"""不运行 exe，直接拆开看它到底装了什么。

用户开着桌宠时（互斥体 + 文件占用都不允许起第二个实例）这是唯一能做的验证。
也可以用来确认某个补丁真的进了包。用法：python _verify_bundle.py [exe路径]
"""
import marshal
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

EXE = sys.argv[1] if len(sys.argv) > 1 else r"D:\桌宠\pet\dist\DS鲸鱼娘桌宠-单文件.exe"

# 源码里的函数名/表名会原样进 code 对象的 co_names，用它确认补丁在不在包里。
MARKS = {
    "pet": ("begin_retract", "step_retract", "retract_motion", "drop_exprs",
            "clear_pose", "clamp_to_screen", "reachable", "screen_for",
            "play_action", "run_steps", "apply_step", "set_expr",
            "PROP_LEAD", "PROP_EXPR_HOLD_SEC", "seq_exprs",
            "motion_labels", "MOTION_SEC", "PHYSICS_OUT"),
    "modelmap": ("MOTION_SEC", "PHYSICS_OUT", "MOTION_PARAMS"),
}
FAIL = []


def strings_in(code, acc):
    """递归扒出 code 对象里所有的名字和字符串常量。"""
    acc.update(code.co_names)
    for c in code.co_consts:
        if isinstance(c, str):
            acc.add(c)
        elif hasattr(c, "co_names"):
            strings_in(c, acc)
    return acc


def check(label, code):
    marks = MARKS[label]
    got = strings_in(code, set())
    missing = [m for m in marks if m not in got]
    print("  %-10s 标记 %d/%d %s"
          % (label, len(marks) - len(missing), len(marks),
             "全在" if not missing else "缺 -> %s" % missing))
    if missing:
        FAIL.append("%s 缺 %s" % (label, missing))


def path_in(names, want):
    return next((n for n in names if n.replace("/", os.sep) == want), None)


r = CArchiveReader(EXE)
names = list(r.toc)
print("%s\n共 %d 个条目" % (os.path.basename(EXE), len(names)))

# ---- 数据文件 ----
for want, label, verify in (
        (os.path.join("modeldata", "motion", "motion_01.motion3.json"), "动作文件",
         lambda b: '"Loop": false' in b.decode("utf-8")),
        (os.path.join("modeldata", "c_0120.2048", "texture_00.png"), "贴图",
         lambda b: len(b) == 1751018),
):
    key = path_in(names, want)
    if key is None:
        print("  %s 没找到（找的是 %s）" % (label, want))
        FAIL.append(label)
        continue
    data = r.extract(key)
    ok = data is not None and verify(data)
    print("  %-8s %d 字节 -> %s" % (label, len(data or b""), ok))
    if not ok:
        FAIL.append(label)

# ---- 代码 ----
# 入口脚本不在 PYZ 里：PyInstaller 按 PYSOURCE 直接塞进 CArchive 的 `pet` 条目，
# extract() 给的是 marshal 字节，marshal.loads 才出 code 对象。
# toc 的值是 (偏移, 压缩长, 原始长, flag, 类型码)，类型码在最后一位。
src = next((n for n in names
            if r.toc[n][4] in ("s", "m")
            and os.path.basename(n).split(".")[0] in ("pet", "__main__")), None)
if src is None:
    print("  CArchive 里没找到入口脚本，候选：",
          [n for n in names if r.toc[n][4] in ("s", "m")][:10])
    FAIL.append("入口脚本")
else:
    check("pet", marshal.loads(r.extract(src)))

# PYZ 得先落到本地文件再交给 ZlibArchiveReader（喂 BytesIO 会报 no attribute 'rfind'）
pyzpath = os.path.join(tempfile.gettempdir(), "_verify_bundle.pyz")
with open(pyzpath, "wb") as fh:
    fh.write(r.extract(next(n for n in names if n.endswith(".pyz"))))
z = ZlibArchiveReader(pyzpath)
for name in ("modelmap",):
    if name in z.toc:
        check(name, z.extract(name))      # PYZ 条目直接给 code 对象，不是 bytes
    else:
        print("  %s 不在 PYZ 里" % name)
        FAIL.append(name)

# ---- 表的内容，不只是名字在不在 ----
# 名字全在也可能装着一张错的表：MOTION_PARAMS['aidale'] 少列 Param74~77 那回，
# 名字一个不少，但重锤出击演完有四个参数停在最后一帧。所以表本身也量一下。
# PYZ 条目给的是 code 对象，exec 一遍就能把模块里的表读出来（不需要 live2d）。
if "modelmap" in z.toc:
    ns = {}
    exec(z.extract("modelmap"), ns)
    aidale = ns.get("MOTION_PARAMS", {}).get("aidale", [])
    want = {"Param74", "Param75", "Param76", "Param77"}
    ok = want <= set(aidale)
    print("  %-8s aidale 驱动参数 %d 个，含 Param74~77 -> %s"
          % ("表内容", len(aidale), ok))
    if not ok:
        FAIL.append("aidale 参数表不全（缺 %s）" % sorted(want - set(aidale)))

print()
print("结论：", "全部通过" if not FAIL else "有问题 -> %s" % FAIL)
sys.exit(1 if FAIL else 0)
