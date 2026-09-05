from __future__ import annotations

from rpa_core.cli import ApplicationDefinition
from rpa_core.discovery import scan_application_architecture, scan_sensitive_content
from rpa_core.requirements import (
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
)
from rpa_core.verification import Counterexample, FakeState, assert_steps_are_falsifiable

from inventory_jushuitan_export_stock.cli import main
from inventory_jushuitan_export_stock.program import (
    APPLICATION,
    PROGRAM_VERSION,
    REQUIREMENT_HASH,
    build_counterexample_context,
    build_program,
)
from inventory_jushuitan_export_stock.steps import BRAND_SELECTED, RESULT_ROW
from inventory_jushuitan_export_stock.validators import APP_DIR, application_report


def test_compact_manifest_requirement_and_program_are_aligned() -> None:
    manifest = load_app_manifest(APP_DIR / "app.toml")
    requirement = load_requirement_memory(APP_DIR / "requirement.md")

    assert manifest.schema_version == 1
    assert manifest.version == PROGRAM_VERSION == "0.4.0"
    assert manifest.requirement_revision == requirement.source.revision == 107
    assert compute_requirement_hash(requirement) == REQUIREMENT_HASH
    assert manifest.requirement_hash == requirement.source.requirement_hash
    assert manifest.requirement_hash == build_program().spec.requirement_hash
    assert manifest.commands.preview == "rpa-app run"
    assert manifest.commands.live == "rpa-app run --live"
    assert manifest.commands.verify_elements == "rpa-app verify-elements"
    assert manifest.commands.check is None
    assert manifest.commands.login is None
    assert manifest.commands.verify_candidates is None

    program_steps = {step.spec.step_id: step.spec for step in build_program().steps}
    requirement_steps = {step.id: step for step in requirement.steps}
    for step_id in ("S001", "S002", "S003", "S004", "S005"):
        assert (
            tuple(requirement_steps[step_id].outputs)
            == program_steps[step_id].declared_outputs
        )
        assert (
            tuple(requirement_steps[step_id].success_conditions)
            == program_steps[step_id].success_conditions
        )


def test_repository_gate_accepts_the_shared_cli_application() -> None:
    report = application_report()

    assert report.ok
    assert report.issues == []
    assert scan_application_architecture(APP_DIR) == []
    assert scan_sensitive_content(APP_DIR) == []


def test_entrypoint_delegates_to_one_shared_application_definition() -> None:
    assert isinstance(APPLICATION, ApplicationDefinition)
    assert APPLICATION.app_dir == APP_DIR
    assert APPLICATION.build_program is build_program
    assert APPLICATION.build_counterexample_context is build_counterexample_context


def test_application_supplies_framework_enforced_counterexample_context(
    tmp_path,
) -> None:
    program = build_program()

    assert_steps_are_falsifiable(
        program.steps,
        lambda step, case: build_counterexample_context(step, case, tmp_path),
    )


def test_counterexamples_use_isolated_run_directories(tmp_path) -> None:
    step = build_program().step("S003")
    cases = list(step.counterexamples())[:2]

    contexts = [
        build_counterexample_context(step, case, tmp_path)
        for case in cases
    ]

    assert contexts[0].run_dir != contexts[1].run_dir
    assert all(context.run_dir.parent == tmp_path for context in contexts)


def test_counterexample_hidden_elements_override_happy_path_defaults(tmp_path) -> None:
    program = build_program()
    brand_context = build_counterexample_context(
        program.step("S003"),
        Counterexample("已选品牌元素不存在", FakeState(hidden=(BRAND_SELECTED,))),
        tmp_path,
    )
    row_context = build_counterexample_context(
        program.step("S004"),
        Counterexample("结果行元素不存在", FakeState(hidden=(RESULT_ROW,))),
        tmp_path,
    )

    assert brand_context.browser.texts(
        brand_context.services["elements"][BRAND_SELECTED]
    ) == []
    assert row_context.browser.count(
        row_context.services["elements"][RESULT_ROW]
    ) == 0


def test_doctor_uses_shared_command_without_launching_browser(capsys) -> None:
    assert main(["doctor"]) == 0

    output = capsys.readouterr().out
    assert '"app_id": "jushuitan.inventory.export_stock"' in output
    assert '"real_browser_launched": false' in output
