# 系统上下文与边界

当前设计见 [V3 框架设计](../docs/rpa-framework-design.md)，业务术语见 [CONTEXT](../CONTEXT.md)。

一份需求对应一个独立应用。同一需求的后续变更更新原应用。当前只有聚水潭和京麦两个测试程序，两者一起迁移，不保留旧接口兼容层。

Agent 生成普通 Python 应用，固定流程由程序执行。元素库集中维护业务目标和当前定位方式；基础操作 API 处理具体交互问题；Step 的输入、输出和成功条件决定是否继续。失败时 Agent 检查页面、临时处理或选择恢复位置，再通过原校验交回程序。

```text
requirement.md + elements.toml + 本地配置
  → 应用有序 Step
  → ExecutionContext 中的服务
  → BrowserActions / 具体业务服务
  → DrissionPage / 外部系统
```

- `BrowserActions` 隐藏浏览器底层对象；只有核心的 `drission_browser.py` 和 `browser_manager.py` 导入 DrissionPage。
- `ElementSpec` 保存稳定元素身份和定位器，不保存实时 DOM 对象；`ElementEntry` 补充匹配数与检查阶段。
- `Step` 用 `execute` 操作，用 `verify` 回读结果，用正常场景和反例验证成功判定。
- 条件、循环和数据处理直接使用 Python。业务操作先使用应用内函数，基础 API 不扩展成另一套流程语言。
- `Runner` 顺序执行，失败记录并结束。run 从头开始；agent 可根据日志和页面决定恢复点，用 resume 接着执行。
- 每个应用独立维护依赖、锁文件和虚拟环境。

不建立指令目录、资产快照、需求哈希或一次性授权记录。续跑复用普通运行记录中的业务输入与已完成结果。通用浏览器能力留在核心；共享业务抽象等第三个真实应用证明重复再建。

生产按配置无人值守运行。开发期真实浏览器和外部操作仍按用户已授权范围执行。调度、业务看板和写入补偿不在当前框架范围。
