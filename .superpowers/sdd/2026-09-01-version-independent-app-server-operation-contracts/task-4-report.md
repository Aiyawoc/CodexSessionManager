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

## 主 Agent 干净提交复验

- 主提交：`8898990 refactor(验收): 输出逐操作契约证据`。
- 首次 `git archive HEAD` 复验为 `24 passed, 1 failed`；唯一失败是 doctor 测试错误地要求全局 `report["ok"]` 为真，而干净源码快照按预期找不到仅随 bundle 提供的 `age` 与 `age-keygen`。
- 最小修复：`6704be6 test(验收): 隔离 doctor 环境依赖`，移除与该测试目标无关的环境总状态断言；仍明确断言公共盘点门禁成功，归档单项失败且 `required=False`。
- 新的干净 `git archive HEAD` 复验：25 个聚焦测试全部通过，Ruff 通过，4 个源文件严格 mypy 通过。
- 索引仅包含 Task 4 审核过的差异；同文件中的永久删除退役改动继续保留为未暂存用户工作。

## Round 1 脱敏修复

- 根因：原 POSIX/Windows 正则在空格处结束，导致已替换的路径前缀后仍暴露私有目录和文件名；`C:/` 还可能先命中 POSIX 分支。
- RED：新增 8 个回归用例，覆盖 POSIX home/绝对路径的未加引号与加引号形式，以及 Windows 斜杠/反斜杠两种形式；基线结果为 8 failed。
- GREEN：`_portable_probe_error()` 保留路径起点之前的诊断前缀；`<home>` 后缀和私有路径起点后的内容整体替换，安全偏向过度脱敏，继续限制 512 字符并在替换后复验 sealed report。
- 验证：33 focused tests passed（7 个既有 DeprecationWarning）、Ruff passed、mypy passed；未执行真实账号、bundle、签名、公证或发布验收。

## Round 2 POSIX 路径脱敏修复

- RED：新增 6 个回归场景，覆盖 `/Private Folder/codex` 与 `/Private File` 的引号/非引号形式、首个多路径和多行首路径；基线为 6 failed。
- 根因：POSIX 路径起点正则错误要求首目录段无空格且必须还有后续 `/`，漏掉含空格首段和单组件绝对路径。
- GREEN：POSIX 分支改为识别任意非单词边界后的 `/`，命中首个起点后截断后续消息；因此多路径、多行及 URL-like 文本安全偏向过度脱敏，Windows 与 home 路径逻辑保留。
- 验证：`tests/test_schema_audit.py tests/test_doctor.py tests/test_cli.py tests/test_acceptance_runner.py` 共 39 passed；Ruff 与 `mypy src/codex_session_manager/schema_audit.py` 通过。未执行真实账号、bundle、签名、公证或发布验收。
