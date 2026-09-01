# Task 6 fix 2 报告：修复第二轮文档收口发现

## 任务与范围

- task_id：`csm-opcontracts-20260902-t6fix2-a1`
- 基线：`7a97aad`
- 工作目录：独立的 clean archive 临时目录，由 `git archive 7a97aad` 解包后仅在该目录修改。
- 主工作区和主 Git index 仅作只读参考；未创建分支、提交或推送，也未创建 subagent。
- 运行时代码未修改；本轮不启动 D1+，不改变 Task 6.5A 的 CLI 期望。

## 修复

- 为四份历史文档只增加顶部 marker，分别链接 ADR 0011 和当前验收索引；阶段 2.5/ADR 0010 的永久删除（purge）结论全文退役，ADR 0002/0009 仅取代 purge 与旧精确版本/画像授权表述，并保留其计划、闭包、上下文延期和来源保护决策。
- 两份当前计划不再把第一版标题修改/重命名列为交付内容；保留的相关表述明确限定为 v1.1 之后的研究，必须另行决策、定义操作契约并完成真实验收，本轮不启动 D1+。
- `skills/manage-codex-sessions/references/commands.md` 移除 restore/import/trim 的四个 Codex 写入 apply 命令行，保留 plan/review/suggest，并明确第一版不可用；memory apply/restore apply 保留。
- `tests/test_skill_contract.py` 改为逐文件断言当前关键边界，纳入四份历史路径和 marker；不使用跨文档 joined 文本，也不要求历史正文删除旧术语。
- 本报告同步改为本轮 task、基线、范围和证据。

## 验证

以下均在上述 clean archive、使用项目 uv 和独立临时 `UV_CACHE_DIR` 执行：

```text
marker-only body equality: 4/4
uv run --locked pytest tests/test_skill_contract.py -q
7 passed
uv run --locked ruff format --check tests/test_skill_contract.py
1 file already formatted
uv run --locked ruff check tests/test_skill_contract.py
All checks passed!
```

`git diff --check` 通过；精确 changed-path audit：`9/9`，仅包含本任务声明的九个 tracked 路径。对 fresh `7a97aad` archive 的 `git apply --cached --check`：通过。

## 证据边界

- 本轮只证明 clean source archive 中的文档、Skill contract tests、Ruff 和差异检查；未执行 fresh bundle、真实 Codex Desktop、真实账号、真实用户输入、目标平台、签名/公证或生产验收。
- 未修改运行时 CLI 命令集合、Codex JSONL、SQLite、认证文件或配置；没有执行归档、反归档、永久删除、恢复/导入写入或上下文应用。
- `scripts/check.sh`、bundle workflow 和真实账号验收不属于本轮最小验证，结果不得从本报告推断。

## SDD_STATUS

`COMPLETED`：第二轮文档与 Skill 契约收口已在声明范围内完成；运行时退休、D1+ 和真实 bundle/账号验收保持独立门禁。
