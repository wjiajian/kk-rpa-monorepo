# 聚水潭库存导出 RPA

从需求 revision 107 生成的独立应用。使用指定账号的独立持久化 Profile，登录并核对目标账号后进入商品库存，按本地配置的品牌精确筛选并下载库存文件。

当前版本 `0.4.0`，Manifest 状态 `ready_for_review`。

> [!IMPORTANT]
> **0.3.0 的"品牌筛选已验证"结论不成立。** 那一版的 S003 是假执行器（回显输入、从不回读页面），S004 是假验证器（`css:table tbody` 在搜索前就存在 —— 2026-09-03 实测搜索前后同为 21 行）。整条 S003 → S004 → S005 链路从未确认过筛选生效，S005 可能导出的是全量库存。
>
> 0.4.0 把断言改为回读页面状态，并为每个 Step 补了必须失败的反例。2026-09-03 的真实 Preview（`preview-20260903T090704Z`）已完成 S001–S005：S003/S004 从 DOM 回读到的选中品牌恰好等于配置品牌，下载 218,251 字节 XLSX，未执行任何外部业务写入。`latest_review` 仍为空，等待开发人员审核。详见 [GENERATION_REPORT.md](GENERATION_REPORT.md)。

## Step 断言

| Step | 验证依据 |
| --- | --- |
| S001 打开库存模块 | `module_marker`（带 `current___`，表示模块真的激活） |
| S002 进入商品库存 | `page_marker`（页签处于 active 状态） |
| S003 选择品牌 | **回读** `brand_selected_option`，选中集合恰好等于配置品牌 |
| S004 搜索并验证筛选 | 结果行数 > 0 **且** 搜索后回读的选中品牌仍恰好等于配置品牌 |
| S005 导出 | 文件在本次 run 的 `downloads/` 内、非空、哈希可复现 |

S004 在**重新归一化之前**先回读平台留下的选中状态。0.3.0 直接重选品牌，把平台可能的重置盖掉了 —— 界面看起来对，结果表可能未筛选。所以 **0.4.0 的 S004 有可能在真实运行中失败，而那个失败是正确的**。

每个 Step 提供至少一个假页面状态，`rpa-app test` 在该状态下真跑一遍 `execute()`，要求它抛错或 `verify()` 返回 `False`。共 16 个反例。

## 本地配置

```bash
cp config/stores.example.toml config/stores.local.toml
cp .env.example .env
```

只在 Git 忽略的本地文件中填写真实值：

- `.env`：账号、密码，以及可选的页面可见账号身份文本；
- `config/stores.local.toml`：品牌、Profile、debug port 和可选 `identity_env`；未配置 `identity_env` 时使用登录账号作为期望身份文本；
- 每个账号必须使用独立 Profile、debug port、run directory 和 lock。

不要把原飞书文档中的凭据复制到源码、测试、报告或 Git。

## 无副作用检查

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
```

`doctor` 和 `check` 都是只读检查，`test` 只使用 Fake Browser 和临时 Authorization Store，不启动真实浏览器，也不创建应用真实 Authorization Record。

## Authorization 流程

日常执行 Preview 只需要：

```bash
uv run rpa-app preview --account STORE_001
```

CLI 会自动生成 `run_id` 和 `authorization_id`。确认页只保留账号、会发生的真实动作和 `external_writes`：

```text
即将执行 Preview：STORE_001
会真实登录、查询和下载；external_writes: []
确认执行本次 Preview？[y/N]
```

输入 `y` 后，CLI 才会为这个 exact scope 创建 300 秒 grant，并立即 claim 和 run。直接回车、输入其他内容或按 Ctrl-C 会取消，并把刚创建的 request 标记为 `REVOKED`；不会创建 run directory 或启动真实浏览器。快捷入口只接受交互式终端，不提供 `--yes`；CI 或脚本必须使用下面的完整接口。

底层规则没有省略：所有真实浏览器命令仍要求 exact `run_id` 和 `authorization_id`，并遵循 request → inspect → grant → claim → execute。Authorization Record 保存在 Git 忽略的 `runtime/authorizations/`；store 被限制在 Application directory boundary 内并拒绝 symlink ancestor。scope 创建后不可变，claim 是 atomic 且 single-use。

以下是自动化、CI 和排障时使用的完整流程。先创建 Preview run request：

```bash
uv run rpa-app authorization request \
  --operation run \
  --mode preview \
  --account STORE_001 \
  --run-id <new_run_id> \
  --requested-by <developer_id>
