"""Десктопное окно Qt с локальным HTML/CSS-интерфейсом."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from desktop_controller import DesktopController


UI_DIR = Path(__file__).resolve().parent / "desktop_ui"
APP_ICON = UI_DIR / "app-icon.ico"


class LocalResources(QWebEngineUrlRequestInterceptor):
    """У оболочки нет сетевых ресурсов; доступны только собственные файлы UI."""
    def interceptRequest(self, request):
        url = request.requestUrl()
        allowed = url.scheme() in {"qrc", "data", "about"}
        if url.isLocalFile():
            allowed = Path(url.toLocalFile()).resolve().is_relative_to(UI_DIR.resolve())
        request.block(not allowed)


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _kind, is_main_frame):
        if not is_main_frame:
            return False
        return url.isLocalFile() and Path(url.toLocalFile()).resolve() == UI_DIR / "index.html"


class DesktopWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Параметрический расчёт ГТУ")
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.setMinimumSize(900, 600)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1200, available.width() - 32), min(800, available.height() - 40))
        self.setStyleSheet("""
            QMainWindow, QMessageBox, QFileDialog { background: #252525; color: #eeeeee; }
            QLabel { color: #eeeeee; font-size: 14px; }
            QMessageBox QPushButton, QFileDialog QPushButton {
                background: #333333; color: #eeeeee; border: 1px solid #424242;
                border-radius: 8px; min-height: 24px; min-width: 70px; padding: 6px 12px;
            }
            QMessageBox QPushButton:hover, QFileDialog QPushButton:hover { background: #424242; }
            QLineEdit, QComboBox, QListView, QTreeView {
                background: #2b2b2b; color: #eeeeee; border: 1px solid #424242;
                border-radius: 6px; padding: 6px;
            }
        """)
        self.view = QWebEngineView(self)
        self.page = LocalPage(self.view)
        self.page.setBackgroundColor(QColor("#252525"))
        self.interceptor = LocalResources(self.page)
        self.page.profile().setUrlRequestInterceptor(self.interceptor)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)
        self.controller = DesktopController(self)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("backend", self.controller)
        self.page.setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(str(UI_DIR / "index.html")))

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            # Тёмная системная строка заголовка только нашего окна.
            try:
                value = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    int(self.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
            except (AttributeError, OSError):
                pass

    def closeEvent(self, event):
        self.controller.closed = True
        if self.controller.dialog is not None:
            self.controller.dialog.loop.quit()
        if self.controller.period_request is not None:
            self.controller.period_request["event"].set()
        super().closeEvent(event)


def main():
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Параметрический расчёт ГТУ")
    application.setWindowIcon(QIcon(str(APP_ICON)))
    application.setFont(QFont("Segoe UI", 10))
    application.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    window = DesktopWindow()
    window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
