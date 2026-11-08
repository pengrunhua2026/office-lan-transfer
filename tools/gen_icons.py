# -*- coding: utf-8 -*-
"""
生成局域网办公文件传输系统程序图标（.ico）
==========================================
用 Pillow 绘制简洁的扁平化图标，输出包含多种尺寸的 .ico 文件：
  - 合并程序：蓝色圆角方块 + 白色文件 + 双向传输箭头（文件收发）

【设计思路】
  1. 为什么用代码绘制图标而非外部设计工具？
     图标随项目一起用代码维护，可随时重新生成、可版本化，无需依赖第三方素材。
  2. 为什么画布 1024x1024 再缩放？
     先在 1024 高分辨率画布上绘制，再缩放到多尺寸（16~256）写入 .ico，
     可保证小尺寸下边缘平滑、不失真。
  3. 图形寓意：
     中央白色"文件"（带横线模拟文字）+ 左右双向箭头 = 文件双向收发，
     蓝色为程序主色，风格统一。

运行方式（在项目根目录下）：
  python tools/gen_icons.py
输出到 build_assets/ 目录。
"""
import os
from PIL import Image, ImageDraw

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "build_assets")
os.makedirs(OUT_DIR, exist_ok=True)

# 需要写入 .ico 的尺寸
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# 画布尺寸（高分辨率绘制后缩放，保证边缘平滑）
CANVAS = 1024


def rounded_bg(draw, color, radius=240):
    """绘制圆角方块背景（从边距 64 到 960，即 1024 画布的 896 见方）。"""
    m = 64
    draw.rounded_rectangle([m, m, CANVAS - m, CANVAS - m], radius=radius, fill=color)


def arrow(draw, x, y, s, color, direction=1):
    """绘制一条水平箭头（direction=1 向右，-1 向左）。"""
    shaft = s * 0.5
    width = int(s * 0.18)
    if direction > 0:
        draw.line([(x - shaft, y), (x + shaft * 0.6, y)], fill=color, width=width)
        draw.polygon([(x + shaft, y), (x + shaft * 0.5, y - s * 0.28),
                      (x + shaft * 0.5, y + s * 0.28)], fill=color)
    else:
        draw.line([(x - shaft * 0.6, y), (x + shaft, y)], fill=color, width=width)
        draw.polygon([(x - shaft, y), (x - shaft * 0.5, y - s * 0.28),
                      (x - shaft * 0.5, y + s * 0.28)], fill=color)


def transfer_icon(draw, cx, cy, scale):
    """绘制"文件收发"主体：中央白色文件 + 左右双向箭头。"""
    s = scale
    w, h = 1.1 * s, 1.4 * s
    left, top = cx - w / 2, cy - h / 2
    draw.rounded_rectangle([left, top, left + w, top + h], radius=0.12 * s, fill="white")
    for i in range(3):
        y = top + h * 0.2 + i * h * 0.16
        draw.rounded_rectangle([left + w * 0.16, y, left + w * 0.16 + w * 0.68, y + h * 0.07],
                               radius=h * 0.03, fill=(60, 90, 128))
    # 左侧向右箭头（接收）、右侧向左箭头（发送）
    arrow(draw, left - s * 0.18, cy, s * 0.4, "white", direction=1)
    arrow(draw, left + w + s * 0.18, cy, s * 0.4, "white", direction=-1)


def make_icon(primary_bg):
    """
    在 CANVAS x CANVAS 画布上绘制图标主体，返回 RGBA 图像。
    居中偏下的文件 + 双向箭头，代表文件收发。

    【设计思路】
    - 透明背景 + 圆角方块底色 + 中央文件主体：
      rounded_bg 画底色，transfer_icon 画文件与箭头。
    - 返回 RGBA 图像，便于 save_ico 缩放并保存为多尺寸 .ico。
    """
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rounded_bg(d, primary_bg)
    transfer_icon(d, CANVAS / 2, CANVAS * 0.5, CANVAS * 0.26)
    return img


def save_ico(img, path):
    """把高分辨率图像缩放到多个尺寸并保存为 .ico。"""
    img.save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])


def main():
    # 合并程序：蓝色 + 文件双向传输箭头
    combined_img = make_icon("#2563EB")
    combined_path = os.path.join(OUT_DIR, "combined.ico")
    save_ico(combined_img, combined_path)
    print("已生成图标：")
    print(" ", combined_path)


if __name__ == "__main__":
    main()
