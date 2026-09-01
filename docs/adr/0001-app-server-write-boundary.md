# App Server 是唯一在线写入边界

> **SUPERSEDED IN PART（2026-09-01）**：本 ADR 中“精确版本 + 全量 schema 哈希作为归档授权条件”的部分由 [`ADR 0011：版本无关、契约敏感的 App Server 操作边界`](0011-version-independent-operation-contracts.md) 取代；App Server 仍是唯一在线写入边界，禁止直接修改 Codex 内部文件。

Codex 任务的读取和写入只通过官方 App Server；CSM 不直接修改 rollout JSONL、SQLite、认证或 Codex 配置。写能力要求本地 Codex 版本与规范化 schema 哈希精确匹配人工批准的协议画像，未知、缺失或未审计差异一律退化为读取、备份、验证和生成计划，且协议画像只能经人工审查新增。
