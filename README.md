# Local Agent Bridge 0.1.0.dev0（内部预览包候选）

本发行源码树是 Windows 11 / Python 3.13 的**内部预览候选**，不是已正式发布的产品，也没有公共远端、tag、
release 或对外分发包。它的范围是从旧 Ask AI MCP 冻结提交 `725333c2e345a01faf04475b4b3bcdade91fdd3c`
按白名单抽取的四项本地能力，加上本次收口的发行面材料。旧仓库的完整工具列表、计费、Source、Review 与
toolsmith 内容不属于本包，本文件取代旧 README 作为本包首页。旧 Ask AI MCP 的 README、旧实现与全部历史
仍原样保留在其**原仓库**（本仓库不包含它们，也不复制其内容）；本仓库是从该仓库按白名单导出的精简发行候选。

本包提供的能力：

1. **本地 MiniMax H3 视频工具**：四个 MCP 工具，只连接本机回环 ComfyUI；见 [docs/H3_USAGE.md](docs/H3_USAGE.md)。
2. **固定 agy 切片桥**：从某个 Git commit 取显式文件清单、回收只读 diff、打印固定主机计划，并可选执行
   **一次**本机 CLI 运行（argv、模型、effort 与权限规则全部由代码固定）；见 [docs/BRIDGE_USAGE.md](docs/BRIDGE_USAGE.md)。
3. **加密会话**：把一次 Bridge 运行实际可取得的输入与 CLI 原字节写成本产品独立密钥的 AES-256-GCM 分帧
   会话，按文件长度计量、整包滚动；见 [docs/SESSION_STORAGE.md](docs/SESSION_STORAGE.md)。
4. **离线影子回放**：只读取已封口会话，输出内容无关的终态、工具/文件集合与用量观察，并可保存自包含重加密快照；
   不回放指令、不调用模型；见 [docs/SHADOW_USAGE.md](docs/SHADOW_USAGE.md)。

## 安装与安装资源

需要 Windows 11、Python 3.13 与 `uv`。开发与验证使用：

```powershell
uv sync --locked
uv run local-agent-bridge --help
uv run local-agent-bridge-h3
```

wheel 内只包含 `local_agent_bridge` 包与两个打包资源：`resources/start_comfyui_h3.ps1`（H3 后端启动脚本）
与 `resources/ag_slice_run_private.ps1`（切片桥的 ACL 辅助脚本）。两者都按包内相对路径定位，安装后
**不依赖源码树**；`uv run` 只用于本仓库内的开发流程。

## 入口与命令

两个控制台入口：

| 入口 | 作用 |
| --- | --- |
| `local-agent-bridge` | 切片桥 CLI：`prepare`、`collect`、`plan`、`run`、`session-status`、`session-key-init`、`shadow` |
| `local-agent-bridge-h3` | 只注册四个 H3 MCP 工具的标准输入输出 MCP 服务 |

`local-agent-bridge --help` 列出七条子命令与当前限制。各子命令用各自 `--help` 查看参数；实际参数为：

```text
local-agent-bridge prepare --commit <sha> --file <path> [--editable <path>] --task-note <path> --out <new dir> [--repository <root>]
local-agent-bridge collect --task-root <dir>
local-agent-bridge plan    --task-root <dir>
local-agent-bridge run     --task-root <dir> --run-root <new dir> --exe <absolute path> --exe-sha256 <64 hex> --settings <absolute path> [--execute]
local-agent-bridge session-status
local-agent-bridge session-key-init
local-agent-bridge shadow {fingerprint|snapshot|replay|compare} ...
```

`run` 缺省只做预检：不写文件、不启动进程。`--execute` 是单独的一次性授权，执行一次固定本地 CLI 调用。

在另一台机器上让 Codex 调用已安装的 Bridge：见 [skills/local-agent-bridge](skills/local-agent-bridge/SKILL.md)（Skill 只做调用，不安装、不升级、不登录、不改配置）。

## 主机前提（本包不安装、不迁移）

- H3：仓库外 `C:\AI\ComfyUI`、H3 与后处理权重、共享视频工作区；启动脚本固定使用
  `127.0.0.1:8188`、`--reserve-vram 2` 与隐藏窗口。
