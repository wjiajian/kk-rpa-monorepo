# RPA 应用生成规则

## 1. 目标

本仓库的目标是：开发人员向 AI 提供一份飞书 RPA 需求文档，AI 按公共框架生成一个完整、可测试、可审核、可独立运行的 RPA 应用。

固定关系：

```text
一份飞书需求文档
= 一份需求记忆
= 一个应用 ID
= 一个独立应用目录
= 一个 RPA 程序入口
```

同一需求文档的后续变更更新原应用。只有业务目标发生实质变化时，才创建新应用。

## 2. 指令优先级

1. 当前用户明确要求；
2. 本文件；
3. `docs/rpa-framework-design.md`；
4. 应用自己的 `REQUIREMENT_MEMORY.md`、`requirement.spec.json` 和 README；
5. 公共包接口和代码惯例。

如果本文件与现有设计文档冲突，以本文件为准，并在生成报告中记录文档待同步项。

涉及 DrissionPage、uv、飞书 API 或其他库、框架、SDK、CLI 和云服务时，先通过 Context7 或对应官方能力核对当前文档，不凭记忆编造接口。

## 3. 仓库边界

目标结构：

```text
repository/
├── AGENTS.md
├── docs/
├── elements/
├── instructions/
├── packages/
│   ├── rpa-core/
│   ├── rpa-platforms/
│   └── rpa-integrations/
└── apps/
    └── <app_slug>/
```

公共能力职责：

- `elements/`：经过真实页面验证的元素源库，按平台、产品、页面和组件组织；
- `instructions/`：经过真实验证的 Python 指令源库，按平台、产品和能力组织；
- `packages/rpa-core/`：Program、Step、Instruction、ExecutionContext、快照锁、检查点、运行时、浏览器操作包装、日志、证据、审核门禁；
- `packages/rpa-platforms/`：兼容保留目录，不再作为元素或指令源库；
- `packages/rpa-integrations/`：Excel、飞书多维表格、飞书机器人、数据库等集成。

应用通过本地路径引用公共框架和集成包，不复制 `rpa-core`。实际使用的元素、指令及其依赖必须复制到应用包内并由 `catalog.lock.json` 固定；运行时不得读取顶层源库。公共包发生变化时，必须测试所有受影响应用。

## 4. 应用必须独立

每个应用必须拥有自己的：

- `pyproject.toml`；
- `uv.lock`；
- `.python-version`；
- `.venv/`，仅本地存在；
- 依赖声明；
- 源码、测试、配置 Schema、需求记忆和生成报告；
- 标准命令入口。

不得让所有应用共用一个根目录虚拟环境或锁文件。不得为一个应用创建仓库外的代码副本。

应用标准结构：

```text
apps/<app_slug>/
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
│   ├── REQUIREMENT_MEMORY.md
│   ├── requirement.spec.json
│   └── assets/
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
└── reviews/
```

`.venv/`、`.env`、`stores.local.toml` 和 `requirement/assets/` 不得提交 Git。

V1 应用继续按原契约读取和验证；所有新生成应用使用 V2 结构。应用内 `elements/` 和 `instructions/` 同时容纳已验证快照与应用候选项，二者都必须进入 `catalog.lock.json`。

## 5. 应用身份

AI 根据需求自动生成：

- 稳定的 `app_id`；
- 程序名称；
- 目录名 `app_slug`；
- Python 包名；
- 程序入口。

应用 ID 应表达业务域、平台和用途。确定后写入 `REQUIREMENT_MEMORY.md`、`requirement.spec.json` 和 `app.toml`，后续处理同一需求时复用，不得重新生成新 ID。

生成前必须扫描 `apps/*/app.toml` 和目标目录：

- `app_id` 或目录冲突时立即停止；
- 不覆盖、不合并、不删除已有应用；
- 向开发人员展示冲突目标和建议处理方式；
- 只有开发人员明确授权进入“现有应用变更流程”后才能继续。

仓库不维护额外的中心应用注册表。应用发现必须扫描 `apps/*/app.toml`。

## 6. `app.toml`

每个应用必须提供机器可读 `app.toml`，至少包含：

