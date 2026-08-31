# 命令工作流

## 运行入口

已安装应用：

```text
csm doctor
```

源码开发：

```text
uv run --locked csm doctor
```

Hook 中禁止使用 `uv`、`.venv`、网络下载或依赖安装。

## 盘点、归档和删除

```text
csm threads list --project /absolute/project/path
csm threads show TASK_ID
csm cleanup review --older-than-days 90
csm acceptance run --output acceptance-report.json
csm acceptance release --output release-acceptance.json
csm mcp serve --host 127.0.0.1 --port 8765
csm cleanup review --request REVIEW_REQUEST.json
csm cleanup plan --action archive --older-than-days 90
csm backup create OUT.csmbackup --thread TASK_ID --recipient AGE_RECIPIENT --identity IDENTITY_FILE
csm cleanup apply PLAN.json --confirm PLAN_ID
csm cleanup reconcile PLAN.json --confirm PLAN_ID
csm purge plan
csm purge apply PLAN.json --confirm PLAN_ID --permanent-phrase "PERMANENTLY DELETE CODEX TASKS"
```

`reconcile` 只在 Codex App 原生任务工具已完成归档后使用；它不执行 Codex 写入。

选择根任务创建备份时，CSM 会自动展开其完整派生后代；输出中的 `covered_thread_ids` 必须与随后归档计划的 affected IDs 对齐。
`cleanup review` 只生成结构化建议和桌面审查请求，不创建归档 ActionPlan，也不满足备份或执行授权。
清理请求会把候选灌入原有项目/任务列表并预选；用户在同一 GUI 中调整最终选择。“备份并归档”只要求选择输出路径；首次确认创建本机托管的 age identity，后续自动复用。程序先完整复验备份，再重读状态和建议指纹、重建最终 ActionPlan 并执行；失败时不会继续归档。CLI 命令仍提供显式 recipient/identity 的分步路径。上下文请求会把本地绑定指纹后的 turn/item 建议灌入原时间线与动作面板；它只准备审查和投影计划，不执行 Codex 上下文应用。

## 备份、恢复与导入

```text
csm backup verify OUT.csmbackup --identity IDENTITY_FILE
csm restore plan OUT.csmbackup --identity IDENTITY_FILE --map-cwd /confirmed/path
csm restore apply PLAN.json OUT.csmbackup --confirm PLAN_ID --identity IDENTITY_FILE
csm import chatgpt plan conversations.json --source-account LABEL --map-cwd /confirmed/path
csm import chatgpt apply PLAN.json conversations.json --confirm PLAN_ID --source-account LABEL
csm import codex plan /path/to/other/.codex/sessions --source-account LABEL --map-cwd /confirmed/path
csm import codex apply PLAN.json /path/to/other/.codex/sessions --confirm PLAN_ID --source-account LABEL
```

口令模式把 `--identity` 替换成布尔 `--passphrase`，并让用户在终端直接操作。

## 上下文审查与投影计划及 Hook

```text
csm trim review TASK_ID
csm trim suggest TASK_ID
csm gui open --page cleanup
csm gui open --page context
csm gui open --page memory
csm gui open --page pending
csm gui open --page backup_restore
csm gui open --request REVIEW_REQUEST.json
csm hook status
csm hook install --yes
csm hook uninstall --yes
csm audit verify
csm audit show
```

`cleanup`、`context` 和 `memory` 三种 `--page` 值复用原有审查 GUI；记忆模式由左侧第二按钮切换。`pending` 与 `backup_restore` 使用辅助入口。

当前基线不运行 `csm trim apply`：原任务应用不可用，派生投影的真实 round-trip 失败。`thread/inject_items` 返回 `{}`、目标 ID 已创建或方法存在，都不能视为投影写入成功；只有完整 probe 通过并重新批准能力后才可恢复研究。

CLI 仍保留以下兼容命令路径供版本契约检查，但它不是当前可交付写能力，禁止在本基线上运行：

```text
csm trim apply PLAN.json --confirm PLAN_ID
```

## 记忆文件管理

```text
csm memory register /confirmed/root/MEMORY.md --root /confirmed/root
csm memory unregister SOURCE_ID
csm memory sources
csm memory list
csm memory show SOURCE_ID
csm memory suggest SOURCE_ID
csm memory review SOURCE_ID
csm memory plan SOURCE_ID --delete SEGMENT_ID --replace SEGMENT_ID=TEXT --protect SEGMENT_ID
csm memory apply PLAN.json --confirm PLAN_ID
csm memory history SOURCE_ID
csm memory restore plan SOURCE_ID BACKUP_ID
csm memory restore apply PLAN.json --confirm PLAN_ID
```

只有 `register` 明确登记的 UTF-8 Markdown/文本文件可进入记忆流程。`AGENTS.md` 等指令文件还需要 `--allow-instruction-file`。`plan` 只保存不可变方案并输出 unified diff；`apply` 在精确 plan ID 确认后创建私有版本、复核内容/mtime/inode/模式、原子替换并重读验证。恢复也先创建计划，并在覆盖前再次备份当前版本。

## 维护者协议与验收证据

以下命令只生成 CSM 自有的只读/脱敏报告，不执行 Codex 写入，也不能绕过真实账号人工阶段：

```text
csm schema audit --output schema-audit-v1.json
csm acceptance report acceptance-v1.json --schema-report schema-audit-v1.json --stage doctor=passed
csm acceptance run --output acceptance-first-delivery.json
csm acceptance release --output acceptance-release.json
```

未知 schema 报告不得自动加入信任列表。验收报告只接受固定阶段、散列任务 ID 和 SHA-256，并始终标记 `production_ready: false`。
