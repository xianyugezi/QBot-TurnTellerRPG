"""环境事件引擎单测（M7 BCH-09 3f F-17 · R-24/R-25/R-26）。

覆盖：注册表装载（显式 environment_events + 隐藏 BOSS window 派生 + 归一/去重）/
事件全键 / check_environment_events 触发计数+日志+首见+地图作用域 / event_timeline
过滤倒序 limit / 纯函数确定性（now 由 ctx 注入）。零 NoneBot，纯函数确定性。
"""

from __future__ import annotations

from qbot_rpg.core.environment_events import (
    AMBIENT_TAG,
    ENVIRONMENT_TAG,
    ENV_EVENT_KEY_BASE,
    EnvironmentEventRegistry,
    check_environment_events,
    event_key_environment,
    event_timeline,
    load_environment_events,
)

# -------------------------------------------------------------------------------------
# 测试夹具（纯 dict，确定性）
# -------------------------------------------------------------------------------------
MAPS = [
    {
        "id": "m1",
        "name": "雾沼",
        "monsters": [
            {"enemy": "wolf", "count": 2},
            {
                "enemy": "hidden_wolf",
                "window": {"var": "weather", "op": "eq", "param": "雷雨"},
                "mode": "after",
                "after": {"var": "[事件:环境事件:rain_night]", "op": "ge", "value": 3},
                "event_id": "rain_night",
                "hidden_find_id": "hf_wolf",
            },
        ],
    },
    {
        "id": "m2",
        "name": "山道",
        "environment_events": [
            {
                "event_id": "autumn_wind",
                "tag": AMBIENT_TAG,
                "condition": {"var": "season", "param": "秋"},
                "priority": 5,
                "text": "秋风吹过{地图}，{季节}的气息……",
            },
            {
                "event_id": "global_event",
                "condition": {"var": "[事件:首杀]", "op": "ge", "value": 1},
                "priority": 1,
            },
        ],
    },
]


def _make_ctx(**extra):
    """最小求值/写入上下文（persistent_state 承载 event_log 环形；now 确定性注入）。"""
    ctx = {
        "persistent_state": {},
        "event_counts": {},
        "longline_counters": {},
        "season": "秋",
        "period": "午夜",
        "weather": "雷雨",
        "now": "2026-08-28T12:00:00",
        "settings": {},
    }
    ctx.update(extra)
    return ctx


# -------------------------------------------------------------------------------------
# 注册表装载（R-24）
# -------------------------------------------------------------------------------------
def test_load_environment_events_explicit_and_derived():
    """显式 environment_events + 隐藏 BOSS window 派生两路装载，字段归一。"""
    reg = load_environment_events(MAPS)
    assert set(reg) == {"autumn_wind", "global_event", "rain_night"}
    rn = reg["rain_night"]
    assert rn["event_id"] == "rain_night"
    assert rn["tag"] == ENVIRONMENT_TAG
    assert rn["priority"] == 100  # 派生事件缺省优先级
    assert rn["map_id"] == "m1"
    assert rn["condition"] == {"var": "weather", "op": "eq", "param": "雷雨"}
    aw = reg["autumn_wind"]
    assert aw["tag"] == AMBIENT_TAG
    assert aw["map_id"] == "m2"
    assert aw["template_id"] == "environment.autumn_wind"  # 缺省模板 ID 约定
    assert aw["text"] == "秋风吹过{地图}，{季节}的气息……"
    assert reg["global_event"]["map_id"] == "m2"


def test_load_environment_events_normalized_pass_through():
    """已归一形（load_environment_events 产物）经 Registry 构造二次装载直通，map_id 不丢失。"""
    reg = load_environment_events(MAPS)
    reg2 = EnvironmentEventRegistry(list(reg.values()))
    assert reg2.get("rain_night")["map_id"] == "m1"
    assert reg2.get("autumn_wind")["map_id"] == "m2"
    assert reg2.get("global_event")["map_id"] == "m2"


def test_load_environment_events_empty_and_single_map():
    """缺数据 → 空 dict；单张地图 dict 形态可装载。"""
    assert load_environment_events(None) == {}
    assert load_environment_events([]) == {}
    single = load_environment_events(MAPS[0])
    assert set(single) == {"rain_night"}


