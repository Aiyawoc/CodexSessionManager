---
name: manage-codex-sessions
description: 安全管理 Codex App 中的任务，包括按项目与时间盘点、计划式归档或清理、age 加密备份和验证、逻辑恢复、跨账号 ChatGPT/Codex 导入去重，以及创建派生任务的上下文裁剪。仅在用户显式调用 $manage-codex-sessions，或明确要求使用本 Skill 时使用；涉及永久删除、Hook 安装、恢复、导入或任务裁剪时必须使用本 Skill 的计划、确认和审计流程。
---

# Manage Codex Sessions

使用 `csm` 执行确定性盘点、计划、校验和审计。把 Codex App Server 视为在线管理的唯一协议边界；禁止直接修改 Codex JSONL、SQLite、认证或配置。

## 解析已安装运行入口

1. 先从当前 shell 解析 `csm`（POSIX 使用 `command -v csm`，PowerShell 使用 `Get-Command csm`）。若存在，后续命令直接使用 `csm ...`。
2. 若 `csm` 不在 `PATH`，则检查平台稳定入口：macOS 为 `~/Applications/CodexSessionManager.app/Contents/MacOS/CodexSessionManager`，Windows 为 `%LOCALAPPDATA%\CodexSessionManager\CodexSessionManager.exe`。使用稳定入口时，在所有 CLI 子命令前加 `cli`。
3. 两类入口都不存在时停止操作，并提示用户先安装当前平台 standalone 应用。除非用户明确处于源码开发模式，否则不要回退到 `uv`、`.venv` 或系统 Python。
4. 用户要求从 Codex 打开裁剪界面时，使用上述入口执行 `trim review TASK_ID`；该进程会打开独立 PySide6 GUI，并保持原任务只读。

## 先建立安全状态

1. 运行 `csm doctor`。若使用源码开发环境，只运行 `uv run --locked csm doctor`；不要调用系统 Python 或全局 pip。
2. 若 `doctor` 报告未知/不完整 App Server schema，只执行读取、备份、验证和计划。停止所有 Codex 写入。
3. 先运行 `csm threads list` 或 `csm threads show TASK_ID`。不要把 `transcript_path` 或 rollout 路径当作稳定接口。
4. 写操作前读取 [安全不变量](references/safety.md)。需要命令参数时读取 [命令工作流](references/commands.md)。

## 盘点与清理

1. 用项目 cwd、Git remote、时间、状态、来源、归档、固定和父子关系筛选。
2. 需要桌面审查时先运行 `csm cleanup review --older-than-days 90`。该命令只生成密封的 `SuggestionBundle`/`ReviewRequest`，并把 LLM/本地初筛候选按项目灌入原有项目/任务 GUI；它不创建 ActionPlan，也不执行归档。
3. GUI 会预选建议归档的根对话，并在每个根下展示全部已知派生后代、总大小、风险、建议理由和当前备份覆盖。当前真实盘点中的其他安全根目标作为“可补选”项显示，默认不选中；用户必须在原任务列表中取消或调整最终选择。
4. 用户点击“备份并归档”后，在本地选择 age recipient、复验 identity 和输出路径。程序先冻结影响范围、创建加密备份并完整解密验证；成功后重新读取 App Server 状态、复核建议指纹与后代闭包、生成新的最终 ActionPlan，再由 CleanupExecutor 执行归档。任一步失败都停止后续归档。
5. 备份 manifest、最终计划和归档结果通过关联审计事件绑定。已经完成备份但随后发生内容或状态漂移时，备份保留，归档拒绝执行。
6. 需要独立生成或手工分步执行时仍可运行 `csm cleanup plan`、`csm backup create/verify` 和 `csm cleanup apply`；这些 CLI 路径使用相同门禁。
7. 不自动永久删除。GUI 和 `csm cleanup eligible-purge` 只读展示同时满足 14 天 CSM 可信归档历史、完整后代闭包和当前有效备份的根候选，默认不选中，也不生成删除计划。只有用户明确要求时才运行 `csm purge plan`，并让用户本人提供精确 plan ID 和固定永久删除确认短语。

默认 90 天未活动进入候选；单批最多 100 个根任务。自动操作的上限永远是归档。

## 备份、恢复与导入

