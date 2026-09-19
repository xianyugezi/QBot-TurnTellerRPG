"""批36 · X2 采集/挖掘引擎纯函数单测（tests/unit/test_gathering.py）。

覆盖：`qbot_rpg/core/gathering.py`——采集点解析（GP-01~GP-11）、季节/时段归一与白名单、
无限资源图判定、天气修正（复用 weather_consumers）、冷却（GP-07 / TC-04 三点边界）、
`gather()` 五类结果桶、确定性（注入 rng / now，多种子不 flaky）。

依据：docs/采集挖掘_实现口径.md §一/§二/§五；细化_2a1d §一 GP-01~GP-11 + L72 判定时序 +
§六 TC-01~TC-04；【时间天气】L204-207；【总纲】L1280/L1085。

铁律：纯函数、零 IO、零定时器；rng 必须注入（禁裸 random 参与断言）。
"""

from __future__ import annotations

import random

from qbot_rpg.core.gathering import (
    DEFAULT_RESPAWN_MINUTES,
    GATHER_STATE_KEY,
    GatherPoint,
    effective_rate_rarity,
    gather,
    is_unlimited_map,
    normalize_period,
    normalize_season,
    parse_gather_points,
    period_ok,
    rarity_tiers,
    remaining_sec,
    season_ok,
    state_key,
)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
_RAIN_150_SHIFT_1 = [{"weather": "rain", "rate_mult": 1.5, "rarity_shift": 1},
                     {"weather": "storm", "rate_mult": 0}]


def _node(**over):
    node = {
        "id": "m1",
        "name": "野草地",
        "monsters": [{"enemy": "slime", "count": 3, "respawn_minutes": 5}],
        "gather_points": [
            {"id": "gp_herb", "item": "herb", "rate": 0.3, "rarity": "rare",
             "periods": ["dawn", "dusk"], "seasons": ["spring", "autumn"],
             "respawn_minutes": 10, "weather_mods": _RAIN_150_SHIFT_1},
        ],
    }
    node.update(over)
    return node


def _point(**over) -> GatherPoint:
    base = dict(id="gp1", item="herb", rate=0.5, rarity="normal", name="gp1")
    base.update(over)
    return GatherPoint(**base)


# ---------------------------------------------------------------------------
# A · 采集点解析（GP-01~GP-11）
# ---------------------------------------------------------------------------
def test_parse_gather_points_reads_all_fields_in_config_order() -> None:
    node = {"gather_points": [
        {"id": "gp_b", "item": "ore", "rate": 0.2, "rarity": "gold", "name": "矿脉",
         "periods": ["night"], "seasons": ["winter"], "respawn_minutes": 30,
         "weather_mods": _RAIN_150_SHIFT_1},
        {"id": "gp_a", "item": "herb", "rate": 0.8},
    ]}
    pts = parse_gather_points(node)
    assert [p.id for p in pts] == ["gp_b", "gp_a"]      # 原序（确定性）
    b = pts[0]
    assert (b.item, b.rarity, b.name) == ("ore", "gold", "矿脉")
    assert b.periods == ("night",) and b.seasons == ("winter",)
    assert b.respawn_minutes == 30
    # 缺省：rarity=normal / name=id / respawn=DEFAULT / periods/seasons 空
    a = pts[1]
    assert (a.rarity, a.name, a.respawn_minutes) == ("normal", "gp_a", DEFAULT_RESPAWN_MINUTES)
    assert a.periods == () and a.seasons == ()


def test_parse_gather_points_skips_bad_rows_and_clamps_rate() -> None:
    node = {"gather_points": [
        "not-a-dict",
        {"item": "herb", "rate": 0.5},          # 缺 id → 跳过
        {"id": "gp_x", "rate": 0.5},            # 缺 item → 跳过
        {"id": "gp_y", "item": "herb", "rate": 2},        # rate 越界 → clamp 1
        {"id": "gp_z", "item": "herb", "rate": -1},       # rate 越界 → clamp 0
    ]}
    pts = parse_gather_points(node)
    assert [p.id for p in pts] == ["gp_y", "gp_z"]
    assert pts[0].rate == 1.0 and pts[1].rate == 0.0


