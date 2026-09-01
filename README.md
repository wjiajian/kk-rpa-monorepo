# kk-rpa-monorepo

飞书 RPA 需求文档驱动的独立应用框架。它把一份需求转换为一个可测试、可审核、可恢复、可独立运行的 Python RPA 应用，并用公共运行时统一需求一致性、指令执行、检查点、证据和外部写入门禁。

```text
一份飞书需求文档
= 一份需求记忆
= 一个稳定应用 ID
= 一个独立应用目录
= 一个 RPA 程序入口
```

> [!IMPORTANT]
> 截至 2026-09-01，仓库中的 `apps/` 为空，尚不存在已生成、已登录、已完成真实 Preview 或通过业务验收的应用。当前完成的是 `rpa-core 0.2.0` 的指令契约、元素/指令源库、应用快照和 V2 门禁实现；不能把公共包测试通过写成自动化程序已经交付。

## 当前真实基线

- `rpa-core` 保留 V1 App/Requirement 读取能力，新应用使用 V2；
- V2 增加 `InstructionSpec`、`Instruction`、`InstructionRegistry` 和类型化 `ExecutionContext.instructions`；
- 顶层 `elements/`、`instructions/` 只保存真实验证过的源资产；
- 生成器把实际使用项及其依赖闭包复制到应用，并写入 `catalog.lock.json`；
- 每次应用校验都会重算副本哈希，拒绝缺失、篡改、未知依赖、循环、路径逃逸、符号链接和硬链接；
- `PendingConfirmation`、`UnresolvedElement` 和 V2 `UnresolvedInstruction` 都是结构化门禁；
- 当前无副作用测试基线为 125 项通过；
- 没有执行 DrissionPage 真实登录、登录后页面操作、下载或外部写入。

为验证“逐步分析元素”的方法，本次只通过 Codex 内置浏览器观察了公开登录页：确认页面标题、URL、无 iframe 以及公开表单控件，未输入凭据、未点击登录，也未检查登录后页面。该观察不是 DrissionPage 集成测试，也不会进入顶层已验证元素库。

## 调用链

```text
Requirement Step
→ InstructionRegistry
→ Instruction.execute(ExecutionContext, inputs)
→ BrowserActions / 其他受控服务
→ Instruction.verify(result)
→ Step.verify(result)
→ Step 检查点
```

边界含义：

- Program 和 Step 负责编排业务流程、重试、恢复和检查点；
- Instruction 表达可跨应用复用、可独立验证的最小能力；
- Element 描述目标，不保存实时 DOM 对象；
- BrowserActions 隔离业务代码与 DrissionPage；
- 指令只返回声明过的结果，不写 Step 检查点；
- 应用不得直接导入 DrissionPage 或顶层 `elements` / `instructions`。

## 仓库结构

```text
kk-rpa-monorepo/
├── AGENTS.md
├── docs/
│   ├── rpa-framework-design.md
│   └── rpa-core-instruction-catalog-implementation-proposal.md
├── elements/                         # 已验证元素源库
├── instructions/                     # 已验证 Python 指令源库
├── packages/
│   ├── rpa-core/                     # 协议、指令、快照、运行时和门禁
│   ├── rpa-platforms/                # 兼容保留目录，不再是元素源库
│   └── rpa-integrations/             # 后续外部系统适配器
└── apps/                             # 当前为空
```

公共框架通过 uv 本地路径依赖引用，不复制到应用。元素和指令采用应用快照，防止顶层库更新静默改变已测试应用。

## 元素库、指令库与快照

顶层源资产：

```text
elements/<platform>/<product>/<page>/<component>.toml

instructions/<platform>/<product>/<capability>/
├── instruction.toml
└── instruction.py
```

应用 V2 快照：

```text
apps/<app_slug>/
├── catalog.lock.json
└── src/<python_package>/
    ├── elements/
    └── instructions/
```

快照规则：

1. 扫描并验证顶层元数据；
2. 解析 `element:<id>` / `instruction:<id>` 依赖闭包；
3. 复制到应用包内；
4. 固定类型、ID、版本、来源、目标、依赖、复制时间和内容哈希；复制时间不参与内容一致性判断；
5. 运行时只验证应用副本，不读取或自动同步顶层库；
6. 已有应用升级必须先展示版本、哈希和文件 diff。

缺失能力在应用内生成候选元素和候选指令。候选项允许 `doctor` 和无副作用测试，但阻止正常真实运行、审核和推送；真实验证通过后才能提出回灌顶层库的独立 diff。

