# CodexSessionManager 参考 dsh-talk-map 的优化升级建议与详细实施计划

> 分析基线：`Aiyawoc/CodexSessionManager` `main@3e82ce274504e8f7565cc31b52ae921a73475a0e`
> 参考项目：`Tasihi89/dsh-talk-map`
> 目标：在保留 CodexSessionManager 现有安全执行内核的基础上，引入空间化会话管理、恢复现场摘要、会话血缘与受控上下文分叉能力。

---

## 1. 总体结论

不建议直接把 `dsh-talk-map` 移植进 CodexSessionManager，也不建议为此引入 React、Node、Qt WebEngine 或额外 Web 服务。

更合理的升级方向是：

> **保留 CodexSessionManager 已经成熟的计划、指纹、备份、审计和人工确认安全内核，在其上增加一个原生 PySide6 的“会话工作区 / 会话地图”，作为只读导航、关系理解和审查编排入口。**

最终产品结构从：

```text
对话列表
  → 清理审查
  → 上下文审查
  → 记忆审查
```

升级为：

```text
会话工作区 / 地图
  ├─ 空间化组织
  ├─ 项目与会话关系
  ├─ 父子 / 分叉血缘
  ├─ 恢复现场摘要
  ├─ 待处理计划与备份状态
  └─ 上下文分叉意图
            ↓
       原有审查 GUI
            ↓
     不可变计划 + 人工确认
            ↓
 Official Codex App Server
            ↓
        备份与审计
```

其中最重要的边界是：

> **地图只能准备操作、展示状态和打开审查流程，不能直接执行归档、删除、上下文派生或记忆修改。**

---

## 2. 当前仓库基础与现状

当前主分支基线为：

```text
3e82ce274504e8f7565cc31b52ae921a73475a0e
docs: 增加v1.1.0正式发布前人工验收Runbook
```

当前源码版本已经是 `1.1.0`。现有代码已经具备：

- Codex App Server 协议探测与能力门禁；
- 对话盘点、父子/派生关系与后代闭包；
- 不可变 `ActionPlan`、`TrimPlan`、`MemoryPlan`；
- 内容、管理、裁剪、备份等多类 SHA-256 指纹；
- age 加密备份、完整复验与审计证据；
- 对话清理、归档、永久删除独立门禁；
- 上下文裁剪与派生任务；
- Pending TrimPlan 生命周期；
- 记忆文件管理 MVP；
- MCP Streamable HTTP 只读/审查编排层；
- PySide6 GUI、CLI、Skill、Hook；
- macOS arm64 / Windows x64 构建与验收体系。

这些能力构成了后续升级最重要的安全基础，不应推倒重来。

---

## 3. 当前项目最优先解决的问题

### 3.1 原 GUI 控制器过度集中

当前 `TrimReviewWindow` / `gui/controller.py` 同时承担：

- 对话盘点；
- 对话清理候选；
- 补选候选；
- 永久删除候选；
- 上下文选择；
- 记忆来源与记忆修改；
- Pending Plan；
- 备份状态；
- 敏感内容扫描；
- 多种异步任务 generation；
- 多种写入状态；
- UI 国际化；
- 全部信号和视图状态。

如果继续把地图逻辑加入该控制器，后续维护风险会快速增加。

### 3.2 当前存在两个 GUI 事实来源

当前既有完整的原审查 GUI，又存在 `UnifiedMainWindow` 形式的统一导航壳。

其中部分页面仍处于只读或占位状态，容易导致：

- 用户看到两个功能重叠入口；
- 一个入口功能完整，另一个入口功能不完整；
- 文档与实际能力发生偏差；
- 后续 Agent 重复开发已经存在的功能。

### 3.3 路线图已经落后于实际实现

现有开发计划中仍有部分功能被标为未完成，但主分支代码实际上已经实现，例如：

- 记忆管理 MVP；
- 对话清理补选；
- 永久删除资格展示；
- MCP 工具注册；
- Pending Plan 生命周期；
- 备份并归档闭环。

因此新一轮升级必须先建立新的事实基线。

### 3.4 MCP 尚未完全复用统一工作流层

部分 MCP bridge 代码仍直接使用：

```text
connect_and_probe()
InventoryService
```

而没有全部经过：

```text
ApplicationWorkflows
```