def test_parse_gather_points_missing_or_wrong_type_returns_empty() -> None:
    assert parse_gather_points({}) == ()
    assert parse_gather_points({"gather_points": "x"}) == ()
    assert parse_gather_points(None) == ()


# ---------------------------------------------------------------------------
# B · 季节 / 时段归一与白名单（GP-05 / GP-06）
# ---------------------------------------------------------------------------
def test_normalize_season_and_period_dual_form() -> None:
    assert normalize_season("spring") == "spring"
    assert normalize_season("春") == "spring"
    assert normalize_period("dusk") == "dusk"
    assert normalize_period("黄昏") == "dusk"
    assert normalize_season("旱季") is None
    assert normalize_period("") is None
    assert normalize_season(3) is None


def test_season_and_period_whitelist_semantics() -> None:
    p = _point(seasons=("spring", "autumn"), periods=("dusk",))
    # 名单空 = 不限
    assert season_ok(_point(seasons=()), "winter") is True
    assert period_ok(_point(periods=()), "noon") is True
    # 名单命中 / 不命中
    assert season_ok(p, "spring") is True
    assert season_ok(p, "summer") is False
    assert period_ok(p, "dusk") is True
    assert period_ok(p, "noon") is False
    # 当前值不可识别（None）→ 视为不限（P-5，不误杀）
    assert season_ok(p, None) is True
    assert period_ok(p, None) is True


# ---------------------------------------------------------------------------
# C · 无限资源图（【总纲】L1280 / L1085；P-1）
# ---------------------------------------------------------------------------
def test_is_unlimited_map_any_zero_count_row() -> None:
    assert is_unlimited_map({"monsters": [{"enemy": "a", "count": 3},
                                          {"enemy": "b", "count": 0}]}) is True
    assert is_unlimited_map({"monsters": [{"enemy": "a", "count": 3}]}) is False
    assert is_unlimited_map({"monsters": []}) is False
    assert is_unlimited_map({}) is False
    assert is_unlimited_map(None) is False
    # bool 不算整数
    assert is_unlimited_map({"monsters": [{"enemy": "a", "count": False}]}) is False


# ---------------------------------------------------------------------------
# D · 天气修正（GP-08~GP-11；复用 weather_consumers.apply_weather_mods）
# ---------------------------------------------------------------------------
def test_effective_rate_rarity_weather_mods() -> None:
    p = _point(rate=0.3, rarity="rare", weather_mods=_RAIN_150_SHIFT_1)
    # 无修正条目 → 原值（GP-08 向后兼容）
    assert effective_rate_rarity(p, "clear") == (0.3, "rare")
    # rain ×1.5 + 稀有档 +1
    rate, rarity = effective_rate_rarity(p, "rain")
    assert abs(rate - 0.45) < 1e-9 and rarity == "gold"
    # storm rate_mult 0 → 0（该天气不出）
    assert effective_rate_rarity(p, "storm")[0] == 0.0
    # 未注入天气 → 原值
    assert effective_rate_rarity(p, None) == (0.3, "rare")


def test_effective_rate_clamped_to_unit_and_rarity_four_tier_clamp() -> None:
    p = _point(rate=0.9, rarity="gold",
               weather_mods=[{"weather": "rain", "rate_mult": 5, "rarity_shift": 9}])
    rate, rarity = effective_rate_rarity(p, "rain")
    assert rate == 1.0                        # P-4：乘积越界收口
    assert rarity == rarity_tiers()[-1]        # clamp 到第 4 档（awakened）
    assert rarity_tiers() == ("normal", "rare", "gold", "awakened")


def test_rarity_tiers_single_source_with_weather_consumers() -> None:
    from qbot_rpg.core.weather_consumers import RARITY_TIERS

    assert rarity_tiers() == tuple(RARITY_TIERS)


