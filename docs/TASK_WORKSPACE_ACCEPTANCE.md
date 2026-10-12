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
| DOC-03 / I | sdist only-include加入新模块/新测试/两份文档及相关Skill引用；wheel/sdist独立环境只做fixture prepare/plan/collect；不误带旧MCP、运行目录、配置或秘密。已审 LAB-TASK-D-PACKAGING-01 的精确集合断言含 task_run.py/task_workspace.py（含反例证明非包含式）；LAB-TASK-DELIVERY-INTEGRATION-01 选择性集成后，sdist 清单含三份 TASK 文档与全部17测试模块（含 legacy），wheel 仅 runtime 包与许可实体；新树构建/安装须重新验证，不复用 D wheel |
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

原CONFIG/restore/capture/timeout和R02/R03回归保持。选择性集成已审 D 的 pytest testpaths/发行清单后，默认 `uv run pytest` 按目录级 `tests/` 发现全部17模块（含新 B/C、贯通与 legacy 测试），sdist 清单携带三份 TASK 文档与全部测试模块。下节补B消费null与真实B产物贯通候选；旧receipt独立候选边界见第10节。本矩阵不表示新集成候选独立Review通过。首次新task R入口留后续单独授权，production Ready仍须对应有效R。

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
| BC-COMPAT-01 / O | 全旧离线回归与旧异常回执合同审查 | 旧成功/未启动/fixed argv/退出码回归保持；后续LEGACY包工程冻结新执行schema v2，单独候选与Review，不把B/C结论冒充旧adapter接受 |

验收命令为默认 `uv run pytest`（目录级 `tests/` 发现，当前17模块），并以显式 `pytest tests` 复核完整有序 nodeids 相同且无重复；新增同约定模块自动发现，发行清单与精确集合断言仍须同步。每轮全新Scratch basetemp/log/XML。完整结果须列出实际平台skip，不能用绿色局部回归替代；D两项已知发行清单失败须在本集成树重新验证。ruff check和format check只验证代码规范，不替代新集成候选独立发行复核或真实R。

## 10. 旧adapter执行回执v2候选（LAB-LEGACY-LAUNCH-RECEIPT-02）

仅新生成execute stdout/run.json为schema_version=2；preflight/plan v1、Task contract v1、加密session v2互不迁移。历史v1不改，不虚构unknown。只用offline fake，独立Review仍必需。

| Gate | 操作 | 必须观察 |
| --- | --- | --- |
| LEGACY-VERSION-01 | 两adapter正常/拒绝/异常，旧v1原字节及旧根复用 | execute2，preflight/plan1；历史字节不变、旧根拒绝；不新增CLI参数 |
| LEGACY-FACT-01 | fake原生恢复前、unknown、confirmed后异常与返回capture | caller-owned事实0/1/null；返回存在不自证1；原spawn_state词表；异常fallback保留原生命周期字段/观察，正常capture形状不变 |
| LEGACY-INTERRUPT-01 | 原生/capture/封口中断及次生恢复、各回执写入/stdout错误 | 原始中断优先，独立尽力收尾、非成功、不重试；原stage/PID/cleanup/null保留，不降级确认计数 |
| LEGACY-CONSUMER-01 | 严格task collect尝试读取旧schema v1/v2/未知3 | RunReceiptInvalid/Failed、continuation=null，不跨合同误读；外部消费者未核验，不声明通用向后兼容 |

默认与显式测试集合均含test_legacy_launch_receipts.py（共17模块），sdist与精确发行测试清单同样登记；完整结果保留实际失败与平台skip。新旧候选边界、独立审查和真实部署不能用这些离线总数合并宣布接受。

## 11. Task CLI v1 离线验收矩阵

对应 LAB-TASK-CLI-IMPLEMENT-01，测试新增 test_task_cli.py；当前默认和显式发行测试清单均为 18 模块，runtime 精确清单包含 task_cli.py。历史章节的模块数量仅描述当时候选，不累计为本轮结果。

