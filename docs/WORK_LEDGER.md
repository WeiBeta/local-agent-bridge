# 工作台账（WORK_LEDGER）

## 当前补充结论（2026-10-01）

PRODUCT-SMOKE-02 已结束，未通过业务验收：桥接器启动一次且四流加密封口完整，Cursor 子进程 exit 1，仅 system/user 事件，无工具调用或终态，OUTPUT 未变。provider 请求次数未知；尚不能归因订阅或模型。单次执行授权已使用，T06 销账；仅本次结果核验继续，不新增调用。证据：`2026-10-01-LAB-CURSOR-PRODUCT-SMOKE-02/REPORT.md`，SHA-256 `C947C99F01E5AE5EEE2BE68DBFC5401F392E598AACA0B8A2D3CBE0115E615465`。

汇总时间：2026-10-01（本次更新同日）。定位：为管理会话**释放上下文**的精简可追溯记录——只记重要事实、限制与证据入口，不做派工流水账，不复制长回执。范围如实声明：仅覆盖**新仓库（Local Agent Bridge）交付及 Cursor 当前阶段**；旧 Ask AI MCP 的长期历史经本地归档索引链接（见下），不在此穷举。管理任务：`019fe10b-df55-7b82-a9ba-3702dc08c55f`。

证据入口约定：本地归档根为 `C:/Users/user/Documents/Codex-Archive`（入口 `INDEX.md`）；证据列使用“任务 ID + 归档相对目录 + 关键哈希”。未核验项一律标“未核验”，不以推断补齐。

| ID | 目标 | 状态与边界（重要事实/限制） | 冻结提交 / 产物哈希 | 证据入口 | 复审会话 | 结论日期 |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | 新仓库初始交付（H3/Bridge/加密会话/影子回放/许可与整包收口，五包链） | 完成；整包独立审查通过；内部候选定位不变 | 仓库初始交付线（见仓库 `docs/` 与归档索引） | 归档根 INDEX 相对目录（LAB-H3/BRIDGE/SESSION/SHADOW/PACKAGE 各任务） | 各独立 Review 会话（见各归档） | 2026-09-30 |
| L02 | Bridge 使用 Skill（跨机调用说明） | 完成；独立核验通过 | `ef928d0e7c577a9b63c3fae032ba880b04d89473` | LAB-BRIDGE-SKILL-REVIEW-01（归档根） | 独立审查会话 | 2026-09-30 |
| L03 | 会话存储重开 ACL 修复 | 完成；独立审查通过；遗留 A1 由 L04 关闭 | `d21afb14cf930cec30bc1520f7322db7d14860cb` | LAB-CAPTURE-ACL-REOPEN-REVIEW-01（归档根） | 独立审查会话 | 2026-09-30 |
| L04 | Shadow 先行创建状态根的 ACL 初始化修复（A1） | 完成；增量独立审查通过，无新增 finding | `77cffb6c9280cdb2befbd6f917862826edbab722` | LAB-SHADOW-ACL-INIT-REVIEW-01（归档根） | 独立审查会话 | 2026-09-30 |
| L05 | Cursor 薄适配实现 | 完成（实现+自检；审查见 L06） | `6a498820c9a3052658d7124e89d78a50ba909c84` | LAB-CURSOR-ADAPTER-IMPL-01（归档根） | —（自检非独立） | 2026-10-01 |
| L06 | Cursor 适配独立审查（REVIEW-02 全量 F01/F02 关闭；REVIEW-03 F03 关闭） | 完成；产品适配**最终冻结** | `a03bbb91fa18fed4492fcc17a85a40601700ee44` | `2026-10-01-LAB-CURSOR-ADAPTER-REVIEW-03/REPORT.md` SHA-256 `B251B4A15497BD2D7F3D67EFE6DB6C02338EBAF72C31C290B9C04E0129DFB99E` | 独立审查会话 | 2026-10-01 |
| L07 | PACKAGE-01 打包验证 | 完成；228 passed / 1 skipped；**未生产部署** | wheel SHA-256 `5c60e9af315db96e08c0364c9ac01d5f8ed62bbfc953bc0c972a0bbbb98ac33a` | `2026-10-01-LAB-CURSOR-ADAPTER-PACKAGE-01/INDEX.md` | —（打包验证） | 2026-10-01 |
| L08 | SMOKE-04 冻结捕获认证重析与归档收口 | 完成（PASS_FROZEN_SMOKE04_REANALYSIS）；与产品入口真实 smoke 严格分开 | 重析报告 `B8E65BF0…4E4E3`；收口 `10395DAB…D6B`（全量见产品仓 CURSOR_EVIDENCE.md） | `2026-09-30-LAB-CURSOR-SMOKE-04-REANALYZE-01`（重析 2026-09-30，归档收口 2026-10-01） | 独立解析审查在案 | 2026-10-01 |
| L09 | 部署配置 Skill 方案登记 | 完成；**规划未实现**，未装 Skill、未改任何配置 | `ca63009dad4e541bb61baee4b4a86d39484c65c8` | 本仓库 `docs/DEPLOYMENT_CONFIGURATION_PLAN.md`；归档 `2026-10-01-LAB-DEPLOYMENT-SKILL-PLAN-01` | —（文档登记） | 2026-10-01 |
| L10 | LAB-CURSOR-PRODUCT-SMOKE-01（产品入口真实 smoke，一次授权） | **已结束：REFUSED_BEFORE_LAUNCH，不成功。**Cursor/provider 调用 0；execute 尝试 1；运行根仅 `plan.json`，无 run/session 产物；`setup_stage` 未留存——拒绝根因未定，**不能归因订阅到期**。一次授权已使用，不得重试/换模型/生产部署 | 报告 SHA-256 `CC7630757ED322EB24EDA3D06E2E8E9DA53E56D24EEA0BC091065F6443740EE8` | `2026-10-01-LAB-CURSOR-PRODUCT-SMOKE-01/REPORT.md`（归档根） | —（终态已回收） | 2026-10-01 |

