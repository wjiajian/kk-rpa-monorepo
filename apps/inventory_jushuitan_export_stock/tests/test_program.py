import json
from pathlib import Path

import pytest
from inventory_jushuitan_export_stock.program import (
    APPLICATION,
    build_program,
    build_test_context,
)
from rpa_core.runtime import Runner, StepRunError
from rpa_core.verification import (
    Counterexample,
    CounterexampleContractError,
    FakeState,
    assert_steps_are_falsifiable,
)


def context(tmp_path, case=None):
    return build_test_context(build_program().steps[0], case, tmp_path)


def test_complete_flow_downloads_to_configured_directory(tmp_path):
    ctx = context(tmp_path)
    result = Runner().run(build_program(), ctx)
    assert result.completed_steps == ("S000", "S001", "S002", "S003", "S004", "S005")
    assert result.status == "succeeded"
    artifact = Path(result.outputs["S005"]["download_path"])
    assert artifact.parent == ctx.download_dir
    assert artifact.stat().st_size > 0
    report = json.loads((ctx.run_dir / "result.json").read_text())
    assert report["status"] == "succeeded"
    assert not (ctx.run_dir / "checkpoint.json").exists()


def test_normal_and_bad_scenarios_use_the_same_fixture(tmp_path):
    serial = [0]

    def factory(step, case):
        serial[0] += 1
        return build_test_context(step, case, tmp_path / str(serial[0]))

    assert_steps_are_falsifiable(build_program().steps, factory)


@pytest.mark.parametrize("index", range(6))
def test_every_verifier_cannot_be_replaced_with_constant_true(tmp_path, index):
    step = build_program().steps[index]
    step.verify = lambda ctx, result: True
    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [step], lambda step, case: build_test_context(step, case, tmp_path)
        )


def test_failed_download_can_be_restarted_from_the_beginning(tmp_path):
    failed = context(
        tmp_path / "first",
        Counterexample("download absent", FakeState(downloads_available=False)),
    )
    with pytest.raises(StepRunError) as caught:
        Runner().run(build_program(), failed)
    assert caught.value.step_id == "S005"
    fresh = context(tmp_path / "second")
    result = Runner().run(build_program(), fresh)
    assert result.completed_steps == ("S000", "S001", "S002", "S003", "S004", "S005")
    assert result.status == "succeeded"


def test_empty_or_missing_download_is_rejected_after_the_action(tmp_path):
    ctx = context(tmp_path)
    step = build_program().step("S005")
    result = step.execute(ctx)
    assert step.verify(ctx, result)
    target = Path(result["download_path"])
    target.write_bytes(b"")
    assert not step.verify(ctx, result)
    target.unlink()
    assert not step.verify(ctx, result)


def test_stage_validation_reaches_all_declared_stages(tmp_path):
    from rpa_core.elements import load_element_catalog

    ctx = context(tmp_path)
    result = APPLICATION.verify_element_stages(
        ctx, load_element_catalog(APPLICATION.app_dir / "elements.toml")
    )
    assert result["ok"], result
    assert result["unreached_stages"] == []


from inventory_jushuitan_export_stock.steps import (
    BRAND_SELECTED,
    BRAND_SELECTOR,
    EXPORT_MENU,
    EXPORT_OPTION,
    NAV_INVENTORY,
    PRODUCT_STOCK_ENTRY,
    RESET_BUTTON,
    SEARCH_BUTTON,
)


def test_inventory_actions_keep_the_verified_business_order(tmp_path):
    ctx = context(tmp_path)
    Runner().run(build_program(), ctx)
    actions = [
        (record.action, record.element_id)
        for record in ctx.browser.actions
        if record.action in {"click", "select", "download"}
    ]
    assert actions == [
        ("click", NAV_INVENTORY),
        ("click", PRODUCT_STOCK_ENTRY),
        ("click", RESET_BUTTON),
        ("select", BRAND_SELECTOR),
        ("select", BRAND_SELECTOR),
        ("click", SEARCH_BUTTON),
        ("select", BRAND_SELECTOR),
        ("select", BRAND_SELECTOR),
        ("click", EXPORT_MENU),
        ("download", EXPORT_OPTION),
    ]
    assert [record.action for record in ctx.browser.actions].count("open") == 1


