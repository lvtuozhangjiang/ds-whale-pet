# 把模型的 icon.png 转成多尺寸 .ico，供 EXE 图标使用。
#
# 模型的 icon.png 是方形且带透明通道，直接缩放即可。
# 运行：python make_icon.py

import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "modeldata", "icon.png")
DST = os.path.join(HERE, "icon.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    img = Image.open(SRC).convert("RGBA")
    # 非正方形时先居中裁成正方形，避免 ICO 里被拉变形
    if img.width != img.height:
        s = min(img.width, img.height)
        img = img.crop(((img.width - s) // 2, (img.height - s) // 2,
                        (img.width + s) // 2, (img.height + s) // 2))
    img.save(DST, format="ICO", sizes=SIZES)
    print("wrote %s (%dx%d -> %d sizes, %d bytes)"
          % (DST, img.width, img.height, len(SIZES), os.path.getsize(DST)))


if __name__ == "__main__":
    sys.exit(main())
