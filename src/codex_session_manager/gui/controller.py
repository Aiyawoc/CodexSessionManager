"""Controller for the Designer-authored context-trimming window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from PySide6.QtCore import QItemSelection, QThreadPool, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHeaderView, QMainWindow, QMessageBox

from codex_session_manager.app_server import connect_and_probe
from codex_session_manager.audit import AuditStore
from codex_session_manager.config import AppPaths, get_paths
from codex_session_manager.gui.timeline_model import TurnTimelineModel
from codex_session_manager.gui.ui_main_window import Ui_MainWindow
from codex_session_manager.gui.worker import FunctionWorker
from codex_session_manager.inventory import InventoryService
from codex_session_manager.models import (
    CapabilityMatrix,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)
from codex_session_manager.plans import PlanStore
from codex_session_manager.trim import (
    LocalTrimSuggester,
    TrimError,
    TrimExecutor,
    validate_selections,
)

ACTION_BY_INDEX = {
    0: TrimAction.KEEP,
    1: TrimAction.EXCLUDE,
    2: TrimAction.SUMMARY,
    3: TrimAction.PROTECT,
}
INDEX_BY_ACTION = {value: key for key, value in ACTION_BY_INDEX.items()}
MAX_PREVIEW_CHARS = 200_000


@dataclass(frozen=True, slots=True)
class ReviewDocument:
    snapshot: ThreadSnapshot
    capabilities: CapabilityMatrix
    suggested_plan: TrimPlan


class TrimReviewWindow(QMainWindow):
    plan_saved = Signal(object)
    derived_created = Signal(str)
    window_closed = Signal()

    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        thread_id: str | None = None,
        trigger: Literal["manual", "auto", "hook"] = "manual",
        source_turn_id: str | None = None,
        hook_mode: bool = False,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)  # type: ignore[no-untyped-call]
        self.paths = paths or get_paths()
        self.paths.ensure()
        self.trigger = trigger
        self.source_turn_id = source_turn_id
        self.hook_mode = hook_mode
        self.thread_pool = QThreadPool.globalInstance()
        self.document: ReviewDocument | None = None
        self.timeline_model: TurnTimelineModel | None = None
        self.selections: dict[str, TrimSelection] = {}
        self.current_target: TurnSnapshot | ThreadItemSnapshot | None = None
        self.current_plan: TrimPlan | None = None
        self._updating_controls = False
        self._generation = 0
        self._closing = False
        self._write_in_progress = False
        self._connect_signals()
        self._configure_views()
        self.ui.errorLabel.hide()
        self.ui.mainSplitter.setSizes([330, 580, 300])
        if hook_mode:
            self.ui.applyButton.hide()
            self.ui.cancelButton.setText("取消并继续原生压缩")
            self.ui.sourceStatusLabel.setText("Hook 审查模式：只保存计划，不创建派生任务")
        if thread_id:
            self.ui.threadIdEdit.setText(thread_id)
            self.load_thread(thread_id)

    def _configure_views(self) -> None:
        """Apply stable column sizing and comfortable desktop reading metrics."""

        header = self.ui.timelineView.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for section in (1, 2, 3):
            header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
        self.ui.timelineView.setIndentation(16)
        self.ui.timelineView.setHeaderHidden(False)
        self.ui.contentBrowser.setLineWrapMode(self.ui.contentBrowser.LineWrapMode.WidgetWidth)
        self.ui.summaryEdit.setMinimumHeight(120)
        self.ui.reasonBrowser.setMinimumHeight(72)

    def _connect_signals(self) -> None:
        self.ui.loadButton.clicked.connect(self._load_from_edit)
        self.ui.threadIdEdit.returnPressed.connect(self._load_from_edit)
        self.ui.actionCombo.currentIndexChanged.connect(self._action_changed)
        self.ui.summaryEdit.textChanged.connect(self._summary_changed)
        self.ui.suggestButton.clicked.connect(self._regenerate_suggestions)
        self.ui.savePlanButton.clicked.connect(self._save_plan)
        self.ui.applyButton.clicked.connect(self._apply_plan)
        self.ui.cancelButton.clicked.connect(self.close)

    @Slot()
    def _load_from_edit(self) -> None:
        thread_id = self.ui.threadIdEdit.text().strip()
        if not thread_id:
            self._show_error("请输入 Codex 任务 ID。")
            return
        self.load_thread(thread_id)

    def load_thread(self, thread_id: str) -> None:
        self._generation += 1
        generation = self._generation
        self._set_busy(True, "正在通过 App Server 加载任务…")

        def load() -> ReviewDocument:
            client, capabilities = connect_and_probe(request_timeout=45)
            try:
                snapshot = InventoryService(client).read(thread_id, include_turns=True)
                suggested = LocalTrimSuggester().suggest(
                    snapshot,
                    capabilities=capabilities,
                    trigger=self.trigger,
                    source_turn_id=self.source_turn_id,
                )
                return ReviewDocument(snapshot, capabilities, suggested)
            finally:
                client.close()

        worker = FunctionWorker(load)
        worker.signals.result.connect(
            lambda value, current=generation: self._document_loaded(current, value)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._load_failed(current, message)
        )
        worker.signals.finished.connect(lambda current=generation: self._load_finished(current))
        self.thread_pool.start(worker)

    def _document_loaded(self, generation: int, value: object) -> None:
        if generation != self._generation or self._closing:
            return
        if not isinstance(value, ReviewDocument):
            self._show_error("加载结果类型异常。")
            return
        self.document = value
        self.selections = {
            selection.target_id: selection for selection in value.suggested_plan.selections
        }
        self.current_plan = value.suggested_plan
        self.timeline_model = TurnTimelineModel(value.snapshot, self.selections, self)
        self.ui.timelineView.setModel(self.timeline_model)
        self.ui.timelineView.expandToDepth(0)
        self.ui.timelineView.selectionModel().selectionChanged.connect(self._selection_changed)
        self.ui.sourceStatusLabel.setText(
            f"{value.snapshot.title or value.snapshot.id} · {value.snapshot.status.value} · {len(value.snapshot.turns)} turns"
        )
        self.ui.savePlanButton.setEnabled(True)
        self.ui.applyButton.setEnabled(
            not self.hook_mode and value.snapshot.status is not ThreadStatus.ACTIVE
        )
        self._update_estimate()
        if value.snapshot.turns:
            first = self.timeline_model.index(0, 0)
            self.ui.timelineView.setCurrentIndex(first)
        if not value.capabilities.write_enabled:
            self.ui.applyButton.setEnabled(False)
            self._show_error(
                "当前 App Server 能力只能读取和规划："
                + (value.capabilities.read_only_reason or "未知协议")
            )

    def _load_failed(self, generation: int, message: str) -> None:
        if generation != self._generation or self._closing:
            return
        self._show_error(f"加载失败：{message}")

    def _load_finished(self, generation: int) -> None:
        if generation == self._generation and not self._closing:
            self._set_busy(False)

    @Slot(QItemSelection, QItemSelection)
    def _selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        if self.timeline_model is None or not selected.indexes():
            return
        index = selected.indexes()[0]
        target = self.timeline_model.target_for(index)
        if target is None:
            return
        self.current_target = target
        self._show_target(target)

    def _show_target(self, target: TurnSnapshot | ThreadItemSnapshot) -> None:
        self._updating_controls = True
        try:
            if isinstance(target, TurnSnapshot):
                text = "\n\n".join(item.text for item in target.items if item.text)
                meta = f"Turn {target.id} · {target.status} · {len(target.items)} items"
                protected = tuple(
                    dict.fromkeys(
                        reason for item in target.items for reason in item.protected_reasons
                    )
                )
            else:
                text = target.text
                meta = f"Item {target.id} · {target.kind.value} · role={target.role or '—'} · depends={', '.join(target.depends_on) or '—'}"
                protected = target.protected_reasons
            self.ui.contentMetaLabel.setText(meta)
            if len(text) > MAX_PREVIEW_CHARS:
                half = MAX_PREVIEW_CHARS // 2
                text = (
                    text[:half]
                    + "\n\n… [预览已按有界缓存截断；计划仍基于完整 App Server 数据] …\n\n"
                    + text[-half:]
                )
            self.ui.contentBrowser.setPlainText(text or "（无模型可见文本）")
            selection = self.selections.get(target.id)
            action = selection.action if selection else TrimAction.KEEP
            self.ui.actionCombo.setCurrentIndex(INDEX_BY_ACTION[action])
            self.ui.summaryEdit.setPlainText(selection.summary or "" if selection else "")
            self.ui.summaryEdit.setEnabled(action is TrimAction.SUMMARY)
            self.ui.reasonBrowser.setPlainText(selection.reason if selection else "继承 turn 动作")
            if protected:
                self.ui.riskLabel.setText("风险：受保护 · " + "；".join(protected))
            else:
                self.ui.riskLabel.setText("风险：请审查建议后再保存")
        finally:
            self._updating_controls = False

    @Slot(int)
    def _action_changed(self, index: int) -> None:
        if self._updating_controls or self.current_target is None:
            return
        action = ACTION_BY_INDEX[index]
        protected = (
            tuple(reason for item in self.current_target.items for reason in item.protected_reasons)
            if isinstance(self.current_target, TurnSnapshot)
            else self.current_target.protected_reasons
        )
        if protected and action in {TrimAction.EXCLUDE, TrimAction.SUMMARY}:
            self._show_error("该内容包含硬保护项，只能保留或保护。")
            self._show_target(self.current_target)
            return
        existing = self.selections.get(self.current_target.id)
        summary = self.ui.summaryEdit.toPlainText().strip() or None
        if action is TrimAction.SUMMARY and not summary:
            summary = self._target_text(self.current_target)[:1200] or "保留原始来源指纹。"
        self.selections[self.current_target.id] = TrimSelection(
            target_id=self.current_target.id,
            target_level="turn" if isinstance(self.current_target, TurnSnapshot) else "item",
            action=action,
            summary=summary if action is TrimAction.SUMMARY else None,
            reason=existing.reason if existing else "用户手动调整",
            suggested=False,
            protected_reasons=tuple(dict.fromkeys(protected))
            if action is TrimAction.PROTECT
            else (),
        )
        self.ui.summaryEdit.setEnabled(action is TrimAction.SUMMARY)
        if action is TrimAction.SUMMARY:
            self._updating_controls = True
            self.ui.summaryEdit.setPlainText(summary or "")
            self._updating_controls = False
        if self.timeline_model:
            self.timeline_model.refresh_actions()
        self._update_estimate()

    @Slot()
    def _summary_changed(self) -> None:
        if self._updating_controls or self.current_target is None:
            return
        selection = self.selections.get(self.current_target.id)
        if selection is None or selection.action is not TrimAction.SUMMARY:
            return
        text = self.ui.summaryEdit.toPlainText().strip()
        if text:
            self.selections[self.current_target.id] = selection.model_copy(update={"summary": text})
            self._update_estimate()

    @Slot()
    def _regenerate_suggestions(self) -> None:
        if self.document is None:
            return
        if self.ui.aiConsentCheck.isChecked():
            self._show_error("尚未配置内容 AI 提供方；未发送任何内容，已使用本地规则。")
        plan = LocalTrimSuggester().suggest(
            self.document.snapshot,
            capabilities=self.document.capabilities,
            trigger=self.trigger,
            source_turn_id=self.source_turn_id,
        )
        self.selections = {selection.target_id: selection for selection in plan.selections}
        if self.timeline_model:
            self.timeline_model.selections = self.selections
            self.timeline_model.refresh_actions()
        self.current_plan = plan
        if self.current_target:
            self._show_target(self.current_target)
        self._update_estimate()

    def _build_plan(self) -> TrimPlan:
        if self.document is None:
            raise TrimError("no thread is loaded")
        selections = tuple(self.selections.values())
        validate_selections(self.document.snapshot, selections)
        after = self._estimated_after()
        return TrimPlan.create(
            source_thread=self.document.snapshot,
            capability_fingerprint=self.document.capabilities.fingerprint,
            selections=selections,
            estimated_tokens_after=after,
            trigger=self.trigger,
            source_turn_id=self.source_turn_id,
        )

    @Slot()
    def _save_plan(self) -> None:
        try:
            plan = self._build_plan()
            PlanStore(self.paths).save(plan)
        except (ValueError, OSError, TrimError) as exc:
            self._show_error(f"无法保存 TrimPlan：{exc}")
            return
        self.current_plan = plan
        self.ui.errorLabel.setText(f"TrimPlan 已安全保存：{plan.plan_id}")
        self.ui.errorLabel.show()
        self.plan_saved.emit(plan)
        if self.hook_mode:
            self.close()

    @Slot()
    def _apply_plan(self) -> None:
        try:
            plan = self._build_plan()
            PlanStore(self.paths).save(plan)
        except (ValueError, OSError, TrimError) as exc:
            self._show_error(f"计划校验失败：{exc}")
            return
        self._set_busy(True, "正在创建派生精简任务…")
        self._write_in_progress = True
        generation = self._generation

        def apply() -> str:
            client, capabilities = connect_and_probe(request_timeout=45)
            try:
                with AuditStore(self.paths) as audit:
                    return TrimExecutor(
                        client=client,
                        inventory=InventoryService(client),
                        capabilities=capabilities,
                        audit=audit,
                    ).apply(plan)
            finally:
                client.close()

        worker = FunctionWorker(apply)
        worker.signals.result.connect(
            lambda value, current=generation: self._apply_succeeded(current, value)
        )
        worker.signals.error.connect(
            lambda message, current=generation: self._apply_failed(current, message)
        )
        worker.signals.finished.connect(lambda current=generation: self._apply_finished(current))
        self.thread_pool.start(worker)

    def _apply_succeeded(self, generation: int, value: object) -> None:
        if generation != self._generation or self._closing:
            return
        thread_id = str(value)
        self.derived_created.emit(thread_id)
        QMessageBox.information(
            self,
            "派生任务已创建",
            f"新任务 ID：{thread_id}\n原任务未修改，也没有自动启动模型 turn。",
        )

    def _apply_failed(self, generation: int, message: str) -> None:
        if generation == self._generation and not self._closing:
            self._show_error(f"创建失败：{message}")

    def _apply_finished(self, generation: int) -> None:
        self._write_in_progress = False
        if generation == self._generation and not self._closing:
            self._set_busy(False)

    def _estimated_after(self) -> int:
        if self.document is None:
            return 0
        total = 0
        for turn in self.document.snapshot.turns:
            selection = self.selections.get(turn.id)
            if selection and selection.action is TrimAction.EXCLUDE:
                continue
            if selection and selection.action is TrimAction.SUMMARY:
                total += max(1, len((selection.summary or "").encode("utf-8")) // 3)
                continue
            for item in turn.items:
                item_selection = self.selections.get(item.id)
                if item_selection and item_selection.action is TrimAction.EXCLUDE:
                    continue
                if item_selection and item_selection.action is TrimAction.SUMMARY:
                    total += max(1, len((item_selection.summary or "").encode("utf-8")) // 3)
                else:
                    total += item.token_estimate
        return total

    def _update_estimate(self) -> None:
        if self.document is None:
            return
        before = self.document.snapshot.token_estimate
        after = self._estimated_after()
        saved = max(0, before - after)
        percent = round(saved * 100 / before) if before else 0
        self.ui.tokenLabel.setText(f"预计上下文：{before:,} → {after:,} tokens（节省约 {saved:,}）")
        self.ui.savingProgress.setValue(percent)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.ui.loadButton.setEnabled(not busy)
        self.ui.suggestButton.setEnabled(not busy and self.document is not None)
        self.ui.savePlanButton.setEnabled(not busy and self.document is not None)
        self.ui.applyButton.setEnabled(
            not busy
            and not self.hook_mode
            and self.document is not None
            and self.document.snapshot.status is not ThreadStatus.ACTIVE
            and self.document.capabilities.write_enabled
        )
        if message:
            self.ui.sourceStatusLabel.setText(message)

    def _show_error(self, message: str) -> None:
        self.ui.errorLabel.setText("⚠ " + message)
        self.ui.errorLabel.show()

    @staticmethod
    def _target_text(target: TurnSnapshot | ThreadItemSnapshot) -> str:
        if isinstance(target, TurnSnapshot):
            return "\n".join(item.text for item in target.items if item.text)
        return target.text

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._write_in_progress:
            self._show_error("派生任务写操作正在复核；完成前不能关闭窗口。")
            event.ignore()
            return
        self._closing = True
        self._generation += 1
        self.window_closed.emit()
        super().closeEvent(event)
