# 京麦商品明细报表导出

应用 `jingmai.reports.export_product_detail`，版本 0.2.0，使用共享 rpa-core 0.8.0。

程序确认目标账号，打开商智商品明细报表，按上海时区选择本次启动日的昨日数据，创建导出任务，再按完整文件名下载已生成的报表。成功要求账号、日期、报表正确，文件下载完成且非空；不核对表格内部业务数据。

在应用目录内安装和检查：

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app test
```

将 `config/stores.example.toml` 复制为忽略的 `config/stores.local.toml`，填写期望账号身份和已确认的导出账号配置。在应用根目录的忽略文件 `.env` 中填写：

```dotenv
username=<京麦账号>
password=<京麦密码>
```

已有会话会复用；未登录时从京麦专用入口完成密码登录。若仍无法建立会话，留截图并结束本次运行。

```bash
uv run rpa-app run --account STORE_001
uv run rpa-app verify-elements --account STORE_001
```

正式运行无需交互确认。run 从 S001 开始并计算昨日日期，允许必要时重复创建同条件报表。失败保留浏览器，agent 修复并准备页面后可续跑，成功关闭。

```bash
uv run rpa-app resume <run_id> --from-step S006
```

示例适用于已进入下载列表、仅需继续下载。resume 沿用原目标日期，跨天也不改变；旧导出弹窗关闭不影响从 S006 继续。页面丢失时 agent 可选择更早的步骤。

`download_directory` 相对应用目录解析，也支持绝对路径；默认 `../../runs/downloads`，与聚水潭共用。新 run 和 verify-elements 前清空该目录，resume 保留已有文件。日志、结果和截图留在应用的 `runs/<run_id>/`。

`verify-elements` 会走到导出弹窗和下载列表，创建一次报表任务并下载；已有登录态时跳过登录页。`--preview` 不取消本应用的报表导出操作。

本次框架迁移的真实浏览器验证：**等待授权**。此前的页面验证范围见 [需求基线](requirement.md)，不代表新版本已完成真实验收。
