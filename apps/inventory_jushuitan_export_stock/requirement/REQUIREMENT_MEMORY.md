# 聚水潭库存导出需求记忆

## 来源与身份

- 来源：飞书文档（链接与 token 已脱敏）
- 来源指纹：`sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722`
- 固定 revision：`107`
- 应用 ID：`jushuitan.inventory.export_stock`
- 应用目录：`apps/inventory_jushuitan_export_stock/`
- 程序入口：`inventory_jushuitan_export_stock.cli:main`
- 文档执行频率：每日 09:00；当前应用提供标准 CLI，调度器接入不属于本应用。

真实账号、密码、人员、店铺和品牌只存在于 Git 忽略的本地配置中。可提交内容统一使用 `STORE_001`、`ACCOUNT_PROVIDER_001` 和 `BRAND_001` 等别名。

## 完整业务流程

1. `Prepare`：使用指定账号的独立持久化 Profile 打开登录入口；会话失效时在本次 `run` 内使用该账号的本地凭据登录，并从已登录页面读取身份文本，与本地期望账号标识比对。只有登录态和账号身份都通过才进入 S001；错误账号、登录失败或人机验证都截图并停止。
2. `S001`：直接点击左侧库存入口，并验证库存模块当前状态。
3. `S002`：进入商品库存，并验证活动页签和业务 iframe。
4. `S003`：重置历史筛选，从本地配置读取品牌值，把真实 checkbox 集合归一化为仅目标品牌选中；点击商品编码输入框安全收起品牌下拉，并确认弹层不可见。
5. `S004`：在品牌下拉已收起的前提下点击搜索，验证结果表存在；搜索后再次确认仅目标品牌选中且弹层关闭。
6. `S005`：导出前再次执行同一品牌前置条件，触发一次库存导出；文件必须位于本次运行下载目录，并回传路径、SHA-256 和字节数。
7. `Resume`：恢复失败步骤前重建必要页面状态；已成功的 S005 只有在文件路径、大小和哈希仍一致时才跳过，不能重复导出。

输出仅为本地下载文件引用，不写 NAS、飞书多维表格、数据库或正式 Excel。

## 截图映射

| 来源图片 block | 本地文件 | SHA-256 | 对应步骤 |
| --- | --- | --- | --- |
| `EsHKdHjMIoSAHGxBnBDcqWRpnmh` | `requirement/assets/step-002-open-product-stock.png` | `26eb57c91092bffa93b7369b27c871c77b784f5dc0c8cf840abd6a9fded56c25` | S001、S002 |
| `AdI8dqrLyoVifFxSYqfcvlN2n4e` | `requirement/assets/step-003-select-brand-and-search.png` | `e58727a29997675fc43fbe179999de62a565f77c353cc585bf7aa06e8237d3ab` | S003、S004 |
| `ICBnd3Y2LofvibxsLu6cLz1jnEh` | `requirement/assets/step-005-export-stock.png` | `d4eae6b2ff962d67200f685cfc87b3c76d9eae0b0527db9bccf1635768fb89f5` | S005 |

截图只用于确认业务意图，不作为定位器证据；文件位于 Git 忽略目录。

## 元素、指令与验证状态

- 顶层公共库：17 个真实验证元素、7 条真实验证指令；本次新增账号身份文本载体和“确保目标账号会话”能力，已被替代且无应用引用的旧登录态检查指令已从源库退役。
- 应用快照：当前业务依赖闭包包含 17 个公共验证元素和 7 条公共验证指令；均由 `catalog.lock.json` 固定，运行时不读取顶层目录。
- 已解决项：账号身份文本载体在授权 Preview 中验证为唯一、可见、可读且跨恢复稳定；错误身份被失败关闭，正确身份放行后完整流程成功。候选元素和指令已回灌顶层公共库并重建应用稳定快照。
- 未沉淀项：人机验证专用标识未在真实登录中出现，不生成定位器；登录未达到认证标识时统一截图并失败转人工。旧的独立品牌选中标识已由品牌选择器内部的真实选中集合契约替代。
- 离线测试：通过。
- 真实候选验证：批次 `account-session-verify-20260903`、运行 `account-session-preview-20260903` 已通过；登录用户名与页面租户身份语义不同的问题已通过本地 `identity_env` 映射解决，真实值未进入可提交文件。
- 真实 Preview：0.3.0 运行 `preview-20260903T062356Z-df357a62` 完成 Prepare、S001–S005，验证本地配置目标品牌并下载 218,378 字节的 XLSX，SHA-256 为 `sha256:b39e6b23dda9bf1f8415ab2d524afa2435ae9126aca33f9542cc19f4412e29c6`；未执行外部业务写入。
- 幂等恢复：0.2.0 历史运行使用同一 Run ID 恢复时 S001–S005 全部跳过，下载文件未变化；0.3.0 本次完整 Preview 没有执行 Resume。
- 详细证据、产物哈希和授权范围见 `GENERATION_REPORT.md`。

