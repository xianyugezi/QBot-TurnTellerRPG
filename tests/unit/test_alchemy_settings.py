"""M8 批次0B·路0B：settings.alchemy 段专项校验（ALC-01~24）+ slots 模块校验 + items 扩展字段 测试。

文件：tests/unit/test_alchemy_settings.py
创建：2026-08-29
作者：Hermes 子agent-0B
功能：覆盖 qbot_rpg.content.alchemy_settings：
  - check_settings_alchemy（ALC-01~24 每规则正反例；红拦=errors / 黄提示=warnings 分开断言；
    settings 缺 alchemy 段/空段 → 默认值兜底不报错）
  - validate_slots（equip_id 引用 / slots 1-3 个 / slot_level ∈1-3 正反例）
  - ITEMS_ALCHEMY_FIELDS / SLOTS_FIELD_DEFS / ALCHEMY_SETTINGS_FIELD_DEFS 结构
  - 真实 validator._Checker 收口兼容（鸭子类型 _err/_warn 路径）

依据：docs/m8_contract_数据与校验.md §四 4.1/4.2 + §五 + §六 6.2（ALC-01~24）
+ §十 B1~B5 用户 5 项拍板（键集 common/uncommon/rare/legendary / 分解宝石平铺 /
珠升阶无门槛 / 复制费 cost.coins / int32 数量上限）。
测试口径（对齐 test_shop_models.py）：纯函数 + report 鸭子类型（本文件 _Report 收集器；
另含真实 _Checker 收口兼容测试）；断言 errors=红拦 / warnings=黄提示。
"""
from __future__ import annotations

