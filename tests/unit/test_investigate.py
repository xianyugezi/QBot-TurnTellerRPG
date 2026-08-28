"""调查引擎测试（tests/unit/test_investigate.py · M7 BCH-06 3f F-05/F-06 · R-07~R-11 · E-02）。

覆盖：交互点彩蛋（R-08：命中/条件不满足/求值失败/无条件/去重/非 one_shot）/ 时段蹲点
（R-09：窗口命中信号/窗口外/坏条件）/ 隐藏地图揭示（R-07 延伸：map_reveal 配置与
hidden exit 两源/一次性/条件不满足）/ 优先级（R-11 D-04：hunt > map_reveal > egg）/
daily 配额（可配/泛化不计/今日键）/ 去重确认（R-11）/ 不提示原则（R-07 TC-09：
泛化文本零「此处有隐藏」措辞）/ 发现即计数 + 首见日志（R-14/R-15）/ 确定性。
"""

from __future__ import annotations

import random

from qbot_rpg.content.map_models import MapDef
from qbot_rpg.core.adventure_log import EVENT_KEY_HIDDEN_FIND
from qbot_rpg.core.event_bus import EVENT_LOG_KEY
from qbot_rpg.core.investigate import (
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_DAILY_QUOTA,
    QUOTA_KEY,
    REVEALED_KEY,
    investigate_map,
)

# 不提示原则违禁措辞（R-07/TC-09：泛化文本不得出现）
_FORBIDDEN = ("隐藏", "这里有什么", "再调查", "此处")


def _mk_ctx(**over: object) -> dict:
    """确定性 ctx：三表 + persistent_state + settings + 环境快照 + today + rng。"""
    ctx: dict = {
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {},
        "settings": {},
        "season": "秋",
        "period": "午夜",
        "weather": "雷雨",
        "today": "2026-08-28",
        "rng": random.Random(42),
    }
    ctx.update(over)
    return ctx


def _mk_map(**entry: object) -> MapDef:
    """MapDef 构造（raw 全量镜像，interact_points 经 raw 兜底读取）。"""
    entry.setdefault("id", "misty_marsh")
    entry.setdefault("name", "雾沼")
    entry.setdefault("desc", "雾沼的泥泞小道，水汽弥漫。")
    raw = dict(entry)
    return MapDef(id=str(entry["id"]), name=str(entry["name"]), raw=raw)


def _egg_point(**over: object) -> dict:
    """E-02 交互点默认条目（雾沼石像）。"""
    p: dict = {
        "id": "statue",
        "alias": ["石像", "雾沼石像"],
        "map_id": "misty_marsh",
        "desc": "石像上刻着古老的纹路，仿佛在讲述久远的故事。",
        "lore_condition": {"var": "codex", "op": "ge", "value": 60},
        "hidden_find_id": "egg_statue",
        "one_shot": True,
    }
    p.update(over)
    return p


def _window_row(**over: object) -> dict:
    """隐藏 BOSS 窗口行（R-12 数据源，补白 2：monsters[] + window 条件键）。"""
    row: dict = {
        "enemy": "wolf_luna",
        "window": {
            "all": [
                {"var": "season", "op": "eq", "param": "秋"},
                {"var": "period", "op": "eq", "param": "午夜"},
                {"var": "weather", "op": "eq", "param": "雷雨"},
            ]
        },
        "desc": "你听到远处传来低沉的狼嗥，与平时的风雨声不同。",
    }
    row.update(over)
    return row


def _log_of(ctx: dict) -> list:
    """event_log 读取（persistent_state 落点）。"""
    return ctx["persistent_state"][EVENT_LOG_KEY]


def _hidden_count(ctx: dict) -> int:
    """[事件:隐藏发现] 嵌套计数汇总。"""
    sub = ctx["event_counts"].get(EVENT_KEY_HIDDEN_FIND, {})
    return sum(int(v) for v in sub.values()) if isinstance(sub, dict) else 0


