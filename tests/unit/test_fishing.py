"""M10 批1·路1B：FishingEngine 流程状态机核心单测（tests/unit/test_fishing.py）。

文件名：tests/unit/test_fishing.py
创建时间：2026-08-31
作者：Hermes 子agent-1B（M10 钓鱼实现组批1·路1B：流程状态机核心）

功能：qbot_rpg.core.fishing FishingEngine 纯函数直测（零 NoneBot、确定性、零定时器/
      零睡眠——等待/决策窗全时间戳懒判，无实时倒计时）：
  - 状态机全迁移 TR-01~11 happy path（S0→S1→S2→S3→ST/SL→S0）
  - 守卫 GU-01(mode off)/GU-02(日计数<daily_limit)/GU-03(spot 合法)/GU-04(无进行中
    钓局) 各自拒绝
  - 懒计算：未到期等待中 / 到期咬钩（now >= cast_at，注入 ctx["now"] 确定性）
  - wait_sec=0 即收（cast_at=now，TC-07）
  - 鱼讯三类：normal→微动 nibble / rare→拉扯 tug / gold→猛烈 violent（TC-10~12）+
    金闪覆写位（king_hit=True → golden=True，TC-13）
  - 决策窗超时跑鱼（carry_sec 90 / 0=不限，TR-07，TC-08）
  - 收杆三选一：止损（不 roll 空收）/ 满力·自动（roll_hook 注入位/骨架，TC-15~17）
  - 每日计数：fish_state {today, casts} 对齐 dayroll 懒重置（跨日 casts 清零，TC-04）
  - simple/off 路由（TC-09/14）：simple 短接直接出鱼骨架、无 S2/S3；off 全拒绝
  - fish_state 持久化：引擎写 ctx["fish_state"] 即挂 player.persistent_state

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §二（状态集/迁移表 TR-01~11/守卫 GU-01~04/
    §2.4 模式前缀）/ §三（鱼讯三类 §3.1 rarity→讯类 + §3.3 金闪 + §3.4 决策窗）/
    §四（收杆三选一）/ §六 验收 TC-01~23（A~E 区）
  - docs/m10_shared_contract.md §二 IF-03（FishDef 访问器）/ §五 铁律
  - docs/m10_接口摸底.md §一（harvest_at 时间戳懒判模式）/ §二（fish_intent_of
    rarity 直接映射）/ §八-4（每日计数 fish_state {today, casts}）/ §九（rng 注入、
    零定时器）
  - 模式参考：tests/unit/test_alchemy_harvest.py（HarvestEngine 直测风格）/
    tests/unit/test_fishing_settings.py（_as_dict helper 处理 Dict[str, object]）
"""
from __future__ import annotations

import random
from typing import Any, Dict, MutableMapping, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.fishing import (
    KIND_NIBBLE,
    KIND_TUG,
    KIND_VIOLENT,
    STATE_BITE,
    STATE_IDLE,
    STATE_LOST,
    STATE_REELED,
    STATE_WAITING,
    FishingEngine,
    fish_intent_of,
)

# =====================================================================================
# 夹具
# =====================================================================================

SPOT = "gp_moon_grass"
SPOT_OTHER = "deep_lake"

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

# 固定时钟（UTC+8 epoch 秒；对齐 dayroll 05:00 日界，选一个远离日界的中午时刻防跨日干扰）
BASE_NOW = 1_800_000_000


def _as_dict(obj: object) -> Dict[str, Any]:
    """fishing_cfg 返回 Mapping[str, object]，测试内按 Dict[str, Any] 读取嵌套断言。"""
    return cast(Dict[str, Any], obj)


def _fish(id: str) -> FishDef:
    return cast(FishDef, FishDef.from_entry(SPECIES_RAW[id]))


def _species() -> list:
    return [_fish("silver_carp"), _fish("rare_loach"), _fish("golden_koi")]


