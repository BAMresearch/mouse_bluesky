from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .models import CollatePolicy


def parse_additional_parameters(raw: Mapping[str, str]) -> dict[str, Any]:
    """Parse logbook additional_parameters (str->str) into JSON-friendly values.

    Supported:
    - Plain key/value strings (values stay strings, except 'collate').
    - Optional JSON blob under key '__json__' containing a JSON object. Parsed values override.

    Example:
      {'__json__': '{"repeats": [3, 4], "configs": [123, 125], "collate": "ALLOW"}'}
    """
    out: dict[str, Any] = {str(k): str(v) for k, v in raw.items()}

    json_blob = out.pop("__json__", None)
    if json_blob is not None:
        try:
            parsed = json.loads(json_blob)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in additional_parameters['__json__']: {e}") from e
        if not isinstance(parsed, dict):
            raise ValueError("additional_parameters['__json__'] must contain a JSON object")
        out.update(parsed)

    if "collate" in out:
        val = out["collate"]
        if isinstance(val, str):
            out["collate"] = CollatePolicy(val.strip().upper())
        elif not isinstance(val, CollatePolicy):
            raise ValueError(f"'collate' must be a string or CollatePolicy, got {type(val)}")

    return out
