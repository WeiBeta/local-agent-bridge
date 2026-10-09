"""Distribution surface tests: packaging, entry points and import closure."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "local_agent_bridge"

# SHA-256 (content digest) of the start script's frozen Git blob at the pinned
# source commit 725333c2e345a01faf04475b4b3bcdade91fdd3c (path
# scripts/start_comfyui_h3.ps1). This is a SHA-256 over the blob's bytes, not a Git
# SHA-1 object ID; the Git object name of that blob is
# 34f6d1b7461064712dc942e58cd13ecfa3e018922ba3f070bcf72c416744444b.
# Only CRLF to LF normalization is allowed, so that a Windows checkout and a
# source archive compare equal while any substantive edit still fails the check.
FROZEN_START_SCRIPT_LF_SHA256 = "34f6d1b7461064712dc942e58cd13ecfa3e018922ba3f070bcf72c416744444b"

EXPECTED_PACKAGE_FILES = {
    "__init__.py",
    "__main__.py",
    "cli.py",
    "task_cli.py",
    "bridge/__init__.py",
    "bridge/contract.py",
    "bridge/paths.py",
    "bridge/slice_run.py",
    "bridge/slice_workspace.py",
    "bridge/winjob.py",
    "bridge/cursor_run.py",
    "bridge/task_input.py",
    "bridge/task_run.py",
    "bridge/layered_acceptance.py",
    "bridge/task_workspace.py",
    "capture/__init__.py",
    "capture/keys.py",
    "capture/retention.py",
    "capture/session.py",
    "shadow/__init__.py",
    "shadow/replay.py",
    "h3.py",
    "h3_mcp.py",
    "h3_models.py",
    "resources/__init__.py",
    "resources/ag_slice_run_private.ps1",
    "resources/start_comfyui_h3.ps1",
}

# Every shipped test module, discovered through the directory-level testpaths
# configuration rather than a hand-written module list.
EXPECTED_TEST_MODULES = {
    "tests/test_agy_live_adapter.py",
    "tests/test_agy_stdout_reanalysis.py",
    "tests/test_bridge_contract.py",
    "tests/test_bridge_run.py",
    "tests/test_bridge_slice.py",
    "tests/test_bridge_winjob.py",
    "tests/test_cursor_run.py",
    "tests/test_distribution.py",
    "tests/test_first_task_r.py",
    "tests/test_h3_adapter.py",
    "tests/test_h3_mcp.py",
    "tests/test_legacy_launch_receipts.py",
    "tests/test_session_capture.py",
    "tests/test_session_retention.py",
    "tests/test_shadow_replay.py",
    "tests/test_task_bc_integration.py",
    "tests/test_task_input.py",
    "tests/test_task_cli.py",
    "tests/test_task_launch_lifecycle.py",
    "tests/test_task_run.py",
    "tests/test_layered_acceptance.py",
    "tests/test_task_workspace.py",
}

# Git blob object names of the license material restored verbatim from the
# historical commit 2b6263712f75e8d436c4e77c4de0a6aa185e2f42. These are Git SHA-1
# object names, not file content digests; they pin the exact restored bytes.
RESTORED_LICENSE_BLOBS = {
    "LICENSE": "be3f7b28e564e7dd05eaf59d64adba1a4065ac0e",
    "LICENSES/MIT-jimmyloi.txt": "bc470504b7429102a79732d2a76582709566ae9f",
    "docs/legal/PROVENANCE.zh-CN.md": "ff0fc82de7434e8bfc54e30ca9a1a1b71192aa14",
    "docs/legal/jimmy-mit-permission.png": "6dc197ba8a78c6635def2c25e2adffb5c59ebc27",
}

# The provenance record's own quoted SHA-256 of the permission screenshot. It is
# reused here so the carried image and the recorded evidence cannot drift apart.
PERMISSION_IMAGE_SHA256 = "400eb071ccf3696eb9b5b6fedbff787ea1e9f74cc3b438c78525eb9eaba18ad5"

# The retired product's own module names, which must not be imported by the
# distribution. "code_review" is absent on purpose: the extracted bridge docstrings
# and module name record where the primitives came from, and that provenance is
# not an import. "budget" is also absent: the new file-length storage budget is
# unrelated to the retired API accounting module. Exact old-package imports are
# still blocked by the first two markers and the isolated wheel import test.
LEGACY_MARKERS = (
    "from ask_ai_mcp",
    "import ask_ai_mcp",
    "coding_models",
    "opencode",
    "toolsmith",
    "wire_capture",
)


def _discover(name: str) -> metadata.Distribution:
    return metadata.distribution(name)


def test_project_metadata_targets_the_preview_package() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]

    assert project["name"] == "local-agent-bridge"
    assert project["version"] == "0.1.0.dev0"
    # The distribution now uses this product's own home page, not the retired
    # repository README and no longer the H3-only usage note either.
    assert project["readme"] == "README.md"
    assert set(project["dependencies"]) == {
        "fastmcp>=3.4.5,<3.5",
        "httpx>=0.28.1,<0.29",
        "pydantic>=2.12,<3",
        "cryptography>=46,<50",
        "keyring>=25.6,<26",
    }
    assert project["scripts"] == {
        "local-agent-bridge": "local_agent_bridge.__main__:main_bridge",
        "local-agent-bridge-h3": "local_agent_bridge.__main__:main_h3",
    }
    wheel = document["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/local_agent_bridge"]


def test_installed_distribution_exposes_the_two_preview_entry_points() -> None:
    distribution = _discover("local-agent-bridge")

    console_scripts = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    assert console_scripts == {
        "local-agent-bridge": "local_agent_bridge.__main__:main_bridge",
        "local-agent-bridge-h3": "local_agent_bridge.__main__:main_h3",
    }
    assert distribution.version == "0.1.0.dev0"


def test_package_tree_contains_only_the_preview_modules() -> None:
    relative = {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert relative == EXPECTED_PACKAGE_FILES


def test_package_sources_do_not_reference_legacy_modules() -> None:
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for marker in LEGACY_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{marker}")

    assert offenders == []


def test_packaged_start_script_matches_the_frozen_blob() -> None:
    packaged = PACKAGE_ROOT / "resources" / "start_comfyui_h3.ps1"

    normalized = packaged.read_bytes().replace(b"\r\n", b"\n")

    assert hashlib.sha256(normalized).hexdigest() == FROZEN_START_SCRIPT_LF_SHA256


def test_frozen_blob_digest_detects_a_substantive_edit(tmp_path: Path) -> None:
    """Prove the digest gate is not loosened by the newline normalization."""

    packaged = PACKAGE_ROOT / "resources" / "start_comfyui_h3.ps1"
    edited = packaged.read_bytes().replace(b"--reserve-vram", b"--reserve-vram2", 1)
    probe = tmp_path / "start_comfyui_h3.ps1"
    probe.write_bytes(edited)

    normalized = probe.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized).hexdigest() != FROZEN_START_SCRIPT_LF_SHA256


def test_wheel_configuration_keeps_the_start_script_inside_the_package() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = document["tool"]["hatch"]["build"]["targets"]["wheel"]
    packaged = PACKAGE_ROOT / "resources" / "start_comfyui_h3.ps1"

    assert packaged.is_file()
    assert wheel["packages"] == ["src/local_agent_bridge"]
    assert packaged.read_text(encoding="utf-8").startswith("[CmdletBinding()]")


def test_default_h3_client_resolves_the_packaged_start_script() -> None:
    import local_agent_bridge
    from local_agent_bridge.h3 import H3ComfyClient

    client = H3ComfyClient(auto_start=False)
    # Compare against the imported package location so the check holds both in the
    # source tree and after an installation from the built archives.
    expected = (
        Path(local_agent_bridge.__file__).resolve().parent / "resources" / "start_comfyui_h3.ps1"
    )

    assert client.start_script == expected
    assert expected.is_file()


def test_h3_mcp_entry_point_imports_without_legacy_modules() -> None:
    from local_agent_bridge import __main__ as entry

    assert callable(entry.main_h3)
    tools = asyncio.run(entry.h3_server.list_tools())
    assert {tool.name for tool in tools} == {
        "h3_backend_status",
        "h3_generate_video",
        "h3_postprocess_video",
        "h3_job_status",
    }


def test_source_archives_do_not_carry_legacy_packages() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    only_include = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    assert "src/ask_ai_mcp" not in only_include
    assert "src/local_agent_bridge" in only_include
    # The archive carries this product's own README, and the retired product's
    # report pile stays out of it: only the two usage notes for the packaged
    # modules and the migration plan are expected in the source archive.
    assert "README.md" in only_include
    packed_reports = [item for item in only_include if item.startswith("docs/reviews/")]
    assert packed_reports == []


def test_session_status_is_read_only_and_key_free(monkeypatch, tmp_path, capsys) -> None:
    from local_agent_bridge import cli

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert cli.main(["session-status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["sessions"]["used_file_bytes"] == 0
    assert report["shadow"]["used_file_bytes"] == 0
    assert not (tmp_path / "LocalAgentBridge").exists()


def test_home_page_names_the_shipped_capabilities_without_claiming_release() -> None:
    home = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    for capability in ("docs/H3_USAGE.md", "docs/BRIDGE_USAGE.md"):
        assert capability in home
    assert "docs/SESSION_STORAGE.md" in home
    assert "docs/SHADOW_USAGE.md" in home
    assert "0.1.0.dev0" in home
    # It must not present itself as a formally released product.
    assert "内部预览候选" in home
    assert "不是已正式发布" in home
    assert "docs/LICENSE_PROVENANCE.md" in home
    assert "docs/RELEASE_CHECKLIST.md" in home


def test_source_archive_carries_the_new_product_documents_only() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    only_include = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    for relative in (
        "README.md",
        "docs/H3_USAGE.md",
        "docs/BRIDGE_USAGE.md",
        "docs/SESSION_STORAGE.md",
        "docs/SHADOW_USAGE.md",
        "docs/CURSOR_USAGE.md",
        "docs/CURSOR_EVIDENCE.md",
        "docs/RELEASE_CHECKLIST.md",
        "docs/LICENSE_PROVENANCE.md",
        "docs/LOCAL_AGENT_BRIDGE_MIGRATION_PLAN.md",
    ):
        assert relative in only_include
        assert (REPOSITORY_ROOT / relative).is_file()
    # The retired product's own documentation must not travel with the archive.
    # docs/legal is the one sanctioned exception: it holds this product's license
    # provenance record and permission screenshot, not retired product docs.
    packed_docs = [
        item
        for item in only_include
        if item.startswith("docs/") and not item.startswith("docs/legal/") and item.endswith(".md")
    ]
    assert packed_docs == [
        "docs/AGY_LIVE_ADAPTER.md",
        "docs/H3_USAGE.md",
        "docs/BRIDGE_USAGE.md",
        "docs/SESSION_STORAGE.md",
        "docs/SHADOW_USAGE.md",
        "docs/CURSOR_USAGE.md",
        "docs/CURSOR_EVIDENCE.md",
        "docs/RELEASE_CHECKLIST.md",
        "docs/LICENSE_PROVENANCE.md",
        "docs/LOCAL_AGENT_BRIDGE_MIGRATION_PLAN.md",
        "docs/TASK_PATH_DECISION.md",
        "docs/TASK_WORKSPACE_CONTRACT.md",
        "docs/TASK_WORKSPACE_ACCEPTANCE.md",
    ]


def test_cli_help_lists_every_subcommand_and_refuses_unknown_routes(capsys) -> None:
    from local_agent_bridge import cli

    assert cli.main(["--help"]) == 0
    help_text = capsys.readouterr().out
    for command in cli.SUBCOMMANDS:
        assert command in help_text

    assert cli.main(["not-a-command"]) == 2
    refusal = capsys.readouterr()
    assert refusal.out == ""
    assert "unknown command: not-a-command" in refusal.err


def test_every_bridge_subcommand_has_its_own_help(capsys) -> None:
    from local_agent_bridge import cli

    # Each Bridge command parses its own argv; argparse exits with status 0.
    for command in ("prepare", "collect", "plan", "run", "cursor"):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([command, "--help"])
        assert exit_info.value.code == 0
        assert capsys.readouterr().out.startswith("usage: local-agent-bridge " + command)
    with pytest.raises(SystemExit) as shadow_exit:
        cli.main(["shadow", "--help"])
    assert shadow_exit.value.code == 0
    shadow_help = capsys.readouterr().out
    for action in ("fingerprint", "snapshot", "replay", "compare"):
        assert action in shadow_help


def test_project_metadata_declares_the_license_and_installable_license_files() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]

    assert project["license"] == "AGPL-3.0-only"
    assert project["license-files"] == ["LICENSE", "LICENSES/*.txt"]


def test_restored_license_material_is_present_and_unchanged() -> None:
    """The restored bytes keep their wording, attribution and recorded digest."""
    for relative, expected_blob in RESTORED_LICENSE_BLOBS.items():
        path = REPOSITORY_ROOT / relative
        assert path.is_file(), relative
        payload = path.read_bytes()
        # The repository is checked out with core.autocrlf, so text files on disk
        # may use CRLF while the recorded blob is LF. Normalize exactly as Git
        # does for a text file, then compare the Git blob object name: any change
        # in wording, attribution or newline normalization still fails.
        if b"\0" not in payload:
            payload = payload.replace(b"\r\n", b"\n")
        header = f"blob {len(payload)}\0".encode("ascii")
        assert hashlib.sha1(header + payload).hexdigest() == expected_blob, relative

    mit = (REPOSITORY_ROOT / "LICENSES" / "MIT-jimmyloi.txt").read_text(encoding="utf-8")
    assert mit.startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in mit
    assert "Copyright (c) Minh Loi (jimmyloi)" in mit
    agpl = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert agpl.startswith("                    GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in agpl


def test_permission_screenshot_matches_the_recorded_evidence_digest() -> None:
    image = REPOSITORY_ROOT / "docs" / "legal" / "jimmy-mit-permission.png"

    assert hashlib.sha256(image.read_bytes()).hexdigest() == PERMISSION_IMAGE_SHA256
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_source_archive_carries_the_license_material() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    only_include = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    # The archive whitelist names whole directories for the license material.
    assert "LICENSE" in only_include
    assert "LICENSES" in only_include
    assert "docs/legal/PROVENANCE.zh-CN.md" in only_include
    assert "docs/legal/jimmy-mit-permission.png" in only_include


def test_default_discovery_collects_every_shipped_test_module() -> None:
    """Directory-level testpaths must equal explicit ``pytest tests`` discovery."""
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    options = document["tool"]["pytest"]["ini_options"]

    assert options["testpaths"] == ["tests"]
    shipped = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "tests").rglob("test_*.py")
    }
    assert shipped == EXPECTED_TEST_MODULES


def test_package_inventory_gate_detects_an_injected_module(tmp_path) -> None:
    """Exact set equality still rejects an extra file; the gate is not a subset check."""
    probe_root = tmp_path / "local_agent_bridge"
    probe_root.mkdir()
    for relative in EXPECTED_PACKAGE_FILES:
        target = probe_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic")
    (probe_root / "audit_notes.py").write_bytes(b"synthetic")

    relative = {
        path.relative_to(probe_root).as_posix()
        for path in probe_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert relative != EXPECTED_PACKAGE_FILES
    assert relative - EXPECTED_PACKAGE_FILES == {"audit_notes.py"}


def test_source_archive_carries_every_shipped_test_module() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    only_include = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    for relative in sorted(EXPECTED_TEST_MODULES):
        assert relative in only_include, relative


def test_first_task_r_validator_is_source_material_without_a_runtime_entrypoint() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    script = "verification/first_task_r.py"
    assert script in document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
    assert (REPOSITORY_ROOT / script).is_file()
    assert document["tool"]["hatch"]["build"]["targets"]["wheel"] == {
        "packages": ["src/local_agent_bridge"]
    }
    assert set(document["project"]["scripts"]) == {"local-agent-bridge", "local-agent-bridge-h3"}
    assert not any(
        "first_task_r" in name or "verification" in name for name in EXPECTED_PACKAGE_FILES
    )


def test_agy_reanalysis_is_source_material_without_a_runtime_entrypoint() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    shipped = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
    for name in (
        "verification/agy_stdout_reanalysis.py",
        "verification/agy_stdout_reanalysis.json",
        "verification/agy_stdout_reanalysis.schema.json",
        "docs/AGY_LIVE_ADAPTER.md",
    ):
        assert name in shipped and (REPOSITORY_ROOT / name).is_file()
    assert set(document["project"]["scripts"]) == {"local-agent-bridge", "local-agent-bridge-h3"}
    assert not any("agy_stdout" in name for name in EXPECTED_PACKAGE_FILES)


def test_source_archive_carries_both_task_contract_documents() -> None:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    only_include = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    for relative in (
        "docs/TASK_WORKSPACE_CONTRACT.md",
        "docs/TASK_WORKSPACE_ACCEPTANCE.md",
        "docs/TASK_PATH_DECISION.md",
    ):
        assert relative in only_include, relative
        assert (REPOSITORY_ROOT / relative).is_file(), relative


def test_packaged_license_text_is_not_the_retired_products_readme_or_metadata() -> None:
    """Only the license material travels; the old product's files stay out."""
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    only_include = document["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

    assert "src/ask_ai_mcp" not in only_include
    assert "mcp_server.py" not in only_include
    assert "proposal.txt" not in only_include
    assert "requirements.txt" not in only_include


def test_license_files_are_not_runtime_package_content() -> None:
    """License material is metadata/evidence, never importable package payload."""
    relative = {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert relative == EXPECTED_PACKAGE_FILES
    # Match license files, not the extracted "slice" modules which share the
    # letters "lice". No restored license path may appear in the runtime package.
    assert not any("LICENSE" in name.upper() for name in relative)
    assert not any(name.lower().endswith(".png") for name in relative)
    assert not any(name.lower().endswith("provenance.zh-cn.md") for name in relative)