- Schema 版本；
- `app_id`、名称和应用版本；
- Python 版本；
- 程序入口；
- 需求文档 revision 和需求哈希；
- 配置 Schema 路径；
- V2 `catalog.lock.json` 路径；
- 当前状态；
- 标准命令；V2 还必须声明 `login` 和 `verify-candidates`；
- 最近一次有效审核记录引用。

`app.toml` 不得包含真实店铺、账号、凭据、Cookie、Token 或本机路径。

允许 AI 设置的状态：

- `draft`；
- `pending_confirmation`；
- `ready_for_test`；
- `test_failed`；
- `ready_for_review`。

只有 RPA 开发人员可以确认：

- `approved`；
- `ready_for_push`。

AI 不得根据测试通过自行把应用标记为已审核。

## 7. 读取需求

需求来源是开发人员提供的飞书文档。不得要求提报人先改成 JSON、YAML 或新的技术模板。

读取时：

1. 获取飞书文档最新 revision；
2. 读取基本信息、操作步骤、截图和输出要求；
3. 下载截图到应用的 `requirement/assets/`；
4. 建立截图与步骤的明确映射；
5. 提取业务步骤、输入、输出、成功条件、条件分支、循环和异常要求；
6. 生成可阅读需求记忆和机器可读 Spec；
7. 对缺失或不明确内容生成待确认项；
8. 即使有待确认项，也要生成完整业务流程草稿。

不得仅凭截图猜测可靠的 DOM 定位器。不得因个别元素未知而只生成半个程序。

## 8. 需求截图

需求截图必须下载到：

```text
apps/<app_slug>/requirement/assets/
```

建议按步骤重命名：

```text
step-001-login-page.png
step-002-date-filter.png
step-003-export-button.png
```

`REQUIREMENT_MEMORY.md` 使用相对路径关联截图，并记录来源图片标识和文件哈希。

截图仅在本地使用，不提交 GitHub。其他开发人员需要截图时，凭飞书权限从原需求文档重新下载。

## 9. 需求记忆

每个应用必须同时生成：

```text
requirement/REQUIREMENT_MEMORY.md
requirement/requirement.spec.json
```

### 9.1 `REQUIREMENT_MEMORY.md`

它是开发人员阅读和人工修正需求的唯一入口，至少包含：

- 脱敏后的飞书文档链接和 revision；
- 应用 ID、名称、目录和入口；
- 结构化业务步骤；
- 截图关联；
- 输入、输出和成功条件；
- 条件、循环和重试要求；
- 待确认项及处理结论；
- 元素与指令解析状态；
- 应用快照版本、哈希和候选验证状态；
- 需求变更历史；
- 对应程序版本和测试状态。

### 9.2 `requirement.spec.json`

它由 AI 从 `REQUIREMENT_MEMORY.md` 生成，供框架和后续 AI 处理，必须通过公共 JSON Schema 校验。开发人员不得直接编辑。

至少包含：

- Schema 版本；
- 需求来源 revision 和需求哈希；
- 应用元数据；
- 有序步骤；
- 每步动作、输入、输出和成功条件；
- 条件、循环、恢复和重试要求；
- 元素引用、指令引用、未解析元素或未解析指令；
- 输出目标及写入模式；
- 待确认项；
- 测试和授权要求。

### 9.3 一致性门禁

`REQUIREMENT_MEMORY.md` 与 `requirement.spec.json` 必须一致：

- 不一致时立即停止；
- 输出字段和步骤级差异；
- 不修改业务代码；
- 不执行真实测试；
- 不自行选择一份文件静默覆盖另一份；
- 提醒开发人员处理。

开发人员人工修正时只修改 `REQUIREMENT_MEMORY.md`。AI 展示 Spec 变更对比，得到开发人员确认后再重新生成 JSON 和需求哈希。

## 10. 需求变更

飞书需求 revision 发生变化时：

1. 读取最新需求；
2. 与已确认需求记忆比较；
3. 生成 `REQUIREMENT_CHANGE_PROPOSAL.md`；
4. 标明新增、修改、删除和受影响步骤；
5. 分析元素、代码、检查点和测试影响；
6. 通知 RPA 开发人员；
7. 开发人员确认前，不更新需求基线，不修改现有程序。

