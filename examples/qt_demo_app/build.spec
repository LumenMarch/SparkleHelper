# -*- mode: python ; coding: utf-8 -*-
"""sparklehelper Qt Demo 的 PyInstaller 打包配置。

生成一个带 Sparkle.framework 与 SUFeedURL/SUPublicEDKey 的 macOS .app，
用于用 PySide6 验证 sparklehelper 的检查更新链路。

前置::

    uv pip install -e ".[demo-qt]"

打包::

    uv run pyinstaller build.spec

产出: ``dist/SparkleHelperQtDemo.app``
"""

block_cipher = None

a = Analysis(
    ["demo_qt.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # PySide6 与 sparklehelper 的 hook 自动收集 Qt 资源与 Sparkle.framework。
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir 模式：Sparkle.framework 由内置 PyInstaller hook 收集到 Contents/Frameworks。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SparkleHelperQtDemo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SparkleHelperQtDemo",
)

app = BUNDLE(
    coll,
    name="SparkleHelperQtDemo.app",
    icon=None,
    bundle_identifier="com.example.sparklehelper.qt-demo",
    codesign_identity="-",
    info_plist={
        "CFBundleName": "sparklehelper Qt Demo",
        "CFBundleIdentifier": "com.example.sparklehelper.qt-demo",
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
        "LSBackgroundOnly": False,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        # ---- Sparkle 配置 ----
        # TODO: 填入 appcast.xml 的公开 URL。
        "SUFeedURL": "https://example.com/appcast.xml",
        # TODO: 用 Sparkle generate_keys 生成 EdDSA 密钥，公钥填此。
        "SUPublicEDKey": "YOUR_EDDSA_PUBLIC_KEY_BASE64",
        "SUEnableAutomaticChecks": True,
        "SUScheduledCheckInterval": 86400,
    },
)
