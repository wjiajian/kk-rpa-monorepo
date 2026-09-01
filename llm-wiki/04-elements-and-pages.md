# 元素、页面与候选元素

## 元素模型

公共元素按以下层次组织：

```text
平台
└── 站点或产品
    └── 页面
        └── 页面组件
```

元素描述使用不可变的 `ElementSpec`。它保存业务名称、定位信息、页面上下文和必要的等待语义，不保存实时 DOM 对象、账号或店铺配置。

示意：

```python
@dataclass(frozen=True, slots=True)
class ElementSpec:
    id: str
    name: str
    locator: str
    page: str
    component: str | None = None
```

正式字段在实现 Schema 时确定。`id` 一旦被需求步骤引用就应保持稳定。

## 定位器选择顺序

优先使用：

1. 稳定且唯一的 `id`；
2. 业务稳定的 `data-*` 属性；
3. 稳定的 `name`、角色或语义属性；
4. 页面组件范围内的相对定位；
5. 稳定文本；
6. 经真实页面验证的 CSS 或 XPath。

避免绝对 XPath、深层 `nth-child`、随机 class、临时哈希属性和仅凭截图猜测的定位器。

DrissionPage 官方文档展示了 `#kw`、`text=文档`、`tag:h3` 等定位方式，但项目中必须由 `ElementSpec` 承载，应用不得散落字符串定位器。

## 查找和等待

- `ele()` 查找一个匹配元素，`eles()` 查找多个元素；
- 元素操作前由包装器执行必要等待；
- 可点击动作至少验证目标可点击，底层可映射到 `element.wait.clickable(...)`；
- 等待失败必须转换为稳定错误，不得把空对象继续传给业务步骤；
- 每次动作重新查找目标，避免页面更新导致旧元素失效。

## iframe

官方文档说明，同域 iframe 支持跨层查找，也可以先定位 iframe 后在其中查找；跨域场景应使用明确的 iframe 上下文。

项目统一通过：

```python
with ctx.browser.frame(LoginPage.LOGIN_FRAME):
    ctx.browser.input(LoginPage.USERNAME, username)
```

业务步骤不判断底层 iframe 类型，也不保存 frame 对象。

## 页面对象

页面对象可以组合多个元素，提供平台语义，例如“查询订单”“切换日期”“验证登录状态”。它不能包含具体店铺规则或一个应用专属的业务流程。

```text
元素：搜索框、搜索按钮、订单行
页面动作：search_orders(...)
应用步骤：查询昨日需要导出的全部订单
```

## 候选元素生命周期

```text
应用内 candidate_elements/
→ PendingConfirmation 或 UnresolvedElement 关联需求步骤和截图
→ 开发人员授权真实浏览器补抓
→ 验证唯一性、显示、可点击、刷新稳定性
→ 完整流程验证
→ 迁移到 packages/rpa-platforms/
→ 应用改为引用公共元素
→ 回归所有受影响应用
```

没有真实 DOM 证据时，元素保持 `UnresolvedElement`，但对应业务步骤仍要保留在完整流程中。
