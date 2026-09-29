# Local Agent Bridge 会话存储（内部候选）

适用范围：Windows 11、Python 3.13；仅覆盖本产品实际可取得的一次 Bridge `run --execute` 输入与 CLI 管道。SHADOW 只离线读取和重新加密已验证的字节，不进行模型复跑或事件指令执行。

## 安装与状态

先由本机用户**显式**运行 `local-agent-bridge session-key-init`。它只在 Windows Credential Manager 的 `LocalAgentBridge.SessionCapture.v1` / `aes256gcm-session-v1` 创建 32 字节密钥；已有密钥不覆盖。普通 `run` 只读取该密钥；缺失、不可用、形状错误或非 Windows 后端时，在配置改动与进程启动之前拒绝。测试用独立注入 key 和临时状态根，不读取或写入真实 Credential Manager。

**实机状态（2026-09-29）**：正式 `session-key-init` 已在真实 Windows Credential Manager 上调用**恰好 1 次**，返回 `session_key_created=true`，产品读回并验证 32 字节 key；密钥**未导出、未输出**，未更换 keyring backend，未访问旧 API 凭据条目。同时完成了一次真实 Bridge 运行的四流加密封口，并在**临时隔离状态根**下完成离线 snapshot/replay；真实运行生成的 `settings` 备份可能含本机设置内容，不在会话域内。未验证：密钥轮换、多用户/多机同步、条目被外部破坏后的恢复。逐项证据与哈希见仓库内 `docs/reviews/LAB_LIVE_ACCEPTANCE_01.md`（报告不在本发行包内）。

`local-agent-bridge session-status` 只读显示 `sessions`、`shadow` 两域的文件长度总量、上限、seal 标记数和未封口数，最多列出 32 个未封口 ID 与省略数量；它不读取密钥、不验证 seal、不创建状态目录。此快照可与并行写入竞争，不能据此判定一个未封口包的进程是否还活动；写入决策以跨进程锁内的重新计量为准。

默认状态根为 `%LOCALAPPDATA%\LocalAgentBridge\sessions`；自包含影子快照独立使用 `%LOCALAPPDATA%\LocalAgentBridge\shadow`。两域各 `104857600` 字节上限，按**目录内文件长度之和**计量，并非 NTFS 簇分配字节。密文、帧开销、`seal.json`、`open.json`、`.quota.lock`、滚动收据、活动 `.partial`、失败残件、未知文件、引用标记都计入。目录自身长度不计。每个未封口包预留 4096 字节终态空间，域另预留 4096 字节收据空间；预留是预算，不是额外磁盘文件。写前取得同域 Windows 文件锁并重算，容量不足时不扩容、不明文回退。

该上限是**文件长度预算**，不是磁盘簇或分区可用空间承诺；两者可能明显不同，实际占用须以操作系统工具查看。

## v2 文件与完整性

每次运行使用新的 UUID 目录：`open.json`、`task.partial`、`request.partial`、`stdout.partial`、`stderr.partial`；完整时四条流改名为 `.enc`，最后写 `seal.json`。`.partial` 永不视为完整。每条流以 `LABFRAME2\n` 开头，随后逐帧为大端密文字节数（4 字节）、序号（8 字节）、随机 nonce（12 字节）、AES-256-GCM 密文及 16 字节认证标记；单帧明文不超过 65536 字节。新帧 AAD 明确包含格式 `v2`、`sessions` 或 `shadow` 域、UUID、流名和连续序号；seal AAD 也绑定 `v2` 与预期域。清单本身记录格式版本和域，绑定文件长度及 SHA-256、各流帧数／明文字节数／SHA-256、来源与内容无关的运行元数据。读取重新验证预期域、seal、文件清单、长度、哈希、每帧认证、序号及流总量；错 key、跨域复制、调包、截断或缺帧拒绝。旧 v1 目录原位保留，新读取器报告格式不支持；不自动迁移、重加密或删除。

