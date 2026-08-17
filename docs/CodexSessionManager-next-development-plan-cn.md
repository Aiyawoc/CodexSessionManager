# CodexSessionManager 下一步开发计划

> 状态：实施中
> 目标版本：`v1.1`–`v2.0` 迭代路线
> 核心原则：LLM 负责建议，本地 GUI 负责最终确认，所有写操作经过计划、指纹复核、备份与审计。


## 0. 本轮实施进度（2026-08-17）

首个基础切片已经设计并配套实现：

- [x] 将完整路线图固化为项目文档；
- [x] 新增带 SHA-256、有效期和账号根绑定的 `ReviewRequest`；
- [x] 新增按业务动作约束的 `SuggestionBundle`；
- [x] 新增私有 review request / suggestion 存储目录及原子写入；
- [x] 新增 `CodexSessionManager --request REQUEST.json` 桌面入口；
- [x] `context_trim` 请求可自动加载目标对话；
- [x] 对话清理、记忆、备份和恢复请求先以只读占位模式打开，避免未完成页面误执行写入；
- [x] 补充篡改、过期、账号漂移、路径逃逸、符号链接、动作越权和 dispatcher 路由测试；
- [x] 单实例窗口置前、进程间请求转发及失败请求私有队列；
- [x] 新增只读 `open_review_demo` 编排桥接函数；
- [x] 新增统一主窗口、五类功能入口及独立页面骨架；
- [x] 新增只读待处理计划中心，可索引审查请求与已保存 TrimPlan；
- [x] 新增本地安全清理候选池、`prepare_cleanup_review` 与 `csm cleanup review`；
- [x] 清理页可按用户最终选择重读当前状态、复核建议指纹并保存不可变 ActionPlan；
- [ ] 对话清理专用页面及“备份并归档”闭环；
- [ ] 待处理计划的状态流转、空闲复核与继续应用；
- [ ] 记忆文件管理 MVP；
- [ ] 将只读桥接函数注册为 ChatGPT MCP/App 对外工具并完成真实入口联调。

### 0.1 当前剩余缺口（按优先级）

1. **对话清理执行闭环**：清理页尚未从当前真实盘点补选目标，也未展示项目、完整后代树、大小、风险和备份状态；“备份并归档”向导、age 完整验证，以及把已生成 ActionPlan 接入归档和审计的串联仍未完成。
2. **ChatGPT MCP/App 正式入口**：`open_review_demo`、`prepare_cleanup_review` 和 `open_cleanup_review` 已有本地只读编排实现，但尚未注册为对外 MCP 工具，也未完成从真实 ChatGPT 对话到已安装桌面应用的端到端验收。
3. **待处理计划状态机**：当前页面能安全索引请求和 TrimPlan，但尚未记录已应用/已取消状态，不能在源任务 idle 后重新探测能力并继续执行。
4. **上下文页面彻底拆分**：统一主窗口已建立，现有完整裁剪能力仍由独立 `TrimReviewWindow` 承载；大型控制器尚未拆成可嵌入页面与独立页面控制器。
5. **记忆文件管理 MVP**：允许根登记、分段模型、diff、版本备份、原子写入、并发漂移校验和恢复均尚未实现。
6. **统一备份/恢复中心**：已有对话备份与逻辑恢复服务，但资源提供器、历史清单和 GUI 向导尚未接入；记忆文件备份/恢复尚不存在。
7. **外部结构化建议与发布验收**：尚缺 LLM 建议适配器、建议来源区分、真实账号联调、安装包运行验收以及 macOS/Windows 目标环境验证。

## 1. 产品目标

CodexSessionManager 的目标是把“对话清理、上下文优化、记忆管理、备份恢复”统一到一个安全、可审查、可恢复的桌面工作流中。

### 1.1 对话清理

用户在 ChatGPT 对话中发出“清理对话”命令后：

1. Skill/MCP 读取项目与对话清单；
2. 本地规则先建立安全候选池；
3. LLM 对历史较久、低活跃度的项目/对话进行梳理和排序；
4. 生成只包含建议的结构化审查请求；
5. 唤起 CodexSessionManager 对话清理面板；
6. 面板按项目展示建议归档的对话、根对话及派生后代；
7. 用户可以排除、补选或修改操作；
8. 用户点击“备份并归档”后，程序生成最终不可变计划、完成加密备份与验证，再执行归档；
9. 永久删除作为独立的高风险流程，默认不选中，也不由自动化直接触发。

