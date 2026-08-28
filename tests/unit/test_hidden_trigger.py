"""隐藏要素引擎测试（tests/unit/test_hidden_trigger.py · M7 BCH-07 3f F-08~F-10 · R-12~R-16）。

覆盖：隐藏 BOSS 三触发模式（R-12：replace/after/fixed + 100% 必出 + 3 次保底 + 日限 1 次 +
懒计算自然日）/ 隐藏任务（R-13 D-05：quest.npc.conditions 全与、priority、npc 匹配、三表
去重、零暗示）/ 仪式感一次性揭示（R-15 F-10：【发现】卡片无 emoji + 首见日志 + 重复简短确认
+ lore 交接补白）/ 确定性（today 注入无随机）。
"""

from __future__ import annotations

import random

from qbot_rpg.content.map_models import MapDef
from qbot_rpg.core.adventure_log import EVENT_KEY_HIDDEN_FIND
from qbot_rpg.core.event_bus import EVENT_LOG_KEY
from qbot_rpg.core.hidden_trigger import (
    BOSS_DAILY_KEY,
    BOSS_PITY_KEY,
    DEFAULT_CONFIRM_TEXT,
    PITY_THRESHOLD,
    REVEALED_KEY,
    check_boss_spawn,
    check_hidden_quest,
    npc_quest_conditions_met,
    reveal_find,
)


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
    """MapDef 构造（raw 全量镜像，monsters[] 经 raw 兜底读取）。"""
    entry.setdefault("id", "misty_marsh")
    entry.setdefault("name", "雾沼")
    entry.setdefault("desc", "雾沼的泥泞小道，水汽弥漫。")
    raw = dict(entry)
    return MapDef(id=str(entry["id"]), name=str(entry["name"]), raw=raw)


def _window_cond() -> dict:
    """限定窗口条件键（R-12：秋·午夜·雷雨；对齐 investigate 测试同款形态）。"""
    return {
        "all": [
            {"var": "season", "op": "eq", "param": "秋"},
            {"var": "period", "op": "eq", "param": "午夜"},
            {"var": "weather", "op": "eq", "param": "雷雨"},
        ]
    }


def _boss_row(**over: object) -> dict:
    """隐藏 BOSS 窗口行（补白 1：enemy + window + mode? + after? + desc?）。"""
    row: dict = {
        "enemy": "wolf_luna",
        "window": _window_cond(),
        "mode": "replace",
        "desc": "你听到远处传来低沉的狼嗥，与平时的风雨声不同。",
        "title": "蚀月之狼",
        "hidden_find_id": "boss_wolf_luna",
    }
    row.update(over)
    return row


def _rain_event(n: int = 0) -> dict:
    """[事件:环境事件:雨夜] 嵌套计数（N-03/3f 预置事件形态）。"""
    return {"[事件:环境事件]": {"雨夜": n}}


def _log_of(ctx: dict) -> list:
    """event_log 读取（persistent_state 落点）。"""
    return ctx["persistent_state"][EVENT_LOG_KEY]


def _hidden_count(ctx: dict) -> int:
    """[事件:隐藏发现] 嵌套计数汇总。"""
    sub = ctx["event_counts"].get(EVENT_KEY_HIDDEN_FIND, {})
    return sum(int(v) for v in sub.values()) if isinstance(sub, dict) else 0


def _pity_of(ctx: dict, boss: str) -> int:
    """保底计数直读（断言用）。"""
    p = ctx["persistent_state"].get(BOSS_PITY_KEY, {})
    return int(p.get(boss, 0))


# ---------------------------------------------------------------------------
# R-12 隐藏 BOSS：三触发模式
# ---------------------------------------------------------------------------
def test_replace_mode_window_hit_spawns() -> None:
    """replace：窗口满足（秋·午夜·雷雨）→ 替换出没，100% 必出（TC-12）。"""
    ctx = _mk_ctx()
    m = _mk_map(monsters=[_boss_row()])
    r = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r["spawned"] is True
    assert r["mode"] == "replace"
    assert r["boss_ref"] == "wolf_luna"
    assert r["reason"] == "condition_met"
    assert r["signal"]["kind"] == "hunt"
    assert r["signal"]["boss_ref"] == "wolf_luna"
    assert r["signal"]["hidden_find_id"] == "boss_wolf_luna"
    assert "狼嗥" in r["signal"]["text"]


