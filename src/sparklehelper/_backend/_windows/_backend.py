"""Windows 更新后端：WinSparkle.dll 的 ctypes 桥接。

:class:`WindowsBackend` 实现
:class:`~sparklehelper._backend.base.UpdateBackend` 契约 +
Windows 独有能力（:class:`~sparklehelper._backend.base.WinSparkleExtras`）。
底层 DLL 加载由 :mod:`._loading` 提供，C API 类型签名由 :mod:`._bindings` 提供。

线程模型
--------
WinSparkle 的 ``init`` / 配置函数必须在主线程调用（其内部用 Win32 消息循环）。
``check_update_*`` 内部启动后台线程，调用后立即返回。
本后端不做主线程断言（SparkleHelper 的 macOS 主线程约束是 Cocoa 特有的；
Windows 上交由 WinSparkle 自身管理）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..base import Callbacks, UpdateConfig
from . import _bindings, _loading

_LOGGER = logging.getLogger(__name__)


class WindowsBackend:
    """Windows 更新后端：通过 ctypes 调用 WinSparkle.dll。

    实现 :class:`~sparklehelper._backend.base.UpdateBackend` 契约 +
    :class:`~sparklehelper._backend.base.WinSparkleExtras`。
    """

    def __init__(self) -> None:
        self._dll = None
        self._started = False
        # 持有 CFUNCTYPE 闭包引用，防止被 GC（DLL 持有的是原始函数指针，
        # Python 侧必须保活包装对象，否则回调时访问已释放内存会崩溃）。
        self._callbacks_holder: list = []

    # ------------------------------------------------------------------
    # 进程级缓存管理（类方法，供测试与诊断）
    # ------------------------------------------------------------------

    @classmethod
    def is_loaded(cls) -> bool:
        """WinSparkle.dll 是否已成功加载。"""
        return _loading.is_loaded()

    @classmethod
    def loaded_path(cls) -> Optional[str]:
        """已加载 DLL 的磁盘路径；未加载时为 None。"""
        return _loading.loaded_path()

    @classmethod
    def _reset_for_test(cls) -> None:
        """仅供测试：清空进程级缓存。"""
        _loading.reset_for_test()

    # ------------------------------------------------------------------
    # 生命周期（UpdateBackend Protocol）
    # ------------------------------------------------------------------

    def configure(self, config: UpdateConfig) -> None:
        """加载 DLL 并设置 init 前的配置。

        WinSparkle 要求 appcast_url / eddsa_key / app_details 在
        ``win_sparkle_init`` **之前** 设置，故全部在此完成。

        ``config.delegate`` 在 Windows 上忽略（WinSparkle 用回调而非 delegate 对象）。
        """
        self._dll = _loading.load_winsparkle()
        _bindings._setup(self._dll)

        if config.feed_url:
            self._dll.win_sparkle_set_appcast_url(
                config.feed_url.encode("utf-8")
            )
        if config.public_key:
            ok = self._dll.win_sparkle_set_eddsa_public_key(
                config.public_key.encode("utf-8")
            )
            if not ok:
                _LOGGER.warning(
                    "win_sparkle_set_eddsa_public_key 失败（返回 0）。"
                    "请检查 EdDSA 公钥是否为有效的 base64 编码。"
                )
        # app_details 的 3 个参数都是 wchar_t*；ctypes 自动用宽字符编码。
        # WinSparkle 要求三者同时提供，部分缺失时记录警告避免静默丢弃。
        app_details = [
            ("company", config.company),
            ("app_name", config.app_name),
            ("version", config.version),
        ]
        missing = [name for name, value in app_details if not value]
        if missing:
            _LOGGER.warning(
                "win_sparkle_set_app_details 未调用：缺少 %s。"
                "三者必须同时提供，否则 WinSparkle 使用 VERSIONINFO 默认值。",
                "、".join(missing),
            )
        else:
            self._dll.win_sparkle_set_app_details(
                config.company,  # type: ignore[arg-type]
                config.app_name,  # type: ignore[arg-type]
                config.version,   # type: ignore[arg-type]
            )
        if config.build:
            self._dll.win_sparkle_set_app_build_version(config.build)

    def register_callbacks(self, callbacks: Callbacks) -> None:
        """把跨平台 Callbacks 映射到 win_sparkle_set_*_callback。

        每个 Python 回调包装成 CFUNCTYPE 闭包并存入 ``_callbacks_holder``，
        防止被 GC（DLL 持有原始函数指针）。
        """
        callback_t = _bindings.get_callback_type()

        def _register(python_cb, dll_setter_name):
            if python_cb is None:
                return
            cb = callback_t(python_cb)
            self._callbacks_holder.append(cb)
            getattr(self._dll, dll_setter_name)(cb)

        _register(callbacks.on_error, "win_sparkle_set_error_callback")
        _register(
            callbacks.on_update_found,
            "win_sparkle_set_did_find_update_callback",
        )
        _register(
            callbacks.on_no_update,
            "win_sparkle_set_did_not_find_update_callback",
        )
        _register(
            callbacks.on_cancelled,
            "win_sparkle_set_update_cancelled_callback",
        )

    def start(self) -> None:
        """``win_sparkle_init()``：启动后台自动检查调度。幂等。"""
        if self._dll is None:
            raise RuntimeError(
                "后端尚未配置，请先调用 configure()。"
            )
        if self._started:
            return
        self._dll.win_sparkle_init()
        self._started = True

    def cleanup(self) -> None:
        """``win_sparkle_cleanup()``：取消后台线程，释放资源。

        应用退出前必须调用（WinSparkle 文档要求）。
        """
        if not self._started:
            return
        self._dll.win_sparkle_cleanup()
        self._started = False

    # ------------------------------------------------------------------
    # 手动检查（UpdateBackend Protocol）
    # ------------------------------------------------------------------

    def check_for_updates(self) -> None:
        """``win_sparkle_check_update_with_ui()``：弹出更新窗口。"""
        self._dll.win_sparkle_check_update_with_ui()

    def check_for_updates_in_background(self) -> None:
        """``win_sparkle_check_update_without_ui()``：后台静默检查。"""
        self._dll.win_sparkle_check_update_without_ui()

    # ------------------------------------------------------------------
    # 可读写状态（UpdateBackend Protocol）
    # ------------------------------------------------------------------

    @property
    def automatically_checks_for_updates(self) -> bool:
        return bool(self._dll.win_sparkle_get_automatic_check_for_updates())

    @automatically_checks_for_updates.setter
    def automatically_checks_for_updates(self, value: bool) -> None:
        self._dll.win_sparkle_set_automatic_check_for_updates(int(bool(value)))

    @property
    def update_check_interval(self) -> float:
        return float(self._dll.win_sparkle_get_update_check_interval())

    @update_check_interval.setter
    def update_check_interval(self, seconds: float) -> None:
        self._dll.win_sparkle_set_update_check_interval(int(seconds))

    @property
    def last_update_check_date(self) -> Optional[datetime]:
        """上次检查时间（UTC aware）。

        WinSparkle 默认返回 -1 表示从未检查；0 及任何非正值（含可能的
        出错哨兵）一律视为 None，避免暴露 1969-12-31 这样的 datetime。
        """
        timestamp = self._dll.win_sparkle_get_last_check_time()
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    @property
    def http_headers(self) -> Optional[dict[str, str]]:
        """WinSparkle 无 getter，始终返回 None。"""
        return None

    @http_headers.setter
    def http_headers(self, headers: Optional[dict[str, str]]) -> None:
        """设置请求头；传入 None 清除全部。"""
        self._dll.win_sparkle_clear_http_headers()
        if headers:
            for name, value in headers.items():
                self._dll.win_sparkle_set_http_header(
                    name.encode("utf-8"),
                    value.encode("utf-8"),
                )

    # ------------------------------------------------------------------
    # WinSparkleExtras（Windows 独有）
    # ------------------------------------------------------------------

    def set_registry_path(self, path: str) -> None:
        """自定义 registry 存储路径（如 ``Software\\MyApp\\Updates``）。

        必须在 :meth:`start` 前调用。
        """
        self._dll.win_sparkle_set_registry_path(path.encode("utf-8"))

    # ------------------------------------------------------------------
    # macOS-only（WinSparkle 无对应物）
    #
    # 这些成员是 ``Updater`` Facade 透明转发到后端的 macOS 独有能力
    # （SparkleExtras / KVO / delegate 体系）。WinSparkle 没有对应 API，
    # 抛出 ``AttributeError`` 让 ``hasattr()`` 返回 False，
    # 平台不支持的特性在 IDE 补全和运行时检查中自然隐藏。
    # ------------------------------------------------------------------

    @staticmethod
    def _unsupported(member: str) -> AttributeError:
        """构造统一的"macOS-only 不支持"异常。"""
        return AttributeError(
            f"{member} is macOS-only (WinSparkle has no equivalent)."
        )

    # -- 方法 -----------------------------------------------------------

    def check_for_update_information(self) -> None:
        """macOS-only：``checkForUpdateInformation``。WinSparkle 无对应物。"""
        raise self._unsupported("check_for_update_information")

    def reset_update_cycle(self) -> None:
        """macOS-only：``resetUpdateCycle``。WinSparkle 无对应物。"""
        raise self._unsupported("reset_update_cycle")

    def reset_update_cycle_after_short_delay(self) -> None:
        """macOS-only：``resetUpdateCycleAfterShortDelay``。WinSparkle 无对应物。"""
        raise self._unsupported("reset_update_cycle_after_short_delay")

    def clear_feed_url_from_user_defaults(self) -> Optional[str]:
        """macOS-only：``clearFeedURLFromUserDefaults``。WinSparkle 无对应物。"""
        raise self._unsupported("clear_feed_url_from_user_defaults")

    def observe(self, property_name, callback):  # noqa: ANN001
        """macOS-only：KVO 订阅。WinSparkle 无 KVO 机制。"""
        raise self._unsupported("observe")

    def observe_can_check_for_updates(self, callback):  # noqa: ANN001
        """macOS-only：``canCheckForUpdates`` KVO 订阅。WinSparkle 无 KVO。"""
        raise self._unsupported("observe_can_check_for_updates")

    # -- 属性 -----------------------------------------------------------

    @property
    def can_check_for_updates(self) -> bool:
        """macOS-only：``canCheckForUpdates``。WinSparkle 无对应物。"""
        raise self._unsupported("can_check_for_updates")

    @property
    def session_in_progress(self) -> bool:
        """macOS-only：``sessionInProgress``。WinSparkle 无对应物。"""
        raise self._unsupported("session_in_progress")

    @property
    def feed_url(self) -> Optional[str]:
        """macOS-only：``feedURL``。WinSparkle 无 getter（仅在 init 前静态设置）。"""
        raise self._unsupported("feed_url")

    @property
    def host_bundle_path(self) -> str:
        """macOS-only：``hostBundle.bundlePath``。WinSparkle 无 bundle 概念。"""
        raise self._unsupported("host_bundle_path")

    @property
    def system_profile(self):
        """macOS-only：``systemProfileArray``。WinSparkle 无对应物。"""
        raise self._unsupported("system_profile")

    @property
    def allows_automatic_updates(self) -> bool:
        """macOS-only：``allowsAutomaticUpdates``。WinSparkle 无对应物。"""
        raise self._unsupported("allows_automatic_updates")

    @property
    def automatically_downloads_updates(self) -> bool:
        """macOS-only：``automaticallyDownloadsUpdates``。WinSparkle 无对应物。"""
        raise self._unsupported("automatically_downloads_updates")

    @automatically_downloads_updates.setter
    def automatically_downloads_updates(self, value: bool) -> None:
        raise self._unsupported("automatically_downloads_updates")

    @property
    def user_agent_string(self) -> str:
        """macOS-only：``userAgentString``。WinSparkle 无对应物。"""
        raise self._unsupported("user_agent_string")

    @user_agent_string.setter
    def user_agent_string(self, value: str) -> None:
        raise self._unsupported("user_agent_string")

    @property
    def sends_system_profile(self) -> bool:
        """macOS-only：``sendsSystemProfile``。WinSparkle 无对应物。"""
        raise self._unsupported("sends_system_profile")

    @sends_system_profile.setter
    def sends_system_profile(self, value: bool) -> None:
        raise self._unsupported("sends_system_profile")


__all__ = ["WindowsBackend"]
