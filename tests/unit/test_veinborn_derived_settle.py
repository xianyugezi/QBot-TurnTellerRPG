"""veinborn G1 派生结算修复单测（tests/unit/test_veinborn_derived_settle.py）。

背景：veinborn 破脉核派生链（chain_core_break：rb_core_strike→vb_core_breaker，
mode=replace，condition target_marks break_vein_core min:120）在 battle 层
_resolve_combo_action 派生成功（form_id 替换）后，伤害倍率/effects 仍停留在
源技能 def：伤害只有源技能 power 60 → 0.6×，而非派生技 vb_core_breaker
power 200 → 2.0×；core_broken 印记不挂（源技能 mark_add break_vein_core
重复执行）。

修复（qbot_rpg/core/battle.py _resolve_combo_action 派生分支）：form_id 替换
发生后重新按派生技 def 解析 mult/effects/tag/armor/hits——显式给定值保持
优先（与上方 power 折算/effects 合并同一口径），非派生路径零变化。

覆盖：
  1. 派生后伤害倍率跟随派生技 def（power 200 → ~2.0×）
  2. 派生后 effects 跟随派生技 def（core_broken 印记出现；源印记不再重复加）
  3. 非派生路径零变化：源技能直接施放仍 power/100 折算 + 源 effects
  4. 无条件 replace 派生（无 target_marks 条件）同样跟随派生技
  5. 显式 mult/effects 优先于派生技 def（显式值不被覆写）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine


# ---------------------------------------------------------------------------
# 夹具（刻意与 veinborn content 同构的最小 defs，零 content 依赖）
# ---------------------------------------------------------------------------

def _defs(**over: Any) -> Dict[str, Dict[str, Any]]:
    """最小派生链 defs：源技能 power60 mark_add X20；派生技 power200 mark_add Y1。"""
    d: Dict[str, Dict[str, Any]] = {
        "rb_core_strike": {
            "id": "rb_core_strike", "name": "贯核击", "type": "active",
            "kind": "damage", "power": 60, "mp_cost": 0,
            "effects": [{"type": "mark_add", "target": "enemy",
                         "mark": "break_vein_core", "count": 20}],
            "chain_refs": ["chain_core_break"],
        },
        "vb_core_breaker": {
            "id": "vb_core_breaker", "name": "破脉核", "type": "active",
            "kind": "damage", "power": 200, "mp_cost": 0,
            "effects": [{"type": "mark_add", "target": "enemy",
                         "mark": "core_broken", "count": 1}],
            "consume_marks": {"break_vein_core": 120},
        },
        "plain_strike": {
            "id": "plain_strike", "name": "普技", "type": "active",
            "kind": "damage", "power": 60, "mp_cost": 0,
            "effects": [{"type": "mark_add", "target": "enemy",
                         "mark": "break_vein_core", "count": 20}],
        },
    }
    d.update(over.get("skills") or {})
    chains = over.get("chains")
    d["chain_core_break"] = chains or {
        "id": "chain_core_break", "name": "破脉核链",
        "trigger_skill": "rb_core_strike", "max_combo": 1,
        "max_combo_behavior": "reset",
        "steps": [{
            "from": "rb_core_strike", "to": "vb_core_breaker",
            "tag": "none", "condition": {
                "target_marks": {"break_vein_core": {"min": 120}}},
            "priority": 1, "mode": "replace", "armor": False,
            "consume": 0, "variant_override": {},
        }],
    }
    return d


def _engine(**over: Any) -> BattleEngine:
    defs = _defs(**{k: v for k, v in over.items() if k in ("skills", "chains")})
    eng = BattleEngine(defs=defs)
    eng.start(
        {"hp": 2000, "max_hp": 2000, "mp": 100, "max_mp": 100,
         "atk": 100, "def": 0, "spr": 0, "spd": 10, "foc": 100, "con": 0,
         "lck": 0, "int": 0, "elem_atk": 0, "name": "玩家"},
        {"hp": 2000, "max_hp": 2000, "mp": 0, "max_mp": 0,
         "atk": 0, "def": 0, "spr": 0, "spd": 10, "foc": 0, "con": 0,
         "lck": 0, "int": 0, "elem_atk": 0, "name": "砾冕"},
        random_seed=7,
    )
    return eng


def _mark_count(eng: BattleEngine, side: str, mark_id: str) -> int:
    """读 marks_state 中指定印记总层数（无定义也按实例层数计）。"""
    ms = eng.battle_state()["marks_state"].get(side, [])
    return sum(int(i.get("count", 0)) for i in ms if i.get("mark_id") == mark_id)


def _marks(eng: BattleEngine, side: str) -> list:
    return eng.battle_state()["marks_state"].get(side, [])


def _enemy_hp(eng: BattleEngine) -> int:
    return int(eng.battle_state()["enemy"]["hp"])


# ---------------------------------------------------------------------------
# 修复主断言：派生触发后结算跟随派生技
# ---------------------------------------------------------------------------

def test_derived_damage_uses_derived_power() -> None:
    """派生触发后伤害按派生技 power 200 折算（≈2.0×），不再停留 0.6×。"""
    eng = _engine()
    # 预置破坏值 120（源技能 6 下满；第 7 下触发派生）
    eng.marks_manager().apply_add(
        __import__("qbot_rpg.core.marks", fromlist=["AddMark"]).AddMark(
            side="enemy", mark="break_vein_core", count=120))
    hp0 = _enemy_hp(eng)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
    assert out.ok is True, f"派生施放应成功，got {out}"
    hp1 = _enemy_hp(eng)
    dmg = hp0 - hp1
    # 2.0× × atk100（无防御无会心）≈ 200 ± 乱数；0.6× 只会有 ~60
    assert dmg > 120, f"派生伤害应按 2.0× 结算（≈200），got {dmg}（0.6× 缺陷≈60）"
    assert dmg < 260, f"派生伤害不应超 2.0× 封顶范围，got {dmg}"
    # combo 侧派生标记真实命中（step_index≥0 由 combo 引擎写入）
    cs = eng.battle_state()["combo_state"]["player"]
    assert cs.get("chain_id") == "chain_core_break"


def test_derived_effects_use_derived_def() -> None:
    """派生后 effects 跟随派生技 def：core_broken 印记出现、源印记不再重复加。"""
    eng = _engine()
    eng.marks_manager().apply_add(
        __import__("qbot_rpg.core.marks", fromlist=["AddMark"]).AddMark(
            side="enemy", mark="break_vein_core", count=120))
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
    assert out.ok is True, f"派生施放应成功，got {out}"
    assert _mark_count(eng, "enemy", "core_broken") == 1, \
        f"派生技 core_broken 印记应挂 1，got {_mark_count(eng, 'enemy', 'core_broken')}"
    # 源印记不再重复 +20（修复前每下派生都重复执行源 effects）
    assert _mark_count(eng, "enemy", "break_vein_core") == 120, \
        f"源印记不应再被重复累加，got {_mark_count(eng, 'enemy', 'break_vein_core')}"
    assert any(e.get("type") == "mark_add" and e.get("mark_id") == "core_broken"
               for e in out.side_effects), "outcome side_effects 应含派生技 mark_add"


def test_non_derived_path_unchanged() -> None:
    """非派生路径零变化：未达条件直接施放源技能 = power/100 折算 + 源 effects。"""
    eng = _engine()
    hp0 = _enemy_hp(eng)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
    assert out.ok is True, f"源技能施放应成功，got {out}"
    hp1 = _enemy_hp(eng)
    dmg = hp0 - hp1
    assert dmg < 120, f"非派生应 0.6×（≈60），got {dmg}"
    assert _mark_count(eng, "enemy", "break_vein_core") == 20, \
        f"非派生应执行源 effects（+20），got {_mark_count(eng, 'enemy', 'break_vein_core')}"
    assert _mark_count(eng, "enemy", "core_broken") == 0, "非派生不应挂派生技印记"
    # 派生技直接施放（cast to，路径 a）也跟派生技 def——顺带回归派生通道：
    # 预置破坏值满 120 → 条件满足 → 派生施放成功且结算跟派生技
    eng.marks_manager().apply_add(
        __import__("qbot_rpg.core.marks", fromlist=["AddMark"]).AddMark(
            side="enemy", mark="break_vein_core", count=120))
    hp0b = _enemy_hp(eng)
    out2 = eng.do_action("player", {"type": "skill", "skill_id": "vb_core_breaker"})
    assert out2.ok is True, f"直接施放派生技应成功，got {out2}"
    dmg2 = hp0b - _enemy_hp(eng)
    assert dmg2 > 120, f"直接施放派生技也应 2.0×（≈200），got {dmg2}"


def test_unconditional_replace_chain_derives() -> None:
    """无条件 replace 派生（无 target_marks 条件）同样跟随派生技 def。"""
    eng = _engine(chains={
        "id": "chain_core_break", "name": "破脉核链",
        "trigger_skill": "rb_core_strike", "max_combo": 1,
        "max_combo_behavior": "reset",
        "steps": [{
            "from": "rb_core_strike", "to": "vb_core_breaker",
            "tag": "none", "condition": {},
            "priority": 1, "mode": "replace", "armor": False,
            "consume": 0, "variant_override": {},
        }],
    })
    hp0 = _enemy_hp(eng)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
    assert out.ok is True, f"无条件派生应成功，got {out}"
    dmg = hp0 - _enemy_hp(eng)
    assert dmg > 120, f"无条件派生也应 2.0×（≈200），got {dmg}"
    assert _mark_count(eng, "enemy", "core_broken") == 1, "无条件派生也应挂派生技印记"


def test_explicit_mult_effects_keep_priority() -> None:
    """显式给定 mult/effects 优先于派生技 def（与上方 power 折算同一口径）。"""
    eng = _engine()
    eng.marks_manager().apply_add(
        __import__("qbot_rpg.core.marks", fromlist=["AddMark"]).AddMark(
            side="enemy", mark="break_vein_core", count=120))
    hp0 = _enemy_hp(eng)
    out = eng.do_action("player", {
        "type": "skill", "skill_id": "rb_core_strike", "mult": 0.5,
        "effects": [{"type": "mark_add", "target": "enemy",
                     "mark": "explicit_mark", "count": 3}],
    })
    assert out.ok is True, f"显式 mult 派生施放应成功，got {out}"
    dmg = hp0 - _enemy_hp(eng)
    assert dmg < 120, f"显式 mult 0.5 应优先（≈50），got {dmg}"
    assert _mark_count(eng, "enemy", "explicit_mark") == 3, "显式 effects 应优先执行"
    assert _mark_count(eng, "enemy", "core_broken") == 0, \
        "显式 effects 优先时派生技 effects 不应执行"


def test_mult0_derived_skill_still_resolves() -> None:
    """mult=0 派生伤害零伤害路径不崩（占位校验派生分支多段/0 倍率健壮性）。"""
    eng = _engine()
    eng.marks_manager().apply_add(
        __import__("qbot_rpg.core.marks", fromlist=["AddMark"]).AddMark(
            side="enemy", mark="break_vein_core", count=120))
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike",
                                   "mult": 0.0})
    assert out.ok is True, f"mult=0 派生不应被拒，got {out}"
    # mult=0 段：不造成伤害，但 effects 仍执行（core_broken 挂上）
    assert _enemy_hp(eng) == 2000, "mult=0 不应造成伤害"
    assert _mark_count(eng, "enemy", "core_broken") == 1, "mult=0 派生 effects 仍应执行"
