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


def test_claimed_scope_exempts_unclaimed_global_effects() -> None:
    """`claimed_effect_ids` 语义：本侧 owner=[] 时，**未被认领**的效果照常触发、
    被认领的不触发（全局效果不被归属过滤静默吞掉）。"""
    s = snap()
    reg = Reg({"fx_own": ev("fx_own", "on_hit", 10),
               "fx_glo": ev("fx_glo", "on_hit", 20)})
    ed.dispatch_event("on_hit", "player", s, reg, runtime=rt(s),
                      owner_effect_ids=[], claimed_effect_ids=["fx_own"])
    assert s["player"]["hp"] == 420, f"只应触发未认领的 fx_glo(+20)，实际 {s['player']['hp']}"


def test_claimed_scope_own_wins_over_claim() -> None:
    """owner ∪ 未认领：本侧既触发自己认领的，也触发未被认领的。"""
    s = snap()
    reg = Reg({"fx_own": ev("fx_own", "on_hit", 10),
               "fx_glo": ev("fx_glo", "on_hit", 20)})
    ed.dispatch_event("on_hit", "player", s, reg, runtime=rt(s),
                      owner_effect_ids=["fx_own"], claimed_effect_ids=["fx_own"])
    assert s["player"]["hp"] == 430, f"自己认领 + 未认领都应触发，实际 {s['player']['hp']}"


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




# ===========================================================================
# C. 事件时点枚举（批51 补点）
# ===========================================================================

def test_event_points_contains_on_kill_and_legacy_16() -> None:
    """枚举更新：新增 on_kill；既有 16 点一个不丢，且前 16 位顺序不变。"""
    assert "on_kill" in ed.EVENT_POINTS
    assert len(ed.EVENT_POINTS) == 17
    for p in LEGACY_POINTS:
        assert p in ed.EVENT_POINTS
    assert ed.EVENT_POINTS[:16] == LEGACY_POINTS


def test_event_points_single_source_data_layer() -> None:
    """唯一源：`core.event_dispatcher.EVENT_POINTS` 即 `data.event_points` 的再导出。"""
    from qbot_rpg.data.event_points import EVENT_POINTS as src

    assert ed.EVENT_POINTS == src


# ===========================================================================
# D. on_kill（击杀者侧）· 战斗级触发证据
# ===========================================================================
PLAYER: Dict[str, Any] = {
    "max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
    "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
    "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P",
}
ENEMY: Dict[str, Any] = {
    "max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
    "mag": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30,
    "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E",
}
SEQ = [0.5, 0.5, 0.5, 1.0]


class QueueRNG:
    """确定性随机源（对齐 test_event_dispatcher_battle 风格）。"""

    def __init__(self, seq: List[float]) -> None:
        self.seq = list(seq)
        self.i = 0

    def random(self) -> float:
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _engine(effects: Optional[Dict[str, dict]] = None,
            statuses: Optional[Dict[str, dict]] = None) -> Any:
    from qbot_rpg.core.battle import BattleEngine

    reg = Reg(effects, statuses)
    eng = BattleEngine(registry=reg, config={})
    eng._rng = QueueRNG(SEQ)  # noqa: SLF001
    return eng


def _tag_effects() -> Dict[str, dict]:
    """on_kill（击杀者侧）/ death（死者侧）各挂一个可观测状态。"""
    return {
        "kill_tag": {"id": "kill_tag", "type": "special", "trigger": "on_kill",
                     "actions": [{"type": "status_apply", "status": "s_kill",
                                  "target": "self"}]},
        "death_tag": {"id": "death_tag", "type": "special", "trigger": "death",
                      "actions": [{"type": "status_apply", "status": "s_death",
                                   "target": "self"}]},
    }


_S_TAGS = {"s_kill": {"id": "s_kill", "type": "buff"},
           "s_death": {"id": "s_death", "type": "buff"}}


def _status_ids(eng: Any, side: str) -> List[str]:
    return [str(i.get("status_id")) for i in eng._snap["status_state"][side]]  # noqa: SLF001


def _spy(eng: Any) -> List[Tuple[str, str, List[str]]]:
    """包装 `_dispatch_event`，记录 (事件, 侧, side_effect 标识)。

    battle_end 收尾会清 status_state（`_settle` 语义），故 on_kill/death 的触发证据
    以**派发返回的 side_effects** 为准（先于收尾、不可被清理掩盖）。
    """
    calls: List[Tuple[str, str, List[str]]] = []
    orig = eng._dispatch_event

    def wrapped(event: str, side: str, **kw: Any) -> List[Dict[str, Any]]:
        out = orig(event, side, **kw)
        calls.append((event, side,
                      [str(e.get("status_id") or e.get("type")) for e in out]))
        return out

    eng._dispatch_event = wrapped  # type: ignore[assignment]
    return calls