from qbot_rpg.content.alchemy_settings import (
    ALCHEMY_ELEMENTS,
    ALCHEMY_SETTINGS_FIELD_DEFS,
    BATTLE_ALCHEMY_KEY,
    BATTLE_ITEM_KEY,
    DECOMPOSE_FORMULA_ENUM,
    DECOMPOSE_TIER_NAMES,
    GEM_DECOMPOSE_FORMULA_KEY,
    GEM_DECOMPOSE_KEY,
    GEM_DUPLICATE_KEY,
    GEM_EXTRA_ALIAS,
    GEM_EXTRA_KEY,
    GEM_SECRET_KEY,
    ITEM_RARITY_KEYS,
    ITEMS_ALCHEMY_FIELDS,
    JOB_TIER_NAMES,
    MAX_QTY_DEFAULT,
    MODE_VALUES,
    QUALITY_KEYS,
    QUALITY_TIER_COUNTS,
    SLOTS_FIELD_DEFS,
    alchemy_settings_meta,
    check_settings_alchemy,
    slots_module_meta,
    validate_slots,
)
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import _Checker


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
class _Report:
    """check_settings_alchemy / validate_slots 收集器（鸭子类型：error/warning 与
    validator._Checker._err/_warn 签名一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def note(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.notes.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _legal_settings() -> dict:
    """合法全量 settings.alchemy 段（契约 §五 全字段，含拍板②④⑤默认；零红拦零黄）。"""
    return {
        "alchemy": {
            "mode": "full",
            "quality_tiers": {
                "common": [0, 39], "uncommon": [40, 59], "rare": [60, 79], "legendary": [80, 100],
            },
            "quality_coef": {"common": 0.8, "uncommon": 1.0, "rare": 1.2, "legendary": 1.5},
            "chain_map": {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6},
            "pp_cost": {"normal": 1, "super": 2},
            "pp_refresh": "会话重置",
            "energy_enabled": False,
            "energy_max": {
                "见习": 5, "正式": 8, "精通": 10, "专家": 12,
                "大师": 15, "宗师": 18, "王": 20,
            },
            "energy_regen_sec": 1800,
            "energy_regen_sec_safe": 900,
            "decompose_rate": {
                "正式": 0.4, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.65,
            },
            "catalyst_unlock_tier": "expert",
            "catalyst_consume": True,
            "gem.分解": {"common": 1, "uncommon": 3, "rare": 8, "legendary": 20},
            "gem.复制": 0.2,
            "gem.成品合成": 10,
            "gem.配方合成": 5,
            "gem.特性合成": 20,
            "gem.珠升阶": 10,
            "gem_diminish": [{"n": 2, "mult": 0.5}, {"n": 3, "mult": 0.25}],
            "synth_exp": "配方等级×1",
            "sp_per_level": 1,
            "sp_panel": [
                {"id": "quality_cap_10", "name": "品质上限+10", "cost": 1,
                 "repeatable": True, "max_repeat": 2},
                {"id": "invest_count_1", "name": "投入次数+1", "cost": 1,
                 "repeatable": True, "max_repeat": 3},
                {"id": "gather_1", "name": "采集量+1", "cost": 1,
                 "repeatable": False, "max_repeat": 1},
                {"id": "chain_1", "name": "连锁上限+1", "cost": 1,
                 "repeatable": False, "max_repeat": 1},
            ],
            "战斗道具": {"强度公式": "技能×(1+0.4×冷却数)", "珠触发上限": 3},
            "战斗即时调合": {"auto_use": True, "per_battle_limit": 1},
            "max_qty": MAX_QTY_DEFAULT,
            "job_tier_map": {
                "见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
                "大师": [31, 40], "宗师": [41, 50], "王": [51, 100],
            },
        },
    }


def _check(**overrides: object) -> _Report:
    """合法 settings；alchemy 段键级覆盖 → 跑 check_settings_alchemy。"""
    s = _legal_settings()
    for k, v in overrides.items():
        s["alchemy"][k] = v
    rep = _Report()
    check_settings_alchemy(s, rep)
    return rep


def _errs(rep: _Report, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep: _Report, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


# ---------------------------------------------------------------------------
# 合法全量 schema 零红拦 + 段缺失兜底 + _Checker 收口兼容
# ---------------------------------------------------------------------------
def test_legal_alchemy_zero_report() -> None:
    """合法全量 alchemy 段 → 零红拦零黄。"""
    rep = _check()
    assert not rep.errors, f"合法 alchemy 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 alchemy 应为零黄提示：{rep.warnings}"


def test_alchemy_section_missing_or_empty_fallback() -> None:
    """settings 缺 alchemy 段 / 段为空 → 默认值兜底判定，不报错（契约 §五 段默认值兜底）。"""
    rep = _Report()
    check_settings_alchemy({}, rep)
    assert not rep.errors and not rep.warnings
    check_settings_alchemy({"currencies": []}, rep)
    assert not rep.errors and not rep.warnings
    check_settings_alchemy({"alchemy": {}}, rep)
    assert not rep.errors and not rep.warnings
    check_settings_alchemy("settings", rep)  # type: ignore[arg-type]  # data 非 Mapping → 静默返回
    assert not rep.errors and not rep.warnings


def test_alchemy_section_not_object() -> None:
    """alchemy 段存在但非对象 → ALC-STRUCT 红拦（【工程补白 P-8】结构性防御）。"""
    rep = _Report()
    check_settings_alchemy({"alchemy": [1, 2]}, rep)
    assert len(rep.errors) == 1
    assert rep.errors[0]["detail"]["rule"] == "alchemy_not_object"
    assert not rep.warnings


def test_alchemy_checker_integration() -> None:
    """收口兼容：check_settings_alchemy 直传真实 validator._Checker（_err/_warn 鸭子路径）。"""
    modules = {"settings": _legal_settings()}
    checker = _Checker(modules, default_field_meta_table())
    check_settings_alchemy(modules["settings"], checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"
    # 负例：非法 mode 直传 _Checker → 红拦进入 checker.errors
    modules2 = {"settings": {"alchemy": {"mode": "bogus"}}}
    checker2 = _Checker(modules2, default_field_meta_table())
    check_settings_alchemy(modules2["settings"], checker2)
    assert any(e.kind == "ALC-01" for e in checker2.errors)


def test_defaults_only_mode_present() -> None:
    """alchemy 仅配 mode → 其余键走默认值兜底，无任何提示（默认值均合法）。"""
    rep = _check(mode="full")
    assert not rep.errors and not rep.warnings
    rep = _check(mode="off")
    assert not rep.errors and not rep.warnings


# ---------------------------------------------------------------------------
# ALC-01 ~ ALC-24 逐规则正反例
# ---------------------------------------------------------------------------
def test_alc_01_mode_enum() -> None:
    """ALC-01 mode ∈ {full, simple, off} | 红拦 | L410。"""
    rep = _check(mode="bogus")
    assert len(_errs(rep, "mode_enum")) == 1
    assert _errs(rep, "mode_enum")[0]["kind"] == "ALC-01"
    for m in MODE_VALUES:
        assert not _errs(_check(mode=m), "mode_enum")


def test_alc_02_quality_tiers() -> None:
    """ALC-02 档位数 3/5/7、0=不限制、区间单调覆盖 0-100 | 提示 | L411 / B1 拍板②。"""
    # 合法默认 4 键（B1 固定键集）→ 无 ALC-02 提示【工程补白 P-2】
    assert not _warns(_check(), "quality_tiers_tier_count")
    # 档位数 6 → 提示
    rep = _check(quality_tiers={
        "common": [0, 10], "uncommon": [11, 20], "rare": [21, 30], "legendary": [31, 40],
        "epic": [41, 50], "mythic": [51, 100],
    })
    assert len(_warns(rep, "quality_tiers_tier_count")) == 1
    # 档位数 2 → 提示（覆盖合法，仅 count 提示）
    rep = _check(quality_tiers={"common": [0, 50], "rare": [51, 100]})
    assert len(_warns(rep, "quality_tiers_tier_count")) == 1
    assert not _warns(rep, "quality_tiers_range_not_monotonic_cover")
    # 档位数 3 → 无 count 提示
    rep = _check(quality_tiers={"common": [0, 39], "uncommon": [40, 79], "legendary": [80, 100]})
    assert not _warns(rep, "quality_tiers_tier_count")
    # 档位数 5 → 无 count 提示（未知键单列提示）
    rep = _check(quality_tiers={
        "common": [0, 19], "uncommon": [20, 39], "rare": [40, 59],
        "legendary": [60, 79], "epic": [80, 100],
    })
    assert not _warns(rep, "quality_tiers_tier_count")
    assert len(_warns(rep, "quality_tiers_key_not_in_set")) == 1  # epic ∉ B1 键集
    # 区间重叠 → 提示
    rep = _check(quality_tiers={"common": [0, 50], "uncommon": [40, 100]})
    assert len(_warns(rep, "quality_tiers_range_not_monotonic_cover")) == 1
    # 区间未覆盖 0-100 → 提示
    rep = _check(quality_tiers={"common": [0, 50], "uncommon": [51, 90]})
    assert len(_warns(rep, "quality_tiers_range_not_monotonic_cover")) == 1
    # 区间形态非法（字符串）→ 提示
    rep = _check(quality_tiers={"common": "0-39", "uncommon": [40, 100]})
    assert len(_warns(rep, "quality_tiers_range_invalid")) == 1
    # 键集 B1：fine 旧名 → 提示
    rep = _check(quality_tiers={"fine": [0, 100]})
    assert len(_warns(rep, "quality_tiers_key_not_in_set")) == 1


def test_alc_03_quality_coef() -> None:
    """ALC-03 quality_coef 键随档位派生、数值 >0 | 提示 | L412。"""
    rep = _check(quality_coef={"common": 0.8, "uncommon": 1.0, "rare": -1.2, "legendary": 1.5})
    assert len(_warns(rep, "quality_coef_value_not_positive")) == 1
    rep = _check(quality_coef={"common": 0.8, "fine": 1.0})
    assert len(_warns(rep, "quality_coef_key_not_in_tiers")) == 1
    rep = _check(quality_coef={"common": "high"})
    assert len(_warns(rep, "quality_coef_value_not_positive")) == 1
    assert not _warns(_check(), "quality_coef_value_not_positive")


def test_alc_04_chain_map() -> None:
    """ALC-04 chain_map 值 ∈ 1-6 整数 | 提示 | L413。"""
    rep = _check(chain_map={1: 0, 2: 7, 3: 3})
    assert len(_warns(rep, "chain_map_value_out_of_range")) == 2
    rep = _check(chain_map={1: 1.5})
    assert len(_warns(rep, "chain_map_value_out_of_range")) == 1
    assert not _warns(_check(), "chain_map_value_out_of_range")


def test_alc_05_pp_cost() -> None:
    """ALC-05 pp_cost {normal, super} 正整数 | 红拦 | L414。"""
    rep = _check(pp_cost={"normal": 1, "super": 0})
    assert len(_errs(rep, "pp_cost_not_positive_int")) == 1
    rep = _check(pp_cost={"normal": -2, "super": 2})
    assert len(_errs(rep, "pp_cost_not_positive_int")) == 1
    rep = _check(pp_cost={"normal": 1, "legendary": 2})
    assert len(_errs(rep, "pp_cost_key_unknown")) == 1
    assert not _errs(_check(), "pp_cost_not_positive_int")


def test_alc_06_pp_refresh() -> None:
    """ALC-06 pp_refresh 枚举（"会话重置"）| 提示 | L415。"""
    rep = _check(pp_refresh="每场重置")
    assert len(_warns(rep, "pp_refresh_enum")) == 1
    rep = _check(pp_refresh="会话重置")
    assert not _warns(rep, "pp_refresh_enum")


def test_alc_07_energy_enabled() -> None:
    """ALC-07 energy_enabled 布尔（默认 false）| 红拦 | R-08。"""
    rep = _check(energy_enabled="yes")
    assert len(_errs(rep, "energy_enabled_not_bool")) == 1
    assert not _errs(_check(energy_enabled=True), "energy_enabled_not_bool")


def test_alc_08_energy_max() -> None:
    """ALC-08 energy_max 7 档非负整数 | 提示 | L416。"""
    rep = _check(energy_max={"见习": 5, "正式": 8, "精通": 10, "专家": 12, "大师": 15, "宗师": 18})
    assert len(_warns(rep, "energy_max_tier_count")) == 1
    rep = _check(energy_max={
        "见习": 5, "正式": -1, "精通": 10, "专家": 12, "大师": 15, "宗师": 18, "王": 20,
    })
    assert len(_warns(rep, "energy_max_value_invalid")) == 1
    rep = _check(energy_max={
        "见习": 5, "正式": 8, "精通": 10, "专家": 12, "大师": 15,
        "宗师": 18, "王": 20, "学徒": 1,
    })
    assert len(_warns(rep, "energy_max_key_unknown")) == 1
    assert not _warns(_check(), "energy_max_value_invalid")


def test_alc_09_energy_regen() -> None:
    """ALC-09 energy_regen_sec / energy_regen_sec_safe 非负整数 | 提示 | L417。"""
    rep = _check(energy_regen_sec=-1)
    assert len(_warns(rep, "energy_regen_sec_invalid")) == 1
    rep = _check(energy_regen_sec_safe=1800.5)
    assert len(_warns(rep, "energy_regen_sec_safe_invalid")) == 1
    assert not _warns(_check(), "energy_regen_sec_invalid")


def test_alc_10_decompose_rate() -> None:
    """ALC-10 decompose_rate 6 档 ratio∈(0,1] 单调（无见习）| 红拦 | L418 / DEC-05。"""
    # ratio = 0 → 红拦
    rep = _check(decompose_rate={
        "正式": 0, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.65,
    })
    assert len(_errs(rep, "decompose_rate_ratio_invalid")) == 1
    # ratio > 1 → 红拦
    rep = _check(decompose_rate={
        "正式": 0.4, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 1.1,
    })
    assert len(_errs(rep, "decompose_rate_ratio_invalid")) == 1
    # 单调只升不降：精通低于正式 → 红拦
    rep = _check(decompose_rate={
        "正式": 0.4, "精通": 0.3, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.65,
    })
    assert len(_errs(rep, "decompose_rate_not_monotonic")) == 1
    # 键集无见习：见习出现 → 红拦
    rep = _check(decompose_rate={
        "见习": 0.3, "正式": 0.4, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.65,
    })
    assert len(_errs(rep, "decompose_rate_has_apprentice")) == 1
    # 缺档：缺 王 → 红拦
    rep = _check(decompose_rate={"正式": 0.4, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6})
    assert len(_errs(rep, "decompose_rate_tier_missing")) == 1
    assert not _errs(_check(), "decompose_rate_ratio_invalid")
    assert set(DECOMPOSE_TIER_NAMES) == {"正式", "精通", "专家", "大师", "宗师", "王"}


def test_alc_11_catalyst_unlock_tier() -> None:
    """ALC-11 catalyst_unlock_tier ∈ 职业等级枚举（默认 expert，R-07）| 红拦 | R-07。"""
    rep = _check(catalyst_unlock_tier="传奇")
    assert len(_errs(rep, "catalyst_unlock_tier_enum")) == 1
    for t in JOB_TIER_NAMES:  # 中文 7 档合法
        assert not _errs(_check(catalyst_unlock_tier=t), "catalyst_unlock_tier_enum")
    # 默认值 "expert"（=专家 英文别名）合法【工程补白 P-9】
    assert not _errs(_check(catalyst_unlock_tier="expert"), "catalyst_unlock_tier_enum")


def test_alc_12_catalyst_consume() -> None:
    """ALC-12 catalyst_consume 布尔（默认 true）| 红拦 | 批5B。"""
    rep = _check(catalyst_consume=1)
    assert len(_errs(rep, "catalyst_consume_not_bool")) == 1
    assert not _errs(_check(catalyst_consume=False), "catalyst_consume_not_bool")


def test_alc_13_gem_decompose() -> None:
    """ALC-13 gem.分解 键 ∈ B1 键集 + 数值非负 | 红拦 | L419 / 拍板②。"""
    rep = _check(**{GEM_DECOMPOSE_KEY: {"common": 1, "rare": -3}})
    assert len(_errs(rep, "gem_decompose_value_negative")) == 1
    rep = _check(**{GEM_DECOMPOSE_KEY: {"fine": 1}})  # fine 旧名废弃
    assert len(_errs(rep, "gem_decompose_key_unknown")) == 1
    rep = _check(**{GEM_DECOMPOSE_KEY: {"common": 1, "uncommon": 3, "rare": 8, "legendary": 20}})
    assert not _errs(rep, "gem_decompose_key_unknown")
    assert not _errs(rep, "gem_decompose_value_negative")
    assert set(QUALITY_KEYS) == {"common", "uncommon", "rare", "legendary"}


def test_alc_14_gem_costs() -> None:
    """ALC-14 gem.{复制/成品合成/配方合成/特性合成/珠升阶} 数值非负（复制可浮点）
    | 红拦 | L419 / 拍板④。"""
    rep = _check(**{"gem.成品合成": -5})
    assert len(_errs(rep, "gem_cost_invalid")) == 1
    rep = _check(**{"gem.配方合成": 5, "gem.特性合成": 20, "gem.珠升阶": 10.5})
    assert len(_errs(rep, "gem_cost_not_int")) == 1  # 珠升阶非整数
    rep = _check(**{GEM_DUPLICATE_KEY: -0.1})
    assert len(_errs(rep, "gem_duplicate_fee_invalid")) == 1
    rep = _check(**{GEM_DUPLICATE_KEY: 0.2})  # 复制费率可浮点 → 不红拦
    assert not _errs(rep, "gem_duplicate_fee_invalid")
    assert not _errs(_check(), "gem_cost_invalid")


def test_alc_15_gem_secret_key() -> None:
    """ALC-15 gem 段不存在 gem.秘钥 键（已砍）；遗留引用 → W 级提示 | L419 注 / TC-23。"""
    rep = _check(**{GEM_SECRET_KEY: {"common": 5}})
    assert len(_warns(rep, "gem_secret_key_deprecated")) == 1
    assert not rep.errors  # 仅提示不拦截
    assert not _warns(_check(), "gem_secret_key_deprecated")


def test_alc_16_gem_diminish() -> None:
    """ALC-16 gem_diminish [{n,mult}]：n≥2 递增、mult∈(0,1] | 提示 | L420 / BEL-10。"""
    rep = _check(gem_diminish=[{"n": 1, "mult": 0.5}])
    assert len(_warns(rep, "gem_diminish_n_invalid")) == 1
    rep = _check(gem_diminish=[{"n": 2, "mult": 0.5}, {"n": 2, "mult": 0.25}])
    assert len(_warns(rep, "gem_diminish_n_not_increasing")) == 1
    rep = _check(gem_diminish=[{"n": 2, "mult": 0}])
    assert len(_warns(rep, "gem_diminish_mult_invalid")) == 1
    rep = _check(gem_diminish=[{"n": 2, "mult": 1.5}])
    assert len(_warns(rep, "gem_diminish_mult_invalid")) == 1
    rep = _check(gem_diminish=[])  # 空/0=无递减
    assert not _warns(rep, "gem_diminish_n_invalid")
    assert not _warns(rep, "gem_diminish_mult_invalid")


def test_alc_17_synth_exp() -> None:
    """ALC-17 synth_exp 字符串 | 提示 | L421。"""
    rep = _check(synth_exp=123)
    assert len(_warns(rep, "synth_exp_not_str")) == 1
    assert not _warns(_check(synth_exp="配方等级×1"), "synth_exp_not_str")


def test_alc_18_sp_per_level_sp_panel() -> None:
    """ALC-18 sp_per_level 非负整数 + sp_panel 4 项默认 + repeatable 布尔 | 提示 | L422-423。"""
    rep = _check(sp_per_level=-1)
    assert len(_warns(rep, "sp_per_level_invalid")) == 1
    rep = _check(sp_panel=[{"id": "a", "repeatable": True}])  # 仅 1 项 → 非 4 项默认
    assert len(_warns(rep, "sp_panel_item_count")) == 1
    panel_4 = [{"id": f"p{i}", "repeatable": True} for i in range(4)]
    panel_4[2]["repeatable"] = "yes"
    rep = _check(sp_panel=panel_4)
    assert len(_warns(rep, "sp_panel_repeatable_not_bool")) == 1
    assert not _warns(_check(), "sp_panel_item_count")


def test_alc_19_battle_item() -> None:
    """ALC-19 战斗道具：强度公式字符串 + 珠触发上限 ≥1 正整数（默认 3）| 提示 | L424。"""
    rep = _check(**{BATTLE_ITEM_KEY: {"强度公式": 42, "珠触发上限": 3}})
    assert len(_warns(rep, "battle_item_formula_not_str")) == 1
    rep = _check(**{BATTLE_ITEM_KEY: {"强度公式": "技能×(1+0.4×冷却数)", "珠触发上限": 0}})
    assert len(_warns(rep, "battle_item_trigger_limit_invalid")) == 1
    assert not _warns(_check(), "battle_item_trigger_limit_invalid")


def test_alc_20_battle_alchemy() -> None:
    """ALC-20 auto_use 布尔 + ALC-20' per_battle_limit ≥1 正整数 | 红拦 | L425。"""
    rep = _check(**{BATTLE_ALCHEMY_KEY: {"auto_use": "yes", "per_battle_limit": 1}})
    assert len(_errs(rep, "auto_use_not_bool")) == 1
    au_errs = _errs(rep, "auto_use_not_bool")
    assert len(au_errs) == 1 and au_errs[0]["kind"] == "ALC-20"
    rep = _check(**{BATTLE_ALCHEMY_KEY: {"auto_use": True, "per_battle_limit": 0}})
    assert len(_errs(rep, "per_battle_limit_invalid")) == 1
    rep = _check(**{BATTLE_ALCHEMY_KEY: {"auto_use": True, "per_battle_limit": -2}})
    assert len(_errs(rep, "per_battle_limit_invalid")) == 1
    assert not _errs(_check(), "auto_use_not_bool")
    assert not _errs(_check(), "per_battle_limit_invalid")


