"""M10 批2·路2B：抛竿 + 鱼讯 接线服务单测（tests/unit/test_fishing_cast.py）。

文件名：tests/unit/test_fishing_cast.py
创建时间：2026-08-31
作者：Hermes 子agent-2B（M10 钓鱼实现组批2·路2B：抛竿 + 鱼讯 接线服务）

功能：qbot_rpg.core.fishing_cast 纯函数直测（零 NoneBot、确定性、零定时器/零睡眠——
      懒计算时间戳判、无实时倒计时）：
  - resolve_spot：精确/唯一前缀/歧义/未找到/空/非 str（对齐 M9 resolve 三态）
  - cast_fishing：下钩成功消息（钓点/等待时长/日计数/饵使用情况）；无饵保底（bait_used
    None → 无饵行）；日计数展示；wait_sec=0 即收提示（TC-07）；守卫透传（GU-01 off /
    GU-02 日限 / GU-03 未找到/歧义 / GU-04 会话进行中）
  - bite_trigger：未到期等待中（钓点/已耗时/等待中，TC-21）；到期三类（normal→微动 /
    rare→拉扯 / gold→猛烈，TC-10~12）+ 收杆提醒（TC-22）；金闪覆写位默认 False、
    king_hit=True 仅猛烈携带金闪（TC-13 微动/拉扯永不金闪）；无钓局/off 拒绝
  - 引擎复用：ctx["fishing_engine"] 注入复用 / 缺省自建兜底（构造器注入 settings+rng）
  - fish_intent_of 复用 fishing.py 内实现（本路 import 自 fishing_cast，断言非重写）
  - fish_state 持久化：cast_fishing 写 ctx["fish_state"] 即挂 player.persistent_state

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §一 1.2（下钩 T06：GU-01~04 + 扣饵/日计数/
    懒计时期）/ §三（鱼讯三类 §3.1 rarity→讯类映射 + §3.3 金闪覆写 + §3.4 决策窗）/
    §五（/鱼讯 推进 TC-21/22）/ §六 验收 TC-03/04/07/10~13/21/22
  - docs/m10_接口摸底.md §一（harvest_at 懒判）/ §二（fish_intent_of rarity 直接映射）/
    §八-3（ctx fish_table 注入）/ §九（rng 注入、零定时器）
  - 模式参考：tests/unit/test_fishing.py（引擎直测风格：_ctx/_engine 夹具）/
    tests/unit/test_forge_tree.py（resolve 三态断言风格）
"""
from __future__ import annotations

import random
from typing import Any, Dict, MutableMapping

from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.fishing import FishingEngine, fish_intent_of
from qbot_rpg.core.fishing_cast import (
    MSG_CAST_IMMEDIATE,
    MSG_CAST_OK,
    MSG_REEL_HINT,
    STATE_BITE,
    STATE_IDLE,
    STATE_WAITING,
    _engine_of,
    bite_trigger,
    cast_fishing,
    resolve_spot,
)

# =====================================================================================
# 夹具
# =====================================================================================

SPOT = "gp_moon_grass"          # 已知钓点（银鳞鲤/赤纹泥鳅/金鳞鲤共用）
SPOT_OTHER = "deep_lake"        # 其它已知钓点（深渊巨鲸独占）
SPOT_PREFIX = "gp_"             # 前缀唯一命中（仅 gp_moon_grass 以 gp_ 开头）

SPECIES_RAW: Dict[str, Dict[str, Any]] = {
    "silver_carp": {
        "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
        "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
        "spots": [SPOT], "preferred_bait": ["饵_蚯蚓"],
    },
    "rare_loach": {
        "id": "rare_loach", "name": "赤纹泥鳅", "rarity": "rare",
        "size_min": 5.0, "size_max": 30.0, "weight_min": 0.1, "weight_max": 1.0,
        "spots": [SPOT], "preferred_bait": ["饵_面团"],
    },
    "golden_koi": {
        "id": "golden_koi", "name": "金鳞鲤", "rarity": "gold",
        "size_min": 20.0, "size_max": 90.0, "weight_min": 1.0, "weight_max": 12.0,
        "spots": [SPOT], "preferred_bait": ["饵_黄金虫"],
    },
    "deep_whale": {
        "id": "deep_whale", "name": "深渊巨鲸", "rarity": "gold",
        "size_min": 100.0, "size_max": 500.0, "weight_min": 50.0, "weight_max": 500.0,
        "spots": [SPOT_OTHER], "preferred_bait": [],
    },
}

