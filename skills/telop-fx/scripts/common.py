"""premiere-short-xml の共通部品：画面の配置（縦・横）、フォント、文字の描画、グラフ・枠の描画。

build_premiere.py（静止画・XML）・build_anim.py（動く図）・check_*・preview_*・short-edit から使う。
グラフは「パネル座標」（幅920×高さ550）で描き、配置（縦・横）ごとの位置に置く。
"""
import re
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

MINCHO = '/System/Library/Fonts/ヒラギノ明朝 ProN.ttc'      # index 2 = ProN W6
GOTHIC = '/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc'   # index 0 = Hiragino Sans W6
COL = {'w': (255, 255, 255), 'y': (255, 230, 0), 'r': (245, 34, 34), 'p': (243, 160, 180), 'gray': (215, 215, 215),
       'b': (175, 218, 255)}          # b はマーカー用の薄い水色（黄色と区別したい語に）
# 2026-10-10：文字クリップの色を足した（橙・緑・水色・紫・黒）。暗い背景で読める明るさ。決めテロップ（telop_fx.py）の色は別の表（BASE）
COL.update({'o': (255, 150, 30), 'g': (120, 230, 110), 'c': (80, 215, 255), 'v': (205, 150, 255), 'k': (20, 20, 24)})
PW, PH = 920, 550          # パネル（図・スクショ枠）の大きさ
MARGIN = 40                # 動くグラフでパネルの外にはみ出す分

LAYOUTS = {
    # 縦 9:16。テロップは画面の真ん中（拡大の軸＝フレーム中心と一致させて、ポンと出しても位置がずれない）
    # text_scale: FCP7 XML の文字サイズ × text_scale が Premiere での px（1080×1920 で実測：120→480、縁取り12→48）
    # 縦（ショート）の画面の割り振り（2026-10-09 時点）：最上部はラベル（ダイナミックアイランドは気にしない＝10-09 ユーザー）、
    # ※ここは common の既定＝古い spec を作り直すための値。新しい回は presets.py の VERTICAL_RULES（テロップ 1010・注記 1840・図 270〜820＝2026-10-11）を
    #   new_short が spec に書く。決まりの正本は references/演出の正本.md（2026-10-23）
    # 図・顔は y270〜900（figures_band）、テロップの中心 1040、注記は左寄せ 1660（セーフティエリアの下端 1728 の手前ぎりぎり＝2026-10-10 ユーザー「かなりセーフティギリギリでいい」。3行でも 1728 の内側）、発信者表示 1330。
    # panel・shot_area の既定は 2026-10-10 から y270〜900（ユーザー決定）。最初の案件の旧 spec（y200〜685）を作り直すときは layout_overrides に旧型の値
    'vertical': dict(W=1080, H=1920, telop_center=(540, 960), telop_max_w=980, telop_sizes={'s': 80, 'm': 104, 'l': 128},
                     listener_scale=0.94, panel=(108, 270), panel_scale=0.93, note_y=1660, note_w=900, note_size=24, note_min_size=16,
                     note_align='left', note_x=112, label_pos=(108, 40), sender_y=1330, app_ui='youtube_ios',
                     label_size=44, bg_label_y=1560, bg_mark_y=1830, bg_tip_y=1735, veil=(840, 1300),
                     title_sizes=[104, 92, 132], title_gap=1.45,
                     end_scale=1.0, text_scale=4.0, stroke_px=12, shot_area=(128, 270, 952, 900),
                     telop_block_y=1040, line_pitch=1.2, safe=0.10,
                     motion={'pop': [(0, 65), (3, 108), (6, 100)], 'rise': [(0, 92), (3, 100)],
                             'soft': [(0, 85), (4, 104), (7, 100)],
                             'slam': [(0, 240), (4, 88), (7, 108), (10, 100)]}, telop_fade=False),
    # 横 16:9。テロップは下寄り。拡大の軸がフレーム中心なので、ずれが目立たないよう拡大は控えめ＋フェード
    # text_scale 2.25 は 2026-09-27 に Premiere で確認（横テスト：FCP 40 → 90px、縁取り 4 → 9px。origin の縦は ×1080、横は ×1920）。
    # 1行・origin 0 のベースラインは 540 − 22（90px のとき）＝ サイズ × 0.244（base_k。試し1点。縦は サイズ/8 + 2）
    'horizontal': dict(W=1920, H=1080, telop_center=(960, 860), telop_max_w=1640, telop_sizes={'s': 64, 'm': 84, 'l': 100},
                       listener_scale=0.94, panel=(500, 70), note_y=1040, note_w=1700, note_size=26, label_pos=(40, 36),
                       label_size=34, bg_label_y=150, bg_mark_y=540, bg_tip_y=1020, veil=(700, 1080),
                       title_sizes=[88, 78, 112], title_gap=1.4,
                       end_scale=0.62, text_scale=2.25, stroke_px=8, shot_area=(460, 60, 1880, 720),
                       telop_block_y=860, line_pitch=1.2, base_k=0.2444, base_b=0, safe=0.05,
                       kf_amp=0.5,      # XML の新しい動き（KF_MOTIONS）の振れ幅。横はテロップが画面の中心から遠いので半分に
                       motion={'pop': [(0, 92), (3, 104), (6, 100)], 'rise': [(0, 97), (3, 100)],
                               'soft': [(0, 95), (4, 102), (7, 100)],
                               'slam': [(0, 240), (4, 88), (7, 108), (10, 100)]}, telop_fade=True),
}


# 2026-10-07 夜：みなさまの声編 v1b でユーザーが Premiere でテロップを 70〜210px 下げ（図・顔とのすき間をあけた）、図と締めの絵を大きくした。
# それに合わせて縦のテロップの中心を y1040 にした（右のボタンに2段目の右端が少しかかるのはユーザーが受け入れた）。図・顔は y 270〜900 に。
# 縦の既定は 2026-10-07 に「iPhone の YouTube アプリの再生画面」に合わせて変えた（app_ui）：テロップの中心 y960（10-07 朝。前は 1060）→ 1040（10-07 夜）、
# 注記は左寄せ y1660・26px（10-07〜10-09 は 1370、前は中央 y1470・34px）、発信者表示 y1330（前は 1400）。前の既定に頼っていた古い spec を作り直すときは
# layout_overrides で前の値（telop_block_y 1060・note_y 1470 など）を書く。layout_overrides の {"app_ui": null} で UI の点検を外せる。

# スマホのアプリの再生画面で、ボタン・題名などが重なって隠れる場所（動画の座標）。2026-10-07、集金人編 v1g を iPhone の YouTube アプリで
# 再生したスクショと元の動画を重ねて測った（動画は高さいっぱいに表示され、左右が約49pxずつ切れる）。
# v1g では注記（y1856）が下の帯で全部隠れ、y1150 のテロップの右端が「高く評価」にかかった。ガイド画像は assets/iphone_youtube_ui_guide.png
APP_UI = {
    'youtube_ios': [
        ('時刻・電池', (0, 0, 1080, 100)),
        ('戻る', (60, 150, 170, 250)),
        ('検索・メニュー', (800, 150, 1000, 250)),
        ('評価・コメント・保存・共有・リミックス', (880, 1050, 1080, 1760)),
        ('チャンネル名・題名・関連動画・共有の帯', (0, 1440, 1080, 1920)),
        ('左の端（切れる）', (0, 0, 49, 1920)),
        ('右の端（切れる）', (1031, 0, 1080, 1920)),
    ],
}


def ui_zones(L):
    """アプリの再生画面で隠れる場所 [(名前, (x0, y0, x1, y1))]。app_ui がなければ空"""
    return APP_UI.get(L.get('app_ui') or '', []) if L.get('W') == 1080 and L.get('H') == 1920 else []


def ui_hits(L, box, ignore=()):
    """box（x0, y0, x1, y1）が重なる UI の名前の一覧"""
    x0, y0, x1, y1 = box
    return [n for n, (a, b, c, d) in ui_zones(L) if n not in ignore and x0 < c and x1 > a and y0 < d and y1 > b]


# セーフティエリア（safe＝外周の片側の割合。2026-10-03 ユーザー指示「全体に10%をセーフティエリアとしてテロップなどが切れないように」）。
# 9:16 の動画を縦長のスマホ（19.5:9・20:9）で全画面にすると、左右が片側 9〜10％ずつ切り取られる。
# 文字（テロップ・注記・ラベル・発信者表示・エンドカード）・座布団・図・スクショはこの内側に置く。背景と人物の絵はこの外に出てよい。
# 縦は 0.10（x 108〜972・y 192〜1728）。横（テレビ前提）は 0.05（タイトルセーフ）。layout_overrides の {"safe": 0.05} などで変えられる。
# 例外：縦のラベルは上の帯（y 110・隠れてもよい情報の場所）のまま。横の位置だけ内側に入れる。
_safe_said = set()


