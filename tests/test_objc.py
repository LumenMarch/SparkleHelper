"""MacOSBackend：Sparkle.framework 的运行时加载。

测试通过 mock ``objc.loadBundle`` / ``objc.lookUpClass`` / NSBundle，
在任意平台验证路径解析优先级、缓存、错误语义，不真正加载 framework。
"""

from __future__ import annotations

import os
import sys
import types

import pytest

from sparklehelper._backend._macos import MacOSBackend, _loading
from sparklehelper.errors import SparkleNotAvailableError


# ---------------------------------------------------------------------------
# 平台检查
# ---------------------------------------------------------------------------


def test_load_sparkle_rejects_non_darwin(reset_backend_cache, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SparkleNotAvailableError, match="macOS-only"):
        MacOSBackend.load_sparkle()


# ---------------------------------------------------------------------------
# 路径解析优先级
# ---------------------------------------------------------------------------


def _fake_sparkle_module():
    """构造一个假的 sparkle module，含 loadBundle 注入的伪类。"""
    return types.ModuleType("sparklehelper._sparkle_runtime")


def _patch_objc_for_success(monkeypatch, required_classes=("SPUStandardUpdaterController", "SPUUpdater")):
    """让 MacOSBackend.load_sparkle 在不真正加载 framework 的情况下走通。"""

    def fake_loadbundle(name, globals_dict, bundle_path=None, **kw):
        # 模拟 loadBundle：把"类"塞进 globals，并在 lookUpClass 里可查。
        for cls_name in required_classes:
            globals_dict[cls_name] = type(cls_name, (), {})
        # 同时把这些类注册进 fake lookUpClass 表。
        for cls_name in required_classes:
            _lookup_table[cls_name] = globals_dict[cls_name]

    _lookup_table: dict = {}

    fake_objc = types.ModuleType("objc")
    fake_objc.loadBundle = fake_loadbundle

    class _LookupError(Exception):
        pass

    fake_objc.error = _LookupError

    def fake_lookup(name):
        if name in _lookup_table:
            return _lookup_table[name]
        raise _LookupError(name)

    fake_objc.lookUpClass = fake_lookup

    # 插入到 sys.modules，让 _loading 内部 `import objc` 命中。
    monkeypatch.setitem(sys.modules, "objc", fake_objc)
    return fake_objc


def test_explicit_path_wins(reset_backend_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    fw = tmp_path / "Sparkle.framework"
    fw.mkdir()

    _patch_objc_for_success(monkeypatch)

    MacOSBackend.load_sparkle(framework_path=str(fw))
    assert MacOSBackend.is_loaded()
    assert os.path.realpath(MacOSBackend.loaded_path()) == os.path.realpath(str(fw))


def test_env_var_path_used_when_no_explicit(reset_backend_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    fw = tmp_path / "Sparkle.framework"
    fw.mkdir()
    monkeypatch.setenv("SPARKLEHELPER_FRAMEWORK_PATH", str(fw))
    # main bundle 解析应返回 None（测试环境无 NSBundle）。
    monkeypatch.setattr(_loading, "main_bundle_frameworks_path", lambda: None)

    _patch_objc_for_success(monkeypatch)

    MacOSBackend.load_sparkle()
    assert os.path.realpath(MacOSBackend.loaded_path()) == os.path.realpath(str(fw))


def test_bundled_framework_used_when_no_override(reset_backend_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("SPARKLEHELPER_FRAMEWORK_PATH", raising=False)
    monkeypatch.setattr(_loading, "main_bundle_frameworks_path", lambda: None)
    framework = tmp_path / "Sparkle.framework"
    framework.mkdir()

    from sparklehelper import _framework

    monkeypatch.setattr(_framework, "bundled_framework_path", lambda: framework)
    _patch_objc_for_success(monkeypatch)

    MacOSBackend.load_sparkle()
    assert os.path.realpath(MacOSBackend.loaded_path()) == os.path.realpath(framework)


def test_explicit_path_must_exist(reset_backend_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    missing = tmp_path / "nope.framework"
    with pytest.raises(SparkleNotAvailableError, match="does not exist"):
        MacOSBackend.load_sparkle(framework_path=str(missing))


def test_load_is_idempotent(reset_backend_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    fw = tmp_path / "Sparkle.framework"
    fw.mkdir()
    fake = _patch_objc_for_success(monkeypatch)

    call_count = {"n": 0}
    orig = fake.loadBundle

    def counting(name, globals_dict, bundle_path=None, **kw):
        call_count["n"] += 1
        orig(name, globals_dict, bundle_path=bundle_path, **kw)

    fake.loadBundle = counting

    MacOSBackend.load_sparkle(framework_path=str(fw))
    first_path = MacOSBackend.loaded_path()
    MacOSBackend.load_sparkle(framework_path=str(fw))  # 第二次应命中缓存

    assert call_count["n"] == 1, "重复 loadBundle 应被缓存拦截"
    assert MacOSBackend.loaded_path() == first_path


def test_missing_required_class_raises(reset_backend_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    fw = tmp_path / "Sparkle.framework"
    fw.mkdir()
    # 故意让 loadBundle 不注入 SPUUpdater，模拟损坏的 framework。
    _patch_objc_for_success(monkeypatch, required_classes=("SPUStandardUpdaterController",))

    with pytest.raises(SparkleNotAvailableError, match="missing classes"):
        MacOSBackend.load_sparkle(framework_path=str(fw))


def test_get_sparkle_returns_loaded_module(reset_backend_cache, monkeypatch, tmp_path):
    """get_sparkle() 在已加载时返回同一对象，未加载时触发 load_sparkle()。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    fw = tmp_path / "Sparkle.framework"
    fw.mkdir()
    monkeypatch.setattr(_loading, "main_bundle_frameworks_path", lambda: None)
    _patch_objc_for_success(monkeypatch)

    # 先用显式路径加载（get_sparkle 不接收 path 参数，需先建立缓存）。
    assert not MacOSBackend.is_loaded()
    first = MacOSBackend.load_sparkle(framework_path=str(fw))
    assert MacOSBackend.is_loaded()

    # get_sparkle 应返回已加载的同一对象，不重复加载。
    assert MacOSBackend.get_sparkle() is first