# 固定时钟（UTC+8 epoch 秒；远离 05:00 日界）
BASE_NOW = 1_800_000_000


def _settings(
    mode: str = "full",
    daily_limit: int = 20,
    wait_min: int = 300,
    wait_max: int = 300,
) -> Dict[str, Any]:
    """settings 全量 dict（含 fishing 段）；wait 区间固定便于懒判断言。"""
    return {"fishing": {
        "mode": mode,
        "bait_ids": ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"],
        "bait_bonus": {"rare": 8, "gold": 2},
        "rod_full_bonus": {"rare": 4, "gold": 2},
        "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95},
        "wait_sec": {"min": wait_min, "max": wait_max},
        "daily_limit": daily_limit,
        "energy": {"enabled": False},
        "king_event": {"enabled": True, "window_daily": 2, "chance": 0.3},
    }}


def _fish_table() -> Dict[str, Dict[str, Any]]:
    """ctx["fish_table"]：species Def→raw dict（装配层注入形态，引擎运行期读）。"""
    return {k: dict(v) for k, v in SPECIES_RAW.items()}


def _ctx(
    now: int = BASE_NOW,
    mode: str = "full",
    daily_limit: int = 20,
    wait_min: int = 300,
    wait_max: int = 300,
    inventory: object = None,
    seed: int = 42,
    with_engine: bool = False,
    fish_state: object = None,
) -> Dict[str, Any]:
    """构造测试 ctx：settings / now / rng / fish_table / player.persistent_state。

    with_engine=True 时注入 ctx["fishing_engine"]（复用路径）；缺省走自建兜底。
    """
    ctx: Dict[str, Any] = {
        "now": now,
        "settings": _settings(mode, daily_limit, wait_min, wait_max),
        "rng": random.Random(seed),
        "fish_table": _fish_table(),
        "player": {"persistent_state": {}},
    }
    if inventory is not None:
        ctx["inventory"] = inventory
    if with_engine:
        ctx["fishing_engine"] = FishingEngine(
            settings=ctx["settings"], rng=ctx["rng"])
    if fish_state is not None:
        ctx["fish_state"] = fish_state
    return ctx


def _today(settings: Dict[str, Any], now: int = BASE_NOW) -> str:
    return str(today_of(None, now, settings)["today"])


# =====================================================================================
# A. resolve_spot（对齐 M9 resolve 三态）
# =====================================================================================
def test_resolve_exact() -> None:
    """精确命中：key == 钓点 id → match=exact。"""
    ctx = _ctx()
    got = resolve_spot(ctx, SPOT)
    assert got["ok"] is True
    assert got["match"] == "exact"
    assert got["spot_id"] == SPOT
    assert got["candidates"] == []


def test_resolve_unique_prefix() -> None:
    """唯一前缀：恰一钓点 id 以 key 开头 → match=prefix。"""
    ctx = _ctx()
    got = resolve_spot(ctx, "gp_")
    assert got["ok"] is True
    assert got["match"] == "prefix"
    assert got["spot_id"] == SPOT


def test_resolve_ambiguous() -> None:
    """歧义：多个不同钓点共享前缀 → match=ambiguous + candidates。"""
    ctx = _ctx()
    # silver_carp 挂 deep_lake、deep_whale 挂 deep_well → 「deep」双候选
    ctx["fish_table"]["silver_carp"]["spots"] = [SPOT_OTHER]
    ctx["fish_table"]["deep_whale"]["spots"] = ["deep_well"]
    got = resolve_spot(ctx, "deep")
    assert got["ok"] is False
    assert got["match"] == "ambiguous"
    assert got["candidates"] == [SPOT_OTHER, "deep_well"]