| 组 | 必须验证 |
| --- | --- |
| CLI-01 | task 与五条 help 无输入访问；必填/重复/缩写/多余参数拒绝，错误无原始文本 |
| CLI-02 | 严格 spec JSON、原路径拼写、64 MiB 读取前/后边界、身份变化、单链接；真实 Windows 第二次 fstat 后及最终路径观察后的等长改写+恢复 mtime 必须 InputChanged，句柄持续有效 |
| CLI-03 | 实际 Git/ZIP/目录经 CLI→A；源类型精确字段、摘要、strip_prefix 与 policy 必填 |
| CLI-04 | 新 task_root 共享加载；管理固定摘要、canonical、receipt/profile/auth 绑定和根不交 |
| CLI-05 | CLI→B prepare；task/note/规则原字节与 input_control_bindings；错误不发布任务 |
| CLI-06 | Cursor 固定模板和只读复验；字节/schema/目录冲突及部分持久化失败原位保留；不完整计划收集必须 ControlChanged/Fail、continuation=null |
| CLI-07 | 无适用 R 为 Blocked；Caps.execute 与 --execute 分离；静态 Review 不误禁宿主 |
| CLI-08 | 实际 A→B→fake C→B；默认 dry run 不读 key/不启动，允许启动只一次 |
| CLI-09 | trust/task note/source/rule/plan/runtime 身份漂移；run 不准备或修复 Cursor 配置 |
| CLI-10 | Failed/TimedOut/null/capture/restore 与原中断清理；退出 2/130、不产生成功 |
| CLI-11 | collect null run、缺输出、越界改动、Worker Blocked；原结果、管理裁决 null、传输 LF |
| CLI-12 | 实际 CLI 身份缺项 Blocked；18 模块有序发现相等且无重复；完整 pytest/ruff/format；新 sdist→wheel 与隔离锁定离线非 editable 安装 |

本轮报告须给出实际 JUnit、失败轮日志、平台 skip、发行清单/RECORD/metadata/源文件字节核对和安装来源。只检查本产品静态帮助，不启动真实宿主帮助或版本命令。
首次真实 Task R/bootstrap 未定义；目录 manifest 的无界读取与 entries 预门禁缺失已由 LAB-DIR-MANIFEST-RESOURCE-01 候选按 package_bytes_limit 有界读取与 entry_count_limit 预门禁关闭，仍待独立 Review。不以合成测试或安装自检替代独立 Review、真实运行与部署。

## 12. CLI 首轮修复验证（LAB-TASK-CLI-REPAIR-01）

原独立 Review 的 LAB-CLI-R01/R02 是两个 P2，拒绝 ff3b5ed；完整回归绿色不替代该裁决。修复自检必须保留原失败及相同反例，随后由未参与修复的独立 Review 复核。

| 组 | 必须观察 |
| --- | --- |
| R01-01 | 原审查实际 Windows 读后改写用例在修复前失败、修复后拒绝；普通已重写文件仍可读 |
| R01-02 | 第2次fstat后、最终路径stat后等长改写并恢复mtime，最终同来源句柄观察拒绝；整个路径观察期句柄有效，无循环重读/无限stat |
| R01-03 | 实际ZIP import spec目标等长变化：InputChanged/空stdout，旧/新目标都不发布 |
| R02-01 | agy/Cursor receipt/plan各写入阶段的普通异常/原中断；receipt-only/截断材料一律ControlChanged/Fail、continuation=null，原字节保留 |
| R02-02 | Cursor mkdir/file写入前、部分、完成后失败；只有完全没有发布控制材料才等同纯prepare；存在材料而计划不完整必拒绝 |
| R02-03 | B直接检查prepare-only、receipt-only、plan-only、Cursor-only、full-plan，null JSON receipt文件不能当文件不存在；null-run结果schema不变、management_decision=null |
| FULL | 全18模块当前树pytest/JUnit、ruff/format；本修复轮不复建整套发行安装，后续独立Review按风险复验 |