def test_load_environment_events_dedup_first_wins():
    """重复 event_id 取先（确定性：装载序第一个）。"""
    maps = [
        {"id": "m1", "environment_events": [
            {"event_id": "dup", "priority": 1},
            {"event_id": "dup", "priority": 9},
        ]},
    ]
    reg = load_environment_events(maps)
    assert reg["dup"]["priority"] == 1


def test_event_key_environment_full_key():
    """事件全键（条件引用形态）：[事件:环境事件:{event_id}]。"""
    assert event_key_environment("rain_night") == "[事件:环境事件:rain_night]"
    assert event_key_environment(123) == "[事件:环境事件:123]"


def test_registry_get_ids_applicable_scoping():
    """Registry：get/ids/applicable 地图作用域 + 优先级排序（高者先）。"""
    reg = EnvironmentEventRegistry.from_maps(MAPS)
    assert reg.get("rain_night") is not None
    assert reg.get("missing") is None
    assert set(reg.ids()) == {"autumn_wind", "global_event", "rain_night"}
    assert [e["event_id"] for e in reg.applicable("m1")] == ["rain_night"]
    # m2 适用：autumn_wind(5) 先于 global_event(1)（优先级高者先，确定性）
    assert [e["event_id"] for e in reg.applicable("m2")] == ["autumn_wind", "global_event"]


# -------------------------------------------------------------------------------------
# 触发检查（R-26 触发时机 / 补白 4）
# -------------------------------------------------------------------------------------
def test_check_environment_events_triggers_count_and_log():
    """条件满足即计数+日志：event_counts nested target + longline + event_log 条目。"""
    ctx = _make_ctx()
    reg = EnvironmentEventRegistry.from_maps(MAPS)
    res = check_environment_events(ctx, MAPS[1], reg)  # m2：autumn_wind 条件满足
    assert res["count"] == 1
    t = res["triggered"][0]
    assert t["event_id"] == "autumn_wind"
    assert t["key"] == "[事件:环境事件:autumn_wind]"
    assert t["first_seen"] is True
    assert t["count"] == 1
    # nested 计数（条件引擎读取源）
    assert ctx["event_counts"][ENV_EVENT_KEY_BASE]["autumn_wind"] == 1
    # longline 累计（只增不减）
    assert ctx["longline_counters"][ENV_EVENT_KEY_BASE] == 1
    # event_log 条目（persistent_state 承载，tag/snapshot/template/params）
    log = ctx["persistent_state"]["event_log"]
    assert len(log) == 1
    entry = log[0]
    assert entry["tag"] == AMBIENT_TAG
    assert entry["event_id"] == "autumn_wind"
    assert entry["snapshot"] == {"season": "秋", "period": "午夜", "weather": "雷雨"}
    assert entry["template_id"] == "environment.autumn_wind"
    assert entry["ts"] == "2026-08-28T12:00:00"
    assert entry["params"]["event_id"] == "autumn_wind"


def test_check_environment_events_condition_not_met_no_trigger():
    """条件不满足 → 零触发零写入（不提示原则）。"""
    ctx = _make_ctx(weather="晴", season="春")
    res = check_environment_events(ctx, MAPS[1], EnvironmentEventRegistry.from_maps(MAPS))
    assert res["triggered"] == []
    assert ctx["event_counts"] == {}
    assert ctx["longline_counters"] == {}


def test_check_environment_events_map_scoping():
    """地图作用域：m1 只触发派生 rain_night（窗口满足），m2 事件不越界触发。"""
    ctx = _make_ctx()
    res = check_environment_events(ctx, MAPS[0], EnvironmentEventRegistry.from_maps(MAPS))
    assert [t["event_id"] for t in res["triggered"]] == ["rain_night"]
    assert res["triggered"][0]["first_seen"] is True
    assert ctx["event_counts"][ENV_EVENT_KEY_BASE] == {"rain_night": 1}


def test_check_environment_events_derived_window_after_count():
    """隐藏 BOSS after 模式依赖 [事件:环境事件:ID] 计数：窗口重复满足 → 计数累加。"""
    ctx = _make_ctx()
    reg = EnvironmentEventRegistry.from_maps(MAPS)
    for _ in range(3):
        check_environment_events(ctx, MAPS[0], reg)
    assert ctx["event_counts"][ENV_EVENT_KEY_BASE]["rain_night"] == 3
    # 非首见（重复触发不再标首见）
    res = check_environment_events(ctx, MAPS[0], reg)
    assert res["triggered"][0]["first_seen"] is False
    assert res["triggered"][0]["count"] == 4


