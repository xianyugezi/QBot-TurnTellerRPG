"""成就引擎单测（tests/unit/test_achievements.py · M11 批1 路1A）。

覆盖细化_4c 契约 TC-01~13 + TC-16（揭示字段），对齐 docs/m11_成就摸底.md §四 承载表。
"""

from typing import Any, MutableMapping

from qbot_rpg.core.achievements import (
    ACHIEVEMENT_STATE_KEY,
    ACHIEVEMENTS_KEY,
    achievement_view,
    check_achievements,
    get_achievement_state,
    list_achievements,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------
def _cfg(items: dict) -> dict:
    """成就配置表（{ID: raw dict} 形态，对齐引擎 _achievements_of 消费）。"""
    return {k: dict(v) for k, v in items.items()}


def _ctx(cfg: dict, **extra) -> dict:
    """引擎 ctx：achievements + achievement_state + 条件引擎消费键。"""
    ctx = {
        ACHIEVEMENTS_KEY: _cfg(cfg),
        ACHIEVEMENT_STATE_KEY: {"unlocked": {}, "repeat_count": {}},
        "today": "2026-09-01",
        "codex": 45.0,  # 总册完成度标量（条件引擎 var:codex 读）
        "level": 10,
        "inventory": {},
        "currencies": {"coins": 0},
        "settings": {"currencies": [{"id": "coins"}, {"id": "diamond"}]},
        "ledger": set(),
        "tx_id": None,
    }
    ctx.update(extra)
    return ctx


def _codex_cfg(pct: float = 45.0) -> dict:
    return {
        "ach_codex_25": {
            "id": "ach_codex_25", "name": "初窥门径",
            "conditions": [{"var": "codex", "op": "ge", "value": 25}],
        },
        "ach_codex_50": {
            "id": "ach_codex_50", "name": "图鉴过半",
            "conditions": [{"var": "codex", "op": "ge", "value": 50}],
        },
        "ach_codex_75": {
            "id": "ach_codex_75", "name": "资深收藏家",
            "conditions": [{"var": "codex", "op": "ge", "value": 75}],
        },
    }


# ---------------------------------------------------------------------------
# ① 解锁条件（TC-01~06）
# ---------------------------------------------------------------------------
def test_tc01_codex_global_ladder():
    """图鉴 45%→52% 跨档：50% 档达成、25% 不重授、75% 不触发（读 codex_state）。"""
    ctx = _ctx(_codex_cfg(45.0))
    r = check_achievements(ctx)
    # 45%：只达 25% 档
    assert any(g["id"] == "ach_codex_25" for g in r["granted"])
    assert not any(g["id"] == "ach_codex_50" for g in r["granted"])
    # 52%：50% 档达成；25% 已达成不重授（once=true）；75% 不触发
    ctx["codex"] = 52.0
    r2 = check_achievements(ctx)
    assert any(g["id"] == "ach_codex_50" for g in r2["granted"])
    assert not any(g["id"] == "ach_codex_25" for g in r2["granted"])
    assert not any(g["id"] == "ach_codex_75" for g in r2["granted"])


def test_tc02_codex_param_category():
    """codex param 分册：怪物册 100% → 仅怪物册成就达成；总册未满 → 收藏家不达成。"""
    cfg = {
        "ach_monster_100": {
            "id": "ach_monster_100", "name": "怪物博士",
            "conditions": [{"var": "codex", "op": "ge", "value": 100, "param": "monster"}],
        },
        "ach_total_100": {
            "id": "ach_total_100", "name": "收藏家",
            "conditions": [{"var": "codex", "op": "ge", "value": 100}],
        },
    }
    # 分册投影：monster=100（满），总册=60（未满）
    ctx = _ctx(cfg, codex=60.0, codex_categories={"monster": 100.0, "fish": 0.0,
                                                  "item": 0.0, "craft": 0.0})
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_monster_100" for g in r["granted"])
    assert not any(g["id"] == "ach_total_100" for g in r["granted"])


def test_tc03_event_count():
    """事件计数：{var:[事件:神鱼支线完成], ge 8}，第 7/8 条边界。"""
    cfg = {
        "ach_lantern": {
            "id": "ach_lantern", "name": "万家灯火",
            "conditions": [{"var": "[事件:神鱼支线完成]", "op": "ge", "value": 8}],
        },
    }
    ctx = _ctx(cfg, event_counts={"[事件:神鱼支线完成]": 7})
    r = check_achievements(ctx)
    assert not any(g["id"] == "ach_lantern" for g in r["granted"])
    ctx["event_counts"] = {"[事件:神鱼支线完成]": 8}
    r2 = check_achievements(ctx)
    assert any(g["id"] == "ach_lantern" for g in r2["granted"])


def test_tc04_gain_count_longline():
    """物品累计：gain_count param 铁矿 ≥100 历史累计（读 longline_counters 嵌套形态）。"""
    cfg = {
        "ach_iron": {
            "id": "ach_iron", "name": "铁矿收藏家",
            "conditions": [{"var": "gain_count", "op": "ge", "value": 100, "param": "铁矿"}],
        },
    }
    ctx = _ctx(cfg, longline_counters={"gain_count": {"铁矿": 99}})
    r = check_achievements(ctx)
    assert not any(g["id"] == "ach_iron" for g in r["granted"])
    ctx["longline_counters"] = {"gain_count": {"铁矿": 100}}
    r2 = check_achievements(ctx)
    assert any(g["id"] == "ach_iron" for g in r2["granted"])


def test_tc05_item_count_no_rollback():
    """当前背包：item_count 神鱼图 20/19；消耗后不回退（只增不减）。"""
    cfg = {
        "ach_map": {
            "id": "ach_map", "name": "神鱼图收藏",
            "conditions": [{"var": "item_count", "op": "ge", "value": 20, "param": "神鱼图"}],
        },
    }
    ctx = _ctx(cfg, inventory={"神鱼图": 19})
    r = check_achievements(ctx)
    assert not any(g["id"] == "ach_map" for g in r["granted"])
    ctx["inventory"] = {"神鱼图": 20}
    r2 = check_achievements(ctx)
    assert any(g["id"] == "ach_map" for g in r2["granted"])
    # 达成后消耗 → 已达成不回退
    ctx["inventory"] = {"神鱼图": 10}
    r3 = check_achievements(ctx)
    assert not any(g["id"] == "ach_map" for g in r3["granted"])  # once=true 不重发


def test_tc06_level():
    """等级：LV30/LV29。"""
    cfg = {
        "ach_lv30": {
            "id": "ach_lv30", "name": "三十而立",
            "conditions": [{"var": "level", "op": "ge", "value": 30}],
        },
    }
    ctx = _ctx(cfg, level=29)
    r = check_achievements(ctx)
    assert not any(g["id"] == "ach_lv30" for g in r["granted"])
    ctx["level"] = 30
    r2 = check_achievements(ctx)
    assert any(g["id"] == "ach_lv30" for g in r2["granted"])


# ---------------------------------------------------------------------------
# ② 奖励统一条目（TC-07~10）
# ---------------------------------------------------------------------------
def test_tc07_scalar_rewards():
    """exp/coins/gem 入账（复用 dispatch_reward）。"""
    cfg = {
        "ach_rich": {
            "id": "ach_rich", "name": "小富",
            "conditions": [{"var": "level", "op": "ge", "value": 5}],
            "reward": [{"exp": 500}, {"coins": 1000}, {"gem": 3}],
        },
    }
    ctx = _ctx(cfg, level=5, currencies={"coins": 0, "gem": 0}, exp=0,
               settings={"currencies": [{"id": "coins"}, {"id": "gem"}, {"id": "diamond"}]})
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_rich" for g in r["granted"])
    assert ctx["currencies"]["coins"] == 1000
    assert ctx["currencies"]["gem"] == 3
    assert ctx["exp"] == 500


def test_tc08_item_reward():
    """物品世界之书入包（add_item hook）。"""
    added = []

    def _add_item(iid: str, count: int, bound: bool = True) -> dict:
        added.append((iid, count, bound))
        return {"ok": True}

    cfg = {
        "ach_book": {
            "id": "ach_book", "name": "藏书家",
            "conditions": [{"var": "level", "op": "ge", "value": 5}],
            "reward": [{"item": "世界之书", "count": 1}],
        },
    }
    ctx = _ctx(cfg, level=5)
    ctx["add_item"] = _add_item
    ctx["items"] = {"世界之书": {"id": "世界之书", "type": "unique"}}
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_book" for g in r["granted"])
    assert ("世界之书", 1) in [(a[0], a[1]) for a in added]


def test_tc09_title_reward():
    """title t_collector → title_state.owned；t_fake 硬拦 skip（校验器侧双测）。"""
    cfg = {
        "ach_title": {
            "id": "ach_title", "name": "称号得主",
            "conditions": [{"var": "level", "op": "ge", "value": 5}],
            "reward": [{"title": "t_collector"}],
        },
    }
    # 注册表含 t_collector → 授予
    ctx = _ctx(cfg, level=5, titles={"t_collector": {"name": "收藏家"}},
               title_state={"owned": [], "equipped": None})
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_title" for g in r["granted"])
    assert "t_collector" in ctx["title_state"]["owned"]


def test_tc10_combined_ordered_skip_idempotent():
    """组合数组按序入账；item 不存在 → 黄字跳过，其余照常；重复结算点幂等。"""
    cfg = {
        "ach_combo": {
            "id": "ach_combo", "name": "组合",
            "conditions": [{"var": "level", "op": "ge", "value": 5}],
            "reward": [{"exp": 500}, {"coins": 1000},
                       {"item": "不存在之物", "count": 1}, {"title": "t_collector"}],
        },
    }
    ctx = _ctx(cfg, level=5, currencies={"coins": 0}, exp=0,
               titles={"t_collector": {"name": "收藏家"}},
               title_state={"owned": [], "equipped": None})
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_combo" for g in r["granted"])
    assert ctx["currencies"]["coins"] == 1000
    assert ctx["exp"] == 500
    # 重复结算点幂等（once=true 已达成不重发）
    r2 = check_achievements(ctx)
    assert not any(g["id"] == "ach_combo" for g in r2["granted"])
    assert ctx["currencies"]["coins"] == 1000


# ---------------------------------------------------------------------------
# ③ 状态持久化（TC-11~13）
# ---------------------------------------------------------------------------
def test_tc11_persist_across_daily_reset():
    """跨每日重置达成态留存。"""
    cfg = _codex_cfg(30.0)
    ctx = _ctx(cfg, codex=30.0)
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_codex_25" for g in r["granted"])
    state = get_achievement_state(ctx)
    assert "ach_codex_25" in state["unlocked"]
    # 模拟跨日：新 ctx 复用同一 achievement_state（持久化段）
    ctx2 = _ctx(cfg, codex=30.0)
    ctx2[ACHIEVEMENT_STATE_KEY] = state
    r2 = check_achievements(ctx2)
    assert not any(g["id"] == "ach_codex_25" for g in r2["granted"])  # 不重发
    assert "ach_codex_25" in get_achievement_state(ctx2)["unlocked"]


def test_tc12_once_idempotent_repeat():
    """once=true 幂等不重发；once=false 重复达成 repeat_count 递增。"""
    cfg_once = {
        "ach_once": {
            "id": "ach_once", "name": "一次性",
            "conditions": [{"var": "level", "op": "ge", "value": 5}],
        },
    }
    ctx = _ctx(cfg_once, level=5)
    check_achievements(ctx)
    check_achievements(ctx)
    st = get_achievement_state(ctx)
    assert st["unlocked"].get("ach_once")
    assert int(st["repeat_count"].get("ach_once", 0) or 0) == 0

    cfg_repeat = {
        "ach_rep": {
            "id": "ach_rep", "name": "可重复",
            "conditions": [{"var": "level", "op": "ge", "value": 5}],
            "once": False,
        },
    }
    ctx2 = _ctx(cfg_repeat, level=5)
    check_achievements(ctx2)
    check_achievements(ctx2)
    check_achievements(ctx2)
    st2 = get_achievement_state(ctx2)
    # 引擎语义：首次达成写 unlocked（repeat 0）；第二次 already → repeat=1；第三次 → 2
    assert st2["repeat_count"].get("ach_rep") == 2


def test_tc13_hot_reload_removed():
    """热重载删配置：列表降级提示「配置已移除」+ 存档保留（M11 A1 P2-1）。"""
    cfg = _codex_cfg(30.0)
    ctx = _ctx(cfg, codex=30.0)
    check_achievements(ctx)
    state = get_achievement_state(ctx)
    # 配置表变化（删掉 ach_codex_25）
    cfg2 = {k: v for k, v in cfg.items() if k != "ach_codex_25"}
    ctx[ACHIEVEMENTS_KEY] = _cfg(cfg2)
    entries = list_achievements(ctx)
    # 原条目不再以正常形态出现
    assert not any(e["id"] == "ach_codex_25" and not e.get("removed") for e in entries)
    # 降级提示行（removed=True，4c §4.3）
    removed = [e for e in entries if e.get("removed")]
    assert any(e["id"] == "ach_codex_25" for e in removed)
    assert "配置已移除" in str(removed[0].get("name"))
    assert "ach_codex_25" in state["unlocked"]  # 存档保留


# ---------------------------------------------------------------------------
# ④ 隐藏成就揭示（TC-16 揭示字段）
# ---------------------------------------------------------------------------
def test_tc16_hidden_reveal_once():
    """隐藏成就达成瞬间揭示卡片一次性；列表翻转已达成。"""
    cfg = {
        "ach_hidden": {
            "id": "ach_hidden", "name": "万家灯火",
            "conditions": [{"var": "[事件:神鱼支线完成]", "op": "ge", "value": 8}],
            "hidden": {"mode": "locked", "reveal_text": "灯火即神鱼——万家灯火，皆为神鱼之鳞。"},
        },
    }
    ctx = _ctx(cfg, event_counts={"[事件:神鱼支线完成]": 8})
    r = check_achievements(ctx)
    assert any(g["id"] == "ach_hidden" for g in r["granted"])
    assert any(rev["id"] == "ach_hidden" for rev in r["reveals"])
    # 列表翻转已达成（不再 ？？？）
    entries = list_achievements(ctx)
    e = next(x for x in entries if x["id"] == "ach_hidden")
    assert e["unlocked"] is True
    assert e["name"] == "万家灯火"
    assert e.get("reveal_text")
    # 再次触发不重发揭示
    r2 = check_achievements(ctx)
    assert not any(g["id"] == "ach_hidden" for g in r2["granted"])


def test_hidden_locked_unreached_name_placeholder():
    """隐藏成就未达成：列表 name=？？？不渲染明文。"""
    cfg = {
        "ach_hidden": {
            "id": "ach_hidden", "name": "万家灯火",
            "conditions": [{"var": "[事件:神鱼支线完成]", "op": "ge", "value": 8}],
            "hidden": {"mode": "locked", "reveal_text": "灯火即神鱼。"},
        },
    }
    ctx = _ctx(cfg, event_counts={"[事件:神鱼支线完成]": 0})
    entries = list_achievements(ctx)
    e = next(x for x in entries if x["id"] == "ach_hidden")
    assert e["name"] == "？？？"
    assert not e.get("reveal_text")  # 未达成不渲染揭示
    v = achievement_view(ctx, "ach_hidden")
    assert v is not None and v["name"] == "？？？"


def test_p0_1_mark_seen_triggers_check():
    """P0-1 回归守卫：mark_seen 图鉴点亮 → check_achievements 自动触发（D-07 结算点）。

    走真实接线链（codex.mark_seen 内调 check_achievements），断言条件满足即达成。
    """
    from qbot_rpg.core.codex import mark_seen as _codex_mark_seen

    cfg = {
        "ach_codex_25": {
            "id": "ach_codex_25", "name": "初窥门径",
            "conditions": [{"var": "codex", "op": "ge", "value": 25}],
        },
    }
    # 构造带 registry 的 ctx（monster 3 只，mark 1 只 → monster 33% → 全局 8.3% <25）
    class _Reg:
        def all_ids(self, kind: str) -> tuple:
            return ("a", "b", "c") if kind == "enemy" else ()

        def resolve(self, rid: str, kind: str):
            return None

    ctx: MutableMapping[str, Any] = {
        ACHIEVEMENTS_KEY: _cfg(cfg),
        ACHIEVEMENT_STATE_KEY: {"unlocked": {}, "repeat_count": {}},
        "registry": _Reg(),
        "codex_state": {},
        "today": "2026-09-01",
        "level": 10,
        "settings": {},
        "event_counts": {},
        "longline_counters": {},
    }
    # mark 全部 3 只怪 → monster 100% → 全局 25% → 成就达成（mark_seen 内自动 check）
    _codex_mark_seen(ctx, "monster", "a", "怪A")
    _codex_mark_seen(ctx, "monster", "b", "怪B")
    _codex_mark_seen(ctx, "monster", "c", "怪C")
    st = get_achievement_state(ctx)
    assert "ach_codex_25" in st["unlocked"]
