"""道具动作到底有没有把东西摆出来 —— 看像素，别只看参数。

她从来不静止（呼吸 3.234 秒一个正弦 + 物理演算 + 自动眨眼），单帧相减全是噪声。
所以每个阶段连抓 8 帧取平均，再比平均图。图也留下来自己看。
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

def avg(n=8):
    """连抓 n 帧取平均，把呼吸/眨眼/物理的摆动平均掉。"""
    acc = None
    for _ in range(n):
        pump(0.05)
        img = w.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        ptr = img.constBits(); ptr.setsize(img.byteCount())
        a = np.frombuffer(bytes(ptr), np.uint8).reshape(img.height(), img.width(), 4).astype(np.float32)
        acc = a if acc is None else acc + a
    return acc / n

def pv(name):
    i = w.idx[name]
    return round(w.mdl.GetParameterValue(i), 3)

# kind 必须照 modelmap 推，不能手写 —— 手机换色是**表情**，写成 motion 会被
# run_steps 过滤掉，只剩前置的开盖在演，看着像"换了色没生效"。（踩过。）
CASES = [
    ("番茄酱",   "danbaofan", 2.5),
    ("手机换色", "shouji",    1.6),
    ("魔爪换色", "mozhua2",   0.6),
]

for label, probe, at in CASES:
    kind = "expr" if label in M.EXPR_ID else "motion"
    w.fire({"kind": "reset"}); pump(0.6)
    before = avg()
    pump(0.6)
    before2 = avg()                # 空转一段再抓一次，量出"她自己在动"的噪声底
    w.play_action(kind, label)
    pump(at)                       # 进到正片里
    during = avg()
    probe_v = pv(probe)
    pump(P.PROP_EXPR_HOLD_SEC + M.MOTION_SEC.get(label, 0) + 1.2)
    after = avg()

    def diff(a, b):
        return float(np.abs(a - b).mean())

    d_during = diff(before, during)
    d_after = diff(before, after)
    d_noise = diff(before, before2)
    print("%-6s 噪声底 %.2f | 演的时候 %.2f | 收完 %.2f | %s=%s"
          % (label, d_noise, d_during, d_after, probe, probe_v))
    if d_after > max(d_noise * 1.5, d_noise + 1.0):
        print("   ★收完和之前差得比噪声大 —— 有东西没收回")

    # 拼三格图：之前 / 演的时候 / 收完
    h, wd = before.shape[:2]
    out = QImage(wd * 3, h, QImage.Format_RGBA8888)
    out.fill(0)
    p = QPainter(out)
    for n, (arr, tag) in enumerate(((before, "before"), (during, "DURING"),
                                    (after, "after"))):
        a = np.clip(arr, 0, 255).astype(np.uint8).copy()
        im = QImage(a.tobytes(), wd, h, QImage.Format_RGBA8888).copy()
        p.drawImage(n * wd, 0, im)
        p.setPen(Qt.red)
        p.drawText(n * wd + 6, 16, tag)
    p.end()
    out.save("_prop_%s.png" % label)
    print("    -> _prop_%s.png" % label)

w.fire({"kind": "reset"})
print("\n完成")
