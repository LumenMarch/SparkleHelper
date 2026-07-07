"""Updater Facade：属性/方法转发 + Subscription + ensure_runnable。

通过注入 mock 的 SPUStandardUpdaterController/SPUUpdater，验证：
- 构造时的 plist 校验、delegate adapter 接入
- 各属性 getter/setter 经 backend 调对了 ObjC selector
- KVO 订阅的 addObserver/removeObserver 配对
- Subscription 的 cancel 幂等与 context manager
"""

from __future__ import annotations

import threading
from unittest import mock

import pytest

import sparklehelper.updater as updater_mod
from sparklehelper._backend._macos import MacOSBackend, _runtime
from sparklehelper.updater import Subscription, Updater, ensure_runnable


# ---------------------------------------------------------------------------
# 测试用 mock 对象
# ---------------------------------------------------------------------------


class _MockSPUUpdater:
    """记录调用以供断言的 SPUUpdater stub。"""

    def __init__(self) -> None:
        self.calls: list = []
        self._props = {
            "canCheckForUpdates": True,
            "sessionInProgress": False,
            "automaticallyChecksForUpdates": True,
            "updateCheckInterval": 86400.0,
            "automaticallyDownloadsUpdates": False,
            "allowsAutomaticUpdates": True,
            "sendsSystemProfile": True,
            "httpHeaders": {"X-App": "demo"},
            "userAgentString": "SparkleHelperDemo/0.1",
        }
        self._observers: list = []

    # 通用 getter
    def canCheckForUpdates(self):
        return self._props["canCheckForUpdates"]

    def sessionInProgress(self):
        return self._props["sessionInProgress"]

    def automaticallyChecksForUpdates(self):
        return self._props["automaticallyChecksForUpdates"]

    def setAutomaticallyChecksForUpdates_(self, v):
        self.calls.append(("setAutomaticallyChecksForUpdates_", v))
        self._props["automaticallyChecksForUpdates"] = v

    def updateCheckInterval(self):
        return self._props["updateCheckInterval"]

    def setUpdateCheckInterval_(self, v):
        self.calls.append(("setUpdateCheckInterval_", v))
        self._props["updateCheckInterval"] = v

    def automaticallyDownloadsUpdates(self):
        return self._props["automaticallyDownloadsUpdates"]

    def allowsAutomaticUpdates(self):
        return self._props["allowsAutomaticUpdates"]

    def setAutomaticallyDownloadsUpdates_(self, v):
        self.calls.append(("setAutomaticallyDownloadsUpdates_", v))

    def sendsSystemProfile(self):
        return self._props["sendsSystemProfile"]

    def setSendsSystemProfile_(self, v):
        self.calls.append(("setSendsSystemProfile_", v))

    def httpHeaders(self):
        return self._props["httpHeaders"]

    def setHttpHeaders_(self, d):
        self.calls.append(("setHttpHeaders_", d))

    def userAgentString(self):
        return self._props["userAgentString"]

    def setUserAgentString_(self, value):
        self.calls.append(("setUserAgentString_", value))
        self._props["userAgentString"] = value

    def hostBundle(self):
        class _Bundle:
            def bundlePath(self):
                return "/Applications/SparkleHelperDemo.app"

        return _Bundle()

    def feedURL(self):
        return None  # 测 feed_url None 分支

    def lastUpdateCheckDate(self):
        return None

    def systemProfileArray(self):
        return [
            {
                "key": "cpuCount",
                "value": "8",
                "displayKey": "Processor Count",
                "displayValue": "8",
            }
        ]

    # 方法
    def checkForUpdatesInBackground(self):
        self.calls.append(("checkForUpdatesInBackground",))

    def checkForUpdateInformation(self):
        self.calls.append(("checkForUpdateInformation",))

    def resetUpdateCycle(self):
        self.calls.append(("resetUpdateCycle",))

    def resetUpdateCycleAfterShortDelay(self):
        self.calls.append(("resetUpdateCycleAfterShortDelay",))

    def clearFeedURLFromUserDefaults(self):
        self.calls.append(("clearFeedURLFromUserDefaults",))
        return "https://old.example.com"

    # KVO
    def addObserver_forKeyPath_options_context_(self, obs, kp, opts, ctx):
        self._observers.append((obs, kp))

    def removeObserver_forKeyPath_(self, obs, kp):
        self._observers = [
            (o, k) for (o, k) in self._observers if not (o is obs and k == kp)
        ]


