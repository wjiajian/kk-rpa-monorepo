# 聚水潭库存导出 RPA

这是从飞书需求 revision 107 生成的独立应用。应用读取本地账号配置，复用持久化浏览器 Profile，进入商品库存，按本地品牌值精确筛选并导出库存文件，最终返回下载路径、SHA-256 和字节数。

当前状态是 `ready_for_review`。实际流程验证得到的 16 个元素和 7 条指令已进入顶层公共库，应用内保存同一依赖闭包的不可变快照，并由 `catalog.lock.json` 固定来源、版本和内容哈希。普通 `check`、`run` 和 `resume` 的候选门禁已经关闭；真实浏览器命令仍须由操作者在明确授权范围内执行。

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
uv run rpa-app verify-candidates --account STORE_001 --batch-id <authorization-batch-id>
uv run rpa-app verify-candidates --account STORE_001 --batch-id <authorization-batch-id> --resume-run-id <run_id>
uv run rpa-app run --mode preview --account STORE_001
uv run rpa-app resume --run-id <run_id> --mode preview --account STORE_001
```

当前阶段：

- `doctor`：只读检查，不启动浏览器；
- `test`：运行无外部副作用测试；
- `check`：校验 Memory/Spec、需求哈希、公共资产快照、架构边界和敏感信息，当前应返回成功；
- `login`、`verify-candidates`：必须携带单独的真实浏览器授权；
- `verify-candidates`：保留为 V2 标准命令，用于将来出现新候选资产时逐条验证；
- `run`、`resume`：当前已可调度；本次公共库整理没有再次启动真实浏览器。

## 业务流程

```text
Prepare 验证登录态
→ S001 打开库存模块
→ S002 进入商品库存
→ S003 精确归一化为仅选中本地配置品牌
→ 安全点击筛选区空白输入框并验证品牌下拉层已收起
→ S004 点击搜索并验证筛选
→ S005 导出并验证下载文件
```

如果品牌下拉层未收起、选中集合不是唯一目标、搜索按钮不可点击、结果表标识缺失或下载未完成，流程会失败关闭，不会继续导出。未观察到的人机验证场景不沉淀虚构定位器：登录未达到认证标识时，程序保存证据并转人工处理。应用不写 NAS、飞书多维表格、数据库或正式 Excel；真实 Preview 只验证读取、筛选和下载，不表示外部业务写入或业务验收通过。
