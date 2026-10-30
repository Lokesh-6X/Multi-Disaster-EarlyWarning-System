"""The MQTT reading contract (design/05 §5.2.2) and the check every outgoing message passes (11 §11.7, DD135).

A small validator for exactly the JSON Schema keywords contract.schema.json uses, so the simulator needs no
`jsonschema` package. Numbers must be finite (JSON has no NaN or Infinity).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

SCHEMA_FILE = Path(__file__).with_name("contract.schema.json")
MAX_BYTES = 4096
KEYWORDS = {"$schema", "$id", "title", "description", "type", "additionalProperties", "required", "properties",
            "minimum", "maximum", "exclusiveMaximum", "minLength", "maxLength", "pattern"}


class ContractError(Exception):
    """An outgoing message broke the contract: a simulator bug, so the run stops (11 §11.7)."""


def load_schema(path: Path = SCHEMA_FILE) -> dict[str, Any]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    used = set(schema) | {k for spec in schema["properties"].values() for k in spec}
    if used - KEYWORDS:
        raise ValueError(f"contract.schema.json uses keywords this validator does not know: {sorted(used - KEYWORDS)}")
    return schema


SCHEMA = load_schema()


def _is(kind: str, value: Any) -> bool:
    if kind == "null":
        return value is None
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    raise ValueError(f"unknown type {kind!r}")


def problems(message: Any, schema: dict[str, Any] = SCHEMA) -> list[str]:
    """Everything wrong with one message; [] = valid."""
    if not isinstance(message, dict):
        return ["the message must be a JSON object"]
    out = [f"missing field {name}" for name in schema["required"] if name not in message]
    for name, value in message.items():
        spec = schema["properties"].get(name)
        if spec is None:
            if schema.get("additionalProperties") is False:
                out.append(f"unknown field {name}")
            continue
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if not any(_is(k, value) for k in kinds):
            out.append(f"{name}: expected {' or '.join(kinds)}, got {value!r}")
            continue
        if value is None:
            continue
        if "minimum" in spec and value < spec["minimum"]:
            out.append(f"{name}: {value} is below {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            out.append(f"{name}: {value} is above {spec['maximum']}")
        if "exclusiveMaximum" in spec and value >= spec["exclusiveMaximum"]:
            out.append(f"{name}: {value} must be below {spec['exclusiveMaximum']}")
        if "minLength" in spec and len(value) < spec["minLength"]:
            out.append(f"{name}: shorter than {spec['minLength']} characters")
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            out.append(f"{name}: longer than {spec['maxLength']} characters")
        if "pattern" in spec and not re.search(spec["pattern"], value):
            out.append(f"{name}: {value!r} does not match {spec['pattern']}")
    return out


def encode(message: dict[str, Any]) -> bytes:
    """Check and serialise one reading; raises ContractError."""
    found = problems(message)
    payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8") if not found else b""
    if len(payload) > MAX_BYTES:
        found.append(f"payload is {len(payload)} bytes, more than {MAX_BYTES}")
    if found:
        raise ContractError("; ".join(found))
    return payload
