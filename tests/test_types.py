"""types 模块：dataclass 与 ObjC→Python 转换。

用 stub 对象模拟 SUAppcastItem/NSDate/NSArray，验证字段映射、
nil→None、日期/数组转换、缺失字段容错。不依赖真实 Sparkle。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sparklehelper import types
from sparklehelper.types import (
    UpdateInfo,
    UserUpdateStage,
    from_appcast_item,
    from_user_update_state,
)


class _FakeNSDate:
    """模拟 NSDate：只暴露 timeIntervalSince1970()。"""

    def __init__(self, ts: float) -> None:
        self._ts = ts

    def timeIntervalSince1970(self) -> float:
        return self._ts


class _FakeAppcastItem:
    """最小化的 SUAppcastItem stub，按 PyObjC selector 形式暴露值。"""

    def __init__(self, **kw) -> None:
        self._values = kw

    def __getattr__(self, name):
        if name not in self._values:
            raise AttributeError(name)
        return lambda: self._values[name]


def test_update_info_is_frozen():
    info = UpdateInfo(version_string="1", display_version_string="1.0", file_url="u")
    with pytest.raises(Exception):  # FrozenInstanceError
        info.version_string = "2"  # type: ignore[misc]


def test_update_info_defaults():
    info = UpdateInfo(version_string="1", display_version_string="1.0", file_url="u")
    assert info.content_length == 0
    assert info.channel is None
    assert info.publication_date is None
    assert info.properties == {}


def test_from_appcast_item_full_mapping():
    item = _FakeAppcastItem(
        versionString="42",
        displayVersionString="1.2.3",
        fileURL="https://example.com/app.dmg",
        contentLength=12345,
        infoURL="https://example.com/info",
        isInformationOnlyUpdate=False,
        title="Version 1.2.3",
        releaseNotesURL="https://example.com/notes",
        fullReleaseNotesURL="https://example.com/full-notes",
        minimumSystemVersion="12.0",
        minimumUpdateVersion="30",
        maximumSystemVersion=None,
        hardwareRequirements=("arm64",),
        minimumAutoupdateVersion="40",
        channel="beta",
        date=_FakeNSDate(1_700_000_000.0),
        isCriticalUpdate=True,
        propertiesDictionary={"sparkle:custom": "value"},
    )
    info = from_appcast_item(item)
    assert info.version_string == "42"
    assert info.display_version_string == "1.2.3"
    assert info.file_url == "https://example.com/app.dmg"
    assert info.content_length == 12345
    assert info.info_url == "https://example.com/info"
    assert info.release_notes_url == "https://example.com/notes"
    assert info.minimum_system_version == "12.0"
    assert info.maximum_system_version is None
    assert info.minimum_autoupdate_version == "40"
    assert info.channel == "beta"
    assert info.hardware_requirements == ("arm64",)
    assert info.publication_date == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert info.critical_update is True
    assert info.properties == {"sparkle:custom": "value"}


def test_from_appcast_item_missing_fields_use_defaults():
    item = _FakeAppcastItem(versionString="5", displayVersionString="0.5")
    info = from_appcast_item(item)
    assert info.version_string == "5"
    assert info.display_version_string == "0.5"
    assert info.file_url is None
    assert info.content_length == 0
    assert info.channel is None
    assert info.publication_date is None


def test_display_version_falls_back_to_version():
    # displayVersionString 缺失时用 versionString。
    item = _FakeAppcastItem(versionString="99")
    info = from_appcast_item(item)
    assert info.display_version_string == "99"


def test_from_appcast_item_nsurl_absolute_string():
    # fileURL 是 NSURL 时走 absoluteString 路径。
    class _FakeURL:
        def absoluteString(self):
            return "https://example.com/x.zip"

    item = _FakeAppcastItem(versionString="1", fileURL=_FakeURL())
    info = from_appcast_item(item)
    assert info.file_url == "https://example.com/x.zip"


def test_nsdate_invalid_returns_none():
    item = _FakeAppcastItem(
        versionString="1",
        date=object(),  # 无 timeIntervalSince1970
    )
    info = from_appcast_item(item)
    assert info.publication_date is None


def test_from_system_profile_empty():
    assert types.from_system_profile(None) == []
    assert types.from_system_profile([]) == []


def test_from_system_profile_maps_entries():
    entries = [
        {
            "key": "macVersion",
            "value": "13.0",
            "displayKey": "macOS Version",
            "displayValue": "13.0",
        },
        {
            "key": "cpuCount",
            "value": "8",
            "displayKey": "Processor Count",
            "displayValue": "8",
        },
    ]
    result = types.from_system_profile(entries)
    assert len(result) == 2
    assert result[0].key == "macVersion"
    assert result[0].value == "13.0"
    assert result[0].display_key == "macOS Version"
    assert result[1].display_value == "8"

    class _State:
        def stage(self):
            return 2

        def userInitiated(self):
            return True

    state = from_user_update_state(_State())
    assert state.stage is UserUpdateStage.INSTALLING
    assert state.user_initiated is True
