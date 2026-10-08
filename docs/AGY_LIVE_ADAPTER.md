# AGY Task adapter 与单次 stdout 重析候选

LAB-AGY-LIVE-ADAPTER-REPAIR-01 第一阶段只做离线实现、自检与冻结。独立 Review、真实 key/认证重析、真实 CLI/模型、部署与 R 验收均未运行。旧 IdentityChanged/ProgressInvalid 及 Unknown 不改写；不能证明自动更新是旧 identity 变化的原因。

## 子进程环境与未来 Task Note

Task agy 调用复用已有常量，把 `AGY_CLI_DISABLE_AUTO_UPDATE=true` 放入独立环境副本，经现有 suspended/Job 启动器传给子进程。父进程、用户/系统环境和 GUI 均不修改，异常/并发期间没有恢复覆盖其他写入的问题。Cursor 不加变量；旧 slice 恢复与中断优先级合同不变。

新生成的生产 request 明确给出 progress 合同。未来 TASK.md 替换冻结 task_id 后必须重复以下约束，再冻结 Task Note：

> 写 out/progress.json，恰好含 contract_version、task_id、status、summary、remaining_paths 五字段。contract_version=1，task_id=本次冻结 ID，summary 为非空字符串，remaining_paths 为授权相对路径数组。status 只能 Completed / Partial / Blocked；Completed 必须 remaining_paths=[]，仅表示 Worker 进度完成，不是管理 Accepted。未完成用 Partial/Blocked 并列缺口。Candidate/Accepted 是非法 progress 状态。CLI exit0、捕获/恢复成功不替代业务验收。

严格 collector 不放宽，不修改/重收历史 progress。

## 狭窄工具与第二阶段

`verification/agy_stdout_reanalysis.py`、固定 JSON 配置、输出 schema 只进 sdist，不进 wheel、CLI、MCP 或 Skill。没有路径/UID/命令/stream 覆盖参数。第一阶段仅测试私有字节函数与合成密钥/向量。

未来唯一包：原 Archive `2026-10-08-LAB-FIRST-R-V2-LIVE-01/encrypted-capture/a357f09f-86a9-410e-9a76-32acf462f575`，只读 open.json、seal.json、stdout.enc，不枚举/读其他流。拒绝 reparse/symlink、多链接与漂移，核对固定长度/SHA、整个公开 manifest 哈希，以既有 v2 AAD 认证 seal，再只认证 stdout，核对帧数与 plaintext SHA。全流 SessionReader 不适用；其他流实际完整性仍未验证。

cipher=48333 bytes / SHA256 `841c86b0b9a7964b284b6bb1b2d23868f7cee3897f2cd08858f80b93b9798913`；plaintext=48283 / SHA256 `b65afdf658b6912aa741ece06b164532d50f65c7387587f6893166daaa819ed4`。公开绑定来自原 ARCHIVE_MANIFEST；第一阶段没打开真实 cipher/key。

独立 Review 通过且管理取得适用授权后，提供批准单及独立 raw SHA。单据恰好含 task_id、uid、author_confirmed=true、review=Passed、artifacts={code,config,schema 的 raw SHA}、max_key_reads=1、max_stdout_authentications=1、grant_ref。Reviewed source/runtime 固定，不能边解密边修代码；变更须重新 Review。批准单不由工具自产。

未来用冻结 Python 3.13 的 `-I -B` 执行冻结脚本，只有 `--approval <管理批准单绝对路径>`、`--expected-approval-sha256 <独立 SHA>`。依赖 cryptography / Windows keyring 的版本、安装来源/身份也须冻结。程序只查询 Bridge 专用 key 一次，无创建/备用 backend；key 仅驻内存，不承诺 Python/crypto 内存零化。

固定输出：`C:/Users/user/Documents/Codex-Scratch/LAB-AGY-LIVE-ADAPTER-REPAIR-01/stage-two`，必须预先不存在。独占创建目录并持久写 attempt.consumed.json 后才读三文件/key。失败也消耗机会、保留标记；目录存在就拒绝，无重试/替代 reader。成功只写 result.json；错误返回固定状态，无 traceback/异常正文。断电或人为删除不属于工具的强制能力，禁止删除和重跑。

## 输出与判读

NDJSON 仅解析一遍：总262144 bytes、每行65536、1024行、256 step、深度16、容器128、4096 nodes/行。过大/畸形/重复 JSON key/非有限数字拒绝。event 识别 init/step_update/result；step_index 关联 ACTIVE/DONE，多次 ACTIVE 可属同一 step；重复 DONE、回退、跨 conversation、命令冲突为 Conflict；缺 init/result/DONE 或末尾换行为 Incomplete。事件行数不等于工具调用次数。

只识别 `step_update.tool_info.parameters.CommandLine`。有限工具类别外为 Unknown；未知键和值不输出。命令只在内存与冻结 recipe 哈希比较，输出 reproduce/regression Match/Mismatch/Unknown；不输出完整命令或命令哈希。配置仅登记六种引用/斜线形式，其他等价拼写也可能 Mismatch；不运行 Shell 解析或命令。init cwd 比较单列，不证明工具 cwd；argv、工具 cwd、Shell 缺失仍 Unknown。可选 tool_info.exit_code 只接受有界整数，仍为 CliDeclared；这个合成覆盖的扩展字段不是官方保证，从不从 output/error.message 猜退出码。

schema 只允许行号、raw-event SHA、已知类别计数、step 顺序/状态/类别、recipe 比较与必要声明退出字段及固定 Unknown/null。没有 source/text_delta/tool output/error.message/account/key。actual_invocations=null，management_decision=null。声明匹配也不证明 OS 实际执行、host composition 或 R Accepted。

2026-10-08 官方字段参考：[更新控制](https://www.antigravity.google/docs/cli/troubleshooting/#resolve-self-updater-locks-and-failures)、[原生事件](https://antigravity.google/docs/cli/headless/#streaming-json)。文档不是本机实测。
