---
name: telop-fx
description: 動画にテレビのバラエティ・ニュース風の「決めテロップ」を入れる。90 種の見た目（多重の縁・グラデーション・金属・ネオン・爆発の台座・3D 回転・4択クイズのパネル・ニュースの帯・街頭インタビュー風の字幕・選挙特番風の題字ほか）から気分の名前で選び、文字ごと焼き込んだ動画（mp4）か、編集ソフトに重ねる透明つきの動画（ProRes 4444 .mov）・止め絵（PNG）を作る。使用場面 (1) この動画の○秒に「…」をテロップで入れて、(2) 派手なテロップ・決めテロップ・テロップの装飾を作りたい、(3) テロップの見本・カタログを見たい・選びたい、(4) 透明のテロップ素材を Premiere・Final Cut・DaVinci に重ねたい。トリガー "テロップを入れて", "テロップを焼き込んで", "決めテロップ", "派手なテロップ", "テロップの見本", "テロップカタログ", "telop", "/telop-fx"
---

# telop-fx：動画に決めテロップを入れる

カタログ（見本の動画つき）：https://darksideofnhk.github.io/telop-fx/

## 何ができるか

- **動画に焼き込む**：動画と「何秒から何秒に、どの文字を、どの気分で」を並べた JSON から、テロップ入りの mp4 を作る（音はそのまま）
- **素材だけ作る**：1 本のテロップを、透明つきの動画（.mov・ProRes 4444）か止め絵（.png）にする。編集ソフトのタイムラインに重ねて使う
- **見本を作り直す**：90 枚のカード（見本の動画・止め絵）と一覧ページ

縦（1080×1920）と横（1920×1080）のどちらにも使える。動画の向きで自動で選ぶ。

## Claude Code がすること（テロップを入れる流れ）

1. **何を入れるか決める**：ユーザーの言葉から、時刻（start・end 秒）・文字（1 行 8 字ほどまで。長いときは 2〜3 行に分ける）・気分を決める。気分はカタログの名前（下の表）。迷ったら `python3 ~/.claude/skills/telop-fx/scripts/telop_fx.py list` で一覧を見る。時刻が分からないときは、動画の長さ（ffprobe）と話の流れから仮に置き、ユーザーに確かめる
2. **telops.json を書く**（作業フォルダに）：

```json
[
  {"start": 0.5, "end": 2.5, "lines": [["受信料", "w"], ["ゼロ円!?", "r"]], "fx": "bakuhatsu"},
  {"start": 3.0, "end": 5.5, "lines": [["受信料って本当に", "w"], ["払う必要あるの？", "w"]],
   "fx": {"mood": "jimaku", "paint": {"払う必要": "r"}}, "y": 1450, "px": 96}
]
```

   - `lines`：`[文字, 色]`。色は `w` 白・`y` 黄・`r` 赤・`p` ピンク・`o` 橙・`g` 緑・`c` 水色・`b` 青・`v` 紫・`k` 黒。行の色がそのまま型の色になる
   - `fx`：気分の名前か、`{"mood": 名前, ...}`。行の中の一部の語だけ色を替えるのは `paint`（`{"語": "色"}`）。札の文字は `tag`、話し手の色の縁は `edge`、語を色の箱に入れるのは `box_words`。カタログの「写す」の一行がそのまま使える
   - `y`：まとまりの中心の高さ（px。省くと縦 1040・横 860）。`px`：字の大きさ（省くと 120）

3. **焼き込む**：

```bash
python3 ~/.claude/skills/telop-fx/scripts/burn_telops.py --video in.mp4 --telops telops.json --out out.mp4
```

4. **確かめる**：テロップが出ている時刻のコマを抜いて見る（`ffmpeg -ss 秒 -i out.mp4 -frames:v 1 check.png`）。字が読めるか・顔や大事な所にかかっていないか・行がはみ出していないかを見てから、ユーザーに渡す。直すときは telops.json を直して 3 からやり直す

## 素材だけ作る（編集ソフトに重ねる）

```bash
python3 ~/.claude/skills/telop-fx/scripts/telop_fx.py render --text '受信料/ゼロ円!?' --color w,r --fx bakuhatsu --out a.mov --sec 2.5
python3 ~/.claude/skills/telop-fx/scripts/telop_fx.py render --text スクランブル化 --color y --fx kaisan_2026 --out a.png
```

`--layout horizontal` で横の画面。`--paint 語=色`・`--tag`・`--edge`・`--box` も使える。

## 気分（よく使うもの）

| 場面 | 気分 |
|---|---|
| 怒り・告発 | `ikari` |
| 驚きの数字・金額 | `suuji` |
| 速報・見出し | `sokuhou`・`news_obi`・`sokuho_flash` |
| 爆発・大声 | `bakuhatsu` |
| 炎上 | `honoo` |
| 二択の問いを回して明かす | `kaiten_tate`・`kaiten_yoko`（行＝面。2 行目の時刻で回る） |
| 4 択クイズ | `yontaku`（1 行目＝問題、2 行目から選択肢。`answer` で正解） |
| 話し言葉の字幕 | `jimaku`・`news_jimaku`・`gaitou_sub` |
| 本音・言い切りの一言 | `honne`・`gaitou_aka`・`gaitou_shiro` |
| ニュース番組風 | `news_head`・`news_cap`・`kaisetsu`・`jouhou_title` |
| 選挙特番風の題字 | `kaisan_2005`〜`kaisan_2026`（`tint` で色、`metal: true` で字も金属） |
| 写真の横の「実際の○○」 | `tatefuda` |

全部の名前と見た目はカタログで。カタログの「NHK」の区分は、作者が NHK 系の動画で使うかどうかの使い分け（読みやすさ・点滅しないかで決めた）。

## 決まり

- **読めることが先**：見せ場の言葉だけに使う。点滅させ続ける・横に揺らし続ける動きは酔いやすいので控える
- 局や番組のロゴ・番組名は描かない（字が要るなら普通の字で）。作り話のニュースを本物の速報の見た目で出さない
- 書体は macOS 同梱のヒラギノ（角ゴ W6〜W9・明朝・丸ゴ）。ほかの書体は `assets/fonts/` に置くとファイル名で呼べる

## 必要なもの

- macOS（ヒラギノの書体を使う）
- Python 3 と Pillow（`pip3 install pillow`）
- ffmpeg（`brew install ffmpeg`）

## カタログを作り直す

```bash
python3 ~/.claude/skills/telop-fx/scripts/telop_fx.py cards            # 90 枚の見本（catalog/。TELOP_CATALOG_DIR で場所を替えられる）
python3 ~/.claude/skills/telop-fx/scripts/telop_fx.py list             # 型・動き・気分の一覧
```
