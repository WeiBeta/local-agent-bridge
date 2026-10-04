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
6. 只向全新、已核对普通父链的专用 staging 排他创建文件；每次创建重核父链，完成后重新枚举全部属性/清单。错误保留带失败标签的专用 staging；不发布 manifest、不覆盖旧根、不自动清理。此方案还需部署环境防止并发篡改父目录，普通 path.resolve 检查不能宣称消除了竞态。
7. 全部条目通过后原子发布清单与 sealed 标记；为每个任务/每个 reviewer 各复制一次，再逐字节核对。不是共享可写目录、hardlink 或 junction。输入原包、原始业务仓库及 sealed snapshot 不给 Worker 写权限。

默认资源 policy 是工程判断的实施初值：压缩包 ≤64 MiB、条目 ≤20,000、展开总量 ≤512 MiB、单文件 ≤64 MiB、单文件展开/压缩比 ≤200、深度 ≤32；单路径分量 ≤255 字符（Unicode 码点，不是255字节），同时须满足目标文件系统分量限制；最终绝对物理路径含根和分隔符，预算为 ≤240 个 UTF-16 码元，导入 deadline 60 秒。路径身份保留原始 Unicode，不做 ANSI 折叠或 NFC 改名；NFC/casefold 仅用于冲突拒绝，拒绝不可编码的孤立 surrogate。零压缩长度且有展开内容拒绝。上限按实际字节与磁盘余量检查；超限明确阻断，不跳过条目或扩大限额。物理预算不足返回 `PathBudgetExceeded`，再申请明确短路径，不静默换目录。冻结 policy 可收紧或采用已授权上限，不提供任意无限值。

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

源包里的 AGENTS、配置、README 和脚本属于输入材料，不自动提升为授权。Host 控制文件放在独立 namespace；各宿主会自动加载的项目控制配置必须在 prepare/plan 中识别。与本 profile 冲突时返回 `InputControlConflict`，在模型启动前停止；不得静默执行包内 hooks/setup、覆盖配置或隐藏源码条目。可信项目规则由管理按哈希明确列入 control。Review 的工作区根可设为 task 根、source 在 work 子目录、out 可写；宿主具体配置发现行为必须实测，不能只靠布局假定不会加载嵌套配置。

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
  "deadline_seconds": 1020,
  "source_output_bytes_limit": 536870912
}
```

role 只取 Coding/Review；排障是 Coding 的目标，不增加第三个 runner。角色和能力字段显式必填，不创建各组合命名 profile。snapshot、instructions、部署 profile、能力、边界模式和授权记录绑定计划摘要。未知字段、重复 JSON 键、类型不符、越界根、write 根本身落在 protected 内、未登记 deployment/host 和 manifest 漂移均在启动前拒绝。task能力/读写根须在可信Authorization与DeploymentProfile允许集合内，task边界与授权一致且在deployment.execution_modes内；不得自行升级。protected子树优先收紧父write根。deadline v1为1–1020秒，不延长真实调用预算。

Coding 的合同允许 work 内普通文件创建、修改、删除和重命名，protected子树收紧；实际运行仍须有效授权。Review write_roots只能有out/scratch；可选execute若运行写入性构建，只用独立scratch副本，不改冻结work。Host不自动应用业务树。

## 5. 角色、能力与执行边界：一次冻结，分别核验宿主

### 5.1 v1 最小能力面

只有 Coding/Review 两个角色。Coding 允许授权 work 内正常增删改重命名、out/scratch 交付；Review 只读 work、可写 out/scratch。以下三个布尔能力相互独立，不为每种组合增加 profile：

| 字段 | 为 true 时允许 | 前提 |
| --- | --- | --- |
| `execute` | 已有工具链的正常测试/构建/诊断，同一次调用复现→修复→回归 | 登记工具链/命令类别、cwd 与写根；不提供通用任意命令服务。Review 执行写入性构建必须使用独立 scratch 副本，不能写 work |
| `web_reference` | 已授权的只读网络搜索、官方/其他文档查询、错误资料检索 | 冻结用途、服务/来源范围和数据规则；不限定只能 GET 或两三个域名。搜索提交查询可能使用 POST，语义只读按目的和外部变更判定；不授权上传源码/凭据、账号变更或外部写入 |
| `prepare_dependencies` | 按锁文件及登记 package manager 在任务环境/scratch/cache 准备依赖 | 要求 execute=true，锁 SHA、工具/缓存根、安装脚本范围；离线缓存与联网 registry/传递依赖范围分别明确；不改锁解失败、不全局安装 |

普通 Coding 的基础组合为 execute=true、其余按任务明确选择；静态 Review 为 execute=false、依赖=false，网络查询可独立选择。未启用能力是合同中的禁止项，是否由宿主强制另记证据。设计和离线实现获准不等于这些实际运行权限已经取得。

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

建议 CLI（待实现，不可调用当前安装版）：`task import` 选 git/zip/directory；`task prepare --snapshot ... --task-manifest ... --task-note ... --deployment-profile ... --authorization ... --out ...`；`task plan --task-root ... --host agy|cursor --deployment-receipt ...`；`task run` 缺省 preflight、--execute 才启动；`task collect --task-root ... --run-root ... --out <fresh result root>`。角色/能力/边界在 task manifest 中一次写清，不造组合 profile；import 的 commit/ZIP hash/目录 manifest 必填，run 不接受任意 model/argv/供应商 URL。

### 7.1 A/B/C 共用的最小 JSON 接口（v1 冻结）

记 H=64位小写SHA-256字符串，P=通过第3节检查、保留原始Unicode的相对路径，S=非空字符串，I=非负整数（bool不算int）。所有合同JSON对象拒绝未知/重复键和NaN/Infinity；settings等外部配置仍按现有规则保留未知字段。规范字节统一为 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`，无BOM/尾换行；路径数组按原路径UTF-8字节排序，身份不做NFC转换。原始输入/候选字节不套JSON序列化。

