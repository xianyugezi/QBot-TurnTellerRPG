"""M3 批次5·路N：M17 副本共用 + M18 探索版流程（qbot_rpg/core/dungeon.py）单元测试。

依据：
  - m3_shared_contract §4.2（副本内状态集 S0–S7 + 迁移表 M1–M15）+ §4.1（dungeon.json 两型）+ §4.4（会话持久化）
  - 细化_2a3_副本两型流程 §2（状态集/迁移表/阶段细化）+ §3（子任务五形式）+ §4（死亡/离开重置）
  - 细化_2a1c_地图副本衔接 §2（入场校验 R4 / 外部锚点 R8 / 离开=重置 R7 / 集合隔离 R5）

fixtures：tests/fixtures/packs/legal/dungeon.json（explore=molten_dungeon_explore / boss=
molten_dungeon_boss 两型样例）+ maps.json（rubble_field/crag_den/lava_tunnel 三图）。

零 NoneBot、零 IO：player_ctx 由用例构造 dict 传入；maps/dungeons 注入内存 fixture。
覆盖：状态常量 / 会话形态与持久化 / enter 入场校验（探索宽松 + BOSS 拦截）/ transition
迁移表（探索版 S0→S1→S5→S7 + 死亡 S6）/ explore_run 全流程 / 集合隔离 / 隐藏门 / BOSS 版拒绝。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Mapping, cast

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.core.dungeon import (
    S0, S1, S2, S3, S4, S5, S6, S7,
    DungeonSession,
    DungeonStateMachine,
    explore_run,
)

LEGAL_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"


# -------------------------------------------------------------------------------------
# 夹具辅助
# -------------------------------------------------------------------------------------
def _load(name: str) -> list:
    data = json.loads((LEGAL_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _def(did: str) -> DungeonDef:
    for d in _load("dungeon"):
        if isinstance(d, Mapping) and d.get("id") == did:
            return cast(DungeonDef, DungeonDef.from_entry(d))
    raise AssertionError(f"legal/dungeon.json 缺少 {did}")


def _def_raw(did: str) -> dict:
    for d in _load("dungeon"):
        if isinstance(d, Mapping) and d.get("id") == did:
            return copy.deepcopy(d)  # type: ignore[arg-type]
    raise AssertionError(f"legal/dungeon.json 缺少 {did}")


def _maps() -> list:
    return _load("maps")


def _ctx(map_id: str = "mountain_foot", inventory: dict | None = None,
         entries: dict | None = None) -> dict:
    """最小玩家上下文（世界图节点 + 背包 count-map + 入场次数表）。"""
    inv = dict(inventory or {})
    return {
        "map_id": map_id,
        "player": {"map_id": map_id, "name": "阿伟", "inventory": dict(inv)},
        "inventory": inv,
        "dungeon_entries": dict(entries or {}),
        "content_pack_id": "legal",
        "content_pack_version": "1.0.0",
    }


def _sess(state: str = S1, dtype: str = "explore", current_map: str = "rubble_field",
          rest_count: int = 0) -> DungeonSession:
    return DungeonSession(dungeon_id="molten_dungeon_explore", dungeon_type=dtype,
                          state=state, current_map=current_map, rest_count=rest_count)


# -------------------------------------------------------------------------------------
# 状态常量（契约 §4.2）与会话形态（§4.4 持久化）
# -------------------------------------------------------------------------------------
def test_state_constants_contract():
    assert (S0, S1, S2, S3, S4, S5, S6, S7) == (
        "ENTRY", "PEACE_EXPLORE", "ELITE_ESCALATE", "BOSS_CHASE",
        "FINAL_DEATHMATCH", "CLEARED", "DEAD_RECOVER", "LEFT",
    )


def test_session_shape_and_persist_roundtrip():
    s = DungeonSession(
        dungeon_id="molten_dungeon_explore", dungeon_type="explore", state=S1,
        current_map="crag_den", cleared_maps=frozenset({"crag_den"}),
        subquest_progress={"quest_gather_ore": 2}, boss_state={"hp": 0.3},
        rest_count=1, external_anchor="mountain_foot",
        content_pack_id="legal", content_pack_version="1.0.0",
    )
    # 交付字段齐全（state/current_map/cleared_maps/subquest_progress/boss_state/rest_count/external_anchor）
    assert (s.state, s.current_map, s.rest_count, s.external_anchor) == (S1, "crag_den", 1, "mountain_foot")
    assert s.cleared_maps == frozenset({"crag_den"})
    assert s.subquest_progress == {"quest_gather_ore": 2}
    assert s.boss_state == {"hp": 0.3}
    # 持久化形态：set→list；from_dict 还原 frozenset
    d = s.to_dict()
    assert d["cleared_maps"] == ["crag_den"]
    assert d["state"] == S1 and d["content_pack_id"] == "legal"
    s2 = DungeonSession.from_dict(d)
    assert s2.cleared_maps == frozenset({"crag_den"})
    assert s2.subquest_progress == {"quest_gather_ore": 2}
    # frozen：with_* 返回新实例，原实例不变
    s3 = s.with_state(S5)
    assert s3.state == S5 and s.state == S1
    assert s3.with_cleared("lava_tunnel").cleared_maps == frozenset({"crag_den", "lava_tunnel"})


# -------------------------------------------------------------------------------------
# enter：入场校验（探索版宽松 / BOSS 版拦截）
# -------------------------------------------------------------------------------------
def test_enter_explore_lenient_no_cost():
    ctx = _ctx()
    r = DungeonStateMachine().enter(ctx, _def("molten_dungeon_explore"))
    assert r["ok"] is True
    assert (r["state"], r["session"].current_map, r["session"].external_anchor) == (S0, "rubble_field", "mountain_foot")
    assert ctx["map_id"] == "rubble_field"            # 落位 safe_zone
    assert ctx["inventory"] == {}                      # 探索版 entry_item null 不扣
    assert ctx["dungeon_entries"]["molten_dungeon_explore"] == 1  # entry_limit 0=不限（计数恒登记）


def test_enter_boss_consumes_item_and_counts():
    ctx = _ctx(inventory={"potion": 2})
    r = DungeonStateMachine().enter(ctx, _def("molten_dungeon_boss"))
    assert r["ok"] is True
    assert r["entry_item_consumed"] == "potion"
    assert ctx["inventory"]["potion"] == 1                        # 扣 1 把
    assert ctx["dungeon_entries"]["molten_dungeon_boss"] == 1     # 入场次数 +1
    assert r["session"].dungeon_type == "boss"
    assert (r["session"].boss_state, r["session"].cleared_maps) == ({}, frozenset())


def test_enter_boss_missing_item_blocked():
    ctx = _ctx(inventory={})   # 无 potion
    r = DungeonStateMachine().enter(ctx, _def("molten_dungeon_boss"))
    assert r["ok"] is False and "potion" in r["reason"]
    assert ctx["inventory"] == {}                     # 不扣道具
    assert ctx["dungeon_entries"] == {}               # 不消耗次数
    assert ctx["map_id"] == "mountain_foot"           # 未落位


def test_enter_boss_limit_exceeded_blocked_no_item_loss():
    ctx = _ctx(inventory={"potion": 2}, entries={"molten_dungeon_boss": 3})
    r = DungeonStateMachine().enter(ctx, _def("molten_dungeon_boss"))
    assert r["ok"] is False and "上限" in r["reason"]
    assert ctx["inventory"]["potion"] == 2            # 校验先于消耗：不扣钥匙
    assert ctx["dungeon_entries"]["molten_dungeon_boss"] == 3   # 不消耗次数


def test_enter_boss_limit_ok_at_boundary():
    ctx = _ctx(inventory={"potion": 1}, entries={"molten_dungeon_boss": 2})
    r = DungeonStateMachine().enter(ctx, _def("molten_dungeon_boss"))
    assert r["ok"] is True and ctx["dungeon_entries"]["molten_dungeon_boss"] == 3
    assert ctx["inventory"]["potion"] == 0


def test_enter_defaults_and_lenient_variants():
    # safe_zone 缺省 = maps[0]（工程补白 7）
    raw = _def_raw("molten_dungeon_explore")
    raw.pop("safe_zone", None)
    r = DungeonStateMachine().enter(_ctx(), DungeonDef.from_entry(raw))
    assert r["session"].current_map == "rubble_field"
    # entry_limit 0=不限：已有计数也不拦
    ctx = _ctx(entries={"molten_dungeon_explore": 99})
    assert DungeonStateMachine().enter(ctx, _def("molten_dungeon_explore"))["ok"] is True
    # boss 版 entry_item null → 宽松（同探索版语义，契约 §4.1）
    rb = _def_raw("molten_dungeon_boss")
    rb["entry_item"] = None
    ctx2 = _ctx(inventory={"potion": 3})
    r2 = DungeonStateMachine().enter(ctx2, DungeonDef.from_entry(rb))
    assert r2["ok"] is True and ctx2["inventory"]["potion"] == 3


# -------------------------------------------------------------------------------------
# transition：迁移表（探索版路径 S0→S1→S5→S7 + 死亡 S6；M1–M15）
# -------------------------------------------------------------------------------------
def test_m2_walk_entry_to_explore_and_stay():
    m = DungeonStateMachine()
    r = m.transition("walk", _sess(S0))
    assert r["ok"] is True and r["state"] == S1          # M2：S0→S1
    assert m.transition("walk", _sess(S1))["state"] == S1  # S1 内继续走图（补白）


def test_m3_m4_elite_escalate_and_done():
    m = DungeonStateMachine()
    r = m.transition("elite", _sess(S1))
    assert r["ok"] is True and r["state"] == S2          # M3：S1→S2
    r2 = m.transition("elite_done", r["session"])
    assert r2["ok"] is True and r2["state"] == S1        # M4：S2→S1


def test_explore_clear_s1_to_s5():
    r = DungeonStateMachine().transition("clear", _sess(S1))   # 探索版通关（补白 2）
    assert r["ok"] is True and r["state"] == S5
    assert DungeonStateMachine().transition("clear", _sess(S1, dtype="boss"))["ok"] is False


def test_leave_m12_m13_m14_and_s0():
    m = DungeonStateMachine()
    assert m.transition("leave", _sess(S1))["state"] == S7    # M12：S1→S7
    assert m.transition("leave", _sess(S5))["state"] == S7    # M13：通关离开
    assert m.transition("leave", _sess(S6))["state"] == S7    # M14：死亡后离开
    assert m.transition("leave", _sess(S0))["state"] == S7    # S0 离开（工程补白：2a1c TC-16）


def test_leave_resets_session_progress():
    s = _sess(S5, current_map="lava_tunnel", rest_count=2).with_cleared("crag_den")
    r = DungeonStateMachine().transition("leave", s)
    sess = r["session"]
    assert r["ok"] is True and sess.state == S7
    assert (sess.cleared_maps, sess.rest_count, sess.current_map) == (frozenset(), 0, None)


def test_death_and_recover():
    m = DungeonStateMachine()
    r = m.transition("death", _sess(S1))                   # 探索版死亡（补白 3）
    assert r["ok"] is True and r["state"] == S6
    assert m.transition("death", _sess(S2))["state"] == S6  # S2 精英死亡
    r2 = m.transition("recover", r["session"])             # M11：虚弱结束
    assert r2["ok"] is True and r2["state"] == S1


def test_boss_events_blocked_on_explore():
    m = DungeonStateMachine()
    blocked = all(
        not m.transition(ev, _sess(S1))["ok"] for ev in ("chase", "caught", "re_chase", "kill")
    )   # 探索版无 BOSS（2a3 R9）；BOSS 追击/决战路径批次5·路O 接线
    assert blocked


def test_walk_and_leave_blocked_states():
    m = DungeonStateMachine()
    assert all(not m.transition("walk", _sess(st))["ok"] for st in (S2, S5, S6, S7))
    assert m.transition("leave", _sess(S2))["ok"] is False      # S2 需先 elite_done（M4）脱离
    assert m.transition("fly", _sess(S1))["ok"] is False        # 未知事件


def test_rest_m15_and_state_query():
    m = DungeonStateMachine()
    r = m.transition("rest", _sess(S0))                        # M15：原地休息≠离开
    assert r["ok"] is True and r["state"] == S0 and r["session"].rest_count == 1
    assert m.state(_sess(S0)) == S0 and m.state(None) is None


# -------------------------------------------------------------------------------------
# explore_run：探索版全流程（M18）
# -------------------------------------------------------------------------------------
def test_explore_run_full_flow():
    ctx = _ctx()
    r = explore_run(ctx, _def("molten_dungeon_explore"), _maps(), actions=[
        ("walk", "上"),                    # rubble_field → crag_den
        ("subquest", "quest_gather_ore", 2),
        ("walk", "左"),                    # crag_den → lava_tunnel
        ("clear",),                        # 探索目标完成 → S5
        ("leave",),                        # 离开 → S7 重置
    ])
    assert r["ok"] is True
    steps = r["steps"]
    assert [s["event"] for s in steps] == ["enter", "walk", "subquest", "walk", "clear", "leave"]
    assert steps[1]["state"] == S1 and steps[1]["to"] == "crag_den"
    assert steps[2]["progress"] == 2
    assert steps[3]["to"] == "lava_tunnel"
    assert steps[4]["state"] == S5
    assert r["cleared"] is not None and r["cleared"]["state"] == "cleared"
    assert "批次 7" in r["cleared"]["reward_hint"]           # 掉落结算批次 7 接线
    assert steps[5]["state"] == S7 and r["left"] is True
    assert ctx["map_id"] == "mountain_foot"                   # R8：回外部锚点
    assert r["session"].state == S7
    assert r["session"].cleared_maps == frozenset()           # 离开=重置


def test_explore_run_cleared_maps_tracked():
    r = explore_run(_ctx(), _def("molten_dungeon_explore"), _maps(),
                    actions=[("walk", "上"), ("walk", "下"), ("clear",)])
    # crag_den 下 → rubble_field；两图均登记已清/已到访
    assert r["session"].cleared_maps == frozenset({"crag_den", "rubble_field"})
    assert r["session"].current_map == "rubble_field" and r["session"].state == S5


def test_explore_run_walk_blocked_cases():
    # 无通道方向（rubble_field 左为空）→ 不移动
    ctx = _ctx()
    r = explore_run(ctx, _def("molten_dungeon_explore"), _maps(), actions=[("walk", "左")])
    assert r["steps"][1]["ok"] is False and "没有通道" in r["steps"][1]["reason"]
    assert ctx["map_id"] == "rubble_field"
    # hidden 门无条件注入 → 拦截「此处无通道」（rubble_field 右 → lava_tunnel hidden）
    ctx2 = _ctx()
    r2 = explore_run(ctx2, _def("molten_dungeon_explore"), _maps(), actions=[("walk", "右")])
    assert r2["steps"][1]["ok"] is False and "通道" in r2["steps"][1]["reason"]
    # hidden 条件满足 → 可走捷径（M05 隐藏门衔接）
    ctx3 = _ctx()
    cond = lambda c, ctx: c.get("param") == "learn_mechanic"   # noqa: E731
    r3 = explore_run(ctx3, _def("molten_dungeon_explore"), _maps(),
                     actions=[("walk", "右")], conditions=cond)
    assert r3["steps"][1]["ok"] is True and r3["steps"][1]["to"] == "lava_tunnel"


def test_explore_run_walk_outside_dungeon_maps_blocked():
    # 集合隔离 R5：副本只含 rubble_field，上通 crag_den 在集合外 → 拦截
    raw = _def_raw("molten_dungeon_explore")
    raw["maps"] = ["rubble_field"]
    raw["safe_zone"] = "rubble_field"
    ctx = _ctx()
    r = explore_run(ctx, DungeonDef.from_entry(raw), _maps(), actions=[("walk", "上")])
    assert r["steps"][1]["ok"] is False and "集合" in r["steps"][1]["reason"]
    assert ctx["map_id"] == "rubble_field"


def test_explore_run_death_recover_flow():
    r = explore_run(_ctx(), _def("molten_dungeon_explore"), _maps(), actions=[
        ("walk", "上"), ("death",), ("recover",), ("walk", "下"), ("clear",), ("leave",),
    ])
    assert r["steps"][1]["state"] == S1
    assert r["steps"][2]["state"] == S6
    assert r["steps"][2]["session"].current_map == "rubble_field"   # 复活点=入口=safe_zone
    assert r["steps"][3]["state"] == S1
    assert r["steps"][4]["to"] == "lava_tunnel" and r["steps"][5]["state"] == S5
    assert r["steps"][6]["state"] == S7 and r["state"] == S7


def test_explore_run_rest_gate_and_after_leave():
    ctx = _ctx()
    r = explore_run(ctx, _def("molten_dungeon_explore"), _maps(),
                    actions=[("rest",), ("walk", "上"), ("rest",)])
    assert r["steps"][1]["ok"] is True and r["steps"][1]["rest_count"] == 1  # S0 入口=安全区
    assert r["steps"][3]["ok"] is False                                     # crag_den 非安全区拒绝
    assert r["session"].rest_count == 1
    # 离开后动作全被拒（S7 离开态）
    r2 = explore_run(_ctx(), _def("molten_dungeon_explore"), _maps(),
                     actions=[("leave",), ("walk", "上")])
    assert r2["steps"][1]["ok"] is True and r2["steps"][2]["ok"] is False


def test_explore_run_rejects_boss_dungeon():
    r = explore_run(_ctx(), _def("molten_dungeon_boss"), _maps(), actions=[])
    assert r["ok"] is False and "路O" in r["reason"]


def test_explore_run_enter_blocked_propagates():
    # 探索版入口配 entry_item（统一校验口径）：缺道具 → 拦截并传播
    raw = _def_raw("molten_dungeon_explore")
    raw["entry_item"] = "potion"
    r = explore_run(_ctx(inventory={}), DungeonDef.from_entry(raw), _maps(), actions=[])
    assert r["ok"] is False and "potion" in r["reason"]


def test_machine_constructor_form_and_mover_injection():
    # 上下文形态：DungeonStateMachine(dungeon_def, ctx).enter(player_ctx)
    m = DungeonStateMachine(_def("molten_dungeon_explore"), {"k": 1})
    assert m.enter(_ctx())["ok"] is True
    # mover 注入：走通道可由调用方接管（纯逻辑测试/路 O 复用）
    calls: list = []

    def fake_mover(ctx: dict, direction: str) -> dict:
        calls.append(direction)
        return {"ok": True, "to": "crag_den", "name": "石甲蜥巢穴"}

    ctx = _ctx()
    r = explore_run(ctx, _def("molten_dungeon_explore"), _maps(),
                    actions=[("walk", "上")], mover=fake_mover)
    assert r["steps"][1]["ok"] is True and r["steps"][1]["to"] == "crag_den"
    assert calls == ["上"]
