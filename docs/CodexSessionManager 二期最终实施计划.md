# CodexSessionManager 二期最终实施计划（v1.2.0—v1.5.0）

> **For agentic workers:** 本计划须按开发节点逐项执行；每个节点先完成自动化测试和人工验收，再进入下一节点。不得绕过现有计划、指纹、备份、审计和 App Server 写入边界。

**Goal:** 先完成 v1.1 其它验收；随后优先实现并验收敏感信息确定性 `Replace/Redact/Protect` 计划层和受支持目标。只有收到明确启动要求且官方能力/真实 round-trip 门禁满足后，才继续 Codex 桌面端 UI、app-only 执行、会话工作区、只读地图、恢复现场摘要、上下文分叉和来源追踪。

**Architecture:** 保留 PySide6 作为本机维护、兼容和退化前端；未来新增基于 MCP Apps 的 TypeScript/React UI，通过标准 MCP 适配层复用 `ApplicationWorkflows`、计划、指纹、备份、审计和执行器。Codex 内 UI 的直接写入只允许未来通过全部门禁的本机个人插件 app-only surface，所有执行都由一次性授权和可恢复执行账本保护。

**Tech Stack:** CPython 3.13.14、uv、现有 PySide6、官方 MCP SDK/MCP Apps 适配层、TypeScript、React、Vite；Node.js 仅用于开发构建，最终安装包不携带 Node 运行时依赖。

**Spec:** 本文件是 `CodexSessionManager` 二期唯一现行计划；旧可行性报告和旧二期计划仅作为 `docs/archive/2026-08-27-phase2/` 中的历史材料保留。

**Current gate (2026-09-01):** v1.1 继续完成除 2.4 上下文应用和 2.5 永久删除应用以外的剩余验收；两者均已按 `CLOSED_WITH_UPSTREAM_BLOCKER` 关闭。当前只交付上下文审查/投影计划以及永久删除资格盘点/计划/审查；原任务应用、派生投影和永久删除应用均不可用。二期 D1+ 未启动；未经明确要求不得开始。

## 全局约束

- D1 及之后的二期代码、插件写入能力和协议画像变更，必须等 v1.1 其它验收完成、敏感信息确定性修改优先方向完成必要规划，并收到明确启动要求后才能执行。本次文档整理不启动二期功能开发。
- `main` 是唯一事实来源；未明确要求时不创建、推送或合并分支。
- Codex 任务读取和写入只能经过官方 App Server；禁止直接修改 Codex JSONL、SQLite、认证文件或配置。
- 远程 HTTP、普通 stdio、CLI、Skill、Hook 和模型可见 MCP profile 继续保持只读/准备计划能力；直接执行仅作为未来本机个人插件 app-only profile 的研究方向，当前不开放。
- 上下文审查与投影计划可用；应用到原任务不可用；派生投影必须在精确版本完成持久化、重启、后续模型可见和 reconcile 的完整 round-trip probe 后才能重新评估。
- 所有写入必须绑定不可变计划、完整后代闭包、能力指纹、内容指纹、备份证据、审计事件和明确人工确认。
- 口令、token、age identity、本地绝对路径和不必要的对话正文不得进入模型上下文、`structuredContent`、日志或 Git。
- 未知协议、未知字段、超时和状态不确定均退化为只读或 `reconcile`，禁止盲目重试。
- PySide6 至少保留一个完整版本周期，不因 Codex UI 迁移而删除。

## 1. 最终目标与范围

### 1.1 v1.3.0 的一期 UI 对等目标

Codex Desktop 内的本机个人插件必须覆盖以下用户流程：

- 项目、任务清单、搜索、筛选、多选、时间线和原文审查。
- 对话清理：盘点、建议、计划预览、归档、取消归档、重命名、备份并归档。
- 上下文审查与投影计划：Keep/Exclude/Summary/Protect、完整差异和待处理续办；原任务应用不可用，派生任务只有在未来执行器通过全部门禁后才可创建。
- 记忆管理：已登记来源、Keep/Delete/Replace/Protect、完整 diff、版本备份、应用和恢复。
- Pending 中心：检查计划 SHA、账号根、内容/能力指纹、任务状态，继续、取消、失效和异常核对。
- 备份与恢复：age 加密、清单和完整性复验、逻辑恢复、隔离导入。
- 永久删除：独立的最高风险流程，最后迁入，不得混入普通清理或自动化链路；迁入前还必须关闭 v1.1 的 App Server 版本迁移兼容与 descendant 完整删除 blocker。