旧 v1 目录**仍按同一文件长度口径计入所在域额度**：它们既不被迁移也不被自动删除，滚动验证器把它们视为不可删保护项，因此可能长期占用预算并触发 `over_limit`；需要释放时须人工核对活动引用与恢复需要后另行授权处理。

四条流的来源：`task` 为任务根 `work/TASK.md` 原字节，捕获后再核对冻结清单中的长度与 SHA-256；`request` 为重新生成的固定 `--print` 参数 UTF-8 字节；`stdout` 与 `stderr` 为 CLI 两条管道的原字节。输入漂移或容量不足时在 spawn 前拒绝，结构化回执只给 `capture_unavailable`／`over_limit` 原因，不回显内容。stdout 的结构化事件直接从认证帧增量解析并保留旧包装事件与扁平测试事件分类；不另写明文事件文件。清单记录来源、字节数、哈希及完整性；无法取得的 agy GUI 对话、隐藏推理和 SDK 内部流不在会话中。`settings` 原始凭据字节不进入加密会话，只记录前后哈希与恢复状态。

离线读取的最小接口：以注入密钥和状态根建立 `SessionStore(key, root=...)`，再调用 `store.reader(session_id).manifest()` 和 `read_stream("task"|"request"|"stdout"|"stderr")`，或使用 `iter_stream(name)` 逐帧读取。影子域使用 `SessionStore(key, domain_name="shadow", root=...)`；只有 seal 且全部校验通过才能读取。Shadow 快照先读验源会话，再以 shadow 域重新加密四流，存来源 UID、seal 哈希、输入摘要及流身份；它不持久引用原会话，故原 sessions 域可独立滚动。`add_reference`／`remove_reference` 仍是显式保护接口，不由本快照流程调用。命令及比较口径见 [SHADOW_USAGE.md](SHADOW_USAGE.md)。

## 容量与恢复

空间不足时，仅按 seal 内创建时间从旧到新滚动**完整、已重新校验、无引用**的整包。删除前写内容无关的 `delete_intent` 收据；16 个槽循环覆盖旧收据，故它是有界滚动痕迹，不是永久审计库。删除只逐个移除已验证清单中的文件和目录，不递归清理未知内容。活动或中断包、未知／篡改文件、引用包、H3 视频与旧 `%LOCALAPPDATA%\AskAIMCP` 材料均不自动删除。只有保护项可用时显示 `over_limit`，下一次会话在 spawn 前拒绝。

中途超限或磁盘写失败时不再保存更多流字节，但继续排空 CLI 管道并恢复配置；回执标为 `capture_incomplete`，该目录保留为未封口残件且继续计量。断电／进程崩溃可能只留下 `.partial`、改名中途文件、滚动 `.tmp` 或 `delete_intent`；状态只把未封口包视为待人工核对，不自动解锁或删除，也不声称滚动完成。人工恢复须先确认没有活动写入、保存需要的恢复材料和引用，再按另行授权处理残件。新会话不能以覆盖旧目录来恢复。

## 宿主明文边界

`run_root/capture/` 不再保留 `stdout.raw`／`stderr.raw`。`run_root/plan.json` 只留摘要和哈希；`run.json`、配置回执及滚动收据不含 CLI 内容。`prepare` 建立的 `work/TASK.md`、工作文件副本，以及本次 `run_root/private/settings.original.bin`、`settings.patched.bin` 和恢复漂移现场，仍可能是明文；Bridge 保持后两者目录的仅属主 ACL。成功恢复后这些本次备份也暂留以供故障核对；恢复失败时尤其不能自动删除。它们不计入会话域上限，加密会话不能代表全机无明文。收尾须清点本次任务根与运行根；历史日志、备份和旧状态既不迁移也不删除。

实现依据（核验 2026-09-28）：[cryptography AESGCM 文档](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM) 的 AAD 与认证标记机制、[keyring Windows 后端](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py) 及 [Microsoft LockFileEx 文档](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)。采用成熟 AESGCM/keyring；Windows 域内计量锁使用 Python `msvcrt.locking`，未实现自定义密码算法或通用日志平台。
