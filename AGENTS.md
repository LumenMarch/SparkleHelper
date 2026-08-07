# AGENTS.md — SparkleHelper 项目指南与工程约定

## 0. 工作原则

## 实现原则

### 1. 坚持长期主义

优先做长期正确的事情，而不是仅仅解决眼前问题。

“长期正确”是指：在目标和约束明确的前提下，选择全生命周期综合成本最低的方案，而不是只追求当前实施成本最低。

短期看似简单的方案，往往会通过技术债务、路径依赖、维护复杂度和未来重构成本延迟暴露代价。必要时，应承担合理的一次性结构成本，以换取系统长期的可维护性、可扩展性和决策自由度。

但长期主义不等于过度建设。对于生命周期短、影响范围小或需求高度不确定的问题，应控制前期投入，避免为尚未发生的需求提前设计复杂架构。

### 2. 追求优雅且务实的实现

优先选择简单、清晰、实用且不过度设计的方案。

“优雅”不是形式上的复杂或抽象，而是在满足当前目标、已知约束和合理演进需求的前提下，以尽可能少的概念、状态、依赖和特殊规则解决问题。

一个优雅的实现通常具备以下特征：

- 核心逻辑清晰，容易理解和验证；
- 模块边界明确，职责划分合理；
- 能复用已有能力，不重复造轮子；
- 能处理必要的边界条件和异常场景；
- 为可预见的变化保留空间，但不为纯粹假设提前设计；
- 实现成本、维护成本与业务价值相匹配。

当“长期正确”与“简单实现”发生冲突时，应明确说明权衡依据，包括方案生命周期、变更概率、影响范围、可逆性和未来修正成本。

## 思维原则

### 1. 从目标和事实出发

运用第一性原理分析问题，不盲从经验、惯例或既有路径。经验可以作为证据和参考，但不能代替对目标、约束和因果关系的分析。

不要默认用户已经完整定义了问题。应先识别：

- 用户真正想达成的目标；
- 当前问题的事实依据；
- 已知约束和未知信息；
- 用户方案中隐含的前提；
- 判断成功与否的验收标准。

### 2. 识别并纠正错误前提

主动识别问题中的隐含假设。

如果关键前提不成立，应先指出并解释其对结论的影响，再继续回答。不要在错误前提上构建看似完整但实际上无效的方案。

区分以下内容：

- 已确认事实；
- 基于事实作出的推断；
- 尚待验证的假设；
- 因信息不足而无法确定的部分。

不要把推测表达为事实。

### 3. 根据目标清晰度采取行动

- 目标清晰、路径合理：直接执行。
- 目标清晰、但当前路径明显不是最优：完成合理范围内的任务，同时指出更短、更低成本或风险更低的替代方案。
- 目标模糊，但可以通过低风险、可逆的假设继续推进：明确假设后执行。
- 目标模糊，且不同选择会显著影响结果：暂停实施，向用户确认关键问题。
- 信息可以通过现有代码、文档、工具或环境获得：先自行验证，不把可自行解决的问题交还给用户。

### 4. 给出明确、可验证的判断

能量化时，不使用模糊形容词代替数字；能形成明确结论时，不为了表面中立而回避判断。

回答应尽可能给出：

- 结论及其适用边界；
- 支撑结论的事实和推导；
- 关键风险与失败条件；
- 可执行的实施步骤；
- 验证方法和验收标准。

当证据不足时，应明确说明不确定性、缺失信息及验证方式，而不是使用模糊语言掩盖问题。

## 回答方式

优先直接回答用户当前问题，再根据实际需要补充深层分析。

### 直接执行

按照用户当前的目标和约束，直接给出结果、方案、代码、命令或操作步骤。

避免长篇铺垫。除非存在重大风险、错误前提或不可逆操作，否则不要在执行前重复确认已经明确的信息。

### 深度交互（按需）

仅在确有必要时，对用户的原始需求进行审慎挑战，例如：

- 当前请求可能是 XY 问题；
- 用户提出的手段偏离了真实目标；
- 当前路径存在未被意识到的长期成本；
- 存在更简单、更低成本或风险更低的替代方案；
- 关键事实、约束或验收标准缺失；
- 当前方案可能导致安全、合规、数据损失或不可逆后果。

挑战时应说明事实依据、推导过程和实际影响，并给出可落地的替代方案。不要为了体现“深度”而机械质疑，也不要在没有依据时揣测用户动机。

对于简单、明确的问题，可以只提供“直接执行”，无需强行增加“深度交互”。

## 与用户的关系

忠于事实、证据和可验证的推理，而不是迎合用户的预期。

