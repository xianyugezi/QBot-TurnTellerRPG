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
    _status_display_name,
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
    # 2026-09-12 用户拍板：状态行**整行全量显示、不折行**（超 14 全角无妨——状态全量
    # 不影响阅读；本行不受结构化行宽度约束）
    assert "怪物状态：跃空丨左翼破坏丨尾部破坏" in lines


def test_hud_enemy_states_hidden_when_empty() -> None:
    """无状态 → 不出「怪物状态」行。"""
    src = SimpleNamespace(
        player=10, enemy=5, player_max_hp=20, enemy_max_hp=10, enemy_name="史莱姆",
        enemy_air=False, enemy_broken_parts=(),
    )
    assert "怪物状态" not in _render_action_hint_from_report(src)


def test_hud_enemy_states_long_line_not_wrapped() -> None:
    """状态多且长（超 14 全角）→ 仍单行全量输出，不折行（用户 2026-09-12 拍板）。"""
    src = SimpleNamespace(
        player=10, enemy=5, player_max_hp=20, enemy_max_hp=10, enemy_name="脊冢幼兽",
        enemy_air=True, enemy_broken_parts=("左翼", "尾部", "右翼", "头壳"),
    )
    lines = _render_action_hint_from_report(src).split("\n")
    assert "怪物状态：跃空丨左翼破坏丨尾部破坏丨右翼破坏丨头壳破坏" in lines
    assert not any(ln.strip() in ("右翼破坏", "头壳破坏") for ln in lines)   # 无续行


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
# ⑥ T5：`_status_display_name` 的 ctx["statuses"] 分支
# ---------------------------------------------------------------------------

def test_status_display_name_ctx_statuses_mapping() -> None:
    """T5：事件无 name → 查 ctx["statuses"]（映射/字符串/缺 name 三种回落）。"""
    ctx_mapping = {"statuses": {"burn": {"name": "燃烧"}}}
    assert _status_display_name({"type": "dot_damage", "status": "burn"}, ctx_mapping) == "燃烧"
    # 字符串形态：直接作为展示名
    assert _status_display_name({"status": "burn"}, {"statuses": {"burn": "灼烧"}}) == "灼烧"
    # Mapping 缺 name → 回落 id
    assert _status_display_name({"status": "burn"}, {"statuses": {"burn": {}}}) == "burn"
    # 无 statuses / 非 Mapping ctx → 回落 id
    assert _status_display_name({"status": "burn"}, {}) == "burn"
    assert _status_display_name({"status": "burn"}, None) == "burn"
    # 事件自带 name 优先于 ctx 查表
    assert _status_display_name(
        {"status": "burn", "name": "事件名"}, ctx_mapping) == "事件名"


def test_effect_lines_use_ctx_statuses_name() -> None:
    """T5 端到端：ctx["statuses"] 提供展示名 → effect 行出中文名（事件不带 name）。"""
    src = SimpleNamespace(effect_events=(
        {"type": "dot_damage", "side": "player", "status": "burn", "value": 4},
        {"type": "status_expired", "side": "enemy", "status": "rage"},
    ))
    lines = _render_effect_lines(src, ctx={
        "statuses": {"burn": {"name": "燃烧"}, "rage": "狂暴"},
    })
    assert lines == [
        "【持续效果】燃烧 生效，你受到 4 伤害。",
        "【效果失效】狂暴 效果时间结束。",
    ]


# ---------------------------------------------------------------------------
# T1：defer_tail（终局尾提示置底）——HUD 块不出尾行
# ---------------------------------------------------------------------------

def test_hud_defer_tail_omits_tail_line() -> None:
    """T1：defer_tail=True → HUD 块不出「→ 攻击…」尾行（改由结束消息末尾补）。"""
    base = dict(player=21, enemy=7, player_max_hp=30, enemy_max_hp=25, enemy_name="史莱姆")
    with_tail = _render_action_hint_from_report(SimpleNamespace(**base, defer_tail=False))
    assert "→ 攻击" in with_tail
    deferred = _render_action_hint_from_report(SimpleNamespace(**base, defer_tail=True))
    assert "→ 攻击" not in deferred
    # 其余 HUD 行不受影响
    assert "剩余生命：21/30" in deferred and "怪物生命：7/25" in deferred


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


# ---------------------------------------------------------------------------
# T9（复核修复 2026-09-12）：battle_hud_payload 对**真实** battle_state() 键名取数
# ---------------------------------------------------------------------------

def test_battle_hud_payload_from_real_engine_snapshot(seed: int) -> None:
    """T9：真实 BattleEngine 跑一回合 → battle_state() → payload 真键名命中。

    原测试用手造 snap，`battle_state()` 一旦改键名（如 mp→mana / shield 结构变动）
    不会被发现。本测试先断言真快照含 payload 读取的键路径，再断言取值一致；
    最后对真快照做部位破坏/跃空/护盾变异，验证载荷映射（真键 → HUD 原始数据）。
    """
    from qbot_rpg.commands.battle_commands import battle_hud_payload
    from qbot_rpg.core.battle import BattleEngine

    player = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100,
              "atk": 100, "dfn": 50, "mag": 50, "spd": 50, "name": "阿伟"}
    enemy = {"max_hp": 400, "hp": 400, "atk": 80, "dfn": 40, "mag": 30, "spd": 40,
             "name": "脊冢幼兽",
             "parts": [{"id": "p1", "name": "左翼"}, {"id": "p2", "name": "尾部"}]}
    eng = BattleEngine().start(dict(player), dict(enemy), random_seed=seed)
    eng.player_act({"type": "normal"})
    snap = eng.battle_state()

    # ① 真快照键路径（payload 消费点）
    assert snap["player"]["mp"] == 100 and snap["player"]["max_mp"] == 100
    assert "shield" in snap["player"]["defenses"]
    assert "shield" in snap["enemy"]["defenses"]
    assert snap["combat_position"]["enemy"]["height"] == "ground"
    assert [p["id"] for p in snap["enemy"]["parts"]] == ["p1", "p2"]
    assert snap["parts_state"]["p1"]["broken"] is False

    hud = battle_hud_payload(snap)
    assert hud["player_mp"] == snap["player"]["mp"]
    assert hud["player_mp_max"] == snap["player"]["max_mp"]
    assert hud["player_shield"] == snap["player"]["defenses"]["shield"]["remaining"]
    assert hud["enemy_broken_parts"] == ()
    assert hud["enemy_air"] is False

    # ② 变异真快照（真实键路径）→ 部位破坏展示名 / 跃空 / 护盾剩余
    snap["parts_state"]["p1"]["broken"] = True
    snap["parts_state"]["p2"]["broken"] = True
    snap["combat_position"]["enemy"]["height"] = "air"
    snap["player"]["defenses"]["shield"]["remaining"] = 7
    snap["player"]["defenses"]["shield"]["turns"] = 2
    hud2 = battle_hud_payload(snap)
    assert hud2["enemy_broken_parts"] == ("左翼", "尾部")
    assert hud2["enemy_air"] is True
    assert hud2["player_shield"] == 7 and hud2["player_shield_turns"] == 2