开发人员确认需求变更后，AI 才能更新需求记忆和提出代码修改方案。

## 11. 现有代码修改

不区分“AI 自动生成区”和“开发人员手写区”。所有代码地位相同。

首次生成后，不得按模板整文件重建应用。修改现有应用必须分为两阶段：

### 阶段一：只读方案

- 比较需求记忆、JSON Spec 和当前代码；
- 生成文件级、步骤级修改方案和 diff；
- 标明测试影响、公共元素影响和风险；
- 不修改文件。

### 阶段二：授权修改

开发人员确认方案后：

- 按确认的 diff 增量修改；
- 保留已有人工修复和优化；
- 更新测试和 `GENERATION_REPORT.md`；
- 运行无副作用测试；
- 等待真实测试授权。

工作区已有修改属于开发人员。不得覆盖、丢弃、重置或混入无关改动。

## 12. 完整流程和待确认项

AI 必须编写完整业务流程。信息不足时使用结构化对象，不使用散落且不可追踪的普通 `TODO`。

### 12.1 `PendingConfirmation`

用于业务规则、输入、输出、成功条件或异常处理不清楚的情况，至少记录：

- 稳定 ID；
- 需求步骤；
- 问题；
- 风险；
- 来源文档位置和截图；
- 是否阻止测试、审核或推送；
- 开发人员结论。

### 12.2 `UnresolvedElement`

元素库中没有目标元素时，至少记录：

- 稳定 ID；
- 平台、页面和元素名称；
- 对应需求步骤和截图；
- 缺失原因；
- 处理方式：开发人员指定或授权补抓；
- 当前解析状态。

未解决元素必须放进完整步骤流程，不能编造 XPath/CSS，也不能删除该步骤。

### 12.3 `UnresolvedInstruction`

顶层指令库没有可复用能力时，至少记录：

- 稳定 `UI-*` ID 和对应需求步骤；
- 平台、能力名称和缺失原因；
- 候选指令引用、应用内实现路径和 Fake 测试引用；
- Fake 测试状态、真实测试状态和真实证据；
- 当前状态：`unresolved`、`candidate` 或 `resolved`；
- 是否阻止离线测试、真实运行、审核和推送。

`candidate` 必须有应用内实现、Fake 测试引用和 `catalog.lock.json` 候选条目。只有稳定指令引用、真实测试通过且存在证据时才能标记 `resolved`。

任何未解决的 `PendingConfirmation`、`UnresolvedElement` 或 `UnresolvedInstruction` 都阻止审核通过、提交和推送。候选项可以不阻止 `doctor` 和无副作用测试，但必须阻止正常真实 `run`。

## 13. 元素、指令和应用快照

顶层源库使用：

```text
elements/<platform>/<product>/<page>/<component>.toml

instructions/<platform>/<product>/<capability>/
├── instruction.toml
└── instruction.py
```

顶层库只保存真实验证过的稳定资产。公共元素只保存定位描述和验证元数据，不保存实时 DOM、店铺配置或业务凭据；公共指令通过 `ExecutionContext` 调用受控服务，不得直接导入 DrissionPage 或外部系统底层 SDK，也不得写 Step 检查点。

生成 V2 应用时：

1. 扫描并验证顶层元素和指令元数据；
2. 解析 `element:<id>` / `instruction:<id>` 的完整依赖闭包；
3. 拒绝重复 ID、未知依赖、循环、路径逃逸、符号链接和硬链接；
4. 复制到 `src/<python_package>/elements/` 和 `instructions/`；
5. 在 `catalog.lock.json` 固定来源、目标、版本、依赖、复制时间和内容哈希，复制时间不参与内容一致性判断；
6. `check`、`run` 和 `resume` 前只验证应用副本，不读取或同步顶层库。

新元素或指令采用：

```text
应用内候选元素和候选指令
→ Fake Browser 测试
→ 开发人员授权 verify-candidates
→ 逐步验证页面身份、定位唯一性、显示、可点击和刷新稳定性
→ 独立验证指令结果
→ Preview 端到端通过
→ 提出回灌顶层源库的独立 diff
→ 回归受影响应用
```

