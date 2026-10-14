# LAB-BASELINE-RECEIPT-FIX-01

2026-10-14 / Asia/Shanghai。**目标红项已修复并自检通过；未独立 Accepted。** 下一门禁为管理安排的独立窄核，Cursor 继续暂停。

## 根因与最小修复

完整读取管理树 WORK_LEDGER 最新「HELP独立审查核收／B01与实测准备并行」安全并行 A 节。目标 `tests/test_first_task_r.py::test_installation_verifier_checks_real_fixture_bytes_and_origin` 构造的合成 deployment receipt 未带 `contract_version`，`task_run._verify_runtime_identity` 在 `fault == "none"` 分支读取该键时抛 KeyError，即已复现的 B01 基线红。

该合成链与内部 helper 既有 v1 合同一致：`_verify_runtime_identity` 在 v1 分支直接核 `host_entry` 与 `host_identity_files`，v6 分支才调用 `agy_host.checked_entry`（会要求 `identity_mode` 等字段）。因此唯一工程变更为在该测试 receipt 顶层加 `contract_version: 1` 及三行注释说明依据；不引入 `identity_mode`、不改断言、不用 xfail。生产代码、验证器与断言零改动。

## 验证结果

复用既有已核开发 venv 只读依赖，以 `-I -B` 启动并核同实际 Bridge 模块均来自本候选 worktree（24 个模块路径/SHA 记录在 target/file 的 import-before/after 文件）。

| 检查 | 结果 |
| --- | --- |
| collect | 该文件 394 nodes，exit 0 |
| 目标测试六参数叶 | 6 passed，exit 0 |
| 同文件回归 | 394 passed，273.97 秒，exit 0 |
| ruff check . --no-cache | exit 0 |
| format --check . --no-cache | exit 0，94 文件 |

未按冻结范围运行全量矩阵；原 B01 红基线证据（Archive/2026-10-14-LAB-AGY-HOST-HELP-FORMAT-REPAIR-01 的回归与基线 JUnit）保留不改，不重复红。

## 边界与保留

普通本地提交在 `codex/baseline-receipt-fix-01` 分支，最终 HEAD/tree/SHA 在本 ID HANDOFF.json 绑定。真实 CLI/model/key/安装/配置/runtime/工位/Skill/远端均为 0；仅工程工具与 pytest 子进程。

初次 `git worktree add` 在错误仓库上下文执行，返回 `invalid reference`，无任何副作用；随后在正确实现树成功创建。该失败尝试如实记录于 PREFLIGHT.json 的 `first_attempt`。

保留本 ID Scratch/Archive、全部检查原出口/JUnit/导入来源、旧红证据及原 worktree。无清理、无到期删除；删除须精确授权与引用核验。只向管理 `019fe10b-df55-7b82-a9ba-3702dc08c55f` 回执一次，送达不等于验收。
