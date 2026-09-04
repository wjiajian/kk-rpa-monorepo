# 京麦商品明细报表导出需求基线

## 来源与应用身份

- 来源：飞书文档（租户、文档 token 与人员信息已脱敏）
- 来源指纹：`feishu-doc-sha256:13532feb9904b6620a069b3cf684a780c7fb69ac6d6b1afeaf14bc077b9fde6d`
- 固定 revision：`164`
- 需求标题：`RPA 需求-京东商志测试`
- 应用 ID：`jingmai.reports.export_product_detail`
- 应用目录：`apps/report_jingmai_export_product_detail/`
- 程序入口：`report_jingmai_export_product_detail.cli:main`
- 触发信息：文档填写“测试”，触发时间 09:00；本应用只提供标准 CLI，不创建调度任务。
- 账号提供方：`ACCOUNT_PROVIDER_001`；真实人员与账号身份只允许存在于 Git 忽略的本地配置。

## 业务目标与完整流程

在已登录的指定京麦账号中，导出京麦商智“经营状况-商品明细”昨日数据，文件仅保存到本次运行的 `runs/<run_id>/downloads/`：

1. `S001`：打开京麦首页；未登录时通过京麦专用稳定入口读取 `.env` 凭据完成密码登录，再回读登录标识和账号身份。身份必须与本地配置精确匹配；验证码、滑块或短信验证只留证并转人工。
2. `S002`：打开京麦商智推荐报表页，点击“经营状况-商品明细报表”的“查看详情”，回读目标页面标识。
3. `S003`：确认组合日期范围的起止日期都是本次运行创建日的昨日；恢复运行沿用检查点里的原目标日期，必要时跨月选择。回读日期范围与每行日期，并确认结果行数大于零。
4. `S004`：点击“下载报表”；回读完成弹窗及完整报表名称。本步骤会创建服务端导出任务，只尝试一次，状态不确定时不自动重复。
5. `S005`：点击弹窗“查看”，切换到新打开的报表下载标签页，并回读下载页标识。
6. `S006`：刷新列表，以完整预期文件名搜索；筛选后的第一行必须精确匹配且状态为“已生成”，才点击该行“下载”。验证文件位于本次运行目录、非空，且大小与 SHA-256 可复算。

公开入口：

- 京麦首页：`https://shop.jd.com/jdm/home`
- 登录页：`https://passport.shop.jd.com/login/index.action`
- 推荐报表页：`https://jdsz.jd.com/szweb/view/reports-center/recommend-report-temp.html`

需求没有指定 NAS、飞书多维表格、数据库或正式 Excel 写入；文档中相应“测试”单元格不作为输出要求。

## 截图证据

截图只用于确认业务意图，不作为 DOM 定位器证据；本地图片位于 Git 忽略目录。

| 来源图片 block | 本地文件 | SHA-256 | 对应步骤 |
| --- | --- | --- | --- |
| `GHX0d9yxroLZYzxtuVecLTPZn70` | `requirement/assets/step-002-open-product-detail.png` | `3aa564dcef0d1c8aad9d2f0442f02a5f8a3361437befae08e7fd34984dac8937` | S002 |
| `CsNZdXQppo9TRqx3fCKcIzjRnZd` | `requirement/assets/step-003-select-yesterday.png` | `324629164f74744fced8355994cecdc04b383bda27e5f316a49903f7cabe0cbc` | S003 |
| `TGufdDc3yov14mx9g9fcCKiRnhb` | `requirement/assets/step-004-request-export.png` | `5f8caac99b6ff44fd224ce26e52f81644bff780997af74d67f9bf32eb29b8d22` | S004 |
| `JqpAd8yELo4PhDxjiHBcB5NGnyg` | `requirement/assets/step-005-open-download-page.png` | `dc21949b3feebb4caf4b2c2a077e7b8ee913e04aeec3faa468e770994c20175c` | S005 |
| `FoDsdit1BoMWhPxisZqcumpCnzg` | `requirement/assets/step-006-download-report.png` | `63c70c896930e935f27eb7deed682a73bb3c54342805cdfaa0b41573ab7e5559` | S006 |

