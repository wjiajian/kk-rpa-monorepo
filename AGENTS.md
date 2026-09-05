# 全局工作约定

以最小必要范围完成真实需求。设计见 [docs/rpa-framework-design.md](docs/rpa-framework-design.md)。

## 应用与代码

- 一份需求对应一个独立应用；同一需求的变更更新原应用。
- 应用保留 app.toml、requirement.md、elements.toml、独立 pyproject.toml / uv.lock / .venv、config/stores.example.toml、程序入口和离线测试。
- 需求基线是可读 Markdown。app.toml 声明 app_id、name、entrypoint。版本由包与 Git 管理，不建立需求哈希、快照锁、指令注册表或旧接口兼容层。
- 仅 rpa_core/drission_browser.py 和 browser_manager.py 导入 DrissionPage。业务通过 ctx.browser / ctx.feishu / ctx.db / ctx.excel 访问外部系统。
- 程序是有序步骤。登录和身份检查也是步骤；每步提供 execute、verify、counterexamples。
- run 从头执行，失败记录并结束。agent 排查、修复和恢复页面后，用 resume <run_id> --from-step <step_id> 指定续跑位置；沿用原参数和已完成结果。不实现写入补偿或部分写入恢复。
- 下载目录可配置，两个应用默认共同使用仓库 runs/downloads，新 run 前清空，resume 保留已有文件；日志和截图另存应用 runs/<run_id>。不添加共享下载目录的并发协调。
- 下载验收为选对账号、条件、报表并成功下载非空文件，不核对表格内部业务数据。
- 新的共享业务抽象等第三个真实应用证明重复再建。真实飞书和数据库适配跟实际写入需求落地，不用假后端代替正式服务。

## 验证

- 离线测试共用应用 build_test_context；None 表示正常场景。
- 先检查每步正常场景成功，再检查反例。动作失败必须声明预期异常；意外异常和校验器自身报错使测试失败。
- 每步至少有一个 execute 成功后由 verify 返回 False 的结果反例。可用 after_execute 修改假页面或测试产物。
- 日期、品牌等需在续跑中保持的业务参数放 RuntimeOptions.inputs / ctx.inputs；凭据和运行服务放 metadata / services，不持久化到业务参数。
- 续跑保留选定步骤之前的成功结果，从选定步骤起重新执行和校验；不能仅凭旧页面标识消失就重跑全部历史步骤。
- 定位器未知时不编造：记录在 requirement.md，elements.toml 保持未解析，真实运行在启动浏览器前报告未解析元素。
- 元素 expect_count 配合 check_at，在对应页面阶段验证。
- 改动后执行相关离线测试，修复改动造成的问题。需求冲突时一次只问一个问题。
- 外部库或 CLI 接口先用 Context7 或官方文档核对；纯内部重构不需要查库文档。

## 开发验收与正式运行

- 正式上线后按配置无人值守运行，不逐次询问、不创建一次性授权凭证。run 默认正式模式，--preview 供支持预览的业务服务使用。
- 命令是 doctor、test、verify-elements、run、resume。调度由调用方负责。失败保留浏览器供 agent 排查和续跑，成功关闭。
- 写入按业务提供的事务方式执行。框架只负责调用、结果检查和错误记录，不负责部分写入恢复。
- 上线验收时核对账号、目标和操作范围；账号权限按实际业务配置。
- agent 开发时仍需用户授权才可打开真实浏览器、登录、下载业务数据或写入外部系统。代码修改与离线测试不等于真实运行授权。
- CAPTCHA / 滑块 / 短信验证只检测、留证并报错，不绕过。
- 未进行的真实验证标为“等待授权”，不得宣称通过。

## 本地信息与提交

- 真实账号、凭据、店铺、人员和本机路径只存忽略的本地配置、Profiles 或运行产物。可提交文件用稳定别名与占位符。
- 不提交 .env、config/stores.local.toml、profiles/、runs/。
- 默认不建分支、不 commit、不 push、不部署。
- 提交前展示文件清单、测试结果、提交信息和目标分支，得到明确确认后执行。
