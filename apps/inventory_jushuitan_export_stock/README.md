# 聚水潭库存导出

应用 `jushuitan.inventory.export_stock`，版本 0.5.0，使用共享 rpa-core 0.8.0。

程序确认目标账号，进入商品库存，重置并选择配置品牌，搜索后导出库存。成功要求账号和品牌正确、下载完成且文件非空；不检查表格内部业务数据。

在应用目录内安装和检查：

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app test
```

将 `config/stores.example.toml` 复制为忽略的 `config/stores.local.toml`，替换账号配置和品牌。在应用根目录的忽略文件 `.env` 中设置配置所引用的用户名和密码环境变量。现有本地配置可以继续使用。

```bash
uv run rpa-app run --account STORE_001
uv run rpa-app verify-elements --account STORE_001
```

正式运行无需交互确认。run 从 S000 开始；失败保留浏览器，agent 修复并准备好页面后可续跑，成功关闭。

```bash
uv run rpa-app resume <run_id> --from-step S005
```

示例适用于页面已准备好、仅需继续库存导出。续跑沿用原品牌和文件名，也可以选择更早的步骤重建页面。

[S003 接管示例](examples/recover-s003.md)使用 `rpa_core.cli.open_recovery_session` 读取原输入与成功输出、连接保留的浏览器，并在临时处理引导或定位器后提交品牌回读。每步输入输出和恢复要求见[需求基线](requirement.md#步骤输入输出与接管)。

`download_directory` 可指定应用目录之外的相对或绝对路径；省略时默认 Windows 系统下载文件夹，非 Windows 开发环境为 ~/Downloads。run、verify-elements 和 resume 均保留已有文件，下载重名时改名并返回实际路径。日志、结果和截图仍在应用 `runs/<run_id>/`。

`verify-elements` 按页面阶段检查匹配数，已有登录态时跳过登录页，不触发库存下载。`--preview` 是运行模式参数，本应用只导出文件，仍会操作页面并下载。

2026-09-05 新接管入口通过 23 项应用离线测试及 macOS 真实验收：临时关闭引导、提交 S003 原品牌输出、异常退出后再连接并完成 S004/S005 下载，源记录与旧文件保留。Windows 实机验收已授权，等待可连接环境。运行记录见[需求基线](requirement.md)。

## 每次调用的流程参数

在忽略的本地文件中准备以下 JSON，也可以通过命令参数直接传 JSON 对象。

`inputs.local.json`：

```json
{"brand_value":"BRAND_TARGET","export_filename":"inventory-export.xlsx"}
```

`credentials.local.json`：

```json
{"username":"<login username>","password":"<login password>"}
```

```bash
uv run rpa-app run --account STORE_001 --inputs "@inputs.local.json" --credentials "@credentials.local.json"
```

显式参数优先于本地默认；参数齐全时无需 stores.local.toml 或 .env。可加 `--download-dir "D:/RPA/downloads"` 指定保存目录，export_filename 只填写 ASCII 文件名，目录可含中文。凭据不保存在运行记录中；无本地凭据时，resume 需再次传 --credentials。

agent 临时完成失败步骤后，用 `--step-result "@step-result.local.json"` 提交该步 execute 应返回的输出；框架独立执行 verify，通过后再继续。校验也用到失效元素时，可用 `--locator-overrides "@locators.local.json"` 仅替换本次定位器。完整格式见 [核心设计](../../docs/rpa-framework-design.md)。

当前测试流程仅确认登录会话已建立，不匹配页面上的预期账号名称。验证码、短信验证或未建立会话仍会失败并留证。