完整计划即使CLI在最后写入后传播异常，B也按真实完整控制材料观察，不伪称缺失或业务接受。最终句柄查询之后的外部变化和原路径链点时限制如实保留；本轮没有长期文件锁或永久TOCTOU消除声明。首次真实R仍未闭合；目录manifest资源残余由 LAB-DIR-MANIFEST-RESOURCE-01 候选关闭，待独立 Review。

## 13. 目录 manifest 资源界（LAB-DIR-MANIFEST-RESOURCE-01）

仅关闭单列残余，不重开其他架构：manifest 读取复用 policy.package_bytes_limit（不新增第十个 policy 键），声明 entries 在逐条解析前过 entry_count_limit。只离线合成反例，不真实巨量内存/磁盘。

| Gate | 反例 | 必须观察 |
| --- | --- | --- |
| DIR-BYTES-01 | manifest 字节等于/超过调低后的 package_bytes_limit；超限叠加错误声明摘要 | 等于上限正常导入；超限在哈希比较与 JSON 解码前 ResourceLimitExceeded；限内错误摘要仍 InputManifestMismatch；失败不发布最终根 |
| DIR-GROW-01 | stat 合法但读取期间返回 limit+1 字节（仅 patch manifest 的 Path.open） | 同一 ResourceLimitExceeded；不发布最终根 |
| DIR-COUNT-01 | entries 等于/超过调低后的 entry_count_limit；超限清单尾部叠加畸形条目 | 等于上限正常；超限在逐条字段解析前以条目数错误拒绝；不发布最终根 |
| DIR-REG-01 | 既有 canonical 目录导入、树漂移与既有 deadline 共享用例（manifest-read 注入点随有界读取更新） | 限内行为与错误契约不变；deadline 仍在读取后即时检查 |

完整 18 模块 pytest/JUnit、ruff/format 照常；本轮不复建发行安装。资源保证为有界读取与有界条目迭代，不宣称 JSON 解析绝对内存上限；本候选仍需未参与修复的独立 Review，首次真实 Task R 保持未验。

## 首次 Task R 验证程序离线矩阵（LAB-FIRST-TASK-R-IMPLEMENT-01）

验收单闭合字段见合同“首次 Task R 独立验证程序 v1”。本包只实现和 fake 自检，不修改 src/普通run/R门禁，不执行真实host（含help/version）、provider、key/解密、配置、R-a实机探针、部署或Skill。真实方案仍 ProposedRecommended/authorConfirmed=false；ObservationRecorded不是R Pass。全套沿用原有受控fixture单元测试，不将其中Windows fixture进程检查登记为真实Task R。

| 组 | 必须验证的离线分支 |
| --- | --- |
| RPERMIT-01 | 缺失/漂移/重复键/未知键、Proposed/未确认/权限缺项/无有效预算、bool冒充次数/deadline、host/role/Caps/boundary扩大、自身hash漂移、已消费许可，均不得进入生命周期 |
| RINPUT-01 | 外部bundle与完整task/Plan/receipt绑定、唯一缺R、其他授权blocker、根重叠/旧输出、profile环境证据/预期shell、protected recipe及唯一Python工具链；Blocked分支显式核全部实际实现身份 |
| RLIFE-01 | 只调用真实C生命周期一次，在测试边界注入fake0/1/null；配置错误消费后launch0留失败；capture/restore失败不接受；启动前permit/控制/身份复验拒绝漂移，无重试 |
| RKEEP-01 | 原中断在收集/观测写入失败时仍传播，run/标记/partial/失败现场保留，原环境恢复；缺生命周期回执记unknown/null，不推定0 |
| RPROD-01 | 正常run即使--execute且Caps.execute=true，缺R仍NotRun/launch0；初验Blocked Plan/R blocker及授权原字节不改，产物明确TaskRuntimeValidation、R Unverified、management_decision=null |
| RCOLLECT-01 | B仍拒绝Blocked Plan/launch1普通回执；验证只用既有null-run回收候选，B保持NotRun/Unrun/null decision，生命周期另存/hash绑定；范围或必需输出不完整则验证Failed |
| RDIST-01 | 新测试模块纳入默认/显式/JUnit完整有序发现与sdist；验证程序仅进sdist，不进wheel、不新增console/MCP/依赖；实际新sdist→wheel核对全部包内payload |

