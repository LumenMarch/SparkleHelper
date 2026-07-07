"""delegates 模块：Protocol 语义 + adapter 转发。

用 _PythonDelegateStub（非 darwin 回退路径）验证转发逻辑与默认值，
不依赖真实 PyObjC。darwin 下 ObjC adapter 的注册由导入冒烟覆盖。
"""

from __future__ import annotations

import pytest

from sparklehelper._backend._macos import _delegates as delegates
from sparklehelper._backend._macos._delegates import (
    UpdaterDelegate,
    _has,
    make_delegate_adapter,
)


class _FullDelegate:
    """实现了所有回调的对象（鸭子类型，不显式继承 Protocol）。"""

    def __init__(self) -> None:
        self.events: list = []

    def updater_did_finish_cycle(self, *, update_check, found_update, error):
        self.events.append(("finish", update_check, found_update, error))

    def feed_url_string_for_updater(self):
        return "https://example.com/feed.xml"

    def allowed_channels_for_updater(self):
        return ("beta",)

    def updater_may_perform_update_check(self, *, update_check):
        return "Current policy forbids checking"

    def feed_parameters_for_updater(self, *, sending_system_profile):
        return ({"key": "cohort", "value": "beta"},)

    def updater_should_prompt_for_permission_to_check_for_updates(self):
        return False

    def allowed_system_profile_keys_for_updater(self):
        return ("cpuCount",)

    def updater_did_find_valid_update(self, *, update):
        self.events.append(("found", update))

    def updater_did_not_find_update(self, *, error):
        self.events.append(("not_found", error))

    def updater_did_download_update(self, *, update):
        self.events.append(("downloaded", update))

    def updater_should_proceed_with_update(self, *, update, update_check):
        return "Current version is not updatable"

    def updater_user_did_make_choice(self, *, choice, update, state):
        self.events.append(("choice", choice, update, state))

    def updater_should_download_release_notes(self, *, update):
        return False

    def updater_will_download_update(self, *, update):
        self.events.append(("will_download", update))

    def updater_failed_to_download_update(self, *, update, error):
        self.events.append(("download_failed", update, error))

    def user_did_cancel_download(self):
        self.events.append(("download_cancelled",))

    def updater_will_extract_update(self, *, update):
        self.events.append(("will_extract", update))

    def updater_did_extract_update(self, *, update):
        self.events.append(("did_extract", update))

    def updater_will_install_update(self, *, update):
        self.events.append(("will_install", update))

    def updater_should_relaunch_application(self):
        return False

    def updater_will_relaunch_application(self):
        self.events.append(("will_relaunch",))

    def updater_will_schedule_update_check(self, *, delay):
        self.events.append(("schedule", delay))

    def updater_will_not_schedule_update_check(self):
        self.events.append(("not_scheduled",))

    def decryption_password_for_updater(self):
        return "secret"

    def updater_did_abort(self, *, error):
        self.events.append(("abort", error))


class _PartialDelegate:
    """只实现一个回调。"""

    def feed_url_string_for_updater(self):
        return "https://example.com/partial.xml"


class _EmptyDelegate:
    """什么都不实现（空对象）。"""


class _FakeItem:
    def versionString(self):
        return "2"

    def displayVersionString(self):
        return "2.0"


class _FakeState:
    def stage(self):
        return 1

    def userInitiated(self):
        return True


# ---------------------------------------------------------------------------
# _has 工具
# ---------------------------------------------------------------------------


def test_has_detects_defined_method():
    assert _has(_FullDelegate(), "feed_url_string_for_updater") is True
    assert _has(_EmptyDelegate(), "feed_url_string_for_updater") is False


def test_has_treats_none_attribute_as_absent():
    class _NoneAttr:
        feed_url_string_for_updater = None

    assert _has(_NoneAttr(), "feed_url_string_for_updater") is False


# ---------------------------------------------------------------------------
# Protocol 运行时检查
# ---------------------------------------------------------------------------


def test_protocol_runtime_check_is_not_required():
    # UpdaterDelegate 是 runtime_checkable，但我们的设计允许鸭子类型：
    # 实现部分方法即可，不强制 isinstance。
    obj = _FullDelegate()
    # feed_url 存在即可，Protocol 仅用于文档/类型提示。
    assert callable(getattr(obj, "feed_url_string_for_updater", None))


# ---------------------------------------------------------------------------
# make_delegate_adapter 行为
# ---------------------------------------------------------------------------


def test_adapter_returns_none_for_none_delegate():
    assert make_delegate_adapter(None) is None


