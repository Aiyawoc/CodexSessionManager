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
    QPushButton, QSizePolicy, QSpacerItem, QSplitter,
    QTextBrowser, QToolButton, QTreeView, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

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

        self.backupRailButton = QToolButton(self.toolRail)
        self.backupRailButton.setObjectName(u"backupRailButton")
        self.backupRailButton.setEnabled(False)
        self.backupRailButton.setAutoRaise(True)
        self.backupRailButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.toolRailLayout.addWidget(self.backupRailButton)

        self.cleanupRailButton = QToolButton(self.toolRail)
        self.cleanupRailButton.setObjectName(u"cleanupRailButton")
        self.cleanupRailButton.setEnabled(False)
        self.cleanupRailButton.setAutoRaise(True)
        self.cleanupRailButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.toolRailLayout.addWidget(self.cleanupRailButton)

        self.auditRailButton = QToolButton(self.toolRail)
        self.auditRailButton.setObjectName(u"auditRailButton")
        self.auditRailButton.setEnabled(False)
        self.auditRailButton.setAutoRaise(True)
        self.auditRailButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.toolRailLayout.addWidget(self.auditRailButton)

        self.toolRailSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.toolRailLayout.addItem(self.toolRailSpacer)


        self.workspaceLayout.addWidget(self.toolRail)

        self.mainSplitter = QSplitter(self.centralwidget)
        self.mainSplitter.setObjectName(u"mainSplitter")
        self.mainSplitter.setOrientation(Qt.Orientation.Horizontal)
        self.mainSplitter.setHandleWidth(8)
        self.mainSplitter.setChildrenCollapsible(False)
        self.taskPane = QWidget(self.mainSplitter)
        self.taskPane.setObjectName(u"taskPane")
        self.taskPane.setMinimumSize(QSize(400, 0))
        self.taskLayout = QVBoxLayout(self.taskPane)
        self.taskLayout.setObjectName(u"taskLayout")
        self.taskLayout.setContentsMargins(0, 0, 8, 0)
        self.taskHeaderLayout = QHBoxLayout()
        self.taskHeaderLayout.setSpacing(8)
        self.taskHeaderLayout.setObjectName(u"taskHeaderLayout")
        self.taskTitle = QLabel(self.taskPane)
        self.taskTitle.setObjectName(u"taskTitle")
        font = QFont()
        font.setPointSize(15)
        self.taskTitle.setFont(font)

        self.taskHeaderLayout.addWidget(self.taskTitle)

        self.taskHeaderSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.taskHeaderLayout.addItem(self.taskHeaderSpacer)

        self.taskPaneCollapseButton = QToolButton(self.taskPane)
        self.taskPaneCollapseButton.setObjectName(u"taskPaneCollapseButton")
        self.taskPaneCollapseButton.setAutoRaise(True)
        self.taskPaneCollapseButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.taskHeaderLayout.addWidget(self.taskPaneCollapseButton)


        self.taskLayout.addLayout(self.taskHeaderLayout)

        self.taskHelp = QLabel(self.taskPane)
        self.taskHelp.setObjectName(u"taskHelp")
        self.taskHelp.setWordWrap(True)

        self.taskLayout.addWidget(self.taskHelp)

        self.threadIdLabel = QLabel(self.taskPane)
        self.threadIdLabel.setObjectName(u"threadIdLabel")

        self.taskLayout.addWidget(self.threadIdLabel)

        self.manualTaskLayout = QHBoxLayout()
        self.manualTaskLayout.setSpacing(6)
        self.manualTaskLayout.setObjectName(u"manualTaskLayout")
        self.threadIdEdit = QLineEdit(self.taskPane)
        self.threadIdEdit.setObjectName(u"threadIdEdit")

        self.manualTaskLayout.addWidget(self.threadIdEdit)

        self.loadButton = QPushButton(self.taskPane)
        self.loadButton.setObjectName(u"loadButton")

        self.manualTaskLayout.addWidget(self.loadButton)


        self.taskLayout.addLayout(self.manualTaskLayout)

        self.taskContextStatusLabel = QLabel(self.taskPane)
        self.taskContextStatusLabel.setObjectName(u"taskContextStatusLabel")
        self.taskContextStatusLabel.setMaximumSize(QSize(16777215, 28))
        self.taskContextStatusLabel.setWordWrap(False)

        self.taskLayout.addWidget(self.taskContextStatusLabel)

        self.taskSearchEdit = QLineEdit(self.taskPane)
        self.taskSearchEdit.setObjectName(u"taskSearchEdit")

        self.taskLayout.addWidget(self.taskSearchEdit)

        self.taskListView = QTreeWidget(self.taskPane)
        self.taskListView.setObjectName(u"taskListView")
        self.taskListView.setAlternatingRowColors(True)
        self.taskListView.setUniformRowHeights(True)
        self.taskListView.setRootIsDecorated(True)
        self.taskListView.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.taskListView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.taskLayout.addWidget(self.taskListView)

        self.taskListStatusLabel = QLabel(self.taskPane)
        self.taskListStatusLabel.setObjectName(u"taskListStatusLabel")
        self.taskListStatusLabel.setWordWrap(True)

        self.taskLayout.addWidget(self.taskListStatusLabel)

        self.taskRefreshButton = QPushButton(self.taskPane)
        self.taskRefreshButton.setObjectName(u"taskRefreshButton")

        self.taskLayout.addWidget(self.taskRefreshButton)

        self.mainSplitter.addWidget(self.taskPane)
        self.timelinePane = QWidget(self.mainSplitter)
        self.timelinePane.setObjectName(u"timelinePane")
        self.timelinePane.setMinimumSize(QSize(300, 0))
        self.timelineLayout = QVBoxLayout(self.timelinePane)
        self.timelineLayout.setObjectName(u"timelineLayout")
        self.timelineLayout.setContentsMargins(0, 0, 0, 0)
        self.timelineTitle = QLabel(self.timelinePane)
        self.timelineTitle.setObjectName(u"timelineTitle")
        self.timelineTitle.setFont(font)

        self.timelineLayout.addWidget(self.timelineTitle)

        self.timelineHelp = QLabel(self.timelinePane)
        self.timelineHelp.setObjectName(u"timelineHelp")
        self.timelineHelp.setWordWrap(True)

        self.timelineLayout.addWidget(self.timelineHelp)

        self.timelineView = QTreeView(self.timelinePane)
        self.timelineView.setObjectName(u"timelineView")
        self.timelineView.setAlternatingRowColors(True)
        self.timelineView.setUniformRowHeights(True)
        self.timelineView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.timelineLayout.addWidget(self.timelineView)

        self.mainSplitter.addWidget(self.timelinePane)
        self.contentPane = QWidget(self.mainSplitter)
        self.contentPane.setObjectName(u"contentPane")
        self.contentPane.setMinimumSize(QSize(420, 0))
        self.contentLayout = QVBoxLayout(self.contentPane)
        self.contentLayout.setObjectName(u"contentLayout")
        self.contentLayout.setContentsMargins(8, 0, 8, 0)
        self.contentTitle = QLabel(self.contentPane)
        self.contentTitle.setObjectName(u"contentTitle")
        self.contentTitle.setFont(font)

        self.contentLayout.addWidget(self.contentTitle)

        self.contentMetaLabel = QLabel(self.contentPane)
        self.contentMetaLabel.setObjectName(u"contentMetaLabel")
        self.contentMetaLabel.setWordWrap(True)

        self.contentLayout.addWidget(self.contentMetaLabel)

        self.contentBrowser = QTextBrowser(self.contentPane)
        self.contentBrowser.setObjectName(u"contentBrowser")
        self.contentBrowser.setOpenExternalLinks(False)

        self.contentLayout.addWidget(self.contentBrowser)

        self.mainSplitter.addWidget(self.contentPane)
        self.actionPane = QWidget(self.mainSplitter)
        self.actionPane.setObjectName(u"actionPane")
        self.actionPane.setMinimumSize(QSize(290, 0))
        self.actionLayout = QVBoxLayout(self.actionPane)
        self.actionLayout.setObjectName(u"actionLayout")
        self.actionLayout.setContentsMargins(0, 0, 0, 0)
        self.actionTitle = QLabel(self.actionPane)
        self.actionTitle.setObjectName(u"actionTitle")
        self.actionTitle.setFont(font)

        self.actionLayout.addWidget(self.actionTitle)

        self.actionCombo = QComboBox(self.actionPane)
        self.actionCombo.addItem("")
        self.actionCombo.addItem("")
        self.actionCombo.addItem("")
        self.actionCombo.addItem("")
        self.actionCombo.setObjectName(u"actionCombo")

        self.actionLayout.addWidget(self.actionCombo)

        self.riskLabel = QLabel(self.actionPane)
        self.riskLabel.setObjectName(u"riskLabel")
        self.riskLabel.setWordWrap(True)

        self.actionLayout.addWidget(self.riskLabel)

        self.reasonLabel = QLabel(self.actionPane)
        self.reasonLabel.setObjectName(u"reasonLabel")

        self.actionLayout.addWidget(self.reasonLabel)

        self.reasonBrowser = QTextBrowser(self.actionPane)
        self.reasonBrowser.setObjectName(u"reasonBrowser")
        self.reasonBrowser.setMaximumSize(QSize(16777215, 110))

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
        self.footerFrame.setMaximumSize(QSize(16777215, 76))
        self.footerLayout = QVBoxLayout(self.footerFrame)
        self.footerLayout.setSpacing(4)
        self.footerLayout.setObjectName(u"footerLayout")
        self.footerMainLayout = QHBoxLayout()
        self.footerMainLayout.setSpacing(8)
        self.footerMainLayout.setObjectName(u"footerMainLayout")
        self.tokenLabel = QLabel(self.footerFrame)
        self.tokenLabel.setObjectName(u"tokenLabel")
        self.tokenLabel.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignVCenter)

        self.footerMainLayout.addWidget(self.tokenLabel)

        self.savingProgress = QProgressBar(self.footerFrame)
        self.savingProgress.setObjectName(u"savingProgress")
        self.savingProgress.setMinimum(0)
        self.savingProgress.setMaximum(100)
        self.savingProgress.setValue(0)

        self.footerMainLayout.addWidget(self.savingProgress)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setSpacing(8)
        self.buttonLayout.setObjectName(u"buttonLayout")
        self.cancelButton = QPushButton(self.footerFrame)
        self.cancelButton.setObjectName(u"cancelButton")

        self.buttonLayout.addWidget(self.cancelButton)

        self.savePlanButton = QPushButton(self.footerFrame)
        self.savePlanButton.setObjectName(u"savePlanButton")
        self.savePlanButton.setEnabled(False)

        self.buttonLayout.addWidget(self.savePlanButton)

        self.applyButton = QPushButton(self.footerFrame)
        self.applyButton.setObjectName(u"applyButton")
        self.applyButton.setEnabled(False)

        self.buttonLayout.addWidget(self.applyButton)


        self.footerMainLayout.addLayout(self.buttonLayout)


        self.footerLayout.addLayout(self.footerMainLayout)

        self.errorLabel = QLabel(self.footerFrame)
        self.errorLabel.setObjectName(u"errorLabel")
        self.errorLabel.setMaximumSize(QSize(16777215, 32))
        self.errorLabel.setWordWrap(True)

        self.footerLayout.addWidget(self.errorLabel)


        self.rootLayout.addWidget(self.footerFrame)

        MainWindow.setCentralWidget(self.centralwidget)
