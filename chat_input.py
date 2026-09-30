# -*- coding: utf-8 -*-
"""
聊天输入框 —— 自绘圆角卡片，替代 Qt 自带那个「系统默认样式」的 QInputDialog。

视觉与 speech_bubble 的气泡保持一致：白底圆角卡片 + 柔和投影 + 淡描边，
配色沿用 #25282D / #747981 与「Microsoft YaHei UI」字体。

交互：
- Enter 发送，Shift+Enter 换行，Esc 取消
- 多行输入时卡片自动长高（有上限）
- 打开时定位在桌宠正上方并水平居中
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QKeyEvent,
    QPainter, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

# ---------------------------------------------------------------- 全局鼠标监听
# 点桌面/任务栏/其他程序时，事件根本不会进 Qt，所以只能用 Win32 轮询真实鼠标状态。
_VK_LBUTTON = 0x01

if sys.platform == 'win32':
    _user32 = ctypes.windll.user32
else:
    _user32 = None


def _left_button_down() -> bool:
    """当前左键是否按下（全局，跨程序）。"""
    if _user32 is None:
        return False
    return bool(_user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)


def _left_button_state() -> int:
    """左键原始状态位：低位=自上次调用后按过，高位=当前按下。"""
    if _user32 is None:
        return 0
    return int(_user32.GetAsyncKeyState(_VK_LBUTTON)) & 0xFFFF


def _global_cursor_pos() -> QPoint:
    """全局鼠标位置（物理像素 → 逻辑坐标，适配高 DPI）。"""
    if _user32 is None:
        return QCursor.pos()
    from ctypes import wintypes
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        dpr = screen.devicePixelRatio()
        if dpr and dpr != 1.0:
            return QPoint(int(pt.x / dpr), int(pt.y / dpr))
    return QPoint(pt.x, pt.y)

# 与 speech_bubble 保持同一套视觉参数
CARD_X = 14          # 卡片相对窗口的左内边距（留出投影空间）
CARD_Y = 7
CARD_RADIUS = 30
CARD_PAD_X = 24      # 卡片内文字左右边距
CARD_PAD_TOP = 16
CARD_PAD_BOTTOM = 14
CARD_WIDTH = 420     # 卡片宽度
MAX_EDIT_HEIGHT = 110  # 输入框最多长到多高，超过就滚动

TITLE = '和大肥鱼聊天'
PLACEHOLDER = '想对我说点什么…'


class ChatInputDialog(QDialog):
    """圆角卡片风格的聊天输入框。exec() 返回 Accepted 时可用 text() 取内容。"""

    def __init__(self, anchor_rect: QRect | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        # 不置顶：用户点开别的东西时不该一直被压在上面
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 点对话框外部自动关闭
        self.setModal(False)

        # 尺寸常量（在 _fit_height / _place 里会用到，必须先定义）
        self._total_w = CARD_X * 2 + CARD_WIDTH
        self._text_width = CARD_WIDTH - CARD_PAD_X * 2
        self._anchor_rect = anchor_rect

        self._title_font = QFont('Microsoft YaHei UI', 11)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._edit_font = QFont('Microsoft YaHei UI', 11)
        self._hint_font = QFont('Microsoft YaHei UI', 9)

        # 标题画在 paintEvent 里，这里放一个占位 label 的位置由布局留白
        self._title_h = 24

        # 停手多久自动关闭（毫秒）；有输入时会重新计时
        self._idle_ms = 5000
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self._idle_ms)
        self._idle_timer.timeout.connect(self._auto_close)

        # 全局鼠标轮询：点桌面/别的程序时也能自动关（只在显示期间跑）
        self._mouse_was_down = False
        self._click_timer = QTimer(self)
        self._click_timer.setInterval(40)
        self._click_timer.timeout.connect(self._watch_global_click)

        # 输入框：透明无边框，由卡片背景承载
        self.edit = QPlainTextEdit()
        self.edit.setFont(self._edit_font)
        self.edit.setPlaceholderText(PLACEHOLDER)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit.setStyleSheet(
            'QPlainTextEdit { background: transparent; border: none; '
            'color: #25282D; selection-background-color: #d6e4ff; }')
        self.edit.viewport().setAutoFillBackground(False)
        self.edit.textChanged.connect(self._fit_height)
        # Enter 会被 QPlainTextEdit 自己吃掉（插入换行），必须在输入框上装过滤器拦截
        self.edit.installEventFilter(self)

        # 发送按钮：圆角，主色
        self.send_btn = QPushButton('发送')
        self.send_btn.setFont(QFont('Microsoft YaHei UI', 10))
        self.send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.send_btn.setFixedSize(76, 30)
        self.send_btn.setDefault(True)
        self.send_btn.setStyleSheet(
            'QPushButton { background: #2f6bff; color: #ffffff; border: none;'
            ' border-radius: 15px; }'
            'QPushButton:hover { background: #245ad9; }'
            'QPushButton:pressed { background: #1f4dc0; }')
        self.send_btn.clicked.connect(self._on_send)

        hint = QHBoxLayout()
        hint.setContentsMargins(0, 0, 0, 0)
        hint_text = QLabel('Enter 发送 · Shift+Enter 换行 · Esc 取消')
        hint_text.setFont(self._hint_font)
        hint_text.setStyleSheet('color: #9aa0a6; background: transparent;')
        hint.addWidget(hint_text)
        hint.addStretch(1)
        hint.addWidget(self.send_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            CARD_X + CARD_PAD_X, CARD_Y + CARD_PAD_TOP,
            CARD_X + CARD_PAD_X, CARD_Y + CARD_PAD_BOTTOM)
        root.setSpacing(8)
        root.addSpacing(self._title_h)   # 给 paintEvent 画的标题留位置
        root.addWidget(self.edit)
        root.addLayout(hint)

        self._fit_height()
        self._place()

    # ------------------------------------------------------------ 取值
    def text(self) -> str:
        return self.edit.toPlainText().strip()

    # ------------------------------------------------------------ 自适应高度
    def _fit_height(self) -> None:
        """根据内容行数调整输入框与窗口高度。

        注意：设了 textWidth 后 QTextDocument.size() 的高度单位是「视觉行数」
        （长段落自动折行会算成多行），不是像素，所以要乘以行高换算。
        """
        doc = self.edit.document()
        doc.setTextWidth(self._text_width)
        line_count = max(1.0, float(doc.size().height()))
        metrics = QFontMetrics(self._edit_font)
        content_h = metrics.lineSpacing() * line_count
        edit_h = max(30, min(MAX_EDIT_HEIGHT, int(content_h) + 8))
        self.edit.setFixedHeight(edit_h)
        self._relayout()

    def _relayout(self) -> None:
        hint_h = self.send_btn.height()
        total_h = (CARD_Y + CARD_PAD_TOP + self._title_h + 8
                   + self.edit.height() + 8 + hint_h + CARD_PAD_BOTTOM)
        self.setFixedSize(self._total_w, total_h)
        # 尺寸变了就重新贴到桌宠上方，避免位置漂移
        self._place(self._anchor_rect)

    # ------------------------------------------------------------ 定位
    def _place(self, anchor_rect: QRect | None = None) -> None:
        """放在桌宠正上方居中；越界则回收到屏幕内。"""
        if anchor_rect is not None:
            self._anchor_rect = anchor_rect
        anchor_rect = self._anchor_rect
        if anchor_rect is None or QGuiApplication.primaryScreen() is None:
            return
        scr = QGuiApplication.screenAt(anchor_rect.center())
        avail = (scr or QGuiApplication.primaryScreen()).availableGeometry()
        x = anchor_rect.left() + (anchor_rect.width() - self.width()) // 2
        y = anchor_rect.top() - self.height() - 10
        x = min(max(x, avail.left() + 8), avail.right() - self.width() - 8)
        if y < avail.top() + 8:
            y = anchor_rect.bottom() + 10   # 上方放不下就放下面
        y = min(max(y, avail.top() + 8), avail.bottom() - self.height() - 8)
        self.move(QPoint(int(x), int(y)))

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        h = self.height()
        card_w = w - CARD_X * 2
        card_h = h - CARD_Y * 2

        # 两层柔和投影，和气泡同款
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(17, 24, 39, 14))
        painter.drawRoundedRect(CARD_X + 1, CARD_Y + 12, card_w - 2,
                                card_h, CARD_RADIUS, CARD_RADIUS)
        painter.setBrush(QColor(17, 24, 39, 20))
        painter.drawRoundedRect(CARD_X, CARD_Y + 6, card_w,
                                card_h, CARD_RADIUS, CARD_RADIUS)

        # 卡片本体
        painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
        painter.setBrush(QColor(252, 252, 253, 250))
        painter.drawRoundedRect(CARD_X, CARD_Y, card_w, card_h,
                                CARD_RADIUS, CARD_RADIUS)

        # 标题
        painter.setFont(self._title_font)
        painter.setPen(QColor('#25282D'))
        painter.drawText(CARD_X + CARD_PAD_X, CARD_Y + CARD_PAD_TOP,
                         card_w - CARD_PAD_X * 2, self._title_h,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         TITLE)
        painter.end()

    # ------------------------------------------------------------ 键盘
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """输入框上的 Enter 拦截 + 记录用户活动。

        点击对话框外部的判断统一交给 _watch_global_click 轮询（那样才能
        覆盖点桌面/任务栏/其他程序的情况）。
        """
        if obj is self.edit:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        return False          # Shift+Enter → 换行
                    self._on_send()
                    return True               # Enter → 发送
                self._touch()                 # 打字中，重新计时
            elif event.type() in (QEvent.Type.MouseButtonPress,
                                  QEvent.Type.Wheel,
                                  QEvent.Type.InputMethod,
                                  QEvent.Type.InputMethodQuery):
                # InputMethod* 覆盖中文输入法组词/上屏，不然用拼音打字
                # 会被当成「没在输入」而超时关掉
                self._touch()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # 焦点不在输入框时（比如在按钮上）也能回车发送
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self._on_send()
            return
        self._touch()
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 自动关闭
    def _touch(self) -> None:
        """有用户操作，重置「停手 5 秒」计时。"""
        self._idle_timer.start(self._idle_ms)

    def _auto_close(self) -> None:
        """停手超时：自动关掉（等同取消）。"""
        self.reject()

    def _watch_global_click(self) -> None:
        """轮询：点到对话框外面就自动关。

        点桌面 / 任务栏 / 别的程序时，事件不会进 Qt，所以用 Win32 的
        GetAsyncKeyState 检测左键「按下」那一瞬间（边沿触发），再用
        GetCursorPos 判断点在哪。

        注意：这里**不能**用「焦点是否还在自己身上」来判断，因为用户
        打字时鼠标可能停在别处，会被误判成「点了外面」而把输入框关掉。
        只认「真的有左键按下」这个事实。
        """
        if not self.isVisible():
            return

        # 左键边沿检测：低位=自上次调用后按过（能抓住极快的点击），
        # 高位=当前正按着
        state = _left_button_state()
        pressed_now = bool(state & 0x0001) or (
            bool(state & 0x8000) and not self._mouse_was_down)
        self._mouse_was_down = bool(state & 0x8000)
        if not pressed_now:
            return

        pos = _global_cursor_pos()
        if self.frameGeometry().contains(pos):
            self._touch()      # 点自己身上 → 重新计时
            return

        self.reject()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.edit.setFocus()
        self._touch()
        self._mouse_was_down = _left_button_down()
        # 非模态窗口需要在应用级观察鼠标，判断是否点了对话框外面
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        # 全局点击轮询（覆盖桌面/任务栏/其他程序）
        self._click_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._idle_timer.stop()
        self._click_timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """点在自己卡片上，重新计时。"""
        self._touch()
        super().mousePressEvent(event)

    def _on_send(self) -> None:
        if not self.text():
            return
        self.accept()


def ask_chat_text(anchor_rect: QRect | None = None, parent=None) -> str | None:
    """弹出圆角聊天输入框；用户发送则返回文本，取消返回 None。"""
    dlg = ChatInputDialog(anchor_rect, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.text() or None