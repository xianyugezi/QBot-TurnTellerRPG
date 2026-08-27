"""天气池等概率确定性抽签单测（M3 批次2·路G · M37/M38）。

依据：细化_2a4b_天气引擎（§1.2 默认池结构 R3/R4 / §2.2-2.3 等概率抽签与确定性 seed R10-R12 /
      §3.1-3.2 地图 weather_pool 覆盖 R13/R16-R20 / §6.2 V4 校验 / TC-2~TC-9 验收口径）
      + m3_shared_contract §6（6.1 核心规则 / 6.2 V4 池校验；IF05 map_pool / IF08 map_weather /
      IF04 weather_now 签名以细化_2a4c §1.1 为准）。
覆盖：IF05 生效池（覆盖池优先 / 空覆盖回退默认 / 缺省回退默认 / 两种条目形态）、
      IF08 确定性抽签（同 tick 同池同值 / 不同 tick 重排 / 大 tick·负数 tick 稳定 / 手算 sha256 对齐 /
      空池防御 / 等概率分布）、IF04 weather_now（用当前 cycle_tick）、V4 池校验（非空 / 键唯一 /
      键+中文名齐全，红拦全收集）。

手算基准：default_pool = DEFAULT_POOL 5 键（clear/cloudy/rain/storm/fog）；tick=100 → seed 由
hashlib.sha256("clearcloudyfograinstorm100") 逐字手算，保证确定性公式逐字对齐（跨端一致）。
"""
from __future__ import annotations

import datetime
import hashlib
from typing import List

import pytest

from qbot_rpg.engine.worldtime import (
    DEFAULT_POOL,
    WorldTime,
    validate_weather_pool,
)

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))

# 细化_2a4b §1.2 默认池结构（{key,name,emoji} 三元组；框架默认 5 键 = 晴/多云/雨/雷雨/雾）
VALID_POOL: List[dict] = [
    {"key": "clear", "name": "晴", "emoji": "☀️"},
    {"key": "cloudy", "name": "多云", "emoji": "☁️"},
    {"key": "rain", "name": "雨", "emoji": "🌧️"},
    {"key": "storm", "name": "雷雨", "emoji": "⛈️"},
    {"key": "fog", "name": "雾", "emoji": "🌫️"},
]


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


def default_cfg() -> dict:
    """默认 time_cycle 配置（weather 默认池用字符串键列表形态，兼容既有 IF）。"""
    return {"time_cycle": {
        "enabled": True,
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
    }}


def dict_pool_cfg(pool: object) -> dict:
    """{key,name,emoji} 对象形态的默认池配置（细化_2a4b §1.2 / V4 校验目标形态）。"""
    return {"time_cycle": {"weather": {"weather_minutes": 60, "default_pool": pool}}}


class _Reporter:
    """与 content/validator.py `_Checker` 同签名的收集器（_err 风格）。"""

    def __init__(self) -> None:
        self.errors: List[dict] = []

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})


# -------------------------------------------------------------------------------------
# IF05 生效池（map_pool）
# -------------------------------------------------------------------------------------
def test_map_pool_default_when_no_overrides():
    wt = WorldTime(default_cfg())
    assert wt.map_pool("any_map") == sorted(DEFAULT_POOL)
    assert wt.map_pool("any_map", None) == sorted(DEFAULT_POOL)
    assert wt.map_pool("any_map", {}) == sorted(DEFAULT_POOL)  # 空映射 = 无覆盖


def test_map_pool_override_priority_sorted():
    wt = WorldTime(default_cfg())
    mp = {"misty_forest": ["rain", "fog"]}
    # 覆盖池优先；返回排序后键列表（seed 输入与配置顺序无关，细化_2a4b §6.1）
    assert wt.map_pool("misty_forest", mp) == ["fog", "rain"]


def test_map_pool_override_dict_entry_form():
    wt = WorldTime(default_cfg())
    mp = {"forest": [{"key": "fog", "name": "雾"}, {"key": "rain", "name": "雨"}]}
    assert wt.map_pool("forest", mp) == ["fog", "rain"]


def test_map_pool_empty_override_falls_back_to_default():
    wt = WorldTime(default_cfg())
    # 空数组 = 统一用默认池（R18）
    assert wt.map_pool("a", {"a": []}) == sorted(DEFAULT_POOL)
    assert wt.map_pool("a", {"a": [], "b": ["rain"]}) == sorted(DEFAULT_POOL)


def test_map_pool_missing_map_falls_back_to_default():
    wt = WorldTime(default_cfg())
    assert wt.map_pool("not_in_override", {"b": ["rain"]}) == sorted(DEFAULT_POOL)


def test_map_pool_default_dict_entry_cfg():
    wt = WorldTime(dict_pool_cfg(VALID_POOL))
    assert wt.map_pool("m") == ["clear", "cloudy", "fog", "rain", "storm"]


