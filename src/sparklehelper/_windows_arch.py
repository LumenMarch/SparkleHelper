"""Windows 进程架构（与 OS 原生架构无关）。

``platform.machine()`` 在 Windows 上报告物理 CPU / 原生 OS，Windows-on-ARM
上模拟的 x86_64 进程仍会得到 ``ARM64``。DLL 与 wheel tag 必须跟**当前进程**
一致，否则 ``LoadLibrary`` 返回 WinError 193。

本模块只依赖标准库，供运行时与 ``setup.py`` 共用。
"""

from __future__ import annotations

import struct
import sysconfig

# 源码树与 wheel 内 DLL 子目录名，也是 current_arch() 的返回值。
ARCHS = ("x64", "x86", "arm64")

_WHEEL_PLAT = {
    "x64": "win_amd64",
    "x86": "win32",
    "arm64": "win_arm64",
}


def current_arch() -> str:
    """返回当前进程匹配的 DLL 目录名：``"x64"`` / ``"x86"`` / ``"arm64"``。

    32 位进程一律 ``x86``（WinSparkle 无 ARM32 运行时）。64 位用
    ``sysconfig.get_platform()``（解释器构建目标，与 pip 选 wheel 同源），
    不用 ``platform.machine()``。
    """
    if struct.calcsize("P") * 8 == 32:
        return "x86"
    platform_name = sysconfig.get_platform().lower().replace("_", "-")
    if "arm64" in platform_name:
        return "arm64"
    return "x64"


def wheel_plat_name() -> str:
    """返回与 :func:`current_arch` 对应的 wheel 平台 tag。"""
    return _WHEEL_PLAT[current_arch()]
