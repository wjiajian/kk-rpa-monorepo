# 元素、页面与候选元素

## 两层资产边界

元素有两个位置，职责不同：

```text
顶层 elements/                         已真实验证的源资产
  ↓ 生成时复制实际使用项及依赖闭包
apps/<app>/src/<package>/elements/     应用运行时冻结副本和应用候选项
```

应用运行时不得读取顶层 `elements/`，也不得通过 Python import 直接依赖它。包内副本和候选项都由 `catalog.lock.json` 固定目标路径、状态、依赖和内容哈希。

`packages/rpa-platforms/` 仅兼容保留，不再作为元素源库。

## 顶层目录与元数据

```text
elements/<platform>/<product>/<page>/<component>.toml
```

一个 TOML 文件定义一个稳定元素，状态必须是 `verified`。示意：

```toml
schema_version = 1
kind = "element"
id = "example.web.login.account"
version = "1.0.0"
name = "登录账号"
platform = "example"
product = "web"
status = "verified"
dependencies = []

[locator]
strategy = "css"
value = "#login_id"

[verification]
url_pattern = "https://example.invalid/login"
match_count = 1
visible = true
enabled = true
refresh_stable = true
evidence = "reviews/verification-batch-id"
```

顶层 ID 在元素和指令之间也必须全局唯一。依赖使用 `element:<id>` 或 `instruction:<id>`，未知依赖和循环会被拒绝。

## 运行时 ElementSpec

`rpa_core.browser.ElementSpec` 是不可变的运行对象：

```python
@dataclass(frozen=True, slots=True)
class ElementSpec:
    id: str
    name: str
    page: str
    component: str | None = None
    locator: Locator | None = None
```

它保存稳定身份、页面上下文和可选的已验证定位器，不保存实时 DOM、浏览器句柄、账号或店铺配置。候选流程可以暂时没有 locator；生产适配器调用 `require_locator()` 时会 fail-closed，Fake Browser 则按稳定 ID 测试完整业务编排。

每次动作重新查找元素，不长期缓存 DOM。

## 定位器优先级

优先使用：

1. 稳定且唯一的 `id`；
2. 业务稳定的 `data-*` 属性；
3. 稳定 `name`、角色或可访问名称；
4. 页面组件范围内、带稳定锚点的相对定位；
5. 稳定文本；
6. 经真实页面验证的 CSS 或 XPath。

避免绝对 XPath、深层 `nth-child`、随机 class、临时哈希属性、屏幕坐标和仅凭截图推断的定位器。语义或视觉定位可以作为有证据的兜底，不能替代匹配数量和结果验证。

## 逐步分析流程

真实候选验证必须有开发人员授权，并按一个需求步骤一个需求步骤执行：

1. 记录 URL、标题、标签页、iframe 和登录状态信号；
2. 只确定当前步骤的目标角色，不全量抓取无关 DOM；
3. 生成按稳定性排序的候选定位；
4. 使用稳定锚点缩小作用域；
5. 验证预期匹配数量、可见、可用/可点击和页面身份；
6. 对拟晋升元素刷新或重新进入页面复核；
7. 只执行当前原子动作；
8. 用 URL、标题、状态元素、筛选值或下载产物验证结果；
9. 保存脱敏 DOM 摘要、截图和运行证据；
10. 失败时停在当前步骤并更新 `UnresolvedElement`，不猜测后续页面。

公开页面观察只能生成候选事实，不能替代 DrissionPage 真实运行、Profile 登录态或刷新稳定性验证。

## 查找、等待和 iframe

- 元素操作前由 BrowserActions 适配器执行必要等待；
- 可点击动作至少验证目标可点击；
- 等待失败必须转换为稳定错误，不能把空对象传给业务步骤；
- iframe 层级属于页面身份和候选证据，业务应用不保存 frame 对象；
- 若当前 BrowserActions 契约确实不足，应先提交独立公共接口 diff 和 Fake 测试，不能让应用直接访问 DrissionPage。

## 页面对象与指令

页面对象组合元素并表达页面语义；Instruction 组合受控动作并独立验证结果；Program/Step 编排完整业务规则。

```text
元素：品牌下拉框、搜索按钮、导出按钮
页面语义：确认库存页面身份
指令：选择品牌并验证筛选值
应用步骤：按本地配置中的品牌导出库存文件
```

公共页面和指令不得包含真实品牌、店铺规则、日期范围或应用输出策略。

## 候选生命周期

```text
应用内 candidate 元素
→ 关联 UE-*、需求步骤和截图
→ Fake Browser 测试完整流程
→ 开发人员授权 verify-candidates
→ 验证唯一、可见、可点击和刷新稳定
→ Preview 端到端通过
→ 提出回灌顶层 elements/ 的独立 diff
→ 回归受影响应用
```

未验证项留在应用包内并在 lock 中标记 `application_candidate/candidate`。顶层库更新不会自动改变当前应用；当前应用如需升级，必须展示来源版本、哈希和文件 diff 后再确认替换。

这套流程参考成熟 RPA 产品的元素捕获、属性编辑、锚点、校验和修复思想，但不采用运行时静默修复或云端自动同步。
