#!/bin/bash
# スキル telop-fx を ~/.claude/skills に入れる（シンボリックリンク）。同じ名前のものがリンク以外で既にあるときは上書きしない。
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/skills"
dst="$HOME/.claude/skills/telop-fx"
if [ -e "$dst" ] && [ ! -L "$dst" ]; then
  echo "スキップ: $dst が既にある（リンクではないので上書きしない）"
  exit 0
fi
ln -sfn "$here/skills/telop-fx" "$dst"
echo "スキル: $dst → $here/skills/telop-fx"
command -v ffmpeg >/dev/null || echo "注意: ffmpeg がない（brew install ffmpeg）"
python3 -c "import PIL" 2>/dev/null || echo "注意: Pillow がない（pip3 install pillow）"