挑战用户观点时，应保持尊重、直接和坚定：

- 不因用户期待某个结论而歪曲事实；
- 不以“可能都对”的方式回避关键判断；
- 不把观点分歧升级为立场对抗；
- 用户提供了更可靠的事实或推导后，应立即修正结论；
- 修正时说明变化的依据，不进行无意义的辩护；
- 对无法确认的内容，应明确承认不确定性并给出验证路径。

最终目标不是证明谁正确，而是共同得到更准确、更低成本且能够落地的结果。

## 1. 项目上下文

SparkleHelper 是为 macOS Sparkle / Windows WinSparkle 原生更新框架提供统一 Python 运行时接口、离线打包与发布工具链的库。项目定位、架构、平台约束、打包链路、开发命令、常见陷阱、已知边界与测试体系要点详见本文档后续章节。

## 2. 语言约定

- 回复与沟通用**简体中文**。
- 代码注释用**中文**，技术术语、API 名、库名、错误消息保留英文。
- **commit 与 PR 的标题、正文一律用英文**（与仓库历史一致；用户明确要求）。
- 标识符、命令名、文件路径、API 名保持原样。

## 3. 授权与变更范围

- **不主动 commit / push / 创建 PR**，用户明确要求才做。
- 从不直接向 `main` 提交；从 `main` 切 `<type>/<short-description>` 分支（如 `feat/multi-platform-backend`、`chore/ci-add-ruff-check`）。
- 每个 commit / PR 只围绕一个内聚关注点，不夹带无关改动。
- 不修改他人创建的 commit（amend / rebase / squash）除非用户明确要求。

## 4. Commit 规则

- **签名提交**：`commit.gpgsign=true` 已配置，提交时签名。
- 格式：`<type>(<scope>): <summary>`，scope 可选。
- 类型表：

  | type | 用途 |
  |---|---|
  | `feat` | 新用户可见功能 |
  | `fix` | 修复真实缺陷 |
  | `docs` | 文档改动 |
  | `update` | 翻译/内容更新 |
  | `upgrade` | 依赖、运行时、工具链升级 |
  | `change` | 行为变更（既非功能也非缺陷） |
  | `style` | 格式化、命名、错别字等纯样式改动 |
  | `refactor` | 内部重构、无行为变化 |
  | `chore` | 构建、CI、仓库、维护类工作 |
  | `perf` | 可度量的运行时/资源优化 |

- scope 可选，仅当历史提交都在用且能标识稳定区域时使用（仓库历史出现过 `ci`、`cli`、`build`、`test`、`readme`、`release`）。
- summary 用祈使语气、简洁、不无谓大写、结尾不加句号。
- 需要说明原因/风险/迁移/后续工作时加正文，解释"为什么改"与"改后需做什么"，不要逐行罗列 diff。

## 5. 本地验证

改动 Python 代码时，提交前运行：

```bash
uv run ruff check .
uv run ruff format .
uv run pytest tests/
```

每次变更前运行 `git diff --check`。纯文档改动可跳过代码检查（不会影响生成文件、构建配置或运行时行为）。

## 6. Pull Request 规则

- 提交 PR 前先跑完第 5 节本地验证。
- PR 标题与 commit subject 同格式：`<type>(<scope>): <summary>`。
- PR 正文用英文，建议含 Summary / Why 等小节，准确反映整个分支内容。
- 合并后让 GitHub 自动删除源分支。

## 7. 项目定位

SparkleHelper 是一个 **packaging-repo 风格的 Python 库**，为 macOS Sparkle（ObjC）与 Windows WinSparkle（C/ctypes）原生更新框架提供统一封装，职责有三：

1. **运行时接口**：向用户提供统一的 `Updater` 门面，无需手写 ObjC/C 桥接即可在 macOS/Windows 应用中使用 Sparkle/WinSparkle 的自动更新能力。
2. **离线打包**：wheel 内嵌平台原生运行时（`Sparkle.framework` / 三架构 `WinSparkle.dll`），通过 PyInstaller hook 与 Nuitka package config/plugin 在打包期收集，最终用户打包全程不联网。
3. **发布制作**：捆绑上游 `generate_keys` / `sign_update` / `generate_appcast` / `BinaryDelta`（macOS）与 `winsparkle-tool.exe`（Windows x64/ARM64），经 `sparklehelper release` CLI 转发。

## 8. 架构速览

