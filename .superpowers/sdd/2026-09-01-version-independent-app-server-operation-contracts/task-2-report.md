# Task 2 报告：版本无关 App Server 操作契约

## 实现

- 新增 `operation_contracts.py`，以固定的五项 v1 规则评估方法稳定性、请求字段、完整 `required` 集合、响应/通知最小投影、局部 `$ref`、`allOf`/`anyOf`/`oneOf`、类型和关键枚举。
- `_generate_schema()` 现在返回全部 JSON 文档、方法集合和 canonical 全量 SHA-256；`probe_capabilities()` 在临时目录销毁前评估五项契约。
- 契约结果分别记录稳定/实验方法证据、规则指纹、运行时最小投影指纹和结构化 issue；单项失败不设置 `probe_error`，生成/解析整体失败返回五项不可用能力并共享 `probe_error`。
- 删除运行时精确版本画像及授权引用；将当前工作树含 `0.151.0-alpha.7.2` 证据的画像保存在 `tests/fixtures/exact-protocol-profiles-v1.json`，仅作为回归语料。
- 更新合成 schema、App Server 进程 fixture 和过时的 profile-era 测试；移除超出本任务能力边界的旧 derived-trim subprocess 测试。

## TDD 证据

RED：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_operation_contracts.py tests/test_app_server.py -q
ModuleNotFoundError: No module named 'codex_session_manager.operation_contracts'
```

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_operation_contracts.py tests/test_app_server.py tests/test_app_server_process.py tests/test_hashing_models_plans.py -q
36 passed in 4.74s
```

聚焦静态检查：

```text
uv run --locked ruff check <Task 2 source/tests>
All checks passed!
uv run --locked mypy src/codex_session_manager/operation_contracts.py src/codex_session_manager/app_server.py
Success: no issues found in 2 source files
```

## 文件与提交

提交文件：`operation_contracts.py`、`app_server.py`、画像删除与测试 fixture、三组聚焦测试、测试 conftest、去除旧画像依赖的 `schema_audit.py`，以及本报告。

提交 subject：`feat(协议): 以最小操作契约取代版本画像`

commit 短 SHA：由最终提交后在任务回执中记录。

## 自审与关注项

- 已确认 `src/` 不再引用 `protocol_profiles`、`TRUSTED_WRITE_SCHEMAS`、`AUDITED_PROTOCOL_PROFILES`；版本号、二进制 SHA 和全量 schema SHA 仍作为 CapabilityMatrix 诊断/指纹输入，不参与操作可用判定。
- 当前本机 Codex `0.142.1` 实际 probe：inventory、legacy、archive、unarchive 可用；分页方法仅实验集合且未协商时局部不可用，符合契约规则。
- 未运行完整 `scripts/check.sh`、真实账号写入、bundle 或发布验收；工作区已有其它任务修改，提交仅暂存本任务及必要的测试/runtime profile 退役 hunk。