def _settings(
    mode: str = "full",
    daily_limit: int = 20,
    wait_min: int = 300,
    wait_max: int = 900,
    carry_sec: object = None,
) -> Dict[str, Any]:
    seg: Dict[str, Any] = {
        "mode": mode,
        "bait_ids": ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"],
        "bait_bonus": {"rare": 8, "gold": 2},
        "rod_full_bonus": {"rare": 4, "gold": 2},
        "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95},
        "wait_sec": {"min": wait_min, "max": wait_max},
        "daily_limit": daily_limit,
        "energy": {"enabled": False},
        "king_event": {"enabled": True, "window_daily": 2, "chance": 0.3},
    }
    if carry_sec is not None:
        seg["carry_sec"] = carry_sec
    return {"fishing": seg}


def _ctx(
    now: int = BASE_NOW,
    mode: str = "full",
    daily_limit: int = 20,
    wait_min: int = 300,
    wait_max: int = 900,
    carry_sec: object = None,
    inventory: object = None,
    seed: int = 42,
    with_remove_hook: bool = False,
    fish_state: object = None,
) -> Dict[str, Any]:
    """构造测试 ctx：settings / now / rng / inventory 注入，fish_state 可选预置。"""
    ctx: Dict[str, Any] = {
        "now": now,
        "settings": _settings(mode, daily_limit, wait_min, wait_max, carry_sec),
        "rng": random.Random(seed),
        "player": {"persistent_state": {}},
    }
    if inventory is not None:
        ctx["inventory"] = inventory
    if with_remove_hook:
        def _remove(item_id: object, count: object) -> bool:
            inv = ctx.get("inventory")
            if not isinstance(inv, MutableMapping):
                return False
            if not isinstance(count, int) or isinstance(count, bool):
                return False
            cur = inv.get(item_id, 0)
            if not isinstance(cur, int) or cur < count:
                return False
            inv[item_id] = cur - count
            return True

        ctx["remove_item"] = _remove
    if fish_state is not None:
        ctx["fish_state"] = fish_state
    return ctx


def _engine(ctx: MutableMapping[str, Any], **kwargs: Any) -> FishingEngine:
    """构造引擎：species 走构造器注入（装配层 fish_table 未接线前测试直注）。"""
    return FishingEngine(species=_species(), **kwargs)


# =====================================================================================
# A. 守卫 GU-01~04
# =====================================================================================
def test_guard_01_off_rejects_start() -> None:
    """GU-01：off 模式 /钓鱼 全拒绝（细化 §2.3 / TC-09）。"""
    ctx = _ctx(mode="off")
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-01"
    assert got["reason"] == "mode_off"
    assert got["state"] == STATE_IDLE


def test_guard_01_off_rejects_bite_and_reel() -> None:
    """GU-01：off 模式 /鱼讯 /收杆 全拒绝（细化 §2.3）。"""
    ctx = _ctx(mode="off")
    eng = _engine(ctx)
    assert eng.bite_check(ctx)["ok"] is False
    assert eng.bite_check(ctx)["guard"] == "GU-01"
    assert eng.reel_in(ctx, "auto")["ok"] is False
    assert eng.reel_in(ctx, "auto")["guard"] == "GU-01"


def test_guard_02_daily_limit_rejects() -> None:
    """GU-02：日计数达 daily_limit=2 → 第 3 次下钩被拦截（TC-04 第 21 次语义）。"""
    ctx = _ctx(daily_limit=2)
    eng = _engine(ctx)
    # 预置 fish_state：当日已抛 2 次
    today = today_of(None, BASE_NOW, ctx["settings"])["today"]
    ctx["fish_state"] = {"state": STATE_IDLE, "today": today, "casts": 2}
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-02"
    assert got["reason"] == "daily_limit"


def test_guard_02_daily_limit_boundary_ok() -> None:
    """GU-02 边界：casts=19（daily_limit=20）→ 第 20 次放行、计数 20。"""
    ctx = _ctx(daily_limit=20)
    eng = _engine(ctx)
    today = today_of(None, BASE_NOW, ctx["settings"])["today"]
    ctx["fish_state"] = {"state": STATE_IDLE, "today": today, "casts": 19}
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert ctx["fish_state"]["casts"] == 20
    # 第 21 次被拦截（TC-04）
    ctx["fish_state"] = {"state": STATE_IDLE, "today": today, "casts": 20}
    got2 = eng.start_fishing(ctx, SPOT)
    assert got2["ok"] is False
    assert got2["guard"] == "GU-02"


