# 工作台账（WORK_LEDGER）

## 当前补充结论（2026-10-04）

LAB-DELIVERY-CONSOLIDATE-01 本地统一候选已整理于 `codex/delivery-consolidate-01`：保留完整产品 `a03bbb91fa18fed4492fcc17a85a40601700ee44`、Skill `1691a231729a9bb5e3901196a57f1f27da6f824e` 和管理已提交历史，冻结四项管理改动后整合；另按作者当日决定纳入 AGENTS 的 Sol 6.1 `xhigh` 单行更新，历史 `max` 记录保留。使用说明保留 1691 完整新版，管理补充的权限排障原文已在其中；仅修订默认 false 无须反复显式保存的建议及过期现状文字。产品源码/测试/构建输入未改，复用原离线证据；新增文档自检不替代管理核验或独立 Review。归档 `2026-10-04-LAB-DELIVERY-CONSOLIDATE-01/INDEX.md` 登记完整 diff、验证与发布审批摘要。精确 origin 分支一次只读查询成功，现有两个已发布分支与本地跟踪值一致；新候选未发布，新仓库不在安全 push 包装器白名单。仅准备候选，不更新本机 Skill、包装器或远端。

T13按缩小后的授权范围销账：SMOKE-02一次execute/agy启动，约49秒，Bridge/child均0、SUCCESS；5组原生文件工具完成配对，OUTPUT精确12字节、collect仅OUTPUT，宿主无人输入。配置仅排版漂移，产品严格恢复为原93字节CCD1B5AC…，临时permissions缺席、共享配置及exe未变，无手工写回或保护放宽。仅新UID `5cfa967d-9192-4cc4-8c79-7156a5a757e5` 内存认证核验。报告 `2026-10-04-LAB-AGY-PERMISSION-SMOKE-02/REPORT.md` SHA-256 `1648CA888DBC12CAA4E3D3C7377322F28C6D3066BBF22B0154EC86E0C0E79414` 已核验。通过的是任务内合成读写、无人输入完成、配置恢复和捕获；一般目录隔离、目录外访问、其他工具及全部业务能力未验，远端身份/请求数/费用未知。旧失败证据保留，不反向确诊旧EOF或键消失原因。

## 当前补充结论（2026-10-03）

agy有界设置调研完成：官方支持allowNonWorkspaceAccess且默认false，但实际保存路径/共享ALLOW优先级仍未知。管理采纳最小方案：保留自然保存的93字节配置，不重复插入默认false，不改产品恢复保护；新exe/配置另冻结后可申请独立单次测试。报告 `2026-10-03-LAB-AGY-SETTINGS-COMPAT-01/REPORT.md` SHA `DED5B98177D702618511151CBB5FF40D68E6BFCB0117D244EB17F4F931966494` 已核验；无新模型调用或配置写入，旧EOF仍未归因。

agy恢复收口：一次精确原字节恢复通过（原哈希8D303360…、129字节、ACL不变），临时permissions已清除，GUI共享哈希未变。随后当前配置变为93字节/CCD1B5AC…，仅false键再次消失；agy文件变为871E1EEB…，人工界面报告1.2.16/已登录。未重复覆盖，不把omitempty静态标签当作已证根因。报告核验：`2026-10-03-LAB-AGY-CONFIG-RECOVERY-01/REPORT.md` SHA `3948E6037B18E255FC96B36E2626C16FCF92E3695945977A39D71155298776BD`；`2026-10-03-LAB-AGY-SMOKE-DIAG-01/REPORT.md` SHA `70C9B0133B9331D7F0D9580C79E5A1BCDE0126033DC7980107497747BC684217`。下一步仅有界设置兼容调研，无新模型调用。

T13真实单次测试失败：Bridge/agy各启动1次，child exit1，资格HTTPS GET EOF，原生文件事件0、OUTPUT未变。加密捕获完整认证但不代表业务成功。CLI配置唯一语义漂移为allowNonWorkspaceAccess消失，恢复被阻止且临时permissions残留；当前SHA B1111458EEF3D881D8D21E8BAE194880608A34886105D06DD61569921811A94A，原备份8D303360E13557BF5753B33FE6C3F27C65FACBE685D754980F100A23631BDB98，共享配置未变。报告 `2026-10-03-LAB-AGY-PERMISSION-SMOKE-01/REPORT.md` SHA-256 `16288E76257510F326F6EBCED8C16DE94B598D0FD6B0E9BFCB5895F3E8637C54` 已核验。无重试；离线诊断继续，精确恢复待授权，不归因未知写入者。

