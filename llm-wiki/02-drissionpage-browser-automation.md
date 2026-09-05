# DrissionPage 浏览器自动化方案

## 已确认选型

浏览器自动化底层选用 [DrissionPage](https://drissionpage.cn/browser_control/intro)。本项目采用其 Chromium 浏览器控制能力，业务应用不直接接触 DrissionPage 对象。

正式决策见 [ADR-025](decisions/ADR-025-browser-automation-drissionpage.md)。

## 具体文档

本地 Wiki 已按你提供的官方入口页整理 DrissionPage `4.1.1.4` 浏览器控制文档，包含对象模型、方法、参数、返回行为和项目采用约束：

- [DrissionPage 具体文档首页](drissionpage/README.md)
- [浏览器控制概述](drissionpage/01-browser-control-intro.md)
- [连接浏览器与启动配置](drissionpage/02-connect-and-options.md)
- [标签页、访问网页与页面信息](drissionpage/03-tabs-navigation-and-page-info.md)
- [定位语法与元素查找](drissionpage/04-locators-and-element-lookup.md)
- [元素交互与等待](drissionpage/05-element-interactions-and-waits.md)
- [iframe、动作链与模式切换](drissionpage/06-iframe-actions-and-modes.md)
- [下载、截图、上传与监听](drissionpage/07-artifacts-and-observability.md)

## 依赖方向

允许：

```text
业务步骤
→ ExecutionContext.browser
→ BrowserActions
→ DrissionPageBrowserAdapter
→ DrissionPage
```

禁止：

```python
# apps/ 中禁止
from DrissionPage import Chromium

page.ele("#submit").click()
```

DrissionPage 只能出现在：

- `rpa_core/drission_browser.py`；
- `rpa_core/browser_manager.py`。

底层测试通过 Fake Tab 验证这些适配器。

## 已核验的官方能力

截至 2026-08-31，官方文档确认：

- `ChromiumOptions().set_browser_path(...)` 可指定浏览器程序；
- `set_local_port(...)` 可配置本地调试端口；
- `set_user_data_path(...)` 可配置独立用户数据目录；
- `Chromium(options)` 可启动或连接浏览器；
- `browser.latest_tab` 可取得当前标签页；
- `tab.ele(...)` 和 `tab.eles(...)` 可查找单个或多个元素；
- `element.wait.clickable(...)` 可等待元素达到可点击状态；
- `click.to_download(...)` 返回下载任务，任务可等待完成；
- `browser.wait.downloads_done(...)` 或标签页对应等待可等待下载结束；
- `browser.wait.new_tab(...)` 可等待新标签页。

这些是适配器实现时可依赖的底层能力，但对业务应用暴露的名称和返回值必须使用本项目自己的契约。

## 适配层初始化示意

以下代码只允许存在于公共适配层：

```python
from DrissionPage import Chromium, ChromiumOptions

options = (
    ChromiumOptions()
    .set_browser_path(browser_path)
    .set_local_port(debug_port)
    .set_user_data_path(profile_path)
)
browser = Chromium(options)
tab = browser.latest_tab
```

其中 `browser_path`、`debug_port` 和 `profile_path` 必须由运行时配置、端口池和 Profile 管理器提供，不能由业务应用硬编码。

## 项目采用约束

- 每次动作重新解析 `ElementSpec`，不长期缓存页面刷新后可能失效的 DOM 对象。
- 点击前由适配器完成定位、等待和状态检查；底层错误转换为框架错误，步骤日志由 Runner 记录。
- 下载使用配置的 `download_dir`，确认目标报表、传输完成和非空文件；截图独立保存在每次运行目录。
- 标签页、iframe 和下载任务由包装器转换为框架引用，不能泄漏底层对象。
- 业务应用不得调用浏览器退出方法；浏览器生命周期由 `BrowserManager` 决定。
- 人机验证只检测、留证并报错，处理后另启一次运行。

## 实现时仍需现场验证

- 统一运行机器上的 Chrome/Chromium 路径与兼容版本；
- Windows 下进程启动、连接、保活和退出行为；
- 同机多 Profile 并发时的端口与锁策略；
- 各业务平台 iframe、新标签页和下载行为；
- DrissionPage 具体版本锁定与升级回归范围。