| 对象 | 准确字段和类型；持久位置 |
| --- | --- |
| InputSource（A参数） | 共用 kind=git/zip/directory。git：root:S（已授权绝对根）、commit:S（精确40位SHA）、paths:list[P]（精确文件，不是glob）；zip：path:S、sha256:H、strip_prefix:P或null；directory：root:S、manifest_path:S、manifest_sha256:H。仅所选kind字段存在 |
| InputPolicy（A参数） | package_bytes_limit:I=67108864、entry_count_limit:I=20000、expanded_bytes_limit:I=536870912、file_bytes_limit:I=67108864、expansion_ratio_limit:I=200、depth_limit:I=32、component_codepoints_limit:I=255、physical_path_utf16_limit:I=240、deadline_seconds:I=60；source_paths:list[P]（原声明源码清单）、excluded_paths:list[{path:P,reason:S}]（明确排除）、sensitive_paths:list[P]、trusted_control_files:dict[P,H]。数字为正且不超过已授权上限；不是可传入正则/任意命令的policy语言 |
| SnapshotManifest（A→B/C） | contract_version:int=1、snapshot_id:H、source:{kind:S,identity:S,selection_sha256:H}、entries:list[Entry]、source_paths:list[P]、excluded_paths:list[{path:P,reason:S}]；snapshot_root/manifest.json，普通字节树在snapshot_root/source。Entry={path:P,kind:file/directory,bytes:I,sha256:H或null,git_mode:100644/100755或null}；目录bytes=0/hash和mode=null，所有父目录显式一次、根不列入；file hash必填，git_mode仅来源记录。source_paths每项必须在file entries或excluded_paths中 |
| TaskManifest（B→C） | 第4节JSON就是准确键集合：contract_version:int=1，task_id:S，role:Coding/Review，snapshot_id/snapshot_manifest_sha256/instructions_sha256/deployment_profile_sha256/authorization_sha256:H，deployment_profile_id:S，capabilities:{execute:bool,web_reference:bool,prepare_dependencies:bool}，execution_boundary:declared_scope/required_enforced，read_roots/write_roots/protected_paths/required_outputs:list[P]，acceptance_ids:list[S]，deadline_seconds:int1–1020，source_output_bytes_limit:正整数；task_root/task.json |
| DeploymentProfile（B/C） | contract_version:int=1、id:S、host:agy/cursor、receipt_sha256:H、roles:list[Coding/Review]、supported_capabilities:上述三bool对象、execution_modes:list[declared_scope/required_enforced]、read_roots/write_roots:list[P]（任务相对根，经回执映射到已授权物理父根）、toolchain_refs:list[S]、enforcement:{method:S,file_scope:Declared/Enforced/Unverified,network_scope:Declared/Enforced/Unverified,evidence_refs:list[Evidence]}；control/deployment-profile.json。refs仅引用登记工具链/证据，不接自定义命令 |
| Authorization（B/C） | contract_version:int=1、task_id:S、grant_ref:S、receipt_sha256:H、capabilities:上述三bool对象、execution_boundary:上述枚举、read_roots/write_roots:list[P]、web_scope:S或null、dependency_scope:S或null；control/authorization.json。grant_ref/各scope只引用已有可信管理授权，C须与部署回执核对；自填字符串不能创建授权，启用能力要求对应有效scope |
| Plan（C） | contract_version:int=1，task_id:S，task_manifest_sha256:H，deployment_receipt_sha256:H，host:agy/cursor，route:{model:S,effort:S或null}，execution_boundary:上述枚举，capabilities:上述三bool对象，preflight_status:Ready/Blocked，blockers:list[S]，evidence_refs:list[Evidence]；可信control中的plan.json。model/effort只能由固定adapter选择，不能caller定义；Ready还须有效实际授权与对应R |
| RunReceipt（C→B） | contract_version:int=1，task_id:S，plan_sha256:H，transport_state:NotRun/Completed/Failed/TimedOut，launch_count:I，capture_uid:S或null，capture_state:NotRun/Sealed/Incomplete，restore_state:NotRun/Unchanged/Restored/Failed，test_observations:list[TestObservation]，evidence_refs:list[Evidence]，blockers:list[S]；run_root/run.json。--execute缺失时NotRun/launch_count0，不初始化密钥/改配置；一次execute最多launch_count1 |
| Result（B→管理） | contract_version:int=1，task_id:S，snapshot_id:H，task_manifest_sha256:H，plan_sha256:H或null，worker_status:Completed/Partial/Blocked或null，host_observations:{transport_state:上述枚举,scope_status:Pass/Fail/Unverified,outputs_status:Pass/Fail/Unverified,coverage_status:Complete/Incomplete/Invalid/NotRequired,test_observations:list[TestObservation],acceptance_observations:list[{id:S,result:Pass/Fail/Unrun/Unverified,evidence_refs:list[Evidence]}]}，changes:list[Change]，artifacts:list[Artifact]，blockers:list[S]，continuation:Continuation或null，management_decision:null；result_root/result.json，同值changes/artifacts另存changes.json/artifacts.json。未观测ID为Unrun/Unverified，不自动Pass |

