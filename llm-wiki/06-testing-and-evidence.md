# 测试与证据

## 测试层次

### 1. 无副作用测试

默认可以自动执行：

- Program 和 Step 顺序、分支、循环；
- Fake Browser、Fake Excel、Fake Feishu、Fake Database；
- 成功条件、重试、失败和恢复；
- Preview 写入拦截；
- Live 未授权拒绝；
- 日志脱敏；
- 检查点原子写入；
- app ID、Program ID、Step ID 唯一性；
- Memory 与 Spec 一致性。

### 2. 架构边界测试

扫描 `apps/`：

- 禁止导入 `DrissionPage`；
- 禁止直接导入飞书、Excel 和数据库底层驱动；
- 禁止出现 `page.ele(...).click()` 等绕开包装器的调用；
- 禁止硬编码 Profile、端口、凭据和本机路径；
- 禁止误提交 `.env`、`stores.local.toml`、截图、运行产物和浏览器 Profile。

### 3. DrissionPage 适配器契约测试

使用 Fake 或受控页面验证：

- 每个动作重新查找元素；
- 等待和超时转换正确；
- 底层异常映射为稳定错误码；
- 输入内容不进入日志；
- iframe 和标签页上下文退出后正确恢复；
- 下载任务等待、超时和产物校验正确；
- 应用层看不到 DrissionPage 类型。

### 4. 真实浏览器测试

必须经过开发人员明确授权。首次默认使用 Preview，且授权限定应用、账号、步骤和目标站点。

真实测试至少验证：

- Chrome 启动或连接；
- Profile、端口和锁隔离；
- 定位唯一性、显示、可点击和刷新稳定性；
- 标签页、iframe 和下载行为；
- 成功条件和失败证据；
- 两个账号并发时互不影响。

## 证据要求

每次运行至少关联：

- `run_id`、`app_id`、程序版本和需求哈希；
- 账号的脱敏别名；
- 运行模式和授权引用；
- 步骤状态、尝试次数和耗时；
- 错误码和是否可重试；
- 截图、下载、预览和日志引用；
- 未执行测试及原因。

证据必须区分：

```text
代码生成完成
≠ 无副作用测试通过
≠ 真实浏览器 Preview 通过
≠ Live 写入验证通过
≠ RPA 开发审核通过
≠ 业务迁移验收通过
```

## 2026-08-31 阶段 1+2 离线验收基线

本次验收只使用脱敏 fixture、Fake 服务和本地运行目录，未启动浏览器，也未连接飞书、Excel、数据库、NAS 或其他真实外部系统。

| 验收项 | 结果 |
| --- | --- |
| `rpa-core` 无副作用测试 | 102 项通过；包含 7 项 DrissionPage 动作适配器和 7 项 BrowserManager 隔离测试 |
| `example_offline_order_daily` 无副作用测试 | 27 项通过 |
| `inventory_jushuitan_export_stock` 无副作用测试 | 27 项通过；Fake Browser 完成 S001–S006，并验证配置映射、Preview 精确授权、Live 拒绝、中断恢复及下载证据篡改拒绝 |
| 离线示例 `rpa-app doctor` | 退出码 0 |
| 离线示例 `rpa-app check` | 退出码 0；同仓库待确认草稿不会跨应用阻塞 |
| run/resume 自动门禁 | Memory/Spec、开放 PC/UE、Manifest/程序身份、架构和敏感信息任一失败均在创建运行目录前退出 21 |
| 运行目录安全 | 安全 run ID、应用目录绑定、服务路径绑定、同 run 跨进程排他、symlink/hardlink 拒绝均有回归测试 |
| Preview | 成功，`run_id=first-batch-final-20260831-f1` |
| Preview 写入边界 | `write_executed=false`、`backend_write_calls=0` |
| Preview 内容 | 1 条日报记录，总金额 `200.00` |
| Resume | 重新验证 `S004` Preview 证据，跳过已成功的 `S001`–`S004` |
| 全新运行的未授权 Live | 退出码 20，未创建 Live 运行目录 |
| Resume 的未授权 Live | 退出码 20，原 Preview 检查点保持 `preview/succeeded` |

Preview 产物位于：

```text
apps/example_offline_order_daily/runs/first-batch-final-20260831-f1/write-previews/feishu-base-upsert--S004.json
```

该路径属于 Git 忽略的本地运行证据。验收结论是“阶段 1+2 离线实现与验收完成”，不等于真实浏览器 Preview、真实 Live 写入、RPA 开发审核或业务迁移验收完成。

当前同运行排他锁基于 POSIX `flock`，已在本次 macOS 环境验证；不支持的平台会拒绝运行。Windows 等目标运行机需要先实现等价锁并增加跨进程回归。父目录被同一账号恶意并发替换的 dirfd 级 TOCTOU 加固不在第一批验收范围内，后续不能把本轮结论扩展为对本机恶意进程的完整防护。

2026-09-01 当前真实需求草稿验证边界：

- Memory 与 Spec 零字段差异，声明/计算/Manifest/程序哈希一致；
- 14 个候选元素中，4 个公开登录页元素已通过内置浏览器检查并绑定 locator；其余 10 个仅按稳定 ID 驱动；
- 运行时输入、日志和检查点不包含测试凭据或品牌值；
- `check` 只报告 2 个开放 `PendingConfirmation` 与 10 个 `UnresolvedElement`；
- Preview、Resume 和 Live 均在创建 `runs/` 前退出 21；
- 三张需求截图由 Git 忽略，文件哈希与需求记忆一致。

尚未测试：

- DrissionPage 动作适配器与真实 Chromium 的集成；
- BrowserManager 与真实 Chrome 的启动集成、iframe、标签页、真实下载和真实截图；
- 真实飞书、Excel、数据库、NAS 和告警写入；
- Live 写入后的真实回读验证。

## DrissionPage 升级验证

升级底层版本时至少回归：

- 浏览器连接和已有 Profile；
- 元素查找、等待、输入与点击；
- iframe 和新标签页；
- 下载任务；
- 截图和失败证据；
- 端口、锁和浏览器生命周期；
- 所有引用公共浏览器适配器的应用。

升级结果应记录版本、日期、测试环境和受影响应用，不得只以安装成功作为兼容性结论。