Hook 安装/卸载、doctor、App Server schema 人工批准、签名、公证和正式发布管理仍属于本机管理入口，不计入一期 Codex UI 对等范围。

### 1.2 v1.5.0 的二期完成目标

- 独立的 `workspace.sqlite3` 和 UI 无关的 workspace 领域层。
- 项目/任务卡片、Board、位置、颜色、手工关系线和来源类型。
- 只读会话地图和 Map/List 双视图；地图卡片操作不改变 Codex 任务。
- 本地 Resume Digest、输入哈希去重、旧版本保留和来源显示。
- 经计划和人工确认、且执行器通过全部门禁的上下文分叉、派生任务落图、provenance edge 和崩溃恢复。
- Pending、备份/恢复、审计和 workspace sidecar 的统一视图。
- 在同一 MCP Apps UI 壳中提供只读地图视图；模型默认只收到 ID、关系、状态和摘要存在性。

多 Board、别名、多父关系、团队共享、自动布局/WIP 规则、全账号自动导入、后台自动执行、自动归档、自动删除和自动修改记忆不属于本二期。

## 2. 目标架构与接口

### 2.1 双前端和插件边界

OpenAI 当前插件文档支持由同一插件组合 MCP server 与可选 UI；MCP Apps UI 通过 UI Resource、`_meta.ui.resourceUri` 和 `ui/*` bridge 与宿主交互。实现时以官方文档为协议依据，并以真实 Codex Desktop surface 验收为准：

