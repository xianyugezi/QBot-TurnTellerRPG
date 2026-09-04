"""M12.5 需求1 批C 验证：formula.json 生产侧装配链。

依据：docs/m125_战斗数值动态化方案.md 批 C。
验收：
  1. registry.modules_raw["formula"] 带 stat_map/段参数 → BattleEngine 自动装配实读；
  2. 无 formula 模块 / 无 registry → 全默认（零破坏）；
  3. conftest.load_formula_params 薄包装 → 生产 formula_loader 同源（既有测试零破坏）。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.content.formula_loader import (
    load_formula_params,
    load_formula_params_from_path,
)
from qbot_rpg.content.registry import Registry
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.damage import DamageFormulaParams, StatMap

PLAYER: Dict[str, Any] = {
    "max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100,
    "atk": 100, "dfn": 50, "mag": 50, "spd": 50,
    "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50, "spr": 50, "lck": 50,
    "custom_focus": 200, "custom_luck": 200, "custom_con": 200, "custom_spd": 200,
    "custom_atk": 200, "elem_atk": 0, "name": "P",
}
ENEMY: Dict[str, Any] = {
    "max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0,
    "atk": 80, "dfn": 40, "mag": 30, "spd": 40,
    "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40, "lck": 10,
    "custom_focus": 10, "custom_luck": 10, "custom_con": 10, "custom_spd": 10,
    "custom_atk": 10, "elem_atk": 0, "name": "E",
}


def _registry_with_formula(formula: Dict[str, Any]) -> Registry:
    return Registry.build(
        pack_id="test_formula", generation=1,
        tables={}, names={},
        modules_raw={"formula": formula},
        manifest=None,
    )


def test_battle_engine_assembles_formula_from_registry() -> None:
    """registry.modules_raw["formula"]（stat_map + hit.k 段）→ BattleEngine 自动装配。"""
    reg = _registry_with_formula({
        "damage_base": "atk * 2 - def",
        "hit": {"k": 2.0, "cap_min": 10, "cap_max": 95},
        "stat_map": {
            "hit_focus": "custom_focus", "hit_spd": "custom_spd",
            "crit_luck": "custom_luck", "def_con": "custom_con", "atk_atk": "custom_atk",
        },
    })
    eng = BattleEngine(registry=reg)
    p = eng._params
    # 段参数装配生效
    assert p.hit.k == 2.0
    # stat_map 装配生效
    assert p.stat_map.hit_focus == "custom_focus"
    assert p.stat_map.hit_spd == "custom_spd"
    assert p.stat_map.crit_luck == "custom_luck"
    assert p.stat_map.def_con == "custom_con"
    assert p.stat_map.atk_atk == "custom_atk"
    # 战斗实读新键（命中率：custom_focus=200 / (200 + custom_spd=10)）
    eng.start(dict(PLAYER), dict(ENEMY))
    focus = float(eng._combat("player").get(p.stat_map.hit_focus, 50))
    espd = float(eng._combat("enemy").get(p.stat_map.hit_spd, 50))
    assert abs(focus / (focus + espd) - 200.0 / 210.0) < 1e-9


def test_battle_engine_no_formula_module_defaults() -> None:
    """registry 无 formula 模块 → 全默认（零破坏）。"""
    reg = Registry.build(
        pack_id="test_no_formula", generation=1,
        tables={}, names={}, modules_raw={"effects": {}}, manifest=None,
    )
    eng = BattleEngine(registry=reg)
    assert eng._params == DamageFormulaParams()
    assert eng._params.stat_map == StatMap()


def test_battle_engine_no_registry_defaults() -> None:
    """无 registry → 全默认（既有测试路径零破坏）。"""
    eng = BattleEngine()
    assert eng._params == DamageFormulaParams()


def test_formula_loader_stat_map_partial_override() -> None:
    """stat_map 部分覆盖 → 未覆盖键回落默认。"""
    p = load_formula_params({"stat_map": {"hit_focus": "aim"}})
    assert p.stat_map.hit_focus == "aim"
    assert p.stat_map.hit_spd == "spd"  # 未覆盖回落现值
    assert p.stat_map.crit_luck == "lck"
    p2 = load_formula_params({})  # 空 dict → 全默认
    assert p2.stat_map == StatMap()


def test_formula_loader_from_path_matches_production(tmp_path) -> None:
    """路径读取器（conftest 兼容）与 dict 读取器同源同结果。"""
    import json

    fp = tmp_path / "formula.json"
    fp.write_text(json.dumps({
        "damage": {"base_attack_mult": 1.2},
        "stat_map": {"crit_luck": "fate"},
    }), encoding="utf-8")
    p_path = load_formula_params_from_path(fp)
    p_dict = load_formula_params({
        "damage": {"base_attack_mult": 1.2},
        "stat_map": {"crit_luck": "fate"},
    })
    assert p_path.base_attack_mult == p_dict.base_attack_mult == 1.2
    assert p_path.stat_map.crit_luck == p_dict.stat_map.crit_luck == "fate"


def test_conftest_wrapper_still_works(legal_pack_dir) -> None:
    """conftest.load_formula_params 薄包装 → 生产同源（fixture 兼容零破坏）。"""
    from tests.conftest import load_formula_params as conftest_loader

    p = conftest_loader(legal_pack_dir / "formula.json")
    assert isinstance(p, DamageFormulaParams)
    # legal 包有默认段参数 → 装配一致
    assert p.hit.k == 1.0 and p.block.cap == 40.0
