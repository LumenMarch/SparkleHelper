"""``SPUUpdaterDelegate`` 的 Python 抽象与 ObjC 桥接。

把用户的 Python 回调对象包装成声明了 ``SPUUpdaterDelegate`` 协议的 ObjC
对象（或无 runtime 时的纯 Python stub）。所有 ObjC selector 方法把回调
转发到用户的 Python 方法，并吞掉异常以避免越过 ObjC 边界导致崩溃。
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, Union, runtime_checkable

from ...types import (
    UpdateCheckKind,
    UpdateInfo,
    UserUpdateChoice,
    UserUpdateState,
    from_appcast_item,
    from_user_update_state,
)
from . import _loading

Decision = Union[bool, str]
"""True 表示允许，False 或错误消息字符串表示拒绝。"""

_LOGGER = logging.getLogger(__name__)

# delegate adapter ObjC 类缓存（惰性创建，全进程单例）。
_delegate_adapter_cls = None

_SELECTOR_CALLBACKS = {
    "feedURLStringForUpdater:": "feed_url_string_for_updater",
    "updater:mayPerformUpdateCheck:error:": "updater_may_perform_update_check",
    "allowedChannelsForUpdater:": "allowed_channels_for_updater",
    "feedParametersForUpdater:sendingSystemProfile:": "feed_parameters_for_updater",
    "updaterShouldPromptForPermissionToCheckForUpdates:": (
        "updater_should_prompt_for_permission_to_check_for_updates"
    ),
    "allowedSystemProfileKeysForUpdater:": "allowed_system_profile_keys_for_updater",
    "updater:didFindValidUpdate:": "updater_did_find_valid_update",
    "updaterDidNotFindUpdate:error:": "updater_did_not_find_update",
    "updater:shouldProceedWithUpdate:updateCheck:error:": (
        "updater_should_proceed_with_update"
    ),
    "updater:userDidMakeChoice:forUpdate:state:": "updater_user_did_make_choice",
    "updater:shouldDownloadReleaseNotesForUpdate:": (
        "updater_should_download_release_notes"
    ),
    "updater:willDownloadUpdate:withRequest:": "updater_will_download_update",
    "updater:didDownloadUpdate:": "updater_did_download_update",
    "updater:failedToDownloadUpdate:error:": "updater_failed_to_download_update",
    "userDidCancelDownload:": "user_did_cancel_download",
    "updater:willExtractUpdate:": "updater_will_extract_update",
    "updater:didExtractUpdate:": "updater_did_extract_update",
    "updater:willInstallUpdate:": "updater_will_install_update",
    "updaterShouldRelaunchApplication:": "updater_should_relaunch_application",
    "updaterWillRelaunchApplication:": "updater_will_relaunch_application",
    "updater:willScheduleUpdateCheckAfterDelay:": (
        "updater_will_schedule_update_check"
    ),
    "updaterWillNotScheduleUpdateCheck:": "updater_will_not_schedule_update_check",
    "decryptionPasswordForUpdater:": "decryption_password_for_updater",
    "updater:didAbortWithError:": "updater_did_abort",
    "updater:didFinishUpdateCycleForUpdateCheck:error:": "updater_did_finish_cycle",
}


@runtime_checkable
class UpdaterDelegate(Protocol):
    """Sparkle 2.9 更新策略与生命周期的可选 Python 回调集合。

    每个方法都是可选的——未实现的方法，adapter 用合理默认值。
    """

    def updater_may_perform_update_check(
        self, *, update_check: UpdateCheckKind
    ) -> Decision: ...

    def feed_url_string_for_updater(self) -> Optional[str]: ...

    def allowed_channels_for_updater(self) -> tuple[str, ...]: ...

    def feed_parameters_for_updater(
        self, *, sending_system_profile: bool
    ) -> tuple[dict[str, str], ...]: ...

    def updater_should_prompt_for_permission_to_check_for_updates(self) -> bool: ...

    def allowed_system_profile_keys_for_updater(
        self,
    ) -> Optional[tuple[str, ...]]: ...

    def updater_did_find_valid_update(self, *, update: UpdateInfo) -> None: ...

    def updater_did_not_find_update(self, *, error: Exception) -> None: ...

    def updater_should_proceed_with_update(
        self, *, update: UpdateInfo, update_check: UpdateCheckKind
    ) -> Decision: ...

    def updater_user_did_make_choice(
        self,
        *,
        choice: UserUpdateChoice,
        update: UpdateInfo,
        state: UserUpdateState,
    ) -> None: ...

    def updater_should_download_release_notes(self, *, update: UpdateInfo) -> bool: ...

    def updater_will_download_update(self, *, update: UpdateInfo) -> None: ...

    def updater_did_download_update(self, *, update: UpdateInfo) -> None: ...

    def updater_failed_to_download_update(
        self, *, update: UpdateInfo, error: Exception
    ) -> None: ...

    def user_did_cancel_download(self) -> None: ...

    def updater_will_extract_update(self, *, update: UpdateInfo) -> None: ...

    def updater_did_extract_update(self, *, update: UpdateInfo) -> None: ...

    def updater_will_install_update(self, *, update: UpdateInfo) -> None: ...

    def updater_should_relaunch_application(self) -> bool: ...

    def updater_will_relaunch_application(self) -> None: ...

    def updater_will_schedule_update_check(self, *, delay: float) -> None: ...

    def updater_will_not_schedule_update_check(self) -> None: ...

    def decryption_password_for_updater(self) -> Optional[str]: ...

    def updater_did_abort(self, *, error: Exception) -> None: ...

    def updater_did_finish_cycle(
        self,
        *,
        update_check: UpdateCheckKind,
        found_update: bool,
        error: Optional[Exception],
    ) -> None: ...


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _has(obj: Any, method_name: str) -> bool:
    """用户对象是否实现了指定方法。"""
    method = getattr(obj, method_name, None)
    return method is not None and callable(method)


def _selector_name(selector: Any) -> str:
    """PyObjC selector / bytes / str → Objective-C selector 名。"""
    value = getattr(selector, "selector", selector)
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore")
    return str(value)


def _invoke(
    delegate: Any,
    method_name: str,
    *,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """安全调用用户回调，避免异常越过 ObjC 边界。"""
    if not _has(delegate, method_name):
        return default
    try:
        return getattr(delegate, method_name)(**kwargs)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("UpdaterDelegate.%s callback failed", method_name)
        return default


def _to_exception(error: Any) -> Optional[Exception]:
    """NSError/Exception → Python Exception。"""
    if error is None:
        return None
    if isinstance(error, Exception):
        return error
    description = getattr(error, "localizedDescription", None)
    if callable(description):
        return Exception(str(description()))
    return Exception(str(error))


def _to_nserror(message: Optional[str]) -> Any:
    """Python 拒绝原因字符串 → NSError，供 error: out-parameter 使用。"""
    if message is None:
        return None
    from Foundation import NSLocalizedDescriptionKey, NSError

    return NSError.errorWithDomain_code_userInfo_(
        "sparklehelper",
        1,
        {NSLocalizedDescriptionKey: message},
    )


def _update_check_kind(value: Any) -> UpdateCheckKind:
    try:
        return UpdateCheckKind(int(value))
    except (TypeError, ValueError):
        return UpdateCheckKind.USER_INITIATED


def _user_update_choice(value: Any) -> UserUpdateChoice:
    try:
        return UserUpdateChoice(int(value))
    except (TypeError, ValueError):
        return UserUpdateChoice.DISMISS


def _decision(value: Any, default_message: str) -> tuple[bool, Optional[str]]:
    if isinstance(value, str):
        return False, value or default_message
    allowed = bool(value)
    return allowed, None if allowed else default_message


def _feed_parameters(value: Any) -> tuple[dict[str, str], ...]:
    if value is None:
        return ()
    try:
        return tuple(
            {str(key): str(item) for key, item in parameter.items()}
            for parameter in value
        )
    except (AttributeError, TypeError):
        return ()


# ---------------------------------------------------------------------------
# 共用事件转发实现（Python stub 与 ObjC adapter 共用）
# ---------------------------------------------------------------------------


class _DelegateMethods:
    """Python stub 与 ObjC adapter 共用的事件转发实现。"""

    _py_delegate: UpdaterDelegate
    _py_last_found: bool

    def _update_callback(self, method_name: str, item: Any) -> Any:
        if not _has(self._py_delegate, method_name):
            return None
        return _invoke(self._py_delegate, method_name, update=from_appcast_item(item))

    def feedURLStringForUpdater_(self, updater) -> Optional[str]:  # noqa: N802
        return _invoke(self._py_delegate, "feed_url_string_for_updater", default=None)

    def updater_didFindValidUpdate_(self, updater, item) -> None:  # noqa: N802
        self._py_last_found = True
        self._update_callback("updater_did_find_valid_update", item)

    def updaterDidNotFindUpdate_error_(self, updater, error) -> None:  # noqa: N802
        _invoke(
            self._py_delegate,
            "updater_did_not_find_update",
            error=_to_exception(error) or Exception("No valid update found"),
        )

    def updater_userDidMakeChoice_forUpdate_state_(  # noqa: N802
        self, updater, choice, item, state
    ) -> None:
        if not _has(self._py_delegate, "updater_user_did_make_choice"):
            return
        _invoke(
            self._py_delegate,
            "updater_user_did_make_choice",
            choice=_user_update_choice(choice),
            update=from_appcast_item(item),
            state=from_user_update_state(state),
        )

    def updater_willDownloadUpdate_withRequest_(  # noqa: N802
        self, updater, item, request
    ) -> None:
        self._update_callback("updater_will_download_update", item)

    def updater_didDownloadUpdate_(self, updater, item) -> None:  # noqa: N802
        self._update_callback("updater_did_download_update", item)

    def updater_failedToDownloadUpdate_error_(  # noqa: N802
        self, updater, item, error
    ) -> None:
        if not _has(self._py_delegate, "updater_failed_to_download_update"):
            return
        _invoke(
            self._py_delegate,
            "updater_failed_to_download_update",
            update=from_appcast_item(item),
            error=_to_exception(error) or Exception("Update download failed"),
        )

    def userDidCancelDownload_(self, updater) -> None:  # noqa: N802
        _invoke(self._py_delegate, "user_did_cancel_download")

    def updater_willExtractUpdate_(self, updater, item) -> None:  # noqa: N802
        self._update_callback("updater_will_extract_update", item)

    def updater_didExtractUpdate_(self, updater, item) -> None:  # noqa: N802
        self._update_callback("updater_did_extract_update", item)

    def updater_willInstallUpdate_(self, updater, item) -> None:  # noqa: N802
        self._update_callback("updater_will_install_update", item)

    def updaterWillRelaunchApplication_(self, updater) -> None:  # noqa: N802
        _invoke(self._py_delegate, "updater_will_relaunch_application")

    def updater_willScheduleUpdateCheckAfterDelay_(  # noqa: N802
        self, updater, delay
    ) -> None:
        _invoke(
            self._py_delegate,
            "updater_will_schedule_update_check",
            delay=float(delay),
        )

    def updaterWillNotScheduleUpdateCheck_(self, updater) -> None:  # noqa: N802
        _invoke(self._py_delegate, "updater_will_not_schedule_update_check")

    def updater_didAbortWithError_(self, updater, error) -> None:  # noqa: N802
        _invoke(
            self._py_delegate,
            "updater_did_abort",
            error=_to_exception(error) or Exception("Update check aborted"),
        )

    def updater_didFinishUpdateCycleForUpdateCheck_error_(  # noqa: N802
        self, updater, update_check, error
    ) -> None:
        _invoke(
            self._py_delegate,
            "updater_did_finish_cycle",
            update_check=_update_check_kind(update_check),
            found_update=self._py_last_found,
            error=_to_exception(error),
        )
        self._py_last_found = False


class _PythonDelegateStub(_DelegateMethods):
    """无 ObjC runtime 时使用的等价 Python 适配器。"""

    def __init__(self, delegate: UpdaterDelegate) -> None:
        self._py_delegate = delegate
        self._py_last_found = False

    def updater_mayPerformUpdateCheck_error_(  # noqa: N802
        self, updater, update_check, error
    ) -> tuple[bool, Optional[Exception]]:
        value = _invoke(
            self._py_delegate,
            "updater_may_perform_update_check",
            default=True,
            update_check=_update_check_kind(update_check),
        )
        allowed, message = _decision(value, "Update check denied by app")
        return allowed, Exception(message) if message else None

    def allowedChannelsForUpdater_(self, updater) -> frozenset[str]:  # noqa: N802
        channels = _invoke(self._py_delegate, "allowed_channels_for_updater", default=())
        return frozenset(channels or ())

    def feedParametersForUpdater_sendingSystemProfile_(  # noqa: N802
        self, updater, sending_profile
    ) -> tuple[dict[str, str], ...]:
        value = _invoke(
            self._py_delegate,
            "feed_parameters_for_updater",
            default=(),
            sending_system_profile=bool(sending_profile),
        )
        return _feed_parameters(value)

    def updaterShouldPromptForPermissionToCheckForUpdates_(  # noqa: N802
        self, updater
    ) -> bool:
        return bool(
            _invoke(
                self._py_delegate,
                "updater_should_prompt_for_permission_to_check_for_updates",
                default=True,
            )
        )

    def allowedSystemProfileKeysForUpdater_(self, updater):  # noqa: N802
        value = _invoke(
            self._py_delegate, "allowed_system_profile_keys_for_updater", default=None
        )
        return None if value is None else tuple(str(item) for item in value)

    def updater_shouldProceedWithUpdate_updateCheck_error_(  # noqa: N802
        self, updater, item, update_check, error
    ) -> tuple[bool, Optional[Exception]]:
        value = _invoke(
            self._py_delegate,
            "updater_should_proceed_with_update",
            default=True,
            update=from_appcast_item(item),
            update_check=_update_check_kind(update_check),
        )
        allowed, message = _decision(value, "App denied proceeding with this update")
        return allowed, Exception(message) if message else None

    def updater_shouldDownloadReleaseNotesForUpdate_(  # noqa: N802
        self, updater, item
    ) -> bool:
        return bool(
            _invoke(
                self._py_delegate,
                "updater_should_download_release_notes",
                default=True,
                update=from_appcast_item(item),
            )
        )

    def updaterShouldRelaunchApplication_(self, updater) -> bool:  # noqa: N802
        return bool(
            _invoke(self._py_delegate, "updater_should_relaunch_application", default=True)
        )

    def decryptionPasswordForUpdater_(self, updater) -> Optional[str]:  # noqa: N802
        return _invoke(self._py_delegate, "decryption_password_for_updater", default=None)


# ---------------------------------------------------------------------------
# ObjC adapter 类（惰性创建）
# ---------------------------------------------------------------------------


def _get_adapter_class() -> Any:
    """惰性创建并缓存 ObjC delegate 类。"""
    global _delegate_adapter_cls
    if _delegate_adapter_cls is not None:
        return _delegate_adapter_cls

    import objc
    from Foundation import (  # noqa: F401
        NSArray,
        NSDictionary,
        NSSet,
        NSObject,
    )

    protocol = objc.protocolNamed("SPUUpdaterDelegate")

    class _DelegateAdapter(NSObject, _DelegateMethods, protocols=[protocol]):
        """实现核心 ``SPUUpdaterDelegate`` 回调的 ObjC 适配器。"""

        @objc.python_method
        def initWithDelegate_(self, delegate):
            self = self.init()
            if self is None:
                return None
            self._py_delegate = delegate
            self._py_last_found = False
            return self

        def respondsToSelector_(self, selector):  # noqa: N802
            method_name = _SELECTOR_CALLBACKS.get(_selector_name(selector))
            if method_name is not None:
                return _has(self._py_delegate, method_name)
            return objc.super(_DelegateAdapter, self).respondsToSelector_(selector)

        def feedURLStringForUpdater_(self, updater):  # noqa: N802
            return _DelegateMethods.feedURLStringForUpdater_(self, updater)

        def updater_didFindValidUpdate_(self, updater, item):  # noqa: N802
            return _DelegateMethods.updater_didFindValidUpdate_(self, updater, item)

        def updaterDidNotFindUpdate_error_(self, updater, error):  # noqa: N802
            return _DelegateMethods.updaterDidNotFindUpdate_error_(self, updater, error)

        def updater_userDidMakeChoice_forUpdate_state_(  # noqa: N802
            self, updater, choice, item, state
        ):
            return _DelegateMethods.updater_userDidMakeChoice_forUpdate_state_(
                self, updater, choice, item, state
            )

        def updater_willDownloadUpdate_withRequest_(  # noqa: N802
            self, updater, item, request
        ):
            return _DelegateMethods.updater_willDownloadUpdate_withRequest_(
                self, updater, item, request
            )

        def updater_didDownloadUpdate_(self, updater, item):  # noqa: N802
            return _DelegateMethods.updater_didDownloadUpdate_(self, updater, item)

        def updater_failedToDownloadUpdate_error_(  # noqa: N802
            self, updater, item, error
        ):
            return _DelegateMethods.updater_failedToDownloadUpdate_error_(
                self, updater, item, error
            )

        def userDidCancelDownload_(self, updater):  # noqa: N802
            return _DelegateMethods.userDidCancelDownload_(self, updater)

        def updater_willExtractUpdate_(self, updater, item):  # noqa: N802
            return _DelegateMethods.updater_willExtractUpdate_(self, updater, item)

        def updater_didExtractUpdate_(self, updater, item):  # noqa: N802
            return _DelegateMethods.updater_didExtractUpdate_(self, updater, item)

        def updater_willInstallUpdate_(self, updater, item):  # noqa: N802
            return _DelegateMethods.updater_willInstallUpdate_(self, updater, item)

        def updaterWillRelaunchApplication_(self, updater):  # noqa: N802
            return _DelegateMethods.updaterWillRelaunchApplication_(self, updater)

        def updater_willScheduleUpdateCheckAfterDelay_(  # noqa: N802
            self, updater, delay
        ):
            return _DelegateMethods.updater_willScheduleUpdateCheckAfterDelay_(
                self, updater, delay
            )

        def updaterWillNotScheduleUpdateCheck_(self, updater):  # noqa: N802
            return _DelegateMethods.updaterWillNotScheduleUpdateCheck_(self, updater)

        def updater_didAbortWithError_(self, updater, error):  # noqa: N802
            return _DelegateMethods.updater_didAbortWithError_(self, updater, error)

        def updater_didFinishUpdateCycleForUpdateCheck_error_(  # noqa: N802
            self, updater, update_check, error
        ):
            return _DelegateMethods.updater_didFinishUpdateCycleForUpdateCheck_error_(
                self, updater, update_check, error
            )

        def updater_mayPerformUpdateCheck_error_(  # noqa: N802
            self, updater, update_check, error
        ):
            value = _invoke(
                self._py_delegate,
                "updater_may_perform_update_check",
                default=True,
                update_check=_update_check_kind(update_check),
            )
            allowed, message = _decision(value, "Update check denied by app")
            return allowed, _to_nserror(message)

        def allowedChannelsForUpdater_(self, updater):  # noqa: N802
            channels = _invoke(self._py_delegate, "allowed_channels_for_updater", default=())
            array = NSArray.arrayWithArray_(list(channels or ()))
            return NSSet.setWithArray_(array)

        def feedParametersForUpdater_sendingSystemProfile_(  # noqa: N802
            self, updater, sending_profile
        ):
            value = _invoke(
                self._py_delegate,
                "feed_parameters_for_updater",
                default=(),
                sending_system_profile=bool(sending_profile),
            )
            parameters = [
                NSDictionary.dictionaryWithDictionary_(parameter)
                for parameter in _feed_parameters(value)
            ]
            return NSArray.arrayWithArray_(parameters)

        def updaterShouldPromptForPermissionToCheckForUpdates_(  # noqa: N802
            self, updater
        ):
            return bool(
                _invoke(
                    self._py_delegate,
                    "updater_should_prompt_for_permission_to_check_for_updates",
                    default=True,
                )
            )

        def allowedSystemProfileKeysForUpdater_(self, updater):  # noqa: N802
            value = _invoke(
                self._py_delegate,
                "allowed_system_profile_keys_for_updater",
                default=None,
            )
            if value is None:
                return None
            return NSArray.arrayWithArray_([str(item) for item in value])

        def updater_shouldProceedWithUpdate_updateCheck_error_(  # noqa: N802
            self, updater, item, update_check, error
        ):
            value = _invoke(
                self._py_delegate,
                "updater_should_proceed_with_update",
                default=True,
                update=from_appcast_item(item),
                update_check=_update_check_kind(update_check),
            )
            allowed, message = _decision(value, "App denied proceeding with this update")
            return allowed, _to_nserror(message)

        def updater_shouldDownloadReleaseNotesForUpdate_(  # noqa: N802
            self, updater, item
        ):
            return bool(
                _invoke(
                    self._py_delegate,
                    "updater_should_download_release_notes",
                    default=True,
                    update=from_appcast_item(item),
                )
            )

        def updaterShouldRelaunchApplication_(self, updater) -> bool:  # noqa: N802
            return bool(
                _invoke(self._py_delegate, "updater_should_relaunch_application", default=True)
            )

        def decryptionPasswordForUpdater_(self, updater) -> Optional[str]:  # noqa: N802
            return _invoke(self._py_delegate, "decryption_password_for_updater", default=None)

    _delegate_adapter_cls = _DelegateAdapter
    return _delegate_adapter_cls


def make_delegate_adapter(delegate: Optional[UpdaterDelegate]) -> Any:
    """把用户 delegate 包装成 ObjC ``SPUUpdaterDelegate``。

    Sparkle 未加载（非 darwin / 测试环境）时降级返回
    :class:`_PythonDelegateStub`。
    """
    if delegate is None:
        return None
    try:
        adapter_cls = _get_adapter_class()
        return adapter_cls.alloc().initWithDelegate_(delegate)
    except Exception:  # noqa: BLE001
        if _loading.is_loaded():
            raise
        return _PythonDelegateStub(delegate)


__all__ = [
    "Decision",
    "UpdaterDelegate",
    "make_delegate_adapter",
    "_has",
]
