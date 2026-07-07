# 1. sparklehelper Demo App

用 PyInstaller 打包一个最小可验证的 .app，端到端跑通 sparklehelper 的
"检查更新 → 弹出 Sparkle / WinSparkle 原生窗口"链路。

## 2. 前置依赖

```bash
uv pip install -e ".[demo]"   # 含 wxPython + pyinstaller
```

## 3. 为什么用 wxPython（而非 tkinter）

Sparkle 依赖 **NSApplication run loop** 处理异步更新检查与 UI。GUI 框架必须
驱动这个 run loop，否则 `startUpdater` 后 `canCheckForUpdates` 永远为 False、
菜单项始终灰色。

- **wxPython** ✅ —— Cocoa 端口接管 `NSApplication`（实测创建的是
  `wxNSApplication` 子类），`MainLoop` 驱动 NSApp run loop，与 Sparkle 完全兼容。
- **tkinter** ❌ —— 用独立的 Tcl 事件循环，不与 NSApp run loop 协同。
  实测 `startUpdater` 返回后 tkinter 的 `after` 定时器全部停转，Sparkle 事件源卡死。
- **PyObjC/AppKit 原生**、**PyQt/PySide** ✅ —— 同样驱动 NSApp run loop，可用。

demo 选 wxPython 作为"纯 Python + 驱动 NSApp + 无需写原生 AppKit 代码"的折中。
Qt / PySide6 版本见 [`../qt_demo_app`](../qt_demo_app)。

## 4. 步骤

### 4.1. 内置 Sparkle.framework

sparklehelper wheel 已内置 Sparkle 2.9.3 universal2 framework，支持
macOS 11 及以上。PyInstaller 和 Nuitka 会直接收集该副本，
打包过程不访问网络。

### 4.2. 生成 EdDSA 密钥

Sparkle 用 EdDSA 签名更新包，appcast 引用公钥校验。

```bash
# 使用 Sparkle 官方 release 单独提供的命令行工具
/path/to/Sparkle/bin/generate_keys        # 生成密钥（写入钥匙串）
/path/to/Sparkle/bin/export_signing_tool  # 导出公钥
```

把导出的**公钥**填进 `build.spec` 的 `SUPublicEDKey`。

### 4.3. 托管 appcast.xml

把一个 appcast 文件放到可公开访问的 URL，并把该 URL 填进 `build.spec`
的 `SUFeedURL`。最小示例（注意 `sparkle:edSignature` 要用私钥对 dmg 签名得到）：

```xml
<?xml version="1.0" standalone="yes"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>sparklehelper Demo</title>
    <item>
      <title>Version 0.2.0</title>
      <pubDate>Mon, 23 Jun 2026 00:00:00 +0000</pubDate>
      <sparkle:version>2</sparkle:version>
      <sparkle:shortVersionString>0.2.0</sparkle:shortVersionString>
      <sparkle:edSignature>SIGNATURE_HERE</sparkle:edSignature>
      <enclosure
        url="https://example.com/SparkleHelperDemo-0.2.0.dmg"
        type="application/octet-stream"
        length="12345678"/>
    </item>
  </channel>
</rss>
```

签名更新包：

```bash
/path/to/Sparkle/bin/sign_update \
    ./SparkleHelperDemo-0.2.0.dmg
# 输出形如: edSignature="..." length=12345678
```

### 4.4. 打包

#### 4.4.1. PyInstaller

```bash
uv run pyinstaller build.spec
# 产出: dist/SparkleHelperDemo.app
```

**关于 Sparkle.framework 的收集**：sparklehelper 通过 `pyinstaller40`
entry point 注册库内嵌 hook（`src/sparklehelper/_pyinstaller/hook-sparklehelper.py`），
打包时自动完成内置 framework 的定位、遍历、符号链接保留与收集，无需在 spec 里
手动 `shutil.copytree` 或 `subprocess.run(['codesign',...])`。
hook 将 framework 实体文件按 Mach-O 检测分入 `binaries`/`datas`，
符号链接以 `SYMLINK` 类型保留。

PyInstaller 的 `collect_files_from_framework_bundles`（Analysis 阶段）
会补全 `Versions/Current`、顶层 `Sparkle`、`Resources` 等关键符号链接；
本 hook 同时显式追加剩余顶层符号链接覆盖所有情况。

BUNDLE 的 `codesign_identity="-"` 在打包完成后对 .app 做 ad-hoc 签名。
正式分发时改为 Developer ID Application 证书名称，并走 notarytool 公证流程。

如果使用 PyInstaller onefile `.app`（spec 形如 `BUNDLE(exe, ...)`），改用
wrapper 命令：

```bash
uv run sparklehelper pyinstaller demo.spec
```

wrapper 会临时修补 spec，把 Sparkle.framework 直接传给 `BUNDLE`，避免它进入
运行时 `_MEI...` 临时目录。onedir 的 `build.spec` 不需要 wrapper。若
onefile `.app` 直接用 `pyinstaller` 构建，hook 会中止并提示使用 wrapper。

#### 4.4.2. Nuitka

```bash
uv run sparklehelper nuitka \
  --version 0.1.0 \
  --build-version 1 \
  --feed-url https://example.com/appcast.xml \
  --public-ed-key YOUR_EDDSA_PUBLIC_KEY_BASE64 \
  --mode=app \
  demo.py
```

macOS 下 Sparkle 会位于 `Contents/Frameworks/Sparkle.framework`；Windows
下 WinSparkle 会位于 Nuitka dist 根目录的 `WinSparkle.dll`，运行时通过
Nuitka 的 `__compiled__.containing_dir` 定位。演示用的 pypylon
会保持自身的 loader-relative 布局，位于
`Contents/Frameworks/pypylon/pylon.framework`。
wrapper 会自动注入包内 Nuitka 配置与 plugin，并在签名前恢复 Sparkle
framework 的顶层 `Autoupdate` 符号链接。`--version` 会写入
`CFBundleShortVersionString`，未传且未透传 Nuitka 原生 `--macos-app-version`
时默认使用 `0.1.0`。`--build-version` 可选写入 Sparkle 使用的
`CFBundleVersion`；未传时会从 `--version` 自动推导，例如 `0.1.0` 会变成
构建版本 `1`；`--feed-url`、`--public-ed-key` 等选项会写入 Sparkle 的
Info.plist key。完整 key 可用 `--sparkle-key KEY=VALUE` 传入。仅透传 Nuitka
原生 `--macos-app-version` 且未传 wrapper 版本参数时，会读取 Nuitka 生成的
`CFBundleShortVersionString` 并补齐缺失的 `CFBundleVersion`。

### 4.5. 验证

```bash
open dist/SparkleHelperDemo.app
# macOS: 从应用菜单选 "Check for Updates…" → 应弹出 Sparkle 原生更新窗口
# Windows: 点击主界面的"检查更新"按钮 → 应弹出 WinSparkle 原生更新窗口
```

> 调试提示：直接 `python demo.py`（非 .app 内运行）会弹窗提示
> "无法启动更新器"——这是 `ensure_runnable()` 在主线程/bundle/plist
> 任一检查失败时的预期行为。必须走打包后的 .app 才能验证完整链路。

## 5. 代码签名与公证（分发前）

未签名的 .app 在用户机器上会被 Gatekeeper 拦截。分发前需：

1. 用 Developer ID Application 证书签名 .app（含内嵌 framework）。
2. 用 Sparkle 的 EdDSA（与 `SUPublicEDKey` 对应）签名更新包本身。
3. 提交 notarytool 公证，通过后 staple。

详见 Sparkle 官方文档：<https://sparkle-project.org/documentation/>
