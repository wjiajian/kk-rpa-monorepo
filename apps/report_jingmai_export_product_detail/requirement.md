# 京麦商品明细报表导出需求基线

来源为飞书 revision 164，来源指纹 `feishu-doc-sha256:13532feb9904b6620a069b3cf684a780c7fb69ac6d6b1afeaf14bc077b9fde6d`。应用 ID 为 `jingmai.reports.export_product_detail`，入口为 `report_jingmai_export_product_detail.cli:main`。

文档触发方式填写“测试”、时间为 09:00。本应用只提供 CLI，调度由调用方负责。真实账号、人员与页面身份只保存在忽略的本地配置。

## 业务步骤

1. S001：打开京麦首页，必要时从京麦专用入口用本次传入或本地凭据登录。确认登录态；登录受阻时留证并结束，不匹配预期账号身份。
2. S002：打开商智推荐报表，进入“经营状况-商品明细报表”，回读目标页面标识。
3. S003：将起止日期都设为 target_date；未传入时以 Asia/Shanghai 时区计算本次启动日的昨日并固定；支持跨月选择。回读组合日期范围和结果行日期，并确认有结果行。
4. S004：点击“下载报表”，创建一次服务端导出任务；回读完成弹窗和完整报表名称。
5. S005：点击弹窗“查看”，切换到新打开的报表下载标签页，确认下载页面。
6. S006：刷新列表，用完整预期文件名搜索；筛选后的第一行文件名必须精确匹配且状态为“已生成”，才点击该行下载。等待完成并检查非空文件。

公开入口：

- 首页：`https://shop.jd.com/jdm/home`
- 登录：`https://passport.shop.jd.com/login/index.action`
- 推荐报表：`https://jdsz.jd.com/szweb/view/reports-center/recommend-report-temp.html`

预期弹窗名称为 `经营状况-商品明细报表-{date}-{date}-全部-全部-汇总展示`，列表文件名为 `经营状况-商品明细日报-{date}-全部-全部-汇总-SKU.xlsx`。平台实际下载可能附加 ZIP 扩展名。

## 步骤输入、输出与接管

以下字段对应当前 execute 输出。示例日期 2026-09-04 仅展示格式，接管必须使用源记录的 `ctx.inputs.target_date`，不能重新计算昨日。各步使用 `ctx.browser` 和应用元素服务，不直接读取前序输出；续跑所选步骤之前必须已有成功记录。输出中的页面快照字段如未列入成功条件，就只用于记录动作，verify 仍以当前页面回读为准。

### S001 登录并确认目标京麦账号

- 目标与输入：读取 `ctx.inputs.target_date`，以及 metadata 的 login_username、login_password；打开首页，必要时从专用登录入口登录。
- 前置状态：原账号 Profile 可连接；允许已有会话或尚未登录。
- 输出：target_date（str）为固定目标日期；login_performed、authenticated（bool）记录是否登录、会话可用；identity_check_skipped=true 表示不执行身份匹配。
- 成功条件：输出日期等于原日期、authenticated=true，且当前已登录标识存在。不读取或匹配页面账号名称。
- 失败与恢复：表单不可用检查登录入口；结果不符检查登录会话；登录后仍无会话时截图并报告人工验证。页面或会话丢失时恢复登录页或从 S001 重跑，不能绕过验证码或短信。

接管输出示例：`{"target_date": "2026-09-04", "login_performed": false, "authenticated": true, "identity_check_skipped": true}`。

### S002 打开商品明细报表

- 目标与输入：读取 `ctx.inputs.target_date`，打开推荐报表地址，点击商品明细入口并切换到新标签页。
- 前置状态：S001 已成功，原账号可访问商智报表。
- 输出：target_date（str）；page_marker_count（int）为打开后的页面标识匹配数。
- 成功条件：输出日期等于原日期，当前商品明细页面标识匹配数严格为 1；输出匹配数是动作记录。
- 失败与恢复：入口或切换失败检查报表访问权限、入口和新标签页；结果不符检查当前标签页。页面丢失时可重新打开推荐报表，登录态丢失则从 S001 恢复。

接管输出示例：`{"target_date": "2026-09-04", "page_marker_count": 1}`。

### S003 选择目标统计日期

- 目标与输入：读取原 `ctx.inputs.target_date`，必要时跨月选择日期，使起止日期都等于目标日。
- 前置状态：S001、S002 已成功，商品明细页和日期控件可操作。
- 输出：target_date（str）；selected_dates（list[str]）为控件起止日期；row_count（int）为结果行数；row_dates（list[str]）为结果行日期回读。
- 成功条件：输出 target_date 与原输入一致；当前控件回读恰好为两个目标日期；当前结果行数大于零，行日期列表非空且全部等于目标日。其余输出字段记录动作时状态，不替代这些实时检查。
- 失败与恢复：选择失败检查日历月份和控件；结果不符检查日期范围、空结果或旧数据。页面丢失时恢复商品明细页，再按原日期选择，不能使用当天重新算出的昨日。

