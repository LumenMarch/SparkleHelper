# 1. sparklehelper Qt Demo App

用 PySide6 打包一个最小可验证的 Qt GUI，端到端跑通
"检查更新 → 弹出 Sparkle / WinSparkle 原生窗口"链路。

## 2. 前置依赖

```bash
uv pip install -e ".[demo-qt]"
```

## 3. 为什么用 PySide6

Sparkle 依赖 **NSApplication run loop** 处理异步检查与 UI。PySide6 的 Qt
Cocoa 后端会驱动 NSApp run loop，因此适合验证 Python Qt GUI 与 Sparkle 的协同。

Qt demo 与 wx demo 的差异：

- PySide6 使用 `QApplication.exec()` 驱动事件循环。
- `Updater.start()` 通过 `QTimer.singleShot(0, ...)` 延迟到事件循环启动后调用。
- `can_check_for_updates` 回调通过 Qt `Signal` 更新按钮或菜单状态。

## 4. 打包

### 4.1. PyInstaller onedir

```bash
uv run pyinstaller build.spec
# 产出: dist/SparkleHelperQtDemo.app
```

onedir spec 使用 `BUNDLE(coll, ...)`，Sparkle.framework 由 sparklehelper
内置 PyInstaller hook 自动收集到 `Contents/Frameworks`。

### 4.2. PyInstaller onefile

如果生成 onefile `.app` spec（形如 `BUNDLE(exe, ...)`），使用 wrapper：

```bash
uv run sparklehelper pyinstaller demo_qt.spec
```

wrapper 会临时修补 spec，把 Sparkle.framework 直接传给 `BUNDLE`，避免它进入
运行时 `_MEI...` 临时目录。直接用 `pyinstaller` 构建 onefile `.app` 时，hook
会中止并提示使用 wrapper。

## 5. 验证

```bash
open dist/SparkleHelperQtDemo.app
# macOS: 从菜单选择 "Check for Updates..." → 应弹出 Sparkle 原生更新窗口
# Windows: 点击主界面的"检查更新"按钮 → 应弹出 WinSparkle 原生更新窗口
```