### 1.2 手动优化上下文

用户在 ChatGPT 对话中发出“清理上下文”命令，或触发 PreCompact Hook 后：

1. 程序读取本对话完整上下文；
2. 本地硬规则标记不可删除内容；
3. LLM 或本地建议器给出 Keep、Exclude、Summary、Protect 建议；
4. 唤起上下文优化面板并自动加载当前对话；
5. 用户查看、修改或重新编辑摘要；
6. 用户确认后创建优化后的派生对话；
7. 原对话保持不变；
8. 可选地对原对话执行备份并归档。

对于 Hook 模式，Hook 只允许保存计划。源任务变为空闲后，由用户在“待处理计划”页面继续执行，Hook 进程本身不创建派生任务。

### 1.3 记忆操作

用户在 ChatGPT 对话中发出“清理记忆”命令后：

1. 程序发现用户明确允许的本地记忆文件；
2. 对记忆文件按标题、段落或列表项拆分；
3. LLM 或本地规则提出保留、删除、替换和保护建议；
4. 唤起记忆管理面板；
5. 用户逐项裁切、修改或保护；
6. 面板展示最终 diff；
7. 用户确认后先创建备份，再以原子方式写入；
8. 写入后重新读取并校验结果；
9. 所有操作进入审计记录，并可从版本历史恢复。

首版只管理用户明确登记的本地 Markdown/文本记忆文件，不声称直接管理 ChatGPT 账号的服务器端 Memory。

### 1.4 通用备份与恢复

主面板提供通用备份/恢复入口，支持：

- 当前对话；
- 已选对话及其派生后代；
- 当前记忆文件；
- 所有已登记记忆文件；
- 已验证备份历史；
- 对话逻辑恢复；
- 记忆文件按 diff 恢复。

## 2. 当前项目基础

项目当前已经具备：

- Codex App Server 协议探测与能力门禁；
- 按项目、时间、状态、来源和关系进行对话盘点；
- 不可变 ActionPlan、ImportPlan、TrimPlan；
- age 加密备份、完整解密校验和审计证据；
- 归档、反归档、永久删除门禁；
- 逻辑恢复和导入；
- 上下文完整加载、本地建议、Keep/Exclude/Summary/Protect；
- 上下文派生任务创建；
- PreCompact/PostCompact Hook；
- PySide6 GUI、CLI、Skill 和审计链；
- macOS arm64 与 Windows x64 测试构建流程。

当前基础已经补齐统一审查协议、单实例桌面转发、统一主窗口、只读待处理索引和本地清理候选生成。剩余缺口集中在：

- 将本地只读编排函数注册为正式 ChatGPT MCP/App 工具并完成真实入口联调；
- 将 `TrimReviewWindow` 的大型控制器彻底拆成可嵌入页面和独立控制器；
- 完成对话清理页的真实盘点补选、后代树、风险和备份状态展示；
- 打通“备份并归档”向导、age 验证，并把已能本地重建的最终计划接入归档与审计闭环；
- 为待处理计划增加状态流转、能力复核、源任务空闲判断和继续应用；
- 实现记忆文件管理及统一备份/恢复中心；
- 接入严格结构化的外部建议，并完成真实账号、安装包和目标平台验收。

## 3. 核心安全原则

### 3.1 LLM 只提出建议

LLM 输出不能直接成为可执行计划。LLM 只能生成 `SuggestionBundle`，最终计划必须由本地程序根据当前真实状态重新创建。

### 3.2 所有建议绑定稳定对象和指纹

每条建议至少绑定：

- 目标 ID 或目标文件路径；
- 内容/管理指纹；
- 建议动作；
- 理由；
- 置信度；
- 生成时间和来源。

目标不存在、指纹变化、账号根变化或请求过期时，建议必须失效。

### 3.3 上下文优化不原地修改历史

上下文优化继续创建派生任务。原任务保持不变，不直接编辑 Codex JSONL、SQLite 或 rollout。

### 3.4 自动化上限是归档

LLM 可以建议归档，但不能自动永久删除。永久删除继续要求独立计划、可信归档历史、已验证备份、进程门禁和精确确认。

### 3.5 记忆文件仅在允许根目录内写入

拒绝符号链接、路径逃逸和未登记路径。写入前复核指纹，写入时使用临时文件、`fsync` 和原子替换，写入后重新读取验证。

## 4. 目标架构

