"""图鉴里程碑阶梯测试（tests/unit/test_codex_milestones.py · M7 BCH-08 批次 3f · F-12/F-13）。

覆盖：五档里程碑触发（R-20，累计语义——达 50% 连授 25/50）/ 称号位授予与升级
覆盖（R-21）/ 授予幂等（E-05/D-07）/ 跨档连升逐档触发（R-21 跨档跳升）/
90% 软锚（R-18 唯一明示例外）/ 100% 三件套：收藏家称号 + 世界之书聚合段 +
隐藏神龛（R-19）/ 完成度读取兜底（ctx["codex"] 标量优先 + 惰性 codex_progress
未落盘 → 0）/ today 注入确定性。

铁律：零 NoneBot import；纯函数确定性；无 emoji。
"""

from __future__ import annotations

from qbot_rpg.core.adventure_log import (
    ADVENTURE_LOG_TAGS,
    log_codex_new,
    log_first_crown,
    log_first_kill,
    log_hidden_find,
    log_milestone,
    log_story_node,
)
from qbot_rpg.core.codex_milestones import (
    COLLECTOR_TITLE,
    CODE_X_MILESTONES_KEY,
    HIDDEN_SHRINE_KEY,
    MILESTONE_DEFS,
    MILESTONE_PCTS,
    check_milestones,
)
from qbot_rpg.core.event_bus import EVENT_LOG_KEY

MILESTONE_TAG = "milestone"


def _mk_ctx(codex: object = None, *, player: bool = True, **over: object) -> dict:
    """确定性 ctx：codex 完成度标量 + 三表 + persistent_state + player（title_state）。

    player=True → ctx["player"] = {"title_state": {}, "persistent_state": 同容器}，
    验证称号位 title_state["current"] 写入。
    """
    ctx: dict = {
        "codex": codex,
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {},
        "settings": {},
        "season": "秋",
        "period": "午夜",
        "weather": "雷雨",
        "now": "2026-08-28T22:40:00+08:00",
    }
    if player:
        ctx["player"] = {"title_state": {}, "persistent_state": ctx["persistent_state"]}
    ctx.update(over)
    return ctx


def _ps(ctx: dict) -> dict:
    """persistent_state 容器（测试写入口）。"""
    return ctx["persistent_state"]


def _event_log(ctx: dict) -> list:
    """event_log 读取（persistent_state 落点，对齐 bump_event._log_list_of）。"""
    return _ps(ctx).get(EVENT_LOG_KEY, [])


def _milestone_log_count(ctx: dict, pct: int) -> int:
    """[事件:里程碑] 冒险日志条目数（log_milestone 写入，按 params.pct 计数）。

    bump_event 的 longline_counters 按 base 键（[事件:里程碑]）累计而非嵌套全键，
    故以 event_log 条目 tag+params.pct 判定 log_milestone 实际写入次数。
    """
    return sum(
        1
        for e in _event_log(ctx)
        if e.get("tag") == MILESTONE_TAG
        and str((e.get("params") or {}).get("pct")) == str(pct)
    )


def _granted(ctx: dict) -> list:
    """persistent_state 已授予集合（升序 list）。"""
    return list(_ps(ctx).get(CODE_X_MILESTONES_KEY, []))


# ---------------------------------------------------------------------------
# 五档触发（R-20，累计语义：达档即授予该档及以下未授档）
# ---------------------------------------------------------------------------
def test_below_25_no_milestone() -> None:
    """pct < 25（如 24）→ 无授予、无消息、无日志、称号位不动。"""
    ctx = _mk_ctx(codex=24)
    r = check_milestones(ctx, today="2026-08-28")
    assert r == {"granted": [], "message": ""}
    assert _granted(ctx) == []
    assert _milestone_log_count(ctx, 25) == 0
    assert ctx["player"]["title_state"] == {}


def test_each_tier_grants_own_title() -> None:
    """达 25/50/75/90 → 末档授予对应称号（收藏新手/收藏家/资深收藏家/收藏大师）。"""
    expect = {25: "收藏新手", 50: "收藏家", 75: "资深收藏家", 90: "收藏大师"}
    for pct, tier in expect.items():
        ctx = _mk_ctx(codex=pct)
        r = check_milestones(ctx, today="2026-08-28")
        # 累计语义：达 pct 档即连授全部 ≤pct 未授档（25 起，逐档）
        assert [g["pct"] for g in r["granted"]] == [
            int(d["pct"]) for d in MILESTONE_DEFS if int(d["pct"]) <= pct
        ], pct
        g = r["granted"][-1]  # 末档即本档
        assert g["milestone"] == f"codex_milestone_{pct}"
        assert g["tier"] == tier
        assert str(pct) in g["message"]
        assert g["title_written"] is True
        assert ctx["player"]["title_state"]["current"] == tier
        assert ctx["title"] == tier
        assert _milestone_log_count(ctx, pct) == 1