def test_download_verification_rereads_the_selected_brand(tmp_path):
    ctx = context(tmp_path)
    step = build_program().step("S005")
    result = step.execute(ctx)
    ctx.browser._text_lists[BRAND_SELECTED] = ["OTHER_BRAND"]
    assert step.verify(ctx, result) is False


def test_store_config_supports_a_custom_download_directory(tmp_path):
    from inventory_jushuitan_export_stock.models import load_store_config

    sample = (APPLICATION.app_dir / "config" / "stores.example.toml").read_text()
    path = tmp_path / "stores.toml"
    path.write_text(sample + '\ndownload_directory = "custom-output"\n')
    assert load_store_config(path, "STORE_001").download_directory == "custom-output"


def test_agent_resumes_export_with_original_brand_after_local_config_changes(tmp_path):
    from dataclasses import replace

    failed = context(
        tmp_path / "first",
        Counterexample("no download", FakeState(downloads_available=False)),
    )
    with pytest.raises(StepRunError):
        Runner().run(build_program(), failed)
    previous = json.loads((failed.run_dir / "result.json").read_text())
    resumed = context(tmp_path / "resume")
    resumed.run_id = "resumed-run"
    resumed.inputs["brand_value"] = "OTHER_BRAND"
    resumed.metadata["store_config"] = replace(
        resumed.metadata["store_config"], brand_value="OTHER_BRAND"
    )
    resumed.browser.download_dir = Path(previous["download_dir"])
    result = Runner().run(build_program(), resumed, previous=previous, from_step="S005")
    assert result.status == "succeeded"
    assert result.outputs["S005"]["requested_brand"] == "BRAND_001"
    assert result.completed_steps == ("S000", "S001", "S002", "S003", "S004", "S005")
    assert not any(
        action.element_id
        in (NAV_INVENTORY, PRODUCT_STOCK_ENTRY, RESET_BUTTON, SEARCH_BUTTON)
        for action in resumed.browser.actions
    )
    assert Path(result.outputs["S005"]["download_path"]).parent == failed.download_dir


def test_main_parameters_work_without_local_config_and_reach_the_steps(tmp_path, monkeypatch):
    from inventory_jushuitan_export_stock import program
    from rpa_core.cli import RunRequest

    source_dir = program.APP_DIR
    monkeypatch.setattr(program, "APP_DIR", tmp_path / "application")
    destination = tmp_path / "downloads"
    request = RunRequest(
        inputs={"brand_value": "BRAND_TEST", "export_filename": "requested.xlsx"},
        credentials={"username": "test-user", "password": "test-secret"},
        download_dir=str(destination),
    )
    options = program.load_runtime_options(request)
    assert options.inputs == request.inputs and options.download_dir == destination
    credentials = options.metadata["login_credentials"]
    assert credentials.username.reveal() == "test-user"
    assert credentials.expected_identity is None
    assert not program.APP_DIR.exists()
    monkeypatch.setattr(program, "APP_DIR", source_dir)
    ctx = context(tmp_path / "fixture")
    ctx.inputs["export_filename"] = options.inputs["export_filename"]
    result = build_program().step("S005").execute(ctx)
    assert Path(result["download_path"]).name == "requested.xlsx"


@pytest.mark.parametrize("inputs", [{"period": "week"}, {"brand_value": []}, {"brand_value": "BRAND_TEST", "export_filename": "../escape.xlsx"}])
def test_unsupported_inventory_parameters_are_rejected_before_execution(tmp_path, monkeypatch, inputs):
    from inventory_jushuitan_export_stock import program
    from inventory_jushuitan_export_stock.models import ConfigurationError
    from rpa_core.cli import RunRequest

    monkeypatch.setattr(program, "APP_DIR", tmp_path)
    with pytest.raises(ConfigurationError):
        program.load_runtime_options(RunRequest(inputs=inputs))


