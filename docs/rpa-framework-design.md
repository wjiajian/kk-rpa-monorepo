# AI 驱动的浏览器 RPA 应用框架设计

> 文档状态：第三版，已纳入 2026-09-01 指令库与应用快照决策
> 适用平台：淘系、京东、拼多多等浏览器后台
> 业务协作：浏览器自动化、Excel、飞书多维表格和数据库
> 当前重点：给 AI 一份带操作描述和截图的飞书需求文档，由 AI 生成一个完整、独立、可测试和可审核的 RPA 应用

## 1. 愿景

本项目的最终使用方式不是让开发人员从空目录手写自动化脚本，而是：

~~~text
飞书 RPA 需求文档和操作截图
→ AI 解析需求
→ 生成仓库内独立 RPA 应用
→ 自动执行无副作用测试
→ 开发人员处理待确认项
→ 开发人员授权真实浏览器预览测试
→ 必要时单独授权真实写入测试
→ RPA 开发人员自然语言审核
→ 手动或授权 AI 提交和推送
~~~

固定关系为：

~~~text
一份飞书需求文档
= 一份需求记忆
= 一个应用 ID
= 一个独立应用目录
= 一个 RPA 程序入口
~~~

同一需求文档后续修改时更新原应用。只有业务目标实质变化，才创建新的应用。

## 2. 背景和已确认约束

公司现有约 100 个影刀 RPA 程序，需要逐步迁移。程序包含每天、每周和每月任务，业务范围可以视为：

- 浏览器自动化；
- Python 直接读写 .xlsx；
- 通过 API 读写飞书多维表格；
- 必要时读写业务数据库；
- 失败时通过飞书机器人通知开发人员。

统一任务运行在专用 Windows 物理机。机器之间采用主机级隔离，同一台机器允许不同店铺并发执行相同应用，预估最多约 6 并发。

每个店铺必须使用独立 Chrome 进程、持久化 Profile 和调试端口，避免一个店铺登录后挤掉另一个店铺的登录状态。

团队约 6～8 人。业务人员可以通过 Codex 等工具在个人设备生成和测试应用；进入统一机器前，必须由 RPA 开发人员审核。

每个影刀程序迁移后，新旧程序同时运行一周并比较结果，通过业务验收后再切换。

## 3. 设计目标

### 3.1 面向 AI 生成

- 需求文档不要求改成 JSON、YAML 或技术 DSL；
- AI 能从现有飞书模板、自由描述和步骤截图中提取流程；
- 缺少信息时仍生成完整程序草稿；
- 所有不确定内容形成结构化待确认项；
- 需求、代码、测试和审核记录可以长期追踪。

### 3.2 面向独立应用

- 每份需求生成一个独立应用；
- 每个应用有自己的 pyproject.toml、uv.lock 和 .venv；
- 应用可以单独安装、测试、运行和部署；
- 一个应用通过配置支持多个店铺，不复制程序代码；
- 应用通过路径依赖复用仓库中的公共包最新代码。

### 3.3 面向稳定运行

- 业务代码只表达业务步骤；
- 浏览器、Excel、飞书和数据库操作经过统一包装；
- 每一步都有成功条件；
- 验证成功后才写检查点；
- 失败后从失败步骤恢复；
- 外部写入支持预览和单独授权；
- 不同店铺并发时浏览器和运行状态完全隔离。

### 3.4 面向审核和治理

- AI 默认不创建分支、不提交、不推送、不部署；
- 真实浏览器测试需要开发人员允许；
- 真实写入需要在预览后再次单独授权；
- 未解决待确认项禁止提交和推送；
- 最终审核状态只能由 RPA 开发人员确认；
- 每次审核都形成不可覆盖的历史记录。

## 4. 非目标

当前阶段不处理：

- 不修改现有飞书需求模板；
- 不建设完整调度中心和业务看板；
- 不设计物理机故障自动漂移；
- 不自动翻译整个影刀工程；
- 不把视觉大模型作为正常操作的主要方式；
- 不建设企业级密钥平台，初期使用应用本地 .env；
- 不把公共页面数据的每日抓取逻辑重复放入每个 RPA 应用；
- 暂不创建专用 AI Skill，先由 AGENTS.md、Schema、模板和自动检查约束生成流程。

## 5. 总体流程

~~~mermaid
flowchart TB
    D[飞书需求文档和截图] --> I[需求摄取器]
    I --> M[REQUIREMENT_MEMORY.md]
    I --> J[requirement.spec.json]
    M --> C{一致性检查}
    J --> C
    C -->|不一致| N[停止并通知开发人员]
    C -->|一致| G[AI 应用生成器]
    G --> A[独立应用草稿]
    G --> P[待确认项]
    G --> T[无副作用自动测试]
    P --> R[开发人员确认或授权补抓]
    T --> B[真实浏览器 Preview]
    R --> B
    B --> W[写入格式预览]
    W --> L[单独授权 Live 写入]
    L --> V[端到端验证]
    V --> Q[RPA 开发人员自然语言审核]
    Q --> X[提交和推送]
~~~

## 6. 架构分层

| 层 | 责任 | 禁止事项 |
| --- | --- | --- |
| 需求层 | 飞书读取、截图下载、需求 memory、JSON Spec、变更比较 | 在可提交文件中保留真实店铺和凭据 |
| AI 生成层 | 生成完整应用、待确认项、候选元素/指令、测试和报告 | 静默覆盖已有应用或人工代码 |
| 应用层 | 一份需求对应的业务流程、独立依赖和冻结资产副本 | 直接调用 DrissionPage、顶层源库或外部服务底层驱动 |
| 公共框架层 | Program、Step、Instruction、Catalog、上下文、恢复、门禁和运行时 | 包含具体店铺业务逻辑 |
| 平台资产层 | 顶层已验证元素与 Python 指令源库 | 保存实时 DOM、账号、店铺配置或未验证定位 |
| 集成层 | Excel、飞书、数据库和告警 | 感知具体应用 ID |
| 运行时层 | 浏览器实例、Profile、端口、锁、目录和进程 | 多店铺共享同一 Profile |

## 7. 目标仓库结构

~~~text
rpa-monorepo/
├── AGENTS.md
├── README.md
├── .gitignore
├── elements/
│   ├── README.md
│   └── <platform>/<product>/<page>/<component>.toml
├── instructions/
│   ├── README.md
│   └── <platform>/<product>/<capability>/
│       ├── instruction.toml
│       └── instruction.py
├── docs/
│   └── rpa-framework-design.md
├── packages/
│   ├── rpa-core/
│   │   ├── pyproject.toml
│   │   ├── src/rpa_core/
│   │   │   ├── instructions.py
│   │   │   ├── catalog.py
│   │   │   └── schemas/
│   │   └── tests/
│   ├── rpa-platforms/                # 兼容保留，不再是资产源库
│   └── rpa-integrations/
└── apps/
    └── <app_slug>/
        ├── app.toml
        ├── pyproject.toml
        ├── uv.lock
        ├── .python-version
        ├── .env.example
        ├── .gitignore
        ├── README.md
        ├── GENERATION_REPORT.md
        ├── catalog.lock.json
        ├── requirement/
        ├── config/
        ├── src/<python_package>/
        │   ├── elements/
        │   └── instructions/
        ├── tests/
        └── reviews/
~~~

