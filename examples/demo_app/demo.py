"""sparklehelper 演示应用（PyInstaller 打包目标，wxPython GUI）。

最小可验证链路：
- wxPython 窗口 + Windows 主界面按钮 / macOS "Check for Updates…" 菜单项
- 构造 :class:`sparklehelper.Updater`，读 .app 的 Info.plist 配置
- macOS 用 KVO 订阅 ``can_check_for_updates``，据此启用/禁用入口
- 点击检查更新入口 → 弹出 Sparkle / WinSparkle 原生更新窗口

打包（见同目录 build.spec / README.md）::

    pyinstaller build.spec
    sparklehelper nuitka \
        --version 0.1.0 \
        --build-version 1 \
        --feed-url https://example.com/appcast.xml \
        --public-ed-key YOUR_EDDSA_PUBLIC_KEY_BASE64 \
        --mode=app \
        demo.py
"""

from __future__ import annotations

import sys


def _is_windows() -> bool:
    return sys.platform == "win32"


def main() -> int:
    import traceback

    # sparklehelper 只能在打包后的 .app 内运行；构造 Updater 前聚合检查。
    try:
        import wx
        from sparklehelper import Updater

        app = wx.App()
        updater = Updater(
            start=False,
            feed_url="https://example.com/appcast.xml",
            public_key="YOUR_EDDSA_PUBLIC_KEY_BASE64",
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()  # 终端打印完整堆栈
        # 此时 wx 可能未初始化，用最简方式报错。
        print(f"Failed to start updater: {exc}", file=sys.stderr)
        return 1

    frame = wx.Frame(None, title="sparklehelper Demo", size=(420, 240))
    panel = wx.Panel(frame)
    root = wx.BoxSizer(wx.VERTICAL)
    panel.SetSizer(root)

    intro = wx.StaticText(
        panel,
        label=(
            "sparklehelper 演示\n\n"
            "点击按钮检查更新。"
            if _is_windows()
            else "sparklehelper 演示\n\n从应用菜单选择 “Check for Updates…”。"
        ),
    )
    root.Add(intro, 0, wx.ALL, 20)

    check_update_button = wx.Button(panel, label="检查更新")
    check_update_button.Enable(False)
    if _is_windows():
        root.Add(check_update_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
    else:
        check_update_button.Hide()

    # ---- 菜单：Sparkle 期望更新项挂在应用菜单（macOS 自动把"App名"菜单放最前）----
    check_update_item = None
    if not _is_windows():
        menubar = wx.MenuBar()
        # 第 0 个菜单在 macOS 上会被映射为应用菜单（Apple menu）。
        app_menu = menubar.OSXGetAppleMenu()
        check_update_item = app_menu.Insert(
            1, wx.ID_ANY, "&Check Update\tCtrl-U", "Check for Updates…"
        )
        check_update_item.Enable(False)  # 初始禁用，由 KVO 解锁
        frame.SetMenuBar(menubar)

    def _on_check_updates(_event) -> None:
        updater.check_for_updates()

    check_update_button.Bind(wx.EVT_BUTTON, _on_check_updates)
    if check_update_item is not None:
        frame.Bind(wx.EVT_MENU, _on_check_updates, check_update_item)

    # 用 KVO 控制菜单项 enable 状态。
    def _set_update_enabled(can_check: bool) -> None:
        # wx 控件状态变更必须在 GUI 线程；KVO 回调本身在主线程，可直接调。
        check_update_button.Enable(bool(can_check))
        if check_update_item is not None:
            check_update_item.Enable(bool(can_check))

    subscription = None
    uses_can_check_observer = True
    try:
        subscription = updater.observe_can_check_for_updates(_set_update_enabled)
    except AttributeError:
        uses_can_check_observer = False

    # 延迟启动 updater：startUpdater 必须在 NSApplication run loop 启动后调用，
    # 否则 canCheckForUpdates 永远为 False。wx 的 MainLoop 驱动 NSApp run loop，
    # 用 CallAfter 在进入 MainLoop 后触发 start。
    def _start_updater_later() -> None:
        try:
            updater.start()
            if not uses_can_check_observer:
                _set_update_enabled(True)
        except Exception as exc:  # noqa: BLE001
            print(f"[demo] start error: {exc}", file=sys.stderr)

    wx.CallAfter(_start_updater_later)

    frame.Show()
    app.MainLoop()

    if subscription is not None:
        subscription.cancel()
    updater.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