# ---------------------------------------------------------------------------
# 授予幂等（E-05 / D-07）与升级覆盖（R-21）
# ---------------------------------------------------------------------------
def test_idempotent_recheck_no_regrant() -> None:
    """重复达档不重授：codex=50 两次检查 → 第二次无授予、不重复写日志、称号不变。"""
    ctx = _mk_ctx(codex=50)
    r1 = check_milestones(ctx, today="2026-08-28")
    assert [g["pct"] for g in r1["granted"]] == [25, 50]
    r2 = check_milestones(ctx, today="2026-08-28")
    assert r2 == {"granted": [], "message": ""}
    assert _granted(ctx) == ["25", "50"]
    assert _milestone_log_count(ctx, 50) == 1
    assert _milestone_log_count(ctx, 25) == 1
    assert ctx["player"]["title_state"]["current"] == "收藏家"


def test_tier_upgrade_overwrites_title() -> None:
    """低→高连达：25 后 50 → 称号从收藏新手覆盖为收藏家（升级可覆盖）。"""
    ctx = _mk_ctx(codex=25)
    check_milestones(ctx, today="2026-08-28")
    assert ctx["player"]["title_state"]["current"] == "收藏新手"
    ctx["codex"] = 50
    r = check_milestones(ctx, today="2026-08-28")
    assert [g["pct"] for g in r["granted"]] == [50]
    assert ctx["player"]["title_state"]["current"] == "收藏家"
    assert _granted(ctx) == ["25", "50"]


# ---------------------------------------------------------------------------
# 跨档连升逐档触发（R-21 跨档跳升语义）
# ---------------------------------------------------------------------------
def test_cross_tier_leap_grants_each() -> None:
    """完成度 20%→60% 一次跨越 25/50 → 逐档连授（升序），各写一次日志。"""
    ctx = _mk_ctx(codex=60)
    r = check_milestones(ctx, today="2026-08-28")
    assert [g["pct"] for g in r["granted"]] == [25, 50]
    assert ctx["player"]["title_state"]["current"] == "收藏家"
    assert _granted(ctx) == ["25", "50"]
    assert _milestone_log_count(ctx, 25) == 1
    assert _milestone_log_count(ctx, 50) == 1
    assert "收藏新手" in r["granted"][0]["message"]
    assert "收藏家" in r["granted"][1]["message"]


def test_gradual_cross_tier_only_new() -> None:
    """渐进跳档：25 已授后 codex=60 → 只授 50（25 不重授，跨档逐档触发）。"""
    ctx = _mk_ctx(codex=25)
    check_milestones(ctx, today="2026-08-28")
    ctx["codex"] = 60
    r = check_milestones(ctx, today="2026-08-28")
    assert [g["pct"] for g in r["granted"]] == [50]
    assert _milestone_log_count(ctx, 50) == 1
    assert _milestone_log_count(ctx, 25) == 1  # 不重授


# ---------------------------------------------------------------------------
# 90% 软锚（R-18 唯一明示例外）
# ---------------------------------------------------------------------------
def test_pct_90_soft_anchor() -> None:
    """90% 档 message 显式含「全收集还有更深处」；其余档不含（零明示）。"""
    ctx = _mk_ctx(codex=90)
    r = check_milestones(ctx, today="2026-08-28")
    assert r["granted"][-1]["pct"] == 90
    assert "全收集还有更深处" in r["granted"][-1]["message"]
    for pct in (25, 50, 75):
        c2 = _mk_ctx(codex=pct)
        r2 = check_milestones(c2, today="2026-08-28")
        for g in r2["granted"]:
            assert "全收集还有更深处" not in g["message"], pct


# ---------------------------------------------------------------------------
# 100% 三件套（R-19）：收藏家称号 + 世界之书聚合段 + 隐藏神龛
# ---------------------------------------------------------------------------
def _ctx_with_full_log(codex: object = 100) -> dict:
    """预填 event_log 六类各 1 条的 ctx（首杀/首钓/剧情/隐藏/里程碑/图鉴新增）。"""
    ctx = _mk_ctx(codex=codex)
    log_first_kill(ctx, "蚀月之狼", monster_id="m1")
    log_first_crown(ctx, "金冠鲤", fish_id="f1")
    log_story_node(ctx, "主线-序章", name="序章")
    log_hidden_find(ctx, "h1")
    log_milestone(ctx, 25)
    log_codex_new(ctx, "e1")
    return ctx


