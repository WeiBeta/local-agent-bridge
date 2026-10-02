# Local Agent Bridge 参数与输出参考

本文件随 Skill 安装，不依赖仓库外的绝对文档路径。命令与参数以当前 CLI `--help` 实测为准（核验版本 `0.1.0.dev0`）。

## 安装位置怎么找

CLI 是 `local-agent-bridge`（切片桥）与 `local-agent-bridge-h3`（H3 MCP，**本 Skill 不使用**）。Windows 上常见位置：

- 用户级工具目录：`%USERPROFILE%\.local\bin`、`%APPDATA%\uv\tools\bin`
- 某个虚拟环境的 `Scripts\`（如项目 `.venv\Scripts`）
- 用户明确给出的路径或部署回执里记录的路径

先确认可执行文件存在并记录其路径，再跑 `--help`。**不要**把某一台机器的绝对路径写进脚本当作通用要求。

## 版本

CLI 没有 `--version`（传入会被当作未知命令）。读包元数据：

```bash
python -c "import importlib.metadata as m; d=m.distribution('local-agent-bridge'); print(d.version, d.metadata['Requires-Python'])"
```

## 子命令与参数（实测）

```text
prepare [-h] [--repository REPOSITORY] --commit COMMIT --file FILE
        [--editable EDITABLE] --task-note TASK_NOTE --out OUT
collect [-h] --task-root TASK_ROOT
plan    [-h] --task-root TASK_ROOT
run     [-h] --task-root TASK_ROOT --run-root RUN_ROOT --exe EXE
        --exe-sha256 EXE_SHA256 --settings SETTINGS [--execute]
shadow  {fingerprint,snapshot,replay,compare} ...
session-status      （无参数）
session-key-init    （无参数，写 Credential Manager）
```

`--repository` 缺省是当前目录；`--file` 可重复以给出多个文件。`shadow` 子项：

- `fingerprint {sessions|shadow} uid`
- `snapshot uid input_sha256`（写入 shadow 域并占用其滚动额度，不是只读操作）
- `replay {sessions|shadow} uid input_sha256`
- `compare {sessions|shadow} first_uid first_input_sha256 {sessions|shadow} second_uid second_input_sha256`

uid 必须是规范 UUID，摘要必须是小写 64 位 SHA-256，否则拒绝。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 生命周期完成且配置已恢复；**不代表模型任务成功** |
| 2 | 未改配置、未启动的受控拒绝（含未知命令与缺参数）；输入捕获拒绝时可能已留下运行根、计划及私有配置备份 |
| 3 | 生命周期未完成，或证据无法落盘 |

## `run` 的行为边界

- 缺省只预检：不写文件、不启动进程；`--execute` 才执行**一次**固定调用。
- `--exe` 必须是绝对路径且与 `--exe-sha256` 匹配；身份不符即拒绝，未知可执行文件绝不启动。
- argv、模型、effort、`--output-format stream-json`、`--disable-slash-commands`、`--print-timeout` 全部由代码固定，调用方无法覆盖。
- 配置生命周期：原字节备份 → 精确插入读写规则 → `finally` 内恢复；恢复失败时该次运行不算成功。
- 运行根必须全新且不复用，且不得位于任务根或安装包目录内。

## 输出与产物

- `collect` 输出单行 JSON 摘要与 unified diff（按 LF 拆行，不给文件补换行）。
- `plan` 输出固定主机运行计划，含 `execution_authorized=false`。
- `session-status` 输出 sessions/shadow 两域的**文件长度**用量、上限、封口数；该上限是目录内文件长度之和，不是 NTFS 簇或磁盘可用空间。
- `run --execute` 的输入与 CLI 原字节写成本产品独立密钥的 AES-256-GCM 加密会话；`capture/` 不留明文管道副本；任务副本与 `settings.*.bin` 仍可能是 ACL 私有明文。

## 常见拒绝与处理

| 现象 | 原因与处理 |
| --- | --- |
| 源文件被拒 | 只支持**既有文本文件**；新增/删除/重命名/符号链接/子模块一律拒绝 |
| 路径越界 | 访问必须在白名单根内；盘符根与宽泛用户根会被拒 |
| `plan` 报工作树不干净 | `plan` 要求任务根未被修改；先 `collect` 查看改动 |
| 缺 key | 需用户显式运行 `session-key-init`；缺 key 在启动前拒绝，不会自动创建 |
| `over_limit` | 会话/影子域容量不足；只有完整、无引用且复验通过的整包才可能被滚动，受保护项存在时停止新写入 |

## 上游 CLI 版本排障（出现故障时按需读）

允许厂商自动更新，不要求用户长期锁死版本。必要时使用厂商支持的手动更新方式；本调用 Skill 只诊断并提出更新建议，更新由单独授权的维护步骤执行，不在活动任务中更新。

- 启动失败、参数不识别、模型缺失或结果解析异常时，先核对实际启动路径、上游 CLI 版本及相关 `--help`/模型目录，与最近成功记录比较。上游支持时用其版本命令，而不是网络 ping；Bridge 本身仍用上文包元数据。非推理探测也可能触发厂商自动更新，不承诺零写入。
- 区分 Bridge 包版本、启动器版本与实际后端版本；PATH 多份安装、旧快捷入口或启动器自动选择新版，都可能让路径/启动器哈希不变而后端已变。无需扫描整机，优先检查本次解析到的入口。
- 模型缺失可能来自旧 CLI 未支持新模型，也可能是账户权限、地区或服务端开放范围。核对厂商说明及实际模型目录；不能把“更新可解决”当作已证实原因，不能用更新反复试探 Free plan/订阅拒绝。
- 哈希变化先确认是预期官方更新，再刷新本次预检依据；不直接用新哈希覆盖旧冻结证据。新参数或输出结构变化做对应小样例/离线解析回归，不因版本号变化自动重审全项目，也不忽略未知输出冒充成功。
- 发生中途更新、超时或输出不完整，先核对已有运行与捕获，确认是否已执行；保留本次失败记录。手动更新成功不等于模型调用成功，也不自动授予第二次真实调用。

本次排障只记实际路径、可得版本、必要哈希、错误类别与检查结论；不建常驻版本轮询器。Antigravity 旧版导致模型缺失目前作为排查假设，不作本机已证实缺陷。

## 不要做的事

- 不安装、不升级、不登录、不改 `settings`、不改主机配置；不在测试中触发真实 agy/H3/provider。
- 不重复提交、不自动换模型、不为失败运行创建第二个 job。
- 不把上游模型路由当作实际模型身份的证明；用量与费用不可观测时如实说明。
- 不擅自应用 `run` 的产物；它只是候选，需验收。

如需更多背景，可在用户已安装 Bridge 的源码或发行包内查找 `docs/BRIDGE_USAGE.md`、`docs/SESSION_STORAGE.md`、`docs/SHADOW_USAGE.md`；那只是可选背景，本文件已含调用所需内容。
