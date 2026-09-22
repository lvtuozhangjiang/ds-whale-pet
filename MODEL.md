# 模型来源与改动说明

**本项目的程序代码是 MIT 许可，但 `modeldata/` 里的模型不是本项目的作品。**
这一页说明模型是谁做的、这份副本和原版差在哪、以及使用条件。

## 模型作者

**模型制作：B站 @氵六青（11272072）、@茶坤不接了**

作者无偿分享这个模型。原作者随模型发布的《使用须知.txt》原文只有一句署名
（氵六青），本仓库**原样保留**那份文件，未作任何修改。

- 允许：商用直播、自印物料
- **禁止：任何形式的盗用以及出售**
- 模型为无偿分享
- 使用问题和定制桌宠，作者的 QQ 交流群：645169617

作者已同意本项目开源（包括随仓库分发模型文件）。如果你的使用场景超出了上面
那几条，请直接联系作者本人，不要拿这份 README 当授权凭据。

## 这份 `modeldata/` 与原版的差异

`modeldata/` **不是作者原版的逐字节副本**。它经过了下面几处改动，全部列在这里。

对照的原版是作者模型包 `DS鲸鱼娘.zip` 里的 `DS鼠控版.zip`。

### 逐字节未改动的部分

| 文件 | 说明 |
|---|---|
| `c_0120.moc3` | 模型本体，2.1 MB，**未改** |
| `c_0120.2048/texture_01.png` | 贴图二，**未改** |
| `c_0120.physics3.json` | 物理演算，**未改** |
| `c_0120.cdi3.json` | 参数显示名，**未改** |
| `icon.png` | 图标，**未改** |
| `exp/` 下 44 个表情 | 内容与原版**逐字节相同** |

### 改动一：改名 + 重组（不改内容）

原版把动作和表情直接摊在根目录，文件名是中文（`脸红.exp3.json`、
`motions/自拍.motion3.json`）。Cubism 是按 `model3.json` 里的索引取文件的，
中文文件名在打包和跨平台时容易出问题，所以重排成了 ASCII 名：

```
aidale.motion3.json          -> motion/motion_00.motion3.json
motions/chuipaopao.motion3.json -> motion/motion_01.motion3.json
motions/喷水.motion3.json     -> motion/motion_02.motion3.json
motions/开盖.motion3.json     -> motion/motion_03.motion3.json
motions/番茄酱.motion3.json   -> motion/motion_04.motion3.json
motions/自拍.motion3.json     -> motion/motion_05.motion3.json
motions/自拍简单.motion3.json -> motion/motion_06.motion3.json
motions/idle.motion3.json    -> motion/motion_idle.motion3.json
<表情名>.exp3.json            -> exp/exp_NN.exp3.json
```

中文名没有丢：`modelmap.py` 里存着 `中文名 -> exp_NN` 的对照表，右键菜单用的
就是这些中文名。这个重排由 `gen_model3.py` 完成。

### 改动二：7 个一次性动作的 `Loop` 关掉（**改了内容**）

作者这 8 个动作文件全都写着 `"Loop": true`。在 VTube Studio 里没影响，但在
本程序里会出问题：一个永不结束的循环动作会一直把它驱动的那几个参数按在自己
身上，而鼠标跟随只写 `ParamAngle*` / `ParamEyeBall*`，碰不到它们 —— 于是
**吹完泡泡，嘴就一直是吹泡泡的形状**，下不来了。

所以 7 个"演一遍就完"的动作改成 `"Loop": false`，由 Cubism 自己在播完时把
参数交还；`motion_idle`（待机）保持 `true`，它本来就该一直循环。

改动就是 `"Loop": true` → `"Loop": false` 这一处文本替换，**没有重新格式化
JSON**（Cubism 的解析器读不了被压成一行或改了缩进的文件）。脚本见
`fix_motion_loop.py`。

### 改动三：贴图嘴角防渗色（**改了内容**）

`c_0120.2048/texture_00.png` 有 **23 个像素**被改过。

嘴角那道淡灰不是作者画上去的，是**双线性采样渗色**：Live2D 采样贴图是双线性
的，"全透明"的像素虽然看不见，RGB 还留在图里；作者画图时透明区的 RGB 留着
黑（texture_00 里有 19 万多个这种像素）。嘴线那一层的网格边缘一旦擦到这些
格子，就把它们的黑混了出来。

治法不动画：把**全透明**像素的 RGB 换成离它最近的不透明像素的颜色，alpha 原样
留 0；而且只在 (1900,1500)-(2048,1700) 这一小块动手。看得见的地方一个像素都
没改。脚本见 `fix_mouth_bleed.py`，两个脚本都带 `--restore` 可以还原成原版。

### 新增：`pet.model3.json`

作者原版的 `c_0120.model3.json` **没有 `Motions` 和 `Expressions` 段**（VTS
是按文件夹扫的，不依赖这两段）。而本程序要用 `StartMotion(group, index)` 和
`AddExpression(id)`，必须有声明 —— 所以 `gen_model3.py` 照着原文件生成了
一份 `pet.model3.json`，把这两段补齐，其余字段照抄。

## 想要作者的原版？

从作者那里拿 `DS鲸鱼娘.zip`，解压出 `DS鼠控版.zip`，再解开就是**未经任何改动**
的原版，两个版本的模型本体字节完全相同（鼠控版和面捕版的差别只在
`vtube.json`、`icon.png`、`吐舌.exp3.json` 和几个贴纸文件）。

把解压结果放进仓库的 `model-src/`（或设环境变量 `MODEL_SRC`），就可以重跑
`gen_model3.py` / `gen_hotkeys.py`。

想在本仓库的副本上还原那两处修正：

```bash
python fix_motion_loop.py --restore
python fix_mouth_bleed.py --restore
```

注意还原之后程序会出问题（动作演完参数不归还），还原只是为了对照原版。
