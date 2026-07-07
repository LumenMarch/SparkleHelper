"""定位 sparklehelper 随包分发的构建资源。"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import TypedDict


_PACKAGE_DIR = Path(__file__).resolve().parent
_FRAMEWORK_SYMLINK_MANIFEST = _PACKAGE_DIR / "Sparkle.framework.symlinks.json"
_DEFAULT_NUITKA_APP_VERSION = "0.1.0"
NUITKA_CF_BUNDLE_VERSION_ENV = "SPARKLEHELPER_NUITKA_CF_BUNDLE_VERSION"
NUITKA_CF_BUNDLE_SHORT_VERSION_ENV = (
    "SPARKLEHELPER_NUITKA_CF_BUNDLE_SHORT_VERSION"
)
NUITKA_SPARKLE_PLIST_OVERRIDES_ENV = "SPARKLEHELPER_NUITKA_SPARKLE_PLIST"
_PYINSTALLER_FRAMEWORK_VARIABLE = "sparklehelper_sparkle_framework"


class FrameworkSymlink(TypedDict):
    """framework 内的单个符号链接条目。"""

    path: str
    target: str


class NuitkaBundleVersions(TypedDict, total=False):
    """Nuitka macOS bundle 版本字段。"""

    build: str
    display: str


class NuitkaSparkleOptions(TypedDict):
    """Nuitka wrapper 提供给 plugin 的 Sparkle plist 配置。"""

    versions: NuitkaBundleVersions | None
    plist: dict[str, object]


_MANIFEST_VERSION = 1
_SPARKLE_PLIST_KEY_TYPES = {
    "SUFeedURL": "str",
    "SUHasLaunchedBefore": "bool",
    "SURelaunchHostBundle": "str",
    "SUShowReleaseNotes": "bool",
    "SUSkippedVersion": "str",
    "SUSkippedMajorVersion": "str",
    "SUSkippedMajorSubreleaseVersion": "str",
    "SUScheduledCheckInterval": "number",
    "SUScheduledImpatientCheckInterval": "number",
    "SULastCheckTime": "str",
    "SUSignedFeedFailureExpirationInterval": "number",
    "SUPublicDSAKey": "str",
    "SUPublicDSAKeyFile": "str",
    "SUPublicEDKey": "str",
    "SURequireSignedFeed": "bool",
    "SUVerifyUpdateBeforeExtraction": "bool",
    "SUAutomaticallyUpdate": "bool",
    "SUAllowsAutomaticUpdates": "bool",
    "SUEnableSystemProfiling": "bool",
    "SUEnableAutomaticChecks": "bool",
    "SUEnableInstallerLauncherService": "bool",
    "SUEnableDownloaderService": "bool",
    "SUEnableInstallerConnectionService": "bool",
    "SUEnableInstallerStatusService": "bool",
    "SUSendProfileInfo": "bool",
    "SUUpdateGroupIdentifier": "str",
    "SULastProfileSubmissionDate": "str",
    "SUPromptUserOnFirstLaunch": "bool",
    "SUEnableJavaScript": "bool",
    "SUAllowedURLSchemes": "array",
    "SUDefaultsDomain": "str",
    "NSUpdateSecurityPolicy": "json",
}
_SPARKLE_BOOLEAN_LITERALS = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}


def bundled_framework_path() -> Path:
    """返回随 wheel 分发的 ``Sparkle.framework`` 路径。"""
    return _PACKAGE_DIR / "Sparkle.framework"


def framework_symlink_manifest_path() -> Path:
    """返回随 wheel 分发的 ``Sparkle.framework`` 符号链接 manifest 路径。"""
    return _FRAMEWORK_SYMLINK_MANIFEST


def _relative_framework_path(framework_path: Path, path: Path) -> str:
    return path.relative_to(framework_path).as_posix()


def capture_framework_symlinks(framework_path: str | Path) -> list[FrameworkSymlink]:
    """扫描 framework，返回其中完整的符号链接布局。"""
    framework = Path(framework_path)
    links: list[FrameworkSymlink] = []

    for root, dirnames, filenames in os.walk(framework, followlinks=False):
        root_path = Path(root)
        for dirname in list(dirnames):
            path = root_path / dirname
            if path.is_symlink():
                links.append(
                    {
                        "path": _relative_framework_path(framework, path),
                        "target": os.readlink(path),
                    }
                )
        dirnames[:] = [
            dirname for dirname in dirnames if not (root_path / dirname).is_symlink()
        ]

        for filename in filenames:
            path = root_path / filename
            if path.is_symlink():
                links.append(
                    {
                        "path": _relative_framework_path(framework, path),
                        "target": os.readlink(path),
                    }
                )

    return sorted(links, key=lambda item: item["path"])


def write_framework_symlink_manifest(
    framework_path: str | Path, manifest_path: str | Path
) -> None:
    """把 framework 当前符号链接布局写入 manifest。"""
    framework = Path(framework_path)
    if not framework.is_dir():
        raise FileNotFoundError(f"Sparkle.framework 不存在: {framework}")

    data = {
        "version": _MANIFEST_VERSION,
        "framework": framework.name,
        "links": capture_framework_symlinks(framework),
    }
    Path(manifest_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_framework_symlink_manifest(
    manifest_path: str | Path,
) -> list[FrameworkSymlink]:
    """从 manifest 读取 framework 符号链接布局。"""
    manifest = Path(manifest_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != _MANIFEST_VERSION:
        raise ValueError(f"不支持的 framework symlink manifest 版本: {manifest}")

    links = data.get("links")
    if not isinstance(links, list):
        raise ValueError(f"framework symlink manifest 缺少 links: {manifest}")

    result: list[FrameworkSymlink] = []
    for item in links:
        if not isinstance(item, dict):
            raise ValueError(f"framework symlink manifest 条目无效: {manifest}")
        path = item.get("path")
        target = item.get("target")
        if not isinstance(path, str) or not isinstance(target, str):
            raise ValueError(f"framework symlink manifest 条目无效: {manifest}")
        result.append({"path": path, "target": target})
    return result


def _manifest_path(framework_path: Path, manifest_path: str | Path | None) -> Path:
    if manifest_path is not None:
        return Path(manifest_path)
    return framework_path.parent / f"{framework_path.name}.symlinks.json"


def _target_path(framework_path: Path, link_path: str) -> Path:
    path = Path(link_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"framework symlink path 必须位于 framework 内: {link_path}")
    return framework_path / path


def restore_framework_symlinks(
    framework_path: str | Path,
    manifest_path: str | Path | None = None,
    *,
    links: list[FrameworkSymlink] | None = None,
) -> None:
    """按 manifest 在目标 framework 中重建符号链接。"""
    framework = Path(framework_path)
    manifest_links = (
        links
        if links is not None
        else load_framework_symlink_manifest(_manifest_path(framework, manifest_path))
    )

    for item in sorted(manifest_links, key=lambda link: link["path"].count("/")):
        link_path = _target_path(framework, item["path"])
        target = item["target"]

        if link_path.is_symlink() and os.readlink(link_path) == target:
            continue

        if link_path.exists() or link_path.is_symlink():
            if link_path.is_dir() and not link_path.is_symlink():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()

        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link_path)


def bundled_winsparkle_path(arch: str) -> Path:
    """返回随 wheel 分发的 ``WinSparkle.dll`` 路径（按架构选子目录）。

    ``arch`` 为 ``"x64"`` / ``"x86"`` / ``"arm64"``。
    """
    return _PACKAGE_DIR / "winsparkle" / arch / "WinSparkle.dll"


def nuitka_config_path() -> Path:
    """返回随包分发的 Nuitka YAML 配置文件路径。"""
    return _PACKAGE_DIR / "sparklehelper.nuitka-package.config.yml"


def nuitka_plugin_path() -> Path:
    """返回随包分发的 Nuitka user plugin 路径。"""
    return _PACKAGE_DIR / "_nuitka_plugin.py"


def _trim_build_parts(parts: list[int]) -> list[int]:
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return parts


def _validate_build_parts(parts: list[int], key: str) -> None:
    if not parts or parts[0] <= 0:
        raise ValueError(f"{key} 的第一个数字必须大于 0")
    limits = (4, 2, 2)
    for index, part in enumerate(parts):
        if len(str(part)) > limits[index]:
            raise ValueError(f"{key} 的第 {index + 1} 个数字过长")


def _build_version_from_display_version(display: str) -> str:
    release_part = re.split(r"[-+]", display, maxsplit=1)[0]
    parts = [int(part) for part in re.findall(r"\d+", release_part)[:3]]
    while parts and parts[0] == 0:
        parts.pop(0)
    if not parts:
        parts = [1]
    parts = _trim_build_parts(parts)
    _validate_build_parts(parts, "CFBundleVersion")
    return ".".join(str(part) for part in parts)


def _normalize_build_version(build_version: str) -> str:
    value = build_version.strip()
    if not re.fullmatch(r"\d+(?:\.\d+){0,2}", value):
        raise ValueError("--build-version 必须是 1 到 3 段数字")

    parts = [int(part) for part in value.split(".")]
    _validate_build_parts(parts, "--build-version")
    return ".".join(str(part) for part in parts)


def _nuitka_bundle_versions(
    version: str | None = None,
    build_version: str | None = None,
) -> NuitkaBundleVersions:
    """把 app 版本参数转换为 Sparkle 需要的 bundle 版本字段。"""
    result: NuitkaBundleVersions = {}
    if build_version is not None:
        result["build"] = _normalize_build_version(build_version)
    if version is None:
        return result

    display = version.strip()
    if display.startswith(("v", "V")) and len(display) > 1 and display[1].isdigit():
        display = display[1:]
    if not display:
        raise ValueError("--version 不能为空")

    if not re.search(r"\d", display):
        raise ValueError("--version 必须包含至少一个数字")

    result["display"] = display
    if build_version is None:
        result["build"] = _build_version_from_display_version(display)
    return result


def _sparkle_cli_name(key: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", key)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    return name.lower()


def _sparkle_cli_options() -> dict[str, str]:
    options = {
        f"--{_sparkle_cli_name(key)}": key
        for key in _SPARKLE_PLIST_KEY_TYPES
    }
    options.update(
        {
            "--feed-url": "SUFeedURL",
            "--public-ed-key": "SUPublicEDKey",
            "--public-dsa-key": "SUPublicDSAKey",
            "--public-dsa-key-file": "SUPublicDSAKeyFile",
            "--automatic-checks": "SUEnableAutomaticChecks",
            "--scheduled-check-interval": "SUScheduledCheckInterval",
            "--scheduled-impatient-check-interval": (
                "SUScheduledImpatientCheckInterval"
            ),
            "--update-group-identifier": "SUUpdateGroupIdentifier",
            "--defaults-domain": "SUDefaultsDomain",
        }
    )
    return options


def _parse_sparkle_bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in _SPARKLE_BOOLEAN_LITERALS:
        raise ValueError(f"{key} 必须是 true/false、yes/no、on/off 或 1/0")
    return _SPARKLE_BOOLEAN_LITERALS[normalized]


def _parse_sparkle_number(value: str, key: str) -> int | float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{key} 必须是数字") from exc
    return int(number) if number.is_integer() else number


def _parse_sparkle_array(value: str, key: str) -> list[object]:
    stripped = value.strip()
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        if not isinstance(parsed, list):
            raise ValueError(f"{key} 必须是数组")
        return parsed
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_sparkle_value(key: str, value: str) -> object:
    if key not in _SPARKLE_PLIST_KEY_TYPES:
        supported = ", ".join(sorted(_SPARKLE_PLIST_KEY_TYPES))
        raise ValueError(
            f"不支持的 Sparkle Info.plist key: {key}；支持: {supported}"
        )

    value_type = _SPARKLE_PLIST_KEY_TYPES[key]
    if value_type == "bool":
        return _parse_sparkle_bool(value, key)
    if value_type == "number":
        return _parse_sparkle_number(value, key)
    if value_type == "array":
        return _parse_sparkle_array(value, key)
    if value_type == "json":
        parsed = json.loads(value)
        if parsed is None:
            raise ValueError(f"{key} 不能是 null")
        return parsed
    return value.strip()


def _parse_sparkle_key_assignment(assignment: str) -> tuple[str, object]:
    if "=" not in assignment:
        raise ValueError("--sparkle-key 必须使用 KEY=VALUE 格式")
    key, value = assignment.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError("--sparkle-key 缺少 key")
    return key, _parse_sparkle_value(key, value)


def _strip_macos_app_version(arguments: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--macos-app-version":
            index += 2
            continue
        if argument.startswith("--macos-app-version="):
            index += 1
            continue
        result.append(argument)
        index += 1
    return result


def _has_macos_app_version(arguments: list[str]) -> bool:
    return any(
        argument == "--macos-app-version"
        or argument.startswith("--macos-app-version=")
        for argument in arguments
    )


def _has_forwarded_version_query(arguments: list[str]) -> bool:
    return any(argument == "--version" for argument in arguments)


def _prepare_nuitka_arguments(
    arguments: list[str],
) -> tuple[list[str], NuitkaSparkleOptions]:
    forwarded: list[str] = []
    plist_overrides: dict[str, object] = {}
    sparkle_options = _sparkle_cli_options()
    wrapper_version: str | None = None
    wrapper_build_version: str | None = None
    index = 0

    while index < len(arguments):
        argument = arguments[index]

        if argument.startswith("--version="):
            wrapper_version = argument.split("=", 1)[1]
            index += 1
            continue
        if (
            argument == "--version"
            and index + 1 < len(arguments)
            and not arguments[index + 1].startswith("-")
        ):
            wrapper_version = arguments[index + 1]
            index += 2
            continue

        if argument.startswith("--build-version="):
            wrapper_build_version = argument.split("=", 1)[1]
            index += 1
            continue
        if argument == "--build-version":
            if index + 1 >= len(arguments) or arguments[index + 1].startswith("-"):
                raise ValueError("--build-version 缺少值")
            wrapper_build_version = arguments[index + 1]
            index += 2
            continue

        if argument.startswith("--sparkle-key="):
            key, value = _parse_sparkle_key_assignment(argument.split("=", 1)[1])
            plist_overrides[key] = value
            index += 1
            continue
        if argument == "--sparkle-key":
            if index + 1 >= len(arguments):
                raise ValueError("--sparkle-key 缺少 KEY=VALUE")
            key, value = _parse_sparkle_key_assignment(arguments[index + 1])
            plist_overrides[key] = value
            index += 2
            continue

        no_argument = None
        if argument.startswith("--no-"):
            no_argument = "--" + argument[len("--no-") :]
        if no_argument in sparkle_options:
            key = sparkle_options[no_argument]
            if _SPARKLE_PLIST_KEY_TYPES[key] != "bool":
                raise ValueError(f"{argument} 只能用于布尔 Sparkle key")
            plist_overrides[key] = False
            index += 1
            continue

        option_name, inline_value = (
            argument.split("=", 1) if "=" in argument else (argument, None)
        )
        if option_name in sparkle_options:
            key = sparkle_options[option_name]
            value_type = _SPARKLE_PLIST_KEY_TYPES[key]
            if inline_value is None:
                if value_type == "bool":
                    next_value = (
                        arguments[index + 1] if index + 1 < len(arguments) else ""
                    )
                    if next_value.lower() in _SPARKLE_BOOLEAN_LITERALS:
                        inline_value = next_value
                        index += 1
                    else:
                        inline_value = "true"
                else:
                    if (
                        index + 1 >= len(arguments)
                        or arguments[index + 1].startswith("-")
                    ):
                        raise ValueError(f"{argument} 缺少值")
                    inline_value = arguments[index + 1]
                    index += 1
            plist_overrides[key] = _parse_sparkle_value(key, inline_value)
            index += 1
            continue

        forwarded.append(argument)
        index += 1

    if (
        wrapper_version is None
        and not _has_macos_app_version(forwarded)
        and not _has_forwarded_version_query(forwarded)
    ):
        wrapper_version = _DEFAULT_NUITKA_APP_VERSION

    if wrapper_version is None and wrapper_build_version is None:
        return forwarded, {"versions": None, "plist": plist_overrides}

    versions = _nuitka_bundle_versions(wrapper_version, wrapper_build_version)
    if wrapper_version is not None:
        forwarded = _strip_macos_app_version(forwarded)
        forwarded.insert(0, f"--macos-app-version={versions['display']}")

    return forwarded, {"versions": versions, "plist": plist_overrides}


def _nuitka_command(arguments: list[str]) -> list[str]:
    """构造自动注入 sparklehelper 构建资源的 Nuitka 命令。"""
    return [
        sys.executable,
        "-m",
        "nuitka",
        f"--user-plugin={nuitka_plugin_path()}",
        f"--user-package-configuration-file={nuitka_config_path()}",
        *arguments,
    ]


def _nuitka_help_text() -> str:
    sparkle_keys = ", ".join(sorted(_SPARKLE_PLIST_KEY_TYPES))
    return f"""usage: sparklehelper nuitka [sparklehelper options] [nuitka options] script.py