截图显示的目标命名模式：

- 完成弹窗：`经营状况-商品明细报表-{date}-{date}-全部-全部-汇总展示`
- 下载文件：`经营状况-商品明细日报-{date}-全部-全部-汇总-SKU.xlsx`

## 当前状态与失败关闭项

- 需求读取：已完成，固定 revision 164。
- 程序和离线假浏览器反例：已完成；每个步骤至少有一个真实执行的失败状态。
- 元素：26 个定位器已从授权真实 DOM 捕获；京麦专用登录表单、登录态、推荐报表、组合日期、导出弹窗、下载列表和行级下载动作均已验证。
- 交互：跨月日期选择、被页面替换的新标签页切换、完整文件名首行关联均已通过真实浏览器验证。
- 下载：京麦实际返回一个 `.xlsx.zip`；归档内含一个非空 `.xlsx`，本地文件大小与 SHA-256 已复算一致。
- 账号身份已写入 Git 忽略的 `config/stores.local.toml`；开发人员于 2026-09-04 确认 `STORE_001` 是只读或仅允许报表导出的专用子账号。
- `PC-READONLY-ACCOUNT` 已关闭，标准 `rpa-app run` 和 `rpa-app verify-elements` 可以进入真实运行阶段。

## 真实验证证据

2026-09-04 使用应用 Git 忽略的 `.env` 与持久化 Profile 进行开发验证，没有出现 CAPTCHA、滑块、短信或安全校验：

- `verify-20260904T045922Z` 完成 S001–S006 页面链路。S004 只创建一次服务端离线导出任务；S005 成功进入“我的报表”新标签页。
- `regression-20260904T055022Z` 由最终代码再次执行 S001、S002、S003、S006，账号身份、目标页面、组合日期范围、10 行结果日期、筛选首行和下载文件均独立回读通过。
- 下载产物 `jingmai-product-detail-2026-09-03-verified.xlsx.zip` 为 321679 bytes，SHA-256 为 `8a844b1d11f3ccd9f7c9946642dc5ef8667d8ac84a7f3417b0def78cb87b1353`；归档内含一个 350149 bytes 的非空 `.xlsx`。
- 开发人员确认账号边界后，标准命令 `verify-elements-20260904T063602Z-16f4661a` 到达 10 个声明阶段，23 个定位器全部符合 `expect_count`，0 失败、0 弱断言。
- 标准 Preview 运行 `run-20260904T063651Z-2801054d` 完成 S001–S006。产物 `jingmai-product-detail-2026-09-03.xlsx.zip` 为 321683 bytes，SHA-256 为 `6fc0070b41d04ae2d2b2d7dd51f1815e714110325a2f67f9dbec518706e2a043`；归档内含一个 350149 bytes 的非空 `.xlsx`，checkpoint 复算一致。
- 本轮标准验收在修正定位器计数阶段时共创建 4 条同日期离线导出任务；没有执行删除、商品修改或其他业务写入。
- 2026-09-04 根据开发人员提供的稳定入口捕获京麦专用登录表单：账号 `#loginname`、动态 ID 密码框的稳定属性组合和 `button.password__submit` 均唯一可见。
- 全新隔离 Profile 的标准 Preview 运行 `run-20260904T082724Z-117a6c99` 由开发人员手动启动，S001 从稳定入口完成密码登录并回读到 `login_performed=true`、`authenticated=true`、`identity_verified=true`，随后 S002–S006 全部成功。产物 `jingmai-product-detail-2026-09-03.xlsx.zip` 为 321680 bytes，SHA-256 为 `b57c4d7ac22326e05a3af87bd7f89196b974dcab802d8b863b15c2d4f8486325`；归档内含一个 350149 bytes 的非空 `.xlsx`。
- 账号、密码、Cookie、页面身份、截图与下载数据均位于 Git 忽略路径。

## 机器可读规范

下面是本文件唯一的规范块；`requirement_hash` 由规范语义计算，排除哈希字段自身。

