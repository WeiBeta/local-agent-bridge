# 统一工程任务验收矩阵 v1

状态：`ProposedRecommended`；以下为实施/验收规格，不是已有功能通过记录。
任务 LAB-TASK-WORKSPACE-CONTRACT-REPAIR-01；2026-10-04；冻结实现 base `7a5d921ed2402023b5b21417b12362ed8da5c1d6`，修订基于 `e64075903e1e2bba11351cb2675703f3ccf35022`。
合同：[TASK_WORKSPACE_CONTRACT.md](TASK_WORKSPACE_CONTRACT.md)。管理任务：019fe10b-df55-7b82-a9ba-3702dc08c55f。

## 1. Gate 与证据口径

| Gate | 可以执行的内容 | 通过后可声明 | 不能据此声明 |
| --- | --- | --- | --- |
| D：本阶段文档修复核验 | 审查报告精确hash、两文档diff、字段/规范JSON/签名/ID/模式静态检查；不重跑全套代码测试或安装 | 修订合同、接口和验收规格可审阅 | 新功能或本机能力已实现/可用；上轮包元数据失败已被本轮重测 |
| O：新实现离线验收 | 合成 Git/ZIP/目录、伪 CLI/进程树、注入 key/root、捕获回放与 profile fixture | 软件合同与拒绝分支通过 | 真实 agy/Cursor、Windows 原生权限、真实 provider 成功 |
| R：宿主能力验收 | 有效实际授权下的本机工具/命令执行、终止、恢复、回收；required_enforced再加所要求隔离 | 该版本/配置/角色/能力/边界的实测效果；declared_scope记录未强制范围 | O直接真实上线；未测范围隔离；供应商模型身份 |
| V：两宿主真实任务 | 明确调用额度，同snapshot、角色/能力/边界分别运行 | 该host与具体能力项通过 | 未测能力/项目或后续CLI版本自动通过 |
| I：集成与发行 | 精确 current main 的新候选分支、冻结 allow-list、全离线回归、独立 Review、文档/Skill/打包核验 | 可集成/可部署候选及已验收能力清单 | 自动修改业务树/main、更新宿主或远端发布授权 |

本阶段只有 D，按管理要求不运行pytest/ruff全套代码检查、不装依赖；上轮测试及失败证据保留，不因文档修复重写。O/R/V/I都是待执行矩阵，不执行上游CLI（含help/version）、模型、游戏包、宿主配置/部署或远端变更。未来O只用伪CLI/注入key，不接触真实凭据/历史UID；没有回执不轮询。

每个测试行必须交：case_id、fixture/input/profile/toolchain SHA、执行者/版本、开始/结束/退出码、expected/actual 判定、证据路径/哈希；失败原样保留。unrun/unverified 不能记 Pass。JUnit 属性为现有测试计数真源；CLI 退出 0、文件存在或 sealed capture 均不等于业务 Completed。门禁与 source/receipt 哈希不符不是瞬态错误，不能自动重试；新真实调用始终受本次明确额度限制。

## 2. 输入、快照与导入（A 包）

所有输入为合成 fixture；不读取业务包。ZIP 标准库探针只验证可复用 API，不代替新 importer 测试。