根目录不为所有应用提供共享 .venv 或统一 uv.lock。公共框架和每个应用都是独立 Python 项目。元素和指令只在生成时从顶层源库复制，应用运行时只读取自己的冻结副本。

## 8. 独立应用结构

~~~text
apps/<app_slug>/
├── app.toml
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
├── README.md
├── GENERATION_REPORT.md
├── REQUIREMENT_CHANGE_PROPOSAL.md
├── catalog.lock.json
├── requirement/
│   ├── REQUIREMENT_MEMORY.md
│   ├── requirement.spec.json
│   └── assets/
│       ├── step-001-login-page.png
│       └── step-002-export-button.png
├── config/
│   ├── config.schema.json
│   ├── stores.example.toml
│   └── stores.local.toml
├── src/
│   └── <python_package>/
│       ├── __init__.py
│       ├── cli.py
│       ├── program.py
│       ├── steps.py
│       ├── models.py
│       ├── validators.py
│       ├── elements/
│       └── instructions/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── architecture/
│   └── fixtures/
└── reviews/
    └── <timestamp>.toml
~~~

### 8.1 独立性要求

每个应用必须：

- 在自己的目录执行 uv sync；
- 在 pyproject.toml 旁生成自己的 .venv；
- 提交自己的 uv.lock；
- 声明自己的第三方依赖；
- 拥有独立测试和命令入口；
- 可以单独复制到目标机器并同步环境；
- 不依赖其他应用目录；
- 使用 `catalog.lock.json` 固定包内元素和指令，不在运行时引用顶层源库。

uv 当前项目机制会在 pyproject.toml 同级管理持久化 .venv，uv run 会在执行前检查项目、锁文件和环境是否一致。

### 8.2 引用公共包

应用引用仓库内公共包的最新代码。例如：

~~~toml
[project]
name = "sales-taobao-sycm-store-daily"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "rpa-core",
]

[tool.uv.sources]
rpa-core = { path = "../../packages/rpa-core", editable = true }

[project.scripts]
rpa-app = "sales_taobao_sycm_store_daily.cli:main"
~~~

应用不固定 `rpa-core` 旧版本；需要外部集成时再声明 `rpa-integrations`。公共包修改会影响引用它的应用，因此合入前必须识别受影响应用并执行回归测试。

顶层 `elements/` 和 `instructions/` 不是 Python path dependency。生成应用时只复制实际使用项及依赖闭包，之后由应用自己的锁文件和哈希保证可复现。顶层资产更新不会自动影响已有应用。

## 9. 需求输入

当前飞书需求模板保持不变。已确认模板包含：

- 任务名称；
- 执行频率；
- 触发时间；
- 平台名称和地址；
- 账号提供人；
- 所需权限；
- RPA 操作流程区域；
- NAS 保存路径和文件名规则；
- 飞书多维表格链接、写入方式和唯一匹配字段。

提报人需要提供详细操作描述和步骤截图。AI 不要求提报人同时维护机器可读格式。

### 9.1 需求摄取步骤

1. 使用用户身份读取飞书文档；
2. 记录文档 ID 和 revision；
3. 读取基本信息、操作流程和输出位置；
4. 下载截图到应用 requirement/assets；
5. 为截图生成步骤化文件名；
6. 记录截图来源标识和 SHA-256；
7. 从文本和截图提取有序业务步骤；
8. 识别输入、输出、成功条件、循环和分支；
9. 匹配顶层已验证元素库和指令库，并解析依赖闭包；
10. 为缺失能力生成 `UE-*` / `UI-*` 候选项；
11. 生成需求 memory、V2 JSON Spec、应用快照和待确认项。

### 9.2 截图规则

截图保存在：

~~~text
apps/<app_slug>/requirement/assets/
~~~

建议命名：

~~~text
step-001-login-page.png
step-002-date-filter.png
step-003-export-button.png
~~~

截图只在本地保存，不提交 GitHub。REQUIREMENT_MEMORY.md 使用相对路径关联截图，并记录原飞书块或图片标识和文件哈希。

新设备缺少本地截图时，AI 根据飞书需求文档重新下载。下载失败不能用旧截图猜测需求。

## 10. 应用身份和发现

### 10.1 AI 自动生成身份

AI 根据业务域、平台和用途自动生成：

- app_id；
- 程序名称；
- app_slug；
- Python 包名；
- 目标目录；
- 程序入口。

app_id 一旦写入需求 memory 就保持稳定。重新处理同一需求时必须复用。

生成前扫描 apps/*/app.toml 和目标目录：

- ID 冲突时停止；
- 目录存在时停止；
- 不覆盖、不合并、不删除；
- 向开发人员说明冲突和建议操作；
- 只有开发人员明确授权现有应用变更流程后才能继续。

### 10.2 app.toml

示例：

~~~toml
schema_version = 2
app_id = "sales.taobao.sycm_store_daily"
app_slug = "sales_taobao_sycm_store_daily"
name = "生意参谋店铺销售日报"
version = "0.1.0"
entrypoint = "sales_taobao_sycm_store_daily.cli:main"
python = "3.12"
requirement_revision = 484
requirement_hash = "sha256:..."
configuration_schema = "config/config.schema.json"
catalog_lock = "catalog.lock.json"
status = "draft"
latest_review = ""

[commands]
doctor = "rpa-app doctor"
check = "rpa-app check"
test = "rpa-app test"
preview = "rpa-app run --mode preview"
live = "rpa-app run --mode live"
resume = "rpa-app resume"
login = "rpa-app login"
verify_candidates = "rpa-app verify-candidates"
~~~

app.toml 不保存店铺、账号、凭据和本机路径。V1 清单继续可以读取；新应用必须使用 V2，且 V2 必须声明快照锁与两个候选验证命令。

### 10.3 应用扫描

仓库不维护第二份中心注册表。发现应用时直接扫描 apps/*/app.toml，并验证：

- app_id 唯一；
- 目录、slug 和 Python 包一致；
- 程序入口存在；
- 需求 memory 和 JSON Spec 一致；
- pyproject.toml 和 uv.lock 完整；
- 标准命令存在；
- V2 catalog.lock.json 存在且包内资产哈希一致；
- 审核状态和最近审核引用有效。

## 11. 双份需求记忆

每个应用必须生成：

~~~text
requirement/REQUIREMENT_MEMORY.md
requirement/requirement.spec.json
~~~

### 11.1 REQUIREMENT_MEMORY.md

这是开发人员阅读和人工修正需求的唯一入口，包含：

- 飞书文档来源和 revision；
- 应用身份；
- 结构化业务目标；
- 有序操作步骤；
- 输入、输出和成功条件；
- 条件、循环和异常处理；
- 截图映射；
- 元素、指令和应用快照状态；
- 待确认项和开发人员结论；
- 需求变更历史；
- 对应程序版本和测试状态。

### 11.2 requirement.spec.json

这是 AI 和框架读取的机器格式，由 AI 从 REQUIREMENT_MEMORY.md 生成，开发人员不得直接修改。

示例骨架：

