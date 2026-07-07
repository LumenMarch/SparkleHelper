"""跨 ObjC 运行时的基础设施：主线程约束、bundle 解析、KVO 桥接。

这些是 macOS 集成中最容易踩坑的三件事：
1. **主线程约束**：Sparkle / Cocoa 绝大多数 API 必须在主线程调用。
2. **KVO 订阅**：``SPUUpdater.canCheckForUpdates`` 是 KVO-compliant。
3. **bundle 解析**：定位 ``.app`` bundle 路径、读取 ``Info.plist``。
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import threading
from typing import Any, Callable, Optional

from ...errors import NotABundleError, WrongThreadError

_LOGGER = logging.getLogger(__name__)

# 主线程标识。进程启动时缓存一次，避免反复查询（且与 PyObjC 主线程概念一致）。
_MAIN_THREAD = threading.main_thread()

# 缓存创建好的 KVO observer 类（惰性注册 NSObject 子类）。
_kvo_observer_cls = None


# ---------------------------------------------------------------------------
# 主线程约束
# ---------------------------------------------------------------------------


def assert_main_thread() -> None:
    """断言当前在主线程，否则抛 :class:`WrongThreadError`。

    把"Cocoa 在非主线程调用导致的不确定行为"转换成明确、可定位的异常。
    """
    if threading.current_thread() is not _MAIN_THREAD:
        raise WrongThreadError(
            "must be called on the main thread "
            f"(current: {threading.current_thread().name}); "
            "Sparkle/Cocoa APIs must not be used from background threads."
        )


def on_main_thread(func: Callable[..., Any]) -> Callable[..., Any]:
    """装饰器：保证被包装函数在主线程执行。

    - 已在主线程：直接同步调用。
    - 在后台线程：通过 ``AppHelper.callOnMainThread`` 同步派发并等待返回值。

    注意：后台线程派发会阻塞当前线程，不要在主线程递归调用（会死锁）。
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if threading.current_thread() is _MAIN_THREAD:
            return func(*args, **kwargs)
        from PyObjCTools import AppHelper

        def _invoker() -> Any:
            return func(*args, **kwargs)

        result_holder: dict[str, Any] = {}

        def _trampoline() -> None:
            try:
                result_holder["value"] = _invoker()
            except BaseException as exc:  # noqa: BLE001
                result_holder["error"] = exc

        AppHelper.callOnMainThread(_trampoline, True)
        if "error" in result_holder:
            raise result_holder["error"]
        return result_holder.get("value")

    return wrapper


# ---------------------------------------------------------------------------
# bundle 解析
# ---------------------------------------------------------------------------


def host_bundle_path() -> str:
    """返回宿主 ``.app`` bundle 的绝对路径（即 ``.../Foo.app``）。

    兼容 PyInstaller 打包（``sys.executable`` 形如 ``Foo.app/Contents/MacOS/Foo``）
    与解释器直接运行（抛 :class:`NotABundleError`）。
    """
    exe = sys.executable
    real = _find_app_ancestor(exe)
    if real is None:
        raise NotABundleError(
            f"current process is not inside a .app bundle "
            f"(sys.executable={exe}); Sparkle only runs inside a packaged "
            f"macOS .app — use py2app/PyInstaller, or launch from an "
            f"interpreter inside the .app."
        )
    return real


def _find_app_ancestor(path: str) -> Optional[str]:
    """从 path 向上查找 ``*.app`` 路径段，找不到返回 None。

    仅按路径结构判断（``.app`` 后缀），不查文件系统：Sparkle 信任
    ``sys.executable`` 的 bundle 结构，做物理 isdir 检查反而会让
    单元测试（用假路径）和某些符号链接场景误判。
    """
    cur = path
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        basename = os.path.basename(cur.rstrip("/"))
        if basename.endswith(".app"):
            return cur
        parent = os.path.dirname(cur) or cur
        if parent == cur:
            break
        cur = parent
    return None


