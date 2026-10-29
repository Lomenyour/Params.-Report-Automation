"""Ранняя заставка отдельно от загрузки расчётных зависимостей."""
from __future__ import annotations

import sys
import traceback
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_resources import APP_ICON
from startup_splash import StartupSplash


def splash_command():
    if getattr(sys, "frozen", False):
        return sys.executable, []
    return sys.executable, [__file__]


class SplashProcess(QObject):
    """Собственный короткоживущий процесс; канал локальный, без TCP и файлов."""
    visible = Signal()
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server, self.process = QLocalServer(self), QProcess(self)
        self.socket = None
        self.closing = self.announced = False
        self.buffer = b""
        self.name = f"GTU-startup-{uuid4().hex}"
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)

    def start(self):
        if not self.server.listen(self.name):
            self.failed.emit(self.server.errorString())
            return
        program, arguments = splash_command()
        self.process.start(program, [*arguments, "--startup-splash", self.name])

    @Slot()
    def _connected(self):
        self.socket = self.server.nextPendingConnection()
        self.server.close()
        self.socket.readyRead.connect(self._read)
        self._read()

    @Slot()
    def _read(self):
        self.buffer += bytes(self.socket.readAll())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if line == b"visible" and not self.announced and not self.closing:
                self.announced = True
                self.visible.emit()

    @Slot(QProcess.ProcessError)
    def _process_error(self, _error):
        if not self.closing:
            self.failed.emit(self.process.errorString())

    @Slot(int, QProcess.ExitStatus)
    def _process_finished(self, code, status):
        if not self.closing:
            if code == 0 and status == QProcess.ExitStatus.NormalExit:
                self.cancelled.emit()
            else:
                self.failed.emit("Не удалось запустить окно загрузки.")

    def close(self):
        self.closing = True
        self.server.close()
        if self.socket is not None and self.socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
            self.socket.write(b"close\n")
            self.socket.flush()

    def shutdown(self):
        self.close()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if not self.process.waitForFinished(1000):
                self.process.terminate()
                if not self.process.waitForFinished(1000):
                    self.process.kill()
                    self.process.waitForFinished(1000)


class StartupCoordinator(QObject):
    window_ready = Signal()

    def __init__(self, application):
        super().__init__(application)
        self.application = application
        self.main_window = None
        self.page_loaded = self.completed = self.cancelled = False
        self.splash = SplashProcess(self)
        self.splash.visible.connect(self._load_window)
        self.splash.failed.connect(self._failed)
        self.splash.cancelled.connect(self._cancelled)
        application.aboutToQuit.connect(self.splash.shutdown)

    def start(self):
        self.application.setQuitOnLastWindowClosed(False)
        self.splash.start()

    @Slot()
    def _load_window(self):
        if self.cancelled or self.completed:
            return
        try:
            # Заставка уже отрисована другим процессом. Здесь выполняются
            # прежние импорты и создаётся контроллер в основном GUI-потоке.
            from desktop_app import DesktopWindow
            self.main_window = DesktopWindow()
            self.main_window.page.loadFinished.connect(self._page_loaded)
            self.main_window.controller.state_changed.connect(self._state_changed)
        except Exception:
            self._failed(traceback.format_exc())

    @Slot(bool)
    def _page_loaded(self, ok):
        if not ok:
            self._failed("Не удалось загрузить локальный интерфейс приложения.")
            return
        self.page_loaded = True
        self._maybe_finish()

    @Slot(str)
    def _state_changed(self, _state):
        self._maybe_finish()

    def _maybe_finish(self):
        if self.completed or self.cancelled or not self.page_loaded:
            return
        if self.main_window is None or not self.main_window.controller.ready:
            return
        self.completed = True
        self.main_window.show()
        self.application.setQuitOnLastWindowClosed(True)
        QTimer.singleShot(0, self.splash.close)
        self.window_ready.emit()

    @Slot()
    def _cancelled(self):
        if self.completed:
            return
        self.cancelled = True
        if self.main_window is not None:
            self.main_window.close()
        self.application.quit()

    @Slot(str)
    def _failed(self, detail):
        if self.completed or self.cancelled:
            return
        self.completed = True
        self.splash.close()
        message = QMessageBox(QMessageBox.Icon.Critical, "Запуск ГТУ",
                              "Не удалось открыть приложение.", QMessageBox.StandardButton.Ok)
        message.setDetailedText(detail)
        message.exec()
        if self.main_window is not None:
            self.main_window.close()
        self.application.exit(1)


def configure_application():
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("Параметрический расчёт ГТУ")
    application.setWindowIcon(QIcon(str(APP_ICON)))
    application.setFont(QFont("Segoe UI", 10))
    application.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    return application


def run_splash(name):
    application = configure_application()
    splash = StartupSplash(application)
    connection = QLocalSocket(application)
    received = bytearray()

    def connected():
        splash.show()
        application.processEvents()
        connection.write(b"visible\n")
        connection.flush()

    def command():
        received.extend(bytes(connection.readAll()))
        if b"close\n" in received:
            splash.close()
            application.quit()

    connection.connected.connect(connected)
    connection.readyRead.connect(command)
    connection.disconnected.connect(application.quit)
    connection.errorOccurred.connect(lambda _error: application.exit(1))
    connection.connectToServer(name)
    return application.exec()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-splash":
        return run_splash(sys.argv[2])
    application = configure_application()
    startup = StartupCoordinator(application)
    startup.start()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