~~~json
{
  "schema_version": 2,
  "source": {
    "document_id": "redacted",
    "revision": 484,
    "requirement_hash": "sha256:..."
  },
  "application": {
    "app_id": "sales.taobao.sycm_store_daily",
    "entrypoint": "sales_taobao_sycm_store_daily.cli:main"
  },
  "steps": [
    {
      "id": "download_sales_file",
      "name": "下载销售明细",
      "action": "download",
      "inputs": ["date_range"],
      "outputs": ["sales_xlsx"],
      "success_conditions": ["download_completed", "workbook_schema_valid"],
      "element_refs": ["taobao.sycm.sales.export_button"],
      "instruction_refs": ["taobao.sycm.export_sales"],
      "unresolved_instruction_ids": [],
      "pending_confirmation_ids": []
    }
  ],
  "outputs": [],
  "pending_confirmations": [],
  "unresolved_elements": [],
  "unresolved_instructions": []
}
~~~

JSON 必须通过公共 JSON Schema。Schema 放在 rpa-core 中并带版本号。

### 11.3 一致性门禁

两份文件包含相同需求哈希和字段映射。

如果不一致：

- 立即停止生成或修改；
- 输出字段级和步骤级差异；
- 不修改代码；
- 不运行真实测试；
- 不自行选一份文件覆盖另一份；
- 通知开发人员。

人工修改只改 REQUIREMENT_MEMORY.md。AI 展示 JSON 变更对比，开发人员确认后才重新生成 requirement.spec.json 和哈希。

## 12. 需求变更

飞书 revision 变化时：

1. 读取最新版本；
2. 与已确认需求 memory 比较；
3. 生成 REQUIREMENT_CHANGE_PROPOSAL.md；
4. 标明新增、修改、删除步骤；
5. 分析元素、代码、检查点和测试影响；
6. 通知开发人员；
7. 开发人员确认前不更新需求基线、不修改程序。

开发人员确认需求变更后：

1. 更新 REQUIREMENT_MEMORY.md；
2. 展示 requirement.spec.json diff；
3. 确认后重新生成 JSON；
4. 生成代码修改方案和 diff；
5. 再次得到开发人员确认；
6. 增量修改现有代码。

不区分 AI 代码和人工代码。首次生成以后，AI 不得按模板整文件重建应用，必须保留已有人工修复和优化。

## 13. AI 应用生成规则

### 13.1 首次生成

AI 必须生成完整应用，不因局部信息缺失而停止在半成品结构：

- 完整步骤顺序；
- Program 和 Step 定义；
- ExecutionContext 调用；
- 输入输出模型；
- 成功条件；
- 检查点和恢复策略；
- 自动测试；
- 候选元素；
- 待确认项；
- README；
- GENERATION_REPORT.md；
- app.toml 和标准命令。

### 13.2 默认 Git 行为

AI 默认：

- 不创建分支；
- 不提交；
- 不推送；
- 不创建 Pull Request；
- 不部署。

AI 在当前工作区生成草稿。生成前检查已有修改并保护开发人员工作。

### 13.3 现有应用变更

必须分两阶段：

第一阶段只读：

- 比较需求、JSON Spec 和当前代码；
- 生成文件级和步骤级修改方案；
- 展示 diff；
- 标明公共包、检查点和测试影响；
- 不修改文件。

第二阶段授权修改：

- 开发人员确认方案；
- AI 按确认内容增量修改；
- 保留已有优化；
- 更新测试和生成报告；
- 自动运行无副作用测试；
- 等待真实测试授权。

## 14. 待确认项

### 14.1 PendingConfirmation

用于业务规则、输入、输出、成功条件或异常处理不明确的情况。

~~~python
PendingConfirmation(
    id="PC-003",
    requirement_step="步骤 5",
    question="导出后是否会出现二次确认弹窗？",
    risk="可能导致下载步骤等待超时",
    source_image="requirement/assets/step-005-export.png",
    blocks_push=True,
)
~~~

必须记录稳定 ID、来源、问题、风险、影响门禁和开发人员结论。

### 14.2 UnresolvedElement

元素库没有对应元素时：

~~~python
UnresolvedElement(
    id="UE-003",
    requirement_step="步骤 4",
    platform="taobao.sycm",
    page="销售概况",
    name="导出按钮",
    screenshot="requirement/assets/step-004-export.png",
    reason="公共元素库中没有匹配元素",
    resolution="等待开发人员指定或授权补抓",
)
~~~

AI 不根据截图编造 XPath 或 CSS。未解析元素仍然放进完整步骤流程。

### 14.3 UnresolvedInstruction

顶层指令库没有对应能力时，使用稳定 `UI-*` 对象记录需求步骤、平台、能力、缺失原因、候选实现、Fake 测试、真实测试和证据状态。

```python
UnresolvedInstruction(
    id="UI-003",
    requirement_step="步骤 4",
    platform="taobao.sycm",
    capability="导出销售明细",
    reason="顶层指令库无已验证实现",
    status="candidate",
    candidate_instruction_ref="taobao.sycm.export_sales",
    candidate_implementation="src/app/instructions/taobao/sycm/export_sales/instruction.py",
    fake_test_ref="tests/test_candidate_export_sales.py",
    fake_test_status="passed",
)
```

候选状态允许 doctor 和无副作用测试，但阻止正常真实运行、审核和推送。只有稳定指令引用、真实测试通过及证据齐全时才能标记 resolved。

任何未解决 PendingConfirmation、UnresolvedElement 或 UnresolvedInstruction 都阻止审核通过、提交和推送。

## 15. 元素库

### 15.1 组织方式

顶层元素源库按以下层级：

~~~text
elements/<platform>/<product>/<page>/<component>.toml
~~~

例如：

~~~text
taobao → sycm → sales_overview → date_picker → START_DATE_INPUT
~~~

元素库只保存定位描述，不保存实时 DOM 对象、店铺数据和业务凭据。

### 15.2 ElementSpec

~~~python
@dataclass(frozen=True, slots=True)
class ElementSpec:
    id: str
    name: str
    page: str
    component: str | None = None
    locator: Locator | None = None
    frame_locator: Locator | None = None
    option_locator: Locator | None = None
~~~

要求：

- id 稳定唯一；
- name 使用可理解中文；
- locator 为空时显式表示未解析元素，真实适配器必须失败关闭；
- frame_locator 只保存已验证 iframe 定位描述，适配器在每次动作前重新解析 frame；
- option_locator 只保存输入型自定义下拉的通用选项定位，不拼接运行时业务值；适配器在同一 frame 内按可见文本精确匹配；
- 默认不缓存 DOM；
- 定位器优先稳定属性、可访问性属性和组件内相对定位；
- 绝对 XPath 和深层位置序号只能临时使用并写说明。

### 15.3 候选元素流程

新元素先进入应用内快照目录：

~~~text
需求截图识别
→ 生成候选元素或 UnresolvedElement
→ 开发人员授权真实流程测试
→ 补抓 DOM
→ 验证唯一、显示、可点击和刷新稳定性
→ 完成端到端测试
→ 提出迁入顶层 elements/ 的独立 diff
→ 当前应用保持冻结副本或经确认执行显式升级
→ 回归测试受影响应用
~~~

测试通过前不得并入顶层源库。候选元素保存在应用自己的 `src/<python_package>/elements/`，并以 `application_candidate/candidate` 条目写入 `catalog.lock.json`。

### 15.4 Python 指令库

公共指令表示可独立验证、可跨应用复用的稳定能力：

```text
instructions/<platform>/<product>/<capability>/
├── instruction.toml
└── instruction.py
```

