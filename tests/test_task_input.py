"""Offline tests for the task input snapshot importer (task contract package A).

Every fixture is synthetic and lives inside the pytest temporary root: small
Git repositories, in-memory ZIP packages and manifest-adjudicated directories.
No real package, credential, provider, network or upstream CLI is involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import warnings
import zipfile
from pathlib import Path

import pytest

from local_agent_bridge.bridge import task_input as entry
from local_agent_bridge.bridge.task_input import (
    TaskInputError,
    import_snapshot,
    read_snapshot,
)

TREE_FILES: dict[str, bytes] = {
    "AGENTS.md": b"# synthetic guide\n",
    "src/main.cs": b"// C-sharp source\nnamespace Demo {}\n",
    "src/nested/util.py": "def util():\n    return '中文'\n".encode(),
    "src/AuthToken.cs": b"public class AuthToken {}\n",
    "assets/blob.bin": bytes(range(256)),
}
TREE_DIRECTORIES = {"src", "src/nested", "assets"}
ENGINEERING_FILES: dict[str, bytes] = {
    "a.cs": b"\xef\xbb\xbfbom plus CRLF\r\n",
    "b.meta": b"no trailing newline",
    "bin.dat": b"\x00\x01\xff binary \x00 payload",
    "中文/说明.md": "中文内容\n".encode(),
    "AuthToken.cs": b"ordinary business class name\n",
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative, raw in files.items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _tree_document(root: Path) -> dict[str, object]:
    files: dict[str, tuple[int, str]] = {}
    directories: set[str] = set()
    for current, subdirectories, filenames in os.walk(root):
        for name in subdirectories:
            directories.add((Path(current) / name).relative_to(root).as_posix())
        for name in filenames:
            path = Path(current) / name
            files[path.relative_to(root).as_posix()] = (
                path.stat().st_size,
                _sha256(path.read_bytes()),
            )
    entries: list[dict[str, object]] = [
        {"path": path, "kind": "directory", "bytes": 0, "sha256": None}
        for path in sorted(directories, key=lambda item: item.encode("utf-8"))
    ]
    entries.extend(
        {"path": path, "kind": "file", "bytes": size, "sha256": digest}
        for path, (size, digest) in sorted(files.items(), key=lambda item: item[0].encode("utf-8"))
    )
    entries.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    return {"contract_version": 1, "entries": entries}


def _manifest_file(root: Path, document: dict[str, object]) -> Path:
    manifest = root.parent / "inventory.json"
    manifest.write_bytes(_canonical(document))
    return manifest


def _directory_source(tree_root: Path, manifest: Path) -> dict[str, object]:
    return {
        "kind": "directory",
        "root": str(tree_root),
        "manifest_path": str(manifest),
        "manifest_sha256": _sha256(manifest.read_bytes()),
    }


def _policy(**overrides: object) -> dict[str, object]:
    policy: dict[str, object] = {
        "source_paths": [],
        "excluded_paths": [],
        "sensitive_paths": [],
        "trusted_control_files": {},
    }
    policy.update(overrides)
    return policy


def _zip_source(package: Path, sha: str, strip: str | None = "pkg") -> dict[str, object]:
    return {"kind": "zip", "path": str(package), "sha256": sha, "strip_prefix": strip}


def _write_zip(
    package: Path,
    files: dict[str, bytes],
    *,
    prefix: str = "pkg",
    compression: int = zipfile.ZIP_DEFLATED,
    reverse: bool = False,
) -> str:
    with zipfile.ZipFile(package, "w") as archive:
        if prefix:
            archive.writestr(zipfile.ZipInfo(prefix + "/"), b"")
        names = sorted(files, reverse=reverse)
        for name in names:
            archive.writestr(
                zipfile.ZipInfo(prefix + "/" + name), files[name], compress_type=compression
            )
    return _sha256(package.read_bytes())


def _git(root: Path, *arguments: str, data: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, input=data
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    return completed.stdout


def _git_repository(root: Path, files: dict[str, bytes], executable: str | None = None) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    _write_tree(root, files)
    _git(root, "add", "-A")
    if executable is not None:
        _git(root, "update-index", "--chmod=+x", executable)
    _git(
        root,
        "-c",
        "user.email=bridge@example.invalid",
        "-c",
        "user.name=Bridge Test",
        "commit",
        "-q",
        "-m",
        "synthetic input",
    )
    return _git(root, "rev-parse", "HEAD").decode("ascii").strip()


def _git_source(root: Path, commit: str, paths: list[str]) -> dict[str, object]:
    return {"kind": "git", "root": str(root), "commit": commit, "paths": paths}


def _entry_map(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    return {entry["path"]: entry for entry in manifest["entries"]}


def _import_directory(tree_root: Path, manifest: Path, snapshot_root: Path) -> dict[str, object]:
    return import_snapshot(
        source=_directory_source(tree_root, manifest),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )


def _expect_error(code: str, callable_object, *arguments, **keywords) -> TaskInputError:
    with pytest.raises(TaskInputError) as details:
        callable_object(*arguments, **keywords)
    assert details.value.code == code
    assert str(details.value)
    return details.value


def test_directory_import_seals_a_canonical_snapshot(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    snapshot_root = tmp_path / "snapshot"

    manifest = _import_directory(tree, manifest_path, snapshot_root)

    assert manifest["contract_version"] == 1
    assert manifest["source"] == {
        "kind": "directory",
        "identity": _sha256(manifest_path.read_bytes()),
        "selection_sha256": _sha256(_canonical({"source_paths": [], "excluded_paths": []})),
    }
    assert manifest["source_paths"] == []
    assert manifest["excluded_paths"] == []
    entries = _entry_map(manifest)
    assert set(entries) == set(TREE_FILES) | TREE_DIRECTORIES
    for directory in TREE_DIRECTORIES:
        assert entries[directory] == {
            "path": directory,
            "kind": "directory",
            "bytes": 0,
            "sha256": None,
            "git_mode": None,
        }
    for relative, raw in TREE_FILES.items():
        assert entries[relative] == {
            "path": relative,
            "kind": "file",
            "bytes": len(raw),
            "sha256": _sha256(raw),
            "git_mode": None,
        }
        staged = snapshot_root.joinpath("source", *relative.split("/"))
        assert staged.read_bytes() == raw
    canonical = _canonical(manifest)
    assert (snapshot_root / "manifest.json").read_bytes() == canonical
    sealed = _sha256(canonical).encode("ascii")
    assert (snapshot_root / "SEALED").read_bytes() == sealed
    assert not sealed.endswith(b"\n")
    assert read_snapshot(snapshot_root=snapshot_root) == manifest


def test_git_zip_and_directory_imports_share_snapshot_identity(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    directory_manifest = _import_directory(
        tree, _manifest_file(tree, _tree_document(tree)), tmp_path / "snap-dir"
    )

    package = tmp_path / "input.zip"
    zip_sha = _write_zip(package, TREE_FILES, compression=zipfile.ZIP_DEFLATED)
    zip_manifest = import_snapshot(
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snap-zip",
    )
    reversed_package = tmp_path / "input-reversed.zip"
    reversed_sha = _write_zip(
        reversed_package, TREE_FILES, compression=zipfile.ZIP_STORED, reverse=True
    )
    stored_manifest = import_snapshot(
        source=_zip_source(reversed_package, reversed_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snap-stored",
    )

    repository = tmp_path / "repository"
    repository.mkdir()
    commit = _git_repository(repository, TREE_FILES, executable="src/main.cs")
    git_manifest = import_snapshot(
        source=_git_source(repository, commit, sorted(TREE_FILES)),
        policy=_policy(),
        snapshot_root=tmp_path / "snap-git",
    )

    identity = directory_manifest["snapshot_id"]
    assert zip_manifest["snapshot_id"] == identity
    assert stored_manifest["snapshot_id"] == identity
    assert git_manifest["snapshot_id"] == identity
    expected_identity = _sha256(
        _canonical(
            {
                "contract_version": 1,
                "entries": [
                    {
                        "path": item["path"],
                        "kind": item["kind"],
                        "bytes": item["bytes"],
                        "sha256": item["sha256"],
                    }
                    for item in directory_manifest["entries"]
                ],
            }
        )
    )
    assert identity == expected_identity
    assert directory_manifest["source"]["kind"] == "directory"
    assert zip_manifest["source"]["kind"] == "zip"
    assert zip_manifest["source"]["identity"] == zip_sha
    assert git_manifest["source"]["identity"] == commit
    git_entries = _entry_map(git_manifest)
    assert git_entries["src/main.cs"]["git_mode"] == "100755"
    assert git_entries["assets/blob.bin"]["git_mode"] == "100644"
    assert _canonical(directory_manifest) != _canonical(zip_manifest)
    assert _canonical(git_manifest) != _canonical(zip_manifest)


def test_git_import_binds_to_commit_not_the_worktree(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commit = _git_repository(repository, TREE_FILES)
    source = _git_source(repository, commit, sorted(TREE_FILES))
    first = import_snapshot(source=source, policy=_policy(), snapshot_root=tmp_path / "snap-one")
    (repository / "src" / "main.cs").write_bytes(b"local edits do not matter\n")
    (repository / "untracked.txt").write_bytes(b"untracked")
    _git(repository, "checkout", "-q", "-b", "renamed-branch")
    second = import_snapshot(source=source, policy=_policy(), snapshot_root=tmp_path / "snap-two")
    assert second["snapshot_id"] == first["snapshot_id"]
    staged = tmp_path / "snap-two" / "source" / "src" / "main.cs"
    assert staged.read_bytes() == TREE_FILES["src/main.cs"]


def test_git_import_preserves_engineering_bytes_and_ordinary_names(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commit = _git_repository(repository, ENGINEERING_FILES)
    manifest = import_snapshot(
        source=_git_source(repository, commit, sorted(ENGINEERING_FILES)),
        policy=_policy(source_paths=sorted(ENGINEERING_FILES)),
        snapshot_root=tmp_path / "snapshot",
    )
    entries = _entry_map(manifest)
    assert set(entries) == set(ENGINEERING_FILES) | {"中文"}
    for relative, raw in ENGINEERING_FILES.items():
        staged = tmp_path / "snapshot" / "source" / Path(*relative.split("/"))
        assert staged.read_bytes() == raw
        assert entries[relative]["sha256"] == _sha256(raw)
        assert entries[relative]["bytes"] == len(raw)
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_git_rejects_links_submodules_and_broken_selections(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commit = _git_repository(repository, TREE_FILES)
    link_sha = (
        _git(repository, "hash-object", "-w", "--stdin", data=b"target.txt").decode("ascii").strip()
    )
    _git(
        repository,
        "-c",
        "user.email=bridge@example.invalid",
        "-c",
        "user.name=Bridge Test",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "link",
    )
    _git(repository, "update-index", "--add", "--cacheinfo", f"120000,{link_sha},link.txt")
    _git(
        repository,
        "-c",
        "user.email=bridge@example.invalid",
        "-c",
        "user.name=Bridge Test",
        "commit",
        "-q",
        "-m",
        "add link",
    )
    for paths, code in (
        (["link.txt"], "GitSelectionInvalid"),
        (["missing.cs"], "GitSelectionInvalid"),
        (["src"], "GitSelectionInvalid"),
    ):
        _expect_error(
            code,
            import_snapshot,
            source=_git_source(repository, commit, paths),
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot",
        )
    _expect_error(
        "InvalidSource",
        import_snapshot,
        source=_git_source(repository, "abcd", ["src/main.cs"]),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )


def test_zip_strip_prefix_is_explicit(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    zip_sha = _write_zip(package, {"data.txt": b"payload\n"})
    manifest = import_snapshot(
        source=_zip_source(package, zip_sha, strip="pkg"),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert set(_entry_map(manifest)) == {"data.txt"}
    _expect_error(
        "StripPrefixMismatch",
        import_snapshot,
        source=_zip_source(package, zip_sha, strip="other"),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-mismatch",
    )
    full = import_snapshot(
        source=_zip_source(package, zip_sha, strip=None),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-full",
    )
    assert set(_entry_map(full)) == {"pkg", "pkg/data.txt"}


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "a/../b.txt",
        "/rooted.txt",
        "C:/drive.txt",
        "C:relative.txt",
        "\\\\server\\share\\file.txt",
        "pkg/CON",
        "pkg/CON.txt",
        "pkg/com1.dat",
        "pkg/nul",
        "pkg/trailing.",
        "pkg/trailing space ",
        "pkg/a//b.txt",
        "pkg/a/./b.txt",
    ],
)
def test_zip_rejects_unsafe_entry_names_before_any_write(tmp_path: Path, name: str) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(zipfile.ZipInfo(name), b"payload\n")
    zip_sha = _sha256(package.read_bytes())
    snapshot_root = tmp_path / "snapshot"
    _expect_error(
        "ZipEntryRejected",
        import_snapshot,
        source=_zip_source(package, zip_sha, strip=None),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    assert not snapshot_root.exists()
    assert not snapshot_root.with_name(snapshot_root.name + ".staging").exists()


def test_zip_rejects_a_name_that_hides_text_after_a_nul() -> None:
    info = zipfile.ZipInfo("pkg/visible.txt")
    info.orig_filename = "pkg/visible.txt\x00hidden.txt"
    with pytest.raises(TaskInputError) as details:
        entry._zip_entry_name(info, entry._default_verification_policy())
    assert details.value.code == "ZipEntryRejected"


@pytest.mark.parametrize(
    "names",
    [
        ["pkg/dup.txt", "pkg/dup.txt"],
        ["pkg/A.cs", "pkg/a.cs"],
        ["pkg/caf\u00e9.txt", "pkg/cafe\u0301.txt"],
        ["pkg/a", "pkg/a/b.txt"],
        ["pkg/same.txt", "pkg/SAME.txt/"],
    ],
)
def test_zip_rejects_duplicate_and_folding_conflicts(tmp_path: Path, names: list[str]) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for name in names:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(zipfile.ZipInfo(name), b"" if name.endswith("/") else b"payload\n")
    zip_sha = _sha256(package.read_bytes())
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )


def test_zip_accepts_explicit_directory_entries_with_children(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(zipfile.ZipInfo("pkg/"), b"")
        archive.writestr(zipfile.ZipInfo("pkg/a/"), b"")
        archive.writestr(zipfile.ZipInfo("pkg/a/b.cs"), b"class B {}\n")
    zip_sha = _sha256(package.read_bytes())
    manifest = import_snapshot(
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert set(_entry_map(manifest)) == {"a", "a/b.cs"}


def _mode_info(name: str, mode: int, *, dos_attributes: int = 0x20) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = (mode << 16) | dos_attributes
    return info


def _make_junction(link: Path, target: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    try:
        winapi.CreateJunction(str(target), str(link))
    except OSError as error:
        pytest.skip(f"junction fixture unavailable on this host: {error}")


@pytest.mark.parametrize(
    "info",
    [
        _mode_info("pkg/link", stat.S_IFLNK | 0o644),
        _mode_info("pkg/pipe", stat.S_IFIFO | 0o644),
        _mode_info("pkg/device", stat.S_IFCHR | 0o644),
    ],
)
def test_zip_rejects_link_and_device_types(tmp_path: Path, info: zipfile.ZipInfo) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(info, b"payload\n")
    zip_sha = _sha256(package.read_bytes())
    _expect_error(
        "ZipEntryRejected",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )


def test_zip_rejects_reparse_directories_encryption_and_other_compression(
    tmp_path: Path,
) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        reparse = zipfile.ZipInfo("pkg/dir/")
        reparse.external_attr = 0x10 | 0x400
        archive.writestr(reparse, b"")
    zip_sha = _sha256(package.read_bytes())
    _expect_error(
        "ZipEntryRejected",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )

    encrypted = zipfile.ZipInfo("pkg/secret.txt")
    encrypted.flag_bits |= 0x1
    with pytest.raises(TaskInputError) as details:
        entry._zip_entry_kind(encrypted, False)
    assert details.value.code == "ZipEntryRejected"

    bzip_package = tmp_path / "bzip.zip"
    with zipfile.ZipFile(bzip_package, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("pkg/data.txt"), b"payload\n", compress_type=zipfile.ZIP_BZIP2
        )
    _expect_error(
        "ZipEntryRejected",
        import_snapshot,
        source=_zip_source(bzip_package, _sha256(bzip_package.read_bytes())),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-bzip",
    )


def test_zip_crc_failure_keeps_a_labelled_staging_root(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(zipfile.ZipInfo("pkg/data.txt"), b"correct horse battery staple " * 4)
    raw = bytearray(package.read_bytes())
    header = raw.find(b"PK\x03\x04")
    name_length = int.from_bytes(raw[header + 26 : header + 28], "little")
    data_start = header + 30 + name_length
    raw[data_start] ^= 0xFF
    package.write_bytes(bytes(raw))
    zip_sha = _sha256(package.read_bytes())
    snapshot_root = tmp_path / "snapshot"

    _expect_error(
        "InputChanged",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )

    staging = snapshot_root.with_name(snapshot_root.name + ".staging")
    assert not snapshot_root.exists()
    assert staging.is_dir()
    assert (staging / "IMPORT-FAILED").read_text(encoding="ascii").strip() == "InputChanged"
    assert not (staging / "manifest.json").exists()
    assert not (staging / "SEALED").exists()


def test_zip_declared_hash_and_package_size_are_checked(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    zip_sha = _write_zip(package, {"data.txt": b"payload\n"})
    _expect_error(
        "InputChanged",
        import_snapshot,
        source=_zip_source(package, "0" * 64),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(package_bytes_limit=16),
        snapshot_root=tmp_path / "snapshot",
    )


def test_expansion_ratio_and_declared_size_limits(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    zip_sha = _write_zip(package, {"zero.bin": b"\x00" * 2048})
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(expansion_ratio_limit=4),
        snapshot_root=tmp_path / "snapshot",
    )
    manifest = import_snapshot(
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert _entry_map(manifest)["zero.bin"]["bytes"] == 2048


def test_depth_and_component_limits_are_enforced(tmp_path: Path) -> None:
    deep_package = tmp_path / "deep.zip"
    deep_name = "pkg/" + "/".join(["d"] * 32) + "/leaf.txt"
    with zipfile.ZipFile(deep_package, "w") as archive:
        archive.writestr(zipfile.ZipInfo(deep_name), b"deep\n")
    deep_sha = _sha256(deep_package.read_bytes())
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_zip_source(deep_package, deep_sha),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-deep",
    )

    long_package = tmp_path / "long.zip"
    long_name = "pkg/" + "汉" * 4 + ".txt"
    with zipfile.ZipFile(long_package, "w") as archive:
        archive.writestr(zipfile.ZipInfo(long_name), b"long\n")
    long_sha = _sha256(long_package.read_bytes())
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_zip_source(long_package, long_sha),
        policy=_policy(component_codepoints_limit=7),
        snapshot_root=tmp_path / "snapshot-long",
    )

    boundary_package = tmp_path / "boundary.zip"
    boundary_name = "pkg/" + "汉" * 4 + ".txt"
    with zipfile.ZipFile(boundary_package, "w") as archive:
        archive.writestr(zipfile.ZipInfo(boundary_name), b"boundary\n")
    boundary_sha = _sha256(boundary_package.read_bytes())
    manifest = import_snapshot(
        source=_zip_source(boundary_package, boundary_sha),
        policy=_policy(component_codepoints_limit=8),
        snapshot_root=tmp_path / "snapshot-boundary",
    )
    assert len(_entry_map(manifest)) == 1
    staged = tmp_path / "snapshot-boundary" / "source" / boundary_name.removeprefix("pkg/")
    assert staged.read_bytes() == b"boundary\n"


def test_physical_path_budget_counts_utf16_units(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    emoji_name = "pkg/\U0001f600note.txt"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(zipfile.ZipInfo(emoji_name), b"emoji\n")
    zip_sha = _sha256(package.read_bytes())
    snapshot_root = tmp_path / "snapshot"
    staged_name = (
        snapshot_root.with_name(snapshot_root.name + ".staging") / "source" / emoji_name[4:]
    )
    budget = sum(2 if ord(char) > 0xFFFF else 1 for char in str(staged_name))
    manifest = import_snapshot(
        source=_zip_source(package, zip_sha),
        policy=_policy(physical_path_utf16_limit=budget),
        snapshot_root=snapshot_root,
    )
    assert len(_entry_map(manifest)) == 1
    second_root = tmp_path / "snapshot-tight"
    tight_name = second_root.with_name(second_root.name + ".staging") / "source" / emoji_name[4:]
    tight_budget = sum(2 if ord(char) > 0xFFFF else 1 for char in str(tight_name))
    _expect_error(
        "PathBudgetExceeded",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(physical_path_utf16_limit=tight_budget - 1),
        snapshot_root=second_root,
    )


def test_directory_entry_and_file_limits(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(entry_count_limit=4),
        snapshot_root=tmp_path / "snapshot-count",
    )
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(file_bytes_limit=64),
        snapshot_root=tmp_path / "snapshot-file",
    )
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(expanded_bytes_limit=64),
        snapshot_root=tmp_path / "snapshot-total",
    )


def test_sensitive_excluded_and_source_path_accounting(tmp_path: Path) -> None:
    files = dict(TREE_FILES)
    files["creds/key.pem"] = b"synthetic credential material\n"
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, files)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    source = _directory_source(tree, manifest_path)

    _expect_error(
        "SensitivePathImported",
        import_snapshot,
        source=source,
        policy=_policy(sensitive_paths=["creds/key.pem"]),
        snapshot_root=tmp_path / "snapshot-sensitive",
    )
    _expect_error(
        "SourcePathUnaccounted",
        import_snapshot,
        source=source,
        policy=_policy(source_paths=["ghost.cs"]),
        snapshot_root=tmp_path / "snapshot-ghost",
    )
    _expect_error(
        "ExcludedPathUnknown",
        import_snapshot,
        source=source,
        policy=_policy(excluded_paths=[{"path": "ghost.cs", "reason": "not present"}]),
        snapshot_root=tmp_path / "snapshot-unknown",
    )

    policy = _policy(
        source_paths=["src/main.cs", "creds/key.pem"],
        sensitive_paths=["creds/key.pem"],
        excluded_paths=[{"path": "creds/key.pem", "reason": "credential material"}],
    )
    manifest = import_snapshot(source=source, policy=policy, snapshot_root=tmp_path / "snapshot")
    entries = _entry_map(manifest)
    assert "creds/key.pem" not in entries
    assert "creds" in entries
    assert entries["src/AuthToken.cs"]["kind"] == "file"
    assert manifest["excluded_paths"] == [
        {"path": "creds/key.pem", "reason": "credential material"}
    ]
    assert manifest["source_paths"] == ["src/main.cs", "creds/key.pem"]
    expected_selection = _sha256(
        _canonical(
            {
                "source_paths": ["src/main.cs", "creds/key.pem"],
                "excluded_paths": [{"path": "creds/key.pem", "reason": "credential material"}],
            }
        )
    )
    assert manifest["source"]["selection_sha256"] == expected_selection
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_trusted_control_files_are_hash_bound(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    source = _directory_source(tree, manifest_path)
    trusted = {"AGENTS.md": _sha256(TREE_FILES["AGENTS.md"])}
    manifest = import_snapshot(
        source=source,
        policy=_policy(trusted_control_files=trusted),
        snapshot_root=tmp_path / "snapshot",
    )
    assert manifest["entries"]

    wrong = {"AGENTS.md": "0" * 64}
    _expect_error(
        "InputControlConflict",
        import_snapshot,
        source=source,
        policy=_policy(trusted_control_files=wrong),
        snapshot_root=tmp_path / "snapshot-wrong",
    )
    missing = {"control/host.rules": _sha256(b"absent")}
    _expect_error(
        "InputControlConflict",
        import_snapshot,
        source=source,
        policy=_policy(trusted_control_files=missing),
        snapshot_root=tmp_path / "snapshot-missing",
    )


def test_directory_manifest_adjudication_rejects_drift(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))

    tampered = _directory_source(tree, manifest_path)
    tampered["manifest_sha256"] = "0" * 64
    _expect_error(
        "InputManifestMismatch",
        import_snapshot,
        source=tampered,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-hash",
    )

    (tree / "extra.txt").write_bytes(b"appeared after the manifest\n")
    _expect_error(
        "InputChanged",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-extra",
    )
    (tree / "extra.txt").unlink()
    (tree / "src" / "main.cs").unlink()
    _expect_error(
        "InputChanged",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-missing",
    )
    (tree / "src" / "main.cs").write_bytes(TREE_FILES["src/main.cs"])

    duplicate_raw = b'{"contract_version":1,"entries":[],"entries":[]}'
    duplicate_manifest = tmp_path / "duplicate.json"
    duplicate_manifest.write_bytes(duplicate_raw)
    _expect_error(
        "InvalidManifest",
        import_snapshot,
        source={
            "kind": "directory",
            "root": str(tree),
            "manifest_path": str(duplicate_manifest),
            "manifest_sha256": _sha256(duplicate_raw),
        },
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-duplicate",
    )

    document = _tree_document(tree)
    document["entries"] = [item for item in document["entries"] if item["path"] != "src/nested"]
    parentless = _manifest_file(tree, document)
    _expect_error(
        "InputManifestMismatch",
        import_snapshot,
        source=_directory_source(tree, parentless),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-parent",
    )


def test_read_snapshot_rejects_every_drift(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    snapshot_root = tmp_path / "snapshot"
    _import_directory(tree, manifest_path, snapshot_root)
    sealed_file = snapshot_root / "source" / "src" / "nested" / "util.py"

    original = sealed_file.read_bytes()
    sealed_file.write_bytes(original + b"drift\n")
    _expect_error("TreeMismatch", read_snapshot, snapshot_root=snapshot_root)
    sealed_file.write_bytes(original)

    (snapshot_root / "source" / "extra.txt").write_bytes(b"extra")
    _expect_error("TreeMismatch", read_snapshot, snapshot_root=snapshot_root)
    (snapshot_root / "source" / "extra.txt").unlink()
    assert read_snapshot(snapshot_root=snapshot_root)

    sealed = (snapshot_root / "SEALED").read_bytes()
    (snapshot_root / "SEALED").write_bytes(b"0" * 64)
    _expect_error("SealedMismatch", read_snapshot, snapshot_root=snapshot_root)
    (snapshot_root / "SEALED").write_bytes(sealed)

    manifest_bytes = (snapshot_root / "manifest.json").read_bytes()
    (snapshot_root / "manifest.json").write_bytes(manifest_bytes + b"\n")
    _expect_error("ManifestNotCanonical", read_snapshot, snapshot_root=snapshot_root)
    (snapshot_root / "manifest.json").write_bytes(manifest_bytes)

    document = json.loads(manifest_bytes)
    document["snapshot_id"] = "0" * 64
    drifted = _canonical(document)
    (snapshot_root / "manifest.json").write_bytes(drifted)
    (snapshot_root / "SEALED").write_bytes(_sha256(drifted).encode("ascii"))
    _expect_error("IdentityMismatch", read_snapshot, snapshot_root=snapshot_root)
    (snapshot_root / "manifest.json").write_bytes(manifest_bytes)
    (snapshot_root / "SEALED").write_bytes(sealed)

    (snapshot_root / "SEALED").unlink()
    _expect_error("IoFailed", read_snapshot, snapshot_root=snapshot_root)


def test_snapshot_root_and_input_arguments_are_validated(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    source = _directory_source(tree, manifest_path)

    existing = tmp_path / "snapshot"
    existing.mkdir()
    _expect_error(
        "SnapshotRootNotFresh",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=existing,
    )
    staging = tmp_path / "snapshot-two.staging"
    staging.mkdir()
    _expect_error(
        "SnapshotRootNotFresh",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-two",
    )
    _expect_error(
        "SnapshotRootInvalid",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=Path("relative-snapshot"),
    )

    for policy, code in (
        ({**_policy(), "unknown_limit": 1}, "InvalidPolicy"),
        (_policy(entry_count_limit=True), "InvalidPolicy"),
        (_policy(entry_count_limit=0), "InvalidPolicy"),
        (_policy(entry_count_limit=20001), "InvalidPolicy"),
        (_policy(source_paths=["ok.cs", "ok.cs"]), "InvalidPolicy"),
        (
            _policy(
                excluded_paths=[
                    {"path": "a", "reason": "x"},
                    {"path": "a", "reason": "y"},
                ]
            ),
            "InvalidPolicy",
        ),
    ):
        _expect_error(
            code,
            import_snapshot,
            source=source,
            policy=policy,
            snapshot_root=tmp_path / "snapshot-policy",
        )
    minimal = dict(_policy())
    del minimal["source_paths"]
    _expect_error(
        "InvalidPolicy",
        import_snapshot,
        source=source,
        policy=minimal,
        snapshot_root=tmp_path / "snapshot-policy",
    )

    broken_source = dict(source)
    broken_source["unexpected"] = True
    _expect_error(
        "InvalidSource",
        import_snapshot,
        source=broken_source,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-source",
    )
    incomplete = dict(source)
    del incomplete["manifest_sha256"]
    _expect_error(
        "InvalidSource",
        import_snapshot,
        source=incomplete,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-source",
    )
    _expect_error(
        "InvalidSource",
        import_snapshot,
        source={"kind": "folder"},
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-source",
    )


def test_input_roots_must_be_narrow_absolute_paths(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))

    relative = _directory_source(tree, manifest_path)
    relative["root"] = "tree"
    _expect_error(
        "InvalidSource",
        import_snapshot,
        source=relative,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )

    drive = _directory_source(tree, manifest_path)
    drive["root"] = "C:\\"
    _expect_error(
        "PathRejected",
        import_snapshot,
        source=drive,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )

    unc = _directory_source(tree, manifest_path)
    unc["root"] = "\\\\localhost\\c\\tree"
    _expect_error(
        "PathRejected",
        import_snapshot,
        source=unc,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )


def test_input_root_must_not_be_a_broad_user_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    (home / "Desktop").mkdir(parents=True)
    (home / "Projects").mkdir(parents=True)
    monkeypatch.setattr(entry.Path, "home", staticmethod(lambda: home))
    _write_tree(home / "Projects", TREE_FILES)
    manifest_path = _manifest_file(home / "Projects", _tree_document(home / "Projects"))

    for root in (home, home / "Desktop"):
        broad = _directory_source(home / "Projects", manifest_path)
        broad["root"] = str(root)
        _expect_error(
            "PathRejected",
            import_snapshot,
            source=broad,
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot",
        )
    manifest = import_snapshot(
        source=_directory_source(home / "Projects", manifest_path),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert manifest["entries"]


def test_broad_root_aliases_are_rejected_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    (home / "Projects").mkdir(parents=True)
    _write_tree(home / "Projects", TREE_FILES)
    manifest_path = _manifest_file(home / "Projects", _tree_document(home / "Projects"))
    monkeypatch.setattr(entry.Path, "home", staticmethod(lambda: home))
    direct_root = str(home)
    alias_root = str(home / "child" / "..")
    assert alias_root != direct_root
    for root in (
        direct_root,
        alias_root,
        str(home) + "/./child/..",
        str(home.parent),
        str(home.parent / "sibling" / ".."),
    ):
        broad = _directory_source(home / "Projects", manifest_path)
        broad["root"] = root
        _expect_error(
            "PathRejected",
            import_snapshot,
            source=broad,
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot-alias",
        )
    manifest = import_snapshot(
        source=_directory_source(home / "Projects", manifest_path),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-narrow",
    )
    assert manifest["entries"]


def test_snapshot_output_and_read_reject_parent_component_aliases(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    area = tmp_path / "snapshots"
    area.mkdir()
    manifest = _import_directory(tree, manifest_path, area / "one")
    _expect_error(
        "PathRejected",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(),
        snapshot_root=tmp_path / "skip" / ".." / "snapshots" / "two",
    )
    assert [path.name for path in area.iterdir()] == ["one"]
    _expect_error(
        "PathRejected",
        read_snapshot,
        snapshot_root=tmp_path / "skip" / ".." / "snapshots" / "one",
    )
    assert read_snapshot(snapshot_root=area / "one") == manifest


def test_directory_input_rejects_reparse_and_hard_links(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))

    try:
        winapi = pytest.importorskip("_winapi")
        target = tmp_path / "junction-target"
        target.mkdir()
        winapi.CreateJunction(str(target), str(tree / "junction"))
    except (FileNotFoundError, OSError):
        pytest.skip("junction fixture needs Windows privileges")
    _expect_error(
        "PathRejected",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    os.rmdir(tree / "junction")

    try:
        os.link(tree / "src" / "main.cs", tree / "linked.cs")
    except OSError:
        pytest.skip("hard link fixture is unavailable")
    second_manifest = _manifest_file(tree, _tree_document(tree))
    _expect_error(
        "PathRejected",
        import_snapshot,
        source=_directory_source(tree, second_manifest),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot-two",
    )


def test_snapshot_output_parent_junction_is_rejected_without_target_write(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical-target"
    physical.mkdir()
    package = tmp_path / "input.zip"
    zip_sha = _write_zip(package, {"canary.txt": b"ordinary fixture only\n"})
    link = tmp_path / "junction-parent"
    _make_junction(link, physical)
    try:
        _expect_error(
            "PathRejected",
            import_snapshot,
            source=_zip_source(package, zip_sha),
            policy=_policy(),
            snapshot_root=link / "snapshot",
        )
        assert not (link / "snapshot").exists()
        assert not (link / "snapshot.staging").exists()
        assert list(physical.iterdir()) == []
    finally:
        os.rmdir(link)


def test_read_snapshot_rejects_ancestor_junction(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    real_area = tmp_path / "real-area"
    real_area.mkdir()
    snapshot_root = real_area / "snapshot"
    manifest = _import_directory(tree, manifest_path, snapshot_root)
    link = tmp_path / "mount"
    _make_junction(link, real_area)
    try:
        _expect_error("PathRejected", read_snapshot, snapshot_root=link / "snapshot")
        assert read_snapshot(snapshot_root=snapshot_root) == manifest
        assert link.exists()
    finally:
        os.rmdir(link)


def test_input_root_junction_target_is_rejected_and_plain_chains_still_import(
    tmp_path: Path,
) -> None:
    area = tmp_path / "area"
    tree = area / "tree"
    tree.mkdir(parents=True)
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    link = tmp_path / "tree-link"
    _make_junction(link, tree)
    try:
        linked = _directory_source(tree, manifest_path)
        linked["root"] = str(link)
        _expect_error(
            "PathRejected",
            import_snapshot,
            source=linked,
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot-rejected",
        )
        assert not (tmp_path / "snapshot-rejected").exists()
        manifest = import_snapshot(
            source=_directory_source(tree, manifest_path),
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot-plain",
        )
        assert manifest["entries"]
    finally:
        os.rmdir(link)
