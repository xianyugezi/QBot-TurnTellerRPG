"""M3 批次5·路P：M22 副本子任务五形式判定 + M23 奖励与可选性 —— 单元测试。

依据：docs/规划/规划_路2a_地图副本.md 章5 M21-M23 + docs/m3_shared_contract.md §4.3
（副本子任务五形式 / 进副本自动激活不占板槽位 / 奖励与可选性——不完成可进 BOSS）。
被测入口：qbot_rpg.core.dungeon_subquest（纯逻辑，零 NoneBot；session/player_ctx 为内存 dict）。

覆盖：五形式各自推进与完成（reach_zone 走图 / defeat 击杀数 / collect 收集数 / interact /
condition）、进度查询、奖励发放与已领防重复、可选性（未完成不阻塞 BOSS 信号）。
"""

from __future__ import annotations

from qbot_rpg.core.dungeon_subquest import (
    SUBQUEST_KINDS,
    SUBQUEST_SESSION_KEY,
    ProgressTracker,
    eval_condition,
    normalize_subquest,
)


def _entry(**kw: object) -> dict:
    base: dict = {
        "id": "sq_reach",
        "kind": "reach_zone",
        "target": "map_a",
        "count": 1,
        "reward": {"items": [], "exp": 0, "gold": 0},
    }
    base.update(kw)
    return base


def _tracker(*entries: dict) -> ProgressTracker:
    return ProgressTracker({}, list(entries))


# ---------------------------------------------------------------------------
# 五形式枚举 + 条目结构（工程补白：quest.json 未定义时的承接结构）
# ---------------------------------------------------------------------------
def test_subquest_kinds_enum():
    assert SUBQUEST_KINDS == ("reach_zone", "defeat", "collect", "interact", "condition")


def test_normalize_structure():
    norm = normalize_subquest(_entry(
        id="sq1", kind="defeat", target="mob_a", count=3,
        reward={"items": [{"item": "i1", "count": 2}], "exp": 100, "gold": 50},
    ))
    assert norm is not None and norm["id"] == "sq1" and norm["kind"] == "defeat"
    assert norm["count"] == 3 and norm["target"] == "mob_a"
    assert norm["reward"]["items"] == [{"item": "i1", "count": 2}]
    assert norm["reward"]["exp"] == 100 and norm["reward"]["gold"] == 50


def test_normalize_defaults_and_invalid():
    dflt = normalize_subquest(_entry())
    assert dflt is not None and dflt["count"] == 1                       # count 缺省 1
    assert dflt["reward"] == {"items": [], "exp": 0, "gold": 0}          # reward 缺省空
    assert normalize_subquest({"id": "x", "kind": "bogus", "target": "t"}) is None   # 未知形式
    assert normalize_subquest({"kind": "defeat", "target": "t"}) is None            # 缺 id
    assert normalize_subquest(_entry(count=0)) is None                              # count 非正


# ---------------------------------------------------------------------------
# activate：进副本自动激活、不占板槽位、幂等
# ---------------------------------------------------------------------------
def test_activate_in_dungeon_progress_only():
    session: dict = {}
    t = ProgressTracker(session, [_entry(id="sq_a", kind="reach_zone", target="map_a", count=1)])
    assert t.activate("sq_a") is True
    assert t.activate("sq_a") is False          # 幂等：已激活不重复建
    assert set(session.keys()) == {SUBQUEST_SESSION_KEY}   # 不占板槽位：仅副本内进度键


# ---------------------------------------------------------------------------
# 五形式各自推进与完成
# ---------------------------------------------------------------------------
def test_reach_zone_advance_and_complete():
    t = _tracker(_entry(id="sq_r", kind="reach_zone", target="lava_core", count=1))
    assert t.record("reach_zone", "rubble_field") == []       # 未到达目标区 → 不推进
    msgs = t.record("reach_zone", "lava_core")                # 到达指定区域 → 完成
    assert any("sq_r" in m for m in msgs)
    assert t.is_complete("sq_r") is True
    assert t.progress("sq_r") == {"current": 1, "target": 1, "done": True}


def test_defeat_counting_and_clamp():
    t = _tracker(_entry(id="sq_d", kind="defeat", target="ember_drake", count=3))
    assert t.record("defeat", "ember_drake") == [] and t.record("defeat", "ember_drake") == []
    msgs = t.record("defeat", "ember_drake")                  # 第 3 只 → 完成
    assert any("sq_d" in m for m in msgs)
    assert t.is_complete("sq_d") is True
    assert t.record("defeat", "ember_drake") == []            # 已完成不再推进（钳制）
    assert t.record("defeat", "other_mob") == []              # 错误目标不推进


def test_collect_batch_clamp():
    t = _tracker(_entry(id="sq_c", kind="collect", target="ore_a", count=3))
    msgs = t.record("collect", "ore_a", count=5)              # 批量超额 → 钳制到上限
    assert any("sq_c" in m for m in msgs)
    assert t.progress("sq_c") == {"current": 3, "target": 3, "done": True}


def test_interact_complete():
    t = _tracker(_entry(id="sq_i", kind="interact", target="lever_b", count=1))
    assert t.record("interact", "trap_a") == []               # 非目标交互不推进
    msgs = t.record("interact", "lever_b")                    # 完成指定交互 → 完成
    assert any("sq_i" in m for m in msgs)
    assert t.is_complete("sq_i") is True