一条指令必须声明稳定 ID、语义版本、平台、输入、输出、依赖元素、前置条件、成功条件和副作用等级。实现继承 `Instruction`，通过 `ExecutionContext` 调用 BrowserActions 或其他受控服务，并提供独立 `verify()`。指令不得包含店铺专属规则、真实品牌、日期范围或应用输出策略，也不得写 Step 检查点。

### 15.5 应用快照

`snapshot_catalog()` 扫描顶层源库，解析 `element:<id>` / `instruction:<id>` 依赖闭包，将实际使用项复制到应用包内，并生成 `catalog.lock.json`。锁条目固定类型、ID、版本、状态、来源、目标、依赖、复制时间和内容哈希；复制时间不参与内容一致性判断。

运行时只校验应用副本，拒绝文件缺失、哈希漂移、未知依赖、循环、路径逃逸、符号链接和硬链接。Python 导入指令目录后生成的 `__pycache__`、`.pyc` 和 `.pyo` 不属于资产内容，不参与复制或哈希；其他额外文件仍会造成完整性失败。顶层源库之后的变化不会改变已有应用；升级必须先展示来源版本、哈希和文件 diff，再经开发人员确认和回归测试。

## 16. 核心程序模型

### 16.1 ProgramSpec

~~~python
@dataclass(frozen=True, slots=True)
class ProgramSpec:
    app_id: str
    program_id: str
    version: str
    requirement_hash: str
    name: str = ""
~~~

一个应用只注册一个 Program。Program ID 与 app_id 保持稳定映射。

### 16.2 BaseProgram

~~~python
class BaseProgram:
    def __init__(self, spec: ProgramSpec, steps: Sequence[Step]): ...

    def prepare(self, ctx: ExecutionContext) -> None:
        """校验输入、配置、账号、目录和外部依赖。"""

    def verify(self, ctx: ExecutionContext) -> bool | None:
        """程序级最终结果验证。"""

    def cleanup(self, ctx: ExecutionContext) -> None:
        """释放本次资源，不决定浏览器进程策略。"""
~~~

标准生命周期：

~~~text
准备 → 执行业务步骤 → 验证最终结果 → 清理本次资源
~~~

### 16.3 StepSpec

每一步声明：

- 稳定步骤 ID；
- 业务名称；
- 输入；
- 输出；
- 成功条件；
- 超时；
- 重试策略；
- 恢复策略；
- 外部副作用类型。

~~~python
@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    name: str
    retry_policy: RetryPolicy
    resume_policy: ResumePolicy
    side_effect: SideEffect
    timeout_seconds: float | None
    declared_inputs: tuple[str, ...]
    declared_outputs: tuple[str, ...]
    success_conditions: tuple[str, ...]
    recovery: tuple[str, ...]
~~~

### 16.4 ExecutionContext

运行身份（含 `requirement_hash`）、运行目录、服务注册表、输出和协作式步骤 deadline 已实现；`instructions` 已提供类型化注册表入口。浏览器、Excel、数据库、密钥和产物继续通过对应的受控服务入口扩展。

~~~python
@dataclass(slots=True)
class ExecutionContext:
    run: RunInfo
    account: AccountInfo
    settings: Settings
    browsers: BrowserSessionRegistry
    excel: ExcelService
    feishu: FeishuService
    database: DatabaseService
    checkpoints: CheckpointStore
    artifacts: ArtifactStore
    logger: RunLogger
    secrets: SecretProvider
    approvals: ApprovalContext

    @property
    def instructions(self) -> InstructionRegistry:
        """当前应用包内注册的冻结指令集合。"""

    @property
    def browser(self) -> BrowserActions:
        """默认账号浏览器。"""

    def output_of(self, step_id: str, key: str) -> JsonValue: ...
~~~

ExecutionContext 是业务代码访问外部世界的唯一入口。

### 16.5 业务代码边界

允许业务程序自由编排。跨应用复用的稳定动作优先通过指令注册表调用：

~~~python
result = ctx.instructions.execute(
    "example.orders.search",
    ctx,
    {"date_range": date_range},
)
~~~

禁止：

~~~python
page.ele(...).click()
~~~

apps 目录不能直接导入 DrissionPage、底层飞书客户端、Excel 驱动或数据库驱动。

复制到应用的指令也受同一架构扫描约束。指令完成 `verify()` 后只返回声明输出；调用它的 Step 仍要执行自己的成功条件，并且只有 Step 验证成功后才能写检查点。

## 17. 浏览器包装和 DrissionPage

当前项目使用 DrissionPage 4.x。`rpa-core 0.7.0` 已落地的公共 BrowserActions 为：

~~~python
class BrowserActions(Protocol):
    def open(self, url: str, *, wait: str = "document") -> None: ...
    def exists(self, element: ElementSpec, *, timeout=0) -> bool: ...
    def click(self, element: ElementSpec) -> None: ...
    def input(self, element: ElementSpec, value: SecretLike) -> None: ...
    def text(self, element: ElementSpec) -> str: ...
    def select(self, element: ElementSpec, value: SecretLike) -> None: ...
    def download(self, element: ElementSpec, *, filename=None) -> DownloadRef: ...
    def screenshot(self, *, name=None, full_page=False) -> ArtifactRef: ...
~~~

`ElementSpec.frame_locator` 提供受控 iframe 上下文：每次元素动作先从托管 Tab 重新获取 frame，再在 frame 内重新定位目标。标准 `AuthorizedBrowserActions` 会在调用前后校验 top-level Origin，并校验 active Session、Step、Action 和 Element；固定内部工具流程中的 iframe 由冻结 locator 约束，不再单独执行 Origin allowlist。DrissionPage adapter 仍保留可选的 same-context guard 能力，供风险模型更严格的集成显式使用，但标准 wrapper 不注入。`text()` 对普通元素返回可见文本，对 `input` 返回当前 `value`。`select()` 对原生 `select` 使用精确文本选择；输入型自定义下拉若配置 `option_locator`，则在同一 frame 内等待选项并按“显示、启用、可点击、可见文本完全一致”筛选，只有唯一命中才点击；未配置时保留 Enter 兼容行为。多选组件可同时配置 `selected_option_locator`、`popup_locator` 和 `dismiss_locator`：适配器按真实 checkbox 状态移除所有非目标项、补选唯一目标项，随后点击不受浮层遮挡的安全关闭目标，并确认浮层不可见后才返回。0 命中、多命中、额外选中项无法清除、浮层未关闭和未知标签都失败关闭，运行时值不写入日志或定位器。`find`、`find_all`、标签页和显式 frame 上下文管理器仍属于后续扩展。

包装器自动完成：

- 动作时重新定位元素；
- 等待显示、可点击或目标条件；
- 记录页面、元素、动作和耗时；
- 输入值脱敏；
- 异常分类；
- 失败截图；
- 下载目录隔离；
- 将底层异常转换为框架异常。

DrissionPage 当前提供 ChromiumOptions.set_browser_path、set_local_port、set_user_data_path 和 Chromium 连接能力，下载可通过任务对象等待，页面和元素支持截图。

底层 DrissionPage 类型只能存在于：

- rpa-core 的 browser actions 和 runtime；
- 少量经过审核的平台 adapters；
- 对应底层测试。

业务应用不能调用 browser.quit。浏览器生命周期由 BrowserManager 决定。

