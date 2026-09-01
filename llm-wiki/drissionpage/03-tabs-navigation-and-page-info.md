# 标签页、访问网页与页面信息

官方来源：

- [标签页管理](https://drissionpage.cn/browser_control/tabs)
- [浏览器对象](https://drissionpage.cn/browser_control/browser_object)
- [访问网页](https://drissionpage.cn/browser_control/visit)
- [页面交互](https://drissionpage.cn/browser_control/page_operation)
- [获取网页信息](https://drissionpage.cn/browser_control/get_page_info)

## 获取与创建标签页

| API | 用途 |
| --- | --- |
| `browser.latest_tab` | 获取最后激活的标签页对象 |
| `browser.get_tab(...)` | 按序号、ID、标题、URL 或类型获取一个标签页 |
| `browser.get_tabs(...)` | 按条件获取多个标签页 |
| `browser.new_tab(url=None, new_window=False, background=False, new_context=False)` | 新建标签页或窗口 |
| `element.click.for_new_tab()` | 点击并返回新出现的标签页对象 |
| `browser.wait.new_tab(...)` | 等待新标签页，成功返回标签页 ID |

`get_tab()` 传入 ID 或序号时，其它过滤条件无效。标题、URL 和标签页类型过滤条件是“与”关系。

项目通过 `ctx.browser.tab(...)` 管理标签页上下文，业务代码不得保存 Tab ID 或关闭其它应用的标签页。

## 访问网页

主要方法：

```python
tab.get(
    url,
    show_errmsg=False,
    retry=None,
    interval=None,
    timeout=None,
) -> bool
```

其中：

- `retry` 为 `None` 时使用页面配置，官方默认重试次数为 3；
- `interval` 为 `None` 时使用页面配置，官方默认间隔为 2 秒；
- `timeout` 为 `None` 时使用页面加载超时；
- 返回布尔值表示访问是否成功；
- `get()` 已包含页面开始加载和主文档完成的等待，不应机械叠加等待。

加载模式：

| 模式 | 行为 |
| --- | --- |
| `normal` | 等待主文档和资源按常规加载，默认模式 |
| `eager` | DOM 完成后停止继续加载资源 |
| `none` | 连接后继续执行，由调用方决定何时停止加载 |

官方文档特别说明，“主文档加载完成”不代表后续 JavaScript 数据或重定向完成。业务成功条件应等待目标元素、URL、数据包或业务状态，而不是只检查 document ready。

## 页面跳转和控制

| API | 行为 |
| --- | --- |
| `tab.back(steps=1)` | 后退指定步数 |
| `tab.forward(steps=1)` | 前进指定步数 |
| `tab.refresh(ignore_cache=False)` | 刷新页面 |
| `tab.stop_loading()` | 强制停止加载 |
| `tab.set.blocked_urls(urls)` | 阻止匹配 URL 的资源请求 |
| `tab.close()` | 关闭当前标签页 |
| `tab.disconnect()` / `reconnect()` | 断开或重新连接控制通道 |

`run_js()`、`run_cdp()` 等底层能力只允许在经过审核的公共适配器中使用，不能作为应用绕过 `BrowserActions` 的通道。

## 页面信息

| 属性或方法 | 返回行为 |
| --- | --- |
| `tab.url` | 当前 URL |
| `tab.title` | 页面标题 |
| `tab.html` | 当前页面 HTML，不包含 iframe 内部文档 |
| `tab.json` | 将 JSON 页面解析为字典 |
| `tab.user_agent` | 当前页面 User-Agent |
| `tab.tab_id` | 标签页 ID |
| `tab.states.is_loading` | 是否正在加载 |
| `tab.states.is_alive` | 标签页是否仍可用 |
| `tab.states.ready_state` | `connecting`、`loading`、`interactive` 或 `complete` |
| `tab.states.has_alert` | 是否存在弹窗 |
| `tab.timeout` | 基础默认超时，官方默认 10 秒 |
| `tab.timeouts` | `base`、`page_load`、`script` 三类超时 |
| `tab.retry_times` | 网络访问重试次数 |
| `tab.retry_interval` | 网络重试间隔 |
| `tab.load_mode` | 当前加载模式 |

页面 URL、标题和 ready state 可以进入脱敏运行证据；HTML、Cookie 和页面业务数据默认不得完整写入日志。