Entry数组按path排序；snapshot_id=规范序列化 `{contract_version:1,entries:[{path,kind,bytes,sha256}]}` 的SHA（不含git_mode）。source.identity为Git commit/ZIP SHA/目录manifest SHA；selection_sha256=规范 `{source_paths,excluded_paths}` 的SHA，excluded_paths按path排序。因此同原字节树跨来源同snapshot_id，来源/选择差异仍由完整manifest SHA绑定。逻辑覆盖分母为entries与excluded_paths的不重复路径并集；source_paths保留原声明，排除不缩源码分母。最终manifest使用规范字节，snapshot_root/SEALED是其H的ASCII字节、无尾换行；B/read_snapshot核对两者和tree，不从live树猜身份。

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
    *, snapshot_root: Path, task_manifest: dict[str, object], task_note: bytes,
    deployment_profile: dict[str, object], authorization: dict[str, object],
    task_root: Path
) -> dict[str, object]: ...
def collect_task(
    *, task_root: Path, run_root: Path | None, result_root: Path
) -> dict[str, object]: ...
# task_run.py
def plan_task(
    *, task_root: Path, host: Literal["agy", "cursor"],
    deployment_receipt: dict[str, object]
) -> dict[str, object]: ...
def run_task(
    *, task_root: Path, plan: dict[str, object], run_root: Path, execute: bool = False
) -> dict[str, object]: ...
```

返回依次为SnapshotManifest、SnapshotManifest、TaskManifest、Result、Plan、RunReceipt。read_snapshot重验封存manifest/tree；prepare_task核对task_note原字节instructions_sha256并建副本；collect_task允许run_root=null用于未运行fixture，但transport=NotRun，management_decision=null。输出根都须全新；失败保留现场。各模块导出TaskInputError/TaskWorkspaceError/TaskRunError（RuntimeError子类，code:S、非敏感消息），已有BridgePathError在新入口映射并保留cause，旧入口异常不改；不自行再调用模型。C Ready/Blocked不等于管理业务裁决。CLI只包装固定入口，不开放caller-selected函数或任意工具链命令。

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