```text
ChatGPT / Skill / MCP
        │
        │ 只读盘点、结构化建议、准备审查请求
        ▼
CSM 编排层
        ├── ReviewRequest
        ├── SuggestionBundle
        ├── 请求过期/签名/账号根校验
        └── 本地桌面唤起
                │
                ▼
CodexSessionManager.app
        ├── 对话清理页
        ├── 上下文优化页
        ├── 记忆管理页
        ├── 待处理计划页
        ├── 备份/恢复中心
        └── 审计页
                │
                ▼
本地安全执行层
        ├── CleanupExecutor
        ├── TrimExecutor
        ├── MemoryExecutor
        ├── Backup/Restore Services
        └── AuditStore
```

## 5. 新增共享协议

### 5.1 ReviewRequest

建议字段：

```text
schema_version
request_id
operation
source
account_root_fingerprint
target_ids
target_paths
suggestion_bundle_path
created_at
expires_at
request_sha256
```

`operation`：

```text
conversation_cleanup
context_trim
memory_edit
backup
restore
```

要求：

- Pydantic 冻结模型；
- 拒绝未知字段；
- SHA-256 封装；
- 有效期校验；
- 账号根指纹校验；
- 只允许从 CSM 私有请求目录加载；
- 防止路径逃逸和符号链接；
- 支持幂等 request ID。

### 5.2 SuggestionBundle

建议字段：

```text
schema_version
bundle_id
operation
source
created_at
expires_at
targets[]
  target_id / target_path
  source_fingerprint
  suggested_action
  reason
  confidence
  suggested_summary / replacement
bundle_sha256
```

它只代表建议，不代表写入授权。

## 6. 分阶段开发计划

## 阶段 0：验证 ChatGPT 到桌面面板的最小链路

### 工作项

- [x] 新增只读编排函数 `open_review_demo`；
- [ ] 将 `open_review_demo` 注册为对外 MCP 工具；
- [x] 生成临时 `ReviewRequest`；
- [x] 增加桌面入口 `CodexSessionManager --request REQUEST.json`；
- [x] 根据 operation 打开指定页面或只读占位模式；
- [x] 应用运行中时复用进程并置前；
- [x] 失败时写入待处理请求队列；
- [x] 重复请求保持幂等。

### 验收标准

- [ ] ChatGPT 发出命令后，本机能打开指定模式窗口；
- [x] 演示链路不执行任何 Codex 或受管文件写入；
- [x] 过期、伪造或账号根不匹配请求被拒绝；
- [x] 同一请求不会创建重复窗口。

## 阶段 1：拆分主窗口并建立统一审查基础

### 工作项

- [ ] 将 `TrimReviewWindow` 的大型控制器完全拆为窗口壳与可嵌入页面；
- [x] 新增 `ConversationCleanupPage` 只读建议审查页；
- [x] 新增 `ContextReviewPage` 稳定入口，继续复用专用审查窗口；
- [x] 新增 `MemoryManagerPage` 占位与只读模式；
- [x] 新增 `PendingPlansPage` 只读 MVP；
- [x] 新增 `BackupRestoreDialog` 只读入口；
- [x] 左侧功能栏提供五类入口；
- [x] 保持 `csm trim review TASK_ID` 兼容；
- [x] 增加 `csm gui open --request/--page/--thread ...`；
- [x] 增加单实例和进程间请求转发。

### 验收标准

- [x] 现有上下文裁剪能力无回归；
- [x] 命令行可直接打开三个以上页面；
- [x] 页面控制器不绕过计划层写入；
- [x] GUI 回归测试通过。

## 阶段 2：对话清理完整闭环

### 工作项

- [x] 本地规则生成安全候选池；
- [x] 本地编排层输出结构化建议；
- [ ] 将清理建议能力注册为正式 Skill/MCP 工具；
- [ ] GUI 按项目显示建议、根和全部后代；
- [ ] 显示最后活动时间、大小、风险、建议理由和备份状态；
- [x] 支持用户取消建议选择；
- [ ] 支持从当前真实盘点中补选安全目标；
- [ ] 新增“备份并归档”向导；
- [ ] 创建并完整验证 age 备份；
- [x] 基于最终选择重新生成 ActionPlan；
- [x] 生成计划时再次复核状态、能力、建议指纹与后代闭包；
- [ ] 执行归档并记录审计；
- [ ] 独立展示满足条件的永久删除候选，默认不选中。

### CLI

```text
csm cleanup review
csm cleanup review --older-than-days 90
csm cleanup review --request REQUEST.json
csm cleanup eligible-purge
```

