"""Offline tests for the extracted strict-JSON bridge contract helpers.

Only the helpers the slice runner uses are in the distribution: strict UTF-8 and
duplicate-key JSON decoding plus type-strict deep equality. The synthetic profile,
request validation and argv builders deliberately stay out, so their tests stay
with the retired package. No provider, file system or MCP surface is involved.
"""

from __future__ import annotations

import json

import pytest

from local_agent_bridge.bridge.contract import (
    BridgeContractError,
    decode_strict_json_bytes,
    deep_equal_strict,
)


def test_decode_strict_json_bytes_enforces_single_strict_document() -> None:
    good = json.dumps({"a": 1}).encode("utf-8")
    assert decode_strict_json_bytes(b"  \n\t " + good + b" \r\n ", label="x") == {"a": 1}
    bad_documents = [
        (b'{"a": 1, "a": 2}', "duplicate"),
        (good + b' {"a": 2}', "strict JSON"),
        (good + b" trailing", "strict JSON"),
        (b'{"a": NaN}', "strict JSON"),
        (b'{"a": Infinity}', "strict JSON"),
        (b'{"a": 1e999}', "non-finite"),
        (b"\xef\xbb\xbf" + good, "BOM"),
        (b'{"a": "\xff\xfe"}', "UTF-8"),
        (b"", "strict JSON"),
    ]
    for raw, reason in bad_documents:
        with pytest.raises(BridgeContractError, match=reason):
            decode_strict_json_bytes(raw, label="x")


def test_negative_float_overflow_rejected_and_underflow_stays_finite() -> None:
    with pytest.raises(BridgeContractError, match="non-finite"):
        decode_strict_json_bytes(b'{"a": -1e999}', label="x")
    assert decode_strict_json_bytes(b'{"a": 1e-999}', label="x") == {"a": 0.0}


def _deep_list(depth: int) -> list:
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


def test_deep_equal_strict_handles_deep_nesting_iteratively() -> None:
    left = _deep_list(5000)
    right = _deep_list(5000)
    assert deep_equal_strict(left, right) is True
    inner = right
    for _ in range(4999):
        inner = inner[0]
    inner.append(1)
    assert deep_equal_strict(left, right) is False


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ({"const": False}, {"const": 0}, False),
        ({"const": 0}, {"const": False}, False),
        ({"const": True}, {"const": 1}, False),
        ({"const": 42}, {"const": 42.0}, False),
        ({"a": [1, 2], "b": {"c": None}}, {"b": {"c": None}, "a": [1, 2]}, True),
        ([1, 2], [2, 1], False),
        ([1, 2], [1, 2, 3], False),
        ("x", "x", True),
    ],
)
def test_deep_equal_strict(left: object, right: object, expected: bool) -> None:
    assert deep_equal_strict(left, right) is expected
