# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'precompact_prompt.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

class Ui_PrecompactPrompt(object):
    def setupUi(self, PrecompactPrompt):
        if not PrecompactPrompt.objectName():
            PrecompactPrompt.setObjectName(u"PrecompactPrompt")
        PrecompactPrompt.resize(520, 230)
        PrecompactPrompt.setMinimumSize(QSize(460, 210))
        PrecompactPrompt.setModal(True)
        self.rootLayout = QVBoxLayout(PrecompactPrompt)
        self.rootLayout.setSpacing(14)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(24, 24, 24, 20)
        self.titleLabel = QLabel(PrecompactPrompt)
        self.titleLabel.setObjectName(u"titleLabel")
        font = QFont()
        font.setPointSize(17)
        self.titleLabel.setFont(font)

        self.rootLayout.addWidget(self.titleLabel)

        self.messageLabel = QLabel(PrecompactPrompt)
        self.messageLabel.setObjectName(u"messageLabel")
        self.messageLabel.setWordWrap(True)

        self.rootLayout.addWidget(self.messageLabel)

        self.countdownProgress = QProgressBar(PrecompactPrompt)
        self.countdownProgress.setObjectName(u"countdownProgress")
        self.countdownProgress.setMinimum(0)
        self.countdownProgress.setMaximum(15)
        self.countdownProgress.setValue(15)

        self.rootLayout.addWidget(self.countdownProgress)

        self.verticalSpacer = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.rootLayout.addItem(self.verticalSpacer)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setObjectName(u"buttonLayout")
        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.buttonLayout.addItem(self.horizontalSpacer)

        self.reviewButton = QPushButton(PrecompactPrompt)
        self.reviewButton.setObjectName(u"reviewButton")

        self.buttonLayout.addWidget(self.reviewButton)

        self.continueButton = QPushButton(PrecompactPrompt)
        self.continueButton.setObjectName(u"continueButton")

        self.buttonLayout.addWidget(self.continueButton)


        self.rootLayout.addLayout(self.buttonLayout)

        QWidget.setTabOrder(self.reviewButton, self.continueButton)

        self.retranslateUi(PrecompactPrompt)

        self.continueButton.setDefault(True)


        QMetaObject.connectSlotsByName(PrecompactPrompt)
    # setupUi

    def retranslateUi(self, PrecompactPrompt):
        PrecompactPrompt.setWindowTitle(QCoreApplication.translate("PrecompactPrompt", u"\u538b\u7f29\u524d\u68c0\u67e5\u4e0a\u4e0b\u6587", None))
        self.titleLabel.setText(QCoreApplication.translate("PrecompactPrompt", u"Codex \u5373\u5c06\u538b\u7f29\u5f53\u524d\u4e0a\u4e0b\u6587", None))
        self.messageLabel.setText(QCoreApplication.translate("PrecompactPrompt", u"\u53ef\u5148\u5ba1\u67e5\u5e76\u4fdd\u5b58 TrimPlan\uff0c\u7a0d\u540e\u521b\u5efa\u6d3e\u751f\u7cbe\u7b80\u4efb\u52a1\uff1b\u5173\u95ed\u6216\u8d85\u65f6\u4f1a\u7ee7\u7eed Codex \u539f\u751f\u538b\u7f29\u3002", None))
        self.countdownProgress.setFormat(QCoreApplication.translate("PrecompactPrompt", u"\u5269\u4f59 %v \u79d2", None))
        self.reviewButton.setText(QCoreApplication.translate("PrecompactPrompt", u"\u5ba1\u67e5\u4e0a\u4e0b\u6587\u2026", None))
        self.continueButton.setText(QCoreApplication.translate("PrecompactPrompt", u"\u7ee7\u7eed\u539f\u751f\u538b\u7f29", None))
#if QT_CONFIG(accessibility)
        self.continueButton.setAccessibleName(QCoreApplication.translate("PrecompactPrompt", u"\u7ee7\u7eed Codex \u539f\u751f\u538b\u7f29", None))
#endif // QT_CONFIG(accessibility)
    # retranslateUi