## Authorization contract

- 日常 Preview 可以执行 `rpa-app preview --account STORE_001`：CLI 自动生成 `run_id`/`authorization_id`，只展示账号、真实动作和 `external_writes`，以一次交互式 `y` 完成 grant 后立即 claim/run。该命令不提供非交互绕过；取消会把 request 标记为 `REVOKED`。完整 `authorization request|grant` 保留给 CI、自动化和排障。
- `login`、`verify-candidates`、`run`、`resume` 都要求显式的 `run_id` 和 `authorization_id`。应用不再接受静态 Batch Constants。
- 开发人员先用 `authorization request` 生成不可变的 `AuthorizationScope` 和 `scope_digest`，检查 `app_id`、`app_version`、`program_id`、`program_version`、`requirement_hash`、`catalog_digest`、`operation`、`mode`、`run_id`、`resume_checkpoint_digest`、`resume_step_id`、`account_id`、`profile_id`、`allowed_origins`、`step_ids`、`browser_actions`、`element_ids`、`candidate_asset_refs`、`external_writes` 和 `source_preview_run_id`，再用 exact `scope_digest`、`authorized_by`、`approval_reference` 和 `ttl_seconds` 执行 `authorization grant`。
- `profile_id` 是实际 Profile directory 的本地 SHA-256 fingerprint，不是账号别名，也不暴露本机路径；配置在 request 后变化会造成 exact-scope mismatch。
- `AuthorizationStore.claim()` 必须在创建 run directory 和构造 `BrowserManager` 之前完成；store 受 Application directory boundary 约束并拒绝 symlink ancestor。scope 必须 exact match，record 只能 claim 一次；Browser 启动前再次校验 expiry。`AuthorizedBrowserActions` 在每次 Browser Boundary 前后校验顶层 Origin，并校验 Step、Action 和 Element；固定业务 iframe 不单独执行 Origin allowlist。
- `resume` 沿用原 `run_id` 和 checkpoint，但必须创建新的 `operation=resume` Authorization Record，并绑定 canonical `resume_checkpoint_digest` 与首个待恢复 `resume_step_id`。checkpoint 在 claim 前变化时 record 保持 `granted`；claim 后变化则由 Runner 在持有 `.run.lock`、重新读取 checkpoint 后且在 `Program.prepare()` 前拒绝，record 最终为 `failed`。旧 record 无论成功、失败或进程中断都不能复用。
- `verify-candidates` 的 Authorization Record 必须绑定当时 `catalog.lock.json` 中全部 `candidate_asset_refs`；当前快照无 candidate，因此该命令会以 `candidate_scope_empty` 失败关闭，直到应用再次引入候选资产。Candidate verification 只允许 fresh run，不提供语义含混的 `--resume`。
- Core 的 Live adapter 还会逐条 claim `external_writes.write_id`、`external_writes.step_id`、`external_writes.adapter`、`external_writes.target`、`external_writes.data_scope`、`external_writes.expected_record_count` 和 `external_writes.payload_digest`，随后按 exact `target` 和 `data_scope` 独立 read back；只有 `record_count` 与 canonical `payload_digest` 都匹配才写入 `SUCCEEDED` receipt。旧的进程内 `LiveWriteGrant` 单独不能越过 External Write boundary。
- 当前应用没有 external business write，`live` request 和 execution 始终以 `application_live_unsupported` 失败关闭。0.2.0 的真实 Preview 与审核记录只作为历史证据，不授权 0.3.0 执行。

## 变更与测试历史

