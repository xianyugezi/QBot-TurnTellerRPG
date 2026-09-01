"""M13 6c 资源轴注册段专项校验器（细化_6c §1.1/§1.5：V1~V4 + V6~V11）。

文件名：resource_axis_validator.py
创建时间：2026-09-02
依据：docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
  - M1 注册段 10 字段结构（V1 红拦）；
  - 数值合法（V2 黄提示：base≥0 / max>base / max_per_pool>0）；
  - reset 三枚举（V3 红拦：battle/keep/battle_start）；
  - display/icon 可选（V4 黄提示缺失）。
  - §五 V6~V11（批12 路12B 追加，追加不覆盖批8 V1~V5 段）：
    - V6 注册结构（红拦）：数值型 max ≥ 0（0=不限）；子池型 pools 非空、池名
      ∈ 元素注册表、max_per_pool ≥ 1、pool_icons 键 = pools 完整集合；
    - V7 键空间与层数型隔离（红拦）：energy_cost 的 any 键仅子池型技能合法、
      同技能 any 与具名键互斥（K3）；层数型资源（marks 型）出现于 energy 键
      → 红拦（须用 mark_add/consume_marks）；
    - V8 组合表校验（黄提示）：combo 行元素 ∈ 轴 pools；行 kind 枚举
      （damage/utility/heal/control）；power 0-400；行数 ≤ C(|pools|+1,2)
      无重组合上限；每组合 ≥1 获取路径（可达性 RE-1~4，黄提示）；
    - V9 季节组校验（红拦）：season ∈ 四枚举；每季技能组非空且 ≤5；通用组
      ≥1（普攻兜底必在）；season_element 键 = 四季完整四枚；
    - V10 互译表登记（红拦）：condition 引用 [季节:X] 需在互译表登记
      （框架已登记四季 → 只查自定义季节）；season_element 值 ∈ 元素注册表；
    - V11 事件枚举登记（红拦）：proc trigger 名 ∈ SEASON_EVENTS 枚举登记表。

功能描述：
  - validate_resource_axes(modules, report) 纯函数专项校验器（对齐
    validate_skills/validate_jobs 形态：_err/_warn 三形态收集器，module 恒为
    "stats"）——stats.json 内每个 resource 型条目的注册段校验（V1~V4 + V6）；
  - validate_skill_energy(modules, report) 技能侧 6c 新增校验（V7~V11）——
    挂 skills 模块校验，与 stats 侧同文件分入口（校验器按模块路由）。

工程补白：
  P-1  stats 条目 type=resource 但带 pools → 子池型（D-01 以 pools 非空判别）；
  P-2  非 resource 型条目（combat 属性）跳过（注册段只约束资源轴）；
  P-3  V6 池名元素注册表 = 8 元素默认 ∪ 包内 formula.json elements 段键
       （镜像 validator._DEFAULT_ELEMENTS 口径，content 层零 core import）；
  P-4  V7 层数型判定 = 键 ∈ marks.json id 集合（marks 模块缺省空集 → 无判定）；
  P-5  V10 互译表为本地常量镜像（condition_engine L164 已登记 [季节:{T}]→season，
       content 层零 engine import；框架四季键视为已登记，只查自定义季节）；
  P-6  V11 事件枚举表 = SEASON_EVENTS 本地常量镜像（core/season_events.py 批10
       已落盘，content 层零 core import——G0 铁律；core 已登记 on_season_change，
       本表同时登记 1b proc 通用事件 on_turn_start/on_hit）；
  P-7  V9 季节组统计范围为 skills.json 全库（job_restrict/job_form 不剔除——
       内容包形态由作者负责；普攻=type basic 计入通用组）。

铁律：零 NoneBot import；G0：content 层零 engine/core import（SEASON_EVENTS
用本地常量镜像，经 ctx 注入亦可）；零定时器/零睡眠；纯函数确定性；不 git
commit。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from qbot_rpg.content.resource_axis_models import (
    AXIS_TYPES,
    RESET_VALUES,
    ResourceAxisDef,
)
from qbot_rpg.content.skill_models import SKILL_ELEMENTS

MODULE_NAME: str = "stats"
MODULE_NAME_SKILLS: str = "skills"

# =====================================================================================
# 常量（V6~V11 契约口径；G0 镜像：content 层零 engine/core import）
# =====================================================================================

# V6 元素注册表（细化_6c §1.1 字段 9「池名 ∈ formula.json 8 元素注册表」；
# 镜像 validator._DEFAULT_ELEMENTS / core 同源，content 层零 core import）
DEFAULT_ELEMENTS: Tuple[str, ...] = SKILL_ELEMENTS

# V8 组合行 kind 枚举（细化_6c §3.1 C3；control 为契约【工程补白】扩展）
COMBO_KINDS: Tuple[str, ...] = ("damage", "utility", "heal", "control")

# V8 power 封顶（细化_6c §3.1 C4 / V8：0-400，对齐狂战士 L409/四时 L414 ≤400；
# 幻觉审查_6c 修正原 0-500 无依据）
COMBO_POWER_MAX: float = 400.0

# V9 四季枚举（细化_6c §2.1 SE1：spring/summer/autumn/winter，缺省=通用）
SEASONS: Tuple[str, ...] = ("spring", "summer", "autumn", "winter")

# V9 组规模上限（细化_6c V9：每季 ≤5；通用组 ≥1）
SEASON_GROUP_MAX: int = 5

# V10 互译表（2a4c 时间天气接口；本地镜像 condition_engine L164 已登记
# [季节:{T}]→season，content 层零 engine import——P-5：框架四季键视为已登记，
# 只查自定义季节）
TRANSLATED_SEASONS: Tuple[str, ...] = SEASONS

# V10 季节条件键前缀（消费点 2：condition 引用 [季节:X]）
SEASON_COND_PREFIX: str = "[季节:"

# V10 消费点 3：season_element 值 ∈ 元素注册表（默认 春风/夏火/秋地/冬水）
SEASON_ELEMENT_KEYS: Tuple[str, ...] = SEASONS

# V11 事件枚举登记表（本地镜像 core/season_events.SEASON_EVENTS 批10 已落盘
# + 1b proc 通用事件 on_turn_start/on_hit；P-6）
SEASON_EVENTS_MIRROR: Tuple[str, ...] = ("on_season_change",)
PROC_TRIGGER_EVENTS: Tuple[str, ...] = ("on_turn_start", "on_hit", "on_season_change")


def _combo_row_limit(pool_count: int) -> int:
    """组合行数上限（细化_6c §3.1 编排约束：C(|pools|+1,2)，3 池 → 6）。"""
    return max(0, (pool_count + 1) * pool_count // 2)


# =====================================================================================
# 收集器发射（三形态兼容：_Checker._err/_warn → dict → list → 鸭子类型兜底）
# =====================================================================================

def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    if hasattr(report, "_err") and level == "error":
        report._err(MODULE_NAME, field, kind, **detail)
        return
    if hasattr(report, "_warn") and level == "warning":
        report._warn(MODULE_NAME, field, kind, **detail)
        return
    if isinstance(report, dict):
        rec = {"field": field, "kind": kind, "level": level, **detail}
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])
        bucket.append(rec)
        return
    if isinstance(report, list):
        report.append({"field": field, "kind": kind, "level": level, **detail})
        return
    if hasattr(report, "error") and level == "error":
        report.error(MODULE_NAME, field, kind, **detail)
        return
    if hasattr(report, "warning") and level == "warning":
        report.warning(MODULE_NAME, field, kind, **detail)
        return


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", field, kind, **detail)


# =====================================================================================
# 元素注册表（V6/V8/V9 消费）
# =====================================================================================

def _element_registry(modules: Mapping[str, object]) -> frozenset:
    """元素注册表：8 元素默认 ∪ 包内 formula.json elements 段键。

    P-3：镜像 validator._element_registry 口径（content 层零 core import）；
    formula 模块缺省/非 Mapping → 默认 8 元素。
    """
    reg: set = set(DEFAULT_ELEMENTS)
    formula = modules.get("formula")
    if isinstance(formula, Mapping):
        elems = formula.get("elements")
        if isinstance(elems, Mapping):
            reg.update(k for k in elems if isinstance(k, str))
    return frozenset(reg)


# =====================================================================================
# 专项校验（stats 侧：V1~V4 注册段 + V6 注册结构）
# =====================================================================================

def _check_axis_entry(report: object, axis_id: str, raw: Mapping[str, Any]) -> None:
    """单条资源轴注册段校验（V1~V4）。"""
    base = f"{axis_id}"
    d = ResourceAxisDef(raw)

    # V1 注册结构（红拦）：type ∈ 两型；子池型必填 pools/max_per_pool
    t = raw.get("type")
    if t is not None and t not in AXIS_TYPES:
        _err(report, f"{base}.type", "V1", rule="axis_type_invalid",
             node_id=axis_id, value=t, allowed=list(AXIS_TYPES),
             msg=f"资源轴 type {t} 不在两型（rage/element_energy 兼容旧键）（V1）")
    # 子池型判定：type 归一后 element_energy，或 raw 显式 pools（D-01 以 pools 为准）
    d_type = d.type
    is_pooled = bool(raw.get("pools")) or d_type == "element_energy"
    if is_pooled:
        pools = raw.get("pools")
        if not isinstance(pools, list) or not pools:
            _err(report, f"{base}.pools", "V1", rule="pooled_missing_pools",
                 node_id=axis_id,
                 msg="子池型资源轴必填 pools 非空数组（V1：D-01 池级展开）")
        mpp = raw.get("max_per_pool")
        if mpp is None:
            _err(report, f"{base}.max_per_pool", "V1", rule="pooled_missing_max_per_pool",
                 node_id=axis_id,
                 msg="子池型资源轴必填 max_per_pool（V1：池级上限）")

    # V2 数值合法（黄提示）：base≥0 / max>base / max_per_pool>0
    base_v = d.base
    if base_v < 0:
        _warn(report, f"{base_v}.base", "V2", rule="base_negative",
              node_id=axis_id, base=base_v, msg=f"资源轴 {axis_id} base 不能为负（V2）")
    mx = raw.get("max")
    if isinstance(mx, (int, float)) and not isinstance(mx, bool):
        if mx <= base_v:
            _warn(report, f"{base_v}.max", "V2", rule="max_not_above_base",
                  node_id=axis_id, base=base_v, max=mx,
                  msg=f"资源轴 {axis_id} max 应 > base（V2）")
    mpp = raw.get("max_per_pool")
    if isinstance(mpp, (int, float)) and not isinstance(mpp, bool) and mpp <= 0:
        _warn(report, f"{base}.max_per_pool", "V2", rule="max_per_pool_nonpositive",
              node_id=axis_id, max_per_pool=mpp,
              msg=f"资源轴 {axis_id} max_per_pool 应 > 0（V2）")

    # V3 reset 枚举（红拦）
    rs = raw.get("reset")
    if rs is not None and rs not in RESET_VALUES:
        _err(report, f"{base}.reset", "V3", rule="reset_enum_invalid",
             node_id=axis_id, value=rs, allowed=list(RESET_VALUES),
             msg=f"资源轴 {axis_id} reset {rs} 不在三枚举（battle/keep/battle_start）（V3）")

    # V4 display/icon 可选（黄提示缺失）
    if not d.display:
        _warn(report, f"{base}.display", "V4", rule="display_missing",
              node_id=axis_id, msg=f"资源轴 {axis_id} 缺 display（V4：可选提示）")
    if not d.icon:
        _warn(report, f"{base}.icon", "V4", rule="icon_missing",
              node_id=axis_id, msg=f"资源轴 {axis_id} 缺 icon（V4：可选提示）")


def _check_v6_axis_structure(
    report: object,
    axis_id: str,
    raw: Mapping[str, Any],
    elements: frozenset,
) -> None:
    """V6 注册段结构（红拦）：数值型 max ≥ 0（0=不限）；子池型 pools 非空、
    池名 ∈ 元素注册表、max_per_pool ≥ 1、pool_icons 键 = pools 完整集合。"""
    base = f"{axis_id}"
    d = ResourceAxisDef(raw)
    is_pooled = bool(raw.get("pools")) or d.type == "element_energy"

    # V6-1 数值型 max ≥ 0（0=不限；负值红拦）
    mx = raw.get("max")
    if not is_pooled and isinstance(mx, (int, float)) and not isinstance(mx, bool):
        if mx < 0:
            _err(report, f"{base}.max", "V6", rule="axis_max_negative",
                 node_id=axis_id, max=mx,
                 msg=f"资源轴 {axis_id} max 不能为负（V6：0=不限）")

    # V6-2 子池型：池名 ∈ 元素注册表（V1 已查 pools 必填，此处查注册表）
    pools = raw.get("pools")
    if is_pooled and isinstance(pools, list) and pools:
        for p in pools:
            if not isinstance(p, str):
                continue
            if p not in elements:
                _err(report, f"{base}.pools", "V6", rule="pool_element_unregistered",
                     node_id=axis_id, pool=p, allowed=sorted(elements),
                     msg=f"资源轴 {axis_id} 池名 {p} 未在元素注册表登记（V6）")

    # V6-3 子池型 max_per_pool ≥ 1（缺失/0/负 → 红拦）
    if is_pooled:
        mpp = raw.get("max_per_pool")
        if isinstance(mpp, (int, float)) and not isinstance(mpp, bool) and mpp < 1:
            _err(report, f"{base}.max_per_pool", "V6", rule="max_per_pool_lt_one",
                 node_id=axis_id, max_per_pool=mpp,
                 msg=f"资源轴 {axis_id} max_per_pool 应 ≥ 1（V6）")

    # V6-4 子池型 pool_icons 键 = pools 完整集合（缺任一池图标 → 红拦）
    if is_pooled and isinstance(pools, list) and pools:
        str_pools = [p for p in pools if isinstance(p, str)]
        icons = raw.get("pool_icons")
        if str_pools:
            if not isinstance(icons, Mapping):
                _err(report, f"{base}.pool_icons", "V6", rule="pool_icons_missing",
                     node_id=axis_id, pools=str_pools,
                     msg=f"子池型资源轴 {axis_id} 缺 pool_icons（V6：键须 = pools 完整集合）")
            else:
                missing = [p for p in str_pools if p not in icons]
                if missing:
                    _err(report, f"{base}.pool_icons", "V6", rule="pool_icons_missing_keys",
                         node_id=axis_id, missing=missing,
                         msg=f"子池型资源轴 {axis_id} pool_icons 缺池 {missing}（V6）")


# =====================================================================================
# 技能侧：V7 键空间与层数型隔离 / V8 组合表 / V9 季节组 / V10 互译表 / V11 事件枚举
# =====================================================================================

def _stat_entries(modules: Mapping[str, object]) -> Dict[str, Mapping[str, Any]]:
    """stats.json 注册段索引（axis_id → 条目；仅 Mapping 条目入表）。"""
    stats = modules.get("stats")
    out: Dict[str, Mapping[str, Any]] = {}
    if isinstance(stats, Mapping):
        for k, v in stats.items():
            if isinstance(k, str) and isinstance(v, Mapping):
                out[k] = v
    return out


def _pooled_axis_ids(modules: Mapping[str, object]) -> Dict[str, Tuple[str, ...]]:
    """子池型轴 → pools 池名表（D-01 判别：pools 非空或 type=element_energy）。"""
    out: Dict[str, Tuple[str, ...]] = {}
    for axis_id, raw in _stat_entries(modules).items():
        d = ResourceAxisDef(raw)
        pools = tuple(p for p in d.pools if p)
        if pools or d.type == "element_energy":
            out[axis_id] = pools
    return out


def _marks_ids(modules: Mapping[str, object]) -> frozenset:
    """marks.json id 集合（V7 层数型判定靶；模块缺省 → 空集 → 无判定，P-4）。"""
    marks = modules.get("marks")
    out: set = set()
    if isinstance(marks, list):
        for e in marks:
            if isinstance(e, Mapping):
                v = e.get("id")
                if isinstance(v, str) and v:
                    out.add(v)
    return frozenset(out)


def _energy_segment(entry: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """技能 energy_gain/energy_cost 段归一（非 Mapping → 空 dict）。"""
    seg = entry.get(key)
    return seg if isinstance(seg, Mapping) else {}


def _check_v7_key_space(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, Any],
    pooled: Mapping[str, Tuple[str, ...]],
    marks: frozenset,
) -> None:
    """V7 键空间与层数型隔离（红拦）：any 键仅子池型技能合法；同技能 any 与
    具名键互斥（K3）；层数型资源（marks 型）出现于 energy 键 → 红拦。"""
    for seg_key in ("energy_gain", "energy_cost"):
        seg = _energy_segment(entry, seg_key)
        if not seg:
            continue
        has_any = "any" in seg
        named = [k for k in seg if k != "any"]
        if has_any and named:
            _err(report, f"{base}.{seg_key}", "V7", rule="any_named_mutex",
                 node_id=sid, seg=seg_key, any_key="any", named_keys=named,
                 msg=f"技能 {sid} {seg_key} 中 any 键与具名键互斥（V7：K3）")
        if has_any:
            # 技能所属轴 = 轴包装键（形态 1：{axis_id: {key: amount}}）或
            # 裸键（形态 2：{rage: 100}，键即资源 ID，K1）
            axes = [k for k in seg if k != "any"]
            wrapped = [k for k in axes if isinstance(seg.get(k), Mapping)]
            for ax in (wrapped or axes):
                if ax not in pooled:
                    _err(report, f"{base}.{seg_key}", "V7", rule="any_on_numeric_axis",
                         node_id=sid, seg=seg_key, axis=ax,
                         msg=f"技能 {sid} any 键仅子池型技能合法（V7：轴 {ax} 非子池型）")
        for k in named:
            if k in marks:
                _err(report, f"{base}.{seg_key}", "V7", rule="mark_in_energy_key",
                     node_id=sid, seg=seg_key, key=k,
                     msg=f"技能 {sid} 层数型资源 {k} 出现在 energy 键（V7：须用 "
                         "mark_add/consume_marks）")


def _check_v8_combo_table(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, Any],
    pooled: Mapping[str, Tuple[str, ...]],
    elements: frozenset,
    skills_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    """V8 组合表校验（黄提示不拦截）：combo 行元素 ∈ 轴 pools；行 kind 枚举；
    power 0-400；行数 ≤ C(|pools|+1,2)；每组合 ≥1 获取路径（可达性 RE-1~4）。"""
    rows = entry.get("combo_table")
    if not isinstance(rows, list) or not rows:
        return
    # 技能所属轴 = energy_cost 轴包装键 ∪ energy_gain 轴包装键（V8 组合行只
    # 对子池型轴合法；缺轴 → 无 pools 可查，元素引用按不合法黄提示）
    cost_seg = _energy_segment(entry, "energy_cost")
    gain_seg = _energy_segment(entry, "energy_gain")
    axis_candidates: List[str] = []
    for seg in (cost_seg, gain_seg):
        for k, v in seg.items():
            if k != "any" and isinstance(v, Mapping):
                axis_candidates.append(k)
    axis_id = axis_candidates[0] if axis_candidates else ""
    pools = pooled.get(axis_id, ()) if axis_id else ()
    limit = _combo_row_limit(len(pools))
    if rows and limit and len(rows) > limit:
        _warn(report, f"{base}.combo_table", "V8", rule="combo_rows_over_limit",
              node_id=sid, rows=len(rows), limit=limit,
              msg=f"技能 {sid} 组合行数 {len(rows)} 超无重组合上限 {limit}（V8 黄提示）")
    seen_combos: set = set()
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        rbase = f"{base}.combo_table[{i}]"
        combo = row.get("combo")
        items = tuple(x for x in combo if isinstance(x, str)) if isinstance(combo, list) else ()
        if not items:
            _warn(report, rbase, "V8", rule="combo_empty", node_id=sid, row=i,
                  msg=f"技能 {sid} 组合行 {i} 缺 combo 多重集（V8 黄提示）")
            continue
        key = tuple(sorted(items))
        if key in seen_combos:
            _warn(report, rbase, "V8", rule="combo_duplicate", node_id=sid, row=i,
                  combo=list(items),
                  msg=f"技能 {sid} 组合行 {i} 与既有组合重复（V8 黄提示）")
        seen_combos.add(key)
        unknown = [p for p in items if pools and p not in pools]
        if unknown:
            _warn(report, rbase, "V8", rule="combo_element_unregistered", node_id=sid,
                  row=i, pools=unknown, axis=axis_id,
                  msg=f"技能 {sid} 组合行 {i} 元素 {unknown} 不在轴 {axis_id} 池（V8）")
        kind = row.get("kind")
        if kind is not None and kind not in COMBO_KINDS:
            _warn(report, rbase, "V8", rule="combo_kind_invalid", node_id=sid, row=i,
                  value=kind, allowed=list(COMBO_KINDS),
                  msg=f"技能 {sid} 组合行 {i} kind {kind} 不在四枚举（V8）")
        power = row.get("power")
        if isinstance(power, (int, float)) and not isinstance(power, bool):
            if power < 0 or power > COMBO_POWER_MAX:
                _warn(report, rbase, "V8", rule="combo_power_out_of_range",
                      node_id=sid, row=i, power=power, max=COMBO_POWER_MAX,
                      msg=f"技能 {sid} 组合行 {i} power {power} 应 0-400（V8）")
        el = row.get("element")
        if isinstance(el, str) and el and el not in elements:
            _warn(report, rbase, "V8", rule="combo_element_unknown", node_id=sid,
                  row=i, element=el,
                  msg=f"技能 {sid} 组合行 {i} element {el} 不在 8 元素注册表（V8）")
    # 可达性（RE-1~4）：组合行涉及的每个池至少存在一种产出技（energy_gain 途径）
    # 产出技两种形态均计入：裸键 {fire: 1} 与轴包装 {element_energy: {fire: 1}}
    if pools and seen_combos:
        producers: Dict[str, int] = {}
        for sk, sraw in skills_by_id.items():
            gain = _energy_segment(sraw, "energy_gain")
            for k, v in gain.items():
                if isinstance(v, Mapping):
                    # 轴包装形态：{axis: {pool: amount}}
                    for pk, amt in v.items():
                        if pk != "any" and isinstance(amt, (int, float)) \
                                and not isinstance(amt, bool) and amt > 0 \
                                and pk in pools:
                            producers[pk] = producers.get(pk, 0) + 1
                elif isinstance(v, (int, float)) and not isinstance(v, bool) \
                        and v > 0 and k in pools:
                    producers[k] = producers.get(k, 0) + 1
        unreachable = sorted(p for p in pools if p not in producers)
        if unreachable:
            _warn(report, f"{base}.combo_table", "V8", rule="combo_unreachable",
                  node_id=sid, pools=unreachable,
                  msg=f"技能 {sid} 组合行池 {unreachable} 无获取路径（V8 黄提示："
                      "死配置可加载）")


def _check_v9_season_groups(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, Any],
    group_counts: Dict[str, int],
) -> None:
    """V9 季节组校验（红拦）：season 枚举；组规模统计（库级判定收口）。"""
    season = entry.get("season")
    if season is not None:
        if not isinstance(season, str) or season not in SEASONS:
            _err(report, f"{base}.season", "V9", rule="season_enum_invalid",
                 node_id=sid, value=season, allowed=list(SEASONS),
                 msg=f"技能 {sid} season {season} 不在四枚举（V9）")
    # 组规模统计（含本条目；P-7 全库口径）
    group = season if isinstance(season, str) and season in SEASONS else "general"
    group_counts[group] = group_counts.get(group, 0) + 1


def _check_v9_season_element(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, Any],
    elements: frozenset,
) -> None:
    """V9 season_element（红拦）：键 = 四季完整四枚；值 ∈ 元素注册表。"""
    se = entry.get("season_element")
    if se is None:
        return
    if not isinstance(se, Mapping):
        _err(report, f"{base}.season_element", "V9", rule="season_element_not_map",
             node_id=sid, got=type(se).__name__,
             msg=f"技能 {sid} season_element 需为映射（V9）")
        return
    missing = [k for k in SEASON_ELEMENT_KEYS if k not in se]
    if missing:
        _err(report, f"{base}.season_element", "V9", rule="season_element_missing_keys",
             node_id=sid, missing=missing,
             msg=f"技能 {sid} season_element 缺四季键 {missing}（V9）")
    for k, v in se.items():
        if isinstance(v, str) and v and v not in elements:
            _err(report, f"{base}.season_element.{k}", "V9", rule="season_element_bad_element",
                 node_id=sid, season=k, element=v,
                 msg=f"技能 {sid} season_element {k} 元素 {v} 未注册（V9）")


def _check_v10_translation_table(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, Any],
) -> None:
    """V10 互译表登记（红拦）：condition 引用 [季节:X] 需在互译表登记。

    P-5：框架四季键（spring/summer/autumn/winter）视为已登记（condition_engine
    L164 已落），只查自定义季节键；被动/状态挂条件 {condition: {var:season,...}}
    的 param 亦查。
    """
    cond = entry.get("condition")
    if isinstance(cond, Mapping):
        var = cond.get("var")
        param = cond.get("param")
        if var == "season" and isinstance(param, str) and param \
                and param not in TRANSLATED_SEASONS:
            _err(report, f"{base}.condition", "V10", rule="season_cond_unregistered",
                 node_id=sid, season=param, translated=sorted(TRANSLATED_SEASONS),
                 msg=f"技能 {sid} [季节:{param}] 未在互译表登记（V10）")
        return
    effects = entry.get("effects")
    if not isinstance(effects, list):
        return
    for i, eff in enumerate(effects):
        if not isinstance(eff, Mapping):
            continue
        econd = eff.get("condition")
        if not isinstance(econd, Mapping):
            continue
        var = econd.get("var")
        param = econd.get("param")
        if var == "season" and isinstance(param, str) and param \
                and param not in TRANSLATED_SEASONS:
            _err(report, f"{base}.effects[{i}]", "V10", rule="season_cond_unregistered",
                 node_id=sid, season=param, translated=sorted(TRANSLATED_SEASONS),
                 msg=f"技能 {sid} 效果 {i} 条件 [季节:{param}] 未在互译表登记（V10）")


def _check_v11_event_registry(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, Any],
) -> None:
    """V11 事件枚举登记（红拦）：proc/effect trigger 名 ∈ 事件枚举登记表。

    P-6：PROC_TRIGGER_EVENTS（SEASON_EVENTS 本地镜像 + 1b proc 通用事件）。
    触发上限字段合法（默认每回合 10/每场 99，非负）——上限非负校验：
    trigger_limit 段 per_round/per_battle 非负。
    """
    effects = entry.get("effects")
    if isinstance(effects, list):
        for i, eff in enumerate(effects):
            if not isinstance(eff, Mapping):
                continue
            trig = eff.get("trigger")
            if isinstance(trig, str) and trig and trig not in PROC_TRIGGER_EVENTS:
                _err(report, f"{base}.effects[{i}].trigger", "V11",
                     rule="trigger_event_unregistered", node_id=sid, trigger=trig,
                     allowed=list(PROC_TRIGGER_EVENTS),
                     msg=f"技能 {sid} 效果 {i} trigger {trig} 未登记事件枚举（V11）")
    tl = entry.get("trigger_limit")
    if isinstance(tl, Mapping):
        for k in ("per_round", "per_battle"):
            v = tl.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
                _err(report, f"{base}.trigger_limit.{k}", "V11",
                     rule="trigger_limit_negative", node_id=sid, key=k, value=v,
                     msg=f"技能 {sid} trigger_limit.{k} 不能为负（V11）")


def _check_skill_entry_611(
    report: object,
    entry: Mapping[str, Any],
    idx: int,
    pooled: Mapping[str, Tuple[str, ...]],
    marks: frozenset,
    elements: frozenset,
    skills_by_id: Mapping[str, Mapping[str, Any]],
    group_counts: Dict[str, int],
) -> None:
    """单条技能 6c 新增校验（V7~V11；V7 红拦、V8 黄提示、V9~V11 红拦）。"""
    base = f"[{idx}]"
    sid = entry.get("id")
    if not isinstance(sid, str) or not sid:
        sid = str(idx)
    _check_v7_key_space(report, base, sid, entry, pooled, marks)
    _check_v8_combo_table(report, base, sid, entry, pooled, elements, skills_by_id)
    _check_v9_season_groups(report, base, sid, entry, group_counts)
    _check_v9_season_element(report, base, sid, entry, elements)
    _check_v10_translation_table(report, base, sid, entry)
    _check_v11_event_registry(report, base, sid, entry)


# =====================================================================================
# 主入口
# =====================================================================================

def _check_v5_variable_refs(
    report: object, modules: Mapping[str, object], stats: Mapping[str, object]
) -> None:
    """V5 变量引用（黄提示，契约 §五 L128）：条件内 [我方资源:ID]/[对方资源:ID]
    （含子池级 [我方资源:axis.pool]）所引轴未注册 → 黄提示。

    扫描 effects/conditional 模块的 condition 字段（var=resource 或
    文本 [我方资源:X]），提取资源 ID（池级取轴段），查 stats 注册表。
    未注册 → 黄提示「公式里的 [我方资源:怒气] 资源轴不存在」。
    """
    axis_ids = set(stats.keys())
    for mod_key in ("effects", "conditional"):
        mod = modules.get(mod_key)
        entries = mod if isinstance(mod, list) else (
            list(mod.values()) if isinstance(mod, Mapping) else None
        )
        if not entries:
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            cond = entry.get("condition")
            if isinstance(cond, Mapping):
                var = cond.get("var")
                if isinstance(var, str) and var.startswith("[我方资源:") or \
                        isinstance(var, str) and var.startswith("[对方资源:"):
                    _check_v5_ref(report, var, axis_ids)
            # 文本形态条件（var 字符串）
            for key in ("condition", "var"):
                v = entry.get(key)
                if isinstance(v, str) and ("[我方资源:" in v or "[对方资源:" in v):
                    import re

                    for m in re.finditer(r"\[(?:我方|对方)资源:([^\]]+)\]", v):
                        _check_v5_ref(report, m.group(0), axis_ids)


def _check_v5_ref(report: object, var_text: str, axis_ids: set) -> None:
    """单条 [我方资源:X] 引用检查（池级取轴段）。"""
    import re

    m = re.search(r"资源:([^\]]+)", var_text)
    if not m:
        return
    ref = m.group(1).strip()
    # 池级引用 axis.pool → 轴 = 点分前段
    axis_id = ref.split(".")[0] if "." in ref else ref
    if axis_id not in axis_ids:
        _warn(report, "condition", "V5", rule="v5_axis_ref_unregistered",
              node_id=None, var=var_text, axis_id=axis_id,
              msg=f"公式里的 {var_text} 资源轴不存在（V5：变量引用轴未注册）")


def validate_resource_axes(modules: Mapping[str, object], report: object) -> None:
    """资源轴注册段校验主入口（stats.json 内 resource 型条目；V1~V4 + V6）。

    modules 含 stats（map 形态 {axis_id: {注册段}}）；stats 缺失 → 跳过。
    非 resource 型条目（combat 属性）跳过（P-2）。
    引用表：modules 含 "skills"（list，V8 可达性/组合元素引用靶）与 "formula"
    （elements 段，V6 池名注册表扩展）时启用；缺省 → 元素注册表回退默认 8 元素。
    V5 变量引用扫描 effects/conditional 条件（黄提示）。
    """
    stats = modules.get("stats")
    if not isinstance(stats, Mapping):
        return
    elements = _element_registry(modules)
    for axis_id, raw in stats.items():
        if not isinstance(raw, Mapping):
            continue
        t = raw.get("type")
        # P-2：明确 combat 型条目（属性）跳过；其余（含非法 type）进注册段校验
        # ——非法 type 由 V1 红拦，不能在入口静默放行。
        if t == "combat":
            continue
        _check_axis_entry(report, str(axis_id), raw)
        _check_v6_axis_structure(report, str(axis_id), raw, elements)
    # V5 变量引用（黄提示）
    _check_v5_variable_refs(report, modules, stats)


def validate_skill_energy(modules: Mapping[str, object], report: object) -> None:
    """技能侧 6c 新增校验（V7~V11；V7/V9/V10/V11 红拦、V8 黄提示）。

    挂 skills 模块校验（与 validate_resource_axes 同文件分入口——校验器按
    模块路由；skills 缺省/非 list → 跳过）。V9 组规模为库级判定，遍历完成后
    统一收口（每季 ≤5 / 通用 ≥1）。
    """
    data = modules.get("skills")
    if data is None or not isinstance(data, list):
        return
    pooled = _pooled_axis_ids(modules)
    marks = _marks_ids(modules)
    elements = _element_registry(modules)
    skills_by_id: Dict[str, Mapping[str, Any]] = {}
    for e in data:
        if isinstance(e, Mapping):
            v = e.get("id")
            if isinstance(v, str) and v:
                skills_by_id[v] = e
    group_counts: Dict[str, int] = {}
    for i, entry in enumerate(data):
        if not isinstance(entry, Mapping):
            continue
        _check_skill_entry_611(report, entry, i, pooled, marks, elements,
                               skills_by_id, group_counts)
    _check_v9_group_sizes(report, group_counts)


def validate_season_groups(modules: Mapping[str, object], report: object) -> None:
    """季节组 + 互译表 + 事件枚举专项校验（V9~V11；红拦）。

    V9 组规模为库级判定（每季 ≤5 / 通用 ≥1），由 validate_skill_energy 内部
    收口；本入口为技能模块缺省时的独立兜底（结构校验防误用）。
    """
    data = modules.get("skills")
    if data is None or not isinstance(data, list):
        return
    validate_skill_energy(modules, report)


def _check_v9_group_sizes(report: object, group_counts: Mapping[str, int]) -> None:
    """V9 组规模（红拦）：每季 ≤5；通用组 ≥1（普攻兜底必在）。"""
    for season in SEASONS:
        n = group_counts.get(season, 0)
        if n == 0:
            _err(report, "skills", "V9", rule="season_group_empty", season=season,
                 count=0, msg=f"季节组 {season} 为空（V9：每季技能组非空）")
        elif n > SEASON_GROUP_MAX:
            _err(report, "skills", "V9", rule="season_group_over_cap", season=season,
                 count=n, max=SEASON_GROUP_MAX,
                 msg=f"季节组 {season} 技能 {n} 超上限 {SEASON_GROUP_MAX}（V9）")
    general = group_counts.get("general", 0)
    if general < 1:
        _err(report, "skills", "V9", rule="general_group_empty", count=general,
             msg="通用组为空（V9：通用组 ≥1，普攻兜底必在）")


__all__ = [
    "MODULE_NAME",
    "MODULE_NAME_SKILLS",
    "DEFAULT_ELEMENTS",
    "COMBO_KINDS",
    "COMBO_POWER_MAX",
    "SEASONS",
    "SEASON_GROUP_MAX",
    "TRANSLATED_SEASONS",
    "SEASON_COND_PREFIX",
    "SEASON_ELEMENT_KEYS",
    "SEASON_EVENTS_MIRROR",
    "PROC_TRIGGER_EVENTS",
    "validate_resource_axes",
    "validate_skill_energy",
    "validate_season_groups",
]