def test_check_environment_events_registry_from_ctx():
    """registry 缺省 → ctx["environment_events"]（dict）/ ctx["maps_data"] 兜底。"""
    ctx = _make_ctx(environment_events=load_environment_events(MAPS))
    res = check_environment_events(ctx, MAPS[0])
    assert [t["event_id"] for t in res["triggered"]] == ["rain_night"]
    ctx2 = _make_ctx(maps_data=MAPS)
    res2 = check_environment_events(ctx2, MAPS[1])
    assert [t["event_id"] for t in res2["triggered"]] == ["autumn_wind"]


def test_check_environment_events_empty_registry_safe():
    """无事件注册表（None/空）→ 零触发不抛错（缺省兜底）。"""
    ctx = _make_ctx()
    assert check_environment_events(ctx, {"id": "x", "monsters": []})["triggered"] == []
    assert check_environment_events(ctx, None)["triggered"] == []


# -------------------------------------------------------------------------------------
# 渲染时间线（R-26）
# -------------------------------------------------------------------------------------
def _timeline_ctx():
    """预置 4 条 event_log（2 条环境 + 1 条 first_kill + 1 条环境）的上下文。"""
    ctx = _make_ctx()
    log = ctx["persistent_state"].setdefault("event_log", [])
    for i, (tag, eid) in enumerate([
        (ENVIRONMENT_TAG, "rain_night"),
        ("first_kill", "wolf"),          # 非环境 tag，不进时间线
        (ENVIRONMENT_TAG, "autumn_wind"),
        (AMBIENT_TAG, "dawn_hint"),
    ]):
        log.append({
            "event_id": eid,
            "tag": tag,
            "count_key": "[事件:环境事件]",
            "template_id": f"environment.{eid}",
            "params": {"event_id": eid, "name": f"事件{eid}"},
            "snapshot": {"season": "秋", "period": "午夜", "weather": "雷雨"},
            "first_seen": True,
            "ts": f"2026-08-28T12:0{i}:00",
        })
    return ctx


def test_event_timeline_filters_reverse_limit():
    """时间线：过滤 tag=environment/ambient、倒序（最新在前）、limit 生效。"""
    ctx = _timeline_ctx()
    rows = event_timeline(ctx, limit=10)
    assert [r["event_id"] for r in rows] == ["dawn_hint", "autumn_wind", "rain_night"]
    assert len(event_timeline(ctx, limit=2)) == 2
    assert [r["event_id"] for r in event_timeline(ctx, limit=2)] == ["dawn_hint", "autumn_wind"]


def test_event_timeline_row_fields():
    """每行含 ts / snapshot / event_id / tag / template_id / params / summary。"""
    ctx = _timeline_ctx()
    row = event_timeline(ctx, limit=1)[0]
    assert row["ts"] == "2026-08-28T12:03:00"
    assert row["snapshot"] == {"season": "秋", "period": "午夜", "weather": "雷雨"}
    assert row["event_id"] == "dawn_hint"
    assert row["tag"] == AMBIENT_TAG
    assert row["template_id"] == "environment.dawn_hint"
    assert row["params"]["event_id"] == "dawn_hint"
    assert "事件dawn_hint" in row["summary"]


def test_event_timeline_summary_from_registry_text():
    """registry 模板文本渲染优先（快照注入占位符），params 兜底。"""
    ctx = _timeline_ctx()
    reg = EnvironmentEventRegistry.from_maps(MAPS)
    rows = event_timeline(ctx, limit=10, registry=reg)
    autumn = [r for r in rows if r["event_id"] == "autumn_wind"][0]
    # 模板文本「秋风吹过{地图}，{季节}的气息……」→ 快照注入秋（地图无 → --）
    assert autumn["summary"] == "秋风吹过--，秋的气息……"


def test_event_timeline_read_only():
    """时间线只读不改（纯函数）：event_log 长度不变，无副作用。"""
    ctx = _timeline_ctx()
    before = list(ctx["persistent_state"]["event_log"])
    event_timeline(ctx, limit=10)
    assert ctx["persistent_state"]["event_log"] == before
    assert ctx["event_counts"] == {}
