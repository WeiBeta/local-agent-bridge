# Local Agent Bridge 提取冻结与实施规格

TASK_ID：LAB-BASELINE-01；管理任务：`019fe10b-df55-7b82-a9ba-3702dc08c55f`；核对日期：2026-09-28。`Local Agent Bridge` / `local-agent-bridge` 是候选产品名，尚未决定远端名称或创建远端。本文件只冻结提取合同，不代表新产品已构建、安装或动态验收。

## 1. 唯一来源与核对结果

- **唯一源码基线**：`725333c2e345a01faf04475b4b3bcdade91fdd3c`，来源分支 `codex/ag-gemini-slice-live-consolidate-01`。本计划在从该精确提交创建的独立工作树、`codex/local-agent-bridge` 分支编写。该提交包含 H3 适配器、AG CLI 切片准备/运行器及其测试；`docs/reviews/AG_GEMINI_SLICE_LIVE_CONSOLIDATE_01.md` 记录最新切片集成与离线验收边界。历史一次真实 CLI 调用的流终态是**离线重分类**，不能转述为本分叉新调用，也不等于 Gemini 全任务能力验收。
- `C:/Dev/ask-ai-mcp` 根目录的 HEAD 是 `ba702e68b4752c7b06ae85f569dd896b7b7848e8`，不是本产品源码基线。根目录 `.gitignore`、`AGENTS.md`、`README.md`、`docs/USER_MANUAL_ZH-CN.md` 有未提交修改，`docs/reviews/` 有未跟踪材料；只读核对后均留在原处。本次有关差异是 `.deploy/` 忽略项、任务/模型约定、异步旧 Coding/Review/Source 经纪说明及手册中的仓库 URL 更新；它们不是 H3/Bridge 实现补丁，不机械复制进产品。未跟踪的 `AG_BRIDGE_REUSE_20260912_DISPOSITION.md`、`AG_CLI_CAPTURE_DISPOSITION_20260913.md`、`AG_CLI_LIVE_DISPOSITION_02.md` 等只作为历史边界参考，不替换 725333c2 源码或其最新验收报告。
- H3 实现在 `src/ask_ai_mcp/h3.py`，4 个 MCP 包装器目前混在 `server.py`，启动脚本为 `scripts/start_comfyui_h3.ps1`，类型集中在 `models.py:1207-1348`，测试入口为 `tests/test_h3.py` 及 `tests/test_server.py`/`tests/test_mcp_profile_contract.py` 的 H3 断言。ComfyUI、模型权重、共享视频工作区均在仓库外；`docs/H3_HANDOFF_ZH-CN.md` 是已有部署/许可线索，不能代替此次主机实测。启动脚本写死旧仓库及主机路径，提取时必须让新包资源位置与受控配置一致；不得自动重装或迁移 ComfyUI。
- AG Bridge 当前可复用的通用切片为 `scripts/ag_slice_workspace.py`、`scripts/ag_slice_run.py`、`scripts/ag_slice_run_private.ps1`，以及下表所列的窄依赖。它只覆盖既有文本文件修改、受限 read/write 文件工具面、固定 agy 路由与一轮执行；新增/删除文件、任意命令、并发及 Zcode 尚无验收合同。`scripts/ag_gemini_*` 和 `scripts/ag_cli_stream_observe_once.py` 多为固定任务、路径、版本或冻结证据的脚本，不作为新产品可配置入口。
- **许可状态**：作者已收到上游作者 Jimmy 的 MIT 许可回复（<https://github.com/jimmyloi/dice/issues/9#issuecomment-5597944924>），并为本项目选择 AGPLv3。当前冻结树缺 `LICENSE`/`NOTICE` 只是许可材料尚未随基线固化，不是作者未取得回复；本任务不重做网络或法律审查。`mcp_server.py` 是留存的上游单文件原件，不进新包。H3 交接文档列有 H3 Community License Agreement 及各模型来源，但没有把权重许可文件纳入本仓库；H3/后处理权重许可与地域/用途限制在对外发布前另行核验。新发行包默认不捆绑权重、ComfyUI、原始上游文件或历史日志。

## 2. 文件级取舍与导入闭包

表中“目标”是下一阶段的**建议新产品树**，不是本次已经移动的文件。只从冻结提交按白名单提取，禁止整库复制后依靠运行时开关隐藏旧工具。

