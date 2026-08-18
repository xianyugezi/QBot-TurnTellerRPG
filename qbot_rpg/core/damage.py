"""伤害公式求值（M1 实装 · 本里程碑仅骨架）。

M1 实装依据：细化_1a_伤害公式数值（双通道物理/元素独立 floor 后相加，L119；
判定顺序：命中→会心→格挡→双通道伤害→防御率→伤害拦截链→扣血，L100）；
细化_3b_玩家属性三层 §5 派生属性输出接入（会心率 M5 / 会心倍率 M4 / 格挡 M7）。
安全表达式求值（【框架】L1572，白名单 / 无 eval 注入面）。

本里程碑（M0）仅定义模块职责与占位签名，不写业务逻辑；零 NoneBot import（3a R1）。
"""
from __future__ import annotations

from typing import Any

__all__ = ["DamageCalculator"]

_NOT_IMPL_MSG = "M1 实装：伤害公式求值（细化_1a / 细化_3b §5）"


class DamageCalculator:
    """公式求值器（安全表达式 / 双通道）。M1 实装，本里程碑仅签名。"""

    def calculate(self, formula_state: Any, context: Any) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)
