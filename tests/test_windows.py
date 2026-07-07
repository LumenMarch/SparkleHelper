"""WindowsBackend：WinSparkle.dll 的 ctypes 桥接。

通过 mock ``ctypes.CDLL`` / ``ctypes.CFUNCTYPE``，在任意平台验证：
- DLL 架构选择（current_arch 按进程宽度）
- 路径解析优先级（explicit → env → exe_dir → bundled）
- DLL 加载的进程级缓存
- configure() 在 init 前设置 appcast_url / app_details / eddsa_key
- start/cleanup 幂等
- 回调注册（CFUNCTYPE 闭包持引用防 GC）
- 属性 getter/setter 映射到正确的 win_sparkle_* 函数
"""

from __future__ import annotations

import ctypes
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from sparklehelper._backend._windows import WindowsBackend
from sparklehelper._backend._windows import _bindings, _loading
from sparklehelper._backend.base import Callbacks, UpdateConfig
from sparklehelper.errors import SparkleNotAvailableError


# ---------------------------------------------------------------------------
# 跨平台兼容：WINFUNCTYPE 在非 win32 不存在，测试用 CFUNCTYPE 替代。
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_winfunctype(monkeypatch):
    """保底：若旧代码仍误用 WINFUNCTYPE，则改写到 CFUNCTYPE。

    生产代码现在用 CDLL/CFUNCTYPE（__cdecl），非 win32 上 CFUNCTYPE 本就存在，
    本 fixture 主要保留为向后兼容的保险，并简化跨平台断言。
    """
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)


@pytest.fixture
def reset_windows_cache():
    """每个测试前后清空 _loading 的进程级缓存。"""
    _loading.reset_for_test()
    yield
    _loading.reset_for_test()


# ---------------------------------------------------------------------------
# 架构选择
# ---------------------------------------------------------------------------


def test_current_arch_x64(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "amd64")
    # 模拟 64 位进程，不依赖本机 Python 位数（x86 runner 上也能验证 x64 分支）
    monkeypatch.setattr("struct.calcsize", lambda _: 8)
    assert _loading.current_arch() == "x64"


