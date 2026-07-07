"""平台无关的更新后端契约（Protocol）与配置/回调数据类。

设计原则
--------
1. ``UpdateBackend`` 只暴露 **Sparkle 与 WinSparkle 都有对应物** 的能力。
   单平台独有的能力（macOS 的 KVO / system_profile / 24+ delegate 方法；
   Windows 的 registry 配置 / 语言设置）**不进 Protocol**，由各后端类自行
   扩展，通过 ``Updater`` 层做 ``hasattr`` 降级或文档标注为平台特性。

2. 后端之间用 duck typing 契约约束：各后端类继承 ``UpdateBackend``，但
   Protocol 本身是 ``runtime_checkable``，便于测试桩与真实后端互换。

3. 找不到框架/dll 时抛
   :class:`~sparklehelper.errors.SparkleNotAvailableError`，配置缺失抛
   :class:`~sparklehelper.errors.ConfigurationError`，与现有 ``Updater``
   行为一致。

能力映射（两端都有对应物才进 Protocol）
======================================

============== ================================== ====================================
Protocol 成员    Sparkle (macOS)                     WinSparkle (Windows)
============== ================================== ====================================
configure       SPUUpdater 属性 / Info.plist        set_appcast_url /
                fallback                            set_eddsa_public_key /
                                                    set_app_details（init 前）
register_       delegate 方法映射                  win_sparkle_set_*_callback
callbacks
start           [controller startUpdater]          win_sparkle_init()
cleanup         （空操作）                          win_sparkle_cleanup()
check_for_      checkForUpdates:                   check_update_with_ui
updates
check_for_      checkForUpdatesInBackground        check_update_without_ui
updates_in_
background
automatically_  automaticallyChecksForUpdates      set/get_automatic_check_for_updates
checks_for_
updates
update_check_   updateCheckInterval                set/get_update_check_interval
interval
last_update_    lastUpdateCheckDate (NSDate)       get_last_check_time (time_t)
check_date
http_headers    httpHeaders                        set_http_header /
                                                    clear_http_headers
============== ================================== ====================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# 配置数据载体（平台无关）
# ---------------------------------------------------------------------------


@dataclass
class UpdateConfig:
    """后端初始化所需的配置，由 ``Updater`` 从平台配置源收集后传入。

    各字段在两端都有对应物：

    ============ ================================== =================================
    字段          macOS 来源                         Windows 来源
    ============ ================================== =================================
    feed_url     ``Info.plist`` ``SUFeedURL``         exe 资源 ``FeedURL`` / 手动传入
    public_key   ``Info.plist`` ``SUPublicEDKey``     ``set_eddsa_public_key``
    company      bundle org id（可选）                ``set_app_details`` company_name
    app_name     ``CFBundleName``                    ``set_app_details`` app_name
    version      ``CFBundleShortVersionString``       VERSIONINFO / ``set_app_details``
    build        ``CFBundleVersion``                  ``set_app_build_version``
    http_headers ``httpHeaders``                      ``set_http_header``
    ============ ================================== =================================
    """

    feed_url: str
    """appcast feed URL。HTTPS 强烈推荐。"""

    public_key: Optional[str] = None
    """EdDSA 公钥（base64）。None 表示使用框架内置来源（Info.plist / exe 资源）。"""

    company: Optional[str] = None
    """厂商名。macOS 可选；Windows 用于确定 registry 存储位置。"""

    app_name: Optional[str] = None
    """应用名，同时用于 User-Agent。"""

    version: Optional[str] = None
    """展示版本号。"""

    build: Optional[str] = None
    """构建版本号（用于版本比较）。"""

    http_headers: dict[str, str] = field(default_factory=dict)
    """附加到 appcast 检查与下载请求的 HTTP 头。"""

    delegate: Any = None
    """macOS 专有：``UpdaterDelegate`` 回调对象。Windows 后端忽略此字段。

    通过 config 携带，让 ``MacOSBackend.configure`` 能在创建 controller 时
    一并包装成 ``SPUUpdaterDelegate`` adapter。
    """


# ---------------------------------------------------------------------------
# 回调数据载体（平台无关，两端都有对应物的子集）
# ---------------------------------------------------------------------------


@dataclass
class Callbacks:
    """跨平台通用回调集合（两端都有对应物的子集）。

    各后端在 ``register_callbacks`` 时把这些回调注册到底层框架：macOS 后端
    映射到对应 delegate 方法，Windows 后端映射到 ``win_sparkle_set_*_callback``。

    所有字段可选——未提供的回调，后端不注册对应钩子。

    注意：``can_shutdown`` / ``shutdown_request`` 仅 WinSparkle 有对应物
    （macOS 无），故不进此集合，由 ``WinSparkleExtras`` 暴露。
    """

    on_error: Optional[Callable[[], None]] = None
    """更新流程发生错误时调用。

    macOS: ``delegate.updater_didAbortWithError_``
    Windows: ``win_sparkle_set_error_callback``
    """

    on_update_found: Optional[Callable[[], None]] = None
    """发现有效更新时调用。

    macOS: ``delegate.updater_didFindValidUpdate_``
    Windows: ``win_sparkle_set_did_find_update_callback``
    """

    on_no_update: Optional[Callable[[], None]] = None
    """未发现更新时调用。

    macOS: ``delegate.updater_didNotFindUpdate_``
    Windows: ``win_sparkle_set_did_not_find_update_callback``
    """

    on_cancelled: Optional[Callable[[], None]] = None
    """用户取消更新时调用。

    macOS: ``delegate.userDidCancelDownload_``
    Windows: ``win_sparkle_set_update_cancelled_callback``
    """


# ---------------------------------------------------------------------------
# 后端契约
# ---------------------------------------------------------------------------


@runtime_checkable
class UpdateBackend(Protocol):
    """更新后端的平台无关契约。

    生命周期（由 ``Updater`` 驱动）::

        backend = get_backend()              # 选择平台后端
        backend.configure(config)            # 注入配置（feed_url/公钥/版本等）
        backend.register_callbacks(cbs)      # 可选：注册回调
        backend.start()                      # 启动后台自动检查调度
        ...
        backend.check_for_updates()          # 用户触发"检查更新"
        ...
        backend.cleanup()                    # 退出前清理（Windows 必需，macOS 空操作）

    线程约束
    --------
    macOS 后端的所有方法**必须在主线程**调用。``Updater`` Facade 统一负责
    主线程断言（抛 :class:`~sparklehelper.errors.WrongThreadError`），后端
    实现可不再重复断言。Windows 后端无此约束（WinSparkle 自身后台线程模型）。

    幂等性
    ------
    ``configure`` 与 ``start`` 应幂等：重复调用安全（第二次起 no-op 或仅更新
    可写状态），便于 ``Updater`` 在多次初始化场景下不抛错。
    """

    # -- 生命周期 --------------------------------------------------------

    def configure(self, config: UpdateConfig) -> None:
        """注入配置。必须在 ``start`` 之前调用一次（幂等）。

        - macOS：用 ``config`` 设置 ``SPUUpdater`` 属性，或作为 fallback
          补充 Info.plist 缺失项。
        - Windows：在 ``win_sparkle_init`` **之前** 调用
          ``set_appcast_url`` / ``set_eddsa_public_key`` / ``set_app_details``
          等（这些配置函数 WinSparkle 要求 init 前设置）。
        """
        ...

    def register_callbacks(self, callbacks: Callbacks) -> None:
        """注册跨平台回调集合。可选，可在 ``start`` 前任意时刻调用。"""
        ...

    def start(self) -> None:
        """启动更新检查调度器（幂等）。

        - macOS：``[controller startUpdater]``。
        - Windows：``win_sparkle_init()``（配置必须在之前就绪）。
        """
        ...

    def cleanup(self) -> None:
        """释放资源，应用退出前调用。

        - macOS：空操作（Sparkle 无显式清理 API）。
        - Windows：``win_sparkle_cleanup()``（必需，取消后台线程）。
        """
        ...

    # -- 手动检查 --------------------------------------------------------

    def check_for_updates(self) -> None:
        """弹出标准更新窗口，让用户决定是否更新。

        - macOS：``[controller checkForUpdates:nil]``。
        - Windows：``win_sparkle_check_update_with_ui()``。

        忽略"跳过此版本"标记（用户主动触发）。
        """
        ...

    def check_for_updates_in_background(self) -> None:
        """后台静默检查，仅发现更新时才打扰用户。

        - macOS：``[updater checkForUpdatesInBackground]``。
        - Windows：``win_sparkle_check_update_without_ui()``。

        尊重"跳过此版本"标记。不要高频手动调用。
        """
        ...

    # -- 可读写状态（两端都有 get/set） ---------------------------------

    @property
    def automatically_checks_for_updates(self) -> bool:
        """是否启用自动检查。"""
        ...

    @automatically_checks_for_updates.setter
    def automatically_checks_for_updates(self, value: bool) -> None:
        ...

    @property
    def update_check_interval(self) -> float:
        """自动检查间隔（秒）。"""
        ...

    @update_check_interval.setter
    def update_check_interval(self, seconds: float) -> None:
        ...

    # -- 只读状态 --------------------------------------------------------

    @property
    def last_update_check_date(self) -> Optional[datetime]:
        """上次更新检查时间（UTC aware），未检查过为 None。

        - macOS：``lastUpdateCheckDate`` (NSDate) → datetime。
        - Windows：``get_last_check_time`` (time_t) → datetime。
        """
        ...

    @property
    def http_headers(self) -> Optional[dict[str, str]]:
        """当前生效的附加 HTTP 头；None 表示使用框架默认。"""
        ...

    @http_headers.setter
    def http_headers(self, headers: Optional[dict[str, str]]) -> None:
        """设置请求头；传入 None 清除。"""
        ...


# ---------------------------------------------------------------------------
# 单平台扩展能力（可选 Protocol，供 ``Updater`` 做 hasattr 降级）
# ---------------------------------------------------------------------------


class SparkleExtras(Protocol):
    """macOS 独有能力契约（``MacOSBackend`` 额外实现）。

    这些是 Sparkle 有、WinSparkle 无对应物的能力。``Updater`` 通过
    ``isinstance(backend, SparkleExtras)`` 或 ``hasattr`` 判断是否暴露，
    在 Windows 上相应公共属性/方法要么降级要么标注 ``UnsupportedError``。
    """

    @property
    def can_check_for_updates(self) -> bool:
        """当前是否允许发起检查（KVO 可订阅）。"""
        ...

    @property
    def system_profile(self) -> list[Any]:
        """随更新检查发送的系统配置项列表。"""
        ...

    @property
    def host_bundle_path(self) -> str:
        """Sparkle 当前更新的宿主 bundle 路径。"""
        ...


class WinSparkleExtras(Protocol):
    """Windows 独有能力契约（``WindowsBackend`` 额外实现）。

    WinSparkle 有、Sparkle 无对应物的能力。
    """

    def set_registry_path(self, path: str) -> None:
        """自定义 registry 存储路径。必须在 ``start`` 前调用。"""
        ...


__all__ = [
    "UpdateConfig",
    "Callbacks",
    "UpdateBackend",
    "SparkleExtras",
    "WinSparkleExtras",
]
