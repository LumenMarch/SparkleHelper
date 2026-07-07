"""Sparkle.framework 的运行时加载（进程级单例缓存）。

PyPI 上没有 ``pyobjc-framework-Sparkle``（PyObjC 只包装 Apple 系统框架，
Sparkle 是第三方），因此用 ``objc.loadBundle`` 在运行时把嵌入在
``.app`` 的 ``Contents/Frameworks/Sparkle.framework`` 动态加载进 Python。

加载策略（路径解析优先级，见 :func:`resolve_framework_path`）：
    1. 显式传入的 ``framework_path``
    2. 主 bundle 的 ``Contents/Frameworks/Sparkle.framework``
    3. 环境变量 ``SPARKLEHELPER_FRAMEWORK_PATH``
    4. wheel 内置的 ``Sparkle.framework``

加载一次后缓存到模块级，避免重复 loadBundle 带来的开销与潜在副作用。
"""

from __future__ import annotations

import os
import sys
from types import ModuleType
from typing import Optional

from ...errors import SparkleNotAvailableError

# ---------------------------------------------------------------------------
# 进程级缓存：load_sparkle 成功后写入，后续 get_sparkle 直接返回。
# ---------------------------------------------------------------------------

_sparkle_module: Optional[ModuleType] = None
"""已加载的 Sparkle 运行时模块（含 SPUStandardUpdaterController 等类）。"""

_sparkle_path: Optional[str] = None
"""已解析的 framework 磁盘路径，便于诊断与测试。"""

# Sparkle 必需的核心类名。加载后用 lookUpClass 校验它们存在，
# 以便在 framework 损坏/版本不符时给出明确错误而非延迟到调用点崩溃。
_REQUIRED_CLASSES = (
    "SPUStandardUpdaterController",
    "SPUUpdater",
)


def main_bundle_frameworks_path() -> Optional[str]:
    """返回主 bundle 内 Sparkle.framework 的路径，无法获取时返回 None。

    非 macOS 或未初始化 Cocoa 时 NSBundle 不可用，这里安全降级。

    实现说明：``NSBundle -pathForResource:ofType:inDirectory:`` 在
    PyInstaller 打包的 .app 下会返回 None（PyInstaller 生成的 Info.plist
    不含完整的资源映射，NSBundle 的资源查找失效）。因此这里用
    ``bundlePath`` 拼接 ``Contents/Frameworks/Sparkle.framework`` 并用
    ``os.path.isdir`` 验证——``bundlePath`` 在实测中对 PyInstaller .app
    可靠，能正确指向 .app 根目录。
    """
    try:
        from Foundation import NSBundle
    except ImportError:
        return None

    bundle = NSBundle.mainBundle()
    if bundle is None:
        return None

    # 优先用 privateFrameworksPath（标准 Frameworks 目录），不可用时
    # 退回 bundlePath + Contents/Frameworks 手动拼接。
    fw_dir = bundle.privateFrameworksPath()
    if not fw_dir:
        bundle_path = bundle.bundlePath()
        if not bundle_path:
            return None
        fw_dir = os.path.join(str(bundle_path), "Contents", "Frameworks")

    fw_path = os.path.join(str(fw_dir), "Sparkle.framework")
    return fw_path if os.path.isdir(fw_path) else None


def resolve_framework_path(explicit: Optional[str]) -> str:
    """按优先级解析 Sparkle.framework 的磁盘路径。

    返回绝对路径字符串。无法解析时抛
    :class:`~sparklehelper.errors.SparkleNotAvailableError`。
    """
    if explicit:
        path = os.path.expanduser(explicit)
        if os.path.isdir(path):
            return os.path.abspath(path)
        raise SparkleNotAvailableError(
            f"Specified Sparkle.framework path does not exist: {path}"
        )

    main_bundle = main_bundle_frameworks_path()
    if main_bundle and os.path.isdir(main_bundle):
        return main_bundle

    env_path = os.environ.get("SPARKLEHELPER_FRAMEWORK_PATH")
    if env_path:
        path = os.path.expanduser(env_path)
        if os.path.isdir(path):
            return os.path.abspath(path)
        raise SparkleNotAvailableError(
            f"SPARKLEHELPER_FRAMEWORK_PATH points to non-existent path: {path}"
        )

    from ..._framework import bundled_framework_path

    bundled_path = bundled_framework_path()
    if bundled_path.is_dir():
        return str(bundled_path)

    raise SparkleNotAvailableError(
        f"Bundled Sparkle.framework is missing: {bundled_path}. "
        "Reinstall sparklehelper or provide an explicit framework path."
    )


def _verify_classes(module: ModuleType) -> None:
    """校验 Sparkle 必需类已通过 loadBundle 注册到 ObjC 运行时。"""
    import objc

    missing = []
    for name in _REQUIRED_CLASSES:
        try:
            objc.lookUpClass(name)
        except objc.error:
            missing.append(name)
    if missing:
        raise SparkleNotAvailableError(
            f"Sparkle.framework loaded but missing classes: {missing}. "
            "The framework may be corrupted or incompatible "
            "(sparklehelper requires Sparkle 2.x)."
        )


def load_sparkle(framework_path: Optional[str] = None) -> ModuleType:
    """加载 Sparkle.framework 并返回注册了其符号的模块对象。幂等。

    重复调用返回第一次加载的结果（忽略后续的 ``framework_path``）。

    Raises:
        SparkleNotAvailableError: 非 macOS、找不到 framework、或缺少必需类。
    """
    global _sparkle_module, _sparkle_path
    if _sparkle_module is not None:
        return _sparkle_module

    if sys.platform != "darwin":
        raise SparkleNotAvailableError(
            "Sparkle is macOS-only (current platform: %s)" % sys.platform
        )

    # 路径解析不依赖 objc，先做；找不到 framework 时给出清晰指引，
    # 而不是因后续 import objc（本机可能未装 PyObjC）报无意义的 ModuleNotFoundError。
    path = resolve_framework_path(framework_path)

    import objc

    # loadBundle 把 framework 的 ObjC 类注入到给定 globals 字典。
    # 用一个临时 module 作为容器，便于缓存与类型标注。
    container: ModuleType = ModuleType("sparklehelper._sparkle_runtime")
    objc.loadBundle("Sparkle", container.__dict__, bundle_path=path)
    container.__file__ = path

    _verify_classes(container)

    _sparkle_module = container
    _sparkle_path = path
    return container


def get_sparkle() -> ModuleType:
    """返回已加载的 Sparkle 运行时；未加载则惰性触发 :func:`load_sparkle`。"""
    if _sparkle_module is None:
        return load_sparkle()
    return _sparkle_module


def is_loaded() -> bool:
    """Sparkle.framework 是否已成功加载（便于测试与诊断）。"""
    return _sparkle_module is not None


def loaded_path() -> Optional[str]:
    """已加载 framework 的磁盘路径；未加载时为 None。"""
    return _sparkle_path


def reset_for_test() -> None:
    """仅供测试：清空模块级缓存以便重新加载。"""
    global _sparkle_module, _sparkle_path
    _sparkle_module = None
    _sparkle_path = None


__all__ = [
    "load_sparkle",
    "get_sparkle",
    "is_loaded",
    "loaded_path",
    "reset_for_test",
    "resolve_framework_path",
    "main_bundle_frameworks_path",
]
