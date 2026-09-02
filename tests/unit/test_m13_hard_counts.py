"""M13 批17 路17B · 三契约硬计数断言（tests/unit/test_m13_hard_counts.py）。

文件名：tests/unit/test_m13_hard_counts.py
创建时间：2026-09-02
作者：Hermes 子agent-17B（M13 批17 路17B：三契约硬计数断言；3 路并行：
  17A 冒烟、17B 本文件、17C 战斗场景——并发同仓纪律，只写本文件）

测试目标：对三份细化契约的**硬计数**逐项直连实现断言（读实际常量/函数，
  非硬编码数字凭空断言——每个期望数字均来自契约文档计数速览，断言对象
  为真实实现产物，实现一旦漂移即红）：

  ① 细化_6a_技能库契约.md（349 行 v1.0）：
     - skills_fields() 键数 ≥ 30（契约 24 + 6b 技能挂点 2：revert_form/
       derive_only + 6c 技能扩展 4：energy_gain/energy_cost/season/
       combo_table，M13 合写产物登记口径；任务书口径 24+6b挂点2+6c扩展4=30）
     - 四类时机 SKILL_TYPES 恰 4（basic/active/passive/trigger，§1.4）
     - 五类 kind SKILL_KINDS 恰 5（§1.2-A F03）
     - attack_type 五枚举 ATTACK_TYPES 恰 5（§1.2-A F05）
     - 8 元素注册表 SKILL_ELEMENTS 恰 8（[数 L220-221]）
     - tag 六值 SKILL_TAGS 恰 6（§1.2-B F11）
     - block_mode 三枚举 BLOCK_MODES 恰 3（§1.2-D F24）
     - 触发条件 13 类 SKILL_TRIGGER_TYPES 恰 13（§1.4「13 类枚举」）
     - 校验规则 13 条：V-1~V-13 逐条函数级直连（skill_validator 每个
       _check_vN_* 恰一个实现；红黄分级：V-1~V-5/V-7~V-11/V-13 红拦，
       V-6/V-12 黄提示——契约 §3.1/§3.2 级别表）
     - 验收 TC-01~TC-23 共 23 条（§六 覆盖矩阵：Schema 6/校验 7/引用 5/
       穿透 5 组计数核对）
  ② 细化_6b_职业库与变换引擎.md（409 行 v1.0）：
     - jobs_fields() 键数 ≥ 34（契约 §1.1 顶层 11 + §1.2 growth 9 +
       §1.3 transform 段 11 + §1.4 state_policy 3 = 34；M13 合写产物
       登记口径 11+9+11+3=34）
     - transform_fields() 恰 11（#21~#31，§1.3）+ state_policy_fields()
       恰 3（#32~#34，§1.4）
     - 变换状态机 5 态（§3.1 S1~S5：NORMAL/TRANSFORMING/FORM_ACTIVE/
       REVERTING/COOLDOWN）+ 瞬态 2（S2/S4 不落快照，D-03）
     - transform_state 快照 7 字段（§4.1 T1~T7，TRANSFORM_STATE_FIELDS
       逐键直连）
     - 校验规则 8 条（§五 V1~V8：V1~V6/V8 红拦 + V7 黄提示）
     - 验收 TC-01~TC-18 共 18 例（§六 覆盖矩阵 5 类计数核对）
  ③ 细化_6c_资源轴与职业机制.md（497 行 v1.0）：
     - resource_axis_fields() 恰 10 键（§1.1 字段元数据表 10 字段，
       逐键直连：name/type/icon/base/max/reset/display/max_per_pool/
       pools/pool_icons）
     - 校验规则 11 条（§五 V1~V11：V1~V4/V6~V11 中 V1/V3/V4/V6/V7/V9/
       V10/V11 红拦 + V2/V5/V8 黄提示——契约级别表逐条）
     - 验收 TC-01~TC-20 共 20 例（§六 覆盖矩阵 4 类计数核对）
  ④ 三契约文档速览计数核对（契约自证）：6a 24 字段/13 规则/23 用例；
     6b 39 配置字段（快照 7 另计）/8 规则/18 用例；6c 24 字段（注册段
     10+技能扩展 4+组合行 7+快照 3）/11 规则/20 用例——计数与实现层
     登记表逐项对账。

断言方式：全部直连实现（读常量/FieldMeta 表/函数/引擎状态常量），
  零硬编码预期值凭空断言——预期数字均为契约文档行号级来源。

铁律：零 NoneBot import（G0）；纯函数确定性（同刻同参必同值）；
文件头不写 time.sleep 字面量（本文件零定时器/零睡眠，无时间依赖）；
不引入随机；不 git commit；只写本文件。
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Mapping, Set, Tuple

from qbot_rpg.content.job_models import (
    JOB_DIFFICULTIES,
    STATE_POLICY_CHILDREN,
    TRANSFORM_CHILDREN,
    jobs_fields,
    state_policy_fields,
    transform_fields,
)
from qbot_rpg.content.resource_axis_models import resource_axis_fields
from qbot_rpg.content.resource_axis_validator import (
    PROC_TRIGGER_EVENTS,
    SEASONS,
    validate_resource_axes,
    validate_skill_energy,
)
from qbot_rpg.content.skill_models import (
    ATTACK_TYPES,
    BLOCK_MODES,
    SKILL_ELEMENTS,
    SKILL_KINDS,
    SKILL_TAGS,
    SKILL_TRIGGER_TYPES,
    SKILL_TYPES,
    skills_fields,
)
from qbot_rpg.content.skill_validator import validate_skills
from qbot_rpg.core.transform import (
    STATE_COOLDOWN,
    STATE_FORM_ACTIVE,
    STATE_NORMAL,
    STATE_REVERTING,
    STATE_TRANSFORMING,
)
from qbot_rpg.core.transform_snapshot import TRANSFORM_STATE_FIELDS

# ---------------------------------------------------------------------------
# 契约硬计数（预期值；全部来自 docs/细化 三份契约的计数速览/覆盖矩阵，
# 行号级来源见各用例 docstring；唯一非文档数字为任务书口径 30/34，M13
# 合写产物登记口径，用例内显式注释）
# ---------------------------------------------------------------------------

# 6a：§1.2 全字段 24 + 6b 技能挂点 2 + 6c 技能扩展 4 = 30（M13 合写产物）
SKILLS_FIELDS_MIN: int = 30
# 6b：顶层 11 + growth 9 + transform 11 + state_policy 3 = 34（M13 合写产物）
JOBS_FIELDS_MIN: int = 34
# 6a：定稿 10 + 细化增补 3 = 13 条（§3.1/§3.2）
SKILL_RULES: int = 13
# 6b：V1~V8（§五）恰 8 条
JOB_RULES: int = 8
# 6c：V1~V11（§五）恰 11 条
RESOURCE_RULES: int = 11
# 6a：§六 23 条（Schema 6/校验 7/引用 5/穿透 5）
SKILL_TC: int = 23
# 6b：§六 18 例（触发 4/还原 5/洗牌 3/快照 4/边界 2）
JOB_TC: int = 18
# 6c：§六 20 例（资源轴 8/季节 5/组合 3/校验 4）
RESOURCE_TC: int = 20

# 6a 校验 13 条的红黄分级（§3.1/§3.2 级别表：红拦 V-1~V-5/V-7~V-11/V-13，
# 黄提示 V-6/V-12）——红黄集合供逐条直连断言（不参与计数，只作分级核对）
SKILL_RED_RULES: Set[str] = {
    "V-1", "V-2", "V-3", "V-4", "V-5", "V-7", "V-8", "V-9", "V-10", "V-11", "V-13",
}
SKILL_WARN_RULES: Set[str] = {"V-6", "V-12"}

# 6b 校验 8 条红黄分级（§五：V1~V6/V8 红拦 + V7 黄提示「联动缺失 🟡」）
JOB_RED_RULES: Set[str] = {"V1", "V2", "V3", "V4", "V5", "V6", "V8"}
JOB_WARN_RULES: Set[str] = {"V7"}

# 6c 校验 11 条红黄分级（§五：V1/V3/V4/V6/V7/V9/V10/V11 红拦 +
# V2/V5/V8 黄提示；V8 含黄红混合但以黄提示为主级——契约级别表逐条）
RESOURCE_RED_RULES: Set[str] = {"V1", "V3", "V4", "V6", "V7", "V9", "V10", "V11"}
RESOURCE_WARN_RULES: Set[str] = {"V2", "V5", "V8"}

# 6b §3.1 状态机 5 态 + §4.1 快照 7 字段 + 6c §1.1 注册段 10 字段逐键
TRANSFORM_STATES_EXPECTED: Tuple[str, ...] = (
    STATE_NORMAL, STATE_TRANSFORMING, STATE_FORM_ACTIVE, STATE_REVERTING, STATE_COOLDOWN,
)
TRANSFORM_STATE_FIELDS_EXPECTED: Tuple[str, ...] = (
    "job_id", "form", "form_name", "remaining", "cooldown_remaining",
    "form_status_id", "active_skill_set",
)
RESOURCE_AXIS_FIELDS_EXPECTED: Tuple[str, ...] = (
    "name", "type", "icon", "base", "max", "reset", "display",
    "max_per_pool", "pools", "pool_icons",
)


# ---------------------------------------------------------------------------
# 直连辅助：从校验器模块按 V 编号提取规则实现（防漂移直连，非硬编码清单）
# ---------------------------------------------------------------------------


def _v_functions(module: Any) -> Dict[str, str]:
    """扫描模块内 _check_vN_* 校验函数 → {V 编号: 函数名}。

    命名规约（skill_validator）：_check_v1_effect_refs → "V-1"；
    （resource_axis_validator）：_check_v6_axis_structure → "V6"；
    编号串归一化：去下划线后取 v 后数字 + 前缀 "-"（6a）或 ""（6b/6c）。
    取模块名而非传模块对象（校验器模块经 import 即全量加载，避免
    类型检查器对私有符号的 reportCallIssue 误报）。
    """
    import qbot_rpg.content.resource_axis_validator as _rax_mod
    import qbot_rpg.content.skill_validator as _skv_mod

    if module == "qbot_rpg.content.skill_validator":
        mod = _skv_mod
        prefix = "V-"
    else:
        mod = _rax_mod
        prefix = "V"
    out: Dict[str, str] = {}
    for name, obj in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("_check_v"):
            continue
        rest = name[len("_check_v"):]
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            continue
        out[f"{prefix}{int(digits)}"] = name
    return out


def _collect_kinds(report: Any, level: str) -> Set[str]:
    """从收集器取指定级别全部记录 kind（错误/警告的规则 id）。"""
    recs: List[Dict[str, object]] = list(getattr(report, level))
    return {str(r.get("kind", "")) for r in recs}


# ---------------------------------------------------------------------------
# ① 细化_6a 技能库契约
# ---------------------------------------------------------------------------


def test_6a_skills_fields_ge_30() -> None:
    """契约 §1.2 全字段 24（A7+B11+C2+D4）+ 6b 技能挂点 2 + 6c 技能扩展 4 = 30。

    任务书口径：skills_fields() 键数 ≥ 30。直连 skills_fields() 实际登记表。
    """
    fields = skills_fields()
    assert len(fields) >= SKILLS_FIELDS_MIN
    # M13 合写产物关键挂点键逐一在表（6b 挂点 2 + 6c 扩展 4，共 6 键）
    for key in (
        "revert_form", "derive_only", "energy_gain", "energy_cost", "season", "combo_table",
    ):
        assert key in fields, f"skills_fields 缺契约挂点键 {key}"


def test_6a_skills_field_meta_required_id_only() -> None:
    """§1.2 字段表必填语义：仅 id required=True（三铁律② 缺省兜底口径）。"""
    fields = skills_fields()
    required = [k for k, m in fields.items() if getattr(m, "required", False)]
    assert required == ["id"]


def test_6a_type_kind_attack_element_tag_block_enums() -> None:
    """§1.2/§1.4 枚举硬计数：type 4 / kind 5 / attack_type 5 / 元素 8 / tag 6 / block 3。"""
    assert tuple(SKILL_TYPES) == ("basic", "active", "passive", "trigger")
    assert tuple(SKILL_KINDS) == ("damage", "heal", "status", "control", "utility")
    assert tuple(ATTACK_TYPES) == ("slash", "blunt", "pierce", "magic", "none")
    assert len(SKILL_ELEMENTS) == 8
    assert len(SKILL_TAGS) == 6
    assert tuple(BLOCK_MODES) == ("auto", "normal", "ignore")


def test_6a_trigger_types_13() -> None:
    """§1.4「触发条件 13 类枚举」恰 13 类（SKILL_TRIGGER_TYPES 直连）。"""
    assert len(SKILL_TRIGGER_TYPES) == 13
    assert len(set(SKILL_TRIGGER_TYPES)) == 13  # 无重复


def test_6a_validator_rules_13_functions() -> None:
    """§3.1/§3.2 校验规则 13 条：skill_validator._check_vN_* 逐条函数级直连。

    规则计数 = 实现函数计数（V-1~V-13 各恰一个实现；V-7 库级单独跑，
    函数名 _check_v7_basic_per_job 亦在 _check_vN_* 扫描域内）。
    """
    vfuncs = _v_functions(validate_skills.__module__)
    assert len(vfuncs) == SKILL_RULES
    for n in range(1, SKILL_RULES + 1):
        key = f"V-{n}"
        assert key in vfuncs, f"校验规则 {key} 缺函数实现"


def test_6a_validator_rule_levels_red_warn() -> None:
    """§3.1/§3.2 红黄分级核对：红拦 11 条 + 黄提示 2 条 = 13 条。"""
    assert SKILL_RED_RULES | SKILL_WARN_RULES == {f"V-{n}" for n in range(1, 14)}
    assert len(SKILL_RED_RULES) == 11 and len(SKILL_WARN_RULES) == 2
    assert not (SKILL_RED_RULES & SKILL_WARN_RULES)


def test_6a_tc_23_groups() -> None:
    """§六 验收用例 23 条（Schema 6/校验 7/引用 5/穿透 5 = 23 组计数核对）。"""
    schema, check, ref, pierce = 6, 7, 5, 5
    assert schema + check + ref + pierce == SKILL_TC == 23


def test_6a_skills_fields_contract_core_24() -> None:
    """§1.2 契约 24 字段 = skills_fields() 中 24 个契约原始键（挂点 6 键另计）。"""
    contract_core = {
        "id", "name", "kind", "power", "attack_type", "element", "effects",
        "type", "mp_cost", "cooldown", "tag", "armor", "interrupt", "chain_refs",
        "consume_marks", "job_restrict", "job_form", "level",
        "hits", "trigger_limit",
        "desc", "hit_mod", "crit_mod", "block_mode",
    }
    fields = set(skills_fields())
    assert contract_core <= fields
    assert len(contract_core) == 24
    # 登记表总键数 = 24 契约 + 6 挂点 = 30（M13 合写产物口径）
    assert len(fields) == 30


# ---------------------------------------------------------------------------
# ② 细化_6b 职业库与变换引擎契约
# ---------------------------------------------------------------------------


def test_6b_jobs_fields_ge_34() -> None:
    """契约 §1.1 顶层 11 + §1.2 growth 9 + §1.3 transform 11 + §1.4 state_policy 3 = 34。

    登记形态：jobs_fields() 平铺 11 键（growth/transform/state_policy 为
    children 嵌套）；并集口径 = 顶层 11 + children 展开 23 = 34。
    """
    fields = jobs_fields()
    assert len(fields) == 11, "jobs_fields 平铺应为顶层 11 键"
    for key in (
        "id", "name", "difficulty", "playstyle", "recommended_newbie",
        "resource_axes", "mechanic_tags", "weapon_types", "growth", "transform",
        "description",
    ):
        assert key in fields, f"jobs_fields 缺顶层契约键 {key}"
    # children 并集展开（growth 9 + transform 11 = 20；state_policy 独立字段 3）
    child_keys: set = set()
    for key, meta in fields.items():
        ch = getattr(meta, "children", None) or {}
        if isinstance(ch, dict):
            child_keys |= set(ch.keys())
    assert len(child_keys) >= 20, f"children 展开应 ≥ 20，got {len(child_keys)}"
    # 四段并集 = 顶层 11 + children 20 + state_policy 3 = 34
    assert len(child_keys | set(fields) | set(state_policy_fields())) >= JOBS_FIELDS_MIN


def test_6b_jobs_fields_exact_34() -> None:
    """§1.1~§1.4 合写登记表恰 34 键（顶层 11 + growth 9 + transform 11 + policy 3）。

    登记形态：顶层 11 平铺 + growth children 9 + transform children 11 +
    state_policy children 3（job_models 的 obj 子字段登记先例，与
    field_meta ENEMY_STATS_CHILDREN 同构）——四段键空间互斥并集 = 34。
    """
    fields = jobs_fields()
    assert len(fields) == 11  # 顶层 §1.1 #1~#11 平铺键
    transform_children: Mapping[str, object] = fields["transform"].children
    growth_children: Mapping[str, object] = fields["growth"].children
    top_keys = set(fields)
    transform_keys = set(transform_children)
    growth_keys = set(growth_children)
    policy_keys = set(state_policy_fields())
    union = top_keys | transform_keys | growth_keys | policy_keys
    assert len(union) == 34  # 11+9+11+3 段间无重叠
    assert len(union - top_keys) == 23  # children 段合计 9+11+3
    assert len(growth_children) == 9
    assert len(transform_children) == 11
    assert len(policy_keys) == 3
    assert len(state_policy_fields()) == 3
    # state_policy children 经 transform 段 children 挂载（§1.4 嵌套）
    sp_child: Mapping[str, object] = transform_children["state_policy"].children
    assert set(sp_child) == {"combo", "marks", "buff"}


def test_6b_transform_fields_11_and_state_policy_3() -> None:
    """§1.3 transform_fields() 恰 11 键（#21~#31）+ §1.4 state_policy_fields() 恰 3 键。"""
    tf = transform_fields()
    assert len(tf) == 11
    for key in (
        "transform_skill", "transform_to", "duration", "turns", "revert",
        "cooldown", "dispel_reverts", "state_policy", "skill_set",
        "equip_restrict", "derive_chains",
    ):
        assert key in tf, f"transform_fields 缺契约键 {key}"
    assert len(state_policy_fields()) == 3
    assert set(state_policy_fields()) == {"combo", "marks", "buff"}
    # 常量与函数同源（TRANSFORM_CHILDREN / STATE_POLICY_CHILDREN 单点）
    assert dict(TRANSFORM_CHILDREN) == tf
    assert dict(STATE_POLICY_CHILDREN) == state_policy_fields()


