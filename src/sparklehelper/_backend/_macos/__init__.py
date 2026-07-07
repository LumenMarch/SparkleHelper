"""macOS 后端包：Sparkle.framework 的加载与 ObjC 桥接。

把原 ``_objc`` / ``_bridge`` / ``delegates`` 三个模块的逻辑按功能边界拆分到
子模块，由 :class:`MacOSBackend` 组合，对外只暴露统一契约：

- :mod:`._loading`：Sparkle.framework 运行时加载（进程级缓存）
- :mod:`._runtime`：主线程约束 / bundle 解析 / KVO observer（进程级缓存）
- :mod:`._delegates`：``SPUUpdaterDelegate`` Python 抽象与 ObjC 适配器
- :mod:`._backend`：:class:`MacOSBackend` 类（组合上述三者）

非 darwin 安全
--------------
本包顶层不 import PyObjC / Foundation。所有 ObjC import 延迟到函数体内
惰性执行，保证非 darwin 平台 ``import sparklehelper._backend._macos``
不会触发 ObjC 类注册或导入失败。
"""

from __future__ import annotations

# MacOSBackend + 公共符号（运行时函数重导出，供 Updater / 测试直接用）。
from ._backend import MacOSBackend
from ._delegates import Decision, UpdaterDelegate, make_delegate_adapter
from ._runtime import (
    Subscription,
    assert_main_thread,
    bundle_info_plist,
    get_kvo_observer_class,
    host_bundle_path,
    in_app_bundle,
    on_main_thread,
)

__all__ = [
    "MacOSBackend",
    "UpdaterDelegate",
    "Decision",
    "Subscription",
    "make_delegate_adapter",
    "assert_main_thread",
    "on_main_thread",
    "host_bundle_path",
    "in_app_bundle",
    "bundle_info_plist",
    "get_kvo_observer_class",
]
