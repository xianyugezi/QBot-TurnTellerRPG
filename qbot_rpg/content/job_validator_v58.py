"""M13 职业库专项校验器 V5~V8（细化_6b §五 后半段，批5 路5B）。

文件名：job_validator_v58.py
创建时间：2026-09-02
作者：Hermes 子agent-5B（M13 职业库实现组批5路5B：6b 职业库校验 V5~V8；
      3 路并行——路5A 写 V1~V4（独立文件 job_validator.py），路5C 写装配，
      主 agent 收口时并入 job_validator.py 合并两文件）

功能描述：
  - validate_jobs_v58(modules, report) 纯函数专项校验器（对齐 M4/M8/M9/M11
    同族 validate_xxx(modules, report) 鸭子类型口径，report 三形态收集器
    兼容；module 恒为 "jobs"，与 validate_skills 的 "skills" 同口径）。
  - 本路校验编号（任务口径）与细化_6b 契约编号的对应（主 agent 收口合并
    时按此表注释对齐）：
      V5 技能挂点引用（红拦）= 契约 V2（transform_skill 存在，[L331]）+
          契约 V8（skill_set 引用存在，[L336]）+ 契约 V1（transform_to
          引用存在——JOB_FORM 值域侧：形态须被 ≥1 技能 job_form 引用，
          [L329]）+ 细化_6a §4.3-1（job_form ∈ transform 形态名 [L217]）；
      V6 派生链作用域（红拦）= 契约 V8 后半段（derive_chains 引用存在 +
          链 job_scope=transform_to，[L336] + §1.6 #39 + §2.3 ③）；
      V7 死配置（红拦）= 契约 V6（revert_form 归属，[L334]）+ 死配置
          （job_form / job_scope / revert_form 引用不存在的形态/技能，
          derive_only 技能 effects 引用不存在；仿 validator._check_dead_config
          模式 [L1580-1604]）；
      V8 battle+revert 红拦（红拦）= 契约 V4（duration=battle 且
          revert=true 矛盾，[L332] + ADR D-04 [L58]）。
  - 契约 V5（state_policy 三键枚举，[L333]）与契约 V7（dispel_reverts bool
    + 联动）由泛型登记表（field_meta.jobs_fields transform children 已登记
    duration/state_policy 枚举与 bool，枚举外值 → 泛型 R-1 红拦）与路5A
    承接，本文件不重复（P-7）。
  - 红黄分级：V5~V8 全红拦（任务强制：本路全部校验红拦，无黄提示）。

依据：
  - docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
    §1.3 transform 段 11 字段（#21~#31）；§1.5 技能侧挂点 4 字段
    （#35~#38：job_form/job_restrict/revert_form/derive_only）；§1.6 链侧
    挂点 1 字段（#39 job_scope）；§五 校验器 V1~V8 全表（[L329-336]）；
    §2.3 三字段语义（revert_form [L208] / job_scope [L210]）；ADR D-04
    （battle+revert 矛盾裁定红拦 [L58]）。
  - docs/细化/细化_6a_技能库契约.md（349 行 v1.0）：§4.3-1 引用存在性
    （job_form ∈ 对应职业 transform 形态名，缺失即红拦 [L217]）；[L131]
    x_ 前缀自定义效果例外。
  - docs/m13_6b摸底.md：V1~V8 全缺（§五）；可复用模式：V4 battle+revert
    矛盾仿 _check_dead_config L1570 红拦（§七）。
  - 模式参考：qbot_rpg/content/skill_validator.py（validate_skills，
    _err/_warn 三形态收集器；V-5 job_restrict 缺表宽松放行 P-1）；
    qbot_rpg/content/forge_models.py（_emit 三形态收集器）；
    qbot_rpg/content/validator.py（_check_dead_config 死配置红拦）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  挂点字段缺登记宽松放行：revert_form/derive_only（技能侧）与
       job_scope（链侧）登记位在 6a 全量字段收口（细化_6b 附·未定稿依赖
       1/3；field_meta.skill_chains_fields L484-491 无 job_scope 键），本
       文件按「字段存在即校验、缺失则该技能/链无挂点可查」放行，零红零黄；
       6a 登记后判定自动生效（与 skill_validator V-5 jobs 缺表宽松放行
       P-1 同构）。
  P-2  引用靶模块缺失宽松放行：skills / skill_chains / effects 表缺失
       （None 或非 list）时跳过对应引用红拦（缺表先例 V-5/P-1：表未落地
       前不误拦）；表存在（含空表）时按契约红拦——引用存在性判定在表落地
       后自动生效。
  P-3  派生链作用域放行口径：skill_chains 表存在但链条目缺失 job_scope 键
       → 该链「无形态作用域限制」放行（等价于通用链；契约 §1.6 #39 为选填）；
       链条目 job_scope 存在但不一致 → V6 红拦（§1.3 #31「链 job_scope=
       该形态」+ §2.3 ③ V8 口径）；transform_to 缺失时跳过作用域一致性
       判定（必填缺失已由泛型 R-5 required_missing 红拦，本文件不重复）。
  P-4  挂点归属校验口径：revert_form=true 的技能须 job_form ∈ 全库形态值域
       （all_forms = 各职业 transform.transform_to 集合；契约 V6 [L334]
       「该技能存在且 job_form=本职业 transform_to 形态」——job_form 唯一
       钉定形态，跨职业形态值域判定等价于「归属形态组」；skill_set 组内
       结构未登记（P-1）不展开）。job_form 缺失/非字符串的 revert_form
       技能 → V7 红拦。
  P-5  V7 死配置中的「效果引用」仅查 derive_only 技能的 effects 引用存在性
       （x_ 前缀例外放行，对齐 V-1 [L131]）；effects 表缺失 → 宽松放行
       （P-2 同口径）；effect 字段与 type 原子动作双形态判定对齐 V-1。
  P-6  V8 矛盾判定以字面 bool True 为准（revert 非 bool/非 True 不拦，
       duration 非 "battle" 不拦）；transform 段缺失/非对象 → 跳过全段。
  P-7  本文件不重复 V1~V4（归路5A job_validator.py 与泛型登记表）：
       transform_to 自指/互指环、dispel_reverts 联动、state_policy 三键
       枚举、duration 枚举外值——分别归路5A / 泛型 R-1（field_meta
       jobs_fields transform children 已登记）；本文件只收 V5~V8 后半段
       （挂点引用/派生链作用域/死配置/battle+revert）。

铁律：零 NoneBot import（平台无关）；G0：content 层零 engine/core import
（本文件仅依赖标准库，无任何 content 兄弟模块 import）；完整类型标注
（typing 3.9 兼容）；纯函数；确定性；零定时器/零睡眠（本文件不含任何
sleep/定时器字面量）；不引入随机；不 git commit。
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Set, Tuple

# =====================================================================================
# 常量（细化_6b §1.3/§1.5/§1.6 字段键 + 枚举）
# =====================================================================================

# transform 段字段键（§1.3 #21~#31）
KEY_TRANSFORM_SKILL: str = "transform_skill"
KEY_TRANSFORM_TO: str = "transform_to"
KEY_DURATION: str = "duration"
KEY_REVERT: str = "revert"
KEY_SKILL_SET: str = "skill_set"
KEY_DERIVE_CHAINS: str = "derive_chains"

# 技能侧挂点字段键（§1.5 #35~#38；job_form 已由 6a 登记于
# skill_models.skills_fields / field_meta.skills_fields，revert_form/
# derive_only 登记位在 6a 全量收口，P-1）
KEY_JOB_FORM: str = "job_form"
KEY_REVERT_FORM: str = "revert_form"
KEY_DERIVE_ONLY: str = "derive_only"

# 链侧挂点字段键（§1.6 #39 job_scope；登记位在 6a 收口，P-1）
KEY_JOB_SCOPE: str = "job_scope"

# #23 duration 两枚举（§1.3 #23：turns=回合制持续（配 turns）/ battle=整场不还原）
# V8 battle+revert 矛盾判定键（契约 V4 [L332] + ADR D-04 [L58]）
V8_DURATION: str = "battle"

# 效果条目双形态键（§1.3-f2 对齐 V-1：引用 {effect, overrides} / 原子动作
# {type, ...}；derive_only 技能 effects 引用查表用，P-5）
EFFECT_REF_KEY: str = "effect"
EFFECT_ATOMIC_KEY: str = "type"

# x_ 前缀自定义效果例外（细化_6a [L131]：x_ 前缀例外，编辑器隐藏，V-1 放行；
# V7 derive_only 效果引用同口径，P-5）
X_PREFIX: str = "x_"

# 模块名（report 收集器 module 恒为 "jobs"，与 validate_skills 的 "skills"
# 同口径）
MODULE_NAME: str = "jobs"


# =====================================================================================
# 收集器发射（三形态兼容：_Checker._err/_warn → dict {"errors","warnings"} → list）
# =====================================================================================


def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    """向收集器发一条校验记录（error/warning 两态，三形态收集器兼容）。

    优先级：_Checker._err/_warn（module 首参）→ dict/list 形态（rec 直接
    append）→ 鸭子类型 error/warning（带 module 首参）兜底。module 恒为
    "jobs"（与 validate_skills 的 "skills" 同口径）。
    """
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
        rec = {"field": field, "kind": kind, "level": level, **detail}
        report.append(rec)
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
# 引用表收集
# =====================================================================================


def _id_set(data: object) -> Set[str]:
    """list 形态模块的 id 集合（skills/skill_chains/effects 引用查表）。

    表缺失/非 list → 空集（与 skill_validator._id_set 同款）；条目非
    Mapping / id 非非空字符串 → 跳过。
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
    """防御性字符串列表读取（derive_chains；非 list → 空）。"""
    v = entry.get(key)
    return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()


