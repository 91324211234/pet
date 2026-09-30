# -*- coding: utf-8 -*-
"""
文件处理 —— 判断能不能「吃」，以及把文件移入回收站。

- 只接受普通文件，且扩展名在白名单里（文本/文档/快捷方式等）
- 删除走 Windows 回收站（SHFileOperationW + FOF_ALLOWUNDO），可撤销
- 非 Windows 平台退化为普通删除，并在返回值里说明
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

# 允许「吃」的扩展名（小写，含点）
ALLOWED_EXTENSIONS = {
    # 纯文本
    '.txt', '.md', '.log', '.ini', '.cfg', '.conf', '.csv', '.json',
    '.xml', '.yaml', '.yml', '.toml', '.rst', '.tex',
    # 文档
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.rtf', '.odt', '.ods', '.odp',
    # 快捷方式
    '.lnk', '.url',
}

# 单次最多处理多少个文件，防止误拖一大坨
MAX_FILES = 20


class RecycleResult:
    """一次「吃掉」操作的结果。"""

    def __init__(self, successes: list[str], failures: list[tuple[str, str]]) -> None:
        self.successes = successes
        self.failures = failures

    @property
    def ok(self) -> bool:
        return bool(self.successes)

    @property
    def all_ok(self) -> bool:
        return bool(self.successes) and not self.failures

    def summary(self) -> str:
        parts = []
        if self.successes:
            parts.append(f'吃掉 {len(self.successes)} 个')
        if self.failures:
            parts.append(f'{len(self.failures)} 个没吃成')
        return '，'.join(parts) or '什么也没吃'


def classify_paths(paths: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """把拖进来的路径分成「可吃的文件」和「不合格的（路径, 原因）」。"""
    accepted: list[str] = []
    rejected: list[tuple[str, str]] = []
    seen: set[str] = set()

    for raw in paths:
        path = str(raw).strip()
        if not path:
            continue
        # 归一化，避免同一文件重复
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)

        p = Path(path)
        name = p.name or path
        if p.is_dir():
            rejected.append((name, '文件夹不能吃'))
            continue
        if not p.exists():
            rejected.append((name, '文件不存在'))
            continue
        if p.suffix.lower() not in ALLOWED_EXTENSIONS:
            shown = p.suffix or '（无扩展名）'
            rejected.append((name, f'不支持的类型 {shown}'))
            continue
        accepted.append(str(p))

    if len(accepted) > MAX_FILES:
        for extra in accepted[MAX_FILES:]:
            rejected.append((Path(extra).name, f'一次最多 {MAX_FILES} 个'))
        accepted = accepted[:MAX_FILES]

    return accepted, rejected


def _to_recycle_bin(path: str) -> bool:
    """Windows：移入回收站，可撤销。"""
    FO_DELETE = 0x0003
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040       # 关键：走回收站而不是真删
    FOF_NOERRORUI = 0x0400

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('wFunc', wintypes.UINT),
            ('pFrom', wintypes.LPCWSTR),
            ('pTo', wintypes.LPCWSTR),
            ('fFlags', ctypes.c_uint16),
            ('fAnyOperationsAborted', wintypes.BOOL),
            ('hNameMappings', ctypes.c_void_p),
            ('lpszProgressTitle', wintypes.LPCWSTR),
        ]

    # pFrom 以单个 \0 分隔多个路径，最后用 \0\0 结束
    src = '\0'.join(os.path.abspath(path) for path in [path]) + '\0\0'
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = src
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0:
        logger.warning('SHFileOperationW 失败 code=%s: %s', result, path)
        return False
    if op.fAnyOperationsAborted:
        logger.info('用户取消了删除: %s', path)
        return False
    return True


def delete_to_recycle_bin(path: str) -> bool:
    """把单个文件移入回收站。成功返回 True。"""
    if sys.platform == 'win32':
        try:
            return _to_recycle_bin(path)
        except Exception as exc:
            logger.warning('移入回收站失败 %s: %s', path, exc)
            return False
    # 非 Windows 没有回收站概念，退化为删除
    try:
        os.remove(path)
        return True
    except Exception as exc:
        logger.warning('删除失败 %s: %s', path, exc)
        return False


def delete_many(paths: list[str]) -> RecycleResult:
    """逐个把文件移入回收站，收集成功与失败。"""
    successes: list[str] = []
    failures: list[tuple[str, str]] = []
    for path in paths:
        if delete_to_recycle_bin(path):
            successes.append(path)
        else:
            failures.append((Path(path).name, '删除失败或被取消'))
    return RecycleResult(successes, failures)