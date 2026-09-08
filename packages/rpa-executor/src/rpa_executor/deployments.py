"""Read console declarations without importing application code."""
import json
from pathlib import Path
import tomllib

from jsonschema import Draft7Validator, SchemaError


def deployment_metadata(deployment):
    result = {key: deployment[key] for key in ("app_id", "version")}
    if deployment.get("release_id"):
        result["release_id"] = deployment["release_id"]
        result["commit"] = deployment.get("commit")
    root = Path(deployment["cwd"]).resolve()
    manifest = root / "app.toml"
    if not manifest.exists():
        return {**result, "schema_status": "missing"}
    source = "app.toml"
    try:
        app = tomllib.loads(manifest.read_text(encoding="utf-8"))
        if app.get("app_id") != deployment["app_id"]:
            raise ValueError("app.toml 的应用 ID 与部署配置不一致")
        console = app.get("console", {})
        if not isinstance(console, dict):
            raise ValueError("app.toml 的 console 必须为对象")
        if "input_schema" not in console:
            return {**result, "schema_status": "missing"}
        reference = console["input_schema"]
        if not isinstance(reference, str) or not reference:
            raise ValueError("input_schema 必须为相对文件路径")
        path = (root / reference).resolve()
        if Path(reference).is_absolute() or not path.is_relative_to(root):
            raise ValueError("input_schema 必须位于应用目录内")
        source = path.relative_to(root).as_posix()
        schema = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("参数声明根节点必须为 object")
        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    raise ValueError("参数声明不支持 $ref，请内联字段定义")
                for item in value.values():
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)
        check_refs(schema)
        Draft7Validator.check_schema(schema)
        return {**result, "schema_status": "valid", "input_schema": schema}
    except SchemaError as error:
        location = ".".join(map(str, error.absolute_path)) or "根节点"
        message = f"{source}：{location} 的声明无效（{error.validator}）"
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        message = f"{source}：无法读取参数声明（{type(error).__name__}）"
    except ValueError as error:
        message = f"{source}：{error}"
    return {**result, "schema_status": "invalid", "schema_error": message}
