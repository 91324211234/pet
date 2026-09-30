# -*- coding: utf-8 -*-
"""
设置对话框 —— 配置 LLM 接口（Base URL / API Key / 模型 / 系统提示词）。

- 打开时回填当前配置，取消不做任何修改；
- 确定时校验并写回 Config（由调用方负责落盘）；
- 提供「恢复默认」和「测试连接」（后台线程发一条最小请求）。
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from config import DEFAULT_CONFIG, FIELD_ORDER

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """API 设置对话框。exec() 返回 Accepted 时可用 values() 取新配置。"""

    # 后台测试连接的结果回调（在主线程执行）
    _test_done = Signal(bool, str)

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle('设置 · 大肥鱼')
        self.setMinimumWidth(460)

        form = QFormLayout()

        self.base_url_edit = QLineEdit(config.get('base_url'))
        self.base_url_edit.setPlaceholderText('http://127.0.0.1:9960/v1')
        form.addRow('接口地址', self.base_url_edit)

        # API Key：默认打码，右侧小眼睛切换明文
        self.api_key_edit = QLineEdit(config.get('api_key'))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText('sk-...')
        self._eye_btn = QPushButton('显示')
        self._eye_btn.setCheckable(True)
        self._eye_btn.setFixedWidth(56)
        self._eye_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._eye_btn.toggled.connect(self._toggle_key_echo)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.api_key_edit)
        key_row.addWidget(self._eye_btn)
        form.addRow('API Key', key_row)

        self.model_edit = QLineEdit(config.get('model'))
        self.model_edit.setPlaceholderText('vllm/deepseek-v4-flash-0731')
        form.addRow('模型', self.model_edit)

        self.prompt_edit = QPlainTextEdit(config.get('system_prompt'))
        self.prompt_edit.setPlaceholderText('给桌宠设定的人设，留空则用默认')
        self.prompt_edit.setFixedHeight(96)
        form.addRow('系统提示词', self.prompt_edit)

        self._status = QLabel('')
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        self._test_btn = QPushButton('测试连接')
        self._test_btn.clicked.connect(self._on_test_clicked)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存')
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')

        reset_btn = QPushButton('恢复默认')
        reset_btn.clicked.connect(self._on_reset)

        bottom = QHBoxLayout()
        bottom.addWidget(self._test_btn)
        bottom.addWidget(reset_btn)
        bottom.addStretch(1)
        bottom.addWidget(self._buttons)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self._status)
        root.addLayout(bottom)

        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        self._test_done.connect(self._on_test_done)

    # ------------------------------------------------------------ 交互
    def _toggle_key_echo(self, shown: bool) -> None:
        self.api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self._eye_btn.setText('隐藏' if shown else '显示')

    def _on_reset(self) -> None:
        self.base_url_edit.setText(DEFAULT_CONFIG['base_url'])
        self.api_key_edit.setText(DEFAULT_CONFIG['api_key'])
        self.model_edit.setText(DEFAULT_CONFIG['model'])
        self.prompt_edit.setPlainText(DEFAULT_CONFIG['system_prompt'])
        self._set_status('已填入默认值，点「保存」生效', ok=True)

    def _on_accept(self) -> None:
        if not self.base_url_edit.text().strip():
            self._set_status('接口地址不能为空', ok=False)
            self.base_url_edit.setFocus()
            return
        if not self.model_edit.text().strip():
            self._set_status('模型名不能为空', ok=False)
            self.model_edit.setFocus()
            return
        self.accept()

    # ------------------------------------------------------------ 取值
    def values(self) -> dict:
        """返回对话框里的配置（保持 FIELD_ORDER 顺序）。"""
        raw = {
            'base_url': self.base_url_edit.text().strip(),
            'api_key': self.api_key_edit.text().strip(),
            'model': self.model_edit.text().strip(),
            'system_prompt': self.prompt_edit.toPlainText().strip(),
        }
        if not raw['system_prompt']:
            raw['system_prompt'] = DEFAULT_CONFIG['system_prompt']
        return {key: raw[key] for key in FIELD_ORDER}

    # ------------------------------------------------------------ 测试连接
    def _set_status(self, text: str, ok: bool | None = None) -> None:
        color = {True: '#1a7f37', False: '#c62828', None: '#5f6368'}[ok]
        self._status.setStyleSheet(f'color: {color};')
        self._status.setText(text)

    def _on_test_clicked(self) -> None:
        values = self.values()
        if not values['base_url']:
            self._set_status('先填接口地址再测试', ok=False)
            return
        self._test_btn.setEnabled(False)
        self._set_status('正在测试连接…', ok=None)
        threading.Thread(
            target=self._test_worker, args=(values,), daemon=True).start()

    def _test_worker(self, values: dict) -> None:
        """后台线程：发一条最小 chat 请求验证配置是否可用。"""
        url = values['base_url'].rstrip('/') + '/chat/completions'
        body = json.dumps({
            'model': values['model'],
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 8,
        }).encode('utf-8')
        req = urllib.request.Request(
            url, data=body, method='POST',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {values['api_key']}",
            })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            content = str(data['choices'][0]['message']['content']).strip()
            self._test_done.emit(True, f'连接成功，模型回复：{content[:60]}')
        except Exception as exc:
            self._test_done.emit(False, f'连接失败：{exc}')

    def _on_test_done(self, ok: bool, message: str) -> None:
        self._test_btn.setEnabled(True)
        self._set_status(message, ok=ok)


def ask_settings(config, parent=None) -> dict | None:
    """弹出设置对话框。用户点了保存则返回新配置字典，取消返回 None。"""
    dlg = SettingsDialog(config, parent)
    try:
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.values()
    except Exception as exc:  # pragma: no cover - 防御性兜底
        logger.exception('设置对话框异常: %s', exc)
        QMessageBox.warning(parent, '设置', f'打开设置失败：{exc}')
        return None