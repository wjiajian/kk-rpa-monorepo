# 京麦商品明细报表导出

该应用按需求基线导出京麦商智“经营状况-商品明细”昨日数据，并把文件保存到本次运行的 `runs/<run_id>/downloads/`。

应用现有 26 个页面定位器。已登录链路的 23 个定位器和 S001–S006 交互均已通过授权真实页面验证；另 3 个登录定位器已在 `https://passport.shop.jd.com/login/index.action` 的真实 DOM 中验证。京麦列表中的源文件名以 `.xlsx` 结尾，实际下载为包含一个非空工作簿的 `.xlsx.zip`。详细证据记录在 [requirement.md](requirement.md)。

标准验收已通过：`verify-elements-20260904T063602Z-16f4661a` 为 23/23，`run-20260904T063651Z-2801054d` 完成 S001–S006 并复算下载产物。

全新隔离 Profile 验收也已通过：`run-20260904T082724Z-117a6c99` 从稳定登录入口读取 `.env` 完成密码登录，回读认证状态和目标身份后继续完成 S002–S006；下载包、内部工作簿和 SHA-256 均已核验。

`PC-READONLY-ACCOUNT` 已于 2026-09-04 关闭：开发人员确认 `STORE_001` 是只读或仅允许报表导出的专用子账号，页面身份和权限开关保存在 Git 忽略的 `config/stores.local.toml`。

首次运行或需要验证完整登录时，在应用根目录创建 Git 忽略的 `.env`：

```dotenv
username=<京麦账号>
password=<京麦密码>
```

S001 会先检查现有会话；未登录时自动打开上述京麦专用登录入口并提交凭据。遇到验证码、滑块或短信验证时，程序会截图并等待人工完成，恢复后继续 S001–S006。

```bash
uv sync --group dev
uv run rpa-app doctor
uv run rpa-app test
```

可执行：

```bash
uv run rpa-app verify-elements --account STORE_001 --yes
uv run rpa-app run --account STORE_001 --yes
```

`verify-elements` 会按 S001–S006 到达各页面并逐项报告定位器。已有登录态时会跳过登录页的 3 项并检查其余 23 项；全新 Profile 会检查全部 26 项。为验证导出弹窗和下载列表，它会创建一次报表导出任务并下载结果。

账号、Cookie、Token、真实身份、Profile、运行截图和下载数据只保存在 Git 忽略路径。
