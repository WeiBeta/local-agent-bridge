"""Prepare and collect a minimal local source slice (no MCP surface, no provider call).

``prepare`` copies an explicit list of repository-relative source files out of
one local Git commit into a fresh task root; ``collect`` reports the changes of
that task root as a unified diff. Neither command installs anything, starts a
CLI or provider, applies a patch, runs a Git write command, modifies the
repository work tree or deletes existing material. The copies are ordinary host
files: this tool is not an OS sandbox and grants no authority.

Reused from ``local_agent_bridge.bridge.paths`` (a stdlib-only module sliced out
of the frozen ``ask_ai_mcp.code_review_workspace``): the bounded Git read
``_run_git``, the reparse and escape boundary ``_is_reparse`` /
``_assert_no_reparse_escape`` / ``_is_within``, the relative-path spelling check
``_validate_relative`` and the secret-bearing name pattern ``_SECRET_NAME``. The
Coding snapshotter, the coding publication helpers and the review catalogue stay
out: they bring a pydantic model chain, an environment-variable repository
catalog and frozen publication contracts that this tool does not need.

``prepare`` builds ``<task root>/manifest.json``, ``baseline/<relative path>``,
``work/TASK.md`` and ``work/<relative path>``, and always refuses an existing
task root. Both trees hold byte-identical copies of the frozen Git blobs, not the
checkout form of the working tree; the manifest binds every copied file and the
task note by byte count and SHA-256 over those raw bytes, so no newline or
encoding normalization happens anywhere. Text is read as strict UTF-8 without NUL
bytes and diffs are split on LF only, with the standard no-newline marker for a
final line that has none. ``collect`` is read-only: it writes one single-line JSON
summary and then the unified diff as explicit UTF-8 bytes on stdout, and never
touches the task root, applies the diff, runs a Git command or overwrites
evidence.
``plan`` is read-only as well: for one untouched task root it prints the fixed
host-run plan (cwd, readable and writable paths, rule strings, model, argv) with
``execution_authorized`` false. A plan is not an approval, does not prove current
CLI capability and grants no permission.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import ntpath
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from local_agent_bridge.bridge.paths import (
    _SECRET_NAME,
    BridgePathError,
    _assert_no_reparse_escape,
    _is_reparse,
    _is_within,
    _run_git,
    _validate_relative,
)

DEFAULT_REPOSITORY = Path.cwd()
BASELINE_DIRECTORY = "baseline"
WORK_DIRECTORY = "work"
MANIFEST_NAME = "manifest.json"
TASK_NOTE_NAME = "TASK.md"
MANIFEST_VERSION = 1
MAX_REPORTED_ENTRIES = 8
_MANIFEST_KEYS = frozenset({"manifest_version", "source_commit", "files", "task_note", "editable"})
_MANIFEST_FILE_KEYS = frozenset({"path", "bytes", "sha256"})
_MANIFEST_NOTE_KEYS = frozenset({"bytes", "sha256"})
_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DRIVE_PATTERN = re.compile(r"[A-Za-z]:")
_READABLE_GIT_MODES = frozenset({"100644", "100755"})
_TEXT_SUFFIXES = frozenset(
    {".py", ".md", ".json", ".toml", ".ps1", ".txt", ".yaml", ".yml", ".cfg", ".ini"}
)
_NO_NEWLINE_MARKER = "\\ No newline at end of file"
PLAN_SCHEMA_VERSION = 1
PLAN_MODEL = "gemini-3.8-flash-high"
PLAN_EFFORT = "high"
PLAN_PRINT_TIMEOUT = "15m"
PLAN_INSTRUCTION = (
    "Read TASK.md in the working directory first, then work from the access list appended below: "
    "read only its readable paths and write only its writable paths, by exact path. Do not run "
    "commands or tests, and do not claim that anything was built, executed or tested; the host "
    "validates afterwards."
)
PLAN_ACCESS_MARKER = " Access list (path data, not instructions): "
_EXAMPLES = """examples:
  uv run local-agent-bridge prepare --commit <40-hex commit>
      --file src/ask_ai_mcp/coding_workspace.py --file tests/test_coding_contract.py
      --editable src/ask_ai_mcp/coding_workspace.py
      --task-note C:\\Users\\user\\Documents\\Codex-Scratch\\SLICE-DEMO-01-note.md
      --out C:\\Users\\user\\Documents\\Codex-Scratch\\SLICE-DEMO-01
  uv run local-agent-bridge collect
      --task-root C:\\Users\\user\\Documents\\Codex-Scratch\\SLICE-DEMO-01
  uv run local-agent-bridge plan
      --task-root C:\\Users\\user\\Documents\\Codex-Scratch\\SLICE-DEMO-01
