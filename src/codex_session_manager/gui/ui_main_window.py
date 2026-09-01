# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QSpacerItem, QTextBrowser,
    QTextEdit, QToolButton, QTreeView, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from codex_session_manager.gui.widgets import CenteredHandleSplitter

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1600, 900)
        MainWindow.setMinimumSize(QSize(1280, 720))
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.rootLayout = QVBoxLayout(self.centralwidget)
        self.rootLayout.setSpacing(12)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(16, 16, 16, 12)
        self.heroFrame = QFrame(self.centralwidget)
        self.heroFrame.setObjectName(u"heroFrame")
        self.heroFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.heroFrame.setMaximumSize(QSize(16777215, 100))
        self.heroLayout = QHBoxLayout(self.heroFrame)
        self.heroLayout.setObjectName(u"heroLayout")
        self.heroLayout.setContentsMargins(14, 12, 14, 12)
        self.brandMark = QLabel(self.heroFrame)
        self.brandMark.setObjectName(u"brandMark")
        self.brandMark.setMinimumSize(QSize(48, 48))
        self.brandMark.setMaximumSize(QSize(48, 48))
        self.brandMark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.heroLayout.addWidget(self.brandMark)

        self.heroTextLayout = QVBoxLayout()
        self.heroTextLayout.setSpacing(2)
        self.heroTextLayout.setObjectName(u"heroTextLayout")
        self.appTitleLabel = QLabel(self.heroFrame)
        self.appTitleLabel.setObjectName(u"appTitleLabel")

        self.heroTextLayout.addWidget(self.appTitleLabel)

        self.appSubtitleLabel = QLabel(self.heroFrame)
        self.appSubtitleLabel.setObjectName(u"appSubtitleLabel")

        self.heroTextLayout.addWidget(self.appSubtitleLabel)


        self.heroLayout.addLayout(self.heroTextLayout)

        self.heroSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.heroLayout.addItem(self.heroSpacer)

        self.headerBadge = QLabel(self.heroFrame)
        self.headerBadge.setObjectName(u"headerBadge")
        self.headerBadge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.heroLayout.addWidget(self.headerBadge)

        self.languageCombo = QComboBox(self.heroFrame)
        self.languageCombo.addItem("")
        self.languageCombo.addItem("")
        self.languageCombo.setObjectName(u"languageCombo")
        self.languageCombo.setMinimumSize(QSize(92, 0))
        self.languageCombo.setMaximumSize(QSize(108, 16777215))

        self.heroLayout.addWidget(self.languageCombo)


        self.rootLayout.addWidget(self.heroFrame)

        self.workspaceLayout = QHBoxLayout()
        self.workspaceLayout.setSpacing(8)
        self.workspaceLayout.setObjectName(u"workspaceLayout")
        self.workspaceLayout.setContentsMargins(0, 0, 0, 0)
        self.toolRail = QFrame(self.centralwidget)
        self.toolRail.setObjectName(u"toolRail")
        self.toolRail.setMinimumSize(QSize(44, 0))
        self.toolRail.setMaximumSize(QSize(44, 16777215))
        self.toolRail.setFrameShape(QFrame.Shape.StyledPanel)
        self.toolRailLayout = QVBoxLayout(self.toolRail)
        self.toolRailLayout.setSpacing(6)
        self.toolRailLayout.setObjectName(u"toolRailLayout")
        self.toolRailLayout.setContentsMargins(4, 4, 4, 4)
        self.projectTaskRailButton = QToolButton(self.toolRail)
        self.projectTaskRailButton.setObjectName(u"projectTaskRailButton")
        self.projectTaskRailButton.setCheckable(True)
        self.projectTaskRailButton.setChecked(True)
        self.projectTaskRailButton.setAutoRaise(True)
        self.projectTaskRailButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.toolRailLayout.addWidget(self.projectTaskRailButton)

        self.memoryRailButton = QToolButton(self.toolRail)
        self.memoryRailButton.setObjectName(u"memoryRailButton")
        self.memoryRailButton.setCheckable(True)
        self.memoryRailButton.setChecked(False)
        self.memoryRailButton.setAutoRaise(True)
        self.memoryRailButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.toolRailLayout.addWidget(self.memoryRailButton)

        self.toolRailSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.toolRailLayout.addItem(self.toolRailSpacer)


        self.workspaceLayout.addWidget(self.toolRail)

        self.mainSplitter = CenteredHandleSplitter(self.centralwidget)
        self.mainSplitter.setObjectName(u"mainSplitter")
        self.mainSplitter.setOrientation(Qt.Orientation.Horizontal)
        self.mainSplitter.setHandleWidth(8)
        self.mainSplitter.setChildrenCollapsible(False)
        self.taskPane = QWidget(self.mainSplitter)
        self.taskPane.setObjectName(u"taskPane")
        self.taskPane.setMinimumSize(QSize(280, 0))
        self.taskLayout = QVBoxLayout(self.taskPane)
        self.taskLayout.setObjectName(u"taskLayout")
        self.taskLayout.setContentsMargins(0, 0, 4, 0)
        self.taskTopLayout = QVBoxLayout()
        self.taskTopLayout.setSpacing(0)
        self.taskTopLayout.setObjectName(u"taskTopLayout")
        self.taskHeaderLayout = QHBoxLayout()
        self.taskHeaderLayout.setSpacing(8)
        self.taskHeaderLayout.setObjectName(u"taskHeaderLayout")
        self.taskTitle = QLabel(self.taskPane)
        self.taskTitle.setObjectName(u"taskTitle")
        self.taskTitle.setMinimumSize(QSize(0, 32))
        self.taskTitle.setMaximumSize(QSize(16777215, 32))
        font = QFont()
        font.setPointSize(15)
        self.taskTitle.setFont(font)

        self.taskHeaderLayout.addWidget(self.taskTitle)

        self.taskHeaderSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.taskHeaderLayout.addItem(self.taskHeaderSpacer)

        self.taskPaneCollapseButton = QToolButton(self.taskPane)
        self.taskPaneCollapseButton.setObjectName(u"taskPaneCollapseButton")
        self.taskPaneCollapseButton.setMinimumSize(QSize(0, 32))
        self.taskPaneCollapseButton.setMaximumSize(QSize(16777215, 32))
        self.taskPaneCollapseButton.setAutoRaise(True)
        self.taskPaneCollapseButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self.taskHeaderLayout.addWidget(self.taskPaneCollapseButton)


        self.taskTopLayout.addLayout(self.taskHeaderLayout)

        self.manualTaskLayout = QHBoxLayout()
        self.manualTaskLayout.setSpacing(6)
        self.manualTaskLayout.setObjectName(u"manualTaskLayout")
        self.threadIdEdit = QLineEdit(self.taskPane)
        self.threadIdEdit.setObjectName(u"threadIdEdit")
        self.threadIdEdit.setMinimumSize(QSize(0, 36))
        self.threadIdEdit.setMaximumSize(QSize(16777215, 36))

        self.manualTaskLayout.addWidget(self.threadIdEdit)

        self.loadButton = QPushButton(self.taskPane)
        self.loadButton.setObjectName(u"loadButton")

        self.manualTaskLayout.addWidget(self.loadButton)

        self.taskFilterButton = QPushButton(self.taskPane)
        self.taskFilterButton.setObjectName(u"taskFilterButton")

        self.manualTaskLayout.addWidget(self.taskFilterButton)


        self.taskTopLayout.addLayout(self.manualTaskLayout)


        self.taskLayout.addLayout(self.taskTopLayout)

        self.taskListView = QTreeWidget(self.taskPane)
        self.taskListView.setObjectName(u"taskListView")
        self.taskListView.setAlternatingRowColors(True)
        self.taskListView.setUniformRowHeights(True)
        self.taskListView.setRootIsDecorated(True)
        self.taskListView.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.taskListView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.taskListView.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.taskLayout.addWidget(self.taskListView)

        self.taskListStatusLabel = QLabel(self.taskPane)
        self.taskListStatusLabel.setObjectName(u"taskListStatusLabel")
        self.taskListStatusLabel.setWordWrap(True)

        self.taskLayout.addWidget(self.taskListStatusLabel)

        self.taskActionLayout = QHBoxLayout()
        self.taskActionLayout.setSpacing(6)
        self.taskActionLayout.setObjectName(u"taskActionLayout")
        self.taskRefreshButton = QPushButton(self.taskPane)
        self.taskRefreshButton.setObjectName(u"taskRefreshButton")

        self.taskActionLayout.addWidget(self.taskRefreshButton)

        self.taskBackupButton = QPushButton(self.taskPane)
        self.taskBackupButton.setObjectName(u"taskBackupButton")
        self.taskBackupButton.setEnabled(False)

        self.taskActionLayout.addWidget(self.taskBackupButton)

        self.taskArchiveButton = QPushButton(self.taskPane)
        self.taskArchiveButton.setObjectName(u"taskArchiveButton")
        self.taskArchiveButton.setEnabled(False)

        self.taskActionLayout.addWidget(self.taskArchiveButton)


        self.taskLayout.addLayout(self.taskActionLayout)

        self.mainSplitter.addWidget(self.taskPane)
        self.timelinePane = QWidget(self.mainSplitter)
        self.timelinePane.setObjectName(u"timelinePane")
        self.timelinePane.setMinimumSize(QSize(250, 0))
        self.timelineLayout = QVBoxLayout(self.timelinePane)
        self.timelineLayout.setSpacing(0)
        self.timelineLayout.setObjectName(u"timelineLayout")
        self.timelineLayout.setContentsMargins(4, 0, 4, 0)
        self.timelineHeaderLayout = QHBoxLayout()
        self.timelineHeaderLayout.setSpacing(6)
        self.timelineHeaderLayout.setObjectName(u"timelineHeaderLayout")
        self.timelineTitle = QLabel(self.timelinePane)
        self.timelineTitle.setObjectName(u"timelineTitle")
        self.timelineTitle.setMinimumSize(QSize(0, 32))
        self.timelineTitle.setMaximumSize(QSize(16777215, 32))
        self.timelineTitle.setFont(font)

        self.timelineHeaderLayout.addWidget(self.timelineTitle)

        self.timelineHeaderSpacer = QSpacerItem(12, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.timelineHeaderLayout.addItem(self.timelineHeaderSpacer)

        self.timelineHelp = QLabel(self.timelinePane)
        self.timelineHelp.setObjectName(u"timelineHelp")
        self.timelineHelp.setMinimumSize(QSize(0, 32))
        self.timelineHelp.setMaximumSize(QSize(16777215, 32))
        self.timelineHelp.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.timelineHelp.setWordWrap(False)

        self.timelineHeaderLayout.addWidget(self.timelineHelp)


        self.timelineLayout.addLayout(self.timelineHeaderLayout)

        self.timelineView = QTreeView(self.timelinePane)
        self.timelineView.setObjectName(u"timelineView")
        self.timelineView.setAlternatingRowColors(True)
        self.timelineView.setUniformRowHeights(True)
        self.timelineView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.timelineLayout.addWidget(self.timelineView)

        self.mainSplitter.addWidget(self.timelinePane)
        self.contentPane = QWidget(self.mainSplitter)
        self.contentPane.setObjectName(u"contentPane")
        self.contentPane.setMinimumSize(QSize(340, 0))
        self.contentLayout = QVBoxLayout(self.contentPane)
        self.contentLayout.setSpacing(0)
        self.contentLayout.setObjectName(u"contentLayout")
        self.contentLayout.setContentsMargins(4, 0, 4, 0)
        self.contentHeaderLayout = QHBoxLayout()
        self.contentHeaderLayout.setSpacing(6)
        self.contentHeaderLayout.setObjectName(u"contentHeaderLayout")
        self.contentTitle = QLabel(self.contentPane)
        self.contentTitle.setObjectName(u"contentTitle")
        self.contentTitle.setMinimumSize(QSize(0, 32))
        self.contentTitle.setMaximumSize(QSize(16777215, 32))
        self.contentTitle.setFont(font)

        self.contentHeaderLayout.addWidget(self.contentTitle)

        self.contentHeaderSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.contentHeaderLayout.addItem(self.contentHeaderSpacer)

        self.contentTagsButton = QToolButton(self.contentPane)
        self.contentTagsButton.setObjectName(u"contentTagsButton")
        self.contentTagsButton.setMinimumSize(QSize(0, 32))
        self.contentTagsButton.setMaximumSize(QSize(16777215, 32))
        self.contentTagsButton.setCheckable(True)
        self.contentTagsButton.setAutoRaise(True)
        self.contentTagsButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self.contentHeaderLayout.addWidget(self.contentTagsButton)

        self.contentMarkdownButton = QToolButton(self.contentPane)
        self.contentMarkdownButton.setObjectName(u"contentMarkdownButton")
        self.contentMarkdownButton.setMinimumSize(QSize(0, 32))
        self.contentMarkdownButton.setMaximumSize(QSize(16777215, 32))
        self.contentMarkdownButton.setCheckable(True)
        self.contentMarkdownButton.setAutoRaise(True)
        self.contentMarkdownButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self.contentHeaderLayout.addWidget(self.contentMarkdownButton)


        self.contentLayout.addLayout(self.contentHeaderLayout)

        self.contentBrowser = QTextEdit(self.contentPane)
        self.contentBrowser.setObjectName(u"contentBrowser")
        self.contentBrowser.setAcceptRichText(False)

        self.contentLayout.addWidget(self.contentBrowser)

        self.mainSplitter.addWidget(self.contentPane)
        self.actionPane = QWidget(self.mainSplitter)
        self.actionPane.setObjectName(u"actionPane")
        self.actionPane.setMinimumSize(QSize(260, 0))
        self.actionLayout = QVBoxLayout(self.actionPane)
        self.actionLayout.setObjectName(u"actionLayout")
        self.actionLayout.setContentsMargins(4, 0, 0, 0)
        self.actionTopLayout = QVBoxLayout()
        self.actionTopLayout.setSpacing(0)
        self.actionTopLayout.setObjectName(u"actionTopLayout")
        self.actionTitle = QLabel(self.actionPane)
        self.actionTitle.setObjectName(u"actionTitle")
        self.actionTitle.setMinimumSize(QSize(0, 32))
        self.actionTitle.setMaximumSize(QSize(16777215, 32))
        self.actionTitle.setFont(font)

        self.actionTopLayout.addWidget(self.actionTitle)

        self.actionCombo = QComboBox(self.actionPane)
        self.actionCombo.addItem("")
        self.actionCombo.addItem("")
        self.actionCombo.addItem("")
        self.actionCombo.addItem("")
        self.actionCombo.setObjectName(u"actionCombo")

        self.actionTopLayout.addWidget(self.actionCombo)


        self.actionLayout.addLayout(self.actionTopLayout)

        self.riskLabel = QLabel(self.actionPane)
        self.riskLabel.setObjectName(u"riskLabel")
        self.riskLabel.setWordWrap(True)

        self.actionLayout.addWidget(self.riskLabel)

        self.reasonLabel = QLabel(self.actionPane)
        self.reasonLabel.setObjectName(u"reasonLabel")

        self.actionLayout.addWidget(self.reasonLabel)

        self.reasonBrowser = QTextBrowser(self.actionPane)
        self.reasonBrowser.setObjectName(u"reasonBrowser")
        self.reasonBrowser.setMinimumSize(QSize(0, 96))
        self.reasonBrowser.setMaximumSize(QSize(16777215, 140))

        self.actionLayout.addWidget(self.reasonBrowser)

        self.summaryLabel = QLabel(self.actionPane)
        self.summaryLabel.setObjectName(u"summaryLabel")

        self.actionLayout.addWidget(self.summaryLabel)

        self.summaryEdit = QPlainTextEdit(self.actionPane)
        self.summaryEdit.setObjectName(u"summaryEdit")

        self.actionLayout.addWidget(self.summaryEdit)

        self.aiConsentCheck = QCheckBox(self.actionPane)
        self.aiConsentCheck.setObjectName(u"aiConsentCheck")

        self.actionLayout.addWidget(self.aiConsentCheck)

        self.suggestButton = QPushButton(self.actionPane)
        self.suggestButton.setObjectName(u"suggestButton")

        self.actionLayout.addWidget(self.suggestButton)

        self.actionSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.actionLayout.addItem(self.actionSpacer)

        self.mainSplitter.addWidget(self.actionPane)

        self.workspaceLayout.addWidget(self.mainSplitter)


        self.rootLayout.addLayout(self.workspaceLayout)

        self.footerFrame = QFrame(self.centralwidget)
        self.footerFrame.setObjectName(u"footerFrame")
        self.footerFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.footerFrame.setMaximumSize(QSize(16777215, 54))
        self.footerLayout = QVBoxLayout(self.footerFrame)
        self.footerLayout.setSpacing(4)
        self.footerLayout.setObjectName(u"footerLayout")
        self.footerMainLayout = QHBoxLayout()
        self.footerMainLayout.setSpacing(8)
        self.footerMainLayout.setObjectName(u"footerMainLayout")
        self.tokenLabel = QLabel(self.footerFrame)
        self.tokenLabel.setObjectName(u"tokenLabel")
        self.tokenLabel.setMinimumSize(QSize(250, 0))
        self.tokenLabel.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignVCenter)

        self.footerMainLayout.addWidget(self.tokenLabel)

        self.errorLabel = QLabel(self.footerFrame)
        self.errorLabel.setObjectName(u"errorLabel")
        self.errorLabel.setMinimumSize(QSize(0, 0))
        self.errorLabel.setMaximumSize(QSize(16777215, 34))
        self.errorLabel.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignVCenter)
        self.errorLabel.setWordWrap(False)

        self.footerMainLayout.addWidget(self.errorLabel)

        self.savingProgress = QProgressBar(self.footerFrame)
        self.savingProgress.setObjectName(u"savingProgress")
        self.savingProgress.setMinimum(0)
        self.savingProgress.setMaximum(100)
        self.savingProgress.setValue(0)

        self.footerMainLayout.addWidget(self.savingProgress)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setSpacing(8)
        self.buttonLayout.setObjectName(u"buttonLayout")
        self.buttonLayout.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.sensitiveScanButton = QPushButton(self.footerFrame)
        self.sensitiveScanButton.setObjectName(u"sensitiveScanButton")
        self.sensitiveScanButton.setCheckable(True)

        self.buttonLayout.addWidget(self.sensitiveScanButton)

        self.savePlanButton = QPushButton(self.footerFrame)
        self.savePlanButton.setObjectName(u"savePlanButton")
        self.savePlanButton.setEnabled(False)

        self.buttonLayout.addWidget(self.savePlanButton)

        self.applyButton = QPushButton(self.footerFrame)
        self.applyButton.setObjectName(u"applyButton")
        self.applyButton.setEnabled(False)

        self.buttonLayout.addWidget(self.applyButton)

        self.cancelButton = QPushButton(self.footerFrame)
        self.cancelButton.setObjectName(u"cancelButton")

        self.buttonLayout.addWidget(self.cancelButton)


        self.footerMainLayout.addLayout(self.buttonLayout)


        self.footerLayout.addLayout(self.footerMainLayout)


        self.rootLayout.addWidget(self.footerFrame)

        MainWindow.setCentralWidget(self.centralwidget)
