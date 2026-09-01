# RPA 核心指令库与应用快照实施方案

> 状态：只读方案，等待 RPA 开发人员确认后实施
> 编制日期：2026-09-01
> 适用仓库：`kk-rpa-monorepo`
> 面向对象：后续执行修改的 Codex / RPA 开发 Agent

## 1. 文档用途与授权边界

本文将已经确认的架构决策转成可执行的文件级实施方案，供后续 Agent 按阶段修改仓库。

本文档本身不构成以下授权：

- 不授权修改本文之外的源码或设计文档；
- 不授权生成或覆盖任何已有应用；
- 不授权打开真实浏览器、登录业务平台、点击页面或下载业务文件；
- 不授权写入 NAS、飞书、数据库或正式 Excel；
- 不授权创建分支、提交、推送、创建 Pull Request 或部署。

执行 Agent 必须先读取仓库根目录 `AGENTS.md`。若用户尚未明确确认对应补丁，只能继续做只读检查，不能修改文件。

## 2. 已确认目标

第一阶段的最终目标是：开发人员把一份固定模板的飞书 RPA 需求文档交给 Codex，由 Codex 自动生成一个完整、独立、可测试、可审核和可运行的 Python RPA 应用。

目标闭环：

```text
输入飞书需求文档
→ 读取 revision、正文和步骤截图
→ 生成 Requirement Memory 和 JSON Spec
→ 检索顶层元素库与指令库
→ 将使用到的元素、指令及其依赖复制到应用
→ 为缺失能力生成应用级候选元素和候选指令
→ 生成独立 uv 应用、CLI、源码和测试
→ 自动运行无副作用测试
→ 开发人员处理登录和真实候选验证
→ Preview 运行真实浏览器流程
→ 返回经过验证的下载文件路径
```

本阶段不要求：NAS、飞书 Base、数据库、正式 Excel 写入、调度中心、业务看板或部署。

## 3. 已确认架构决策

### 3.1 AI 执行方式

- 使用 Codex 这类编码 Agent 直接读取需求文档并修改仓库；
- 不在 `rpa-core` 内实现调用大模型的 `rpa generate` 服务；
- 后续使用项目级生成 Skill 固化 Codex 的生成流程。

### 3.2 需求输入

- 继续使用现有、面向业务人员的飞书需求模板；
- 不要求提报人填写 JSON 或 YAML；
- 信息缺失时生成结构化待确认项，但仍生成完整应用草稿；
- 不允许仅凭截图猜测 DOM 定位器。

### 3.3 指令粒度

一条公共指令表示一个可独立验证、可跨应用复用的稳定能力，例如：

- 登录平台；
- 验证登录状态；
- 打开库存模块；
- 进入商品库存；
- 选择品牌；
- 执行搜索；
- 导出库存。

完整业务流程仍由应用的 Program 和 Step 编排。公共指令不得包含店铺专属规则、真实品牌、日期范围或应用专属输出策略。

### 3.4 指令实现方式

- 指令实现为 Python 类；
- 指令元数据必须机器可读；
- 不建设 JSON/YAML 解释执行 DSL；
- 指令可以使用 `ExecutionContext` 和 `BrowserActions`，但不能直接导入 DrissionPage；
- 指令不独立写检查点，检查点仍由调用它的应用 Step 管理。

### 3.5 顶层库与应用快照

- 元素源库位于仓库顶层 `elements/`；
- 指令源库位于仓库顶层 `instructions/`；
- 顶层库只保存经过真实验证的稳定内容；
- AI 生成应用时，把实际使用的元素、指令及依赖闭包复制到应用；
- 应用运行时只使用自己的冻结副本，不引用顶层元素或指令；
- 顶层库更新不会自动影响已有应用；
- 已有应用升级必须先展示来源版本、内容哈希和文件 diff，开发人员确认后才能替换。

`rpa-core` 不复制，继续通过 uv 本地路径依赖引用。顶层快照规则只适用于元素和平台指令。

### 3.6 缺失能力

顶层库没有匹配项时：

1. AI 在应用内生成完整候选元素和候选 Python 指令；
2. 生成对应 Fake Browser 测试；
3. 候选状态不阻止离线测试；
4. 候选状态阻止正常真实运行、审核和推送；
5. 开发人员明确授权后，使用单独的候选验证命令执行真实页面检查；
6. 真实端到端验证通过后，再提出回灌顶层库的独立 diff；
7. 回灌不能静默改写当前应用已经测试通过的副本。

