"""WinSparkle.dll 的运行时加载（进程级单例缓存）。

WinSparkle 是纯 C ``__cdecl`` 库，提供 x64 / x86 / arm64 三套预编译 DLL。
本模块按当前进程架构选择匹配的 DLL，解析其磁盘路径，并 ``ctypes.CDLL``
加载。加载一次后缓存到模块级，避免重复加载与句柄泄漏。

DLL 路径解析优先级（见 :func:`resolve_winsparkle_path`）：
    1. 显式传入的 ``dll_path``
    2. 环境变量 ``SPARKLEHELPER_WINSPARKLE_PATH``
    3. 主可执行文件同目录（PyInstaller / Nuitka 打包后 DLL 与 exe 并排）
    4. Nuitka ``__compiled__.containing_dir`` 下的 ``WinSparkle.dll``
    5. PyInstaller 内部目录（onedir 下通常是 ``_internal/WinSparkle.dll``）
    6. wheel 内置的 ``winsparkle/<arch>/WinSparkle.dll``

非 win32 安全
-------------
本模块顶层不 import ``ctypes``（避免非 win32 平台导入时拉起 ctypes 的
Win32 相关初始化）。``import ctypes`` 延迟到 :func:`load_winsparkle` 内。
"""

from __future__ import annotations

import os
import platform
import struct
import sys
from typing import Optional

from ...errors import SparkleNotAvailableError

# ---------------------------------------------------------------------------
# 进程级缓存
# ---------------------------------------------------------------------------

_winsparkle_dll = None
"""已加载的 WinSparkle.dll 句柄（``ctypes.CDLL``）。"""

_winsparkle_path: Optional[str] = None
"""已加载 DLL 的磁盘路径，便于诊断与测试。"""


# ---------------------------------------------------------------------------
# 架构选择
# ---------------------------------------------------------------------------


def current_arch() -> str:
    """返回当前进程匹配的 DLL 架构目录名：``"x64"`` / ``"x86"`` / ``"arm64"``。

    按进程的指针宽度（而非 OS）判断：32 位 Python 进程跑在 64 位 Windows 上
    必须加载 x86 DLL，反之亦然——DLL 架构必须与宿主进程一致，否则
    ``LoadLibrary`` 会失败（错误码 193）。
    """
    machine = platform.machine().lower()
    # Windows on ARM：machine 返回 "arm64" / "aarch64"。
    if machine in ("arm64", "aarch64") or "arm" in machine:
        return "arm64"
    bits = struct.calcsize("P") * 8
    return "x64" if bits == 64 else "x86"


# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------


def _nuitka_containing_dir() -> Optional[str]:
    """返回 Nuitka 编译产物根目录；普通 Python 运行时返回 None。

    Nuitka 将 ``__compiled__`` 注册为 builtin module，必须通过 import 访问。
    ``globals().get("__compiled__")`` 仅在 Python 3.11 + standalone +
    非 package 模块时被 Nuitka 预注入 globals，其他条件下返回 None。
    """
    try:
        import __compiled__  # noqa: F821
    except ImportError:
        return None
    containing_dir = getattr(__compiled__, "containing_dir", None)
    if not containing_dir:
        return None
    return os.fspath(containing_dir)


