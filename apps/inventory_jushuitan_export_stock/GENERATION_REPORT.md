# 应用生成报告

## 基本信息

- 最近更新时间：`2026-09-03T14:38:49+08:00`
- 飞书需求：脱敏链接 `https://<tenant>.feishu.cn/docx/<redacted>`
- 读取 revision：`107`
- 来源指纹：`sha256:d4e454239bfd451dc4a0147c3ac693209f947adb41ed2c52dfe6cd6b96f83722`
- 应用 ID：`jushuitan.inventory.export_stock`
- 应用版本：`0.3.0`
- 当前需求哈希：`sha256:b073ce710e447aa0d76afec300f89f69a47eb8a29f678788ea0369054001982e`
- Manifest 状态：`ready_for_push`
- 本轮目标：删除应用内静态 Authorization Batch Constants，接入 `rpa-core==0.7.0` 的 durable、exact-scope、single-use Authorization API，提供一次确认即可运行的交互式 Preview 快捷入口，让失败摘要既能快速定位又不在终端展开完整 Exception Chain，并按内部工具的实际风险简化确认页与 iframe Origin Gate。
- 实现工作没有代替开发人员发起真实运行。开发人员随后执行 0.3.0 Preview `preview-20260903T062356Z-df357a62`：真实浏览器已启动，S001–S005 全部成功，生成本地 XLSX 和成功截图；Authorization Record 为 `succeeded`，未执行 Live 或 external business write。

## 完整业务流程

1. `Prepare`：打开登录入口，复用正确会话或自动登录，并验证当前页面身份属于命令指定账号。
2. `S001`：直接点击左侧库存入口并验证库存模块状态。
3. `S002`：进入商品库存并验证活动页签和业务 iframe。
4. `S003`：重置历史筛选，把真实 checkbox 集合归一化为仅本地目标品牌选中；使用安全锚点收起品牌下拉并验证不可见。
5. `S004`：点击搜索，验证结果表、唯一目标品牌选中状态和下拉层关闭状态。
6. `S005`：导出前再次验证品牌前置条件，只触发一次库存导出；等待下载完成并返回路径、SHA-256 和字节数。
7. `Resume`：重新执行登录与身份验证，重建失败步骤所需页面状态；已验证的既有下载不会重复导出。

业务步骤、elements、instructions 和输出目标未改变。输出仍只包含本地下载文件引用，不含 NAS、飞书多维表格、数据库或正式 Excel 写入。

## Authorization 实现