自检不替代独立 Review。首次R-a/R-b、真实安装/权限/费用/模型可用性、原生命令取证、默认生产capture根和current-main选择性整合全部待各自冻结和验收；不能从本表或fake Approved验收单继承实际许可。

### 第一轮落盘证据 Repair 矩阵（LAB-FIRST-TASK-R-REPAIR-01）

先固定短决策及成组矩阵，再实现；原独立缺失反例修前复现，修后仍用其只读helper副本、既有审查测试安装与合成边界复核。本轮不安装runtime、不复建完整发行包；自检不得宣称独立接受。

| 组 | 离线缺失/变更/错绑定与正常对照 |
| --- | --- |
| RSAVED-01 | C返回dict/None均重读固定run；缺失、非规范raw、返回差异、task/plan错绑定失败；合法None返回但存在文件正常；SHA来自文件，0/1/null事实不重置 |
| RLOCAL-01 | launch/restore文件及必需引用缺失、hash不符、事实错绑定、恢复后实际设置漂移失败；重复引用逐项验，任一重复hash错失败；未知ref不得被读取；opaque只标声明范围 |
| RRESULT-01 | result缺失/非规范/返回差异/task错绑定，artifact清单或文件漂移、缺失/额外文件、重新自洽但错误的host控制均失败；核实际文件、树和来源Task |
| RFINAL-01 | 回收后源树、环境和run漂移拒绝；合法Worker业务源码修改与实际回收对照通过；同任务控制和外部许可仍冻结 |
| RINT-01 | 原中断叠加run/local证据缺失或collect失败仍传播原对象；固定launch可保留已发生计数，缺回执不生成run SHA；场景和许可不清理、不重试 |

完整pytest、Ruff、format按常规运行。其结果只属于Repair自检；新的独立Review补齐此前因P1停止的矩阵与发行审计，真实Task R仍未验。

## 启动事实来源交叉矩阵（LAB-FIRST-TASK-R-REPAIR-02）

本轮关闭Review-02新增的启动计数P1候选，不重置缺陷链两轮上限。计数来源规则见合同“启动事实来源修复候选”。

| 组 | 必须观察 |
| --- | --- |
| RFACT-01 | 原Review-02真实A/B/C离线反例：正常中断及错task/plan零回执均保留实际launch=1；原KeyboardInterrupt对象相同，错回执hash=null |
| RFACT-02 | 原Review-01缺run正常/缺失对照继续通过；可信返回1不因缺文件变0/null |
| RFACT-03 | 错task/plan、错误状态、NotRun/Completed/TimedOut不一致、bool/越界计数及未知缺blocker不能贡献0/1；固定launch自洽0/1/null才提供对应事实 |
| RFACT-04 | 缺run及缺launch/无效launch、未知run，无法确认则null，不能以异常或文件缺失推定0 |
| RFACT-05 | 可信C明确0/1与不可信saved相反，保留可信返回；无明确返回时有效run本体与固定launch中任一明确1保留1，完整证据冲突仍拒绝 |
| RFACT-06 | 已绑定run本体明确1，launch相反零/缺失/不自洽/unknown或引用畸形仍保留1；实际A/B/C附属零漂移反例修前失败/修后通过，原中断不被替换 |
| FULL | fresh basetemp完整pytest/JUnit、Ruff及格式检查；失败和成功材料分别保留，不重复发行重建，fresh Review补停止矩阵 |

只离线fake与合成安装核验，不执行真实host/provider/凭据解密/配置、新R-a/H3或部署；自检不是独立接受，真实Task R仍Unverified。

