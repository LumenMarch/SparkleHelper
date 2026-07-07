"""Sparkle 数据对象的 Python 表示。

把 ObjC 的 ``SUAppcastItem``、``SPUUpdateCheck`` 与系统配置项翻译成
纯 Python 类型，让用户代码不需要直接操作 PyObjC 对象。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Optional


class UpdateCheckKind(IntEnum):
    """对应 Sparkle 2.9 的 ``SPUUpdateCheck``。"""

    USER_INITIATED = 0
    BACKGROUND = 1
    INFORMATION = 2


class UserUpdateChoice(IntEnum):
    """对应 Sparkle 2.9 的 ``SPUUserUpdateChoice``。"""

    SKIP = 0
    INSTALL = 1
    DISMISS = 2


class UserUpdateStage(IntEnum):
    """对应 Sparkle 2.9 的 ``SPUUserUpdateStage``。"""

    NOT_DOWNLOADED = 0
    DOWNLOADED = 1
    INSTALLING = 2


@dataclass(frozen=True)
class UpdateInfo:
    """对应 Sparkle 2.9 的 ``SUAppcastItem`` 公开属性。"""

    version_string: str
    """构建版本号，对应 ``CFBundleVersion``。"""

    display_version_string: str
    """展示版本号，对应 ``CFBundleShortVersionString``。"""

    file_url: Optional[str] = None
    """更新包下载地址；信息类更新可能没有下载地址。"""

    content_length: int = 0
    """更新包字节数；feed 未提供时为 0。"""

    info_url: Optional[str] = None
    information_only: bool = False
    title: Optional[str] = None
    publication_date: Optional[datetime] = None
    release_notes_url: Optional[str] = None
    full_release_notes_url: Optional[str] = None
    minimum_system_version: Optional[str] = None
    minimum_update_version: Optional[str] = None
    maximum_system_version: Optional[str] = None
    hardware_requirements: tuple[str, ...] = ()
    channel: Optional[str] = None
    installation_type: Optional[str] = None
    minimum_autoupdate_version: Optional[str] = None
    critical_update: bool = False
    os_string: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)
    """Sparkle 的 ``propertiesDictionary``，包含自定义 appcast 扩展。"""


@dataclass(frozen=True)
class SystemProfileEntry:
    """``systemProfileArray`` 中的一项系统配置。"""

    key: str
    value: str
    display_key: str
    display_value: str


@dataclass(frozen=True)
class UserUpdateState:
    """用户看到更新时的下载与安装状态。"""

    stage: UserUpdateStage
    user_initiated: bool


@dataclass(frozen=True)
class UpdateCheckResult:
    """一次更新检查的 Python 结果。"""

    found: bool
    latest: Optional[UpdateInfo] = None
    skipped: bool = False


def _objc_value(obj: Any, name: str) -> Any:
    """读取 ObjC selector 或测试桩属性。"""
    value = getattr(obj, name, None)
    if callable(value):
        try:
            return value()
        except TypeError:
            return None
    return value


def _nsstring_to_str(value: Any) -> Optional[str]:
    """NSString/Python str → str；nil/None → None。"""
    if value is None:
        return None
    result = str(value)
    return result or None


def _nsurl_to_str(value: Any) -> Optional[str]:
    """NSURL/Python str → str；nil/None → None。"""
    if value is None:
        return None
    absolute_string = getattr(value, "absoluteString", None)
    if callable(absolute_string):
        return _nsstring_to_str(absolute_string())
    if isinstance(value, str):
        return value or None
    return None


def _nsdate_to_datetime(value: Any) -> Optional[datetime]:
    """NSDate → UTC aware datetime；nil/None → None。"""
    if value is None:
        return None
    try:
        timestamp = float(value.timeIntervalSince1970())
    except (AttributeError, TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _collection_to_tuple_str(value: Any) -> tuple[str, ...]:
    """NSArray/NSSet → tuple[str, ...]；nil/None → 空元组。"""
    if value is None:
        return ()
    try:
        return tuple(str(item) for item in value)
    except TypeError:
        return ()


def _number_to_int(value: Any) -> int:
    """NSNumber/int → int；无效值 → 0。"""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _mapping_to_dict(value: Any) -> dict[str, Any]:
    """NSDictionary/Mapping → 使用字符串键的 dict。"""
    if value is None:
        return {}
    try:
        return {str(key): item for key, item in value.items()}
    except (AttributeError, TypeError):
        return {}


def from_appcast_item(item: Any) -> UpdateInfo:
    """从 ObjC ``SUAppcastItem`` 构造 :class:`UpdateInfo`。"""
    version_string = _nsstring_to_str(_objc_value(item, "versionString")) or ""
    display_version = _nsstring_to_str(
        _objc_value(item, "displayVersionString")
    )

    return UpdateInfo(
        version_string=version_string,
        display_version_string=display_version or version_string,
        file_url=_nsurl_to_str(_objc_value(item, "fileURL")),
        content_length=_number_to_int(_objc_value(item, "contentLength")),
        info_url=_nsurl_to_str(_objc_value(item, "infoURL")),
        information_only=bool(_objc_value(item, "isInformationOnlyUpdate")),
        title=_nsstring_to_str(_objc_value(item, "title")),
        publication_date=_nsdate_to_datetime(_objc_value(item, "date")),
        release_notes_url=_nsurl_to_str(_objc_value(item, "releaseNotesURL")),
        full_release_notes_url=_nsurl_to_str(
            _objc_value(item, "fullReleaseNotesURL")
        ),
        minimum_system_version=_nsstring_to_str(
            _objc_value(item, "minimumSystemVersion")
        ),
        minimum_update_version=_nsstring_to_str(
            _objc_value(item, "minimumUpdateVersion")
        ),
        maximum_system_version=_nsstring_to_str(
            _objc_value(item, "maximumSystemVersion")
        ),
        hardware_requirements=_collection_to_tuple_str(
            _objc_value(item, "hardwareRequirements")
        ),
        channel=_nsstring_to_str(_objc_value(item, "channel")),
        installation_type=_nsstring_to_str(
            _objc_value(item, "installationType")
        ),
        minimum_autoupdate_version=_nsstring_to_str(
            _objc_value(item, "minimumAutoupdateVersion")
        ),
        critical_update=bool(_objc_value(item, "isCriticalUpdate")),
        os_string=_nsstring_to_str(_objc_value(item, "osString")),
        properties=_mapping_to_dict(_objc_value(item, "propertiesDictionary")),
    )


def from_system_profile(entries: Any) -> list[SystemProfileEntry]:
    """从 ``SPUUpdater.systemProfileArray`` 构造系统配置列表。"""
    if entries is None:
        return []

    result: list[SystemProfileEntry] = []
    for entry in entries:
        if isinstance(entry, Mapping):
            value_for = entry.get
        else:
            value_for = lambda key, default=None: _objc_value(entry, key)
        result.append(
            SystemProfileEntry(
                key=_nsstring_to_str(value_for("key")) or "",
                value=_nsstring_to_str(value_for("value")) or "",
                display_key=_nsstring_to_str(value_for("displayKey")) or "",
                display_value=_nsstring_to_str(value_for("displayValue")) or "",
            )
        )
    return result


def from_user_update_state(state: Any) -> UserUpdateState:
    """从 ObjC ``SPUUserUpdateState`` 构造 Python 状态。"""
    stage_value = _number_to_int(_objc_value(state, "stage"))
    try:
        stage = UserUpdateStage(stage_value)
    except ValueError:
        stage = UserUpdateStage.NOT_DOWNLOADED
    return UserUpdateState(
        stage=stage,
        user_initiated=bool(_objc_value(state, "userInitiated")),
    )


__all__ = [
    "UpdateInfo",
    "SystemProfileEntry",
    "UpdateCheckKind",
    "UpdateCheckResult",
    "UserUpdateChoice",
    "UserUpdateStage",
    "UserUpdateState",
    "from_appcast_item",
    "from_system_profile",
    "from_user_update_state",
]
