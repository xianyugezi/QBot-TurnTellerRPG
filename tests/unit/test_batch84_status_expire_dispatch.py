"""批84 · B3：tick **到期**派发 `status_lose`（on_expire / on_lose 生效）回归。

设计口径（判据 → 裁定「该触发」）：
  · `docs/细化/细化_1b_效果系统契约.md:106`：`on_gain`/`on_lose`/`on_expire`
    三字段「状态获得/**消失**/**过期**时触发」；
  · `docs/框架_功能三_通用效果事件分派器_设计.md:100`（§2.4）+ `:120`（§三 批3）：
    `_remove_status / dispel / tick 过期 → 补 dispatch status_lose/on_expire`；
  · `docs/深度打造_实现说明.md:736`：`status_lose` = 状态获得 / 消失（**含过期**）。

覆盖：
  1. 持续双维（`turns` 归零）到期 → `on_expire` 触发；
  2. 衰减（`decay` 归零）到期 → `on_expire` 触发；
  3. `on_lose` 与 `on_expire` 共用 `status_lose`，两者都在到期触发；
  4. 未声明 `on_lose`/`on_expire` → **零行为变化**（对拍口径）；
  5. 未注册分派器 → 安全失败（不崩、不副作用）。
"""
from __future__ import annotations

from typing import Any, Optional

from qbot_rpg.core import effects as fx
from qbot_rpg.core import event_dispatcher as _ed  # noqa: F401 —— 注册状态事件回调


def _snap() -> dict:
    return {
        "player": {"hp": 300, "max_hp": 500, "atk": 50, "dfn": 50},
        "enemy": {"hp": 300, "max_hp": 300, "atk": 40, "dfn": 30},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
    }


def _inst(sid: str, *, turns: int = 1, value: int = 0, decay: str = "none") -> dict:
    return {"status_id": sid, "name": sid, "category": "buff", "level": 1,
            "stacks": 1, "value": value, "turns": turns, "charges": 0,
            "decay": decay, "decay_subject": "carrier", "source": "player",
            "immune_uses": 0, "trigger_halve": False, "_uid": 1}


def _rt(snap: dict, defs: Optional[dict] = None) -> fx.EffectRuntime:
    rt = fx.EffectRuntime(status_state=snap["status_state"],
                          marks_state=snap["marks_state"])
    d = defs or {}
    rt._resolver = lambda i, k: d.get(i)
    return rt


def _boom_defs(sid: str, **extra: Any) -> dict:
    d = {"id": sid, "type": "buff", "category": "buff",
         "duration": {"turns": 1, "charges": 0}}
    d.update(extra)
    return {sid: d, "boom": {"id": "boom", "type": "damage", "power": 30}}


def test_tick_turns_expire_fires_on_expire() -> None:
    """持续双维归零（tick_turns）→ on_expire 效果触发（修前不触发，待查 P-1）。"""
    s = _snap()
    s["status_state"]["player"].append(_inst("shield", turns=1))
    fx.tick_turn_end(s, _rt(s, _boom_defs("shield", on_expire=[
        {"effect": "boom", "target": "enemy"}])))
    assert s["enemy"]["hp"] == 270, f"on_expire 应触发，enemy hp={s['enemy']['hp']}"
    assert s["status_state"]["player"] == []      # 状态仍按既有逻辑移除


def test_tick_turns_expire_fires_on_lose() -> None:
    """on_lose 与 on_expire 共用 `status_lose` → 到期同样触发。"""
    s = _snap()
    s["status_state"]["player"].append(_inst("shield", turns=1))
    fx.tick_turn_end(s, _rt(s, _boom_defs("shield", on_lose=[
        {"effect": "boom", "target": "enemy"}])))
    assert s["enemy"]["hp"] == 270


def test_decay_expire_fires_on_expire() -> None:
    """衰减归零（tick_after_action → decay_carrier）→ on_expire 触发。"""
    s = _snap()
    s["status_state"]["player"].append(
        _inst("wither", turns=-1, value=1, decay="decrement"))
    fx.tick_after_action(s, _rt(s, _boom_defs("wither", decay="decrement",
                                              on_expire=[{"effect": "boom",
                                                          "target": "enemy"}])),
                         "player")
    assert s["enemy"]["hp"] == 270


def test_no_declaration_zero_change() -> None:
    """未声明 on_lose/on_expire → 与修前逐字段一致（无副作用，仅既有 log/移除）。"""
    s = _snap()
    s["status_state"]["player"].append(_inst("shield", turns=1))
    log = fx.tick_turn_end(s, _rt(s, _boom_defs("shield")))
    assert s["enemy"]["hp"] == 300 and s["player"]["hp"] == 300
    assert [e["type"] for e in log] == ["status_expired"]
    assert log[0]["status"] == "shield"


def test_unregistered_dispatcher_safe_failure(monkeypatch) -> None:
    """未注册分派器（单测只 import effects 的场景）→ [] 安全失败，不崩/不副作用。"""
    monkeypatch.setattr(fx, "_STATUS_EVENT_DISPATCHER", None)
    s = _snap()
    s["status_state"]["player"].append(_inst("shield", turns=1))
    fx.tick_turn_end(s, _rt(s, _boom_defs("shield", on_expire=[
        {"effect": "boom", "target": "enemy"}])))
    assert s["enemy"]["hp"] == 300
    assert s["status_state"]["player"] == []


def test_helper_empty_for_unknown_status() -> None:
    s = _snap()
    out = fx._dispatch_status_expire("player", "不存在", s, _rt(s, {}))
    assert out == []
    out2 = fx._dispatch_status_expire("player", "", s, _rt(s, {}))
    assert out2 == []