候选项保留在应用自己的快照目录并标记 `candidate`，不得直接写入顶层库。已有应用升级公共资产时，必须先展示来源版本、哈希和文件 diff；开发人员确认前不得替换应用副本。禁止运行时自动修复或云端静默同步。

## 14. 业务代码边界

业务步骤可以自由编排流程、条件和循环，但所有外部操作必须经过 `ExecutionContext`：

- 可复用能力：`ctx.instructions`；
- 浏览器：`ctx.browser` 或 `ctx.browsers`；
- Excel：`ctx.excel`；
- 飞书：`ctx.feishu`；
- 数据库：`ctx.database`；
- 日志、截图、产物、凭据和检查点：对应上下文服务。

应用源码和应用快照指令不得直接导入 DrissionPage，不得调用 `page.ele().click()`，不得绕开包装器直接访问飞书、Excel 或数据库底层驱动。应用不得从仓库顶层 `elements` 或 `instructions` 导入运行时代码，只能使用包内冻结副本。

每个步骤必须有稳定步骤 ID、输入、输出、成功条件、重试策略、恢复策略，并在验证成功后才写入检查点。

一条 Instruction 必须有稳定 ID、语义版本、精确输入输出、依赖元素、前置条件、成功条件和副作用等级。注册表必须拒绝重复 ID、输入输出漂移及验证失败；Instruction 的 `verify()` 通过不等于 Step 成功，Step 仍须独立验证后才能写检查点。

## 15. 多店铺配置

一个应用可以通过本地配置支持多个店铺，不得为每个店铺复制应用代码。

每个店铺必须使用：

- 独立 Chrome 进程；
- 独立持久化 Profile；
- 独立调试端口；
- 独立运行目录和检查点；
- Profile 排他锁。

账号密码集中保存在应用本地 `.env` 中。店铺 ID、名称、平台、环境变量名和 Profile 映射保存在 `config/stores.local.toml`。两者均不得提交。

可提交的 `.env.example` 和 `stores.example.toml` 只能使用通用占位符，不得泄露真实店铺名称或环境变量命名。

## 16. 脱敏

所有可提交文件必须脱敏：

- 真实店铺名称改为稳定别名，如 `STORE_001`；
- 账号提供人改为角色或匿名标识；
- 账号、手机号、邮箱、Token、Cookie 删除或掩码；
- 业务数据样例使用等价模拟数据；
- 本机路径和机器信息使用变量或通用路径。

需要脱敏的文件包括需求记忆、JSON Spec、源码、测试、README、生成报告、变更方案和审核记录。

真实信息只允许存在于本地 `.env`、`stores.local.toml`、未提交截图和运行产物中。

## 17. 标准命令

每个应用必须在自己的 `pyproject.toml` 注册统一入口：

```toml
[project.scripts]
rpa-app = "<python_package>.cli:main"
```

所有新生成的 V2 应用必须支持：

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

含义：

- `doctor`：检查 Python、浏览器、配置、目录和依赖；
- `check`：检查需求一致性、待确认项、元素、指令、快照哈希和架构边界；
- `test`：运行无外部副作用测试；
- `login`：在单独授权下建立或确认指定持久化 Profile 的登录态，不执行业务流程；
- `verify-candidates`：在单独授权下逐条验证应用候选元素和候选指令，不关闭正常运行门禁；
- `preview`：真实读取和下载，所有外部业务写入只生成本地预览；
- `live`：执行经过开发人员单独授权的真实写入；
- `resume`：从失败步骤恢复，仍受 preview/live 模式约束。

## 18. 测试授权

生成或修改完成后，AI 可以自动运行：

- 单元测试；
- Fake Browser、Fake Excel、Fake Feishu 和 Fake Database 测试；
- 类型、语法和静态检查；
- ID 唯一性检查；
- 指令契约、依赖闭包和应用快照完整性检查；
- 架构边界检查；
- 敏感信息和误提交文件扫描；
- 检查点与失败恢复测试。

AI 未得到开发人员明确授权时，不得：

- 打开真实浏览器；
- 登录业务平台；
- 点击、查询、下载或提交真实页面；
- 写入飞书多维表格；
- 修改正式 Excel 文件；
- 写入业务数据库；
- 发送真实飞书告警。