未来应统一连接、超时、能力门禁、错误处理和审计入口。

### 3.5 GitHub 远程回归门禁需加强

建议让：

```text
main
release/**
pull_request
workflow_dispatch
```

全部进入持续 CI，而不是主要依赖本地 `scripts/check.sh` 和人工证据。

---

## 4. 从 dsh-talk-map 应该借鉴的设计

| dsh-talk-map 设计 | CodexSessionManager 决策 | 说明 |
|---|---|---|
| CardId 与 SessionId 分离 | **采用** | 使用 `CardId != ThreadId`，方便未来同一会话出现在多个 Board。 |
| 用户主动导入会话 | **采用** | 不自动把整个账号所有历史会话铺到地图。 |
| 卡片位置是用户数据 | **采用** | 后台刷新不得自动改变位置。 |
| 项目/工作区 Frame | **采用** | 使用项目 cwd / git remote 作为默认分组。 |
| 原生血缘虚线 | **采用** | Codex 原生父子/派生关系以虚线展示。 |
| 用户/CSM 关系实线 | **采用** | CSM 派生任务和用户手工关联以独立样式展示。 |
| summary / key findings / next step | **采用** | 作为“恢复现场”卡片信息。 |
| 摘要输入哈希去重 | **采用** | 内容未变化时不重复生成。 |
| 摘要失败保留旧版本 | **采用** | 不因为一次错误清空已有恢复现场。 |
| 功能层独立降级 | **采用** | App Server / Digest / MCP / Map 各自失败不拖垮整个 App。 |
| React Flow + HTTP + SSE | **不采用** | CSM 继续使用原生 PySide6。 |
| 直接 spawn / inject | **不直接采用** | 改成 Draft → 原 GUI 审查 → TrimPlan → 人工确认 → 派生任务。 |
| autoSync Edge | **当前不采用** | 与 CSM 人工确认模型冲突。 |
| Edge 保存完整 injectedText | **不采用** | 改存 Plan SHA / Projection SHA / Audit 引用。 |

---

## 5. 目标架构

```text
ChatGPT / Skill / MCP / Hook
              │
              │ 仅生成建议或打开请求
              ▼
SuggestionBundle / ReviewRequest
              │
              ▼
┌─────────────────────────────────────────┐
│ ReviewWorkspaceWindow                   │
│                                         │
│  ├─ 会话地图 Surface                    │
│  ├─ 原项目与任务 Surface                │
│  ├─ 上下文审查 Surface                  │
│  ├─ 记忆审查 Surface                    │
│  ├─ Pending / Evidence Surface          │
│  └─ 备份恢复 Surface                    │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Application Services                    │
│                                         │
│  ├─ ApplicationWorkflows                │
│  ├─ WorkspaceStore                      │
│  ├─ ConversationMapService              │
│  ├─ ResumeDigestScheduler               │
│  ├─ PlanIndexService                    │
│  ├─ ContextTransferCoordinator          │
│  ├─ BackupResourceRegistry              │
│  └─ AuditStore                          │
└─────────────────────────────────────────┘
       │                         │
       ▼                         ▼
Official Codex App Server   CSM 私有数据目录
                           workspace.sqlite3
                           plans / suggestions
                           backups / audit
```

---

## 6. 数据权威边界

| 数据 | 唯一权威来源 |
|---|---|
| 会话内容、状态、标题、项目、原生父子关系 | Official Codex App Server |
| CSM 派生会话关系 | AuditStore + TrimPlan |
| 地图位置、颜色、Board、用户关联线 | `workspace.sqlite3` |
| 摘要和下一步 | WorkspaceStore，附带来源和输入指纹 |
| 清理、裁剪、记忆修改 | 现有不可变 Plan |
| 备份可信状态 | BackupManifest + AuditStore |
| LLM 建议 | SuggestionBundle，不是执行授权 |

---

## 7. 推荐代码结构

