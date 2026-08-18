"""战斗消息渲染（M1 实装 · 本里程碑仅骨架签名）。

归属：core/message_format（细化_3a §2.1 / §5，原 engine 渲染职责，D-04 归入引擎层）。
M1 实装依据：
  - 细化_1g2_回合时序与拦截链（回合迁移/行动+反击合并语义）
  - 细化_1a_伤害公式数值（伤害结果文案）
  - 细化_5e_战斗战报格式（含检测状态行）
  - 细化_3d_消息模板规范 §1.5/§3.1（前缀首行、一轮战斗仍 1 条消息、合并策略）
    §1.2 TPL-01（前缀）、§2.1 5 条/页（战斗日志流水分页日常见 M1 细化）。

契约约束（即使 M1 实装也必须遵守，见 3a §5.2）：
  - S1：返回 `str`；S2：无 "[CQ:"；S3：无 at/图片/表情段占位；
  - S4：一轮一条消息 —— 玩家行动结算 + 怪物反击结算合并为 1 条字符串；
  - S5：渲染层不截断不吞内容（超长分条是壳层 sender 职责）。
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "render_battle_start",
    "render_battle_round",
    "render_battle_end",
]

_NOT_IMPL_MSG = "M1 实装：战斗渲染（细化_1g / 细化_1a / 细化_5e / 细化_3d §三）"


def render_battle_start(
    party: Any,
    enemy: Any,
    hint: Optional[str] = None,
) -> str:
    """战斗开始渲染（围：锁定开战消息；含双方概况与操作提示）。TODO(M1)。"""
    raise NotImplementedError(_NOT_IMPL_MSG)


def render_battle_round(round_result: Any) -> str:
    """战斗一轮渲染（拒：玩家行动 + 怪物反击合并 1 条，含行动/伤害/反击/状态行）。TODO(M1)。"""
    raise NotImplementedError(_NOT_IMPL_MSG)


def render_battle_end(
    player: Any,
    enemy: Any,
    winner: str,
    summary: Optional[Any] = None,
) -> str:
    """战斗结束渲染（围：胜负/经验/掉落/存活状态）。TODO(M1)。"""
    raise NotImplementedError(_NOT_IMPL_MSG)