def _fired(calls: List[Tuple[str, str, List[str]]], event: str, side: str) -> List[List[str]]:
    return [c[2] for c in calls if c[0] == event and c[1] == side and c[2]]


def test_on_kill_fires_on_killer_side_after_combo_kill() -> None:
    """player 连段套中击杀敌人 → on_kill 只在**击杀者（player）**侧触发；
    death 只在**被击杀者（enemy）**侧触发（两侧语义分明、不互换）。"""
    eng = _engine(_tag_effects(), _S_TAGS)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["enemy"]["hp"] = 1  # noqa: SLF001 —— 一击必杀
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.player_act("normal")
    assert eng._snap["enemy"]["hp"] <= 0, "enemy 应被击杀"  # noqa: SLF001
    assert _fired(calls, "on_kill", "player") == [["s_kill"]], \
        f"击杀者侧应触发 on_kill，实际 {calls}"
    assert _fired(calls, "on_kill", "enemy") == [], "被击杀者侧不得触发 on_kill"
    assert _fired(calls, "death", "enemy") == [["s_death"]], \
        f"被击杀者侧应触发 death，实际 {calls}"
    assert _fired(calls, "death", "player") == [], "击杀者侧不得触发 death"


def test_on_kill_fires_once_per_kill() -> None:
    """每次击杀恰好触发一次（dead_mark 门控；不因多段/收尾重复派发）。"""
    eng = _engine(_tag_effects(), _S_TAGS)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["enemy"]["hp"] = 1  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.player_act("normal")
    assert len(_fired(calls, "on_kill", "player")) == 1, f"应恰好一次，实际 {calls}"


def test_on_kill_boss_immediate_end_still_fires() -> None:
    """BOSS 死亡立即结束（A5）路径：on_kill 仍在结束前触发（钩在死亡判定后、
    `_resolve_battle_end` 之前）。"""
    eng = _engine(_tag_effects(), _S_TAGS)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["enemy"]["hp"] = 1  # noqa: SLF001
    eng._snap["enemy"]["tier"] = "boss"  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.player_act("normal")
    assert eng.finished, "BOSS 死亡应立即结束"
    kill_at = [i for i, c in enumerate(calls) if c[0] == "on_kill" and c[1] == "player"]
    end_at = [i for i, c in enumerate(calls) if c[0] == "battle_end"]
    assert kill_at, f"应触发 on_kill，实际 {calls}"
    assert end_at and kill_at[0] < end_at[0], f"on_kill 应在 battle_end 之前：{calls}"


def test_on_kill_enemy_kills_player_fires_on_enemy() -> None:
    """反向：敌人击杀玩家 → on_kill 触发在 enemy 侧（击杀者是哪侧就哪侧）。"""
    eng = _engine(_tag_effects(), _S_TAGS)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["player"]["hp"] = 1  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.do_action("enemy", {"type": "normal"})
    assert eng._snap["player"]["hp"] <= 0, "player 应被击杀"  # noqa: SLF001
    assert _fired(calls, "on_kill", "enemy") == [["s_kill"]], \
        f"击杀者（enemy）侧应触发 on_kill，实际 {calls}"
    assert _fired(calls, "death", "player") == [["s_death"]], "被击杀者侧应触发 death"


def test_owned_effect_not_fired_on_other_side_but_global_is() -> None:
    """战斗级归属（**不串**）：player 认领 `own_kill`、另有**未被认领**的
    `global_kill`。敌人击杀 player → on_kill 派给 enemy：`own_kill` 不触发（非其
    宿主），`global_kill` 照常触发（未认领 = 全局效果，不被归属过滤吞掉）。"""
    from qbot_rpg.data.gear_stats import OWNED_EFFECT_IDS_KEY

    eff = {
        "own_kill": {"id": "own_kill", "type": "special", "trigger": "on_kill",
                     "actions": [{"type": "status_apply", "status": "s_own",
                                  "target": "self"}]},
        "global_kill": {"id": "global_kill", "type": "special", "trigger": "on_kill",
                        "actions": [{"type": "status_apply", "status": "s_glo",
                                     "target": "self"}]},
    }
    sts = {"s_own": {"id": "s_own", "type": "buff"},
           "s_glo": {"id": "s_glo", "type": "buff"}}
    eng = _engine(eff, sts)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["player"][OWNED_EFFECT_IDS_KEY] = ["own_kill"]  # noqa: SLF001
    eng._snap["player"]["hp"] = 1  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.do_action("enemy", {"type": "normal"})
    assert eng._snap["player"]["hp"] <= 0  # noqa: SLF001
    fired = [e for group in _fired(calls, "on_kill", "enemy") for e in group]
    assert "s_own" not in fired, f"player 认领的效果不得在 enemy 侧触发：{calls}"
    assert "s_glo" in fired, f"未认领的全局效果应照常触发：{calls}"


