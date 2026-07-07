# 1. SparkleHelper

[English](README.md) | [简体中文](README.zh-CN.md)

> A Python runtime interface for native app updates with
> [Sparkle](https://github.com/sparkle-project/Sparkle) on macOS and
> [WinSparkle](https://github.com/vslavik/winsparkle) on Windows.

SparkleHelper lets you integrate check-for-updates, background download, and
native update UI into packaged Python desktop apps — Sparkle for macOS `.app`
bundles and WinSparkle for Windows executables — without writing
Objective-C / Swift or Win32 update plumbing.

## 2. Why

[Sparkle](https://github.com/sparkle-project/Sparkle) and
[WinSparkle](https://github.com/vslavik/winsparkle) are mature native update
frameworks, but they expose platform-specific Objective-C and C APIs.
SparkleHelper gives Python desktop apps one runtime facade while preserving
the native updater on each platform. It solves three things:

1. **Runtime loading** — dynamically load the bundled `Sparkle.framework` on
   macOS or `WinSparkle.dll` on Windows.
2. **Pythonic API** — expose a typed `Updater` facade over
   `SPUStandardUpdaterController` / `SPUUpdater` and the WinSparkle C API.
3. **Offline packaging** — ship platform-native update runtimes inside wheels
   and let supported bundlers collect them without network access.

## 3. Quick start

### 3.1. Install

```bash
# uv project
uv add sparklehelper

# or plain pip
pip install sparklehelper
```

Requires Python ≥ 3.11. To hack on SparkleHelper itself, see §8 Development
for an editable install with dev dependencies.

### 3.2. Use in an app

On macOS, Sparkle must run inside a packaged `.app` bundle because it depends
on the bundle structure and `Info.plist`. On Windows, WinSparkle is configured
from `Updater(...)` before its native runtime is started.

macOS minimal usage:

```python
from sparklehelper import Updater

updater = Updater()              # reads SUFeedURL from Info.plist
updater.check_for_updates()      # pops the native Sparkle update window
```

Windows minimal usage:

```python
from sparklehelper import Updater

updater = Updater(
    feed_url="https://example.com/appcast.xml",
    public_key="...",
    company="Example",
    app_name="ExampleApp",
    version="0.1.0",
)
updater.check_for_updates()      # pops the native WinSparkle update window
```

On macOS, bind it to a GUI menu item and drive its enabled state via KVO:

```python
updater = Updater()

with updater.observe_can_check_for_updates(menu_item.setEnabled):
    # the menu item's state refreshes automatically while inside the block
    ...
```

Other macOS KVO properties can be subscribed to through the unified entry point:

```python
subscription = updater.observe(
    "automatically_downloads_updates",
    settings_view.set_auto_download_enabled,
)
```

macOS custom feed source and channel filtering (implement **any subset** of
`UpdaterDelegate`). On Windows, pass `feed_url` directly to `Updater(...)`:

```python
class MyDelegate:
    def feed_url_string_for_updater(self):
        return "https://example.com/appcast.xml"
    def allowed_channels_for_updater(self):
        return ("beta",) if is_beta_user() else ()

updater = Updater(delegate=MyDelegate())
```

## 4. Platform configuration

### 4.1. macOS

Sparkle's core macOS configuration lives in the `.app` `Info.plist`:

| Key | Required | Description |
|---|---|---|
| `SUFeedURL` | Yes | Public URL of appcast.xml |
| `SUPublicEDKey` | Yes | EdDSA public key used to verify update signatures |
| `SUEnableAutomaticChecks` | No | Enable automatic checks (on by default) |
| `SUScheduledCheckInterval` | No | Check interval in seconds (default 86400) |

The Nuitka wrapper supports Sparkle's full host-app plist key set exposed by
Sparkle 2.x `SUConstants.h`; pass any of them with `--sparkle-key KEY=VALUE`
or the generated kebab-case option such as `--su-automatically-update true`.

### 4.2. Windows

WinSparkle must receive its init-time settings from Python before
`win_sparkle_init()`:

| `Updater(...)` argument | Required | Description |
|---|---|---|
| `feed_url` | Yes | Public URL of appcast.xml |
| `public_key` | Recommended | EdDSA public key used to verify update signatures |
| `company` / `app_name` / `version` | Recommended | App identity shown by WinSparkle and used for its settings |
| `build` | No | Build version used for update comparison |

## 5. Packaging

SparkleHelper ships first-class support for the two mainstream Python
bundlers. Wheels include the native runtime for their target platform:
`Sparkle.framework` for macOS and `WinSparkle.dll` for Windows, so packaging
never downloads native assets.

### 5.1. PyInstaller

SparkleHelper registers a built-in PyInstaller hook (via the
`pyinstaller40` entry point) that collects the platform-native updater at
build time. It uses the wheel copy by default; `SPARKLEHELPER_FRAMEWORK_PATH`
on macOS and `SPARKLEHELPER_WINSPARKLE_PATH` on Windows can override the source
for development or compatibility testing.

```bash
pyinstaller my_app.spec
```

On macOS, inject the Sparkle keys via `info_plist={}` in your `.spec`; see
[`examples/demo_app/build.spec`](examples/demo_app/build.spec) for a
reference. On Windows, pass WinSparkle settings to `Updater(...)`.

For macOS onefile `.app` specs shaped like `BUNDLE(exe, ...)`, use the
wrapper command instead:

```bash
uv run sparklehelper pyinstaller my_app.spec
```

The wrapper creates a temporary patched spec that moves `Sparkle.framework`
from `Analysis` into `BUNDLE`, so it lands in `Contents/Frameworks` instead of
the onefile `_MEI...` extraction directory. Onedir specs shaped like
`BUNDLE(coll, ...)` do not need this wrapper and should keep using plain
`pyinstaller`. If a onefile `.app` spec is built with plain `pyinstaller`, the
hook stops the build and points to this wrapper command.

### 5.2. Nuitka

SparkleHelper ships a Nuitka package config and user plugin as package data.
Nuitka does not auto-discover either third-party resource, so the
`sparklehelper nuitka` wrapper injects both before forwarding all remaining
arguments to Nuitka.

Requirements:

- Nuitka **4.1.2** or newer.
- macOS 11 or newer for Sparkle wheels, or Windows for WinSparkle wheels.

```bash
uv run sparklehelper nuitka \
  --version 0.1.0 \
  --build-version 1 \
  --feed-url https://example.com/appcast.xml \
  --public-ed-key YOUR_EDDSA_PUBLIC_KEY_BASE64 \
  --mode=app \
  my_app.py
```

The config collects the wheel's bundled copy and places it at
`Contents/Frameworks/Sparkle.framework` on macOS and at
`WinSparkle.dll` in the Windows Nuitka dist directory; the runtime locates this
directory through Nuitka's `__compiled__.containing_dir`.

On macOS, the plugin restores the framework's top-level `Autoupdate` symlink
before Nuitka signs the app. The wrapper's
`--version` option writes `CFBundleShortVersionString` and defaults to `0.1.0`
when neither `--version` nor Nuitka's native `--macos-app-version` is passed.
`--build-version` optionally writes the Sparkle-comparable `CFBundleVersion`;
when it is omitted, the wrapper derives an Apple-compatible build version from
`--version`, for example `0.1.0` becomes build version `1`. The wrapper also
accepts
Sparkle Info.plist keys via aliases such as `--feed-url`,
`--public-ed-key`, `--automatic-checks`, and `--scheduled-check-interval`, or
via repeated `--sparkle-key KEY=VALUE` entries for the full Sparkle key set. If
Nuitka's native `--macos-app-version` is forwarded without wrapper version
options, the plugin reads Nuitka's generated `CFBundleShortVersionString` from
`Info.plist` and only fills in a missing `CFBundleVersion`. If the application
also uses pypylon,
Nuitka intentionally keeps its loader-relative framework at
`Contents/Frameworks/pypylon/pylon.framework`.

To build the demo:

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

The wheel does not include Sparkle release authoring tools such as
`generate_keys` or `sign_update`; obtain those separately when producing
signed updates.

## 6. API overview

```text
Updater                       main entry (wraps the native platform backend)
├─ check_for_updates()        pops the native update window
├─ check_for_updates_in_background()
├─ start() / reset_update_cycle() / reset_update_cycle_after_short_delay()
├─ can_check_for_updates      macOS-only KVO property
├─ feed_url / host_bundle_path / last_update_check_date / system_profile
├─ automatically_checks_for_updates / update_check_interval
├─ automatically_downloads_updates / allows_automatic_updates
├─ user_agent_string / http_headers / sends_system_profile
└─ observe(property_name, cb) -> Subscription  macOS-only KVO subscription

UpdaterDelegate              macOS-only optional callback Protocol
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
UpdateCheckKind / UserUpdateChoice / UserUpdateStage                    enums

ensure_runnable()            aggregate check: platform/native runtime/config
errors                       SparkleError exception hierarchy
```

## 7. Platform constraints

- **macOS main thread**: Sparkle/Cocoa APIs must be called on the main thread;
  SparkleHelper asserts this at every entry point.
- **macOS bundle**: Sparkle must be packaged as a `.app`; `ensure_runnable()`
  checks the bundle and plist.
- **Sparkle ships its own UI**: `check_for_updates()` pops the native window
  with zero config (built-in `SPUStandardUserDriver` + the in-framework nib).
- **macOS persistence**: dynamic settings still land in Sparkle's own
  NSUserDefaults, following the official advice to "not add another layer on
  top of user preferences".
- **macOS GUI run loop**: Sparkle's
  `startUpdater` is asynchronous and depends on the NSApp run loop to
  complete; `canCheckForUpdates` only becomes `True` once the run loop is
  spinning. So the host GUI must drive the NSApp run loop — **wxPython,
  PyQt/PySide, PyObjC/AppKit native** all work; **tkinter does not** (it
  uses a separate Tcl event loop that does not interoperate with NSApp,
  leaving menu items permanently greyed out). See
  [`examples/demo_app/README.md`](examples/demo_app/README.md).
- **macOS delay `start()`**: `Updater()` does not start automatic checks by
  default. In GUI apps, call `start()` after entering the mainloop (the demo
  does this via `wx.CallAfter`), or pass `start=True` only when the NSApp run
  loop is already ready.
- **Windows cleanup**: WinSparkle starts background work in
  `win_sparkle_init()`. Call `cleanup()` before application exit, or use
  `Updater(...)` as a context manager.

## 8. Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest                # unit tests (mock the ObjC layer; run on any platform)
```

### 8.1. Building wheels (maintainers)

This is a packaging repo: the main package source tree no longer ships the
large native runtime binaries (`Sparkle.framework`, `WinSparkle.dll`). They
are fetched at wheel build time.

- Normal install — published wheels already embed the native assets, so end
  users need no network access or compiler.
- Upstream source refs — `Sparkle/` and `winsparkle/` are Git submodules
  pinned to upstream commits for source browsing, matching the opencv-python
  packaging-repo style where GitHub shows entries such as `Sparkle @ <commit>`.
- Fresh clone — use `git clone --recursive`, or run
  `git submodule update --init --recursive` after cloning.
- Building a wheel — `uv build --wheel` resolves the latest upstream
  Sparkle / WinSparkle release assets, verifies their SHA256, syncs the
  matching upstream license files, and unpacks them into the wheel. The archive
  is cached under
  `build/native-cache/` and reused on subsequent builds.
- Offline build — either keep the previously generated native files in place,
  or set `SPARKLEHELPER_SKIP_NATIVE_SYNC=1`, which forbids network access and
  only validates the local native/license assets (the build fails with a clear
  error if they are missing).
- Tracked vs. generated — upstream source references are tracked as gitlinks;
  package resources only commit `src/sparklehelper/winsparkle/winsparkle.h`.
  `Sparkle.framework/`, `winsparkle/*/WinSparkle.dll`, and
  `src/sparklehelper/licenses/*.txt` are git-ignored and regenerated by
  `scripts/sync_native_deps.py`.

## 9. License

SparkleHelper is MIT licensed. Bundled native dependencies are redistributed
under their upstream licenses:

- `Sparkle.framework`: `sparklehelper/licenses/Sparkle-LICENSE.txt`
- `WinSparkle.dll`: `sparklehelper/licenses/WinSparkle-LICENSE.txt`