def test_adapter_forwards_feed_url():
    delegate = _FullDelegate()
    adapter = make_delegate_adapter(delegate)
    assert adapter is not None
    assert adapter.feedURLStringForUpdater_(None) == "https://example.com/feed.xml"
    allowed, error = adapter.updater_mayPerformUpdateCheck_error_(None, 1, None)
    assert allowed is False
    assert "forbids checking" in str(error)
    assert adapter.feedParametersForUpdater_sendingSystemProfile_(None, True) == (
        {"key": "cohort", "value": "beta"},
    )
    assert adapter.updaterShouldPromptForPermissionToCheckForUpdates_(None) is False
    assert adapter.allowedSystemProfileKeysForUpdater_(None) == ("cpuCount",)


def test_adapter_feed_url_none_when_not_implemented():
    adapter = make_delegate_adapter(_EmptyDelegate())
    assert adapter.feedURLStringForUpdater_(None) is None


def test_adapter_channels_empty_when_not_implemented():
    adapter = make_delegate_adapter(_EmptyDelegate())
    assert adapter.allowedChannelsForUpdater_(None) == frozenset()


def test_adapter_channels_returned_when_implemented():
    delegate = _FullDelegate()
    adapter = make_delegate_adapter(delegate)
    assert adapter.allowedChannelsForUpdater_(None) == frozenset({"beta"})
    item = _FakeItem()
    adapter.updater_didFindValidUpdate_(None, item)
    adapter.updater_willDownloadUpdate_withRequest_(None, item, None)
    adapter.updater_didDownloadUpdate_(None, item)
    adapter.updater_failedToDownloadUpdate_error_(None, item, Exception("x"))
    adapter.userDidCancelDownload_(None)
    adapter.updater_willExtractUpdate_(None, item)
    adapter.updater_didExtractUpdate_(None, item)
    adapter.updater_willInstallUpdate_(None, item)
    adapter.updater_userDidMakeChoice_forUpdate_state_(None, 1, item, _FakeState())
    adapter.updaterWillRelaunchApplication_(None)
    adapter.updater_willScheduleUpdateCheckAfterDelay_(None, 30.0)
    adapter.updaterWillNotScheduleUpdateCheck_(None)
    adapter.updater_didAbortWithError_(None, Exception("abort"))
    names = [event[0] for event in delegate.events]
    assert names == [
        "found",
        "will_download",
        "downloaded",
        "download_failed",
        "download_cancelled",
        "will_extract",
        "did_extract",
        "will_install",
        "choice",
        "will_relaunch",
        "schedule",
        "not_scheduled",
        "abort",
    ]


def test_adapter_channels_drive_filtering_when_empty():
    # delegate 未实现 allowed_channels → 返回空，Sparkle 侧即"不限制"。
    adapter = make_delegate_adapter(_EmptyDelegate())
    # allowedChannelsForUpdater_ 是两个 adapter 都暴露的方法。
    result = adapter.allowedChannelsForUpdater_(None)
    # 真实 adapter 返回 NSSet，stub 返回 frozenset；都应是空集合。
    assert len(result) == 0
    assert adapter.updater_mayPerformUpdateCheck_error_(None, 0, None) == (
        True,
        None,
    )
    assert adapter.updaterShouldRelaunchApplication_(None) is True
    assert adapter.decryptionPasswordForUpdater_(None) is None


def test_adapter_channels_drive_filtering_when_set():
    # delegate 实现 allowed_channels → 返回值驱动 Sparkle 的频道过滤。
    adapter = make_delegate_adapter(_FullDelegate())  # allowed = ("beta",)
    result = adapter.allowedChannelsForUpdater_(None)
    assert "beta" in result
    allowed, error = adapter.updater_shouldProceedWithUpdate_updateCheck_error_(
        None, _FakeItem(), 0, None
    )
    assert allowed is False
    assert "not updatable" in str(error)
    assert adapter.updater_shouldDownloadReleaseNotesForUpdate_(
        None, _FakeItem()
    ) is False
    assert adapter.updaterShouldRelaunchApplication_(None) is False
    assert adapter.decryptionPasswordForUpdater_(None) == "secret"


def test_adapter_partial_delegate_only_known_methods():
    adapter = make_delegate_adapter(_PartialDelegate())
    assert adapter.feedURLStringForUpdater_(None) == "https://example.com/partial.xml"
    # 未实现的返回默认。
    assert adapter.allowedChannelsForUpdater_(None) == frozenset()
