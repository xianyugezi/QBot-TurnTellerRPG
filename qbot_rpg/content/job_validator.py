"""M13 职业库专项校验器（细化_6b §五：V1~V4 加载期红拦，批5 路5A）。

文件名：job_validator.py
创建时间：2026-09-02
作者：Hermes 子agent-5A（M13 职业库实现组批5路5A：6b 职业库校验 V1~V4）

功能描述：
  - validate_jobs(modules, report) 纯函数专项校验器（对齐 M4/M8/M9/M11 同族
    validate_xxx(modules, report) 鸭子类型口径，report 三形态收集器兼容，
    与 qbot_rpg.content.skill_validator.validate_skills 同形态）：
    V1 字段结构（红拦）：jobs 条目顶层字段 ∈ jobs_fields 34 键（含 transform
        段 11 子键 + state_policy 3 子键的嵌套结构登记）；缺 id/name 红拦；
        顶层未知键红拦；transform 非对象红拦；transform 段未知子键红拦；
        state_policy 非对象红拦（非对象子键红拦由 V5 专项承接，本文件不重复）；
    V2 成长率合法（红拦）：growth 各子字段数值 ∈ [0, 合理上限]
        （hp/mp 0~1000、其余七键 0~100，契约 §1.2 成长率锚点量级 路3 B5
        L103）；非数值红拦；负值红拦；超上限红拦；
    V3 资源轴引用（红拦）：resource_axes 每个值 ∈ stats.json 注册段
        （6c 批8 才落，缺表宽松放行+注释；stats 存在则严格查）；
    V4 transform 段合法（红拦）：transform 段存在时必需键齐
        （transform_skill/transform_to/duration/revert/cooldown/state_policy/
        skill_set 七必填，§1.3 字段表）；duration/turns/cooldown 非负；
        state_policy 三键枚举 ∈ {clear, keep}；battle+revert=true 矛盾红拦。
  - 红黄分级：V1~V4 全红拦（细化_6b §五层级列全部「🔴 红拦」；V4 含 D-04
    仲裁与 3e2 BLK-1 死配置同档）。
  - 收口边界（本文件不含，明确登记不越界）：
    V2（transform_skill 归属校验）/ V3（transform_to 存在性+形态环）/
    V6 / V7 / V8 归批5 路5B job_validator_v58.py（主 agent 收口合并）；
    transform_to 引用存在性与自指（契约 V1）在路5B 与 skill 侧 job_form
    值域联动收口（V1 契约判定含 forms 注册/JOB_FORM 值域双源，本文件按
    任务批号切分不重复拦截）；级联删除钩子随 6a 技能库统一实现。

依据：
  - docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
    §1.1 顶层字段表（#1~#11，id/name 必填 L71-72）；§1.2 growth 九属性
    成长率（#12~#20，缺省 0，锚点 路3 B5 L103：str 2.0/con 1.5/int 2.0/
    spr 1.5/lck 1.0/agi 2.0/hp 1.5 等量级）；§1.3 transform 段 11 字段
    （#21~#31，必填 7：transform_skill/transform_to/duration/revert/
    cooldown/state_policy/skill_set；turns 条件必填 >0；cooldown ≥0；
    duration 枚举 turns|battle；battle+revert=true → 红拦 V4/D-04）；
    §1.4 state_policy 3 字段（#32~#34，三键枚举 {clear, keep} 二值收敛，
    枚举外值 → V5 红拦）；§五 V1~V8 层级全红拦；D-04（battle+revert 仲裁
    红拦）；⑥ TC-18（校验器全量扫描坏包断言 ①~⑨）。
  - docs/m13_6b摸底.md：G3（V1~V8 全缺）；可复用模式：V1/V2 引用存在性仿
    泛型 R-4、V3 形态环仿 _check_chain_cycle、V4 battle+revert 矛盾仿
    _check_dead_config、V5 state_policy 枚举仿 FieldMeta enum、V7 黄提示仿
    Y 系；批8 切法（V1~V8 红/黄二分）。
  - 模式参考：qbot_rpg/content/skill_validator.py（validate_skills 同形态，
    _err/_warn 三形态收集器，module 恒为 'skills'——本文件 module 恒为
    'jobs'）；qbot_rpg/content/job_models.py（jobs_fields()/transform_fields()/
    state_policy_fields() 34 键 FieldMeta 登记表单点）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  V1 字段登记口径 = job_models.jobs_fields() 顶层 11 键 + transform 段
       11 子键 + state_policy 3 子键 = 34 键（任务批号口径：jobs 条目顶层
       字段 ∈ jobs_fields 34 键含 transform/state_policy 子键结构）；顶层
       未知键红拦、transform 段未知子键红拦（未登记字段拒绝依据 = 4f 注册
       契约 + 摸底 §8-2 skills 先例）；growth 内未知子键黄提示不拦截
       （成长率九键非登记即忽略有消费歧义，三铁律② 防御读取）。
  P-2  V2 合理上限：hp/mp 0~1000、其余七键 0~100（任务规格字面）；任务规格
       用 atk_growth 表述，契约键空间无 atk（growth 九键 = str/int/con/spr/
       foc/agi/lck/hp/mp，§1.2）——按契约键实现，hp/mp 上限 1000 语义对齐
       「hp_growth 0~1000」，其余七键（含 str 等攻击向）上限 100 语义对齐
       「atk_growth 0~100」；非数值/负值/超上限 → 红拦（FieldMeta
       range_min 仅为 Y-1 黄提示口径，本专项按任务规格红拦）。
  P-3  V3 stats 缺表宽松放行（对齐 skill_validator V-5 jobs 缺表 P-1 先例）：
       modules 无 "stats" 键或非 map/list → 零红零黄（6c 批8 才落 stats
       energy_cost 字段，缺表期间 resource_axes 引用无法判定）；stats 为
       map 形态（field_meta entry_type="map"，键 = 属性 ID）→ 查键；stats
       为 list 形态（内容包手写统计侧）→ 查条目 id；stats 存在则严格红拦。
  P-4  V4 必需键齐判定 = transform 段七必填键逐键缺失红拦（§1.3 字段表
       required=True 口径，与 field_meta transform children required 登记
       一致）；turns 条件必填（duration=turns 时缺失/≤0 红拦，duration=
       battle 时 turns 缺省合法）；cooldown 负值红拦（≥0，§1.3 #26）；
       duration 枚举外值红拦（battle+revert=true 矛盾红拦 V4 在枚举合法
       前提下判定）；state_policy 非对象红拦、三键枚举外值红拦（V5 判定
       基底 = 本文件 V4 结构段，契约 §1.4 注「枚举外值 → V5 红拦」，任务
       批号将 V5 归路5B，枚举红拦本文件先行收口，V5 枚举常量与 rules 名
       与路5B 同名常量对齐，主 agent 合并时去重）。
  P-5  宽松放行口径（三铁律②）：growth 缺省/非对象 → 不拦（全 0 成长率
       合法，§1.2「缺省 0」）；resource_axes 缺省 → 不拦（§1.1 #6 必填但
       JobDef 兜底空元组）；transform 缺省 → 不拦（§1.1 #10 缺省=无形态
       切换职业）；name 缺 id 兜底 → 缺 id 红拦、缺 name 红拦（§1.1 #2
       必填，不随 BaseDef 兜底）。
  P-6  红拦条目不重复上报：同一条目同字段同规则只报一次（对齐
       skill_validator 逐条独立上报口径）；条目非对象红拦一条后跳过其余
       检查（防级联噪音）。
  P-7  duration 枚举外值 + battle+revert 判定：枚举外值已红拦，battle 矛盾
       仅在 duration == "battle" 时判定（枚举外值不再叠加矛盾红拦，防双报）。

铁律：零 NoneBot import；完整类型标注（typing 3.9 兼容）；纯函数；确定性；
零定时器/零睡眠（本文件不含任何 sleep/定时器字面量）；不引入随机；不 git
commit。仅依赖 qbot_rpg.content.job_models（jobs_fields/transform_fields/
state_policy_fields 34 键 FieldMeta 登记表单点，G0 单向依赖：content 层不
import core）与标准库。
"""