## 18. 浏览器生命周期和多店铺并发

### 18.1 生命周期策略

~~~python
class BrowserLifecyclePolicy(Enum):
    KEEP_OPEN = "keep_open"
    REUSE_UNTIL_IDLE = "reuse_until_idle"
    TERMINATE_ON_FINISH = "terminate_on_finish"
~~~

- 本地开发和人工验证默认 KEEP_OPEN；
- 统一机器可使用 REUSE_UNTIL_IDLE；
- 只有明确配置才在任务结束后关闭；
- Profile 持久保存 Cookie 和登录态；
- 业务程序不负责关闭浏览器。

### 18.2 店铺隔离

~~~text
一个平台账号或店铺
= 一个 Chrome 进程
+ 一个持久化用户数据目录
+ 一个调试端口
+ 一把 Profile 排他锁
~~~

同一台物理机可以并发运行多个店铺。不同店铺不得共享 Profile。

### 18.3 端口池

PortPool：

1. 获取机器级端口池锁；
2. 排除已租用和正在监听的端口；
3. 写入 run_id、进程 ID、Profile ID 和租约时间；
4. 启动或连接浏览器；
5. 定期续租；
6. 浏览器退出后释放。

业务程序不得硬编码调试端口。

### 18.4 Profile 锁

- 同一 Profile 只能被一个 Chrome 进程使用；
- 并发请求相同 Profile 时排队或明确失败；
- 锁记录机器、进程、运行和心跳；
- 清理陈旧锁前先确认进程不存在；
- KEEP_OPEN 或复用期间由 BrowserManager 继续持锁。

## 19. 店铺配置、凭据和脱敏

### 19.1 本地配置

一个应用通过配置支持多个店铺。账号密码集中在应用本地 .env：

~~~dotenv
STORE_001_USERNAME=...
STORE_001_PASSWORD=...
STORE_002_USERNAME=...
STORE_002_PASSWORD=...
~~~

店铺映射保存在 config/stores.local.toml。真实 .env 和 stores.local.toml 都不提交。

可提交的 .env.example 和 stores.example.toml 只能使用通用占位符，不能暴露真实店铺名称、账号提供人或公司内部命名。

### 19.2 SecretProvider

业务代码通过：

~~~python
username = ctx.secrets.get(ctx.account.username_secret)
password = ctx.secrets.get(ctx.account.password_secret)
~~~

应用不得自行读取 .env。SecretProvider 负责加载、必填检查和日志脱敏。

### 19.3 可提交文件脱敏

所有可提交内容必须：

- 真实店铺名转稳定别名；
- 账号提供人转角色或匿名标识；
- 账号、手机号、邮箱、Token 和 Cookie 删除或掩码；
- 业务样例替换成等价模拟数据；
- 本机路径和机器信息使用变量。

脱敏范围包括需求 memory、JSON Spec、源码、测试、README、生成报告、变更方案和审核记录。

## 20. 步骤状态机、检查点和恢复

~~~mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RUNNING
    RUNNING --> VERIFYING: run 返回
    RUNNING --> RETRY_WAIT: 可重试异常
    VERIFYING --> RETRY_WAIT: 可重试验证失败
    RETRY_WAIT --> RUNNING: 尚有重试次数
    VERIFYING --> SUCCEEDED: 验证通过并原子保存检查点
    RUNNING --> FAILED: 不可重试或次数耗尽
    VERIFYING --> FAILED: 不可重试或次数耗尽
    SUCCEEDED --> [*]
    FAILED --> [*]
~~~

### 20.1 恢复规则

- 已成功且版本兼容的步骤不重跑；
- 从第一个未成功步骤继续；
- 失败步骤有外部副作用时先验证结果；
- 已产生有效结果则补写检查点；
- 不提供无证据 SKIP；
- 不可安全恢复的步骤要求人工确认。

### 20.2 ResumePolicy

~~~python
class ResumePolicy(Enum):
    VERIFY_THEN_RUN = "verify_then_run"
    ALWAYS_RUN = "always_run"
    MANUAL = "manual"
~~~

### 20.3 检查点

初期使用文件实现，后续通过 CheckpointStore 切换数据库。

~~~json
{
  "schema_version": 1,
  "run_id": "01J...",
  "app_id": "sales.taobao.sycm_store_daily",
  "program_version": "0.1.0",
  "account_id": "STORE_001",
  "mode": "preview",
  "steps": {
    "login": {
      "status": "succeeded",
      "attempts": 1,
      "outputs": {
        "login_state": "authenticated"
      }
    },
    "download_sales_file": {
      "status": "failed",
      "attempts": 2,
      "error_code": "DOWNLOAD_TIMEOUT"
    }
  }
}
~~~

检查点只在成功条件通过后写入，必须原子替换，不保存密码、Cookie、Token 或实时 DOM。阶段 2 还要求运行目录精确绑定到应用与安全 `run_id`，checkpoint/event 及路径型服务与同一运行身份绑定，并拒绝最终文件的符号链接和硬链接。同一 `run_id` 从读取检查点到 cleanup 与最终保存必须持有跨进程排他锁。

## 21. 写入预览和授权模型

### 21.1 自动允许的测试

AI 生成后可自动运行：

- 单元测试；
- Fake Browser、Fake Excel、Fake Feishu 和 Fake Database；
- 语法、类型和静态检查；
- ID 唯一性；
- 架构边界；
- 敏感信息和误提交扫描；
- 检查点与恢复测试。

### 21.2 真实浏览器授权

开发人员明确允许前，AI 不得：

- 打开真实浏览器；
- 登录真实平台；
- 点击、查询、下载或提交真实页面；
- 访问真实飞书、数据库和正式 Excel；
- 发送真实飞书告警。

未授权时报告必须写“等待开发人员授权”，不能声明真实测试通过。

所有 Real Browser invocation 使用 application-local `AuthorizationRecord`：先 request 不可变的 exact `AuthorizationScope`，Developer 核对 `scope_digest` 后短时 grant，执行入口在 Browser launch 前 atomic claim。Record 是 single-use；Scope 固定 Application/Program Version、Requirement/Catalog Digest、Operation、Mode、Run、Account、Profile fingerprint、Allowed Origins、Steps、Browser Actions、Elements、Candidate Assets 与 External Writes。Resume 必须使用新的 Record，并绑定 canonical Checkpoint Digest 和首个 recovery Step；Runner 在持有 run lock、重新读取 Checkpoint 后且在 `Program.prepare()` 前再次核对。完整决策见 ADR-027。

应用可以额外提供面向开发人员的交互式 Preview convenience command。它把 `request → grant → claim → run` 编排成一条命令和一次 TTY 确认；确认页只需显示 Account、会发生的真实动作和 `external_writes`。完整 exact scope 仍持久化在 Authorization Record，并可通过显式 request 命令检查。快捷入口不得创建可复用 grant、接受 `--yes` 或供无人值守流程自动授权；取消必须 revoke request，CI 和 Scheduler 仍使用显式 request/grant。

### 21.3 Preview 模式

开发人员首次授权真实流程测试后默认使用 preview：

- 浏览器读取、筛选、查询和下载可以真实执行；
- 页面提交、飞书、数据库、正式 Excel 和 NAS 写入被拦截；
- 按真实目标格式生成本地预览；
- 校验字段、类型、唯一键、覆盖范围、记录数量和目标位置；
- 报告明确标记“写入未执行”。

