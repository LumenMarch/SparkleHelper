"""errors 模块：异常层级与语义。

这些是纯 Python 逻辑，可在任意平台验证，无需 mock。
"""

from __future__ import annotations

import pytest

from sparklehelper import errors


def test_base_class_is_exception():
    assert issubclass(errors.SparkleError, Exception)


@pytest.mark.parametrize(
    "name",
    [
        "SparkleNotAvailableError",
        "NotABundleError",
        "ConfigurationError",
        "UpdateCheckError",
        "WrongThreadError",
    ],
)
def test_subclasses_inherit_from_base(name):
    cls = getattr(errors, name)
    assert issubclass(cls, errors.SparkleError)


def test_update_check_error_carries_cause():
    original = ValueError("boom")
    err = errors.UpdateCheckError("检查失败", cause=original)
    assert "检查失败" in str(err)
    assert err.cause is original


def test_can_catch_all_via_base():
    with pytest.raises(errors.SparkleError):
        raise errors.NotABundleError("x")
    with pytest.raises(errors.SparkleError):
        raise errors.WrongThreadError("x")
