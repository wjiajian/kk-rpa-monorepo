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

## 完成与运行方式

账号、品牌和库存报表正确，文件成功下载且非空即完成；不检查表格内部业务数据。本应用没有飞书、数据库、NAS 或正式 Excel 写入。

使用共享 CLI 的 doctor、test、verify-elements、run、resume。正式 run 按配置无人值守执行，从 S000 开始。失败保留浏览器和结果，agent 修复后选择恢复步骤；resume 沿用原品牌、文件名和已完成结果。

下载目录可指定；默认 `../../runs/downloads`，相对应用目录解析，与京麦共用。新 run 和 verify-elements 前清空，resume 保留已有文件，日志和截图保留在本应用 `runs/<run_id>`。

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

本次迁移后的真实浏览器验证：**等待授权**。上述旧版证据不替代当前版本验收。
