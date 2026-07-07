"""sparklehelper 自带的 PyInstaller hook 目录。

通过 ``pyinstaller40`` entry point（``hook-dirs = sparklehelper._pyinstaller:get_hook_dirs``）
注册到 PyInstaller，下游 ``pip install sparklehelper`` 后无需 ``--additional-hooks-dir``
即可自动加载 ``hook-sparklehelper.py``。

hook 负责：
1. 把 ``sparklehelper`` 加入 hiddenimports；
2. 定位 ``Sparkle.framework``（环境变量 → wheel 内置副本）；
3. 遍历 framework 目录，保留符号链接语义，产出 datas/binaries/SYMLINK 条目，
   让 PyInstaller onedir ``.app`` 把整个 framework 原样收集进
   ``Contents/Frameworks/``。

onefile ``.app`` 可通过 ``sparklehelper pyinstaller app.spec`` 临时修补 spec，
把 framework 直接交给 ``BUNDLE``。
"""

from __future__ import annotations

import ast
import os
from pathlib import Path


PyInstallerTocEntry = tuple[str, str, str]
PYINSTALLER_WRAPPER_ENV = "SPARKLEHELPER_PYINSTALLER_WRAPPER"

_MACHO_MAGICS = frozenset({
    b'\xfe\xed\xfa\xce',  # 32-bit 大端
    b'\xfe\xed\xfa\xcf',  # 64-bit 大端
    b'\xcf\xfa\xed\xfe',  # 64-bit 小端
    b'\xce\xfa\xed\xfe',  # 32-bit 小端
    b'\xca\xfe\xba\xbe',  # FAT_MAGIC
    b'\xca\xfe\xba\xbf',  # FAT_MAGIC_64
    b'\xbe\xba\xfe\xca',  # 反序 FAT_MAGIC
    b'\xbf\xba\xfe\xca',  # 反序 FAT_MAGIC_64
})

_FILTER_NAMES = frozenset({'.DS_Store', '__pycache__', '_CodeSignature'})
_FRAMEWORK_NAME = "Sparkle.framework"


def get_hook_dirs() -> list[str]:
    """PyInstaller 调用此函数获取 hook 目录列表。"""
    return [os.path.dirname(__file__)]


def is_onefile_exe(exe: object) -> bool:
    """判断 PyInstaller ``EXE`` 目标是否为 onefile 模式。"""
    return not bool(getattr(exe, "exclude_binaries", True))


def _is_name_call(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def _assigned_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AnnAssign):
        targets = [statement.target]
    else:
        return None

    for target in targets:
        if isinstance(target, ast.Name):
            return target.id
    return None


def _constant_bool(node: ast.AST) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _exe_call_is_onefile(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "exclude_binaries":
            continue
        value = _constant_bool(keyword.value)
        if value is not None:
            return not value
        return False
    return True


def spec_uses_onefile_bundle(source: str) -> bool:
    """判断 PyInstaller spec 是否包含 onefile macOS ``BUNDLE(exe, ...)``。"""
    module = ast.parse(source)
    exe_targets: dict[str, bool] = {}

    for statement in module.body:
        value = getattr(statement, "value", None)
        if _is_name_call(value, "EXE"):
            target = _assigned_name(statement)
            if target is not None:
                exe_targets[target] = _exe_call_is_onefile(value)

    for node in ast.walk(module):
        if not _is_name_call(node, "BUNDLE") or not node.args:
            continue

        first_argument = node.args[0]
        if _is_name_call(first_argument, "EXE"):
            if _exe_call_is_onefile(first_argument):
                return True
            continue
        if isinstance(first_argument, ast.Name):
            if exe_targets.get(first_argument.id, False):
                return True

    return False


def _resolve_framework_path() -> Path:
    env = os.environ.get("SPARKLEHELPER_FRAMEWORK_PATH")
    if env:
        path = Path(os.path.expanduser(env))
        if path.is_dir():
            return path.resolve()
        raise SystemExit(
            "SPARKLEHELPER_FRAMEWORK_PATH points to a non-existent directory: "
            f"{path}"
        )

    from sparklehelper._framework import bundled_framework_path

    bundled = bundled_framework_path()
    if bundled.is_dir():
        return bundled
    raise SystemExit(f"Bundled Sparkle.framework is missing: {bundled}")


def _is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) in _MACHO_MAGICS
    except OSError:
        return False


