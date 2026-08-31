---
name: manage-codex-sessions
description: 安全管理 Codex App 中的任务，包括按项目与时间盘点、计划式归档或清理、age 加密备份和验证、逻辑恢复、跨账号 ChatGPT/Codex 导入去重，以及上下文审查与投影计划。仅在用户显式调用 $manage-codex-sessions，或明确要求使用本 Skill 时使用；涉及永久删除、Hook 安装、恢复、导入或上下文计划时必须使用本 Skill 的计划、确认和审计流程。
---

# Manage Codex Sessions

使用 `csm` 执行确定性盘点、计划、校验和审计。把 Codex App Server 视为在线管理的唯一协议边界；禁止直接修改 Codex JSONL、SQLite、认证或配置。

## 解析已安装运行入口

1. 先从当前 shell 解析 `csm`（POSIX 使用 `command -v csm`，PowerShell 使用 `Get-Command csm`）。若存在，后续命令直接使用 `csm ...`。
2. 若 `csm` 不在 `PATH`，则检查平台稳定入口：macOS 为 `~/Applications/CodexSessionManager.app/Contents/MacOS/CodexSessionManager`，Windows 为 `%LOCALAPPDATA%\CodexSessionManager\CodexSessionManager.exe`。使用稳定入口时，在所有 CLI 子命令前加 `cli`。
3. 两类入口都不存在时停止操作，并提示用户先安装当前平台 standalone 应用。除非用户明确处于源码开发模式，否则不要回退到 `uv`、`.venv` 或系统 Python。
4. 用户要求从 Codex 打开上下文审查界面时，使用上述入口执行 `trim review TASK_ID`；该进程会打开独立 PySide6 GUI，并保持原任务只读。

## 先建立安全状态

1. 运行 `csm doctor`。若使用源码开发环境，只运行 `uv run --locked csm doctor`；不要调用系统 Python 或全局 pip。
2. 若 `doctor` 报告未知/不完整 App Server schema，只执行读取、备份、验证和计划。停止所有 Codex 写入。
3. 先运行 `csm threads list` 或 `csm threads show TASK_ID`。不要把 `transcript_path` 或 rollout 路径当作稳定接口。
4. 写操作前读取 [安全不变量](references/safety.md)。需要命令参数时读取 [命令工作流](references/commands.md)。

## 盘点与清理

1. 用项目 cwd、Git remote、时间、状态、来源、归档、固定和父子关系筛选。
2. 需要桌面审查时先运行 `csm cleanup review --older-than-days 90`。该命令只生成密封的 `SuggestionBundle`/`ReviewRequest`，并把 LLM/本地初筛候选按项目灌入原有项目/任务 GUI；它不创建 ActionPlan，也不执行归档。
3. GUI 会预选建议归档的根对话，并在每个根下展示全部已知派生后代、总大小、风险、建议理由和当前备份覆盖。当前真实盘点中的其他安全根目标作为“可补选”项显示，默认不选中；用户必须在原任务列表中取消或调整最终选择。
4. 用户点击“备份并归档”后只选择输出路径。首次确认后，GUI 在 CSM 私有数据目录生成一个原生 age identity，以后自动派生 recipient 并复用同一私钥完整解密复验。程序再重读 App Server 状态、复核建议指纹与后代闭包、生成最终 ActionPlan 并归档。任一步失败都停止。
5. 备份 manifest、最终计划和归档结果通过关联审计事件绑定。已经完成备份但随后发生内容或状态漂移时，备份保留，归档拒绝执行。
6. 需要独立生成或手工分步执行时仍可运行 `csm cleanup plan`、`csm backup create/verify` 和 `csm cleanup apply`；这些 CLI 路径使用相同门禁。
7. 不自动永久删除。GUI 和 `csm cleanup eligible-purge` 只读展示同时满足 14 天 CSM 可信归档历史、完整后代闭包和当前有效备份的根候选，默认不选中，也不生成删除计划。只有用户明确要求时才运行 `csm purge plan`，并让用户本人提供精确 plan ID 和固定永久删除确认短语。

默认 90 天未活动进入候选；单批最多 100 个根任务。自动操作的上限永远是归档。

## 备份、恢复与导入

