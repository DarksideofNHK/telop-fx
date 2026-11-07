"""NHK 系の動画で使わない決めテロップの決まり（作者の動画での使い分け）。telop_fx.py のカタログが NHK の区分に使う"""
BANNED_FX = ('odoroki', 'kirakira', 'tsukkomi', 'shizuka', 'gouka', 'shoutai', 'happyou', 'henshin', 'kakumei', 'shindoi', 'tassei')
BANNED_FX_STYLE = ('rainbow', 'kinmin', 'hikari')
BANNED_FX_HOLD = ('sway', 'tenmetsu')
BANNED_FX_IN_PREFIX = ('glow_', 'blink')
BANNED_FX_WHY = {'odoroki': '黄色が明るすぎる', 'bakuhatsu': '黄色が明るすぎる', 'kirakira': '虹色', 'tsukkomi': '左右に揺れ続ける', 'suuji': '銀の字に光で字がにじむ', 'rainbow': '虹色', 'burst': '背景と透過できない', 'obi': '座布団が変', 'fire': '背景と透過できない', 'sway': '左右に揺れ続ける', 'kinmin': '金の光で字がにじむ', 'hikari': '白い光で字がにじむ', 'shiromin': '白い光で字がにじむ', 'glow_': '白い光の塊で入って字がにじむ', 'blink': '点滅する（チラチラ）', 'tenmetsu': '点滅する（チラチラ）', 'shizuka': '使わない（2026-11-07 夜）', 'gouka': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）', 'shoutai': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）', 'happyou': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）', 'henshin': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）', 'kakumei': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）', 'shindoi': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）', 'tassei': '白く光る・金で字がにじむ（グロー系・2026-11-07 職員と学歴編）'}