| 冻结源文件 | 处置与目标 | 必须处理的导入/行为 |
| --- | --- | --- |
| `src/ask_ai_mcp/h3.py` | 提取为 `src/local_agent_bridge/h3.py` | `httpx` 与 12 个 H3 类型（5 枚举 + 7 Pydantic 模型）来自旧 `models.py`；改引 `h3_models.py`，保留 loopback、输入根、输出根、后处理和队列空闲显存释放边界。 |
| `src/ask_ai_mcp/models.py` | **仅提取** `StrictModel` 基类所需配置及 `H3*` 枚举/模型（现位于约 1207-1348 行）到 `h3_models.py` | 逐项保留 Pydantic 验证与字段约束；不引入同文件的预算、Source、Coding、Review、toolsmith 模型。 |
| `src/ask_ai_mcp/server.py`、`mcp_profiles.py`、`__main__.py` | **仅提取** `server.py:430-493` 的四个 H3 包装器到 `h3_mcp.py`，新建窄 `__main__.py` | 原 `server.py` 在模块导入时引入会计、Source、Coding、Review、生命周期等旧服务；原 Full/Core profile 不可复制。MCP 层只做严格参数转交与协议输出。 |
| `scripts/start_comfyui_h3.ps1` | 保留，经明确路径适配后作为包资源 | `h3.py` 默认从仓库 `scripts/` 查找它；新 wheel 必须能定位打包资源。继续只启动指定本机 ComfyUI、隐藏窗口、监听回环；不将视频纳入会话滚动目录。 |
| `scripts/ag_slice_workspace.py` | 提取为 `bridge/slice_workspace.py` | 原导入 `ask_ai_mcp.code_review_workspace` 的 `_run_git`、`_is_reparse`、`_assert_no_reparse_escape`、`_is_within`、`_validate_relative`、`_SECRET_NAME` 和错误类型；仅将这些路径/Git 读取原语移入 `bridge/paths.py`，不带入审查快照/补丁业务。修正 `REPOSITORY_ROOT` 在新包中的含义。 |
| `scripts/ag_slice_run.py`、`ag_slice_run_private.ps1` | 提取为 `bridge/slice_run.py` 与打包的固定 PowerShell 辅助资源 | 原导入脚本 `ag_slice_workspace`、旧 `ag_oneshot_contract` 的严格 JSON/等值函数、`ag_oneshot_winjob.spawn_suspended_in_job`、旧审查路径原语；改引 `bridge/{slice_workspace,contract,winjob,paths}`。保留配置原字节备份/恢复、单次启动、进程身份与失败回执；不得开放任意 argv、模型、配置路径或权限规则。 |
| `src/ask_ai_mcp/ag_oneshot_contract.py`、`ag_oneshot_winjob.py`、`code_review_workspace.py` | 前者只抽 `decode_strict_json_bytes`/`deep_equal_strict` 所需代码到 `bridge/contract.py`；Windows Job 对象模块取其已审进程收束能力到 `bridge/winjob.py`；路径原语取到 `bridge/paths.py` | `ag_oneshot_contract.py` 全量导入旧 `models.StrictModel` 与 Pydantic 合成/请求合同；`code_review_workspace.py` 全量还含 Review 策略。抽取后须用原负向用例核对等价性，不把旧模型闭包拖进 wheel。 |
| `src/ask_ai_mcp/ag_oneshot_capture.py`、`ag_oneshot_parse.py`、`ag_oneshot_meta.py`、`ag_oneshot_outcome.py` | 暂留旧版作行为参考，不直接打包 | 针对旧一次性任务与安全结果包的合同；可按具体所需函数另提，禁止把候选/计费术语伪装为新通用 SDK。 |
| `src/ask_ai_mcp/wire_capture.py` | 只提取 AES-GCM 分帧、AAD 绑定及原子封口思路到 `capture/session.py` | 现有 `wire_capture.py` 直接导入 `credentials.SERVICE_NAME`，从 Windows Credential Manager 的旧服务名取密钥；新产品必须用独立 `capture/keys.py` 服务名/账户，不能读取或重写旧 API 凭据。现有对象捕获 provider HTTP 请求/响应，不捕获 agy 的完整 CLI I/O。 |
| `src/ask_ai_mcp/storage_retention.py` | 只借鉴 sealed bundle 校验/按整包滚动到 `capture/retention.py` | 原模块导入旧 `models` 且包含旧数据库和多业务域策略；不能复制其默认 root。新产品会话与影子包分别计磁盘字节，活动/部分文件受保护。 |
| `src/ask_ai_mcp/shadow.py`、`replay.py`、`qwen_toolsmith.py`、`lifecycle.py`、`sandbox.py` | 旧版保留，不进入新 wheel；另写 `shadow/replay.py` | 旧 `shadow.py` 明确是 DeepSeek→Qwen toolsmith 候选对比，依赖生命周期、静态候选分析、Docker 执行和旧 replay capsule；这些都不是 Agent 会话影子回放合同。 |
| `src/ask_ai_mcp/{accounting,budget,coding*,code_review*,source*,provider*,opencode*,qwen*,verified_execution,workspace,policy,pricing}.py` 及 `mcp_server.py` | 排除于新发行包 | 旧 API Worker、费用、Source、toolsmith 和上游原件留在旧 Git 历史/分支，不作为新产品导入闭包或备用入口。实际排除以 wheel 文件清单与导入测试核验。 |

