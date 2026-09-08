import json
from pathlib import Path

from rpa_core.cli import RunRequest
from inventory_jushuitan_export_stock import program


def test_console_fields_match_application_inputs(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "input.schema.json").read_text())
    assert set(schema["properties"]) == {"brand_value", "export_filename"}
    assert schema["required"] == ["brand_value"]
    # Use an isolated application root to avoid developer account defaults.
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(program, "APP_DIR", tmp_path / "app")
    options = program.load_runtime_options(RunRequest(
        account_id="SCHEMA_TEST", inputs={"brand_value": "TEST_BRAND"},
        credentials={"username": "test-user", "password": "test-password"},
        download_dir=str(tmp_path / "downloads"),
    ))
    assert options.inputs["brand_value"] == "TEST_BRAND"
    assert options.inputs["export_filename"]