from __future__ import annotations

from typing import Mapping, Set, Tuple

from qbot_rpg.content.job_models import (
    GROWTH_KEYS,
    STATE_POLICY_VALUES,
    TRANSFORM_DURATION_VALUES,
    transform_fields,
)

# =====================================================================================
# 常量（细化_6b §1.2 成长率值域 / §1.3 transform 段必填与枚举 / §1.4 state_policy）
# =====================================================================================

# V2 growth 合理上限（P-2：hp/mp 0~1000、其余七键 0~100，任务规格字面；
# 契约 §1.2 锚点 路3 B5 L103 量级 str 2.0/con 1.5/int 2.0/spr 1.5/lck 1.0/
# agi 2.0/hp 1.5 远低于上限，上限为防误配数量级护栏）
GROWTH_LIMITS: Mapping[str, Tuple[float, float]] = {
    "hp": (0.0, 1000.0),
    "mp": (0.0, 1000.0),
    "str": (0.0, 100.0),
    "int": (0.0, 100.0),
    "con": (0.0, 100.0),
    "spr": (0.0, 100.0),
    "foc": (0.0, 100.0),
    "agi": (0.0, 100.0),
    "lck": (0.0, 100.0),
}

# V4 transform 段七必填键（§1.3 字段表 #21/#22/#23/#25/#26/#28/#29 required；
# 与 field_meta transform children required 登记同源）
TRANSFORM_REQUIRED_KEYS: Tuple[str, ...] = (
    "transform_skill",
    "transform_to",
    "duration",
    "revert",
    "cooldown",
    "state_policy",
    "skill_set",
)

