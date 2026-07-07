"""pytest 公共 fixture。

本包是 macOS 专用（依赖 PyObjC + Sparkle.framework），但单元测试需要
在非 darvin CI 上也能导入并运行逻辑层。因此：

- 凡真正需要 Cocoa/Sparkle 运行时的测试，标记 ``@pytest.mark.darwin``，
  在非 darvin 上整体跳过。
- 纯 Python 逻辑（路径解析、异常、dataclass 转换、delegate 转发）
  通过 mock ObjC 层在任意平台测试。
"""

from __future__ import annotations

import sys

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "darwin: 需要 macOS/PyObjC/Sparkle 的测试")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if sys.platform == "darwin":
        return
    skip_darwin = pytest.mark.skip(reason="非 darwin 平台，跳过需要 Cocoa 的测试")
    for item in items:
        if "darwin" in item.keywords:
            item.add_marker(skip_darwin)


@pytest.fixture
def reset_backend_cache():
    """每个测试前后清空 MacOSBackend 的进程级缓存，保证用例间隔离。"""
    from sparklehelper._backend._macos import MacOSBackend

    MacOSBackend._reset_for_test()
    yield
    MacOSBackend._reset_for_test()