def test_eval_condition_primitives():
    state = {"codex_unlocked": 3, "season": "summer", "flag": True}
    assert eval_condition({"var": "codex_unlocked", "op": "gte", "value": 3}, state) is True
    assert eval_condition({"var": "codex_unlocked", "op": "eq", "value": 3}, state) is True
    assert eval_condition({"var": "codex_unlocked", "op": "lt", "value": 3}, state) is False
    assert eval_condition({"var": "season", "op": "==", "param": "summer"}, state) is True  # 契约形态


def test_eval_condition_failsafe():
    state = {"codex_unlocked": 3}
    assert eval_condition({"var": "codex_unlocked", "op": "like", "value": 1}, state) is False  # 未知 op
    assert eval_condition("not a cond", state) is False        # 非 dict → fail-safe False


def test_condition_kind_record():
    cond = {"var": "codex_unlocked", "op": "gte", "value": 1}
    t = _tracker(_entry(id="sq_cond", kind="condition", target=cond, count=1))
    assert any("sq_cond" in m for m in t.record("condition", cond))   # 条件满足 → 完成
    assert t.is_complete("sq_cond") is True
    assert t.record("condition", {"var": "codex_unlocked", "op": "gte", "value": 2}) == []  # 异条件
    assert t.progress("sq_cond") == {"current": 1, "target": 1, "done": True}


def test_condition_kind_counted():
    cond = {"var": "mech_trigger", "op": "eq", "value": 1}
    t = _tracker(_entry(id="sq_cond2", kind="condition", target=cond, count=3))
    assert t.record("condition", cond) == []                  # 第 1 次触发
    assert t.record("condition", cond) == []                  # 第 2 次触发
    msgs = t.record("condition", cond)                        # 第 3 次 → 完成
    assert any("sq_cond2" in m for m in msgs)
    assert t.progress("sq_cond2") == {"current": 3, "target": 3, "done": True}


# ---------------------------------------------------------------------------
# 进度查询 / is_complete
# ---------------------------------------------------------------------------
def test_progress_query_shapes():
    session: dict = {}
    t = ProgressTracker(session, [_entry(id="sq_a", kind="reach_zone", target="m1", count=1)])
    assert t.progress("sq_a") == {"current": 0, "target": 1, "done": False}   # 未激活 → 基线
    assert t.progress("ghost") == {"current": 0, "target": 0, "done": False}  # 未知 id
    t.record("reach_zone", "m1")
    assert t.progress("sq_a") == {"current": 1, "target": 1, "done": True}


# ---------------------------------------------------------------------------
# 奖励发放（M23）：形态 / 已领防重复 / 未完成拒发
# ---------------------------------------------------------------------------
def test_claim_reward_grants_and_dedupe():
    session: dict = {}
    t = ProgressTracker(session, [
        _entry(id="sq_r1", kind="reach_zone", target="map_a", count=1,
               reward={"items": [{"item": "i_x", "count": 2}], "exp": 100, "gold": 50}),
    ])
    assert t.claim_reward("sq_r1")["reason"] == "not_complete"      # 未完成 → 拒发
    t.record("reach_zone", "map_a")
    r = t.claim_reward("sq_r1")
    assert r["granted"] is True
    assert r["items"] == [{"item": "i_x", "count": 2}]
    assert r["exp"] == 100 and r["gold"] == 50
    r2 = t.claim_reward("sq_r1")                                     # 已领防重复
    assert r2["granted"] is False and r2["reason"] == "already_claimed"
    assert session[SUBQUEST_SESSION_KEY]["sq_r1"]["claimed"] is True  # 已领标记落会话
    assert t.claim_reward("ghost")["reason"] == "unknown_subquest"


def test_claim_reward_items_not_aliased():
    reward = {"items": [{"item": "gem", "count": 3}], "exp": 10, "gold": 10}
    t = _tracker(_entry(id="sq_cp", kind="collect", target="ore", count=1, reward=reward))
    t.record("collect", "ore")
    r = t.claim_reward("sq_cp")
    assert r["items"] == [{"item": "gem", "count": 3}]
    r["items"][0]["count"] = 999                                     # 篡改返回不影响原始配置
    assert reward["items"][0]["count"] == 3


# ---------------------------------------------------------------------------
# 可选性（M23 / 契约 §4.3）：未完成不阻塞 BOSS 信号
# ---------------------------------------------------------------------------
def test_optionality_incomplete_not_block_boss():
    t = _tracker(
        _entry(id="sq_opt_a", kind="collect", target="herb", count=3),
        _entry(id="sq_opt_b", kind="defeat", target="boss_mob", count=1),
    )
    t.record("collect", "herb")                                     # 只完成 1/3
    incomplete = [sid for sid in ("sq_opt_a", "sq_opt_b") if not t.is_complete(sid)]
    assert incomplete == ["sq_opt_a", "sq_opt_b"]                   # 两个子任务均未完成
    # 未完成子任务不抛错、不阻塞：其余子任务照常推进/完成，BOSS 侧状态可正常查询
    assert any("sq_opt_b" in m for m in t.record("defeat", "boss_mob"))
    assert t.is_complete("sq_opt_b") is True
    assert t.claim_reward("sq_opt_b")["granted"] is True            # 完成的子任务可领
    assert t.claim_reward("sq_opt_a")["reason"] == "not_complete"   # 未完成仅拒发，不抛错
    assert t.progress("sq_opt_a")["done"] is False                  # 关键信号：未完成仍可查询
