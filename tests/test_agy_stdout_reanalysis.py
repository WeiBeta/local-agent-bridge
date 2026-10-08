"""Synthetic stream vectors only. Never open the real UID or Windows key."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCRIPT = Path(__file__).resolve().parents[1] / "verification/agy_stdout_reanalysis.py"
spec = importlib.util.spec_from_file_location("agy_stdout_reanalysis", SCRIPT)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
KEY = bytes(range(32))
RECIPES = {
    "cwd_sha256": [helper._sha(b"synthetic-cwd")],
    "reproduce_command_sha256": [helper._sha(b"synthetic-reproduce")],
    "regression_command_sha256": [helper._sha(b"synthetic-regression")],
}


def event(state="DONE", index=4, command="synthetic-reproduce", **extra):
    payload = {
        "step_index": index,
        "state": state,
        "step_type": "tool",
        "tool_name": "run_command",
        "tool_info": {"name": "run_command", "parameters": {"CommandLine": command}},
    }
    payload.update(extra)
    return {"event": "step_update", "step_update": payload}


def stream(*steps, finish=True):
    events = [{"event": "init", "init": {"cwd": "synthetic-cwd", "tools": ["run_command"]}}]
    events.extend(steps)
    if finish:
        events.append({"event": "result", "result": {"status": "SUCCESS"}})
    return b"".join(helper._canonical(e) + b"\n" for e in events)


def validate(result):
    schema = json.loads(helper.SCHEMA.read_bytes())
    jsonschema.Draft202012Validator(schema).validate(result)
    return helper._canonical(result)


def test_native_transitions_group_by_step_and_never_claim_invocation_count():
    result = helper._analyze(stream(event("ACTIVE"), event("ACTIVE"), event()), RECIPES)
    validate(result)
    assert result["status"] == "Complete"
    assert result["event_categories"]["step_update"] == 3
    assert len(result["steps"]) == 1
    step = result["steps"][0]
    assert step["states"] == ["ACTIVE", "ACTIVE", "DONE"]
    assert step["command"] == {"reproduce": "Match", "regression": "Mismatch"}
    assert step["argv"] == step["cwd"] == result["shell"] == "Unknown"
    assert step["exit_code"] is result["actual_invocations"] is None
    assert result["init_cwd"] == "Match"


@pytest.mark.parametrize("where", ["root", "payload", "tool", "parameters", "error"])
def test_sensitive_unknown_fields_never_escape(where):
    secret = "SENSITIVE_ACCOUNT_SOURCE_PASSWORD_COMMAND_TEXT"
    item = event(command="SENSITIVE_COMMAND_NOT_RECIPE")
    targets = {
        "root": item,
        "payload": item["step_update"],
        "tool": item["step_update"]["tool_info"],
        "parameters": item["step_update"]["tool_info"]["parameters"],
        "error": item["step_update"]["tool_info"].setdefault("error", {}),
    }
    targets[where][secret] = {"message": secret, "output": secret, "text_delta": secret}
    result = helper._analyze(stream(item), RECIPES)
    raw = validate(result)
    assert secret.encode() not in raw and b"SENSITIVE_COMMAND_NOT_RECIPE" not in raw
    assert result["steps"][0]["command"]["reproduce"] == "Mismatch"


@pytest.mark.parametrize(
    "changes",
    [
        {"tool_name": "SENSITIVE_UNKNOWN_TOOL"},
        {"step_type": "SENSITIVE_UNKNOWN_TYPE"},
        {"state": "SENSITIVE_UNKNOWN_STATE"},
        {"step_index": "SENSITIVE_UNKNOWN_ID"},
    ],
)
def test_unknown_categories_are_never_copied(changes):
    result = helper._analyze(stream(event(**changes)), RECIPES)
    assert b"SENSITIVE" not in validate(result)


@pytest.mark.parametrize(
    "items",
    [
        [event(), event()],
        [event(), event("ACTIVE")],
        [event("ACTIVE"), event(command="conflicting-command")],
        [event("ACTIVE"), event(step_type="agent_response")],
        [event("ACTIVE", conversation_id="A"), event(conversation_id="B")],
    ],
)
def test_conflicting_events_keep_comparisons_unknown(items):
    result = helper._analyze(stream(*items), RECIPES)
    assert result["status"] == "Conflict"
    assert all(s["command"]["reproduce"] == "Unknown" for s in result["steps"])
    validate(result)


@pytest.mark.parametrize(
    "plain", [stream(event(), finish=False), stream(event())[:-1], stream(event("ACTIVE"))]
)
def test_truncated_or_unfinished_stream_is_incomplete(plain):
    result = helper._analyze(plain, RECIPES)
    assert result["status"] == "Incomplete"
    assert result["steps"][0]["command"]["reproduce"] == "Unknown"


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json\n",
        b'{"event":"init","event":"result"}\n',
        b'{"value":NaN}\n',
        b'{"unknown":' + b"[" * 18 + b"0" + b"]" * 18 + b"}\n",
        b'{"unknown":[' + b"0," * 129 + b"0]}\n",
        b"{}\n" * 1025,
        b'{"unknown":"' + b"s" * 65536 + b'"}\n',
        b"s" * 262145,
        b"[]\n",
        b"\xff\n",
        b'{"unknown":1e999}\n',
    ],
    ids=[
        "non-json",
        "duplicate-key",
        "nan",
        "deep",
        "wide",
        "many-lines",
        "long-line",
        "long-stream",
        "array",
        "non-utf8",
        "float-overflow",
    ],
)
def test_malformed_huge_or_hostile_events_refuse_without_value_output(raw):
    with pytest.raises(helper.Refused):
        helper._analyze(raw, RECIPES)


def synthetic_bundle(tmp_path, plaintext=None):
    plaintext = stream(event()) if plaintext is None else plaintext
    uid = "00000000-0000-4000-8000-000000000001"
    opening = {"schema_version": 2, "domain": "sessions", "session_id": uid}
    opening_raw = helper._canonical(opening)
    cipher = AESGCM(KEY)
    nonce = b"SYNTHFRAME01"
    # 12 byte deterministic nonces are ONLY synthetic test vectors.
    nonce = nonce.ljust(12, b"0")
    aad = f"LocalAgentBridge/session-frame/v2/sessions/{uid}/stdout/0".encode()
    encrypted = cipher.encrypt(nonce, plaintext, aad)
    framed = helper.MAGIC + helper.HEADER.pack(len(encrypted), 0, nonce) + encrypted

    def binding(raw):
        return {"bytes": len(raw), "sha256": helper._sha(raw)}

    manifest = {
        **opening,
        "state": "complete",
        "files": {"open.json": binding(opening_raw), "stdout.enc": binding(framed)},
        "streams": {"stdout": {**binding(plaintext), "frames": 1, "complete": True}},
    }
    nonce = b"SYNTHSEAL001"
    tag = cipher.encrypt(
        nonce, b"", b"LocalAgentBridge/session-seal/v2/sessions/" + helper._canonical(manifest)
    )
    seal_raw = helper._canonical(
        {
            "schema_version": 2,
            "manifest": manifest,
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
        }
    )
    raw = {"open.json": opening_raw, "seal.json": seal_raw, "stdout.enc": framed}
    config = {
        "uid": uid,
        "files": {name: binding(data) for name, data in raw.items()},
        "manifest_sha256": helper._sha(helper._canonical(manifest)),
        "plaintext": binding(plaintext),
        "recipes": RECIPES,
    }
    bundle = tmp_path / "synthetic-bundle"
    bundle.mkdir()
    for name, data in raw.items():
        (bundle / name).write_bytes(data)
    # The helper must neither enumerate nor open these deliberately invalid files.
    for name in ("task.enc", "request.enc", "stderr.enc"):
        (bundle / name).write_bytes(b"FORBIDDEN_SYNTHETIC_STREAM")
    return bundle, config, raw


@pytest.mark.parametrize("fault", ["none", "key", "seal_tag", "cipher_hash", "plain_hash", "parse"])
def test_exact_three_reads_one_key_one_auth_attempt_no_retry(tmp_path, monkeypatch, fault):
    bundle, config, raw = synthetic_bundle(tmp_path, b"not-json\n" if fault == "parse" else None)
    if fault == "cipher_hash":
        (bundle / "stdout.enc").write_bytes(raw["stdout.enc"][:-1] + b"X")
    elif fault == "seal_tag":
        seal = json.loads(raw["seal.json"])
        seal["tag"] = base64.b64encode(b"x" * 16).decode()
        new = helper._canonical(seal)
        (bundle / "seal.json").write_bytes(new)
        config["files"]["seal.json"] = {"bytes": len(new), "sha256": helper._sha(new)}
    elif fault == "plain_hash":
        config["plaintext"]["sha256"] = "0" * 64
    reads, keys, auth = [], [], []
    original_read, original_auth = helper._read_bound, helper._authenticate

    def read(path, binding):
        reads.append(path.name)
        return original_read(path, binding)

    def key():
        keys.append(1)
        if fault == "key":
            raise RuntimeError("SENSITIVE_KEY_ERROR")
        return KEY

    def authenticate(*args):
        auth.append(1)
        return original_auth(*args)

    monkeypatch.setattr(helper, "_read_bound", read)
    monkeypatch.setattr(helper, "_authenticate", authenticate)
    output = tmp_path / "once"
    if fault == "none":
        validate(helper._run_once(bundle, output, config, key))
        assert (output / "result.json").exists()
    else:
        with pytest.raises((helper.Refused, RuntimeError)):
            helper._run_once(bundle, output, config, key)
        assert not (output / "result.json").exists()
    assert reads == ["open.json", "seal.json", "stdout.enc"]
    assert len(keys) == (0 if fault == "cipher_hash" else 1)
    assert len(auth) == (0 if fault in {"cipher_hash", "key"} else 1)
    assert (output / "attempt.consumed.json").exists()
    before = (len(reads), len(keys), len(auth))
    with pytest.raises(FileExistsError):
        helper._run_once(bundle, output, config, key)
    assert before == (len(reads), len(keys), len(auth))
    assert set(p.name for p in output.iterdir()) <= {"attempt.consumed.json", "result.json"}


def test_future_config_is_closed_and_pinned_without_opening_real_input():
    config = json.loads(helper.CONFIG.read_bytes())
    assert config["uid"] == helper.UID and config["bundle"] == helper.BUNDLE.as_posix()
    assert set(config["files"]) == {"open.json", "seal.json", "stdout.enc"}
    assert config["files"]["stdout.enc"]["bytes"] == 48333
    assert config["plaintext"]["bytes"] == 48283


@pytest.mark.parametrize("fault", ["truncated", "sequence", "frame_tag", "frame_count"])
def test_authenticated_seal_does_not_hide_invalid_stdout_frames(tmp_path, fault):
    _, config, raw = synthetic_bundle(tmp_path)
    seal = json.loads(raw["seal.json"])
    framed = raw["stdout.enc"]
    if fault == "truncated":
        framed = framed[:-2]
    elif fault == "sequence":
        header = len(helper.MAGIC)
        length, _, nonce = helper.HEADER.unpack_from(framed, header)
        framed = (
            framed[:header]
            + helper.HEADER.pack(length, 9, nonce)
            + framed[header + helper.HEADER.size :]
        )
    elif fault == "frame_tag":
        framed = framed[:-1] + bytes([framed[-1] ^ 1])
    else:
        seal["manifest"]["streams"]["stdout"]["frames"] = 2
    raw["stdout.enc"] = framed
    binding = {"bytes": len(framed), "sha256": helper._sha(framed)}
    config["files"]["stdout.enc"] = binding
    seal["manifest"]["files"]["stdout.enc"] = binding
    config["manifest_sha256"] = helper._sha(helper._canonical(seal["manifest"]))
    nonce = base64.b64decode(seal["nonce"])
    tag = AESGCM(KEY).encrypt(
        nonce,
        b"",
        b"LocalAgentBridge/session-seal/v2/sessions/" + helper._canonical(seal["manifest"]),
    )
    seal["tag"] = base64.b64encode(tag).decode()
    raw["seal.json"] = helper._canonical(seal)
    with pytest.raises(helper.Refused):
        helper._authenticate(raw, KEY, config)


@pytest.mark.parametrize("code", [0, 1, True, "SENSITIVE", 2147483648])
def test_optional_exit_is_numeric_cli_declaration_only(code):
    item = event()
    item["step_update"]["tool_info"]["exit_code"] = code
    result = helper._analyze(stream(item), RECIPES)
    assert result["steps"][0]["exit_code"] == (
        code if type(code) is int and code < 2147483648 else None
    )
    assert b"SENSITIVE" not in validate(result)


def test_cli_refusal_has_no_sensitive_exception_or_retry(tmp_path, monkeypatch, capsys):
    approval = tmp_path / "synthetic-approval.json"
    approval.write_bytes(b'{"SENSITIVE":"SENSITIVE"}')
    called = []
    monkeypatch.setattr(helper, "_load_key", lambda: called.append(1))
    assert helper.main(["--approval", str(approval), "--expected-approval-sha256", "0" * 64]) == 2
    assert called == []
    assert capsys.readouterr().out == '{"status":"Refused","retry":false}\n'


@pytest.mark.parametrize(
    "field,value",
    [
        ("review", "Unrun"),
        ("author_confirmed", False),
        ("uid", "other"),
        ("max_key_reads", True),
        ("max_key_reads", 2),
        ("max_stdout_authentications", 2),
        ("artifacts", {}),
        ("grant_ref", ""),
        ("unknown", "SENSITIVE"),
    ],
)
def test_unapproved_or_changed_artifacts_refuse(field, value):
    artifacts = {"code": "1" * 64, "config": "2" * 64, "schema": "3" * 64}
    sheet = {
        "task_id": helper.TASK_ID,
        "uid": helper.UID,
        "author_confirmed": True,
        "review": "Passed",
        "artifacts": artifacts,
        "max_key_reads": 1,
        "max_stdout_authentications": 1,
        "grant_ref": "synthetic-grant",
    }
    helper._approved(sheet, artifacts)
    sheet[field] = value
    with pytest.raises(helper.Refused):
        helper._approved(sheet, artifacts)
