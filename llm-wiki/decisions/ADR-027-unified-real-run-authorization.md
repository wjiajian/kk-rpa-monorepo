# ADR-027：统一 Real Run Authorization

- 状态：已接受
- 日期：2026-09-03

## 背景

真实浏览器操作需要开发人员明确授权，但首个应用仍使用 application-local batch constants 分别保护 `login` 和 `verify-candidates`，标准 Preview 也缺少同一套可审计的 invocation boundary。静态常量无法表达 Application Version、Requirement Hash、Command、Run、Account、Profile、Site、Steps 和 Actions，也不能可靠阻止过期授权或重复调用。

Real Run Authorization 与 External Write Authorization 是不同校验边界。Preview 与 Live 使用不同的、分别由开发人员 grant 的 Authorization Record；Live Record 同时声明 invocation scope 和开发人员审核过的 exact external write scopes。取得 Live invocation claim 仍不能跳过 adapter boundary 的逐项 write claim。

## 决策

所有真实 invocation 使用统一的 `Authorization Record` 和 `Authorization Claim`：

```text
Developer Authorization
→ Authorization Record
→ single-use Authorization Claim
→ Real Browser launch
→ Preview or Live execution

Live external write
→ nested exact External Write Authorization claim
→ external adapter boundary
```

- `login`、`verify-candidates`、Preview `run`、Preview `resume` 以及未来 Live invocation 都必须在 Browser launch 前完成一次匹配的 `Authorization Claim`；
- `Authorization Scope` 必须绑定当前 `app_id`、Application Version、Requirement Hash、Command、Mode、Run ID、Account、Profile fingerprint、Site、Steps 和 Allowed Actions；Candidate Verification 还必须绑定允许验证的 Element 和 Instruction IDs；
- `profile_id` 是 resolved Profile directory 的本地 SHA-256 fingerprint，不是 Account ID，也不保存本机路径；Profile 配置变化后旧 scope 不能 claim；
- 每个 Authorization Record 只允许一个 invocation claim。`resume` 复用原 Run ID，但必须取得新的 Authorization Record，并绑定 canonical `resume_checkpoint_digest` 和首个待恢复 `resume_step_id`，不能重放首次 `run` 的 claim；
- Authorization Record、claim state 和 receipt 持久化为 application-local、Git-ignored JSON；使用 POSIX `flock` 对 claim 做跨进程原子保护，并以 Application directory 作为 trusted filesystem boundary，拒绝 path escape、symlink ancestor 和非目录组件；
- claim 在 Browser launch 前完成。Record 一旦被 claim，即使 Browser launch 或后续执行失败，也不能再次使用；
- Browser launch 前紧邻边界再次检查 session expiry；RESUME 还会复核 checkpoint digest 与 recovery Step。Runner 在取得 `.run.lock`、重新读取 checkpoint 后，并在 `Program.prepare()` 前再次核对该 digest、Step 和 execution identity，消除 pre-launch check 到 checkpoint use 之间的竞态；
- `AuthorizedBrowserActions` 在每次 Browser Boundary 前后校验 top-level Origin，并校验 active Session、Step、Action 和 Element。当前风险模型是固定流程的内部工具：业务 iframe 由冻结的 `ElementSpec.frame_locator` 约束，不再逐个执行 Origin allowlist；
- Preview 继续拦截 External Business Write。开发人员只能在审核 Write Preview 后单独 grant 一份 Live Authorization Record；该 Record 必须包含 exact write scopes。Live external adapter 在真正越过 write boundary 前，再逐项校验并原子消费对应 scope；字段至少包含 App、Run、Account、Step、Target、Data Scope、Expected Record Count 和 Payload Digest。写后必须按 exact Target 和 Data Scope 独立 Read-back，只有 Record Count 与 canonical Payload Digest 同时匹配才可标记 `SUCCEEDED`，无法建立精确结果时标记 `UNKNOWN`；
- Real Run Authorization 不能绕过 Requirement Consistency、Catalog Integrity、Candidate、Architecture、Sensitive Content、Checkpoint Identity、Review 或 Push Gates；
- 移除 application 内旧 authorization batch constants，不再把硬编码 batch ID 视为授权；
- Candidate Verification 只使用 fresh run；不保留无法在 `operation=verify_candidates` scope 中区分语义的 candidate `--resume`；
- Application 可以提供交互式 Preview convenience command，把 `request → grant → claim → run` 编排为一条命令；确认页只显示 Account、会发生的真实动作和 `external_writes`，并只在 TTY 接受一次明确确认。完整 exact scope 仍写入 Authorization Record，显式 request 命令仍可查看；快捷入口不得提供 `--yes`，取消时必须 revoke 未 claim 的 request。CI、Scheduler 和其他非交互调用继续使用显式 request/grant；
- 当前 `jushuitan.inventory.export_stock` 不包含 External Business Write，因此其 Live command 继续 fail closed。引入统一 Authorization Record 不构成开放 Live 的许可。

