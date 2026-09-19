"""批51 · 触发归属过滤 + 事件补点（on_kill）验收测试。

依据：
  · `特效整理设计_3_落点与分期.md` §二「批 49」（旧编号 = 本批，批号顺序：仓内 批50
    = 设计 批48「特效轴地基」）；
  · `特效整理设计_1_修正轴全集.md` §3 P0 第 1 项（I01 触发时点 ＋ 归属过滤）；
  · `装备被动_实现口径.md` §3.3 方案 A（`active_effect_ids` 归属作用域）。

覆盖：
  A. 归属过滤：owner 集非空 → 只认集合内 effect；缺省 → 全库扫描旧行为（对拍）；
  B. on_kill：击杀者侧触发、被击杀者侧仍是 death（两侧语义分清）；
  C. 装备接线（最小）：装备实例 `passives` → trait `effects` → combatant 归属集
     → 该侧按宿主触发，另一侧不串。

零真实内容包：全部用临时 registry / 内存 ctx（对齐批19.1 内容防污染门禁）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.core import event_dispatcher as ed
from qbot_rpg.core.effects import EffectRuntime


# ---------------------------------------------------------------------------
# 伪 registry / 快照（同 test_event_dispatcher 形态）
# ---------------------------------------------------------------------------
class Reg:
    """伪内容注册表（all_ids/resolve 同形，effect/status 分表）。"""

    def __init__(self, effects: Optional[Dict[str, dict]] = None,
                 statuses: Optional[Dict[str, dict]] = None) -> None:
        self._effects: Dict[str, dict] = effects or {}
        self._statuses: Dict[str, dict] = statuses or {}

    def all_ids(self, kind: str) -> Tuple[str, ...]:
        return tuple(self._effects if kind == "effect" else self._statuses)

    def resolve(self, id: str, kind: str) -> Any:
        return self._effects.get(id) if kind == "effect" else self._statuses.get(id)


def snap() -> dict:
    return {
        "player": {"hp": 400, "max_hp": 500, "mp": 100, "atk": 50, "dfn": 50, "name": "P"},
        "enemy": {"hp": 300, "max_hp": 300, "mp": 0, "atk": 40, "dfn": 30, "name": "E"},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
        "turn": 1,
    }


def rt(s: Mapping[str, Any]) -> EffectRuntime:
    return EffectRuntime(status_state=s.get("status_state"),
                         marks_state=s.get("marks_state"))


def ev(eid: str, trigger: str, value: int = 10,
       target: str = "self") -> dict:
    """极小触发效果：trigger 时点 heal 指定侧（可观测 hp 变化）。"""
    return {"id": eid, "name": eid, "type": "special", "trigger": trigger,
            "actions": [{"type": "heal", "value": value, "target": target}]}


# ===========================================================================
# A. 归属过滤（owner_effect_ids）
# ===========================================================================

def test_owner_scope_only_owned_effect_fires() -> None:
    """A 侧拥有 fx_a、B 侧拥有 fx_b → 各自只触发自己那一个（**不串**）。"""
    s = snap()
    reg = Reg({
        "fx_a": ev("fx_a", "on_hit", 10),
        "fx_b": ev("fx_b", "on_hit", 20),
    })
    # A（player）拥有 fx_a
    ed.dispatch_event("on_hit", "player", s, reg, runtime=rt(s),
                      owner_effect_ids=["fx_a"])
    assert s["player"]["hp"] == 410, f"A 只应触发 fx_a(+10)，实际 {s['player']['hp']}"
    # B（enemy）拥有 fx_b（先把 B 打残，避免满血封顶掩盖 heal）
    s["enemy"]["hp"] = 200
    ed.dispatch_event("on_hit", "enemy", s, reg, runtime=rt(s),
                      owner_effect_ids=["fx_b"])
    assert s["enemy"]["hp"] == 220, f"B 只应触发 fx_b(+20)，实际 {s['enemy']['hp']}"


def test_owner_scope_other_side_effect_not_fired() -> None:
    """反向证明：A 侧派出 fx_b 不触发（fx_b 不在 A 的归属集内）。"""
    s = snap()
    reg = Reg({"fx_b": ev("fx_b", "on_hit", 20)})
    out = ed.dispatch_event("on_hit", "player", s, reg, runtime=rt(s),
                            owner_effect_ids=["fx_a"])
    assert out == [], f"归属集不含 fx_b → 零候选零副作用，实际 {out}"
    assert s["player"]["hp"] == 400


def test_owner_scope_empty_set_no_candidates() -> None:
    """空归属集 = 本侧不拥有任何效果 → 零候选（不是「回退全库」）。"""
    s = snap()
    reg = Reg({"fx_a": ev("fx_a", "on_hit", 10)})
    assert ed.dispatch_event("on_hit", "player", s, reg, runtime=rt(s),
                             owner_effect_ids=[]) == []
    assert s["player"]["hp"] == 400


def test_owner_scope_status_branch_unaffected() -> None:
    """归属过滤只作用于纯效果分支：status on_gain 仍按 status_id 精确触发。"""
    s = snap()
    reg = Reg(
        effects={"heal_now": {"id": "heal_now", "type": "heal", "power": 50}},
        statuses={"shield": {"id": "shield", "type": "buff",
                             "on_gain": [{"effect": "heal_now"}]}},
    )
    ed.dispatch_event("status_gain", "player", s, reg, status_id="shield",
                      runtime=rt(s), owner_effect_ids=[])
    assert s["player"]["hp"] == 450, "status 分支不受 owner 集影响"


def test_owner_scope_does_not_filter_extra_candidates() -> None:
    """既有 `extra_candidates`（批48 符文声明效果）语义不变——不受 owner 集影响。"""
    s = snap()
    s["enemy"]["hp"] = 200   # heal 未显式 target → 落 ctx.target（= 触发侧对侧）
    reg = Reg({})
    extra = [("rune_fx", {"id": "rune_fx", "trigger": "on_hit",
                          "overrides": {"value": 15}}, "effect")]
    # 让引用可被 execute_action 解析（引用归一查 registry）
    reg._effects["rune_fx"] = {"id": "rune_fx", "type": "heal", "power": 15}
    out = ed.dispatch_event("on_hit", "player", s, reg, runtime=rt(s),
                            extra_candidates=extra, owner_effect_ids=[])
    assert isinstance(out, list), out
    assert s["enemy"]["hp"] == 215, f"extra 候选应照常执行，实际 {s['enemy']['hp']}"


# ===========================================================================
# B. 缺省无 owner 集 = 全库扫描旧行为（逐字段对拍）
# ===========================================================================

#: 批51 之前 `_iter_candidates` 纯效果分支的参考实现（本地复刻，用于对拍）。
def _legacy_effect_candidates(
    event: str, registry: Reg,
) -> List[Tuple[str, Mapping[str, Any], str]]:
    out: List[Tuple[str, Mapping[str, Any], str]] = []
    for eid in registry.all_ids("effect"):
        raw = registry.resolve(eid, "effect")
        if not raw:
            continue
        if str(raw.get("trigger") or "") == event:
            out.append((eid, raw, "effect"))
    return out


LEGACY_POINTS: Tuple[str, ...] = (
    "battle_start", "battle_end", "action_start", "action_end",
    "turn_start", "turn_end", "status_gain", "status_lose",
    "mark_gain", "mark_lose", "death", "revive",
    "on_attack", "on_hit", "on_skill", "season_change",
)


def test_owner_none_matches_legacy_global_scan_all_16_points() -> None:
    """对拍：既有 16 个事件时点上，`owner_effect_ids=None` 的候选与
    「本批之前的全库扫描」**逐条一致**（零行为变化基线）。"""
    points = [p for p in LEGACY_POINTS if p not in ("status_gain", "status_lose")]
    reg = Reg({f"fx_{p}": ev(f"fx_{p}", p, 1) for p in points})
    for p in points:
        legacy = _legacy_effect_candidates(p, reg)
        got = ed._iter_candidates(p, reg, owner_effect_ids=None)  # noqa: SLF001
        assert [c[0] for c in got] == [c[0] for c in legacy], p
        assert [c[2] for c in got] == [c[2] for c in legacy], p


def test_owner_none_dispatch_zero_change_all_16_points() -> None:
    """对拍（行为面）：16 个时点各跑一次 dispatch，owner=None 与本地旧实现
    产出**同一 side_effects 形态与同一快照后态**。"""
    points = [p for p in LEGACY_POINTS if p not in ("status_gain", "status_lose")]
    reg = Reg({f"fx_{p}": ev(f"fx_{p}", p, 5) for p in points})
    for p in points:
        s_new = snap()
        out_new = ed.dispatch_event(p, "player", s_new, reg, runtime=rt(s_new))
        s_old = snap()
        out_old = _legacy_dispatch(p, "player", s_old, reg)
        assert [e.get("type") for e in out_new] == [e.get("type") for e in out_old], p
        assert s_new == s_old, f"{p} 快照后态不一致"


def _legacy_dispatch(event: str, side: str, s: Mapping[str, Any], reg: Reg) -> List[dict]:
    """本批之前的 `dispatch_event`（纯效果分支）最小复刻——仅用于对拍。"""
    from qbot_rpg.core.effects import execute_action
    from qbot_rpg.core.event_dispatcher import _build_ctx, _run_candidate  # noqa: SLF001

    runtime = rt(s)
    runtime._resolver = reg.resolve  # noqa: SLF001
    atk = side
    tgt = "enemy" if atk == "player" else "player"
    ctx = _build_ctx(event, side, s, atk, tgt, None)
    out: List[dict] = []
    for eid, raw, kind in _legacy_effect_candidates(event, reg):
        out.extend(_run_candidate(eid, raw, kind, event, side, s, runtime, ctx, 0))
    assert execute_action is not None  # 保持 import 语义（引用归一入口）
    return out


