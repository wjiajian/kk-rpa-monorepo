# 元素交互与等待

官方来源：

- [元素交互](https://drissionpage.cn/browser_control/ele_operation)
- [获取元素信息](https://drissionpage.cn/browser_control/get_ele_info)
- [等待](https://drissionpage.cn/browser_control/waiting)

## 点击

常用点击能力：

| API | 行为 |
| --- | --- |
| `element.click(...)` / `click.left(...)` | 左键点击 |
| `click.right()` | 右键点击 |
| `click.middle(get_tab=True)` | 中键点击，可返回新标签页 |
| `click.multi(times=2)` | 多次点击 |
| `click.at(...)` | 按元素内偏移位置点击 |
| `click.for_new_tab(...)` | 点击并等待新标签页 |
| `click.to_download(...)` | 点击并返回下载任务 |
| `click.to_upload(...)` | 点击并处理文件选择框 |

`click()` 支持模拟点击和 JavaScript 点击。官方 `4.1.1.4` 页面中，参数表把 `by_js` 默认值列为 `False`，随后说明段落又描述默认值为 `None` 时自动降级；两处存在不一致。项目适配器必须在锁定版本契约测试后显式传入策略，不能依赖这个默认值。

项目默认使用真实可交互点击；只有经页面适配器明确允许，才能回退 JavaScript 点击。高风险提交、删除、支付和权限操作禁止自动使用 JS 绕过可见性或遮挡。

## 输入和清空

```python
element.clear(by_js=False)
element.input(vals, clear=False, by_js=False)
element.focus()
```

- `clear()` 的模拟方式使用全选并删除，JS 方式直接修改 `value`；
- `input()` 接收文本、按键组合或上传控件的文件路径；
- `clear=True` 可在输入前清空；
- `by_js=True` 时不能输入按键组合；
- 普通 Python 值会被转换为字符串；
- 文本末尾可包含换行以触发回车。

账号、密码和 Token 通过 `SecretLike` 传入，包装器不得记录真实值。

## 读取元素信息

| 属性或方法 | 返回 |
| --- | --- |
| `tag` | 标签名 |
| `html` | outerHTML |
| `inner_html` | innerHTML |
| `text` | 格式化后的文本 |
| `raw_text` | 原始文本 |
| `texts(text_node_only=False)` | 直接子节点文本列表 |
| `attrs` | 全部属性字典 |
| `attr(name)` | 指定 attribute，无属性时返回 `None` |
| `property(name)` | DOM property |
| `value` | 元素 value |
| `link` | href 或 src |
| `shadow_root` | ShadowRoot 或 `None` |
| `rect.size` | 元素宽高 |
| `rect.location` | 页面内左上角坐标 |
| `states.is_alive` | 元素是否仍有效 |
| `states.is_displayed` | 是否显示 |
| `states.is_enabled` | 是否可用 |
| `states.is_clickable` | 是否可点击 |

HTML、全部属性和页面业务文本可能包含敏感信息，默认不写入结构化日志。

## 页面级等待

| API | 用途 |
| --- | --- |
| `wait.load_start(...)` | 等待页面开始加载 |
| `wait.doc_loaded(...)` | 等待主 document 完成 |
| `wait.eles_loaded(locator, timeout=None, any_one=False, raise_err=None)` | 等待元素进入 DOM |
| `wait.ele_displayed(...)` | 等待元素显示 |
| `wait.ele_hidden(...)` | 等待元素隐藏 |
| `wait.ele_deleted(...)` | 等待元素从 DOM 删除 |
| `wait.title_change(...)` | 等待标题变化 |
| `wait.url_change(...)` | 等待 URL 变化 |
| `wait.alert_closed(...)` | 等待弹窗关闭 |

`get()` 已内置主文档加载等待；JavaScript 后续请求必须等待业务信号。

## 元素级等待

| API | 用途 |
| --- | --- |
| `wait.displayed()` | 等待显示 |
| `wait.hidden()` | 等待隐藏 |
| `wait.deleted()` | 等待删除 |
| `wait.has_rect()` | 等待元素具有布局矩形 |
| `wait.covered()` / `not_covered()` | 等待被遮挡或不被遮挡 |
| `wait.enabled()` / `disabled()` | 等待启用或禁用 |
| `wait.stop_moving()` | 等待停止移动 |
| `wait.clickable(wait_moved=True, timeout=None, raise_err=None)` | 等待可点击 |
| `wait.disabled_or_deleted()` | 等待禁用或删除 |

所有等待都应设置有界超时。框架根据 `StepSpec` 把返回 `False` 或底层异常转换为稳定错误码，并决定是否重试；禁止用无边界 `sleep()` 代替业务条件。
