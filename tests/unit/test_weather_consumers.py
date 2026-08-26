"""M3 批次2·路H（M39）：天气消费方联动测试 —— qbot_rpg.engine.weather_consumers。

依据：细化_2a4b §4（4.3 采集 weather_mods R25 / 4.4 战斗 combat.weather_mult R26）
      + 细化_2a1d（§一 GP-08~GP-11 weather_mods 字段 / §三 LC-01~LC-04 lore.condition）
      + m3_shared_contract §6.1（消费方联动：weather_mods / combat.weather_mult 默认关 /
        lore condition）+ 2a1d LC-D（求值失败默认不满足）。

测试口径（对齐 test_maps_schema 风格）：构造输入 → 跑纯函数 → 断言结果。
  - weather_mods 双形态：归一 dict {天气:{"rate_mult","rarity_shift"}} 与 2a1d GP-08
    列表形态 [{weather, rate_mult, rarity_shift}] 均兼容。
  - 稀有度档位 clamp 4 档（normal/rare/gold/awakened）。
  - combat.weather_mult 默认关 → 1.0；开启取 mults[天气]（缺省 1.0）。
  - lore_visible 缺省显示 True；condition 求值按当前图天气（fail-safe False）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.engine.weather_consumers import (
    RARITY_TIERS,
    apply_weather_mods,
    combat_weather_mult,
    lore_visible,
)
from qbot_rpg.engine.worldtime import ANCHOR, WorldTime

# 2a1d GP-08 列表形态样例（细化_2a4b §4.3 原样）
_LIST_MODS = [
    {"weather": "rain", "rate_mult": 1.5, "rarity_shift": 1},
    {"weather": "storm", "rate_mult": 0},
]

# 同义归一 dict 形态（任务签名）
_DICT_MODS = {
    "rain": {"rate_mult": 1.5, "rarity_shift": 1},
    "storm": {"rate_mult": 0},
}


# ---------------------------------------------------------------------------
# apply_weather_mods：rate_mult 乘出率 + rarity_shift 平移档位（clamp 4 档）
# ---------------------------------------------------------------------------
def test_mods_dict_form_rain_hit() -> None:
    rate, rarity = apply_weather_mods(0.3, "rare", _DICT_MODS, "rain")
    assert rate == pytest.approx(0.45)  # 0.3 × 1.5（TC-02 期望出率）
    assert rarity == "gold"  # rare +1 → gold


def test_mods_list_form_same_as_dict() -> None:
    # 2a1d GP-08 列表形态与归一 dict 同语义（收口可直传配置原文）
    rate, rarity = apply_weather_mods(0.3, "rare", _LIST_MODS, "rain")
    assert rate == pytest.approx(0.45)
    assert rarity == "gold"


def test_mods_zero_rate_means_not_spawn() -> None:
    rate, rarity = apply_weather_mods(0.3, "rare", _DICT_MODS, "storm")
    assert rate == 0.0  # rate_mult 0 = 该天气不出
    assert rarity == "rare"  # rarity_shift 缺省 0 → 原值


def test_mods_no_config_for_weather_returns_original() -> None:
    rate, rarity = apply_weather_mods(0.3, "gold", _DICT_MODS, "fog")
    assert rate == pytest.approx(0.3)
    assert rarity == "gold"


def test_mods_empty_or_none_returns_original() -> None:
    assert apply_weather_mods(0.3, "rare", {}, "rain") == (0.3, "rare")
    assert apply_weather_mods(0.3, "rare", None, "rain") == (0.3, "rare")
    assert apply_weather_mods(0.3, "rare", _DICT_MODS, "") == (0.3, "rare")  # 无当前天气


def test_mods_rarity_shift_clamp_top_and_bottom() -> None:
    # clamp 4 档：+5 顶到 awakened；−5 底到 normal
    rate, rarity = apply_weather_mods(0.3, "normal", {"x": {"rate_mult": 1, "rarity_shift": 5}}, "x")
    assert rarity == "awakened"
    rate, rarity = apply_weather_mods(0.3, "normal", {"x": {"rate_mult": 1, "rarity_shift": -5}}, "x")
    assert rarity == "normal"


def test_mods_unknown_base_rarity_unchanged() -> None:
    # 未知档位 → 原值返回（fail-safe 不平移不报错）
    rate, rarity = apply_weather_mods(0.3, "mythic", _DICT_MODS, "rain")
    assert rate == pytest.approx(0.45)
    assert rarity == "mythic"


def test_mods_missing_rate_mult_defaults_one() -> None:
    rate, rarity = apply_weather_mods(0.4, "normal", {"fog": {"rarity_shift": 2}}, "fog")
    assert rate == pytest.approx(0.4)  # rate_mult 缺省 1
    assert rarity == "gold"  # normal +2 → gold


def test_mods_negative_shift_downgrades() -> None:
    rate, rarity = apply_weather_mods(0.3, "gold", {"rain": {"rate_mult": 1, "rarity_shift": -1}}, "rain")
    assert rarity == "rare"


def test_rarity_tiers_four_levels() -> None:
    assert RARITY_TIERS == ("normal", "rare", "gold", "awakened")


# ---------------------------------------------------------------------------
# combat_weather_mult：默认关 → 1.0；开启取 mults[天气]（缺省 1.0）；不改公式
# ---------------------------------------------------------------------------
_COMBAT_ON = {"weather_mult": {"enabled": True,
                               "mults": {"rain": 0.95, "storm": 1.1, "fog": 0.9}}}
_COMBAT_OFF = {"weather_mult": {"enabled": False,
                                "mults": {"rain": 0.95, "storm": 1.1}}}


def test_combat_default_off_no_cfg() -> None:
    assert combat_weather_mult(None, "storm") == 1.0
    assert combat_weather_mult({}, "storm") == 1.0
    assert combat_weather_mult({"other": 1}, "storm") == 1.0  # 缺 weather_mult 段


def test_combat_enabled_false_returns_one() -> None:
    assert combat_weather_mult(_COMBAT_OFF, "storm") == 1.0  # 默认关（R26）
    assert combat_weather_mult({"weather_mult": {"mults": {"rain": 0.9}}}, "rain") == 1.0


def test_combat_enabled_true_takes_value() -> None:
    assert combat_weather_mult(_COMBAT_ON, "storm") == pytest.approx(1.1)
    assert combat_weather_mult(_COMBAT_ON, "rain") == pytest.approx(0.95)


def test_combat_enabled_true_missing_weather_defaults_one() -> None:
    assert combat_weather_mult(_COMBAT_ON, "clear") == 1.0  # 未配天气 → 缺省 1.0


def test_combat_bad_config_failsafe() -> None:
    assert combat_weather_mult({"weather_mult": {"enabled": True, "mults": {"rain": 0}}}, "rain") == 1.0
    assert combat_weather_mult({"weather_mult": {"enabled": True, "mults": {"rain": "abc"}}}, "rain") == 1.0
    assert combat_weather_mult({"weather_mult": {"enabled": "yes", "mults": {"rain": 1.5}}}, "rain") == 1.0
    assert combat_weather_mult(_COMBAT_ON, None) == 1.0  # 无当前天气


# ---------------------------------------------------------------------------
# lore_visible：图鉴 lore/codex condition 按当前图天气判定（缺省显示 True）
# ---------------------------------------------------------------------------
def test_lore_default_visible() -> None:
    assert lore_visible(None, "rain", {}) is True
    assert lore_visible({}, "rain", {}) is True
    assert lore_visible([], "rain", {}) is True


def test_lore_single_weather_condition() -> None:
    cond = {"var": "weather", "op": "eq", "param": "storm"}
    assert lore_visible(cond, "storm", {}) is True   # 雷雨天显示（TC-09）
    assert lore_visible(cond, "clear", {}) is False  # 晴天不显示


def test_lore_multi_condition_and() -> None:
    # 午夜雷雨双条件事件（2a4b R31 AND 叠加）
    conds = [
        {"var": "period", "op": "eq", "param": "midnight"},
        {"var": "weather", "op": "eq", "param": "storm"},
    ]
    ctx = {"period_now": "midnight"}
    assert lore_visible(conds, "storm", ctx) is True
    assert lore_visible(conds, "rain", ctx) is False   # 天气不满足
    assert lore_visible(conds, "storm", {"period_now": "noon"}) is False  # 时段不满足


def test_lore_season_condition_via_ctx() -> None:
    cond = {"var": "season", "op": "eq", "param": "summer"}
    assert lore_visible(cond, "clear", {"season_now": "summer"}) is True
    assert lore_visible(cond, "clear", {"season_now": "winter"}) is False


def test_lore_no_weather_source_failsafe() -> None:
    # 上下文无任何天气源（无 ctx、无 current_weather）→ 不满足（LC-D fail-safe）
    cond = {"var": "weather", "op": "eq", "param": "storm"}
    assert lore_visible(cond, None, {}) is False
    assert lore_visible(cond, "", {}) is False


def test_lore_ctx_explicit_weather_wins() -> None:
    # 优先级：ctx["weather_now"] 显式键 > current_weather 参数
    cond = {"var": "weather", "op": "eq", "param": "rain"}
    assert lore_visible(cond, "storm", {"weather_now": "rain"}) is True
    assert lore_visible(cond, "rain", {"weather_now": "clear"}) is False


def test_lore_real_worldtime_ctx() -> None:
    # ctx 提供真实 WorldTime + map_id：当前图天气经 IF04 兜底取值
    cond = {"var": "weather", "op": "eq", "param": "spring"}
    wt = WorldTime({})
    # weather_now 属批次 2 IF08 落地后方法；真实 WorldTime 尚无 → 无天气源 → 不满足（fail-safe）
    assert lore_visible(cond, None, {"worldtime": wt, "map_id": "x", "now": ANCHOR}) is False


def test_lore_bad_entry_failsafe() -> None:
    # 列表中混入非条件对象 → 该条不满足（LC-D）
    assert lore_visible([{"var": "weather", "param": "rain"}, "junk"], "rain", {}) is False
    # 非 dict/列表形态 = 坏配置 → 不显示
    assert lore_visible("storm", "storm", {}) is False


def test_lore_unknown_var_failsafe() -> None:
    assert lore_visible({"var": "codex", "op": "eq", "param": "x"}, "clear", {}) is False