def _str_val(entry: Mapping[str, object], key: str) -> Optional[str]:
    """防御性字符串读取（transform_skill/transform_to/skill_set/job_form/
    job_scope；非字符串/空串 → None）。"""
    v = entry.get(key)
    return v if isinstance(v, str) and v else None


def _bool_val(entry: Mapping[str, object], key: str) -> Optional[bool]:
    """防御性布尔读取（revert/revert_form/derive_only；非 bool → None）。"""
    v = entry.get(key)
    return v if isinstance(v, bool) else None


def _module_data(modules: Mapping[str, object], key: str) -> Optional[List[object]]:
    """引用靶模块读取（skills/skill_chains/effects）。

    None/非 list → None（P-2 宽松放行：表缺失跳过引用红拦，缺表先例
    V-5/P-1）；list（含空表）→ 原样返回（空表 = 引用必红拦）。
    """
    data = modules.get(key)
    return data if isinstance(data, list) else None


def _all_forms(jobs_data: object) -> Set[str]:
    """全库形态值域 = 各职业 transform.transform_to 集合（P-4 挂点归属判定基）。

    仅收集 transform 段为 Mapping 且 transform_to 为非空字符串的职业；
    无 transform 段/transform_to 缺失 → 不贡献形态（§1.1 #10 缺省合法）。
    """
    out: Set[str] = set()
    if not isinstance(jobs_data, list):
        return out
    for j in jobs_data:
        if not isinstance(j, Mapping):
            continue
        tr = j.get("transform")
        if not isinstance(tr, Mapping):
            continue
        tt = _str_val(tr, KEY_TRANSFORM_TO)
        if tt is not None:
            out.add(tt)
    return out