```text
src/codex_session_manager/
├── workspace/
│   ├── models.py
│   ├── store.py
│   ├── migrations.py
│   ├── import_service.py
│   ├── lineage.py
│   ├── digest.py
│   ├── provenance.py
│   └── context_transfer.py
│
├── gui/
│   ├── controllers/
│   │   ├── inventory_controller.py
│   │   ├── context_controller.py
│   │   ├── cleanup_controller.py
│   │   ├── memory_controller.py
│   │   ├── plan_controller.py
│   │   └── sensitive_scan_controller.py
│   │
│   ├── conversation_map/
│   │   ├── page.py
│   │   ├── scene.py
│   │   ├── view.py
│   │   ├── card_item.py
│   │   ├── edge_item.py
│   │   ├── project_frame_item.py
│   │   ├── inspector.py
│   │   └── commands.py
│   │
│   └── review_workspace_window.py
│
└── resource_providers/
    ├── base.py
    ├── conversation_backup.py
    ├── memory_backup.py
    └── workspace_backup.py
```

会话地图建议使用：

```text
QGraphicsView
QGraphicsScene
QGraphicsObject
QGraphicsPathItem
QUndoStack
```

不增加 React、Node、WebEngine。

---

# 8. 详细升级里程碑

## 阶段 0：冻结 v1.1 基线并修正项目事实

### 目标

把当前 `v1.1.0` 候选状态固定下来，避免地图开发污染正式发布收口。

### 实施内容

1. 从当前稳定基线建立 `release/1.1`。
2. `release/1.1` 只处理：
   - 真实 Codex 账号验收；
   - macOS Developer ID、公证与 Gatekeeper；
   - Windows Authenticode；
   - 固定 Tunnel 与真实 ChatGPT MCP；
   - 安装、升级、回退和发布资产。
3. `main` 开始进入 `v1.2`。
4. 重写当前能力状态文档，区分：
   - 已完成；
   - 已实现但未真实验收；
   - 仍是占位；
   - 正式发布阻塞项。
5. 删除或重定向过期 GUI 占位入口。
6. CI 增加：

```yaml
on:
  push:
    branches:
      - main
      - "release/**"
  pull_request:
    branches:
      - main
      - "release/**"
  workflow_dispatch:
```

7. 增加 CI concurrency cancel。
8. 建立 coverage 基线和不下降门禁。
9. 为 v1.2 建立 GitHub Milestone 和 Issue。

### 验收标准

- 路线图不再把已完成功能列为缺口；
- 统一工作台不再展示与真实能力矛盾的占位按钮；
- 最新 `main` 和 `release/1.1` 都有 GitHub Actions 结果；
- `scripts/check.sh` 与现有验收脚本全部通过；
- v1.1 与 v1.2 的范围完全分离。

### 建议提交

```text
docs: 重算v1.2升级基线与当前能力状态
fix(gui): 移除统一工作台中的过期占位入口
ci: 为main与release分支补齐持续回归门禁
chore(release): 固化v1.1.0候选发布基线
```

---

## 阶段 1：拆解原审查窗口控制器

### 目标

保持原 GUI 外观和行为不变，但让地图能够作为独立模块接入。

### 实施顺序

1. 增加行为锁定测试；
2. 提取任务盘点与筛选控制器；
3. 提取上下文审查控制器；
4. 提取对话清理控制器；
5. 提取记忆管理控制器；
6. 提取计划保存、执行与 Pending 控制器；
7. 提取敏感扫描控制器；
8. 最终让 `TrimReviewWindow` 只负责：
   - 创建控件；
   - 连接高层信号；
   - 切换 Surface；
   - 展示状态和错误。

### 关键约束

- 不先重写 UI；
- 不改变现有 ObjectName；
- 不改变现有审查步骤；
- 不改变 Hook 行为；
- 不改变 Plan 格式；
- 不允许 GUI 控制器直接新增 App Server 写调用。

### 需要补充的行为测试

- 切换清理、上下文、记忆模式不丢状态；
- 外部 SuggestionBundle 正确载入；
- 硬保护覆盖外部建议；
- 语言切换不重新加载会话；
- 关闭窗口时后台 worker 不访问已销毁控件；
- 单实例转发同一请求只打开一次；
- Pending Plan 恢复后仍进入原 GUI；
- 清理、记忆、上下文确认门禁保持不变。

### 验收标准

- `TrimReviewWindow` 不再包含领域策略；
- GUI 只能通过 Controller + `ApplicationWorkflows` 调业务逻辑；
- MCP、CLI、GUI 复用相同工作流；
- 原有 GUI 使用流程无功能回归；
- 主 controller 文件不再继续增长。