def test_alc_21_max_qty() -> None:
    """ALC-21 max_qty 正整数（默认 2147483647，拍板⑤）| 红拦 | 拍板⑤。"""
    rep = _check(max_qty=0)
    assert len(_errs(rep, "max_qty_invalid")) == 1
    rep = _check(max_qty=-5)
    assert len(_errs(rep, "max_qty_invalid")) == 1
    rep = _check(max_qty="100")
    assert len(_errs(rep, "max_qty_invalid")) == 1
    assert not _errs(_check(max_qty=MAX_QTY_DEFAULT), "max_qty_invalid")
    assert MAX_QTY_DEFAULT == 2147483647


def test_alc_22_decompose_formula() -> None:
    """ALC-22 宝石产出公式可配项合法（默认平铺，拍板①）| 提示 | 拍板① / DEC-04。"""
    rep = _check(**{GEM_DECOMPOSE_FORMULA_KEY: "linear"})
    assert len(_warns(rep, "decompose_formula_enum")) == 1
    for v in DECOMPOSE_FORMULA_ENUM:
        assert not _warns(_check(**{GEM_DECOMPOSE_FORMULA_KEY: v}), "decompose_formula_enum")
    assert DECOMPOSE_FORMULA_ENUM == ("flat", "rate")


def test_alc_23_copy_extra_cost() -> None:
    """ALC-23 gem.复制额外（=copy_extra_cost）非负 int、默认 0 | 提示 | 拍板④ / DUP-03。"""
    rep = _check(**{GEM_EXTRA_KEY: -1})
    assert len(_warns(rep, "copy_extra_cost_invalid")) == 1
    rep = _check(**{GEM_EXTRA_ALIAS: -1})  # 别名兼容【工程补白 P-7】
    assert len(_warns(rep, "copy_extra_cost_invalid")) == 1
    rep = _check(**{GEM_EXTRA_KEY: 5})
    assert not _warns(rep, "copy_extra_cost_invalid")
    assert not _warns(_check(), "copy_extra_cost_invalid")  # 缺省默认 0