接管输出示例：`{"target_date": "2026-09-04", "selected_dates": ["2026-09-04", "2026-09-04"], "row_count": 1, "row_dates": ["2026-09-04"]}`。

### S004 生成商品明细导出任务

- 目标与输入：读取原 `ctx.inputs.target_date`，点击下载报表创建服务端导出任务。
- 前置状态：S001–S003 已成功，商品明细页的原日期结果已加载，下载报表按钮可操作。
- 输出：target_date（str）；dialog_visible（bool）为完成弹窗是否出现；report_name（str）为从“报表【…】已生成”文本提取的完整名称。
- 成功条件：输出日期等于原日期，当前完成弹窗存在，当前解析名称严格等于 `expected_dialog_name(target_date)`。输出 dialog_visible、report_name 是动作记录。
- 失败与恢复：点击失败检查按钮；结果不符检查弹窗和完整报表名称。若从 S004 重跑，需恢复原日期页面，可能生成同条件的新任务。若 S004 已成功而 S006 下载失败，应准备下载页并从 S006 继续，无须重建该弹窗。

接管输出示例：`{"target_date": "2026-09-04", "dialog_visible": true, "report_name": "经营状况-商品明细报表-2026-09-04-2026-09-04-全部-全部-汇总展示"}`。

### S005 打开报表下载页

- 目标与输入：读取原 `ctx.inputs.target_date`，点击导出弹窗的查看按钮并切换到新下载标签页。
- 前置状态：S001–S004 已成功；正常 execute 需要弹窗查看按钮可操作。Agent 已直接打开下载页时可提交该步输出，由 verify 检查目的页面。
- 输出：target_date（str）；downloads_opened（bool）记录下载页标识匹配数是否为 1。
- 成功条件：输出日期等于原日期，当前下载页标识匹配数严格为 1；不重新检查已离开的导出弹窗，也不以输出布尔值代替页面检查。
- 失败与恢复：点击或切换失败检查查看按钮和标签页；结果不符检查是否到达下载页。弹窗已关闭时根据实际页面导航到下载页；没有确认的 URL 或定位器时先观察，不能编造。

接管输出示例：`{"target_date": "2026-09-04", "downloads_opened": true}`。

### S006 匹配并下载目标报表

- 目标与输入：读取 `ctx.inputs.target_date`、`ctx.inputs.export_filename` 和原 `ctx.download_dir`；根据原日期生成 `expected_report_filename(target_date)`，刷新列表、搜索完整文件名并下载首个匹配报表。
- 前置状态：S001–S005 已成功，当前下载页可刷新和搜索；正常 execute 在首行名称精确匹配且状态为“已生成”后才下载。原导出弹窗可以已关闭。
- 输出：target_date、source_filename（str）为原日期与平台完整文件名；download_path（str）为实际下载路径；sha256（str 或 null）为下载引用提供的可选摘要；size_bytes（int）和 status（str）为传输大小及状态。
- 成功条件：输出日期和平台文件名符合原输入；当前筛选首行名称精确匹配且状态为“已生成”；下载 status 为 completed，文件位于原目录内、不是符号链接且实际非空。verify 不比较 size_bytes 或 sha256，不解析工作簿。
- 失败与恢复：报表未生成或首行不符时检查完整文件名和状态；下载失败检查传输及实际路径；空文件不能作为成功结果。下载页丢失时先根据实际页面恢复并确认原账号，再从 S006 继续；不会重新执行 S004 创建报表。

接管输出示例（路径与大小为占位）：`{"target_date": "2026-09-04", "source_filename": "经营状况-商品明细日报-2026-09-04-全部-全部-汇总-SKU.xlsx", "download_path": "<实际下载目录>/jingmai-product-detail-2026-09-04.xlsx.zip", "sha256": null, "size_bytes": 123, "status": "completed"}`。

## 完成与运行方式

选对账号、日期和报表，成功下载非空文件即完成。不核对工作簿内部业务数据，不写 NAS、飞书或数据库；原文相应“测试”单元格不作为输出要求。

正式 run 按配置无人值守执行，从 S001 开始计算昨日日期，允许必要时重复创建相同条件的报表。失败保留浏览器和结果，agent 修复后选择步骤 resume；续跑沿用原目标日期，跨日也不改变。

