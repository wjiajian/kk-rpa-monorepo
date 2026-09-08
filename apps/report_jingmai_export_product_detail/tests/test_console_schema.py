import json
from pathlib import Path

from rpa_core.cli import RunRequest
from report_jingmai_export_product_detail import program


def test_console_fields_match_application_inputs(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "input.schema.json").read_text())
    assert set(schema["properties"]) == {"target_date", "export_filename"}
    assert schema["required"] == ["target_date"]
    # Use an isolated application root to avoid developer account defaults.
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(program, "APP_DIR", tmp_path / "app")
    options = program.load_runtime_options(RunRequest(
        account_id="SCHEMA_TEST", inputs={"target_date": "2026-09-08"},
        credentials={"username": "test-user", "password": "test-password"},
        download_dir=str(tmp_path / "downloads"),
    ))
    assert options.inputs["target_date"] == "2026-09-08"
    assert options.inputs["export_filename"]
