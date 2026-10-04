# 统一工程任务合同 v1（实施规格）

状态：`ProposedRecommended`，文档候选；尚未实现或验收。核验日期：2026-10-04。
任务：LAB-TASK-WORKSPACE-CONTRACT-01；管理：019fe10b-df55-7b82-a9ba-3702dc08c55f。
冻结 base：`7a5d921ed2402023b5b21417b12362ed8da5c1d6`。
验收表：[TASK_WORKSPACE_ACCEPTANCE.md](TASK_WORKSPACE_ACCEPTANCE.md)。

## 1. 交付目标与本轮边界

Bridge 为 Coding、排障与独立 Review 提供正常工程工作目录：Coding 可在专用副本增删改、重命名、多文件实现、执行测试与构建；同一次任务可复现、修复、回归；明确授权后可准备锁定依赖。Review 可检索分析并新建报告，但不得修改冻结 source。不同 reviewer 从同一快照创建独立目录，使用一致覆盖分母。

“等价”指这些业务能力和可核验结果，不要求 Gemini、Cursor 和 Codex 的工具名称、原生权限键或推理行为相同。功能目标为完整工程任务；已通过的文件读写小样例不替代完整验收。一次宿主调用内的正常多轮工具执行、失败测试后的修复和回归均允许；无自动重试约束限制的是启动第二次真实宿主调用、换模型或另建付费 job。

本轮仅文档、官方/GitHub 与冻结实现的只读核验；没有模型/上游 CLI 调用、运行安装或宿主权限改动。管理提供的 GR03 需求为 946 源码、963 包条目、约 2.4 MB，同快照 Gemini 3.8 Flash High 与 Cursor Grok 4.7 High，中文 report/findings/coverage/progress；这些数量是需求输入，未独立复核。本轮未读取 GR03 ZIP 或游戏源码，不把它们当测试材料。

## 2. 已有实现：保留什么，必须补什么

以下定位相对冻结仓库，函数/常量是改动入口，不从新文档推定现有运行版已支持。

| 现有入口 | 精确限制/复用点 | v1 必须处理 |
| --- | --- | --- |
| `bridge/slice_workspace.py::_require_source_path`、`_TEXT_SUFFIXES` | 仅少量 UTF-8 文本后缀，当前连 `.cs` 都不接受；排除秘密名、Git 路径、保留名 | 工程快照保留普通文件原字节；内容类型只影响显示 diff，不影响项目可导入性；继续做路径/秘密范围检查 |
| `_require_editable`、`_verify_tree`、`_verify_frozen_site` | editable 只能是现有 files 子集；work 缺文件或多文件均拒绝 | 新模式按授权相对根接收新增/删除；冻结输入验证与候选树验证分开 |
| `_read_blob`、`paths.py::_run_git` | Git 输出严格 UTF-8 解码，适合旧文本切片，不是通用二进制传输 | 保留有界 Git/路径判断；新增固定 Git argv 的 bytes 读取，拒绝链接和 submodule，不用文本 helper 读原始 blob |
| `PLAN_INSTRUCTION`、`build_plan` | 固定禁止 commands/tests，`counts.command=0` | 按任务 profile 生成指令与权限；允许任务内执行和调试，记录真实能力与边界 |
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

默认资源 profile 是工程判断的实施初值，不是作者对真实包的既有裁决：压缩包 ≤64 MiB、条目 ≤20,000、展开总量 ≤512 MiB、单文件 ≤64 MiB、单文件展开/压缩比 ≤200、深度 ≤32；单路径分量 ≤255 字符，最终物理路径默认 ≤240 字符，导入 deadline 60 秒。零压缩长度且有展开内容拒绝。上限按实际字节与已有磁盘余量检查；超限返回明确 blocker，不跳过条目、不自动扩大额度或换目录。长路径不足返回 `PathBudgetExceeded`，再申请明确短路径。后续任务可通过冻结 profile 指定已授权上限，不提供任意无限值。

## 4. 专用工作目录与最小请求

