"""Nuitka 静态包配置。"""

from __future__ import annotations

from sparklehelper._framework import nuitka_config_path, nuitka_plugin_path


def test_config_collects_bundled_framework_on_macos() -> None:
    config = nuitka_config_path().read_text(encoding="utf-8")
    assert "raw_dirs:" in config
    assert "- 'Sparkle.framework'" in config
    assert "when: 'macos'" in config


def test_config_targets_frameworks_root_without_setup_code() -> None:
    config = nuitka_config_path().read_text(encoding="utf-8")
    assert "dest_path: '.'" in config
    assert "setup_code" not in config
    assert "prepare_framework" not in config


def test_plugin_restores_framework_links_before_signing() -> None:
    plugin = nuitka_plugin_path().read_text(encoding="utf-8")
    assert "_normalizeMacOSFrameworkBundleLayout" in plugin
    assert "restore_framework_symlinks" in plugin
    assert "framework_symlink_manifest_path" in plugin
    assert "createPlistInfoFile" in plugin
    assert "CFBundleVersion" in plugin
    assert "CFBundleShortVersionString" in plugin
    assert "NUITKA_SPARKLE_PLIST_OVERRIDES_ENV" in plugin