def safe_rect(L):
    """セーフティエリア (x0, y0, x1, y1)（px）"""
    s = L.get('safe', 0)
    return (round(L['W'] * s), round(L['H'] * s), round(L['W'] * (1 - s)), round(L['H'] * (1 - s)))


def safe_w(L):
    x0, _, x1, _ = safe_rect(L)
    return x1 - x0


def _fit_safe(L):
    """位置・幅の設定（既定と layout_overrides）をセーフティエリアの内側に直す。直した項目の説明を返す。"""
    sx0, sy0, sx1, sy1 = safe_rect(L)
    W, fixed = L['W'], []

    def put(key, val, why):
        if L.get(key) != val:
            fixed.append(f'{key} {L.get(key)}→{val}（{why}）')
            L[key] = val

    put('telop_max_w', min(L['telop_max_w'], sx1 - sx0 - 2 * L['stroke_px']), 'テロップの幅＝内側の幅−縁取り')
    if L.get('note_align') == 'left':
        nx = L.get('note_x', W / 2 - L['note_w'] / 2)
        right = min(nx + L['note_w'], sx1 - 4)            # 右端は spec の右端（右下の操作ボタンよけ）か内側の右端の小さい方
        for n, (a, b, c, d) in ui_zones(L):               # アプリの右のボタンの高さにかかるなら、その左まで
            if b < L['note_y'] + 60 and d > L['note_y'] - 60 and a > W / 2:
                right = min(right, a - 10)
        nx = max(nx, sx0 + 4)                              # 4＝注記の縁取り
        put('note_x', round(nx), '注記の左端')
        put('note_w', round(right - nx), '注記の幅')
    else:
        put('note_w', min(L['note_w'], sx1 - sx0 - 8), '注記の幅')
    lx, ly = L['label_pos']
    put('label_pos', (max(lx, sx0), ly), 'ラベルの左端')
    ax0, ay0, ax1, ay1 = L['shot_area']      # スクショは白い縁（6）・寄りのポン（3.5％）・ハンコの揺れ（12）の分だけさらに内側
    put('shot_area', (max(ax0, sx0 + 20), max(ay0, sy0 + 20), min(ax1, sx1 - 20), min(ay1, sy1 - 20)), 'スクショの範囲')
    k = min(L.get('panel_scale', 1.0), (sx1 - sx0) / PW)   # グラフのパネル（920×550 を panel_scale 倍）
    if k != L.get('panel_scale', 1.0):
        put('panel_scale', round(k, 4), 'グラフの倍率')
    px, py = L['panel']
    px = min(max(px, sx0), sx1 - PW * k)
    put('panel', (round(px), max(py, sy0)), 'グラフの位置')
    return fixed


OVERLAY_NAME = '手直し.json'


def apply_overlay(spec, ov):
    """編集画面（short-edit スキル）で直した分を spec に重ねる。make_spec.py で spec.json を作り直しても消えないように、
    直しは spec の横の 手直し.json に置き、spec を読むたびに重ねる（2026-10-08）。
    title・script・audio_manifest は上書き。telops は {line, anchor, k, set} の並びで、同じ行の中から
    目印（anchor）が同じテロップを探し（なければ k 番目）、set の項目（lines・y・size・anchor など）で上書きする。"""
    for key in ('title', 'script'):
        if ov.get(key):
            spec[key] = ov[key]
    if ov.get('audio_manifest'):
        spec.setdefault('audio', {})['manifest'] = ov['audio_manifest']
    miss = []
    for t in ov.get('telops', []):
        units = spec.get('lines', {}).get(str(t['line'])) or []
        k = t.get('k', 0) - 1
        hit = [i for i, u in enumerate(units) if u.get('anchor') == t.get('anchor')]
        i = k if k in hit else (hit[0] if hit else (k if 0 <= k < len(units) else None))
        if i is None:
            miss.append(f'{t["line"]}行目「{t.get("anchor")}」')
            continue
        for key, val in t.get('set', {}).items():     # null は「spec の値を外す」（大きさを既定に・目印を行の頭に）
            if val is None:
                units[i].pop(key, None)
            else:
                units[i][key] = val
    if miss:
        import sys as _s
        print(f'注意: {OVERLAY_NAME} のテロップが spec に見つからない（台本が変わった？）：' + '、'.join(miss), file=_s.stderr)
    return spec


def load_spec(path):
    """spec.json を読み、横に 手直し.json があれば重ねる。どのスクリプトもこれで spec を読む（手直し.json がなければ今までどおり）。"""
    import json as _j
    path = Path(path)
    spec = _j.loads(path.read_text(encoding='utf-8'))
    ov = path.parent / OVERLAY_NAME
    if ov.exists():
        spec = apply_overlay(spec, _j.loads(ov.read_text(encoding='utf-8')))
    return spec


def layout_of(spec):
    """spec の配置（layout）に、spec の layout_overrides（例 {"telop_block_y": 1150}）を上書きした dict。
    どのスクリプトもこれで L を作る（プレビューと XML で置き方がずれないように）。
    最後に位置・幅をセーフティエリア（safe）の内側に直す（直したら1回だけ知らせる）。"""
    L = dict(LAYOUTS[spec.get('layout', 'vertical')])
    ov = spec.get('layout_overrides', {})
    L.update(ov)
    for key in ('label_pos', 'shot_area', 'panel'):
        if isinstance(L.get(key), list):
            L[key] = tuple(L[key])
    fixed = [x for x in _fit_safe(L) if x.split(' ')[0] in ov]   # 知らせるのは spec の layout_overrides で書いた項目だけ
    key = (spec.get('title'), tuple(fixed))
    if fixed and key not in _safe_said:
        _safe_said.add(key)
        print(f'セーフティエリア（片側 {L["safe"] * 100:.0f}％）に合わせて layout_overrides を直した：' + '、'.join(fixed))
    return L


# Premiere に渡すフォント名は PostScript 名（空白なし）。空白を含む名前は読み込み時に壊れる（例 HiraginoMinchoProNW6W6）
FONT_PS = {'m': 'HiraMinProN-W6', 'g': 'HiraginoSans-W6'}

_fc = {}


def font(kind, size):
    size = max(8, int(size))
    key = (kind, size)
    if key not in _fc:
        _fc[key] = ImageFont.truetype(MINCHO if kind == 'm' else GOTHIC, size, index=2 if kind == 'm' else 0)
    return _fc[key]


def font_for_ps(font_ps, size):
    """Premiere に渡すフォント名（PostScript 名）に合う PIL のフォント。幅の計算・プレビューで使う（既定は明朝）"""
    fp = font_ps or ''
    m = re.search(r'Sans-W(\d)', fp)
    if m and m.group(1) != '6':        # ゴシックの太さ（W8・W9 など）をそのまま使う。2026-10-07：W8 を W6 で測っていた
        key = ('w' + m.group(1), max(8, int(size)))
        if key not in _fc:
            _fc[key] = ImageFont.truetype(f'/System/Library/Fonts/ヒラギノ角ゴシック W{m.group(1)}.ttc', key[1])
        return _fc[key]
    return font('g', size) if 'Sans' in fp else font('m', size)


def color(c):
    if isinstance(c, (list, tuple)):          # [r, g, b] の直書き（縁の色など）
        return tuple(int(v) for v in c[:3])
    return COL.get(c, (255, 255, 255))


# ---------------------------------------------------------------- 文字クリップの動き（XML のキーフレーム・2026-10-10）
# Premiere が FCP7 XML から読むのは、ネストのクリップに付けた拡大（scale）・回転（rotation）・不透明度（opacity）のキーフレームだけ。
# 位置（center）のキーフレームはネストでは未確認なので、横から入る・上から落ちる動きは決めテロップ（telop_fx.py・動画）の側にある。
# 時刻はクリップの頭からのフレーム。loop は出きったあと every フレームごとに繰り返す分。
# spec では "motion": "don"。後ろに +grow を付ける（"don+grow"）と、出たあと消えるまでに 110％ まで大きくなり続ける。
KF_MOTIONS = {
    'don': ('強い飛び込み（どん）', {'scale': [(0, 330), (4, 86), (6, 110), (8, 97), (10, 100)]}),
    'zoom': ('奥から飛び出す', {'scale': [(0, 8), (5, 116), (8, 96), (10, 100)]}),
    'blink': ('点滅しながら大きく', {'scale': [(0, 60), (9, 100)],
                             'opacity': [(0, 100), (1, 100), (2, 15), (3, 100), (4, 15), (5, 100), (6, 15), (7, 100)]}),
    'shake': ('震えて止まる', {'scale': [(0, 70), (3, 104), (6, 100)],
                         'rotation': [(0, -5), (2, 5), (4, -4), (6, 3), (8, -2), (10, 1), (12, 0)]}),
    'swing': ('振り子で止まる', {'scale': [(0, 80), (4, 100)], 'rotation': [(0, -14), (4, 9), (8, -5), (12, 2), (15, 0)]}),
    'spin2': ('2回転', {'scale': [(0, 10), (16, 100)], 'rotation': [(0, -720), (16, 0)]}),
    'fade': ('ふわっと', {'scale': [(0, 94), (8, 100)], 'opacity': [(0, 0), (8, 100)]}),
    'beat': ('鼓動（出たあとも脈打つ）', {'scale': [(0, 65), (3, 108), (6, 100)],
                                'loop': {'scale': [(0, 100), (3, 107), (7, 100)], 'every': 18, 'from': 14}}),
    'buru': ('震え続ける', {'scale': [(0, 70), (3, 104), (6, 100)],
                       'loop': {'rotation': [(0, -1.3), (2, 1.3), (4, -1.3)], 'every': 4, 'from': 6}}),
}
KF_REST = {'scale': 100, 'rotation': 0, 'opacity': 100}

