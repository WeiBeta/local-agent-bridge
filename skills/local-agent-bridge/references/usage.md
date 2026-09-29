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

## 不要做的事

- 不安装、不升级、不登录、不改 `settings`、不改主机配置；不在测试中触发真实 agy/H3/provider。
- 不重复提交、不自动换模型、不为失败运行创建第二个 job。
- 不把上游模型路由当作实际模型身份的证明；用量与费用不可观测时如实说明。
- 不擅自应用 `run` 的产物；它只是候选，需验收。

如需更多背景，可在用户已安装 Bridge 的源码或发行包内查找 `docs/BRIDGE_USAGE.md`、`docs/SESSION_STORAGE.md`、`docs/SHADOW_USAGE.md`；那只是可选背景，本文件已含调用所需内容。
