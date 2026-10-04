# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：voice-excel（文件夹模式 onedir）。

用法：
    .venv\\Scripts\\python.exe -m PyInstaller --clean --noconfirm voice-excel.spec

产物：
    dist/voice-excel/voice-excel.exe      主程序
    dist/voice-excel/_internal/           依赖与静态资源
    dist/funasr_model.zip                 模型（由打包脚本单独生成，见 build.py）
"""

from PyInstaller.utils.hooks import collect_all

# ---------- 数据 / 二进制 / 隐藏导入 ----------
datas = []
binaries = []
hiddenimports = []

# 前端静态资源
datas += [("static", "static")]

# funasr / modelscope 大量使用 register 装饰器 + pkgutil 动态发现子模块，
# 必须全量子模块作为 hiddenimports 收集，并把非 .py 数据文件一并打入。
for pkg in ("funasr", "modelscope", "modelscope_hub", "kaldiio", "soundfile", "jieba", "sentencepiece"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # 单个包收集失败不应阻断整体
        print(f"[spec] collect_all({pkg}) failed: {e}")

# 常见动态导入兜底
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明确用不到的 GUI / 开发工具，减体积
        "tkinter",
        "pytest",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "IPython",
        "jupyter",
        "notebook",
        "matplotlib",
        "pandas",
        # 注意：不要排除 unittest / doctest / pydoc —— torch 等库在导入时会用到
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voice-excel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 控制台程序：需打印启动信息并支持 Ctrl+C
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="voice-excel",
)