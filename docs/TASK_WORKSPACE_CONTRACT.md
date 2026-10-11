# 统一工程任务合同 v1（实施规格）

状态：`ProposedRecommended`，文档候选；尚未实现或验收。核验日期：2026-10-04。
任务：LAB-TASK-WORKSPACE-CONTRACT-REPAIR-01；管理：019fe10b-df55-7b82-a9ba-3702dc08c55f。
冻结实现 base：`7a5d921ed2402023b5b21417b12362ed8da5c1d6`；修订基于文档提交 `e64075903e1e2bba11351cb2675703f3ccf35022`。
验收表：[TASK_WORKSPACE_ACCEPTANCE.md](TASK_WORKSPACE_ACCEPTANCE.md)。

## 1. 交付目标与本轮边界

Bridge 为 Coding、排障与独立 Review 提供正常工程工作目录：Coding 可在专用副本增删改、重命名、多文件实现、执行测试与构建；同一次任务可复现、修复、回归；明确授权后可准备锁定依赖。Review 可检索分析并新建报告，但不得修改冻结 source。不同 reviewer 从同一快照创建独立目录，使用一致覆盖分母。

“等价”指这些业务能力和可核验结果，不要求 Gemini、Cursor 和 Codex 的工具名称、原生权限键或推理行为相同。功能目标为完整工程任务；已通过的文件读写小样例不替代完整验收。一次宿主调用内的正常多轮工具执行、失败测试后的修复和回归均允许；无自动重试约束限制的是启动第二次真实宿主调用、换模型或另建付费 job。

初稿的官方/GitHub与冻结实现只读核验记录保留；本修订按独立报告和管理裁决仅检查/修改两文档，不重跑全套代码测试、安装或网页调研。没有模型/上游CLI、部署或宿主权限改动。管理给出的GR03需求为946源码、963包条目、约2.4MB，同快照Gemini 3.8 Flash High与Cursor Grok 4.7 High，中文report/findings/coverage/progress；数量未独立复核，未读取游戏包/源码。

## 2. 已有实现：保留什么，必须补什么

以下定位相对冻结仓库，函数/常量是改动入口，不从新文档推定现有运行版已支持。

| 现有入口 | 精确限制/复用点 | v1 必须处理 |
| --- | --- | --- |
| `bridge/slice_workspace.py::_require_source_path`、`_TEXT_SUFFIXES` | 仅少量 UTF-8 文本后缀，当前连 `.cs` 都不接受；排除秘密名、Git 路径、保留名 | 工程快照保留普通文件原字节；内容类型只影响显示 diff，不影响项目可导入性；继续做路径/秘密范围检查 |
| `_require_editable`、`_verify_tree`、`_verify_frozen_site` | editable 只能是现有 files 子集；work 缺文件或多文件均拒绝 | 新模式按授权相对根接收新增/删除；冻结输入验证与候选树验证分开 |
| `_read_blob`、`paths.py::_run_git` | Git 输出严格 UTF-8 解码，适合旧文本切片，不是通用二进制传输 | 保留有界 Git/路径判断；新增固定 Git argv 的 bytes 读取，拒绝链接和 submodule，不用文本 helper 读原始 blob |
| `PLAN_INSTRUCTION`、`build_plan` | 固定禁止 commands/tests，`counts.command=0` | 按角色/能力/边界字段生成指令与权限；允许任务内执行和调试，记录真实能力与边界 |
| `slice_run.py::_verify_plan_shape`、`_read_settings`、`_build_patched_settings` | 再次强制 command=0；已有 settings.permissions 即拒绝；只插 allow | 新 task 模式独立验证 profile 和配置兼容性；不能只改提示词或删一个断言；旧 slice 行为保持 |
| `_launch_and_capture`、`bridge/winjob.py` | 一次启动、有界 deadline、进程树回收、采集失败显式记录 | 复用；任务内工具循环由 CLI 自身完成，不建 Bridge 调度循环；Job Object 不是文件/网络沙箱 |
| `_restore_settings`、strict JSON helpers | 原字节备份、语义漂移拒绝、合法排版漂移后恢复 | 复用恢复规则与测试；不能为新功能放宽漂移保护或覆盖用户配置 |
| `cursor_run.py::_cursor_config`、`_cursor_argv` | 配置须冻结，固定 Grok 4.7 High 与 --force；不解析业务终态 | 复用身份/输入绑定与采集；task 模式须有已验收的 profile 对应 argv，不直接沿用 --force 当范围保护 |
| `capture/session.py`、`retention.py`、`shadow/replay.py` | 独立密钥、认证加密、封口与滚动、离线回放 | 保留现有协议；metadata 绑定新任务/快照/profile 摘要，不复制一套存储或重做 AGPL/加密底座 |
| `collect`、现有 unified diff | 对既有可编辑文本输出原字节依据的 diff | 新 collector 同时产出完整文件变化清单与产物哈希；文本 diff 为辅助，不是唯一交付接口 |
| 两个 Skill 与发布检查表 | 日常调用仍描述旧切片；agy 固定模型漏写；部署回执入口不够具体 | 由文档/Skill 实施包同步更正，保留已安装版本与候选能力区别，见第 9 节 |

旧 `prepare/plan/run/collect` 与 `cursor run` 保留为 slice v1；新工程任务使用明确的新命名空间 `task` 和 `contract_version=1`。不要悄悄扩大旧 manifest v1 的权限，也不把旧失败工单自动转成新任务。H3 MCP 与退役 Ask AI MCP 不增加入口。

## 3. 输入快照：一次导入，多份独立副本

### 3.1 统一输入身份

来源三选一：精确 Git commit + 显式选择清单；带指定 SHA-256 的 ZIP；带可信逐文件清单的明确目录。仅访问调用方已经授权的精确根，不扫描用户目录或磁盘。目录必须匹配清单，不能只按 live 目录“看起来一样”接收；复制前后核对 size/hash，变化即 `InputChanged`，不自动重拷。

Host 导入器生成唯一 sealed snapshot：排序的规范相对路径、条目类型、字节长度、SHA-256、来源 Git mode（如适用）；保存包 SHA/commit、选择与排除依据。`snapshot_id` 为规范清单摘要；只含内容、路径、必要类型，不把 reviewer、绝对工作路径、mtime 或 ZIP 压缩参数放进内容身份。ZIP 原包 SHA 单列，重复压缩不等于相同原包；解压后 canonical tree 才用于跨 reviewer 比较。

