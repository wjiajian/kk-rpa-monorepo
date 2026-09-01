# 聚水潭库存导出 RPA

这是从飞书需求 revision 107 生成的独立应用草稿。应用读取本地账号配置，复用持久化浏览器 Profile，进入商品库存，按本地品牌值筛选并导出库存文件，最终返回下载路径、SHA-256 和字节数。

当前状态是 `pending_confirmation`。应用包含 16 个候选元素和 7 条候选指令，Fake Browser 可以验证完整流程，但尚未获得真实登录后页面的候选验证证据。因此正常 `run` 和 `resume` 会在创建运行目录和启动浏览器之前拒绝执行。

## 本地配置

```bash
cp config/stores.example.toml config/stores.local.toml
cp .env.example .env
```

只在忽略的本地文件中填写真实值：

- `.env`：账号与密码；
- `config/stores.local.toml`：品牌、Profile 和调试端口；
- 每个账号必须使用独立 Profile、端口、运行目录和锁。

不要把原飞书文档中的凭据复制到源码、测试、报告或 Git。

## 环境与命令

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
uv run rpa-app login --account STORE_001
uv run rpa-app verify-candidates --account STORE_001
uv run rpa-app run --mode preview --account STORE_001
uv run rpa-app resume --run-id <run_id> --mode preview --account STORE_001
```

当前阶段：

- `doctor`：只读检查，不启动浏览器；
- `test`：运行无外部副作用测试；
- `check`：精确列出所有 `UE-*`、`UI-*`，并返回非零状态；
- `login`、`verify-candidates`：要求补丁 C 的单独真实浏览器授权；
- `run`、`resume`：候选项关闭前拒绝，且不会创建 `runs/`。

## 业务流程

```text
Prepare 验证登录态
→ S001 打开库存模块
→ S002 进入商品库存
→ S003 选择本地配置品牌
→ S004 搜索并验证筛选
→ S005 导出并验证下载文件
```

应用不写 NAS、飞书多维表格、数据库或正式 Excel。真实 Preview 只验证读取、筛选和下载，不表示外部业务写入或业务验收通过。