def test_current_arch_arm64(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert _loading.current_arch() == "arm64"


def test_current_arch_aarch64(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    assert _loading.current_arch() == "arm64"


# ---------------------------------------------------------------------------
# 路径解析优先级
# ---------------------------------------------------------------------------


def test_resolve_rejects_non_win32(reset_windows_cache, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SparkleNotAvailableError, match="Windows-only"):
        _loading.load_winsparkle()


def test_explicit_path_wins(reset_windows_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    dll = tmp_path / "WinSparkle.dll"
    dll.write_bytes(b"fake")

    path = _loading.resolve_winsparkle_path(str(dll))
    assert os.path.realpath(path) == os.path.realpath(str(dll))


def test_explicit_path_must_exist(reset_windows_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    missing = tmp_path / "nope.dll"
    with pytest.raises(SparkleNotAvailableError, match="does not exist"):
        _loading.resolve_winsparkle_path(str(missing))


def test_env_var_path_used(reset_windows_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    dll = tmp_path / "WinSparkle.dll"
    dll.write_bytes(b"fake")
    monkeypatch.setenv("SPARKLEHELPER_WINSPARKLE_PATH", str(dll))
    # 显式传 None 时才走 env；exe_dir 无 DLL；bundled 由 env 命中。
    monkeypatch.setattr(sys, "executable", "/nowhere/python.exe")

    path = _loading.resolve_winsparkle_path(None)
    assert os.path.realpath(path) == os.path.realpath(str(dll))


def test_env_var_nonexistent_raises(reset_windows_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SPARKLEHELPER_WINSPARKLE_PATH", str(tmp_path / "ghost.dll"))
    with pytest.raises(SparkleNotAvailableError, match="non-existent"):
        _loading.resolve_winsparkle_path(None)


def test_exe_dir_used(reset_windows_cache, monkeypatch, tmp_path):
    """exe 同目录的 WinSparkle.dll 优先于 bundled。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SPARKLEHELPER_WINSPARKLE_PATH", raising=False)
    exe_dir = tmp_path
    (exe_dir / "WinSparkle.dll").write_bytes(b"exe-dir-dll")
    monkeypatch.setattr(sys, "executable", str(exe_dir / "myapp.exe"))

    path = _loading.resolve_winsparkle_path(None)
    assert os.path.realpath(path) == os.path.realpath(str(exe_dir / "WinSparkle.dll"))


def test_nuitka_containing_dir_dll_used(reset_windows_cache, monkeypatch, tmp_path):
    """Nuitka 只复制当前架构 DLL 到 containing_dir 根目录。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SPARKLEHELPER_WINSPARKLE_PATH", raising=False)
    monkeypatch.setattr(_loading, "current_arch", lambda: "x64")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "short" / "demo.exe"))
    monkeypatch.setitem(
        sys.modules,
        "__compiled__",
        SimpleNamespace(containing_dir=str(tmp_path)),
    )

    dll = tmp_path / "WinSparkle.dll"
    dll.write_bytes(b"nuitka-dll")

    path = _loading.resolve_winsparkle_path(None)
    assert os.path.realpath(path) == os.path.realpath(str(dll))


def test_bundled_used_as_fallback(reset_windows_cache, monkeypatch, tmp_path):
    """无显式/env/exe 时，回退到 wheel 内置（按架构选子目录）。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SPARKLEHELPER_WINSPARKLE_PATH", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    # 让 current_arch 固定为 x64，便于断言。
    monkeypatch.setattr(_loading, "current_arch", lambda: "x64")

    bundled_root = tmp_path / "winsparkle" / "x64"
    bundled_root.mkdir(parents=True)
    bundled_dll = bundled_root / "WinSparkle.dll"
    bundled_dll.write_bytes(b"bundled")

    from sparklehelper import _framework

    monkeypatch.setattr(
        _framework,
        "bundled_winsparkle_path",
        lambda arch: tmp_path / "winsparkle" / arch / "WinSparkle.dll",
    )

    path = _loading.resolve_winsparkle_path(None)
    assert os.path.realpath(path) == os.path.realpath(str(bundled_dll))


# ---------------------------------------------------------------------------
# DLL 加载与进程级缓存
# ---------------------------------------------------------------------------


def test_load_is_idempotent(reset_windows_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    dll = tmp_path / "WinSparkle.dll"
    dll.write_bytes(b"fake")

    call_count = {"n": 0}

    def counting_windll(path):
        call_count["n"] += 1
        return mock.MagicMock()

    monkeypatch.setattr(ctypes, "CDLL", counting_windll, raising=False)

    first = _loading.load_winsparkle(str(dll))
    second = _loading.load_winsparkle(str(dll))

    assert first is second, "重复加载应返回缓存的同一对象"
    assert call_count["n"] == 1
    assert _loading.is_loaded()
    assert _loading.loaded_path() is not None


# ---------------------------------------------------------------------------
# WindowsBackend.configure（init 前设置）
# ---------------------------------------------------------------------------


def _make_mock_dll():
    """构造一个记录调用的 mock DLL（模拟 WinSparkle 导出函数）。"""
    dll = mock.MagicMock()
    return dll


def _patch_load_with_mock(monkeypatch, dll):
    """让 _loading.load_winsparkle 返回给定的 mock dll。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_loading, "load_winsparkle", lambda *a, **kw: dll)


def test_configure_sets_appcast_url(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="https://x/appcast.xml"))

    dll.win_sparkle_set_appcast_url.assert_called_once_with(b"https://x/appcast.xml")


def test_configure_sets_eddsa_key(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u", public_key="BASE64KEY"))

    dll.win_sparkle_set_eddsa_public_key.assert_called_once_with(b"BASE64KEY")


def test_configure_sets_app_details_as_wchar(monkeypatch):
    """app_details 的参数是 wchar_t*，ctypes 用 c_wchar_p（传 str 而非 bytes）。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(
        UpdateConfig(
            feed_url="u",
            company="MyCompany",
            app_name="MyApp",
            version="1.0",
            build="100",
        )
    )

    # app_details 接收 str（wchar），不是 bytes。
    dll.win_sparkle_set_app_details.assert_called_once_with(
        "MyCompany", "MyApp", "1.0"
    )
    dll.win_sparkle_set_app_build_version.assert_called_once_with("100")


def test_configure_skips_partial_app_details(monkeypatch):
    """company/app_name/version 任一缺失则不调 set_app_details。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u", company="OnlyCompany"))

    dll.win_sparkle_set_app_details.assert_not_called()


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


def test_start_calls_init_once(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.start()
    backend.start()  # 幂等

    dll.win_sparkle_init.assert_called_once()


def test_cleanup_calls_win_cleanup(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.start()
    backend.cleanup()

    dll.win_sparkle_cleanup.assert_called_once()


def test_cleanup_idempotent_when_not_started(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.cleanup()  # 未 start，应 no-op

    dll.win_sparkle_cleanup.assert_not_called()


# ---------------------------------------------------------------------------
# 检查方法
# ---------------------------------------------------------------------------


def test_check_for_updates(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))

    backend.check_for_updates()
    dll.win_sparkle_check_update_with_ui.assert_called_once()

    backend.check_for_updates_in_background()
    dll.win_sparkle_check_update_without_ui.assert_called_once()


# ---------------------------------------------------------------------------
# 属性 getter/setter
# ---------------------------------------------------------------------------


def test_automatically_checks_get_set(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    dll.win_sparkle_get_automatic_check_for_updates.return_value = 1

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    assert backend.automatically_checks_for_updates is True

    backend.automatically_checks_for_updates = False
    dll.win_sparkle_set_automatic_check_for_updates.assert_called_once_with(0)


def test_update_check_interval(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    dll.win_sparkle_get_update_check_interval.return_value = 3600

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    assert backend.update_check_interval == 3600.0

    backend.update_check_interval = 7200.5
    dll.win_sparkle_set_update_check_interval.assert_called_once_with(7200)


def test_last_check_time_none_when_zero(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    dll.win_sparkle_get_last_check_time.return_value = 0

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    assert backend.last_update_check_date is None


def test_last_check_time_none_when_unchecked(monkeypatch):
    """winsparkle.h 默认返回 -1（从未检查），也应转成 None，不能是 1969。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    dll.win_sparkle_get_last_check_time.return_value = -1

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    assert backend.last_update_check_date is None


def test_last_check_time_returns_datetime(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    dll.win_sparkle_get_last_check_time.return_value = 1700000000

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    dt = backend.last_update_check_date
    assert dt is not None
    assert dt.year == 2023


def test_http_headers_clear_then_set(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.http_headers = {"X-App": "demo", "Authorization": "Bearer x"}

    dll.win_sparkle_clear_http_headers.assert_called_once()
    assert dll.win_sparkle_set_http_header.call_count == 2


def test_http_headers_none_clears_only(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.http_headers = None

    dll.win_sparkle_clear_http_headers.assert_called_once()
    dll.win_sparkle_set_http_header.assert_not_called()


def test_http_headers_getter_always_none(monkeypatch):
    """WinSparkle 无 getter，http_headers 读始终返回 None。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    assert backend.http_headers is None


# ---------------------------------------------------------------------------
# 回调注册（CFUNCTYPE 闭包持引用防 GC）
# ---------------------------------------------------------------------------


def test_register_callbacks(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.register_callbacks(
        Callbacks(
            on_error=lambda: None,
            on_update_found=lambda: None,
            on_no_update=lambda: None,
            on_cancelled=lambda: None,
        )
    )

    # 4 个回调各注册一次，闭包引用存入 _callbacks_holder 防 GC。
    dll.win_sparkle_set_error_callback.assert_called_once()
    dll.win_sparkle_set_did_find_update_callback.assert_called_once()
    dll.win_sparkle_set_did_not_find_update_callback.assert_called_once()
    dll.win_sparkle_set_update_cancelled_callback.assert_called_once()
    assert len(backend._callbacks_holder) == 4


def test_register_callbacks_skips_none(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.register_callbacks(Callbacks(on_error=lambda: None))

    dll.win_sparkle_set_error_callback.assert_called_once()
    dll.win_sparkle_set_did_find_update_callback.assert_not_called()
    assert len(backend._callbacks_holder) == 1


# ---------------------------------------------------------------------------
# WinSparkleExtras
# ---------------------------------------------------------------------------


def test_set_registry_path(monkeypatch):
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.set_registry_path("Software\\MyApp\\Updates")

    dll.win_sparkle_set_registry_path.assert_called_once_with(
        b"Software\\MyApp\\Updates"
    )


# ---------------------------------------------------------------------------
# macOS-only 成员：WinSparkle 无对应物 → 明确 AttributeError（非裸 AttributeError）
# ---------------------------------------------------------------------------

_MACOS_ONLY_METHODS = [
    "check_for_update_information",
    "reset_update_cycle",
    "reset_update_cycle_after_short_delay",
    "clear_feed_url_from_user_defaults",
    "observe",
    "observe_can_check_for_updates",
]


@pytest.mark.parametrize("method_name", _MACOS_ONLY_METHODS)
def test_macos_only_methods_raise(monkeypatch, method_name):
    """macOS-only 方法在 Windows 上抛 AttributeError，使 hasattr() 返回 False。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))

    method = getattr(backend, method_name)
    with pytest.raises(AttributeError, match="macOS-only"):
        if method_name == "observe":
            method("property", lambda v: None)
        elif method_name == "observe_can_check_for_updates":
            method(lambda v: None)
        else:
            method()


_MACOS_ONLY_PROPERTIES_GET = [
    "can_check_for_updates",
    "session_in_progress",
    "feed_url",
    "host_bundle_path",
    "system_profile",
    "allows_automatic_updates",
    "automatically_downloads_updates",
    "user_agent_string",
    "sends_system_profile",
]


@pytest.mark.parametrize("prop_name", _MACOS_ONLY_PROPERTIES_GET)
def test_macos_only_properties_raise_on_get(monkeypatch, prop_name):
    """macOS-only 属性读取在 Windows 上抛 AttributeError。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))

    with pytest.raises(AttributeError, match="macOS-only"):
        getattr(backend, prop_name)


_MACOS_ONLY_PROPERTIES_SET = [
    "automatically_downloads_updates",
    "user_agent_string",
    "sends_system_profile",
]


@pytest.mark.parametrize("prop_name", _MACOS_ONLY_PROPERTIES_SET)
def test_macos_only_property_setters_raise(monkeypatch, prop_name):
    """macOS-only 属性写入在 Windows 上抛 AttributeError。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))

    with pytest.raises(AttributeError, match="macOS-only"):
        setattr(backend, prop_name, None)


def test_cross_platform_members_still_work(monkeypatch):
    """回归保护：跨平台 UpdateBackend 成员在 Windows 后端照常工作。"""
    dll = _make_mock_dll()
    _patch_load_with_mock(monkeypatch, dll)
    dll.win_sparkle_get_automatic_check_for_updates.return_value = 1
    dll.win_sparkle_get_update_check_interval.return_value = 3600
    dll.win_sparkle_get_last_check_time.return_value = -1

    backend = WindowsBackend()
    backend.configure(UpdateConfig(feed_url="u"))
    backend.check_for_updates()  # 不抛即通过
    backend.check_for_updates_in_background()
    assert backend.automatically_checks_for_updates is True
    assert backend.update_check_interval == 3600.0
    assert backend.last_update_check_date is None  # -1 → None（上次修复）
    backend.automatically_checks_for_updates = False
    backend.update_check_interval = 7200
    backend.http_headers = {"X": "y"}
    # setter 路径不抛即通过（getter 跨平台也成立，http_headers getter 返回 None）
    assert backend.http_headers is None
