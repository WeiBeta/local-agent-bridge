"""Opt-in stable agy entry and two bounded, prompt-free host observations.

Disk identity and help declarations are observations, not vendor authentication
or proof of loaded image, parameter semantics, provider identity or cost.
"""

from __future__ import annotations

import hashlib
import re
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import contract, slice_run, task_input, winjob

OBSERVATION_REF = "agy-host-observation.json"
OBSERVATION_LIMIT = 16 * 1024
REQUIRED_FLAGS = (
    "--project",
    "--print",
    "--model",
    "--effort",
    "--output-format",
    "--disable-slash-commands",
    "--print-timeout",
)
_CLEANUP_KEYS = {"child_exit_observed", "pipes_closed", "job_closed"}
_REASONS = {
    "VersionProbeFailed",
    "HelpProbeFailed",
    "ProbeTimedOut",
    "ProbeOutputTruncated",
    "RequiredParametersMissing",
    "DiagnosticCleanupUnverified",
    "HostSourceUnavailable",
    "ProbeInterrupted",
    "DeadlineExceeded",
}
_VERSION = r"[0-9]+(?:\.[0-9]+){1,3}"


class AgyHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require(condition: object) -> None:
    if not condition:
        raise AgyHostError("AgyHostObservationInvalid")


def validate_entry(value: object) -> tuple[Path, Path]:
    _require(type(value) is dict and set(value) == {"path", "install_root", "identity_mode"})
    _require(value["identity_mode"] == "StableInstalledEntry")
    entry = task_input._validate_absolute_path(value["path"], label="agy entry")
    root = task_input._validate_absolute_path(value["install_root"], label="agy installation")
    task_input._reject_broad_root(root, "agy installation")
    _require(entry == root / "agy.exe")
    return entry, root