#if QT_CONFIG(shortcut)
        self.summaryLabel.setBuddy(self.summaryEdit)
#endif // QT_CONFIG(shortcut)
        QWidget.setTabOrder(self.languageCombo, self.projectTaskRailButton)
        QWidget.setTabOrder(self.projectTaskRailButton, self.memoryRailButton)
        QWidget.setTabOrder(self.memoryRailButton, self.threadIdEdit)
        QWidget.setTabOrder(self.threadIdEdit, self.loadButton)
        QWidget.setTabOrder(self.loadButton, self.taskFilterButton)
        QWidget.setTabOrder(self.taskFilterButton, self.taskListView)
        QWidget.setTabOrder(self.taskListView, self.taskRefreshButton)
        QWidget.setTabOrder(self.taskRefreshButton, self.taskBackupButton)
        QWidget.setTabOrder(self.taskBackupButton, self.taskArchiveButton)
        QWidget.setTabOrder(self.taskArchiveButton, self.taskPaneCollapseButton)
        QWidget.setTabOrder(self.taskPaneCollapseButton, self.timelineView)
        QWidget.setTabOrder(self.timelineView, self.contentBrowser)
        QWidget.setTabOrder(self.contentBrowser, self.actionCombo)
        QWidget.setTabOrder(self.actionCombo, self.reasonBrowser)
        QWidget.setTabOrder(self.reasonBrowser, self.summaryEdit)
        QWidget.setTabOrder(self.summaryEdit, self.aiConsentCheck)
        QWidget.setTabOrder(self.aiConsentCheck, self.suggestButton)
        QWidget.setTabOrder(self.suggestButton, self.sensitiveScanButton)
        QWidget.setTabOrder(self.sensitiveScanButton, self.savePlanButton)
        QWidget.setTabOrder(self.savePlanButton, self.applyButton)
        QWidget.setTabOrder(self.applyButton, self.cancelButton)

        self.retranslateUi(MainWindow)

        self.savePlanButton.setDefault(True)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"CodexSessionManager \u00b7 \u4e0a\u4e0b\u6587\u88c1\u526a", None))
        self.brandMark.setText(QCoreApplication.translate("MainWindow", u"CSM", None))
        self.appTitleLabel.setText(QCoreApplication.translate("MainWindow", u"CodexSessionManager", None))
        self.appSubtitleLabel.setText(QCoreApplication.translate("MainWindow", u"\u5b89\u5168\u5730\u5ba1\u67e5\u3001\u7cbe\u7b80\u548c\u6d3e\u751f Codex \u4e0a\u4e0b\u6587", None))
        self.headerBadge.setText(QCoreApplication.translate("MainWindow", u"\u539f\u4efb\u52a1\u53ea\u8bfb\u4fdd\u62a4", None))
        self.languageCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"\u4e2d\u6587", None))
        self.languageCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"English", None))

