# Bridge 配置参考（按需读取）

本参考承载详细差异与已知/未验证边界；SKILL.md 只保留流程与硬性边界，不重复此处内容。

## 共通边界

- 启动 CLI 的 Shell 与 Worker 执行命令的 Shell 可能不同，逐项记录不混写。
- 当前产品 runner 依赖 pwsh 7；未经验证不自动降级或放宽。
- 厂商自动更新允许；必要时按官方方法手动更新，不默认禁更新或永久锁版本。版本排障见 `skills/local-agent-bridge/references/usage.md`。
- 自动审批 ≠ 文件隔离；`cwd`/workspace 不是 OS 沙箱。

## Cursor CLI

### 已核验事实（来源：LAB-CURSOR-AUTOAPPROVAL-RESEARCH-01，2026-10-03）

| 项 | 值 |
| --- | --- |
| 全局配置 | `%USERPROFILE%\.cursor\cli-config.json` |
| 项目级配置 | `<project>\.cursor\cli.json`（**只能配 permissions**；approvalMode 等只能全局） |
| 审批键 | `approvalMode`：`allowlist`（默认）/`auto-review`/`unrestricted` |
| 权限规则 | `permissions.allow` / `permissions.deny`；**deny 优先于 allow**（官方+实现核验） |
| 启动参数 | `--force`（= `unrestricted` 等效）/ `--auto-review`（与 --force 互斥）/ `--sandbox <mode>` |
| 合并语义 | 项目级深度合并到全局之上；**数组整体替换不追加** |

### 产品现状与建议

- **Bridge 已固定 `--force`**（产品 `cursor run` 固定 argv），因此**不需要也不应在全局另设 `approvalMode: "unrestricted"`**——那等于把仅限 Bridge 会话的放行扩展为该用户所有 Cursor CLI 会话。
- 文件边界由**项目级** `.cursor/cli.json` 的 `permissions.allow/deny` 承担（Bridge `prepare --file .cursor/cli.json` 将其作为冻结输入），目录约束在任务层而不在全局。
- 如果需要非 Bridge 会话也有免交互：讨论 `auto-review`（服务器分类器自动放行安全操作），而非 `unrestricted`。

### 未验证（如实告知用户）

- 本 Skill 证据链（2026-10-03 抓取 + 实现 JS）覆盖版本 `2026.10.01-e373342`；后续版本行为可能变化。

## agy（Antigravity CLI）

### 已核验事实（来源：LAB-AGY-AUTOAPPROVAL-RESEARCH-01 + LAB-AGY-PERMISSION-CONFIG-DECISION-01，2026-10-03）

| 项 | 值 |
| --- | --- |
| CLI 用户级设置 | `%USERPROFILE%\.gemini\antigravity-cli\settings.json` |
| 共享/IDE 层 | `%USERPROFILE%\.gemini\config\config.json` → `userSettings` |
| 审批键 | `toolPermission`：`always-proceed` / `request-review` / `strict` / `proceed-in-sandbox` |
| 工作区外开关 | CLI 层 `allowNonWorkspaceAccess`（bool）；共享层 `nonWorkspaceFileAccessPolicy` |
| 权限规则 | `permissions.allow` / `permissions.deny`（`command()`/`read()`/`write()` 规则；`unsandboxed` 已废弃） |
| 全放行标志 | `--dangerously-skip-permissions`（覆盖会话级 always-deny，不推荐） |

### 两键候选与本机现状

```json
// %USERPROFILE%\.gemini\antigravity-cli\settings.json 新增（保留既有 trustedWorkspaces）：
{
  "toolPermission": "always-proceed",
  "allowNonWorkspaceAccess": false
}
```

- 本机**已写入**此两键（主控 2026-10-03 执行，非本 Skill）。
- 共享层 `nonWorkspaceFileAccessPolicy=AGENT_SETTING_POLICY_ALLOW` **未改**（作者选择不动 GUI）。
- **Windows 仍用旧权限系统**（官方 permissions 页）；两键在 Windows 的实际合并/覆盖顺序**未验证**。

### 产品兼容性硬约束（LAB-AGY-PERMISSION-CONFIG-DECISION-01 核实）

- **`permissions` 持久键与现有 Bridge 不兼容**：Bridge `_read_settings` 检测到根 `permissions` 键即在启动前拒绝——**不得**向 CLI settings.json 添加持久 `permissions` 对象。
- Bridge 会在执行期间临时插入任务级 `permissions.allow` 并在 `finally` 内原字节恢复；不覆盖 `toolPermission` 或 `allowNonWorkspaceAccess`。
- `--settings` 是 Bridge 的文件修改目标（用户 CLI 设置文件），不是配置选择参数。

### 未验证（如实告知用户）

- 两键在 Windows 的实际审批行为与工作区外拒绝效果。
- `permissions.deny` 对 `always-proceed` 的优先级在 Windows 的实际表现（官方文档说 deny 优先，本机未测）。
- CLI 层 `allowNonWorkspaceAccess=false` 与共享层 `ALLOW` 的合并顺序。

## 兼容表（持续维护）

| Bridge | 官方来源及核验日 | 启动 Shell | Worker Shell | 本机实测 | 指令文件与作用域 | 降级支持 |
| --- | --- | --- | --- | --- | --- | --- |
| Cursor | docs 2026-10-03 | pwsh 7（产品固定） | 同启动 | 产品合成 smoke 通过（10-01）；审批行为未实测 | 项目 `.cursor/cli.json`（仅 permissions）+ 全局 `cli-config.json` | 无（pwsh 7 依赖） |
| agy | docs 2026-10-03 | 直接 exe（Bridge argv） | 同启动 | 两键已写入未验效；权限行为未知 | CLI `antigravity-cli/settings.json` + 共享 `config/config.json` | 无（pwsh 7 辅助依赖） |

## 管理区块格式

所有写入使用如下围栏（版本号递增），重复运行整块替换：

```text
<!-- bridge-deploy-config:v1 BEGIN -->
... 管理内容 ...
<!-- bridge-deploy-config:v1 END -->
```

CLI JSON 配置不用围栏；以键为粒度做增量写入（保留未涉及键原值），备份为 `<file>.bridge-deploy-backup-<timestamp>`。
