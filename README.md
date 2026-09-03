# kk-rpa-monorepo

飞书 RPA 需求文档驱动的独立应用框架。它把一份需求转换为一个可测试、可审核、可恢复、可独立运行的 Python RPA Application，并用公共 Runtime 统一 Requirement Consistency、Instruction Execution、Checkpoint、Evidence 和 External Write Gates。

```text
一份飞书 Requirement Source
= 一份 Requirement Memory
= 一份 Requirement Spec
= 一个稳定 Application ID
= 一个独立 Application Directory
= 一个 Program Entry Point
```

> [!IMPORTANT]
> 截至 2026-09-03，仓库已经包含第一个 V2 RPA Application `jushuitan.inventory.export_stock`。当前 0.3.0 已迁移到持久化、exact-scope、single-use Authorization Record，并在运行 `preview-20260903T062356Z-df357a62` 完成 S001–S005 和本地库存下载。Developer Review 已通过，Application Status 为 `ready_for_push`；Live 仍不受支持。

## 当前真实基线

- `rpa-core 0.7.0` 保留 V1 App/Requirement 读取能力，新应用使用 V2；
- V2 增加 `InstructionSpec`、`Instruction`、`InstructionRegistry` 和类型化 `ExecutionContext.instructions`；
- 顶层 `elements/`、`instructions/` 只保存 Verified Source Assets；
- Generator 把实际使用项及其 Dependency Closure 复制到应用，并写入 `catalog.lock.json`；
- 每次 Application Validation 都会重算 Snapshot Hash，拒绝缺失、篡改、Unknown Dependency、Cycle、Path Escape、Symbolic Link 和 Hard Link；
- `PendingConfirmation`、`UnresolvedElement` 和 V2 `UnresolvedInstruction` 都是 Structured Gates；
- 顶层公共目录包含 17 个 Verified Elements 和 7 条 Verified Instructions；当前应用冻结使用全部 24 项 Assets；
- 当前离线测试基线为 229 项通过：应用 51 项，`rpa-core` 178 项；
- 交互式 Preview 失败只显示可定位的 Root Cause 摘要，完整 `exception_chain` 和结构化 `traceback` 写入 run-local diagnostics JSON；显式机器命令仍保留完整 JSON 输出；
- Real Browser 入口已统一使用持久化 Authorization Record，并在 Browser Boundary 复核 Operation、Mode、Run、Account、Profile fingerprint、top-level Origin、Step、Action 和 Element Scope；RESUME 还绑定 Checkpoint digest 与 recovery Step，并在 Runner 持有 run lock、重新读取 Checkpoint 后再次核对。当前按内部工具边界处理固定业务 iframe，不再逐个授权 iframe Origin；
- 最新运行 `preview-20260903T062356Z-df357a62` 已验证简化后的内部工具边界：S001–S005 全部完成，生成 218,378 字节的本地 XLSX 和成功截图，Authorization receipt 为 `succeeded`，未执行 external business write；
- 当前应用已验证 Session Reuse、Target Account Identity、Brand Filter、Search 及一次 Inventory Download；
- 当前应用不包含 NAS、飞书、数据库或正式 Excel Write，Live Gate 仍保持关闭。

## Terminology

README 使用代码和持久化字段中的英文原词，中文只解释含义：

| Term | Meaning |
| --- | --- |
| Contract | 可机器校验的数据或接口约束 |
| Gate | 条件不满足时 fail closed 的阻断规则 |
| Manifest | 描述 Application Identity、Version、Status 和 Commands 的清单 |
| Requirement Memory | 面向开发人员阅读和修正的需求基线 |
| Requirement Spec | 与 Requirement Memory 一致的机器可读需求表示 |
| Catalog Snapshot | Application 内冻结的 Element 和 Instruction 集合 |
| Dependency Closure | 一个 Asset 及其全部递归依赖 |
| Checkpoint | Step 成功验证后保存的可恢复状态 |
| Evidence | 支撑运行结论的脱敏日志、截图或 Artifact |
| Authorization | 对真实浏览器或 External Write 的明确、限域许可 |
| Error Diagnostics | 失败时输出的脱敏 Root Cause、Exception Chain 和 Source Location |

