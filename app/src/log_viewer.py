"""A modeless, live view of the controller's complete calculation journal."""
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)
from qt_theme import apply_theme


class LogViewer(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window)
        self.setWindowTitle('Полный журнал выполнения')
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setMinimumSize(640, 420)
        screen = self.screen().availableGeometry()
        self.resize(min(1000, screen.width()-32), min(700, screen.height()-40))
        apply_theme(self)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Найти в журнале')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('Поиск в журнале')
        toolbar.addWidget(self.search, 1)
        find = QPushButton('Найти далее', self)
        find.clicked.connect(self.find_next)
        self.search.returnPressed.connect(self.find_next)
        toolbar.addWidget(find)
        copy = QPushButton('Копировать всё', self)
        copy.clicked.connect(self.copy_all)
        toolbar.addWidget(copy)
        layout.addLayout(toolbar)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setPlaceholderText('Здесь появится полный журнал выполнения.')
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(10)
        self.text.setFont(font)
        self.text.setPlainText(controller.logs)
        self.text.moveCursor(QTextCursor.End)
        layout.addWidget(self.text, 1)
        self.match_status = QLabel('', self)
        layout.addWidget(self.match_status)
        controller.log_changed.connect(self.update_log)

    def update_log(self, message):
        data = json.loads(message)
        bar = self.text.verticalScrollBar()
        follow = bar.value() >= bar.maximum()-1
        position = bar.value()
        if 'replace' in data:
            self.text.setPlainText(data['replace'])
        else:
            cursor = QTextCursor(self.text.document())
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(data.get('append', ''))
        bar.setValue(bar.maximum() if follow else position)

    def find_next(self):
        term = self.search.text()
        if not term:
            self.match_status.clear()
            return
        found = self.text.find(term)
        if not found:
            self.text.moveCursor(QTextCursor.Start)
            found = self.text.find(term)
        self.match_status.setText('' if found else 'Совпадений нет')

    def copy_all(self):
        QApplication.clipboard().setText(self.text.toPlainText())
