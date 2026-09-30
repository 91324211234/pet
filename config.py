# -*- coding: utf-8 -*-
"""
配置管理 —— 把 LLM 接口配置从代码里抽出来，读写同目录下的 config.json。

首次运行时会用 llm_client 里的默认值生成 config.json；之后用户在
右键菜单「设置…」里改的内容都会存到这里，重启依然有效。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置文件（与脚本同目录）
CONFIG_FILE = Path(__file__).resolve().parent / 'config.json'

# 默认配置：老代码里硬编码的值搬到这里，保持向后兼容
DEFAULT_CONFIG = {
    'base_url': 'http://192.168.8.101:9960/v1',
    'api_key': 'sk-bf-team-b-xxxx',
    'model': 'vllm/deepseek-v4-flash-0731',
    'system_prompt': (
        '你是"大肥鱼"，一个活泼可爱的桌面宠物。'
        '你陪用户聊天、解闷，回答要简短、亲切、口语化，'
        '一般不超过 3 句话。不要提及你是 AI 模型。'
    ),
}

# 字段顺序，供设置对话框生成表单
FIELD_ORDER = ('base_url', 'api_key', 'model', 'system_prompt')


class Config:
    """带文件持久化的配置。字段通过 self.data 字典访问。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else CONFIG_FILE
        self.data: dict = dict(DEFAULT_CONFIG)
        self._load()

    # ------------------------------------------------------------ 读写
    def _load(self) -> None:
        """从 config.json 读取；文件不存在或缺字段时用默认值补齐。"""
        if not self.path.is_file():
            self._save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning('读取配置文件失败（将使用默认配置）: %s', exc)
            return
        if not isinstance(raw, dict):
            logger.warning('配置文件格式不对（应为 JSON 对象），使用默认配置')
            return
        # 只接受已知字段，忽略多余键
        for key in DEFAULT_CONFIG:
            if key in raw:
                self.data[key] = str(raw[key])

    def _save(self) -> None:
        """把当前配置写入 config.json。"""
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding='utf-8')
        except Exception as exc:
            logger.warning('保存配置文件失败: %s', exc)

    # ------------------------------------------------------------ 访问
    def get(self, key: str, default: str = '') -> str:
        value = self.data.get(key)
        return default if value is None else str(value)

    def update(self, values: dict) -> None:
        """批量更新字段并落盘（只接受已知字段）。"""
        for key, value in values.items():
            if key in DEFAULT_CONFIG:
                self.data[key] = str(value)
        self._save()