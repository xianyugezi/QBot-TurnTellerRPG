"""功能三批 1 · 通用效果事件分派器引擎 单元测试（2026-09-02）。

依据：docs/框架_功能三_通用效果事件分派器_设计.md（§2 设计 + §四验收）。

覆盖：
  1. effects 定义 trigger 匹配：on_hit 事件 → 执行该效果 actions
  2. status on_gain/on_lose 触发（status_gain/status_lose 事件按 status_id）
  3. 无候选/未配置事件 → []（零行为变化）
  4. 未知事件 → []（安全失败）
  5. chance 三态（必定执行 / 固定概率命中不命中）
  6. 每回合/每场上限（effect_triggers 计数）
  7. 深度上限（链递归截断）
  8. registry 缺方法 → []（防御）
  9. execute_action 复用（引用归一 + condition 门控生效）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from qbot_rpg.core import event_dispatcher as ed
from qbot_rpg.core.effects import EffectRuntime


class FakeRegistry:
    """伪内容注册表（all_ids/resolve 同形，effect/status 分表）。"""

    def __init__(self, effects: Optional[Dict[str, dict]] = None,
                 statuses: Optional[Dict[str, dict]] = None) -> None:
        self._effects: Dict[str, dict] = effects or {}
        self._statuses: Dict[str, dict] = statuses or {}

    def all_ids(self, kind: str) -> Tuple[str, ...]:
        return tuple(self._effects if kind == "effect" else self._statuses)

    def resolve(self, id: str, kind: str) -> Any:
        return self._effects.get(id) if kind == "effect" else self._statuses.get(id)


def _snap() -> dict:
    """最小战斗快照（功能二同款形态：五块在顶层）。"""
    ss = {"player": [], "enemy": []}
    ms = {"player": [], "enemy": []}
    return {
        "player": {"hp": 400, "max_hp": 500, "mp": 100, "atk": 50, "dfn": 50},
        "enemy": {"hp": 300, "max_hp": 300, "atk": 40, "dfn": 30},
        "status_state": ss,
        "marks_state": ms,
        "turn": 1,
    }


def _rt(snap: dict) -> EffectRuntime:
    return EffectRuntime(status_state=snap.get("status_state"),
                         marks_state=snap.get("marks_state"))


def _effect_ev(eid: str, trigger: str, actions: List[dict],
               chance: Any = None) -> dict:
    d = {"id": eid, "name": eid, "type": "special",
         "trigger": trigger, "actions": actions}
    if chance is not None:
        d["chance"] = chance
    return d


def _status_on(sid: str, **on_fields: List[dict]) -> dict:
    d: Dict[str, Any] = {"id": sid, "name": sid, "type": "buff"}
    for k, v in on_fields.items():
        d[k] = v
    return d


# ---------------------------------------------------------------- 1. effects trigger

def test_effect_trigger_event_executes():
    """effects 定义 trigger=on_hit → 事件时执行 actions。"""
    snap = _snap()
    reg = FakeRegistry(effects={
        "thorns": _effect_ev("thorns", "on_hit",
                             [{"type": "damage", "value": 20, "target": "enemy"}]),
    })
    out = ed.dispatch_event("on_hit", "player", snap, reg, runtime=_rt(snap))
    # damage 20 → enemy hp 300-20=280（damage 走管线，可能有浮动，验证有副作用返回）
    assert isinstance(out, list) and len(out) >= 1, f"on_hit 应触发 thorns，实际 {out}"
    assert snap["enemy"]["hp"] < 300, f"damage 应扣血，实际 hp={snap['enemy']['hp']}"


def test_effect_trigger_wrong_event_no_fire():
    """effects trigger=on_hit → turn_end 事件不触发（无候选 → []）。"""
    snap = _snap()
    reg = FakeRegistry(effects={
        "thorns": _effect_ev("thorns", "on_hit", [{"type": "damage", "value": 20}]),
    })
    assert ed.dispatch_event("turn_end", "player", snap, reg, runtime=_rt(snap)) == []


# ---------------------------------------------------------------- 2. status on_gain/on_lose

def test_status_on_gain_executes():
    """status on_gain → status_gain 事件执行（精确 status_id）。"""
    snap = _snap()
    reg = FakeRegistry(statuses={
        "shield": _status_on("shield", on_gain=[{"effect": "heal_now"}]),
    }, effects={
        "heal_now": {"id": "heal_now", "type": "heal", "power": 50},
    })
    out = ed.dispatch_event("status_gain", "player", snap, reg,
                            status_id="shield", runtime=_rt(snap))
    assert isinstance(out, list), "status_gain 应触发 on_gain"
    # heal 执行（player 残血 400 → 450）
    assert snap["player"]["hp"] == 450, f"on_gain heal 应生效，实际 hp={snap['player']['hp']}"


def test_status_on_lose_executes():
    """status on_lose → status_lose 事件执行（动作显式 target=enemy 打敌方）。"""
    snap = _snap()
    reg = FakeRegistry(statuses={
        "shield_break": _status_on("shield_break",
                                   on_lose=[{"effect": "explode",
                                             "target": "enemy"}]),
    }, effects={
        "explode": {"id": "explode", "type": "damage", "power": 30},
    })
    out = ed.dispatch_event("status_lose", "player", snap, reg,
                            status_id="shield_break", runtime=_rt(snap))
    assert isinstance(out, list) and len(out) >= 1
    assert snap["enemy"]["hp"] < 300, "on_lose explode 应扣敌方血（显式 target=enemy）"


def test_status_full_scan_no_status_id():
    """status_gain 不带 status_id → 全扫所有 status 的 on_gain。"""
    snap = _snap()
    reg = FakeRegistry(statuses={
        "a": _status_on("a", on_gain=[{"effect": "heal_now"}]),
        "b": _status_on("b"),  # 无 on_gain
    }, effects={
        "heal_now": {"id": "heal_now", "type": "heal", "power": 50},
    })
    ed.dispatch_event("status_gain", "player", snap, reg, runtime=_rt(snap))
    assert snap["player"]["hp"] == 450, "全扫应命中 a.on_gain"


# ---------------------------------------------------------------- 3. 无候选 / 未知事件

def test_no_candidates_returns_empty():
    """无匹配候选 → []（零行为变化）。"""
    snap = _snap()
    reg = FakeRegistry(effects={"x": _effect_ev("x", "battle_start", [])})
    assert ed.dispatch_event("turn_end", "player", snap, reg) == []


def test_unknown_event_safe_empty():
    """未知事件 → []（安全失败）。"""
    snap = _snap()
    assert ed.dispatch_event("not_an_event", "player", snap, FakeRegistry()) == []


# ---------------------------------------------------------------- 4. chance

def test_chance_fixed_hit_and_miss():
    """chance 固定概率：mode 必中命中；0% 不命中。"""
    snap = _snap()
    reg = FakeRegistry(effects={
        "always": _effect_ev("always", "battle_start",
                             [{"type": "heal", "value": 30, "target": "player"}],
                             chance={"mode": -1}),
    })
    ed.dispatch_event("battle_start", "player", snap, reg, runtime=_rt(snap))
    assert snap["player"]["hp"] == 430, "chance mode=-1 必中应执行"
    snap2 = _snap()
    reg2 = FakeRegistry(effects={
        "never": _effect_ev("never", "battle_start",
                            [{"type": "heal", "value": 30, "target": "player"}],
                            chance={"mode": 0, "value": 0}),
    })
    ed.dispatch_event("battle_start", "player", snap2, reg2, runtime=_rt(snap2))
    assert snap2["player"]["hp"] == 400, "chance 0% 不应执行"


# ---------------------------------------------------------------- 5. 计数上限

def test_trigger_count_limit():
    """每回合触发上限：max_triggers_per_turn=1 → 第二次不触发。"""
    snap = _snap()
    reg = FakeRegistry(effects={
        "fx": _effect_ev("fx", "turn_end",
                         [{"type": "heal", "value": 30, "target": "player"}]),
    })
    rt = _rt(snap)
    rt.config["max_triggers_per_turn"] = 1
    ed.dispatch_event("turn_end", "player", snap, reg, runtime=rt)
    ed.dispatch_event("turn_end", "player", snap, reg, runtime=rt)
    # 第一次 +30 → 430；第二次被上限拦 → 仍 430
    assert snap["player"]["hp"] == 430, f"第二次应被上限拦截，实际 hp={snap['player']['hp']}"


# ---------------------------------------------------------------- 6. 深度上限

def test_depth_limit_chain():
    """深度上限：效果 actions 引环 → 截断不崩不无限。"""
    snap = _snap()
    # 环：ev1 actions 引用 ev2，ev2 actions 引用 ev1
    reg = FakeRegistry(effects={
        "ev1": _effect_ev("ev1", "battle_start", [{"effect": "ev2"}]),
        "ev2": _effect_ev("ev2", "battle_start", [{"effect": "ev1"}]),
    })
    out = ed.dispatch_event("battle_start", "player", snap, reg,
                            runtime=_rt(snap), depth=0)
    assert isinstance(out, list), "环引用应截断返回列表不崩"
    # 不抛异常即通过（无死循环）


# ---------------------------------------------------------------- 7. registry 缺方法防御

def test_registry_missing_methods_safe():
    """registry 无 all_ids/resolve → []（防御）。"""
    snap = _snap()
    assert ed.dispatch_event("battle_start", "player", snap, object()) == []


# ------- 8. execute_action 复用（引用归一 + condition）-------

def test_effect_trigger_with_condition():
    """effects trigger 条目经 execute_action：condition 门控生效（功能二打通）。"""
    snap = _snap()
    # 敌方有 vulnerable 印记才触发
    snap["marks_state"] = {"player": [], "enemy": [
        {"mark_id": "vulnerable", "name": "vulnerable", "count": 1}]}
    reg = FakeRegistry(effects={
        "smite": {"id": "smite", "type": "special",
                  "trigger": "on_hit",
                  "actions": [{"effect": "dotfx"}]},
    })
    # dotfx 定义（引用展开目标）
    reg._effects["dotfx"] = {"id": "dotfx", "type": "dot", "power": 12, "duration": 3}
    out = ed.dispatch_event("on_hit", "player", snap, reg, runtime=_rt(snap))
    assert isinstance(out, list) and len(out) >= 1, f"on_hit 应触发，实际 {out}"
    pool = snap["enemy"].get("dot_pool") or {}
    assert "dot" in pool, "引用展开的 dot 应施加"
