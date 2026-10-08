"""Closed, sdist-only, one-UID stdout reanalysis. No plaintext or command export.

Executable use requires a separately approved, externally hash-bound Review sheet.
The first stage tests private byte functions with synthetic keys/events only.
No SessionStore/SessionReader: those authenticate every stream in a bundle.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import stat
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TASK_ID = "LAB-AGY-LIVE-ADAPTER-REPAIR-01"
UID = "a357f09f-86a9-410e-9a76-32acf462f575"
BUNDLE = Path(
    "C:/Users/user/Documents/Codex-Archive/2026-10-08-LAB-FIRST-R-V2-LIVE-01"
    "/encrypted-capture/" + UID
)
OUTPUT = Path("C:/Users/user/Documents/Codex-Scratch") / TASK_ID / "stage-two"
CONFIG = Path(__file__).with_suffix(".json")
SCHEMA = Path(__file__).with_name("agy_stdout_reanalysis.schema.json")
MAGIC = b"LABFRAME2\n"
HEADER = struct.Struct(">IQ12s")
MAX_BYTES = 262144
MAX_LINE = 65536
MAX_LINES = 1024
MAX_STEPS = 256
MAX_DEPTH = 16
EVENTS = {"init", "step_update", "result"}
STEP_TYPES = {"user_input", "agent_response", "tool", "checkpoint"}
TOOLS = {"run_command", "write_to_file", "ask_permission"}
STATES = {"ACTIVE", "DONE"}
RESULTS = {"SUCCESS", "ERROR", "CANCELLED"}
COMPARISONS = {"Match", "Mismatch", "Unknown"}


class Refused(RuntimeError):
    """Fixed, nonsensitive failure code only."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("DuplicateJsonKey")
        result[key] = value
    return result


def _reject_constant(_):
    raise Refused("InvalidJsonConstant")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise Refused("InvalidJsonNumber")
    return result


def _json(raw: bytes):
    # Bound nesting before json.loads, including hostile unknown fields.
    depth = 0
    quoted = escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_DEPTH:
                raise Refused("JsonDepthLimit")
        elif byte in (93, 125):
            depth -= 1
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Refused("MalformedJson") from error
    pending = [value]
    nodes = 0
    while pending:
        item = pending.pop()
        nodes += 1
        if nodes > 4096:
            raise Refused("JsonNodeLimit")
        if isinstance(item, dict):
            if len(item) > 128:
                raise Refused("JsonContainerLimit")
            pending.extend(item.values())
        elif isinstance(item, list):
            if len(item) > 128:
                raise Refused("JsonContainerLimit")
            pending.extend(item)
    if not isinstance(value, dict):
        raise Refused("JsonObjectRequired")
    return value


def _known(value, choices):
    return value if isinstance(value, str) and value in choices else "Unknown"


def _compare(value, expected):
    if not isinstance(value, str) or not value or not expected:
        return "Unknown"
    return "Match" if _sha(value.encode()) in expected else "Mismatch"


