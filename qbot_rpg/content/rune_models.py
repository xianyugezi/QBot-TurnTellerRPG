"""批46 · 符文数据层：runes.json 数据模型 + 专项校验器（qbot_rpg/content/rune_models.py）。

定位：符文定义（`runes.json`，list 模块）的**专项校验**。字段口径（id/name/tier/family/
by_equip_type/effects/bias）登记在 `content/field_meta.py` 的 `_module_table()["runes"]`；
本文件只做**跨字段/引用/枚举**深度校验，鸭子类型 `(modules, report)` 口径对齐
`alchemy_models.validate_recipes` / `alchemy_settings.validate_slots`。

依据：
  - `/root/deliverables/符文系统_实现口径.md` §二.1 校验点 1~6：
      1) `tier ∈ {1,2,3}` 红拦（R3 独立刻度，禁与 quality 混）；
      2) `tier==1` → 必须有 `by_equip_type[*].stats` 且键集必须属于 `GEAR_NUMERIC_KEYS`，
         红拦自造键（R4）；
      3) `tier>=2` → `effects` 引用存在（effects 注册表），红拦悬空引用（R6）；
      4) `by_equip_type` 必须含 `default`；其余键须是合法 `items.type` 值，未知键黄提示；
      5) `tier==3` 且 `bias` 非空 → 按 Q7 结论校验（Q7 未裁决 → 本批只提示，不红拦）；
      6) `family` 相同的符文才允许互为 3 合 1 输入（R5）→ family 必填非空。
  - `docs/深度打造_决策记录.md` H2（品质正交——符文三阶独立刻度）。

【工程补白 · 显式标注】
  1. `tier` 枚举走本模块红拦（field_meta 里 `tier` 登记为 int + range 1..3，泛型 R-2 亦拦
     越界；本模块另给规则号 RUNE-01，语义与 R3 对齐）。
  2. `by_equip_type` 未知类型键 = **黄提示**（Y-1，对齐 slots 引用检查的宽严口径：
     先有数据、后补 items 条目合法；不硬拦作者）。
  3. `tier==1` 的 `stats` 下限：只要求 `default` 条目有非空 stats（其余类型覆盖条目可只写
     差异项；default+覆盖合并后仍有数值）。
  4. `bias`（3 阶偏向性，Q7）机制未裁决 → 本批仅当 `tier==3` 且 `bias` 非空时给**信息级
     note**，不红拦、不臆断其形状。
  5. 符文条目 id 唯一性：模块内唯一（命名空间独立于 items.id，口径 §二.1）。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Set

from qbot_rpg.data.runes import (
    DEFAULT_EQUIP_TYPE_KEY,
    MAX_RUNE_TIER,
    MIN_RUNE_TIER,
    rune_tier_of,
)
from qbot_rpg.data.gear_stats import GEAR_NUMERIC_KEYS

__all__ = ["validate_runes"]

# 规则号（供报告/测试稳定引用；前缀 RUNE）
RUNE_ID = "RUNE-01"
RUNE_TIER = "RUNE-02"
RUNE_FAMILY = "RUNE-03"
RUNE_BY_TYPE = "RUNE-04"
RUNE_STATS = "RUNE-05"
RUNE_EFFECTS = "RUNE-06"
RUNE_BIAS = "RUNE-07"


def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """鸭子类型报告收集器（对齐 alchemy_models._emit：先试 method，再试下划线别名）。"""
    mapping = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, mapping.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "runes", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "runes", field, kind, **detail)


def _note(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "note", "runes", field, kind, **detail)


def _is_int(v: object) -> bool:
    """整数判定（排除 bool——bool 是 int 子类）。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _id_set(modules: Mapping[str, object], name: str) -> Set[str]:
    """模块条目 id 集合（引用靶；非 list/非对象条目跳过）。"""
    mod = modules.get(name)
    if not isinstance(mod, list):
        return set()
    return {str(e.get("id")) for e in mod if isinstance(e, Mapping) and e.get("id")}