```text
snapshot/                         # Host 封存；多个任务只引用其身份
task-<id>/
  task.json                       # Host 冻结合同；Worker 不改
  control/TASK.md                  # Host 可信任务说明，不与输入 TASK.md 冲突
  control/host-profile.json        # 已核验部署与任务 profile 摘要，无秘密
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
  "profile_id": "coding-local-v1",
  "profile_sha256": "<sha256>",
  "read_roots": ["work", "out", "scratch", "control"],
  "write_roots": ["work", "out", "scratch"],
  "protected_paths": ["work/vendor", "control", "task.json"],
  "required_outputs": ["out/progress.json"],
  "acceptance_ids": ["CODING-01", "TEST-01"],
  "deadline_seconds": 1020,
  "source_output_bytes_limit": 536870912
}
```

role 只取 Coding/Review；排障是 Coding 的目标，不增加第三个 runner。snapshot、instructions、profile 和部署回执绑定计划摘要。未知字段、重复 JSON 键、类型不符、越界根、write 根本身落在 protected 内、未知 profile/host 路由和 manifest 漂移均在启动前拒绝。protected 子树可以收紧父级 write 根，且始终优先。deadline v1 仍用既有 1020 秒上界；只是 profile 数据入口，不借文档延长真实调用预算。

Coding 默认授权 work 内普通文件创建、修改、删除和重命名；task 额外 protected 子树收紧。Review 的 write_roots 必须只有 out/scratch，不得有 work；需要执行会写源码的构建时，另建独立 scratch 构建副本并由明确 profile 授权，不能改变该 reviewer 的冻结 source。Host 只验证/收集，不把候选自动应用到业务树。

## 5. 执行、依赖与网络：统一 profile，分别核验宿主

### 5.1 v1 三个任务 profile

| profile | 允许 | 禁止/前提 |
| --- | --- | --- |
| `coding-local-v1` | work 增删改重命名；已登记工具链的本地测试/构建/诊断；同次调用复现→修复→回归；out/scratch 写入 | Worker 网络关闭；不安装共享工具；只用已有任务环境/离线缓存；有副作用的包脚本也受同一执行范围约束 |
| `coding-locked-deps-v1` | 上述能力；按授权锁文件与登记 package manager 在任务 `.venv`/scratch/cache 准备依赖 | 必须有锁文件 SHA、固定 registry/镜像与传递依赖域名许可、安装脚本授权、缓存写根和网络强制机制；不改锁文件来解失败，不安装全局包 |
| `review-static-v1` | work 阅读/检索/分析；生成中文 out/report.md、findings.json、coverage.json、progress.json；scratch 中分析辅助文件 | work 写入拒绝；不运行项目脚本/构建/依赖安装；需要这类动态验证时独立指定已验收 profile，不冒充静态 Review |

profile 一次派工冻结，整次宿主调用复用，不为每个测试命令临时申请权限。它引用已验收 deployment envelope：准确 CLI/后端与工具链身份、原生文件规则、command 类别与 cwd、只读/可写物理根、子进程网络规则、真实 enforcement 方法与验证证据。任务只能收紧已授权部署范围，不能在 task.json 自带新 executable/URL/任意 shell argv 或权限文本。

Worker 不得主动更新/登录宿主、读取凭据、配置/注册 MCP、包发布、远端 Git 写入、调用任意外部服务、提权或改动物理机。厂商正常自动更新不被本合同新增禁用；记录实际后端变化并按能力 gate 重新核验，不承诺入口哈希不变就等于版本冻结。任务内删除普通副本文件属于 Coding 授权，不包括删除 snapshot/control、业务树或宿主目录。全局工具链、账户、额度与发布仍由另行授权的流程处理。现有固定模型保持 agy `gemini-3.8-flash-high` / `high`、Cursor `grok-4.7-high` 非 Fast；不把本合同变成模型/预算接口。

### 5.2 宿主支持与当前缺口

