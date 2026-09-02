"""功能二 · 效果引用归一 + 效果条件化 单元测试（2026-09-02 框架级新增）。

依据：docs/框架_功能二_效果引用归一与条件化_设计.md（§2 设计 + §三 测试用例）。

覆盖：
  1. 引用展开：{effect: burn_dot} → 合成 dot action 执行（target dot_pool 有条目）
  2. overrides 覆盖：{power:50} 键过映射表翻译 → value=50（定义 power:12 被覆盖）
  3. 无条件引用 = 既有行为（回归：直接 type action 不受影响）
  4. condition 命中/不命中：target_marks vulnerable 存在→执行/不存在→跳过
  5. condition 复合：self_status + target_hp_pct（and 拓扑）
  6. 未知 effect id → 安全失败不崩
  7. proc 内引用生效（execute_proc_action 子动作过归一）
  8. 环引用深度截断（A 引用 B 引用 A）→ 不崩

确定性：全部直接构造快照 + defs 注入，零随机。
"""
from __future__ import annotations

from qbot_rpg.core.effects import DamageCtx, EffectRuntime, execute_action


def _snap(player_hp: int = 500, enemy_hp: int = 300,
          enemy_marks: list | None = None, player_statuses: list | None = None) -> dict:
    """构造最小战斗快照（五块在顶层，对齐 battle.py L194 marks_state 快照形态）。"""
    ss = {"player": list(player_statuses or []), "enemy": []}
    ms = {"player": [], "enemy": list(enemy_marks or [])}
    return {
        "player": {"hp": player_hp, "max_hp": 500, "mp": 100, "atk": 50, "dfn": 50},
        "enemy": {"hp": enemy_hp, "max_hp": 300, "atk": 40, "dfn": 30},
        "status_state": ss,
        "marks_state": ms,
        "turn": 1,
    }


def _status_inst(status_id: str) -> dict:
    return {"status_id": status_id, "name": status_id, "category": "增益",
            "remaining_turns": 3}


def _mark(mark_id: str, count: int) -> dict:
    return {"mark_id": mark_id, "name": mark_id, "count": count,
            "polarity": "negative", "remaining_turns": None}


# 简化 effects 定义（对齐 content/test_demo/effects.json 形态）
_DEFS = {
    "burn_dot": {"id": "burn_dot", "name": "灼烧", "type": "dot",
                 "power": 12, "duration": 3},
    "heal_small": {"id": "heal_small", "name": "小回复", "type": "heal", "power": 50},
    "l2_pack": {"id": "l2_pack", "name": "复合包", "type": "special",
                "actions": [{"type": "mark_add", "target": "enemy",
                             "mark": "vulnerable", "count": 1},
                            {"effect": "burn_dot"}]},
    # 环引用：a_loop → b_loop → a_loop（深度截断用）
    "a_loop": {"id": "a_loop", "type": "special", "actions": [{"effect": "b_loop"}]},
    "b_loop": {"id": "b_loop", "type": "special", "actions": [{"effect": "a_loop"}]},
}


def _rt(snap: dict) -> EffectRuntime:
    rt = EffectRuntime(status_state=snap.get("status_state"),
                       marks_state=snap.get("marks_state"))
    # resolver：kind=effect 查 _DEFS
    rt._resolver = lambda id_, kind: _DEFS.get(id_) if kind == "effect" else None  # type: ignore[attr-defined]
    return rt


def _ctx(snap: dict) -> DamageCtx:
    return DamageCtx(raw_damage=0, attack_type="skill", attacker="player",
                     target="enemy", snapshot=snap)


# ---------------------------------------------------------------- 1. 引用展开

def test_ref_expand_dot_executes():
    """{effect: burn_dot} 引用 → 合成 dot action 执行（enemy dot_pool 有条目）。"""
    snap = _snap()
    res = execute_action({"effect": "burn_dot"}, _ctx(snap), _rt(snap))
    assert res.ok
    pool = snap["enemy"].get("dot_pool") or {}
    assert "dot" in pool, f"dot_pool 应有 dot 条目，实际 {pool}"
    assert pool["dot"]["value"] == 12, f"定义 power:12 应生效，实际 {pool['dot']}"
    assert pool["dot"]["turns"] == 3


def test_ref_overrides_maps_power_to_value():
    """overrides {power:50} 键过映射表 → value=50（定义 power:12 被覆盖）。"""
    snap = _snap()
    res = execute_action({"effect": "burn_dot", "overrides": {"power": 50}},
                         _ctx(snap), _rt(snap))
    assert res.ok
    pool = snap["enemy"].get("dot_pool") or {}
    assert pool["dot"]["value"] == 50, f"overrides power:50 应覆盖为 value:50，实际 {pool['dot']}"


# ---------------------------------------------------------------- 2. L2 容器

