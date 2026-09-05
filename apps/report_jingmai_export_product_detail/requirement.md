# 京麦商品明细报表导出需求基线

来源为飞书 revision 164，来源指纹 `feishu-doc-sha256:13532feb9904b6620a069b3cf684a780c7fb69ac6d6b1afeaf14bc077b9fde6d`。应用 ID 为 `jingmai.reports.export_product_detail`，入口为 `report_jingmai_export_product_detail.cli:main`。

文档触发方式填写“测试”、时间为 09:00。本应用只提供 CLI，调度由调用方负责。真实账号、人员与页面身份只保存在忽略的本地配置。

## 业务步骤

1. S001：打开京麦首页，必要时从京麦专用入口用本次传入或本地凭据登录。回读登录态和配置账号身份；身份不符或登录受阻时留证并结束。
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

## 主流程参数

inputs 支持 target_date（YYYY-MM-DD，默认昨日）和 export_filename（ASCII 文件名，默认随目标日期生成）。该应用提供单日报表，不接受周/月报表范围。credentials 支持 username、password、expected_identity；--download-dir 覆盖下载目录。未知字段或非法参数在启动浏览器前拒绝。显式参数优先，参数齐全时本地配置可省略。续跑保留原日期、文件名和目录，凭据需从本次调用或本地配置重新提供。

agent 临时完成失败步时可以提交该步输出，经原 verify 校验后继续下一步；允许仅为本次续跑替换失效定位器，不改变原业务成功条件或应用文件。
