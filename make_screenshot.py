"""给 README 生成一张截图：把她渲染在右下角，垫一层素净的桌面底。

不是屏幕截图 —— 是拿真模型现渲染的，所以图里是她真实的样子（真表情、真呼吸、
真的跟着 QCursor 转过来的头）。底图是画出来的渐变，不冒充别人的桌面。
"""
import io, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import numpy as np
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import (QSurfaceFormat, QCursor, QImage, QPainter,
                         QLinearGradient, QColor, QFont)
from PyQt5.QtWidgets import QApplication

fmt = QSurfaceFormat(); fmt.setAlphaBufferSize(8); QSurfaceFormat.setDefaultFormat(fmt)
import live2d.v3 as live2d
live2d.init()
import pet as P

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "screenshot.png")

W, H = 1200, 640          # 成品尺寸
SIDE = 460                # 她在图里多大 —— 比真身的 320 大一点，缩略图里看得清
MARGIN = 22               # 离右下角的边距，和程序默认的贴边感觉一致

app = QApplication(sys.argv)
pet = P.Pet(P.load_config())
pet.resize(SIDE, SIDE)
pet.show()
for _ in range(500):
    app.processEvents()
    if pet.model is not None:
        break
    time.sleep(0.02)
if pet.model is None:
    raise SystemExit("模型没加载起来")

pet.idle_timer.stop(); pet.hotkey_timer.stop()

# 光标放左上角，让她朝这边看 —— 正面直立的大头照不好看，也显不出跟随。
QCursor.setPos(0, 0)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.004)


# 挂一个表情，让图里有点神采。星星眼见 _test_prop_visual.py 同样的用法。
pet.set_expr("星星眼", True)
pump(1.6)                 # 等淡入走完（实测 1.05 秒）


def avg(n=10):
    """连抓 n 帧取平均 —— 她一直在呼吸/眨眼/物理摆动，单帧会糊。"""
    acc = None
    for _ in range(n):
        pump(0.05)
        img = pet.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        ptr = img.constBits(); ptr.setsize(img.byteCount())
        a = np.frombuffer(bytes(ptr), np.uint8).reshape(
            img.height(), img.width(), 4).astype(np.float32)
        acc = a if acc is None else acc + a
    return np.clip(acc / n, 0, 255).astype(np.uint8)


# 平均会把眨眼平均成"半闭眼"，所以取平均之后单独补一帧睁眼的：用平均图定形，
# 但把眼睛那一块换成某一帧真睁开的。简单起见，直接挑一张眼睛睁得最开的单帧。
best, best_v = None, -1
for _ in range(14):
    pump(0.06)
    img = pet.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
    ptr = img.constBits(); ptr.setsize(img.byteCount())
    a = np.frombuffer(bytes(ptr), np.uint8).reshape(
        img.height(), img.width(), 4)
    # 眼睛在窗口偏上那一片；alpha 总量越大说明睁得越开、头发物理也越稳
    v = int(a[:int(SIDE * 0.55), :, 3].sum())
    if v > best_v:
        best_v, best = v, a.copy()
figure = best

canvas = QImage(W, H, QImage.Format_RGB32)
p = QPainter(canvas)
p.setRenderHint(QPainter.SmoothPixmapTransform)

# 底图：斜向上的浅灰蓝渐变，模仿一张素色壁纸。四角压暗一点，免得平。
g = QLinearGradient(0, 0, W, H)
g.setColorAt(0.0, QColor(238, 242, 247))
g.setColorAt(1.0, QColor(206, 216, 228))
p.fillRect(0, 0, W, H, g)

she = QImage(figure.tobytes(), figure.shape[1], figure.shape[0],
             QImage.Format_RGBA8888).copy()
x, y = W - SIDE - MARGIN, H - SIDE - MARGIN
p.drawImage(x, y, she)

# 左下角一点淡淡的说明，免得看图的人不知道这张图想说什么。字压在那片空白上，
# 所以先垫一层半透明白。框宽按文字实际宽度算 —— 写死宽度会截断（踩过）。
NOTE = "DS鲸鱼娘桌宠 · 320×320 · 贴右下角 · 置顶透明"
p.setFont(QFont("Microsoft YaHei UI", 13))
tw = p.fontMetrics().horizontalAdvance(NOTE)
pad = 16
box = QRectF(28, H - 46 - pad, tw + pad * 2, 46)
p.setPen(Qt.NoPen)
p.setBrush(QColor(255, 255, 255, 190))
p.drawRoundedRect(box, 8, 8)
p.setBrush(Qt.NoBrush)
p.setPen(QColor(60, 70, 85))
p.drawText(box, Qt.AlignCenter, NOTE)
p.end()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
canvas.save(OUT)
print("wrote", OUT, canvas.width(), "x", canvas.height())
