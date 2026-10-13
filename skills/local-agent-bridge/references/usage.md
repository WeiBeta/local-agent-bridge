# Local Agent Bridge 参数与输出参考

本文件随 Skill 安装，不依赖仓库外绝对路径。命令/schema 对照产品源码基线 `0e28d2bd09c88fcc2cecff9564eb6e2c8192db28`（2026-10-13）；目标安装按批准回执与获准的 help 核验。本 Skill 不安装、不升级、不登录、不改配置、不初始化密钥。

## 安装位置与版本

Windows 常见位置：用户级工具目录、`%APPDATA%\uv\tools\bin`、某个 venv 的 `Scripts\`，或用户/部署回执给出的精确路径。先按回执确认实际入口、wheel/运行身份与包元数据；版本字符串或目录名不足以识别安装。工单允许时再运行 help；禁止 CLI 查询时仅读文件资料。读取包元数据需使用该安装的解释器。

CLI 没有 `--version`。需要版本时读包元数据：

```bash
python -c "import importlib.metadata as m; d=m.distribution('local-agent-bridge'); print(d.version, d.metadata['Requires-Python'])"
```

## Native station dispatch

已配置 agy 工位的逐单完整链：

```text
task dispatch --spec <absolute-json-spec> --pool-registry <absolute-registry> --pool-sha256 <64-lowercase-hex> [--execute]
```

三个路径/摘要参数来自管理冻结材料。dispatch **没有** `--trusted-control-root` / `--trusted-inputs-sha256`；逐单 task、plan、trust 由产品生成，不用多步 run spec 代替 dispatch spec。

| 材料 | 版本与字段 |
| --- | --- |
| CLI spec | `cli_contract_version=1`；闭合字段为 `source`、`policy`、`instructions_path`、`instructions_sha256`、`task`、`admission_timeout_seconds`，另含该版本键 |
| registry | `contract_version=1`、`id`、统一 `control_root`、完整 `deployment_receipt` seed、`policy`、1..4 条 `stations` |
| station | `id`、`native_id`、`root`、`record`、`root_identity`；后者为 `st_dev`/`st_ino`；相同工位的调用共用 station ID/control root |
| 逐单 deployment receipt | `contract_version=4`，加入 `native_project` 与 `station_binding`；不能把 CLI spec 版本改成 4 |

`task` 恰含 `role`、`capabilities`、`read_roots`、`write_roots`、`protected_paths`、`required_outputs`、`acceptance_ids`、`deadline_seconds`、`source_output_bytes_limit`。角色只有 Coding/Review；Testing 为 Coding/execute 且 work 只读，Mixed 为 Coding 工程操作；Review work 只读，写入型测试放 scratch。能力为 execute/web_reference/prepare_dependencies，当前 station 任务的后两项必须 false。相对任务路径数组与验收 ID 按合同排序去重；deadline/output 服从 policy 上限，deadline 最多 3600 秒。入场 timeout 为 null 或 0..86400 秒，实际值仍按本次获批预算。

registry SHA 固定原字节，不能由 Worker 换算替代。默认 `PreparedOnly` 仅读 registry/任务说明、验证结构与 spec：`launch_count=0`、`task_root=null`、capacity 是注册数；未取得租约，未 materialize/import/run、未核验源包字节或实际执行能力、未读 key。已有 Project 配置不等于当前任务获执行许可。

`--execute` 只用于本次明确授权的任务。产品 admission/native mutex 管理空闲位与满位等待；选中工位后在 `root/jobs/<fresh UUID>` 完成 import/prepare/plan/run/collect/release，每单独立 request/root/result/capture 和新会话。调用方不手写 Accepted，不重置 state 或另建池绕过忙位。

`PreparedOnly` / `Collected` 的 CLI 退出为 0，其他 dispatch 结果为 2；中断/解析异常仍按 CLI 错误回执。control_complete、launch_count=0/1/null、宿主退出、业务 Candidate/Incomplete、管理 Accepted 分开记录。`Collected` 只表示本单收集与控制收尾，不等于业务成功。

## Task v1 多步工作流

管理供给分步 spec、可信控制根和 bundle SHA 时，使用五条固定命令：

```text
task import  --spec <absolute-json-spec>
task prepare --spec <absolute-json-spec> --trusted-control-root <absolute-root> --trusted-inputs-sha256 <64-lowercase-hex>
task plan    --spec <absolute-json-spec> --trusted-control-root <absolute-root> --trusted-inputs-sha256 <64-lowercase-hex>
task run     --spec <absolute-json-spec> --trusted-control-root <absolute-root> --trusted-inputs-sha256 <64-lowercase-hex> [--execute]
task collect --spec <absolute-json-spec>
```

Spec 由管理或调用方明确供给：`cli_contract_version=1`，字段随命令闭合；路径是未 trim/展开/折叠的绝对路径。import spec 含 source/policy/snapshot_root；prepare 含 snapshot/task-manifest/task-note/task-root；plan 含 task-root/host；run 含 task-root/run-root；collect 含 task-root/run-root/result-root。prepare/plan/run 的可信根和 bundle SHA 必须来自外部固定材料，不能写进 Worker 说明或由候选自算。

Task v1 Coding 在工单指定目录和允许文件范围内可做必要检查、哈希核对、编辑、本地测试与辅助脚本。管理配方是必需验收，不是完整命令白名单；冻结控制、验收配方与 protected_paths 不可修改。任务外写入、凭据、额外网络、依赖安装、生产与远端仍须单独授权。Task v1 支持授权 work 内普通新增/删除/修改/重命名；不要套用旧 slice “只改既有文本”的限制。

`task run` 缺省预检、不初始化 key、不启动；`--execute` 仅在明确授权后使用，一次一个。0 只表示对应命令的产品合同结果，不等于模型业务成功；2 表示 Blocked/Failed/收集或门禁拒绝，3 只属于旧 adapter 生命周期入口。Task plan Ready/Blocked 均可能分别以 0/2 返回原 Plan。

## Legacy source slice 工作流

旧小切片命令保留如下：

```text
prepare --commit <sha> --file <path> [--editable <path>] --task-note <path> --out <new-root> [--repository <root>]
collect --task-root <root>
plan    --task-root <root>
run     --task-root <root> --run-root <new-root> --exe <absolute-exe> --exe-sha256 <sha> --settings <absolute-settings> [--execute]
cursor  run --task-root <root> --run-root <new-root> --exe <agent.ps1> --exe-sha256 <sha> [--execute]
```

旧 slice 只支持既有文本文件；新增、删除、重命名、符号链接、子模块、跨根 diff 与二进制内容均拒绝。运行根必须全新，且不得位于任务根或安装包目录内。

## 运行边界与验收

- Bridge argv、模型、effort 和固定参数由代码决定，调用方不能覆盖；未知可执行文件绝不启动。
- agy 配置模式按 receipt 的实际绑定判断：无 `native_project` 的 settings Task 使用租约、原字节备份、受控增量和 finally 恢复；旧 slice 的 `--settings` 通路也有原字节恢复。含 `native_project` 的 Task（含 station v4）configuration 三项 null，不取 settings lease、不改全局设置；postflight 核 native id/root，`Unchanged` 表示未改，不能写成已恢复 settings。v1-v3 的同根 native 模式不等于 station 复用。Cursor 项目权限来自冻结模板，`--force` 不等于目录隔离。
- Worker/CLI 自述与 OS 执行事实分开。管理验收看交付范围/完整性、受保护文件不变、独立固定测试、宿主终态、加密采集和适用配置收尾；Unknown 不自动判为通过或违规，可见越范围证据必须处理。
- dispatch/`collect`/`task collect` 产物仍是候选，不自动应用、不推送、不创建 PR。失败现场保留，不自动重试、不换模型、不建第二个 job。
- 上游实际模型身份、token/费用通常不可观测；不要从路由名或退出码补猜。

## 其他固定入口

- `session-status` 只读输出 sessions/shadow 文件长度用量、上限和封口数；不读 key。
- `session-key-init` 显式写 Windows Credential Manager，仅在用户明确要求时执行。
- `shadow fingerprint/snapshot/replay/compare` 只接受规范 UUID 与小写 SHA-256；snapshot 写 shadow 域并占额度，不是只读操作。
- `local-agent-bridge-h3` 是独立 H3 MCP 入口，本 Skill 不使用。

## 常见拒绝

| 现象 | 处理 |
| --- | --- |
| Task spec 键/类型/路径不符 | 核对管理供给的严格 JSON 和绝对路径；不修改 spec 来绕过 |
| Trusted SHA 或控制材料不符 | 停止并保留现场；不重算、覆盖或换根 |
| Registry SHA 不符 | 停报并保留原 registry；不改 control root、station/native ID 或 state 绕过 |
| 工位 record/root 不可用 | 按产品 admission 结果核对：坏位可被跳过，健康位可继续；控制/绑定失败仅暂停自身位，不替产品修复或重置状态；Idle 文件不能代替 mutex 所有权 |
| Legacy 源文件被拒 | 旧 slice 合同只支持既有文本；Task v1 才支持授权树内增删改重命名 |
| 路径越界 | 核对任务读写/保护根和解析后路径；不放宽权限 |
| 缺 key | 需用户显式授权 `session-key-init`；普通运行不自动创建 |
| `over_limit` | 保留完整/受保护包，不清理未知文件或绕过滚动规则 |

## 上游版本与权限排障

启动失败、参数不识别、模型缺失或输出异常时，先核对本次解析到的入口、实际后端版本/模型目录和最近成功记录；区分 Bridge 包版本、启动器版本和后端版本。非推理探测也可能触发厂商自动更新，不承诺零写入。哈希变化先确认预期来源，再刷新本次冻结依据；不直接覆盖旧证据。

权限问题先区分审批模式与文件访问规则。自动批准/完全访问不一定取消显式 deny，冻结副本也不是 OS 隔离；检查实际配置位置、作用域、优先级和加载证据。不要把模型自述当强制证明，不要为绕过失败改全局配置；维护或更新始终另项授权。
