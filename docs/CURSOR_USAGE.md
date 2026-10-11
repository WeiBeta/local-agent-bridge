# Local Agent Bridge Cursor 固定入口（内部候选）

适用 Windows 11 / Python 3.13。`local-agent-bridge cursor run` 对一个已由 `prepare` 冻结的任务根执行**恰好一次**固定 Cursor CLI 调用，并把可取得的输入与两条管道原字节写入本产品加密会话（sessions 域）。本入口不解析模型事件、不改写/恢复任何 settings 文件、也不接受调用方的 argv、模型、URL 或额外路径。

## 命令

```text
local-agent-bridge cursor run --task-root <dir> --run-root <new dir>
                              --exe <agent.ps1 绝对路径> --exe-sha256 <64位小写hex>
                              [--execute]
```

- 缺省为 preflight：零写入、零启动，输出内容无关 JSON（含 launcher/config 哈希、固定 argv 概要、`execution_authorized=false`）。
- `--exe/--exe-sha256` 复用 `run` 的本地受信启动器模型：调用方给出绝对路径与 SHA-256，身份不符即拒。**哈希只绑定字节身份，不证明官方来源，也不构成 OS 级隔离。**
- 内部 argv 固定为：`pwsh -NoProfile -NonInteractive -File <exe> --workspace <task_root>/work -p --model grok-4.7-high --output-format stream-json --force <prompt>`；`prompt` 为冻结 `work/TASK.md` 去掉一个尾部 LF 的 UTF-8 文本。观察/收束时限与 `run` 相同（1020s/30s/30s）。

## 项目权限配置合同

Task v1的Cursor通路与agy共用1–3600秒工作上限，覆盖全部已有Coding/Review角色；较短显式预算继续约束剩余等待。Cursor的Task argv沿用已有参数，不猜测或添加native超时flag。进程提前退出即进入封口/回执；阶段收集和恢复宽限另计，不把3600秒当全工具总时限。本页旧`cursor`切片入口保持1020秒默认观察和各30秒收束宽限。真实一小时运行及上游内部期限尚未验证，配置隔离/并发不在本修订范围。

- 任务根必须经 `prepare --file .cursor/cli.json` 把 Cursor 项目配置作为**冻结输入**带入（实测与 manifest/额外文件校验相容；本适配器未旁路任何冻结核验）。
- 适配器只记录该文件的 SHA-256；启动前漂移（含 TASK.md、manifest、launcher）即拒绝。**适配器不解释 allow/deny 规则语义**——工具范围治理由调用方预置的 `cli.json` 与 Cursor 本体负责。
- 无 agy 式 settings 回写/恢复生命周期，也不设置 `AGY_CLI_DISABLE_AUTO_UPDATE`。

## 捕获与结果口径

- 四流进 sessions 域 v2 加密会话，seal metadata `kind=cursor_cli_one_call`，含模型、launcher/config/manifest 哈希与退出码；运行根仅 `plan.json`（内容无关）与 `run.json`。
- **退出码 0 只表示"单次启动生命周期完成且捕获完整封口"**，不表示模型任务成功，更不表示编码工作正确；子进程非零退出被如实记录（`process_exit_code`），生命周期完整时仍为 0。2=受控拒绝（启动前）；3=生命周期未完成或证据失败。
- 事件级判定（工具配对、权限拒绝等）属冒烟探针范围，**不在本入口**；本入口不宣称任何工具包含或文件隔离能力。

## 执行回执版本（离线候选）

LAB-LEGACY-LAUNCH-RECEIPT-02新生成的execute stdout摘要及`run.json`使用`schema_version=2`；preflight、`plan.json`保留v1，sessions加密格式继续既有v2。历史v1回执保持原字节与原含义，不重写、不迁移或补出unknown。

`launches=0/1/null`取自同一次调用方持有的共享生命周期事实：确证未执行/确认执行/潜在执行未确认。捕获返回存在与否不决定这个数，确认后失败仍为1；null不能当0、成功或自动再尝试。顶层`spawn_state`仍只用confirmed/not_confirmed，后者包括未知；准确区分以launches为准。正常`launch`capture记录形状保持，异常没有capture返回时使用既有生命周期记录作为fallback，保留stage/PID/cleanup及未观测的null。

未知或启动后异常保留`result=launch_failed`及非成功退出，捕获失败仍为capture_incomplete；子进程非零退出在已确认、完整封口的正常路径仍保持原有退出码口径。原中断在尽力回执后传播，次生写入/封口错误不替换它。没有新增CLI参数、配置改写、调用或重试。

仓内没有读取旧Cursor执行回执的产品解析器；task collect的独立合同明确拒绝此schema。外部读取器必须支持v2或明确拒绝未知版本，兼容性未核验。本包仍需新的独立Review，既有Cursor历史冒烟证据不自动接受这次变化；未运行真实CLI/provider/help/version/配置密钥/部署。归档入口见[BRIDGE_USAGE.md](BRIDGE_USAGE.md)的本任务索引。

## 边界（如实声明）

- Shell/MCP/WebFetch 拒绝、一般文件隔离、上游模型真实身份、请求数与费用均未验证；`--force` 会放行未显式拒绝的命令（官方文档），不能把 `cwd`/Job 当文件隔离。
- 既有合成冒烟证据见 [CURSOR_EVIDENCE.md](CURSOR_EVIDENCE.md)：一次冻结捕获经已审解析器认证重析通过，**不构成真实 coding 能力替代结论**。
- agy `run` 默认行为与 H3 入口不变。
