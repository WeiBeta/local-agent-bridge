---
name: deployment-config
description: "Configure Bridge host CLIs on Windows or verify reuse of approved agy native stations: discover the approved installation and mode, preview necessary configuration changes, then apply only authorized changes. Covers Cursor and agy; does not install software, grant full access, or call models."
---

# Bridge 部署配置（Cursor / agy）

首次部署、新增 Bridge 或复用已配置原生工位时使用。先只读发现；有配置增量时走**预览 → 适用授权 → 最小写入**。软件安装走独立部署工单，日常调用走 `local-agent-bridge` Skill。

## 固定流程

1. **核对已批准目标与模式**（Cursor / agy native station / agy settings）；用户或冻结工单已明确时直接沿用，缺少必要选择时才询问；未选者不写。
2. **只读环境核验**：先查批准路径/部署回执、实际 exe 与包元数据，不按目录名或相同版本字符串推定活动安装。核对 Windows 及该模式所需的 pwsh/Python 入口；缺项只报告，不代装或改 PATH。上游 help/version 可能触发厂商自更新，只在工单允许时调用；禁止查询时仅读文件资料。Bridge 无 `--version`，获准的 `--help` 只核命令入口。禁止 `-p`/`--print`、MCP/backend 等生成入口。
3. **生成必要增量预览**：列文字 diff、备份与回退。已有适用批准覆盖具体变更时直接执行该范围；实质新增配置权限才请求确认。无差异不重写。
4. **授权内最小写入**：备份原文 → 写入 → 复验。复用已配置 native station 时只给部署绑定预览，不写 global settings、原生 record 或 AGENTS；新增/迁移 Project 先明确其配置范围。

native station 的 registry/身份绑定、settings 模式差异及 Cursor 配置细节见 [references/bridges.md](references/bridges.md)，只读当前模式所需段落。

## 硬性边界（不可跳过）

- **自动审批与文件边界是两个独立轴**：改审批模式不得写成"已获得目录隔离"；工作目录不是 OS 沙箱。
- **不默认完全访问**：`--dangerously-skip-permissions`（agy）/ `unrestricted`（Cursor）不在候选。
- **不猜键**：证据不足的配置位置/覆盖顺序标"未核验"并写入预览警告，不写入未确认字段。
- **预览与适用授权覆盖实际写入**；不能把 Skill 调用或只读发现当作新增配置授权。
- **幂等**：管理区块带版本标记，重复运行整块替换不追加；用户区块外原文逐字节保留。

## 有配置增量时的写入目标

以下按实际增量选择，不是每次部署的必写清单；已配置 native station 复用不写前两层。

| 层 | 边界 |
| --- | --- |
| Codex 总 `AGENTS.md` | 短入口（指向本 Skill）+ 已启用项 + 必要安全边界，单次 ≤10 行管理区块 |
| 目标 CLI 全局配置 | 仅该宿主必要的已核验键/值；不复制管理流程 |
| 日常调用 Skill（`local-agent-bridge`） | 本配置流程不顺带修改；文档更新/同步走其专门工单 |

作用域优先级：**项目/任务级优先**；写全局需用户明确选择。

## 写入格式区分

- **Markdown 文件**（AGENTS.md 等）：使用 HTML 注释围栏管理区块（见 references/bridges.md）。
- **JSON 配置文件**（cli-config.json / settings.json 等）：不用围栏——以键为粒度做增量写入，保留未涉及键原值；备份为 `<file>.bridge-deploy-backup-<timestamp>`。
