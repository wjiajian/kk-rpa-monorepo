# 浏览器控制概述

官方来源：[浏览器控制概述](https://drissionpage.cn/browser_control/intro)。官方页面标注版本：DrissionPage `4.1.1.4`。

## 官方基本逻辑

浏览器控制的基本流程是：

```text
创建 Chromium 浏览器对象
→ 获取 Tab 对象
→ Tab 访问网址
→ Tab 获取元素对象
→ 元素执行输入、点击或读取
```

官方入口页给出的最小示例：

```python
from DrissionPage import Chromium

browser = Chromium()
tab = browser.latest_tab
tab.get("https://www.baidu.com")

search_input = tab.ele("#kw")
search_input.input("DrissionPage")
tab("#su").click()

for heading in tab.eles("tag:h3"):
    print(heading.text)
```

这段代码用于解释 DrissionPage 对象关系，只允许在公共适配层或底层测试中出现。

## 三类核心对象

### Chromium

`Chromium` 管理浏览器整体，包括：

- 启动或接管浏览器；
- 获取、新建、激活和关闭标签页；
- 配置整体运行参数；
- 获取浏览器状态；
- 管理浏览器级下载和等待；
- 结束浏览器进程。

本项目中，对象的创建与退出只由 `BrowserManager` 管理。

### Tab

`ChromiumTab` 或 `MixTab` 对应实际标签页。大部分页面动作都由 Tab 完成：

- `get(url)` 访问页面；
- `ele(locator)` 获取一个元素；
- `eles(locator)` 获取多个元素；
- 读取 `url`、`title` 和 `html`；
- 页面跳转、等待、截图、下载和网络监听。

多个 Tab 对象可以并行操作，不要求把标签页切换到前台。

### ChromiumElement

元素对象负责：

- 点击；
- 输入和清空；
- 读取文本、属性和位置；
- 在元素内部继续查找；
- 按 DOM 相对关系查找其它元素；
- 等待显示、可点击或停止移动；
- 截图、上传或触发下载。

元素对象与当前页面 DOM 绑定。项目包装器每次动作都重新定位，不跨步骤缓存对象。

## 内部查找与相对查找

页面和元素均支持 `ele()`/`eles()`：

```python
nav = tab.ele("text=文档")
link = nav.ele("tag:a")
```

元素还可以相对定位：

```python
current = tab.ele("text=文档")
next_element = current.next()
```

相对查找适用于稳定的组件内部结构；不能从一个 iframe 的文档跨越到另一个文档。

## 本项目对应关系

| DrissionPage 对象 | 项目对外类型 | 持有者 |
| --- | --- | --- |
| `Chromium` | 不向应用暴露 | `BrowserManager` |
| `ChromiumTab` / `MixTab` | `BrowserSession` 或受控 Tab 上下文 | 浏览器适配器 |
| `ChromiumElement` | 短生命周期 `ElementRef` | 单次 BrowserActions 动作 |
| `ChromiumFrame` | `frame(...)` 上下文 | 浏览器适配器 |
| `DownloadMission` | `DownloadRef` | 下载包装器 |

业务步骤应写成：

```python
ctx.browser.input(LoginPage.USERNAME, username)
ctx.browser.click(LoginPage.SUBMIT)
```

而不是直接使用 `tab.ele()` 或 `element.click()`。