class _MockController:
    def __init__(self, *, delegate_adapter=None) -> None:
        self._updater = _MockSPUUpdater()
        self._delegate_adapter = delegate_adapter

    def updater(self):
        return self._updater

    def startUpdater(self):
        self._updater.calls.append(("startUpdater",))

    def checkForUpdates_(self, sender):
        self._updater.calls.append(("checkForUpdates_", sender))


def _patch_backend_for_controller(monkeypatch, *, delegate=None):
    """patch MacOSBackend.get_sparkle 返回含假 SPUStandardUpdaterController 的 module。

    让 backend.configure() 能在不真正加载 framework 的情况下创建 mock controller。
    """
    fake_class = mock.MagicMock()

    # 构造 alloc().initWith..._ 链（selector 名来自 framework introspection，不可改）。
    alloc_proxy = mock.MagicMock()
    alloc_proxy.initWithStartingUpdater_updaterDelegate_userDriverDelegate_.side_effect = (
        lambda s, d, dd: _MockController(delegate_adapter=d)
    )
    fake_class.alloc.return_value = alloc_proxy

    sparkle_mod = mock.MagicMock()
    setattr(sparkle_mod, "SPUStandardUpdaterController", fake_class)

    monkeypatch.setattr(MacOSBackend, "get_sparkle", staticmethod(lambda: sparkle_mod))


def _patch_macos_facade(monkeypatch):
    """让 facade 测试在任意 CI 平台都稳定走 macOS 后端分支。"""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(updater_mod, "get_backend", lambda: MacOSBackend())


def _make_updater(monkeypatch, *, plist=None, delegate=None, start=False):
    """构造一个 Updater，注入 mock controller 与 plist。"""
    plist = plist if plist is not None else {
        "CFBundleVersion": "1",
        "SUFeedURL": "https://x/appcast.xml",
        "SUPublicEDKey": "test-key",
    }

    _patch_macos_facade(monkeypatch)
    _patch_backend_for_controller(monkeypatch, delegate=delegate)
    # Updater.__init__ 经 updater 模块顶层 import 调用 bundle_info_plist，
    # 故 patch updater 模块命名空间里的引用（非 _runtime 命名空间）。
    monkeypatch.setattr(updater_mod, "bundle_info_plist", lambda: plist)
    # ensure_runnable 依赖也 patch 掉（load_sparkle 由 get_sparkle mock 隐式绕过）。
    monkeypatch.setattr(MacOSBackend, "load_sparkle", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(updater_mod, "host_bundle_path", lambda: "/x.app")

    u = Updater(delegate=delegate, start=start)
    return u


# ---------------------------------------------------------------------------
# 构造与校验
# ---------------------------------------------------------------------------


def test_constructor_does_not_start_by_default(monkeypatch):
    u = _make_updater(monkeypatch)
    calls = u._backend._updater.calls
    assert ("startUpdater",) not in calls


def test_constructor_requires_feed_url_in_plist(monkeypatch):
    with pytest.raises(Exception):  # ConfigurationError
        _make_updater(monkeypatch, plist={"CFBundleVersion": "1"})


def test_constructor_requires_bundle_build_version(monkeypatch):
    from sparklehelper.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="CFBundleVersion"):
        _make_updater(monkeypatch, plist={"SUFeedURL": "https://x/appcast.xml"})


def test_start_invokes_startUpdater_with_adapter(monkeypatch):
    u = _make_updater(monkeypatch, start=True)
    calls = u._backend._updater.calls
    assert ("startUpdater",) in calls


def test_cleanup_forwards_to_backend(monkeypatch):
    """Updater.cleanup() 转发到 backend.cleanup()（公开退出入口）。"""
    u = _make_updater(monkeypatch)
    with mock.patch.object(u._backend, "cleanup") as backend_cleanup:
        u.cleanup()
        backend_cleanup.assert_called_once_with()


def test_context_manager_calls_cleanup_on_exit(monkeypatch):
    """with 块退出时自动调 cleanup()。"""
    u = _make_updater(monkeypatch)
    with mock.patch.object(u._backend, "cleanup") as backend_cleanup:
        with u:
            pass
        backend_cleanup.assert_called_once_with()


