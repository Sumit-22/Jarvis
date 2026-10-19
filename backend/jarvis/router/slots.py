"""Slot filling: templates -> concrete step args, and params validation against params_schema."""
from __future__ import annotations

import re
from typing import Any

_WHOLE = re.compile(r"^\{(\w+)\}$")
_PART = re.compile(r"\{(\w+)\}")


def fill_template(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        m = _WHOLE.match(value)
        if m:
            return params.get(m.group(1))
        return _PART.sub(lambda mm: str(params.get(mm.group(1), "")), value)
    if isinstance(value, dict):
        return {k: fill_template(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_template(v, params) for v in value]
    return value


def build_steps(workflow_steps: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for s in workflow_steps:
        args = fill_template(s.get("args_template", {}), params)
        args = {k: v for k, v in args.items() if v is not None}
        out.append({"tool": s["tool"], "args": args})
    return out


def missing_params(params_schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
    return [p for p in params_schema.get("required", []) if params.get(p) in (None, "")]


def coerce_params(params_schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Lowercase a value only when its schema pattern requires it (e.g. 'Two-Sum' -> 'two-sum' for a slug)."""
    out = dict(params)
    for name, spec in params_schema.get("properties", {}).items():
        v, pat = out.get(name), spec.get("pattern")
        if isinstance(v, str) and pat and not re.fullmatch(pat, v) and re.fullmatch(pat, v.lower()):
            out[name] = v.lower()
    return out


def validate_params(params_schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Minimal JSON-Schema check (types + pattern) without an extra dependency. Returns error strings."""
    errors = []
    props = params_schema.get("properties", {})
    for name, value in params.items():
        spec = props.get(name)
        if spec is None:
            continue
        t = spec.get("type")
        if t == "string" and not isinstance(value, str):
            errors.append(f"{name} must be a string")
        elif t == "integer" and not isinstance(value, int):
            errors.append(f"{name} must be an integer")
        pat = spec.get("pattern")
        if pat and isinstance(value, str) and not re.fullmatch(pat, value):
            errors.append(f"{name}={value!r} does not match {pat}")
    return errors
