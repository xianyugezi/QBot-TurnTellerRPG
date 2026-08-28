"""冒险日志引擎测试（tests/unit/test_adventure_log.py · M7 3f F-01/F-02 + N-04 RN-11）。

覆盖：六类记录写入（三表 + tag/first_seen/params/快照）/ 事件键约定 / 分组分页
（组序固定、组内倒序、每页 5 条、越界回落、空组不渲染）/ 环形容量 / 非六类条目过滤 /
RN-11 会话快照 30 天惰性清理。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from qbot_rpg.core.adventure_log import (
    DIALOG_SNAPSHOT_KEY,
    DIALOG_SNAPSHOT_TTL_DAYS,
    EVENT_KEY_FIRST_CROWN,
    EVENT_KEY_FIRST_KILL,
    EVENT_KEY_HIDDEN_FIND,
    EVENT_KEY_MILESTONE,
    EVENT_KEY_STORY_NODE,
    EVENT_KEY_CODEX_NEW,
    cleanup_dialog_snapshot,
    event_key_codex_new,
    event_key_first_crown,
    event_key_first_kill,
    event_key_hidden_find,
    event_key_milestone,
    event_key_story_node,
    log_codex_new,
    log_first_crown,
    log_hidden_find,
    log_first_kill,
    log_milestone,
    log_story_node,
    read_log,
)
from qbot_rpg.core.event_bus import EVENT_LOG_KEY, bump_event


def _mk_ctx(**over: object) -> dict:
    """确定性 ctx：三表 + 环境快照 + settings（event_log 落 persistent_state）。"""
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
    ctx.update(over)
    return ctx


def _log_of(ctx: dict) -> list:
    """event_log 读取（persistent_state 落点）。"""
    return ctx["persistent_state"][EVENT_LOG_KEY]


# ---------------------------------------------------------------------------
# 六类记录写入（R-02：三表 + tag/first_seen/params）
# ---------------------------------------------------------------------------
def test_first_kill_writes_three_tables() -> None:
    """首杀：event_counts nested 按怪物 + longline 累计 + event_log 条目（首见）。"""
    ctx = _mk_ctx()
    res = log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    assert res["ok"] is True
    assert ctx["event_counts"][EVENT_KEY_FIRST_KILL] == {"wolf_luna": 1}
    assert ctx["longline_counters"][EVENT_KEY_FIRST_KILL] == 1
    e = _log_of(ctx)[0]
    assert e["tag"] == "first_kill"
    assert e["first_seen"] is True
    assert e["params"]["name"] == "蚀月之狼"
    assert e["snapshot"] == {"season": "秋", "period": "午夜", "weather": "雷雨"}


def test_first_kill_first_seen_only_first_time() -> None:
    """重复首杀计数只增不减，仅首次 first_seen=true。"""
    ctx = _mk_ctx()
    log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    log_first_kill(ctx, "蚀月之狼", monster_id="wolf_luna")
    log_first_kill(ctx, "雾沼水蛭", monster_id="leech")
    log = _log_of(ctx)
    assert [x["first_seen"] for x in log] == [True, False, True]
    assert ctx["event_counts"][EVENT_KEY_FIRST_KILL] == {"wolf_luna": 2, "leech": 1}
    assert ctx["longline_counters"][EVENT_KEY_FIRST_KILL] == 3


def test_story_node_flat_preset() -> None:
    """剧情节点：复用 N-03 预置键 [事件:任务完成] flat（条件引擎读取源不变）。"""
    ctx = _mk_ctx()
    res = log_story_node(ctx, "q_main3", name="主线·第三章")
    assert res["ok"] is True
    assert ctx["event_counts"][EVENT_KEY_STORY_NODE] == 1  # flat 标量
    assert ctx["longline_counters"][EVENT_KEY_STORY_NODE] == 1
    e = _log_of(ctx)[0]
    assert e["tag"] == "story_node"
    assert e["first_seen"] is False
    assert e["params"] == {"node": "q_main3", "name": "主线·第三章"}


def test_first_crown_writes() -> None:
    """首钓冠级：nested 按鱼种 + 首见 first_seen=true。"""
    ctx = _mk_ctx()
    log_first_crown(ctx, "金冠鲤鱼", fish_id="carp_gold")
    log_first_crown(ctx, "金冠鲤鱼", fish_id="carp_gold")
    assert ctx["event_counts"][EVENT_KEY_FIRST_CROWN] == {"carp_gold": 2}
    assert [x["first_seen"] for x in _log_of(ctx)] == [True, False]


def test_hidden_find_writes() -> None:
    """隐藏发现：nested 按隐藏 ID + 首见 first_seen=true（契约 [事件:隐藏发现:ID]）。"""
    ctx = _mk_ctx()
    log_hidden_find(ctx, "HID_01")
    assert ctx["event_counts"][EVENT_KEY_HIDDEN_FIND] == {"HID_01": 1}
    e = _log_of(ctx)[0]
    assert e["tag"] == "hidden_find"
    assert e["first_seen"] is True


def test_milestone_writes() -> None:
    """里程碑：nested 按完成度，非首见类 first_seen=false。"""
    ctx = _mk_ctx()
    log_milestone(ctx, 50)
    assert ctx["event_counts"][EVENT_KEY_MILESTONE] == {"50": 1}
    e = _log_of(ctx)[0]
    assert e["tag"] == "milestone"
    assert e["first_seen"] is False
    assert e["params"]["pct"] == "50"


def test_codex_new_writes() -> None:
    """图鉴新增：nested 按条目，非首见类 first_seen=false。"""
    ctx = _mk_ctx()
    log_codex_new(ctx, "雾沼水蛭")
    assert ctx["event_counts"][EVENT_KEY_CODEX_NEW] == {"雾沼水蛭": 1}
    e = _log_of(ctx)[0]
    assert e["tag"] == "codex_new"
    assert e["params"]["entry"] == "雾沼水蛭"


def test_empty_args_no_write() -> None:
    """空参 → ok=False，不写任何表。"""
    for fn, args in (
        (log_first_kill, ("",)),
        (log_first_crown, ("",)),
        (log_story_node, ("",)),
        (log_hidden_find, ("",)),
        (log_milestone, (None,)),
        (log_codex_new, ("",)),
    ):
        ctx = _mk_ctx()
        res = fn(ctx, *args)
        assert res["ok"] is False
        assert ctx["event_counts"] == {}
        assert ctx["longline_counters"] == {}


def test_event_key_conventions() -> None:
    """六类事件键约定（R-02 语义，full 条件形态）。"""
    assert event_key_first_kill("蚀月之狼") == "[事件:首杀:蚀月之狼]"
    assert event_key_first_crown("鲤鱼") == "[事件:首钓冠级:鲤鱼]"
    assert event_key_story_node("q3") == "[事件:任务完成:q3]"
    assert event_key_hidden_find("HID_01") == "[事件:隐藏发现:HID_01]"
    assert event_key_milestone(50) == "[事件:里程碑:50]"
    assert event_key_codex_new("雾沼水蛭") == "[事件:图鉴新增:雾沼水蛭]"


# ---------------------------------------------------------------------------
# 分组分页（R-03：组序固定、组内倒序、每页 5 条、越界回落、空组不渲染）
# ---------------------------------------------------------------------------
def _seed(ctx: dict, tag: str, n: int) -> None:
    """以固定 tag 追加 n 条（追加序=时间序，反转=组内倒序）。"""
    for i in range(n):
        bump_event(ctx, f"[事件:种子:{tag}:{i}]", instance={"tag": tag, "params": {"i": i}})


def test_read_log_group_order_and_reverse_within_group() -> None:
    """组序固定（首杀→首钓冠级→剧情节点→隐藏发现→里程碑→图鉴新增）；组内倒序。"""
    ctx = _mk_ctx()
    _seed(ctx, "milestone", 2)     # 追加序 0,1
    _seed(ctx, "first_kill", 2)    # 追加序 2,3
    _seed(ctx, "codex_new", 1)     # 追加序 4
    out = read_log(ctx)
    # 固定组序：first_kill 在前
    assert list(out["entries"].keys()) == ["first_kill", "milestone", "codex_new"]
    assert out["order"] == [
        "first_kill", "first_crown", "story_node", "hidden_find", "milestone", "codex_new",
    ]
    # 组内倒序：first_kill 组 i 由新到旧
    assert [e["params"]["i"] for e in out["entries"]["first_kill"]] == [1, 0]
    assert [e["params"]["i"] for e in out["entries"]["milestone"]] == [1, 0]


def test_read_log_pagination_5_per_page_and_clamp() -> None:
    """每页 5 条；越界回落最末页。"""
    ctx = _mk_ctx()
    _seed(ctx, "milestone", 4)
    _seed(ctx, "first_kill", 8)
    total = 12
    out = read_log(ctx)
    assert out["total"] == total
    assert out["pages"] == 3
    assert out["page"] == 1
    count1 = sum(len(v) for v in out["entries"].values())
    assert count1 == 5
    # 页 2、页 3（越界回落最末页）
    p2 = read_log(ctx, page=2)
    assert sum(len(v) for v in p2["entries"].values()) == 5
    p3 = read_log(ctx, page=3)
    assert sum(len(v) for v in p3["entries"].values()) == 2
    assert p3["page"] == 3
    # 越界回落最末页（99 → 3）
    p99 = read_log(ctx, page=99)
    assert p99["page"] == 3
    # 页内条目不重复、无遗漏（三页合并 = 全量 12 条；event_id 全局唯一）
    seen_ids: list = []
    for pg in (read_log(ctx), p2, p3):
        for lst in pg["entries"].values():
            seen_ids.extend(e["event_id"] for e in lst)
    assert len(seen_ids) == 12
    assert len(set(seen_ids)) == 12


def test_read_log_tag_filter() -> None:
    """tag 过滤：只返回该类条目。"""
    ctx = _mk_ctx()
    _seed(ctx, "first_kill", 3)
    _seed(ctx, "milestone", 2)
    out = read_log(ctx, tag="milestone")
    assert out["total"] == 2
    assert list(out["entries"].keys()) == ["milestone"]


def test_read_log_non_six_tag_excluded() -> None:
    """非六类 tag（N-03 预置 tag=event）不进入六类分组（R-03 只展示六类）。"""
    ctx = _mk_ctx()
    bump_event(ctx, "[事件:签到]", instance={"tag": "event"})
    out = read_log(ctx)
    assert out["total"] == 0
    assert out["entries"] == {}
    assert out["pages"] == 1


def test_read_log_empty() -> None:
    """空日志 → 空分组，page/pages 回落 1。"""
    out = read_log(_mk_ctx())
    assert out["entries"] == {}
    assert out["total"] == 0
    assert out["page"] == 1
    assert out["pages"] == 1


def test_read_log_snapshot_passthrough() -> None:
    """R-05：条目快照（season/period/weather）随展示透传。"""
    ctx = _mk_ctx(season="冬", period="黄昏", weather="晴")
    log_first_kill(ctx, "蚀月之狼")
    out = read_log(ctx)
    e = out["entries"]["first_kill"][0]
    assert e["snapshot"] == {"season": "冬", "period": "黄昏", "weather": "晴"}


# ---------------------------------------------------------------------------
# 环形容量（3f E-01 / D-01：300 可配，写满覆盖最旧）
# ---------------------------------------------------------------------------
def test_ring_capacity_trim() -> None:
    """settings.event_log_capacity 可配环形；写满覆盖最旧（引擎侧经 bump_event）。"""
    ctx = _mk_ctx(settings={"event_log_capacity": 5})
    for i in range(8):
        log_milestone(ctx, i)
    log = _log_of(ctx)
    assert len(log) == 5
    # 最旧 0-2 被覆盖，最新 7 保留
    assert log[-1]["params"]["pct"] == "7"
    assert log[0]["params"]["pct"] == "3"


# ---------------------------------------------------------------------------
# N-04 RN-11：dialog_session 30 天惰性清理
# ---------------------------------------------------------------------------
def _snap_ctx(last_at: object) -> dict:
    """含 dialog_session 快照的 ctx（last_active_at 可注入）。"""
    return {
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {
            DIALOG_SNAPSHOT_KEY: {
                "state": "menu",
                "npc_id": "blacksmith",
                "last_active_at": last_at,
            },
        },
        "settings": {},
    }


def test_cleanup_expired_snapshot() -> None:
    """last_active_at 超 30 天 → 清除，返回 True。"""
    ctx = _snap_ctx("2026-07-01T12:00:00+00:00")  # 58 天前
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is True
    assert DIALOG_SNAPSHOT_KEY not in ctx["persistent_state"]


def test_cleanup_recent_snapshot_kept() -> None:
    """未超 30 天 → 保留，返回 False。"""
    ctx = _snap_ctx("2026-08-20T12:00:00+00:00")  # 8 天前
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is False
    assert DIALOG_SNAPSHOT_KEY in ctx["persistent_state"]


def test_cleanup_no_timestamp_kept() -> None:
    """无 last_active_at/last_active → 保留（不误删旧快照）。"""
    ctx = {
        "persistent_state": {DIALOG_SNAPSHOT_KEY: {"state": "menu"}},
        "settings": {},
    }
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is False
    assert DIALOG_SNAPSHOT_KEY in ctx["persistent_state"]


def test_cleanup_last_active_fallback() -> None:
    """last_active 兜底键（RN-11 兼容旧字段）。"""
    ctx = {
        "persistent_state": {DIALOG_SNAPSHOT_KEY: {"last_active": "2026-06-01T00:00:00"}},
        "settings": {},
    }
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is True


def test_cleanup_numeric_epoch() -> None:
    """数值 epoch（秒/毫秒）解析。"""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=60)).timestamp()
    ctx = {"persistent_state": {DIALOG_SNAPSHOT_KEY: {"last_active_at": old}}}
    assert cleanup_dialog_snapshot(ctx, now=now) is True
    # 毫秒形态
    ctx2 = {"persistent_state": {DIALOG_SNAPSHOT_KEY: {"last_active_at": old * 1000}}}
    assert cleanup_dialog_snapshot(ctx2, now=now) is True


def test_cleanup_non_mapping_snapshot_kept() -> None:
    """dialog_session 非 Mapping（如恢复实例/None）→ 不清理。"""
    ctx = {"persistent_state": {DIALOG_SNAPSHOT_KEY: None}, "settings": {}}
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is False
    ctx2 = {"persistent_state": {}, "settings": {}}  # type: ignore[var-annotated]
    assert cleanup_dialog_snapshot(ctx2, now=now) is False


def test_cleanup_player_container() -> None:
    """容器定位：ctx["player"].persistent_state（装配层形态）。"""
    player = {"persistent_state": {
        DIALOG_SNAPSHOT_KEY: {"last_active_at": "2026-07-01T00:00:00+00:00"},
    }}
    ctx = {"player": player, "settings": {}}
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is True
    assert DIALOG_SNAPSHOT_KEY not in player["persistent_state"]


def test_cleanup_now_injected_from_ctx() -> None:
    """now 由 ctx["now"] 注入（确定性）。"""
    ctx = _snap_ctx("2026-07-01T00:00:00+00:00")
    ctx["now"] = "2026-08-28T12:00:00+08:00"
    assert cleanup_dialog_snapshot(ctx) is True


def test_cleanup_ttl_configurable() -> None:
    """ttl_days 可配（如 7 天）。"""
    ctx = _snap_ctx("2026-08-20T00:00:00+00:00")  # 8 天前
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now, ttl_days=7) is True
    assert DIALOG_SNAPSHOT_TTL_DAYS == 30


def test_cleanup_npc_marks_untouched() -> None:
    """npc_heard/npc_delivered 常驻标记与快照分离（清理不动它们）。"""
    ctx = {
        "persistent_state": {
            DIALOG_SNAPSHOT_KEY: {"last_active_at": "2026-07-01T00:00:00+00:00"},
            "npc_heard": ["intro1"],
            "npc_delivered": {"intel:ref1": True},
        },
        "settings": {},
    }
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert cleanup_dialog_snapshot(ctx, now=now) is True
    assert ctx["persistent_state"]["npc_heard"] == ["intro1"]
    assert ctx["persistent_state"]["npc_delivered"] == {"intel:ref1": True}