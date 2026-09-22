"""把「带道具的动作」整条线回归一遍。

判据只有一个：演完 + 收回淡出之后，这套动作驱动过的东西是不是**一个不剩地**回到
默认值 —— 参数（动作的、道具表情的）和 active_expr 两边都得干净。这是「动作演完
卡住」那个 bug 的原始症状，回归就得盯死它。

第三节是这轮新加的雷：纯表情的道具组合（魔爪换色 = 魔爪 + 魔爪换色）**不能**
去动 motion_token，也不能 StopAllMotions。它要是不小心清了场，正播着的动作排好的
那次收回就作废了，泡泡的嘴会永远卡在脸上 —— 第八轮修的就是那个。
"""
import io
import json
import os
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
w.idle_timer.stop()               # 待机会自己蹦动作，闯进来就说不清了
w.hotkey_timer.stop()
QCursor.setPos(60, 60)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


# 表情文件里的参数表 —— modelmap 没有 EXPR_PARAMS，测试自己从 exp3 里读。
# （程序本身不需要这张表：摘掉表情时 Cubism 的表情管理器会自己在下一帧把
#   上一帧的贡献减回去，用不着我们记账。）
def expr_params(label):
    eid = M.EXPR_ID.get(label)
    if eid is None:
        return {}
    path = os.path.join("modeldata", "exp", "%s.exp3.json" % eid)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return {p["Id"]: p.get("Value", 0.0) for p in doc.get("Parameters", [])}


def motion_params(label):
    """动作驱动过哪些参数 —— 从 motion3.json 的 Curves 里读，**不是**读
    M.MOTION_PARAMS。

    这一点是必须的：MOTION_PARAMS 是要被检验的东西，拿它当检验标准就是自己查
    自己。原先的写法就是那样，于是 aidale 的表漏了 Param74~77（星轨迹/锤子旋转/
    锤子X/兔兔耳朵）时，扫的名单也跟着漏 —— 四个参数明明停在最后一帧，测试报
    "干净"。现在两边独立：表错了，这里立刻看得见。"""
    g, i = M.MOTION[label]
    fname = ("motion/motion_idle.motion3.json" if g == "Idle"
             else "motion/motion_%02d.motion3.json" % i)
    path = os.path.join("modeldata", fname)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return sorted({c["Id"] for c in doc["Curves"]})


# 每帧都被别的子系统覆盖、因而"残留"没有意义的参数，和 begin_retract 里跳过的是
# 同一类，只是多了一个自动眨眼：
#   · FOLLOW_NAMES / ParamBreath —— 鼠标跟随和呼吸每帧都写
#   · PHYSICS_OUT —— 物理演算在 Update() 的最后一步写
#   · ParamEyeLOpen/ROpen —— **自动眨眼**（默认开着）每帧都写。这个是实测出来的：
#     番茄酱演完单点采样读到 -0.788，看着像卡在闭眼上，连采 6 秒才发现它在
#     -1.000 ~ 0.000 之间来回摆（0 是睁开、-1 是闭紧），102/114 个采样都贴在默认上
#     —— 就是正好眨到一半被抓到了。她不光在呼吸，还在眨眼，两个振荡器都不归我们管。
SKIP = set(P.FOLLOW_NAMES) | set(M.PHYSICS_OUT) | {"ParamBreath",
                                                   "ParamEyeLOpen",
                                                   "ParamEyeROpen"}


def leftovers(steps):
    """这一步串驱动过、现在还偏着的参数。"""
    out = {}
    names = []
    for kind, lab in steps:
        names += motion_params(lab) if kind == "motion" else list(expr_params(lab))
    for n in names:
        if n in SKIP:
            continue
        i = w.idx.get(n)
        if i is None:
            continue
        d = w.mdl.GetParameterValue(i) - w.mdl.GetParameterDefaultValue(i)
        if abs(d) > 1e-3:
            out[n] = round(d, 4)
    return out


def hold(steps):
    """照着 run_steps 的算法算这一串演多久，别写死。"""
    at = 0.0
    last = len(steps) - 1
    for n, (kind, lab) in enumerate(steps):
        if kind == "motion":
            at += M.MOTION_SEC.get(lab, 3.0)
        elif n < last:
            at += 0.0
        else:
            at += P.PROP_EXPR_HOLD_SEC
    return at


# 期望的标签不能写死 —— PROP_LEAD 会自己多排前置，照它推，以后往里加道具动作，
# 这张表不用跟着改。
CASES = []
for _l in M.MOTION:
    if _l != "idle":
        CASES.append((_l, P.PROP_LEAD.get(_l, []) + [("motion", _l)]))
for _l in P.PROP_LEAD:                    # 手机换色 / 魔爪换色 这两条是表情
    if _l in M.EXPR_ID:
        CASES.append((_l, P.PROP_LEAD[_l] + [("expr", _l)]))

# ---- 第零节：左键单击那个池子 ----
# 池子 = 所有表情 + 所有非 idle 动作，减去 RANDOM_EXCLUDE。带道具的现在都能自己
# 把道具弄出来，所以全在池子里 —— 除了 `开盖`：它只是别条的前置，单抽出来是
# 一秒没下文的掏手机，自己不进池子（手动点菜单照样能播）。
pool = [("expr", l) for l in M.EXPR_ID if l not in P.RANDOM_EXCLUDE]
pool += [("motion", l) for l in M.MOTION
         if l != "idle" and l not in P.RANDOM_EXCLUDE]
