"""装备数值键空间注册表（批⑧ 装备接线收口 · 2026-09-12）。

唯一源（single source of truth）：凡「物品 def 数值字段 → 实例 stats_bonus →
聚合 / 战斗桥 / 展示 / 编辑器字段表」各处的键清单，一律从这里派生。
新增词条 = 本文件加一行（转换/聚合/桥按分层规则自动生效；展示与编辑器自动跟进）。

分层（data 层纯数据模块：零 import、零 IO——content/core/commands 全层可依赖；
字段表 content/field_meta 也要 import 本表，G0 依赖矩阵 content→{data}，
故注册表落 data 层而非 core 层）。

- FLAT   白值加算键：聚合进 attributes.bonus["flat"]（语义=数值加算）。
- PCT    百分比键：def 侧以 "xxx_pct" 命名（单位=百分点，5=+5%）；聚合端拆后缀
         进 attributes.bonus["pct"]["xxx"]；落档/实例层保留 "_pct" 全键。
- COMBAT 战斗直读键：不进属性管线；由 core/pvp._combatant_of 桥进战斗 combatant。

接线现状（批⑧）：
- 实例化：assembly/context.add_item、commands/shop_tx._new_default_instance → extract_bonus()。
- 聚合：core/equipment.aggregate_bonus → route_bonus_into()（flat/pct 拆层）。
- 战斗桥：core/pvp._combatant_of → combatant_updates()（crit 百分点可负、耳栓封顶 2、
  超会心/属性会心封顶 3）。
- 展示：commands/basic_commands._item_stat_parts；编辑器：content/field_meta 派生。

历史：原三处手写键表（context 13 键 / shop_tx 12 键 / 详情面板 12 键）互相漂移，
crit 与全部 _pct 键漏转 → 装备词条悬空（2026-09-12 批⑧ 勘察实证并收口）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Tuple

__all__ = [
    "GEAR_FLAT_KEYS",
    "GEAR_PCT_KEYS",
    "GEAR_COMBAT_KEYS",
    "GEAR_NUMERIC_KEYS",
    "GEAR_LABELS_ZH",
    "PCT_SUFFIX",
    "COMBAT_TO_COMBATANT",
    "extract_bonus",
    "route_bonus_into",
    "combatant_updates",
]

PCT_SUFFIX: str = "_pct"

# 白值加算键（聚合进 attributes.bonus["flat"]；def 旧键保留双兼容）
GEAR_FLAT_KEYS: Tuple[str, ...] = (
    "atk", "def", "dfn", "hp", "mp", "str", "con", "agi", "foc", "spr", "lck", "spd", "mag",
)
# 百分比键（单位=百分点；聚合端拆 "_pct" 后缀）
GEAR_PCT_KEYS: Tuple[str, ...] = ("atk_pct", "dfn_pct", "hp_pct", "mp_pct")
# 战斗直读键（pvp 桥 → combatant）：会心(可负) / 耳栓 / 超会心 / 属性会心
GEAR_COMBAT_KEYS: Tuple[str, ...] = ("crit", "earplug", "super_crit_lv", "elem_crit_lv")
# 数值键全集（实例化转换 / 展示 / 编辑器遍历用）
GEAR_NUMERIC_KEYS: Tuple[str, ...] = GEAR_FLAT_KEYS + GEAR_PCT_KEYS + GEAR_COMBAT_KEYS

# 战斗桥映射：(聚合 flat 键, combatant 键, 封顶) —— None=不封顶（crit 可负）
COMBAT_TO_COMBATANT: Tuple[Tuple[str, str, Any], ...] = (
    ("crit", "crit_bonus", None),
    ("earplug", "earplug", 2),
    ("super_crit_lv", "super_crit_lv", 3),
    ("elem_crit_lv", "elem_crit_lv", 3),
)

# 中文 label（展示 / 编辑器共用）
GEAR_LABELS_ZH: Dict[str, str] = {
    "atk": "攻击", "def": "防御", "dfn": "防御", "hp": "生命", "mp": "魔力",
    "str": "力量", "con": "体魄", "agi": "敏捷", "foc": "专注", "spr": "精神",
    "lck": "幸运", "spd": "速度", "mag": "魔法",
    "atk_pct": "攻击%", "dfn_pct": "防御%", "hp_pct": "生命%", "mp_pct": "魔力%",
    "crit": "会心", "earplug": "耳栓", "super_crit_lv": "超会心", "elem_crit_lv": "属性会心",
}


def extract_bonus(item_cfg: Mapping[str, Any]) -> Dict[str, float]:
    """def 数值字段 → stats_bonus（FLAT+PCT+COMBAT 全取；0/布尔/非数值排除）。"""
    out: Dict[str, float] = {}
    for k in GEAR_NUMERIC_KEYS:
        v = item_cfg.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
            out[k] = float(v)
    return out


def route_bonus_into(
    bonus: Mapping[str, Any],
    flat: MutableMapping[str, float],
    pct: MutableMapping[str, float],
) -> None:
    """stats_bonus 键表按层路由："..._pct" → pct[stem]（百分点）；其余 → flat。"""
    for k, v in bonus.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        ks = str(k)
        if ks.endswith(PCT_SUFFIX) and len(ks) > len(PCT_SUFFIX):
            stem = ks[: -len(PCT_SUFFIX)]
            pct[stem] = pct.get(stem, 0.0) + fv
        else:
            flat[ks] = flat.get(ks, 0.0) + fv


def combatant_updates(flat: Mapping[str, Any]) -> Dict[str, float]:
    """聚合 flat → combatant 战斗桥更新项（非零项；封顶按 COMBAT_TO_COMBATANT）。

    crit 保留浮点（百分点、可负=赌狗流）；耳栓/超会心/属性会心按整数档位封顶。
    """
    out: Dict[str, float] = {}
    for src, dst, cap in COMBAT_TO_COMBATANT:
        v = flat.get(src)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if fv == 0.0:
            continue
        if cap is not None:
            fv = float(max(0.0, min(float(cap), fv)))
        out[dst] = fv
    return out