## 3. 最小发行面与测试白名单

计划的发行树只包含 `pyproject.toml`、`uv.lock`、`README.md`、`docs/` 中的新产品使用/来源说明、`src/local_agent_bridge/`、固定 `scripts/start_comfyui_h3.ps1`（或等价包资源）及新产品测试。包内模块限定为 `h3.py`、`h3_models.py`、`h3_mcp.py`、`bridge/{slice_workspace,slice_run,contract,winjob,paths}.py`、`capture/{session,keys,retention}.py`、`shadow/replay.py` 和窄入口。目标为 Windows 11 / Python 3.13；运行依赖从真实导入闭包锁定：H3 的 `httpx`、Pydantic，MCP 薄层的 `fastmcp`，加密的 `cryptography`、Windows `keyring`，必要时状态目录的 `platformdirs`。`Git`、PowerShell 7、agy 和仓库外 ComfyUI 是功能相关的宿主前提，不作为 Python 包依赖；`pillow`、`pypdfium2` 与旧 provider/计费依赖不因旧 lock 存在而保留。新 lock 需重新锁定并核对 wheel 内容。

入口：`local-agent-bridge` 提供受控切片 `prepare/collect/plan/run` 与本地会话/影子包的只读状态；`local-agent-bridge-h3` 只注册四个现有 H3 MCP 工具。CLI/SDK Bridge 先共用同一已验证固定 agy 执行服务；若需要 MCP Bridge，只能在该服务之上增加严格的计划 ID 包装器，不接受任意 prompt、Shell、模型、可执行文件、URL 或宽泛目录。Zcode 只保留后续适配点，当前不打包空实现，也不据此宣称可用。

移植的**测试白名单**为：`tests/test_h3.py` 与 `tests/test_server.py:154-161` 的四工具面断言；`tests/test_ag_slice_workspace.py`、`tests/test_ag_slice_run.py`、`tests/test_ag_oneshot_winjob.py`，以及 `tests/test_ag_oneshot_contract.py` 中严格 JSON/等值相关用例；`tests/test_wire_capture.py` 中密文往返、AAD、部分文件和边界用例；`tests/test_storage_retention.py:143-246` 的整包保留用例。它们要改成新包导入并按新合同补足测试，不能直接把旧 `tests/test_server.py`、全 `test_mcp_profile_contract.py`、`test_shadow.py` 或全 `test_storage_retention.py` 放进新包：这些文件还断言旧多 profile、Qwen/toolsmith 或旧状态根。新产品另须有打包清单/禁止旧模块导入测试、无真实 agy/ComfyUI 的离线验收和显式 opt-in 的本机集成测试；普通 pytest 不启动外部服务。

## 4. 加密会话、容量与影子回放合同

