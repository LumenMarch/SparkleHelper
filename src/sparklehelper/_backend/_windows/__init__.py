"""Windows 后端包：WinSparkle.dll 的 ctypes 桥接。

把 WinSparkle 的纯 C ``__cdecl`` API 按 ctypes 绑定拆分：

- :mod:`._loading`：DLL 定位（按进程架构选 x64/x86/arm64）+ ``ctypes.CDLL`` 加载
- :mod:`._bindings`：C API 函数的 ``restype`` / ``argtypes`` 签名定义
- :mod:`._backend`：:class:`WindowsBackend`（实现 UpdateBackend + WinSparkleExtras）

非 win32 安全
-------------
本包顶层不 import ``ctypes``。所有 ``import ctypes`` / ``CFUNCTYPE`` 延迟到
``_setup`` 内执行，保证非 win32 平台 ``import sparklehelper._backend._windows``
不会触发 ctypes 的 Win32 专用初始化。
"""

from __future__ import annotations

from ._backend import WindowsBackend

__all__ = ["WindowsBackend"]
