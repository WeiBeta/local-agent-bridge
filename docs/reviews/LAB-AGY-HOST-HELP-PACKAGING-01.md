# LAB-AGY-HOST-HELP-PACKAGING-01

2026-10-14 / Asia/Shanghai。**源码包 fixture 纳入及实际解包自检闭合；存在一次 Ruff 缓存路径偏差，已保留记录。未独立 Accepted。** 下一门禁为管理冻结新 HEAD 后的 fresh 独立 Review，Cursor 继续暂停。

## 冻结与最小补项

完整读取管理树 WORK_LEDGER 最新「HOST-HELP-FORMAT实现核收／源码包补齐」节及适用项目规则。就在原 clean 实现树 `C:/Dev/ask-ai-mcp/worktrees/agy-host-help-format-repair-01`、分支 `codex/agy-host-help-format-repair-01`、base `77d1c45edc3328102fb116d59b8b1bf28e1d1f01` 上作单独普通提交；精确最终 HEAD/tree 在本 ID HANDOFF.json 中绑定。

- pyproject.toml 的唯一数据差异：sdist only-include 加一项 `tests/fixtures/agy-help-1.3.4.txt`；其余配置、依赖、版本和锁不变。
- tests/test_distribution.py 仅加 fixture 纳入、存在及 LF 归一后来源 SHA 的防回归。
- 原 BRIDGE_USAGE.md 与 RELEASE_CHECKLIST.md 同步指向包内 fixture/来源复核及本报告；旧修复报告、旧包和旧证据不改。
- 生产解析代码及整个 src、uv.lock、test_agy_host、fixture、test_first_task_r 和其验证器共 35 个冻结文件逐项 SHA 保持。这是配套完整性补项，不增加或重置解析 Repair 轮次。

## 离线构建与实际包

只读复用 `LAB-AGY-STATION-BUILD-PREP-01/bv` 的已存在本地 backend：Hatchling 1.32.4、packaging 26.2、pathspec 1.1.1、pluggy 1.6.0、trove-classifiers 2026.9.21.13、tomlkit 0.15.1。现场核同既有 BUILD-ENVIRONMENT-03 的版本，记录实际模块来源/SHA，构建后核原模块字节不变。初始开发 venv 没有 hatchling/tomlkit，未据此安装或下载；使用了已完整具备依赖的旧 builder。没有执行旧构建脚本。

直接调用该环境的 PEP 517 `build_sdist`，额外 build requirements=[]；未调用依赖解析、安装、同步或在线补依赖。child 设置无 bytecode、PIP_NO_INDEX、UV_OFFLINE 等，临时目录放本 ID。只构建 sdist，不构建/安装 wheel，不刷新 runtime。

实际产物：`dist/local_agent_bridge-0.1.0.dev0.tar.gz`，696235 字节，SHA256 `c8f528d7cc7c83434760a5db7a8aa43c77588b63e13df8931d9f3b461472042b`。构建原 stdout/stderr、native 生命周期和 backend 来源见 build.receipt.json / BUILD-TOOLS.json；成员及每项原 SHA 见 PACKAGE-CONTENTS.json。

实际 TAR 有 85 个成员，恰含 `local_agent_bridge-0.1.0.dev0/tests/fixtures/agy-help-1.3.4.txt`。该成员原始 2905 字节，原始及 LF 归一后 SHA256 均为 `337622c6dcdcb204312277570c4173dda83f3cbf006629f0eabe657069071e7c`，与 HELP-DIAG 原文一致。不是只检查清单或读取工作树替代实际包。

先核成员唯一性、单一根、普通文件/目录和无路径逃逸，再 data-filter 解包到本 ID 的 `unpacked/local_agent_bridge-0.1.0.dev0`。所有解包成员字节与 TAR 核同；除生成的 PKG-INFO 外，全部包输入与当前源码物理字节核同。本报告在构建后新增，仍沿原策略不把 docs/reviews 报告纳入包；没有改包的其他分发范围。

## 适用验证与来源证明

| 阶段 | 结果 |
| --- | --- |
| 当前源码 distribution + help | 156 passed（28 + 128），JUnit 无 fail/error/skip |
| 实际解包 distribution + help | 同样 156 passed（28 + 128），JUnit 无 fail/error/skip |
| ruff check . --no-cache | exit 0 |
| 首次 format --check . | exit 0，另记录缓存路径偏差 |
| format --check . --no-cache | exit 0，93 个 Python 文件格式通过 |

测试复用既有开发 venv 的依赖，以 `-I -B` 启动。导入前移除旧源码路径，优先注入指定 target 的 src/tests；前后核所有加载的 Bridge 模块均来自该 target。解包测试核 24 个实际 Bridge 模块均来自解包 src，逐项记录路径/SHA，不是从旧 worktree 借来生产代码。依赖/已安装 distribution metadata 仍来自旧开发环境；这不是包安装或安装后验收。

六个本地构建/测试/格式阶段均由现有受控 launcher/WinJob 执行，未修改相关生产模块；每阶段执行上限 900 秒、独立共享 4 MiB RAM 输出预算，原 cleanup 预算保持。各阶段 native tool exit=0、外层检查 exit=0、capture complete、未超时/截断；child_exit_observed / pipes_closed / job_closed 均 true。PID/created FILETIME、耗时及原双流分别记录，未留下失管 Job。真实 agy/Cursor/model/key 调用均 0，不把本地工具启动数与真实业务混用。

本单按冻结不重复全量。此前完整原执行 3041 passed / 1 failed / 1 skipped、180 秒外层超时、native exit 未记录均保留；`test_installation_verifier_checks_real_fixture_bytes_and_origin[none]` 的 contract_version 基线红项仍开放，相关代码/测试/验证器不改、不遮蔽。fresh Review 须核其与候选 diff 的关系及发布影响；本单不宣告全项目测试全绿。

## Ruff 缓存路径偏差

首次 format 检查遗漏 `--no-cache` / 本 ID 缓存目录；检查期间当前实现树的三个既有忽略缓存文件出现本轮 mtime 更新：`.ruff_cache/0.16.1/4018434876859487881`、`9222683089403517575`、`987980224188311220`。这超出本轮冻结产物路径；不能以 ignored 为由省略。CACHE-SCOPE-DEVIATION.json 记录当前 SHA/长度/mtime，先前字节 hash 未保存，字节差异保持 Unknown。

没有删除、回滚或覆盖旧缓存。后续 child 显式将 RUFF_CACHE_DIR 放本 ID，最终 format 加 `--no-cache`，原检查记录保留。这不改变生产代码/配置/依赖，但路径执行偏差仍须管理核收，不用后续绿色检查抹去。

保留本 ID Scratch/Archive、实际包、成员清单、解包根、两组 JUnit/导入来源、全部检查原出口及脚本，并保留上述三个缓存/旧基线红证据/原 builder/依赖环境。根 Archive INDEX 登记本任务；无清理、到期或自动删除，删除须精确授权与引用核验。只向管理 `019fe10b-df55-7b82-a9ba-3702dc08c55f` 回执一次，不自行派工、实测、部署或业务重试。
