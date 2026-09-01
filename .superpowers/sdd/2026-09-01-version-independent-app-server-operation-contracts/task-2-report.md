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

## 修复轮次 1：独立复核 Important

基线：`996eaa0`。本轮仅处理六项 Important，未恢复上下文应用或其它写能力。

### TDD 证据

RED：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_operation_contracts.py -q
4 failed, 10 passed
```

失败分别复现了响应 union/allOf/enum 误放行和循环 `$ref` 的 `RecursionError`；恢复的 derived-trim subprocess 回归也先以失败关闭/旧 profile-era fixture 不可构造暴露绑定断裂。

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest \
  tests/test_operation_contracts.py \
  tests/test_app_server.py \
  tests/test_app_server_process.py \
  tests/test_hashing_models_plans.py \
  tests/test_schema_audit.py -q
49 passed in 5.81s
```

### 修复映射

1. `allOf` 现在逐约束求交，响应 `anyOf`/`oneOf` 的每个分支逐一检查；请求 union 只接受能满足全部字段的完整分支，并保留合法布尔 JSON Schema。
2. enum 缺失、空值、非数组和缺少必需值均结构化失败；新增未知字符串值保持兼容。
3. `$ref` 采用有界深度和访问栈；循环、非法组合器及非法分支记录 `reference_cycle`、`schema_combiner` 或 `schema_branch`，不再递归崩溃或静默通过。
4. 请求 schema 的规范化完整 `required_sets` 纳入运行时投影；集合顺序规范化，集合内容变化会改变运行时指纹。
5. 恢复 derived-trim subprocess 回归，断言上下文应用失败关闭且 `thread/fork`、`thread/start`、`thread/inject_items`、`thread/name/set`、`thread/rollback` 均零调用。
6. `tests/test_schema_audit.py` 改用当前 `CapabilityMatrix`/操作能力测试数据，移除已删除 profile module 依赖；未扩大 report-v2。

### 静态验证

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked ruff check <本轮涉及 Python 文件>
All checks passed!

env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked mypy \
  src/codex_session_manager/operation_contracts.py \
  src/codex_session_manager/app_server.py \
  src/codex_session_manager/schema_audit.py
Success: no issues found in 3 source files
```

本轮未运行完整 `scripts/check.sh`、真实账号写入、bundle 或发布验收；工作树其它任务修改保持未暂存，报告路径保持为本文件。

补充：本轮相关五组聚焦测试已完整收集并通过；全量 `pytest -q` 仍在 collection 阶段被未授权路径 `tests/test_cli.py` 对已删除 `codex_session_manager.protocol_profiles` 的旧 import 阻断。本轮不扩大到该路径，避免越过 route 写入边界。

## 修复轮次 2：独立复核 Important

基线：`9f48dd8`。本轮只处理响应 union enum、非法字符串 type、布尔组合分支、allOf 可选字段冲突、CLI profile 依赖和运行时指纹分支顺序六项问题；保留轮次 1 已通过的 required fingerprint、derived-trim 零写入和 profile 退役行为。

### TDD 证据

RED（先于实现）：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_operation_contracts.py -q
..............FFFFF
5 failed, 14 passed in 0.28s
```

初次测试包中的 response 缺 enum 用例占用了 `None` 占位值，随后在实现前修正为合法的缺 enum schema；其余失败直接复现本轮非法 type、布尔分支、可选冲突和 required-set 顺序问题。修正后的 5 类回归均在 GREEN 中覆盖，响应 enum 另覆盖完整、缺失、空、仅未知和已知加未知分支。

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest \
  tests/test_operation_contracts.py \
  tests/test_app_server.py \
  tests/test_app_server_process.py \
  tests/test_hashing_models_plans.py \
  tests/test_schema_audit.py \
  tests/test_cli.py -q
66 passed in 32.86s
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_cli.py --collect-only -q
11 tests collected in 0.05s
```

聚焦静态检查：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked ruff check \
  src/codex_session_manager/operation_contracts.py \
  tests/test_operation_contracts.py tests/test_cli.py
All checks passed!

env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked mypy \
  src/codex_session_manager/operation_contracts.py
Success: no issues found in 1 source file
```

