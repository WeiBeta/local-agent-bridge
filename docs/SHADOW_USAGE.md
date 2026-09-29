# Local Agent Bridge 离线影子回放（内部候选）

适用 Windows 11／Python 3.13 的本地已封口 v2 会话。此命令读取加密证据、提取可解析事件的有限字段，并可保存自包含的重新加密快照。它不会执行事件中的命令，不启动 agy、模型、Docker 或 H3，也不能推断未出现在 CLI 管道里的隐藏能力。

## 命令与输入核验

`local-agent-bridge shadow --help` 列出四种操作；命令只接受固定域名、规范 UUID 和小写 64 位 SHA-256，没有任意状态根、可执行文件、模型或权限参数。

```text
local-agent-bridge shadow fingerprint sessions <UID>
local-agent-bridge shadow snapshot <UID> <INPUT_SHA256>
local-agent-bridge shadow replay sessions <UID> <INPUT_SHA256>
local-agent-bridge shadow replay shadow <SNAPSHOT_UID> <INPUT_SHA256>
local-agent-bridge shadow compare sessions <UID_A> <INPUT_SHA256_A> sessions <UID_B> <INPUT_SHA256_B>
```

`fingerprint` 先验证封口与全部四流，再输出内容无关的输入摘要。摘要为 v2 前缀加上 `task` 和 `request` 各自字节长度、SHA-256 的规范 JSON 再取 SHA-256；所有 replay、compare、snapshot 均要求调用者显式提供它，并逐项与已验证包比较。`fingerprint` 自同一包得出的值只是操作用等值门禁，不是外部输入来源的独立证明。快照响应中的 UID 是新的 shadow 包 ID；来源 UID、来源 seal SHA-256、输入摘要和四流长度／哈希保存在认证清单中。

`snapshot` 先验证来源 sessions 包，逐帧读出后按 shadow 域重新加密四流，再复验来源清单和 seal 哈希后封口。`replay shadow` 只依赖 shadow 包，不要求来源仍在 sessions 域。快照不创建原会话的永久引用，因此原会话仍可按既有规则滚动。未封口、旧 v1、跨域直接复制、错摘要、篡改、截断或容量不足均拒绝；中断留下的 `.partial` 继续计入预算，不自动删除。失败只输出 `state=refused` 和无内容的原因类别。

## 输出与比较口径

回放结果仅含域与 UID、输入／输出哈希、来源摘要、已封口元数据中的进程退出码，以及可解析 stdout 事件观察。终态只把 `SUCCESS`／`ERROR` 显示为标签，其余状态只标为 `other` 并给出哈希；工具名和文件路径仅按已识别的 `tools`／`tool_calls`、`files`／`file_paths` 列表做去重数量与集合哈希，不回显原值。usage 只认非负整数的 `input_tokens`、`output_tokens`、`total_tokens`、`prompt_tokens`、`completion_tokens`、`cache_read_tokens`、`cache_write_tokens` 字段；未知或缺失字段不会凭空补齐。识别范围仅代表实际可见的事件字段，不代表全部调用、文件或模型能力。

`compare` 分别验证两个 UID 与各自显式输入摘要。输入不同则全部结果标为 `incomparable/input_differs`；缺失字段、解析失败或不支持的结构也明确为 `incomparable`。输入一致且两边都可观察时，逐项给出 `equal`／`different`，包含终态、拒绝／错误标记、工具／文件集合哈希、usage、退出码及 stdout/stderr 原字节哈希。自比仅证明同一证据摘要相同，绝不等于模型复跑成功、候选接受或独立 Review。

shadow 与 sessions 各有独立 `104857600` 字节文件长度上限；写前锁内重算，容量不足按完整、无引用且复验通过的最旧 shadow 包滚动。仅有部分、未知或篡改包时报告 `over_limit`，不清理旧材料。两个域共享本产品的独立会话密钥命名空间，但 frame/seal AAD 均绑定 v2 和预期域。旧 v1 样本原位保留且新读取器拒绝，不自动迁移或删除。**实机状态（2026-09-29）**：本包自带测试仍只以注入密钥与临时根做离线合成验证；另有一次真实 agy 运行产生的已封口 session，在临时隔离状态根下完成了离线 `snapshot` 与 `replay`（解析终态 `SUCCESS`、进程码 0、无拒绝或错误标记）。离线影子回放只是对同一份已封口证据的重新读取与比较，**不等于第二次模型复跑**，不构成模型能力、候选接受或独立 Review 的证据，也不会因此执行事件中的命令。仍未验收：生产或跨机部署、真实主机长期运行、并发与容量压力下的滚动行为、真实 provider 行为与上游实际模型身份。逐项证据与哈希见仓库内 `docs/reviews/LAB_LIVE_ACCEPTANCE_01.md`（报告不在本发行包内）。