### MCP 工具

```text
inspect_conversation_inventory
prepare_cleanup_suggestions
open_cleanup_review
```

### 验收标准

- [ ] 用户取消的对话不会被归档；
- [x] 后代闭包不可遗漏；
- [x] 无有效备份时不能归档；
- [x] 默认自动化上限是归档；
- [x] 状态或建议指纹漂移使计划失效；
- [x] 既有 CleanupExecutor 的执行结果进入审计链。

## 阶段 3：LLM 辅助上下文优化与待处理计划

### 工作项

- [ ] 扩展 `ContentSuggestionProvider` 为严格结构化接口；
- [ ] 新增 `ExternalSuggestionBundleProvider`；
- [ ] 每条建议绑定 turn/item ID 和指纹；
- [ ] 本地 `validate_selections` 始终拥有最终否决权；
- [ ] GUI 区分 LLM、本地规则、用户修改和硬保护；
- [ ] 应用后创建优化副本；
- [ ] 新增“验证后归档原对话”选项；
- [x] 新增 `PendingPlanStore` 只读索引 MVP；
- [x] Hook 保存的 TrimPlan 可在待处理计划页出现；
- [ ] 源任务空闲后允许用户继续应用；
- [ ] 内容或能力变化时使计划失效并重新生成。

### 验收标准

- [ ] LLM 建议不能覆盖硬保护；
- [ ] 工具调用与结果成组处理；
- [ ] 文件变更与验证成组处理；
- [ ] Hook 失败、关闭或超时继续原生压缩；
- [ ] 原始对话保持不变。

## 阶段 4：记忆文件管理 MVP

### 支持范围

- [ ] 用户显式登记的 `MEMORY.md`；
- [ ] 用户明确允许的项目说明文件；
- [ ] CSM 配置中登记的用户级记忆根；
- [ ] `AGENTS.md` 等指令文件使用独立开关，不默认作为普通记忆修改。

### 新增模型

```text
MemorySource
MemorySnapshot
MemorySegment
MemorySelection
MemoryPlan
MemoryBackupManifest
MemoryRestorePlan
```

动作：

```text
KEEP
DELETE
REPLACE
PROTECT
```

### 分段规则

1. YAML front matter；
2. 一级/二级标题；
3. 列表项或独立段落；
4. 无法识别的区域作为不可拆分原始块。

稳定分段 ID 由以下内容构成：

```text
文件相对路径
+ 标题路径
+ 原始字节范围
+ 内容 SHA-256
```

### 安全写入

- [ ] 只允许登记根目录；
- [ ] 拒绝符号链接和路径逃逸；
- [ ] 写入前检查指纹、大小、mtime，必要时检查 inode；
- [ ] 自动创建加密备份或私有版本快照；
- [ ] 展示最终 unified diff；
- [ ] 用户再次确认；
- [ ] 临时文件写入、flush、fsync、原子替换；
- [ ] 重读并验证结果；
- [ ] 记录审计事件；
- [ ] 失败时保留原文件。

### CLI

```text
csm memory sources
csm memory list
csm memory show SOURCE_ID
csm memory review SOURCE_ID
csm memory suggest SOURCE_ID
csm memory apply PLAN.json --confirm PLAN_ID
csm memory history SOURCE_ID
csm memory restore plan ...
csm memory restore apply ...
```

### 验收标准

- [ ] 不可修改允许范围外文件；
- [ ] 并发修改使旧计划失效；
- [ ] 每次修改有可恢复版本；
- [ ] diff 与实际写入一致；
- [ ] 编码、换行符和未知 Markdown 保持；
- [ ] 敏感信息默认不离开本机。

## 阶段 5：统一备份/恢复中心

### 工作项

- [ ] 抽象 `BackupResourceProvider`；
- [ ] 实现 `ConversationBackupProvider`；
- [ ] 实现 `MemoryFileBackupProvider`；
- [ ] GUI 支持当前对话、已选对话、当前记忆和全部登记记忆；
- [ ] 备份创建后自动完整验证；
- [ ] 展示备份历史和 manifest；
- [ ] 对话恢复继续创建新 ID；
- [ ] 记忆恢复展示 diff 后原子执行；
- [ ] 归档流程复用“备份并归档”简化向导。

## 阶段 6：MCP/App 集成、测试和发布

### MCP 工具边界

允许：

```text
inspect_*
suggest_*
prepare_*_review
open_*_review
get_pending_review_status
```

不允许直接暴露：