- 2026-09-01：按飞书 revision 107 首次生成脱敏需求记忆、V2 Spec、应用候选元素/指令和离线程序。
- 2026-09-02：完成真实页面验证、目标品牌精确选择、下拉层安全收起、搜索、库存下载和 Resume 验证。
- 2026-09-02：经开发人员明确授权，将程序实际使用的 16 个元素和 7 条指令晋升顶层公共库，并重建应用稳定快照。
- 2026-09-02：开发人员明确审核通过，接受既有 Preview 证据用于当前版本，并授权提交推送；审核记录为 `reviews/20260902T165014+0800.toml`。
- 2026-09-03：开发人员根据实际调用结果明确修正登录需求：标准 `run/resume` 必须自行确保会话并验证目标账号，不能只检查当前标签页的通用登录标识。旧审核随需求哈希和代码变化失效，但历史记录保留。
- 2026-09-03：开发人员授权 `STORE_001` 账号身份候选验证和一次 Preview；同一运行经检查点恢复完成目标品牌筛选与一次库存下载，随后将两个新增稳定资产回灌公共库。
- 2026-09-03：开发人员确认审核通过 0.2.0，接受运行 `account-session-preview-20260903` 的既有 Preview 证据覆盖当前需求哈希，并授权提交及推送；审核记录为 `reviews/20260903T095809+0800.toml`。
- 2026-09-03：0.3.0 移除静态 Batch Constants，改为持久化、exact-scope、single-use Authorization Record；旧审核随版本和需求哈希变化失效，但历史记录保留。
- 2026-09-03：在不改变底层 Authorization Contract 的前提下增加交互式 `preview` 快捷入口，把 request、scope review、grant 和 run 合并为一条命令与一次确认；非交互调用继续失败关闭。
- 2026-09-03：0.3.0 首次真实 Preview `preview-20260903-001` 完成 S001、S002，S003 两次返回 `instruction_execution_failed`，S004、S005 未执行；Authorization Record 已 `failed`，未执行 external business write。
- 2026-09-03：开发人员确认按内部工具边界移除逐 iframe Origin Gate 后，0.3.0 运行 `preview-20260903T062356Z-df357a62` 完成 S001–S005、本地 XLSX 下载和成功截图；Authorization Record 为 `succeeded`，未执行 external business write。
- 2026-09-03：开发人员明确审核通过应用 0.3.0、当前 Requirement Hash 和运行 `preview-20260903T062356Z-df357a62`，同意进入 `ready_for_push` 并提交推送；审核记录为 `reviews/20260903T143849+0800.toml`。
- 程序版本：`0.4.0`。
- 当前状态：`ready_for_push`；当前 Developer Review 已完成。

## 机器可读规范

开发人员只编辑本文件。下面是唯一规范块；JSON Spec 必须由其生成并保持一致。

