# BrowserActions 契约

`BrowserActions` 是业务应用访问浏览器的唯一接口。它隐藏 DrissionPage 类型、统一等待和错误语义，并自动关联 `run_id`、`step_id`、账号和证据。

## 协议

```python
@runtime_checkable
class BrowserActions(Protocol):
    @property
    def current_url(self) -> str | None: ...

    def open(self, url: str, *, wait: str = "document") -> None: ...
    def exists(self, element: ElementSpec, *, timeout: float = 0.0) -> bool: ...
    def count(self, element: ElementSpec, *, timeout: float = 0.0) -> int: ...
    def click(self, element: ElementSpec) -> None: ...
    def input(self, element: ElementSpec, value: SecretLike) -> None: ...
    def text(self, element: ElementSpec) -> str: ...
    def texts(self, element: ElementSpec, *, timeout: float = 0.0) -> list[str]: ...
    def select(self, element: ElementSpec, value: SecretLike) -> None: ...
    def download(self, element: ElementSpec, *, filename: str | None = None) -> DownloadRef: ...
    def screenshot(self, *, name: str | None = None, full_page: bool = False) -> ArtifactRef: ...
```

### count() 和 texts() 为什么存在

V1 的接口只有 `exists()` 返回布尔、`text()` 返回单个字符串。**接口的贫乏直接导致了断言的贫乏** —— 所有 `verify()` 只能退化成 `bool(...)`，这是 S003/S004 恒真的技术原因，不只是态度问题。

- `count()` —— 数结果行、数选中项。断言"筛选后有结果"需要它
- `texts()` —— 读回一组元素的文本。断言"选中的品牌集合等于配置品牌"需要它

用 `element.selected_option_locator` 配合 `texts()` 回读真实选中集合，是 V2 里把"筛选生效"变成真断言的标准手法。

## 当前实现基线（2026-09-03，DrissionPage 4.1.1.4）

- **`ElementSpec`**：稳定元素 ID，允许 `locator` 为空以显式表达未捕获元素，支持可选 `frame_locator`、`option_locator`、`selected_option_locator`、`popup_locator`、`dismiss_locator`。适配器在每次动作前重新解析 iframe，不把 frame 对象暴露给应用。所有 locator 只描述通用节点，不包含运行时业务值。
- **`SecretValue`**：`str()` 和 `repr()` 都不泄露运行时值。
- **`DownloadRef` / `ArtifactRef`**：本地路径、文件大小和 SHA-256。
- **`FakeBrowserActions`**：不启动浏览器、不访问网络，按元素稳定 ID 验证完整业务编排。文本读取必须显式提供 fixture；动作记录只保留 `<redacted>`。反例通过构造不同的 Fake 状态表达。
- **`DrissionBrowserActions`**：接收运行时托管的 Chromium Tab。输入固定采用 `clear(by_js=True) → focus() → input(..., by_js=False)`；`select` 保持原生 `select.by_text()`；输入型自定义下拉配置 `option_locator` 时，在同一 frame 内等待并过滤显示、启用、可点击且文本完全一致的选项，必须唯一命中才点击。精确多选组件按真实 checkbox 状态清除非目标项、补齐唯一目标项，点击经验证且不受浮层遮挡的关闭目标，并等待浮层不可见；任何一步不能证明成功都失败关闭。
- **`text()`**：普通元素返回可见文本，`input` 返回当前 `value`；读取失败转换为公共 `ElementActionError`。
- **`count()` / `texts()`**：在解析后的 frame 作用域内多元素查找。元素不存在时 `count()` 返回 `0`、`texts()` 返回 `[]`，不抛错 —— 这让"结果为空"能被断言表达，而不是变成异常。
- 下载只允许进入 `run_dir/downloads/`，截图只允许进入 `run_dir/evidence/`，返回前检查普通文件、大小和 SHA-256；路径逃逸或符号链接目录失败关闭。
- **`BrowserManager`**：为每个 Profile 持有 OS 排他锁，通过机器级租约目录动态选择未监听端口，创建 `ChromiumOptions` 和 `Chromium`，把 Tab 绑定为当前运行的 `DrissionBrowserActions`。
- **`BrowserLifecyclePolicy`**：`keep_open` / `reuse_until_idle` / `terminate_on_finish`。保留会话时 Profile 锁与端口租约持续由 Manager 持有，`shutdown()` 才统一释放。

生产适配器必须调用 `ElementSpec.require_locator()`；Fake 可以在定位器尚未捕获时使用稳定 ID，从而验证完整流程而不伪造 CSS/XPath。应用通过 `ExecutionContext.browser` 获取该能力。

## 每次动作的统一流程

```text
记录 action.started
→ 按 ElementSpec 解析实际 tab/frame context
→ 等待目标状态
→ 执行动作
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

- `DownloadRef`：脱敏后的本地产物引用、状态、文件哈希和验证结果
- `ArtifactRef`：指向当前运行目录中的证据，不包含本机绝对路径的可提交副本
- `SecretLike`：日志层只能记录字段名或掩码，不能调用普通 `repr()` 输出真实值
- 底层 DrissionPage 的 `ChromiumTab`、`ChromiumElement`、`DownloadMission` 和异常一律不得逃逸到应用层

## 错误转换

适配器至少应将底层失败映射为：

`AuthenticationError`、`HumanVerificationRequired`、`ElementLookupError`、`ElementActionError`、`NavigationError`、`DownloadError`、`InfrastructureError`。

业务代码只能基于稳定错误码和 `retryable` 判断恢复策略，不依赖 DrissionPage 的异常文本。

## 明确禁止

- 应用持有 `browser`、`tab` 或元素的底层对象
- 跨步骤缓存 DOM 对象
- 应用硬编码调试端口、Profile 路径或下载目录
- **仅因为点击方法没有抛错就认定步骤成功** —— `verify()` 必须回读页面状态
- 在日志中记录输入框的真实账号、密码或 Token
- 在业务步骤中调用 `quit()`、`close_tabs()` 等生命周期操作

## 尚未实现

`find` / `find_all` 返回受控 `ElementRef`、显式 tab 上下文管理器、显式 frame 上下文管理器、统一动作事件流。这些是目标协议，不是已交付接口。需要时先提交独立的公共接口 diff 和 Fake 测试，不能让应用绕过契约直接访问 DrissionPage。
