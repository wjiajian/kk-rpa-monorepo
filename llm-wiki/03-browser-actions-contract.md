# BrowserActions 契约

`BrowserActions` 是业务应用访问浏览器的唯一接口。它隐藏 DrissionPage 类型、统一等待和错误语义，并自动关联 `run_id`、`step_id`、账号和证据。

## 当前实现基线

截至 2026-09-03，`rpa-core 0.7.0` 已落地无副作用契约和 DrissionPage 4.1.1.4 动作适配器：

- `BrowserActions`：`open`、`exists`、`click`、`input`、`text`、`select`、`download`、`screenshot`；
- `ElementSpec`：稳定元素 ID，允许目标 locator 为空以显式表达未解析元素，并支持可选 `frame_locator`、`option_locator`、`selected_option_locator`、`popup_locator` 与 `dismiss_locator`；适配器在每次动作前重新解析 iframe，不把 frame 对象暴露给应用；所有 locator 只描述通用节点，不包含运行时业务值；
- `SecretValue`：`str` 和 `repr` 都不泄露运行时值；
- `DownloadRef` / `ArtifactRef`：本地路径、文件大小和 SHA-256；
- `FakeBrowserActions`：不启动浏览器、不访问网络，按元素稳定 ID 验证完整业务编排；文本读取必须显式提供 fixture，动作记录只保留 `<redacted>`。
- `DrissionBrowserActions`：接收运行时托管的 Chromium Tab，实现上述动作；输入固定采用 `clear(by_js=True) → focus() → input(..., by_js=False)`；`select` 保持原生 `select.by_text()`；输入型自定义下拉配置 `option_locator` 时，在同一 frame 内等待并过滤显示、启用、可点击且文本完全一致的选项，必须唯一命中才点击，未配置时保留 Enter 兼容行为。精确多选组件还会按真实 checkbox 状态清除非目标项、补齐唯一目标项，点击经过验证且不受浮层遮挡的关闭目标，并等待浮层不可见；任何一步不能证明成功都失败关闭。
- `text()`：普通元素返回可见文本，`input` 返回当前 `value`；读取失败转换为公共 `ElementActionError`。
- 下载只允许进入当前 `run_dir/downloads/`，截图只允许进入 `run_dir/evidence/`，返回前检查普通文件、大小和 SHA-256；路径逃逸或符号链接目录会失败关闭。
- 适配器把底层导航、查找、动作和下载失败转换为公共稳定异常，不把 Tab、元素或 `DownloadMission` 暴露给应用。
- `BrowserManager`：为每个 Profile 持有 OS 排他锁，通过机器级租约目录动态选择未监听端口，创建 `ChromiumOptions` 和 `Chromium`，并把 Tab 绑定为当前运行的 `DrissionBrowserActions`。
- `BrowserLifecyclePolicy`：实现 `keep_open`、`reuse_until_idle` 和 `terminate_on_finish`；保留会话时 Profile 锁与端口租约持续由 Manager 持有，`shutdown()` 才统一释放。
- `AuthorizedBrowserActions`：每次边界都校验 active Authorization Session、Step、Action、Element，并在调用前后校验 top-level Origin；固定内部工具流程中的 iframe 由冻结的 `ElementSpec.frame_locator` 约束，不再逐个执行 Origin allowlist。DrissionPage adapter 仍保留可选的 `ContextGuardedBrowserActions` 能力，供更严格的集成显式使用。

生产适配器必须调用 `ElementSpec.require_locator()`；Fake 可以在 locator 尚未补抓时使用稳定 ID，从而验证完整流程而不伪造 CSS/XPath。应用通过 `ExecutionContext.browser` 获取该能力。

当前已有一个应用完成 Fake 测试；其 17 个元素和 7 条指令已显式晋升顶层公共库并重新锁定到应用快照。0.3.0 已在授权运行 `preview-20260903T062356Z-df357a62` 完成 S001–S005 和本地下载，Developer Review 已通过，当前为 `ready_for_push`。指令目录的内容哈希排除 Python 自动生成的 `__pycache__`、`.pyc` 和 `.pyo`，其他额外文件仍会触发完整性失败。业务验收状态以应用 Generation Report 和 Developer Review Record 为准。公共 `AuthorizationScope` 精确绑定 Application/Program Version、Requirement/Catalog Digest、Operation、Mode、Run、Account、Profile fingerprint、Allowed Origins、Steps、Browser Actions、Elements、Candidate Assets 与 External Writes；Resume 还绑定 Checkpoint Digest 和 recovery Step。协议扩展仍缺少 `find`、`find_all`、受控标签页、显式 frame 上下文管理器和统一动作事件；以下仍是目标协议，而不是已经全部交付的接口。

## 目标协议

```python
class BrowserActions(Protocol):
    def open(self, url: str, *, wait: str = "document") -> None: ...
    def find(self, element: ElementSpec, *, root=None) -> ElementRef: ...
    def find_all(self, element: ElementSpec, *, root=None) -> list[ElementRef]: ...
    def exists(self, element: ElementSpec, *, timeout=0, root=None) -> bool: ...
    def click(self, element: ElementSpec, *, root=None) -> None: ...
    def input(self, element: ElementSpec, value: SecretLike, *, root=None) -> None: ...
    def text(self, element: ElementSpec, *, root=None) -> str: ...
    def select(self, element: ElementSpec, value: str, *, root=None) -> None: ...
    def download(self, element: ElementSpec, *, filename=None) -> DownloadRef: ...
    def screenshot(self, *, name=None, full_page=False) -> ArtifactRef: ...
    def tab(self, *, opened_by=None, close=False) -> ContextManager: ...
    def frame(self, element: ElementSpec) -> ContextManager: ...
```

具体签名在实现阶段可以细化，但不得把 DrissionPage 的 `ChromiumTab`、`ChromiumElement`、下载任务或异常直接暴露给应用层。

## 每次动作的统一流程

```text
校验当前授权和运行状态
→ 记录 action.started
→ 按 ElementSpec 解析实际 tab/frame context
→ 等待目标状态
→ 执行动作
→ 复核 top-level Origin 和动作后条件
→ 记录耗时和脱敏结果
→ 返回框架引用
```

失败时：

```text
捕获底层异常
→ 转换为稳定 RpaError
→ 保存 URL、标题、步骤、元素和最近动作
→ 按策略保存截图
→ 标记是否可重试
→ 记录 action.failed
```

## 返回值边界

- `ElementRef`：仅在当前动作或受控上下文中有效，不可持久化到检查点。
- `DownloadRef`：包含脱敏后的本地产物引用、状态、文件哈希和验证结果。
- `ArtifactRef`：指向当前运行目录中的证据，不包含本机绝对路径的可提交副本。
- `SecretLike`：日志层只能记录字段名或掩码，不能调用普通 `repr()` 输出真实值。

## 错误转换

适配器至少应将底层失败映射为：

- `AuthenticationError`；
- `HumanVerificationRequired`；
- `ElementLookupError`；
- `ElementActionError`；
- `NavigationError`；
- `DownloadError`；
- `InfrastructureError`。

业务代码只能基于稳定错误码和 `retryable` 判断恢复策略，不依赖 DrissionPage 的异常文本。

## 明确禁止

- 应用持有 `browser`、`tab` 或元素的底层对象；
- 跨步骤缓存 DOM 对象；
- 应用硬编码调试端口、Profile 路径或下载目录；
- 仅因为点击方法没有抛错就认定步骤成功；
- 在日志中记录输入框的真实账号、密码或 Token；
- 在业务步骤中调用 `quit()`、`close_tabs()` 等生命周期操作。