#if QT_CONFIG(shortcut)
        self.threadIdLabel.setBuddy(self.threadIdEdit)
        self.summaryLabel.setBuddy(self.summaryEdit)
#endif // QT_CONFIG(shortcut)
        QWidget.setTabOrder(self.threadIdEdit, self.loadButton)
        QWidget.setTabOrder(self.loadButton, self.taskSearchEdit)
        QWidget.setTabOrder(self.taskSearchEdit, self.taskListView)
        QWidget.setTabOrder(self.taskListView, self.taskRefreshButton)
        QWidget.setTabOrder(self.taskRefreshButton, self.taskPaneCollapseButton)
        QWidget.setTabOrder(self.taskPaneCollapseButton, self.timelineView)
        QWidget.setTabOrder(self.timelineView, self.contentBrowser)
        QWidget.setTabOrder(self.contentBrowser, self.actionCombo)
        QWidget.setTabOrder(self.actionCombo, self.reasonBrowser)
        QWidget.setTabOrder(self.reasonBrowser, self.summaryEdit)
        QWidget.setTabOrder(self.summaryEdit, self.aiConsentCheck)
        QWidget.setTabOrder(self.aiConsentCheck, self.suggestButton)
        QWidget.setTabOrder(self.suggestButton, self.cancelButton)
        QWidget.setTabOrder(self.cancelButton, self.savePlanButton)
        QWidget.setTabOrder(self.savePlanButton, self.applyButton)

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
        self.projectTaskRailButton.setText(QCoreApplication.translate("MainWindow", u"\u9879\u76ee", None))
