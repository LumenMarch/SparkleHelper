# -*- mode: python ; coding: utf-8 -*-
"""sparklehelper Demo 的 PyInstaller 打包配置。

生成一个带 Sparkle.framework 与 SUFeedURL/SUPublicEDKey 的 macOS .app，
用于端到端验证 sparklehelper 的检查更新链路。

前置::

    uv pip install -e ".[demo]"

打包::

    uv run pyinstaller build.spec

产出: ``dist/SparkleHelperDemo.app``

Sparkle.framework 由 sparklehelper 库内嵌 PyInstaller hook 从 wheel 收集。
SPARKLEHELPER_FRAMEWORK_PATH 可覆盖默认路径，无需联网或事后拷贝。
"""

import os

block_cipher = None

a = Analysis(
    ["demo.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # wx 与 sparklehelper 的 hook 自动收集依赖与 framework。
    hiddenimports=["wx"],
    # sparklehelper 通过 pyinstaller40 entry point 自动注册 hook-dirs，
    # 因此无需显式 --additional-hooks-dir 或 hookspath。
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir 模式：EXE 只含 scripts，COLLECT 铺到独立目录，BUNDLE 再包成 .app。
# Sparkle.framework 以真实目录结构存在于 Contents/Frameworks/。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SparkleHelperDemo",
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
    name="SparkleHelperDemo",
)

app = BUNDLE(
    coll,
    name="SparkleHelperDemo.app",
    icon=None,
    bundle_identifier="com.example.sparklehelper.demo",
    # codesign_identity="-" 对 .app 做 ad-hoc 签名（含内嵌 framework）。
    # 正式分发时改为 Developer ID Application 证书名称。
    codesign_identity="-",
    info_plist={
        "CFBundleName": "sparklehelper Demo",
        "CFBundleIdentifier": "com.example.sparklehelper.demo",
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
