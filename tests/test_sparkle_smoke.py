"""darwin 上真加载 wheel 内 Sparkle.framework 的冒烟测试。

非 darwin 由 ``darwin`` marker 自动 skip；framework 未同步时 skipif。
错写 init selector 会在这里变成 AttributeError，而不是 mock 层的静默通过。
"""

from __future__ import annotations

import pytest

from sparklehelper import _framework
from sparklehelper._backend._macos import MacOSBackend, _loading, _runtime


@pytest.mark.darwin
@pytest.mark.skipif(
    not _framework.bundled_framework_path().exists(),
    reason="Sparkle.framework 为构建期获取，未同步时不存在",
)
def test_real_sparkle_load_controller_selector_and_kvo(reset_backend_cache):
    sparkle = MacOSBackend.load_sparkle(
        framework_path=str(_framework.bundled_framework_path())
    )
    assert _loading.is_loaded()
    controller_cls = sparkle.SPUStandardUpdaterController
    updater_cls = sparkle.SPUUpdater
    assert controller_cls is not None
    assert updater_cls is not None

    init = controller_cls.alloc().initWithStartingUpdater_updaterDelegate_userDriverDelegate_
    controller = init(False, None, None)
    if controller is None:
        return

    updater = controller.updater()
    observer_cls = _runtime.get_kvo_observer_class()
    seen: list = []

    def callback(value):
        seen.append(value)

    observer = observer_cls.alloc().initWithCallback_target_keyPath_(
        callback, updater, "canCheckForUpdates"
    )
    from Foundation import (
        NSKeyValueObservingOptionInitial,
        NSKeyValueObservingOptionNew,
    )

    options = NSKeyValueObservingOptionNew | NSKeyValueObservingOptionInitial
    updater.addObserver_forKeyPath_options_context_(
        observer, "canCheckForUpdates", options, 0
    )
    subscription = _runtime.Subscription(
        observer=observer, target=updater, key_path="canCheckForUpdates"
    )
    subscription.cancel()
    assert seen  # OptionInitial 应立即回调一次
