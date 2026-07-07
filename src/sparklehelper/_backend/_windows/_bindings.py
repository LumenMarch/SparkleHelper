"""WinSparkle C API 的 ctypes 签名定义。

把 ``winsparkle.h`` 的 C 函数声明成带 ``restype`` / ``argtypes`` 的 ctypes
函数，集中一处便于维护。``_setup(dll)`` 在 :meth:`WindowsBackend.configure`
加载 DLL 后调用一次。

调用约定
--------
WinSparkle 全部导出都是 ``__cdecl``，对应 ``ctypes.CDLL`` 与
``ctypes.CFUNCTYPE``。注意 **不能** 用 ``WinDLL`` / ``WINFUNCTYPE``——它们
是 stdcall 约定，32 位 Windows 上调用栈清理不匹配会导致崩溃。

类型映射要点（来自 ``winsparkle.h`` 实际签名）
----------------------------------------------
- ``const char *``  → ``c_char_p``  ：appcast URL、EdDSA key、HTTP 头、registry 路径
- ``const wchar_t *`` → ``c_wchar_p``：app_details(company/name/version)、build 版本
- ``int`` → ``c_int``
- ``time_t`` → 按进程位数：64 位进程 ``c_int64``，32 位 ``c_int32``。
  Windows 是 LLP64：64 位上 C ``long`` 仍是 32 位，而 ``time_t`` 是 64 位，
  故不能用 ``c_long``（见 :func:`_time_t_type`）。
- 回调全部是 ``void (__cdecl *)()``（无参无返回，含 can_shutdown 返回 int）

注意：``win_sparkle_set_app_details`` 的 3 个参数都是 ``wchar_t*``，
而 ``win_sparkle_set_appcast_url`` 是 ``char*``（UTF-8）——这是 WinSparkle
API 的历史不一致，ctypes 绑定必须分别处理。

非 win32 安全
-------------
本模块顶层不 import ``ctypes``。``import ctypes`` 与回调类型
（``CFUNCTYPE``）的创建都延迟到 :func:`_setup` 内。
"""

from __future__ import annotations

import struct

# 回调类型（进程级缓存，惰性创建；非 win32 上 _setup 被调用前为 None）。
_callback_type = None
_can_shutdown_callback_type = None


def get_callback_type():
    """``void (__cdecl *)()`` 回调类型（惰性创建，进程级缓存）。"""
    global _callback_type
    if _callback_type is None:
        import ctypes

        _callback_type = ctypes.CFUNCTYPE(None)
    return _callback_type


def get_can_shutdown_callback_type():
    """``int (__cdecl *)()`` 回调类型（can_shutdown 返回 BOOL，惰性缓存）。"""
    global _can_shutdown_callback_type
    if _can_shutdown_callback_type is None:
        import ctypes

        _can_shutdown_callback_type = ctypes.CFUNCTYPE(ctypes.c_int)
    return _can_shutdown_callback_type


def _time_t_type():
    """按进程位数返回 ``time_t`` 对应的 ctypes 类型。

    Windows 是 LLP64：64 位进程下 C ``long`` 仍是 32 位，而 ``time_t`` 是
    64 位；32 位进程两者都是 32 位。``c_long`` 在 64 位上会截断
    ``win_sparkle_get_last_check_time`` 返回的 8 字节 time_t，故按指针宽度
    显式选 ``c_int64`` / ``c_int32``。
    """
    import ctypes

    bits = struct.calcsize("P") * 8
    return ctypes.c_int64 if bits == 64 else ctypes.c_int32