#if QT_CONFIG(tooltip)
        self.languageCombo.setToolTip(QCoreApplication.translate("MainWindow", u"\u754c\u9762\u8bed\u8a00", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.languageCombo.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u754c\u9762\u8bed\u8a00", None))
#endif // QT_CONFIG(accessibility)
        self.projectTaskRailButton.setText(QCoreApplication.translate("MainWindow", u"\u9879\u76ee", None))
#if QT_CONFIG(tooltip)
        self.projectTaskRailButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u4e0e\u4efb\u52a1", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.projectTaskRailButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u4e0e\u4efb\u52a1", None))
#endif // QT_CONFIG(accessibility)
        self.memoryRailButton.setText(QCoreApplication.translate("MainWindow", u"\u8bb0\u5fc6", None))
#if QT_CONFIG(tooltip)
        self.memoryRailButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u8bb0\u5fc6\u7ba1\u7406", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.memoryRailButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u8bb0\u5fc6\u7ba1\u7406", None))
#endif // QT_CONFIG(accessibility)
        self.taskTitle.setText(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u4e0e\u4efb\u52a1", None))
        self.taskPaneCollapseButton.setText(QCoreApplication.translate("MainWindow", u"\u6536\u8d77", None))
#if QT_CONFIG(tooltip)
        self.taskPaneCollapseButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u6536\u8d77\u9879\u76ee\u4e0e\u4efb\u52a1\u9762\u677f", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.taskPaneCollapseButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6536\u8d77\u9879\u76ee\u4e0e\u4efb\u52a1\u9762\u677f", None))
