# 聚水潭库存导出需求基线

来源为飞书 revision 107，来源指纹 `sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722`。应用 ID 为 `jushuitan.inventory.export_stock`，入口为 `inventory_jushuitan_export_stock.cli:main`。文档要求每日 09:00 执行，调度由调用方负责。

真实账号和品牌放在忽略的本地配置中；可提交内容使用 `STORE_001`、`BRAND_001` 等别名。

## 业务步骤

1. S000：打开稳定登录入口，必要时用本地凭据登录。回读登录态和期望账号身份，失败留截图并结束。
2. S001：点击库存入口，确认库存模块已打开。
3. S002：进入商品库存，确认活动页签与业务页面。
4. S003：重置历史筛选，将品牌选中集合归一为配置品牌，回读选中集合；通过经验证的关闭目标收起浮层。
5. S004：点击搜索，确认存在结果行；回读搜索后品牌集合仍符合配置，并收起浮层。
6. S005：导出前再确认配置品牌，展开导出菜单，点击导出库存，等待文件下载完成。

## 步骤输入、输出与接管

以下字段对应当前 execute 输出。示例中的 BRAND_TARGET 必须替换为源失败记录的 `ctx.inputs.brand_value`；文件路径、大小和状态必须来自本次实际下载。各步使用 `ctx.browser` 和应用元素服务；凭据只从本次加载的 metadata 读取。这些步骤不直接读取前序输出，但续跑所选步骤之前必须已有成功记录。

### S000 登录并确认目标账号

- 目标与输入：读取 metadata 中的 store_config.login_url、login_credentials（username、password、expected_identity）；expected_identity 缺省时用 username。打开登录入口，必要时登录。
- 前置状态：目标账号的 Profile 可连接；可能已有登录态，也可能显示登录页。
- 输出：authenticated、identity_verified、login_performed、human_verification_required 均为 bool，分别表示会话可用、动作时身份符合、是否执行登录、是否仍需人工验证。
- 成功条件：输出 authenticated 严格为 true，当前会话标识存在，当前身份文本经 NFKC、大小写及空白归一后包含期望身份。其他三个输出字段是动作记录，不代替页面回读。身份载体目前为整页文本，保留已知弱断言。
- 失败与恢复：登录动作失败检查登录表单、凭据和截图；身份不符检查当前账号。会话丢失时恢复登录页或从 S000 重跑；验证码、短信等只留证并报错。

接管输出示例：`{"authenticated": true, "identity_verified": true, "login_performed": false, "human_verification_required": false}`。

### S001 打开库存模块

- 目标与输入：使用库存导航元素进入库存模块；不读取业务 inputs 或前序输出。
- 前置状态：S000 已成功，当前为目标账号的系统主界面，库存入口可操作。
- 输出：inventory_module_active（bool），点击后库存模块标识是否出现。
- 成功条件：输出字段为真值，且当前库存模块标识仍存在。
- 失败与恢复：点击失败检查入口与遮挡；输出不符检查目标模块是否打开。页面或会话丢失时恢复主界面，必要时选择 S000 重跑。

接管输出示例：`{"inventory_module_active": true}`。

### S002 进入商品库存

- 目标与输入：使用商品库存入口打开目标业务页；不读取业务 inputs 或前序输出。
- 前置状态：S000、S001 已成功，库存模块及商品库存入口可操作。
- 输出：product_stock_active（bool），点击后商品库存页面标识是否出现。
- 成功条件：输出字段为真值，且当前商品库存页面标识仍存在。
- 失败与恢复：入口失败检查库存模块；结果不符检查活动页签、iframe 与目标页标识。页面丢失时恢复库存模块或选择更早步骤重跑。

接管输出示例：`{"product_stock_active": true}`。

### S003 选择目标品牌

- 目标与输入：读取原任务 `ctx.inputs.brand_value`，重置历史筛选，将选中品牌归一为该品牌。
- 前置状态：S000–S002 已成功，商品库存页面打开，重置按钮和品牌选择器可操作。
- 输出：requested_brand（str）为原目标品牌；selected_brands（list[str]）为选择后回读的品牌文本。
- 成功条件：requested_brand 与原输入经归一后相同；输出选中集合与当前页面选中集合归一后都只能包含目标品牌。归一处理全半角、大小写和空白，忽略空文本及重复文本。
- 失败与恢复：动作失败检查重置按钮、iframe、浮层与引导；结果不符检查漏选或多选。页面丢失时先恢复商品库存页。临时引导可用实际 DOM 确认的辅助目标关闭；verify 定位器失效时只为本次 resume 覆盖定位字段。