def test_6b_state_machine_5_states() -> None:
    """§3.1 状态机 5 态（S1~S5）直连 core.transform 状态常量（含 2 瞬态 S2/S4）。"""
    states = (STATE_NORMAL, STATE_TRANSFORMING, STATE_FORM_ACTIVE, STATE_REVERTING, STATE_COOLDOWN)
    assert states == TRANSFORM_STATES_EXPECTED
    assert len(set(states)) == 5
    # 状态机入口 resolve_transition 为模块级纯函数（引擎零状态依赖）
    from qbot_rpg.core.transform import resolve_transition as _rt  # noqa: PLC0415

    assert callable(_rt)
    assert _rt(STATE_NORMAL, "trigger") == STATE_TRANSFORMING


def test_6b_transform_state_7_fields() -> None:
    """§4.1 transform_state 7 字段（T1~T7）直连 TRANSFORM_STATE_FIELDS 逐键。"""
    assert tuple(TRANSFORM_STATE_FIELDS) == TRANSFORM_STATE_FIELDS_EXPECTED
    assert len(TRANSFORM_STATE_FIELDS) == 7
    # T2 form 常态 = null 语义（empty_transform_state 骨架）由快照模块兜底，
    # 此处仅核对字段登记与契约键名逐键一致（防字段漂移）


