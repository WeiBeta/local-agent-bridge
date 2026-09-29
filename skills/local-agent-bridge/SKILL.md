---
name: local-agent-bridge
description: "Drive an already-installed Local Agent Bridge CLI from another machine's Codex: locate the installed entry point, inspect help, then run bounded prepare/plan/run/collect source-slice tasks. Use when asked to slice a Git file set locally or run one fixed agy CLI invocation. Does not install, upgrade, log in, or configure anything, and is not for H3 video work."
---

# Local Agent Bridge 调用（已安装机器）

只调用**用户已经装好**的 Bridge；不安装、不升级、不登录、不改配置、不初始化密钥。默认先只读检查，再按用户要求执行。

## 1. 先定位，再检查

不要假定安装路径。依次尝试：用户给出的路径或部署回执 → `local-agent-bridge` 是否已在 `PATH`（Windows 上常为 `%USERPROFILE%\.local\bin`、`%APPDATA%\uv\tools` 或某个 venv 的 `Scripts\`）→ 询问用户。

检查只用非变更方式：`--help`、各子命令 `--help`。**CLI 没有 `--version`**；版本读包元数据（`importlib.metadata` 查 `local-agent-bridge`）。

## 2. 命令

```text
local-agent-bridge prepare --commit <sha> --file <path> [--editable <path>] --task-note <path> --out <新目录> [--repository <根>]
local-agent-bridge collect --task-root <目录>
local-agent-bridge plan    --task-root <目录>
local-agent-bridge run     --task-root <目录> --run-root <新目录> --exe <绝对路径> --exe-sha256 <64位小写hex> --settings <绝对路径> [--execute]
```

`prepare` 只导出**既有文本文件**（新增/删除/重命名被拒）；`collect`、`plan` 只读。`run` 缺省是预检，不写不改不启动；**只有用户明确授权才加 `--execute`**，一次一个。

argv、模型、effort、权限规则都由代码固定，调用方不能传。`session-key-init` 会写 Windows Credential Manager——仅在用户明确要求时执行。

`run` 退出码：0 表示生命周期完成且配置已恢复（**不等于模型任务成功**）；2 表示未改配置、未启动的拒绝，但可能留下运行目录；3 表示生命周期未完成或证据无法落盘。

## 3. 必须守住

- 只改**既有文本文件**的小切片；不是 OS 沙箱，也不构成授权。
- `run` 产物是**候选**：用 `collect` 看 diff，再由用户或独立检查验收，不要自行应用。
- 先保留冻结依据（commit + 文件清单）；失败的运行**不自动重试、不换模型、不建第二个 job**。
- 上游模型身份、用量与费用通常不可观测；不要补猜。

详细参数、输出字段与排障见 [references/usage.md](references/usage.md)（随本 Skill 安装，已含调用所需内容）。
