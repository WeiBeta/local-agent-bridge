# LAB-AGY-HOST-HELP-FORMAT-REPAIR-01

2026-10-14 / Asia/Shanghai。结论：**离线修复自检通过，普通全量存在已复现的基线红项；未独立接受、未实测或部署。** 下一门禁为管理安排的 fresh 独立 Review。Cursor 继续暂停。

## 冻结与变更

已完整读取管理树 WORK_LEDGER 最新「HELP-DIAG核收／实际宿主格式修复冻结」节及适用 AGENTS/治理。HOST-HELP-FORMAT 为新根因链第一轮；旧声明枚举链两轮已关闭的历史不重置。任务路由按冻结为 Sol 6.1 / xhigh，回执目标 `019fe10b-df55-7b82-a9ba-3702dc08c55f`。

新 worktree `C:/Dev/ask-ai-mcp/worktrees/agy-host-help-format-repair-01`，branch `codex/agy-host-help-format-repair-01`，base `116cbf9ba2425194527f04c5b43e78fdbdcef08e`。正常 Git 创建，不修改原 `agy-upgrade-decouple-review-03` 审查树。交付为普通本地单主题提交，最终 HEAD/tree/文件 SHA 在本任务 Archive 的 HANDOFF.json 中绑定，本报告不内嵌自身提交哈希。

代码仅改 `src/local_agent_bridge/bridge/agy_host.py`；配套改 `tests/test_agy_host.py`、新增 `tests/fixtures/agy-help-1.3.4.txt` 及本报告。必要文档增量为 `docs/BRIDGE_USAGE.md` 的 Help 投影/格式/重复策略说明，与 `docs/RELEASE_CHECKLIST.md` 的复核矩阵及源码包夹具缺口。没有修改 launcher、WinJob、Version、schema、权限、额度、其他宿主、pyproject/lock、生产/运行安装/工位/Skill/远端。

之前同一真实帮助字节仅在 stderr 时，原 observe 投影空 stdout，报缺七项；单独投影其正文仍因无参数占位符报缺六项。现有纯解析和 fake launcher 观察均支持该实际布局及两个输出通道，仍不证明真实 CLI 实参、权限或业务结果。

## 解析与重复策略

- Help 在原完整 capture、launch_count、exit、timeout、截断与 cleanup 门禁之后，将 stdout + LF + stderr 投影给 missing_flags。原双流共享 256 KiB capture 限制与原执行/cleanup 预算保持；Version 仍只读 stdout。
- 保留旧 `<...>` / `[...]` 参数、alias、wrapped labelled enum 语法，原 `_declared_choice_tokens` 不改。额外识别 `Usage of agy.exe:` 后连续的缩进 option/description 表；短 alias 行允许存在，但不补造 long-option 声明。出现该 Usage 标题时，表外浮动选项示例不能作为 required 声明。
- Usage 的 effort/output-format 从各自声明行第一个完整 comma/pipe 括号枚举核 high/stream-json；不从 default、任意描述词、其他行、续行或未来说明补齐。没有为未知厂商布局建立通用框架。
- Usage 重复比较折叠空白后的整行描述；legacy 比较参数形态与显式枚举集合（未声明枚举与已声明不同）；boolean 比较首行描述。重复一致允许，任何不兼容项或不同签名保守拒绝，不按先后覆盖，混合格式不推断等价。
- 拼接旧帮助时，第二份文档的顶层 `Options:` / `Usage of agy.exe:` 标题不属于前一声明的 enum metadata。

AST 比较确认除 missing_flags、observe 的 Help 输入及两项新私有 helper 外，模块原常量、类与函数不变；observe 只替换 Help 输入表达式后与 base AST 一致。task_run、slice_run、winjob、schema validators 与原门禁未修改。

## 真实夹具与换行

来源为已管理核收的 `2026-10-14-LAB-AGY-HELP-DIAG-01/stderr.help.txt`，日期 2026-10-14；有限秘密模式扫描命中 0 的原始 help 字节。源 REPORT `287adb921e3a8a81ffce376496fa730914ebf4e9c3b25ecde8890bf70f12e6fa`、HANDOFF `68e15dc1c00311b5d576e30d8c7063c959d1b0235cc173a8f906ac3509d55543` 已核，不恢复 LIVE-03 未存档的历史原文。

