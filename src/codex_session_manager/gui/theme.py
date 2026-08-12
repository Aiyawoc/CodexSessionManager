"""Role-based light theme for the desktop GUI."""

from __future__ import annotations

SURFACE = "#f4f7fb"
PANEL = "#ffffff"
PANEL_MUTED = "#f8faff"
TEXT = "#1f2937"
TEXT_MUTED = "#66758a"
OUTLINE = "#d9e2ee"
OUTLINE_STRONG = "#b7c6d9"
ACCENT = "#3567d6"
ACCENT_HOVER = "#2c56b8"
ACCENT_SOFT = "#e8f0ff"
SUCCESS = "#1f7a45"
SUCCESS_SOFT = "#eaf7ef"
WARNING = "#9a5b00"
WARNING_SOFT = "#fff7e6"
DANGER = "#b42318"
DANGER_SOFT = "#fff1f0"


APP_STYLESHEET = f"""
QMainWindow, QDialog, QWidget#centralwidget {{
    background: {SURFACE};
    color: {TEXT};
}}

QFrame#heroFrame, QFrame#footerFrame {{
    background: {PANEL};
    border: 1px solid {OUTLINE};
    border-radius: 10px;
}}

QFrame#toolRail {{
    background: {PANEL};
    border: 1px solid {OUTLINE};
    border-radius: 8px;
}}

QToolButton#projectTaskRailButton, QToolButton#backupRailButton,
QToolButton#cleanupRailButton, QToolButton#auditRailButton {{
    min-width: 32px;
    min-height: 32px;
    max-width: 34px;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {TEXT_MUTED};
    font-size: 15px;
    font-weight: 600;
}}

QToolButton#projectTaskRailButton:hover,
QToolButton#projectTaskRailButton:checked {{
    background: {ACCENT_SOFT};
    border-color: #c8d8ff;
    color: #174a9e;
}}

QToolButton#taskPaneCollapseButton {{
    min-width: 34px;
    min-height: 34px;
    background: {ACCENT_SOFT};
    border: 1px solid #c8d8ff;
    border-radius: 6px;
    color: #174a9e;
}}

QToolButton#taskPaneCollapseButton:hover {{
    background: #dce8ff;
    border-color: {ACCENT};
}}

QToolButton#backupRailButton:disabled, QToolButton#cleanupRailButton:disabled,
QToolButton#auditRailButton:disabled {{
    background: {PANEL_MUTED};
    border-color: {OUTLINE};
    color: {TEXT_MUTED};
}}

QLabel#brandMark {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    border: 1px solid #c8d8ff;
    border-radius: 12px;
    font-size: 16px;
    font-weight: 700;
}}

QLabel#appTitleLabel {{
    color: {TEXT};
    font-size: 18px;
    font-weight: 600;
}}

QLabel#appSubtitleLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

QLabel#timelineHelp, QLabel#contentMetaLabel,
QLabel#taskContextStatusLabel, QLabel#taskHelp,
QLabel#taskListStatusLabel {{
    color: {TEXT_MUTED};
}}

QLabel#threadIdLabel {{
    font-weight: 600;
}}

QLabel#taskContextStatusLabel {{
    font-size: 11px;
}}

QLabel#headerBadge {{
    background: {SUCCESS_SOFT};
    color: {SUCCESS};
    border: 1px solid #c5e8d1;
    border-radius: 7px;
    padding: 6px 10px;
    font-weight: 600;
}}

QLabel#timelineTitle, QLabel#contentTitle, QLabel#actionTitle, QLabel#taskTitle {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
}}

QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {OUTLINE};
    border-radius: 7px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}

QLineEdit, QComboBox {{
    min-height: 30px;
    padding: 0 9px;
}}

QPlainTextEdit, QTextBrowser {{
    padding: 8px;
}}

QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus,
QTreeView:focus {{
    border: 1px solid {ACCENT};
}}

QComboBox::drop-down {{
    width: 28px;
    border: 0;
    border-left: 1px solid {OUTLINE};
}}

QPushButton {{
    min-height: 31px;
    padding: 0 13px;
    border: 1px solid {OUTLINE_STRONG};
    border-radius: 7px;
    background: {PANEL};
    color: {TEXT};
    font-weight: 500;
}}

QPushButton:hover {{
    background: {PANEL_MUTED};
    border-color: {ACCENT};
}}

QPushButton:pressed {{
    background: {ACCENT_SOFT};
}}

QPushButton:disabled {{
    background: #eef2f7;
    color: #9aa7b7;
    border-color: #e2e8f0;
}}

QPushButton#loadButton, QPushButton#suggestButton, QPushButton#taskRefreshButton,
QPushButton#savePlanButton, QPushButton#reviewButton {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}

QPushButton#loadButton:hover, QPushButton#suggestButton:hover,
QPushButton#taskRefreshButton:hover,
QPushButton#savePlanButton:hover, QPushButton#reviewButton:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

QPushButton#applyButton {{
    background: {SUCCESS};
    border-color: {SUCCESS};
    color: #ffffff;
}}

QPushButton#applyButton:hover {{
    background: #176238;
    border-color: #176238;
}}

QTreeView, QTreeWidget {{
    background: {PANEL};
    color: {TEXT};
    alternate-background-color: {PANEL_MUTED};
    border: 1px solid {OUTLINE};
    border-radius: 8px;
    outline: 0;
    padding: 4px;
}}

QTreeView::item, QTreeWidget::item {{
    color: {TEXT};
    min-height: 28px;
    padding: 4px 6px;
    border-radius: 5px;
}}

QTreeView::item:hover, QTreeWidget::item:hover {{
    background: {ACCENT_SOFT};
}}

QTreeView::item:selected, QTreeWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: #174a9e;
}}

QTreeWidget::item:disabled {{
    color: {TEXT_MUTED};
}}

QHeaderView::section {{
    background: {PANEL_MUTED};
    color: {TEXT_MUTED};
    border: 0;
    border-bottom: 1px solid {OUTLINE};
    padding: 7px 6px;
    font-weight: 600;
}}

QSplitter::handle:horizontal {{
    width: 6px;
    background: #dbe7ff;
    border-radius: 3px;
}}

QSplitter::handle:horizontal:hover {{
    background: {ACCENT};
    border-radius: 4px;
}}

QLabel#riskLabel {{
    background: {WARNING_SOFT};
    color: {WARNING};
    border: 1px solid #f1d39a;
    border-radius: 7px;
    padding: 7px 8px;
}}

QTextBrowser#reasonBrowser {{
    background: {WARNING_SOFT};
    border-color: #f1d39a;
}}

QLabel#errorLabel {{
    background: {DANGER_SOFT};
    color: {DANGER};
    border: 1px solid #f1c6c1;
    border-radius: 7px;
    padding: 6px 8px;
}}

QProgressBar {{
    min-height: 18px;
    border: 1px solid {OUTLINE};
    border-radius: 7px;
    background: #edf2f8;
    color: {TEXT_MUTED};
    text-align: center;
}}

QProgressBar::chunk {{
    border-radius: 6px;
    background: {ACCENT};
}}

QCheckBox {{
    spacing: 7px;
    color: {TEXT_MUTED};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
}}

QDialog#PrecompactPrompt {{
    background: {PANEL};
}}

QLabel#titleLabel {{
    color: {TEXT};
    font-size: 17px;
    font-weight: 600;
}}

QLabel#messageLabel {{
    color: {TEXT_MUTED};
    line-height: 1.4;
}}

QToolTip {{
    background: {TEXT};
    color: #ffffff;
    border: 0;
    padding: 6px 8px;
}}
"""
