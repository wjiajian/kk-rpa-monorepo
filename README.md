# kk-rpa-monorepo

飞书 RPA 需求文档驱动的独立应用框架。它把一份需求转换为一个可测试、可审核、可恢复、可独立运行的 RPA 应用，并用公共运行时统一需求一致性、检查点、证据和外部写入门禁。

```text
一份飞书需求文档
= 一份需求记忆
= 一个稳定应用 ID
= 一个独立应用目录
= 一个 RPA 程序入口
```

> [!IMPORTANT]
> 阶段 1“需求协议和应用骨架”与阶段 2“核心运行闭环”已经完成离线实现与验收；阶段 3 已完成 `BrowserActions` 最小契约、Fake Browser 和首个真实需求的完整程序草稿。该结论仅覆盖脱敏 fixture、Fake 服务和本地产物，不代表 DrissionPage 适配器、真实浏览器、真实外部写入、开发审核或业务验收已经通过。

## 当前范围

第一批代码面向完全离线的纵向闭环：

```text
脱敏假需求
→ REQUIREMENT_MEMORY.md 与 requirement.spec.json
→ 独立应用和标准 CLI
→ Program / Step / ExecutionContext
→ 文件检查点、失败恢复和 JSONL 事件
→ Preview 本地产物
→ 未授权 Live 被拒绝
```

当前已完成离线验收的内容包括：

- 版本化的 `app.toml` 与需求协议模型；
- Memory、Spec、应用清单及需求哈希的一致性门禁；
- `apps/*/app.toml` 扫描、应用身份冲突检测、架构边界和敏感内容检查；
- Program、Step、ExecutionContext、状态机、原子文件检查点和 Resume；
- `run`/`resume` 执行前强制门禁，以及运行身份、目录、服务和证据路径绑定；
- 同一 `run_id` 的 OS 文件排他锁，符号链接/硬链接逃逸防护；
- Preview/Live 授权策略、Fake 外部服务和结构化运行事件；
- 一个不访问浏览器或外部系统的离线订单日报示例；
- `BrowserActions`、稳定元素身份、SecretValue、下载/证据引用和 Fake Browser；
- 飞书真实测试需求 revision 107 对应的“聚水潭库存导出”独立应用草稿。

2026-08-31 离线验收基线：

- `rpa-core`：88 项测试通过；
- `example_offline_order_daily`：27 项测试通过；
- `inventory_jushuitan_export_stock`：27 项 Fake Browser、配置、授权与无副作用测试通过；
- `doctor`、`check`：退出码均为 0；
- Preview：`run_id=first-batch-final-20260831-f1`，生成 1 条金额 `200.00` 的本地预览，`write_executed=false`、`backend_write_calls=0`；
- Resume：重新验证 `S004` Preview 证据后，跳过已经成功的 `S001`–`S004`；
- 全新运行和 Resume 的未授权 Live：退出码均为 20；未创建新的 Live 运行目录，也未改变 Preview 检查点。

完整证据边界见[测试与证据](llm-wiki/06-testing-and-evidence.md)。

## 仓库结构

```text
kk-rpa-monorepo/
├── AGENTS.md                         # 最高级生成、测试、审核和授权规则
├── docs/
│   └── rpa-framework-design.md       # 完整架构设计与实施阶段
├── llm-wiki/                         # 项目决策与 DrissionPage 本地知识库
├── packages/
│   ├── rpa-core/                     # 协议、门禁、运行时、检查点和证据
│   ├── rpa-platforms/                # 后续存放经真实验证的平台页面和元素
│   └── rpa-integrations/             # 后续存放 Excel、飞书和数据库适配器
└── apps/
    ├── example_offline_order_daily/          # 离线纵向示例
    └── inventory_jushuitan_export_stock/     # 真实需求生成的待确认应用草稿
```

公共能力只放在 `packages/`。业务应用通过本地 path dependency 使用公共包，不复制框架，也不依赖其他应用目录。

## 每个应用独立运行

每个 `apps/<app_slug>/` 都必须拥有自己的：

- `pyproject.toml`；
- `uv.lock`；
- `.python-version`；
- 本地 `.venv/`；
- `app.toml`、配置 Schema、需求记忆、源码、测试和生成报告；
- `rpa-app` 标准命令入口。

根目录不提供供所有应用共用的虚拟环境或锁文件。在目标应用目录内执行：

```bash
uv sync
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
uv run rpa-app run --mode preview
uv run rpa-app run --mode live
uv run rpa-app resume --run-id <run_id> --mode preview
uv run rpa-app resume --run-id <run_id> --mode live
```

命令语义：

| 命令 | 责任 |
| --- | --- |
| `doctor` | 检查 Python、配置、目录、依赖及声明的本地能力 |
| `check` | 检查需求一致性、待确认项、元素状态和架构边界 |
| `test` | 运行无外部副作用测试 |
| `run --mode preview` | 执行允许的流程，但把业务写入转换为本地预览 |
| `run --mode live` | 仅在一次性、精确范围授权后执行真实写入 |
| `resume` | 从失败步骤恢复，同时继续受 Preview/Live 门禁约束 |

## 当前离线示例

示例应用位于 [`apps/example_offline_order_daily/`](apps/example_offline_order_daily/)，应用入口为：

```text
example_offline_order_daily.cli:main
```

它使用脱敏的本地订单 fixture 演示读取、筛选、汇总和 Fake 飞书写入请求。已验证 Preview 只在当前运行目录生成写入预览，没有有效授权的 Live 会在产生副作用前被拒绝。

