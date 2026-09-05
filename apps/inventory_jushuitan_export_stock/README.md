# 聚水潭库存导出 RPA

应用使用指定账号的独立持久化 Profile，确认登录身份后进入商品库存，按本地品牌配置筛选并把库存文件下载到本次运行目录。

当前版本为 `0.4.0`。应用入口委托给共享 `rpa_core.cli`，业务代码只保留 Program、Step、配置装配和逐阶段元素验证。V1 catalog 与 Instruction 快照已经移除。

## 业务断言

| Step | 回读依据 |
| --- | --- |
| Prepare | 已登录标识存在，页面身份包含本地配置的期望身份 |
| S001 | 库存模块标识带当前激活状态 |
| S002 | 商品库存页签处于活动状态 |
| S003 | 已选品牌集合恰好等于配置品牌 |
| S004 | 结果行数大于 0，搜索后品牌集合仍恰好等于配置品牌 |
| S005 | 下载文件位于本次运行的 `downloads/`，非空且哈希可复算 |

每个 Step 都声明至少一个假页面状态。`rpa-app test` 会先在生产 Fake 上执行这些反例，再运行应用 pytest；任何仍能通过的反例都会使命令失败。

## 本地配置

```bash
cp config/stores.example.toml config/stores.local.toml
cp .env.example .env
```

只在 Git 忽略的文件中填写真实账号、密码、期望页面身份、品牌、Profile 目录和调试端口。一个账号必须使用独立 Profile。

## 无浏览器检查

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app test
```

`doctor` 检查 Python、Chrome、配置、依赖锁、元素和阻塞项。`test` 只运行 Fake Browser 与离线测试。

## 真实运行

真实浏览器操作需要显式确认：

```bash
uv run rpa-app verify-elements --account STORE_001 --yes
uv run rpa-app run --account STORE_001 --yes
uv run rpa-app resume <run_id> --account STORE_001 --yes
```

默认 `run` 为 Preview，可以登录、读取、筛选并下载到本地运行目录。本应用没有 NAS、飞书、数据库或正式 Excel 写入。失败运行保留浏览器供排查和恢复，成功运行关闭浏览器。

`verify-elements` 按 `login_page`、`session`、S001–S004 导航并检查 `elements.toml` 的 `expect_count`。S005 会触发下载，因此元素验证不会执行它。

## 版本证据

0.3.0 及更早版本的真实运行和旧授权协议记录保留在 `GENERATION_REPORT.md` 与 `reviews/`。它们是历史证据，不代表共享 CLI 迁移后的真实验证结果。当前清单状态为 `ready_for_review`。
