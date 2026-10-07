# Local Agent Bridge 切片桥使用说明（预览包）

适用版本：`local-agent-bridge` 0.1.0.dev0（内部预览候选）；平台：Windows 11；Python 3.13。
本模块从冻结提交 `725333c2e345a01faf04475b4b3bcdade91fdd3c` 的 `scripts/ag_slice_workspace.py`、
`scripts/ag_slice_run.py` 与 `scripts/ag_slice_run_private.ps1` 提取；SESSION 阶段随后把管道持久化改为加密会话，保留单次启动与配置恢复合同。

## 1. 命令

| 命令 | 作用 |
| --- | --- |
| `local-agent-bridge prepare` | 从本仓库某个完整 commit 取显式文件清单，写入全新任务根（`baseline/`、`work/TASK.md`、`work/` 副本与 `manifest.json`） |
| `local-agent-bridge collect` | 只读回收：核验冻结面，输出单行 JSON 摘要与 unified diff 到 stdout |
| `local-agent-bridge plan` | 只读输出固定主机运行计划（cwd、读写路径、规则串、模型、argv），`execution_authorized=false` |
| `local-agent-bridge run` | 默认 preflight（不写不改不启动）；`--execute` 执行一次固定本地 CLI 运行 |
| `local-agent-bridge session-status` | 只读查看 sessions / shadow 两域文件长度用量，不读取 key |
| `local-agent-bridge session-key-init` | 显式初始化本产品独立 Windows 会话密钥 |
| `local-agent-bridge shadow` | 离线验证、快照、回放或比较已封口会话；详见 [SHADOW_USAGE.md](SHADOW_USAGE.md) |
| `local-agent-bridge cursor` | 对冻结任务根执行一次固定 Cursor CLI 调用（grok-4.7-high，非 Fast）；详见 [CURSOR_USAGE.md](CURSOR_USAGE.md) |

`local-agent-bridge --help` 列出九条顶层命令；原八条参数和默认行为保留，新增 `task` 包装五条 Task v1 操作；`local-agent-bridge-h3` 保持原四工具 H3 MCP 入口不变。

## 2. 保留的原合同

- 只处理**既有文本文件**：新增、删除、重命名、符号链接与子模块一律拒绝；可编辑面必须是已准备文件清单的子集。
- 冻结语义：内容取自指定 commit 的 Git blob 而非工作树；清单按原始字节数 + SHA-256 绑定，diff 只按 LF 拆行，不给文件补换行。
- 单次固定调用：`run` 的 argv、模型（`gemini-3.8-flash-high`）、effort（`high`）、`--output-format stream-json`、
  `--disable-slash-commands`、`--print-timeout 15m` 均由代码固定；调用方不能传 argv、模型或权限规则。
- 可执行文件必须给定绝对路径与其 SHA-256，身份不符即拒绝，未知可执行文件绝不启动。
- 配置生命周期：原始字节备份、精确插入本计划的只读/可写规则、`finally` 内恢复；并发语义漂移不被覆盖，恢复被阻断时该次运行不算成功。
- 运行根全新且不复用；运行根不得位于任务根或安装包目录内。源码树仓库内、`src/local_agent_bridge` 之外的路径不再由旧仓库级规则拒绝。`private/` 与 `capture/` 通过固定 PowerShell 辅助脚本施加仅属主可继承 ACL。
- 进程收束：CREATE_SUSPENDED 生成 → Job 归属 → 线程归属核验后恢复；任何失败都通过自有句柄与 Job 回收，不存在普通生成回退。
- 退出码：0 表示生命周期完成且恢复已验证（不等于模型任务成功）；2 表示未改配置、未启动的受控拒绝；3 表示生命周期未完成或证据无法落盘。

## 3. 当前限制（如实声明）

- `run --execute` 对 `work/TASK.md`、固定 CLI 请求参数及 stdout/stderr 原字节使用独立会话密钥加密；`capture/` 不再有永久原始管道副本。必须先显式运行 `session-key-init`；缺 key 会在启动前拒绝。容量、读取格式和宿主明文边界见 [SESSION_STORAGE.md](SESSION_STORAGE.md)。
- 会话存储目录首次创建时施加仅属主 ACL；后续进程只读核验已有目录的精确 ACL，不重施 `Set-Acl`。不符合要求则在加密输入写入和 CLI 启动前拒绝。
- `shadow` 只处理 sealed v2 证据，读取时必须提供明确 UID 与输入摘要；自包含快照另占 shadow 域预算，不调用本地 CLI、模型或 Docker。
- `cursor` 只做一次固定调用与加密捕获，退出码 0 不表示模型任务成功；无工具包含或文件隔离承诺（见 CURSOR_USAGE.md）。
- 任务工作副本与 `private/settings.*.bin` 仍可为 ACL 私有明文，旧材料不迁移；本包仍为内部候选，不应作为正式可部署版本发布。
- 只覆盖既有文本文件的小切片；不支持新增/删除文件、跨根 diff、二进制内容、ignore 规则或并发运行。
- 不是 OS 沙箱，不构成授权；`plan` 不是批准，也不证明当前 CLI 能力。
- 未做 Zcode 适配；本包不包含任何第 Zcode 相关实现或空壳。

