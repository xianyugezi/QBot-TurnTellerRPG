"""M2 怪物条件行动 + 连招链（B2 路）单元测试（新增：B2 无留存 smoke，本文件补齐缺口）。

依据：细化_1f_怪物AI状态机.md（② L3 条件行动——13 类触发匹配、priority 降序同级随机、
once/max_triggers/trigger_cooldown 过滤；⑤ 5.2 chain C 模型——首节点 chance roll 决定入队/
断链+冷却、套内确定性、5.4 打断=套完结）＋ docs/m2_shared_contract.md §一（trigger 13 类
枚举/旧别名归一/special_actions 条目结构/after_action timing）＋ §五（evaluate_conditions
返回约定 / roll_chain 签名 / ai_state 快照）。

monster_conditions 覆盖：
  13 类触发逐一用例（hp_below 阈值命中/不命中、pv_broken、get_up、battle_start、
  after_action 缺 action/chance 返回空、player_status、player_hp_below、turn_count、
  phase_changed、zone_changed、ally_dead、combo_broken、script）
  x_ 自定义扩展（register_condition）+ 未知名兜底 False
  旧别名归一（broken→pv_broken / revive→get_up / enter_phase→battle_start）
  priority 降序同级随机（Fisher-Yates 注入 rng 可复现）
  once / max_triggers / trigger_cooldown 过滤 + commit=False 纯匹配不记账
  post_state 生效（state 切换 + post_state 扩展键 {state, turns, until}）
  铁律 6：需 roll/排序未注入 rng → ValueError；ai_state 缺失 → ValueError

monster_chains 覆盖：
  evaluate_chain 首节点 chance roll（入队 True / 断链 False）+ 链冷却过滤（不消耗 rng）
  evaluate_chain 边界（缺 actions / chance<=0 / 缺 rng → ValueError）
  node_chance 缺省 1.0 / 夹取 0-1 / 越界 0.0
  enqueue_chain 全链序列入队 + 空链 no-op
  on_chain_broken 清队列 + exec_state 回 idle + 当前链进冷却（既有更高冷却保留）
  chain_validation_rules 登记表 + 返回拷贝

确定性（铁律 6/8）：全部注入 ScriptedRng 固定序列；禁止裸/未播种 random。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core import monster_conditions as mc
from qbot_rpg.core.monster_chains import (
    chain_validation_rules,
    enqueue_chain,
    evaluate_chain,
    node_chance,
    on_chain_broken,
)

# 13 类触发权威枚举（contract §一）
TRIGGER_TYPES = mc.TRIGGER_TYPES


class ScriptedRng:
    """注入确定性 rng（铁律 6）：按脚本序列循环返回 random()，并记录调用次数。"""

    def __init__(self, values):
        self._values = list(values)
        self.calls = 0

    def random(self):
        v = self._values[self.calls % len(self._values)] if self._values else 0.0
        self.calls += 1
        return v


def bs_builder(**over):
    """构造 battle_state（含 ai_state 14 键 + B2 additive 扩展键；contract §五）。"""
    ai = {"state": "normal", "exec_state": "idle", "phase": 1, "chain_pos": 0,
          "chain_queue": [], "chain_id": None, "chain_cooldowns": {}, "charge": None,
          "trigger_cooldowns": {}, "action_cooldowns": {}, "hungry_count": {},
          "intent": {}, "forced_queue": [], "boss_phase": 1,
          "trigger_used_once": [], "trigger_counts": {}}
    d = {"turn": 1, "enemy": {"hp": 100, "max_hp": 100, "pv": 10},
         "players": [], "allies": [], "ai_state": ai}
    d.update(over)
    return d


def hp_below_entry(value=50, **extra):
    """标准 hp_below 条件行动条目（B2 记账键：action|type|value）。"""
    e = {"action": "fireball", "trigger": {"type": "hp_below", "value": value}}
    e.update(extra)
    return e


def _fireball_key():
    return "fireball|hp_below|50"


# ================================================================== 13 类触发逐一用例

def test_trigger_hp_below_hit_and_miss():
    # 命中：hp 30/100 < 50
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    m = mc.evaluate_conditions_all([hp_below_entry()], bs, ScriptedRng([0.5]))
    assert len(m) == 1 and m[0]["action"] == "fireball", m
    # 不命中：hp 60/100
    bs = bs_builder(enemy={"hp": 60, "max_hp": 100, "pv": 10})
    assert mc.evaluate_conditions_all([hp_below_entry()], bs, ScriptedRng([0.5])) == []
    # 无 max_hp → False
    bs = bs_builder(enemy={"hp": 30})
    assert mc.evaluate_conditions_all([hp_below_entry()], bs, ScriptedRng([0.5])) == []


def test_trigger_pv_broken():
    sa = [{"action": "shield_break", "trigger": {"type": "pv_broken"}}]
    # pv<=0 → 命中
    bs = bs_builder(enemy={"hp": 100, "max_hp": 100, "pv": 0})
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1 and m[0]["action"] == "shield_break", m
    # pv>0 → 不命中（缺省 pv 按 1）
    bs = bs_builder(enemy={"hp": 100, "max_hp": 100, "pv": 10})
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    bs = bs_builder(enemy={"hp": 100, "max_hp": 100})
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_get_up():
    sa = [{"action": "roar_again", "trigger": {"type": "get_up"}}]
    # battle_state["downed"]=True → 命中（TC-05：起身后下一回合窗口）
    bs = bs_builder(downed=True)
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1 and m[0]["action"] == "roar_again", m
    # ai_state.exec_state == "downed" → 命中
    bs = bs_builder()
    bs["ai_state"]["exec_state"] = "downed"
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # 均不满足 → 不命中
    bs = bs_builder()
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_battle_start():
    sa = [{"action": "opening", "trigger": {"type": "battle_start"}}]
    # turn<=1 → 命中（开场技）
    bs = bs_builder(turn=1)
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # battle_start 标记 → 命中（换区重触发，1e A06 ④）
    bs = bs_builder(turn=5, battle_start=True)
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # turn>1 且无标记 → 不命中
    bs = bs_builder(turn=5)
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_after_action_missing_params_empty():
    """after_action 缺 action 或 chance → 不匹配返回空（A2 R11 硬拦口径）。"""
    # 缺 action
    sa = [{"action": "combo2", "trigger": {"type": "after_action", "chance": 50}}]
    bs = bs_builder(last_action="fireball")
    assert mc.evaluate_conditions_all(sa, bs, rng=None) == []
    # 缺 chance
    sa = [{"action": "combo2", "trigger": {"type": "after_action", "action": "fireball"}}]
    bs = bs_builder(last_action="fireball")
    assert mc.evaluate_conditions_all(sa, bs, rng=None) == []
    # last_action 不匹配 → 不命中（且不消耗 rng）
    sa = [{"action": "combo2", "trigger": {"type": "after_action", "action": "fireball",
                                           "chance": 50}}]
    bs = bs_builder(last_action="claw")
    rng = ScriptedRng([0.4])
    assert mc.evaluate_conditions_all(sa, bs, rng=rng) == []
    assert rng.calls == 0


def test_trigger_after_action_chance_roll():
    sa = [{"action": "combo2", "trigger": {"type": "after_action", "action": "fireball",
                                           "chance": 50}}]
    # rng 0.4 → 40 < 50 → 命中
    bs = bs_builder(last_action="fireball")
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.4]))
    assert len(m) == 1 and m[0]["action"] == "combo2", m
    # rng 0.6 → 60 < 50 不成立 → 不命中
    bs = bs_builder(last_action="fireball")
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.6])) == []


def test_trigger_player_status():
    sa = [{"action": "punish", "trigger": {"type": "player_status", "value": "burn"}}]
    # statuses 列表命中
    bs = bs_builder(players=[{"id": "p1", "statuses": ["burn"]}])
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # effects 列表 {id} 命中
    bs = bs_builder(players=[{"id": "p1", "statuses": [], "effects": [{"id": "burn"}]}])
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # effects 纯字符串列表命中
    bs = bs_builder(players=[{"id": "p1", "statuses": [], "effects": ["burn"]}])
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # 无该状态 → 不命中
    bs = bs_builder(players=[{"id": "p1", "statuses": ["poison"]}])
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # value 缺失 → 不命中
    sa_no = [{"action": "x", "trigger": {"type": "player_status"}}]
    bs = bs_builder(players=[{"id": "p1", "statuses": ["burn"]}])
    assert mc.evaluate_conditions_all(sa_no, bs, ScriptedRng([0.5])) == []


def test_trigger_player_hp_below():
    sa = [{"action": "finish", "trigger": {"type": "player_hp_below", "value": 50}}]
    # 任一玩家 30% < 50 → 命中
    bs = bs_builder(players=[{"id": "p1", "hp": 30, "max_hp": 100},
                             {"id": "p2", "hp": 80, "max_hp": 100}])
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # 全玩家 ≥50% → 不命中
    bs = bs_builder(players=[{"id": "p1", "hp": 60, "max_hp": 100}])
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # 无玩家 → 不命中
    bs = bs_builder()
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_turn_count():
    sa = [{"action": "late_game", "trigger": {"type": "turn_count", "value": 5}}]
    # op 默认 >=：turn=5 → 命中
    bs = bs_builder(turn=5)
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # turn=4 → 不命中
    bs = bs_builder(turn=4)
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # op "<" 形态
    sa_lt = [{"action": "early", "trigger": {"type": "turn_count", "value": 3, "op": "<"}}]
    bs = bs_builder(turn=2)
    assert len(mc.evaluate_conditions_all(sa_lt, bs, ScriptedRng([0.5]))) == 1
    bs = bs_builder(turn=3)
    assert mc.evaluate_conditions_all(sa_lt, bs, ScriptedRng([0.5])) == []


def test_trigger_phase_changed():
    sa = [{"action": "p2_skill", "trigger": {"type": "phase_changed", "value": 2}}]
    # phase>=value → 命中（B1 内建口径：名称含 changed，口径=当前 phase 已达到）
    bs = bs_builder()
    bs["ai_state"]["phase"] = 2
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # phase 未达 → 不命中
    bs = bs_builder()
    bs["ai_state"]["phase"] = 1
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # value 缺失 → 不命中
    sa_no = [{"action": "x", "trigger": {"type": "phase_changed"}}]
    bs = bs_builder()
    bs["ai_state"]["phase"] = 3
    assert mc.evaluate_conditions_all(sa_no, bs, ScriptedRng([0.5])) == []


def test_trigger_zone_changed():
    sa = [{"action": "zone_skill", "trigger": {"type": "zone_changed"}}]
    # zone_changed 标记 → 命中
    bs = bs_builder(zone_changed=True)
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # zone != prev_zone → 命中
    bs = bs_builder(zone="volcano", prev_zone="village")
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # 同区 → 不命中
    bs = bs_builder(zone="volcano", prev_zone="volcano")
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # 均缺 → 不命中
    bs = bs_builder()
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_ally_dead():
    sa = [{"action": "avenge", "trigger": {"type": "ally_dead"}}]
    # hp<=0 → 命中
    bs = bs_builder(allies=[{"id": "a1", "hp": 0}])
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # alive=False → 命中
    bs = bs_builder(allies=[{"id": "a1", "hp": 50, "alive": False}])
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # dead=True → 命中
    bs = bs_builder(allies=[{"id": "a1", "hp": 50, "dead": True}])
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    # 全存活 → 不命中
    bs = bs_builder(allies=[{"id": "a1", "hp": 50, "alive": True}])
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # value 指定友方：仅特定 id 阵亡才命中
    sa_want = [{"action": "avenge_b", "trigger": {"type": "ally_dead", "value": "a2"}}]
    bs = bs_builder(allies=[{"id": "a1", "hp": 0}, {"id": "a2", "hp": 50, "alive": True}])
    assert mc.evaluate_conditions_all(sa_want, bs, ScriptedRng([0.5])) == []
    bs = bs_builder(allies=[{"id": "a1", "hp": 0}, {"id": "a2", "hp": 0}])
    assert len(mc.evaluate_conditions_all(sa_want, bs, ScriptedRng([0.5]))) == 1


def test_trigger_combo_broken():
    sa = [{"action": "counter", "trigger": {"type": "combo_broken"}}]
    # 本回合连招被打断（C1 置 battle_state["combo_broken"]=True）→ 命中
    bs = bs_builder(combo_broken=True)
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1 and m[0]["action"] == "counter", m
    # 无标记 → 不命中
    bs = bs_builder()
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_script():
    sa = [{"action": "scripted", "trigger": {"type": "script", "value": "rage"}}]
    # script_flags[value] 为真 → 命中
    bs = bs_builder(script_flags={"rage": True})
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    # 为假 → 不命中
    bs = bs_builder(script_flags={"rage": False})
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # value 缺失 → 不命中
    sa_no = [{"action": "x", "trigger": {"type": "script"}}]
    bs = bs_builder(script_flags={"rage": True})
    assert mc.evaluate_conditions_all(sa_no, bs, ScriptedRng([0.5])) == []


def test_trigger_types_enum_complete():
    """TRIGGER_TYPES 权威枚举 = 13 类（contract §一）。"""
    assert len(TRIGGER_TYPES) == 13
    assert set(TRIGGER_TYPES) == {
        "hp_below", "pv_broken", "get_up", "battle_start", "after_action",
        "player_status", "player_hp_below", "turn_count", "phase_changed",
        "zone_changed", "ally_dead", "combo_broken", "script",
    }


# ================================================================== x_ 自定义扩展 / 未知类型

def test_x_custom_extension_register():
    mc.register_condition("x_custom", lambda trig, bs, rng: bs.get("custom_flag") is True)
    try:
        sa = [{"action": "custom", "trigger": {"type": "x_custom", "value": "whatever"}}]
        bs = bs_builder(custom_flag=True)
        m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
        assert len(m) == 1 and m[0]["action"] == "custom", m
        bs = bs_builder(custom_flag=False)
        assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    finally:
        mc._CUSTOM_HANDLERS.pop("x_custom", None)


def test_x_custom_extension_decorator_form():
    @mc.register_condition("x_deco")
    def _h(trig, bs, rng):  # noqa: ANN001
        return bs.get("deco_flag") is True
    try:
        sa = [{"action": "deco", "trigger": {"type": "x_deco"}}]
        bs = bs_builder(deco_flag=True)
        assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
        bs = bs_builder(deco_flag=False)
        assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    finally:
        mc._CUSTOM_HANDLERS.pop("x_deco", None)


def test_unknown_trigger_type_false():
    sa = [{"action": "mystery", "trigger": {"type": "no_such_trigger"}}]
    bs = bs_builder()
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # 无 trigger / 非 mapping → 跳过
    assert mc.evaluate_conditions_all([{"action": "x"}], bs, ScriptedRng([0.5])) == []
    assert mc.evaluate_conditions_all(["not_a_mapping"], bs, ScriptedRng([0.5])) == []


# ================================================================== 旧别名归一（contract §一）

def test_old_alias_normalization():
    assert mc.normalize_trigger_type("broken") == "pv_broken"
    assert mc.normalize_trigger_type("revive") == "get_up"
    assert mc.normalize_trigger_type("enter_phase") == "battle_start"
    assert mc.normalize_trigger_type("hp_below") == "hp_below"  # canonical 恒等
    assert mc.normalize_trigger_type("x_custom") == "x_custom"
    assert mc.normalize_trigger_type(123) == ""  # 非 str → ""


def test_alias_broken_maps_pv_broken():
    sa = [{"action": "guard_crash", "trigger": {"type": "broken"}}]
    bs = bs_builder(enemy={"hp": 100, "max_hp": 100, "pv": 0})
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    bs = bs_builder(enemy={"hp": 100, "max_hp": 100, "pv": 10})
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_alias_revive_maps_get_up():
    sa = [{"action": "revive_skill", "trigger": {"type": "revive"}}]
    bs = bs_builder(downed=True)
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    bs = bs_builder()
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_alias_enter_phase_maps_battle_start():
    sa = [{"action": "opening2", "trigger": {"type": "enter_phase"}}]
    bs = bs_builder(turn=1)
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    bs = bs_builder(turn=5)
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


# ================================================================== priority 降序同级随机

def test_priority_desc_order():
    """priority 降序：队首=最高优，与 rng 无关。"""
    sa = [hp_below_entry(action="low", priority=5),
          hp_below_entry(action="high", priority=10)]
    for seed in ([0.0], [0.99], [0.5]):
        bs = bs_builder(enemy={"hp": 10, "max_hp": 100, "pv": 10})
        m = mc.evaluate_conditions_all(sa, bs, ScriptedRng(seed))
        assert [e["action"] for e in m] == ["high", "low"], (seed, m)


def test_priority_default_zero_sorts_last():
    """无 priority 默认 0 → 排在有 priority 的条目之后。"""
    sa = [hp_below_entry(action="no_prio"),
          hp_below_entry(action="prio5", priority=5)]
    bs = bs_builder(enemy={"hp": 10, "max_hp": 100, "pv": 10})
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert [e["action"] for e in m] == ["prio5", "no_prio"], m


def test_same_priority_random_tie():
    """同级随机（Fisher-Yates 注入 rng，铁律 6）：不同 rng 可达不同队首。"""
    sa = [hp_below_entry(action="a"),
          hp_below_entry(action="b")]
    bs = bs_builder(enemy={"hp": 10, "max_hp": 100, "pv": 10})
    m0 = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.0]))
    bs = bs_builder(enemy={"hp": 10, "max_hp": 100, "pv": 10})
    m1 = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.99]))
    assert m0[0]["action"] == "b", m0   # r=0 → 交换 → [b, a]
    assert m1[0]["action"] == "a", m1   # r≈1 → 不交换 → [a, b]
    assert {e["action"] for e in m0} == {"a", "b"}


# ================================================================== once / max_triggers / trigger_cooldown 过滤

def test_once_only_triggers_once():
    sa = [hp_below_entry(once=True)]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    m1 = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m1) == 1, m1
    assert _fireball_key() in bs["ai_state"]["trigger_used_once"]
    # 第二次评估 → 过滤（TC-05 once 语义）
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_max_triggers_limits():
    sa = [hp_below_entry(max_triggers=2)]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    assert bs["ai_state"]["trigger_counts"][_fireball_key()] == 1
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    assert bs["ai_state"]["trigger_counts"][_fireball_key()] == 2
    # 达上限 → 过滤
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_trigger_cooldown_blocks():
    sa = [hp_below_entry(trigger_cooldown=3)]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1
    assert bs["ai_state"]["trigger_cooldowns"][_fireball_key()] == 3
    # 冷却中 → 过滤
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []
    # 冷却归零（C1 回合边界递减）→ 可再次触发
    bs["ai_state"]["trigger_cooldowns"][_fireball_key()] = 0
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))) == 1


def test_id_based_bookkeeping_key():
    """记账键：special_action.id 优先；无 id → action|type|value（A04 id 选填）。"""
    sa = [hp_below_entry(id="s1", once=True)]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert "s1" in bs["ai_state"]["trigger_used_once"]
    assert _fireball_key() not in bs["ai_state"]["trigger_used_once"]
    # 再评估同 id 条目 → 被过滤
    assert mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5])) == []


def test_commit_false_pure_match_no_bookkeeping():
    sa = [hp_below_entry(once=True)]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]), commit=False)
    assert len(m) == 1, m
    assert bs["ai_state"]["trigger_used_once"] == [], "commit=False 不记账"
    # 连续纯匹配均可命中
    assert len(mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]), commit=False)) == 1


# ================================================================== post_state 应用

def test_post_state_applied():
    sa = [hp_below_entry(post_state={"state": "enraged", "turns": 2})]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10}, turn=3)
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    assert bs["ai_state"]["state"] == "enraged", "post_state 切行为态"
    assert bs["ai_state"]["post_state"] == {"state": "enraged", "turns": 2, "until": 5}, \
        bs["ai_state"]["post_state"]


def test_post_state_ignored_when_invalid():
    # 非 mapping / 无 state → 不生效
    sa = [hp_below_entry(post_state={"turns": 2})]
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    m = mc.evaluate_conditions_all(sa, bs, ScriptedRng([0.5]))
    assert len(m) == 1, m
    assert bs["ai_state"]["state"] == "normal"
    assert "post_state" not in bs["ai_state"]


# ================================================================== 铁律 6 / ai_state 前置（ValueError）

def test_requires_rng_when_matched():
    """需随机（同级排序/roll）而未注入 rng → ValueError（铁律 6，不给隐式系统随机源）。"""
    bs = bs_builder(enemy={"hp": 30, "max_hp": 100, "pv": 10})
    with pytest.raises(ValueError):
        mc.evaluate_conditions_all([hp_below_entry()], bs, rng=None)
    # 无匹配 → 无需 roll → 不抛
    bs = bs_builder(enemy={"hp": 60, "max_hp": 100, "pv": 10})
    assert mc.evaluate_conditions_all([hp_below_entry()], bs, rng=None) == []


def test_missing_ai_state_raises():
    bs = {"turn": 1, "enemy": {"hp": 30, "max_hp": 100, "pv": 10}}
    with pytest.raises(ValueError):
        mc.evaluate_conditions_all([hp_below_entry()], bs, ScriptedRng([0.5]))


# ================================================================== monster_chains：chain C 模型

def _chain_def():
    return {"id": "molten", "cooldown": 2,
            "actions": [{"action": "fireball", "chance": 0.8, "role": "chain"},
                        {"action": "tail_sweep", "chance": 1.0, "role": "finisher"}]}


def test_evaluate_chain_roll_success_and_fail():
    """链首节点 chance roll：rng.random() < 首节点 chance → 入队 True / 断链 False。"""
    cd = _chain_def()
    bs = bs_builder()
    assert evaluate_chain("molten", cd, bs["ai_state"], ScriptedRng([0.5])) is True  # 0.5<0.8
    bs = bs_builder()
    assert evaluate_chain("molten", cd, bs["ai_state"], ScriptedRng([0.9])) is False  # 0.9≥0.8
    # 成功路径消耗恰好 1 次 rng
    bs = bs_builder()
    rng = ScriptedRng([0.5])
    evaluate_chain("molten", cd, bs["ai_state"], rng)
    assert rng.calls == 1


def test_evaluate_chain_cooldown_blocks_without_roll():
    """链在冷却 → False 且不消耗 rng（冷却过滤优先于 roll）。"""
    cd = _chain_def()
    bs = bs_builder()
    bs["ai_state"]["chain_cooldowns"]["molten"] = 1
    rng = ScriptedRng([0.5])
    assert evaluate_chain("molten", cd, bs["ai_state"], rng) is False
    assert rng.calls == 0


def test_evaluate_chain_edges():
    """缺 actions / 首节点缺失 / chance<=0 → False；缺 rng → ValueError。"""
    bs = bs_builder()
    assert evaluate_chain("x", {}, bs["ai_state"], ScriptedRng([0.5])) is False
    assert evaluate_chain("x", None, bs["ai_state"], ScriptedRng([0.5])) is False
    assert evaluate_chain("x", {"actions": []}, bs["ai_state"], ScriptedRng([0.5])) is False
    cd0 = {"actions": [{"action": "a", "chance": 0.0}]}
    assert evaluate_chain("x", cd0, bs["ai_state"], ScriptedRng([0.5])) is False
    with pytest.raises(ValueError):
        evaluate_chain("molten", _chain_def(), bs["ai_state"], rng=None)


def test_node_chance_normalization():
    """节点 chance 归一 0-1：缺省 1.0（防御性兜底）/ 夹取 / 越界 0.0。"""
    assert node_chance({"actions": [{"action": "a"}]}, 0) == 1.0, "缺 chance → 1.0"
    assert node_chance({"actions": [{"action": "a", "chance": 0.8}]}, 0) == 0.8
    assert node_chance({"actions": [{"action": "a", "chance": 1.5}]}, 0) == 1.0, "夹取上限"
    assert node_chance({"actions": [{"action": "a", "chance": -0.2}]}, 0) == 0.0, "夹取下限"
    assert node_chance({"actions": [{"action": "a"}]}, 5) == 0.0, "越界"
    assert node_chance({}, 0) == 0.0
    assert node_chance({"actions": ["not_mapping"]}, 0) == 0.0


def test_enqueue_chain_full_sequence():
    """入队 = 全链序列（套内确定性执行）；触发行动 = 链首节点由调用方本次执行。"""
    bs = bs_builder()
    enqueue_chain("molten", _chain_def(), bs["ai_state"])
    ai = bs["ai_state"]
    assert ai["chain_queue"] == ["fireball", "tail_sweep"], ai["chain_queue"]
    assert ai["chain_id"] == "molten"
    assert ai["chain_pos"] == 0
    assert ai["exec_state"] == "in_chain"


def test_enqueue_chain_empty_noop():
    bs = bs_builder()
    before = dict(bs["ai_state"])
    enqueue_chain("x", {"actions": []}, bs["ai_state"])
    assert bs["ai_state"] == before, "空链不入队（no-op）"
    enqueue_chain("x", None, bs["ai_state"])
    assert bs["ai_state"] == before


def test_on_chain_broken_clears_and_cooldown():
    """打断=套完结（1f ⑤5.4）：清在途队列 + exec_state 回 idle + 当前链进冷却。"""
    bs = bs_builder()
    bs["ai_state"].update(chain_queue=["tail_sweep"], chain_id="molten", chain_pos=1,
                          exec_state="in_chain")
    on_chain_broken(bs["ai_state"])
    ai = bs["ai_state"]
    assert ai["chain_queue"] == [], "打断清在途队列"
    assert ai["chain_pos"] == 0
    assert ai["chain_id"] is None
    assert ai["exec_state"] == "idle", "下一回合走随机流程 L6"
    assert ai["chain_cooldowns"].get("molten", 0) == 1, "当前链进冷却（防同链立即重触发）"


def test_on_chain_broken_preserves_higher_cooldown():
    bs = bs_builder()
    bs["ai_state"].update(chain_queue=["tail_sweep"], chain_id="molten", chain_pos=1,
                          exec_state="in_chain", chain_cooldowns={"molten": 3})
    on_chain_broken(bs["ai_state"])
    assert bs["ai_state"]["chain_cooldowns"]["molten"] == 3, "既有更高冷却保留"


def test_on_chain_broken_no_chain_no_cooldown():
    bs = bs_builder()
    on_chain_broken(bs["ai_state"])
    assert bs["ai_state"]["chain_cooldowns"] == {}, "无在途链不登记冷却"


def test_chain_validation_rules_registry():
    """A2 已落地的校验规则登记表（本模块登记不重复实现）+ 返回拷贝防外部修改。"""
    rules = chain_validation_rules()
    for key in ("R15_chain_ref_missing", "R15_node_chance_required",
                "R15_node_role_enum", "R15_chain_continuation_lt60", "R15_chain_cycle"):
        assert key in rules, key
    rules["R15_chain_ref_missing"] = "mutated"
    assert chain_validation_rules()["R15_chain_ref_missing"] != "mutated", "返回拷贝"
