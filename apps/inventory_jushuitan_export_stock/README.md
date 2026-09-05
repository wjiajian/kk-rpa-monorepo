# 聚水潭库存导出

应用 `jushuitan.inventory.export_stock`，版本 0.5.0，使用共享 rpa-core 0.8.0。

程序确认目标账号，进入商品库存，重置并选择配置品牌，搜索后导出库存。成功要求账号和品牌正确、下载完成且文件非空；不检查表格内部业务数据。

在应用目录内安装和检查：

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app test
```

将 `config/stores.example.toml` 复制为忽略的 `config/stores.local.toml`，替换账号配置和品牌。在应用根目录的忽略文件 `.env` 中设置配置所引用的用户名、密码和预期身份环境变量。现有本地配置可以继续使用。

```bash
uv run rpa-app run --account STORE_001
uv run rpa-app verify-elements --account STORE_001
```

正式运行无需交互确认。run 从 S000 开始；失败保留浏览器，agent 修复并准备好页面后可续跑，成功关闭。

```bash
uv run rpa-app resume <run_id> --from-step S005
```

示例适用于页面已准备好、仅需继续库存导出。续跑沿用原品牌和文件名，也可以选择更早的步骤重建页面。

`download_directory` 相对应用目录解析，也支持绝对路径；默认 `../../runs/downloads`，与京麦共用。新 run 和 verify-elements 前清空该目录，resume 保留已有文件。日志、结果和截图留在应用的 `runs/<run_id>/`。

`verify-elements` 按页面阶段检查匹配数，已有登录态时跳过登录页，不触发库存下载。`--preview` 是运行模式参数，本应用只导出文件，仍会操作页面并下载。

本次框架迁移的真实浏览器验证：**等待授权**。此前的页面验证范围见 [需求基线](requirement.md)，不代表新版本已完成真实验收。