T13准备报告已核验：`2026-10-03-LAB-AGY-PERMISSION-SMOKE-PREPARE-01/REPORT.md` SHA-256 `477A59E5AC5A25439687B39619EAD895E02AFC8BE14F7280DF8C5DCA24DCEFA9`。prepare/plan/default run三项通过、模型调用0。原测试目标超出现有合同：固定work内清单不允许读取目录外marker，且runner不按审批事件即时取消。管理建议收窄为任务内读写免人工审批与配置恢复，接受现有15m打印/1020s子进程等待，目录外行为未验证；不为本次验证扩建运行器。尚待作者明确调整目标和单次执行授权，原冻结材料保留不改。

并排部署完成，T03/T04销账：新版入口 `C:\Dev\ask-ai-mcp\runtime\local-agent-bridge\0.1.0.dev0-5c60e9af\.venv\Scripts\local-agent-bridge.exe`。冻结wheel5C60E9AF…安装，依赖70包兼容、产品22/22字节、入口及3次help通过；旧9113686f目录与21文件保留。两个本机Skill按1691a23冻结Git blob同步4/4、校验2/2通过，旧调用Skill备份2/2；usage物理CRLF与Git LF区别已登记。未改PATH/GUI/MCP/权限/用户AGENTS，模型调用0。报告 `2026-10-03-LAB-BRIDGE-PARALLEL-DEPLOY-01/REPORT.md` SHA-256 `AEDF1A467317EA14FE4A18AFBFBE8A39D03473B3F1E8EF7BDB9EBFA34047F31A` 已核验；备份及回退见同目录ROLLBACK.md。T02仅剩远端交付授权路线，T13实际权限验证仍未运行。

T04文档核验完成：调用Skill新增Cursor流程，管理对照源码核对固定模型、参数和force，补回遗漏的上游CLI版本排障并区分agy生成许可与Cursor冻结项目配置。最终候选 `1691a231729a9bb5e3901196a57f1f27da6f824e`，UTF-8 quick_validate与diff检查通过、clean。仅文档，未安装/调用/部署/推送；与部署Skill一起等待交付。

T03文档复核收口：部署配置 Skill 候选 `509673a5b95dbd0c61ae2ee6f5451de06580dd0e` 经独立复核，F01/F02/F03全部关闭；UTF-8 quick_validate及5个有限合成例通过。报告 `2026-10-03-LAB-DEPLOYMENT-CONFIG-SKILL-REVIEW-02/REPORT.md` SHA-256 `3B6F6FD18E7EF4EE83BD810B03D6AD40BE840CC224DF50E733CDAB774A8B2EF2` 已核验。仅文档与离线检查通过，未安装Skill、未部署、未验证agy实际权限行为；安装随交付处理。

作者同意不影响GUI方案后，本机agy CLI已新增toolPermission=always-proceed、allowNonWorkspaceAccess=false；原trustedWorkspaces保持、无持久permissions，GUI共享配置哈希未变。静态JSON核验通过，实际Windows覆盖/拒读行为待验，未调用模型。备份与回退入口为归档 `2026-10-03-LAB-AGY-CLI-CONFIG-01/INDEX.md`。Cursor固定force已实现已测流程免审批，无需重复改全局配置。

部署预检完成但未部署：建议并排运行目录 `0.1.0.dev0-5c60e9af`，冻结wheel5C60E9AF…，旧目录保留回退；安装后仅依赖/22包文件/入口help检查，不需重启GUI或开启H3。当前已测force+显式deny文件流程无审批等待，不代表所有操作已验收。新仓库独立common Git dir未被现安全推送包装器覆盖，发布路线待明确。归档 `2026-10-03-LAB-CURSOR-DEPLOYMENT-PREFLIGHT-01/REPORT.md` SHA-256 `992810DFA8E401266BFF4B89FE53CC3F474602CD07F2345BDEBCED11FB545458` 已核对，安装/模型/远端操作均0。

agy自动审批调研初报待边界补正：候选toolPermission=always-proceed；官方在线文档注明Windows旧权限体系，当前共享层工作区外策略为ALLOW，不能据二进制字符串就宣称目录约束已保留。暂未写配置，等待核实。调研发生一次未经派工允许的 `-p` 非法模式探针，后端调用数未知，不能记零调用；后续禁止此类探测。原报告 `2026-10-03-LAB-AGY-AUTOAPPROVAL-RESEARCH-01/REPORT.md` SHA-256 `EE804B970EAF4A1CBD48DFDFA710C69ADFD77AAD063974514268B67524113FCB` 已核验，保留原始偏差记录。

