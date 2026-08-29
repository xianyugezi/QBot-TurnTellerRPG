"""M8 批次0B·路0B：settings.alchemy 段专项校验（ALC-01~24）+ items/slots 炼金扩展字段定义。

文件：qbot_rpg/content/alchemy_settings.py
创建：2026-08-29
作者：Hermes 子agent-0B
功能：M8 炼金 settings.alchemy 段校验器（鸭子类型纯函数）+ items.json 炼金扩展字段
      （ITEMS_ALCHEMY_FIELDS）+ slots.json 模块校验（SLOTS_FIELD_DEFS + validate_slots）
      + settings.alchemy 段 FieldMeta（ALCHEMY_SETTINGS_FIELD_DEFS），供主 agent 收口
      接线 field_meta/validator。

依据：
  - docs/m8_contract_数据与校验.md §四（4.1 items 扩展 / 4.2 slots）/ §五（settings.alchemy
    段全字段表，逐键含默认值/枚举/可配标注）/ §六 6.2（ALC-01~24 规则清单 + 级别）/
    §十（B1~B5 用户 5 项拍板）
  - 炼金定稿 v2.3 §10（L378-382 / L408-426）
  - 模式参考：shop_models.py _emit/_err/_warn（L478-492）鸭子类型报告收集；
    validator._check_settings_1g4（L1329）为 settings 专项形态——本文件实现为鸭子类型
    纯函数 check_settings_alchemy(data, report)，红拦=report.error/_err、黄=report.warning/_warn。

铁律：本文件只读依赖既有模块（field_meta/models），绝不修改任何既有文件（field_meta.py/
      validator.py/loader.py 由主 agent 收口接线）；校验器为鸭子类型纯函数，无副作用。

【工程补白】清单（契约/定稿未显式定义处的实现口径，标 P-N）：
  P-1  quality_tiers 值形态 = [lo, hi] 两元素 int 列表（兼容 {min, max} 对象）。
  P-2  ALC-02 档位数 = quality_tiers 键数 ∈ {3,5,7}；B1 拍板②固定 4 键集
       （common/uncommon/rare/legendary）视为合法默认档；0=不限制（段缺失/空对象）→
       合法。4 键集与 3/5/7 可配档位的张力只提示不拦截（契约 ALC-02 级别=提示）。
  P-3  items rarity 键名 = normal/rare/gold（契约仅中文 普通/稀有/金色）。
  P-4  slots 为 M8 新增注册模块：与 EQP-04 部位定义形态（core/equipment.py L134
       {slots:{id:def}}）是不同数据空间，装配层注入区分归批11；本批只做 schema+校验。
  P-5  slots 校验级别：契约 §4.2 未标级别，按数据完整性一律红拦（SLOT-01~03）。
  P-6  settings.alchemy 段缺失/空 → 默认值兜底判定，不报错（契约 §五 段默认值兜底）。
  P-7  gem.复制额外 别名 copy_extra_cost 双键名兼容（ALC-23 拍板④）。
  P-8  alchemy 段存在但非对象 → ALC-STRUCT 红拦（结构性防御，契约未显式列出）。
"""
from __future__ import annotations

from typing import List, Mapping, Optional, Tuple, TypeGuard

# 字段定义/常量自 field_meta 单向 import（schema 之家统一持有；0B 路产出迁移，收口裁决
# 2026-08-29——防 field_meta↔alchemy_settings 循环依赖，G0 TC-03）
from qbot_rpg.content.field_meta import (
    ALCHEMY_ELEMENTS,
    ALCHEMY_SETTINGS_FIELD_DEFS,
    BATTLE_ALCHEMY_DEFAULT,
    BATTLE_ALCHEMY_KEY,
    BATTLE_ITEM_KEY,
    CATALYST_UNLOCK_TIER_ENUM,
    DECOMPOSE_FORMULA_ENUM,
    DECOMPOSE_TIER_NAMES,
    DEFAULT_GEM_DIMINISH,
    GEM_COST_INT_KEYS,
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
    PP_REFRESH_ENUM,
    QUALITY_KEYS,
    QUALITY_KEYS_CN,
    QUALITY_TIER_COUNTS,
    SLOTS_FIELD_DEFS,
    alchemy_settings_meta,
    slots_module_meta,
)