| ID / Gate | 输入或操作 | 必须观察的结果 |
| --- | --- | --- |
| INPUT-01 / O | Git 同一精确 commit 包含 .cs、.meta、UTF-8/中文、BOM、CRLF、无尾 LF、NUL 二进制 | 原字节、长度和哈希一致；不因后缀/UTF-8 要求拒绝工程普通文件；control TASK 不覆盖业务 TASK.md |
| INPUT-02 / O | 修改 live checkout、挂 export-ignore/export-subst、换 branch 名但仍指定同 SHA | commit bytes 不受 checkout/导出变换影响；选择清单全部绑定；不得以工作树或被过滤的 archive 替代 |
| INPUT-03 / O | 同一文件树分别来自Git/ZIP/目录；ZIP顺序/压缩/时间戳不同，git_mode只来源记录 | snapshot_id按合同§7.1精确规范字节一致；父目录一项、无根项；原包/selection/manifest SHA分别绑定，不混原始字节与JSON摘要 |
| INPUT-04 / O | 目录前后内容变化、清单少/多文件、清单不可信或 SHA 不符 | InputChanged/InputManifestMismatch，启动数 0；不自动补清单/重拷，失败副本保留 |
| ZIP-01 / O | `../`、混合分隔符、绝对/UNC、C:foo/C:/foo、设备路径、ADS、NUL、保留名、尾点/空格 | 写入前拒绝；没有目标根外文件，拒绝不会“清理路径再接受”；检查原始名而非只检查截断后的 filename |
| ZIP-02 / O | 同名重复、A.cs/a.cs、NFC/NFD 冲突、a 文件+a/b、目录/文件同名 | 集合预检拒绝；正常 a/ 目录项+a/b.cs 可接受；不覆盖/去重 |
| ZIP-03 / O | UNIX symlink/mode、设备/FIFO、DOS reparse 属性、目录 junction、目录输入硬链接 | 类型拒绝；不跟随/创建；没有访问目标文件内容；缺 Windows 权限无法创建 fixture 时标 Skip/Unverified，不能算 Pass |
| ZIP-04 / O | stored/deflate 普通与零字节文件；local/central CRC、size、method、flags 组合；stored 压缩/展开等长；合法有/无签名 descriptor 与限额内 ZIP64；deflate 实际长度、真实流结束、尾随字节/第二流；加密、不支持压缩、CRC 错、截断、伪报 size | 合法包原字节保留，不因 descriptor 零占位或 ZIP64 sentinel 误拒；记录不一致 staging 前拒绝，复制中的实际流/CRC 失败保留专用 staging；无有效最终根，不重新下载或运行模型解压。新小型真实格式 fixture 与读取粒度等定向注入分列；自检不关闭独立 A 或其余矩阵 |
| ZIP-05 / O | 越过各资源上限；中文/非BMP路径、255码点分量、完整物理路径240 UTF-16码元边界 | 计数单位准确：原规定是255字符而非字节，物理根/分隔符/非BMP字符按UTF-16计；原Unicode身份/UTF-8输出保留，NFC/casefold冲突拒绝而非改名；超限不换目录 |
| ZIP-06 / O | staging 写入中断、磁盘不足、父路径在检查后变 reparse、已存在目标 | staging 保留且未 sealed；最终清单不可信；不覆盖原目录，竞态防护未闭合时明确阻断 |
| INPUT-07 / O | 真实 ZIP close 完成后注入异常、关闭入口读最终根、关闭耗时/异常与失败标签 I/O 失败 | 来源关闭在最终根可读前完成；关闭失败或返回后到期保留 staging，不产生有效最终根。标签写入失败不影响此拒绝资格；原始来源/失败现场不删除、不覆盖 |
| INPUT-08 / O | 单一绝对预算跨选择/关闭/metadata；真实 1.2s metadata 延迟及正常对照；最终 rename 紧前到期、rename 自身跨时成功、rename 失败 | 预算不重置；发布前超时为 DeadlineExceeded、无有效最终根、staging 及已有 metadata 保留并尽力标签。紧前预算检查通过后的 rename 成功为成功提交，即使跨时返回也正常读回，不再事后改判失败；不宣称严格墙钟抢占。rename 失败保持既有错误 code/cause，不依赖事后标签撤销成功资格 |
| INPUT-09 / O | Git/ZIP/目录合成余量：保留声明总量不足/相等/足够、多文件累计/排除/全排除、块间/文件间余量下降、manifest/SEALED 实际 bytes 不足/相等、查询异常/超时、写入路径 ENOSPC 与标签失败 | staging 前不足无新 staging；原 Git blob size 预取保持 no-replace 与同一 deadline，不预留排除内容字节；每个内容 chunk 写前复查，写后刷新 Python 缓冲，metadata 按实际 bytes 检查；不足 ResourceLimitExceeded，查询/写入 I/O 为非敏感 IoFailed/cause 保留；开始后的失败现场保留、无最终根，不依赖失败标签。成功 rename 后不查询；不真实填盘/改配额，不声称可防并发耗尽或精确分配开销，自检非独立 A 接受 |
| INPUT-05 / O | Git mode120000/160000、LFS pointer、包内 hooks/setup/宿主控制文件 | 链接/submodule 拒绝；LFS不自动联网；不执行 hooks/setup；控制冲突启动前阻断，保留所有选择/排除依据 |
| INPUT-06 / O | 三来源普通 AuthToken.cs、敏感/排除大小写及 NFC 范围、目录前缀与分量边界；精确 control 原名/hash 正负对照 | 不因 token 子字符串漏源码；敏感等价路径拒绝，明确排除保留来源原名/原因及源码分母；最深排除原因稳定，等价重复规则拒绝；control 别名/错hash/被排除拒绝。不读取真实凭据作 fixture，NFC 等价不冒充物理 samefile |
| INPUT-10 / O | 三来源无序 source_paths、原 UTF-8 非ASCII、空/子集/重复/精确原声明、排除声明；reader 正确 seal/selection 的无序列表；ZIP 精确 strip_prefix | 参数无序可导入且不被修改；原名/成员保留，发布按原名 UTF-8 字节排序，摘要绑定规范序列；reader 无序/重复 InvalidManifest 且不改旧字节；source/control/strip_prefix 别名不替代精确引用。旧输入顺序测试须按合同§7.1修正期望，保留失败原证据；自检不关闭独立 A |
| SNAPSHOT-01 / O | sealed 后改一个 byte、manifest/task/profile 哈希漂移；两副本分别编辑 | drift gate 拒绝；Coding 改动不改 snapshot 或另一 reviewer；不使用共享可写树、hardlink 或 junction |

