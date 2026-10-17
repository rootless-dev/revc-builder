"""Small widgets shared by the wizard pages. All artwork is drawn in code and original."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget

PINK = QColor("#ff3ea5")
CYAN = QColor("#2de2e6")
NIGHT = QColor("#0b0420")


def label(text: str, role: str = "Body", *, wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(role)
    widget.setWordWrap(wrap)
    widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def glow(widget: QWidget, color: QColor = PINK, radius: float = 24.0) -> QWidget:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(radius)
    effect.setColor(color)
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)
    return widget


class SunsetBanner(QWidget):
    """A striped sunset over a perspective grid."""

    def __init__(self, parent: QWidget | None = None, height: int = 120) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        horizon = height * 0.62

        sky = QLinearGradient(0, 0, 0, horizon)
        sky.setColorAt(0.0, NIGHT)
        sky.setColorAt(1.0, QColor("#2a0b4d"))
        painter.fillRect(QRectF(0, 0, width, horizon), sky)

        radius = height * 0.48
        centre = QPointF(width / 2, horizon)
        sun = QPainterPath()
        sun.addEllipse(centre, radius, radius)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, width, horizon))
        stripe_gap = radius * 0.14
        y = horizon - radius * 0.55
        thickness = 2.0
        while y < horizon:
            band = QPainterPath()
            band.addRect(QRectF(0, y, width, thickness))
            clip = clip.subtracted(band)
            y += stripe_gap
            thickness += 1.6
        sun_gradient = QLinearGradient(0, horizon - radius, 0, horizon)
        sun_gradient.setColorAt(0.0, QColor("#ffd23f"))
        sun_gradient.setColorAt(1.0, PINK)
        painter.fillPath(sun.intersected(clip), sun_gradient)

        ground = QLinearGradient(0, horizon, 0, height)
        ground.setColorAt(0.0, QColor("#1a0636"))
        ground.setColorAt(1.0, NIGHT)
        painter.fillRect(QRectF(0, horizon, width, height - horizon), ground)

        pen = QPen(CYAN)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, horizon), QPointF(width, horizon))
        depth = height - horizon
        step = 1.0
        offset = 0.0
        while offset < depth:
            painter.drawLine(QPointF(0, horizon + offset), QPointF(width, horizon + offset))
            offset += step
            step *= 1.7
        vanishing = QPointF(width / 2, horizon)
        for index in range(-12, 13):
            painter.drawLine(vanishing, QPointF(width / 2 + index * width / 10, height))
        painter.end()
