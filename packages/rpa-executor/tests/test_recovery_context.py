from rpa_executor.worker import recovery_context


REQUIREMENT = """# 应用需求
固定原日期，不改变业务范围。
## 步骤契约
### S001 登录
完整的登录要求。
### S002 下载
输出：download_path。
成功条件：原目录内非空文件，原日期和报表名称精确匹配。
接管输出：完整结果交由原 verify 检查。
## 验收历史
这段只在全文中读取。
"""


def test_step_context_preserves_complete_contract_original_inputs_and_outputs():
    source = {"failed_step": "S002", "inputs": {"date": "2026-09-06"}, "outputs": {"S001": {"identity_verified": True}},
              "error": {"code": "failed", "diagnostics": {"root_cause": {"type": "LookupError", "message": "missing"}, "traceback": ["long traceback"]}}}
    elements = {"login": {"check_at": "S001"}, "download": {"check_at": "S002"}, "dialog": {"check_at": "S002-dialog"}}
    context = recovery_context(source, REQUIREMENT, elements)
    assert context["source"]["inputs"] == source["inputs"]
    assert context["source"]["outputs"] == source["outputs"]
    assert "成功条件：原目录内非空文件，原日期和报表名称精确匹配。" in context["requirement"]
    assert "固定原日期" in context["requirement"]
    assert "完整的登录要求" not in context["requirement"]
    assert "验收历史" not in context["requirement"]
    assert context["elements"] == elements
    assert "traceback" not in str(context["source"])
    assert context["source"]["error"]["message"] == "missing"
    assert recovery_context(source, REQUIREMENT, elements, step="S001")["elements"] == elements
    full = recovery_context(source, REQUIREMENT, elements, full=True)
    assert full["requirement"] == REQUIREMENT
    assert full["elements"] == elements
    assert full["source"] == source


def test_unrecognized_requirement_format_keeps_full_baseline():
    assert recovery_context({"failed_step": "S1"}, "plain requirements", {})["requirement"] == "plain requirements"


def test_brand_recovery_retains_reset_and_selector_checked_before_failed_step():
    from pathlib import Path
    import tomllib
    app = Path(__file__).resolve().parents[3] / 'apps' / 'inventory_jushuitan_export_stock'
    elements = tomllib.loads((app / 'elements.toml').read_text())['elements']
    requirement = (app / 'requirement.md').read_text()
    context = recovery_context({'failed_step': 'S003'}, requirement, elements)
    reset = next(key for key, value in elements.items() if value['name'] == '重置筛选按钮')
    selector = next(key for key, value in elements.items() if value['name'] == '商品品牌选择器')
    assert elements[reset]['check_at'] == 'S002'
    assert context['elements'][reset] == elements[reset]
    assert context['elements'][selector] == elements[selector]
    assert context['step_id'] == 'S003' and context['scope'] == 'step'