补充最小 API 样例：在 BytesIO 中创建普通 .cs、相同大小写冲突、含 NUL 的 ZipInfo，确认 infolist 保留重复条目、orig_filename 保留 NUL、按 open 流式读取原字节、ntpath.isreserved 检出 Windows 保留名。它只证明 stdlib 原语适用；新输入拒绝逻辑与物理机行为仍需上表 O/R。

## 3. 任务工作区、回收与业务状态（B 包）

| ID / Gate | 操作 | 必须观察的结果 |
| --- | --- | --- |
| TASK-01 / O | 合同§4/7.1键/类型；未知/重复键、bool当int、能力缺键、未知role/边界/deployment、越界/protected | 严格拒绝且spawn0；两个角色、三个bool和边界字段组合不增命名profile；依赖true要求execute=true；protected合法收紧父write；旧slice不扩权 |
| CODING-01 / O | 在授权 work 新增模块/测试/目录、改已有代码、删过时文件、重命名普通文件 | collect 不拒绝新/缺文件；added/modified/deleted before/after hash准确；授权外/protected变动被判失败 |
| CODING-02 / O | 原字节同 hash 的 rename、rename后编辑、多候选重复内容、大小写改名 | 可明确关联的纯rename准确；歧义按delete/add，编辑后不伪称纯rename；Windows冲突处理，不丢产物 |
| OUTPUT-01 / O | 二进制变化、CRLF/LF/BOM/无尾换行、生成目录与新增源码同时存在 | raw bytes 保留；文本diff辅助；生成目录有单独清单/大小，源码不能被宽泛 ignore 掩盖 |
| OUTPUT-02 / O | 输出越额、新 reparse/hardlink、缺 required_output、异常 result root | scope/resource失败；保留候选和失败记录；不自动修正/应用业务树，输出根必须全新专用 |
| REVIEW-01 / O | Review改work、正常写中文out/scratch；可选execute在scratch独立构建副本 | 合同work不可写，collect记录hash变化为Fail；中文UTF-8输出原样回收。declared_scope不据此声称物理拒写；required_enforced另需R拒写证据 |
| REVIEW-02 / O | 同 snapshot 生成两 reviewer 目录并分别修改 out/scratch | snapshot/每份 source hash一致；out完全独立；无共享候选或读另一 reviewer结果路径 |
| RESULT-01 / O | CLI success/sealed，缺代码/报告/测试或PENDING；Worker仍自述Completed | worker_status原样自述，host_observations如实Fail/Unverified，management_decision=null；不自动Pass全部IDs、不替Worker补结果，管理裁决Partial/Blocked |
| RESULT-02 / O | deadline/context不足；部分产物/NotAnalyzed；未观测验收ID | Host保留缺口/候选/测试/续接，未观测ID=Unrun/Unverified；管理判Partial；不自动continue/resume或把全部IDs判通过 |
| RESULT-03 / O | provider拒绝、preflight未授权、恢复失败、capture不足、范围失败 | blocker原因区分，原候选保留；旧退出码语义保持；不把业务失败包装成通讯失败或反之 |
| COVERAGE-01 / O | 946源码+17辅助合成文件；Worker声明Analyzed/Excluded/Failed/NotAnalyzed，Host仅观测Read/Grep | Host分列声明和实际观测、结构/分母；每逻辑路径一行，排除不缩source_paths；Read/Grep不自动变Analyzed。完整声明也不证明质量，管理裁决Completed |
| COVERAGE-02 / O | 空findings、缺/重复coverage、行号失配、假Analyzed、排除源码缩分母 | Host记结构/定位Complete/Incomplete/Invalid并保留声明，不裁定真正理解；管理独立质量验收。按实际目录项计数，963合成文件不冒充真实包分母 |
| CONTINUE-01 / O | snapshot/profile一致与不一致的续接描述，遗漏artifact hash、旧test_run引用 | 完整引用可供管理派后续；缺失/漂移拒绝；续接数据本身不授予新真实调用或自动模型重试 |

