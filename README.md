# DS鲸鱼娘 桌宠

把一套 Live2D 模型做成**独立运行的 Windows 桌面宠物**：双击就是一个 320×320
的鲸鱼娘蹲在屏幕右下角，压在别的窗口上面，背景真透明，不动你的桌面壁纸。

用鼠标跟着你转头转眼睛，左键单击随机表演一个动作，作者那 52 条快捷键一条不落
地照搬，右键菜单里 51 个动作（模型里全部 44 个表情 + 7 个动画）也一条不藏。

> 模型是 B站 **@氵六青（11272072）**、**@茶坤不接了** 的作品，无偿分享，
> **禁止盗用与出售**。程序代码 MIT，模型不是 —— 使用前请看
> [MODEL.md](MODEL.md) 和 [使用须知.txt](使用须知.txt)。

![截图](docs/screenshot.png)

## 直接下载用

到 [Releases](../../releases) 拿，双击就跑，不用装 Python，不用装 Live2D 的任何东西。

| 文件 | 里面是什么 |
|---|---|
| `DS-whale-pet.exe` | 就一个 exe，图省事下这个 |
| `DS-whale-pet-v1.0.0.zip` | exe + 使用说明 + 按键表 + 作者的《使用须知.txt》 |

**建议下 zip 那份** —— 作者的《使用须知.txt》是随模型一起发的，模型的使用条件都写在
里面，zip 保证它跟着模型走。解出来的 exe 叫 `DS鲸鱼娘桌宠.exe`，文件名可以随便改，
不影响使用。