# ---------------------------------------------------------------------------
# R-08 交互点彩蛋
# ---------------------------------------------------------------------------
def test_egg_hit_satisfied_writes_hidden_find() -> None:
    """图鉴>=60% 时 /调查 石像 → 彩蛋正文 + [事件:隐藏发现:ID] 计数 + 首见日志。"""
    ctx = _mk_ctx(codex=80)
    m = _mk_map(interact_points=[_egg_point()])
    r = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r["kind"] == "egg"
    assert "古老的纹路" in r["text"]
    assert r["hidden_find_id"] == "egg_statue"
    assert r["one_shot"] is True
    assert r["first_seen"] is True
    assert r["quota_remaining"] == DEFAULT_DAILY_QUOTA - 1
    assert ctx["event_counts"][EVENT_KEY_HIDDEN_FIND] == {"egg_statue": 1}
    assert ctx["longline_counters"][EVENT_KEY_HIDDEN_FIND] == 1
    e = _log_of(ctx)[0]
    assert e["tag"] == "hidden_find"
    assert e["first_seen"] is True
    assert e["snapshot"] == {"season": "秋", "period": "午夜", "weather": "雷雨"}
    assert ctx["persistent_state"][REVEALED_KEY] == ["egg:statue"]
    assert ctx["persistent_state"][QUOTA_KEY] == {"2026-08-28": 1}


def test_egg_condition_not_satisfied_generic_zero_hint() -> None:
    """图鉴 20% 时同指令 → 泛化文本零暗示，不写事件不计配额。"""
    ctx = _mk_ctx(codex=20)
    m = _mk_map(interact_points=[_egg_point()])
    r = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r["kind"] == "generic"
    assert not any(w in r["text"] for w in _FORBIDDEN)
    assert _hidden_count(ctx) == 0
    assert ctx["persistent_state"].get(QUOTA_KEY) is None


def test_egg_condition_eval_failure_generic() -> None:
    """lore_condition 求值失败（未注册 var）→ 不满足 → 泛化文本（R-08/D-03）。"""
    ctx = _mk_ctx()
    p = _egg_point(lore_condition={"var": "nonexistent_xyz", "op": "eq", "param": "x"})
    m = _mk_map(interact_points=[p])
    r = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r["kind"] == "generic"
    assert not any(w in r["text"] for w in _FORBIDDEN)
    assert _hidden_count(ctx) == 0


def test_egg_without_lore_condition_always_hit() -> None:
    """lore_condition=null → 无条件恒可触发（E-02）。"""
    ctx = _mk_ctx()
    p = _egg_point(lore_condition=None)
    m = _mk_map(interact_points=[p])
    r = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r["kind"] == "egg"
    assert r["hidden_find_id"] == "egg_statue"


def test_egg_match_by_id_and_alias() -> None:
    """目标匹配：交互点 id 或 alias 均可命中（E-02 alias 数组）。"""
    ctx = _mk_ctx(codex=80)
    m = _mk_map(interact_points=[_egg_point()])
    r_id = investigate_map(ctx, m, "statue", today="2026-08-28")
    assert r_id["kind"] == "egg"
    r_alias = investigate_map(dict(ctx, persistent_state={}), m, "雾沼石像", today="2026-08-28")
    assert r_alias["kind"] == "egg"


def test_egg_one_shot_repeat_confirm_no_card() -> None:
    """两次满足条件发现同一彩蛋：首次卡片+首见；二次仅简短确认，无卡片无计数。"""
    ctx = _mk_ctx(codex=80)
    m = _mk_map(interact_points=[_egg_point()])
    r1 = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r1["kind"] == "egg"
    r2 = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r2["kind"] == "egg_confirm"
    assert r2["text"] == DEFAULT_CONFIRM_TEXT
    assert r2["quota_remaining"] == DEFAULT_DAILY_QUOTA - 1  # 确认不计配额
    assert _hidden_count(ctx) == 1
    assert len(_log_of(ctx)) == 1


def test_egg_not_one_shot_repeats_card() -> None:
    """one_shot=false → 重复命中仍出彩蛋正文，计数递增，二次首见=false。"""
    ctx = _mk_ctx(codex=80)
    m = _mk_map(interact_points=[_egg_point(one_shot=False)])
    r1 = investigate_map(ctx, m, "石像", today="2026-08-28")
    r2 = investigate_map(ctx, m, "石像", today="2026-08-28")
    assert r1["kind"] == "egg" and r1["first_seen"] is True
    assert r2["kind"] == "egg" and r2["first_seen"] is False
    assert _hidden_count(ctx) == 2
    assert ctx["persistent_state"][QUOTA_KEY] == {"2026-08-28": 2}