### 建议提交

```text
test(gui): 固化统一审查窗口关键行为
refactor(gui): 提取任务盘点与异步加载控制器
refactor(gui): 提取上下文与清理审查控制器
refactor(gui): 提取记忆和计划执行控制器
refactor(core): 统一GUI CLI与MCP工作流入口
```

---

## 阶段 2：建立会话工作区领域与私有存储

### 目标

建立与 UI 无关、可独立测试的地图领域层。

### 建议模型

```text
WorkspaceBoard
ConversationCard
AssociationEdge
ResumeDigest
BoardViewport
LayoutMemory
MapImportRecord
PendingMapPlacement
```

### CardId 与 ThreadId 分离

```text
card-uuid → thread-id
```

同一个 Thread 将来可拥有多个卡片。

### 独立 SQLite

建议新增：

```text
AppPaths.workspace_db
→ data_dir/workspace.sqlite3
```

并启用：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA user_version = N;
```

不要把地图高频状态塞入 append-only 的 `audit.sqlite3`。

### 绑定 Codex 账号根

每个 Board 保存：

```text
account_root_fingerprint
```

如果用户切换 `CODEX_HOME`：

- 原 Board 不自动绑定新账号；
- 地图进入只读隔离状态；
- 用户必须显式导入或映射；
- 不允许仅凭 Thread ID 猜测新账号对象。

### 地图关系三分类

```text
native_lineage
    来自 App Server，计算得出，不持久化

derived_context
    来自成功的 trim.apply 审计事件和 TrimPlan

association
    用户画的本地关联，仅存在 workspace.sqlite3
```

### 隐私设计

- DB 权限 `0600`；
- 不在日志写摘要正文；
- Edge 默认只保存 Plan SHA、Projection SHA 和来源；
- 不复制完整 injected context；
- 地图导出默认加密；
- MCP 默认不返回卡片摘要正文。

### 验收标准

- 数据库迁移可重复；
- 数据库损坏只禁用地图，不影响核心清理/上下文/记忆功能；
- 迁移失败退化为只读；
- 切换 Codex 账号不会误绑定；
- 删除地图卡片不会归档或删除 Codex 会话；
- 找不到的 Thread 标记 orphan，不静默删除位置。

### 建议提交

```text
feat(workspace): 建立会话工作区领域模型
feat(workspace): 增加私有SQLite存储与迁移机制
test(workspace): 覆盖账号隔离布局持久化与损坏恢复
```

---

## 阶段 3：接入只读会话地图 MVP

### 目标

先交付一个不会触发任何 Codex 写入的会话地图。

### UI 结构

原窗口工具栏增加：

```text
项目
记忆
地图
```

建议新增独立概念：

```python
class WorkspaceSurface(StrEnum):
    REVIEW = "review"
    MEMORY = "memory"
    MAP = "map"
    PENDING = "pending"
    BACKUP = "backup"
```

不要把地图塞进 `ReviewMode`。

### MVP 功能

- 导入一个项目；
- 导入选中的会话；
- 卡片自由拖动；
- 16px 网格吸附；
- 位置持久化；
- 平移和缩放；
- 搜索并定位卡片；
- 双击卡片打开原上下文审查；
- 项目 Frame；
- 原生父子关系虚线；
- CSM 已成功派生关系实线；
- 移除卡片只影响地图；
- 颜色标签；
- Fit to content；
- Map / List 两种视图。

### 明确不做

- 不自动导入全部会话；
- 不双击空白直接创建 Codex 会话；
- 不从地图直接归档、删除或修改记忆；
- 不拖线后自动注入上下文；
- 不自动移动已有卡片；
- 不自动进行 LLM 摘要。

### 性能原则

地图首次加载只读取：

```python
include_turns = False
```

禁止为每张卡单独建立 App Server 连接。

完整内容仅在：

- 用户打开卡片；
- 用户手动刷新摘要；
- 卡片进入恢复现场生成队列；

时按批次补全。

### 验收标准

- 原项目、清理、上下文、记忆流程无回归；
- 地图关闭重开后位置和视口一致；
- 刷新会话状态不会覆盖正在拖动的卡片；
- 未导入会话不会自动出现；
- Thread 标题变化只更新文字，不改变位置；
- App Server 离线时仍可打开最后一次缓存地图；
- 所有会话写操作仍只能在原审查 GUI 触发。

### 建议提交

```text
feat(gui): 在原审查窗口增加会话地图入口
feat(map): 实现会话卡片项目分组与持久布局
feat(map): 展示原生血缘和CSM派生关系
test(map): 覆盖导入拖拽刷新与只读安全边界
```

---

## 阶段 4：恢复现场摘要与建议来源可见化

### 目标

让卡片承担“回来后一眼知道下一步”的作用。

### ResumeDigest 建议模型

```python
class ResumeDigest:
    thread_id: str
    input_fingerprint: str

    summary: str
    key_findings: tuple[str, ...]
    next_step: str

    provider_kind: Literal[
        "local_rule",
        "manual",
        "mcp",
        "skill",
        "llm",
    ]

    provider: str | None
    model: str | None
    prompt_version: str | None
    request_id: str | None

    generated_at: datetime
    error: str | None