未授权的真实测试在报告中标记为“等待开发人员授权”，不得宣称通过。

## 19. 写入预览和真实写入

开发人员首次授权真实流程测试时，默认使用 `preview`：

- 浏览器读取、查询、筛选和下载可以执行；
- 页面提交、飞书、数据库、正式 Excel、NAS 等外部写入被拦截；
- 按真实格式生成本地预览；
- 校验字段、类型、唯一键、覆盖范围、记录数和目标位置；
- 报告必须明确“写入未执行”。

建议预览目录：

```text
runs/<run_id>/write-previews/
```

开发人员审核预览后，可以单独授权一次真实写入测试。授权必须限定：

- 应用和运行 ID；
- 店铺或账号；
- 写入目标；
- 写入步骤；
- 数据范围和预计记录数；
- 仅本次测试有效。

真实写入完成后必须回读并验证，记录实际数量、成功条件和证据。

## 20. `GENERATION_REPORT.md`

每次生成或修改都必须更新报告，至少包含：

- 飞书需求链接和读取 revision；
- 应用 ID、名称和生成时间；
- AI 识别出的完整业务步骤；
- 新增和修改文件；
- 复用、新增和候选元素、指令及快照哈希；
- 待确认项及风险；
- 已运行、通过、失败和未运行的测试；
- 真实浏览器测试和授权状态；
- 写入预览和真实写入状态；
- 是否满足审核、提交和推送条件；
- RPA 开发人员审核记录引用。

不得把预览成功写成真实写入成功，不得把自动测试通过写成业务验收通过。

## 21. 审核留痕

审核通过必须由 RPA 开发人员用明确自然语言确认。允许开发者和审核人为同一人，也允许另一名开发人员复核。

模糊表达如“看起来可以”“应该没问题”不视为审核通过。AI 必须确认当前应用、需求哈希和测试运行 ID属于审核范围。

每次审核生成不可覆盖的独立记录：

```text
reviews/<timestamp>.toml
```

至少记录：

- 审核人和审核时间；
- 审核结论；
- 需求哈希和应用版本；
- 测试运行 ID及结果；
- 外部写入验证状态；
- 非阻塞说明；
- 被审核文件的内容摘要哈希。

需求或代码变化后，旧审核失效但历史记录必须保留。

## 22. 提交和推送门禁

默认行为：

- 不创建 Git 分支；
- 不提交；
- 不推送；
- 不创建 Pull Request；
- 不部署。

提交和推送前必须同时满足：

- 所有 `PendingConfirmation` 已关闭；
- 所有 `UnresolvedElement` 已解析并测试；
- 所有 `UnresolvedInstruction` 已解析并完成真实验证；
- `catalog.lock.json` 与应用副本一致；
- 自动测试全部通过；
- 真实浏览器流程已授权并完成；
- 所有外部写入至少完成格式预览；
- 需要真实写入验证的步骤已单独授权并验证；
- `GENERATION_REPORT.md` 已更新；
- RPA 开发人员明确审核通过；
- `app.toml` 状态为 `ready_for_push`。

任一条件不满足都禁止提交和推送。

满足条件后，开发人员可以手动提交和推送，也可以明确授权 AI 代为执行。AI 代为执行前必须展示：

- 精确文件清单；
- 测试结果；
- 提交信息；
- 远程和目标分支；
- 工作区中的无关修改。

只提交当前应用和经过确认的公共包修改，不得混入其他改动。

## 23. 与开发人员沟通

需要澄清时一次只问一个问题。

遇到以下情况必须停止并提醒开发人员：

- 应用 ID或目录冲突；
- 需求 memory 与 JSON Spec 不一致；
- 需求 revision 变化但未确认；
- 现有代码修改方案未确认；
- 需要真实浏览器或外部写入授权；
- 仍有待确认项或未解析元素；
- 仍有未解析指令、候选项或快照哈希不一致；
- 脱敏扫描失败；
- 测试失败；
- 提交或推送门禁未满足。

提醒必须说明：发生了什么、受影响文件或步骤、当前已完成工作、下一项需要开发人员确认的具体问题。
