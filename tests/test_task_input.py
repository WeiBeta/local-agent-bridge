"""Offline tests for the task input snapshot importer (task contract package A).

Every fixture is synthetic and lives inside the pytest temporary root: small
Git repositories, in-memory ZIP packages and manifest-adjudicated directories.
No real package, credential, provider, network or upstream CLI is involved.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import stat
import struct
import subprocess
import time
import warnings
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace

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


def _git_commit(root: Path, message: str) -> str:
    _git(
        root,
        "-c",
        "user.email=bridge@example.invalid",
        "-c",
        "user.name=Bridge Test",
        "commit",
        "-q",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD").decode("ascii").strip()


def _git_sha(root: Path, revision: str) -> str:
    return _git(root, "rev-parse", revision).decode("ascii").strip()


def _git_repository(root: Path, files: dict[str, bytes], executable: str | None = None) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    _write_tree(root, files)
    _git(root, "add", "-A")
    if executable is not None:
        _git(root, "update-index", "--chmod=+x", executable)
    return _git_commit(root, "synthetic input")


def _git_blob(root: Path, payload: bytes) -> str:
    return _git(root, "hash-object", "-w", "--stdin", data=payload).decode("ascii").strip()


def _git_tree(root: Path, entries: list[tuple[str, str, str, str]]) -> str:
    listing = "".join(f"{mode} {kind} {sha}\t{name}\n" for mode, kind, sha, name in entries)
    return _git(root, "mktree", data=listing.encode("utf-8")).decode("ascii").strip()


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


def test_git_import_ignores_commit_tree_and_blob_replacements(tmp_path: Path) -> None:
    original = b"class OriginalFrozenInput {}\r\n"
    replaced = b"class DifferentInput {}\r\n"
    for scenario in ("commit", "tree", "blob"):
        repository = tmp_path / f"repository-{scenario}"
        repository.mkdir()
        frozen = _git_repository(repository, {"a.cs": original})
        (repository / "a.cs").write_bytes(replaced)
        _git(repository, "add", "-A")
        diverging = _git_commit(repository, "change the same file")
        source = _git_source(repository, frozen, ["a.cs"])
        before = import_snapshot(
            source=source,
            policy=_policy(),
            snapshot_root=tmp_path / f"before-{scenario}",
        )
        objects = {
            "commit": frozen,
            "tree": _git_sha(repository, f"{frozen}^{{tree}}"),
            "blob": _git_sha(repository, f"{frozen}:a.cs"),
        }
        replacements = {
            "commit": diverging,
            "tree": _git_sha(repository, f"{diverging}^{{tree}}"),
            "blob": _git_sha(repository, f"{diverging}:a.cs"),
        }
        _git(repository, "replace", objects[scenario], replacements[scenario])
        # Plain Git honours the replacement ref, so each fixture is live.
        if scenario == "commit":
            assert _git(repository, "cat-file", "-p", frozen).startswith(
                b"tree " + replacements["tree"].encode("ascii")
            )
        elif scenario == "tree":
            assert replacements["blob"].encode("ascii") in _git(repository, "ls-tree", frozen)
        else:
            assert _git(repository, "cat-file", "blob", objects["blob"]) == replaced
        after = import_snapshot(
            source=source,
            policy=_policy(),
            snapshot_root=tmp_path / f"after-{scenario}",
        )
        assert after == before
        assert after["source"]["identity"] == frozen
        staged = tmp_path / f"after-{scenario}" / "source" / "a.cs"
        assert staged.read_bytes() == original
        _git(repository, "show-ref", "--verify", f"refs/replace/{objects[scenario]}")


def test_git_rejects_link_and_gitlink_entries_from_commits_that_contain_them(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    base_commit = _git_repository(repository, TREE_FILES)
    link_sha = (
        _git(repository, "hash-object", "-w", "--stdin", data=b"target.txt").decode("ascii").strip()
    )
    _git(repository, "update-index", "--add", "--cacheinfo", f"120000,{link_sha},link.txt")
    link_commit = _git_commit(repository, "add a symbolic link entry")
    _git(repository, "update-index", "--add", "--cacheinfo", f"160000,{base_commit},vendor/lib")
    gitlink_commit = _git_commit(repository, "add a gitlink entry")
    link_listing = _git(repository, "ls-tree", "-rz", "--full-tree", link_commit).decode("utf-8")
    assert f"120000 blob {link_sha}\tlink.txt" in link_listing
    gitlink_listing = _git(repository, "ls-tree", "-rz", "--full-tree", gitlink_commit).decode(
        "utf-8"
    )
    assert f"160000 commit {base_commit}\tvendor/lib" in gitlink_listing
    for commit, path in ((link_commit, "link.txt"), (gitlink_commit, "vendor/lib")):
        _expect_error(
            "GitSelectionInvalid",
            import_snapshot,
            source=_git_source(repository, commit, [path]),
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot",
        )


def test_git_rejects_missing_paths_directories_and_short_commit_ids(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commit = _git_repository(repository, TREE_FILES)
    for path in ("missing.cs", "src"):
        _expect_error(
            "GitSelectionInvalid",
            import_snapshot,
            source=_git_source(repository, commit, [path]),
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


def test_git_rejects_implicit_parent_folding_conflicts(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    files = {"caf\u00e9/a.cs": b"nfc parent\n", "cafe\u0301/b.cs": b"decomposed parent\n"}
    commit = _git_repository(repository, files)
    snapshot_root = tmp_path / "snapshot"
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_git_source(repository, commit, sorted(files)),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    assert not snapshot_root.exists()
    assert not snapshot_root.with_name(snapshot_root.name + ".staging").exists()


def test_git_rejects_case_folded_implicit_parents_from_colliding_trees(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    upper = _git_tree(repository, [("100644", "blob", _git_blob(repository, b"upper\n"), "x.cs")])
    lower = _git_tree(repository, [("100644", "blob", _git_blob(repository, b"lower\n"), "y.cs")])
    root = _git_tree(
        repository,
        [("040000", "tree", upper, "A"), ("040000", "tree", lower, "a")],
    )
    commit = (
        _git(
            repository,
            "-c",
            "user.email=bridge@example.invalid",
            "-c",
            "user.name=Bridge Test",
            "commit-tree",
            root,
            "-m",
            "synthetic case-colliding trees",
        )
        .decode("ascii")
        .strip()
    )
    snapshot_root = tmp_path / "snapshot"
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_git_source(repository, commit, ["A/x.cs", "a/y.cs"]),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    assert not snapshot_root.exists()
    assert not snapshot_root.with_name(snapshot_root.name + ".staging").exists()


def test_directory_import_rejects_folding_conflicts_between_real_dirs(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    files = {"caf\u00e9/a.cs": b"nfc parent\n", "cafe\u0301/b.cs": b"decomposed parent\n"}
    _write_tree(tree, files)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    snapshot_root = tmp_path / "snapshot"
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_directory_source(tree, manifest_path),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    assert not snapshot_root.exists()
    assert not snapshot_root.with_name(snapshot_root.name + ".staging").exists()


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


@pytest.mark.parametrize(
    "names",
    [
        ["pkg/caf\u00e9/a.cs", "pkg/cafe\u0301/b.cs"],
        ["pkg/A/x.cs", "pkg/a/y.cs"],
        ["pkg/caf\u00e9/", "pkg/cafe\u0301/b.cs"],
        ["pkg/x/caf\u00e9/deep/a.cs", "pkg/x/cafe\u0301/deep/b.cs"],
        ["pkg/A", "pkg/a/b.cs"],
        ["pkg/A/b/", "pkg/a/x.cs"],
    ],
)
def test_zip_rejects_implicit_parent_folding_conflicts(tmp_path: Path, names: list[str]) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for name in names:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(zipfile.ZipInfo(name), b"" if name.endswith("/") else b"payload\n")
    zip_sha = _sha256(package.read_bytes())
    snapshot_root = tmp_path / "snapshot"
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    # The completed view is checked during planning, before any staging exists.
    assert not snapshot_root.exists()
    assert not snapshot_root.with_name(snapshot_root.name + ".staging").exists()


def test_zip_implicit_parents_import_with_original_unicode(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    files = {
        "caf\u00e9/menu.cs": "// caf\u00e9 source\n".encode(),
        "\u4e2d\u6587/\u8bf4\u660e.md": "\u4e2d\u6587\u5185\u5bb9\n".encode(),
        "plain.cs": b"plain\n",
    }
    with zipfile.ZipFile(package, "w") as archive:
        for name, payload in files.items():
            archive.writestr(zipfile.ZipInfo(name), payload)
    zip_sha = _sha256(package.read_bytes())
    manifest = import_snapshot(
        source=_zip_source(package, zip_sha, strip=None),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert set(_entry_map(manifest)) == {
        "caf\u00e9",
        "caf\u00e9/menu.cs",
        "\u4e2d\u6587",
        "\u4e2d\u6587/\u8bf4\u660e.md",
        "plain.cs",
    }
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


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
    # Contract §7.1 keeps declaration members/original names in UTF-8 order.
    assert manifest["source_paths"] == ["creds/key.pem", "src/main.cs"]
    expected_selection = _sha256(
        _canonical(
            {
                "source_paths": ["creds/key.pem", "src/main.cs"],
                "excluded_paths": [{"path": "creds/key.pem", "reason": "credential material"}],
            }
        )
    )
    assert manifest["source"]["selection_sha256"] == expected_selection
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_directory_exclusion_records_every_excluded_path(tmp_path: Path) -> None:
    files = {
        "keep.cs": b"kept input\n",
        "omit/a.cs": b"omitted source\n",
        "omit/deep/b.cs": b"omitted nested source\n",
        "omit/deep/notes.txt": b"omitted non-source\n",
    }
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, files)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    source = _directory_source(tree, manifest_path)
    exclusion = {"path": "omit", "reason": "explicit subtree"}

    _expect_error(
        "SourcePathUnaccounted",
        import_snapshot,
        source=source,
        policy=_policy(
            source_paths=["omit/ghost.cs"],
            excluded_paths=[exclusion],
        ),
        snapshot_root=tmp_path / "snapshot-ghost",
    )

    policy = _policy(
        source_paths=["keep.cs", "omit/a.cs", "omit/deep/b.cs"],
        excluded_paths=[exclusion],
    )
    manifest = import_snapshot(source=source, policy=policy, snapshot_root=tmp_path / "snapshot")

    assert [entry["path"] for entry in manifest["entries"]] == ["keep.cs"]
    assert manifest["excluded_paths"] == [
        {"path": "omit", "reason": "explicit subtree"},
        {"path": "omit/a.cs", "reason": "explicit subtree"},
        {"path": "omit/deep", "reason": "explicit subtree"},
        {"path": "omit/deep/b.cs", "reason": "explicit subtree"},
        {"path": "omit/deep/notes.txt", "reason": "explicit subtree"},
    ]
    denominator = {entry["path"] for entry in manifest["entries"]} | {
        item["path"] for item in manifest["excluded_paths"]
    }
    assert denominator == set(files) | {"omit", "omit/deep"}
    expected_selection = _sha256(
        _canonical(
            {
                "source_paths": manifest["source_paths"],
                "excluded_paths": manifest["excluded_paths"],
            }
        )
    )
    assert manifest["source"]["selection_sha256"] == expected_selection
    assert not (tmp_path / "snapshot" / "source" / "omit").exists()
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_nested_exclusions_use_the_most_specific_reason(tmp_path: Path) -> None:
    files = {"b/e.cs": b"outer\n", "b/c/d.cs": b"inner\n", "keep.txt": b"keep\n"}
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, files)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    outer = {"path": "b", "reason": "whole subtree"}
    nested = {"path": "b/c", "reason": "nested subtree"}

    for index, order in enumerate(([outer, nested], [nested, outer])):
        manifest = import_snapshot(
            source=_directory_source(tree, manifest_path),
            policy=_policy(excluded_paths=list(order)),
            snapshot_root=tmp_path / f"snapshot-{index}",
        )
        assert manifest["excluded_paths"] == [
            {"path": "b", "reason": "whole subtree"},
            {"path": "b/c", "reason": "nested subtree"},
            {"path": "b/c/d.cs", "reason": "nested subtree"},
            {"path": "b/e.cs", "reason": "whole subtree"},
        ]
        assert [entry["path"] for entry in manifest["entries"]] == ["keep.txt"]


def test_exclusions_stay_within_the_entry_count_ceiling(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, TREE_FILES)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    source = _directory_source(tree, manifest_path)
    excluded = [{"path": "src", "reason": "generated sources"}]

    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=source,
        policy=_policy(excluded_paths=excluded, entry_count_limit=7),
        snapshot_root=tmp_path / "snapshot-tight",
    )
    manifest = import_snapshot(
        source=source,
        policy=_policy(excluded_paths=excluded, entry_count_limit=8),
        snapshot_root=tmp_path / "snapshot-exact",
    )
    assert {entry["path"] for entry in manifest["entries"]} == {
        "AGENTS.md",
        "assets",
        "assets/blob.bin",
    }
    assert [item["path"] for item in manifest["excluded_paths"]] == [
        "src",
        "src/AuthToken.cs",
        "src/main.cs",
        "src/nested",
        "src/nested/util.py",
    ]


def test_zip_exclusion_does_not_invent_implicit_directories(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    sha = _write_zip(package, {"keep.cs": b"keep\n", "x/y.txt": b"omit\n"})
    manifest = import_snapshot(
        source=_zip_source(package, sha),
        policy=_policy(excluded_paths=[{"path": "x", "reason": "dropped folder"}]),
        snapshot_root=tmp_path / "snapshot",
    )
    assert [entry["path"] for entry in manifest["entries"]] == ["keep.cs"]
    assert manifest["excluded_paths"] == [{"path": "x/y.txt", "reason": "dropped folder"}]
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_implicit_parent_conflicts_are_rejected_before_exclusions(tmp_path: Path) -> None:
    package = tmp_path / "input.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(zipfile.ZipInfo("pkg/keep.cs"), b"keep\n")
        archive.writestr(zipfile.ZipInfo("pkg/caf\u00e9/x.cs"), b"omit\n")
        archive.writestr(zipfile.ZipInfo("pkg/cafe\u0301/y.cs"), b"omit\n")
    zip_sha = _sha256(package.read_bytes())
    snapshot_root = tmp_path / "snapshot"
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_zip_source(package, zip_sha),
        policy=_policy(
            excluded_paths=[
                {"path": "caf\u00e9/x.cs", "reason": "dropped"},
                {"path": "cafe\u0301/y.cs", "reason": "dropped"},
            ]
        ),
        snapshot_root=snapshot_root,
    )
    assert not snapshot_root.exists()
    assert not snapshot_root.with_name(snapshot_root.name + ".staging").exists()


def test_git_exclusion_keeps_exact_file_accounting(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commit = _git_repository(repository, {"keep.cs": b"keep\n", "omit.cs": b"omit\n"})
    _expect_error(
        "ExcludedPathUnknown",
        import_snapshot,
        source=_git_source(repository, commit, ["keep.cs", "omit.cs"]),
        policy=_policy(excluded_paths=[{"path": "absent.cs", "reason": "not selected"}]),
        snapshot_root=tmp_path / "snapshot-unknown",
    )
    manifest = import_snapshot(
        source=_git_source(repository, commit, ["keep.cs", "omit.cs"]),
        policy=_policy(
            source_paths=["keep.cs", "omit.cs"],
            excluded_paths=[{"path": "omit.cs", "reason": "reviewed separately"}],
        ),
        snapshot_root=tmp_path / "snapshot",
    )
    assert [entry["path"] for entry in manifest["entries"]] == ["keep.cs"]
    assert manifest["excluded_paths"] == [{"path": "omit.cs", "reason": "reviewed separately"}]
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_read_snapshot_rejects_selection_denominator_drift(tmp_path: Path) -> None:
    files = {"keep.cs": b"kept input\n", "omit/a.cs": b"omitted\n"}
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, files)
    manifest_path = _manifest_file(tree, _tree_document(tree))
    snapshot_root = tmp_path / "snapshot"
    import_snapshot(
        source=_directory_source(tree, manifest_path),
        policy=_policy(
            source_paths=["keep.cs", "omit/a.cs"],
            excluded_paths=[{"path": "omit", "reason": "explicit subtree"}],
        ),
        snapshot_root=snapshot_root,
    )
    original = (snapshot_root / "manifest.json").read_bytes()
    sealed = (snapshot_root / "SEALED").read_bytes()

    def reseal(document: dict[str, object]) -> None:
        document["source"]["selection_sha256"] = _sha256(
            _canonical(
                {
                    "source_paths": document["source_paths"],
                    "excluded_paths": document["excluded_paths"],
                }
            )
        )
        raw = _canonical(document)
        (snapshot_root / "manifest.json").write_bytes(raw)
        (snapshot_root / "SEALED").write_bytes(_sha256(raw).encode("ascii"))

    prefix_only = json.loads(original)
    prefix_only["excluded_paths"] = [{"path": "omit", "reason": "explicit subtree"}]
    reseal(prefix_only)
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot_root)

    overlapped = json.loads(original)
    overlapped["excluded_paths"] = [
        *overlapped["excluded_paths"],
        {"path": "keep.cs", "reason": "late exclusion"},
    ]
    reseal(overlapped)
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot_root)

    covering = json.loads(original)
    covering["excluded_paths"] = [{"path": "keep", "reason": "prefix exclusion"}]
    reseal(covering)
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot_root)

    digest_drift = json.loads(original)
    digest_drift["source"]["selection_sha256"] = "0" * 64
    raw = _canonical(digest_drift)
    (snapshot_root / "manifest.json").write_bytes(raw)
    (snapshot_root / "SEALED").write_bytes(_sha256(raw).encode("ascii"))
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot_root)

    (snapshot_root / "manifest.json").write_bytes(original)
    (snapshot_root / "SEALED").write_bytes(sealed)
    assert read_snapshot(snapshot_root=snapshot_root)


@pytest.mark.parametrize(
    ("first", "second"),
    [("caf\u00e9", "cafe\u0301"), ("A", "a")],
)
def test_read_snapshot_rejects_manifest_folding_conflicts(
    tmp_path: Path, first: str, second: str
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, {"keep.cs": b"kept input\n"})
    manifest_path = _manifest_file(tree, _tree_document(tree))
    snapshot_root = tmp_path / "snapshot"
    import_snapshot(
        source=_directory_source(tree, manifest_path),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    document = json.loads((snapshot_root / "manifest.json").read_bytes())
    colliding = [
        {"path": first, "kind": "directory", "bytes": 0, "sha256": None, "git_mode": None},
        {
            "path": f"{first}/a.cs",
            "kind": "file",
            "bytes": 1,
            "sha256": "0" * 64,
            "git_mode": None,
        },
        {"path": second, "kind": "directory", "bytes": 0, "sha256": None, "git_mode": None},
        {
            "path": f"{second}/b.cs",
            "kind": "file",
            "bytes": 1,
            "sha256": "0" * 64,
            "git_mode": None,
        },
    ]
    document["entries"] = sorted(
        [*document["entries"], *colliding], key=lambda entry: entry["path"].encode("utf-8")
    )
    identity = [
        {key: entry[key] for key in ("path", "kind", "bytes", "sha256")}
        for entry in document["entries"]
    ]
    document["snapshot_id"] = _sha256(_canonical({"contract_version": 1, "entries": identity}))
    raw = _canonical(document)
    (snapshot_root / "manifest.json").write_bytes(raw)
    (snapshot_root / "SEALED").write_bytes(_sha256(raw).encode("ascii"))
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot_root)


def _read_collection_fixture(
    root: Path,
    kept_paths: list[str],
    excluded_paths: list[str],
    *,
    source_paths: list[str] | None = None,
    empty_directories: tuple[str, ...] = (),
) -> dict[str, object]:
    """Write a fresh sealed reader fixture without calling the importer."""

    source_root = root / "source"
    source_root.mkdir(parents=True)
    _write_tree(source_root, dict.fromkeys(kept_paths, b"synthetic\r\n\x00\xff"))
    for path in empty_directories:
        source_root.joinpath(*path.split("/")).mkdir(parents=True, exist_ok=True)
    inventory = _tree_document(source_root)
    entries = [{**item, "git_mode": None} for item in inventory["entries"]]
    declared = kept_paths if source_paths is None else source_paths
    selection = {
        "source_paths": sorted(declared, key=lambda path: path.encode("utf-8")),
        "excluded_paths": [
            {"path": path, "reason": "synthetic exclusion"}
            for path in sorted(excluded_paths, key=lambda path: path.encode("utf-8"))
        ],
    }
    document = {
        "contract_version": 1,
        "snapshot_id": _sha256(_canonical(inventory)),
        "source": {
            "kind": "zip",
            "identity": "1" * 64,
            "selection_sha256": _sha256(_canonical(selection)),
        },
        "entries": entries,
        **selection,
    }
    raw = _canonical(document)
    (root / "manifest.json").write_bytes(raw)
    (root / "SEALED").write_bytes(_sha256(raw).encode("ascii"))
    return document


def test_read_collection_rejects_kept_excluded_samefile(tmp_path: Path) -> None:
    snapshot = tmp_path / "sealed"
    document = _read_collection_fixture(snapshot, ["a.cs", "z.cs"], ["A.cs"])
    assert os.path.samefile(snapshot / "source/a.cs", snapshot / "source/A.cs")
    before = (snapshot / "manifest.json").read_bytes()
    error = _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot)
    assert error.__cause__ is None
    assert before == _canonical(document) == (snapshot / "manifest.json").read_bytes()
    assert (snapshot / "source/a.cs").read_bytes() == b"synthetic\r\n\x00\xff"


@pytest.mark.parametrize(
    ("kept", "excluded"),
    [
        pytest.param(["caf\u00e9.cs"], ["cafe\u0301.cs"], id="cross-leaf-nfc"),
        pytest.param(["Top/a.cs"], ["top"], id="excluded-folded-kept-directory"),
        pytest.param(["caf\u00e9/a.cs"], ["cafe\u0301"], id="excluded-nfc-kept-directory"),
        pytest.param(["Top/deep/a.cs"], ["top/deep"], id="cross-deep-prefix-case"),
        pytest.param(["caf\u00e9/deep/a.cs"], ["cafe\u0301/deep"], id="cross-deep-prefix-nfc"),
        pytest.param(["a.cs"], ["a.cs/child"], id="kept-file-excluded-parent"),
        pytest.param(["a.cs"], ["A.cs/child"], id="kept-file-folded-excluded-parent"),
        pytest.param(["caf\u00e9.cs"], ["cafe\u0301.cs/child"], id="kept-file-nfc-excluded-parent"),
        pytest.param(["Top/a.cs"], ["top/b.cs"], id="cross-implicit-parent-case"),
        pytest.param(["caf\u00e9/a.cs"], ["cafe\u0301/b.cs"], id="cross-implicit-parent-nfc"),
        pytest.param(["Top/deep/a.cs"], ["top/deep/b.cs"], id="cross-deep-parent-case"),
        pytest.param(["caf\u00e9/deep/a.cs"], ["cafe\u0301/deep/b.cs"], id="cross-deep-parent-nfc"),
        pytest.param([], ["A.cs", "a.cs"], id="excluded-leaf-case"),
        pytest.param([], ["caf\u00e9.cs", "cafe\u0301.cs"], id="excluded-leaf-nfc"),
        pytest.param([], ["Top", "top/a.cs"], id="excluded-explicit-implicit-parent-case"),
        pytest.param(
            [], ["caf\u00e9", "cafe\u0301/a.cs"], id="excluded-explicit-implicit-parent-nfc"
        ),
        pytest.param([], ["Top/a.cs", "top/b.cs"], id="excluded-implicit-parent-case"),
        pytest.param([], ["caf\u00e9/a.cs", "cafe\u0301/b.cs"], id="excluded-implicit-parent-nfc"),
        pytest.param([], ["Top/deep/a.cs", "top/deep/b.cs"], id="excluded-deep-parent-case"),
        pytest.param(
            [], ["root/Caf\u00e9/a.cs", "root/Cafe\u0301/b.cs"], id="excluded-inner-parent-nfc"
        ),
    ],
)
def test_read_collection_rejects_conflicting_path_identities(
    tmp_path: Path, kept: list[str], excluded: list[str]
) -> None:
    snapshot = tmp_path / "sealed"
    document = _read_collection_fixture(snapshot, kept, excluded)
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot)
    assert (snapshot / "manifest.json").read_bytes() == _canonical(document)
    assert (snapshot / "SEALED").read_bytes() == _sha256(_canonical(document)).encode("ascii")


@pytest.mark.parametrize(
    ("kept", "excluded", "empty_directories"),
    [
        pytest.param([], ["omit", "omit/a.cs"], (), id="explicit-excluded-parent-child"),
        pytest.param(
            [], ["omit", "omit/deep", "omit/deep/a.cs"], (), id="nested-excluded-directories"
        ),
        pytest.param([], ["omit/a.cs", "omit/b.cs"], (), id="shared-implicit-excluded-parent"),
        pytest.param(["src/a.cs"], ["src/b.cs"], (), id="kept-directory-excluded-child"),
        pytest.param(
            ["src/a.cs"], ["src/deep", "src/deep/b.cs"], (), id="kept-parent-excluded-subtree"
        ),
        pytest.param(["Top/a.cs"], ["Other/b.cs"], (), id="different-parent-paths"),
        pytest.param([], ["a", "ab/child"], (), id="component-boundary"),
        pytest.param(["cafe\u0301/a.cs"], ["cafe\u0301/b.cs"], (), id="preserved-original-nfd"),
        pytest.param(["\U0001f600/a.cs"], ["\U0001f600/b.cs"], (), id="preserved-non-bmp"),
        pytest.param([], ["omit"], ("kept",), id="empty-directory-and-exclusion"),
        pytest.param([], ["kept/child"], ("kept",), id="empty-kept-parent-excluded-child"),
        pytest.param(["a.cs"], ["omit", "omit/a.cs"], (), id="excluded-child-kind-unknown"),
        pytest.param([], [], (), id="empty-collection"),
    ],
)
def test_read_collection_preserves_valid_exclusion_combinations(
    tmp_path: Path, kept: list[str], excluded: list[str], empty_directories: tuple[str, ...]
) -> None:
    snapshot = tmp_path / "sealed"
    # Explicitly declare excluded leaves too: they stay in the source denominator.
    declared = kept + [path for path in excluded if path.endswith(".cs")]
    document = _read_collection_fixture(
        snapshot, kept, excluded, source_paths=declared, empty_directories=empty_directories
    )
    before = (snapshot / "manifest.json").read_bytes()
    actual = read_snapshot(snapshot_root=snapshot)
    assert actual == document
    assert actual["source_paths"] == sorted(declared, key=lambda path: path.encode("utf-8"))
    assert len(actual["excluded_paths"]) == len(excluded)
    assert len({item["path"] for item in actual["entries"] + actual["excluded_paths"]}) == (
        len(actual["entries"]) + len(excluded)
    )
    assert before == _canonical(actual) == (snapshot / "manifest.json").read_bytes()


@pytest.mark.parametrize(
    ("kept", "excluded", "declared"),
    [
        pytest.param(["a.cs"], [], "A.cs", id="kept-case-alias"),
        pytest.param(["caf\u00e9.cs"], [], "cafe\u0301.cs", id="kept-nfc-alias"),
        pytest.param([], ["a.cs"], "A.cs", id="excluded-case-alias"),
        pytest.param([], ["caf\u00e9.cs"], "cafe\u0301.cs", id="excluded-nfc-alias"),
        pytest.param([], ["omit"], "omit/a.cs", id="excluded-prefix-is-not-exact-leaf"),
    ],
)
def test_read_collection_source_declarations_require_exact_membership(
    tmp_path: Path, kept: list[str], excluded: list[str], declared: str
) -> None:
    snapshot = tmp_path / "sealed"
    document = _read_collection_fixture(snapshot, kept, excluded, source_paths=[declared])
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot)
    assert (snapshot / "manifest.json").read_bytes() == _canonical(document)


READ_IDENTITY_KINDS = ("git", "zip", "directory")


def _identity_fixture(root: Path, kind: str, identity: object) -> dict[str, object]:
    """Write a fresh sealed reader fixture with a chosen source identity."""

    source_root = root / "source"
    source_root.mkdir(parents=True)
    _write_tree(source_root, {"a.cs": b"kept input\r\n\x00", "z.cs": b"\xff binary\r\n"})
    inventory = _tree_document(source_root)
    entries = [{**item, "git_mode": None} for item in inventory["entries"]]
    selection = {"source_paths": ["a.cs", "z.cs"], "excluded_paths": []}
    document = {
        "contract_version": 1,
        "snapshot_id": _sha256(_canonical(inventory)),
        "source": {
            "kind": kind,
            "identity": identity,
            "selection_sha256": _sha256(_canonical(selection)),
        },
        "entries": entries,
        **selection,
    }
    raw = _canonical(document)
    (root / "manifest.json").write_bytes(raw)
    (root / "SEALED").write_bytes(_sha256(raw).encode("ascii"))
    return document


@pytest.mark.parametrize("kind", READ_IDENTITY_KINDS)
def test_read_snapshot_accepts_kind_specific_source_identities(tmp_path: Path, kind: str) -> None:
    snapshot = tmp_path / "sealed"
    identity = "1c0ffee7" * 5 if kind == "git" else "0f9a" * 16
    document = _identity_fixture(snapshot, kind, identity)
    before = (snapshot / "manifest.json").read_bytes()
    actual = read_snapshot(snapshot_root=snapshot)
    assert actual == document
    assert actual["source"]["kind"] == kind
    assert actual["source"]["identity"] == identity
    assert actual["source_paths"] == ["a.cs", "z.cs"]
    assert before == _canonical(actual) == (snapshot / "manifest.json").read_bytes()


@pytest.mark.parametrize(
    ("kind", "identity"),
    [
        pytest.param("zip", "1" * 40, id="zip-40-characters"),
        pytest.param("directory", "1" * 40, id="directory-40-characters"),
        pytest.param("git", "0" * 64, id="git-64-characters"),
        pytest.param("zip", "0" * 63, id="zip-63-characters"),
        pytest.param("directory", "0" * 65, id="directory-65-characters"),
        pytest.param("git", "0" * 39, id="git-39-characters"),
        pytest.param("git", "0" * 41, id="git-41-characters"),
        pytest.param("zip", "g" * 64, id="zip-non-hex"),
        pytest.param("directory", "z" * 64, id="directory-non-hex"),
        pytest.param("git", "z" * 40, id="git-non-hex"),
        pytest.param("zip", "A" * 64, id="zip-uppercase"),
        pytest.param("directory", "F" * 64, id="directory-uppercase"),
        pytest.param("git", "F" * 40, id="git-uppercase"),
        pytest.param("zip", "0" * 63 + " ", id="zip-trailing-space"),
        pytest.param("git", " " + "0" * 39, id="git-leading-space"),
        pytest.param("zip", "", id="zip-empty"),
        pytest.param("git", "", id="git-empty"),
        pytest.param("directory", None, id="directory-null"),
        pytest.param("zip", 1, id="zip-integer"),
        pytest.param("git", ["0" * 40], id="git-list"),
        pytest.param("directory", {"sha256": "0" * 64}, id="directory-dict"),
        pytest.param("zip", True, id="zip-boolean"),
        pytest.param("git", 4.5, id="git-float"),
    ],
)
def test_read_snapshot_rejects_kind_mismatched_source_identities(
    tmp_path: Path, kind: str, identity: object
) -> None:
    snapshot = tmp_path / "sealed"
    document = _identity_fixture(snapshot, kind, identity)
    error = _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot)
    assert error.__cause__ is None
    assert (snapshot / "manifest.json").read_bytes() == _canonical(document)
    assert (snapshot / "SEALED").read_bytes() == _sha256(_canonical(document)).encode("ascii")


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


@pytest.fixture
def absolute_path_case(
    tmp_path: Path, entry_kind: str, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    """Freeze ordinary inputs for one public path field, with a synthetic home."""

    home = tmp_path / "profile"
    monkeypatch.setattr(entry.Path, "home", staticmethod(lambda: home))
    tree = tmp_path / "输入" / "tree"
    tree.mkdir(parents=True)
    files = {"canary.txt": b"ordinary fixture\n", "src/说明.cs": b"// synthetic\r\n"}
    _write_tree(tree, files)
    inventory = _manifest_file(tree, _tree_document(tree))
    source = _directory_source(tree, inventory)
    package = tmp_path / "输入" / "ordinary.zip"
    package_hash = _write_zip(package, files)
    output = tmp_path / "result"
    field = "root"
    value = tree
    if entry_kind == "git":
        repository = tmp_path / "输入" / "repo"
        repository.mkdir()
        commit = _git_repository(repository, files)
        source = _git_source(repository, commit, sorted(files))
        value = repository
    elif entry_kind == "zip":
        source = _zip_source(package, package_hash)
        field = "path"
        value = package
    elif entry_kind == "manifest":
        field = "manifest_path"
        value = inventory
    elif entry_kind == "output":
        value = output
    elif entry_kind == "read":
        value = tmp_path / "输入" / "sealed"
        import_snapshot(source=source, policy=_policy(), snapshot_root=value)
    return {"source": source, "field": field, "value": value, "output": output, "home": home}


def _call_absolute_entry(entry_kind: str, case: dict[str, object], value: str) -> dict[str, object]:
    if entry_kind == "read":
        return read_snapshot(snapshot_root=Path(value))
    source = dict(case["source"])
    snapshot_root = case["output"]
    if entry_kind == "output":
        snapshot_root = Path(value)
    else:
        source[case["field"]] = value
    return import_snapshot(source=source, policy=_policy(), snapshot_root=snapshot_root)


@pytest.mark.parametrize("entry_kind", ["git", "directory", "zip", "manifest", "output", "read"])
@pytest.mark.parametrize("spelling", ["plain", "case_separators", "unicode"])
def test_absolute_entries_preserve_ordinary_paths(
    entry_kind: str, spelling: str, absolute_path_case: dict[str, object]
) -> None:
    value = str(absolute_path_case["value"])
    if spelling == "case_separators":
        value = value.swapcase().replace("\\", "/") + "/" * (entry_kind in {"git", "directory"})
    elif spelling == "unicode":
        assert "输入" in value or entry_kind == "output"
        if entry_kind == "output":
            value += "中文"
    manifest = _call_absolute_entry(entry_kind, absolute_path_case, value)
    assert {item["path"] for item in manifest["entries"] if item["kind"] == "file"} == {
        "canary.txt",
        "src/说明.cs",
    }
    snapshot = Path(value) if entry_kind in {"read", "output"} else absolute_path_case["output"]
    assert (snapshot / "source" / "src" / "说明.cs").read_bytes() == b"// synthetic\r\n"


def _invalid_absolute_spelling(path: Path, variant: str) -> str:
    if variant == "tail_dot":
        return str(path) + "."
    if variant == "tail_space":
        return str(path) + " "
    if variant == "ancestor_dot":
        return str(path.parent) + ".\\" + path.name
    if variant == "ancestor_space":
        return str(path.parent) + " \\" + path.name
    if variant == "parent":
        return str(path.parent / "child" / ".." / path.name)
    if variant == "dot":
        return str(path.parent) + "/./" + path.name
    if variant == "ads":
        return str(path) + ":stream"
    if variant == "control":
        return str(path) + "\x01"
    if variant == "surrogate":
        return str(path) + "\ud800"
    if variant == "unc":
        return r"\\server\share\ordinary"
    if variant == "extended":
        return "\\\\?\\" + str(path)
    if variant == "device":
        return "\\\\.\\" + str(path)
    return str(path.parent / variant)


@pytest.mark.parametrize("entry_kind", ["git", "directory", "zip", "manifest", "output", "read"])
@pytest.mark.parametrize(
    "variant",
    [
        "tail_dot",
        "tail_space",
        "ancestor_dot",
        "ancestor_space",
        "parent",
        "ads",
        "control",
        "surrogate",
        "unc",
        "extended",
        "device",
        "NUL.txt",
        "CONIN$",
        "COM¹.txt",
        "LPT³",
        "bad?name",
    ],
)
def test_absolute_entries_reject_ambiguous_names_before_content_io(
    entry_kind: str,
    variant: str,
    absolute_path_case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _invalid_absolute_spelling(absolute_path_case["value"], variant)

    def no_content_read(*arguments, **keywords):
        pytest.fail("an invalid path reached source content I/O")

    # A manifest-field case validates its ordinary directory first, but must
    # reject the manifest spelling before any file bytes/tree/Git are read.
    monkeypatch.setattr(entry, "_hash_file", no_content_read)
    monkeypatch.setattr(entry, "_scan_tree", no_content_read)
    monkeypatch.setattr(entry, "_git_text", no_content_read)
    monkeypatch.setattr(entry.Path, "read_bytes", no_content_read)
    _expect_error("PathRejected", _call_absolute_entry, entry_kind, absolute_path_case, value)
    assert not absolute_path_case["output"].exists()


@pytest.mark.parametrize("entry_kind", ["git", "directory", "zip", "manifest"])
def test_string_absolute_entries_reject_raw_dot(
    entry_kind: str, absolute_path_case: dict[str, object]
) -> None:
    value = _invalid_absolute_spelling(absolute_path_case["value"], "dot")
    _expect_error("PathRejected", _call_absolute_entry, entry_kind, absolute_path_case, value)


@pytest.mark.parametrize("entry_kind", ["output", "read"])
def test_path_absolute_entries_acknowledge_folded_dot(
    entry_kind: str, absolute_path_case: dict[str, object]
) -> None:
    ordinary = absolute_path_case["value"]
    raw = _invalid_absolute_spelling(ordinary, "dot")
    assert Path(raw) == ordinary
    assert _call_absolute_entry(entry_kind, absolute_path_case, raw)["entries"]


@pytest.mark.parametrize("entry_kind", ["git", "directory", "zip", "manifest", "output", "read"])
def test_absolute_entries_reject_original_junction_chain(
    entry_kind: str,
    absolute_path_case: dict[str, object],
    tmp_path: Path,
) -> None:
    ordinary = absolute_path_case["value"]
    link = tmp_path / "parent-link"
    _make_junction(link, ordinary.parent)
    _expect_error(
        "PathRejected",
        _call_absolute_entry,
        entry_kind,
        absolute_path_case,
        str(link / ordinary.name),
    )
    assert not absolute_path_case["output"].exists()


@pytest.mark.parametrize("entry_kind", ["git", "directory", "read"])
def test_directory_identity_rejects_a_real_samefile_forbidden_root(
    entry_kind: str,
    absolute_path_case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary = absolute_path_case["value"]
    forbidden_alias = Path(str(ordinary) + ".")
    assert ordinary != forbidden_alias
    assert os.path.samefile(ordinary, forbidden_alias)
    # Only the trusted synthetic home spelling is substituted. Candidate path,
    # stat and samestat use real ordinary Windows metadata, with no mapping.
    monkeypatch.setattr(entry.Path, "home", staticmethod(lambda: forbidden_alias))
    _expect_error(
        "PathRejected", _call_absolute_entry, entry_kind, absolute_path_case, str(ordinary)
    )


@pytest.mark.parametrize("entry_kind", ["git", "directory", "read"])
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_directory_identity_io_errors_fail_closed_with_cause(
    entry_kind: str,
    error_type,
    absolute_path_case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stat = entry.Path.stat
    synthetic_home = absolute_path_case["home"]
    injected = error_type("synthetic metadata failure")

    def checked_stat(path, *arguments, **keywords):
        if path == synthetic_home:
            raise injected
        return original_stat(path, *arguments, **keywords)

    monkeypatch.setattr(entry.Path, "stat", checked_stat)
    error = _expect_error(
        "IoFailed",
        _call_absolute_entry,
        entry_kind,
        absolute_path_case,
        str(absolute_path_case["value"]),
    )
    assert error.__cause__ is injected


def test_plain_chain_is_checked_before_forbidden_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    link = tmp_path / "root-link"
    _make_junction(link, tree)

    def identity_not_reached(*arguments, **keywords):
        pytest.fail("identity comparison ran before reparse refusal")

    monkeypatch.setattr(entry, "_reject_broad_root", identity_not_reached)
    _expect_error("PathRejected", entry._validate_absolute_directory, str(link), label="fixture")


def test_generated_writes_reject_ambiguous_leafs_and_skip_failure_labels(tmp_path: Path) -> None:
    ordinary = tmp_path / "area"
    ordinary.mkdir()
    alias = Path(str(ordinary) + ".")
    _expect_error(
        "PathRejected",
        entry._write_exclusive,
        alias / "metadata",
        b"ordinary",
        entry._Deadline.starting_now(60),
    )
    entry._write_failure_label(alias, "SyntheticFailure")
    assert list(ordinary.iterdir()) == []


@pytest.mark.parametrize("entry_kind", ["git", "directory", "zip", "manifest", "output", "read"])
@pytest.mark.parametrize("value", ["relative", "C:relative", r"\rooted"])
def test_absolute_entries_require_local_drive_absolute_form(
    entry_kind: str, value: str, absolute_path_case: dict[str, object]
) -> None:
    expected = "SnapshotRootInvalid" if entry_kind in {"output", "read"} else "InvalidSource"
    _expect_error(expected, _call_absolute_entry, entry_kind, absolute_path_case, value)


@pytest.mark.parametrize("entry_kind", ["git", "directory", "read"])
def test_missing_forbidden_roots_allow_an_ordinary_narrow_root(
    entry_kind: str, absolute_path_case: dict[str, object]
) -> None:
    assert not absolute_path_case["home"].exists()
    assert _call_absolute_entry(entry_kind, absolute_path_case, str(absolute_path_case["value"]))[
        "entries"
    ]


def test_documents_scratch_descendants_remain_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profile"
    scratch = home / "Documents" / "Scratch"
    tree = scratch / "project"
    tree.mkdir(parents=True)
    _write_tree(tree, {"ordinary.cs": b"// ordinary\n"})
    inventory = _manifest_file(tree, _tree_document(tree))
    monkeypatch.setattr(entry.Path, "home", staticmethod(lambda: home))
    snapshot = scratch / "result"
    manifest = _import_directory(tree, inventory, snapshot)
    assert read_snapshot(snapshot_root=snapshot) == manifest


def test_publish_rechecks_output_before_rename_and_labels_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "input.zip"
    digest = _write_zip(package, {"ordinary.txt": b"ordinary"})
    snapshot = tmp_path / "snapshot"
    staging = tmp_path / "snapshot.staging"
    original_reparse = entry._is_reparse

    def injected_late_reparse(path):
        # Inject only the final output observation after staging metadata is
        # complete. This tests guard order, not a real concurrent OS mutation.
        if path == snapshot and (staging / "SEALED").exists():
            return True
        return original_reparse(path)

    def rename_not_reached(*arguments, **keywords):
        pytest.fail("publish rename ran after the output became unsafe")

    monkeypatch.setattr(entry, "_is_reparse", injected_late_reparse)
    monkeypatch.setattr(entry.os, "rename", rename_not_reached)
    _expect_error(
        "PathRejected",
        import_snapshot,
        source=_zip_source(package, digest),
        policy=_policy(),
        snapshot_root=snapshot,
    )
    assert not snapshot.exists()
    assert (staging / "IMPORT-FAILED").read_bytes() == ("PathRejected" + os.linesep).encode("ascii")


def _deadline_source(tmp_path: Path, kind: str) -> dict[str, object]:
    files = {"src/a.cs": b"a", "empty.dat": b""}
    if kind == "zip":
        package = tmp_path / "input.zip"
        return _zip_source(package, _write_zip(package, files))
    root = tmp_path / "input"
    root.mkdir()
    if kind == "git":
        commit = _git_repository(root, files)
        return _git_source(root, commit, sorted(files))
    _write_tree(root, files)
    inventory = _manifest_file(root, _tree_document(root))
    return _directory_source(root, inventory)


class _ImportClock:
    """A controlled importer clock; subprocess and pytest keep real time."""

    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now

    def expire(self) -> None:
        self.now += 1.0


@pytest.mark.parametrize("delay_seconds", [0.0, 1.2], ids=["no-delay", "bounded-real-delay"])
def test_metadata_deadline_uses_real_elapsed_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delay_seconds: float
) -> None:
    source = _deadline_source(tmp_path, "directory")
    snapshot = tmp_path / "snapshot"
    staging = tmp_path / "snapshot.staging"
    original_write = entry._write_exclusive
    original_rename = entry.os.rename
    observation: dict[str, object] = {"injected_delay_seconds": delay_seconds}

    def delayed_metadata(target, raw, deadline):
        if target.name == "manifest.json":
            observation["expires_at"] = deadline.expires_at
            observation["delay_started_at"] = time.monotonic()
            # This is a deliberate bounded delay, not a naturally slow disk.
            time.sleep(delay_seconds)
            observation["delay_finished_at"] = time.monotonic()
        return original_write(target, raw, deadline)

    def observed_rename(old, new):
        observation["rename_started_at"] = time.monotonic()
        return original_rename(old, new)

    monkeypatch.setattr(entry, "_write_exclusive", delayed_metadata)
    monkeypatch.setattr(entry.os, "rename", observed_rename)
    started = time.monotonic()
    if delay_seconds:
        _expect_error(
            "DeadlineExceeded",
            import_snapshot,
            source=source,
            policy=_policy(deadline_seconds=1),
            snapshot_root=snapshot,
        )
        observation["error"] = "DeadlineExceeded"
        assert not snapshot.exists()
        assert not (staging / "manifest.json").exists()
        assert not (staging / "SEALED").exists()
        assert (staging / "source/src/a.cs").read_bytes() == b"a"
        assert (staging / "IMPORT-FAILED").read_text() == "DeadlineExceeded\n"
        assert "rename_started_at" not in observation
        assert observation["delay_started_at"] < observation["expires_at"]
        assert observation["delay_finished_at"] >= observation["expires_at"]
    else:
        manifest = import_snapshot(
            source=source, policy=_policy(deadline_seconds=1), snapshot_root=snapshot
        )
        observation["error"] = None
        assert read_snapshot(snapshot_root=snapshot) == manifest
        assert observation["rename_started_at"] < observation["expires_at"]
        assert not staging.exists()
    observation["elapsed_seconds"] = time.monotonic() - started
    (tmp_path / "metadata-deadline-observation.json").write_bytes(_canonical(observation))


@pytest.mark.parametrize(
    ("stage", "kind", "failure_root"),
    [
        ("root-validation", "directory", None),
        ("git-type", "git", None),
        ("git-tree", "git", None),
        ("git-listing-parse", "git", None),
        ("git-size", "git", None),
        ("git-blob", "git", "staging"),
        ("zip-hash", "zip", None),
        ("zip-open", "zip", None),
        ("zip-member-scan", "zip", None),
        ("manifest-read", "directory", None),
        ("manifest-hash", "directory", None),
        ("manifest-parse", "directory", None),
        ("manifest-entries", "directory", None),
        ("selection", "directory", None),
        ("selection-digest", "directory", None),
        ("staging-create", "directory", "staging"),
        ("source-create", "directory", "staging"),
        ("directory-create", "directory", "staging"),
        ("snapshot-identity", "directory", "staging"),
        ("manifest-serialize", "directory", "staging"),
        ("manifest-after-write", "directory", "staging"),
        ("seal-after-write", "directory", "staging"),
        ("rename-precheck", "directory", "staging"),
        ("zip-close", "zip", "staging"),
    ],
)
def test_import_stages_share_one_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, kind: str, failure_root: str | None
) -> None:
    source = _deadline_source(tmp_path, kind)
    snapshot = tmp_path / "snapshot"
    staging = tmp_path / "snapshot.staging"
    clock = _ImportClock()
    monkeypatch.setattr(entry, "time", clock)
    injected = False

    def expire_once() -> None:
        nonlocal injected
        assert not injected, f"stage injection repeated: {stage}"
        injected = True
        clock.expire()

    def delay_result(owner, name, matches):
        original = getattr(owner, name)

        def delayed(*arguments, **keywords):
            result = original(*arguments, **keywords)
            if not injected and matches(arguments, keywords):
                expire_once()
            return result

        monkeypatch.setattr(owner, name, delayed)

    if stage.startswith("git-") and stage != "git-listing-parse":
        operation = {
            "git-type": ["cat-file", "-t"],
            "git-tree": ["ls-tree", "-rz"],
            "git-size": ["cat-file", "-s"],
            "git-blob": ["cat-file", "blob"],
        }[stage]
        delay_result(entry.subprocess, "run", lambda args, kw: args[0][4:6] == operation)
    elif stage == "git-listing-parse":
        delay_result(entry, "_parse_git_listing", lambda args, kw: True)
    elif stage == "root-validation":
        delay_result(entry, "_validate_absolute_directory", lambda args, kw: True)
    elif stage == "zip-hash":
        delay_result(entry, "_hash_file", lambda args, kw: args[0] == Path(source["path"]))
    elif stage == "zip-open":
        delay_result(entry.zipfile.ZipFile, "__init__", lambda args, kw: True)
    elif stage == "zip-member-scan":
        delay_result(entry, "_zip_entry_name", lambda args, kw: True)
    elif stage == "manifest-read":
        delay_result(
            entry.Path, "read_bytes", lambda args, kw: args[0] == Path(source["manifest_path"])
        )
    elif stage == "manifest-hash":
        delay_result(entry, "_sha256_bytes", lambda args, kw: True)
    elif stage == "manifest-parse":
        delay_result(
            entry,
            "decode_strict_json_bytes",
            lambda args, kw: kw.get("label") == "directory manifest",
        )
    elif stage == "manifest-entries":
        delay_result(
            entry, "_validate_relative_path", lambda args, kw: kw.get("label") == "manifest entry"
        )
    elif stage == "selection":
        delay_result(entry, "_most_specific_exclusion", lambda args, kw: True)
    elif stage == "selection-digest":
        delay_result(entry, "_selection_digest", lambda args, kw: True)
    elif stage.endswith("-create"):
        target = {
            "staging-create": staging,
            "source-create": staging / "source",
            "directory-create": staging / "source/src",
        }[stage]
        delay_result(entry.os, "mkdir", lambda args, kw: args[0] == target)
    elif stage in {"snapshot-identity", "manifest-serialize"}:
        expected_key = "entries" if stage == "snapshot-identity" else "snapshot_id"
        delay_result(
            entry,
            "_canonical_json_bytes",
            lambda args, kw: (
                isinstance(args[0], dict)
                and expected_key in args[0]
                and ("snapshot_id" in args[0]) == (stage == "manifest-serialize")
            ),
        )
    elif stage in {"manifest-after-write", "seal-after-write"}:
        name = "manifest.json" if stage == "manifest-after-write" else "SEALED"
        delay_result(entry, "_write_exclusive", lambda args, kw: args[0].name == name)
    elif stage == "rename-precheck":
        delay_result(
            entry,
            "_assert_plain_target",
            lambda args, kw: args[0] == snapshot and (staging / "SEALED").exists(),
        )
    elif stage == "zip-close":
        delay_result(entry.zipfile.ZipFile, "close", lambda args, kw: staging.exists())
    else:
        pytest.fail(f"missing stage injection: {stage}")

    _expect_error(
        "DeadlineExceeded",
        import_snapshot,
        source=source,
        policy=_policy(deadline_seconds=1),
        snapshot_root=snapshot,
    )
    assert injected, f"stage was not reached: {stage}"
    if failure_root is None:
        assert not staging.exists()
        assert not snapshot.exists()
    else:
        assert failure_root == "staging"
        assert staging.is_dir()
        assert (staging / "IMPORT-FAILED").read_text() == "DeadlineExceeded\n"
        assert not snapshot.exists()


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
def test_one_second_import_without_delay_preserves_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    source = _deadline_source(tmp_path, kind)
    monkeypatch.setattr(entry, "time", _ImportClock())
    snapshot = tmp_path / "snapshot"
    manifest = import_snapshot(
        source=source, policy=_policy(deadline_seconds=1), snapshot_root=snapshot
    )
    assert read_snapshot(snapshot_root=snapshot) == manifest
    assert (snapshot / "source/src/a.cs").read_bytes() == b"a"
    assert (snapshot / "source/empty.dat").read_bytes() == b""
    assert not (snapshot / "IMPORT-FAILED").exists()


def test_git_timeout_is_remaining_budget_without_a_minimum_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _ImportClock()
    monkeypatch.setattr(entry, "time", clock)
    timeout_values: list[float] = []

    def completed_git(arguments, **keywords):
        timeout_values.append(keywords["timeout"])
        return subprocess.CompletedProcess(arguments, 0, stdout=b"original", stderr=b"")

    monkeypatch.setattr(entry.shutil, "which", lambda name: "synthetic-git")
    monkeypatch.setattr(entry.subprocess, "run", completed_git)
    deadline = entry._Deadline(100.025)
    assert entry._git_bytes(tmp_path, ["cat-file", "-t", "synthetic"], deadline) == b"original"
    assert len(timeout_values) == 1
    assert timeout_values[0] == pytest.approx(0.025)
    clock.now = deadline.expires_at
    _expect_error("DeadlineExceeded", entry._git_bytes, tmp_path, ["unused"], deadline)
    assert len(timeout_values) == 1, "expired Git operation was launched"


def test_git_subprocess_timeout_keeps_the_public_deadline_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _deadline_source(tmp_path, "git")

    def timeout_git(arguments, **keywords):
        raise subprocess.TimeoutExpired(arguments, keywords["timeout"])

    monkeypatch.setattr(entry.subprocess, "run", timeout_git)
    _expect_error(
        "DeadlineExceeded",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot.staging").exists()


@pytest.mark.parametrize(
    ("operation", "kind", "failure_root"),
    [
        ("package-read", "zip", None),
        ("directory-hash-read", "directory", None),
        ("copy-read", "directory", "staging"),
        ("copy-empty-eof", "directory", "staging"),
        ("zip-read", "zip", "staging"),
        ("zip-empty-eof", "zip", "staging"),
        ("final-hash-read", "directory", "staging"),
        ("file-write", "directory", "staging"),
        ("file-close", "directory", "staging"),
        ("metadata-write", "directory", "staging"),
        ("metadata-close", "directory", "staging"),
        ("seal-write", "directory", "staging"),
        ("seal-close", "directory", "staging"),
    ],
)
def test_blocking_io_is_checked_after_return_including_eof_and_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    kind: str,
    failure_root: str | None,
) -> None:
    source = _deadline_source(tmp_path, kind)
    snapshot = tmp_path / "snapshot"
    staging = tmp_path / "snapshot.staging"
    clock = _ImportClock()
    monkeypatch.setattr(entry, "time", clock)
    injected = False

    def expire_once() -> None:
        nonlocal injected
        assert not injected
        injected = True
        clock.expire()

    class TimedHandle:
        def __init__(self, handle, action: str) -> None:
            self.handle = handle
            self.action = action

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *arguments):
            result = self.handle.__exit__(*arguments)
            if self.action == "close" and not injected:
                expire_once()
            return result

        def read(self, *arguments):
            raw = self.handle.read(*arguments)
            if not injected and (self.action == "read" or (self.action == "empty-eof" and not raw)):
                expire_once()
            return raw

        def write(self, raw):
            result = self.handle.write(raw)
            if self.action == "write" and not injected:
                expire_once()
            return result

        def flush(self):
            return self.handle.flush()

    if operation in {"zip-read", "zip-empty-eof"}:
        original_read = entry.zipfile.ZipExtFile.read

        def zip_read(handle, *arguments):
            raw = original_read(handle, *arguments)
            if not injected and (
                (operation == "zip-read" and not handle.name.endswith("/"))
                or (handle.name.endswith("empty.dat") and not raw)
            ):
                expire_once()
            return raw

        monkeypatch.setattr(entry.zipfile.ZipExtFile, "read", zip_read)
    elif operation.endswith("-read") or operation == "copy-empty-eof":
        original_open = entry.Path.open
        root = Path(source["root"]) if kind == "directory" else None
        target = {
            "package-read": Path(source.get("path", "unused")),
            "directory-hash-read": root / "src/a.cs" if root else None,
            "copy-read": root / "src/a.cs" if root else None,
            "copy-empty-eof": root / "empty.dat" if root else None,
            "final-hash-read": staging / "source/src/a.cs",
        }[operation]
        open_count = 0
        expected_open = 2 if operation in {"copy-read", "copy-empty-eof"} else 1

        def path_open(path, mode="r", *arguments, **keywords):
            nonlocal open_count
            handle = original_open(path, mode, *arguments, **keywords)
            if path == target and mode == "rb" and not injected:
                open_count += 1
                if open_count == expected_open:
                    return TimedHandle(
                        handle, "empty-eof" if operation == "copy-empty-eof" else "read"
                    )
            return handle

        monkeypatch.setattr(entry.Path, "open", path_open)
    else:
        original_fdopen = entry.os.fdopen
        write_count = 0
        expected_write = {
            "file-write": 2,
            "file-close": 1,
            "metadata-write": 3,
            "metadata-close": 3,
            "seal-write": 4,
            "seal-close": 4,
        }[operation]

        def fdopen(descriptor, mode, *arguments, **keywords):
            nonlocal write_count
            handle = original_fdopen(descriptor, mode, *arguments, **keywords)
            if mode == "wb":
                write_count += 1
                if write_count == expected_write:
                    return TimedHandle(handle, "close" if operation.endswith("close") else "write")
            return handle

        monkeypatch.setattr(entry.os, "fdopen", fdopen)

    _expect_error(
        "DeadlineExceeded",
        import_snapshot,
        source=source,
        policy=_policy(deadline_seconds=1),
        snapshot_root=snapshot,
    )
    assert injected, f"I/O injection was not reached: {operation}"
    assert not snapshot.exists()
    if failure_root is None:
        assert not staging.exists()
    else:
        assert (staging / "IMPORT-FAILED").read_text() == "DeadlineExceeded\n"


def test_elapsed_work_is_not_reset_between_selection_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _deadline_source(tmp_path, "directory")
    clock = _ImportClock()
    monkeypatch.setattr(entry, "time", clock)
    original_selection = entry._selection_digest
    original_write = entry._write_exclusive
    observed_deadlines: list[float] = []

    def elapsed_selection(*arguments):
        result = original_selection(*arguments)
        clock.now += 0.6
        return result

    def elapsed_metadata(target, raw, deadline):
        observed_deadlines.append(deadline.expires_at)
        assert clock.now == pytest.approx(100.6)
        result = original_write(target, raw, deadline)
        clock.now += 0.6
        return result

    monkeypatch.setattr(entry, "_selection_digest", elapsed_selection)
    monkeypatch.setattr(entry, "_write_exclusive", elapsed_metadata)
    _expect_error(
        "DeadlineExceeded",
        import_snapshot,
        source=source,
        policy=_policy(deadline_seconds=1),
        snapshot_root=tmp_path / "snapshot",
    )
    assert observed_deadlines == [101.0]
    assert (tmp_path / "snapshot.staging/manifest.json").exists()
    assert not (tmp_path / "snapshot.staging/SEALED").exists()


@pytest.fixture
def publication_input(tmp_path: Path) -> dict[str, object]:
    """A new stored ZIP for publication ordering, independent of deadline fixtures."""

    package = tmp_path / "publication.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("a.cs", b"class Publication {}\r\n")
    return {
        "source": {
            "kind": "zip",
            "path": str(package),
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "strip_prefix": None,
        },
        "policy": {
            "source_paths": [],
            "excluded_paths": [],
            "sensitive_paths": [],
            "trusted_control_files": {},
            "deadline_seconds": 1,
        },
        "snapshot_root": tmp_path / "published",
    }


@pytest.mark.parametrize("label_io_failure", [False, True], ids=["label-ok", "label-io-failure"])
@pytest.mark.parametrize("close_result", ["normal", "expired", "error", "expired-error"])
def test_zip_origin_close_precedes_sealing_and_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication_input: dict[str, object],
    close_result: str,
    label_io_failure: bool,
) -> None:
    package = Path(publication_input["source"]["path"])
    snapshot = publication_input["snapshot_root"]
    staging = snapshot.with_name(snapshot.name + ".staging")
    original_package = package.read_bytes()
    clock = _ImportClock()
    original_close = zipfile.ZipFile.close
    original_write_text = Path.write_text
    close_error = OSError(errno.EIO, "synthetic origin close completion failure")
    observation = {"close_result": close_result, "label_io_failure": label_io_failure}
    close_events: list[dict[str, object]] = []
    label_attempts: list[str] = []

    def observed_close(handle):
        if handle.fp is None or Path(handle.filename) != package or handle.mode != "r":
            return original_close(handle)
        event: dict[str, object] = {
            "entry_time": clock.now,
            "origin_open_at_entry": True,
            "snapshot_exists_at_entry": snapshot.exists(),
            "staging_exists_at_entry": staging.exists(),
            "manifest_exists_at_entry": (staging / "manifest.json").exists(),
            "seal_exists_at_entry": (staging / "SEALED").exists(),
        }
        try:
            read_snapshot(snapshot_root=snapshot)
        except TaskInputError as error:
            event["reader_error_at_entry"] = error.code
        else:
            event["reader_error_at_entry"] = None
        result = original_close(handle)
        event["origin_closed_after_real_close"] = handle.fp is None
        if close_result.startswith("expired"):
            clock.expire()
        event["return_time"] = clock.now
        close_events.append(event)
        if close_result.endswith("error"):
            raise close_error
        return result

    def label_write(path, *arguments, **keywords):
        if path in {staging / "IMPORT-FAILED", snapshot / "IMPORT-FAILED"}:
            label_attempts.append(str(path))
            if label_io_failure:
                raise OSError(errno.ENOSPC, "synthetic failure label write rejection")
        return original_write_text(path, *arguments, **keywords)

    manifest = None
    import_error = None
    with monkeypatch.context() as patches:
        patches.setattr(entry, "time", clock)
        patches.setattr(zipfile.ZipFile, "close", observed_close)
        patches.setattr(Path, "write_text", label_write)
        try:
            manifest = import_snapshot(**publication_input)
        except TaskInputError as error:
            import_error = error
    try:
        readback = read_snapshot(snapshot_root=snapshot)
    except TaskInputError as error:
        reader_error = error.code
        readback = None
    else:
        reader_error = None
    observation.update(
        close_events=close_events,
        label_attempts=label_attempts,
        import_error=import_error.code if import_error else None,
        reader_error=reader_error,
        snapshot_exists=snapshot.exists(),
        staging_exists=staging.exists(),
    )
    (tmp_path / "publication-close-observation.json").write_bytes(_canonical(observation))

    assert len(close_events) == 1, "the actual source ZIP close was not observed exactly once"
    event = close_events[0]
    assert event["origin_closed_after_real_close"], "the real ZIP close did not complete"
    assert not event["snapshot_exists_at_entry"], "final root became visible before origin close"
    assert event["reader_error_at_entry"] is not None, "reader accepted a root at close entry"
    assert event["staging_exists_at_entry"]
    assert not event["manifest_exists_at_entry"]
    assert not event["seal_exists_at_entry"]
    assert package.read_bytes() == original_package
    if close_result == "normal":
        assert import_error is None
        assert readback == manifest
        assert not staging.exists()
        assert label_attempts == []
    else:
        expected_code = "IoFailed" if close_result.endswith("error") else "DeadlineExceeded"
        assert import_error is not None and import_error.code == expected_code
        if close_result.endswith("error"):
            assert import_error.__cause__ is close_error
        assert not snapshot.exists(), "failed origin close published a valid final root"
        assert reader_error is not None
        assert (staging / "source/a.cs").read_bytes() == b"class Publication {}\r\n"
        assert not (staging / "manifest.json").exists()
        assert not (staging / "SEALED").exists()
        assert label_attempts == [str(staging / "IMPORT-FAILED")]
        if label_io_failure:
            assert not (staging / "IMPORT-FAILED").exists()
        else:
            assert (staging / "IMPORT-FAILED").read_text() == expected_code + "\n"


@pytest.mark.parametrize("label_io_failure", [False, True], ids=["label-ok", "label-io-failure"])
@pytest.mark.parametrize(
    "rename_result", ["expired-precheck", "error", "late-operation", "late-return"]
)
def test_final_rename_is_the_commit_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication_input: dict[str, object],
    rename_result: str,
    label_io_failure: bool,
) -> None:
    snapshot = publication_input["snapshot_root"]
    staging = snapshot.with_name(snapshot.name + ".staging")
    original_rename = os.rename
    original_target_check = entry._assert_plain_target
    original_write_text = Path.write_text
    original_close = zipfile.ZipFile.close
    rename_error = OSError(errno.EIO, "synthetic final rename failure")
    committed = False
    closed_origins = []
    rename_events = []
    label_attempts = []

    class CommitClock(_ImportClock):
        def monotonic(self) -> float:
            assert not committed, "the importer checked time after successful final rename"
            return super().monotonic()

    clock = CommitClock()

    def observed_close(handle):
        is_origin = handle.fp is not None and handle.mode == "r"
        result = original_close(handle)
        if is_origin:
            closed_origins.append(handle)
        return result

    def final_target_check(path, **keywords):
        result = original_target_check(path, **keywords)
        if (
            rename_result == "expired-precheck"
            and path == snapshot
            and (staging / "SEALED").exists()
        ):
            clock.expire()
        return result

    def final_rename(old, new):
        nonlocal committed
        assert old == staging and new == snapshot
        assert clock.now < 101.0, "final rename entered after the budget expired"
        assert len(closed_origins) == 1 and closed_origins[0].fp is None
        assert not snapshot.exists()
        rename_events.append({"entry_time": clock.now})
        if rename_result == "error":
            raise rename_error
        if rename_result == "late-operation":
            # Simulate time spent inside the unpreemptible rename call before
            # its real OS side effect; this is an explicit boundary injection.
            clock.expire()
        result = original_rename(old, new)
        if rename_result == "late-return":
            clock.expire()
        committed = True
        rename_events[-1]["return_time"] = clock.now
        return result

    def label_write(path, *arguments, **keywords):
        if path == staging / "IMPORT-FAILED":
            label_attempts.append(str(path))
            if label_io_failure:
                raise OSError(errno.ENOSPC, "synthetic failure label write rejection")
        return original_write_text(path, *arguments, **keywords)

    manifest = None
    import_error = None
    with monkeypatch.context() as patches:
        patches.setattr(entry, "time", clock)
        patches.setattr(zipfile.ZipFile, "close", observed_close)
        patches.setattr(entry, "_assert_plain_target", final_target_check)
        patches.setattr(os, "rename", final_rename)
        patches.setattr(Path, "write_text", label_write)
        try:
            manifest = import_snapshot(**publication_input)
        except TaskInputError as error:
            import_error = error
    (tmp_path / "publication-rename-observation.json").write_bytes(
        _canonical(
            {
                "rename_result": rename_result,
                "label_io_failure": label_io_failure,
                "rename_events": rename_events,
                "label_attempts": label_attempts,
                "import_error": import_error.code if import_error else None,
                "committed": committed,
                "origin_close_count": len(closed_origins),
            }
        )
    )
    if rename_result.startswith("late"):
        assert import_error is None and committed
        assert read_snapshot(snapshot_root=snapshot) == manifest
        assert len(rename_events) == 1 and rename_events[0]["return_time"] >= 101.0
        assert label_attempts == []
        assert not (snapshot / "IMPORT-FAILED").exists()
        assert not staging.exists()
    else:
        expected_code = "IoFailed" if rename_result == "error" else "DeadlineExceeded"
        assert import_error is not None and import_error.code == expected_code
        if rename_result == "error":
            assert import_error.__cause__ is rename_error
            assert len(rename_events) == 1
        else:
            assert rename_events == []
        assert not snapshot.exists()
        assert (staging / "manifest.json").is_file()
        assert (staging / "SEALED").is_file()
        assert (staging / "source/a.cs").read_bytes() == b"class Publication {}\r\n"
        assert label_attempts == [str(staging / "IMPORT-FAILED")]
        if label_io_failure:
            assert not (staging / "IMPORT-FAILED").exists()
        else:
            assert (staging / "IMPORT-FAILED").read_text() == expected_code + "\n"


@pytest.mark.parametrize("delay_seconds", [0.0, 1.2], ids=["no-delay", "bounded-real-delay"])
def test_successful_final_rename_can_return_after_the_cooperative_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication_input: dict[str, object],
    delay_seconds: float,
) -> None:
    original_rename = os.rename
    original_check = entry._Deadline.check
    observation: dict[str, object] = {"delay_seconds": delay_seconds}
    committed = False

    def observed_check(deadline):
        assert not committed, "a deadline check ran after successful final rename"
        observation["expires_at"] = deadline.expires_at
        return original_check(deadline)

    def delayed_rename(old, new):
        nonlocal committed
        observation["rename_started_at"] = time.monotonic()
        assert observation["rename_started_at"] < observation["expires_at"]
        # A deliberate delay inside the final call, not a claim about natural
        # OS latency or strict wall-clock preemption.
        time.sleep(delay_seconds)
        result = original_rename(old, new)
        observation["rename_finished_at"] = time.monotonic()
        committed = True
        return result

    with monkeypatch.context() as patches:
        patches.setattr(entry._Deadline, "check", observed_check)
        patches.setattr(os, "rename", delayed_rename)
        manifest = import_snapshot(**publication_input)
    snapshot = publication_input["snapshot_root"]
    assert read_snapshot(snapshot_root=snapshot) == manifest
    assert not (snapshot / "IMPORT-FAILED").exists()
    if delay_seconds:
        assert observation["rename_finished_at"] >= observation["expires_at"]
    else:
        assert observation["rename_finished_at"] < observation["expires_at"]
    (tmp_path / "publication-real-rename-observation.json").write_bytes(_canonical(observation))


def test_one_absolute_budget_spans_selection_origin_close_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication_input: dict[str, object]
) -> None:
    clock = _ImportClock()
    original_check = entry._Deadline.check
    original_selection = entry._selection_digest
    original_close = zipfile.ZipFile.close
    original_write = entry._write_exclusive
    budgets: set[tuple[int, float]] = set()
    events: list[dict[str, object]] = []

    def observed_check(deadline):
        budgets.add((id(deadline), deadline.expires_at))
        return original_check(deadline)

    def elapsed_selection(*arguments):
        result = original_selection(*arguments)
        clock.now += 0.4
        events.append({"stage": "selection", "return_time": clock.now})
        return result

    def elapsed_close(handle):
        is_origin = handle.fp is not None and handle.mode == "r"
        result = original_close(handle)
        if is_origin:
            clock.now += 0.4
            events.append({"stage": "origin-close", "return_time": clock.now})
        return result

    def elapsed_metadata(target, raw, deadline):
        assert target.name == "manifest.json"
        assert clock.now == pytest.approx(100.8)
        assert deadline.expires_at == 101.0
        result = original_write(target, raw, deadline)
        clock.now += 0.3
        events.append({"stage": "metadata", "return_time": clock.now})
        return result

    monkeypatch.setattr(entry, "time", clock)
    monkeypatch.setattr(entry._Deadline, "check", observed_check)
    monkeypatch.setattr(entry, "_selection_digest", elapsed_selection)
    monkeypatch.setattr(zipfile.ZipFile, "close", elapsed_close)
    monkeypatch.setattr(entry, "_write_exclusive", elapsed_metadata)
    _expect_error("DeadlineExceeded", import_snapshot, **publication_input)
    snapshot = publication_input["snapshot_root"]
    staging = snapshot.with_name(snapshot.name + ".staging")
    assert len(budgets) == 1 and next(iter(budgets))[1] == 101.0
    assert [event["stage"] for event in events] == ["selection", "origin-close", "metadata"]
    assert not snapshot.exists()
    assert (staging / "manifest.json").is_file()
    assert not (staging / "SEALED").exists()
    assert (staging / "IMPORT-FAILED").read_text() == "DeadlineExceeded\n"
    (tmp_path / "publication-budget-observation.json").write_bytes(
        _canonical({"budget_count": len(budgets), "expires_at": 101.0, "events": events})
    )


def _capacity_source(tmp_path: Path, kind: str, files: dict[str, bytes]) -> dict[str, object]:
    if kind == "zip":
        package = tmp_path / "capacity.zip"
        return _zip_source(package, _write_zip(package, files))
    root = tmp_path / "input"
    root.mkdir()
    if kind == "git":
        commit = _git_repository(root, files)
        return _git_source(root, commit, sorted(files))
    _write_tree(root, files)
    inventory = _manifest_file(root, _tree_document(root))
    return _directory_source(root, inventory)


def _capacity_queries(monkeypatch: pytest.MonkeyPatch, free_bytes: list[int]) -> list[Path]:
    """Supply one exact synthetic free-space observation per expected query."""

    queries: list[Path] = []

    def disk_usage(path):
        assert len(queries) < len(free_bytes), "unexpected extra output-volume query"
        queries.append(Path(path))
        return SimpleNamespace(free=free_bytes[len(queries) - 1])

    monkeypatch.setattr(entry.shutil, "disk_usage", disk_usage)
    return queries


def _refuse_failure_label(monkeypatch: pytest.MonkeyPatch) -> None:
    original_write = Path.write_text

    def write_text(path, *arguments, **keywords):
        if path.name == "IMPORT-FAILED":
            raise OSError(errno.ENOSPC, "synthetic label write failure")
        return original_write(path, *arguments, **keywords)

    monkeypatch.setattr(Path, "write_text", write_text)


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("free_bytes", [1, 4095])
def test_capacity_preflight_refuses_without_creating_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, free_bytes: int
) -> None:
    source = _capacity_source(tmp_path, kind, {"a.cs": b"Z" * 4096})
    queries = _capacity_queries(monkeypatch, [free_bytes])
    snapshot = tmp_path / "snapshot"
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=snapshot,
    )
    assert queries == [tmp_path]
    assert not snapshot.exists()
    assert not snapshot.with_name("snapshot.staging").exists()


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("extra_bytes", [0, 1])
def test_capacity_exact_content_and_metadata_boundaries_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, extra_bytes: int
) -> None:
    files = {"a.cs": b"abcd", "b.cs": b"efghij", "empty.dat": b""}
    source = _capacity_source(tmp_path, kind, files)
    reference = tmp_path / "reference"
    expected = import_snapshot(source=source, policy=_policy(), snapshot_root=reference)
    manifest_bytes = len((reference / "manifest.json").read_bytes())
    monkeypatch.setattr(entry, "_STREAM_CHUNK_BYTES", 3)
    queries = _capacity_queries(monkeypatch, [10 + extra_bytes, 3, 1, 3, 3, manifest_bytes, 64])
    snapshot = tmp_path / "snapshot"
    actual = import_snapshot(source=source, policy=_policy(), snapshot_root=snapshot)
    assert actual == expected == read_snapshot(snapshot_root=snapshot)
    assert (
        queries
        == [tmp_path]
        + [snapshot.with_name("snapshot.staging") / "source"] * 4
        + [snapshot.with_name("snapshot.staging")] * 2
    )
    for name, raw in files.items():
        assert (snapshot / "source" / name).read_bytes() == raw


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("exclude", [False, True])
def test_capacity_preflight_counts_retained_multifile_total_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, exclude: bool
) -> None:
    files = {"a.cs": b"abcd", "b.cs": b"123456", "omit.dat": b"X" * 4096}
    source = _capacity_source(tmp_path, kind, files)
    policy = _policy(source_paths=sorted(files))
    if exclude:
        policy["excluded_paths"] = [{"path": "omit.dat", "reason": "synthetic exclusion"}]
    # Each retained file fits separately; the cumulative retained total does not.
    free_bytes = 9 if exclude else sum(map(len, files.values())) - 1
    queries = _capacity_queries(monkeypatch, [free_bytes])
    snapshot = tmp_path / "snapshot"
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=source,
        policy=policy,
        snapshot_root=snapshot,
    )
    assert queries == [tmp_path]
    assert not snapshot.exists() and not snapshot.with_name("snapshot.staging").exists()


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("exclude_all", [False, True])
def test_capacity_excluded_bytes_are_not_reserved_or_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, exclude_all: bool
) -> None:
    files = {"a.cs": b"abcd", "omit.dat": b"X" * 4096}
    source = _capacity_source(tmp_path, kind, files)
    excluded = sorted(files) if exclude_all else ["omit.dat"]
    policy = _policy(
        source_paths=sorted(files),
        excluded_paths=[{"path": name, "reason": "synthetic exclusion"} for name in excluded],
    )
    original_git = entry._git_bytes
    size_reads: list[str] = []

    def git_bytes(root, arguments, deadline):
        if arguments[:2] == ["cat-file", "-s"]:
            size_reads.append(arguments[2])
        return original_git(root, arguments, deadline)

    monkeypatch.setattr(entry, "_git_bytes", git_bytes)
    values = [0, 10000, 64] if exclude_all else [4, 4, 10000, 64]
    queries = _capacity_queries(monkeypatch, values)
    snapshot = tmp_path / "snapshot"
    manifest = import_snapshot(source=source, policy=policy, snapshot_root=snapshot)
    assert manifest == read_snapshot(snapshot_root=snapshot)
    assert len(queries) == len(values)
    assert not (snapshot / "source/omit.dat").exists()
    assert (snapshot / "source/a.cs").exists() is not exclude_all
    assert {row["path"] for row in manifest["excluded_paths"]} == set(excluded)
    if kind == "git":
        assert len(size_reads) == (0 if exclude_all else 1)


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("scope", ["within-file", "next-file"])
@pytest.mark.parametrize("label_fails", [False, True])
def test_capacity_decreasing_free_space_stops_before_the_next_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    scope: str,
    label_fails: bool,
) -> None:
    if scope == "within-file":
        files, values, copied = {"a.cs": b"abcdef"}, [6, 2, 1], b"ab"
        monkeypatch.setattr(entry, "_STREAM_CHUNK_BYTES", 2)
    else:
        files, values, copied = {"a.cs": b"abcd", "b.cs": b"123456"}, [10, 4, 5], b"abcd"
    source = _capacity_source(tmp_path, kind, files)
    queries = _capacity_queries(monkeypatch, values)
    original_usage = entry.shutil.disk_usage
    snapshot = tmp_path / "snapshot"
    staging = snapshot.with_name("snapshot.staging")

    def observed_usage(path):
        if len(queries) == 2:
            assert (staging / "source/a.cs").read_bytes() == copied
        return original_usage(path)

    monkeypatch.setattr(entry.shutil, "disk_usage", observed_usage)
    if label_fails:
        _refuse_failure_label(monkeypatch)
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=snapshot,
    )
    assert len(queries) == len(values)
    assert (staging / "source/a.cs").read_bytes() == copied
    if scope == "next-file":
        assert (staging / "source/b.cs").read_bytes() == b""
    assert not snapshot.exists() and not (staging / "manifest.json").exists()
    assert (staging / "IMPORT-FAILED").exists() is not label_fails
    _expect_error("SnapshotRootInvalid", read_snapshot, snapshot_root=snapshot)


@pytest.mark.parametrize("metadata", ["manifest.json", "SEALED"])
@pytest.mark.parametrize("label_fails", [False, True])
def test_capacity_metadata_shortage_uses_serialized_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: str, label_fails: bool
) -> None:
    source = _capacity_source(tmp_path, "directory", {"a.cs": b"abcdef"})
    reference = tmp_path / "reference"
    import_snapshot(source=source, policy=_policy(), snapshot_root=reference)
    manifest_bytes = len((reference / "manifest.json").read_bytes())
    values = (
        [6, 6, manifest_bytes - 1] if metadata == "manifest.json" else [6, 6, manifest_bytes, 63]
    )
    queries = _capacity_queries(monkeypatch, values)
    if label_fails:
        _refuse_failure_label(monkeypatch)
    snapshot = tmp_path / "snapshot"
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=snapshot,
    )
    staging = snapshot.with_name("snapshot.staging")
    assert len(queries) == len(values)
    assert not (staging / metadata).exists()
    assert (staging / "manifest.json").exists() is (metadata == "SEALED")
    assert (staging / "source/a.cs").read_bytes() == b"abcdef"
    assert not snapshot.exists()
    assert (staging / "IMPORT-FAILED").exists() is not label_fails


@pytest.mark.parametrize(
    "query_number", [1, 2, 3, 4], ids=["preflight", "chunk", "manifest", "seal"]
)
@pytest.mark.parametrize("label_fails", [False, True])
def test_capacity_query_failure_preserves_cause_without_host_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, query_number: int, label_fails: bool
) -> None:
    source = _capacity_source(tmp_path, "directory", {"a.cs": b"abcdef"})
    failure = OSError(errno.EIO, "synthetic private host detail")
    query_count = 0

    def disk_usage(path):
        nonlocal query_count
        query_count += 1
        if query_count == query_number:
            raise failure
        return SimpleNamespace(free=10000)

    monkeypatch.setattr(entry.shutil, "disk_usage", disk_usage)
    if label_fails:
        _refuse_failure_label(monkeypatch)
    snapshot = tmp_path / "snapshot"
    error = _expect_error(
        "IoFailed", import_snapshot, source=source, policy=_policy(), snapshot_root=snapshot
    )
    assert error.__cause__ is failure
    assert "private host detail" not in str(error)
    assert query_count == query_number
    assert not snapshot.exists()
    staging = snapshot.with_name("snapshot.staging")
    assert staging.exists() is (query_number > 1)
    assert (staging / "IMPORT-FAILED").exists() is (query_number > 1 and not label_fails)


@pytest.mark.parametrize("target_name", ["a.cs", "manifest.json", "SEALED"])
@pytest.mark.parametrize("label_fails", [False, True])
def test_capacity_actual_write_enospc_retains_partial_evidence_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_name: str, label_fails: bool
) -> None:
    source = _capacity_source(tmp_path, "directory", {"a.cs": b"abcdef"})
    failure = OSError(errno.ENOSPC, "synthetic write exhaustion")
    original_open, original_fdopen = entry.os.open, entry.os.fdopen
    targets: dict[int, Path] = {}
    injected = False

    def os_open(path, *arguments, **keywords):
        descriptor = original_open(path, *arguments, **keywords)
        targets[descriptor] = Path(path)
        return descriptor

    class FailingWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *arguments):
            return self.handle.__exit__(*arguments)

        def write(self, raw):
            nonlocal injected
            self.handle.write(raw[:2])
            self.handle.flush()
            injected = True
            raise failure

    def fdopen(descriptor, mode, *arguments, **keywords):
        handle = original_fdopen(descriptor, mode, *arguments, **keywords)
        if mode == "wb" and targets[descriptor].name == target_name:
            return FailingWriter(handle)
        return handle

    monkeypatch.setattr(entry.os, "open", os_open)
    monkeypatch.setattr(entry.os, "fdopen", fdopen)
    # Real writes of two harmless fixture bytes precede a directed ENOSPC;
    # this does not fill the volume or claim a natural OS capacity failure.
    monkeypatch.setattr(entry.shutil, "disk_usage", lambda path: SimpleNamespace(free=10000))
    if label_fails:
        _refuse_failure_label(monkeypatch)
    snapshot = tmp_path / "snapshot"
    error = _expect_error(
        "IoFailed", import_snapshot, source=source, policy=_policy(), snapshot_root=snapshot
    )
    assert injected and error.__cause__ is failure
    staging = snapshot.with_name("snapshot.staging")
    target = staging / "source/a.cs" if target_name == "a.cs" else staging / target_name
    assert len(target.read_bytes()) == 2
    assert not snapshot.exists()
    assert (staging / "IMPORT-FAILED").exists() is not label_fails
    _expect_error("SnapshotRootInvalid", read_snapshot, snapshot_root=snapshot)


@pytest.mark.parametrize(
    "query_number", [1, 2, 3, 4], ids=["preflight", "chunk", "manifest", "seal"]
)
def test_capacity_queries_consume_the_original_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, query_number: int
) -> None:
    source = _capacity_source(tmp_path, "directory", {"a.cs": b"abcdef"})
    clock = _ImportClock()
    original_check = entry._Deadline.check
    budgets: set[tuple[int, float]] = set()
    query_count = 0

    def check(deadline):
        budgets.add((id(deadline), deadline.expires_at))
        return original_check(deadline)

    def disk_usage(path):
        nonlocal query_count
        query_count += 1
        clock.now += 1.0 - 0.25 * (query_number - 1) if query_count == query_number else 0.25
        return SimpleNamespace(free=10000)

    monkeypatch.setattr(entry, "time", clock)
    monkeypatch.setattr(entry._Deadline, "check", check)
    monkeypatch.setattr(entry.shutil, "disk_usage", disk_usage)
    snapshot = tmp_path / "snapshot"
    _expect_error(
        "DeadlineExceeded",
        import_snapshot,
        source=source,
        policy=_policy(deadline_seconds=1),
        snapshot_root=snapshot,
    )
    assert query_count == query_number
    assert len(budgets) == 1 and next(iter(budgets))[1] == 101.0
    assert not snapshot.exists()
    assert snapshot.with_name("snapshot.staging").exists() is (query_number > 1)


def test_capacity_git_declared_total_and_file_limits_precede_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _capacity_source(tmp_path, "git", {"a.cs": b"abcd", "b.cs": b"123456"})

    def no_capacity_query(path):
        pytest.fail("Git declaration limits must be checked before staging or space query")

    monkeypatch.setattr(entry.shutil, "disk_usage", no_capacity_query)
    for name, policy in [
        ("file", _policy(file_bytes_limit=5)),
        ("total", _policy(expanded_bytes_limit=9)),
    ]:
        snapshot = tmp_path / name
        _expect_error(
            "ResourceLimitExceeded",
            import_snapshot,
            source=source,
            policy=policy,
            snapshot_root=snapshot,
        )
        assert not snapshot.exists() and not snapshot.with_name(name + ".staging").exists()


def _drift_at_final_scan(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_root: Path,
    relative: str,
    expected_before: bytes,
    replacement: bytes,
) -> None:
    """Rewrite one staged file at the real final verification boundary only."""

    original_scan = entry._scan_tree
    staging_source = snapshot_root.with_name(snapshot_root.name + ".staging") / "source"

    def scan_tree(root, policy, deadline):
        if Path(root) == staging_source:
            staged = staging_source.joinpath(*relative.split("/"))
            assert staged.read_bytes() == expected_before
            staged.write_bytes(replacement)
        return original_scan(root, policy, deadline)

    monkeypatch.setattr(entry, "_scan_tree", scan_tree)


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize(
    "replacement",
    [b"changed--source", b"changed-source-longer"],
    ids=["same-length", "variable-length"],
)
def test_final_verification_rejects_post_copy_content_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, replacement: bytes
) -> None:
    original = b"original-source"
    source = _capacity_source(tmp_path, kind, {"a.cs": original})
    snapshot = tmp_path / "snapshot"
    _drift_at_final_scan(monkeypatch, snapshot, "a.cs", original, replacement)
    _expect_error(
        "InputChanged",
        import_snapshot,
        source=source,
        policy=_policy(),
        snapshot_root=snapshot,
    )
    staging = snapshot.with_name("snapshot.staging")
    assert not snapshot.exists()
    assert (staging / "source/a.cs").read_bytes() == replacement
    assert (staging / "IMPORT-FAILED").read_text(encoding="ascii").strip() == "InputChanged"
    assert not (staging / "manifest.json").exists()
    assert not (staging / "SEALED").exists()


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
def test_final_verification_seals_the_copied_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    original = b"original-source"
    source = _capacity_source(tmp_path, kind, {"a.cs": original})
    snapshot = tmp_path / "snapshot"
    _drift_at_final_scan(monkeypatch, snapshot, "a.cs", original, original)
    manifest = import_snapshot(source=source, policy=_policy(), snapshot_root=snapshot)
    row = _entry_map(manifest)["a.cs"]
    assert row["bytes"] == len(original)
    assert row["sha256"] == _sha256(original)
    assert (snapshot / "source/a.cs").read_bytes() == original
    assert read_snapshot(snapshot_root=snapshot) == manifest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", ["zip"]),
        ("kind", {"kind": "zip"}),
        ("git_mode", ["100644"]),
        ("git_mode", {"mode": "100644"}),
        ("source_paths", [["a.cs"]]),
        ("source_paths", [{"path": "a.cs"}]),
    ],
    ids=[
        "kind-list",
        "kind-dict",
        "git-mode-list",
        "git-mode-dict",
        "source-paths-list",
        "source-paths-dict",
    ],
)
def test_read_snapshot_rejects_malformed_manifest_types_before_membership(
    tmp_path: Path, field: str, value: object
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    _write_tree(tree, {"a.cs": b"directory input\n"})
    manifest_path = _manifest_file(tree, _tree_document(tree))
    snapshot_root = tmp_path / "snapshot"
    manifest = _import_directory(tree, manifest_path, snapshot_root)
    # The sealed directory snapshot keeps legal null git_mode rows and reads.
    assert read_snapshot(snapshot_root=snapshot_root) == manifest

    document = json.loads((snapshot_root / "manifest.json").read_bytes())
    if field == "kind":
        document["source"]["kind"] = value
    elif field == "git_mode":
        file_rows = [row for row in document["entries"] if row["kind"] == "file"]
        assert file_rows
        file_rows[0]["git_mode"] = value
    else:
        document["source_paths"] = value
    raw = _canonical(document)
    (snapshot_root / "manifest.json").write_bytes(raw)
    (snapshot_root / "SEALED").write_bytes(_sha256(raw).encode("ascii"))
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=snapshot_root)


def _zip_length_fixture(
    payload: bytes,
    *,
    method: int = zipfile.ZIP_STORED,
    descriptor: str | None = None,
    zip64: bool = False,
    local_changes: dict[str, int] | None = None,
    central_changes: dict[str, int] | None = None,
    descriptor_changes: dict[str, int] | None = None,
    compressed_data: bytes | None = None,
) -> bytes:
    """Real single-member ZIP records; no importer/stdlib replacement.

    ZIP64 includes local and central size extras plus ZIP64 EOCD/locator.
    Changes are explicit raw-format corruptions of this new synthetic input.
    """

    if compressed_data is None:
        if method == zipfile.ZIP_DEFLATED:
            compressor = zlib.compressobj(wbits=-15)
            compressed_data = compressor.compress(payload) + compressor.flush()
        else:
            compressed_data = payload
    values = {
        "flags": 8 if descriptor else 0,
        "method": method,
        "crc": zlib.crc32(payload),
        "compressed": len(compressed_data),
        "expanded": len(payload),
    }
    local = dict(values)
    if descriptor:
        local.update(crc=0, compressed=0, expanded=0)
    local.update(local_changes or {})
    central = values | (central_changes or {})
    name = b"a.cs"
    local_extra = (
        struct.pack("<HHQQ", 1, 16, local["expanded"], local["compressed"]) if zip64 else b""
    )
    local_header = struct.pack(
        "<4s5H3I2H",
        b"PK\x03\x04",
        45 if zip64 else 20,
        local["flags"],
        local["method"],
        0,
        0,
        local["crc"],
        0xFFFFFFFF if zip64 else local["compressed"],
        0xFFFFFFFF if zip64 else local["expanded"],
        len(name),
        len(local_extra),
    )
    data_descriptor = b""
    if descriptor:
        declared = values | (descriptor_changes or {})
        data_descriptor = struct.pack(
            "<IQQ" if zip64 else "<III",
            declared["crc"],
            declared["compressed"],
            declared["expanded"],
        )
        if descriptor == "signed":
            data_descriptor = b"PK\x07\x08" + data_descriptor
    prefix = local_header + name + local_extra + compressed_data + data_descriptor
    central_extra = (
        struct.pack("<HHQQ", 1, 16, central["expanded"], central["compressed"]) if zip64 else b""
    )
    central_header = (
        struct.pack(
            "<4s6H3I5H2I",
            b"PK\x01\x02",
            45 if zip64 else 20,
            45 if zip64 else 20,
            central["flags"],
            central["method"],
            0,
            0,
            central["crc"],
            0xFFFFFFFF if zip64 else central["compressed"],
            0xFFFFFFFF if zip64 else central["expanded"],
            len(name),
            len(central_extra),
            0,
            0,
            0,
            0x20,
            0,
        )
        + name
        + central_extra
    )
    end64 = b""
    if zip64:
        end64 = struct.pack(
            "<4sQ2H2I4Q",
            b"PK\x06\x06",
            44,
            45,
            45,
            0,
            0,
            1,
            1,
            len(central_header),
            len(prefix),
        ) + struct.pack("<4sIQI", b"PK\x06\x07", 0, len(prefix) + len(central_header), 1)
    end = struct.pack(
        "<4s4H2IH",
        b"PK\x05\x06",
        0,
        0,
        0xFFFF if zip64 else 1,
        0xFFFF if zip64 else 1,
        0xFFFFFFFF if zip64 else len(central_header),
        0xFFFFFFFF if zip64 else len(prefix),
        0,
    )
    return prefix + central_header + end64 + end


def _import_zip_length_fixture(tmp_path: Path, raw: bytes) -> tuple[Path, dict[str, object]]:
    package = tmp_path / "length.zip"
    package.write_bytes(raw)
    snapshot = tmp_path / "snapshot"
    manifest = import_snapshot(
        source=_zip_source(package, _sha256(raw), strip=None),
        policy=_policy(),
        snapshot_root=snapshot,
    )
    assert manifest["source"]["identity"] == _sha256(raw)
    assert read_snapshot(snapshot_root=snapshot) == manifest
    return snapshot, manifest


def _reject_zip_length_fixture(tmp_path: Path, raw: bytes, code: str, *, staged: bool) -> None:
    package = tmp_path / "length.zip"
    package.write_bytes(raw)
    snapshot = tmp_path / "snapshot"
    _expect_error(
        code,
        import_snapshot,
        source=_zip_source(package, _sha256(raw), strip=None),
        policy=_policy(),
        snapshot_root=snapshot,
    )
    assert package.read_bytes() == raw
    assert not snapshot.exists()
    staging = tmp_path / "snapshot.staging"
    assert staging.exists() is staged
    if staged:
        assert (staging / "IMPORT-FAILED").read_text().strip() == code
        assert not (staging / "manifest.json").exists()
        assert not (staging / "SEALED").exists()


def test_zip_r10_stored_central_prefix_length_is_rejected(tmp_path: Path) -> None:
    # Fresh real stored ZIP: local/payload=15, central compressed=15,
    # expanded=5 and CRC=first five bytes. Never reuse the R10 failed package.
    payload = b"original-source"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("a.cs", payload)
    raw = bytearray(buffer.getvalue())
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<I", raw, central + 16, zlib.crc32(payload[:5]))
    struct.pack_into("<I", raw, central + 24, 5)
    _reject_zip_length_fixture(tmp_path, bytes(raw), "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("descriptor", [None, "unsigned", "signed"])
@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize("payload", [b"", b"original-source"])
def test_zip_real_record_lengths_preserve_legal_formats(
    tmp_path: Path, method: int, descriptor: str | None, zip64: bool, payload: bytes
) -> None:
    raw = _zip_length_fixture(payload, method=method, descriptor=descriptor, zip64=zip64)
    # Independently confirm stdlib understands these real record layouts.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("a.cs") == payload
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert (snapshot / "source/a.cs").read_bytes() == payload
    row = _entry_map(manifest)["a.cs"]
    assert row["bytes"] == len(payload)
    assert row["sha256"] == _sha256(payload)


class _StreamingZipBuffer(io.BytesIO):
    def seek(self, *arguments: object) -> int:
        raise io.UnsupportedOperation("synthetic non-seekable ZIP output")


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("force_zip64", [False, True])
@pytest.mark.parametrize("payload", [b"", b"original-source"])
def test_zip_stdlib_writer_descriptor_and_local_zip64_are_preserved(
    tmp_path: Path, method: int, streaming: bool, force_zip64: bool, payload: bytes
) -> None:
    buffer = _StreamingZipBuffer() if streaming else io.BytesIO()
    with (
        zipfile.ZipFile(buffer, "w", compression=method) as archive,
        archive.open("a.cs", "w", force_zip64=force_zip64) as writer,
    ):
        writer.write(payload)
    snapshot, _manifest = _import_zip_length_fixture(tmp_path, buffer.getvalue())
    assert (snapshot / "source/a.cs").read_bytes() == payload


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("variant", ["ordinary", "descriptor", "zip64", "zip64-descriptor"])
@pytest.mark.parametrize("field", ["crc", "compressed", "expanded", "method", "flags"])
def test_zip_local_central_metadata_disagreement_is_rejected(
    tmp_path: Path, method: int, variant: str, field: str
) -> None:
    raw = _zip_length_fixture(
        b"original-source",
        method=method,
        descriptor="signed" if "descriptor" in variant else None,
        zip64="zip64" in variant,
        local_changes={field: 99 if field != "method" else (8 if method == 0 else 0)},
    )
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("descriptor", ["unsigned", "signed"])
@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize("field", ["crc", "compressed", "expanded"])
def test_zip_descriptor_disagreement_is_rejected(
    tmp_path: Path, method: int, descriptor: str, zip64: bool, field: str
) -> None:
    raw = _zip_length_fixture(
        b"original-source",
        method=method,
        descriptor=descriptor,
        zip64=zip64,
        descriptor_changes={field: 99},
    )
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("zip64", [False, True])
def test_zip_stored_equal_local_central_but_unequal_sizes_is_rejected(
    tmp_path: Path, zip64: bool
) -> None:
    changes = {"expanded": 5, "crc": zlib.crc32(b"origi")}
    raw = _zip_length_fixture(
        b"original-source", zip64=zip64, local_changes=changes, central_changes=changes
    )
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("declared_size", [0, 5, 16])
@pytest.mark.parametrize("descriptor", [None, "signed"])
@pytest.mark.parametrize("zip64", [False, True])
def test_zip_deflate_actual_length_is_checked_beyond_matching_metadata(
    tmp_path: Path, declared_size: int, descriptor: str | None, zip64: bool
) -> None:
    payload = b"original-source"
    changes = {"expanded": declared_size, "crc": zlib.crc32(payload[:declared_size])}
    raw = _zip_length_fixture(
        payload,
        method=zipfile.ZIP_DEFLATED,
        descriptor=descriptor,
        zip64=zip64,
        local_changes={} if descriptor else changes,
        central_changes=changes,
        descriptor_changes=changes,
    )
    _reject_zip_length_fixture(tmp_path, raw, "InputChanged", staged=True)


def test_zip_corrupt_deflate_stream_maps_the_decompress_error(tmp_path: Path) -> None:
    payload = b"original-source"
    compressor = zlib.compressobj(wbits=-15)
    real = compressor.compress(payload) + compressor.flush()
    raw = _zip_length_fixture(
        payload,
        method=zipfile.ZIP_DEFLATED,
        compressed_data=b"\xff" * len(real),
    )
    package = tmp_path / "corrupt.zip"
    package.write_bytes(raw)
    snapshot_root = tmp_path / "snapshot"
    error = _expect_error(
        "InputChanged",
        import_snapshot,
        source=_zip_source(package, _sha256(raw), strip=None),
        policy=_policy(),
        snapshot_root=snapshot_root,
    )
    assert isinstance(error.__cause__, zlib.error)
    assert package.read_bytes() == raw
    assert not snapshot_root.exists()
    staging = tmp_path / "snapshot.staging"
    assert (staging / "IMPORT-FAILED").read_text().strip() == "InputChanged"
    assert not (staging / "manifest.json").exists()
    assert not (staging / "SEALED").exists()


@pytest.mark.parametrize("defect", ["unfinished", "truncated-end", "trailing", "second-stream"])
@pytest.mark.parametrize("descriptor", [None, "unsigned", "signed"])
@pytest.mark.parametrize("zip64", [False, True])
def test_zip_deflate_real_stream_end_and_compressed_length_are_checked(
    tmp_path: Path, defect: str, descriptor: str | None, zip64: bool
) -> None:
    payload = b"original-source"
    compressor = zlib.compressobj(wbits=-15)
    data = compressor.compress(payload)
    data += compressor.flush(zlib.Z_SYNC_FLUSH if defect == "unfinished" else zlib.Z_FINISH)
    if defect == "truncated-end":
        data = data[:-1]
    elif defect == "trailing":
        data += b"trailing bytes"
    elif defect == "second-stream":
        other = zlib.compressobj(wbits=-15)
        data += other.compress(b"extra") + other.flush()
    raw = _zip_length_fixture(
        payload,
        method=zipfile.ZIP_DEFLATED,
        descriptor=descriptor,
        zip64=zip64,
        compressed_data=data,
    )
    _reject_zip_length_fixture(tmp_path, raw, "InputChanged", staged=True)


@pytest.mark.parametrize("chunk_bytes", [1, 257, 1024 * 1024])
def test_zip_deflate_valid_stream_across_read_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_bytes: int
) -> None:
    # Real format with only reader chunk size injected; not an EOF/CRC mock.
    monkeypatch.setattr(entry, "_STREAM_CHUNK_BYTES", chunk_bytes)
    payload = bytes(range(256)) * 33
    raw = _zip_length_fixture(payload, method=zipfile.ZIP_DEFLATED, descriptor="signed", zip64=True)
    snapshot, _manifest = _import_zip_length_fixture(tmp_path, raw)
    assert (snapshot / "source/a.cs").read_bytes() == payload


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("zip64", [False, True])
def test_zip_descriptor_can_repeat_known_local_values(
    tmp_path: Path, method: int, zip64: bool
) -> None:
    payload = b"original-source"
    plain = _zip_length_fixture(payload, method=method)
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        info = archive.getinfo("a.cs")
        known = {"crc": info.CRC, "compressed": info.compress_size, "expanded": info.file_size}
    raw = _zip_length_fixture(
        payload, method=method, descriptor="unsigned", zip64=zip64, local_changes=known
    )
    snapshot, _manifest = _import_zip_length_fixture(tmp_path, raw)
    assert (snapshot / "source/a.cs").read_bytes() == payload


@pytest.mark.parametrize("zip64", [False, True])
def test_zip_missing_descriptor_is_rejected(tmp_path: Path, zip64: bool) -> None:
    raw = _zip_length_fixture(
        b"original-source",
        zip64=zip64,
        local_changes={"flags": 8, "crc": 0, "compressed": 0, "expanded": 0},
        central_changes={"flags": 8},
    )
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("defect", ["missing-extra", "truncated-extra", "truncated-local"])
def test_zip_local_zip64_required_fields_are_checked(tmp_path: Path, defect: str) -> None:
    raw = bytearray(_zip_length_fixture(b"original-source", zip64=True))
    if defect == "missing-extra":
        # Keep the sentinel but replace local ZIP64 extra ID with an unknown ID.
        struct.pack_into("<H", raw, 34, 0xFFFF)
    elif defect == "truncated-extra":
        struct.pack_into("<H", raw, 36, 17)  # only sixteen field bytes exist
    else:
        # Point the central record at the last nine bytes before the directory.
        central = raw.index(b"PK\x01\x02")
        struct.pack_into("<I", raw, central + 42, central - 9)
    _reject_zip_length_fixture(tmp_path, bytes(raw), "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("defect", [None, "unfinished", "hidden-content"])
def test_zip_explicit_deflate_directory_checks_its_empty_stream(
    tmp_path: Path, defect: str | None
) -> None:
    compressor = zlib.compressobj(wbits=-15)
    payload = b"hidden" if defect == "hidden-content" else b""
    data = compressor.compress(payload)
    data += compressor.flush(zlib.Z_SYNC_FLUSH if defect == "unfinished" else zlib.Z_FINISH)
    # Replace both four-byte filenames with a directory spelling; only bytes
    # and directory attributes are changed, not any runtime API.
    raw = bytearray(_zip_length_fixture(b"", method=zipfile.ZIP_DEFLATED, compressed_data=data))
    raw[30:34] = b"dir/"
    central = raw.index(b"PK\x01\x02")
    raw[central + 46 : central + 50] = b"dir/"
    struct.pack_into("<I", raw, central + 38, 0x10)
    if defect:
        _reject_zip_length_fixture(tmp_path, bytes(raw), "InputChanged", staged=False)
    else:
        snapshot, manifest = _import_zip_length_fixture(tmp_path, bytes(raw))
        assert (snapshot / "source/dir").is_dir()
        assert _entry_map(manifest)["dir"]["bytes"] == 0


def test_zip_directory_stream_precheck_uses_the_import_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Actual ZIP bytes/reader, with only the clock expiry after directory read
    # injected. This is preflight, unlike the existing staged file-read test.
    source = _deadline_source(tmp_path, "zip")
    snapshot = tmp_path / "snapshot"
    clock = _ImportClock()
    monkeypatch.setattr(entry, "time", clock)
    original_read = zipfile.ZipExtFile.read
    observed = []

    def directory_read(reader, *arguments):
        raw = original_read(reader, *arguments)
        if reader.name.endswith("/"):
            observed.append(reader.name)
            clock.expire()
        return raw

    monkeypatch.setattr(zipfile.ZipExtFile, "read", directory_read)
    _expect_error(
        "DeadlineExceeded",
        import_snapshot,
        source=source,
        policy=_policy(deadline_seconds=1),
        snapshot_root=snapshot,
    )
    assert observed
    assert not snapshot.exists()
    assert not (tmp_path / "snapshot.staging").exists()


# LAB-TASK-ZIP-NAME-REPAIR-01: raw local/central name records. The standard
# library writer rewrites separator spellings, so these members are assembled
# from real header bytes with the original names kept in both records.


_UNIX_FILE_ATTRS = (0o100644 << 16) | 0x20
_UNIX_DIRECTORY_ATTRS = (0o40755 << 16) | 0x10


def _zip_raw_name_member(
    name: bytes,
    *,
    payload: bytes = b"",
    flags: int = 0,
    method: int = zipfile.ZIP_STORED,
    external_attr: int = _UNIX_FILE_ATTRS,
    local_name: bytes | None = None,
    extra: bytes = b"",
    local_extra: bytes | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "local_name": name if local_name is None else local_name,
        "payload": payload,
        "flags": flags,
        "method": method,
        "external_attr": external_attr,
        "extra": extra,
        "local_extra": extra if local_extra is None else local_extra,
    }


def _zip_raw_name_package(members: list[dict[str, object]]) -> bytes:
    """Real stored-member records with explicit raw names, flags and attributes."""

    prefix_parts: list[bytes] = []
    central_parts: list[bytes] = []
    offset = 0
    for member in members:
        name = member["name"]
        local_name = member["local_name"]
        payload = member["payload"]
        flags = member["flags"]
        method = member["method"]
        attrs = member["external_attr"]
        extra = member["extra"]
        local_extra = member["local_extra"]
        size = len(payload)
        crc = zlib.crc32(payload)
        local = (
            struct.pack(
                "<4s5H3I2H",
                b"PK\x03\x04",
                20,
                flags,
                method,
                0,
                0,
                crc,
                size,
                size,
                len(local_name),
                len(local_extra),
            )
            + local_name
            + local_extra
            + payload
        )
        central = (
            struct.pack(
                "<4s6H3I5H2I",
                b"PK\x01\x02",
                20,
                20,
                flags,
                method,
                0,
                0,
                crc,
                size,
                size,
                len(name),
                len(extra),
                0,
                0,
                0,
                attrs,
                offset,
            )
            + name
            + extra
        )
        prefix_parts.append(local)
        central_parts.append(central)
        offset += len(local)
    central_directory = b"".join(central_parts)
    end = struct.pack(
        "<4s4H2IH",
        b"PK\x05\x06",
        0,
        0,
        len(members),
        len(members),
        len(central_directory),
        offset,
        0,
    )
    return b"".join(prefix_parts) + central_directory + end


def test_zip_r12_root_absolute_entry_is_rejected_before_any_output(tmp_path: Path) -> None:
    # Mirrors the independent R12 fixture: one stored directory entry whose
    # local and central raw name is exactly one slash.
    raw = _zip_raw_name_package([_zip_raw_name_member(b"/", external_attr=_UNIX_DIRECTORY_ATTRS)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()[0]
        assert info.orig_filename == "/"
        assert info.filename == "/"
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


def test_zip_r12_backslash_root_entry_is_rejected(tmp_path: Path) -> None:
    raw = _zip_raw_name_package([_zip_raw_name_member(b"\\", external_attr=_UNIX_DIRECTORY_ATTRS)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "\\" in archive.infolist()[0].orig_filename
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


def test_zip_r12_empty_raw_entry_name_is_rejected(tmp_path: Path) -> None:
    raw = _zip_raw_name_package([_zip_raw_name_member(b"")])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.infolist()[0].orig_filename == ""
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


def test_zip_r12_raw_nul_entry_name_is_rejected(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"pkg/visible.txt\x00hidden.txt", payload=b"payload\n")]
    )
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


def test_zip_r12_separator_rewrite_is_not_treated_as_a_hidden_nul() -> None:
    info = zipfile.ZipInfo("folder/ordinary.cs")
    info.orig_filename = "folder\\ordinary.cs"
    name, trailing_directory = entry._zip_entry_name(info, entry._default_verification_policy())
    assert name == "folder/ordinary.cs"
    assert trailing_directory is False


@pytest.mark.parametrize(
    ("raw_name", "flags"),
    [
        (b"folder\\ordinary.cs", 0),
        ("中文\\说明.md".encode(), 0x800),
    ],
)
def test_zip_r12_raw_backslash_names_import_normalized(
    tmp_path: Path, raw_name: bytes, flags: int
) -> None:
    payload = b"payload\n"
    raw = _zip_raw_name_package([_zip_raw_name_member(raw_name, payload=payload, flags=flags)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()[0]
        assert "\\" in info.orig_filename
        assert "\\" not in info.filename
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    expected = info.orig_filename.replace("\\", "/")
    assert (snapshot / "source" / expected).read_bytes() == payload
    assert _entry_map(manifest)[expected]["sha256"] == _sha256(payload)


def test_zip_r12_mixed_separator_names_collide(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(b"pkg/a/b.cs", payload=b"first\n"),
            _zip_raw_name_member(b"pkg/a\\b.cs", payload=b"second\n"),
        ]
    )
    _reject_zip_length_fixture(tmp_path, raw, "PathConflict", staged=False)


def test_zip_r12_ordinary_empty_directory_and_empty_package_are_accepted(
    tmp_path: Path,
) -> None:
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"empty/", external_attr=_UNIX_DIRECTORY_ATTRS)]
    )
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert (snapshot / "source/empty").is_dir()
    assert _entry_map(manifest)["empty"]["kind"] == "directory"

    empty_raw = _zip_raw_name_package([])
    package = tmp_path / "empty-package.zip"
    package.write_bytes(empty_raw)
    empty_manifest = import_snapshot(
        source=_zip_source(package, _sha256(empty_raw), strip=None),
        policy=_policy(),
        snapshot_root=tmp_path / "empty-package-snapshot",
    )
    assert empty_manifest["entries"] == []
    assert read_snapshot(snapshot_root=tmp_path / "empty-package-snapshot") == empty_manifest


def test_zip_r12_multi_level_empty_directories_are_accepted(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(name, external_attr=_UNIX_DIRECTORY_ATTRS)
            for name in (b"pkg/", b"pkg/outer/", b"pkg/outer/inner/")
        ]
    )
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert set(_entry_map(manifest)) == {"pkg", "pkg/outer", "pkg/outer/inner"}
    assert (snapshot / "source/pkg/outer/inner").is_dir()


def test_zip_r12_strip_prefix_root_is_not_registered(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(b"pkg/", external_attr=_UNIX_DIRECTORY_ATTRS),
            _zip_raw_name_member(b"pkg/data.cs", payload=b"payload\n"),
        ]
    )
    package = tmp_path / "strip-root.zip"
    package.write_bytes(raw)
    manifest = import_snapshot(
        source=_zip_source(package, _sha256(raw), strip="pkg"),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert set(_entry_map(manifest)) == {"data.cs"}
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


@pytest.mark.parametrize(
    "member",
    [
        pytest.param(
            _zip_raw_name_member(b"pkg/", flags=0x1, external_attr=_UNIX_DIRECTORY_ATTRS),
            id="encrypted",
        ),
        pytest.param(
            _zip_raw_name_member(b"pkg/", method=99, external_attr=_UNIX_DIRECTORY_ATTRS),
            id="unsupported-method",
        ),
        pytest.param(
            _zip_raw_name_member(b"pkg/", external_attr=(0o120777 << 16) | 0x20),
            id="symbolic-link",
        ),
        pytest.param(
            _zip_raw_name_member(b"pkg/", external_attr=_UNIX_DIRECTORY_ATTRS | 0x400),
            id="reparse-attribute",
        ),
    ],
)
def test_zip_r12_strip_prefix_root_illegal_entries_are_still_rejected(
    tmp_path: Path, member: dict[str, object]
) -> None:
    raw = _zip_raw_name_package([member])
    package = tmp_path / "strip-root.zip"
    package.write_bytes(raw)
    _expect_error(
        "ZipEntryRejected",
        import_snapshot,
        source=_zip_source(package, _sha256(raw), strip="pkg"),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot").exists()
    assert not (tmp_path / "snapshot.staging").exists()


def test_zip_r12_local_central_name_disagreement_is_rejected_by_reading(
    tmp_path: Path,
) -> None:
    # Raw name bytes are not compared by the planner itself; the standard
    # library rejects the mismatch when the member is opened for the copy.
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"a.cs", payload=b"payload\n", local_name=b"b.cs")]
    )
    _reject_zip_length_fixture(tmp_path, raw, "InputChanged", staged=True)


# LAB-TASK-ZIP-NAME-REPAIR-02: source records, implicit empty parents and
# CPython 3.13 Unicode Path extra semantics, using real local/central headers.


def _unicode_path_extra(
    original: bytes, unicode_name: bytes, *, version: int = 1, crc: int | None = None
) -> bytes:
    data = struct.pack("<BL", version, zlib.crc32(original) if crc is None else crc) + unicode_name
    return struct.pack("<HH", 0x7075, len(data)) + data


def test_zip_r13_duplicate_strip_roots_are_rejected(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(b"pkg/", external_attr=_UNIX_DIRECTORY_ATTRS),
            _zip_raw_name_member(b"pkg/", external_attr=_UNIX_DIRECTORY_ATTRS),
            _zip_raw_name_member(b"pkg/a.cs", payload=b"x"),
        ]
    )
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_zip_source(package, _sha256(raw)),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot").exists()
    assert not (tmp_path / "snapshot.staging").exists()


def test_zip_r13_implicit_empty_directory_parents_are_kept(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"pkg/outer/inner/", external_attr=_UNIX_DIRECTORY_ATTRS)]
    )
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert list(_entry_map(manifest)) == ["pkg", "pkg/outer", "pkg/outer/inner"]
    assert (snapshot / "source/pkg/outer/inner").is_dir()
    assert manifest["excluded_paths"] == []


@pytest.mark.parametrize("raw_name", [b"\xff.cs", b"\xc0\xaf.cs", b"\xed\xa0\x80.cs"])
def test_zip_r13_invalid_utf8_header_names_have_a_stable_error(
    tmp_path: Path, raw_name: bytes
) -> None:
    raw = _zip_raw_name_package([_zip_raw_name_member(raw_name, flags=0x800)])
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    error = _expect_error(
        "InputChanged",
        import_snapshot,
        source=_zip_source(package, _sha256(raw), strip=None),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert isinstance(error.__cause__, UnicodeDecodeError)
    assert raw_name.hex() not in str(error)
    assert not (tmp_path / "snapshot").exists()
    assert not (tmp_path / "snapshot.staging").exists()


def test_zip_r13_unicode_path_extra_preserves_native_reading(tmp_path: Path) -> None:
    original = b"original.cs"
    effective = "别名.cs"
    payload = b"\xef\xbb\xbfsource\r\n\x00\xff"
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(
                original, payload=payload, extra=_unicode_path_extra(original, effective.encode())
            )
        ]
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()[0]
        assert info.orig_filename == original.decode()
        assert info.filename == effective
        assert archive.read(info) == payload
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert list(_entry_map(manifest)) == [effective]
    assert (snapshot / "source" / effective).read_bytes() == payload
    assert _entry_map(manifest)[effective]["sha256"] == _sha256(payload)


@pytest.mark.parametrize(
    "second_root",
    [
        _zip_raw_name_member(b"pkg\\", external_attr=_UNIX_DIRECTORY_ATTRS),
        _zip_raw_name_member(b"pkg", external_attr=_UNIX_DIRECTORY_ATTRS),
        _zip_raw_name_member(b"pkg", payload=b"file"),
    ],
    ids=["backslash", "directory-attribute", "file-directory"],
)
def test_zip_r13_equivalent_strip_roots_are_rejected(
    tmp_path: Path, second_root: dict[str, object]
) -> None:
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"pkg/", external_attr=_UNIX_DIRECTORY_ATTRS), second_root]
    )
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_zip_source(package, _sha256(raw)),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot.staging").exists()


@pytest.mark.parametrize(("root", "child"), [("pkg", "PKG/a.cs"), ("caf\u00e9", "cafe\u0301/a.cs")])
def test_zip_r13_source_root_conflicts_precede_stripping(
    tmp_path: Path, root: str, child: str
) -> None:
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(
                (root + "/").encode(), flags=0x800, external_attr=_UNIX_DIRECTORY_ATTRS
            ),
            _zip_raw_name_member(child.encode(), flags=0x800, payload=b"x"),
        ]
    )
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    _expect_error(
        "PathConflict",
        import_snapshot,
        source=_zip_source(package, _sha256(raw), strip=root),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot.staging").exists()


def test_zip_r13_single_strip_root_can_have_no_output(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"pkg/", external_attr=_UNIX_DIRECTORY_ATTRS)]
    )
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    manifest = import_snapshot(
        source=_zip_source(package, _sha256(raw)),
        policy=_policy(entry_count_limit=1),
        snapshot_root=tmp_path / "snapshot",
    )
    assert manifest["entries"] == []
    assert manifest["excluded_paths"] == []
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


@pytest.mark.parametrize("strip", [None, "pkg"])
def test_zip_r13_empty_parent_inventory_and_exclusion_denominator(
    tmp_path: Path, strip: str | None
) -> None:
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(b"pkg/outer/inner/", external_attr=_UNIX_DIRECTORY_ATTRS),
            _zip_raw_name_member(b"pkg/drop/deep/", external_attr=_UNIX_DIRECTORY_ATTRS),
        ]
    )
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    source = _zip_source(package, _sha256(raw), strip=strip)
    prefix = "pkg/" if strip is None else ""
    kept = [prefix + "outer", prefix + "outer/inner"]
    if strip is None:
        kept.insert(0, "pkg")
    excluded = [{"path": prefix + "drop", "reason": "omitted empty subtree"}]
    exact_count = len(kept) + 1
    _expect_error(
        "ResourceLimitExceeded",
        import_snapshot,
        source=source,
        policy=_policy(excluded_paths=excluded, entry_count_limit=exact_count - 1),
        snapshot_root=tmp_path / "tight",
    )
    assert not (tmp_path / "tight.staging").exists()
    manifest = import_snapshot(
        source=source,
        policy=_policy(excluded_paths=excluded, entry_count_limit=exact_count),
        snapshot_root=tmp_path / "snapshot",
    )
    assert list(_entry_map(manifest)) == kept
    assert manifest["excluded_paths"] == [
        {"path": prefix + "drop/deep", "reason": "omitted empty subtree"}
    ]
    assert manifest["source_paths"] == []
    assert manifest["source"]["identity"] == _sha256(raw)
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


def test_zip_r13_all_excluded_empty_directory_has_no_output_ancestors(tmp_path: Path) -> None:
    raw = _zip_raw_name_package(
        [_zip_raw_name_member(b"pkg/outer/inner/", external_attr=_UNIX_DIRECTORY_ATTRS)]
    )
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    manifest = import_snapshot(
        source=_zip_source(package, _sha256(raw)),
        policy=_policy(
            excluded_paths=[{"path": "outer", "reason": "omitted"}], entry_count_limit=1
        ),
        snapshot_root=tmp_path / "snapshot",
    )
    assert manifest["entries"] == []
    assert manifest["excluded_paths"] == [{"path": "outer/inner", "reason": "omitted"}]
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_zip_r13_constructor_interruptions_are_not_mapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: type[BaseException]
) -> None:
    package = tmp_path / "input.zip"
    raw = _zip_raw_name_package([])
    package.write_bytes(raw)

    def interrupted(*args: object, **kwargs: object) -> None:
        raise interruption("synthetic interruption")

    monkeypatch.setattr(entry.zipfile, "ZipFile", interrupted)
    with pytest.raises(interruption, match="synthetic interruption"):
        import_snapshot(
            source=_zip_source(package, _sha256(raw), strip=None),
            policy=_policy(),
            snapshot_root=tmp_path / "snapshot",
        )
    assert not (tmp_path / "snapshot.staging").exists()


@pytest.mark.parametrize(
    ("original", "flags", "effective"),
    [
        (b"caf\x82.cs", 0, "中文.cs"),
        ("原名.cs".encode(), 0x800, "别名.cs"),
        (b"ordinary.cs", 0, "目录\\别名.cs"),
    ],
)
def test_zip_r13_unicode_path_extra_uses_the_header_encoding(
    tmp_path: Path, original: bytes, flags: int, effective: str
) -> None:
    payload = b"original bytes\x00\xff\r\n"
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(
                original,
                flags=flags,
                payload=payload,
                extra=_unicode_path_extra(original, effective.encode()),
            )
        ]
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()[0]
        assert info.orig_filename == original.decode("utf-8" if flags else "cp437")
        assert info.filename == effective.replace("\\", "/")
        assert archive.read(info) == payload
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    expected = effective.replace("\\", "/")
    assert (snapshot / "source" / expected).read_bytes() == payload
    assert _entry_map(manifest)[expected]["sha256"] == _sha256(payload)


def test_zip_r13_unicode_empty_directory_completes_effective_parents(tmp_path: Path) -> None:
    original = b"empty/"
    effective = "目录/内层/"
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(
                original,
                external_attr=_UNIX_DIRECTORY_ATTRS,
                extra=_unicode_path_extra(original, effective.encode()),
            )
        ]
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read(archive.infolist()[0]) == b""
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert list(_entry_map(manifest)) == ["目录", "目录/内层"]
    assert (snapshot / "source/目录/内层").is_dir()


@pytest.mark.parametrize(
    "name",
    [
        b"visible.cs\x00hidden",
        b"../escape.cs",
        b"/root.cs",
        b"\\root.cs",
        b"C:drive.cs",
        b"dir//file.cs",
        b"dir/./file.cs",
        b"NUL.cs",
        b"tail. ",
        b"file.cs:stream",
    ],
)
@pytest.mark.parametrize("unsafe_view", ["original", "effective"])
def test_zip_r13_unicode_extra_does_not_hide_an_unsafe_name(
    tmp_path: Path, name: bytes, unsafe_view: str
) -> None:
    original = name if unsafe_view == "original" else b"original.cs"
    effective = name if unsafe_view == "effective" else b"safe.cs"
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(
                original, payload=b"x", extra=_unicode_path_extra(original, effective)
            )
        ]
    )
    _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)


@pytest.mark.parametrize("ignored", ["crc", "version"])
def test_zip_r13_unrecognized_unicode_extra_keeps_the_original_name(
    tmp_path: Path, ignored: str
) -> None:
    original = b"original.cs"
    extra = _unicode_path_extra(
        original,
        b"\xff\x00../unused",
        version=2 if ignored == "version" else 1,
        crc=zlib.crc32(original) ^ 1 if ignored == "crc" else None,
    )
    raw = _zip_raw_name_package([_zip_raw_name_member(original, payload=b"x", extra=extra)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()[0]
        assert info.filename == original.decode()
        assert archive.read(info) == b"x"
    snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
    assert list(_entry_map(manifest)) == ["original.cs"]
    assert (snapshot / "source/original.cs").read_bytes() == b"x"


@pytest.mark.parametrize(
    "extra",
    [
        struct.pack("<HH", 0x7075, 5) + b"\x01",
        struct.pack("<HH", 0x7075, 4) + b"\0" * 4,
        _unicode_path_extra(b"original.cs", b"\xff.cs"),
    ],
    ids=["truncated-field", "short-unicode-header", "invalid-unicode-utf8"],
)
def test_zip_r13_malformed_unicode_extra_has_a_stable_error(tmp_path: Path, extra: bytes) -> None:
    raw = _zip_raw_name_package([_zip_raw_name_member(b"original.cs", extra=extra)])
    package = tmp_path / "input.zip"
    package.write_bytes(raw)
    error = _expect_error(
        "InputChanged",
        import_snapshot,
        source=_zip_source(package, _sha256(raw), strip=None),
        policy=_policy(),
        snapshot_root=tmp_path / "snapshot",
    )
    assert isinstance(error.__cause__, zipfile.BadZipFile)
    assert "original.cs" not in str(error)
    assert not (tmp_path / "snapshot.staging").exists()


@pytest.mark.parametrize(
    ("original_names", "effective_names"),
    [
        (("same.cs", "same.cs"), ("one.cs", "two.cs")),
        (("A.cs", "a.cs"), ("one.cs", "two.cs")),
        (("caf\u00e9/x.cs", "cafe\u0301/y.cs"), ("one.cs", "two.cs")),
        (("parent", "parent/child.cs"), ("one.cs", "two.cs")),
        (("one.cs", "two.cs"), ("same.cs", "same.cs")),
        (("one.cs", "two.cs"), ("A.cs", "a.cs")),
        (("one.cs", "two.cs"), ("caf\u00e9/x.cs", "cafe\u0301/y.cs")),
        (("one.cs", "two.cs"), ("parent", "parent/child.cs")),
    ],
    ids=[
        "raw-duplicate",
        "raw-casefold",
        "raw-nfc-parents",
        "raw-file-parent",
        "effective-duplicate",
        "effective-casefold",
        "effective-nfc-parents",
        "effective-file-parent",
    ],
)
def test_zip_r13_original_and_effective_collections_reject_conflicts(
    tmp_path: Path, original_names: tuple[str, str], effective_names: tuple[str, str]
) -> None:
    members = [
        _zip_raw_name_member(
            original.encode(),
            flags=0x800,
            payload=b"x",
            extra=_unicode_path_extra(original.encode(), effective.encode()),
        )
        for original, effective in zip(original_names, effective_names, strict=True)
    ]
    _reject_zip_length_fixture(
        tmp_path, _zip_raw_name_package(members), "PathConflict", staged=False
    )


def test_zip_r13_unicode_extra_keeps_local_header_name_verification(tmp_path: Path) -> None:
    original = b"original.cs"
    effective = "别名.cs".encode()
    raw = _zip_raw_name_package(
        [
            _zip_raw_name_member(
                original,
                flags=0x800,
                local_name=effective,
                payload=b"x",
                extra=_unicode_path_extra(original, effective),
            )
        ]
    )
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as archive,
        pytest.raises(zipfile.BadZipFile, match="differ"),
    ):
        archive.read(archive.infolist()[0])
    _reject_zip_length_fixture(tmp_path, raw, "InputChanged", staged=True)


@pytest.mark.parametrize("hidden_nul", [False, True])
def test_zip_r13_multiple_unicode_fields_validate_each_accepted_name(
    tmp_path: Path, hidden_nul: bool
) -> None:
    original = b"original.cs"
    first = b"one.cs\x00hidden" if hidden_nul else b"one.cs"
    extra = _unicode_path_extra(original, first) + _unicode_path_extra(original, "最终.cs".encode())
    raw = _zip_raw_name_package([_zip_raw_name_member(original, payload=b"x", extra=extra)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.infolist()[0].filename == "最终.cs"
        assert archive.read(archive.infolist()[0]) == b"x"
    if hidden_nul:
        _reject_zip_length_fixture(tmp_path, raw, "ZipEntryRejected", staged=False)
    else:
        snapshot, manifest = _import_zip_length_fixture(tmp_path, raw)
        assert list(_entry_map(manifest)) == ["最终.cs"]
        assert (snapshot / "source/最终.cs").read_bytes() == b"x"


def test_zip_r13_an_unexplained_name_difference_is_rejected() -> None:
    info = zipfile.ZipInfo("original.cs")
    info.filename = "other.cs"
    _expect_error(
        "ZipEntryRejected", entry._zip_entry_name, info, entry._default_verification_policy()
    )


def _semantics_origin(
    tmp_path: Path, kind: str, files: dict[str, bytes]
) -> tuple[dict[str, object], Path]:
    """Make one plain synthetic tree, with a byte-pinned source of each kind."""
    tree = tmp_path / "origin"
    tree.mkdir()
    _write_tree(tree, files)
    if kind == "zip":
        package = tmp_path / "origin.zip"
        return _zip_source(package, _write_zip(package, files)), tree
    if kind == "directory":
        inventory = _manifest_file(tree, _tree_document(tree))
        return _directory_source(tree, inventory), tree
    fixed_options = (
        "-c",
        "core.autocrlf=false",
        "-c",
        f"core.hooksPath={tmp_path / 'no-hooks'}",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.name=OfflineFixture",
        "-c",
        "user.email=fixture@example.invalid",
    )
    _git(tree, *fixed_options, "init", "-q")
    _git(tree, *fixed_options, "add", "--all")
    _git(tree, *fixed_options, "commit", "-q", "--allow-empty", "-m", "synthetic path semantics")
    commit = _git_sha(tree, "HEAD")
    return _git_source(tree, commit, list(reversed(files))), tree


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize(
    ("actual", "rule", "blocked"),
    [
        pytest.param("Creds/Key.pem", "creds/key.pem", True, id="case-file"),
        pytest.param("Creds/Deep/Key.pem", "creds", True, id="case-subtree"),
        pytest.param("Cafe\u0301/clé.pem", "CAFÉ", True, id="nfc-subtree"),
        pytest.param("Creds2/Key.pem", "creds", False, id="component-boundary"),
        pytest.param("AuthToken.cs", "token", False, id="ordinary-business-name"),
    ],
)
def test_path_semantics_sensitive_scope(
    tmp_path: Path, kind: str, actual: str, rule: str, blocked: bool
) -> None:
    raw = b"SYNTHETIC-NONCREDENTIAL\r\n\x00\xff"
    source, tree = _semantics_origin(tmp_path, kind, {actual: raw})
    if actual == "Creds/Key.pem":
        observed = os.path.samefile(tree / actual, tree / rule)
        (tmp_path / "SAMEFILE.json").write_bytes(_canonical({"samefile": observed}))
        assert observed, "case-only fixture must name the same Windows file"
    target = tmp_path / "snapshot"
    policy = _policy(source_paths=[actual], sensitive_paths=[rule])
    if blocked:
        _expect_error(
            "SensitivePathImported",
            import_snapshot,
            source=source,
            policy=policy,
            snapshot_root=target,
        )
        assert not target.exists()
        assert not target.with_name("snapshot.staging").exists()
    else:
        manifest = import_snapshot(source=source, policy=policy, snapshot_root=target)
        assert manifest["source_paths"] == [actual]
        assert target.joinpath("source", actual).read_bytes() == raw
        assert read_snapshot(snapshot_root=target) == manifest
    assert tree.joinpath(actual).read_bytes() == raw


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
def test_path_semantics_exclusion_scope_and_sensitive_interaction(
    tmp_path: Path, kind: str
) -> None:
    files = {
        "Creds/Key.pem": b"x",
        "Creds/Deep/Cafe\u0301.pem": b"y",
        "Creds2/AuthToken.cs": b"ordinary\r\n\x00\xff",
    }
    source, _ = _semantics_origin(tmp_path, kind, files)
    exclusions = [
        {"path": "creds", "reason": "outside input"},
        {"path": "CREDS/deep", "reason": "separate subtree"},
    ]
    results = []
    for index, order in enumerate((exclusions, list(reversed(exclusions)))):
        target = tmp_path / f"snapshot-{index}"
        policy = _policy(
            source_paths=list(reversed(files)), excluded_paths=order, sensitive_paths=["CREDS"]
        )
        before = _canonical(policy)
        manifest = import_snapshot(source=source, policy=policy, snapshot_root=target)
        assert _canonical(policy) == before
        records = {row["path"]: row["reason"] for row in manifest["excluded_paths"]}
        assert records["Creds/Key.pem"] == "outside input"
        assert records["Creds/Deep/Cafe\u0301.pem"] == "separate subtree"
        assert "Creds2/AuthToken.cs" in _entry_map(manifest)
        assert set(manifest["source_paths"]) == set(files)
        assert manifest["source"]["selection_sha256"] == _sha256(
            _canonical(
                {
                    "source_paths": sorted(files, key=lambda path: path.encode("utf-8")),
                    "excluded_paths": manifest["excluded_paths"],
                }
            )
        )
        assert read_snapshot(snapshot_root=target) == manifest
        results.append(manifest)
    assert results[0] == results[1], "rule order must not choose a different exclusion reason"


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
def test_path_semantics_exclusion_nfc_preserves_original_name(tmp_path: Path, kind: str) -> None:
    original = "Cafe\u0301/Key.pem"
    source, _ = _semantics_origin(tmp_path, kind, {original: b"synthetic"})
    manifest = import_snapshot(
        source=source,
        policy=_policy(
            source_paths=[original],
            excluded_paths=[{"path": "CAFÉ", "reason": "omitted"}],
            sensitive_paths=["café"],
        ),
        snapshot_root=tmp_path / "snapshot",
    )
    assert {row["path"] for row in manifest["excluded_paths"]} >= {original}
    assert manifest["source_paths"] == [original]
    assert read_snapshot(snapshot_root=tmp_path / "snapshot") == manifest


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
def test_path_semantics_exclusion_does_not_cross_component_boundary(
    tmp_path: Path, kind: str
) -> None:
    source, _ = _semantics_origin(tmp_path, kind, {"Creds2/Key.pem": b"synthetic"})
    _expect_error(
        "ExcludedPathUnknown",
        import_snapshot,
        source=source,
        policy=_policy(excluded_paths=[{"path": "creds", "reason": "not present"}]),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot.staging").exists()


@pytest.mark.parametrize("field", ["sensitive_paths", "excluded_paths"])
@pytest.mark.parametrize("rules", [("Creds", "creds"), ("café", "cafe\u0301")])
def test_path_semantics_equivalent_scope_rules_are_not_merged(
    field: str, rules: tuple[str, str]
) -> None:
    values = (
        [{"path": path, "reason": "omitted"} for path in rules]
        if field == "excluded_paths"
        else list(rules)
    )
    _expect_error("InvalidPolicy", entry._validate_policy, _policy(**{field: values}))


def test_path_semantics_specific_exclusion_uses_component_depth() -> None:
    # Casefold expands ß: original codepoint length must not rank scope depth.
    broad = "S" * 16
    deep = "ß" * 8 + "/leaf"
    policy = entry._validate_policy(
        _policy(
            excluded_paths=[{"path": broad, "reason": "broad"}, {"path": deep, "reason": "deep"}]
        )
    )
    assert entry._most_specific_exclusion(
        broad + "/leaf/a.cs", policy.excluded_paths, entry._Deadline.starting_now(60)
    ) == (deep, "deep")


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("variant", ["exact", "case-alias", "nfc-alias", "wrong-hash", "excluded"])
def test_path_semantics_control_reference_is_exact(tmp_path: Path, kind: str, variant: str) -> None:
    original = "Cafe\u0301/AGENTS.md"
    raw = b"# synthetic host guide\r\n\x00\xff"
    source, _ = _semantics_origin(tmp_path, kind, {original: raw})
    reference = original
    if variant == "case-alias":
        reference = "cafe\u0301/agents.md"
    elif variant == "nfc-alias":
        reference = "Café/AGENTS.md"
    digest = "0" * 64 if variant == "wrong-hash" else _sha256(raw)
    exclusions = [{"path": "CAFÉ", "reason": "omitted"}] if variant == "excluded" else []
    policy = _policy(trusted_control_files={reference: digest}, excluded_paths=exclusions)
    target = tmp_path / "snapshot"
    if variant == "exact":
        manifest = import_snapshot(source=source, policy=policy, snapshot_root=target)
        assert target.joinpath("source", original).read_bytes() == raw
        assert read_snapshot(snapshot_root=target) == manifest
    else:
        _expect_error(
            "InputControlConflict",
            import_snapshot,
            source=source,
            policy=policy,
            snapshot_root=target,
        )
        assert not target.exists()
        assert (target.with_name("snapshot.staging") / "IMPORT-FAILED").read_text() == (
            "InputControlConflict\n"
        )


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("declared", ["empty", "subset", "all"])
def test_path_semantics_canonical_declarations_and_digest(
    tmp_path: Path, kind: str, declared: str
) -> None:
    # Preserve a decomposed name in a different component without an NFC collision.
    files = {
        "é.cs": b"accent\r\n",
        "z.cs": b"ascii\x00\xff",
        "中文/e\u0301.cs": b"decomposed\r\n\x80",
    }
    source, _ = _semantics_origin(tmp_path, kind, files)
    names = [] if declared == "empty" else ["中文/e\u0301.cs", "z.cs"]
    if declared == "all":
        names.append("é.cs")
    expected = sorted(names, key=lambda path: path.encode("utf-8"))
    manifests = []
    for index, order in enumerate((names, list(reversed(names)))):
        policy = _policy(source_paths=order)
        original_policy = _canonical(policy)
        original_source = _canonical(source)
        target = tmp_path / f"snapshot-{index}"
        manifest = import_snapshot(source=source, policy=policy, snapshot_root=target)
        assert _canonical(policy) == original_policy and _canonical(source) == original_source
        assert manifest["source_paths"] == expected
        assert manifest["source"]["selection_sha256"] == _sha256(
            _canonical({"source_paths": expected, "excluded_paths": []})
        )
        assert read_snapshot(snapshot_root=target) == manifest
        for path, raw in files.items():
            assert target.joinpath("source", path).read_bytes() == raw
        manifests.append(manifest)
    assert manifests[0] == manifests[1]


@pytest.mark.parametrize("kind", ["git", "zip", "directory"])
@pytest.mark.parametrize("variant", ["case-member", "nfc-excluded-member", "duplicate"])
def test_path_semantics_declaration_members_are_exact(
    tmp_path: Path, kind: str, variant: str
) -> None:
    original = "Cafe\u0301/a.cs"
    source, _ = _semantics_origin(tmp_path, kind, {original: b"synthetic"})
    declared = ["cafe\u0301/A.cs"]
    exclusions = []
    code = "SourcePathUnaccounted"
    if variant == "nfc-excluded-member":
        declared = ["Café/a.cs"]
        exclusions = [{"path": "CAFÉ", "reason": "omitted"}]
    elif variant == "duplicate":
        declared = [original, original]
        code = "InvalidPolicy"
    _expect_error(
        code,
        import_snapshot,
        source=source,
        policy=_policy(source_paths=declared, excluded_paths=exclusions),
        snapshot_root=tmp_path / "snapshot",
    )
    assert not (tmp_path / "snapshot.staging").exists()


@pytest.mark.parametrize("variant", ["reverse-ascii", "reverse-unicode", "duplicate"])
def test_path_semantics_reader_rejects_noncanonical_declarations(
    tmp_path: Path, variant: str
) -> None:
    paths = ["z.cs", "é.cs", "中文/e\u0301.cs"]
    target = tmp_path / "snapshot"
    document = _read_collection_fixture(target, paths, [])
    ordered = sorted(paths, key=lambda path: path.encode("utf-8"))
    if variant == "reverse-ascii":
        document["source_paths"] = [ordered[1], ordered[0], ordered[2]]
    elif variant == "reverse-unicode":
        document["source_paths"] = [ordered[0], ordered[2], ordered[1]]
    else:
        document["source_paths"] = [ordered[0], *ordered]
    document["source"]["selection_sha256"] = _sha256(
        _canonical({"source_paths": document["source_paths"], "excluded_paths": []})
    )
    raw = _canonical(document)
    (target / "manifest.json").write_bytes(raw)
    (target / "SEALED").write_bytes(_sha256(raw).encode("ascii"))
    before = (target / "manifest.json").read_bytes(), (target / "SEALED").read_bytes()
    _expect_error("InvalidManifest", read_snapshot, snapshot_root=target)
    assert ((target / "manifest.json").read_bytes(), (target / "SEALED").read_bytes()) == before


@pytest.mark.parametrize("variant", ["exact", "case-alias", "nfc-alias", "component-boundary"])
def test_path_semantics_zip_strip_prefix_is_exact(tmp_path: Path, variant: str) -> None:
    prefix = "Cafe\u0301"
    rule = {
        "exact": prefix,
        "case-alias": "cafe\u0301",
        "nfc-alias": "Café",
        "component-boundary": "Cafe",
    }[variant]
    package = tmp_path / "origin.zip"
    raw = b"original bytes\r\n\x00\xff"
    source = _zip_source(package, _write_zip(package, {"说明.cs": raw}, prefix=prefix), strip=rule)
    target = tmp_path / "snapshot"
    if variant == "exact":
        manifest = import_snapshot(
            source=source, policy=_policy(source_paths=["说明.cs"]), snapshot_root=target
        )
        assert target.joinpath("source", "说明.cs").read_bytes() == raw
        assert read_snapshot(snapshot_root=target) == manifest
    else:
        _expect_error(
            "StripPrefixMismatch",
            import_snapshot,
            source=source,
            policy=_policy(),
            snapshot_root=target,
        )
        assert not target.with_name("snapshot.staging").exists()
