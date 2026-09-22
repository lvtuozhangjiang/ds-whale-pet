# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller 打包配置：DS鲸鱼娘桌宠.exe
#
# 用 onedir（不是 onefile）：启动快，出问题时能直接翻 _internal 里的东西排查。
#
# 两个关键点：
#  1. live2d 运行时要读 v3/FrameworkShaders/ 下的 10 个着色器文件，而目录是按
#     live2d/v3/__init__.py 的所在位置推出来的（init() 里的 init_internal）。
#     所以这些文件必须原样落在 _MEIPASS/live2d/v3/FrameworkShaders/ 下。
#     collect_all 会把它们按包内相对路径放好，正好满足。
#  2. live2d/v3/__init__.py 里 `from .params import *` 带了一句
#     "pyinstaller may not find it (hidden import)" —— 作者自己踩过，必须显式声明。

from PyInstaller.utils.hooks import collect_all

datas = [("modeldata", "modeldata")]
binaries = []
hiddenimports = ["live2d.v3.params"]

_d, _b, _h = collect_all("live2d")
datas += _d
binaries += _b
hiddenimports += _h

a = Analysis(
    ["pet.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "pandas",
              "PyQt5.QtWebEngineWidgets", "PyQt5.QtBluetooth", "PyQt5.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DS鲸鱼娘桌宠",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 不弹黑框；崩溃信息走 pet_crash.log
    disable_windowed_traceback=False,
    icon="icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DS鲸鱼娘桌宠",
)