项目专用 Domain Language 见 [`CONTEXT.md`](CONTEXT.md)。

## 调用链

```text
Requirement Step
→ InstructionRegistry
→ Instruction.execute(ExecutionContext, inputs)
→ BrowserActions / 其他受控服务
→ Instruction.verify(result)
→ Step.verify(result)
→ Step Checkpoint
```

边界含义：

- Program 和 Step 负责编排业务流程、Retry、Resume 和 Checkpoint；
- Instruction 表达可跨 Application 复用、可独立验证的最小能力；
- Element 描述 UI Target，不保存实时 DOM 对象；
- BrowserActions 隔离业务代码与 DrissionPage；
- Instruction 只返回 Declared Outputs，不写 Step Checkpoint；
- Application 不得直接导入 DrissionPage 或顶层 `elements` / `instructions`。

## 仓库结构

```text
kk-rpa-monorepo/
├── AGENTS.md
├── docs/
│   ├── rpa-framework-design.md
│   └── rpa-core-instruction-catalog-implementation-proposal.md
├── elements/                         # Verified Element Source Catalog
├── instructions/                     # Verified Instruction Source Catalog
├── packages/
│   ├── rpa-core/                     # Contracts, Runtime, Snapshot and Gates
│   ├── rpa-platforms/                # Compatibility placeholder
│   └── rpa-integrations/             # Future external-system Adapters
└── apps/
    └── inventory_jushuitan_export_stock/  # V2 RPA Application
```

公共 Runtime 通过 uv Local Path Dependency 引用，不复制到 Application。Element 和 Instruction 使用 Catalog Snapshot，防止顶层 Source Catalog 更新静默改变已测试 Application。

## 当前应用

`apps/inventory_jushuitan_export_stock/` 是当前首个独立应用：

```text
Prepare 复用或建立登录会话，并核对目标账号身份
→ S001 打开库存模块
→ S002 进入商品库存
→ S003 精确选择本地配置品牌
→ S004 搜索并验证筛选状态
→ S005 导出并校验下载文件
```

Application Version 为 `0.3.0`，Requirement Revision 为 `107`，Application Status 为 `ready_for_push`。0.2.0 的真实 Preview 和 Review Record 保留为历史证据；0.3.0 运行 `preview-20260903T062356Z-df357a62` 已完成 S001–S005 和本地下载，当前版本 Developer Review 已通过。详情见[应用 README](apps/inventory_jushuitan_export_stock/README.md)和[Generation Report](apps/inventory_jushuitan_export_stock/GENERATION_REPORT.md)。

## 快速开始

前置条件：Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/)；Real Browser 流程还需要本机 Chrome/Chromium、Application 本地配置和一次明确 Authorization。

以下命令只执行 Environment Check、Contract Validation 和 Side-effect-free Tests，不会启动 Real Browser：

```bash
cd apps/inventory_jushuitan_export_stock
uv sync --locked
uv run --locked rpa-app doctor
uv run --locked rpa-app check
uv run --locked rpa-app test
```

需要真实 Preview 时，先按应用 README 准备 Git 忽略的 `.env`、`config/stores.local.toml` 和独立 Profile。当前应用的日常入口只需一条命令：

```bash
uv run --locked rpa-app preview --account STORE_001
```

CLI 会自动生成 `run_id` 和 `authorization_id`，底层仍创建 exact `AuthorizationScope`；确认页只显示账号、会发生的真实动作和 `external_writes`，然后询问一次 `确认执行本次 Preview？[y/N]`。只有交互式终端输入 `y` 后才会短时 grant 并启动流程；取消会把 request 标记为 `REVOKED`，非交互环境不会自动授权。完整的 `authorization request/grant` 仍作为 CI、自动化和排障接口。

## Element / Instruction Catalog and Catalog Snapshot

Repository Source Assets：

```text
elements/<platform>/<product>/<page>/<component>.toml

instructions/<platform>/<product>/<capability>/
├── instruction.toml
└── instruction.py
```

