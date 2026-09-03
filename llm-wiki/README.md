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

正式选型记录见 [ADR-025](decisions/ADR-025-browser-automation-drissionpage.md)、[ADR-026](decisions/ADR-026-application-catalog-snapshots.md) 和 [ADR-027](decisions/ADR-027-unified-real-run-authorization.md)。

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
- 当前实现状态：`rpa-core 0.7.0` 已实现 V1/V2 Contract、Instruction/Catalog Snapshot、Checkpoint/Resume、BrowserActions/BrowserManager、redacted source-level Error Diagnostics，以及 durable、exact-scope、single-use Authorization Record；Live adapter 还要求 nested External Write claim 和 independent Read-back Verification
- 当前应用状态：首个 V2 Application `jushuitan.inventory.export_stock` 为 `0.3.0 / ready_for_push`；0.3.0 Developer Review 已通过，0.2.0 Review Record 仅保留为历史证据
- 当前能力边界：229 项 side-effect-free tests 通过（Application 51、Core 178）；0.3.0 Real Browser Preview `preview-20260903T062356Z-df357a62` 已完成 S001–S005、本地下载和成功截图，未执行 External Business Write；当前 Application 不支持 Live
- 真实历史边界：0.2.0 曾在明确授权下完成 Profile Session、S001–S005、本地库存下载和 Resume；版本与 Authorization boundary 已变化，不能替代 0.3.0 验证
- 当前验收证据：[Application Generation Report](../apps/inventory_jushuitan_export_stock/GENERATION_REPORT.md)
- 官方文档核验日期：2026-09-03
- 官方文档标注版本：DrissionPage 4.1.1.4