- [Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Add UI to your app](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Plugins reference](https://developers.openai.com/plugins/reference)

具体约定：

- 新增 `plugin-ui/`，使用 TypeScript、React、Vite 和锁定依赖；构建后的静态资源随 Python 包和 standalone bundle 发布。
- 新增本机入口 `CodexSessionManager cli mcp ui-stdio`，插件只调用稳定安装路径。
- 保持现有 `mcp stdio`、`mcp serve`、CLI、Skill、Hook 和 PySide 行为兼容。
- 保留现有业务 Handler，在 `mcp_server.py` 外增加标准 MCP/MCP Apps 适配层；不从 Qt controller 直接暴露业务。
- 使用一个版本化资源 `ui://csm/review-workspace-v1.html` 承载统一审查壳，按 `initialSurface` 路由清理、上下文、记忆、Pending 和备份页面。
- 数据工具只返回最小化结构化摘要；渲染工具负责挂载 UI，正文、差异和大列表由组件按需分页取得。
- UI 不支持时，客户端仍获得结构化结果和打开本地 GUI 的退化入口；UI 不得成为唯一业务事实来源。

### 2.2 MCP 工具和领域接口（未来范围，当前不实现）

模型可见工具继续使用现有盘点、建议准备、请求打开和状态查询工具；新增渲染工具：

- `render_cleanup_review`
- `render_context_review`
- `render_memory_review`
- `render_pending_review`
- `render_backup_review`

以下 app-only 工具只是未来候选接口，当前不注册、不实现，也不改变 v1.1 的能力边界：

- `issue_execution_grant`
- `execute_cleanup_plan`
- `execute_trim_plan`
- `execute_memory_plan`
- `execute_backup_plan`
- `execute_restore_plan`
- `execute_purge_plan`
- `get_execution_status`
- `reconcile_execution`
- `cancel_execution`

所有新工具必须提供严格 `inputSchema`/`outputSchema`、固定枚举和未知字段拒绝。执行工具只接收一次性 grant、capability token 和幂等键，不接收任意路径、任务 ID、App Server 方法名或自由参数。

### 2.3 直接执行安全模型

新增冻结领域模型：

- `UiSessionCapability`：绑定插件进程、Codex 数据根指纹、UI 构建哈希、session、随机 nonce 和有效期。
- `ExecutionGrant`：绑定具体操作、计划 SHA-256、能力画像、内容指纹、确认证据和 UI session，只能消费一次。
- `ExecutionReceipt`：返回 operation ID、逐目标结果、回读核对结果和审计事件引用。
- `ExecutionState`：`PREPARED`、`APPROVED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`PARTIAL`、`UNKNOWN`、`RECONCILIATION_REQUIRED`、`CANCELLED`。

执行账本扩展现有 `audit.sqlite3.operations`，使用 operation UUID 和唯一幂等键，记录批量操作逐目标状态。Tool Result 的 `_meta` 仅向组件传递 capability；任何 capability、token、口令或 identity 内容不得进入模型可见结果。

执行统一遵循（仅适用于未来通过硬门禁的受支持目标；当前上下文执行器为 unsupported）：

```text
盘点 → 选择 → 不可变计划 → 影响/差异预览 → 人工确认
→ 一次性 grant → 执行 → 回读核对 → 审计/异常续办
```

超时、断线、进程重启或响应丢失均先进入 `UNKNOWN`/`RECONCILIATION_REQUIRED`，通过真实状态核对后才能生成新计划；禁止对原写请求盲目重放。地图自身不提供执行授权，只能打开已经通过审查的功能页面。

### 2.4 主要实现文件责任

- 协议和能力：`src/codex_session_manager/mcp_server.py`、`mcp_bridge.py`、`app_server.py`。
- 工作流和安全：`workflows.py`、`models.py`、`plans.py`、`audit.py`、`backup.py`、`cleanup.py`、`trim.py`、`memory.py`、`importing.py`。
- 本机插件前端：`plugin-ui/`；打包入口和依赖清单同步更新 `pyproject.toml`、构建脚本和 standalone spec。
- 现有桌面兼容层：`src/codex_session_manager/gui/`，后续拆分 controller 但保持原交互。
- workspace：新增独立 `workspace/` 领域模块和 `workspace.sqlite3` 存储，不将高频地图状态写入审计表。
- 测试：新增 MCP Apps/UI 合约、执行账本、故障恢复、workspace 和真实宿主验收证据；不删除现有 PySide/CLI/Hook 回归测试。

## 3. 开发节点与交付物

### D0：文档收口与二期启动闸门

本节点可在 v1.1 本机验收期间执行，但只修改文档和 Git 管理，不实现二期功能。

- 将旧可行性报告、旧二期计划和已过期的 next-development 计划移至 `docs/archive/2026-08-27-phase2/`，正文语义保持不变；仅允许不影响语义的行尾空白规范化。
- 在归档目录增加 `README.md`，标记 `SUPERSEDED`、原始基线、归档原因和现行计划链接。
- 更新中英文 README、文档索引、Skill safety 和现行 acceptance 文档，明确 2.4 的 `CLOSED_WITH_UPSTREAM_BLOCKER`、当前上下文计划层边界和敏感信息优先级；所有二期链接只指向本文件。
- 增加 ADR 0006/0007/0008，分别记录 MCP Apps 双前端、UI direct execution 安全模型和 surface profile 隔离。
- 二期执行闸门引用 v1.1 本机受控验收报告；未关闭前不得新增 UI 写入工具、协议画像或 schema 例外。

**D0 验收：**仓库只存在一份现行二期计划；历史文档可从归档目录打开；没有 README、AGENTS、Skill safety 和 acceptance 文档之间的冲突表述。2.4 的应用执行保持上游阻塞，不作为 D0 或 v1.1 的成功能力。

### D1：v1.2.0 Codex Desktop 最小兼容 Spike

D1 及之后的节点在本轮不启动。开始条件是 v1.1 其它验收完成、敏感信息确定性 `Replace/Redact/Protect` 计划层已优先实现并验收，并收到明确的二期启动要求；2.4 的上游阻塞不得通过文档或测试改写为已通过。

只用合成数据和无副作用测试工具验证：

- 本机个人插件清单、稳定路径和 `ui-stdio` 启动链。
- `resources/list/read`、版本化 HTML Resource、`render_review_demo`。
- inline/fullscreen、重载、断线重连、无 UI 退化和 `ui/*` bridge。
- `_meta` 与 `structuredContent` 隔离，以及 app-only 工具的模型不可见性。
- 插件重启后旧 capability 失效，跨数据根/跨 UI build 使用被拒绝。

**D1 硬门禁：**真实 Codex Desktop 必须稳定渲染并交互；模型不得发现或调用 app-only 工具；UI-only `_meta` 不得进入对话上下文；不支持 UI 时普通 MCP 结果仍可用。任一项无法证明，停止 D3 的直接写入迁移，也不开始地图开发。

### D2：v1.2.0 UI 壳与执行基础

- 完成 MCP Apps 适配层、统一 React 审查壳、主题、风险提示、键盘焦点、响应式布局和分页。
- 完成 surface profile、UI session、grant、执行账本、幂等、异常状态和 reconcile。
- 仅在临时数据根和假 App Server 中启用未来执行器的回环；上下文应用仍须额外通过真实 round-trip 门禁。
- 将静态资源加入 wheel、macOS 和 Windows bundle；构建产物不得依赖 Node。
- 在 ADR 通过和安全测试完成后，把现行 MCP 写入禁令改为“远程/headless 禁止，本机个人插件 app-only 固定执行器例外”。

**D2 验收：**Spike 和故障矩阵通过；现有 MCP 工具兼容测试不回退；远程/headless profile 无法发现或调用执行器；standalone 能在无 Python/uv/Node 环境中加载 UI 资源。

### D3：v1.3.0 一期功能全量迁入 Codex UI

按以下顺序实现并分别验收：

1. 项目/任务/时间线、搜索、多选和 Pending 中心。
2. 清理预览、归档、取消归档、重命名、备份并归档。
3. 上下文审查与投影计划、差异预览和 Pending 续办；派生任务仅在未来执行器通过硬门禁后加入。
4. 记忆编辑、版本备份、原子应用、并发漂移拒绝和恢复。
5. 备份、验证、逻辑恢复和隔离导入。
6. 永久删除独立流程。

每一项都必须复用 D2 的 grant/账本/reconcile，不允许页面自行调用 App Server 或直接访问文件。

**D3 验收：**真实 Codex Desktop、本机批准的 App Server schema 和隔离测试账号中，一期可执行页面完成“盘点—计划—确认—执行—回读—审计”闭环；上下文页面在执行器未通过前只完成“审查—计划—源任务保护”闭环。重启/超时/部分成功不会重复写入；原任务、后代闭包、备份证据和记忆版本符合现有 CLI/PySide 结果。

### D4：v1.4.0 原二期只读会话地图

- 拆分原 GUI controller，使 controller、MCP 和 Codex UI 都只经 `ApplicationWorkflows` 调用业务逻辑。
- 建立 workspace 领域模型和独立 `workspace.sqlite3`，绑定 Codex 账号根但不替代 App Server 事实。
- 交付 PySide6 Map/List 只读 MVP：手动导入、布局、缩放、搜索、关系边和缓存状态。
- 地图卡片删除只改 workspace；数据库损坏只禁用地图；账号根变化时进入只读隔离；App Server 离线时可查看最后缓存。
- 地图操作只打开 D3 审查页面，不直接归档、删除、裁剪或修改记忆。

**D4 验收：**关闭重开后位置/视口一致；地图与 Codex 数据隔离；删除卡片不改变 Codex 任务；不自动导入全账号、不自动调用 LLM、不产生写入。

### D5：v1.5.0 摘要、上下文分叉与统一备份

- 增加本地 Resume Digest、输入哈希去重、失败保留旧摘要和来源显示；LLM 摘要默认关闭。
- 仅在上下文执行器通过完整官方能力和真实 round-trip 门禁后，增加经计划确认的上下文分叉、派生任务落图、provenance edge 和 `PendingMapPlacement` 崩溃恢复。
- 将 workspace sidecar 纳入 age 加密备份、隔离恢复、Pending 和审计中心。
- 在 MCP Apps 统一壳中增加只读地图视图，默认只提供卡片 ID、关系、状态和摘要存在性。

**D5 验收：**摘要失败不清空旧版本；相同输入不重复计算；派生任务已创建但落图中断时可恢复；地图备份可验证、可隔离恢复；模型默认看不到摘要正文。

## 4. 测试与验收矩阵

### 4.1 自动化门禁

每个节点必须执行并保存脱敏证据：

- `scripts/check.sh`。
- 前端 `npm ci`、类型检查、单元测试、构建和构建产物可重复性检查。
- MCP schema、Resource、Tool Result、`_meta`、visibility、session/grant 和账本测试。
- `scripts/test_source_workflow.sh`；涉及安装、Skill、Hook、macOS 或 Windows 时执行对应 workflow。
- wheel、macOS arm64、Windows AMD64 bundle 的静态资源、无 Node 运行依赖、中文/空格路径和可写用户目录检查。
- 大量任务、JSONL、附件和 UI 列表的分页、流式读取和有界缓存检查。

### 4.2 安全故障矩阵

必须覆盖计划过期、计划/能力/内容指纹变化、后代闭包变化、账号根变化、未知字段、grant 过期、nonce 重放、跨 session 使用、重复幂等键、写前断线、写后响应丢失、批量部分成功、进程重启、备份损坏、错误 identity、恢复回读不一致、可信归档证据缺失或与备份 manifest 不一致、进程仍运行和确认挑战错误。

结果必须遵循：

- 不确定写入进入 `UNKNOWN`/`RECONCILIATION_REQUIRED`。
- 只有服务端回读确认后才能生成新的后续计划。
- 任何失败不得把未完成操作报告为已归档、已删除、已恢复或已修改。
- 任何 capability、密钥、口令、正文或绝对路径均不得出现在模型结果和日志。

### 4.3 真实环境分层

验收报告必须分开记录：

1. 单元、schema 和前端测试。
2. 假 App Server、临时数据根和 offscreen UI。
3. 本机构建、wheel、standalone 和安装流程。
4. 真实 Codex Desktop 本机插件 UI，包括 iframe、重连、模型隔离和 app-only 调用。
5. 真实 App Server、真实用户输入和隔离账号生命周期。
6. macOS arm64、Windows AMD64 目标平台验收。
7. Developer ID/公证/staple、Authenticode、干净机和正式发布验收。

前四层不能替代真实账号和目标平台验收；未完成签名、公证或 Authenticode 时，产物只能标为测试版。

### 4.4 v1.3 一期功能通过条件

- 清理：最终选择、完整后代闭包、备份并归档、取消归档、重命名和批量部分失败均可从回读与审计核对。
- 上下文：计划层保持源任务不变；工具调用与结果整体保留或整体摘要；未知 item 被保留并标记；当前派生投影为 `blocked_upstream`，执行器通过后才验收派生任务和 Pending 应用状态。
- 记忆：来源登记、结构保护、完整 diff、版本备份、原子写入、回读验证、恢复和并发漂移拒绝全部通过。
- 备份恢复：age、清单、散列、错误 identity、损坏包和隔离恢复全部通过；不覆盖现有数据。
- 永久删除：当前应用不可执行；未来先关闭 App Server 版本迁移兼容和 descendant 完整删除 blocker，再按 ADR 0010 复核用户主动单选、独立计划、CSM 可信归档、archive-bound 当前备份、进程门禁、精确挑战和单根闭包。
- UI：inline/fullscreen、键盘操作、焦点、对比度、长列表分页、禁用状态、错误提示、重连和窗口重启通过真实 Codex Desktop。

## 5. 目录、Git 和文档维护规则

- 正式现行计划和历史归档属于项目治理证据，必须提交到 Git；不得使用宽泛的 `docs/*plan*.md` 忽略规则。
- `agent_team/` 仅保存本地 Agent 协作状态、任务板和复核 packet，不是产品源码或发布输入；从 Git 索引移除并加入忽略，保留本机文件供当前工作流使用。
- 新增以下本地草稿/临时目录的忽略规则：`docs/superpowers/plans/`、`docs/_drafts/`、`agent_team/`。构建、缓存、测试和验收产物继续使用现有 `build/`、`dist/`、`artifacts/` 等忽略规则。
- 归档文档保持原文，不在归档文件内追加新事实；所有新决策写入本文件或 ADR。
- 每个版本节点使用聚焦的中文 Conventional Commit；提交前执行 `git diff --cached --check`、`git diff --cached --name-status` 和统计，提交后复核无关路径状态。

## 6. 二期最终完成定义

二期只有在以下条件全部满足时才算完成：

- v1.1.0 本机受控验收已关闭，并且二期所有直接写入均命中批准的 App Server schema。
- v1.3.0 在真实 Codex Desktop 中完成一期功能全量 UI、直接执行、回读、审计和异常续办验收。
- v1.4.0/v1.5.0 完成 workspace 隔离地图、恢复现场摘要、来源可追踪上下文分叉、崩溃恢复和统一备份。
- 自动化、本机构建、真实宿主、隔离账号和目标平台证据已分层记录；未通过的层级明确标记，不得以其他层级替代。
- PySide6、CLI、Skill、Hook、远程/headless MCP 和正式发布安全边界没有被 Codex UI 迁移削弱。
