# DS鲸鱼娘 桌宠 —— 一个自包含的 Live2D 桌面宠物。
#
# 为什么不用 VTube Studio：VTS 的窗口不是分层窗口（WS_EX_LAYERED = False），
# Windows 上拿不到像素级透明，也没有原生的置顶。这里自己搭一个。
#
# 渲染循环的写法来自实测（见 memory/live2d-py-gotchas.md）：
#   * 每帧只调一次 mdl.Update(dt) 就够了 —— 它内部跑完动作、表情、眨眼、呼吸、
#     物理、姿态全序列。手工再调一遍那些子接口是多余的。
#   * 更新必须在 timerEvent 里做并显式 self.update() 排重绘。放进 paintGL() 会
#     因为 Qt 不主动重绘而几乎不执行，表现为"动作和表情完全不生效"。
#   * 表情用 AddExpression / RemoveExpression 这一对，才能叠加并单独关闭。
#     SetExpression 是替换语义，RemoveExpression 对它无效。

import ctypes
import ctypes.wintypes
import faulthandler
import json
import math
import os
import random
import shutil
import sys
import time

from PyQt5.QtCore import Qt, QTimer, QPoint, QRect
from PyQt5.QtGui import QSurfaceFormat, QIcon, QCursor
from PyQt5.QtWidgets import (QApplication, QOpenGLWidget, QMenu,
                             QSystemTrayIcon, QAction, QActionGroup)
import live2d.v3 as live2d

import hotkeys as hk
import modelmap

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                       else __file__))
BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(BUNDLE, "modeldata", "pet.model3.json")
ICON = os.path.join(BUNDLE, "modeldata", "icon.png")

# 运行时"要写"的东西（配置、日志）统一放 %APPDATA%，不放 exe 旁边。两个原因：
#   1. 单文件版经常被直接丢在桌面或下载目录里双击，写旁边的话用户桌面上会凭空
#      多出 config.json 和 pet.log，看着像个来路不明的东西。
#   2. 从压缩包里直接双击运行时，Windows 把 exe 解到临时目录再启动，exe 的所在
#      目录就是那个临时目录 —— 配置写进去，退出时随临时目录一起被删掉。
# 只读的资源（模型、图标）仍然走 BUNDLE，那些在 exe 内部，不受影响。
DATA_DIR = os.path.join(os.environ.get("APPDATA") or HERE, "DS鲸鱼娘桌宠")
CONFIG = os.path.join(DATA_DIR, "config.json")
LOG = os.path.join(DATA_DIR, "pet.log")
CRASH = os.path.join(DATA_DIR, "pet_crash.log")
OLD_CONFIG = os.path.join(HERE, "config.json")      # 老版本存在 exe 旁边
_crash_fh = None        # faulthandler 的目标，必须留引用，否则会被回收掉


def ensure_data_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass


def log(*parts):
    """运行轨迹，写到 %APPDATA%\\DS鲸鱼娘桌宠\\pet.log。

    打包成 --noconsole 之后没有控制台，用户能提供的全部信息就是"它闪退了"。
    之前排查那次闪退报告时，日志是空的、事件查看器里也没有崩溃记录，什么都
    定不了位。所以把关键节点都记下来：启动、被单实例挡下、每个动作、隐藏/
    显示、穿透开关、退出。"""
    try:
        ensure_data_dir()
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("%s [%d] %s\n" % (time.strftime("%m-%d %H:%M:%S"),
                                       os.getpid(),
                                       " ".join(str(p) for p in parts)))
    except Exception:
        pass


def rotate_log():
    """日志只留最近这一段。动作热键会持续往里写，不封顶的话迟早变成
    几十兆的垃圾文件躺在用户 APPDATA 里。"""
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1 << 20:
            os.replace(LOG, LOG + ".old")
    except Exception:
        pass


def migrate_config():
    """老版本把 config.json 放在 exe 旁边。第一次跑新版本时搬过去，
    免得用户发现位置和大小被重置回默认值。"""
    if os.path.exists(CONFIG) or not os.path.exists(OLD_CONFIG):
        return
    ensure_data_dir()
    try:
        shutil.copy2(OLD_CONFIG, CONFIG)
    except Exception:
        pass

# 尺寸按"占屏幕面积的比例"定义，不写死像素 —— 这样跟分辨率、系统缩放都无关。
# 注意 Qt5 默认把 Windows 的缩放比例取整（这里 150% 被取整成 2.0），所以逻辑像素
# 和物理像素差 2 倍；写死 320 逻辑像素实际会得到 640 物理像素，也就是 1/9 屏。
# 这里从屏幕的物理面积反推边长，保证 1/16 就是 1/16。
SIZES = [("小", 25), ("中", 16), ("大", 9)]     # (名称, 面积分母)
DEFAULT_AREA_DIV = 16                            # 用户要的 ≈1/16 屏
MARGIN = 16
DRAG_THRESHOLD = 4

# 鼠标跟随映射，取自模型自带的 c_0120.vtube.json 的 ParameterSettings
# （原作者调好的范围，不自己编）。字段：
#   参数, 输入轴, 输入下界, 输入上界, 输出下界, 输出上界, 平滑
# 平滑值越大越迟钝，跟 VTS 的观感一致。
FOLLOW = [
    ("ParamAngleX",     "x", -1.0, 1.0, -30.0,  15.0, 31),
    ("ParamAngleY",     "y", -1.0, 1.0, -25.0,  30.0, 32),
    ("ParamAngleZ",     "x", -1.0, 1.0, -20.0,  20.0, 85),
    ("ParamEyeBallX",   "x", -1.0, 1.0,  -1.0,   1.0,  0),
    ("ParamEyeBallY",   "y", -1.0, 1.0,  -0.3,   0.5,  0),
    ("pointX",          "x", -1.0, 1.0, -30.0,  30.0, 20),
    ("pointY",          "y", -1.0, 1.0, -30.0,  30.0, 20),
    ("danbaoX",         "x", -1.0, 1.0, -10.0,  10.0, 20),
    ("danbaoY",         "y", -1.0, 1.0, -10.0,  10.0, 20),
    # 原配置里身体旋转由 FaceAngle* 驱动（面捕信号），鼠控版没有这个来源。
    # 这三条是我补的：用同一份鼠标输入接过去，幅度取小以免 320px 下晃得厉害。
    ("ParamBodyAngleX", "x", -1.0, 1.0, -10.0,  10.0, 20),
    ("ParamBodyAngleY", "y", -1.0, 1.0, -10.0,  10.0, 20),
    ("ParamBodyAngleZ", "x", -1.0, 1.0,  -5.0,   5.0, 20),
]

# 鼠标跟随每帧都在写的参数。收回姿势时要绕开它们：follow 每帧覆盖一次，
# 本来就不会卡住，写进去也是白写（下一帧就被顶掉）。
FOLLOW_NAMES = {pid for pid, _axis, *_rest in FOLLOW}

# 左键单击 = 从这个池子里随机抽一个动作。排除两类，都是实测出来的：
#
# 一、推上去画面纹丝不动（参数被作者漏接了，见下面 DEAD_ACTION 那段）：
#     喷水 (pengshui) / 冒爱心 (love) / 挤 (ji)。这三条在阈值 3/255 下都是
#     0 像素，同一套手法推 ParamAngleZ 对照组是 594 像素，所以不是测法的问题。
#
# 二、`开盖` —— 它是下面 PROP_LEAD 里的前置（掏手机），单抽出来只有 1 秒的
#     掏手机、没下文。它自己不进池子，但手动点菜单照样能播。
#
# 「要有道具才有意义」那一类（自拍 / 番茄酱 / 手机换色 / 魔爪换色）原先也排除了，
# 现在归 PROP_LEAD 管、能自己把道具弄出来，所以都收进池子。
RANDOM_EXCLUDE = {"开盖", "喷水", "love", "挤"}