~~~text
runs/<run_id>/write-previews/
├── feishu-base-upsert--<step_id>.json
├── result-preview.xlsx
└── database-operation-plan.json
~~~

### 21.4 Live 模式

预览通过后，开发人员可以单独授权一次真实写入。授权限定：

- 应用和运行 ID；
- 店铺或账号；
- 写入目标；
- 写入步骤；
- 数据范围和预计记录数；
- 仅本次运行有效。

Live invocation 使用与 Preview 分开的 Developer grant，并包含 exact nested External Write scopes；adapter 在真正写入前逐条 atomic claim。写入后必须按 exact Target 与 Data Scope 独立 Read-back，只有 Record Count 与 canonical Payload Digest 都匹配才标记 `SUCCEEDED`；缺少回读能力时写前拒绝，写后无法确定结果时持久化 `UNKNOWN` 且不可重放。生成了预览不能写成真实写入成功。

## 22. 标准命令

每个应用注册：

~~~toml
[project.scripts]
rpa-app = "<python_package>.cli:main"
~~~

统一支持：

~~~bash
uv sync
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
uv run rpa-app preview --account <account>  # optional interactive convenience command
uv run rpa-app login
uv run rpa-app verify-candidates
uv run rpa-app run --mode preview
uv run rpa-app run --mode live
uv run rpa-app resume --run-id <run_id> --mode preview
uv run rpa-app resume --run-id <run_id> --mode live
~~~

| 命令 | 责任 |
| --- | --- |
| doctor | 检查 Python、Chrome、配置、目录、依赖和本地权限 |
| check | 检查需求一致性、待确认项、元素、指令、快照哈希和架构边界 |
| test | 运行无外部副作用测试 |
| preview convenience | 交互展示 Account、真实动作和 `external_writes`，经一次明确确认后编排单次 Preview Authorization 与执行 |
| login | 在单独授权下建立或确认指定持久化 Profile 的登录态 |
| verify-candidates | 在单独授权下逐条验证候选元素和候选指令 |
| preview | 执行已授权的真实读取和下载，拦截业务写入 |
| live | 执行被单独授权的真实写入 |
| resume | 从失败步骤恢复，仍受 preview 或 live 约束 |

`run` 和 `resume` 不能依赖开发人员先手动执行 `check`；命令必须在创建运行目录前自动执行同一套需求一致性、开放待确认项、应用身份、快照完整性、架构和敏感信息门禁。候选验证只能走 `verify-candidates`，不得关闭正常 `run` 的阻塞规则。

## 23. Excel、飞书和数据库集成

### 23.1 Excel

~~~python
class ExcelService(Protocol):
    def read_table(self, path, *, sheet, header_row=1) -> TableData: ...
    def write_table(self, path, data, *, sheet, mode="replace") -> None: ...
    def assert_workbook(self, path, *, required_columns, min_rows=0) -> None: ...
    def atomic_update(self, source, updater, *, backup=True) -> Path: ...
~~~

统一处理文件占用、临时文件、原子替换、日期和数据类型、空行、公式策略、工作表缺失和错误上下文。

preview 模式只生成本地 result-preview.xlsx，不覆盖正式文件。

### 23.2 飞书多维表格

~~~python
class FeishuBaseService(Protocol):
    def query(self, base, table, *, filters) -> list[Record]: ...
    def upsert(self, base, table, records, *, unique_by) -> UpsertResult: ...
    def batch_update(self, base, table, records) -> BatchResult: ...
~~~

统一处理认证、分页、限流、重试、批量大小、错误翻译和业务唯一键。

preview 模式输出目标字段和 upsert JSON，不发送写请求。

### 23.3 数据库

数据库集成负责连接、事务、参数化查询、批次号和幂等。公共页面每日抓取数据优先查数据库，减少重复浏览器操作。

preview 模式只生成参数化操作计划，不执行写 SQL。

## 24. 异常、日志和告警

### 24.1 异常分类

~~~text
RpaError
├── ConfigurationError
├── AuthenticationError
├── HumanVerificationRequired
├── ElementLookupError
├── ElementActionError
├── NavigationError
├── DownloadError
├── IntegrationError
├── BusinessValidationError
└── InfrastructureError
~~~

异常记录稳定错误码、是否可重试、应用、运行、店铺、步骤、元素上下文、证据和原始异常链。

滑块、短信和人机验证只检测和告警，不尝试绕过。

### 24.2 结构化事件

至少包括：

~~~text
run.started
run.prepared
step.started
action.started
action.succeeded
action.failed
locator.fallback_used
step.retrying
step.succeeded
step.failed
run.verifying
run.succeeded
run.failed
run.cleaned
~~~

### 24.3 失败证据

最终失败保存：

- 页面截图；
- URL 和标题；
- 失败步骤和元素；
- 脱敏 Root Cause、Exception Chain 和结构化 Traceback；
- repo-relative `file`、`line`、`function` 和安全 `code`；
- 最近动作；
- 下载状态；
- 可选脱敏页面信息。

### 24.4 飞书告警

已确认主格式：

~~~text
程序名称 -（店铺名称）- 失败步骤 - 错误信息 - 截图
~~~

本地运行告警可以使用真实店铺显示名，可提交报告必须使用脱敏别名。

发送告警本身属于真实外部操作，AI 自动测试时不得发送；使用 Fake Bot 验证格式。

## 25. GENERATION_REPORT.md

每次生成或修改都更新，至少包含：

- 飞书需求链接和 revision；
- app_id、名称和生成时间；
- 识别出的完整业务步骤；
- 新增和修改文件；
- 复用、新增和候选元素、指令及快照哈希；
- 待确认项及风险；
- 已执行、通过、失败和未执行的测试；
- 真实浏览器授权和结果；
- Preview 产物；
- Live 写入授权和结果；
- 是否满足审核、提交和推送条件；
- 最近审核记录引用。

报告必须区分：

- 代码生成完成；
- 无副作用测试通过；
- 真实浏览器 Preview 通过；
- Live 写入验证通过；
- RPA 开发审核通过；
- 业务迁移验收通过。

这些状态不能相互替代。

## 26. 审核和留痕

### 26.1 状态

AI 可以设置：

- draft；
- pending_confirmation；
- ready_for_test；
- test_failed；
- ready_for_review。

只有 RPA 开发人员可以确认：

- approved；
- ready_for_push。

### 26.2 自然语言审核

不要求审核命令。开发人员可以表达：

- “这个应用审核通过”；
- “真实测试通过，可以推送”；
- “审核不通过，下载步骤需要修改”。

AI 必须确认语言明确，并确认当前应用、需求哈希和测试运行 ID 在审核范围内。

“看起来可以”“应该没问题”等模糊表达不视为审核通过。

应用开发者和最终审核人可以是同一人，也可以由其他 RPA 开发人员复核。

### 26.3 审核文件

每次审核生成不可覆盖记录：

~~~text
reviews/2026-08-25T143000+0800.toml
~~~

记录：

- 审核人；
- 审核时间；
- 结论；
- 需求哈希；
- 应用版本；
- 测试运行 ID；
- 自动测试和真实测试结果；
- 外部写入验证状态；
- 非阻塞说明；
- 被审核文件摘要哈希。

需求或代码变化后，旧审核失效但记录保留。

