# kk-rpa-monorepo

一份需求对应一个独立 Python RPA 应用，目前包含聚水潭库存导出和京麦商品明细导出。

设计见 [核心设计](docs/rpa-framework-design.md)，后续任务与验收标准见 [Agent 开发与接管实施文档](docs/rpa-agent-implementation.md)，生成规则见 [AGENTS.md](AGENTS.md)。

后续网页控制台的前后端 monorepo 架构、任务与运行模型，以及本仓库应用的直接导入方式，见 [控制台架构与应用导入方案](../kk-rpa-dashboard/docs/rpa-console-architecture.md)。该文档为待实施方案。

Agent 根据需求生成普通 Python 应用。应用内元素库维护正式流程使用的页面目标，少量 BrowserActions API 处理浏览器交互与稳定性问题，业务 Step 定义输入输出和成功条件。条件、循环和数据处理直接使用 Python；接管中临时发现的辅助目标可以当次使用并留证，成为正常流程依赖后再整理进应用元素库。

在对应应用目录执行：

    uv sync --locked
    uv run rpa-app doctor
    uv run rpa-app test
    uv run rpa-app run --account STORE_001

上线后按配置无人值守运行。run 从头开始；失败后 agent 可以排查修复，再用 resume 指定从某一步继续。

主流程参数可以逐次传入，JSON 可直接写在参数中，也可保存为文件：

    uv run rpa-app run --account STORE_001 --inputs "@inputs.local.json" --credentials "@credentials.local.json"

`inputs.local.json` 的字段由应用定义：聚水潭使用 `brand_value`、`export_filename`，京麦使用 `target_date`（YYYY-MM-DD，默认昨日）、`export_filename`。`credentials.local.json` 接收 `username`、`password`、`expected_identity`，不写入运行记录。参数齐全时不需要本地配置；已有本地配置仍提供默认值。
指定下载目录可增加 `--download-dir "D:/RPA/downloads"`。周/月/日等业务范围由对应应用声明，核心通过 inputs 原样传入；现有京麦应用提供单日报表。

    uv run rpa-app resume <run_id> --from-step <step_id>

agent 已临时完成失败步骤时，提交该步输出，由框架校验通过后继续下一步：

    uv run rpa-app resume <run_id> --from-step <failed_step> --step-result "@step-result.local.json" --locator-overrides "@locators.local.json"

临时定位器仅用于本次续跑，不改变业务成功条件或应用文件。没有本地凭据时，同样传入 `--credentials "@credentials.local.json"`。完整格式见 [核心设计](docs/rpa-framework-design.md)。

续跑沿用原业务参数、账号、运行模式和下载目录。agent 先确认当前页面、账号与恢复步骤需要的文件；若页面丢失，可选择更早的步骤重建页面。
本地配置使用忽略的 config/stores.local.toml 和 .env。
省略 download_directory 时默认使用 Windows 系统下载文件夹；非 Windows 开发环境使用 ~/Downloads。所有命令保留已有文件，同名下载改名，结果返回实际文件路径。已有配置中的 download_directory 或本次 --download-dir 可覆盖默认位置。
日志、截图和结果保存在应用 runs/<run_id>；续跑建立新记录并关联原失败记录。失败保留浏览器，成功关闭。

开发元素验证用 rpa-app verify-elements，离线测试用 rpa-app test。
agent 打开真实浏览器或写入业务系统仍需用户授权。

2026-09-05 已授权并完成两个应用在 macOS 上的真实导出，以及聚水潭 S003 接管结果校验、临时定位器续跑和同名下载保留验证。Windows 实机验证已授权，等待可连接的 Windows 环境。详细记录见各应用需求基线。

- [聚水潭应用](apps/inventory_jushuitan_export_stock/README.md)
- [京麦应用](apps/report_jingmai_export_product_detail/README.md)
- [核心包](packages/rpa-core/README.md)
