# Local Agent Bridge 发布检查表（0.1.0.dev0 内部预览候选）

- AGY adapter 新行为需离线矩阵与独立 Review；冻结新 wheel/sdist/部署身份，不沿用旧包 SHA。source-only 重析器不得进入 wheel/MCP/CLI，第二阶段只在独立 Review 通过后的单 UID 授权下执行，详见 [AGY_LIVE_ADAPTER.md](AGY_LIVE_ADAPTER.md)。此项尚不代表真实验证或发布通过。

适用范围：Windows 11 / Python 3.13 的 `local-agent-bridge` 内部预览包。本表把发布前要做的事分成
四栏：**已验**（本机离线证据已通过）、**实机三项**（2026-09-29 已完成授权验收，逐项列出已验与未验）、
**待许可**、**待远端**。本表不是发布授权，也不是已发布声明。

## 已验（离线、可重复）

| 项 | 证据口径 |
| --- | --- |
| 源码树全套单元测试 | `uv run pytest` 的 JUnit XML，而非进度文本 |
| sdist 解包后全套单元测试 | 从构建出的 sdist 安全解包、`uv sync --locked` 后重跑 |
| 代码风格 | `uv run ruff check .` 与 `uv run ruff format --check .` |
| 构建清单与哈希 | `uv build` 的 wheel / sdist 条目数、字节数与 SHA-256 |
| 隔离安装 | wheel 装入全新 venv，确认导入来自该环境 `site-packages` |
| 入口面 | `local-agent-bridge --help` 七条子命令；六条 Bridge 子命令各自 `--help`；`shadow --help` 四种操作 |
| H3 工具面 | 只注册 `h3_backend_status`、`h3_generate_video`、`h3_postprocess_video`、`h3_job_status` |
| 旧模块隔离 | 隔离环境内 `ask_ai_mcp` 不可导入；wheel/sdist 清单不含旧包路径 |
| 合成的会话与影子入口 | 注入测试密钥与临时状态根，跑通 `session-status`、`session-key-init`（桩化）、`shadow` 四条操作 |
| 协议纯净 | MCP 入口不以非协议内容写 stdout |
| 许可实体入包 | wheel 的 `dist-info/licenses/` 与 sdist 均含 AGPL 全文与上游 MIT 正文，且与冻结 Git blob 逐字节一致 |
| 许可来源可溯 | sdist 含 `docs/legal/PROVENANCE.zh-CN.md` 与授权截图；截图 SHA-256 与来源记录一致 |

**重要口径（仅针对上表）**：上表的离线验证全部使用注入的测试密钥、临时目录与合成夹具；那些测试本身
**不**读写真实 Windows Credential Manager，也**不**启动真实 agy、provider、模型、ComfyUI、H3 或 Docker。
测试通过只覆盖已列出的构建与隔离属性，不构成真实主机可用性、生成质量或供应商行为的证据。真实资源在
下一节的独立 opt-in 验收中才被使用；不要把两节混读，也不要据上表推断实机结论。

## 实机三项（2026-09-29 已完成授权验收）

三项最小实机验证已在一次显式 opt-in 的验收任务中执行完毕（`LAB-LIVE-ACCEPTANCE-01`，送检候选
`a17f7e11f9bb1a573bebb6268945a808eb8d6a71`，已审 wheel SHA-256
`9113686f0faac75c58060a45c35aea0880814d9f87d789123c14480c49e89d09`）。逐项的确切结论与未验证边界见仓库内
`docs/reviews/LAB_LIVE_ACCEPTANCE_01.md`（报告不在本发行包内，随源码仓库与归档保留）。

| 项 | 已验证 | 仍未验证 |
| --- | --- | --- |
| 真实新密钥初始化 | `session-key-init` 恰好 1 次，返回 `session_key_created=true`，产品读回并验证 32 字节 key；只写本产品独立条目，未导出密钥 | 密钥轮换、多用户/多机同步、条目被外部破坏后的恢复 |
| 一小 agy 切片运行 | `agy.exe` 启动 1 次、退出码 0、耗时 35.548 秒、解析 `SUCCESS`；settings 前后外部哈希一致（`f8db8c3a…`）；`collect` 仅报告 `label_utils.py`；独立小测试通过；四流加密封口并完成离线 shadow snapshot/replay | 上游实际模型身份、token 用量与费用不可观测（未补猜）；CLI 模型路由不等于实际身份证明 |
| 一小 H3 生成 | 同一持续 MCP 会话内队列 0/0 后仅提交 1 次；4.0 秒 / 864×480 / seed 20260929，107 帧，`prompt_id` `d0e4ea4d-8b82-4c16-afd8-39c8774cda8d`，3 次状态读取后 `succeeded`，产物 182129 B SHA-256 `dd3a463f…` | 24 fps 来自已审查 workflow，`107/24≈4.458 秒` 仅为帧数推算；无 `ffprobe`，容器时长/帧率/分辨率未独立探测；显存释放仅知产品已请求、未测实际释放；生成质量与权重地域用途未验证 |

**后处理（`h3_postprocess_video` 插帧/超分）不在本次实机授权范围内，仍无任何实测**；不要在填写检查表时把它
当作上述三项之一、也不要因它未测而把三项写成未完成。它需要单独的显式 opt-in 验收。

H3 前次只提交 0 次属历史阶段（当时后端不可达、队列无法核验），**不代表全场 0 次**；其后端退出根因仍**未证实**，
持续会话复测**未复现**。三项均不得在普通单元测试中触发。

## 待许可

