"""构建期同步 Sparkle / WinSparkle native 资源。

只用 Python 标准库（GitHub latest release API、``urllib`` 下载、``hashlib``
校验、``tarfile`` / ``zipfile`` 解包），在 ``uv build --wheel`` 阶段把上游
预编译 runtime 与发布工具准备到位。运行时 API 与 loader 路径约定均不改变。

设计要点：

- 模块顶层只定义常量与函数，**不做任何 IO**，确保被 setup.py 导入时不产生
  副作用（sdist / egg_info / metadata 解析阶段不会联网）。
- 仅当真实构建 wheel 时由 ``setup.py`` 调用 ``sync()``。
- 仓库根目录的 ``Sparkle/`` 与 ``winsparkle/`` submodule 只用于展示上游源码
  提交；最小 wheel 构建路径使用上游 latest release asset。
- 第三方 license 文件随对应 latest release tag 同步，保证 wheel 内 native
  产物与上游许可证来自同一版本。
- 下载结果缓存于 ``build/native-cache/``，缓存 archive 的 SHA256 匹配则复用。
- ``SPARKLEHELPER_SKIP_NATIVE_SYNC=1`` 禁止联网；此时目标缺失即报错。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

#: 仓库根目录（本脚本位于 ``scripts/`` 下）。
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_DIR = _REPO_ROOT / "src" / "sparklehelper"
_CACHE_DIR = _REPO_ROOT / "build" / "native-cache"

#: 设为 ``1`` 时禁止联网同步；目标缺失即构建失败。
SKIP_ENV = "SPARKLEHELPER_SKIP_NATIVE_SYNC"

# Sparkle.framework 上游资产（universal2，macOS 11+）。
_SPARKLE = {
    "repo": "sparkle-project/Sparkle",
    "asset_pattern": r"^Sparkle-(?P<version>.+)\.tar\.xz$",
    "extract_root": "Sparkle.framework",
    "tools": {
        "bin/BinaryDelta": "bin/BinaryDelta",
        "bin/generate_appcast": "bin/generate_appcast",
        "bin/generate_keys": "bin/generate_keys",
        "bin/sign_update": "bin/sign_update",
    },
    "license": {
        "source": "LICENSE",
        "target": "licenses/Sparkle-LICENSE.txt",
    },
}

# WinSparkle 上游资产：zip 内路径 -> 包内目标相对路径（相对 _PACKAGE_DIR）。
_WINSPARKLE = {
    "repo": "vslavik/winsparkle",
    "asset_pattern": r"^WinSparkle-(?P<version>[0-9][0-9A-Za-z.]*)\.zip$",
    "license": {
        "source": "COPYING",
        "target": "licenses/WinSparkle-LICENSE.txt",
    },
    "extract": {
        "WinSparkle-{version}/x64/Release/WinSparkle.dll": "winsparkle/x64/WinSparkle.dll",
        "WinSparkle-{version}/Release/WinSparkle.dll": "winsparkle/x86/WinSparkle.dll",
        "WinSparkle-{version}/ARM64/Release/WinSparkle.dll": "winsparkle/arm64/WinSparkle.dll",
    },
    "tool": {
        "source": "WinSparkle-{version}/bin/winsparkle-tool.exe",
        "target": "bin/winsparkle-tool.exe",
    },
}


class NativeSyncError(RuntimeError):
    """native 资源同步失败（下载/校验/解包路径缺失/离线缺失）。"""


def _skip_sync_enabled() -> bool:
    return os.environ.get(SKIP_ENV) == "1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _github_request(url: str) -> urllib.request.Request:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "SparkleHelper-native-sync",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return request


def _read_github_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(_github_request(url)) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        raise NativeSyncError(
            f"读取 GitHub release 信息失败: {url}\n"
            f"  {exc}\n"
            "请检查网络后重新运行 `uv build --wheel`。"
        ) from exc


def _read_github_file(repo: str, source: str, ref: str) -> bytes:
    quoted_source = urllib.parse.quote(source, safe="/")
    quoted_ref = urllib.parse.quote(ref, safe="")
    data = _read_github_json(
        f"https://api.github.com/repos/{repo}/contents/{quoted_source}"
        f"?ref={quoted_ref}"
    )
    content = data.get("content")
    encoding = data.get("encoding")
    if not isinstance(content, str) or encoding != "base64":
        raise NativeSyncError(
            f"GitHub contents API 返回了未支持的文件编码: {repo}/{source}@{ref}"
        )
    try:
        return base64.b64decode(content)
    except ValueError as exc:
        raise NativeSyncError(
            f"GitHub contents API 返回了无效的 base64 内容: {repo}/{source}@{ref}"
        ) from exc


def _asset_sha256(asset: dict, asset_name: str) -> str:
    digest = asset.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        return digest.removeprefix("sha256:")
    raise NativeSyncError(
        f"GitHub release asset 缺少 sha256 digest: {asset_name}\n"
        "无法校验下载内容，已停止构建。"
    )


def _latest_release_asset(asset_config: dict) -> dict:
    repo = asset_config["repo"]
    release = _read_github_json(f"https://api.github.com/repos/{repo}/releases/latest")
    pattern = re.compile(asset_config["asset_pattern"])
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise NativeSyncError(f"GitHub latest release 缺少 assets: {repo}")

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if not isinstance(name, str):
            continue
        match = pattern.match(name)
        if match is None:
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str):
            raise NativeSyncError(f"GitHub release asset 缺少下载地址: {name}")
        tag_name = release.get("tag_name")
        if not isinstance(tag_name, str) or not tag_name:
            raise NativeSyncError(f"GitHub latest release 缺少 tag_name: {repo}")
        return {
            "version": match.group("version"),
            "archive": name,
            "url": url,
            "sha256": _asset_sha256(asset, name),
            "release": tag_name,
        }

    available = ", ".join(
        asset.get("name", "<unknown>")
        for asset in assets
        if isinstance(asset, dict)
    )
    raise NativeSyncError(
        f"GitHub latest release 未找到匹配资产: {repo}\n"
        f"  pattern: {asset_config['asset_pattern']}\n"
        f"  assets: {available}"
    )


def _download(url: str, dest: Path, expected_sha: str) -> None:
    """下载到 ``*.part``，校验 SHA256 后原子替换到 ``dest``。"""
    print(f"[sync_native_deps] downloading {url}")
    partial = dest.with_name(dest.name + ".part")
    try:
        urllib.request.urlretrieve(url, partial)
        actual_sha = _sha256(partial)
        if actual_sha != expected_sha:
            raise NativeSyncError(
                f"SHA256 mismatch for {dest.name}:\n"
                f"  expected {expected_sha}\n"
                f"  actual   {actual_sha}\n"
                "上游资产可能已更新或下载被篡改/中断，请重新运行 "
                "`uv build --wheel` 或检查网络与上游 release。"
            )
        os.replace(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _ensure_archive(asset: dict) -> Path:
    """缓存命中且 SHA 匹配则复用，否则下载。"""
    archive = _CACHE_DIR / asset["archive"]
    if archive.is_file() and _sha256(archive) == asset["sha256"]:
        return archive
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _download(asset["url"], archive, asset["sha256"])
    except urllib.error.URLError as exc:
        raise NativeSyncError(
            f"下载 {asset['archive']} 失败: {exc}\n"
            "请检查网络后重新运行 `uv build --wheel`。"
        ) from exc
    return archive


def _license_target(asset_config: dict) -> Path:
    return _PACKAGE_DIR / asset_config["license"]["target"]


def _license_valid(asset_config: dict) -> bool:
    target = _license_target(asset_config)
    return target.is_file() and target.stat().st_size > 0


def _sync_license(asset_config: dict, release: str) -> None:
    license_config = asset_config["license"]
    source = license_config["source"]
    target = _license_target(asset_config)
    content = _read_github_file(asset_config["repo"], source, release)
    if not content.strip():
        raise NativeSyncError(
            f"上游 license 文件为空: {asset_config['repo']}/{source}@{release}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _framework_target() -> Path:
    return _PACKAGE_DIR / "Sparkle.framework"


def _framework_valid() -> bool:
    """检查 framework 关键结构：顶层符号链接 + Versions 链接 + 真实二进制。"""
    framework = _framework_target()
    return (
        (framework / "Sparkle").is_symlink()
        and (framework / "Versions" / "Current").is_symlink()
        and (framework / "Versions" / "B" / "Sparkle").is_file()
    )


def _extract_framework_subset(
    tar: tarfile.TarFile, dest: Path, extract_root: str
) -> None:
    """从 tarball 解包 ``Sparkle.framework/`` 子集到 dest，保留符号链接。

    手动遍历 member 而非 ``extractall``：精确只取 framework 子树、还原符号
    链接（``os.symlink``）、保留普通文件可执行位（``os.chmod``），并对未预期
    member 类型显式报错，避免静默丢数据。member 路径（含 ``Sparkle.framework/``
    前缀）原样落到 dest 下。
    """
    prefix = extract_root
    dest.mkdir(parents=True, exist_ok=True)
    extracted_any = False
    for member in tar.getmembers():
        name = member.name[2:] if member.name.startswith("./") else member.name
        if name != prefix and not name.startswith(prefix + "/"):
            continue
        extracted_any = True
        target = dest / name
        if member.issym():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            os.symlink(member.linkname, target)
        elif member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif member.isreg():
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise NativeSyncError(f"无法读取 tar 成员: {member.name}")
            with source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
            os.chmod(target, member.mode)
        else:
            raise NativeSyncError(
                f"tarball 含未支持的成员类型 ({member.type!r}): {member.name}"
            )
    if not extracted_any:
        raise NativeSyncError(
            f"tarball 内未找到 {prefix}/，上游资产结构可能已变化。"
        )


def _extract_tar_files(
    tar: tarfile.TarFile,
    dest: Path,
    paths: dict[str, str],
) -> None:
    """从 tarball 提取指定普通文件，并保留可执行位。"""
    remaining = dict(paths)
    for member in tar.getmembers():
        name = member.name[2:] if member.name.startswith("./") else member.name
        target_name = remaining.get(name)
        if target_name is None:
            continue
        if not member.isreg():
            raise NativeSyncError(f"tarball 成员不是普通文件: {member.name}")
        source = tar.extractfile(member)
        if source is None:
            raise NativeSyncError(f"无法读取 tar 成员: {member.name}")
        target = dest / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source, target.open("wb") as out:
            shutil.copyfileobj(source, out)
        os.chmod(target, member.mode)
        remaining.pop(name)

    if remaining:
        raise NativeSyncError(
            f"tarball 内缺少发布工具，上游资产结构可能已变化: {sorted(remaining)}"
        )


def _sparkle_tool_target_paths() -> list[Path]:
    return [_PACKAGE_DIR / target for target in _SPARKLE["tools"].values()]


def sync_sparkle_framework() -> None:
    """准备 macOS ``Sparkle.framework`` 与发布工具。"""
    target = _framework_target()
    if _skip_sync_enabled():
        tool_targets = _sparkle_tool_target_paths()
        if (
            _framework_valid()
            and all(path.is_file() and path.stat().st_size > 0 for path in tool_targets)
            and _license_valid(_SPARKLE)
        ):
            return
        missing = [str(target)] if not _framework_valid() else []
        missing.extend(str(path) for path in tool_targets if not path.is_file())
        if not _license_valid(_SPARKLE):
            missing.append(str(_license_target(_SPARKLE)))
        raise NativeSyncError(
            f"{SKIP_ENV}=1 但 Sparkle 资源缺失或结构无效: {missing}\n"
            "离线构建需提前保留生成后的 native/license 文件，"
            "或取消该环境变量让构建联网同步。"
        )

    asset = _latest_release_asset(_SPARKLE)
    archive = _ensure_archive(asset)
    extract_root = _CACHE_DIR / f"sparkle-{asset['version']}"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    with tarfile.open(archive, "r:xz") as tar:
        _extract_framework_subset(tar, extract_root, _SPARKLE["extract_root"])
        _extract_tar_files(tar, extract_root, _SPARKLE["tools"])

    source = extract_root / _SPARKLE["extract_root"]
    if not source.is_dir():
        raise NativeSyncError(f"解包后未找到 framework: {source}")
    if target.exists() or target.is_symlink():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)
    for relative_target in _SPARKLE["tools"].values():
        source_tool = extract_root / relative_target
        target_tool = _PACKAGE_DIR / relative_target
        target_tool.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_tool, target_tool)
    _sync_license(_SPARKLE, asset["release"])


def _winsparkle_extract_paths(version: str) -> dict[str, str]:
    return {
        src.format(version=version): dst
        for src, dst in _WINSPARKLE["extract"].items()
    }


def _winsparkle_target_paths() -> list[Path]:
    return [_PACKAGE_DIR / dst for dst in _WINSPARKLE["extract"].values()]


def _winsparkle_tool_paths(version: str) -> tuple[str, Path]:
    tool = _WINSPARKLE["tool"]
    return tool["source"].format(version=version), _PACKAGE_DIR / tool["target"]


def _include_winsparkle_tool() -> bool:
    """x64 与 ARM64 构建携带官方 x64 发布工具；x86 构建不携带。"""
    return struct.calcsize("P") * 8 == 64


def sync_winsparkle() -> None:
    """准备 Windows 三架构 DLL，并按构建架构准备发布工具。"""
    if _skip_sync_enabled():
        targets = _winsparkle_target_paths()
        if _include_winsparkle_tool():
            targets.append(_PACKAGE_DIR / _WINSPARKLE["tool"]["target"])
        if (
            all(path.is_file() and path.stat().st_size > 0 for path in targets)
            and _license_valid(_WINSPARKLE)
        ):
            return
        missing = [str(p) for p in targets if not p.is_file()]
        if not _license_valid(_WINSPARKLE):
            missing.append(str(_license_target(_WINSPARKLE)))
        raise NativeSyncError(
            f"{SKIP_ENV}=1 但 WinSparkle 资源缺失: {missing}\n"
            "离线构建需提前保留 native/license 文件，"
            "或取消该环境变量让构建联网同步。"
        )

    asset = _latest_release_asset(_WINSPARKLE)
    archive = _ensure_archive(asset)
    targets = {
        src: _PACKAGE_DIR / dst
        for src, dst in _winsparkle_extract_paths(asset["version"]).items()
    }
    if _include_winsparkle_tool():
        tool_source, tool_target = _winsparkle_tool_paths(asset["version"])
        targets[tool_source] = tool_target
    with zipfile.ZipFile(archive) as zf:
        available = set(zf.namelist())
        for src, dest in targets.items():
            if src not in available:
                raise NativeSyncError(
                    f"zip 内未找到 {src}，上游资产结构可能已变化。"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(src) as source, dest.open("wb") as out:
                shutil.copyfileobj(source, out)
    _sync_license(_WINSPARKLE, asset["release"])


def sync(platform_name: str | None = None) -> None:
    """按平台准备 native 资源；仅 wheel 构建调用。"""
    current = platform_name or sys.platform
    if current == "win32":
        sync_winsparkle()
    else:
        sync_sparkle_framework()


if __name__ == "__main__":  # pragma: no cover
    sync()