# V4 state_policy 三键（§1.4 #32~#34：combo/marks/buff）
STATE_POLICY_KEYS: Tuple[str, ...] = ("combo", "marks", "buff")

# 顶层 id/name 必填（§1.1 #1/#2；name 不随 BaseDef 兜底，P-5）
TOP_REQUIRED_KEYS: Tuple[str, ...] = ("id", "name")


# =====================================================================================
# 收集器发射（三形态兼容，与 skill_validator._emit 同口径；module 恒为 "jobs"）
# =====================================================================================


def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    """向收集器发一条校验记录（error/warning 两态，三形态收集器兼容）。

    优先级：_Checker._err/_warn（module 首参）→ dict/list 形态（rec 直接
    append）→ 鸭子类型 error/warning（带 module 首参）兜底。module 恒为
    "jobs"（与 validate_skills 恒为 "skills" 同口径）。
    """
    if hasattr(report, "_err") and level == "error":
        report._err("jobs", field, kind, **detail)
        return
    if hasattr(report, "_warn") and level == "warning":
        report._warn("jobs", field, kind, **detail)
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
        report.error("jobs", field, kind, **detail)
        return
    if hasattr(report, "warning") and level == "warning":
        report.warning("jobs", field, kind, **detail)
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
# V1 字段结构（红拦）：顶层字段 ∈ jobs_fields 34 键 + 嵌套子键结构
# =====================================================================================


def _jobs_known_keys() -> Set[str]:
    """jobs 条目合法键集合（P-1：顶层 11 + transform 11 + state_policy 3 = 34 键）。

    以 job_models.jobs_fields() 为单点（顶层 11 键）；transform 段 11 子键
    与 state_policy 3 子键经 jobs_fields()["transform"].children 嵌套读取
    （4B 合写后 children 已含 14 子键，任务口径 34 键 = 顶层 11 + 子键 23）。
    """
    from qbot_rpg.content.job_models import jobs_fields

    top = set(jobs_fields().keys())
    tf = jobs_fields().get("transform")
    if tf is not None:
        top.update(tf.children.keys())
        sp = tf.children.get("state_policy")
        if sp is not None:
            top.update(sp.children.keys())
    return top


