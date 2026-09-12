"""战斗 HUD v2 专项测试（2026-09-12 用户样稿重构）。

用户口径（原话）：
  「消息模板改成这样，如果没有护盾/法力等资源则不显示这些资源，持续效果也一样。
    另外，怪物的朝向就是正面，只有玩家位于怪物的哪个方位，没有怪物哪个方位。」

覆盖（任务书 §4.4 六类）：
  ① 无法力/护盾 → 对应行整行不出现（不留空行）
  ② 有法力/护盾 → 行出现且格式为「剩余法力：{mp}/{max}（{pct}%）」「剩余护盾：{n}（{t}s）」
  ③ 百分比格式化：92.5 / 34.2 / 1 / 100（一位小数、整数省略小数）
  ④ 怪物侧不含朝向（无【正面】/【背后】等；不再渲染敌方位格）
  ⑤ 玩家站位行 = 玩家相对怪物方位（含上空组合，如「正面上空」）
  ⑥ 持续效果行：DOT 生效（玩家/怪物视角）与效果失效；无事件 → 无行

依据：docs/消息模板重构/00_方案与规范_v1.md + 用户 2026-09-12 样稿。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

from qbot_rpg.core.message_format.battle_render import (
    _fmt_pct,
    _render_effect_lines,
    _render_action_hint_from_report,
    _wrap_state_segments,
    render_action_hint,
)


def _fmt_pct_expect(cur: int, mx: int, want: str) -> None:
    assert _fmt_pct(cur, mx) == want


# ---------------------------------------------------------------------------
# ③ 百分比格式化
# ---------------------------------------------------------------------------

def test_fmt_pct_formats() -> None:
    """③ 一位小数；整数省略小数（用户样稿 92.5% / 34.2% / 1% / 100%）。"""
    _fmt_pct_expect(484, 523, "92.5")
    _fmt_pct_expect(90, 263, "34.2")
    _fmt_pct_expect(1, 100, "1")
    _fmt_pct_expect(523, 523, "100")
    _fmt_pct_expect(0, 0, "0")          # 分母缺失不崩
    _fmt_pct_expect(5, 0, "0")


# ---------------------------------------------------------------------------
# ①/② 按需显示：无法力/护盾不出行；有则成形
# ---------------------------------------------------------------------------

def test_hud_hides_absent_resources() -> None:
    """① 无法力、无护盾 → 「剩余法力」「剩余护盾」「怪物护盾」整行不出现。"""
    text = render_action_hint(21, 30, 7, 25, target_name="史莱姆")
    lines = text.split("\n")
    assert "剩余生命：21/30（70%）" in lines
    assert "怪物生命：7/25（28%）" in lines
    assert not any("剩余法力" in ln for ln in lines)
    assert not any("剩余护盾" in ln for ln in lines)
    assert not any("怪物护盾" in ln for ln in lines)
    assert not any("怪物状态" in ln for ln in lines)
    assert lines[-1] == "→ 攻击 或 攻击 <技能名>"
    assert all(ln.strip() for ln in lines)          # 不留空行


def test_hud_shows_present_resources() -> None:
    """② 有法力/护盾 → 行出现且格式正确（护盾带剩余行动数）。"""
    text = render_action_hint(
        484, 523, 90, 263, target_name="脊冢幼兽",
        player_mp=1, player_mp_max=100,
        player_shield=100, player_shield_turns=3,
        target_shield=20, target_shield_turns=1,
    )
    lines = text.split("\n")
    assert "剩余生命：484/523（92.5%）" in lines
    assert "剩余法力：1/100（1%）" in lines
    assert "剩余护盾：100（3s）" in lines
    assert "怪物生命：90/263（34.2%）" in lines
    assert "怪物护盾：20（1s）" in lines


def test_hud_shield_without_turns_omits_suffix() -> None:
    """② 护盾无剩余行动数（0）→ 只出数值，不出空括号。"""
    lines = render_action_hint(10, 20, 5, 10, player_shield=30, player_shield_turns=0).split("\n")
    assert "剩余护盾：30" in lines


# ---------------------------------------------------------------------------
# ④ 怪物无朝向
# ---------------------------------------------------------------------------

def test_hud_no_enemy_facing() -> None:
    """④ 怪物侧不渲染朝向（不出现【正面】等方位格）。"""
    lines = render_action_hint(
        21, 30, 7, 25, target_name="史莱姆",
        player_pos="正面", enemy_pos="【背后】",
    ).split("\n")
    assert not any("【" in ln for ln in lines)
    assert not any("背后" in ln for ln in lines)


def test_hud_from_report_drops_enemy_pos() -> None:
    """④ 接线层传入 enemy_pos 也不再渲染（用户拍板：怪只有正面，不存在「怪在哪个方位」）。"""
    src = SimpleNamespace(
        player=21, enemy=7, player_max_hp=30, enemy_max_hp=25, enemy_name="史莱姆",
        player_pos=("front", "ground"), enemy_pos=("back", "ground"),
    )
    text = _render_action_hint_from_report(src)
    assert "玩家站位：正面" in text
    assert "背后" not in text and "【" not in text


# ---------------------------------------------------------------------------
# ⑤ 玩家站位（含上空）
# ---------------------------------------------------------------------------

def test_hud_player_position_with_air() -> None:
    """⑤ 玩家站位 = 玩家相对怪物方位；空中组合「正面上空」。"""
    src = SimpleNamespace(
        player=21, enemy=7, player_max_hp=30, enemy_max_hp=25, enemy_name="史莱姆",
        player_pos=("front", "air"), enemy_pos=None,
    )
    text = _render_action_hint_from_report(src)
    assert "玩家站位：正面上空" in text


def test_hud_player_position_absent_when_unknown() -> None:
    """⑤ 方位未知（None）→ 不出「玩家站位」行。"""
    src = SimpleNamespace(
        player=21, enemy=7, player_max_hp=30, enemy_max_hp=25, enemy_name="史莱姆",
        player_pos=None, enemy_pos=None,
    )
    assert "玩家站位" not in _render_action_hint_from_report(src)


# ---------------------------------------------------------------------------
# ⑦ 怪物状态（跃空/部位破坏）
# ---------------------------------------------------------------------------

def test_hud_enemy_states_air_and_parts() -> None:
    """怪物状态：跃空 + 已破坏部位（用户样稿「跃空丨左翼破坏丨尾部破坏」）。"""
    src = SimpleNamespace(
        player=484, enemy=90, player_max_hp=523, enemy_max_hp=263, enemy_name="脊冢幼兽",
        enemy_air=True, enemy_broken_parts=("左翼", "尾部"),
    )
    lines = _render_action_hint_from_report(src).split("\n")
    # 用户样稿三态整行 = 34 半角（17 全角）> 14 全角上限 → 按定稿「结构化行 ≤14 全角」折行，
    # 首行带「怪物状态：」前缀、续行只出状态串（信息不丢）
    assert "怪物状态：跃空丨左翼破坏" in lines
    assert "尾部破坏" in lines


def test_hud_enemy_states_hidden_when_empty() -> None:
    """无状态 → 不出「怪物状态」行。"""
    src = SimpleNamespace(
        player=10, enemy=5, player_max_hp=20, enemy_max_hp=10, enemy_name="史莱姆",
        enemy_air=False, enemy_broken_parts=(),
    )
    assert "怪物状态" not in _render_action_hint_from_report(src)


def test_wrap_state_segments_stays_within_budget() -> None:
    """状态超宽自动折行：每段（含「怪物状态：」前缀）≤ 14 全角当量。"""
    segs = _wrap_state_segments(["跃空", "左翼破坏", "尾部破坏", "右翼破坏", "头壳破坏"])
    assert len(segs) > 1
    assert segs[0].startswith("跃空")
    from qbot_rpg.core.message_format.battle_render import _display_width_half

    assert _display_width_half(segs[0]) + 10 <= 28          # 首行含前缀
    for seg in segs[1:]:
        assert _display_width_half(seg) <= 28


# ---------------------------------------------------------------------------
# ⑥ 持续效果行
# ---------------------------------------------------------------------------

def test_effect_lines_dot_and_expire() -> None:
    """⑥ DOT 生效（玩家视角「你受到」/怪物视角「造成」）+ 效果失效。"""
    src = SimpleNamespace(effect_events=(
        {"type": "dot_damage", "side": "enemy", "status": "burn", "name": "燃烧", "value": 100},
        {"type": "status_expired", "side": "enemy", "status": "rage", "name": "狂暴"},
        {"type": "dot_damage", "side": "player", "status": "bleed", "name": "流血", "value": 1},
    ))
    assert _render_effect_lines(src) == [
        "【持续效果】燃烧 生效，造成 100 伤害。",
        "【效果失效】狂暴 效果时间结束。",
        "【持续效果】流血 生效，你受到 1 伤害。",
    ]


def test_effect_lines_absent_when_no_events() -> None:
    """⑥ 无事件（含缺字段的对象）→ 无行、不崩。"""
    assert _render_effect_lines(SimpleNamespace()) == []
    assert _render_effect_lines(SimpleNamespace(effect_events=())) == []
    assert _render_effect_lines(
        SimpleNamespace(effect_events=({"type": "regen", "side": "player"},))
    ) == []


def test_effect_lines_unknown_status_falls_back_to_id() -> None:
    """⑥ 状态无展示名 → 回落状态 id（不臆造）。"""
    src = SimpleNamespace(effect_events=(
        {"type": "dot_damage", "side": "player", "status": "dot_1", "value": 3},
    ))
    assert _render_effect_lines(src) == ["【持续效果】dot_1 生效，你受到 3 伤害。"]


# ---------------------------------------------------------------------------
# 接线层取数（battle_hud_payload）
# ---------------------------------------------------------------------------

def test_battle_hud_payload_reads_snapshot() -> None:
    """接线层取数：法力/护盾/跃空/部位破坏 → 原始数据（中文由模板产出）。"""
    from qbot_rpg.commands.battle_commands import battle_hud_payload

    snap: Dict[str, Any] = {
        "player": {"hp": 10, "max_hp": 20, "mp": 3, "max_mp": 50,
                   "defenses": {"shield": {"value": 30, "remaining": 30, "turns": 2}}},
        "enemy": {"hp": 5, "max_hp": 30, "parts": [{"id": "p1", "name": "左翼"}]},
        "parts_state": {"p1": {"broken": True}},
        "combat_position": {"enemy": {"side": "front", "height": "air"}},
    }
    hud = battle_hud_payload(snap)
    assert hud["player_mp"] == 3 and hud["player_mp_max"] == 50
    assert hud["player_shield"] == 30 and hud["player_shield_turns"] == 2
    assert hud["enemy_shield"] == 0 and hud["enemy_shield_turns"] == 0
    assert hud["enemy_air"] is True
    assert hud["enemy_broken_parts"] == ("左翼",)


def test_battle_hud_payload_tolerates_garbage() -> None:
    """接线层取数兜底：空/异常快照 → 全缺省（不崩、不臆造）。"""
    from qbot_rpg.commands.battle_commands import battle_hud_payload

    for bad in ({}, None, {"player": 1, "enemy": "x"}):        # type: ignore[arg-type]
        hud = battle_hud_payload(bad)                          # type: ignore[arg-type]
        assert hud["player_mp"] is None and hud["player_shield"] == 0
        assert hud["enemy_air"] is False and hud["enemy_broken_parts"] == ()


def test_effect_events_flow_from_report() -> None:
    """TurnReport.effect_events → EnrichedTurnReport.effect_events（接线层透传）。"""
    from qbot_rpg.commands.battle_commands import enrich_round_report

    evs = ({"type": "dot_damage", "side": "player", "status": "bleed", "name": "流血", "value": 1},)
    report = SimpleNamespace(
        turn=1, action_seq=1, battle_time=100.0, player=10, enemy=5, ended=False,
        status=None, log=(), outcomes=(), effect_events=evs,
    )
    enriched = enrich_round_report(report, enemy_name="史莱姆", player_max_hp=20, enemy_max_hp=30)
    assert enriched.effect_events == evs
    lines: List[str] = _render_effect_lines(enriched)
    assert lines == ["【持续效果】流血 生效，你受到 1 伤害。"]