## 4. 角色、能力、边界与执行（C 包）

| ID / Gate | 操作 | 必须观察的结果 |
| --- | --- | --- |
| PLAN-01 / O | 同角色/能力/边界分别构造agy/Cursor Plan；两个角色的各合法能力组合 | 固定adapter映射显式，无新增组合profile；execute启用才允许测试/内部修复，Review不写source；字段/签名遵守合同§7，旧命令禁止不套新task |
| PLAN-02 / O | 任意model/argv/供应商URL、未授权能力/查询/依赖、授权hash或R缺失 | preflight=Blocked，launch0/不初始化key/不改配置；已授权查询引用URL不被误当供应商路由；设计获准不冒充实际授权 |
| SPAWN-01 / O | fake CLI 在一次宿主调用中做多个read/write/测试失败/修复/回归事件 | host spawn=1，工具与测试run>1合法；Bridge不为失败测试重新launch。一次调用可能有多个上游请求，实际provider次数未知时记unknown |
| TEST-01 / O | 故意失败的测试再回归成功、只声称测试成功、伪造/缺JUnit | 失败和通过记录均绑定recipe/toolchain/source/artifact；自述或未核验报告不接受，记录Actual/Reported区别 |
| CONFIG-01 / O | agy自然缺键与已有permissions、用户deny冲突、另一个任务占配置锁 | 旧slice继续旧拒绝；新task严格merge/拒绝冲突；独占协调；不覆盖deny、设置默认false或把恢复开关删掉 |
| CONFIG-02 / O | 正常恢复、仅排版漂移、语义漂移、中断、备份/回执写入失败 | 原字节恢复或显式blocked；完整失败产物；不手动还原后伪造原成功，实机前通过全部existing restore回归 |
| CONFIG-03 / O→R | Cursor project/global合并、native Windows path rule、--force显式deny、profile argv组合 | 离线结构与本机语义分别有证据；不猜键、不把深合并数组当追加、不会将--force当allow-only |
| BOUNDARY-01 / O→R | declared_scope与required_enforced、缺本机证据、只提供cwd/ACL/JobObject/首token | required_enforced缺所需enforcement证据=Blocked/ExecutionBoundaryUnverified；declared_scope不以未建沙箱阻断离线实现，但真实运行仍须实际授权和R-RUNTIME-01，不标强隔离 |
| R-RUNTIME-01 / R | declared_scope有效授权下，已有工具链在副本执行正常命令/失败测试/修复回归；终止子树、配置恢复、结果回收 | 启用能力实际可用，各生命周期/回收证据完整；只O不能真实上线。同用户/未强制网络范围如实登记；无权限时不运行，不把VM建设变全产品前置 |
| BOUNDARY-02 / R（required_enforced） | 无敏感canary，Read/Write与Grep/Glob/list分别访问约定禁止根 | 所要求各工具面真正拒绝并留证据；未尝试不Pass。declared_scope仅记录实际可达范围，不要求此行全拒绝 |
| BOUNDARY-03 / R（required_enforced） | 已授权fixture中解释器项目脚本/子进程访问禁止根，Review脚本写source | 要求强制的进程访问真正拒绝；若未强制不能称Pass。declared_scope不伪称拒绝，source变动仍由collect发现；不触碰业务树/凭据 |
| WEB-01 / O→R | web_reference启用/禁用、已授权搜索服务与多来源文档查询、HTTP POST查询、未授权目的地 | 启用能力在对应R真实可执行；查询按语义只读，不只GET/两三个域名、不造组合profile；不继承安装/外部写入权限，不上传源码秘密；未知授权阻断对应操作 |
| NETWORK-01 / O→R | provider通讯与任务查询/子进程网络分开；无强制机制；required_enforced目标IP/代理/重定向 | declared_scope记录实际可达/Unverified，不写禁网；合同禁用不冒充OS拒绝。required_enforced所要求网络约束不通过则Blocked；测试目标预授权，不加skip/unrestricted |
| DEPS-01 / O→R | prepare_dependencies开关、execute依赖、离线缓存/联网锁定包、install脚本/全局变更 | 单独可选能力，锁/registry传递范围/script/env/cache有授权；不全局安装/改锁/换源；declared_scope与required_enforced按实际边界如实记录，不为组合新增profile |
| TIMEOUT-01 / O | fake CLI持有grandchild/管道、deadline终止、capture不完整 | 仅回收本task树；capture/restore明确；未确认退出不声称取消上游；没有进程名模糊终止 |
| CAPTURE-01 / O | 输入/任务/profile/plan/UID绑定、seal tamper/帧缺失/额度满 | 现有认证与限额回归通过，缺证据不启动/不验收；测试注入key/root，不接触真实Credential Manager/旧UID |