Run Nuitka with SparkleHelper's bundled package configuration and user plugin.
Unknown options are forwarded to Nuitka.

SparkleHelper options:
  -h, --help
      Show this help message and exit.
  --version VERSION
      Set CFBundleShortVersionString. Defaults to {_DEFAULT_NUITKA_APP_VERSION}
      unless --macos-app-version is already passed through to Nuitka.
  --build-version BUILD_VERSION
      Set CFBundleVersion. If omitted, it is derived from --version.
  --feed-url URL
      Set SUFeedURL.
  --public-ed-key KEY
      Set SUPublicEDKey.
  --automatic-checks [true|false]
      Set SUEnableAutomaticChecks.
  --scheduled-check-interval SECONDS
      Set SUScheduledCheckInterval.
  --sparkle-key KEY=VALUE
      Set any supported Sparkle Info.plist key. Repeat as needed.

Supported Sparkle keys:
  {sparkle_keys}
"""


def _run_nuitka(arguments: list[str]) -> int:
    """在当前 Python 环境中运行 Nuitka。"""
    if any(argument in {"-h", "--help"} for argument in arguments):
        print(_nuitka_help_text(), end="")
        return 0

    if importlib.util.find_spec("nuitka") is None:
        print(
            "Nuitka is not installed. Install sparklehelper with the demo extra.",
            file=sys.stderr,
        )
        return 1

    try:
        forwarded_arguments, sparkle_options = _prepare_nuitka_arguments(arguments)
    except ValueError as exc:
        print(f"sparklehelper nuitka: {exc}", file=sys.stderr)
        return 2

    env = None
    versions = sparkle_options["versions"]
    plist_overrides = sparkle_options["plist"]
    if versions is not None or plist_overrides:
        env = os.environ.copy()
        if versions is not None:
            if "build" in versions:
                env[NUITKA_CF_BUNDLE_VERSION_ENV] = versions["build"]
            if "display" in versions:
                env[NUITKA_CF_BUNDLE_SHORT_VERSION_ENV] = versions["display"]
        if plist_overrides:
            env[NUITKA_SPARKLE_PLIST_OVERRIDES_ENV] = json.dumps(
                plist_overrides,
                ensure_ascii=False,
                sort_keys=True,
            )

    try:
        return subprocess.run(
            _nuitka_command(forwarded_arguments),
            check=False,
            env=env,
        ).returncode
    except OSError as exc:
        print(f"Failed to start Nuitka: {exc}", file=sys.stderr)
        return 1


def _pyinstaller_command(arguments: list[str]) -> list[str]:
    """构造 PyInstaller 命令。"""
    return [sys.executable, "-m", "PyInstaller", *arguments]


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


def _analysis_target_name(statement: ast.stmt) -> str | None:
    value = getattr(statement, "value", None)
    if _is_name_call(value, "Analysis"):
        return _assigned_name(statement)
    return None


def _has_prepare_import(module: ast.Module) -> bool:
    for statement in module.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        if statement.module != "sparklehelper._pyinstaller":
            continue
        if any(
            alias.name == "prepare_sparkle_framework_for_onefile_bundle"
            for alias in statement.names
        ):
            return True
    return False


def _is_framework_bundle_argument(argument: ast.AST) -> bool:
    if isinstance(argument, ast.Name):
        return argument.id in {
            _PYINSTALLER_FRAMEWORK_VARIABLE,
            "sparkle_framework",
        }
    return _is_name_call(argument, "prepare_sparkle_framework_for_onefile_bundle")


def _framework_variable_used(call: ast.Call) -> bool:
    return any(_is_framework_bundle_argument(argument) for argument in call.args)


def _is_onefile_bundle_call(call: ast.Call) -> bool:
    if not isinstance(call.func, ast.Name) or call.func.id != "BUNDLE":
        return False
    if not call.args:
        return False
    first = call.args[0]
    return isinstance(first, ast.Name) and first.id == "exe"


class _BundleFrameworkInserter(ast.NodeTransformer):
    """把 onefile BUNDLE 调用改为显式接收 Sparkle.framework TOC。"""

    def __init__(self) -> None:
        self.changed = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if _is_onefile_bundle_call(node) and not _framework_variable_used(node):
            node.args.insert(
                1,
                ast.Name(id=_PYINSTALLER_FRAMEWORK_VARIABLE, ctx=ast.Load()),
            )
            self.changed = True
        return node


def _insert_after_docstring_and_futures(
    body: list[ast.stmt],
    statement: ast.stmt,
) -> None:
    index = 0
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        index = 1

    while (
        index < len(body)
        and isinstance(body[index], ast.ImportFrom)
        and body[index].module == "__future__"
    ):
        index += 1

    body.insert(index, statement)


def _patch_pyinstaller_onefile_spec(source: str) -> tuple[str, bool]:
    """为 PyInstaller onefile .app spec 注入 Sparkle.framework 的 BUNDLE TOC。"""
    module = ast.parse(source)

    inserter = _BundleFrameworkInserter()
    patched = inserter.visit(module)
    if not isinstance(patched, ast.Module):
        raise ValueError("PyInstaller spec AST 无效")
    module = patched
    if not inserter.changed:
        return source, False

    analysis_name = None
    analysis_index = None
    for index, statement in enumerate(module.body):
        analysis_name = _analysis_target_name(statement)
        if analysis_name is not None:
            analysis_index = index
            break

    if analysis_name is None or analysis_index is None:
        raise ValueError(
            "未找到 Analysis(...) 赋值，无法自动修补 PyInstaller onefile spec"
        )

    prepare_call = ast.Assign(
        targets=[
            ast.Name(id=_PYINSTALLER_FRAMEWORK_VARIABLE, ctx=ast.Store()),
        ],
        value=ast.Call(
            func=ast.Name(
                id="prepare_sparkle_framework_for_onefile_bundle",
                ctx=ast.Load(),
            ),
            args=[ast.Name(id=analysis_name, ctx=ast.Load())],
            keywords=[],
        ),
    )
    module.body.insert(analysis_index + 1, prepare_call)

    if not _has_prepare_import(module):
        import_statement = ast.ImportFrom(
            module="sparklehelper._pyinstaller",
            names=[
                ast.alias(
                    name="prepare_sparkle_framework_for_onefile_bundle",
                )
            ],
            level=0,
        )
        _insert_after_docstring_and_futures(module.body, import_statement)

    ast.fix_missing_locations(module)
    return ast.unparse(module) + "\n", True


def _spec_argument_indexes(arguments: list[str]) -> list[int]:
    return [
        index for index, argument in enumerate(arguments)
        if not argument.startswith("-") and Path(argument).suffix == ".spec"
    ]


def _patched_pyinstaller_arguments(
    arguments: list[str],
) -> tuple[list[str], Path | None]:
    spec_indexes = _spec_argument_indexes(arguments)
    if not spec_indexes:
        return arguments, None
    if len(spec_indexes) > 1:
        raise ValueError("sparklehelper pyinstaller 只支持一次构建一个 .spec")

    spec_index = spec_indexes[0]
    spec_path = Path(arguments[spec_index]).expanduser()
    if not spec_path.is_file():
        raise ValueError(f"PyInstaller spec 不存在: {spec_path}")

    patched_source, changed = _patch_pyinstaller_onefile_spec(
        spec_path.read_text(encoding="utf-8")
    )
    if not changed:
        return arguments, None

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=spec_path.parent,
        prefix=f".{spec_path.stem}.sparklehelper.",
        suffix=".spec",
        delete=False,
    ) as fh:
        fh.write(patched_source)
        patched_path = Path(fh.name)

    patched_arguments = list(arguments)
    patched_arguments[spec_index] = str(patched_path)
    return patched_arguments, patched_path


def _pyinstaller_help_text() -> str:
    return """usage: sparklehelper pyinstaller [pyinstaller options] app.spec

