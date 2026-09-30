# -*- coding: utf-8 -*-
"""
聊天气泡 —— 简洁的圆角卡片气泡，显示在桌宠上方。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame

_MAC = sys.platform == 'darwin'

_CARD_X = 14
_CARD_Y = 7
_CARD_HEIGHT = 84
_CARD_RADIUS = 30
_CARD_WINDOW_WIDTH = 448
_CARD_WINDOW_HEIGHT = 98


class PetSpeechBubble(QFrame):
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        if _MAC:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.title = ''
        self.detail = ''
        self._anchor_rect = QRect()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._dismiss)
        self.setFixedSize(_CARD_WINDOW_WIDTH, _CARD_WINDOW_HEIGHT)

    def show_text(self, text: str, anchor_rect: QRect,
                  duration_ms: int = 3200) -> None:
        text = str(text).strip()
        if not text:
            return
        lines = text.splitlines()
        self.title = lines[0].strip()
        self.detail = ' '.join(l.strip() for l in lines[1:] if l.strip())
        if not self.detail:
            self.detail = '大肥鱼 · 陪你工作'

        title_font = QFont('Microsoft YaHei UI', 11)
        title_font.setWeight(QFont.Weight.DemiBold)
        detail_font = QFont('Microsoft YaHei UI', 9)
        needed = max(
            QFontMetrics(title_font).horizontalAdvance(self.title),
            QFontMetrics(detail_font).horizontalAdvance(self.detail),
        )
        width = max(_CARD_WINDOW_WIDTH, int(needed) + 130)
        self.setFixedSize(width, _CARD_WINDOW_HEIGHT)

        self._anchor_rect = anchor_rect
        self._place(anchor_rect)
        self.show()
        if not _MAC:
            self.raise_()
        self._hide_timer.start(max(500, int(duration_ms)))

    def _dismiss(self) -> None:
        was_visible = self.isVisible()
        self.hide()
        if was_visible:
            self.dismissed.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        card_width = w - 28

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(17, 24, 39, 13))
        painter.drawRoundedRect(_CARD_X + 1, _CARD_Y + 13, card_width - 2,
                                _CARD_HEIGHT, _CARD_RADIUS, _CARD_RADIUS)
        painter.setBrush(QColor(17, 24, 39, 18))
        painter.drawRoundedRect(_CARD_X, _CARD_Y + 7, card_width,
                                _CARD_HEIGHT, _CARD_RADIUS, _CARD_RADIUS)
        painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
        painter.setBrush(QColor(252, 252, 253, 248))
        painter.drawRoundedRect(_CARD_X, _CARD_Y, card_width,
                                _CARD_HEIGHT, _CARD_RADIUS, _CARD_RADIUS)

        text_x = _CARD_X + 24
        text_width = card_width - 60
        title_font = QFont('Microsoft YaHei UI', 11)
        title_font.setWeight(QFont.Weight.DemiBold)
        detail_font = QFont('Microsoft YaHei UI', 9)

        painter.setFont(title_font)
        painter.setPen(QColor('#25282D'))
        title_text = QFontMetrics(title_font).elidedText(
            self.title, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(text_x, _CARD_Y + 15, text_width, 27,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         title_text)

        painter.setFont(detail_font)
        painter.setPen(QColor('#747981'))
        detail_text = QFontMetrics(detail_font).elidedText(
            self.detail, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(text_x, _CARD_Y + 43, text_width, 24,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         detail_text)
        painter.end()

    def _place(self, anchor_rect: QRect) -> None:
        if QGuiApplication.primaryScreen() is None:
            return
        gap = 10
        size = self.size()
        # 始终优先显示在桌宠正上方并水平居中；允许超出屏幕边界
        centered_x = anchor_rect.left() + (anchor_rect.width() - size.width()) // 2
        x = centered_x
        y = anchor_rect.top() - size.height() - gap
        self.move(x, y)

    def reposition(self, anchor_rect: QRect) -> None:
        """跟随桌宠重新定位（气泡显示期间桌宠移动时调用）。"""
        if self.isVisible():
            self._place(anchor_rect)