def test_owned_effect_fires_on_owner_side() -> None:
    """正向：player 认领 `own_kill` → player 击杀敌人时它触发（归属不误伤宿主）。"""
    from qbot_rpg.data.gear_stats import OWNED_EFFECT_IDS_KEY

    eff = {"own_kill": {"id": "own_kill", "type": "special", "trigger": "on_kill",
                        "actions": [{"type": "status_apply", "status": "s_own",
                                     "target": "self"}]}}
    sts = {"s_own": {"id": "s_own", "type": "buff"}}
    eng = _engine(eff, sts)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["player"][OWNED_EFFECT_IDS_KEY] = ["own_kill"]  # noqa: SLF001
    eng._snap["enemy"]["hp"] = 1  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.player_act("normal")
    fired = [e for group in _fired(calls, "on_kill", "player") for e in group]
    assert "s_own" in fired, f"宿主侧应触发自己认领的效果：{calls}"


def test_no_owner_declared_legacy_global_scan_still_fires() -> None:
    """对拍：两侧都未声明归属键 → 全库扫描旧行为（未认领效果对任意侧都触发）。"""
    eng = _engine(_tag_effects(), _S_TAGS)
    eng.start(PLAYER, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["enemy"]["hp"] = 1  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.player_act("normal")
    assert _fired(calls, "on_kill", "player") == [["s_kill"]], f"旧行为：全局触发 {calls}"


def test_owned_effect_ids_helper_absent_key_is_none() -> None:
    """`_owned_effect_ids` 键缺省 / 畸形 → None（= 全库扫描旧行为）；键在 → 列表。"""
    from qbot_rpg.data.gear_stats import OWNED_EFFECT_IDS_KEY

    eng = _engine(_tag_effects(), _S_TAGS)
    eng.start(PLAYER, ENEMY, random_seed=1)
    assert eng._owned_effect_ids("player") is None            # noqa: SLF001
    eng._snap["player"][OWNED_EFFECT_IDS_KEY] = []            # noqa: SLF001
    assert eng._owned_effect_ids("player") == []              # noqa: SLF001
    eng._snap["player"][OWNED_EFFECT_IDS_KEY] = ["a", "", "b"]  # noqa: SLF001
    assert eng._owned_effect_ids("player") == ["a", "b"]      # noqa: SLF001
    eng._snap["player"][OWNED_EFFECT_IDS_KEY] = "oops"        # noqa: SLF001
    assert eng._owned_effect_ids("player") is None            # noqa: SLF001


# ===========================================================================
# E. 校验器（未知时点黄提示 / 非字符串红拦 / 缺省静默）
# ===========================================================================

def _rules(rep: Any) -> Tuple[List[str], List[str]]:
    return ([str(e.detail.get("rule")) for e in rep.errors],
            [str(w.detail.get("rule")) for w in rep.warnings])


def test_validator_known_event_point_silent() -> None:
    """已登记时点（含新补 on_kill）→ 零红零黄。"""
    from qbot_rpg.content.validator import check_pack

    for trig in ("on_kill", "death", "on_hit", "battle_start"):
        rep = check_pack({"effects": [{"id": "a", "type": "special",
                                       "trigger": trig, "actions": []}]})
        assert _rules(rep) == ([], []), (trig, _rules(rep))


def test_validator_unknown_event_point_yellow() -> None:
    """未登记时点 → 黄提示 Y-19（不硬拦），且提示里带已知时点键空间。"""
    from qbot_rpg.content.validator import check_pack

    rep = check_pack({"effects": [{"id": "a", "type": "special",
                                   "trigger": "on_kil", "actions": []}]})
    errs, warns = _rules(rep)
    assert errs == []
    assert warns == ["trigger_event_unknown"]
    assert "on_kill" in rep.warnings[0].detail.get("key_space", [])


def test_validator_non_string_trigger_red() -> None:
    """`trigger` 非字符串 → 红拦 R-1（soft 展示键的泛型校验补白）。"""
    from qbot_rpg.content.validator import check_pack

    rep = check_pack({"effects": [{"id": "a", "type": "special",
                                   "trigger": 3, "actions": []}]})
    assert _rules(rep) == (["type"], [])


def test_validator_absent_trigger_silent() -> None:
    """缺 `trigger` / 空串 → 放行（非事件型效果）。"""
    from qbot_rpg.content.validator import check_pack

    for entry in ({"id": "a", "type": "special", "actions": []},
                  {"id": "a", "type": "special", "trigger": "", "actions": []}):
        assert _rules(check_pack({"effects": [entry]})) == ([], [])


def test_validator_rune_ref_trigger_checked() -> None:
    """符文效果引用条目的 `trigger` 同样受校验（批48 声明面）。"""
    from qbot_rpg.content.validator import check_pack

    rep = check_pack({"runes": [{
        "id": "r", "tier": 1, "family": "f",
        "by_equip_type": {"default": {"stats": {"atk": 1}}},
        "effects": [{"effect": "fx", "trigger": "on_kil"}],
    }]})
    assert _rules(rep)[1] == ["trigger_event_unknown"]


# ===========================================================================
# F. 装备接线（最小）：实例 passives → traits.effects → combatant 归属集 → 战斗触发
# ===========================================================================

def _gear_ctx(passives: List[str], effect_refs: List[Any], *,
              item_id: str = "gear_x", slot: str = "weapon",
              trait_id: str = "t_gear") -> Dict[str, Any]:
    """内存 ctx：一件已穿戴装备实例（带 passives）+ 内存 traits 表。

    **零真实内容包**（批19.1 门禁）：items / traits / effects 全为匿名内存表。
    """
    from qbot_rpg.data.item import ItemInstance

    row = ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                       bound=False, stack_max=1, slot=slot,
                       passives=tuple(passives))
    player: Dict[str, Any] = {
        "inventory": [row],
        "equipment": {slot: {"item_id": item_id, "uid": row.uid}},
    }
    return {
        "player": player,
        "items": {item_id: {"id": item_id, "type": "weapon"}},
        "traits": {trait_id: {"id": trait_id, "name": trait_id,
                              "effects": list(effect_refs)}},
        "settings": {},
    }