def test_no_target_map_level_egg() -> None:
    """无目标参数 → 当前地图整体调查：命中地图级彩蛋（R-07）。"""
    ctx = _mk_ctx(codex=80)
    m = _mk_map(interact_points=[_egg_point()])
    r = investigate_map(ctx, m, None, today="2026-08-28")
    assert r["kind"] == "egg"


# ---------------------------------------------------------------------------
# R-07 TC-09 不提示原则
# ---------------------------------------------------------------------------
def test_no_interact_points_generic_no_hint() -> None:
    """/调查 无交互点地图 → 泛化环境文本，无「此处有隐藏」类措辞。"""
    ctx = _mk_ctx()
    m = _mk_map(desc="一条寂静的小径，通往密林深处。", interact_points=[])
    r = investigate_map(ctx, m, None, today="2026-08-28")
    assert r["kind"] == "generic"
    assert r["text"] == "一条寂静的小径，通往密林深处。"
    assert not any(w in r["text"] for w in _FORBIDDEN)


def test_target_unmatched_generic() -> None:
    """目标既非交互点也非本图 → 泛化文本零暗示。"""
    ctx = _mk_ctx()
    m = _mk_map(interact_points=[_egg_point()])
    r = investigate_map(ctx, m, "不存在的目标", today="2026-08-28")
    assert r["kind"] == "generic"
    assert not any(w in r["text"] for w in _FORBIDDEN)


# ---------------------------------------------------------------------------
# R-09 特定时段蹲点
# ---------------------------------------------------------------------------
def test_hunt_window_satisfied_signal() -> None:
    """秋·午夜·雷雨 /调查 雾沼 → hunt 信号 + boss_ref（BOSS 战归 BCH-07）。"""
    ctx = _mk_ctx()
    m = _mk_map(monsters=[_window_row()], interact_points=[_egg_point()])
    r = investigate_map(ctx, m, "雾沼", today="2026-08-28")
    assert r["kind"] == "hunt"
    assert r["boss_ref"] == "wolf_luna"
    assert "狼嗥" in r["text"]
    assert r["quota_remaining"] == DEFAULT_DAILY_QUOTA - 1
    # 优先级：hunt 优先于 egg，彩蛋不触发
    assert _hidden_count(ctx) == 0


def test_hunt_window_outside_generic_or_egg() -> None:
    """窗口外（春·白昼·晴）→ 无蹲点信号，回落到彩蛋/泛化（零暗示）。"""
    ctx = _mk_ctx(season="春", period="白昼", weather="晴")
    m = _mk_map(monsters=[_window_row()], interact_points=[_egg_point(lore_condition=None)])
    r = investigate_map(ctx, m, "雾沼", today="2026-08-28")
    assert r["kind"] == "egg"  # hunt 不命中 → 降级到彩蛋
    assert ctx["event_counts"][EVENT_KEY_HIDDEN_FIND] == {"egg_statue": 1}


def test_hunt_bad_window_condition_generic() -> None:
    """window 引用未注册条件键 → 求值失败不满足 → 泛化文本零暗示。"""
    ctx = _mk_ctx()
    m = _mk_map(monsters=[_window_row(window={"var": "ghost_var", "op": "ge", "value": 1})])
    r = investigate_map(ctx, m, "雾沼", today="2026-08-28")
    assert r["kind"] == "generic"
    assert not any(w in r["text"] for w in _FORBIDDEN)


