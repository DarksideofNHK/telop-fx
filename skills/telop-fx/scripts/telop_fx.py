#!/usr/bin/env python3
"""派手テロップ（決めテロップ）と、文字クリップの後ろに敷く装飾を描く（2026-10-10）。

Premiere の文字クリップ（FCP7 XML）で運べるのは「書体・塗り1色・縁取り1本」と、ネストに付ける拡大・回転・不透明度だけ。
テレビのバラエティ番組のような見た目（縁取り3〜4重・光沢のグラデーション・金属・グロー・立体の影・帯や爆発の台座）と、
1文字ずつの動き・ブラー・ワイプ・色ずれ・残像は運べないので、ここで透明つきの絵・動画にする。使い道は2つ：

  決めテロップ（spec のテロップに "fx"）… 文字ごと焼き込んだ動く透明動画（ProRes 4444）。Premiere では打ち替えられない
      （直すときは spec／手直し.json を直して作り直す）。見せ場だけに使う
  装飾（spec のテロップに "deco"）… 打ち替えられる文字クリップはそのまま、後ろに敷く外側の縁・グロー・影・台座の PNG

型（見た目）と色は別：型は STYLES、色はテロップの行の色（w 白・y 黄・r 赤・p ピンク・o 橙・g 緑・c 水色・b 青・v 紫・k 黒）。
動きは「出方（in）＋出ている間（hold）＋消え方（out）」。気分（MOODS）は 型＋動きのおすすめの組み合わせ。

usage:
  python3 telop_fx.py list                         型・動き・気分の一覧
  python3 telop_fx.py catalog --out 見本フォルダ    見本（型の一覧 PNG・動きの見本動画）
  python3 telop_fx.py render --text 受信料が払えない --color y --fx gloss:slam:shine --out a.mov [--sec 2.5]

ここの型は、どの番組にもある作りの族（光沢・金属・多重の縁・ネオン…）を自分で組んだもので、商品名は付けない。
"""
import argparse
import math
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import COL, KF_MOTIONS, LAYOUTS, PALT, color as tcolor, font_for_ps, kf_motion, safe_rect  # noqa: E402

FEAT = {'features': PALT} if PALT else {}      # Premiere と同じ字詰め（プロポーショナル）。装飾は文字クリップと字の位置を合わせるため必須

SYS = '/System/Library/Fonts/'
# 書体。macOS 同梱のものだけ。assets/fonts/ に置いた書体はファイル名（拡張子なし）で呼べる
FONTS = {'W9': (SYS + 'ヒラギノ角ゴシック W9.ttc', 0), 'W8': (SYS + 'ヒラギノ角ゴシック W8.ttc', 0),
         'W7': (SYS + 'ヒラギノ角ゴシック W7.ttc', 0), 'W6': (SYS + 'ヒラギノ角ゴシック W6.ttc', 0),
         'mincho': (SYS + 'ヒラギノ明朝 ProN.ttc', 2), 'maru': (SYS + 'ヒラギノ丸ゴ ProN W4.ttc', 0)}
PS_FONT = {'HiraginoSans-W9': 'W9', 'HiraginoSans-W8': 'W8', 'HiraginoSans-W7': 'W7', 'HiraginoSans-W6': 'W6',
           'HiraMinProN-W6': 'mincho', 'HiraMaruProN-W4': 'maru'}
FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'
_fc = {}


def fx_font(name, size):
    size = max(8, int(round(size)))
    name = PS_FONT.get(name, name) or 'W9'
    key = (name, size)
    if key not in _fc:
        if name in FONTS:
            path, idx = FONTS[name]
        else:
            hit = [p for p in (list(FONT_DIR.glob(name + '.*')) if FONT_DIR.exists() else []) if p.suffix.lower() in ('.ttf', '.otf', '.ttc')]
            cand = hit[0] if hit else Path(name).expanduser()
            if not cand.exists():
                raise SystemExit(f'telop_fx: 書体「{name}」がない（使えるのは {", ".join(FONTS)}、または assets/fonts/ に置いた書体の名前）')
            path, idx = str(cand), 0
        _fc[key] = ImageFont.truetype(path, size, index=idx)
    return _fc[key]


# ---------------------------------------------------------------- 色
BASE = {'w': (255, 255, 255), 'y': (255, 222, 0), 'r': (238, 28, 36), 'p': (255, 105, 170), 'o': (255, 138, 0),
        'g': (40, 190, 60), 'c': (0, 190, 255), 'b': (30, 110, 255), 'v': (150, 80, 255), 'k': (28, 28, 34)}
COLOR_LABEL = {'w': '白', 'y': '黄', 'r': '赤', 'p': 'ピンク', 'o': '橙', 'g': '緑', 'c': '水色', 'b': '青', 'v': '紫', 'k': '黒'}
WHITE, BLACK, INK = (255, 255, 255), (0, 0, 0), (14, 14, 18)


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def lighten(c, t):
    return mix(c, WHITE, t)


def darken(c, t):
    return mix(c, BLACK, t)


def gloss_fill(C):
    """光沢：上は明るく、真ん中で折り返して濃く、下へ少し暗く"""
    return [(0, lighten(C, .82)), (.46, lighten(C, .30)), (.5, C), (1, darken(C, .30))]


# ---------------------------------------------------------------- 型（見た目）。色 C とキー key から、重ね方の定義を返す
# layers：後ろ→前の縁（w＝字面からの距離・字の大きさに対する割合）。fill：塗り。glows・shadow・extrude・plate：字の下に敷くもの
def st_gloss(C, key):
    if key == 'w':
        return dict(layers=[dict(w=.18, color=(10, 22, 70)), dict(w=.085, grad=[(0, (120, 170, 255)), (1, (40, 80, 210))])],
                    fill=[(0, WHITE), (.46, (238, 243, 255)), (.5, (178, 192, 220)), (1, (244, 247, 255))],
                    glows=[dict(color=(70, 130, 255), r=.22, a=.6)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))
    if key == 'k':
        return dict(layers=[dict(w=.17, color=(250, 250, 250)), dict(w=.07, color=(120, 124, 136))],
                    fill=[(0, (120, 124, 140)), (.46, (60, 62, 74)), (.5, (20, 20, 26)), (1, (52, 54, 64))],
                    glows=[dict(color=WHITE, r=.22, a=.5)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))
    return dict(layers=[dict(w=.18, color=darken(C, .74)), dict(w=.08, color=WHITE)], fill=gloss_fill(C),
                glows=[dict(color=C, r=.22, a=.6)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))


def st_kin(C, key):
    C = {'w': (206, 212, 226), 'y': (255, 196, 20), 'k': (90, 94, 108)}.get(key, C)
    return dict(layers=[dict(w=.19, color=(18, 10, 4)), dict(w=.12, grad=[(0, lighten(C, .75)), (.5, darken(C, .40)), (1, lighten(C, .5))]),
                        dict(w=.05, color=darken(C, .75))],
                fill=[(0, lighten(C, .92)), (.30, lighten(C, .40)), (.47, darken(C, .06)), (.53, darken(C, .42)),
                      (.78, lighten(C, .30)), (1, darken(C, .28))],
                bevel=.4, glows=[dict(color=lighten(C, .2), r=.28, a=.5)], shadow=dict(dx=.03, dy=.055, blur=.04, a=.6))


def st_fuchi(C, key):
    ring = INK if key in ('w', 'k') else C
    return dict(layers=[dict(w=.24, color=INK), dict(w=.17, color=WHITE), dict(w=.10, color=ring)],
                fill=[(0, WHITE), (1, (236, 238, 244))] if key != 'k' else [(0, (255, 232, 60)), (1, (255, 206, 0))],
                shadow=dict(dx=.03, dy=.05, blur=.035, a=.55))


def st_beta(C, key):
    if key == 'w':
        return dict(layers=[dict(w=.15, color=INK)], fill=[(0, WHITE), (1, (232, 234, 240))],
                    extrude=dict(dx=.05, dy=.07, color=(0, 0, 0)), shadow=dict(dx=.06, dy=.09, blur=.03, a=.45))
    return dict(layers=[dict(w=.15, color=WHITE), dict(w=.055, color=darken(C, .8))], fill=[(0, lighten(C, .22)), (1, C)],
                extrude=dict(dx=.05, dy=.07, color=darken(C, .82)), shadow=dict(dx=.06, dy=.09, blur=.03, a=.45))


def st_neon(C, key):
    C = {'w': (120, 220, 255), 'k': (255, 60, 200)}.get(key, C)
    return dict(layers=[dict(w=.05, color=darken(C, .2))], fill=[(0, WHITE), (1, lighten(C, .7))],  # 2026-11-07 夜 読みやすさの直し（ユーザー「解約とか読みづらいものが幾つかある」）：光で字の形が消えていた
                glows=[dict(color=darken(C, .15), r=.09, a=.95, k=2.0), dict(color=C, r=.36, a=.55, k=1.8)])


def st_horror(C, key):
    C = {'w': (236, 236, 240), 'k': (120, 0, 0), 'y': (220, 200, 40)}.get(key, C)
    return dict(font='mincho', bold=.02, layers=[dict(w=.085, color=BLACK)] + ([dict(w=.03, color=(236, 230, 230))] if key != 'w' else []),  # 2026-11-07 夜 読みやすさの直し（ユーザー「解約とか読みづらいものが幾つかある」）：赤い字が暗い背景に沈んでいた
                fill=[(0, lighten(C, .2)), (.55, C), (1, darken(C, .4))],
                glows=[dict(color=BLACK, r=.16, a=1.0, k=2.4), dict(color=darken(C, .35), r=.5, a=.55)])


def st_mincho(C, key):
    C = {'w': (30, 70, 200), 'k': (60, 60, 70)}.get(key, C)
    return dict(font='mincho', bold=.03, layers=[dict(w=.105, grad=[(0, darken(C, .35)), (1, darken(C, .78))])],
                fill=[(0, WHITE), (1, (232, 236, 246))], glows=[dict(color=C, r=.3, a=.6)],
                shadow=dict(dx=.02, dy=.04, blur=.04, a=.6))


def st_kage(C, key):
    return dict(layers=[dict(w=.125, color=BLACK if key != 'k' else WHITE)], fill=[(0, C), (1, C)],
                shadow=dict(dx=.035, dy=.055, blur=.035, a=.7))


def st_obi(C, key):
    light = key in ('w', 'y')
    C2 = (232, 234, 240) if key == 'w' else C
    return dict(layers=[dict(w=.06, color=WHITE if light else darken(C2, .78))],
                fill=[(0, INK), (1, INK)] if light else [(0, WHITE), (1, (240, 242, 248))],
                plate=dict(kind='band', grad=[(0, lighten(C2, .25)), (.5, C2), (1, darken(C2, .42))], pad=(.42, .16), slant=.22,
                           edge=WHITE if not light else INK),
                shadow=dict(dx=.03, dy=.05, blur=.04, a=.55))


def st_burst(C, key):
    T = (232, 22, 30) if key in ('w', 'y') else C
    return dict(layers=[dict(w=.15, color=INK), dict(w=.09, color=WHITE)], fill=[(0, lighten(T, .2)), (1, T)],
                plate=dict(kind='burst', fill=(255, 232, 40), rim=(232, 22, 30), pad=(.5, .55)),
                shadow=dict(dx=.03, dy=.05, blur=.05, a=.5))


def st_fire(C, key):
    if key in ('b', 'c', 'v'):
        return dict(layers=[dict(w=.17, color=(2, 6, 30)), dict(w=.10, color=(14, 40, 150)), dict(w=.045, color=WHITE)],
                    fill=[(0, WHITE), (.4, (160, 232, 255)), (.72, (30, 130, 255)), (1, (12, 36, 170))],
                    glows=[dict(color=(60, 160, 255), r=.3, a=.75)])
    return dict(layers=[dict(w=.17, color=(24, 0, 0)), dict(w=.10, color=(130, 8, 8)), dict(w=.045, color=WHITE)],
                fill=[(0, (255, 252, 190)), (.4, (255, 204, 30)), (.72, (246, 92, 10)), (1, (196, 12, 12))],
                glows=[dict(color=(255, 150, 20), r=.3, a=.75)])


_RAINBOW = ['r', 'o', 'y', 'g', 'c', 'b', 'v', 'p']


def st_rainbow(C, key):
    return dict(layers=[dict(w=.17, color=INK), dict(w=.08, color=WHITE)], fill=gloss_fill(C),
                fill_fn=lambda i: gloss_fill(BASE[_RAINBOW[i % len(_RAINBOW)]]),
                shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))


# ---- グロー系の見本（2026-11-06。バラエティのテロップ素材集の見本動画から、作りの族だけを写した。素材・商品名は使わない）
# 2026-11-07 職員と学歴編で NHK 系では使わないことにした（白く光る・金で字がにじむ＝check_spec が △・カタログは「NHK では使わない」）
def soft_fill(C):
    """やわらかい縦のグラデーション：上を明るく・下を少し濃く（折り返しなし）"""
    return [(0, lighten(C, .45)), (.5, C), (1, darken(C, .30))]


def st_kinmin(C, key):
    """金の明朝：金の照り＋こげ茶の縁＋クリームの外縁＋金色の光（「本日の〜」のような特別・豪華）。w なら銀"""
    G = (206, 212, 226) if key == 'w' else (255, 196, 20)
    return dict(font='mincho', bold=.012,
                layers=[dict(w=.15, color=(255, 246, 176)), dict(w=.095, color=(66, 36, 6)), dict(w=.035, color=darken(G, .5))],
                fill=[(0, lighten(G, .92)), (.32, lighten(G, .45)), (.5, darken(G, .05)), (.56, darken(G, .38)),
                      (.8, lighten(G, .25)), (1, darken(G, .35))],
                glows=[dict(color=(255, 226, 90), r=.26, a=.75)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))


def st_hikari(C, key):
    """光る明朝：色の字＋白い縁＋濃い細い縁＋太い光る外縁（既定は黄。fx の glow で色を替える）"""
    F = [(0, WHITE), (1, (232, 236, 244))] if key == 'w' else soft_fill(C)
    return dict(font='mincho', bold=0, fill=F,  # 2026-11-07 夜 読みやすさの直し（ユーザー「解約とか読みづらいものが幾つかある」）：字の中が埋まっていた
                layers=[dict(w=.155, color=(255, 238, 40)), dict(w=.095, color=(22, 24, 56)), dict(w=.052, color=WHITE)],
                glows=[dict(color=(255, 230, 0), r=.24, a=.9)], shadow=dict(dx=.02, dy=.04, blur=.03, a=.45))


def st_shiromin(C, key):
    """白縁の明朝：色の字＋白い縁＋濃い細い縁＋白い光（新事実・対決。skew を付けると勢いが出る）"""
    F = [(0, WHITE), (1, (226, 230, 240))] if key == 'w' else soft_fill(C)
    if key == 'k':      # 黒い字は濃い縁が背景に沈むので、白い縁を外に（2026-11-07 点検：kakumei の「に」「が!」が読みにくかった）
        return dict(font='mincho', bold=0, fill=[(0, (56, 56, 66)), (1, (14, 14, 20))],
                    layers=[dict(w=.10, color=WHITE)],
                    glows=[dict(color=(255, 250, 225), r=.22, a=.8)], shadow=dict(dx=.03, dy=.05, blur=.03, a=.5))
    return dict(font='mincho', bold=0, fill=F,  # 2026-11-07 夜 読みやすさの直し（ユーザー「解約とか読みづらいものが幾つかある」）：字の中が埋まっていた
                layers=[dict(w=.088, color=(34, 34, 44)), dict(w=.052, color=WHITE)],
                glows=[dict(color=(255, 250, 225), r=.22, a=.8)], shadow=dict(dx=.03, dy=.05, blur=.03, a=.5))


def st_pop(C, key):
    """太いゴシック＋濃い縁＋クリームの外縁＋黄色い光（発表・達成）"""
    F = [(0, WHITE), (1, (232, 236, 244))] if key == 'w' else [(0, lighten(C, .40)), (.45, lighten(C, .12)), (1, darken(C, .22))]
    return dict(layers=[dict(w=.15, color=(255, 246, 180)), dict(w=.075, color=(92, 72, 14))], fill=F,
                glows=[dict(color=(255, 236, 70), r=.24, a=.75)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))


def st_hako(C, key):
    """黄色い板：黄→橙の四角い台座に、縁なしの色の字（既定の色は紫。「しんどい〜」のような小見出し）"""
    T = (140, 20, 190) if key in ('w', 'y', 'v') else C
    return dict(layers=[dict(w=.025, color=darken(T, .45))], fill=[(0, lighten(T, .18)), (1, darken(T, .12))],
                plate=dict(kind='rect', grad=[(0, (252, 252, 80)), (.45, (250, 238, 48)), (1, (234, 150, 18))], pad=(.42, .20),
                           edge=(150, 90, 0)),
                shadow=dict(dx=.02, dy=.035, blur=.02, a=.35))


# ---- バラエティの字幕型（2026-11-07。バラエティ番組の字幕テロップから、縁の重ね方と色の族だけを写した。番組の素材・マスコット・書体は使わない）
#  どれも出方は cut（パッと出る）。元の番組も 30 コマ/秒で見て動きなし
_SUB_SHADOW = dict(dx=.035, dy=.055, blur=.008, a=.75)          # 固い落ち影（右下）


def st_jimaku(C, key):
    """字幕：W9 の字＋縁＋固い落ち影。白い字は黒い縁（fx の edge で話し手の色の縁）。色の字は白い縁＋黒い外縁（行の中の強調は paint）"""
    sp = dict(track=.05, row_gap=.2)  # 11-07 夜：縁が隣の字・下の行にかぶっていた（ユーザー「jimaku は重なってるのがダメ」）
    if key == 'w':
        return dict(layers=[dict(w=.105, color=INK)], fill=[(0, WHITE), (1, (240, 240, 244))], shadow=_SUB_SHADOW,
                    edge_fn=lambda E: dict(layers=[dict(w=.125, color=E)]), **sp)
    F = [(0, (255, 248, 160)), (1, (255, 212, 0))] if key == 'y' else [(0, lighten(C, .1)), (1, darken(C, .08))]
    return dict(layers=[dict(w=.14, color=INK), dict(w=.09, color=WHITE)], fill=F, shadow=_SUB_SHADOW, **sp)


def st_dekai(C, key):
    """大きな長体：横を詰めた W9（cond）＋黒い縁＋黒いにじみ（本音・詰め寄る一言を画面いっぱいに。fx の big と組む）"""
    F = {'w': [(0, WHITE), (1, (234, 234, 240))], 'r': [(0, (255, 36, 28)), (1, (214, 0, 0))]}.get(
        key, [(0, lighten(C, .08)), (1, darken(C, .12))])
    if key == 'k':      # 黒い字：黒い縁では背景に沈む＝白い縁（2026-11-07 点検）
        return dict(cond=.58, layers=[dict(w=.075, color=WHITE)], fill=[(0, (60, 60, 70)), (1, (12, 12, 16))],
                    glows=[dict(color=WHITE, r=.08, a=.5)], shadow=dict(dx=.02, dy=.04, blur=.03, a=.6))
    if key in ('b', 'v', 'r'):   # 暗い色：黒い縁の内側に白い細縁（暗い背景でも字の形が立つ。赤は 11-07 夜に足した）
        return dict(cond=.58, layers=[dict(w=.10, color=BLACK), dict(w=.045, color=WHITE)], fill=F,
                    glows=[dict(color=BLACK, r=.10, a=.85, k=2.0)], shadow=dict(dx=.02, dy=.04, blur=.03, a=.6))
    return dict(cond=.58, layers=[dict(w=.075, color=BLACK)], fill=F,
                glows=[dict(color=BLACK, r=.10, a=.85, k=2.0)], shadow=dict(dx=.02, dy=.04, blur=.03, a=.6))


def st_tsuyo(C, key):
    """強調：上が淡い色の字＋白い縁＋同じ色の濃い外縁（固有名詞・「〜で」の一言を目立たせる。w は橙）"""
    C = {'w': (255, 138, 0), 'y': (255, 176, 0)}.get(key, C)
    return dict(layers=[dict(w=.19, grad=[(0, darken(C, .18)), (1, darken(C, .38))]), dict(w=.075, color=WHITE)],
                fill=[(0, lighten(C, .40)), (.5, lighten(C, .06)), (1, darken(C, .10))], glows=[dict(color=C, r=.06, a=.45)],
                shadow=dict(dx=.02, dy=.04, blur=.04, a=.4))


def st_geki(C, key):
    """劇画の明朝：太らせた明朝を少し縦長に（cond）＋黒い縁＋黒いにじみ（独白・迫る問い）"""
    F = {'w': [(0, WHITE), (1, (230, 230, 236))], 'r': [(0, (255, 24, 20)), (1, (212, 0, 0))]}.get(
        key, [(0, lighten(C, .05)), (1, darken(C, .15))])
    if key == 'k':
        return dict(font='mincho', bold=.012, cond=.64, layers=[dict(w=.065, color=WHITE)], fill=[(0, (60, 60, 70)), (1, (12, 12, 16))],
                    glows=[dict(color=WHITE, r=.08, a=.45)], shadow=dict(dx=.02, dy=.035, blur=.03, a=.55))
    if key in ('b', 'v'):
        return dict(font='mincho', bold=.012, cond=.64, layers=[dict(w=.09, color=BLACK), dict(w=.04, color=WHITE)], fill=F,
                    glows=[dict(color=BLACK, r=.08, a=.7, k=1.8)], shadow=dict(dx=.02, dy=.035, blur=.03, a=.55))
    return dict(font='mincho', bold=.012, cond=.64, layers=[dict(w=.065, color=BLACK)], fill=F,
                glows=[dict(color=BLACK, r=.08, a=.7, k=1.8)], shadow=dict(dx=.02, dy=.035, blur=.03, a=.55))


def st_waku(C, key):
    """枠の板：黄色い太枠の黄緑の板に色の字（ナレーション・心の声の短い一言。既定の字は赤）"""
    T = (230, 14, 14) if key in ('w', 'y', 'g') else C
    ink = [] if key in ('w', 'y', 'g', 'r', 'k') else [dict(w=.055, color=INK)]    # 淡い色の字は板と近い＝濃い細縁（2026-11-07 点検）
    return dict(fill=[(0, lighten(T, .08)), (1, darken(T, .1))], layers=ink,
                plate=dict(kind='round', fill=(164, 250, 150), edge=(250, 200, 30), ew=.09, r=.07, pad=(.62, .38)),
                shadow=dict(dx=.015, dy=.03, blur=.02, a=.3))


def st_waku_ao(C, key):
    """見出しの板：黄色い太枠の水色の板に黒い字（2行目を赤にすると企画の見出し）"""
    T = INK if key in ('w', 'k', 'c') else C
    ink = [] if key in ('w', 'k', 'c', 'r') else [dict(w=.055, color=INK)]
    return dict(fill=[(0, lighten(T, .08)), (1, darken(T, .1))], layers=ink,
                plate=dict(kind='round', fill=(96, 204, 244), edge=(250, 214, 40), ew=.09, r=.05, pad=(.9, .3)),
                shadow=dict(dx=.015, dy=.03, blur=.02, a=.25))


# ---- ニュース風（2026-11-07。テレビのニュース特集の街頭インタビューのテロップから、作りの族だけを写した。番組名・局の飾りは使わない）
#  fx の edge が「色の要」：字幕＝話し手の縁、帯＝帯の色、札＝字とタブの色。tag で帯の左上の札（「妻」）・札の上のタブ（「料金」）
_NAVY = (24, 44, 128)


def st_news_jimaku(C, key):
    """インタビュー字幕：白い字＋話し手の色の縁（edge・既定は紺）＋濃い外縁。要の語は paint（黄・緑の字）か box_words（色の箱）"""
    dark = key in ('b', 'v', 'k')          # 暗い色の字は縁の色に沈む＝縁の内側に白い細縁（2026-11-07 点検）

    def edge(E):
        return dict(layers=[dict(w=.15, color=darken(E, .55)), dict(w=.105, color=E)] + ([dict(w=.05, color=WHITE)] if dark else []))
    F = ([(0, WHITE), (1, (236, 238, 244))] if key == 'w' else [(0, (70, 70, 80)), (1, (16, 16, 22))] if key == 'k'
         else [(0, lighten(C, .25)), (1, C)])
    d = dict(fill=F, shadow=dict(dx=.025, dy=.04, blur=.02, a=.55), edge_fn=edge)
    d.update(edge(_NAVY))
    return d


def st_news_obi(C, key):
    """見出しの帯：横いっぱいのグラデーションの帯（edge の色・既定は緑）に白い字＋黒い縁。要の語は paint の黄"""
    def band(E):
        return dict(plate=dict(kind='band', full=True, slant=0, pad=(.5, .2), edge=lighten(E, .65),
                               grad=[(0, lighten(E, .55)), (.42, lighten(E, .12)), (1, darken(E, .22))],
                               tag_fill=WHITE, tag_ink=darken(E, .15), tag_edge=(250, 200, 30), tag_kind='bubble'))
    F = [(0, (255, 240, 60)), (1, (255, 214, 0))] if key == 'y' else [(0, WHITE), (1, (236, 238, 244))]
    d = dict(layers=[dict(w=.11, color=INK)], fill=F, shadow=dict(dx=.02, dy=.04, blur=.02, a=.5), edge_fn=band)
    d.update(band(BASE['g']))
    return d


def st_news_tsuyo(C, key):
    """大きな強調：濃い色の字＋白い太縁＋同じ色の濃い外縁（「大興奮」のような一言。w は白い字＋黒い縁）"""
    if key == 'w':
        return dict(layers=[dict(w=.12, color=INK)], fill=[(0, WHITE), (1, (232, 234, 240))],
                    shadow=dict(dx=.03, dy=.05, blur=.03, a=.55))
    if key in ('y', 'c'):                  # 淡い色は白い縁と近い＝内側に濃い細縁を挟む（2026-11-07 点検）
        return dict(layers=[dict(w=.17, color=darken(C, .5)), dict(w=.115, color=WHITE), dict(w=.04, color=darken(C, .55))],
                    fill=[(0, lighten(C, .12)), (1, darken(C, .1))], glows=[dict(color=lighten(C, .3), r=.12, a=.45)],
                    shadow=dict(dx=.03, dy=.05, blur=.03, a=.45))
    return dict(layers=[dict(w=.17, color=darken(C, .45)), dict(w=.115, color=WHITE)],
                fill=[(0, lighten(C, .12)), (1, darken(C, .1))], glows=[dict(color=lighten(C, .3), r=.12, a=.45)],
                shadow=dict(dx=.03, dy=.05, blur=.03, a=.45))


def st_news_fuda(C, key):
    """情報の札：白い板に色の字（edge の色・既定は青）。tag で板の上のタブ（「料金」）"""
    def ink(E):
        return dict(fill=[(0, lighten(E, .05)), (1, darken(E, .12))],
                    plate=dict(kind='round', fill=WHITE, edge=E, ew=.035, r=.03, pad=(.35, .14),
                               tag_fill=E, tag_ink=WHITE, tag_edge=darken(E, .3), tag_kind='tab'))
    d = dict(shadow=dict(dx=.02, dy=.035, blur=.02, a=.35), edge_fn=ink)
    d.update(ink((30, 90, 210)))
    if key not in ('w', 'b'):                       # 行の色で字の色を替える（タブと枠は edge のまま）。白い板で淡い色は読めないので濃くする
        C = darken(C, .28) if key in ('y', 'c', 'p', 'o', 'g') else C
        d['fill'] = [(0, lighten(C, .05)), (1, darken(C, .12))]
    return d


def st_kaiten(C, key):
    """3D 回転（柱の面に字）。決めテロップでは Kaiten が立体で描く。ここは装飾（文字クリップの後ろ）用の平らな形"""
    return dict(layers=[dict(w=.12, color=darken(KAITEN_PANEL.get(key, C), .55))], fill=[(0, WHITE), (1, (232, 236, 244))],
                shadow=dict(dx=.03, dy=.05, blur=.03, a=.5))


# 3D 回転の面の色（行の色キー → 面の地の色。字はいつも白＋濃い縁）
KAITEN_PANEL = {'w': (34, 54, 140), 'y': (232, 150, 0), 'r': (214, 18, 40), 'p': (226, 60, 140), 'o': (236, 104, 0),
                'g': (18, 146, 64), 'c': (0, 146, 206), 'b': (28, 78, 214), 'v': (116, 56, 206), 'k': (34, 34, 44)}


# ---- バラエティ風 その2（2026-11-07。トーク番組の主張の札・大小と色を混ぜた字幕・出演者の名札から、作りの族だけを写した）
def st_bara(C, key):
    """バラエティの字幕：黒＝白い縁＋青い光／青・赤・紫・水色＝白から色のグラデーションの字＋色の縁＋白い外縁／
    黄・橙・ピンク・緑＝べたの色の字＋白い縁＋黒い外縁／白＝白い字＋黒い縁。語ごとの色は paint、大きさは size_words"""
    sh = dict(dx=.03, dy=.05, blur=.03, a=.5)
    if key == 'k':
        return dict(layers=[dict(w=.11, color=WHITE, fill_holes=True)], fill=[(0, (40, 40, 48)), (1, (6, 6, 10))],
                    glows=[dict(color=(60, 120, 255), r=.2, a=.95, k=1.6)], shadow=sh)   # 輪の中に青い光が透けないよう穴を埋める
    if key == 'w':
        return dict(layers=[dict(w=.12, color=INK)], fill=[(0, WHITE), (1, (232, 236, 244))], shadow=sh)
    if key in ('b', 'r', 'v', 'c'):
        C = {'r': (226, 40, 90)}.get(key, C)
        return dict(layers=[dict(w=.16, color=WHITE), dict(w=.085, color=darken(C, .3))],
                    fill=[(0, WHITE), (.35, lighten(C, .75)), (1, lighten(C, .1))], shadow=dict(dx=.03, dy=.05, blur=.05, a=.55))
    C = {'o': (240, 120, 10)}.get(key, C)
    return dict(layers=[dict(w=.17, color=INK), dict(w=.105, color=WHITE)], fill=[(0, lighten(C, .1)), (1, darken(C, .08))], shadow=sh)