#endif // QT_CONFIG(accessibility)
        self.threadIdEdit.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u641c\u7d22\u9879\u76ee\u3001\u5bf9\u8bdd\u540d\u79f0\uff0c\u6216\u8f93\u5165\u5b8c\u6574\u5bf9\u8bdd ID", None))
#if QT_CONFIG(accessibility)
        self.threadIdEdit.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u641c\u7d22 Codex \u5bf9\u8bdd\u6216\u8f93\u5165\u5bf9\u8bdd ID", None))
#endif // QT_CONFIG(accessibility)
        self.loadButton.setText(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d ID", None))
#if QT_CONFIG(accessibility)
        self.loadButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6309 Codex \u5bf9\u8bdd ID \u52a0\u8f7d", None))
#endif // QT_CONFIG(accessibility)
        self.taskFilterButton.setText(QCoreApplication.translate("MainWindow", u"\u7b5b\u9009", None))
#if QT_CONFIG(accessibility)
        self.taskFilterButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u7b5b\u9009 Codex \u9879\u76ee\u548c\u4efb\u52a1", None))
#endif // QT_CONFIG(accessibility)
        ___qtreewidgetitem = self.taskListView.headerItem()
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("MainWindow", u"\u8ddd\u4eca", None))
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"\u4efb\u52a1\u540d\u79f0", None))
#if QT_CONFIG(accessibility)
        self.taskListView.setAccessibleName(QCoreApplication.translate("MainWindow", u"Codex \u9879\u76ee\u548c\u4efb\u52a1\u5217\u8868", None))