```
sparklehelper/__init__.py       公共导出（Updater/UpdaterDelegate/Decision/types/errors）
├── updater.py                  Facade：配置收集 + 主线程断言 + 属性/方法转发
│   └── _backend/base.py        平台无关契约（UpdateBackend/UpdateConfig/Callbacks）
│       └── _backend/__init__.py 后端选择器 get_backend()：darwin→MacOSBackend，win32→WindowsBackend，其余抛 SparkleNotAvailableError
│           ├── _macos/          ObjC 桥接层（_loading 加载 / _runtime 主线程+bundle+KVO / _delegates 回调）
│           └── _windows/        ctypes 桥接层（_loading 定位加载 / _bindings 签名 / _backend 生命周期）
├── _framework.py               构建资源定位 + CLI（nuitka / pyinstaller / release / nuitka-config 四个子命令）
├── types.py                    SUAppcastItem→UpdateInfo 等 ObjC→Python dataclass 转换
├── errors.py                   SparkleError 异常层级（6 个异常）
├── _pyinstaller/               PyInstaller hook 目录 + TOC 收集/排除逻辑
├── _nuitka_plugin.py           Nuitka user plugin（framework 归一化恢复 + plist 补丁）
└── sparklehelper.nuitka-package.config.yml  Nuitka 包配置（data-files + dlls）
```

关键数据流：

1. **构造**：`Updater.__init__` → `assert_main_thread()` → darwin 分支读取 `bundle_info_plist()` 并校验 `CFBundleVersion`、`SUFeedURL`、`SUPublicEDKey`；显式 `feed_url` 经 `_FeedURLDelegateShim` 包装进 delegate；`public_key` 在 darwin 上仅告警并忽略。
2. **配置**：组装 `UpdateConfig` → `backend.configure(config)`。macOS 用 `objc.loadBundle` + `make_delegate_adapter` → `SPUStandardUpdaterController.alloc().initWithStartingUpdater_updaterDelegate_userDriverDelegate_`；Windows 用 `ctypes.CDLL` → init **前**调用 `set_appcast_url` / `set_eddsa_public_key` / `set_app_details` / `set_app_build_version`。
3. **启动**：`start()` → `[controller startUpdater]`（macOS）/ `win_sparkle_init()`（Windows），均幂等。
4. **检查更新**：`check_for_updates()` → `checkForUpdates`（macOS）/ `win_sparkle_check_update_with_ui()`（Windows）；后台版分别映射 `checkForUpdatesInBackground` / `check_update_without_ui`。
5. **delegate 回调**（macOS）：Sparkle 回调 ObjC adapter → `_DelegateAdapter` → `_SELECTOR_CALLBACKS` 名映射 → 用户 Python 方法（keyword-only 参数），异常吞掉并记日志；`respondsToSelector_` 按用户实现的方法动态应答。

## 9. 关键平台约束

### 9.1 macOS

- **必须 .app bundle 内运行**：`host_bundle_path()` 仅按 `sys.executable` 路径结构向上找 `*.app` 段；非 bundle 抛 `NotABundleError`。构造时强制 `CFBundleVersion`（缺失抛 `ConfigurationError`），`Updater(version=...)/build=...` 不能替代。
- **主线程断言**：`assert_main_thread()` 基于 `threading.main_thread()` 身份比较，`Updater` 所有入口与后端全部方法调用均强制；违者抛 `WrongThreadError`。另有 `on_main_thread` 装饰器可同步派发到主线程。
- **依赖 NSApp run loop**：`startUpdater` 异步，依赖 NSApp run loop 才能完成，`canCheckForUpdates` 才变 True。tkinter 不兼容。
- **CFBundleVersion 必填**：Sparkle 只认 bundle 的 build 版本。
- **`public_key` 在 macOS 无效**：仅告警并忽略（Sparkle 无运行时 EdDSA setter），触发 `DeprecationWarning`。
- **KVO**：惰性创建 `NSObject` 子类 observer，`observe()` 订阅后建立时立即回调一次；`Subscription.cancel()` 幂等，`__del__` 兜底注销。

### 9.2 Windows

- **`feed_url` 必填**：Windows 分支下必须显式提供，否则报错。
- **`cleanup` 必须调用**：`win_sparkle_cleanup()` 取消后台线程，退出前必须调用；`Updater` 支持 context manager。
- **`set_registry_path` 须在 `start()` 前调用**（WinSparkleExtras）。
- ctypes 用 `CDLL` + `CFUNCTYPE`（`__cdecl`），不能用 `WinDLL`/`WINFUNCTYPE`（32 位栈清理不匹配会崩）。
- 回调持有：CFUNCTYPE 包装对象存入 `_callbacks_holder` 防 GC——DLL 持原始函数指针，Python 侧必须保活。

