# rpa-core

0.8.0 提供共享 CLI、浏览器与元素接口、顺序运行、运行记录和正常/反例测试。

程序由 ProgramSpec 和有序 Step 组成；每步声明 ID、名称、超时，并实现 execute、verify、counterexamples。
ExecutionContext 保存服务、业务输入、步骤结果、证据目录与可配置下载目录。可持久化业务参数放 inputs，凭据和服务配置留在 metadata / services。

正式 run 无交互确认，从头执行。agent 可用 resume <run_id> --from-step <step_id> 续跑：沿用原业务参数、账号、模式、下载目录和指定步骤之前的成功结果。每步更新 result.json，events.jsonl 记录过程。
BrowserManager 管理账号 Profile、端口与生命周期，失败保留浏览器供后续接管，成功关闭。下载默认使用 Windows 系统下载文件夹（非 Windows 为 ~/Downloads），所有命令保留已有文件，同名下载改名；配置、下载目录或浏览器准备失败也返回 run_id 并保存失败记录。

ApplicationDefinition.load_runtime_options 接收 RunRequest：account_id、inputs、credentials、download_dir；应用验证输入并转换为 RuntimeOptions。CLI 使用 --inputs / --credentials 传入 JSON 对象或 @JSON文件，--download-dir 覆盖路径。凭据不写入 inputs 或运行记录。

resume 的 --step-result 对应 Runner.run(step_result=...)：接收原失败步骤的输出，只运行该步 verify，成功后执行后续步骤。--locator-overrides 对应 locator_overrides，只为本次续跑覆盖定位器字段，不改业务成功条件、不修改 elements.toml，也不自动继承到下次续跑。

ApplicationDefinition.build_test_context 同时构造正常与失败场景。
先验证正常场景，再验证明确失败场景，每步至少有一个由 verify 拒绝的结果。

飞书、数据库、Excel 服务通过 ApplicationDefinition.build_services 注入，未配置时报错。
真实适配跟实际业务需求开发，不内置假后端或事务恢复机制。

本包离线测试：

    uv sync --locked
    uv run --locked pytest

完整约定见 [核心设计](../../docs/rpa-framework-design.md)。