def _analyze(plaintext: bytes, recipes: dict) -> dict:
    if len(plaintext) > MAX_BYTES:
        raise Refused("StreamByteLimit")
    lines = plaintext.splitlines(keepends=True)
    if len(lines) > MAX_LINES:
        raise Refused("EventLimit")
    counts = dict.fromkeys(sorted(EVENTS | {"Unknown"}), 0)
    events = []
    steps = {}
    conversation = None
    result_status = "Unknown"
    init_cwd = "Unknown"
    conflict = False
    terminal = False
    seen_init = False
    truncated = bool(plaintext and not plaintext.endswith(b"\n"))
    for number, raw in enumerate(lines, 1):
        if len(raw) > MAX_LINE:
            raise Refused("EventByteLimit")
        value = _json(raw)
        category = _known(value.get("event"), EVENTS)
        counts[category] += 1
        events.append({"line": number, "raw_event_sha256": _sha(raw), "category": category})
        if terminal:
            conflict = True
        payload = value.get(category)
        if not isinstance(payload, dict):
            continue
        identity = payload.get("conversation_id", value.get("conversation_id"))
        if isinstance(identity, str):
            if conversation is not None and conversation != identity:
                conflict = True
            conversation = identity
        if category == "init":
            conflict |= seen_init or bool(steps)
            seen_init = True
            init_cwd = _compare(payload.get("cwd"), recipes["cwd_sha256"])
        elif category == "result":
            terminal = True
            result_status = _known(payload.get("status"), RESULTS)
        elif category == "step_update":
            index = payload.get("step_index")
            if type(index) is not int or not 0 <= index <= 1000000:
                continue
            if index not in steps:
                if len(steps) >= MAX_STEPS:
                    raise Refused("StepLimit")
                steps[index] = {
                    "step_index": index,
                    "order": len(steps) + 1,
                    "category": "Unknown",
                    "tool": "Unknown",
                    "states": [],
                    "command": {"reproduce": "Unknown", "regression": "Unknown"},
                    "exit_code": None,
                    "argv": "Unknown",
                    "cwd": "Unknown",
                    "_command_hash": None,
                }
            step = steps[index]
            kind = _known(payload.get("step_type"), STEP_TYPES)
            if step["category"] != "Unknown" and kind != step["category"]:
                conflict = True
            step["category"] = kind
            state = _known(payload.get("state"), STATES)
            if "DONE" in step["states"]:
                conflict = True  # repeated DONE or regression to ACTIVE is ambiguous
            if len(step["states"]) >= MAX_LINES:
                raise Refused("TransitionLimit")
            step["states"].append(state)
            info = payload.get("tool_info")
            if kind != "tool" or not isinstance(info, dict):
                continue
            tool = _known(payload.get("tool_name", info.get("name")), TOOLS)
            if "name" in info and tool != _known(info["name"], TOOLS):
                conflict = True
            if step["tool"] != "Unknown" and tool != step["tool"]:
                conflict = True
            step["tool"] = tool
            parameters = info.get("parameters")
            command = parameters.get("CommandLine") if isinstance(parameters, dict) else None
            if tool == "run_command" and isinstance(command, str):
                command_hash = _sha(command.encode())
                if step["_command_hash"] not in (None, command_hash):
                    conflict = True
                step["_command_hash"] = command_hash
                step["command"] = {
                    phase: _compare(command, recipes[phase + "_command_sha256"])
                    for phase in ("reproduce", "regression")
                }
            # This optional numeric field is only CLI-declared. Never parse output/error text.
            code = info.get("exit_code")
            if type(code) is int and -2147483648 <= code <= 2147483647:
                if step["exit_code"] not in (None, code):
                    conflict = True
                step["exit_code"] = code
    missing_done = any(not s["states"] or s["states"][-1] != "DONE" for s in steps.values())
    status = (
        "Conflict"
        if conflict
        else (
            "Incomplete"
            if truncated or not seen_init or not terminal or missing_done
            else "Complete"
        )
    )
    for step in steps.values():
        del step["_command_hash"]
        if status != "Complete":
            step["command"] = dict.fromkeys(("reproduce", "regression"), "Unknown")
    return {
        "schema_version": 1,
        "origin": "CliDeclared",
        "status": status,
        "events": events,
        "event_categories": counts,
        "steps": list(steps.values()),
        "init_cwd": init_cwd if status == "Complete" else "Unknown",
        "result_status": result_status,
        "shell": "Unknown",
        "actual_invocations": None,
        "management_decision": None,
    }