### 3.7 登录解耦

- 登录实现为独立公共指令；
- 应用提供独立 `rpa-app login` 命令；
- 业务 `run` 不重复输入账号密码，只检查指定持久化 Profile 的登录状态；
- 登录指令负责判断已有登录态、读取本地凭据引用、执行登录、识别人机验证并验证成功；
- 验证码、滑块和短信只能检测、截图和转人工，不能绕过；
- 真实凭据只能存在于应用本地 `.env` 和本地店铺配置中。

## 4. 当前仓库基线

执行方案前已完成只读核对：

- 分支：`main`；
- 基线提交：`4ac40e0ed746ddd3e637e08db3d3940f79411fcf`；
- 工作区在核对时为干净状态；
- `rpa-core` 当前版本：`0.1.2`；
- Python：`3.12.13`；
- DrissionPage：`4.1.1.4`；
- Pydantic：`2.13.5`；
- uv：`0.11.28`；
- 当前 `rpa-core` 共有 102 项测试，全部通过；
- 当前 `apps/` 为空；
- 根 README 声称存在两个应用和历史验收结果，与当前文件系统不一致。

执行 Agent 必须重新核对这些状态，不得假设本方案编制后的工作区仍然相同。

## 5. 官方文档核对结论

实现前已经通过 Context7 核对当前官方文档：

- DrissionPage 仍支持通过 `ChromiumOptions` 设置浏览器路径、用户数据目录和本地调试端口；
- DrissionPage 支持设置下载目录、等待下载完成和页面/元素截图；
- uv 支持每个应用拥有独立 `pyproject.toml`、`.venv` 和 `uv.lock`；
- uv 支持通过 `[tool.uv.sources]` 声明本地路径依赖；
- `uv.lock` 应提交，不能手工编辑。

参考：

- https://github.com/g1879/drissionpage/blob/master/_autodocs/005_configuration_classes.md
- https://github.com/g1879/drissionpage/blob/master/_autodocs/010_advanced_features.md
- https://github.com/astral-sh/uv/blob/main/docs/concepts/projects/workspaces.md
- https://github.com/astral-sh/uv/blob/main/docs/concepts/projects/layout.md

实施时若版本或 API 发生变化，必须重新通过 Context7 或官方文档核对。

## 6. 目标目录结构

```text
kk-rpa-monorepo/
├── elements/
│   ├── README.md
│   └── <platform>/<product>/<page>/<component>.toml
├── instructions/
│   ├── README.md
│   └── <platform>/<product>/<capability>/
│       ├── instruction.toml
│       └── instruction.py
├── packages/
│   └── rpa-core/
│       └── src/rpa_core/
│           ├── catalog.py
│           └── instructions.py
└── apps/
    └── <app_slug>/
        ├── catalog.lock.json
        └── src/<python_package>/
            ├── elements/
            └── instructions/
```

顶层元素清单只保存定位描述和验证元数据，不保存实时 DOM、店铺配置、账号或凭据。

## 7. 分阶段实施顺序

实施拆成四个补丁。每个补丁完成后必须停止、报告并等待下一阶段所需的授权。

### 补丁 A：核心指令与快照契约

目标：只修改公共框架、Schema、验证器和架构文档，不生成业务应用，不打开真实浏览器。

#### A.1 新增文件

| 文件 | 内容 |
| --- | --- |
| `packages/rpa-core/src/rpa_core/instructions.py` | 指令运行契约、注册表及稳定错误 |
| `packages/rpa-core/src/rpa_core/catalog.py` | 顶层目录发现、应用快照锁加载及哈希验证 |
| `packages/rpa-core/tests/test_instructions.py` | 指令契约测试 |
| `packages/rpa-core/tests/test_catalog.py` | 目录与快照测试 |
| `elements/README.md` | 顶层元素库规则 |
| `instructions/README.md` | 顶层 Python 指令库规则 |
| `llm-wiki/07-instructions-and-snapshots.md` | 指令、Step、元素和快照边界 |
| `llm-wiki/decisions/ADR-026-application-catalog-snapshots.md` | 新的快照决策记录 |

#### A.2 修改文件

