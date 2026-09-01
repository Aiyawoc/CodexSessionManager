# CodexSessionManager v1.1 上下文投影收口与敏感信息修改优先计划

> 状态：`ACTIVE NORMATIVE ADDENDUM`
>
> 基线：`main@76a4e0caf7f2e4c8ed0e48f9044f79bd71c52ede`
>
> 生效日期：2026-08-31
>
> 本文件是当前 v1.1 验收和后续研发顺序的规范性补充：2.4 能力状态以 2.4 收口记录为准，研发顺序以本计划为准，首次交付与正式发布门禁以对应 Runbook 为准，README 与 Skill 反映相同的当前能力边界。

本计划遵循版本无关、契约敏感边界：版本、二进制和全量 schema 散列仅用于诊断与计划失效，不是归档授权条件；归档与反归档由静态、人工复核的最小操作契约逐项评估；无关变化自动兼容，相关方法/字段/关键枚举不兼容时只关闭受影响操作。当前 Codex 在线任务仅允许 `archive`/`unarchive` 执行；上下文审查与投影计划可用，但应用不可用；`purge`、restore/import 写入、trim/context apply 和 MCP 写入不可用。

标题修改/重命名不属于第一版范围且当前不可用；只有在 v1.1 之后另行完成产品决策、受支持的操作契约和真实验收，才可重新研究；本轮不启动 D1+。

## 1. 目标

本计划落实两项已确认决策：

1. **停止推进当前的上下文应用执行层，保留并完善上下文审查与投影计划层；2.4 以上游能力阻塞、源任务保持完整正式关闭。**
2. **先继续完成 v1.1 其它功能验收；其后优先实现敏感信息修改，再继续研究其它上下文应用方向。**

本计划不通过直接修改 `.codex` JSONL、SQLite、认证文件或内部状态满足产品需求，也不把未验证的 App Server 返回值包装成成功。

## 2. 产品语义重新划分

### 2.1 上下文审查

用户查看现有任务的模型可见内容、结构、依赖、工具调用、文件修改、验证和敏感信息命中结果。

上下文审查是只读能力，不改变 Codex。

### 2.2 上下文投影计划

用户对可审查目标设置：

- `Keep`：原样保留；
- `Exclude`：从计划投影中排除；
- `Summary`：用人工确认的摘要替代；
- `Replace`：用指定文本确定性替换；
- `Redact`：用固定占位符或经批准的脱敏文本替换；
- `Protect`：硬保护，不允许删除或修改。

投影计划绑定任务内容指纹、能力指纹、目标 ID、分组关系、计划有效期和 projection SHA-256。保存计划不等于已经修改 Codex。

### 2.3 上下文应用

把确定性投影安装到：

- 原 Codex 任务的活动上下文；或
- 新派生任务；或
- 其它正式支持的执行目标。

这是独立执行层。当前基线没有通过真实 round-trip 验证的执行器，因此保持关闭；上游阻塞期间不得创建派生任务。

### 2.4 敏感信息修改的三种保证

产品和文档必须区分：

1. **物理删除**：来源数据本身不再包含敏感值；
2. **确定性投影修改**：来源仍保留，但指定执行目标的模型可见投影已按计划替换；
3. **语义纠正**：后续追加一条说明，要求模型以新值为准，但不能证明旧值不可见。

只有完成对应层级的读取、写入和重读验证，才能声明该保证。原生 compact、动态提示词或附加上下文不能被称为物理删除或确定性脱敏。

## 3. 当前架构决策

### 3.1 保留

- 时间线和原文审查；
- 内容规范化；
- Keep/Exclude/Summary/Protect；
- 后续 Replace/Redact；
- 投影计算和 Token 估算；
- 不可变计划；
- 指纹、过期、漂移和 Pending 状态；
- GUI、CLI、Skill、Hook、MCP 共用工作流；
- 源任务保护、审计和 reconcile。

### 3.2 暂停

- 通过 `thread/inject_items` 创建精简派生任务；
- 以请求返回 `{}` 作为写入成功；
- 对空目标自动重试、归档或删除；
- 在没有公开接口的情况下实现原任务 replacement history；
- 通过修改 Codex 内部存储伪造上下文修改；
- 对外宣称完整上下文裁剪执行可用。

### 3.3 用户界面状态

在代码完成安全退化后，相关入口应显示：

```text
保存上下文投影方案           可用
审查与导出投影               可用
应用到原任务                 当前上下文应用不可用
创建精简派生任务             运行时持久化探测未通过
等待受支持的执行能力         可用
```

禁用状态必须给出具体受影响的操作契约和最近一次能力探测结果，而不是以 Codex 版本或全量 schema 是否相等作为授权条件，也不能笼统显示“操作失败”。

