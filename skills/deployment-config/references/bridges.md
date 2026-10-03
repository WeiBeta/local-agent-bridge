# Bridge 配置参考（按需读取）

本参考承载详细差异与已知/未验证边界；SKILL.md 只保留流程与硬性边界，不重复此处内容。

## 共通边界

- 启动 CLI 的 Shell 与 Worker 执行命令的 Shell 可能不同，**逐项记录不混写**；不因启动器类型推定 Worker Shell。
- 当前产品 runner 依赖 pwsh 7；未经验证不自动降级或放宽。
- 厂商自动更新允许；必要时按官方方法手动更新，不默认禁更新或永久锁版本。版本排障：优先定位已安装 `local-agent-bridge` Skill 中的 usage 参考按需段；该 Skill 不在时查厂商官方文档，**不假设源码仓库布局**。
- 自动审批 ≠ 文件隔离；`cwd`/workspace 不是 OS 沙箱。

## Cursor CLI

### 已核验事实

| 项 | 值 | 来源 |
| --- | --- | --- |
| 全局配置 | `%USERPROFILE%\.cursor\cli-config.json` | [官方 configuration](https://cursor.com/docs/cli/reference/configuration)，2026-10-03 |
| 项目级配置 | `<project>\.cursor\cli.json`（**只能配 permissions**；approvalMode 等只能全局） | 同上 |
| 审批键 | `approvalMode`：`allowlist`（默认）/`auto-review`/`unrestricted` | [官方 parameters](https://cursor.com/docs/cli/reference/parameters)，2026-10-03 |
| 权限规则 | `permissions.allow` / `permissions.deny`；**deny 优先于 allow** | [官方 permissions](https://cursor.com/docs/cli/reference/permissions)，2026-10-03 |
| 启动参数 | `--force`（= `unrestricted` 等效）/ `--auto-review`（与 --force 互斥）/ `--sandbox <mode>` | 同上 |
| 合并语义 | 项目级深度合并到全局之上；**数组整体替换不追加** | 官方 + 本机实现 JS 核验，2026-10-03 |

### 产品现状与建议

- **Bridge 已固定 `--force`**（产品 `cursor run` 固定 argv），因此**不需要也不应在全局另设 `approvalMode: "unrestricted"`**——那等于把仅限 Bridge 会话的放行扩展为该用户所有 Cursor CLI 会话。
- 任务目录与可编辑面是声明范围；`--force` 下未被显式 deny 的操作可放行。项目级 permissions 规则是许可增量而非天然完整目录边界；已测 marker 拒读不外推清单外项。
- 如果需要非 Bridge 会话也有免交互：讨论 `auto-review`（服务器分类器自动放行安全操作），而非 `unrestricted`。

### 本机历史参考（非目标机事实）

- 2026-10-03 合成产品 smoke 中，项目级 permissions 配置的文件读取/编辑与 deny 规则在 `--force` 下行为正常（Bridge 加密捕获认证通过）。此为本机一次性观测，不外推其他安装或后续版本。

### 未验证（如实告知用户）

- 本 Skill 证据链覆盖版本 `2026.10.01-e373342`；后续版本行为可能变化。
- 非 Bridge 会话下 `auto-review` 的实际审批行为。

## agy（Antigravity CLI）

### 已核验事实

| 项 | 值 | 来源 |
| --- | --- | --- |
| CLI 用户级设置 | `%USERPROFILE%\.gemini\antigravity-cli\settings.json` | [官方 CLI reference](https://www.antigravity.google/docs/cli/reference/)，2026-10-03 |
| 共享/IDE 层 | `%USERPROFILE%\.gemini\config\config.json` → `userSettings` | 同上 |
| 审批键 | `toolPermission`：`always-proceed` / `request-review` / `strict` / `proceed-in-sandbox` | 同上 |
| 工作区外开关 | CLI 层 `allowNonWorkspaceAccess`（bool）；共享层 `nonWorkspaceFileAccessPolicy` | 同上 |
| 权限规则 | `permissions.allow` / `permissions.deny`（`command()` / `read_file()` / `write_file()` 规则；`unsandboxed` 已废弃） | [官方 permissions](https://www.antigravity.google/docs/permissions?tab=cli)，2026-10-03 |
| 全放行标志 | `--dangerously-skip-permissions`（覆盖会话级 always-deny，不推荐） | 本机 `--help`，2026-10-03 |

### 两键候选（非安装要求）

如下增量仅当用户明确选择时写入（保留未涉及键原值）：

```text
%USERPROFILE%\.gemini\antigravity-cli\settings.json 新增：
  "toolPermission": "always-proceed"
  "allowNonWorkspaceAccess": false
```

### 本机历史参考（非目标机事实）

- 2026-10-03 作者决策选择自动审批并保留目录约束后，主控已在本机写入上述两键；共享层 `nonWorkspaceFileAccessPolicy` 保持不动。此为本机历史操作记录，**不作为其他机器的已配置状态**。

### 产品兼容性硬约束

- **`permissions` 持久键与现有 Bridge 不兼容**：Bridge `_read_settings` 检测到根 `permissions` 键即在启动前拒绝——**不得**向 CLI settings.json 添加持久 `permissions` 对象。因此本 Skill **不教持久 permissions 写法**。任务目录与可编辑面是声明范围；Bridge 临时插入的 permissions.allow 只是许可增量，不添加 deny/ask 规则，也不收窄共享 ALLOW。未命中 allow 的操作不等于被拒绝。
- Bridge 会在执行期间临时插入任务级 `permissions.allow` 并在 `finally` 内原字节恢复；不覆盖 `toolPermission` 或 `allowNonWorkspaceAccess`。
- `--settings` 是 Bridge 的文件修改目标（用户 CLI 设置文件），不是配置选择参数。

### 未验证（如实告知用户）

- **Windows 仍用旧权限系统**（官方 permissions 页 2026-10-03）；两键在 Windows 的实际审批行为与工作区外拒绝效果。
- `permissions.deny` 对 `always-proceed` 的优先级在 Windows 的实际表现（官方文档说 deny 优先，本机未测）。
- CLI 层 `allowNonWorkspaceAccess=false` 与共享层 `ALLOW` 的合并顺序。

## 兼容表（持续维护）

| Bridge | 官方来源及核验日 | 启动 Shell | Worker Shell | 本机实测 | 指令文件与作用域 | 降级支持 |
| --- | --- | --- | --- | --- | --- | --- |
| Cursor | [configuration](https://cursor.com/docs/cli/reference/configuration) 2026-10-03 | pwsh 7（产品固定） | 未核验 | 合成 smoke 文件流程+deny 正常（2026-10-03，限该范围） | 项目 `.cursor/cli.json`（仅 permissions）+ 全局 `cli-config.json` | 无（pwsh 7 依赖） |
| agy | [CLI reference](https://www.antigravity.google/docs/cli/reference/) 2026-10-03 | 直接 exe（Bridge argv） | 未核验 | 两键已写入未验效（本机历史，非目标机事实）；权限行为未知 | CLI `antigravity-cli/settings.json` + 共享 `config/config.json` | 无（pwsh 7 辅助依赖） |

## 管理区块格式

### Markdown 目标（AGENTS.md 等）

```text
<!-- bridge-deploy-config:v1 BEGIN -->
... 管理内容 ...
<!-- bridge-deploy-config:v1 END -->
```

版本号代表块格式协议版本，仅在格式变更时更新。相同请求与现状应无 diff，不变则不重写或新增备份。发生实际内容更新时替换既有块，用户区块外原文逐字节保留。

### JSON 目标（CLI 配置文件）

JSON **不能**使用 HTML 注释围栏；以键为粒度做增量写入（保留未涉及键原值），备份为 `<file>.bridge-deploy-backup-<timestamp>`。
