---
name: deployment-config
description: "Configure Bridge host CLIs for auto-approval with explicit boundaries: discover environment read-only, preview managed-block changes for AGENTS.md and CLI config, then write only after user confirmation. Run at first Bridge deployment or when adding a new Bridge; covers Cursor and agy on Windows. Does not install software, grant full access, or call models."
---

# Bridge 部署配置（Cursor / agy）

首次部署 Bridge 或新增 Bridge 时使用。本 Skill 只做**只读发现 → 预览 → 用户确认 → 最小写入**；日常调用走 `local-agent-bridge` Skill，安装/配置与调用分离。

## 固定流程

1. **询问启用哪些 Bridge**（Cursor / agy / 后续批准项）；未选者不写任何内容。
2. **只读环境核验**：Windows 版本、`pwsh` 7 存在性与入口。缺 pwsh 7 时建议按官方渠道安装，不代装不改 `PATH`。Bridge CLI 的 `--version` / `--help` 等非生成子命令可经用户授权后执行以核验版本（可能触发厂商自更新，如实提示）；**禁止** `-p`/`--print` 等会调用模型的子命令、MCP 操作及任何可能误触发生成的入口。
3. **生成改动预览**（文字 diff，含备份路径与回退说明）；展示后等用户确认。
4. **确认后最小写入**：备份原文 → 写入 → 复验。

详细 Bridge 差异、配置键/作用域/优先级、以及各 CLI 的已知与未验证边界见 [references/bridges.md](references/bridges.md)（按需读取）。

## 硬性边界（不可跳过）

- **自动审批与文件边界是两个独立轴**：改审批模式不得写成"已获得目录隔离"；工作目录不是 OS 沙箱。
- **不默认完全访问**：`--dangerously-skip-permissions`（agy）/ `unrestricted`（Cursor）不在候选。
- **不猜键**：证据不足的配置位置/覆盖顺序标"未核验"并写入预览警告，不写入未确认字段。
- **预览-确认-写入链路完整**；无用户确认的静默写入一律禁止。
- **幂等**：管理区块带版本标记，重复运行整块替换不追加；用户区块外原文逐字节保留。

## 三层薄化写入目标

| 层 | 边界 |
| --- | --- |
| Codex 总 `AGENTS.md` | 短入口（指向本 Skill）+ 已启用项 + 必要安全边界，单次 ≤10 行管理区块 |
| 目标 CLI 全局配置 | 仅该宿主必要的已核验键/值；不复制管理流程 |
| 日常调用 Skill（`local-agent-bridge`） | 不改；版本排障已在其中 usage 参考按需段，不重复 |

作用域优先级：**项目/任务级优先**；写全局需用户明确选择。

## 写入格式区分

- **Markdown 文件**（AGENTS.md 等）：使用 HTML 注释围栏管理区块（见 references/bridges.md）。
- **JSON 配置文件**（cli-config.json / settings.json 等）：不用围栏——以键为粒度做增量写入，保留未涉及键原值；备份为 `<file>.bridge-deploy-backup-<timestamp>`。