def _skill_forms(skills_data: object) -> Set[str]:
    """skills 表内技能 job_form 值集合（V5 transform_to 引用存在判定基）。

    skills 表缺失/非 list → 空集（P-2：缺表时 V5 引用检查整体跳过）；
    表存在但无技能带 job_form → 空集（transform_to 形态无人引用 → 红拦）。
    """
    out: Set[str] = set()
    if not isinstance(skills_data, list):
        return out
    for s in skills_data:
        if not isinstance(s, Mapping):
            continue
        jf = _str_val(s, KEY_JOB_FORM)
        if jf is not None:
            out.add(jf)
    return out


# =====================================================================================
# 单条目校验（V5 / V6 / V8；job 侧 transform 引用）
# =====================================================================================


def _check_v5_transform_refs(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    skills_ids: Optional[Set[str]],
    skill_forms: Set[str],
) -> None:
    """V5 技能挂点引用（红拦，任务口径 = 契约 V1/V2/V8 引用存在性）。

    - transform.transform_skill → skills 表存在（红拦，契约 V2 [L331]）；
      skills 表缺失 → 宽松放行（P-2，缺表先例 V-5/P-1）。
    - transform.skill_set → skills 表存在（红拦，契约 V8 [L336]）。
    - transform.transform_to → JOB_FORM 值域引用存在（红拦，契约 V1
      [L329]）：形态须被 ≥1 技能 job_form 引用，否则形态为死配置
      （skills 表缺失 → 宽松放行 P-2）。
    """
    transform = entry.get("transform")
    if not isinstance(transform, Mapping):
        return  # 无 transform 段 → 无挂点引用可查（§1.1 #10 缺省合法）
    ts = _str_val(transform, KEY_TRANSFORM_SKILL)
    if ts is not None and skills_ids is not None and ts not in skills_ids:
        _err(report, f"{base}.transform.transform_skill", "V5",
             rule="V5_transform_skill_ref", node_id=sid, skill_ref=ts,
             ref_target="skill",
             msg="触发技能 %r 不存在（V5：transform.transform_skill ∈ skills 表）" % (ts,))
    ss = _str_val(transform, KEY_SKILL_SET)
    if ss is not None and skills_ids is not None and ss not in skills_ids:
        _err(report, f"{base}.transform.skill_set", "V5",
             rule="V5_skill_set_ref", node_id=sid, skill_set_ref=ss,
             ref_target="skill",
             msg="形态技能组 %r 不存在（V5：transform.skill_set ∈ skills 表）" % (ss,))
    tt = _str_val(transform, KEY_TRANSFORM_TO)
    if tt is not None and skills_ids is not None and tt not in skill_forms:
        _err(report, f"{base}.transform.transform_to", "V5",
             rule="V5_form_unreferenced", node_id=sid, transform_to=tt,
             ref_target="job_form",
             msg=(
                 "形态 %r 无任何技能 job_form 引用"
                 "（V5：transform_to ∈ JOB_FORM 值域，死形态配置）" % (tt,)
             ))