def test_guard_03_spot_invalid_rejects() -> None:
    """GU-03：spot 不在已知钓点集 → 拒绝（B-4 引擎层口径）。"""
    ctx = _ctx()
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, "nowhere_spot")
    assert got["ok"] is False
    assert got["guard"] == "GU-03"
    assert got["reason"] == "spot_invalid"


def test_guard_03_spot_invalid_empty_or_nonstr() -> None:
    """GU-03：空串 / 非 str spot → 拒绝。"""
    ctx = _ctx()
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, "")["ok"] is False
    assert eng.start_fishing(ctx, "  ")["ok"] is False
    assert eng.start_fishing(ctx, None)["ok"] is False


def test_guard_03_spot_valid_other_pool_spot() -> None:
    """GU-03：已知钓点集含其它鱼种 spot（deep_lake）→ 合法。"""
    ctx = _ctx()
    eng = FishingEngine(species=[_fish("deep_whale")])
    got = eng.start_fishing(ctx, SPOT_OTHER)
    assert got["ok"] is True
    assert got["spot_id"] == SPOT_OTHER


def test_guard_04_session_active_waiting_rejects() -> None:
    """GU-04：已有进行中钓局（S2 等待中）→ 新下钩拒绝。"""
    ctx = _ctx()
    eng = _engine(ctx)
    first = eng.start_fishing(ctx, SPOT)
    assert first["ok"] is True
    assert first["state"] == STATE_WAITING
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-04"
    assert got["reason"] == "session_active"


def test_guard_04_session_active_bite_rejects() -> None:
    """GU-04：已有进行中钓局（S3 咬钩）→ 新下钩拒绝（TC-20 讨伐中 /钓 新局被拒同型）。"""
    ctx = _ctx(wait_min=0, wait_max=0)  # 即收便于进入 S3
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    bite = eng.bite_check(ctx)
    assert bite["ok"] is True and bite["bite"] is True
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is False
    assert got["guard"] == "GU-04"


# =====================================================================================
# B. start_fishing 流程（TR-01/TR-02）+ 懒计时期注册
# =====================================================================================
def test_start_full_happy_registers_wait() -> None:
    """full happy path：下钩 → S2、cast_at = now + wait_sec、日计数 +1（TC-03）。"""
    ctx = _ctx(wait_min=300, wait_max=300)
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["state"] == STATE_WAITING
    assert got["spot_id"] == SPOT
    assert got["cast_at"] == BASE_NOW + 300
    assert got["wait_sec"] == 300
    fs = ctx["fish_state"]
    assert fs["state"] == STATE_WAITING
    assert fs["casts"] == 1
    assert fs["today"] == today_of(None, BASE_NOW, ctx["settings"])["today"]


def test_start_bait_consumed() -> None:
    """扣饵：有饵 → bait_used 记录 + inventory 扣 1（B-3 内置最小扣饵）。"""
    ctx = _ctx(inventory={"饵_蚯蚓": 3})
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["bait_used"] == "饵_蚯蚓"
    assert ctx["fish_state"]["bait_used"] == "饵_蚯蚓"
    assert ctx["inventory"]["饵_蚯蚓"] == 2


def test_start_bait_consumed_remove_hook() -> None:
    """扣饵：ctx.remove_item hook 优先（批2 装配注入形态）。"""
    ctx = _ctx(inventory={"饵_面团": 3}, with_remove_hook=True)
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["bait_used"] == "饵_面团"
    assert ctx["inventory"]["饵_面团"] == 2