| 文件 | 精确修改范围 |
| --- | --- |
| `AGENTS.md` | 修改仓库结构、应用结构、元素晋升、指令候选、标准命令、审核和推送门禁 |
| `README.md` | 删除不存在应用的完成声明，增加真实基线、顶层库和新调用链 |
| `docs/rpa-framework-design.md` | 替换元素/平台包路径引用，新增指令层和快照生命周期，更新 ADR 表与实施顺序 |
| `llm-wiki/README.md` | 加入新专题和 ADR-026 |
| `llm-wiki/01-system-context.md` | 加入指令层和复制边界 |
| `llm-wiki/04-elements-and-pages.md` | 把公共元素位置改为顶层 `elements/`，应用改为冻结副本 |
| `llm-wiki/06-testing-and-evidence.md` | 增加候选指令与快照证据要求 |
| `llms.txt` | 同步新的文档入口和规则摘要 |
| `packages/rpa-platforms/README.md` | 标记为保留目录，不再作为元素源库；本补丁不删除该目录 |
| `packages/rpa-core/README.md` | 增加 Instruction 和 Catalog 能力边界 |
| `packages/rpa-core/pyproject.toml` | 将 `rpa-core` 升级到 `0.2.0`，不新增第三方依赖 |
| `packages/rpa-core/uv.lock` | 仅通过 uv 重新锁定，禁止手工编辑 |
| `packages/rpa-core/src/rpa_core/__init__.py` | 导出新的公共接口 |
| `packages/rpa-core/src/rpa_core/contracts.py` | 增加 V2 App/Requirement 契约和 `UnresolvedInstruction` |
| `packages/rpa-core/src/rpa_core/runtime.py` | 为 `ExecutionContext` 增加类型化指令注册表入口 |
| `packages/rpa-core/src/rpa_core/discovery.py` | 增加 V2 应用目录、快照、候选和复制代码边界验证 |
| `packages/rpa-core/src/rpa_core/schema_export.py` | 导出新增 Schema |
| `packages/rpa-core/src/rpa_core/schemas/*.json` | 更新并新增检查入库的 JSON Schema |
| `packages/rpa-core/tests/test_contracts.py` | V1 兼容和 V2 指令引用测试 |
| `packages/rpa-core/tests/test_discovery.py` | 应用快照、路径、哈希和候选验证测试 |
| `packages/rpa-core/tests/test_requirements.py` | `UI-*` 引用、孤立项、哈希和一致性测试 |

#### A.3 不修改的核心浏览器文件

第一批不主动扩展以下文件：

- `browser.py`；
- `browser_manager.py`；
- `drission_browser.py`。

现有 `open`、`exists`、`click`、`input`、`select`、`download` 和 `screenshot` 已足够支撑候选流程。只有黄金应用 Fake 测试或真实候选验证明确证明动作能力不足时，才另提增量 diff。

### 补丁 B：Codex 生成工作流与黄金应用草稿

目标：补丁 A 测试通过后，固化 Codex 生成流程并根据需求 revision 107 生成首个应用草稿。只运行无副作用测试，不打开真实浏览器。

#### B.1 项目级生成 Skill

拟新增：

```text
.agents/skills/rpa-app-generator/
├── SKILL.md
└── references/
    ├── requirement-ingestion.md
    ├── catalog-selection.md
    ├── application-generation.md
    └── validation-gates.md
```

生成 Skill 必须：

1. 读取 `AGENTS.md`；
2. 获取飞书文档最新 revision；
3. 下载并映射步骤截图；
4. 在生成前扫描 `apps/*/app.toml` 和目标目录；
5. 脱敏需求内容；
6. 先生成 Memory，再生成 JSON Spec；
7. 验证二者一致；
8. 检索顶层库并复制依赖闭包；
9. 为缺失能力生成完整候选项；
10. 生成 `catalog.lock.json`；
11. 自动运行允许的离线测试；
12. 停在真实浏览器授权之前。

#### B.2 黄金应用身份

拟生成：

```text
apps/inventory_jushuitan_export_stock/
```

建议稳定身份：

```text
app_id = "jushuitan.inventory.export_stock"
app_slug = "inventory_jushuitan_export_stock"
entrypoint = "inventory_jushuitan_export_stock.cli:main"
schema_version = 2
requirement_revision = 107
```

