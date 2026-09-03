# 聚水潭库存导出 RPA

这是从飞书需求 revision 107 生成并按实际运行反馈修正的独立应用。应用读取本地账号配置，复用持久化浏览器 Profile，在同一次标准运行中确保登录并验证目标账号，然后进入商品库存，按本地品牌值精确筛选并导出库存文件，最终返回下载路径、SHA-256 和字节数。

当前版本是 `0.2.0`，状态为 `ready_for_push`。顶层公共库现有 17 个真实验证元素和 7 条真实验证指令；本应用快照完整使用这 24 项资产。新增账号身份元素及“确保目标账号会话”指令已完成真实验证和公共库回灌，普通 `check` 已解除候选门禁。开发人员已接受既有 Preview 证据并审核通过，审核记录为 `reviews/20260903T095809+0800.toml`。

## 本地配置

```bash
cp config/stores.example.toml config/stores.local.toml
cp .env.example .env
```

只在忽略的本地文件中填写真实值：

- `.env`：账号、密码，以及可选的页面可见账号身份文本；
- `config/stores.local.toml`：品牌、Profile、调试端口和可选 `identity_env`；未配置 `identity_env` 时使用登录账号作为期望身份文本；
- 每个账号必须使用独立 Profile、端口、运行目录和锁。

不要把原飞书文档中的凭据复制到源码、测试、报告或 Git。

## 环境与命令

```bash
uv sync --locked
uv run rpa-app doctor
uv run rpa-app check
uv run rpa-app test
uv run rpa-app login --account STORE_001 --batch-id <authorization-batch-id>
uv run rpa-app verify-candidates --account STORE_001 --batch-id <authorization-batch-id>
uv run rpa-app verify-candidates --account STORE_001 --batch-id <authorization-batch-id> --resume-run-id <run_id>
uv run rpa-app run --mode preview --account STORE_001
uv run rpa-app resume --run-id <run_id> --mode preview --account STORE_001
```

当前阶段：

- `doctor`：只读检查，不启动浏览器；
- `test`：运行无外部副作用测试；
- `check`：校验 Memory/Spec、需求哈希、资产快照、架构边界和敏感信息；当前应通过且无开放候选门禁；
- `login`、`verify-candidates`：必须携带单独的真实浏览器授权；
- `verify-candidates`：只用于另行授权的新候选验证；本轮批次 `account-session-verify-20260903` 已消费并撤销，不能复用；
- `run`、`resume`：候选门禁已解除；执行真实浏览器流程仍须遵守开发人员的单次授权范围；
- 0.2.0 Preview 已验证有效会话复用、目标账号核对、目标品牌筛选、搜索及一次下载，未执行外部业务写入；会话失效时的自动登录编排由既有真实验证登录指令和本轮 Fake 测试覆盖，本次未主动清除有效会话。

## 业务流程

```text
Prepare 打开登录入口并检查会话
→ 会话失效时在同一次运行中使用目标账号凭据登录
→ 比对页面身份文本与本地期望账号
→ S001 打开库存模块
→ S002 进入商品库存
→ S003 精确归一化为仅选中本地配置品牌
→ 安全点击筛选区空白输入框并验证品牌下拉层已收起
→ S004 点击搜索并验证筛选
→ S005 导出并验证下载文件
```

如果登录失败、需要人机验证、页面账号身份不匹配、品牌下拉层未收起、选中集合不是唯一目标、搜索按钮不可点击、结果表标识缺失或下载未完成，流程会截图并失败关闭，不会继续导出。未观察到的人机验证场景不沉淀虚构定位器。应用不写 NAS、飞书多维表格、数据库或正式 Excel；真实 Preview 只验证读取、筛选和下载，不表示外部业务写入或业务验收通过。