下载目录可指定；省略配置时默认 Windows 系统下载文件夹，非 Windows 开发环境为 ~/Downloads。所有命令保留已有文件，同名下载改名并返回实际路径，日志和截图另存本应用 runs/<run_id>。

## 截图证据

截图只用于确认业务意图，不作为 DOM 定位器证据；本地图片位于 Git 忽略目录。

| 来源图片 block | 本地文件 | SHA-256 | 对应步骤 |
| --- | --- | --- | --- |
| `GHX0d9yxroLZYzxtuVecLTPZn70` | `requirement/assets/step-002-open-product-detail.png` | `3aa564dcef0d1c8aad9d2f0442f02a5f8a3361437befae08e7fd34984dac8937` | S002 |
| `CsNZdXQppo9TRqx3fCKcIzjRnZd` | `requirement/assets/step-003-select-yesterday.png` | `324629164f74744fced8355994cecdc04b383bda27e5f316a49903f7cabe0cbc` | S003 |
| `TGufdDc3yov14mx9g9fcCKiRnhb` | `requirement/assets/step-004-request-export.png` | `5f8caac99b6ff44fd224ce26e52f81644bff780997af74d67f9bf32eb29b8d22` | S004 |
| `JqpAd8yELo4PhDxjiHBcB5NGnyg` | `requirement/assets/step-005-open-download-page.png` | `dc21949b3feebb4caf4b2c2a077e7b8ee913e04aeec3faa468e770994c20175c` | S005 |
| `FoDsdit1BoMWhPxisZqcumpCnzg` | `requirement/assets/step-006-download-report.png` | `63c70c896930e935f27eb7deed682a73bb3c54342805cdfaa0b41573ab7e5559` | S006 |

## 元素与验证记录

26 个定位器沿用 2026-09-04 授权捕获的真实 DOM，涉及登录表单、账号身份、日期选择、导出弹窗、新标签页和列表下载。已确认的导出子账号信息保存在本地配置。

旧版真实运行 `run-20260904T063651Z-2801054d` 完成 S001–S006；全新 Profile 的 `run-20260904T082724Z-117a6c99` 完成密码登录和全流程。旧版产物是包含非空 XLSX 的 ZIP 文件，详情可从 Git 历史和忽略的运行目录追溯。

0.2.0 与 rpa-core 0.8.0 一起迁移：删除检查点和需求哈希，修正正常场景的报表弹窗文本，加入执行后的空文件反例，使用配置下载目录，并支持旧导出弹窗关闭后由 agent 从下载步骤续跑。

2026-09-05 经用户授权，在 macOS 运行 `run-20260905T060401Z-d16713f5`，当前代码完成 S001–S006。目标日期为 2026-09-04，账号、日期和报表回读均通过，下载 product-detail-validation.xlsx.zip，文件大小 310806 字节。此次通过主入口传入文件名和下载目录；完整路径和结果保存在忽略的运行产物中，未核对表格内部业务数据。

Windows 实机验证已授权，当前等待可连接的 Windows 环境；上述真实运行发生在 macOS。

2026-09-05 新接管入口实施后，经本次授权在 macOS 沿用原任务日期 2026-09-04、账号和下载目录验收。为准备接管场景，在真实完成 S001–S005 后、S006 下载前注入一次仅用于验收的内存异常，生成失败记录 `run-20260905T071146Z-02ad2a2e`；随后恢复原 execute，没有修改业务代码或成功条件。

`open_recovery_session` 报告 browser_adopted 为 true，原输入和 S001–S005 输出保留。确认旧导出弹窗已不再显示，重新打开实际观察到的下载地址；页面重新加载时标识短时不可用，后续 S006 按原流程等待下载控件后成功。续跑 `run-20260905T071533Z-3571517a` 只执行 S006，来源为 program，没有再次创建导出任务。下载 product-detail-validation.xlsx_1.zip，310805 字节；源 result.json、前序输出及原下载文件大小和修改时间均保持不变。接管证据和 helper-acceptance.local.json 留在忽略的运行目录，本应用 21 项离线测试通过。

## 主流程参数

inputs 支持 target_date（YYYY-MM-DD，默认昨日）和 export_filename（ASCII 文件名，默认随目标日期生成）。该应用提供单日报表，不接受周/月报表范围。credentials 支持 username、password、expected_identity；--download-dir 覆盖下载目录。未知字段或非法参数在启动浏览器前拒绝。显式参数优先，参数齐全时本地配置可省略。续跑保留原日期、文件名和目录，凭据需从本次调用或本地配置重新提供。

agent 临时完成失败步时可以提交该步输出，经原 verify 校验后继续下一步；允许仅为本次续跑替换失效定位器，不改变原业务成功条件或应用文件。