Application V2 Catalog Snapshot：

```text
apps/<app_slug>/
├── catalog.lock.json
└── src/<python_package>/
    ├── elements/
    └── instructions/
```

Catalog Snapshot Rules：

1. 扫描并验证 Repository Metadata；
2. 解析 `element:<id>` / `instruction:<id>` Dependency Closure；
3. 复制到 Application Package；
4. 固定 Kind、ID、Version、Source、Target、Dependencies、Copied Time 和 Content Hash；Copied Time 不参与内容一致性判断；
5. Runtime 只验证 Application-local Snapshot，不读取或自动同步 Source Catalog；
6. 已有 Application 升级必须先展示 Version、Hash 和 File Diff。

缺失能力在 Application 内生成 Candidate Element 和 Candidate Instruction。Candidate Assets 允许执行 `doctor` 和 Side-effect-free Tests，但阻止 Real Run、Review 和 Push；完成 Real Verification 后才能提出回灌 Source Catalog 的独立 Diff。

## 每个应用独立

新生成的 V2 应用必须至少拥有：

- 自己的 `pyproject.toml`、`uv.lock`、`.python-version` 和本地 `.venv/`；
- `app.toml`、`catalog.lock.json`、Configuration Schema、Requirement Memory、Source Code、Tests 和 Generation Report；
- Application-local `elements/` 与 `instructions/` Catalog Snapshot；
- `rpa-app` 标准 Command Entry Point。

标准命令：

```bash
uv sync --locked
uv run --locked rpa-app doctor
uv run --locked rpa-app check
uv run --locked rpa-app test
uv run --locked rpa-app authorization request --operation <operation> --mode <mode> --account <account> --run-id <run_id>
uv run --locked rpa-app authorization grant --authorization-id <authorization_id> --scope-digest <scope_digest> --authorized-by <developer_id> --approval-reference <reference> --ttl-seconds <seconds>
uv run --locked rpa-app login --account <account> --run-id <run_id> --authorization-id <authorization_id>
uv run --locked rpa-app verify-candidates --account <account> --run-id <run_id> --authorization-id <authorization_id>
uv run --locked rpa-app run --mode preview --account <account> --run-id <run_id> --authorization-id <authorization_id>
uv run --locked rpa-app run --mode live --account <account> --run-id <run_id> --authorization-id <authorization_id>
uv run --locked rpa-app resume --run-id <run_id> --mode preview --account <account> --authorization-id <authorization_id>
uv run --locked rpa-app resume --run-id <run_id> --mode live --account <account> --authorization-id <authorization_id>
```

当前首个应用另提供交互式快捷入口 `uv run --locked rpa-app preview --account <account>`。它只是把 Preview 的 `request → grant → claim → run` 编排成一次确认，不改变标准 Runtime Contract。`login` 只管理指定 Persistent Profile 的 Session；`verify-candidates` 只在独立 Authorization Scope 内逐条验证 Candidate Assets；这些命令都不能绕过 CAPTCHA、Human Verification、Preview/Live 或 Real Browser Authorization。

## Stepwise Element Analysis

在获得明确的 Real Browser Authorization 后，Codex 按 Requirement Step 逐个处理目标：

1. 确认 URL、标题、标签页、iframe 和登录状态；
2. 只分析当前步骤需要的目标；
3. 优先稳定 ID、`name`、`data-*`、可访问名称和稳定文本；
4. 必要时使用稳定锚点限定作用域；
5. 验证匹配数量、可见、可用/可点击和页面身份；
6. 对拟晋升 Element 刷新或重新进入页面复核；
7. 执行一个原子动作并独立验证结果；
8. 保存 Redacted Evidence，失败时停在当前 Step 并生成 Structured Unresolved Item。

这套设计参考成熟 RPA 产品的 Element Capture、Attribute Editing、Anchor、Validation、Repair 和 Instruction Reuse 思路，但采用 Auditable Files、Frozen Catalog Snapshots 和 Explicit Upgrade，不使用 Cloud Silent Sync 或 Unverified Auto Repair。

## Safety and Authorization

