"""Strict JSON helpers for the local agent bridge (extracted subset).

Extracted from ``ask_ai_mcp.ag_oneshot_contract`` (frozen source 725333c2): the strict
UTF-8 and duplicate-key JSON decoding plus the type-strict deep equality that the slice
runner uses. The synthetic profile, request validation and argv builders stay out of
this distribution.
"""

from __future__ import annotations

import json
import math
from typing import Any

# Task work budget for every supported role and host, excluding recovery grace.
TASK_DEADLINE_MAX_SECONDS = 3600


class BridgeContractError(ValueError):
    """Raised when bytes are not exactly one strict JSON document."""


def _decode_strict_utf8(raw: bytes, *, label: str) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise BridgeContractError(f"{label} bytes must not begin with a UTF-8 BOM")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise BridgeContractError(f"{label} bytes are not strict UTF-8") from error


class _DuplicateKeyError(ValueError):
    """Internal marker so duplicate-key rejections keep their own diagnosis."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("duplicate object keys are not accepted at any level")
        result[key] = value
    return result


def _reject_non_finite_constant(token: str) -> float:
    raise ValueError(f"non-finite JSON number literal {token!r} is not accepted")


_STRICT_JSON_DECODER = json.JSONDecoder(
    object_pairs_hook=_reject_duplicate_keys,
    parse_constant=_reject_non_finite_constant,
)


def _reject_non_finite_numbers(value: Any, *, label: str) -> None:
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if type(current) is float and not math.isfinite(current):
            raise BridgeContractError(f"{label} contains a non-finite JSON number")
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def decode_strict_json_bytes(raw: bytes, *, label: str) -> Any:
    """Decode exactly one strict JSON value: UTF-8, no BOM, no duplicate keys.

    Only JSON whitespace may surround the value; trailing documents or any
    other non-whitespace text is rejected. Non-finite numbers (NaN/Infinity
    literals and float overflow such as 1e999) are rejected.
    """
    text = _decode_strict_utf8(raw, label=label)
    stripped = text.lstrip(" \t\n\r")
    try:
        value, end = _STRICT_JSON_DECODER.raw_decode(stripped)
        if stripped[end:].strip(" \t\n\r"):
            raise ValueError("trailing text after the JSON document")
    except _DuplicateKeyError as error:
        raise BridgeContractError(f"{label} contains duplicate object keys") from error
    except RecursionError as error:
        raise BridgeContractError(f"{label} nesting exceeds the supported JSON depth") from error
    except ValueError as error:
        raise BridgeContractError(f"{label} is not exactly one strict JSON document") from error
    _reject_non_finite_numbers(value, label=label)
    return value


def deep_equal_strict(left: Any, right: Any) -> bool:
    """Type-strict JSON deep equality where bool never equals int.

    Iterative on purpose: recursion on hostile nesting would turn a bounded
    comparison into an uncaught RecursionError at the same boundaries the
    JSON decoder must reject.
    """
    stack: list[tuple[Any, Any]] = [(left, right)]
    while stack:
        current_left, current_right = stack.pop()
        if type(current_left) is not type(current_right):
            return False
        if isinstance(current_left, dict):
            if set(current_left) != set(current_right):
                return False
            stack.extend((current_left[key], current_right[key]) for key in current_left)
        elif isinstance(current_left, list):
            if len(current_left) != len(current_right):
                return False
            stack.extend(zip(current_left, current_right, strict=True))
        elif current_left != current_right:
            return False
    return True
