# App Server schema 人工批准流程

本流程只用于维护 `protocol_profiles.json`，不能由版本范围、环境变量、CLI 开关或自动化任务替代。未知画像在批准提交进入源码前始终保持只读。

## 1. 固定候选二进制

确认 Codex 的安装来源与版本，记录二进制 SHA-256；不要从版本号推断兼容性。运行：

```bash
csm schema audit --output schema-audit-candidate.json
```

报告必须可复验、`exact_profile_match: false`、`write_enabled: false`，且不含用户目录、凭据或任务内容。将报告中的 Codex 版本、二进制哈希、schema 哈希、能力指纹、稳定/实验方法和差异分类纳入审查证据。

## 2. 审查原始 schema

在一次性临时目录分别生成稳定和实验 schema：

```bash
SCHEMA_REVIEW_ROOT=$(mktemp -d)
codex app-server generate-json-schema --out "$SCHEMA_REVIEW_ROOT/stable"
codex app-server generate-json-schema --experimental --out "$SCHEMA_REVIEW_ROOT/experimental"
```

至少逐项审查：

- `thread/list`、`thread/read`、`thread/loaded/list` 的分页、状态和内容字段；
- `thread/archive`、`thread/unarchive`、`thread/delete`、`thread/name/set` 的请求与响应；
- `thread/fork`、`thread/rollback`、`thread/start`、`thread/inject_items` 的写入、持久化和后置条件；上下文投影还必须单独完成写后读取、服务重启、Codex Desktop 重启、后续模型可见和 reconcile 的完整 round-trip probe；
- `ThreadForkParams.lastTurnId` 等由 CSM 分支选择依赖的关键字段；
- 方法新增、移除、稳定/实验迁移，以及未知字段的保留语义。

任一写方法语义不完整、响应后置条件不稳定或内容映射无法证明时停止批准；只读报告可以保留，但不得修改信任画像。

方法出现在 schema 或人工批准画像中，只能证明协议形状和基础写入门禁，不证明上下文投影可用。当前 `0.142.1` 的 `thread/inject_items` 空返回和目标读取 `0 turns` 已作为 2.4 的上游阻塞记录；在独立 round-trip 证据出现前，不得把它作为派生投影执行能力。

## 3. 人工加入画像

只有审查结论通过后，才手工向 `src/codex_session_manager/protocol_profiles.json` 增加一个精确的 `codex_version + schema_sha256` 项，并完整写入稳定方法、实验方法和关键字段结果。画像批准只覆盖通用 App Server 协议门禁，不自动开放上下文应用；禁止修改代码来接受版本范围、仅版本命中或运行时自动学习。

同时补充 added、removed、stability changed、critical field changed 和 unknown profile 回归样例，运行：

```bash
scripts/check.sh
scripts/test_source_workflow.sh
scripts/test_full_workflow.sh
```

最后用候选二进制重新生成不可覆盖的审计报告；只有新报告 `exact_profile_match: true`、差异为空且 `write_enabled: true` 才算通用画像门禁验收。上下文应用还必须满足独立 round-trip probe；真实账号写入仍必须执行对应人工 Runbook，画像批准本身不等于账号、GUI、签名或生产验收。