## 10. 打包链路

### 10.1 wheel 内嵌 native

- 构建期 `scripts/sync_native_deps.py` 从 GitHub `releases/latest` API 下载最新 release + SHA256 校验（取自 `digest` 字段），原子替换到 `src/sparklehelper/`。
- `SPARKLEHELPER_SKIP_NATIVE_SYNC=1` 禁止联网，仅校验本地资源完整性（离线构建）。
- `Sparkle.framework.symlinks.json` 记录 framework 顶层符号链接布局，wheel 构建期生成，被 .gitignore 忽略、未入库。

### 10.2 PyInstaller hook

- **onedir 推荐**；**onefile .app 需 wrapper**：未经 wrapper（`SPARKLEHELPER_PYINSTALLER_WRAPPER`≠"1"）直接构建 onefile 会 `SystemExit` 中止。
- PyInstaller 6.21 已弃用 onefile + .app，且 `collect_files_from_framework_bundles` 在 hooks 之后运行。

### 10.3 Nuitka

- 必须经 `sparklehelper nuitka` wrapper（`--mode=app` = standalone + bundle，**推荐**），它负责参数转发、注入 `--user-plugin` 与 `--user-package-configuration-file`。
- **macOS onefile 不受支持**；plist 补丁仅在 standalone app mode 生效（非 standalone 返回 None + 告警）。

## 11. 开发命令

- 单元测试：`uv run pytest tests/`
- 静态检查：`uv run ruff check .`（CI 已启用，pyproject 顶层无 ruff，命令同 CI）
- wheel 构建：`uv build --wheel`（解析并下载上游最新 native 资源）
- 离线构建：`SPARKLEHELPER_SKIP_NATIVE_SYNC=1 uv build --wheel`
- 依赖管理：用 `uv`（`uv sync` / `uv lock`），不用 `pip`

## 12. 常见陷阱

- **submodule（`Sparkle/`、`winsparkle/`）仅作源码浏览参考，不参与构建**。
- **framework 版本随上游 latest 漂移**：当前 2.9.4；wheel 内容随上游最新 release 漂移，两次构建可能不同。
- **`SPARKLEHELPER_FRAMEWORK_PATH` 运行时优先级低于主 bundle**：若 `.app` 内已嵌入 framework（打包场景常态），env 实际不生效；只有 hook 打包期 env 才优先。
- **delegate 回调异常被吞**：异常仅记日志，需在日志中排查。
- **KVO `Subscription` 必须持有**：`Subscription.cancel()` 幂等、`__del__` 兜底注销，但对象被 GC 前不应丢失引用。
- 修改平台约束相关代码后跑测试时注意 `tests/conftest.py` 的 `darwin` marker 会在非 darwin 自动 skip。

## 13. 已知边界

- **onefile wrapper AST 修补硬编码 `exe` 变量名**：`_is_onefile_bundle_call` 要求 BUNDLE 首参变量名恰为 `exe`；若用户 spec 用其他名字（`app_exe` 等），wrapper 不修补而 hook 守卫放行 → 产出静默损坏的 .app。两个判断维度不一致。
- **构建期拉最新 release 不固定版本**：可复现性依赖上游 latest 不变化；SHA256 严格校验（防篡改）但版本不固定。
- **hook 守卫依赖 PyInstaller 内部 `CONF["spec"]`**：取不到 spec 时 fail-open（返回 False），PyInstaller 版本变化时"hook 会中止构建"的承诺可能失效。
- **Nuitka plugin 深度依赖 Nuitka 私有内部符号**：`MacOSApp.createPlistInfoFile`、`Standalone._normalizeMacOSFrameworkBundleLayout`、`options.Options.isStandaloneMode` 等全为内部 API，Nuitka 升级即可能碎。
- **delegate adapter 绑定 Sparkle 2.x selector**：若未来 Sparkle 改动 delegate 方法签名，回调会**静默不触发**（无运行时诊断）。

## 14. 测试体系要点

- 完全 mock 真实 ObjC/ctypes：用假 `objc`/`Foundation` 模块注入 `sys.modules`、`_MockSPUUpdater`/`_MockController` 假 ObjC 对象、mock DLL。
- 已知盲区：onefile spec AST 修补无测试；release 命令路径无测试；Windows 真实 DLL 与真实 Sparkle framework 从未加载；无 wheel 构建集成测试；无 PyInstaller/Nuitka 端到端构建测试。
- 本机若已同步 Sparkle.framework，`test_framework.py` 的 framework 存在性测试可跑（`uv run --locked pytest` → 162 passed）。