def test_start_no_bait_no_deadlock() -> None:
    """无饵保底不卡死：空背包 → bait_used None，仍可下钩（TC-04 无饵仍可下钩）。"""
    ctx = _ctx(inventory={})
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["bait_used"] is None
    assert ctx["fish_state"]["bait_used"] is None
    assert ctx["fish_state"]["state"] == STATE_WAITING


def test_start_wait_sec_zero_immediate() -> None:
    """wait_sec=0 即收：cast_at = now（TC-07）。"""
    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["wait_sec"] == 0
    assert got["cast_at"] == BASE_NOW


def test_start_wait_uses_injected_rng() -> None:
    """确定性：wait_sec 随机区间经注入 rng（同种子同值，禁止裸 random）。"""
    ctx_a = _ctx(wait_min=300, wait_max=900, seed=42)
    ctx_b = _ctx(wait_min=300, wait_max=900, seed=42)
    eng_a = _engine(ctx_a)
    eng_b = _engine(ctx_b)
    ga = eng_a.start_fishing(ctx_a, SPOT)
    gb = eng_b.start_fishing(ctx_b, SPOT)
    assert ga["wait_sec"] == gb["wait_sec"]
    assert 300 <= ga["wait_sec"] <= 900
    # 不同种子 → 等待仍落在配置区间（随机区间生效）
    ctx_c = _ctx(wait_min=300, wait_max=900, seed=2026)
    gc = _engine(ctx_c).start_fishing(ctx_c, SPOT)
    assert 300 <= gc["wait_sec"] <= 900


def test_start_daily_count_cross_day_reset() -> None:
    """每日计数跨日重置：fish_state today 为昨天、casts=5 → 懒计算重置后从 1 计（TC-04）。"""
    ctx = _ctx()
    eng = _engine(ctx)
    yesterday = today_of(None, BASE_NOW - 86400, ctx["settings"])["today"]
    ctx["fish_state"] = {"state": STATE_IDLE, "today": yesterday, "casts": 5}
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    fs = ctx["fish_state"]
    assert fs["casts"] == 1
    assert fs["today"] == today_of(None, BASE_NOW, ctx["settings"])["today"]


def test_fish_state_persist_hangs_on_ps() -> None:
    """fish_state 持久化：引擎写 ctx["fish_state"] 即挂 player.persistent_state（落档）。"""
    ctx = _ctx()
    eng = _engine(ctx)
    assert "fish_state" not in ctx["player"]["persistent_state"]
    eng.start_fishing(ctx, SPOT)
    ps = ctx["player"]["persistent_state"]
    assert isinstance(ps["fish_state"], dict)
    assert ps["fish_state"] is ctx["fish_state"]
    assert ps["fish_state"]["state"] == STATE_WAITING


def test_simple_mode_direct_settle() -> None:
    """simple 短接：下钩 → ST 直接出鱼骨架（无 S2/S3，无等待/鱼讯；TC-09/14）。"""
    ctx = _ctx(mode="simple")
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["state"] == STATE_REELED
    assert got["mode"] == "simple"
    assert got["direct"] is True
    assert got["settle_pending"] is True  # 出鱼结算批3 接线
    assert ctx["fish_state"]["state"] == STATE_REELED
    # 日计数仍 +1
    assert ctx["fish_state"]["casts"] == 1


# =====================================================================================
# C. bite_check（TR-03 / TR-11）+ 鱼讯三类 + 金闪
# =====================================================================================
def _to_bite(ctx: MutableMapping[str, Any], eng: FishingEngine) -> MutableMapping[str, Any]:
    """推进到 S3：即收下钩 → 咬钩（返回 fish_state 供断言）。"""
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    bite = eng.bite_check(ctx)
    assert bite["ok"] is True and bite["bite"] is True
    return ctx["fish_state"]


def test_bite_waiting_not_due() -> None:
    """懒计算未到期：now < cast_at → 等待中（bite=False，S2；TC-21）。"""
    ctx = _ctx(wait_min=300, wait_max=300)
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    got = eng.bite_check(ctx)  # now == cast_at - 300 < cast_at
    assert got["ok"] is True
    assert got["bite"] is False
    assert got["state"] == STATE_WAITING
    assert got["message"] == "等待中，尚未有鱼讯"