# ---------------------------------------------------------------------------
# E · 冷却（GP-07 / TC-04）
# ---------------------------------------------------------------------------
def test_state_key_and_remaining_sec() -> None:
    assert state_key("m1", "gp1") == "m1:gp1"
    st = {"m1:gp1": 1600.0}
    assert remaining_sec(st, "m1", "gp1", 1000) == 600.0
    assert remaining_sec(st, "m1", "gp1", 1600) == 0.0
    assert remaining_sec(st, "m1", "gp1", 2000) == 0.0
    assert remaining_sec({}, "m1", "gp1", 1) == 0.0
    # {"ready_at": ts} 形态兼容
    assert remaining_sec({"m1:gp1": {"ready_at": 1600.0}}, "m1", "gp1", 1000) == 600.0


def test_tc04_refresh_boundary_immediate_9m59_10m00() -> None:
    node = _node(gather_points=[{"id": "gp_herb", "item": "herb", "rate": 1.0,
                                 "respawn_minutes": 10}])
    # 首次采集（now=0）→ 命中并置 ready_at = 600
    first = gather(node, "m1", rng=random.Random(1), now=0)
    assert [r["point_id"] for r in first["produced"]] == ["gp_herb"]
    st = dict(first["state_updates"])
    assert st == {"m1:gp_herb": 600.0}
    # 立即再采 → 拒绝（冷却中）
    again = gather(node, "m1", state=st, rng=random.Random(1), now=0)
    assert again["produced"] == [] and len(again["cooling"]) == 1
    assert again["cooling"][0]["remaining_sec"] == 600.0
    # 9 分 59 秒 → 拒绝
    t599 = gather(node, "m1", state=st, rng=random.Random(1), now=599)
    assert t599["produced"] == [] and t599["cooling"][0]["remaining_sec"] == 1.0
    # 10 分 00 秒 → 可采
    t600 = gather(node, "m1", state=st, rng=random.Random(1), now=600)
    assert [r["point_id"] for r in t600["produced"]] == ["gp_herb"]


# ---------------------------------------------------------------------------
# F · gather() 五类结果桶 + 判定顺序（2a1d L72）
# ---------------------------------------------------------------------------
def test_gather_buckets_produced_cooling_gated_blocked_missed() -> None:
    node = {"id": "m1", "gather_points": [
        {"id": "gp_ok", "item": "herb", "rate": 1.0, "respawn_minutes": 10},
        {"id": "gp_gated", "item": "herb", "rate": 1.0, "periods": ["night"]},
        {"id": "gp_blocked", "item": "ore", "rate": 0.5,
         "weather_mods": [{"weather": "storm", "rate_mult": 0}]},
        {"id": "gp_miss", "item": "ore", "rate": 0.0},
    ]}
    res = gather(node, "m1", period="noon", weather="storm", rng=random.Random(7), now=100)
    assert res["ok"] is True and res["reason"] == ""
    assert [r["point_id"] for r in res["produced"]] == ["gp_ok"]
    assert [r["point_id"] for r in res["gated"]] == ["gp_gated"]
    # gp_blocked（storm rate_mult 0）与 gp_miss（base rate 0）都按 GP-10
    # 「该天气不出 → 不进概率判定」归 blocked
    assert [r["point_id"] for r in res["blocked"]] == ["gp_blocked", "gp_miss"]
    assert res["missed"] == []
    assert res["state_updates"] == {"m1:gp_ok": 100 + 10 * 60}


def test_gather_missed_bucket_when_roll_fails() -> None:
    node = {"id": "m1", "gather_points": [{"id": "gp1", "item": "herb", "rate": 0.5}]}
    # 找一个必然落空的种子（rng.random() >= 0.5）
    miss = gather(node, "m1", rng=random.Random(0), now=0)
    assert miss["produced"] == [] and len(miss["missed"]) == 1
    hit = gather(node, "m1", rng=random.Random(1), now=0)
    assert len(hit["produced"]) == 1 and hit["missed"] == []


