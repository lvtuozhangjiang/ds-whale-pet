"""端到端验**已安装**的那份 exe：带道具的动作真会自己把道具弄出来、演完自己收。

打的是真热键，走 poll_hotkeys -> fire -> play_action -> run_steps 这条真路径。

判据是 pet.log 里的两行：
  · 「动作 motion/expr <label>」—— 开演了
  · 「收回 <串>`」—— 收回排上了，而且盖的是整串（含道具那几步）
从开演到收回应当等于这一串的总时长，不是正片自己的时长。
秒数比截图靠谱 —— 她从来不静止（呼吸 + 物理演算 + 自动眨眼），像素差分不出东西。

**游戏模式会把 48 条热键全静音**（那是它的用途），所以开着的时候这个测试
按不动她。脚本会先把 game_mode 临时关掉、测完把 config.json 原样写回去 ——
用的是字节级备份，你的位置/大小/开关一个都不会变。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# 要测哪份 exe：默认测刚构建出来的单文件版。测别的（比如已经装到别处的那份）
# 就设环境变量 PET_EXE 指过去。
EXE = os.environ.get("PET_EXE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dist", "DS鲸鱼娘桌宠-单文件.exe")
NAME = os.path.basename(EXE)
TITLE = "DS鲸鱼娘桌宠"
APPDIR = os.path.join(os.environ["APPDATA"], "DS鲸鱼娘桌宠")
LOG = os.path.join(APPDIR, "pet.log")
CFG = os.path.join(APPDIR, "config.json")
user32 = ctypes.windll.user32

# hotkeys.py 里的真绑定。keys 是 vk 码。
CASES = [
    # 显示名,        keys,                    kind,    label,   收回日志,          时长
    ("快速自拍",   (0x65, 0x6E), "motion", "自拍",    "开盖+自拍",       4.30),
    ("挤番茄酱动画", (0x63, 0x6E), "motion", "番茄酱",  "番茄酱+蛋包饭",    5.00),
    ("手机换色",   (0x60, 0x62), "expr",   "手机换色", "开盖+手机换色",    4.00),
    ("魔爪换色",   (0x65, 0x6A), "expr",   "魔爪换色", "魔爪+魔爪换色",    3.00),
    # 这条是回归：它的 MOTION_PARAMS 原先手写漏了 Param74~77（星轨迹/锤子旋转/
    # 锤子X/兔兔耳朵），演完四个参数停在最后一帧。表已经改成从 motion3.json 生成。
    ("重锤出击",   (0xA3, 0x2E), "motion", "aidale",  "aidale",          4.77),
]


def kill_all():
    """单文件版跑起来是**两个同名进程**（bootloader 父 + 主体），都得清掉，
    不然新启动的会被单实例互斥体挡下，只是把旧的叫醒。"""
    subprocess.run(["taskkill", "/F", "/IM", NAME], capture_output=True)
    time.sleep(1.5)


def launch():
    subprocess.Popen([EXE])


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


def press_down(keys):
    """按住这一组键。poll_hotkeys 是轮询 GetAsyncKeyState，得同时按着；
    触发看的是按下沿，一直按着不会重复触发。"""
    for vk in keys:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)


def release(keys):
    for vk in reversed(keys):
        user32.keybd_event(vk, 0, 0x0002, 0)
        time.sleep(0.03)


def wait_window():
    hwnd = None
    for _ in range(80):                    # 单文件版要解压到 %TEMP%，慢
        hwnd = find_hwnd()
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        sys.exit("等了 40 秒也没等到窗口")
    time.sleep(3)                          # 等模型加载完


def one_case(name, keys, kind, label, want_back, want_span):
    """时刻不能用日志里那两行相减 —— 日志的时间戳只到秒（%H:%M:%S），
    4.30 秒的间隔会被读成 5.00 秒，判据直接失效。改成边按边盯日志文件，
    记「我第一次看见这一行」的墙上时刻，50ms 一轮，够分辨。"""
    log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    press_down(keys)
    fresh = ""
    t_play = t_back = None
    deadline = time.time() + want_span + 12
    while time.time() < deadline:
        time.sleep(0.05)
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            fh.seek(log_start)
            fresh = fh.read()
        if t_play is None and ("动作 %s %s" % (kind, label)) in fresh:
            t_play = time.time()
            release(keys)                  # 看见了就松手，别一直按着
        if ("收回 " + want_back) in fresh:
            t_back = time.time()
            break
    release(keys)

    got_play = t_play is not None
    got_back = t_back is not None
    print("  %-10s 开演 %-5s  收回「%s」%-5s"
          % (name, got_play, want_back, got_back), end="")
    if not (got_play and got_back):
        print("   ★缺日志")
        return False, fresh
    span = t_back - t_play
    ok = want_span - 0.4 <= span <= want_span + 0.5
    print("  实测 %.2fs（应 %.2fs）%s" % (span, want_span, "对" if ok else "★不对"))
    return ok, fresh


orig = open(CFG, "rb").read()
cfg = json.loads(orig)
need_flip = bool(cfg.get("game_mode"))
print("游戏模式：%s" % need_flip)
if need_flip:
    print("  游戏模式会把 48 条热键全静音，测之前先临时关掉，config.json 原样备份")

kill_all()
results = []
try:
    if need_flip:
        cfg["game_mode"] = False
        with open(CFG, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    launch()
    wait_window()
    print("  窗口已出现，模型已加载。开始逐个打热键：")
    for case in CASES:
        results.append(one_case(*case)[0])
        time.sleep(0.5)
finally:
    # 不管测成没测成，config.json 都得还原成原样（位置、大小、开关）
    if need_flip:
        with open(CFG, "wb") as fh:
            fh.write(orig)
        print()
        print("已把 config.json 还原（game_mode 回到 %s）" % json.loads(orig)["game_mode"])
    kill_all()
    launch()
    print("桌宠已重新启动")

print()
print("--- 这段测试期间的 pet.log ---")
start = 0
with open(LOG, encoding="utf-8", errors="replace") as fh:
    lines = fh.read().splitlines()
for line in lines[-40:]:
    if "动作" in line or "待机" in line:
        print("   ", line)

print()
print("结论：", "全部通过" if all(results) else "★没过 %s" % results)
sys.exit(0 if all(results) else 1)