- 新增 developer-local 子命令 `rpa-app authorization request|grant`，不改变 `app.toml` 中标准 commands 的字面值。
- 新增 `rpa-app preview --account <account>` convenience command：自动生成安全的 `run_id`/`authorization_id`，确认页只显示 Account、真实登录/查询/下载提示和 `external_writes`，经一次 TTY `y` 确认后按原 Contract 完成 request、grant、claim 和 run；完整 immutable scope 仍保存在 Authorization Record，TTL 固定为 300 秒。
- 快捷入口不接受 `--yes`，非交互环境在创建 request 前以 `interactive_confirmation_required` 失败关闭；取消会把未 claim request 持久化为 `revoked`，且不创建 run directory、不启动 browser。显式 request/grant 仍保留给 CI、自动化和排障。
- `request` 根据运行时真实契约构造不可变 `AuthorizationScope`，返回完整 scope 与 `scope_digest`，但不创建 run directory、不读取 credentials、不启动 browser。
- `grant` 强制要求 exact `scope_digest`、`authorized_by`、`approval_reference` 和 `ttl_seconds`；应用 TTL 范围为 1–3600 秒。
- `login`、`verify-candidates`、`run`、`resume` 全部强制要求 `--run-id` 与 `--authorization-id`。
- scope 固定 `app_id`、`app_version`、`program_id`、`program_version`、`requirement_hash`、semantic `catalog_digest`、`operation`、`mode`、`run_id`、`resume_checkpoint_digest`、`resume_step_id`、`account_id`、Profile-directory-derived `profile_id`、`allowed_origins`、`step_ids`、`browser_actions`、`element_ids`、`candidate_asset_refs`、`external_writes` 和 `source_preview_run_id`。
- execution 在创建 run directory、读取 credentials 和构造 `BrowserManager` 之前调用 `AuthorizationStore.claim()`；claim 使用 Core record lock 完成 atomic transition，record 只能消费一次。
- Authorization Store 使用 Application directory 作为 trusted boundary，拒绝 path escape、symlink ancestor 和非目录组件；`profile_id` 是 resolved Profile directory 的 SHA-256 fingerprint，因此修改 `profile_directory` 不能沿用旧 grant。
- execution 紧邻 `BrowserManager.start()` 前再次检查 session expiry；过期 session 不启动 Browser。
- `ExecutionContext.services` 同时注入 `authorization` session 和 `AuthorizedBrowserActions`；标准 wrapper 在每次 Browser Boundary 前后校验 top-level Origin，并校验 Step、Action 和 Element。固定业务 iframe 由冻结 locator 约束，不再单独执行 Origin allowlist。
- execution success/failure 会把 claimed record 写为 `succeeded`/`failed` 并保存 error code 与 run-relative evidence refs；进程在 claim 后崩溃则保留不可复用的 `claimed` record。
- standard `resume` 沿用原 `run_id` 与 checkpoint，但 scope 使用 `operation=resume`，绑定 canonical `resume_checkpoint_digest` 和首个待恢复 `resume_step_id`，且必须是新的 Authorization Record。claim 前发生变化会拒绝且不消费 record；claim 后除 Browser launch 前复核外，Runner 还会在持有 `.run.lock` 并重新读取 checkpoint 后核对 digest、recovery step 和 execution identity，任何 mismatch 都在 `Program.prepare()` 前失败关闭并把已消费 record 记为 `failed`。
- `verify-candidates` scope 绑定 request 时 `catalog.lock.json` 中全部 exact `candidate_asset_refs`。当前 24 项均为 `verified`，所以该 request 以 `candidate_scope_empty` 失败关闭；为避免 fresh verification 与 recovery 共用无法区分的 scope，candidate `--resume` 已移除。
- Core `PreviewFeishuService` 的 Live path 现在必须持有 durable `AuthorizationSession`，按实际 payload 逐条 claim exact `ExternalWriteScope`；backend 必须提供独立 `read_back_base()`，按 exact `target`/`data_scope` 回读，只有 `record_count` 与 canonical `payload_digest` 同时匹配才记录 `SUCCEEDED`，异常、非法结果或 mismatch 均记录 durable `UNKNOWN`。旧 `LiveWriteGrant` 单独不足以越过 adapter boundary。
- 当前应用没有 external business write，所有 Live request/run/resume 均在 Authorization creation/claim 和 browser launch 前返回 `application_live_unsupported`。
- DrissionPage adapter 保留可选的 same-context guard 接口，供更严格的集成显式使用；当前标准 `AuthorizedBrowserActions` 不再注入该 guard。当前风险边界信任固定应用中冻结 locator 指向的业务 iframe；若未来接入第三方或不可信页面，需要重新引入 per-frame policy。未被 Manager 接管的新 tab 仍不在可观察范围内。
- `BrowserStartError.real_browser_launched` 会在 Chromium object 已返回后发生初始化失败时如实标记并清理；trusted Chromium constructor 若在返回 object 前已启动进程后直接抛错，caller 无法只凭异常确认短暂 launch，进一步收紧需 process/port-level observability。

## 失败诊断实现

- Core 新增 `exception_diagnostics()`；它会忽略 adapter 解包原始 cause 时产生的双向 Python exception-context cycle，确保真正的底层异常仍是 `root_cause`。
- 交互式 Preview 失败只显示约 7 行：Step/Instruction、Root Cause、safe message、app trigger location、framework raise location、details path 和 Run ID。完整 diagnostics 使用独占创建和 `0600` 权限写入 `runs/<run_id>/error-diagnostics-<timestamp>-<id>.json`，不会覆盖同一 run 的既有证据。
- 显式机器命令继续保留原有字段，并输出 `diagnostic_schema_version`、`root_cause`、root-cause-first `exception_chain`、结构化 `traceback` 和截断标志，保持自动化兼容。
- 每个可信项目异常显示稳定 `error_code`、安全单行 `message`，以及 repo-relative `file`、`line`、`function` 和 `code`；异常包装关系通过 `exception_index` 可追踪。
- 不序列化 frame locals。内置/第三方异常的 message 与 source line 失败关闭为 redacted；site-packages 和其他外部绝对路径被规范化，避免 Credential、页面运行值与本机路径泄露。
- 旧 Preview 输出中未持久化的底层异常无法追溯恢复；该能力适用于更新后的新运行。本轮没有为验证日志而启动真实 Browser。

## S003 失败与简化