### 完整目录关联矩阵（LAB-FIRST-TASK-R-REPAIR-03）

本次为作者额外明确批准的窄修复，不恢复或重置自动修复轮次。新独立Review-04由管理核收后安排；再次阻断不自动追加修复。

| 组 | 必须观察 |
| --- | --- |
| RDIR-01 | 原Review03真实A/B/C：收集前合法out空目录对照通过，实际B返回后增加同目录拒绝；真实安装gate不替换 |
| RDIR-02 | authored/generated/out/scratch四复制域各核合法收集前创建、当前源新增/缺失/改名、保存副本新增/缺失/错映射；不机械禁止空目录 |
| RDIR-03 | result、candidate/out/scratch、generated/work及其必要父目录、host/control、validation、无声明run目录的多余/缺失按完整目录集合拒绝 |
| RDIR-04 | 通用build仍authored，新空缓存正确generated，合法层级与B生成祖先正确保留；原中断及已启动事实不被目录失败抹去 |
| RDIR-KEEP | 三类旧缺run/错绑定零/有效本体1附属零反例保持通过；B.NotRun不是整项未启动，opaque仍不证明密文 |
| FULL | fresh basetemp全pytest/JUnit、Ruff/format；默认与显式全部模块有序发现和JUnit逐项同序核对；原失败及各阶段材料保留 |

只五文件离线候选；生产B/C/R、依赖及治理/台账不变。自检与独立审查、真实R、管理接受和部署仍分别记录。

### 首次观测 v2 矩阵（LAB-FIRST-R-OBSERVATION-CONTRACT-01）

v2 精确 schema 见合同“首次观测合同 v2”；以下离线合成自检不构成真实权限或 R。

| 组 | 必须观察 |
| --- | --- |
| OBS-V1 | v1 原非空实现清单、Known 预期 Shell 和观察输出兼容；v1 空清单/Unknown/新增键继续拒绝 |
| OBS-V2 | 仅 agy、组成 Unknown/FirstObservation、空实现和空接受清单；环境 Known/Unknown；bool/未知版本/混版本、额外键、错误 scope/状态、null/伪身份及重复 exe 清单拒绝 |
| OBS-NORMAL | 实际共享加载器及 CLI prepare/plan 可登记 v2；普通 Plan 固定双 blocker，execute/非execute 均 NotRun0；伪 Ready、Accepted 不能执行，不读 key/配置 |
| OBS-IDENTITY | 已知入口/Bridge/toolchain 不因组成 Unknown 跳过；Known 预期 Shell 的缺失、漂移、硬链接及 capture 开始后的 environment/receipt/Shell 漂移均拒绝 |
| OBS-ACCEPT | v2 ObservationRecorded 保留组成 Unknown、实际 Shell Unknown、命令 Unverified 和接受前必需证据；R Unverified/decision=null；B 仍拒绝 Blocked Plan 下的普通 launch1 回执 |
| OBS-COUNTS | 原缺run、错绑定零、有效本体1附属零及所有0/1/null来源反例同时运行v1/v2；许可只消费一次，原中断对象/恢复/原字节和失败证据保留 |
| OBS-TREE | 原完整文件/目录映射反例同时运行v1/v2，合法空目录/生成祖先保留，收集后新增/缺失/错映射仍拒绝 |
| OBS-FULL | 针对及全套pytest/JUnit、Ruff/format；默认/显式有序nodeids无重复且与JUnit逐项相等；新源码/发行包身份核验，不借旧wheel |

实际 Shell/命令 argv/cwd/完成/退出的独立证据仍是接受前条件；v2 不捕获或认证它们，也不选择实际 Shell。本候选不改变普通生产接受标准、文件单链接规则、OS权限、C生命周期或B收集语义。独立Review、真实R和部署仍各自未由自检取得。


## 7. trusted_coding_v1 分层矩阵（作者选择 B，离线候选）

