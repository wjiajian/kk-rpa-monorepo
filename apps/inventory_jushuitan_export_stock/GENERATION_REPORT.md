# 应用生成报告

## 基本信息

- 最近更新时间：`2026-09-02T16:50:14+08:00`
- 飞书需求：脱敏链接 `https://<tenant>.feishu.cn/docx/<redacted>`
- 读取 revision：`107`
- 来源指纹：`sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722`
- 应用 ID：`jushuitan.inventory.export_stock`
- 应用版本：`0.1.0`
- 当前需求哈希：`sha256:5d5392ab35e4263f015dd80e68aad443b6e5aba822b262a2babfc38c7b691ceb`
- Manifest 状态：`ready_for_push`
- 本轮范围：将实际流程验证得到的可复用资产显式晋升顶层公共库，重建应用快照和需求基线，整理诊断文件，并完成无副作用回归；本轮未重新启动真实浏览器或执行外部业务写入。开发人员已明确审核通过并授权把当前 `main` 提交、推送到 `origin/main`。

## 完整业务流程

1. `Prepare`：加载指定账号的本地配置和独立持久化 Profile，确认登录态；交互登录只能由单独授权的 `login` 命令执行。
2. `S001`：直接点击左侧库存入口，并验证库存模块状态。
3. `S002`：进入商品库存，并验证活动页签和业务 iframe。
4. `S003`：重置历史筛选，从本地配置读取目标品牌，把真实 checkbox 集合归一化为仅目标项选中；点击筛选区内的安全锚点，并确认品牌下拉层已收起。
5. `S004`：在下拉层关闭后点击搜索，验证结果表存在；搜索后再次确认仅目标品牌选中且弹层关闭。
6. `S005`：导出前再次执行同一品牌前置条件，只触发一次库存导出；下载文件必须位于本次运行目录，并返回路径、SHA-256 和字节数。
7. `Resume`：恢复前重建必要页面状态；已成功的 S005 只有在文件路径、大小和哈希仍一致时才跳过，不能重复导出。

输出仅为本地下载文件引用。应用不写 NAS、飞书多维表格、数据库或正式 Excel。

## 实际缺陷与最终行为

- 旧尝试没有证明目标品牌已经成为唯一选中项；品牌选项框也不会自行收起，继续点击搜索时可能被浮层遮挡，因而不能证明导出使用了目标筛选。未完成的大文件下载不计入成功结果。
- 当前品牌元素契约同时保存 iframe、精确选项、真实选中集合、弹层和安全收起锚点。指令会清理非目标选项、补选唯一目标项，并在搜索前后及导出前重复验证。
- 下拉层未收起、选中集合不是唯一目标、搜索不可点击、结果标识缺失或下载未完成时均失败关闭。
- 下载准备和传输共享 `300s` 预算；S005 的 `max_attempts = 1`，防止失败恢复造成重复导出。
- 人机验证专用标识在授权实测中没有出现，因此未沉淀虚构定位器。登录未达到认证标识时，程序保存证据并转人工处理。

## 公共元素、指令和应用快照

开发人员已明确授权本轮晋升。顶层公共库此前没有该平台资产，本轮新增并真实证据关联如下：

- 公共元素：`16` 个，全部为 `verified`。
  - 登录与会话：账号输入、密码输入、协议确认、密码提示确认、登录提交、认证状态。
  - 库存导航与页面：库存入口、库存模块标识、商品库存入口、商品库存页标识。
  - 筛选与导出：重置按钮、品牌选择器、搜索按钮、筛选结果标识、导出菜单、导出库存选项。
- 公共指令：`7` 条，全部为 `verified`：
  - `jushuitan.auth.login`
  - `jushuitan.auth.require_session`
  - `jushuitan.inventory.open_module`
  - `jushuitan.inventory.open_product_stock`
  - `jushuitan.inventory.select_brand`
  - `jushuitan.inventory.search`
  - `jushuitan.inventory.export_stock`
- 应用候选元素：`0`；应用候选指令：`0`；开放 `UE-*`、`UI-*` 和 `PC-*`：均为 `0`。
- 未晋升项：未出现的人机验证占位元素；被品牌选择器真实选中集合契约取代的独立品牌选中标识。
- 应用 `catalog.lock.json`：`23` 项，均为 `repository/verified`；文件 SHA-256 为 `321aaa764e1fd5e29142f658cd7eede87588d1cecec8245750283f187b0b87d9`。
- 公共源与应用锁：缺失项 `0`、额外项 `0`、版本/来源/依赖/内容哈希差异 `0`；应用快照 `23/23` 通过。
- 指令运行时只从 `ExecutionContext.services["elements"]` 获取应用冻结元素，不导入具体应用包，也不直接依赖 DrissionPage。
- `rpa-core` 升级到 `0.6.0`：目录资产复制与哈希排除 Python 自动生成的 `__pycache__`、`.pyc` 和 `.pyo`；其他意外文件仍会触发完整性失败。

## 需求基线变化

- `REQUIREMENT_MEMORY.md` 是唯一人工可编辑基线，`requirement.spec.json` 已由其机械生成。
- 当前 Memory、Spec 和 Manifest 的 revision 与需求哈希完全一致；字段差异为 `0`。
- 已关闭 16 个元素候选和 7 个指令候选门禁；开发人员明确审核后，`app.toml` 已更新为 `ready_for_push`。
- 原候选基线哈希为 `sha256:8a86352eedbbbdfbf03bbade09c4766800d34598cadc232d3c513ecf183ac2f2`；晋升后的正式哈希为 `sha256:5d5392ab35e4263f015dd80e68aad443b6e5aba822b262a2babfc38c7b691ceb`。
- 本次哈希变化记录候选解析、冗余引用删除和公共来源锁定，不表示重新读取了新的飞书 revision。