def st_shuchou(C, key):
    """主張の札：黒紫の六角の板＋光る緑の縁＋左右の紫の六角の飾り＋上の紫の名前のタブ（tag）。字は白、2行目を黄に"""
    F = ([(0, (255, 244, 120)), (1, (240, 200, 0))] if key == 'y' else [(0, lighten(C, .5)), (1, lighten(C, .2))] if key not in ('w', 'k')
         else [(0, WHITE), (1, (236, 236, 242))])          # 色の字は明るめに（暗い板に沈まないように・2026-11-07 点検）
    return dict(font='W7', fill=F, shadow=dict(dx=.02, dy=.04, blur=.02, a=.5),
                plate=dict(kind='hexpanel', fill=[(0, (46, 22, 64)), (.5, (22, 10, 34)), (1, (10, 4, 18))], edge=(110, 236, 70),
                           deco=(150, 70, 220), pad=(.75, .55), tag_fill=(126, 52, 196), tag_ink=WHITE, tag_edge=(190, 150, 240),
                           tag_kind='tab'))


NAFUDA = {'w': (126, 52, 196), 'r': (214, 40, 30), 'p': (232, 80, 160), 'g': (30, 140, 50), 'b': (30, 90, 210),
          'o': (234, 110, 0), 'c': (0, 150, 200), 'v': (126, 52, 196), 'y': (200, 150, 0), 'k': (40, 40, 50)}


def st_nafuda(C, key):
    """出演者の名札：両端のとがった色の札（行の色）に白い字。前の小さい語（コンビ名）は size_words"""
    P = NAFUDA.get(key, NAFUDA['v'])
    return dict(fill=[(0, WHITE), (1, (240, 240, 246))], layers=[dict(w=.03, color=darken(P, .4))],
                plate=dict(kind='hexpill', fill=[(0, lighten(P, .2)), (.5, P), (1, darken(P, .2))], edge=(255, 226, 120), pad=(.5, .16)),
                shadow=dict(dx=.015, dy=.03, blur=.02, a=.3))

# ---- 街頭インタビュー風（2026-11-07。深夜バラエティの街頭インタビューの切り抜きから、縁の重ね方と色の族だけを写した。
#      番組名・ロゴ・出演者の顔のアイコン・桜の額は使わない）。どれも出方は cut（30 コマ/秒で見て動きなし）。
#      元の作り：言い切りの一言＝太い明朝の色のグラデ＋白い縁＋濃い外縁＋厚み、白い一言＝太いゴシック＋黒い縁、
#      要の語だけ色＝paint（白い字の中の語を紫に）、2 色の一言（前半の色と後半の色）＝paint
_GT_LIME = (196, 240, 40)


def _gt_color(C, key):
    return {'r': (232, 20, 30), 'y': (255, 214, 0), 'g': (30, 170, 50), 'o': (250, 110, 10)}.get(key, C)


def _gt_colored(C, key, font):
    """色の字：縦のグラデ（上が淡い）＋濃い細縁＋白い縁＋同じ色の濃い外縁＋右下の厚み＋暗いにじみ"""
    C = _gt_color(C, key)
    if key == 'k':
        return dict(font=font, bold=0, track=.05, row_gap=.16, layers=[dict(w=.11, color=(8, 8, 12)), dict(w=.064, color=WHITE)],
                    fill=[(0, (84, 84, 96)), (1, (14, 14, 20))], glows=[dict(color=WHITE, r=.1, a=.4)],
                    shadow=dict(dx=.03, dy=.06, blur=.04, a=.5))
    return dict(font=font, bold=0, cond=1.0 if font == 'mincho' else .94, track=.05, row_gap=.16,  # 11-07 夜：縁が隣の字・下の行にかぶっていた（ユーザー「jimaku は重なってるのがダメ」）
                 # 2026-11-07 夜 読みやすさの直し（ユーザー「解約とか読みづらいものが幾つかある」）：「解約」の字の中が埋まっていた
                layers=[dict(w=.11, color=darken(C, .62)), dict(w=.064, color=WHITE)],
                fill=[(0, lighten(C, .3)), (.5, C), (1, darken(C, .25))],
                extrude=dict(dx=.016, dy=.035, color=darken(C, .7)),
                glows=[dict(color=darken(C, .5), r=.09, a=.65, k=1.5)], shadow=dict(dx=.03, dy=.06, blur=.04, a=.5))


def st_gaitou(C, key):
    """色の太明朝：太らせた明朝の色のグラデ＋白い縁＋濃い外縁＋厚み（言い切りの一言）。白は白い字＋黒い縁＋黒いにじみ"""
    if key == 'w':
        return dict(font='mincho', bold=0, track=.05, row_gap=.16, layers=[dict(w=.1, color=INK)], fill=[(0, WHITE), (1, (226, 228, 236))],
                    glows=[dict(color=BLACK, r=.12, a=.7, k=1.6)], shadow=dict(dx=.03, dy=.05, blur=.03, a=.6))
    return _gt_colored(C, key, 'mincho')


def st_gaitou_go(C, key):
    """太いゴシック：白い字＋黒い太縁＋黒いにじみ（本音の一言）。色の字は太明朝と同じ重ね方"""
    if key == 'w':
        return dict(cond=.94, track=.05, row_gap=.16, layers=[dict(w=.12, color=INK)], fill=[(0, WHITE), (1, (222, 224, 232))],
                    glows=[dict(color=BLACK, r=.14, a=.75, k=1.6)], shadow=dict(dx=.03, dy=.05, blur=.03, a=.6))
    return _gt_colored(C, key, 'W9')


def st_gaitou_sub(C, key):
    """話し言葉の字幕：中くらいのゴシックの色の字＋白い細縁＋同じ色の光。白い字は edge の色の縁と光、黄は黒い細縁だけ"""
    sh = dict(dx=.02, dy=.035, blur=.02, a=.45)
    if key == 'y':
        return dict(font='W7', layers=[dict(w=.09, color=INK)], fill=[(0, (255, 250, 150)), (1, (255, 226, 0))], shadow=sh)
    if key in ('w', 'k'):
        def edge(E):
            return dict(layers=[dict(w=.1, color=E)], glows=[dict(color=E, r=.14, a=.85)])
        d = dict(font='W7', fill=[(0, WHITE), (1, (236, 238, 246))] if key == 'w' else [(0, (70, 70, 80)), (1, (16, 16, 22))],
                 layers=[dict(w=.09, color=INK if key == 'w' else WHITE)], shadow=sh, edge_fn=edge)
        return d
    C = _gt_color(C, key)               # 濃い外縁はつけない（字幕の大きさだと字がつぶれる）＝白い細縁＋同じ色の光
    return dict(font='W7', layers=[dict(w=.1, color=darken(C, .5)), dict(w=.06, color=WHITE)],  # 2026-11-07 夜 読みやすさの直し（ユーザー「解約とか読みづらいものが幾つかある」）：光が字の形を消していた＝光は字より暗く
                fill=[(0, lighten(C, .12)), (1, darken(C, .1))], glows=[dict(color=darken(C, .25), r=.12, a=.7, k=1.3)], shadow=sh)


def st_gaitou_staff(C, key):
    """スタッフの問い：白い字＋黒い細縁（小さく）・答えの行は黄などの色。左上に黒い札（tag＝「スタッフ」）"""
    F = ([(0, WHITE), (1, (236, 238, 246))] if key in ('w', 'k') else [(0, (255, 250, 150)), (1, (255, 226, 0))] if key == 'y'
         else [(0, lighten(C, .2)), (1, C)])
    return dict(font='W7', layers=[dict(w=.1, color=INK)], fill=F, shadow=dict(dx=.02, dy=.035, blur=.02, a=.5),
                scale=.74 if key in ('w', 'k') else 1.0,       # 問い（白）は小さく・答え（色）は大きく
                plate=dict(kind='none', pad=(.1, .12), tag_fill=INK, tag_ink=WHITE, tag_edge=WHITE, tag_kind='tab', tag_r=0, tag_size=.6))


def st_gaitou_obi(C, key):
    """紺の帯：横いっぱいの暗い紺の帯に黄色い太字＋黒い細縁（「〜騒動」の見出し）"""
    F = ([(0, WHITE), (1, (236, 238, 246))] if key in ('w', 'k') else [(0, (255, 250, 120)), (1, (255, 230, 0))] if key == 'y'
         else [(0, lighten(C, .3)), (1, C)])
    return dict(layers=[dict(w=.07, color=INK)], fill=F, shadow=dict(dx=.02, dy=.04, blur=.02, a=.5),
                plate=dict(kind='bar', full=True, fill=[(0, (34, 40, 92)), (.5, (16, 20, 56)), (1, (6, 8, 28))], alpha=.94, pad=(.4, .24)))


def st_gaitou_q(C, key):
    """問いの板：白い角丸の板＋灰色の枠に黒い字（「Q.〜は？」）。要の語は paint の赤"""
    T_ = INK if key in ('w', 'k') else {'r': (220, 24, 30)}.get(key, darken(C, .2))
    return dict(font='W7', fill=[(0, T_), (1, T_)],
                plate=dict(kind='round', fill=WHITE, edge=(70, 70, 82), ew=.06, r=.16, pad=(.55, .3)),
                shadow=dict(dx=.015, dy=.03, blur=.02, a=.3))


def st_gaitou_kado(C, key):
    """1字ずつの箱の題名：黒い帯の上に、1字ずつ黒い枠の箱（白）に黒い字。要の語は paint で箱の色（緑＝黄緑）"""
    B = WHITE if key in ('w', 'k') else _GT_LIME if key == 'g' else lighten(C, .1)
    return dict(font='W7', track=.16, fill=[(0, INK), (1, INK)], char_box=B,
                plate=dict(kind='bar', fill=[(0, (30, 30, 34)), (1, (8, 8, 10))], alpha=.9, pad=(.3, .18)))


# ---- ニュース・情報番組のパロディ用（2026-11-07。局の速報・ニュースの帯・解説番組・朝の情報番組の画面から、作りの族と色だけを写した。
#      局や番組のロゴ・番組名・時計は描かない。局名などの文字が要るときは spec に普通の字で書く）
_NAVY2 = (22, 40, 120)


def st_news_flash(C, key):
    """速報の字：白い字＋黒い太縁＋落ち影（画面の上に 2 行）"""
    F = [(0, WHITE), (1, (236, 238, 244))] if key in ('w', 'k') else [(0, lighten(C, .1)), (1, C)]
    return dict(layers=[dict(w=.13, color=INK)], fill=F, shadow=dict(dx=.04, dy=.06, blur=.05, a=.7))


def st_news_flash_head(C, key):
    """速報の見出し：斜めの白い字＋黒い縁＋上下の 2 本の線（「ニュース速報」）"""
    return dict(skew=.16, layers=[dict(w=.11, color=INK)], fill=[(0, WHITE), (1, (236, 238, 244))],
                plate=dict(kind='lines2', pad=(.25, .12)), shadow=dict(dx=.04, dy=.06, blur=.05, a=.6))


def st_news_head(C, key):
    """ニュースの見出しの帯：横いっぱいの白い帯（上に青い縁）に黒い字・要の語は赤（paint）。上に青いタブ（tag）"""
    T_ = {'r': (214, 36, 24), 'b': (20, 80, 200)}.get(key, INK)
    return dict(fill=[(0, T_), (1, T_)],
                plate=dict(kind='bar', full=True, fill=[(0, WHITE), (.8, (244, 245, 248)), (1, (214, 218, 226))], top=(30, 80, 200),
                           top_w=.08, pad=(.4, .26), tag_fill=(30, 80, 200), tag_ink=WHITE, tag_edge=(30, 80, 200), tag_kind='tab', tag_r=0))


def st_news_cap(C, key):
    """ニュースの字幕の帯：半透明の暗い帯に白い字（2 行）。左上に青い札（tag）と白い札（tag2）"""
    F = [(0, WHITE), (1, (236, 238, 244))] if key in ('w', 'k') else [(0, lighten(C, .2)), (1, C)]
    return dict(fill=F, shadow=dict(dx=.02, dy=.03, blur=.02, a=.6),
                plate=dict(kind='bar', full=True, fill=[(0, (34, 38, 50)), (1, (16, 18, 26))], alpha=.78, pad=(.4, .2),
                           tag_fill=(30, 80, 200), tag_ink=WHITE, tag_edge=(30, 80, 200), tag_kind='tab', tag_r=0,
                           tag2_fill=WHITE, tag2_ink=INK, tag2_edge=(30, 80, 200)))


def st_news_corner(C, key):
    """右上の札：白い板に黒い字・2 行目を赤（行の色）。fx の align で右に寄せる"""
    T_ = {'r': (214, 36, 24), 'b': (20, 80, 200)}.get(key, INK)
    return dict(fill=[(0, T_), (1, T_)], plate=dict(kind='bar', fill=[(0, WHITE), (1, (240, 241, 245))], edge=(190, 194, 204), pad=(.3, .14)))


def st_news_basho(C, key):
    """場所の札：黒い板に白い小さな字（右上・align r）"""
    return dict(fill=[(0, WHITE), (1, (236, 238, 244))], plate=dict(kind='bar', fill=[(0, (30, 30, 36)), (1, (10, 10, 14))], alpha=.85, pad=(.3, .12)))


def st_kaisetsu(C, key):
    """解説番組の見出し：行ごとの斜めの帯。白の行＝紺の帯に白い字／黒の行＝白い帯に紺の大きな字（要の語は paint の赤）。左上に星形の札（tag）"""
    burst = dict(tag_fill=(255, 220, 30), tag_ink=_NAVY2, tag_edge=(230, 150, 0), tag_kind='burst')
    if key in ('k', 'b'):
        return dict(layers=[dict(w=.08, color=WHITE)], fill=[(0, lighten(_NAVY2, .2)), (1, _NAVY2)],
                    plate=dict(kind='band', per_line=True, slant=.35, grad=[(0, WHITE), (.6, (238, 238, 244)), (1, (200, 204, 220))],
                               edge=(200, 30, 40), pad=(.5, .1), **burst), shadow=dict(dx=.02, dy=.04, blur=.03, a=.4))
    if key == 'r':
        return dict(layers=[dict(w=.08, color=WHITE)], fill=[(0, (236, 44, 40)), (1, (190, 16, 20))],
                    plate=dict(kind='band', per_line=True, slant=.35, grad=[(0, WHITE), (1, (200, 204, 220))], edge=(200, 30, 40), pad=(.5, .1),
                               **burst), shadow=dict(dx=.02, dy=.04, blur=.03, a=.4))
    return dict(fill=[(0, WHITE), (1, (232, 236, 246))],
                plate=dict(kind='band', per_line=True, slant=.35, grad=[(0, lighten(_NAVY2, .25)), (.5, _NAVY2), (1, darken(_NAVY2, .3))],
                           edge=WHITE, pad=(.5, .14), **burst), shadow=dict(dx=.02, dy=.04, blur=.03, a=.4))


_PINK = (232, 72, 120)


def st_jouhou_title(C, key):
    """朝の情報番組の題名：行ごとのピンクの縁の白い札（丸い端）に黒い字・要の語は赤（paint）"""
    T_ = {'r': (220, 30, 60)}.get(key, INK)
    return dict(fill=[(0, T_), (1, T_)], plate=dict(kind='round', per_line=True, fill=WHITE, edge=_PINK, ew=.07, r=.6, pad=(.55, .16)),
                shadow=dict(dx=0, dy=.02, blur=.02, a=.15))


def st_jouhou_name(C, key):
    """朝の情報番組の名前の札：ピンクの縁の白い札に黒い大きな名前、上にピンクのタブ（tag＝所属）、左に色の縦じま"""
    return dict(fill=[(0, INK), (1, INK)],
                plate=dict(kind='round', fill=WHITE, edge=_PINK, ew=.06, r=.18, pad=(.6, .22),
                           stripe=[(250, 210, 40), (226, 50, 50), (40, 160, 90), (232, 72, 120)],
                           tag_fill=_PINK, tag_ink=WHITE, tag_edge=_PINK, tag_kind='tab', tag_r=0), shadow=dict(dx=0, dy=.02, blur=.02, a=.15))


# ---- 選挙特番の題字（2026-11-07。NHK の「衆議院解散」の題字の年ごとの変遷＝2005〜2026 年の 8 つから、作りの族と色だけを写した）
#      行の色は使わない（年ごとに色が決まっている）。書体は W9／W8 と明朝で代用
_GOLD_FOLD = [(0, (255, 250, 210)), (.3, (255, 226, 120)), (.48, (236, 180, 40)), (.53, (170, 110, 10)), (.8, (240, 196, 70)), (1, (150, 96, 10))]


_SILVER_FOLD = [(0, WHITE), (.45, (226, 230, 238)), (.52, (160, 166, 180)), (.8, (230, 234, 242)), (1, (180, 186, 198))]


def _metal(C):
    """色の金属（照りの折り返し）：上は白く、真ん中で折り返して濃く"""
    return [(0, WHITE), (.45, lighten(C, .55)), (.52, darken(C, .25)), (.8, lighten(C, .45)), (1, darken(C, .15))]


def _tok_recolor(d, key, C, gold=True):
    """題字の色替え（2026-11-07）：黄＝元のまま／白＝銀の字（金の年）／ほかの色＝その色の光と外側の縁"""
    if key == 'y':
        return d
    if key == 'w':
        if gold:
            d['fill'] = _SILVER_FOLD
            d['layers'] = [dict(l, color=(24, 24, 30)) if l is d['layers'][0] else dict(l, color=(150, 156, 170)) for l in d['layers']]
            if d.get('extrude'):
                d['extrude'] = dict(d['extrude'], color=(26, 26, 32))
        return d
    d['layers'] = [dict(d['layers'][0], color=darken(C, .62))] + d['layers'][1:]
    d['glows'] = [dict(color=C, r=.26, a=.85)]
    return d


def st_tokuban_2005(C, key):
    """2005：銀のゴシック（照りの折り返し）＋黒い縁＋立体の影（色を指定するとその色の金属）"""
    return dict(font='W8', layers=[dict(w=.1, color=(20, 20, 26) if key in ('w', 'y') else darken(C, .7))],
                fill=_SILVER_FOLD if key in ('w', 'y') else _metal(C),
                bevel=.3, extrude=dict(dx=.03, dy=.05, color=(30, 30, 38)), shadow=dict(dx=.05, dy=.08, blur=.05, a=.6))


def st_tokuban_2009(C, key):
    """2009：金の太いゴシック（照りの折り返し）＋こげ茶の縁＋黒い立体の厚み"""
    return _tok_recolor(dict(layers=[dict(w=.08, color=(60, 30, 0))], fill=_GOLD_FOLD, bevel=.45,
                             extrude=dict(dx=.04, dy=.07, color=(26, 14, 0)), shadow=dict(dx=.05, dy=.09, blur=.05, a=.65)), key, C)


def st_tokuban_2012(C, key):
    """2012：金の太いゴシック・字の間を広く＋黒い厚み（2009 より明るい金）"""
    return _tok_recolor(dict(track=.12, layers=[dict(w=.07, color=(70, 40, 0))],
                             fill=[(0, (255, 252, 220)), (.3, (255, 232, 130)), (.5, (240, 190, 50)), (.55, (190, 128, 20)),
                                   (.85, (250, 210, 90)), (1, (170, 110, 20))], bevel=.5,
                             extrude=dict(dx=.05, dy=.08, color=(10, 6, 0)), shadow=dict(dx=.06, dy=.1, blur=.05, a=.7)), key, C)


def st_tokuban_2014(C, key):
    """2014：黄から白のグラデーションの字＋紺の縁＋白い外縁＋青い光（色を指定すると縁と光がその色）"""
    E = (20, 40, 120) if key in ('y', 'b', 'w') else darken(C, .55)
    G = (50, 130, 255) if key in ('y', 'b') else ((150, 180, 240) if key == 'w' else C)     # 白は淡い青の光（白い光だと字がぼやける）
    F = ([(0, (226, 244, 80)), (.55, (244, 250, 150)), (1, (255, 255, 214))] if key != 'w'
         else [(0, (226, 232, 246)), (.55, (246, 248, 252)), (1, WHITE)])
    return dict(layers=[dict(w=.105, color=WHITE), dict(w=.065, color=E)], fill=F,
                glows=[dict(color=G, r=.26, a=.95)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.4))


_MIN_GOLD = [(0, WHITE), (.4, (255, 246, 204)), (.72, (246, 212, 120)), (1, (210, 156, 56))]   # 白から薄い金（明朝の題字）


def st_tokuban_2017(C, key):
    """2017：白から薄い金の明朝＋こげ茶と金の二重の縁＋金茶の厚み＋暗いにじみ"""
    return _tok_recolor(dict(font='mincho', bold=.014, layers=[dict(w=.105, color=(46, 22, 0)), dict(w=.06, color=(206, 146, 34))],
                             fill=_MIN_GOLD, extrude=dict(dx=.03, dy=.07, color=(96, 54, 4)), glows=[dict(color=BLACK, r=.16, a=.6, k=1.6)],
                             shadow=dict(dx=.04, dy=.08, blur=.05, a=.5)), key, C)


def st_tokuban_2021(C, key):
    """2021：2017 と同じ明朝の金＋青緑の光（色を指定すると光がその色）"""
    d = _tok_recolor(dict(font='mincho', bold=.014, layers=[dict(w=.105, color=(46, 22, 0)), dict(w=.06, color=(206, 146, 34))],
                          fill=_MIN_GOLD, extrude=dict(dx=.03, dy=.07, color=(96, 54, 4)), glows=[dict(color=(80, 220, 225), r=.3, a=.8)]),
                     key, C)
    if key == 'w':
        d['glows'] = [dict(color=(80, 220, 225), r=.3, a=.8)]
    return d


def st_tokuban_2024(C, key):
    """2024：白から金のグラデーションの細めの明朝＋金の厚み"""
    return _tok_recolor(dict(font='mincho', bold=.012, layers=[dict(w=.05, color=(110, 64, 0))],
                             fill=[(0, WHITE), (.45, (255, 244, 200)), (1, (232, 184, 70))],
                             extrude=dict(dx=.035, dy=.09, color=(196, 136, 24)), shadow=dict(dx=.05, dy=.11, blur=.05, a=.55)), key, C)


def st_tokuban_2026(C, key):
    """2026：金の明朝＋赤い縁＋赤い光（色を指定すると縁と光がその色・白は銀の字＋灰の縁）"""
    E = (200, 32, 22) if key in ('y', 'r') else (C if key != 'w' else (120, 126, 140))
    F = ([(0, (255, 252, 232)), (.5, (252, 226, 150)), (1, (216, 162, 60))] if key != 'w'
         else [(0, WHITE), (.5, (230, 234, 242)), (1, (170, 176, 190))])
    red = key in ('y', 'r')                         # 元の色（赤い縁）はもとの値のまま
    return dict(font='mincho', bold=.016, layers=[dict(w=.1, color=(80, 0, 0) if red else darken(E, .6)), dict(w=.062, color=E)], fill=F,
                extrude=dict(dx=.03, dy=.06, color=(110, 12, 8) if red else darken(E, .45)),
                glows=[dict(color=(255, 40, 30) if red else E, r=.18, a=.4)], shadow=dict(dx=.03, dy=.05, blur=.04, a=.5))


TOKUBAN_YEARS = ('2005', '2009', '2012', '2014', '2017', '2021', '2024', '2026')


def st_yontaku(C, key):
    """4択パネル（決めテロップでは Yontaku が描く）。ここは装飾用の平らな形＝白い字＋黒い縁"""
    return dict(layers=[dict(w=.1, color=INK)], fill=[(0, WHITE), (1, (232, 236, 244))], shadow=dict(dx=.02, dy=.04, blur=.02, a=.5))


STYLES = {
    'gloss': ('光沢（白い縁＋濃い縁＋グロー）', st_gloss),
    'kin': ('金属（金・銀。折り返しのある照り）', st_kin),
    'fuchi': ('多重の縁（白抜き・色・白・黒）', st_fuchi),
    'beta': ('べた＋立体の影（ポップ）', st_beta),
    'neon': ('ネオン（光る細い字）', st_neon),
    'fire': ('炎（黄→橙→赤。青系の色なら氷）', st_fire),
    'horror': ('にじむ明朝（怖い話・重い話）', st_horror),
    'mincho': ('白い明朝＋色のにじみ（静かな決め）', st_mincho),
    'kage': ('素直（黒い縁＋落ち影。いつもの字に近い）', st_kage),
    'obi': ('帯（斜めの色帯に白抜き）', st_obi),
    'burst': ('爆発（ギザギザの台座）', st_burst),
    'rainbow': ('虹（1文字ずつ色違い）', st_rainbow),
    'kinmin': ('金の明朝（金の照り＋クリームの外縁＋金の光）', st_kinmin),
    'hikari': ('光る明朝（白い縁＋太い光る外縁。glow で光の色）', st_hikari),
    'shiromin': ('白縁の明朝（白い縁＋白い光）', st_shiromin),
    'pop': ('太いゴシック＋クリームの外縁＋黄色い光', st_pop),
    'hako': ('黄色い板に色の字（小見出し）', st_hako),
    'jimaku': ('字幕（白い字＋黒い縁＋固い影。edge で話し手の色の縁）', st_jimaku),
    'dekai': ('大きな長体（横を詰めた W9＋黒い縁）', st_dekai),
    'tsuyo': ('強調（淡い色の字＋白い縁＋濃い外縁）', st_tsuyo),
    'geki': ('劇画の明朝（縦長の明朝＋黒い縁）', st_geki),
    'waku': ('枠の板（黄色い太枠の黄緑の板）', st_waku),
    'waku_ao': ('見出しの板（黄色い太枠の水色の板）', st_waku_ao),
    'news_jimaku': ('ニュースの字幕（白い字＋話し手の色の縁。edge）', st_news_jimaku),
    'news_obi': ('ニュースの見出しの帯（横いっぱいの帯。edge で帯の色・tag で札）', st_news_obi),
    'news_tsuyo': ('ニュースの強調（濃い字＋白い太縁）', st_news_tsuyo),
    'news_fuda': ('ニュースの情報の札（白い板＋色の字・tag でタブ）', st_news_fuda),
    'kaiten': ('3D 回転（金の枠の柱が回って面ごとに字。行＝面）', st_kaiten),
    'yontaku': ('4択パネル（光る縁の六角の板。1行目＝問題・2行目から選択肢）', st_yontaku),
    'bara': ('バラエティの字幕（黒＝青い光・青赤＝白からのグラデ・黄橙ピンク＝べた）', st_bara),
    'shuchou': ('主張の札（黒紫の六角の板＋緑の縁＋紫の名前のタブ）', st_shuchou),
    'nafuda': ('出演者の名札（両端のとがった色の札）', st_nafuda),
    'news_flash': ('速報の字（白い字＋黒い太縁＋落ち影）', st_news_flash),
    'news_flash_head': ('速報の見出し（斜めの白い字＋上下の2本の線）', st_news_flash_head),
    'news_head': ('ニュースの見出しの帯（白い帯＋青い縁・青いタブ）', st_news_head),
    'news_cap': ('ニュースの字幕の帯（半透明の暗い帯・青い札と白い札）', st_news_cap),
    'news_corner': ('右上の札（白い板に黒と赤の字）', st_news_corner),
    'news_basho': ('場所の札（黒い板に白い字）', st_news_basho),
    'kaisetsu': ('解説番組の見出し（行ごとの斜めの帯＋星形の札）', st_kaisetsu),
    'jouhou_title': ('朝の情報番組の題名（ピンクの縁の白い札）', st_jouhou_title),
    'jouhou_name': ('朝の情報番組の名前の札（ピンクのタブ＋色の縦じま）', st_jouhou_name),
    'gaitou': ('色の太明朝（色のグラデ＋白い縁＋濃い外縁＋厚み。白は黒い縁）', st_gaitou),
    'gaitou_go': ('太いゴシック（白い字＋黒い太縁＋黒いにじみ。色の字は太明朝と同じ重ね）', st_gaitou_go),
    'gaitou_sub': ('話し言葉の字幕（色の字＋白い細縁＋同じ色の光。白い字は edge の色）', st_gaitou_sub),
    'gaitou_staff': ('スタッフの問い（白い小さな字・黒い札は tag・答えの行は黄）', st_gaitou_staff),
    'gaitou_obi': ('紺の帯の見出し（横いっぱいの紺の帯に黄色い太字）', st_gaitou_obi),
    'gaitou_q': ('問いの板（白い角丸の板に黒い字・要の語は赤）', st_gaitou_q),
    'gaitou_kado': ('1字ずつの箱の題名（黒い帯の上に白い箱・要の語は黄緑の箱）', st_gaitou_kado),
    'tatefuda': ('縦の札（色の板に白い縦書き・写真の横に「実際の○○」）', lambda C, key: st_tatefuda(C, key)),
    'tokuban_2005': ('選挙特番の題字 2005（銀のゴシック＋立体の影）', st_tokuban_2005),
    'tokuban_2009': ('選挙特番の題字 2009（金の太いゴシック＋黒い厚み）', st_tokuban_2009),
    'tokuban_2012': ('選挙特番の題字 2012（明るい金・字の間を広く）', st_tokuban_2012),
    'tokuban_2014': ('選挙特番の題字 2014（黄白のグラデ＋紺と白の縁＋青い光）', st_tokuban_2014),
    'tokuban_2017': ('選挙特番の題字 2017（金の太い明朝＋濃い厚み）', st_tokuban_2017),
    'tokuban_2021': ('選挙特番の題字 2021（金の太い明朝＋青緑の光）', st_tokuban_2021),
    'tokuban_2024': ('選挙特番の題字 2024（白から金の細めの明朝＋金の厚み）', st_tokuban_2024),
    'tokuban_2026': ('選挙特番の題字 2026（金の明朝＋赤い縁＋赤い光）', st_tokuban_2026),
}
MULTI_LINE_FX = ('yontaku',)       # 3 行を超えてよい決めテロップ（build_premiere が控えの文字クリップを 3 行までにする）


