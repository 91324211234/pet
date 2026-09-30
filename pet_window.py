# -*- coding: utf-8 -*-
"""
桌宠主窗口 —— 透明无边框置顶窗口 + 动画链状态机 + 移动驱动 + 交互。

功能：
- 透明置顶窗口（FramelessWindowHint + WA_TranslucentBackground + Tool）
- 动画链状态机：待机 → 随机动作 / 转向 / 移动
- 点击回应、拖拽
- 移动（位置插值，动画只提供走路姿态）
- 聊天气泡
- 右键菜单（动画频率、移动频率、缩放、置顶、退出）
"""
from __future__ import annotations

import logging
import math
import random
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QActionGroup, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent,
    QPainter, QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from catalog import (
    CANVAS_H, CANVAS_W, CORNER_MARGIN, DEFAULT_SCALE, DRAG_THRESHOLD,
    MOVE_LEAD_SEC, MOVE_MARGIN, MOVE_MAX_PX, MOVE_MIN_PX, MOVE_TAIL_SEC,
    P_ACTS, P_IDLE, P_TURN, PAD, SCALE_STEPS, Catalog,
)
from chat_input import ask_chat_text
from config import Config
from eat_confirm import ask_eat_files
from file_actions import classify_paths, delete_many
from llm_client import LLMClient
from settings_dialog import ask_settings
from speech_bubble import PetSpeechBubble
from webm_player import WebMPlayer

logger = logging.getLogger(__name__)

# 动画频率档位 → 两次随机动作之间的间隔（秒）
IDLE_ANIMATION_INTERVALS = {
    'continuous': 0.0,
    'frequent': 15.0,
    'balanced': 45.0,
    'occasional': 120.0,
    'task_only': None,
}
# 移动频率档位 → 移动概率
MOVEMENT_PROBABILITIES = {
    'continuous': 1.0,
    'frequent': 0.6,
    'balanced': 0.3,
    'occasional': 0.1,
    'off': 0.0,
}

# 吃饭动画：按时间段挑（小时 → 动画名），找不到就回退到备选池
MEAL_ANIMATIONS = {
    'breakfast': ('吃早餐', '吃白饭', '吃年糕'),
    'lunch': ('吃午餐', '吃饺子', '吃大闸蟹'),
    'dinner': ('吃晚餐', '吃汤圆', '吃粽子'),
    'snack': ('大口吃零食', '吃糖葫芦', '吃西瓜', '吃冰淇淋融化'),
}


def pick_meal_animation(acts: list[str], now=None) -> str | None:
    """按当前时间选吃饭动画：早餐 / 午餐 / 晚餐 / 零食。

    时间表：5-10 点早餐，11-14 点午餐，17-21 点晚餐，其余时间当零食。
    从对应池里挑一个动作池里真实存在的；都没有就返回 None。
    """
    import datetime

    hour = (now or datetime.datetime.now()).hour
    if 5 <= hour < 11:
        slot = 'breakfast'
    elif 11 <= hour < 15:
        slot = 'lunch'
    elif 17 <= hour < 22:
        slot = 'dinner'
    else:
        slot = 'snack'

    available = set(acts)
    for name in MEAL_ANIMATIONS[slot]:
        if name in available:
            return name
    # 时间段内的候选都没有，就从所有「吃」开头的动画里随便挑一个
    eats = [n for n in acts if n.startswith('吃') or '吃' in n]
    if eats:
        return random.choice(eats)
    return None


def _win_set_topmost(hwnd: int, on: bool) -> bool:
    """Windows 原生强制置顶/取消置顶（Qt hint 之外的兜底）。"""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        return bool(user32.SetWindowPos(
            wintypes.HWND(hwnd),
            wintypes.HWND(HWND_TOPMOST if on else HWND_NOTOPMOST),
            0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        ))
    except Exception:
        return False


