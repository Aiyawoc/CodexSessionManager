# App Server 是唯一在线写入边界

Codex 任务的读取和写入只通过官方 App Server；CSM 不直接修改 rollout JSONL、SQLite、认证或 Codex 配置。写能力要求本地 Codex 版本与规范化 schema 哈希精确匹配人工批准的协议画像，未知、缺失或未审计差异一律退化为读取、备份、验证和生成计划，且协议画像只能经人工审查新增。
