"""M3 批次2·路H（M40）：条件键三键注册求值测试 —— qbot_rpg.engine.weather_conditions。

依据：细化_2a4b §4/§5（[天气:X] R28~R32）+ 细化_2a4c §2（条件键接入：注册/求值接线/V6）
      + m3_shared_contract §5.4（条件键三键）+/§6.2 V6（消费方枚举引用红拦）
      + 2a1d LC-D（求值失败默认不满足，fail-safe）。

测试口径（对齐 test_maps_schema 风格）：构造输入 → 跑纯函数 → 断言结果。
  - eval_condition(cond, ctx)：ctx 取季节/时段直接值或 worldtime 实例桩（IF02~IF04 形态）；
    天气按 map_id 上下文绑定（TC-14 口径）。
  - validate_condition_keys(cond, report, registered_weather)：收集器鸭子类型 _Report +
    一条真实 validator._Checker 收口兼容测试。
"""
from __future__ import annotations

import pytest

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import _Checker
from qbot_rpg.engine.weather_conditions import (
    PERIOD_KEYS,
    REGISTERED_KEYS,
    SEASON_KEYS,
    eval_condition,
    validate_condition_keys,
)
from qbot_rpg.engine.worldtime import ANCHOR, WorldTime


# ---------------------------------------------------------------------------
# 夹具：世界时钟桩（IF02~IF04 形态；weather_now 即批次 2 IF04 落地后的签名）
# ---------------------------------------------------------------------------
class _StubWorldTime:
    """季节/时段固定 + 按图天气表（同 tick 不同图可不同天气，TC-14 上下文绑定）。"""

    def __init__(self, season: str = "summer", period: str = "night", weather: dict | None = None):
        self._season = season
        self._period = period
        self._weather = dict(weather or {"misty_forest": "rain", "crag_den": "clear"})

    def season_now(self, now=None) -> str:
        return self._season

    def period_now(self, now=None) -> str:
        return self._period

    def weather_now(self, map_id: str, now=None) -> str:
        return self._weather.get(map_id, "clear")