#endif // QT_CONFIG(accessibility)
        self.taskListStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u5c1a\u672a\u52a0\u8f7d\u4efb\u52a1\u5217\u8868", None))
        self.taskRefreshButton.setText(QCoreApplication.translate("MainWindow", u"\u5237\u65b0", None))
#if QT_CONFIG(accessibility)
        self.taskRefreshButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5237\u65b0 Codex \u9879\u76ee\u548c\u4efb\u52a1\u5217\u8868", None))
#endif // QT_CONFIG(accessibility)
        self.taskBackupButton.setText(QCoreApplication.translate("MainWindow", u"\u5907\u4efd", None))
#if QT_CONFIG(accessibility)
        self.taskBackupButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5907\u4efd\u5e76\u5b8c\u6574\u590d\u9a8c\u6240\u9009 Codex \u5bf9\u8bdd", None))
#endif // QT_CONFIG(accessibility)
        self.taskArchiveButton.setText(QCoreApplication.translate("MainWindow", u"\u5f52\u6863", None))
#if QT_CONFIG(accessibility)
        self.taskArchiveButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5f52\u6863\u6216\u53cd\u5f52\u6863\u6240\u9009 Codex \u5bf9\u8bdd", None))
#endif // QT_CONFIG(accessibility)
        self.timelineTitle.setText(QCoreApplication.translate("MainWindow", u"\u65f6\u95f4\u7ebf", None))
        self.timelineHelp.setText(QCoreApplication.translate("MainWindow", u"\u9690\u85cf 0 \u00b7 \u8f93\u5165 0 \u00b7 \u8f93\u51fa 0", None))
