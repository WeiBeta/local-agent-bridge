# 统一工程任务验收矩阵 v1

状态：`ProposedRecommended`；以下为实施/验收规格，不是已有功能通过记录。
任务 LAB-TASK-WORKSPACE-CONTRACT-01；2026-10-04；冻结 base `7a5d921ed2402023b5b21417b12362ed8da5c1d6`。
合同：[TASK_WORKSPACE_CONTRACT.md](TASK_WORKSPACE_CONTRACT.md)。管理任务：019fe10b-df55-7b82-a9ba-3702dc08c55f。

## 1. Gate 与证据口径

| Gate | 可以执行的内容 | 通过后可声明 | 不能据此声明 |
| --- | --- | --- | --- |
| D：本阶段文档核验 | 精确 base/allow-list、官方/GitHub/源码只读检查；stdlib 内存探针；现有无上游 fixture 单测及格式检查 | 合同、分包和验收规格可审阅 | 新 importer、Coding/Review、命令执行或隔离已经实现/可用 |
| O：新实现离线验收 | 合成 Git/ZIP/目录、伪 CLI/进程树、注入 key/root、捕获回放与 profile fixture | 软件合同与拒绝分支通过 | 真实 agy/Cursor、Windows 原生权限、真实 provider 成功 |
| R：宿主能力验收 | 独立授权的本机版本/配置定位和非模型 CLI/沙箱/测试 runner 小样例 | 该版本、该配置、该测试路径/工具面效果 | 100%任务能力、任意路径隔离、供应商模型身份 |
| V：两宿主真实任务 | 独立授权、每项清楚的真实调用额度；同 snapshot 分别运行 Coding 与 Review | 该 host/role/profile 的具体业务项通过 | 未测 profile/项目、其他模型或后续 CLI 版本自动通过 |
| I：集成与发行 | 精确 current main 的新候选分支、冻结 allow-list、全离线回归、独立 Review、文档/Skill/打包核验 | 可集成/可部署候选及已验收能力清单 | 自动修改业务树/main、更新宿主或远端发布授权 |

本阶段只有 D。O/R/V/I 都是待执行矩阵；本阶段不执行上游 CLI，即使是 --help/--version 也不调用。常规单测允许伪 CLI fixture，不允许真实模型、H3、ComfyUI、Docker、系统凭据或历史 UID 解密。没有回执不轮询，不使用 wait_threads/heartbeat。

每个测试行必须交：case_id、fixture/input/profile/toolchain SHA、执行者/版本、开始/结束/退出码、expected/actual 判定、证据路径/哈希；失败原样保留。unrun/unverified 不能记 Pass。JUnit 属性为现有测试计数真源；CLI 退出 0、文件存在或 sealed capture 均不等于业务 Completed。门禁与 source/receipt 哈希不符不是瞬态错误，不能自动重试；新真实调用始终受本次明确额度限制。

## 2. 输入、快照与导入（A 包）

所有输入为合成 fixture；不读取业务包。ZIP 标准库探针只验证可复用 API，不代替新 importer 测试。

