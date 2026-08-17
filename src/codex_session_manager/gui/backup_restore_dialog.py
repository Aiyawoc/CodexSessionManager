"""Unified backup/restore entry kept read-only until provider abstraction lands."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from codex_session_manager.review_requests import ReviewOperation, ReviewRequest


class BackupRestoreDialog(QDialog):
    """Describe existing safe services without bypassing their plan-based CLI flows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CodexSessionManager · 备份与恢复")
        self.setMinimumWidth(620)
        self.request: ReviewRequest | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.status_label = QLabel(
            "通用资源提供器尚未接入 GUI。已有对话 age 备份与逻辑恢复能力仍可通过"
            "现有计划式 CLI 工作流使用。"
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        backup_group = QGroupBox("创建备份")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.addWidget(
            QLabel("目标范围、age recipient 与完整解密验证将在后续向导中明确选择。")
        )
        backup_button = QPushButton("启动备份向导")
        backup_button.setEnabled(False)
        backup_button.setToolTip("BackupResourceProvider 尚未实现。")
        backup_layout.addWidget(backup_button)
        root.addWidget(backup_group)

        restore_group = QGroupBox("逻辑恢复")
        restore_layout = QVBoxLayout(restore_group)
        restore_layout.addWidget(
            QLabel("对话恢复继续创建新 ID；记忆文件恢复必须先展示 diff 并原子执行。")
        )
        restore_button = QPushButton("启动恢复向导")
        restore_button.setEnabled(False)
        restore_button.setToolTip("统一恢复向导尚未实现。")
        restore_layout.addWidget(restore_button)
        root.addWidget(restore_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def load_request(self, request: ReviewRequest) -> None:
        if request.operation not in {ReviewOperation.BACKUP, ReviewOperation.RESTORE}:
            raise ValueError("BackupRestoreDialog only accepts backup or restore")
        self.request = request
        operation = "备份" if request.operation is ReviewOperation.BACKUP else "恢复"
        target_count = len(request.target_ids) + len(request.target_paths)
        self.status_label.setText(
            f"已加载{operation}请求 {request.request_id}，目标 {target_count} 个。"
            "当前对话框保持只读，不会执行文件或 Codex 写入。"
        )