## 每个应用独立

新生成的 V2 应用必须至少拥有：

- 自己的 `pyproject.toml`、`uv.lock`、`.python-version` 和本地 `.venv/`；
- `app.toml`、`catalog.lock.json`、配置 Schema、需求记忆、源码、测试和生成报告；
- 包内 `elements/` 与 `instructions/` 冻结副本；
- `rpa-app` 标准命令入口。

标准命令：

```bash
uv sync
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
uv run rpa-app login
uv run rpa-app verify-candidates
uv run rpa-app run --mode preview
uv run rpa-app run --mode live
uv run rpa-app resume --run-id <run_id> --mode preview
uv run rpa-app resume --run-id <run_id> --mode live
```

其中 `login` 只管理指定持久化 Profile 的登录态；`verify-candidates` 只在单独授权范围内逐条验证候选能力；二者都不能绕过验证码、人机验证、Preview/Live 或真实浏览器授权。

## 逐步元素分析

在获得明确的真实浏览器授权后，Codex 按需求步骤逐个处理目标：

1. 确认 URL、标题、标签页、iframe 和登录状态；
2. 只分析当前步骤需要的目标；
3. 优先稳定 ID、`name`、`data-*`、可访问名称和稳定文本；
4. 必要时使用稳定锚点限定作用域；
5. 验证匹配数量、可见、可用/可点击和页面身份；
6. 对拟晋升元素刷新或重新进入页面复核；
7. 执行一个原子动作并独立验证结果；
8. 保存脱敏证据，失败时停在当前步骤并生成结构化未解决项。

这套设计参考成熟 RPA 产品的元素捕获、属性编辑、锚点、校验、修复和指令复用思路，但采用可审计文件、冻结快照和显式升级，不使用云端静默同步或未经验证的自动修复。

## 安全与授权

- 业务应用只能通过 `ExecutionContext` 使用浏览器和外部服务；
- 真实浏览器操作必须有应用、账号、站点和步骤范围授权；
- Preview 允许被授权的读取和下载，但业务写入只生成本地预览；
- Live 需要另一次、单次、精确范围授权，并在写入后回读验证；
- 验证码、滑块和短信只检测、留证并转人工，不得绕过；
- `.env`、`stores.local.toml`、需求截图、Profile 和运行产物不得提交；
- AI 不得自行将应用标记为 `approved` 或 `ready_for_push`；
- 默认不建分支、不提交、不推送、不部署。

证据结论必须始终区分：

```text
框架代码完成
≠ 无副作用测试通过
≠ 公开页面观察完成
≠ DrissionPage 真实 Preview 通过
≠ Live 写入验证通过
≠ 开发审核通过
≠ 业务验收通过
```

## 文档入口

- [生成、测试和授权规则](AGENTS.md)
- [完整框架设计](docs/rpa-framework-design.md)
- [本轮实施方案](docs/rpa-core-instruction-catalog-implementation-proposal.md)
- [LLM Wiki 首页](llm-wiki/README.md)
- [系统上下文与边界](llm-wiki/01-system-context.md)
- [BrowserActions 契约](llm-wiki/03-browser-actions-contract.md)
- [元素、页面与候选元素](llm-wiki/04-elements-and-pages.md)
- [测试与证据](llm-wiki/06-testing-and-evidence.md)
- [指令、元素分析与应用快照](llm-wiki/07-instructions-and-snapshots.md)
- [ADR-025：浏览器自动化选用 DrissionPage](llm-wiki/decisions/ADR-025-browser-automation-drissionpage.md)
- [ADR-026：元素与指令使用应用快照](llm-wiki/decisions/ADR-026-application-catalog-snapshots.md)

涉及 DrissionPage、uv、飞书 API 或其他库、SDK、CLI 时，实施前必须重新核对当前官方文档。

## 下一阶段边界

核心指令与快照补丁完成后，生成第一个业务应用仍需要：

1. 实际飞书需求文档 URL 和最新 revision；
2. 应用 ID/目录冲突检查；
3. 需求 Memory、V2 Spec 和候选项草稿；
4. 开发人员确认应用生成范围；
5. 真实候选验证前，再提供账号别名、持久化 Profile、允许操作的步骤和单次授权。

在这些输入与授权到位前，仓库不会凭公开登录页推断登录后元素，也不会生成一个冒充已完成的业务应用。
