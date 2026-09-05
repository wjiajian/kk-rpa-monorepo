# 聚水潭 S003 接管示例

适用于源失败步骤为 S003，S000–S002 已成功的运行。先读取[步骤契约](../requirement.md#s003-选择目标品牌)，在已有真实运行授权的范围内使用应用环境执行以下 Python。`run_id` 取实际失败记录；`credentials` 为本次凭据字典，使用本地配置时设为 None。

```python
import json
from uuid import uuid4

from rpa_core.cli import open_recovery_session
from rpa_core.elements import override_element_locators
from inventory_jushuitan_export_stock.program import APPLICATION
from inventory_jushuitan_export_stock.steps import (
    BRAND_SELECTED, BRAND_SELECTOR, RESET_BUTTON,
)

with open_recovery_session(APPLICATION, run_id, credentials=credentials) as recovery:
    ctx = recovery.context
    if recovery.source_record.get("failed_step") != "S003":
        raise ValueError("此示例只处理 S003 失败")
    print(ctx.account_id, ctx.inputs, recovery.browser_adopted)
    evidence_name = "recovery-s003-" + uuid4().hex[:8]
    ctx.browser.screenshot(name=evidence_name + "-before.png")

    # 在交互式会话中检查当前账号、商品库存页和实际 DOM 后，再继续。
    # 没有接回保留的浏览器时，先恢复页面；此入口不会自动登录或导航。
    # guide 是根据实际 DOM 构造的临时 ElementSpec；无引导时保持 None。
    guide = None
    if guide is not None:
        ctx.browser.click(guide)

    # 如原品牌回读定位器失效，在此填写已确认的已有元素定位字段。
    # 不填写猜测值，不修改 expect_count、check_at 或其他业务条件。
    overrides = {}
    ctx.services["elements"] = override_element_locators(ctx.service("elements"), overrides)
    elements = ctx.service("elements")
    brand = ctx.inputs["brand_value"]
    ctx.browser.click(elements[RESET_BUTTON])
    ctx.browser.select(elements[BRAND_SELECTOR], brand)
    supplied = {
        "requested_brand": brand,
        "selected_brands": list(ctx.browser.texts(elements[BRAND_SELECTED])),
    }
    ctx.browser.screenshot(name=evidence_name + "-after.png")
    result_path = ctx.run_dir / (evidence_name + "-result.local.json")
    result_path.write_text(json.dumps(supplied, ensure_ascii=False), encoding="utf-8")
    if overrides:
        locator_path = ctx.run_dir / (evidence_name + "-locators.local.json")
        locator_path.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")

# 必须退出 with，释放 Profile 占用后再调用 resume。
print(result_path)
```

使用实际结果文件路径执行现有命令：

```bash
uv run --locked rpa-app resume <run_id> --from-step S003 --step-result "@<result_path>"
```

如果生成了定位器文件，加 `--locator-overrides "@<locator_path>"`；未使用本地凭据时加 `--credentials "@credentials.local.json"`。修改接管 ctx 的元素映射不会自动传给 resume，必须显式提交定位器文件。

框架独立运行原 S003.verify，通过后才执行 S004、S005。新记录中 S003 成功事件来源为 agent，后续为 program。若再次失败，使用新 run_id 处理；定位器覆盖每次都需重新提供。临时辅助目标和原 result.json 均不会被入口写入或改成成功。接管事件在源运行的 recovery-events.jsonl，截图和本地结果也留在忽略的 runs 目录。

若执行工具会在命令结束时回收子浏览器，使用持续终端完成接管和续跑。
