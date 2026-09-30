# -*- coding: utf-8 -*-
"""
动画目录 —— 自己扫描资源目录构建动画清单，不依赖任何外部项目代码。

资源目录结构（videos/ 下按分类子目录组织）：
    videos/
    ├── idle/    待机动画
    ├── turn/    转向动画
    ├── move/    移动动画（走路姿态）
    ├── click/   点击回应动画
    ├── drag/    拖拽动画
    └── random/  随机动作池

每个子目录里的 .webm 文件名即动画名（中文）。
"""
from __future__ import annotations

from pathlib import Path

# 画布几何（webm 素材为 640×360 透明视频，脚底在 y=330）
CANVAS_W = 640
CANVAS_H = 360
FEET_Y = 330
PAD = CANVAS_H - FEET_Y  # 落地偏移 30px

# 动画链概率：30% 待机 / 10% 转向 / 40% 动作 / 20% 移动
P_IDLE = 0.30
P_TURN = 0.40
P_ACTS = 0.80

# 移动参数
MOVE_MIN_PX = 60
MOVE_MAX_PX = 240
MOVE_MARGIN = 20
MOVE_LEAD_SEC = 2.0   # 动画开头 2s 准备，位置不动
MOVE_TAIL_SEC = 2.0   # 动画结尾 2s 收尾，位置不动

# 拖拽判定阈值（逻辑像素）
DRAG_THRESHOLD = 5

# 默认显示缩放与右下角边距
DEFAULT_SCALE = 0.72
CORNER_MARGIN = 24
SCALE_STEPS = (0.5, 0.72, 0.85, 1.0)

# 分类子目录名
DIR_IDLE = 'idle'
DIR_TURN = 'turn'
DIR_MOVE = 'move'
DIR_CLICK = 'click'
DIR_DRAG = 'drag'
DIR_RANDOM = 'random'

# 默认资源目录：项目自带的 assets/videos（clone 下来即可用）
DEFAULT_ASSET_DIR = Path(__file__).resolve().parent / 'assets' / 'videos'


class Catalog:
    """扫描资源目录，构建动画分类清单。"""

    def __init__(self, asset_dir: Path | str | None = None) -> None:
        self.asset_dir = Path(asset_dir) if asset_dir else DEFAULT_ASSET_DIR
        self.idles: list[str] = []
        self.turns: list[str] = []
        self.moves: list[str] = []
        self.clicks: list[str] = []
        self.drag: str | None = None
        self.acts: list[str] = []
        self.all_names: list[str] = []
        self._scan()

    def _scan(self) -> None:
        """扫描 videos/ 下各分类子目录，收集动画名。"""
        if not self.asset_dir.is_dir():
            raise FileNotFoundError(f'资源目录不存在: {self.asset_dir}')

        def _collect(sub: str) -> list[str]:
            d = self.asset_dir / sub
            if not d.is_dir():
                return []
            return sorted(p.stem for p in d.glob('*.webm'))

        self.idles = _collect(DIR_IDLE)
        self.turns = _collect(DIR_TURN)
        self.moves = _collect(DIR_MOVE)
        self.clicks = _collect(DIR_CLICK)
        drags = _collect(DIR_DRAG)
        self.drag = drags[0] if drags else None
        self.acts = _collect(DIR_RANDOM)

        # 汇总全部动画名（去重保序）
        seen: set[str] = set()
        for name in (self.idles + self.turns + self.moves + self.clicks
                     + ([self.drag] if self.drag else []) + self.acts):
            if name not in seen:
                seen.add(name)
                self.all_names.append(name)

        if not self.idles:
            raise RuntimeError('资源目录中未找到 idle 动画')

    def path_for(self, name: str) -> Path:
        """根据动画名定位 webm 文件路径。"""
        for sub in (DIR_IDLE, DIR_TURN, DIR_MOVE, DIR_CLICK, DIR_DRAG, DIR_RANDOM):
            p = self.asset_dir / sub / f'{name}.webm'
            if p.is_file():
                return p
        raise FileNotFoundError(f'找不到动画文件: {name}')

    def count(self) -> int:
        return len(self.all_names)
