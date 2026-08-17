"""Unified navigation shell for review workflows that remain plan-gated."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from codex_session_manager.config import AppPaths
from codex_session_manager.gui.backup_restore_dialog import BackupRestoreDialog
from codex_session_manager.gui.context_review_page import ContextReviewPage
from codex_session_manager.gui.conversation_cleanup_page import ConversationCleanupPage
from codex_session_manager.gui.memory_manager_page import MemoryManagerPage
from codex_session_manager.gui.pending_plans_page import PendingPlansPage
from codex_session_manager.gui.single_instance import DesktopPage
from codex_session_manager.review_requests import ReviewOperation, ReviewRequest

_PAGE_LABELS: dict[DesktopPage, str] = {
    DesktopPage.CLEANUP: "对话清理",
    DesktopPage.CONTEXT: "上下文优化",
    DesktopPage.MEMORY: "记忆管理",
    DesktopPage.PENDING: "待处理计划",
    DesktopPage.BACKUP_RESTORE: "备份与恢复",
}


class UnifiedMainWindow(QMainWindow):
    """Stable shell that routes users to read-only or plan-based workflows."""

    open_thread_requested = Signal(str)
    open_review_requested = Signal(str)
    window_closed = Signal()

    def __init__(self, paths: AppPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.paths.ensure()
        self.setObjectName("UnifiedMainWindow")
        self.setWindowTitle("CodexSessionManager")
        self.resize(1600, 900)
        self.setMinimumSize(1280, 720)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("workspaceSidebar")
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 12)
        sidebar_layout.setSpacing(10)

        brand = QLabel("CodexSessionManager")
        brand.setObjectName("workspaceBrand")
        sidebar_layout.addWidget(brand)
        subtitle = QLabel("统一审查工作台")
        subtitle.setObjectName("workspaceSubtitle")
        sidebar_layout.addWidget(subtitle)

        self.navigation = QListWidget()
        self.navigation.setObjectName("workspaceNavigation")
        self.navigation.setAccessibleName("CodexSessionManager 功能导航")
        self.navigation.setSpacing(4)
        sidebar_layout.addWidget(self.navigation, 1)

        safety = QLabel("LLM 只给建议\n最终写入必须由本地计划复核")
        safety.setWordWrap(True)
        safety.setObjectName("workspaceSafety")
        sidebar_layout.addWidget(safety)
        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("workspaceStack")
        root.addWidget(self.stack, 1)

        self.cleanup_page = ConversationCleanupPage(paths)
        self.context_page = ContextReviewPage()
        self.memory_page = MemoryManagerPage()
        self.pending_page = PendingPlansPage(paths)
        self.backup_dialog = BackupRestoreDialog(self)
        self.backup_page = self._create_backup_page()

        self._pages: dict[DesktopPage, QWidget] = {
            DesktopPage.CLEANUP: self.cleanup_page,
            DesktopPage.CONTEXT: self.context_page,
            DesktopPage.MEMORY: self.memory_page,
            DesktopPage.PENDING: self.pending_page,
            DesktopPage.BACKUP_RESTORE: self.backup_page,
        }
        self._rows: dict[DesktopPage, int] = {}
        for page, label in _PAGE_LABELS.items():
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, page.value)
            self.navigation.addItem(item)
            self._rows[page] = self.stack.addWidget(self._pages[page])

        self.navigation.currentRowChanged.connect(self._navigation_changed)
        self.context_page.open_thread_requested.connect(self.open_thread_requested)
        self.pending_page.open_thread_requested.connect(self.open_thread_requested)
        self.pending_page.open_review_requested.connect(self.open_review_requested)
        self.open_page(DesktopPage.CONTEXT)

    @property
    def current_page(self) -> DesktopPage:
        current = self.navigation.currentItem()
        if current is None:
            return DesktopPage.CONTEXT
        value = current.data(Qt.ItemDataRole.UserRole)
        return DesktopPage(str(value))

    def open_page(self, page: DesktopPage) -> None:
        row = self._rows[page]
        self.navigation.setCurrentRow(row)
        self.stack.setCurrentWidget(self._pages[page])
        self.setWindowTitle(f"CodexSessionManager · {_PAGE_LABELS[page]}")
        if page is DesktopPage.PENDING:
            self.pending_page.refresh()

    def load_request(self, request: ReviewRequest) -> None:
        self.setProperty("csmReviewRequestId", request.request_id)
        self.setProperty("csmReviewOperation", request.operation.value)
        if request.operation is ReviewOperation.CONVERSATION_CLEANUP:
            self.cleanup_page.load_request(request)
            self.open_page(DesktopPage.CLEANUP)
        elif request.operation is ReviewOperation.CONTEXT_TRIM:
            self.context_page.set_thread_id(request.target_ids[0])
            self.open_page(DesktopPage.CONTEXT)
        elif request.operation is ReviewOperation.MEMORY_EDIT:
            self.memory_page.load_request(request)
            self.open_page(DesktopPage.MEMORY)
        elif request.operation in {ReviewOperation.BACKUP, ReviewOperation.RESTORE}:
            self.backup_dialog.load_request(request)
            self.open_page(DesktopPage.BACKUP_RESTORE)
            self.backup_dialog.show()
            self.backup_dialog.raise_()
            self.backup_dialog.activateWindow()

    def _create_backup_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("备份与恢复")
        title.setObjectName("workspacePageTitle")
        root.addWidget(title)
        status = QLabel(
            "现有 age 加密备份和逻辑恢复服务继续通过计划式 CLI 使用。"
            "统一 GUI 向导尚未接入资源提供器，因此这里不会直接执行写入。"
        )
        status.setObjectName("workspacePageStatus")
        status.setWordWrap(True)
        root.addWidget(status)
        open_dialog_button = QPushButton("查看备份/恢复入口")
        open_dialog_button.clicked.connect(self.backup_dialog.show)
        root.addWidget(open_dialog_button)
        root.addStretch(1)
        return page

    def _navigation_changed(self, row: int) -> None:
        item = self.navigation.item(row)
        if item is None:
            return
        value = item.data(Qt.ItemDataRole.UserRole)
        try:
            page = DesktopPage(str(value))
        except ValueError:
            return
        self.stack.setCurrentWidget(self._pages[page])
        self.setWindowTitle(f"CodexSessionManager · {_PAGE_LABELS[page]}")
        if page is DesktopPage.PENDING:
            self.pending_page.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.window_closed.emit()
        super().closeEvent(event)
