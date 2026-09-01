# v1.0.1 macOS 真实账号与 Cocoa GUI 验收 Runbook

> **SUPERSEDED IN PART（2026-09-01）**：本文是历史验收流程；其中精确版本/全量 schema 授权和永久删除相关边界不描述当前产品。第一版现行任务管理只提供盘点、备份、批量归档和反归档；现行契约见 [`ADR 0011：版本无关、契约敏感的 App Server 操作边界`](../adr/0011-version-independent-operation-contracts.md)。正文结论保持不变。

本流程必须由维护者在真实 Apple Silicon macOS 上逐阶段执行。它不会被 CI 或“一键脚本”替代，也不授权永久删除、恢复、导入、真实 Hook 安装、发布、签名或公证。

## 1. 范围和前置条件

- 使用专门创建、无重要内容、`idle`、未 pinned、无 spawned descendants 的来源任务。
- 退出其它可能操作同一账号的 Codex 进程；确认 `CODEX_HOME` 与 `CSM_CODEX_HOME` 未冲突。
- 使用真实 Cocoa 窗口和稳定安装路径；源码/offscreen 预览只能作为补充证据。
- 准备独立 age recipient 与对应 identity 文件。口令、identity 内容和绝对私有路径不得写入报告、日志、Issue 或模型上下文。
- 任一写请求超时都按“可能已完成”处理：停止后续写入，先按任务 ID 复读实际状态，不得盲目重试。

## 2. 只读基线

每步完成后单独记录结果，失败即停止。

```bash
csm doctor
csm schema audit --output csm-schema-audit-v1.json
csm threads list
csm threads show SOURCE_TASK_ID --include-content
```

核对 schema 报告包含工具版本、`darwin`、`arm64`、Codex 版本、二进制哈希、schema 哈希、能力指纹和差异结论，且不含可执行文件或用户目录绝对路径。只有精确画像命中才能继续写入阶段。

## 3. 实体 Cocoa GUI

在 `1600×900` 和最小 `1280×720` 下分别检查：

1. 中文输入法输入、英文输入和粘贴均不丢字，搜索框焦点清晰。
2. 搜索项目、任务标题和完整任务 ID；多选后按钮状态与选中范围一致。
3. 收起/展开任务面板后时间线填满剩余宽度；时间线与原文 Splitter 可拖动。
4. 在 100%、125%/Retina 等可用缩放下检查文字、图标、风险提示和禁用状态。
5. 选择来源任务并保存 TrimPlan；此时来源任务不得变化。
6. 派生写操作进行时尝试关闭窗口：窗口应等待或明确阻止关闭，不能遗留无归属 Worker。

保存 TrimPlan 后单独记录其 `plan_sha256`。不要在本阶段归档来源任务。

## 4. 派生裁剪闭环

1. 在 GUI 使用已保存计划创建派生任务。
2. 逐 ID 复读来源和派生任务，确认来源任务的模型可见消息顺序与来源指纹未变。
3. 对照 TrimPlan 检查派生任务的模型可见消息顺序、投影哈希和来源任务指纹。
4. 如果发现未知 item、缺失工具调用/结果组或投影差异，停止，不进入备份与归档。

## 5. 备份、复验、审计和只归档派生任务

在 GUI 选择来源任务和派生任务，执行“创建并复验备份”；或等价地逐 ID 使用 CLI：

```bash
csm backup create acceptance.csmbackup \
  --thread SOURCE_TASK_ID \
  --thread DERIVED_TASK_ID \
  --recipient age1... \
  --identity /secure/path/identity.txt
csm backup verify acceptance.csmbackup --identity /secure/path/identity.txt
csm audit verify
csm audit show --limit 1
```

核对备份清单精确覆盖两个任务的完整内容与后代映射，记录清单哈希；`audit show` 返回的首个事件是当前链尾，其 `event_sha256` 作为本次审计链哈希。随后在 GUI **只选择派生任务**生成归档计划、复核确认并归档；不得归档来源任务。归档及最终复读后再次执行 `audit verify` 和 `audit show --limit 1`，验收报告应记录最终链尾哈希。最后逐 ID 复读：

```bash
csm threads show SOURCE_TASK_ID --include-content
csm threads show DERIVED_TASK_ID --include-content
csm audit verify
csm audit show --limit 1
```

预期：来源任务仍未归档且内容指纹不变；派生任务已归档；审计链可验证；备份证据仍与两个任务的备份指纹匹配。

## 6. 生成脱敏验收报告

报告只接受固定阶段名、散列后的任务标识和 SHA-256，不接受自由文本、对话内容或路径：

```bash
csm acceptance report acceptance-macos-v1.json \
  --schema-report csm-schema-audit-v1.json \
  --scope macos_real_account_manual \
  --thread-id SOURCE_TASK_ID \
  --thread-id DERIVED_TASK_ID \
  --plan-sha256 PLAN_SHA256 \
  --backup-manifest-sha256 MANIFEST_SHA256 \
  --audit-sha256 AUDIT_SHA256 \
  --stage doctor=passed \
  --stage read_inventory=passed \
  --stage gui_trim_plan_saved=passed \
  --stage derived_thread_created=passed \
  --stage source_unchanged=passed \
  --stage derived_projection_verified=passed \
  --stage backup_created=passed \
  --stage backup_verified=passed \
  --stage audit_verified=passed \
  --stage derived_archived=passed \
  --stage reread_verified=passed \
  --stage cocoa_window_input=passed
```

验收报告固定包含 `production_ready: false`。Developer ID、公证、staple、Windows Authenticode、SmartScreen 信誉和干净机生产验收仍是独立发布门禁。