Run PyInstaller, patching onefile macOS .app specs so Sparkle.framework is
placed in Contents/Frameworks instead of the onefile _MEI extraction directory.

Use this wrapper only for onefile macOS .app specs shaped like BUNDLE(exe, ...).
Onedir specs shaped like BUNDLE(coll, ...) should keep using plain pyinstaller;
the built-in PyInstaller hook already handles those.

Options:
  -h, --help
      Show this help message and exit.
  All other options are forwarded to PyInstaller.
"""


def _run_pyinstaller(arguments: list[str]) -> int:
    """运行 PyInstaller，并在 onefile .app spec 上自动注入 Sparkle.framework。"""
    if any(argument in {"-h", "--help"} for argument in arguments):
        print(_pyinstaller_help_text(), end="")
        return 0

    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "PyInstaller is not installed. Install sparklehelper with the demo extra.",
            file=sys.stderr,
        )
        return 1

    patched_spec = None
    try:
        forwarded_arguments, patched_spec = _patched_pyinstaller_arguments(arguments)
    except ValueError as exc:
        print(f"sparklehelper pyinstaller: {exc}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    from sparklehelper._pyinstaller import PYINSTALLER_WRAPPER_ENV

    env[PYINSTALLER_WRAPPER_ENV] = "1"

    try:
        return subprocess.run(
            _pyinstaller_command(forwarded_arguments),
            check=False,
            env=env,
        ).returncode
    except OSError as exc:
        print(f"Failed to start PyInstaller: {exc}", file=sys.stderr)
        return 1
    finally:
        if patched_spec is not None:
            try:
                patched_spec.unlink()
            except OSError:
                pass


def _build_parser() -> argparse.ArgumentParser:
    """构造构建资源查询与 Nuitka 包装命令的 CLI parser。"""
    parser = argparse.ArgumentParser(
        prog="sparklehelper",
        description="SparkleHelper build resource utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "nuitka-config",
        help="Print the path to the bundled Nuitka package configuration.",
    )
    subparsers.add_parser(
        "nuitka",
        add_help=False,
        help="Run Nuitka with the bundled configuration and plugin.",
    )
    subparsers.add_parser(
        "pyinstaller",
        add_help=False,
        help="Run PyInstaller with onefile macOS .app spec patching.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行 ``sparklehelper`` 命令行入口。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "nuitka":
        return _run_nuitka(arguments[1:])
    if arguments and arguments[0] == "pyinstaller":
        return _run_pyinstaller(arguments[1:])

    args = _build_parser().parse_args(arguments)
    if args.command == "nuitka-config":
        print(nuitka_config_path())
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "FrameworkSymlink",
    "NuitkaBundleVersions",
    "NuitkaSparkleOptions",
    "NUITKA_CF_BUNDLE_SHORT_VERSION_ENV",
    "NUITKA_CF_BUNDLE_VERSION_ENV",
    "NUITKA_SPARKLE_PLIST_OVERRIDES_ENV",
    "bundled_framework_path",
    "capture_framework_symlinks",
    "framework_symlink_manifest_path",
    "load_framework_symlink_manifest",
    "restore_framework_symlinks",
    "write_framework_symlink_manifest",
    "bundled_winsparkle_path",
    "nuitka_config_path",
    "nuitka_plugin_path",
    "main",
]