```

检查输出中的完整 `scope` 和 `scope_digest`。scope 固定 application/program version、requirement/catalog digest、operation/mode、run/account/profile、allowed origins、steps、browser actions、elements、candidate refs 和 external writes；`profile_id` 是实际 Profile directory 的本地 SHA-256 fingerprint，不是账号别名。确认无误后，用输出中的 exact `authorization_id` 与 exact `scope_digest` grant；`ttl_seconds` 必须在 1–3600 之间：

```bash
uv run rpa-app authorization grant \
  --authorization-id <authorization_id> \
  --scope-digest <sha256_digest> \
  --authorized-by <reviewer_id> \
  --approval-reference <approval_reference> \
  --ttl-seconds 300
```

然后在 TTL 内执行同一 exact scope：

```bash
uv run rpa-app run \
  --mode preview \
  --account STORE_001 \
  --run-id <same_run_id> \
  --authorization-id <same_authorization_id>
```

执行时，应用先以 exact scope atomic claim Authorization Record，再创建 run directory、读取 credentials 和构造 `BrowserManager`；紧邻 Browser launch 前还会重新检查 Profile fingerprint、Resume checkpoint 和 expiry。`AuthorizedBrowserActions` 在每次调用前后校验顶层 URL，并校验当前 Step、Action 和 Element；固定业务 iframe 由应用冻结的 `ElementSpec.frame_locator` 定位，不再要求其 Origin 单独出现在 `allowed_origins`。claim 前发现的 scope mismatch、expired/revoked/ungranted record 或已消费 record 都不会启动真实浏览器。

快捷入口用当前本机用户名填写 `requested_by` 和 `authorized_by`，用自动生成的 Run ID 建立 `approval_reference`。这些都是 developer-local audit fields，不是 cryptographic identity proof。只有开发人员本人在 scope 后输入 `y`、亲自执行完整 grant，或在当前对话中明确授权 AI 代为 grant，才算 Developer Authorization。

其他 operation 使用相同的 request/grant 顺序：

```bash
# 单独建立或确认登录态
uv run rpa-app authorization request --operation login --mode preview --account STORE_001 --run-id <login_run_id>
uv run rpa-app login --account STORE_001 --run-id <login_run_id> --authorization-id <login_authorization_id>

# 从失败 checkpoint 恢复：沿用原 run_id，但必须创建新的 RESUME record
uv run rpa-app authorization request --operation resume --mode preview --account STORE_001 --run-id <existing_run_id>
uv run rpa-app resume --mode preview --account STORE_001 --run-id <existing_run_id> --authorization-id <new_resume_authorization_id>
```

RESUME scope 会固定 canonical `resume_checkpoint_digest` 和首个待恢复 `resume_step_id`。如果 checkpoint 在 claim 前变化，exact claim 会拒绝，record 保持 `granted`；如果它在 claim 后的启动窗口变化，Runner 会在持有 `.run.lock`、重新读取 checkpoint 后，并在 `Program.prepare()` 前再次拒绝，record 已消费并最终记为 `failed`，不会执行 Program action。

`verify-candidates` request 会绑定 request 当时 `catalog.lock.json` 中 exact `candidate_asset_refs`。当前快照全部为 `verified`，没有 candidate，因此 request 会返回 `candidate_scope_empty`，不会启动浏览器。将来应用再次引入 candidate 后，命令形式为：

```bash
uv run rpa-app authorization request --operation verify-candidates --mode preview --account STORE_001 --run-id <candidate_run_id>
uv run rpa-app verify-candidates --account STORE_001 --run-id <candidate_run_id> --authorization-id <candidate_authorization_id>
```

Candidate verification 只接受 fresh run，不提供 `--resume`。如果验证失败，需要修正候选项后使用新的 `run_id` 和新的 `operation=verify_candidates` Authorization Record，避免把 fresh verification 与 checkpoint recovery 混成同一个 scope。

当前应用没有 external business write。`authorization request --mode live`、`run --mode live` 和 `resume --mode live` 都固定返回 `application_live_unsupported`，不会创建可执行的 Live authorization，也不会启动浏览器。Core 的 Live adapter 要求 separately granted durable Authorization Record，并在 adapter boundary 逐条 claim exact `write_id`、`step_id`、`adapter`、`target`、`data_scope`、`expected_record_count` 和 `payload_digest`；写后还必须按 exact `target` 和 `data_scope` 独立 read back，只有 `record_count` 与 canonical `payload_digest` 都匹配才能标记 `SUCCEEDED`。旧 `LiveWriteGrant` 单独不能执行 Live。

## 失败诊断

交互式 `rpa-app preview` 失败时只在终端显示不超过约 7 行的定位摘要：`step_id` / `instruction_id`、`root_cause`、安全 `message`、业务触发位置、框架抛错位置、详细日志路径和 `run_id`。例如：

```text
Preview failed — S003 / jushuitan.inventory.select_brand
  root_cause: BrowserOriginNotAuthorizedError (browser_origin_not_authorized)
  message: browser origin is not authorized
  triggered_at: apps/.../select_brand/instruction.py:42 (execute)
  raised_at: packages/rpa-core/.../authorization.py:1288 (authorize_browser_origin)
  details: runs/<run_id>/error-diagnostics-<timestamp>-<id>.json
  run_id: <run_id>
