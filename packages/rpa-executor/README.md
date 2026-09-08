# Windows 执行端

安装 Google Chrome、uv，在 Windows 桌面用户会话内运行；保持完整 monorepo 的 apps/packages 目录结构。

```powershell
# 未安装 uv 时，安装后重新打开 PowerShell。
winget install --id astral-sh.uv -e

# 在 monorepo 根目录启动。
.\packages\rpa-executor\start.ps1
```

若 PowerShell 提示禁止运行脚本，使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packages\rpa-executor\start.ps1`。该参数仅作用于这次进程，见 [PowerShell 执行策略](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies)。

脚本同步执行端与两个应用的独立 Python 3.12 环境，首次只询问控制台 HTTPS 地址和机器人连接凭据。控制台先创建机器人取得连接凭据；业务账号和密码在控制台发起运行时填写。执行端按控制台 Run ID 隔离浏览器 Profile，同次接管与续跑沿用该 Profile，无需填写账号别名。

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

业务账号和密码、日期、品牌、文件名和下载目录在控制台创建 Run 时填写。升级时先结束活跃 Run，服务端与执行端同步更新后再启动。活跃 Run 先在控制台请求停止并等到结束确认，再关闭执行端窗口；强行退出可能保留“状态待确认”。不要删除 `executor.sqlite` 或浏览器现场来强行解除占用。

每个正常步骤校验通过后和失败收尾前，执行端采集脱敏截图并立即作为独立证据事件回传。接管观察的截图随操作结果回传，即使 DOM 读取失败也保留截图。截图不可用时回传具体原因；同次 Run 最多分配 3 轮 Agent 接管，累计接管时限仍为 900 秒。

Mac 测试与 Linux 服务端配置见 [测试部署说明](../../../kk-rpa-dashboard/docs/test-deployment.md)。

## 桌面用户登录后自启

先用 `start.ps1` 完成首次配置和机器人连接验证，再在同一个 Windows 用户下安装自启。自启注册不会立即启动另一份执行端。

```powershell
.\packages\rpa-executor\autostart.ps1 -Action Install
.\packages\rpa-executor\autostart.ps1 -Action Status
# 取消下一次登录自启；不会终止当前进程。
.\packages\rpa-executor\autostart.ps1 -Action Remove
```

任务计划程序采用当前用户的登录触发器和 Interactive 身份，以普通权限进入桌面会话；不保存 Windows 密码、不自动登录、不使用系统服务。依据 [ScheduledTasks 身份配置](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)。电脑重启后需要该用户登录，浏览器执行环境才恢复。

自启入口 `startup-runner.ps1` 读取已有配置、DPAPI 连接凭据和已安装环境，不询问输入或同步依赖。更新代码后先在维护窗口手动运行 `start.ps1` 同步环境，再恢复自启。移动仓库后需重新执行 Install 更新路径。

日志保存在忽略目录 `packages/rpa-executor/runtime/startup/executor-YYYY-MM-DD.log`，记录启动错误和执行端重连诊断。连续启动失败最多间隔一分钟重试 3 次；缺配置、凭据无法解密或存在另一执行端时，应先处理日志提示。执行端仍用原文件锁保证单实例，不能通过复制配置或删除锁、journal 绕过占用。

Windows 验收需检查：注销后登录自动连接、任务使用当前交互用户、连续断网重连、重复启动只保留一个执行端、更新环境后恢复，以及未登录时不运行浏览器。仅 PowerShell 语法检查不代表这些场景通过。

## 发布安装中断后的收尾

平台安装在独立发布目录执行 `uv sync --locked`、`rpa-app doctor --deployment` 和 `rpa-app test`。部署 doctor 校验程序定义、元素声明、Python/依赖及浏览器可用性，不读取业务账号配置、不启动浏览器；普通 `doctor` 仍检查业务配置。业务输入和凭据由运行请求提供，并继续通过程序原校验。

控制台部署作业显示 `uncertain` 时，机器人继续保持占用。先关闭执行端，并在 Windows 任务管理器中核对该作业的 uv、Python 及安装子进程已停止；无法确认时重启执行机后登录桌面，再处理。不要先重新启动执行端。

在仓库根目录执行以下命令，将 `JOB_ID` 替换为控制台显示的部署作业 ID。确认参数表示操作者已经完成进程检查，命令本身不代替这项检查。

```powershell
uv run --project packages/rpa-executor rpa-executor --config packages/rpa-executor/config.local.toml --resolve-deployment JOB_ID --confirm-processes-stopped
.\packages\rpa-executor\start.ps1
```

本地收尾与正常执行端使用同一把锁，只处理本机日志中的不确定部署，存在未结束业务 Run 时拒绝操作。未完成安装的目录移动到 `runtime/releases/interrupted/JOB_ID` 保留排查，原作业记为失败；未完成卸载在隔离残留目录后移除对应注册项，记为已卸载。其他版本不变，不删除业务文件或运行日志。

第二条命令重连后补传收尾报告，后端确认后才释放机器人。安装失败可从控制台重新提交安装，形成新的作业。若本地收尾报错，保留原目录和日志继续排查；不要直接修改 SQLite 或服务端部署状态。