## 4. 凭据与主机约定

本包只为加密会话读取本产品独立的 Windows Credential Manager 密钥；`session-key-init` 是唯一显式创建入口，不访问旧 API 凭据。运行 `--exe`/`--settings` 指向的是调用方自备的本机 CLI 与配置文件，
由调用方负责其权限与内容。包内不捆绑 agy、模型或 ComfyUI，也不改动主机配置。

## 5. 已验与未验边界

**离线（本包自带测试）**：临时合成 Git 仓库、伪造可执行文件、伪造 settings 与受控桩函数；不启动真实
agy、provider、模型或 Docker。

**实机（2026-09-29 一次显式 opt-in 验收，已验证部分）**：`agy.exe` 确认启动 1 次，子进程退出码 0、耗时
35.548 秒、产品解析终态 `SUCCESS`；固定计划仅允许写一个文件，`collect` 只报告该文件变化；settings 外部前后
SHA-256 一致（`f8db8c3a99d02e99bcd9034a13beb43d26d642bec84ba34ce7df2e9af1627af6`），产品已恢复原始字节；
四条加密流封口成功，并完成离线 shadow snapshot/replay。逐项证据见仓库内
`docs/reviews/LAB_LIVE_ACCEPTANCE_01.md`（报告不在本发行包内）。

**仍未验证**：

- **上游实际模型身份、token 用量与费用不可观测**；CLI 请求的模型路由（`gemini-3.8-flash-high` / `high`）
  **不等于**经独立验证的上游实际模型身份，也不得据此报告用量或费用。agy 内部上游请求次数同样不可观测。
- 候选补丁未应用到任何仓库；该次运行未被当作模型能力或候选接受证据。
- 真实主机部署、MCP 客户端接入与服务化部署未验收；并发运行、超大切片与失败恢复的真实语义未实测。
- 只覆盖既有文本文件的小切片；不支持新增/删除文件、跨根 diff、二进制内容或 Zcode。

## 6. 执行回执版本（离线候选，LAB-LEGACY-LAUNCH-RECEIPT-02）

本候选新生成的 `run --execute` stdout摘要及 `run.json` 使用 `schema_version=2`，包括执行阶段的受控拒绝摘要；preflight与`plan.json`保持各自的v1，sessions加密格式仍为既有v2。没有新增命令参数。历史v1回执不重写、不迁移：旧`launches=0`只能按当时记录解释，不能据它推断未知原生执行，也不把历史字段补成新观测。

v2的`launches`是`0/1/null`，来自本次调用方持有的同一份LaunchLifecycle：确证未执行=0，观测确认执行=1，潜在执行尚未确认=null。后续捕获、配置恢复或回执写入失败不能把1降成0/null；不能把null按真值规则当0，亦不能当成功或自动再启动。`launch_attempts`仍只记录是否调用过共享启动入口，不能替代执行计数。

顶层`spawn_state`保留原词表：confirmed（已确认）、not_confirmed（调用过但未确认，包括unknown）、not_attempted（尚未调用）。未知与确知零由`launches`准确区分。正常返回的`launch`仍为原capture记录；异常未返回capture记录时，`launch`是既有生命周期记录（spawn_state/launch_count/stage/pid/pid_created_filetime/cleanup），未观测清理结果保留null，不推断全部后代已退出。没有新增顶层字段。

未知或启动后异常仍为既有`launch_failed`/非成功退出；捕获不完整保留`capture_incomplete`，已知正常结果与0/2/3退出码语义保持。原始中断在独立尽力收尾/回执尝试后继续传播，次生恢复/写入错误不替换它，不重试任何启动或写入。

仓内CLI只转发结果，没有读取旧执行回执的产品解析器；task collect使用独立`contract_version=1`合同并明确拒绝这两种旧adapter回执，不能跨合同误读。外部读取器须显式支持v2或拒绝未知版本；外部兼容、真实CLI/部署与本候选独立Review尚未验收。归档索引：`C:/Users/user/Documents/Codex-Archive/2026-10-06-LAB-LEGACY-LAUNCH-RECEIPT-02/INDEX.md`。

## 7. Task v1 CLI 候选

五条 `task import/prepare/plan/run/collect` 的命令和 spec 表见 [TASK_WORKSPACE_CONTRACT.md](TASK_WORKSPACE_CONTRACT.md) §11，验收矩阵见 [TASK_WORKSPACE_ACCEPTANCE.md](TASK_WORKSPACE_ACCEPTANCE.md) §11。Task 的 A 输入支持冻结工程字节树；目录导入的 manifest 读取复用 package_bytes_limit 做 stat 加实际 limit+1 有界读取，声明 entries 先过 entry_count_limit 预门禁，超限在哈希与解码前拒绝，不新增 policy 键。旧切片命令仍遵守上文既有文本限制。

