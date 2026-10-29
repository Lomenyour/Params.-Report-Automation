"""Ранний показ заставки и передача управления только готовому интерфейсу."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMainWindow

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scr"))
from desktop_bootstrap import StartupCoordinator


class DesktopStartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_bootstrap_import_does_not_load_calculation_or_webengine(self):
        result = subprocess.run([sys.executable, "-X", "utf8", "-c",
            "import sys; sys.path.insert(0, 'scr'); import desktop_bootstrap; "
            "assert not any(name in sys.modules for name in "
            "('desktop_controller','app','pandas','matplotlib','CoolProp','PySide6.QtWebEngineWidgets'))"],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_window_waits_for_page_and_webchannel(self):
        with patch("desktop_bootstrap.SplashProcess"):
            startup = StartupCoordinator(self.application)
        startup.main_window = QMainWindow()
        startup.main_window.controller = SimpleNamespace(ready=False)
        emissions = []
        startup.window_ready.connect(lambda: emissions.append(True))
        try:
            startup._maybe_finish()
            self.assertFalse(startup.main_window.isVisible())
            startup.page_loaded = True
            startup._maybe_finish()
            self.assertFalse(startup.main_window.isVisible())
            startup.splash.close.assert_not_called()
            startup.main_window.controller.ready = True
            startup._maybe_finish()
            self.application.processEvents()
            self.assertTrue(startup.main_window.isVisible())
            startup.splash.close.assert_called_once_with()
            startup._maybe_finish()
            self.assertEqual(emissions, [True])
        finally:
            startup.main_window.close()
            startup.splash.close()

    def test_startup_failure_closes_splash_and_reports_error(self):
        with patch("desktop_bootstrap.SplashProcess"):
            startup = StartupCoordinator(self.application)
        with patch("desktop_bootstrap.QMessageBox") as message, patch.object(self.application, "exit") as exit_app:
            startup._failed("test import failure")
            startup.splash.close.assert_called_once_with()
            message.return_value.setDetailedText.assert_called_once_with("test import failure")
            exit_app.assert_called_once_with(1)

    def test_closing_splash_cancels_startup_without_showing_main_window(self):
        with patch("desktop_bootstrap.SplashProcess"):
            startup = StartupCoordinator(self.application)
        startup.main_window = QMainWindow()
        with patch.object(self.application, "quit") as quit_app:
            startup._cancelled()
            self.assertTrue(startup.cancelled)
            self.assertFalse(startup.main_window.isVisible())
            quit_app.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
