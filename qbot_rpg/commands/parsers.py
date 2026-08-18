"""指令解析壳 Parsers（M4 实装 · 本里程碑仅接口签名）。

职责（细化_3a §1.3；【框架】L1261-1264 指令分隔符规范统一在壳层解析）：
空格分参、`*` 数量、`,` 列表、`=` 键值对、页码最后一个整数参数（细化_3d §2.2）。
M4 实装依据：细化_3c_指令解析契约。

本里程碑（M0）**零 nonebot import**（3a R1）；解析器为纯函数，可脱离平台单测。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ParsedCommand",
    "parse_command",
    "parse_int",
]

_NOT_IMPL_MSG = "M4 实装：指令分隔符解析（细化_3c / 细化_3a §1.3）"


class ParsedCommand:
    """指令解析结果（M4 实装：name + 位置参数 + 键值对）。"""

    def __init__(
        self,
        name: str,
        args: List[str],
        kwargs: Dict[str, str],
    ) -> None:
        self.name = name
        self.args: List[str] = args
        self.kwargs: Dict[str, str] = kwargs

    def arg(self, index: int, default: Optional[str] = None) -> Optional[str]:
        return self.args[index] if index < len(self.args) else default


def parse_command(raw: str) -> ParsedCommand:
    """M4 实装：按分隔符规范解析指令原文（防注入：前缀样式文本不影响解析，3d TC-26）。"""
    raise NotImplementedError(_NOT_IMPL_MSG)


def parse_int(text: str) -> Optional[int]:
    """M4 实装：安全整数解析（页码等；非法返回 None → 壳层 TPL-12，3d §2.2）。"""
    raise NotImplementedError(_NOT_IMPL_MSG)