def _check_v6_derive_chains(
    report: object,
    base: str,
    sid: str,
    entry: Mapping[str, object],
    chains_ids: Optional[Set[str]],
    chains_by_id: Mapping[str, Mapping[str, object]],
) -> None:
    """V6 派生链作用域（红拦，任务口径 = 契约 V8 后半段 + §1.6 #39 + §2.3 ③）。

    - transform.derive_chains 每个值 ∈ skill_chains 表存在（红拦）；表缺失
      宽松放行（P-2）。
    - 链条目 job_scope 与 transform_to 形态一致性：链存在且 job_scope 键
      存在但不等于 transform_to → V6 红拦（§1.3 #31「链 job_scope=该形态」
      + §2.3 ③ V8 口径）；链缺失 job_scope 键 → 无形态作用域限制放行
      （P-3，等价于通用链）；transform_to 缺失 → 跳过一致性判定（P-3，
      必填缺失由泛型 R-5 红拦）。
    """
    transform = entry.get("transform")
    if not isinstance(transform, Mapping):
        return  # 无 transform 段 → 无 derive_chains 可查（§1.1 #10 缺省合法）
    chains = _str_list(transform, KEY_DERIVE_CHAINS)
    if not chains:
        return
    if chains_ids is None:
        return  # P-2：skill_chains 表缺失宽松放行
    tt = _str_val(transform, KEY_TRANSFORM_TO)
    for i, cid in enumerate(chains):
        if cid not in chains_ids:
            _err(report, f"{base}.transform.derive_chains[{i}]", "V6",
                 rule="V6_chain_ref", node_id=sid, chain_ref=cid,
                 ref_target="skill_chain",
                 msg="派生链 %r 不存在（V6：transform.derive_chains ∈ skill_chains 表）" % (cid,))
            continue
        ch = chains_by_id.get(cid)
        if not isinstance(ch, Mapping):
            continue
        scope = _str_val(ch, KEY_JOB_SCOPE)
        if scope is not None and scope != tt:
            _err(report, f"{base}.transform.derive_chains[{i}]", "V6",
                 rule="V6_chain_scope", node_id=sid, chain_ref=cid,
                 job_scope=scope, transform_to=tt,
                 msg=(
                 "派生链 %r 的 job_scope=%r 与本职业 transform_to=%r"
                 " 不一致（V6：链 job_scope=该形态）" % (cid, scope, tt)
             ))


