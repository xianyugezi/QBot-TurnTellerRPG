"""formula.json 段级参数 → DamageFormulaParams 生产侧装配（M12.5 需求1 批C）。

文件：qbot_rpg/core/formula_loader.py · 2026-09-04 · Hermes Agent
功能描述：
  - load_formula_params(data)：接受 formula.json 顶层 dict（registry.modules_raw
    ["formula"] 原样）→ DamageFormulaParams（含 stat_map 段），段缺省回退默认。
  - load_formula_params_from_path(path)：文件路径形态（兼容 conftest 既有读取器）。
  - 原测试侧读取器（tests/conftest.load_formula_params）改为薄包装走本模块，
    生产/测试同一装配源（对齐 battle.py L332-336 注释「共享加载函数未落生产侧」）。

依据：
  - docs/m125_战斗数值动态化方案.md 批 C（formula.json 生产侧装配链 T01 补落）
  - 细化_M6 测试体系强化 D6 §三 FIX-2 / F-FIX-01~27（段字段映射表）
  - 细化_1a §2.1（DamageFormulaParams 字段表默认值）

铁律：零 NoneBot import；异常兜底不崩；段缺省回退不抛错。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Tuple, cast

from qbot_rpg.core.damage import (
    BattlePositionParams,
    BlockParams,
    CritMultUp,
    CritParams,
    CritTiers,
    DamageFormulaParams,
    DefenseParams,
    DerivedParams,
    HitParams,
    StatMap,
    TypeAffinityParams,
    WeaknessParams,
)

__all__ = ["load_formula_params", "load_formula_params_from_path"]


def _stat_map_from(seg: Mapping[str, Any]) -> StatMap:
    """stat_map 段（dict）→ StatMap（缺省回落 = 现值键，零破坏）。"""
    base = StatMap()
    if not isinstance(seg, Mapping):
        return base

    def _key(name: str) -> str:
        v = seg.get(name)
        if isinstance(v, str) and v:
            return v
        return getattr(base, name)

    return StatMap(
        hit_focus=_key("hit_focus"),
        hit_spd=_key("hit_spd"),
        crit_luck=_key("crit_luck"),
        block_focus=_key("block_focus"),
        def_con=_key("def_con"),
        atk_atk=_key("atk_atk"),
        mag_int=_key("mag_int"),
        enemy_str=_key("enemy_str"),
        enemy_con=_key("enemy_con"),
        enemy_spr=_key("enemy_spr"),
        enemy_agi=_key("enemy_agi"),
        atk_base=_key("atk_base"),
        dfn_base=_key("dfn_base"),
    )


def load_formula_params(data: Mapping[str, Any]) -> DamageFormulaParams:
    """formula.json 顶层 dict → DamageFormulaParams（生产侧装配源，F-FIX-01~27 映射）。

    - data = registry.modules_raw["formula"]（map 形态模块原始 dict：既有公式键
      damage_base/heal_rate + 段级参数 damage/hit/crit/.../elements + stat_map）。
    - 段缺省回退：缺某段/键 → dataclass 默认值不抛错（D6 §3.4 边界异常）；
    - 数组形态（rng/tier_p）→ tuple；扁平对象（tiers/crit_mult_up/pierce_types/
      elements）→ 对应 frozen 子结构；
    - floor_mode/deep_floor 等纯配置字段不在 DamageFormulaParams 内，读取器不消费。
    """
    dmg, hit_seg, crit_seg, block_seg = (
        data.get(k) or {} for k in ("damage", "hit", "crit", "block")
    )
    bp_seg = data.get("battle_position") or {}
    defense_seg = data.get("defense") or {}
    weakness_seg = data.get("weakness") or {}
    ta_seg = data.get("type_affinity") or {}
    derived_seg = data.get("derived") or {}
    stat_map_seg = data.get("stat_map") or {}
    base = DamageFormulaParams()  # 段缺省回退默认源（dataclass 默认 = F-FIX 表默认）

    def _f(seg: Any, key: str, default: Any) -> Any:
        if not isinstance(seg, Mapping):
            return default
        v = seg.get(key)
        return default if v is None else v

    tiers = crit_seg.get("tiers") or {} if isinstance(crit_seg, Mapping) else {}
    mult_up = crit_seg.get("crit_mult_up") or {} if isinstance(crit_seg, Mapping) else {}
    return DamageFormulaParams(
        base_attack_mult=float(_f(dmg, "base_attack_mult", base.base_attack_mult)),  # F-FIX-01
        rng=cast(Tuple[float, float],  # F-FIX-02
                  tuple(float(x) for x in _f(dmg, "rng", base.rng))),
        hit=HitParams(
            k=float(_f(hit_seg, "k", base.hit.k)),  # F-FIX-03
            cap_min=float(_f(hit_seg, "cap_min", base.hit.cap_min)),  # F-FIX-04
            cap_max=float(_f(hit_seg, "cap_max", base.hit.cap_max)),  # F-FIX-05
        ),
        crit=CritParams(
            p_coef=float(_f(crit_seg, "p_coef", base.crit.p_coef)),  # F-FIX-06
            cap=float(_f(crit_seg, "cap", base.crit.cap)),  # F-FIX-07
            tiers=CritTiers(
                high=float(_f(tiers, "high", base.crit.tiers.high)),  # F-FIX-08
                mid=float(_f(tiers, "mid", base.crit.tiers.mid)),
                low=float(_f(tiers, "low", base.crit.tiers.low)),
            ),
            tier_p=cast(  # F-FIX-09
                Tuple[int, int],
                tuple(int(x) for x in _f(crit_seg, "tier_p", base.crit.tier_p))),
            crit_mult_up=CritMultUp(
                lv1=float(_f(mult_up, "lv1", base.crit.crit_mult_up.lv1)),  # F-FIX-10
                lv2=float(_f(mult_up, "lv2", base.crit.crit_mult_up.lv2)),
                lv3=float(_f(mult_up, "lv3", base.crit.crit_mult_up.lv3)),
            ),
            negative_crit=float(_f(crit_seg, "negative_crit", base.crit.negative_crit)),  # E19
            elem_crit_step=float(_f(crit_seg, "elem_crit_step", base.crit.elem_crit_step)),  # E21
        ),
        block=BlockParams(
            k=float(_f(block_seg, "k", base.block.k)),  # F-FIX-11
            cap=float(_f(block_seg, "cap", base.block.cap)),  # F-FIX-12
            magic_ignores=bool(  # F-FIX-13
                _f(block_seg, "magic_ignores", base.block.magic_ignores)),
            halve_after_block=bool(  # F-FIX-14
                _f(block_seg, "halve_after_block", base.block.halve_after_block)
            ),
        ),
        defense=DefenseParams(
            mode=str(_f(defense_seg, "mode", base.defense.mode)),  # F-FIX-15
            k=float(_f(defense_seg, "k", base.defense.k)),  # F-FIX-16
            pierce_types=dict(  # F-FIX-17
                _f(defense_seg, "pierce_types", base.defense.pierce_types)
            ),
        ),
        weakness=WeaknessParams(
            type_mult=float(_f(weakness_seg, "type_mult", base.weakness.type_mult)),  # F-FIX-18
            element_mult=float(  # F-FIX-19
                _f(weakness_seg, "element_mult", base.weakness.element_mult)
            ),
        ),
        type_affinity=TypeAffinityParams(
            enabled=bool(_f(ta_seg, "enabled", base.type_affinity.enabled)),  # F-FIX-20
            blunt_pierce=float(  # F-FIX-21
                _f(ta_seg, "blunt_pierce", base.type_affinity.blunt_pierce)),
            thrust_hit=float(_f(ta_seg, "thrust_hit", base.type_affinity.thrust_hit)),  # F-FIX-22
            slash_crit=float(_f(ta_seg, "slash_crit", base.type_affinity.slash_crit)),  # F-FIX-23
            magic_ignore_block=bool(  # F-FIX-24
                _f(ta_seg, "magic_ignore_block", base.type_affinity.magic_ignore_block)
            ),
        ),
        derived=DerivedParams(  # F-FIX-25
            max_total_mult=float(_f(derived_seg, "max_total_mult", base.derived.max_total_mult))
        ),
        stat_map=_stat_map_from(stat_map_seg),  # M12.5 需求1 批C：stat_map 段装配
        monster_def_rate=float(_f(data, "monster_def_rate", base.monster_def_rate)),  # F-FIX-26
        elements=dict(_f(data, "elements", base.elements)),  # F-FIX-27
        # 方位 v0.6（附录 A Step 2）：battle_position 段（破坏力公式参数，缺省=零破坏基线）
        battle_position=BattlePositionParams(
            break_base_damage=float(_f(bp_seg, "break_base_damage",
                                       base.battle_position.break_base_damage)),
            break_sqrt_coef=float(_f(bp_seg, "break_sqrt_coef",
                                     base.battle_position.break_sqrt_coef)),
            broken_part_mult=float(_f(bp_seg, "broken_part_mult",
                                      base.battle_position.broken_part_mult)),
        ),
    )


def load_formula_params_from_path(path: Path) -> DamageFormulaParams:
    """formula.json 文件路径 → DamageFormulaParams（兼容 conftest 既有读取器）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # 读取/解析失败 → 全默认（战斗不因 formula.json 坏而崩，兜底精神）
        return DamageFormulaParams()
    if not isinstance(data, Mapping):
        return DamageFormulaParams()
    return load_formula_params(data)
