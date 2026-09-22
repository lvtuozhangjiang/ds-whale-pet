"""演完一条动作，把**模型自己的全部 247 个参数**前后比一遍，看哪些没回去。

和 _test_retract_sweep.py 的区别，也是它存在的理由：
    那份测试查的参数名单，原先是从 M.MOTION_PARAMS 推的 —— 而 MOTION_PARAMS 正是
    要被检验的东西。表漏了参数，名单跟着漏，于是 aidale 少列了 Param74~77
    （星轨迹 / 锤子旋转 / 锤子X / 兔兔耳朵），四个参数实打实停在最后一帧，测试却
    报"干净"。自己查自己。
    这份不读任何表，参数全集直接从模型拿（pet 建好的 w.idx），谁驱动的不重要，
    演完偏着的都得挑出来。

代价是它比较慢（每条动作要连采 18 帧来压掉呼吸/眨眼的相位），所以只跑动作，
表情那部分交给 sweep。用法：

    python _test_param_residue.py              跑全部 7 条一次性动作
    python _test_param_residue.py aidale       只跑一条
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PyQt5.QtGui import QSurfaceFormat, QCursor
from PyQt5.QtWidgets import QApplication

fmt = QSurfaceFormat()
fmt.setAlphaBufferSize(8)
QSurfaceFormat.setDefaultFormat(fmt)

import live2d.v3 as live2d

live2d.init()

import modelmap as M
import pet as P

app = QApplication(sys.argv)
w = P.Pet(P.load_config())
w.resize(320, 320)
w.show()
for _ in range(400):
    app.processEvents()
    if w.model is not None:
        break
    time.sleep(0.02)
w.idle_timer.stop()
w.hotkey_timer.stop()
QCursor.setPos(60, 60)

# 每帧都被别的子系统写的参数 —— 它们"偏着"是正常的，不是残留。和 begin_retract
# 里跳过的那几类一致，外加自动眨眼（默认开着，每帧写 ParamEyeLOpen/ROpen）。
SKIP = set(P.FOLLOW_NAMES) | set(M.PHYSICS_OUT) | {"ParamBreath",
                                                   "ParamEyeLOpen",
                                                   "ParamEyeROpen"}
ALL = sorted(w.idx)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


def snap():
    """连采 18 帧，每个参数取"离默认值最远"的那次。

    她从来不停：呼吸是 3.234 秒一个正弦，眨眼随机，物理一直在晃。单帧采样会正好
    抓到眨眼抓到一半（ParamEyeLOpen = -0.788 那次就是这么来的）。取最偏值是为了
    让"本来就在摆"的参数在两轮里量到差不多的幅度，免得把振荡当成残留。"""
    best = {}
    for _ in range(18):
        pump(0.05)
        for n in ALL:
            i = w.idx[n]
            d = w.mdl.GetParameterValue(i) - w.mdl.GetParameterDefaultValue(i)
            if n not in best or abs(d) > abs(best[n]):
                best[n] = d
    return best


labels = sys.argv[1:] or [l for l in M.MOTION if l != "idle"]
bad = []

for label in labels:
    w.fire({"kind": "reset"})
    pump(1.2)
    base = snap()
    w.play_action("motion", label)
    pump(M.MOTION_SEC[label] + P.RETRACT_FADE_SEC + 2.0)
    after = snap()

    stuck = []
    for n in ALL:
        if n in SKIP:
            continue
        d0, d1 = base[n], after[n]
        # 收回后还明显偏着，而且比演之前更偏 —— 演之前就偏的是别的东西写的
        if abs(d1) > 1e-3 and abs(d1) > abs(d0) + 1e-3:
            stuck.append((n, d0, d1))

    in_table = set(M.MOTION_PARAMS.get(label, ()))
    miss = [n for n, _a, _b in stuck if n not in in_table]
    print("%-10s %5.3fs  残留 %d 个%s"
          % (label, M.MOTION_SEC[label], len(stuck),
             "   ★ 不在 MOTION_PARAMS 里：" + ", ".join(miss) if miss else ""))
    for n, d0, d1 in stuck:
        print("             %-34s 演前 %+.3f -> 收完 %+.3f" % (n, d0, d1))
    if stuck:
        bad.append(label)

print()
print("结论：", "全部干净" if not bad else "有残留 -> %s" % bad)
sys.exit(1 if bad else 0)
