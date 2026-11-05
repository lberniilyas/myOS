"""Turn a Pydantic model into the JSON Schema subset that structured outputs accept.

Structured outputs need additionalProperties=false on every object and reject numeric and
string-length constraints, so those are stripped here; Pydantic still enforces them when the
response is validated.
"""

import copy

from pydantic import BaseModel

_DROPPED_KEYWORDS = (
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
)


def _clean(node: object) -> None:
    if not isinstance(node, dict):
        return
    for keyword in _DROPPED_KEYWORDS:
        node.pop(keyword, None)
    if "$ref" in node:
        # Keep a bare reference; the referenced definition carries the description.
        for key in [k for k in node if k != "$ref"]:
            del node[key]
        return
    if node.get("type") == "object" or "properties" in node:
        properties = node.setdefault("properties", {})
        node["additionalProperties"] = False
        node["required"] = list(properties)
        for sub_schema in properties.values():
            _clean(sub_schema)
    if "items" in node:
        _clean(node["items"])
    for key in ("anyOf", "allOf", "oneOf"):
        for sub_schema in node.get(key, []):
            _clean(sub_schema)
    for sub_schema in node.get("$defs", {}).values():
        _clean(sub_schema)


def strict_json_schema(model: type[BaseModel]) -> dict:
    schema = copy.deepcopy(model.model_json_schema())
    _clean(schema)
    return schema


def inline_refs(schema: dict) -> dict:
    """Replace every local $ref with its definition and drop $defs (the schema must not recurse)."""
    definitions = schema.get("$defs", {})

    def resolve(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(copy.deepcopy(definitions[name]))
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


# Lowercase "none" is a real enum value in our schemas (e.g. a task with no due date), so it stays.
_NULL_WORDS = {"null", "NULL", "None"}


def restore_nulls(value: object) -> object:
    """Turn the strings "null"/"None" back into real nulls.

    Gemini sometimes writes an omitted optional value as the word "null"; no field in our
    schemas legitimately holds that word.
    """
    if isinstance(value, str) and value.strip() in _NULL_WORDS:
        return None
    if isinstance(value, dict):
        return {key: restore_nulls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [restore_nulls(item) for item in value]
    return value
