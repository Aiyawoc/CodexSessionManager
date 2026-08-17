"""Read-only placeholder for explicitly registered local memory files."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codex_session_manager.review_requests import ReviewOperation, ReviewRequest


class MemoryManagerPage(QWidget):
    """Show requested memory paths without exposing file mutation yet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.request: ReviewRequest | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("记忆文件管理")
        title.setObjectName("workspacePageTitle")
        root.addWidget(title)

        self.status_label = QLabel(
            "MVP 只会管理用户明确登记的本地 Markdown/文本文件。当前切片保持只读，"
            "不会修改 ChatGPT 账号的服务器端 Memory，也不会写入未登记路径。"
        )
        self.status_label.setObjectName("workspacePageStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.sources = QTreeWidget()
        self.sources.setObjectName("memorySourceTree")
        self.sources.setHeaderLabels(("请求路径", "状态"))
        self.sources.setRootIsDecorated(False)
        self.sources.setAlternatingRowColors(True)
        self.sources.setAccessibleName("记忆文件请求路径")
        root.addWidget(self.sources, 1)

        self.register_button = QPushButton("登记记忆来源")
        self.register_button.setEnabled(False)
        self.register_button.setToolTip("允许根登记与安全写入将在阶段 4 实现。")
        root.addWidget(self.register_button)

    def load_request(self, request: ReviewRequest) -> None:
        if request.operation is not ReviewOperation.MEMORY_EDIT:
            raise ValueError("MemoryManagerPage only accepts memory_edit")
        self.request = request
        self.sources.clear()
        for target_path in request.target_paths:
            self.sources.addTopLevelItem(QTreeWidgetItem((target_path, "只读待审查")))
        self.sources.resizeColumnToContents(0)
        self.status_label.setText(
            f"已加载请求 {request.request_id}，包含 {len(request.target_paths)} 个路径。"
            "当前页面不会读取或改写这些文件。"
        )