| 项目 | agy | Cursor |
| --- | --- | --- |
| 文件与命令能力 | 官方 headless 支持读写和预先授予 command；当前实机只验过窄文件流程 | 官方 print 有写入/shell，CLI 有 Read/Write/Shell 规则；当前实机只验过窄文件流程与一个拒读样例 |
| 项目/全局配置 | 当前 Bridge 临时修改 CLI 用户 settings 并严格恢复；持久 permissions 与旧 runner 不兼容 | `.cursor/cli.json` 只有 permissions 可项目配置；其他 CLI 设置全局；不能在项目文件猜写审批/sandbox 键 |
| 自动批准 | 预授予 profile 规则后仍须证明 Windows 行为；always-proceed 与 deny/共享层优先级未实测 | --force 只对显式 deny 保留约束，不能当 allow-only 模式；不能用 `Shell(git)` 表示只准测试，因为它覆盖整个 git 命令族 |
| Shell/搜索路径范围 | command 匹配不验证脚本实际读写；`allowNonWorkspaceAccess` 不等于 shell OS 边界；共享 ALLOW 优先级未知 | Read/Write 规则不自动约束 shell 内部文件访问，也不能先假定覆盖 Grep/Glob；必须测试完整工具面 |
| Windows OS/网络边界 | 既有部署参考记录 Windows 旧权限系统；新版页面本轮不可获取，不据此宣称本机可强制隔离 | 当前官方 sandbox 平台页列 macOS/Linux，不能移植为 Windows 已验收；本轮没有 native sandbox CLI 探测 |
| 原生 argv/输出 | 固定 argv + wrapped stream；保留 timeout、恢复、封口 | 固定 argv + NDJSON；新 profile 的批准/沙箱组合必须有独立 gate，不能仅改 flag 就上线 |