对应合同 §15；不改原 v1 严格 R 与 v2 首次观察接受表。deployment receipt v3 / Plan v2 必须显式出现方式，旧字段和来源不能混用。接受只绑定精确 task scope，普通代码交付与管理独立复测不意味着 Worker execute、完整多文件 CRUD/rename 或真实超时已验收。

| 组 | 离线合成场景 | 门禁 |
| --- | --- | --- |
| LA-LEGACY | 旧 v1 严格 R、v2 Unknown/空 R、v2 插 Accepted | 原语义、原两个 blocker；不静默升级 |
| LA-VERSION | v3/Plan v2 错版本、bool、未知字段、错方式/host/组成、重复 exe | 闭合拒绝，v3 的 runtime_acceptances 必空 |
| LA-MATCH | 精确角色/全部能力/边界/receipt binding/task projection；新 ID、snapshot/说明、CRUD/rename、路径变化 | 仅精确范围可以 Ready；更广样本或变更范围 Blocked |
| LA-AUTH | 执行授权撤销、profile/auth hash、受保护/控制路径、入口 drift | 原授权与路径/身份拒绝仍生效 |
| LA-LAYERS | 交付范围、独立复测、WorkerReported/CliDeclared/Unknown/完整 HostObserved、外层事实 | 分层记录；评价只有 Eligible，业务接受由管理明确冻结 |
| LA-NEGATIVE | 单独伪 XML、只有自述、源码树/recipe/toolchain/argv/cwd/actor/时间/exit 不匹配、证据 SHA 错 | 相应层不能通过，声明不升为 HostObserved |
| LA-LIFECYCLE | Failed/TimedOut、Unknown launch/cleanup、capture/restore 失败、错 Plan/UID | 必需外层门禁，代码通过不能覆盖；Unknown 保留 |
| LA-COLLECT | 新旧 Plan 加载、dry/fake lifecycle 与实际 B prepare/collect | 保持 v1 collector 的 management_decision=null 和 Unrun/Unverified |
| LA-PACKAGE | 锁定离线依赖、适用 pytest/ruff/format/diff、sdist→wheel、独立 noneditable copy | 仅自检；不作为独立 Review 或真实 runtime 接受 |

本实现的 fixture 接受记录全部是合成注入，不落生产回执。下一门禁为新独立 Review；实际 native/模型/真实超时、完整 CRUD/rename、生产配置和部署均另授权并单独报告 NotRun。本轮不触现有 first_task_r/reanalysis helper 或旧捕获机会。

## agy 原生项目模式离线矩阵（LAB-AGY-NATIVE-PROJECT-IMPL-01）

| 组 | 必须核对 |
| --- | --- |
| NP-BIND | receipt 的 id/root/record 闭合；任务根=资源根=cwd；多/空/远端/额外资源、记录 ID 错配、路径逃逸、记录缺失/漂移先于 key/launch 拒绝 |
| NP-REQUEST | 绝对读写/保护/输出/progress 路径及冻结 toolchain；同固定 model/argv tail/外层 deadline，只增加项目 ID，无 skip-permissions |
| NP-NOSETTINGS | 明确禁止全局 settings 读取、权限合并、租约、patch/restore 的 fake run 仍完成；两不同项目 fake 启动可重叠，不宣称真实并发或权限隔离 |
| NP-LIFECYCLE | 单次启动、采集、清理、0/1/null 和主中断语义复用；启动后只核目标 ID/资源根，元数据/global raw SHA 漂移不单凭此失败，不恢复或覆盖原材料 |
| NP-ACCEPT | native 字段改变完整 R/layered binding；旧接受无效，v2/v3 未接受仍 Blocked/NotRun0；新合成 v3 接受只用于自检 |
| NP-BC | 实际 B prepare + C fake run + B collect 的 Coding/Review 材料/项目检查原字节留存，management_decision=null；现有根 fresh/额外文件门禁不放宽 |
| NP-LEGACY | 原 agy settings 租约/恢复、Cursor、Task CLI、首观/分层和 launch 生命周期适用回归 |