def test_replace_mode_window_miss_zero_hint() -> None:
    """窗口外（春·白昼·晴）→ 不触发，零暗示（R-12/TC-10）。"""
    ctx = _mk_ctx(season="春", period="白昼", weather="晴")
    m = _mk_map(monsters=[_boss_row()])
    r = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r["spawned"] is False
    assert r["reason"] == "window_not_met"
    assert r["boss_ref"] is None


def test_replace_mode_default_when_missing() -> None:
    """mode 缺省 → replace（补白 1）；窗口满足即出。"""
    row = _boss_row()
    del row["mode"]
    m = _mk_map(monsters=[row])
    r = check_boss_spawn(_mk_ctx(), m)
    assert r["spawned"] is True
    assert r["mode"] == "replace"


def test_after_mode_requires_prereq_event() -> None:
    """after：窗口满足 + [事件:环境事件:雨夜]≥3 才追加（R-12/TC-12）。"""
    row = _boss_row(mode="after", after={"var": "[事件:环境事件:雨夜]", "op": "ge", "value": 3})
    # 雨夜 2 次 → 前置不足 → 不触发
    ctx = _mk_ctx(event_counts=_rain_event(2))
    m = _mk_map(monsters=[row])
    r = check_boss_spawn(ctx, m)
    assert r["spawned"] is False
    assert r["reason"] == "window_not_met"
    # 雨夜 3 次 → 前置达成 → 追加出现
    ctx2 = _mk_ctx(event_counts=_rain_event(3))
    r2 = check_boss_spawn(ctx2, m)
    assert r2["spawned"] is True
    assert r2["mode"] == "after"
    assert r2["reason"] == "condition_met"


def test_after_mode_no_extra_prereq_window_only() -> None:
    """after 模式未配 after 字段 → 仅窗口即可（补白 1：after=None 无额外前置）。"""
    row = _boss_row(mode="after")
    m = _mk_map(monsters=[row])
    r = check_boss_spawn(_mk_ctx(), m)
    assert r["spawned"] is True
    assert r["mode"] == "after"


def test_fixed_mode_guaranteed_no_rng() -> None:
    """fixed：固定交互点/时刻蹲点必出（窗口满足 100% 命中，无随机，TC-12）。"""
    row = _boss_row(mode="fixed")
    m = _mk_map(monsters=[row])
    for seed in (1, 42, 99):
        ctx = _mk_ctx(rng=random.Random(seed))
        r = check_boss_spawn(ctx, m)
        assert r["spawned"] is True
        assert r["mode"] == "fixed"
        assert r["reason"] == "condition_met"


def test_bad_window_condition_failsafe_zero_hint() -> None:
    """window 求值失败（未注册 var）→ 不满足，不触发（D-03 fail-safe）。"""
    row = _boss_row(window={"var": "nonexistent_xyz", "op": "eq", "param": "x"})
    m = _mk_map(monsters=[row])
    r = check_boss_spawn(_mk_ctx(), m)
    assert r["spawned"] is False
    assert r["reason"] == "window_not_met"


def test_no_hidden_boss_row() -> None:
    """地图无隐藏 BOSS 行 → no_hidden_boss（普通怪行不带 window 不参与）。"""
    m = _mk_map(monsters=[{"enemy": "wolf_plain", "count": 3}])
    r = check_boss_spawn(_mk_ctx(), m)
    assert r["spawned"] is False
    assert r["reason"] == "no_hidden_boss"


