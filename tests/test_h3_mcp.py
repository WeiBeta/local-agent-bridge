"""Offline contract tests for the four-tool H3 MCP surface."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from local_agent_bridge import h3_mcp
from local_agent_bridge.h3_models import (
    H3BackendStatus,
    H3GenerationCommand,
    H3InterpolationModel,
    H3JobReport,
    H3JobState,
    H3JobSubmission,
    H3PostprocessCommand,
    H3PostprocessSubmission,
    H3ResolutionPreset,
    H3VisualProfile,
)


def test_h3_surface_contains_only_local_video_tools() -> None:
    tools = asyncio.run(h3_mcp.h3_server.list_tools())

    assert {tool.name for tool in tools} == {
        "h3_backend_status",
        "h3_generate_video",
        "h3_postprocess_video",
        "h3_job_status",
    }
    assert all(len(tool.description or "") < 800 for tool in tools)


def test_generation_schema_keeps_duration_and_resolution_bounds() -> None:
    tools = asyncio.run(h3_mcp.h3_server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    command = by_name["h3_generate_video"].parameters["properties"]["command"]
    properties = command["properties"]

    assert properties["duration_seconds"]["minimum"] == 4.0
    assert properties["duration_seconds"]["maximum"] == 15.0
    assert set(properties["resolution"]["enum"]) == {
        "landscape_480p",
        "portrait_480p",
        "square_480p",
    }
    assert command["additionalProperties"] is False


def test_job_status_schema_requires_a_bounded_prompt_id() -> None:
    tools = asyncio.run(h3_mcp.h3_server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    prompt_id = by_name["h3_job_status"].parameters["properties"]["prompt_id"]

    assert prompt_id["minLength"] == 1
    assert prompt_id["maxLength"] == 128
    assert prompt_id["pattern"] == "^[A-Za-z0-9-]+$"


class _StubClient:
    """Record the exact client calls each tool makes; never starts ComfyUI."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def status(self) -> H3BackendStatus:
        self.calls.append(("status", None))
        return H3BackendStatus(
            backend_url="http://127.0.0.1:8188",
            reachable=True,
            required_models=["a", "b", "c", "d"],
            ready=True,
            detail="stub backend ready",
        )

    def submit(self, command: H3GenerationCommand) -> H3JobSubmission:
        self.calls.append(("submit", command))
        return H3JobSubmission(
            prompt_id="stub-job",
            resolution=H3ResolutionPreset.LANDSCAPE_480P,
            width=864,
            height=480,
            requested_duration_seconds=command.duration_seconds,
            frame_count=124,
            seed=command.seed,
        )

    def submit_postprocess(self, command: H3PostprocessCommand) -> H3PostprocessSubmission:
        self.calls.append(("submit_postprocess", command))
        return H3PostprocessSubmission(
            prompt_id="stub-postprocess",
            source_video=command.source_video,
            visual_profile=command.visual_profile,
            interpolation=command.interpolation,
            upscale=command.upscale,
            target_fps=command.target_fps,
            target_short_side=command.target_short_side,
        )

    def job_status(self, prompt_id: str) -> H3JobReport:
        self.calls.append(("job_status", prompt_id))
        return H3JobReport(prompt_id=prompt_id, state=H3JobState.SUCCEEDED, detail="stub done")


@pytest.fixture
def stub_client(monkeypatch) -> _StubClient:
    client = _StubClient()
    monkeypatch.setattr(h3_mcp, "get_h3_client", lambda: client)
    return client


def test_each_tool_forwards_to_the_shared_client(stub_client: _StubClient) -> None:
    assert h3_mcp.h3_backend_status().ready is True
    submission = h3_mcp.h3_generate_video(
        H3GenerationCommand(prompt="A quiet cinematic landscape with natural sound.")
    )
    postprocess = h3_mcp.h3_postprocess_video(
        H3PostprocessCommand(
            source_video="C:\\shared\\original.mp4",
            visual_profile=H3VisualProfile.ANIME,
            interpolation=H3InterpolationModel.RIFE_4_26,
            target_fps=48,
        )
    )
    report = h3_mcp.h3_job_status("stub-job")

    assert submission.prompt_id == "stub-job"
    assert postprocess.prompt_id == "stub-postprocess"
    assert report.state is H3JobState.SUCCEEDED
    assert [name for name, _ in stub_client.calls] == [
        "status",
        "submit",
        "submit_postprocess",
        "job_status",
    ]


def test_client_is_constructed_lazily_through_a_cached_factory(monkeypatch) -> None:
    created: list[str] = []
    monkeypatch.setattr(
        h3_mcp,
        "H3ComfyClient",
        lambda: created.append("built") or SimpleNamespace(),
    )
    h3_mcp.get_h3_client.cache_clear()
    try:
        first = h3_mcp.get_h3_client()
        second = h3_mcp.get_h3_client()
    finally:
        h3_mcp.get_h3_client.cache_clear()

    assert first is second
    assert created == ["built"]
