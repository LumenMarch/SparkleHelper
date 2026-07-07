"""sparklehelper 异常层级。

把 Sparkle/NSError 场景翻译成有意义的 Python 异常，
让用户代码可以按语义捕获，而不是面对裸字符串或 NSError code。
"""

from __future__ import annotations


class SparkleError(Exception):
    """所有 sparklehelper 异常的基类。"""


class SparkleNotAvailableError(SparkleError):
    """Sparkle 运行时不可用。

    触发场景：
    - 当前平台不是 macOS（``sys.platform != "darwin"``）。
    - 找不到 ``Sparkle.framework``（未嵌入 .app 的 Contents/Frameworks/，
      wheel 内置副本缺失，且未通过 ``SPARKLEHELPER_FRAMEWORK_PATH`` 提供）。
    - framework 已加载但缺少必需的类（如 ``SPUStandardUpdaterController``）。
    """


class NotABundleError(SparkleError):
    """当前进程不在 ``.app`` bundle 内。

    Sparkle 只能在真正的 macOS .app bundle 中工作（它需要读取
    ``Contents/Info.plist`` 中的 ``SUFeedURL`` 等，并把更新替换到
    bundle 内）。用 ``python script.py`` 直接运行脚本会触发此错误。
    """


class ConfigurationError(SparkleError):
    """Sparkle 配置缺失或无效。

    典型场景：``Info.plist`` 缺少 ``SUFeedURL`` 或 ``SUPublicEDKey``。
    """


class UpdateCheckError(SparkleError):
    """更新检查失败。

    对应 Sparkle 在拉取/解析 appcast feed、下载更新时发生的网络或解析错误。
    ``cause`` 携带原始 ``NSError`` 或底层异常，便于诊断。
    """

    def __init__(self, message: str = "", *, cause: object | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class WrongThreadError(SparkleError):
    """在非主线程调用了必须主线程执行的 API。

    Sparkle（以及 Cocoa）绝大多数 API 要求在主线程调用。
    sparklehelper 在进入这些 API 前会主动断言，给出比 Cocoa 崩溃更清晰的报错。
    """


__all__ = [
    "SparkleError",
    "SparkleNotAvailableError",
    "NotABundleError",
    "ConfigurationError",
    "UpdateCheckError",
    "WrongThreadError",
]
