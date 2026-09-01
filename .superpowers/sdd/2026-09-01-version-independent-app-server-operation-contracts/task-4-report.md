# Task 4 报告：Schema audit v2 与逐操作诊断证据

## 实现

- `SchemaAuditReport` 升级为 `schema_version=2`，移除精确画像和全局 `write_enabled` 字段，直接封存五项 `operation_capabilities`。
- 结论只由五项能力与 `probe_error` 产生：全可用为 `compatible`，schema 可评估但有失败为 `partial`，探测错误为 `unavailable`。
- `probe_error` 在报告边界统一限制长度并脱敏 home、用户名、POSIX/Windows 私有路径，同时保留可诊断错误类别/消息。
- doctor 将 `inventory.common` 作为必需读取门禁，其余 history/archive/unarchive 作为独立的可选操作检查；CLI schema audit 输出逐操作能力，不再输出授权布尔值。
- acceptance runner 的 pending-plan fixture 明确构造五项合成能力，并将 fixture/offscreen 证据标签写入检查详情。

## TDD 与验证

RED（实现前）：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_schema_audit.py tests/test_doctor.py tests/test_cli.py -q
1 failed, 19 passed
```

失败为旧 doctor 仍读取已删除的 `CapabilityMatrix.write_enabled`，确认了 caller 迁移缺口。

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_schema_audit.py tests/test_doctor.py tests/test_cli.py tests/test_acceptance_runner.py -q
25 passed
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked ruff check src/codex_session_manager/schema_audit.py src/codex_session_manager/doctor.py src/codex_session_manager/cli.py src/codex_session_manager/acceptance_runner.py tests/test_schema_audit.py tests/test_doctor.py tests/test_cli.py tests/test_acceptance_runner.py
All checks passed!
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked mypy src/codex_session_manager/schema_audit.py src/codex_session_manager/doctor.py src/codex_session_manager/cli.py src/codex_session_manager/acceptance_runner.py
Success: no issues found in 4 source files
```

未运行真实账号写入、bundle、签名、公证或发布验收；这些仍需目标环境门禁。
