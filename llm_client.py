# -*- coding: utf-8 -*-
"""
LLM 聊天客户端 —— 直接调用本地 LLM API（不经过 opencode）。

- 配置从 config.Config（config.json）实时读取，可在设置对话框里修改
- 维护对话历史（角色 + 内容），支持文件持久化
- 调用 OpenAI 兼容的 /chat/completions 接口
- 提供清空上下文的方法
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from pathlib import Path

from config import Config

logger = logging.getLogger(__name__)

# 上下文窗口：最多保留最近 N 条消息（不含系统提示）
MAX_HISTORY = 20

# 对话历史文件（与脚本同目录）
HISTORY_FILE = Path(__file__).resolve().parent / 'chat_history.json'


class LLMClient:
    """带文件持久化上下文的 LLM 聊天客户端。"""

    def __init__(self, history_file: Path | str | None = None,
                 config: Config | None = None) -> None:
        self.history_file = Path(history_file) if history_file else HISTORY_FILE
        self.config = config if config is not None else Config()
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._load()

    # ------------------------------------------------------------ 配置
    def apply_config(self, config: Config) -> None:
        """替换配置对象（设置保存后由界面调用）。"""
        self.config = config

    # ------------------------------------------------------------ 历史管理
    def _load(self) -> None:
        """从文件加载历史（仅 assistant/user 消息）。"""
        try:
            if self.history_file.is_file():
                data = json.loads(self.history_file.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    self._history = [
                        m for m in data
                        if isinstance(m, dict) and m.get('role') in ('user', 'assistant')
                    ]
        except Exception as exc:
            logger.warning('加载对话历史失败: %s', exc)
            self._history = []

    def _save(self) -> None:
        """把历史写入文件。"""
        try:
            self.history_file.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding='utf-8')
        except Exception as exc:
            logger.warning('保存对话历史失败: %s', exc)

    def clear(self) -> None:
        """清空上下文并删除历史文件。"""
        with self._lock:
            self._history = []
            try:
                if self.history_file.exists():
                    self.history_file.unlink()
            except Exception as exc:
                logger.warning('删除历史文件失败: %s', exc)

    def history_count(self) -> int:
        with self._lock:
            return len(self._history)

    # ------------------------------------------------------------ 聊天
    def chat(self, text: str, timeout: float = 60.0) -> str:
        """发送用户消息，返回 LLM 回复文本。会更新并持久化上下文。"""
        text = str(text).strip()
        if not text:
            return ''

        with self._lock:
            self._history.append({'role': 'user', 'content': text})
            # 构造请求消息：系统提示 + 最近 MAX_HISTORY 条
            system_prompt = self.config.get('system_prompt')
            messages = [{'role': 'system', 'content': system_prompt}]
            messages.extend(self._history[-MAX_HISTORY:])

        reply = self._request(messages, timeout=timeout)

        with self._lock:
            self._history.append({'role': 'assistant', 'content': reply})
            self._save()
        return reply

    def _request(self, messages: list[dict], timeout: float) -> str:
        """调用配置里的 LLM API。"""
        base_url = self.config.get('base_url').rstrip('/')
        api_key = self.config.get('api_key')
        model = self.config.get('model')
        if not base_url or not model:
            return '（还没配置好接口，右键我 →「设置…」填一下接口地址和模型吧）'

        url = base_url + '/chat/completions'
        body = json.dumps({
            'model': model,
            'messages': messages,
            'max_tokens': 500,
            'temperature': 0.8,
        }).encode('utf-8')
        req = urllib.request.Request(
            url, data=body, method='POST',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            content = data['choices'][0]['message']['content']
            return str(content).strip()
        except Exception as exc:
            logger.error('LLM 调用失败: %s', exc)
            return f'（哎呀，我这边出了点问题：{exc}）'