## 4. 工作顺序

## P0：继续完成 v1.1 其它功能验收

在任何新的上下文执行研究前，先完成：

- doctor、schema、逐项操作能力和只读盘点；
- MCP 十工具边界和 GUI 唤起；
- 加密备份、托管 age identity、完整解密复验；
- 清理候选、后代闭包、独立备份、批量归档和反归档；
- 批量归档和反归档；
- 记忆登记、计划、原子写入、漂移拒绝、恢复和审计；
- Pending 中心、异常核对和审计链；
- Skill、Hook、安装、bundle 和目标平台验收；
- 脱敏验收报告和已知限制。

2.4 上游阻塞不降低其它功能的通过标准。第一版任务管理只提供盘点、备份、批量归档和反归档，不提供永久删除能力。

### P0 完成条件

- 所有未阻塞的 v1.1 验收项有真实证据；
- 2.4 按 `closed_with_upstream_blocker` 记录；
- 公开说明不再声称上下文应用已可用；
- `production_ready` 仍为 `false`，直到正式发布条件全部满足；
- 任何二期直接执行代码仍受现行启动闸门约束。

## P1：优先实现敏感信息修改

敏感信息修改先建设确定性计划和验证内核，不以“能否马上写回原 Codex 任务”为前置条件。

### P1.1 领域模型

将现有 TrimPlan 逐步泛化为可兼容的 ContextProjectionPlan，至少包含：

```text
ContextProjectionPlan
├─ source_thread_id
├─ source_content_fingerprint
├─ source_management_fingerprint
├─ capability_fingerprint
├─ reviewed_prefix_fingerprint
├─ selections
│  ├─ KEEP
│  ├─ EXCLUDE
│  ├─ SUMMARY
│  ├─ REPLACE
│  ├─ REDACT
│  └─ PROTECT
├─ protected_groups
├─ projection_sha256
├─ expected_model_visible_messages
├─ risk_class
├─ execution_preference
│  ├─ PLAN_ONLY
│  ├─ SAME_THREAD
│  └─ DERIVED_THREAD
├─ required_capabilities
├─ created_at / expires_at
└─ plan_sha256
```

计划模型仍应冻结并拒绝未知字段；旧 TrimPlan 在迁移期通过版本化适配读取，不能静默改变已有计划语义。

### P1.2 敏感信息动作

`Replace` 和 `Redact` 必须是确定性转换：

- 目标绑定当前 item/segment ID 和内容 SHA-256；
- 用户可编辑替换文本；
- Redact 默认使用固定占位符，如 `[REDACTED:credential]`；
- 支持命中范围预览，不把敏感原文写入日志、审计详情或模型可见 MCP 返回；
- 完整 diff 只在本机可信 UI 中展示；
- 导出的验收证据只记录类别、数量、位置散列和计划散列；
- 旧计划在内容变化后立即失效。

### P1.3 原子分组

以下内容不能被拆开删除或修改：

- 工具调用与对应工具结果；
- 文件变更与对应验证结果；
- approval 请求与决定；
- 错误与紧随其后的恢复说明；
- 依赖链中的必要引用；
- 系统、开发者、当前用户请求和进行中的 turn；
- 未知 item 和映射不完整的结构。

敏感值位于受保护结构中时，允许对文本叶节点做精确 Redact，但不得破坏调用 ID、结构字段、工具协议或验证证据。

### P1.4 风险等级

- `LOW`：去除冗余过程、合并重复说明；
- `MEDIUM`：替换过时结论、路径、项目说明；
- `HIGH`：凭据、token、私钥、身份信息、法律/医疗/财务内容；
- `CRITICAL`：可能影响恢复、审计、工具依赖或安全边界的内容。

HIGH/CRITICAL 必须额外确认，并明确显示当前可提供的保证层级。执行目标不支持确定性投影时，只允许保存计划，不允许把语义纠正标记为脱敏完成。

### P1.5 首批支持的执行目标

优先支持 CSM 能完全控制并能重读验证的目标：

1. CSM 自有计划、投影预览和导出；
2. 已登记的本地记忆文件；
3. CSM 生成的可恢复逻辑导出或隔离恢复输入；
4. 测试 fixture 和临时隔离数据根。

对原 Codex 任务和派生任务的实际应用继续受 capability gate 控制。计划层完成不代表 Codex 历史已经改变。

### P1.6 用户流程

```text
选择任务或来源
→ 本地扫描并标记敏感信息
→ 用户逐项 Keep/Replace/Redact/Protect
→ 展示原子分组和完整 diff
→ 保存不可变计划
→ 重读并验证来源指纹
→ 仅对受支持目标执行
→ 重读目标并比较 projection SHA-256
→ 写入审计和可恢复证据
```

