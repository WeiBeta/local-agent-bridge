# Local Agent Bridge 发布检查表（0.1.0.dev0 内部预览候选）

## 当前阶段状态（2026-10-13）

- 源码仓库已建立为 `WeiBeta/local-agent-bridge`。2026-10-04 的
  `LAB-DELIVERY-PUBLISH-01` 已记录普通分支 `codex/delivery-consolidate-01` 的源码交付，
  提交为 `7a5d921ed2402023b5b21417b12362ed8da5c1d6`；这不是正式 tag、Release 或发布包的验收。
  此处引用当时的交付记录，不声称重新查询了当前远端状态。
- 后续 agy 四工位候选 `0e28d2bd09c88fcc2cecff9564eb6e2c8192db28` 已完成独立离线审查，
  2026-10-12 的管理裁定接受正常无人干预四路重叠、第五单等待复用的 Coding/Review/Testing/Mixed 范围。
  原自动 audit 的 Unknown 与后续补证、管理裁定分别保留，不将其改写为原 audit 全部通过。
- 同一冻结 wheel（SHA-256 `a66a7e170c529bf50b248a5319b9e8ce70eb315d5380aa04d921e1c2e4d5be8e`）
  已于 2026-10-13 完成本机并排安装、依赖/帮助/四工位 PreparedOnly 检查；本次模型启动为零，
  不算新的真实业务复测。配套两份 Skill、共四个文档已同步本机；Skill 随源码交付，不在该 wheel/sdist 内。
- 上述结果不外推为 Cursor 新 Task、任意并发规模、所有异常恢复或正式发行通过。
  本机路径、配置、原始捕获和密钥不随源码发布；详细材料按同名任务 ID 在管理归档中溯源。

下方按候选陆续增加的条目保留其原阶段范围。未勾选的历史检查项不是当前阻塞清单，
也不因本节更新而逐项追认为通过；后续发行以精确候选和对应验收记录确定适用项。

## Cursor 已授权 workspace v5（2026-10-13）

候选 `180cb430f4728f0e4d3a2f77d5854635b6ffb4c6` 已完成实现自检（2636 通过、
1 项 Windows 链接权限跳过）及 `LAB-CURSOR-AUTHORIZED-WORKSPACE-REVIEW-01`
fresh 独立离线复核（112 通过、无 actionable finding）。仅新增 15 行生产代码，
复用公开 Task prepare/plan/run/collect，不引入新配置租约或首单 waiver。

- v5 严格绑定 Cursor、同一明确授权的 `grant_ref`、`declared_scope` 和空 `runtime_acceptances`；
  Plan Ready 不是业务 Accepted。旧 v1–v4 的字段、接受条件及两宿主预算保留。
- 任务目录内正常工程读写、测试与必要子进程按授权开放；目录外副作用另行控制。
  不把命令字面一致、OS 沙箱或全部异常恢复证明列为普通任务的启动前置。
- 本次源码汇合后的运行代码、测试与锁文件须与已审候选一致。新构建必须绑定新 wheel、
  实际导入身份及安装回执；不得用旧 `a66a7e17…` 安装代替新 v5 候选。
- 下一步是适用新授权下的单次合成 Coding+Testing 实测、受保护材料及必要来源核验和本地独立复测。
  当前真实 Cursor、并发、生产部署和该候选远端交付均未完成；不能用 Gemini 4+1 或旧 slice 结果代替。

## 历史候选与检查范围

- LAB-BRIDGE-DEADLINE-1H-01候选：Task全部已有角色及agy/Cursor上限3600秒，较短值保持；验证3600/3601和类型边界、两host剩余预算/argv、早退、timeout/异常恢复、task/permit/budget一致性及旧slice1020/15m兼容。自测不替代fresh独立Review或真实验收。
- 新一小时实测包须冻结新wheel/runtime、task/root/grant、permit/预算及全部身份/hash绑定，纠正新任务说明中过时unapproved提示，最外shell立即保存LASTEXITCODE并显式传播退出码；不得改旧失败现场或复用已消费许可。确认agy新增分钟值的原生支持、Cursor/provider/tool更早期限和最外工具停止合同，另列恢复/封口/collect/复测预算，不把3600作为全流程上界。先新授权单任务成功，再另做配置隔离和双任务验证；本候选不实现并发。

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
| 入口面 | 2026-09-29 基线为 `local-agent-bridge --help` 七条子命令；Task CLI 候选后现行入口共九条，发布时按下文 Task CLI 复核项重新核验 |
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

