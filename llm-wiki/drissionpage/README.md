# DrissionPage 4.1.1.4 具体文档

本专区根据用户提供的 [DrissionPage 浏览器控制入口](https://drissionpage.cn/browser_control/intro) 及其官方专题页整理。它面向本项目的开发者和 LLM，提供可检索的方法、参数、返回行为和采用边界。

- 官方页面标注版本：`4.1.1.4`
- 抓取与核验日期：2026-08-31
- 文档性质：官方内容的项目化整理，不是完整镜像
- API 事实优先级：锁定版本官方文档与实际契约测试

## 文档导航

1. [浏览器控制概述](01-browser-control-intro.md)
2. [连接浏览器与启动配置](02-connect-and-options.md)
3. [标签页、访问网页与页面信息](03-tabs-navigation-and-page-info.md)
4. [定位语法与元素查找](04-locators-and-element-lookup.md)
5. [元素交互与等待](05-element-interactions-and-waits.md)
6. [iframe、动作链与模式切换](06-iframe-actions-and-modes.md)
7. [下载、截图、上传与监听](07-artifacts-and-observability.md)

## 官方章节覆盖

| 官方章节 | 本地页面 |
| --- | --- |
| 概述、连接浏览器、浏览器启动设置 | 01、02 |
| 浏览器对象、标签页管理、访问网页、页面交互、获取网页信息 | 03 |
| 查找元素、定位语法、相对定位、行为模式、语法速查表 | 04 |
| 元素交互、获取元素信息、等待 | 05 |
| iframe、动作链、模式切换 | 06 |
| 下载、截图、上传、监听网络、控制台信息 | 07 |

## 使用约定

这些页面同时包含两类信息：

- “官方行为”：DrissionPage `4.1.1.4` 文档给出的接口和语义；
- “项目规则”：`kk-rpa-monorepo` 对这些能力的封装、授权和安全限制。

不要把官方示例直接复制到 `apps/`。业务应用只能调用 `ExecutionContext.browser`；只有公共适配层可以导入 DrissionPage。

## 版本更新方式

升级 DrissionPage 时：

1. 记录新旧版本；
2. 重新抓取本专区列出的官方页面；
3. 对比方法签名、默认值和返回行为；
4. 更新 `DrissionPageBrowserAdapter`；
5. 运行浏览器适配器契约测试和受影响应用回归；
6. 更新核验日期，不覆盖历史测试证据。