def _setup(dll) -> None:
    """为已加载的 WinSparkle.dll 设置全部导出函数的类型签名。

    在 :meth:`WindowsBackend.configure` 中、加载 DLL 后调用一次。
    重复调用幂等（仅覆盖相同属性）。
    """
    import ctypes

    callback_t = get_callback_type()
    can_shutdown_t = get_can_shutdown_callback_type()

    # -- 配置（必须在 init 前调用）-------------------------------------

    dll.win_sparkle_set_appcast_url.restype = None
    dll.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]

    dll.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
    dll.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]

    # app_details 的 3 个参数都是 wchar_t*（宽字符）。
    dll.win_sparkle_set_app_details.restype = None
    dll.win_sparkle_set_app_details.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]

    dll.win_sparkle_set_app_build_version.restype = None
    dll.win_sparkle_set_app_build_version.argtypes = [ctypes.c_wchar_p]

    dll.win_sparkle_set_registry_path.restype = None
    dll.win_sparkle_set_registry_path.argtypes = [ctypes.c_char_p]

    dll.win_sparkle_set_http_header.restype = None
    dll.win_sparkle_set_http_header.argtypes = [ctypes.c_char_p, ctypes.c_char_p]

    dll.win_sparkle_clear_http_headers.restype = None
    dll.win_sparkle_clear_http_headers.argtypes = []

    # -- 生命周期 -------------------------------------------------------

    dll.win_sparkle_init.restype = None
    dll.win_sparkle_init.argtypes = []

    dll.win_sparkle_cleanup.restype = None
    dll.win_sparkle_cleanup.argtypes = []

    # -- 自动检查配置 ---------------------------------------------------

    dll.win_sparkle_set_automatic_check_for_updates.restype = None
    dll.win_sparkle_set_automatic_check_for_updates.argtypes = [ctypes.c_int]

    dll.win_sparkle_get_automatic_check_for_updates.restype = ctypes.c_int
    dll.win_sparkle_get_automatic_check_for_updates.argtypes = []

    dll.win_sparkle_set_update_check_interval.restype = None
    dll.win_sparkle_set_update_check_interval.argtypes = [ctypes.c_int]

    dll.win_sparkle_get_update_check_interval.restype = ctypes.c_int
    dll.win_sparkle_get_update_check_interval.argtypes = []

    # time_t 在 Win64 是 8 字节，Win32 是 4 字节；c_long 在 Win64 仍是 4 字节
    # 会截断返回值，按进程位数显式选 c_int64/c_int32（见 _time_t_type）。
    dll.win_sparkle_get_last_check_time.restype = _time_t_type()
    dll.win_sparkle_get_last_check_time.argtypes = []

    # -- 手动检查 -------------------------------------------------------

    dll.win_sparkle_check_update_with_ui.restype = None
    dll.win_sparkle_check_update_with_ui.argtypes = []

    dll.win_sparkle_check_update_with_ui_and_install.restype = None
    dll.win_sparkle_check_update_with_ui_and_install.argtypes = []

    dll.win_sparkle_check_update_without_ui.restype = None
    dll.win_sparkle_check_update_without_ui.argtypes = []

    # -- 回调（跨平台 Callbacks 子集映射到这里）-------------------------

    dll.win_sparkle_set_error_callback.restype = None
    dll.win_sparkle_set_error_callback.argtypes = [callback_t]

    dll.win_sparkle_set_did_find_update_callback.restype = None
    dll.win_sparkle_set_did_find_update_callback.argtypes = [callback_t]

    dll.win_sparkle_set_did_not_find_update_callback.restype = None
    dll.win_sparkle_set_did_not_find_update_callback.argtypes = [callback_t]

    dll.win_sparkle_set_update_cancelled_callback.restype = None
    dll.win_sparkle_set_update_cancelled_callback.argtypes = [callback_t]

    # WinSparkle 独有回调（can_shutdown / shutdown_request / skipped /
    # postponed / dismissed / user_run_installer）当前未通过 Callbacks 暴露，
    # 仅设置类型签名以便后续按需扩展。
    dll.win_sparkle_set_can_shutdown_callback.restype = None
    dll.win_sparkle_set_can_shutdown_callback.argtypes = [can_shutdown_t]

    dll.win_sparkle_set_shutdown_request_callback.restype = None
    dll.win_sparkle_set_shutdown_request_callback.argtypes = [callback_t]


__all__ = [
    "_setup",
    "get_callback_type",
    "get_can_shutdown_callback_type",
]