def test_gather_no_points_returns_not_ok() -> None:
    res = gather({"id": "m1"}, "m1", rng=random.Random(1), now=0)
    assert res["ok"] is False and res["reason"] == "no_points"
    assert res["produced"] == [] and res["state_updates"] == {}


def test_gather_gate_precedes_cooldown_and_is_not_consumed() -> None:
    """门控不命中 → 不给冷却增量（动作不可用），且不消耗 rng 效果。"""
    node = {"id": "m1", "gather_points": [
        {"id": "gp1", "item": "herb", "rate": 1.0, "periods": ["night"]}]}
    res = gather(node, "m1", period="noon", rng=random.Random(1), now=0)
    assert res["state_updates"] == {}
    assert len(res["gated"]) == 1


def test_gather_unlimited_map_never_sets_cooldown() -> None:
    node = {"id": "m1", "monsters": [{"enemy": "bat", "count": 0}],
            "gather_points": [{"id": "gp1", "item": "ore", "rate": 1.0}]}
    a = gather(node, "m1", rng=random.Random(1), now=0)
    assert a["unlimited"] is True and a["state_updates"] == {}
    # 连采 5 次仍命中（无冷却）
    for _ in range(5):
        r = gather(node, "m1", state={}, rng=random.Random(1), now=0)
        assert len(r["produced"]) == 1


def test_gather_does_not_mutate_input_state() -> None:
    node = {"id": "m1", "gather_points": [{"id": "gp1", "item": "herb", "rate": 1.0}]}
    st = {"m1:gp_other": 999.0}
    snapshot = dict(st)
    gather(node, "m1", state=st, rng=random.Random(1), now=0)
    assert st == snapshot           # 引擎纯函数：冷却增量只经 state_updates 回传


# ---------------------------------------------------------------------------
# G · 确定性 / 多种子不 flaky（TC-01 rate 收敛 ±5%）
# ---------------------------------------------------------------------------
def test_gather_is_deterministic_for_same_seed() -> None:
    node = _node()
    args = dict(season="spring", period="dawn", weather="rain", now=0)
    a = gather(node, "m1", rng=random.Random(2026), **args)
    b = gather(node, "m1", rng=random.Random(2026), **args)
    assert a == b


def test_rate_convergence_within_5_percent_multi_seed() -> None:
    """TC-01：rate=0.3，多种子 × 1000 取样，命中率收敛于 0.3（±5%）。"""
    node = {"id": "m1", "gather_points": [{"id": "gp1", "item": "herb", "rate": 0.3}]}
    for seed in (42, 2026, 7):
        rng = random.Random(seed)
        hits = sum(1 for _ in range(1000)
                   if gather(node, "m1", rng=rng, now=0)["produced"])
        assert abs(hits / 1000.0 - 0.3) <= 0.05, (seed, hits)


def test_weather_raises_effective_rate_detectable() -> None:
    """TC-02：rain ×1.5 使 0.3 → 0.45（用大样本命中率对比体现）。"""
    node = {"id": "m1", "gather_points": [
        {"id": "gp1", "item": "herb", "rate": 0.3,
         "weather_mods": [{"weather": "rain", "rate_mult": 1.5}]}]}

    def hits(weather: str, seed: int) -> float:
        rng = random.Random(seed)
        return sum(1 for _ in range(2000)
                   if gather(node, "m1", weather=weather, rng=rng, now=0)["produced"]) / 2000.0

    plain = hits("clear", 42)
    rainy = hits("rain", 42)
    assert abs(plain - 0.3) <= 0.05
    assert abs(rainy - 0.45) <= 0.05
    assert rainy > plain


# ---------------------------------------------------------------------------
# H · 常量锚点（GP-07）
# ---------------------------------------------------------------------------
def test_constants_anchored_to_spec() -> None:
    assert DEFAULT_RESPAWN_MINUTES == 10          # GP-07 缺省 10 分钟
    assert GATHER_STATE_KEY == "gather_state"     # P-3 落点