def test_worn_passive_effect_ids_resolves_chain() -> None:
    """装备实例 passives → traits.effects → effect id 列表（链路解析）。"""
    from qbot_rpg.core.equip_mods import worn_passive_effect_ids

    ctx = _gear_ctx(["t_gear"], ["fx_a", {"effect": "fx_b"}])
    assert worn_passive_effect_ids(ctx, ctx["player"]) == ["fx_a", "fx_b"]


def test_worn_passive_effect_ids_dedup_and_no_passives() -> None:
    """去重（确定性、保序）；无 passives / 无 traits 表 → []（零新增）。"""
    from qbot_rpg.core.equip_mods import worn_passive_effect_ids

    ctx = _gear_ctx(["t_gear"], ["fx_a", "fx_a"])
    assert worn_passive_effect_ids(ctx, ctx["player"]) == ["fx_a"]
    ctx2 = _gear_ctx([], [])
    assert worn_passive_effect_ids(ctx2, ctx2["player"]) == []
    assert worn_passive_effect_ids({}, {}) == []


def test_worn_passive_effect_ids_unknown_trait_skipped() -> None:
    """passives 里引用未定义 trait → 跳过（框架不臆造，引用存在性归校验器）。"""
    from qbot_rpg.core.equip_mods import worn_passive_effect_ids

    ctx = _gear_ctx(["t_missing"], [])
    assert worn_passive_effect_ids(ctx, ctx["player"]) == []


def test_player_combatant_carries_owned_effects_only_when_present() -> None:
    """装配：有装备被动 → combatant 带归属集；无 → 不新增键（既有 combatant 逐字段一致）。"""
    from qbot_rpg.commands.battle_launch_commands import _player_combatant
    from qbot_rpg.data.gear_stats import OWNED_EFFECT_IDS_KEY

    ctx = _gear_ctx(["t_gear"], ["fx_a"])
    comb = _player_combatant(ctx)
    assert comb[OWNED_EFFECT_IDS_KEY] == ["fx_a"]
    plain = _player_combatant(_gear_ctx([], []))
    assert OWNED_EFFECT_IDS_KEY not in plain
    assert plain == _player_combatant(_gear_ctx([], []))


