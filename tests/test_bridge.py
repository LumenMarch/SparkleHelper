"""运行时基础设施：主线程断言、bundle 解析、KVO observer。

主线程断言与 .app 路径解析是纯 Python 逻辑，可在任意平台测试。
KVO observer 类的创建需要 Cocoa，放在 darwin marker 下。
"""

from __future__ import annotations

import sys
import threading

import pytest

from sparklehelper._backend._macos import _runtime
from sparklehelper.errors import NotABundleError, WrongThreadError


# ---------------------------------------------------------------------------
# 主线程断言
# ---------------------------------------------------------------------------


def test_assert_main_thread_passes_on_main():
    # pytest 默认在主线程跑。
    _runtime.assert_main_thread()


def test_assert_main_thread_raises_off_main():
    err_box: list[BaseException | None] = [None]

    def worker():
        try:
            _runtime.assert_main_thread()
        except BaseException as exc:  # noqa: BLE001
            err_box[0] = exc

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert isinstance(err_box[0], WrongThreadError)


def test_on_main_thread_direct_call_when_already_main():
    @_runtime.on_main_thread
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


# ---------------------------------------------------------------------------
# bundle 解析
# ---------------------------------------------------------------------------


def test_host_bundle_path_rejects_plain_python(monkeypatch):
    # 模拟 `python script.py`：executable 不在 .app 内。
    monkeypatch.setattr(sys, "executable", "/usr/local/bin/python3")
    with pytest.raises(NotABundleError, match=".app"):
        _runtime.host_bundle_path()


def test_host_bundle_path_resolves_app(monkeypatch):
    # 模拟 PyInstaller 打包的 .app：Contents/MacOS/Foo
    fake_exe = "/Apps/Foo.app/Contents/MacOS/Foo"
    monkeypatch.setattr(sys, "executable", fake_exe)
    path = _runtime.host_bundle_path()
    assert path.endswith("Foo.app")


def test_in_app_bundle_predicate(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/usr/local/bin/python3")
    assert _runtime.in_app_bundle() is False

    monkeypatch.setattr(sys, "executable", "/Apps/Bar.app/Contents/MacOS/Bar")
    assert _runtime.in_app_bundle() is True


def test_bundle_info_plist_returns_dict_on_non_darwin():
    # 非 darwin 无 NSBundle，应安全降级为空 dict 而非抛错。
    result = _runtime.bundle_info_plist()
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# KVO observer 类创建（仅 darwin）
# ---------------------------------------------------------------------------


@pytest.mark.darwin
def test_kvo_observer_class_creation():
    cls = _runtime.get_kvo_observer_class()
    assert cls is _runtime.get_kvo_observer_class()  # 缓存