- 第一次启动会解压到临时目录，慢几秒；之后正常
- 配置和日志写在 `%APPDATA%\DS鲸鱼娘桌宠\`，不在 exe 旁边
- Windows 可能会弹 SmartScreen 警告（exe 没签名），点"更多信息 → 仍要运行"

## 怎么玩

| 操作 | 结果 |
|---|---|
| 左键单击 | 随机抽一个动作演一遍（先全部归位，一次只留一个效果） |
| 左键拖动 | 挪位置，松手记住 |
| 右键 | 菜单：51 个动作 + 全部归位、点击穿透、游戏模式、置顶、大小、开机自启、退出 |
| 托盘图标 | 和右键同一个菜单；窗口被隐藏后从这里唤回 |

**右Ctrl + 右Shift + P** 是逃生门 —— 随时切回可交互模式，热键冲突或者戳不中
的时候用。这条刻意避开了作者那 48 条，且**不吞键**。

### 右键菜单

- **动作** → 分三组：`表情（一次一条）` / `装扮与道具（可以和表情一起挂）` /
  `动画`。组名把行为写出来了 —— 点下去会不会顶掉别人，光看名字猜不到。
- **点击穿透** —— 开了之后桌宠完全不挡鼠标，但也点不到它了（托盘和逃生门还在）
- **游戏模式** —— 打游戏时 Alt+字母 / Alt+数字 / 单按 E 会一直被她当成热键，
  在游戏画面上乱做表情。这一条把 48 条全静默（不影响左键和待机）
- **大小** —— 1/25、1/16、1/9 屏

### 待机

每 30 秒她自己挑一个动作演 8 秒，**演完自己收回，不会动你搭好的搭配**。

## 自己从源码跑

```bash
pip install -r requirements.txt
python pet.py
```

环境：Python 3.12 / Windows / PyQt5 5.15 / `live2d-py` 0.7.0.4（自带 Cubism
Core 和着色器，不用另外下 SDK）。

打包：

```bash
pyinstaller build_onefile.spec     # 单文件，发给别人用
pyinstaller build.spec             # onedir，启动快，自己用
```

## 目录

```
pet.py                主程序：窗口、渲染循环、事件、托盘、动作调度
modelmap.py           生成物：中文名 -> 模型内部 id 的对照表
hotkeys.py            生成物：52 条快捷键绑定表
gen_model3.py         从作者原版生成 modeldata/ 和 modelmap.py
gen_hotkeys.py        从作者原版 c_0120.vtube.json 生成 hotkeys.py
fix_motion_loop.py    改作者那 8 个动作的 Loop 标志
fix_mouth_bleed.py    修贴图透明区的渗色
make_icon.py          icon.png -> icon.ico
make_shortcut.py      在桌面建快捷方式
modeldata/            模型（改过的副本，差异见 MODEL.md）
docs/                 使用说明、按键表
_verify_bundle.py     构建后校验：18 个关键符号在不在 exe 里
_smoke_exe.py         启 exe、截图、读窗口属性
_test_*.py            各项回归测试
```

`_` 开头的都是**我自己的验证脚本**，不是程序的一部分。留在仓库根目录是有原因
的：它们要 `import pet`，Python 把**脚本所在目录**加进 `sys.path`，挪进
`tools/` 就 import 不到了。

都靠 `PET_EXE` 环境变量指向要测的 exe，默认 `dist/DS鲸鱼娘桌宠-单文件.exe`：

```bash
python _verify_bundle.py         # exe 里关键符号齐不齐、参数表全不全
python _test_param_residue.py    # 7 条动作演完，247 个参数逐个查有没有残留
python _test_retract_sweep.py    # 47 条（含道具组合）走一遍收回
python _test_prop_visual.py      # 带道具的动作，道具出来没有、收走没有
python _test_recolor.py          # 换色是真换了色，不是没动
python _test_exe_combo.py        # 真按快捷键驱动 exe，验时序
python _test_clamp.py            # 拖到屏幕外，位置钳制
```

关于 `_test_param_residue.py` 和 `_test_retract_sweep.py` 为什么要两份：sweep 查参数
的名单曾经是从 `MOTION_PARAMS` 推的，而那张表正是被检验的东西 —— 表漏了参数，名单
跟着漏，于是有四个参数实打实停在最后一帧，测试却报干净。residue 那份不读任何表，
参数全集直接从模型拿，专门堵这个。**测试的判据不能来自被测对象本身。**

## 改模型 / 换模型

`modeldata/` 不是作者原版的副本，是我**改过并重排过**的一份，改了什么、
为什么改，[MODEL.md](MODEL.md) 里逐条列了。想从作者原版重新生成：

```bash
# 把作者模型包里的 DS鼠控版.zip 解压到 model-src/（或设 MODEL_SRC）
python gen_model3.py
python gen_hotkeys.py
```

## 几个坑

写这个的过程中最费时间的几件事，记在这儿免得下一个人再踩：

- **Cubism 动作演完不还原参数。** 只有 `ResetAllParameters()` 会还。而
  `CubismModel::Update()` 的顺序是动作 → 表情 → 物理，物理会盖掉它列为自己
  输出的每一个参数。所以动作演完必须显式收回，否则姿势就卡在最后一帧。
- **作者那 8 个动作全写着 `"Loop": true`。** 在 VTS 里没事，在这里就是
  "吹完泡泡嘴一直是吹泡泡的形状" —— 一个永不结束的动作会一直按着它驱动的参数。
- **`model3.json` 里没有 `Motions` 和 `Expressions` 段。** VTS 按文件名扫，不
  看这两段；`live2d-py` 看。没有声明的话 `StartMotion` 会触发回调但什么都不动，
  `SetExpression` 静默失败。
- **别把"程序以为的"当成"模型实际的"。** `MOTION_PARAMS` 一度是手写的，`aidale`
  漏了 `Param74~77`（星轨迹/锤子旋转/锤子X/兔兔耳朵），于是重锤出击演完这四个
  参数停在最后一帧。而查残留的测试又是照着这张表查的，所以查不出来。现在表由
  `gen_model3.py` 从 `motion3.json` 生成，测试也改成从模型数据取判据。
- **表情用 `AddExpression` / `RemoveExpression`，不是 `SetExpression`。**
  后者是替换语义，`RemoveExpression` 对它无效，也没法叠加。
- **每帧只调一次 `model.Update(dt)`。** 它内部跑完动作、表情、眨眼、呼吸、
  物理、姿态全序列。手工再调一遍子接口是多余的。
- **更新要放 `timerEvent` 并显式 `self.update()`。** 放进 `paintGL()` 会因为
  Qt 不主动重绘而几乎不执行，表现是"动作和表情完全不生效"。
- **PyQt5 里 Python 异常逃出槽函数会直接 `qFatal` 掉进程。** 所有槽和
  `QTimer` 回调的函数体都得包 try/except。
- **`QTimer.singleShot` 走的是墙上时间**，不是帧。

更多细节散在 `pet.py` 的注释里，那里面写得比这里细。

## 许可

- **程序代码**：MIT，见 [LICENSE](LICENSE)
- **`modeldata/` 和 `使用须知.txt`**：模型作者的作品，**MIT 不适用**。无偿分享，
  禁止盗用与出售，商用直播和自印物料需遵守作者原话 —— 见 [MODEL.md](MODEL.md)