#if QT_CONFIG(accessibility)
        self.timelineView.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5bf9\u8bdd turn \u548c item \u65f6\u95f4\u7ebf", None))
#endif // QT_CONFIG(accessibility)
        self.contentTitle.setText(QCoreApplication.translate("MainWindow", u"\u4e0a\u4e0b\u6587", None))
        self.contentTagsButton.setText(QCoreApplication.translate("MainWindow", u"\u663e\u793a\u6807\u7b7e", None))
#if QT_CONFIG(tooltip)
        self.contentTagsButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u663e\u793a\u6216\u9690\u85cf <...> \u534f\u8bae\u6807\u7b7e\uff1b\u9ed8\u8ba4\u9690\u85cf", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.contentTagsButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u663e\u793a\u6216\u9690\u85cf\u534f\u8bae\u6807\u7b7e", None))
#endif // QT_CONFIG(accessibility)
        self.contentMarkdownButton.setText(QCoreApplication.translate("MainWindow", u"Markdown \u9884\u89c8", None))
#if QT_CONFIG(tooltip)
        self.contentMarkdownButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u5207\u6362 Markdown \u6e32\u67d3\u9884\u89c8\uff1b\u5173\u95ed\u540e\u53ef\u7f16\u8f91\u539f\u6587", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.contentMarkdownButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5207\u6362 Markdown \u9884\u89c8", None))