def _framework_symlinks(fw_root: Path):
    from sparklehelper._framework import (
        capture_framework_symlinks,
        framework_symlink_manifest_path,
        load_framework_symlink_manifest,
    )

    if os.environ.get("SPARKLEHELPER_FRAMEWORK_PATH"):
        captured = capture_framework_symlinks(fw_root)
        if captured:
            return captured

    manifest = framework_symlink_manifest_path()
    if manifest.is_file():
        return load_framework_symlink_manifest(manifest)
    return capture_framework_symlinks(fw_root)


def _relative_posix(root: Path, path: Path) -> str:
    return os.path.relpath(path, root).replace(os.path.sep, "/")


def collect_sparkle_framework_toc(
    *, include_versions_current: bool = True
) -> list[PyInstallerTocEntry]:
    """生成 Sparkle.framework 的 PyInstaller TOC 条目。

    返回值可直接传给 ``BUNDLE``，让 onefile macOS ``.app`` 也把
    ``Sparkle.framework`` 放进 ``Contents/Frameworks``。
    """
    fw_root = _resolve_framework_path()
    symlinks = _framework_symlinks(fw_root)
    symlink_paths = {item["path"] for item in symlinks}
    toc: list[PyInstallerTocEntry] = []

    for dirpath, dirnames, filenames in os.walk(fw_root, followlinks=False):
        dir_path = Path(dirpath)
        rel_dir = os.path.relpath(dir_path, fw_root)
        dest_dir = (
            _FRAMEWORK_NAME
            if rel_dir == "."
            else os.path.join(_FRAMEWORK_NAME, rel_dir)
        )

        dirnames[:] = [
            dirname for dirname in dirnames
            if dirname not in _FILTER_NAMES
            and not (dir_path / dirname).is_symlink()
            and _relative_posix(fw_root, dir_path / dirname) not in symlink_paths
        ]

        for filename in filenames:
            if filename in _FILTER_NAMES:
                continue
            full = dir_path / filename
            if full.is_symlink():
                continue
            if _relative_posix(fw_root, full) in symlink_paths:
                continue
            dest = os.path.normpath(os.path.join(dest_dir, filename))
            typecode = "BINARY" if _is_macho(full) else "DATA"
            toc.append((dest, str(full), typecode))

    for item in symlinks:
        if not include_versions_current and item["path"] == "Versions/Current":
            continue
        dest = os.path.normpath(os.path.join(_FRAMEWORK_NAME, item["path"]))
        toc.append((dest, item["target"], "SYMLINK"))

    return toc


def collect_sparkle_framework_for_bundle(
    exe: object | None = None,
) -> list[PyInstallerTocEntry]:
    """为 macOS onefile ``BUNDLE`` 生成额外的 Sparkle.framework TOC。

    传入 ``EXE`` 对象时，只有 onefile 模式才返回条目；onedir 模式返回空列表。
    """
    if exe is not None and not is_onefile_exe(exe):
        return []
    return collect_sparkle_framework_toc(include_versions_current=True)


def prepare_sparkle_framework_for_onefile_bundle(
    analysis: object,
) -> list[PyInstallerTocEntry]:
    """从 ``Analysis`` 中取出 Sparkle.framework，返回可传给 ``BUNDLE`` 的 TOC。"""
    framework_toc = collect_sparkle_framework_for_bundle()
    analysis.binaries = exclude_sparkle_framework_toc(list(analysis.binaries))
    analysis.datas = exclude_sparkle_framework_toc(list(analysis.datas))
    return framework_toc


def exclude_sparkle_framework_toc(
    toc: list[PyInstallerTocEntry],
) -> list[PyInstallerTocEntry]:
    """从 Analysis TOC 中移除 hook 自动收集的 Sparkle.framework 条目。"""
    prefix = _FRAMEWORK_NAME + os.sep
    posix_prefix = _FRAMEWORK_NAME + "/"
    return [
        entry for entry in toc
        if entry[0] != _FRAMEWORK_NAME
        and not entry[0].startswith(prefix)
        and not entry[0].startswith(posix_prefix)
    ]


__all__ = [
    "PyInstallerTocEntry",
    "collect_sparkle_framework_for_bundle",
    "collect_sparkle_framework_toc",
    "exclude_sparkle_framework_toc",
    "get_hook_dirs",
    "is_onefile_exe",
    "PYINSTALLER_WRAPPER_ENV",
    "prepare_sparkle_framework_for_onefile_bundle",
    "spec_uses_onefile_bundle",
]