# ---------------------------------------------------------------------------
# R-12 保底与日限
# ---------------------------------------------------------------------------
def test_daily_limit_once_per_day_lazy_reset() -> None:
    """日限 1 次：当日触发过 → 同日第 2 次不出；次日自然日懒计算重置可再出（TC-13）。"""
    m = _mk_map(monsters=[_boss_row()])
    ctx = _mk_ctx()
    # 首日首蹲 → 必出
    r1 = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r1["spawned"] is True
    # 首日再蹲（同 ctx，日限表已记）→ 日限挡下
    r2 = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r2["spawned"] is False
    assert r2["reason"] == "daily_limit"
    assert r2["boss_ref"] == "wolf_luna"
    # 次日（同一 ctx，日期作键懒计算，无需显式重置）→ 再出
    r3 = check_boss_spawn(ctx, m, today="2026-08-29")
    assert r3["spawned"] is True
    assert ctx["persistent_state"][BOSS_DAILY_KEY] == {
        "2026-08-28": {"wolf_luna": 1},
        "2026-08-29": {"wolf_luna": 1},
    }


def test_daily_limit_tracked_in_persistent_state() -> None:
    """触发后日限表落 persistent_state[hidden_boss_daily][日期][boss_ref]。"""
    ctx = _mk_ctx()
    m = _mk_map(monsters=[_boss_row()])
    check_boss_spawn(ctx, m, today="2026-08-28")
    assert ctx["persistent_state"][BOSS_DAILY_KEY] == {"2026-08-28": {"wolf_luna": 1}}


def test_pity_increments_on_blocked_window() -> None:
    """被日限挡下的窗口 → 保底 +1（连续满足条件未出战窗口计数，TC-13）。"""
    m = _mk_map(monsters=[_boss_row()])
    ctx = _mk_ctx()
    assert check_boss_spawn(ctx, m, today="2026-08-28")["spawned"] is True  # pity 0
    assert _pity_of(ctx, "wolf_luna") == 0
    r = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r["spawned"] is False
    assert r["reason"] == "daily_limit"
    assert r["pity"] == 1
    assert _pity_of(ctx, "wolf_luna") == 1


def test_pity_threshold_forces_spawn_next_window() -> None:
    """累计 ≥3 → 下次必触发（覆盖日限，R-12 L84 / 补白 2）。"""
    m = _mk_map(monsters=[_boss_row()])
    ctx = _mk_ctx()
    # 首蹲出
    assert check_boss_spawn(ctx, m, today="2026-08-28")["spawned"] is True
    # 3 次被挡 → 保底 1, 2, 3（就绪）
    for i in (1, 2, 3):
        r = check_boss_spawn(ctx, m, today="2026-08-28")
        assert r["spawned"] is False
        assert r["reason"] == "daily_limit"
        assert r["pity"] == i
    assert _pity_of(ctx, "wolf_luna") == PITY_THRESHOLD
    # 下次（第 5 蹲，当日第 2 次）→ 保底强制触发，覆盖日限
    r = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r["spawned"] is True
    assert r["reason"] == "pity"
    assert _pity_of(ctx, "wolf_luna") == 0  # 触发后清零


def test_spawn_resets_pity() -> None:
    """成功触发（condition_met）→ 保底清零。"""
    ctx = _mk_ctx(persistent_state={BOSS_PITY_KEY: {"wolf_luna": 2}})
    m = _mk_map(monsters=[_boss_row()])
    r = check_boss_spawn(ctx, m, today="2026-08-29")
    assert r["spawned"] is True
    assert r["reason"] == "condition_met"
    assert _pity_of(ctx, "wolf_luna") == 0


def test_today_empty_no_daily_limit_deterministic() -> None:
    """today 空串 → 不强制日限（确定性）：同窗口重复判定均触发，无状态副作用拦截。"""
    m = _mk_map(monsters=[_boss_row()])
    for _ in range(3):
        r = check_boss_spawn(_mk_ctx(), m, today="")
        assert r["spawned"] is True
        assert r["reason"] == "condition_met"


