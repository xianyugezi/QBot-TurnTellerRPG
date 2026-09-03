"""adventure_log / environment_events 写读键解析测试（M12.5 批5 收口）。

覆盖：settings.events 配置改名后，adventure_log 六类 log_* 与环境事件
check_environment_events 的 bump 写点/_prev_count 读点落配置新键；零配置
ctx 缺省回退现常量键（向后兼容零破坏，旧键计数照常）。

"""

from __future__ import annotations

from qbot_rpg.core.adventure_log import (
    EVENT_KEY_CODEX_NEW,
    EVENT_KEY_FIRST_CROWN,
    EVENT_KEY_FIRST_KILL,
    EVENT_KEY_HIDDEN_FIND,
    EVENT_KEY_MILESTONE,
    EVENT_KEY_STORY_NODE,
    log_codex_new,
    log_first_crown,
    log_first_kill,
    log_hidden_find,
    log_milestone,
    log_story_node,
)
from qbot_rpg.core.environment_events import (
    ENV_EVENT_KEY_BASE,
    EnvironmentEventRegistry,
    check_environment_events,
)
from qbot_rpg.core.event_bus import EVENT_LOG_KEY


def _mk_ctx(events: object = None, **over: object) -> dict:
    """确定性 ctx：事件三表 + settings（events 段可选注入）+ 环境快照。"""
    ctx: dict = {
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {},
        "settings": {},
        "season": "秋",
        "period": "午夜",
        "weather": "雷雨",
        "now": "2026-08-28T22:40:00+08:00",
    }
    if events is not None:
        ctx["settings"] = {"events": events}
    ctx.update(over)
    return ctx


def _log_of(ctx: dict) -> list:
    """event_log 读取（persistent_state 落点）。"""
    return ctx["persistent_state"][EVENT_LOG_KEY]


def _nested_counts(ctx: dict, key: str) -> dict:
    """nested 计数子表读取：key 缺失视为空表。"""
    sub = ctx["event_counts"].get(key)
    return sub if isinstance(sub, dict) else {}


# ---------------------------------------------------------------------------
# adventure_log 六类：零配置 -> 默认键（向后兼容）
# ---------------------------------------------------------------------------
def test_no_config_log_first_kill_writes_default_key() -> None:
    """无 settings.events 配置 ctx -> log_first_kill 计数落 [事件:首杀]（默认键）。"""
    ctx = _mk_ctx()
    res = log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    assert res["ok"] is True
    assert ctx["event_counts"][EVENT_KEY_FIRST_KILL] == {"wolf_luna": 1}
    assert ctx["longline_counters"][EVENT_KEY_FIRST_KILL] == 1


def test_no_config_all_six_default_keys() -> None:
    """六类 log_* 零配置 -> 各自默认常量键（缺省回退零破坏）。"""
    ctx = _mk_ctx()
    log_first_crown(ctx, "金冠鲤鱼", fish_id="carp_gold")
    log_story_node(ctx, "q_main3", name="主线·第三章")
    log_hidden_find(ctx, "HID_01")
    log_milestone(ctx, 50)
    log_codex_new(ctx, "雾沼水蛭")
    assert ctx["event_counts"][EVENT_KEY_FIRST_CROWN] == {"carp_gold": 1}
    assert ctx["event_counts"][EVENT_KEY_STORY_NODE] == 1  # flat 标量
    assert ctx["event_counts"][EVENT_KEY_HIDDEN_FIND] == {"HID_01": 1}
    assert ctx["event_counts"][EVENT_KEY_MILESTONE] == {"50": 1}
    assert ctx["event_counts"][EVENT_KEY_CODEX_NEW] == {"雾沼水蛭": 1}


# ---------------------------------------------------------------------------
# adventure_log 六类：events 配置改名 -> 新键；默认键 0
# ---------------------------------------------------------------------------
def test_configured_log_first_kill_writes_renamed_key() -> None:
    """events 段配 首杀->狩猎达成 -> log_first_kill 计数落 [事件:狩猎达成] 且默认键 0。"""
    ctx = _mk_ctx({"首杀": "狩猎达成"})
    res = log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    assert res["ok"] is True
    assert ctx["event_counts"]["[事件:狩猎达成]"] == {"wolf_luna": 1}
    assert ctx["longline_counters"]["[事件:狩猎达成]"] == 1
    assert _nested_counts(ctx, EVENT_KEY_FIRST_KILL) == {}


def test_configured_log_first_crown_renamed_key() -> None:
    """events 段配 首钓冠级->王冠级 -> 计数落新键且默认键 0。"""
    ctx = _mk_ctx({"首钓冠级": "王冠级"})
    log_first_crown(ctx, "金冠鲤鱼", fish_id="carp_gold")
    assert ctx["event_counts"]["[事件:王冠级]"] == {"carp_gold": 1}
    assert _nested_counts(ctx, EVENT_KEY_FIRST_CROWN) == {}