# =====================================================================================
# 常量：键集 / 枚举 / 默认值（契约 §五 + §十 B1~B5 拍板）
# —— 全部迁移至 field_meta（schema 之家统一持有，0B 路产出收口裁决 2026-08-29），
#    本文件顶部单向 import；防 field_meta↔alchemy_settings 循环依赖（G0 TC-03）。
# =====================================================================================

# =====================================================================================
# 报告收集（鸭子类型，照 shop_models._emit/_err/_warn L478-492）
# =====================================================================================
def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配：优先 report.<method>，其次 validator._Checker 的 _<method>。"""
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _settings_err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "settings", field, kind, **detail)


def _settings_warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "settings", field, kind, **detail)


def _slots_err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "slots", field, kind, **detail)


# =====================================================================================
# 数值/区间判定小工具
# =====================================================================================
def _is_num(v: object) -> TypeGuard[float]:
    """数字判定（排除 bool——bool 是 int 子类）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: object) -> TypeGuard[int]:
    """整数判定（排除 bool）。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _parse_range(value: object) -> Optional[Tuple[int, int]]:
    """解析区间值 → (lo, hi)；非法 → None。

    支持形态：【工程补白 P-1】[lo, hi] 两元素 int 列表 / {min, max} 对象。
    """
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_int(x) for x in value):
        lo, hi = value[0], value[1]
        if isinstance(lo, int) and isinstance(hi, int) and lo <= hi:
            return (lo, hi)
        return None
    if isinstance(value, Mapping):
        lo, hi = value.get("min"), value.get("max")
        if isinstance(lo, int) and isinstance(hi, int) and lo <= hi:
            return (lo, hi)
    return None


def _ranges_monotonic_cover(ranges: List[Tuple[int, int]]) -> bool:
    """区间单调递增、互不重叠、共同覆盖 0-100（ALC-02 quality_tiers 判定）。"""
    if not ranges:
        return False
    s = sorted(ranges)
    if s[0][0] != 0 or s[-1][1] != 100:
        return False
    for (_, h1), (l2, _) in zip(s, s[1:]):
        if l2 <= h1:  # 重叠 → 不合法
            return False
    return True


def _id_set(modules: Mapping[str, object], name: str) -> set:
    """模块条目 id 集合（引用靶；非 list/非对象条目跳过）。"""
    mod = modules.get(name)
    if not isinstance(mod, list):
        return set()
    return {str(e.get("id")) for e in mod if isinstance(e, Mapping) and e.get("id")}


# =====================================================================================
# check_settings_alchemy：settings.alchemy 段专项校验（ALC-01~24）
# =====================================================================================
def check_settings_alchemy(data: Mapping, report: object) -> None:
    """settings.alchemy 段专项校验（M8 数据与校验契约 §六 6.2 ALC-01~24）。纯函数，无副作用。

    入参：
      data   —— settings 模块数据（Mapping；从 data["alchemy"] 取段）。
      report —— 鸭子类型收集器：error(module, field, kind, **detail) / warning(...)，
                兼容 validator._Checker 的 _err/_warn（经 _emit 回落）。
    出参：None；红拦（error）/ 黄提示（warning）全部经 report 追加（一次给全量）。
    核心逻辑：
      - settings 缺 alchemy 段或段为空 → 按默认值兜底判定，不报错（契约 §五 段默认值兜底，
        对齐 L506「机制过多配置负担 → 默认值兜底 + 模块开关」；mode:off 时整段不生效）。
      - 键名照契约原样（含中文键 gem.分解 / 战斗道具 / 战斗即时调合 / gem.复制额外）。
      - ALC-20 拆两项：auto_use 布尔红拦 + per_battle_limit ≥1 红拦（独立级别）。
      - 级别照契约 §6.2 表：红拦 = ALC-01/05/07/10/11/12/13/14/20/20'/21/24；
        黄提示 = ALC-02/03/04/06/08/09/15/16/17/18/19/22/23。
    入口（主 agent 收口）：validator.settings 分支（L559 旁）调
        check_settings_alchemy(data, checker)。
    """
    if not isinstance(data, Mapping):
        return
    alchemy = data.get("alchemy")
    if alchemy is None:
        return  # P-6：段缺失 → 默认值兜底，不报错（契约 §五）
    if not isinstance(alchemy, Mapping):
        # P-8：段存在但非对象 → 结构性红拦（契约未显式列出，防御口径）
        _settings_err(report, "settings.alchemy", "ALC-STRUCT",
                      rule="alchemy_not_object", got=type(alchemy).__name__)
        return
    a: Mapping = alchemy

    # ---- ALC-01 mode 枚举 ∈ {full, simple, off}（默认 full）| 红拦 | 定稿 L410 ----
    if "mode" in a and a["mode"] not in MODE_VALUES:
        _settings_err(report, "settings.alchemy.mode", "ALC-01",
                      rule="mode_enum", got=a["mode"])

    # ---- ALC-02 quality_tiers 区间单调覆盖 0-100 不重叠；档位数 3/5/7、
    #       0=不限制 → 只提示不拦截 ----
    #      | 提示 | 定稿 L411 / QLT-03 / B1 拍板②
    qt = a.get("quality_tiers")
    if qt is not None:
        if not isinstance(qt, Mapping):
            _settings_warn(report, "settings.alchemy.quality_tiers", "ALC-02",
                           rule="quality_tiers_not_object", got=type(qt).__name__)
        else:
            # 键集 B1：只允许 common/uncommon/rare/legendary（旧名废弃）
            bad_keys = [k for k in qt if k not in QUALITY_KEYS]
            if bad_keys:
                _settings_warn(report, "settings.alchemy.quality_tiers", "ALC-02",
                               rule="quality_tiers_key_not_in_set", keys=bad_keys)
            # 档位数：3/5/7 可配；4 = B1 固定键集默认档【工程补白 P-2】；0=不限制走兜底
            if len(qt) not in QUALITY_TIER_COUNTS:
                _settings_warn(report, "settings.alchemy.quality_tiers", "ALC-02",
                               rule="quality_tiers_tier_count", count=len(qt))
            # 区间单调覆盖 0-100 不重叠
            qt_ranges: List[Tuple[int, int]] = []
            parsed_ok = True
            for k, v in qt.items():
                r = _parse_range(v)
                if r is None:
                    parsed_ok = False
                    _settings_warn(report, f"settings.alchemy.quality_tiers.{k}", "ALC-02",
                                   rule="quality_tiers_range_invalid", key=k, value=v)
                else:
                    qt_ranges.append(r)
            if parsed_ok and qt_ranges and not _ranges_monotonic_cover(qt_ranges):
                _settings_warn(report, "settings.alchemy.quality_tiers", "ALC-02",
                               rule="quality_tiers_range_not_monotonic_cover")

    # ---- ALC-03 quality_coef 键随档位派生、数值 >0 | 提示 | 定稿 L412 / QLT-04 ----
    qc = a.get("quality_coef")
    if qc is not None:
        tier_keys = set(qt) if isinstance(qt, Mapping) else set(QUALITY_KEYS)
        if not isinstance(qc, Mapping):
            _settings_warn(report, "settings.alchemy.quality_coef", "ALC-03",
                           rule="quality_coef_not_object", got=type(qc).__name__)
        else:
            for k, v in qc.items():
                if k not in tier_keys:
                    _settings_warn(report, f"settings.alchemy.quality_coef.{k}", "ALC-03",
                                   rule="quality_coef_key_not_in_tiers", key=k)
                if not _is_num(v) or v <= 0:
                    _settings_warn(report, f"settings.alchemy.quality_coef.{k}", "ALC-03",
                                   rule="quality_coef_value_not_positive", key=k, value=v)

    # ---- ALC-04 chain_map 值 ∈ 1-6 整数 | 提示 | 定稿 L413 / QLT-13 ----
    cm = a.get("chain_map")
    if cm is not None:
        if not isinstance(cm, Mapping):
            _settings_warn(report, "settings.alchemy.chain_map", "ALC-04",
                           rule="chain_map_not_object", got=type(cm).__name__)
        else:
            for k, v in cm.items():
                if not _is_int(v) or not (1 <= v <= 6):
                    _settings_warn(report, f"settings.alchemy.chain_map.{k}", "ALC-04",
                                   rule="chain_map_value_out_of_range", key=k, value=v)

    # ---- ALC-05 pp_cost {normal, super} 正整数 | 红拦 | 定稿 L414 / TSC-14 ----
    pc = a.get("pp_cost")
    if pc is not None:
        if not isinstance(pc, Mapping):
            _settings_err(report, "settings.alchemy.pp_cost", "ALC-05",
                          rule="pp_cost_not_object", got=type(pc).__name__)
        else:
            for k, v in pc.items():
                if k not in ("normal", "super"):
                    _settings_err(report, f"settings.alchemy.pp_cost.{k}", "ALC-05",
                                  rule="pp_cost_key_unknown", key=k)
                if not _is_int(v) or v < 1:
                    _settings_err(report, f"settings.alchemy.pp_cost.{k}", "ALC-05",
                                  rule="pp_cost_not_positive_int", key=k, value=v)

    # ---- ALC-06 pp_refresh 枚举（"会话重置"）| 提示 | 定稿 L415 / INH-09 ----
    pr = a.get("pp_refresh")
    if pr is not None and (not isinstance(pr, str) or pr not in PP_REFRESH_ENUM):
        _settings_warn(report, "settings.alchemy.pp_refresh", "ALC-06",
                       rule="pp_refresh_enum", got=pr)

    # ---- ALC-07 energy_enabled 布尔（默认 false，R-08）| 红拦 | R-08 / 定稿 L416 注 ----
    ee = a.get("energy_enabled")
    if ee is not None and not isinstance(ee, bool):
        _settings_err(report, "settings.alchemy.energy_enabled", "ALC-07",
                      rule="energy_enabled_not_bool", got=ee)

    # ---- ALC-08 energy_max 7 档非负整数（见习 5 … 王 20）| 提示 | 定稿 L416 ----
    em = a.get("energy_max")
    if em is not None:
        if not isinstance(em, Mapping):
            _settings_warn(report, "settings.alchemy.energy_max", "ALC-08",
                           rule="energy_max_not_object", got=type(em).__name__)
        else:
            for k, v in em.items():
                if k not in JOB_TIER_NAMES:
                    _settings_warn(report, f"settings.alchemy.energy_max.{k}", "ALC-08",
                                   rule="energy_max_key_unknown", key=k)
                if not _is_int(v) or v < 0:
                    _settings_warn(report, f"settings.alchemy.energy_max.{k}", "ALC-08",
                                   rule="energy_max_value_invalid", key=k, value=v)
            if len(em) != len(JOB_TIER_NAMES):
                _settings_warn(report, "settings.alchemy.energy_max", "ALC-08",
                               rule="energy_max_tier_count", count=len(em))

    # ---- ALC-09 energy_regen_sec / energy_regen_sec_safe 非负整数 | 提示 | L417 / LVL-09 ----
    for key in ("energy_regen_sec", "energy_regen_sec_safe"):
        v = a.get(key)
        if v is not None and (not _is_int(v) or v < 0):
            _settings_warn(report, f"settings.alchemy.{key}", "ALC-09",
                           rule=f"{key}_invalid", value=v)

    # ---- ALC-10 decompose_rate 6 档 ratio ∈ (0,1] 单调（见习无分解→表自正式起）| 红拦 ----
    #      | 定稿 L418 / DEC-02/05
    dr = a.get("decompose_rate")
    if dr is not None:
        if not isinstance(dr, Mapping):
            _settings_err(report, "settings.alchemy.decompose_rate", "ALC-10",
                          rule="decompose_rate_not_object", got=type(dr).__name__)
        else:
            # 键集从正式起、无见习（见习无分解）
            if "见习" in dr:
                _settings_err(report, "settings.alchemy.decompose_rate.见习", "ALC-10",
                              rule="decompose_rate_has_apprentice")
            bad_keys = [k for k in dr if k not in DECOMPOSE_TIER_NAMES]
            if bad_keys:
                _settings_err(report, "settings.alchemy.decompose_rate", "ALC-10",
                              rule="decompose_rate_key_unknown", keys=bad_keys)
            missing = [k for k in DECOMPOSE_TIER_NAMES if k not in dr]
            if missing:
                _settings_err(report, "settings.alchemy.decompose_rate", "ALC-10",
                              rule="decompose_rate_tier_missing", missing=missing)
            # ratio ∈ (0,1]
            for k, v in dr.items():
                if not _is_num(v) or not (0 < v <= 1):
                    _settings_err(report, f"settings.alchemy.decompose_rate.{k}", "ALC-10",
                                  rule="decompose_rate_ratio_invalid", key=k, value=v)
            # 单调（只升不降）：按 正式..王 顺序
            ordered = [dr[k] for k in DECOMPOSE_TIER_NAMES if k in dr and _is_num(dr[k])]
            for prev, cur in zip(ordered, ordered[1:]):
                if cur < prev:
                    _settings_err(report, "settings.alchemy.decompose_rate", "ALC-10",
                                  rule="decompose_rate_not_monotonic")
                    break

    # ---- ALC-11 catalyst_unlock_tier ∈ 职业等级枚举（默认 expert，R-07）| 红拦 | R-07 ----
    cut = a.get("catalyst_unlock_tier")
    if cut is not None and cut not in CATALYST_UNLOCK_TIER_ENUM:
        _settings_err(report, "settings.alchemy.catalyst_unlock_tier", "ALC-11",
                      rule="catalyst_unlock_tier_enum", got=cut)

    # ---- ALC-12 catalyst_consume 布尔（默认 true）| 红拦 | 批5B ----
    cc = a.get("catalyst_consume")
    if cc is not None and not isinstance(cc, bool):
        _settings_err(report, "settings.alchemy.catalyst_consume", "ALC-12",
                      rule="catalyst_consume_not_bool", got=cc)

    # ---- ALC-13 gem.分解 键 ∈ {common,uncommon,rare,legendary} + 数值非负 | 红拦 ----
    #      | 定稿 L419 / 拍板②（键名）
    gd = a.get(GEM_DECOMPOSE_KEY)
    if gd is not None:
        if not isinstance(gd, Mapping):
            _settings_err(report, f"settings.alchemy.{GEM_DECOMPOSE_KEY}", "ALC-13",
                          rule="gem_decompose_not_object", got=type(gd).__name__)
        else:
            for k, v in gd.items():
                if k not in QUALITY_KEYS:
                    _settings_err(report, f"settings.alchemy.{GEM_DECOMPOSE_KEY}.{k}", "ALC-13",
                                  rule="gem_decompose_key_unknown", key=k)
                if not _is_num(v) or v < 0:
                    _settings_err(report, f"settings.alchemy.{GEM_DECOMPOSE_KEY}.{k}", "ALC-13",
                                  rule="gem_decompose_value_negative", key=k, value=v)

    # ---- ALC-14 gem.{复制/成品合成/配方合成/特性合成/珠升阶} 数值非负（复制可浮点）| 红拦 ----
    #      | 定稿 L419 / 拍板④
    for key in GEM_COST_INT_KEYS:
        v = a.get(key)
        if v is None:
            continue
        if not _is_num(v) or v < 0:
            _settings_err(report, f"settings.alchemy.{key}", "ALC-14",
                          rule="gem_cost_invalid", key=key, value=v)
        elif not _is_int(v):  # 4 个合成费字段类型 int（§五），非整数 → 红拦
            _settings_err(report, f"settings.alchemy.{key}", "ALC-14",
                          rule="gem_cost_not_int", key=key, value=v)
    dup = a.get(GEM_DUPLICATE_KEY)
    if dup is not None and (not _is_num(dup) or dup < 0):  # 复制费率可浮点（0.2）
        _settings_err(report, f"settings.alchemy.{GEM_DUPLICATE_KEY}", "ALC-14",
                      rule="gem_duplicate_fee_invalid", value=dup)

    # ---- ALC-15 gem 段不存在 gem.秘钥 键（已砍）；遗留引用 → W 级提示
    #      | 提示 | L419 注 / TC-23 ----
    if GEM_SECRET_KEY in a:
        _settings_warn(report, f"settings.alchemy.{GEM_SECRET_KEY}", "ALC-15",
                       rule="gem_secret_key_deprecated", key=GEM_SECRET_KEY)

    # ---- ALC-16 gem_diminish [{n,mult}]：n ≥2 递增、mult ∈ (0,1] | 提示 | 定稿 L420 / BEL-10 ----
    gdim = a.get("gem_diminish")
    if gdim is not None:
        if not isinstance(gdim, list):
            _settings_warn(report, "settings.alchemy.gem_diminish", "ALC-16",
                           rule="gem_diminish_not_list", got=type(gdim).__name__)
        else:
            prev_n: Optional[int] = None
            for i, entry in enumerate(gdim):
                if not isinstance(entry, Mapping) or "n" not in entry or "mult" not in entry:
                    _settings_warn(report, f"settings.alchemy.gem_diminish.{i}", "ALC-16",
                                   rule="gem_diminish_entry_invalid", index=i, entry=entry)
                    continue
                n, mult = entry["n"], entry["mult"]
                if not _is_int(n) or n < 2:
                    _settings_warn(report, f"settings.alchemy.gem_diminish.{i}", "ALC-16",
                                   rule="gem_diminish_n_invalid", index=i, n=n)
                if not _is_num(mult) or not (0 < mult <= 1):
                    _settings_warn(report, f"settings.alchemy.gem_diminish.{i}", "ALC-16",
                                   rule="gem_diminish_mult_invalid", index=i, mult=mult)
                if prev_n is not None and _is_int(n) and n <= prev_n:
                    _settings_warn(report, f"settings.alchemy.gem_diminish.{i}", "ALC-16",
                                   rule="gem_diminish_n_not_increasing", index=i, n=n)
                if _is_int(n):
                    prev_n = n

    # ---- ALC-17 synth_exp 字符串（"配方等级×1"）| 提示 | 定稿 L421 / EXP-03 ----
    se = a.get("synth_exp")
    if se is not None and not isinstance(se, str):
        _settings_warn(report, "settings.alchemy.synth_exp", "ALC-17",
                       rule="synth_exp_not_str", got=se)

    # ---- ALC-18 sp_per_level 非负整数 + sp_panel 4 项默认 + repeatable 布尔 | 提示 ----
    #      | 定稿 L422-423 / SP-01/03
    spl = a.get("sp_per_level")
    if spl is not None and (not _is_int(spl) or spl < 0):
        _settings_warn(report, "settings.alchemy.sp_per_level", "ALC-18",
                       rule="sp_per_level_invalid", value=spl)
    sp_panel = a.get("sp_panel")
    if sp_panel is not None:
        if not isinstance(sp_panel, list):
            _settings_warn(report, "settings.alchemy.sp_panel", "ALC-18",
                           rule="sp_panel_not_list", got=type(sp_panel).__name__)
        else:
            if len(sp_panel) != 4:  # 默认 4 项（L423）
                _settings_warn(report, "settings.alchemy.sp_panel", "ALC-18",
                               rule="sp_panel_item_count", count=len(sp_panel))
            for i, item in enumerate(sp_panel):
                if not isinstance(item, Mapping):
                    _settings_warn(report, f"settings.alchemy.sp_panel.{i}", "ALC-18",
                                   rule="sp_panel_entry_not_object", index=i)
                    continue
                if "repeatable" in item and not isinstance(item["repeatable"], bool):
                    _settings_warn(report, f"settings.alchemy.sp_panel.{i}.repeatable", "ALC-18",
                                   rule="sp_panel_repeatable_not_bool", index=i)

    # ---- ALC-19 战斗道具：强度公式字符串 + 珠触发上限 ≥1 正整数（默认 3）
    #      | 提示 | 定稿 L424 / BEL-11 ----
    bi = a.get(BATTLE_ITEM_KEY)
    if bi is not None:
        if not isinstance(bi, Mapping):
            _settings_warn(report, f"settings.alchemy.{BATTLE_ITEM_KEY}", "ALC-19",
                           rule="battle_item_not_object", got=type(bi).__name__)
        else:
            f = bi.get("强度公式")
            if f is not None and not isinstance(f, str):
                _settings_warn(report, f"settings.alchemy.{BATTLE_ITEM_KEY}.强度公式", "ALC-19",
                               rule="battle_item_formula_not_str", got=f)
            t = bi.get("珠触发上限")
            if t is not None and (not _is_int(t) or t < 1):
                _settings_warn(report, f"settings.alchemy.{BATTLE_ITEM_KEY}.珠触发上限", "ALC-19",
                               rule="battle_item_trigger_limit_invalid", value=t)

    # ---- ALC-20 战斗即时调合.auto_use 布尔（默认 true）| 红拦 | 定稿 L425 ----
    # ---- ALC-20' 战斗即时调合.per_battle_limit 正整数 ≥1（默认 1）| 红拦 | 定稿 L425 ----
    ba = a.get(BATTLE_ALCHEMY_KEY)
    if ba is not None:
        if not isinstance(ba, Mapping):
            _settings_err(report, f"settings.alchemy.{BATTLE_ALCHEMY_KEY}", "ALC-20",
                          rule="battle_alchemy_not_object", got=type(ba).__name__)
        else:
            au = ba.get("auto_use")
            if au is not None and not isinstance(au, bool):
                _settings_err(report, f"settings.alchemy.{BATTLE_ALCHEMY_KEY}.auto_use", "ALC-20",
                              rule="auto_use_not_bool", value=au)
            pbl = ba.get("per_battle_limit")
            if pbl is not None and (not _is_int(pbl) or pbl < 1):
                _settings_err(
                    report,
                    f"settings.alchemy.{BATTLE_ALCHEMY_KEY}.per_battle_limit",
                    "ALC-20",
                    rule="per_battle_limit_invalid",
                    value=pbl,
                )

    # ---- ALC-21 max_qty 正整数（默认 2147483647，拍板⑤）| 红拦 | 拍板⑤ ----
    mq = a.get("max_qty")
    if mq is not None and (not _is_int(mq) or mq < 1):
        _settings_err(report, "settings.alchemy.max_qty", "ALC-21",
                      rule="max_qty_invalid", value=mq)

    # ---- ALC-22 宝石产出公式可配项合法（默认平铺，拍板①）| 提示 | 拍板① / DEC-04 ----
    gdf = a.get(GEM_DECOMPOSE_FORMULA_KEY)
    if gdf is not None and gdf not in DECOMPOSE_FORMULA_ENUM:
        _settings_warn(report, f"settings.alchemy.{GEM_DECOMPOSE_FORMULA_KEY}", "ALC-22",
                       rule="decompose_formula_enum", got=gdf)

    # ---- ALC-23 复制额外消耗 gem.复制额外（=copy_extra_cost）非负 int、默认 0 | 提示 ----
    #      | 拍板④ / DUP-03 / §一 1.3
    gex = a.get(GEM_EXTRA_KEY, a.get(GEM_EXTRA_ALIAS))  # P-7 双键名兼容
    if gex is not None and (not _is_int(gex) or gex < 0):
        _settings_warn(report, f"settings.alchemy.{GEM_EXTRA_KEY}", "ALC-23",
                       rule="copy_extra_cost_invalid", value=gex)

    # ---- ALC-24 job_tier_map：称号引用职业等级枚举、区间单调 | 红拦 | L34 / LVL-06 ----
    jtm = a.get("job_tier_map")
    if jtm is not None:
        if not isinstance(jtm, Mapping):
            _settings_err(report, "settings.alchemy.job_tier_map", "ALC-24",
                          rule="job_tier_map_not_object", got=type(jtm).__name__)
        else:
            jtm_ranges: List[Tuple[str, int, int]] = []
            for k, v in jtm.items():
                if k not in JOB_TIER_NAMES:
                    _settings_err(report, f"settings.alchemy.job_tier_map.{k}", "ALC-24",
                                  rule="job_tier_map_key_unknown", key=k)
                r = _parse_range(v)
                if r is None or r[0] < 1:
                    _settings_err(report, f"settings.alchemy.job_tier_map.{k}", "ALC-24",
                                  rule="job_tier_map_range_invalid", key=k, value=v)
                else:
                    jtm_ranges.append((k, r[0], r[1]))
            # 区间单调：按称号顺序 lo 递增、不重叠（默认 见习 1-5 … 王 51+）
            ordered = [r for k in JOB_TIER_NAMES for r in jtm_ranges if r[0] == k]
            for (k1, lo1, hi1), (k2, lo2, hi2) in zip(ordered, ordered[1:]):
                if lo2 <= hi1:
                    _settings_err(report, "settings.alchemy.job_tier_map", "ALC-24",
                                  rule="job_tier_map_not_monotonic",
                                  prev=(k1, lo1, hi1), cur=(k2, lo2, hi2))
                    break


# =====================================================================================
# 字段定义（ITEMS_ALCHEMY_FIELDS / SLOTS_FIELD_DEFS + slots_module_meta /
# ALCHEMY_SETTINGS_FIELD_DEFS + alchemy_settings_meta）已迁移至 field_meta 统一持有，
# 本文件顶部单向 import（收口裁决 2026-08-29，防循环依赖）。
# =====================================================================================
# =====================================================================================
# validate_slots：slots.json 模块专项校验（契约 §四 4.2；供主 agent 收口接 check_pack）
# =====================================================================================
def validate_slots(modules: Mapping[str, object], report: object) -> None:
    """slots.json 模块专项校验（M8 数据与校验契约 §四 4.2）。纯函数，无副作用。

    入参：
      modules —— 模块名 → parsed JSON（含 "slots" 列表与可选 "items" 引用靶）。
      report —— 鸭子类型收集器（error/warning 与 validator._Checker._err/_warn 签名一致）。
    出参：None；违规一律红拦（【工程补白 P-5】契约 §4.2 未标级别，按数据完整性取红）。
    核心逻辑：
      - 条目须为对象；equip_id 必填非空 string 且条目内唯一；
        equip_id 引用 items 存在（items 模块已接线时；未接线跳过引用检查）。
      - slots 数组 1-3 个（【工程补白 SOCK-01】单件槽位数默认 1-3，内容包可配）。
      - 每个槽位 slot_level 整数 ∈ 1-3（定稿 L258/L260）。
    """
    slots = modules.get("slots")
    if not isinstance(slots, list):
        return  # 未接线 slots 模块 → 跳过（§2.3 默认放行）
    # equip_id 引用靶 = items ∪ equipment（共享 item_lib）【收口裁决 2026-08-29】
    item_ids = _id_set(modules, "items") | _id_set(modules, "equipment")
    items_wired = (
        isinstance(modules.get("items"), list)
        or isinstance(modules.get("equipment"), list)
    )
    seen: set = set()
    for i, entry in enumerate(slots):
        node_id = (
            str(entry.get("equip_id"))
            if isinstance(entry, Mapping) and entry.get("equip_id")
            else f"#{i}"
        )
        if not isinstance(entry, Mapping):
            _slots_err(report, f"slots.{i}", "SLOT-01",
                       rule="slot_entry_not_object", node_id=node_id, got=type(entry).__name__)
            continue
        eid = entry.get("equip_id")
        if not isinstance(eid, str) or not eid:
            _slots_err(report, f"slots.{i}.equip_id", "SLOT-01",
                       rule="equip_id_required", node_id=node_id)
        elif eid in seen:
            _slots_err(report, f"slots.{i}.equip_id", "SLOT-01",
                       rule="equip_id_duplicate", equip_id=eid)
        else:
            seen.add(eid)
            if items_wired and eid not in item_ids:
                _slots_err(report, f"slots.{i}.equip_id", "SLOT-01",
                           rule="equip_id_ref_missing", ref=eid, ref_kind="item")
        slots_list = entry.get("slots")
        if not isinstance(slots_list, list):
            _slots_err(report, f"slots.{i}.slots", "SLOT-02",
                       rule="slots_not_list", got=type(slots_list).__name__)
        elif not (1 <= len(slots_list) <= 3):
            _slots_err(report, f"slots.{i}.slots", "SLOT-02",
                       rule="slots_count_out_of_range", count=len(slots_list))
        else:
            for j, s in enumerate(slots_list):
                if not isinstance(s, Mapping):
                    _slots_err(report, f"slots.{i}.slots.{j}", "SLOT-03",
                               rule="slot_not_object", index=j)
                    continue
                sl = s.get("slot_level")
                if not _is_int(sl) or not (1 <= sl <= 3):
                    _slots_err(report, f"slots.{i}.slots.{j}.slot_level", "SLOT-03",
                               rule="slot_level_invalid", value=sl)


# =====================================================================================
# 字段定义（ALCHEMY_SETTINGS_FIELD_DEFS + alchemy_settings_meta）已迁移至 field_meta
# 统一持有，本文件顶部单向 import（收口裁决 2026-08-29，防循环依赖）。
# =====================================================================================


__all__ = [
    # 常量 / 枚举 / 默认值
    "QUALITY_KEYS", "QUALITY_KEYS_CN", "JOB_TIER_NAMES", "DECOMPOSE_TIER_NAMES",
    "MODE_VALUES", "PP_REFRESH_ENUM", "DECOMPOSE_FORMULA_ENUM",
    "QUALITY_TIER_COUNTS", "DEFAULT_GEM_DIMINISH", "MAX_QTY_DEFAULT",
    "BATTLE_ALCHEMY_DEFAULT", "ALCHEMY_ELEMENTS", "ITEM_RARITY_KEYS",
    "CATALYST_UNLOCK_TIER_ENUM",
    "GEM_DECOMPOSE_KEY", "GEM_DUPLICATE_KEY", "GEM_COST_INT_KEYS",
    "GEM_EXTRA_KEY", "GEM_EXTRA_ALIAS", "GEM_SECRET_KEY", "GEM_DECOMPOSE_FORMULA_KEY",
    "BATTLE_ITEM_KEY", "BATTLE_ALCHEMY_KEY",
    # 校验器
    "check_settings_alchemy", "validate_slots",
    # 字段定义
    "ITEMS_ALCHEMY_FIELDS", "SLOTS_FIELD_DEFS", "ALCHEMY_SETTINGS_FIELD_DEFS",
    # 接线辅助
    "slots_module_meta", "alchemy_settings_meta",
]
