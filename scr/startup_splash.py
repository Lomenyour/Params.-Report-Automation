"""Лёгкая заставка: только Qt Widgets, без WebEngine и расчётных импортов."""
from PySide6.QtCore import QObject, QPoint, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsOpacityEffect, QLabel, QWidget

from desktop_resources import APP_ICON, STARTUP_PLANT

SMOKE_CYCLE_MS = 3000
SPLASH_RADIUS = 23
SPLASH_SIZE = (430, 290)


class StartupSplash(QObject):
    """Анимации и виджеты нативные: Python не вызывается на каждом кадре."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = QWidget(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.window.setObjectName("startupSplash")
        self.window.setWindowTitle("ГТУ — загрузка")
        self.window.setWindowIcon(QIcon(str(APP_ICON)))
        self.window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.window.setFixedSize(*SPLASH_SIZE)
        card = QFrame(self.window)
        card.setObjectName("startupCard")
        card.setGeometry(0, 0, *SPLASH_SIZE)
        card.setStyleSheet(f"""
            QFrame#startupCard {{ background: #252525; border: 1px solid #424242;
                border-radius: {SPLASH_RADIUS}px; }}
            QLabel {{ background: transparent; border: 0; color: #f3f3f3;
                font-family: 'Segoe UI'; }}
        """)
        mark = QLabel(card)
        mark.setGeometry(30, 25, 20, 20)
        mark.setPixmap(QIcon(str(APP_ICON)).pixmap(20, 20))
        brand = QLabel("ГТУ", card)
        brand.setGeometry(58, 25, 80, 20)
        brand.setStyleSheet("font-size: 12px; color: #b4b4b4;")

        # Цвет задаётся представлением; исходный PNG электростанции не меняется.
        plant = QPixmap(str(STARTUP_PLANT)).scaled(
            110, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(plant)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(plant.rect(), QColor("#f3f3f3"))
        painter.end()
        base = QLabel(card)
        base.setObjectName("startupPlant")
        base.setGeometry(160, 90, 110, 76)
        base.setPixmap(plant.copy(0, 34, 110, 76))
        self.animations, self.clouds = [], []
        for phase in (0, SMOKE_CYCLE_MS // 2):
            cloud = QLabel(card)
            cloud.setObjectName("startupSmoke")
            cloud.setGeometry(160, 56, 110, 35)
            cloud.setPixmap(plant.copy(0, 0, 110, 35))
            opacity = QGraphicsOpacityEffect(cloud)
            cloud.setGraphicsEffect(opacity)
            group = QParallelAnimationGroup(self)
            move = QPropertyAnimation(cloud, b"pos", group)
            move.setDuration(SMOKE_CYCLE_MS)
            move.setStartValue(QPoint(158, 59))
            move.setEndValue(QPoint(172, 45))
            move.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade = QPropertyAnimation(opacity, b"opacity", group)
            fade.setDuration(SMOKE_CYCLE_MS)
            for time, value in ((0., 0.), (.2, .75), (.65, .44), (1., 0.)):
                fade.setKeyValueAt(time, value)
            group.addAnimation(move)
            group.addAnimation(fade)
            group.setLoopCount(-1)
            self.animations.append((group, phase))
            self.clouds.append(cloud)
        heading = QLabel("Параметрический расчёт ГТУ", card)
        heading.setObjectName("startupTitle")
        heading.setGeometry(24, 184, 382, 30)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet("font-size: 21px; font-weight: 500;")
        caption = QLabel("Подготовка рабочего пространства…", card)
        caption.setObjectName("startupSubtitle")
        caption.setGeometry(24, 220, 382, 23)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setStyleSheet("font-size: 13px; color: #b4b4b4;")

    def show(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.window.move(screen.center() - self.window.rect().center())
        self.window.show()
        for animation, phase in self.animations:
            animation.start()
            animation.setCurrentTime(phase)

    def close(self):
        for animation, _phase in self.animations:
            animation.stop()
        self.window.close()