| ID / Gate | 输入或操作 | 必须观察的结果 |
| --- | --- | --- |
| INPUT-01 / O | Git 同一精确 commit 包含 .cs、.meta、UTF-8/中文、BOM、CRLF、无尾 LF、NUL 二进制 | 原字节、长度和哈希一致；不因后缀/UTF-8 要求拒绝工程普通文件；control TASK 不覆盖业务 TASK.md |
| INPUT-02 / O | 修改 live checkout、挂 export-ignore/export-subst、换 branch 名但仍指定同 SHA | commit bytes 不受 checkout/导出变换影响；选择清单全部绑定；不得以工作树或被过滤的 archive 替代 |
| INPUT-03 / O | 同一文件树分别来自 Git、ZIP、目录 manifest；ZIP 仅改变顺序/压缩/时间戳 | canonical snapshot_id 一致；原包 SHA 分别记录；reviewer ID/绝对路径不进入内容身份 |
| INPUT-04 / O | 目录前后内容变化、清单少/多文件、清单不可信或 SHA 不符 | InputChanged/InputManifestMismatch，启动数 0；不自动补清单/重拷，失败副本保留 |
| ZIP-01 / O | `../`、混合分隔符、绝对/UNC、C:foo/C:/foo、设备路径、ADS、NUL、保留名、尾点/空格 | 写入前拒绝；没有目标根外文件，拒绝不会“清理路径再接受”；检查原始名而非只检查截断后的 filename |
| ZIP-02 / O | 同名重复、A.cs/a.cs、NFC/NFD 冲突、a 文件+a/b、目录/文件同名 | 集合预检拒绝；正常 a/ 目录项+a/b.cs 可接受；不覆盖/去重 |
| ZIP-03 / O | UNIX symlink/mode、设备/FIFO、DOS reparse 属性、目录 junction、目录输入硬链接 | 类型拒绝；不跟随/创建；没有访问目标文件内容；缺 Windows 权限无法创建 fixture 时标 Skip/Unverified，不能算 Pass |
| ZIP-04 / O | stored/deflate 普通 ZIP；加密、不支持压缩、CRC 错、截断、伪报 size | 正常通过；异常拒绝并保留专用失败 staging；不发布 sealed manifest，不重新下载或运行模型解压 |
| ZIP-05 / O | 分别越过 64 MiB 包、20k 条目、512 MiB展开、64 MiB单项、200比率、32深度、物理路径预算 | 每项都有具名错误与实际阈值；声明预检+实际流式计数均生效；不一次性读全部解压内容，不静默扩大上限/换短路径 |
| ZIP-06 / O | staging 写入中断、磁盘不足、父路径在检查后变 reparse、已存在目标 | staging 保留且未 sealed；最终清单不可信；不覆盖原目录，竞态防护未闭合时明确阻断 |
| INPUT-05 / O | Git mode120000/160000、LFS pointer、包内 hooks/setup/宿主控制文件 | 链接/submodule 拒绝；LFS不自动联网；不执行 hooks/setup；控制冲突启动前阻断，保留所有选择/排除依据 |
| INPUT-06 / O | 普通业务 AuthToken.cs 与真实敏感路径排除规则 | 不因 token 子字符串漏源码；敏感路径仍拒绝/明确排除；不读取真实凭据作 fixture |
| SNAPSHOT-01 / O | sealed 后改一个 byte、manifest/task/profile 哈希漂移；两副本分别编辑 | drift gate 拒绝；Coding 改动不改 snapshot 或另一 reviewer；不使用共享可写树、hardlink 或 junction |

补充最小 API 样例：在 BytesIO 中创建普通 .cs、相同大小写冲突、含 NUL 的 ZipInfo，确认 infolist 保留重复条目、orig_filename 保留 NUL、按 open 流式读取原字节、ntpath.isreserved 检出 Windows 保留名。它只证明 stdlib 原语适用；新输入拒绝逻辑与物理机行为仍需上表 O/R。

## 3. 任务工作区、回收与业务状态（B 包）

