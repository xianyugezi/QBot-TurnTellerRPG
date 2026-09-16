"""批27 · α7：技能附加的「对方」减益与持续制式（CakeGame 装备附加Re《核心配置》:133-145）。

**现状核查结论（本批拍板）**：α7 的"对方属性减益 + 回合制持续 + 可叠加"**已可由
既有字段表达**，故**不新增任何 effects 字段**。既有面：
  · `target`（self/enemy）：`core/effects.py::execute_action` 顶部
    `target = _resolve_side(attacker, action.get("target","enemy"))`——`target:"enemy"`
    即对方，已有；
  · 对方属性减益两条既有通道：
      ① 直接补丁 `{"type":"stat_modifier","target":"enemy","stat":"atk",
         "value":-30,"pct":true}`（即时、无持续，写快照）；
      ② 持续性减益 = 状态（statuses.json）+ `{"type":"status_apply","target":"enemy",
         "status_id":"..."}`；状态 `duration:{turns,charges}` 为**回合制**，`tick_turns`
         到 0 即移除，战斗增伤聚合 `battle._aggregate_boost` **实时**读活状态实例→
         到期自动回滚（无需"撤销补丁"）；
  · `max_stack` + `stack_frame`：`"dual"` = 两槽相加（可叠加，实测 -20%×2=-40%）；
    `"stack"` = 层数计数（本框架既有多态，语义见 `core/effects.py::apply_status`）。
**缺口（如实登记，不在本批新造）**：
  · **时间制（秒）持续**不存在——本框架战斗是 CTB 回合/行动驱动（无墙钟计时），
    这是模型差异而非字段缺口（他们的 `Pattern=0` 时间制在本框架无对应物）；
  · 战斗内可改的属性为 combatant 快照键（atk/dfn/mag/... 见 battle._DEFAULT_STATS），
    无"基础/特殊/技能/熟练/物品"分层属性命名空间（熟练度是独立子系统）；
  · `effects[].patch`（`field_meta.py:1716`）是**已登记但引擎无消费点**的死字段，
    本批不使用它（减益走 `stat_modifier` 通道）。

覆盖：
  - 元数据：本项**零新增字段**（字段对拍删除/值变化 = 0）；
  - 引擎消费（数值级）：对方 atk 直接补丁 200→140；状态减益使怪**出手伤害降 30%**；
    回合制到期回滚；dual 叠加 -20%×2；
  - 回归：不带减益 → boost 0 / 倍率 1.0，逐字段一致。

测试只建临时对象，绝不写真实内容包。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.effects import execute_action
from qbot_rpg.core.effect_types import DamageCtx


def _engine(defs: Optional[Dict[str, Any]] = None, *, seed: int = 11) -> BattleEngine:
    eng = BattleEngine(defs=defs or {}, config={})
    eng.start(
        {"hp": 5000, "max_hp": 5000, "mp": 100, "max_mp": 100,
         "atk": 100, "def": 0, "spr": 0, "spd": 10, "foc": 500, "con": 0,
         "lck": 0, "int": 0, "name": "玩家"},
        {"hp": 2000, "max_hp": 2000, "mp": 0, "max_mp": 0,
         "atk": 200, "def": 0, "spr": 0, "spd": 1, "foc": 0, "con": 0,
         "lck": 0, "int": 0, "name": "桩"},
        random_seed=seed,
    )
    return eng


_ATK_DOWN = {
    "atk_down": {"id": "atk_down", "name": "破甲", "type": "debuff", "category": "weak",
                 "stack_frame": "stack", "max_stack": 3,
                 "duration": {"turns": 9, "charges": 0}, "decay": "none",
                 "actions": [{"type": "stat_modifier", "stat": "atk", "value": "-30%"}]},
}
_ATK_DOWN_DUAL = {
    "atk_down_dual": {"id": "atk_down_dual", "name": "破甲(双槽)", "type": "debuff",
                      "category": "weak", "stack_frame": "dual",
                      "duration": {"turns": 9, "charges": 0}, "decay": "none",
                      "actions": [{"type": "stat_modifier", "stat": "atk",
                                   "value": "-20%"}]},
}


def _apply(eng: BattleEngine, status_id: str, times: int = 1) -> None:
    rt = eng._new_runtime()  # noqa: SLF001 - 引擎运行期实例读取位（同既有测试口径）
    for _ in range(times):
        rt.apply_status(status_id, "enemy")
    eng._absorb_runtime(rt)  # noqa: SLF001


# ---------------------------------------------------------------------------
# 对方属性减益（数值级）
# ---------------------------------------------------------------------------
def test_a7_direct_enemy_attr_patch_numeric() -> None:
    """既有 stat_modifier 通道可直接补「对方」属性：敌 atk 200 →(pct -30%)→ 140。"""
    eng = _engine()
    assert int(eng.battle_state()["enemy"]["atk"]) == 200
    ctx = DamageCtx(raw_damage=0, attack_type="skill", attacker="player",
                    target="enemy", snapshot=eng._snap, variables={})  # noqa: SLF001
    res = execute_action(
        {"type": "stat_modifier", "target": "enemy", "stat": "atk",
         "value": -30, "pct": True},
        ctx, eng._new_runtime(),  # noqa: SLF001
    )
    assert res.ok is True, res
    assert int(ctx.snapshot["enemy"]["atk"]) == 140, ctx.snapshot["enemy"]["atk"]
    assert any(e.get("type") == "stat_modified" and e.get("target") == "enemy"
               for e in res.side_effects), res.side_effects


def test_a7_enemy_debuff_lowers_outgoing_damage() -> None:
    """状态减益（target=enemy）经战斗增伤聚合实时消费：怪出手伤害降 ~30%（贴数值）。"""
    a = _engine(_ATK_DOWN)
    dmg_no = a.do_action("enemy", {"type": "normal", "mult": 1.0}).final_damage

    b = _engine(_ATK_DOWN)
    _apply(b, "atk_down")
    assert b._aggregate_boost("enemy", "atk") == -30.0  # noqa: SLF001
    assert b._apply_boost_to_mult("enemy", 1.0, "atk") == 0.7  # noqa: SLF001
    dmg_yes = b.do_action("enemy", {"type": "normal", "mult": 1.0}).final_damage
    assert dmg_yes < dmg_no, (dmg_yes, dmg_no)
    assert abs(dmg_yes - int(round(dmg_no * 0.7))) <= 2, (dmg_yes, dmg_no)


def test_a7_debuff_is_turn_based_and_reverts_on_expiry() -> None:
    """回合制持续：`duration.turns` 到 0 → 状态移除 → 减益自动回滚（无需撤销补丁）。"""
    eng = _engine(_ATK_DOWN)
    _apply(eng, "atk_down")
    assert eng._aggregate_boost("enemy", "atk") == -30.0  # noqa: SLF001
    for _ in range(20):  # 超过 turns=9
        eng._new_runtime().tick_turns("enemy")  # noqa: SLF001
    assert eng._aggregate_boost("enemy", "atk") == 0.0  # noqa: SLF001


def test_a7_dual_slot_stacking_compounds() -> None:
    """可叠加：stack_frame="dual" 两槽相加 → -20%×2 = -40%（实测数值）。"""
    eng = _engine(_ATK_DOWN_DUAL)
    _apply(eng, "atk_down_dual", times=2)
    assert len(eng._new_runtime().status_instances("enemy")) == 2  # noqa: SLF001
    assert eng._aggregate_boost("enemy", "atk") == -40.0  # noqa: SLF001


def test_a7_regression_without_debuff_identical() -> None:
    """不带减益 → 聚合 0 / 倍率 1.0；怪出手伤害与基线一致（逐字段）。"""
    a = _engine(_ATK_DOWN)
    b = _engine(_ATK_DOWN)
    assert a._aggregate_boost("enemy", "atk") == 0.0  # noqa: SLF001
    assert a._apply_boost_to_mult("enemy", 1.0, "atk") == 1.0  # noqa: SLF001
    oa = a.do_action("enemy", {"type": "normal", "mult": 1.0})
    ob = b.do_action("enemy", {"type": "normal", "mult": 1.0})
    assert (oa.final_damage, oa.target_hp) == (ob.final_damage, ob.target_hp)