执行 Agent 必须在创建前重新扫描冲突；若目录或 `app_id` 已存在，立即停止，不能覆盖或合并。

需求来源在可提交文件中只保存脱敏链接、稳定来源指纹和 revision。真实飞书 token 必须由用户在执行时提供，不能写入本方案或应用源码。

#### B.3 登录入口

平台公开登录地址：

```text
https://www.erp321.com/login.aspx
```

应用提供：

```bash
uv run rpa-app login --account STORE_001
```

业务 `run` 只验证登录态，不自动读取需求正文中的账号密码。

#### B.4 程序步骤

| 阶段 | 行为 | 指令能力 | 输出 |
| --- | --- | --- | --- |
| Prepare | 验证指定 Profile 已登录 | `jushuitan.auth.require_session` | authenticated |
| S001 | 打开库存模块 | `jushuitan.inventory.open_module` | inventory_module_opened |
| S002 | 进入商品库存 | `jushuitan.inventory.open_product_stock` | product_stock_opened |
| S003 | 根据本地配置选择品牌 | `jushuitan.inventory.select_brand` | selected_brand |
| S004 | 搜索并验证筛选完成 | `jushuitan.inventory.search` | filter_applied |
| S005 | 导出库存并验证下载 | `jushuitan.inventory.export_stock` | download_path、sha256、size_bytes |

每个 Step 都必须有稳定 ID、输入、输出、成功条件、超时、重试、恢复策略和副作用声明。

#### B.5 应用内目录

```text
apps/inventory_jushuitan_export_stock/
├── app.toml
├── catalog.lock.json
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
├── README.md
├── GENERATION_REPORT.md
├── requirement/
│   ├── REQUIREMENT_MEMORY.md
│   ├── requirement.spec.json
│   └── assets/
├── config/
│   ├── config.schema.json
│   ├── stores.example.toml
│   └── stores.local.toml
├── src/inventory_jushuitan_export_stock/
│   ├── __init__.py
│   ├── cli.py
│   ├── program.py
│   ├── steps.py
│   ├── models.py
│   ├── validators.py
│   ├── elements/
│   └── instructions/
├── tests/
└── reviews/
```

`.env`、`stores.local.toml`、需求截图、Profile 和运行产物不得提交。

#### B.6 候选项边界

当前仓库没有经过本次真实验证的聚水潭顶层元素或指令。因此首次生成时：

- 登录、登录状态、库存导航、品牌筛选、搜索和导出均为应用级候选指令；
- 页面元素均为应用级候选元素；
- 截图只能用于理解业务位置，不能据此写入未经验证的 XPath/CSS；
- Fake Browser 可以按稳定 element ID 验证完整流程；
- `check`、正常 `run` 和 `resume` 必须列出并拒绝未解决的 `UI-*`、`UE-*`；
- 真实验证只能通过开发人员明确授权的候选验证入口进行。

### 补丁 C：真实候选验证与 Preview

补丁 C 需要单独的真实浏览器授权，不得从补丁 A 或 B 的确认中推断。

授权范围至少包含：

- 应用 ID；
- 账号别名；
- Profile；
- 允许验证的指令和元素 ID；
- 允许访问的平台；
- 允许执行的读取、筛选和下载动作；
- 本次授权的运行 ID 或验证批次；
- 明确禁止的页面提交和外部写入。

执行顺序：

1. 运行独立登录命令；
2. 人工处理验证码、滑块或短信；
3. 验证登录成功标识；
4. 验证候选元素唯一性、显示、可点击和刷新稳定性；
5. 验证候选指令输入、输出和成功条件；
6. 更新 Requirement Memory；
7. 展示 Spec 和需求哈希变化；
8. 得到开发人员确认后再更新 JSON Spec；
9. 执行真实 Preview；
10. 验证下载文件存在、非空、路径受控、哈希可重算；
11. 验证 S001 至 S005 的 Resume。

Preview 成功仅表示读取、筛选和下载成功，不表示外部业务写入或业务验收通过。

### 补丁 D：回灌顶层库与应用快照升级

补丁 D 必须再次走只读方案：

1. 列出拟回灌的元素和指令；
2. 给出真实测试证据引用；
3. 展示顶层新增文件；
4. 展示黄金应用快照变更；
5. 展示 `catalog.lock.json` 前后差异；
6. 说明受影响应用；
7. 得到开发人员确认后才迁移；
8. 回归所有受影响应用。

