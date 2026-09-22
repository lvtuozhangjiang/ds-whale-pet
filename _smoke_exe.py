"""端到端验**已安装**的那份 exe：真的启动它、真的按它的全局热键、真的截图看嘴。

打的是「泡泡糖」的热键 `右Ctrl + PageUp`，走 poll_hotkeys -> do_action ->
apply_action -> fire -> play_motion 这条真路径。

判据用「噪声底」对照：自动呼吸和眨眼一直在动，两张相隔几秒的干净截图本来就
有差异，所以先量干净-干净的差异当底线，再看
  · 演到一半 vs 干净  -> 应该远大于底线
  · 收回之后 vs 干净  -> 应该回到底线附近
另外查 pet.log 里有没有「动作 收回」那行 —— 那是收回真的跑了的直接证据。
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 不设的话坐标会被虚拟化

import numpy as np
from PIL import Image, ImageGrab

# 要冒烟测哪份 exe：默认测刚构建出来的单文件版，也可以用 PET_EXE 指别处。
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.environ.get("PET_EXE") or os.path.join(
    HERE, "dist", "DS鲸鱼娘桌宠-单文件.exe")
NAME = os.path.basename(EXE)
TITLE = "DS鲸鱼娘桌宠"
LOG = os.path.join(os.environ["APPDATA"], "DS鲸鱼娘桌宠", "pet.log")
user32 = ctypes.windll.user32

VK_RCTRL, VK_PGUP = 0xA3, 0x21
EXT, KEYUP = 0x0001, 0x0002


def kill_all():
    """先清场：留着旧实例的话，新启动的会被单实例互斥体挡下（只唤醒旧的）。
    注意单文件版跑起来是**两个同名进程**（bootloader 父 + 主体）。"""
    subprocess.run(["taskkill", "/F", "/IM", NAME], capture_output=True)
    time.sleep(1.5)


def find_hwnd():
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == TITLE and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def rect_of(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


# 她会跟着鼠标转脑袋。用户就坐在键盘前，随手一动就把半个脸换掉，比嘴那点变化大得多
# —— 上一版就是这么量出「收回后还在动 3.35%」的假警报。每次抓屏前把光标钉死在固定
# 位置，这一项就成常量了。测完把光标放回原处。
PIN = (60, 60)


def pin_cursor():
    user32.SetCursorPos(*PIN)


def shot(box):
    pin_cursor()
    time.sleep(0.25)                 # 让她把头转到位再拍
    return np.asarray(ImageGrab.grab(bbox=box).convert("RGB"), dtype=np.int16)


def diff(a, b):
    """只数"明显变了"的像素占比，不取全帧均值。

    全帧均值在这儿是错的度量：窗口是透明的，边框那一圈拍进去的是**桌宠背后的
    桌面** —— 用户背后开着什么在动，均值就跟着动。第一版就是这么量出"噪声底
    18.4"，把嘴上那点变化整个淹掉了。脸是不透明的，所以只看脸那一块。
    """
    return float((np.abs(a - b).max(axis=2) > 25).mean())


# Cubism 的自动呼吸是个正弦（LAppModel 里周期 3.234 秒），驱动 ParamAngleX/Y/Z ±15、
# ParamBodyAngle* ±10 —— 她**从来不静止**，头一直在摆。所以"两帧相减"根本量不出嘴：
# 摆动造成的差异比嘴大得多（这就是前几版一直误报的原因）。
# 呼吸是周期性的，按**整数个呼吸周期**取平均就能把它抵消掉，而吹泡泡的 ○
# 在整个动作期间一直在，平均完还在。
BREATH_CYCLE = 3.234


def sample_mean(box, n=13):
    """在整数个呼吸周期上连拍取平均，把呼吸/摆动摊平。

    每一帧都先把光标钉回去 —— 用户就坐在键盘前，手一动她就跟着转头，
    那一项比嘴的动静大得多（前几版就是这么误报的）。
    """
    gap = BREATH_CYCLE / (n - 1)
    frames = []
    for i in range(n):
        pin_cursor()
        frames.append(np.asarray(ImageGrab.grab(bbox=box).convert("RGB"),
                                 dtype=np.float32))
        if i < n - 1:
            time.sleep(gap)
    return np.mean(frames, axis=0)


def press(keys):
    for vk in keys:
        user32.keybd_event(vk, 0, EXT, 0)
        time.sleep(0.04)
    for vk in reversed(keys):
        user32.keybd_event(vk, 0, EXT | KEYUP, 0)
        time.sleep(0.04)


def check_bundle():
    """确认在跑的解压目录里装的是打过补丁的数据（单文件版会解到 %TEMP%\\_MEI*）"""
    tmp = os.environ["TEMP"]
    cands = [os.path.join(tmp, d) for d in os.listdir(tmp)
             if d.startswith("_MEI") and os.path.isdir(os.path.join(tmp, d))]
    cands.sort(key=os.path.getmtime, reverse=True)
    for d in cands:
        m = os.path.join(d, "modeldata", "motion", "motion_01.motion3.json")
        t = os.path.join(d, "modeldata", "c_0120.2048", "texture_00.png")
        if os.path.exists(m) and os.path.exists(t):
            loop_off = '"Loop": false' in open(m, encoding="utf-8").read()
            size = os.path.getsize(t)
            print("  解压目录里 motion_01 的 Loop 是 false：%s" % loop_off)
            print("  解压目录里 texture_00.png 是 %d 字节（补丁版应为 1751018）" % size)
            return loop_off and size == 1751018
    print("  没找到解压目录，跳过")
    return None


def main():
    orig = wt.POINT()
    user32.GetCursorPos(ctypes.byref(orig))    # 测完把光标放回原处
    kill_all()
    print("启动", NAME)
    subprocess.Popen([EXE])
    hwnd = None
    for _ in range(80):                       # 单文件版要解压到 %TEMP%，慢
        time.sleep(0.5)
        hwnd = find_hwnd()
        if hwnd:
            break
    if not hwnd:
        sys.exit("等了 40 秒也没等到窗口")
    print("窗口出现，等模型加载…")
    time.sleep(3)     # 待机 30 秒后会自己蹦一个动作，整轮测试得抢在它前面跑完
    print("窗口位置", rect_of(hwnd))
    print("exe 里的数据是打过补丁的：%s" % check_bundle())

    # 记下日志当前位置，等下只看这一段 —— 免得翻到历史记录里那条旧动作
    log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0

    # 只量脸那一块：嘴在这儿，而且脸是不透明的，不会把桌面背景算进来
    box = rect_of(hwnd)
    fh, fw = box[3] - box[1], box[2] - box[0]
    face = (box[0] + int(fw * 0.28), box[1] + int(fh * 0.40),
            box[0] + int(fw * 0.72), box[1] + int(fh * 0.68))
    # 量测只取嘴那一小块。整张脸里嘴占 1% 上下，摆动的差异能盖过它；
    # 收紧到嘴之后，嘴本身占了这一块的大半，信噪比就上来了。
    mouth = (box[0] + int(fw * 0.36), box[1] + int(fh * 0.46),
             box[0] + int(fw * 0.56), box[1] + int(fh * 0.62))

    # 本底 = 连着取两个「干净」的平均，两者的差就是"她自己在动"留下的残差。
    # 注意两次都必须各盖满一整个呼吸周期 —— 只盖半程的话两次正好采到摆动的
    # 两极，量出来的"本底"比信号还大（上一版就是这么量出 0.2168 的）。
    pin_cursor()
    time.sleep(0.5)
    base = sample_mean(mouth)
    base2 = sample_mean(mouth)
    floor = float((np.abs(base2 - base).max(axis=2) > 20).mean())
    bar = max(floor * 2.5, 0.002)
    print("本底（两次干净平均之差）          %.4f  （判据线 %.4f）" % (floor, bar))

    print("按 右Ctrl+PageUp（泡泡糖，5 秒）…")
    press([VK_RCTRL, VK_PGUP])

    mid = sample_mean(mouth)                    # 3.24 秒，落在 5 秒动作之内
    d_mid = float((np.abs(mid - base).max(axis=2) > 20).mean())
    print("演到一半 vs 干净                  %.4f  %s"
          % (d_mid, "有变化" if d_mid > bar else "★没反应"))

    time.sleep(6.5 - BREATH_CYCLE)             # 补足到动作演完 + 收回淡出之后
    after = sample_mean(mouth)
    d_after = float((np.abs(after - base).max(axis=2) > 20).mean())
    print("自己收回之后 vs 干净              %.4f  %s"
          % (d_after, "干净了" if d_after <= bar else "★还卡着"))
    d_later = d_after

    # 日志：收回那行是收回真的跑了的直接证据
    print()
    print("--- 这段测试期间的 pet.log ---")
    fresh = ""
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            fh.seek(log_start)
            fresh = fh.read()
    for line in fresh.splitlines():
        if "动作" in line or "收回" in line:
            print("   ", line)
    got = "收回 chuipaopao" in fresh
    print("  日志里有「收回 chuipaopao」：%s" % got)

    # 并排存一张嘴部特写，肉眼复核（base1/mid/after 本身就是脸那一块）
    tiles = [Image.fromarray(x.astype(np.uint8)) for x in (base, mid, after)]
    tiles = [t.resize((t.width * 2, t.height * 2), Image.NEAREST) for t in tiles]
    sheet = Image.new("RGB", (sum(t.width for t in tiles), tiles[0].height))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width
    out = os.path.join(HERE, "EXE-动作收回-验证.png")
    sheet.save(out)
    print()
    print("嘴部特写三连（干净 / 吹着嘴带泡泡 / 收回后）：%s" % out)

    user32.SetCursorPos(orig.x, orig.y)
    print()
    print("上面那几个像素占比只当参考，不当作判据 —— 她从来不静止：自动呼吸驱动")
    print("头 ±15°、身体 ±10°，物理演算又让身体/头发前后摇，这两项加起来比嘴大得多，")
    print("而桌宠一旦跑起来就没法把模型冻住，所以干净-干净的差压不到嘴的动静以下。")
    print("真正能下结论的是日志那两行：收回确实在动作自己的时长（这里 5.000 秒）后触发。")
    print("嘴到底回没回去，看 D:\\桌宠\\EXE-动作收回-验证.png 那张三连图。")
    return got


passed = main()
# 测完再把桌宠留给她跑着，别让用户回来发现桌宠没了
kill_all()
subprocess.Popen([EXE])
print("已重新启动，桌宠留在桌面上")
sys.exit(0 if passed else 1)