def style_of(name, key, over=None):
    if name not in STYLES:
        raise SystemExit(f'telop_fx: 型「{name}」は知らない（{", ".join(STYLES)}）')
    st = dict(font='W9', bold=0, skew=0, kana=1.0, track=0, cond=1.0, layers=[], glows=[], bevel=0)
    st.update(STYLES[name][1](BASE.get(key, BASE['w']), key if key in BASE else 'w'))
    st.update(over or {})
    return st


def stops(g):
    """グラデーションの定義 [(位置, 色)...]（色だけの並びなら等間隔）"""
    if g and not isinstance(g[0][0], (int, float)):
        return [(i / max(1, len(g) - 1), tuple(c)) for i, c in enumerate(g)]
    return [(p, tuple(c)) for p, c in g]


def grad_at(g, t):
    t = min(1.0, max(0.0, t))
    for (p0, c0), (p1, c1) in zip(g, g[1:]):
        if t <= p1:
            return mix(c0, c1, (t - p0) / (p1 - p0) if p1 > p0 else 1.0)
    return g[-1][1]


def grad_img(size, g, y0, y1):
    """縦のグラデーション（y0〜y1 に g を張る。外は端の色）"""
    w, h = size
    g = stops(g)
    col = Image.new('RGB', (1, h))
    col.putdata([grad_at(g, (y - y0) / max(1, y1 - y0)) for y in range(h)])
    return col.resize((w, h))


def paint(mask, spec, y0, y1):
    """マスクに色（color）かグラデーション（grad）を付けた RGBA。透明なところにも同じ色を入れておく（回したときに縁が黒ずまない）"""
    if isinstance(spec, dict) and 'grad' in spec:
        img = grad_img(mask.size, spec['grad'], y0, y1)
    elif isinstance(spec, dict):
        img = Image.new('RGB', mask.size, tuple(spec['color']))
    else:
        img = grad_img(mask.size, spec, y0, y1)
    img = img.convert('RGBA')
    img.putalpha(mask)
    return img


# ---------------------------------------------------------------- 動きの部品
def clamp(t):
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def eo(t):
    return 1 - (1 - clamp(t)) ** 3


def ei(t):
    return clamp(t) ** 3


def back(t, k=1.70158):
    t = clamp(t) - 1
    return 1 + (k + 1) * t ** 3 + k * t ** 2


def lerp(a, b, t):
    return a + (b - a) * t


class St:
    """1コマの状態。まとまり全体（dx・dy・sx・sy・rot・a・ぼかし・ワイプ・光・色ずれ・残像）と、1文字ごと（chars）"""

    def __init__(self):
        self.dx = self.dy = self.rot = 0.0
        self.sx = self.sy = self.a = self.glow = 1.0
        self.blur = (0.0, 0.0)
        self.wipe = self.blinds = self.shine = None
        self.flash = self.chroma = 0.0
        self.ghosts = []
        self.chars = {}
        self.plate_a = 1.0
        self.bloom = 0.0        # グロー：字より太い真っ白の光の塊を重ねる濃さ（0〜1）
        self.plate_sy = 1.0     # 台座だけの縦の倍率（グロー縦伸び）
        self.echo = []          # [(倍率, 不透明度)]：止まった絵の写しを大きくして後ろに薄く（グロー飛び込みの余韻）
        self.floor = None       # この y（全画面）より下を切る（床からせり上がる）

    def rest_block(self):
        return (self.dx == 0 and self.dy == 0 and self.rot == 0 and self.sx == 1 and self.sy == 1 and self.a == 1)

    def rest_inner(self):
        return (not self.chars and self.blur == (0.0, 0.0) and self.wipe is None and self.blinds is None and self.shine is None
                and self.flash == 0 and self.chroma == 0 and self.glow == 1 and self.plate_a == 1
                and self.bloom == 0 and self.plate_sy == 1)


# 出方（まとまりごと）：名前 → (説明, 長さ（フレーム）, 関数(t 0〜1, S, T))
def in_pop(t, S, T):
    S.sx = S.sy = lerp(.3, 1, back(t, 2.4))
    S.a = min(1, t * 3.5)


def in_slam(t, S, T):
    if t < .5:
        u = t / .5
        S.sx = S.sy = 3.4 - 2.5 * u * u
        S.a = min(1, u * 3)
    else:
        u = (t - .5) / .5
        S.sx = S.sy = lerp(.9, 1, back(u, 3.2))
        S.flash = max(0.0, .9 - u * 2.2)
        S.dx, S.dy = T.rnd(1) * .07 * T.em * (1 - u), T.rnd(2) * .07 * T.em * (1 - u)


def in_tobidashi(t, S, T):
    S.sx = S.sy = max(.02, 1 - math.exp(-5 * t) * math.cos(9 * t))
    S.a = min(1, t * 5)
    if t < .7:
        S.ghosts = [(1, .35), (2, .18)]


def in_drop(t, S, T):
    if t < .45:
        u = t / .45
        S.dy = -(T.cy + T.bh) * (1 - u * u)
    elif t < .7:
        v = (t - .45) / .25
        S.sy = 1 - .26 * math.sin(math.pi * v)
        S.sx = 1 + .13 * math.sin(math.pi * v)
        S.dy = (1 - S.sy) * T.bh / 2
    else:
        v = (t - .7) / .3
        S.dy = -.2 * T.em * math.sin(math.pi * v)


def _slide(sign):
    def fn(t, S, T):
        S.dx = sign * T.W * .95 * (1 - back(t, 1.5))
        S.blur = (70 * (1 - t) ** 2, 0)
        if t < .6:
            S.ghosts = [(1, .3), (2, .15)]
    return fn


def in_rise(t, S, T):
    S.dy = .9 * T.em * (1 - eo(t))
    S.a = min(1, t * 2.5)


def _wipe(d):
    def fn(t, S, T):
        S.wipe = (t, d)
    return fn


def in_blinds(t, S, T):
    S.blinds = t


def in_stretch_v(t, S, T):
    S.sy = max(.02, lerp(.02, 1, back(t, 3.2)))
    S.a = min(1, t * 6)


def in_stretch_h(t, S, T):
    S.sx = max(.02, lerp(.02, 1, back(t, 3.2)))
    S.a = min(1, t * 6)


def in_blur_h(t, S, T):
    S.blur = (90 * (1 - eo(t)), 0)
    S.sx = 1 + .5 * (1 - eo(t))
    S.a = min(1, t * 2)


def in_news_swipe(t, S, T):
    """ニュースの帯：横ぶれしながら左から開き、字がはっきりする（実測 14 フレーム）"""
    S.wipe = (eo(min(1.0, t * 1.5)), 'L')
    S.blur = (80 * (1 - eo(t)) ** 1.5, 0)


def in_blur_v(t, S, T):
    S.blur = (0, 70 * (1 - eo(t)))
    S.sy = 1 + .7 * (1 - eo(t))
    S.a = min(1, t * 2)


def in_spin(t, S, T):
    S.rot = -360 * (1 - eo(t))
    S.sx = S.sy = lerp(.15, 1, back(t, 2.0))
    S.a = min(1, t * 4)


def in_flip(t, S, T):
    c = math.cos((1 - eo(t)) * 1.5 * math.pi)
    S.sx = c if abs(c) > .03 else .03
    S.a = min(1, t * 4)


def in_blink(t, S, T):
    S.sx = S.sy = lerp(.55, 1, eo(t))
    if t < .78 and T.f % 2 == 1:
        S.a = .12


def in_chroma(t, S, T):
    S.chroma = 34 * (1 - eo(t))
    S.sx = S.sy = 1 + .35 * (1 - eo(t))
    S.a = min(1, t * 3)


def in_glow(t, S, T):
    S.glow = 1 + 3.5 * (1 - t)
    S.flash = .95 * (1 - eo(t))
    b = 26 * (1 - eo(t))
    S.blur = (b, b)
    S.a = min(1, t * 2.5)


def in_shake(t, S, T):
    S.sx = S.sy = lerp(.6, 1, back(t, 2.6))
    S.dx, S.dy = T.rnd(3) * .15 * T.em * (1 - t), T.rnd(4) * .15 * T.em * (1 - t)
    S.rot = T.rnd(5) * 6 * (1 - t)
    S.a = min(1, t * 4)


def in_swing(t, S, T):
    S.rot = 16 * math.cos(t * math.pi * 3.2) * (1 - t) ** 1.5
    S.sx = S.sy = lerp(.7, 1, eo(t * 3))
    S.a = min(1, t * 4)


def in_fly(t, S, T):
    S.sx = S.sy = 1 + 1.3 * (1 - eo(t))
    b = 38 * (1 - eo(t))
    S.blur = (b, b)
    S.a = min(1, t * 2.5)


def in_cut(t, S, T):
    pass


# ---- グロー系の出方（2026-11-06）：動き（base フレーム）のあいだは真っ白に光る塊のまま入り、着いてから cool フレームで色に冷める。
# 見本の実測：動き 約8〜10フレーム＋冷め 約8フレーム（30fps）
def glow_wrap(base_fn, base, cool=8, blur=.13, after=None):
    """base_fn(t, S, T) の動きを、白い光の塊で入って色に冷める出方にする。(関数, 全体のフレーム数) を返す。
    after(u, S, T) は冷めるあいだ（u 0〜1）に足す動き（余韻など）"""
    total = base + cool

    def fn(t, S, T):
        f = t * total
        if f < base:
            base_fn(f / base, S, T)
            S.bloom = 1.0
            b = blur * T.em
            S.blur = (S.blur[0] + b, S.blur[1] + b)
            S.glow = max(S.glow, 2.2)
            return
        u = clamp((f - base) / cool)
        base_fn(1.0, S, T)
        S.bloom = (1 - u) ** 1.6
        b = blur * T.em * (1 - u) ** 2
        S.blur = (S.blur[0] + b, S.blur[1] + b)
        S.glow = max(S.glow, 1 + 1.2 * (1 - u))
        if after:
            after(u, S, T)
    return fn, total


def _g_slam(t, S, T):
    S.sx = S.sy = 1 + 2.6 * (1 - eo(t))
    S.a = min(1, t * 4)


def _g_slam_echo(u, S, T):
    S.echo = [(1 + .65 * eo(u), .42 * (1 - u))]


def _g_slide(sign):
    def fn(t, S, T):
        S.dx = sign * T.W * .30 * (1 - eo(t))
        S.a = .22 + .78 * eo(t)                             # 灰色の影から白くなりながら滑り込む
        S.blur = (40 * (1 - t) ** 2, 0)
    return fn


def _g_pop(t, S, T):
    S.dy = T.bh * .95 * (1 - back(t, 2.2))                  # 床の下から跳ね上がり、少し行き過ぎて戻る
    if t < 1:
        S.floor = T.by1 + .06 * T.em


def _g_stretch(t, S, T):
    s = max(.03, lerp(.03, 1, back(t, 2.6)))
    if T.plate is not None:                                 # 台座がある型：台座が線から縦に伸び、字はそのあと
        S.plate_sy = s
        if t < 1:
            for u in T.units:
                S.chars[u.idx] = (0, 0, 1, 0, 0)
    else:
        S.sy = s


def _blink_land(sign):
    """巨大なところから縮んで着地（回りながら・点滅しながら）。白い光はなし"""
    def fn(t, S, T):
        S.sx = S.sy = 1 + 3.6 * (1 - eo(t))
        S.rot = -sign * 12 * (1 - eo(t))
        if t < .8 and T.f % 2 == 1:
            S.glow *= 2.2
            S.a = .55
    return fn


_GW_L, _GW_LN = glow_wrap(_wipe('l'), 9)
_GW_C, _GW_CN = glow_wrap(_wipe('c'), 9)
_GSLAM, _GSLAM_N = glow_wrap(_g_slam, 10, cool=10, after=_g_slam_echo)
_GSL_R, _GSL_RN = glow_wrap(_g_slide(1), 9)
_GSL_L, _GSL_LN = glow_wrap(_g_slide(-1), 9)
_GSTR, _GSTR_N = glow_wrap(_g_stretch, 6, cool=10)
_GPOP, _GPOP_N = glow_wrap(_g_pop, 9, cool=8)

BLOCK_IN = {
    'pop': ('ポップアップ（ぽんっ）', 8, in_pop),
    'slam': ('飛び込み（手前からどん・光る）', 10, in_slam),
    'tobidashi': ('飛び出し（奥からびよん・残像）', 12, in_tobidashi),
    'drop': ('上から落下（つぶれて弾む）', 12, in_drop),
    'slide_l': ('左からスライド（ぶれ・残像）', 9, _slide(-1)),
    'slide_r': ('右からスライド（ぶれ・残像）', 9, _slide(1)),
    'rise': ('下からすっと', 7, in_rise),
    'wipe_l': ('光るワイプ（左から）', 10, _wipe('l')),
    'wipe_c': ('光るワイプ（中央から）', 10, _wipe('c')),
    'wipe_u': ('光るワイプ（下から）', 9, _wipe('u')),
    'blinds': ('ブラインド', 10, in_blinds),
    'stretch_v': ('縦伸び', 8, in_stretch_v),
    'stretch_h': ('横伸び', 8, in_stretch_h),
    'blur_h': ('横ぶれから', 8, in_blur_h),
    'blur_v': ('縦ぶれから', 8, in_blur_v),
    'news_swipe': ('ニュースの帯（横ぶれしながら左から開く）', 14, in_news_swipe),
    'kaiten_in': ('3D 回転の柱が回りながら出る（kaiten 用。ほかの型では pop）', 16, in_pop),
    'panel_in': ('4択パネルが中央から横に開く（yontaku 用。ほかの型では pop）', 8, in_pop),
    'fly': ('ぼけた手前から寄る', 9, in_fly),
    'spin': ('回って出る', 12, in_spin),
    'flip': ('板がひるがえる', 11, in_flip),
    'blink': ('点滅しながら大きく', 12, in_blink),
    'chroma': ('色ずれしながら', 10, in_chroma),
    'glow': ('光の中から', 11, in_glow),
    'shake': ('震えながら', 12, in_shake),
    'swing': ('振り子で止まる', 16, in_swing),
    'cut': ('動きなし（0フレーム目から完成形）', 0, in_cut),
    'glow_wipe_l': ('グロー・ワイプ（左から白く光って色に冷める）', _GW_LN, _GW_L),
    'glow_wipe_c': ('グロー・ワイプ（中央から開く）', _GW_CN, _GW_C),
    'glow_slam': ('グロー・飛び込み（大きな白い塊が縮んで着地・後ろに余韻）', _GSLAM_N, _GSLAM),
    'glow_slide_r': ('グロー・スライドイン（右から）', _GSL_RN, _GSL_R),
    'glow_slide_l': ('グロー・スライドイン（左から）', _GSL_LN, _GSL_L),
    'glow_stretch_v': ('グロー・縦伸び（台座が先に伸びる）', _GSTR_N, _GSTR),
    'glow_pop': ('グロー・ポップアップ（床の下から跳ね上がる）', _GPOP_N, _GPOP),
    'blink_cw': ('点滅しながら着地（大きいところから・時計回り）', 11, _blink_land(1)),
    'blink_ccw': ('点滅しながら着地（大きいところから・反時計回り）', 11, _blink_land(-1)),
}


# 出方（1文字ずつ）：名前 → (説明, 1文字の長さ, 文字の間隔（フレーム）, 関数(t, i, T) → (dx, dy, 倍率, 回転, 不透明度))
def ch_pop(t, i, T):
    return 0, 0, max(.02, back(t, 2.8)), 0, min(1, t * 4)


def ch_drop(t, i, T):
    if t < .6:
        u = t / .6
        return 0, -1.25 * T.em * (1 - u * u), 1, 0, min(1, t * 4)
    v = (t - .6) / .4
    return 0, -.22 * T.em * abs(math.sin(math.pi * v)) * (1 - v), 1, 0, 1


def ch_rise(t, i, T):
    return 0, .7 * T.em * (1 - eo(t)), 1, 0, min(1, t * 3)


def ch_spin(t, i, T):
    return 0, 0, max(.02, eo(t)), -220 * (1 - eo(t)), min(1, t * 4)


def ch_type(t, i, T):
    return 0, 0, 1, 0, 1


def ch_slam(t, i, T):
    s = 2.8 - 1.9 * ei(t / .6) if t < .6 else lerp(.9, 1, back((t - .6) / .4, 3))
    return 0, 0, s, 0, min(1, t * 4)


def ch_wave(t, i, T):
    return 0, -.5 * T.em * math.sin(t * math.pi * 2) * (1 - t), lerp(.6, 1, eo(t)), 0, min(1, t * 3)


CHAR_IN = {
    'chars_pop': ('1文字ずつぽん', 7, 2, ch_pop),
    'chars_drop': ('1文字ずつ落ちて弾む', 10, 2, ch_drop),
    'chars_rise': ('1文字ずつせり上がる', 6, 2, ch_rise),
    'chars_spin': ('1文字ずつ回る', 8, 2, ch_spin),
    'chars_slam': ('1文字ずつどん', 8, 3, ch_slam),
    'type': ('1文字ずつ打つ', 1, 2, ch_type),
    'wave_in': ('波打ちながら', 12, 2, ch_wave),
}


# 出ている間：名前 → (説明, 関数(k＝出きってからのフレーム, S, T))。"grow+shine" のように + でつなげる
def ho_grow(k, S, T):
    s = 1 + .08 * clamp(k / max(1, T.hold_n))
    S.sx *= s
    S.sy *= s


def _ho_shake(amp):
    def fn(k, S, T):
        S.dx += T.rnd(11) * amp * T.em
        S.dy += T.rnd(12) * amp * T.em
        S.rot += T.rnd(13) * amp * 22
    return fn


def ho_wave(k, S, T):
    for u in T.units:
        d = S.chars.get(u.idx, (0, 0, 1, 0, 1))
        S.chars[u.idx] = (d[0], d[1] + .085 * T.em * math.sin(2 * math.pi * (k / 22 - u.i / 5)), d[2], d[3], d[4])


def ho_pulse(k, S, T):
    ph = (k % 18) / 18
    s = 1 + .075 * max(0.0, 1 - ph * 4) ** 2
    S.sx *= s
    S.sy *= s


def ho_shine(k, S, T):
    if k % 50 < 14:
        S.shine = (k % 50) / 14


def ho_sway(k, S, T):
    S.rot += 2.2 * math.sin(2 * math.pi * k / 40)


