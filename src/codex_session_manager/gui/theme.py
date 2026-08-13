"""Role-based light theme for the desktop GUI."""

from __future__ import annotations

SURFACE = "#f4f7fb"
PANEL = "#ffffff"
PANEL_MUTED = "#f8faff"
TEXT = "#1f2937"
TEXT_MUTED = "#66758a"
OUTLINE = "#d9e2ee"
OUTLINE_STRONG = "#b7c6d9"
# Quiet blue-gray separator, only slightly darker than the application surface.
SPLITTER_LINE = OUTLINE
ACCENT = "#3567d6"
ACCENT_HOVER = "#2c56b8"
ACCENT_SOFT = "#e8f0ff"
SUCCESS = "#1f7a45"
SUCCESS_SOFT = "#eaf7ef"
WARNING = "#9a5b00"
WARNING_SOFT = "#fff7e6"
DANGER = "#b42318"
DANGER_SOFT = "#fff1f0"
ON_DANGER = "#ffffff"


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

QToolButton#projectTaskRailButton {{
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

QToolButton#taskPaneCollapseButton, QToolButton#contentTagsButton,
QToolButton#contentMarkdownButton {{
    min-height: 28px;
    padding: 0 7px;
    border: 1px solid transparent;
    border-radius: 5px;
    color: {TEXT_MUTED};
    font-size: 11px;
}}

QToolButton#taskPaneCollapseButton:hover,
QToolButton#contentTagsButton:hover, QToolButton#contentMarkdownButton:hover,
QToolButton#contentTagsButton:checked, QToolButton#contentMarkdownButton:checked {{
    background: {ACCENT_SOFT};
    border-color: #c8d8ff;
    color: #174a9e;
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

QLabel#timelineHelp, QLabel#taskContextStatusLabel, QLabel#taskListStatusLabel {{
    color: {TEXT_MUTED};
}}

QLabel#tokenLabel {{
    color: {TEXT};
    background: transparent;
}}

QLabel#reasonLabel, QLabel#summaryLabel {{
    color: {TEXT_MUTED};
    font-weight: 500;
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

QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QTextEdit {{
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

QPlainTextEdit, QTextBrowser, QTextEdit {{
    padding: 8px;
}}

QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus,
QTextEdit:focus,
QTreeView:focus {{
    border: 1px solid {ACCENT};
}}

QTextEdit#contentBrowser {{
    background: #ffffff;
    color: {TEXT};
}}

QComboBox::drop-down {{
    width: 28px;
    background: {PANEL_MUTED};
    border-left: 1px solid {OUTLINE};
    subcontrol-origin: padding;
    subcontrol-position: top right;
}}

QComboBox::down-arrow {{
    image: url(:/csm/combo-down.svg);
    width: 12px;
    height: 8px;
}}

QComboBox QAbstractItemView, QAbstractItemView {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {OUTLINE};
    outline: 0;
    selection-background-color: {ACCENT_SOFT};
    selection-color: #174a9e;
}}

QComboBox QAbstractItemView::item {{
    background: {PANEL};
    color: {TEXT};
    min-height: 28px;
    padding: 5px 8px;
}}

QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT_SOFT};
    color: #174a9e;
}}

QMenu {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {OUTLINE};
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 22px 6px 10px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: #174a9e;
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
QPushButton#taskArchiveButton, QPushButton#savePlanButton, QPushButton#reviewButton {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}

QPushButton#loadButton:hover, QPushButton#suggestButton:hover,
QPushButton#taskRefreshButton:hover,
QPushButton#taskArchiveButton:hover, QPushButton#savePlanButton:hover,
QPushButton#reviewButton:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

QPushButton#taskDeleteButton {{
    background: {DANGER_SOFT};
    border-color: #f1c6c1;
    color: {DANGER};
}}

QPushButton#taskDeleteButton:hover {{
    background: #ffe5e2;
    border-color: {DANGER};
}}

QPushButton#taskBackupButton {{
    background: {ACCENT_SOFT};
    border-color: {ACCENT};
    color: {ACCENT};
}}

QPushButton#taskBackupButton:hover {{
    background: #dce9ff;
    border-color: {ACCENT_HOVER};
    color: {ACCENT_HOVER};
}}

QPushButton#sensitiveScanButton {{
    background: {DANGER_SOFT};
    border-color: #f1c6c1;
    color: {DANGER};
}}

QPushButton#sensitiveScanButton:hover {{
    background: #ffe5e2;
    border-color: {DANGER};
}}

QPushButton#sensitiveScanButton:checked {{
    background: {DANGER};
    border-color: {DANGER};
    color: #ffffff;
}}

QPushButton#sensitiveScanButton:checked:hover {{
    background: #8f1c13;
    border-color: #8f1c13;
}}

QPushButton#loadButton:disabled, QPushButton#suggestButton:disabled,
QPushButton#taskRefreshButton:disabled, QPushButton#taskArchiveButton:disabled,
QPushButton#taskBackupButton:disabled, QPushButton#taskDeleteButton:disabled,
QPushButton#savePlanButton:disabled,
QPushButton#sensitiveScanButton:disabled, QPushButton#reviewButton:disabled {{
    background: #eef2f7;
    color: #9aa7b7;
    border-color: #e2e8f0;
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

QTreeView::branch:closed:has-children,
QTreeWidget::branch:closed:has-children {{
    image: url(:/csm/branch-closed.svg);
}}

QTreeView::branch:open:has-children,
QTreeWidget::branch:open:has-children {{
    image: url(:/csm/branch-open.svg);
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
    width: 8px;
    background: transparent;
    border: 0;
    border-radius: 0;
}}

QSplitter::handle:horizontal:hover {{
    background: transparent;
    border: 0;
    border-radius: 0;
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