def test_windows_requires_explicit_feed_url(monkeypatch):
    """非 darwin 上必须显式传 feed_url，delegate 动态 feed 无效。

    WinSparkle 无运行时 feed 查询，WindowsBackend.configure 忽略 delegate；
    仅提供 delegate.feed_url_string_for_updater 仍应 ConfigurationError。
    """
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(
        updater_mod, "get_backend", lambda: _NullBackend()
    )

    class _Delegate:
        def feed_url_string_for_updater(self):
            return "https://dynamic.example.com/appcast.xml"

    from sparklehelper.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="feed_url is required"):
        Updater(delegate=_Delegate())


class _NullBackend:
    """darwin 上用不到；仅满足 Updater 在 win32 仍 import get_backend 成功。"""

    def configure(self, config):
        pass

    def start(self):
        pass

    def cleanup(self):
        pass


# ---------------------------------------------------------------------------
# macOS feed_url 经 delegate 动态生效 + public_key 不作为 plist 替代
# ---------------------------------------------------------------------------


def _make_updater_with_feed_url(monkeypatch, feed_url, *, delegate=None, plist=None):
    """构造 Updater 并 patch controller，返回它（便于检查 delegate adapter）。"""
    plist = plist if plist is not None else {"CFBundleVersion": "1", "SUPublicEDKey": "test-key"}
    _patch_macos_facade(monkeypatch)
    _patch_backend_for_controller(monkeypatch, delegate=delegate)
    monkeypatch.setattr(updater_mod, "bundle_info_plist", lambda: plist)
    monkeypatch.setattr(MacOSBackend, "load_sparkle", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(updater_mod, "host_bundle_path", lambda: "/x.app")
    return Updater(feed_url=feed_url, delegate=delegate, start=False)


def test_explicit_feed_url_applied_via_delegate(monkeypatch):
    """macOS 上显式 feed_url 经 delegate.feed_url_string_for_updater 动态生效。

    plist 无 SUFeedURL、无用户 delegate——校验靠显式 feed_url 通过，且该 URL
    被注入 _FeedURLDelegateShim，经 delegate adapter 的 feedURLStringForUpdater_
    返回（Sparkle 官方推荐的运行时 feed 路径）。
    """
    url = "https://explicit.example.com/appcast.xml"
    u = _make_updater_with_feed_url(monkeypatch, url)

    adapter = u._backend._controller._delegate_adapter
    # 测试走 _PythonDelegateStub（framework 未真正加载），_py_delegate 即 shim。
    assert adapter.feedURLStringForUpdater_(None) == url


def test_user_delegate_feed_url_not_overridden(monkeypatch):
    """用户 delegate 自带 feed_url_string_for_updater 时不被 shim 覆盖。

    显式 feed_url 与 delegate 都提供时，尊重 delegate 自身的实现。
    """
    user_url = "https://delegate.example.com/appcast.xml"

    class _Delegate:
        def feed_url_string_for_updater(self):
            return user_url

    # 显式 feed_url 与 delegate 都给：走 delegate 自身（不包 shim）。
    u = _make_updater_with_feed_url(
        monkeypatch, "https://explicit.example.com/x.xml", delegate=_Delegate()
    )

    adapter = u._backend._controller._delegate_adapter
    assert adapter.feedURLStringForUpdater_(None) == user_url


def test_public_key_not_accepted_as_plist_replacement(monkeypatch):
    """macOS 上 public_key 不作为 SUPublicEDKey 的替代。

    Sparkle 无运行时 EdDSA setter，plist 缺 SUPublicEDKey 时即使传了
    public_key 也必须 ConfigurationError。
    """
    _patch_macos_facade(monkeypatch)
    monkeypatch.setattr(MacOSBackend, "load_sparkle", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(updater_mod, "host_bundle_path", lambda: "/x.app")
    monkeypatch.setattr(
        updater_mod,
        "bundle_info_plist",
        lambda: {"CFBundleVersion": "1", "SUFeedURL": "u"},
    )
    from sparklehelper.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="SUPublicEDKey"):
        ensure_runnable(feed_url="u", public_key="BASE64KEY")


# ---------------------------------------------------------------------------
# 方法
# ---------------------------------------------------------------------------


def test_check_for_updates_calls_controller(monkeypatch):
    u = _make_updater(monkeypatch)
    u.check_for_updates()
    assert ("checkForUpdates_", None) in u._backend._updater.calls


def test_check_for_update_information(monkeypatch):
    u = _make_updater(monkeypatch)
    u.check_for_update_information()
    assert ("checkForUpdateInformation",) in u._backend._updater.calls


def test_reset_update_cycle(monkeypatch):
    u = _make_updater(monkeypatch)
    u.reset_update_cycle()
    u.reset_update_cycle_after_short_delay()
    assert ("resetUpdateCycle",) in u._backend._updater.calls
    assert ("resetUpdateCycleAfterShortDelay",) in u._backend._updater.calls


def test_clear_feed_url_returns_value(monkeypatch):
    u = _make_updater(monkeypatch)
    result = u.clear_feed_url_from_user_defaults()
    assert result == "https://old.example.com"


# ---------------------------------------------------------------------------
# 属性 getter / setter
# ---------------------------------------------------------------------------


def test_can_check_for_updates(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.can_check_for_updates is True

    class _Observer:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithCallback_target_keyPath_(self, callback, target, key_path):
            self.callback = callback
            return self

    monkeypatch.setattr(_runtime, "get_kvo_observer_class", lambda: _Observer)
    values = []
    subscription = u.observe("update_check_interval", values.append)
    observer, key_path = u._backend._updater._observers[0]
    assert key_path == "updateCheckInterval"
    observer.callback(7200)
    assert values == [7200.0]
    subscription.cancel()
    assert u._backend._updater._observers == []
    with pytest.raises(ValueError, match="unsupported observable property"):
        u.observe("session_in_progress", values.append)


def test_session_in_progress(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.session_in_progress is False


def test_feed_url_none(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.feed_url is None
    assert u.host_bundle_path == "/Applications/SparkleHelperDemo.app"


def test_last_update_check_date_none(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.last_update_check_date is None


def test_system_profile_maps_array(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.system_profile[0].key == "cpuCount"


def test_bool_property_getters(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.automatically_checks_for_updates is True
    assert u.automatically_downloads_updates is False
    assert u.allows_automatic_updates is True
    assert u.sends_system_profile is True


def test_interval_getter(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.update_check_interval == 86400.0
    assert u.user_agent_string == "SparkleHelperDemo/0.1"
    u.user_agent_string = "CustomAgent/2"
    assert u.user_agent_string == "CustomAgent/2"


def test_bool_setters_dispatch(monkeypatch):
    u = _make_updater(monkeypatch)
    u.automatically_checks_for_updates = False
    u.automatically_downloads_updates = True
    u.sends_system_profile = False
    calls = u._backend._updater.calls
    assert ("setAutomaticallyChecksForUpdates_", False) in calls
    assert ("setAutomaticallyDownloadsUpdates_", True) in calls
    assert ("setSendsSystemProfile_", False) in calls


def test_interval_setter(monkeypatch):
    u = _make_updater(monkeypatch)
    u.update_check_interval = 3600.0
    assert ("setUpdateCheckInterval_", 3600.0) in u._backend._updater.calls


def test_http_headers_getter(monkeypatch):
    u = _make_updater(monkeypatch)
    assert u.http_headers == {"X-App": "demo"}
    u.http_headers = None
    assert ("setHttpHeaders_", None) in u._backend._updater.calls


# ---------------------------------------------------------------------------
# 主线程断言
# ---------------------------------------------------------------------------


def test_methods_assert_main_thread(monkeypatch):
    # 在工作线程调用应抛 WrongThreadError。
    u = _make_updater(monkeypatch)
    err_box: list = [None]

    def worker():
        try:
            u.check_for_updates()
        except BaseException as exc:  # noqa: BLE001
            err_box[0] = exc

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    from sparklehelper.errors import WrongThreadError

    assert isinstance(err_box[0], WrongThreadError)


# ---------------------------------------------------------------------------
# ensure_runnable
# ---------------------------------------------------------------------------


def test_ensure_runnable_passes_when_all_ok(monkeypatch):
    _patch_macos_facade(monkeypatch)
    monkeypatch.setattr(MacOSBackend, "load_sparkle", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(updater_mod, "host_bundle_path", lambda: "/x.app")
    monkeypatch.setattr(
        updater_mod,
        "bundle_info_plist",
        lambda: {"CFBundleVersion": "1", "SUFeedURL": "u", "SUPublicEDKey": "k"},
    )
    ensure_runnable()  # 不抛即通过


def test_ensure_runnable_missing_feed_url(monkeypatch):
    _patch_macos_facade(monkeypatch)
    monkeypatch.setattr(MacOSBackend, "load_sparkle", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(updater_mod, "host_bundle_path", lambda: "/x.app")
    monkeypatch.setattr(updater_mod, "bundle_info_plist", lambda: {"CFBundleVersion": "1"})
    from sparklehelper.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="SUFeedURL"):
        ensure_runnable()