## 27. 提交和推送门禁

默认不创建分支、不提交、不推送、不创建 PR、不部署。

提交和推送前必须同时满足：

- 所有 PendingConfirmation 已关闭；
- 所有 UnresolvedElement 已解析并测试；
- 所有 UnresolvedInstruction 已解析并完成真实验证；
- catalog.lock.json 与应用元素/指令副本一致；
- 自动测试全部通过；
- 真实浏览器流程已授权并完成；
- 所有外部写入至少完成格式预览；
- 需要 Live 验证的步骤已单独授权并验证；
- GENERATION_REPORT.md 已更新；
- RPA 开发人员明确审核通过；
- app.toml 为 ready_for_push。

任一项不满足都禁止提交和推送。

满足条件后：

- 开发人员可以手动提交和推送；
- 或明确授权 AI 代为操作。

AI 代为操作前展示精确文件清单、测试结果、提交信息、远程分支和无关工作区修改。只提交目标应用和确认过的公共包修改。

## 28. 应用测试策略

### 28.1 单元测试

使用假服务验证：

- 步骤顺序；
- 分支和循环；
- 输入输出；
- 成功条件；
- 重试和恢复；
- preview 写入拦截；
- 敏感信息不进入日志；
- 指令声明输入输出、独立验证和稳定错误；
- 候选指令 Fake Browser 行为。

### 28.2 架构测试

扫描：

- apps 不得导入 DrissionPage；
- apps 不得直接导入底层飞书、Excel 或数据库驱动；
- 禁止 page.ele().click()；
- app_id、Program ID 和步骤 ID 唯一；
- 禁止提交 .env、stores.local.toml、截图、Profile 和运行产物；
- app.toml、需求 memory 和 JSON Spec 一致；
- 应用不得从顶层 elements/instructions 导入；
- 复制指令不得导入 DrissionPage；
- V2 快照锁、依赖闭包、内容哈希和候选条目一致。

### 28.3 公共包契约测试

- 底层异常转换正确；
- run_id 和 step_id 自动关联；
- 检查点只有验证成功后写入；
- Excel 原子更新失败保留原文件；
- 飞书 upsert 按唯一键防重；
- preview 模式无真实写入。
- 指令注册表不写 Step 检查点；
- Catalog 拒绝重复 ID、未知依赖、循环、路径逃逸、符号链接和硬链接；
- 修改顶层源库不改变已有应用副本。

### 28.4 真实平台测试

必须由开发人员明确授权。候选阶段先走 `verify-candidates`，按需求步骤逐条确认页面身份、元素唯一性/可见/可点击/刷新稳定性和指令结果；完整业务流程再走 Preview。

验证码和短信仅检测并提示人工处理。

## 29. 运行目录

运行时数据不进入 Git。Windows 建议：

~~~text
D:\RPAData\
├── profiles\<platform>\<account_id>\
├── apps\<app_id>\
│   ├── runs\<run_id>\
│   │   ├── run.json
│   │   ├── artifacts\
│   │   ├── downloads\
│   │   ├── write-previews\
│   │   └── temp\
│   └── checkpoints\<account_id>\
├── screenshots\<app_id>\<run_id>\
├── logs\<date>\
├── locks\
└── port-leases\
~~~

所有路径由 RuntimePaths 生成。应用不能硬编码 D:\RPAData。

阶段 2 的已实现形态暂时使用仓库内、Git 忽略的 `apps/<app_slug>/runs/<run_id>/`，并以 POSIX `flock` 提供同运行排他；不支持的平台 fail-closed。迁移到上述 Windows 运行根目录前，必须由受信任的 `RuntimePaths` 配置取代任意路径输入，实现 Windows 等价锁并重新执行路径逃逸、并发与崩溃释放测试。

## 30. 影刀迁移验收

每个应用：

1. 固定输入范围和店铺；
2. 新旧程序同时运行一周；
3. 对比文件、行数、关键字段、汇总指标和飞书结果；
4. 明确允许差异规则；
5. 记录失败、人工介入和耗时；
6. 差异清零或得到业务确认后切换；
7. 按约定时间保留影刀回退方案。

开发完成、技术测试通过、RPA 开发审核通过和业务迁移验收通过是不同状态。

## 31. 当前仓库迁移边界

当前仓库没有 `src/drission_element_library`，也没有可恢复或迁移的历史业务应用。不得根据旧文档描述重建不存在的原型。

后续若从其他仓库迁入资产：

- 通用浏览器包装只进入 `packages/rpa-core`；
- 已真实验证的元素进入顶层 `elements/`；
- 已真实验证、可复用的 Python 能力进入顶层 `instructions/`；
- 应用只复制实际使用的依赖闭包并固定在自己的 `catalog.lock.json`；
- 登录状态判断作为可独立验证的指令或页面断言；
- 未完成真实验证的内容只能作为应用候选项；
- 新旧实现行为一致前不删除原来源。

## 32. 未来调度中心边界

框架提供稳定输入：

- app_id；
- account_id 或店铺列表；
- 业务参数；
- 触发来源；
- resume_run_id；
- preview 或 live 模式；
- 浏览器生命周期策略。

输出：

- run_id；
- 应用、店铺和步骤状态；
- 耗时；
- 错误码；
- 日志、截图和产物引用；
- 结构化事件。

