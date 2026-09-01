# CodexSessionManager 验收文档索引

本目录区分首次交付、正式发布、协议画像、本机真实账号和单项验收收口。报告任何结果时必须标明证据层级；fixture、offscreen GUI、本机构建、真实 App Server 写入和生产发布不能混称为“E2E 通过”。

## 当前 v1.1 状态

- 当前基线：`main` 当前提交；单项历史收口文档各自保留当时的精确基线。
- 当前阶段：继续完成 v1.1 其它功能验收；2.4 上下文应用执行层不再强行推进。
- 2.4 判定：`CLOSED_WITH_UPSTREAM_BLOCKER`
- 已证明：上下文审查与投影计划可生成；源任务在失败后保持完整。
- 未证明：派生投影可以持久化；人工投影可以安装回原任务；敏感信息已经从 Codex 历史或活动上下文中删除。
- 后续顺序：先完成 v1.1 其它验收；再优先实现敏感信息修改计划与受支持目标；最后研究其它官方上下文应用方向。

### 当前能力边界

- 上下文审查/投影计划：可用；
- 应用到原任务：不可用；
- 派生投影：当前真实 round-trip 失败，保持 `blocked_upstream`；
- 敏感信息确定性 `Replace/Redact/Protect`：v1.1 其它验收完成后的下一优先级；
- 2.5 永久删除：固定 14 天等待已取消；继续按用户主动单选、独立单根计划、CSM 可信归档证据、与归档事件绑定的当前有效备份、进程/loaded/后台终端复核和精确双重确认验收。只有完整备份仍不具备删除资格。

## 现行入口

### 本机受控验收

- [`local-controlled-v1.1.0.md`](local-controlled-v1.1.0.md)：v1.1.0 本机两步受控验收主 Runbook。
- [`v1.1.0-phase-2.4-context-projection-closure.md`](v1.1.0-phase-2.4-context-projection-closure.md)：2.4 上下文投影的正式结论、真实证据和停止边界。对 2.4 的冲突表述以该文件为准。

### 首次交付与正式发布

- [`first-delivery-v1.1.0.md`](first-delivery-v1.1.0.md)：首次交付候选验收。
- [`formal-release-manual-v1.1.0.md`](formal-release-manual-v1.1.0.md)：正式发布前人工验收；在统一修订前，不得把其中的上下文应用步骤视为当前已验证能力。

### 协议画像与历史验收

- [`app-server-schema-approval.md`](app-server-schema-approval.md)：App Server 精确画像人工批准流程。
- [`macos-real-account-v1.0.1.md`](macos-real-account-v1.0.1.md)：v1.0.1 历史真实账号验收。

## 规范性补充

- [`../CodexSessionManager-v1.1-context-projection-and-sensitive-data-plan.md`](../CodexSessionManager-v1.1-context-projection-and-sensitive-data-plan.md)：v1.1 收口、敏感信息修改优先级和后续研究计划。
- [`../adr/0009-defer-context-projection-application.md`](../adr/0009-defer-context-projection-application.md)：延期上下文投影应用的架构决策。

在 README、Skill、旧 Runbook 和二期计划完成统一修订前，上述两个文件以及 2.4 收口记录对以下内容具有优先级：

- 2.4 是否通过；
- 当前是否支持上下文应用；
- 派生任务写入是否可用；
- 对外可以声明的上下文能力；
- 后续研发顺序。

2.4 的计划层通过不代表 Codex 历史已改变；任何 `thread/inject_items` 方法存在、空响应或目标 ID 创建结果，都不能作为投影持久化证据。

## 证据规则

可提交到 Git 的验收证据仅包括：

- 精确版本和候选 SHA；
- schema、计划、投影、备份和内容散列；
- 固定状态和审计事件编号；
- 脱敏后的能力结论；
- 不含真实正文的失败分类。

不得提交：

- 原始任务 ID、完整标题或正文；
- `.codex` 快照和解密目录；
- age identity、token、认证文件；
- 未脱敏本机路径；
- MCP 环境中的 secret；
- 能恢复真实用户内容的日志。

## 结果术语

- `passed`：在声明的证据层级完整验证；
- `failed`：实现或行为不满足预期；
- `blocked_upstream`：CSM 安全层通过，但依赖的官方能力不存在或真实语义未兑现；
- `not_run`：尚未执行；
- `waiting_period`：受时间门禁约束；
- `unavailable`：当前版本对用户不可交付；
- `production_ready: false`：不论其它阶段结果如何，当前候选不是生产验收。