- RPA Application 只能通过 `ExecutionContext` 使用 Browser 和 External Services；
- Real Browser Operation 必须有 Application、Account、Site 和 Steps 的精确 Authorization Scope；
- Preview 允许 Authorized Read 和 Download，但 External Business Write 只生成 Local Write Preview；
- Live 需要另一次 Single-use Scoped Authorization，并在 Write 后执行 Read-back Verification；
- CAPTCHA、Slider 和 SMS Verification 只检测、记录 Evidence 并转人工，不得绕过；
- `.env`、`stores.local.toml`、需求截图、Profile 和运行产物不得提交；
- AI 不得自行将 Application Status 标记为 `approved` 或 `ready_for_push`；
- 默认不创建 Branch，也不执行 Commit、Push 或 Deploy。

Evidence 结论必须始终区分：

```text
Framework Code Complete
≠ Side-effect-free Tests Passed
≠ Public Page Observation Complete
≠ Real DrissionPage Preview Passed
≠ Live Write Verification Passed
≠ Developer Review Passed
≠ Business Acceptance Passed
```

## 文档入口

- [Generation、Testing and Authorization Rules](AGENTS.md)
- [Domain Language](CONTEXT.md)
- [完整框架设计](docs/rpa-framework-design.md)
- [本轮实施方案](docs/rpa-core-instruction-catalog-implementation-proposal.md)
- [LLM Wiki 首页](llm-wiki/README.md)
- [系统上下文与边界](llm-wiki/01-system-context.md)
- [BrowserActions Contract](llm-wiki/03-browser-actions-contract.md)
- [Elements、Pages and Candidate Elements](llm-wiki/04-elements-and-pages.md)
- [Testing and Evidence](llm-wiki/06-testing-and-evidence.md)
- [Instructions、Element Analysis and Catalog Snapshots](llm-wiki/07-instructions-and-snapshots.md)
- [ADR-025：浏览器自动化选用 DrissionPage](llm-wiki/decisions/ADR-025-browser-automation-drissionpage.md)
- [ADR-026：Element and Instruction Catalog Snapshots](llm-wiki/decisions/ADR-026-application-catalog-snapshots.md)
- [ADR-027：Unified Real Run Authorization](llm-wiki/decisions/ADR-027-unified-real-run-authorization.md)

涉及 DrissionPage、uv、飞书 API 或其他库、SDK、CLI 时，实施前必须重新核对当前官方文档。

## 建议的下一阶段

当前框架已经跑通第一个真实业务闭环，下一步建议按以下顺序推进：

1. **验证 Reproducibility**：在 Clean Environment 执行 Locked Install、`doctor`、`check` 和全部 Side-effect-free Tests，确认首个 Application 不依赖开发机偶然状态。
2. **保留当前 Review Evidence**：0.3.0 运行 `preview-20260903T062356Z-df357a62` 的 Checkpoint、Screenshot 和 Download Evidence 已通过 Developer Review；继续保持运行产物仅本地保存。
3. **提交当前版本**：Review Record 已生成，Manifest 为 `ready_for_push`；只提交当前应用、相关公共 Core 和已确认文档，不包含本地运行产物。
4. **生成第二个 RPA Application**：选择一份目标不同但能复用部分 Public Assets 的飞书需求，验证“One Requirement Source, One RPA Application”和 Catalog Reuse 模型确实可扩展。
5. **强化 Step-level Verification**：在 Instruction Verification 之外，为关键 Step 增加独立 Business Success Conditions，避免 Step 只重复调用 Instruction Verifier。
6. **按真实需求补 Integration**：只有第二个 Application 确实需要时，再向 `rpa-integrations` 增加 Excel、飞书或 Database Adapter，并先完成 Preview/Live Gates。
7. **最后接入 Scheduler**：等至少两个 Application 的 Run、Resume、Evidence 和 Authorization 模式稳定后，再设计 Scheduler、Alerting 和 Run Dashboard。

在上述阶段中，Real Browser、Candidate Verification 和 External Write 始终需要独立 Authorization；Scheduler 不能绕过 Application Gates。
