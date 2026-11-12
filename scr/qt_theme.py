"""Shared graphite controls for the native dialogs alongside the HTML UI."""
from PySide6.QtGui import QFont


STYLE = '''
    QMainWindow, QDialog, QMessageBox, QFileDialog { background: #252525; color: #eeeeee; }
    QLabel { color: #eeeeee; }
    QPushButton {
        background: #333333; color: #eeeeee; border: 1px solid #424242;
        border-radius: 8px; min-height: 22px; padding: 6px 12px;
    }
    QPushButton:hover { background: #424242; }
    QPushButton:pressed { background: #4a4a4a; }
    QPushButton:disabled { color: #858585; background: #292929; }
    QPushButton:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #b4b4b4; }
    QLineEdit, QComboBox, QPlainTextEdit, QListView, QTreeView {
        background: #2b2b2b; color: #eeeeee; border: 1px solid #424242;
        border-radius: 8px; padding: 6px; selection-background-color: #4a4a4a;
        selection-color: #eeeeee;
    }
    QComboBox QAbstractItemView {
        background: #2c2c2c; color: #eeeeee; border: 1px solid #454545;
        selection-background-color: #3c3c3c; selection-color: #eeeeee; padding: 4px;
    }
    QComboBox QAbstractItemView::item { min-height: 28px; padding: 3px 7px; }
'''


def apply_theme(widget):
    font = QFont('Segoe UI')
    font.setPixelSize(14)
    widget.setFont(font)
    widget.setStyleSheet(STYLE)
