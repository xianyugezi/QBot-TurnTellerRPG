"""CTB 方位 HUD 回归测试（2026-09-10）。

背景：CTB 重写后，主渲染路径改为 `send_round(_without_npc_outcomes(enriched))`，
而新拆出的 `_without_npc_outcomes` / `_without_player_outcomes` 副本未透传
`player_pos` / `enemy_pos` → 实机 HUD 方位后缀（「你 358/400右侧」）整体丢失。
本测试锁死该透传契约：两个副本构建器必须保留方位字段。
"""
from __future__ import annotations

import pytest

from qbot_rpg.commands.battle_commands import (
    EnrichedTurnReport,
    _without_npc_outcomes,
    _without_player_outcomes,
)

# T3（复核修复 2026-09-12）：HUD v2 九字段（投影须逐个透传，防 #26「新增字段漏改投影」）。
_HUD_FIELDS = (
    "player_mp", "player_mp_max", "player_shield", "player_shield_turns",
    "enemy_shield", "enemy_shield_turns", "enemy_air", "enemy_broken_parts",
    "effect_events",
)


def _report() -> EnrichedTurnReport:
    return EnrichedTurnReport(
        turn=3,
        player=358,
        enemy=230,
        player_pos=("right", "ground"),
        enemy_pos=("front", "ground"),
        player_max_hp=400,
        enemy_max_hp=263,
        player_mp=12,
        player_mp_max=80,
        player_shield=30,
        player_shield_turns=2,
        enemy_shield=5,
        enemy_shield_turns=1,
        enemy_air=True,
        enemy_broken_parts=("左翼", "尾部"),
        effect_events=({"type": "dot_damage", "side": "player", "status": "bleed"},),
    )


def test_without_npc_outcomes_keeps_pos() -> None:
    ns = _without_npc_outcomes(_report())
    assert ns.player_pos == ("right", "ground")
    assert ns.enemy_pos == ("front", "ground")


def test_without_player_outcomes_keeps_pos() -> None:
    ns = _without_player_outcomes(_report())
    assert ns.player_pos == ("right", "ground")
    assert ns.enemy_pos == ("front", "ground")


@pytest.mark.parametrize("builder", [_without_npc_outcomes, _without_player_outcomes])
def test_projections_pass_through_all_hud_fields(builder) -> None:
    """T3：两个投影须逐个透传 HUD 九字段（值相等，非仅存在）。"""
    src = _report()
    ns = builder(src)
    for field in _HUD_FIELDS:
        assert getattr(ns, field) == getattr(src, field), f"{builder.__name__} 漏透传 {field}"


def test_pos_reaches_action_hint() -> None:
    """副本 → BREP-09 提示行渲染链须携带方位（端到端锁）。"""
    from qbot_rpg.core.message_format.battle_render import (
        _render_action_hint_from_report,
    )

    ns = _without_npc_outcomes(_report())
    hint = _render_action_hint_from_report(ns, ctx={})
    assert "右侧" in hint
