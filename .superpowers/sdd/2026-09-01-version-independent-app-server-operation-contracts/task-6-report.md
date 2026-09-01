# Task 6 fix 1 报告：收口文档与 Skill 契约残留

## 任务与范围

- task_id：`csm-opcontracts-20260902-t6fix1-a1`
- 基线：`a8c0f39`
- 工作目录：由 `git archive a8c0f39` 解包的 clean archive；主工作区仅作只读参考。
- 运行时实现未修改；runtime retirement 保留给独立后续任务。

## 变更

- `AGENTS.md` 改为指向 `operation_contracts.py` 和只读 `schema_audit.py`。
- 上下文计划改用版本无关、逐操作契约边界，明确当前仅允许 archive/unarchive；上下文应用、purge、rename、restore/import 写入、trim/context apply 和 MCP 写入不可用。
- 二期计划移除永久删除交付项和 `execute_purge_plan`，明确 D1+ 尚未启动，并把敏感信息 `Replace/Redact/Protect`、diff、fingerprint 和风险控制保留为 v1.1 验收后的下一优先级。
- 验收索引改称操作契约审查，删除永久删除历史的悬空入口；本机受控验收移除不存在的 purge archive link，并改为待归档说明。
- 2.4 历史正文未改写，仅在顶部增加指向 ADR 0011 和当前验收索引的 `SUPERSEDED IN PART` marker。
- Skill 契约测试按文件独立校验当前文档的版本无关/契约敏感边界，并扫描 live `protocol_profiles`、全局 `write_enabled`、精确画像授权和永久删除交付残留；历史正文与测试负向字面量不纳入 current-doc 扫描。

## 验证

以下均在 clean archive、使用项目 uv 和 `UV_CACHE_DIR=/private/tmp/csm-uv-cache` 执行：

```text
pytest tests/test_skill_contract.py -q
6 passed in 1.06s

ruff format --check tests/test_skill_contract.py
1 file already formatted

ruff check tests/test_skill_contract.py
All checks passed!

python scripts/validate_skill.py skills/manage-codex-sessions
Skill valid
```

聚焦 `rg` 检查确认 current docs 无 live `protocol_profiles`、`write_enabled`、精确画像授权或永久删除交付标记。允许命中仅为历史 `SUPERSEDED` 文档正文，以及 `tests/test_skill_contract.py` 中用于负向断言的字面量。

`scripts/test_skill_workflow.sh`：`NOT_RUN`，按 Task 6 要求延期至 Task 7；clean source archive 不包含 `dist` app，无法满足该 workflow 的 fresh-bundle 前置条件。

## 证据边界与关注项

- 本轮证据是 clean source archive 的文档、Skill validator、pytest 和 Ruff 结果；不等同于真实账号、真实用户输入、fresh bundle、目标平台、签名/公证或生产验收。
- 主工作区既有未暂存变更未被恢复、覆盖、暂存或提交；本轮只提交上述 8 个 Task 6 所有权路径。
- 本报告随聚焦提交写入；提交短 SHA 在任务回执中记录。

## SDD_STATUS

`COMPLETED`：Task 6 fix 1 review findings are closed within the documentation/Skill boundary; runtime retirement and Task 7 fresh-bundle Skill workflow remain separate follow-ups.