def test_resolve_shared_spot_dedup_not_ambiguous() -> None:
    """共享钓点去重：多鱼种引用同一钓点 → 去重后唯一前缀命中（非歧义）。"""
    ctx = _ctx()
    # deep_lake 被 deep_whale 与 silver_carp 同时引用 → 去重后仍唯一
    ctx["fish_table"]["silver_carp"]["spots"] = [SPOT_OTHER]
    ctx["fish_table"]["deep_whale"]["spots"] = [SPOT_OTHER]
    got = resolve_spot(ctx, "deep")
    assert got["ok"] is True
    assert got["match"] == "prefix"
    assert got["spot_id"] == SPOT_OTHER


def test_resolve_not_found() -> None:
    """未找到：已知钓点集内无匹配 → match=not_found。"""
    ctx = _ctx()
    got = resolve_spot(ctx, "nowhere_spot")
    assert got["ok"] is False
    assert got["match"] == "not_found"
    assert got["spot_id"] is None
    assert got["candidates"] == []


def test_resolve_empty_key() -> None:
    """空串/纯空白 → not_found（不做匹配）。"""
    ctx = _ctx()
    assert resolve_spot(ctx, "")["match"] == "not_found"
    assert resolve_spot(ctx, "   ")["match"] == "not_found"


def test_resolve_nonstr_key() -> None:
    """非 str key（None/数字）→ not_found 不炸。"""
    ctx = _ctx()
    assert resolve_spot(ctx, None)["match"] == "not_found"
    assert resolve_spot(ctx, 123)["match"] == "not_found"


# =====================================================================================
# B. cast_fishing：下钩成功消息（TC-03/07/04）+ 守卫透传
# =====================================================================================
def test_cast_full_happy_message() -> None:
    """下钩成功：消息含 钓点/等待时长/日计数/饵使用情况（TC-03）。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["state"] == STATE_WAITING
    assert got["spot_id"] == SPOT
    assert got["wait_sec"] == 300
    assert got["bait_used"] == "饵_蚯蚓"
    assert got["casts"] == 1
    msg = got["message"]
    assert "已抛竿" in msg and SPOT in msg
    assert "300" in msg          # 等待时长
    assert "今日已抛 1 次" in msg  # 日计数
    assert "饵：饵_蚯蚓" in msg    # 饵使用情况
    assert MSG_CAST_OK.split("{")[0].strip() in msg


def test_cast_no_bait_guarantee() -> None:
    """无饵保底：空背包 → bait_used None、仍可下钩、消息含无饵行（TC-04）。"""
    ctx = _ctx(inventory={})
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["bait_used"] is None
    assert "无饵抛竿" in got["message"]
    assert ctx["fish_state"]["state"] == STATE_WAITING


def test_cast_daily_count_display() -> None:
    """日计数展示：预设 casts=5 → 下钩后 casts=6 且消息展示 6。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    today = _today(ctx["settings"])
    ctx["fish_state"] = {"state": STATE_IDLE, "today": today, "casts": 5}
    got = cast_fishing(ctx, SPOT)
    assert got["casts"] == 6
    assert "今日已抛 6 次" in got["message"]
    assert ctx["fish_state"]["casts"] == 6


def test_cast_wait_sec_zero_immediate() -> None:
    """wait_sec=0 即收：消息走 MSG_CAST_IMMEDIATE 即收提示（TC-07）。"""
    ctx = _ctx(wait_min=0, wait_max=0, inventory={"饵_面团": 2})
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["wait_sec"] == 0
    assert "即收" in got["message"]
    assert MSG_CAST_IMMEDIATE.split("{")[0].strip() in got["message"]
    assert ctx["fish_state"]["cast_at"] == BASE_NOW


def test_cast_guard_01_off() -> None:
    """GU-01：off 模式下钩拒绝（透传引擎 guard）。"""
    ctx = _ctx(mode="off", inventory={"饵_蚯蚓": 3})
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-01"
    assert got["reason"] == "mode_off"
    assert "关闭" in got["message"]


def test_cast_guard_02_daily_limit() -> None:
    """GU-02：日计数达上限 → 拒绝（透传引擎 guard，TC-04 第 21 次语义）。"""
    ctx = _ctx(daily_limit=2, inventory={"饵_蚯蚓": 3})
    today = _today(ctx["settings"])
    ctx["fish_state"] = {"state": STATE_IDLE, "today": today, "casts": 2}
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-02"
    assert got["reason"] == "daily_limit"
    assert "上限" in got["message"]


