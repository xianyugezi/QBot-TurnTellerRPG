"""M13 技能库专项校验器（细化_6a §3：V-1~V-6 技能侧落点，批2 路2A）。

文件名：skill_validator.py
创建时间：2026-09-02
作者：Hermes 子agent-2A（M13 技能库实现组批2路2A：6a 技能库校验 V-1~V-6）

功能描述：
  - validate_skills(modules, report) 纯函数专项校验器（对齐 M4/M8/M9/M11 同族
    validate_xxx(modules, report) 鸭子类型口径，report 三形态收集器兼容）：
    V-1 效果引用存在（effects[].effect ∈ effects 表 / x_ 前缀例外放行 / type 原子
        动作放行，契约 [L201] 判定细节 §3.1）；
    V-2 派生链引用存在（chain_refs ∈ skill_chains 表，契约 [L202] 红拦部分；
        死链可达性黄提示由 1c2 校验器承接，本文件不重复）；
    V-3 印记引用存在 + 消耗值域（consume_marks 键 ∈ marks 表；值 ≥1 且 ≤ 印记
        上限字段，契约 [L203]）；
    V-4 元素 ∈ 8 元素注册表（契约 [L204] / [数 L220-221]）；
    V-5 职业引用存在（job_restrict ∈ jobs 表，契约 [L205]；jobs 模块批4 才落，
        缺表时宽松放行——工程补白 P-1）；
    V-6 派生倍率累计提示（沿 chain_refs 可达链累计 power，>1.5× 黄提示不拦截，
        契约 [L206] / TC-11）。
  - 红黄分级：红拦 = V-1/2/3/4/5；黄提示 = V-6（三铁律③：不做数值预警，
    power 999 是作者自由，V-6 仅「注意数值膨胀」提示）。
  - 引用查表仿 validator._check_action_ref 先例（表未声明 → 按引用不存在红拦）；
    仅 V-5 jobs 特例宽松（批4 落表，P-1）。

依据：
  - docs/细化/细化_6a_技能库契约.md（349 行 v1.0）：
    §3.1 定稿校验 10 条全量（V-1..V-6 逐条级别/判定细节）；§1.3-f2 effects
    条目双形态（引用 {effect,overrides} / 原子动作 {type,...}，x_ 前缀例外
    [L131]）；§1.2-A F04（power 默认 100）/F06（8 元素注册表）/F14（chain_refs）/
    F15（consume_marks）/F16（job_restrict）；⑥ TC-11（V-6 1.8× 黄提示）、
    TC-14/15/16/17（V-1/2/3/5 红拦）。
  - docs/m13_6a摸底.md：A2（效果引用 + L0 词汇执行器）、A8（8 元素注册表）、
    G3（V-1~V-13 无技能专项落点 → 本文件收口 V-1~V-6）、§8-5（element 引用
    检查缺技能路）。
  - 模式参考：qbot_rpg/content/skill_action_models.py（validate_actions 专项
    校验器，_emit/_err/_warn 三形态收集器兼容，字段枚举镜像常量 G0 口径）；
    qbot_rpg/content/validator.py（_Checker._err/_warn 收口 + _check_action_ref
    引用缺失先例）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  V-5 jobs 表宽松放行：jobs 模块批4 才落（field_meta 现无 jobs 登记），
       本文件在 modules 缺 "jobs" 时跳过 V-5 引用检查（零红零黄），jobs 表
       存在时按契约红拦——契约 §4.3-1 引用存在性判定在 jobs 落地后自动生效。
  P-2  V-3 印记上限字段名取 marks 条目 "max"（契约 F15 约束「≤ 印记上限」未给
       字段名）：条目含数值 "max" 时校验 count ≤ max；无 max 字段时只查存在性
       与 count ≥1（上限语义由 1d 承接，防御读取不臆造字段）。
  P-3  V-6 倍率口径：power/100 为倍率（power 100 = 1.0×）；累计 = 自身 power
       × 各可达链条目 power（链条目 power 缺省 1.0×）；链条目递归 chain_refs
       时防环（visited 集合）；累计 > 1.5× 黄提示（TC-11 1.8× 口径）。
  P-4  V-1 effects 结构防御：effects 非 list / 条目非 Mapping / 条目无
       effect/type 键 → 跳过（结构形态校验归 V-11 与泛型字段校验，本文件只查
       引用存在性）。

铁律：零 NoneBot import；完整类型标注（typing 3.9 兼容）；纯函数；确定性；
零定时器/零睡眠（本文件不含任何 sleep/定时器字面量）；不引入随机；不 git
commit。仅依赖 qbot_rpg.content.skill_models（SKILL_ELEMENTS 常量，G0 单向
依赖：content 层不 import core）与标准库。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Set, Tuple

from qbot_rpg.content.skill_models import SKILL_ELEMENTS

# =====================================================================================
# 常量（契约 §3.1 / §1.2）
# =====================================================================================

# F06 8 元素注册表（契约 [数 L220-221]；与 skill_models.SKILL_ELEMENTS 同源单点，
# validator._DEFAULT_ELEMENTS 镜像——G0 单向依赖：content 层不 import core）
ELEMENT_VALUES: Tuple[str, ...] = SKILL_ELEMENTS

# F04 power 缺省（契约 §1.2-A：默认 100 = 1.0× 倍率）
DEFAULT_POWER: float = 100.0

# V-6 派生倍率累计阈值（契约 [L206]：默认 ≤1.5×；超配仅在编辑器提示，不拦截）
V6_RATIO_LIMIT: float = 1.5

# F07 effects 条目双形态键（契约 §1.3-f2）
EFFECT_REF_KEY: str = "effect"
EFFECT_ATOMIC_KEY: str = "type"

# x_ 前缀自定义效果例外（契约 [L131]：x_ 前缀例外，编辑器隐藏，V-1 放行）
X_PREFIX: str = "x_"


# =====================================================================================
# 收集器发射（三形态兼容：_Checker._err/_warn → dict {"errors","warnings"} → list）
# =====================================================================================


def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    """向收集器发一条校验记录（error/warning 两态，三形态收集器兼容）。

    优先级：_Checker._err/_warn（module 首参）→ dict/list 形态（rec 直接
    append）→ 鸭子类型 error/warning（带 module 首参）兜底。module 恒为
    "skills"（与 validate_actions 的 "action" 同口径）。
    """
    if hasattr(report, "_err") and level == "error":
        report._err("skills", field, kind, **detail)
        return
    if hasattr(report, "_warn") and level == "warning":
        report._warn("skills", field, kind, **detail)
        return
    if isinstance(report, dict):
        rec = {"field": field, "kind": kind, "level": level, **detail}
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])
        bucket.append(rec)
        return
    if isinstance(report, list):
        rec = {"field": field, "kind": kind, "level": level, **detail}
        report.append(rec)
        return
    if hasattr(report, "error") and level == "error":
        report.error("skills", field, kind, **detail)
        return
    if hasattr(report, "warning") and level == "warning":
        report.warning("skills", field, kind, **detail)
        return
    rec = {"field": field, "kind": kind, "level": level, **detail}
    if isinstance(report, Mapping) and hasattr(report, "setdefault"):
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])
        bucket.append(rec)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", field, kind, **detail)


# =====================================================================================
# 引用表收集
# =====================================================================================


def _id_set(data: object) -> Set[str]:
    """list 形态模块的 id 集合（effects/skill_chains/marks/jobs 引用查表）。

    表缺失/非 list → 空集（引用查表先例：validator._check_action_ref「表未
    声明 → 按引用不存在红拦」）；条目非 Mapping / id 非非空字符串 → 跳过。
    """
    if not isinstance(data, list):
        return set()
    out: Set[str] = set()
    for e in data:
        if isinstance(e, Mapping):
            v = e.get("id")
            if isinstance(v, str) and v:
                out.add(v)
    return out


def _entry_id(entry: Mapping[str, object]) -> str:
    """条目 id 详情串（用于报告定位；非字符串/缺失 → 索引占位）。"""
    v = entry.get("id")
    return v if isinstance(v, str) and v else "?"


def _str_list(entry: Mapping[str, object], key: str) -> Tuple[str, ...]:
    """防御性字符串列表读取（chain_refs/job_restrict；非 list → 空）。"""
    v = entry.get(key)
    return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()


def _mark_max(marks_data: object, mark_id: str) -> Optional[float]:
    """印记上限字段（P-2：marks 条目数值 "max"；无 → None 不校验上限）。"""
    if not isinstance(marks_data, list):
        return None
    for e in marks_data:
        if isinstance(e, Mapping) and e.get("id") == mark_id:
            m = e.get("max")
            if isinstance(m, (int, float)) and not isinstance(m, bool):
                return float(m)
            return None
    return None


# =====================================================================================
# V-6 派生倍率累计（契约 [L206] / TC-11：沿 chain_refs 可达链累计 power）
# =====================================================================================


def _power_mult(entry: Mapping[str, object]) -> float:
    """条目倍率（power/100；缺省 100 = 1.0×；非法值兜底 1.0×，P-3）。"""
    p = entry.get("power")
    if isinstance(p, (int, float)) and not isinstance(p, bool) and p > 0:
        return float(p) / 100.0
    return DEFAULT_POWER / 100.0


def _chain_mult(
    chain_id: str,
    chains_by_id: Mapping[str, Mapping[str, object]],
    visited: Set[str],
) -> float:
    """单条链的倍率累计（链条目 power × 递归其 chain_refs；visited 防环，P-3）。"""
    if chain_id in visited:
        return 1.0
    visited.add(chain_id)
    ch = chains_by_id.get(chain_id)
    if ch is None:
        return 1.0
    mult = _power_mult(ch)
    refs = ch.get("chain_refs")
    if isinstance(refs, list):
        for r in refs:
            if isinstance(r, str):
                mult *= _chain_mult(r, chains_by_id, visited)
    return mult


def _cumulative_mult(
    entry: Mapping[str, object],
    chains_by_id: Mapping[str, Mapping[str, object]],
) -> float:
    """技能派生倍率累计 = 自身 power × 各可达链累计（P-3；防环）。"""
    cum = _power_mult(entry)
    for ref in _str_list(entry, "chain_refs"):
        cum *= _chain_mult(ref, chains_by_id, set())
    return cum


# =====================================================================================
# 单条目校验（V-1 ~ V-6）
# =====================================================================================


def _check_v1_effect_refs(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    effects_ids: Set[str],
) -> None:
    """V-1 效果引用存在（红拦，契约 [L201] + §1.3-f2 双形态判定）。

    effects[].effect ∈ effects 表 id（x_ 前缀例外放行 [L131]）；
    effects[].type 原子动作（L0 词汇表成员，归口 1b）放行；
    effects 表缺失 → 引用不存在红拦（_check_action_ref 先例）。
    """
    effects = entry.get("effects")
    if not isinstance(effects, list):
        return  # P-4：结构形态校验归 V-11/泛型，本文件只查引用
    for i, eff in enumerate(effects):
        if not isinstance(eff, Mapping):
            continue  # P-4
        ref = eff.get(EFFECT_REF_KEY)
        if isinstance(ref, str) and ref:
            if ref.startswith(X_PREFIX):
                continue  # x_ 前缀自定义效果例外（契约 [L131]）
            if ref not in effects_ids:
                _err(report, f"{base}.effects[{i}]", "V-1", rule="V1_effect_ref",
                     node_id=sid, effect_ref=ref, ref_target="effect",
                     msg="效果引用 %r 不存在（V-1：effects[].effect ∈ effects 表）" % (ref,))


def _check_v2_chain_refs(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    chains_ids: Set[str],
) -> None:
    """V-2 派生链引用存在（红拦，契约 [L202]）。

    chain_refs 每个值 ∈ skill_chains 表 id；表缺失 → 引用不存在红拦；
    死链可达性黄提示由 1c2 校验器承接（本文件不重复，V-2 红拦部分收口）。
    """
    for ref in _str_list(entry, "chain_refs"):
        if ref not in chains_ids:
            _err(report, f"{base}.chain_refs", "V-2", rule="V2_chain_ref",
                 node_id=sid, chain_ref=ref, ref_target="skill_chain",
                 msg="派生链引用 %r 不存在（V-2：chain_refs ∈ skill_chains 表）" % (ref,))


def _check_v3_marks(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    marks_ids: Set[str],
    marks_data: object,
) -> None:
    """V-3 印记引用存在 + 消耗值域（红拦，契约 [L203]）。

    consume_marks 键 ∈ marks 表 id；值 ≥1 整数；≤ 印记上限字段（P-2：marks
    条目数值 "max"，无则不查上限）；表缺失 → 引用不存在红拦。
    """
    cm = entry.get("consume_marks")
    if cm is None:
        return
    if not isinstance(cm, Mapping):
        _err(report, f"{base}.consume_marks", "V-3", rule="V3_mark_struct",
             node_id=sid, got=type(cm).__name__,
             msg="consume_marks 需对象 {mark_id: count}（V-3）")
        return
    for mark_id, count in cm.items():
        if not isinstance(mark_id, str) or not mark_id:
            continue  # 非字符串键防御跳过（SkillDef 同口径）
        if mark_id not in marks_ids:
            _err(report, f"{base}.consume_marks.{mark_id}", "V-3", rule="V3_mark_ref",
                 node_id=sid, mark_ref=mark_id, ref_target="mark",
                 msg="印记引用 %r 不存在（V-3：consume_marks 键 ∈ marks 表）" % (mark_id,))
            continue
        valid_count = isinstance(count, int) and not isinstance(count, bool) and count >= 1
        if not valid_count:
            _err(report, f"{base}.consume_marks.{mark_id}", "V-3", rule="V3_mark_count",
                 node_id=sid, mark_ref=mark_id, count=count,
                 msg="印记消耗 %r 需正整数 ≥1（V-3）" % (count,))
            continue
        cap = _mark_max(marks_data, mark_id)
        if cap is not None and count > cap:
            _err(report, f"{base}.consume_marks.{mark_id}", "V-3", rule="V3_mark_count",
                 node_id=sid, mark_ref=mark_id, count=count, mark_max=cap,
                 msg="印记消耗 %d 超过上限 %g（V-3：≤ 印记上限字段）" % (count, cap))


def _check_v4_element(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
) -> None:
    """V-4 元素 ∈ 8 元素注册表（红拦，契约 [L204] / [数 L220-221]）。

    element null/缺省放行（F06 默认 null=按武器元素，§1.3-f5）；
    非字符串 / 注册表外 → 红拦。
    """
    element = entry.get("element")
    if element is None:
        return
    if not isinstance(element, str):
        _err(report, f"{base}.element", "V-4", rule="V4_element",
             node_id=sid, element=element, allowed=list(ELEMENT_VALUES),
             msg="element 需字符串或 null（V-4）")
        return
    if element not in ELEMENT_VALUES:
        _err(report, f"{base}.element", "V-4", rule="V4_element",
             node_id=sid, element=element, allowed=list(ELEMENT_VALUES),
             msg="element %r 不在 8 元素注册表（V-4）" % (element,))


def _check_v5_job_restrict(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    jobs_data: object,
) -> None:
    """V-5 职业引用存在（红拦，契约 [L205] / §4.3-1）。

    job_restrict 每个值 ∈ jobs 表 id（任一缺失即红拦，TC-17）；
    jobs 模块缺失 → 宽松放行（P-1：jobs 表批4 才落，field_meta 现无 jobs
    登记；jobs 落地后本判定自动生效）。
    """
    if jobs_data is None:
        return  # P-1：jobs 表批4 才落，缺表宽松放行
    jobs_ids = _id_set(jobs_data)
    for ref in _str_list(entry, "job_restrict"):
        if ref not in jobs_ids:
            _err(report, f"{base}.job_restrict", "V-5", rule="V5_job_ref",
                 node_id=sid, job_ref=ref, ref_target="job",
                 msg="职业引用 %r 不存在（V-5：job_restrict ∈ jobs 表）" % (ref,))


def _check_v6_ratio(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    chains_by_id: Mapping[str, Mapping[str, object]],
) -> None:
    """V-6 派生倍率累计提示（黄提示不拦截，契约 [L206] / TC-11）。

    累计 = 自身 power × 各可达链累计（P-3）；> 1.5× 黄提示「注意数值膨胀」；
    三铁律③：不拦数值，power 999 是作者自由。
    """
    cum = _cumulative_mult(entry, chains_by_id)
    if cum > V6_RATIO_LIMIT:
        _warn(report, f"{base}.power", "V-6", rule="V6_ratio_high",
              node_id=sid, cumulative=cum, limit=V6_RATIO_LIMIT,
              msg=(
                  "派生倍率累计 %.2f× 超过默认上限 %.1f× → 注意数值膨胀"
                  "（V-6 黄提示不拦截）" % (cum, V6_RATIO_LIMIT)
              ))


# =====================================================================================
# V-7 ~ V-13 条目级/库级校验（批2 路2B；V-7 为库级单独跑）
# =====================================================================================


def _check_v8_cooldown(
    report: object, base: str, sid: str, entry: Mapping[str, object]
) -> None:
    """V-8 冷却非负（红拦）：cooldown 缺省 0；负值红拦。"""
    cd = entry.get("cooldown")
    if isinstance(cd, (int, float)) and not isinstance(cd, bool) and cd < 0:
        _err(report, f"{base}.cooldown", "R-2", rule="cooldown_negative",
             node_id=sid, cooldown=cd, msg="技能 cooldown 不能为负数（V-8）")


def _check_v9_mp_cost(
    report: object, base: str, sid: str, entry: Mapping[str, object]
) -> None:
    """V-9 MP 非负（红拦）：mp_cost 缺省 0；负值红拦。"""
    mp = entry.get("mp_cost")
    if isinstance(mp, (int, float)) and not isinstance(mp, bool) and mp < 0:
        _err(report, f"{base}.mp_cost", "R-2", rule="mp_cost_negative",
             node_id=sid, mp_cost=mp, msg="技能 mp_cost 不能为负数（V-9）")


def _check_v10_duplicate_id(
    report: object, base: str, sid: str, entry: Mapping[str, object],
    ctx: Mapping[str, object],
) -> None:
    """V-10 库内唯一（红拦）：skills 条目 id 全局唯一。

    由 validate_skills 库级统计所有 id；每条重复 id 红拦一次（首现不拦）。
    """
    seen = ctx.get("_seen_ids")
    if isinstance(seen, set) and sid:
        if sid in seen:
            _err(report, f"{base}.id", "R-5", rule="skill_id_duplicate",
                 node_id=sid, msg="技能 id 必须全局唯一（V-10）")
        else:
            seen.add(sid)


def _check_v11_field_registry(
    report: object, base: str, sid: str, entry: Mapping[str, object]
) -> None:
    """V-11 字段登记（红拦）：skills 条目字段 ∈ skills_fields 24 键 + 兼容键。

    仅 skills 库收紧（摸底 §8-2 裁决）；action 库保持既有放行。
    """
    from qbot_rpg.content.skill_models import skills_fields

    known = set(skills_fields().keys())
    # 兼容键：id 索引、旧键（skill_actions 共用 ActionCore 但条目形态同）
    for k in entry:
        if k not in known:
            _err(report, f"{base}.{k}", "R-5", rule="skill_field_unregistered",
                 node_id=sid, field_name=k,
                 msg=f"技能字段 {k} 未登记（V-11：须在 skills_fields 24 键内）")


def _check_v12_kind_inference(
    report: object, base: str, sid: str, entry: Mapping[str, object]
) -> None:
    """V-12 kind 推断（黄提示，不拦截）：kind 缺省/非法 → 按 effects 内容推断。

    推断成功仅登记提示；推断不出 → 黄提示 kind_not_inferred。
    """

    kind = entry.get("kind")
    if kind is not None:
        return  # 显式 kind（合法与否归 V-13 枚举）
    # 按 effects 推断：damage 类→damage；heal→heal；status/control 类→status
    inferred = None
    effects = entry.get("effects")
    if isinstance(effects, list):
        for e in effects:
            if not isinstance(e, Mapping):
                continue
            etype = e.get("type") or e.get("effect")
            if isinstance(etype, str):
                if etype in ("damage", "aoe"):
                    inferred = "damage"
                    break
                if etype == "heal":
                    inferred = "heal"
                    break
                if etype in ("status", "control", "dispel", "shield",
                             "stat_modifier", "mark_add", "mark_remove"):
                    inferred = "status"
                    break
    if inferred is None:
        _warn(report, f"{base}.kind", "V-12", rule="kind_not_inferred",
              node_id=sid, msg="kind 未能推断（effects 无 damage/heal/status 类行为）")
    else:
        _warn(report, f"{base}.kind", "V-12", rule="kind_inferred",
              node_id=sid, value=inferred, msg=f"kind 缺省，按 effects 推断为 {inferred}")


def _check_v13_basic_gate(
    report: object, base: str, sid: str, entry: Mapping[str, object]
) -> None:
    """V-13 基础门禁（红拦）：type/kind/attack_type/tag/block_mode 枚举 + 数值域。

    attack_type 中文旧值读兼容（对齐行动库 P-4）。
    """
    from qbot_rpg.content.skill_models import (
        ATTACK_TYPES, BLOCK_MODES, SKILL_KINDS, SKILL_TAGS, SKILL_TYPES,
    )

    t = entry.get("type")
    if t is not None and t not in SKILL_TYPES:
        _err(report, f"{base}.type", "R-5", rule="skill_type_enum_invalid",
             node_id=sid, value=t, allowed=list(SKILL_TYPES),
             msg=f"技能 type {t} 不在四枚举（basic/active/passive/trigger）（V-13）")
    k = entry.get("kind")
    if k is not None and k not in SKILL_KINDS:
        _err(report, f"{base}.kind", "R-5", rule="skill_kind_enum_invalid",
             node_id=sid, value=k, allowed=list(SKILL_KINDS),
             msg=f"技能 kind {k} 不在五枚举（damage/heal/status/control/utility）（V-13）")
    at = entry.get("attack_type")
    if at is not None and at not in ATTACK_TYPES and at not in ("斩", "打", "突", "魔"):
        _err(report, f"{base}.attack_type", "R-5", rule="skill_attack_type_invalid",
             node_id=sid, value=at, allowed=list(ATTACK_TYPES),
             msg=f"技能 attack_type {at} 不在五枚举（V-13）")
    tg = entry.get("tag")
    if tg is not None and tg not in SKILL_TAGS:
        _err(report, f"{base}.tag", "R-5", rule="skill_tag_invalid",
             node_id=sid, value=tg, allowed=list(SKILL_TAGS),
             msg=f"技能 tag {tg} 不在六枚举（V-13）")
    bm = entry.get("block_mode")
    if bm is not None and bm not in BLOCK_MODES:
        _err(report, f"{base}.block_mode", "R-5", rule="skill_block_mode_invalid",
             node_id=sid, value=bm, allowed=list(BLOCK_MODES),
             msg=f"技能 block_mode {bm} 不在三枚举（V-13）")
    # 数值域
    for key, lo, hi in (("power", 0, 500), ("hits", 1, None), ("hit_mod", 0, None),
                        ("crit_mod", 0, None)):
        v = entry.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v < lo:
                _err(report, f"{base}.{key}", "R-2", rule=f"{key}_out_of_range",
                     node_id=sid, value=v, msg=f"技能 {key} 不能小于 {lo}（V-13）")
            if hi is not None and v > hi:
                _err(report, f"{base}.{key}", "R-2", rule=f"{key}_out_of_range",
                     node_id=sid, value=v, msg=f"技能 {key} 不能大于 {hi}（V-13）")


def _check_v7_basic_per_job(
    report: object, skills: List[Mapping[str, object]], jobs_data: object
) -> None:
    """V-7 普攻每职业恰 1（库级红拦，契约 §4.3-2）。

    计数口径：无 job_restrict（缺失/空/非列表）的 basic 计入所有职业；
    带 job_restrict 的 basic 只计入所列职业；对每个职业：可见 basic 恰 1 个，
    否则红拦。技能列表无 basic → 红拦「技能库无普攻」。
    """
    basic_indices = [
        i for i, e in enumerate(skills)
        if isinstance(e.get("type"), str) and e.get("type") == "basic"
    ]
    if not basic_indices:
        _err(report, "skills", "V-7", rule="no_basic_attack",
             node_id=None, msg="技能库无普攻（V-7：basic 每职业恰 1）")
        return
    # 职业集合：jobs 表 id ∪ 全局组
    job_ids: Set[str] = set()
    if isinstance(jobs_data, list):
        for j in jobs_data:
            if isinstance(j, Mapping) and isinstance(j.get("id"), str):
                job_ids.add(j["id"])
    # 全局 basic（无 job_restrict；排除形态专属 job_form——形态普攻不占常态位）
    global_basics = [
        e for i, e in enumerate(skills)
        if e.get("type") == "basic" and not e.get("job_restrict")
        and not e.get("job_form")
    ]
    if len(global_basics) > 1:
        _err(report, "skills", "V-7", rule="global_basic_multiple",
             node_id=None, count=len(global_basics),
             msg="无职业限制的 basic 普攻多于 1 条（V-7）")
    # 每职业可见 basic 计数（排除形态专属 basic——job_form 限定技能随形态切换）
    per_job: Dict[str, int] = {}
    for e in skills:
        if e.get("type") != "basic":
            continue
        if e.get("job_form"):
            continue  # 形态专属普攻不占常态职业普攻位（细化_6b 技能挂点语义）
        jr = e.get("job_restrict")
        if isinstance(jr, list) and jr:
            for jid in jr:
                if isinstance(jid, str):
                    per_job[jid] = per_job.get(jid, 0) + 1
        else:
            for jid in job_ids:
                per_job[jid] = per_job.get(jid, 0) + 1
    for jid in sorted(job_ids):
        if per_job.get(jid, 0) == 0:
            _err(report, "skills", "V-7", rule="job_zero_basic",
                 node_id=None, job_id=jid,
                 msg=f"职业 {jid} 可见 basic 0 个（V-7：每职业恰 1）")
        elif per_job.get(jid, 0) > 1:
            _err(report, "skills", "V-7", rule="job_multiple_basic",
                 node_id=None, job_id=jid, count=per_job[jid],
                 msg=f"职业 {jid} 可见 basic {per_job[jid]} 个（V-7：每职业恰 1）")


def _check_skill_entry(
    report: object,
    entry: object,
    idx: int,
    ctx: Mapping[str, object],
) -> None:
    """单条技能条目校验（V-1 ~ V-6 + V-8 ~ V-13 全量；V-7 为库级单独跑）。"""
    base = f"[{idx}]"
    if not isinstance(entry, Mapping):
        _err(report, base, "R-5", rule="skill_not_object",
             node_id=str(idx), got=type(entry).__name__,
             msg="skills.json 每条技能需对象")
        return
    sid = _entry_id(entry)
    effects_ids = ctx.get("effects_ids")
    chains_ids = ctx.get("chains_ids")
    marks_ids = ctx.get("marks_ids")
    marks_data = ctx.get("marks_data")
    jobs_data = ctx.get("jobs_data")
    chains_by_id = ctx.get("chains_by_id")
    if not isinstance(effects_ids, set) or not isinstance(chains_ids, set) \
            or not isinstance(marks_ids, set):
        return  # 引用表类型异常（防御；validate_skills 构造的 ctx 恒为 set）
    _check_v1_effect_refs(report, base, sid, entry, effects_ids)
    _check_v2_chain_refs(report, base, sid, entry, chains_ids)
    _check_v3_marks(report, base, sid, entry, marks_ids, marks_data)
    _check_v4_element(report, base, sid, entry)
    _check_v5_job_restrict(report, base, sid, entry, jobs_data)
    _check_v6_ratio(
        report, base, sid, entry,
        chains_by_id if isinstance(chains_by_id, Mapping) else {},
    )
    # V-8~V-13 条目级
    _check_v8_cooldown(report, base, sid, entry)
    _check_v9_mp_cost(report, base, sid, entry)
    _check_v10_duplicate_id(report, base, sid, entry, ctx)
    _check_v11_field_registry(report, base, sid, entry)
    _check_v12_kind_inference(report, base, sid, entry)
    _check_v13_basic_gate(report, base, sid, entry)


# =====================================================================================
# 主入口
# =====================================================================================


def validate_skills(modules: Mapping[str, object], report: object) -> None:
    """技能库专项校验主入口（细化_6a §3：V-1~V-6；loader/validator 专项路由调用）。

    入参:
      modules: 全量内容模块（skills 键为技能条目数组；缺失 → 跳过，对齐既有
               校验器「模块未接线默认放行」惯例；effects/skill_chains/marks/
               jobs 为引用靶模块）。
      report:  收集器（_err/_warn 三形态兼容：_Checker / dict {"errors":[]} /
               list）。
    出参: 无（红拦/黄提示全部经 report 收集，红拦由 loader 聚合拒绝加载）。
    """
    data = modules.get("skills")
    if data is None:
        return
    if not isinstance(data, list):
        _err(report, "skills", "R-5", rule="skill_not_list",
             node_id=None, got=type(data).__name__,
             msg="skills.json 需顶层数组（每条技能一个对象，契约 §1.1）")
        return

    # 引用靶表（effects/skill_chains/marks 缺失 → 空集 → 引用红拦；jobs 特例 P-1）
    effects_data = modules.get("effects")
    chains_data = modules.get("skill_chains")
    marks_data = modules.get("marks")
    jobs_data = modules.get("jobs")
    effects_ids = _id_set(effects_data)
    chains_ids = _id_set(chains_data)
    marks_ids = _id_set(marks_data)

    # V-6 链索引（id → 条目；仅 Mapping 条目入表）
    chains_by_id: Dict[str, Mapping[str, object]] = {}
    if isinstance(chains_data, list):
        for e in chains_data:
            if isinstance(e, Mapping):
                cid = e.get("id")
                if isinstance(cid, str) and cid:
                    chains_by_id[cid] = e

    ctx: Mapping[str, object] = {
        "effects_ids": effects_ids,
        "chains_ids": chains_ids,
        "marks_ids": marks_ids,
        "marks_data": marks_data,
        "jobs_data": jobs_data,
        "chains_by_id": chains_by_id,
        "_seen_ids": set(),
    }
    for i, entry in enumerate(data):
        _check_skill_entry(report, entry, i, ctx)
    # V-7 库级（普攻每职业恰 1；放末尾跑，条目级错误优先收集）
    _check_v7_basic_per_job(report, [e for e in data if isinstance(e, Mapping)], jobs_data)


__all__ = [
    "ELEMENT_VALUES",
    "DEFAULT_POWER",
    "V6_RATIO_LIMIT",
    "EFFECT_REF_KEY",
    "EFFECT_ATOMIC_KEY",
    "X_PREFIX",
    "validate_skills",
]