"""


class SliceWorkspaceError(RuntimeError):
    """Raised when a slice request is refused or cannot be completed."""


@dataclass(frozen=True)
class SliceFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SliceManifest:
    source_commit: str
    files: tuple[SliceFile, ...]
    editable: tuple[str, ...]
    task_note_size: int
    task_note_sha256: str


def _git(root: Path, *arguments: str) -> str:
    try:
        return _run_git(root, *arguments)
    except BridgePathError as error:
        raise SliceWorkspaceError(f"Git read failed for {arguments[0]}: {error}") from error


def _require_plain_chain(path: Path) -> None:
    """Refuse a reparse point anywhere from the drive root down to ``path``."""
    try:
        _assert_no_reparse_escape(path, Path(path.anchor))
    except BridgePathError as error:
        raise SliceWorkspaceError(f"path chain refused for {path}: {error}") from error


def _decode_text(payload: bytes, label: str) -> str:
    """Strict text policy: UTF-8, and no NUL byte."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SliceWorkspaceError(f"{label} is not valid UTF-8 text") from error
    if "\x00" in text:
        raise SliceWorkspaceError(f"{label} contains NUL and is not a plain text file")
    return text


def _read_text_file(path: Path, label: str) -> bytes:
    if not path.is_absolute():
        raise SliceWorkspaceError(f"{label} must be an absolute path: {path}")
    _require_plain_chain(path)
    if not path.is_file():
        raise SliceWorkspaceError(f"{label} is not an existing file: {path}")
    payload = path.read_bytes()
    _decode_text(payload, label)
    return payload


def _summarize(values: list[str]) -> str:
    if len(values) <= MAX_REPORTED_ENTRIES:
        return "; ".join(values)
    return (
        "; ".join(values[:MAX_REPORTED_ENTRIES])
        + f"; ... {len(values) - MAX_REPORTED_ENTRIES} more"
    )