另以当前本机 Codex `0.142.1` 生成 schema 运行真实 probe 回归：`test_local_codex_schema_probe_reports_operation_contracts` 通过；其状态 `oneOf` 的合法单值 enum 分支保持可用。

### 修复映射

1. `_direct_shape()` 校验字符串 `type`；response enum 改为逐 `_SchemaShape` 检查，要求分支有 enum 且至少包含一个已知值，允许已知值与新增未知值共存；request 仍要求 exact CSM 值命中一个完整分支。
2. 组合器允许合法 `true`/`false` 分支：`true` 作为无约束 identity，`false` 作为不可满足分支；非法 branch 继续结构化失败，allOf 仍求交，anyOf/oneOf 仍按响应全分支、请求一可用分支处理。
3. allOf 合并时，冲突的非 required 可选 property 从父投影省略；若 property 被 required 或被契约字段读取，后续字段/required 校验失败关闭；不可满足的根 schema 仍产生结构化 issue。
4. shape、enum、items、field variants、document variants 和完整 required_sets 在 runtime projection 中规范排序，交换语义等价 schema 分支不改变 runtime fingerprint。
5. `tests/test_cli.py` 改用独立 `OperationCapability`/`CapabilityMatrix` fixture，移除已删除 profile import；既有 purge-removal hunk 原样保留。

`scripts/check.sh` 已运行，但在全仓 `ruff format --check .` 阶段因基线 `tests/test_operation_contracts.py` 的 4 个既有格式 hunk 失败，未进入完整 pytest；未运行真实账号写入、bundle 或发布验收。当前工作树仍包含其它任务修改，未触碰或暂存这些路径。

## 修复轮次 3：独立复核剩余 fail-open

基线：`04cb593`。本轮只处理混合组合器复活不可满足 schema，以及实际契约字段的 declared-but-unsatisfiable optional property 被 `allow_missing` 放行两项问题。

### TDD 证据

RED（先于实现）：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest tests/test_operation_contracts.py -q
....................FF                                                   [100%]
2 failed, 20 passed in 6.91s
```

失败分别复现 `allOf: [false]` 后接 `anyOf/oneOf` 错误开放 `archive.v1`，以及 `Thread.historyMode` 的 `allOf: [string, integer]` 被丢弃后错误开放 `inventory.common.v1`。

GREEN：

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked pytest \
  tests/test_operation_contracts.py \
  tests/test_app_server.py \
  tests/test_app_server_process.py \
  tests/test_hashing_models_plans.py \
  tests/test_schema_audit.py \
  tests/test_cli.py -q
68 passed in 36.03s
```

```text
env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked ruff check \
  src/codex_session_manager/operation_contracts.py \
  tests/test_operation_contracts.py
All checks passed!

env UV_CACHE_DIR=/private/tmp/csm-uv-cache uv run --locked mypy \
  src/codex_session_manager/operation_contracts.py
Success: no issues found in 1 source file
```

### 修复映射

1. `_SchemaShape.unsatisfiable` 作为最小状态 marker：`false`、组合交集为空、非法/循环 schema 均保留不可满足状态；后续 `anyOf/oneOf` 只与已有状态求交，不再以空 variants 注入 identity。纯 union 和合法 `true` identity 仍按原方向规则工作。
2. `_SchemaShape` 的声明属性保留空 variant；`_PathResult.declared` 将声明但无可满足 shape 与真正不存在区分。实际投影字段即使 `allow_missing=True` 也失败关闭，无关 optional 冲突仍不读取、不阻塞。
3. 新增回归覆盖混合 `allOf/anyOf/oneOf` 顺序、纯 union、`historyMode` 冲突、真正缺失和无关 `optionalMeta` 冲突。

本轮未运行完整 `scripts/check.sh`、真实账号写入、bundle 或发布验收；其它工作树改动保持未暂存。提交只包含本轮三个所有权路径。
