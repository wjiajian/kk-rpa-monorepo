# 聚水潭库存导出需求基线

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

## 元素与验证状态

- 运行时只加载应用根目录的 `elements.toml`；V1 catalog、逐元素快照和 Instruction 源码已从当前应用移除，历史结论仍可从 Git 与审核材料追溯。
- Prepare 和 S001–S005 均直接使用 `BrowserActions` 与 `ElementSpec`。登录态、账号身份、品牌选择、搜索结果和下载文件都由页面或本地产物回读验证。
- 人机验证专用标识未在真实登录中出现，因此不生成推测定位器；登录后仍没有认证标识时截图并停止。
- 0.4.0 已迁移到共享 `ApplicationDefinition`，离线 Fake 流程与 Step 反例通过；迁移后的真实浏览器验证尚未执行。
- 迁移前的真实 Preview 和恢复记录保留在 `GENERATION_REPORT.md`，只能证明当时的业务页面链路，不能替代共享 CLI 的新一轮真实验证。

## 标准运行契约

- 应用入口委托给共享 `rpa_core.cli`，提供 `doctor`、`test`、`verify-elements`、`run` 和 `resume`。
- `run` 与 `verify-elements` 必须显式传入 `--yes` 才能启动真实浏览器；未确认、配置无效或仍有阻塞项时，在创建运行和启动浏览器前失败。
- 默认 `run` 为 Preview，可读取页面、筛选和下载到本次运行目录；本应用没有外部业务写入。
- `resume <run_id>` 复用原检查点，并回读页面状态决定跳过或重跑步骤；失败时保留浏览器供排查和恢复，成功后关闭。
- 每个 Step 的反例由应用提供生产 Fake 上下文，`rpa-app test` 在 pytest 前统一执行并强制反例失败。

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
- 2026-09-04：0.4.0 删除应用内 CLI/runtime、catalog 快照和运行时 Instruction 层，改用共享 `rpa_core.cli/ApplicationDefinition`；旧审核材料保留为历史证据。
- 程序版本：`0.4.0`。
- 当前状态：`ready_for_review`；共享 CLI 迁移等待代码审查，未声明真实浏览器验证通过。

## 机器可读规范

下面是本文件唯一的规范块；`requirement_hash` 由规范语义计算，排除哈希字段自身。

```toml requirement-canonical
schema_version = 1
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


[source]
document_id = "feishu-doc-sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722"
revision = 107
requirement_hash = "sha256:615a2108edca13f072eff8c8e08120f93efdd34885aae0e425d838980b6680bb"
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
unresolved_element_ids = ["UE-ACCOUNT-IDENTITY"]
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
outputs = ["inventory_module_active"]
success_conditions = ["库存模块处于激活状态（module_marker 带 current 类）"]
element_refs = ["jushuitan.erp.navigation.inventory_module", "jushuitan.erp.inventory.module_marker"]
unresolved_element_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["verify module marker before repeating navigation"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_element_not_found", "browser_element_action_failed"]

[[steps]]
id = "S002"
name = "进入商品库存"
action = "open_product_stock"
inputs = []
outputs = ["product_stock_active"]
success_conditions = ["商品库存页签处于活动状态"]
element_refs = ["jushuitan.erp.inventory.product_stock_entry", "jushuitan.erp.product_stock.page_marker"]
unresolved_element_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["verify product stock marker before repeating navigation"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_element_not_found", "browser_element_action_failed"]

[[steps]]
id = "S003"
name = "根据本地配置精确选择品牌"
action = "select_configured_brand"
inputs = ["stores.<account_id>.brand_value"]
outputs = ["requested_brand", "selected_brands"]
success_conditions = ["回读的选中品牌集合恰好等于配置品牌", "品牌选择动作已验证下拉弹层关闭"]
element_refs = ["jushuitan.erp.product_stock.reset_button", "jushuitan.erp.product_stock.brand_selector", "jushuitan.erp.product_stock.brand_selected_option"]
unresolved_element_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["normalize the real selected checkbox set before continuing"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_element_not_found", "browser_element_action_failed"]

[[steps]]
id = "S004"
name = "搜索并验证筛选完成"
action = "search_inventory"
inputs = ["stores.<account_id>.brand_value"]
outputs = ["row_count", "brands_after_search", "brands_normalized"]
success_conditions = ["结果行数大于 0", "搜索完成后回读的选中品牌仍恰好等于配置品牌", "品牌选择动作已验证下拉弹层关闭"]
element_refs = ["jushuitan.erp.product_stock.brand_selector", "jushuitan.erp.product_stock.search_button", "jushuitan.erp.product_stock.result_row", "jushuitan.erp.product_stock.brand_selected_option"]
unresolved_element_ids = []
timeout_seconds = 60.0
resume = "verify_then_run"
recovery = ["verify and normalize the exact filter before searching again"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_element_not_found", "browser_element_action_failed"]

[[steps]]
id = "S005"
name = "导出库存并验证下载"
action = "export_inventory_file"
inputs = ["safe_export_filename", "stores.<account_id>.brand_value"]
outputs = ["requested_brand", "selected_brands", "download_path", "sha256", "size_bytes"]
success_conditions = ["回读的选中品牌集合恰好等于配置品牌", "品牌选择动作已验证下拉弹层关闭", "下载文件位于本次运行的 downloads 目录内", "文件非空且哈希可复现"]
element_refs = ["jushuitan.erp.product_stock.brand_selector", "jushuitan.erp.product_stock.brand_selected_option", "jushuitan.erp.product_stock.export_menu", "jushuitan.erp.product_stock.export_stock_option"]
unresolved_element_ids = []
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
