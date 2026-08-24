"""状态面板 / 列表渲染（细化_3a §5 纯字符串契约 / 细化_3d §二 列表分页 / 【框架】L1390-1396）。

- ``render_panel``：玩家基础状态面板 —— 前缀首行（仅首行带前缀，3d §3.1/TC-23）+ 职业/等级/生命/魔法/货币。
- ``paginate``：列表类回复分页工具（3d D-02：每页最多 5 条，超 5 条分页；
  页脚格式 TPL-08 由壳层/业务渲染侧按需拼装——本函数只做切片与页数计算）。

平台无关铁律（3a §5 D-04 / R5）：全部输出为纯 str，不含 "[CQ:"、不含 at/图片/表情段占位符（S1/S2/S3）；
渲染层不截断不吞内容、不拼 CQ 转义（S5 归壳层 sender）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from qbot_rpg.core.message_format.prefix_render import render_prefix
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.player import Player, PlayerAttributes

__all__ = [
    "render_panel",
    "render_stats_line",
    "paginate",
]

# 列表分页每页上限（细化_3d §2.1 D-02：5 条/页）
DEFAULT_PAGE_SIZE: int = 5

# 九预置属性显示顺序（细化_3b §4.2 / L14-24）
_STAT_ORDER: List[str] = ["hp", "mp", "str", "int", "con", "spr", "foc", "agi", "lck"]
_STAT_LABELS: Dict[str, str] = {
    "hp": "生命", "mp": "魔法", "str": "力量", "int": "智力",
    "con": "体质", "spr": "精神", "foc": "专注", "agi": "敏捷", "lck": "幸运",
}


def _worn_title(player: Player) -> Optional[str]:
    """当前佩戴称号（细化_3d §1.3 [称号]；成就批登记状态）。缺失/空 → 无称号（3d §1.4 末条）。"""
    ts: Dict[str, str] = player.title_state or {}
    for key in ("current", "title", "worn", "佩戴"):
        val = ts.get(key)
        if val:
            return str(val)
    for val in ts.values():
        if val:
            return str(val)
    return None


def render_stats_line(attributes: PlayerAttributes) -> str:
    """九预置属性一条简况（细化_3b §4.2）。纯文本，无 emoji（3d D-01）。

    P1-1（M0 复查）：消费 calc_all_final_attributes 合并加成/临时/条件层，
    面板显示值 = 战斗最终属性（fixture base+bonus 下 str 显示 20 而非 15）。
    """
    final = calc_all_final_attributes(attributes)
    parts: List[str] = []
    for attr_id in _STAT_ORDER:
        label = _STAT_LABELS.get(attr_id, attr_id)
        value = final.get(attr_id, 0)
        parts.append(f"{label} {int(value)}")
    return "  ".join(parts)


def render_panel(player: Player, *, include_prefix: bool = True) -> str:
    """玩家基础状态面板（细化_3a §5 / 细化_3d §3.1：前缀首行 + 正文多行）。

    :param player: data/player.Player 运行实例
    :param include_prefix: 是否渲染前缀首行（enabled 开关由调用方控制，3a §5.2 S6）
    :return: 纯 str 面板（S1/S2/S3）
    """
    lines: List[str] = []
    if include_prefix:
        lines.append(render_prefix(player.level, player.name, _worn_title(player)))

    lines.append(f"职业：{player.job_id}    等级：{player.level}    EXP：{player.exp}")

    # P1-1（M0 复查）：生命/魔法上限改用最终属性（含 pct 加成，如 fixture hp 110 而非 100）
    final = calc_all_final_attributes(player.attributes)
    max_hp = int(final.get("hp", 0) or player.hp)
    max_mp = int(final.get("mp", 0) or player.mp)
    lines.append(f"生命：{player.hp}/{max_hp}    魔法：{player.mp}/{max_mp}")

    gold = 0
    if player.currencies:
        gold = int(player.currencies.get("gold", 0))
    lines.append(f"金币：{gold}")

    # 属性简况行（完整三层管线，见 core.player_attributes）
    lines.append(render_stats_line(player.attributes))
    return "\n".join(lines)


def paginate(
    items: List[Any],
    page: int,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> Tuple[List[Any], int, int]:
    """列表分页切片（细化_3d §2：每页最多 5 条；单页不输出页脚由渲染侧判断）。

    :param items: 待分页条目（用户可见条目数语义，3d §2.1 条数）
    :param page: 页码，取值 1..总页数（3d §2.2：非法值经壳层转 TPL-12，本函数抛 IndexError）
    :param per_page: 每页条数上限，默认 5
    :return: (当前页条目, 总页数, 总条数)。0 条时总页数=1（单页空列表）。
    """
    if per_page <= 0:
        raise ValueError(f"per_page 必须 > 0，got {per_page}")
    total = len(items)
    total_pages = max(1, math.ceil(total / per_page)) if total else 1
    if page < 1 or page > total_pages:
        raise IndexError(
            f"页码 {page} 越界（1..{total_pages}，共 {total} 条）——壳层应转 TPL-12 统一报错（3d §2.2）"
        )
    start = (page - 1) * per_page
    return list(items[start:start + per_page]), total_pages, total