def test_ref_l2_container_actions_execute():
    """定义带 actions（L2/special）→ 子动作全执行（mark_add + 内嵌引用 burn_dot）。"""
    snap = _snap()
    res = execute_action({"effect": "l2_pack"}, _ctx(snap), _rt(snap))
    assert res.ok
    # mark_add vulnerable 生效
    marks = snap["marks_state"]["enemy"]
    assert any(m["mark_id"] == "vulnerable" for m in marks), f"应施加 vulnerable，实际 {marks}"
    # 内嵌 burn_dot 也执行
    pool = snap["enemy"].get("dot_pool") or {}
    assert "dot" in pool, "L2 容器内嵌引用应执行"


# ---------------------------------------------------------------- 3. 无条件回归

def test_direct_type_action_unaffected():
    """直接 type action（无 effect 键）→ 原样走既有分支（零行为变化）。"""
    snap = _snap(player_hp=400)  # 残血才能验证 heal
    res = execute_action({"type": "heal", "value": 30, "target": "player"},
                         _ctx(snap), _rt(snap))
    assert res.ok
    assert snap["player"]["hp"] == 430, f"heal 30 应生效，实际 hp={snap['player']['hp']}"


# ---------------------------------------------------------------- 4. condition

def test_condition_target_marks_hit_skip():
    """condition target_marks vulnerable：不存在 → 跳过；存在 → 执行。"""
    snap = _snap()  # enemy 无 marks
    cond = {"condition": {"target_marks": {"vulnerable": {"min": 1}}}}
    res = execute_action({"effect": "burn_dot", **cond}, _ctx(snap), _rt(snap))
    assert not res.ok and not res.side_effects, "vulnerable 不存在 → 应跳过"
    assert "dot_pool" not in snap["enemy"], "跳过时不应施加 dot"
    # 有 vulnerable → 执行
    snap2 = _snap(enemy_marks=[_mark("vulnerable", 1)])
    res2 = execute_action({"effect": "burn_dot", **cond}, _ctx(snap2), _rt(snap2))
    assert res2.ok, f"vulnerable 存在 → 应执行，实际 {res2.message}"


def test_condition_absent_marks():
    """condition 支持 absent（无指定印记才执行）。"""
    snap = _snap(enemy_marks=[_mark("core_broken", 1)])
    cond = {"condition": {"target_marks": {"core_broken": {"absent": True}}}}
    res = execute_action({"effect": "burn_dot", **cond}, _ctx(snap), _rt(snap))
    assert not res.ok and not res.side_effects, "core_broken 存在 → absent 条件不满足应跳过"
    snap2 = _snap()
    res2 = execute_action({"effect": "burn_dot", **cond}, _ctx(snap2), _rt(snap2))
    assert res2.ok, "无 core_broken → absent 满足应执行"


def test_condition_composite_and():
    """condition 复合 and：self_status + target_hp_pct 同时满足才执行。"""
    # player 有 buff 状态 + enemy 血量 50% (<80)
    snap = _snap(player_statuses=[_status_inst("stone_shield")], enemy_hp=150)
    cond = {"condition": {"and": [
        {"self_status": {"has": ["stone_shield"]}},
        {"target_hp_pct": {"max": 80}},
    ]}}
    res = execute_action({"effect": "burn_dot", **cond}, _ctx(snap), _rt(snap))
    assert res.ok, f"复合条件满足应执行，实际 {res.message}"
    # 不满足（无状态）
    snap2 = _snap(enemy_hp=150)
    res2 = execute_action({"effect": "burn_dot", **cond}, _ctx(snap2), _rt(snap2))
    assert not res2.ok and not res2.side_effects, "无状态 → 复合不满足应跳过"


# ---------------------------------------------------------------- 5. 未知 id

def test_unknown_effect_id_safe_fail():
    """未知 effect id → 安全失败不崩。"""
    snap = _snap()
    res = execute_action({"effect": "nonexistent_fx"}, _ctx(snap), _rt(snap))
    assert not res.ok
    assert snap["enemy"].get("dot_pool") is None, "未知 id 不应产生副作用"


# ---------------------------------------------------------------- 6. proc 内引用

def test_proc_subaction_ref_executes():
    """execute_proc_action 子动作过归一（proc actions 内嵌 effect 引用生效）。"""
    from qbot_rpg.core.effects import execute_proc_action
    snap = _snap()
    proc = {"id": "p1", "chance": 1.0,
            "actions": [{"effect": "burn_dot", "overrides": {"power": 30}}]}
    res = execute_proc_action(proc, _ctx(snap), _rt(snap))
    assert res.ok
    pool = snap["enemy"].get("dot_pool") or {}
    assert pool.get("dot", {}).get("value") == 30, f"proc 内引用应生效，实际 {pool}"


# ---------------------------------------------------------------- 7. 环引用深度截断

def test_loop_ref_depth_truncated():
    """环引用（a_loop→b_loop→a_loop）→ 深度超限截断不崩。"""
    snap = _snap()
    res = execute_action({"effect": "a_loop"}, _ctx(snap), _rt(snap))
    # 深度超限 → 返回 not ok（截断），不抛异常不卡死
    assert not res.ok
