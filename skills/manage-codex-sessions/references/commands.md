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
csm cleanup plan --action archive --older-than-days 90
csm backup create OUT.csmbackup --thread TASK_ID --recipient AGE_RECIPIENT --identity IDENTITY_FILE
csm cleanup apply PLAN.json --confirm PLAN_ID
csm cleanup reconcile PLAN.json --confirm PLAN_ID
csm purge plan
csm purge apply PLAN.json --confirm PLAN_ID --permanent-phrase "PERMANENTLY DELETE CODEX TASKS"
```

`reconcile` 只在 Codex App 原生任务工具已完成归档后使用；它不执行 Codex 写入。

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
csm hook status
csm hook install --yes
csm hook uninstall --yes
csm audit verify
csm audit show
```
