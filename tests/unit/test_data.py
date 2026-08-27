"""data 层单测（细化_3a§3 D-03/U1-U3：frozen、唯一落点、ID+名称冗余、round-trip）。"""
from __future__ import annotations

import dataclasses

import pytest

from qbot_rpg.data import (
    BattleSnapshot, Player, PlayerAttributes, StatusInstance,
    WorldState, ItemInstance, EquipmentSlot,
)
from qbot_rpg.storage.repository import Repository
from qbot_rpg.storage.connection import Database
from conftest import make_player  # type: ignore[import-not-found]


# U1/U3：核心数据类型 frozen
@pytest.mark.parametrize("cls", [Player, PlayerAttributes, BattleSnapshot,
                                 StatusInstance, ItemInstance, WorldState, EquipmentSlot])
def test_core_types_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen is True


def test_battle_snapshot_has_random_seed():
    from qbot_rpg.data.battle import CombatantSnapshot
    snap = BattleSnapshot(
        session_type="battle",
        player=CombatantSnapshot(max_hp=100, hp=80, atk=10, dfn=5, mag=2, spd=4, name="阿伟"),
        enemy=CombatantSnapshot(max_hp=60, hp=60, atk=8, dfn=3, mag=1, spd=2, name="史莱姆"),
        turn=1, combo_state={}, ai_state={}, status_state={}, marks_state={},
        resist_table={}, effect_triggers={}, effect_cooldowns={},
        formula_state={"random_seed": 42},
    )
    assert snap.formula_state["random_seed"] == 42
    assert snap.session_type == "battle"


# 4a TC-12 编解码 round-trip（不碰 DB）
def test_codec_roundtrip(player):
    r = Repository.__new__(Repository)  # 仅用编解码纯函数，不落库
    ok, msg = r.codec_roundtrip(player)
    assert ok, msg


# SCHEMA-5 ID+名称冗余：inventory 存 item_id+name
def test_id_name_redundancy(player):
    it = player.inventory[0]
    assert it.item_id and it.name
