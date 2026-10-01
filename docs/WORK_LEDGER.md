# 工作台账（WORK_LEDGER）

汇总时间：2026-10-01。范围如实声明：本台账只覆盖**新仓库（Local Agent Bridge）交付及 Cursor 当前阶段**；旧 Ask AI MCP 的长期历史不在此穷举，仅经本地归档索引链接（见下）。管理任务：`019fe10b-df55-7b82-a9ba-3702dc08c55f`。

证据入口约定：本地归档根为 `C:/Users/user/Documents/Codex-Archive`（入口 `INDEX.md`）；下表证据列使用“任务 ID + 归档相对目录 + 关键哈希”，不复制宿主绝对细节。未核验项一律标“未核验”，不以推断补齐。

| ID | 目标 | 状态与边界 | 冻结提交 / 产物哈希 | 证据入口 | 复审会话 | 结论日期 |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | 新仓库初始交付（H3/Bridge/加密会话/影子回放/许可与整包收口，H3→Package 五包链） | 完成；整包独立审查通过、内部候选定位不变 | 仓库初始交付线（详见仓库 `docs/` 与归档索引） | 归档根 INDEX 相对目录（LAB-H3/BRIDGE/SESSION/SHADOW/PACKAGE 各任务） | 各独立 Review 会话（见各归档） | 2026-09-30 |
| L02 | Bridge 使用 Skill（跨机调用说明） | 完成；独立核验通过 | `ef928d0e7c577a9b63c3fae032ba880b04d89473` | LAB-BRIDGE-SKILL-REVIEW-01（归档根） | 独立审查会话 | 2026-09-30 |
| L03 | 会话存储重开 ACL 修复（Protect/Verify 分流） | 完成；独立审查通过，发现 A1 并由 L04 关闭 | `d21afb14cf930cec30bc1520f7322db7d14860cb` | LAB-CAPTURE-ACL-REOPEN-REVIEW-01（归档根） | 独立审查会话 | 2026-09-30 |
| L04 | Shadow 先行创建状态根的 ACL 初始化修复（A1） | 完成；增量独立审查通过，无新增 finding | `77cffb6c9280cdb2befbd6f917862826edbab722` | LAB-SHADOW-ACL-INIT-REVIEW-01（归档根） | 独立审查会话 | 2026-09-30 |
| L05 | Cursor 薄适配实现（固定一次调用 + 加密捕获） | 完成（实现+自检）；后续审查轮见 L06 | `6a498820c9a3052658d7124e89d78a50ba909c84` | LAB-CURSOR-ADAPTER-IMPL-01（归档根） | —（自检非独立） | 2026-10-01 |
| L06 | Cursor 适配独立审查轮（REVIEW-02 全量：F01/F02 关闭；REVIEW-03：F03 关闭） | 完成；产品适配**最终冻结**为下一列提交 | `a03bbb91fa18fed4492fcc17a85a40601700ee44` | REVIEW-03 归档目录 `2026-10-01-LAB-CURSOR-ADAPTER-REVIEW-03/REPORT.md`，SHA-256 `B251B4A15497BD2D7F3D67EFE6DB6C02338EBAF72C31C290B9C04E0129DFB99E` | 独立审查会话 | 2026-10-01 |
| L07 | PACKAGE-01 打包验证 | 完成；228 passed / 1 skipped（JUnit 为准），**未生产部署** | wheel SHA-256 `5c60e9af315db96e08c0364c9ac01d5f8ed62bbfc953bc0c972a0bbbb98ac33a` | 归档目录 `2026-10-01-LAB-CURSOR-ADAPTER-PACKAGE-01/INDEX.md` | —（按派工为打包验证） | 2026-10-01 |
| L08 | SMOKE-04 冻结捕获认证重析与归档收口 | 完成（PASS_FROZEN_SMOKE04_REANALYSIS）；**与产品入口真实 smoke 严格分开**，不代表真实 coding 能力 | 重析报告 `B8E65BF0…4E4E3`（全量见 CURSOR_EVIDENCE.md）；收口 `10395DAB…D6B` | `2026-09-30-LAB-CURSOR-SMOKE-04-REANALYZE-01`（归档根） | 独立解析审查在案 | 2026-09-30 |
| L09 | 部署配置 Skill 方案登记（仅文档） | 完成；**规划未实现**，未装 Skill、未改任何配置 | `ca63009dad4e541bb61baee4b4a86d39484c65c8` | 本仓库 `docs/DEPLOYMENT_CONFIGURATION_PLAN.md`；归档 `2026-10-01-LAB-DEPLOYMENT-SKILL-PLAN-01` | —（文档登记） | 2026-10-01 |
| L10 | LAB-CURSOR-PRODUCT-SMOKE-01（产品入口真实 smoke，一次授权） | **已派发、终态待回执**——不得记为已执行或通过；固定 High 非 Fast，禁重试/换模型/生产部署 | 冻结输入为 L06 最终提交 + L07 wheel | 派发目标：Luna 会话 `01a0cc6c-70c8-79d1-bdd0-8e68a03c9ab9`（不轮询、不读取该会话） | —（待回执后裁决） | — |

固定裁决（不再开待办）：Grok `grok-4.7-high` 非 Fast 已确认，不再安排 XHigh 对比；H3 通道按作者决定关闭，不派开启任务；Zcode 暂缓；后续其他 Bridge 仅记 backlog，不视为已启动。

历史边界：旧 Ask AI MCP 仓库的完整任务史、冻结提交与归档以归档根 `INDEX.md` 及该仓库自身记录为入口，本台账不复制、不重述其结论。
