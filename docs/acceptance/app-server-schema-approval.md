# App Server 操作契约人工审查流程

本流程用于维护 CSM 的五项最小操作契约和脱敏审计报告。它不把版本、二进制或全量 schema 的精确匹配当作归档授权条件；未知或不完整的相关契约只关闭受影响操作，读取、备份、验证和生成计划仍可用。

## 1. 固定运行时证据

确认 Codex 安装来源并运行：

```bash
csm schema audit --output schema-audit-candidate.json
```

报告可以记录 Codex 版本、二进制 SHA-256、稳定/实验 schema SHA-256、初始化指纹、方法集合和脱敏差异。这些值是诊断与计划失效证据，不是归档授权条件。报告不得包含用户目录、凭据或任务内容。

## 2. 人工审查五项契约

逐项审查下列静态、人工维护的最小契约：

| 契约 | 必需能力 | 必须证明的语义 |
| --- | --- | --- |
| `inventory.common.v1` | `initialize`、`thread/list`、`thread/read`、`thread/loaded/list` | ID、归档状态、运行状态、父子关系、临时状态和历史模式可确定 |
| `history.legacy.v1` | `thread/read` | turns/items 可完整建立内容指纹和逻辑备份 |
| `history.paginated.v1` | `thread/turns/list` | `itemsView=full`、升序分页、cursor 可证明终止且 items 完整 |
| `archive.v1` | `thread/archive`、归档通知、归档后列表/读取 | 完整后代闭包逐项重读为已归档 |
| `unarchive.v1` | 已归档列表/读取、`thread/unarchive`、恢复通知 | 目标闭包逐项重读为活跃 |

审查 CSM 实际发送的请求字段、读取的响应/通知字段、关键枚举、稳定性、写前条件和写后可观测状态。分页契约失败只影响分页历史任务；普通历史任务仍独立评估。

## 3. 兼容性判定

以下变化自动兼容：Codex 版本、二进制哈希或全量 schema 哈希变化；新增无关方法/定义；无关方法在稳定和实验集合间迁移；描述、标题、默认值、顺序或 JSON 键顺序变化；不改变已使用类型、必需性或已知枚举语义的可选字段。

以下变化只关闭受影响操作：必需方法删除、改名或稳定性降低；请求/响应字段类型、名称或必需性不兼容；未知关键状态、历史模式或关系枚举；分页失去完整 items 或可证明终止；归档/反归档响应与写后状态无法一致映射；schema 生成、解析或契约投影失败。

运行时不自动学习、扩展或批准新的写入语义。新增、移除或关键字段变化须由维护者人工审查，并在必要时发布新的契约规则版本。无关变化不要求 CSM 跟随 Codex Desktop 发布。

## 4. 计划和能力报告

能力报告封存 `inventory.common`、`history.legacy`、`history.paginated`、`archive` 和 `unarchive` 五项结果，每项输出 `available`、契约 ID、规则/运行时指纹和结构化原因。不可变计划绑定契约指纹、运行时证据、目标状态与内容指纹、账号根、完整后代闭包、备份证据和有效期；任一漂移都要求重新规划。

归档与反归档由静态、人工复核的最小操作契约逐项评估。当前 Codex 任务在线写入仅为批量归档和反归档，并且只能通过官方 App Server；永久删除、重命名、restore/import 写入、上下文应用和 MCP 写入均不可用。写入超时先重读并 reconcile，禁止盲目重试。

## 5. 验收命令与边界

```bash
scripts/check.sh
scripts/test_source_workflow.sh
scripts/test_skill_workflow.sh
```

必须覆盖版本/二进制/全量 schema 变化和无关方法变化不关闭兼容归档、相关方法变化只关闭受影响操作、GUI/CLI/Skill 得出相同资格与原因，以及 MCP 不暴露 archive/unarchive executor。历史精确画像文档只作为诊断和回归语料，不改写历史验收结论。