def test_map_pool_override_invalid_keys_falls_back():
    # 覆盖池非空但条目全非法（缺 key）→ 提取不出键 → 回退默认池（防御，不崩溃）
    wt = WorldTime(default_cfg())
    mp = {"bad": [{"emoji": "☀️"}, {"emoji": "🌧️"}]}
    assert wt.map_pool("bad", mp) == sorted(DEFAULT_POOL)


# -------------------------------------------------------------------------------------
# IF08 确定性抽签（map_weather）
# -------------------------------------------------------------------------------------
def test_map_weather_same_tick_same_value_across_instances():
    # 同 tick + 同池 → 两次同值（同实例 + 跨实例，R12 跨群/跨进程/重启一致）
    wt1 = WorldTime(default_cfg())
    wt2 = WorldTime(default_cfg())
    for tick in (0, 1, 7, 100, 9999, 233376):
        a = wt1.map_weather("m", tick)
        assert a == wt1.map_weather("m", tick)       # 同实例两次同值
        assert a == wt2.map_weather("m", tick)       # 跨实例同值
        assert a in DEFAULT_POOL                     # 命中生效池


def test_map_weather_matches_sha256_seed_formula():
    # 手算对齐（细化_2a4b §2.3 R11）：seed = sha256(生效池键排序 + str(tick))，idx = int(hex,16) % len
    wt = WorldTime(default_cfg())
    pool = sorted(DEFAULT_POOL)
    tick = 100
    seed = hashlib.sha256(("".join(pool) + str(tick)).encode("utf-8")).hexdigest()
    idx = int(seed, 16) % len(pool)
    assert wt.map_weather("m", tick) == pool[idx]
    # 覆盖池同样走同公式
    mp = {"forest": ["fog", "rain"]}
    seed2 = hashlib.sha256(("fograin" + str(tick)).encode("utf-8")).hexdigest()
    idx2 = int(seed2, 16) % 2
    assert wt.map_weather("forest", tick, map_pools=mp) == ["fog", "rain"][idx2]


def test_map_weather_different_ticks_reorder():
    # tick 前进 → 序列按新 tick 重排（TC-3：不等值不恒定）；5 键池 200 tick 内 5 键全出现
    wt = WorldTime(default_cfg())
    vals = {wt.map_weather("m", t) for t in range(200)}
    assert len(vals) > 1                      # 非恒定
    assert vals == set(DEFAULT_POOL)          # 变化充分（全池遍历）


def test_map_weather_large_tick_and_negative_stable():
    # 跨年/大 tick 稳定：weather_tick 只增不取模，大整数/负数均按公式逐字计算（确定性）
    wt = WorldTime(default_cfg())
    big = 10 ** 12
    assert wt.map_weather("m", big) == wt.map_weather("m", big)
    assert wt.map_weather("m", -7) == wt.map_weather("m", -7)
    assert len({wt.map_weather("m", big + k) for k in range(16)}) > 1  # 大 tick 区段不恒定


def test_map_weather_override_pool_result_in_override():
    # TC-6：迷雾森林 weather_pool=["fog","rain"] → 该图天气恒 ∈ {雾,雨}
    wt = WorldTime(default_cfg())
    mp = {"misty_forest": ["fog", "rain"]}
    seen = {wt.map_weather("misty_forest", t, map_pools=mp) for t in range(500)}
    assert seen <= {"fog", "rain"}
    assert len(seen) == 2  # 两键均可能抽到


def test_map_weather_empty_override_uses_default():
    # TC-8：空数组 = 默认池 → 结果 ∈ 默认池，且抽签序列 = 默认池 seed 序列
    wt = WorldTime(default_cfg())
    mp = {"a": []}
    assert all(wt.map_weather("a", t, map_pools=mp) in DEFAULT_POOL for t in range(200))
    assert all(wt.map_weather("a", t, map_pools=mp) == wt.map_weather("a", t) for t in range(50))


def test_map_weather_empty_pool_defensive():
    # 防御：默认池条目全缺 key → 生效池空 → 返回 ""（不抛异常）
    wt = WorldTime(dict_pool_cfg([{"emoji": "☀️"}, {"emoji": "🌧️"}]))
    assert wt.map_pool("m") == []
    assert wt.map_weather("m", 5) == ""


def test_weather_pool_equal_probability_all_keys_appear():
    # 等概率分布（R10）：20 键池 × 10000 tick → 20 种全出现，且大样本下无极端缺失（均匀性粗检）
    pool20 = [f"w{i:02d}" for i in range(20)]
    wt = WorldTime({"time_cycle": {"weather": {"weather_minutes": 60, "default_pool": pool20}}})
    counts: dict = {}
    for t in range(10000):
        k = wt.map_weather("m", t)
        counts[k] = counts.get(k, 0) + 1
    assert set(counts) == set(pool20)          # 20 种全出现
    assert min(counts.values()) > 100          # 均匀性粗检（期望 500/种，下限极保守）