def resolve_winsparkle_path(explicit: Optional[str] = None) -> str:
    """按优先级解析 WinSparkle.dll 的磁盘路径。

    返回绝对路径字符串。无法解析时抛
    :class:`~sparklehelper.errors.SparkleNotAvailableError`。

    优先级（与 macOS 的 Sparkle.framework 解析对齐）：
        1. ``explicit`` 显式路径
        2. 环境变量 ``SPARKLEHELPER_WINSPARKLE_PATH``
        3. 主可执行文件同目录（打包场景，DLL 与 exe 并排）
        4. Nuitka ``__compiled__.containing_dir`` 下的 ``WinSparkle.dll``
        5. PyInstaller 内部目录（onedir 下通常是 ``_internal``）
        6. wheel 内置（按 :func:`current_arch` 选子目录）
    """
    if explicit:
        path = os.path.expanduser(explicit)
        if os.path.isfile(path):
            return os.path.abspath(path)
        raise SparkleNotAvailableError(
            f"Specified WinSparkle.dll path does not exist: {path}"
        )

    env_path = os.environ.get("SPARKLEHELPER_WINSPARKLE_PATH")
    if env_path:
        path = os.path.expanduser(env_path)
        if os.path.isfile(path):
            return os.path.abspath(path)
        raise SparkleNotAvailableError(
            f"SPARKLEHELPER_WINSPARKLE_PATH points to non-existent path: {path}"
        )

    arch = current_arch()

    # 打包场景：WinSparkle.dll 与主可执行文件并排。
    exe_dir = os.path.dirname(sys.executable)
    nuitka_containing_dir = _nuitka_containing_dir()
    if exe_dir:
        candidate = os.path.join(exe_dir, "WinSparkle.dll")
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    if nuitka_containing_dir:
        candidate = os.path.join(nuitka_containing_dir, "WinSparkle.dll")
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    pyinstaller_dir = getattr(sys, "_MEIPASS", None)
    if pyinstaller_dir:
        candidate = os.path.join(pyinstaller_dir, "WinSparkle.dll")
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    # wheel 内置：winsparkle/<arch>/WinSparkle.dll
    from ..._framework import bundled_winsparkle_path

    bundled = bundled_winsparkle_path(arch)
    if bundled.is_file():
        return str(bundled)

    raise SparkleNotAvailableError(
        f"WinSparkle.dll not found for architecture {arch!r}. "
        f"Checked: explicit path, SPARKLEHELPER_WINSPARKLE_PATH env, "
        f"exe dir ({exe_dir}), Nuitka containing dir ({nuitka_containing_dir}), "
        f"PyInstaller internal dir ({pyinstaller_dir}), "
        f"bundled ({bundled}). "
        "Reinstall sparklehelper or provide an explicit DLL path."
    )


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------


def load_winsparkle(dll_path: Optional[str] = None):
    """加载 WinSparkle.dll 并返回 ``ctypes.CDLL`` 句柄。幂等。

    重复调用返回第一次加载的结果（忽略后续的 ``dll_path``）。

    Raises:
        SparkleNotAvailableError: 非 win32 或找不到 DLL。
    """
    global _winsparkle_dll, _winsparkle_path
    if _winsparkle_dll is not None:
        return _winsparkle_dll

    if sys.platform != "win32":
        raise SparkleNotAvailableError(
            "WinSparkle is Windows-only (current platform: %s)" % sys.platform
        )

    path = resolve_winsparkle_path(dll_path)

    import ctypes

    # CDLL：__cdecl 调用约定（WinSparkle 全部导出都是 __cdecl）。
    # WinDLL 用 stdcall，32 位 Windows 上栈清理不匹配会崩溃。
    _winsparkle_dll = ctypes.CDLL(path)
    _winsparkle_path = path
    return _winsparkle_dll


def get_winsparkle():
    """返回已加载的 WinSparkle.dll；未加载则惰性触发 :func:`load_winsparkle`。"""
    if _winsparkle_dll is None:
        return load_winsparkle()
    return _winsparkle_dll


def is_loaded() -> bool:
    """WinSparkle.dll 是否已成功加载。"""
    return _winsparkle_dll is not None


def loaded_path() -> Optional[str]:
    """已加载 DLL 的磁盘路径；未加载时为 None。"""
    return _winsparkle_path


def reset_for_test() -> None:
    """仅供测试：清空模块级缓存。"""
    global _winsparkle_dll, _winsparkle_path
    _winsparkle_dll = None
    _winsparkle_path = None


__all__ = [
    "current_arch",
    "resolve_winsparkle_path",
    "load_winsparkle",
    "get_winsparkle",
    "is_loaded",
    "loaded_path",
    "reset_for_test",
]
