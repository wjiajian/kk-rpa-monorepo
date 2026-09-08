# 京麦商品明细报表导出

应用 `jingmai.reports.export_product_detail`，版本 0.2.0，使用共享 rpa-core 0.8.0。

程序确认目标账号，打开商智商品明细报表，按上海时区选择本次启动日的昨日数据，创建导出任务，再按完整文件名下载已生成的报表。成功要求账号、日期、报表正确，文件下载完成且非空；不核对表格内部业务数据。

在应用目录内安装和检查：

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app test
```

将 `config/stores.example.toml` 复制为忽略的 `config/stores.local.toml`，填写已确认的导出账号配置。在应用根目录的忽略文件 `.env` 中填写：

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

[S006 接管示例](examples/recover-s006.md)使用 `rpa_core.cli.open_recovery_session` 获得原日期、成功输出和浏览器上下文，准备下载页后释放占用，再使用现有 resume。每步输入输出和恢复要求见[需求基线](requirement.md#步骤输入输出与接管)。

`download_directory` 可指定应用目录之外的相对或绝对路径；省略时默认 Windows 系统下载文件夹，非 Windows 开发环境为 ~/Downloads。run、verify-elements 和 resume 均保留已有文件，下载重名时改名并返回实际路径。日志、结果和截图仍在应用 `runs/<run_id>/`。

`verify-elements` 会走到导出弹窗和下载列表，创建一次报表任务并下载；已有登录态时跳过登录页。`--preview` 不取消本应用的报表导出操作。

2026-09-05 新接管入口通过 21 项应用离线测试及 macOS 真实验收：在 S006 下载前建立可控失败记录，接管并准备下载页后只执行 S006，沿用原日期，保留前序输出和旧文件。Windows 实机验收已授权，等待可连接环境。运行记录见[需求基线](requirement.md)。

## 每次调用的流程参数

在忽略的本地文件中准备以下 JSON，也可以通过命令参数直接传 JSON 对象。

`inputs.local.json`：

```json
{"target_date":"2026-09-01","export_filename":"product-detail.xlsx"}
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
