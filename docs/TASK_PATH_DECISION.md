# TASK_PATH_DECISION：集中绝对路径规则

状态：集中方案内的实施选择，候选待独立 Review；不代表 A 整包接受。
日期：2026-10-04。TASK_ID：LAB-TASK-PATH-CONSOLIDATE-01；管理：019fe10b-df55-7b82-a9ba-3702dc08c55f。
精确 base：de1bea7aeafc36a93c255df78de7d7599f8efa1a。
作者对两轮自动修复停止后的集中处理明确授权；本轮为新的集中修订，由原 Reviewer 转任实现者。
后续独立 Review 必须另派未参与实现者。

## 范围和采用理由

只修改 task_input.py、test_task_input.py 和本文；公共 JSON schema、CLI、依赖锁和其他模块保持本轮冻结范围。
此前相对条目有统一组件规则，绝对入口却仅拒绝 dot/parent，再按 Path 拼写判断宽根。
集中复用现有组件检查和 Python 3.13 标准库，不为每一种 Windows 别名另造补丁。

核验 2026-10-04：[Microsoft 文件/路径命名](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
说明 Win32 命名和设备命名空间、尾点/空格、保留名及其扩展形式。
[Python 3.13 os.path](https://docs.python.org/3.13/library/os.path.html#os.path.samefile)
提供 Windows 文件身份比较；samefile/samestat 使用 stat 身份，stat 失败会抛出异常。
采用组件合法性拒绝和实际身份比较，不调用 abspath/resolve 来修正调用方输入。
采用 ntpath.isreserved 补齐 Python 3.13 的 Windows 保留名识别，保留原组件的长度和字符检查。
它是标准库近似规则，不能据此声称覆盖所有未来 Windows 命名变化。

## 三阶段规则

1. 所有外部绝对入口共用合法性函数。仅接受 ASCII 盘符加根分隔符的本地绝对路径；
   拒绝 UNC、扩展/设备命名空间、相对和 drive-relative 形式。
   在 str 构造成 Path 前检查所有非 anchor 原始组件；Path 入口按其现有拼写检查。
   复用组件规则拒绝 dot/parent、尾点/空格、ADS 冒号、保留设备名、非法字符、孤立 surrogate 和超长组件。
   普通大小写、正反斜杠分隔符、中文/其他可编码 Unicode、冗余分隔符可保持原 Windows 语义；不 strip、resolve 或改名。
   Path 构造已折叠的 dot 和分隔符无法恢复，不能宣称拒绝其原始文本；残留 parent 仍拒绝。
2. 在任何实际目录身份比较前，检查目标自身及完整原链的 reparse 属性。
   检查不跟随 resolve 后的路径，不丢原链证据；写入、失败标签、发布和读取继续按动作重核。
3. 对存在的输入目录及 sealed 读取根拒绝明确禁止根：盘符根、home、home.parent、Desktop、Documents、Downloads。
   先用词法相等，再 stat + samestat 比较物理身份；只读取这些根的元数据，不枚举其内容。
   禁止根 FileNotFoundError 表示当前缺失，可略过；PermissionError 和其他 I/O 异常保留 cause 并失败，不能当作不同身份。
   新输出叶必须合法、目标全新，父目录存在且原链普通；不对其祖先作宽根相等拒绝，允许合法 Documents/Scratch 子目录。

源路径仍严格为 schema 中 str；snapshot_root 仍为 Path，不增加输入类型。
非法相对源保持 InvalidSource、非法 snapshot 参数保持 SnapshotRootInvalid；非法绝对拼写/宽根/reparse 使用 PathRejected。
I/O 错误经既有入口映射为非敏感 IoFailed，不打印根路径或异常正文。
本方案是点时检查，未消除父链检查后的并发替换；不新增句柄沙箱、路径框架或 VM。

## 成组回归矩阵（先冻结，再实施）

每列为对应公共入口的路径字段。文件列使用普通 ZIP/可信清单 fixture，目录列使用普通窄根；其他参数冻结正确。
Path 已折叠 dot 的事实单独检查，不把无法检测的原始拼写算拒绝。

| 类别 | Git root str | directory root str | ZIP path str | manifest_path str | snapshot 输出 Path | snapshot 读取 Path |
| --- | --- | --- | --- | --- | --- | --- |
| 普通窄路径 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| 大小写/分隔符 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| 中文/非 ASCII | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| 原链 junction | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝、target 零写入 | 拒绝 |
| 原始 dot / parent | 拒绝 | 拒绝 | 拒绝 | 拒绝 | parent 拒绝；dot 已折叠单列 | parent 拒绝；dot 已折叠单列 |
| 尾点/尾空格（叶和祖先） | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| 保留名/ADS/非法字符 | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| UNC/设备命名空间/相对 | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| 禁止目录同物理身份 | 拒绝 | 拒绝 | 不把普通文件父目录误拒 | 不把普通文件父目录误拒 | 既有目标拒绝；新窄叶通过 | 拒绝 |
| 禁止根缺失 | 窄根通过 | 窄根通过 | 普通文件通过 | 普通文件通过 | 窄输出通过 | 窄读取通过 |
| 身份检查 Permission/I/O 错误 | IoFailed | IoFailed | 普通文件不作目录身份比较 | 同左 | 不存在叶不作身份比较 | IoFailed |

机制测试使用真实普通目录 stat 身份，另以明确标注的定向注入覆盖元数据错误分支及身份命中。
F1/F2/F3 另在本任务新 Scratch 做真实 Windows 回归：junction、合成 home dot/parent、home 尾点和尾空格。
仅 mock Path.home 可构造禁止根；不读取真实宽根内容，不改宿主映射/权限、不复用旧 fixture 写入。
8.3/subst/映射盘/DFS 的真实别名实例未测；统一 stat 身份机制覆盖该类判断不等于这些环境已逐项验收。

## 验证与交接

保留全部旧测试。执行定向和全量 JUnit、ruff、代码格式；全仓 Markdown 基线漂移独列，保留失败和最终证据。
结果入口：C:\Users\user\Documents\Codex-Archive\2026-10-04-LAB-TASK-PATH-CONSOLIDATE-01\INDEX.md。
测试/fixture/helper 写本任务 Scratch，原 Reviewer 与实施者工作树、旧证据不改不删。
自检只是实现证据；剩余 A 包目录/分母/跨来源/deadline/bytes/control/read_snapshot/维护性完整 Review 仍待独立执行。

## 本轮落实与自检

- `_validate_absolute_path`：六类外部入口及动作重核共用原始组件规则；str 原始 dot 拒绝，Path 已折叠 dot 的正例单列。
- `_assert_plain_target`：合法性之后检查目标和完整原链；staging/source、metadata 写入、失败标签、发布和读取按动作检查。
- `_reject_broad_root`：普通链检查后，用真实 stat + samestat 判定存在目录身份；FileNotFoundError 单独略过，其他 I/O 失败保留 cause。
- 成组单测包含 160 项新增用例，旧 50 项保持；本工作树离线锁定环境定向 210/0失败/0错误/0skip，全量 439/0/0/1，即 438 passed。
- 新 Scratch 真实 Windows F1/F2/F3 复验通过；普通元数据身份命中实测通过，Permission/I/O 和发布观察错误分支明确为注入测试。
- ruff 和 src/tests 格式通过；全仓格式仍仅基线 TASK_WORKSPACE_CONTRACT.md 漂移，文件未改。不称全部门禁全绿。
- 最初的新标签测试误期待 LF，已按既有 Windows 换行更正；复用开发环境缺安装元数据的失败经本工作树离线锁定同步纠正。原始失败和最终证据均归档。
