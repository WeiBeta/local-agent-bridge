---
name: local-agent-bridge
description: "Drive an already-installed Local Agent Bridge CLI: verify the approved entry point and receipt, then run native-station task dispatch, Task v1 import/prepare/plan/run/collect, or legacy source-slice workflows. Does not install, upgrade, log in, configure anything, or run H3 video work."
---

# Local Agent Bridge 调用（已安装机器）

只调用**用户已经装好**的 Bridge；不安装、不升级、不登录、不改配置、不初始化密钥。默认先只读检查，再按用户明确要求执行。支持 agy 与 Cursor 两个宿主；本 Skill 只负责日常调用，不处理 H3 MCP。

## 可选经纪会话：只执行，不裁决

使用低成本经纪会话时，管理或工程会话先备好工单、完整命令/spec、权限与预算绑定、结果位置及停止条件；经纪只按已验证步骤执行，转交非敏感状态和产物引用。遇到缺参、字段不符或其他非预期即停报，不现场编脚本、猜参数、修流程或重试。工单设计、证据核验、排障与最终验收由管理或工程会话负责；执行成功不等于验收通过。经纪模式是可选分工，不要求用户另开会话或使用指定模型。

## 1. 先定位，再检查

不要假定安装路径。依次尝试：用户给出的路径或部署回执 → `local-agent-bridge` 是否已在 `PATH`（Windows 上常为 `%USERPROFILE%\.local\bin`、`%APPDATA%\uv\tools` 或某个 venv 的 `Scripts\`）→ 询问用户。

先按回执核对实际入口和包元数据；相同版本号不代表相同安装。工单允许时才用 `--help` 核参数；禁止 CLI 查询时仅读文件资料。CLI 没有 `--version`。已有明确批准路径无需重复询问。

## 2. 选择工作流

### Native station dispatch（已配置 agy 工位）

使用管理给出的 station-capable 安装回执、spec、registry 与原字节 SHA；缺少该入口时停报，不现场升级或换到测试安装。

```text
local-agent-bridge task dispatch --spec <绝对路径> --pool-registry <绝对路径> --pool-sha256 <64位小写hex> [--execute]
```

默认 `PreparedOnly`：`launch_count=0`、`task_root=null`，尚未取得工位租约。实际任务的执行 grant、范围和预算明确后才用 `--execute`。产品在一个租约下完成 import/prepare/plan/run/collect/release；池为 1..4 位，调用共享管理冻结的 control root。dispatch 不接受下述多步流程的两个 trusted 参数。schema、角色映射及配置模式详见 [usage 的 station 段](references/usage.md#native-station-dispatch)。

### Task v1（新日常任务树）

适用于管理或用户已给出严格 JSON spec、可信控制根和 trusted-inputs SHA 的任务树：

```text
local-agent-bridge task import  --spec <绝对路径>
local-agent-bridge task prepare --spec <绝对路径> --trusted-control-root <绝对根> --trusted-inputs-sha256 <64位小写hex>
local-agent-bridge task plan    --spec <绝对路径> --trusted-control-root <绝对根> --trusted-inputs-sha256 <64位小写hex>
local-agent-bridge task run     --spec <绝对路径> --trusted-control-root <绝对根> --trusted-inputs-sha256 <64位小写hex> [--execute]
local-agent-bridge task collect --spec <绝对路径>
```

spec 路径、可信根和摘要必须来自明确工单/调用方；不要自造、修改或从 Worker 内容推导。`task run` 缺省预检；只有用户明确授权才加 `--execute`，一次一个，失败不重试。

Coding Worker 在工单指定的 task 目录和允许文件范围内，可做必要目录/源码检查、哈希核对、代码编辑、本地测试与辅助脚本操作。指定管理配方是必须完成的验收，不是 Worker 可用操作的完整清单。冻结控制、验收配方与 protected_paths 不可修改；任务外写入、凭据、额外网络、依赖安装、生产与远端仍须单独授权。

### Legacy source slice（旧小切片）

```text
local-agent-bridge prepare --commit <sha> --file <path> [--editable <path>] --task-note <path> --out <新目录> [--repository <根>]
local-agent-bridge collect --task-root <目录>
local-agent-bridge plan    --task-root <目录>
local-agent-bridge run     --task-root <目录> --run-root <新目录> --exe <绝对路径> --exe-sha256 <64位小写hex> --settings <绝对路径> [--execute]
local-agent-bridge cursor  run --task-root <目录> --run-root <新目录> --exe <agent.ps1绝对路径> --exe-sha256 <64位小写hex> [--execute]
```

旧 slice 仍只处理既有文本文件；新增、删除、重命名、符号链接与子模块会被拒绝。不要把这条旧限制误用于 Task v1 Coding 任务树。

## 3. 必须守住

- station、Task v1 与旧 slice 都不是 OS 沙箱，也不构成授权；`declared_scope` 不等于 Full Access。
- Worker 产物是候选：dispatch 已收集自己的结果，其他流程用 `task collect` 或旧 `collect`；退出 0 / `Collected` 不等于业务 Accepted，不自行应用。
- 冻结依据、spec、控制根与失败现场保留；不自动重试、不换模型、不建第二个 job。
- 管理固定配方、次数、预算与 Accepted 语义不因 Worker 可做辅助操作而放宽。Worker/CLI 自述不能替代宿主终态、加密采集、适用的配置收尾和独立验收；native `Unchanged` 与 settings 恢复分支不同，见 usage。后续任务使用本次适用 grant，不借旧波次预算。
- 上游模型身份、用量与费用通常不可观测；不要补猜。

详细参数、输出字段与排障见 [references/usage.md](references/usage.md)。
