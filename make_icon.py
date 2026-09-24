# -*- coding: utf-8 -*-
"""生成程序图标 szu_grab.ico

设计：深大红圆角方块 + 白色「抢」字，右下角一个小金闪电。
      红是主色，金是辅色，「抢」直接点题——一眼能看出跟抢课有关。

配色出处：深圳大学官网自己的样式表 https://www.szu.edu.cn/css/style.css
    主色 #930A41 出现 32 次（另有 #a20a47、#b40048 两个亮一档的变体）
    金色 #CE9C44 出现 32 次，作辅色
不是凭空挑的色。

改颜色/换字改下面三个常量即可，然后跑：
    python make_icon.py
"""

import os

from PIL import Image, ImageDraw, ImageFont

# ---- 可调 ----
RED = (0x93, 0x0A, 0x41)        # 深大主色
GOLD = (0xCE, 0x9C, 0x44)       # 深大辅色
GLYPH = "抢"                     # 图标里的字
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
)

SUPERSAMPLE = 8      # 超采样倍数，先画大再缩，边缘才平滑
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _font_path():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise SystemExit("找不到可用的中文字体，请修改 FONT_CANDIDATES")


def render(size):
    """画一张 size×size 的图标。"""
    n = size * SUPERSAMPLE
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角方块铺满画布。半径按比例给，缩小后看起来才匀称。
    draw.rounded_rectangle([0, 0, n - 1, n - 1],
                           radius=int(n * 0.23), fill=RED)

    # 「抢」：以字的墨迹外框居中，而不是按字体行高居中，否则会偏下
    font = ImageFont.truetype(_font_path(), int(n * 0.62), index=0)
    left, top, right, bottom = draw.textbbox((0, 0), GLYPH, font=font)
    # 往左上挪一点，把右下角让给闪电，两者不打架
    x = (n - (right - left)) / 2 - left - n * 0.05
    y = (n - (bottom - top)) / 2 - top - n * 0.07
    draw.text((x, y), GLYPH, font=font, fill=(255, 255, 255, 255))

    # 右下角一点金闪电：小尺寸下只是暖色点缀，大尺寸下能看出是闪电
    bx, by, bw, bh = n * 0.76, n * 0.70, n * 0.115, n * 0.20
    draw.polygon([(bx + bw * 0.55, by),
                  (bx, by + bh * 0.58),
                  (bx + bw * 0.42, by + bh * 0.58),
                  (bx + bw * 0.18, by + bh),
                  (bx + bw, by + bh * 0.40),
                  (bx + bw * 0.50, by + bh * 0.40)],
                 fill=GOLD + (255,))

    return img.resize((size, size), Image.LANCZOS)


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(out_dir, "szu_grab.ico")
    frames = [render(size) for size in SIZES]

    # 256 那张当底图，其余尺寸用 append_images 塞进同一个 ico
    base = frames[-1]
    try:
        base.save(ico_path, format="ICO",
                  sizes=[(s, s) for s in SIZES],
                  append_images=frames[:-1])
    except TypeError:
        base.save(ico_path, format="ICO", sizes=[(s, s) for s in SIZES])

    # 再导一张 PNG：万一 ico 在某个系统上加载不了，
    # 程序还能用 iconphoto + 这张 PNG 顶上，不至于退回 Tk 的默认羽毛图标
    render(256).save(os.path.join(out_dir, "szu_grab.png"))

    # 顺便导一张放大预览，方便肉眼检查
    preview = Image.new("RGBA", (560, 180), (245, 245, 245, 255))
    x = 20
    for size in (16, 32, 64, 128):
        art = render(size)
        preview.paste(art, (x, 20 + (128 - size) // 2), art)
        x += size + 26
    preview.save(os.path.join(out_dir, "_icon_preview.png"))

    print("已生成 %s（含 %s 像素）" % (ico_path, "、".join(str(s) for s in SIZES)))
    print("已生成 szu_grab.png（备用窗口图标）")
    print("预览图 _icon_preview.png")


if __name__ == "__main__":
    main()
