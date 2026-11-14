import copy
import json
from pathlib import Path

CONTRACT = Path(__file__).with_name("openapi.json")


def _is_null(schema):
    return isinstance(schema, dict) and schema.get("type") == "null"


def _denull(schema):
    """`anyOf: [X, {type: null}]` → X (the field is optional instead). Swift's generator
    can't express a null branch; an optional property decodes null fine."""
    if not isinstance(schema, dict):
        return schema, False
    options = schema.get("anyOf")
    if options and any(_is_null(o) for o in options):
        rest = [o for o in options if not _is_null(o)]
        merged = {k: v for k, v in schema.items() if k != "anyOf"}
        if len(rest) == 1:
            merged = {**rest[0], **merged}
        else:
            merged["anyOf"] = rest
        return merged, True
    return schema, False


def _walk(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            nullable = []
            for name, prop in props.items():
                props[name], was_null = _denull(prop)
                if was_null:
                    nullable.append(name)
            if "required" in node:
                node["required"] = [r for r in node["required"] if r not in nullable]
                if not node["required"]:
                    del node["required"]
        if "schema" in node and "in" in node:  # a parameter
            node["schema"], _ = _denull(node["schema"])
        for value in node.values():
            _walk(value)
    elif isinstance(node, list):
        for value in node:
            _walk(value)


def schema_json():
    from .api import api

    schema = copy.deepcopy(api.get_openapi_schema(path_prefix="/api/v1"))
    _walk(schema)
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