def _check_v1_field_structure(
    report: object, base: str, jid: str, entry: Mapping[str, object]
) -> None:
    """V1 字段结构（红拦）：顶层字段 ∈ jobs_fields 34 键（含 transform/
    state_policy 子键），缺 id/name 红拦，transform 非对象/未知子键红拦。

    判定口径（P-1/P-5）：
      - 顶层未知键 → 红拦（未登记字段拒绝依据 = 4f 注册契约）；
      - 缺 id / 缺 name → 红拦（§1.1 #1/#2 必填，name 不随 BaseDef 兜底）；
      - transform 存在但非对象 → 红拦（§1.1 #10 形态为对象）；
      - transform 为对象时其未知子键 → 红拦（§1.3 11 子键登记口径）；
      - growth 内未知子键 → 黄提示不拦截（P-1，成长率键非登记即忽略有
        消费歧义，非顶层字段拒绝语义）。
    """
    known = _jobs_known_keys()
    for k in entry:
        if k not in known:
            _err(report, f"{base}.{k}", "V1", rule="V1_top_field_unregistered",
                 node_id=jid, field_name=k,
                 msg=(f"职业字段 {k} 未登记（V1：须在 jobs_fields 34 键内，"
                      "含 transform/state_policy 子键）"))
    for req in TOP_REQUIRED_KEYS:
        if req not in entry:
            _err(report, f"{base}.{req}", "V1", rule="V1_required_missing",
                 node_id=jid, field_name=req,
                 msg=f"职业缺少必填字段 {req}（V1：§1.1 id/name 必填）")
    # 缺省语义：id/name 显式 null 视为缺失（§1.1 #1/#2 必填，name 不随
    # BaseDef 兜底，P-5）；非对象条目已由 _check_job_entry 红拦跳过
    for req in TOP_REQUIRED_KEYS:
        if entry.get(req) is None:
            _err(report, f"{base}.{req}", "V1", rule="V1_required_missing",
                 node_id=jid, field_name=req,
                 msg=f"职业缺少必填字段 {req}（V1：§1.1 id/name 必填，null 视为缺失）")
    tf = entry.get("transform")
    if tf is None:
        return  # §1.1 #10 缺省 = 无形态切换职业，合法不拦
    if not isinstance(tf, Mapping):
        _err(report, f"{base}.transform", "V1", rule="V1_transform_not_object",
             node_id=jid, got=type(tf).__name__,
             msg="transform 段需对象（V1：§1.1 #10 形态切换引擎配置段）")
        return
    tf_known = set(transform_fields().keys())
    for k in tf:
        if k not in tf_known:
            _err(report, f"{base}.transform.{k}", "V1", rule="V1_transform_field_unregistered",
                 node_id=jid, field_name=k,
                 msg=f"transform 段字段 {k} 未登记（V1：须在 transform_fields 11 键内）")
    sp = tf.get("state_policy")
    if sp is not None and not isinstance(sp, Mapping):
        _err(report, f"{base}.transform.state_policy", "V1", rule="V1_state_policy_not_object",
             node_id=jid, got=type(sp).__name__,
             msg="state_policy 需对象（V1：§1.4 三键子对象）")
    # growth 未知子键黄提示（P-1：非登记即忽略有消费歧义，防御读取不拦）
    g = entry.get("growth")
    if isinstance(g, Mapping):
        for k in g:
            if k not in GROWTH_KEYS:
                _warn(report, f"{base}.growth.{k}", "V1", rule="V1_growth_unregistered_key",
                      node_id=jid, field_name=k,
                      msg=f"growth 子字段 {k} 不在九属性注册表（V1 黄提示不拦截，消费侧忽略）")


# =====================================================================================
# V2 成长率合法（红拦）：growth 各子字段数值 ∈ [0, 合理上限]
# =====================================================================================