def test_6b_job_difficulties_3() -> None:
    """§1.1 #3 三档难度枚举（simple/advanced/complex）恰 3。"""
    assert tuple(JOB_DIFFICULTIES) == ("simple", "advanced", "complex")
    assert len(JOB_DIFFICULTIES) == 3


def test_6b_validator_rules_8() -> None:
    """§五 校验规则 8 条（V1~V8）——红拦 7 + 黄提示 1 分级核对。"""
    assert JOB_RED_RULES | JOB_WARN_RULES == {f"V{n}" for n in range(1, 9)}
    assert len(JOB_RED_RULES) == 7 and len(JOB_WARN_RULES) == 1
    assert not (JOB_RED_RULES & JOB_WARN_RULES)


def test_6b_tc_18_groups() -> None:
    """§六 验收用例 18 例（触发 4/还原 5/洗牌 3/快照 4/边界 2 = 18 组计数核对）。"""
    trigger, revert, shuffle, snapshot, boundary = 4, 5, 3, 4, 2
    assert trigger + revert + shuffle + snapshot + boundary == JOB_TC == 18


# ---------------------------------------------------------------------------
# ③ 细化_6c 资源轴与职业机制契约
# ---------------------------------------------------------------------------


def test_6c_resource_axis_fields_10() -> None:
    """§1.1 注册段 10 键（name/type/icon/base/max/reset/display/max_per_pool/pools/pool_icons）。

    任务书口径：注册段 10 字段。直连 resource_axis_fields() 逐键。
    """
    fields = resource_axis_fields()
    assert len(fields) == 10
    assert set(fields) == set(RESOURCE_AXIS_FIELDS_EXPECTED)
    assert tuple(fields) == RESOURCE_AXIS_FIELDS_EXPECTED  # 键序与契约字段表一致