def test_bite_due_normal_nibble() -> None:
    """到期 normal → 微动 nibble 鱼讯（TC-10）；S2→S3。"""
    ctx = _ctx(wait_min=300, wait_max=300)
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    ctx["now"] = BASE_NOW + 300  # 到期
    got = eng.bite_check(ctx)
    assert got["ok"] is True and got["bite"] is True
    assert got["kind"] == KIND_NIBBLE
    assert got["golden"] is False
    assert got["state"] == STATE_BITE
    assert "微动" in got["message"]


def test_bite_due_rare_tug() -> None:
    """到期 rare → 拉扯 tug 鱼讯（TC-11）。"""
    # 单鱼种池（仅 rare_loach 在 SPOT）→ 目标确定性
    eng = FishingEngine(species=[_fish("rare_loach")])
    ctx = _ctx(wait_min=0, wait_max=0)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    got = eng.bite_check(ctx)
    assert got["kind"] == KIND_TUG
    assert got["golden"] is False
    assert "拉扯" in got["message"]


def test_bite_due_gold_violent() -> None:
    """到期 gold → 猛烈 violent 鱼讯（TC-12）。"""
    eng = FishingEngine(species=[_fish("golden_koi")])
    ctx = _ctx(wait_min=0, wait_max=0)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    got = eng.bite_check(ctx)
    assert got["kind"] == KIND_VIOLENT
    assert got["golden"] is False
    assert "猛烈" in got["message"]


def test_bite_king_hit_golden() -> None:
    """金闪覆写位：king_hit=True + gold → golden True（TC-13 金闪隔离；批4 接线位）。"""
    eng = FishingEngine(species=[_fish("golden_koi")])
    ctx = _ctx(wait_min=0, wait_max=0)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    got = eng.bite_check(ctx, king_hit=True)
    assert got["kind"] == KIND_VIOLENT
    assert got["golden"] is True
    # 微动/拉扯永不金闪（TC-13）
    assert fish_intent_of("normal", king_hit=True)["golden"] is False
    assert fish_intent_of("rare", king_hit=True)["golden"] is False


def test_bite_target_locked_in_state() -> None:
    """咬钩锁定目标：fish_state 写 target_species_id / target_rarity / bite_ts（供批3）。"""
    eng = FishingEngine(species=[_fish("silver_carp")])
    ctx = _ctx(wait_min=0, wait_max=0)
    fs = _to_bite(ctx, eng)
    assert fs["target_species_id"] == "silver_carp"
    assert fs["target_rarity"] == "normal"
    assert fs["bite_ts"] == BASE_NOW
    assert fs["kind"] == KIND_NIBBLE


def test_bite_no_session() -> None:
    """空闲态 /鱼讯 → 无进行中钓局，不报错（TC-23）。"""
    ctx = _ctx()
    eng = _engine(ctx)
    got = eng.bite_check(ctx)
    assert got["ok"] is False
    assert got["reason"] == "no_session"
    assert got["message"] == "无进行中钓局"


def test_bite_already_bite_self_loop() -> None:
    """S3 已咬钩：自环返回已有讯类，不重复 roll（TR-11 / TC-22）。"""
    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx)
    fs = _to_bite(ctx, eng)
    kind1 = fs["kind"]
    got = eng.bite_check(ctx)
    assert got["ok"] is True and got["bite"] is True
    assert got["kind"] == kind1
    assert got["state"] == STATE_BITE


def test_bite_simple_no_wait() -> None:
    """simple 模式：无 S2/S3 实例 → bite_check 拒绝（TC-14）。"""
    ctx = _ctx(mode="simple")
    eng = _engine(ctx)
    got = eng.bite_check(ctx)
    assert got["ok"] is False
    assert got["reason"] == "simple_no_wait"