- `preview-20260903T054937Z-69c6b05a` 在 S003 第一个 reset click 前失败；diagnostics 显示业务 iframe 已被解析，但其 document URL 当时还不是 HTTP(S) origin，因此错误发生在品牌 locator lookup 之前。
- diagnostics 未保存当时 URL 的精确值，不能把 `about:blank` 写成已证实事实；结合两次 attempt 均在 9–21ms 内失败，临时空白 document 是当前最符合证据的解释。
- 公共 DrissionPage adapter 随后对该短暂加载窗口加入了有界等待。下一次运行 `preview-20260903T060531Z-97c4f3de` 中 S001 用时 1086ms、S002 用时 622ms 并成功，S003 第一次 attempt 1326ms 后失败、第二次 attempt 8ms 后失败；Root Cause 已变为 HTTP(S) Origin 不在 allowlist，说明流程越过了原临时空白阶段。
- 本机 Profile 状态把商品库存业务页记录为 `https://src.erp321.com/erp-web-group/erp-scm-goods/stockInventoryManagement`，而 Authorization scope 只有顶层 `https://www.erp321.com`，与最新错误一致。
- 经开发人员确认，当前应用按固定流程内部工具处理：不把 `https://src.erp321.com` 追加为逐 iframe 权限，也不再对 iframe Origin 单独授权；只保留 top-level Origin、Step、Action、Element、账号、Profile、single-use claim 和 Preview external-write Gate。
- 应用 instruction、elements、Requirement Spec 与 `catalog.lock.json` 均未改变。简化后的运行 `preview-20260903T062356Z-df357a62` 已完成 S001–S005：S003 在第二次 attempt 成功，S004、S005 随后成功；应用先进入 `ready_for_review`，随后取得当前版本 Developer Review 并进入 `ready_for_push`。

## 0.3.0 Preview 成功证据

- Run ID：`preview-20260903T062356Z-df357a62`；Account：`STORE_001`；Authorization ID：`auth-preview-20260903T062356Z-df357a62`；Authorization 状态：`succeeded`。
- Authorization Scope Digest：`sha256:04ff52afa6e124f0c46fa0373bb1b19612fbbbf0fc2f73ca7792ee9b9fc436c5`；Requirement Hash 与当前 Manifest 同为 `sha256:b073ce710e447aa0d76afec300f89f69a47eb8a29f678788ea0369054001982e`。
- Checkpoint 状态：`succeeded`；S001、S002、S004、S005 各 1 次成功，S003 第 2 次 attempt 成功；`skipped_steps = []`。
- 下载：`runs/<run_id>/downloads/inventory-export.xlsx`，218,378 字节，SHA-256 `sha256:b39e6b23dda9bf1f8415ab2d524afa2435ae9126aca33f9542cc19f4412e29c6`；本地复算哈希一致，XLSX ZIP 结构校验通过。
- 成功截图：`runs/<run_id>/evidence/preview-succeeded-20260903T062431462313Z-d2d1e0943a48432a971330ee64b916f0.png`，780,469 字节，SHA-256 `sha256:c2ea3cc8eb134d5e52f26584e49f9bd9ff34d5a7d49d33f6d7e30eba6aecd1c6`；本地复算哈希一致。
- `external_business_writes_executed = false`；Authorization `external_writes = []`。运行目录和 Authorization Record 均经 `.gitignore` 排除，不进入提交。

## 元素、指令与快照

- 应用快照仍为 24 项：17 个 verified elements、7 个 verified instructions，来源均为 `repository`。
- `catalog.lock.json` 字节级 SHA-256 仍为 `sha256:1cb599b6a4e40ae11654fc4888f6ef35dc1e8b82ad6406719ac8ffdb06076eeb`，本轮未修改任何 snapshot item 或 lock byte。
- Authorization scope 中的 `catalog_digest` 由 Core 对验证后的 semantic CatalogLock 计算，并排除 `copied_at`；它不是上面的 raw file digest。
- 开放 `PendingConfirmation`：0。
- 开放 `UnresolvedElement`：0。
- 开放 `UnresolvedInstruction`：0。
- 当前 candidate assets：0；因此 `verify-candidates` 不具备可授权的候选范围。

## Requirement Memory、Spec 与版本

- `REQUIREMENT_MEMORY.md` 是本轮人工可读基线；canonical block 与 `requirement.spec.json` 同步更新到 0.3.0。
- Authorization requirements 使用 public API 的 English field names，Memory/Spec semantic diff 为 0。
- 规范化需求哈希从 0.2.0 的 `sha256:2ecfe62d15e2cbc3ae180b4e0acf3ca3cd3e1b5aa6bab1e330f41ba4c8687f14` 更新为当前 `sha256:b073ce710e447aa0d76afec300f89f69a47eb8a29f678788ea0369054001982e`。
- `app.toml`、Python package、Program 和 project version 均更新为 `0.3.0`；`pyproject.toml` pin 更新为 `rpa-core==0.7.0`。
- `packages/rpa-core/uv.lock` 与应用 `uv.lock` 已刷新，分别锁定 `rpa-core==0.7.0` 和应用 `0.3.0`；两处 `uv lock --check` 均通过。

## 修改文件