取消、超时、GUI 关闭和能力不足均不得产生半应用状态。

## P2：敏感信息计划层稳定后研究其它可行方向

P2 是能力研究，不预设一定能恢复执行器。

### P2.1 官方接口研究

逐版本检查：

- 是否出现同任务 replacement-history 接口；
- 是否允许向 `thread/compact/start` 传入 custom summary、projection 或 replacement history；
- 是否有正式的 context window、checkpoint 或 rewind API；
- Codex Desktop app-only surface 是否能调用模型不可见的固定执行器；
- 是否能建立明确的写入后读取和持久化契约。

### P2.2 `thread/inject_items` round-trip probe

每个待评估的上下文操作能力都必须使用一次性临时任务执行：

```text
创建目标
→ 注入带随机 nonce 的最小合法 item
→ thread/read
→ 独立 turns/list
→ thread/resume
→ App Server 重启后读取
→ Codex Desktop 重启后读取
→ 发起后续 turn 并验证模型可见
→ 记录结果并隔离目标
```

仅 schema 存在、方法返回 `{}` 或目标 ID 已创建都不能开放能力。

### P2.3 执行器抽象

```text
ContextProjectionExecutor
├─ probe()
├─ prepare()
├─ apply()
├─ verify()
├─ reconcile()
└─ cancel()
```

实现至少包括：

- `UnsupportedProjectionExecutor`：当前默认，结构化返回能力不可用；
- `DerivedThreadProjectionExecutor`：只有完整 probe 通过后启用；
- `NativeSameThreadProjectionExecutor`：只有正式 replacement-history 接口出现后启用。

GUI、CLI、Hook 和未来 MCP Apps UI 不直接调用具体 App Server 方法。

### P2.4 重新开放硬门禁

执行器必须同时证明：

- 官方接口；
- 相关操作契约经人工复核；
- 写后读取一致；
- 重启后持久化；
- 后续模型实际可见；
- 超时后可 reconcile；
- 可恢复证据；
- 源任务保护；
- 真实 macOS/Codex Desktop 验收；
- 对应 Windows 行为或明确的平台限制。

否则上下文应用能力保持不可用；当前只支持审查与投影计划。

## 5. Hook 设计边界

PreCompact Hook 继续 fail-open，除非用户明确选择严格阻止策略。

### 默认流程

```text
PreCompact
→ 查找 PendingContextProjection
→ 无计划或计划失效：记录并 continue:true
→ 有待审查计划：写入请求、尝试唤起 GUI、快速返回
→ Hook/GUI 失败或超时：continue:true
```

Hook 不在进行中的 turn 内创建派生任务，也不长期等待 GUI。只有计划成功持久化且用户显式选择“本次必须审查”时，才允许 `continue:false` 阻止当次 compact。

即使原生 compact 完成，PostCompact 或 SessionStart 注入的补充说明也只能标记为“语义纠正”，不能标记为确定性删除或硬脱敏。

## 6. 空目标和不确定执行治理

新增或保留以下执行状态：

```text
PREPARED
TARGET_CREATED
WRITE_REQUEST_ACCEPTED
VERIFYING
SUCCEEDED
EMPTY_TARGET
PARTIAL
UNKNOWN
RECONCILIATION_REQUIRED
FAILED
CANCELLED
```

规则：

- `{}` 只允许进入 `WRITE_REQUEST_ACCEPTED`；
- 读取结果为空时进入 `EMPTY_TARGET`；
- 超时但可能已提交时进入 `UNKNOWN`；
- 未完成重读不得进入 `SUCCEEDED`；
- 不自动重试可能重复写入的请求；
- 不自动删除异常目标；
- 异常目标不建立成功 provenance；
- 用户只能在异常中心执行“重新核对”或受控归档。

## 7. 模块改造任务

以下是后续代码阶段的目标，不在本次文档提交中实现。

### `models.py` / `plans.py`

- 增加 ContextProjectionPlan、风险等级、执行偏好和版本字段；
- 兼容旧 TrimPlan；
- 增加 Replace/Redact 选择模型；
- 增加执行状态和 capability requirement。

### `inventory.py`

- 保留未知字段和 raw payload SHA；
- 提供稳定 reviewed-prefix 指纹；
- 对工具、文件变更和验证建立原子分组；
- 标记进行中 turn、当前用户请求和结构不完整目标。

### `trim.py`

- 拆分“投影计算”和“执行目标写入”；
- 投影计算保持纯函数；
- 加入 Replace/Redact；
- 生成模型可见消息和 diff 的确定性散列。

### `app_server.py` / `operation_contracts.py`