1. 现有 `wire_capture.py` 是可复用的加密机制证据：Windows Credential Manager 中的 32 字节密钥、AES-256-GCM 分帧、`job_id:direction:frame` AAD，单 job 请求+响应明文累计上限 100 MiB，`.partial` 封口为 `.wire`。但这不是“100 MiB 磁盘占用”合同：分帧/审计开销不计入上限；滚动按审计中的 `stored_bytes` 计算且跳过 `capturing` 审计，活动文件和失败后残留的部分文件实际占用均未完整计入。不能原封用于新产品的会话容量承诺。
2. 现有 `ag_slice_run.py` 把 `stdout.raw`/`stderr.raw` 和 `private/settings.*` 写到 owner-only ACL 的运行根，stdout/stderr 分别最多保留 32/8 MiB；`run.json` 记录哈希、截断和恢复结果。ACL 只控制访问，不提供静态加密；截断时也不是“全量可获取会话”。新会话必须加密**本产品确实可取得的**任务输入/请求字节、CLI stdout/stderr 原字节、结构化事件及必要运行元数据，逐项标明来源、字节数、哈希、采集完整性与缺项；不声称可读取 agy GUI 内部对话、供应商隐藏状态或不可取得的 SDK 流。运行所需 `work/TASK.md`、工作副本和临时 settings 备份仍可能以明文存在于各自受控工作根；加密会话包不等于整个宿主机无明文，下一实施包必须明确这些临时材料的 ACL、保留和退出清点。旧配置备份/凭据不得因“全量”被复制到新包；只留配置哈希和恢复状态。内容密文不写 MCP stdout、普通日志或 Git。
3. 新状态根与旧 `%LOCALAPPDATA%/AskAIMCP` 分离，例如当前 Windows 用户的 `LocalAgentBridge/sessions/`、`LocalAgentBridge/shadow/`；各域建议 100 MiB (`104857600` 字节) **实际磁盘文件总量**，分别计算密文、帧开销、清单、收据、活动 `.partial`、墓碑及失败残件。写入前预留收据开销、跨进程串行计量；超过可用额度则停止保留、明确标记 `capture_incomplete/over_limit`，继续安全排空子进程管道，绝不把截断包标成全量。已超限或保护项挤满额度时拒绝下一次会话并给出无内容状态；不靠隐式扩大限额或删除活动文件“修复”。
4. 滚动只按终态、显式 seal、哈希和大小重新校验后，以最旧完整 bundle 为单位移除；正在写、`.partial`、校验失败、未知文件、还被影子包引用的会话不得自动删除。删除前按新产品既定滚动策略记录内容无关的收据；若仅有保护项使总量超限，显示 `over_limit` 并停止新写入。H3 `inputs/outputs/postprocessed` 和 ComfyUI 日志不在这两个容量域内，尤其不自动滚动删除视频。旧日志、replay capsule、Scratch 和历史备份既不自动迁移也不自动删除；需另行核对活动引用、归档与授权。
5. 新 `shadow/replay.py` 只接受已 seal 的会话 ID 与显式输入哈希，在**离线**模式重放可解析事件并比较终态、工具/文件范围、拒绝、用量可见性和输出摘要，保留不可比/缺失字段；影子包自身可带加密原字节及内容无关索引，计入独立 100 MiB 域。它不调用 Qwen、DeepSeek、Docker 或旧 lifecycle，不执行回放中的指令。若后续需要第二次真实 agy/Zcode 运行，必须成为独立、明确授权且单次的 Bridge run，另记新会话和成本；“离线影子回放”不能被写成模型复跑成功。加密全量会话是后续任务的单独特殊授权范围，只覆盖本产品实际可取得的 Bridge 输入输出，不扩展到旧 API 凭据、旧状态库或供应商隐藏数据；H3 包本身不实现日志体系。

## 5. 可分别实施和验收的下一包

每包先核对 725333c2 源文件字节与自身白名单，再实施、配套测试、自检、独立 Review；测试结论只覆盖相应包。下一包之间不自动扩大到真实模型、主机配置或旧状态迁移。