class _Report:
    """validate_condition_keys 收集器（鸭子类型：_err 与 validator._Checker 同签名）。"""

    def __init__(self) -> None:
        self.errors: list = []

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _errs(rep: _Report, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


# ---------------------------------------------------------------------------
# 固定枚举与注册表（防碎片化：与 worldtime.SEASONS/PERIODS 同源）
# ---------------------------------------------------------------------------
def test_season_keys_fixed_enum() -> None:
    assert SEASON_KEYS == ("spring", "summer", "autumn", "winter")


def test_period_keys_fixed_enum() -> None:
    assert PERIOD_KEYS == ("dawn", "noon", "dusk", "night", "midnight")


def test_registered_keys_shape() -> None:
    # weather 值域动态（内容包自定义）→ None 表示由收口经 registered_weather 注入
    assert set(REGISTERED_KEYS) == {"season", "period", "weather"}
    assert REGISTERED_KEYS["season"] is SEASON_KEYS
    assert REGISTERED_KEYS["period"] is PERIOD_KEYS
    assert REGISTERED_KEYS["weather"] is None


# ---------------------------------------------------------------------------
# 季节求值（全局值：直接值 / worldtime 实例）
# ---------------------------------------------------------------------------
def test_season_hit_via_direct_value() -> None:
    cond = {"var": "season", "op": "eq", "param": "summer"}
    assert eval_condition(cond, {"season_now": "summer"}) is True


def test_season_miss_via_direct_value() -> None:
    cond = {"var": "season", "op": "eq", "param": "winter"}
    assert eval_condition(cond, {"season_now": "summer"}) is False


def test_season_via_worldtime_instance() -> None:
    wt = _StubWorldTime(season="summer")
    assert eval_condition({"var": "season", "param": "summer"}, {"worldtime": wt}) is True
    assert eval_condition({"var": "season", "param": "spring"}, {"worldtime": wt}) is False


def test_season_via_real_worldtime_engine() -> None:
    # 真实 WorldTime（IF02）：now=ANCHOR → 春季（0 基 0春）· 晨（0 基 0晨）
    wt = WorldTime({})
    ctx = {"worldtime": wt, "now": ANCHOR}
    assert eval_condition({"var": "season", "op": "eq", "param": "spring"}, ctx) is True
    assert eval_condition({"var": "season", "op": "eq", "param": "summer"}, ctx) is False


# ---------------------------------------------------------------------------
# 时段求值（全局值：直接值 / worldtime 实例）
# ---------------------------------------------------------------------------
def test_period_hit_and_miss_via_direct_value() -> None:
    ctx = {"period_now": "midnight"}
    assert eval_condition({"var": "period", "op": "eq", "param": "midnight"}, ctx) is True
    assert eval_condition({"var": "period", "op": "eq", "param": "dusk"}, ctx) is False


def test_period_via_worldtime_instance() -> None:
    wt = _StubWorldTime(period="night")
    assert eval_condition({"var": "period", "param": "night"}, {"worldtime": wt}) is True
    assert eval_condition({"var": "period", "param": "noon"}, {"worldtime": wt}) is False


# ---------------------------------------------------------------------------
# 天气求值（上下文绑定：按玩家当前所在图取值，TC-13/TC-14）
# ---------------------------------------------------------------------------
def test_weather_by_map_context_binding() -> None:
    # 同一时刻：A 图雨、B 图晴（TC-14）——A 图玩家 [天气:雨]=true，B 图玩家=false
    wt = _StubWorldTime(weather={"misty_forest": "rain", "crag_den": "clear"})
    cond = {"var": "weather", "op": "eq", "param": "rain"}
    assert eval_condition(cond, {"worldtime": wt, "map_id": "misty_forest"}) is True
    assert eval_condition(cond, {"worldtime": wt, "map_id": "crag_den"}) is False


def test_weather_via_direct_weather_now() -> None:
    cond = {"var": "weather", "op": "eq", "param": "storm"}
    assert eval_condition(cond, {"weather_now": "storm"}) is True
    assert eval_condition(cond, {"weather_now": "rain"}) is False


# ---------------------------------------------------------------------------
# op 兼容 / 简写归一（2a4c TC-18：简写 {var,param:X} 与完整形等价）
# ---------------------------------------------------------------------------
def test_op_eq_and_double_eq_compatible() -> None:
    ctx = {"season_now": "summer"}
    assert eval_condition({"var": "season", "op": "==", "param": "summer"}, ctx) is True
    assert eval_condition({"var": "season", "op": "eq", "param": "summer"}, ctx) is True


def test_op_missing_defaults_eq_shorthand() -> None:
    # 简写 {var, param:X}（2a4c §2.1 L178-180 简写归一）求值等价完整形
    assert eval_condition({"var": "season", "param": "summer"}, {"season_now": "summer"}) is True


def test_op_unsupported_returns_false() -> None:
    assert eval_condition({"var": "season", "op": "gt", "param": "summer"},
                          {"season_now": "summer"}) is False


# ---------------------------------------------------------------------------
# 未知 var / 非法 param / 缺上下文 → False（fail-safe，不抛错；2a1d LC-D）
# ---------------------------------------------------------------------------
def test_unknown_var_failsafe() -> None:
    assert eval_condition({"var": "level", "op": "eq", "param": 5}, {"season_now": "summer"}) is False


def test_illegal_season_param_failsafe() -> None:
    assert eval_condition({"var": "season", "op": "eq", "param": "friday"},
                          {"season_now": "summer"}) is False


def test_illegal_period_param_failsafe() -> None:
    assert eval_condition({"var": "period", "op": "eq", "param": "afternoon"},
                          {"period_now": "noon"}) is False


def test_weather_param_non_string_failsafe() -> None:
    assert eval_condition({"var": "weather", "op": "eq", "param": 123},
                          {"weather_now": "rain"}) is False
    assert eval_condition({"var": "weather", "op": "eq", "param": ""},
                          {"weather_now": "rain"}) is False


def test_missing_context_failsafe() -> None:
    # 无 worldtime / 无 map_id / 无直接值 → False（不抛错）
    assert eval_condition({"var": "season", "op": "eq", "param": "summer"}, {}) is False
    assert eval_condition({"var": "weather", "op": "eq", "param": "rain"},
                          {"worldtime": _StubWorldTime()}) is False  # 缺 map_id
    assert eval_condition({"var": "weather", "op": "eq", "param": "rain"},
                          {"map_id": "misty_forest"}) is False  # 缺 worldtime


def test_non_mapping_inputs_failsafe() -> None:
    assert eval_condition(None, {"season_now": "summer"}) is False
    assert eval_condition({"var": "season", "param": "summer"}, None) is False


def test_value_key_not_participating() -> None:
    # 2a4c §2.1 L100：三键 value 不参与（eq+param 判定）→ 只写 value 视为无 param → False
    assert eval_condition({"var": "season", "op": "eq", "value": "summer"},
                          {"season_now": "summer"}) is False


# ---------------------------------------------------------------------------
# 校验器 V6：param 非法枚举 → 红拦（供收口接 check_pack）
# ---------------------------------------------------------------------------
def test_validate_legal_cond_no_error() -> None:
    rep = _Report()
    validate_condition_keys({"var": "season", "op": "eq", "param": "summer"}, rep)
    validate_condition_keys({"var": "period", "op": "eq", "param": "midnight"}, rep)
    validate_condition_keys({"var": "weather", "op": "eq", "param": "storm"}, rep,
                            registered_weather=["clear", "cloudy", "rain", "storm", "fog"])
    assert rep.errors == []


def test_validate_illegal_season_enum_red_block() -> None:
    rep = _Report()
    validate_condition_keys({"var": "season", "op": "eq", "param": "friday"}, rep)
    errs = _errs(rep, "season_enum_invalid")
    assert len(errs) == 1
    assert errs[0]["detail"]["param"] == "friday"


def test_validate_illegal_period_enum_red_block() -> None:
    rep = _Report()
    validate_condition_keys({"var": "period", "op": "eq", "param": "afternoon"}, rep)
    assert len(_errs(rep, "period_enum_invalid")) == 1


def test_validate_unknown_var_red_block() -> None:
    rep = _Report()
    validate_condition_keys({"var": "codex", "op": "eq", "param": "storm"}, rep)
    assert len(_errs(rep, "var_not_registered")) == 1


def test_validate_op_not_eq_red_block() -> None:
    rep = _Report()
    validate_condition_keys({"var": "season", "op": "gt", "param": "summer"}, rep)
    assert len(_errs(rep, "op_not_eq")) == 1


def test_validate_weather_key_not_registered_red_block() -> None:
    rep = _Report()
    validate_condition_keys({"var": "weather", "op": "eq", "param": "snow"}, rep,
                            registered_weather=["clear", "cloudy", "rain", "storm", "fog"])
    errs = _errs(rep, "weather_key_not_registered")
    assert len(errs) == 1
    assert errs[0]["detail"]["param"] == "snow"
    assert "rain" in errs[0]["detail"]["registered"]


def test_validate_weather_skipped_without_registry() -> None:
    # 收口未注入注册天气集 → 天气键值域校验跳过（LC-D 不崩）；季节/时段仍恒校验
    rep = _Report()
    validate_condition_keys({"var": "weather", "op": "eq", "param": "snow"}, rep)
    assert rep.errors == []
    validate_condition_keys({"var": "season", "op": "eq", "param": "friday"}, rep)
    assert len(rep.errors) == 1


def test_validate_cond_list_checks_each_entry() -> None:
    # 多条件 AND 列表（2a1d LC-C）逐项校验：一项坏 → 一项红拦
    rep = _Report()
    validate_condition_keys([
        {"var": "period", "op": "eq", "param": "midnight"},
        {"var": "weather", "op": "eq", "param": "storm"},
        {"var": "season", "op": "eq", "param": "friday"},
    ], rep, registered_weather=["storm"])
    assert len(rep.errors) == 1
    assert _errs(rep, "season_enum_invalid")


def test_validate_non_object_red_block() -> None:
    rep = _Report()
    validate_condition_keys("storm", rep)
    assert len(_errs(rep, "condition_not_object")) == 1


def test_validate_checker_integration() -> None:
    """收口兼容：直传真实 validator._Checker（_err 鸭子路径）红拦落 errors。"""
    checker = _Checker({}, default_field_meta_table())
    validate_condition_keys({"var": "weather", "op": "eq", "param": "snow"}, checker,
                            registered_weather=["clear", "rain"])
    assert len(checker.errors) == 1
    assert checker.errors[0].kind == "V6"
    assert checker.errors[0].detail["rule"] == "weather_key_not_registered"