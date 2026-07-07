"""_framework 模块：内置 framework 与构建资源路径。"""

from __future__ import annotations

import plistlib

import pytest

from sparklehelper import _framework


def _sparkle_license_path():
    return (
        _framework.bundled_framework_path().parent
        / "licenses"
        / "Sparkle-LICENSE.txt"
    )


@pytest.mark.skipif(
    not _framework.bundled_framework_path().exists(),
    reason="Sparkle.framework 为构建期获取，未构建 wheel 时不存在",
)
def test_bundled_framework_has_version() -> None:
    framework = _framework.bundled_framework_path()
    plist_path = framework / "Versions" / "B" / "Resources" / "Info.plist"

    assert framework.is_dir()
    with plist_path.open("rb") as fh:
        info = plistlib.load(fh)
    assert isinstance(info["CFBundleShortVersionString"], str)
    assert info["CFBundleShortVersionString"]


@pytest.mark.skipif(
    not _sparkle_license_path().exists(),
    reason="Sparkle license 为构建期同步，未构建 wheel 时不存在",
)
def test_bundled_framework_includes_license() -> None:
    license_path = _sparkle_license_path()
    assert license_path.is_file()
    assert "Permission is hereby granted" in license_path.read_text(encoding="utf-8")


def test_nuitka_config_subcommand(capsys) -> None:
    rc = _framework.main(["nuitka-config"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == str(_framework.nuitka_config_path())


def test_nuitka_subcommand_forwards_arguments(monkeypatch) -> None:
    captured = []

    def fake_run(arguments):
        captured.extend(arguments)
        return 7

    monkeypatch.setattr(_framework, "_run_nuitka", fake_run)

    rc = _framework.main(["nuitka", "--mode=app", "demo.py"])

    assert rc == 7
    assert captured == ["--mode=app", "demo.py"]


def test_nuitka_subcommand_prints_wrapper_help(capsys) -> None:
    rc = _framework.main(["nuitka", "-h"])

    assert rc == 0
    output = capsys.readouterr().out
    assert "usage: sparklehelper nuitka" in output
    assert "--version VERSION" in output
    assert "--build-version BUILD_VERSION" in output
    assert "--sparkle-key KEY=VALUE" in output


def test_nuitka_default_version_is_used_without_native_version() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        ["--mode=app", "demo.py"]
    )

    assert arguments == ["--macos-app-version=0.1.0", "--mode=app", "demo.py"]
    assert options == {
        "versions": {"build": "1", "display": "0.1.0"},
        "plist": {},
    }


def test_nuitka_version_option_overrides_macos_bundle_versions() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        [
            "--macos-app-version=9.9",
            "--version",
            "v0.1.0",
            "demo.py",
        ]
    )

    assert arguments == ["--macos-app-version=0.1.0", "demo.py"]
    assert options == {
        "versions": {"build": "1", "display": "0.1.0"},
        "plist": {},
    }


def test_nuitka_build_version_option_overrides_derived_build_version() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        [
            "--version",
            "0.1.0",
            "--build-version",
            "42",
            "demo.py",
        ]
    )

    assert arguments == ["--macos-app-version=0.1.0", "demo.py"]
    assert options == {
        "versions": {"build": "42", "display": "0.1.0"},
        "plist": {},
    }


def test_nuitka_build_version_can_be_used_without_display_version() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        ["--build-version=42", "--macos-app-version", "0.1.0", "demo.py"]
    )

    assert arguments == ["--macos-app-version", "0.1.0", "demo.py"]
    assert options == {"versions": {"build": "42"}, "plist": {}}


def test_nuitka_build_version_uses_default_display_version() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        ["--build-version=42", "demo.py"]
    )

    assert arguments == ["--macos-app-version=0.1.0", "demo.py"]
    assert options == {
        "versions": {"build": "42", "display": "0.1.0"},
        "plist": {},
    }


def test_nuitka_without_version_keeps_native_version_arguments() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        ["--macos-app-version", "0.1.0", "demo.py"]
    )

    assert arguments == ["--macos-app-version", "0.1.0", "demo.py"]
    assert options == {"versions": None, "plist": {}}


def test_nuitka_bare_version_argument_is_forwarded() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(["--version"])

    assert arguments == ["--version"]
    assert options == {"versions": None, "plist": {}}


def test_nuitka_sparkle_options_are_plist_overrides() -> None:
    arguments, options = _framework._prepare_nuitka_arguments(
        [
            "--feed-url",
            "https://example.com/appcast.xml",
            "--public-ed-key=abc",
            "--no-su-enable-automatic-checks",
            "--scheduled-check-interval",
            "3600",
            "--sparkle-key",
            "SUAllowedURLSchemes=https,sparkle",
            "--mode=app",
            "demo.py",
        ]
    )

    assert arguments == ["--macos-app-version=0.1.0", "--mode=app", "demo.py"]
    assert options == {
        "versions": {"build": "1", "display": "0.1.0"},
        "plist": {
            "SUFeedURL": "https://example.com/appcast.xml",
            "SUPublicEDKey": "abc",
            "SUEnableAutomaticChecks": False,
            "SUScheduledCheckInterval": 3600,
            "SUAllowedURLSchemes": ["https", "sparkle"],
        },
    }


def test_nuitka_command_injects_bundled_resources() -> None:
    command = _framework._nuitka_command(["demo.py"])

    assert f"--user-plugin={_framework.nuitka_plugin_path()}" in command
    assert (
        f"--user-package-configuration-file={_framework.nuitka_config_path()}"
        in command
    )
    assert command[-1] == "demo.py"