#endif // QT_CONFIG(accessibility)
#if QT_CONFIG(accessibility)
        self.contentBrowser.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6240\u9009\u5bf9\u8bdd\u5185\u5bb9\uff0c\u53ef\u7f16\u8f91\u539f\u6587", None))
#endif // QT_CONFIG(accessibility)
        self.actionTitle.setText(QCoreApplication.translate("MainWindow", u"\u88c1\u526a\u52a8\u4f5c", None))
        self.actionCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"\u4fdd\u7559", None))
        self.actionCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"\u6392\u9664", None))
        self.actionCombo.setItemText(2, QCoreApplication.translate("MainWindow", u"\u6458\u8981", None))
        self.actionCombo.setItemText(3, QCoreApplication.translate("MainWindow", u"\u4fdd\u62a4", None))

#if QT_CONFIG(accessibility)
        self.actionCombo.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6240\u9009\u5185\u5bb9\u7684\u88c1\u526a\u52a8\u4f5c", None))
#endif // QT_CONFIG(accessibility)
        self.riskLabel.setText(QCoreApplication.translate("MainWindow", u"\u98ce\u9669\uff1a\u7b49\u5f85\u9009\u62e9", None))
        self.reasonLabel.setText(QCoreApplication.translate("MainWindow", u"\u5efa\u8bae\u7406\u7531", None))
