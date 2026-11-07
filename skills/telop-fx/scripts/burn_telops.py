"""動画に決めテロップを焼き込む（2026-11-07。Claude Code から「この動画の 3 秒目に『受信料ゼロ円!?』を bakuhatsu で」のように入れる用）。

usage:
  python3 burn_telops.py --video in.mp4 --telops telops.json --out out.mp4 [--keep]

telops.json（並び）：
  [{"start": 1.0, "end": 3.2, "lines": [["受信料", "w"], ["ゼロ円!?", "r"]], "fx": "bakuhatsu"},
   {"start": 4.0, "end": 6.0, "lines": [["受信料って本当に", "w"], ["払う必要あるの？", "w"]],
    "fx": {"mood": "jimaku", "paint": {"払う必要": "r"}}, "y": 1500, "px": 96}]
  - start・end：秒。lines：[文字, 色キー]（色キー w 白・y 黄・r 赤・p ピンク・o 橙・g 緑・c 水色・b 青・v 紫・k 黒）
  - fx：気分の名前（telop_fx.py list・カタログの「写す」の一行）か dict（mood＋paint・tag・edge など）
  - y：まとまりの中心の高さ（px。省くと縦 1040・横 860）。px：字の大きさ（省くと 120）
動画が縦（高さ＞幅）なら 1080×1920、横なら 1920×1080 の画面として描き、動画の大きさに合わせて重ねる。音はそのまま写す。
決めテロップは telop_fx.FxTelop が 1 本ずつ透明つきの動画（ProRes 4444）に描き、ffmpeg で時刻どおりに重ねる。
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LAYOUTS  # noqa: E402
from telop_fx import FxTelop, resolve_fx, write_mov  # noqa: E402


def probe(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate',
                          '-of', 'json', str(video)], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    a, b = s['r_frame_rate'].split('/')
    has_audio = bool(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0',
                                     str(video)], capture_output=True, text=True).stdout.strip())
    return int(s['width']), int(s['height']), float(a) / float(b or 1), has_audio


def item_of(t, L):
    """telops.json の 1 つ → FxTelop の item（行のベースラインを、まとまりの中心 y から積む）"""
    lines = t['lines']
    px = float(t.get('px', 120))
    y = float(t.get('y', L.get('telop_block_y', L['H'] * .54)))
    pitch = px * L.get('line_pitch', 1.2)
    top = y - pitch * len(lines) / 2
    its = []
    for i, ln in enumerate(lines):
        text, color = (ln, 'w') if isinstance(ln, str) else (ln[0], ln[1] if len(ln) > 1 else 'w')
        its.append({'text': str(text), 'color': color, 'px': px, 'baseline': top + pitch * i + (pitch - px) / 2 + .88 * px, 'delay': 0})
    resolve_fx(t.get('fx') or 'ikari')               # 名前の書き間違いはここで止める
    return {'lines': its, 'fx': t.get('fx') or 'ikari'}


def main():
    ap = argparse.ArgumentParser(description='動画に決めテロップを焼き込む')
    ap.add_argument('--video', required=True)
    ap.add_argument('--telops', required=True, help='テロップの並び（JSON）')
    ap.add_argument('--out', required=True)
    ap.add_argument('--keep', action='store_true', help='テロップの透明動画（.mov）を残す（out と同じ場所の _telops/）')
    a = ap.parse_args()
    W, H, fps, has_audio = probe(a.video)
    L = dict(LAYOUTS['vertical' if H > W else 'horizontal'])
    tel = json.loads(Path(a.telops).read_text(encoding='utf-8'))
    tmp = Path(a.out).with_name(Path(a.out).stem + '_telops') if a.keep else Path(tempfile.mkdtemp(prefix='telops_'))
    tmp.mkdir(parents=True, exist_ok=True)
    r = max(1, round(fps))
    movs = []
    for i, t in enumerate(tel):
        s, e = float(t['start']), float(t['end'])
        n = max(1, round((e - s) * r))
        dst = tmp / f'telop_{i:02d}.mov'
        write_mov(FxTelop(item_of(t, L), L, n), dst, r)
        movs.append((dst, s, e))
        print(f'テロップ {i + 1}/{len(tel)}：{s:.2f}〜{e:.2f} 秒', ' / '.join(str(x[0]) for x in t['lines']))
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str(a.video)]
    for m, s, _ in movs:
        cmd += ['-itsoffset', f'{s:.3f}', '-i', str(m)]
    fl, last = [], '0:v'
    for k, (_, s, e) in enumerate(movs, 1):
        fl.append(f'[{k}:v]scale={W}:{H}[t{k}]')
        fl.append(f"[{last}][t{k}]overlay=0:0:eof_action=pass:enable='between(t,{s:.3f},{e:.3f})'[v{k}]")
        last = f'v{k}'
    cmd += ['-filter_complex', ';'.join(fl) if fl else 'null', '-map', f'[{last}]' if fl else '0:v']
    if has_audio:
        cmd += ['-map', '0:a', '-c:a', 'copy']
    cmd += ['-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(a.out)]
    subprocess.run(cmd, check=True)
    print('できた:', a.out)


if __name__ == '__main__':
    main()
