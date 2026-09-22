# -*- mode: python ; coding: utf-8 -*-
#
# 单文件版：整包塞进一个 exe，方便直接发给别人（微信/QQ 传一个文件就行）。
#
# 和 build.spec 的区别只有一个：不生成 _internal 目录，所有东西内嵌在 exe 里。
# 代价是每次启动都要先把内容解压到 %TEMP%，启动比 onedir 慢。
# 先用它测出真实耗时，再决定分享版用哪个。

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
    a.binaries,          # onefile：库直接进 exe，不拆到 _internal
    a.datas,
    [],
    name="DS鲸鱼娘桌宠-单文件",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="icon.ico",
)