```text
delete_*
purge_*
apply_memory_edit
execute_trim
```

最终高风险写入留在本地 GUI，由用户操作触发。

### 新增测试

```text
tests/test_review_request.py
tests/test_suggestion_bundle.py
tests/test_cleanup_review_gui.py
tests/test_pending_trim_plans.py
tests/test_memory_inventory.py
tests/test_memory_plans.py
tests/test_memory_executor.py
tests/test_memory_backup_restore.py
tests/test_mcp_bridge.py
tests/test_desktop_launch.py
```

必须覆盖：

- 请求伪造、过期和重放；
- LLM 返回不存在目标；
- 内容指纹变化；
- 账号根不匹配；
- GUI 取消选择；
- 备份失败；
- 符号链接和路径穿越；
- 文件并发修改；
- Hook 超时；
- 应用已运行时窗口唤起；
- App Server 未知协议时退化为只读。

## 7. 推荐代码结构

```text
src/codex_session_manager/
├── review_requests.py
├── suggestions.py
├── pending.py
├── memory_models.py
├── memory.py
├── memory_backup.py
├── mcp_bridge.py
└── gui/
    ├── main_window.py
    ├── conversation_cleanup_page.py
    ├── context_review_page.py
    ├── memory_manager_page.py
    ├── pending_plans_page.py
    └── backup_restore_dialog.py
```

现有模块调整：

| 模块 | 调整方向 |
|---|---|
| `gui/controller.py` | 拆分窗口壳与页面控制器 |
| `gui/main_window.ui` | 功能导航、页面容器、通用备份/恢复入口 |
| `cleanup.py` | 保持执行器，增加候选池与建议适配层 |
| `trim.py` | 接入外部结构化建议，保留本地规则和硬保护 |
| `plans.py` | 支持 MemoryPlan、ReviewRequest 等新类型 |
| `cli.py` | 增加 cleanup review、memory、pending 等命令 |
| `dispatcher.py` | 支持 `--request`、单实例和窗口置前 |
| `skills/manage-codex-sessions/` | 增加对话、上下文和记忆三套工作流 |

## 8. 第一批实施提交建议

1. `docs: 增加统一会话与记忆管理开发路线图`
2. `feat: 增加统一审查请求与建议数据模型`
3. `feat: 支持通过请求文件打开指定审查模式`
4. `test: 覆盖审查请求校验与桌面入口`
5. `refactor: 拆分主窗口与上下文审查页面`
6. `feat: 增加对话清理建议审查页面`
7. `feat: 增加归档前加密备份向导`
8. `feat: 打通 ChatGPT MCP 到清理面板的只读链路`

## 9. 首个可交付里程碑

首个里程碑定义为：

> 用户在 ChatGPT 中要求清理旧对话，系统分析安全候选并打开本地清理面板；用户排除或确认后，程序先完成加密备份，再只归档被确认的对话。

完成条件：

- [x] ReviewRequest/SuggestionBundle 已实现并经过测试；
- [x] 桌面应用可按请求打开对话清理页；
- [ ] 建议对话按项目分组并可调整选择；
- [x] 最终计划由本地重建；
- [ ] 归档前自动完成加密备份与验证；
- [ ] 归档执行经过状态、能力、指纹和后代闭包复核；
- [ ] 审计链记录完整；
- [x] 永久删除未进入自动流程。

## 10. 执行顺序

当前应按以下顺序推进：

1. [x] 将本路线图加入 `docs/`；
2. [x] 实现 `ReviewRequest` 与 `SuggestionBundle`；
3. [x] 扩展 `AppPaths`，增加私有 requests/suggestions/pending 目录；
4. [x] 扩展 dispatcher，支持 `--request`、单实例和窗口置前；
5. [x] 建立统一主窗口、五类入口和只读页面骨架；
6. [x] 实现只读待处理索引和本地清理安全候选池；
7. [x] 覆盖请求安全、桌面路由、页面导航、候选池和待处理索引测试；
8. [ ] 完成清理页的真实盘点补选、项目/后代分组和备份状态展示；
9. [ ] 实现“备份并归档”向导，并把已重建的最终 ActionPlan 接入执行闭环；
10. [ ] 注册正式 MCP/App 只读工具并完成真实 ChatGPT 到桌面的联调；
11. [ ] 为待处理 TrimPlan 增加状态机、空闲复核和继续应用；
12. [ ] 推进记忆文件管理 MVP、统一备份恢复和外部结构化建议。