- 切片桥：调用方自备的本机 CLI 可执行文件、其 SHA-256 与 settings 路径；PowerShell 7
  (`C:\Program Files\PowerShell\7\pwsh.exe`) 与 `git`。
- 加密会话：只使用本产品独立的 Windows Credential Manager 条目
  `LocalAgentBridge.SessionCapture.v1` / `aes256gcm-session-v1`，由 `session-key-init` 显式创建；
  不读取旧 API 凭据。

上述环境变量名、配置项与限制在对应文档中逐项列出。本包不改动主机配置、不安装权重、不创建远端。

## 状态与容量

会话域与影子域默认位于 `%LOCALAPPDATA%\LocalAgentBridge\sessions` 与 `...\shadow`，两域各
`104857600` 字节上限。该上限按**目录内文件长度之和**计量，不是 NTFS 簇分配字节。密文、帧开销、
清单、收据、`.quota.lock`、活动 `.partial`、失败残件与未知文件都计入。

滚动不是无条件持续行为：只有完整、已重新校验且无引用的整包才可能按最旧顺序被滚动移除，删除前先写
内容无关的 `delete_intent` 收据；仅有受保护项、部分包、未知文件或篡改包时报告 `over_limit` 并停止
新写入，不清理无法验证的材料。旧 v1 样本原位保留、新读取器拒绝，既不迁移也不重加密，但**仍占用所在域额度**。

## 已知边界（如实声明）

- **验证状态是混合的**：包自带的测试套件全部为离线合成（不启动真实 agy、provider、模型、ComfyUI、H3
  或 Docker）；另有一轮 2026-09-29 的显式 opt-in 实机验收：真实密钥初始化 1 次、真实 agy 切片运行 1 次
  （退出码 0、解析 `SUCCESS`）、真实 H3 生成 1 次（4.0 秒 / 864×480 / 107 帧、`succeeded`，产物
  SHA-256 `dd3a463f…`）。仍**未**验收：MCP 客户端接入、主机部署、H3 容器时长/帧率独立探测、显存实际
  释放、后处理、agy 上游身份与费用可见性。逐项边界记录在导出来源仓库的验收报告
  （`docs/reviews/LAB_LIVE_ACCEPTANCE_01.md`）与本地归档中；该报告与原始日志**不在本仓库**，也不随发行包分发。
- 切片桥只覆盖既有文本文件的小切片；不支持新增/删除文件、跨根 diff、二进制内容、并发运行或 Zcode。
- 该工具不是 OS 沙箱，不构成任何授权；`plan` 不是批准。
- 任务工作副本与 `run_root/private/settings.*.bin` 仍可能是 ACL 私有明文：加密会话不代表整机无明文。
- 离线影子回放不能推断未出现在 CLI 管道中的隐藏模型能力，也不构成模型复跑成功或候选接受。

## 许可与发布边界

本项目整体采用 **AGPL-3.0-only**（仅 GNU Affero General Public License 第 3 版），全文见 [LICENSE](LICENSE)；
上游作者 Jimmy 的 MIT 许可与署名保留于 [LICENSES/MIT-jimmyloi.txt](LICENSES/MIT-jimmyloi.txt)。
许可实体已随本发行树补齐：wheel 的 `dist-info/licenses/` 与 sdist 均携带 AGPL 全文与上游 MIT 正文。
来源、固定 Git 对象、截图证据与核验边界见 [docs/LICENSE_PROVENANCE.md](docs/LICENSE_PROVENANCE.md) 与
[docs/legal/PROVENANCE.zh-CN.md](docs/legal/PROVENANCE.zh-CN.md)；发布前检查表见
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)。

许可实体补齐**只解决材料缺项**，不代表已通过公开发布审查：尚未做第三方依赖许可整体兼容性审查、
未核验 H3 权重地域与用途限制、未创建远端或对外包。H3 权重与后处理权重依 MiniMax Community License Agreement 等各自
条款，未捆绑进本包，对外分发前须另行核验。

产品名 `Local Agent Bridge` / `local-agent-bridge` 仍为候选名。

开发协作与署名说明见 [CREDITS.md](CREDITS.md)。