禁止在真实测试刚通过后直接静默移动文件。

## 8. 核心接口草案

### 8.1 InstructionSpec

```python
@dataclass(frozen=True, slots=True)
class InstructionSpec:
    instruction_id: str
    version: str
    name: str
    platform: str
    declared_inputs: tuple[str, ...]
    declared_outputs: tuple[str, ...]
    required_element_ids: tuple[str, ...]
    preconditions: tuple[str, ...]
    success_conditions: tuple[str, ...]
    side_effect: SideEffect
```

### 8.2 Instruction

```python
class Instruction(ABC):
    spec: InstructionSpec

    @abstractmethod
    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    @abstractmethod
    def verify(
        self,
        context: ExecutionContext,
        result: Mapping[str, object],
    ) -> bool: ...
```

### 8.3 InstructionRegistry

注册表至少负责：

- 拒绝重复 ID；
- 按稳定 ID 获取指令；
- 校验声明输入是否齐全；
- 校验输出键是否符合声明；
- 执行 `verify()`；
- 将底层异常转换为稳定的 Instruction 错误；
- 不写入 Step 检查点；
- 不允许指令获取 DrissionPage 原始对象。

### 8.4 Requirement V2

拟新增字段：

```diff
+ RequirementStep.instruction_refs
+ RequirementStep.unresolved_instruction_ids
+ RequirementSpec.unresolved_instructions
+ UnresolvedInstruction
```

`UnresolvedInstruction` 使用稳定 `UI-*` ID，至少记录：

- 对应需求步骤；
- 平台与能力名称；
- 缺失原因；
- 候选指令引用；
- Fake 测试状态；
- 真实测试状态；
- 当前状态：`unresolved`、`candidate`、`resolved`；
- 是否阻止真实测试、审核和推送。

只有存在稳定指令引用且真实验证完成时，才能进入 `resolved`。

### 8.5 App V2

拟新增：

```diff
+ AppManifest.catalog_lock
+ AppCommands.login
+ AppCommands.verify_candidates
```

V1 应用必须继续可以读取和验证；新生成应用使用 V2。不得静默把所有 V1 应用解释成 V2。

### 8.6 catalog.lock.json

每个条目至少记录：

- 类型：element / instruction；
- 稳定 ID；
- 版本；
- 状态；
- 来源类型：顶层目录 / 应用候选；
- 来源相对路径；
- 目标相对路径；
- 内容哈希；
- 依赖项；
- 复制时间不参与内容一致性判断。

运行前验证应用自己的文件哈希。不得在运行时读取顶层库并自动同步。

## 9. 测试矩阵

### 9.1 补丁 A

- 原有 102 项测试保持通过；
- V1 AppManifest 和 RequirementSpec 兼容；
- V2 缺少 `catalog.lock.json` 时失败；
- 指令 ID、元素 ID 和阻塞项 ID 全局唯一；
- 未知或孤立 `UI-*` 引用失败；
- candidate 指令必须存在应用级实现和 Fake 测试引用；
- resolved 指令必须有真实测试证据；
- 指令输入缺失、输出多余或验证失败时返回稳定错误；
- 应用快照文件缺失或哈希变化时失败；
- 快照路径逃逸、符号链接和硬链接失败；
- 修改顶层目录不改变已有应用副本；
- 复制到应用的 Python 指令直接导入 DrissionPage 时失败；
- 导出的 JSON Schema 与 Pydantic 模型一致；
- `git diff --check` 通过；
- 工作区无无关改动。

### 9.2 补丁 B

- 需求 revision、Memory、Spec、app.toml 一致；
- 应用 ID 和目录无冲突；
- Fake Browser 动作顺序符合 S001 至 S005；
- 登录命令与业务 run 解耦；
- 品牌通过本地配置注入，不写死在公共指令；
- 凭据和真实业务身份不进入源码、测试、事件、检查点和报告；
- Fake 下载生成路径、大小和哈希；
- S003、S004、S005 的失败恢复测试；
- 候选项存在时，正常 `run` 在创建运行目录前拒绝；
- `doctor` 和无副作用 `test` 可以执行；
- `check` 精确列出 `UI-*` 和 `UE-*`。

### 9.3 补丁 C