```

### 默认本地策略

默认恢复现场使用本地确定性信息：

- 标题和 preview；
- 最后活动时间；
- 当前状态；
- Pending Plan 状态；
- 已验证备份状态；
- 是否归档；
- 是否存在未完成 Hook 计划；
- 最后一条可安全展示的用户目标摘要。

### 可选 LLM 策略

只有用户显式启用后才允许：

- MCP 生成；
- Skill 生成；
- 未来本地配置模型生成。

约束：

- 只处理已导入地图的卡片；
- 不处理全账号所有历史；
- UI 明确显示来源；
- LLM 文本不能改变硬保护；
- LLM 文本不能自动生成可执行计划；
- 更换模型或 Prompt 必须产生新的 provenance。

### 调度器

```text
会话变化
  → debounce
  → single-flight queue
  → 读取完整内容
  → 输入指纹
  → 未变化则跳过
  → Provider
  → 保存摘要
```

失败时：

- 保留上一版 summary；
- 保留上一版 key findings；
- 保留上一版 next step；
- 更新 error 和错误时间。

### SuggestionBundle v2

建议拆分：

```text
request_origin:
    GUI / CLI / MCP / Skill / Hook

suggestion_generator:
    local_rule / manual / llm

generator_metadata:
    provider
    model
    prompt_template
    prompt_sha256
    policy_version
```

旧 v1 Bundle 继续支持，通过适配器转换。

### 验收标准

- 相同输入不重复生成；
- 模型失败不清空旧摘要；
- 本地摘要不产生网络请求；
- UI 可区分“本地规则”“ChatGPT 建议”“用户编辑”；
- 切换语言不重建 Scene、不丢失选区和视口；
- 摘要正文默认不暴露给 MCP。

### 建议提交

```text
feat(workspace): 增加可追溯的恢复现场摘要
feat(review): 增加建议生成器与模型来源元数据
feat(map): 在卡片显示下一步计划与备份状态
test(workspace): 覆盖摘要去重降级和来源追踪
```

---

## 阶段 5：地图上下文分叉与 Provenance Edge

### 目标

实现类似 dsh-talk-map 的“拉线分叉”，但严格服从 CSM 的人工确认模型。

### 正确流程

```text
用户从源卡片拖线到空白位置
              ↓
创建 ContextTransferDraft
              ↓
展示将保留 / 摘要 / 排除的上下文预览
              ↓
打开原上下文审查 GUI
              ↓
用户调整并保存 TrimPlan
              ↓
用户明确点击创建派生任务
              ↓
TrimExecutor 通过 App Server 创建
              ↓
源会话保持不变
              ↓
AuditStore 记录成功
              ↓
