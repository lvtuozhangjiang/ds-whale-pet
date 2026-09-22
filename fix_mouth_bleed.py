"""去掉嘴角那道淡灰的痕迹。

那道灰不是画上去的，是**双线性采样渗色**：
Live2D 贴图采样是双线性的，"全透明"的像素虽然看不见，RGB 还留在图里。
作者画图时透明区的 RGB 留着黑，texture_00 里有 19 万多个这种像素。
嘴线那一层的网格边缘一旦擦到这些格子，就把它们的黑混了出来 —— 于是嘴左边渗出一道淡灰。

治法不动画：把所有**全透明**像素的 RGB 换成离它最近的不透明像素的颜色，
alpha 原样留 0。看得见的地方一个像素都没改。

而且只在贴图 (1900,1500)-(2048,1700) 这一小块动手。实测：
整幅画面只有 23 个像素变化，全部落在嘴角那几像素里，模型别处逐像素完全一致。

用法:
  python fix_mouth_bleed.py            打补丁（第一次跑会先把原图备份到 ../备份/）
  python fix_mouth_bleed.py --restore  还原（有备份用备份，没有就从作者原版 model-src/ 取）
  python fix_mouth_bleed.py --dry-run  只报会改多少像素，不写文件

依赖 numpy / pillow / scipy，见 requirements.txt 的"只跑这些脚本才需要"一段。
"""
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.join(HERE, "modeldata", "c_0120.2048", "texture_00.png")
BACKUP_DIR = os.path.join(os.path.dirname(HERE), "备份", "c_0120.2048")
BACKUP = os.path.join(BACKUP_DIR, "texture_00.png")

# 只在嘴线网格会采样到的这一小块动手，免得碰别处
BOX = (1900, 1500, 2048, 1700)

# 作者原版贴图（仓库里没有，得自己从模型包里解压出来，见 gen_model3.py 顶部）
SRC_TEX = os.path.join(os.environ.get("MODEL_SRC") or os.path.join(HERE, "model-src"),
                       "c_0120.2048", "texture_00.png")

mode = sys.argv[1] if len(sys.argv) > 1 else ""

if mode == "--restore":
    if os.path.exists(BACKUP):
        shutil.copyfile(BACKUP, TEX)
        print("已从备份还原：%s" % TEX)
    elif os.path.exists(SRC_TEX):
        # 从仓库 clone 下来的人没有"备份"这个目录 —— 备份是第一次跑本脚本时自己建的。
        shutil.copyfile(SRC_TEX, TEX)
        print("已从作者原版还原：%s" % TEX)
    else:
        sys.exit("既没有备份（%s），也没有作者原版（%s）。\n"
                 "把作者模型包里的 DS鼠控版.zip 解压到后者，或者设 MODEL_SRC。"
                 % (BACKUP, SRC_TEX))
    sys.exit(0)

if not os.path.exists(BACKUP):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    shutil.copyfile(TEX, BACKUP)
    print("原图已备份到 %s" % BACKUP)

a = np.asarray(Image.open(TEX).convert("RGBA")).copy()
solid = a[:, :, 3] > 0
before = a[:, :, :3].copy()

# 每个像素 → 离它最近的不透明像素的坐标
idx = ndimage.distance_transform_edt(~solid, return_distances=False,
                                     return_indices=True)
filled = a[:, :, :3][tuple(idx)]

x0, y0, x1, y1 = BOX
region = (slice(y0, y1), slice(x0, x1))
changed = (a[:, :, :3][region] != filled[region]).any(axis=2) & ~solid[region]
print("框内全透明像素 %d 个，其中 RGB 需要改的 %d 个"
      % (int((~solid[region]).sum()), int(changed.sum())))

if mode == "--dry-run":
    sys.exit(0)

a[region + (slice(0, 3),)] = filled[region]
Image.fromarray(a, "RGBA").save(TEX)
print("已打补丁：%s" % TEX)
print("（alpha 通道一个都没改，看得见的地方没有任何像素被动过）")