# 道具依赖的动作：单独播就是空比划，得先把道具弄出来。
#
# 值是**先弄道具的那几步**，每步 (kind, label)，kind 同 fire()。道具本身可能是
# 动作，也可能是装扮 —— 所以步骤得能混着排：
#
#   · 自拍 / 自拍简单 —— 两条自拍的曲线一上来就假定手机已经在手里（phone 的首值
#     就是 1）。单独播不会没有手机，而是一百九十毫秒里从 0 冲到 1，"啪"一下凭空
#     出现在手里，不是"掏出来"。开盖那一秒补的就是这个。
#   · 手机换色 —— 换的是手机的颜色（shouji=1）。道具不在时推上去画面 0 像素。
#   · 魔爪换色 —— 同上，要 mozhua=1，那是「魔爪」这条装扮摆出来的。
#   · 番茄酱   —— 挤的是蛋包饭上的酱，要 danbaofan=1（「蛋包饭」那条装扮，
#     顺带还把 point 压到 -1）。作者原版 VTS 配置里这就是一个组合
#     （蛋包饭 + 挤番茄酱），这里照绑。
PROP_LEAD = {
    "自拍":     [("motion", "开盖")],
    "自拍简单": [("motion", "开盖")],
    "手机换色": [("motion", "开盖")],
    "番茄酱":   [("expr", "蛋包饭")],
    "魔爪换色": [("expr", "魔爪")],
}

# 表情步骤演多久。表情是"挂上去"的，没有自己的时长：作为正片收尾时留一段让人
# 看清（实测淡入淡出要 1.05 秒，取 3 秒留出余量）；作为前置时是 0，让下一步
# 立刻接上（道具先摆好，正片马上开演）。
PROP_EXPR_HOLD_SEC = 3.0

# 一条规矩：**带道具的动作是一段自己会收的表演，道具不留在场上**。
#
# 于是「手机换色」点下去是"掏手机 → 换个色 → 收起来"，演完不留，和它所在的
# 「装扮与道具」那一组（点了就挂着）不一样。这是被手机那一条逼出来的：
# 手机是 `开盖` 这条**动作**摆出来的，动作的参数必须收回（不然就是第八轮那个
# "姿势卡在最后一帧"的 bug），手机一收，「手机换色」就成了一条挂在那儿、
# 屏幕上什么也看不见的表情 —— 菜单里打着勾却毫无动静，比演完就收更怪。
#
# 待机那条规矩也要求这样：她挑一个动作演，**不能动你搭好的搭配**。
# 要是抽到「番茄酱」就把蛋包饭永远留在桌上，那正是"动了你的搭配"。

# 模型作者漏接了参数、点了画面纹丝不动的几条。菜单里照旧列出来（用户要的是
# "一条都不藏"），但名字后面挂个标记，免得点完以为是自己没点到。
# 判定方法见上面第二条；`pengshui` 在整个模型里只出现在 cdi3.json 的声明和那条
# 驱动它的动作里，没有任何表情/部件引用它 —— 作者原版在 VTS 里也是这个效果。
DEAD_ACTION = {"喷水", "love", "挤"}

# 待机：多久自己动一次、一次演多久。
# 间隔 30 秒（用户 2026-09-21 从 60 秒调快的）—— 她一动你，计时就从那一刻重新算。
# 演出时间取 8 秒 —— 表情的淡入淡出实测要 1.05 秒，太短的话还没看清就收了；
# 太长又会和"她自己待机"的节奏脱节。
IDLE_INTERVAL_MS = 30 * 1000
IDLE_HOLD_MS = 8 * 1000

# 动作演完，姿势用多久拉回默认。为什么不"啪"一下了事：动作停在最后一帧的
# 姿势上，比如吹泡泡的终点还是吹着的嘴，直接复位就是一帧内的突变。
RETRACT_FADE_SEC = 0.4

# 右键「动作」菜单的分组，给记不住那 48 条快捷键的人用。按"看起来是什么"分，
# 不按按键位置。每项是 (kind, label, 显示名)，label 走 modelmap。
# 52 条全在这里 —— 显式点选时不隐藏任何一条，抽不到的那 5 条手动还是能播。
ACTION_MENU = [
    ("表情", [
        ("expr", "悲伤", "悲伤"), ("expr", "星星眼", "星星眼"),
        ("expr", "爱心眼", "爱心眼"), ("expr", "呆呆眼", "呆呆眼"),
        ("expr", "闭眼口水", "闭眼口水"), ("expr", "哭", "大哭"),
        ("expr", "开心兴奋", "开心兴奋"), ("expr", "晕晕", "晕晕"),
        ("expr", "生气", "生气"), ("expr", "调皮", "调皮"),
        ("expr", "阴暗", "阴暗"), ("expr", "脸红", "脸红"),
        ("expr", "问号", "问号"), ("expr", "流汗", "流汗"),
        ("expr", "感叹号", "感叹号"), ("expr", "圆眼镜", "圆眼镜"),
        ("expr", "方眼镜", "方眼镜"), ("expr", "椭圆眼镜", "椭圆眼镜"),
        ("expr", "墨镜", "墨镜"), ("expr", "情绪花花", "情绪花花"),
        ("expr", "心跳", "心跳"), ("expr", "猫猫贴纸", "猫猫贴纸"),
        ("expr", "兔兔贴纸", "兔兔贴纸"), ("expr", "蝴蝶结贴纸", "蝴蝶结贴纸"),
        ("expr", "吐魂", "吐魂"),
        # 吐舌原来排在「装扮与道具」那一组（作者的热键表把它排在那一带），
        # 但它改的是 ParamMouthOpenY / ParamMouthForm / ParamCheek79(舌头) /
        # ParamBrowRForm2 —— 是彻头彻尾的表情，而且是用户报的那个 bug 的主角。
        # 放到「装扮」组就等于给它开了叠加的后门，闭着嘴的表情会顶着它的张嘴。
        ("expr", "吐舌", "吐舌"),
    ]),
    ("装扮与道具", [
        ("expr", "鲸鱼", "头顶鲸鱼"), ("expr", "单边马尾", "单边马尾"),
        ("expr", "头箍", "摘掉发箍"), ("expr", "深色桌布", "深色桌布"),
        ("expr", "鲸鱼放桌上", "鲸鱼放桌上"), ("expr", "蛋包饭", "蛋包饭"),
        ("expr", "喵喵手~喵~动画", "喵喵手"), ("expr", "love", "冒爱心"),
        ("expr", "双手比耶", "双手比耶"), ("expr", "巴菲", "桌面芭菲"),
        ("expr", "魔爪", "桌面粉魔爪"), ("expr", "魔爪换色", "魔爪变白"),
        ("expr", "手机换色", "手机换色"),
        ("expr", "点菜按下", "点菜"), ("expr", "画笔", "画笔"),
        ("expr", "挤", "MoeMoeQ~"), ("expr", "橡皮", "橡皮"),
        ("expr", "撤回", "撤回"),
    ]),
    ("动画", [
        ("motion", "喷水", "鲸鱼喷水"), ("motion", "aidale", "重锤出击"),
        ("motion", "chuipaopao", "泡泡糖"), ("motion", "番茄酱", "挤番茄酱"),
        ("motion", "开盖", "自拍手机"), ("motion", "自拍", "快速自拍"),
        ("motion", "自拍简单", "自拍动画"),
    ]),
]