接管输出示例：`{"requested_brand": "BRAND_TARGET", "selected_brands": ["BRAND_TARGET"]}`。

### S004 搜索并验证筛选

- 目标与输入：读取原任务 `ctx.inputs.brand_value`，选择目标品牌后点击搜索，读取结果行和搜索后品牌，再归一品牌选择。
- 前置状态：S000–S003 已成功，商品库存页及搜索按钮可操作，筛选条件属于原任务。
- 输出：requested_brand（str）为原品牌；row_count（int）为搜索后的行数；brands_after_search、brands_normalized（list[str]）分别为搜索后、再次归一后的品牌回读。
- 成功条件：输出品牌与原输入相同；输出行数可转为整数且大于零，当前行数也大于零；两份输出品牌集合和当前页面品牌集合均只包含原目标。verify 不要求输出行数与当前行数完全相等，不检查库存单元格内容。
- 失败与恢复：动作失败检查搜索按钮、遮挡和页面加载；结果不符检查空结果或品牌被平台重置。页面丢失时恢复商品库存页并重新完成原筛选搜索，或从 S003 重跑；不能只凭存在表格容器提交成功。

接管输出示例：`{"requested_brand": "BRAND_TARGET", "row_count": 1, "brands_after_search": ["BRAND_TARGET"], "brands_normalized": ["BRAND_TARGET"]}`。

### S005 导出并验证库存文件

- 目标与输入：读取 `ctx.inputs.brand_value`、`ctx.inputs.export_filename` 和原 `ctx.download_dir`，确认品牌后展开导出菜单，下载库存文件。
- 前置状态：S000–S004 已成功，商品库存页保持原筛选结果，导出菜单可操作。
- 输出：requested_brand（str）、selected_brands（list[str]）记录导出前目标和品牌回读；download_path（str）是实际下载路径；size_bytes（int）是下载返回的大小；status（str）是传输状态。
- 成功条件：输出品牌与原输入一致，输出和页面品牌集合均只含目标；status 为 completed，路径为原下载目录内的普通非符号链接文件，实际大小大于零。size_bytes 是动作记录，verify 以磁盘文件是否非空为准，不计算摘要或解析表格。
- 失败与恢复：动作失败检查品牌、展开后的导出选项与下载诊断；校验失败检查品牌是否变化、文件路径及是否为空。页面丢失时先恢复原账号商品库存页和筛选条件，再从 S005 下载；保留旧文件，使用本次下载返回的实际路径。

接管输出示例（路径与大小为占位）：`{"requested_brand": "BRAND_TARGET", "selected_brands": ["BRAND_TARGET"], "download_path": "<实际下载目录>/inventory-export.xlsx", "size_bytes": 123, "status": "completed"}`。

## 完成与运行方式

账号、品牌和库存报表正确，文件成功下载且非空即完成；不检查表格内部业务数据。本应用没有飞书、数据库、NAS 或正式 Excel 写入。

使用共享 CLI 的 doctor、test、verify-elements、run、resume。正式 run 按配置无人值守执行，从 S000 开始。失败保留浏览器和结果，agent 修复后选择恢复步骤；resume 沿用原品牌、文件名和已完成结果。

下载目录可指定；省略配置时默认 Windows 系统下载文件夹，非 Windows 开发环境为 ~/Downloads。所有命令保留已有文件，同名下载改名并返回实际路径，日志和截图另存本应用 runs/<run_id>。

## 元素与待确认项

全部定位器来自应用的 elements.toml，沿用此前真实捕获的定位器。账号身份当前仍从整页文本做子串匹配，元素检查会报告弱断言；精确身份载体尚待真实页面确认，不编造替代定位器。

尚未捕获专用的人机验证标识。若登录后仍无会话则截图并报错，不绕过验证。

## 截图映射

