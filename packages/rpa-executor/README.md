# Windows 执行端

安装 Google Chrome、uv，在 Windows 桌面用户会话内运行；保持完整 monorepo 的 apps/packages 目录结构。

```powershell
# 未安装 uv 时，安装后重新打开 PowerShell。
winget install --id astral-sh.uv -e

# 在 monorepo 根目录启动。
.\packages\rpa-executor\start.ps1
```

若 PowerShell 提示禁止运行脚本，使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packages\rpa-executor\start.ps1`。该参数仅作用于这次进程，见 [PowerShell 执行策略](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies)。

脚本同步执行端与两个应用的独立 Python 3.12 环境，首次只询问控制台 HTTPS 地址和机器人连接凭据。控制台先创建机器人取得连接凭据；业务账号、密码、预期登录身份和账号别名均在控制台发起运行时填写。

路径与 WSS 地址自动填写到忽略的 `config.local.toml`。相对路径以配置文件目录为基准。ngrok 使用公开签发证书，不需要 CA 文件；私有 CA 仍可在 TOML 中配置 `ca_file`。

机器人连接凭据通过 Windows DPAPI 加密保存在忽略的 `credentials.local.clixml`，只供同一电脑的同一 Windows 用户解密。脚本会从旧版凭据文件移除业务账号字段，只保留连接凭据。业务凭据由控制台加密保存，通过 WSS 随本次运行下发，只在工作进程内使用；不写入本地配置或 SQLite 日志，Agent 不接触明文。

```powershell
# 更新测试域名并启动，保留机器人连接凭据。
.\packages\rpa-executor\start.ps1 -ServerUrl https://新的测试域名

# 重新输入地址与机器人连接凭据。
.\packages\rpa-executor\start.ps1 -Configure

# 离线测试。
uv run --project packages/rpa-executor pytest packages/rpa-executor/tests
```

业务账号、密码、预期身份、账号别名、日期、品牌、文件名和下载目录在控制台创建 Run 时填写。升级时先结束活跃 Run，服务端与执行端同步更新后再启动。活跃 Run 先在控制台请求停止并等到结束确认，再关闭执行端窗口；强行退出可能保留“状态待确认”。不要删除 `executor.sqlite` 或浏览器现场来强行解除占用。

Mac 测试与 Linux 服务端配置见 [测试部署说明](../../../kk-rpa-dashboard/docs/test-deployment.md)。