以上为实现自检范围，不是独立 Review、真实 agy/model/key/捕获解密、权限反向 deny、A/B 业务验收或生产刷新。现有 A/B 根复用合同尚未实施；首次真实执行材料也须按新无 settings 绑定核适用性，不能直接套旧 first_task_r 许可或旧双调用预算。

## 四工位薄调度候选验收

| ID | 必需离线断言 |
| --- | --- |
| ST-REGISTRY | 配置驱动 1..4 位，四位目标用四条；重复物理根/native、容量超限、根重叠拒绝；无 A/B 或角色专属工位 |
| ST-PATH | requests 父链与 trusted 目标的真 junction 仅在本任务合成 Scratch 中构造；首次 mkdir/import 前拒绝，外部合成目录不产生写入 |
| ST-OWNER | 真 Windows 合成 OS 子进程争同一根仅一 owner；四根可同时由四 PID 持有；v4 低层 run 无当前 lease 在根/密钥/启动前拒绝 |
| ST-ADMISSION | 第五单满位等待，无第五 job/root/launch；取消/等待上限保留零启动；第一单释放唤醒第五并使用 fresh UUID，不扰其他三单 |
| ST-FAILURE | 普通红测试/非零宿主/Review findings 保留其业务结果且可释放；失联/遗弃/持久 Running/无效恢复材料仅使本根不可用，其他根仍完成 |
| ST-LOCAL | 缺 native record、注册前 root 不可用、record 非普通文件、state 路径/写入拒绝只隔离选中位；保留原字节、不建坏位 job，健康位完成；全局 schema/policy 错误仍拒绝 |
| ST-NATIVE-READ | 选中 ownership 下复用单链接/有界身份读取；合成硬链接、IoFailed/InputChanged 仅暂停坏位，两个不同新 request 由健康位完成，原记录保留；普通 source/import 错误仍可释放 |
| ST-RUN-EVIDENCE | 合成 close_job=false 且 run.json 写失败时 null/控制未确认/仅暂停本位；run 缺失、读取拒绝、结构不足/错本单绑定及必要 launch 缺失/不足不能沿用启动前 true；原中断对象保留，控制闭合业务红可释放 |
| ST-RELEASE | 合成 release/close 故障保留主 KeyboardInterrupt/SystemExit 对象；每个取得的 mutex 只释放一次，finish 后不借 abandon 重试；Unconfirmed 不报 Released、不生成成功 final、不继续该 Pool 入场 |
| ST-ISOLATION | 四位分别覆盖 Coding、Review、Testing、Mixed 范围；Review/Testing source 不变；连续复用 root/request/native CID/capture/result 独立，旧单字节不变 |
| ST-COLLECT | 实际 import/prepare/plan/run/collect 链且每单独立收尾；自己的 result 先完成和释放，兄弟单可以仍 Running；final 才标 Released |
| ST-LEGACY | 原 agy/Cursor、Task CLI、A/B、R、first execution、capture 和 launch 生命周期适用回归；v4 不借旧 Accepted，不改旧门禁 |

native conversation 的 Unknown/Mismatch 必须保留，不能把 capture UID 当作 native CID。普通元数据变化与权限/资源政策变化分别判断；不把全历史树或所有异常组合设为普通前置。测试使用合成宿主和公开测试密钥，真实 agy/model/config/Credential Manager 调用为 NotRun。

完整后续真实波至少五个新模型任务：四位同时覆盖 Coding green、Review findings、Testing expected red、Mixed green，第五个在四位全忙时等候并复用首个释放工位。须证明四初始区间重叠、第五开始晚于释放、实际 native CID/task/result/capture 独立、旧单不变和独立终态顺序；一次单站 PassScoped 与三位波不能自动覆盖四位目标。本表是候选验收矩阵，不是实测许可或管理接受，次数/预算和安装身份另冻，无自动重试。
