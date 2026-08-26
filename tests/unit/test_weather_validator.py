"""M41 天气校验器（V5-V8 接线 + 黄提示）单元测试 —— tests/unit/test_weather_validator.py

测试目标：qbot_rpg.content.weather_validator.validate_weather（M3 批次2·路I）。
依据：细化_2a4b §8（V4-V8 硬校验 + 黄提示）+ m3_shared_contract §6.2（校验器 V1–V8 + 黄提示）。
断言级别：errors=红拦（拦截）/ warnings=黄提示（不拦截）。
"""

from qbot_rpg.content.weather_validator import validate_weather
from qbot_rpg.engine.worldtime import DEFAULT_POOL


class _Report:
    """_Checker 形态收集器（_err/_warn，与 content/validator.py `_Checker` 同签名）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def _warn(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _errs(rep: _Report, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep: _Report, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


_POOL = ["clear", "cloudy", "rain", "storm", "fog"]  # 默认 5 键（= worldtime.DEFAULT_POOL）


def _cfg(**over: object) -> dict:
    tc: dict = {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(_POOL)},
        "combat": {"weather_mult": {"enabled": False, "mults": {}}},
        "broadcast": {"enabled": False, "template": "{emoji} {name}"},
    }
    tc.update(over)
    return {"time_cycle": tc}


def _mods(maps: object = None, enemies: object = None) -> dict:
    m: dict = {}
    if maps is not None:
        m["maps"] = maps
    if enemies is not None:
        m["enemies"] = enemies
    return m


# -------------------------------------------------------------------------------------
# V5 地图 weather_pool 引用 ∈ 默认池注册键（红拦）
# -------------------------------------------------------------------------------------
def test_v5_illegal_pool_red_block():
    mods = _mods(maps=[{"id": "misty_forest", "name": "迷雾森林", "weather_pool": ["snow", "hail"]}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    errs = _errs(rep, "pool_key_not_registered")
    assert len(errs) == 2
    assert all(e["kind"] == "V5" for e in errs)
    assert {e["detail"]["key"] for e in errs} == {"snow", "hail"}
    assert errs[0]["detail"]["map_id"] == "misty_forest"
    assert "没有在默认天气池里注册" in errs[0]["detail"]["msg"]


def test_v5_legal_pool_zero():
    mods = _mods(maps=[{"id": "m1", "weather_pool": ["fog", "rain"]}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert not rep.errors, f"合法覆盖池不应红拦：{rep.errors}"
    assert not rep.warnings, f"合法覆盖池（2 种）不应黄提示：{rep.warnings}"


def test_v5_empty_pool_means_default():
    mods = _mods(maps=[{"id": "m1", "weather_pool": []}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert not rep.errors  # 空数组 = 默认池（契约 §6.1）→ 零红拦
    assert not _warns(rep, "map_pool_single_constant")  # 空池不触发单种恒定提示


def test_v5_registered_keys_fallback_to_engine_default():
    # cfg 无 time_cycle → 注册集回退引擎内建 DEFAULT_POOL
    rep = _Report()
    validate_weather(_mods(maps=[{"id": "m1", "weather_pool": ["clear", "fog"]}]), {}, rep)
    assert not rep.errors and not rep.warnings
    rep2 = _Report()
    validate_weather(_mods(maps=[{"id": "m1", "weather_pool": ["snow"]}]), {}, rep2)
    assert len(_errs(rep2, "pool_key_not_registered")) == 1
    assert _errs(rep2, "pool_key_not_registered")[0]["detail"]["key"] == "snow"


def test_v5_pool_type_red():
    rep = _Report()
    validate_weather(_mods(maps=[{"id": "m1", "weather_pool": "fog"}]), _cfg(), rep)
    errs = _errs(rep, "pool_type")
    assert len(errs) == 1
    assert errs[0]["kind"] == "V5"


# -------------------------------------------------------------------------------------
# V6 消费方枚举引用（enemies special_actions 条件 / 采集点 weather_mods / lore condition）
# -------------------------------------------------------------------------------------
def test_v6_enum_red():
    mods = _mods(enemies=[{"id": "e1", "special_actions": [
        {"id": "sa1", "action": "a1", "trigger": {"type": "hp_below", "value": 50,
                                                  "condition": {"var": "season", "op": "eq",
                                                                "param": "sprin"}}},
        {"id": "sa2", "action": "a2", "trigger": {"type": "hp_below", "value": 50,
                                                  "condition": {"var": "period", "op": "eq",
                                                                "param": "midni"}}},
        {"id": "sa3", "action": "a3", "trigger": {"type": "hp_below", "value": 50,
                                                  "condition": {"var": "weather", "op": "eq",
                                                                "param": "snow"}}},
        {"id": "sa4", "action": "a4", "trigger": {"type": "hp_below", "value": 50,
                                                  "condition": {"var": "season", "op": "eq",
                                                                "param": 3}}},
    ]}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert len(_errs(rep, "season_enum_invalid")) == 1
    assert len(_errs(rep, "period_enum_invalid")) == 1
    assert len(_errs(rep, "weather_key_not_registered")) == 1
    assert len(_errs(rep, "param_invalid")) == 1
    assert all(e["kind"] == "V6" for e in rep.errors)
    assert _errs(rep, "weather_key_not_registered")[0]["detail"]["param"] == "snow"


def test_v6_bracket_forms_red():
    mods = _mods(enemies=[{"id": "e1", "lore": [
        {"unlock": 10, "desc": "图鉴一", "condition": "[天气:snow]"},
        {"unlock": 50, "desc": "图鉴二", "condition": "[季节:sprin]"},
        {"unlock": 100, "desc": "图鉴三", "condition": "[时段:midni]"},
    ]}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert len(_errs(rep, "weather_key_not_registered")) == 1
    assert len(_errs(rep, "season_enum_invalid")) == 1
    assert len(_errs(rep, "period_enum_invalid")) == 1
    assert all(e["kind"] == "V6" for e in rep.errors)
    assert all(e["detail"].get("rule") for e in rep.errors)  # 每条都带 rule


def test_v6_gather_weather_mods_red():
    mods = _mods(maps=[{"id": "m1", "gather_points": [
        {"id": "g1", "item": "i1", "rate": 0.3, "rarity": "normal",
         "weather_mods": [{"weather": "rain", "rate_mult": 1.5, "rarity_shift": 1},
                          {"weather": "snow", "rate_mult": 0}]},
    ]}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    errs = _errs(rep, "gather_weather_key_not_registered")
    assert len(errs) == 1
    assert errs[0]["kind"] == "V6"
    assert errs[0]["detail"]["weather"] == "snow"


def test_v6_legal_conditions_zero():
    mods = _mods(
        maps=[{"id": "m1", "gather_points": [
            {"id": "g1", "item": "i1", "rate": 0.3, "rarity": "normal",
             "weather_mods": [{"weather": "rain", "rate_mult": 1.5}]}]}],
        enemies=[{"id": "e1",
                  "special_actions": [{"id": "sa1", "action": "a1",
                                       "trigger": {"type": "hp_below", "value": 50,
                                                   "condition": {"var": "season", "op": "eq",
                                                                 "param": "summer"}}}],
                  "lore": [{"unlock": 10, "desc": "图鉴", "condition": "[天气:storm]"}]}],
    )
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert not rep.errors, f"合法消费方引用不应红拦：{rep.errors}"
    assert not rep.warnings, f"有消费方引用不应触发无消费方黄提示：{rep.warnings}"


# -------------------------------------------------------------------------------------
# V7 combat.weather_mult.mults 键 ∈ 注册天气集（红拦）
# -------------------------------------------------------------------------------------
def test_v7_mults_key_red():
    cfg = _cfg(combat={"weather_mult": {"enabled": True,
                                        "mults": {"rain": 0.95, "snow": 1.1}}})
    rep = _Report()
    validate_weather({}, cfg, rep)
    errs = _errs(rep, "mults_key_not_registered")
    assert len(errs) == 1
    assert errs[0]["kind"] == "V7"
    assert errs[0]["detail"]["key"] == "snow"
    assert "没有在默认天气池里注册" in errs[0]["detail"]["msg"]


def test_v7_mults_all_registered_zero():
    cfg = _cfg(combat={"weather_mult": {"enabled": True,
                                        "mults": {"rain": 0.95, "storm": 1.1, "fog": 0.9}}})
    rep = _Report()
    validate_weather({}, cfg, rep)
    assert not rep.errors, f"全注册 mults 键不应红拦：{rep.errors}"
    assert not _warns(rep, "no_consumer_refs")  # mults 键计入消费方引用


def test_v7_mults_not_object_red():
    cfg = _cfg(combat={"weather_mult": {"enabled": True, "mults": "rain"}})
    rep = _Report()
    validate_weather({}, cfg, rep)
    assert len(_errs(rep, "mults_not_object")) == 1
    assert _errs(rep, "mults_not_object")[0]["kind"] == "V7"


# -------------------------------------------------------------------------------------
# V8 broadcast.template 占位符 ∈ {type,name,emoji,map}（红拦）
# -------------------------------------------------------------------------------------
def test_v8_template_placeholder_red():
    cfg = _cfg(broadcast={"enabled": True, "template": "{type} {name} {emoji} {map} {hp}"})
    rep = _Report()
    validate_weather({}, cfg, rep)
    errs = _errs(rep, "template_placeholder_invalid")
    assert len(errs) == 1
    assert errs[0]["kind"] == "V8"
    assert errs[0]["detail"]["placeholder"] == "hp"


def test_v8_template_legal_zero():
    cfg = _cfg(broadcast={"enabled": True, "template": "{emoji} {name}"})
    rep = _Report()
    validate_weather({}, cfg, rep)
    assert not rep.errors, f"合法模板不应红拦：{rep.errors}"


def test_v8_template_type_red():
    cfg = _cfg(broadcast={"enabled": True, "template": 123})
    rep = _Report()
    validate_weather({}, cfg, rep)
    assert len(_errs(rep, "template_type")) == 1
    assert _errs(rep, "template_type")[0]["kind"] == "V8"


# -------------------------------------------------------------------------------------
# 黄提示（不拦截）六条各自触发
# -------------------------------------------------------------------------------------
def test_w1_season_days_365():
    rep = _Report()
    validate_weather({}, _cfg(season={"season_days": 365}), rep)
    warns = _warns(rep, "season_days_full_year")
    assert len(warns) == 1
    assert warns[0]["detail"]["days"] == 365
    assert "全季节 1 天轮换" in warns[0]["detail"]["msg"]


def test_w2_period_minutes_1440():
    rep = _Report()
    validate_weather({}, _cfg(period={"period_minutes": 1440}), rep)
    assert len(_warns(rep, "period_minutes_full_day")) == 1
    assert _warns(rep, "period_minutes_full_day")[0]["detail"]["minutes"] == 1440


def test_w3_pool_too_many():
    big = [f"w{i}" for i in range(13)]
    rep = _Report()
    validate_weather({}, _cfg(weather={"weather_minutes": 60, "default_pool": big}), rep)
    warns = _warns(rep, "pool_too_many")
    assert len(warns) == 1
    assert warns[0]["detail"]["size"] == 13
    assert not rep.errors  # 黄提示不拦截


def test_w4_pool_single_constant_default():
    rep = _Report()
    validate_weather({}, _cfg(weather={"weather_minutes": 60, "default_pool": ["fog"]}), rep)
    assert len(_warns(rep, "pool_single_constant")) == 1
    assert not rep.errors


def test_w4_map_pool_single_constant():
    mods = _mods(maps=[{"id": "m1", "weather_pool": ["fog"]}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert len(_warns(rep, "map_pool_single_constant")) == 1
    assert not rep.errors


def test_w5_no_consumer_refs():
    mods = _mods(maps=[{"id": "m1", "monsters": []}], enemies=[{"id": "e1"}])
    rep = _Report()
    validate_weather(mods, _cfg(), rep)
    assert len(_warns(rep, "no_consumer_refs")) == 1
    # 有消费方引用（地图覆盖池）→ 不提示
    mods2 = _mods(maps=[{"id": "m1", "weather_pool": ["fog", "rain"]}])
    rep2 = _Report()
    validate_weather(mods2, _cfg(), rep2)
    assert not _warns(rep2, "no_consumer_refs")


def test_w6_pool_config_reorder():
    cfg = _cfg(weather={"weather_minutes": 60,
                        "default_pool": ["clear", "cloudy", "rain", "storm", "snow"]})
    rep = _Report()
    validate_weather({}, cfg, rep)
    warns = _warns(rep, "pool_config_reorder")
    assert len(warns) == 1
    assert "重新铺排" in warns[0]["detail"]["msg"]
    # 显式配置 = 引擎内建集合 → 非变更 → 不提示
    rep2 = _Report()
    validate_weather({}, _cfg(), rep2)
    assert not _warns(rep2, "pool_config_reorder")
    assert set(DEFAULT_POOL) == set(_POOL)  # 测试基线与引擎内建池一致


# -------------------------------------------------------------------------------------
# 收集器鸭子类型 + 边界
# -------------------------------------------------------------------------------------
class _MethodReport:
    """error/warning 方法形态收集器（map_models 测试同款鸭子类型）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


