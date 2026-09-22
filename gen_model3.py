# Build `modeldata/` from the source model, and generate a model3.json that
# actually declares the motions and expressions.
#
# WHY THIS EXISTS
#   The source `c_0120.model3.json` has no `Motions` and no `Expressions` section,
#   and the `.exp3.json` files carry no `Name` field of their own. VTube Studio
#   gets away with it by identifying expressions by *filename*, but live2d-py does
#   not: measured on this model, `StartMotion` fired its onStart callback yet moved
#   nothing, and `SetExpression` silently no-opped. Patch the declaration and both
#   work normally.
#
# ASCII FILENAMES
#   Most expression/motion files are named in Chinese. Rather than depend on how the
#   native loader treats non-ASCII paths inside JSON on Windows, we copy every asset
#   to an ASCII name and keep the Chinese names in the generated mapping table. The
#   resulting model3.json is pure ASCII.
#
# Run:  python gen_model3.py

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "modeldata")

# 作者原版解压到哪。默认是仓库里的 model-src\ —— 把作者模型包 DS鲸鱼娘.zip
# 里的 **DS鼠控版.zip** 解压进去（解压后 c_0120.moc3、motions\、*.exp3.json
# 应该直接躺在 model-src\ 下面）。放在别处就设环境变量 MODEL_SRC。
SRC = os.environ.get("MODEL_SRC") or os.path.join(HERE, "model-src")

# Motion groups. "Idle" loops forever in the background; "Action" holds the
# one-shots that hotkeys trigger. Order defines the index used by StartMotion.
IDLE_FILE = "motions/idle.motion3.json"

ACTION_FILES = [
    "aidale.motion3.json",            # 重锤出击
    "motions/chuipaopao.motion3.json",  # 泡泡糖
    "motions/喷水.motion3.json",        # 鲸鱼喷水
    "motions/开盖.motion3.json",        # 自拍手机
    "motions/番茄酱.motion3.json",      # 挤番茄酱动画
    "motions/自拍.motion3.json",        # 快速自拍
    "motions/自拍简单.motion3.json",    # 自拍动画
]

FADE = 0.3  # seconds; the source motions declare no FadeInTime/FadeOutTime