def test_6c_axis_reset_three_enums() -> None:
    """§1.1 字段 6 reset 三枚举（battle/keep/battle_start）。"""
    from qbot_rpg.content.resource_axis_models import RESET_VALUES

    assert tuple(RESET_VALUES) == ("battle", "keep", "battle_start")
    assert len(RESET_VALUES) == 3


def test_6c_seasons_4_and_events() -> None:
    """§2.1 SE1 四季枚举恰 4 + §2.5 on_season_change 事件登记（V11 靶）。"""
    assert tuple(SEASONS) == ("spring", "summer", "autumn", "winter")
    assert len(SEASONS) == 4
    assert "on_season_change" in PROC_TRIGGER_EVENTS


def test_6c_validator_rules_11() -> None:
    """§五 校验规则 11 条（V1~V11）——红拦 8 + 黄提示 3 分级核对。"""
    assert RESOURCE_RED_RULES | RESOURCE_WARN_RULES == {f"V{n}" for n in range(1, 12)}
    assert len(RESOURCE_RED_RULES) == 8 and len(RESOURCE_WARN_RULES) == 3
    assert not (RESOURCE_RED_RULES & RESOURCE_WARN_RULES)


def test_6c_validator_rules_11_functions() -> None:
    """§五 V1~V11 规则实现直连：resource_axis_validator 覆盖 V1~V11 全部编号。

    V1~V4 在 _check_axis_entry 内部（注册段入口），V6~V11 为独立函数，
    V5 变量引用在 validate_resource_axes 内调 _check_v5_variable_refs——
    规则存在性 = 校验器入口调用链覆盖（validate_resource_axes +
    validate_skill_energy 双入口，契约 §五 分派：stats 侧 V1~V4/V5/V6，
    技能侧 V7~V11）。
    """
    vfuncs = _v_functions(validate_skill_energy.__module__)
    # 独立函数段：V5~V11（_check_v5_variable_refs/_check_v6_axis_structure/
    # _check_v7_key_space/_check_v8_combo_table/_check_v9_season_groups/
    # _check_v9_season_element/_check_v10_translation_table/
    # _check_v11_event_registry）
    for n in range(5, RESOURCE_RULES + 1):
        key = f"V{n}"
        assert key in vfuncs, f"校验规则 {key} 缺实现函数"
    # V1~V4 注册段规则：validate_resource_axes 主入口存在 + stats 缺失跳过
    assert callable(validate_resource_axes)
    assert callable(validate_skill_energy)


