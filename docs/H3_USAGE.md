# Local Agent Bridge H3 预览包使用说明

适用版本：`local-agent-bridge` 0.1.0.dev0（内部预览候选）；平台：Windows 11；Python 3.13。
产品名仍为暂定名，尚未确定远端或对外发布方式。

## 1. 本包范围

本包只包含从冻结提交 `725333c2e345a01faf04475b4b3bcdade91fdd3c` 抽取的本地 MiniMax H3 能力：
一个仅连接本机回环 ComfyUI 的适配器、严格 H3 数据模型、四个 MCP 工具和随包分发的 ComfyUI 启动脚本。
不含旧 Ask AI MCP 的 Coding、Review、Source、计费、toolsmith 入口。同一发行包内的切片桥、加密会话与
离线影子回放是独立模块，H3 工具面本身不依赖它们；总览见包根 `README.md`。

## 2. 入口与工具面

H3 能力由控制台入口 `local-agent-bridge-h3` 暴露：该入口启动后只注册以下四个工具，工具名与旧版完全相同。
整包有两个控制台入口——`local-agent-bridge-h3`（H3 MCP）与 `local-agent-bridge`（切片桥 CLI）——本节只描述前者。

| 工具 | 用途 |
| --- | --- |
| `h3_backend_status` | 必要时启动本机 ComfyUI，再检查 GPU、4 个 H3 权重与 5 个后处理权重 |
| `h3_generate_video` | 异步提交 480p/24fps 低成本原片（4–15 秒） |
| `h3_postprocess_video` | 对人工选中的原片执行显式插帧/超分 |
| `h3_job_status` | 查询任务终态、返回本地路径与查看地址，队列空闲时释放显存 |

适配器只接受 HTTP 回环地址（默认 `http://127.0.0.1:8188`）；URL 含凭据、查询串或子路径会被拒绝，
且客户端不读取系统代理设置。输入图片、源视频必须先落入配置白名单根，越界、软链接或超大文件会被拒绝。

## 3. 主机前提与配置

ComfyUI、模型权重与共享视频工作区都在仓库之外，本包不安装、不迁移、不修改它们。
启动脚本随包安装在 `local_agent_bridge/resources/start_comfyui_h3.ps1`，其内容与旧仓库脚本逐字节相同，
仍固定使用 `C:\AI\ComfyUI`、回环 `127.0.0.1:8188`、`--reserve-vram 2` 与隐藏窗口；如主机布局不同，
用环境变量指向自己的脚本或路径，而不是修改包内资源。

环境变量（沿用旧版名称，便于从旧部署迁移）：

| 变量 | 含义 |
| --- | --- |
| `ASK_AI_MCP_H3_URL` | 回环后端地址，默认 `http://127.0.0.1:8188` |
| `ASK_AI_MCP_H3_INPUT_ROOTS` | 允许的参考帧根，分号分隔 |
| `ASK_AI_MCP_H3_COMFY_INPUT_ROOT` | ComfyUI 可见输入目录（暂存参考帧与选中视频） |
| `ASK_AI_MCP_H3_OUTPUT_ROOT` | 输出根，用于把文件映射为本地路径 |
| `ASK_AI_MCP_H3_WORKSPACE_ROOT` | 共享工作区根，后处理源视频必须位于其中 |
| `ASK_AI_MCP_H3_AUTO_START` | 缺省 `1`，后端不可用时尝试启动脚本 |
| `ASK_AI_MCP_H3_START_SCRIPT` | 自定义启动脚本绝对路径 |
| `ASK_AI_MCP_H3_START_TIMEOUT_SECONDS` | 启动等待上限，5–600 秒 |
| `ASK_AI_MCP_H3_AUTO_FREE_VRAM` | 缺省 `1`，终态且队列空闲时请求卸载模型 |

**自定义 URL 或根目录时须同步处理启动脚本**：包内 `start_comfyui_h3.ps1` 逐字节固定了
`C:\AI\ComfyUI`、`...\H3-Workspace` 与端口 8188，且不接受参数；适配器只会用 `-File` 直接执行它。
因此覆盖 `ASK_AI_MCP_H3_URL`、输入输出根或工作区根中的任一项时，必须同时把
`ASK_AI_MCP_H3_START_SCRIPT` 指向适配该布局的自备脚本，或设 `ASK_AI_MCP_H3_AUTO_START=0`
并自行启动正确服务；否则自动启动仍会拉起硬编码端口与目录上的服务，适配器探测地址或根目录将不可达或错位。
本预览包保留本机默认布局，不做脚本参数化。

## 4. 已验与未验边界

**离线（本包自带测试）**：MockTransport 合成后端、临时目录文件与合成 PowerShell 替身；不启动真实 ComfyUI、
H3、agy、模型或 Docker。

**实机（2026-09-29 一次显式 opt-in 验收，已验证部分）**：同一持续 MCP 会话内队列 0/0 后仅提交一次 4.0 秒 /
864×480 / seed 20260929 请求，107 帧，`prompt_id` `d0e4ea4d-8b82-4c16-afd8-39c8774cda8d`，3 次状态读取后
`succeeded`；产物 182129 字节 SHA-256 `dd3a463f709a71cd1182a3fb065dae5d62e8415ffa7317bd9af745199b4e9934`。
后端此前短暂退出的原因**未证实**，持续会话复测**未复现**。逐项证据与哈希见仓库内
`docs/reviews/LAB_LIVE_ACCEPTANCE_01.md`（报告不在本发行包内）。

**仍未验证**：

- **24 fps 来自已审查 workflow 的固定设置**；`107 / 24 ≈ 4.458 秒` 只是帧数推算，现场无 `ffprobe`，
  实际容器时长、帧率与分辨率未独立探测。
- 显存：产品终态报告"已请求卸载模型并释放显存"，**这是产品请求，未测量实际空闲显存**。
- **后处理（`h3_postprocess_video` 插帧/超分）无任何实测**，需单独的显式 opt-in 验收。
- 真实主机部署（注册 MCP 入口、改动主机配置）与 MCP 客户端接入（Claude Desktop / Codex Desktop）未验收。
- 生成质量结论、长时间或并发生成、权重地域与用途合规未验证。

许可：本项目整体采用 **AGPL-3.0-only**，全文见 [LICENSE](../LICENSE)；上游作者 Jimmy 的 MIT 许可与署名保留于
[LICENSES/MIT-jimmyloi.txt](../LICENSES/MIT-jimmyloi.txt)。许可实体**已随本发行树补齐**（wheel 的
`dist-info/licenses/` 与 sdist 均携带），来源与核验边界见 [LICENSE_PROVENANCE.md](LICENSE_PROVENANCE.md)。
H3 权重受 MiniMax Community License Agreement 约束，权重**未捆绑**进本包，对外分发或商业使用前须另行核验其
地域/用途限制。