def test_cast_guard_02_daily_limit_boundary() -> None:
    """GU-02 边界：casts=19（daily_limit=20）→ 放行并计数 20。"""
    ctx = _ctx(daily_limit=20, inventory={"饵_蚯蚓": 3})
    today = _today(ctx["settings"])
    ctx["fish_state"] = {"state": STATE_IDLE, "today": today, "casts": 19}
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["casts"] == 20


def test_cast_guard_03_not_found() -> None:
    """GU-03 未找到：未知钓点 → spot_not_found（不进引擎）。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    got = cast_fishing(ctx, "nowhere_spot")
    assert got["ok"] is False
    assert got["reason"] == "spot_not_found"
    assert "钓点不存在" in got["message"]


def test_cast_guard_03_ambiguous() -> None:
    """GU-03 歧义：共享前缀多候选 → spot_ambiguous + candidates。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    ctx["fish_table"]["silver_carp"]["spots"] = [SPOT_OTHER]
    ctx["fish_table"]["deep_whale"]["spots"] = ["deep_well"]
    got = cast_fishing(ctx, "deep")
    assert got["ok"] is False
    assert got["reason"] == "spot_ambiguous"
    assert "匹配多个" in got["message"]
    assert SPOT_OTHER in got["candidates"]
    assert "deep_well" in got["candidates"]


def test_cast_guard_03_empty_or_nonstr() -> None:
    """GU-03 兜底：空串/非 str 钓点 → spot_not_found。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    assert cast_fishing(ctx, "")["reason"] == "spot_not_found"
    assert cast_fishing(ctx, None)["reason"] == "spot_not_found"


def test_cast_guard_04_session_active() -> None:
    """GU-04：已有进行中钓局（S2）→ 新下钩拒绝（透传引擎 guard）。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    assert cast_fishing(ctx, SPOT)["ok"] is True
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-04"
    assert got["reason"] == "session_active"