```

此前两次 S003 失败分别暴露了 iframe 短暂空白和逐 frame Origin 授权问题。当前按内部工具的实际风险简化，只保留顶层站点、Step、Action 和 Element Gate；运行 `preview-20260903T062356Z-df357a62` 已确认 S003–S005 可以继续并成功完成。

完整 diagnostics JSON 保存在对应 run directory，包含：

- `root_cause`：最内层错误的 `type`、稳定 `error_code`、安全 `message`，以及 `file`、`line`、`function`、`code`；
- `exception_chain`：从 Root Cause 到最外层 Application Error 的完整包装关系；
- `traceback`：逐帧结构化调用位置，并用 `exception_index` 关联到 `exception_chain`；
- `exception_chain_truncated` / `traceback_truncated`：极长诊断是否被安全截断。

显式 `authorization`、`login`、`verify-candidates`、`run` 和 `resume` 命令继续输出完整机器 JSON，避免改变自动化接口。文件位置使用 repo-relative path。日志不序列化局部变量；内置或第三方异常可能携带页面值、Locator 或 Credential，因此其 `message` 和源码行会明确标记为 redacted，本机绝对路径也不会输出。项目内带稳定 `error_code` 的异常会显示安全错误信息和源码行。

这项诊断只对更新后的新运行生效。旧运行若当时只输出了外层 `instruction_execution_failed`，已经丢弃的底层异常不能由旧 JSON 反向恢复；下一次失败会直接显示实际 Root Cause 和出错行。

## 业务流程

```text
Prepare 打开登录入口并检查会话
→ 会话失效时在同一次运行中使用目标账号凭据登录
→ 比对页面身份文本与本地期望账号
→ S001 打开库存模块
→ S002 进入商品库存
→ S003 精确归一化为仅选中本地配置品牌
→ 安全点击筛选区空白输入框并验证品牌下拉层已收起
→ S004 点击搜索并验证筛选
→ S005 导出并验证下载文件
```

如果登录失败、需要 human verification、页面账号身份不匹配、品牌下拉层未收起、选中集合不是唯一目标、搜索按钮不可点击、结果表标识缺失或下载未完成，流程会截图并失败关闭，不会继续导出。应用不写 NAS、飞书多维表格、数据库或正式 Excel；Preview 只执行页面读取、筛选和本地下载，不表示 external business write 或业务验收通过。

## 0.4.0 下一步

1. ~~在干净环境用 `uv sync --locked` 执行无副作用检查~~（285 项通过）
2. ~~跑 `rpa-app verify-elements`~~（已完成：6 个阶段全到达，19 项 0 失效）
3. ~~跑一次真实 Preview~~（已完成：S001–S005 全部通过）
4. **由开发人员审核 0.4.0、Requirement Hash 和本次 Preview run。** `latest_review` 和 `ready_for_push` 在那之前没有依据 —— AI 不得自行设置。

0.3.0 运行 `preview-20260903T062356Z-df357a62` 的 checkpoint、截图和下载物保留为历史证据（Git-ignored），但它签署的"筛选已验证"结论不适用于 0.4.0。