以上两项保留为正式 tag/Release 或对外分发包前的待核验事项；许可实体补齐只解决材料缺项。
不据此否定已经作者授权的普通源码分支交付，也不把未捆绑权重的核验列为普通源码分支推送的新前置。

## 远端与正式发行

- 早期“尚无远端”记录已由上方 2026-10-04 源码交付更新；当前产品使用 `Local Agent Bridge` 名称。
- 新的普通源码分支推送仍须有适用授权；已有公开仓库或历史成功推送不自动授权下一次写入。
- PR、tag、Release 与对外分发包各按其实际范围取得授权；正式发行仍须核对上方许可未决项。
  本表不声称已经创建这些发行对象。
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

## agy 原生项目模式候选复核项

- [ ] fresh 独立 Review 核 native_project 的完整 receipt/R/Plan 绑定、唯一资源根=cwd=task_root、有界普通记录读取及紧前漂移拒绝。
- [ ] 无全局 settings 读取/写入/租约，原模式的锁/恢复和 Cursor 仍保持；fake 重叠只作离线证据，不能升级为真实并发/隔离。
- [ ] 请求脚本/输出绝对路径，固定 argv 仅增项目 ID；启动后绑定检查材料经原 collector 留存，主中断、原失败和 0/1/null 不降级。
- [ ] 优先复用现有 A/B 根的窄合同另完成：保留旧证据，明确新输出空间和 exact inventory；不得通过清根、嵌套 cwd、手写项目 JSON 绕过当前 RootNotFresh/ControlChanged。
- [ ] 新冻结部署材料、接受/首次执行材料适配、真实双调用许可、业务 artifact-first 验收和生产部署各自核收；当前只为离线候选，原预算不续借。

## 四工位薄 dispatch 候选复核项

- [ ] fresh 独立 Review 核注册表/policy/receipt v4 与旧 v1/v2/v3 分支；v4 Ready 不等于 Accepted，不迁移旧运行接受。
- [ ] 真 Windows 合成多进程四 owner、第五等待/取消/释放复用、遗弃与持久 Running、单根故障/其他根继续；不使用进程内锁冒充跨进程锁。
- [ ] 每站 Coding/Review/Testing/Mixed 范围均可运行；新 UUID 根/请求/CID/capture/result 独立，旧任务字节保留；每单 collect/release 不等全池结束。
- [ ] 业务红/Review findings 与控制失联区分；0/1/null、transport 失败和 Unknown 保留；终态落盘失败不返回成功；不自动清理、重跑或修复暂停根。
- [ ] 新 wheel 带 station_pool/station_task；sdist 带两份新测试及四份同步文档；实际导入源码身份包含两模块。pyproject 仅扩充 sdist 测试清单，uv.lock 不变。
- [ ] 离线 pytest/JUnit、ruff/format 和失败证据完整；自检后冻结精确 commit 交独立 Review，再集中授权四路真实重叠加第五单复用。真实运行、包安装、生产接受和部署分别核收。

## Cursor v5 配置收尾候选复核项

