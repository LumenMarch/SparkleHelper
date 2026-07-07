"""PyInstaller hook for sparklehelper: 跨平台收集二进制资源。

macOS: 收集 ``Sparkle.framework``（Mach-O 检测 + 符号链接重建）。
Windows: 收集 ``WinSparkle.dll``（按进程架构选 x64/x86/arm64）。

框架/DLL 定位优先级（两端各自）:
    macOS:
        1. 环境变量 ``SPARKLEHELPER_FRAMEWORK_PATH``
        2. wheel 内置的 ``Sparkle.framework``
    Windows:
        1. 环境变量 ``SPARKLEHELPER_WINSPARKLE_PATH``
        2. 主可执行文件同目录
        3. PyInstaller 内部目录（onedir 下通常是 ``_internal/WinSparkle.dll``）
        4. wheel 内置的 ``winsparkle/<arch>/WinSparkle.dll``

macOS 收集策略:
    - 读取 wheel 构建时保存的符号链接 manifest，作为 framework 标准布局；
    - 用 ``os.walk`` 遍历 framework 目录（不跟随符号链接），所有符号链接
      和 manifest 中的链接路径都跳过，实体文件按 Mach-O 检测分入
      binaries/datas；
    - 最后按 manifest 追加 SYMLINK 条目，避免 Sparkle 更新后手写清单漂移；
      ``Versions/Current`` 由 PyInstaller 自己从 framework binary 重建；
    - PyInstaller 的 ``collect_files_from_framework_bundles`` 在 Analysis 阶段
      从 BINARY 条目自动重建 ``Versions/Current`` 等关键符号链接；
      本 hook 追加的顶层符号链接与 PyInstaller 自动产生的不冲突
      （normalize_toc 按 dest_name 去重）
    - macOS onefile ``.app`` 需要在 spec 中调用
      ``prepare_sparkle_framework_for_onefile_bundle(a)``，把 framework
      直接传给 ``BUNDLE``；否则 hook 收集结果会进入 ``_MEI`` 临时目录
    - hook 会检查 onefile ``.app`` 是否由 ``sparklehelper pyinstaller`` 启动；
      未经 wrapper 启动时直接中止并提示正确命令

Windows 收集策略:
    - 单个 ``WinSparkle.dll`` 收集到 PyInstaller 内部目录；PyInstaller 6
      onedir 默认为 ``_internal/WinSparkle.dll``
    - 无 Mach-O 检测、无符号链接重建

PyInstaller 6.x 通过 ``pyinstaller40`` entry point (``hook-dirs``) 自动加载本 hook，
下游 ``pip install sparklehelper`` 后打包无需 ``--additional-hooks-dir``。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

hiddenimports = ["sparklehelper"]


def _resolve_winsparkle_path():
    """Windows：解析 WinSparkle.dll 路径（优先级 env → exe_dir → _MEIPASS → bundled）。

    复用运行时 ``_loading.resolve_winsparkle_path``，保持打包期与运行时
    定位逻辑一致（含按进程架构选 DLL）。
    """
    env = os.environ.get("SPARKLEHELPER_WINSPARKLE_PATH")
    if env:
        env = os.path.expanduser(env)
        if os.path.isfile(env):
            return os.path.abspath(env)
        raise SystemExit(
            "SPARKLEHELPER_WINSPARKLE_PATH points to a non-existent file: "
            f"{env}"
        )

    from sparklehelper._backend._windows._loading import resolve_winsparkle_path

    return resolve_winsparkle_path()


def _collect_winsparkle(hook_api):
    """Windows：收集 WinSparkle.dll 到 PyInstaller 内部目录。"""
    dll_path = _resolve_winsparkle_path()
    hook_api.analysis.binaries.append(("WinSparkle.dll", dll_path, "BINARY"))


def _collect_sparkle_framework(hook_api):
    """macOS：收集 Sparkle.framework（Mach-O 检测 + 符号链接重建）。"""
    from sparklehelper._pyinstaller import collect_sparkle_framework_toc

    for entry in collect_sparkle_framework_toc(include_versions_current=False):
        if entry[2] == "DATA":
            hook_api.analysis.datas.append(entry)
        else:
            hook_api.analysis.binaries.append(entry)


def _current_spec_uses_onefile_bundle() -> bool:
    try:
        from PyInstaller.config import CONF
        from sparklehelper._pyinstaller import spec_uses_onefile_bundle

        spec = CONF.get("spec")
        if not spec:
            return False
        return spec_uses_onefile_bundle(Path(spec).read_text(encoding="utf-8"))
    except Exception:
        return False


def _require_wrapper_for_onefile_bundle():
    from sparklehelper._pyinstaller import PYINSTALLER_WRAPPER_ENV

    if not _current_spec_uses_onefile_bundle():
        return
    if os.environ.get(PYINSTALLER_WRAPPER_ENV) == "1":
        return

    raise SystemExit(
        "sparklehelper: macOS PyInstaller onefile .app builds must use "
        "`sparklehelper pyinstaller app.spec`. Plain `pyinstaller app.spec` "
        "places Sparkle.framework in the _MEI extraction directory instead of "
        "Contents/Frameworks."
    )


def hook(hook_api):
    """按平台分发：macOS 收集 Sparkle.framework，Windows 收集 WinSparkle.dll。"""
    if sys.platform == "win32":
        _collect_winsparkle(hook_api)
        return
    _require_wrapper_for_onefile_bundle()
    _collect_sparkle_framework(hook_api)