T12销账：CLI `2026.10.01-e373342` 定点兼容检查通过，PRODUCT-SMOKE-04-CONTINUED 指定合成流程通过。原04调用0，继续单调用1；marker明确拒读且无内容，OUTPUT12字节、collect仅OUTPUT、真实success终态和四流认证通过。不是全面隔离或部署验收，Shell/MCP/WebFetch未测，provider身份/请求数/费用未知。原产品未改。核验报告哈希：兼容 `4627A654E7126DA3C9288EAC50BAA3B3BF0E9DDD077A8987AB1A08B3AF59B5AB`；继续单 `780E48162091968B70ADE71C1596CCBAC7FBB46199C190769016B4AC816DDC67`。入口分别为归档根 `2026-10-03-LAB-CURSOR-CLI-COMPAT-20261001/REPORT.md`、`2026-10-03-LAB-CURSOR-PRODUCT-SMOKE-04-CONTINUED/REPORT.md`。下一项为部署/回退/远端交付准备，不自动部署或推送。

## 当前补充结论（2026-10-02）

夹具修复及独立核验完成，T11销账：候选 SHA-256 `E84AD60D11B66F417FF20AED7EC916456016E73EE4BC4E7EF57526B2E53811F3`；独立核验确认5行/单一config语句变化、13条规则数量次序与任务调用流程保留。核验报告哈希已核对：`2026-10-02-LAB-CURSOR-SMOKE-FIXTURE-REVIEW-01/REPORT.md`，`F55FBFE57117FD1A97A1C0F8A5B0647730F3508DDE2F3F7BFA33EA92765D1C02`。真实配置加载/拒读尚未验证，等待新单次smoke授权；不据离线PASS接受部署。

权限诊断收口，T10销账：SMOKE03夹具 as_posix 规则与 Cursor 原生绝对目标不匹配，纯探针36项通过，原10条规则0命中、原生规则10命中。此前SMOKE04原生规则曾拒读；未发现桥接器改写规则或传错cwd，也不支持 force 一律绕过deny。因当次有效权限数组未观测，不断言唯一根因。仅修新夹具，不改产品或本机权限。报告SHA-256 `51557B966E0636A3B6CEA2639578229D31BADDFE1DA26116DE03606D866428D9`，归档 `2026-10-02-LAB-CURSOR-PERMISSION-DIAG-02/REPORT.md`。

PRODUCT-SMOKE-03：充值后原产品固定 Grok 4.7 High 非 Fast 单次调用取得成功终态，OUTPUT 精确目标12字节，collect仅OUTPUT；但DENY_MARKER读取成功，权限拒绝样例失败，整体不接受部署。T09销账，转零模型调用诊断；根因未定。报告哈希已核验：`2026-10-02-LAB-CURSOR-PRODUCT-SMOKE-03/REPORT.md`，SHA-256 `53EC38463EF069FDFA01B27C83E8464A460FE4C12EA6B95C99D840A6954EDC1F`。费用与独立provider身份未知，原安装/候选未变。

上游CLI允许自动更新、必要时手动更新；按需版本排障已补入仓库Skill参考并同步本机，Skill校验通过（无CLI升级）。产品版本变化适配测试仍在部署配置规划，未宣称实现。

## 当前补充结论（2026-10-01）

Grok 4.6 Medium 尝鲜配额隔离实测已收口，T08 销账：CLI 确认 ID `cursor-grok-4.6-medium`，单次启动仍返回 `ActionRequiredError` / Free plan 仅允许 Auto；无工具调用或终态，OUTPUT 未变。GUI 配额未转化为 CLI 可用证据，实际 provider 请求数及费用未知。原 wheel、安装及候选提交未变；不重试，按作者要求暂停，等充值后通知。报告哈希已核验：`2026-10-01-LAB-CURSOR-GROK46-MED-SMOKE-01/REPORT.md`，SHA-256 `648914701D5BBD473B01299BDBA8F1CD1D67F03603154E15E4121EC95C60C1DE`。临时材料按该任务 Scratch INDEX 登记保留，未删除。

SMOKE-02 原因已确认：认证后的 CLI 错误为 `ActionRequiredError`，报告当前 Free plan 仅允许 Auto，具名模型不可用。账户后台订阅未核查；不推断 4.6 Medium 可绕开限制。init 的 `Grok 4.7 256K High` 是显示标签，不是执行成功证明，原标签规范化不匹配不能单独作为错路由证据。诊断无新增模型调用，T07 销账。证据：`2026-10-01-LAB-CURSOR-PRODUCT-SMOKE-02-RESULT-DIAG/REPORT.md`，SHA-256 `95D5ED23341CA5DF52AB47400062D4F615AFB122E1677F181FC5616AFEE2F7A3`。

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
