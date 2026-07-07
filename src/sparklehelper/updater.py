"""Sparkle 更新控制器的平台无关 Facade。

``Updater`` 不再直接接触 ObjC——它持有平台后端
（macOS 下为 :class:`~sparklehelper._backend._macos.MacOSBackend`），
收集配置后交给后端创建底层 controller，自身只做转发。

设计要点
--------
- 默认不启动自动检查调度；GUI 准备好后由宿主显式调用 ``start()``。
- 所有入口都 :func:`assert_main_thread`（由后端统一断言）。
- 构造时校验 Info.plist 含 ``SUFeedURL``，否则 :class:`ConfigurationError`。
- ``Updater`` 不再暴露 ``_controller`` / ``_raw_updater``；访问底层 ObjC
  对象请通过 ``self._backend``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from ._backend import get_backend
from ._backend._macos import (
    Subscription,
    UpdaterDelegate,
    assert_main_thread,
    bundle_info_plist,
    host_bundle_path,
    make_delegate_adapter,
)
from ._backend.base import UpdateConfig
from .errors import ConfigurationError
from .types import SystemProfileEntry

# 必需的 Info.plist 键。
_FEED_URL_KEY = "SUFeedURL"
_ED_KEY = "SUPublicEDKey"
_BUILD_VERSION_KEY = "CFBundleVersion"


def _require_bundle_build_version(plist: dict[str, Any]) -> None:
    value = plist.get(_BUILD_VERSION_KEY)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"Info.plist 缺少有效的 {_BUILD_VERSION_KEY}。Sparkle 在 macOS "
            "上只读取 .app bundle 的 CFBundleVersion 作为当前构建版本；"
            "Updater(version=...) / Updater(build=...) 不能替代它。"
        )


def ensure_runnable(
    delegate: Any = None,
    *,
    feed_url: Optional[str] = None,
    public_key: Optional[str] = None,
) -> None:
    """聚合检查：平台、bundle、framework、配置。

    在启动 updater 前调用，可一次性收集所有配置问题，
    而不是在不同 API 调用点零散抛错。任一检查失败即抛对应异常。

    macOS 上 ``delegate`` 提供 ``feed_url_string_for_updater`` 或显式
    ``feed_url`` 时，Info.plist 可以省略 ``SUFeedURL``。
    Windows 上 ``feed_url`` 必须显式传入（无 plist）；
    delegate 的 ``feed_url_string_for_updater`` 在 Windows 上无效
    （WinSparkle 无运行时 feed 查询，需 init 前静态 URL）。

    ``public_key``（EdDSA）在 macOS 上 **不接受为 ``SUPublicEDKey`` 的替代**：
    Sparkle 无运行时 setter，公钥只能从 Info.plist 读。故 darwin 上
    ``public_key`` 参数被忽略，plist 必须含 ``SUPublicEDKey``。
    """
    import sys

    if sys.platform == "darwin":
        from ._backend._macos import MacOSBackend

        # 1. 平台 + framework（load_sparkle 内部会校验平台）。
        MacOSBackend.load_sparkle()
        # 2. 必须在 .app 内。
        host_bundle_path()
        # 3. Info.plist 关键键（显式参数可覆盖）。
        plist = bundle_info_plist()
        _require_bundle_build_version(plist)
        has_dynamic_feed = callable(
            getattr(delegate, "feed_url_string_for_updater", None)
        )
        if not (feed_url or plist.get(_FEED_URL_KEY) or has_dynamic_feed):
            raise ConfigurationError(
                f"Info.plist 缺少 {_FEED_URL_KEY}。请在打包时为 .app 的 "
                "Info.plist 配置 SUFeedURL，或通过 delegate/feed_url 提供。"
            )
        # SUPublicEDKey 只能来自 Info.plist（Sparkle 无运行时 setter）。
        # public_key 参数在 darwin 上无效，显式拒绝而非假装生效。
        if not plist.get(_ED_KEY):
            raise ConfigurationError(
                f"Info.plist 缺少 {_ED_KEY}。Sparkle 的 EdDSA 公钥只能从 "
                f"Info.plist 的 {_ED_KEY} 读取（无运行时 setter）。"
                "请用 Sparkle.framework 自带的 `generate_keys` 生成公钥"
                "并填入 Info.plist；public_key 参数在 macOS 上不被接受。"
            )
    else:
        # Windows 是唯一支持的非 macOS 平台；其余平台 get_backend() 会抛错。
        if sys.platform != "win32":
            raise ConfigurationError(
                f"sparklehelper 不支持当前平台: {sys.platform}"
                "（仅支持 macOS / Windows）。"
            )
        # WinSparkle 不支持 delegate 动态 feed，必须显式传入 feed_url。
        if not feed_url:
            raise ConfigurationError(
                "feed_url is required on this platform "
                "(WinSparkle 需在 init 前静态设置 appcast URL；"
                "不支持 delegate 动态 feed)."
            )


class _FeedURLDelegateShim:
    """用显式 feed URL 包装用户 delegate（macOS 专用）。

    ``Updater(feed_url=...)`` 在 macOS 上不能直接写 feed URL（Sparkle 的
    ``-[SPUUpdater setFeedURL:]`` 已 deprecated 且会写 user defaults）。
    官方推荐的运行时 feed 路径是 delegate 的
    ``feed_url_string_for_updater``——本 shim 让传入的显式 feed_url 经由
    该方法被 Sparkle 查询到。

    仅当被包装的 delegate 自身未实现 ``feed_url_string_for_updater`` 时，
    shim 才提供该方法（尊重用户显式实现）。其余属性/方法全部透传给被
    包装 delegate，保证 delegate 的其它回调正常工作（适配器通过
    ``getattr`` 访问，shim 的 ``__getattr__`` 转发即可）。
    """

    def __init__(self, delegate: Any, feed_url: str) -> None:
        self._delegate = delegate
        self._feed_url = feed_url

    def feed_url_string_for_updater(self) -> Optional[str]:
        """Sparkle 查询 feed URL 时返回显式传入的值。

        被包装 delegate 自身实现该方法时不该被 shim 覆盖——构造时由
        ``Updater.__init__`` 保证（仅 delegate 未实现时才包 shim）。
        """
        return self._feed_url

    def __getattr__(self, name: str) -> Any:
        # delegate adapter 经 getattr 访问其它回调方法，全部透传。
        return getattr(self._delegate, name)


class Updater:
    """Sparkle/WinSparkle 更新控制器的平台无关接口。

    macOS 上必须运行在打包后的 ``.app`` bundle 内（``ensure_runnable()``
    会检查 bundle 与 plist）

    Windows 上可独立运行，但必须显式传入
    ``feed_url``（以及 ``public_key`` 用于签名校验）

    Args:
        delegate: ``--macOS-only``。macOS 的 ``UpdaterDelegate``（P1）；
            Windows 上忽略。
        start: ``--macOS`` / ``--Windows``。为 True 时构造后立即
            ``start()`` 启动自动检查调度。
        feed_url: ``--macOS`` / ``--Windows``。appcast feed URL。macOS
            可省略（读 Info.plist 的 ``SUFeedURL``），传入时经 delegate 的
            ``feed_url_string_for_updater`` 动态生效；Windows 必须传入。
        public_key: ``--Windows-only``。EdDSA 公钥（base64），用于
            WinSparkle 签名校验。macOS 必须在 Info.plist 的
            ``SUPublicEDKey`` 配置（Sparkle 无运行时 setter，本参数被忽略）。
        company: ``--Windows-only``。厂商名，用于 WinSparkle registry 定位；
            macOS 忽略。
        app_name: ``--macOS`` / ``--Windows``。应用名（User-Agent）。
        version: ``--Windows-only``。展示版本号，传给 WinSparkle；macOS 必须通过
            ``Info.plist`` 的 ``CFBundleShortVersionString`` 提供。
        build: ``--Windows-only``。构建版本号（用于版本比较），传给 WinSparkle；
            macOS 必须通过 ``Info.plist`` 的 ``CFBundleVersion`` 提供。

    Lifecycle
    ---------
    构造后不会默认启动后台自动检查；需要自动调度时显式调用
    :meth:`start`，或传入 ``start=True``。**应用退出前** 必须调
    :meth:`cleanup`（Windows 上 ``win_sparkle_cleanup()`` 会取消后台线程；
    macOS 上为空操作）。推荐用 context manager::

        with Updater(feed_url=...) as updater:
            updater.check_for_updates()
        # 退出 with 块时自动 cleanup

    Example:
        >>> from sparklehelper import Updater
        >>> # macOS（从 Info.plist 自动读取）
        >>> updater = Updater()
        >>> # Windows（显式配置）
        >>> updater = Updater(feed_url="https://x/appcast.xml",
        ...                   public_key="...", company="My", app_name="App")
        >>> updater.check_for_updates()
    """

    def __init__(
        self,
        *,
        delegate: Any = None,
        start: bool = False,
        feed_url: Optional[str] = None,
        public_key: Optional[str] = None,
        company: Optional[str] = None,
        app_name: Optional[str] = None,
        version: Optional[str] = None,
        build: Optional[str] = None,
    ) -> None:
        assert_main_thread()

        self._delegate = delegate
        self._backend = get_backend()

        import sys

        effective_delegate = delegate
        if sys.platform == "darwin":
            # macOS：显式参数优先，否则从 Info.plist 读取。
            plist = bundle_info_plist()
            _require_bundle_build_version(plist)
            has_dynamic_feed = callable(
                getattr(delegate, "feed_url_string_for_updater", None)
            )
            if not feed_url and not has_dynamic_feed and not plist.get(_FEED_URL_KEY):
                raise ConfigurationError(
                    f"Info.plist 缺少 {_FEED_URL_KEY}，且未通过 feed_url "
                    "或 delegate 提供。"
                )
            # SUPublicEDKey 只能来自 Info.plist，Sparkle 无运行时 setter。
            if public_key is not None:
                import warnings
                warnings.warn(
                    "public_key 参数在 macOS 上无效。Sparkle 仅从 Info.plist "
                    "的 SUPublicEDKey 读取 EdDSA 公钥（无运行时 setter），"
                    "传入的 public_key 将被忽略。请用 Sparkle.framework 自带的 "
                    "`generate_keys` 生成公钥并填入 Info.plist。",
                    stacklevel=2,
                )
            if not plist.get(_ED_KEY):
                raise ConfigurationError(
                    f"Info.plist 缺少 {_ED_KEY}。Sparkle 的 EdDSA 公钥只能从 "
                    f"Info.plist 的 {_ED_KEY} 读取（无运行时 setter）。"
                    "请用 Sparkle.framework 自带的 `generate_keys` 生成公钥"
                    "并填入 Info.plist；public_key 参数在 macOS 上不被接受。"
                )
            # 显式 feed_url 经 delegate 的 feed_url_string_for_updater 动态生效
            # （Sparkle 官方推荐的运行时 feed 路径，见 SPUUpdater.h）。
            # plist 的 SUFeedURL 由 Sparkle 自身读取，无需注入。
            #
            # 冲突优先级：若用户 delegate 自身实现了 feed_url_string_for_updater，
            # 尊重用户实现（不包 shim）；否则用 shim 让该方法返回显式 feed_url。
            # 这样 Updater(feed_url=..., delegate=Delegate(自带 feed 方法)) 时，
            # delegate 的显式实现胜过便利参数。
            if feed_url and not has_dynamic_feed:
                effective_delegate = _FeedURLDelegateShim(delegate, feed_url)
            elif not feed_url:
                # 无显式 feed_url 时，回退到 plist 供 UpdateConfig 记录。
                feed_url = plist.get(_FEED_URL_KEY)
        else:
            # Windows：feed_url 必须显式传入。
            #
            # 注意：不在此接受 delegate.feed_url_string_for_updater。该方法
            # 是 macOS Sparkle 的运行时查询语义（每次检查时由框架回调），
            # WinSparkle 无对应能力，且要求 appcast URL 在 win_sparkle_init()
            # 之前静态设置。WindowsBackend.configure() 也忽略 config.delegate，
            # 若仅靠 delegate 构造会静默导致 URL 未设置。
            if not feed_url:
                raise ConfigurationError(
                    "feed_url is required on this platform "
                    "(WinSparkle 需在 init 前静态设置 appcast URL；"
                    "不支持 delegate 动态 feed)."
                )

        # 后端加载底层库并应用配置（macOS: 创建 controller；Windows: set_*）。
        config = UpdateConfig(
            feed_url=feed_url or "",
            public_key=public_key,
            company=company,
            app_name=app_name,
            version=version,
            build=build,
            delegate=effective_delegate,
        )
        self._backend.configure(config)

        if start:
            self.start()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动更新检查调度器（``[controller startUpdater]``）。"""
        self._backend.start()

    def cleanup(self) -> None:
        """释放资源，应用退出前调用（转发到 backend.cleanup）。

        - macOS：空操作（Sparkle 无显式清理 API）。
        - Windows：``win_sparkle_cleanup()`` 取消后台线程（必需）。

        幂等：多次调用安全。也可通过 context manager 自动触发。
        """
        assert_main_thread()
        self._backend.cleanup()

    # ------------------------------------------------------------------
    # Context manager：自动 cleanup
    # ------------------------------------------------------------------

    def __enter__(self) -> "Updater":
        return self

    def __exit__(self, *exc_info) -> None:
        self.cleanup()

    # ------------------------------------------------------------------
    # 检查更新
    # ------------------------------------------------------------------

    def check_for_updates(self) -> None:
        """弹出 Sparkle 标准更新窗口，让用户决定是否更新。

        即使用户曾跳过当前版本，此入口也会再次显示该版本。
        """
        self._backend.check_for_updates()

    def check_for_updates_in_background(self) -> None:
        """后台检查更新；仅在发现更新时才打扰用户。

        遵循 Sparkle 文档警告：不要高频手动调用，正常使用应依赖
        ``start()`` 后的自动调度。
        """
        self._backend.check_for_updates_in_background()

    def check_for_update_information(self) -> None:
        """仅拉取 appcast 信息，不触发起安装流程。"""
        self._backend.check_for_update_information()

    def reset_update_cycle(self) -> None:
        """重置自动检查计时，立即开始新一轮调度。"""
        self._backend.reset_update_cycle()

    def reset_update_cycle_after_short_delay(self) -> None:
        """短暂延迟后重置自动检查计时，可被后续调用取消。"""
        self._backend.reset_update_cycle_after_short_delay()

    def clear_feed_url_from_user_defaults(self) -> Optional[str]:
        """清除此前持久化的 feed URL，返回被清除的值。"""
        return self._backend.clear_feed_url_from_user_defaults()

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------

    @property
    def can_check_for_updates(self) -> bool:
        """当前是否允许发起更新检查（KVO 可订阅）。"""
        return self._backend.can_check_for_updates

    @property
    def session_in_progress(self) -> bool:
        """当前是否正处于一次更新会话中。"""
        return self._backend.session_in_progress

    @property
    def feed_url(self) -> Optional[str]:
        """当前生效的 appcast feed URL。"""
        return self._backend.feed_url

    @property
    def host_bundle_path(self) -> str:
        """Sparkle 当前更新的宿主 bundle 路径。"""
        return self._backend.host_bundle_path

    @property
    def last_update_check_date(self) -> Optional[datetime]:
        """上次更新检查时间（UTC aware datetime 或 None）。"""
        return self._backend.last_update_check_date

    @property
    def system_profile(self) -> list[SystemProfileEntry]:
        """Sparkle 随更新检查发送的系统配置项列表。"""
        return self._backend.system_profile

    @property
    def allows_automatic_updates(self) -> bool:
        """用户是否可以启用自动下载更新。"""
        return self._backend.allows_automatic_updates

    @property
    def automatically_downloads_updates(self) -> bool:
        return self._backend.automatically_downloads_updates

    # ------------------------------------------------------------------
    # 可读写属性
    # ------------------------------------------------------------------

    @property
    def automatically_checks_for_updates(self) -> bool:
        return self._backend.automatically_checks_for_updates

    @automatically_checks_for_updates.setter
    def automatically_checks_for_updates(self, value: bool) -> None:
        self._backend.automatically_checks_for_updates = value

    @property
    def update_check_interval(self) -> float:
        """自动检查间隔（秒）。"""
        return self._backend.update_check_interval

    @update_check_interval.setter
    def update_check_interval(self, seconds: float) -> None:
        self._backend.update_check_interval = seconds

    @automatically_downloads_updates.setter
    def automatically_downloads_updates(self, value: bool) -> None:
        self._backend.automatically_downloads_updates = value

    @property
    def user_agent_string(self) -> str:
        """Sparkle 更新请求使用的 User-Agent。"""
        return self._backend.user_agent_string

    @user_agent_string.setter
    def user_agent_string(self, value: str) -> None:
        self._backend.user_agent_string = value

    @property
    def http_headers(self) -> Optional[dict[str, str]]:
        """附加到更新请求的 HTTP 头；None 表示使用 Sparkle 默认值。"""
        return self._backend.http_headers

    @http_headers.setter
    def http_headers(self, headers: Optional[dict[str, str]]) -> None:
        """设置请求头；传入 None 可清除动态配置。"""
        self._backend.http_headers = headers

    @property
    def sends_system_profile(self) -> bool:
        return self._backend.sends_system_profile

    @sends_system_profile.setter
    def sends_system_profile(self, value: bool) -> None:
        self._backend.sends_system_profile = value

    # ------------------------------------------------------------------
    # KVO 订阅
    # ------------------------------------------------------------------

    def observe(
        self, property_name: str, callback: Callable[[Any], None]
    ) -> Subscription:
        """订阅 Sparkle 公开的 KVO 属性。

        ``property_name`` 使用 Python 属性名，例如
        ``"automatically_checks_for_updates"``。订阅建立后会立即回调一次。
        """
        return self._backend.observe(property_name, callback)

    def observe_can_check_for_updates(
        self, callback: Callable[[bool], None]
    ) -> Subscription:
        """订阅 ``canCheckForUpdates`` 变化（KVO）。

        立即用当前值触发一次回调，之后每次变化都会调用。返回的
        :class:`Subscription` 必须被持有；调用 ``cancel()`` 或离开
        ``with`` 块时注销观察，避免泄漏。
        """
        return self._backend.observe_can_check_for_updates(callback)


__all__ = ["Updater", "Subscription", "ensure_runnable", "UpdaterDelegate"]
