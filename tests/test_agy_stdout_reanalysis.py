"""Synthetic stream vectors only. Never open the real UID or Windows key."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
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


# Each process starts without helper/cffi/Windows imports. Its observer and native
# guard precede those imports; replacing CredRead happens as its real loader exits.
COLD_KEY_PROBE = r"""
import base64
import builtins
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys

script, fixture, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
assert not any(name in sys.modules for name in ("keyring", "win32ctypes", "cffi"))
counts = {"config_reads": 0, "discovery": 0, "native_calls": 0, "audit_reads": 0}
queries = []
allowed = [script.parent.parent, Path(sys.prefix), Path(sys.base_prefix), fixture,
           Path(os.environ["SystemRoot"])]

def observe(path):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(path)).absolute()
    if path.name.casefold() == "keyringrc.cfg":
        counts["config_reads"] += 1
        raise AssertionError("SyntheticConfigurationReadDenied")
    if not any(path.is_relative_to(root) for root in allowed):
        raise AssertionError("OutsidePublicSoftwareOrFixtureDenied")

original_builtin, original_io, original_path = builtins.open, io.open, Path.open
def builtin_open(path, *args, **kwargs):
    observe(path)
    return original_builtin(path, *args, **kwargs)
def io_open(path, *args, **kwargs):
    observe(path)
    return original_io(path, *args, **kwargs)
def path_open(path, *args, **kwargs):
    observe(path)
    return original_path(path, *args, **kwargs)
def audit(event, args):
    if event == "open":
        counts["audit_reads"] += 1
        observe(args[0])
sys.addaudithook(audit)
builtins.open, io.open, Path.open = builtin_open, io_open, path_open

# Calibration would fail with counterexample01's Path.open-only observer.
configuration = fixture / "keyringrc.cfg"
for opener in (builtins.open, io.open, Path.open):
    try:
        opener(configuration, "rb")
    except AssertionError as error:
        assert str(error) == "SyntheticConfigurationReadDenied"
    else:
        raise AssertionError("ObserverMissedActualOpen")
try:
    original_builtin(configuration, "rb")  # bypass wrappers; audit must still see it
except AssertionError as error:
    assert str(error) == "SyntheticConfigurationReadDenied"
else:
    raise AssertionError("ObserverMissedBuiltinAudit")
calibration = counts["config_reads"]
assert calibration == 4
counts["config_reads"] = counts["audit_reads"] = 0

def native_denied(*args, **kwargs):
    counts["native_calls"] += 1
    raise AssertionError("NativeCredentialCallDenied")

class ProtectedLibrary:
    def __init__(self, library):
        self.library = library
    def __getattr__(self, name):
        if name.startswith("Cred"):
            return native_denied
        return getattr(self.library, name)

def fake_read(*args, **kwargs):
    queries.append((args, kwargs))
    if mode == "missing":
        raise OSError(1168, "SENSITIVE_MISSING_CREDENTIAL")
    if mode == "exception":
        raise RuntimeError("SENSITIVE_KEY_ERROR synthetic-full-command --password secret")
    encoded = base64.urlsafe_b64encode(bytes(range(32))).decode()
    credential = {"UserName": "aes256gcm-session-v1",
                  "CredentialBlob": encoded.encode("utf-16-le")}
    if mode == "account":
        credential["UserName"] = "SENSITIVE_OTHER_ACCOUNT"
    elif mode == "not-dict":
        return None
    elif mode == "blob-type":
        credential["CredentialBlob"] = "SENSITIVE_BLOB"
    elif mode == "blob-size":
        credential["CredentialBlob"] = b"short"
    elif mode == "utf16":
        credential["CredentialBlob"] = b"\x00\xd8" * 44
    elif mode == "base64":
        credential["CredentialBlob"] = ("!" * 44).encode("utf-16-le")
    elif mode == "key-size":
        encoded = base64.urlsafe_b64encode(bytes(range(31))).decode()
        credential["CredentialBlob"] = encoded.encode("utf-16-le")
    return credential

class GuardedLoader:
    def __init__(self, delegate, name):
        self.delegate, self.name = delegate, name
    def create_module(self, spec):
        return self.delegate.create_module(spec)
    def exec_module(self, module):
        self.delegate.exec_module(module)
        if self.name == "cffi":
            original_dlopen = module.FFI.dlopen
            def guarded_dlopen(ffi, name, *args, **kwargs):
                library = original_dlopen(ffi, name, *args, **kwargs)
                if str(name).casefold() == "advapi32.dll":
                    return ProtectedLibrary(library)
                return library
            module.FFI.dlopen = guarded_dlopen
        elif self.name == "win32ctypes.core" and mode == "wrong-transport":
            module._backend = "ctypes"
        elif self.name == "win32ctypes.pywin32.win32cred":
            module.CredRead = fake_read
            for name in ("CredWrite", "CredDelete", "CredEnumerate"):
                if hasattr(module, name):
                    setattr(module, name, native_denied)

class GuardedFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "keyring" or fullname.startswith("keyring."):
            counts["discovery"] += 1
            raise AssertionError("DefaultKeyringDiscoveryDenied")
        if fullname in {"win32cred", "pywintypes", "win32api"}:
            raise AssertionError("Pywin32FallbackDenied")
        if (fullname == "cffi" and mode == "no-cffi") or (
            fullname == "win32ctypes.pywin32" and mode == "import-failure"
        ):
            raise ImportError("SyntheticFixedBackendUnavailable")
        if fullname in {"cffi", "win32ctypes.core", "win32ctypes.pywin32.win32cred"}:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            assert spec is not None
            spec.loader = GuardedLoader(spec.loader, fullname)
            return spec