def _plain_file(path: Path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Refused("PathAlias")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Refused("NotSingleRegularFile")
    return info


def _read_bound(path: Path, binding: dict) -> bytes:
    before = _plain_file(path)
    if before.st_size != binding["bytes"] or before.st_size > MAX_BYTES:
        raise Refused("FileLengthMismatch")
    with path.open("rb") as source:
        opened = os.fstat(source.fileno())
        if not os.path.samestat(before, opened):
            raise Refused("FileIdentityMismatch")
        raw = source.read(binding["bytes"] + 1)
        after = os.fstat(source.fileno())
    final = _plain_file(path)
    if (
        not os.path.samestat(opened, final)
        or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or (after.st_size, after.st_mtime_ns) != (final.st_size, final.st_mtime_ns)
    ):
        raise Refused("FileChanged")
    if len(raw) != binding["bytes"] or _sha(raw) != binding["sha256"]:
        raise Refused("FileHashMismatch")
    return raw


def _authenticate(raw: dict[str, bytes], key: bytes, config: dict) -> bytes:
    opening = _json(raw["open.json"])
    envelope = _json(raw["seal.json"])
    manifest = envelope.get("manifest")
    if not isinstance(manifest, dict) or _sha(_canonical(manifest)) != config["manifest_sha256"]:
        raise Refused("ManifestBindingMismatch")
    for value in (opening, manifest):
        if (
            value.get("schema_version") != 2
            or value.get("session_id") != config["uid"]
            or (value.get("domain") != "sessions")
        ):
            raise Refused("SessionBindingMismatch")
    if envelope.get("schema_version") != 2 or manifest.get("state") != "complete":
        raise Refused("IncompleteSeal")
    for name in ("open.json", "stdout.enc"):
        if manifest.get("files", {}).get(name) != config["files"][name]:
            raise Refused("ManifestFileMismatch")
    expected = manifest.get("streams", {}).get("stdout")
    if (
        not isinstance(expected, dict)
        or expected.get("complete") is not True
        or (expected.get("bytes"), expected.get("sha256"))
        != (config["plaintext"]["bytes"], config["plaintext"]["sha256"])
    ):
        raise Refused("PlaintextBindingMismatch")
    cipher = AESGCM(key)
    try:
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        tag = base64.b64decode(envelope["tag"], validate=True)
        if len(nonce) != 12 or len(tag) != 16:
            raise Refused("InvalidSealShape")
        cipher.decrypt(
            nonce, tag, b"LocalAgentBridge/session-seal/v2/sessions/" + _canonical(manifest)
        )
        data = raw["stdout.enc"]
        if not data.startswith(MAGIC):
            raise Refused("FrameHeaderMismatch")
        offset = len(MAGIC)
        sequence = 0
        plaintext = bytearray()
        while offset < len(data):
            if len(data) - offset < HEADER.size:
                raise Refused("TruncatedFrame")
            length, found, nonce = HEADER.unpack_from(data, offset)
            offset += HEADER.size
            if found != sequence or not 16 <= length <= 65552 or len(data) - offset < length:
                raise Refused("FrameSequenceOrLength")
            aad = f"LocalAgentBridge/session-frame/v2/sessions/{config['uid']}/stdout/{sequence}"
            plaintext.extend(
                cipher.decrypt(nonce, data[offset : offset + length], aad.encode("ascii"))
            )
            if len(plaintext) > MAX_BYTES:
                raise Refused("StreamByteLimit")
            offset += length
            sequence += 1
    except Refused:
        raise
    except Exception as error:
        raise Refused("AuthenticationFailed") from error
    if (sequence, len(plaintext), _sha(plaintext)) != (
        expected.get("frames"),
        config["plaintext"]["bytes"],
        config["plaintext"]["sha256"],
    ):
        raise Refused("PlaintextHashOrFrameCount")
    return bytes(plaintext)


def _run_once(bundle: Path, output: Path, config: dict, key_loader) -> dict:
    # Private test seam. The executable fixes bundle/output/config; no path/UID override.
    for parent in output.parents:
        if getattr(parent.lstat(), "st_file_attributes", 0) & 0x400 or parent.is_symlink():
            raise Refused("PathAlias")
    output.mkdir(exist_ok=False)
    with (output / "attempt.consumed.json").open("xb") as marker:
        marker.write(b'{"key_read_cap":1,"stdout_authentication_cap":1,"retry":false}\n')
        marker.flush()
        os.fsync(marker.fileno())
    # Attempts are consumed even if a binding, key, authentication or parser check fails.
    raw = {
        name: _read_bound(bundle / name, config["files"][name])
        for name in ("open.json", "seal.json", "stdout.enc")
    }
    try:
        key = key_loader()  # exactly one call; never fallback/create
        plaintext = _authenticate(raw, key, config)
        result = _analyze(plaintext, config["recipes"])
    finally:
        raw.clear()
        # No file cache; Python/crypto memory is not a zeroization guarantee.
        key = plaintext = None
    with (output / "result.json").open("xb") as target:
        target.write(_canonical(result) + b"\n")
        target.flush()
        os.fsync(target.fileno())
    return result


def _load_key():
    # Require the locked transport before win32ctypes can select its ctypes fallback.
    import cffi  # noqa: F401
    from win32ctypes import core

    if core._backend != "cffi":
        raise Refused("KeyBackendRefused")
    from win32ctypes.pywin32 import win32cred

    # No keyring discovery/constructor or get_password's compound-target second read.
    credential = win32cred.CredRead(
        TargetName="LocalAgentBridge.SessionCapture.v1",
        Type=win32cred.CRED_TYPE_GENERIC,
        Flags=0,
    )
    if not isinstance(credential, dict) or credential.get("UserName") != "aes256gcm-session-v1":
        raise Refused("KeyAccountRefused")
    blob = credential.get("CredentialBlob")
    if not isinstance(blob, bytes) or len(blob) != 88:
        raise Refused("KeyShapeRefused")
    try:
        # The locked Windows writer stores its 44 ASCII base64 characters as UTF-16LE.
        key = base64.b64decode(blob.decode("utf-16-le"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError):
        raise Refused("KeyShapeRefused") from None
    if len(key) != 32:
        raise Refused("KeyShapeRefused")
    return key


def _approved(sheet: dict, artifacts: dict):
    fields = {
        "task_id",
        "uid",
        "author_confirmed",
        "review",
        "artifacts",
        "max_key_reads",
        "max_stdout_authentications",
        "grant_ref",
    }
    if (
        set(sheet) != fields
        or sheet["task_id"] != TASK_ID
        or sheet["uid"] != UID
        or (sheet["author_confirmed"] is not True or sheet["review"] != "Passed")
        or type(sheet["max_key_reads"]) is not int
        or sheet["max_key_reads"] != 1
        or (
            type(sheet["max_stdout_authentications"]) is not int
            or sheet["max_stdout_authentications"] != 1
        )
        or sheet["artifacts"] != artifacts
        or not isinstance(sheet["grant_ref"], str)
        or (not sheet["grant_ref"].strip())
    ):
        raise Refused("ApprovalRefused")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Approved single-UID stdout reanalysis only")
    parser.add_argument("--approval", required=True, type=Path)
    parser.add_argument("--expected-approval-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if sys.platform != "win32" or sys.version_info[:2] != (3, 13):
            raise Refused("RuntimeRefused")
        _plain_file(args.approval)
        if args.approval.stat().st_size > 32768:
            raise Refused("ApprovalSizeRefused")
        raw_sheet = args.approval.read_bytes()
        if _sha(raw_sheet) != args.expected_approval_sha256:
            raise Refused("ApprovalHashMismatch")
        artifacts = {}
        raw_config = None
        for name, path in (("code", Path(__file__)), ("config", CONFIG), ("schema", SCHEMA)):
            _plain_file(path)
            if path.stat().st_size > MAX_BYTES:
                raise Refused("ArtifactSizeRefused")
            raw = path.read_bytes()
            artifacts[name] = _sha(raw)
            if name == "config":
                raw_config = raw
        _approved(_json(raw_sheet), artifacts)
        config = _json(raw_config)
        if config["uid"] != UID or config["bundle"] != BUNDLE.as_posix():
            raise Refused("FixedInputMismatch")
        _run_once(BUNDLE, OUTPUT, config, _load_key)
    except BaseException:
        # Fail closed without exception bodies, tracebacks, keys, plaintext, commands or paths.
        print('{"status":"Refused","retry":false}')
        return 2
    print('{"status":"Written","origin":"CliDeclared"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