def test_window_miss_has_no_state_side_effect() -> None:
    """窗口不满足 → 不触发且不写任何状态（纯函数确定性，零副作用）。"""
    ctx = _mk_ctx(season="春", period="白昼", weather="晴")
    m = _mk_map(monsters=[_boss_row()])
    r = check_boss_spawn(ctx, m, today="2026-08-28")
    assert r["spawned"] is False
    assert ctx["persistent_state"] == {}


# ---------------------------------------------------------------------------
# R-13 隐藏任务
# ---------------------------------------------------------------------------
def _quest(**over: object) -> dict:
    """quest 条目（2b4 §1.4：id + npc{id, conditions, priority}）。"""
    q: dict = {
        "id": "rain_secret_quest",
        "name": "雨夜传闻",
        "npc": {
            "id": "npc_elder",
            "conditions": [
                {"var": "codex", "op": "ge", "value": 50},
                {"var": "[事件:环境事件:雨夜]", "op": "ge", "value": 1},
            ],
            "priority": 0,
        },
    }
    q.update(over)
    return q


def test_hidden_quest_granted_when_conditions_met() -> None:
    """图鉴≥50% + 雨夜≥1 → NPC 主动发任务（R-13 D-05，TC-14）。"""
    ctx = _mk_ctx(codex=60, event_counts=_rain_event(1))
    r = check_hidden_quest(ctx, "npc_elder", [_quest()])
    assert r["grant"] is True
    assert r["quest_id"] == "rain_secret_quest"
    assert r["reason"] == "granted"


def test_hidden_quest_conditions_fail_zero_hint() -> None:
    """图鉴 45%（<50%）→ 不发，无「可领任务」暗示（R-13 D-05，TC-14）。"""
    ctx = _mk_ctx(codex=45, event_counts=_rain_event(1))
    r = check_hidden_quest(ctx, "npc_elder", [_quest()])
    assert r["grant"] is False
    assert r["quest_id"] is None
    assert r["reason"] == "no_eligible_quest"


def test_hidden_quest_all_conditions_required_and() -> None:
    """雨夜未达（事件 0 次，图鉴够）→ 全与不满足 → 不发。"""
    ctx = _mk_ctx(codex=60, event_counts={})
    r = check_hidden_quest(ctx, "npc_elder", [_quest()])
    assert r["grant"] is False


def test_hidden_quest_priority_order() -> None:
    """多候选均满足 → priority 小者先（2b4 §1.4）。"""
    ctx = _mk_ctx(codex=60, event_counts=_rain_event(1))
    q1 = _quest(id="q_high", npc={"id": "npc_elder", "conditions": [], "priority": 5})
    q2 = _quest(id="q_low", npc={"id": "npc_elder", "conditions": [], "priority": 1})
    r = check_hidden_quest(ctx, "npc_elder", [q1, q2])
    assert r["grant"] is True
    assert r["quest_id"] == "q_low"


def test_hidden_quest_npc_mismatch_filtered() -> None:
    """quest.npc.id 与当前 NPC 不匹配 → 不发。"""
    ctx = _mk_ctx(codex=60, event_counts=_rain_event(1))
    r = check_hidden_quest(ctx, "npc_other", [_quest()])
    assert r["grant"] is False


def test_hidden_quest_active_dedup() -> None:
    """已接取（quest_active）→ 不重发（SM06 去重）。"""
    ctx = _mk_ctx(codex=60, event_counts=_rain_event(1), quest_active={"rain_secret_quest": {}})
    r = check_hidden_quest(ctx, "npc_elder", [_quest()])
    assert r["grant"] is False


def test_hidden_quest_no_conditions_always_grantable() -> None:
    """quest.npc.conditions 缺省/空 → 恒可发（2b4 §1.4 默认 []）。"""
    ctx = _mk_ctx()
    q = _quest(npc={"id": "npc_elder", "priority": 0})
    r = check_hidden_quest(ctx, "npc_elder", [q])
    assert r["grant"] is True


