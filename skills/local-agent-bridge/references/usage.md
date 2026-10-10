# Local Agent Bridge 参数与输出参考

本文件随 Skill 安装，不依赖仓库外绝对路径。命令与参数以当前安装 CLI `--help` 实测为准；本 Skill 不安装、不升级、不登录、不改配置、不初始化密钥。

## 安装位置与版本

Windows 常见位置：用户级工具目录、`%APPDATA%\uv\tools\bin`、某个 venv 的 `Scripts\`，或用户/部署回执给出的精确路径。先确认入口存在并记录路径，再运行 help。

CLI 没有 `--version`。需要版本时读包元数据：

```bash
python -c "import importlib.metadata as m; d=m.distribution('local-agent-bridge'); print(d.version, d.metadata['Requires-Python'])"
```

## Task v1 工作流

新日常任务树优先使用五条固定命令：

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
- agy 配置生命周期是原字节备份、精确受控增量、finally 恢复；恢复失败不算成功。Cursor 项目权限来自冻结模板，`--force` 不等于目录隔离。
- Worker/CLI 自述与 OS 执行事实分开。管理验收看交付范围/完整性、受保护文件不变、独立固定测试、宿主终态、加密采集和配置恢复；Unknown 不自动判为通过或违规，可见越范围证据必须处理。
- `collect`/`task collect` 产物仍是候选，不自动应用、不推送、不创建 PR。失败现场保留，不自动重试、不换模型、不建第二个 job。
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
| Legacy 源文件被拒 | 旧 slice 合同只支持既有文本；Task v1 才支持授权树内增删改重命名 |
| 路径越界 | 核对任务读写/保护根和解析后路径；不放宽权限 |
| 缺 key | 需用户显式授权 `session-key-init`；普通运行不自动创建 |
| `over_limit` | 保留完整/受保护包，不清理未知文件或绕过滚动规则 |

## 上游版本与权限排障

启动失败、参数不识别、模型缺失或输出异常时，先核对本次解析到的入口、实际后端版本/模型目录和最近成功记录；区分 Bridge 包版本、启动器版本和后端版本。非推理探测也可能触发厂商自动更新，不承诺零写入。哈希变化先确认预期来源，再刷新本次冻结依据；不直接覆盖旧证据。

权限问题先区分审批模式与文件访问规则。自动批准/完全访问不一定取消显式 deny，冻结副本也不是 OS 隔离；检查实际配置位置、作用域、优先级和加载证据。不要把模型自述当强制证明，不要为绕过失败改全局配置；维护或更新始终另项授权。