def _item_type_set(modules: Mapping[str, object]) -> Set[str]:
    """items ∪ equipment 的 `type` 值集（by_equip_type 未知键黄提示用）。"""
    out: Set[str] = set()
    for name in ("items", "equipment"):
        mod = modules.get(name)
        if not isinstance(mod, list):
            continue
        for e in mod:
            if isinstance(e, Mapping) and isinstance(e.get("type"), str) and e.get("type"):
                out.add(e["type"])
    return out


def validate_runes(modules: Mapping[str, object], report: object) -> None:
    """runes.json 模块专项校验（口径 §二.1 校验点 1~6）。纯函数，无副作用。

    入参：
      modules —— 模块名 → parsed JSON（含 "runes" 列表；可选引用靶 items/equipment/effects）。
      report  —— 鸭子类型收集器（_err/_warn/_note 签名与 validator._Checker 一致）。
    出参：None；红拦（error）/ 黄提示（warning）/ 信息（note）全部经 report 追加。
    核心：未接线 runes 模块（非 list）→ 直接返回（§2.3 默认放行）；逐条目按
          RUNE-01~07 判定，一次给全量。
    """
    runes = modules.get("runes")
    if not isinstance(runes, list):
        return  # 未接线 runes 模块 → 跳过（§2.3 默认放行）

    effect_ids = _id_set(modules, "effects")
    effects_wired = isinstance(modules.get("effects"), list)
    item_types = _item_type_set(modules)
    items_wired = isinstance(modules.get("items"), list) or isinstance(
        modules.get("equipment"), list
    )
    gear_keys = set(GEAR_NUMERIC_KEYS)
    seen_ids: Set[str] = set()

    for i, entry in enumerate(runes):
        node_id = (
            str(entry.get("id")) if isinstance(entry, Mapping) and entry.get("id") else f"#{i}"
        )
        if not isinstance(entry, Mapping):
            _err(report, f"runes.{i}", RUNE_ID, rule="rune_entry_not_object",
                 node_id=node_id, got=type(entry).__name__)
            continue

        # RUNE-01：id 必填非空 + 模块内唯一
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid:
            _err(report, f"runes.{i}.id", RUNE_ID, rule="rune_id_required", node_id=node_id)
        elif rid in seen_ids:
            _err(report, f"runes.{i}.id", RUNE_ID, rule="rune_id_duplicate", rune_id=rid)
        else:
            seen_ids.add(rid)

        # RUNE-02：tier ∈ {1,2,3} 红拦（独立刻度；不读 quality）
        tier = rune_tier_of(entry)
        if tier is None:
            _err(report, f"runes.{node_id}.tier", RUNE_TIER, rule="tier_invalid",
                 node_id=node_id, value=entry.get("tier"),
                 allowed=[MIN_RUNE_TIER, 2, MAX_RUNE_TIER])

        # RUNE-03：family 必填非空（3 合 1 同族判定输入）
        fam = entry.get("family")
        if not isinstance(fam, str) or not fam:
            _err(report, f"runes.{node_id}.family", RUNE_FAMILY, rule="family_required",
                 node_id=node_id, value=fam)

        _check_by_equip_type(report, entry, node_id, tier, item_types, items_wired, gear_keys)
        _check_effects(report, entry, node_id, tier, effect_ids, effects_wired)

        # RUNE-07：3 阶偏向性（Q7 未裁决 → 信息级提示，不臆断形状）
        if tier == MAX_RUNE_TIER and entry.get("bias") is not None:
            _note(report, f"runes.{node_id}.bias", RUNE_BIAS, rule="bias_pending_ruling",
                  node_id=node_id,
                  msg="3 阶偏向性（Q7）机制未裁决：本批只登记不解释，勿据此实现")


