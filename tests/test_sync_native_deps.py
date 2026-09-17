"""sync_native_deps：archive 成员解析与 provenance，不联网。"""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_native_deps.py"


def _load_sync():
    spec = importlib.util.spec_from_file_location("sync_native_deps", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_named_member_prefers_exact_path():
    sync = _load_sync()
    names = [
        "WinSparkle-0.9.4/x64/Release/WinSparkle.dll",
        "WinSparkle-0.9.4/Win32/Release/WinSparkle.dll",
    ]
    assert (
        sync.resolve_named_member(
            names, "WinSparkle-0.9.4/Win32/Release/WinSparkle.dll"
        )
        == "WinSparkle-0.9.4/Win32/Release/WinSparkle.dll"
    )


def test_resolve_named_member_finds_moved_basename():
    sync = _load_sync()
    names = ["WinSparkle-0.9.4/Release/WinSparkle.dll"]
    resolved = sync.resolve_named_member(
        names, "WinSparkle-0.9.4/Win32/Release/WinSparkle.dll"
    )
    assert resolved == "WinSparkle-0.9.4/Release/WinSparkle.dll"


def test_resolve_named_member_missing_lists_archive():
    sync = _load_sync()
    with pytest.raises(sync.NativeSyncError, match="顶层|成员预览") as exc:
        sync.resolve_named_member(["README.txt"], "bin/sign_update")
    assert "README.txt" in str(exc.value)
    assert "bin/sign_update" in str(exc.value)


def test_resolve_framework_prefix_nested_layout():
    sync = _load_sync()
    names = [
        "Sparkle-2.10.0/Sparkle.framework/Versions/B/Sparkle",
        "Sparkle-2.10.0/Sparkle.framework/Versions/Current",
    ]
    assert (
        sync.resolve_framework_prefix(names, "Sparkle.framework")
        == "Sparkle-2.10.0/Sparkle.framework"
    )


def test_extract_zip_moved_member(tmp_path, monkeypatch):
    sync = _load_sync()
    archive = tmp_path / "WinSparkle-9.9.9.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("WinSparkle-9.9.9/Release/WinSparkle.dll", b"dll")
    resolved = sync.resolve_named_member(
        zipfile.ZipFile(archive).namelist(),
        "WinSparkle-9.9.9/Win32/Release/WinSparkle.dll",
    )
    assert resolved.endswith("Release/WinSparkle.dll")


def test_extract_tar_moved_tool(tmp_path):
    sync = _load_sync()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="relocated/sign_update")
        data = b"tool"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r") as tar:
        dest = tmp_path / "out"
        dest.mkdir()
        sync._extract_tar_files(tar, dest, {"bin/sign_update": "bin/sign_update"})
    assert (dest / "bin" / "sign_update").read_bytes() == b"tool"


def test_offline_pin_mismatch(monkeypatch, tmp_path):
    sync = _load_sync()
    provenance = tmp_path / "native-provenance.json"
    provenance.write_text(
        json.dumps({"sparkle": {"tag": "2.9.4", "archive": "x", "sha256": "0"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "_provenance_path", lambda: provenance)
    with pytest.raises(sync.NativeSyncError, match="2.10.0"):
        sync._offline_pin_matches("sparkle", "2.10.0")


def test_offline_pin_matches(monkeypatch, tmp_path):
    sync = _load_sync()
    provenance = tmp_path / "native-provenance.json"
    provenance.write_text(
        json.dumps({"sparkle": {"tag": "2.10.0"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "_provenance_path", lambda: provenance)
    sync._offline_pin_matches("sparkle", "2.10.0")


def test_native_info_prints_provenance(tmp_path, monkeypatch, capsys):
    from sparklehelper import _framework

    record = {"sparkle": {"tag": "2.10.0", "sha256": "abc"}}
    path = tmp_path / "native-provenance.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(_framework, "bundled_native_provenance_path", lambda: path)
    rc = _framework.main(["native-info"])
    assert rc == 0
    assert "2.10.0" in capsys.readouterr().out