# 2026-10-10（夜）Premiere 2026 で読めると確かめた分（試験_telop_xml_v1）：ネストに付けた 位置（center）のキーフレーム・切り抜き（Crop）・
# ぼかし（Gaussian Blur）。位置は 横＝画面の幅に対する割合・縦＝画面の高さに対する割合（0.1 で 108px／192px）・直線で動く。
# 切り抜きは ％（画面全体に対して）。x0・x1 は文字の左右の端（px）で、kf_motion が ％ に直す
KF_MOTIONS.update({
    'slide_l': ('左から滑り込む', {'center': [(0, (-0.75, 0)), (5, (0.025, 0)), (8, (0, 0))]}),
    'slide_r': ('右から滑り込む', {'center': [(0, (0.75, 0)), (5, (-0.025, 0)), (8, (0, 0))]}),
    'drop': ('上から落ちて弾む', {'center': [(0, (0, -0.62)), (5, (0, 0)), (7, (0, -0.028)), (9, (0, 0))]}),
    'up': ('下からすっと上がる', {'center': [(0, (0, 0.10)), (6, (0, 0))], 'opacity': [(0, 0), (4, 100)]}),
    'wipe': ('左から右へワイプ', {'crop': {'right': [(0, 'x0'), (9, 'x1'), (10, 0)]}}),
    'wipe_r': ('右から左へワイプ', {'crop': {'left': [(0, 'x1'), (9, 'x0'), (10, 0)]}}),
    'wipe_c': ('中央から開くワイプ', {'crop': {'left': [(0, 'xc'), (9, 'x0'), (10, 0)], 'right': [(0, 'xc'), (9, 'x1'), (10, 0)]}}),
    'blur': ('ぼけた状態からはっきり', {'blur': [(0, 70), (8, 0)], 'opacity': [(0, 0), (3, 100)], 'scale': [(0, 125), (8, 100)]}),
})

# Premiere は文字クリップを「プロポーショナルメトリクス（palt）」で組む（ひらがなが詰まる。2026-10-10 に書き出したコマで確認：
# palt で描くと字の位置が 1px 以内で一致、詰めないと かなの多い行で 13px ずれた）。Premiere の字を写す絵（確認動画・装飾）はこれで描く。
# テロップの幅の見積もり（telop_px）は今までどおり詰めない幅で測る（広めに見積もる＝はみ出さない側）
try:
    from PIL import features as _pf
    PALT = ['palt'] if _pf.check('raqm') else None
except Exception:  # noqa: BLE001
    PALT = None


def kf_motion(name, d, amp=1.0, x0=None, x1=None, W=None):
    """KF_MOTIONS の動きを、長さ d フレームのクリップのキーフレーム {'scale': [...], 'rotation': [...], 'opacity': [...]} にする。
    位置を使う動きは 'center'（[(フレーム, (横, 縦))]）、切り抜きは 'crop'（{'left'|'right': [(フレーム, ％)]}）、ぼかしは 'blur' も返す。
    最後のキーフレームはクリップの最後のコマ（d−1）まで（d 以上は Premiere が捨てる）。amp＝振れ幅の倍率（横の画面は控えめに）。
    x0・x1・W＝文字の左右の端と画面の幅（px。ワイプの切り抜きを文字の幅に合わせる。なければ画面の端から端）"""
    base, *opts = name.split('+')
    if base not in KF_MOTIONS:
        raise SystemExit(f'motion「{name}」は知らない（XML の動き：{", ".join(KF_MOTIONS)}）')
    m = KF_MOTIONS[base][1]
    last = max(1, d - 1)
    out = {}
    for key in ('scale', 'rotation', 'opacity'):
        ks = list(m.get(key, []))
        lp = (m.get('loop') or {})
        if key in lp:
            f0 = lp.get('from', (ks[-1][0] if ks else 0) + 4)
            while f0 + lp[key][-1][0] <= last - 1:
                ks += [(f0 + f, v) for f, v in lp[key] if not ks or f0 + f > ks[-1][0]]
                f0 += lp['every']
            if ks and ks[-1][1] != KF_REST[key] and ks[-1][0] + 2 <= last:
                ks.append((ks[-1][0] + 2, KF_REST[key]))
        if not ks:
            continue
        rest = KF_REST[key]
        if amp != 1.0 and key != 'opacity':
            ks = [(f, round(rest + (v - rest) * amp, 2)) for f, v in ks]
        cut = [k for k in ks if k[0] <= last]
        if len(cut) < len(ks):                   # 短いクリップ：入りきらない分は捨て、最後のコマで落ち着いた値に
            cut = [k for k in cut if k[0] < last] + [(last, ks[-1][1])]
        out[key] = cut
    def cut(ks):
        c = [k for k in ks if k[0] <= last]
        return c if len(c) == len(ks) else [k for k in c if k[0] < last] + [(last, ks[-1][1])]
    if m.get('center'):
        out['center'] = cut(list(m['center']))
    if m.get('blur'):
        out['blur'] = cut(list(m['blur']))
    if m.get('crop'):
        W_ = W or 100
        a, b = (x0, x1) if x0 is not None and x1 is not None else (0, W_)
        pos = {'x0': a, 'x1': b, 'xc': (a + b) / 2}
        out['crop'] = {}
        for side, ks in m['crop'].items():
            vals = []
            for f, v in ks:
                if isinstance(v, str):               # 文字の端（px）→ その辺からの切り抜き ％
                    v = 100 * (1 - pos[v] / W_) if side == 'right' else 100 * pos[v] / W_
                vals.append((f, round(max(0.0, min(100.0, v)), 2)))
            out['crop'][side] = cut(vals)
    if 'grow' in opts and last > 12:                  # +grow：出たあと消えるまでに 110％ まで
        sc = out.get('scale') or [(10, 100)]
        if last > sc[-1][0] + 1:
            out['scale'] = sc + [(last, round(sc[-1][1] * 1.10, 2))]
    return out


def blank(L):
    return Image.new('RGBA', (L['W'], L['H']), (0, 0, 0, 0))


def wrap(text, fnt, max_w):
    out, cur = [], ''
    for ch in text:
        if fnt.getlength(cur + ch) > max_w and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def draw_plain(canvas, text, xy, fnt, fill=(255, 255, 255, 255), anchor='mm', stroke=3):
    ImageDraw.Draw(canvas).text(xy, text, font=fnt, fill=fill, anchor=anchor, stroke_width=stroke,
                                stroke_fill=(0, 0, 0, 255))


def dash(d, x0, y0, x1, y1, fill, width, seg):
    x0, y0, x1, y1 = map(int, (x0, y0, x1, y1))
    for x in range(x0, x1, seg * 2):
        d.line([(x, y0), (min(x + seg, x1), y0)], fill=fill, width=width)
        d.line([(x, y1), (min(x + seg, x1), y1)], fill=fill, width=width)
    for y in range(y0, y1, seg * 2):
        d.line([(x0, y), (x0, min(y + seg, y1))], fill=fill, width=width)
        d.line([(x1, y), (x1, min(y + seg, y1))], fill=fill, width=width)


def draw_rich(canvas, lines, cx, cy, base, max_w, boost=1.22, shadow=True):
    """lines = [[(文字, 色), ...], ...] を (cx, cy) を中心に、明朝・黒縁・影つきで描く。黄・赤の語は少し大きく。"""
    layout = []
    for spans in lines:
        items = [[t, c, int(base * (boost if c in ('y', 'r') else 1.0))] for t, c in spans]
        width = sum(font('m', s).getlength(t) for t, _, s in items)
        if width > max_w:
            k = max_w / width
            for it in items:
                it[2] = max(24, int(it[2] * k))
        layout.append(items)
    heights = [max(s for _, _, s in items) * 1.2 for items in layout]
    top = cy - sum(heights) / 2
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = top
    for items, lh in zip(layout, heights):
        width = sum(font('m', s).getlength(t) for t, _, s in items)
        x = cx - width / 2
        big = max(s for _, _, s in items)
        baseline = y + lh * 0.5 + font('m', big).getmetrics()[0] * 0.42
        for text, c, size in items:
            f = font('m', size)
            d.text((x, baseline), text, font=f, fill=color(c) + (255,), anchor='ls',
                   stroke_width=max(5, int(size * 0.09)), stroke_fill=(0, 0, 0, 255))
            x += f.getlength(text)
        y += lh
    if shadow:
        sh = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        sh.putalpha(layer.split()[3].point(lambda v: int(v * 0.85)))
        sh = sh.filter(ImageFilter.GaussianBlur(9))
        moved = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        moved.paste(sh, (6, 8), sh)
        canvas.alpha_composite(moved)
    canvas.alpha_composite(layer)
    return canvas