事实依据：[agy headless](https://antigravity.google/docs/cli/headless/)、[Cursor parameters](https://cursor.com/docs/cli/reference/parameters)、[Cursor permissions](https://cursor.com/docs/cli/reference/permissions)、[Cursor configuration](https://cursor.com/docs/cli/reference/configuration)、[Cursor Run Modes](https://cursor.com/docs/agent/security/run-modes)，及冻结 `skills/deployment-config/references/bridges.md`。本轮 agy permissions/terminal-sandbox 页面获取失败，不能把旧部署参考升级为新版本实测。

**Shell 边界的工程规则：** Python/pwsh/node/msbuild 等可执行项目脚本；前缀/首 token 许可、cwd、环境变量、只读属性、NTFS 同用户 ACL 和 Job Object 均不能独自证明“只能读写副本”或“不能联网”。deployment 必须写 `enforcement.method`（已验收的 native sandbox 或既有隔离 runner）及真实可访问范围。没有对应 Windows 证据，plan 将执行/网络能力标为 `Unverified`，要求强制边界的 task run 返回 `Blocked/ExecutionBoundaryUnverified`，不自动加 unrestricted、skip-permissions 或移到新容器/VM。

该门禁不否定业务目标，也不把旧文本模式冒充替代：输入/工作区/回收/报告可立即实施；允许任意项目测试脚本的部署验收另成一个有界实施包。若作者选择保留同用户、声明范围的可信工程模式，必须单独明确接受 shell 可触达其他用户可访问路径的事实，不能在结果写成范围强制。本阶段不请求重复批准已有文档工作，也不擅自把该风险接受记为 authorConfirmed=true。

模型连接网络与 Worker 子进程网络分开：CLI 连接现有供应商是通讯层；shell/WebFetch/MCP 等属于任务层。离线任务不得误阻断模型通讯，也不得以模型能联网推定依赖网络已获授权。domain allowlist、重定向、代理、直接 IP 与包安装脚本的实际执行面均须验收；环境变量或提示词不提供网络强制。

### 5.3 配置与恢复复用

Cursor 优先生成冻结项目 permissions，与用户全局配置合并语义需复验；保护 control/config 不能被 Worker 写入。agy 优先核验可用任务作用域；若仍需临时全局改动，整次调用只生成一次 profile 增量，严格核对 before/expected-after 与原字节恢复，并对同一配置取得独占协调。跨任务配置竞争、已有用户 deny 冲突或未知作用域在启动前阻断；不删除 deny、追加根通配符或强行覆盖权限对象。没有权限改动时不触碰设置；仍不反复补入自然缺省的 false。

新 task runner 兼容已有权限对象的实现要单独 review；直接复用旧 `_read_settings` 会拒绝它，直接跳过校验则破坏恢复。允许方案是复用 strict JSON、原字节备份/恢复和漂移判定，在 task 专用分支校验受控 profile delta；未知用户字段原样保留。恢复失败为 transport/lifecycle 失败，产物保留为未接受候选，不能补一次调用或覆盖漂移现场。

## 6. 结果合同与明确续接

Worker 写 out/progress.json 及任务 required_outputs；Host collect 生成 result.json、changes.json 与 artifacts.json，Worker 不能把自述替代 Host 验证。原始报告/结果原样保留，Host 校验单列；缺失错误产物不自动补成 Worker 成功。测试 stdout/stderr 全量留产品已授权加密管道或专用加密 sidecar；常规 JSON 只留工具/recipe、cwd 相对路径、退出码、时间、报告相对路径/哈希、必要计数，避免复制源码/完整命令文本。

结果最低字段：task/snapshot/profile/plan SHA、role、host route、加密 UID、transport_state、worker_status、host_status、scope_status、产物与测试报告哈希、coverage、blockers、continuation。业务状态仅 Completed/Partial/Blocked；transport 完整和 CLI success 均不直接提升为 Completed。

| Host 业务状态 | 必须满足 |
| --- | --- |
| Completed | 生命周期/捕获/恢复通过；输入和受保护内容未变；所有 required_outputs 可解析且哈希可定位；全部验收 ID 通过；Review coverage 无遗漏/失败，或 Coding 必需测试记录有 Host 核验 |
| Partial | 已有合法产物或实质进展，但覆盖/测试/输出未完成、deadline/上下文不足；逐项列缺口与下一步；不会自启动下一次 CLI |
| Blocked | 缺授权/能力/输入或无可继续安全工作；严重范围、恢复或证据异常单列 failure_reason，即使 Worker 已声称 Completed 也不接受 |

测试至少记录唯一 test_run_id、phase=reproduce/regression/build、recipe_id、锁定工具链身份、exit/timing、JUnit/构建报告引用与哈希；记录失败后修复再通过，两条都保留。不把 `pytest` 字符串出现在回复或文件名里当执行证明。原生事件无法给出可核验命令/退出码时，profile 可使用事先登记、已验收的证据包装 recipe；包装器不被当成 OS 沙箱，也不开放任意宿主命令接口。无可靠测试证据时只能 Partial。

changes 对授权 work 原始清单和收尾清单做 bytes 比较：added/modified/deleted 明确列出 before/after length/hash；纯原字节同 hash 的一对 delete/add 可附 `rename` 关联，歧义时不猜。编辑后重命名按 delete/add 或明确未验证 rename suggestion，绝不因未识别 rename 丢文件。二进制变化用文件/hash 交付，不强制 UTF-8 diff。源文件编码、BOM、CRLF/LF、末尾无换行均保留；patch 只对可解码文本辅助输出。

生成目录如 `.venv`、缓存、build 单独登记 generated roots/大小，不当源码交付，也不能静默忽略新增源码。收尾重扫 reparse/链接、protected hash 与输出上限；范围失败仍保留失败产物，不自行还原 Worker 行为以冒充通过。交付不自动应用业务 worktree，不推送或创建 PR。

续接字段至少：snapshot_id、当前候选树/产物摘要、冻结 profile、未完成验收/覆盖条目、最后一个有效 test_run_id、blocker、建议下一动作与原生 session_id（仅引用）。Host 验证身份完整后管理可派新任务；需要新真实 CLI 调用仍另外授权。v1 不自动 --continue/--resume、不无限重试、不换供应商、不做额度调度。

Review 最低 schema：findings 含 id/severity P0–P3/file/verified line/evidence/recommendation；coverage 按 manifest 中每个逻辑文件列 Analyzed/Excluded/Failed/NotAnalyzed、reason，并分别给全包和源码分母。读取、grep 命中或 presence 不算 Analyzed；源码排除不得被挪出原分母来做 100%。Completed 的静态 Review 要求全部声明源码已分析且无 Failed/NotAnalyzed；合理非源码 Excluded 保留理由和总条目分母。无发现是合法结果，但不能用空 findings 推导完整覆盖。

GR03 类型任务的中文 out/report.md、findings.json、coverage.json、progress.json 使用同一 snapshot_id 和 946/963 两个明确分母；package entries 与文件/目录、source 选择的对应必须由导入清单核对，不能由模型猜数。每个 reviewer 自有 out/scratch/work，禁止互看其他 reviewer 结果；管理之后独立比较，不让一个 reviewer 的结论成为另一个的输入。

## 7. 最小实施面与可并行边界

新增三个模块，不建 provider 平台、调度服务或复杂权限解释器：

| 包/写集合 | 实施内容 | 必须交回 |
| --- | --- | --- |
| A：`bridge/task_input.py` + 输入单测 | Git bytes、ZIP/目录导入、canonical inventory、资源/路径/控制冲突验证；复用 paths/strict JSON/stdlib zipfile | snapshot manifest v1 与跨来源同树 fixture；普通源、二进制和 `.cs` 通过 |
| B：`bridge/task_workspace.py` + 工作区/collector 单测 | 从 snapshot 创建角色副本；task manifest 校验；新增/删除/重命名与 bytes artifacts；Review coverage/results 检查 | task/result/changes/artifacts schema，Coding/Review 无供应商离线 fixtures |
| C：`bridge/task_run.py` + adapter/profile 单测 | 统一 plan/preflight；注册 profiles；复用现有 launcher/capture/restore；单次调用统计；真实能力与边界 gate | fixture-only agy/Cursor transport 与业务状态分离；不直接真实运行 |
| D：CLI/发布/Skill 文档 | `cli.py` 新 task namespace；README/usage/发布清单/Skill 与 sdist inclusion 同步；必要 AGENTS 短规则 | 新旧入口区分、可发现部署回执、固定模型与能力表 |

A/B 在本合同的 canonical inventory/task schema 上并行；C 可用合成 snapshot 开始，接入 A/B 后再封口验证；D 拥有 cli.py/打包/持久文档，避免多个包同时改入口。现有 slice_run/cursor_run 若需公共生命周期抽取，由 C 单独拥有；A/B 不触碰捕获/恢复。各实现包独立 worktree、精确 base、allow-list、配套测试与独立 Review。先离线集成候选，再另行授权实机 profile 验收；不因 Phase 切换再次要求作者确认既定实现工作。

建议 CLI（待实现，不可照此调用当前安装版）：`task import` 显式选 git/zip/directory；`task prepare --snapshot ... --role ... --profile ... --policy ... --task-note ... --out ...`；`task plan --task-root ... --host agy|cursor --deployment-receipt ...`；`task run` 同 plan 输入，缺省 preflight，明确 --execute 才启动；`task collect --task-root ... --out <fresh result root>`。import 的 commit/ZIP hash/目录 manifest 必填；run 不接受任意 model/argv/URL 或 caller-defined profile。具体 argparse 接口由 C/D 按这些不变量实现并测试。

## 8. 有界复用核验与采用理由

截至 2026-10-04，仅查以下官方/维护者来源，没有安装、clone、升级或调用候选产品。最小样例限 Python 标准库内存操作及冻结实现纯函数；不宣称新 importer 或权限行为已验收。

| 候选/来源 | 许可证/维护/Windows | 采用决定 |
| --- | --- | --- |
| 现有 Bridge 通讯、winjob、恢复、加密回放 | 冻结现有产品；沿用已定许可/加密底座 | 直接复用，扩任务合同与 role/profile 验证；不重新研究既有 AGPL |
| [Python 3.13 zipfile](https://docs.python.org/3.13/library/zipfile.html)、[CPython 源码](https://github.com/python/cpython/tree/3.13/Lib/zipfile)、[Python license](https://docs.python.org/3.13/license.html) | PSF；目标运行时已有 stdlib；3.13 官方文档持续维护；Windows 路径另做校验 | 采用解析/解压/CRC 原语，补验证与限额；不复制整套 ZIP 解析器 |
| [pypa/installer](https://github.com/pypa/installer) | MIT，维护者项目；Python wheel 安装抽象支持跨平台脚本包装；本轮未做安装/Windows运行验收，最近维护时间未独立确认 | 不引入：用途是 wheel 安装，不提供任意源码包的冲突、role/profile、覆盖/续接合同，不能替代 importer |
| [Google Antigravity CLI 官方仓库](https://github.com/google-antigravity/antigravity-cli)、[官方 organization](https://github.com/Google-Antigravity) | 官方 issue/examples/changelog 仓库；organization 显示 2026-10-03 更新，README 有 Windows 安装路径；未发现可复用 CLI 引擎源码许可，沿用用户已安装产品条款 | 继续复用现有 agy 通讯，不引入 SDK/IDE 自动化；多步能力声明仍需本机验收 |
| [Cursor CLI](https://cursor.com/docs/cli/overview)、上述 parameters/permissions/configuration | 官方 Windows 入口；不是本项目可直接 vendoring 的开源完整引擎；当前机器版本证据与在线文档分开 | 复用现有 Cursor adapter；权限/隔离按 profile 验收，不重新搭 ACP/cloud worker 平台 |

结论：在已查范围内，没有可直接替换本地两宿主并满足上述输入/产物/权限证据合同的成品。选择标准解析器与当前 adapter 的小幅扩展，而不是开发新 Agent 编排平台。此结论限这些候选，不是“所有成品都不存在”。

## 9. 文档、Skill 与权限决策的落地要求

日常 Skill 第 1 节的部署定位必须给出“读取本机部署回执 → 验证其中绝对 entry/版本/wheel SHA/产品摘要 → 再查 PATH”的操作；回执引用有日期/来源，不将单机路径写成所有机器固定入口。本机当前示例入口是 `C:\Dev\ask-ai-mcp\runtime\local-agent-bridge\0.1.0.dev0-5c60e9af\.venv\Scripts\local-agent-bridge.exe`，部署依据为 `C:\Users\user\Documents\Codex-Archive\2026-10-03-LAB-BRIDGE-PARALLEL-DEPLOY-01\RUNTIME_VERIFICATION.json`。本轮只读这些路径的既有记录，不运行上游 CLI。

Skill 必补的固定路由文字：`agy run: gemini-3.8-flash-high / effort high；Cursor: grok-4.7-high，非 Fast。task v1 仅使用部署回执中已通过验收的 role/profile；旧 slice v1 继续只改既有文件且不运行测试。` 该文字是 D 包的具体修改要求，本轮不修改已安装 Skill，也不把未来能力写成当前事实。

必要 AGENTS 短变更建议（在 task v1 实现、独立 Review 与相应能力验收后替换旧“切片桥只能小切片”描述，禁止本轮提前应用）：

```text
工程 task v1 只处理冻结快照的专用副本；Coding 可在授权 work 根增删改重命名、测试构建与同次调试，Review 只读 source 并写 out/scratch。
使用已验收 deployment/task profile；权限、网络、工具链与产物合同以 TASK_WORKSPACE_CONTRACT/ACCEPTANCE 为准，不把 cwd 或审批模式当 OS 沙箱。
一次宿主调用可包含正常多轮工具执行；新真实调用/恢复会话/换模型仍需相应授权，失败不自动重新提交。
原始 source、控制配置、凭据、业务树与远端不因任务权限扩大而可写；产物须收集并独立核验后集成。
旧 slice v1 和 H3 MCP 保持各自入口；不开放 generic prompt forwarding、任意 argv/model/URL 或无限委派。
```

可直接工程决定：上述新旧协议分离、bytes 快照、固定资源初值、角色目录、增删变化清单、业务状态/覆盖、续接引用、现有底座复用、离线 fixtures 与分包所有权。这些不需要额外作者玩法决定。

确需作者权限：新真实模型/上游调用、部署或宿主全局设置改变、未核验的 shell 范围风险接受、新 VM/容器/受限账户与工具安装、新域名/联网依赖或安装脚本范围、预算/账户扩展、游戏包使用和远端发布。现有会话明确授权的项继续有效，不逐阶段重新确认；缺少授权只阻断依赖该项的运行，不阻止其余离线实现。所有待决项标 `ProposedRecommended/authorConfirmed=false`，不在本阶段创建审批等待、轮询或监控。
