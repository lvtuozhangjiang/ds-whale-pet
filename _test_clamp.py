"""验 place() 的钳制：config 里的 pos 不管多离谱，窗口都得落在看得见的地方。

纯几何，不用起 GL —— Pet.__init__ 里不碰模型，place() 只调 setGeometry。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

import pet as P
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
g = QApplication.primaryScreen().availableGeometry()
print("可用区（已有任务栏的那块屏）：(%d,%d)-(%d,%d)  %dx%d"
      % (g.left(), g.top(), g.right(), g.bottom(), g.width(), g.height()))
print()

SIDE = P.side_for_area_div(9)
print("窗口边长（area_div=9）：%d" % SIDE)
print()

CASES = [
    ("正常（右下角内）", [g.left() + 100, g.top() + 100]),
    ("右边超出去", [g.right() + 500, g.top() + 100]),
    ("右下都超出去", [g.right() + 500, g.bottom() + 500]),
    ("左上角负数", [-800, -600]),
    ("完全在屏幕外", [g.right() + 2000, g.bottom() + 1500]),
    ("贴着右下边缘", [g.right() - SIDE, g.bottom() - SIDE]),
]

bad = []
for label, pos in CASES:
    cfg = {"pos": list(pos), "area_div": 9}
    p = P.Pet(cfg)
    p.size_px = SIDE
    p.place()
    geo = p.geometry()
    inside = g.contains(geo)
    if not inside:
        bad.append(label)
    print("%-14s 存的是 (%5d,%5d) -> 落在 (%5d,%5d)-(%5d,%5d)  %s"
          % (label, pos[0], pos[1], geo.left(), geo.top(),
             geo.right(), geo.bottom(), "在可视区内" if inside else "★还是在外面"))

# 没有 pos 的老配置：应该走右下角默认位置，行为不变
cfg = {"area_div": 9}
p = P.Pet(cfg)
p.size_px = SIDE
p.place()
geo = p.geometry()
dx, dy = p.default_pos()
ok = (geo.left(), geo.top()) == (int(dx), int(dy))
print()
print("%-14s -> 落在 (%5d,%5d)  和 default_pos 一致：%s"
      % ("config 里没有 pos", geo.left(), geo.top(), ok))
if not ok:
    bad.append("没有 pos")

print()
print("--- 拖动松手时的判定：露一点算数，整个出去才算丢 ---")
p = P.Pet({"area_div": 9})
p.size_px = SIDE
REACH = [
    ("整个在屏幕外", g.right() + 200, 300, False),
    ("只露出 1 像素", g.right() - 1, 300, True),
    ("露半个身子在右边", g.right() - SIDE // 2, 300, True),
    ("在下面露一点", 300, g.bottom() - 1, True),
    ("整个在下面", 300, g.bottom() + 200, False),
    ("正常位置", 300, 300, True),
]
for label, x, y, want in REACH:
    got = p.reachable(x, y)
    ok = got == want
    if not ok:
        bad.append("reachable " + label)
    print("%-18s (%5d,%5d)  期望 %-5s 实得 %-5s %s"
          % (label, x, y, want, got, "" if ok else "★"))

print()
print("结论：", "全部通过" if not bad else "有问题 -> %s" % bad)
sys.exit(1 if bad else 0)
