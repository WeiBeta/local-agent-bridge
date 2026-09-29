"""Four-tool H3 MCP surface for the Local Agent Bridge preview package."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from local_agent_bridge import __version__
from local_agent_bridge.h3 import H3ComfyClient
from local_agent_bridge.h3_models import (
    H3BackendStatus,
    H3GenerationCommand,
    H3JobReport,
    H3JobSubmission,
    H3PostprocessCommand,
    H3PostprocessSubmission,
)

H3_SERVER_INSTRUCTIONS = """
Use these tools only for bounded local MiniMax H3 video generation and explicit
ComfyUI post-processing. Poll submitted jobs with h3_job_status; terminal jobs
release model GPU memory while leaving ComfyUI running.
""".strip()

h3_server = FastMCP(
    "Local Agent Bridge H3",
    instructions=H3_SERVER_INSTRUCTIONS,
    version=__version__,
)


@lru_cache(maxsize=1)
def get_h3_client() -> H3ComfyClient:
    """Create the loopback ComfyUI client lazily after MCP initialization."""

    return H3ComfyClient()


@h3_server.tool(
    annotations=ToolAnnotations(
        title="MiniMax H3 本地后端状态",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def h3_backend_status() -> H3BackendStatus:
    """必要时启动本机 ComfyUI, 再检查 GPU 和必需的 MiniMax H3 模型。"""
    return get_h3_client().status()


@h3_server.tool(
    annotations=ToolAnnotations(
        title="提交 MiniMax H3 本地视频生成",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def h3_generate_video(command: H3GenerationCommand) -> H3JobSubmission:
    """异步提交本地 H3 文生视频或首尾帧生视频任务。

    仅连接本机回环地址, 输出含原生立体声音频。调用者须遵守 MiniMax H3
    许可地域和可接受使用政策; 任务提交后使用 h3_job_status 轮询。
    """
    return get_h3_client().submit(command)


@h3_server.tool(
    annotations=ToolAnnotations(
        title="后处理已筛选的 MiniMax H3 原片",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def h3_postprocess_video(command: H3PostprocessCommand) -> H3PostprocessSubmission:
    """对共享工作区中的已筛选 H3 原片执行显式插帧、超分或组合任务。

    调用者必须明确选择卡通或写实分组及具体模型; ComfyUI 不推断画风。
    原片不会被覆盖, 最终资产写入共享 outputs/postprocessed 目录。
    """
    return get_h3_client().submit_postprocess(command)


@h3_server.tool(
    annotations=ToolAnnotations(
        title="查询 MiniMax H3 本地视频任务",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def h3_job_status(
    prompt_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")],
) -> H3JobReport:
    """查询异步 H3 任务并在完成后返回路径, 队列空闲时自动释放显存。"""
    return get_h3_client().job_status(prompt_id)
