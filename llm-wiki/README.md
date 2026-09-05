# kk-rpa-monorepo LLM Wiki

当前架构以 [V3 框架设计](../docs/rpa-framework-design.md) 为准。后续任务、依赖和验收标准见 [Agent 开发与接管实施文档](../docs/rpa-agent-implementation.md)。此 Wiki 记录项目使用方式；外部 API 事实按锁定版本的官方文档核对，拟新增的接口需以代码实现状态为准。

阅读入口：

1. [系统上下文](01-system-context.md)
2. [DrissionPage 方案](02-drissionpage-browser-automation.md)
3. [BrowserActions 契约](03-browser-actions-contract.md)
4. [元素与页面阶段](04-elements-and-pages.md)
5. [运行目录与执行边界](05-runtime-isolation-and-safety.md)
6. [测试、反例与证据](06-testing-and-evidence.md)
7. [DrissionPage 版本文档](drissionpage/README.md)与[官方资料索引](sources.md)

当前版本为 rpa-core 0.8.0，聚水潭 0.5.0，京麦 0.2.0。两个测试应用一起迁移，旧授权、快照、指令、需求哈希和检查点模块已删除。生产无人值守，run 从头执行，失败后可由 agent 指定步骤 resume；下载默认使用系统下载文件夹，所有命令保留已有文件。

当前基线已通过 209 项离线测试。2026-09-05 在 macOS 完成两个应用真实导出及新接管入口的续跑验收，事实见[聚水潭](../apps/inventory_jushuitan_export_stock/requirement.md)与[京麦](../apps/report_jingmai_export_product_detail/requirement.md)需求基线。Windows 实机验证已授权，等待可连接的环境。

历史决策：

- [ADR-025：DrissionPage 选型](decisions/ADR-025-browser-automation-drissionpage.md)仍适用。
- ADR-026、ADR-027、[ADR-028](decisions/ADR-028-v2-structural-simplification.md)、[ADR-029](decisions/ADR-029-falsifiable-step-assertions.md)保留背景；已被当前设计替代的内容不作为实现要求。

当前用户要求优先于仓库约定；Wiki 与 [AGENTS.md](../AGENTS.md)、V3 设计不一致时，以后两者为准。真实测试结论需说明日期、版本和范围，不能用历史运行代替新版本验收。