R分别记录版本/后端、启动Shell和WorkerShell、启用能力、边界模式、实际可达范围。declared_scope必须验证本机执行/终止/恢复/回收，网络查询与依赖按启用项验证；required_enforced另测所要求工具/进程/网络隔离。当前这些新task能力均未验收，在线线索不算本机Pass。新增VM/容器/受限用户须实际授权，不把它们作为普通可信模式前置。

## 5. 两宿主真实样例（未来独立授权，不是本轮调用）

每个host/角色/能力/边界需对应证据；不为每组合新造profile或强制跑全组合。先O和对应R，再按有效实际授权/调用额度派一次具体任务，不由本文自动取得更多调用。允许同次调试；失败/限额保留回执，不第二次调用补分。

### V-Coding：完整小工程与同次排障

同一 Git/ZIP导入快照，预置错误 `src/calculation.py` 与失败测试；目标为非负整数 n 的不大于 n 的偶数和，n=10结果30，负输入ValueError，边界0/1/2都有规格。要求新增一个模块和测试文件、删除指定过时副本文件、把指定说明文件重命名并更新引用。冻结源中先有能复现错误的测试；Worker须实际执行一次失败测试、修改代码、执行通过回归/构建或语法检查，并生成 out/result.txt 与测试记录。

- 双方任务说明/快照/验收ID/角色/能力/边界相同，仅host配置不同；不供另一方产物。
- 必须观察 read/search、create/edit/delete/rename、测试失败→修复→回归的真实工具/进程证据；不能只生成看似完成的文件。
- Host independently运行同一受控验收、核对全部边界与result原字节、变化清单、protected/source/snapshot、配置恢复、capture与deadline。Worker结果缺失和Host另存结果严格区分。
- 交付包含未修补Worker代码/原始out/Host验证；管理裁决相应能力是否通过，不泛化模型胜负或所有能力。

### V-Review：完整静态审查与覆盖

使用946合成源码+17辅助文件、中文路径和确定的少量P1/P2/无问题样例；一个已授权小样例用于先验证多文件搜索和out创建，然后相同导入快照上的规模样例验证覆盖与续接。小样例/规模样例是真实调用时分别需要授权，不能暗中加第二job。每个reviewer独立目录，不读另一个reviewer结果。