## 文件和目录整理

- 新增公共源：`elements/jushuitan/erp/**` 的 16 个元素 TOML，以及 `instructions/jushuitan/erp/**` 的 7 组 `instruction.py + instruction.toml`。
- 重建应用快照：`src/inventory_jushuitan_export_stock/elements/**`、`instructions/**` 和 `catalog.lock.json`。
- 更新程序：`cli.py`、`program.py`、`steps.py`、`real_runtime.py`、元素/指令注册表和验证入口。
- 更新契约与环境：`app.toml`、Memory、Spec、`pyproject.toml`、`uv.lock`、README、配置忽略规则和本报告。
- 更新框架：浏览器精确多选、浮层收起、下载预算、证据命名、目录快照哈希及相应测试；同步框架设计和 BrowserActions 契约文档。
- 更新测试：Fake Browser 流程、精确品牌选择、搜索前后重验、下载失败关闭、恢复幂等、真实运行授权门禁和公共目录闭包。
- 删除应用内两个无效候选元素、7 个不属于目录资产契约的能力级 `__init__.py`、`requirement/assets/.gitkeep`、旧的 `runtime/c1_live_validation.py` 及其孤立字节码。
- 保留 V2 应用必须的报告、README、Manifest、Memory/Spec、配置 Schema、快照锁、程序源码、测试和独立依赖锁。真实配置、Profile、需求截图、运行产物和证据继续保存在 Git 忽略目录，不纳入程序提交面。

## 已有真实 Preview 证据

- 授权批次：`patch-c-verify-20260901`。
- 运行 ID：`patch-c-preview-20260902`。
- 授权范围：本应用、`STORE_001`、登录态确认、库存导航、商品库存、候选验证、配置品牌筛选和一次库存下载；禁止 NAS、飞书、数据库、正式 Excel及其他业务提交写入。
- 检查点：Prepare 与 S001–S005 均为 `succeeded`。
- 筛选证据：搜索前只有目标 checkbox 被选中；安全收起后弹层不可见；搜索按钮实际收到一次点击；搜索后仍为唯一目标且弹层关闭。
- 下载产物：`runs/<run_id>/downloads/inventory-export.xlsx`，`218167` bytes，SHA-256 为 `040d5ba474ca4eba126bd1ba308a255e77ae0831f73176516126e7dda4d205d0`。
- 幂等 Resume：同一运行 ID 再次恢复时 S001–S005 全部跳过，文件 inode、大小、修改时间和 SHA-256 均未变化，没有重复导出或下载。
- 浏览器清理：运行结束后调试端口 `9301` 无监听，端口租约已释放。
- 外部业务写入：`false`。

该 Preview 在晋升前的正式需求哈希下完成。晋升时仅整理资产来源、解析状态和依赖注入边界，业务动作与验证条件保持一致，并通过完整 Fake 回归；本轮没有用新哈希再次启动真实浏览器，因此不把既有证据描述为“新哈希下的第二次 Preview”。

## 本轮测试与门禁结果

- 应用无副作用测试：`20 passed`。
- `rpa-core` 回归：`138 passed`。
- 合计：`158 passed`。
- Memory/Spec 字段差异：`0`；计算哈希与三处声明一致。
- 公共目录发现：`23` 项（16 元素、7 指令）；依赖闭包和应用锁完全一致。
- 应用报告：`ok = true`，issue `0`；架构边界 issue `0`；敏感内容 issue `0`。
- `rpa-app doctor`：退出码 `0`，Python `3.12.13`、`rpa-core 0.6.0`、快照有效，`real_browser_launched = false`。
- `rpa-app check`：退出码 `0`，无开放门禁。
- 未带新授权的 `login` / `verify-candidates`：退出码 `4`，均在浏览器启动前以 `real_browser_authorization_required` 拒绝。
- 应用与 `rpa-core` 的 `uv lock --check`：通过。
- Schema 漂移测试、语法导入、Fake Browser、失败恢复、架构扫描、敏感信息扫描、忽略路径检查和 `git diff --check`：通过。
- 本轮真实浏览器测试：未运行；沿用并明确限定上述既有 Preview 证据。
- Live：未授权、未运行；应用需求也不包含外部业务写入。

## 当前结论与剩余门禁

- 业务程序：完成。
- 公共资产晋升：完成。
- 应用快照与需求基线：完成并一致。
- 无副作用测试：完成并通过。
- 授权真实 Preview：此前已完成；本轮未重复执行。
- 开发人员审核：已明确通过；记录为 `reviews/20260902T165014+0800.toml`，覆盖当前应用、需求哈希、既有 Preview 证据和本轮测试结果。
- 业务验收：未声明通过。
- 提交或推送条件：满足；开发人员已授权提交全部需求相关修改，并把当前 `main`（含既有 `5c1f95d`）推送到 `origin/main`。
- 新建分支：否；PR、部署：不在本次授权范围内，均不执行。
- 本报告完成时本轮修改尚待形成新提交；最终提交和推送结果以执行回执为准。