| L11 | LAB-CURSOR-PRODUCT-REFUSAL-DIAG-01（启动前拒绝根因诊断） | 已完成：当前状态父目录（%LOCALAPPDATA%\LocalAgentBridge，仅记此一次）为继承 ACL，固定 Verify 返回 DACL_NOT_PROTECTED；合成 SessionStore 复现了启动前拒绝；原一次 smoke 缺 setup 字段，唯一历史原因未证；登录用户已自行验证正常。真实产品 smoke 仍未验收；一次授权已使用，后续新调用需另得授权 | 报告 SHA-256 `874451B618AC04A589B7FF2557E1F382DDFF06D4D1A00A950DD12027330ADEC9` | `2026-10-01-LAB-CURSOR-PRODUCT-REFUSAL-DIAG-01/REPORT.md`（归档根） | —（诊断会话） | 2026-10-01 |

| L12 | LAB-STATE-ROOT-ACL-REPAIR-02（状态根 ACL 修复） | 已完成（PASS）：仅批准的 root/shadow/锁三项 DACL 及继承改动；root/shadow 产品 Verify 均 rc 0；owner/group 与锁内容保全；无新增 session/CLI/provider/key。**存储权限通过不等于产品 smoke 验收** | 报告 SHA-256 `EFCB1B64DDFCAE3A8251315AE7355C96F86C58C8D278C6F7EDAF1F0E9AB08206` | `2026-10-01-LAB-STATE-ROOT-ACL-REPAIR-02/INDEX.md`（归档根） | —（修复会话） | 2026-10-01 |

| L13 | 工程难度路由长期决定（2026-10-01） | Flash=低难度/规格明确基础；GLM5.3=*中档（Cursor Grok4.7 High 非 Fast 仅已验收范围，Gemini4 Pro 仅待评估）；Sol=gpt-6.1-sol@max 处理逻辑耦合/中档易错工程；Astra@medium 仅顶级攻坚或 Sol 失利升级（提强度需作者审批）；Luna=机械调度员不做首次实测/开放排障/验收；不按任务名自动选档、不自动切换已有会话、不扩大权限/付费授权 | 本仓库 AGENTS.md（本提交） | 本仓库 AGENTS.md 模型段 | — | 2026-10-01 |

固定裁决（不再开待办）：Grok `grok-4.7-high` 非 Fast 已确认，不再安排 XHigh 对比；H3 通道按作者决定关闭，不派开启任务；Zcode 暂缓；后续其他 Bridge 仅记 backlog，不视为已启动。

历史边界：旧 Ask AI MCP 仓库的完整任务史以归档根 `INDEX.md` 及该仓库自身记录为入口，本台账不复制、不重述其结论。