```toml requirement-canonical
schema_version = 1

[source]
document_id = "feishu-doc-sha256:13532feb9904b6620a069b3cf684a780c7fb69ac6d6b1afeaf14bc077b9fde6d"
revision = 164
requirement_hash = "sha256:e230ef486a961af966bcf7e80be44810b946a079ad82c9614f8070127541c1aa"
document_url = "https://<tenant>.feishu.cn/docx/<redacted>"

[application]
app_id = "jingmai.reports.export_product_detail"
app_slug = "report_jingmai_export_product_detail"
name = "京麦商品明细报表导出"
version = "0.1.0"
entrypoint = "report_jingmai_export_product_detail.cli:main"

[[pending_confirmations]]
id = "PC-READONLY-ACCOUNT"
requirement_step = "S001"
question = "本地 STORE_001 是否为只读或仅允许报表导出的专用子账号，并已配置可回读的期望身份？"
risk = "账号权限过大或身份未核对时，页面误操作和串号无法由应用外部边界阻断。"
source_location = "需求文档/账号信息"
status = "resolved"
developer_conclusion = "开发人员于 2026-09-04 确认 STORE_001 是只读或仅允许报表导出的专用子账号，且期望身份已配置。"
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-LOGIN-USERNAME"
requirement_step = "S001"
platform = "jingmai"
page = "login"
name = "京麦登录账号输入框"
reason = "完整运行需要在持久化会话失效时自动登录。"
resolution = "在京麦专用稳定登录页捕获唯一 #loginname 输入框。"
status = "resolved"
resolved_element_ref = "jingmai.login.username_input"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-LOGIN-PASSWORD"
requirement_step = "S001"
platform = "jingmai"
page = "login"
name = "京麦登录密码输入框"
reason = "密码输入框 id 每次加载变化，不能依赖动态 id。"
resolution = "使用唯一的 password 类型和“请输入登录密码” placeholder 组合定位。"
status = "resolved"
resolved_element_ref = "jingmai.login.password_input"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-LOGIN-SUBMIT"
requirement_step = "S001"
platform = "jingmai"
page = "login"
name = "京麦立即登录按钮"
reason = "完整运行需要提交密码登录表单，且不得误点短信登录。"
resolution = "捕获密码登录表单唯一主按钮 button.password__submit。"
status = "resolved"
resolved_element_ref = "jingmai.login.submit_button"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-AUTHENTICATED-MARKER"
requirement_step = "S001"
platform = "jingmai"
page = "home"
name = "京麦已登录标识"
reason = "需求从已登录态开始，但截图未提供首页 DOM。"
resolution = "在专用账号的授权真实验证中捕获，并验证未登录页不匹配。"
status = "resolved"
resolved_element_ref = "jingmai.shell.authenticated_marker"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-ACCOUNT-IDENTITY"
requirement_step = "S001"
platform = "jingmai"
page = "home"
name = "当前账号身份文本"
reason = "通用登录标识不能证明当前会话属于目标账号。"
resolution = "捕获唯一可读身份文本，并验证正确与错误身份两种状态。"
status = "resolved"
resolved_element_ref = "jingmai.shell.account_identity_surface"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-PRODUCT-DETAIL-ENTRY"
requirement_step = "S002"
platform = "jdsz"
page = "recommended-reports"
name = "商品明细报表查看详情入口"
screenshot = "requirement/assets/step-002-open-product-detail.png"
reason = "截图证明入口文案和位置，但没有 DOM 证据。"
resolution = "捕获与报表标题行级关联的稳定入口，并验证唯一匹配。"
status = "resolved"
resolved_element_ref = "jdsz.reports.product_detail_entry"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-PRODUCT-DETAIL-PAGE"
requirement_step = "S002"
platform = "jdsz"
page = "product-detail"
name = "商品明细页标识"
screenshot = "requirement/assets/step-003-select-yesterday.png"
reason = "需要区分目标商品明细页与报表中心。"
resolution = "捕获目标页面稳定且唯一的业务标识。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.page_marker"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-START-DATE"
requirement_step = "S003"
platform = "jdsz"
page = "product-detail"
name = "统计开始日期控件"
screenshot = "requirement/assets/step-003-select-yesterday.png"
reason = "截图无法确认控件 DOM 类型和可写入接口。"
resolution = "在真实页面确认日期控件类型、定位器和昨日写入方式。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.start_date_input"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-END-DATE"
requirement_step = "S003"
platform = "jdsz"
page = "product-detail"
name = "统计结束日期控件"
screenshot = "requirement/assets/step-003-select-yesterday.png"
reason = "截图无法确认控件 DOM 类型和可写入接口。"
resolution = "在真实页面确认日期控件类型、定位器和昨日写入方式。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.end_date_input"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-DATE-VALUES"
requirement_step = "S003"
platform = "jdsz"
page = "product-detail"
name = "统计日期回读值"
screenshot = "requirement/assets/step-003-select-yesterday.png"
reason = "必须独立回读两个日期，不能回显程序输入。"
resolution = "捕获两个当前值载体，验证起止日期都等于目标昨日。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.date_values"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-REPORT-ROWS"
requirement_step = "S003"
platform = "jdsz"
page = "product-detail"
name = "商品明细结果行"
screenshot = "requirement/assets/step-003-select-yesterday.png"
reason = "日期生效需要结果状态作为第二条页面证据。"
resolution = "捕获结果行集合并验证目标日期下数量大于零。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.report_rows"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-DOWNLOAD-REPORT"
requirement_step = "S004"
platform = "jdsz"
page = "product-detail"
name = "下载报表按钮"
screenshot = "requirement/assets/step-004-request-export.png"
reason = "截图未提供可执行定位器。"
resolution = "捕获唯一下载报表按钮并验证点击后的弹窗状态。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.download_report_button"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-EXPORT-DIALOG"
requirement_step = "S004"
platform = "jdsz"
page = "product-detail"
name = "报表生成完成弹窗"
screenshot = "requirement/assets/step-004-request-export.png"
reason = "需区分导出完成弹窗与其他通用提示。"
resolution = "捕获弹窗稳定标识并验证期望阶段唯一出现。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.export_ready_dialog"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-DIALOG-REPORT-NAME"
requirement_step = "S004"
platform = "jdsz"
page = "product-detail"
name = "弹窗报表名称"
screenshot = "requirement/assets/step-004-request-export.png"
reason = "弹窗存在本身不能证明生成的是本次日期报表。"
resolution = "捕获名称文本并精确验证目标日期命名模式。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.dialog_report_name"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-VIEW-EXPORTS"
requirement_step = "S005"
platform = "jdsz"
page = "product-detail"
name = "弹窗查看按钮"
screenshot = "requirement/assets/step-005-open-download-page.png"
reason = "需要确认该按钮确实打开新标签页。"
resolution = "捕获按钮并在真实浏览器验证新标签页行为。"
status = "resolved"
resolved_element_ref = "jdsz.product_detail.view_exports_button"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-DOWNLOADS-PAGE"
requirement_step = "S005"
platform = "jdsz"
page = "downloads"
name = "报表下载页标识"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "切换新标签页后必须证明目标页面已激活。"
resolution = "捕获下载页稳定唯一标识并验证标签页切换后可见。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.page_marker"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-REFRESH-REPORTS"
requirement_step = "S006"
platform = "jdsz"
page = "downloads"
name = "刷新报表列表按钮"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "截图未提供可执行定位器。"
resolution = "捕获刷新按钮并验证刷新后列表状态可回读。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.refresh_button"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-REPORT-SEARCH-INPUT"
requirement_step = "S006"
platform = "jdsz"
page = "downloads"
name = "报表名称搜索框"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "必须按完整文件名筛选，不能假定第一行最新。"
resolution = "捕获搜索框并验证可输入完整目标文件名。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.search_input"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-REPORT-SEARCH-BUTTON"
requirement_step = "S006"
platform = "jdsz"
page = "downloads"
name = "搜索报表按钮"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "截图未提供可执行定位器。"
resolution = "捕获搜索按钮并验证搜索提交后的列表状态。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.search_button"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-REPORT-NAMES"
requirement_step = "S006"
platform = "jdsz"
page = "downloads"
name = "报表列表文件名集合"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "需回读所有候选文件名并精确匹配本次目标。"
resolution = "捕获行序稳定的文件名集合，并构造旧文件反例。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.report_names"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-REPORT-STATUSES"
requirement_step = "S006"
platform = "jdsz"
page = "downloads"
name = "报表列表状态集合"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "文件名匹配但状态未生成时不得下载。"
resolution = "捕获与文件名同序的状态集合，并验证同一行状态为已生成。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.report_statuses"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[unresolved_elements]]
id = "UE-MATCHING-DOWNLOAD"
requirement_step = "S006"
platform = "jdsz"
page = "downloads"
name = "首个匹配报表下载按钮"
screenshot = "requirement/assets/step-006-download-report.png"
reason = "必须证明下载动作和精确匹配的文件名属于同一行。"
resolution = "捕获行级关联定位器，验证搜索结果含旧文件时仍下载目标行。"
status = "resolved"
resolved_element_ref = "jdsz.downloads.first_matching_download_button"
tested = true
blocks_test = false
blocks_review = false
blocks_push = false

[[steps]]
id = "S001"
name = "登录并确认目标京麦账号会话"
action = "login_or_verify_target_account_session"
inputs = ["account_id", "persistent_profile", ".env username/password", "stores.<account_id>.expected_identity"]
outputs = ["target_date", "login_performed", "authenticated", "identity_verified"]
success_conditions = ["an unauthenticated session logs in through the stable Jingmai URL", "authenticated marker exists", "page identity exactly matches local expected identity"]
element_refs = ["jingmai.login.username_input", "jingmai.login.password_input", "jingmai.login.submit_button", "jingmai.shell.authenticated_marker", "jingmai.shell.account_identity_surface"]
instruction_refs = []
pending_confirmation_ids = ["PC-READONLY-ACCOUNT"]
unresolved_element_ids = ["UE-LOGIN-USERNAME", "UE-LOGIN-PASSWORD", "UE-LOGIN-SUBMIT", "UE-AUTHENTICATED-MARKER", "UE-ACCOUNT-IDENTITY"]
unresolved_instruction_ids = []
timeout_seconds = 75.0
resume = "verify_then_run"
recovery = ["re-read login and identity state; never accept an unknown account", "retain CAPTCHA, slider, SMS, or an unknown login state for manual handling"]
side_effect = "read"

[steps.retry]
max_attempts = 1
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = []

[[steps]]
id = "S002"
name = "打开经营状况商品明细报表"
action = "open_product_detail_report"
inputs = ["recommended_reports_url"]
outputs = ["target_date", "page_marker_count"]
success_conditions = ["product-detail page marker count equals one"]
element_refs = ["jdsz.reports.product_detail_entry", "jdsz.product_detail.page_marker"]
instruction_refs = []
pending_confirmation_ids = []
unresolved_element_ids = ["UE-PRODUCT-DETAIL-ENTRY", "UE-PRODUCT-DETAIL-PAGE"]
unresolved_instruction_ids = []
timeout_seconds = 45.0
resume = "verify_then_run"
recovery = ["re-open the report center and verify the target page before continuing"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_navigation_failed", "browser_element_not_found", "application_state_invalid"]

[[steps]]
id = "S003"
name = "选择昨日统计日期"
action = "select_yesterday_date_range"
inputs = ["checkpoint target_date or Asia/Shanghai yesterday"]
outputs = ["target_date", "selected_dates", "row_count", "row_dates"]
success_conditions = ["combined date range equals target_date", "report row count is greater than zero", "every report row date equals target_date"]
element_refs = ["jdsz.product_detail.start_date_input", "jdsz.product_detail.end_date_input", "jdsz.product_detail.date_values", "jdsz.product_detail.calendar_month", "jdsz.product_detail.calendar_previous_month", "jdsz.product_detail.calendar_next_month", "jdsz.product_detail.report_rows", "jdsz.product_detail.report_row_dates"]
instruction_refs = []
pending_confirmation_ids = []
unresolved_element_ids = ["UE-START-DATE", "UE-END-DATE", "UE-DATE-VALUES", "UE-REPORT-ROWS"]
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["preserve the original target_date across calendar-day changes"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_element_not_found", "step_verification_failed"]

[[steps]]
id = "S004"
name = "生成商品明细导出任务"
action = "request_report_export"
inputs = ["target_date"]
outputs = ["target_date", "dialog_visible", "report_name"]
success_conditions = ["export-ready dialog exists", "dialog report name exactly matches target_date"]
element_refs = ["jdsz.product_detail.download_report_button", "jdsz.product_detail.export_ready_dialog", "jdsz.product_detail.dialog_report_name"]
instruction_refs = []
pending_confirmation_ids = []
unresolved_element_ids = ["UE-DOWNLOAD-REPORT", "UE-EXPORT-DIALOG", "UE-DIALOG-REPORT-NAME"]
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "manual"
recovery = ["never repeat an uncertain export request automatically"]
side_effect = "write"

[steps.retry]
max_attempts = 1
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = []

[[steps]]
id = "S005"
name = "打开报表下载页"
action = "open_downloads_in_new_tab"
inputs = ["export-ready dialog"]
outputs = ["target_date", "downloads_opened"]
success_conditions = ["a new tab becomes active", "download page marker count equals one"]
element_refs = ["jdsz.product_detail.view_exports_button", "jdsz.downloads.page_marker"]
instruction_refs = []
pending_confirmation_ids = []
unresolved_element_ids = ["UE-VIEW-EXPORTS", "UE-DOWNLOADS-PAGE"]
unresolved_instruction_ids = []
timeout_seconds = 30.0
resume = "verify_then_run"
recovery = ["re-read the active tab's download page marker"]
side_effect = "read"

[steps.retry]
max_attempts = 2
delay_seconds = 0.0
backoff_multiplier = 1.0
retryable_errors = ["browser_navigation_failed", "browser_element_not_found", "application_state_invalid"]

[[steps]]
id = "S006"
name = "匹配并下载本次商品明细报表"
action = "match_ready_report_and_download"
inputs = ["target_date", "expected source filename"]
outputs = ["target_date", "source_filename", "download_path", "sha256", "size_bytes"]
success_conditions = ["first filtered row exactly matches the filename and has status 已生成", "download is non-empty inside the run directory", "size and sha256 match a fresh read"]
element_refs = ["jdsz.downloads.refresh_button", "jdsz.downloads.search_input", "jdsz.downloads.search_button", "jdsz.downloads.report_names", "jdsz.downloads.report_statuses", "jdsz.downloads.first_matching_download_button"]
instruction_refs = []
pending_confirmation_ids = []
unresolved_element_ids = ["UE-REFRESH-REPORTS", "UE-REPORT-SEARCH-INPUT", "UE-REPORT-SEARCH-BUTTON", "UE-REPORT-NAMES", "UE-REPORT-STATUSES", "UE-MATCHING-DOWNLOAD"]
unresolved_instruction_ids = []
timeout_seconds = 300.0
resume = "verify_then_run"
recovery = ["re-verify an existing artifact before any new download"]
side_effect = "read"

[steps.retry]
max_attempts = 3
delay_seconds = 2.0
backoff_multiplier = 1.0
retryable_errors = ["report_not_ready", "browser_download_failed", "browser_element_not_found", "application_state_invalid"]

[[outputs]]
id = "OUT-001"
name = "京麦商品明细昨日导出文件"
target = "runs/<run_id>/downloads"
write_mode = "local_download_path_only"
fields = ["download_path", "sha256", "size_bytes", "source_filename", "target_date"]
unique_keys = ["sha256"]
success_conditions = ["file is non-empty and cryptographically re-readable inside this run"]
side_effect = "read"

[test_requirements]
required_suites = ["unit", "fake_browser", "static", "architecture_boundary", "checkpoint_recovery", "sensitive_data"]
real_browser_required = true
real_browser_authorization_required = true
external_write_preview_required = false
```