- **许可实体已补齐**（原阻断项已关闭）：`LICENSE`（AGPL-3.0-only 全文）与
  `LICENSES/MIT-jimmyloi.txt`（上游 MIT 正文与署名）已随树跟踪；wheel 的 `dist-info/licenses/` 与
  sdist 均携带两者。来源记录 `docs/legal/PROVENANCE.zh-CN.md` 与授权截图
  `docs/legal/jimmy-mit-permission.png` 亦随 sdist 分发，供溯源核对。来源、固定 Git 对象与核验边界见
  [LICENSE_PROVENANCE.md](LICENSE_PROVENANCE.md)。
- 仍待关闭：H3 / 后处理权重的 MiniMax Community License Agreement 地域与用途限制未随包核验。
- 仍待关闭：第三方依赖许可清单未做整体兼容性审查。

在以上两项关闭前，本包保持内部候选。许可实体补齐只解决材料缺项，不构成公开发布审查通过。

## 待远端

- 尚无远端仓库、tag、release 与对外分发包；产品名 `Local Agent Bridge` 仍为候选名。
- 公共远端、PR、release、tag 与正式命名均须作者明确授权，且必须在"待许可"关闭之后。
- 旧 `ask-ai-mcp` 仓库、冻结提交、历史日志与旧状态根保持原位，不迁移、不删除、不覆盖。

## 发布前须复核的声明准确性

- 文档不得把文件长度预算写成 NTFS 磁盘簇占用。
- 文档不得暗示会话会无条件持续滚动；只有完整、无引用且复验通过的整包才可能被滚动。
- 文档不得把离线影子回放写成模型复跑成功。
- 文档不得把本包写成已正式发布的产品。

## Task CLI v1 候选复核项

LAB-TASK-CLI-IMPLEMENT-01 增加 task 的五条命令；当前顶层共九条，原八条和旧 adapter 执行回执 v2 保持原合同。发布复核须以本轮新构建和 JUnit 为准，不套用上表历史验证结果。

- 18 个测试模块默认/显式有序 nodeids 相等且无重复；test_task_cli.py 随 sdist 分发。
- 精确 runtime 清单包含 task_cli.py；C 运行身份包含实际 cli.py/task_cli.py。
- 新 sdist 构建 wheel；metadata、entry_points、全部 RECORD 项和源码/许可原字节核对；全新隔离环境锁定、离线、非 editable 安装，导入来自其 site-packages。
- 安装后的本产品根 help、task help 和五条 Task 子 help 为静态检查；不调用真实 agy/Cursor 的帮助或版本。
- 同批独立 Review 待验；首次真实 Task R/bootstrap、真实 Task 宿主、部署和 Skill 更新另需后续范围。目录 manifest 资源风险仍为依赖，不声明已解决。

## 首次观测合同 v2 候选复核项

LAB-FIRST-R-OBSERVATION-CONTRACT-01 改变共享 receipt 加载源码和首次验证材料，必须使用该候选的新包身份；原实机/Review04 wheel SHA 不能支持它的部署或实测。

- 旧 v1 不静默放宽；v2 空组成清单只能明确 Unknown/FirstObservation，伪身份、重复 exe、未知键/版本和非空接受清单拒绝。
- 普通 Plan/run 继续 Blocked/NotRun0；验证程序 v2 只保存观察，不产生 Ready/Accepted；实际 Shell/命令证据仍接受前必需。
- 原计数、中断、恢复、文件及完整目录反例在 v1/v2 同时通过；针对/全pytest/JUnit、Ruff/format 和全部模块默认/显式有序发现逐项核对。
- 新 sdist/wheel 全部源码payload、RECORD及元数据核验，验证程序只进sdist；新冻结 wheel 的隔离非editable安装和实际导入身份需有对应证据，未做项如实登记。
- 独立Review、新适用实测许可、真实 Shell/命令取证、生产部署与 Skill 更新各自核收；历史失败材料及自动修复上限不重置。


## trusted_coding_v1 候选发布门禁

- deployment receipt v3/Plan v2 与旧 v1/v2 分支分别核对；profile/auth 完整 SHA、task scope、实际入口/版本与 Unknown 组成不可混淆。
- wheel 包含 bridge/layered_acceptance.py；sdist 包含 test_layered_acceptance.py 及现有合同/接受表/本清单。独立 copy 安装核验 import/文件集合，不复用旧 runtime 或 live 授权。
- 三个必需层与可选 Worker 来源分开；Eligible 不自动变 Accepted，strict R 固定 Unverified。生产 runtime 没有本轮自动接受记录，历史材料不追溯改写。
- 独立 Review、对应实机验证、生产接受/部署仍是分开的门禁；完整 CRUD/rename/真实强制超时未覆盖时不能写产品全能力 Pass。

## 显式 v3 首次分层执行候选复核项

- [ ] fresh 独立 Review 核闭合 v3 permit/env、唯一 waiver、预算/权限、排他消费、跨 task/Plan/receipt/identity/根漂移及旧v1/v2兼容；离线自检不代替该门禁。
- [ ] 普通未接受 v3 run 仍 NotRun/0；普通 collect 不自动发现首次记录。显式 collector 核原 Blocked Plan、许可/marker 原字节、实际 run/UID 与候选整树。
- [ ] 原 Plan/blockers、失败、0/1/null、中断均留存；没有真实/合成 Accepted 写入，没有清除旧 blocker 或重用旧 marker/UID。
- [ ] 管理固定两条本地 recipe 独立事实完整，实际 candidate 六例与 baseline 一例预期失败；Worker XML 不可代替，失败/超时/漂移不重试。
- [ ] 新 sdist 包含首次程序及配套测试；wheel 仅含既有产品文件，受影响 C/B 源码和 runtime 身份重新冻结。旧 wheel/uv sync 不作为生产刷新。
- [ ] 实现自检、独立复审、真实 host/key/config/native/恢复/进程行为、部署与业务接受分别核收；旧56Unrun/1平台skip不因本次候选而提升。