- GUI 使用一个本机托管的 age recipient-key：首次生成，后续自动复用，丢失或损坏时拒绝静默替换。CLI 仍由用户在本地终端显式提供 `--recipient` 和 `--identity`。
- 口令模式只让用户在真实终端直接运行 `csm ... --passphrase`。不要询问、接收、转述、保存或代填口令；不要把口令放入参数、环境变量、日志或模型上下文。
- 创建后必须执行完整解密校验，并从逻辑条目重新计算嵌入任务 fingerprint；失败时不要把文件登记为有效备份或删除门禁证据。
- 恢复先 `plan`，再用同一加密源进行第二遍解密和 `apply`。V1 只逻辑恢复；raw rollout 仅作加密灾备，不原样写回。
- 把工具调用和结果作为惰性 sidecar 保存；永不执行或重放。
- ChatGPT 导出按根到叶分支创建候选。完全相同跳过，前缀选择较完整版本，分叉并存。
- 未经用户确认项目映射时导入隔离区。不得猜测 cwd 或 Git remote。

## 上下文审查与投影计划

1. 用 `csm trim review TASK_ID` 或 `csm gui open --page context` 打开原有时间线/上下文/动作 GUI；也可用 `csm trim suggest TASK_ID` 生成本地规则建议。
2. 默认在 turn 级处理；只有用户需要时进入 item 级。将 `keep`、`exclude`、`summary`、`protect` 的含义和预计节省量展示给用户。
3. 硬保护当前请求、进行中 turn、有效目标、审批决定、未解决错误和未知 item。工具调用/结果以及文件变更/验证必须整体保留或整体摘要。
4. 内容 AI 默认关闭。只有用户显式同意并已配置清晰的数据边界时才启用；外部建议必须先由本地绑定当前 turn/item 指纹，再灌入原 GUI，且不得覆盖硬保护。
5. 保存不可变 TrimPlan 只保存上下文投影计划，不写入 Codex；当前不要运行 `csm trim apply`，也不要把它作为可用结果。
6. 当前上下文应用执行层保持关闭：原任务不可应用，派生投影的真实 round-trip 尚未通过。`thread/inject_items` 的方法存在、返回 `{}` 或目标 ID 已创建，都不能证明持久化或后续模型可见；只有完整 probe 通过并重新批准能力后才可研究执行。

PreCompact Hook 只保存计划。在 GUI 关闭、崩溃、启动失败或超时后继续原生压缩；默认 fail-open。只有用户明确选择严格审查、计划已原子持久化且当前能力、协议 fingerprint、源内容 fingerprint 和选择语义均通过复核时，才允许 `continue:false`。即使原生 compact 完成，补充说明也只能是语义纠正，不能称为确定性删除或硬脱敏。

已保存的 TrimPlan 和未被桌面接收的 ReviewRequest 可在 `csm gui open --page pending` 中只读查看。当前待处理页只负责索引和打开复核，不表示计划仍然可执行；真正应用前必须重新探测源任务状态、能力与内容指纹。

当前边界：上下文审查与投影计划可用；应用到原任务不可用；派生投影当前真实 round-trip 失败并保持阻塞。敏感信息的确定性 `Replace/Redact/Protect` 是后续优先方向，2.5 永久删除继续按独立计划、等待期、备份和确认门禁验收。

## 记忆管理

- 先用 `csm memory register FILE --root ROOT` 显式登记本地 UTF-8 Markdown/文本文件。禁止猜测目录；拒绝符号链接、路径逃逸和未登记路径。`AGENTS.md` 等指令文件只有用户明确要求时才使用 `--allow-instruction-file`。
- 用 `csm memory show SOURCE_ID` 查看稳定分段、segment ID 和当前 source fingerprint；用 `csm memory review SOURCE_ID` 在原 GUI 左侧第二按钮中审查。
- LLM 只能经 `inspect_memory_source` 和 `prepare_memory_suggestions` 提出 `KEEP/DELETE/REPLACE/PROTECT`。本地重新绑定 segment ID 与内容 SHA-256；标题、front matter、代码块和结构空白的硬保护不能被建议覆盖。
- GUI 或 `csm memory plan` 必须展示最终 unified diff。`csm memory apply PLAN --confirm PLAN_ID` 会在写入前重新检查内容、mtime、inode、模式和路径，创建私有版本备份，再使用同目录临时文件、flush、fsync、原子替换和重读验证。
- 用 `csm memory history SOURCE_ID` 查看已验证版本。恢复必须先 `csm memory restore plan`，再以精确 plan ID 执行；覆盖前再次备份当前版本。
- 记忆功能只管理明确登记的本地文件，不声称管理 ChatGPT 服务器端 Memory。

## MCP 编排边界

- `csm mcp serve` 只注册盘点、建议准备、打开审查、状态查询和只读演示工具。
- 允许调用：`inspect_conversation_inventory`、`prepare_cleanup_suggestions`、`open_cleanup_review`、`prepare_context_suggestions`、`open_context_review`、`inspect_memory_source`、`prepare_memory_suggestions`、`open_memory_review`、`get_pending_review_status`、`open_review_demo`。
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