def in_app_bundle() -> bool:
    """当前进程是否运行在 ``.app`` bundle 内。"""
    try:
        host_bundle_path()
        return True
    except NotABundleError:
        return False


def bundle_info_plist() -> dict[str, Any]:
    """返回主 bundle 的 ``Info.plist`` 字典。

    非 macOS 或 NSBundle 不可用时返回空 dict（便于在 CI/非 darwin 上导入）。
    """
    try:
        from Foundation import NSBundle
    except ImportError:
        return {}

    bundle = NSBundle.mainBundle()
    if bundle is None:
        return {}
    info = bundle.infoDictionary()
    if info is None:
        return {}
    # PyObjC 已把 NSString/NSNumber 桥接成 Python 标量，显式复制更安全。
    return {str(k): v for k, v in info.items()}


# ---------------------------------------------------------------------------
# KVO 桥接
# ---------------------------------------------------------------------------


def _objc_super_init(self: Any) -> Any:
    """调用 NSObject 的 init，兼容 PyObjC 的 super() 用法差异。"""
    try:
        return self.init()
    except Exception:  # noqa: BLE001
        _LOGGER.warning("NSObject init 失败，KVO observer 创建将返回 None", exc_info=True)
        return None


def _make_kvo_observer_class() -> Any:
    """惰性创建并返回 KVO observer 的 ObjC 子类。

    放在函数内、惰性执行，以便在非 darwin 平台导入本模块时不触发
    NSObject 子类注册（那会要求 Cocoa 已初始化）。
    """
    from Foundation import NSObject

    class _KVOObserver(NSObject):
        """把 ObjC ``observeValueForKeyPath:...`` 转发到 Python callable。

        持有 ``py_callback`` 的强引用，防止观察期间被 GC。
        """

        def initWithCallback_target_keyPath_(  # noqa: N802
            self, callback, target, key_path
        ):
            self = _objc_super_init(self)
            if self is None:
                return None
            self._py_callback = callback
            self._py_target = target
            self._py_key_path = key_path
            return self

        def observeValueForKeyPath_ofObject_change_context_(  # noqa: N802
            self, key_path, obj, change, context
        ):
            try:
                from Foundation import NSKeyValueChangeNewKey

                new_value = change.get(NSKeyValueChangeNewKey) if change else None
                self._py_callback(new_value)
            except Exception:  # noqa: BLE001
                # KVO 回调里绝不能抛 ObjC 异常，否则会崩溃。
                _LOGGER.exception("KVO callback %s 抛出异常", self._py_callback)

    return _KVOObserver


def get_kvo_observer_class() -> Any:
    """惰性创建并缓存 KVO observer 的 ObjC 子类（全进程单例）。"""
    global _kvo_observer_cls
    if _kvo_observer_cls is None:
        _kvo_observer_cls = _make_kvo_observer_class()
    return _kvo_observer_cls


# ---------------------------------------------------------------------------
# Subscription：KVO 订阅句柄（平台中立的纯 Python）
# ---------------------------------------------------------------------------


class Subscription:
    """KVO 订阅句柄。持有 observer 强引用，``cancel`` 或离开 ``with`` 注销。"""

    __slots__ = ("_observer", "_target", "_key_path", "_cancelled")

    def __init__(self, *, observer: Any, target: Any, key_path: str) -> None:
        self._observer = observer
        self._target = target
        self._key_path = key_path
        self._cancelled = False

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        try:
            self._target.removeObserver_forKeyPath_(self._observer, self._key_path)
        except Exception:  # noqa: BLE001
            pass
        self._observer = None

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.cancel()

    def __del__(self) -> None:
        try:
            self.cancel()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "assert_main_thread",
    "on_main_thread",
    "host_bundle_path",
    "in_app_bundle",
    "bundle_info_plist",
    "get_kvo_observer_class",
    "Subscription",
]