def _check_by_equip_type(
    report: object,
    entry: Mapping[str, Any],
    node_id: str,
    tier: Optional[int],
    item_types: Set[str],
    items_wired: bool,
    gear_keys: Set[str],
) -> None:
    """RUNE-04/05：by_equip_type 结构 + default 兜底 + stats 键空间 + 未知类型黄提示。"""
    bet = entry.get("by_equip_type")
    if not isinstance(bet, Mapping):
        _err(report, f"runes.{node_id}.by_equip_type", RUNE_BY_TYPE,
             rule="by_equip_type_not_object", node_id=node_id,
             got=type(bet).__name__)
        return
    if DEFAULT_EQUIP_TYPE_KEY not in bet:
        _err(report, f"runes.{node_id}.by_equip_type", RUNE_BY_TYPE,
             rule="by_equip_type_default_missing", node_id=node_id)
    for key, val in bet.items():
        key_s = str(key)
        if not isinstance(val, Mapping):
            _err(report, f"runes.{node_id}.by_equip_type.{key_s}", RUNE_BY_TYPE,
                 rule="by_equip_type_entry_not_object", node_id=node_id,
                 equip_type=key_s, got=type(val).__name__)
            continue
        stats = val.get("stats")
        if stats is not None:
            if not isinstance(stats, Mapping):
                _err(report, f"runes.{node_id}.by_equip_type.{key_s}.stats", RUNE_STATS,
                     rule="stats_not_object", node_id=node_id, equip_type=key_s,
                     got=type(stats).__name__)
            else:
                for sk in stats.keys():
                    if str(sk) not in gear_keys:
                        _err(report,
                             f"runes.{node_id}.by_equip_type.{key_s}.stats.{sk}",
                             RUNE_STATS, rule="stat_key_unknown", node_id=node_id,
                             equip_type=key_s, key=str(sk))
        # 未知类型键：黄提示（先有数据后补 items 条目合法；不硬拦作者）
        if (key_s != DEFAULT_EQUIP_TYPE_KEY and items_wired and key_s not in item_types):
            _warn(report, f"runes.{node_id}.by_equip_type.{key_s}", RUNE_BY_TYPE,
                  rule="equip_type_unknown", node_id=node_id, equip_type=key_s)
    # tier==1：纯数值加成 → default 必须给出非空 stats（R4）
    if tier == MIN_RUNE_TIER:
        dflt = bet.get(DEFAULT_EQUIP_TYPE_KEY)
        dflt_stats = dflt.get("stats") if isinstance(dflt, Mapping) else None
        if not isinstance(dflt_stats, Mapping) or not dflt_stats:
            _err(report, f"runes.{node_id}.by_equip_type.default.stats", RUNE_STATS,
                 rule="tier1_stats_required", node_id=node_id,
                 msg="1 阶符文为单纯数值加成：default 必须给出非空 stats")


def _check_effects(
    report: object,
    entry: Mapping[str, Any],
    node_id: str,
    tier: Optional[int],
    effect_ids: Set[str],
    effects_wired: bool,
) -> None:
    """RUNE-06：effects 结构 + 引用存在性（悬空红拦）；tier>=2 缺 effects 不红拦。"""
    effs = entry.get("effects")
    if effs is None:
        return
    if not isinstance(effs, list):
        _err(report, f"runes.{node_id}.effects", RUNE_EFFECTS, rule="effects_not_list",
             node_id=node_id, got=type(effs).__name__)
        return
    for j, e in enumerate(effs):
        if not isinstance(e, Mapping):
            _err(report, f"runes.{node_id}.effects.{j}", RUNE_EFFECTS,
                 rule="effect_entry_not_object", node_id=node_id, got=type(e).__name__)
            continue
        eid = e.get("effect")
        if not isinstance(eid, str) or not eid:
            _err(report, f"runes.{node_id}.effects.{j}.effect", RUNE_EFFECTS,
                 rule="effect_id_required", node_id=node_id)
        elif effects_wired and eid not in effect_ids:
            _err(report, f"runes.{node_id}.effects.{j}.effect", RUNE_EFFECTS,
                 rule="effect_ref_missing", node_id=node_id, ref=eid, ref_target="effects")