def test_cast_prefix_resolve_through() -> None:
    """前缀解析穿透：输入唯一前缀 → 解析为完整钓点后下钩成功。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    got = cast_fishing(ctx, "gp_")
    assert got["ok"] is True
    assert got["spot_id"] == SPOT


# =====================================================================================
# C. bite_trigger：等待中 / 鱼讯三类 / 金闪覆写位 / 收杆提醒
# =====================================================================================
def _cast_to_waiting(ctx: MutableMapping[str, Any]) -> None:
    """下钩到 S2（wait 300 固定 → cast_at = BASE_NOW+300）。"""
    assert cast_fishing(ctx, SPOT)["ok"] is True


def test_bite_waiting_not_due() -> None:
    """未到期等待中：now < cast_at → 等待中消息（钓点/已耗时/等待中，TC-21）。"""
    ctx = _ctx()
    _cast_to_waiting(ctx)
    got = bite_trigger(ctx)
    assert got["ok"] is True
    assert got["bite"] is False
    assert got["state"] == STATE_WAITING
    assert got["spot_id"] == SPOT
    assert got["elapsed_sec"] == 0
    assert "等待中" in got["message"]
    assert SPOT in got["message"]


def test_bite_waiting_elapsed_positive() -> None:
    """等待中已耗时：now 前移 120 → elapsed=120 展示。"""
    ctx = _ctx(now=BASE_NOW)
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 120
    got = bite_trigger(ctx)
    assert got["bite"] is False
    assert got["elapsed_sec"] == 120
    assert "120" in got["message"]


def test_bite_due_normal_nibble() -> None:
    """到期 normal → 微动 nibble 鱼讯（TC-10）+ 收杆提醒（TC-22）。"""
    # 单鱼种池（仅 silver_carp normal 在 SPOT）→ 目标确定性
    ctx = _ctx()
    ctx["fish_table"] = {"silver_carp": dict(SPECIES_RAW["silver_carp"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300  # 到期
    got = bite_trigger(ctx)
    assert got["ok"] is True
    assert got["bite"] is True
    assert got["kind"] == "nibble"
    assert got["golden"] is False
    assert got["state"] == STATE_BITE
    assert "微动" in got["message"]
    assert MSG_REEL_HINT in got["message"]
    assert got["target_rarity"] == "normal"


def test_bite_due_rare_tug() -> None:
    """到期 rare → 拉扯 tug 鱼讯（TC-11）。"""
    ctx = _ctx()
    ctx["fish_table"] = {"rare_loach": dict(SPECIES_RAW["rare_loach"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    got = bite_trigger(ctx)
    assert got["bite"] is True
    assert got["kind"] == "tug"
    assert "拉扯" in got["message"]
    assert got["golden"] is False


def test_bite_due_gold_violent() -> None:
    """到期 gold → 猛烈 violent 鱼讯（TC-12）。"""
    ctx = _ctx()
    ctx["fish_table"] = {"golden_koi": dict(SPECIES_RAW["golden_koi"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    got = bite_trigger(ctx)
    assert got["bite"] is True
    assert got["kind"] == "violent"
    assert "猛烈" in got["message"]
    assert got["golden"] is False  # king_hit 默认 False


def test_bite_golden_default_false() -> None:
    """金闪默认 False：未传 king_hit → 猛烈也不带金闪（本路 golden 恒 False）。"""
    ctx = _ctx()
    ctx["fish_table"] = {"golden_koi": dict(SPECIES_RAW["golden_koi"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    got = bite_trigger(ctx)
    assert got["golden"] is False
    assert "金闪" not in got["message"]


def test_bite_king_hit_golden_only_violent() -> None:
    """金闪覆写位：king_hit=True + gold → golden=True + 金闪标记行（TC-13 批4 接线位）。"""
    ctx = _ctx()
    ctx["fish_table"] = {"golden_koi": dict(SPECIES_RAW["golden_koi"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    got = bite_trigger(ctx, king_hit=True)
    assert got["golden"] is True
    assert got["kind"] == "violent"
    assert "金闪" in got["message"]
    assert MSG_REEL_HINT in got["message"]


def test_bite_gold_flash_isolation_nibble_tug_never() -> None:
    """金闪隔离 TC-13：微动/拉扯即使 king_hit=True 也永不金闪（fish_intent_of 承载）。"""
    # normal + king_hit → 不金闪
    ctx = _ctx()
    ctx["fish_table"] = {"silver_carp": dict(SPECIES_RAW["silver_carp"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    got = bite_trigger(ctx, king_hit=True)
    assert got["kind"] == "nibble"
    assert got["golden"] is False
    assert "金闪" not in got["message"]
    # rare + king_hit → 不金闪
    ctx2 = _ctx()
    ctx2["fish_table"] = {"rare_loach": dict(SPECIES_RAW["rare_loach"])}
    _cast_to_waiting(ctx2)
    ctx2["now"] = BASE_NOW + 300
    got2 = bite_trigger(ctx2, king_hit=True)
    assert got2["kind"] == "tug"
    assert got2["golden"] is False
    # 纯函数断言同源
    assert fish_intent_of("normal", king_hit=True)["golden"] is False
    assert fish_intent_of("rare", king_hit=True)["golden"] is False
    assert fish_intent_of("gold", king_hit=True)["golden"] is True


def test_bite_reel_hint_three_choices() -> None:
    """收杆提醒：鱼讯消息含 /收杆 满力/自动/止损（TC-22）。"""
    ctx = _ctx()
    ctx["fish_table"] = {"golden_koi": dict(SPECIES_RAW["golden_koi"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    got = bite_trigger(ctx)
    assert MSG_REEL_HINT in got["message"]
    for word in ("满力", "自动", "止损"):
        assert word in got["message"]


def test_bite_no_session() -> None:
    """空闲态 /鱼讯：无进行中钓局，不报错（TC-23）。"""
    ctx = _ctx()
    got = bite_trigger(ctx)
    assert got["ok"] is False
    assert got["reason"] == "no_session"
    assert "无进行中钓局" in got["message"]


def test_bite_off_rejected() -> None:
    """off 模式 /鱼讯 拒绝（GU-01 透传）。"""
    ctx = _ctx(mode="off")
    got = bite_trigger(ctx)
    assert got["ok"] is False
    assert got["guard"] == "GU-01"


def test_bite_already_bite_self_loop() -> None:
    """已咬钩自环：再查返回已有讯类不重复 roll（TR-11）。"""
    ctx = _ctx()
    ctx["fish_table"] = {"silver_carp": dict(SPECIES_RAW["silver_carp"])}
    _cast_to_waiting(ctx)
    ctx["now"] = BASE_NOW + 300
    first = bite_trigger(ctx)
    assert first["bite"] is True
    second = bite_trigger(ctx)
    assert second["bite"] is True
    assert second["kind"] == first["kind"]
    assert MSG_REEL_HINT in second["message"]


# =====================================================================================
# D. 引擎复用 / 确定性 / 持久化
# =====================================================================================
def test_engine_reuse_injected() -> None:
    """ctx["fishing_engine"] 已注入 → _engine_of 复用该实例。"""
    ctx = _ctx()
    eng = FishingEngine(settings=ctx["settings"], rng=ctx["rng"])
    ctx["fishing_engine"] = eng
    got_eng = _engine_of(ctx)
    assert got_eng is eng


def test_engine_self_build_fallback() -> None:
    """缺省自建兜底：无注入 → _engine_of 自建（settings+rng 注入）。"""
    ctx = _ctx()
    eng = _engine_of(ctx)
    assert isinstance(eng, FishingEngine)
    # 自建引擎运行期读 ctx fish_table（不炸）
    ctx["fish_table"] = {"silver_carp": dict(SPECIES_RAW["silver_carp"])}
    res = cast_fishing(ctx, SPOT)
    assert res["ok"] is True


def test_cast_with_injected_engine_full_path() -> None:
    """注入引擎全链路：cast_fishing 经注入引擎下钩成功。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3}, with_engine=True)
    got = cast_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["spot_id"] == SPOT