def stem(path):
    """'脸红.exp3.json' -> '脸红';  'motions/喷水.motion3.json' -> '喷水'."""
    b = os.path.basename(path)
    for suf in (".exp3.json", ".motion3.json", ".model3.json"):
        if b.endswith(suf):
            return b[: -len(suf)]
    return b[: -len(".json")] if b.endswith(".json") else b


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(
            "找不到作者原版模型目录：%s\n"
            "把作者模型包 DS鲸鱼娘.zip 里的 DS鼠控版.zip 解压到那里，"
            "或者用环境变量 MODEL_SRC 指过去。" % SRC)
    if not os.path.isfile(os.path.join(SRC, "c_0120.moc3")):
        raise SystemExit(
            "%s 里没有 c_0120.moc3 —— 多半是解压多套了一层目录。\n"
            "要的是解压后文件直接躺在里面的那一层。" % SRC)

    # ---- 1. lay out modeldata/ with ASCII names ----
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(os.path.join(DST, "exp"))
    os.makedirs(os.path.join(DST, "motion"))

    for name in ["c_0120.moc3", "c_0120.physics3.json", "c_0120.cdi3.json",
                 "c_0120.2048", "icon.png"]:
        s = os.path.join(SRC, name)
        d = os.path.join(DST, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)

    # expressions: sorted for a stable, reproducible index
    exp_src = sorted(f for f in os.listdir(SRC) if f.endswith(".exp3.json"))
    expressions = []          # [{name, file, index}]
    for i, f in enumerate(exp_src):
        name = stem(f)
        rel = "exp/exp_{:02d}.exp3.json".format(i)
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, rel))
        expressions.append({"name": name, "file": rel, "index": i})

    # motions
    motions = []              # [{name, file, group, index}]
    shutil.copy2(os.path.join(SRC, IDLE_FILE),
                 os.path.join(DST, "motion/motion_idle.motion3.json"))
    motions.append({"name": stem(IDLE_FILE), "file": "motion/motion_idle.motion3.json",
                    "group": "Idle", "index": 0})
    for i, f in enumerate(ACTION_FILES):
        rel = "motion/motion_{:02d}.motion3.json".format(i)
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, rel))
        motions.append({"name": stem(f), "file": rel, "group": "Action", "index": i})

    # ---- 2. patch model3.json ----
    with open(os.path.join(SRC, "c_0120.model3.json"), encoding="utf-8") as fh:
        model = json.load(fh)

    model["FileReferences"]["Motions"] = {
        "Idle": [{"File": "motion/motion_idle.motion3.json",
                  "FadeInTime": 0.5, "FadeOutTime": 0.5}],
        "Action": [{"File": m["file"], "FadeInTime": FADE, "FadeOutTime": FADE}
                   for m in motions if m["group"] == "Action"],
    }
    model["FileReferences"]["Expressions"] = [
        {"Name": e["name"] if e["name"].isascii() else "exp_{:02d}".format(e["index"]),
         "File": e["file"]}
        for e in expressions
    ]

    # ---- 2b. 从动作文件自己读出时长和它驱动的参数 ----
    #
    # 这三张表原先是我手写在 modelmap.py 里的，而那个文件头写着"由 gen_model3.py
    # 生成，别手改" —— 于是重跑一次生成器就会把它们抹掉，而且抹得悄无声息。
    # 现在按模型数据生成，数据本来就在 motion3.json / physics3.json 里：
    #
    #   MOTION_SEC    <- Meta.Duration（每条的 Meta 里就有，别写死）
    #   MOTION_PARAMS <- Curves[].Id 去重排序
    #   PHYSICS_OUT   <- physics3.json 各 PhysicsSettings[].Output[].Destination.Id
    #
    # 手写那张表当时漏了 aidale 的 Param74~77（星轨迹/锤子旋转/锤子X/兔兔耳朵），
    # 后果是重锤出击演完这四个参数停在最后一帧不回去 —— 生成就不该有这种漏。
    def _read(rel):
        with open(os.path.join(DST, rel), encoding="utf-8") as fh:
            return json.load(fh)

    motion_sec = {}
    motion_params = {}
    for m in motions:
        doc = _read(m["file"])
        motion_sec[m["name"]] = doc["Meta"]["Duration"]
        if m["group"] != "Idle":
            # idle 一直循环着，没有"演完收回"这回事，不进这张表
            motion_params[m["name"]] = sorted({c["Id"] for c in doc["Curves"]})

    physics_out = set()
    for st in _read("c_0120.physics3.json")["PhysicsSettings"]:
        for o in st["Output"]:
            physics_out.add(o["Destination"]["Id"])

    out = os.path.join(DST, "pet.model3.json")
    with open(out, "w", encoding="ascii") as fh:
        json.dump(model, fh, ensure_ascii=True, indent=2)

    # ---- 3. emit the mapping table pet.py and gen_hotkeys.py share ----
    # Expression *names* must be ASCII (they go into model3.json), so the readable
    # Chinese label maps to a generated id. Keep both.
    with open(os.path.join(HERE, "modelmap.py"), "w", encoding="utf-8") as fh:
        fh.write('"""GENERATED by gen_model3.py - do not edit by hand."""\n\n')
        fh.write("# expression label (Chinese, as used by the VTS hotkeys) -> model3.json Name\n")
        fh.write("EXPR_ID = {\n")
        for e in expressions:
            eid = e["name"] if e["name"].isascii() else "exp_{:02d}".format(e["index"])
            fh.write("    {!r}: {!r},\n".format(e["name"], eid))
        fh.write("}\n\n")
        fh.write("# expression label -> file, relative to modeldata/\n")
        fh.write("EXPR_FILE = {\n")
        for e in expressions:
            fh.write("    {!r}: {!r},\n".format(e["name"], e["file"]))
        fh.write("}\n\n")
        fh.write("# motion label -> (group, index) for model.StartMotion\n")
        fh.write("MOTION = {\n")
        for m in motions:
            fh.write("    {!r}: ({!r}, {}),\n".format(m["name"], m["group"], m["index"]))
        fh.write("}\n\n")

        fh.write("# 各动作自己的时长（秒），取自 motion3.json 的 Meta.Duration。\n")
        fh.write("# 用完就收：桌宠靠它决定什么时候把动作留下的姿势拉回默认，见 pet.play_motion。\n")
        fh.write("MOTION_SEC = {\n")
        for m in motions:
            fh.write("    {!r}: {!r},\n".format(m["name"], motion_sec[m["name"]]))
        fh.write("}\n\n")

        fh.write("# 各动作驱动哪些参数，取自 motion3.json 的 Curves[].Id。\n")
        fh.write("# Cubism 演完动作不会把这些参数还原（权重淡到 0 之后值就停在最后一帧），\n")
        fh.write("# 所以收回时得照着这张表挨个拉回默认值。idle 不在表里 —— 它一直循环着，\n")
        fh.write("# 没有「演完」这一刻。\n")
        fh.write("MOTION_PARAMS = {\n")
        for m in motions:
            if m["name"] not in motion_params:
                continue
            names = motion_params[m["name"]]
            fh.write("    {!r}: [".format(m["name"]))
            col = len(repr(m["name"])) + 6
            for i, n in enumerate(names):
                piece = "{!r}".format(n) + (", " if i < len(names) - 1 else "")
                if col + len(piece) > 88:
                    fh.write("\n               ")
                    col = 15
                fh.write(piece)
                col += len(piece)
            fh.write("],\n")
        fh.write("}\n\n")

        fh.write("# 由物理演算（头发/尾巴的摇摆）写出去的参数，取自 c_0120.physics3.json 的 Output。\n")
        fh.write("# Cubism 每帧的顺序是 动作 -> 表情 -> 物理，物理在最后，所以这些参数写什么都会被\n")
        fh.write("# 物理覆盖掉 —— 收回时得绕开它们（写进去也白写，反而会让收回看起来没生效）。\n")
        fh.write("PHYSICS_OUT = {\n")
        for n in sorted(physics_out):
            fh.write("    {!r},\n".format(n))
        fh.write("}\n\n")

        fh.write("# the 'File' string used inside c_0120.vtube.json -> our label\n")
        fh.write("# (VTS writes e.g. '脸红.exp3.json' / '番茄酱.motion3.json')\n")
        fh.write("VTS_FILE = {\n")
        for e in expressions:
            fh.write("    {!r}: {!r},\n".format(e["name"] + ".exp3.json", e["name"]))
        for m in motions:
            fh.write("    {!r}: {!r},\n".format(m["name"] + ".motion3.json", m["name"]))
        fh.write("}\n")

    print("wrote", out)
    print("wrote", os.path.join(HERE, "modelmap.py"))
    print("expressions:", len(expressions), " motions:", len(motions))


if __name__ == "__main__":
    main()
