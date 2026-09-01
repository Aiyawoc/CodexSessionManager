# Task 5 报告：GUI 归档状态复用逐操作契约

## 实现

- 任务列表加载保留 `InventoryResult.capabilities`，并在加载中、失败或能力缺失时 fail-closed。
- `_can_archive_root()` / `_can_unarchive_root()` 统一调用 `selected_root_block_reason()`；归档按钮显示归档/反归档契约、历史模式或领域门禁返回的第一个阻塞原因。
- 删除任务右键菜单的 rename 入口及其 GUI i18n 文案；上下文方案仍可保存，但 apply 按钮和直接调用均保持禁用并说明当前仅支持审查与投影计划。

## TDD 与验证

RED（实现前）：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/test_gui.py tests/test_review_mode_gui.py -q
20 failed, 32 passed, 1 error
```

失败集中在 GUI 仍访问已删除的全局 `write_enabled`、列表结果丢弃能力矩阵和新增契约回归未满足。

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/test_gui.py tests/test_review_mode_gui.py -q
52 passed
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked ruff check src/codex_session_manager/gui/controller.py src/codex_session_manager/gui/i18n.py tests/test_gui.py tests/test_review_mode_gui.py
All checks passed!
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked mypy src/codex_session_manager/gui/controller.py src/codex_session_manager/gui/i18n.py
Success: no issues found in 2 source files
```

未运行真实账号归档/反归档、真实 GUI、bundle、签名、公证或发布验收；这些仍需目标环境与明确测试目标门禁。
