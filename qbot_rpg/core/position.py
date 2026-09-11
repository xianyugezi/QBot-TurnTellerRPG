"""方位战斗系统核心原语（草案 v0.6 §三.1/§三.2 + 附录 A Step 1）。

文件名：position.py
创建时间：2026-09-08
作者：Hermes Agent（方位战斗系统框架改造 Step 1）

功能描述：
  - 8 方位格模型常量：side ∈ {front/back/left/right} × height ∈ {ground/air}
  - position_of(snapshot, side)：读战斗快照某 combatant 的方位。缺 combat_position 段/
    缺键/非法值 → 缺省正面贴地（front/ground）——旧快照无段不崩（对齐 resource_state
    RS-5 缺段降级口径）。
  - rule_permits(rule, side, height)：ActionCore position_rule 命中资格判定。规则缺省
    （None/空 dict）=全量；单轴缺省或空数组=该轴全量；两轴都命中才放行。
  - spec_permits(spec, pos)：position_match 条件统一原语（怪物 trigger / combo 条件
    共用同一 shape：{"which": ..., "side": [...], "height": [...]} → 按位置求值）。

语义边界（与定稿对应）：
  - 玩家技能 position_rule 的消费点是「部位命中资格」（附录 A Step 2 part resolve），
    Step 1 只登记/校验不消费；怪物行动 position_rule 的消费点 = 玩家位置 miss 检查
    （未命中，§四 height check，Step 1 接线于 battle._resolve_combo_action）。
  - 位置轴永远「只建议不限制」的校验口径：枚举外值红拦，范围/组合不拦。

纯函数，零 NoneBot import；确定性；防御性（非法输入 fail-safe 不抛错）。
"""

from __future__ import annotations

from typing import Mapping, Tuple

__all__ = [
    "POSITION_SIDES",
    "POSITION_HEIGHTS",
    "DEFAULT_SIDE",
    "DEFAULT_HEIGHT",
    "DEFAULT_POSITION",
    "position_of",
    "rule_permits",
    "spec_permits",
]

POSITION_SIDES: Tuple[str, ...] = ("front", "back", "left", "right")
"""方位格 side 四枚举（草案 §三.1：front/back/left/right）。"""

POSITION_HEIGHTS: Tuple[str, ...] = ("ground", "air")
"""高度二枚举（草案 §三.1：ground 地面 / air 空中）。"""

DEFAULT_SIDE: str = "front"
DEFAULT_HEIGHT: str = "ground"
DEFAULT_POSITION: Mapping[str, str] = {"side": DEFAULT_SIDE, "height": DEFAULT_HEIGHT}
"""缺省方位（正面贴地）：战斗快照缺段/缺键的降级值（RS-5 口径）。"""


def _clean_axes(value: object) -> Tuple[str, ...]:
    """轴值归一：list/tuple 内非空字符串；str 单值包装；None/非法形态 → ()（=全量）。

    引擎侧防御性归一（校验器已红拦枚举外值；此处容忍坏数据不抛错，坏值视为该轴不设限
    会放大命中面——安全方向）。"""
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple)):
        return tuple(x for x in value if isinstance(x, str) and x)
    return ()


def position_of(snapshot: Mapping, side: str) -> Tuple[str, str]:
    """读战斗快照某 combatant 当前方位 (side, height)。

    参数：
      snapshot: 战斗快照（_snap / battle_state / to_snapshot 同构 dict）
      side: combatant 侧键（"player"/"enemy"，对齐快照 per-side 惯例）
    返回：
      (side, height) 归一化元组；快照缺 combat_position 段 / 该侧缺条目 / 值非法 →
      (front, ground)（缺省正面贴地，旧快照无段不崩）。
    """
    cp = snapshot.get("combat_position")
    if not isinstance(cp, Mapping):
        return DEFAULT_SIDE, DEFAULT_HEIGHT
    ent = cp.get(side)
    if not isinstance(ent, Mapping):
        return DEFAULT_SIDE, DEFAULT_HEIGHT
    s = ent.get("side")
    h = ent.get("height")
    return (
        s if isinstance(s, str) and s in POSITION_SIDES else DEFAULT_SIDE,
        h if isinstance(h, str) and h in POSITION_HEIGHTS else DEFAULT_HEIGHT,
    )


def rule_permits(rule: object, side: str, height: str) -> bool:
    """position_rule 命中资格判定（草案 §三.2）：行动打不打得到 (side, height) 格。

    参数：
      rule: position_rule dict（{"side": [...], "height": [...]}）；None/空/非 Mapping
            = 全量放行
      side / height: 目标当前方位（引擎侧应先经 position_of 归一）
    返回：
      两轴（显式限定者）都覆盖当前格 → True；任一显式轴未覆盖 → False。
    """
    if not isinstance(rule, Mapping) or not rule:
        return True
    allowed_sides = _clean_axes(rule.get("side"))
    if allowed_sides and side not in allowed_sides:
        return False
    allowed_heights = _clean_axes(rule.get("height"))
    if allowed_heights and height not in allowed_heights:
        return False
    return True


def spec_permits(spec: object, pos: Tuple[str, str]) -> bool:
    """position_match 条件原语统一求值（spec 内 side/height 轴 → 目标格）。

    参数：
      spec: 条件 spec（怪物 trigger / combo 条件共用 shape；额外键如 which 被忽略——
            目标格由调用方按 which 解析后传入）
      pos: 目标格 (side, height)（经 position_of 归一）
    返回：
      轴全部放行 → True（rule_permits 同语义，供条件引擎统一调用）。
    """
    return rule_permits(spec, pos[0], pos[1])
