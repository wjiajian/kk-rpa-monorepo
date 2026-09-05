# kk-rpa-monorepo LLM Wiki

当前架构以 [V3 框架设计](../docs/rpa-framework-design.md) 为准。此 Wiki 记录项目使用方式；外部 API 事实按锁定版本的官方文档核对。

阅读入口：

1. [系统上下文](01-system-context.md)
2. [DrissionPage 方案](02-drissionpage-browser-automation.md)
3. [BrowserActions 契约](03-browser-actions-contract.md)
4. [元素与页面阶段](04-elements-and-pages.md)
5. [运行目录与执行边界](05-runtime-isolation-and-safety.md)
6. [测试、反例与证据](06-testing-and-evidence.md)
7. [DrissionPage 版本文档](drissionpage/README.md)与[官方资料索引](sources.md)

当前版本为 rpa-core 0.8.0，聚水潭 0.5.0，京麦 0.2.0。两个测试应用一起迁移，旧授权、快照、指令、需求哈希和检查点模块已删除。生产无人值守，run 从头执行，失败后可由 agent 指定步骤 resume；下载目录在新 run 前清空，resume 保留文件。

本次迁移通过离线测试，真实浏览器验证等待授权。

历史决策：

- [ADR-025：DrissionPage 选型](decisions/ADR-025-browser-automation-drissionpage.md)仍适用。
- ADR-026、ADR-027、[ADR-028](decisions/ADR-028-v2-structural-simplification.md)、[ADR-029](decisions/ADR-029-falsifiable-step-assertions.md)保留背景；已被当前设计替代的内容不作为实现要求。

当前用户要求优先于仓库约定；Wiki 与 [AGENTS.md](../AGENTS.md)、V3 设计不一致时，以后两者为准。真实测试结论需说明日期、版本和范围，不能用历史运行代替新版本验收。
