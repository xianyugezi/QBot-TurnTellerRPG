"""统一发送出口壳 Sender（M4 实装 · 本里程碑仅接口签名）。

职责（细化_3a §1.3 / §5.3 壳层发送职责 · 唯一发送出口）：
  - CQ 转义（对 message_format 纯字符串做段级转义防注入，【框架】L1622/【规则】L510）
  - 长度预算分条（超长分两条发送，不吞消息，【规则】L507；S5）
  - 失败重试 + 风控退避（指数退避，不无限重发，【规则】L503/L523）
  - 禁止裸 send：所有发送路径必须收敛本出口（【规则】L523；3a TC-21）
  - 频率控制：全局 ≥1s / 单群 ≤20 条·分 / 单日上限（【规则】L499-501）

本里程碑（M0）零 nonebot import（3a R1）；发送器为壳层唯一 NoneBot 接触位置之一（M4）。
"""
from __future__ import annotations

from typing import Any, List

__all__ = ["Sender", "segment_by_length"]

# 单条消息长度预算（字符；超长分条，规则 L507/框架 L1346）
DEFAULT_LENGTH_BUDGET: int = 4500

_NOT_IMPL_MSG = "M4 实装：统一发送出口（CQ 转义/分条/退避/频率；细化_3a §5.3）"


class Sender:
    """统一发送出口（M4 接线 bot.send；本里程碑仅签名，零 nonebot）。"""

    def __init__(self) -> None:
        self._client: Any = None

    def send(self, text: str, *, to: Any = None) -> None:
        """M4 实装：CQ 转义 → 长度分条 → 发送（失败重试+风控退避）。"""
        raise NotImplementedError(_NOT_IMPL_MSG)


def segment_by_length(
    text: str,
    budget: int = DEFAULT_LENGTH_BUDGET,
) -> List[str]:
    """M4 实装：按长度预算分条（顺序不颠倒，S5 不吞内容）。"""
    raise NotImplementedError(_NOT_IMPL_MSG)