def test_configured_log_story_node_renamed_key() -> None:
    """events 段配 任务完成->委托完成 -> story_node flat 计数落新键且默认键 0。"""
    ctx = _mk_ctx({"任务完成": "委托完成"})
    log_story_node(ctx, "q_main3", name="主线·第三章")
    assert ctx["event_counts"]["[事件:委托完成]"] == 1
    assert ctx["event_counts"].get(EVENT_KEY_STORY_NODE, 0) == 0


def test_configured_log_hidden_find_renamed_key() -> None:
    """events 段配 隐藏发现->秘域发现 -> 计数落新键且默认键 0。"""
    ctx = _mk_ctx({"隐藏发现": "秘域发现"})
    log_hidden_find(ctx, "HID_01")
    assert ctx["event_counts"]["[事件:秘域发现]"] == {"HID_01": 1}
    assert _nested_counts(ctx, EVENT_KEY_HIDDEN_FIND) == {}


def test_configured_log_milestone_renamed_key() -> None:
    """events 段配 里程碑->征程节点 -> 计数落新键且默认键 0。"""
    ctx = _mk_ctx({"里程碑": "征程节点"})
    log_milestone(ctx, 50)
    assert ctx["event_counts"]["[事件:征程节点]"] == {"50": 1}
    assert _nested_counts(ctx, EVENT_KEY_MILESTONE) == {}


def test_configured_log_codex_new_renamed_key() -> None:
    """events 段配 图鉴新增->收集物 -> 计数落新键且默认键 0。"""
    ctx = _mk_ctx({"图鉴新增": "收集物"})
    log_codex_new(ctx, "雾沼水蛭")
    assert ctx["event_counts"]["[事件:收集物]"] == {"雾沼水蛭": 1}
    assert _nested_counts(ctx, EVENT_KEY_CODEX_NEW) == {}


# ---------------------------------------------------------------------------
# adventure_log：改名后首见/重复语义沿用新键读点
# ---------------------------------------------------------------------------
def test_configured_repeat_kill_first_seen_under_new_key() -> None:
    """改名后 _prev_count 读新键：首次 first_seen=true，重复 false（读点同键）。"""
    ctx = _mk_ctx({"首杀": "狩猎达成"})
    log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    log = _log_of(ctx)
    assert [x["first_seen"] for x in log] == [True, False]
    assert ctx["event_counts"]["[事件:狩猎达成]"] == {"wolf_luna": 2}


# ---------------------------------------------------------------------------
# environment_events：写读键解析（缺省同值回退 + 配置改名）
# ---------------------------------------------------------------------------
def _env_ctx(events: object = None) -> dict:
    """环境事件 ctx：三表 + settings + 雷雨（匹配 rain_night 窗口派生）。"""
    ctx = _mk_ctx(events, weather="雷雨")
    # persistent_state 已有 event_log 容器（check_environment_events 依赖 bump 落点）
    ctx["persistent_state"][EVENT_LOG_KEY] = []
    return ctx


_ENV_MAPS = [{
    "id": "m1",
    "monsters": [{
        "enemy": "hidden_wolf",
        "window": {"var": "weather", "op": "eq", "param": "雷雨"},
        "mode": "after",
        "after": {"var": "[事件:环境事件:rain_night]", "op": "ge", "value": 3},
        "event_id": "rain_night",
        "hidden_find_id": "hf_wolf",
    }],
}]


def test_check_env_no_config_writes_default_base_key() -> None:
    """零配置 -> 环境事件写读落 ENV_EVENT_KEY_BASE（缺省回退同值零破坏）。"""
    ctx = _env_ctx()
    reg = EnvironmentEventRegistry.from_maps(_ENV_MAPS)
    res = check_environment_events(ctx, {"id": "m1"}, reg)
    assert len(res["triggered"]) == 1
    assert ctx["event_counts"][ENV_EVENT_KEY_BASE] == {"rain_night": 1}
    assert res["triggered"][0]["count"] == 1


def test_check_env_configured_writes_renamed_key() -> None:
    """events 段配 环境事件->自然现象 -> 写读落新键且默认键 0。"""
    ctx = _env_ctx({"环境事件": "自然现象"})
    reg = EnvironmentEventRegistry.from_maps(_ENV_MAPS)
    res = check_environment_events(ctx, {"id": "m1"}, reg)
    assert len(res["triggered"]) == 1
    assert ctx["event_counts"]["[事件:自然现象]"] == {"rain_night": 1}
    assert _nested_counts(ctx, ENV_EVENT_KEY_BASE) == {}
    assert res["triggered"][0]["count"] == 1