# =====================================================================================
# D. reel_in（TR-04~09）：止损 / 满力·自动骨架 / 决策窗超时
# =====================================================================================
def test_reel_stop_empty_reel() -> None:
    """止损：不 roll 空收回 S0（TR-06/08，TC-17）；饵已计耗不返还、日计数不减。"""
    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    ctx["fish_state"]["bait_used"] = "饵_蚯蚓"
    got = eng.reel_in(ctx, "stop")
    assert got["ok"] is True
    assert got["choice"] == "stop"
    assert got["state"] == STATE_REELED
    assert got["reeled"] is False
    assert ctx["fish_state"]["state"] == STATE_IDLE  # 终态回 S0
    assert ctx["fish_state"]["casts"] == 1  # 日计数不回滚
    assert "last" not in ctx["fish_state"]  # 止损不触发 roll


def test_reel_full_skeleton() -> None:
    """满力：roll 概率批2 路2C 实现——本路返回 {ok, choice, state} 骨架（B-6）。"""
    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    got = eng.reel_in(ctx, "full")
    assert got["ok"] is True
    assert got["choice"] == "full"
    assert got["state"] == STATE_REELED
    assert got["reeled"] is True
    assert got["roll_pending"] is True
    assert got["settle_pending"] is True
    assert ctx["fish_state"]["state"] == STATE_IDLE
    # last 快照供批3 结算跨指令读取
    assert ctx["fish_state"]["last"]["choice"] == "full"


def test_reel_auto_skeleton() -> None:
    """自动：同骨架（TC-16 概率归批2）。"""
    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is True
    assert got["choice"] == "auto"
    assert got["state"] == STATE_REELED
    assert got["roll_pending"] is True


def test_reel_roll_hook_injected() -> None:
    """roll_hook 注入位：注入后被调用并返回 roll 结果（批2 路2C 接线形态）。"""
    calls: list = []

    def hook(c: Any, fs: Any, ch: Any) -> Dict[str, Any]:
        calls.append((c, fs, ch))
        return {"rarity": "gold"}

    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx, roll_hook=hook)
    _to_bite(ctx, eng)
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is True
    assert got["roll"] == {"rarity": "gold"}
    assert len(calls) == 1
    assert calls[0][2] == "auto"
    assert ctx["fish_state"]["last"]["roll"] == {"rarity": "gold"}


def test_reel_timeout_lost() -> None:
    """决策窗超时：now - bite_ts > carry_sec(90) → SL 跑鱼回 S0（TR-07，TC-08）。"""
    ctx = _ctx(wait_min=0, wait_max=0, carry_sec=90)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    ctx["now"] = BASE_NOW + 91  # 超时 1 秒
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is False
    assert got["reason"] == "timeout"
    assert got["state"] == STATE_LOST
    assert ctx["fish_state"]["state"] == STATE_IDLE  # 跑鱼回 S0（TR-09）
    assert ctx["fish_state"]["casts"] == 1  # 日计数不减（TR-07）
    assert "bait_used" not in ctx["fish_state"]  # 饵已计耗不返还


def test_reel_timeout_boundary_not_lost() -> None:
    """决策窗边界：now - bite_ts == carry_sec → 未超时（> carry 才跑鱼）。"""
    ctx = _ctx(wait_min=0, wait_max=0, carry_sec=90)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    ctx["now"] = BASE_NOW + 90
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is True


def test_reel_timeout_zero_unlimited() -> None:
    """carry_sec=0 不限：任意长决策窗不跑鱼（细化 §3.4 0=不限）。"""
    ctx = _ctx(wait_min=0, wait_max=0, carry_sec=0)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    ctx["now"] = BASE_NOW + 99999
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is True
    assert got["state"] == STATE_REELED


def test_reel_no_session() -> None:
    """空闲态 /收杆 → 无进行中钓局（TC-23 同型）。"""
    ctx = _ctx()
    eng = _engine(ctx)
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is False
    assert got["reason"] == "no_session"


def test_reel_waiting_cannot_reel() -> None:
    """S2 等待中 /收杆 → 拒绝（未咬钩）。"""
    ctx = _ctx(wait_min=300, wait_max=300)
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is False
    assert got["reason"] == "waiting"