# ---------------------------------------------------------------- 動きの計算
def clamp(t):
    return max(0.0, min(1.0, t))


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_back(t, k=1.9):
    t = clamp(t)
    return 1 + (k + 1) * (t - 1) ** 3 + k * (t - 1) ** 2


def prog(f, a, dur):
    return clamp((f - a) / dur) if dur > 0 else float(f >= a)


def shake(f, a, amp=8, dur=8, static=False):
    if static or not (a <= f < a + dur):
        return 0, 0
    k = 1 - (f - a) / dur
    return int(amp * k * math.sin((f - a) * 2.3)), int(amp * 0.6 * k * math.cos((f - a) * 3.1))


def fmt(value, spec):
    """数値の表示。spec='man_yen' なら +2万2400円 の形、それ以外は '{:.1f}％' '{:d}億円' などの書式。"""
    if spec == 'man_yen':
        v = int(round(value / 100) * 100)
        man, rest = divmod(v, 10000)
        return f'+{man}万{rest}円' if man and rest else (f'+{man}万円' if man else f'+{rest}円')
    try:
        return spec.format(value)
    except (ValueError, TypeError):
        return spec.format(int(round(value)))


# ---------------------------------------------------------------- パネルの描画（2倍で描いて縮小）
class Panel:
    """パネル座標（0..920 × 0..550）で描く。S=2 で描いて縮小すると線がなめらかになる。"""

    def __init__(self, S=2):
        self.S = S
        self.im = Image.new('RGBA', ((PW + 2 * MARGIN) * S, (PH + 2 * MARGIN) * S), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def P(self, x, y):
        return ((x + MARGIN) * self.S, (y + MARGIN) * self.S)

    def f(self, kind, size):
        return font(kind, size * self.S)

    def text(self, xy, s, kind, size, fill, anchor='mm', stroke=0, alpha=255):
        if alpha <= 0 or not s:
            return
        layer = Image.new('RGBA', self.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(self.P(*xy), s, font=self.f(kind, size), fill=tuple(fill)[:3] + (255,), anchor=anchor,
                                   stroke_width=int(stroke * self.S), stroke_fill=(0, 0, 0, 255))
        if alpha < 255:
            layer.putalpha(layer.split()[3].point(lambda v: v * alpha // 255))
        self.im.alpha_composite(layer)

    def rect(self, box, fill, r=8, outline=None, width=0):
        x0, y0, x1, y1 = box
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        self.d.rounded_rectangle([*self.P(x0, y0), *self.P(x1, y1)], radius=r * self.S, fill=fill,
                                 outline=outline, width=width * self.S)

    def glow(self, fn, radius=10, strength=1.0):
        layer = Image.new('RGBA', self.im.size, (0, 0, 0, 0))
        fn(ImageDraw.Draw(layer))
        g = layer.filter(ImageFilter.GaussianBlur(radius * self.S))
        if strength != 1.0:
            g.putalpha(g.split()[3].point(lambda v: min(255, int(v * strength))))
        self.im.alpha_composite(g)
        self.im.alpha_composite(layer)

    def dashed_line(self, x0, y0, x1, y1, fill, width, seg=12, upto=1.0):
        length = math.hypot(x1 - x0, y1 - y0) or 1
        i = 0
        while True:
            s0 = i * seg * 2 / length
            if s0 > upto or s0 >= 1:
                break
            s1 = min(1.0, (i * seg * 2 + seg) / length, upto)
            self.d.line([self.P(x0 + (x1 - x0) * s0, y0 + (y1 - y0) * s0), self.P(x0 + (x1 - x0) * s1, y0 + (y1 - y0) * s1)],
                        fill=fill, width=width * self.S)
            i += 1

    def base(self, f, title=None, static=False, fill_alpha=175):
        t = 1.0 if static else ease_out(prog(f, 0, 8))
        if t <= 0:
            return 0
        dy = (1 - t) * 30
        self.d.rounded_rectangle([*self.P(0, dy), *self.P(PW, PH + dy)], radius=26 * self.S,
                                 fill=(0, 0, 0, int(fill_alpha * t)), outline=(255, 255, 255, int(90 * t)), width=2 * self.S)
        if title:
            self.text((PW / 2, 55 + dy), title, 'm', 40, COL['w'], alpha=255 if static else int(255 * ease_out(prog(f, 4, 8))))
        return dy

    def stamp(self, f, a, text, cx, cy, sub=None, static=False, scale=1.0):
        t = 1.0 if static else prog(f, a, 6)
        if t <= 0:
            return
        k = (1.9 - 0.9 * ease_out(t)) * scale
        S = self.S
        fnt = self.f('m', 58)
        sub_w = int(self.f('g', 26).getlength(sub) + 24 * S) if sub else 0     # 小さい字が切れないよう幅を広げる（2026-10-07 ユーザー「97％の下のラベルが消えてる」）
        w, h = max(int(fnt.getlength(text) + 60 * S), sub_w), int(96 * S)
        st = Image.new('RGBA', (w, h + (int(40 * S) if sub else 0)), (0, 0, 0, 0))
        dd = ImageDraw.Draw(st)
        dd.rounded_rectangle([4 * S, 4 * S, w - 4 * S, h - 4 * S], radius=12 * S, outline=COL['r'] + (255,), width=7 * S,
                             fill=(40, 0, 0, 170))
        dd.text((w / 2, h / 2), text, font=fnt, fill=COL['r'] + (255,), anchor='mm', stroke_width=2 * S,
                stroke_fill=(255, 255, 255, 255))
        if sub:
            dd.text((w / 2, h + 20 * S), sub, font=self.f('g', 26), fill=(255, 255, 255, 255), anchor='mm',
                    stroke_width=3 * S, stroke_fill=(0, 0, 0, 255))
        st = st.rotate(8, resample=Image.BICUBIC, expand=True)
        st = st.resize((max(1, int(st.width * k)), max(1, int(st.height * k))), Image.BICUBIC)
        st.putalpha(st.split()[3].point(lambda v: int(v * min(1, t * 2))))
        px, py = self.P(cx, cy)
        self.im.alpha_composite(st, (int(px - st.width / 2), int(py - st.height / 2)))

    def to_frame(self, L):
        """パネルを縮小して、配置（縦・横）の位置に置いた全画面の画像を返す。"""
        k = L.get('panel_scale', 1.0)             # パネルは 920×550 で描いて、配置の倍率で縮める（中の文字の位置は変えない）
        small = self.im.resize((round((PW + 2 * MARGIN) * k), round((PH + 2 * MARGIN) * k)), Image.LANCZOS)
        full = blank(L)
        px, py = L['panel']
        full.alpha_composite(small, (round(px - MARGIN * k), round(py - MARGIN * k)))
        return full


GRAY_TXT = (190, 190, 190)


def _ev(ev, k):
    """テロップの番号 k（1から）が出るフレーム。範囲外は大きな値（＝起きない）。"""
    if k is None:
        return 10 ** 9
    return ev[k - 1] if 1 <= k <= len(ev) else 10 ** 9


# ---------------------------------------------------------------- グラフ4種
def chart_line(c, f, ev, static=False):
    p = Panel()
    dy = p.base(f, c.get('title'), static)
    pts_spec = c['points']
    lo, hi = c['y_range']
    x0, x1, y0, y1 = 120, 800, 160, 430
    ym = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0) + dy
    n = len(pts_spec)
    xs = [x0 + i * (x1 - x0) / max(1, n - 1) for i in range(n)]
    ga = 255 if static else int(255 * ease_out(prog(f, 8, 10)))
    for i, (lab, _) in enumerate(pts_spec):
        p.text((xs[i], y1 + 42 + dy), lab, 'g', 26, (220, 220, 220), alpha=ga)
    p.text((PW / 2, 522 + dy), c.get('footnote', ''), 'g', 22, GRAY_TXT, alpha=ga)
    start = 0 if static else _ev(ev, c.get('start_on', 1))
    seg = c.get('segment_frames', 20)
    seg_start = [start + 7 + seg * i for i in range(n - 1)]
    th = c.get('threshold')
    if th:
        yt = ym(th['value'])
        p.dashed_line(x0 - 40, yt, x1 + 40, yt, COL['r'] + (255,), 4, upto=1.0 if static else ease_out(prog(f, 12, 16)))
        p.text((x0 - 70, yt), th.get('label', ''), 'g', 28, (245, 90, 90), alpha=ga)
    pts = [(xs[i], ym(v)) for i, (_, v) in enumerate(pts_spec)]
    drawn = [pts[0]] if (static or f >= start) else []
    for k, s0 in enumerate(seg_start):
        t = 1.0 if static else ease_out(prog(f, s0, seg))
        if t <= 0:
            break
        (ax, ay), (bx, by) = pts[k], pts[k + 1]
        drawn.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    glow_on = _ev(ev, c.get('glow_on'))
    lit = static or f >= glow_on
    if len(drawn) >= 2:
        col = (COL['y'] if lit and c.get('glow_on') else COL['w']) + (255,)
        if lit and c.get('glow_on'):
            p.glow(lambda d: d.line([p.P(*q) for q in drawn], fill=col, width=8 * p.S), radius=8, strength=1.3)
        else:
            p.d.line([p.P(*q) for q in drawn], fill=col, width=7 * p.S)
        hx, hy = drawn[-1]
        if not static and f < seg_start[-1] + seg:
            p.glow(lambda d: d.ellipse([*p.P(hx - 9, hy - 9), *p.P(hx + 9, hy + 9)], fill=COL['w'] + (255,)), radius=10)
    vf = c.get('value_format', '{}')
    for i, ((lab, v), (px, py)) in enumerate(zip(pts_spec, pts)):
        a = start if i == 0 else seg_start[i - 1] + seg - 2
        t = 1.0 if static else prog(f, a, 6)
        if t <= 0:
            continue
        last = i == n - 1 and c.get('highlight_last', True)
        r = (16 if last else 11) * (0.3 + 0.7 * ease_back(t))
        p.d.ellipse([*p.P(px - r, py - r), *p.P(px + r, py + r)], fill=(COL['y'] if last else COL['w']) + (255,))
        p.text((px, py - 44), fmt(v, vf), 'm', 44 if last else 36, COL['y'] if last else COL['w'], stroke=4,
               alpha=int(255 * min(1, t * 2)))
        if last and not static and f >= glow_on:
            for rep in range(3):
                if f - glow_on >= rep * 12:
                    ph = ((f - glow_on) - rep * 12) % 36
                    rr = 16 + ph * 1.6
                    p.d.ellipse([*p.P(px - rr, py - rr), *p.P(px + rr, py + rr)], outline=COL['y'] + (max(0, 200 - ph * 6),),
                                width=3 * p.S)
    if th and th.get('over_label'):
        vals = [v for _, v in pts_spec]
        cross_seg = next((k for k in range(n - 1) if vals[k] < th['value'] <= vals[k + 1]), None)
        if cross_seg is not None:
            frac = (th['value'] - vals[cross_seg]) / (vals[cross_seg + 1] - vals[cross_seg])
            cross = seg_start[cross_seg] + int(seg * frac)
            if static or f >= cross:
                t = 1.0 if static else prog(f, cross, 6)
                p.text((PW - 10, ym(th['value']) + 34), th['over_label'], 'm', 32, COL['r'], anchor='rm', stroke=4, alpha=int(255 * t))
    return p


def chart_hbar(c, f, ev, static=False):
    p = Panel()
    stamp = c.get('stamp') or {}
    ox, oy = shake(f, _ev(ev, stamp.get('on')) + 5, static=static) if stamp else (0, 0)
    dy = p.base(f, c.get('title'), static)
    rows = c['rows']
    lo, hi = c['x_range']
    xs, xe = 340, 790                                 # 値の文字がパネルからはみ出さない右端
    n_rows = max(1, len(rows))
    gap = min(190, 330 / n_rows)                      # 行を図の高さいっぱいに詰める（少ない行ほど大きく）。2026-10-07 ユーザー「隙間が多すぎる」
    half = min(66, gap * 0.36)                        # 棒の太さ（半分）。行が多いと従来の26
    y_top = 150 + (330 - gap * n_rows) / 2 + gap / 2
    f_val = int(38 + max(0, half - 30) * 0.8)         # 値の文字の大きさ（行が少ないほど大きい）

    def _tw(s, size):                                  # 文字列のおおよその幅（全角1.0・半角0.55）
        return sum(1.0 if ord(ch) > 255 else 0.55 for ch in s) * size

    f_lab = int(min(f_val + 2, 318 / max(1.0, max(_tw(str(r[0]), 1) for r in rows))))   # ラベルは左の枠（〜318）に収める
    xe = min(790, 910 - max(_tw(fmt(r[1], c.get('value_format', '{}')), f_val) for r in rows))   # 値の文字がパネルの右端を越えない
    flash_on = _ev(ev, c.get('flash_on'))
    lit_on = _ev(ev, stamp.get('on')) if stamp else 10 ** 9
    vf = c.get('value_format', '{}')
    n = len(rows)
    for i, row in enumerate(rows):
        name, v, hot = row[0], row[1], (row[2] if len(row) > 2 else False)
        y = y_top + i * gap + dy + oy
        a = 6 + (n - 1 - i) * 3
        p.text((320 + ox, y), name, 'm', f_lab, COL['w'], anchor='rm', alpha=255 if static else int(255 * ease_out(prog(f, a, 6))))
        if not static and prog(f, a, 16) <= 0:
            continue
        t = 1.0 if static else ease_back(prog(f, a, 16))
        xw = xs + (v - lo) / (hi - lo) * (xe - xs) * t
        col = (COL['y'] if hot else COL['gray']) + (255,)
        if hot and not static and f >= flash_on and (f - flash_on) < 14 and ((f - flash_on) // 3) % 2 == 0:
            col = COL['w'] + (255,)
        if hot and (static or f >= lit_on) and stamp:
            p.glow(lambda d, y=y, xw=xw, col=col: d.rounded_rectangle([*p.P(xs + ox, y - half), *p.P(xw + ox, y + half)],
                                                                     radius=8 * p.S, fill=col), radius=9)
        else:
            p.rect((xs + ox, y - half, xw + ox, y + half), col)
        val = v if static else lo + (v - lo) * ease_out(prog(f, a, 16))
        p.text((xw + 12 + ox, y), fmt(val, vf), 'm', f_val, COL['y'] if hot else COL['w'], anchor='lm', stroke=3)
    p.text((PW / 2, 522 + dy), c.get('footnote', ''), 'g', 22, GRAY_TXT, alpha=255 if static else int(255 * ease_out(prog(f, 10, 10))))
    if stamp:
        p.stamp(f, _ev(ev, stamp.get('on')) + 1, stamp['text'], stamp.get('x', 560) + ox, stamp.get('y', 202) + oy,
                sub=stamp.get('sub'), static=static, scale=stamp.get('scale', 1.0))
    return p


def chart_compare(c, f, ev, static=False):
    """縦棒2〜3本の比較。mode='shortfall'（必要＞使える の不足を示す）／'increase'（増えた差を示す）。"""
    p = Panel()
    mode = c.get('mode', 'increase')
    note_on = _ev(ev, c.get('note_on'))
    ox, oy = shake(f, note_on + (2 if mode == 'shortfall' else 4), amp=10 if mode == 'shortfall' else 7, static=static)
    dy = p.base(f, c.get('title'), static)
    bars = c['bars']
    base_y, top_y = 440 + dy, 170 + dy
    vmax = max(b['value'] for b in bars)
    sc = (base_y - top_y) / vmax
    step = 300 if mode == 'shortfall' else 360
    x_first = PW / 2 - step * (len(bars) - 1) / 2 - (40 if mode == 'shortfall' else 0)
    vf = c.get('value_format', '{}')
    tops = []
    for i, b in enumerate(bars):
        x = x_first + i * step + ox
        colname = b.get('color', 'gray')
        col = color(colname)
        a = _ev(ev, b.get('on'))
        p.text((x, base_y + 32), b['label'], 'm', 32, COL['w'], alpha=255 if static else int(255 * ease_out(prog(f, 6, 8))))
        tops.append((x, base_y - b['value'] * sc))
        if not static and prog(f, a, 18) <= 0:
            continue
        t = 1.0 if static else ease_back(prog(f, a, 18), 1.4)
        hgt = b['value'] * sc * t
        half = 70 if mode == 'shortfall' else 80
        p.rect((x - half, base_y - hgt, x + half, base_y), col + (255,), r=10)
        val = b['value'] if static else b['value'] * ease_out(prog(f, a, 18))
        if mode == 'shortfall':
            if hgt > 60:
                p.text((x, base_y - hgt + 34), fmt(val, vf), 'm', 36, COL['w'] if colname == 'r' else (20, 20, 20))
        else:
            p.text((x, base_y - hgt - 34), fmt(val, vf), 'm', 44, col if colname != 'gray' else COL['w'], stroke=4)
    label = c.get('note_label')
    if len(tops) >= 2 and (static or f >= note_on):
        t = 1.0 if static else prog(f, note_on, 8)
        (xa, ya), (xb, yb) = tops[0], tops[1]
        if mode == 'shortfall':
            blink = static or ((f - note_on) // 4) % 2 == 0
            p.d.rounded_rectangle([*p.P(xb - 74, min(ya, yb) - 2 + oy), *p.P(xb + 74, max(ya, yb) + 2 + oy)], radius=6 * p.S,
                                  outline=COL['r'] + (255 if blink else 140,), width=5 * p.S,
                                  fill=(245, 34, 34, 90 if blink else 40))
            if label:
                p.text((xb + 220, 290 + oy), label, 'm', 50, COL['y'], stroke=5, alpha=int(255 * t))
        else:
            p.dashed_line(xa + 80, ya + oy, xb - 80, ya + oy, COL['w'] + (220,), 3, seg=10, upto=ease_out(t) if not static else 1)
            p.d.rectangle([*p.P(xb - 80, yb + oy), *p.P(xb + 80, ya + oy)], outline=COL['r'] + (255,), width=5 * p.S)
            if label:
                k = 1.0 if static else 0.4 + 0.6 * ease_back(t)
                p.text(((xa + xb) / 2, 270 + oy), label, 'm', int(50 * k), COL['y'], stroke=5)
    p.text((PW / 2, 530 + dy), c.get('footnote', ''), 'g', 22, GRAY_TXT, alpha=255 if static else int(255 * ease_out(prog(f, 8, 10))))
    return p


def chart_hbar_seq(c, f, ev, static=False):
    """横棒を1本ずつ、呼ばれた順に出す（impact: true の行で揺れて光る）。"""
    p = Panel()
    rows = c['rows']
    imp = next((r for r in rows if r.get('impact')), None)
    ox, oy = shake(f, _ev(ev, imp['on']) + 16, amp=10, static=static) if imp else (0, 0)
    dy = p.base(f, c.get('title'), static)
    sub = c.get('subtitle') or {}
    if sub:
        p.text((PW / 2, 105 + dy), sub.get('text', ''), 'g', 24, (220, 220, 220),
               alpha=255 if static else int(255 * ease_out(prog(f, _ev(ev, sub.get('on', 1)), 8))))
    vmax = max(r['value'] for r in rows)
    xs, xe = 30, 820
    gap = min(150, 365 / max(1, len(rows)))           # 行を図の高さいっぱいに詰める（2026-10-07 ユーザー「隙間が多い」）
    bh = min(66, gap * 0.5)                           # 棒の太さ（従来46）
    f_l = 34 + int((bh - 46) * 0.4) if bh > 46 else 34
    vf = c.get('value_format', '{}')
    for i, r in enumerate(rows):
        big = r.get('impact', False)
        y = 165 + i * gap + dy + (oy if big else 0)
        x_off = ox if big else 0
        a = _ev(ev, r.get('on'))
        lt = 1.0 if static else ease_out(prog(f, a - 2, 6))
        p.text((xs + x_off, y - 26), r['label'], 'm', f_l, COL['w'], anchor='lm', alpha=int(255 * lt))
        if not static and prog(f, a, 18) <= 0:
            continue
        t = 1.0 if static else ease_back(prog(f, a, 18), 1.2)
        colname = r.get('color', 'gray')
        col = color(colname) + (255,)
        xw = xs + r['value'] / vmax * (xe - xs - 170) * t
        if big and (static or f >= a + 16):
            p.glow(lambda d, y=y, xw=xw, x_off=x_off, col=col: d.rounded_rectangle([*p.P(xs + x_off, y), *p.P(xw + x_off, y + bh)],
                                                                                   radius=8 * p.S, fill=col), radius=10, strength=1.2)
        else:
            p.rect((xs + x_off, y, xw + x_off, y + bh), col)
        val = r['value'] if static else r['value'] * ease_out(prog(f, a, 18))
        p.text((xw + 14 + x_off, y + bh / 2), fmt(val, vf), 'm', (f_l + 6) if big else f_l, color(colname) if colname != 'gray' else COL['w'],
               anchor='lm', stroke=3)
    p.text((PW / 2, 532 + dy), c.get('footnote', ''), 'g', 22, GRAY_TXT,
           alpha=255 if static else int(255 * ease_out(prog(f, _ev(ev, sub.get('on', 1)) if sub else 8, 8))))
    return p


CHART_TYPES = {'line': chart_line, 'hbar': chart_hbar, 'compare': chart_compare, 'hbar_seq': chart_hbar_seq}


def render_chart_frame(chart, L, f=0, ev=None, static=False):
    return CHART_TYPES[chart['type']](chart, f, ev or [], static).to_frame(L)


def _steps(cuts, n, draw):
    """XML だけの版の共通の道具：切り替わるフレームの並びから [(開始f, 終了f, 絵), ...] を作る。
    何も見えない区間は入れず、同じ絵が続く区間はつなぐ。draw(a, b) → その区間の絵（動きは済んだ形）"""
    cuts = sorted({0, n} | {c for c in cuts if 0 < c < n})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        img = draw(a, b)
        if img.getchannel('A').getbbox() is None:
            continue
        key = img.tobytes()
        if out and out[-1][1] == a and out[-1][3] == key:
            out[-1] = (out[-1][0], b, out[-1][2], key)
        else:
            out.append((a, b, img, key))
    return [(a, b, img) for a, b, img, _ in out]


def chart_steps(chart, L, ev, n):
    """XML だけの版：グラフを、言葉に合わせて切り替わる静止画の並びにする（棒が伸びる途中の数字を止め絵にしないよう、
    その区間までに出た分は伸び切った形・まだの分は出ていない形で描く）。ev はテロップが出るフレーム（図の頭から）"""
    return _steps(ev, n, lambda a, b: render_chart_frame(chart, L, 10 ** 6, [0 if e <= a else 10 ** 9 for e in ev]))


def shot_steps(item, steps, L, base, cache_dir, n):
    """XML だけの版：スクショを、言葉に合わせて切り替わる静止画の並びにする（寄り・マーカー・枠・ハンコは済んだ形）。
    steps は f（図の頭からのフレーム）が入ったもの"""
    steps = sorted(steps, key=lambda s: s['f'])
    a_in = item.get('enter_at', 0)

    def draw(a, b):
        past = [dict(s, f=-10 ** 6) for s in steps if s['f'] <= a]
        # 出てくる動き（9フレーム）が済んだ形で描く。出る前の区間（enter_at より前）は何も描かれない＝クリップにしない
        return Shot(dict(item, steps=past), L, base, cache_dir, n).frame(b - 1 if b <= a_in else max(b - 1, a_in + 9))
    return _steps([s['f'] for s in steps] + [a_in], n, draw)


# ---------------------------------------------------------------- 枠・引用カード（静止画）
def render_slot(item, L):
    p = Panel(S=1)
    p.d.rounded_rectangle([*p.P(0, 0), *p.P(PW, PH)], radius=26, fill=(0, 0, 0, 110))
    x0, y0 = p.P(0, 0)
    x1, y1 = p.P(PW, PH)
    dash(p.d, x0, y0, x1, y1, (255, 230, 0, 230), 4, 18)
    p.text((PW / 2, 80), '［差し替え］', 'g', 40, COL['y'])
    y = 150
    for ln in wrap(item['label'], font('g', 34), 860):
        p.text((PW / 2, y), ln, 'g', 34, COL['w'], stroke=3)
        y += 48
    y += 14
    for ln in wrap(item.get('hint', ''), font('g', 26), 860):
        p.text((PW / 2, y), ln, 'g', 26, (220, 220, 220), stroke=2)
        y += 38
    if item.get('url'):
        lines = wrap(item['url'], font('g', 20), 860)
        uy = 520 - (len(lines) - 1) * 26
        for ln in lines:
            p.text((PW / 2, uy), ln, 'g', 20, (180, 180, 180))
            uy += 26
    return p.to_frame(L)


def render_quote(item, L):
    p = Panel(S=1)
    p.base(0, None, static=True)
    p.text((PW / 2, 70), item.get('caption', ''), 'g', item.get('caption_size', 30), (220, 220, 220))
    layer = Image.new('RGBA', p.im.size, (0, 0, 0, 0))
    lines = [[(t, item.get('color', 'w'))] if isinstance(t, str) else [(t[0], t[1])] for t in item['lines']]   # 行は文字か [文字, 色]
    draw_rich(layer, lines, p.P(PW / 2, 270)[0], p.P(PW / 2, 270)[1], item.get('size', 70), 860)
    p.im.alpha_composite(layer)
    for i, ln in enumerate(wrap(item.get('source', ''), font('g', item.get('source_size', 22)), 880)):   # 出典（長ければ2行）
        p.text((PW / 2, 495 + i * item.get('source_size', 22) * 1.3), ln, 'g', item.get('source_size', 22), (200, 200, 200))
    return p.to_frame(L)


# ---------------------------------------------------------------- スクショの動き（shot）
# 資料（PDF のページか画像）を「カード」にして、寄る・マーカーを引く・赤枠・ハンコ・揺れ、を
# ナレーションの目印に合わせて動かす。座標は資料の座標（PDF はポイント、画像は px）。
# 手順（steps）は build_premiere.py が「何フレーム目に起きるか」（f）を決めて timeline.json に書く。
import json as _json  # noqa: E402
import subprocess as _sp  # noqa: E402

from PIL import ImageChops  # noqa: E402

_docs = {}


def ease_io(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def load_doc(src, base, cache_dir):
    """source の指定から (資料の画像 RGB, 座標→px の倍率) を返す。PDF は pdftoppm で描いて cache_dir にためる。"""
    key = _json.dumps(src, sort_keys=True, ensure_ascii=False)
    if key in _docs:
        return _docs[key]
    if 'pdf' in src:
        pdf = (Path(base) / src['pdf']).resolve()
        dpi, page = src.get('dpi', 300), src.get('page', 1)
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        stem = Path(cache_dir) / f'{pdf.stem}_p{page}_{dpi}dpi'
        png = stem.with_suffix('.png')
        if not png.exists():
            _sp.run(['pdftoppm', '-f', str(page), '-l', str(page), '-r', str(dpi), '-png', '-singlefile', str(pdf), str(stem)],
                    check=True)
        im, k = Image.open(png).convert('RGB'), dpi / 72
    else:
        im, k = Image.open((Path(base) / src['image']).resolve()).convert('RGB'), src.get('scale', 1.0)
    _docs[key] = (im, k)
    return im, k


def _fit(rect, bounds, amin=1.15, amax=2.6):
    """表示範囲 rect を、縦横比 amin〜amax に広げ、資料の外に出ないようにずらす。"""
    x0, y0, x1, y1 = rect
    bw, bh = bounds
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if w / h < amin:
        w = h * amin
    elif w / h > amax:
        h = w / amax
    w, h = min(w, bw), min(h, bh)
    x0 = min(max(cx - w / 2, 0), bw - w)
    y0 = min(max(cy - h / 2, 0), bh - h)
    return (x0, y0, x0 + w, y0 + h)


def _stamp_img(text, sub, S=1):
    fnt = font('m', 58 * S)
    bw, h = int(fnt.getlength(text) + 60 * S), int(96 * S)          # ハンコの枠の幅
    w = max(bw, int(font('g', 24 * S).getlength(sub) + 24 * S)) if sub else bw   # 下の小さい字が切れない幅
    st = Image.new('RGBA', (w, h + (int(44 * S) if sub else 0)), (0, 0, 0, 0))
    dd = ImageDraw.Draw(st)
    x0 = (w - bw) / 2
    dd.rounded_rectangle([x0 + 4 * S, 4 * S, x0 + bw - 4 * S, h - 4 * S], radius=12 * S, outline=COL['r'] + (255,),
                         width=7 * S, fill=(40, 0, 0, 185))
    dd.text((w / 2, h / 2), text, font=fnt, fill=COL['r'] + (255,), anchor='mm', stroke_width=2 * S,
            stroke_fill=(255, 255, 255, 255))
    if sub:
        dd.text((w / 2, h + 22 * S), sub, font=font('g', 24 * S), fill=(255, 255, 255, 255), anchor='mm',
                stroke_width=3 * S, stroke_fill=(0, 0, 0, 255))
    return st.rotate(8, resample=Image.BICUBIC, expand=True)


class Shot:
    """1つのスクショの動き。frame(f) で全画面（透明背景）の1枚を返す。"""

    def __init__(self, item, L, base, cache_dir, n):
        self.it, self.L, self.n = item, L, n
        self.doc, self.k = load_doc(item['source'], base, cache_dir)
        self.bounds = (self.doc.width / self.k, self.doc.height / self.k)
        ax0, ay0, ax1, ay1 = L['shot_area']
        self.area = (ax0, ay0, ax1, ay1)
        self.steps = sorted(item.get('steps', []), key=lambda s: s['f'])
        first = item.get('view') or [0, 0, *self.bounds]
        self.views = [(0, 0, _fit(first, self.bounds))]      # (開始フレーム, 長さ, 表示範囲)
        for s in self.steps:
            if 'view' in s:
                v = [0, 0, *self.bounds] if s['view'] == 'page' else s['view']
                self.views.append((s['f'], s.get('dur', 14), _fit(v, self.bounds)))
        self.stamps = [(_stamp_img(s['stamp'], s.get('sub')), s) for s in self.steps if 'stamp' in s]

    def view_at(self, f):
        cur = self.views[0][2]
        for a, dur, v in self.views[1:]:
            if f < a:
                break
            t = ease_io(prog(f, a, dur))
            cur = tuple(c + (d - c) * t for c, d in zip(cur, v))
        drift = self.it.get('drift', 0.035) * f / max(1, self.n)       # ずっと少しずつ寄る
        x0, y0, x1, y1 = cur
        cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * (1 - drift), (y1 - y0) * (1 - drift)
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def frame(self, f):
        L = self.L
        ax0, ay0, ax1, ay1 = self.area
        AW, AH = ax1 - ax0, ay1 - ay0
        vx0, vy0, vx1, vy1 = self.view_at(f)
        s = min(AW / (vx1 - vx0), AH / (vy1 - vy0))
        cw, ch = max(2, int((vx1 - vx0) * s)), max(2, int((vy1 - vy0) * s))
        k = self.k
        card = self.doc.resize((cw, ch), Image.BICUBIC, box=(vx0 * k, vy0 * k, vx1 * k, vy1 * k), reducing_gap=2.0)
        X = lambda x: (x - vx0) / (vx1 - vx0) * cw
        Y = lambda y: (y - vy0) / (vy1 - vy0) * ch
        ov = Image.new('RGBA', card.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        punch, shake_at, flash_at, spots = 0.0, [], [], []
        for st in self.steps:
            a = st['f']
            if f < a:
                continue
            if 'mark' in st:                          # マーカーを左から引く（複数行は順に）
                rects = st['mark'] if isinstance(st['mark'][0], (list, tuple)) else [st['mark']]
                total = sum(r[2] - r[0] for r in rects) or 1
                p = ease_out(prog(f, a, st.get('dur', 10))) * total
                col = color(st.get('color', 'y'))
                for r in rects:
                    seg = r[2] - r[0]
                    if p <= 0:
                        break
                    xe = r[0] + seg * min(1.0, p / seg)
                    p -= seg
                    box = [int(X(r[0])), int(Y(r[1])), int(X(xe)), int(Y(r[3]))]
                    if box[2] - box[0] >= 1 and box[3] - box[1] >= 1:
                        region = card.crop(box)
                        card.paste(ImageChops.multiply(region, Image.new('RGB', region.size, col)), box[:2])
                if st.get('punch', True):
                    punch = max(punch, math.sin(math.pi * prog(f, a, 8)) * 0.035)
                if st.get('spot'):
                    spots.append((rects, prog(f, a + st.get('dur', 10), 6)))
            if 'box' in st:                           # 赤い枠で囲む
                x0, y0, x1, y1 = st['box']
                t = ease_back(prog(f, a, 7), 1.4)
                pad = 10 * (2 - t)
                od.rounded_rectangle([X(x0) - pad, Y(y0) - pad, X(x1) + pad, Y(y1) + pad], radius=10,
                                     outline=COL['r'] + (int(255 * min(1, t * 1.5)),), width=6)
            if 'stamp' in st:
                shake_at.append(a + 2)
                flash_at.append(a + 2)
        for rects, t in spots:                        # まわりを暗くして、そこだけ見せる
            if t <= 0:
                continue
            dim = Image.new('L', card.size, int(120 * t))
            dd = ImageDraw.Draw(dim)
            for r in rects:
                dd.rounded_rectangle([X(r[0]) - 8, Y(r[1]) - 8, X(r[2]) + 8, Y(r[3]) + 8], radius=8, fill=0)
            dim = dim.filter(ImageFilter.GaussianBlur(6))
            black = Image.new('RGBA', card.size, (0, 0, 0, 255))
            black.putalpha(dim)
            ov = Image.alpha_composite(black, ov)
        card = card.convert('RGBA')
        card.alpha_composite(ov)
        for a in flash_at:                            # ハンコの瞬間に白く光る
            if a <= f < a + 5:
                wf = Image.new('RGBA', card.size, (255, 255, 255, int(120 * (1 - (f - a) / 5))))
                card.alpha_composite(wf)
        # 白い縁・角丸・影
        B = 6
        framed = Image.new('RGBA', (cw + 2 * B, ch + 2 * B), (255, 255, 255, 255))
        framed.paste(card, (B, B))
        mask = Image.new('L', framed.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, framed.width - 1, framed.height - 1], radius=14, fill=255)
        framed.putalpha(mask)
        # 出てくる動き＋寄りの「ポン」
        a_in = self.it.get('enter_at', 0)
        te = prog(f, a_in, 9)
        sc = (0.86 + 0.14 * ease_back(te, 1.6)) * (1 + punch)
        alpha = ease_out(prog(f, a_in, 5))
        if abs(sc - 1) > 1e-3:
            framed = framed.resize((max(2, int(framed.width * sc)), max(2, int(framed.height * sc))), Image.BICUBIC)
        ox, oy = 0, 0
        for a in shake_at:
            dx, dy = shake(f, a, amp=12, dur=9)
            ox, oy = ox + dx, oy + dy
        cx, cy = (ax0 + ax1) / 2 + ox, (ay0 + ay1) / 2 + oy + (1 - ease_out(te)) * 40
        out = blank(L)
        shadow = Image.new('RGBA', (framed.width + 60, framed.height + 60), (0, 0, 0, 0))
        sa = Image.new('L', shadow.size, 0)
        sa.paste(framed.split()[3].point(lambda v: int(v * 0.6)), (30, 30))
        shadow.putalpha(sa.filter(ImageFilter.GaussianBlur(12)))
        px, py = int(cx - framed.width / 2), int(cy - framed.height / 2)
        if alpha < 1:
            framed.putalpha(framed.split()[3].point(lambda v: int(v * alpha)))
            shadow.putalpha(shadow.split()[3].point(lambda v: int(v * alpha)))
        out.alpha_composite(shadow, (px - 30 + 8, py - 30 + 12))
        out.alpha_composite(framed, (px, py))
        cap = self.it.get('caption')                  # 資料名の帯
        if cap:
            ca = int(255 * alpha * ease_out(prog(f, a_in + 4, 6)))
            if ca > 0:
                fc = font('g', 26)
                tw = fc.getlength(cap)
                bx0, by0 = max(20, px - 4), max(10, py - 30)
                bar = Image.new('RGBA', out.size, (0, 0, 0, 0))
                bd = ImageDraw.Draw(bar)
                bd.rounded_rectangle([bx0, by0, bx0 + tw + 36, by0 + 46], radius=10, fill=(20, 24, 40, 230))
                bd.text((bx0 + 18, by0 + 23), cap, font=fc, fill=(255, 255, 255, 255), anchor='lm')
                if ca < 255:
                    bar.putalpha(bar.split()[3].point(lambda v: v * ca // 255))
                out.alpha_composite(bar)
        for img, st in self.stamps:                   # ハンコ（押す瞬間に大きく→縮む）
            a = st['f']
            t = prog(f, a, 6)
            if t <= 0:
                continue
            kk = 1.9 - 0.9 * ease_out(t)
            im2 = img.resize((max(1, int(img.width * kk)), max(1, int(img.height * kk))), Image.BICUBIC)
            im2.putalpha(im2.split()[3].point(lambda v: int(v * min(1, t * 2))))
            fx, fy = st.get('pos', [0.74, 0.7])
            sx, sy = ax0 + AW * fx + ox, ay0 + AH * fy + oy
            out.alpha_composite(im2, (int(sx - im2.width / 2), int(sy - im2.height / 2)))
        return out


# ---------------------------------------------------------------- 見せ方の型（spec の telop_style・chars_grow）
def apply_style(spec, base):
    """spec の最上位の見せ方の型を、各テロップ・各イラストに広げる（build_premiere・build_anim が spec を読んだ直後に呼ぶ）。

    telop_style: "dopa"（2026-10-07 みなさまの声編 v3c でユーザー「かなり良い」。化け学のふしぎのショートの型）
      全部のテロップ：書体 HiraginoSans-W9（spec の font_ps が未指定なら）・size l・縁取り 16px・座布団なし・水平・
      motion "grow"（25％→5フレームで100％→終わりに110％）。2段目以降は、その行の頭の言葉（5〜3字）が読まれた瞬間に
      時間差で出す（line_at を台本の文から自動で探す。テロップに書いた値が優先）
    chars_grow: 1.15 など（人物＝ref head の絵で、出方が cut でないものに grow を付ける。ぽんっと出て大きくなり続ける）
    """
    import json as _json
    st = spec.get('telop_style')
    if st == 'dopa':
        spec.setdefault('font_ps', 'HiraginoSans-W9')
        nar = {}
        sp = spec.get('script')
        if sp:
            txt = (Path(base) / sp).read_text(encoding='utf-8')
            if '```' in txt:
                for ln in txt.split('```')[1].strip().splitlines():
                    m = re.match(r'^(\d+)\s+\S+?：(.*)$', ln)
                    if m:
                        nar[m.group(1)] = m.group(2)
        for ln, tels in (spec.get('lines') or {}).items():
            pos = 0
            txt = nar.get(str(ln), '')
            for tel in tels:
                a0 = txt.find(tel.get('anchor', ''), pos)
                pos = a0 if a0 >= 0 else pos
                tel.setdefault('size', 'l')
                tel.setdefault('stroke_px', 16)
                tel.setdefault('box', False)
                tel.setdefault('motion', 'grow')
                if 'line_at' in tel or len(tel.get('lines', [])) < 2:
                    continue
                la, p2 = [None], pos
                for s, _ in tel['lines'][1:]:
                    key = re.sub(r'[「」『』、。！？!?\s]', '', s)
                    hit = None
                    for n in (5, 4, 3):
                        if len(key) >= n:
                            j = txt.find(key[:n], p2)
                            if j > p2:
                                hit = (j, key[:n])
                                break
                    la.append({'line': int(ln), 'anchor': hit[1]} if hit else None)
                    if hit:
                        p2 = hit[0]
                if any(la[1:]):
                    tel['line_at'] = la
    elif st:
        raise SystemExit(f'telop_style「{st}」は知らない型（いまは "dopa" だけ）')
    g = spec.get('chars_grow')
    if g:
        for c in spec.get('chars', []):
            for a in c.get('actors', []):
                if a.get('place', {}).get('ref', 'head') == 'head' and a.get('img') and (a.get('in') or {}).get('how') != 'cut':
                    a.setdefault('grow', g)
    band = spec.get('figures_band')
    if band:
        # figures_band: [上, 下]（新しい回は [270, 820]＝2026-10-11。common の既定は [270, 900]）。図・顔をこの帯に収めて、テロップ（新しい回は中心 y1010・common の既定 1040）と重ねない
        # （2026-10-07 ユーザー「テロップは絵・図と重ねない」。ジョン万編 make_spec.py 末尾の後処理を spec のキーにした 2026-10-09）。
        # 人物（ref head）は頭の上端を上の線より下に・あごから下（crop_bottom）を下の線で切る。小物（ref center）は帯に入る大きさまで
        # 縮め、中心を帯の中に。出方が cut（冒頭のサムネ）と差し替え枠（透明）はそのまま
        top_y, bot_y = band
        for c in spec.get('chars', []):
            for a in c.get('actors', []):
                if 'img' not in a or (a.get('in') or {}).get('how') == 'cut' or a.get('band') is False:   # band: false＝テロップのない行で帯の外に置く絵（2026-10-14）
                    continue
                pl = a.setdefault('place', {})
                if pl.get('ref', 'head') == 'head':
                    a['crop_bottom'] = min(a.get('crop_bottom', bot_y), bot_y)
                    pl['y'] = max(pl.get('y', top_y), top_y)
                    continue
                p = Path(base) / a['img']
                if not p.exists():
                    continue
                im = Image.open(p)
                if im.mode != 'RGBA':
                    im = im.convert('RGBA')
                b = im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
                if not b:
                    continue
                h = b[3] - b[1]
                pl['scale'] = round(min(pl.get('scale', 1.0), (bot_y - top_y) / h), 3)
                hh = h * pl['scale']
                pl['y'] = round(min(max(pl.get('y', top_y), top_y + hh / 2), bot_y - hh / 2))
    return spec


FONT_LABEL = {'HiraMinProN-W6': 'ヒラギノ明朝 ProN W6', 'HiraMinProN-W3': 'ヒラギノ明朝 ProN W3',
              'HiraginoSans-W3': 'ヒラギノ角ゴシック W3', 'HiraginoSans-W6': 'ヒラギノ角ゴシック W6',
              'HiraginoSans-W7': 'ヒラギノ角ゴシック W7', 'HiraginoSans-W8': 'ヒラギノ角ゴシック W8', 'HiraginoSans-W9': 'ヒラギノ角ゴシック W9'}


def font_label(ps):
    """PostScript 名 → 日本語の書体名（README の「フォントを置換」の説明用。2026-10-09、README が書体を明朝で決め打ちしていたのを直した）"""
    return FONT_LABEL.get(ps or 'HiraMinProN-W6', ps or 'HiraMinProN-W6')
