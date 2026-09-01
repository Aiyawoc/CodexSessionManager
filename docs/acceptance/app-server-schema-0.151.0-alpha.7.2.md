# App Server `0.151.0-alpha.7.2` 精确画像审计

> **SUPERSEDED IN PART（2026-09-01）**：本文是历史精确画像与只读 probe 证据；精确版本、二进制和全量 schema 散列不再作为归档授权条件。现行边界见 [`ADR 0011：版本无关、契约敏感的 App Server 操作边界`](../adr/0011-version-independent-operation-contracts.md)。正文结论保持不变。

日期：2026-09-01  
证据层级：本机官方 App Server 原始 schema + 真实账号只读 probe + 自动回归  
未执行：归档、反归档或任何其它真实账号写入

## 候选身份

- 来源：ChatGPT.app 内置 Codex CLI；
- Codex 版本：`0.151.0-alpha.7.2`；
- 二进制 SHA-256：`a6042937174f72112dbd2d554a4af36936422e0c5ac69e353dc68994458996e9`；
- schema SHA-256：`7819d402c19b75fdd87c00f9f81901d1f54b109fb28f3b7316c2b2da236c7033`；
- 能力指纹：`21de87d501da903f3d8ce6447d2c3f4266860fae4ac87ab1caf5aa6dcceb134d`；
- `ThreadForkParams.lastTurnId`：存在。

## Schema 审查

- `thread/archive` 和 `thread/unarchive` 仍只接受必填 `threadId`；归档响应仍为空对象，反归档响应仍返回 `thread`。
- `thread/list` 新增可选 `sectionId`，分页 `data/nextCursor/backwardsCursor` 形状不变。
- `thread/read` 的根响应不变，但 `historyMode=paginated` 已不应依赖单次 `includeTurns=true`。CSM 对该模式使用稳定的 `thread/turns/list`，按升序、`itemsView=full`遍历至 `nextCursor=null`。
- `thread/loaded/list` 请求和响应形状不变。
- 任务新增 `historyMode`、`projectId`、`section`、`sectionEnteredAt`、`canAcceptDirectInput` 和 `extra`。前五项不改变父子血缘；`extra` 只在为 `null` 时视为已审计，任何非空不透明内容仍将 `mapping_complete` 置为 `false`。
- 新增项目、section、queue、timeline 等方法不自动进入 CSM 一期功能；`thread/delete` 仍只是上游 schema 事实，CSM 不提供永久删除。

## 真实账号只读证据

- 活跃任务摘要：969；其中 `legacy` 894、`paginated` 75；
- 兼容修复后：`mapping_complete=true` 855，仍因真实血缘或未知映射不完整而阻断 114；
- 一个 `paginated` 任务通过分页读取得到 `content_complete=true`；
- 截图中已加载的任务复核为 `mapping_complete=true`、`content_complete=true`、`notLoaded`、未固定、非临时、无后代。本文不记录其真实 ID 或内容。

## 结论与边界

源码复验结果为 `exact_profile_match=true`、`differences=[]`、`conclusion=trusted_write`、`write_enabled=true`。因此该精确画像可进入 CSM 现有归档/反归档计划与执行门禁。

本结论不表示任意未知 schema 可写，也不开放上下文应用、永久删除或其它未验收能力。真实归档/反归档 round-trip 尚未在本阶段执行，必须由用户在最新 bundle 中选定已备份任务并确认后单独记录。