- 输出中文report及findings/coverage/progress。source和snapshot完全不变；out正常创建；protected/跨任务范围结果明确。
- collect只核对结构、分母和位置；管理对比已知fixture的finding、severity、证据与漏报来验收质量，Host Read/Grep不替代Worker分析，不要求两模型措辞相同。
- 若一次预算不足以分析全部源码，须Partial并给完整未完成清单/候选/快照/profile/最后证据引用；接受“如实Partial”的状态合同，不接受“任务能力100%已通过”。后续新调用须另行授权。
- 真实游戏包进入验证必须另有精确输入/授权：这里的946/963只为合成容量目标，本轮不读取游戏ZIP，也不拿合成finding当游戏审查完成。

### V-Deps：已授权依赖与构建（单独能力项）

prepare_dependencies=true且实际锁/registry传递范围/脚本/cache/env授权与对应R通过后，使用带锁小工程，记录真实安装、构建/测试与边界模式。stdlib Coding不证明安装能力，模型连接不证明包网络授权；可先离线缓存准备，不新增依赖组合profile。

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

先管理冻结合同§7准确字段/规范序列化/导出签名和本矩阵ID；A交snapshot fixture，B/C可依同schema并行，D后接共享CLI/打包/文档，再独立Review/离线集成。两个角色+三个能力bool+两个边界枚举已经设计裁决，不再边实现边增加profile；不拿未验收本机能力作离线前提。

真实运行前集中说明/取得：同用户shell实际可触达范围与未强制网络、已有工具执行/终止/恢复/回收R、所选查询/依赖/脚本范围、必要部署/配置权限、调用额度和真实包授权。declared_scope设计获准不等于这些实际权限获准；required_enforced未验收不声称可用。缺项仅阻断相应实际运行，继续安全离线实现，不能把VM建设变整个产品前置。

本页不会创建自动续接/额度调度、付费重试、常驻进程监控、定时巡检或新的Agent平台。

## 8. C 回执接口增补（管理工程冻结，2026-10-06）

采用合同§7.3；不新增实际权限/R。O只用显式可信测试注入与fake，不启动真实宿主/配置/密钥。

| ID / Gate | 操作 | 必须观察的结果 |
| --- | --- | --- |
| TRUSTED-INPUT-01 / O | 外部固定receipt/profile/auth和派工expected SHA；task选根、自证hash、未知/重复键/非规范JSON、根重叠/reparse/硬链接 | 固定加载/严格schema/可信供给边界；无密钥配置启动，固定非敏感错误 |
| RECEIPT-BINDING-01 / O | profile去receipt_sha、R绑定排除两字段、完整receipt/bundle摘要；plan→run漂移 | 无自引用；副本排他/同字节复验；再读管理输入并再生Plan，漂移launch0、不覆盖 |
| DRY-RUN-01 / O | capabilities.execute=true/prepare_dependencies=true，run execute=False；Accepted/缺R | 合法NotRun/launch_count0，不读key/真实配置；能力依赖与Host启动开关分开 |
| R-GATE-01 / O | 缺新task R、旧slice、WorkerReported/hash-null、组合别行、缺强制项 | Blocked；不降级/旁路/bootstrap；fake Accepted不证明真实R |
| IDENTITY-01 / O | 实际使用task_run/launcher/capture/restore产品、Bridge entry/后端标记/toolchain身份和遗漏/漂移 | 精确文件/运行实现绑定，不以版本字符串证明；不能验证Blocked，不另启动CLI |
| CONTROL-01 / O | C首次receipt/plan；B尚无二者；Cursor固定配置缺失/漂移/冲突 | C创建副本，B不提前要求；D/Host准备、C核对、B保护，不覆盖现场 |
| PREPARED-TREE-01 / O | B固定control/snapshot与SEALED；plan后work/快照/control漂移，capture准备期间漂移 | 先核验外部可信输入，再用B公共verify_input_controls及A完整树校验复核，配置写入前再次检查，launch0；不使用B私有导出 |
| RUN-EVIDENCE-01 / O | Plan外部来源、run元数据、session UID与两个fake测试事件 | 运行文件SHA可按run_root核对；session:UID为opaque认证清单引用；原始声明不提升为HostObserved测试或业务接受 |
| CONFIG-LIFECYCLE-01 / O | 配置独占、key/backup/capture/patch/metadata失败、Cursor启动后漂移 | 计数按底层执行事实；先备份后key/写入；finally恢复或如实Failed，不覆盖语义漂移，无自动重试 |
| LAUNCH-FACT-01 / O | 恢复前身份失败；原生调用无效果/有效果但返回未观测；返回转换/记录前后中断；线程关闭/交接/捕获失败；第二线程失败 | 0/1/null事实贯通；confirmed不降级；unknown必Failed+LaunchUnverified，不允许再试；NotRun0/Completed1；无包装器仍持久化launch事实 |
| LAUNCH-CLEANUP-01 / O | 原始KeyboardInterrupt与线程/回收/管道/Job清理的次生故障；held-handle未知存活状态 | 原始中断保留，各清理独立尝试；未观测结果null；不以回收推断未执行，不输出参数/配置正文 |
| CURSOR-FINALIZE-01 / O | 正常/异常/KeyboardInterrupt；project/global漂移、只读核验故障及核验中断 | 所有启动路径只读核验；Failed及RestoreFailed如实记录；原中断保留、配置不覆盖 |
| EVIDENCE-ORDER-01 / O | 各输入引用、caller Plan乱序/重复；跨清单精确ref相同或hash/origin冲突；不同Unicode/大小写ref | 输入有序唯一；完全相同声明可合并，不同声明拒绝；输出按精确ref UTF-8排序，不折叠丢失 |