地图在原落点生成新卡片和实线 Edge
```

### 新增模型

```text
ContextTransferDraft
PendingMapPlacement
ProjectionManifest
DerivedConversationResult
```

`ContextTransferDraft` 应绑定：

- 源 Thread ID；
- 源 `trim_fingerprint`；
- Board ID；
- 目标位置；
- 建议选择；
- 创建时间；
- 过期时间；
- Draft SHA-256。

### Crash Recovery

如果派生线程已经创建，但应用在地图落卡前崩溃：

1. 从 `trim.apply` 审计事件读取 source、target、plan；
2. 查找 `PendingMapPlacement`；
3. 重新创建地图卡片和 Edge；
4. 将 Pending Placement 标记 resolved。

### 安全限制

- 在最终确认前地图不得调用 App Server 写方法；
- 源 Thread Active 时不能执行；
- 源指纹变化后 Draft 失效；
- 拖到现有卡片只建立本地关联，不注入上下文；
- 首版不支持多父合并；
- 首版不支持后台自动同步；
- 投影中必须明确标记历史背景边界；
- 派生会话创建后等待用户下一条消息，不自动执行旧任务。

### 审计增强

建议在 `trim.apply` 审计详情中增加：

```text
projection_sha256
source_trim_fingerprint
target_management_fingerprint
context_boundary_version
map_draft_id
```

Edge 只引用这些证据，不复制完整上下文。

### 验收标准

- 单纯拖线不产生 App Server 写调用；
- 取消预览不留下卡片、Edge 或 Plan；
- 指纹漂移阻止派生；
- 派生失败不显示成功 Edge；
- 成功 Edge 可追溯到 Plan SHA 和 Audit event；
- 崩溃后可以通过审计恢复；
- 源会话内容和指纹保持不变。

### 建议提交

```text
feat(context): 增加地图上下文分叉草稿
feat(context): 将地图分叉接入原上下文审查GUI
feat(audit): 记录上下文投影与地图来源证据
test(context): 覆盖分叉取消漂移失败和崩溃恢复
```

---

## 阶段 6：统一 Pending、备份恢复与审计中心

### 目标

消除两个 GUI Shell 和多个占位页面。

### 推荐主窗口

```text
ReviewWorkspaceWindow
```

包含：

- 项目与任务；
- 会话地图；
- 上下文审查；
- 记忆管理；
- Pending Plans；
- 备份恢复；
- 审计与证据。

旧 `UnifiedMainWindow` 进入兼容期：

1. 旧入口继续接受 `DesktopCommand`；
2. 内部转发新主窗口；
3. 一个版本后删除旧窗口类。

### Resource Provider

统一资源发现、备份、验证和恢复 UI，但不把所有领域 Plan 强行合并。

```python
class BackupResourceProvider(Protocol):
    resource_kind: str

    def inspect(...)
    def prepare_backup(...)
    def verify_backup(...)
    def prepare_restore(...)
    def apply_restore(...)
```

实现：

```text
ConversationBackupProvider
MemoryBackupProvider
WorkspaceBackupProvider
```

地图导出可以作为 age 加密备份中的 sidecar。

### 地图恢复规则

跨账号恢复时：

- 不自动绑定旧 Thread ID；
- 未解析卡片进入 quarantine；
- 用户手动映射或保留为只读历史卡；
- Edge 只有两端都解析后才恢复可交互；
- Digest 标记为来自旧账号备份。

### PlanIndexService

不要合并 `ActionPlan`、`TrimPlan`、`MemoryPlan`。

新增只读索引：

```text
PlanReference
  kind
  plan_id
  plan_sha256
  target_ids
  created_at
  status
  source