def _check_v8_battle_revert(
    report: object, base: str, sid: str, entry: Mapping[str, object]
) -> None:
    """V8 battle+revert 红拦（红拦，任务口径 = 契约 V4 + ADR D-04 仲裁）。

    transform.duration == "battle" 且 transform.revert is True → 红拦：
    矛盾配置令还原时序二义（battle=整场不还原 vs revert=结束后还原），
    细化层仲裁为红拦（与技能库校验器「死配置」口径一致）。判定以字面
    bool True 为准（P-6）。
    """
    transform = entry.get("transform")
    if not isinstance(transform, Mapping):
        return  # 无 transform 段 → 无矛盾可查（P-6）
    duration = transform.get(KEY_DURATION)
    revert = transform.get(KEY_REVERT)
    if duration == V8_DURATION and revert is True:
        _err(report, f"{base}.transform.duration/revert", "V8",
             rule="V8_battle_revert_conflict", node_id=sid,
             duration=duration, revert=revert,
             msg=(
                 "duration=battle 与 revert=true 矛盾"
                 "（V8：battle=整场不还原 vs revert=结束后还原，ADR D-04 红拦）"
             ))


# =====================================================================================
# 库级校验（V7 死配置：技能/链挂点引用 + derive_only 效果引用）
# =====================================================================================


def _check_effects_refs(
    report: object,
    base: str,
    node_id: str,
    entry: Mapping[str, object],
    effects_ids: Optional[Set[str]],
) -> None:
    """V7 死配置：effects 引用存在（红拦，仿 V-1 判定细节，P-5）。

    effects[].effect ∈ effects 表 id（x_ 前缀例外放行 [L131]）；effects[].type
    原子动作（L0 词汇表成员）放行；effects 表缺失 → 宽松放行（P-2）。
    """
    if effects_ids is None:
        return  # P-2：effects 表缺失宽松放行
    effects = entry.get("effects")
    if not isinstance(effects, list):
        return  # 结构形态校验归泛型/6a，本文件只查引用
    for i, eff in enumerate(effects):
        if not isinstance(eff, Mapping):
            continue
        ref = eff.get(EFFECT_REF_KEY)
        if isinstance(ref, str) and ref:
            if ref.startswith(X_PREFIX):
                continue  # x_ 前缀自定义效果例外（细化_6a [L131]）
            if ref not in effects_ids:
                _err(report, f"{base}.effects[{i}]", "V7",
                     rule="V7_effect_ref", node_id=node_id, effect_ref=ref,
                     ref_target="effect",
                     msg=(
                         "效果引用 %r 不存在"
                         "（V7：derive_only 技能 effects[].effect ∈ effects 表）" % (ref,)
                     ))