fixture 的源、工作文件与 Git blob 均为 2905 字节，SHA256 `337622c6dcdcb204312277570c4173dda83f3cbf006629f0eabe657069071e7c`，Git blob `953db6784a1a34593ab744e7e1382f8bfeda0499`。仓库已有 core.autocrlf=true，过滤 checkout 会得到 39 组 CRLF、2944 字节、SHA256 `0a9935ac5b87c7477eee4f9a3e6ceb2878e8870e15c12b982d2fe003e1b48881`。测试仅对读取副本做 CRLF-to-LF，随后核原字节数/SHA；实际 CRLF 情形另有回归。没有改 Git 配置或原来源字节。

## 验证结果与保留失败

复用 base 审查树已存在的 `.venv` 作为只读依赖输入，以 `uv run --no-sync --active --offline --no-cache` 与 candidate src 的 PYTHONPATH 执行。74 个 installed distribution 版本与两树相同 uv.lock 核同；Python 3.13.14、pytest 9.1.1、ruff 0.16.1。禁止 bytecode/cache 写入旧树；pytest 临时根与输出均为本 ID Scratch。无 sync/install/resolve/真实宿主 CLI/model/key。

| 检查 | 结果 |
| --- | --- |
| 初轮 focused | 118 passed / 5 failed；原 XML/日志保留 |
| 文档边界修正后的 focused | 127 passed，exit 0 |
| 最终 focused（含 checkout 转换） | 128 passed，exit 0；原 75 项 + 新 53 项 |
| 普通全量原执行 | 3041 passed / 1 failed / 1 skipped，JUnit time 1172.220 秒；未重复全量 |
| 冻结 base 上唯一红项 | 1 failed，exit 1，同样 KeyError: contract_version |
| ruff check . / format --check . | 最终均 exit 0；92 个 Python 文件格式通过 |
| 最终 collect 与测试节点核对 | 3044 节点；原全量 + 最终 focused 的节点并集精确相等 |

普通全量开始后，生产代码未再修改；之后只补了 fixture checkout 读取转换及其一项测试、追加文档。原执行收集 3043 节点；最终额外一项由 focused 覆盖。节点并集核对说明覆盖范围，不把全量的一项失败或一项 skip 改成通过。

全量的 180 秒外层包装器发生 TimeoutExpired/exit 1；原 pytest 继续至 JUnit 完整落盘，没有手工终止或重新启动。按精确路径、PID/parent、创建身份与本任务 argv 核对后，事件式收取原进程退出。GetProcess 的 ExitCode 读得 null，保持 NotRecorded，不由 JUnit 或包装器退出推定 native exit。外层超时与后续测试结果分别保留，不把它改写为外层成功。初次等待校验把 WMI 微秒创建时间当成 FILETIME 精度严格比较，因 8 ticks 差异被拒；核同 WMI 创建值、命令归属/路径/parent 与实际 FILETIME 后才收取原退出，无进程操作。

唯一全量红项为 `tests/test_first_task_r.py::test_installation_verifier_checks_real_fixture_bytes_and_origin[none]`，该合成 receipt 缺少 contract_version，经 `verification/first_task_r.py:347` 到 `task_run.py:1096` 抛 KeyError。冻结 base 的同一项离线复现相同失败；三个相关文件均与 base 不变，未扩改。本项不是帮助格式修复的通过项，也没有据此修改 receipt/schema/runtime。

初轮 focused 的五失败来自新重复比较将第二份 `Options:` 当成第一份最后一条声明的枚举标签；已在本轮实现中补文档边界，旧枚举 helper/回归保留。另保留依赖核对包名点号未做 PEP 503 归一的首轮 assertion，以及统计脚本误猜新增测试数量的 assertion；二者为核对工具错误，不计为产品测试失败。更正后记录实际数，不删除红材料。

## 源码包缺口与下一门禁

当前 pyproject 的 sdist only-include 已包含 test_agy_host.py，但没有新 fixture 路径；因此源码 worktree 自检不代表源码包中的新测试闭合。pyproject 不在本单冻结允许路径内，未修改。最窄补项为只将 `tests/fixtures/agy-help-1.3.4.txt` 加入 only-include，再核实际源码包；建议见 PACKAGING-GAP.json 与发布检查表，由管理安排适用路径及后续验证。

管理下一步 fresh 独立 Review，另裁定基线红项和源码包配套。真实续测、安装/部署、生产/集成接受均 NotRun；本次不能追认 LIVE-03 或旧证据，不自动恢复 Cursor，也不自行派工或重试业务。

本任务 Scratch/Archive、所有 pytest 临时材料、旧失败/诊断、原审查树和已存在 `.venv` 保留。Archive INDEX/MANIFEST/HANDOFF 绑定关键文件与哈希，根 INDEX 仅登记本任务。没有清理或到期删除；后续删除须核引用、精确目标和授权。单次主动终态回执管理，送达不等于验收。