def test_agent_search_result_cannot_change_the_original_brand(tmp_path):
    failed = context(tmp_path / "first", Counterexample("search button absent", FakeState(hidden=(SEARCH_BUTTON,))))
    with pytest.raises(StepRunError) as caught:
        Runner().run(build_program(), failed)
    assert caught.value.step_id == "S004"
    previous = json.loads((failed.run_dir / "result.json").read_text())
    resumed = context(tmp_path / "resume", Counterexample("wrong brand selected", FakeState(texts={BRAND_SELECTED: ("OTHER_BRAND",)})))
    resumed.run_id = "resumed-agent"
    supplied = {"requested_brand": "OTHER_BRAND", "row_count": 1, "brands_after_search": ["OTHER_BRAND"], "brands_normalized": ["OTHER_BRAND"]}
    with pytest.raises(StepRunError) as caught:
        Runner().run(build_program(), resumed, previous=previous, from_step="S004", step_result=supplied)
    assert caught.value.step_id == "S004"
    report = json.loads((resumed.run_dir / "result.json").read_text())
    assert "S004" not in report["completed_steps"]
    assert not any(action.action == "download" for action in resumed.browser.actions)


@pytest.mark.parametrize("supplied_outcome", ["correct", "wrong_brand", "verify_error"])
def test_public_recovery_handles_guide_and_temporary_verifier_then_continues(
    tmp_path, monkeypatch, capsys, supplied_outcome
):
    from dataclasses import replace
    from types import SimpleNamespace
    from inventory_jushuitan_export_stock import program
    from rpa_core import cli
    from rpa_core.browser import ElementActionError, ElementLookupError, ElementSpec, Locator
    from rpa_core.elements import override_element_locators

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    for name in ("app.toml", "requirement.md", "elements.toml"):
        (app_dir / name).write_bytes((APPLICATION.app_dir / name).read_bytes())
    failed = context(app_dir, Counterexample("reset absent", FakeState(hidden=(RESET_BUTTON,))))
    failed.inputs["brand_value"] = "BRAND_ORIGINAL"
    failed.download_dir = tmp_path / "original-downloads"
    failed.browser.download_dir = failed.download_dir
    with pytest.raises(StepRunError) as caught:
        Runner().run(build_program(), failed)
    assert caught.value.step_id == "S003"
    source = failed.run_dir / "result.json"
    source_bytes = source.read_bytes()
    previous = json.loads(source_bytes)
    (app_dir / "config").mkdir()
    (app_dir / "config" / "stores.local.toml").write_text(
        'schema_version = 1\n[stores.STORE_001]\nbrand_value = "CHANGED_DEFAULT"\n'
        'download_directory = "changed-downloads"\n'
    )
    monkeypatch.setattr(program, "APP_DIR", app_dir)
    definition = replace(APPLICATION, app_dir=app_dir)
    page = build_test_context(build_program().step("S003"), None, tmp_path / "page").browser
    page._text_lists[BRAND_SELECTED] = ["BRAND_ORIGINAL"]
    guide = ElementSpec("recovery.page.guide", "Fixture guide", "Fixture", locator=Locator("css:#fixture-guide"))
    page._visible |= {guide.id}
    state = {"guide_closed": False, "verify_error": False}
    replacement = "css:#fixture-selected-brand"

    class RecoveryPage:
        def __getattr__(self, name):
            return getattr(page, name)

        def click(self, target):
            page.click(target)
            if target.id == guide.id:
                state["guide_closed"] = True

        def select(self, target, value):
            if not state["guide_closed"]:
                raise ElementActionError("fixture guide obstructs selection")
            page.select(target, value)

        def texts(self, target, **kwargs):
            if target.id == BRAND_SELECTED:
                if state["verify_error"]:
                    raise RuntimeError("fixture verifier read failed")
                if target.locator.value != replacement:
                    raise ElementLookupError("fixture verifier locator is stale")
            return page.texts(target, **kwargs)

    sessions = []

    class Manager:
        def __init__(self, root):
            pass

        def start(self, spec, **kwargs):
            page.run_dir = kwargs["run_dir"]
            page.download_dir = kwargs["download_dir"]
            session = SimpleNamespace(active=True, actions=RecoveryPage(), adopted=True)
            sessions.append(session)
            return session

        def detach(self, session):
            session.active = False

        def finish(self, session, *, failed):
            session.active = False

        def shutdown(self):
            pass

    monkeypatch.setattr(cli, "BrowserManager", Manager)
    credentials = {"username": "fixture-user", "password": "fixture-secret"}
    credentials_arg = json.dumps(credentials)
    overrides = {BRAND_SELECTED: {"locator": replacement}}
    with cli.open_recovery_session(definition, failed.run_id, credentials=credentials) as recovery:
        ctx = recovery.context
        assert ctx.inputs == previous["inputs"] and ctx.outputs == previous["outputs"]
        assert ctx.metadata["store_config"].brand_value == "BRAND_ORIGINAL"
        assert ctx.browser.actions == []
        ctx.browser.screenshot(name="recovery-before.png")
        ctx.browser.click(guide)
        assert guide.id not in ctx.service("elements")
        ctx.services["elements"] = override_element_locators(ctx.service("elements"), overrides)
        elements = ctx.service("elements")
        ctx.browser.click(elements[RESET_BUTTON])
        ctx.browser.select(elements[BRAND_SELECTOR], ctx.inputs["brand_value"])
        supplied = {"requested_brand": ctx.inputs["brand_value"],
                    "selected_brands": list(ctx.browser.texts(elements[BRAND_SELECTED]))}
        ctx.browser.screenshot(name="recovery-after.png")
    assert all(not session.active for session in sessions)
    assert not any(action.action == "download" for action in page.actions)
    source_id = failed.run_id
    if supplied_outcome != "correct":
        bad_result = dict(supplied)
        if supplied_outcome == "wrong_brand":
            bad_result["requested_brand"] = "OTHER_BRAND"
        else:
            state["verify_error"] = True
        assert cli.main(definition, ["resume", source_id, "--from-step", "S003",
                        "--credentials", credentials_arg, "--step-result", json.dumps(bad_result),
                        "--locator-overrides", json.dumps(overrides)]) == 2
        source_id = json.loads(capsys.readouterr().out)["run_id"]
        rejected = json.loads((app_dir / "runs" / source_id / "result.json").read_text())
        assert rejected["outputs"] == previous["outputs"]
        assert rejected["completed_steps"] == previous["completed_steps"]
        assert rejected["inputs"] == previous["inputs"]
        assert not any(action.action == "download" for action in page.actions)
        state["verify_error"] = False
        with cli.open_recovery_session(definition, source_id, credentials=credentials) as recovery:
            assert recovery.context.inputs == previous["inputs"]
            assert recovery.context.service("elements")[BRAND_SELECTED].locator.value != replacement
        # A previous attempt's locator changes must be explicitly supplied again.
        assert cli.main(definition, ["resume", source_id, "--from-step", "S003",
                        "--credentials", credentials_arg, "--step-result", json.dumps(supplied)]) == 2
        source_id = json.loads(capsys.readouterr().out)["run_id"]
    assert cli.main(definition, ["resume", source_id, "--from-step", "S003",
                    "--credentials", credentials_arg, "--step-result", json.dumps(supplied),
                    "--locator-overrides", json.dumps(overrides)]) == 0
    resumed = json.loads(capsys.readouterr().out)
    report_dir = app_dir / "runs" / resumed["run_id"]
    report = json.loads((report_dir / "result.json").read_text())
    events = [json.loads(line) for line in (report_dir / "events.jsonl").read_text().splitlines()]
    assert [(event["step_id"], event["details"]["source"]) for event in events
            if event["event_type"] == "step.succeeded"] == [
                ("S003", "agent"), ("S004", "program"), ("S005", "program"),
            ]
    assert report["inputs"] == previous["inputs"]
    assert all(report["outputs"][key] == previous["outputs"][key] for key in previous["completed_steps"])
    assert Path(report["outputs"]["S005"]["download_path"]).parent == failed.download_dir
    assert source.read_bytes() == source_bytes
    assert not (app_dir / "changed-downloads").exists()
    assert (app_dir / "elements.toml").read_bytes() == (APPLICATION.app_dir / "elements.toml").read_bytes()


def test_login_ignores_displayed_identity_but_requires_session(tmp_path):
    from inventory_jushuitan_export_stock import program
    step = build_program().steps[0]
    ctx = context(tmp_path, Counterexample("different visible identity", FakeState(texts={program.IDENTITY_SURFACE: ("OTHER_ACCOUNT",)})))
    result = step.execute(ctx)
    assert result["authenticated"] is True
    assert result["identity_check_skipped"] is True
    assert "identity_verified" not in result
    assert step.verify(ctx, result)
    result["authenticated"] = False
    assert not step.verify(ctx, result)
