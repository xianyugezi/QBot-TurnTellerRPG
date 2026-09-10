"""CTB 方位 HUD 回归测试（2026-09-10）。

背景：CTB 重写后，主渲染路径改为 `send_round(_without_npc_outcomes(enriched))`，
而新拆出的 `_without_npc_outcomes` / `_without_player_outcomes` 副本未透传
`player_pos` / `enemy_pos` → 实机 HUD 方位后缀（「你 358/400右侧」）整体丢失。
本测试锁死该透传契约：两个副本构建器必须保留方位字段。
"""
from __future__ import annotations

from qbot_rpg.commands.battle_commands import (
    EnrichedTurnReport,
    _without_npc_outcomes,
    _without_player_outcomes,
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
    )


def test_without_npc_outcomes_keeps_pos() -> None:
    ns = _without_npc_outcomes(_report())
    assert ns.player_pos == ("right", "ground")
    assert ns.enemy_pos == ("front", "ground")


def test_without_player_outcomes_keeps_pos() -> None:
    ns = _without_player_outcomes(_report())
    assert ns.player_pos == ("right", "ground")
    assert ns.enemy_pos == ("front", "ground")


def test_pos_reaches_action_hint() -> None:
    """副本 → BREP-09 提示行渲染链须携带方位（端到端锁）。"""
    from qbot_rpg.core.message_format.battle_render import (
        _render_action_hint_from_report,
    )

    ns = _without_npc_outcomes(_report())
    hint = _render_action_hint_from_report(ns, ctx={})
    assert "右侧" in hint