```bash
cd apps/example_offline_order_daily
uv sync
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
uv run rpa-app run --mode preview
```

> [!NOTE]
> 示例用于证明框架闭环，不是已接入生产平台的 RPA 应用。执行 `live` 不是本轮离线验收的前置条件；本轮需要验证的是未授权 Live 会被安全拒绝。

## 当前测试需求应用

[`apps/inventory_jushuitan_export_stock/`](apps/inventory_jushuitan_export_stock/) 由飞书需求 revision `107` 生成，包含登录、商品库存导航、品牌筛选、导出和返回文件路径的完整六步程序。Fake Browser 已验证完整流程与检查点恢复，凭据和真实品牌不会进入日志或检查点。

该应用仍有 2 个开放的 `PendingConfirmation`；14 个元素记录中有 4 个登录页候选元素已经内置浏览器检查并解析，另有 10 个开放的 `UnresolvedElement`。BrowserManager 已绑定标准 CLI、本地店铺配置、独立 Profile 和精确到 run/account 的 Preview 授权；当前 `check`、`run`、`resume` 和 `live` 仍先被需求门禁拒绝，且未创建运行目录。当前状态不是“DrissionPage 真实流程测试通过”。

## 安全与授权边界

- 业务应用只能通过 `ExecutionContext` 访问浏览器、Excel、飞书、数据库、日志、凭据和检查点。
- `apps/` 禁止直接导入 DrissionPage 或外部系统底层 SDK，也禁止调用 `page.ele(...).click()` 绕过包装器。
- `run` 和 `resume` 在创建运行目录前自动执行需求、清单、架构和敏感信息门禁，不能依赖人工先运行 `check`。
- 运行目录必须精确绑定为当前应用的 `runs/<run_id>`；同一运行全程持有 OS 排他锁，路径型服务及 checkpoint/event 必须绑定同一运行身份。
- 步骤成功条件验证通过后才能原子写入检查点。
- Preview 只是写入策略，不等于获得真实浏览器操作授权。
- Live 授权必须限定应用、运行、账号、步骤、目标、数据范围、预计数量和有效期，并在适配器产生副作用前再次校验。
- 未解决的 `PendingConfirmation` 或 `UnresolvedElement` 会阻止审核、提交和推送。
- AI 不得自行把应用标记为 `approved` 或 `ready_for_push`。
- `.env`、`stores.local.toml`、需求截图、浏览器 Profile、运行日志、检查点和预览产物不得提交。
- 验证码、滑块和短信只允许检测、留证并转人工处理，不得绕过。

第一批排他锁使用 POSIX `flock`；当前 macOS 验收通过。在不支持该能力的平台上运行时会 fail-closed。进入 Windows 运行机部署前，必须实现并测试等价的进程退出自动释放锁，不能关闭排他门禁规避兼容性问题。

完整规则见 [`AGENTS.md`](AGENTS.md)、[运行隔离与安全授权](llm-wiki/05-runtime-isolation-and-safety.md)和[测试与证据](llm-wiki/06-testing-and-evidence.md)。

## DrissionPage 与 LLM Wiki

浏览器自动化底层已经选定 [DrissionPage](https://drissionpage.cn/browser_control/intro)，但业务应用不会直接接触其 Chromium、Tab、Element 或下载任务对象。后续统一调用链为：

```text
业务应用
→ ExecutionContext.browser
→ BrowserActions
→ DrissionBrowserActions
→ DrissionPage
```

项目知识入口：

- [LLM Wiki 首页](llm-wiki/README.md)
- [系统上下文与边界](llm-wiki/01-system-context.md)
- [DrissionPage 浏览器自动化方案](llm-wiki/02-drissionpage-browser-automation.md)
- [DrissionPage 4.1.1.4 具体文档](llm-wiki/drissionpage/README.md)
- [BrowserActions 契约](llm-wiki/03-browser-actions-contract.md)
- [元素、页面与候选元素](llm-wiki/04-elements-and-pages.md)
- [运行隔离与安全授权](llm-wiki/05-runtime-isolation-and-safety.md)
- [测试与证据](llm-wiki/06-testing-and-evidence.md)
- [ADR-025：浏览器自动化选用 DrissionPage](llm-wiki/decisions/ADR-025-browser-automation-drissionpage.md)
- [完整架构设计](docs/rpa-framework-design.md)

涉及 DrissionPage、uv、飞书 API 或其他 SDK/CLI 的实现，必须先核对当前官方文档，不能仅凭 Wiki 示例或历史记忆推断接口。

## 下一阶段

阶段 1+2 的离线验收已经完成，阶段 3 已具备公共契约、Fake Browser、DrissionPage 4.1.1.4 动作适配器、BrowserManager 和当前应用 CLI 绑定。下一步继续内部页面元素实现：

1. 用户在内置浏览器完成登录后，自主检查登录成功标识和库存内部页面元素；
2. 逐项关闭测试应用的待确认项；
3. 在明确授权下运行 DrissionPage Preview，验证下载、截图、失败证据及恢复；
4. 通过端到端验证后，再把稳定候选元素迁移到 `rpa-platforms` 并回归受影响应用。

当前动作适配器已经通过 Fake Tab 测试，但尚未与真实 Chromium 集成，也没有执行 DrissionPage 登录或库存下载。真实 Excel、飞书、数据库和告警写入仍属于阶段 4，尚未测试；调度中心和业务看板继续后置。
