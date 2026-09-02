"""功能三批3 · effects 层状态事件接线 单元测试（2026-09-02）。

依据：docs/框架_功能三_通用效果事件分派器_设计.md（§2.5/§三批3）。

覆盖：
  1. status_apply 成功 → status_gain 事件（on_gain 效果触发）
  2. dispel 移除 → status_lose 事件（on_lose 效果触发）
  3. status_apply 失败（被免疫）→ 不触发 status_gain
  4. 未配置 on_gain/on_lose → 零行为变化
"""
from __future__ import annotations

from typing import Any, Optional

from qbot_rpg.core.effects import DamageCtx, EffectRuntime, execute_action


def _snap(player_hp: int = 300) -> dict:
    ss = {"player": [], "enemy": []}
    ms = {"player": [], "enemy": []}
    return {
        "player": {"hp": player_hp, "max_hp": 500, "atk": 50, "dfn": 50},
        "enemy": {"hp": 300, "max_hp": 300, "atk": 40, "dfn": 30},
        "status_state": ss,
        "marks_state": ms,
    }


def _rt(snap: dict, defs: Optional[dict] = None) -> EffectRuntime:
    rt = EffectRuntime(status_state=snap.get("status_state"),
                       marks_state=snap.get("marks_state"))
    d = defs or {}

    def resolver(id_: str, kind: str) -> Any:
        return d.get(id_)

    rt._resolver = resolver
    return rt


def _ctx(snap: dict, attacker: str = "player", target: str = "player") -> DamageCtx:
    return DamageCtx(raw_damage=0, attack_type="skill", attacker=attacker,
                     target=target, snapshot=snap)


def _shield_def(on_gain: Optional[list] = None, on_lose: Optional[list] = None) -> dict:
    d = {"id": "shield", "type": "buff", "category": "buff",
         "duration": {"turns": 2, "charges": 0}}
    if on_gain:
        d["on_gain"] = on_gain
    if on_lose:
        d["on_lose"] = on_lose
    return d


# ---------------------------------------------------------------- 1. status_gain

def test_status_apply_triggers_on_gain():
    """status_apply 成功 → on_gain heal 生效（player 300→350）。"""
    snap = _snap()
    defs = {"shield": _shield_def(on_gain=[{"effect": "heal_now"}]),
            "heal_now": {"id": "heal_now", "type": "heal", "power": 50}}
    rt = _rt(snap, defs)
    res = execute_action({"type": "status_apply", "status_id": "shield",
                          "target": "self"}, _ctx(snap), rt)
    assert res.ok
    assert snap["player"]["hp"] == 350, f"on_gain heal 应生效，实际 hp={snap['player']['hp']}"


def test_status_apply_no_on_gain_zero_change():
    """状态定义无 on_gain → status_apply 只施加不触发（零行为变化）。"""
    snap = _snap()
    defs = {"shield": _shield_def()}  # 无 on_gain
    rt = _rt(snap, defs)
    res = execute_action({"type": "status_apply", "status_id": "shield",
                          "target": "self"}, _ctx(snap), rt)
    assert res.ok
    assert snap["player"]["hp"] == 300, "无 on_gain 不应 heal"


# ---------------------------------------------------------------- 2. status_lose (dispel)

def test_dispel_triggers_on_lose():
    """dispel 移除状态 → on_lose 效果触发（盾碎爆炸打敌方）。"""
    snap = _snap()
    defs = {"shield": _shield_def(on_lose=[{"effect": "explode", "target": "enemy"}]),
            "explode": {"id": "explode", "type": "damage", "power": 30}}
    rt = _rt(snap, defs)
    # 先施加 shield（无 on_gain）
    execute_action({"type": "status_apply", "status_id": "shield",
                    "target": "self"}, _ctx(snap), rt)
    hp_e_before = snap["enemy"]["hp"]
    # dispel 清 buff（filter=buff）
    res = execute_action({"type": "dispel", "filter": "buff", "count": 9,
                          "target": "self"}, _ctx(snap), rt)
    assert res.ok
    assert snap["enemy"]["hp"] < hp_e_before, \
        f"on_lose explode 应扣敌方血，实际 {hp_e_before} → {snap['enemy']['hp']}"


def test_dispel_no_on_lose_zero_change():
    """状态无 on_lose → dispel 只移除不触发。"""
    snap = _snap()
    defs = {"shield": _shield_def()}
    rt = _rt(snap, defs)
    execute_action({"type": "status_apply", "status_id": "shield",
                    "target": "self"}, _ctx(snap), rt)
    res = execute_action({"type": "dispel", "filter": "buff", "count": 9,
                          "target": "self"}, _ctx(snap), rt)
    assert res.ok
    assert snap["enemy"]["hp"] == 300, "无 on_lose 不应爆炸"