Git 通过固定 `ls-tree -rz` / `cat-file blob` 原字节读取，明确拒绝 `120000` 链接及 `160000` submodule。可复用 Git 导出能力，但不直接以 `git archive` 作为“包含全部所选文件”的依据：其 export-ignore/export-subst 会影响导出，必须核对完整逐文件清单。[Git archive 官方文档](https://git-scm.com/docs/git-archive)

快照包含普通文本与二进制文件原字节，不解码/重写文件内容、不运行导入包内脚本、不取 LFS 网络内容、不递归获取 submodule。Git 可执行位仅记录；Windows 文件执行权限由 profile 决定。凭据、宽泛缓存和无授权内容仍不允许进入快照；选择/排除均记录，禁止静默漏文件后宣称完整覆盖。旧 `_SECRET_NAME` 属于 slice 的保守过滤；工程输入不得仅因普通类名含 token/secret 就整批拒绝合法源码。task 使用明确冻结的敏感路径规则与经管理核对的输入选择，名字疑似项报告给管理，不把业务类名当凭据内容的证明。

### 3.2 ZIP/目录验证的固定次序

复用 Python 3.13 `zipfile.ZipFile` 的格式、压缩流和 CRC 实现，用 `infolist()`、逐项 `open()` 流式复制；只开发下面缺失的输入合同。不能把解压交给模型，也不能直接 `extractall()` 后再检查。标准库会清理部分非法路径，且不提供本产品的冲突与资源合同，需在写入前拒绝非法输入。[Python zipfile](https://docs.python.org/3.13/library/zipfile.html)

1. 核对明确输入根、原包长度与 SHA、全路径普通文件/目录属性；检查所有父级 reparse，拒绝盘符根、UNC 输入根及宽泛用户根。目录输入不跟随链接。
2. 完整审查条目名，包括 CPython `ZipInfo.orig_filename` 与 filename，防止 NUL 被解析器截断后隐藏；ZIP 反斜杠与斜杠按分隔符形成同一规范路径。拒绝绝对/drive-relative/UNC/设备路径、空或 `.`/`..` 分量、ADS 冒号、Windows 保留名、尾点/空格和不可表示的名字。不要“去掉 ..”或改字符后继续。
3. 对整个条目集合检查重复、Windows casefold/NFC 冲突、文件与目录同名、`a` 文件与 `a/b` 前缀冲突；明确目录项与它的普通子文件不算冲突。禁止自动去重/覆盖、大小写重命名或自动剥掉顶层目录；需要 strip-prefix 时由冻结输入清单明确指定，并再次做冲突检查。
4. 拒绝 symlink、设备/FIFO、目录 reparse 属性、加密 ZIP 与 v1 不支持的压缩方法；ZIP v1 支持 stored/deflate。普通文件身份必须保守判定，不能只依据后缀；目录遍历拒绝 symlink/junction/reparse 及多链接普通文件（保守拒绝硬链接输入），禁止输出 reparse/硬链接。
5. 在创建 staging 前核对声明资源限额；流式读时累计实际解压长度、CRC 与 hash，不能只信 central directory 的声明。解压时不嵌套解压其他 archive，不运行任何文件。
6. 只向全新、已核对普通父链的专用 staging 排他创建文件；每次创建重核父链，复制完成后先关闭全部来源句柄，再重新枚举全部属性/清单及验证。来源读取/关闭、验证和 metadata 等所有可失败动作须在最终发布前完成。发布前错误保留专用 staging 并尽力写入失败标签；标签 I/O 失败也不得产生有效最终根。不覆盖旧根、不自动删除/回滚现场；staging 中已写的 manifest/SEALED 保留为失败证据，不构成最终发布。此方案还需部署环境防止并发篡改父目录，普通 path.resolve 检查不能宣称消除了竞态。
7. 全部条目及来源关闭/验证通过后，在 staging 写清单与 sealed 标记，最终 rename 调用紧前检查同一绝对预算；成功 rename 是成功提交的线性化点。rename 成功后不得因事后计时或来源清理改判失败；rename 失败按既有错误契约处理，保留 staging 并尽力标签，不删除/覆盖/回滚证据。为每个任务/每个 reviewer 各复制一次，再逐字节核对。不是共享可写目录、hardlink 或 junction。输入原包、原始业务仓库及 sealed snapshot 不给 Worker 写权限。

ZIP 长度验证补充（LAB-TASK-ZIP-LENGTH-REPAIR-01，2026-10-05）：stored 的压缩/展开长度必须相等；逐成员核对 local/central 的 flags、method、CRC 与长度。无 descriptor 时 CRC/长度须一致；有 descriptor 时本地零占位或已知正确值可接受，最终 descriptor（有/无签名）须与 central 一致。ZIP64 本地长度按扩展字段解析，descriptor 使用相应 64 位长度，不以经典字段的 sentinel 当实际长度。只补这些缺失校验，继续复用 Python 3.13 zipfile 的目录解析、逐项 open、解压与 CRC。读取使用独立 ZipInfo 副本留一个长度探测字节，避免声明展开长度截断实际返回流；检查实际长度、压缩字节耗尽及 deflate 真正结束，拒绝未结束、尾随字节或第二压缩流。目录无输出文件，空流验证在 staging 前执行；记录不一致在 staging 前拒绝，复制中的流/CRC 失败保留失败 staging。本补充保持 stored/deflate 与既有资源上限，不增加分卷、加密、其他压缩方法或超限 ZIP64 支持承诺，也不表示实现自检已完成独立 A 验收。[PKWARE APPNOTE §4.3.7/4.3.9/4.4.7–9/4.5.3](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT)。

导入 deadline 是协作式单次绝对预算，自导入入口计时，贯穿来源预检、读取/句柄关闭、选择、复制、验证、哈希及 metadata，不在阶段之间重置。rename 前到期返回 `DeadlineExceeded`，来源关闭异常按既有错误契约失败，二者都不得发布有效最终根。最后一次 OS rename 自身不可抢占；若紧前预算检查通过、rename 跨时返回成功，仍属已提交成功。该语义不承诺严格墙钟抢占，也不依赖事后 best-effort 标签撤销成功资格。以上 deadline/最终提交/失败可见性澄清按管理在 2026-10-05 对 LAB-TASK-PUBLICATION-REPAIR-02 的裁定执行，不代表完整 A 已验收。

默认资源 policy 是工程判断的实施初值：压缩包 ≤64 MiB、条目 ≤20,000、展开总量 ≤512 MiB、单文件 ≤64 MiB、单文件展开/压缩比 ≤200、深度 ≤32；单路径分量 ≤255 字符（Unicode 码点，不是255字节），同时须满足目标文件系统分量限制；最终绝对物理路径含根和分隔符，预算为 ≤240 个 UTF-16 码元，导入 deadline 60 秒。路径身份保留原始 Unicode，不做 ANSI 折叠或 NFC 改名；NFC/casefold 只作为集合冲突与敏感/排除范围的比较键，不替换原名精确引用（第7.1节），拒绝不可编码的孤立 surrogate。零压缩长度且有展开内容拒绝。上限按实际字节与磁盘余量检查；超限明确阻断，不跳过条目或扩大限额。物理预算不足返回 `PathBudgetExceeded`，再申请明确短路径，不静默换目录。冻结 policy 可收紧或采用已授权上限，不提供任意无限值。

磁盘检查按管理 2026-10-05 的 LAB-TASK-DISK-CAPACITY-REPAIR-01 冻结要求定义：创建 staging 前，在已核对的输出父目录调用标准库 `shutil.disk_usage`，要求当前 `free` 字节不少于本次实际保留文件的声明长度总和。ZIP 使用保留成员的展开长度，目录使用已核验清单/实际长度；Git 在选择与排除后以既有固定 `--no-replace-objects cat-file -s` 预取保留原 blob 的长度，并在 staging 前核对单文件及累计 policy 上限。排除内容不写入，不计入内容待写总量；排除记录仍进入清单。每个实际内容 chunk 写前按该 chunk 长度复查其输出父目录的当前余量；每块写后刷新 Python 缓冲，再检查下一块/文件。manifest 与 SEALED 分别在排他创建前按实际待写序列化 bytes 查询，清单包含排除记录的实际字节，不预估或另加固定 metadata/安全余量。等于待写长度可通过该次容量检查，后续写入与 metadata 仍须各自通过；内容总量预检不声称已预留整次导入的空间。

上述查询、Git 大小预取及缓冲刷新消耗入口创建的同一绝对 deadline，查询返回后再次核对，不重置预算。容量不足沿用 `ResourceLimitExceeded`；查询或实际写入/刷新发生 I/O 异常沿用非敏感 `IoFailed` 并保留 cause。staging 前拒绝无新 staging；开始后拒绝保留专用现场，无最终根。失败标签仅为尽力恢复记录，标签自身不执行容量验收，不依赖标签保证失败根不可接受。成功 rename 后没有容量查询或其他可失败检查。查询为点时观测，不是配额、全局预留或文件系统分配开销预测，不能防止其他进程在查询后耗尽空间，也不承诺小文件/目录/文件系统 metadata 的分配开销；实际 ENOSPC 仍必须拒绝且保留现场。本澄清不表示自检已替代独立 A 验收。[Python 3.13 disk_usage](https://docs.python.org/3.13/library/shutil.html#shutil.disk_usage)；[Git cat-file](https://git-scm.com/docs/git-cat-file)。

## 4. 专用工作目录与最小请求

```text
snapshot/                         # Host 封存；多个任务只引用其身份
task-<id>/
  task.json                       # Host 冻结合同；Worker 不改
  control/TASK.md                  # Host 可信任务说明，不与输入 TASK.md 冲突
  control/deployment-profile.json  # 冻结部署profile，无秘密；不代表实际权限已授予
  control/authorization.json       # 已有可信授权记录/引用；Worker不改
  work/                           # Coding 可写副本；Review 独立只读 source 副本
  out/                            # Worker 的交付与报告
  scratch/                        # 临时分析、缓存与允许的依赖准备
run-<id>/                         # 单次启动、配置恢复与加密 UID；不放入 work
result-<id>/                      # Host collect 生成的验收清单与候选产物
```

源包里的 AGENTS、配置、README 和脚本属于输入材料，不自动提升为授权。Host 控制文件放在独立 namespace；各宿主会自动加载的项目控制配置必须在 prepare/plan 中识别。与本 profile 冲突时返回 `InputControlConflict`，在模型启动前停止；不得静默执行包内 hooks/setup、覆盖配置或隐藏源码条目。管理核对的原生项目规则按精确原名与原字节摘要列入 Authorization.input_control_bindings.files，且 work 下对应路径必须 protected；A 的 trusted_control_files 仅为导入声明，不能替代这项任务绑定。源包原生配置不能凭规则绑定豁免（详见§7.4）。Review 的工作区根可设为 task 根、source 在 work 子目录、out 可写；宿主具体配置发现行为必须实测，不能只靠布局假定不会加载嵌套配置。

task.json 必需字段（路径均为任务根内相对路径；下面值是合成规格示例）：

```json
{
  "contract_version": 1,
  "task_id": "CODING-FIXTURE-01",
  "role": "Coding",
  "snapshot_id": "<sha256-of-canonical-inventory>",
  "snapshot_manifest_sha256": "<sha256>",
  "instructions_sha256": "<sha256>",
  "deployment_profile_id": "<registered-deployment>",
  "deployment_profile_sha256": "<sha256>",
  "capabilities": {"execute": true, "web_reference": false, "prepare_dependencies": false},
  "execution_boundary": "declared_scope",
  "authorization_sha256": "<sha256>",
  "read_roots": ["control", "out", "scratch", "work"],
  "write_roots": ["out", "scratch", "work"],
  "protected_paths": ["control", "task.json", "work/vendor"],
  "required_outputs": ["out/progress.json"],
  "acceptance_ids": ["CODING-01", "TEST-01"],
  "deadline_seconds": 3600,
  "source_output_bytes_limit": 536870912
}
```

role 只取 Coding/Review；排障是 Coding 的目标，不增加第三个 runner。角色和能力字段显式必填，不创建各组合命名 profile。snapshot、instructions、部署 profile、能力、边界模式和授权记录绑定计划摘要。未知字段、重复 JSON 键、类型不符、越界根、write 根本身落在 protected 内、未登记 deployment/host 和 manifest 漂移均在启动前拒绝。task能力/读写根须在可信Authorization与DeploymentProfile允许集合内，task边界与授权一致且在deployment.execution_modes内；不得自行升级。protected子树优先收紧父write根。deadline v1为必填整数1–3600秒，所有已有角色及agy/Cursor通路共用上限；较短显式值继续生效，字段扩容不延长既有真实调用授权。

工作时限从runner/validator入口计时，启动时减去已消耗时间，剩余秒数传给共享采集器；正常进程结束后立即进入收束，不等满期限。agy Task的固定`--print-timeout`值按剩余秒数向上取整为1–60分钟（`ceil(remaining/60)m`），精确截止仍由外层等待控制；Cursor沿用既有argv，仅使用外层剩余工作预算，不添加未经验证的native时限flag。新增分钟值的CLI原生支持与provider/tool独立期限仍需新实测核验。旧slice默认1020秒及固定15m保持，kill和pipe join宽限各30秒、单项配方预算与配置互斥保持。

prepare、collect及saved collection核验仍在各自入口按同一字段新建阶段deadline，不改为全流程计时框架；因此3600不是整个工具/经纪过程的墙钟上界。配置恢复、封口、后置收集/复测/reader及工具最外层预算必须在新实测包中单列，不能在3600秒直接终止validator而截断恢复/终态回执。

Coding 的合同允许 work 内普通文件创建、修改、删除和重命名，protected子树收紧；实际运行仍须有效授权。Review write_roots只能有out/scratch；可选execute若运行写入性构建，只用独立scratch副本，不改冻结work。Host不自动应用业务树。

## 5. 角色、能力与执行边界：一次冻结，分别核验宿主

### 5.1 v1 最小能力面

只有 Coding/Review 两个角色。Coding 允许授权 work 内正常增删改重命名、out/scratch 交付；Review 只读 work、可写 out/scratch。以下三个布尔能力相互独立，不为每种组合增加 profile：

| 字段 | 为 true 时允许 | 前提 |
| --- | --- | --- |
| `execute` | 已有工具链的必要本地测试/构建/诊断和授权辅助脚本，同一次调用复现→修复→回归 | 登记工具链/命令类别、cwd 与写根；不提供通用任意命令服务。Review 执行写入性构建必须使用独立 scratch 副本，不能写 work |
| `web_reference` | 已授权的只读网络搜索、官方/其他文档查询、错误资料检索 | 冻结用途、服务/来源范围和数据规则；不限定只能 GET 或两三个域名。搜索提交查询可能使用 POST，语义只读按目的和外部变更判定；不授权上传源码/凭据、账号变更或外部写入 |
| `prepare_dependencies` | 按锁文件及登记 package manager 在任务环境/scratch/cache 准备依赖 | 要求 execute=true，锁 SHA、工具/缓存根、安装脚本范围；离线缓存与联网 registry/传递依赖范围分别明确；不改锁解失败、不全局安装 |

普通 Coding 的基础组合为 execute=true、其余按任务明确选择；静态 Review 为 execute=false、依赖=false，网络查询可独立选择。未启用能力是合同中的禁止项，是否由宿主强制另记证据。设计和离线实现获准不等于这些实际运行权限已经取得。

2026-10-10 日常 Coding 范围裁决同步：在工单明确指定的工作目录和允许文件范围内，Worker 可为完成任务做必要目录/源码检查、哈希核对、代码编辑、本地测试与辅助脚本操作；指定管理配方是必须完成的验收，不是 Worker 可用操作的完整清单。冻结控制、验收配方与 protected_paths 仍不可修改；任务外写入、凭据、额外网络、依赖安装、生产与远端仍须单独授权。管理仍以实际产物、独立固定测试、宿主终态、加密采集与恢复为准，Worker/CLI 声明和 OS 执行事实分开，Unknown 不自动判为通过或违规。

task 引用登记 deployment profile：CLI/后端与工具链身份、可用工具面、原生权限映射、路径/网络可触达范围及验证证据。角色、能力和授权范围在部署/派单时一次冻结，整次调用复用，不逐条测试命令审批。未授权或未知网络继续遵守已有授权；web_reference=true 本身不授权任何新目的地。已明确授权的广泛搜索/查询可按范围使用，不把每个来源都造为新 profile。依赖准备和外部写入分别判定，外部写入不在 v1 能力中。正常引用 URL 是查询材料，不是开放供应商路由或任意请求接口；task 不能传入新 executable/任意 shell argv/权限文本。

Worker 不得主动更新/登录宿主、读取凭据、配置/注册 MCP、包发布、远端 Git 写入、调用任意外部服务、提权或改动物理机。厂商正常自动更新不被本合同新增禁用；记录实际后端变化并按能力 gate 重新核验，不承诺入口哈希不变就等于版本冻结。任务内删除普通副本文件属于 Coding 授权，不包括删除 snapshot/control、业务树或宿主目录。全局工具链、账户、额度与发布仍由另行授权的流程处理。现有固定模型保持 agy `gemini-3.8-flash-high` / `high`、Cursor `grok-4.7-high` 非 Fast；不把本合同变成模型/预算接口。

### 5.2 两种边界模式与宿主核验

`execution_boundary` 是正交字段，不按角色或网络组合增加 profile：

| 模式 | 实施路线和真实运行门禁 |
| --- | --- |
| `declared_scope` | 普通可信工程设计路线。快照副本、指令/原生规则、收尾核验约束行为；同用户 shell 可能触达其他用户可访问路径，未经强制的网络也可能可达。真实运行前集中说明范围并取得所需实际权限，且必须完成本机命令执行、终止、配置恢复、产物回收的 R 验证；O 通过不能直接上线 |
| `required_enforced` | 仅任务明确要求强制文件/网络范围时启用；必须有对应工具/进程/网络 enforcement 的本机证据。缺失时 Blocked/ExecutionBoundaryUnverified，不能声称可用或降级为 declared_scope |

不把 VM/沙箱建设作为整个产品前置；输入/工作区/回收和 declared_scope 离线实现可先做。本次管理只批准设计与离线实现，未接受实际同用户 shell 触达风险、未批准部署；后续按既有有效授权集中补齐实际运行项，不为普通 Phase 重复确认。

| 项目 | agy | Cursor |
| --- | --- | --- |
| 文件与命令能力 | 官方 headless 支持读写和预先授予 command；当前实机只验过窄文件流程 | 官方 print 有写入/shell，CLI 有 Read/Write/Shell 规则；当前实机只验过窄文件流程与一个拒读样例 |
| 项目/全局配置 | 当前 Bridge 临时修改 CLI 用户 settings 并严格恢复；持久 permissions 与旧 runner 不兼容 | `.cursor/cli.json` 只有 permissions 可项目配置；其他 CLI 设置全局；不能在项目文件猜写审批/sandbox 键 |
| 自动批准 | 预授予 profile 规则后仍须证明 Windows 行为；always-proceed 与 deny/共享层优先级未实测 | --force 只对显式 deny 保留约束，不能当 allow-only 模式；不能用 `Shell(git)` 表示只准测试，因为它覆盖整个 git 命令族 |
| Shell/搜索路径范围 | command 匹配不验证脚本实际读写；`allowNonWorkspaceAccess` 不等于 shell OS 边界；共享 ALLOW 优先级未知 | Read/Write 规则不自动约束 shell 内部文件访问，也不能先假定覆盖 Grep/Glob；必须测试完整工具面 |
| Windows OS/网络边界 | 既有部署参考记录 Windows 旧权限系统；新版页面本轮不可获取，不据此宣称本机可强制隔离 | 当前官方 sandbox 平台页列 macOS/Linux，不能移植为 Windows 已验收；本轮没有 native sandbox CLI 探测 |
| 原生 argv/输出 | 固定 argv + wrapped stream；保留 timeout、恢复、封口 | 固定 argv + NDJSON；新 profile 的批准/沙箱组合必须有独立 gate，不能仅改 flag 就上线 |

初稿事实依据：[agy headless](https://antigravity.google/docs/cli/headless/)、[Cursor parameters](https://cursor.com/docs/cli/reference/parameters)、[Cursor permissions](https://cursor.com/docs/cli/reference/permissions)、[Cursor configuration](https://cursor.com/docs/cli/reference/configuration)、[Cursor Run Modes](https://cursor.com/docs/agent/security/run-modes)，及冻结部署参考。初稿agy permissions/terminal-sandbox页面获取失败；本修订未重复网页核验，不提升为新版实测。

Python/pwsh/node/msbuild 能运行项目脚本；前缀/首 token 许可、cwd、环境变量、只读属性、同用户 ACL 和 Job Object 均不能独自证明路径/网络隔离。deployment 记录实际 `enforcement.method`、覆盖工具面和可访问范围；declared_scope 的未强制部分标 Unverified，不写“禁网”或“仅可触达副本”。required_enforced 才要求相应隔离用例通过，不自动加 unrestricted/skip-permissions 或安装容器/VM。

模型连接网络与 Worker 子进程/WebFetch 网络分开。现有供应商连接不授予任务查询、依赖安装或任意外部服务权限。R 核对已启用能力确能执行和实际范围；required_enforced 额外检查 domain/重定向/代理/IP 与子进程约束。没有强制机制时声明事实，不用环境变量/提示词冒充网络拒绝。

### 5.3 配置与恢复复用

Cursor 优先生成冻结项目 permissions，与用户全局配置合并语义需复验；保护 control/config 不能被 Worker 写入。agy 优先核验可用任务作用域；若仍需临时全局改动，整次调用只生成一次 profile 增量，严格核对 before/expected-after 与原字节恢复，并对同一配置取得独占协调。跨任务配置竞争、已有用户 deny 冲突或未知作用域在启动前阻断；不删除 deny、追加根通配符或强行覆盖权限对象。没有权限改动时不触碰设置；仍不反复补入自然缺省的 false。

新 task runner 兼容已有权限对象的实现要单独 review；直接复用旧 `_read_settings` 会拒绝它，直接跳过校验则破坏恢复。允许方案是复用 strict JSON、原字节备份/恢复和漂移判定，在 task 专用分支校验受控 profile delta；未知用户字段原样保留。恢复失败为 transport/lifecycle 失败，产物保留为未接受候选，不能补一次调用或覆盖漂移现场。

## 6. 结果合同与明确续接

生产 request 应明示 progress 五字段与 Completed/Partial/Blocked 完整枚举，未来 Task Note 同样冻结这项约束；Completed 是 Worker 进度而非 Accepted。AGY 环境及 source-only 原生事件重析候选、限次/脱敏/Unknown 边界见 [AGY_LIVE_ADAPTER.md](AGY_LIVE_ADAPTER.md)。collector 不接受 Candidate，也不重写历史进度。

Worker 写 out/progress.json 及任务 required_outputs；Host collect 生成 result.json、changes.json 与 artifacts.json，Worker 不能把自述替代 Host 验证。原始报告/结果原样保留，Host 校验单列；缺失错误产物不自动补成 Worker 成功。测试 stdout/stderr 全量留产品已授权加密管道或专用加密 sidecar；常规 JSON 只留工具/recipe、cwd 相对路径、退出码、时间、报告相对路径/哈希、必要计数，避免复制源码/完整命令文本。

result.json 分开记录 worker_status（Worker 自述）、host_observations（实际观察/结构核验）与 management_decision=null。Host collect 不裁定审查质量，不自动把全部 acceptance_ids 标 Pass；管理在独立裁决记录引用 result SHA 后给出 final_status。业务状态仅 Completed/Partial/Blocked，transport 完整和 CLI success 不直接提升为 Completed。

| 管理 final_status | 裁决依据 |
| --- | --- |
| Completed | Host 生命周期/捕获/恢复、范围、必需输出/测试证据通过；管理确认全部必需验收项及业务质量，Review 还须覆盖完整。结构完整或空 findings 不证明审查质量 |
| Partial | 已有合法产物或实质进展，但覆盖/测试/输出未完成、deadline/上下文不足；逐项列缺口与下一步；不会自启动下一次 CLI |
| Blocked | 缺授权/能力/输入或无可继续安全工作；严重范围、恢复或证据异常单列 failure_reason，即使 Worker 已声称 Completed 也不接受 |

测试至少记录唯一 test_run_id、phase=reproduce/regression/build、recipe_id、锁定工具链身份、exit/timing、JUnit/构建报告引用与哈希；记录失败后修复再通过，两条都保留。不把 `pytest` 字符串出现在回复或文件名里当执行证明。原生事件无法给出可核验命令/退出码时，profile 可使用事先登记、已验收的证据包装 recipe；包装器不被当成 OS 沙箱，也不开放任意宿主命令接口。无可靠测试证据时只能 Partial。

changes 对授权 work 原始清单和收尾清单做 bytes 比较：added/modified/deleted 明确列出 before/after length/hash；纯原字节同 hash 的一对 delete/add 可附 `rename` 关联，歧义时不猜。编辑后重命名按 delete/add 或明确未验证 rename suggestion，绝不因未识别 rename 丢文件。二进制变化用文件/hash 交付，不强制 UTF-8 diff。源文件编码、BOM、CRLF/LF、末尾无换行均保留；patch 只对可解码文本辅助输出。

生成目录如 `.venv`、缓存、build 单独登记 generated roots/大小，不当源码交付，也不能静默忽略新增源码。收尾重扫 reparse/链接、protected hash 与输出上限；范围失败仍保留失败产物，不自行还原 Worker 行为以冒充通过。交付不自动应用业务 worktree，不推送或创建 PR。

续接精确字段见§7.1，task_manifest_sha256绑定原角色/能力/边界/授权，保留候选/产物、缺口、最后有效测试与session引用。Host核对身份后管理可派新任务；真实调用按届时有效授权，不由续接数据新增权限。v1不自动continue/resume/重试/换供应商/调度额度。

Review findings 含 id/severity P0–P3/file/line/evidence/recommendation；line 是 Worker 提供位置，Host 另记能否在冻结文件定位。coverage 的 Analyzed/Excluded/Failed/NotAnalyzed 是 Worker 声明，Host 核对每路径唯一一行、分母/引用及 finding 可定位性，不证明模型理解或审查质量。读取/grep/presence 的 Host 观测另列，不能替代 Analyzed；源码排除不从原分母移除，合理非源码 Excluded 留理由。完整声明是管理判 Completed 的必要条件，质量由独立对比/管理验收判断。所有 Review JSON/中文 Markdown 输出统一 UTF-8，无 ANSI 转码；源文件和候选原字节仍不改编码。

GR03 类型任务的中文 out/report.md、findings.json、coverage.json、progress.json 使用同一 snapshot_id 和 946/963 两个明确分母；package entries 与文件/目录、source 选择的对应必须由导入清单核对，不能由模型猜数。每个 reviewer 自有 out/scratch/work，禁止互看其他 reviewer 结果；管理之后独立比较，不让一个 reviewer 的结论成为另一个的输入。

## 7. 最小实施面与可并行边界

新增三个模块，不建 provider 平台、调度服务或复杂权限解释器：

| 包/写集合 | 实施内容 | 必须交回 |
| --- | --- | --- |
| A：`bridge/task_input.py` + 输入单测 | Git bytes、ZIP/目录导入、canonical inventory、资源/路径/控制冲突验证；复用 paths/strict JSON/stdlib zipfile | snapshot manifest v1 与跨来源同树 fixture；普通源、二进制和 `.cs` 通过 |
| B：`bridge/task_workspace.py` + 工作区/collector 单测 | 从 snapshot 创建角色副本；task manifest 校验；新增/删除/重命名与 bytes artifacts；Review coverage/results 检查 | task/result/changes/artifacts schema，Coding/Review 无供应商离线 fixtures |
| C：`bridge/task_run.py` + adapter/profile 单测 | 同一 deployment profile 上映射角色/三个能力/边界模式；统一 plan/preflight；复用 launcher/capture/restore；真实能力 gate | fixture-only agy/Cursor transport 与管理业务裁决分离；不直接真实运行 |
| D：CLI/发布/Skill 文档 | `cli.py` 新 task namespace；README/usage/发布清单/Skill 与 sdist inclusion 同步；必要 AGENTS 短规则 | 新旧入口区分、可发现部署回执、固定模型与能力表 |

A 先按下表交可复用快照 fixture；B/C 可使用同一冻结 schema 并行做本地 fixture，接入后再集成。D 最后接 CLI/打包/文档，拥有这些共享文件。现有 slice_run/cursor_run 的必要生命周期抽取由 C 单独拥有；A/B 不触碰捕获/恢复。各包独立 worktree、精确 base、allow-list、测试与独立 Review。字段变更交管理先裁决再同批更新，不由各包自添 profile。真实运行前完成对应 R 与实际权限；普通 Phase 不重复确认。

建议 CLI（待实现，不可调用当前安装版）：`task import` 选 git/zip/directory；`task prepare --snapshot ... --task-manifest ... --task-note ... --deployment-profile ... --authorization ... --out ...`；`task plan --task-root ... --host agy|cursor --trusted-control-root ... --trusted-inputs-sha256 ...`；`task run` 使用同一可信根/摘要，缺省 preflight、--execute 才启动；`task collect --task-root ... --run-root ... --out <fresh result root>`。角色/能力/边界在 task manifest 中一次写清，不造组合 profile；import 的 commit/ZIP hash/目录 manifest 必填，run 不接受任意 model/argv/供应商 URL。

### 7.1 A/B/C 共用的最小 JSON 接口（v1 冻结）

记 H=64位小写SHA-256字符串，P=通过第3节检查、保留原始Unicode的相对路径，S=非空字符串，I=非负整数（bool不算int）。所有合同JSON对象拒绝未知/重复键和NaN/Infinity；settings等外部配置仍按现有规则保留未知字段。规范字节统一为 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`，无BOM/尾换行；路径数组按原路径UTF-8字节排序，身份不做NFC转换。原始输入/候选字节不套JSON序列化。

| 对象 | 准确字段和类型；持久位置 |
| --- | --- |
| InputSource（A参数） | 共用 kind=git/zip/directory。git：root:S（已授权绝对根）、commit:S（精确40位SHA）、paths:list[P]（精确文件，不是glob）；zip：path:S、sha256:H、strip_prefix:P或null；directory：root:S、manifest_path:S、manifest_sha256:H。仅所选kind字段存在 |
| InputPolicy（A参数） | package_bytes_limit:I=67108864、entry_count_limit:I=20000、expanded_bytes_limit:I=536870912、file_bytes_limit:I=67108864、expansion_ratio_limit:I=200、depth_limit:I=32、component_codepoints_limit:I=255、physical_path_utf16_limit:I=240、deadline_seconds:I=60；source_paths:list[P]（原声明源码清单）、excluded_paths:list[{path:P,reason:S}]（明确排除）、sensitive_paths:list[P]、trusted_control_files:dict[P,H]。数字为正且不超过已授权上限；数字上限键可省略以使用冻结默认值，四个非数字键必填；不是可传入正则/任意命令的policy语言 |
| SnapshotManifest（A→B/C） | contract_version:int=1、snapshot_id:H、source:{kind:S,identity:S,selection_sha256:H}、entries:list[Entry]、source_paths:list[P]、excluded_paths:list[{path:P,reason:S}]；snapshot_root/manifest.json，普通字节树在snapshot_root/source。Entry={path:P,kind:file/directory,bytes:I,sha256:H或null,git_mode:100644/100755或null}；目录bytes=0/hash和mode=null，所有父目录显式一次、根不列入；file hash必填，git_mode仅来源记录。source_paths每项必须在file entries或excluded_paths中 |
| TaskManifest（B→C） | 第4节JSON就是准确键集合：contract_version:int=1，task_id:S，role:Coding/Review，snapshot_id/snapshot_manifest_sha256/instructions_sha256/deployment_profile_sha256/authorization_sha256:H，deployment_profile_id:S，capabilities:{execute:bool,web_reference:bool,prepare_dependencies:bool}，execution_boundary:declared_scope/required_enforced，read_roots/write_roots/protected_paths/required_outputs:list[P]，acceptance_ids:list[S]，deadline_seconds:int1–3600，source_output_bytes_limit:正整数；task_root/task.json |
| DeploymentProfile（B/C） | contract_version:int=1、id:S、host:agy/cursor、receipt_sha256:H、roles:list[Coding/Review]、supported_capabilities:上述三bool对象、execution_modes:list[declared_scope/required_enforced]、read_roots/write_roots:list[P]（任务相对根，经回执映射到已授权物理父根）、toolchain_refs:list[S]、enforcement:{method:S,file_scope:Declared/Enforced/Unverified,network_scope:Declared/Enforced/Unverified,evidence_refs:list[Evidence]}；control/deployment-profile.json。refs仅引用登记工具链/证据，不接自定义命令 |
| Authorization（B/C） | contract_version:int=1、task_id:S、grant_ref:S、receipt_sha256:H、capabilities:上述三bool对象、execution_boundary:上述枚举、read_roots/write_roots:list[P]、web_scope:S或null、dependency_scope:S或null、input_control_bindings:{task_fields_sha256:H,files:dict[P,H]}；control/authorization.json。binding必填且不能null，files允许空；摘要构造顺序及原名匹配见§7.4。grant_ref/各scope只引用已有可信管理授权，C须与部署回执核对；自填字符串不能创建授权，启用能力要求对应有效scope |
| Plan（C） | contract_version:int=1，task_id:S，task_manifest_sha256:H，deployment_receipt_sha256:H，host:agy/cursor，route:{model:S,effort:S或null}，execution_boundary:上述枚举，capabilities:上述三bool对象，preflight_status:Ready/Blocked，blockers:list[S]，evidence_refs:list[Evidence]；可信control中的plan.json。model/effort只能由固定adapter选择，不能caller定义；Ready还须有效实际授权与对应R |
| RunReceipt（C→B） | contract_version:int=1，task_id:S，plan_sha256:H，transport_state:NotRun/Completed/Failed/TimedOut，launch_count:0/1/null，capture_uid:S或null，capture_state:NotRun/Sealed/Incomplete，restore_state:NotRun/Unchanged/Restored/Failed，test_observations:list[TestObservation]，evidence_refs:list[Evidence]，blockers:list[S]；run_root/run.json。NotRun必须为0，Completed必须为1；null仅表示一次潜在执行未确认，必须Failed并包含LaunchUnverified，不允许再尝试；已确认后不得降级为0/null |
| Result（B→管理） | contract_version:int=1，task_id:S，snapshot_id:H，task_manifest_sha256:H，plan_sha256:H或null，worker_status:Completed/Partial/Blocked或null，host_observations:{transport_state:上述枚举,scope_status:Pass/Fail/Unverified,outputs_status:Pass/Fail/Unverified,coverage_status:Complete/Incomplete/Invalid/NotRequired,test_observations:list[TestObservation],acceptance_observations:list[{id:S,result:Pass/Fail/Unrun/Unverified,evidence_refs:list[Evidence]}]}，changes:list[Change]，artifacts:list[Artifact]，blockers:list[S]，continuation:Continuation或null，management_decision:null；result_root/result.json，同值changes/artifacts另存changes.json/artifacts.json。未观测ID为Unrun/Unverified，不自动Pass |

Entry数组按path排序；snapshot_id=规范序列化 `{contract_version:1,entries:[{path,kind,bytes,sha256}]}` 的SHA（不含git_mode）。source.identity为Git commit/ZIP SHA/目录manifest SHA；selection_sha256=规范 `{source_paths,excluded_paths}` 的SHA，excluded_paths按path排序。因此同原字节树跨来源同snapshot_id，来源/选择差异仍由完整manifest SHA绑定。逻辑覆盖分母为entries与excluded_paths的不重复路径并集；source_paths保留原声明成员和原名，按原名UTF-8字节形成规范序列，排除不缩源码分母。最终manifest使用规范字节，snapshot_root/SEALED是其H的ASCII字节、无尾换行；B/read_snapshot核对两者和tree，不从live树猜身份。

A 路径语义澄清（LAB-TASK-PATH-SEMANTICS-REPAIR-03，2026-10-05）：InputSource.git.paths 与 InputPolicy 的路径列表参数允许无序，导入器验证后在内部按原路径 UTF-8 字节排序，不修改调用参数、原名或成员；持久 source_paths、entries、excluded_paths 必须有序且唯一。read_snapshot 拒绝无序或重复的 source_paths，即使其 selection/SEALED 摘要正确；不自动重排或改写旧封存结果。此前已发布的无序清单须重新导入，不能凭全量测试通过视为规范。无序声明的 selection/完整 manifest SHA 因规范序列而变化，内容 snapshot_id 规则不变。

敏感与排除是范围规则，使用既有 NFC 后 casefold 的逻辑等价键判断同路径或带 `/` 分量边界的子树；这沿用第3.2节的逻辑等价键，不改写原 Unicode，不声称所有逻辑等价名都是 Windows 物理 samefile。排除范围必须覆盖实际输入，输出逐项记录来源原名及原因；重叠规则采用分量最深的原因，等价重复敏感/排除规则以 InvalidPolicy 拒绝，不自动合并。排除先于敏感检查，仅保留文件可触发 SensitivePathImported；source_paths 的精确声明成员仍保留在保留文件或明确排除记录中。source_paths 原名成员、trusted_control_files 的原名与 SHA 绑定、ZIP strip_prefix 的剥离声明均为精确匹配，别名不扩大可信引用或剥离范围。集合身份冲突继续拒绝，reader 仍核对原名排除覆盖及跨集合等价冲突。详见 TASK_PATH_DECISION 的本轮语义表；实现自检不构成独立 A 接受。

紧凑公共记录：Evidence={ref:S,sha256:H或null,origin:WorkerReported/HostObserved}，ref是登记的相对产物或加密UID引用，未核验hash=null不算Pass。TestObservation={test_run_id:S,phase:reproduce/regression/build,recipe_id:S,toolchain_sha256:H或null,source_tree_sha256:H或null,exit_code:int或null,start_utc:S或null,end_utc:S或null,evidence_refs:list[Evidence],origin:上述枚举}，缺实际字段记Unverified。FileStamp={bytes:I,sha256:H}；Change={path:P,kind:added/modified/deleted,before:FileStamp或null,after:FileStamp或null,rename_from:P或null}，纯rename关联仅附added项，歧义null。Artifact={path:P,bytes:I,sha256:H,origin:WorkerOutput/CandidateTree/HostValidation}。Continuation={snapshot_id:H,candidate_tree_sha256:H,artifact_manifest_sha256:H,task_manifest_sha256:H,remaining_acceptance_ids:list[S],remaining_paths:list[P],last_test_run_id:S或null,blocker:S或null,next_action:S,session_id:S或null}；引用不是新调用授权。

Worker coverage.json={contract_version:1,task_id:S,snapshot_id:H,entries:list[{path:P,state:Analyzed/Excluded/Failed/NotAnalyzed,reason:S}],package_entry_count:I,source_file_count:I}，按冻结逻辑清单每路径一行；findings.json={contract_version:1,task_id:S,snapshot_id:H,findings:list[{id:S,severity:P0/P1/P2/P3,file:P,line:正整数,evidence:S,recommendation:S}]}；progress.json={contract_version:1,task_id:S,status:Completed/Partial/Blocked,summary:S,remaining_paths:list[P]}。这是Worker声明；Host只输出对应结构/引用观测，最终业务裁决单列。

### 7.2 导出函数签名与交接

以下为待实现签名，不新增类层或权限解释框架。全部参数keyword-only；字典按上表严格验证。部署profile和authorization由已有可信管理/部署回执冻结后供给，不由Worker生成；B保存其规范JSON到control，校验第4节H，C对照登记部署回执验证权限与R证据，不把自由文本当授权。

```python
# task_input.py
def import_snapshot(
    *, source: dict[str, object], policy: dict[str, object], snapshot_root: Path
) -> dict[str, object]: ...
def read_snapshot(*, snapshot_root: Path) -> dict[str, object]: ...
# task_workspace.py
def prepare_task(
    *,
    snapshot_root: Path,
    task_manifest: dict[str, object],
    task_note: bytes,
    deployment_profile: dict[str, object],
    authorization: dict[str, object],
    task_root: Path,
) -> dict[str, object]: ...
def collect_task(
    *, task_root: Path, run_root: Path | None, result_root: Path
) -> dict[str, object]: ...
def verify_input_controls(
    *,
    task_root: Path,
    task_manifest: dict[str, object],
    deployment_profile: dict[str, object],
    authorization: dict[str, object],
) -> None: ...
# task_run.py
def plan_task(
    *,
    task_root: Path,
    host: Literal["agy", "cursor"],
    trusted_control_root: Path,
    trusted_inputs_sha256: str,
) -> dict[str, object]: ...
def run_task(
    *,
    task_root: Path,
    plan: dict[str, object],
    run_root: Path,
    trusted_control_root: Path,
    trusted_inputs_sha256: str,
    execute: bool = False,
) -> dict[str, object]: ...
```

返回依次为SnapshotManifest、SnapshotManifest、TaskManifest、Result、None、Plan、RunReceipt。read_snapshot重验封存manifest/tree；prepare_task核对task_note原字节instructions_sha256并建副本；verify_input_controls是B的只读Host导出，不授予执行权限；collect_task允许run_root=null用于未运行fixture，但transport=NotRun，management_decision=null。输出根都须全新；失败保留现场。各模块导出TaskInputError/TaskWorkspaceError/TaskRunError（RuntimeError子类，code:S、非敏感消息），已有BridgePathError在新入口映射并保留cause，旧入口异常不改；不自行再调用模型。C Ready/Blocked不等于管理业务裁决。CLI只包装固定入口，不开放caller-selected函数或任意工具链命令。


### 7.3 C 部署回执与可信输入（管理工程冻结，2026-10-06）

TASK_ID=LAB-TASK-RUN-C-01；管理=019fe10b-df55-7b82-a9ba-3702dc08c55f。采用提案 SHA-256 `cde9efe36266a1b9c3ee3c40a9e35d3d33f87acef1e25cc205644d1cd13a6656` 第3–7节。以下是管理工程冻结，不是作者新增实际权限、部署或 R 接受。原提案保留不改。该次冻结新增准确 DeploymentReceipt；后续§7.4仅给Authorization增加input_control_bindings，TaskManifest/Profile/Plan/RunReceipt键集合仍不变。

#### 3. 准确 JSON 类型和摘要

沿用合同规范 JSON 字节、未知/重复键拒绝、无 BOM/尾换行、NaN/Infinity 拒绝。所有字段必填，明确标 null 的才可为 null。以下是闭合集合；没有任意字段扩展。

- H：64 位小写 SHA-256；S：非空 UTF-8 字符串；A：通过 A 包规则的本地 Windows 绝对路径，不接受宽根/reparse。
- Caps：原三键 bool 对象；Role/Boundary/Evidence：原合同枚举与记录。
- FileIdentity=`{path:A,sha256:H}`。
- ConfigIdentity=`{path:A,sha256:H|null}`；null hash **只表示该准确路径应不存在**，不是不核验。存在文件须普通单链接文件。
- Toolchain=`{ref:S,identity_files:list[FileIdentity],recipe_refs:list[S]}`；identity_files 非空。ref/recipe_refs 只指已登记事实与配套 recipe，既不含命令文本，也不提供执行自定义 recipe 的接口。
- Gate=`{id:"R-RUNTIME-01"|"WEB-01"|"DEPS-01"|"BOUNDARY-02"|"BOUNDARY-03"|"NETWORK-01",result:"Pass"|"Fail"|"Unrun"|"Unverified",evidence_refs:list[Evidence]}`。
- RuntimeAcceptance=`{role:Role,capabilities:Caps,execution_boundary:Boundary,receipt_binding_sha256:H,status:"Accepted"|"Blocked"|"Unverified",gates:list[Gate],management_acceptance_ref:Evidence}`。

DeploymentReceipt 准确字段：

| 字段 | 类型和约束 |
| --- | --- |
| contract_version | int=1，bool 不算 int |
| id | S；必须等于 DeploymentProfile.id 和 TaskManifest.deployment_profile_id |
| host | agy/cursor；等于 profile.host 和请求 host |
| adapter | agy_task_v1/cursor_task_v1；必须分别与 host 对应，代码固定映射，不接受其他 adapter |
| workspace_parent | A；可信管理批准的窄物理任务父根；task_root 必须是其普通直接子目录 |
| bridge | `{version:S,entry:FileIdentity,wheel_sha256:H,product_files:list[FileIdentity]}`；产品文件按 path 原 UTF-8 字节排序/唯一，必须包括实际使用的 task_run/launcher/capture/restore 实现；entry 是 Bridge entry，不是宿主 entry |
| host_entry | FileIdentity；agy 为登记 agy.exe，Cursor 为登记 agent.ps1；由对应固定 adapter 使用 |
| launch_shell | FileIdentity 或 null；agy=null；Cursor 为已验收且代码支持的 pwsh 路径/身份，不变成任意解释器入口 |
| host_version | S；已验收本机 CLI/后端版本事实，不从 entry hash 推断版本 |
| host_identity_files | 非空 list[FileIdentity]；管理从已验收本机部署确定的后端版本/实现标记；无法点时验证当前后端身份则 Blocked，不为查版本额外启动 CLI |
| configuration | `{agy_settings:ConfigIdentity|null,cursor_global:ConfigIdentity|null,cursor_project:FileIdentity|null}`；默认 agy 只前者非 null 且 hash 非 null；§17 原生项目模式三者必须 null；Cursor 后两者非 null，global 可声明准确路径应不存在；project.path 固定为 task_root/.cursor/cli.json |
| profile_fields_sha256 | H；对规范 DeploymentProfile 去掉且仅去掉 receipt_sha256 后的对象求 SHA |
| toolchains | list[Toolchain]；ref 唯一，按 ref UTF-8 字节排序；与 profile.toolchain_refs 一一对应；execute 或 prepare_dependencies 启用时不得为空 |
| runtime_acceptances | list[RuntimeAcceptance]；可空；role/capabilities/boundary 三元组唯一，不创建组合 profile |
| provenance_refs | list[Evidence]；引用原部署/launcher/安装/R 来源，不把历史材料改写成当前接受 |

数组 FileIdentity 按 path、recipe_refs/其余引用清单按原字符串 UTF-8 字节排序且唯一；gates 按 id 唯一；runtime_acceptances 按 role、Caps 三 bool 固定键顺序、boundary 排序。Evidence 沿用原记录，引用只作登记材料引用，不作为任意路径/URL 自动解析入口。接受所用 evidence 必须是 HostObserved 且 hash 非 null，管理必须在供给前核验引用；仅具备这些字段不自行产生 Pass。

Evidence 的唯一性按精确 ref 原字符串，不做大小写或 Unicode 形式折叠。每个输入清单自身乱序或重复 ref 均拒绝；Plan 合并多个有效来源清单时，同 ref 且完整 sha256/origin 声明相同才合并为一项，同 ref 不同声明拒绝，不选取优先来源。Plan 与 RunReceipt 输出引用均按 ref 原 UTF-8 字节排序且唯一。

消除摘要循环：

1. `profile_fields_sha256` 的投影不包含 profile.receipt_sha256；receipt 不包含完整 profile SHA。
2. `receipt_binding_sha256` 是对 DeploymentReceipt **去掉 runtime_acceptances 和 provenance_refs 两键**后的规范对象求 SHA。
3. 管理的 R applicability 接受记录绑定上述 digest 和准确 role/Caps/boundary。记录是在核对已有实测范围后出具，不是 C 按 hash 推断 R；当前配置或物理范围不能由旧 R 支持时，只填 Blocked/Unverified。参数化任务子根复用也必须由既有 R/接受材料明确支持，不能自动外推。
4. 填妥 runtime_acceptances 后，对完整 receipt 求 SHA，填入原 profile.receipt_sha256 和 authorization.receipt_sha256；task 的 profile/auth SHA 仍按原合同求值。
5. `trusted_inputs_sha256` 为规范对象 `{"deployment_receipt":receipt,"deployment_profile":profile,"authorization":authorization}` 的 SHA，由管理派工另行给出，不放进这三份文件自引用。

#### 4. 持久位置、信任与最小签名变更

可信管理输入根由当前明确派工给出，例如允许的任务 Archive 内专用 `trusted-input/<task_id>`；这只是位置建议，不是本轮创建真实授权材料。
其三个固定文件为 `deployment-receipt.json`、`deployment-profile.json`、`authorization.json`。Cursor 另可由管理放置固定 `cursor-project.json` 原生配置材料，其 raw SHA 必须等于 receipt.configuration.cursor_project.sha256；它不属于可自由扩展的第四合同对象。

根不得来自 Worker/源包/任务内容，不得在 snapshot、业务 worktree、task_root、run_root 或其后代内；禁止宽根与 reparse，三个文件逐项只读，不递归扫描。当前管理派工必须同时提供根和 trusted_inputs_sha256。D 不从文件内读取“我可信”的标志，也不读取完文件后自动计算 expected hash 来替代派工固定值。

调用方信任是明确的宿主边界：这一方案不鉴别任意同用户程序，也不阻止恶意宿主调用方伪装管理。Worker 没有供给这两个宿主参数的正常入口；declared_scope 不声称其 OS 进程绝对无法访问控制材料。同用户可达范围仍须实际授权；required_enforced 仍须 R 强制证据。若需要防御敌对宿主调用方，那是本次范围之外的新权限系统，不以本提案宣称已实现。

task 的固定绑定副本：原 `control/deployment-profile.json`、`control/authorization.json` 加新增 `control/deployment-receipt.json`；C 在首次 plan 排他保存 receipt 副本与 plan。已有同字节副本可只读复验；存在不同字节则拒绝，不覆盖旧计划或失败现场。它们都归 protected control，不是信任源。
Cursor `.cursor/cli.json` 是额外固定受保护 Host 文件：D/可信 Host 准备阶段仅将上述固定、管理已核验的配置材料复制至此，C 不开放任意原生权限文本参数；B 保留/回收其 frozen 身份。冲突文件不覆盖。未有相应 CONFIG-03/R 的映射只能 Blocked。run execute=False 不写或读取真实宿主配置。

冻结两个准确 keyword-only 签名：

```python
def plan_task(
    *,
    task_root: Path,
    host: Literal["agy", "cursor"],
    trusted_control_root: Path,
    trusted_inputs_sha256: str,
) -> dict[str, object]: ...


def run_task(
    *,
    task_root: Path,
    plan: dict[str, object],
    run_root: Path,
    trusted_control_root: Path,
    trusted_inputs_sha256: str,
    execute: bool = False,
) -> dict[str, object]: ...
```

以 root+派工 SHA 替代原 plan 的自由 dict 输入，并给 run 增加相同两参数。B prepare/collect 签名和所有原 JSON 键集合不变；D 从同一可信根把原 profile/auth 传给 B。旧 slice/Cursor API、退出码和配置恢复不变。

#### 5. plan → run 重读算法

1. **固定加载**：核对可信根及三固定文件普通链；严格解码、闭合 schema 与规范字节；重算 bundle SHA 与派工参数相等。只读取这些受管理提供的材料和 task/control，不调用真实宿主、读取 key 或真实宿主 settings。
2. **绑定验证**：task 的 profile/auth/instructions SHA、可信 profile/auth 与 task 副本、receipt id/host/profile 投影 SHA、两个 receipt_sha256 全部一致；task_root 在 receipt.workspace_parent 下。验证原角色/三能力/边界/roots/protected/输出/deadline 合同；原任务控制冲突保持拒绝。
3. **授权判断**：可信 authorization 是管理对实际已授权任务的准确记录。task_id/能力/边界/读写范围必须相符；web/deps 启用分别需管理提供的有效 scope 引用，依赖还要求 execute。C 不把 task 自带 grant_ref 或 receipt 自填字符串升级为授权，也不建立通用 scope 解释器。
4. **R 判断**：找唯一准确 role/Caps/boundary、binding digest 相符且 status=Accepted 的记录。所有任务要求 R-RUNTIME-01 Pass；web/deps 分别要求 WEB-01/DEPS-01 Pass；required_enforced 另需 BOUNDARY-02/03/NETWORK-01 Pass，且原 profile.file_scope/network_scope=Enforced。缺项返回 Blocked，允许 runtime_acceptances=[]；不得套旧 slice R、组合不同记录或降级边界。Ready 仅表示这些管理供给门禁满足，仍不等于业务接受或最终瞬时启动核验通过。
5. **固定计划**：route 只取 agy gemini-3.8-flash-high/high 或 Cursor grok-4.7-high/null。Plan 保持原字段；evidence_refs 引用供给来源/R 记录；在 control 排他保存 receipt/plan 绑定副本。
6. **run 重读**：每次 run 重新执行 1–4，从外部可信根取得当前固定内容，重算相同 Plan 并与参数及 control/plan.json 严格相等；核对 control/receipt 同字节同 SHA。不得仅验证 caller Plan schema 或使用内存 cache。任一 drift 拒绝，launch_count=0；不静默重 plan。
7. **未执行路径**：execute=False 返回原 RunReceipt 的 NotRun/0/null/NotRun/NotRun；不初始化 key/store，不触碰宿主配置或启动宿主。Blockers 如实保留；全新 run_root 保存元数据的行为保持原合同，不复用根。
8. **执行路径**：execute=True 且 Ready 才对 receipt 中明确的 Bridge/host/后端标记/toolchain 文件作普通链与当前 bytes/hash 身份复核，确认实际加载 Bridge 实现属于绑定产品。只读核对准确配置路径的存在/不存在及 hash、原生冲突和配置独占协调；task/control 紧前再核对。失败先于 key/config 写入/launch。复用现有 fixed adapter、原字节备份/漂移恢复、加密 capture 和进程树回收；最多 launch 一次，deadline 取原 task 值。transport/capture/restore 分列，失败产物保留，不产生业务 Completed。

底层、共享 launcher 和 C 显式传递同一份生命周期事实（not_attempted/confirmed/unknown、固定阶段、持有句柄所得 PID/创建 FILETIME、逐项清理观察）。原生 ResumeThread 调用前先标记 unknown；观测返回 1 后立即标记 confirmed，后续线程关闭、交接、捕获或中断不得降级。恢复前的确证失败记0；调用/结果转换/记录被中断记null，即使回收成功也不能据此推断未执行。launch.json 保留此事实，包括没有返回包装器的路径；未观测的清理结果为null，child_exit_observed只说明持有子进程的退出观察，不证明全部后代回收。原始中断在清理后继续传播，元数据不包含 argv/prompt/配置正文。新增原生失败阶段 thread_close_failed 仅说明自持线程句柄关闭失败。

消费者必须显式处理 launch_count=null，不得用真值判断将其当0，或接受为 Completed/成功。§7.4的B/C候选已补B消费与贯通离线测试，尚须新的独立Review；D和旧slice/Cursor回执兼容不在该候选接受范围，也不授权重试或恢复调度。

管理变更授权或 R 接受时，必须另给当前可信材料与派工摘要；旧 Plan 随绑定漂移拒绝。没有后台监听、自动过期或自动刷新机制。此入口不自行恢复真实运行授权。

#### 6. B/C/D 所有权与必要变更

| 所有者 | 必要最小变更 | 保持关系 |
| --- | --- | --- |
| 管理 | 冻结本 schema/签名/位置；供给实际授权、已有 R 适用性记录和外部根+bundle SHA；引用原部署材料 | Hash 不决定授权或审查质量；没有有效新 task R 可以合法 Blocked |
| B | 原 task/profile/auth 校验与副本不变；保护新增 receipt/plan control；Cursor 固定 .cursor/cli.json 加入 host 控制面完整性检查，不能让 Worker 改它 | prepare/collect 导出签名不变；不创建 registry，不拥有 launcher |
| C | DeploymentReceipt 严格验证、两次固定加载和 Plan 再生比较、R/身份/配置 gate；拥有 fixed adapter 与必要 slice_run/cursor_run 生命周期复用 | 可复用原 JSON/路径/restore/capture；不复制 A 路径逻辑，不依赖不存在 B 私有函数 |
| D | 将两个新增可信输入参数包装成明确 Host CLI 参数；prepare 从同根转交 profile/auth；Cursor 只准备固定配置文件；同步 usage/Skill/打包 | task 参数不新增 argv/model/URL/权限字符串；旧命令不扩权 |

冻结文档未来只需补 DeploymentReceipt 表、上述两个签名、固定 control/Cursor 控制面与 gate 规则；不必改原五种业务 JSON，不需要改变 H3/MCP 或 provider 平台。B 的 `.cursor` 保护处理是必要共享范围变更，须同批明确 allow-list，C 本轮不越界实现。

#### 7. 必要拒绝案例

| 案例 | 结果 |
| --- | --- |
| 根来自 task/work、宽根/reparse、非固定文件名、未知/重复键/NaN、bundle SHA 不符 | 拒绝可信输入；launch=0，不读真实 key/config |
| Worker 自填 grant_ref、授权文件或自算 hash；未从管理当前供给取得根+expected SHA | 不构成可信输入，不能 Ready |
| receipt 与 host/adapter/profile/task 根/三个引用 SHA 不符，任意 argv/model/URL 或未知字段 | 拒绝；不尝试其他 host/route |
| web/deps 无可信有效 scope、prepare_dependencies=true 但 execute=false、roots 超范围、Review 写 work | Blocked/合同拒绝，不启动 |
| 缺新 task R、旧 slice R、WorkerReported/hash=null、只 cwd/ACL/Job Object、required_enforced 缺强制项 | Blocked；不降级或伪称物理强制 |
| plan→run 材料漂移、项目控制冲突、launcher/后端标记/配置漂移或未知当前版本、配置锁竞争/deny 冲突 | 启动前拒绝；不覆盖现场，不更新输入重试 |
| capture 不完整、配置恢复失败/语义漂移、中断 | transport/capture/restore 原结果分别保留，不二次启动、不自动业务接受 |

离线测试只能由测试显式注入可信根、固定摘要、合成授权/R 与 fake 文件/launcher；这些测试证明合同分支，不证明实际宿主、权限或新 task R。


#### 管理澄清与首次验收边界

- prepare_dependencies 依赖 capabilities.execute=true；run_task(execute=False) 仍是合法 dry run，与能力 bool 独立。
- 首次新 task R 的受控实机验收路径尚未定义，留后续单独授权；不降低 production Ready、不用旧 slice/smoke R、不加旁路。fake Accepted 只证明分支。
- product_files/host_identity_files/toolchain 按准确文件与实际运行实现绑定；普通版本字符串不是当前运行证据，无法验证 Blocked，不额外启动宿主 CLI。
- C 首次创建/核验 control/deployment-receipt.json 与 plan.json，B prepare 不预先要求二者；副本排他创建或同字节复验，漂移不覆盖。
- Cursor 固定 .cursor/cli.json 由 D/可信 Host 准备后 C 核对，B 保护/收集身份但 prepare 签名不变；缺失/冲突 Blocked，协调只经管理。
- Cursor readonly 配置收尾核验覆盖正常返回、异常和中断；无法复核或漂移记 restore_state=Failed，不覆盖现场，原启动中断/异常不被收尾错误替换。
- 可信根/expected SHA 来自当前管理派工，不能从 Worker/task/源包选取；hash/HostObserved/任意宿主调用方不能创建授权。无签名/registry/ACL 平台；路径复用原语，点时检查不消除竞态。固定非敏感错误；元数据写入与实际 launch 分开。

#### C 与 B 候选的固定交接

C 启动前读取 B 保留的 `control/snapshot`，复用 A 的 `read_snapshot` 与树验证，核对 task 的 snapshot_id/manifest SHA、task 根 `SEALED` 和 work 原字节树；不导入 B 私有实现。plan→run 及配置写入前再次检查，漂移 launch=0。Coding 启动后的允许改动由 B collect 检查，C 不把它们当启动前完整性失败。write_roots 必须受 read_roots 覆盖，required_outputs 限于允许 out 路径且包含 out/progress.json；Cursor protected_paths 须预先覆盖 `.cursor` 或 `.cursor/cli.json`，固定目录只允许 cli.json。

RunReceipt.evidence_refs 只登记本次 run_root 下的 Host 元数据和加密会话引用；外部管理/R 来源留在受 plan_sha256 绑定的 Plan，不冒充运行目录文件。加密引用准确使用 `session:<capture_uid>`，其 SHA 是认证会话清单规范字节摘要，capture_uid 字段仍为原 UID。B 按不合法相对路径的 opaque 引用处理，不复制或解密会话。原 capture v2 不改；C 封存 metadata.input_sources 准确记录 task=`control/TASK.md`、request=`fixed_task_v1`。CLI 输出中的测试声明只加密保留，不自动生成 HostObserved TestObservation；没有可独立核验的 recipe/tree/toolchain/时序证据时 test_observations 为空，业务接受仍须后续裁决。

### 7.4 B/C 控制绑定与 nullable 回收（LAB-TASK-BC-INTEGRATION-01，2026-10-06）

管理冻结来源为 `CONTROL_BINDING_PROPOSAL.md`，SHA-256 `0588f335cf2a85d6aa52f4fc6587e8ffcaf59332ac1e2e51f83f7bae6db14a8b`；原提案与C交接证据保留不改。本候选从C `a182dd1c2b07c97486c97df1daafefdebd1c0aee`、共同A `c79a725c917b0a93aea0e19ccc14154087909bb1` 选择性引入B `8dae5112ad58f0c15da06d348346dc65ae3cdd80` 的workspace实现和测试。它是离线接口候选，未经新的独立Review，不表示真实R/部署/发行接受。

Authorization新增且仅新增必填 `input_control_bindings={task_fields_sha256:H,files:dict[P,H]}`。管理先填完TaskManifest的所有其他字段（包括完整deployment_profile_sha256和规则protected_paths），对仅排除authorization_sha256的规范任务对象求SHA，填入task_fields_sha256；再对完整Authorization求SHA填入task.authorization_sha256。Plan/Result仍绑定完整TaskManifest，三文件外部trusted bundle仍绑定完整Authorization，没有第四信任文件或新注册表。

files须精确覆盖保留快照中所有原生规则文件：末分量为AGENTS.md/GEMINI.md/CLAUDE.md/.cursorrules，包括嵌套。发现使用既有身份比较，授权成员始终使用原始Unicode和大小写名字，不以NFC/casefold别名替代；每个SHA对应原始文件字节，且work对应路径受protected_paths覆盖。管理已核对其规则与role/capabilities/boundary/profile一致的声明才可进入可信bundle；软件只校验结构、身份与字节，不解释规则自然语言，也不从TASK.md或源码内授权文本自行取得信任。缺绑定、未登记/额外/名称/原字节/任务投影/保护漂移以InputControlConflict拒绝；底层路径、JSON、seal错误保留其错误契约。

源包 `.cursor/cli.json`、`.gemini/settings.json`、`.claude/settings.json` 及其子路径仍拒绝，不能通过files字段豁免。task_root/.cursor/cli.json是独立的Host准备配置，由固定部署回执绑定并保护，不与work中的源配置混同。

C先核验外部可信bundle摘要、严格schema和control副本/任务身份，再调用B的公共verify_input_controls；plan、run重读及捕获准备后配置写入前均复用同一导出，漂移在启动前停止。C继续用A核对完整work树，并将实际使用的task_workspace实现纳入产品文件身份集合。公共导出错误在生命周期内也保留原code；与B prepare授权不兼容的输入可在Plan生成前硬拒绝，不伪造Blocked计划。

B明确校验launch_count为0/1/null（bool不是int）；null仅接受Failed且包含LaunchUnverified，Blocked计划只接受明确0。NotRun仍为0、Completed仍为1。有效未知回执、原测试声明、清理观察及opaque加密UID引用均保留；transport=Failed、continuation=null、management_decision=null。无效回执同样不给续接描述。collect规则漂移保留原始快照和当前候选字节，scope=Fail且continuation=null，不修复或自动继续。C的fake测试事件和WorkerReported、hash-null、opaque引用均不能提升为已核验测试。

上述B/C候选e75ba428未修改旧slice/Cursor整数回执；后续LAB-LEGACY-LAUNCH-RECEIPT-02在独立工作树收到工程冻结：新产生的旧adapter执行回执统一schema_version=2、launches=0/1/null，使用共享caller-owned生命周期、原顶层spawn_state词表及异常时原生命周期fallback结构；正常capture记录形状保持，异常/null非成功、原中断优先、无重试。preflight/plan仍v1，task的contract_version=1及加密session格式不变。历史v1回执绝不重写或虚构unknown；task collect严格拒绝旧schema_version v1/v2，不能跨合同读取。细节见BRIDGE_USAGE/CURSOR_USAGE；此旧adapter候选仍需独立Review，B/C审查不覆盖它，真实/外部消费者兼容与D另行推进。

本任务证据与保留清点入口：`C:/Users/user/Documents/Codex-Archive/2026-10-06-LAB-TASK-BC-INTEGRATION-01/INDEX.md`。归档包含修改前决策矩阵、冻结来源/原始Git blob、候选报告及各轮失败/通过验证引用；索引不替代事实真源或自动清理授权。

## 8. 有界复用核验与采用理由

以下是2026-10-04初稿的有界调研记录，本修订保留来源，不重复网页核验或执行探针。初稿无安装/clone/升级/上游调用，样例仅标准库内存/静态检查；不宣称新importer或权限行为通过。

| 候选/来源 | 许可证/维护/Windows | 采用决定 |
| --- | --- | --- |
| 现有 Bridge 通讯、winjob、恢复、加密回放 | 冻结现有产品；沿用已定许可/加密底座 | 直接复用，扩任务合同与 role/profile 验证；不重新研究既有 AGPL |
| [Python 3.13 zipfile](https://docs.python.org/3.13/library/zipfile.html)、[CPython 源码](https://github.com/python/cpython/tree/3.13/Lib/zipfile)、[Python license](https://docs.python.org/3.13/license.html) | PSF；目标运行时已有 stdlib；3.13 官方文档持续维护；Windows 路径另做校验 | 采用解析/解压/CRC 原语，补验证与限额；不复制整套 ZIP 解析器 |
| [pypa/installer](https://github.com/pypa/installer) | MIT，维护者项目；Python wheel 安装抽象支持跨平台脚本包装；本轮未做安装/Windows运行验收，最近维护时间未独立确认 | 不引入：用途是 wheel 安装，不提供任意源码包的冲突、role/profile、覆盖/续接合同，不能替代 importer |
| [Google Antigravity CLI 官方仓库](https://github.com/google-antigravity/antigravity-cli)、[官方 organization](https://github.com/Google-Antigravity) | 官方 issue/examples/changelog 仓库；organization 显示 2026-10-03 更新，README 有 Windows 安装路径；未发现可复用 CLI 引擎源码许可，沿用用户已安装产品条款 | 继续复用现有 agy 通讯，不引入 SDK/IDE 自动化；多步能力声明仍需本机验收 |
| [Cursor CLI](https://cursor.com/docs/cli/overview)、上述 parameters/permissions/configuration | 官方 Windows 入口；不是本项目可直接 vendoring 的开源完整引擎；当前机器版本证据与在线文档分开 | 复用现有 Cursor adapter；权限/隔离按 profile 验收，不重新搭 ACP/cloud worker 平台 |

结论：在已查范围内，没有可直接替换本地两宿主并满足上述输入/产物/权限证据合同的成品。选择标准解析器与当前 adapter 的小幅扩展，而不是开发新 Agent 编排平台。此结论限这些候选，不是“所有成品都不存在”。

## 9. 文档、Skill 与权限决策的落地要求

日常Skill定位须“读本机部署回执→核对绝对entry/版本/wheel SHA/产品摘要→再查PATH”，引用日期/来源，不把单机路径当通用入口。初稿部署记录示例entry为 `C:\Dev\ask-ai-mcp\runtime\local-agent-bridge\0.1.0.dev0-5c60e9af\.venv\Scripts\local-agent-bridge.exe`，依据为 `C:\Users\user\Documents\Codex-Archive\2026-10-03-LAB-BRIDGE-PARALLEL-DEPLOY-01\RUNTIME_VERIFICATION.json`；本修订未运行上游CLI，D/实际运行须读届时回执，不从示例推定部署仍一致。

Skill 必补固定路由：`agy run: gemini-3.8-flash-high / effort high；Cursor: grok-4.7-high，非 Fast。task v1 用冻结的角色/能力/边界和已验收部署回执；declared_scope仍须实际授权与本机运行证据。旧slice v1只改既有文件、不运行测试。` 此为D包修改要求，本轮不改已安装Skill、不把未来能力写成当前事实。

必要 AGENTS 短变更建议（在 task v1 实现、独立 Review 与相应能力验收后替换旧“切片桥只能小切片”描述，禁止本轮提前应用）：

```text
工程 task v1 只处理冻结快照的专用副本；Coding 可在授权 work 根增删改重命名、测试构建与同次调试，Review 只读 source 并写 out/scratch。
使用冻结角色/能力/边界与登记部署profile；declared_scope不声称强制隔离，required_enforced须对应本机证据；真实运行须有效实际授权。
一次宿主调用可包含正常多轮工具执行；新真实调用/恢复会话/换模型仍需相应授权，失败不自动重新提交。
原始 source、控制配置、凭据、业务树与远端不因任务权限扩大而可写；产物须收集并独立核验后集成。
旧 slice v1 和 H3 MCP 保持各自入口；不开放 generic prompt forwarding、任意 argv/model/URL 或无限委派。
```

可直接工程决定：上述新旧协议分离、bytes 快照、固定资源初值、角色目录、增删变化清单、业务状态/覆盖、续接引用、现有底座复用、离线 fixtures 与分包所有权。这些不需要额外作者玩法决定。

确需作者权限：新真实模型/上游调用、部署或宿主全局设置改变、未核验的 shell 范围风险接受、新 VM/容器/受限账户与工具安装、新域名/联网依赖或安装脚本范围、预算/账户扩展、游戏包使用和远端发布。现有会话明确授权的项继续有效，不逐阶段重新确认；缺少授权只阻断依赖该项的运行，不阻止其余离线实现。所有待决项标 `ProposedRecommended/authorConfirmed=false`，不在本阶段创建审批等待、轮询或监控。

## 11. Task CLI v1 候选（LAB-TASK-CLI-IMPLEMENT-01）

冻结提案：LAB-TASK-CLI-CONTRACT-01，SHA-256 `e5b484ba27b97ca299442ee5e4e7fd82e4e6f5309328f6dc5eae1fa7be665847`。
本阶段只包装已有 A/B/C API；原八条命令及旧 adapter 回执 v2 保持原含义。新增命令如下：

```text
local-agent-bridge task import  --spec <absolute path>
local-agent-bridge task prepare --spec <absolute path> --trusted-control-root <absolute root> --trusted-inputs-sha256 <64 lowercase hex>
local-agent-bridge task plan    --spec <absolute path> --trusted-control-root <absolute root> --trusted-inputs-sha256 <64 lowercase hex>
local-agent-bridge task run     --spec <absolute path> --trusted-control-root <absolute root> --trusted-inputs-sha256 <64 lowercase hex> [--execute]
local-agent-bridge task collect --spec <absolute path>
```

每条 spec 的 `cli_contract_version` 为整数 1，并且必须且只能包含下表字段。所有路径为未经 trim、环境展开或 dot/parent 折叠的绝对路径字符串；只有 collect.run_root 可显式为 null。

| 命令 | 其余必填字段 |
| --- | --- |
| import | source、policy、snapshot_root |
| prepare | snapshot_root、task_manifest_path、task_note_path、task_root |
| plan | task_root、host（agy 或 cursor） |
| run | task_root、run_root |
| collect | task_root、run_root、result_root |

spec 是严格 UTF-8、无 BOM 的单个 JSON 文档；允许 JSON 空白，拒绝重复/未知键、非有限数、溢出和错误类型。
重复 CLI 选项、长选项缩写、额外位置参数、stdin/`-` 和任意模型/argv/URL/宿主配置参数均拒绝。`task --help` 与五条子命令的独立 `--help` 返回 0，不读输入或访问服务。

source/policy 原样交给 A：Git 须精确 40 位提交与文件列表；ZIP 须明确摘要和 strip_prefix（可为 null）；目录须清单文件和明确摘要。policy 的 source_paths、excluded_paths、sensitive_paths、trusted_control_files 四项必填，原九项数值上限及缺省值保持。A 的目录清单读取复用既有 package_bytes_limit：先 stat 拒超限，再实际读取至多 limit+1 字节并在超出时同样拒绝，声明摘要比对与严格 JSON 解码只发生在这些有界字节上；声明 entries 列表在逐条解析前先过 entry_count_limit 门禁。不新增 policy 键或公共 schema；有界读取约束原始字节与条目迭代，不宣称 JSON 解码的绝对内存上限。task_manifest_path 严格 JSON 解码后由 B 校验原业务 schema；task_note_path 按原字节交给 B，保留 BOM、CRLF 和末尾换行状态。

C 公开 `checked_host_path`、`read_host_input_bytes`、`load_trusted_inputs`、`prepare_cursor_project`。固定 64 MiB 的 Host 文件读取检查读取前大小、实际读取长度、普通单链接文件身份及读取前后稳定性；不增加可配置上限。读取句柄保持打开，完成最终路径检查后再查询同一句柄，作为本次最终变化观察点；opened/after/final 的 fstat ctime 相互比较，path-before/path-current 的 stat ctime 相互比较，其余身份信息跨查询核对。固定有限观察覆盖读后句柄查询至最终路径检查期间的变化；不重读或循环重试，不保证最后一次句柄观察之后的文件不可变，既有路径链点时检查限制保持。
共享加载只从可信根读取 deployment-receipt.json、deployment-profile.json、authorization.json 三个 canonical JSON；bundle 与管理另外供给的摘要相等才继续。共享 receipt/profile/auth 绑定校验复用 C，完整 input_control_bindings 和 task/规则语义继续由 B 校验。尚未创建的 task_root 可以加载可信材料，但不得据此创建任务或读取 task.json。已知 task/snapshot/run/product 根与可信根不能相交；管理仍须供给业务及来源根以外的可信根，CLI 不扫描整机发现其他根。

plan/run 的 C 入口和紧前复核继续重读可信材料、B 输入控制与原 work 树；不缓存接受、自动重 plan 或修复输入。运行身份的必需文件增加实际 cli.py 和 task_cli.py，旧 receipt 缺少它们会 Blocked，不能删减必需集合兼容旧证据。

Cursor 仅在 task plan 前由 C 准备固定 task_root/.cursor/cli.json：原字节来自 trusted-control-root/cursor-project.json，摘要绑定于 receipt.configuration.cursor_project.sha256。这是固定原生模板，不是第四个通用合同对象。校验原 permissions.allow/deny 字符串数组 schema，不生成或合并权限；task/B 控制、原始 work、准确目标及保护范围均先核对。缺目录排他创建；已有目录只能包含普通单链接 cli.json，且必须同字节，只读复验。冲突、额外文件、链接、模板缺失或不符均拒绝。run 不准备配置，不读写全局配置来补救；未通过 R 仍 Blocked。

Cursor 文件准备与原 C receipt/plan 持久化不是原子事务。普通持久化异常返回 2，原中断返回 130，保留先前写入和失败现场，不删除、覆盖、回滚或自动重做。存在 deployment-receipt 但缺 plan，或存在 Cursor 准备材料而计划不完整，B collect 必须报告 ControlChanged，并将 scope_status=Fail、continuation=null；agy 与 Cursor 一致。纯 prepare 无 receipt/plan/Cursor 材料保持合法；完整计划仍按原 schema/摘要/保护范围核验。

stdout 保持原 SnapshotManifest、TaskManifest、Plan、RunReceipt 或 ResultManifest 的单个 canonical UTF-8 JSON 对象，并增加一个传输 LF；落盘 canonical JSON 不带该 LF，文件摘要不包含传输换行。异常 stdout 为空，stderr 仅固定 `local-agent-bridge task: <stable-code>`，不输出路径、输入、异常正文或 traceback。

| 结果 | 进程退出码 |
| --- | --- |
| help、成功 import/prepare | 0 |
| plan Ready / Blocked（均输出原 Plan） | 0 / 2 |
| Ready dry run，NotRun/0 且无 blockers | 0 |
| 已执行 Completed/1、capture Sealed、restore Unchanged 或 Restored，且无 blockers | 0 |
| run blockers、Failed、TimedOut、launch_count=null、capture/restore 失败 | 2 |
| collect 无 blockers 且 scope_status 不是 Fail / 其余收集结果（均输出原 Result） | 0 / 2 |
| 参数、schema、路径、摘要、I/O 等异常 | 2 |
| 原 KeyboardInterrupt 经原 C 收尾并传播 | 130 |

CLI 退出 0 不接受 Worker 业务结果；collect 的 worker_status 不决定进程退出码，management_decision 仍为 null。
Caps.execute 是 Worker 测试/命令能力，`--execute` 是宿主是否启动：静态 Review 可在 Caps.execute=false 且适用真实 R 下启动；prepare_dependencies=true 仍要求 Caps.execute=true；默认 dry run 即使 Caps.execute=true 也不启动。

本候选的 synthetic Accepted/fake launch 只证明离线分支。首次真实 Task R/bootstrap、真实 agy/Cursor、独立 Review 和部署分别待验；无 Skill、H3/MCP、A 或真实配置变更。LAB-TASK-CLI-REPAIR-01 按管理扩大的范围，仅调整 B 对不完整计划的观察，不变更 Result schema。

### 首次 Task R 独立验证程序 v1（LAB-FIRST-TASK-R-IMPLEMENT-01）

`verification/first_task_r.py` 是 sdist 中的可信管理验证材料，不进入 wheel、不注册 CLI/MCP、不修改 src 或普通 run/R 门禁。实现和 fake 自检不是实际执行批准，真实方案仍 ProposedRecommended/authorConfirmed=false。程序只验证 agy/Coding/Caps={execute:true,web_reference:false,prepare_dependencies:false}/declared_scope；不实现第二 host、R-a 实机探针、解密、部署或接受裁决。

管理在验收单外供给其绝对路径与 expected raw SHA；源文件/Worker 不供给信任。验收单为严格 JSON 对象，未知/重复键、错误类型、bool冒充int、hash/路径漂移拒绝。只有审批字段 Approved/true、全部明确权限 true、预算证据非空且 hash 非 null 才可消费；字段仅记录可信管理批准，不能鉴别任意同用户伪造调用方或证明费用未超限。

| 闭合字段 | 精确语义 |
| --- | --- |
| contract_version；kind | int=1；TaskRuntimeValidationPermit |
| permit_id；task_id；management_task_id | permit_id为1–64位ASCII字母数字/下划线/连字符；task_id绑定Task/Auth；management_task_id固定019fe10b-df55-7b82-a9ba-3702dc08c55f |
| approval；grant_ref；budget_ref；max_host_launches | approval={status:Proposed/Approved,author_confirmed:bool}；grant_ref等于可信Auth.grant_ref；budget_ref为一个HostObserved且hash非null的Evidence（管理预先核实，程序不自动解析ref）；max_host_launches严格int=1，限制一次生命周期调用，不证明provider请求数或费用 |
| host；role；capabilities；execution_boundary | 精确agy/Coding/上述三bool/declared_scope；Task/Auth/Profile均不得提供其他角色/能力/边界 |
| task_root；trusted_control_root；run_root；result_root | 普通窄绝对根；可信根及其SHA沿用原三文件bundle；run/result必须不存在且父目录已存在；相互、安装根、capture根不重叠；不得覆盖旧产物 |
| task_manifest_sha256；plan_sha256；trusted_inputs_sha256；receipt_binding_sha256；deadline_seconds | 前三者绑定规范task/Plan/bundle；R binding仅排除receipt.runtime_acceptances/provenance_refs；deadline为1–3600秒并准确等于Task值；专用首单R仍保持既定host/role范围 |
| validator；installation | validator为本程序自身FileIdentity；installation={root:A,python:FileIdentity,wheel:FileIdentity}，root必须是当前sys.prefix，python是当前sys.executable；非editable安装、实际产品路径及全部wheel包内payload原字节核验，不能使用源码editable运行环境 |
| environment | FileIdentity指向严格对象{contract_version:1,kind:TaskRuntimeValidationEnvironment,local_appdata:A,worker_shell:FileIdentity}；其raw SHA/路径必须在profile.enforcement.evidence_refs以HostObserved登记。Worker Shell这里只是冻结预期身份，实际使用仍需实机独立取证 |
| recipes | 恰好一项{ref:first_task_r_unittest_v1,identity:FileIdentity}；绑定receipt唯一Python工具链recipe_refs，文件在work内并受protected_paths保护；程序只核字节，不执行任意recipe/argv |
| permissions | 严格六bool对象：synthetic_copies、same_user_declared_scope、configuration_lease、owned_job_termination、capture_key_read、isolated_capture_write，全部true才可消费；其他权限没有入口 |

先核验许可、程序/安装、路径、环境绑定、完整Task/Profile/Auth/快照/规则/控制与唯一缺R，再排他创建 `run_root.parent/<permit_id>.consumed.json`。存在或写入失败即拒绝；失败标记、部分run/state/result均保留，不删除或自动重用。初始静态核验失败不读key/配置、不消费；消费后才核原配置及复验。C的Blocked分支会跳过实现身份核验，程序每次必须显式核 `_verify_runtime_identity`、安装/recipe/环境和全部非R门禁，不能只凭blocker字符串放行。

真实receipt.runtime_acceptances必须为空，Plan原样Blocked且唯一blocker为RuntimeAcceptanceUnverified。严格recheck重复外部permit raw SHA、自身身份、冻结bundle/Task/Plan/receipt副本、根、实现/环境/工具链/recipe和配置核验；复用安装C的 `_load_inputs`、`_execute_once`、真实launch/capture/restore/Job，不猴补实际检查，不制造Ready/Accepted或删原R blocker。仅程序本进程临时使用全新LOCALAPPDATA，C创建自己的新capture域，agy继承该环境；finally恢复调用进程环境，不改用户/机器环境。此环境兼容性及真实认证未验。

独立 `validation.json` 标明kind=TaskRuntimeValidation、普通Plan=Blocked、R=Unverified、management_decision=null；状态仅ObservationRecorded/Failed/Interrupted。C run.json与B result完整保留，其Completed/Pass不提升为R或业务接受。生命周期只调用一次；launch_count=0/1/null来自C事实，无回执的执行异常保守记null；中断尽力保存观测后传播原异常，不用次生写入/collect异常替换。前置拒绝仅返回固定非敏感错误，可信调用方保留自己的失败回执。程序不解密、不判断命令业务质量、不产出Accepted；后续R-a/R-b及独立核验、管理接受另行授权。

B的普通run回执规则明确拒绝Blocked Plan且launch_count非0，本程序不改变该规则。独立验证只用既有 `collect_task(run_root=None)` 回收候选，仍核完整receipt/plan控制、范围和必需产物；B.transport=NotRun、acceptance=Unrun、management_decision=null。validation.collection_mode=ArtifactsOnlyNullRun，C生命周期run.json/hash单独保存，不能把它交B当作已接受的普通run。ObservationRecorded还要求生命周期完整、B.scope=Pass及outputs=Pass；它不表示普通run贯通或R通过。此数据分离是离线候选协议，真实路径仍待独立Review和作者批准。

### 首次验证落盘证据修复候选（LAB-FIRST-TASK-R-REPAIR-01）

45a22cf因缺失固定run.json仍ObservationRecorded被独立P1拒绝，本修复自检不撤销该裁定、不接受null-run协议。无论C返回dict或None，均经C既有有界、普通单链接、保持句柄到最终身份观察的读取重读固定run.json，核strict JSON/canonical、冻结task/plan与返回对象严格一致。run_receipt_sha256只来自已核验的raw文件，最终复核或关联失败时保守置null；collection_sha256同样来自实际result.json，不能用内存对象摘要冒充落盘。

run中的HostObserved与test_observations中的引用逐项核验，包括同名重复引用。只准读run根固定launch.json/config-restore.json/lifecycle-failure.json；未知或绝对/穿越ref拒绝，不按ref值任意读盘。启动声明核LaunchLifecycle计数与spawn状态、Completed/TimedOut及清理事实；恢复声明核原配置摘要、状态、实际恢复文件及专用original/patched备份。必要launch/restore声明或文件缺失、hash不符、事实矛盾均阻断ObservationRecorded。

session:UID仅核声明与同run.capture_uid相等，run_evidence_checks标记OpaqueDeclarationOnly。它不证明密文/manifest存在、seal内容或真实host/命令实测，不从opaque hash推断成功；不读历史会话、不新增key读取或解密。WorkerReported保持未验证。launch_count与证据完成度分开：可信C返回或合法固定回执保留0/1/null；原中断且run缺失时可从固定launch文件保留一致的计数事实，但这不成为同Task/Plan的已核验run，缺口仍失败/中断且hash=null，无计数证据保守null。

回收后重读固定B result/artifacts/changes规范文件，核与实际返回对象、task/snapshot/manifest绑定一致；复用B inventory、路径、生成目录与树摘要函数核实际文件集合、原字节长度/hash、candidate树、continuation摘要、host复制的原Plan/receipt及同Task当前work/out/scratch。最终复验许可、外部可信bundle、控制/规则、protected recipe和环境身份，不把Worker合法修改的业务源码重新当初始快照拒绝；最终再次重读run与每项local证据，回收期间漂移也不能完整观测。保存原launch事实、原中断和失败现场，不重试、覆盖或清理。

仍只五文件离线Repair。普通B的Blocked+launch拒绝、普通run/R门禁、src、发行配置及入口不变；真实R为Unverified、真实方案ProposedRecommended/authorConfirmed=false。重新独立Review必须裁定这些落盘及关联门禁和协议模式，自检不是接受。

### 启动事实来源修复候选（LAB-FIRST-TASK-R-REPAIR-02）

首轮修复因错误task/plan的saved run零计数覆盖已发生的一次启动，再被独立Review-02以P1拒绝。本轮为同缺陷链第2且最后自动Repair，尚待fresh Review，不能据自检接受协议或真实R。

本调用可信C返回的明确0/1优先；返回缺失、畸形或null时才采用磁盘事实。固定run须先经过version/task/plan及基本生命周期校验；固定launch.json须经规范、有界读取且spawn_state/launch_count自洽。两者任一明确记录启动1就保留1，不以相反零或附属证据缺口抹去已确认启动；没有1时保留已核来源的明确0，无法确认则null。未经校验的saved run不贡献0/1，错误/缺失本身不能证明0。未调用C的前置失败仍保留程序自身已知的0。

基本run校验与附属证据完整性分开：严格计数类型、transport/capture/restore、capture_uid、NotRun/Completed/TimedOut和LaunchUnverified关系先核，再逐项核引用与收集。run本体有效且明确已启动，即使launch引用/文件或其他附属证据缺失，仍保留1并报告Failed/Interrupted。错绑定、错误状态或畸形run不能贡献0/1；与固定launch矛盾由既有完整证据检查拒绝。可信C的明确返回不能被相反磁盘摘要覆盖。

来源选择不是证据接受。无效run的hash仍null，原KeyboardInterrupt对象优先于所有次生错误，consumed标记和原字节保留；没有重试、恢复或新生产B/C门禁。

### 完整目录映射修复候选（LAB-FIRST-TASK-R-REPAIR-03）

作者额外批准这次窄修复及独立离线审查，不重置自动两轮界限。Review-03发现收集后out空目录与保存副本不同仍完整观测；本候选自检不能撤销P1或接受真实R。

保存并核B inventory的完整目录集合，不只核文件及candidate摘要。当前work目录沿用B的generated分类：authored映射candidate/<relative>，新生成缓存映射generated/work/<relative>；out/scratch分别同名映射。合法收集前空目录、嵌套目录和通用build源目录继续保留；冻结源中的缓存名仍按B原规则处理。

result目录必须精确等于上述当前源目录映射、B固定生成的candidate/out/scratch三个根，以及映射和已核artifact文件所需的祖先目录（含host/control、validation等）。收集后任一复制域新增、缺失、改名/错映射，或result多出无声明空目录、缺少必要生成目录，均拒绝完整观测。文件/长度/hash、candidate与continuation及最终控制核验继续；目录关联失败使collection/run完整hash保守null，不抹去0/1/null启动事实或原中断。该检查是有限阶段观察，不保证观察后的树不变。

### 首次观测合同 v2（LAB-FIRST-R-OBSERVATION-CONTRACT-01）

本节新增闭合的首次观测材料，沿用原 A/B/C 操作和独立验证通道。旧 DeploymentReceipt v1、Permit v1 和 Environment v1 保持原样：v1 的 `host_identity_files` 仍非空，预期 `worker_shell` 仍是必须核验的 FileIdentity。不能给旧 v1 填 Unknown 或静默改为空清单。

| 对象 | v2 精确差异与适用范围 |
| --- | --- |
| DeploymentReceipt | `contract_version` 严格 int=2；原 v1 全部键外恰好新增 `host_composition`，值为严格对象 `{status:"Unknown",scope:"FirstObservation"}`；仅 `host=agy`，`host_identity_files=[]` 和 `runtime_acceptances=[]` 必须为空 list，其余原字段/类型/摘要规则不变 |
| TaskRuntimeValidationPermit | 原闭合字段不变，`contract_version` 严格 int=2；必须绑定 Receipt v2 与 Environment v2；v1/v2 交叉不允许。审批、权限、预算、一次消费及外部 raw SHA 沿用原规则 |
| TaskRuntimeValidationEnvironment | 严格五键 `{contract_version:2,kind:"TaskRuntimeValidationEnvironment",local_appdata:A,scope:"FirstObservation",worker_shell:ExpectedShell}`；其原字节身份仍登记在 profile 的 HostObserved 引用中 |
| ExpectedShell | 严格两键 `{status:"Known"|"Unknown",identity:FileIdentity|null}`；Known 必须给实际普通单链接文件并核 SHA；Unknown 必须 identity=null，仅该 v2 首次环境允许。路径未知不能用候选/占位身份填充 |
| TaskRuntimeValidation | `contract_version=2`，保留原观察字段；新增 `host_composition` 为上述 Unknown 对象、`expected_worker_shell` 为冻结 ExpectedShell、`actual_worker_shell={status:"Unknown",identity:null}`、`command_evidence_status="Unverified"`、`acceptance_requirements=["ActualWorkerShellIdentity","RecipeCommandCompletionEvidence"]` |

这里的空清单明确表示尚未建立本地实现组成映射；已知入口由 `host_entry` 单独绑定并继续核真实文件，不能重复登记 exe 来假装完整组成。v2 不接受非空实现清单、占位 backend 或接受记录；已取得组成的原 v1 材料不因本节被削弱。未知/重复键、非上述版本、bool 冒充 int、伪格式和错误 scope 均拒绝。其他 Task/Profile/Auth/Plan/RunReceipt 与 CLI spec 仍为 v1。

共享加载器可读取管理固定的 v2 材料，现有 `prepare/plan` 不新增参数。普通 Plan 始终为 Blocked，至少包含 `HostCompositionUnverified` 和 `RuntimeAcceptanceUnverified`；普通 `run` 即使 `--execute` 也只能保存 NotRun/launch_count=0，不读配置/key、不进执行生命周期。伪造 Ready 或补 Accepted 不能解除该状态。v2 不是普通生产 R 接受格式，不能将这次观察直接升级成可复用 R。

独立验证程序仅在另外批准的 v2 验收单下要求准确的上述两个 blocker；其他非 R 门禁仍必须通过。初始、消费前与结束重读继续核原 bundle/raw SHA、环境、入口/安装/toolchain/recipe、全部控制和实际文件；Known 预期 Shell 仍逐次核验。许可消费、配置恢复、0/1/null 启动事实、原中断及 B 文件和完整目录关联语义不变，不重新实现执行通道。

预期 Shell 字段不传入 agy、不选择或约束实际 Shell。v2 的 ObservationRecorded 只表示生命周期和候选回收证据完整保存，实际组成/Shell/命令证据仍如上述未证字段声明，R 始终 Unverified、management_decision=null。实际 Worker Shell 路径/文件身份，以及固定 recipe 的完整 argv、cwd、完成与退出事实，必须由另行获准的真实证据在管理接受前取得；程序不解密，不承诺现有捕获必然提供它们。缺证不能从 Unknown、stdout 终态、预期文件或自检推导接受。本合同候选仍需独立 Review 和新的适用实测授权，旧真实许可及自动修复上限不重置。


## 15. 普通可信 Coding 分层接受 v1（LAB-AGY-LAYERED-ACCEPTANCE-IMPL-01）

作者已选择 B。本节增加独立接受方式，不追溯改写 §14 首次观察 v2、§13 严格 R 或任何历史 Unverified。实现仍是离线候选，独立 Review、适用实机验证及部署须另行完成；本轮不为真实 runtime 生成接受记录。

| 对象 | 精确新规则 |
| --- | --- |
| DeploymentReceipt v3 | 严格 int=3；v1 字段外恰好新增 `host_composition`、`acceptance_method`、`layered_acceptances`；仅 agy。method 固定 `trusted_coding_v1`，composition 恰为 `{status:"Unknown",scope:"FixedEntryKnown"}`。固定 host_entry/host_version、bridge 和 toolchain 身份仍必须完整；host_identity_files=[]、runtime_acceptances=[]。不将相同 exe 再登记为组成，也不把版本字符串当全部后端身份 |
| Profile/Auth/Task | 仍为闭合 v1，不增加权限缺省。profile/auth 完整 receipt_sha256 绑定包含方式/层记录的 v3 原对象；原 profile_fields_sha256、授权 input_control_bindings、控制文件/范围/受保护文件检查照旧 |
| Plan v2 | 原 Plan v1 键外恰好新增 acceptance_method=`trusted_coding_v1`；只由 Receipt v3 分支生成。旧 Receipt v1/v2 继续生成 Plan v1。CLI spec 与五条 task 命令不变 |
| 外层 RunReceipt / collector | 保持 v1 生命周期和 test_observations 语义，以完整新 Plan SHA 绑定。collector 仅兼容加载 Plan v2，仍 management_decision=null；其 acceptance_observations 不被自动写 Accepted |

v3 只允许 Coding、capabilities 恰为 execute=true/web_reference=false/prepare_dependencies=false、declared_scope。新方式不接受 Review、联网依赖、Web、required_enforced 或隐式权限扩张。既有路径/实际文件身份、配置租约与恢复、有界 owned Job 回收、capture/key 门禁仍在原执行路径；新方式不重写它们。

layered_acceptances 每条恰为：`role,capabilities,execution_boundary,receipt_binding_sha256,task_scope_sha256,status,evaluation,management_acceptance_ref`。status 枚举 Accepted/Blocked/Unverified。仅 Accepted 且 evaluation=Eligible、管理引用是非空 SHA 的 HostObserved 才可解除 LayeredAcceptanceUnverified；其他授权/身份门禁仍须通过。匹配角色/全部能力/边界以及精确 task_scope_sha256，不能仅按 execute=true 推广。

receipt_binding_sha256 是规范 JSON receipt 去掉 runtime_acceptances/layered_acceptances/provenance_refs 的 SHA；task_scope_sha256 是完整规范 task 去掉 deployment_profile_sha256/authorization_sha256 的 SHA。只剔除循环绑定，task_id/snapshot/说明/路径/保护/outputs/acceptance_ids/预算仍都参与。不同 task、源码快照、说明、CRUD/rename/多文件或期限范围必须重新明确接受，不能复用单行修复的记录。记录按 scope SHA 唯一排序。

### 离线评价与管理裁决

产品模块 `local_agent_bridge.bridge.layered_acceptance.evaluate_delivery` 为无 IO 的固定对象接口，无新 CLI/MCP/任意命令入口。输入 task、Receipt v3、管理冻结的 candidate_tree_sha256、recipes，以及 collection/manager_retest/host_lifecycle/可选 worker_execution/worker_recipe。每项证据恰为 `{value,evidence_ref}`，ref 恰为 `{ref,sha256,origin}`，SHA 必须等于 value 的规范 JSON。输入由可信管理固定；hash 与来源标签不验证任意调用方的权限，也无抗同用户伪造保证。不读 XML、原 stream、秘密或旧 capture。

recipes 恰为 recipe_sha256/toolchain_sha256/executable_identity/argv/cwd；toolchain SHA 是对应登记 toolchain 的规范 JSON SHA，exe identity 必须在其 identity_files，argv[0] 是该 exe。可选 worker_recipe 使用相同闭合形状，独立冻结 Worker 的实际预期 argv/cwd，不把管理复测目录当 Worker 目录；缺该绑定时 Worker 层保持 Unknown。recipe SHA、完整 argv/cwd 由管理独立冻结，不接受 Worker 临时声明为预期值。retest 的源码树必须是实际 collector 交付 candidate_tree，不能先修补后接受。

| 层 | 对应输入及通过条件 | 未知/声明边界 |
| --- | --- | --- |
| code_delivery | 原 collector 的闭合 v1 对象；HostObserved，task/snapshot/candidate/完整 artifact_manifest 绑定，scope/outputs Pass、Completed、无 blocker/remaining_paths | 仅接受交付与范围，不证明 Worker OS 操作或完整 CRUD；collection 的历史业务状态不改 |
| manager_retest | actor=ManagementIndependent；task/source/recipe/toolchain/exe/完整 argv/cwd 匹配；有时区 start/end 且完成时间不倒序、exit=0、tests>0、failures/errors=0、HostObserved | 单独 XML、Worker 自述、错误原始候选树、缺证或错绑定不能通过；必须是管理实际保存的独立命令事实 |
| worker_execution | Unknown，或 WorkerReported/CliDeclared 的声明；可选完整 HostObserved 命令事实 actor=Worker，并提供实际 worker_shell_identity | 声明层 result 固定 Unknown。HostObserved 也只证明该固定命令；管理执行不得填 actor=Worker，预期 Shell 不得冒充实际 Shell |
| host_lifecycle | HostObserved；task/Plan SHA/新 capture UID 与 collection continuation 绑定，Completed、launch=1、exit=0、Sealed、Unchanged/Restored、owned_process_cleanup=Pass、无 blocker | 外层成功与 Worker 业务执行分开；失败或未确认回收不被代码/复测通过覆盖。正常关闭不证明真实强制超时能力 |

命令事实闭合字段为 actor/task_id/source_tree_sha256/recipe_sha256/toolchain_sha256/executable_identity/worker_shell_identity/argv/cwd/start_utc/end_utc/exit_code/tests/failures/errors。管理事实的 worker_shell_identity=null；实际 Worker 事实须给身份。外层事实闭合字段为 task_id/plan_sha256/transport_state/launch_count/capture_uid/capture_state/restore_state/owned_process_cleanup/exit_code/blockers。

evaluation 恰为 contract_version=1、acceptance_method、receipt_binding_sha256、task_scope_sha256、candidate_tree_sha256、layers、status、strict_r_status。layers 恰含 code_delivery/manager_retest/worker_execution/host_lifecycle；每层恰为 result/origin/evidence_refs。result=Pass/Fail/Unknown，origin=HostObserved/Unknown，Worker 层另可 WorkerReported/CliDeclared。strict_r_status 永远 Unverified。

评价器只返回 Eligible/Blocked/Unverified：三个必需层 code_delivery/manager_retest/host_lifecycle 都有 HostObserved Pass 才 Eligible；任一必需层 Fail 则 Blocked，缺证为 Unverified。Worker 层独立，不以管理复测提升。Eligible 不是 Accepted。管理核验原材料后，才能在**新**部署回执的 layered_acceptances 中明确冻结 Accepted + management_acceptance_ref，并重新绑定 profile/auth/任务和 trusted bundle。不得在已准备的冻结控制树里改 receipt 或 Plan；新接受材料须准备新的专用 task 副本。

普通生产路径仍为既有 `task prepare → task plan → task run → task collect`。普通 Plan 不自动取旧观察为接受证据；没有精确新记录时为 LayeredAcceptanceUnverified，范围不支持时另 LayeredScopeUnverified。standalone first_task_r v1/v2 不升级为 v3；§16 单独定义 v3 首次证据生产候选，实际许可仍须另冻。历史 R Unverified、旧退出码、旧消费 marker 和一次密文机会不变。

## 16. 显式单次 v3 首次证据生产（LAB-AGY-LAYERED-FIRST-RUN-REPAIR-01）

本节只补作者已选 B 的首次交付证据入口。实现自检、独立 Review、真实执行与管理 Accepted 分别裁决；没有实测许可时不得执行。普通 `task run --execute` 不接受首次许可参数，缺接受仍 NotRun/0。v1/v2 材料和 null-run 观察语义不变，不改旧记录或旧消费 marker。

沿用 sdist-only `verification/first_task_r.py` 的固定两个参数、完整管理 permit/env/installation/recipe 身份核验和排他消费。没有新增 CLI/MCP、host/model/argv 覆盖、解密入口或通用执行框架。Permit v3 使用 v1 的原字段，恰好追加：

| 字段 | 闭合合同 |
| --- | --- |
| contract_version | 严格 int=3；仅 DeploymentReceipt v3，同 Coding/execute=true/web=false/dependencies=false/declared_scope |
| acceptance_method | trusted_coding_v1 |
| waived_blockers | 恰好 `["LayeredAcceptanceUnverified"]`；原始 Plan 必须 Blocked 且仅此 blocker；任何额外 blocker 拒绝 |
| manager_retest | 恰好 `{root,timeout_seconds,baseline_tests,candidate_tests}`；根与全部任务/控制/运行/结果/安装/捕获根互不重叠、初始不存在；timeout 严格 int 1..60，baseline_tests=1/candidate_tests=6 |
| permissions | v1 原六个 true 布尔字段外恰好新增 management_local_retest=true |
| Environment v3 | 原 v2 闭合字段；scope=LayeredFirstExecution，worker_shell 仍 `{status,identity}`，Unknown 必须 null，Known 核普通单链接身份 |

receipt 仍无 runtime_acceptances/layered_acceptances；不能伪造或注入 Accepted 来取得 Ready。完整 Task/profile/auth/trusted bundle/Plan/receipt/environment/program/wheel/toolchain/recipe/root/预算绑定和既有 deny、配置租约/恢复、capture/key、owned Job 门禁继续核验。缺少既往接受之外无覆盖项。

消费 marker 仍采用既有排他 `xb` 创建；完整/部分 marker 均不重用，失败不释放或换名重跑。本次新 run 根排他保存 `first-execution.json`：严格 contract_version=1/kind=LayeredFirstExecution，恰好含 permit_identity、consumption_identity、task_id、task_manifest_sha256、task_scope_sha256、receipt_binding_sha256、plan_sha256、waived_blockers。FileIdentity 指向原许可和已消费 marker 的实际原字节；三个摘要使用当前合同的域。共享验证核源许可的闭合批准/预算/权限、marker 和同一 Task/receipt/Plan/bundle。该记录是显式管理证据声明，不认证任意同用户调用方，也不表示接受。

C 仅在验证该记录的本次内部生命周期中不携带获准覆盖的缺少既往接受阻断；其余实际失败与 0/1/null launch 保留。原 `control/plan.json` 的 Blocked 状态、blockers 和 SHA 不改；run/capture 均绑定它。first-execution.json 作为 HostObserved 文件引用保存在 run 和 collector 的原始副本，不清理历史 blocker 或补造旧 UID。

B `collect_task` 新增可选 `first_execution: FileIdentity` Python 参数，普通 CLI spec 不变。仅显式传入固定 run 根中的精确记录身份时可核该新 Blocked-Plan 生命周期；无参数仍拒绝非零启动，不自动发现文件放宽规则。collect 保存真实 Plan SHA 和 continuation.session_id=本次 capture UID，核单链接/字节/控制/许可/marker/task/receipt；失败或缺失不提升。v3 验证程序使用 BoundFirstExecution；v1/v2 仍 ArtifactsOnlyNullRun。

管理复测只在本次 run/collection/原控制最终核验成功后执行。分别从原 snapshot/source 与实际已核 result/candidate 物化两个新 `work/out` 根，冻结整树与原 protected recipe，固定 argv 为 `[permit Python,-I,-B,recipe相对路径,reproduce|regression]`。不接收任意命令，Python same-user declared_scope 不宣称 OS 沙箱。每条仅一次、各自限定 timeout；stdout/stderr 丢弃，不把 Worker XML/自报当独立命令。命令前后核 executable、recipe、原始/物化整树，超时/异常/变动即停，保留原失败，不自动执行下一条或重试。

仅从管理新 out 读取有界、无 DTD/entity 的单 testsuite XML，校验 case 数、failure/error 数及无 skip；baseline 一例预期失败/exit1，candidate 六例通过/exit0。事实 `command.json` 恰为 §15 COMMAND_KEYS：actor=ManagementIndependent、task、整树、recipe/toolchain/exe、worker_shell_identity=null、实际 argv/cwd/带时区 UTC 起止/exit/counts。成功保存独立 baseline/candidate、recipes、已核原 run/launch 派生 host-lifecycle 身份；原 Worker 声明只留原层，actual Worker Shell/command 仍 Unknown/Unverified。

新材料可提交给现有 evaluate_delivery，由管理核验必需三层后裁决；程序只记录 ObservationRecorded/Failed/Interrupted 与 strict R、layered/runtime acceptance=Unverified、management_decision=null。Eligible 也不自动成为 Accepted 或批准第二次普通生产调用。真实 host/key/config/native/超时和业务接受仍按集中实测授权与独立 Review 门禁办理。

## 17. agy 原生项目模式候选（LAB-AGY-NATIVE-PROJECT-IMPL-01）

仅给 DeploymentReceipt v1/v2/v3 增加一个可选、非 null 的 `native_project` 字段；无此字段时沿用旧模式。其闭合对象为 `{id:S,root:A,record:FileIdentity}`。仅 agy 可用，configuration 三项必须 null，launch_shell 仍 null。id 为 1..128 位 ASCII 字母、数字、下划线或连字符，首位必须字母/数字；record 文件名必须为 `<id>.json`，由管理登记实际原生记录的路径和原字节 SHA，不能把手写或归档副本登记为当前配置。

`native_project.root` 必须与精确 task_root 相同，仍为 workspace_parent 的普通直接子目录；记录必须在 task_root 之外。计划与启动紧前有界读取记录，核原字节 SHA、记录 id 和唯一的 `projectResources.resources=[{folderUri:S}]`。目前只支持这一已观察的本地文件夹结构；额外资源/资源字段、远端 URI、相对路径、路径逃逸、普通链或文件身份失败均拒绝。支持 `file://C:/...`、`file:///C:/...` 和合法百分号编码，解码后复用既有 Windows 路径校验，不在输入 Path 化之前折叠点段。

native_project 纳入原 receipt/bundle/Plan 摘要及 R 或 layered acceptance 的完整绑定，不能沿用旧全局配置模式的接受记录。v2 仍是首次观察阻断；v3 的 Coding/execute/declared_scope 及精确 scope 接受限制不变。Task/Plan/RunReceipt、三能力、角色与 collector 合同不新增键，CLI 的 spec 和参数不变。测试是既有 execute 能力：Coding 可在允许的 work/out/scratch 内进行普通工程操作，Review 测试使用 scratch 副本；不新增 Testing 角色或逐命令许可框架。

agy argv 只在固定入口之后增加 `--project <id>`，固定 model/tail、精确外层 deadline、一次启动、owned Job 和加密采集继续复用；cwd 固定为 task_root。生成请求把读写/保护/输出根和 progress 路径改为绝对路径，附上冻结 toolchain 身份，要求脚本、命令文件参数、文件工具目标和 artifact 使用绝对路径。说明中的相对标签只按 task_root 解析。请求是合同声明，不证明 Worker 实际照做或 OS 强制隔离。

本模式不读取/合并/写回全局 settings，不创建 settings 备份/恢复材料，不取得旧全局配置租约；不写项目记录/项目 settings，也不增加 skip-permissions。启动后（含异常/中断）只读复核项目 id 与资源根，成功在 run 根保存 `native-project-check.json`，含 project_id/root/record_sha256/binding_status=Matched，由原 evidence_refs 和 collector 留存。CLI 名称等元数据变化可改变 raw SHA，不单凭此判失败；绑定漂移或无法读取则 restore_state=Failed、NativeProjectBindingUnverified 和 RestoreFailed，保留失败并使 transport 失败。这里的 restore_state 沿用已有回执字段，本模式不会执行恢复。原启动中断优先于后续检查异常。该检查不核权限语义或共享设置；原生继承权限、always-proceed、资源绑定均不能证明反向 deny 或隔离。

**现有根复用限制（未实施）**：B prepare 的 `_root(fresh=True)` 要求 task_root 不存在，否则 RootNotFresh；C `_verify_prepared_tree` 拒绝根中 task 布局之外的历史文件，否则 ControlChanged，且仍要求 work 与冻结 snapshot 相符。原生模式不绕过这些条件。A/B 的旧根不能直接经过本候选 prepare，不能通过删旧证据、改到嵌套 cwd 或手写项目 JSON 规避。若继续复用同一 A/B 根，最小后续设计是显式冻结现有树及本任务输出命名空间，定义在原根排他添加控制布局、保护旧文件、核原清单与收集本任务增量的合同；当前没有此接口。需先完成该窄合同修补及独立 Review，再冻结适用真实许可；本节不授权实施或真实调用。
