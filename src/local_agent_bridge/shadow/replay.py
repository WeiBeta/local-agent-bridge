"""Content-free replay of sealed sessions and self-contained shadow snapshots.

This module reads authenticated local bytes only. Event lines are framed and
classified by the Bridge parser; no captured instruction is executed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Iterator
from errno import ENOENT

from local_agent_bridge.bridge.slice_run import _event_lines, _parse_or_none, _scan_stream
from local_agent_bridge.capture.keys import SessionKeyError, load_key
from local_agent_bridge.capture.retention import StorageError, _canonical_uuid
from local_agent_bridge.capture.session import (
    FRAME_MAX_PLAINTEXT,
    STREAMS,
    SessionError,
    SessionReader,
    SessionStore,
    _canonical,
)

_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INPUT_PREFIX = b"LocalAgentBridge/input-digest/v2/"
_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    }
)
_SCOPE_LIMIT = 4096


class ShadowError(RuntimeError):
    """A shadow replay cannot establish its requested provenance or comparison."""


def _refusal_reason(error: BaseException) -> str:
    """Classify one refusal as content-free input, bundle or storage category.

    A caller-supplied identifier or digest that cannot address a bundle is an
    input or provenance problem, and an absent bundle is an incomplete bundle;
    neither is reported as a local storage failure. A real read, lock or
    permission failure (for example a denied directory) still is.
    """
    message = str(error)
    if message.startswith("over_limit"):
        return "over_limit"
    if isinstance(error, SessionKeyError):
        return "key_unavailable"
    if isinstance(error, SessionError):
        return "invalid_or_incomplete_bundle"
    if message.startswith("storage_write_failed"):
        return "storage_unavailable"
    if isinstance(error, ShadowError):
        return "input_or_provenance_mismatch"
    if isinstance(error, StorageError) and message.startswith("session reference ID"):
        return "input_or_provenance_mismatch"
    if isinstance(error, FileNotFoundError) or (
        getattr(error, "errno", None) == ENOENT or getattr(error, "winerror", None) in {2, 3}
    ):
        return "invalid_or_incomplete_bundle"
    return "storage_unavailable"


def _require_sha256(value: str) -> str:
    if not isinstance(value, str) or not _HEX_SHA256.fullmatch(value):
        raise ShadowError("expected input digest is not a lowercase SHA-256 value")
    return value


def _stream_identity(manifest: dict) -> dict[str, dict[str, int | str]]:
    return {
        name: {
            "bytes": manifest["streams"][name]["bytes"],
            "sha256": manifest["streams"][name]["sha256"],
        }
        for name in STREAMS
    }


def input_sha256(manifest: dict) -> str:
    """Digest the verified task and request identities, including their lengths."""
    identity = _stream_identity(manifest)
    return hashlib.sha256(
        _INPUT_PREFIX + _canonical({name: identity[name] for name in ("task", "request")})
    ).hexdigest()


def fingerprint(store: SessionStore, uid: str) -> dict[str, str]:
    _canonical_uuid(uid)
    manifest = store.reader(uid).manifest()
    _snapshot_source(manifest)
    return {"domain": store.domain.domain, "uid": uid, "input_sha256": input_sha256(manifest)}


def _verified_manifest(store: SessionStore, uid: str, expected_input_sha256: str) -> dict:
    _canonical_uuid(uid)
    _require_sha256(expected_input_sha256)
    manifest = store.reader(uid).manifest()
    if input_sha256(manifest) != expected_input_sha256:
        raise ShadowError("input digest differs from the sealed bundle")
    return manifest


def _seal_sha256(store: SessionStore, uid: str) -> str:
    seal = store.domain.root / uid / "seal.json"
    return hashlib.sha256(seal.read_bytes()).hexdigest()


def snapshot(
    sessions: SessionStore, shadow: SessionStore, uid: str, expected_input_sha256: str
) -> str:
    """Verify a source, then re-encrypt its four streams into the shadow domain.

    A failure leaves an unsealed, counted partial bundle for manual inspection.
    No source reference is retained, so normal session rolling can continue.
    """
    if sessions.domain.domain != "sessions" or shadow.domain.domain != "shadow":
        raise ShadowError("snapshot stores have the wrong storage domains")
    if sessions.domain.root.resolve() == shadow.domain.root.resolve():
        raise ShadowError("session and shadow storage roots must differ")
    if sessions.key != shadow.key:
        raise ShadowError("snapshot stores must use the same session key")
    source = _verified_manifest(sessions, uid, expected_input_sha256)
    source_seal_sha256 = _seal_sha256(sessions, uid)
    writer = shadow.start()
    reader = sessions.reader(uid)
    for name in STREAMS:
        for chunk in reader.iter_stream(name):
            for offset in range(0, len(chunk), FRAME_MAX_PLAINTEXT):
                if not writer.append(name, chunk[offset : offset + FRAME_MAX_PLAINTEXT]):
                    reason = writer.incomplete_reason or "storage_write_failed"
                    raise ShadowError(f"{reason}: shadow snapshot is incomplete")
    if reader.manifest() != source or _seal_sha256(sessions, uid) != source_seal_sha256:
        raise ShadowError("source session changed during snapshot")
    source_metadata = source.get("metadata")
    exit_code = (
        source_metadata.get("process_exit_code") if isinstance(source_metadata, dict) else None
    )
    writer.seal(
        {
            "process_exit_code": exit_code,
            "shadow_source": {
                "domain": "sessions",
                "uid": uid,
                "seal_sha256": source_seal_sha256,
                "input_sha256": expected_input_sha256,
                "streams": _stream_identity(source),
            },
        }
    )
    return writer.session_id


def _snapshot_source(manifest: dict) -> dict[str, str] | None:
    if manifest.get("domain") != "shadow":
        return None
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ShadowError("shadow source provenance is missing")
    source = metadata.get("shadow_source")
    if not isinstance(source, dict) or source.get("domain") != "sessions":
        raise ShadowError("shadow source provenance is missing")
    uid = source.get("uid")
    seal_sha256 = source.get("seal_sha256")
    input_digest = source.get("input_sha256")
    try:
        _canonical_uuid(uid)
    except StorageError as error:
        raise ShadowError("shadow source UID is invalid") from error
    if not isinstance(seal_sha256, str) or not _HEX_SHA256.fullmatch(seal_sha256):
        raise ShadowError("shadow source seal digest is invalid")
    if input_digest != input_sha256(manifest) or source.get("streams") != _stream_identity(
        manifest
    ):
        raise ShadowError("shadow source stream identity differs")
    return {"uid": uid, "seal_sha256": seal_sha256}


class _StdoutView:
    def __init__(self, reader: SessionReader) -> None:
        self.reader = reader

    def iter_chunks(self) -> Iterator[bytes]:
        return self.reader.iter_stream("stdout")


def _scope_values(record: dict, field: str) -> list[str] | None:
    value = record.get(field)
    if not isinstance(value, list) or len(value) > _SCOPE_LIMIT:
        return None
    items: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("name" if field in {"tools", "tool_calls"} else "path")
        if not isinstance(item, str) or not item or len(item) > 1024:
            return None
        items.append(item)
    return items


def _observations(reader: SessionReader) -> dict[str, object]:
    statuses, _last, denied, error_seen, malformed = _scan_stream(_StdoutView(reader))
    if malformed:
        return {
            "parse_state": "malformed",
            "terminal": None,
            "denied_actions_seen": None,
            "error_seen": None,
            "tool_scope": {"state": "incomparable"},
            "file_scope": {"state": "incomparable"},
            "usage": None,
        }
    scopes: dict[str, set[str]] = {"tool": set(), "file": set()}
    scope_seen = {"tool": False, "file": False}
    scope_bad = {"tool": False, "file": False}
    usages: list[dict[str, int]] = []
    usage_bad = False
    for line in _event_lines(reader.iter_stream("stdout")):
        value = _parse_or_none(line)
        if not isinstance(value, dict):
            continue  # _scan_stream already established the whole stream shape.
        payload = value.get(value.get("event")) if "event" in value else value
        if not isinstance(payload, dict):
            continue
        records = (value, payload) if payload is not value else (value,)
        for record in records:
            scope_fields = (("tool", ("tools", "tool_calls")), ("file", ("files", "file_paths")))
            for kind, fields in scope_fields:
                for field in fields:
                    if field not in record:
                        continue
                    scope_seen[kind] = True
                    found = _scope_values(record, field)
                    if found is None or len(scopes[kind]) + len(found) > _SCOPE_LIMIT:
                        scope_bad[kind] = True
                    else:
                        scopes[kind].update(found)
            if "usage" in record:
                usage = record["usage"]
                if not isinstance(usage, dict):
                    usage_bad = True
                    continue
                selected = {
                    key: value
                    for key, value in usage.items()
                    if key in _USAGE_FIELDS
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 <= value < 2**63
                }
                if any(key in _USAGE_FIELDS and key not in selected for key in usage):
                    usage_bad = True
                if selected:
                    usages.append(selected)

    def scope(kind: str) -> dict[str, object]:
        if scope_bad[kind]:
            return {"state": "incomparable"}
        if not scope_seen[kind]:
            return {"state": "missing"}
        values = sorted(scopes[kind])
        return {
            "state": "observed",
            "count": len(values),
            "sha256": hashlib.sha256(_canonical(values)).hexdigest(),
        }

    terminal = None
    if len(statuses) == 1:
        status = next(iter(statuses))
        terminal = {
            "label": status if status in {"SUCCESS", "ERROR"} else "other",
            "sha256": hashlib.sha256(_canonical(status)).hexdigest(),
        }
    usage_conflict = bool(usages) and not all(usage == usages[0] for usage in usages)
    terminal_state = "conflicting" if len(statuses) > 1 else "observed" if statuses else "missing"
    usage_state = (
        "incomparable" if usage_bad or usage_conflict else "observed" if usages else "missing"
    )
    return {
        "parse_state": "parsed",
        "terminal": terminal,
        "terminal_state": terminal_state,
        "denied_actions_seen": denied,
        "error_seen": error_seen,
        "tool_scope": scope("tool"),
        "file_scope": scope("file"),
        "usage": usages[0] if not usage_bad and not usage_conflict and usages else None,
        "usage_state": usage_state,
    }


def replay(store: SessionStore, uid: str, expected_input_sha256: str) -> dict[str, object]:
    """Report only authenticated, observable fields; never return stream content."""
    manifest = _verified_manifest(store, uid, expected_input_sha256)
    provenance = _snapshot_source(manifest)
    observed = _observations(store.reader(uid))
    metadata = manifest.get("metadata", {})
    exit_code = metadata.get("process_exit_code") if isinstance(metadata, dict) else None
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = None
    return {
        "domain": store.domain.domain,
        "uid": uid,
        "source": provenance,
        "input_sha256": expected_input_sha256,
        "output_sha256": {
            name: manifest["streams"][name]["sha256"] for name in ("stdout", "stderr")
        },
        "process_exit_code": exit_code,
        **observed,
    }


def compare(first: dict[str, object], second: dict[str, object]) -> dict[str, object]:
    """Keep missing observations explicit; differing inputs cannot support a run comparison."""
    same_input = first["input_sha256"] == second["input_sha256"]
    fields = (
        "terminal",
        "denied_actions_seen",
        "error_seen",
        "tool_scope",
        "file_scope",
        "process_exit_code",
        "output_sha256",
    )
    results = {}
    for field in fields:
        left, right = first.get(field), second.get(field)
        if not same_input:
            results[field] = {"state": "incomparable", "reason": "input_differs"}
        elif field not in {"process_exit_code", "output_sha256"} and (
            first.get("parse_state") != "parsed" or second.get("parse_state") != "parsed"
        ):
            results[field] = {"state": "incomparable", "reason": "event_parse"}
        elif (
            left is None
            or right is None
            or (isinstance(left, dict) and left.get("state") != "observed" and "state" in left)
            or (isinstance(right, dict) and right.get("state") != "observed" and "state" in right)
        ):
            results[field] = {"state": "incomparable", "reason": "missing_observation"}
        else:
            results[field] = {"state": "equal" if left == right else "different"}

    left_usage, right_usage = first.get("usage"), second.get("usage")
    if not same_input:
        results["usage"] = {"state": "incomparable", "reason": "input_differs"}
    elif first.get("parse_state") != "parsed" or second.get("parse_state") != "parsed":
        results["usage"] = {"state": "incomparable", "reason": "event_parse"}
    elif not isinstance(left_usage, dict) or not isinstance(right_usage, dict):
        results["usage"] = {"state": "incomparable", "reason": "missing_observation"}
    else:
        usage_fields = {}
        for name in sorted(left_usage.keys() | right_usage.keys()):
            if name not in left_usage or name not in right_usage:
                usage_fields[name] = "incomparable"
            else:
                usage_fields[name] = (
                    "equal" if left_usage[name] == right_usage[name] else "different"
                )
        if "incomparable" in usage_fields.values():
            state = "incomparable"
        elif "different" in usage_fields.values():
            state = "different"
        else:
            state = "equal"
        results["usage"] = {"state": state, "fields": usage_fields}
    return {
        "input": {"state": "equal" if same_input else "different"},
        "fields": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-agent-bridge shadow")
    commands = parser.add_subparsers(dest="action", required=True)
    fingerprint_command = commands.add_parser("fingerprint", help="verify and show input digest")
    fingerprint_command.add_argument("domain", choices=("sessions", "shadow"))
    fingerprint_command.add_argument("uid")
    snapshot_command = commands.add_parser("snapshot", help="re-encrypt a sealed session")
    snapshot_command.add_argument("uid")
    snapshot_command.add_argument("input_sha256")
    replay_command = commands.add_parser("replay", help="summarize one sealed bundle")
    replay_command.add_argument("domain", choices=("sessions", "shadow"))
    replay_command.add_argument("uid")
    replay_command.add_argument("input_sha256")
    compare_command = commands.add_parser("compare", help="compare two sealed bundles")
    for side in ("first", "second"):
        compare_command.add_argument(f"{side}_domain", choices=("sessions", "shadow"))
        compare_command.add_argument(f"{side}_uid")
        compare_command.add_argument(f"{side}_input_sha256")
    return parser


def main(argv: list[str]) -> int:
    arguments = _parser().parse_args(argv)
    try:
        key = load_key()
        stores = {name: SessionStore(key, domain_name=name) for name in ("sessions", "shadow")}
        if arguments.action == "fingerprint":
            result = fingerprint(stores[arguments.domain], arguments.uid)
        elif arguments.action == "snapshot":
            uid = snapshot(
                stores["sessions"], stores["shadow"], arguments.uid, arguments.input_sha256
            )
            result = {"domain": "shadow", "uid": uid, "input_sha256": arguments.input_sha256}
        elif arguments.action == "replay":
            result = replay(stores[arguments.domain], arguments.uid, arguments.input_sha256)
        else:
            first = replay(
                stores[arguments.first_domain],
                arguments.first_uid,
                arguments.first_input_sha256,
            )
            second = replay(
                stores[arguments.second_domain],
                arguments.second_uid,
                arguments.second_input_sha256,
            )
            result = compare(first, second)
    except (SessionError, SessionKeyError, ShadowError, StorageError, OSError, ValueError) as error:
        reason = _refusal_reason(error)
        print(_canonical({"state": "refused", "reason": reason}).decode(), file=sys.stderr)
        return 2
    print(_canonical(result).decode("ascii"))
    return 0