## Trust Boundary

JSON persistence 与 POSIX `flock` 用于本机 accident prevention、replay prevention 和 audit。它们防止普通并发调用、重复消费和误操作，但不声称抵御能够任意修改 application files、runtime state、process memory 或 system clock 的 malicious local actor。

Developer-local `authorization grant` 记录 `authorized_by`、`approval_reference` 和 exact `scope_digest`，但这些 caller-supplied fields 不是 cryptographic identity proof。只有开发人员亲自执行或在当前对话中明确授权 AI 执行，才构成项目流程认可的 Developer Authorization。

未来若 Authorization 由 Scheduler 或远程控制平面签发，需要另行设计 authenticated issuer、signature、key management 和 remote revocation；本 ADR 不把这些能力伪装成本机 JSON 已经提供。

## 结果

正面影响：

- 所有真实命令共享同一套 identity、scope、expiry 和 single-use 语义；
- 每次 Browser launch 都能关联一个持久化 claim receipt；
- 旧 batch constants 被可验证、不可重放的 invocation record 替代；
- Live write 继续保留独立且更窄的二次授权边界。

代价和限制：

- 每次 `resume` 都需要新的 Authorization Record；
- Profile 或 checkpoint 变化后需要重新 request/grant；
- Browser 启动失败也会消费本次 claim；
- 本机管理员或同权限恶意进程不在防御范围内；
- 当前边界信任冻结 locator 指向的业务 iframe，不抵御已获授权顶层页面主动替换 iframe 内容的攻击。若将来接入第三方或不可信页面，需要重新启用 per-frame policy 或使用 CDP navigation/request interception；
- 当前 adapter 只约束其 managed tab，新建但未被 Manager 接管的 tab 不属于可观察 scope，因此业务能力不得依赖未受控新 tab；
- `real_browser_launched` 能可靠标记 Chromium object 已返回后的初始化失败；若 trusted Chromium constructor 在返回 object 前已经启动进程又直接抛错，Python caller 无法从该异常本身证明进程是否短暂启动，需更底层的 process/port observability 才能消除该限制；
- 真实 invocation 仍需开发人员明确授权，offline tests 不能替代该授权。
- 交互式快捷入口减少手工复制字段，但不适合无人值守运行；自动化仍需外部审批流程提供显式 grant。

## 被否决方案

- 继续使用 batch constants：不能表达完整 Scope、Expiry 或 single-use claim；
- 只使用进程内 grant：进程退出后无法审计，也不能阻止跨进程 replay；
- 一个宽泛 grant 同时覆盖 Browser invocation 和所有 Live writes：会把启动权限扩大为业务写入权限；
- 允许 `run` 与 `resume` 重复消费同一 Record：不符合 one Record per invocation 的边界；
- 将本机 JSON + `flock` 描述为 hostile-host security：超出该机制实际提供的保证。