| ID / Gate | 操作 | 必须观察的结果 |
| --- | --- | --- |
| TASK-01 / O | 新任务 schema；未知/重复字段、bool当int、未知 role/profile、越界根、写根落在 protected 内 | 严格拒绝且 spawn0；protected 子树可合法收紧父级 write 根；旧 slice manifest 不被当作新 task |
| CODING-01 / O | 在授权 work 新增模块/测试/目录、改已有代码、删过时文件、重命名普通文件 | collect 不拒绝新/缺文件；added/modified/deleted before/after hash准确；授权外/protected变动被判失败 |
| CODING-02 / O | 原字节同 hash 的 rename、rename后编辑、多候选重复内容、大小写改名 | 可明确关联的纯rename准确；歧义按delete/add，编辑后不伪称纯rename；Windows冲突处理，不丢产物 |
| OUTPUT-01 / O | 二进制变化、CRLF/LF/BOM/无尾换行、生成目录与新增源码同时存在 | raw bytes 保留；文本diff辅助；生成目录有单独清单/大小，源码不能被宽泛 ignore 掩盖 |
| OUTPUT-02 / O | 输出越额、新 reparse/hardlink、缺 required_output、异常 result root | scope/resource失败；保留候选和失败记录；不自动修正/应用业务树，输出根必须全新专用 |
| REVIEW-01 / O | Review 尝试改 work、正常写 out/report/findings/coverage/progress，写 scratch辅助分析 | 规则中 work不可写；collector 哈希检查原始 source；报告创建成功。规则结构离线通过不等于物理拒写，需 R |
| REVIEW-02 / O | 同 snapshot 生成两 reviewer 目录并分别修改 out/scratch | snapshot/每份 source hash一致；out完全独立；无共享候选或读另一 reviewer结果路径 |
| RESULT-01 / O | CLI success、sealed=true，但无代码/报告/必需测试或输出PENDING | transport可完整，业务为Partial/Blocked；不得记Completed或由Host替Worker补成功 |
| RESULT-02 / O | deadline/context不足；有效部分产物；仍有NotAnalyzed项 | Partial；保存未完成条目/候选hash/最后有效测试/续接依据；不自动启动 --continue/--resume |
| RESULT-03 / O | provider拒绝、preflight未授权、恢复失败、capture不足、范围失败 | blocker原因区分，原候选保留；旧退出码语义保持；不把业务失败包装成通讯失败或反之 |
| COVERAGE-01 / O | 946普通合成源码+17合成辅助文件=963项；排除/失败/未分析各注入一项 | 源码与全包分母分别稳定；所有路径一项一状态；仅Read/Grep不算Analyzed；一个源码NotAnalyzed就不能Completed |
| COVERAGE-02 / O | findings为空、缺coverage行、重复finding、行号不匹配、排除源码来缩分母 | 空finding合法但不推导100%；其他拒绝/Partial；行号与冻结文件核验。真实包含目录时按实际manifest另计条目，不能拿本合成文件数当真实963证据 |
| CONTINUE-01 / O | snapshot/profile一致与不一致的续接描述，遗漏artifact hash、旧test_run引用 | 完整引用可供管理派后续；缺失/漂移拒绝；续接数据本身不授予新真实调用或自动模型重试 |

## 4. profile、执行与权限（C 包）