- [ ] fresh 独立 Review 核仅 v5 收尾改变：启动前仍 raw hash；项目精确控制、必要 global 字段/未知字段/类型与数组顺序保持；仅容忍既有 bool 显示/提示叶子与固定后端已证的三处 cache.updatedAt 数字值。
- [ ] cache 严格对象，时间戳严格 int/有限 float；对象/叶子存在性和未知兄弟保留，实际 privacy/身份/路由/sandbox/model/permissions 控制不放宽，不忽略整个 cache 或默认值物化。
- [ ] launch/lifecycle-failure 的 cursor_configuration_status 仅固定非敏感分类；无值/正文/任意未知键名/摘要，新分组不替代完整控制门禁；collector 兼容保留，原失败码与主异常/诊断写入优先级不变。
- [ ] 正常/异常/中断的无害维护、必要语义漂移、损坏/消失/新增、紧前漂移、project/IO 失败及主异常优先均有离线 JUnit；旧 Cursor v1 与 agy v1–v4 适用回归不放宽。
- [ ] RunReceipt/Plan/CLI schema 不变，无新证据文件/锁/全局回写/正文落盘，v5 Unchanged 为必要语义未变；B collect 继续不自动业务接受。
- [ ] 历史 CursorConfigurationUnverified/RestoreFailed 原失败保留，具体 2 字节变更与 actor/语义仍 Unknown；新代码不能追认旧 Passed。
- [ ] 启动前共享 global raw 漂移及非持续快照限制明确；真实 CLI/并发/部署需新冻结身份和适用授权，离线通过不升级为生产接受。
- [ ] 第二轮 metadata 修订的源码依据不证明 LIVE-02 确切 diff 或根因；LIVE-01/LIVE-02 原失败保留，fresh 独立 Review 为下一门禁，第三次实测未授权。

## agy receipt v6 更新解耦候选复核项

- [ ] fresh 独立 Review 核仅显式 v6 StableInstalledEntry，旧 v1–v5 strict 不变，registry v1/policy/Project/任务/lease 及 Bridge/toolchain/catalog 精确绑定；未吸收暂停 Cursor 候选。
- [ ] native-conversation 固定错误分类复核：503容量、其它/缺失/类型不明、成功无错误、成功但带错误、凭据/URL/userinfo、多行与超长输入均有正负例；只有Observed且matched才归属类别，Mismatch/Unknown两字段null，SUCCESS带error使用中性说明；重复 init/result与CID/cwd/model/toolCID失败仍原语义，SUCCESS/blockers/退出/权限/锁/时限不变，且回执不含任意上游文本。
- [ ] R01–R10 聚焦 JUnit：稳定根正常更新；旧合同/closed shape；来源逃逸；两条原 launcher RAM 诊断；help 宽容；已闭合失败释放；未知挂起；单观察 SHA/task-plan/脱敏；必要 native 终态与附加事件；中断/NotRun。
- [ ] wheel 含实际 agy_host 模块，sdist 含新测试与共享夹具清单；只更新分发清单，不加依赖或改 uv.lock；适用回归、ruff/format 与原 exit/JUnit 保留。
- [ ] 管理冻结一次候选迁移的 wheel/canonical catalog/new receipt/profile/registry 摘要及两个无 prompt 诊断额度；保留旧部署和报告，不拿源码 sync 代替运行刷新。
- [ ] 另按适用授权验证真实 version/help 无模型语义、正常首单、计数 2+1 和四位释放/复用；离线、自检、独立 Review、发布、业务接受分别报告。本实现真实 CLI/model/key/capture、生产/配置/Skill/远端为 0。
- [ ] 说明 TOCTOU、磁盘 SHA 非内存 image/厂商认证、旧 provenance 仅快照、真实后端/上游模型/费用 Unknown；正常失败释放不代表兼容或 Accepted。

## 实际 agy Help 格式修复候选复核项

- [ ] fresh 独立 Review 核 Help 双流投影仅发生在原成功门禁之后，Version/launcher/WinJob/schema/额度不变。
- [ ] 核原 Usage 夹具 Git blob 为 2905 字节，SHA256 `337622c6dcdcb204312277570c4173dda83f3cbf006629f0eabe657069071e7c`；checkout 仅允许 CRLF-to-LF 后核同原文。
- [ ] 复核真实 stdout/stderr、重复一致/冲突、缺项、正文伪命中、本行枚举及旧 wrapped enum/alias/拒绝回归；重复冲突不能由先后覆盖。
- [ ] fresh 独立 Review 核 `tests/fixtures/agy-help-1.3.4.txt` 的显式 sdist 纳入、实际包成员/原 SHA 及解包源码导入来源；配套自检见 HOST-HELP-PACKAGING-01 报告，不替代独立接受或全量基线红项核收。
- [ ] 保留原自检失败、外层测试超时与最终结果的区别；离线通过不追认 LIVE-03，也不自动恢复真实调用或 Cursor。