| 包 | 精确可改文件范围（新产品树） | 行为合同与验收矩阵 |
| --- | --- | --- |
| LAB-H3-EXTRACT-01 | `pyproject.toml`、`uv.lock`、`src/local_agent_bridge/{__init__,__main__,h3,h3_models,h3_mcp}.py`、`scripts/start_comfyui_h3.ps1`、`tests/{test_h3_adapter,test_h3_mcp}.py`、`docs/H3_USAGE.md` | 从上述 H3 源白名单移植；MockTransport 核对四工具、严格类型验证、回环/根边界、启动脚本定位、生成/后处理/状态/失败行为；wheel 中无旧 server/models/provider，普通测试不启动 ComfyUI。主机 H3 opt-in 验收另列，不借旧交接文档冒充新实测。 |
| LAB-BRIDGE-EXTRACT-01 | `src/local_agent_bridge/bridge/{__init__,slice_workspace,slice_run,contract,winjob,paths}.py`、`src/local_agent_bridge/bridge/ag_slice_run_private.ps1`、`src/local_agent_bridge/__main__.py`、`pyproject.toml`、`uv.lock`、`tests/{test_bridge_slice,test_bridge_run,test_bridge_winjob,test_bridge_contract}.py`、`docs/BRIDGE_USAGE.md` | 保持 prepare/collect/plan 的冻结 blob、路径白名单及只改既有文本文件合同；run 保持固定 argv、单次 spawn、owner-only 临时目录、原字节恢复和失败分层。用合成子进程测 settings 语义漂移、ACL/备份失败、PID/spawn、排空/超时、证据缺失、无 provider 调用；wheel 不依赖旧 Review/Coding 模块。Zcode 不在本包。 |
| LAB-SESSION-01 | `src/local_agent_bridge/capture/{__init__,session,keys,retention}.py`、`src/local_agent_bridge/bridge/slice_run.py`、`src/local_agent_bridge/cli.py`、`tests/{test_session_capture,test_session_retention,test_bridge_run,test_distribution}.py`、`docs/{SESSION_STORAGE,BRIDGE_USAGE}.md`、`docs/reviews/LAB_SESSION_01.md`、`pyproject.toml`、`uv.lock` | 在 Bridge I/O 接缝接入独立 Windows keyring 密钥、分帧密文与严格完整性标记；真实磁盘字节双域各 100 MiB、跨进程上限、整包滚动、活动/部分保护、密钥缺失/磁盘满/崩溃恢复的负向用例。明文扫描与哈希回读在临时测试根完成；旧 API 凭据服务名与旧状态根零访问。不能保证全量时 fail closed。CLI、发行断言和 BRIDGE_USAGE 是上一包派工时已允许的范围，本轮按管理裁决同步记录，不是事后扩大授权。 |
| LAB-SHADOW-01 | `src/local_agent_bridge/shadow/{__init__,replay}.py`、`src/local_agent_bridge/capture/{session,retention}.py`、`src/local_agent_bridge/cli.py`、`tests/{test_shadow_replay,test_session_capture,test_session_retention,test_bridge_run,test_distribution}.py`、`docs/{SHADOW_USAGE,SESSION_STORAGE,BRIDGE_USAGE,LOCAL_AGENT_BRIDGE_MIGRATION_PLAN}.md`、`docs/reviews/LAB_SHADOW_01.md`、`pyproject.toml`、`uv.lock`（仅实际必要） | 仅对 sealed v2 会话做离线回放／比较；frame/seal AAD 绑定 v2 与预期域，旧 v1 原位拒绝；明确输入／来源哈希、相同会话自比、缺事件、篡改、部分会话拒绝、不可比字段和影子包独立 100 MiB 滚动。自包含影子快照经验证后重加密，不持久 pin 来源会话；断言零 CLI／模型／Docker 启动，不真实访问 keyring。 |
| LAB-PACKAGE-01 | `pyproject.toml`、`uv.lock`（仅实际必要）、`README.md`、`docs/RELEASE_CHECKLIST.md`、`docs/{H3_USAGE,BRIDGE_USAGE,SESSION_STORAGE,SHADOW_USAGE,LICENSE_PROVENANCE,LOCAL_AGENT_BRIDGE_MIGRATION_PLAN}.md`、`tests/test_distribution.py`、`docs/reviews/LAB_PACKAGE_01.md`、`shadow/replay.py` 及对应测试的 H1 最窄映射改动 | 安装 wheel 到干净隔离环境，核对打包清单、`local-agent-bridge` 与 H3 MCP 入口、依赖闭包、只在 H3 MCP 出现四工具、stdout 协议纯净，扫描不存在旧 API Coding/Review/Source/计费/toolsmith 入口。权利未澄清前只形成内部候选，不创建公共远端或对外包。 |

## 6. 旧版、发行与回滚

旧 `ask-ai-mcp` 仓库、冻结提交、管理报告及历史状态继续原位保留。新产品使用独立包名、命令、状态根与密钥命名空间；不覆盖旧 `.venv`、MCP 配置或 `%LOCALAPPDATA%/AskAIMCP`。新发行树从白名单构建并核验 wheel，而不是发布含旧模块的整库归档。对外远端、PR、tag、release 和产品正式命名均后置于实施、独立 Review、实机 opt-in 验收及许可裁决；本计划没有授权这些动作。

回滚时停止新入口并恢复原 MCP 启动配置/旧版本入口（须保留其原始配置备份），新状态保留供取证；不反向覆盖旧数据库/凭据，不自动导入旧会话，不删除新旧密文或视频。若许可或打包门禁未过，保持旧版可用并报告阻断，不把本分支计划提交当成可发布产品。

## 本阶段检查口径

本文件以指定 Git 提交和本地现有报告/源码作只读静态核对；没有运行真实 agy、模型、H3、Docker、构建、pytest 或外部许可重新验证。提交前只执行文档路径/范围检查及 `git diff --check`；上述各包的动态测试留在实施包，不提前宣称通过。