| 来源图片 block | 本地文件 | SHA-256 | 对应步骤 |
| --- | --- | --- | --- |
| `EsHKdHjMIoSAHGxBnBDcqWRpnmh` | `requirement/assets/step-002-open-product-stock.png` | `26eb57c91092bffa93b7369b27c871c77b784f5dc0c8cf840abd6a9fded56c25` | S001、S002 |
| `AdI8dqrLyoVifFxSYqfcvlN2n4e` | `requirement/assets/step-003-select-brand-and-search.png` | `e58727a29997675fc43fbe179999de62a565f77c353cc585bf7aa06e8237d3ab` | S003、S004 |
| `ICBnd3Y2LofvibxsLu6cLz1jnEh` | `requirement/assets/step-005-export-stock.png` | `d4eae6b2ff962d67200f685cfc87b3c76d9eae0b0527db9bccf1635768fb89f5` | S005 |

截图只用于确认业务意图，不作为定位器证据；文件位于 Git 忽略目录。

## 验证记录

2026-09-02 至 09-03 的旧版本曾完成真实页面、品牌精确选择、浮层收起、库存下载等验证。历史日志与产物在忽略的运行目录，旧代码和审核记录可从 Git 历史追溯。

0.5.0 与 rpa-core 0.8.0 一起迁移：登录成为 S000，删除检查点和需求哈希，使用可配置下载目录；离线测试共用正常场景与反例，并覆盖下载后文件为空、品牌回读不符、从头重跑，以及 agent 指定步骤后沿用原品牌续跑。

2026-09-05 经用户授权，在 macOS 完成当前代码的真实验证：

- 初次运行 `run-20260905T055952Z-0400da80` 在 S003 未找到重置按钮，保留 S000–S002 的成功结果。验收工具结束单次进程会回收子浏览器，后续改用持续终端会话。
- 页面重新建立后，`run-20260905T060258Z-c902106f` 完成 S000–S005，下载非空库存文件，大小 217809 字节。
- 接管时确认原账号，关闭实际页面上的菜单及库存引导提示后，完成目标品牌选择并回读。将 S003 实际输出交回框架，同时仅为当次续跑替换品牌回读元素的定位器及 iframe 定位器。
- `run-20260905T061302Z-f994b26b` 从 S003 续跑成功；事件标记 S003 来源为 agent，S004、S005 来源为 program，没有重跑 S000–S002。前序输出与原记录一致，elements.toml 未修改。
- 同名下载自动生成 inventory-validation_1.xlsx，大小 217802 字节；原 inventory-validation.xlsx 的大小和修改时间保持不变。完整路径、截图和结果仅保存在忽略的运行产物中。

Windows 实机验证已授权，当前等待可连接的 Windows 环境；上述真实运行发生在 macOS。

2026-09-05 新接管入口实施后，经本次授权在 macOS 使用 `open_recovery_session` 接管原 S003 失败记录。原浏览器已关闭，入口报告 browser_adopted 为 false，保留原输入与 S000–S002 输出；Agent 显式恢复账号和商品库存页面，根据实际 DOM 临时关闭“我知道了”引导，完成原品牌选择与回读。退出后再次打开报告 browser_adopted 为 true；主动抛出一次处理异常后，仍可通过 resume 连接。临时元素和定位器没有写入应用元素库。

续跑 `run-20260905T071106Z-6b8539e4` 成功：S003 来源为 agent，S004、S005 为 program；源 result.json、原品牌及前序输出不变。下载 inventory-validation_2.xlsx，217777 字节，原下载文件大小与修改时间均保留。接管事件、截图、实际输出、定位器文件与 helper-acceptance.local.json 保存在忽略的 runs 目录。本应用 23 项离线测试也已通过。

## 主流程参数

inputs 支持 brand_value（必填，可取本地配置默认值）和 export_filename（ASCII 文件名，默认 inventory-export.xlsx）。credentials 支持 username、password、expected_identity；--download-dir 覆盖下载目录。未知字段或非法参数在启动浏览器前拒绝。显式参数优先，参数齐全时本地配置可省略。续跑保留原品牌、文件名和目录，凭据需从本次调用或本地配置重新提供。

agent 临时完成失败步时可以提交该步输出，经原 verify 校验后继续下一步；允许仅为本次续跑替换失效定位器，不改变原业务成功条件或应用文件。