def profile(frame, event, argument):
    if event == "call":
        module = frame.f_globals.get("__name__", "")
        if module.startswith("win32ctypes") and frame.f_code.co_name.casefold() in {
            "credread", "credwrite", "creddelete", "credenumerate", "_credread",
            "_credwrite", "_creddelete", "_credenumerate", "_credfree", "credential2dict"
        }:
            native_denied()
sys.meta_path.insert(0, GuardedFinder())
sys.setprofile(profile)
spec = importlib.util.spec_from_file_location("cold_helper", script)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
assert queries == [] and counts["native_calls"] == 0
failed = False
try:
    key = helper._load_key()
except (helper.Refused, ImportError, OSError, RuntimeError):
    failed = True
finally:
    sys.setprofile(None)
assert failed == (mode != "success")
expected = 0 if mode in {"no-cffi", "import-failure", "wrong-transport"} else 1
assert len(queries) == expected
for args, kwargs in queries:
    assert args == ()
    assert kwargs == {"TargetName": "LocalAgentBridge.SessionCapture.v1", "Type": 1, "Flags": 0}
assert counts["config_reads"] == counts["discovery"] == counts["native_calls"] == 0
assert counts["audit_reads"] > 0
if not failed:
    assert key == bytes(range(32))
print(json.dumps({**counts, "query_count": len(queries), "calibration": calibration,
                  "failed": failed, "key_bytes": 0 if failed else len(key)}))
"""


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "missing",
        "exception",
        "account",
        "not-dict",
        "blob-type",
        "blob-size",
        "utf16",
        "base64",
        "key-size",
        "no-cffi",
        "import-failure",
        "wrong-transport",
    ],
)
def test_cold_fixed_backend_has_no_discovery_config_or_second_query(tmp_path, mode):
    fixture = tmp_path / "synthetic-account-config"
    fixture.mkdir()
    (fixture / "keyringrc.cfg").write_text("[fixture-only]\nvalue=synthetic\n", encoding="utf-8")
    env = dict(os.environ)
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        env[name] = str(fixture)
    env.update(
        PYTHON_KEYRING_BACKEND="synthetic.unapproved.Backend",
        KEYRING_PROPERTY_SERVICE="SENSITIVE_SERVICE_OVERRIDE",
        KEYRING_PROPERTY_KEYRING="SENSITIVE_BACKEND_OVERRIDE",
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", COLD_KEY_PROBE, str(SCRIPT), str(fixture), mode],
        cwd=fixture,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert "SENSITIVE" not in completed.stdout and "synthetic-full-command" not in completed.stdout
    facts = json.loads(completed.stdout)
    assert facts["calibration"] == 4
    assert facts["config_reads"] == facts["discovery"] == facts["native_calls"] == 0
    assert facts["query_count"] == (
        0 if mode in {"no-cffi", "import-failure", "wrong-transport"} else 1
    )
    assert facts["key_bytes"] == (32 if mode == "success" else 0)


def test_native_key_failure_consumes_marker_and_cli_sanitizes(tmp_path, monkeypatch, capsys):
    from win32ctypes.pywin32 import win32cred

    bundle, config, _ = synthetic_bundle(tmp_path)
    config["bundle"] = bundle.as_posix()
    configuration = tmp_path / "synthetic-config.json"
    configuration.write_bytes(helper._canonical(config))
    schema = tmp_path / "synthetic-schema.json"
    schema.write_bytes(b"{}")
    output = tmp_path / "synthetic-once"
    for name, value in (
        ("UID", config["uid"]),
        ("BUNDLE", bundle),
        ("OUTPUT", output),
        ("CONFIG", configuration),
        ("SCHEMA", schema),
    ):
        monkeypatch.setattr(helper, name, value)
    queries, auth = [], []

    def fail_read(*args, **kwargs):
        queries.append((args, kwargs))
        raise RuntimeError("SENSITIVE_KEY_ERROR synthetic-full-command --password secret")

    monkeypatch.setattr(win32cred, "CredRead", fail_read)
    monkeypatch.setattr(helper, "_authenticate", lambda *args: auth.append(1))
    artifacts = {
        name: helper._sha(path.read_bytes())
        for name, path in (("code", SCRIPT), ("config", configuration), ("schema", schema))
    }
    sheet = {
        "task_id": helper.TASK_ID,
        "uid": config["uid"],
        "author_confirmed": True,
        "review": "Passed",
        "artifacts": artifacts,
        "max_key_reads": 1,
        "max_stdout_authentications": 1,
        "grant_ref": "synthetic-test-only-not-a-real-grant",
    }
    approval = tmp_path / "synthetic-approval.json"
    approval.write_bytes(helper._canonical(sheet))
    argv = [
        "--approval",
        str(approval),
        "--expected-approval-sha256",
        helper._sha(approval.read_bytes()),
    ]
    assert helper.main(argv) == 2
    assert queries == [
        ((), {"TargetName": "LocalAgentBridge.SessionCapture.v1", "Type": 1, "Flags": 0})
    ]
    assert auth == []
    assert set(path.name for path in output.iterdir()) == {"attempt.consumed.json"}
    assert helper.main(argv) == 2
    assert len(queries) == 1 and auth == []
    assert capsys.readouterr().out == '{"status":"Refused","retry":false}\n' * 2