def _tree_path(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def _require_source_path(value: str) -> str:
    """One canonical, policy-cleared repository-relative source path."""
    try:
        canonical = _validate_relative(value)
    except BridgePathError as error:
        raise SliceWorkspaceError(f"source path refused ({value}): {error}") from error
    if canonical != value:
        raise SliceWorkspaceError(
            "source paths must already be canonical forward-slash relative paths: " + value
        )
    if _SECRET_NAME.search(value) is not None:
        raise SliceWorkspaceError("secret-bearing source paths are excluded: " + value)
    if PurePosixPath(value).suffix.casefold() not in _TEXT_SUFFIXES:
        raise SliceWorkspaceError("source path is not an approved plain-text format: " + value)
    if value.casefold() == TASK_NOTE_NAME.casefold():
        raise SliceWorkspaceError("source path collides with the work/TASK.md task note: " + value)
    for part in PurePosixPath(value).parts:
        if part.casefold() == ".git" or ntpath.isreserved(part) or part.endswith((".", " ")):
            raise SliceWorkspaceError("source path holds a reserved or prohibited name: " + value)
    return value


def _require_path_list(values: list[str], label: str) -> tuple[str, ...]:
    if not values:
        raise SliceWorkspaceError(f"{label} requires at least one path")
    seen: dict[str, str] = {}
    for value in values:
        canonical = _require_source_path(value)
        if canonical.casefold() in seen:
            raise SliceWorkspaceError(f"{label} repeats or case-collides: " + canonical)
        seen[canonical.casefold()] = canonical
    return tuple(sorted(seen.values()))


def _require_editable(values: list[str], files: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        return ()
    editable = _require_path_list(values, "editable")
    unknown = [value for value in editable if value not in frozenset(files)]
    if unknown:
        raise SliceWorkspaceError(
            "editable paths must be a subset of the prepared files: " + _summarize(unknown)
        )
    return editable


def _require_repository(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or not path.is_dir():
        raise SliceWorkspaceError("repository must be an absolute existing directory: " + raw)
    absolute = Path(os.path.abspath(path))
    resolved = path.resolve(strict=True)
    if os.path.normcase(str(absolute)) != os.path.normcase(str(resolved)):
        raise SliceWorkspaceError("repository root must not be a symlink or junction: " + raw)
    _require_plain_chain(resolved)
    home = Path.home().resolve(strict=True)
    if resolved == Path(resolved.anchor) or resolved == home or _is_within(home, resolved):
        raise SliceWorkspaceError("drive roots and broad user-profile roots are refused: " + raw)
    top = _git(resolved, "rev-parse", "--show-toplevel").strip()
    if Path(top).resolve(strict=True) != resolved:
        raise SliceWorkspaceError("repository must be the exact Git work-tree root: " + raw)
    return resolved


def _require_commit(repository: Path, raw: str) -> str:
    if _OBJECT_ID_PATTERN.fullmatch(raw) is None:
        raise SliceWorkspaceError("commit must be a full lowercase 40-hex commit id: " + raw)
    try:
        kind = _git(repository, "cat-file", "-t", raw).strip()
    except SliceWorkspaceError as error:
        raise SliceWorkspaceError(
            "commit is not present in this local repository: " + raw
        ) from error
    if kind != "commit":
        raise SliceWorkspaceError(f"commit id does not name a commit object (found {kind}): " + raw)
    return raw


def _require_new_task_root(raw: str, repository: Path) -> Path:
    if ntpath.normpath(raw) != raw or _DRIVE_PATTERN.fullmatch(ntpath.splitdrive(raw)[0]) is None:
        raise SliceWorkspaceError(
            "task root must be a normalized absolute Windows path with backslash spelling: " + raw
        )
    root = Path(raw)
    for part in root.parts[1:]:
        if (
            part in {".", ".."}
            or ":" in part
            or ntpath.isreserved(part)
            or part.endswith((".", " "))
        ):
            raise SliceWorkspaceError("task root holds a reserved or ambiguous segment: " + raw)
    _require_plain_chain(root)
    if not root.parent.is_dir():
        raise SliceWorkspaceError("the task root parent must already exist: " + str(root.parent))
    if root.exists():
        raise SliceWorkspaceError("the task root already exists and is never reused: " + raw)
    if _is_within(root, repository):
        raise SliceWorkspaceError(
            "the task root must stay outside the repository work tree: " + raw
        )
    return root


def _require_task_root(raw: str) -> Path:
    """One existing task root below a reparse-free ancestor chain."""
    root = Path(raw)
    if not root.is_absolute() or not root.is_dir():
        raise SliceWorkspaceError("task root must be an absolute existing directory: " + raw)
    _require_plain_chain(root)
    return root


def _tree_entries(repository: Path, commit: str) -> dict[str, tuple[str, str]]:
    """Exact path -> (mode, object id) for one commit; metadata only, no blob bodies."""
    entries: dict[str, tuple[str, str]] = {}
    for record in _git(repository, "ls-tree", "-r", "-z", commit).split("\0"):
        if not record:
            continue
        metadata, separator, path = record.partition("\t")
        fields = metadata.split(" ")
        if not separator or len(fields) != 3 or _OBJECT_ID_PATTERN.fullmatch(fields[2]) is None:
            raise SliceWorkspaceError("Git tree record has an unexpected shape")
        entries[path] = (fields[0], fields[2])
    return entries


def _read_blob(repository: Path, object_id: str, path: str) -> bytes:
    try:
        text = _run_git(repository, "cat-file", "blob", object_id)
    except BridgePathError as error:
        raise SliceWorkspaceError(f"Git blob read failed for {path}: {error}") from error
    payload = text.encode("utf-8")
    _decode_text(payload, path)  # The frozen bytes carry the same text policy.
    return payload


def _read_sources(repository: Path, commit: str, paths: tuple[str, ...]) -> dict[str, bytes]:
    """Exact blob bytes for every requested path, read from the commit, never the work tree."""
    tree = _tree_entries(repository, commit)
    payloads: dict[str, bytes] = {}
    for path in paths:
        entry = tree.get(path)
        if entry is None:
            raise SliceWorkspaceError("source path is not present at the frozen commit: " + path)
        mode, object_id = entry
        if mode not in _READABLE_GIT_MODES:
            raise SliceWorkspaceError(
                f"source path has Git mode {mode}; symlinks, submodules and trees are refused: "
                + path
            )
        payloads[path] = _read_blob(repository, object_id, path)
    return payloads


def _manifest_bytes(
    payloads: dict[str, bytes], note: bytes, commit: str, editable: tuple[str, ...]
) -> bytes:
    document = {
        "manifest_version": MANIFEST_VERSION,
        "source_commit": commit,
        "files": [
            {"path": path, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
            for path, payload in payloads.items()
        ],
        "task_note": {"bytes": len(note), "sha256": hashlib.sha256(note).hexdigest()},
        "editable": list(editable),
    }
    encoded = json.dumps(
        document, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    return encoded.encode("utf-8") + b"\n"


def _parse_manifest(payload: bytes) -> SliceManifest:
    try:
        document = json.loads(_decode_text(payload, "manifest"))
    except json.JSONDecodeError as error:
        raise SliceWorkspaceError("manifest is not valid JSON") from error
    if not isinstance(document, dict) or set(document) != _MANIFEST_KEYS:
        raise SliceWorkspaceError("manifest must carry exactly the version 1 keys")
    version = document["manifest_version"]
    if type(version) is not int or version != MANIFEST_VERSION:
        raise SliceWorkspaceError("manifest version is not supported")
    commit = document["source_commit"]
    if not isinstance(commit, str) or _OBJECT_ID_PATTERN.fullmatch(commit) is None:
        raise SliceWorkspaceError("manifest source commit must be a full lowercase 40-hex id")
    entries, editable = document["files"], document["editable"]
    if not isinstance(entries, list) or not entries:
        raise SliceWorkspaceError("manifest file list must be a non-empty array")
    if not isinstance(editable, list) or any(not isinstance(value, str) for value in editable):
        raise SliceWorkspaceError("manifest editable list must be an array of paths")
    recorded: dict[str, tuple[int, str]] = {}
    for item in entries:
        if not isinstance(item, dict) or set(item) != _MANIFEST_FILE_KEYS:
            raise SliceWorkspaceError("manifest file entries carry exactly path, bytes and sha256")
        path, size, digest = item["path"], item["bytes"], item["sha256"]
        if not isinstance(path, str) or not isinstance(digest, str) or type(size) is not int:
            raise SliceWorkspaceError(
                "manifest entries need string paths, string hashes, int bytes"
            )
        if size < 0 or _SHA256_PATTERN.fullmatch(digest) is None:
            raise SliceWorkspaceError("manifest byte counts and hashes must be well formed")
        recorded[path] = (size, digest)
    paths = _require_path_list([item["path"] for item in entries], "manifest file")
    editable_paths = tuple(sorted(editable))
    if len(set(editable_paths)) != len(editable_paths) or set(editable_paths) - set(paths):
        raise SliceWorkspaceError(
            "manifest editable paths must be a duplicate-free subset of the files"
        )
    note = document["task_note"]
    if not isinstance(note, dict) or set(note) != _MANIFEST_NOTE_KEYS:
        raise SliceWorkspaceError("manifest task note carries exactly bytes and sha256")
    note_size, note_digest = note["bytes"], note["sha256"]
    if type(note_size) is not int or not isinstance(note_digest, str) or note_size < 0:
        raise SliceWorkspaceError("manifest task note needs an int byte count and a string hash")
    if _SHA256_PATTERN.fullmatch(note_digest) is None:
        raise SliceWorkspaceError("manifest task note hash must be 64 lowercase hex")
    files = tuple(
        SliceFile(path=path, size=recorded[path][0], sha256=recorded[path][1]) for path in paths
    )
    return SliceManifest(
        source_commit=commit,
        files=files,
        editable=editable_paths,
        task_note_size=note_size,
        task_note_sha256=note_digest,
    )


def _scan_tree(
    root: Path, expected_files: frozenset[str], allowed_extra: frozenset[str]
) -> tuple[frozenset[str], tuple[str, ...]]:
    """List one slice tree without ever following a reparse point."""
    if not root.is_dir():
        raise SliceWorkspaceError("required slice directory is missing: " + str(root))
    expected_directories = {
        "/".join(PurePosixPath(value).parts[:index])
        for value in expected_files
        for index in range(1, len(PurePosixPath(value).parts))
    }
    present: set[str] = set()
    problems: list[str] = []
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if _is_reparse(path):
                    problems.append("reparse point is refused: " + relative)
                elif entry.is_dir():
                    if relative in expected_directories:
                        pending.append(path)
                    else:
                        problems.append("unexpected directory: " + relative)
                elif relative in expected_files or relative in allowed_extra:
                    present.add(relative)
                else:
                    problems.append("unexpected file: " + relative)
    return frozenset(present), tuple(problems)


def _verify_tree(
    root: Path,
    manifest: SliceManifest,
    allowed_extra: frozenset[str],
    label: str,
    *,
    verify_hashes: bool,
) -> None:
    expected = frozenset(file.path for file in manifest.files)
    present, problems = _scan_tree(root, expected, allowed_extra)
    details = [*(f"missing: {value}" for value in sorted(expected - present)), *problems]
    details.extend(f"missing: {value}" for value in sorted(allowed_extra - present))
    if details:
        raise SliceWorkspaceError(f"{label} does not match the manifest: " + _summarize(details))
    if not verify_hashes:
        return
    for file in manifest.files:
        payload = _tree_path(root, file.path).read_bytes()
        if len(payload) != file.size or hashlib.sha256(payload).hexdigest() != file.sha256:
            raise SliceWorkspaceError("baseline no longer matches the manifest: " + file.path)


def _verify_frozen_site(root: Path) -> tuple[SliceManifest, bytes]:
    """Read the manifest and re-verify baseline, work surface and task note.

    Both `collect` and `plan` start from this read-only precondition, so the two
    commands cannot drift apart in what they accept.
    """
    manifest_bytes = _read_text_file(root / MANIFEST_NAME, "manifest")
    manifest = _parse_manifest(manifest_bytes)
    baseline_root, work_root = root / BASELINE_DIRECTORY, root / WORK_DIRECTORY
    _verify_tree(baseline_root, manifest, frozenset(), "baseline", verify_hashes=True)
    _verify_tree(work_root, manifest, frozenset({TASK_NOTE_NAME}), "work tree", verify_hashes=False)
    note_bytes = (work_root / TASK_NOTE_NAME).read_bytes()
    if len(note_bytes) != manifest.task_note_size or (
        hashlib.sha256(note_bytes).hexdigest() != manifest.task_note_sha256
    ):
        raise SliceWorkspaceError("the task note no longer matches the manifest: " + TASK_NOTE_NAME)
    return manifest, manifest_bytes


def _changed_texts(
    baseline_root: Path, work_root: Path, manifest: SliceManifest
) -> tuple[tuple[str, str, str], ...]:
    changed: list[tuple[str, str, str]] = []
    for file in manifest.files:
        baseline_bytes = _tree_path(baseline_root, file.path).read_bytes()
        work_bytes = _tree_path(work_root, file.path).read_bytes()
        if baseline_bytes == work_bytes:
            continue
        changed.append(
            (
                file.path,
                _decode_text(baseline_bytes, BASELINE_DIRECTORY + "/" + file.path),
                _decode_text(work_bytes, WORK_DIRECTORY + "/" + file.path),
            )
        )
    return tuple(changed)


def _split_lines(text: str) -> list[str]:
    """Split on LF only; other Unicode separators stay inside the line."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _unified_diff(path: str, baseline_text: str, work_text: str) -> str:
    generated = difflib.unified_diff(
        _split_lines(baseline_text),
        _split_lines(work_text),
        fromfile=BASELINE_DIRECTORY + "/" + path,
        tofile=WORK_DIRECTORY + "/" + path,
        lineterm="\n",
        n=3,
    )
    return "".join(_terminate_diff_line(line) for line in generated)


def _terminate_diff_line(line: str) -> str:
    """Keep raw bytes intact: a line without LF gets the standard diff marker."""
    if line.endswith("\n"):
        return line
    return line + "\n" + _NO_NEWLINE_MARKER + "\n"


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def _json_bytes(document: dict[str, object]) -> bytes:
    encoded = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (encoded + "\n").encode("utf-8")


def _print_json(document: dict[str, object]) -> None:
    _write_stdout_bytes(_json_bytes(document))


def _write_stdout_bytes(payload: bytes) -> None:
    """Emit explicit UTF-8 bytes: no newline translation, no extra encoding layer."""
    stream = getattr(sys.stdout, "buffer", None)
    sys.stdout.flush()
    if stream is None:
        sys.stdout.write(payload.decode("utf-8"))
        return
    stream.write(payload)


def command_prepare(arguments: argparse.Namespace) -> int:
    repository = _require_repository(arguments.repository or str(DEFAULT_REPOSITORY))
    commit = _require_commit(repository, arguments.commit)
    paths = _require_path_list(arguments.file, "source")
    editable = _require_editable(arguments.editable, paths)
    root = _require_new_task_root(arguments.out, repository)
    note = _read_text_file(Path(arguments.task_note), "task note")
    payloads = _read_sources(repository, commit, paths)
    manifest = _manifest_bytes(payloads, note, commit, editable)
    try:
        root.mkdir()
    except FileExistsError as error:
        raise SliceWorkspaceError(
            "the task root already exists and is never reused: " + str(root)
        ) from error
    try:
        for path, payload in payloads.items():
            _write_new(_tree_path(root / BASELINE_DIRECTORY, path), payload)
        _write_new(root / WORK_DIRECTORY / TASK_NOTE_NAME, note)
        for path, payload in payloads.items():
            _write_new(_tree_path(root / WORK_DIRECTORY, path), payload)
        _write_new(root / MANIFEST_NAME, manifest)
    except OSError as error:
        raise SliceWorkspaceError(
            "write failed; the partial task root stays in place at " + str(root)
        ) from error
    _print_json(
        {
            "command": "prepare",
            "task_root": str(root),
            "source_commit": commit,
            "files": len(payloads),
            "editable": list(editable),
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        }
    )
    return 0


def command_collect(arguments: argparse.Namespace) -> int:
    root = _require_task_root(arguments.task_root)
    manifest, _manifest_raw = _verify_frozen_site(root)
    baseline_root, work_root = root / BASELINE_DIRECTORY, root / WORK_DIRECTORY
    changed = _changed_texts(baseline_root, work_root, manifest)
    editable = frozenset(manifest.editable)
    outside = [path for path, _baseline, _work in changed if path not in editable]
    if outside:
        raise SliceWorkspaceError(
            "changed paths outside the editable set are refused: " + _summarize(outside)
        )
    diff = "".join(
        _unified_diff(path, baseline_text, work_text) for path, baseline_text, work_text in changed
    )
    encoded = diff.encode("utf-8")
    _print_json(
        {
            "command": "collect",
            "task_root": str(root),
            "source_commit": manifest.source_commit,
            "files": len(manifest.files),
            "editable": len(manifest.editable),
            "changed": [path for path, _baseline, _work in changed],
            "diff_bytes": len(encoded),
            "diff_sha256": hashlib.sha256(encoded).hexdigest(),
        }
    )
    _write_stdout_bytes(encoded)
    return 0


def _posix_absolute(path: Path) -> str:
    """Plan paths use forward slashes, matching the recorded rule strings."""
    return str(path).replace("\\", "/")


def _plan_read_paths(root: Path, manifest: SliceManifest) -> tuple[str, ...]:
    work_root = root / WORK_DIRECTORY
    return (
        _posix_absolute(work_root / TASK_NOTE_NAME),
        *(_posix_absolute(_tree_path(work_root, file.path)) for file in manifest.files),
    )


def _plan_prompt(read_paths: tuple[str, ...], write_paths: tuple[str, ...]) -> str:
    """One --print argument: the fixed instruction plus this plan's path data."""
    access_list = json.dumps(
        {"readable": list(read_paths), "writable": list(write_paths)},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return PLAN_INSTRUCTION + PLAN_ACCESS_MARKER + access_list


def _plan_argv(read_paths: tuple[str, ...], write_paths: tuple[str, ...]) -> list[str]:
    return [
        "--print",
        _plan_prompt(read_paths, write_paths),
        "--model",
        PLAN_MODEL,
        "--effort",
        PLAN_EFFORT,
        "--output-format",
        "stream-json",
        "--disable-slash-commands",
        "--print-timeout",
        PLAN_PRINT_TIMEOUT,
    ]


def _plan_document(root: Path, manifest: SliceManifest, manifest_sha256: str) -> dict[str, object]:
    read_paths = _plan_read_paths(root, manifest)
    write_paths = tuple(
        _posix_absolute(_tree_path(root / WORK_DIRECTORY, path)) for path in manifest.editable
    )
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "execution_authorized": False,
        "task_root": _posix_absolute(root),
        "source_commit": manifest.source_commit,
        "manifest_sha256": manifest_sha256,
        "cwd": _posix_absolute(root / WORK_DIRECTORY),
        "read_file": list(read_paths),
        "write_file": list(write_paths),
        "model": PLAN_MODEL,
        "effort": PLAN_EFFORT,
        "argv": _plan_argv(read_paths, write_paths),
        "permission_rules": {
            "read_file": ["read_file(" + path + ")" for path in read_paths],
            "write_file": ["write_file(" + path + ")" for path in write_paths],
            "counts": {"read_file": len(read_paths), "write_file": len(write_paths), "command": 0},
        },
        "notes": [
            "Plan only: not an approval, not an authorization and not a runner.",
            "The recorded syntax is an allow list; exact-file versus prefix matching is not "
            "established by the single recorded run, and no OS isolation is claimed.",
            "No command rule, no wildcard root, no continue and no skip-permissions entry.",
            "Untested here: the CLI binary identity, model behaviour and provider outcome.",
        ],
    }


def build_plan(task_root: str) -> dict[str, object]:
    """Public read-only entry: regenerate and verify one task root's plan."""
    root = _require_task_root(task_root)
    manifest, manifest_bytes = _verify_frozen_site(root)
    baseline_root, work_root = root / BASELINE_DIRECTORY, root / WORK_DIRECTORY
    changed = _changed_texts(baseline_root, work_root, manifest)
    if changed:
        raise SliceWorkspaceError(
            "plan requires an untouched work tree; changed paths are refused: "
            + _summarize([path for path, _baseline, _work in changed])
        )
    return _plan_document(root, manifest, hashlib.sha256(manifest_bytes).hexdigest())


def command_plan(arguments: argparse.Namespace) -> int:
    _print_json(build_plan(arguments.task_root))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent-bridge",
        description=(
            "Prepare and collect a minimal local source slice. Local developer entry only: "
            "no MCP surface, no provider call, no OS sandbox. No arbitrary "
            "command, model, URL or path interface is offered."
        ),
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="copy an explicit source list out of one commit")
    prepare.add_argument(
        "--repository",
        default=None,
        help="exact Git work-tree root to slice; defaults to the current directory",
    )
    prepare.add_argument("--commit", required=True)
    prepare.add_argument("--file", action="append", required=True, default=[])
    prepare.add_argument("--editable", action="append", default=[])
    prepare.add_argument("--task-note", required=True)
    prepare.add_argument("--out", required=True)
    prepare.set_defaults(handler=command_prepare)
    collect = commands.add_parser("collect", help="report the editable diff of one task root")
    collect.add_argument("--task-root", required=True)
    collect.set_defaults(handler=command_collect)
    plan = commands.add_parser("plan", help="print the fixed host-run plan for one untouched root")
    plan.add_argument("--task-root", required=True)
    plan.set_defaults(handler=command_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        return arguments.handler(arguments)
    except SliceWorkspaceError as error:
        print("local-agent-bridge: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