# 可以和表情同时挂着的那些 —— 就是「装扮与道具」这一组。do_action 只关「表情」
# 组的，这组一律留着。名单不另立一份，直接从菜单分组推出来，免得改了一边忘了
# 另一边：**改 ACTION_MENU 的分组 = 改点下去的行为。**
#
# 怎么分的：**长在脸上的算表情，摆在身上/桌上的算装扮。**
# 这个分法和参数结构是吻合的，查了全部 44 份 .exp3.json：
#   · 改脸的 9 条（哭 / 生气 / 爱心眼 / 开心兴奋 / 晕晕 / 悲伤 / 调皮 / 吐舌 /
#     墨镜）动的都是标准骨骼 ParamEye* / ParamBrow* / ParamMouth*，几条一起抢
#     同一批参数（比如 6 条一起抢 ParamBrow*），本来就没法叠；
#   · 这 18 条各自只占一个独立的自定义槽（jingyu / bafei / mozhua / phone /
#     danbaofan / chehui…）。作者给每个道具单开一个参数，本来就是**为了让它们
#     能同时出现**。
#
# 眼镜和贴纸（猫猫/兔兔/蝴蝶结贴纸、圆方椭圆眼镜、漂浮的问号流汗爱心）虽然也是
# "道具"，但它们长在脸上、和表情占的是同一块地方，所以留在「表情」组里互斥。
# 要把它们挪到可叠那边，就是 ACTION_MENU 里挪一行的事。
STACKABLE = {label for group, items in ACTION_MENU if group == "装扮与道具"
             for _kind, label, _title in items}

# 菜单里显示的组名。把「会不会顶掉别人」直接写在标题上 —— 这是这个菜单最容易
# 让人误解的地方，光看「表情 / 装扮与道具」猜不出来点下去会怎样。
GROUP_TITLE = {
    "表情": "表情（一次一条）",
    "装扮与道具": "装扮与道具（可以和表情一起挂）",
    "动画": "动画",
}

# ---- Win32 ----
u32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10
SW_SHOW = 5
u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
# 声明 argtypes，否则 64 位窗口句柄会被 ctypes 按 c_int 截断
u32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
u32.GetWindowLongW.restype = ctypes.c_long
u32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
u32.SetWindowLongW.restype = ctypes.c_long
u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
u32.GetAsyncKeyState.restype = ctypes.c_short
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DS鲸鱼娘桌宠"

# 重画用。收菜单时要把菜单占的那块屏幕重新刷一遍，见 Pet.repaint_region。
RDW_INVALIDATE, RDW_ERASE, RDW_ALLCHILDREN, RDW_UPDATENOW = 0x1, 0x4, 0x80, 0x100
u32.RedrawWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_uint]
u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
u32.FindWindowW.restype = ctypes.c_void_p
u32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                             ctypes.c_void_p]
u32.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
u32.RegisterWindowMessageW.restype = ctypes.c_uint

# 穿透逃生门。穿透开着时窗口收不到任何鼠标消息，托盘图标是唯一入口 —— 万一托盘
# 图标被 Win11 折叠进隐藏区（默认就会），用户就彻底锁死了：click_through 是持久化
# 的，杀掉进程重启读回来还是穿透，照样点不到。这条热键保证任何时候都切得回来。
# 刻意避开 hotkeys.py 里那 48 条，且不吞键。
CLICK_THROUGH_KEYS = (0xA3, 0xA1, 0x50)          # 右Ctrl + 右Shift + P

# 单实例：两个桌宠会摆在同一位置严丝合缝地重叠，静止时看不出来，
# 一播动作两边相位不同就错开，看起来就是"重影"。用命名互斥体挡住第二次启动。
# 不带 "Global\" 前缀 —— 那需要 SeCreateGlobalPrivilege，标准用户可能创建失败；
# 而且桌宠本就该每会话一个，别的用户登录后各开各的才对。
k32 = ctypes.windll.kernel32
MUTEX_NAME = "DSWhalePet_SingleInstance"
ERROR_ALREADY_EXISTS = 183
_k32_handles = []       # 句柄必须活到进程结束，被回收锁就没了


def claim_single_instance():
    """已有一个实例在跑就返回 False。"""
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, 0, MUTEX_NAME)
    if not h:
        return True                      # 拿不到互斥体就别挡着用户用
    _k32_handles.append(h)
    return k32.GetLastError() != ERROR_ALREADY_EXISTS


# 第二次启动时用来叫醒已经在跑的那一个。
#
# 光靠互斥体"挡住"是不够的：安静地退出，用户看到的就是"双击图标没反应"或者
# "闪一下人就没了"。而当旧实例正好是隐藏状态（菜单里点过「隐藏桌宠」）或者开着
# 穿透，托盘图标又被 Win11 默认折进隐藏区 —— 用户就彻底找不回桌宠了，只能得出
# "它闪退了"的结论。所以第二次启动改成给旧窗口发个自定义消息，让它自己现身。
# 必须在模块加载时就注册：接收方（先启动的那个实例）的 nativeEvent 里靠它做
# 判断，如果等 wake_existing() 被调用才注册，先启动的那个拿到的永远是 0，
# 消息就白发了。
try:
    WAKE_MSG = u32.RegisterWindowMessageW("DSWhalePet_Wake")
except Exception:
    WAKE_MSG = 0


def wake_existing():
    """叫醒已经在跑的那个实例。叫到了返回 True。"""
    try:
        h = u32.FindWindowW(None, RUN_NAME)
        if not h:
            return False
        u32.PostMessageW(h, WAKE_MSG, None, None)
        return True
    except Exception:
        return False


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as k:
        if on:
            exe = sys.executable if getattr(sys, "frozen", False) else None
            if not exe:
                return False
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, '"%s"' % exe)
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
    return True


def pressed(vk):
    return bool(u32.GetAsyncKeyState(vk) & 0x8000)


def side_for_area_div(div):
    """边长（Qt 逻辑像素），使窗口物理面积约为屏幕的 1/div。"""
    g = QApplication.primaryScreen().geometry()
    return max(64, int(round(math.sqrt(g.width() * g.height() / float(div)))))