pool_names = [l for _k, l in pool]
print("随机池 %d 条（表情 %d + 动作 %d）"
      % (len(pool), sum(1 for k, _ in pool if k == "expr"),
         sum(1 for k, _ in pool if k == "motion")))
for want in ("自拍", "自拍简单", "番茄酱", "手机换色", "魔爪换色"):
    print("  %-6s 在池子里：%-5s  抽到会先演 %s"
          % (want, want in pool_names, P.PROP_LEAD.get(want)))
print("  开盖 在池子里：%s（只当前置，不进池子）" % ("开盖" in pool_names))
print()

bad = []
print("%-8s %-22s %-7s %s" % ("点了", "实际排上", "总时长", "收回后残留"))
print("-" * 68)
for label, steps in CASES:
    w.fire({"kind": "reset"})
    pump(0.4)
    kind = "expr" if label in M.EXPR_ID else "motion"
    w.play_action(kind, label)
    total = hold(steps)
    want_m = [l for k, l in steps if k == "motion"]
    assert w.motion_labels == want_m, (label, w.motion_labels, want_m)
    pump(total + P.RETRACT_FADE_SEC + 0.6)
    left = leftovers(steps)
    stuck = [l for k, l in steps if k == "expr" and l in w.active_expr]
    if left or w.retract is not None or w.seq_exprs or stuck:
        bad.append((label, left, stuck))
    print("%-8s %-22s %5.2fs  %s%s"
          % (label, "+".join("%s:%s" % (k[0], l) for k, l in steps), total,
             left if left else "干净",
             "  残留表情 %s" % stuck if stuck else ""))

# ---- 第三节：正播着动作时插一条纯表情的道具组合 ----
# 它不该打断那个动作，更不该让那个动作的收回作废。
w.fire({"kind": "reset"})
pump(0.4)
print()
print("正播「吹泡泡」时插一条「魔爪换色」（纯表情，不该碰动作那条线）：")
w.play_motion("chuipaopao")
pump(1.2)
tok_before = w.motion_token
w.play_action("expr", "魔爪换色")
print("  motion_token 变了没：%s（必须是 False）"
      % (w.motion_token != tok_before))
w_motion_ok = w.motion_token == tok_before
# 魔爪换色的两段都在 at=0，立刻挂上；3 秒后自己摘掉
pump(P.PROP_EXPR_HOLD_SEC + 0.5)
expr_ok = not ({"魔爪", "魔爪换色"} & w.active_expr)
print("  魔爪 / 魔爪换色 3 秒后自己摘掉：%s" % expr_ok)
# 吹泡泡 4.77 秒，收回排在它演完那一刻
pump(M.MOTION_SEC["chuipaopao"] + P.RETRACT_FADE_SEC + 0.6)
left = leftovers([("motion", "chuipaopao")])
bubble_ok = not left and w.retract is None
print("  吹泡泡照常收回、没被顶掉：%s %s" % (bubble_ok, left or ""))

if not (w_motion_ok and expr_ok and bubble_ok):
    bad.append(("魔爪换色插播", {"token": w_motion_ok, "expr": expr_ok,
                                 "bubble": bubble_ok}))

# ---- 第四节：待机自己抽到这三条 ----
# 待机另有一套"我加上去的 / 我顶掉的"账（idle_action + idle_restore），和序列的
# 收回是两拨人，撞一起就容易互相拆台。抽签固定成要测的那条，别的照真流程走。
print()
print("待机自己抽到道具动作（抽签固定，其余走真流程）：")
w.fire({"kind": "reset"})
pump(0.4)
for label in ("番茄酱", "手机换色", "魔爪换色"):
    kind = "expr" if label in M.EXPR_ID else "motion"
    w.fire({"kind": "reset"})
    pump(0.4)
    w.idle_token += 1                      # 把上一轮排的 idle_restore 作废
    w.pick_random = lambda k=kind, l=label: (k, l)
    w.idle_action()
    # 序列自己的收回 + 待机的 IDLE_HOLD_MS 都得跑完，看它们会不会打架
    pump(max(hold(P.PROP_LEAD[label] + [(kind, label)]),
             P.IDLE_HOLD_MS / 1000.0) + P.RETRACT_FADE_SEC + 0.8)
    left = leftovers(P.PROP_LEAD[label] + [(kind, label)])
    stuck = [l for l in w.active_expr]
    ok = not left and not stuck and w.retract is None and not w.seq_exprs
    if not ok:
        bad.append(("待机 " + label, left, stuck))
    print("  %-8s 残留参数 %-4s 还挂着的表情 %-6s %s"
          % (label, left or "无", stuck or "无", "干净" if ok else "★有问题"))
del w.pick_random

w.fire({"kind": "reset"})
pump(0.3)
print()
print("结论：", "全部干净" if not bad else "有问题 -> %s" % bad)
sys.exit(1 if bad else 0)
