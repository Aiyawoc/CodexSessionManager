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
csm cleanup review --request REVIEW_REQUEST.json
csm cleanup plan --action archive --older-than-days 90
csm backup create OUT.csmbackup --thread TASK_ID --recipient AGE_RECIPIENT --identity IDENTITY_FILE
csm cleanup apply PLAN.json --confirm PLAN_ID
csm cleanup reconcile PLAN.json --confirm PLAN_ID
csm purge plan
csm purge apply PLAN.json --confirm PLAN_ID --permanent-phrase "PERMANENTLY DELETE CODEX TASKS"
```

`reconcile` 只在 Codex App 原生任务工具已完成归档后使用；它不执行 Codex 写入。

`cleanup review` 只生成结构化建议和桌面审查请求，不创建归档 ActionPlan，也不满足备份或执行授权。

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

## 裁剪与 Hook

```text
csm trim review TASK_ID
csm trim suggest TASK_ID
csm trim apply PLAN.json --confirm PLAN_ID
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
