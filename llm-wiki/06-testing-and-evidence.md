# 测试与证据

## 测试层次

### 1. 无副作用测试

默认可以自动执行：

- Program 和 Step 顺序、分支、循环；
- Fake Browser、Fake Excel、Fake Feishu、Fake Database；
- 成功条件、重试、失败和恢复；
- Preview 写入拦截与 Live 未授权拒绝；
- 日志脱敏和检查点原子写入；
- App、Program、Step 和阻塞项 ID 唯一性；
- Memory、Spec、Manifest 和需求哈希一致性；
- Instruction 输入输出、独立验证、稳定错误和检查点边界；
- Catalog 发现、依赖闭包、复制、锁文件和内容哈希。

### 2. 架构与快照测试

扫描应用：

- 禁止直接导入 DrissionPage、飞书、Excel 和数据库底层驱动；
- 禁止 `page.ele(...).click()` 等绕开 BrowserActions 的调用；
- 禁止从顶层 `elements` / `instructions` 导入运行时代码；
- 复制到应用的指令同样禁止直接导入 DrissionPage；
- V2 `catalog.lock.json`、元素/指令引用和候选条目必须一致；
- 快照文件缺失、哈希变化、未知依赖、循环、路径逃逸、符号链接或硬链接必须 fail-closed；
- 禁止硬编码 Profile、端口、凭据和本机路径；
- 禁止误提交 `.env`、`stores.local.toml`、截图、运行产物和浏览器 Profile。

### 3. DrissionPage 适配器契约测试

使用 Fake Tab 或受控页面验证：

- 每个动作重新查找元素；
- 等待和超时转换正确；
- 底层异常映射为稳定错误码；
- 输入内容不进入日志；
- iframe 和标签页上下文退出后恢复；
- 下载任务等待、超时和产物校验正确；
- 应用层看不到 DrissionPage 类型。

这类适配器契约测试仍不等于真实 Chromium 集成。

### 4. 候选验证

`rpa-app verify-candidates` 必须有一次性、精确范围授权，至少限定应用、账号别名、Profile、目标站点、步骤和允许动作。

逐条验证：

- 页面 URL、标题、标签页、iframe 和登录状态；
- 元素匹配数量、可见、可用/可点击和刷新稳定性；
- Instruction 声明输入输出与独立成功条件；
- 失败截图、脱敏 DOM 摘要和稳定错误；
- 验证批次、运行 ID、版本和证据引用。

候选验证不能关闭正常 `run` 的阻塞规则，也不能自动把候选项回灌顶层库。

### 5. 真实浏览器 Preview

必须再次经过开发人员授权。首次业务流程默认 Preview：

- 允许授权范围内的页面读取、查询、筛选和下载；
- 页面提交、飞书、数据库、正式 Excel、NAS 等业务写入被拦截；
- 检查成功条件、下载文件、哈希、失败恢复和证据；
- Profile、端口和运行目录保持账号隔离。

### 6. Live 与业务验收

Live 需要与 Preview 分离的单次授权，限定应用、run、账号、目标、步骤、数据范围、预计数量和有效期。完成后必须回读验证。

开发审核和业务验收仍是后续独立状态，不能由测试自动推导。

## 证据要求

每次运行至少关联：

- `run_id`、`app_id`、程序版本和需求哈希；
- 账号脱敏别名、运行模式和授权引用；
- Catalog lock 哈希和实际使用的元素/指令版本；
- 步骤、指令、尝试次数、耗时和验证结果；
- 错误码和是否可重试；
- 截图、下载、预览和日志引用；
- 未执行测试及原因。

证据必须区分：

```text
框架代码完成
≠ 无副作用测试通过
≠ 公开页面观察完成
≠ 候选真实验证通过
≠ DrissionPage 真实 Preview 通过
≠ Live 写入验证通过
≠ RPA 开发审核通过
≠ 业务迁移验收通过
```

## 2026-09-01 核心指令与快照补丁

本轮代码范围是公共框架、Schema、验证器、测试和架构文档。没有生成业务应用，`apps/` 为空。

无副作用验收：

| 验收项 | 结果 |
| --- | --- |
| 原有测试兼容 | 原基线 102 项继续纳入全量测试 |
| `rpa-core` 全量测试 | 125 项通过 |
| V1/V2 契约 | V1 可读；V2 强制 catalog lock、login 和 verify-candidates |
| Instruction | 重复/未知 ID、输入输出漂移、验证失败和异常脱敏有回归 |
| Requirement V2 | `UI-*` 未知引用、孤立项、候选和 resolved 证据有回归 |
| Catalog | 依赖闭包、跨类型全局 ID 唯一、未知依赖、循环和冻结副本有回归 |
| 快照安全 | 缺失/篡改、路径逃逸、符号链接、硬链接及 symlink lock 有回归 |
| 应用架构 | 顶层资产 import 和复制指令直接导入 DrissionPage 被拒绝 |
| JSON Schema | 三份检查入库 Schema 由当前 Pydantic 模型生成 |

公开页面观察边界：

- 使用 Codex 内置浏览器打开公开登录页；
- 观察到页面标题、URL、iframe 状态和公开表单控件；
- 未输入账号或密码；
- 未点击登录；
- 未处理验证码或人机验证；
- 未访问登录后页面；
- 未下载文件或写入外部系统；
- 未通过 DrissionPage 或应用 CLI 执行。

因此该观察只验证逐步分析方法可以从页面身份开始，不能标记为候选真实验证、DrissionPage 集成、Preview 或业务验收。

未运行：

- 从真实飞书需求读取 revision、正文和截图；
- 生成 V2 独立应用及应用自己的 uv 环境；
- `rpa-app login` 和 `verify-candidates`；
- DrissionPage 与真实 Chromium、Profile、下载和截图集成；
- 登录后页面元素分析；
- 真实 Preview、Resume 或 Live；
- 飞书、Excel、数据库、NAS 和告警写入；
- 开发审核、提交、推送、部署和业务验收。

## DrissionPage 升级验证

升级底层版本时至少回归：

- 浏览器连接和已有 Profile；
- 元素查找、等待、输入与点击；
- iframe 和新标签页；
- 下载任务、截图和失败证据；
- 端口、锁和浏览器生命周期；
- 所有引用公共浏览器适配器的应用。

升级结果应记录版本、日期、测试环境和受影响应用，不得只以安装成功作为兼容性结论。