调度中心通过扫描 apps/*/app.toml 发现应用，不解析日志猜状态，不重新实现应用生命周期。

调度和看板技术选型后续单独处理。

## 33. 视觉 Agent 扩展

未来视觉大模型只作为异常恢复：

1. 正常元素定位失败；
2. 保存页面和截图；
3. 根据应用策略请求 Agent；
4. Agent 返回建议动作和置信度；
5. 高风险提交、删除、支付和权限变更禁止自动执行；
6. 执行后仍使用原成功条件验证；
7. 保存 Agent 输入、决策和结果；
8. 将稳定修复迁入正式元素库。

初期预留接口但默认禁用。

## 34. 实施顺序

> 2026-09-03 状态：`rpa-core 0.7.0` 已具备 V1/V2 Contract、Instruction/Catalog Snapshot、Checkpoint/Resume、BrowserActions/BrowserManager，以及 durable exact-scope Authorization 和 Live independent Read-back Verification。标准 Browser Authorization 校验 top-level Origin、Step、Action 和 Element，固定内部业务 iframe 不再逐 Origin 授权。首个 Application 当前为 0.3.0，冻结 17 个 verified elements 和 7 个 verified instructions；运行 `preview-20260903T062356Z-df357a62` 已完成 S001–S005 和本地下载，Developer Review 已通过，状态为 `ready_for_push`。

### 阶段 1：需求协议和应用骨架

- 实现 app.toml Schema；
- 实现 REQUIREMENT_MEMORY 和 requirement.spec.json Schema；
- 建立独立应用模板；
- 实现应用扫描和冲突检测；
- 实现脱敏和误提交扫描；
- 保留用假需求生成完整示例应用的验收任务。

当前：公共 Contract 和 scanner 已实现；首个独立 Application 已完成资产晋升和 Snapshot 重建。0.2.0 历史 Review Record 保留；0.3.0 Real Preview 和 Developer Review 已完成，因此处于 `ready_for_push`。

### 阶段 2：核心运行闭环

- 实现 Program、Step、ExecutionContext；
- 实现状态机和文件检查点；
- 实现标准 CLI；
- 实现 preview/live 授权上下文；
- 实现 JSON 日志和生成报告。

当前：公共 Runtime、durable Authorization 和 redacted source-level Error Diagnostics 已完成包级回归；Application 0.3.0 的离线 Gate 与 Real Preview 已验证，Live 在该 Application 中保持 fail closed。

### 阶段 3：浏览器和元素

- 迁移现有 DrissionPage 原型；
- 实现 BrowserActions 最小契约与 Fake Browser（已完成）；
- 实现 DrissionPage 生产动作适配器（已完成并接入 BrowserManager）；
- 实现受控 iframe 定位、只读文本和输入型自定义下拉精确选项定位（已完成实现与离线测试）；
- 实现 Profile、端口和锁（公共 BrowserManager 已完成，等待真实 Chrome 集成验证）；
- 实现 InstructionRegistry、顶层元素/指令发现、依赖闭包、应用快照锁和 V2 候选门禁（已完成包级实现）；
- 实现候选元素/指令到顶层源库的显式升级流程；
- 保留本地浏览器 KEEP_OPEN。

当前验收边界：229 项无副作用测试覆盖公共 Contract、Snapshot Integrity、Architecture scan、top-level Origin 前后校验、固定 iframe 不单独授权、Resume under-lock binding、Live Read-back、Interactive Preview Authorization 编排，以及 Error Diagnostics 的 compact summary、full run-local JSON、Root Cause/Source Line 输出与 secret/path redaction。Application 0.3.0 运行 `preview-20260903T062356Z-df357a62` 已完成 S001–S005、本地下载和成功截图，且未执行 external business write；Developer Review 已通过。双账号并发和 Live 未验证，不属于当前应用提交范围。

### 阶段 4：Excel、飞书和告警

- 实现 .xlsx 服务；
- 实现飞书 Base API；
- 实现数据库协议；
- 实现飞书机器人；
- 实现格式预览和回读验证。

验收：preview 不写外部系统，live 单次授权后可写并验证。

### 阶段 5：首个真实应用

- 从当前需求模板读取需求；
- 下载截图；
- AI 生成完整应用；
- RPA 开发处理待确认项；
- 完成真实 Preview 和必要 Live；
- 形成自然语言审核记录。

前置条件：提供实际飞书需求文档 URL 和最新 revision；真实候选验证还需另行限定账号别名、Profile、站点、步骤和允许动作。公开登录页信息不能替代这些输入。

### 阶段 6：迁移扩展

- 选择 3～5 个不同类型程序；
- 新旧并行一周；
- 总结公共元素和集成模式；
- 开始多人并行生成和迁移；
- 评估是否需要专用 AI Skill。

### 阶段 7：调度接入

- 选择调度技术；
- 扫描 app.toml；
- 接入物理机容量和看板；
- 保持应用与调度产品解耦。

## 35. 关键决策记录

| 编号 | 决策 | 原因 |
| --- | --- | --- |
| ADR-001 | 一份需求对应一个应用和程序 | 保持需求、代码、依赖和审核边界清晰 |
| ADR-002 | 每个应用独立 .venv、pyproject.toml 和 uv.lock | 依赖隔离，支持独立运行部署 |
| ADR-003 | 公共框架在同一仓库，通过路径引用最新代码 | 复用运行时并避免复制核心包 |
| ADR-004 | 应用通过 app.toml 扫描发现，不维护中心注册表 | 避免双份注册信息不一致 |
| ADR-005 | 保持现有飞书需求模板 | 不增加提报人负担 |
| ADR-006 | 同时生成 Markdown memory 和 JSON Spec | 兼顾人工维护和机器稳定读取 |
| ADR-007 | 人工只编辑 Markdown，JSON 由 AI 生成 | 避免双入口冲突 |
| ADR-008 | 截图下载到应用但不提交 | AI 可本地使用，同时避免敏感图片入库 |
| ADR-009 | 信息不全仍生成完整草稿 | 尽快形成可审阅程序 |
| ADR-010 | 未知元素不从截图猜定位器 | DOM 定位必须真实验证 |
| ADR-011 | 新元素和指令真实测试后才并入顶层源库 | 避免污染后续应用 |
| ADR-012 | 不区分 AI 和人工代码区 | 应用代码统一增量维护 |
| ADR-013 | 默认不创建分支、不提交、不推送 | 审核测试完成前保持本地草稿 |
| ADR-014 | 真实浏览器必须开发人员授权 | 防止未经允许操作真实平台 |
| ADR-015 | 第一次真实测试默认 preview | 先验证输出格式，不直接写业务系统 |
| ADR-016 | Live 写入单独一次性授权 | 限定副作用范围 |
| ADR-017 | 所有待确认项解决后才能推送 | 不把不确定程序交给统一运行环境 |
| ADR-018 | 最终审核由开发人员自然语言确认 | 保留人类责任边界和使用便利 |
| ADR-019 | 一个应用通过本地配置支持多店铺 | 避免复制程序，支持并发 |
| ADR-020 | 店铺配置和需求可提交内容均脱敏 | 避免真实业务身份进入 Git |
| ADR-021 | 从失败步骤恢复 | 降低长流程重跑成本 |
| ADR-022 | 一店铺一进程一 Profile 一端口 | 避免登录态互相顶掉 |
| ADR-023 | 新旧程序并行一周 | 用真实结果完成迁移验收 |
| ADR-024 | 调度中心后置 | 当前聚焦 AI 生成和应用运行框架 |
| ADR-025 | 浏览器自动化底层选用 DrissionPage | 统一 Chromium 控制能力，并通过 BrowserActions 隔离业务应用与底层对象 |
| ADR-026 | 元素与指令使用应用快照 | 固定已测试行为，顶层更新通过显式 diff 升级 |

## 36. 后续阶段待确定

`app.toml` 与 `requirement.spec.json` 的 V1 Schema 继续兼容；V2 已增加 catalog lock、登录/候选验证命令、指令引用和 `UnresolvedInstruction`。后续字段扩展仍必须提升或兼容 Schema 版本，不能静默改变 V1/V2 语义。

- .xlsx 底层库及公式、样式保真范围；
- Windows 浏览器进程保活实现；
- 文件检查点升级数据库的时机；
- 日志和截图保留时间；
- 公共包变更的受影响应用分析算法；
- GitHub Actions 到 Windows 物理机的分发；
- 调度中心和看板技术选型；
- 视觉 Agent 模型、阈值和允许动作。

这些实现选择不得违反 AGENTS.md 和本文的应用独立性、授权、审核及推送门禁。

## 37. 参考资料

- DrissionPage 浏览器控制入门：https://drissionpage.cn/browser_control/intro
- DrissionPage 连接浏览器：https://www.drissionpage.cn/browser_control/connect_browser
- DrissionPage 浏览器选项：https://www.drissionpage.cn/browser_control/browser_options
- DrissionPage 下载管理：https://www.drissionpage.cn/download/browser
- DrissionPage 截图：https://www.drissionpage.cn/browser_control/screen
- uv 项目结构：https://docs.astral.sh/uv/concepts/projects/layout/
- uv 项目运行：https://docs.astral.sh/uv/concepts/projects/run/
- uv 路径依赖：https://docs.astral.sh/uv/concepts/projects/dependencies/