def test_pct_100_three_piece() -> None:
    """100% 三件套：收藏家称号 + 世界之书聚合段（六类计数）+ 隐藏神龛标记。

    世界之书在五档授予后聚合：预填 6 条 + 本批 5 档 log_milestone = 11 条
    （milestone 类 6 条，其余五类各 1 条）。
    """
    ctx = _ctx_with_full_log(100)
    r = check_milestones(ctx, today="2026-08-28")
    assert [g["pct"] for g in r["granted"]] == [25, 50, 75, 90, 100]
    g100 = r["granted"][-1]
    assert g100["pct"] == 100
    assert g100["tier"] == COLLECTOR_TITLE == "收藏家"
    # 称号位 = 收藏家（三件套第 1 件）
    assert ctx["player"]["title_state"]["current"] == "收藏家"
    # 隐藏神龛（第 3 件）
    assert _ps(ctx).get(HIDDEN_SHRINE_KEY) is True
    # 世界之书聚合段（第 2 件）：六类固定组序 + 计数（6 预填 + 5 档授予 = 11）
    wb = g100["world_book"]["world_book"]
    assert wb["total"] == 11
    assert [c["tag"] for c in wb["categories"]] == list(ADVENTURE_LOG_TAGS)
    by_tag = {c["tag"]: c["count"] for c in wb["categories"]}
    assert by_tag["milestone"] == 6
    assert by_tag["first_kill"] == 1
    assert by_tag["first_crown"] == 1
    assert by_tag["story_node"] == 1
    assert by_tag["hidden_find"] == 1
    assert by_tag["codex_new"] == 1
    assert "世界之书已载入 11 条冒险见证" in g100["message"]
    assert "全收集还有更深处" in r["message"]
    # 100 档 milestone 日志写入（log_milestone）
    assert _milestone_log_count(ctx, 100) == 1
    assert _granted(ctx) == ["25", "50", "75", "90", "100"]


def test_pct_100_empty_log_world_book() -> None:
    """100% 且 event_log 仅含本批 5 档授予日志 → 世界之书 total=5（milestone 类 5 条）。"""
    ctx = _mk_ctx(codex=100)
    r = check_milestones(ctx, today="2026-08-28")
    g100 = r["granted"][-1]
    wb = g100["world_book"]["world_book"]
    assert wb["total"] == 5
    assert wb["categories"][4]["tag"] == "milestone"
    assert wb["categories"][4]["count"] == 5
    assert "世界之书已载入 5 条冒险见证" in g100["message"]
    assert _ps(ctx).get(HIDDEN_SHRINE_KEY) is True


def test_pct_100_idempotent() -> None:
    """100% 重复检查：不重授、不重复写日志、隐藏神龛保持 true。"""
    ctx = _mk_ctx(codex=100)
    r1 = check_milestones(ctx, today="2026-08-28")
    assert len(r1["granted"]) == 5
    r2 = check_milestones(ctx, today="2026-08-28")
    assert r2 == {"granted": [], "message": ""}
    assert _milestone_log_count(ctx, 100) == 1
    assert _milestone_log_count(ctx, 50) == 1
    assert _ps(ctx).get(HIDDEN_SHRINE_KEY) is True


# ---------------------------------------------------------------------------
# 完成度读取兜底（ctx["codex"] 优先 / 惰性 codex_progress 未落盘 → 0）
# ---------------------------------------------------------------------------
def test_codex_scalar_variants() -> None:
    """ctx["codex"] 支持 int/float/str 标量（累计达档）；88 不达 90 档不授予。"""
    for codex in (50, 50.0, "50"):
        ctx = _mk_ctx(codex=codex)
        r = check_milestones(ctx, today="2026-08-28")
        assert [g["pct"] for g in r["granted"]] == [25, 50], codex
        assert r["granted"][-1]["pct"] == 50, codex
    ctx88 = _mk_ctx(codex=88)
    r88 = check_milestones(ctx88, today="2026-08-28")
    # 88 达 25/50/75 档（累计授予），但未达 90 档（不授予 90）
    assert [g["pct"] for g in r88["granted"]] == [25, 50, 75]
    assert r88["granted"][-1]["pct"] == 75


def test_codex_absent_no_exception() -> None:
    """ctx 无 codex 键（兄弟路 codex.py 未落盘 → 惰性 import 兜底 0）→ 不抛异常。"""
    ctx = _mk_ctx(codex=None)
    del ctx["codex"]
    r = check_milestones(ctx, today="2026-08-28")
    assert r == {"granted": [], "message": ""}


# ---------------------------------------------------------------------------
# today 注入确定性 / 无 player 兜底
# ---------------------------------------------------------------------------
def test_today_injection() -> None:
    """today 入参注入 ctx["today"] 并透传授予记录（确定性）。"""
    ctx = _mk_ctx(codex=25)
    r = check_milestones(ctx, today="2026-08-28")
    assert ctx["today"] == "2026-08-28"
    assert r["granted"][0]["today"] == "2026-08-28"
    assert "2026-08-28" in _event_log(ctx)[-1]["ts"]


def test_no_player_title_skipped_but_granted() -> None:
    """无 player（未注册/裸 ctx）→ 称号位不写（title_written=False），授予仍生效。"""
    ctx = _mk_ctx(codex=50, player=False)
    r = check_milestones(ctx, today="2026-08-28")
    assert r["granted"][-1]["pct"] == 50
    assert r["granted"][-1]["title_written"] is False
    assert _granted(ctx) == ["25", "50"]
    assert _milestone_log_count(ctx, 50) == 1


def test_public_constants() -> None:
    """公开常量契约：五档升序 / 收集家称号 / 存储键。"""
    assert MILESTONE_PCTS == (25, 50, 75, 90, 100)
    assert [int(d["pct"]) for d in MILESTONE_DEFS] == [25, 50, 75, 90, 100]
    assert COLLECTOR_TITLE == "收藏家"
    assert CODE_X_MILESTONES_KEY == "codex_milestones"
    assert HIDDEN_SHRINE_KEY == "hidden_shrine"
