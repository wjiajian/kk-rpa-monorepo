# kk-rpa-monorepo LLM Wiki

这套 Wiki 为开发者和 AI 提供低歧义的项目上下文。它记录已确认的架构决策、浏览器自动化边界和运行安全约束，不复制整站 API 文档。

## 阅读顺序

1. [系统上下文与边界](01-system-context.md)
2. [DrissionPage 浏览器方案](02-drissionpage-browser-automation.md)
3. [DrissionPage 4.1.1.4 具体文档](drissionpage/README.md)
4. [BrowserActions 契约](03-browser-actions-contract.md)
5. [元素库与失效检测](04-elements-and-pages.md)
6. [运行隔离与安全边界](05-runtime-isolation-and-safety.md)
7. [测试、反例与证据](06-testing-and-evidence.md)
8. [官方资料索引](sources.md)

决策记录：

- [ADR-025：浏览器自动化选用 DrissionPage](decisions/ADR-025-browser-automation-drissionpage.md)
- [ADR-028：V2 结构简化](decisions/ADR-028-v2-structural-simplification.md)（取代 ADR-026、ADR-027）
- [ADR-029：可证伪断言作为唯一强制约束](decisions/ADR-029-falsifiable-step-assertions.md)

## 信息优先级

出现冲突时按以下顺序处理：

1. 当前用户明确要求；
2. 仓库根目录 `AGENTS.md`；
3. `docs/rpa-framework-design.md`；
4. 本 Wiki；
5. 应用自己的 `requirement.md` 和 README；
6. 代码示例。

涉及 DrissionPage 的接口、参数或版本行为时，先查 [官方资料索引](sources.md)。Wiki 中的示例只表达本项目的采用方式，不能替代当前官方文档。

## Wiki 更新规则

- 架构决策变化时，新增或更新 `decisions/` 中的 ADR，并同步专题页。
- 只记录已核验的 API；不确定的接口标记为"实现时待核对"。
- 禁止写入账号、密码、手机号、邮箱、Cookie、Token、真实店铺名、内部地址和本机绝对路径。
- 真实浏览器测试结果必须注明日期、版本和证据位置。

## 当前状态

- 浏览器底层：DrissionPage 4.1.1.4（官方文档核验日期 2026-09-03）
- 架构版本：V2。三层结构 `BrowserActions` → `Element` → `Step`；反例强制是唯一的强制约束
- 首个应用 `jushuitan.inventory.export_stock` 已按 V2 迁移
- 聚水潭和京麦都已使用共享 `rpa_core.cli`；新应用只使用 `BrowserActions` / `Element` / `Step`。`authorization.py`、`catalog.py`、`instructions.py` 等旧合同仅作仓库兼容层，不得进入新应用运行路径
- 已知的历史教训：V1 的 `success_conditions` 是永不执行的字符串，导致 S003（假执行器）和 S004（假验证器）恒真通过。详见 [ADR-029](decisions/ADR-029-falsifiable-step-assertions.md)
