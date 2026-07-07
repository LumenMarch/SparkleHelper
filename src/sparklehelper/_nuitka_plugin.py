"""修正 Nuitka 对 Sparkle.framework 的链接归一化。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib

from nuitka.plugins.PluginBase import NuitkaPluginBase

from sparklehelper._framework import (
    NUITKA_CF_BUNDLE_SHORT_VERSION_ENV,
    NUITKA_CF_BUNDLE_VERSION_ENV,
    NUITKA_SPARKLE_PLIST_OVERRIDES_ENV,
    _nuitka_bundle_versions,
    framework_symlink_manifest_path,
    restore_framework_symlinks,
)

_FRAMEWORK_NAME = "Sparkle.framework"


def _restore_framework_links(framework_path: str) -> None:
    """将 wheel 中实体化的 framework 条目恢复为标准符号链接。"""
    if os.path.basename(framework_path) != _FRAMEWORK_NAME:
        return
    restore_framework_symlinks(framework_path, framework_symlink_manifest_path())


def _bundle_info_plist_path() -> Path:
    """返回 Nuitka 生成中的 macOS bundle Info.plist 路径。"""
    from nuitka.OutputDirectories import (
        getResultRunFilename,
        getStandaloneDirectoryPath,
    )
    from nuitka.options.Options import isStandaloneMode

    if isStandaloneMode():
        bundle_dir = os.path.dirname(
            getStandaloneDirectoryPath(bundle=True, real=False)
        )
    else:
        bundle_dir = os.path.dirname(getResultRunFilename(onefile=False))
    return Path(bundle_dir) / "Info.plist"


def _patch_info_plist(plist_path: Path) -> None:
    """写入 Sparkle 读取的 bundle 版本字段。"""
    if not plist_path.is_file():
        return

    build_version = os.environ.get(NUITKA_CF_BUNDLE_VERSION_ENV)
    display_version = os.environ.get(NUITKA_CF_BUNDLE_SHORT_VERSION_ENV)
    try:
        plist_overrides = json.loads(
            os.environ.get(NUITKA_SPARKLE_PLIST_OVERRIDES_ENV, "{}")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"环境变量 {NUITKA_SPARKLE_PLIST_OVERRIDES_ENV} 的值不是合法 JSON: "
            f"{os.environ.get(NUITKA_SPARKLE_PLIST_OVERRIDES_ENV, '')!r}"
        ) from exc
    info = plistlib.loads(plist_path.read_bytes())
    changed = False

    for key, value in plist_overrides.items():
        if info.get(key) != value:
            info[key] = value
            changed = True

    if build_version and info.get("CFBundleVersion") != build_version:
        info["CFBundleVersion"] = build_version
        changed = True
    if (
        display_version
        and info.get("CFBundleShortVersionString") != display_version
    ):
        info["CFBundleShortVersionString"] = display_version
        changed = True
    if not build_version and not str(info.get("CFBundleVersion") or "").strip():
        source_version = str(info.get("CFBundleShortVersionString") or "").strip()
        if source_version:
            try:
                info["CFBundleVersion"] = _nuitka_bundle_versions(
                    version=source_version
                )["build"]
            except ValueError as exc:
                raise ValueError(
                    f"无法从 Info.plist 的 CFBundleShortVersionString "
                    f"({source_version!r}) 推导 CFBundleVersion: {exc}"
                ) from exc
            changed = True

    if changed:
        plist_path.write_bytes(plistlib.dumps(info, sort_keys=False))


def _patch_plist_creator() -> None:
    from nuitka.freezer import MacOSApp
    import nuitka.PostProcessing as PostProcessing

    original = MacOSApp.createPlistInfoFile
    if getattr(original, "_sparklehelper_plist_wrapped", False):
        return

    def create_plist_info_file(logger) -> None:
        original(logger=logger)
        _patch_info_plist(_bundle_info_plist_path())

    create_plist_info_file._sparklehelper_plist_wrapped = True
    MacOSApp.createPlistInfoFile = create_plist_info_file
    PostProcessing.createPlistInfoFile = create_plist_info_file


def _patch_framework_normalizer() -> None:
    from nuitka.freezer import Standalone

    original = Standalone._normalizeMacOSFrameworkBundleLayout
    if getattr(original, "_sparklehelper_wrapped", False):
        return

    def normalize_framework(framework_path: str) -> None:
        original(framework_path)
        _restore_framework_links(framework_path)

    normalize_framework._sparklehelper_wrapped = True
    Standalone._normalizeMacOSFrameworkBundleLayout = normalize_framework


class SparkleHelperNuitkaPlugin(NuitkaPluginBase):
    """扩展 Nuitka 的 macOS framework 归一化阶段。"""

    plugin_name = "sparklehelper-framework"
    plugin_desc = "Restore Sparkle.framework symlinks and bundle versions."

    def onBeforeCodeParsing(self) -> None:
        _patch_framework_normalizer()
        _patch_plist_creator()
