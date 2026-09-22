"""让 7 个"一次性动作"演完自己收回。

作者这 8 个动作文件全都写了 `"Loop": true`，多半是没动过默认值 —— 在 VTS 里
这些热键动作本来就是播一遍就回到待机的。可桌宠里 `StartMotion` 一起来，
一个永不结束的循环动作就会一直把它驱动的那几个参数按在自己身上：
吹泡泡（motion_01）按的是 `chuipaopao`~`chuipaopao7` 这 8 个自定义参数，
而鼠标跟随只写 ParamAngle*/ParamEyeBall*，碰不到它们 ——
于是"吹完泡泡嘴就一直是吹泡泡的形状"，其它动作的喷水、手机、蛋包饭同理。

关掉 Loop 后，Cubism 自己在动作播完时把参数交还给模型，平滑淡出，不用我们插手。
待机 motion_idle 保持 Loop: true（它就该一直循环）。

注意：**只做文本替换，不重新格式化 JSON**。
Cubism 的 JSON 解析器读不了被压成一行 / 改了缩进的文件（实测报 Json parse error），
所以这里按原样替换 `"Loop": true` → `"Loop": false`，一个字节的排版都不动。

用法:
  python fix_motion_loop.py            改（第一次跑会先把原文件备份到 ../备份/motion/）
  python fix_motion_loop.py --restore  还原（有备份用备份，没有就从作者原版 model-src/ 取）
  python fix_motion_loop.py --dry-run  只报会改哪些文件
"""
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
MDIR = os.path.join(HERE, "modeldata", "motion")
BACKUP_DIR = os.path.join(os.path.dirname(HERE), "备份", "motion")

KEEP_LOOPING = {"motion_idle.motion3.json"}      # 待机继续循环

mode = sys.argv[1] if len(sys.argv) > 1 else ""


def restore_from_src():
    """没有备份时，从作者原版 model-src/ 取回。

    从仓库 clone 下来的人没有"备份"这个目录 —— 备份是第一次跑本脚本时自己建的。
    所以还原得能从原版重建：文件名映射不另抄一份，直接用 gen_model3 那张表，
    免得两边改岔了。"""
    sys.path.insert(0, HERE)
    import gen_model3 as G

    if not os.path.isdir(G.SRC):
        sys.exit("既没有备份（%s），也没有作者原版（%s）。\n"
                 "把作者模型包里的 DS鼠控版.zip 解压到后者，或者设 MODEL_SRC。"
                 % (BACKUP_DIR, G.SRC))

    n = 0
    for i, rel in enumerate(G.ACTION_FILES):
        s = os.path.join(G.SRC, rel)
        d = os.path.join(MDIR, "motion_{:02d}.motion3.json".format(i))
        if not os.path.isfile(s):
            sys.exit("作者原版里没有 %s —— 确认 %s 解压对了。" % (rel, G.SRC))
        shutil.copyfile(s, d)
        n += 1
    s = os.path.join(G.SRC, G.IDLE_FILE)
    shutil.copyfile(s, os.path.join(MDIR, "motion_idle.motion3.json"))
    print("已从作者原版还原 %d 个动作文件（%s）" % (n + 1, G.SRC))


if mode == "--restore":
    if os.path.isdir(BACKUP_DIR):
        for f in os.listdir(BACKUP_DIR):
            shutil.copyfile(os.path.join(BACKUP_DIR, f), os.path.join(MDIR, f))
        print("已从备份还原 %d 个动作文件" % len(os.listdir(BACKUP_DIR)))
    else:
        restore_from_src()
    sys.exit(0)

if not os.path.isdir(BACKUP_DIR):
    shutil.copytree(MDIR, BACKUP_DIR)
    print("原动作文件已备份到 %s" % BACKUP_DIR)

pat = re.compile(r'("Loop"\s*:\s*)true')
changed = 0
for f in sorted(os.listdir(MDIR)):
    if not f.endswith(".motion3.json") or f in KEEP_LOOPING:
        continue
    p = os.path.join(MDIR, f)
    src = open(p, encoding="utf-8").read()
    new, n = pat.subn(r"\1false", src)
    if not n:
        print("  %-28s 本来就是 false，跳过" % f)
        continue
    if mode == "--dry-run":
        print("  %-28s 会改 %d 处" % (f, n))
        changed += n
        continue
    open(p, "w", encoding="utf-8", newline="").write(new)
    print("  %-28s Loop -> false" % f)
    changed += n

print(("会改 %d 处（未写盘）" if mode == "--dry-run" else "共改 %d 处") % changed)
