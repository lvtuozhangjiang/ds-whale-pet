"""在桌面建一个启动桌宠的快捷方式。

用 win32com 而不是 PowerShell：路径里有中文，PowerShell 传参容易踩编码。
"""

import os
import sys

import win32com.client

sys.stdout.reconfigure(encoding="utf-8")

DESKTOP = os.path.join(os.environ["USERPROFILE"], "Desktop")
# 默认给刚构建出来的单文件版建快捷方式；要指别处就设 PET_EXE。
EXE = os.environ.get("PET_EXE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dist", "DS鲸鱼娘桌宠-单文件.exe")
LNK = os.path.join(DESKTOP, "DS鲸鱼娘桌宠.lnk")

if not os.path.isfile(EXE):
    raise SystemExit("找不到 exe: " + EXE)

shell = win32com.client.Dispatch("WScript.Shell")
sc = shell.CreateShortCut(LNK)
sc.TargetPath = EXE
# 工作目录设成 exe 所在目录：配置和日志都写在那里，
# 不设的话从别处启动会落到当前目录，找起来麻烦。
sc.WorkingDirectory = os.path.dirname(EXE)
sc.IconLocation = EXE + ",0"        # exe 里已经嵌了 icon.ico
sc.Description = "DS鲸鱼娘 桌面宠物"
sc.Save()

print("已创建:", LNK)
print("指向  :", sc.TargetPath)
print("工作目录:", sc.WorkingDirectory)
print("图标  :", sc.IconLocation)

# 读回来确认真的落盘了，而不是只写进了内存对象
chk = shell.CreateShortCut(LNK)
print()
print("回读确认 ->", chk.TargetPath)
print("目标存在:", os.path.isfile(chk.TargetPath))
