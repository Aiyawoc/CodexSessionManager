"""Small runtime translation layer for the standalone review GUI.

The Designer file contains the Simplified Chinese defaults so the window is
usable even before the controller is connected.  Runtime switching is kept in
this module instead of scattering language conditionals through Qt code.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from codex_session_manager.config import private_atomic_write
from codex_session_manager.models import ItemKind, ThreadStatus, TrimAction


class GuiLanguage(StrEnum):
    ZH_CN = "zh_CN"
    EN_US = "en_US"


DEFAULT_LANGUAGE = GuiLanguage.ZH_CN


_TEXT: dict[GuiLanguage, dict[str, str]] = {
    GuiLanguage.ZH_CN: {
        "window_title": "CodexSessionManager · 上下文裁剪",
        "subtitle": "安全地审查、精简和派生 Codex 上下文",
        "readonly_badge": "原任务只读保护",
        "language_tooltip": "界面语言",
        "language_save_failed": "无法保存界面语言设置：{error}",
        "precompact_window": "压缩前检查上下文",
        "precompact_title": "Codex 即将压缩当前上下文",
        "precompact_message": "可先审查并保存方案，稍后创建派生精简任务；关闭或超时会继续 Codex 原生压缩。",
        "precompact_remaining": "剩余 %v 秒",
        "precompact_review": "审查上下文…",
        "precompact_continue": "继续原生压缩",
        "precompact_continue_accessible": "继续 Codex 原生压缩",
        "project_tasks": "项目与任务",
        "cleanup_window_title": "CodexSessionManager · 对话清理审查",
        "cleanup_subtitle": "复核 LLM 初筛列表，最终选择始终由用户确认",
        "cleanup_badge": "建议不等于归档授权",
        "cleanup_candidates": "建议清理的对话",
        "cleanup_timeline": "对话时间线",
        "cleanup_content": "对话内容",
        "cleanup_suggestion": "清理建议",
        "cleanup_waiting": "等待选择左侧候选对话进行最终复核",
        "cleanup_search_placeholder": "筛选建议对话、项目或对话 ID",
        "cleanup_candidate": "候选对话",
        "cleanup_candidate_count": "已灌入 {count} 个候选；{missing} 个目标当前不可见",
        "cleanup_suggestion_tooltip": "建议置信度 {confidence}%\n{reason}",
        "cleanup_confidence": "建议置信度：{confidence}% · 仍需人工确认",
        "cleanup_scope_tooltip": "影响范围：派生后代 {descendants} 个；总大小 {size}\n当前有效备份：{verified}/{total}；风险：{risk}",
        "cleanup_risk_ready": "可进入备份与最终复核",
        "cleanup_risk_blocked": "当前状态阻断",
        "cleanup_descendant": "↳ {title}",
        "cleanup_missing_descendant": "↳ 缺失后代：{thread_id}",
        "cleanup_missing_descendant_tooltip": "后代闭包不完整；在重新盘点并解决前不能归档。",
        "cleanup_descendant_tooltip": "大小：{size}\n备份状态：{backup}",
        "cleanup_backup_verified": "已验证且文件仍有效",
        "cleanup_backup_missing": "缺少当前指纹的有效备份",
        "cleanup_backup_archive": "备份并归档…",
        "cleanup_backup_archive_selected": "备份并归档所选候选（{count}）…",
        "cleanup_backup_archive_confirm_title": "确认备份并归档",
        "cleanup_backup_archive_confirm": "将对 {selected} 个最终选择的根对话及其全部派生后代创建 age 加密备份，并立即完整解密复验。\n输出文件：{filename}\n\n备份成功后程序会重新读取状态、建议指纹和后代闭包，生成新的最终计划并执行归档。任一步失败都不会继续归档。是否继续？",
        "cleanup_backup_archive_busy": "正在创建并复验备份、重建最终计划并执行归档…",
        "cleanup_backup_archive_invalid": "备份并归档操作返回类型异常。",
        "cleanup_selection_unsafe": "所选候选的当前状态、保护标记或后代闭包不再满足归档安全条件；请刷新后重新选择。",
        "cleanup_backup_archive_done_title": "备份并归档完成",
        "cleanup_backup_archive_done": "已验证备份覆盖 {covered} 个对话，并归档 {roots} 个根对话。\n清单 SHA-256：{manifest_sha256}\n计划 ID：{plan_id}",
        "memory_window_title": "CodexSessionManager · 记忆管理",
        "memory_subtitle": "以与对话审查一致的布局复核已登记本地记忆文件",
        "memory_badge": "当前记忆来源只读",
        "memory_sources": "记忆来源",
        "memory_segments": "记忆分段",
        "memory_content": "记忆原文",
        "memory_action": "记忆动作",
        "memory_keep": "保留",
        "memory_delete": "删除",
        "memory_replace": "替换",
        "memory_protect": "保护",
        "memory_replacement": "替换内容",
        "memory_readonly_reason": "记忆文件写入尚未启用；后续计划必须先展示 diff、创建版本备份并原子写入。",
        "memory_waiting": "通过左侧第二个按钮进入记忆管理；仅显示用户明确登记的来源",
        "memory_search_placeholder": "筛选已登记的记忆文件路径",
        "memory_source": "记忆文件",
        "memory_status": "状态",
        "memory_readonly": "只读",
        "memory_source_count": "共 {count} 个已登记记忆来源",
        "memory_source_preview": "记忆来源：{path}\n\n当前里程碑只完成统一界面与请求灌入，不会读取或改写该文件。",
        "memory_source_selected": "已选择记忆来源：{path}",
        "external_suggestions_loaded": "已灌入 {applied} 条 LLM 建议；{ignored} 条因硬保护被本地规则否决",
        "collapse_tasks": "收起项目与任务面板",
        "collapse_button": "收起",
        "task_search_placeholder": "搜索项目、对话名称，或输入完整对话 ID",
        "task_search_accessible": "搜索 Codex 对话或输入对话 ID",
        "load_id": "加载 ID",
        "not_loaded": "尚未加载任务",
        "loaded_context": "{title} · {status} · {turns} turns",
        "task_list_accessible": "Codex 项目和任务列表",
        "task_name": "任务名称",
        "age": "距今",
        "task_list_not_loaded": "尚未加载任务列表",
        "task_list_loading": "正在通过 App Server 加载任务列表…",
        "task_list_invalid": "任务列表返回类型异常。",
        "task_list_count_search": "共 {count} 个对话 · 可按名称或对话 ID 搜索",
        "task_list_failed_input": "任务列表加载失败；仍可输入完整对话 ID。",
        "task_list_failed": "任务列表加载失败：{error}",
        "refresh": "刷新",
        "backup": "备份并复验…",
        "archive": "归档",
        "delete": "删除…",
        "rename": "更名…",
        "copy_id": "复制对话 ID",
        "backup_selected": "备份并复验所选对话（{count}）…",
        "archive_selected": "归档所选对话（{count}）…",
        "delete_selected": "永久删除所选对话（{count}）…",
        "clipboard_unavailable": "系统剪贴板当前不可用。",
        "id_copied": "已复制对话 ID。",
        "task_stale": "所选对话已不在当前列表中，请刷新后重试。",
        "rename_title": "对话更名",
        "rename_prompt": "新名称：",
        "rename_empty": "对话名称不能为空。",
        "rename_busy": "正在复核并更名对话…",
        "rename_invalid": "更名操作返回类型异常。",
        "rename_done_title": "对话已更名",
        "rename_done": "已完成 {count} 个根对话。\n计划 ID：{plan_id}",
        "select_task": "请先选择至少一个对话。",
        "backup_destination_title": "保存加密备份",
        "backup_recipient_title": "age recipient",
        "backup_recipient_prompt": "输入用于加密的 age recipient（公钥）：",
        "backup_recipient_empty": "age recipient 不能为空。",
        "backup_identity_title": "选择创建后复验所用的 age identity",
        "backup_confirm_title": "确认创建并完整复验备份",
        "backup_confirm": "将备份 {selected} 个所选根对话及其全部派生后代。\n输出文件：{filename}\n\n创建后会立即完整解密并校验所有成员，成功证据写入 CSM 审计链；不会归档任何对话。是否继续？",
        "backup_busy": "正在展开后代、创建 age 加密备份并完整复验…",
        "backup_invalid": "备份操作返回类型异常。",
        "backup_done_title": "加密备份已完整复验",
        "backup_done": "已覆盖 {count} 个对话。\n清单 SHA-256：{manifest_sha256}\n\n现在可以选择需要归档的对话并生成归档计划。",
        "archive_plan_busy": "正在展开派生后代并生成归档计划…",
        "archive_plan_invalid": "归档计划返回类型异常。",
        "archive_confirm_title": "确认归档计划",
        "archive_confirm": "计划 ID：{plan_id}\n根对话：{roots}；包含派生后代共 {affected} 个对话。\n\n应用时会再次复核状态、后代闭包、协议能力和已验证加密备份。是否应用？",
        "archive_saved": "归档计划已保存但未执行：{plan_id}",
        "archive_apply_busy": "正在复核并应用归档计划…",
        "archive_invalid": "归档操作返回类型异常。",
        "archive_done_title": "归档完成",
        "archive_done": "已归档 {count} 个根对话。\n计划 ID：{plan_id}",
        "purge_prepare_title": "准备永久删除",
        "purge_prepare": "永久删除 {count} 个所选对话属于不可恢复操作。仅已归档至少 14 天、具有 CSM 可信归档记录和当前已验证加密备份的对话可以进入计划。\n\n现在只生成并复核删除计划，是否继续？",
        "purge_plan_busy": "正在复核永久删除资格并生成计划…",
        "purge_plan_invalid": "永久删除计划返回类型异常。",
        "purge_confirm_title": "确认永久删除计划",
        "purge_confirm": "根对话 {roots} 个，包含派生后代共 {affected} 个对话。\n请输入完整计划 ID：\n{plan_id}",
        "purge_saved": "删除计划已保存但未执行：{plan_id}",
        "purge_final_title": "最终确认",
        "purge_final_prompt": "请输入：PERMANENTLY DELETE CODEX TASKS",
        "purge_mismatch": "计划 ID 或永久删除确认短语不匹配；计划未执行。",
        "purge_apply_busy": "正在最终复核并永久删除…",
        "purge_invalid": "永久删除操作返回类型异常。",
        "purge_done_title": "永久删除完成",
        "purge_done": "已删除 {count} 个根对话。\n计划 ID：{plan_id}",
        "task_operation_active": "已有对话管理操作正在执行，请等待其完成。",
        "task_operation_not_run": "对话管理操作未执行。",
        "task_operation_failed": "对话管理操作失败：{error}",
        "task_operation_no_result": "对话管理操作没有返回结果。",
        "timeline": "时间线",
        "timeline_summary": "隐藏 {hidden} · 输入 {input} · 输出 {output}",
        "timeline_usage_tooltip": "Token 数来自规范化可见内容的本地估算；App Server 历史 thread/read 不返回逐 turn 用量。",
        "timeline_order_tooltip": "Turn 1–N 按 App Server 返回顺序编号；正常历史记录通常就是时间先后顺序。",
        "content": "上下文",
        "show_tags": "显示标签",
        "hide_tags": "隐藏标签",
        "tags_tooltip": "显示或隐藏 <...> 协议标签；默认隐藏",
        "markdown_preview": "Markdown 预览",
        "markdown_exit": "退出 Markdown",
        "markdown_tooltip": "切换 Markdown 渲染预览；关闭后可编辑非保护内容",
        "content_accessible": "所选对话内容，可编辑非保护内容",
        "trim_action": "裁剪动作",
        "risk_waiting": "风险：等待选择",
        "reason": "建议理由",
        "summary": "摘要内容",
        "summary_placeholder": "选择“摘要”后编辑将注入派生任务的摘要",
        "ai_consent": "允许内容 AI 给出建议",
        "ai_consent_tooltip": "默认关闭；启用前应确认内容提供方和数据边界。",
        "suggest": "重新生成本地建议",
        "estimate_empty": "预计上下文：—",
        "saving_progress": "预计节省 %p%",
        "sensitive_scan": "敏感筛查",
        "sensitive_tooltip": "使用本地规则筛查疑似敏感内容，并在上下文中以红底白字标记匹配内容",
        "sensitive_finding": "疑似敏感内容（本地规则）：{summary}",
        "sensitive_off": "共 {count} 个对话 · 敏感内容筛查已关闭",
        "sensitive_need_list": "请先加载对话列表，再启动敏感内容筛查。",
        "sensitive_progress_title": "敏感内容筛查",
        "sensitive_progress_cancel": "取消筛查",
        "sensitive_progress": "正在本地筛查疑似敏感内容… {current}/{total}（内容不会上传）",
        "sensitive_invalid_result": "后台筛查返回了无效结果",
        "sensitive_failed": "敏感内容筛查失败：{error}",
        "sensitive_read_failed": "；{count} 个读取失败",
        "sensitive_summary": "发现 {count} 个疑似敏感对话（本地规则；未上传内容）{suffix}",
        "save_plan": "保存方案",
        "save_plan_tooltip": "保存不可变裁剪方案；不会修改或派生对话",
        "apply_plan": "派生精简任务",
        "close": "关闭",
        "cancel_native_compact": "取消并继续原生压缩",
        "hook_review": "Hook 审查模式：只保存方案",
        "content_empty": "（无模型可见文本）",
        "preview_truncated": "… [预览已按有界缓存截断；方案仍基于完整 App Server 数据] …",
        "inherited_action": "继承 turn 动作",
        "risk_protected": "风险：受保护 · {reasons}",
        "risk_review": "风险：请审查建议后再保存",
        "unknown_project": "未指定项目",
        "unnamed_task": "未命名任务",
        "today": "今天",
        "days_ago": "{days}天前",
        "unknown": "未知",
        "query_filtered": "已按输入内容筛选；若输入的是列表外完整对话 ID，请点击“加载 ID”。",
        "enter_conversation_id": "请输入完整的 Codex 对话 ID。",
        "thread_loading": "正在通过 App Server 加载任务…",
        "load_invalid": "加载结果类型异常。",
        "read_only_server": "当前 App Server 能力只能读取和规划：{reason}",
        "unknown_protocol": "未知协议",
        "load_failed": "加载失败：{error}",
        "task_count": "任务数：{count}",
        "project_paths": "项目路径：{paths}",
        "git_remotes": "Git：{remotes}",
        "no_project_mapping": "未指定项目路径或 Git remote",
        "last_activity": "最后活动：{timestamp}\n对话 ID：{thread_id}",
        "no_activity": "没有可用的创建或最后活动时间",
        "task_tooltip_project": "项目：{cwd}",
        "task_tooltip_git": "Git：{remote}",
        "conversation_id": "对话 ID：{thread_id}",
        "status_line": "状态：{status}",
        "status_archived": "{status} · 已归档",
        "timeline_header_name": "时间线",
        "timeline_header_type": "类型/状态",
        "timeline_header_token": "Token",
        "timeline_header_action": "动作",
        "turn": "Turn {number}",
        "action_inherit": "继承",
        "estimate": "预计上下文：{before} → {after} tokens（节省约 {saved}）",
        "plan_save_busy": "正在安全保存不可变方案…",
        "plan_saved": "方案已安全保存：{plan_id}",
        "plan_save_failed": "无法保存方案：{error}",
        "plan_save_no_result": "方案保存 Worker 没有返回结果。",
        "plan_validate_failed": "方案校验失败：{error}",
        "apply_busy": "正在创建派生精简任务…",
        "derived_title": "派生任务已创建",
        "derived_message": "新对话 ID：{thread_id}\n原任务未修改，也没有自动启动模型 turn。",
        "apply_failed": "创建失败：{error}",
        "hard_protected_action": "该内容包含硬保护项，只能保留或保护。",
        "edited_summary_reason": "用户编辑的替代内容",
        "manual_reason": "用户手动调整",
        "protected_edit_tooltip": "硬保护内容只读，不能在派生方案中改写。",
        "summary_fingerprint": "保留原始来源指纹。",
        "ai_not_configured": "尚未配置内容 AI 提供方；未发送任何内容，已使用本地规则。",
        "write_in_progress": "写操作正在复核；完成前不能关闭窗口。",
    },
    GuiLanguage.EN_US: {
        "window_title": "CodexSessionManager · Context Trim",
        "subtitle": "Safely review, reduce, and derive Codex context",
        "readonly_badge": "Source task is read-only",
        "language_tooltip": "Interface language",
        "language_save_failed": "Could not save the interface language: {error}",
        "precompact_window": "Review context before compaction",
        "precompact_title": "Codex is about to compact this context",
        "precompact_message": "Review and save a plan now, then create a derived trimmed task later. Closing or timing out continues native Codex compaction.",
        "precompact_remaining": "%v seconds remaining",
        "precompact_review": "Review context…",
        "precompact_continue": "Continue native compaction",
        "precompact_continue_accessible": "Continue native Codex compaction",
        "project_tasks": "Projects & Tasks",
        "cleanup_window_title": "CodexSessionManager · Conversation Cleanup Review",
        "cleanup_subtitle": "Review the LLM shortlist; the user always makes the final selection",
        "cleanup_badge": "Suggestions are not archive authority",
        "cleanup_candidates": "Suggested cleanup conversations",
        "cleanup_timeline": "Conversation timeline",
        "cleanup_content": "Conversation content",
        "cleanup_suggestion": "Cleanup suggestion",
        "cleanup_waiting": "Select a candidate on the left for final review",
        "cleanup_search_placeholder": "Filter suggested conversations, projects, or IDs",
        "cleanup_candidate": "Candidate conversation",
        "cleanup_candidate_count": "Loaded {count} candidates; {missing} targets are currently unavailable",
        "cleanup_suggestion_tooltip": "Suggested confidence {confidence}%\n{reason}",
        "cleanup_confidence": "Suggested confidence: {confidence}% · Human confirmation required",
        "cleanup_scope_tooltip": "Scope: {descendants} derived descendants; total size {size}\nCurrent verified backups: {verified}/{total}; risk: {risk}",
        "cleanup_risk_ready": "Ready for backup and final checks",
        "cleanup_risk_blocked": "Blocked by current state",
        "cleanup_descendant": "↳ {title}",
        "cleanup_missing_descendant": "↳ Missing descendant: {thread_id}",
        "cleanup_missing_descendant_tooltip": "The descendant closure is incomplete. Archiving is blocked until inventory is repaired.",
        "cleanup_descendant_tooltip": "Size: {size}\nBackup status: {backup}",
        "cleanup_backup_verified": "Verified and the ciphertext is still current",
        "cleanup_backup_missing": "No current backup for this fingerprint",
        "cleanup_backup_archive": "Backup & archive…",
        "cleanup_backup_archive_selected": "Backup & archive selected candidates ({count})…",
        "cleanup_backup_archive_confirm_title": "Confirm backup and archive",
        "cleanup_backup_archive_confirm": "Create an age-encrypted backup for {selected} finally selected roots and all derived descendants, then fully decrypt and verify it.\nOutput file: {filename}\n\nAfter verification, current state, suggestion fingerprints, and descendant closure are read again, a new final plan is created, and archiving is applied. Any failure stops before the archive step. Continue?",
        "cleanup_backup_archive_busy": "Creating and verifying the backup, rebuilding the final plan, and archiving…",
        "cleanup_backup_archive_invalid": "The backup-and-archive operation returned an unexpected type.",
        "cleanup_selection_unsafe": "The selected candidates no longer satisfy archive safety gates for state, protection, or descendant closure. Refresh and select again.",
        "cleanup_backup_archive_done_title": "Backup and archive complete",
        "cleanup_backup_archive_done": "Verified a backup covering {covered} conversations and archived {roots} roots.\nManifest SHA-256: {manifest_sha256}\nPlan ID: {plan_id}",
        "memory_window_title": "CodexSessionManager · Memory Management",
        "memory_subtitle": "Review registered local memory files in the same layout as conversations",
        "memory_badge": "Memory sources are currently read-only",
        "memory_sources": "Memory sources",
        "memory_segments": "Memory segments",
        "memory_content": "Memory source",
        "memory_action": "Memory action",
        "memory_keep": "Keep",
        "memory_delete": "Delete",
        "memory_replace": "Replace",
        "memory_protect": "Protect",
        "memory_replacement": "Replacement text",
        "memory_readonly_reason": "Memory writes are not enabled yet. A later plan must show a diff, create a version backup, and write atomically.",
        "memory_waiting": "Use the second left-rail button to review explicitly registered memory sources",
        "memory_search_placeholder": "Filter registered memory file paths",
        "memory_source": "Memory file",
        "memory_status": "Status",
        "memory_readonly": "Read-only",
        "memory_source_count": "{count} registered memory sources",
        "memory_source_preview": "Memory source: {path}\n\nThis milestone only unifies the interface and request injection; the file will not be read or modified.",
        "memory_source_selected": "Selected memory source: {path}",
        "external_suggestions_loaded": "Loaded {applied} LLM suggestions; local hard protection rejected {ignored}",
        "collapse_tasks": "Collapse Projects & Tasks",
        "collapse_button": "Collapse",
        "task_search_placeholder": "Search project or conversation, or enter a full conversation ID",
        "task_search_accessible": "Search Codex conversations or enter a conversation ID",
        "load_id": "Load ID",
        "not_loaded": "No task loaded",
        "loaded_context": "{title} · {status} · {turns} turns",
        "task_list_accessible": "Codex project and task list",
        "task_name": "Task",
        "age": "Age",
        "task_list_not_loaded": "Task list not loaded",
        "task_list_loading": "Loading tasks through App Server…",
        "task_list_invalid": "The task list returned an unexpected type.",
        "task_list_count_search": "{count} conversations · Search by name or conversation ID",
        "task_list_failed_input": "Could not load the task list; a full conversation ID can still be entered.",
        "task_list_failed": "Could not load the task list: {error}",
        "refresh": "Refresh",
        "backup": "Backup & verify…",
        "archive": "Archive",
        "delete": "Delete…",
        "rename": "Rename…",
        "copy_id": "Copy conversation ID",
        "backup_selected": "Backup & verify selected ({count})…",
        "archive_selected": "Archive selected ({count})…",
        "delete_selected": "Permanently delete selected ({count})…",
        "clipboard_unavailable": "The system clipboard is unavailable.",
        "id_copied": "Conversation ID copied.",
        "task_stale": "The selected conversation is no longer in the list. Refresh and try again.",
        "rename_title": "Rename conversation",
        "rename_prompt": "New name:",
        "rename_empty": "Conversation name cannot be empty.",
        "rename_busy": "Reviewing and renaming the conversation…",
        "rename_invalid": "The rename operation returned an unexpected type.",
        "rename_done_title": "Conversation renamed",
        "rename_done": "Completed {count} root conversations.\nPlan ID: {plan_id}",
        "select_task": "Select at least one conversation first.",
        "backup_destination_title": "Save encrypted backup",
        "backup_recipient_title": "age recipient",
        "backup_recipient_prompt": "Enter the age recipient (public key) used for encryption:",
        "backup_recipient_empty": "The age recipient cannot be empty.",
        "backup_identity_title": "Select the age identity used for post-create verification",
        "backup_confirm_title": "Confirm backup creation and full verification",
        "backup_confirm": "Back up {selected} selected root conversations and every derived descendant.\nOutput file: {filename}\n\nAfter creation, every member is fully decrypted and verified and the evidence is written to the CSM audit chain. No conversation will be archived. Continue?",
        "backup_busy": "Expanding descendants, creating the age-encrypted backup, and fully verifying it…",
        "backup_invalid": "The backup operation returned an unexpected type.",
        "backup_done_title": "Encrypted backup fully verified",
        "backup_done": "Covered {count} conversations.\nManifest SHA-256: {manifest_sha256}\n\nYou can now select conversations and prepare an archive plan.",
        "archive_plan_busy": "Expanding derived descendants and preparing an archive plan…",
        "archive_plan_invalid": "The archive plan returned an unexpected type.",
        "archive_confirm_title": "Confirm archive plan",
        "archive_confirm": "Plan ID: {plan_id}\nRoot conversations: {roots}; {affected} conversations including derived descendants.\n\nApplication rechecks state, descendant closure, protocol capabilities, and verified encrypted backup. Apply it?",
        "archive_saved": "Archive plan saved but not applied: {plan_id}",
        "archive_apply_busy": "Rechecking and applying the archive plan…",
        "archive_invalid": "The archive operation returned an unexpected type.",
        "archive_done_title": "Archive complete",
        "archive_done": "Archived {count} root conversations.\nPlan ID: {plan_id}",
        "purge_prepare_title": "Prepare permanent deletion",
        "purge_prepare": "Permanently deleting {count} selected conversations is irreversible. Only conversations archived for at least 14 days, with trusted CSM archive records and a currently verified encrypted backup, can enter the plan.\n\nPrepare and review the deletion plan now?",
        "purge_plan_busy": "Checking permanent-deletion eligibility and preparing a plan…",
        "purge_plan_invalid": "The permanent-deletion plan returned an unexpected type.",
        "purge_confirm_title": "Confirm permanent-deletion plan",
        "purge_confirm": "{roots} root conversations; {affected} conversations including derived descendants.\nEnter the complete plan ID:\n{plan_id}",
        "purge_saved": "Deletion plan saved but not applied: {plan_id}",
        "purge_final_title": "Final confirmation",
        "purge_final_prompt": "Enter: PERMANENTLY DELETE CODEX TASKS",
        "purge_mismatch": "The plan ID or permanent-deletion phrase did not match; nothing was deleted.",
        "purge_apply_busy": "Performing final checks and permanent deletion…",
        "purge_invalid": "The permanent-deletion operation returned an unexpected type.",
        "purge_done_title": "Permanent deletion complete",
        "purge_done": "Deleted {count} root conversations.\nPlan ID: {plan_id}",
        "task_operation_active": "Another conversation-management operation is running. Wait for it to finish.",
        "task_operation_not_run": "The conversation-management operation was not run.",
        "task_operation_failed": "Conversation-management operation failed: {error}",
        "task_operation_no_result": "The conversation-management operation returned no result.",
        "timeline": "Timeline",
        "timeline_summary": "Hidden {hidden} · In {input} · Out {output}",
        "timeline_usage_tooltip": "Token counts are local estimates from normalized visible content; historical thread/read responses do not include per-turn usage.",
        "timeline_order_tooltip": "Turn 1–N follows App Server response order, normally chronological for stored history.",
        "content": "Context",
        "show_tags": "Show tags",
        "hide_tags": "Hide tags",
        "tags_tooltip": "Show or hide <...> protocol tags; hidden by default",
        "markdown_preview": "Markdown preview",
        "markdown_exit": "Exit Markdown",
        "markdown_tooltip": "Toggle rendered Markdown; turn it off to edit unprotected content",
        "content_accessible": "Selected conversation content; unprotected content is editable",
        "trim_action": "Trim action",
        "risk_waiting": "Risk: waiting for selection",
        "reason": "Suggestion reason",
        "summary": "Summary",
        "summary_placeholder": "Select Summary, then edit the text injected into the derived task",
        "ai_consent": "Allow content AI suggestions",
        "ai_consent_tooltip": "Off by default; confirm provider and data boundaries before enabling.",
        "suggest": "Regenerate local suggestions",
        "estimate_empty": "Estimated context: —",
        "saving_progress": "Estimated saving %p%",
        "sensitive_scan": "Sensitive scan",
        "sensitive_tooltip": "Scan locally for likely sensitive content and highlight matches in Context",
        "sensitive_finding": "Likely sensitive content (local rules): {summary}",
        "sensitive_off": "{count} conversations · Sensitive scan off",
        "sensitive_need_list": "Load the conversation list before starting a sensitive scan.",
        "sensitive_progress_title": "Sensitive content scan",
        "sensitive_progress_cancel": "Cancel scan",
        "sensitive_progress": "Scanning locally for likely sensitive content… {current}/{total} (content is not uploaded)",
        "sensitive_invalid_result": "The background scan returned an invalid result",
        "sensitive_failed": "Sensitive scan failed: {error}",
        "sensitive_read_failed": "; {count} reads failed",
        "sensitive_summary": "Found {count} conversations with likely sensitive content (local rules; nothing uploaded){suffix}",
        "save_plan": "Save plan",
        "save_plan_tooltip": "Save an immutable trim plan without changing or deriving a conversation",
        "apply_plan": "Create trimmed task",
        "close": "Close",
        "cancel_native_compact": "Cancel and continue native compaction",
        "hook_review": "Hook review mode: save plan only",
        "content_empty": "(No model-visible text)",
        "preview_truncated": "… [Preview truncated to a bounded cache; the plan still uses full App Server data] …",
        "inherited_action": "Inherit turn action",
        "risk_protected": "Risk: protected · {reasons}",
        "risk_review": "Risk: review the suggestion before saving",
        "unknown_project": "Unassigned project",
        "unnamed_task": "Untitled task",
        "today": "Today",
        "days_ago": "{days}d ago",
        "unknown": "Unknown",
        "query_filtered": "The list is filtered. To load a full conversation ID outside the list, click Load ID.",
        "enter_conversation_id": "Enter a complete Codex conversation ID.",
        "thread_loading": "Loading the task through App Server…",
        "load_invalid": "The load operation returned an unexpected type.",
        "read_only_server": "Current App Server capabilities allow only reading and planning: {reason}",
        "unknown_protocol": "unknown protocol",
        "load_failed": "Load failed: {error}",
        "task_count": "Tasks: {count}",
        "project_paths": "Project paths: {paths}",
        "git_remotes": "Git: {remotes}",
        "no_project_mapping": "No project path or Git remote",
        "last_activity": "Last activity: {timestamp}\nConversation ID: {thread_id}",
        "no_activity": "No creation or last-activity time is available",
        "task_tooltip_project": "Project: {cwd}",
        "task_tooltip_git": "Git: {remote}",
        "conversation_id": "Conversation ID: {thread_id}",
        "status_line": "Status: {status}",
        "status_archived": "{status} · Archived",
        "timeline_header_name": "Timeline",
        "timeline_header_type": "Type/status",
        "timeline_header_token": "Token",
        "timeline_header_action": "Action",
        "turn": "Turn {number}",
        "action_inherit": "Inherit",
        "estimate": "Estimated context: {before} → {after} tokens (save about {saved})",
        "plan_save_busy": "Safely saving the immutable plan…",
        "plan_saved": "Plan saved safely: {plan_id}",
        "plan_save_failed": "Could not save plan: {error}",
        "plan_save_no_result": "The plan-save worker returned no result.",
        "plan_validate_failed": "Plan validation failed: {error}",
        "apply_busy": "Creating a derived trimmed task…",
        "derived_title": "Derived task created",
        "derived_message": "New conversation ID: {thread_id}\nThe source task was unchanged and no model turn was started.",
        "apply_failed": "Creation failed: {error}",
        "hard_protected_action": "This content has hard-protected items and can only be kept or protected.",
        "edited_summary_reason": "User-edited replacement content",
        "manual_reason": "Manually adjusted by user",
        "protected_edit_tooltip": "Hard-protected content is read-only and cannot be rewritten in a derived plan.",
        "summary_fingerprint": "Preserve the source fingerprint.",
        "ai_not_configured": "No content-AI provider is configured. No content was sent; local rules were used.",
        "write_in_progress": "A write operation is being verified; the window cannot close yet.",
    },
}


_ACTION_LABELS = {
    GuiLanguage.ZH_CN: {
        TrimAction.KEEP: "保留",
        TrimAction.EXCLUDE: "排除",
        TrimAction.SUMMARY: "摘要",
        TrimAction.PROTECT: "保护",
    },
    GuiLanguage.EN_US: {
        TrimAction.KEEP: "Keep",
        TrimAction.EXCLUDE: "Exclude",
        TrimAction.SUMMARY: "Summary",
        TrimAction.PROTECT: "Protect",
    },
}


_STATUS_LABELS = {
    GuiLanguage.ZH_CN: {
        ThreadStatus.NOT_LOADED: "未加载",
        ThreadStatus.IDLE: "空闲",
        ThreadStatus.ACTIVE: "进行中",
        ThreadStatus.SYSTEM_ERROR: "系统错误",
        ThreadStatus.UNKNOWN: "未知",
    },
    GuiLanguage.EN_US: {
        ThreadStatus.NOT_LOADED: "Not loaded",
        ThreadStatus.IDLE: "Idle",
        ThreadStatus.ACTIVE: "Active",
        ThreadStatus.SYSTEM_ERROR: "System error",
        ThreadStatus.UNKNOWN: "Unknown",
    },
}


_ITEM_KIND_LABELS = {
    GuiLanguage.ZH_CN: {
        ItemKind.USER_MESSAGE: "用户消息",
        ItemKind.ASSISTANT_MESSAGE: "助手消息",
        ItemKind.SYSTEM_MESSAGE: "系统指令",
        ItemKind.DEVELOPER_MESSAGE: "开发者指令",
        ItemKind.REASONING: "推理",
        ItemKind.TOOL_CALL: "工具调用",
        ItemKind.TOOL_RESULT: "工具结果",
        ItemKind.FILE_CHANGE: "文件变更",
        ItemKind.VERIFICATION: "验证",
        ItemKind.APPROVAL: "审批",
        ItemKind.ERROR: "错误",
        ItemKind.SUMMARY: "摘要",
        ItemKind.UNKNOWN: "未知",
    },
    GuiLanguage.EN_US: {kind: kind.value.replace("_", " ") for kind in ItemKind},
}


_TURN_STATUS_LABELS: dict[GuiLanguage, dict[str, str]] = {
    GuiLanguage.ZH_CN: {
        "completed": "已完成",
        "inProgress": "进行中",
        "interrupted": "已中断",
        "failed": "失败",
    },
    GuiLanguage.EN_US: {
        "completed": "Completed",
        "inProgress": "In progress",
        "interrupted": "Interrupted",
        "failed": "Failed",
    },
}

_SUGGESTION_REASONS = {
    "硬保护项所在 turn": "Turn contains a hard-protected item",
    "保留最近 turn": "Keep a recent turn",
    "可能包含未解决错误，需人工确认": "May contain an unresolved error; review required",
    "后续 turn 已包含完全相同内容": "A later turn contains identical content",
    "低信息确认语": "Low-information acknowledgement",
    "长输出或工具链建议整体摘要": "Summarize a long output or tool chain as one unit",
    "没有足够证据安全裁剪": "Insufficient evidence for safe trimming",
}

_PROTECTED_REASONS = {
    "current user request": "当前用户请求",
    "turn is still in progress": "turn 仍在进行中",
    "unpaired tool item lacks a complete call/result group": "工具调用缺少完整的调用/结果配对",
    "possible unresolved error": "可能存在未解决错误",
    "User-edited replacement content": "用户编辑的替代内容",
    "Manually adjusted by user": "用户手动调整",
}

_SENSITIVE_CATEGORIES = {
    "私钥": "Private key",
    "云服务/API 密钥": "Cloud/API key",
    "JWT": "JWT",
    "口令/令牌赋值": "Password/token assignment",
    "电子邮箱": "Email address",
    "中国大陆手机号": "Mainland China phone number",
    "中国居民身份证号": "Chinese resident ID number",
    "支付卡号": "Payment card number",
}


def text(language: GuiLanguage, key: str, **values: Any) -> str:
    """Return one translated GUI string, falling back to Chinese then the key."""

    template = _TEXT.get(language, {}).get(key) or _TEXT[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**values)


def action_label(language: GuiLanguage, action: TrimAction) -> str:
    return _ACTION_LABELS[language][action]


def thread_status_label(language: GuiLanguage, status: ThreadStatus) -> str:
    return _STATUS_LABELS[language].get(status, status.value)


def turn_status_label(language: GuiLanguage, status: str) -> str:
    return _TURN_STATUS_LABELS[language].get(status, status)


def item_kind_label(language: GuiLanguage, kind: ItemKind) -> str:
    return _ITEM_KIND_LABELS[language].get(kind, kind.value)


def localized_reason(language: GuiLanguage, value: str) -> str:
    """Translate stable planner/protection reason text for display only."""

    if language is GuiLanguage.EN_US:
        return _SUGGESTION_REASONS.get(value, value)
    translated = _PROTECTED_REASONS.get(value)
    if translated is not None:
        return translated
    prefix = "hard-protected item kind: "
    if value.startswith(prefix):
        return "硬保护的内部事件类型：" + value.removeprefix(prefix)
    return value


def sensitive_category_label(language: GuiLanguage, value: str) -> str:
    if language is GuiLanguage.EN_US:
        return _SENSITIVE_CATEGORIES.get(value, value)
    return value


def compact_number(value: int) -> str:
    """Format non-negative counts with compact, deterministic k/m/b suffixes."""

    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    tiers = ((1_000_000_000, "b"), (1_000_000, "m"), (1_000, "k"))
    for divisor, suffix in tiers:
        if magnitude < divisor:
            continue
        scaled = magnitude / divisor
        rendered = f"{scaled:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{rendered}{suffix}"
    return str(value)


def missing_translation_keys(language: GuiLanguage) -> frozenset[str]:
    """Return keys missing from one locale relative to the Chinese source set."""

    return frozenset(_TEXT[DEFAULT_LANGUAGE]).difference(_TEXT[language])


def load_language(config_dir: Path) -> GuiLanguage:
    """Load the persisted GUI language, falling back safely to Chinese."""

    path = config_dir / "gui-preferences.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return GuiLanguage(str(payload.get("language")))
    except (OSError, ValueError, TypeError):
        pass
    return DEFAULT_LANGUAGE


def save_language(config_dir: Path, language: GuiLanguage) -> None:
    """Persist only non-sensitive GUI preferences using CSM's atomic writer."""

    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_atomic_write(
        config_dir / "gui-preferences.json",
        json.dumps({"language": language.value}, sort_keys=True).encode("utf-8") + b"\n",
    )