#if QT_CONFIG(tooltip)
        self.projectTaskRailButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u4e0e\u4efb\u52a1", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.projectTaskRailButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u4e0e\u4efb\u52a1", None))
#endif // QT_CONFIG(accessibility)
        self.backupRailButton.setText(QCoreApplication.translate("MainWindow", u"\u5907\u4efd", None))
#if QT_CONFIG(tooltip)
        self.backupRailButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u5907\u4efd\u4e0e\u6062\u590d\uff08\u9884\u89c8\uff09", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.backupRailButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5907\u4efd\u4e0e\u6062\u590d\uff0c\u9884\u89c8\u529f\u80fd", None))
#endif // QT_CONFIG(accessibility)
        self.cleanupRailButton.setText(QCoreApplication.translate("MainWindow", u"\u6e05\u7406", None))
#if QT_CONFIG(tooltip)
        self.cleanupRailButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u6e05\u7406\u4e0e\u5f52\u6863\uff08\u9884\u89c8\uff09", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.cleanupRailButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6e05\u7406\u4e0e\u5f52\u6863\uff0c\u9884\u89c8\u529f\u80fd", None))
#endif // QT_CONFIG(accessibility)
        self.auditRailButton.setText(QCoreApplication.translate("MainWindow", u"\u5ba1\u8ba1", None))
