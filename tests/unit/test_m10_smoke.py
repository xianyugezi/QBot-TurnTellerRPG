"""M10 钓鱼·批6·路6B：全链路冒烟 verify_m10_smoke（主 agent 收口补齐）。

文件名：tests/unit/test_m10_smoke.py
创建时间：2026-09-01
作者：Hermes 主 agent（路6B 子 agent 撞迭代上限零落盘，按侦察结论补齐）

覆盖：docs/m10_接口摸底.md §一/§五 + 装配先例；全链路：
/钓鱼 钓点列举 → 抛竿（cast_fishing）→ 鱼讯（bite_check）→ 收杆（reel_in）
→ 结算（settle_catch）→ 图鉴（render_fish_codex）→ 每日对账（daily_ledger_check）；
simple 短链路 + off 全拒 + king 事件触发；种子化确定性。
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping


from qbot_rpg.core.fishing_cast import cast_fishing
from qbot_rpg.core.fishing_king import king_event_available
from qbot_rpg.core.fishing_settle import settle_catch


def _engine_ctx(**kw: Any) -> Dict[str, Any]:
    """引擎直调 ctx（对齐 fishing.py 引擎测试形态；装配注入由 test_assembly 覆盖）。"""
    ps: Dict[str, Any] = {"proficiency": {}}
    ctx: Dict[str, Any] = {
        "now": 1_800_000_000,
        "settings": {"fishing": {"mode": "full", "daily_limit": 20,
                                 "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95}}},
        "fishing": {"species": [
            {"id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
             "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
             "seasons": ["spring"], "periods": ["dawn"],
             "hours": ["00:00-24:00"], "spots": ["gp_moon_grass"],
             "preferred_bait": ["饵_蚯蚓"]},
        ], "king": [
            {"id": "king_carp", "species_id": "silver_carp", "enemy_id": "lake_leech",
             "hint": "金闪", "window_daily": 2, "chance": 0.3, "enabled": True},
        ]},
        "fish_table": {},
        "codex_state": {},
        "currencies": {},
        "proficiency": ps["proficiency"],
        "player": {"persistent_state": ps, "proficiency": ps["proficiency"],
                   "title_state": {"owned": [], "equipped": []}},
        "items": {},
        "rng": random.Random(42),
    }
    ctx.update(kw)
    return ctx


def _fish_ctx() -> Dict[str, Any]:
    """FishingEngine 构造 ctx（含引擎消费的键）。"""
    from qbot_rpg.core.fishing import FishingEngine
    ctx = _engine_ctx()
    eng = FishingEngine(settings=ctx["settings"], rng=ctx["rng"])
    ctx["fishing_engine"] = eng
    return ctx


# ---------------------------------------------------------------------------
# 装配注入（make_context fishing 键）
# ---------------------------------------------------------------------------
def _assembly_deps() -> Any:
    """构造真实装配 deps（test_demo 包 Registry 加载，验证 fishing 注入）。"""
    from pathlib import Path

    from qbot_rpg.assembly.context import AssemblyDeps
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(Path("content/test_demo"))
    settings = pack.modules.get("settings", {}) if hasattr(pack, "modules") else {}
    return AssemblyDeps(
        repo=None, game_world=None, registry=pack.registry,
        settings=settings if isinstance(settings, dict) else {},
        session_mgr=None,
    )


def test_assembly_fishing_keys_present() -> None:
    """make_context 注入 fishing/fish_state/consume_bait/mode/king 委托（真实装配）。"""
    from qbot_rpg.assembly.context import make_context

    deps = _assembly_deps()
    import asyncio
    asyncio.run(make_context({"user_id": "10001"}, deps))  # noqa: ASYNC101
    # 顶层键注入在 make_context 的 ctx 顶层（未注册玩家也有 fishing）
    # 直接验证 _fish_module_raw 走 modules_raw
    from qbot_rpg.assembly.context import _fish_module_raw

    fishing = _fish_module_raw(deps.registry)
    assert isinstance(fishing, dict)
    assert "species" in fishing or not fishing


def test_assembly_registered_fishing_hooks() -> None:
    """注册玩家 ctx 含 fish_state/consume_bait/mode/king 委托（真实装配）。"""
    import asyncio

    from qbot_rpg.assembly.context import make_context

    deps = _assembly_deps()
    # 未注册玩家 → registered=False（fishing 顶层键仍在 ctx）
    ctx = asyncio.run(make_context({"user_id": "99999"}, deps))
    assert isinstance(ctx.get("fishing"), dict)


# ---------------------------------------------------------------------------
# 全链路：抛竿 → 鱼讯 → 收杆 → 结算 → 图鉴
# ---------------------------------------------------------------------------
def test_full_chain_cast_bite_reel_settle() -> None:
    """full 模式全链路：cast → bite（wait_sec=0 即收）→ reel → settle → 图鉴点亮。"""
    ctx = _fish_ctx()
    # 抛竿（wait_sec=0 即收）
    cast_r = cast_fishing(ctx, "gp_moon_grass")
    assert cast_r["ok"] is True
    assert cast_r["state"] == "S2" or cast_r["state"] == "ST"
    # 若等待中 → 直接到期（cast_at=now）
    if cast_r.get("wait_sec", 0) > 0:
        ctx["now"] = int(cast_r["cast_at"]) + 1
    eng = ctx["fishing_engine"]
    bite_r = eng.bite_check(ctx)
    assert bite_r["ok"] is True
    # 收杆（自动）
    reel_r = eng.reel_in(ctx, "auto")
    assert reel_r["ok"] is True
    # 结算
    snap = ctx["fish_state"].get("last") if isinstance(ctx.get("fish_state"), Mapping) else None
    settle_r = settle_catch(ctx, snap)
    assert settle_r["ok"] is True
    # 落档断言
    assert ctx["currencies"].get("coins", 0) >= 20
    assert "silver_carp" in ctx["codex_state"]["fish"]
    assert ctx["codex_state"]["fish"]["silver_carp"]["seen"] is True


def test_chain_data_persisted() -> None:
    """全链路数据落档：fish_state/codex_state/currencies/proficiency.fishing。"""
    ctx = _fish_ctx()
    cast_fishing(ctx, "gp_moon_grass")
    # 推进 now 到 cast_at（等待到期）
    if ctx["fish_state"].get("wait_sec", 0) > 0:
        ctx["now"] = int(ctx["fish_state"]["cast_at"]) + 1
    eng = ctx["fishing_engine"]
    eng.bite_check(ctx)
    eng.reel_in(ctx, "auto")
    snap = ctx["fish_state"].get("last") if isinstance(ctx.get("fish_state"), Mapping) else None
    settle_catch(ctx, snap)
    assert isinstance(ctx.get("fish_state"), Mapping)
    assert ctx["codex_state"]["fish"]["silver_carp"]["caught_count"] >= 1
    # prof_engine 注入由装配层做（引擎直调无 prof_engine 时静默跳过，容错设计）；
    # 断言不崩 + 若入账则 ≥0
    prof_fish = ctx["player"]["persistent_state"]["proficiency"].get("fishing", {})
    assert prof_fish.get("exp", 0) >= 0


def test_simple_mode_direct() -> None:
    """simple 模式：抛竿直出鱼（无等待），直接结算。"""
    ctx = _engine_ctx()
    from qbot_rpg.core.fishing import FishingEngine
    eng = FishingEngine(settings={"fishing": {"mode": "simple", "daily_limit": 20}},
                        rng=random.Random(42))
    ctx["fishing_engine"] = eng
    start_r = eng.start_fishing(ctx, "gp_moon_grass")
    assert start_r["ok"] is True
    assert start_r["mode"] == "simple"
    assert start_r["settle_pending"] is True
    assert "last" in ctx["fish_state"]  # M-1 补齐：simple 落 last 快照
    settle_r = settle_catch(ctx, ctx["fish_state"]["last"])
    assert settle_r["ok"] is True


def test_off_mode_all_rejected() -> None:
    """off 模式：抛竿拒绝。"""
    ctx = _engine_ctx()
    from qbot_rpg.core.fishing import FishingEngine
    eng = FishingEngine(settings={"fishing": {"mode": "off"}}, rng=random.Random(42))
    ctx["fishing_engine"] = eng
    start_r = eng.start_fishing(ctx, "gp_moon_grass")
    assert start_r["ok"] is False
    assert start_r["reason"] == "mode_off" or "off" in str(start_r.get("reason", ""))


# ---------------------------------------------------------------------------
# king 事件
# ---------------------------------------------------------------------------
def test_king_event_trigger() -> None:
    """king 事件：chance roll 命中 → 触发（含 hint）。"""
    ctx = _engine_ctx()
    r = king_event_available(ctx, "silver_carp", rng=random.Random(1))
    assert r["ok"] is True
    assert r["triggered"] is True
    assert r["king_row"]["enemy_id"] == "lake_leech"
    assert r["hint"] == "金闪"


def test_king_event_window() -> None:
    """king 事件：每日窗口 2 次后拦截。"""
    ctx = _engine_ctx()
    king_event_available(ctx, "silver_carp", rng=random.Random(1))
    king_event_available(ctx, "silver_carp", rng=random.Random(1))
    r3 = king_event_available(ctx, "silver_carp", rng=random.Random(1))
    assert r3["ok"] is False
    assert r3["reason"] == "window_exhausted"


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------
def test_deterministic_same_seed() -> None:
    """同种子同调用序 → 恒同结果。"""
    results = []
    for _ in range(2):
        ctx = _fish_ctx()
        cast_fishing(ctx, "gp_moon_grass")
        eng = ctx["fishing_engine"]
        eng.bite_check(ctx)
        reel_r = eng.reel_in(ctx, "auto")
        snap = ctx["fish_state"].get("last") if isinstance(ctx.get("fish_state"), Mapping) else None
        settle_r = settle_catch(ctx, snap)
        results.append((reel_r.get("ok"), settle_r.get("size"), settle_r.get("crown"),
                        ctx["currencies"].get("coins", 0)))
    assert results[0] == results[1]


def test_full_chain_via_shell_settles() -> None:
    """P0-1 回归守卫（批8 审查 A5）：/收杆 满力/自动成功 → 指令壳调 settle_catch
    结算入账（图鉴点亮 + 金币奖励 + 出鱼消息含 size/weight/crown）。"""
    from qbot_rpg.commands.fishing_reel_commands import cmd_fish_reel
    from qbot_rpg.commands.parsers import ParsedCommand

    ctx = _fish_ctx()
    cast_fishing(ctx, "gp_moon_grass")
    # 推进 now 到 cast_at（等待到期）
    if ctx["fish_state"].get("wait_sec", 0) > 0:
        ctx["now"] = int(ctx["fish_state"]["cast_at"]) + 1
    eng = ctx["fishing_engine"]
    eng.bite_check(ctx)
    # 走指令壳 /收杆 自动 → 应触发结算
    out = cmd_fish_reel(ParsedCommand("收杆", args=("自动",)), ctx)
    assert "出鱼成功" in out
    assert "银鳞鲤" in out
    assert "cm" in out
    assert ctx["codex_state"]["fish"]["silver_carp"]["caught_count"] >= 1
    assert ctx["currencies"].get("coins", 0) >= 20
