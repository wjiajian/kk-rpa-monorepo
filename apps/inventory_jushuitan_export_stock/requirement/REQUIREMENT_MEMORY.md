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

1. `Prepare`：使用指定账号的独立持久化 Profile 确认登录态；交互登录只能通过单独授权的 `rpa-app login` 执行。
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

- 顶层公共库：16 个真实验证元素、7 条真实验证指令。
- 应用快照：从公共库复制完整依赖闭包并由 `catalog.lock.json` 固定；运行时不读取顶层目录。
- 未沉淀项：人机验证专用标识未在真实登录中出现，不生成定位器；登录未达到认证标识时统一截图并失败转人工。旧的独立品牌选中标识已由品牌选择器内部的真实选中集合契约替代。
- 离线测试：通过。
- 真实候选验证：通过。
- 真实 Preview：运行 `patch-c-preview-20260902` 完成筛选和下载，未执行外部业务写入。
- 幂等恢复：同一运行 ID 再次恢复时 S001–S005 全部跳过，下载文件未变化。
- 详细证据、产物哈希和授权范围见 `GENERATION_REPORT.md`。

## 变更与测试历史

- 2026-09-01：按飞书 revision 107 首次生成脱敏需求记忆、V2 Spec、应用候选元素/指令和离线程序。
- 2026-09-02：完成真实页面验证、目标品牌精确选择、下拉层安全收起、搜索、库存下载和 Resume 验证。
- 2026-09-02：经开发人员明确授权，将程序实际使用的 16 个元素和 7 条指令晋升顶层公共库，并重建应用稳定快照。
- 2026-09-02：开发人员明确审核通过，接受既有 Preview 证据用于当前版本，并授权提交推送；审核记录为 `reviews/20260902T165014+0800.toml`。
- 程序版本：`0.1.0`。
- 当前状态：`ready_for_push`；审核通过不等于业务验收通过。

## 机器可读规范

开发人员只编辑本文件。下面是唯一规范块；JSON Spec 必须由其生成并保持一致。

```toml requirement-canonical
schema_version = 2
pending_confirmations = []
unresolved_elements = []
unresolved_instructions = []

[source]
document_id = "feishu-doc-sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722"
revision = 107
requirement_hash = "sha256:5d5392ab35e4263f015dd80e68aad443b6e5aba822b262a2babfc38c7b691ceb"
document_url = "https://<tenant>.feishu.cn/docx/<redacted>"

[application]
app_id = "jushuitan.inventory.export_stock"
app_slug = "inventory_jushuitan_export_stock"
name = "聚水潭库存导出"
version = "0.1.0"
entrypoint = "inventory_jushuitan_export_stock.cli:main"

[[steps]]
id = "Prepare"
name = "验证指定 Profile 已登录"
action = "require_authenticated_session"
inputs = ["account_id", "persistent_profile"]
outputs = ["authenticated"]
success_conditions = ["authenticated is true"]
element_refs = ["jushuitan.erp.login.account_input", "jushuitan.erp.login.password_input", "jushuitan.erp.login.agreement_checkbox", "jushuitan.erp.login.submit_button", "jushuitan.erp.login.password_notice_confirm", "jushuitan.erp.shell.authenticated_marker"]
instruction_refs = ["jushuitan.auth.login", "jushuitan.auth.require_session"]
unresolved_element_ids = []
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["stop and run the separately authorized login command"]
side_effect = "read"

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
live_scope_fields = ["app_id", "run_id", "account_id", "target", "step_ids", "data_range", "expected_record_count"]
```
