# Local Agent Bridge 许可与来源凭据（内部核对记录）

核对日期：2026-09-29（许可实体补齐轮）；范围：**本发行源码树当前跟踪的材料**及其**当前提交历史**。本文件只记录在
本地 Git 对象中可直接复核的事实，不重新做网络或法律审查，也不把未独立核验的条款结论当作定论。
本文件不授权公开发布、推送或创建远端。

## 1. 本发行树当前状态：许可实体已补齐

任务 `LAB-LICENSE-PACKAGE-01` 从历史提交精确恢复了下述四个路径，使许可实体随本发行树固化。恢复方式是
**按精确路径**取源文件（`git checkout <commit> -- <path>`），只影响这四个路径；未整提交 cherry-pick，
因此旧 README、旧 `pyproject.toml` 与旧业务源码都没有被带入。恢复前已确认四路径在本树既不存在也未跟踪。

此前在起点 `e77cecf1579bf4c7fdbdfa5b28e9e284a30fba57` 的树内，`LICENSE`、`NOTICE`、`COPYING`、
`LICENSES/` 或 `docs/legal/` 均为零条（核查方式为 `git ls-tree -r <commit>` 路径前缀统计）。
**该缺项自始只是材料未随基线固化，不等于本项目从未取得许可。** 用户历史已提供上游作者 Jimmy 的
MIT 授权回复（issue 评论）；作者已据此为项目选择 AGPLv3。

## 2. 许可材料及其来源提交

提交 `2b6263712f75e8d436c4e77c4de0a6aa185e2f42`（`docs: add AGPLv3 license and upstream MIT
provenance`，2026-09-09 15:48:20 +0800，父提交 `0fd39b65345d6dc2e62303b8e5bf9a6b5cf8f887`）
引入了以下许可材料。恢复后本树内这四个对象的 Git blob 与源逐字节一致（用
`git hash-object` 与 `git rev-parse <commit>:<path>` 对比，四项全部相同）。

表中字节数为 **Git blob 字节（LF）**；Windows 工作树按仓库既有 `core.autocrlf=true` 检出为 CRLF，
故磁盘文件长度更大，两者内容相同（见第 6 节）。

| 路径 | Git blob | 字节 | 说明 |
| --- | --- | --- | --- |
| `LICENSE` | `be3f7b28e564e7dd05eaf59d64adba1a4065ac0e` | 34523 | GNU AGPL v3 全文，项目选择 `AGPL-3.0-only` |
| `LICENSES/MIT-jimmyloi.txt` | `bc470504b7429102a79732d2a76582709566ae9f` | 1071 | 上游 MIT 正文，署名为 `Copyright (c) Minh Loi (jimmyloi)` |
| `docs/legal/PROVENANCE.zh-CN.md` | `ff0fc82de7434e8bfc54e30ca9a1a1b71192aa14` | 3315 | 授权来源记录；含评论链接、截图哈希与核验边界 |
| `docs/legal/jimmy-mit-permission.png` | `6dc197ba8a78c6635def2c25e2adffb5c59ebc27` | 190218 | 授权截图原图，未重绘或压缩 |

同一提交还在当时的 `README.md` 与 `pyproject.toml` 中增加了许可章节与 `license` /
`license-files` 元数据。**那些是旧仓库的产品元数据，不是本预览包的发行面**：本包没有把旧 README
复制进来，只在当前 `pyproject.toml` 中独立设置 `license = "AGPL-3.0-only"` 与
`license-files = ["LICENSE", "LICENSES/*.txt"]`。

## 3. 凭据内容与其独立核验边界

`LICENSES/MIT-jimmyloi.txt` 为 MIT 全文并以上游 Git 作者补充署名。`docs/legal/PROVENANCE.zh-CN.md`
记载：上游 MIT 授权回复位于作者向 Jimmy 提问后的 issue 评论；该记录同时说明**未能确定版权年份，
因此未编造年份**，并声明 MIT 模板正文取自 OSI 页面。它记录的截图 SHA-256 为
`400eb071ccf3696eb9b5b6fedbff787ea1e9f74cc3b438c78525eb9eaba18ad5`。

上述引用的评论 ID、账号归属与时间由当时的管理任务在登录页面核验，历史记录本身已声明未做独立复验；
本任务只做**本地 Git 对象存在性与字节核对**，不重新登录、不抓取网络、不重新解释条款。截图内容
是第三方页面证据，不被主张为整体 AGPL 覆盖。

## 4. 本包当前的技术立场

- 许可实体已随树跟踪：`LICENSE`（AGPL-3.0-only 全文）与 `LICENSES/MIT-jimmyloi.txt`（上游 MIT 正文与署名）。
  wheel 通过 `license-files` 把两者装入 `dist-info/licenses/`；sdist 另含 `docs/legal/` 的来源记录与截图。
- 本包仍为**内部预览候选**：无对外分发包，无公共远端，未做真实主机测试，未做依赖许可整体兼容性审查。
  许可实体补齐**只解决材料缺项**，不等于公开发布审查通过。
- 依赖（`fastmcp`、`httpx`、`pydantic`、`cryptography`、`keyring`）依其各自许可，本包不复制其正文。
- H3 与后处理权重受 MiniMax Community License Agreement 等各自条款约束，权重与 ComfyUI **未捆绑**进本包；
  对外分发或商业使用前须另行核验权重许可与地域/用途限制。
- 上游单文件原件 `mcp_server.py` 留存在旧仓库历史中，不进本包、也不是支持入口。

## 5. 许可材料在发行包中的位置

| 位置 | 内容 |
| --- | --- |
| wheel `local_agent_bridge-0.1.0.dev0.dist-info/licenses/LICENSE` | AGPL-3.0-only 全文 |
| wheel `.../licenses/LICENSES/MIT-jimmyloi.txt` | 上游 MIT 正文与署名 |
| sdist 根 `LICENSE`、`LICENSES/MIT-jimmyloi.txt` | 同上，源码形态 |
| sdist `docs/legal/PROVENANCE.zh-CN.md` | 来源记录（评论链接、截图哈希、核验边界） |
| sdist `docs/legal/jimmy-mit-permission.png` | 授权截图原图 |

截图是**来源证据、不是运行资源**：它按 sdist 白名单随源码包分发，供许可溯源核对，不被任何模块读取或执行。
wheel 只装许可正文（PEP 639 `license-files` 机制），不含截图。

## 6. 换行与哈希口径

恢复的四项按 Git blob 字节存储（LF）。Windows 工作树检出后为 CRLF，因此磁盘长度与上表 blob 字节不同；
发行包内为归一化后的字节。核对许可材料时**以 Git blob 或包内字节为准**，不以工作树磁盘长度为准。