- 优先使用 age recipient-key。把 `--recipient` 和用于复验的 `--identity` 留在本地终端/GUI。
- 口令模式只让用户在真实终端直接运行 `csm ... --passphrase`。不要询问、接收、转述、保存或代填口令；不要把口令放入参数、环境变量、日志或模型上下文。
- 创建后必须执行完整解密校验，并从逻辑条目重新计算嵌入任务 fingerprint；失败时不要把文件登记为有效备份或删除门禁证据。
- 恢复先 `plan`，再用同一加密源进行第二遍解密和 `apply`。V1 只逻辑恢复；raw rollout 仅作加密灾备，不原样写回。
- 把工具调用和结果作为惰性 sidecar 保存；永不执行或重放。
- ChatGPT 导出按根到叶分支创建候选。完全相同跳过，前缀选择较完整版本，分叉并存。
- 未经用户确认项目映射时导入隔离区。不得猜测 cwd 或 Git remote。

## 上下文裁剪

1. 用 `csm trim review TASK_ID` 或 `csm gui open --page context` 打开原有时间线/上下文/动作 GUI；也可用 `csm trim suggest TASK_ID` 生成本地规则建议。
2. 默认在 turn 级处理；只有用户需要时进入 item 级。将 `keep`、`exclude`、`summary`、`protect` 的含义和预计节省量展示给用户。
3. 硬保护当前请求、进行中 turn、有效目标、审批决定、未解决错误和未知 item。工具调用/结果以及文件变更/验证必须整体保留或整体摘要。
4. 内容 AI 默认关闭。只有用户显式同意并已配置清晰的数据边界时才启用；外部建议必须先由本地绑定当前 turn/item 指纹，再灌入原 GUI，且不得覆盖硬保护。
5. 保存不可变 TrimPlan 后，等待源任务 idle，再运行 `csm trim apply PLAN --confirm PLAN_ID`。
6. 裁剪只创建派生任务，不改写原任务，不自动启动模型 turn。非连续裁剪注入带来源 manifest 的 ContextProjection；连续前缀可用官方 fork。

PreCompact Hook 只保存计划。在 GUI 关闭、崩溃、启动失败或超时后继续原生压缩；只有当前 App Server 写能力、协议 fingerprint、源内容 fingerprint 和选择语义均通过复核，且 TrimPlan 已原子持久化时，才允许 `continue:false`。

已保存的 TrimPlan 和未被桌面接收的 ReviewRequest 可在 `csm gui open --page pending` 中只读查看。当前待处理页只负责索引和打开复核，不表示计划仍然可执行；真正应用前必须重新探测源任务状态、能力与内容指纹。

## 记忆管理

- 使用原 GUI 左侧工具栏第二个按钮进入记忆管理模式；`memory_edit` 请求会把明确请求的本地路径灌入同一任务列表和内容/动作布局。
- 当前模式只读，不读取或改写未登记路径，也不管理 ChatGPT 服务器端 Memory。
- 后续启用分段和写入时，仍必须由本地复核路径、指纹、diff、备份和原子写入；LLM 只能提供 `KEEP/DELETE/REPLACE/PROTECT` 建议。

## MCP 编排边界

- `csm mcp serve` 只注册盘点、建议准备、打开审查、状态查询和只读演示工具。
- 允许调用：`inspect_conversation_inventory`、`prepare_cleanup_suggestions`、`open_cleanup_review`、`prepare_context_suggestions`、`open_context_review`、`get_pending_review_status`、`open_review_demo`。
- MCP 不提供 `delete_*`、`purge_*`、归档执行、`execute_trim`、`apply_memory_edit` 或任何绕过 GUI 最终确认的工具。
- `prepare_*` 只把 LLM 给出的目标 ID 和理由绑定到本地当前指纹并保存不可变建议；不得把工具返回解释为已执行写入。
- 公网 Tunnel 前使用独立认证策略；静态 Bearer token 只从本地环境变量读取，不放入命令、日志、Issue 或模型上下文。
- `--allow-unauthenticated-local` 只允许显式回环 IP 的本机测试，不得用于 Cloudflare Tunnel 或其他公网入口。

## Hook 与安装

- 只有用户明确要求启用时才运行 `csm hook install --yes`。
- Hook 必须指向当前平台的稳定安装包内可执行文件；禁止指向源码、`.venv` 或 `uv`。
- 安装后提醒用户在 Codex `/hooks` 中审查并信任精确 Hook 定义。
- 卸载只移除 CSM 自己的条目，并保留原 `hooks.json` 备份。

## 报告结果

报告计划路径、plan ID、SHA-256、根数、后代总数、备份 manifest SHA-256、实际新建/归档对话 ID、审计结果和任何未满足的门。不要把 dry-run、假服务器、offscreen GUI 或本机构建称为真实 macOS/公开分发验收。