- 将方法存在与语义能力分离；
- 记录派生注入的负能力证据；
- 增加 round-trip probe 结果；
- 未验证时不暴露写能力。

### `workflows.py`

- 通过 ContextProjectionExecutor 调度；
- 默认使用 UnsupportedProjectionExecutor；
- 统一 apply/verify/reconcile；
- 禁止 GUI/CLI 绕过工作流调用 App Server。

### `hooks.py` / Pending 服务

- 保存和查询 PendingContextProjection；
- 支持严格/宽松触发策略；
- 继续 fail-open；
- 不在 Hook 内执行危险写入。

### `gui/`

- 增加 Replace/Redact 编辑器和差异视图；
- 显示保证层级和执行能力；
- 禁用不可用执行按钮；
- 增加空目标和 reconcile 页面；
- 敏感原文仅在本机可信 UI 中显示。

### `mcp_bridge.py` / `mcp_server.py`

- 模型可见工具只准备建议和打开审查；
- 不返回敏感正文；
- 后续 app-only 执行器仍需一次性 grant；
- 当前阶段不新增模型可见写工具。

### 测试与验收

- 投影纯函数和散列稳定性；
- Replace/Redact 精确行为；
- 原子分组保护；
- 漂移、过期和未知字段；
- Hook fail-open 和严格阻止；
- `{}` 不等于成功；
- 空目标、超时和 reconcile；
- CSM 自有目标的写后重读；
- 版本无关的上下文能力 round-trip probe；
- 真实 macOS/Codex Desktop 验收。

## 8. 分阶段里程碑

### M0：文档与验收收口

- 2.4 关闭记录；
- ADR 0009；
- 验收索引；
- 本规范性计划。

通过标准：文档明确上游阻塞、源任务保持完整、执行层暂停和后续优先级。

### M1：完成 v1.1 其它验收

不修改上下文执行器，完成剩余真实验收和证据收口。

通过标准：除明确上游阻塞和时间等待项外，v1.1 其余范围都有对应层级证据。

### M2：敏感信息投影内核

完成 Replace/Redact、风险等级、原子分组、投影散列和 Pending 模型。

通过标准：在纯函数和隔离 fixture 中确定性复现，敏感正文不进入审计或 MCP 返回。

### M3：受支持目标应用

只对 CSM 自有数据、记忆来源、导出和隔离输入实现应用、版本、回滚和重读。

通过标准：任一步失败不发布目标，恢复可验证。

### M4：上下文能力研究

对新的精确 Codex 版本运行官方接口和 inject-items probe，研究 app-only surface。

通过标准：形成正/负能力报告；无证据不开放执行器。

### M5：条件式恢复上下文应用

仅在 M4 全部硬门禁通过后实现 same-thread 或 derived executor。

通过标准：真实目标持久化、重启可读、模型可见、可 reconcile、可恢复。

## 9. 与 v1.2—v1.5 的衔接

### v1.2

- MCP Apps UI 先迁移审查、投影和 capability 状态；
- ExecutionGrant 和账本可在合成/受支持目标中实现；
- 不以恢复上下文写入作为 UI Spike 通过条件。

### v1.3

- 一期 UI 对等范围中，上下文“审查与计划”必须可用；
- “应用到原任务/创建派生任务”按 capability 显示，不伪造对等；
- 清理、备份和记忆等已验证执行能力可独立迁移；v1.1 之后若仍需研究标题修改，必须另行决策、定义操作契约并完成真实验收，不能作为既定范围。

### v1.4—v1.5

- workspace/provenance 能区分 `planned`、`applied`、`blocked_upstream`、`empty_target` 和 `reconciled`；
- Resume Digest 可以消费已确认投影，但不得被描述为历史删除；
- 受控上下文分叉在执行器通过后接入，同一计划模型无需重做。

## 10. 停止条件

出现以下任一情况立即停止执行研究：

- 需要直接修改 Codex 内部存储；
- 只能靠版本范围或猜测字段放行；
- 写后无法独立读取；
- 重启后丢失；
- 无法证明后续模型可见；
- 可能重复写入且不可 reconcile；
- 敏感正文进入日志、Git、Issue 或模型可见工具结果；
- 源任务或用户数据无法恢复；
- 为满足路线时间表而降低安全门禁。

## 11. 最终交付定义

本阶段的正确交付不是“强行做出上下文裁剪按钮”，而是：

- v1.1 其它功能继续完成真实验收；
- 上下文审查和投影计划保持可用并得到完善；
- 当前不可靠执行器关闭且原因透明；
- 敏感信息修改获得确定性、可审计、可恢复的计划和受支持目标实现；
- 其它上下文应用方向在敏感信息能力稳定后，以官方接口和真实 round-trip 证据重新评估。