`prepare/plan/run` 的可信根和 bundle 摘要必须由管理作为单独 CLI 参数供给；不能写进 spec 或从 Worker/任务内容自算接受。Cursor 仅 task plan 可准备管理绑定的固定项目文件，原始模板字节保留。task run 默认在新运行根保存 NotRun，不初始化 key、不启动；显式 --execute 仍须原 C 全部门禁，无新 Task R 合法 Blocked。
stdout 是原业务 JSON 加一个传输 LF，固定错误在 stderr；CLI 退出码不构成业务接受。离线 fake/self-check、独立 Review、首次真实 R 与部署分别记录，本候选没有实机声明。

普通计划写入异常退出 2，原中断退出 130，材料原样保留。receipt 存在但 plan 缺失，或 Cursor 材料存在而计划不完整时，原 B collect 必须报告 ControlChanged、scope_status=Fail、continuation=null；纯 prepare 无这些材料仍合法。读取句柄保持有效到最终路径复核及最后一次句柄变化观察；这是有限观察，不保证观察后文件不变。LAB-TASK-CLI-REPAIR-01 自检仍须新的独立 Review。

### 首次 Task R 的独立验证材料

`verification/first_task_r.py` 随源码发行材料保存，wheel没有此脚本或新入口。它只供可信管理者在另行批准的冻结验收单下验证单一agy/Coding/execute能力；普通 `task run --execute` 仍须Accepted R。当前只有离线实现/自检，真实方案和许可仍未批准，不能照着本节直接运行实际host。

未来单独授权后的调用形状为：冻结安装的Python，以 `-I -B` 运行冻结脚本，只有 `--acceptance-sheet <管理固定绝对路径>`、`--expected-sha256 <派工独立供给的raw SHA>` 两个参数。没有model/argv/host命令、skip-R、解密或任意执行入口。验收单需准确记录Approved/author_confirmed=true、全部权限、一次宿主启动与预算引用、程序/非editable安装/wheel/环境/recipe/控制材料身份；完整schema见 TASK_WORKSPACE_CONTRACT.md，不能从源包自填“我可信”。实际provider请求数/费用不由次数1证明，程序不是预算平台或OS沙箱。

许可排他消费后失败也不重用；正常Plan保持Blocked，生命周期调用明确标作验证程序所得。validation.json的ObservationRecorded仅表示观测已保存，Failed/Interrupted保存缺口；R始终Unverified，独立核验与管理接受另做。程序不覆盖旧控制或删除失败，不读取历史会话/导出key/解密。专用LOCALAPPDATA只在该进程内临时设置并恢复，真实agy会继承，其兼容性、登录和Worker Shell实际使用未验；后续普通入口复用R须管理核对同环境适用范围，不自动验收默认生产state根。

B只在既有null-run模式回收本验证候选，transport仍NotRun，验收项Unrun。独立生命周期事实另存，不能作为Blocked Plan下的普通run回执交B。正常B对此回执仍返回RunReceiptInvalid；验证程序不更改该门禁，也不宣称正常run真实贯通。

45a22cf的落盘缺失P1已被独立Review拒绝；LAB-FIRST-TASK-R-REPAIR-01仅提出修复候选。修复程序重读固定run与本地launch/restore证据、实际B result/artifacts及同任务控制/环境，不用C/B返回对象哈希替代保存证明。缺失/漂移/错绑定失败也保留原0/1/null启动事实和原中断；opaque会话引用只记录声明，不能据此断言密文或命令已实测，不解密。修复自检不批准ArtifactsOnlyNullRun模式，仍须新的独立Review及另行真实许可；本轮没有runtime安装、完整发行复建或真实调用。

LAB-FIRST-TASK-R-REPAIR-02处理Review-02的新增P1：未绑定的saved run不能先提供计数。优先保留本调用可信C返回的明确0/1；没有明确返回时核固定launch的自洽事实及已绑定、基本生命周期有效的run本体，两者任一确认1保留1，没有1时保留已核来源的明确0，无法确认则null。相反零/缺失/无效/unknown均不能消除有效run本体的已知1。证据不完整仍Failed/Interrupted、无效run hash=null，原中断、consumed和原字节保留，不自动重试。此为第2且最后自动Repair候选，仍需fresh Review，不能据零计数或自检结果另启真实调用。

作者另行批准LAB-FIRST-TASK-R-REPAIR-03窄修复与独立离线审查，不重置自动轮次。验证候选现在将当前authored/generated work、out、scratch的完整目录映射与实际result目录逐项对应，计入B固定根和必要生成祖先。合法收集前空目录继续复制；收集后新增/缺失/错映射或多余result目录拒绝完整观测，同时保留启动事实、原中断和原字节。仍待管理安排独立Review-04，真实R未验收；B.NotRun只描述null-run收集，不能解释为整个验证从未启动。