def _check_v7_dead_config(
    report: object,
    skills_data: Optional[List[object]],
    chains_data: Optional[List[object]],
    all_forms: Set[str],
    effects_ids: Optional[Set[str]],
) -> None:
    """V7 死配置（红拦，仿 validator._check_dead_config 模式，库级单跑）。

    引用了不存在的 id/效果 → 红拦：
    - 技能 job_form 引用不存在的形态（job_form ∉ all_forms → 死引用；
      all_forms 为空而技能带 job_form → 全库无形态可归 → 死引用）。
    - revert_form=true 技能归属校验（契约 V6 [L334]）：job_form 缺失/非
      字符串或 ∉ all_forms → 红拦（不归属任何形态组，P-4）。
    - derive_only=true 技能 effects 引用不存在（P-5，效果引用仿 V-1）。
    - 链 job_scope 引用不存在的形态（job_scope ∉ all_forms → 死引用）。
    库级单跑一次（技能/链侧字段非 job 条目字段，逐职业跑会 N 倍重复）。
    """
    if skills_data is not None:
        for i, s in enumerate(skills_data):
            base = f"[{i}]"
            if not isinstance(s, Mapping):
                continue
            sid = _entry_id(s)
            jf = _str_val(s, KEY_JOB_FORM)
            if jf is not None and jf not in all_forms:
                _err(report, f"{base}.job_form", "V7",
                     rule="V7_job_form_ref", node_id=sid, job_form=jf,
                     ref_target="job_form",
                     msg=(
                         "技能 job_form %r 不在任何职业 transform 形态值域 %s"
                         "（V7：引用了不存在的形态，死配置）" % (jf, sorted(all_forms))
                     ))
            rf = _bool_val(s, KEY_REVERT_FORM)
            if rf is True:
                if jf is None or jf not in all_forms:
                    _err(report, f"{base}.revert_form", "V7",
                         rule="V7_revert_form_scope", node_id=sid,
                         job_form=jf, all_forms=sorted(all_forms),
                         msg=(
                             "revert_form=true 技能须 job_form ∈ 形态值域 %s"
                             "（V7：契约 V6 归属校验，不归属形态组）" % (sorted(all_forms),)
                         ))
            do = _bool_val(s, KEY_DERIVE_ONLY)
            if do is True:
                _check_effects_refs(report, base, sid, s, effects_ids)
    if chains_data is not None:
        for i, c in enumerate(chains_data):
            base = f"[{i}]"
            if not isinstance(c, Mapping):
                continue
            cid = _entry_id(c)
            js = _str_val(c, KEY_JOB_SCOPE)
            if js is not None and js not in all_forms:
                _err(report, f"{base}.job_scope", "V7",
                     rule="V7_job_scope_ref", node_id=cid, job_scope=js,
                     ref_target="job_form",
                     msg=(
                         "链 job_scope %r 不在任何职业 transform 形态值域 %s"
                         "（V7：引用了不存在的形态，死配置）" % (js, sorted(all_forms))
                     ))


# =====================================================================================
# 单条目包装 + 主入口
# =====================================================================================


def _check_job_entry(
    report: object,
    entry: object,
    idx: int,
    ctx: Mapping[str, object],
) -> None:
    """单条职业条目校验（V5 / V6 / V8 全量；V7 为库级单独跑）。"""
    base = f"[{idx}]"
    if not isinstance(entry, Mapping):
        _err(report, base, "R-5", rule="job_not_object",
             node_id=str(idx), got=type(entry).__name__,
             msg="jobs.json 每条职业需对象")
        return
    sid = _entry_id(entry)
    skills_ids = ctx.get("skills_ids")
    skill_forms = ctx.get("skill_forms")
    chains_ids = ctx.get("chains_ids")
    chains_by_id = ctx.get("chains_by_id")
    skills_ids_set = skills_ids if isinstance(skills_ids, set) else None
    chains_ids_set = chains_ids if isinstance(chains_ids, set) else None
    forms_set = skill_forms if isinstance(skill_forms, set) else set()
    chains_map = chains_by_id if isinstance(chains_by_id, Mapping) else {}
    _check_v5_transform_refs(report, base, sid, entry, skills_ids_set, forms_set)
    _check_v6_derive_chains(report, base, sid, entry, chains_ids_set, chains_map)
    _check_v8_battle_revert(report, base, sid, entry)