- 登录成功标识可稳定验证；
- Profile 复用有效；
- 每个元素唯一、显示、可点击并在刷新后稳定；
- 品牌筛选成功条件可验证；
- 导出下载完成可验证；
- 下载文件存在、非空且哈希一致；
- Preview 不产生 NAS、飞书或数据库写入；
- Resume 不重复执行已成功步骤；
- 运行报告明确区分自动测试、真实 Preview 和业务验收。

## 10. 已知风险与处理

### 10.1 README 与真实仓库不一致

当前 README 声称存在示例应用，但 `apps/` 实际为空。补丁 A 必须先修正文档，不能把不存在的应用当成历史基线恢复或复用。

### 10.2 顶层源库与应用副本漂移

通过 `catalog.lock.json`、内容哈希和显式升级 diff 管理。禁止运行时自动同步。

### 10.3 复制后的 Python import 失效

指令目录必须使用应用包内相对导入，或由注册表通过相对入口加载。顶层源代码不能写死仓库根包路径。

### 10.4 候选状态导致正常 run 被阻止

这是预期行为。候选真实验证走单独的 `verify-candidates` 入口，不能为了测试候选而关闭正常运行门禁。

### 10.5 文档包含真实凭据

执行 Agent 读取原需求时必须立刻将账号、密码、手机号和真实品牌转换为本地配置引用。任何可提交文件只使用 `STORE_001`、`BRAND_001` 和通用环境变量占位符。

### 10.6 截图无法提供可靠定位器

截图只用于建立需求步骤和页面位置映射。没有真实 DOM 证据时必须保持候选或 unresolved 状态。

### 10.7 BrowserActions 能力可能不足

补丁 A 不预先扩展浏览器协议。若 Fake 或真实验证证明需要 `text`、多元素、iframe 或新标签页能力，再提交独立增量方案和测试。

### 10.8 uv 不在 PATH

执行 Agent 应先定位当前机器的 uv 可执行文件，并使用已安装版本。不得把用户绝对路径写进应用或文档；不得手工修改 `uv.lock`。

## 11. 执行 Agent 检查清单

每个补丁开始前：

1. 读取 `AGENTS.md` 和本文；
2. 检查当前用户要求是否明确授权该补丁；
3. 检查 `git status --short`；
4. 记录分支、HEAD 和无关修改；
5. 扫描当前文件，确认本文没有过期；
6. 涉及库/API 时重新使用 Context7；
7. 只修改本补丁列出的文件；
8. 使用增量 patch，保留开发人员已有修改；
9. 运行无副作用测试；
10. 更新实施结果和未完成项；
11. 不提交、不推送；
12. 在需要真实浏览器或后续补丁前停止并请求授权。

## 12. 必须停止的情况

执行 Agent 遇到以下任一情况必须停止：

- 工作区出现本文未覆盖的开发人员修改；
- `app_id` 或目标目录冲突；
- 需求 revision 不再是本方案记录的版本；
- Memory 与 JSON Spec 不一致；
- V1 兼容性无法保持；
- 指令快照无法构造稳定依赖闭包；
- 脱敏扫描失败；
- 自动测试失败；
- 需要打开真实浏览器；
- 需要登录、点击、查询或下载真实页面；
- 需要修改本方案没有列出的公共接口；
- 用户尚未明确确认现有代码修改方案。

停止提醒必须说明：发生了什么、影响哪些文件或步骤、当前已完成什么、下一项需要开发人员确认什么。

## 13. 阶段交付格式

补丁完成后，执行 Agent必须报告：

- 实际修改文件清单；
- 与本文拟议 diff 的偏差；
- 新增或修改的公共接口；
- 实际测试命令和结果；
- 未运行测试及原因；
- 工作区中的无关修改；
- 当前是否具备进入下一补丁的条件；
- 下一步所需的精确授权。

不得把 Fake 测试通过写成真实浏览器通过，不得把 Preview 下载成功写成业务验收通过。

## 14. 推荐授权语句

若开发人员只批准第一批核心改造，可使用：

> 确认本方案，授权执行补丁 A：修改核心指令与快照契约及对应文档；不生成黄金应用，不打开真实浏览器，不提交、不推送。

补丁 A 完成并验收后，补丁 B 仍需单独确认。真实浏览器候选验证和 Preview 必须再次单独授权。
