# 官方资料索引

核验日期：2026-09-01。DrissionPage 官方页面当前标注适用于 `4.1.1.4`。

## DrissionPage

- [浏览器控制入门](https://drissionpage.cn/browser_control/intro)：浏览器对象、标签页、元素查找、输入和点击。
- [连接浏览器](https://www.drissionpage.cn/browser_control/connect_browser)：`Chromium`、`ChromiumOptions`、浏览器路径、调试端口和用户数据目录。
- [浏览器选项](https://www.drissionpage.cn/browser_control/browser_options)：浏览器启动与连接配置。
- [浏览器对象](https://www.drissionpage.cn/browser_control/browser_object)：标签页、浏览器状态、等待和生命周期。
- [标签页管理](https://www.drissionpage.cn/browser_control/tabs)：获取、新建和协同控制标签页。
- [访问网页](https://www.drissionpage.cn/browser_control/visit)：`get()`、重试、超时和加载模式。
- [页面交互](https://www.drissionpage.cn/browser_control/page_operation)：跳转、脚本、弹窗和关闭连接。
- [获取网页信息](https://www.drissionpage.cn/browser_control/get_page_info)：URL、标题、HTML、状态和超时参数。
- [查找元素概述](https://www.drissionpage.cn/browser_control/get_elements/intro)：元素查找对象与基本方式。
- [定位语法](https://www.drissionpage.cn/browser_control/get_elements/syntax)：属性、文本、组合条件和匹配模式。
- [元素查找行为](https://www.drissionpage.cn/browser_control/get_elements/behavior)：查找超时和元素获取行为。
- [在对象中查找元素](https://www.drissionpage.cn/browser_control/get_elements/find_in_object)：页面、元素和 iframe 中查找。
- [相对定位](https://www.drissionpage.cn/browser_control/get_elements/relative)：父子、兄弟和文档前后节点。
- [定位语法速查表](https://www.drissionpage.cn/browser_control/get_elements/sheet)：定位语法与简写索引。
- [元素交互](https://www.drissionpage.cn/browser_control/ele_operation)：点击、输入、选择、上传和下载。
- [获取元素信息](https://www.drissionpage.cn/browser_control/get_ele_info)：文本、属性、状态和位置。
- [iframe 操作](https://www.drissionpage.cn/browser_control/iframe)：同域、跨域和 `ChromiumFrame`。
- [动作链](https://www.drissionpage.cn/browser_control/actions)：鼠标、键盘、拖拽和链式动作。
- [模式切换](https://www.drissionpage.cn/browser_control/mode_change)：d/s 模式与 Cookie 同步。
- [等待](https://www.drissionpage.cn/browser_control/waiting)：元素状态和浏览器事件等待。
- [下载管理](https://www.drissionpage.cn/download/browser)：下载触发、下载任务和完成等待。
- [截图](https://www.drissionpage.cn/browser_control/screen)：页面和元素截图。
- [上传文件](https://www.drissionpage.cn/browser_control/upload)：上传拦截和文件控件输入。
- [监听网络数据](https://www.drissionpage.cn/browser_control/listener)：监听目标、等待和实时消费。
- [获取控制台信息](https://www.drissionpage.cn/browser_control/console)：控制台监听与数据对象。
- [官方 GitHub 仓库](https://github.com/g1879/DrissionPage)：源码、发布记录和问题追踪。

对应的本地详细整理见 [DrissionPage 具体文档](drissionpage/README.md)。

## 影刀 RPA

- [元素库](https://www.yingdao.com/yddoc/rpa/zh-CN/711640069456760832)：元素捕获、存放以及 Web/Windows 元素与对应指令的关系。
- [设置元素属性（Web）](https://www.yingdao.com/yddoc/rpa/zh-CN/711576054527373312)：从元素库选择或捕获目标，并编辑 Web 元素属性。
- [自定义指令使用说明](https://www.yingdao.com/yddoc/rpa/zh-CN/710933855642267648)：自定义指令的开发、调用和编辑。

本项目借鉴“元素独立保存、属性可编辑、指令复用、锚点、校验和修复”的产品思想；当前实现采用 Python 步骤和应用内元素定义，不建立应用快照。企业云元素自动同步、运行时静默修复和产品专有指令格式不属于本项目运行语义。

## 使用规则

- API 实现前重新核对对应官方页面和项目锁定版本。
- 官方文档与本 Wiki 冲突时，API 事实以官方文档为准，项目安全边界以根目录 `AGENTS.md` 为准。
- 竞品文档用于提炼设计原则，不直接复制其私有格式、云同步机制或未经当前环境验证的行为。
- 不从搜索摘要或第三方教程直接复制高风险浏览器启动、Profile 或绕过风控方案。
- 若官方接口行为在真实环境中不同，保存最小复现、版本和证据，再更新 Wiki。