class PetWindow(QWidget):
    """桌宠窗口本体。"""

    # 后台聊天完成信号：参数为 (用户输入, LLM 回复)
    _chat_done = Signal(str, str)

    def __init__(self, catalog: Catalog, on_top: bool = False) -> None:
        super().__init__()
        self.cat = catalog
        self.idle = catalog.idles[0]
        self.turn = catalog.turns[0] if catalog.turns else None
        self.moves = catalog.moves
        self.clicks = catalog.clicks
        self.drag = catalog.drag
        self.acts = catalog.acts

        # 播放器缓存：动画名 → WebMPlayer
        self._players: dict[str, WebMPlayer] = {}
        self._current_name: str | None = None
        self._current_player: WebMPlayer | None = None

        # 状态
        self.facing: str = 'left'  # left | right
        self.scale: float = DEFAULT_SCALE
        self.on_top: bool = on_top
        self.idle_animation_frequency = 'balanced'
        self.movement_frequency = 'balanced'
        self._next_idle_action_at = 0.0
        self._reset_idle_deadline()

        # 交互状态
        self._press_global: QPoint | None = None
        self._grab_offset: QPoint | None = None
        self._dragging = False
        self._just_dragged = False
        self._menu_open = False  # 右键菜单是否打开（打开时暂停置顶看门狗）
        self._drag_hover = False  # 是否有文件拖到桌宠身上
        self._eating_anim: str | None = None  # 正在播的吃饭动画名（None=没在吃）
        self._hover_anim: str | None = None   # 拖拽悬停时预告用的动画名

        # 接收文件拖放（拖文件过来 → 确认 → 吃掉 + 吃饭动画）
        self.setAcceptDrops(True)

        # 移动驱动
        self._move_plan: dict | None = None
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(33)
        self._move_timer.timeout.connect(self._on_move_tick)

        # 气泡
        self._bubble = PetSpeechBubble()
        # 气泡跟随定时器：气泡显示期间让气泡跟随桌宠移动
        self._bubble_follow = QTimer(self)
        self._bubble_follow.setInterval(50)
        self._bubble_follow.timeout.connect(self._follow_bubble)

        # 聊天客户端（直接调用本地 LLM，带文件持久化上下文）
        self._config = Config()
        self._llm = LLMClient(config=self._config)
        self._chat_done.connect(self._on_chat_done)

        # 窗口属性
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # 透明背景：Windows 上透明小窗口容易被前台应用盖住，
        # 改用 mask 方式让透明区域真正透明，比 WA_TranslucentBackground 更可靠
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # 置顶看门狗：每 2 秒强制重新置顶，防止被前台窗口覆盖
        self._topmost_watchdog = QTimer(self)
        self._topmost_watchdog.setInterval(2000)
        self._topmost_watchdog.timeout.connect(self._enforce_topmost)

        self._apply_scale()
        self._restore_position()
        self._switch(self.idle, origin='idle')
        # 启动后立即强制置顶
        QTimer.singleShot(100, self._enforce_topmost)
        self._topmost_watchdog.start()

    def _enforce_topmost(self) -> None:
        # 右键菜单打开时不要置顶，否则会把菜单盖住
        if self._menu_open:
            return
        if self.on_top:
            if sys.platform == 'win32':
                _win_set_topmost(int(self.winId()), True)
            self.raise_()
            self.show()

    # ================================================================ 尺寸
    def _apply_scale(self) -> None:
        self._w = max(1, int(round(CANVAS_W * self.scale)))
        self._h = max(1, int(round((CANVAS_H + PAD) * self.scale)))
        self.setFixedSize(self._w, self._h)

    def change_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        old_bottom = self.geometry().bottom()
        self.scale = scale
        self._apply_scale()
        self.move(self.x(), old_bottom - self._h + 1)
        self.update()

    # ================================================================ 位置
    def _screen_available(self):
        scr = self.screen()
        if scr is None:
            scr = QApplication.primaryScreen()
        return scr

    def _restore_position(self) -> None:
        scr = self._screen_available()
        avail = scr.availableGeometry()
        x = avail.right() - self._w - CORNER_MARGIN
        y = avail.bottom() - self._h
        self.move(x, y)

    # ================================================================ 播放器
    def _get_player(self, name: str) -> WebMPlayer:
        if name not in self._players:
            path = self.cat.path_for(name)
            player = WebMPlayer(path, CANVAS_W, CANVAS_H, self)
            player.finished.connect(lambda n=name: self._on_clip_finished(n))
            # 每解码出一帧就触发窗口重绘，否则动画不会显示
            player.frameChanged.connect(lambda _n: self.update())
            self._players[name] = player
        return self._players[name]

    def _switch(self, name: str, origin: str = '', restart: bool = False) -> None:
        """切换到指定动画并播放。

        如果请求的动画就是当前正在播的那个，默认什么都不做 —— 拖放等高频
        事件会反复请求同一个动画，无脑 stop+play 会让画面 0.1s 一抖。
        确实需要重头播时传 restart=True。
        """
        if name == self._current_name and not restart:
            return
        if self._current_player is not None:
            self._current_player.stop()
        self._current_name = name
        self._current_player = self._get_player(name)
        self._current_player.play()
        logger.debug('播放动画: %s (%s)', name, origin)

    # ================================================================ 动画链
    def _reset_idle_deadline(self) -> None:
        interval = IDLE_ANIMATION_INTERVALS.get(self.idle_animation_frequency, 45.0)
        if interval is None:
            self._next_idle_action_at = float('inf')
        else:
            self._next_idle_action_at = self._now() + interval

    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()

    def _on_clip_finished(self, name: str) -> None:
        """当前动画播完，决定下一段。"""
        # 只处理「当前正在播的那一段」播完；被 stop 掉的旧动画别来捣乱
        if name != self._current_name:
            return
        # 吃饭动画播完：回到待机（用名字判断，避免标志位卡死）
        if name == self._eating_anim:
            self._eating_anim = None
            self._reset_idle_deadline()
            self._switch(self.idle, origin='after-eat')
            return
        # 点击回应 / 拖拽动画播完先回待机
        if name in self.clicks or name == self.drag:
            self._switch(self.idle, origin='after-interaction')
            return
        # 移动动画播完回待机
        if name in self.moves:
            self._switch(self.idle, origin='after-move')
            return
        # 动作/转向播完：重置 idle 间隔，回到待机休息
        if name in self.acts or name == self.turn:
            self._reset_idle_deadline()
            self._switch(self.idle, origin='after-act')
            return
        # 待机播完：进入随机链
        self._schedule_next()

    def _schedule_next(self) -> None:
        """按概率选择下一段：待机 / 转向 / 动作 / 移动。"""
        # 移动频率为 off 时，把移动概率并入动作
        move_prob = MOVEMENT_PROBABILITIES.get(self.movement_frequency, 0.3)
        # 若未到随机动作间隔，则保持待机（不播随机动作/移动）
        if self._now() < self._next_idle_action_at:
            self._switch(self.idle, origin='chain-idle-gap')
            return
        r = random.random()
        if r < P_IDLE:
            self._switch(self.idle, origin='chain-idle')
            return
        if r < P_TURN and self.turn:
            self._switch(self.turn, origin='chain-turn')
            self.facing = 'right' if self.facing == 'left' else 'left'
            return
        if r < P_ACTS:
            # 动作池：优先随机动作，其次待机
            pool = self.acts or [self.idle]
            self._switch(random.choice(pool), origin='chain-act')
            return
        # 移动
        if move_prob > 0 and self.moves and random.random() < move_prob:
            self._start_move()
        else:
            self._switch(self.idle, origin='chain-idle')

    # ================================================================ 移动
    def _start_move(self) -> None:
        scr = self._screen_available()
        avail = scr.availableGeometry()
        start_x = self.x()
        start_y = self.y()
        dist = random.randint(MOVE_MIN_PX, MOVE_MAX_PX)
        direction = random.choice([-1, 1])
        target_x = start_x + direction * dist
        target_x = min(max(target_x, avail.left() + MOVE_MARGIN),
                       avail.right() - self._w - MOVE_MARGIN)
        # 若目标与起点太近则放弃移动
        if abs(target_x - start_x) < 20:
            self._switch(self.idle, origin='move-abort')
            return
        anim = random.choice(self.moves)
        player = self._get_player(anim)
        player._ensure_meta()
        duration = player._duration if player._duration > 0 else 3.0
        self._move_plan = {
            'anim': anim,
            'start_x': start_x,
            'start_y': start_y,
            'target_x': target_x,
            'duration': duration,
            'elapsed': 0.0,
            'last_tick': self._now(),
        }
        self._switch(anim, origin='move')
        self._move_timer.start()

    def _on_move_tick(self) -> None:
        if not self._move_plan:
            self._move_timer.stop()
            return
        plan = self._move_plan
        now = self._now()
        plan['elapsed'] += now - plan['last_tick']
        plan['last_tick'] = now
        total = plan['duration']
        lead = MOVE_LEAD_SEC
        tail = MOVE_TAIL_SEC
        if total <= lead + tail:
            # 动画太短，直接线性移动
            t = min(1.0, plan['elapsed'] / total)
        else:
            if plan['elapsed'] < lead:
                t = 0.0
            elif plan['elapsed'] > total - tail:
                t = 1.0
            else:
                t = (plan['elapsed'] - lead) / (total - lead - tail)
        x = plan['start_x'] + (plan['target_x'] - plan['start_x']) * t
        self.move(int(round(x)), plan['start_y'])
        if plan['elapsed'] >= total:
            self._move_timer.stop()
            self._move_plan = None
            self._switch(self.idle, origin='move-done')

    # ================================================================ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        pm = self._current_player.current_pixmap() if self._current_player else None
        if pm is None:
            pm = self._current_player.first_pixmap() if self._current_player else None
        if pm is None:
            painter.end()
            return
        # 缩放绘制，脚底对齐窗口底线
        target_w = self._w
        target_h = int(round(CANVAS_H * self.scale))
        y = self._h - target_h
        if self.facing == 'right':
            painter.scale(-1, 1)
            painter.drawPixmap(-target_w, y, target_w, target_h, pm)
        else:
            painter.drawPixmap(0, y, target_w, target_h, pm)
        painter.end()

    # ================================================================ 鼠标交互
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._grab_offset = self._press_global - self.pos()
            self._dragging = False
            self._just_dragged = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is None:
            return
        pos = event.globalPosition().toPoint()
        if not self._dragging:
            if (pos - self._press_global).manhattanLength() > DRAG_THRESHOLD:
                self._dragging = True
                if self.drag:
                    self._switch(self.drag, origin='drag')
        if self._dragging:
            self.move(pos - self._grab_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._dragging = False
            self._press_global = None
            self._grab_offset = None
            if was_dragging:
                self._just_dragged = True
                self._switch(self.idle, origin='after-drag')
            else:
                # 点击回应：播放点击动画 + 弹出输入框聊天
                if self.clicks:
                    self._switch(random.choice(self.clicks), origin='click')
                self._ask_chat()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self._menu_open = True
        try:
            self._build_menu().exec(event.globalPos())
        finally:
            self._menu_open = False

    # ================================================================ 文件拖放
    @staticmethod
    def _dropped_files(event) -> list[str]:
        """从拖放事件里取出本地文件路径（过滤掉网络 URL 等）。"""
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        """文件拖进桌宠范围：能吃的就接受，并给个视觉反馈。"""
        files = self._dropped_files(event)
        if not files:
            event.ignore()
            return
        accepted, _rejected = classify_paths(files)
        if not accepted:
            # 一个能吃的都没有，不接受拖放
            event.ignore()
            return
        event.acceptProposedAction()
        # 拖拽期间 enter 可能被反复触发；_switch 本身幂等，这里再挡一层，
        # 避免同一段预告动画被反复重播
        if self._drag_hover:
            return
        self._drag_hover = True
        if self._eating_anim is not None:
            return  # 已经在吃了，别打断
        # 摆出「准备好吃了」的样子（用换行前缀的动画不好找，挑不吃的普通动作）
        if self.acts:
            meal = pick_meal_animation(self.acts)
            if meal:
                self._hover_anim = meal
                self._switch(meal, origin='drag-hover')

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._dropped_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drag_hover = False
        self._hover_anim = None
        # 只有确认没在吃饭时才回待机。拖拽在边缘来回蹭会连续触发 leave/enter，
        # 但 _switch 是幂等的，不会造成重复重播。
        if self._eating_anim is None:
            self._switch(self.idle, origin='drag-leave')

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """松手：弹确认框，确认后移入回收站 + 播吃饭动画。"""
        self._drag_hover = False
        self._hover_anim = None
        files = self._dropped_files(event)
        event.acceptProposedAction()
        if not files:
            return

        accepted, rejected = classify_paths(files)
        if not accepted:
            # 全都不合规，直接提示，不弹确认
            reason = '，'.join(f'{n}（{r}）' for n, r in rejected[:3])
            self._show_bubble('这可吃不了', reason or '只能吃普通文件哦',
                              duration_ms=5000)
            self._switch(self.idle, origin='drop-reject')
            return

        # 确认（在桌宠上方弹出圆角卡片）
        if not ask_eat_files(accepted, rejected,
                             anchor_rect=self.frameGeometry(), parent=self):
            self._switch(self.idle, origin='drop-cancel')
            return

        self._eat_files(accepted, rejected)

    def _eat_files(self, files: list[str], rejected: list[tuple[str, str]]) -> None:
        """执行删除（回收站）并播放吃饭动画。"""
        result = delete_many(files)

        # 播放吃饭动画（同一时间只吃一顿；再喂就重新开始这一段）
        if result.ok:
            meal = pick_meal_animation(self.acts)
            if meal:
                # 上一顿的动画如果同名，需要重头播
                self._eating_anim = meal
                self._switch(meal, origin='eat', restart=True)
            else:
                self._eating_anim = None
                self._switch(self.idle, origin='eat-no-anim')
        else:
            self._eating_anim = None

        # 气泡反馈
        if result.all_ok and not rejected:
            names = '、'.join(Path(p).name for p in result.successes[:2])
            more = f' 等 {len(result.successes)} 个' if len(result.successes) > 2 else ''
            self._show_bubble('咔嚓咔嚓～', f'吃掉啦：{names}{more}（已进回收站）',
                              duration_ms=6000)
        elif result.ok:
            self._show_bubble('吃到一部分～',
                              f'{result.summary()}，其他吃不了',
                              duration_ms=6000)
        else:
            reason = '，'.join(f'{n}（{r}）' for n, r in result.failures[:2])
            self._show_bubble('呜…没吃到', reason or '没能放进回收站',
                              duration_ms=6000)
            self._switch(self.idle, origin='eat-failed')

    # ================================================================ 气泡
    def _show_bubble(self, title: str, detail: str, duration_ms: int = 6000) -> None:
        self._bubble.show_text(title, self.frameGeometry(), duration_ms)
        # 气泡显示期间跟随桌宠移动，避免漂移
        self._bubble_follow.start()

    def _follow_bubble(self) -> None:
        """让气泡跟随桌宠当前位置。"""
        if self._bubble.isVisible():
            self._bubble.reposition(self.frameGeometry())
        else:
            self._bubble_follow.stop()

    # ================================================================ 聊天
    def _ask_chat(self) -> None:
        """弹出圆角聊天输入框，让用户输入聊天内容。"""
        text = ask_chat_text(self.frameGeometry(), self)
        if not text:
            return
        self._show_bubble('你', text, duration_ms=4000)
        self._do_chat(text)

    def _do_chat(self, text: str) -> None:
        """后台线程调用 LLM，完成后通过信号回到主线程。"""
        import threading

        def worker():
            reply = self._llm.chat(text)
            self._chat_done.emit(text, reply)

        threading.Thread(target=worker, daemon=True).start()

    def _on_chat_done(self, user_text: str, reply: str) -> None:
        """LLM 回复到达，显示在气泡里。"""
        if not reply:
            return
        # 第一行作为标题，其余作为详情
        lines = reply.splitlines()
        title = lines[0].strip() or '大肥鱼'
        detail = ' '.join(l.strip() for l in lines[1:] if l.strip())
        self._show_bubble(title, detail, duration_ms=10000)

    # ================================================================ 右键菜单
    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        # 动画频率
        anim_menu = menu.addMenu('动画频率')
        anim_group = QActionGroup(anim_menu)
        for level in IDLE_ANIMATION_INTERVALS:
            act = anim_menu.addAction(level)
            act.setCheckable(True)
            act.setChecked(level == self.idle_animation_frequency)
            act.setActionGroup(anim_group)
            act.triggered.connect(
                lambda checked, lv=level: self._set_anim_freq(lv))

        # 移动频率
        move_menu = menu.addMenu('移动频率')
        move_group = QActionGroup(move_menu)
        for level in MOVEMENT_PROBABILITIES:
            act = move_menu.addAction(level)
            act.setCheckable(True)
            act.setChecked(level == self.movement_frequency)
            act.setActionGroup(move_group)
            act.triggered.connect(
                lambda checked, lv=level: self._set_move_freq(lv))

        # 显示大小
        size_menu = menu.addMenu('显示大小')
        size_group = QActionGroup(size_menu)
        for step in SCALE_STEPS:
            label = f'{int(round(step * 100))}%'
            act = size_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(abs(step - self.scale) < 1e-6)
            act.setActionGroup(size_group)
            act.triggered.connect(
                lambda checked, s=step: self.change_scale(s))

        # 置顶
        top_act = menu.addAction('置顶')
        top_act.setCheckable(True)
        top_act.setChecked(self.on_top)
        top_act.triggered.connect(self._toggle_topmost)

        menu.addSeparator()
        menu.addAction('清空对话', self._clear_chat)
        menu.addAction('设置…', self._open_settings)
        menu.addAction('退出', QApplication.instance().quit)
        return menu

    def _open_settings(self) -> None:
        """打开设置对话框，保存后立即生效并持久化。"""
        values = ask_settings(self._config, self)
        if values is None:
            return
        self._config.update(values)
        self._llm.apply_config(self._config)
        self._show_bubble('大肥鱼', f"设置好啦，现在用的是 {values['model']} ～")

    def _clear_chat(self) -> None:
        """清空对话上下文。"""
        self._llm.clear()
        self._show_bubble('大肥鱼', '好啦，我把之前的话都忘掉啦，重新开始～')

    def _set_anim_freq(self, level: str) -> None:
        self.idle_animation_frequency = level
        self._reset_idle_deadline()

    def _set_move_freq(self, level: str) -> None:
        self.movement_frequency = level

    def _toggle_topmost(self, checked: bool) -> None:
        self.on_top = checked
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()
        if sys.platform == 'win32':
            QTimer.singleShot(0, lambda: _win_set_topmost(int(self.winId()), checked))
        if checked:
            self.raise_()

    # ================================================================ 生命周期
    def closeEvent(self, event) -> None:  # noqa: N802
        for player in self._players.values():
            player.stop()
        super().closeEvent(event)
