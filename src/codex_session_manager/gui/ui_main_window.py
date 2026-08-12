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
    QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpacerItem,
    QSplitter, QTextBrowser, QTreeView, QVBoxLayout,
    QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1280, 800)
        MainWindow.setMinimumSize(QSize(960, 640))
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.rootLayout = QVBoxLayout(self.centralwidget)
        self.rootLayout.setSpacing(12)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(16, 16, 16, 12)
        self.heroFrame = QFrame(self.centralwidget)
        self.heroFrame.setObjectName(u"heroFrame")
        self.heroFrame.setFrameShape(QFrame.Shape.StyledPanel)
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

        self.sourceFrame = QFrame(self.centralwidget)
        self.sourceFrame.setObjectName(u"sourceFrame")
        self.sourceFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.sourceLayout = QHBoxLayout(self.sourceFrame)
        self.sourceLayout.setObjectName(u"sourceLayout")
        self.threadIdLabel = QLabel(self.sourceFrame)
        self.threadIdLabel.setObjectName(u"threadIdLabel")

        self.sourceLayout.addWidget(self.threadIdLabel)

        self.threadIdEdit = QLineEdit(self.sourceFrame)
        self.threadIdEdit.setObjectName(u"threadIdEdit")

        self.sourceLayout.addWidget(self.threadIdEdit)

        self.loadButton = QPushButton(self.sourceFrame)
        self.loadButton.setObjectName(u"loadButton")

        self.sourceLayout.addWidget(self.loadButton)

        self.sourceStatusLabel = QLabel(self.sourceFrame)
        self.sourceStatusLabel.setObjectName(u"sourceStatusLabel")
        self.sourceStatusLabel.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.sourceLayout.addWidget(self.sourceStatusLabel)


        self.rootLayout.addWidget(self.sourceFrame)

        self.mainSplitter = QSplitter(self.centralwidget)
        self.mainSplitter.setObjectName(u"mainSplitter")
        self.mainSplitter.setOrientation(Qt.Orientation.Horizontal)
        self.mainSplitter.setHandleWidth(8)
        self.mainSplitter.setChildrenCollapsible(False)
        self.timelinePane = QWidget(self.mainSplitter)
        self.timelinePane.setObjectName(u"timelinePane")
        self.timelinePane.setMinimumSize(QSize(260, 0))
        self.timelineLayout = QVBoxLayout(self.timelinePane)
        self.timelineLayout.setObjectName(u"timelineLayout")
        self.timelineLayout.setContentsMargins(0, 0, 0, 0)
        self.timelineTitle = QLabel(self.timelinePane)
        self.timelineTitle.setObjectName(u"timelineTitle")
        font = QFont()
        font.setPointSize(15)
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
        self.contentPane.setMinimumSize(QSize(380, 0))
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
        self.actionPane.setMinimumSize(QSize(260, 0))
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

        self.rootLayout.addWidget(self.mainSplitter)

        self.footerFrame = QFrame(self.centralwidget)
        self.footerFrame.setObjectName(u"footerFrame")
        self.footerFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.footerLayout = QGridLayout(self.footerFrame)
        self.footerLayout.setObjectName(u"footerLayout")
        self.tokenLabel = QLabel(self.footerFrame)
        self.tokenLabel.setObjectName(u"tokenLabel")

        self.footerLayout.addWidget(self.tokenLabel, 0, 0, 1, 1)

        self.savingProgress = QProgressBar(self.footerFrame)
        self.savingProgress.setObjectName(u"savingProgress")
        self.savingProgress.setMinimum(0)
        self.savingProgress.setMaximum(100)
        self.savingProgress.setValue(0)

        self.footerLayout.addWidget(self.savingProgress, 0, 1, 1, 1)

        self.errorLabel = QLabel(self.footerFrame)
        self.errorLabel.setObjectName(u"errorLabel")
        self.errorLabel.setWordWrap(True)

        self.footerLayout.addWidget(self.errorLabel, 1, 0, 1, 2)

        self.buttonLayout = QHBoxLayout()
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


        self.footerLayout.addLayout(self.buttonLayout, 0, 2, 2, 1)


        self.rootLayout.addWidget(self.footerFrame)

        MainWindow.setCentralWidget(self.centralwidget)
#if QT_CONFIG(shortcut)
        self.threadIdLabel.setBuddy(self.threadIdEdit)
        self.summaryLabel.setBuddy(self.summaryEdit)
#endif // QT_CONFIG(shortcut)
        QWidget.setTabOrder(self.threadIdEdit, self.loadButton)
        QWidget.setTabOrder(self.loadButton, self.timelineView)
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
        self.threadIdLabel.setText(QCoreApplication.translate("MainWindow", u"\u4efb\u52a1 ID", None))
        self.threadIdEdit.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u8f93\u5165 Codex \u4efb\u52a1 ID", None))
#if QT_CONFIG(accessibility)
        self.threadIdEdit.setAccessibleName(QCoreApplication.translate("MainWindow", u"Codex \u4efb\u52a1 ID", None))
#endif // QT_CONFIG(accessibility)
        self.loadButton.setText(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d\u4efb\u52a1", None))
#if QT_CONFIG(accessibility)
        self.loadButton.setAccessibleName(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d Codex \u4efb\u52a1", None))
#endif // QT_CONFIG(accessibility)
        self.sourceStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u5c1a\u672a\u52a0\u8f7d", None))
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
        self.errorLabel.setText("")
        self.cancelButton.setText(QCoreApplication.translate("MainWindow", u"\u5173\u95ed", None))
        self.savePlanButton.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58 TrimPlan", None))
        self.applyButton.setText(QCoreApplication.translate("MainWindow", u"\u521b\u5efa\u6d3e\u751f\u7cbe\u7b80\u4efb\u52a1", None))
    # retranslateUi