#if QT_CONFIG(tooltip)
        self.auditRailButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u5ba1\u8ba1\u8bb0\u5f55\uff08\u9884\u89c8\uff09", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.auditRailButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5ba1\u8ba1\u8bb0\u5f55\uff0c\u9884\u89c8\u529f\u80fd", None))
#endif // QT_CONFIG(accessibility)
        self.taskTitle.setText(QCoreApplication.translate("MainWindow", u"\u9879\u76ee\u4e0e\u4efb\u52a1", None))
        self.taskPaneCollapseButton.setText(QCoreApplication.translate("MainWindow", u"\u6536\u8d77", None))
#if QT_CONFIG(tooltip)
        self.taskPaneCollapseButton.setToolTip(QCoreApplication.translate("MainWindow", u"\u6536\u8d77\u9879\u76ee\u4e0e\u4efb\u52a1\u9762\u677f", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.taskPaneCollapseButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6536\u8d77\u9879\u76ee\u4e0e\u4efb\u52a1\u9762\u677f", None))
#endif // QT_CONFIG(accessibility)
        self.taskHelp.setText(QCoreApplication.translate("MainWindow", u"\u6309\u9879\u76ee\u5206\u7ec4\uff1b\u9009\u62e9\u4efb\u52a1\u540e\u76f4\u63a5\u52a0\u8f7d\u4e0a\u4e0b\u6587\u3002", None))
        self.threadIdLabel.setText(QCoreApplication.translate("MainWindow", u"\u624b\u52a8\u8f93\u5165\u4efb\u52a1 ID", None))
        self.threadIdEdit.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u8f93\u5165 Codex \u4efb\u52a1 ID", None))
#if QT_CONFIG(accessibility)
        self.threadIdEdit.setAccessibleName(QCoreApplication.translate("MainWindow", u"Codex \u4efb\u52a1 ID", None))
#endif // QT_CONFIG(accessibility)
        self.loadButton.setText(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d", None))
#if QT_CONFIG(accessibility)
        self.loadButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d Codex \u4efb\u52a1", None))
#endif // QT_CONFIG(accessibility)
        self.taskContextStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u5c1a\u672a\u52a0\u8f7d\u4efb\u52a1", None))
#if QT_CONFIG(tooltip)
        self.taskContextStatusLabel.setToolTip(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u6b63\u5728\u5ba1\u67e5\u7684\u4efb\u52a1\u72b6\u6001", None))
#endif // QT_CONFIG(tooltip)
        self.taskSearchEdit.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u641c\u7d22\u9879\u76ee\u3001\u4efb\u52a1\u540d\u79f0\u6216 ID", None))
#if QT_CONFIG(accessibility)
        self.taskSearchEdit.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u641c\u7d22 Codex \u9879\u76ee\u548c\u4efb\u52a1", None))
#endif // QT_CONFIG(accessibility)
        ___qtreewidgetitem = self.taskListView.headerItem()
        ___qtreewidgetitem.setText(2, QCoreApplication.translate("MainWindow", u"\u72b6\u6001", None))
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("MainWindow", u"\u4efb\u52a1 ID", None))
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"\u4efb\u52a1\u540d\u79f0", None))
#if QT_CONFIG(accessibility)
        self.taskListView.setAccessibleName(QCoreApplication.translate("MainWindow", u"Codex \u9879\u76ee\u548c\u4efb\u52a1\u5217\u8868", None))
#endif // QT_CONFIG(accessibility)
        self.taskListStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u5c1a\u672a\u52a0\u8f7d\u4efb\u52a1\u5217\u8868", None))
        self.taskRefreshButton.setText(QCoreApplication.translate("MainWindow", u"\u5237\u65b0\u4efb\u52a1\u5217\u8868", None))
#if QT_CONFIG(accessibility)
        self.taskRefreshButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5237\u65b0 Codex \u9879\u76ee\u548c\u4efb\u52a1\u5217\u8868", None))
#endif // QT_CONFIG(accessibility)
        self.timelineTitle.setText(QCoreApplication.translate("MainWindow", u"\u65f6\u95f4\u7ebf", None))
        self.timelineHelp.setText(QCoreApplication.translate("MainWindow", u"\u9ed8\u8ba4\u6309 turn \u64cd\u4f5c\uff1b\u5c55\u5f00\u540e\u53ef\u67e5\u770b item\u3002", None))
#if QT_CONFIG(accessibility)
        self.timelineView.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u5bf9\u8bdd turn \u548c item \u65f6\u95f4\u7ebf", None))
#endif // QT_CONFIG(accessibility)
        self.contentTitle.setText(QCoreApplication.translate("MainWindow", u"\u539f\u6587\u4e0e\u4f9d\u8d56", None))
        self.contentMetaLabel.setText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9\u5de6\u4fa7 turn \u6216 item \u67e5\u770b\u8be6\u60c5", None))
#if QT_CONFIG(accessibility)
        self.contentBrowser.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u6240\u9009\u5bf9\u8bdd\u5185\u5bb9", None))
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
        self.savingProgress.setFormat(QCoreApplication.translate("MainWindow", u"\u9884\u8ba1\u8282\u7701 %p%", None))
#if QT_CONFIG(accessibility)
        self.savingProgress.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u9884\u8ba1\u4e0a\u4e0b\u6587\u8282\u7701\u6bd4\u4f8b", None))
#endif // QT_CONFIG(accessibility)
        self.cancelButton.setText(QCoreApplication.translate("MainWindow", u"\u5173\u95ed", None))
        self.savePlanButton.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58 TrimPlan", None))
        self.applyButton.setText(QCoreApplication.translate("MainWindow", u"\u521b\u5efa\u6d3e\u751f\u7cbe\u7b80\u4efb\u52a1", None))
        self.errorLabel.setText("")
    # retranslateUi

