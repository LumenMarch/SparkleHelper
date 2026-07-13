from __future__ import annotations

import importlib.util
import os
import platform
import struct
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel


_PACKAGE_DIR = Path(__file__).parent / "src" / "sparklehelper"
_FRAMEWORK_DIR = _PACKAGE_DIR / "Sparkle.framework"
_FRAMEWORK_SYMLINK_MANIFEST = _PACKAGE_DIR / "Sparkle.framework.symlinks.json"
_WINSPARKLE_DIR = _PACKAGE_DIR / "winsparkle"
_LICENSE_DIR = _PACKAGE_DIR / "licenses"


def _run_native_sync() -> None:
    """在 wheel 构建阶段延迟加载并执行 native 资源同步。

    通过文件路径加载 ``scripts/sync_native_deps.py``，避免把它当作包导入；
    同步逻辑惰性执行，setup.py 顶层 / egg_info / sdist / metadata 阶段不会联网。
    """
    sync_path = Path(__file__).parent / "scripts" / "sync_native_deps.py"
    spec = importlib.util.spec_from_file_location(
        "_sparklehelper_sync_native_deps", sync_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.sync()


def _write_framework_symlink_manifest() -> None:
    """在 wheel 构建阶段记录 Sparkle.framework 当前符号链接布局。"""
    framework_module_path = _PACKAGE_DIR / "_framework.py"
    spec = importlib.util.spec_from_file_location(
        "_sparklehelper_framework", framework_module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write_framework_symlink_manifest(
        _FRAMEWORK_DIR,
        _FRAMEWORK_SYMLINK_MANIFEST,
    )


def _add_existing_license(files: set[str], filename: str) -> None:
    """只收集构建期已经同步出来的第三方 license。"""
    license_file = _LICENSE_DIR / filename
    if license_file.is_file():
        files.add(str(license_file.relative_to(_PACKAGE_DIR)))


def _macos_package_data() -> list[str]:
    """macOS：收集 Sparkle.framework、发布工具与共享文件。"""
    files = {
        "bin/BinaryDelta",
        "bin/generate_appcast",
        "bin/generate_keys",
        "bin/sign_update",
        "sparklehelper.nuitka-package.config.yml",
    }
    _add_existing_license(files, "Sparkle-LICENSE.txt")
    if _FRAMEWORK_SYMLINK_MANIFEST.is_file():
        files.add(str(_FRAMEWORK_SYMLINK_MANIFEST.relative_to(_PACKAGE_DIR)))

    for root, dirnames, filenames in os.walk(_FRAMEWORK_DIR, followlinks=False):
        root_path = Path(root)
        # 跳过符号链接目录（framework 的 Versions/Current 等由打包工具重建）。
        dirnames[:] = [
            dirname for dirname in dirnames if not (root_path / dirname).is_symlink()
        ]
        for filename in filenames:
            files.add(str((root_path / filename).relative_to(_PACKAGE_DIR)))

    return sorted(files)


def _windows_package_data() -> list[str]:
    """Windows：收集 WinSparkle.dll、发布工具、头文件与 LICENSE。

    收集全部 3 个架构（x64/x86/arm64）：CI 为每个架构各产一个 wheel
    （win_amd64 / win32 / win_arm64），运行时按进程架构选用对应 DLL；
    单 wheel 内三架构冗余换取 pip 平台 tag 过滤的兼容性。
    x64 与 ARM64 wheel 额外携带官方 x64 发布工具；x86 wheel 不携带。
    """
    files = {
        "sparklehelper.nuitka-package.config.yml",
        "winsparkle/winsparkle.h",
    }
    if struct.calcsize("P") * 8 == 64:
        files.add("bin/winsparkle-tool.exe")
    _add_existing_license(files, "WinSparkle-LICENSE.txt")
    for arch in ("x64", "x86", "arm64"):
        dll = _WINSPARKLE_DIR / arch / "WinSparkle.dll"
        if dll.is_file():
            files.add(str(dll.relative_to(_PACKAGE_DIR)))
    return sorted(files)


def _package_data() -> list[str]:
    """按构建平台收集二进制资源。"""
    if sys.platform == "win32":
        return _windows_package_data()
    return _macos_package_data()


class _MacOSUniversal2Wheel(bdist_wheel):
    """生成包含 macOS universal2 二进制的非纯 Python wheel。"""

    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        return "py3", "none", "macosx_11_0_universal2"

    def run(self) -> None:
        # 同步 native 资源后必须重新计算 package_data：setup() 调用时 framework
        # 可能尚未生成，_package_data() 会得到空列表，需在 build_py 执行前刷新。
        _run_native_sync()
        _write_framework_symlink_manifest()
        self.distribution.package_data["sparklehelper"] = _package_data()
        super().run()


class _WindowsWheel(bdist_wheel):
    """按构建进程架构选 Windows 平台 tag。

    64 位 Python → ``win_amd64``，32 位 → ``win32``，ARM → ``win_arm64``。
    与运行时 ``_loading.current_arch()`` 同逻辑，确保 wheel tag 与内置
    DLL 架构匹配。
    """

    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        bits = struct.calcsize("P") * 8
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64") or "arm" in machine:
            return "py3", "none", "win_arm64"
        return "py3", "none", "win_amd64" if bits == 64 else "win32"

    def run(self) -> None:
        # 同步 native 资源后必须重新计算 package_data：setup() 调用时 DLL 可能
        # 尚未生成，_package_data() 会得到空列表，需在 build_py 执行前刷新。
        _run_native_sync()
        self.distribution.package_data["sparklehelper"] = _package_data()
        super().run()


def _select_wheel_cmdclass() -> type[bdist_wheel]:
    """按构建平台选择 wheel cmdclass。"""
    if sys.platform == "win32":
        return _WindowsWheel
    return _MacOSUniversal2Wheel


setup(
    include_package_data=False,
    package_data={"sparklehelper": _package_data()},
    cmdclass={"bdist_wheel": _select_wheel_cmdclass()},
)
