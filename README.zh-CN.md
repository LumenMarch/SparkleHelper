# 1. SparkleHelper

[English](README.md) | [简体中文](README.zh-CN.md)

> 面向原生应用更新的 Python 运行时接口：macOS 使用
> [Sparkle](https://github.com/sparkle-project/Sparkle)，Windows 使用
> [WinSparkle](https://github.com/vslavik/winsparkle)。

SparkleHelper 让你用 Python 在打包后的桌面应用里集成检查更新、后台下载与原生
更新 UI：macOS `.app` 使用 Sparkle，Windows 可执行程序使用 WinSparkle，
无需手写 Objective-C / Swift 或 Win32 更新桥接。

## 2. 为什么需要它

[Sparkle](https://github.com/sparkle-project/Sparkle) 与
[WinSparkle](https://github.com/vslavik/winsparkle) 是成熟的原生更新框架，
但暴露的是平台特定的 Objective-C / C API。SparkleHelper 为 Python 桌面应用
提供统一运行时 facade，同时保留各平台的原生更新体验。它解决三件事：

1. **运行时加载** —— macOS 动态加载 wheel 内置的 `Sparkle.framework`，
   Windows 动态加载 `WinSparkle.dll`。
2. **Python 化 API** —— 用带类型的 `Updater` facade 封装
   `SPUStandardUpdaterController` / `SPUUpdater` 与 WinSparkle C API。
3. **离线打包** —— wheel 内置目标平台的原生更新运行时，由支持的打包器直接收集，
   不访问网络。

## 3. 快速上手

### 3.1. 安装

```bash
# uv 项目
uv add sparklehelper

# 或直接用 pip
pip install sparklehelper
```

需要 Python ≥ 3.11。如需本地开发 SparkleHelper 本体，参见第 8 章「开发」
的 editable 安装方式（含开发依赖）。

### 3.2. 在应用内使用

macOS 上 Sparkle 必须在打包后的 `.app` bundle 内运行，因为它依赖 bundle
结构与 `Info.plist`。Windows 上 WinSparkle 需要在启动 native runtime 前通过
`Updater(...)` 配置。

macOS 最小用法：

```python
from sparklehelper import Updater

updater = Updater()              # 读 Info.plist 的 SUFeedURL
updater.check_for_updates()      # 弹出 Sparkle 原生更新窗口
```

Windows 最小用法：

```python
from sparklehelper import Updater

updater = Updater(
    feed_url="https://example.com/appcast.xml",
    public_key="...",
    company="Example",
    app_name="ExampleApp",
    version="0.1.0",
)
updater.check_for_updates()      # 弹出 WinSparkle 原生更新窗口
```

macOS 上可绑定到 GUI 菜单，并用 KVO 控制启用态：

```python
updater = Updater()

with updater.observe_can_check_for_updates(menu_item.setEnabled):
    # 期间菜单项状态随 Sparkle 自动刷新
    ...
```

其它 macOS KVO 属性可通过统一入口订阅：

```python
subscription = updater.observe(
    "automatically_downloads_updates",
    settings_view.set_auto_download_enabled,
)
```

macOS 自定义 feed 来源与频道过滤（实现 `UpdaterDelegate` 的**任意子集**即可）。
Windows 直接把 `feed_url` 传给 `Updater(...)`：

```python
class MyDelegate:
    def feed_url_string_for_updater(self):
        return "https://example.com/appcast.xml"
    def allowed_channels_for_updater(self):
        return ("beta",) if is_beta_user() else ()

updater = Updater(delegate=MyDelegate())
```

## 4. 平台配置

### 4.1. macOS

Sparkle 的 macOS 核心配置放在 `.app` 的 `Info.plist` 里：

| 键 | 必需 | 说明 |
|---|---|---|
| `SUFeedURL` | 是 | appcast.xml 的公开 URL |
| `SUPublicEDKey` | 是 | EdDSA 公钥，校验更新签名 |
| `SUEnableAutomaticChecks` | 否 | 是否开启自动检查（默认开） |
| `SUScheduledCheckInterval` | 否 | 检查间隔（秒，默认 86400） |

Nuitka wrapper 支持 Sparkle 2.x `SUConstants.h` 暴露的完整 host-app
plist key 集合；任意 key 可用 `--sparkle-key KEY=VALUE`，也可用自动生成的
kebab-case 选项，例如 `--su-automatically-update true`。

### 4.2. Windows

WinSparkle 需要在 `win_sparkle_init()` 前从 Python 侧拿到初始化配置：

| `Updater(...)` 参数 | 必需 | 说明 |
|---|---|---|
| `feed_url` | 是 | appcast.xml 的公开 URL |
| `public_key` | 建议 | EdDSA 公钥，校验更新签名 |
| `company` / `app_name` / `version` | 建议 | WinSparkle 展示与设置存储所需的应用标识 |
| `build` | 否 | 用于版本比较的构建版本 |

## 5. 打包

SparkleHelper 对两大主流 Python 打包器都提供一等支持。wheel
会内置目标平台的原生运行时：macOS 为 `Sparkle.framework`，Windows 为
`WinSparkle.dll`，打包时不会下载 native 资源。

### 5.1. PyInstaller

SparkleHelper 注册了一个内置的 PyInstaller hook（通过 `pyinstaller40`
入口点），在构建时收集目标平台的原生更新资源。默认使用 wheel
内置副本；开发或兼容性测试时，macOS 可用 `SPARKLEHELPER_FRAMEWORK_PATH`，
Windows 可用 `SPARKLEHELPER_WINSPARKLE_PATH` 覆盖来源。

```bash
pyinstaller my_app.spec
```

macOS 在 `.spec` 的 `info_plist={}` 里注入 Sparkle 相关键即可，参考
[`examples/demo_app/build.spec`](examples/demo_app/build.spec)。Python 侧无需
额外参数。Windows 则通过 `Updater(...)` 传入 WinSparkle 配置。

macOS onefile `.app` spec（形如 `BUNDLE(exe, ...)`）使用 wrapper 命令：

```bash
uv run sparklehelper pyinstaller my_app.spec
```

wrapper 会临时生成一个修补后的 spec，把 `Sparkle.framework` 从 `Analysis`
移交给 `BUNDLE`，因此 framework 会进入 `Contents/Frameworks`，不会进入
onefile 的 `_MEI...` 解压目录。onedir spec（形如 `BUNDLE(coll, ...)`）
不需要 wrapper，继续直接使用 `pyinstaller` 即可。如果 onefile `.app`
spec 直接用 `pyinstaller` 构建，hook 会中止构建并提示改用 wrapper。

### 5.2. Nuitka

SparkleHelper 以包数据形式随附 Nuitka 包配置与 user plugin。Nuitka
不会自动发现这两类第三方资源，因此使用 `sparklehelper nuitka` wrapper
自动注入它们，再将其余参数原样转发给 Nuitka。

要求：

- Nuitka **4.1.2** 及以上。
- Sparkle wheel 需要 macOS 11 及以上；WinSparkle wheel 面向 Windows。

```bash
uv run sparklehelper nuitka \
  --version 0.1.0 \
  --build-version 1 \
  --feed-url https://example.com/appcast.xml \
  --public-ed-key YOUR_EDDSA_PUBLIC_KEY_BASE64 \
  --mode=app \
  my_app.py
```

配置会收集 wheel 内置副本；macOS 放入
`Contents/Frameworks/Sparkle.framework`，Windows 放入 Nuitka dist 根目录下的
`WinSparkle.dll`，运行时通过 Nuitka 的 `__compiled__.containing_dir`
定位该目录。

macOS 上 plugin 会在 Nuitka 签名前恢复 framework 顶层的 `Autoupdate`
符号链接。wrapper 的 `--version` 会写入
`CFBundleShortVersionString`；未传 `--version` 且未透传 Nuitka 原生
`--macos-app-version` 时默认使用 `0.1.0`。`--build-version` 可选写入 Sparkle
可比较的 `CFBundleVersion`；未传时会从 `--version` 自动推导 Apple 兼容的
构建版本，例如 `0.1.0` 会变成构建版本 `1`。wrapper 也支持通过
`--feed-url`、`--public-ed-key`、`--automatic-checks`、
`--scheduled-check-interval` 等别名写入 Sparkle Info.plist key，完整 key
可用重复的 `--sparkle-key KEY=VALUE` 传入；仅透传 Nuitka 原生
`--macos-app-version` 且未传 wrapper 版本参数时，plugin 会读取 Nuitka
生成的 `Info.plist`，只在缺少 `CFBundleVersion` 时按
`CFBundleShortVersionString` 自动补齐。
如果应用同时使用 pypylon，Nuitka
会按其 loader-relative 设计保留在
`Contents/Frameworks/pypylon/pylon.framework`。

构建 demo：

```bash
cd examples/demo_app
uv run sparklehelper nuitka \
  --version 0.1.0 \
  --build-version 1 \
  --feed-url https://example.com/appcast.xml \
  --public-ed-key YOUR_EDDSA_PUBLIC_KEY_BASE64 \
  --mode=app \
  demo.py
```

wheel 不包含 `generate_keys`、`sign_update` 等 Sparkle release authoring
tools；制作签名更新时需单独获取这些工具。

## 6. API 概览

```text
Updater                       主入口（封装当前平台的 native backend）
├─ check_for_updates()        弹出原生更新窗口
├─ check_for_updates_in_background()
├─ start() / reset_update_cycle() / reset_update_cycle_after_short_delay()
├─ can_check_for_updates      macOS-only KVO 属性
├─ feed_url / host_bundle_path / last_update_check_date / system_profile
├─ automatically_checks_for_updates / update_check_interval
├─ automatically_downloads_updates / allows_automatic_updates
├─ user_agent_string / http_headers / sends_system_profile
└─ observe(property_name, cb) -> Subscription  macOS-only KVO 订阅

UpdaterDelegate              macOS-only 可选回调 Protocol
├─ updater_may_perform_update_check()
├─ feed_url_string_for_updater()
├─ allowed_channels_for_updater()
├─ feed_parameters_for_updater() / allowed_system_profile_keys_for_updater()
├─ updater_did_find_valid_update()
├─ updater_did_not_find_update()
├─ updater_should_proceed_with_update() / updater_user_did_make_choice()
├─ updater_will_download_update() / updater_did_download_update()
├─ updater_failed_to_download_update() / user_did_cancel_download()
├─ updater_will_extract_update() / updater_did_extract_update()
├─ updater_will_install_update() / updater_should_relaunch_application()
├─ updater_will_schedule_update_check() / updater_will_not_schedule_update_check()
└─ updater_did_abort() / updater_did_finish_cycle()

UpdateInfo / SystemProfileEntry / UpdateCheckResult / UserUpdateState   dataclass
UpdateCheckKind / UserUpdateChoice / UserUpdateStage                    枚举

ensure_runnable()            聚合检查：平台/native runtime/配置
errors                       SparkleError 异常层级
```

## 7. 平台约束

- **macOS 主线程**：Sparkle/Cocoa API 必须主线程调用，SparkleHelper 入口处主动断言。
- **macOS bundle**：Sparkle 需打包成 `.app`，`ensure_runnable()` 会检测 bundle
  与 plist。
- **Sparkle 自带 UI**：`check_for_updates()` 零配置弹原生窗口
  （内置 `SPUStandardUserDriver` + framework 内 nib）。
- **macOS 持久化**：动态设置仍落到 Sparkle 自己的 NSUserDefaults，
  遵循官方"不要在用户偏好上再加一层"的建议。
- **macOS GUI run loop**：Sparkle 的 `startUpdater` 是
  异步的，依赖 NSApp run loop 完成；`canCheckForUpdates` 在 run loop 转起来后
  才变 True。因此宿主 GUI 必须驱动 NSApp run loop——**wxPython、PyQt/PySide、
  PyObjC/AppKit 原生** 都可以；**tkinter 不行**（它用独立 Tcl 事件循环，不与
  NSApp 协同，会导致菜单项永远灰色）。详见
  [`examples/demo_app/README.md`](examples/demo_app/README.md)。
- **macOS 延迟 `start()`**：`Updater()` 默认不启动自动检查调度。GUI 应用应在
  进入 mainloop 后再调 `start()`（demo 用 `wx.CallAfter` 实现）；只有确认
  NSApp run loop 已准备好时才传 `start=True`。
- **Windows cleanup**：WinSparkle 会在 `win_sparkle_init()` 后启动后台工作。
  应用退出前调用 `cleanup()`，或用 `Updater(...)` 作为 context manager。

## 8. 开发

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest                # 单元测试（mock ObjC 层，任意平台可跑）
```

### 8.1. 维护者构建 wheel

本仓库采用 packaging repo 模式：主包源码树不再提交大体积 native 运行时二进制
（`Sparkle.framework`、`WinSparkle.dll`），改为在 wheel 构建期获取。

- 普通安装 —— 发布的 wheel 已内置 native 资源，终端用户无需联网或编译。
- 上游源码引用 —— `Sparkle/` 与 `winsparkle/` 是 Git submodule，固定到上游
  提交用于源码浏览，形态与 opencv-python 的 packaging repo 一致，GitHub 会
  显示类似 `Sparkle @ <commit>` 的入口。
- 首次克隆 —— 使用 `git clone --recursive`，或克隆后运行
  `git submodule update --init --recursive`。
- 构建 wheel —— `uv build --wheel` 会解析最新上游 Sparkle / WinSparkle
  release asset，校验 SHA256、同步对应上游 license 后解包进 wheel。归档缓存于
  `build/native-cache/`，后续构建复用，不重复下载。
- 离线构建 —— 提前保留已生成的 native 文件；或设置
  `SPARKLEHELPER_SKIP_NATIVE_SYNC=1`，禁止联网、只校验本地 native/license
  资源（缺失时报错）。
- 入库与生成 —— 上游源码引用以 gitlink 入库；包资源只提交
  `src/sparklehelper/winsparkle/winsparkle.h`。`Sparkle.framework/`、
  `winsparkle/*/WinSparkle.dll` 与 `src/sparklehelper/licenses/*.txt`
  被 git 忽略，由
  `scripts/sync_native_deps.py` 重新生成。

## 9. 许可证

SparkleHelper 采用 MIT 许可。内置 native 依赖按各自上游许可再分发：

- `Sparkle.framework`：`sparklehelper/licenses/Sparkle-LICENSE.txt`
- `WinSparkle.dll`：`sparklehelper/licenses/WinSparkle-LICENSE.txt`