def test_npc_quest_conditions_met_helper() -> None:
    """BCH-04 缺口 helper：conditions 数组全与求值（npc.py 接线由兄弟路做）。"""
    ctx = _mk_ctx(codex=60, event_counts=_rain_event(1))
    assert npc_quest_conditions_met(ctx, _quest()) is True
    assert npc_quest_conditions_met(ctx, _quest(npc=None)) is True          # 缺 npc → 恒可发
    assert npc_quest_conditions_met(ctx, _quest(npc={"id": "x"})) is True   # 缺 conditions → 恒可发
    low = _mk_ctx(codex=45, event_counts=_rain_event(1))
    assert npc_quest_conditions_met(low, _quest()) is False                 # 条件不足
    bad = _quest(npc={"id": "x", "conditions": {"var": "bogus_var", "op": "eq", "param": 1}})
    assert npc_quest_conditions_met(ctx, bad) is False                      # 求值失败 → False


# ---------------------------------------------------------------------------
# R-15 / F-10 仪式感一次性揭示
# ---------------------------------------------------------------------------
def test_reveal_first_time_card_and_log() -> None:
    """首次发现 → 【发现】卡片 + first_seen + 首见日志 + [事件:隐藏发现:ID] 计数（TC-15/16）。"""
    ctx = _mk_ctx()
    r = reveal_find(ctx, "boss_wolf_luna", "蚀月之狼")
    assert r["ok"] is True
    assert r["card"] == "【发现】蚀月之狼"
    assert r["first_seen"] is True
    assert r["logged"] is True
    assert r["revealed"] is True
    assert ctx["event_counts"][EVENT_KEY_HIDDEN_FIND] == {"boss_wolf_luna": 1}
    assert ctx["longline_counters"][EVENT_KEY_HIDDEN_FIND] == 1
    e = _log_of(ctx)[0]
    assert e["tag"] == "hidden_find"
    assert e["first_seen"] is True
    assert e["snapshot"] == {"season": "秋", "period": "午夜", "weather": "雷雨"}
    assert ctx["persistent_state"][REVEALED_KEY] == ["hidden_find:boss_wolf_luna"]


def test_reveal_repeat_short_confirm_no_double_count() -> None:
    """二次发现 → 简短确认，无卡片、不再计数、不再首见（R-15 TC-15）。"""
    ctx = _mk_ctx()
    reveal_find(ctx, "boss_wolf_luna", "蚀月之狼")
    r = reveal_find(ctx, "boss_wolf_luna", "蚀月之狼")
    assert r["card"] == DEFAULT_CONFIRM_TEXT
    assert r["first_seen"] is False
    assert r["logged"] is False
    assert _hidden_count(ctx) == 1  # 只计一次
    assert len(_log_of(ctx)) == 1


def test_reveal_card_no_emoji() -> None:
    """卡片无 emoji（⛩️ 降级【发现】，铁律）。"""
    ctx = _mk_ctx()
    r = reveal_find(ctx, "egg_statue", "雾沼石像")
    assert "【发现】" in r["card"]
    assert "⛩️" not in r["card"]


def test_reveal_lore_pending_flagged() -> None:
    """图鉴 lore 补全交接：lore_pending=True（2c1c/4d 未实装，写侧归 F-16/BCH-09 补白 5）。"""
    r = reveal_find(_mk_ctx(), "boss_wolf_luna", "蚀月之狼")
    assert r["lore_pending"] is True


def test_reveal_empty_id_fails() -> None:
    """空 hidden_find_id → ok=False 不写任何状态。"""
    ctx = _mk_ctx()
    r = reveal_find(ctx, "", "标题")
    assert r["ok"] is False
    assert ctx["persistent_state"] == {}
    assert _hidden_count(ctx) == 0


def test_reveal_title_fallback_to_id() -> None:
    """title 缺省 → 用 hidden_find_id 作卡片标题。"""
    r = reveal_find(_mk_ctx(), "mystery_x", "")
    assert r["card"] == "【发现】mystery_x"