#if QT_CONFIG(accessibility)
        self.reasonBrowser.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u88c1\u526a\u5efa\u8bae\u7406\u7531", None))
#endif // QT_CONFIG(accessibility)
        self.summaryLabel.setText(QCoreApplication.translate("MainWindow", u"\u6458\u8981\u5185\u5bb9", None))
        self.summaryEdit.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9\u201c\u6458\u8981\u201d\u540e\u7f16\u8f91\u5c06\u6ce8\u5165\u6d3e\u751f\u4efb\u52a1\u7684\u6458\u8981", None))
#if QT_CONFIG(accessibility)
        self.summaryEdit.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6458\u8981\u7f16\u8f91\u5668", None))
#endif // QT_CONFIG(accessibility)
        self.aiConsentCheck.setText(QCoreApplication.translate("MainWindow", u"\u5141\u8bb8\u5185\u5bb9 AI \u7ed9\u51fa\u5efa\u8bae", None))
#if QT_CONFIG(tooltip)
        self.aiConsentCheck.setToolTip(QCoreApplication.translate("MainWindow", u"\u9ed8\u8ba4\u5173\u95ed\uff1b\u542f\u7528\u524d\u5e94\u786e\u8ba4\u5185\u5bb9\u63d0\u4f9b\u65b9\u548c\u6570\u636e\u8fb9\u754c\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.suggestButton.setText(QCoreApplication.translate("MainWindow", u"\u91cd\u65b0\u751f\u6210\u672c\u5730\u5efa\u8bae", None))
        self.tokenLabel.setText(QCoreApplication.translate("MainWindow", u"\u9884\u8ba1\u4e0a\u4e0b\u6587\uff1a\u2014", None))
        self.errorLabel.setText("")
        self.savingProgress.setFormat(QCoreApplication.translate("MainWindow", u"\u9884\u8ba1\u8282\u7701 %p%", None))
#if QT_CONFIG(accessibility)
        self.savingProgress.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u9884\u8ba1\u4e0a\u4e0b\u6587\u8282\u7701\u6bd4\u4f8b", None))
#endif // QT_CONFIG(accessibility)
        self.sensitiveScanButton.setText(QCoreApplication.translate("MainWindow", u"\u654f\u611f\u7b5b\u67e5", None))
#if QT_CONFIG(tooltip)
        self.sensitiveScanButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u4f7f\u7528\u672c\u5730\u89c4\u5219\u7b5b\u67e5\u7591\u4f3c\u654f\u611f\u5185\u5bb9\uff0c\u5e76\u5728\u4e0a\u4e0b\u6587\u4e2d\u4ee5\u7ea2\u5e95\u767d\u5b57\u6807\u8bb0\u5339\u914d\u5185\u5bb9", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.sensitiveScanButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u7b5b\u67e5\u5e76\u6807\u8bb0\u7591\u4f3c\u654f\u611f\u5185\u5bb9", None))
#endif // QT_CONFIG(accessibility)
        self.savePlanButton.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58\u65b9\u6848", None))
#if QT_CONFIG(tooltip)
        self.savePlanButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58\u4e0d\u53ef\u53d8\u88c1\u526a\u65b9\u6848\uff1b\u4e0d\u4f1a\u4fee\u6539\u6216\u6d3e\u751f\u5bf9\u8bdd", None))
#endif // QT_CONFIG(tooltip)
        self.applyButton.setText(QCoreApplication.translate("MainWindow", u"\u6d3e\u751f\u7cbe\u7b80\u4efb\u52a1", None))
        self.cancelButton.setText(QCoreApplication.translate("MainWindow", u"\u5173\u95ed", None))
    # retranslateUi