| ID / Gate | 操作 | 必须观察的结果 |
| --- | --- | --- |
| PLAN-01 / O | 同 role/profile 分别给 agy/Cursor 构造计划 | 业务合同同源；host键/argv区别显式记录；新Coding提示允许执行/测试/内部修复，Review只读source；不残留统一commands禁止或count0断言 |
| PLAN-02 / O | caller 传 arbitrary model/argv/URL、未知recipe、未经授权网络/profile | preflight拒绝；固定 route与已验收 deployment envelope不能被task文本覆盖；没有启动、key初始化或主机修改 |
| SPAWN-01 / O | fake CLI 在一次宿主调用中做多个read/write/测试失败/修复/回归事件 | host spawn=1，工具与测试run>1合法；Bridge不为失败测试重新launch。一次调用可能有多个上游请求，实际provider次数未知时记unknown |
| TEST-01 / O | 故意失败的测试再回归成功、只声称测试成功、伪造/缺JUnit | 失败和通过记录均绑定recipe/toolchain/source/artifact；自述或未核验报告不接受，记录Actual/Reported区别 |
| CONFIG-01 / O | agy自然缺键与已有permissions、用户deny冲突、另一个任务占配置锁 | 旧slice继续旧拒绝；新task严格merge/拒绝冲突；独占协调；不覆盖deny、设置默认false或把恢复开关删掉 |
| CONFIG-02 / O | 正常恢复、仅排版漂移、语义漂移、中断、备份/回执写入失败 | 原字节恢复或显式blocked；完整失败产物；不手动还原后伪造原成功，实机前通过全部existing restore回归 |
| CONFIG-03 / O→R | Cursor project/global合并、native Windows path rule、--force显式deny、profile argv组合 | 离线结构与本机语义分别有证据；不猜键、不把深合并数组当追加、不会将--force当allow-only |
| BOUNDARY-01 / O→R | enforcement证据缺失、只给cwd/只读位/同用户ACL/JobObject/命令前缀 | required-enforced profile不能启动，Blocked/ExecutionBoundaryUnverified；该元数据不标为强隔离 |
| BOUNDARY-02 / R | 在授权测试目录中置无敏感 canary，普通Read/Write与Grep/Glob/list分别尝试任务外读写 | 真正命中拒绝；每类工具独立记结果；拒一个Read不能覆盖搜索工具，不能拿未尝试项算通过 |
| BOUNDARY-03 / R | 允许的python/pwsh/node项目脚本尝试任务外读/写/删除及子进程逃出访问；Review脚本尝试source写入 | 进程层实际访问被拒并留退出/拒绝证据；只靠profile文字或工具Read规则不能通过。只在已授权无敏感fixture根测试，不触碰业务树/凭据 |
| NETWORK-01 / O→R | Worker subprocess/WebFetch/MCP尝试未许可域、IP/重定向/代理；CLI正常供应商连接 | task网络拒绝而通讯不被混为同一权限；测试目标必须事先授权；无法强制时blocked，不加skip/unrestricted |
| DEPS-01 / O→R | offline缓存安装；锁文件hash不符；任务env/缓存与全局安装；锁定registry装包的install脚本 | offline不联网；locked-deps仅预先授权锁/hash/registry/transitive域/script与根；全局变更/锁改动拒绝，失败不换源/解锁自动恢复 |
| TIMEOUT-01 / O | fake CLI持有grandchild/管道、deadline终止、capture不完整 | 仅回收本task树；capture/restore明确；未确认退出不声称取消上游；没有进程名模糊终止 |
| CAPTURE-01 / O | 输入/任务/profile/plan/UID绑定、seal tamper/帧缺失/额度满 | 现有认证与限额回归通过，缺证据不启动/不验收；测试注入key/root，不接触真实Credential Manager/旧UID |

R 需要真实版本/后端、启动Shell与WorkerShell分别记录。当前 Windows native sandbox、agy deny/always-proceed/共享层优先级、Cursor搜索工具范围、Shell继承文件/网络限制均未验收。在线文档和argv可选值是待测支持线索，不是本机Pass。新增容器/VM/受限用户或主机策略需已有明确授权；R失败不自动安装它们作为替代。

## 5. 两宿主真实样例（未来独立授权，不是本轮调用）

每个 host/role/profile 是独立能力项。先完成 O 和对应 R，再由管理按已授权额度派发一次具体调用；不把本页解读为自动取得四次或更多调用。允许模型在那次调用中调试；host失败/限额后保留并回执，禁止第二次真实调用补分。

### V-Coding：完整小工程与同次排障

同一 Git/ZIP导入快照，预置错误 `src/calculation.py` 与失败测试；目标为非负整数 n 的不大于 n 的偶数和，n=10结果30，负输入ValueError，边界0/1/2都有规格。要求新增一个模块和测试文件、删除指定过时副本文件、把指定说明文件重命名并更新引用。冻结源中先有能复现错误的测试；Worker须实际执行一次失败测试、修改代码、执行通过回归/构建或语法检查，并生成 out/result.txt 与测试记录。

- 双方核心任务说明/快照/验收ID/profile相同，仅host配置不同；不供另一方产物。
- 必须观察 read/search、create/edit/delete/rename、测试失败→修复→回归的真实工具/进程证据；不能只生成看似完成的文件。
- Host independently运行同一受控验收、核对全部边界与result原字节、变化清单、protected/source/snapshot、配置恢复、capture与deadline。Worker结果缺失和Host另存结果严格区分。
- 用户下载包含未经修补的Worker代码、原始out产物和独立Host验证，不泛化模型胜负。两边都通过才能标相应Coding profile双宿主已验收。

