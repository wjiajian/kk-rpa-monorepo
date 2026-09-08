import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

from rpa_executor.deployments import deployment_metadata


def test_missing_and_invalid_declarations_are_distinct(tmp_path):
    deployment = {"app_id": "sample", "version": "1", "cwd": str(tmp_path)}
    assert deployment_metadata(deployment)["schema_status"] == "missing"
    manifest = tmp_path / "app.toml"
    manifest.write_text('app_id="sample"\n[console]\ninput_schema="input.schema.json"\n')
    assert deployment_metadata(deployment)["schema_status"] == "invalid"
    schema = tmp_path / "input.schema.json"
    schema.write_text('{"type":"object","properties":{"name":{"type":"nonexistent"}}}')
    result = deployment_metadata(deployment)
    assert result["schema_status"] == "invalid"
    assert "properties.name.type" in result["schema_error"]
    schema.write_text('{"type":"object","properties":{"name":{"$ref":"https://example.invalid/schema"}}}')
    assert deployment_metadata(deployment)["schema_status"] == "invalid"
    manifest.write_text('app_id="sample"\n[console]\ninput_schema="../outside.json"\n')
    assert "应用目录内" in deployment_metadata(deployment)["schema_error"]


@pytest.mark.parametrize("app,key,value", [
    ("inventory_jushuitan_export_stock", "brand_value", "TEST_BRAND"),
    ("report_jingmai_export_product_detail", "target_date", "2026-09-08"),
])
def test_real_application_declarations(app, key, value):
    import tomllib
    root = Path(__file__).resolve().parents[3] / "apps" / app
    manifest = tomllib.loads((root / "app.toml").read_text())
    result = deployment_metadata({"app_id": manifest["app_id"], "version": "test", "cwd": root})
    assert result["schema_status"] == "valid"
    schema = result["input_schema"]
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    assert validator.is_valid({key: value})
    assert not validator.is_valid({})
    assert not validator.is_valid({key: "   "})
    assert not validator.is_valid({key: value, "unknown": 1})
    assert not validator.is_valid({key: value, "export_filename": "../report.xlsx"})
    assert not validator.is_valid({key: value, "export_filename": "report.xlsx\n"})
    assert all("default" not in field for field in schema["properties"].values())