# -------------------------------------------------------------------------------------
# IF04 天气查询（weather_now）
# -------------------------------------------------------------------------------------
def test_weather_now_uses_current_cycle_tick():
    # weather_now = map_weather(当前 weather_tick)（IF04 完整实现）
    wt = WorldTime(default_cfg())
    now = _ts(2026, 8, 16, 0, 0)
    tick = wt.cycle_tick("weather", now)
    assert wt.weather_now("m", now=now) == wt.map_weather("m", tick)
    mp = {"m": ["fog", "rain"]}
    assert wt.weather_now("m", now=now, map_pools=mp) == wt.map_weather("m", tick, map_pools=mp)
    assert wt.weather_now("m", now=now, map_pools=mp) in ["fog", "rain"]


def test_weather_now_default_current_time():
    # now 缺省 = 当前 UTC+8；同一 tick 内两次调用同值、命中生效池
    wt = WorldTime(default_cfg())
    a = wt.weather_now("m")
    b = wt.weather_now("m")
    assert a == b
    assert a in DEFAULT_POOL


# -------------------------------------------------------------------------------------
# V4 默认天气池校验（validate_weather_pool）
# -------------------------------------------------------------------------------------
def test_validate_pool_valid_zero_errors():
    r = _Reporter()
    validate_weather_pool(dict_pool_cfg(VALID_POOL), r)
    assert r.errors == []


def test_validate_pool_empty_red():
    r = _Reporter()
    validate_weather_pool(dict_pool_cfg([]), r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "V4"
    assert r.errors[0]["detail"]["rule"] == "pool_empty"
    assert r.errors[0]["detail"]["msg"] == "默认天气池至少要 1 种天气"


def test_validate_pool_dup_keys_red():
    r = _Reporter()
    pool = list(VALID_POOL) + [{"key": "rain", "name": "雨2", "emoji": "🌧️"}]
    validate_weather_pool(dict_pool_cfg(pool), r)
    dup = [e for e in r.errors if e["detail"].get("rule") == "pool_key_dup"]
    assert len(dup) == 1
    assert dup[0]["detail"]["msg"] == "默认天气池天气键重复了：rain"


def test_validate_pool_missing_name_red():
    r = _Reporter()
    pool = [{"key": "snow", "emoji": "❄️"}, {"key": "clear", "name": "晴", "emoji": "☀️"}]
    validate_weather_pool(dict_pool_cfg(pool), r)
    miss = [e for e in r.errors if e["detail"].get("rule") == "pool_name_missing"]
    assert len(miss) == 1
    assert miss[0]["detail"]["msg"] == "天气『snow』缺中文名 name"


def test_validate_pool_missing_key_red():
    r = _Reporter()
    pool = [{"name": "晴", "emoji": "☀️"}]
    validate_weather_pool(dict_pool_cfg(pool), r)
    assert any(e["detail"].get("rule") == "pool_key_missing" for e in r.errors)


def test_validate_pool_non_mapping_entry_red():
    r = _Reporter()
    validate_weather_pool(dict_pool_cfg(["clear", {"key": "rain", "name": "雨"}]), r)
    assert any(e["detail"].get("rule") == "pool_entry_type" for e in r.errors)


def test_validate_pool_not_array_red():
    r = _Reporter()
    validate_weather_pool(dict_pool_cfg("clear"), r)
    assert len(r.errors) == 1
    assert r.errors[0]["detail"]["rule"] == "pool_type"
    assert r.errors[0]["detail"]["msg"] == "默认天气池要填数组"


def test_validate_pool_multiple_errors_all_collected():
    # 一次给全（D-01 同口径）：重复键 + 缺名 两错齐发
    r = _Reporter()
    pool = [
        {"key": "clear", "name": "晴", "emoji": "☀️"},
        {"key": "clear", "name": "晴2", "emoji": "☀️"},
        {"key": "snow", "emoji": "❄️"},
    ]
    validate_weather_pool(dict_pool_cfg(pool), r)
    rules = sorted(e["detail"].get("rule") for e in r.errors)
    assert rules == ["pool_key_dup", "pool_name_missing"]


def test_validate_pool_missing_section_zero_errors():
    r = _Reporter()
    validate_weather_pool({}, r)                                # 缺整段
    validate_weather_pool({"time_cycle": {}}, r)                # 缺 weather 段
    validate_weather_pool({"time_cycle": {"weather": {}}}, r)   # 缺 default_pool 字段
    validate_weather_pool(None, r)
    assert r.errors == []


def test_validate_pool_report_errors_list_fallback():
    # 无 _err 方法的收集器：退化为 .errors 列表 append dict（主 agent 接线兼容）
    report = {"errors": []}
    validate_weather_pool(dict_pool_cfg([]), report)
    assert len(report["errors"]) == 1
    assert report["errors"][0]["kind"] == "V4"