def test_alc_24_job_tier_map() -> None:
    """ALC-24 job_tier_map 称号引用职业等级枚举、区间单调 | 红拦 | L34 / LVL-06。"""
    # 未知称号 → 红拦
    rep = _check(job_tier_map={
        "学徒": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
        "大师": [31, 40], "宗师": [41, 50], "王": [51, 100],
    })
    assert len(_errs(rep, "job_tier_map_key_unknown")) == 1
    # 区间 lo<1 → 红拦
    rep = _check(job_tier_map={
        "见习": [0, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
        "大师": [31, 40], "宗师": [41, 50], "王": [51, 100],
    })
    assert len(_errs(rep, "job_tier_map_range_invalid")) == 1
    # 区间不单调（正式 lo ≤ 见习 hi）→ 红拦
    rep = _check(job_tier_map={
        "见习": [1, 5], "正式": [4, 10], "精通": [11, 20], "专家": [21, 30],
        "大师": [31, 40], "宗师": [41, 50], "王": [51, 100],
    })
    assert len(_errs(rep, "job_tier_map_not_monotonic")) == 1
    assert not _errs(_check(), "job_tier_map_key_unknown")
    assert not _errs(_check(), "job_tier_map_not_monotonic")


# ---------------------------------------------------------------------------
# validate_slots：slots.json 模块（契约 §四 4.2）
# ---------------------------------------------------------------------------
def _legal_slots() -> list:
    return [
        {"equip_id": "sword_iron", "slots": [{"slot_level": 2}, {"slot_level": 2}]},
        {"equip_id": "dagger_steel", "slots": [{"slot_level": 1}]},
        {"equip_id": "staff_willow",
         "slots": [{"slot_level": 3}, {"slot_level": 2}, {"slot_level": 3}]},
    ]


def _check_slots(slots: object = None, items_wired: bool = True) -> _Report:
    modules: dict = {"slots": _legal_slots() if slots is None else slots}
    if items_wired:
        modules["items"] = [{"id": "sword_iron"}, {"id": "dagger_steel"}, {"id": "staff_willow"}]
    rep = _Report()
    validate_slots(modules, rep)
    return rep


def test_slots_legal_zero() -> None:
    """合法 slots（1-3 槽位、slot_level∈1-3、equip_id 引用存在）→ 零红拦。"""
    rep = _check_slots()
    assert not rep.errors, f"合法 slots 不应有红拦：{rep.errors}"
    assert not rep.warnings


def test_slots_not_wired() -> None:
    """未接线 slots 模块 / 非 list → 跳过（§2.3 默认放行）。"""
    rep = _Report()
    validate_slots({}, rep)
    assert not rep.errors and not rep.warnings
    validate_slots({"slots": "nope"}, rep)
    assert not rep.errors and not rep.warnings


def test_slots_entry_not_object() -> None:
    """条目非对象 → 红拦 SLOT-01。"""
    rep = _check_slots(["sword_iron"])
    assert len(_errs(rep, "slot_entry_not_object")) == 1


def test_slots_equip_id_required_and_duplicate() -> None:
    """equip_id 必填非空 string + 条目内唯一 → 红拦 SLOT-01。"""
    slots = _legal_slots()
    del slots[0]["equip_id"]
    rep = _check_slots(slots)
    assert len(_errs(rep, "equip_id_required")) == 1
    slots = _legal_slots()
    slots[1]["equip_id"] = "sword_iron"  # 与第 0 条重复
    rep = _check_slots(slots)
    assert len(_errs(rep, "equip_id_duplicate")) == 1


def test_slots_equip_id_ref_missing() -> None:
    """equip_id 引用 items 存在（items 已接线时）→ 红拦；未接线跳过引用检查。"""
    slots = _legal_slots()
    slots[0]["equip_id"] = "ghost_sword"
    rep = _check_slots(slots, items_wired=True)
    assert len(_errs(rep, "equip_id_ref_missing")) == 1
    rep = _check_slots(slots, items_wired=False)
    assert not _errs(rep, "equip_id_ref_missing")


def test_slots_count_out_of_range() -> None:
    """slots 数组 1-3 个【工程补白 SOCK-01】→ 越界红拦 SLOT-02。"""
    slots = _legal_slots()
    slots[1]["slots"] = []
    rep = _check_slots(slots)
    assert len(_errs(rep, "slots_count_out_of_range")) == 1
    slots = _legal_slots()
    slots[2]["slots"] = [{"slot_level": 1}, {"slot_level": 2}, {"slot_level": 3}, {"slot_level": 1}]
    rep = _check_slots(slots)
    assert len(_errs(rep, "slots_count_out_of_range")) == 1
    slots = _legal_slots()
    slots[2]["slots"] = [{"slot_level": 1}, {"slot_level": 1}, {"slot_level": 1}]
    rep = _check_slots(slots)  # 3 槽位边界合法
    assert not _errs(rep, "slots_count_out_of_range")


def test_slots_slot_level_invalid() -> None:
    """slot_level 整数 ∈ 1-3 → 越界/非整数红拦 SLOT-03。"""
    slots = _legal_slots()
    slots[1]["slots"] = [{"slot_level": 0}]
    rep = _check_slots(slots)
    assert len(_errs(rep, "slot_level_invalid")) == 1
    slots = _legal_slots()
    slots[1]["slots"] = [{"slot_level": 4}]
    rep = _check_slots(slots)
    assert len(_errs(rep, "slot_level_invalid")) == 1
    slots = _legal_slots()
    slots[1]["slots"] = [{"slot_level": 2.5}]
    rep = _check_slots(slots)
    assert len(_errs(rep, "slot_level_invalid")) == 1
    slots = _legal_slots()
    slots[1]["slots"] = [{"slot_level": 1}]
    rep = _check_slots(slots)
    assert not _errs(rep, "slot_level_invalid")


def test_slots_checker_integration() -> None:
    """收口兼容：validate_slots 直传真实 validator._Checker（_err/_warn 鸭子路径）零红拦。"""
    modules = {
        "slots": _legal_slots(),
        "items": [{"id": "sword_iron"}, {"id": "dagger_steel"}, {"id": "staff_willow"}],
    }
    checker = _Checker(modules, default_field_meta_table())
    validate_slots(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings


# ---------------------------------------------------------------------------
# 字段定义结构（ITEMS_ALCHEMY_FIELDS / SLOTS_FIELD_DEFS / ALCHEMY_SETTINGS_FIELD_DEFS）
# ---------------------------------------------------------------------------
def test_items_alchemy_fields_structure() -> None:
    """ITEMS_ALCHEMY_FIELDS 覆盖契约 §4.1 全部 8 键 + 关键类型/枚举。"""
    assert set(ITEMS_ALCHEMY_FIELDS) == {"type", "quality", "elements", "traits",
                                         "awaken", "rarity", "base_effects", "seed"}
    assert ITEMS_ALCHEMY_FIELDS["quality"].type == "enum"
    assert ITEMS_ALCHEMY_FIELDS["quality"].enum == QUALITY_KEYS
    assert ITEMS_ALCHEMY_FIELDS["quality"].default == "common"
    assert ITEMS_ALCHEMY_FIELDS["elements"].type == "obj"
    assert set(ITEMS_ALCHEMY_FIELDS["elements"].children or {}) == set(ALCHEMY_ELEMENTS)
    traits_el = ITEMS_ALCHEMY_FIELDS["traits"].element
    # 【收口裁决 2026-08-29】items.traits 只做 str 结构校验（既有 M2 内容包旧语义防误拦），
    # 深引用存在性校验归批7 装饰珠/镶嵌引擎运行时
    assert traits_el is not None and traits_el.type == "str"
    assert ITEMS_ALCHEMY_FIELDS["awaken"].type == "bool"
    assert ITEMS_ALCHEMY_FIELDS["awaken"].default is False
    assert ITEMS_ALCHEMY_FIELDS["rarity"].enum == ITEM_RARITY_KEYS  # 【工程补白 P-3】
    assert ITEMS_ALCHEMY_FIELDS["seed"].type == "bool"
    assert ITEMS_ALCHEMY_FIELDS["seed"].default is False
    assert ITEM_RARITY_KEYS == ("普通", "稀有", "金色")
    # 【工程补白 P-3：契约 §4.1 中文 普通/稀有/金色】


def test_slots_field_defs_structure() -> None:
    """SLOTS_FIELD_DEFS 覆盖契约 §4.2（equip_id 引用 item + slot_level int 1-3）。"""
    assert set(SLOTS_FIELD_DEFS) == {"equip_id", "slots"}
    # 【收口裁决 2026-08-29】equip_id 引用 items ∪ equipment（泛型 ref 只能单一 kind）
    # → 用 str + validate_slots 跨表查
    assert SLOTS_FIELD_DEFS["equip_id"].type == "str"
    assert SLOTS_FIELD_DEFS["equip_id"].required is True
    slot_meta = SLOTS_FIELD_DEFS["slots"].element
    assert slot_meta is not None
    assert slot_meta.children["slot_level"].type == "int"
    assert slot_meta.children["slot_level"].range_min == 1
    assert slot_meta.children["slot_level"].range_max == 3
    meta = slots_module_meta()
    assert meta.entry_type == "list"
    assert meta.kind == "slots"


def test_alchemy_settings_field_defs_structure() -> None:
    """ALCHEMY_SETTINGS_FIELD_DEFS 覆盖契约 §五 全字段键表（含中文键）。"""
    expect = {
        "mode", "quality_tiers", "quality_coef", "chain_map", "pp_cost", "pp_refresh",
        "energy_enabled", "energy_max", "energy_regen_sec", "energy_regen_sec_safe",
        "decompose_rate", "catalyst_unlock_tier", "catalyst_consume",
        "gem.分解", "gem.复制", "gem.成品合成", "gem.配方合成", "gem.特性合成", "gem.珠升阶",
        "gem.复制额外", "copy_extra_cost", "gem.decompose_formula", "gem_diminish",
        "synth_exp", "sp_per_level", "sp_panel", "战斗道具", "战斗即时调合",
        "max_qty", "job_tier_map",
    }
    assert set(ALCHEMY_SETTINGS_FIELD_DEFS) == expect
    assert ALCHEMY_SETTINGS_FIELD_DEFS["mode"].enum == MODE_VALUES
    assert ALCHEMY_SETTINGS_FIELD_DEFS["energy_enabled"].type == "bool"
    assert ALCHEMY_SETTINGS_FIELD_DEFS["catalyst_unlock_tier"].default == "expert"
    assert ALCHEMY_SETTINGS_FIELD_DEFS["max_qty"].default == MAX_QTY_DEFAULT
    assert ALCHEMY_SETTINGS_FIELD_DEFS["gem.decompose_formula"].enum == DECOMPOSE_FORMULA_ENUM
    assert ALCHEMY_SETTINGS_FIELD_DEFS["gem.复制"].type == "number"
    assert ALCHEMY_SETTINGS_FIELD_DEFS["gem.成品合成"].type == "int"
    # 战斗即时调合子字段（ALC-20/20'）
    ba = ALCHEMY_SETTINGS_FIELD_DEFS[BATTLE_ALCHEMY_KEY].children
    assert ba["auto_use"].type == "bool"
    assert ba["auto_use"].default is True
    assert ba["per_battle_limit"].type == "int"
    assert ba["per_battle_limit"].default == 1
    meta = alchemy_settings_meta()
    assert meta.type == "obj"
    assert set(meta.children) == expect


def test_constants() -> None:
    """契约常量断言（§五 + §十 B1~B5）。"""
    assert MODE_VALUES == ("full", "simple", "off")
    assert JOB_TIER_NAMES == ("见习", "正式", "精通", "专家", "大师", "宗师", "王")
    assert QUALITY_TIER_COUNTS == (3, 4, 5, 7)  # 【工程补白 P-2】含 4 = B1 固定键集默认档
    assert ALCHEMY_ELEMENTS == ("地", "水", "火", "风", "雷", "晶", "月", "无")
    assert GEM_SECRET_KEY == "gem.秘钥"
    assert GEM_EXTRA_KEY == "gem.复制额外"
    assert GEM_EXTRA_ALIAS == "copy_extra_cost"
