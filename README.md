# kk-rpa-monorepo

一份需求对应一个独立 Python RPA 应用，目前包含聚水潭库存导出和京麦商品明细导出。

设计见 [核心设计](docs/rpa-framework-design.md)，生成规则见 [AGENTS.md](AGENTS.md)。

在对应应用目录执行：

    uv sync --locked
    uv run rpa-app doctor
    uv run rpa-app test
    uv run rpa-app run --account STORE_001

上线后按配置无人值守运行。run 从头开始；失败后 agent 可以排查修复，再用 resume 指定从某一步继续。

    uv run rpa-app resume <run_id> --from-step <step_id>

续跑沿用原业务参数、账号、运行模式和下载目录。agent 先确认当前页面、账号与恢复步骤需要的文件；若页面丢失，可选择更早的步骤重建页面。
本地配置使用忽略的 config/stores.local.toml 和 .env。
download_directory 默认 ../../runs/downloads，两个应用共用，新 run 和 verify-elements 前清空，resume 保留已有文件。
日志、截图和结果保存在应用 runs/<run_id>；续跑建立新记录并关联原失败记录。失败保留浏览器，成功关闭。

开发元素验证用 rpa-app verify-elements，离线测试用 rpa-app test。
agent 打开真实浏览器或写入业务系统仍需用户授权。

- [聚水潭应用](apps/inventory_jushuitan_export_stock/README.md)
- [京麦应用](apps/report_jingmai_export_product_detail/README.md)
- [核心包](packages/rpa-core/README.md)