- 应用元数据与依赖：`app.toml`、`pyproject.toml`、`src/inventory_jushuitan_export_stock/__init__.py`、`program.py`。
- 应用锁文件：`uv.lock`。
- Authorization 与 CLI：`real_runtime.py`、`cli.py`。
- Requirement：`requirement/REQUIREMENT_MEMORY.md`、`requirement/requirement.spec.json`。
- 测试：`tests/helpers.py`、`tests/test_real_runtime.py`、`tests/test_contracts_and_gates.py`。
- 文档：`README.md`、`GENERATION_REPORT.md`。
- Review：新增 `reviews/20260903T143849+0800.toml`；历史记录不覆盖。
- 公共 Core：`packages/rpa-core` 的 Authorization Contract、Runtime/Browser Boundary、Error Diagnostics、Schema、Tests、README、Version 和 `uv.lock`。
- 仓库文档：根 `README.md`、`CONTEXT.md`、`docs/rpa-framework-design.md`、`llm-wiki/README.md`、`llm-wiki/03-browser-actions-contract.md` 和 `llm-wiki/decisions/ADR-027-unified-real-run-authorization.md`。
- 未修改：`catalog.lock.json`、应用 snapshot elements/instructions、`reviews/20260902T165014+0800.toml`、`reviews/20260903T095809+0800.toml`。

## 自动测试与门禁

- 应用全套测试：`51 passed`。
- 新增/更新覆盖：Authorization request/grant/revoke、交互式 Preview 的 request→grant→run 顺序、两行确认页、取消 revocation、non-TTY refusal、pre-request Gate、exact scope content、Profile fingerprint mutation refusal、candidate ref binding、empty candidate refusal、candidate resume refusal、scope mismatch、atomic claim 顺序、single-use replay、post-claim setup failure、pre-launch expiry、Browser 启动后异常的真实 launch audit、checkpoint digest/step binding、claim 前 mutation non-consumption、Browser 启动窗口 mutation 的 Runner under-lock refusal、same-run-id/new-RESUME-record、Live unsupported、CLI required arguments 与参数映射，以及 Runtime failure summary、完整 diagnostics 持久化、Source Line 和绝对路径脱敏输出。
- `rpa-core` 全套测试：`178 passed`；包括 top-level Origin 前后校验、iframe Origin 不单独授权、可选 same-context guard 的临时 `about:blank` 处理、Resume under-lock binding、Live independent Read-back Verification 的 success/unknown/fail-closed 路径、trusted chained error 的源码定位、untrusted error 的 secret/path redaction，以及解包 transport exception cycle 后的正确 Root Cause。
- `rpa-app check`：退出码 0，`issues = []`。
- Python compile check：通过。
- `git diff --check -- apps/inventory_jushuitan_export_stock`：通过。
- Memory/Spec semantic diff：0；computed hash 与 Memory、Spec、Manifest 一致。
- `catalog.lock.json` raw SHA-256：保持 `1cb599...76eeb`。
- 两份历史 review 文件 raw SHA-256：保持 `f210a3...8574` 与 `6f81d6...57f1`。
- `uv lock --check`：公共 Core 与当前应用均通过。
- 真实 browser test：开发人员发起的 0.3.0 Preview `preview-20260903T062356Z-df357a62` 已成功；S001–S005 全部完成，下载与成功截图哈希复算一致。对应 Authorization Record 为 `succeeded` 且不可重放；未执行 external business write。
- external write preview：需求不要求。
- Live：应用不支持，未运行。

## 历史证据边界

- 0.2.0 运行 `account-session-preview-20260903` 曾完成 Prepare、S001–S005、目标品牌筛选和一次本地 XLSX 下载，并完成同 run ID checkpoint resume；未执行 external business write。
- 历史下载为 218,367 字节，SHA-256 `sha256:bcd6cc8e21af97f2c81d8d2d75e7bdeb0955b5cb17fca3ef86d9448897ec9cc9`；只读检查为 1,331 行（含表头）、47 列，与页面 1,330 条结果一致。
- 历史 review records `reviews/20260902T165014+0800.toml` 和 `reviews/20260903T095809+0800.toml` 保留且未覆盖。
- 因 0.3.0 的 program version、requirement hash 和 authorization boundary 已变化，以上证据不能替代 0.3.0 的新 Authorization、真实 Preview 或 developer review。

## 当前结论与下一步

- Authorization 代码迁移与离线验证：完成。
- 当前状态：`ready_for_push`。
- `latest_review`：`reviews/20260903T143849+0800.toml`；两份历史 review 保留。
- Developer Review：已明确审核应用 `jushuitan.inventory.export_stock` 0.3.0、Requirement Hash `sha256:b073ce710e447aa0d76afec300f89f69a47eb8a29f678788ea0369054001982e` 和 Preview Run `preview-20260903T062356Z-df357a62`，并授权提交推送。
- 提交/推送：全部门禁满足；本报告记录的是提交前状态，Git 执行结果由对应 Commit 和 Remote Branch 留痕。
