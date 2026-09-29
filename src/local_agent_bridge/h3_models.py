"""Strict models for the local H3 adapter only."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject fields outside the declared H3 tool contract."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class H3ResolutionPreset(StrEnum):
    LANDSCAPE_480P = "landscape_480p"
    PORTRAIT_480P = "portrait_480p"
    SQUARE_480P = "square_480p"


class H3VisualProfile(StrEnum):
    ANIME = "anime"
    REALISTIC = "realistic"


class H3InterpolationModel(StrEnum):
    NONE = "none"
    RIFE_4_26 = "rife_4_26"
    FILM = "film"


class H3UpscaleModel(StrEnum):
    NONE = "none"
    ANIME_VIDEO = "anime_video"
    SEEDVR2_3B = "seedvr2_3b"


class H3JobState(StrEnum):
    QUEUED_OR_RUNNING = "queued_or_running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class H3GenerationCommand(StrictModel):
    """A bounded local MiniMax H3 FL2VA generation request."""

    prompt: str = Field(min_length=10, max_length=12_000)
    resolution: H3ResolutionPreset = H3ResolutionPreset.LANDSCAPE_480P
    duration_seconds: float = Field(
        default=5.0,
        ge=4.0,
        le=15.0,
        description="Requested seconds; 5-15 is recommended for the trained frame range.",
    )
    seed: int = Field(default=0, ge=0, le=9_007_199_254_740_991)
    first_frame: str | None = Field(default=None, max_length=1_024)
    last_frame: str | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def require_first_frame_before_last_frame(self) -> Self:
        if self.last_frame is not None and self.first_frame is None:
            raise ValueError("last_frame requires first_frame")
        return self


class H3BackendStatus(StrictModel):
    backend_url: str = Field(min_length=1, max_length=255)
    reachable: bool
    comfyui_version: str | None = Field(default=None, max_length=120)
    device_name: str | None = Field(default=None, max_length=240)
    required_models: list[str] = Field(min_length=4, max_length=4)
    missing_models: list[str] = Field(default_factory=list, max_length=4)
    ready: bool
    postprocess_models: list[str] = Field(default_factory=list, max_length=5)
    missing_postprocess_models: list[str] = Field(default_factory=list, max_length=5)
    postprocess_ready: bool = False
    detail: str = Field(min_length=1, max_length=500)


class H3PostprocessCommand(StrictModel):
    """A deterministic post-processing request for one selected H3 original."""

    source_video: str = Field(min_length=1, max_length=1_024)
    visual_profile: H3VisualProfile
    interpolation: H3InterpolationModel = H3InterpolationModel.NONE
    upscale: H3UpscaleModel = H3UpscaleModel.NONE
    target_fps: int = Field(default=24)
    target_short_side: int = Field(default=480)
    seed: int = Field(default=0, ge=0, le=9_007_199_254_740_991)

    @model_validator(mode="after")
    def validate_postprocess_combination(self) -> Self:
        if self.target_fps not in {24, 48, 72}:
            raise ValueError("target_fps must be 24, 48, or 72")
        if self.target_short_side not in {480, 720, 1080}:
            raise ValueError("target_short_side must be 480, 720, or 1080")
        if self.interpolation is H3InterpolationModel.NONE and self.target_fps != 24:
            raise ValueError("target_fps above 24 requires an interpolation model")
        if self.interpolation is not H3InterpolationModel.NONE and self.target_fps == 24:
            raise ValueError("an interpolation model requires target_fps 48 or 72")
        if self.upscale is H3UpscaleModel.NONE and self.target_short_side != 480:
            raise ValueError("a larger target_short_side requires an upscale model")
        if self.upscale is not H3UpscaleModel.NONE and self.target_short_side == 480:
            raise ValueError("an upscale model requires target_short_side 720 or 1080")
        if self.visual_profile is H3VisualProfile.ANIME:
            if self.interpolation is H3InterpolationModel.FILM:
                raise ValueError("anime profile supports RIFE interpolation")
            if self.upscale is H3UpscaleModel.SEEDVR2_3B:
                raise ValueError("anime profile supports AnimeVideo upscaling")
        if (
            self.visual_profile is H3VisualProfile.REALISTIC
            and self.upscale is H3UpscaleModel.ANIME_VIDEO
        ):
            raise ValueError("realistic profile supports SeedVR2 upscaling")
        if self.interpolation is H3InterpolationModel.NONE and self.upscale is H3UpscaleModel.NONE:
            raise ValueError("post-processing must enable interpolation or upscaling")
        return self


class H3PostprocessSubmission(StrictModel):
    prompt_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")
    state: H3JobState = H3JobState.QUEUED_OR_RUNNING
    source_video: str = Field(min_length=1, max_length=1_024)
    visual_profile: H3VisualProfile
    interpolation: H3InterpolationModel
    upscale: H3UpscaleModel
    target_fps: int = Field(ge=24, le=72)
    target_short_side: int = Field(ge=480, le=1080)


class H3JobSubmission(StrictModel):
    prompt_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")
    state: H3JobState = H3JobState.QUEUED_OR_RUNNING
    resolution: H3ResolutionPreset
    width: int = Field(ge=32, le=1_344)
    height: int = Field(ge=32, le=1_344)
    requested_duration_seconds: float = Field(ge=4.0, le=15.0)
    frame_count: int = Field(ge=5, le=400)
    seed: int = Field(ge=0)


class H3OutputAsset(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    subfolder: str = Field(default="", max_length=512)
    storage_type: str = Field(default="output", min_length=1, max_length=32)
    local_path: str | None = Field(default=None, max_length=1_024)
    view_url: str = Field(min_length=1, max_length=2_048)


class H3JobReport(StrictModel):
    prompt_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")
    state: H3JobState
    assets: list[H3OutputAsset] = Field(default_factory=list, max_length=20)
    detail: str = Field(min_length=1, max_length=2_000)
