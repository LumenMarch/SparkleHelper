"""sparklehelper —— Sparkle / WinSparkle 原生更新框架的 Python 运行时接口。

快速上手::

    from sparklehelper import Updater

    updater = Updater()                # 读 .app 的 Info.plist 配置
    updater.check_for_updates()        # 弹出平台原生更新窗口

详见 :class:`sparklehelper.updater.Updater`。
"""

from __future__ import annotations

from . import errors, types
from ._backend._macos import Decision, UpdaterDelegate
from .errors import (
    ConfigurationError,
    NotABundleError,
    SparkleError,
    SparkleNotAvailableError,
    UpdateCheckError,
    WrongThreadError,
)
from .types import (
    SystemProfileEntry,
    UpdateCheckKind,
    UpdateCheckResult,
    UpdateInfo,
    UserUpdateChoice,
    UserUpdateStage,
    UserUpdateState,
)
from .updater import Subscription, Updater, ensure_runnable

__version__ = "0.1.2"

__all__ = [
    "Updater",
    "UpdaterDelegate",
    "Decision",
    "Subscription",
    "ensure_runnable",
    "types",
    "errors",
    # dataclass 快捷导出
    "UpdateInfo",
    "SystemProfileEntry",
    "UpdateCheckKind",
    "UpdateCheckResult",
    "UserUpdateChoice",
    "UserUpdateStage",
    "UserUpdateState",
    # 异常快捷导出
    "SparkleError",
    "SparkleNotAvailableError",
    "NotABundleError",
    "ConfigurationError",
    "UpdateCheckError",
    "WrongThreadError",
    "__version__",
]
