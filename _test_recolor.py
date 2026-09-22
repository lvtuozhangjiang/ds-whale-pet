"""换色到底换没换 —— 同一个道具，挂着换色表情和没挂，颜色一样吗？

她一直在动，所以每个状态连抓 12 帧取平均再看。
"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np
from PyQt5.QtGui import QSurfaceFormat, QCursor, QImage, QPainter
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
fmt = QSurfaceFormat(); fmt.setAlphaBufferSize(8); QSurfaceFormat.setDefaultFormat(fmt)
import live2d.v3 as live2d
live2d.init()
import modelmap as M, pet as P

app = QApplication(sys.argv)
w = P.Pet(P.load_config()); w.resize(320, 320); w.show()
for _ in range(400):
    app.processEvents()
    if w.model is not None: break
    time.sleep(0.02)
w.idle_timer.stop(); w.hotkey_timer.stop(); QCursor.setPos(60, 60)

def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.004)

def avg(n=12):
    acc = None
    for _ in range(n):
        pump(0.04)
        img = w.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        ptr = img.constBits(); ptr.setsize(img.byteCount())
        a = np.frombuffer(bytes(ptr), np.uint8).reshape(img.height(), img.width(), 4).astype(np.float32)
        acc = a if acc is None else acc + a
    return acc / n

def shot(prop_motion, recolor, tag):
    """把道具摆出来，可选叠一层换色，然后平均取图。"""
    w.fire({"kind": "reset"}); pump(0.8)
    w.apply_step("motion", prop_motion)       # 只摆道具，不走序列
    if recolor:
        w.apply_step("expr", recolor)
    pump(1.0)
    return avg()

panels = [
    ("手机", "开盖", "手机换色"),
    ("魔爪", None,   "魔爪换色"),
]
rows = []
for name, prop, recolor in panels:
    plain = shot(prop, None, name + " 原色") if prop else None
    if prop is None:
        w.fire({"kind": "reset"}); pump(0.8)
        w.apply_step("expr", "魔爪"); pump(1.0)
        plain = avg()
    tinted = shot(prop, recolor, name + " 换色") if prop else None
    if prop is None:
        w.fire({"kind": "reset"}); pump(0.8)
        w.apply_step("expr", "魔爪"); w.apply_step("expr", recolor); pump(1.0)
        tinted = avg()
    d = np.abs(plain - tinted)
    # 只看有明显变化的像素，全局平均会被大片没动的地方稀释掉
    hot = (d.max(axis=2) > 24)
    print("%-4s 原色 vs 换色：全局平均 %.2f，明显不同的像素 %d 个（占 %.2f%%）"
          % (name, d.mean(), hot.sum(), 100.0 * hot.sum() / hot.size))
    rows.append((name, plain, tinted))

h, wd = rows[0][1].shape[:2]
out = QImage(wd * 4, h, QImage.Format_RGBA8888); out.fill(0)
p = QPainter(out)
n = 0
for name, plain, tinted in rows:
    for arr, tag in ((plain, name + " 原色"), (tinted, name + " 换色")):
        a = np.clip(arr, 0, 255).astype(np.uint8).copy()
        p.drawImage(n * wd, 0, QImage(a.tobytes(), wd, h, QImage.Format_RGBA8888).copy())
        p.setPen(Qt.red); p.drawText(n * wd + 6, 16, tag)
        n += 1
p.end(); out.save("_recolor.png")
print("-> _recolor.png")