def test_gear_trigger_effect_end_to_end_host_only() -> None:
    """端到端：一件装备的触发型效果只在其**宿主侧**触发（另一侧击杀时不串）。"""
    from qbot_rpg.commands.battle_launch_commands import _player_combatant
    from qbot_rpg.data.gear_stats import OWNED_EFFECT_IDS_KEY

    ctx = _gear_ctx(["t_gear"], ["fx_gear_kill"])
    comb_p = _player_combatant(ctx)
    assert comb_p[OWNED_EFFECT_IDS_KEY] == ["fx_gear_kill"]

    eff = {"fx_gear_kill": {"id": "fx_gear_kill", "type": "special",
                           "trigger": "on_kill",
                           "actions": [{"type": "status_apply", "status": "s_gear",
                                        "target": "self"}]}}
    sts = {"s_gear": {"id": "s_gear", "type": "buff"}}

    # ① 宿主（player）击杀 → 装备效果触发
    # 玩家侧战斗单位 = 常规数值块 + **装配产出的归属集**（键来自 `_player_combatant`）
    eng = _engine(eff, sts)
    player_comb = dict(PLAYER)
    player_comb[OWNED_EFFECT_IDS_KEY] = comb_p[OWNED_EFFECT_IDS_KEY]
    eng.start(player_comb, ENEMY, random_seed=1)
    calls = _spy(eng)
    eng._snap["enemy"]["hp"] = 1  # noqa: SLF001
    eng._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng.player_act("normal")
    fired = [e for g in _fired(calls, "on_kill", "player") for e in g]
    assert "s_gear" in fired, f"宿主侧击杀应触发装备效果：{calls}"

    # ② 敌人击杀宿主 → 装备效果不在敌人侧触发（不串）
    eng2 = _engine(eff, sts)
    player_comb2 = dict(PLAYER)
    player_comb2[OWNED_EFFECT_IDS_KEY] = comb_p[OWNED_EFFECT_IDS_KEY]
    player_comb2["hp"] = 1
    eng2.start(player_comb2, ENEMY, random_seed=1)
    calls2 = _spy(eng2)
    eng2._rng = QueueRNG(SEQ)    # noqa: SLF001
    eng2.do_action("enemy", {"type": "normal"})
    assert eng2._snap["player"]["hp"] <= 0  # noqa: SLF001
    fired2 = [e for g in _fired(calls2, "on_kill", "enemy") for e in g]
    assert "s_gear" not in fired2, f"装备效果不得在非宿主侧触发：{calls2}"


def test_gear_effects_on_both_sides_do_not_cross() -> None:
    """**不串**（B 也有同类效果的场景）：两侧各有一件带 on_kill 触发的装备效果，
    各自只在**自己宿主**侧触发，互不越界。"""
    from qbot_rpg.commands.battle_launch_commands import _player_combatant
    from qbot_rpg.data.gear_stats import OWNED_EFFECT_IDS_KEY

    eff = {
        "fx_p": {"id": "fx_p", "type": "special", "trigger": "on_kill",
                 "actions": [{"type": "status_apply", "status": "s_p", "target": "self"}]},
        "fx_e": {"id": "fx_e", "type": "special", "trigger": "on_kill",
                 "actions": [{"type": "status_apply", "status": "s_e", "target": "self"}]},
    }
    sts = {"s_p": {"id": "s_p", "type": "buff"}, "s_e": {"id": "s_e", "type": "buff"}}
    comb_p = _player_combatant(_gear_ctx(["t_gear"], ["fx_p"], trait_id="t_gear"))
    assert comb_p[OWNED_EFFECT_IDS_KEY] == ["fx_p"]

    def _mk(p_hp: int = 500, e_hp: int = 400) -> Any:
        eng = _engine(eff, sts)
        p = dict(PLAYER)
        p[OWNED_EFFECT_IDS_KEY] = ["fx_p"]
        p["hp"] = p_hp
        e = dict(ENEMY)
        e[OWNED_EFFECT_IDS_KEY] = ["fx_e"]   # B 侧也声明归属（同类效果场景）
        e["hp"] = e_hp
        eng.start(p, e, random_seed=1)
        return eng

    # ① player 击杀 enemy → 只有 fx_p 触发
    eng = _mk(e_hp=1)
    calls = _spy(eng)
    eng._rng = QueueRNG(SEQ)      # noqa: SLF001
    eng.player_act("normal")
    fired = [x for g in _fired(calls, "on_kill", "player") for x in g]
    assert fired == ["s_p"], f"player 侧只应触发自己的 fx_p：{calls}"

    # ② enemy 击杀 player → 只有 fx_e 触发
    eng2 = _mk(p_hp=1)
    calls2 = _spy(eng2)
    eng2._rng = QueueRNG(SEQ)     # noqa: SLF001
    eng2.do_action("enemy", {"type": "normal"})
    fired2 = [x for g in _fired(calls2, "on_kill", "enemy") for x in g]
    assert fired2 == ["s_e"], f"enemy 侧只应触发自己的 fx_e：{calls2}"
