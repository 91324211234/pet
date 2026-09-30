# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 主程序入口。

用法：
    python main.py [--assets <资源目录>]

依赖：
    pip install PySide6 imageio-ffmpeg Pillow
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from catalog import Catalog
from pet_window import PetWindow

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('main')


def build_tray(app: QApplication, window: PetWindow) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(QIcon(), app)
    tray.setToolTip('大肥鱼桌宠')

    menu = QMenu()
    show_act = menu.addAction('显示桌宠')
    show_act.triggered.connect(lambda: (window.show(), window.raise_()))
    hide_act = menu.addAction('隐藏桌宠')
    hide_act.triggered.connect(window.hide)
    menu.addSeparator()
    quit_act = menu.addAction('退出')
    quit_act.triggered.connect(app.quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    return tray


def main() -> int:
    parser = argparse.ArgumentParser(description='大肥鱼桌宠')
    parser.add_argument('--assets', default=None,
                        help='动画资源目录（videos 的父目录）')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    try:
        cat = Catalog(args.assets)
    except Exception as exc:
        logger.error('初始化资源目录失败: %s', exc)
        logger.error('默认资源目录是 %s',
                     args.assets or 'assets/videos（项目自带）')
        logger.error('如果素材在别处，用 --assets 指定：'
                     'python main.py --assets "D:\\path\\to\\videos"')
        return 1

    logger.info('加载动画 %d 个（idle=%d turn=%d move=%d click=%d drag=%s random=%d）',
                cat.count(), len(cat.idles), len(cat.turns), len(cat.moves),
                len(cat.clicks), cat.drag, len(cat.acts))

    window = PetWindow(cat)
    window.show()

    if QSystemTrayIcon.isSystemTrayAvailable():
        build_tray(app, window)
    else:
        logger.warning('系统托盘不可用，跳过托盘图标')

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