def checked_entry(value: dict) -> Path:
    entry, root = validate_entry(value)
    task_input._assert_plain_target(root, label="agy installation")
    task_input._assert_plain_target(entry, label="agy entry")
    info = entry.lstat()
    _require(root.is_dir() and stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    return entry


class _RamOutput:
    """Two stream sinks share a byte budget; no session store or key is used."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.kept = 0
        self.incomplete_reason = None
        self.lock = threading.Lock()


class _RamStream:
    def __init__(self, writer: _RamOutput) -> None:
        self.writer = writer
        self.raw = bytearray()

    def append(self, chunk: bytes) -> bool:
        with self.writer.lock:
            if len(chunk) > self.writer.limit - self.writer.kept:
                self.writer.incomplete_reason = "ProbeOutputTruncated"
                return False
            self.raw.extend(chunk)
            self.writer.kept += len(chunk)
            return True

    def stat(self) -> SimpleNamespace:
        return SimpleNamespace(st_size=len(self.raw))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


def _declared_choice_tokens(description: str) -> list[str] | None:
    """Read the first explicit enum without treating its trailing prose as values."""
    marker = re.search(r"\b(?:choices|options|values)[ \t]*:[ \t]*", description, re.I)
    if marker is None:
        return None
    # Only a complete enclosing pair permits continuation lines. Searching for
    # a closing parenthesis alone would consume a later explanatory note.
    enclosing = next(
        (
            pair
            for pair in re.finditer(r"\([^()]*\)", description)
            if pair.start() < marker.start() < pair.end()
        ),
        None,
    )
    if enclosing is not None:
        values = description[marker.end() : enclosing.end() - 1]
    else:
        values = re.split(r"[\r\n]", description[marker.end() :], maxsplit=1)[0]
    # Values form a comma/pipe-separated list, optionally quoted. Stop before
    # prose, parentheses or other metadata instead of scanning all their words.
    value = r"(?:\"[A-Za-z][A-Za-z0-9_-]*\"|'[A-Za-z][A-Za-z0-9_-]*'|[A-Za-z][A-Za-z0-9_-]*)"
    enum = re.match(rf"\s*{value}(?:\s*[,|]\s*{value})*", values)
    return re.findall(r"[A-Za-z][A-Za-z0-9_-]*", enum.group()) if enum else []


def missing_flags(raw: bytes) -> list[str]:
    """Project option declarations, allowing aliases, wrapping and extra options."""
    text = raw.decode("utf-8", "replace")
    # A long option must occur in an option declaration, not prose mentioning it.
    declarations = {}
    starts = list(re.finditer(r"(?m)^\s*(?:(?:-\w|--[\w-]+)\s*,\s*)?(--[\w-]+)\b", text))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        declaration = text[match.end() : end].lstrip()
        declarations[match.group(1)] = declaration
    missing = []
    for flag in REQUIRED_FLAGS:
        declaration = declarations.get(flag)
        if declaration is None:
            missing.append(flag)
            continue
        if flag == "--disable-slash-commands":
            continue
        # A declaration may list further aliases before the shared parameter form.
        body = re.sub(r"^(?:\s*,\s*(?:-\w|--[\w-]+))+\s*", "", declaration)
        argument = re.match(r"(?:=\s*)?(<[^>\r\n]+>|\[[^\]\r\n]+\])", body)
        if argument is None:
            missing.append(flag)
            continue
        required_value = {"--effort": "high", "--output-format": "stream-json"}.get(flag)
        choices = _declared_choice_tokens(body[argument.end() :])
        enum = argument.group(1)[1:-1]
        if choices is not None or "|" in enum:
            tokens = choices if choices is not None else re.findall(r"[A-Za-z][A-Za-z0-9_-]*", enum)
            if required_value is not None and required_value not in tokens:
                missing.append(flag)
    return missing


def new_observation(task_id: str, plan_sha256: str) -> dict:
    return {
        "contract_version": 1,
        "kind": "AgyHostObservation",
        "task_id": task_id,
        "plan_sha256": plan_sha256,
        "entry": None,
        "reported_version": None,
        "diagnostics": [],
        "compatibility": {"state": "NotChecked", "missing_required_flags": [], "reason": None},
    }


def diagnostics_complete(observation: dict) -> bool:
    return all(
        item["launch_count"] is not None
        and all(value is True for value in item["cleanup"].values())
        for item in observation["diagnostics"]
    )


def observe(entry_spec: dict, cwd: Path, deadline: float, observation: dict) -> None:
    compatibility = observation["compatibility"]
    compatibility["state"] = "Unverified"
    try:
        entry = checked_entry(entry_spec)
        observation["entry"] = {"path": entry_spec["path"], "sha256": slice_run._sha256_file(entry)}
    except (OSError, task_input.TaskInputError, AgyHostError):
        compatibility["reason"] = "HostSourceUnavailable"
        return
    for name, flag, limit in (("Version", "--version", 8192), ("Help", "--help", 262144)):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            compatibility["reason"] = "DeadlineExceeded"
            return
        lifecycle = winjob.LaunchLifecycle()
        output = _RamOutput(limit)
        stdout, stderr = _RamStream(output), _RamStream(output)
        item = {
            "name": name,
            "launch_count": 0,
            "pid": None,
            "pid_created_filetime": None,
            "exit_code": None,
            "timed_out": None,
            "output_truncated": False,
            "cleanup": dict.fromkeys(sorted(_CLEANUP_KEYS)),
        }
        observation["diagnostics"].append(item)  # reserve before entering launcher
        launch = {}
        try:
            launch = slice_run._launch_and_capture(
                str(entry),
                [str(entry), flag],
                str(cwd),
                stdout,
                stderr,
                timeout_seconds=min(10.0, remaining),
                lifecycle=lifecycle,
                env=slice_run._agy_child_environment(),
            )
        except BaseException as error:
            compatibility["reason"] = (
                "ProbeInterrupted" if not isinstance(error, Exception) else name + "ProbeFailed"
            )
            if not isinstance(error, Exception):
                raise
            return
        finally:
            record = lifecycle.record()
            item.update(
                launch_count=lifecycle.launch_count,
                pid=lifecycle.pid,
                pid_created_filetime=lifecycle.pid_created_filetime,
                exit_code=launch.get("exit_code"),
                timed_out=launch.get("timed_out"),
                output_truncated=output.incomplete_reason is not None,
                cleanup={key: record["cleanup"][key] for key in sorted(_CLEANUP_KEYS)},
            )
        if not diagnostics_complete(observation):
            compatibility["reason"] = "DiagnosticCleanupUnverified"
            return
        if item["timed_out"]:
            compatibility["reason"] = "ProbeTimedOut"
            return
        if item["output_truncated"]:
            compatibility["reason"] = "ProbeOutputTruncated"
            return
        if (
            item["launch_count"] != 1
            or item["exit_code"] != 0
            or launch.get("capture_state") != "complete"
        ):
            compatibility["reason"] = name + "ProbeFailed"
            return
        if name == "Version":
            versions = re.findall(
                rf"(?<![\w.])v?({_VERSION})(?![\w.])",
                stdout.raw.decode("utf-8", "replace"),
                re.I,
            )
            if len(versions) != 1 or len(versions[0]) > 128:
                compatibility["reason"] = "VersionProbeFailed"
                return
            observation["reported_version"] = versions[0]
        else:
            missing = missing_flags(bytes(stdout.raw))
            if missing:
                compatibility.update(
                    state="Unsupported",
                    missing_required_flags=missing,
                    reason="RequiredParametersMissing",
                )
                return
    compatibility.update(state="Supported", reason=None)


def validate_observation(value: object, task_id: str, plan_sha: str, entry_path: str) -> dict:
    _require(
        type(value) is dict
        and set(value)
        == {
            "contract_version",
            "kind",
            "task_id",
            "plan_sha256",
            "entry",
            "reported_version",
            "diagnostics",
            "compatibility",
        }
    )
    _require(type(value["contract_version"]) is int and value["contract_version"] == 1)
    _require(
        value["kind"] == "AgyHostObservation"
        and value["task_id"] == task_id
        and value["plan_sha256"] == plan_sha
    )
    entry = value["entry"]
    _require(
        entry is None
        or (
            type(entry) is dict
            and set(entry) == {"path", "sha256"}
            and entry["path"] == entry_path
            and type(entry["sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None
        )
    )
    version = value["reported_version"]
    _require(
        version is None
        or (
            type(version) is str
            and len(version) <= 128
            and re.fullmatch(_VERSION, version) is not None
        )
    )
    diagnostics = value["diagnostics"]
    _require(type(diagnostics) is list and len(diagnostics) <= 2)
    for index, item in enumerate(diagnostics):
        _require(
            type(item) is dict
            and set(item)
            == {
                "name",
                "launch_count",
                "pid",
                "pid_created_filetime",
                "exit_code",
                "timed_out",
                "output_truncated",
                "cleanup",
            }
        )
        _require(item["name"] == ("Version", "Help")[index])
        count = item["launch_count"]
        _require(count is None or (type(count) is int and count in {0, 1}))
        for key in ("pid", "pid_created_filetime", "exit_code"):
            _require(item[key] is None or type(item[key]) is int)
        _require(item["pid"] is None or item["pid"] > 0)
        _require(item["pid_created_filetime"] is None or item["pid_created_filetime"] > 0)
        _require(item["timed_out"] is None or type(item["timed_out"]) is bool)
        _require(type(item["output_truncated"]) is bool)
        cleanup = item["cleanup"]
        _require(type(cleanup) is dict and set(cleanup) == _CLEANUP_KEYS)
        _require(all(flag is None or type(flag) is bool for flag in cleanup.values()))
    compatibility = value["compatibility"]
    _require(
        type(compatibility) is dict
        and set(compatibility) == {"state", "missing_required_flags", "reason"}
    )
    _require(
        type(compatibility["state"]) is str
        and compatibility["state"] in {"Supported", "Unsupported", "Unverified", "NotChecked"}
    )
    missing = compatibility["missing_required_flags"]
    _require(
        type(missing) is list and missing == [flag for flag in REQUIRED_FLAGS if flag in missing]
    )
    _require(
        compatibility["reason"] is None
        or (type(compatibility["reason"]) is str and compatibility["reason"] in _REASONS)
    )
    if compatibility["state"] == "Supported":
        _require(
            entry is not None
            and version is not None
            and not missing
            and compatibility["reason"] is None
            and len(diagnostics) == 2
            and diagnostics_complete(value)
        )
        _require(
            all(
                item["launch_count"] == 1
                and item["exit_code"] == 0
                and item["timed_out"] is False
                and item["output_truncated"] is False
                for item in diagnostics
            )
        )
    return value


def read_observation(run: dict, run_root: Path, entry_path: str) -> dict | None:
    refs = [item for item in run["evidence_refs"] if item["ref"] == OBSERVATION_REF]
    if not refs and run["transport_state"] == "NotRun":
        return None
    _require(len(refs) == 1 and refs[0]["origin"] == "HostObserved")
    path = run_root / OBSERVATION_REF
    task_input._assert_plain_target(path, label="agy observation")
    info = path.lstat()
    _require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= OBSERVATION_LIMIT
    )
    with path.open("rb") as stream:
        raw = stream.read(OBSERVATION_LIMIT + 1)
    _require(len(raw) <= OBSERVATION_LIMIT and hashlib.sha256(raw).hexdigest() == refs[0]["sha256"])
    value = contract.decode_strict_json_bytes(raw, label="agy observation")
    _require(raw == task_input._canonical_json_bytes(value))
    observation = validate_observation(value, run["task_id"], run["plan_sha256"], entry_path)
    if run["transport_state"] == "NotRun":
        _require(not observation["diagnostics"])
    if run["launch_count"] != 0:
        _require(observation["compatibility"]["state"] == "Supported")
    return observation
