"""Navigation page for the existing full context-review workflow."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ContextReviewPage(QWidget):
    """Keep the large legacy controller isolated while exposing a stable page entry."""

    open_thread_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("上下文优化")
        title.setObjectName("workspacePageTitle")
        root.addWidget(title)

        description = QLabel(
            "上下文优化继续使用经过回归测试的专用审查窗口，并只创建派生任务。"
            "本页是统一主窗口中的稳定入口；原对话始终保持不变。"
        )
        description.setWordWrap(True)
        description.setObjectName("workspacePageStatus")
        root.addWidget(description)

        notice = QFrame()
        notice.setObjectName("workspaceNotice")
        notice_layout = QVBoxLayout(notice)
        notice_layout.setContentsMargins(12, 10, 12, 10)
        notice_layout.addWidget(
            QLabel(
                "当前架构切片尚未把 1,800 行的 TrimReviewWindow 控制器完全拆成 QWidget 页面。"
                "为避免回归，统一窗口先负责导航，实际审查仍在独立窗口中完成。"
            )
        )
        root.addWidget(notice)

        input_row = QHBoxLayout()
        self.thread_id_edit = QLineEdit()
        self.thread_id_edit.setPlaceholderText("输入完整 Codex 对话 ID")
        self.thread_id_edit.setAccessibleName("要打开的 Codex 对话 ID")
        input_row.addWidget(self.thread_id_edit, 1)
        self.open_button = QPushButton("打开上下文审查")
        self.open_button.clicked.connect(self._open_thread)
        input_row.addWidget(self.open_button)
        root.addLayout(input_row)

        self.status_label = QLabel("尚未选择对话。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch(1)

        self.thread_id_edit.returnPressed.connect(self._open_thread)

    def set_thread_id(self, thread_id: str) -> None:
        self.thread_id_edit.setText(thread_id)
        self.status_label.setText(f"已准备打开对话 {thread_id}。")

    def _open_thread(self) -> None:
        thread_id = self.thread_id_edit.text().strip()
        if not thread_id:
            self.status_label.setText("请输入完整 Codex 对话 ID。")
            return
        self.status_label.setText(f"正在打开 {thread_id} 的专用上下文审查窗口…")
        self.open_thread_requested.emit(thread_id)