def _check_v2_growth(
    report: object, base: str, jid: str, entry: Mapping[str, object]
) -> None:
    """V2 成长率合法（红拦）：growth 各子字段数值 ∈ [0, 合理上限]。

    判定口径（P-2/P-5）：
      - growth 缺省/非对象 → 不拦（全 0 成长率合法，§1.2「缺省 0」）；
      - 子字段非数值（含 bool）→ 红拦；
      - 子字段负值 → 红拦（FieldMeta range_min 0 口径，任务规格红拦）；
      - 子字段超上限 → 红拦（hp/mp ≤1000、其余七键 ≤100）；
      - growth 内未知子键 → 不拦（V1 已黄提示，V2 只校验九键值域）。
    """
    g = entry.get("growth")
    if g is None:
        return  # §1.2 缺省 0，全 0 成长率合法
    if not isinstance(g, Mapping):
        _err(report, f"{base}.growth", "V2", rule="V2_growth_not_object",
             node_id=jid, got=type(g).__name__,
             msg="growth 需对象（V2：§1.2 九属性成长率子对象）")
        return
    for key in GROWTH_KEYS:
        if key not in g:
            continue  # §1.2 缺省 0，未配键合法
        v = g[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            _err(report, f"{base}.growth.{key}", "V2", rule="V2_growth_not_number",
                 node_id=jid, growth_key=key, value=v,
                 msg=f"成长率 {key} 需数值（V2：非数值红拦，got {type(v).__name__}）")
            continue
        lo, hi = GROWTH_LIMITS[key]
        if v < lo:
            _err(report, f"{base}.growth.{key}", "V2", rule="V2_growth_negative",
                 node_id=jid, growth_key=key, value=v,
                 msg=f"成长率 {key} 不能为负数（V2：∈ [0, {hi:g}]）")
        elif v > hi:
            _err(report, f"{base}.growth.{key}", "V2", rule="V2_growth_out_of_range",
                 node_id=jid, growth_key=key, value=v, limit=hi,
                 msg=f"成长率 {key} 超过上限 {hi:g}（V2：hp/mp ≤1000、其余 ≤100）")


# =====================================================================================
# V3 资源轴引用（红拦）：resource_axes 每个值 ∈ stats.json 注册段
# =====================================================================================


def _stats_ids(stats_data: object) -> Set[str]:
    """stats.json 注册键集合（P-3：map 形态查键 / list 形态查条目 id）。

    stats 为 field_meta entry_type="map"（键 = 属性 ID，细化_3b §4.1）；
    内容包手写统计侧可为 list（条目 id 键空间）。缺表/非 map/list →
    空集（调用方据此宽松放行，不按引用不存在红拦——6c 批8 才落表）。
    """
    if isinstance(stats_data, Mapping):
        return {str(k) for k in stats_data.keys() if isinstance(k, str)}
    if isinstance(stats_data, list):
        out: Set[str] = set()
        for e in stats_data:
            if isinstance(e, Mapping):
                v = e.get("id")
                if isinstance(v, str) and v:
                    out.add(v)
        return out
    return set()


def _check_v3_resource_axes(
    report: object, base: str, jid: str, entry: Mapping[str, object],
    stats_data: object,
) -> None:
    """V3 资源轴引用（红拦）：resource_axes 每个值 ∈ stats.json 注册段。

    判定口径（P-3/P-5）：
      - stats 模块缺失或非 map/list → 宽松放行（6c 批8 才落 stats 注册表，
        缺表期间引用无法判定，零红零黄——对齐 skill_validator V-5 jobs
        缺表 P-1 先例）；
      - stats 存在则严格查：resource_axes 每个字符串值 ∈ stats 注册键，
        任一缺失红拦；resource_axes 非 list → 红拦（§1.1 #6 string[]）；
      - resource_axes 缺省 → 不拦（JobDef 兜底空元组，P-5）。
    """
    axes = entry.get("resource_axes")
    if axes is None:
        return  # P-5：缺省 = 无资源轴职业
    if not isinstance(axes, list):
        _err(report, f"{base}.resource_axes", "V3", rule="V3_axes_not_list",
             node_id=jid, got=type(axes).__name__,
             msg="resource_axes 需字符串数组（V3：§1.1 #6 资源轴列表）")
        return
    if stats_data is None or not isinstance(stats_data, (Mapping, list)):
        # P-3：stats 注册表 6c 批8 才落，缺表宽松放行（零红零黄）
        return
    ids = _stats_ids(stats_data)
    for ax in axes:
        if not isinstance(ax, str) or not ax:
            _err(report, f"{base}.resource_axes", "V3", rule="V3_axes_non_string",
                 node_id=jid, value=ax,
                 msg="resource_axes 每项需非空字符串（V3）")
            continue
        if ax not in ids:
            _err(report, f"{base}.resource_axes", "V3", rule="V3_axis_ref",
                 node_id=jid, axis_ref=ax, ref_target="stat",
                 msg="资源轴引用 %r 不存在（V3：resource_axes ∈ stats.json 注册段）" % (ax,))


# =====================================================================================
# V4 transform 段合法（红拦）：必需键齐 + 数值非负 + state_policy 三键枚举
# =====================================================================================


def _check_v4_transform(
    report: object, base: str, jid: str, entry: Mapping[str, object]
) -> None:
    """V4 transform 段合法（红拦）：transform 段存在时必需键齐、
    duration/turns/cooldown 非负、state_policy 三键枚举 ∈ {clear, keep}。

    判定口径（P-4/P-7）：
      - transform 缺省 → 不拦（§1.1 #10 缺省=无形态切换职业）；
      - transform 非对象 → V1 已红拦，V4 跳过（防双报，P-6）；
      - 七必填键逐键缺失 → 红拦（§1.3 字段表 required 口径）；
      - duration 枚举外值 → 红拦（turns|battle，§1.3 #23）；
      - duration == "battle" 且 revert == true → 红拦（V4/D-04 仲裁，
        3e2 BLK-1 死配置同档；枚举外值不再叠加矛盾红拦，P-7）；
      - duration == "turns" 时 turns 缺失/≤0 → 红拦（§1.3 #24 条件必填）；
      - cooldown 负值 → 红拦（§1.3 #26 必填 ≥0；非数值缺失已由必填红拦）；
      - state_policy 非对象 → 红拦（§1.4 三键子对象）；
      - state_policy 三键枚举外值 → 红拦（§1.4 注：值域收敛 {clear, keep}
        二值，枚举外值 → V5 红拦；本文件按任务批号 V4 结构段先行收口，
        rules 名与路5B V5 枚举判定同名对齐，主 agent 合并去重）。
    """
    tf = entry.get("transform")
    if tf is None:
        return
    if not isinstance(tf, Mapping):
        return  # V1 已红拦（V1_transform_not_object），防双报 P-6
    for req in TRANSFORM_REQUIRED_KEYS:
        if req not in tf:
            _err(report, f"{base}.transform.{req}", "V4", rule="V4_required_missing",
                 node_id=jid, field_name=req,
                 msg=f"transform 段缺少必填字段 {req}（V4：§1.3 七必填）")
    # duration 枚举 + battle+revert 矛盾（P-4/P-7：枚举合法前提下判定矛盾）
    duration = tf.get("duration")
    if duration is not None and duration not in TRANSFORM_DURATION_VALUES:
        _err(report, f"{base}.transform.duration", "V4", rule="V4_duration_enum",
             node_id=jid, value=duration, allowed=list(TRANSFORM_DURATION_VALUES),
             msg="transform.duration 需 turns|battle（V4：§1.3 #23 两枚举）")
    elif duration == "battle" and tf.get("revert") is True:
        _err(report, f"{base}.transform.revert", "V4", rule="V4_battle_revert_conflict",
             node_id=jid, duration="battle", revert=True,
             msg="duration=battle 配 revert=true 矛盾（V4：整场不还原 vs 结束后还原，D-04 红拦）")
    # turns 条件必填（§1.3 #24：duration=turns 时 >0）
    if duration == "turns":
        turns = tf.get("turns")
        if turns is None:
            _err(report, f"{base}.transform.turns", "V4", rule="V4_turns_required",
                 node_id=jid,
                 msg="transform.turns 必填（V4：duration=turns 时条件必填 >0）")
        elif not isinstance(turns, (int, float)) or isinstance(turns, bool) or turns <= 0:
            _err(report, f"{base}.transform.turns", "V4", rule="V4_turns_positive",
                 node_id=jid, value=turns,
                 msg="transform.turns 需正整数（V4：duration=turns 时 >0）")
    # cooldown 非负（§1.3 #26：≥0；数值且负值红拦）
    cd = tf.get("cooldown")
    if isinstance(cd, (int, float)) and not isinstance(cd, bool) and cd < 0:
        _err(report, f"{base}.transform.cooldown", "V4", rule="V4_cooldown_negative",
             node_id=jid, value=cd,
             msg="transform.cooldown 不能为负数（V4：§1.3 #26 ≥0）")
    # state_policy 三键枚举（§1.4：值域收敛 {clear, keep} 二值）
    sp = tf.get("state_policy")
    if sp is not None and not isinstance(sp, Mapping):
        _err(report, f"{base}.transform.state_policy", "V4", rule="V4_state_policy_not_object",
             node_id=jid, got=type(sp).__name__,
             msg="transform.state_policy 需对象（V4：§1.4 三键子对象）")
        return
    if isinstance(sp, Mapping):
        for key in STATE_POLICY_KEYS:
            v = sp.get(key)
            if v is None:
                continue  # §1.4 三键各带默认值（clear/keep/keep），缺省合法
            if v not in STATE_POLICY_VALUES:
                _err(report, f"{base}.transform.state_policy.{key}", "V4",
                     rule="V4_state_policy_enum", node_id=jid, policy_key=key,
                     value=v, allowed=list(STATE_POLICY_VALUES),
                     msg="state_policy.%s 需 clear|keep（V4：§1.4 值域收敛二值）" % key)


# =====================================================================================
# 单条目校验（V1 ~ V4）
# =====================================================================================


def _check_job_entry(
    report: object, entry: object, idx: int, ctx: Mapping[str, object]
) -> None:
    """单条职业条目校验（V1~V4 全量；条目非对象红拦一条后跳过其余，P-6）。"""
    base = f"[{idx}]"
    if not isinstance(entry, Mapping):
        _err(report, base, "V1", rule="V1_job_not_object",
             node_id=str(idx), got=type(entry).__name__,
             msg="jobs.json 每条职业需对象（V1）")
        return
    jid = entry.get("id")
    jid = jid if isinstance(jid, str) and jid else "?"
    stats_data = ctx.get("stats_data")
    _check_v1_field_structure(report, base, jid, entry)
    _check_v2_growth(report, base, jid, entry)
    _check_v3_resource_axes(report, base, jid, entry, stats_data)
    _check_v4_transform(report, base, jid, entry)


# =====================================================================================
# 主入口
# =====================================================================================


def validate_jobs(modules: Mapping[str, object], report: object) -> None:
    """职业库专项校验主入口（细化_6b §五：V1~V4 红拦；loader/validator 专项路由调用）。

    入参:
      modules: 全量内容模块（jobs 键为职业条目数组；缺失 → 跳过，对齐既有
               校验器「模块未接线默认放行」惯例；stats 为 V3 引用靶模块）。
      report:  收集器（_err/_warn 三形态兼容：_Checker / dict {\"errors\":[]} /
               list）。
    出参: 无（红拦全部经 report 收集，红拦由 loader 聚合拒绝加载）。

    V1~V4 收口边界见文件头：V2 归属/V3 形态环/V6/V7/V8 归路5B
    job_validator_v58.py（本文件不越界）。
    """
    data = modules.get("jobs")
    if data is None:
        return
    if not isinstance(data, list):
        _err(report, "jobs", "V1", rule="V1_jobs_not_list",
             node_id=None, got=type(data).__name__,
             msg="jobs.json 需顶层数组（每条职业一个对象，细化_6b §1）")
        return

    # V3 引用靶：stats 模块（map/list 形态；缺失 → 宽松放行 P-3）
    stats_data = modules.get("stats")

    ctx: Mapping[str, object] = {"stats_data": stats_data}
    for i, entry in enumerate(data):
        _check_job_entry(report, entry, i, ctx)


__all__ = [
    "GROWTH_LIMITS",
    "TRANSFORM_REQUIRED_KEYS",
    "STATE_POLICY_KEYS",
    "TOP_REQUIRED_KEYS",
    "validate_jobs",
]
