"""sparklehelper Qt 演示应用（PySide6 GUI）。

最小可验证链路：
- PySide6 窗口 + Windows 主界面按钮 / macOS 菜单项
- 构造 :class:`sparklehelper.Updater`，读取 .app 的 Info.plist 配置
- macOS 用 KVO 订阅 ``can_check_for_updates``，通过 Qt signal 更新入口状态
- 点击检查更新入口 → 弹出 Sparkle / WinSparkle 原生更新窗口

打包（见同目录 build.spec / README.md）::

    pyinstaller build.spec
"""

from __future__ import annotations

import sys


FEED_URL = "https://example.com/appcast.xml"
PUBLIC_KEY = "YOUR_EDDSA_PUBLIC_KEY_BASE64"


def _is_windows() -> bool:
    return sys.platform == "win32"


def main() -> int:
    import traceback

    try:
        from PySide6.QtCore import QObject, QTimer, Signal
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import (
            QApplication,
            QLabel,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )
        from sparklehelper import Updater

        class UpdateBridge(QObject):
            """把 sparklehelper 回调切回 Qt 对象信号。"""

            can_check_changed = Signal(bool)
            start_failed = Signal(str)

        app = QApplication(sys.argv)
        app.setApplicationName("sparklehelper Qt Demo")
        app.setOrganizationName("sparklehelper")
        bridge = UpdateBridge()
        updater = Updater(
            start=False,
            feed_url=FEED_URL,
            public_key=PUBLIC_KEY,
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"Failed to start updater: {exc}", file=sys.stderr)
        return 1

    window = QMainWindow()
    window.setWindowTitle("sparklehelper Qt Demo")
    window.resize(440, 240)

    central = QWidget(window)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(16)
    window.setCentralWidget(central)

    intro = QLabel(
        (
            "sparklehelper Qt 演示\n\n点击按钮检查更新。"
            if _is_windows()
            else "sparklehelper Qt 演示\n\n从菜单选择 “Check for Updates…”。"
        ),
        central,
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    layout.addStretch(1)

    check_update_button = QPushButton("检查更新", central)
    check_update_button.setEnabled(False)
    if _is_windows():
        layout.addWidget(check_update_button)
    else:
        check_update_button.hide()

    check_update_action = None
    if not _is_windows():
        menu = window.menuBar().addMenu("sparklehelper Qt Demo")
        check_update_action = QAction("Check for Updates...", window)
        check_update_action.setEnabled(False)
        menu.addAction(check_update_action)

    def _on_check_updates() -> None:
        updater.check_for_updates()

    check_update_button.clicked.connect(lambda _checked=False: _on_check_updates())
    if check_update_action is not None:
        check_update_action.triggered.connect(
            lambda _checked=False: _on_check_updates()
        )

    def _set_update_enabled(can_check: bool) -> None:
        enabled = bool(can_check)
        check_update_button.setEnabled(enabled)
        if check_update_action is not None:
            check_update_action.setEnabled(enabled)

    bridge.can_check_changed.connect(_set_update_enabled)
    bridge.start_failed.connect(
        lambda message: QMessageBox.warning(window, "sparklehelper", message)
    )

    subscription = None
    uses_can_check_observer = True
    try:
        subscription = updater.observe_can_check_for_updates(
            lambda can_check: bridge.can_check_changed.emit(bool(can_check))
        )
    except AttributeError:
        uses_can_check_observer = False

    def _start_updater_later() -> None:
        try:
            updater.start()
            if not uses_can_check_observer:
                bridge.can_check_changed.emit(True)
        except Exception as exc:  # noqa: BLE001
            print(f"[qt-demo] start error: {exc}", file=sys.stderr)
            bridge.start_failed.emit(str(exc))

    QTimer.singleShot(0, _start_updater_later)

    window.show()
    rc = app.exec()

    if subscription is not None:
        subscription.cancel()
    updater.cleanup()
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
