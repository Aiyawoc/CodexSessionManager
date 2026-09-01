# Task 3 报告：任务级 historyMode 与归档契约门禁

## 实现

- `normalize_thread()` 默认将缺省 `historyMode` 归一化为 `legacy`，未知值保存为 `UNKNOWN`；history mode 已进入 `ThreadSnapshot`，并由现有 management/backup fingerprint 绑定，详情快照覆盖摘要值。
- 移除任意未知顶层字段 allowlist 阻塞；保留 `extra`、未知 status/history/关系、未知 item、坏 turns shape 和闭包异常的 fail-closed 映射门禁。
- 新增共享纯函数 `selected_root_block_reason()`：先解析根的精确后代闭包，再检查 `inventory.common`、archive/unarchive、每个任务的 legacy/paginated history 契约，最后复用状态、归档、pinned、ephemeral、mapping/content 门禁。
- archive/unarchive 计划器按根调用共享资格函数；`CleanupExecutor.apply()` 在任何 client 写请求前复核当前能力、闭包和任务 fingerprint。删除 rename 规划、workflow 和 executor 分支，保留 `PlanAction.RENAME` 读取历史计划时的兼容性拒绝。
- PreCompact Hook 永远继续 native compact；Trim/Import 继续通过现有 `CapabilityMatrix.require_write()` 在首个不批准方法前零写失败。

## TDD 与验证

RED：新增测试先因 `selected_root_block_reason` 未实现而收集失败。

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest \
  tests/test_inventory.py tests/test_cleanup_audit.py tests/test_workflows.py \
  tests/test_lifecycle_integration.py tests/test_hooks.py -q
60 passed
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest \
  tests/test_hashing_models_plans.py tests/test_app_server_process.py -q
16 passed
```

`ruff check`、`ruff format --check` 均通过；Task 3 六个源码文件的 `mypy` 通过。

## 关注项

- 未运行真实账号归档/反归档、真实用户输入、bundle 或发布验收。
- 既有 `tests/test_trim.py` 与 `tests/test_importing.py` 的 7 个旧成功路径测试仍期待 Task 2 已关闭的 trim/import App Server 写能力；本 Task 3 route 不允许修改这些测试，已单独记录为集成关注项，未将其误报为 Task 3 GREEN。

## Retry attempt 2（2026-09-01）

- 复核 attempt 1 的实现与 index 后，保留任务级 `historyMode`、共享资格函数、能力/闭包/fingerprint 写前复核，以及历史 `PlanAction.RENAME` 的拒绝；补齐 selected unarchive planner/workflow 与 executor 统一门禁。
- 将 `tests/test_trim.py` 的 6 个旧成功路径和 `tests/test_importing.py` 的 1 个旧成功路径迁移为显式 capability fail-closed 测试；每个 fake client 均断言 fork/start 零写入。生产 trim/import 实现未改动。
- Attempt 2 聚焦测试结果：trim/import `23 passed`，inventory/cleanup/workflows/lifecycle/hooks `60 passed`，合计 `83 passed`；Ruff format/check 与目标源码 mypy 作为收尾门禁执行。
- 本次提交的 cached scope 仅包含 Task 3 的 9 个源码/测试文件与本报告；purge retirement、GUI、文档及其他 working-tree/index 用户改动均保留在提交外。
- 未运行真实账号归档/反归档、真实用户输入、bundle、签名、公证或发布验收。
