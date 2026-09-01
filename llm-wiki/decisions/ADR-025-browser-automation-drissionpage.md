# ADR-025：浏览器自动化选用 DrissionPage

- 状态：已接受
- 决策日期：2026-08-31
- 适用范围：`kk-rpa-monorepo` 的浏览器 RPA 公共运行层

## 背景

平台需要控制 Chromium 浏览器，支持页面访问、元素操作、iframe、新标签页、下载、截图、独立 Profile 和调试端口，并在同一运行机器上隔离多个店铺账号。

业务应用还必须保持可测试和可审核，不能直接依赖浏览器驱动的对象、异常和生命周期。

## 决策

浏览器自动化底层选用 [DrissionPage](https://drissionpage.cn/browser_control/intro)。

采用方式：

```text
apps
→ ExecutionContext.browser
→ BrowserActions
→ DrissionPageBrowserAdapter
→ DrissionPage
```

业务应用不得直接导入或调用 DrissionPage。底层依赖集中在公共浏览器适配层，通过框架协议、错误类型、日志、证据和授权门禁向上提供能力。

## 结果

正面影响：

- 使用统一的 Chromium 浏览器控制方案；
- 可利用官方提供的浏览器连接、元素、等待、iframe、标签页、下载和截图能力；
- 可以通过 `ChromiumOptions` 配置独立端口和 Profile；
- 公共包装器能够统一处理等待、重试、脱敏、证据和异常。

代价和风险：

- 需要维护稳定的 `BrowserActions` 适配层；
- DrissionPage 升级必须执行公共契约和受影响应用回归；
- Windows 物理机上的进程保活、端口租约和 Profile 锁仍需单独实现和验证；
- 各平台页面变化仍需要真实授权测试，不能依靠框架选择消除元素维护成本。

## 强制边界

- `apps/` 禁止导入 `DrissionPage`；
- 应用不能持有或持久化 Chromium、Tab、Element、Frame 或 DownloadMission 对象；
- 浏览器路径、调试端口、Profile 和下载目录由运行时提供；
- 真实浏览器操作必须获得开发人员授权；
- 验证码、滑块和短信只检测并转人工，不绕过；
- 浏览器读操作授权、Preview 写入拦截和 Live 单次授权分别校验。

## 官方依据

见 [官方资料索引](../sources.md)。