class Pet(QOpenGLWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.model = None
        self.mdl = None
        self.idx = {}
        self.active_expr = set()
        self.held = set()
        self.held_thru = False       # 穿透热键的按下沿检测
        self.last_pick = None        # 左键随机抽中的那个（排查用）
        self.idle_token = 0          # 待机收回的凭据，见 note_manual
        self.motion_token = 0        # 动作收回的凭据，见 play_motion
        self.motion_labels = []      # 正在播的那串动作，收回时照着它们查参数表
        self.seq_exprs = []          # 这串动作顺带挂上去的道具表情，收回时摘掉
        self.retract = None          # 正在进行的收回：[[(名, 起点值, 默认值)], 剩余秒]
        self.expr_acts = {}          # 动作菜单里表情项的 QAction，用来打勾
        self.size_acts = {}
        self._menu = None
        self.follow_cur = {}
        self.dragging = False
        self.drag_from = None
        self.press_pos = None
        self.last = time.time()
        self.angle_buf = {}

        self.area_div = cfg.get("area_div", DEFAULT_AREA_DIV)
        self.size_px = side_for_area_div(self.area_div)
        self.click_through = cfg.get("click_through", False)
        self.topmost = cfg.get("topmost", True)
        # 游戏模式：作者那 48 条动作热键全部静默。默认关。
        self.game_mode = cfg.get("game_mode", False)

        self.setWindowTitle("DS鲸鱼娘桌宠")
        self.setWindowIcon(QIcon(ICON))
        # 这里不加 Qt.Tool。Tool 会让窗口从任务栏和 Alt+Tab 里一起消失，而用户要的
        # 正是"任务栏有个图标、能直接关掉桌宠"。Windows 上任务栏和 Alt+Tab 是同一套
        # 判定（WS_EX_TOOLWINDOW 同时排除两者），没法只保留其一，所以 Alt+Tab 里会多
        # 一条"DS鲸鱼娘桌宠"，这是取舍后的结果。
        flags = Qt.FramelessWindowHint
        if self.topmost:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

    # ---------- 窗口 ----------
    def hwnd(self):
        return int(self.winId())

    def nativeEvent(self, eventType, message):
        """只为了收"叫醒"那条自定义消息 —— QWidget 没有别的入口能收到
        WM_USER 以上的窗口消息。"""
        try:
            if WAKE_MSG:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WAKE_MSG:
                    self.wake_up()
                    return True, 0
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def wake_up(self):
        """第二次双击图标 = 用户在说"把它叫出来"。
        顺手关掉穿透：穿透状态下唤回来也还是点不动，等于没唤。"""
        log("被叫醒：显示窗口" + ("，并关掉穿透" if self.click_through else ""))
        if self.click_through:
            self.toggle_click_through(False)
        self.show_pet()
        # 再从 Win32 层面显式显示一次。Qt 认为窗口可见、但系统层面被藏起来的情况
        # 是存在的 —— 按 Win+D"显示桌面"就是这么藏的。那种状态下 self.show() 是
        # 空操作，唤不回来。
        u32.ShowWindow(self.hwnd(), SW_SHOW)
        u32.SetWindowPos(self.hwnd(), HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.raise_()

    def repaint_region(self, rect):
        """把菜单占过的那块屏幕重新刷一遍。

        实测：菜单是叠在置顶半透明窗口上的，收起之后系统没有重画它底下的那块，
        菜单的像素会原地留在屏幕上，看起来就像"菜单卡住了不走"。只刷自己的窗口
        不够 —— 菜单有一半压在本窗口外面，得连着桌面一起刷。"""
        try:
            r = ctypes.wintypes.RECT(rect.left(), rect.top(), rect.right(),
                                     rect.bottom())
            u32.RedrawWindow(None, ctypes.byref(r), None,
                             RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN
                             | RDW_UPDATENOW)
        except Exception:
            pass

    def on_menu_hide(self):
        # 等菜单真收起来再刷，aboutToHide 时它还在屏幕上
        g = self._menu.geometry()
        QTimer.singleShot(40, lambda: self.repaint_region(g))

    def apply_click_through(self):
        ex = u32.GetWindowLongW(self.hwnd(), GWL_EXSTYLE)
        if self.click_through:
            ex |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            ex &= ~WS_EX_TRANSPARENT
        u32.SetWindowLongW(self.hwnd(), GWL_EXSTYLE, ex)

    def apply_topmost(self):
        u32.SetWindowPos(self.hwnd(), HWND_TOPMOST if self.topmost else HWND_NOTOPMOST,
                         0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def default_pos(self):
        g = QApplication.primaryScreen().availableGeometry()
        return g.right() - self.size_px - MARGIN, g.bottom() - self.size_px - MARGIN

    def screen_for(self, x, y):
        """挑一块屏幕安置窗口：优先能盛下这个点的，都不盛就取最近的。

        不能只认 primaryScreen —— config 里的坐标可能是插着第二块屏时存的，
        那块屏拔了之后坐标就落在不存在的区域里。
        """
        best, best_d = QApplication.primaryScreen(), None
        for s in QApplication.screens():
            g = s.availableGeometry()
            if g.contains(x, y):
                return s
            # 点到矩形外接框的距离平方，取最近的
            dx = max(g.left() - x, 0, x - g.right())
            dy = max(g.top() - y, 0, y - g.bottom())
            d = dx * dx + dy * dy
            if best_d is None or d < best_d:
                best, best_d = s, d
        return best

    def clamp_to_screen(self, x, y):
        """把窗口夹回可视区。

        config 里的 pos 是上次退出时存的。换了分辨率、拔了一块屏、或者文件被写坏了，
        窗口就会落在屏幕外 —— 那时她既看不见也点不到，右键菜单挂在窗口上同样叫不出来，
        表现和"她不见了"一模一样，只能去删 config。夹一下至少保证还在画面上。
        """
        g = self.screen_for(x, y).availableGeometry()
        w = h = self.size_px
        # 窗口比屏幕还大时无处可夹，贴左上角，至少露出左上那一片
        cx = g.left() if g.width() <= w else max(g.left(), min(x, g.right() - w + 1))
        cy = g.top() if g.height() <= h else max(g.top(), min(y, g.bottom() - h + 1))
        if (cx, cy) != (x, y):
            log("位置", "config 里的 %s,%s 落在屏幕外，夹回 %s,%s" % (x, y, cx, cy))
        return cx, cy

    def reachable(self, x, y):
        """窗口至少有一块落在某块屏的可视区里？"""
        r = QRect(x, y, self.size_px, self.size_px)
        return any(s.availableGeometry().intersects(r)
                   for s in QApplication.screens())

    def place(self):
        x, y = self.cfg.get("pos", [None, None])
        if x is None or y is None:
            x, y = self.default_pos()
        else:
            x, y = self.clamp_to_screen(int(x), int(y))
        self.setGeometry(int(x), int(y), self.size_px, self.size_px)

    def resize_to(self, div):
        self.area_div = div
        self.size_px = side_for_area_div(div)
        self.cfg["area_div"] = div
        self.place()
        if self.model:
            self.model.Resize(self.size_px, self.size_px)
        save_config(self.cfg)

    # ---------- GL ----------
    def initializeGL(self):
        live2d.glInit()
        m = live2d.LAppModel()
        self.model = m
        self.mdl = m._model
        m.LoadModelJson(MODEL)
        m.Resize(self.width(), self.height())
        m.SetAutoBlinkEnable(True)
        m.SetAutoBreathEnable(True)
        self.idx = {n: i for i, n in enumerate(m.GetParamIds())}

        self.timer = self.startTimer(16)
        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.timeout.connect(self.poll_hotkeys)
        self.hotkey_timer.start(25)

        # 待机。idle_token 是"这次待机还算不算数"的凭据，你手动一动就 +1，
        # 让已经排上队的那次收回失效 —— 细节见 note_manual。
        self.idle_token = 0
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.idle_action)
        self.idle_timer.start(IDLE_INTERVAL_MS)

    def paintGL(self):
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if self.model:
            self.model.Draw()

    def resizeGL(self, w, h):
        if self.model:
            self.model.Resize(w, h)

    # ---------- 每帧 ----------
    def timerEvent(self, ev):
        now = time.time()
        dt = min(now - self.last, 0.1)
        self.last = now
        try:
            self.update_follow(dt)
            self.step_retract(dt)
            self.mdl.Update(dt)     # 这一行跑完全部动画子系统
        except Exception:
            pass
        self.update()               # 不排重绘 paintGL 就不会被调用

    # ---------- 动作的播与收 ----------
    def clear_pose(self):
        """把动作留在参数上的姿势一次清掉。

        `ResetAllParameters` 只碰参数，不碰表情 —— Cubism 的表情是每帧重新叠加上去
        的，复位之后下一次 Update 就把它加回来了，所以戴着的墨镜、桌上的蛋包饭
        都还在。实测确认过。"""
        self.model.StopAllMotions()
        self.mdl.ResetAllParameters()

    def play_motion(self, label):
        """演一个动作，要道具就先把道具弄出来（见 PROP_LEAD）。"""
        self.play_action("motion", label)

    def play_action(self, kind, label):
        """落地「用户点了这个」的一个动作，带道具前置就连着前置一起排。

        为什么非得自己收：Cubism 不会替我们把参数还原。动作的权重淡到 0 之后，
        它驱动过的参数就停在最后一帧的值上 —— 实测吹泡泡演完，`chuipaopao` 那 8 个
        参数原封不动留着，而鼠标跟随只写 ParamAngle*/ParamEyeBall*，碰不到它们，
        于是嘴就一直是吹泡泡的形状（用户报的"换到一个动作之后就一直保持那个动作"）。
        收回的时刻取动作自己的时长（modelmap.MOTION_SEC），也就是它演完的那一刻。

        「已经开着的表情再点一下 = 关掉」不走序列 —— 关掉不需要道具，而且序列那套
        是"把东西弄出来"，语义正好反着。

        同理，**不用道具的表情也不走序列**：序列演完会自己收回，而表情是开关，
        点一下脸红就该一直挂着，三秒后自己消失是说不通的。"""
        if kind == "expr" and label in self.active_expr:
            self.set_expr(label, False)
            return
        lead = PROP_LEAD.get(label, [])
        if kind == "expr" and not lead:
            self.set_expr(label, True)
            return
        self.run_steps(lead + [(kind, label)])

    def set_expr(self, label, on):
        """开/关一条表情。返回是不是真的动了它。"""
        eid = modelmap.EXPR_ID.get(label)
        if eid is None:
            return False
        if on and label not in self.active_expr:
            self.model.AddExpression(eid)
            self.active_expr.add(label)
            return True
        if not on and label in self.active_expr:
            self.model.RemoveExpression(eid)
            self.active_expr.discard(label)
            return True
        return False

    def run_steps(self, steps):
        """按顺序演几步，演完一起收回。每步是 (kind, label)，kind 同 fire()。

        中间那几步不能各走一次 play_action —— 它每步开头都 clear_pose()，
        开盖刚把手机掏出来，自拍一开头就给她收回去了。所以清场只在最前面做一次，
        后面每步按前一步的时长准点接上（StartMotion 是 FORCE 优先级，接手时会
        把上一段停掉，不用我们管）。

        **只有这几步里有动作时才清场**：纯表情的（「魔爪 + 魔爪换色」）本来就不该
        打断正播着的动作，点一条换装把吹泡泡打断是说不通的。

        收回照**全部**几步来：动作的参数取 MOTION_PARAMS 的并集（不然开盖摆出来的
        手机不在自拍的参数表里，会漏在手里），表情那几步单独记下来一起摘掉（不然
        蛋包饭的盘子、魔爪会留在桌上）。

        「魔爪 + 魔爪换色」这种**纯表情的组合不碰动作那条线** —— 它不动 motion_token，
        收的时候也不 StopAllMotions。凭据一动，正播着的动作排好的那次收回就作废了，
        泡泡的嘴会永远卡在脸上（第八轮修的就是这个）。"""
        steps = [(k, l) for k, l in steps
                 if (k == "motion" and l in modelmap.MOTION)
                 or (k == "expr" and l in modelmap.EXPR_ID)]
        if not steps:
            return
        motions = [l for k, l in steps if k == "motion"]
        self.seq_exprs = []              # 这次新挂上去的表情，收的时候摘掉
        if motions:
            self.motion_token += 1       # 这一串动作归我，之前排的收回作废
            self.motion_labels = motions
            self.retract = None
        try:
            if motions:
                self.clear_pose()    # 先清掉上一个动作的残留，切换时不继承
            at = 0.0                 # 每步排在自己的起点上
            last = len(steps) - 1
            for n, (kind, label) in enumerate(steps):
                if at <= 0:
                    self.apply_step(kind, label)
                else:
                    QTimer.singleShot(int(at * 1000),
                                      lambda k=kind, l=label: self.apply_step(k, l))
                # 轮下一步之前，这一步占多久
                if kind == "motion":
                    at += modelmap.MOTION_SEC.get(label, 3.0)
                elif n < last:
                    at += 0.0            # 道具：下一步立刻接上
                else:
                    at += PROP_EXPR_HOLD_SEC   # 正片：留一段让人看清
        except Exception:
            return
        # 纯表情的组合：所有步都在 at=0 上、当场就挂完了，快照就是全貌。
        # 动作串不能这么抓 —— 后面的表情步排在 at>0，这会儿还没挂上，
        # 得等收回那一刻现读 self.seq_exprs。
        exprs = list(self.seq_exprs)
        if motions:
            tok = self.motion_token
            QTimer.singleShot(int(at * 1000), lambda: self.retract_motion(tok))
        elif exprs:
            QTimer.singleShot(int(at * 1000),
                              lambda: self.drop_exprs(self.motion_token, exprs))

    def apply_step(self, kind, label):
        """执行一步。异常必须吞掉：多半是从 QTimer 回调进来的，逃出槽函数 PyQt5
        会当成致命错误直接 abort 掉进程；退出时排队的那次也一样会被派发，
        那会儿 GL 上下文已经没了。"""
        try:
            if kind == "expr":
                # 本来就在的不算我们挂的，收的时候也别动它（可能是你自己搭的）
                if self.set_expr(label, True):
                    self.seq_exprs.append(label)
            else:
                g, i = modelmap.MOTION[label]
                self.model.StartMotion(g, i, live2d.MotionPriority.FORCE)
        except Exception:
            pass

    def drop_exprs(self, tok, labels):
        """这一串道具表情演完了，摘掉。tok 是排它时的 motion_token —— 这中间你要是
        点了别的动作，那次动作已经清过场了，就别再按老账本去动表情。"""
        try:
            if tok != self.motion_token:
                return
            # 和「动作 收回」「待机 收回」对齐 —— 纯表情的组合没有动作可收，
            # 但日志里也得留下"这一串演完了"，不然翻日志像是没收。
            log("动作", "收回", "+".join(labels))
            for label in labels:
                self.set_expr(label, False)
            for label in labels:
                if label in self.seq_exprs:
                    self.seq_exprs.remove(label)
        except Exception:
            pass

    def retract_motion(self, tok):
        # 整个包在 try 里：这是 QTimer 回调，异常逃出去会被 PyQt5 当成致命错误
        # 直接 abort 掉进程。而且退出时排队的那次仍可能被派发，那时 GL 上下文
        # 已经没了，self.mdl 是野指针。
        try:
            if tok != self.motion_token:
                return              # 这中间你又点了别的动作，以新的为准
            self.model.StopAllMotions()
            # 和「待机 收回」对齐，方便翻日志。组合动作记成「开盖+自拍」。
            log("动作", "收回", "+".join(self.motion_labels + self.seq_exprs))
            # 先摘表情再记参数：表情的贡献是每帧叠加上去的，摘掉之后参数会自己
            # 减回去，这时量到的才是真正的基准值，收回的起点不会偏高一个道具的量。
            for label in self.seq_exprs:
                self.set_expr(label, False)
            self.seq_exprs = []
            self.begin_retract(self.motion_labels)
        except Exception:
            pass

    def begin_retract(self, labels):
        """记下这些动作驱动过、且现在还偏着的参数，交给 step_retract 逐帧拉回去。

        labels 是一串 —— PROP_LEAD 串起来的组合有好几段，参数表要取并集。"""
        plan = []
        seen = set()
        for label in labels:
            for name in modelmap.MOTION_PARAMS.get(label, ()):
                if name in seen:
                    continue
                seen.add(name)
                if name in FOLLOW_NAMES or name in modelmap.PHYSICS_OUT \
                        or name == "ParamBreath":
                    # 这几类每帧都被别的子系统写：鼠标跟随、物理演算、自动呼吸。
                    # 它们自己会回到原位，用不着（也轮不到）我们收回。
                    continue
                i = self.idx.get(name)
                if i is None:
                    continue
                cur = self.mdl.GetParameterValue(i)
                dft = self.mdl.GetParameterDefaultValue(i)
                if abs(cur - dft) > 1e-4:
                    plan.append((name, cur, dft))
        if plan:
            self.retract = [plan, RETRACT_FADE_SEC]

    def step_retract(self, dt):
        """把正要收回的参数往默认值拉。拉的是**基准值**，表情是之后才叠加上去的，
        所以正开着的装扮不会跟着一起被拉走。"""
        if self.retract is None:
            return
        plan, left = self.retract
        left -= dt
        k = 0.0 if left <= 0 else left / RETRACT_FADE_SEC
        for name, cur, dft in plan:
            self.mdl.SetAndSaveParameterValueById(name, dft + (cur - dft) * k, 1.0)
        self.retract = None if left <= 0 else [plan, left]

    def update_follow(self, dt):
        cur = QCursor.pos()
        scr = QApplication.primaryScreen().availableGeometry()
        center = self.geometry().center()
        # 以窗口中心为原点、半个屏幕为量程：光标到屏幕边缘时偏转最大
        nx = max(-1.0, min(1.0, (cur.x() - center.x()) / max(1.0, scr.width() * 0.5)))
        # Y 轴要翻符号。Qt 的屏幕坐标 y 朝下（y=0 在屏幕顶端），而作者那份 vtube.json
        # 是按 VTS 的鼠标输入约定调的（+1 = 光标在屏幕上方）。不翻的话鼠标往下移会算出
        # ny=+1，喂给 ParamAngleY 就是 +30（抬头）—— 你在下、她抬头看你。
        # 受影响的都是"上下"类参数（AngleY / EyeBallY / pointY / danbaoY / BodyAngleY），
        # 一次翻转全部对上。X 轴两边约定一致，不用动。
        ny = max(-1.0, min(1.0, (center.y() - cur.y()) / max(1.0, scr.height() * 0.5)))
        src = {"x": nx, "y": ny}

        for pid, axis, ilo, ihi, olo, ohi, smooth in FOLLOW:
            if pid not in self.idx:
                continue
            t = (src[axis] - ilo) / (ihi - ilo) if ihi != ilo else 0.0
            target = olo + (ohi - olo) * t
            prev = self.follow_cur.get(pid, target)
            if smooth > 0:
                tau = smooth * 0.006
                a = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
            else:
                a = 1.0
            v = prev + (target - prev) * a
            self.follow_cur[pid] = v
            # SetAndSave 写在 Update 之前：Update 内部的 LoadParameters 会恢复基准，
            # 普通写会被擦掉；而每帧写绝对值不会累积。
            self.mdl.SetAndSaveParameterValueById(pid, v, 1.0)

    # ---------- 热键 ----------
    def poll_hotkeys(self):
        # 穿透逃生门。不放进 hk.HOTKEYS —— 那条表是 gen_hotkeys.py 从模型的
        # vtube.json 生成的，重跑一次就会被冲掉，而这条是我们自己加的。
        # 放在游戏模式判断**之前**：游戏模式静默的是作者那 48 条动作热键，
        # 这条是自救用的，任何时候都得留着 —— 否则穿透开着进游戏模式，
        # 托盘图标又被 Win11 折进隐藏区，就彻底锁死了。
        thru = all(pressed(k) for k in CLICK_THROUGH_KEYS)
        if thru and not self.held_thru:
            self.toggle_click_through(not self.click_through)
        self.held_thru = thru

        cur = set()
        for i, b in enumerate(hk.HOTKEYS):
            if all(pressed(k) for k in b["keys"]):
                cur.add(i)

        if self.game_mode:
            # 只更新「当前按着哪些键」，一条都不触发。这样在游戏里正按着
            # Alt+Z 的时候把游戏模式关掉，也不会立刻补触发一条 —— 否则
            # 「关掉游戏模式」这个动作本身就会让她蹦一下。
            self.held = cur
            return

        for i in cur - self.held:
            b = hk.HOTKEYS[i]
            # 走 apply_action，不走 fire —— 否则快捷键会绕过菜单那套
            # 「表情一次一条」。绕过的话，Alt+Z 戴墨镜再 Alt+D 脸红，或者
            # 右Ctrl+M 吐舌再按 Alt+Q 悲伤，两条表情会叠在同一批骨骼参数上
            # （ParamMouthForm 之类是加法），画面就是用户报的那种脏脸。
            # 作者那份 vtube.json 里的组合都是「装扮 + 动画」（蛋包饭 + 挤番茄
            # 酱、手机 + 自拍动画），那两类本来就可叠，所以这么改不影响它们。
            self.note_manual()
            self.apply_action(b["kind"], b.get("label"))
        self.held = cur

    def do_action(self, kind, label):
        """从「动作」菜单显式点选。行为见 apply_action。"""
        self.note_manual()
        self.apply_action(kind, label)

    def apply_action(self, kind, label):
        """落地一个动作。

        **表情一次只留一条，装扮可以叠。**

        点一条新表情时，把别的正开着的**表情**关掉，但**不动装扮** —— 头顶的
        鲸鱼、桌上的蛋包饭、眼镜贴纸、手上的画笔都留着，所以「戴墨镜 + 脸红」
        这种搭配能成立。

        为什么表情非关不可：Cubism 的表情是加法叠加的，上一条的贡献会一直挂在
        脸上。实测点「吐舌」再点「脸红」，吐舌的张嘴 (ParamMouthOpenY=0.756) 和
        舌头 (ParamCheek79=1.0) 原封不动地留着 —— 用户报的就是这个
        （"吐舌还有残留，会出现在别的表情上"）。

        同一条再点一下仍然是关掉它（开关语义），关的时候不清别人。
        哪条算「表情」、哪条算「装扮」，见 STACKABLE：那是从菜单分组推出来的，
        改菜单分组就等于改这里的行为。

        待机那条路也走这里 —— 这样"她自己在动"和"你点她"的观感是一致的；
        区别只在于待机演完会自己收回，见 idle_action。"""
        if kind != "expr" or label in self.active_expr:
            # 点的是动画，或点的是正开着的这一条（意思是关掉它）—— 都不清别人。
            self.fire({"kind": kind, "label": label})
            return
        if label not in STACKABLE:
            # 开一条新表情：先把别的表情关掉。list() 是快照 —— fire 会改
            # active_expr，边遍历边改会漏掉元素。
            for other in list(self.active_expr):
                if other not in STACKABLE:
                    self.fire({"kind": "expr", "label": other})
        self.fire({"kind": kind, "label": label})

    def reset_all(self):
        self.note_manual()
        self.fire({"kind": "reset"})

    # ---------- 待机 ----------
    def note_manual(self):
        """你自己动过（点动作 / 左键单击 / 全部归位）—— 推迟下一次待机，并作废
        还没执行的那次收回。

        作废收回是必须的：收回的逻辑是"把待机期间加上的东西摘掉、把它顶掉的
        东西开回来"，你要是在这 8 秒里点了左键（那条路是先全部归位），收回就
        会把你刚清掉的搭配又复活回来。以你的操作为准。"""
        self.idle_token += 1
        # idle_timer 在模型加载完之后才建（见 glInit 那一段），而 note_manual
        # 有可能在那之前被叫到，所以这里不直接取属性。
        t = getattr(self, "idle_timer", None)
        if t is not None:
            t.start(IDLE_INTERVAL_MS)

    def idle_action(self):
        """待机：每隔 IDLE_INTERVAL_MS 她自己做一个动作，演出 IDLE_HOLD_MS 后自己收回，
        **不动你手动搭好的搭配**。

        收回只碰我们自己改过的那两条线：
          · 我们加上去、现在还开着的   -> 关掉
          · 我们顶掉、现在还没开回来的 -> 开回来
        期间你手动动过的那条不管 —— 比如你顺手把她刚戴上的贴纸摘了，收回时
        不会又给你戴回去。真要在这 8 秒里手动操作了，note_manual 会把这次
        收回整个作废（见上）。"""
        if self.dragging or not self.isVisible():
            return
        picked = self.pick_random()
        if picked is None:
            return
        kind, label = picked
        if kind == "expr" and label in self.active_expr:
            # 抽到正开着的：apply_action 的开关语义会把它关掉，等于帮倒忙。
            return
        before = set(self.active_expr)
        self.apply_action(kind, label)
        log("待机", "演", str(label))            # 和用户自己点的区分开，方便翻日志
        added = self.active_expr - before        # 我们加上去的
        dropped = before - self.active_expr      # 被我们顶掉的
        if not added and not dropped:
            # 抽到的是动作：这里没什么可收的 —— 动作的收回由 play_motion 按它自己的
            # 时长排好了（原先这里写的是"动画自己会播完"，是错的：动作演完参数
            # 并不会自己回去，用户报的"嘴一直是吹泡泡"就是这么来的）。
            return
        self.idle_token += 1
        tok = self.idle_token
        QTimer.singleShot(IDLE_HOLD_MS, lambda: self.idle_restore(tok, added, dropped))

    def idle_restore(self, tok, added, dropped):
        if tok != self.idle_token:
            return                               # 你手动动过了，以你的为准
        log("待机", "收回")
        try:
            for label in added:
                if label in self.active_expr:     # 你自己关掉的就不管了
                    self.fire({"kind": "expr", "label": label})
            for label in dropped:
                if label not in self.active_expr:  # 你自己开回来的也不管了
                    self.fire({"kind": "expr", "label": label})
        except Exception:
            pass

    def fire(self, b):
        """把一件事落地。带道具前置的动作会连着前置一起排（见 play_action）。"""
        kind, label = b["kind"], b.get("label")
        log("动作", kind, label or "")
        try:
            if kind == "reset":
                self.model.ResetExpressions()
                self.active_expr.clear()
                # 「全部归位」也管动作：停掉正播的，把姿势清回原样。少了这一步，
                # 点了归位之后吹泡泡的嘴还留在脸上。凭据 +1 让排着队的那次收回作废。
                self.motion_token += 1
                self.motion_labels = []
                self.seq_exprs = []
                self.retract = None
                self.clear_pose()
                return
            self.play_action(kind, label)
        except Exception:
            pass

    def pick_random(self):
        """左键单击和待机共用的随机池。池子怎么来的见 RANDOM_EXCLUDE 上面那段。"""
        pool = [("expr", l) for l in modelmap.EXPR_ID if l not in RANDOM_EXCLUDE]
        pool += [("motion", l) for l in modelmap.MOTION
                 if l != "idle" and l not in RANDOM_EXCLUDE]
        if not pool:
            return None
        return random.choice(pool)

    def click_action(self):
        """左键单击：随机抽一个动作，先全部归位再播 —— 一次只留一个效果，连点也
        不会越点越花。池子见 RANDOM_EXCLUDE 上面那段。
        （原先是从 4 个动作里轮流，改成随机后不走 hk.CLICK_CYCLE 了。）

        注意这条路和菜单不一样：**它仍然先全部归位**，所以你手动搭的搭配会被
        清掉。这是之前定的（"抽到表情先全部归位再播，一次只留一个效果"），
        待机那条路才是不动搭配的。"""
        self.note_manual()
        picked = self.pick_random()
        if picked is None:
            return
        kind, label = picked
        self.last_pick = label          # 只用于排查，界面不显示
        self.fire({"kind": "reset"})
        self.fire({"kind": kind, "label": label})

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press_pos = e.globalPos()
            self.drag_from = self.pos()
            self.dragging = False
        elif e.button() == Qt.RightButton:
            self.menu().exec_(e.globalPos())

    def mouseMoveEvent(self, e):
        if self.press_pos is None:
            return
        d = e.globalPos() - self.press_pos
        if not self.dragging and (abs(d.x()) > DRAG_THRESHOLD or abs(d.y()) > DRAG_THRESHOLD):
            self.dragging = True
        if self.dragging:
            self.move(self.drag_from + d)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.dragging:
            x, y = self.x(), self.y()
            if not self.reachable(x, y):
                # 松手时她整个在屏幕外就再也抓不回来了 —— 右键菜单挂在窗口上，
                # 托盘图标还可能被 Win11 折进隐藏区。拖到边上、露半个身子都随你，
                # 但不许整个拖没。夹回来顺手把自己摆正，免得 config 里留着野坐标。
                x, y = self.clamp_to_screen(x, y)
                self.move(x, y)
            self.cfg["pos"] = [x, y]
            save_config(self.cfg)
        elif self.press_pos is not None:
            self.click_action()
        self.press_pos = None
        self.drag_from = None
        self.dragging = False

    # ---------- 菜单 ----------
    def menu(self):
        """菜单只建一次，弹出前用 sync_menu() 刷状态。不再是每次右键都新建 ——
        那样 QMenu(self) 挂在 pet 上不会释放，动作菜单这 52 个 QAction 会随着
        每一次右键累积，托盘右键尤其频繁。"""
        if self._menu is not None:
            return self._menu

        m = QMenu(self)
        # 隐藏只是把窗口收起来，进程留着 —— 从托盘能原样唤回，不用重新启动。
        # 文案在 sync_menu() 里跟着当前可见状态改。
        self.a_vis = m.addAction("隐藏桌宠", self.toggle_visible)

        act = m.addMenu("动作")
        # 归位放最上面：点花了第一反应是找它。
        act.addAction("全部归位", self.reset_all)
        act.addSeparator()
        for group, items in ACTION_MENU:
            # 组名把行为也写出来 —— 点下去会不会顶掉别人，光看名字猜不出来。
            sub = act.addMenu(GROUP_TITLE.get(group, group))
            for kind, label, title in items:
                if label in DEAD_ACTION:
                    title += "（模型里没效果）"
                a = QAction(title, sub)
                a.triggered.connect(lambda _=False, k=kind, l=label: self.do_action(k, l))
                if kind == "expr":
                    # 表情是开关语义，打勾显示当前开着的，再点一下就是关掉。
                    a.setCheckable(True)
                    self.expr_acts[label] = a
                sub.addAction(a)

        m.addSeparator()
        # 热键写在菜单项里 —— 穿透之后窗口点不到，这一条是唯一的自救线索，
        # 得让人在开启之前就看见。
        self.a_thru = QAction("点击穿透（右Ctrl+右Shift+P 随时切回）", m, checkable=True)
        self.a_thru.triggered.connect(self.toggle_click_through)
        m.addAction(self.a_thru)

        # 打游戏时 Alt+字母 / Alt+数字 / 光秃秃一个 E 会一直被当成热键，
        # 她就在游戏画面上乱做表情。这一条把作者那 48 条全静默。
        self.a_game = QAction("游戏模式（不响应快捷键）", m, checkable=True)
        self.a_game.triggered.connect(self.toggle_game_mode)
        m.addAction(self.a_game)

        self.a_top = QAction("始终置顶", m, checkable=True)
        self.a_top.triggered.connect(self.toggle_topmost)
        m.addAction(self.a_top)

        m.addSeparator()
        sub = m.addMenu("大小")
        grp = QActionGroup(sub)
        for name, div in SIZES:
            px = side_for_area_div(div)
            a = QAction("%s (1/%d 屏, %d×%d)" % (name, div, px, px), sub, checkable=True)
            a.triggered.connect(lambda _, d=div: self.resize_to(d))
            grp.addAction(a)
            sub.addAction(a)
            self.size_acts[div] = a

        m.addAction("回到右下角", self.reset_pos)

        m.addSeparator()
        self.a_auto = QAction("开机自启", m, checkable=True)
        self.a_auto.triggered.connect(self.toggle_autostart)
        m.addAction(self.a_auto)

        m.addSeparator()
        m.addAction("退出", self.quit)

        m.aboutToShow.connect(self.sync_menu)
        m.aboutToHide.connect(self.on_menu_hide)
        self._menu = m
        return m

    def sync_menu(self):
        """菜单弹出前刷一遍。状态可能在别处被改过（热键、托盘、拖动），
        所以勾选和文案一律现读，不走缓存。"""
        self.a_vis.setText("隐藏桌宠" if self.isVisible() else "显示桌宠")
        self.a_thru.setChecked(self.click_through)
        self.a_game.setChecked(self.game_mode)
        self.a_top.setChecked(self.topmost)
        self.a_auto.setChecked(autostart_enabled())
        for div, a in self.size_acts.items():
            a.setChecked(div == self.area_div)
        for label, a in self.expr_acts.items():
            a.setChecked(label in self.active_expr)

    def toggle_visible(self):
        if self.isVisible():
            self.hide_pet()
        else:
            self.show_pet()

    def toggle_click_through(self, on):
        self.click_through = on
        self.cfg["click_through"] = on
        self.apply_click_through()
        save_config(self.cfg)
        log("穿透 ->", on)

    def toggle_game_mode(self, on):
        """游戏模式：作者那 48 条动作热键全部静默。

        静默的是键盘那条路。左键单击和待机动作不受影响 —— 它们不吃键盘，
        误触不到，没必要一起关掉。
        逃生门（右Ctrl+右Shift+P）也不受影响，见 poll_hotkeys。
        """
        self.game_mode = on
        self.cfg["game_mode"] = on
        save_config(self.cfg)
        log("游戏模式 ->", on)

    def toggle_topmost(self, on):
        self.topmost = on
        self.cfg["topmost"] = on
        self.apply_topmost()
        save_config(self.cfg)

    def toggle_autostart(self, on):
        if not set_autostart(on) and on:
            self.tray.showMessage("开机自启", "请先用打包好的 EXE 运行再开启自启。")

    def reset_pos(self):
        self.cfg.pop("pos", None)
        self.place()
        save_config(self.cfg)

    def quit(self):
        log("退出")
        if self.model:
            self.model.StopAllMotions()
        self.hide()
        # 不显式收掉，Windows 上托盘区常留一个点不动的假图标，要等鼠标扫过才消失。
        tray = getattr(self, "tray", None)
        if tray:
            tray.hide()
        QApplication.quit()

    # ---------- 生命周期 ----------
    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.apply_click_through)
        QTimer.singleShot(0, self.apply_topmost)

    def closeEvent(self, e):
        # 任务栏右键"关闭窗口"和 Alt+F4 都走这里。托盘还在，且
        # setQuitOnLastWindowClosed(False)，不接管的话窗口消失了进程还活着、只剩个
        # 托盘图标，用户会以为没关掉。所以这里直接当作"退出"。
        e.accept()
        self.quit()

    def hide_pet(self):
        log("隐藏桌宠（进程还在跑）")
        self.hide()

    def show_pet(self):
        log("显示桌宠")
        self.show()
        self.apply_click_through()
        self.apply_topmost()


def set_app_id():
    """给进程一个固定身份，任务栏按钮才会稳定地用我们自己的图标。
    不设的话 Windows 按可执行文件路径临时认领，换个目录图标就可能变回默认白纸，
    "固定到任务栏"也会认成另一个程序。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DSWhalePet.DesktopPet")
    except Exception:
        pass


def main():
    rotate_log()

    if not claim_single_instance():
        # 别安静地退出。用户双击图标的意思是"我要看见它"，所以把已经在跑的
        # 那个叫出来，见 wake_existing 上面的说明。
        ok = wake_existing()
        log("已有实例在跑，叫醒%s，本次启动直接结束" % ("成功" if ok else "失败（没找到窗口）"))
        return 0

    # 原生层的访问违例会被 Python 的 try/except 完全漏掉 —— 上回那次"闪退"
    # 既没有 crash log 也没有事件查看器记录，就是因为崩在 C++ 里。
    # faulthandler 能接住这种死法并把 native 栈写进 pet_crash.log。
    global _crash_fh
    try:
        ensure_data_dir()
        _crash_fh = open(CRASH, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_crash_fh, all_threads=True)
    except Exception:
        pass

    log("启动 单文件=%s" % getattr(sys, "frozen", False))
    set_app_id()

    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    live2d.init()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    ensure_data_dir()
    migrate_config()
    cfg = load_config()
    pet = Pet(cfg)
    pet.place()

    icon = QIcon(ICON)
    app.setWindowIcon(icon)          # 任务栏/Alt+Tab 用这个图标
    pet.tray = QSystemTrayIcon(icon, app)
    pet.tray.setToolTip("DS鲸鱼娘桌宠")
    # 菜单只建一次并一直复用；勾选和文案由 menu 自己的 aboutToShow → sync_menu 刷新，
    # 所以这里不需要每次右键重建。
    pet.tray.setContextMenu(pet.menu())
    def on_tray(reason):
        # 左键单击或双击托盘图标：窗口若被隐藏就唤回来
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            pet.show_pet()

    pet.tray.activated.connect(on_tray)
    pet.tray.show()

    pet.show()
    code = app.exec()
    live2d.dispose()
    return code


def _redirect_streams():
    """打包成 --noconsole 后 stdout/stderr 是 None，任何 print 都会炸。
    live2d 的日志层会写 stdout，所以这里把它们接到文件上。"""
    if not getattr(sys, "frozen", False):
        return None
    ensure_data_dir()
    path = LOG
    try:
        fh = open(path, "a", encoding="utf-8", buffering=1)
    except Exception:
        return None
    if sys.stdout is None:
        sys.stdout = fh
    if sys.stderr is None:
        sys.stderr = fh
    return fh


if __name__ == "__main__":
    _redirect_streams()
    try:
        sys.exit(main())
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            ensure_data_dir()
            with open(CRASH, "a", encoding="utf-8") as fh:
                fh.write("\n=== %s ===\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), tb))
        except Exception:
            pass
        raise