# ---------------------------------------------------------------------------
# R-07 延伸 隐藏地图揭示
# ---------------------------------------------------------------------------
def test_map_reveal_config_satisfied_one_shot() -> None:
    """/调查 当前地图，地图级 lore condition 满足 → 一次性揭示隐藏地图入口。"""
    ctx = _mk_ctx(codex=80)
    reveal = {"map_id": "hidden_cave", "desc": "雾汽散开，露出一条通往隐秘洞窟的裂隙。",
              "lore_condition": {"var": "codex", "op": "ge", "value": 60}}
    m = _mk_map(hidden_reveal=reveal, interact_points=[_egg_point()])
    r1 = investigate_map(ctx, m, None, today="2026-08-28")
    assert r1["kind"] == "map_reveal"
    assert r1["map_ref"] == "hidden_cave"
    assert "裂隙" in r1["text"]
    assert ctx["persistent_state"][REVEALED_KEY] == ["map_reveal:hidden_cave"]
    # 二次：仅简短确认（R-11 去重）
    r2 = investigate_map(ctx, m, None, today="2026-08-28")
    assert r2["kind"] == "map_reveal_confirm"
    assert r2["text"] == DEFAULT_CONFIRM_TEXT
    # 优先级：map_reveal 优先于 egg，彩蛋不触发
    assert _hidden_count(ctx) == 0


def test_map_reveal_via_hidden_exit() -> None:
    """exits[dir] mode=hidden + condition（2a1b 契约）→ 揭示隐藏通道。"""
    ctx = _mk_ctx(level=10)
    exits = {"right": {"to": "hidden_cave", "mode": "hidden",
                       "condition": {"var": "level", "op": "ge", "value": 5},
                       "desc": "石壁后似乎有风声。"}}
    m = _mk_map(exits=exits)
    r = investigate_map(ctx, m, None, today="2026-08-28")
    assert r["kind"] == "map_reveal"
    assert r["map_ref"] == "hidden_cave"


def test_map_reveal_condition_not_satisfied_generic() -> None:
    """地图级 lore condition 不满足 → 泛化文本（R-07 §2.4）。"""
    ctx = _mk_ctx(level=2)
    exits = {"right": {"to": "hidden_cave", "mode": "hidden",
                       "condition": {"var": "level", "op": "ge", "value": 5}}}
    m = _mk_map(exits=exits)
    r = investigate_map(ctx, m, None, today="2026-08-28")
    assert r["kind"] == "generic"
    assert not any(w in r["text"] for w in _FORBIDDEN)


def test_map_reveal_does_not_write_hidden_find() -> None:
    """隐藏地图揭示不写 [事件:隐藏发现]（R-14 仅彩蛋发现即计数）。"""
    ctx = _mk_ctx()
    m = _mk_map(hidden_reveal={"map_id": "hidden_cave", "lore_condition": None})
    r = investigate_map(ctx, m, None, today="2026-08-28")
    assert r["kind"] == "map_reveal"
    assert _hidden_count(ctx) == 0


# ---------------------------------------------------------------------------
# R-11 D-04 优先级 + daily 配额
# ---------------------------------------------------------------------------
def test_priority_hunt_over_map_reveal_over_egg() -> None:
    """三类全命中 → 只输出最高优先的 hunt（一次 /调查 最多 1 条演出/揭示）。"""
    ctx = _mk_ctx()
    m = _mk_map(
        monsters=[_window_row()],
        hidden_reveal={"map_id": "hidden_cave", "lore_condition": None},
        interact_points=[_egg_point(lore_condition=None)],
    )
    r = investigate_map(ctx, m, "雾沼", today="2026-08-28")
    assert r["kind"] == "hunt"
    assert r["boss_ref"] == "wolf_luna"
    assert _hidden_count(ctx) == 0
    assert "map_reveal:hidden_cave" not in ctx["persistent_state"].get(REVEALED_KEY, [])


def test_priority_map_reveal_over_egg() -> None:
    """地图揭示与彩蛋同时命中 → 只输出 map_reveal。"""
    ctx = _mk_ctx()
    m = _mk_map(
        hidden_reveal={"map_id": "hidden_cave", "lore_condition": None},
        interact_points=[_egg_point(lore_condition=None)],
    )
    r = investigate_map(ctx, m, "雾沼", today="2026-08-28")
    assert r["kind"] == "map_reveal"
    assert _hidden_count(ctx) == 0


