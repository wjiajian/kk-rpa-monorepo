# kk-rpa-monorepo LLM Wiki

这套 Wiki 为开发者和 AI 提供低歧义的项目上下文。它记录已经确认的架构决策、浏览器自动化边界、运行安全约束和官方资料入口，不复制整站 API 文档。

## 阅读顺序

1. [系统上下文与边界](01-system-context.md)
2. [DrissionPage 浏览器方案](02-drissionpage-browser-automation.md)
3. [DrissionPage 4.1.1.4 具体文档](drissionpage/README.md)
4. [BrowserActions 契约](03-browser-actions-contract.md)
5. [元素、页面与候选元素](04-elements-and-pages.md)
6. [运行隔离与安全授权](05-runtime-isolation-and-safety.md)
7. [测试与证据](06-testing-and-evidence.md)
8. [指令、元素分析与应用快照](07-instructions-and-snapshots.md)
9. [官方资料索引](sources.md)

正式选型记录见 [ADR-025](decisions/ADR-025-browser-automation-drissionpage.md) 和 [ADR-026](decisions/ADR-026-application-catalog-snapshots.md)。

## 信息优先级

出现冲突时按以下顺序处理：

1. 当前用户明确要求；
2. 仓库根目录 `AGENTS.md`；
3. `docs/rpa-framework-design.md`；
4. 本 Wiki；
5. 应用自己的需求记忆、Spec 和 README；
6. 代码示例。

涉及 DrissionPage 的接口、参数或版本行为时，先查 [官方资料索引](sources.md)。Wiki 中的示例只表达本项目的采用方式，不能替代当前官方文档。

## Wiki 更新规则

- 架构决策变化时，新增或更新 `decisions/` 中的 ADR，并同步专题页。
- 只记录已经核验的 API；不确定接口标记为“实现时待核对”。
- 业务应用的真实经验应先脱敏，再沉淀为通用规则。
- 禁止写入账号、密码、手机号、邮箱、Cookie、Token、真实店铺名、内部地址和本机绝对路径。
- 真实浏览器测试结果必须注明日期、版本、授权范围和证据位置。

## 当前状态

- Wiki 建立日期：2026-08-31
- 浏览器底层：DrissionPage
- 当前实现状态：`rpa-core 0.2.0` 已实现 V1 运行契约、V2 指令/快照契约、BrowserActions、DrissionPage 动作适配器和 BrowserManager 的包级能力
- 当前应用状态：`apps/` 为空，没有可执行的独立业务应用
- 当前能力边界：无副作用公共包测试已通过；DrissionPage 真实登录、登录后流程、下载、Preview 和真实外部写入均未测试
- 公开页面观察：Codex 内置浏览器只检查过公开登录页，未输入凭据或登录，不属于 DrissionPage 集成验证
- 当前验收证据：[测试与证据](06-testing-and-evidence.md#2026-09-01-核心指令与快照补丁)
- 官方文档核验日期：2026-09-01
- 官方文档标注版本：DrissionPage 4.1.1.4