原CONFIG/restore/capture/timeout和R02/R03回归保持。D尚未更新pytest testpaths/发行清单，新B/C和贯通测试显式加入验收命令。下节补B消费null与真实B产物贯通候选；D/旧receipt兼容仍待独立处理。本矩阵不表示独立Review通过。首次新task R入口留后续单独授权，production Ready仍须对应有效R。

## 9. B/C 接口贯通候选（LAB-TASK-BC-INTEGRATION-01）

采用合同§7.4的冻结控制绑定与公共Host导出。仅实际A导入→B prepare的合成数据、fake Host/R/key；不手工伪造B形状替代这组贯通测试，不运行真实CLI/provider/config/R。新候选仍须独立Review。

| ID / Gate | 操作 | 必须观察的结果 |
| --- | --- | --- |
| BC-CONTROL-01 / O | Coding/Review、两Host、空/原生嵌套规则，B实际prepare→C plan/run→B collect | 投影/完整task摘要贯通；原名与CRLF/BOM/非ASCII/无尾换行原字节保留；protected生效；源码文字不创建信任 |
| BC-CONTROL-02 / O | 缺/多/空绑定、投影/hash/名称/protected漂移，plan/run/capture阶段规则漂移 | 公共导出准确调用；外部bundle先验；InputControlConflict在配置/启动前停止，底层错误保留；collect保留当前与原快照字节，scopeFail/continuation=null |
| BC-LAUNCH-01 / O | 正常、NotRun、未执行/confirmed/unknown异常与原始中断 | 0/1/null和清理观察原样回收；unknown必Failed+LaunchUnverified，无二次launch/续接；原中断传播，NotRun0/Completed1 |
| BC-LAUNCH-02 / O | null与NotRun/Completed/TimedOut/缺LaunchUnverified、Blocked+null、bool/越界 | RunReceiptInvalid/Failed/continuation=null，不将null当0或成功 |
| BC-FINALIZE-01 / O | agy语义漂移、Cursor project漂移及异常收尾 | 启动事实1保持、RestoreFailed/transportFailed，备份与当前配置保留；Cursor control漂移另记Fail |
| BC-EVIDENCE-01 / O | C真实fake encrypted session refs、自报/opaque/hash-null测试、测试报告digest漂移 | UID为opaque Unverified，原声明/观测保留，不自动Pass；失配产物单独保留，未核验测试不能作last_test_run |
| BC-COMPAT-01 / O | 全旧离线回归与旧异常回执合同审查 | 旧成功/未启动/fixed argv/退出码回归保持；legacy nullable方案尚未冻结，旧adapter修正依赖暂停，不冒充三项全部完成 |

显式验收命令包含原pytest testpaths的12模块（含test_bridge_winjob.py生命周期回归），再加test_task_run.py、test_task_workspace.py及test_task_bc_integration.py；每轮全新Scratch basetemp/log/XML。完整结果须列出D的两个已知发行失败和平台skip，不能用忽略这些模块的绿色局部回归替代。ruff check和format check只验证代码规范，不替代独立Review、D或真实R。