class _ListReport:
    """errors/warnings 列表形态收集器（worldtime validate_time_cycle 同款）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []


def test_duck_typing_method_report():
    mods = _mods(maps=[{"id": "m1", "weather_pool": ["snow"]}])
    rep = _MethodReport()
    validate_weather(mods, _cfg(), rep)
    assert len(rep.errors) == 1 and rep.errors[0]["kind"] == "V5"
    assert len(rep.warnings) == 1  # 覆盖池 1 种 → 恒定黄提示
    assert rep.warnings[0]["detail"]["rule"] == "map_pool_single_constant"


def test_duck_typing_list_report():
    cfg = _cfg(combat={"weather_mult": {"enabled": True, "mults": {"snow": 1.1}}})
    rep = _ListReport()
    validate_weather({}, cfg, rep)
    assert len(rep.errors) == 1 and rep.errors[0]["kind"] == "V7"
    assert rep.warnings == []  # mults 键计入消费方引用 → 无 W5


def test_validate_weather_none_safe():
    rep = _Report()
    validate_weather(None, None, rep)  # type: ignore[arg-type]
    assert not rep.errors and not rep.warnings


def test_legal_full_config_zero():
    mods = _mods(
        maps=[{"id": "m1", "weather_pool": ["fog", "rain"],
               "gather_points": [{"id": "g1", "item": "i1", "rate": 0.3, "rarity": "normal",
                                  "weather_mods": [{"weather": "rain", "rate_mult": 1.5}]}]}],
        enemies=[{"id": "e1",
                  "special_actions": [{"id": "sa1", "action": "a1",
                                       "trigger": {"type": "hp_below", "value": 50,
                                                   "condition": {"var": "weather", "op": "eq",
                                                                 "param": "storm"}}}],
                  "lore": [{"unlock": 10, "desc": "图鉴", "condition": "[时段:midnight]"}]}],
    )
    cfg = _cfg(combat={"weather_mult": {"enabled": True, "mults": {"storm": 1.1}}})
    rep = _Report()
    validate_weather(mods, cfg, rep)
    assert not rep.errors, f"合法全量配置不应红拦：{rep.errors}"
    assert not rep.warnings, f"合法全量配置不应黄提示：{rep.warnings}"