def validate_jobs_v58(modules: Mapping[str, object], report: object) -> None:
    """职业库专项校验主入口 V5~V8（细化_6b §五 后半段；loader/validator 专项路由调用）。

    入参:
      modules: 全量内容模块（jobs 键为职业条目数组；缺失 → 跳过，对齐既有
               校验器「模块未接线默认放行」惯例；skills/skill_chains/effects
               为引用靶模块——缺失 → 宽松放行，P-2）。
      report:  收集器（_err/_warn 三形态兼容：_Checker / dict
               {"errors":[],"warnings":[]} / list）。
    出参: 无（红拦全部经 report 收集，红拦由 loader 聚合拒绝加载；
          V5~V8 全红拦，本路无黄提示）。

    实现要点（V5~V8 后半段，主 agent 收口时并入 job_validator.py）：
      - V5 技能挂点引用（红拦）：transform.transform_skill / skill_set →
        skills 表存在（缺表宽松放行 P-2）；transform_to → JOB_FORM 值域
        （须被 ≥1 技能 job_form 引用，死形态配置红拦）。
      - V6 派生链作用域（红拦）：transform.derive_chains → skill_chains 表
        存在（缺表宽松放行 P-2）；链 job_scope 与 transform_to 一致性
        （§2.3 ③ V8 口径）。
      - V7 死配置（红拦）：技能 job_form / revert_form / 链 job_scope 引用
        不存在的形态 + derive_only 技能 effects 引用不存在 → 红拦（仿
        _check_dead_config 模式；挂点字段缺登记宽松放行 P-1，库级单跑）。
      - V8 battle+revert 红拦（红拦）：transform.duration == "battle" 且
        transform.revert is True → 红拦（ADR D-04）。
    """
    data = modules.get("jobs")
    if data is None:
        return
    if not isinstance(data, list):
        _err(report, "jobs", "R-5", rule="job_not_list",
             node_id=None, got=type(data).__name__,
             msg="jobs.json 需顶层数组（每条职业一个对象，契约 §1.1）")
        return

    # 引用靶表（skills/skill_chains/effects 缺失 → None → 宽松放行 P-2；
    # 表存在但空 → 引用必红拦）
    skills_data = _module_data(modules, "skills")
    chains_data = _module_data(modules, "skill_chains")
    effects_data = _module_data(modules, "effects")
    skills_ids: Optional[Set[str]] = _id_set(skills_data) if skills_data is not None else None
    chains_ids: Optional[Set[str]] = _id_set(chains_data) if chains_data is not None else None
    effects_ids: Optional[Set[str]] = _id_set(effects_data) if effects_data is not None else None
    skill_forms = _skill_forms(skills_data)
    all_forms = _all_forms(data)

    # V6 链索引（id → 条目；仅 Mapping 条目入表）
    chains_by_id: Dict[str, Mapping[str, object]] = {}
    if isinstance(chains_data, list):
        for e in chains_data:
            if isinstance(e, Mapping):
                cid = e.get("id")
                if isinstance(cid, str) and cid:
                    chains_by_id[cid] = e

    ctx: Mapping[str, object] = {
        "skills_ids": skills_ids,
        "skill_forms": skill_forms,
        "chains_ids": chains_ids,
        "chains_by_id": chains_by_id,
    }
    for i, entry in enumerate(data):
        _check_job_entry(report, entry, i, ctx)
    # V7 库级单跑（技能/链挂点死配置；放末尾跑，条目级错误优先收集）
    _check_v7_dead_config(report, skills_data, chains_data, all_forms, effects_ids)


__all__ = [
    "MODULE_NAME",
    "KEY_TRANSFORM_SKILL",
    "KEY_TRANSFORM_TO",
    "KEY_DURATION",
    "KEY_REVERT",
    "KEY_SKILL_SET",
    "KEY_DERIVE_CHAINS",
    "KEY_JOB_FORM",
    "KEY_REVERT_FORM",
    "KEY_DERIVE_ONLY",
    "KEY_JOB_SCOPE",
    "V8_DURATION",
    "EFFECT_REF_KEY",
    "EFFECT_ATOMIC_KEY",
    "X_PREFIX",
    "validate_jobs_v58",
]
