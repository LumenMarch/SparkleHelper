"""Updater Facade 在 Windows 分支下的公共行为。"""

from __future__ import annotations

from unittest import mock

import pytest

import sparklehelper.updater as updater_mod
from sparklehelper._backend._windows import _loading
from sparklehelper.errors import ConfigurationError
from sparklehelper.updater import Updater, ensure_runnable


def _make_mock_dll():
    """构造一个模拟 WinSparkle.dll 导出函数的对象。"""
    dll = mock.MagicMock()
    dll.win_sparkle_get_automatic_check_for_updates.return_value = 1
    dll.win_sparkle_get_update_check_interval.return_value = 3600
    dll.win_sparkle_get_last_check_time.return_value = -1
    return dll


def _patch_windows_facade(monkeypatch, dll=None):
    """让 Updater 在任意平台都稳定走真实 WindowsBackend 分支。"""
    if dll is None:
        dll = _make_mock_dll()
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(_loading, "load_winsparkle", lambda *a, **kw: dll)
    return dll


def test_windows_updater_requires_feed_url(monkeypatch):
    _patch_windows_facade(monkeypatch)

    class _Delegate:
        def feed_url_string_for_updater(self):
            return "https://dynamic.example.com/appcast.xml"

    with pytest.raises(ConfigurationError, match="feed_url is required"):
        Updater(delegate=_Delegate())


def test_windows_ensure_runnable_requires_feed_url(monkeypatch):
    _patch_windows_facade(monkeypatch)

    with pytest.raises(ConfigurationError, match="feed_url is required"):
        ensure_runnable()


def test_windows_updater_configures_backend_without_start(monkeypatch):
    dll = _patch_windows_facade(monkeypatch)

    updater = Updater(
        feed_url="https://example.com/appcast.xml",
        public_key="BASE64KEY",
        company="Example",
        app_name="Demo",
        version="1.0.0",
        build="1",
    )

    dll.win_sparkle_set_appcast_url.assert_called_once_with(
        b"https://example.com/appcast.xml"
    )
    dll.win_sparkle_set_eddsa_public_key.assert_called_once_with(b"BASE64KEY")
    dll.win_sparkle_set_app_details.assert_called_once_with(
        "Example", "Demo", "1.0.0"
    )
    dll.win_sparkle_set_app_build_version.assert_called_once_with("1")
    dll.win_sparkle_init.assert_not_called()

    updater.cleanup()
    dll.win_sparkle_cleanup.assert_not_called()


def test_windows_updater_start_and_cleanup(monkeypatch):
    dll = _patch_windows_facade(monkeypatch)

    updater = Updater(feed_url="https://example.com/appcast.xml", start=True)
    dll.win_sparkle_init.assert_called_once()

    updater.cleanup()
    dll.win_sparkle_cleanup.assert_called_once()


def test_windows_updater_cross_platform_members(monkeypatch):
    dll = _patch_windows_facade(monkeypatch)
    updater = Updater(feed_url="https://example.com/appcast.xml")

    updater.check_for_updates()
    updater.check_for_updates_in_background()
    assert updater.automatically_checks_for_updates is True
    updater.automatically_checks_for_updates = False
    assert updater.update_check_interval == 3600.0
    updater.update_check_interval = 7200.5
    assert updater.last_update_check_date is None
    assert updater.http_headers is None
    updater.http_headers = {"X-App": "Demo"}

    dll.win_sparkle_check_update_with_ui.assert_called_once()
    dll.win_sparkle_check_update_without_ui.assert_called_once()
    dll.win_sparkle_set_automatic_check_for_updates.assert_called_once_with(0)
    dll.win_sparkle_set_update_check_interval.assert_called_once_with(7200)
    dll.win_sparkle_clear_http_headers.assert_called_once()
    dll.win_sparkle_set_http_header.assert_called_once_with(b"X-App", b"Demo")


@pytest.mark.parametrize(
    "member_name",
    [
        "check_for_update_information",
        "reset_update_cycle",
        "reset_update_cycle_after_short_delay",
        "clear_feed_url_from_user_defaults",
        "can_check_for_updates",
        "session_in_progress",
        "feed_url",
        "host_bundle_path",
        "system_profile",
        "allows_automatic_updates",
        "automatically_downloads_updates",
        "user_agent_string",
        "sends_system_profile",
    ],
)
def test_windows_macos_only_members_raise(monkeypatch, member_name):
    _patch_windows_facade(monkeypatch)
    updater = Updater(feed_url="https://example.com/appcast.xml")
    member = getattr(type(updater), member_name, None)

    with pytest.raises(AttributeError, match="macOS-only"):
        if isinstance(member, property):
            getattr(updater, member_name)
        else:
            getattr(updater, member_name)()