```toml requirement-canonical
schema_version = 2
pending_confirmations = []

[[unresolved_elements]]
id = "UE-ACCOUNT-IDENTITY"
requirement_step = "Prepare"
platform = "jushuitan"
page = "authenticated_shell"
name = "当前账号身份文本载体"
reason = "现有公共元素只能证明页面已登录，不能证明当前会话属于命令指定账号。"
resolution = "授权 Preview 已验证页面正文文本载体唯一、可见、可读、错误身份拒绝和跨恢复稳定性；已回灌公共元素库。"
status = "resolved"
resolved_element_ref = "jushuitan.erp.shell.account_identity_surface"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_instructions]]
id = "UI-ENSURE-ACCOUNT-SESSION"
requirement_step = "Prepare"
platform = "jushuitan"
capability = "在标准运行中确保目标账号登录并验证身份"
reason = "既有 require_session 只检查当前标签页的库存菜单，不导航、不登录且不核对目标账号。"
candidate_instruction_ref = "jushuitan.auth.ensure_account_session"
candidate_implementation = "src/inventory_jushuitan_export_stock/instructions/jushuitan/erp/auth/ensure_account_session/instruction.py"
fake_test_ref = "tests/test_catalog_instructions.py"
fake_test_status = "passed"
real_test_status = "passed"
real_test_evidence = "GENERATION_REPORT.md"
status = "resolved"
resolved_instruction_ref = "jushuitan.auth.ensure_account_session"
blocks_offline_test = false
blocks_real_run = false
blocks_review = false
blocks_push = false

[source]
document_id = "feishu-doc-sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722"
revision = 107
requirement_hash = "sha256:02de868803b5daf6eb76d4e66abfad385e20eddb9578a133a4285fc31cd30199"
document_url = "https://<tenant>.feishu.cn/docx/<redacted>"

[application]
app_id = "jushuitan.inventory.export_stock"
app_slug = "inventory_jushuitan_export_stock"
name = "聚水潭库存导出"
version = "0.4.0"
entrypoint = "inventory_jushuitan_export_stock.cli:main"

[[steps]]
id = "Prepare"
name = "确保目标账号登录并验证身份"
action = "ensure_target_account_session"
inputs = ["account_id", "persistent_profile", "stores.<account_id>.login_url", "credentials.<account_id>", "stores.<account_id>.expected_identity"]
outputs = ["authenticated", "identity_verified", "login_performed", "human_verification_required"]
success_conditions = ["authenticated is true", "identity_verified is true", "human_verification_required is false"]
element_refs = ["jushuitan.erp.login.account_input", "jushuitan.erp.login.password_input", "jushuitan.erp.login.agreement_checkbox", "jushuitan.erp.login.submit_button", "jushuitan.erp.login.password_notice_confirm", "jushuitan.erp.shell.authenticated_marker", "jushuitan.erp.shell.account_identity_surface"]
instruction_refs = ["jushuitan.auth.login", "jushuitan.auth.ensure_account_session"]
unresolved_element_ids = ["UE-ACCOUNT-IDENTITY"]
unresolved_instruction_ids = ["UI-ENSURE-ACCOUNT-SESSION"]
timeout_seconds = 60.0
resume = "verify_then_run"
recovery = ["capture sanitized evidence and stop before inventory navigation"]
side_effect = "write"

[steps.retry]
max_attempts = 1
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = []

[[steps]]
id = "S001"
name = "打开库存模块"
action = "open_inventory_module"
inputs = []
outputs = ["inventory_module_opened"]
success_conditions = ["inventory module marker is visible"]
element_refs = ["jushuitan.erp.navigation.inventory_module", "jushuitan.erp.inventory.module_marker"]
instruction_refs = ["jushuitan.inventory.open_module"]
unresolved_element_ids = []
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["verify module marker before repeating navigation"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["instruction_execution_failed", "instruction_verification_failed"]

[[steps]]
id = "S002"
name = "进入商品库存"
action = "open_product_stock"
inputs = []
outputs = ["product_stock_opened"]
success_conditions = ["product stock page marker is visible"]
element_refs = ["jushuitan.erp.inventory.product_stock_entry", "jushuitan.erp.product_stock.page_marker"]
instruction_refs = ["jushuitan.inventory.open_product_stock"]
unresolved_element_ids = []
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["verify product stock marker before repeating navigation"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["instruction_execution_failed", "instruction_verification_failed"]

[[steps]]
id = "S003"
name = "根据本地配置精确选择品牌"
action = "select_configured_brand"
inputs = ["stores.<account_id>.brand_value"]
outputs = ["selected_brand", "selection_visible"]
success_conditions = ["only the configured brand is selected", "brand popup is hidden before search"]
element_refs = ["jushuitan.erp.product_stock.reset_button", "jushuitan.erp.product_stock.brand_selector"]
instruction_refs = ["jushuitan.inventory.select_brand"]
unresolved_element_ids = []
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["normalize the real selected checkbox set before continuing"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["instruction_execution_failed", "instruction_verification_failed"]

[[steps]]
id = "S004"
name = "搜索并验证筛选完成"
action = "search_inventory"
inputs = ["stores.<account_id>.brand_value"]
outputs = ["filter_applied"]
success_conditions = ["filtered result marker is visible", "only the configured brand remains selected", "brand popup is hidden"]
element_refs = ["jushuitan.erp.product_stock.brand_selector", "jushuitan.erp.product_stock.search_button", "jushuitan.erp.product_stock.filter_applied_marker"]
instruction_refs = ["jushuitan.inventory.search"]
unresolved_element_ids = []
unresolved_instruction_ids = []
timeout_seconds = 60.0
resume = "verify_then_run"
recovery = ["verify and normalize the exact filter before searching again"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["instruction_execution_failed", "instruction_verification_failed"]

[[steps]]
id = "S005"
name = "导出库存并验证下载"
action = "export_inventory_file"
inputs = ["safe_export_filename", "stores.<account_id>.brand_value"]
outputs = ["download_path", "sha256", "size_bytes"]
success_conditions = ["only the configured brand remains selected", "brand popup is hidden", "download path is inside the run directory", "download is non-empty and hash is reproducible"]
element_refs = ["jushuitan.erp.product_stock.brand_selector", "jushuitan.erp.product_stock.export_menu", "jushuitan.erp.product_stock.export_stock_option"]
instruction_refs = ["jushuitan.inventory.export_stock"]
unresolved_element_ids = []
unresolved_instruction_ids = []
timeout_seconds = 360.0
resume = "verify_then_run"
recovery = ["verify an existing completed download before downloading again"]
side_effect = "read"

[steps.retry]
max_attempts = 1
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = []

[[outputs]]
id = "OUT-001"
name = "库存导出文件引用"
target = "runs/<run_id>/downloads"
write_mode = "local_download_path_only"
fields = ["download_path", "sha256", "size_bytes"]
unique_keys = ["sha256"]
success_conditions = ["CLI prints a verified local download path"]
side_effect = "read"

[test_requirements]
required_suites = ["unit", "fake_browser", "static", "architecture_boundary", "checkpoint_recovery", "sensitive_data"]
real_browser_required = true
real_browser_authorization_required = true
external_write_preview_required = false

[authorization_requirements]
real_browser_requires_authorization = true
live_requires_separate_authorization = true
live_scope_fields = ["app_id", "app_version", "program_id", "program_version", "requirement_hash", "catalog_digest", "operation", "mode", "run_id", "resume_checkpoint_digest", "resume_step_id", "account_id", "profile_id", "allowed_origins", "step_ids", "browser_actions", "element_ids", "candidate_asset_refs", "external_writes", "external_writes.write_id", "external_writes.step_id", "external_writes.adapter", "external_writes.target", "external_writes.data_scope", "external_writes.expected_record_count", "external_writes.payload_digest", "source_preview_run_id"]
```
