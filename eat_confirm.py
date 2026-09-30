# -*- coding: utf-8 -*-
"""
吃掉文件确认框 —— 自绘圆角卡片，跟聊天输入框 / 气泡同一套视觉。

显示要「吃」（移入回收站）的文件列表，让用户确认。
确认后由调用方执行删除 + 播放吃饭动画。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QKeyEvent,
    QPainter, QPen,
)
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

# 与 chat_input / speech_bubble 同一套视觉参数
CARD_X = 14
CARD_Y = 7
CARD_RADIUS = 30
CARD_PAD_X = 26
CARD_PAD_TOP = 18
CARD_PAD_BOTTOM = 16
CARD_WIDTH = 440
MAX_LIST_ROWS = 6      # 列表最多显示几行，多了折叠

TITLE = '要让大肥鱼吃掉这些吗？'
SUBTITLE = '吃掉的会被移入回收站，可以再捞回来'
LIST_HINT = '…以及其他 {n} 个'


class ConfirmEatDialog(QDialog):
    """确认把文件移入回收站。exec() 返回 Accepted 表示确认。"""

    def __init__(self, files: list[str], rejected: list[tuple[str, str]] | None = None,
                 anchor_rect: QRect | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('大肥鱼')
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._files = list(files)
        self._rejected = list(rejected or [])
        self._anchor_rect = anchor_rect
        self._total_w = CARD_X * 2 + CARD_WIDTH

        self._title_font = QFont('Microsoft YaHei UI', 12)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._sub_font = QFont('Microsoft YaHei UI', 9)
        self._item_font = QFont('Microsoft YaHei UI', 10)
        self._btn_font = QFont('Microsoft YaHei UI', 10)

        rows = min(len(self._files), MAX_LIST_ROWS)
        line_h = QFontMetrics(self._item_font).lineSpacing()
        self._list_h = rows * (line_h + 4) + 8
        if len(self._files) > MAX_LIST_ROWS:
            self._list_h += line_h + 2

        root = QVBoxLayout(self)
        root.setContentsMargins(
            CARD_X + CARD_PAD_X, CARD_Y + CARD_PAD_TOP,
            CARD_X + CARD_PAD_X, CARD_Y + CARD_PAD_BOTTOM)
        root.setSpacing(8)
        root.addSpacing(self._title_h())          # 标题（paintEvent 画）
        root.addSpacing(self._sub_h() + 2)        # 副标题
        root.addSpacing(self._list_h)             # 文件列表
        if self._rejected:
            root.addSpacing(self._reject_h())
        root.addLayout(self._build_buttons())

        self.setFixedSize(self._total_w, self.sizeHint().height())
        self._place()

    # ------------------------------------------------------------ 尺寸辅助
    def _title_h(self) -> int:
        return 26

    def _sub_h(self) -> int:
        return 18

    def _reject_h(self) -> int:
        return 16

    # ------------------------------------------------------------ 按钮
    def _build_buttons(self) -> QHBoxLayout:
        self.cancel_btn = QPushButton('先不吃')
        self.cancel_btn.setFont(self._btn_font)
        self.cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cancel_btn.setFixedSize(88, 32)
        self.cancel_btn.setStyleSheet(
            'QPushButton { background: #f1f3f5; color: #3c4043; border: none;'
            ' border-radius: 16px; }'
            'QPushButton:hover { background: #e6e9ec; }'
            'QPushButton:pressed { background: #dcdfe3; }')
        self.cancel_btn.clicked.connect(self.reject)

        self.eat_btn = QPushButton('吃掉它')
        self.eat_btn.setFont(self._btn_font)
        self.eat_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.eat_btn.setFixedSize(96, 32)
        self.eat_btn.setDefault(True)
        self.eat_btn.setStyleSheet(
            'QPushButton { background: #ff7043; color: #ffffff; border: none;'
            ' border-radius: 16px; }'
            'QPushButton:hover { background: #f45c2c; }'
            'QPushButton:pressed { background: #e04f21; }')
        self.eat_btn.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addSpacing(8)
        row.addWidget(self.eat_btn)
        return row

    # ------------------------------------------------------------ 定位
    def _place(self) -> None:
        anchor = self._anchor_rect
        if anchor is None or QGuiApplication.primaryScreen() is None:
            return
        scr = QGuiApplication.screenAt(anchor.center())
        avail = (scr or QGuiApplication.primaryScreen()).availableGeometry()
        x = anchor.left() + (anchor.width() - self.width()) // 2
        y = anchor.top() - self.height() - 10
        x = min(max(x, avail.left() + 8), avail.right() - self.width() - 8)
        if y < avail.top() + 8:
            y = anchor.bottom() + 10
        y = min(max(y, avail.top() + 8), avail.bottom() - self.height() - 8)
        self.move(QPoint(int(x), int(y)))

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card_w = self.width() - CARD_X * 2
        card_h = self.height() - CARD_Y * 2

        # 柔和投影（同气泡 / 聊天框）
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(17, 24, 39, 14))
        painter.drawRoundedRect(CARD_X + 1, CARD_Y + 12, card_w - 2,
                                card_h, CARD_RADIUS, CARD_RADIUS)
        painter.setBrush(QColor(17, 24, 39, 20))
        painter.drawRoundedRect(CARD_X, CARD_Y + 6, card_w,
                                card_h, CARD_RADIUS, CARD_RADIUS)
        painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
        painter.setBrush(QColor(252, 252, 253, 250))
        painter.drawRoundedRect(CARD_X, CARD_Y, card_w, card_h,
                                CARD_RADIUS, CARD_RADIUS)

        left = CARD_X + CARD_PAD_X
        text_w = card_w - CARD_PAD_X * 2
        y = CARD_Y + CARD_PAD_TOP

        painter.setFont(self._title_font)
        painter.setPen(QColor('#25282D'))
        painter.drawText(left, y, text_w, self._title_h(),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         TITLE)
        y += self._title_h()

        painter.setFont(self._sub_font)
        painter.setPen(QColor('#747981'))
        painter.drawText(left, y, text_w, self._sub_h(),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         SUBTITLE)
        y += self._sub_h() + 2

        # 文件列表：浅灰底圆角块
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(242, 244, 246, 255))
        painter.drawRoundedRect(left, y, text_w, self._list_h, 12, 12)

        metrics = QFontMetrics(self._item_font)
        line_h = metrics.lineSpacing() + 4
        painter.setFont(self._item_font)
        painter.setPen(QColor('#3c4043'))
        tx = left + 14
        tw = text_w - 28
        ty = y + 6
        for name in self._files[:MAX_LIST_ROWS]:
            shown = metrics.elidedText(f'• {name}', Qt.TextElideMode.ElideMiddle, tw)
            painter.drawText(tx, ty, tw, line_h,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             shown)
            ty += line_h
        hidden = len(self._files) - MAX_LIST_ROWS
        if hidden > 0:
            painter.setPen(QColor('#9aa0a6'))
            painter.drawText(tx, ty, tw, line_h,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             LIST_HINT.format(n=hidden))
        y += self._list_h

        # 被拒绝的文件提示
        if self._rejected:
            painter.setFont(self._sub_font)
            painter.setPen(QColor('#c62828'))
            bad = '，'.join(f'{n}（{r}）' for n, r in self._rejected[:3])
            if len(self._rejected) > 3:
                bad += f' 等 {len(self._rejected)} 个'
            painter.drawText(left, y, text_w, self._reject_h(),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(f'吃不了：{bad}',
                                                Qt.TextElideMode.ElideRight, text_w))
        painter.end()

    # ------------------------------------------------------------ 键盘
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)


def ask_eat_files(files: list[str], rejected: list[tuple[str, str]] | None = None,
                  anchor_rect: QRect | None = None, parent=None) -> bool:
    """弹出确认框；用户确认吃掉返回 True。"""
    dlg = ConfirmEatDialog(files, rejected, anchor_rect, parent)
    return dlg.exec() == QDialog.DialogCode.Accepted