# -*- coding: utf-8 -*-
"""
WebM 透明动画播放器。

使用 imageio-ffmpeg 自带的静态 ffmpeg 解码 640×360 透明 webm（VP9 alpha）：
- imageio_ffmpeg.read_frames(path, pix_fmt='rgba', bits_per_pixel=32,
                             input_params=['-c:v','libvpx-vp9'])
  可正确保留 alpha 通道，输出 RGBA 原始帧字节。

线程模型：
- 后台 reader 线程把 RGBA 字节放入有界队列；
- 主线程 QTimer 按视频 fps 从队列取帧，构造 QImage/QPixmap 并发出 frameChanged；
- 所有 Qt GUI 操作只发生在主线程。
"""
from __future__ import annotations

import logging
import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap

logger = logging.getLogger(__name__)

try:
    import imageio_ffmpeg
except Exception as exc:  # pragma: no cover
    imageio_ffmpeg = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class WebMPlayer(QObject):
    """单个 webm 动画的播放器。"""

    frameChanged = Signal(int)      # 帧序号
    finished = Signal()             # 播放结束
    errorOccurred = Signal(str)

    def __init__(self, path, width: int = 640, height: int = 360,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = str(path)
        self._w = width
        self._h = height
        self._bpp = 4  # RGBA

        self._frame_count = 0
        self._duration = 0.0
        self._fps = 24.0
        self.playback_speed = 1.0

        self._queue: queue.Queue = queue.Queue(maxsize=8)
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self._timer_interval())
        self._timer.timeout.connect(self._poll)

        self._current_pixmap: QPixmap | None = None
        self._first_pixmap: QPixmap | None = None
        self._frame_index = 0
        self._ended_fired = False
        self._running = False

    # ------------------------------------------------------------ 元数据
    def _timer_interval(self) -> int:
        if self._fps > 0:
            return max(1, int(round(1000 / (self._fps * self.playback_speed))))
        return max(1, int(round(40 / self.playback_speed)))

    def _ensure_meta(self) -> None:
        if self._duration > 0 or imageio_ffmpeg is None:
            return
        try:
            frames, secs = imageio_ffmpeg.count_frames_and_secs(self.path)
            if frames and frames > 0:
                self._frame_count = int(frames)
            if secs and secs > 0:
                self._duration = float(secs)
            if self._frame_count > 0 and self._duration > 0:
                self._fps = self._frame_count / self._duration
        except Exception as exc:
            logger.warning('webm 元数据读取失败 %s: %s', self.path, exc)

    # ------------------------------------------------------------ 播放控制
    def play(self) -> None:
        if self._running:
            return
        if imageio_ffmpeg is None:
            self.errorOccurred.emit(str(_IMPORT_ERROR or 'imageio_ffmpeg 不可用'))
            return
        self._ensure_meta()
        self._timer.setInterval(self._timer_interval())
        # 每次播放都新建 queue / stop 事件，并作为「本次运行」的凭据传给 reader。
        # 这样即使上一轮的 reader 线程还没退出，它也只操作自己那份 queue，
        # 不会往新一轮的队列里塞帧或塞结束标记（否则会出现帧堆积 / 乱发 finished）。
        self._stop_evt = threading.Event()
        self._queue = queue.Queue(maxsize=8)
        self._frame_index = 0
        self._ended_fired = False
        self._running = True
        run_queue = self._queue
        run_stop = self._stop_evt
        self._thread = threading.Thread(
            target=self._reader, args=(run_queue, run_stop), daemon=True)
        self._thread.start()
        self._timer.start()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        if self._stop_evt is not None:
            self._stop_evt.set()
        # 不 join：reader 是 daemon 线程，避免切换动画时阻塞 UI
        self._thread = None

    def current_pixmap(self) -> QPixmap | None:
        return self._current_pixmap

    def first_pixmap(self) -> QPixmap | None:
        return self._first_pixmap

    # ------------------------------------------------------------ 后台解码
    def _reader(self, run_queue: "queue.Queue", run_stop: threading.Event) -> None:
        """后台解码线程。run_queue / run_stop 是本次运行专属的凭据。"""
        gen = None
        try:
            gen = imageio_ffmpeg.read_frames(
                self.path,
                pix_fmt='rgba',
                bits_per_pixel=self._bpp * 8,
                input_params=['-c:v', 'libvpx-vp9'],
            )
            meta = next(gen)
            if meta.get('fps'):
                self._fps = float(meta['fps'])
            if meta.get('duration'):
                self._duration = float(meta['duration'])
            if self._frame_count <= 0 and self._fps > 0 and self._duration > 0:
                self._frame_count = int(round(self._fps * self._duration))

            for frame in gen:
                if run_stop.is_set():
                    break
                try:
                    run_queue.put(frame, timeout=0.2)
                except queue.Full:
                    # 队列满说明 UI 消费不过来；丢弃这一帧，保持实时性
                    pass
            # 正常播完时放入结束标记（None），循环重试直到放入或收到停止信号
            while not run_stop.is_set():
                try:
                    run_queue.put(None, timeout=0.5)
                    break
                except queue.Full:
                    continue
        except Exception as exc:
            logger.exception('webm 解码失败: %s', self.path)
            self.errorOccurred.emit(str(exc))
            while not run_stop.is_set():
                try:
                    run_queue.put(None, timeout=0.5)
                    break
                except queue.Full:
                    continue
        finally:
            if gen is not None:
                try:
                    gen.close()
                except Exception:
                    pass

    # ------------------------------------------------------------ 主线程取帧
    def _poll(self) -> None:
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return
        if item is None:
            # 正常播完
            if not self._ended_fired:
                self._ended_fired = True
                self._running = False
                self._timer.stop()
                self.finished.emit()
            return
        # 构造 QImage
        expect = self._w * self._h * self._bpp
        if len(item) == expect:
            img = QImage(item, self._w, self._h, self._w * self._bpp,
                         QImage.Format.Format_RGBA8888)
            if not img.isNull():
                pm = QPixmap.fromImage(img)
                self._current_pixmap = pm
                if self._first_pixmap is None:
                    self._first_pixmap = pm
                self._frame_index += 1
                self.frameChanged.emit(self._frame_index)