### V-Review：完整静态审查与覆盖

使用946合成源码+17辅助文件、中文路径和确定的少量P1/P2/无问题样例；一个已授权小样例用于先验证多文件搜索和out创建，然后相同导入快照上的规模样例验证覆盖与续接。小样例/规模样例是真实调用时分别需要授权，不能暗中加第二job。每个reviewer独立目录，不读另一个reviewer结果。

- 输出中文report及findings/coverage/progress。source和snapshot完全不变；out正常创建；protected/跨任务范围结果明确。
- 管理核对已知fixture finding位置、severity、证据与漏报，不要求两模型措辞/工具完全相同；代码presence不能充当分析。
- 若一次预算不足以分析全部源码，须Partial并给完整未完成清单/候选/快照/profile/最后证据引用；接受“如实Partial”的状态合同，不接受“任务能力100%已通过”。后续新调用须另行授权。
- 真实游戏包进入验证必须另有精确输入/授权：这里的946/963只为合成容量目标，本轮不读取游戏ZIP，也不拿合成finding当游戏审查完成。

### V-Deps：已授权依赖与构建（单独能力项）

只在 registry/网络/脚本/缓存/工具链 profile 通过 R 后使用带锁的最小工程，记录锁文件不变、任务环境安装、实际构建/测试、安装脚本与网络范围。不能用 stdlib Coding通过证明依赖准备通过，也不能因联网模型成功证明包管理网络通过。离线依赖profile可先独立验证。

## 6. 发布与文档一致性（D/I 包）

| ID / Gate | 必须核对 |
| --- | --- |
| DOC-01 / D→I | 当前能力与候选功能明确区分；旧slice仍有原限制；新task允许完整任务内调试；CLI/README/usage/Skill/AGENTS不互相矛盾 |
| DOC-02 / D→I | Skill明确读取部署回执的位置/字段/entry验证顺序；agy gemini-3.8-flash-high/high与Cursor grok-4.7-high非Fast均有文字；不把本机路径当通用安装路径 |
| DOC-03 / I | sdist only-include加入新模块/新测试/两份文档及相关Skill引用；wheel/sdist独立环境只做fixture prepare/plan/collect；不误带旧MCP、运行目录、配置或秘密 |
| COMPAT-01 / O→I | 全部旧slice/Cursor/restore/capture/H3离线回归；固定模型与旧退出码语义未静默改变；缺--execute不启动/改设置 |
| REVIEW-03 / I | 每个实现包有独立Review；不能仅实现者切模型自证；P0/P1按管理Repair规则处理，不在Review自行修复 |
| RECEIPT-01 / D→I | 一次终态回执：TASK_ID/status/commit/证据引用/验证/下一步；发送失败最终留ReceiptDeliveryFailed，不轮询补偿 |
| ARCHIVE-01 / D→I | Scratch/Archive INDEX、文件目的/来源/hash、恢复与失败证据、保留原因/可删条件；worktree登记保留或正规Git移除，本阶段不删除/发布 |

## 7. 本阶段可交实施与待裁决清单

可立即派 A/B/C 的离线实现及 D 文档/入口包，冻结第3–6节 schemas 与本矩阵ID；各包以合成fixture工作，不拿宿主真实未验收能力作前提。管理独立核对本候选后可继续分包，不需为常规Phase反复问作者。

必须在具体运行前解决：Windows命令/搜索/网络边界的真实实现与R证据；新调用额度；依赖域/脚本授权；涉及宿主全局设置或安装的部署权限；游戏包精确授权。保留 ProposedRecommended/authorConfirmed=false，不能自行接受同用户shell宽访问或标强隔离。无法实现某profile范围时如实Blocked，同时继续输入/工作区/产物等不依赖它的实现。

本页不会创建自动续接/额度调度、付费重试、常驻进程监控、定时巡检或新的Agent平台。