```

### 验收标准

- 只有一个用户可见主窗口；
- CLI、Skill、MCP、Hook 入口仍打开正确页面；
- 对话、记忆和地图可通过统一向导备份；
- 地图数据默认进入 age 加密包；
- 恢复不会绕过账号根绑定；
- AuditStore 仍保持 append-only，不被 Undo 修改。

### 建议提交

```text
refactor(gui): 统一审查地图与待处理计划主窗口
feat(backup): 建立通用备份资源提供器
feat(backup): 支持会话地图加密导出与隔离恢复
feat(pending): 统一各类计划和审查请求索引
```

---

## 阶段 7：ChatGPT MCP 与地图编排

### 目标

在完成现有真实 MCP 发布门禁后，增加地图相关工具。

### 建议新增工具

```text
inspect_conversation_map
open_conversation_map
prepare_map_import
prepare_context_transfer
get_context_transfer_status
```

### 不得新增

```text
archive_thread
delete_thread
apply_trim_plan
inject_context
edit_memory
move_card_and_execute
```

即使工具名叫 `prepare_*`，也只能创建：

- SuggestionBundle；
- ReviewRequest；
- ContextTransferDraft；
- Pending queue entry。

### MCP 默认隐私边界

`inspect_conversation_map` 默认只返回：

- Card ID；
- Thread ID；
- 标题；
- 项目；
- 更新时间；
- 状态；
- 关系类型；
- 是否有摘要。

默认不返回：

- 完整摘要；
- 对话正文；
- ContextProjection；
- Memory 内容；
- Plan 正文。

### 真实验收

必须覆盖：

- 固定 Tunnel；
- Bearer Token；
- Origin 限制；
- 工具快照；
- 断线恢复；
- 真实 ChatGPT 工作区；
- GUI 唤起；
- 权限隔离；
- 未批准工具不可见。

### 建议提交

```text
feat(mcp): 增加会话地图只读盘点工具
feat(mcp): 增加上下文分叉审查编排工具
test(mcp): 覆盖地图工具权限内容边界与重放
docs(mcp): 更新真实ChatGPT连接与验收说明
```

---

# 9. 版本规划

| 版本 | 范围 |
|---|---|
| `v1.1.0` | 当前功能正式发布收口：真实账号、签名、公证、Windows、真实 MCP |
| `v1.2.0` | 控制器拆分、统一事实来源、WorkspaceStore、只读地图 MVP、本地恢复现场 |
| `v1.3.0` | 可追溯上下文分叉、Suggestion provenance v2、统一 Pending 和备份恢复 |
| `v2.0.0` | 多 Board、Alias Card、多父合并、选段注入、时间视图、WIP 管理 |

## 9.1 v2.0 才应考虑的功能

- 同一 Thread 多个 Alias Card；
- 多父会话合并；
- 选中多个来源构建新上下文；
- 时间镜头；
- 整板归档；
- 长期未动卡片变暗；
- Project WIP 上限；
- Board 导出与分享。

## 9.2 暂不建议承诺的功能

- 自动向已有会话推送上下文；
- 后台自动执行 Edge；
- 无人工确认的 Context Auto-Sync；
- 自动归档；
- 自动永久删除；
- 自动修改记忆；
- 自动导入整个账号的所有会话。

---

# 10. 全局交付门禁

每一个里程碑都应同时提交：

```text
代码
单元测试
GUI测试
自动验收工具
中文文档
英文文档
路线图状态
迁移说明
```

并使用聚焦的中文 Conventional Commit。

全局 Definition of Done：

1. 任何 Codex 写入都必须经过现有 Plan 和人工确认；
2. 地图操作本身不构成执行授权；
3. 永久删除路径保持独立、高风险、默认不选中；
4. 原会话在上下文优化中保持不变；
5. LLM 只生成建议或摘要；
6. 卡片位置不会被后台刷新覆盖；
7. 地图数据库与 Codex 数据库完全分离；
8. Codex 账号根变化时地图失败安全；
9. App Server、Digest 或 MCP 不可用时主程序仍可打开；
10. macOS 和 Windows 均通过源码、GUI、打包和真实安装验收。

---

# 11. 推荐实际启动顺序

第一轮建议严格按以下顺序实施：

```text
1. docs: 重算v1.2升级基线与当前能力状态
2. ci: 为main与release分支补齐持续回归门禁
3. test(gui): 固化统一审查窗口关键行为
4. refactor(gui): 拆分原审查窗口内部控制器
5. feat(workspace): 建立会话地图领域模型与私有存储
6. feat(gui): 接入只读会话地图MVP
```

在第 6 步完成并通过首次地图验收之前，不建议开始：

- 上下文拖线分叉；
- LLM 自动摘要；
- 多 Board；
- 多父合并；
- 地图 MCP 编排扩展。

---

# 12. 最终产品定位

升级后的 CodexSessionManager 不应只是：

> “Codex 对话清理与上下文裁剪工具”

而应逐步升级为：

> **面向长期 Codex / Agent 工作流的安全会话工作区、上下文管理器与可审计生命周期工具。**

其核心差异化能力应是：

```text
会话空间组织
+ 恢复现场
+ 血缘关系
+ Pending 状态
+ 上下文传递 Provenance
+ 人工审查
+ 不可变计划
+ 备份与审计
```

这也是 `dsh-talk-map` 最值得借鉴的部分，同时保留 CodexSessionManager 相比普通会话图工具更强的安全边界。
