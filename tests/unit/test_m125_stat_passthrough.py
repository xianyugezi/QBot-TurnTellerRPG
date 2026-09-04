"""M12.5 需求1 批A 验证：combatant 全量透传（玩家 attrs 三层合成全键 + 敌方 stats 全键）。

依据：docs/m125_战斗数值动态化方案.md 批 A A1/A2/A3。
验收：玩家/敌方 combatant 含自定义 stat 键；既有键映射保持（零破坏）。
"""
from __future__ import annotations

from typing import Any, Mapping

from qbot_rpg.commands.battle_launch_commands import _enemy_combatant
from qbot_rpg.core.pvp import _combatant_of


def _dict_like() -> Any:
    """鸭子兼容 dict：既有测试用 dict / 生产是 frozen dataclass。"""

    class _P(dict):
        pass

    return _P


def test_player_combatant_passthrough_custom_stat_keys() -> None:
    """玩家 attrs.base 含自定义键（str 已映射 / custom_x 新键）→ combatant 全键输出。"""
    attrs = {
        "base": {"str": 15.0, "con": 12.0, "custom_x": 7.0, "hp": 100.0, "mp": 30.0},
        "bonus": {"flat": {"custom_x": 3.0}, "pct": {}},
        "temp": {"pct": {"atk": 10.0}},
    }
    player: Mapping[str, Any] = {
        "name": "测试者", "qid": "10001", "level": 5,
        "hp": 90, "max_hp": 100, "mp": 30, "max_mp": 30,
        "attributes": attrs,
    }
    comb = _combatant_of(player)
    # 既有语义键仍在（零破坏）
    assert comb["atk"] >= 1 and comb["dfn"] >= 1 and comb["con"] == 12
    assert comb["hp"] == 90 and comb["max_hp"] == 100
    # 自定义键透传：base 7 + flat 3 = 10（数值口径沿用 _attr 现语义：pct 为小数乘子）
    assert comb["custom_x"] == 10
    # hp/mp 是资源不重复追加（保持档案血量口径）
    assert comb["hp"] == 90 and comb["mp"] == 30


def test_player_combatant_passthrough_no_base_attrs() -> None:
    """attrs 缺失/空 → 只输出既有键（不崩、无多余键）。"""
    comb = _combatant_of({"name": "无属性者", "qid": "10002", "level": 1})
    assert comb["atk"] >= 1 and comb["hp"] >= 1
    # 无自定义键时键集 = 既有固定键
    fixed = {"id", "name", "level", "hp", "max_hp", "mp", "max_mp",
             "atk", "dfn", "mag", "spd", "foc", "con", "int", "lck"}
    assert set(comb) == fixed


def test_enemy_combatant_passthrough_custom_stat_keys() -> None:
    """敌方 stats 含自定义键 → combatant 全键输出（含原始映射键语义保持）。"""
    enemy = {
        "id": "wolf", "name": "荒原狼",
        "stats": {
            "hp": 80, "str": 14, "con": 10, "agi": 12, "spr": 6, "luk": 8,
            "custom_y": 5.0, "focus_cost": 2,
        },
    }
    comb = _enemy_combatant(enemy)
    # 既有映射语义（str→atk 等）
    assert comb["atk"] == 14 and comb["dfn"] == 10 and comb["spd"] == 12
    assert comb["mag"] == 6 and comb["lck"] == 8
    # 自定义键透传
    assert comb["custom_y"] == 5.0
    assert comb["focus_cost"] == 2
    assert comb["hp"] == 80


def test_enemy_combatant_no_custom_no_crash() -> None:
    """无自定义键 / stats 缺失 → 既有行为不变。"""
    comb = _enemy_combatant({"id": "slime", "name": "史莱姆",
                             "stats": {"hp": 50, "str": 8}})
    assert comb["atk"] == 8 and comb["hp"] == 50
    comb2 = _enemy_combatant({"id": "x", "name": "x"})
    assert comb2["atk"] == 10  # 缺省 str→atk=10