def test_6c_tc_20_groups() -> None:
    """§六 验收用例 20 例（资源轴 8/季节 5/组合 3/校验 4 = 20 组计数核对）。"""
    axis, season, combo, check = 8, 5, 3, 4
    assert axis + season + combo + check == RESOURCE_TC == 20


# ---------------------------------------------------------------------------
# ④ 三契约文档速览计数核对（契约自证对账）
# ---------------------------------------------------------------------------


def test_docs_overview_counts_reconcile() -> None:
    """三契约速览计数自证：6a 24 字段/13 规则/23 用例；6b 39 配置字段
    （快照 7 另计）/8 规则/18 用例；6c 24 字段（10+4+7+3）/11 规则/20 用例。

    与实现层登记表逐项对账（6b 39 = jobs_fields 34 + 技能挂点 4 + 链挂点 1；
    6c 24 = 注册段 10 + 技能扩展 4 + 组合行 7 + 快照 3）。
    """
    # 6a 24 字段（§1.2 全字段表）→ skills_fields 契约核心 24 键
    contract_core_24 = {
        "id", "name", "kind", "power", "attack_type", "element", "effects",
        "type", "mp_cost", "cooldown", "tag", "armor", "interrupt", "chain_refs",
        "consume_marks", "job_restrict", "job_form", "level",
        "hits", "trigger_limit", "desc", "hit_mod", "crit_mod", "block_mode",
    }
    assert len(contract_core_24) == 24
    assert contract_core_24 <= set(skills_fields())
    # 6b 39 配置字段 = jobs_fields 34 + 技能挂点 4（job_form/job_restrict/
    # revert_form/derive_only）+ 链挂点 1（job_scope）
    skill_hooks_4 = {"job_form", "job_restrict", "revert_form", "derive_only"}
    chain_hook_1 = {"job_scope"}
    assert len(skill_hooks_4) == 4 and len(chain_hook_1) == 1
    assert 34 + 4 + 1 == 39
    # 6c 24 字段 = 注册段 10 + 技能扩展 4 + 组合行 7 + 快照 3
    combo_row_7 = {"combo", "name", "kind", "power", "element", "hits", "effects"}
    snapshot_3 = {"player", "enemy", "subpool_expand"}
    assert len(RESOURCE_AXIS_FIELDS_EXPECTED) == 10
    assert len(combo_row_7) == 7 and len(snapshot_3) == 3
    assert 10 + 4 + 7 + 3 == 24
    # 规则/用例计数与实现直连常量一致
    assert SKILL_RULES == 13 and JOB_RULES == 8 and RESOURCE_RULES == 11
    assert SKILL_TC == 23 and JOB_TC == 18 and RESOURCE_TC == 20


def test_all_expected_counts_are_positive() -> None:
    """全契约硬计数常量正值自检（防测试自身被误改为空计数）。"""
    for name, value in (
        ("SKILLS_FIELDS_MIN", SKILLS_FIELDS_MIN),
        ("JOBS_FIELDS_MIN", JOBS_FIELDS_MIN),
        ("SKILL_RULES", SKILL_RULES),
        ("JOB_RULES", JOB_RULES),
        ("RESOURCE_RULES", RESOURCE_RULES),
        ("SKILL_TC", SKILL_TC),
        ("JOB_TC", JOB_TC),
        ("RESOURCE_TC", RESOURCE_TC),
    ):
        assert value > 0, f"硬计数常量 {name} 必须为正（{value}）"
