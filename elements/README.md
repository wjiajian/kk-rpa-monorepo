# 顶层元素源库

`elements/` 只保存经过授权的真实页面验证、可跨应用复用的稳定元素。应用运行时不得读取本目录；生成应用时由 Codex 复制实际使用的元素及依赖到应用包，并由 `catalog.lock.json` 固定内容哈希。

## 目录与身份

```text
elements/<platform>/<product>/<page>/<component>.toml
```

一个 TOML 文件只定义一个稳定元素。`id` 一经进入顶层库不得复用或静默改名。

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

`dependencies` 使用 `element:<id>` 或 `instruction:<id>`。元素锚点可以依赖另一个元素，但必须避免循环依赖。

## 自主分析与验证顺序

Codex 可以在开发人员授权的浏览器范围内逐步分析页面，但不能只凭截图生成定位器：

1. 打开已授权 URL，确认页面标题、URL、标签页和 iframe；
2. 按需求步骤识别本次要操作的目标，不全量抓取无关 DOM；
3. 优先生成稳定 ID、`name`、`data-*`、可访问名称或稳定文本定位；
4. 动态 class、绝对 XPath、序号和屏幕坐标只能作为低优先级候选；
5. 需要时用稳定锚点缩小范围，语义或视觉定位只能作为有证据的兜底；
6. 校验匹配数量、可见、可用/可点击、刷新稳定性和页面身份；
7. 保存脱敏 DOM 摘要、截图或运行证据引用，不保存账号、Cookie 或业务数据；
8. 未通过验证的元素留在应用快照中并标记 `candidate`，不得写入本目录。

这套流程借鉴了成熟 RPA 产品的“捕获、编辑、锚点、校验、修复”思路，但本仓库使用可审计文件和显式升级，不做运行时自动修复或云端静默同步。

## 禁止内容

- 实时 DOM 对象、浏览器句柄或 Profile；
- 真实店铺、账号、手机号、Token、Cookie 和业务数据；
- 未验证的 XPath/CSS；
- 只在单一分辨率可用的坐标或图像定位；
- 应用专属品牌、日期、输出路径或写入规则。