def test_deterministic_replay() -> None:
    """确定性：同 now 同种子 → 两次下钩 wait_sec 一致（禁裸 random）。"""
    ctx_a = _ctx(wait_min=100, wait_max=500, seed=2026, inventory={"饵_蚯蚓": 3})
    ctx_b = _ctx(wait_min=100, wait_max=500, seed=2026, inventory={"饵_蚯蚓": 3})
    ga = cast_fishing(ctx_a, SPOT)
    gb = cast_fishing(ctx_b, SPOT)
    assert ga["wait_sec"] == gb["wait_sec"]
    assert 100 <= ga["wait_sec"] <= 500


def test_fish_state_persist_hangs_on_ps() -> None:
    """持久化：cast_fishing 写 ctx["fish_state"] 即挂 player.persistent_state（落档）。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    assert "fish_state" not in ctx["player"]["persistent_state"]
    cast_fishing(ctx, SPOT)
    ps = ctx["player"]["persistent_state"]
    assert isinstance(ps["fish_state"], dict)
    assert ps["fish_state"] is ctx["fish_state"]
    assert ps["fish_state"]["state"] == STATE_WAITING


def test_fish_intent_of_reused_not_rewritten() -> None:
    """fish_intent_of 复用 fishing.py 内实现（本路 import 自 fishing_cast 同一对象）。"""
    from qbot_rpg.core.fishing import fish_intent_of as engine_fn
    from qbot_rpg.core.fishing_cast import fish_intent_of as cast_fn

    assert engine_fn is cast_fn  # 同一函数对象 = 复用非重写
    assert engine_fn("gold", king_hit=True) == {"kind": "violent", "golden": True}
    assert cast_fn("normal") == {"kind": "nibble", "golden": False}


def test_cross_session_lazy_calc() -> None:
    """跨会话懒计算：重启（新 ctx 仅带 fish_state + 到期时钟）→ 仍可咬钩（TC-06）。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    _cast_to_waiting(ctx)
    saved = dict(ctx["fish_state"])
    ctx2 = _ctx(now=BASE_NOW + 400, fish_state=saved)
    got = bite_trigger(ctx2)
    assert got["ok"] is True
    assert got["bite"] is True
    assert got["state"] == STATE_BITE