def ho_flicker(k, S, T):
    r = T.rnd(21, k // 2)
    S.glow *= 1 + .45 * r
    S.a *= .9 + .1 * (r + 1) / 2


def ho_bound(k, S, T):
    S.dy -= .09 * T.em * abs(math.sin(math.pi * k / 12))


def ho_none(k, S, T):
    pass


def _ho_turn(sign):
    """ゆっくり回り続ける（4秒で約4度）"""
    def fn(k, S, T):
        S.rot += sign * .035 * k
    return fn


def ho_tenmetsu(k, S, T):
    """光が明滅する（3フレームごとに強く・弱く）。字そのものは消えない"""
    S.glow *= 1.5 if (k // 3) % 2 == 0 else .75


HOLD = {
    'none': ('動かない', ho_none),
    'grow': ('じわじわ大きく', ho_grow),
    'shake': ('小さく震える', _ho_shake(.02)),
    'shake_big': ('大きく震える', _ho_shake(.06)),
    'wave': ('波打つ', ho_wave),
    'pulse': ('鼓動（どくん）', ho_pulse),
    'shine': ('光が走る', ho_shine),
    'sway': ('左右に傾く', ho_sway),
    'flicker': ('ネオンのちらつき', ho_flicker),
    'bound': ('弾み続ける', ho_bound),
    'turn_cw': ('ゆっくり時計回りに回り続ける', _ho_turn(1)),
    'turn_ccw': ('ゆっくり反時計回りに回り続ける', _ho_turn(-1)),
    'tenmetsu': ('光が明滅する（点滅）', ho_tenmetsu),
}


# 消え方：名前 → (説明, 長さ, 関数(t, S, T))
def out_fade(t, S, T):
    S.a *= 1 - t


def out_pop(t, S, T):
    S.sx *= 1 + .25 * t
    S.sy *= 1 + .25 * t
    S.a *= 1 - t


def out_shrink(t, S, T):
    S.sx *= max(.02, 1 - ei(t))
    S.sy *= max(.02, 1 - ei(t))


def _out_slide(sign):
    def fn(t, S, T):
        S.dx += sign * T.W * ei(t)
        S.blur = (S.blur[0] + 60 * t, S.blur[1])
    return fn


def out_down(t, S, T):
    S.dy += T.H * .35 * ei(t)
    S.rot += 10 * t
    S.a *= 1 - t * t


def out_blur(t, S, T):
    S.blur = (S.blur[0] + 80 * t, S.blur[1])
    S.sx *= 1 + .5 * t
    S.a *= 1 - t


def out_wipe(t, S, T):
    S.wipe = (1 - t, 'r')


OUT = {
    'cut': ('すっと消える（動きなし）', 0, lambda t, S, T: None),
    'fade': ('フェード', 5, out_fade),
    'pop': ('ふくらんで消える', 5, out_pop),
    'shrink': ('しぼむ', 5, out_shrink),
    'slide_l': ('左へ抜ける', 6, _out_slide(-1)),
    'slide_r': ('右へ抜ける', 6, _out_slide(1)),
    'down': ('下へ落ちる', 7, out_down),
    'blur': ('横にぶれて消える', 6, out_blur),
    'wipe': ('ワイプで消える', 6, out_wipe),
}

# 気分：型＋動きのおすすめの組み合わせ（spec では "fx": "ikari" のように書ける）。color は行の色がなければ使う色
MOODS = {
    'ikari': ('怒り・告発', dict(style='fuchi', **{'in': 'slam'}, hold='shake', color='r')),
    'odoroki': ('驚き', dict(style='gloss', **{'in': 'tobidashi'}, hold='pulse', color='y')),
    'gimon': ('疑問・あやしい', dict(style='neon', **{'in': 'wave_in'}, hold='wave', color='c')),
    'suuji': ('数字・金額', dict(style='kin', **{'in': 'chars_drop'}, hold='shine', color='y')),
    'ketsuron': ('結論・決め', dict(style='gloss', **{'in': 'wipe_l'}, hold='grow+shine', color='r')),
    'tsukkomi': ('ツッコミ', dict(style='beta', **{'in': 'pop'}, hold='sway', color='p', skew=.14)),
    'kowai': ('怖い・重い', dict(style='horror', **{'in': 'blur_v'}, hold='shake', color='r')),
    'kirakira': ('明るい・おどける', dict(style='rainbow', **{'in': 'chars_pop'}, hold='wave', color='y')),
    'sokuhou': ('速報・見出し', dict(style='obi', **{'in': 'slide_l'}, hold='shine', color='r')),
    'bakuhatsu': ('爆発・大声', dict(style='burst', **{'in': 'tobidashi'}, hold='pulse', color='r')),
    'honoo': ('炎上・熱い', dict(style='fire', **{'in': 'stretch_v'}, hold='flicker', color='r')),
    'shizuka': ('静かな決め', dict(style='mincho', **{'in': 'glow'}, hold='grow', color='w')),
    # グロー系（2026-11-06）。行の中の色分けは fx の paint（{"語": "色"}）で足す
    'gouka': ('豪華・特別（金の明朝が左から光って出る）', dict(style='kinmin', **{'in': 'glow_wipe_l'}, hold='none', color='y')),
    'shoutai': ('正体・暴露（光る明朝が中央から開く）', dict(style='hikari', **{'in': 'glow_wipe_c'}, hold='none', color='r')),
    'happyou': ('発表（白い塊が飛び込んで着地）', dict(style='pop', **{'in': 'glow_slam'}, hold='none', color='r')),
    'henshin': ('変身・様変わり（右から滑り込む・紫の光）', dict(style='hikari', **{'in': 'glow_slide_r'}, hold='none', color='v', glow='v')),
    'kakumei': ('新事実・ひっくり返る（左から滑り込む）', dict(style='shiromin', **{'in': 'glow_slide_l'}, hold='none', color='c')),
    'shindoi': ('苦労・小見出し（黄色い板が縦に伸びる）', dict(style='hako', **{'in': 'glow_stretch_v'}, hold='none', color='v')),
    'tassei': ('達成・クリア（床から跳ね上がる）', dict(style='pop', **{'in': 'glow_pop'}, hold='none', color='p')),
    'taiketsu': ('対決・幕開け（飛び込んで着地・右に回る。11-07 夜に点滅を外した）',
                 dict(style='shiromin', **{'in': 'slam'}, hold='grow+turn_cw', color='r', skew=.14)),
    'shinjitsu': ('真実・発表（飛び込んで着地・左に回る。11-07 夜に点滅を外した）',
                  dict(style='shiromin', **{'in': 'slam'}, hold='grow+turn_ccw', color='b', skew=.14)),
    # バラエティの字幕型（2026-11-07）。どれも cut（パッと出る）。話し手の色は edge、行の中の強調は paint
    'jimaku': ('字幕（話し手の色の縁・強調の語は paint）', dict(style='jimaku', **{'in': 'cut'}, hold='none', color='w', edge='b')),
    'honne': ('本音の一言（大きな長体・白）', dict(style='dekai', **{'in': 'cut'}, hold='none', color='w', big=True)),
    'tsumeyori': ('詰め寄る一言（大きな長体・赤）', dict(style='dekai', **{'in': 'cut'}, hold='none', color='r', big=True)),
    'kyouchou': ('目立たせる一言（白い縁＋濃い外縁・橙）', dict(style='tsuyo', **{'in': 'cut'}, hold='none', color='o')),
    'dokuhaku': ('独白・迫る問い（劇画の明朝）', dict(style='geki', **{'in': 'cut'}, hold='none', color='w', big=True)),
    'narration': ('ナレーション・心の声（黄色い枠の板）', dict(style='waku', **{'in': 'cut'}, hold='none', color='r')),
    'midashi': ('企画の見出し（水色の板・2行目を赤に）', dict(style='waku_ao', **{'in': 'cut'}, hold='none', color='k')),
    # バラエティ風 その2（2026-11-07）：語ごとの色は paint、大きさは size_words、名前のタブは tag
    'bara_mix': ('大小と色を混ぜた字幕（語ごとに paint と size_words）', dict(style='bara', **{'in': 'cut'}, hold='none', color='k')),
    'shuchou': ('主張の札（紫の名前のタブ tag＋緑に光る六角の板・2行目は黄）', dict(style='shuchou', **{'in': 'pop'}, hold='none', color='w')),
    'nafuda': ('出演者の名札（両端のとがった色の札・前の小さい語は size_words）', dict(style='nafuda', **{'in': 'cut'}, hold='none', color='v')),
    # 街頭インタビュー風（2026-11-07）。どれも cut。要の語の色は paint、白い字幕の縁の色は edge、スタッフの札は tag
    'gaitou_aka': ('言い切りの一言（色の太明朝・赤）', dict(style='gaitou', **{'in': 'cut'}, hold='none', color='r', big=True)),
    'gaitou_ao': ('しくじった一言（色の太明朝・青）', dict(style='gaitou', **{'in': 'cut'}, hold='none', color='b', big=True)),
    'gaitou_shiro': ('本音の一言（白い太ゴシック＋黒い縁）', dict(style='gaitou_go', **{'in': 'cut'}, hold='none', color='w', big=True)),
    'gaitou_mix': ('要の語だけ色の一言（白い太ゴシックの中の語を paint で紫に）', dict(style='gaitou_go', **{'in': 'cut'}, hold='none', color='w', big=True)),
    'gaitou_futairo': ('2色の一言（前半と後半で色を替える・paint）', dict(style='gaitou', **{'in': 'cut'}, hold='none', color='g', big=True)),
    'gaitou_sub': ('話し言葉の字幕（色の字＋同じ色の光）', dict(style='gaitou_sub', **{'in': 'cut'}, hold='none', color='p')),
    'gaitou_sub_w': ('話し言葉の字幕・白（edge の色の縁と光・既定は青）', dict(style='gaitou_sub', **{'in': 'cut'}, hold='none', color='w', edge='b')),
    'gaitou_staff': ('スタッフの問い＋答え（黒い札 tag・1行目は小さく白・2行目は黄）', dict(style='gaitou_staff', **{'in': 'cut'}, hold='none', color='w')),
    'gaitou_obi': ('「〜騒動」の見出し（紺の帯に黄色い太字）', dict(style='gaitou_obi', **{'in': 'cut'}, hold='none', color='y', big=True)),
    'gaitou_q': ('問いの板（Q.〜は？・要の語は赤）', dict(style='gaitou_q', **{'in': 'cut'}, hold='none', color='k')),
    'gaitou_kado': ('1字ずつの箱の題名（企画名・要の語は黄緑の箱）', dict(style='gaitou_kado', **{'in': 'cut'}, hold='none', color='w')),
    'tatefuda': ('縦の札（写真の横に「実際の○○」・既定は左の端・align r で右）', dict(style='tatefuda', **{'in': 'cut'}, hold='none', color='r', align='l')),
    # ニュース・情報番組のパロディ用（2026-11-07）。どれも cut。tag＝タブ・札、tag2＝2 つ目の札、align＝左右の寄せ
    'sokuho_flash': ('速報の字（画面の上に2行・白い字＋黒い太縁）', dict(style='news_flash', **{'in': 'cut'}, hold='none', color='w')),
    'sokuho_head': ('速報の見出し（「ニュース速報」＋上下の線）', dict(style='news_flash_head', **{'in': 'cut'}, hold='none', color='w')),
    'news_head': ('ニュースの見出しの帯（白い帯・要の語は赤・青いタブは tag）', dict(style='news_head', **{'in': 'cut'}, hold='none', color='k', align='l')),
    'news_cap': ('ニュースの字幕の帯（暗い帯に白い字・青い札 tag と白い札 tag2）', dict(style='news_cap', **{'in': 'cut'}, hold='none', color='w', align='l')),
    'news_corner': ('右上の札（白い板・2行目は赤・右寄せ）', dict(style='news_corner', **{'in': 'cut'}, hold='none', color='k', align='r')),
    'news_basho': ('場所の札（黒い板に白い字・右寄せ）', dict(style='news_basho', **{'in': 'cut'}, hold='none', color='w', align='r')),
    'kaisetsu': ('解説番組の見出し（行ごとの斜めの帯・星形の札は tag）', dict(style='kaisetsu', **{'in': 'cut'}, hold='none', color='w')),
    'jouhou_title': ('朝の情報番組の題名（ピンクの縁の白い札・要の語は赤）', dict(style='jouhou_title', **{'in': 'cut'}, hold='none', color='k')),
    'jouhou_name': ('朝の情報番組の名前の札（ピンクのタブ tag＝所属・色の縦じま）', dict(style='jouhou_name', **{'in': 'cut'}, hold='none', color='k')),
    # 選挙特番の題字（2026-11-07）：年ごとの「衆議院解散」の題字の作り。行の色＝黄で元のまま・白で銀・ほかの色でその色の光と縁
    **{f'kaisan_{y}': (f'選挙特番の題字 {y} 年の作り（NHK の衆議院解散の題字）', dict(style=f'tokuban_{y}', **{'in': 'pop'}, hold='none', color='y'))
       for y in ('2005', '2009', '2012', '2014', '2017', '2021', '2024', '2026')},
    # ニュース風（2026-11-07）。帯だけ横ぶれで入り、ほかは cut。edge＝色の要、tag＝札、box_words＝要の語を色の箱に
    'news_jimaku': ('インタビュー字幕（白い字＋話し手の色の縁・要の語は箱か色の字）',
                    dict(style='news_jimaku', **{'in': 'cut'}, hold='none', color='w', edge='b')),
    'news_obi': ('見出しの帯（横いっぱいの帯がぶれて入る・左上の札は tag）',
                 dict(style='news_obi', **{'in': 'news_swipe'}, hold='none', color='w', edge='g')),
    'news_kyouchou': ('大きな強調（濃い字＋白い太縁）', dict(style='news_tsuyo', **{'in': 'cut'}, hold='none', color='r')),
    'news_fuda': ('情報の札（白い板＋色の字・上のタブは tag）', dict(style='news_fuda', **{'in': 'cut'}, hold='none', color='w', edge='b')),
    # 3D 回転（2026-11-07）：行＝面。回るのは各行の出る時刻（2行目の anchor が読まれたとき）か turn_at（秒）
    'kaiten_tate': ('3D 回転・縦の柱（面ごとに縦書き。「気づく？→気づかない？」）',
                    dict(style='kaiten', **{'in': 'kaiten_in'}, hold='none', color='r', axis='y')),
    'kaiten_yoko': ('3D 回転・横の帯（転がって次の面）', dict(style='kaiten', **{'in': 'kaiten_in'}, hold='none', color='r', axis='x')),
    'kaiten_gin': ('3D 回転・銀の枠の横の帯（ニュース・解説向き）',
                   dict(style='kaiten', **{'in': 'kaiten_in'}, hold='none', color='w', axis='x', frame='gin')),
    'kaiten_pop': ('3D 回転・白い枠の縦の柱（明るいクイズ）', dict(style='kaiten', **{'in': 'kaiten_in'}, hold='none', color='p', axis='y', frame='shiro')),
    # 4択パネル（2026-11-07）：1行目＝問題、2行目から＝選択肢（2〜4）。選択肢は各行の出る時刻（anchor）に出る。answer で正解を緑に
    'yontaku': ('4択クイズ（青く光る縁・選択肢が順に出る・answer で正解が緑に）', dict(style='yontaku', **{'in': 'panel_in'}, hold='none', color='w')),
    'yontaku_kin': ('4択クイズ・金の縁（豪華・決勝）', dict(style='yontaku', **{'in': 'panel_in'}, hold='none', color='w', edge='y')),
    'mondai': ('問題の板だけ（光る縁の六角の板に問い）', dict(style='yontaku', **{'in': 'panel_in'}, hold='none', color='w')),
    'yontaku_nhk': ('4択クイズ・NHK 版（紺の板＋黄の縁・正解は黄に）', dict(style='yontaku', **{'in': 'panel_in'}, hold='none', color='w', theme='nhk')),
    'mondai_nhk': ('問題の板だけ・NHK 版（紺＋黄）', dict(style='yontaku', **{'in': 'panel_in'}, hold='none', color='w', theme='nhk')),
}
GLOW_MOODS = ('gouka', 'shoutai', 'happyou', 'henshin', 'kakumei', 'shindoi', 'tassei', 'taiketsu', 'shinjitsu')
# 見本の文言（行, 色）と行の中の色分け（paint）
GLOW_SAMPLES = {
    'gouka': ([('受信料 特別検証', 'y')], None),
    'shoutai': ([('使い道が判明!', 'r')], {'が判明!': 'b'}),
    'happyou': ([('値上げの真相', 'r')], None),
    'henshin': ([('NHKが大変身!', 'v')], {'大変身!': 'o'}),
    'kakumei': ([('受信料に新事実が!', 'c')], {'新事実': 'r', 'に': 'k', 'が!': 'k'}),
    'shindoi': ([('しんどい集金', 'v')], None),
    'tassei': ([('解約できた!', 'p')], None),
    'taiketsu': ([('国会VS会長', 'g'), ('論戦が幕を開く!', 'r')], {'VS': 'k', '会長': 'p', '幕を開く!': 'y'}),
    'shinjitsu': ([('誰も知らない真実', 'b')], {'真実': 'r'}),
}


SUB_STYLES = ('jimaku', 'dekai', 'tsuyo', 'geki', 'waku', 'waku_ao', 'news_jimaku', 'news_obi', 'news_tsuyo', 'news_fuda',
              'gaitou', 'gaitou_go', 'gaitou_sub', 'gaitou_staff', 'gaitou_obi', 'gaitou_q', 'gaitou_kado', 'tatefuda')     # バラエティの字幕型（XML だけの版でも動きなし）
VARIETY_MOODS = ('jimaku', 'honne', 'tsumeyori', 'kyouchou', 'dokuhaku', 'narration', 'midashi', 'bara_mix', 'shuchou', 'nafuda')
NEWS_MOODS = ('news_jimaku', 'news_obi', 'news_kyouchou', 'news_fuda')
KAITEN_MOODS = ('kaiten_tate', 'kaiten_yoko', 'kaiten_gin', 'kaiten_pop')
QUIZ_MOODS = ('yontaku', 'yontaku_kin', 'mondai', 'yontaku_nhk', 'mondai_nhk')
PARODY_MOODS = ('sokuho_flash', 'sokuho_head', 'news_head', 'news_cap', 'news_corner', 'news_basho', 'kaisetsu', 'jouhou_title', 'jouhou_name')
KAISAN_MOODS = tuple(f'kaisan_{y}' for y in TOKUBAN_YEARS)
# 見本の文言は本物のニュースと取り違えないもの（作り話のニュースを書かない）
PARODY_SAMPLES = {
    'sokuho_flash': ([('元NHK職員が答える', 'w'), ('受信料のギモン', 'w')], {}),
    'sokuho_head': ([('ニュース速報', 'w')], {}),
    'news_head': ([('受信料のギモン 元職員が解説', 'k')], {'paint': {'元職員が解説': 'r'}, 'tag': '元NHK職員'}),
    'news_cap': ([('受信料は', 'w'), ('放送法にもとづく契約', 'w')], {'tag': '元NHK職員', 'tag2': '解説'}),
    'news_corner': ([('元NHK職員', 'k'), ('受信料のギモン', 'r')], {}),
    'news_basho': ([('渋谷・NHK前', 'w')], {}),
    'kaisetsu': ([('元職員が解説', 'w'), ('受信料のギモン', 'k'), ('その答えは', 'w')], {'tag': '緊急解説', 'paint': {'ギモン': 'r'}}),
    'jouhou_title': ([('受信料の 素朴なギモン', 'k'), ('元NHK職員が答えます…', 'k')], {'paint': {'素朴なギモン': 'r'}}),
    'jouhou_name': ([('ある元NHK職員', 'k')], {'tag': '解説'}),
}
QUIZ_SAMPLES = {'yontaku': ([('受信料は 月いくら？', 'w'), ('1100円', 'w'), ('2200円', 'w'), ('550円', 'w'), ('無料', 'w')], {'pick': 'C', 'answer': 'A'}),      # 地上契約・口座振替の月額（2023-10〜）
                'yontaku_kin': ([('NHKの会長を 選ぶのは？', 'w'), ('経営委員会', 'w'), ('総理大臣', 'w'), ('国会', 'w'), ('視聴者', 'w')], {'answer': 'A'}),       # 会長は経営委員会が任命（放送法52条）
                'mondai': ([('受信料は 何のため？', 'w')], {}),
                'yontaku_nhk': ([('NHKの 正式な名前は？', 'w'), ('日本放送協会', 'w'), ('日本放送局', 'w'), ('国営放送', 'w'), ('日本放送公社', 'w')],
                                {'pick': 'B', 'answer': 'A'}),
                'mondai_nhk': ([('受信料は 何のため？', 'w')], {})}
KAITEN_SAMPLES = {'kaiten_tate': [('解約？', 'r'), ('継続？', 'b')], 'kaiten_yoko': [('スクランブル化？', 'c'), ('国営化？', 'r')],
                  'kaiten_gin': [('受信料は', 'w'), ('いらない？', 'k')], 'kaiten_pop': [('払う？', 'p'), ('払わない？', 'g')]}
# 見本の文言（行, 色）と、ほかの fx の値（paint・box_words・tag）
NEWS_SAMPLES = {
    'news_jimaku': ([('受信料は', 'w'), ('毎月払ってますね', 'w')], {'box_words': {'受信料': 'r'}, 'paint': {'毎月': 'y'}}),
    'news_obi': ([('受信料 どう思う？', 'w')], {'paint': {'受信料': 'y'}, 'tag': '妻'}),
    'news_kyouchou': ([('値上げに反発', 'r')], {}),
    'news_fuda': ([('月1100円〜', 'w')], {'tag': '受信料'}),
}
VARIETY_SAMPLES = {
    'jimaku': ([('受信料って本当に', 'w'), ('払う必要あるの？', 'w')], {'払う必要': 'r'}),
    'honne': ([('集金が3回も来た…', 'w')], None),
    'tsumeyori': ([('値上げ 知ってた？', 'r')], None),
    'kyouchou': ([('集金のプロで', 'o')], None),
    'dokuhaku': ([('解約したはずなのに', 'w')], None),
    'narration': ([('まさかの契約!!', 'r')], None),
    'midashi': ([('元職員が答える', 'k'), ('受信料って必要？', 'r')], None),
    'bara_mix': ([('正直 解約したい', 'k')], None),
    'shuchou': ([('集金に来る人', 'w'), ('ちょっと怖い！', 'y')], None),
    'nafuda': ([('視聴者 Aさん', 'v')], None),
}
VARIETY_EXTRA = {'bara_mix': {'paint': {'正直': 'p'}, 'size_words': {'正直': .72}}, 'shuchou': {'tag': '視聴者 Aさん'},
                 'nafuda': {'size_words': {'視聴者': .62}}}


def catalog_variety(out):
    """バラエティの字幕型（7つの気分）の見本動画"""
    cells = [(k, MOODS[k][0], VARIETY_SAMPLES[k][0], dict(mood=k, **({'paint': VARIETY_SAMPLES[k][1]} if VARIETY_SAMPLES[k][1] else {}),
                                                           **VARIETY_EXTRA.get(k, {})))
             for k in VARIETY_MOODS]
    return _grid_video(cells, Path(out) / '見本_8_バラエティの字幕型.mp4', 'バラエティの字幕型（2026-11-07）', sec=2.4)


# 3D 回転の見本（2026-11-07 ユーザー「賛成？反対？ スクランブル化？国営化？ など作ってみて 色やテロップのバリエーションも」）
KAITEN_VARIANTS = [
    ('縦・金', '賛成？反対？（赤／青）', [('賛成？', 'r'), ('反対？', 'b')], dict(mood='kaiten_tate')),
    ('横・金', '賛成？反対？（赤／青）', [('賛成？', 'r'), ('反対？', 'b')], dict(mood='kaiten_yoko')),
    ('横・金', 'スクランブル化？国営化？（水色／赤）', [('スクランブル化？', 'c'), ('国営化？', 'r')], dict(mood='kaiten_yoko')),
    ('縦・銀', 'スクランブル化？国営化？（青／橙）', [('スクランブル化？', 'b'), ('国営化？', 'o')], dict(mood='kaiten_tate', frame='gin')),
    ('縦・3面', '賛成？反対？どちらでもない？', [('賛成？', 'r'), ('反対？', 'b'), ('どちらでもない？', 'k')], dict(mood='kaiten_tate')),
    ('横・銀', '受信料は／いらない？（紺／黒）', [('受信料は', 'w'), ('いらない？', 'k')], dict(mood='kaiten_gin')),
    ('縦・白', '払う？払わない？（ピンク／緑）', [('払う？', 'p'), ('払わない？', 'g')], dict(mood='kaiten_pop')),
    ('横・枠なし', 'NHKは／必要？（黄／紫）', [('NHKは', 'y'), ('必要？', 'v')], dict(mood='kaiten_yoko', frame='nashi')),
    ('縦・枠なし', '公共放送？国営放送？（橙／水色）', [('公共放送？', 'o'), ('国営放送？', 'c')], dict(mood='kaiten_tate', frame='nashi')),
    ('縦・のぞかせ', '気づく？気づかない？（次の面を横に見せる）', [('気づく？', 'r'), ('気づかない？', 'b')], dict(mood='kaiten_tate', peek=True)),
]


def catalog_kaiten(out):
    """3D 回転の見本動画（10 通り）"""
    cells = [(lab, desc, lines, dict(fx, tall=.78)) for lab, desc, lines, fx in KAITEN_VARIANTS]
    return _grid_video(cells, Path(out) / '見本_9_3D回転.mp4', '3D 回転テロップ（2026-11-07）', sec=3.6)


QUIZ_VARIANTS = [
    ('4択・青', '選択肢が順に出る→C を選ぶ（橙）→正解 A が緑に',
     [('受信料は 月いくら？', 'w'), ('1100円', 'w'), ('2200円', 'w'), ('550円', 'w'), ('無料', 'w')], dict(mood='yontaku', pick='C', answer='A')),
    ('4択・金', '金の縁（決勝・最後の問題）',
     [('受信料の 正式な名前は？', 'w'), ('視聴料', 'w'), ('放送受信料', 'w'), ('電波使用料', 'w'), ('NHK会費', 'w')], dict(mood='yontaku_kin', answer='B')),
    ('3択・赤', 'edge で縁の色（赤）',
     [('あなたは どっち派？', 'w'), ('払う', 'w'), ('払わない', 'w'), ('考え中', 'w')], dict(mood='yontaku', edge='r')),
    ('2択・緑', '1・2 の番号（labels）',
     [('スクランブル化に 賛成？', 'w'), ('賛成', 'w'), ('反対', 'w')], dict(mood='yontaku', edge='g', labels=['1', '2'])),
    ('問題だけ', '問いの板だけ（mondai）', [('受信料は 何のため？', 'w')], dict(mood='mondai')),
    ('NHK 版・4択', '紺＋黄。B を選ぶ（白）→正解 A が黄に', [('NHKの 正式な名前は？', 'w'), ('日本放送協会', 'w'), ('日本放送局', 'w'),
                                                     ('国営放送', 'w'), ('日本放送公社', 'w')], dict(mood='yontaku_nhk', pick='B', answer='A')),
    ('NHK 版・4択', '受信契約の根拠（正解 A）', [('受信契約の 根拠は？', 'w'), ('放送法', 'w'), ('電波法', 'w'), ('民法', 'w'), ('NHKの規約', 'w')],
                                    dict(mood='yontaku_nhk', answer='A')),
    ('NHK 版・2択', '番号（labels）', [('受信料は 税金？', 'w'), ('はい', 'w'), ('いいえ', 'w')], dict(mood='yontaku_nhk', labels=['1', '2'], answer='2')),
    ('NHK 版・問題だけ', 'mondai_nhk', [('受信料は 何のため？', 'w')], dict(mood='mondai_nhk')),
    ('4択・紫', '長い選択肢は板の中で縮む', [('次のうち 正しいのは？', 'w'), ('受信料は 税金である', 'w'), ('受信料は 契約にもとづく', 'w'),
                                            ('受信料は 寄付である', 'w'), ('受信料は 任意である', 'w')], dict(mood='yontaku', edge='v')),
]


def catalog_quiz(out):
    """4択パネルの見本動画（縦用・6 通り）"""
    return _grid_video(QUIZ_VARIANTS, Path(out) / '見本_10_4択クイズ.mp4', '4択クイズ（縦用・2026-11-07）', sec=5.0)


def catalog_kaisan(out):
    """選挙特番の題字（年ごと 8 つ）の見本動画"""
    cells = [(f'kaisan_{y}', MOODS[f'kaisan_{y}'][0].replace('（NHK の衆議院解散の題字）', ''), [('スクランブル化', 'y')], f'kaisan_{y}')
             for y in TOKUBAN_YEARS]
    return _grid_video(cells, Path(out) / '見本_11_選挙特番の題字.mp4', '選挙特番の題字（年ごと・2026-11-07）', sec=2.6)


GAITOU_MOODS = ('gaitou_aka', 'gaitou_ao', 'gaitou_shiro', 'gaitou_mix', 'gaitou_futairo', 'gaitou_sub', 'gaitou_sub_w', 'gaitou_staff',
                'gaitou_obi', 'gaitou_q', 'gaitou_kado', 'tatefuda')
# 見本の文言（行, 色）と、ほかの fx の値。街の人の声の形だが、実在の人の発言ではない一般的な言い回し
GAITOU_SAMPLES = {
    'gaitou_aka': ([('集金が3回来た', 'r')], {}),
    'gaitou_ao': ([('解約でしくじった', 'b')], {}),
    'gaitou_shiro': ([('テレビないです', 'w')], {}),
    'gaitou_mix': ([('契約済みらしい', 'w')], {'paint': {'契約': 'v'}}),
    'gaitou_futairo': ([('テレビ離れの若者', 'g')], {'paint': {'若者': 'o'}}),
    'gaitou_sub': ([('解約の電話したら', 'p'), ('1時間待たされて', 'p')], {}),
    'gaitou_sub_w': ([('受信料の話を', 'w'), ('聞きに行こうかって', 'w')], {}),
    'gaitou_staff': ([('受信料 払ってます？', 'w'), ('払ってますよ', 'y')], {'tag': 'スタッフ'}),
    'gaitou_obi': ([('NHK契約騒動', 'y')], {}),
    'gaitou_q': ([('Q.受信料の使い道は？', 'k')], {'paint': {'使い道': 'r'}}),
    'gaitou_kado': ([('街で受信料の本音を聞いた件', 'w')], {'paint': {'受信料の本音': 'g'}}),
    'tatefuda': ([('実際の契約書', 'r')], {}),
}


def catalog_gaitou(out):
    """街頭インタビュー風（11 の気分）の見本動画"""
    cells = [(k, MOODS[k][0], GAITOU_SAMPLES[k][0], dict(mood=k, **GAITOU_SAMPLES[k][1])) for k in GAITOU_MOODS]
    return _grid_video(cells, Path(out) / '見本_12_街頭インタビュー風.mp4', '街頭インタビュー風（2026-11-07）', sec=2.4)


def catalog_glow(out):
    """グロー系（9つの気分）の見本動画"""
    cells = [(k, MOODS[k][0], GLOW_SAMPLES[k][0], dict(mood=k, **({'paint': GLOW_SAMPLES[k][1]} if GLOW_SAMPLES[k][1] else {})))
             for k in GLOW_MOODS]
    return _grid_video(cells, Path(out) / '見本_7_グロー系.mp4', 'グロー系の決めテロップ（2026-11-06）', sec=3.4)


def resolve_fx(fx):
    """spec の fx（気分の名前／"型:出方:出ている間:消え方"／dict）を、全部そろった dict にする"""
    if isinstance(fx, str):
        if fx in MOODS:
            fx = dict(MOODS[fx][1])
        else:
            p = fx.split(':')
            fx = {k: v for k, v in zip(('style', 'in', 'hold', 'out'), p) if v}
    else:
        fx = dict(fx)
        if fx.get('mood'):
            if fx['mood'] not in MOODS:
                raise SystemExit(f'telop_fx: 気分「{fx["mood"]}」は知らない（{", ".join(MOODS)}）')
            fx = dict(MOODS[fx['mood']][1], **{k: v for k, v in fx.items() if k != 'mood'})
    fx.setdefault('style', 'gloss')
    fx.setdefault('in', 'pop')
    fx.setdefault('hold', 'none')
    fx.setdefault('out', 'cut')
    if fx['style'] not in STYLES:
        raise SystemExit(f'telop_fx: 型「{fx["style"]}」は知らない（型 {", ".join(STYLES)}／気分 {", ".join(MOODS)}）')
    if fx['in'] not in BLOCK_IN and fx['in'] not in CHAR_IN:
        raise SystemExit(f'telop_fx: 出方「{fx["in"]}」は知らない（{", ".join(list(BLOCK_IN) + list(CHAR_IN))}）')
    for h in str(fx['hold']).split('+'):
        if h not in HOLD:
            raise SystemExit(f'telop_fx: 出ている間の動き「{h}」は知らない（{", ".join(HOLD)}）')
    if fx['out'] not in OUT:
        raise SystemExit(f'telop_fx: 消え方「{fx["out"]}」は知らない（{", ".join(OUT)}）')
    p = fx.get('paint')
    if isinstance(p, str):                       # "が明らかに!=b,VS=k" の書き方も受ける
        p = dict(kv.rsplit('=', 1) for kv in p.split(',') if '=' in kv)
    elif isinstance(p, list):                    # [["語", "色"], ...]
        p = {w: c for w, c in p}
    if p:
        for w, c in p.items():
            if c not in BASE:
                raise SystemExit(f'telop_fx: paint の「{w}」の色「{c}」は知らない（{", ".join(BASE)}）')
        fx['paint'] = p
    bw = fx.get('box_words')
    if isinstance(bw, str):
        bw = dict(kv.rsplit('=', 1) for kv in bw.split(',') if '=' in kv)
    elif isinstance(bw, list):
        bw = {w: c for w, c in bw}
    if bw:
        for w, c in bw.items():
            if c not in BASE:
                raise SystemExit(f'telop_fx: box_words の「{w}」の色「{c}」は知らない（{", ".join(BASE)}）')
        fx['box_words'] = bw
    for k in ('answer', 'pick'):
        v = fx.get(k)
        if v is not None and not ((isinstance(v, str) and len(v) == 1) or isinstance(v, int)):
            raise SystemExit(f'telop_fx: {k} は選択肢の記号（"A"〜"D"）か番号（1〜4）')
    if fx.get('theme') not in (None, 'std', 'nhk'):
        raise SystemExit('telop_fx: theme は std（黒＋青）か nhk（紺＋黄）')
    if fx.get('frame') not in (None, 'kin', 'gin', 'shiro', 'nashi'):
        raise SystemExit('telop_fx: frame は kin（金）・gin（銀）・shiro（白）・nashi（枠なし）')
    if fx.get('axis') not in (None, 'x', 'y'):
        raise SystemExit('telop_fx: axis は "y"（縦の柱）か "x"（横の帯）')
    ta = fx.get('turn_at')
    if ta is not None and not (isinstance(ta, (list, tuple)) and all(isinstance(v, (int, float)) for v in ta)):
        raise SystemExit('telop_fx: turn_at は秒の並び（例 [1.2, 2.5]）')
    sw_ = fx.get('size_words')
    if isinstance(sw_, str):                                 # "男女=1.35,大体=1" の書き方も受ける
        sw_ = {w: float(v) for w, v in (kv.rsplit('=', 1) for kv in sw_.split(',') if '=' in kv)}
    if sw_:
        for w, v in sw_.items():
            if not isinstance(v, (int, float)) or not .3 <= v <= 2.5:
                raise SystemExit(f'telop_fx: size_words の「{w}」の倍率「{v}」は 0.3〜2.5 の数')
        fx['size_words'] = dict(sw_)
    if fx.get('tint') is not None and fx['tint'] not in BASE:
        raise SystemExit(f'telop_fx: tint の色「{fx["tint"]}」は知らない（{", ".join(BASE)}）')
    if fx.get('metal') is not None and not isinstance(fx['metal'], bool):
        raise SystemExit('telop_fx: metal は true か false（選挙特番の題字の字を行の色の金属にする）')
    if fx.get('tag2') is not None and not isinstance(fx['tag2'], str):
        raise SystemExit('telop_fx: tag2 は文字（例 "ことし2月"）')
    if fx.get('align') not in (None, 'l', 'c', 'r'):
        raise SystemExit('telop_fx: align は l（左）・c（中央）・r（右）')
    if fx.get('tag') is not None and not isinstance(fx['tag'], str):
        raise SystemExit('telop_fx: tag は文字（例 "妻"）')
    e = fx.get('edge')
    if e is not None and not ((isinstance(e, str) and e in BASE) or (isinstance(e, (list, tuple)) and len(e) >= 3)):
        raise SystemExit(f'telop_fx: edge の色「{e}」は知らない（{", ".join(BASE)} か [r, g, b]）')
    g = fx.get('glow')
    if g is not None and not ((isinstance(g, str) and g in BASE) or (isinstance(g, (list, tuple)) and len(g) >= 3)):
        raise SystemExit(f'telop_fx: glow の色「{g}」は知らない（{", ".join(BASE)} か [r, g, b]）')
    return fx


# XML だけの版（build_premiere.py --xml-only）：決めテロップの出方を、XML で運べる動き（common.KF_MOTIONS）に読み替える。
# ここに無い出方（pop・slam・tobidashi・stretch・fly・flip・glow・chroma・文字ごとの pop/slam・cut）は don
XML_IN = {'drop': 'drop', 'chars_drop': 'drop', 'slide_l': 'slide_l', 'slide_r': 'slide_r', 'rise': 'up', 'chars_rise': 'up',
          'wave_in': 'up', 'wipe_l': 'wipe', 'wipe_u': 'wipe', 'blinds': 'wipe', 'type': 'wipe', 'wipe_c': 'wipe_c',
          'blur_h': 'blur', 'blur_v': 'blur', 'spin': 'spin2', 'chars_spin': 'spin2', 'blink': 'blink', 'shake': 'shake',
          'swing': 'swing', 'glow_wipe_l': 'wipe', 'glow_wipe_c': 'wipe_c', 'glow_slide_l': 'slide_l', 'glow_slide_r': 'slide_r',
          'glow_pop': 'up', 'glow_stretch_v': 'blur', 'blink_cw': 'blink', 'blink_ccw': 'blink', 'news_swipe': 'wipe', 'kaiten_in': 'spin', 'panel_in': 'wipe_c'}


def fx_as_xml(spec):
    """決めテロップ（fx＝動画）の指定を、打ち替えられる形（文字クリップ＋後ろの装飾 deco＋XML の動き motion）に置き換えた写しを返す。
    spec に deco・motion が書いてあればそちらを使う。座布団は敷かない（決めテロップと同じ）"""
    fx = resolve_fx(spec['fx'])
    out = {k: v for k, v in spec.items() if k != 'fx'}
    out.setdefault('deco', {k: fx[k] for k in ('style', 'color', 'glow', 'edge', 'tag') if fx.get(k)})
    grow = any(h in ('grow', 'pulse') for h in str(fx['hold']).split('+'))
    from common import KF_MOTIONS
    if fx['style'] == 'yontaku':                   # 4択は XML では板にできない＝問題＋選択肢を 3 行までの字にまとめる
        ls = out.get('lines') if isinstance(out.get('lines'), list) else []
        if ls:
            labs = fx.get('labels') or ['A', 'B', 'C', 'D', 'E', 'F']
            ch = [f'{labs[i]} {ln[0]}' for i, ln in enumerate(ls[1:])]
            out['lines'] = [[ls[0][0], 'w']] + [['　'.join(ch[i:i + 2]), 'y'] for i in range(0, len(ch), 2)][:2]
        out['deco'] = None
        out['motion'] = 'none'
        out.setdefault('box', False)
        return out
    if fx['style'] == 'tatefuda':                  # 縦の札は XML では縦書きにできない＝横書きの字だけ（装飾なし）
        out['deco'] = None
        out['motion'] = 'none'
        out.setdefault('box', False)
        return out
    if fx['style'] == 'kaiten':                    # 3D 回転は XML では回せない＝最後の面（答え）だけを 1 回転で出す
        if isinstance(out.get('lines'), list) and out['lines']:
            out['lines'] = [out['lines'][-1]]
        out['deco'] = None
        out['motion'] = 'spin'
        out.setdefault('box', False)
        return out
    if fx['style'] in ('news_fuda', 'gaitou_q') and isinstance(out.get('lines'), list):   # 白い板の上は白い字だと読めない＝濃い字に
        out['lines'] = [[ln[0], 'k' if (len(ln) < 2 or ln[1] == 'w') else ln[1]] + list(ln[2:]) if isinstance(ln, (list, tuple)) else ln
                        for ln in out['lines']]
    if fx['style'] in ('jimaku', 'news_jimaku') and fx.get('edge') is not None:     # 話し手の色の縁は、文字クリップの縁取りが受け持つ（装飾のいちばん内側の縁）
        out.setdefault('stroke_color', list(_glow_color(fx['edge'])))
    m = out.get('motion')
    if not (isinstance(m, str) and m.split('+')[0] in KF_MOTIONS):     # 型の既定（grow など）が書いてあっても、決めテロップの出方を優先
        if fx['in'] == 'cut' and fx['style'] in SUB_STYLES:           # バラエティの字幕型はパッと出るだけ（元の番組も動きなし）
            out['motion'] = 'none' + ('+grow' if grow else '')
        else:
            out['motion'] = XML_IN.get(fx['in'], 'don') + ('+grow' if grow else '')
    out.setdefault('box', False)
    return out


STYLE_KEYS = ('font', 'bold', 'skew', 'kana', 'track', 'cond')


def _glow_color(g):
    return tuple(g[:3]) if isinstance(g, (list, tuple)) else BASE[g]


def paint_keys(text, base, paint):
    """行の文字ごとの色キー。paint {"語": "色"} の語が出てくるところだけ塗り替える（重なったら長い語が勝つ）"""
    keys = [base] * len(text)
    for w in sorted(paint or {}, key=len):
        i = text.find(w)
        while w and i >= 0:
            for j in range(i, i + len(w)):
                keys[j] = paint[w]
            i = text.find(w, i + len(w))
    return keys


def font_keys(text, words):
    """行の文字ごとの書体（font_words {"語": "書体"} の語が出てくるところだけ。ほかは None＝行の書体）。2026-11-06 まる子の裏設定編「白黒を明朝で」"""
    keys = [None] * len(text)
    for w in sorted(words or {}, key=len):
        i = text.find(w)
        while w and i >= 0:
            for j in range(i, i + len(w)):
                keys[j] = words[w]
            i = text.find(w, i + len(w))
    return keys


def _fill_holes(m):
    """縁のマスクの中の閉じた穴（「ま」「す」の輪の中など）を埋める。外側（部品の絵の四隅につながる所）は残す"""
    b = m.point(lambda v: 255 if v > 96 else 0)
    inv = ImageChops.invert(b)
    ImageDraw.floodfill(inv, (0, 0), 0)
    return ImageChops.lighter(m, inv)


def _dilate(m, r):
    """マスクを r px 太らせる（3×3 の十字と四角を交互に＝八角形で丸く近い）。長体の字の縁取り用（PIL の stroke は詰める前の字にしか付かない）"""
    for i in range(int(round(r))):                  # PIL だけで（numpy のない環境でも動くように）。部品の絵は縁の外まで余白があるので offset の折り返しは出ない
        if i % 2:
            m = m.filter(ImageFilter.MaxFilter(3))
        else:
            c = m
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                c = ImageChops.lighter(c, ImageChops.offset(m, dx, dy))
            m = c
    return m


# ---------------------------------------------------------------- 描く
class Unit:
    pass


def _is_hira(ch):
    return 'ぁ' <= ch <= 'ゖ'


class FxTelop:
    """テロップ1つ分。frame(f) で全画面（透明背景）の1枚を返す。

    item = {'lines': [{'text', 'color', 'px', 'baseline', 'delay'}], 'fx': {…}, 'font_ps': …}
      px・baseline は文字クリップと同じ決め方（build_premiere.py の add_telop）。ここでは縁の外側までがセーフティエリアに収まるよう、
      まとまりの中心を軸に全体を同じ倍率で縮める（fx の big が真なら、短い言葉を幅いっぱいまで大きくする）
    mode 'chars'（既定）＝1文字ずつ部品にする（決めテロップ）／'string'＝行をまるごと1つの部品に（文字クリップの後ろの装飾。字の位置を合わせる）
    """

    def __new__(cls, item, L, n, mode='chars', own_stroke=None):
        st_ = resolve_fx(item.get('fx') or {})['style'] if mode == 'chars' else None
        if st_ == 'kaiten':
            return Kaiten(item, L, n)                  # 3D 回転は別の描き手（__init__ は呼ばれない）
        if st_ == 'yontaku':
            return Yontaku(item, L, n)                 # 4択パネルも別の描き手
        if st_ == 'tatefuda':
            return TateFuda(item, L, n)                # 縦の札も別の描き手
        return super().__new__(cls)

    def __init__(self, item, L, n, mode='chars', own_stroke=None):
        self.it, self.L, self.n = item, L, max(1, n)
        self.W, self.H = L['W'], L['H']
        self.fx = resolve_fx(item.get('fx') or {})
        self.mode = mode
        self.own = own_stroke              # 装飾のとき：文字クリップ自身の縁取り（px）。これより内側の縁は描かない
        self.seed = sum(map(ord, ''.join(l['text'] for l in item['lines']))) + 17
        self.f = 0
        over = {k: self.fx[k] for k in STYLE_KEYS if k in self.fx}
        if mode == 'string' and item.get('font_ps'):
            over['font'] = item['font_ps']           # 装飾は文字クリップと同じ書体で
        if mode == 'string':
            over['cond'] = 1.0                       # 装飾は文字クリップ（詰められない）に合わせる
        self._over = over
        self._stc = {}
        self.styles = [self._style(l.get('color', self.fx.get('color', 'w'))) for l in item['lines']]
        self._layout()
        self._sprites()
        self._plate()
        fi = self.fx['in']
        delays = [u.delay for u in self.units]
        if fi in CHAR_IN:
            _, per, stag, _ = CHAR_IN[fi]
            per, stag = self.fx.get('in_dur', per), self.fx.get('stagger', stag)
            self.in_total = max(u.delay + u.i * stag + per for u in self.units)
        else:
            self.in_total = self.fx.get('in_dur', BLOCK_IN[fi][1]) + (max(delays) + 6 if max(delays) else 0)
        self.out_dur = min(self.fx.get('out_dur', OUT[self.fx['out']][1]), max(0, self.n - self.in_total))
        self.hold_n = max(1, self.n - self.in_total - self.out_dur)
        self._rest = None
        self._rest_frame = None

    def rnd(self, salt, k=None):
        return random.Random(self.seed * 1000003 + (self.f if k is None else k) * 7919 + salt).uniform(-1, 1)

    def _style(self, key):
        """色キーごとの型（同じ色は使い回す）。fx の glow があれば光の色を替える"""
        if self.fx.get('tint'):                        # tint：行の色に関係なく型の色を決める（題字の色違いのカード）
            key = self.fx['tint']
        if key not in self._stc:
            st = style_of(self.fx['style'], key, self._over)
            e = self.fx.get('edge')
            if e is not None and st.get('edge_fn'):     # 話し手の色の縁（jimaku の白い字）
                st.update(st['edge_fn'](_glow_color(e)))
            if self.fx.get('metal') and str(self.fx['style']).startswith('tokuban_') and key not in ('y',):
                M_ = BASE.get(key, BASE['y'])
                st['fill'] = _SILVER_FOLD if key == 'w' else _metal(M_)   # 題字の字そのものを色の金属に
                if key != 'w':                              # 内側の金の縁・金の厚みも色に合わせる（金が残ると字の色とけんかする）
                    if len(st.get('layers') or []) > 1:
                        st['layers'] = st['layers'][:-1] + [dict(st['layers'][-1], color=(214, 218, 228) if key == 'k' else darken(M_, .5))]   # 11-07 夜：字と縁が溶けていた
                    if st.get('extrude'):
                        st['extrude'] = dict(st['extrude'], color=darken(M_, .6))
                if key == 'k':                              # 黒の金属は暗い背景に沈む＝白い光で字の形を浮かせる
                    st['glows'] = [dict(color=(226, 230, 240), r=.2, a=.65)]
            g = self.fx.get('glow')
            if g is not None and st.get('glows'):
                st['glows'] = [dict(gl, color=_glow_color(g)) for gl in st['glows']]
            self._stc[key] = st
        return self._stc[key]

    # ---------------------------------------------- 置き方
    def _outer(self, st, px):
        """字面から外へどれだけ出るか（px）：いちばん外の縁＋斜体＋立体の影"""
        w = max([l['w'] for l in st['layers']] + [0]) * px
        if self.mode == 'string' and self.own is not None:
            w = max(deco_widths(st, px, self.own) + [self.own])
        ex = st.get('extrude')
        return w + (abs(ex['dx']) * px if ex else 0) + st.get('skew', 0) * px * .5

    def _plate_side(self, st, px):
        """角丸の板（round）の左右の余白と枠（px）。字が板の枠にかからないよう、幅を決めるときに足す（ほかの台座は今までどおり）"""
        pl = st.get('plate') if self.mode == 'chars' else None
        if pl and pl.get('tag_kind') == 'burst' and self.fx.get('tag'):    # 星形の札の分（帯の左の外に置く＝字にかけない）
            return (pl.get('pad', (.4, .2))[0] + 1.25) * px
        return (pl.get('pad', (.4, .2))[0] + pl.get('ew', .08)) * px if pl and pl.get('kind') == 'round' else 0

    def _measure(self, k):
        rows = []
        for ln, st in zip(self.it['lines'], self.styles):
            px = ln['px'] * k * st.get('scale', 1.0)       # scale：色ごとの字の大きさ（スタッフの問いの白い行を小さく）
            text = ln['text']
            kana = st.get('kana', 1.0)
            mixed = kana != 1.0 and any(_is_hira(c) for c in text) and not all(_is_hira(c) or not c.strip() for c in text)
            if self.mode == 'string':
                parts = [(text, px)]
            else:
                sz = paint_keys(text, None, self.fx.get('size_words')) if self.fx.get('size_words') else [None] * len(text)
                parts = [(c, px * (kana if mixed and _is_hira(c) else 1.0) * (sz[i] or 1.0)) for i, c in enumerate(text)]
            cd = st.get('cond', 1.0)
            fk = font_keys(text, self.fx.get('font_words')) if self.mode == 'chars' and self.fx.get('font_words') else [None] * len(parts)
            advs = [fx_font(fk[i] or st['font'], p).getlength(c, **FEAT) * cd for i, (c, p) in enumerate(parts)]
            tr = st.get('track', 0) * px
            rows.append((parts, advs, tr, sum(advs) + tr * max(0, len(parts) - 1), px))
        return rows

    def _layout(self):
        L = self.L
        lines = self.it['lines']
        sx0, sy0, sx1, sy1 = safe_rect(L)
        rg = max(st.get('row_gap', 0) for st in self.styles) if self.mode == 'chars' and len(lines) > 1 else 0
        if rg:                                            # row_gap：行と行の間を広げる（太い縁の型で、上の行の縁が下の行にかぶらないように）
            pm = max(l['px'] for l in lines)
            lines = [dict(l, baseline=l['baseline'] + (i - (len(lines) - 1) / 2) * rg * pm) for i, l in enumerate(lines)]
        rows = self._measure(1.0)
        need = max(w + 2 * (self._outer(st, px) + self._plate_side(st, px)) for (_, _, _, w, px), st in zip(rows, self.styles))
        tops = [l['baseline'] - .88 * l['px'] for l in lines]
        bots = [l['baseline'] + .12 * l['px'] for l in lines]
        cy0 = (min(tops) + max(bots)) / 2
        tall = (max(bots) - min(tops)) + 2 * max(self._outer(st, px) for (_, _, _, _, px), st in zip(rows, self.styles))
        k = min(1.0, (sx1 - sx0) / need) if need else 1.0
        if self.mode == 'chars':
            big = self.fx.get('big')
            if big:                                       # 短い言葉を大きく（上限は字の大きさ big px。真だけなら 230）
                cap = (230 if big is True else float(big)) / max(l['px'] for l in lines)
                k = min(cap, (sx1 - sx0) * .98 / need)
            k = min(k, (sy1 - sy0) * .96 / tall)          # 高さもセーフティエリアに入る大きさまで
        elif k < 1:
            k = 1.0                                       # 装飾は文字クリップに合わせる（縮めない。はみ出しは build_premiere が字を小さくして防ぐ）
        self.k = k
        if self.mode == 'chars':                          # 縁の外側が上下にはみ出すときは、まとまりごと内側へ寄せる
            o = max(self._outer(st, l['px'] * k) for l, st in zip(lines, self.styles))
            top_k, bot_k = cy0 + (min(tops) - cy0) * k - o, cy0 + (max(bots) - cy0) * k + o
            sh = min(0.0, sy1 - bot_k) if bot_k > sy1 else max(0.0, sy0 - top_k)
            if sh:
                lines = [dict(l, baseline=l['baseline'] + sh / 1.0) for l in lines]
                cy0 += sh
        rows = self._measure(k) if k != 1.0 else rows
        if self.mode == 'chars':                          # 字の大きさは整数に丸まるので、縮めたあとの幅をもう一度測って収まるまで詰める
            for _ in range(6):
                need_k = max(w + 2 * (self._outer(st, px) + self._plate_side(st, px)) for (_, _, _, w, px), st in zip(rows, self.styles))
                if need_k <= (sx1 - sx0) - 1:
                    break
                k *= ((sx1 - sx0) - 2) / need_k
                rows = self._measure(k)
            self.k = k
        self.units, self.rows = [], []
        idx = 0
        for li, ((parts, advs, tr, w, px), ln, st) in enumerate(zip(rows, lines, self.styles)):
            base = cy0 + (ln['baseline'] - cy0) * k       # まとまりの中心を軸に同じ倍率で
            x = self.W / 2 - w / 2
            al = self.fx.get('align')
            if al in ('l', 'r') and self.mode == 'chars':  # 左寄せ・右寄せ（右上の札・字幕の帯）：まとまりごと寄せ、行は中で左揃え
                pl_ = st.get('plate') or {}
                off = max(self._outer(st_, px_) + (pl_.get('pad', (0, 0))[0] * px_ if pl_ else 0)
                          for (_, _, _, _, px_), st_ in zip(rows, self.styles)) + 4
                wmax = max(w_ for (_, _, _, w_, _) in rows)
                x = (sx0 + off) if al == 'l' else (sx1 - off - wmax)
            self.rows.append(dict(px=px, base=base, x0=x, x1=x + w, st=st, delay=int(ln.get('delay') or 0)))
            pk = (paint_keys(ln['text'], ln.get('color', self.fx.get('color', 'w')), self.fx.get('paint'))
                  if self.mode == 'chars' and self.fx.get('paint') else None)
            bk = (paint_keys(ln['text'], None, self.fx.get('box_words'))
                  if self.mode == 'chars' and self.fx.get('box_words') else None)
            fk_ = font_keys(ln['text'], self.fx.get('font_words')) if self.mode == 'chars' and self.fx.get('font_words') else None
            for i, ((c, p), adv) in enumerate(zip(parts, advs)):
                u = Unit()
                ust = self._style(pk[i]) if pk else st                # 行の中の色分け（paint）：塗りも縁も、その字の色の型で
                box = None
                if bk and bk[i]:                                      # 色の箱の中の字（box_words）：縁は細く（太い縁だと箱が隠れる）
                    ust = dict(ust, layers=[dict(w=.035, color=darken(BASE[bk[i]], .6))], glows=[])
                    box = (BASE[bk[i]], i == 0 or bk[i - 1] != bk[i], i == len(bk) - 1 or bk[i + 1] != bk[i])
                elif ust.get('char_box') and c.strip():                # 1字ずつの箱（街頭インタビュー風の題名）：箱の色は字の型（paint で替わる）
                    box = (tuple(ust['char_box']), True, True, True)
                if fk_ and fk_[i]:                                    # 行の中の書体の差し替え（font_words）
                    ust = dict(ust, font=fk_[i])
                u.idx, u.line, u.i, u.text, u.px, u.lpx, u.x, u.base, u.adv, u.st = idx, li, i, c, p, px, x, base, adv, ust
                u.delay = int(ln.get('delay') or 0)
                u.box = box if self.mode == 'chars' else None
                x += adv + tr
                idx += 1
                if c.strip():
                    self.units.append(u)
        self.em = max(r['px'] for r in self.rows)
        out = max(self._outer(r['st'], r['px']) for r in self.rows)
        self.bx0 = min(r['x0'] for r in self.rows) - out
        self.bx1 = max(r['x1'] for r in self.rows) + out
        self.by0 = min(r['base'] - .88 * r['px'] for r in self.rows) - out
        self.by1 = max(r['base'] + .12 * r['px'] for r in self.rows) + out
        self.cx, self.cy = self.W / 2, (self.by0 + self.by1) / 2
        self.bw, self.bh = self.bx1 - self.bx0, self.by1 - self.by0
        reach = max([g['r'] * self.em * 2.6 for r in self.rows for g in r['st'].get('glows', [])] + [0])
        m = int(1.5 * self.em + reach)
        self.rx0, self.ry0 = max(0, int(self.bx0 - m)), max(0, int(self.by0 - m - self.em * .6))
        self.rx1, self.ry1 = min(self.W, int(self.bx1 + m)), min(self.H, int(self.by1 + m))
        if any((r['st'].get('plate') or {}).get('full') for r in self.rows):     # 横いっぱいの帯（news_obi）
            sx0, _, sx1, _ = safe_rect(L)
            self.rx0, self.rx1 = max(0, min(self.rx0, int(sx0) - 4)), min(self.W, max(self.rx1, int(sx1) + 4))
        self.rsize = (self.rx1 - self.rx0, self.ry1 - self.ry0)

    def _sprites(self):
        """部品ごとに、縁（後ろ→前）と塗りの絵を作る。どの絵も同じ大きさ・同じ原点"""
        self.nlayers = max(len(s['layers']) for s in [r['st'] for r in self.rows] + [u.st for u in self.units]) + 1   # paint で縁の段数が違う型が混ざっても揃える
        for u in self.units:
            st, px = u.st, u.px
            f = fx_font(st['font'], px)
            asc, desc = f.getmetrics()
            bold = int(round(st.get('bold', 0) * px))
            ws = [int(round(l['w'] * px)) + bold for l in st['layers']]
            if self.mode == 'string' and self.own is not None:
                ws = deco_widths(st, px, self.own)
            P = max(ws + [bold]) + 4
            if getattr(u, 'box', None):                      # 色の箱の余白の分も絵を広げる
                P = max(P, int(.13 * u.lpx) + 4)
            sk = st.get('skew', 0)
            skp = int(math.ceil(abs(sk) * (asc + desc + 2 * P)))
            w, h = int(math.ceil(u.adv)) + 2 * P + 2 * skp, asc + desc + 2 * P
            ox, oy = P + skp, P + asc                    # 部品の中の字の原点（左端・ベースライン）

            cd = st.get('cond', 1.0)

            def mask(sw):
                if cd != 1.0:                            # 長体：詰めた字を描いてから太らせる（縁の太さが縦横で同じになる）
                    m = Image.new('L', (int(math.ceil(w / cd)) + 2, h), 0)
                    ImageDraw.Draw(m).text((ox / cd, oy), u.text, font=f, fill=255, anchor='ls', **FEAT)
                    m = m.resize((w, h), Image.LANCZOS)
                    if sw:
                        m = _dilate(m, sw)
                else:
                    m = Image.new('L', (w, h), 0)
                    ImageDraw.Draw(m).text((ox, oy), u.text, font=f, fill=255, anchor='ls', stroke_width=sw, stroke_fill=255, **FEAT)
                if sk:
                    m = m.transform((w, h), Image.AFFINE, (1, sk, -sk * oy, 0, 1, 0), resample=Image.BICUBIC)
                return m
            y0, y1 = oy - .88 * u.lpx, oy + .12 * u.lpx
            sprites = [None] * (self.nlayers - 1 - len(st['layers']))
            for l, sw in zip(st['layers'], ws):
                sprites.append(paint(_fill_holes(mask(sw)) if l.get('fill_holes') else mask(sw), l, y0 - sw, y1 + sw) if sw else None)
            if self.mode == 'string':
                sprites.append(None)                      # 装飾は塗りを描かない（前に文字クリップが乗る）
                u.sil = mask(max(self.own or 0, max(ws + [0])))      # グロー・影のもとになる外形（文字クリップ自身の縁も含む）
            else:
                fm = mask(bold)
                fill = st['fill_fn'](u.idx) if st.get('fill_fn') else st['fill']
                img = paint(fm, fill, y0, y1)
                bv = st.get('bevel', 0)
                if bv:
                    d = max(1, int(round(.022 * px)))
                    hl = ImageChops.subtract(fm, ImageChops.offset(fm, d, d))
                    lo = ImageChops.subtract(fm, ImageChops.offset(fm, -d, -d))
                    rgb = img.convert('RGB')
                    rgb = Image.composite(Image.new('RGB', img.size, WHITE), rgb, hl.point(lambda v: int(v * bv)))
                    rgb = Image.composite(Image.new('RGB', img.size, BLACK), rgb, lo.point(lambda v: int(v * bv * .6)))
                    img = rgb.convert('RGBA')
                    img.putalpha(fm)
                if getattr(u, 'box', None):                      # 色の箱（box_words）：箱＋細い縁＋塗りを1枚にして塗りの段で重ねる
                    C, first, last = u.box[:3]                   # ＝隣の字の縁より上、自分の字の下に箱が来る
                    o, lp = .1 * u.lpx, u.lpx
                    bx = Image.new('RGBA', (w, h), C + (0,))
                    bd = ImageDraw.Draw(bx)
                    xa, xb = ox - (o if first else 0), ox + u.adv + (o if last else 1)
                    ya, yb = oy - .88 * lp - o, oy + .12 * lp + o
                    if len(u.box) > 3:                           # 1字ずつの箱：字の幅より少し広い正方形に近い箱＋黒い枠
                        o2 = .05 * lp
                        xa, xb = ox - o2, ox + u.adv + o2
                        bd.rectangle([xa, ya, xb, yb], fill=C + (255,), outline=INK + (255,), width=max(2, int(.055 * lp)))
                    else:
                        bd.rectangle([xa, ya, xb, yb], fill=C + (255,))
                        bd.rectangle([xa, yb - .06 * lp, xb, yb], fill=darken(C, .35) + (255,))
                    for sp in sprites:
                        if sp is not None:
                            bx.alpha_composite(sp)
                    bx.alpha_composite(img)
                    sprites = [None] * len(sprites) + [bx]
                else:
                    sprites.append(img)
            u.sprites = sprites
            u.size = (w, h)
            u.ox = u.x - ox - self.rx0                     # 絵の左上（範囲の中の座標）
            u.oy = u.base - oy - self.ry0
            u.pcx = u.x + u.adv / 2 - self.rx0             # 拡大・回転の軸（字の真ん中）
            u.pcy = u.base - .38 * px - self.ry0

    def _plate(self):
        """台座（帯・爆発）。まとまりの外形に合わせて1枚"""
        self.plate = None
        # 台座の色は、白でない最初の行の色（白＋赤の2行なら赤い帯）
        keys = [l.get('color', 'w') for l in self.it['lines']]
        k0 = next((i for i, k in enumerate(keys) if k != 'w'), 0)
        self.under_st = self.rows[k0]['st']
        pl = self.under_st.get('plate')
        if not pl:
            return
        em = self.em
        px_, py_ = pl.get('pad', (.4, .2))
        x0, x1 = self.bx0 - px_ * em - self.rx0, self.bx1 + px_ * em - self.rx0
        y0, y1 = self.by0 - py_ * em - self.ry0, self.by1 + py_ * em - self.ry0
        sx0, _, sx1, _ = safe_rect(self.L)
        if pl.get('full'):                                  # 横いっぱい（セーフティエリアの幅）
            x0, x1 = sx0 - self.rx0, sx1 - self.rx0
        x0, x1 = max(x0, sx0 - self.rx0), min(x1, sx1 - self.rx0)        # 台座もセーフティエリアの内側
        S = 2                                               # 倍の大きさで描いて縮める（斜めの線をなめらかに）
        img = Image.new('RGBA', (self.rsize[0] * S, self.rsize[1] * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        def shape(x0, y0, x1, y1, pl):                     # 台座の形を1つ描く（x0〜y1＝範囲の中の座標）
            if pl['kind'] == 'band':
                sl = pl.get('slant', .2) * (y1 - y0) / 2
                poly = [(x0 + sl, y0), (x1 + sl, y0), (x1 - sl, y1), (x0 - sl, y1)]
                poly = [(min(max(x, sx0 - self.rx0), sx1 - self.rx0), y) for x, y in poly]
                m = Image.new('L', img.size, 0)
                ImageDraw.Draw(m).polygon([(x * S, y * S) for x, y in poly], fill=255)
                g = grad_img(img.size, pl['grad'], y0 * S, y1 * S).convert('RGBA')
                g.putalpha(m)
                img.alpha_composite(g)
                ew = max(2, int(.035 * em)) * S
                e = tuple(pl.get('edge', WHITE)) + (255,)
                d.line([(poly[0][0] * S, poly[0][1] * S + ew / 2), (poly[1][0] * S, poly[1][1] * S + ew / 2)], fill=e, width=ew)
                d.line([(poly[3][0] * S, poly[3][1] * S - ew / 2), (poly[2][0] * S, poly[2][1] * S - ew / 2)], fill=e, width=ew)
            elif pl['kind'] == 'rect':                          # rect：四角い板（縦のグラデーション＋右と下に濃い厚み）
                th = max(2, int(.045 * em))
                e = tuple(pl.get('edge', (120, 70, 0))) + (255,)
                d.rectangle([(x0 + th) * S, (y0 + th) * S, (x1 + th) * S, (y1 + th) * S], fill=e)
                m = Image.new('L', img.size, 0)
                ImageDraw.Draw(m).rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=255)
                g = grad_img(img.size, pl['grad'], y0 * S, y1 * S).convert('RGBA')
                g.putalpha(m)
                img.alpha_composite(g)
            elif pl['kind'] in ('hexpanel', 'hexpill'):         # 両端のとがった板（hexpanel＝主張の札・hexpill＝名札）
                tip = (y1 - y0) * (.32 if pl['kind'] == 'hexpanel' else .45)
                pts = [(x0, (y0 + y1) / 2), (x0 + tip, y0), (x1 - tip, y0), (x1, (y0 + y1) / 2), (x1 - tip, y1), (x0 + tip, y1)]
                P = [(x * S, y * S) for x, y in pts]
                if pl['kind'] == 'hexpanel' and pl.get('deco'):   # 左右の紫の六角の飾り（板の外側に半分出す）
                    dc = tuple(pl['deco'])
                    r = (y1 - y0) * .14
                    for cx in (x0 + tip * .3, x1 - tip * .3):
                        for cy in ((y0 + y1) / 2 - r * 2.1, (y0 + y1) / 2 + r * 2.1):
                            hx = [((cx + r * math.cos(math.radians(a))) * S, (cy + r * math.sin(math.radians(a))) * S) for a in range(0, 360, 60)]
                            d.polygon(hx, fill=darken(dc, .2) + (255,), outline=lighten(dc, .4) + (255,))
                m = Image.new('L', img.size, 0)
                ImageDraw.Draw(m).polygon(P, fill=255)
                if pl['kind'] == 'hexpanel':                    # 縁の光
                    gl = Image.new('L', img.size, 0)
                    ImageDraw.Draw(gl).line(P + [P[0]], fill=255, width=int(em * .14 * S), joint='curve')
                    gl = gl.filter(ImageFilter.GaussianBlur(em * .1 * S))
                    lay = Image.new('RGBA', img.size, tuple(pl['edge']) + (0,))
                    lay.putalpha(gl.point(lambda v: int(v * .8)))
                    img.alpha_composite(lay)
                g = grad_img(img.size, pl['fill'], y0 * S, y1 * S).convert('RGBA')
                g.putalpha(m)
                img.alpha_composite(g)
                ew = max(2, int(em * (.06 if pl['kind'] == 'hexpanel' else .035) * S))
                d.line(P + [P[0]], fill=tuple(pl['edge']) + (255,), width=ew, joint='curve')
                if pl['kind'] == 'hexpanel':
                    d.line(P + [P[0]], fill=lighten(tuple(pl['edge']), .6) + (255,), width=max(1, ew // 3), joint='curve')
            elif pl['kind'] == 'bar':                           # bar：横長の板（上の縁の色 top・半透明 alpha・細い縁 edge）
                m = Image.new('L', img.size, 0)
                ImageDraw.Draw(m).rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=int(255 * pl.get('alpha', 1.0)))
                g = grad_img(img.size, pl['fill'], y0 * S, y1 * S).convert('RGBA')
                g.putalpha(m)
                img.alpha_composite(g)
                if pl.get('top'):
                    tw_ = max(2, int(em * pl.get('top_w', .07) * S))
                    d.rectangle([x0 * S, y0 * S, x1 * S, y0 * S + tw_], fill=tuple(pl['top']) + (255,))
                if pl.get('edge'):
                    d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], outline=tuple(pl['edge']) + (255,), width=max(1, int(em * .025 * S)))
            elif pl['kind'] == 'none':                          # none：台座なし（札 tag だけを出すため。スタッフの問い）
                pass
            elif pl['kind'] == 'lines2':                        # lines2：字の上下に 2 本の太い線（黒い縁つき）＝速報の見出し
                lw = max(3, int(em * .1 * S))
                for yy in (y0, y1):
                    d.line([(x0 * S, yy * S), (x1 * S, yy * S)], fill=INK + (255,), width=lw + max(4, int(em * .08 * S)))
                    d.line([(x0 * S, yy * S), (x1 * S, yy * S)], fill=WHITE + (255,), width=lw)
            elif pl['kind'] == 'round':                         # round：太枠の角丸の板（枠の色 edge・板の色 fill）
                ew, rr = pl.get('ew', .08) * em, pl.get('r', .08) * em
                if pl.get('stripe'):                            # 左の色の縦じま（情報番組の名前の札）
                    cs_ = pl['stripe']
                    sw_ = em * .2
                    hh_ = (y1 - y0) / len(cs_)
                    for k_, c_ in enumerate(cs_):
                        d.rectangle([(x0 - sw_ * .4) * S, (y0 + hh_ * k_) * S, (x0 + sw_ * .6) * S, (y0 + hh_ * (k_ + 1)) * S], fill=tuple(c_) + (255,))
                    x0 = x0 + sw_ * .6
                d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=rr * S, fill=tuple(pl.get('edge', (250, 200, 30))) + (255,))
                d.rounded_rectangle([(x0 + ew) * S, (y0 + ew) * S, (x1 - ew) * S, (y1 - ew) * S], radius=max(0, rr - ew * .6) * S,
                                    fill=tuple(pl.get('fill', WHITE)) + (255,))
            else:                                               # burst：ギザギザ
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
                rnd = random.Random(self.seed)
                n = max(14, int((rx + ry) / (em * .32)) // 2 * 2)
                lim = (sx1 - sx0) / 2 - 4

                def star(grow):
                    pts = []
                    r2 = random.Random(self.seed)
                    for i in range(n * 2):
                        a = math.pi * i / n + .12
                        k = (1.0 if i % 2 == 0 else .74) * (1 + .09 * r2.uniform(-1, 1))
                        x = min(lim, max(-lim, (rx + grow) * k * math.cos(a)))
                        pts.append(((cx + x) * S, (cy + (ry + grow) * k * math.sin(a)) * S))
                    return pts
                d.polygon(star(.12 * em), fill=INK + (255,))
                d.polygon(star(.06 * em), fill=tuple(pl['rim']) + (255,))
                d.polygon(star(0), fill=tuple(pl['fill']) + (255,))
                del rnd

        if pl.get('per_line'):                             # 行ごとの台座（解説番組の帯・情報番組の札）：行の型の台座で、その行の字のまわりに
            first = None
            for r in self.rows:
                rp = r['st'].get('plate') or pl
                o = self._outer(r['st'], r['px'])
                qx, qy = rp.get('pad', (.4, .2))
                a0x, a1x = r['x0'] - o - qx * r['px'] - self.rx0, r['x1'] + o + qx * r['px'] - self.rx0
                a0y, a1y = r['base'] - .88 * r['px'] - o - qy * r['px'] - self.ry0, r['base'] + .12 * r['px'] + o + qy * r['px'] - self.ry0
                if rp.get('full'):
                    a0x, a1x = sx0 - self.rx0, sx1 - self.rx0
                a0x, a1x = max(a0x, sx0 - self.rx0), min(a1x, sx1 - self.rx0)
                shape(a0x, a0y, a1x, a1y, rp)
                first = first or (a0x, a0y, a1x, a1y)
            x0, y0, x1, y1 = first
        else:
            shape(x0, y0, x1, y1, pl)
        tag = self.fx.get('tag')
        if tag and pl.get('tag_fill'):                      # 札（帯の左上の「妻」・札の上のタブ「料金」）
            f = fx_font('W9', em * pl.get('tag_size', .7 if pl.get('tag_kind') == 'tab' else .92))
            tw = f.getlength(tag, **FEAT)
            if pl.get('tag_kind') == 'burst':                # 星形の札（「緊急解説」）：最初の帯の左上にかぶせる
                rr = em * 1.05
                cx, cy = max(sx0 - self.rx0 + rr * .9, x0 - rr * .6), y0 + rr * .2        # 帯の左の外に（字にかけない）
                n_ = 16
                pts = [((cx + rr * (1 if k % 2 == 0 else .82) * math.cos(math.pi * k / n_)) * S,
                        (cy + rr * (1 if k % 2 == 0 else .82) * math.sin(math.pi * k / n_)) * S) for k in range(n_ * 2)]
                d.polygon(pts, fill=tuple(pl.get('tag_edge', (230, 150, 0))) + (255,))
                pts2 = [((cx + (rr - em * .06) * (1 if k % 2 == 0 else .82) * math.cos(math.pi * k / n_)) * S,
                         (cy + (rr - em * .06) * (1 if k % 2 == 0 else .82) * math.sin(math.pi * k / n_)) * S) for k in range(n_ * 2)]
                d.polygon(pts2, fill=tuple(pl['tag_fill']) + (255,))
                rows_ = [tag[:2], tag[2:]] if len(tag) == 4 else [tag]
                fs = fx_font('W9', int(rr * (.62 if len(rows_) == 2 else .5) * S))
                for k, t_ in enumerate(rows_):
                    d.text((cx * S, (cy + (k - (len(rows_) - 1) / 2) * rr * .66) * S), t_, font=fs, fill=tuple(pl['tag_ink']) + (255,),
                           anchor='mm', **FEAT)
                tag = None
            elif pl.get('tag_kind') == 'tab' and pl.get('kind') == 'hexpanel':   # 主張の札の名前のタブ：上の縁にまたがる台形
                th = em * .9
                bx0, by1 = x0 + (y1 - y0) * .32 + em * .2, y0 + th * .18      # 上の縁にまたがる（字にはかけない）
                box = [bx0, by1 - th, bx0 + tw + em * 1.0, by1]
            elif pl.get('tag_kind') == 'tab':                 # タブ：板の上の左に、板にくっつけて
                th = em * (.92 if 'tag_size' not in pl else pl['tag_size'] * 1.3)
                bx0, by1 = x0, y0 + pl.get('ew', .04) * em
                box = [bx0, by1 - th, bx0 + tw + em * .5, by1]
            else:                                           # 吹き出しの札：帯の左上の上に（しっぽは帯へ向ける）
                side = max(em * 1.4, tw + em * .5)
                bx0, by1 = x0 + em * .1, y0 - em * .22
                box = [bx0, by1 - em * 1.4, bx0 + side, by1]
                tx = bx0 + em * .3
                d.polygon([(tx * S, (by1 - em * .1) * S), ((tx + em * .36) * S, (by1 - em * .1) * S), (tx * S, (by1 + em * .32) * S)],
                          fill=tuple(pl.get('tag_edge', INK)) + (255,))
            if tag:
                d.rounded_rectangle([v * S for v in box], radius=em * pl.get('tag_r', .08) * S, fill=tuple(pl['tag_fill']) + (255,),
                                    outline=tuple(pl.get('tag_edge', INK)) + (255,), width=max(2, int(em * .045)) * S)
                fs = fx_font('W9', f.size * S)
                d.text(((box[0] + box[2]) / 2 * S, (box[1] + box[3]) / 2 * S), tag, font=fs, fill=tuple(pl['tag_ink']) + (255,),
                       anchor='mm', **FEAT)
                t2 = self.fx.get('tag2')
                if t2:                                      # 2 つ目の札（「ことし2月」）：1 つ目の右に同じ高さで
                    w2 = f.getlength(t2, **FEAT) + em * .6
                    b2 = [box[2] + em * .18, box[1], box[2] + em * .18 + w2, box[3]]
                    d.rounded_rectangle([v * S for v in b2], radius=em * pl.get('tag_r', .08) * S,
                                        fill=tuple(pl.get('tag2_fill', WHITE)) + (255,),
                                        outline=tuple(pl.get('tag2_edge', pl.get('tag_edge', INK))) + (255,), width=max(2, int(em * .045)) * S)
                    d.text(((b2[0] + b2[2]) / 2 * S, (b2[1] + b2[3]) / 2 * S), t2, font=fs,
                           fill=tuple(pl.get('tag2_ink', INK)) + (255,), anchor='mm', **FEAT)
        self.plate = img.resize(self.rsize, Image.LANCZOS)

    # ---------------------------------------------- 状態
    def state(self, f, ghosts=True):
        self.f = f
        S, fx = St(), self.fx
        fi = fx['in']
        if fi in CHAR_IN:
            _, per, stag, fn = CHAR_IN[fi]
            per, stag = fx.get('in_dur', per), fx.get('stagger', stag)
            for u in self.units:
                t = (f - u.delay - u.i * stag) / max(1, per)
                if t < 0:
                    S.chars[u.idx] = (0, 0, 1, 0, 0)
                elif t < 1:
                    S.chars[u.idx] = fn(t, u.i, self)
            S.plate_a = clamp((f + 1) / 4)
        else:
            dur = fx.get('in_dur', BLOCK_IN[fi][1])
            if f < dur:
                BLOCK_IN[fi][2](f / dur, S, self)
            for u in self.units:                           # 時間差で出る段（line_at）：その段だけ後からぽんっと出す
                if u.delay:
                    r = self.rows[u.line]
                    t = (f - u.delay) / 6
                    if t < 0:
                        S.chars[u.idx] = (0, 0, 1, 0, 0)
                    elif t < 1:
                        s = lerp(.25, 1, eo(t))
                        px_, py_ = (r['x0'] + r['x1']) / 2 - self.rx0, r['base'] - .38 * r['px'] - self.ry0
                        S.chars[u.idx] = ((s - 1) * (u.pcx - px_), (s - 1) * (u.pcy - py_), s, 0, min(1, t * 3))
        if f >= self.in_total:
            for h in str(fx['hold']).split('+'):
                HOLD[h][1](f - self.in_total, S, self)
        k = f - (self.n - self.out_dur)
        if self.out_dur and k >= 0:
            OUT[fx['out']][2](clamp((k + 1) / self.out_dur), S, self)
        if not ghosts:
            S.ghosts = []
        return S

    # ---------------------------------------------- 1コマを組む
    @staticmethod
    def _put(dst, im, x, y):
        x, y = int(round(x)), int(round(y))
        sx0, sy0 = max(0, -x), max(0, -y)
        sx1, sy1 = min(im.width, dst.width - x), min(im.height, dst.height - y)
        if sx1 > sx0 and sy1 > sy0:
            dst.alpha_composite(im if (sx0, sy0, sx1, sy1) == (0, 0, im.width, im.height) else im.crop((sx0, sy0, sx1, sy1)),
                                (x + sx0, y + sy0))

    def _compose(self, S):
        """縁（後ろ→前）→ 塗り の順に、全部の部品を重ねた絵（範囲の大きさ）。sil＝グロー・影のもとになる外形"""
        R = Image.new('RGBA', self.rsize, (0, 0, 0, 0))
        for li in range(self.nlayers):
            for u in self.units:
                spr = u.sprites[li]
                if spr is None:
                    continue
                st = S.chars.get(u.idx)
                if st is None:
                    self._put(R, spr, u.ox, u.oy)
                    continue
                dx, dy, s, rot, a = st
                if a <= .004:
                    continue
                im = spr
                w, h = u.size
                cx, cy = u.pcx - u.ox, u.pcy - u.oy          # 絵の中の軸
                if abs(s - 1) > .004:
                    im = im.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))), Image.BILINEAR)
                    cx, cy = cx * s, cy * s
                if abs(rot) > .05:
                    big = Image.new('RGBA', (im.width * 2, im.height * 2), im.getpixel((0, 0))[:3] + (0,))
                    big.paste(im, (im.width // 2, im.height // 2))
                    cx, cy = cx + im.width // 2, cy + im.height // 2
                    im = big.rotate(-rot, resample=Image.BICUBIC, center=(cx, cy))
                if a < 1:
                    im = im.copy()
                    im.putalpha(im.getchannel('A').point(lambda v: int(v * a)))
                self._put(R, im, u.pcx + dx - cx, u.pcy + dy - cy)
        return R

    def _under(self, R, S):
        """字の下に敷くもの（影・グロー・立体の影・台座）を足した絵"""
        st = self.under_st
        em = self.em
        body = R
        if self.mode == 'string':                          # 装飾：外形は文字クリップ自身の縁まで含める
            sil = Image.new('L', self.rsize, 0)
            for u in self.units:
                sil.paste(255, (int(round(u.ox)), int(round(u.oy))), u.sil)
            A = ImageChops.lighter(sil, R.getchannel('A'))
        else:
            A = R.getchannel('A')
        if self.plate is not None:
            pl = self.plate
            if S.plate_sy != 1:                            # 台座だけ縦に伸び縮み（まとまりの中心を軸に）
                cy = self.cy - self.ry0
                sy = max(.01, S.plate_sy)
                pl = pl.transform(pl.size, Image.AFFINE, (1, 0, 0, 0, 1 / sy, cy - cy / sy), resample=Image.BILINEAR)
            if S.plate_a < 1:
                pl = pl.copy()
                pl.putalpha(pl.getchannel('A').point(lambda v: int(v * S.plate_a)))
            body = pl.copy()
            body.alpha_composite(R)
            A = ImageChops.lighter(A, pl.getchannel('A'))
        out = Image.new('RGBA', self.rsize, (0, 0, 0, 0))
        ex = st.get('extrude')
        E = None
        if ex:
            n = max(2, int(round(max(abs(ex['dx']), abs(ex['dy'])) * em)))
            E = Image.new('L', self.rsize, 0)
            for i in range(1, n + 1):
                sh = Image.new('L', self.rsize, 0)
                sh.paste(A, (int(round(ex['dx'] * em * i / n)), int(round(ex['dy'] * em * i / n))))
                E = ImageChops.lighter(E, sh)
        sil_all = ImageChops.lighter(A, E) if E is not None else A
        sh = st.get('shadow')
        if sh:
            m = sil_all.filter(ImageFilter.GaussianBlur(max(.5, sh['blur'] * em)))
            lay = Image.new('RGBA', self.rsize, tuple(sh.get('color', BLACK)) + (0,))
            lay.putalpha(m.point(lambda v: int(v * sh['a'])))
            self._put(out, lay, sh['dx'] * em, sh['dy'] * em)
        for g in st.get('glows', []):
            m = sil_all.filter(ImageFilter.GaussianBlur(max(1.0, g['r'] * em)))
            kk = g.get('k', 1.6) * g['a'] * S.glow
            lay = Image.new('RGBA', self.rsize, tuple(g['color']) + (0,))
            lay.putalpha(m.point(lambda v: min(255, int(v * kk))))
            out.alpha_composite(lay)
        if E is not None:
            lay = Image.new('RGBA', self.rsize, tuple(ex['color']) + (0,))
            lay.putalpha(E)
            out.alpha_composite(lay)
        out.alpha_composite(body)
        return out

    def _effects(self, F, S):
        em = self.em
        x0, x1 = self.bx0 - self.rx0 - .1 * em, self.bx1 - self.rx0 + .1 * em
        y0, y1 = self.by0 - self.ry0 - .1 * em, self.by1 - self.ry0 + .1 * em
        if S.wipe is not None:
            fr, d = S.wipe
            w, h = self.rsize
            soft = .12 * em
            m = Image.new('L', (w, h), 0)
            dr = ImageDraw.Draw(m)
            edge = Image.new('L', (w, h), 0)
            de = ImageDraw.Draw(edge)
            ew = .3 * em
            if d == 'L':                                    # 範囲の左端から右端まで（横いっぱいの帯を端から開く）
                x = lerp(0, w, fr)
                dr.rectangle([0, 0, x, h], fill=255)
                de.rectangle([x - ew, 0, x + ew * .3, h], fill=255)
            elif d in ('l', 'r'):
                x = lerp(x0, x1, fr) if d == 'l' else lerp(x1, x0, fr)
                dr.rectangle([0, 0, x, h] if d == 'l' else [x, 0, w, h], fill=255)
                de.rectangle([x - ew, 0, x + ew * .3, h] if d == 'l' else [x - ew * .3, 0, x + ew, h], fill=255)
            elif d == 'c':
                c, half = (x0 + x1) / 2, (x1 - x0) / 2 * fr
                dr.rectangle([c - half, 0, c + half, h], fill=255)
                de.rectangle([c - half - ew * .3, 0, c - half + ew, h], fill=255)
                de.rectangle([c + half - ew, 0, c + half + ew * .3, h], fill=255)
            else:
                y = lerp(y1, y0, fr)
                dr.rectangle([0, y, w, h], fill=255)
                de.rectangle([0, y - ew * .3, w, y + ew], fill=255)
            m = m.filter(ImageFilter.GaussianBlur(soft / 2))
            A = F.getchannel('A')
            F = F.copy()
            F.putalpha(ImageChops.multiply(A, m))
            if 0 < fr < 1:                                  # ワイプの先頭が光る
                edge = ImageChops.multiply(edge.filter(ImageFilter.GaussianBlur(ew / 3)),
                                           A.filter(ImageFilter.GaussianBlur(.08 * em)).point(lambda v: min(255, v * 2)))
                lay = Image.new('RGBA', F.size, (255, 255, 235, 0))
                lay.putalpha(edge.point(lambda v: int(v * .95)))
                F.alpha_composite(lay)
        if S.blinds is not None:
            w, h = self.rsize
            sl = max(6, int(em / 3))
            col = Image.new('L', (1, h), 0)
            col.putdata([255 if ((y - int(y0)) % sl) / sl < S.blinds else 0 for y in range(h)])
            F = F.copy()
            F.putalpha(ImageChops.multiply(F.getchannel('A'), col.resize((w, h))))
        if S.bloom > .004:                                  # グロー：字を白く飛ばし、字より太い白い光の塊を重ねる（ワイプの先端にも付いていく）
            A = F.getchannel('A')
            fat = A.filter(ImageFilter.GaussianBlur(max(1.0, .035 * em))).point(lambda v: min(255, v * 2))
            fat = fat.filter(ImageFilter.GaussianBlur(max(1.0, .03 * em)))
            wh = Image.new('RGBA', F.size, (255, 255, 255, 0))
            wh.putalpha(A)
            F = Image.blend(F, wh, min(1.0, S.bloom))
            lay = Image.new('RGBA', F.size, (255, 255, 250, 0))
            lay.putalpha(fat.point(lambda v: int(v * min(1.0, S.bloom))))
            F.alpha_composite(lay)
        if S.shine is not None:
            w, h = self.rsize
            bw = .5 * em
            x = lerp(x0 - bw * 2, x1 + bw * 2, S.shine)
            band = Image.new('L', (w, h), 0)
            ImageDraw.Draw(band).polygon([(x, y0), (x + bw, y0), (x + bw - .5 * (y1 - y0), y1), (x - .5 * (y1 - y0), y1)], fill=255)
            band = ImageChops.multiply(band.filter(ImageFilter.GaussianBlur(bw / 5)), F.getchannel('A'))
            lay = Image.new('RGBA', F.size, (255, 255, 255, 0))
            lay.putalpha(band.point(lambda v: int(v * .8)))
            F = F.copy()
            F.alpha_composite(lay)
        if S.flash > .01:
            wh = Image.new('RGBA', F.size, (255, 255, 255, 0))
            wh.putalpha(F.getchannel('A'))
            F = Image.blend(F, wh, min(1.0, S.flash))
        if S.chroma > .5:
            d = int(round(S.chroma))
            r, g, b, a = F.convert('RGBa').split()
            A = F.getchannel('A')
            r, b = ImageChops.offset(r, -d, 0), ImageChops.offset(b, d, 0)
            al = ImageChops.lighter(ImageChops.lighter(ImageChops.offset(A, -d, 0), A), ImageChops.offset(A, d, 0))
            F = Image.merge('RGBa', (r, g, b, al)).convert('RGBA')
        if S.blur[0] > .5 or S.blur[1] > .5:
            F = F.convert('RGBa').filter(ImageFilter.GaussianBlur((S.blur[0] / 2, S.blur[1] / 2))).convert('RGBA')
        return F

    def _region(self, S):
        if S.rest_inner():
            if self._rest is None:
                self._rest = self._under(self._compose(S), S)
            return self._rest
        return self._effects(self._under(self._compose(S), S), S)

    def _place(self, canvas, F, S, alpha=1.0):
        a = S.a * alpha
        if a <= .004:
            return
        if S.floor is not None:                            # 床より下を切る：いったん全画面に置いてから下を消す
            tmp = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
            fl, S.floor = S.floor, None
            self._place(tmp, F, S, alpha)
            S.floor = fl
            y = max(0, min(self.H, int(round(fl))))
            if y < self.H:
                tmp.paste((0, 0, 0, 0), (0, y, self.W, self.H))
            canvas.alpha_composite(tmp)
            return
        if S.dx == 0 and S.dy == 0 and S.rot == 0 and S.sx == 1 and S.sy == 1:
            im = F
            if a < 1:
                im = F.copy()
                im.putalpha(im.getchannel('A').point(lambda v: int(v * a)))
            self._put(canvas, im, self.rx0, self.ry0)
            return
        th = math.radians(S.rot)
        c, s = math.cos(th), math.sin(th)
        sx, sy = (S.sx if abs(S.sx) > .01 else .01), (S.sy if abs(S.sy) > .01 else .01)
        cx, cy = self.cx + S.dx, self.cy + S.dy
        co = (c / sx, s / sx, -(c * cx + s * cy) / sx + self.cx - self.rx0,
              -s / sy, c / sy, (s * cx - c * cy) / sy + self.cy - self.ry0)
        im = F.convert('RGBa').transform((self.W, self.H), Image.AFFINE, co, resample=Image.BICUBIC).convert('RGBA')
        if a < 1:
            im.putalpha(im.getchannel('A').point(lambda v: int(v * a)))
        canvas.alpha_composite(im)

    def frame(self, f):
        S = self.state(f)
        if S.rest_inner() and S.rest_block() and not S.ghosts and not S.echo and S.floor is None:
            if self._rest_frame is None:
                c = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
                self._place(c, self._region(S), S)
                self._rest_frame = c
            return self._rest_frame
        canvas = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        if S.echo:                                         # 余韻：止まった絵の写しを大きくして後ろに薄く
            if self._rest is None:
                self._rest = self._under(self._compose(St()), St())
            for sc, al in S.echo:
                E = St()
                E.dx, E.dy, E.rot, E.sx, E.sy = S.dx, S.dy, S.rot, S.sx * sc, S.sy * sc
                self._place(canvas, self._rest, E, al)
        for df, al in sorted(S.ghosts, reverse=True):
            if f - df >= 0:
                G = self.state(f - df, ghosts=False)
                self._place(canvas, self._region(G), G, al)
        S = self.state(f)
        self._place(canvas, self._region(S), S)
        return canvas

    def still(self):
        """止まったときの絵（全画面）。仮の静止画・点検・装飾の PNG に使う"""
        S = St()
        c = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        self._place(c, self._under(self._compose(S), S), S)
        return c

    def rest_bbox(self):
        """止まったときの外形（縁の外側まで）の四角 (x0, y0, x1, y1)"""
        return (self.bx0, self.by0, self.bx1, self.by1)


def deco_widths(st, px, own):
    """装飾の縁の太さ（px・字面からの距離）。型のいちばん内側の縁は文字クリップ自身の縁取り（own）が受け持つので描かず（0）、
    それより外の縁は、型での間隔のまま own の外側に積む（例：fuchi＝色・白・黒 → 文字クリップの縁・白・黒）"""
    if not st['layers']:
        return []
    wmin = min(l['w'] for l in st['layers'])
    return [own + int(round((l['w'] - wmin) * px)) if l['w'] > wmin else 0 for l in st['layers']]


def deco_outer_px(fx, color, px, own):
    """装飾の縁が字面から外へ出る幅（px）。文字クリップの幅の上限を決めるのに使う"""
    st = style_of(resolve_fx(fx)['style'], color)
    return max(deco_widths(st, px, own) + [own]) + (abs(st['extrude']['dx']) * px if st.get('extrude') else 0)


def deco_image(line, fx, L, font_ps, own_stroke):
    """文字クリップ1行の後ろに敷く装飾（外側の縁・グロー・影・台座）の全画面 PNG。line = {'text','color','px','baseline'}"""
    t = FxTelop({'lines': [dict(line, delay=0)], 'fx': fx, 'font_ps': font_ps}, L, 1, mode='string', own_stroke=own_stroke)
    return t.still()


# ---------------------------------------------------------------- 書き出し
PRORES = ['-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-vendor', 'apl0', '-alpha_bits', '16']


# ---------------------------------------------------------------- 3D 回転（2026-11-07）
# 金の枠の四角い柱（縦の軸で回る）に、行ごとの面を貼る。横（axis x）は、横書きの面で縦の柱を作ってから絵ごと 90 度回す。
# numpy は使わない（numpy のない環境でも動くように）。縦書きは 1 文字ずつ置く（縦書きの仕組み raqm のない PIL でも動くように）
_TATE_ROT = set('ー〜～－—―…‥()（）「」『』[]［］-→←=＝')
_TATE_SMALL = set('ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ')
_TATE_PUNCT = set('、。，．,.')
GOLD = [(0, (255, 246, 170)), (.35, (250, 206, 50)), (.7, (226, 150, 10)), (1, (150, 86, 0))]
# 枠の種類（fx の frame）：kin＝金（既定）・gin＝銀・shiro＝白（明るいポップ）・nashi＝枠なし（平らな板の柱）
KAITEN_FRAMES = {
    'kin': dict(grad=GOLD, line=(120, 70, 0)),
    'gin': dict(grad=[(0, (255, 255, 255)), (.35, (214, 220, 232)), (.7, (150, 158, 176)), (1, (80, 86, 100))], line=(60, 64, 78)),
    'shiro': dict(grad=[(0, (255, 255, 255)), (.6, (246, 246, 250)), (1, (200, 204, 214))], line=(150, 154, 166)),
    'nashi': None,
}


def _persp_coeffs(dst, src):
    """出力の4点 dst → 入力の4点 src の射影変換（PIL の PERSPECTIVE の8つの値）。8元の連立方程式を素の Python で解く"""
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    n = 8
    M = [row[:] + [b] for row, b in zip(A, B)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        pv = M[c][c] or 1e-12
        for r in range(n):
            if r != c:
                k = M[r][c] / pv
                if k:
                    M[r] = [a - k * b for a, b in zip(M[r], M[c])]
    return [M[i][n] / (M[i][i] or 1e-12) for i in range(n)]


class Kaiten:
    """3D 回転テロップ。item の行＝柱の面（2行なら 1・2 面目、3・4 面目はその繰り返し）。
    fx：axis（y＝縦の柱・縦書き／x＝横の帯・横書き）・turn_at（面が替わる秒の並び。なければ各行の出る時刻＝anchor、それもなければ等分）・
    yaw（止まったときの斜めの角度・既定 16 度＝左の面が見え、次の面は見えない）・peek（真なら次の面を横にのぞかせる＝見本の動画と同じ向き）・
    in（kaiten_in＝回りながら出る／cut）"""
    TURN = 12                                          # 1 面ぶん回るフレーム数

    def __init__(self, item, L, n):
        self.it, self.L, self.n = item, L, max(1, n)
        self.W, self.H = L['W'], L['H']
        self.fx = resolve_fx(item.get('fx') or {})
        self.axis = self.fx.get('axis', 'y')
        lines = [l for l in item['lines'] if l['text'].strip()] or item['lines'][:1]
        self.lines = lines
        self.px = max(l['px'] for l in lines)
        self.cy = sum(l['baseline'] - .38 * l['px'] for l in lines) / len(lines)
        self.in_total = 0 if self.fx['in'] == 'cut' else self.fx.get('in_dur', 16)
        self.frame_def = KAITEN_FRAMES.get(self.fx.get('frame', 'kin'), KAITEN_FRAMES['kin']) if self.fx.get('frame') != 'nashi' else None
        self._faces()
        self._turns()
        self._cache = {}

    # ---- 面の絵
    def _face_img(self, text, key, fw, fh, cs):
        S = 2
        W, H = fw * S, fh * S
        C = KAITEN_PANEL.get(key, KAITEN_PANEL['r'])
        img = grad_img((W, H), [(0, lighten(C, .22)), (.5, C), (1, darken(C, .3))], 0, H).convert('RGBA')
        sh = Image.new('L', (W, H), 0)                 # 斜めの照り
        ImageDraw.Draw(sh).polygon([(0, H * .05), (W, 0), (W, H * .18), (0, H * .42)], fill=46)
        sh = sh.filter(ImageFilter.GaussianBlur(W * .04))
        img = Image.composite(Image.new('RGBA', (W, H), (255, 255, 255, 255)), img, sh)
        fr = self.frame_def
        bw = (int(fw * .085 * S) if self.axis == 'y' else int(fh * .085 * S)) if fr else 0
        cap = int((fw if self.axis == 'y' else fh) * .16 * S) if fr else 0     # 上下の金のふた（横の帯では左右）
        G = fr['grad'] if fr else GOLD
        gold_v = grad_img((W, H), G, 0, H).convert('RGBA')
        gold_h = grad_img((H, W), G, 0, W).convert('RGBA').rotate(90, expand=True).resize((W, H))
        m = Image.new('L', (W, H), 0)
        dm = ImageDraw.Draw(m)
        if self.axis == 'y':
            dm.rectangle([0, 0, W, H], fill=255)
            dm.rectangle([bw, cap, W - bw, H - cap], fill=0)
        else:
            dm.rectangle([0, 0, W, H], fill=255)
            dm.rectangle([cap, bw, W - cap, H - bw], fill=0)
        if fr:
            img.paste(gold_v if self.axis == 'y' else gold_h, (0, 0), m)
        d = ImageDraw.Draw(img)
        lw = max(2, S * 2)
        ln = fr['line'] if fr else darken(C, .5)
        if not fr:                                      # 枠なし：面の縁に細い白い線だけ
            d.rectangle([lw, lw, W - lw, H - lw], outline=(255, 255, 255, 200), width=lw)
        elif self.axis == 'y':
            d.rectangle([bw, cap, W - bw, H - cap], outline=darken(C, .6) + (255,), width=lw)
            d.line([(0, cap), (W, cap)], fill=ln + (255,), width=lw)
            d.line([(0, H - cap), (W, H - cap)], fill=ln + (255,), width=lw)
        else:
            d.rectangle([cap, bw, W - cap, H - bw], outline=darken(C, .6) + (255,), width=lw)
            d.line([(cap, 0), (cap, H)], fill=ln + (255,), width=lw)
            d.line([(W - cap, 0), (W - cap, H)], fill=ln + (255,), width=lw)
        # 字（白＋面の色の濃い縁）
        f = fx_font('W9', cs * S)
        sw = max(2, int(cs * S * .1))
        ink = darken(C, .62) + (255,)
        if self.axis == 'y':
            chars = list(text)
            step = cs * S * 1.0
            y = H / 2 - step * len(chars) / 2 + step / 2
            for ch in chars:
                cx, cy = W / 2, y
                if ch in _TATE_SMALL:
                    cx, cy = cx + cs * S * .1, cy - cs * S * .1
                if ch in _TATE_PUNCT:
                    cx, cy = cx + cs * S * .32, cy - cs * S * .32
                if ch in _TATE_ROT:
                    g = Image.new('RGBA', (int(step * 1.6), int(step * 1.6)), (0, 0, 0, 0))
                    ImageDraw.Draw(g).text((g.width / 2, g.height / 2), ch, font=f, fill=WHITE + (255,), anchor='mm',
                                           stroke_width=sw, stroke_fill=ink)
                    g = g.rotate(-90, resample=Image.BICUBIC)
                    img.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
                else:
                    d.text((cx, cy), ch, font=f, fill=WHITE + (255,), anchor='mm', stroke_width=sw, stroke_fill=ink)
                y += step
        else:
            d.text((W / 2, H / 2), text, font=f, fill=WHITE + (255,), anchor='mm', stroke_width=sw, stroke_fill=ink, **FEAT)
        return img.resize((fw, fh), Image.LANCZOS)

    def _faces(self):
        texts = [(l['text'].strip(), l.get('color', self.fx.get('color', 'r'))) for l in self.lines]
        sx0, sy0, sx1, sy1 = safe_rect(self.L)
        cs = self.px
        if self.axis == 'y':
            nmax = max(len(t) for t, _ in texts)
            cs = min(cs, (sy1 - sy0) * self.fx.get('tall', .62) / (nmax * 1.0 + 1.2))   # 柱が画面の 6 割を超えないように（tall で変える）
            fw, fh = int(cs * 1.62), int(cs * (nmax * 1.0 + .5) + cs * 1.62 * .32)
        else:
            f = fx_font('W9', cs)
            wmax = max(f.getlength(t, **FEAT) for t, _ in texts)
            k = min(1.0, (sx1 - sx0) * .78 / (wmax + cs * 1.0))
            cs *= k
            wmax *= k
            fh, fw = int(cs * 1.62), int(wmax + cs * .6 + cs * 1.62 * .32)
        self.cs, self.fw, self.fh = cs, fw, fh
        faces = [self._face_img(t, c, fw, fh, cs) for t, c in texts]
        peek = self.fx.get('peek')
        while len(faces) < 4:                           # 使わない面：peek なら字の面の繰り返し、ふだんは無地（次の答えを先に見せない）
            faces.append(faces[len(faces) % len(texts)] if peek else self._face_img('', texts[0][1], fw, fh, cs))
        self.faces = faces[:4] if len(texts) <= 4 else faces
        if self.axis == 'x':                            # 横の帯：面を縦にして縦の柱として描き、最後に絵ごと戻す
            self.faces = [f.rotate(-90, expand=True) for f in self.faces]
        self.nf = len(self.faces)
        g = 64
        self.top = grad_img((g, g), (self.frame_def or KAITEN_FRAMES['kin'])['grad'], 0, g).convert('RGBA')

    # ---- 回るタイミング
    def _turns(self):
        fps = 30
        ta = self.fx.get('turn_at')
        k = len(self.lines)
        if ta:
            at = [int(round(v * fps)) for v in ta]
        elif any(int(l.get('delay') or 0) for l in self.lines[1:]):
            at = [int(l.get('delay') or 0) for l in self.lines[1:]]
        else:
            free = max(1, self.n - self.in_total)
            at = [self.in_total + int(free * i / k) - self.TURN // 2 for i in range(1, k)]
        self.at = sorted(max(self.in_total, a) for a in at)

    def _pose(self, f):
        """（向き yaw 度・大きさ・不透明度）"""
        rest = self.fx.get('yaw', -16 if self.fx.get('peek') else 16)    # 既定は左の面（前の面か無地）が見える向き＝次の面（右）は隠れる
        yaw, sc, a = rest, 1.0, 1.0
        if f < self.in_total:
            t = f / max(1, self.in_total)
            yaw = rest - 200 * (1 - back(t, 1.3))
            sc = .55 + .45 * eo(t)
            a = min(1.0, t * 3)
        for i, s0 in enumerate(self.at):
            t = (f - s0) / self.TURN
            if t >= 1:
                yaw -= 90
            elif t > 0:
                yaw -= 90 * back(t, 1.5)
        return yaw, sc, a

    # ---- 描く
    def _render(self, yaw, sc):
        key = (round(yaw, 2), round(sc, 3))
        if key in self._cache:
            return self._cache[key]
        S = 2
        aw = self.fw / 2 if self.axis == 'y' else self.fh / 2      # 柱の半分の幅（奥行きも同じ）
        hh = (self.fh if self.axis == 'y' else self.fw) / 2       # 柱の半分の高さ
        cap_o, cap_h = aw * .1, aw * .3                            # ふたのはみ出し・厚み
        pitch = math.radians(-10)
        D = hh * 7
        size = int((max(aw, hh) * 2.6 + cap_h * 2) * S)
        cv = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        c0 = size / 2
        cyw, syw = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cp, sp = math.cos(pitch), math.sin(pitch)

        def xf(p):
            x, y, z = p
            x, z = x * cyw + z * syw, -x * syw + z * cyw              # 縦の軸で回す
            y, z = y * cp - z * sp, y * sp + z * cp                    # 少し上から見下ろす
            return x, y, z

        def pj(p):
            x, y, z = xf(p)
            k = D / (D - z) * sc * S
            return (c0 + x * k, c0 - y * k)

        light = (-.35, .45, .82)
        ln = math.sqrt(sum(v * v for v in light))
        light = tuple(v / ln for v in light)

        def quad(pts3, tex, normal):
            c = [sum(p[i] for p in pts3) / 4 for i in range(3)]
            nx, ny, nz = xf(normal)
            cx, cyy, cz = xf(c)
            if nx * (0 - cx) + ny * (0 - cyy) + nz * (D - cz) <= 0:   # 裏向きは描かない
                return None
            pts = [pj(p) for p in pts3]
            lum = .52 + .48 * max(0.0, nx * light[0] + ny * light[1] + nz * light[2])
            return (cz, pts, tex, lum)

        def box(a, h, yc, texs, top_tex, bot=False):
            out = []
            for i in range(4):
                th = math.radians(i * 90)
                n = (math.sin(th), 0, math.cos(th))
                t = (math.cos(th), 0, -math.sin(th))
                cc = (a * n[0], yc, a * n[2])
                p = [(cc[0] - a * t[0], yc + h, cc[2] - a * t[2]), (cc[0] + a * t[0], yc + h, cc[2] + a * t[2]),
                     (cc[0] + a * t[0], yc - h, cc[2] + a * t[2]), (cc[0] - a * t[0], yc - h, cc[2] - a * t[2])]
                q = quad(p, texs[i % len(texs)], n)
                if q:
                    out.append(q)
            p = [(-a, yc + h, -a), (a, yc + h, -a), (a, yc + h, a), (-a, yc + h, a)]
            q = quad(p, top_tex, (0, 1, 0))
            if q:
                out.append(q)
            return out

        gold = self.top
        body = box(aw, hh, 0, self.faces, gold if self.frame_def else self.faces[0].resize((8, 8)).resize((64, 64)))
        capt = box(aw + cap_o, cap_h / 2, hh + cap_h / 2, [gold], gold) if self.frame_def else []
        capb = box(aw + cap_o, cap_h / 2, -hh - cap_h / 2, [gold], gold) if self.frame_def else []
        for group in (capb, body, capt):                 # 下のふた → 柱 → 上のふた（上から見下ろすので）
            for cz, pts, tex, lum in sorted(group, key=lambda q: q[0]):
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                x0, y0 = int(math.floor(min(xs))) - 2, int(math.floor(min(ys))) - 2
                x1, y1 = int(math.ceil(max(xs))) + 2, int(math.ceil(max(ys))) + 2
                w, h = max(1, x1 - x0), max(1, y1 - y0)
                tw, th_ = tex.size
                co = _persp_coeffs([(p[0] - x0, p[1] - y0) for p in pts], [(0, 0), (tw, 0), (tw, th_), (0, th_)])
                src = tex if lum >= .999 else Image.merge('RGBA', [*(ch.point(lambda v, k=lum: int(v * k)) for ch in tex.split()[:3]),
                                                                     tex.split()[3]])
                im = src.transform((w, h), Image.PERSPECTIVE, co, resample=Image.BICUBIC)
                mk = Image.new('L', (w, h), 0)
                ImageDraw.Draw(mk).polygon([(p[0] - x0, p[1] - y0) for p in pts], fill=255)
                im.putalpha(ImageChops.multiply(im.getchannel('A'), mk))
                cv.alpha_composite(im, (x0, y0))
        cv = cv.resize((size // S, size // S), Image.LANCZOS)
        if self.axis == 'x':
            cv = cv.rotate(90, resample=Image.BICUBIC)
        sh = cv.getchannel('A').filter(ImageFilter.GaussianBlur(self.cs * .12)).point(lambda v: int(v * .55))
        out = Image.new('RGBA', cv.size, (0, 0, 0, 0))
        out.paste((0, 0, 0, 255), (int(self.cs * .05), int(self.cs * .08)), sh)
        out.putalpha(ImageChops.lighter(out.getchannel('A'), Image.new('L', cv.size, 0)))
        out.alpha_composite(cv)
        if len(self._cache) > 400:
            self._cache.clear()
        self._cache[key] = out
        return out

    def frame(self, f):
        yaw, sc, a = self._pose(f)
        loc = self._render(yaw, sc)
        if a < 1:
            loc = loc.copy()
            loc.putalpha(loc.getchannel('A').point(lambda v, k=a: int(v * k)))
        c = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        c.alpha_composite(loc, (int(self.W / 2 - loc.width / 2), int(self.cy - loc.height / 2)))
        return c

    def still(self):
        return self.frame(self.in_total + 2)

    def rest_bbox(self):
        bb = [self.frame(max(self.in_total, s - 1)).getbbox() for s in [self.in_total + 2] + [a + self.TURN + 1 for a in self.at]]
        bb = [b for b in bb if b]
        return (min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)) if bb else None


# ---------------------------------------------------------------- 縦の札（2026-11-07・街頭インタビュー風）
# 写真や映像の横に立てる縦書きの札（「実際の寝顔写真」）。行＝列（右から左へ並べる）。色の板に白い字（白・黄の板は黒い字）。
# 置き場所：fx の align（l＝左の端・既定／r＝右の端／c＝真ん中）、縦はテロップの高さ（spec の y）を札の真ん中に
def st_tatefuda(C, key):
    """縦の札：色の板（行の色・既定は赤）に白い縦書きの字（写真の横に「実際の○○」）"""
    return dict(font='W9', fill=[(0, WHITE), (1, WHITE)])


class TateFuda:
    def __init__(self, item, L, n):
        self.it, self.L, self.n = item, L, max(1, n)
        self.W, self.H = L['W'], L['H']
        self.fx = resolve_fx(item.get('fx') or {})
        self.in_total = 0
        lines = [l for l in item['lines'] if l['text'].strip()] or item['lines'][:1]
        px = max(l['px'] for l in lines)
        cs = int(px * .56)                                   # 札の字は本文のテロップの半分ほど
        key = self.fx.get('tint') or lines[0].get('color', self.fx.get('color', 'r'))
        C = {'r': (214, 18, 30)}.get(key, BASE.get(key, BASE['r']))
        ink = INK if key in ('w', 'y', 'c') else WHITE
        S = 2
        step = cs * 1.02
        colw = cs * 1.25
        rows = max(len(l['text'].strip()) for l in lines)
        pad = cs * .32
        bw, bh = colw * len(lines) + pad * 2, step * rows + pad * 2
        img = Image.new('RGBA', (int((bw + cs) * S), int((bh + cs) * S)), (0, 0, 0, 0))
        ox, oy = cs * .4, cs * .4
        d = ImageDraw.Draw(img)
        sh = Image.new('L', img.size, 0)                     # 落ち影
        ImageDraw.Draw(sh).rectangle([(ox + cs * .08) * S, (oy + cs * .12) * S, (ox + bw + cs * .08) * S, (oy + bh + cs * .12) * S], fill=150)
        sh = sh.filter(ImageFilter.GaussianBlur(cs * .1 * S))
        img.paste(Image.new('RGBA', img.size, (0, 0, 0, 255)), (0, 0), sh)
        g = grad_img(img.size, [(0, lighten(C, .18)), (.5, C), (1, darken(C, .25))], oy * S, (oy + bh) * S).convert('RGBA')
        m = Image.new('L', img.size, 0)
        ImageDraw.Draw(m).rectangle([ox * S, oy * S, (ox + bw) * S, (oy + bh) * S], fill=255)
        img.paste(g, (0, 0), m)
        d.rectangle([ox * S, oy * S, (ox + bw) * S, (oy + bh) * S], outline=darken(C, .55) + (255,), width=max(2, int(cs * .06 * S)))
        e = max(1, int(cs * .035 * S))
        d.rectangle([(ox + e / S * 2) * S, (oy + e / S * 2) * S, (ox + bw - e / S * 2) * S, (oy + bh - e / S * 2) * S],
                    outline=(255, 255, 255, 200), width=e)
        f = fx_font('W9', cs * S)
        for ci, l in enumerate(lines):                       # 1 行目が右の列
            cx = ox + bw - pad - colw * (ci + .5)
            chars = list(l['text'].strip())
            y = oy + bh / 2 - step * len(chars) / 2 + step / 2
            for ch in chars:
                x_, y_ = cx, y
                if ch in _TATE_SMALL:
                    x_, y_ = x_ + cs * .1, y_ - cs * .1
                if ch in _TATE_PUNCT:
                    x_, y_ = x_ + cs * .32, y_ - cs * .32
                if ch in _TATE_ROT:
                    gg = Image.new('RGBA', (int(step * 1.6 * S), int(step * 1.6 * S)), (0, 0, 0, 0))
                    ImageDraw.Draw(gg).text((gg.width / 2, gg.height / 2), ch, font=f, fill=ink + (255,), anchor='mm')
                    gg = gg.rotate(-90, resample=Image.BICUBIC)
                    img.alpha_composite(gg, (int(x_ * S - gg.width / 2), int(y_ * S - gg.height / 2)))
                else:
                    d.text((x_ * S, y_ * S), ch, font=f, fill=ink + (255,), anchor='mm')
                y += step
        img = img.resize((int(img.width / S), int(img.height / S)), Image.LANCZOS)
        sx0, sy0, sx1, sy1 = safe_rect(L)
        al = self.fx.get('align') or 'l'
        cy = sum(l['baseline'] - .38 * l['px'] for l in lines) / len(lines)
        m_ = cs * .45                                         # 落ち影のぼけの分だけ内側に（セーフティエリアの外に出さない）
        x = sx0 - ox + m_ if al == 'l' else (sx1 - bw - ox - m_ if al == 'r' else self.W / 2 - bw / 2 - ox)
        y = min(max(cy - bh / 2, sy0 + m_), sy1 - bh - m_) - oy
        self.img = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        self.img.alpha_composite(img, (int(x), int(y)))
        self.blank = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))

    def frame(self, f):
        return self.img if 0 <= f < self.n else self.blank

    def still(self):
        return self.img

    def rest_bbox(self):
        return self.img.getbbox()


# ---------------------------------------------------------------- 4択パネル（2026-11-07）
# クイズ番組風：黒い六角の板に光る縁、左右の先から画面の端まで光る線。縦の画面向けに、問題の下へ選択肢を縦に積む。
# 1行目＝問題、2行目から＝選択肢。fx：answer（正解の記号か番号）・pick（選んだ答え＝橙）・pick_at／reveal_at（秒）・labels・edge（縁の色）
QUIZ_EDGE = (40, 150, 255)
# 見た目の組（fx の theme）：std＝黒い板・青い縁・選んだ答え橙・正解緑／nhk＝紺の板・黄の縁・選んだ答え白・正解黄（NHK 系のサムネと同じ紺＋黄）
QUIZ_THEMES = {
    'std': dict(edge=QUIZ_EDGE, label=(255, 196, 30), fill=[(0, (26, 30, 52)), (.5, (6, 8, 18)), (1, (0, 0, 0))],
                pick=[(0, (255, 196, 80)), (.5, (240, 140, 10)), (1, (196, 90, 0))],
                ok=[(0, (120, 236, 120)), (.5, (36, 176, 60)), (1, (14, 120, 40))],
                flash=[(0, (240, 255, 240)), (.5, (150, 250, 150)), (1, (60, 200, 80))], ink_on=INK),
    'nhk': dict(edge=(255, 206, 0), label=(255, 214, 0), fill=[(0, (34, 58, 132)), (.5, (14, 30, 86)), (1, (6, 14, 50))],
                pick=[(0, (255, 255, 255)), (.5, (228, 234, 246)), (1, (190, 200, 222))],
                ok=[(0, (255, 240, 120)), (.5, (255, 212, 0)), (1, (226, 160, 0))],
                flash=[(0, (255, 255, 255)), (.5, (255, 246, 170)), (1, (255, 220, 60))], ink_on=(14, 30, 86)),
}


class Yontaku:
    APPEAR = 8                                       # 板が開くフレーム数

    def __init__(self, item, L, n):
        self.it, self.L, self.n = item, L, max(1, n)
        self.W, self.H = L['W'], L['H']
        self.fx = resolve_fx(item.get('fx') or {})
        lines = [l for l in item['lines'] if l['text'].strip()] or item['lines'][:1]
        self.q, self.ch = lines[0], lines[1:]
        self.theme = QUIZ_THEMES.get(self.fx.get('theme', 'std'), QUIZ_THEMES['std'])
        e = self.fx.get('edge')
        self.edge = self.theme['edge'] if e is None else _glow_color(e)
        self.labels = list(self.fx.get('labels') or 'ABCDEF')
        px0 = max(l['px'] for l in lines)
        sx0, sy0, sx1, sy1 = safe_rect(L)
        self.x0, self.x1 = sx0 + 6, sx1 - 6
        self.qpx = min(px0, 82)
        self.apx = round(self.qpx * .86)
        self.qrows = self._wrap(self.q['text'].strip(), self.qpx, self.x1 - self.x0 - self.qpx * 1.3)
        self.qh = int(self.qpx * (1.0 + 1.18 * len(self.qrows)))
        self.ah = int(self.apx * 1.75)
        self.gap = int(self.apx * .34)
        total = self.qh + (self.gap * 1.6 if self.ch else 0) + len(self.ch) * self.ah + max(0, len(self.ch) - 1) * self.gap
        cy = sum(l['baseline'] - .38 * l['px'] for l in lines) / len(lines)
        bottom = min(sy1, self.H * .74) if self.H > self.W else sy1     # 縦の画面：下の帯（スマホの YouTube の操作部・y1440〜）にかけない
        top = max(sy0, min(cy - total / 2, bottom - total))
        self.boxes = [(top, top + self.qh)]
        y = top + self.qh + self.gap * 1.6
        for _ in self.ch:
            self.boxes.append((y, y + self.ah))
            y += self.ah + self.gap
        # 出る時刻：問題は 0、選択肢は各行の出る時刻（anchor）。なければ 8 フレームずつ
        dl = [int(l.get('delay') or 0) for l in self.ch]
        self.t_in = [0] + (dl if any(dl) else [10 + 8 * i for i in range(len(self.ch))])
        self.in_total = max(self.t_in) + self.APPEAR if self.fx['in'] != 'cut' else 0
        if self.fx['in'] == 'cut':
            self.t_in = [0] * len(self.t_in)
        fps = 30
        self.ans = self._idx(self.fx.get('answer'))
        self.pick = self._idx(self.fx.get('pick'))
        last = max(self.t_in) + self.APPEAR
        ra, pa = self.fx.get('reveal_at'), self.fx.get('pick_at')
        # 明かす時刻：既定は選択肢が出そろって 1 秒ほどあと（テロップの終わりの 0.6 秒前より遅くしない＝必ずテロップの中で明かす）
        self.t_reveal = (int(round(ra * fps)) if ra is not None else
                         (max(min(max(last + 30, self.n - 45), self.n - 18), min(last, self.n - 1)) if self.ans is not None else None))
        self.t_pick = int(round(pa * fps)) if pa is not None else ((last + (self.t_reveal - last) // 2) if (self.pick is not None and self.t_reveal)
                                                                    else (last + 24 if self.pick is not None else None))
        self._cache = {}

    def _idx(self, v):
        if v is None or not self.ch:
            return None
        i = (v - 1) if isinstance(v, int) else (self.labels.index(v.upper()) if v.upper() in self.labels else None)
        return i if i is not None and 0 <= i < len(self.ch) else None

    def _wrap(self, text, px, maxw):
        f = fx_font('W9', px)
        if f.getlength(text, **FEAT) <= maxw:
            return [text]
        parts = text.split(' ') if ' ' in text or '　' in text else None
        if parts:
            parts = text.replace('　', ' ').split(' ')
            best = min(range(1, len(parts)), key=lambda i: abs(f.getlength(' '.join(parts[:i]), **FEAT) - f.getlength(' '.join(parts[i:]), **FEAT)))
            return [' '.join(parts[:best]), ' '.join(parts[best:])]
        m = len(text) // 2
        return [text[:m], text[m:]]

    def _panel(self, i, state):
        """i 番目の板（0＝問題）の絵（範囲の大きさ・板＋光る縁＋字）。state：normal／pick／ok／okflash"""
        key = (i, state)
        if key in self._cache:
            return self._cache[key]
        y0, y1 = self.boxes[i]
        h = y1 - y0
        S = 2
        m = int(self.qpx * .5)
        W = int(self.x1 - self.x0 + 2 * m)
        H = int(h + 2 * m)
        tip = h * .42
        pts = [(m, m + h / 2), (m + tip, m), (W - m - tip, m), (W - m, m + h / 2), (W - m - tip, m + h), (m + tip, m + h)]
        P = [(x * S, y * S) for x, y in pts]
        E = self.edge
        th = self.theme
        fill = {'normal': th['fill'], 'pick': th['pick'], 'ok': th['ok'], 'okflash': th['flash']}[state]
        img = Image.new('RGBA', (W * S, H * S), (0, 0, 0, 0))
        mk = Image.new('L', img.size, 0)
        ImageDraw.Draw(mk).polygon(P, fill=255)
        g = grad_img(img.size, fill, m * S, (m + h) * S).convert('RGBA')
        g.putalpha(mk)
        glow = Image.new('L', img.size, 0)
        ImageDraw.Draw(glow).line(P + [P[0]], fill=255, width=int(h * .1 * S), joint='curve')
        glow = glow.filter(ImageFilter.GaussianBlur(h * .09 * S))
        lay = Image.new('RGBA', img.size, E + (0,))
        lay.putalpha(glow.point(lambda v: int(v * .95)))
        img.alpha_composite(lay)
        img.alpha_composite(g)
        d = ImageDraw.Draw(img)
        d.line(P + [P[0]], fill=lighten(E, .55) + (255,), width=max(3, int(h * .045 * S)), joint='curve')
        d.line(P + [P[0]], fill=(255, 255, 255, 235), width=max(1, int(h * .014 * S)), joint='curve')
        # 字
        ink = WHITE if state in ('normal',) else th['ink_on']
        if i == 0:
            f = fx_font('W9', self.qpx * S)
            n = len(self.qrows)
            room = (W - 2 * m - 2 * tip * .8) * S                # 六角の斜めの縁にかからない幅
            for t in self.qrows:
                while f.getlength(t, **FEAT) > room and f.size > 20:
                    f = fx_font('W9', f.size - 2)
            for r, t in enumerate(self.qrows):
                yy = (m + h / 2 + (r - (n - 1) / 2) * self.qpx * 1.18) * S
                d.text((W / 2 * S, yy), t, font=f, fill=ink + (255,), anchor='mm', **FEAT)
        else:
            f = fx_font('W9', self.apx * S)
            lab = self.labels[i - 1] + ':'
            x = (m + tip + self.apx * .35) * S
            yy = (m + h / 2) * S
            r = self.apx * .2 * S
            gold = th['label'] if state == 'normal' else th['ink_on']
            d.ellipse([x - r, yy - r, x + r, yy + r], fill=gold + (255,))
            x += r + self.apx * .3 * S
            d.text((x, yy), lab, font=f, fill=gold + (255,), anchor='lm', **FEAT)
            x += f.getlength(lab, **FEAT) + self.apx * .45 * S
            t = self.ch[i - 1]['text'].strip()
            room = (W - m - tip - self.apx * .3) * S - x
            ft = f
            while ft.getlength(t, **FEAT) > room and ft.size > 20:
                ft = fx_font('W9', ft.size - 2)
            d.text((x, yy), t, font=ft, fill=ink + (255,), anchor='lm', **FEAT)
        img = img.resize((W, H), Image.LANCZOS)
        self._cache[key] = (img, m, tip)
        return self._cache[key]

    def _state(self, i, f):
        if i == 0 or i - 1 not in (self.ans, self.pick):
            return 'normal'
        k = i - 1
        if k == self.ans and self.t_reveal is not None and f >= self.t_reveal:
            r = f - self.t_reveal
            return 'okflash' if r < 18 and (r // 3) % 2 == 0 else 'ok'
        if k == self.pick and self.t_pick is not None and f >= self.t_pick:
            return 'pick'
        return 'normal'

    def frame(self, f):
        c = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(c)
        for i, (y0, y1) in enumerate(self.boxes):
            t = (f - self.t_in[i]) / self.APPEAR if self.fx['in'] != 'cut' else 1
            if t <= 0:
                continue
            img, m, tip = self._panel(i, self._state(i, f))
            sx = eo(t)
            yc = (y0 + y1) / 2
            # 板の先から画面の端まで光る線（板が開いてから伸びる）
            if t >= .6:
                k = min(1.0, (t - .6) / .4)
                lw = max(2, int((y1 - y0) * .035))
                for xa, xb in ((self.x0 - (self.x0) * k, self.x0), (self.x1, self.x1 + (self.W - self.x1) * k)):
                    d.line([(xa, yc), (xb, yc)], fill=lighten(self.edge, .35) + (230,), width=lw)
            if sx < .999:
                w = max(1, int(img.width * sx))
                im = img.resize((w, img.height), Image.BILINEAR)
                im.putalpha(im.getchannel('A').point(lambda v, a=min(1.0, t * 2): int(v * a)))
            else:
                im = img
            c.alpha_composite(im, (int(self.W / 2 - im.width / 2), int(y0 - m)))
        return c

    def still(self):
        return self.frame(self.in_total + 2)

    def rest_bbox(self):
        return self.frame(max(self.in_total, self.n - 1)).getbbox()


def write_mov(telop, dst, fps=30):
    """透明つきの動画（ProRes 4444）に書き出す。フレームは ffmpeg に直接流す"""
    W, H = telop.W, telop.H
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(fps),
                          '-i', '-', *PRORES, str(dst)], stdin=subprocess.PIPE)
    last, buf = None, None
    for f in range(telop.n):
        im = telop.frame(f)
        if im is not last:
            last, buf = im, im.tobytes()
        p.stdin.write(buf)
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f'{Path(dst).name} の書き出しに失敗')
    return dst


# ---------------------------------------------------------------- 見本
def _bg(W, H, seed=3):
    """見本の背景（暗い青〜えんじのグラデーションに光の線）。ショートの動く背景に近い明るさ"""
    g = grad_img((W, H), [(0, (18, 26, 64)), (.55, (34, 30, 78)), (1, (70, 20, 40))], 0, H).convert('RGBA')
    d = ImageDraw.Draw(g)
    r = random.Random(seed)
    for _ in range(26):
        x, y, ln = r.uniform(0, W), r.uniform(0, H), r.uniform(60, 260)
        d.line([(x, y), (x + ln * .12, y + ln)], fill=(255, 255, 255, int(r.uniform(10, 34))), width=3)
    return g


def _cell_telop(lines, fx, W, H, px, n, cy=None):
    L = dict(LAYOUTS['vertical'], W=W, H=H, safe=.06)
    cy = cy if cy is not None else H * .56
    pitch = px * 1.2
    top = cy - pitch * len(lines) / 2
    its = [{'text': t, 'color': c, 'px': px, 'baseline': top + pitch * i + (pitch - px) / 2 + .88 * px, 'delay': 0}
           for i, (t, c) in enumerate(lines)]
    return FxTelop({'lines': its, 'fx': fx}, L, n)


class _QuizCell:
    """4択パネルを縦の画面（1080×1920）で描き、見本の枠（W×H）に収まるよう縮めて返す"""

    def __init__(self, lines, fx, W, H, n):
        L = dict(LAYOUTS['vertical'])
        its = [{'text': t, 'color': c, 'px': 80, 'baseline': 960 + 40 * i, 'delay': 0} for i, (t, c) in enumerate(lines)]
        self.t = Yontaku({'lines': its, 'fx': fx}, L, n)
        self.n, self.in_total, self.W, self.H = n, self.t.in_total, W, H
        bb = self.t.frame(n - 1).getbbox() or (0, 0, 1080, 1920)
        self.box = (0, max(0, bb[1] - 10), 1080, min(1920, bb[3] + 10))
        bw, bh = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.k = min(W * .96 / bw, H * .92 / bh)

    def frame(self, f):
        im = self.t.frame(f).crop(self.box)
        im = im.resize((max(1, int(im.width * self.k)), max(1, int(im.height * self.k))), Image.LANCZOS)
        c = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        c.alpha_composite(im, ((self.W - im.width) // 2, (self.H - im.height) // 2))
        return c


def _quiz_card(lines, fx, W, H, n):
    return _QuizCell(lines, fx, W, H, n)


def _label(img, xy, text, size=22, fill=(255, 255, 255, 235), anchor='la'):
    ImageDraw.Draw(img).text(xy, text, font=fx_font('W6', size), fill=fill, anchor=anchor, stroke_width=3, stroke_fill=(0, 0, 0, 200))


def catalog_styles(out):
    """型の一覧（型ごとに全部の色）。縦 1080 幅の PNG を1枚"""
    keys = ['w', 'y', 'r', 'p', 'o', 'g', 'c', 'b', 'v', 'k']
    cw, ch, px = 540, 132, 76
    names = [k for k in STYLES if k not in ('kaiten', 'yontaku')]        # 3D 回転は面ごとの柱なので型×色の一覧には入れない（カタログで見る）
    head = 96
    rows = (len(keys) + 1) // 2
    blk = head + rows * ch + 30
    W, H = 1080, blk * len(names) + 40
    H += 80
    sheet = _bg(W, H)
    _label(sheet, (30, 22), '決めテロップ（動画）の型 × 色（打ち替えは作り直し）', 38, (120, 230, 255, 255))
    for si, name in enumerate(names):
        y0 = 100 + si * blk
        _label(sheet, (30, y0 + 8), f'{name}', 46, (255, 236, 60, 255))
        _label(sheet, (30 + fx_font('W6', 46).getlength(name) + 24, y0 + 24), STYLES[name][0], 26)
        for ki, key in enumerate(keys):
            t = _cell_telop([('決めテロップ', key)], {'style': name, 'in': 'cut'}, cw, ch, px, 1, cy=ch * .52)
            sheet.alpha_composite(t.still(), ((ki % 2) * cw, y0 + head + (ki // 2) * ch))
            _label(sheet, ((ki % 2) * cw + 14, y0 + head + (ki // 2) * ch + 6), f'{key} {COLOR_LABEL[key]}', 18, (220, 220, 230, 220))
    dst = Path(out) / '見本_3_決めテロップの型.png'
    sheet.convert('RGB').save(dst)
    return dst


def _grid_video(cells, dst, title, fps=30, sec=2.6, loops=2):
    """cells = [(ラベル, 説明, lines, fx)]。2列×3段のページを順に見せる動画（1080×1920）"""
    W, H, cw, ch = 1080, 1920, 540, 580
    top = 150
    n = int(sec * fps)
    pages = [cells[i:i + 6] for i in range(0, len(cells), 6)]
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(fps),
                            '-i', '-', '-c:v', 'libx264', '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(dst)],
                           stdin=subprocess.PIPE)
    for pi, page in enumerate(pages):
        base = _bg(W, H, seed=pi + 1)
        _label(base, (40, 36), title, 46, (255, 236, 60, 255))
        _label(base, (W - 40, 50), f'{pi + 1}/{len(pages)}', 30, anchor='ra')
        d = ImageDraw.Draw(base)
        tels = []
        for k, (lab, desc, lines, fx) in enumerate(page):
            x0, y0 = (k % 2) * cw, top + (k // 2) * ch
            d.rectangle([x0 + 8, y0 + 8, x0 + cw - 8, y0 + ch - 8], outline=(255, 255, 255, 60), width=2)
            _label(base, (x0 + 26, y0 + 22), lab, 34, (120, 230, 255, 255))
            _label(base, (x0 + 26, y0 + 68), desc, 22)
            px = 84 if max(len(t) for t, _ in lines) <= 5 else 62
            if isinstance(fx, tuple) and fx[0] == 'xml':      # XML の範囲の見本（文字クリップ＋キーフレーム）
                tels.append((x0, y0, XmlTelop(lines, cw, ch, px, n - 8, **fx[1])))
            elif resolve_fx(fx)['style'] == 'yontaku':          # 4択は縦の画面で描いて枠に縮める
                tels.append((x0, y0 + 60, _QuizCell(lines, fx, cw, ch - 70, n - 8)))
            else:
                tels.append((x0, y0, _cell_telop(lines, fx, cw, ch, px, n - 8)))
        for _ in range(loops):
            for f in range(n):
                img = base.copy()
                for x0, y0, t in tels:
                    if 4 <= f < 4 + t.n:
                        img.alpha_composite(t.frame(f - 4), (x0, y0))
                enc.stdin.write(img.tobytes())
    enc.stdin.close()
    enc.wait()
    return dst


# ---- XML で出せる範囲（打ち替えられる文字クリップ＋縁の色＋後ろの装飾＋キーフレームの動き）の見本
XML_MOTIONS = {'grow': 'ぐいっと出て大きくなり続ける（いつもの）', 'pop': 'ぽん', 'rise': 'すっ', 'soft': 'ふわぽん（聞き手）',
               'slam': '飛び込み', 'spin': '1回転', **{k: v[0] for k, v in KF_MOTIONS.items()}}


def xml_keys(name, d):
    """XML の動きのキーフレーム（見本用。build_premiere.py の motion_for・add_telop と同じ値）"""
    if name.split('+')[0] in KF_MOTIONS:
        return kf_motion(name, d)
    if name == 'grow':
        return {'scale': [(0, 25), (5, 100), (d - 1, 110)]}
    if name == 'spin':
        return {'scale': [(0, 20), (14, 100)], 'rotation': [(0, -360), (14, 0)]}
    return {'scale': LAYOUTS['vertical']['motion'][name]}


def _kf(keys, f, default):
    if not keys:
        return default
    if f <= keys[0][0]:
        return keys[0][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f <= f1:
            return v0 + (v1 - v0) * (f - f0) / max(1, f1 - f0)
    return keys[-1][1]


class XmlTelop:
    """見本用：文字クリップ（塗り1色＋縁1本）＋後ろの装飾＋キーフレームの動きを、Premiere と同じ決まりで描く。
    拡大・回転の軸は画面の中心（テロップは中心より少し下にある）"""

    def __init__(self, lines, W, H, px, n, motion=None, deco=None, stroke_color=None, cy=None, font_ps='HiraginoSans-W9'):
        self.W, self.H, self.n = W, H, n
        L = dict(LAYOUTS['vertical'], W=W, H=H, safe=.06)
        cy = cy if cy is not None else H * .56
        own = max(2, int(round(px * .125)))
        pitch = px * 1.2
        top = cy - pitch * len(lines) / 2
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        f = font_for_ps(font_ps, px)
        for i, (t, c) in enumerate(lines):
            base = top + pitch * i + (pitch - px) / 2 + .88 * px
            if deco:
                dfx = {'style': deco} if isinstance(deco, str) else dict(deco)
                lay.alpha_composite(deco_image({'text': t, 'color': dfx.get('color') or c, 'px': px, 'baseline': base}, dfx, L, font_ps, own))
        for i, (t, c) in enumerate(lines):
            base = top + pitch * i + (pitch - px) / 2 + .88 * px
            sc = stroke_color[i] if isinstance(stroke_color, list) and stroke_color and not isinstance(stroke_color[0], int) else stroke_color
            d.text((W / 2, base), t, font=f, fill=tcolor(c) + (255,), anchor='ms', stroke_width=own, **FEAT,
                   stroke_fill=(tcolor(sc) if sc is not None else (0, 0, 0)) + (255,))
        self.lay = lay
        self.keys = xml_keys(motion, n) if motion else {}

    def frame(self, f):
        W, H = self.W, self.H
        sc, rot, op = _kf(self.keys.get('scale'), f, 100) / 100, _kf(self.keys.get('rotation'), f, 0), _kf(self.keys.get('opacity'), f, 100) / 100
        lay = self.lay
        if abs(sc - 1) > .004 or rot:
            th = math.radians(rot)
            c, s_ = math.cos(th), math.sin(th)
            cx, cy = W / 2, H / 2
            co = (c / sc, s_ / sc, -(c * cx + s_ * cy) / sc + cx, -s_ / sc, c / sc, (s_ * cx - c * cy) / sc + cy)
            lay = lay.convert('RGBa').transform((W, H), Image.AFFINE, co, resample=Image.BICUBIC).convert('RGBA')
        cr = self.keys.get('crop')
        if cr:
            lf, rt = _kf(cr.get('left'), f, 0) / 100, _kf(cr.get('right'), f, 0) / 100
            if lf > .001 or rt > .001:
                keep = Image.new('L', (W, H), 0)
                ImageDraw.Draw(keep).rectangle([int(W * lf), 0, int(W * (1 - rt)), H], fill=255)
                a = lay.getchannel('A')
                lay = lay.copy()
                lay.putalpha(Image.composite(a, Image.new('L', (W, H), 0), keep))
        if self.keys.get('blur'):
            r = _kf(self.keys['blur'], f, 0)
            if r > .5:
                lay = lay.convert('RGBa').filter(ImageFilter.GaussianBlur(r / 4.4)).convert('RGBA')
        cen = self.keys.get('center')
        if cen:
            dx = int(round(_kf([(k, v[0]) for k, v in cen], f, 0) * W))
            dy = int(round(_kf([(k, v[1]) for k, v in cen], f, 0) * H))
            if dx or dy:
                sh = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                sh.paste(lay, (dx, dy))
                lay = sh
        if op < .995:
            lay = lay.copy()
            lay.putalpha(lay.getchannel('A').point(lambda v: int(v * op)))
        return lay

    def still(self):
        return self.lay


def catalog_xml_looks(out):
    """打ち替えられる範囲の見た目：塗りの色・縁の色・後ろの装飾"""
    cw, ch, px = 540, 132, 76
    fills = ['w', 'y', 'r', 'p', 'o', 'g', 'c', 'v', 'b', 'k']
    edges = [('y', 'r', '黄＋赤い縁'), ('w', 'r', '白＋赤い縁'), ('w', [20, 70, 200], '白＋青い縁'), ('k', 'w', '黒＋白い縁'),
             ('y', [110, 50, 0], '黄＋こげ茶の縁'), ('c', [10, 30, 110], '水色＋紺の縁'), ('r', 'w', '赤＋白い縁'), ('p', [120, 0, 60], 'ピンク＋えんじの縁')]
    decos = [('fuchi', 'y', 'r'), ('fuchi', 'w', 'w'), ('gloss', 'y', 'y'), ('kin', 'y', 'y'), ('kin', 'w', 'w'), ('beta', 'w', 'r'),
             ('neon', 'w', 'c'), ('neon', 'y', 'o'), ('fire', 'y', 'r'), ('horror', 'r', 'r'), ('mincho', 'w', 'b'), ('kage', 'y', 'y'),
             ('obi', 'w', 'r'), ('obi', 'y', 'b'), ('burst', 'r', 'r'), ('rainbow', 'w', 'w')]
    xl = dict(COLOR_LABEL, b='薄い水色（マーカー用）', k='黒（白い縁と組む）')
    secs = [('塗りの色（lines の色）', [(f'{k} {xl.get(k, "")}', dict(lines=[('テロップ', k)], stroke_color='w' if k == 'k' else None)) for k in fills]),
            ('縁の色（stroke_color）', [(lab, dict(lines=[('縁の色', c)], stroke_color=e)) for c, e, lab in edges]),
            ('後ろの装飾（deco。字は打ち替えられるまま）', [(f'deco {st}（色 {dc}）', dict(lines=[('後ろに装飾', c)], deco={'style': st, 'color': dc}))
                                                for st, c, dc in decos])]
    head = 84
    H = sum(head + ((len(cells) + 1) // 2) * ch + 24 for _, cells in secs) + 110
    sheet = _bg(1080, H)
    _label(sheet, (30, 22), 'XML で出せる見た目（Premiere で打ち替えられる）', 40, (120, 230, 255, 255))
    y = 100
    for title, cells in secs:
        _label(sheet, (30, y + 14), title, 34, (255, 236, 60, 255))
        for i, (lab, kw) in enumerate(cells):
            t = XmlTelop(W=cw, H=ch, px=px, n=1, cy=ch * .52, **kw)
            sheet.alpha_composite(t.still(), ((i % 2) * cw, y + head + (i // 2) * ch))
            _label(sheet, ((i % 2) * cw + 14, y + head + (i // 2) * ch + 4), lab, 18, (220, 220, 230, 220))
        y += head + ((len(cells) + 1) // 2) * ch + 24
    dst = Path(out) / '見本_1_XMLの見た目.png'
    sheet.convert('RGB').save(dst)
    return dst


# ---- テロップカタログ（2026-11-07）：気分ごとの短い見本動画＋一覧データ（catalog.json・catalog.js）＋ページ（カタログ.html）。
# 書き出し先は環境変数 TELOP_CATALOG_DIR（なければスキルの catalog/）
CATALOG_DIR = Path(__import__('os').environ.get('TELOP_CATALOG_DIR') or Path(__file__).resolve().parent.parent / 'catalog')
CATALOG_GROUPS = (('kihon', '基本'), ('glow', 'グロー系'), ('variety', 'バラエティの字幕型'), ('news', 'ニュース風'), ('kaiten', '3D 回転'),
                  ('quiz', 'クイズ'), ('parody', 'ニュース・情報番組（パロディ用）'), ('tokuban', '選挙特番の題字（年ごと）'),
                  ('gaitou', '街頭インタビュー風'))


# 題字の色違い（2026-11-07 ユーザー「これも登録しておいて」）：カード 1 枚で色まで決まる（tint・metal）
KAISAN_VARIANTS = [
    ('kaisan_2005', 'r', False, '2005・赤の金属'), ('kaisan_2005', 'b', False, '2005・青の金属'),
    ('kaisan_2009', 'w', False, '2009・銀'), ('kaisan_2009', 'b', True, '2009・青の金属'),
    ('kaisan_2012', 'r', False, '2012・金＋赤い光'), ('kaisan_2012', 'w', False, '2012・銀'),
    ('kaisan_2014', 'g', False, '2014・緑の縁と光'), ('kaisan_2014', 'p', False, '2014・ピンクの縁と光'),
    ('kaisan_2017', 'w', False, '2017・銀の明朝'), ('kaisan_2017', 'p', True, '2017・ピンクの金属'),
    ('kaisan_2021', 'v', False, '2021・金＋紫の光'), ('kaisan_2021', 'g', True, '2021・緑の金属'),
    ('kaisan_2024', 'c', True, '2024・水色の金属'), ('kaisan_2024', 'k', True, '2024・黒の金属'),
    ('kaisan_2026', 'b', False, '2026・青い縁と光'), ('kaisan_2026', 'r', True, '2026・赤の金属'), ('kaisan_2026', 'w', False, '2026・銀＋灰の縁'),
]


def _catalog_entries():
    """カタログに並べるもの：気分ぜんぶ＋題字の色違い。[(id, 説明, 気分の定義, 系統, 見本の行, fx)]"""
    out = []
    for name, (desc, m) in MOODS.items():
        group = ('glow' if name in GLOW_MOODS else 'variety' if name in VARIETY_MOODS else 'news' if name in NEWS_MOODS
                 else 'kaiten' if name in KAITEN_MOODS else 'quiz' if name in QUIZ_MOODS else 'parody' if name in PARODY_MOODS
                 else 'tokuban' if name in KAISAN_MOODS else 'gaitou' if name in GAITOU_MOODS else 'kihon')
        lines, paint = _card_sample(name, m)
        fx = dict(mood=name, **({'paint': paint} if paint else {}), **(NEWS_SAMPLES[name][1] if name in NEWS_MOODS else {}),
                  **(QUIZ_SAMPLES[name][1] if name in QUIZ_MOODS else {}), **VARIETY_EXTRA.get(name, {}),
                  **(PARODY_SAMPLES[name][1] if name in PARODY_MOODS else {}), **(GAITOU_SAMPLES[name][1] if name in GAITOU_MOODS else {}))
        out.append((name, desc, m, group, lines, fx))
    for base, tint, metal, label in KAISAN_VARIANTS:
        vid = f'{base}_{tint}' + ('_metal' if metal else '')
        fx = dict(mood=base, tint=tint, **({'metal': True} if metal else {}))
        out.append((vid, f'選挙特番の題字の色違い：{label}', MOODS[base][1], 'tokuban', [('NHK解体', 'y')], fx))
    return out


def _nhk_status(name, m):
    """NHK 系で使えるか：use＝候補（演出の正本に書いたもの）・ok＝使ってよい・no＝使わない（check_spec が △）・tbd＝未決"""
    try:
        import check_spec as C
        bad_fx, bad_st, bad_hold, bad_in = C.BANNED_FX, C.BANNED_FX_STYLE, C.BANNED_FX_HOLD, C.BANNED_FX_IN_PREFIX
    except Exception:  # noqa: BLE001
        bad_fx, bad_st, bad_hold, bad_in = (), (), (), ()
    if (name in bad_fx or (name in GLOW_MOODS and name not in ('taiketsu', 'shinjitsu')) or m['style'] in bad_st
            or any(h in bad_hold for h in str(m['hold']).split('+')) or any(str(m.get('in') or '').startswith(p) for p in bad_in)):
        return 'no'     # グロー系は 11-06 に候補へ→11-07 職員と学歴編で外した（白く光る・金で字がにじむ）。taiketsu・shinjitsu は 11-07 夜に点滅を外して可
    if (name == 'ikari' or name in KAITEN_MOODS or name in PARODY_MOODS or name in KAISAN_MOODS
            or name in ('yontaku_nhk', 'mondai_nhk')):      # 3D 回転・4択の NHK 版・パロディ用は 11-07 に候補へ（ユーザー）
        return 'use'
    if name in VARIETY_MOODS or name in NEWS_MOODS or name in QUIZ_MOODS or name in GAITOU_MOODS:
        return 'tbd'
    return 'ok'


BASIC_SAMPLES = {      # 基本の気分の見本の文（2026-11-07 夜 ユーザー「全部 受信料とかスクランブルとか NHK 関係の言葉にしておいて」）
    'ikari': [('受信料の', 'w'), ('不当な請求', 'r')], 'odoroki': [('受信料が', 'w'), ('値下げ!?', 'y')],
    'gimon': [('スクランブル化', 'w'), ('できない?', 'c')], 'suuji': [('受信料収入', 'w'), ('約6000億円', 'y')],
    'ketsuron': [('NHKは', 'w'), ('スクランブル化', 'r')], 'tsukkomi': [('テレビないのに', 'w'), ('契約!?', 'p')],
    'kowai': [('集金人が', 'w'), ('また来た', 'r')], 'kirakira': [('受信料', 'w'), ('ついに値下げ', 'y')],
    'sokuhou': [('NHKが', 'w'), ('受信料値下げ', 'r')], 'bakuhatsu': [('受信料', 'w'), ('ゼロ円!?', 'r')],
    'honoo': [('NHKに', 'w'), ('批判殺到', 'r')], 'shizuka': [('それでも', 'w'), ('受信料は続く', 'w')],
}


def _card_sample(name, m):
    if name in GLOW_SAMPLES:
        return GLOW_SAMPLES[name]
    if name in VARIETY_SAMPLES:
        return VARIETY_SAMPLES[name]
    if name in NEWS_SAMPLES:
        return NEWS_SAMPLES[name][0], None
    if name in KAITEN_SAMPLES:
        return KAITEN_SAMPLES[name], None
    if name in QUIZ_SAMPLES:
        return QUIZ_SAMPLES[name][0], None
    if name in PARODY_SAMPLES:
        return PARODY_SAMPLES[name][0], None
    if name in KAISAN_MOODS:
        return [('スクランブル化', 'y')], None
    if name in GAITOU_SAMPLES:
        return GAITOU_SAMPLES[name][0], None
    return BASIC_SAMPLES.get(name, [('受信料の', 'w'), ('使い道', m.get('color', 'y'))]), None


def catalog_cards(out=None, only=None):
    """気分ごとのカード（540×360 の見本動画 mp4・止め絵 png）と catalog.json・catalog.js・カタログ.html を書き出す"""
    out = Path(out) if out else CATALOG_DIR
    out.mkdir(parents=True, exist_ok=True)
    W, H, fps, lead = 540, 360, 30, 6
    cards = []
    for name, desc, m, group, lines, fx in _catalog_entries():
        snippet = {'fx': fx if len(fx) > 1 else name}
        base_mood = fx.get('mood', name)
        cards.append(dict(id=name, desc=desc, group=group, nhk=_nhk_status(base_mood, m), style=m['style'], style_desc=STYLES[m['style']][0],
                          **{'in': m['in']}, hold=m['hold'], color=m.get('color', 'w'), sample=[t for t, _ in lines],
                          clip=f'{name}.mp4', poster=f'{name}.png', snippet=snippet))
        if only and name not in only:
            continue
        px = 84 if max(len(t) for t, _ in lines) <= 5 else 62
        n = 84 if name not in GLOW_MOODS else 96
        if name in QUIZ_MOODS:                          # 4択は縦に長いので、縦の見本（1080×1920 を縮めた絵）で作る
            n = 120
            t = _quiz_card(lines, fx, W, H, n)
        elif name in KAITEN_MOODS:                        # 見本の枠は横長なので柱を大きめに（実際の回は既定の 6 割）
            n = 96
            t = _cell_telop(lines, dict(fx, tall=.78), W, H, 80, n)
        else:
            t = _cell_telop(lines, fx, W, H, px, n)
        base = _bg(W, H, seed=sum(map(ord, name)) % 7 + 1)
        enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(fps),
                                '-i', '-', '-c:v', 'libx264', '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                                str(out / f'{name}.mp4')], stdin=subprocess.PIPE)
        for f in range(lead + n + 4):            # ループの切れ目の空白は短く（頭 0.2 秒は出方を見せるため）
            img = base.copy()
            if lead <= f < lead + n:
                img.alpha_composite(t.frame(f - lead))
            enc.stdin.write(img.tobytes())
            if f == lead + min(n - 14, max(t.in_total + 18, 40)):
                img.convert('RGB').save(out / f'{name}.png')
        enc.stdin.close()
        enc.wait()
        print('カード:', name)
    data = {'updated': __import__('datetime').date.today().isoformat(), 'groups': [dict(id=g, label=l) for g, l in CATALOG_GROUPS],
            'nhk_labels': {'use': 'NHK の候補', 'ok': 'NHK でも可', 'no': 'NHK では使わない', 'tbd': 'NHK は未決'},
            'colors': COLOR_LABEL, 'cards': cards}
    import json as _json
    (out / 'catalog.json').write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'catalog.js').write_text('window.TELOP_CATALOG = ' + _json.dumps(data, ensure_ascii=False) + ';\n', encoding='utf-8')
    tpl = Path(__file__).resolve().parent.parent / 'assets' / 'telop_catalog.html'
    (out / 'カタログ.html').write_text(tpl.read_text(encoding='utf-8'), encoding='utf-8')
    return out / 'カタログ.html'


def catalog(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    print('XML の見た目:', catalog_xml_looks(out))
    two0 = [('受信料が', 'w'), ('払えない', 'y')]
    xm = [(k, v, two0, ('xml', dict(motion=k, deco='fuchi' if k in ('don', 'zoom', 'beat') else None))) for k, v in XML_MOTIONS.items()]
    print('XML の動き:', _grid_video(xm, out / '見本_2_XMLの動き.mp4', 'XML の動き（打ち替えられる）'))
    print('型の一覧:', catalog_styles(out))
    two = [('受信料が', 'w'), ('払えない', 'y')]
    ins = [(k, v[0], two, {'style': 'gloss', 'in': k, 'hold': 'none'}) for k, v in BLOCK_IN.items() if k != 'cut']
    ins += [(k, v[0], two, {'style': 'gloss', 'in': k, 'hold': 'none'}) for k, v in CHAR_IN.items()]
    print('出方:', _grid_video(ins, out / '見本_4_決めテロップの出方.mp4', '決めテロップ（動画）の出方'))
    holds = [(k, v[0], [('まさかの', 'w'), ('値上げ', 'r')], {'style': 'fuchi' if k != 'flicker' else 'neon', 'in': 'pop', 'hold': k})
             for k, v in HOLD.items() if k != 'none']
    outs = [(k, v[0], [('契約してない', 'y')], {'style': 'beta', 'in': 'pop', 'out': k}) for k, v in OUT.items() if k != 'cut']
    print('出ている間・消え方:', _grid_video(holds + outs, out / '見本_5_決めテロップの出ている間と消え方.mp4', '決めテロップの出ている間・消え方', sec=3.2))
    moods = [(k, v[0], BASIC_SAMPLES.get(k, [('受信料の', 'w'), ('使い道', v[1].get('color', 'y'))]), k) for k, v in MOODS.items()
             if k not in GLOW_MOODS + VARIETY_MOODS + NEWS_MOODS + KAITEN_MOODS + QUIZ_MOODS + PARODY_MOODS + KAISAN_MOODS + GAITOU_MOODS]
    print('気分:', _grid_video(moods, out / '見本_6_決めテロップの気分.mp4', '決めテロップの気分（型＋動きのおすすめ）', sec=3.0))
    print('グロー系:', catalog_glow(out))
    print('バラエティの字幕型:', catalog_variety(out))
    print('3D 回転:', catalog_kaiten(out))
    print('4択クイズ:', catalog_quiz(out))
    print('選挙特番の題字:', catalog_kaisan(out))
    print('街頭インタビュー風:', catalog_gaitou(out))
    print('カタログ:', catalog_cards())
    lst = out / '_list.txt'
    vids = ['見本_2_XMLの動き.mp4', '見本_4_決めテロップの出方.mp4', '見本_5_決めテロップの出ている間と消え方.mp4', '見本_6_決めテロップの気分.mp4',
            '見本_7_グロー系.mp4', '見本_8_バラエティの字幕型.mp4', '見本_9_3D回転.mp4',
            '見本_10_4択クイズ.mp4', '見本_11_選挙特番の題字.mp4']
    lst.write_text(''.join(f"file '{out / v}'\n" for v in vids), encoding='utf-8')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', '-movflags', '+faststart',
                    str(out / '見本リール_テロップの動き.mp4')], check=True)
    lst.unlink()
    print('まとめ:', out / '見本リール_テロップの動き.mp4')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    p = sub.add_parser('catalog')
    p.add_argument('--out', required=True)
    p = sub.add_parser('cards', help='テロップカタログ（気分ごとの見本動画・catalog.json・カタログ.html）だけ作り直す')
    p.add_argument('--out', default=None, help='既定はスキルの catalog/（環境変数 TELOP_CATALOG_DIR で替えられる）')
    p.add_argument('--only', default=None, help='動画を作り直す気分（カンマ区切り。一覧データとページは全部書く）')
    p = sub.add_parser('render')
    p.add_argument('--text', required=True, help='行は / で区切る')
    p.add_argument('--color', default='y', help='行ごとの色（w,y のようにカンマで）')
    p.add_argument('--fx', default='gloss:pop', help='気分の名前、または 型:出方:出ている間:消え方')
    p.add_argument('--out', required=True, help='.mov（透明つき）か .png（止まった絵）')
    p.add_argument('--sec', type=float, default=2.5)
    p.add_argument('--px', type=int, default=128)
    p.add_argument('--y', type=int, default=None, help='まとまりの中心の y（既定は縦 1040・横 860）')
    p.add_argument('--paint', default=None, help='行の中の色分け「語=色,語=色」（例 が明らかに!=b）')
    p.add_argument('--glow', default=None, help='光の色（色キー）')
    p.add_argument('--edge', default=None, help='色の要（色キー。jimaku・news_jimaku＝話し手の縁、news_obi＝帯、news_fuda＝字とタブ）')
    p.add_argument('--tag', default=None, help='札の文字（news_obi の「妻」・news_fuda の「料金」）')
    p.add_argument('--box', default=None, help='語を色の箱に「語=色,語=色」（news_jimaku の要の語）')
    p.add_argument('--layout', default='vertical', choices=list(LAYOUTS))
    a = ap.parse_args()
    if a.cmd == 'list':
        print('■ 型（style）')
        for k, v in STYLES.items():
            print(f'  {k:<10} {v[0]}')
        print('■ 色  ' + '  '.join(f'{k}={v}' for k, v in COLOR_LABEL.items()))
        print('■ 出方（in）まとまりごと')
        for k, v in BLOCK_IN.items():
            print(f'  {k:<11} {v[0]}（{v[1]}f）')
        print('■ 出方（in）1文字ずつ')
        for k, v in CHAR_IN.items():
            print(f'  {k:<11} {v[0]}')
        print('■ 出ている間（hold。+ でつなげる）')
        for k, v in HOLD.items():
            print(f'  {k:<11} {v[0]}')
        print('■ 消え方（out）')
        for k, v in OUT.items():
            print(f'  {k:<11} {v[0]}')
        print('■ 気分（型＋動きのおすすめ）')
        for k, v in MOODS.items():
            m = v[1]
            print(f'  {k:<11} {v[0]}：{m["style"]}・{m["in"]}・{m["hold"]}')
        return
    if a.cmd == 'cards':
        print(catalog_cards(a.out, a.only.split(',') if a.only else None))
        return
    if a.cmd == 'catalog':
        catalog(a.out)
        return
    L = dict(LAYOUTS[a.layout])
    y = a.y if a.y is not None else (1040 if a.layout == 'vertical' else 860)
    texts = a.text.split('/')
    cols = (a.color.split(',') * len(texts))[:len(texts)]
    pitch = a.px * 1.2
    top = y - pitch * len(texts) / 2
    lines = [{'text': t, 'color': c, 'px': a.px, 'baseline': top + pitch * i + (pitch - a.px) / 2 + .88 * a.px, 'delay': 0}
             for i, (t, c) in enumerate(zip(texts, cols))]
    fx = resolve_fx(a.fx)
    if a.paint:
        fx['paint'] = a.paint
    if a.glow:
        fx['glow'] = a.glow
    if a.edge:
        fx['edge'] = a.edge
    if a.tag:
        fx['tag'] = a.tag
    if a.box:
        fx['box_words'] = a.box
    t = FxTelop({'lines': lines, 'fx': resolve_fx(fx)}, L, int(a.sec * 30))
    if a.out.endswith('.png'):
        t.still().save(a.out)
    else:
        write_mov(t, a.out)
    print('OK:', a.out)


if __name__ == '__main__':
    main()