def test_reel_invalid_choice() -> None:
    """未知收杆方式 → 拒绝（三选一之外，细化 §4.1）。"""
    ctx = _ctx(wait_min=0, wait_max=0)
    eng = _engine(ctx)
    _to_bite(ctx, eng)
    got = eng.reel_in(ctx, "power")
    assert got["ok"] is False
    assert got["reason"] == "invalid_choice"


def test_reel_simple_no_wait() -> None:
    """simple 模式：无 S2/S3 → /收杆 拒绝（TC-14）。"""
    ctx = _ctx(mode="simple")
    eng = _engine(ctx)
    got = eng.reel_in(ctx, "auto")
    assert got["ok"] is False
    assert got["reason"] == "simple_no_wait"


# =====================================================================================
# E. 状态机全链路 + 鱼讯意图纯函数
# =====================================================================================
def test_full_fsm_happy_path() -> None:
    """完整 happy path：S0→S1→S2→S3→ST→S0（TR-01~08；TC-05）。"""
    ctx = _ctx(wait_min=300, wait_max=300)
    eng = _engine(ctx)
    # S0 → S2（S1 瞬时，B-1）
    start = eng.start_fishing(ctx, SPOT)
    assert start["state"] == STATE_WAITING
    # S2 → S3（到期）
    ctx["now"] = BASE_NOW + 300
    bite = eng.bite_check(ctx)
    assert bite["state"] == STATE_BITE
    # S3 → ST（自动收杆骨架）
    reel = eng.reel_in(ctx, "auto")
    assert reel["state"] == STATE_REELED
    # ST → S0（会话清理）
    assert ctx["fish_state"]["state"] == STATE_IDLE
    # 回 S0 后可再开局（TR-08 后接受新钓局）
    ctx["now"] = BASE_NOW + 600
    again = eng.start_fishing(ctx, SPOT)
    assert again["ok"] is True
    assert ctx["fish_state"]["casts"] == 2  # 日计数累计


def test_fish_intent_of_pure() -> None:
    """fish_intent_of 纯函数：三讯类映射 + 未知回落微动 + 金闪隔离（TC-10~13）。"""
    assert fish_intent_of("normal") == {"kind": KIND_NIBBLE, "golden": False}
    assert fish_intent_of("rare") == {"kind": KIND_TUG, "golden": False}
    assert fish_intent_of("gold") == {"kind": KIND_VIOLENT, "golden": False}
    assert fish_intent_of("gold", king_hit=True)["golden"] is True
    assert fish_intent_of("bogus") == {"kind": KIND_NIBBLE, "golden": False}
    assert fish_intent_of(None)["kind"] == KIND_NIBBLE


def test_deterministic_same_state_replay() -> None:
    """确定性重放：同 now 同 rng 种子 → 两次完整流程产出同 wait_sec/目标鱼讯。"""
    outs = []
    for _ in range(2):
        ctx = _ctx(wait_min=100, wait_max=500, seed=2026)
        eng = _engine(ctx)
        start = eng.start_fishing(ctx, SPOT)
        ctx["now"] = start["cast_at"]
        bite = eng.bite_check(ctx)
        outs.append((start["wait_sec"], bite["kind"], bite["target_species_id"]))
    assert outs[0] == outs[1]


def test_cross_session_lazy_calc() -> None:
    """跨会话懒计算：重启（新 ctx）后沿用 fish_state 仍可到期咬钩（TC-06，无实时计时器）。"""
    ctx = _ctx(wait_min=300, wait_max=300)
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    saved = dict(ctx["fish_state"])  # 模拟落档快照
    # 模拟重启：新 ctx 仅带持久化 fish_state + 到期时钟
    ctx2 = _ctx(now=BASE_NOW + 400, fish_state=saved)
    eng2 = _engine(ctx2)
    got = eng2.bite_check(ctx2)
    assert got["ok"] is True and got["bite"] is True
    assert got["state"] == STATE_BITE
