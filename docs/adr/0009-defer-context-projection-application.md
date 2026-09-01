> **SUPERSEDED IN PART（2026-09-02）**：仅永久删除（purge）及旧精确版本/画像授权归档写入的表述被取代；不可变计划、完整后代闭包、上下文应用延期和来源任务保护决策继续有效。当前边界见 [ADR 0011：版本无关操作契约](0011-version-independent-operation-contracts.md) 与 [当前验收索引](../acceptance/README.md)。

# ADR 0009：延期上下文投影应用，保留审查与计划层

- 状态：Accepted
- 日期：2026-08-31
- 基线：`main@76a4e0caf7f2e4c8ed0e48f9044f79bd71c52ede`
- 关联：ADR 0001、ADR 0002、ADR 0003、v1.1 本机受控验收 2.4

## 背景

CSM 的上下文优化原设计为：读取现有任务、生成 Keep/Exclude/Summary/Protect 投影，再创建一个承载投影的新派生任务，原任务保持不变。

在 v1.1 本机真实账号验收中，App Server `thread/inject_items` 返回空对象，但新目标的 `thread/read --include-content`、实验性 turns 列表和 resume 后读取均为 `0 turns`。CSM 正确记录失败，源任务保持不变，目标没有被继续写入。

与此同时，公开 App Server 没有经过验证的接口允许 CSM 把自定义 replacement history 安装回原任务。PreCompact Hook 只能继续或停止，不能提供任意替换历史；原生 compact 和提示词也不能证明指定内容已被确定删除或脱敏。

继续修补当前执行路径会产生误报成功、空目标、盲目重试、不可恢复状态和用户保证不准确等风险。

## 决策

1. 当前上下文应用执行层停止推进并保持关闭；
2. 上下文审查、确定性投影、不可变计划、指纹、Pending 和审计继续维护；
3. `thread/inject_items` 的方法存在不再等价于写能力可用；必须通过持久化、重启、后续模型可见和 reconcile 的完整 round-trip probe；
4. 当前 2.4 以 `blocked_upstream` 关闭，源任务保护记为通过；
5. v1.1 继续完成其它功能验收，不为完成路线降低上下文或 purge 门禁；
6. 其余 v1.1 验收完成后，先实现敏感信息修改的计划、diff、风险和受支持目标，再研究 same-thread、可靠派生、custom compact 或 app-only 执行方向；
7. 不直接修改 Codex JSONL、SQLite、认证文件或内部状态；
8. 对外只声明“上下文审查与投影计划”，不声明上下文应用、历史删除或硬脱敏已可用。

## 对 ADR 0002 的补充

ADR 0002 中“派生裁剪”的安全原则仍成立：原任务不应被未经验证地覆盖，投影必须绑定不可变计划和指纹。

本 ADR 补充：

- 派生任务只是可能的执行目标，不再是默认已可用能力；
- 执行目标必须由 capability-gated executor 选择；
- 当前默认执行器为 unsupported；
- 只有真实 round-trip 证明成功后才能启用派生或同任务执行器。

## 结果

### 正面结果

- 不把请求接受误报为持久化成功；
- 不破坏源任务；
- 保留已经成熟的审查、计划和 GUI 投资；
- 为 Replace/Redact 和未来 MCP Apps UI 提供稳定领域模型；
- 后续官方能力出现时只需新增执行器，不重做计划层。

### 代价

- v1.1 暂时不能交付完整上下文裁剪应用；
- 部分现有 README、Runbook、Skill 和二期计划需要后续统一修订；
- 用户只能保存、审查和导出投影，不能把它可靠安装到原任务或派生目标；
- 异常空目标需要额外治理和人工核对。

## 重新评估条件

同时满足以下条件时重新评估本决策：

- 官方提供明确的 replacement-history、custom compact、checkpoint/rewind 或等价接口；或 `thread/inject_items` 在新的精确版本完成全部持久化 probe；
- 精确 schema 画像经人工批准；
- 写后可由两个独立读取路径验证；
- App Server 和 Codex Desktop 重启后仍可读取；
- 后续模型请求实际使用预期投影；
- 超时和断线可 reconcile，不需要盲目重试；
- 失败后源任务和目标均可恢复或安全隔离；
- 自动化和真实目标平台验收通过。

缺少任一证据时，本决策继续有效。
