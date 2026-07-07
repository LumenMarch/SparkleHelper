"""macOS 更新后端：组合 Sparkle 加载、运行时基础设施与 delegate 桥接。

:class:`MacOSBackend` 实现
:class:`~sparklehelper._backend.base.UpdateBackend` 契约 + macOS 独有能力
（KVO / system_profile / 24+ delegate 方法）。它本身只持有 controller /
updater 实例状态与 ObjC selector 调用，底层逻辑由同包的
:mod:`._loading` / :mod:`._runtime` / :mod:`._delegates` 提供。

所有方法**必须在主线程**调用（``Updater`` Facade 统一断言）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ...errors import SparkleNotAvailableError
from ...types import SystemProfileEntry, from_system_profile
from ..base import Callbacks, UpdateConfig
from . import _delegates, _loading, _runtime

# Sparkle 2.9 明确声明为 KVO-compliant 的属性。
_KVO_PROPERTIES: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "can_check_for_updates": ("canCheckForUpdates", bool),
    "automatically_checks_for_updates": ("automaticallyChecksForUpdates", bool),
    "update_check_interval": ("updateCheckInterval", float),
    "automatically_downloads_updates": ("automaticallyDownloadsUpdates", bool),
    "allows_automatic_updates": ("allowsAutomaticUpdates", bool),
    "sends_system_profile": ("sendsSystemProfile", bool),
}


class MacOSBackend:
    """macOS 更新后端：Sparkle.framework 的加载与 ObjC 桥接。

    实现 :class:`~sparklehelper._backend.base.UpdateBackend` 契约 +
    macOS 独有能力（KVO / system_profile / 24+ delegate 方法）。

    所有方法**必须在主线程**调用（``Updater`` Facade 统一断言）。
    """

    # ------------------------------------------------------------------
    # 进程级缓存管理（类方法，供测试与诊断）
    # ------------------------------------------------------------------

    @classmethod
    def is_loaded(cls) -> bool:
        """Sparkle.framework 是否已成功加载。"""
        return _loading.is_loaded()

    @classmethod
    def loaded_path(cls) -> Optional[str]:
        """已加载 framework 的磁盘路径；未加载时为 None。"""
        return _loading.loaded_path()

    @classmethod
    def _reset_for_test(cls) -> None:
        """仅供测试：清空所有进程级缓存。"""
        _loading.reset_for_test()

    # 透传给 _loading，便于测试 patch（与原 _objc 模块函数签名一致）。
    _main_bundle_frameworks_path = staticmethod(_loading.main_bundle_frameworks_path)
    _resolve_framework_path = staticmethod(_loading.resolve_framework_path)
    load_sparkle = staticmethod(_loading.load_sparkle)
    get_sparkle = staticmethod(_loading.get_sparkle)

    # ------------------------------------------------------------------
    # ObjC 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _look_up(sparkle_module: Any, class_name: str) -> Any:
        """从已加载的 Sparkle module 取出类，先查 globals 再 lookUpClass 兜底。"""
        cls = getattr(sparkle_module, class_name, None)
        if cls is not None:
            return cls
        try:
            import objc

            return objc.lookUpClass(class_name)
        except Exception as exc:  # noqa: BLE001
            raise SparkleNotAvailableError(
                f"Sparkle.framework loaded but cannot get class {class_name}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # 构造与生命周期（UpdateBackend Protocol）
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._controller: Any = None
        self._updater: Any = None
        self._delegate: Any = None
        self._delegate_adapter: Any = None
        self._started: bool = False

    def configure(self, config: UpdateConfig) -> None:
        """加载 Sparkle、创建 controller（复刻原 Updater.__init__ 创建链）。

        顺序：load_sparkle → make_delegate_adapter → alloc().initWith...
        selector 名 ``initWithStartingUpdater_updaterDelegate_userDriverDelegate_``
        来自 framework introspection，不可改名。

        ``delegate`` 通过 :attr:`UpdateConfig.delegate` 传入。
        """
        _runtime.assert_main_thread()

        sparkle = self.get_sparkle()
        SPUStandardUpdaterController = self._look_up(
            sparkle, "SPUStandardUpdaterController"
        )

        delegate = config.delegate
        self._delegate = delegate
        delegate_adapter = _delegates.make_delegate_adapter(delegate)
        self._delegate_adapter = delegate_adapter

        self._controller = (
            SPUStandardUpdaterController.alloc()
            .initWithStartingUpdater_updaterDelegate_userDriverDelegate_(
                False, delegate_adapter, None
            )
        )
        if self._controller is None:
            raise SparkleNotAvailableError(
                "SPUStandardUpdaterController 初始化失败（返回 nil）。"
                "请检查 Info.plist 是否包含 SUFeedURL、SUPublicEDKey、"
                "CFBundleVersion 等必需字段。"
            )
        self._updater = self._controller.updater()

    def register_callbacks(self, callbacks: Callbacks) -> None:
        """注册跨平台回调集合。

        macOS 后端通过 :class:`~._delegates.UpdaterDelegate` 体系接收回调。
        粗粒度回调（error/found/no_update/cancelled）由 delegate 的对应方法
        承载；此方法当前为 Protocol 完整性保留。
        """
        return

    def start(self) -> None:
        """启动更新检查调度器：``[controller startUpdater]``。幂等。"""
        _runtime.assert_main_thread()
        if self._controller is None:
            raise SparkleNotAvailableError(
                "后端尚未配置，请先调用 configure()。"
            )
        if self._started:
            return
        self._controller.startUpdater()
        self._started = True

    def cleanup(self) -> None:
        """释放资源。macOS 下 Sparkle 无显式清理 API，空操作。"""
        return

    # ------------------------------------------------------------------
    # 手动检查（UpdateBackend Protocol）
    # ------------------------------------------------------------------

    def check_for_updates(self) -> None:
        """弹出标准更新窗口：``[controller checkForUpdates:nil]``。"""
        _runtime.assert_main_thread()
        self._controller.checkForUpdates_(None)

    def check_for_updates_in_background(self) -> None:
        """后台静默检查：``[updater checkForUpdatesInBackground]``。"""
        _runtime.assert_main_thread()
        self._updater.checkForUpdatesInBackground()

    # ------------------------------------------------------------------
    # macOS 独有检查方法
    # ------------------------------------------------------------------

    def check_for_update_information(self) -> None:
        """仅拉取 appcast 信息，不触发起安装流程。"""
        _runtime.assert_main_thread()
        self._updater.checkForUpdateInformation()

    def reset_update_cycle(self) -> None:
        """重置自动检查计时，立即开始新一轮调度。"""
        _runtime.assert_main_thread()
        self._updater.resetUpdateCycle()

    def reset_update_cycle_after_short_delay(self) -> None:
        """短暂延迟后重置自动检查计时。"""
        _runtime.assert_main_thread()
        self._updater.resetUpdateCycleAfterShortDelay()

    def clear_feed_url_from_user_defaults(self) -> Optional[str]:
        """清除此前持久化的 feed URL，返回被清除的值。"""
        _runtime.assert_main_thread()
        url = self._updater.clearFeedURLFromUserDefaults()
        if url is None:
            return None
        absolute_string = getattr(url, "absoluteString", None)
        if callable(absolute_string):
            value = absolute_string()
            return str(value) if value else None
        return str(url) or None

    # ------------------------------------------------------------------
    # 只读状态（UpdateBackend Protocol + SparkleExtras）
    # ------------------------------------------------------------------

    @property
    def can_check_for_updates(self) -> bool:
        _runtime.assert_main_thread()
        return bool(self._updater.canCheckForUpdates())

    @property
    def session_in_progress(self) -> bool:
        _runtime.assert_main_thread()
        return bool(self._updater.sessionInProgress())

    @property
    def feed_url(self) -> Optional[str]:
        _runtime.assert_main_thread()
        url = self._updater.feedURL()
        if url is None:
            return None
        if hasattr(url, "absoluteString"):
            abs_str = url.absoluteString()
            return str(abs_str) if abs_str else None
        return str(url) or None

    @property
    def host_bundle_path(self) -> str:
        _runtime.assert_main_thread()
        bundle = self._updater.hostBundle()
        path = bundle.bundlePath() if bundle is not None else None
        return str(path) if path else ""

    @property
    def last_update_check_date(self) -> Optional[datetime]:
        _runtime.assert_main_thread()
        date = self._updater.lastUpdateCheckDate()
        if date is None:
            return None
        try:
            ts = float(date.timeIntervalSince1970())
        except (AttributeError, TypeError, ValueError):
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def system_profile(self) -> list[SystemProfileEntry]:
        _runtime.assert_main_thread()
        entries = self._updater.systemProfileArray()
        return from_system_profile(entries)

    @property
    def allows_automatic_updates(self) -> bool:
        _runtime.assert_main_thread()
        return bool(self._updater.allowsAutomaticUpdates())

    @property
    def automatically_downloads_updates(self) -> bool:
        _runtime.assert_main_thread()
        return bool(self._updater.automaticallyDownloadsUpdates())

    @automatically_downloads_updates.setter
    def automatically_downloads_updates(self, value: bool) -> None:
        _runtime.assert_main_thread()
        self._updater.setAutomaticallyDownloadsUpdates_(bool(value))

    # ------------------------------------------------------------------
    # 可读写状态（UpdateBackend Protocol + SparkleExtras）
    # ------------------------------------------------------------------

    @property
    def automatically_checks_for_updates(self) -> bool:
        _runtime.assert_main_thread()
        return bool(self._updater.automaticallyChecksForUpdates())

    @automatically_checks_for_updates.setter
    def automatically_checks_for_updates(self, value: bool) -> None:
        _runtime.assert_main_thread()
        self._updater.setAutomaticallyChecksForUpdates_(bool(value))

    @property
    def update_check_interval(self) -> float:
        _runtime.assert_main_thread()
        return float(self._updater.updateCheckInterval())

    @update_check_interval.setter
    def update_check_interval(self, seconds: float) -> None:
        _runtime.assert_main_thread()
        self._updater.setUpdateCheckInterval_(float(seconds))

    @property
    def http_headers(self) -> Optional[dict[str, str]]:
        _runtime.assert_main_thread()
        headers = self._updater.httpHeaders()
        if headers is None:
            return None
        return {str(k): str(v) for k, v in headers.items()}

    @http_headers.setter
    def http_headers(self, headers: Optional[dict[str, str]]) -> None:
        _runtime.assert_main_thread()
        if headers is None:
            self._updater.setHttpHeaders_(None)
            return
        from Foundation import NSDictionary

        ns_dict = NSDictionary.dictionaryWithDictionary_(
            {str(k): str(v) for k, v in headers.items()}
        )
        self._updater.setHttpHeaders_(ns_dict)

    @property
    def user_agent_string(self) -> str:
        _runtime.assert_main_thread()
        value = self._updater.userAgentString()
        return str(value) if value else ""

    @user_agent_string.setter
    def user_agent_string(self, value: str) -> None:
        _runtime.assert_main_thread()
        self._updater.setUserAgentString_(str(value))

    @property
    def sends_system_profile(self) -> bool:
        _runtime.assert_main_thread()
        return bool(self._updater.sendsSystemProfile())

    @sends_system_profile.setter
    def sends_system_profile(self, value: bool) -> None:
        _runtime.assert_main_thread()
        self._updater.setSendsSystemProfile_(bool(value))

    # ------------------------------------------------------------------
    # KVO 订阅
    # ------------------------------------------------------------------

    def observe(
        self, property_name: str, callback: Callable[[Any], None]
    ) -> "_runtime.Subscription":
        """订阅 Sparkle 公开的 KVO 属性。订阅建立后立即回调一次。"""
        _runtime.assert_main_thread()
        try:
            key_path, converter = _KVO_PROPERTIES[property_name]
        except KeyError as exc:
            supported = ", ".join(sorted(_KVO_PROPERTIES))
            raise ValueError(
                f"unsupported observable property {property_name!r}; "
                f"available: {supported}"
            ) from exc

        target = self._updater
        observer_cls = _runtime.get_kvo_observer_class()

        def wrapped(new_value: Any) -> None:
            if new_value is not None:
                callback(converter(new_value))

        observer = observer_cls.alloc().initWithCallback_target_keyPath_(
            wrapped, target, key_path
        )
        from Foundation import (
            NSKeyValueObservingOptionInitial,
            NSKeyValueObservingOptionNew,
        )

        options = NSKeyValueObservingOptionNew | NSKeyValueObservingOptionInitial
        target.addObserver_forKeyPath_options_context_(observer, key_path, options, 0)
        return _runtime.Subscription(observer=observer, target=target, key_path=key_path)

    def observe_can_check_for_updates(
        self, callback: Callable[[bool], None]
    ) -> "_runtime.Subscription":
        """订阅 ``canCheckForUpdates`` 变化（便捷封装）。"""
        return self.observe("can_check_for_updates", callback)


__all__ = ["MacOSBackend"]
