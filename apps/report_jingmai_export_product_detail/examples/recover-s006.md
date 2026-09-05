# 京麦 S006 下载接管示例

适用于 S001–S005 已成功，S006 下载失败且旧导出弹窗已关闭的运行。先读取[步骤契约](../requirement.md#s006-匹配并下载目标报表)。在已有真实运行授权的范围内，使用应用环境执行以下 Python；`run_id` 取实际失败记录，`credentials` 为本次凭据字典，使用本地配置时设为 None。

```python
from uuid import uuid4

from rpa_core.cli import open_recovery_session
from report_jingmai_export_product_detail.program import (
    APPLICATION, DOWNLOADS_PAGE, expected_report_filename,
)

with open_recovery_session(APPLICATION, run_id, credentials=credentials) as recovery:
    ctx = recovery.context
    if recovery.source_record.get("failed_step") != "S006":
        raise ValueError("此示例只处理 S006 失败")
    target = ctx.inputs["target_date"]
    print(ctx.account_id, target, expected_report_filename(target))
    print("browser_adopted:", recovery.browser_adopted)
    evidence_name = "recovery-s006-" + uuid4().hex[:8]
    ctx.browser.screenshot(name=evidence_name + "-before.png")

    # 在交互式会话中确认原账号与当前页面。
    # 若当前没有下载页，填写从实际页面确认的下载地址或通过已确认目标导航。
    # 没有接回原浏览器时也需先恢复会话；不要重建 S004 的导出任务。
    observed_download_url = None
    if observed_download_url is not None:
        ctx.browser.open(observed_download_url, wait="complete")
    marker = ctx.service("elements")[DOWNLOADS_PAGE]
    if ctx.browser.count(marker) != 1:
        raise RuntimeError("需要先恢复报表下载页")
    ctx.browser.screenshot(name=evidence_name + "-ready.png")

# 退出 with 后再从 S006 继续；不提交伪造的下载结果。
```

```bash
uv run --locked rpa-app resume <run_id> --from-step S006
```

未使用本地凭据时加 `--credentials "@credentials.local.json"`。S006 按源记录日期、导出文件名和下载目录重新执行刷新、搜索、首行精确匹配及下载校验。S001–S005 的输出保留，不要求旧弹窗重新出现，也不再次创建导出任务。

查看新记录的实际下载路径与文件大小；旧文件必须保留，重名下载会使用新路径。接管事件保存在源运行的 recovery-events.jsonl，源 result.json 不变。接管退出或 browser_adopted 为 true 都不代表业务成功，结果以 resume 的原 verify 为准。若执行工具会回收子浏览器，用持续终端完成接管和续跑。
