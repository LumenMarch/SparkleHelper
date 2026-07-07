"""平台后端选择器。

按 ``sys.platform`` 选择并返回一个 :class:`~sparklehelper._backend.base.UpdateBackend`
实现。后端类的 import 放在函数体内（惰性），保证：

- 非 darwin / 非 win32 平台 ``import sparklehelper._backend`` 本身不失败；
- 目标平台才 import 对应后端模块（macOS 不 import ctypes win32，Windows
  不 import PyObjC），避免拉起无关的平台依赖。

后端类尚未全部实现时，调用 ``get_backend`` 在对应平台会抛
:class:`~sparklehelper.errors.SparkleNotAvailableError`，这是预期行为。
"""

from __future__ import annotations

import sys

from ..errors import SparkleNotAvailableError

from .base import (
    Callbacks,
    SparkleExtras,
    UpdateBackend,
    UpdateConfig,
    WinSparkleExtras,
)

__all__ = [
    "get_backend",
    "UpdateBackend",
    "UpdateConfig",
    "Callbacks",
    "SparkleExtras",
    "WinSparkleExtras",
]


def get_backend() -> UpdateBackend:
    """返回当前平台的更新后端实例。

    :raises SparkleNotAvailableError: 当前平台不支持，或对应后端模块缺失。
    """
    platform = sys.platform
    if platform == "darwin":
        from ._macos import MacOSBackend

        return MacOSBackend()
    if platform == "win32":
        from ._windows import WindowsBackend

        return WindowsBackend()
    raise SparkleNotAvailableError(
        f"sparklehelper 不支持当前平台: {platform}（仅支持 macOS / Windows）"
    )