def test_daily_quota_configurable() -> None:
    """daily 配额可配（settings.investigate.daily_quota=1）：首个揭示后超限 → 泛化。"""
    ctx = _mk_ctx(settings={"investigate": {"daily_quota": 1}})
    p1 = _egg_point(id="a", alias=["甲"], hidden_find_id="egg_a", lore_condition=None)
    p2 = _egg_point(id="b", alias=["乙"], hidden_find_id="egg_b", lore_condition=None)
    m = _mk_map(interact_points=[p1, p2])
    r1 = investigate_map(ctx, m, "甲", today="2026-08-28")
    assert r1["kind"] == "egg" and r1["quota_remaining"] == 0
    r2 = investigate_map(ctx, m, "乙", today="2026-08-28")
    assert r2["kind"] == "generic"  # 超限 → 泛化文本
    assert _hidden_count(ctx) == 1


def test_quota_generic_not_consumed() -> None:
    """泛化文本不计配额（R-11）：多次泛化后 quota 仍空。"""
    ctx = _mk_ctx()
    m = _mk_map(interact_points=[])
    for _ in range(5):
        r = investigate_map(ctx, m, None, today="2026-08-28")
        assert r["kind"] == "generic"
    assert ctx["persistent_state"].get(QUOTA_KEY) is None


def test_today_explicit_overrides_ctx() -> None:
    """today 入参优先于 ctx["today"]（配额按日隔离）。"""
    ctx = _mk_ctx(codex=80, today="2026-08-28")
    m = _mk_map(interact_points=[_egg_point()])
    r = investigate_map(ctx, m, "石像", today="2026-08-29")
    assert r["kind"] == "egg"
    assert ctx["persistent_state"][QUOTA_KEY] == {"2026-08-29": 1}
    # 次日重新配额：再次揭示成功
    ctx2 = dict(ctx, persistent_state={})
    r2 = investigate_map(ctx2, m, "石像", today="2026-08-30")
    assert r2["kind"] == "egg"


def test_quota_reset_next_day() -> None:
    """同一 ctx 跨日：今日配额耗尽 → 泛化；次日揭示恢复（按日懒计算重置）。"""
    ctx = _mk_ctx(settings={"investigate": {"daily_quota": 1}})
    m = _mk_map(interact_points=[_egg_point(lore_condition=None, one_shot=False)])
    investigate_map(ctx, m, "石像", today="2026-08-28")
    assert investigate_map(ctx, m, "石像", today="2026-08-28")["kind"] == "generic"
    # 次日（同一 ctx 不同 today 注入）→ 揭示恢复（one_shot=False 不受去重影响）
    r = investigate_map(ctx, m, "石像", today="2026-08-29")
    assert r["kind"] == "egg"


# ---------------------------------------------------------------------------
# R-14/R-15 发现即计数 + 确定性
# ---------------------------------------------------------------------------
def test_hidden_find_event_chain_referenceable() -> None:
    """发现后 [事件:隐藏发现:egg_statue] 可被条件引擎引用（nested 形态）。"""
    ctx = _mk_ctx()
    m = _mk_map(interact_points=[_egg_point(lore_condition=None)])
    investigate_map(ctx, m, "石像", today="2026-08-28")
    from qbot_rpg.engine.condition_engine import eval_condition
    cond = {"var": "[事件:隐藏发现:egg_statue]", "op": "ge", "value": 1}
    assert eval_condition(cond, ctx) is True


def test_determinism_same_input_same_result() -> None:
    """纯函数确定性：相同 ctx+map 两次调用结果全等（含持久副作用一致）。"""
    def run() -> dict:
        c = _mk_ctx()
        m = _mk_map(interact_points=[_egg_point(lore_condition=None)])
        return investigate_map(c, m, "石像", today="2026-08-28")
    a, b = run(), run()
    assert a == b


def test_generic_uses_settings_pool_deterministic() -> None:
    """可配泛化文本池：无 rng 确定性取池首条；有 rng 用 rng.choice（同种子可复现）。"""
    pool = ["风声穿过林间。", "水汽在林间飘荡。"]
    ctx = _mk_ctx(settings={"investigate": {"generic_texts": pool}}, rng=random.Random(7))
    m = _mk_map(interact_points=[])
    r = investigate_map(ctx, m, None, today="2026-08-28")
    assert r["kind"] == "generic"
    assert r["text"] in pool
