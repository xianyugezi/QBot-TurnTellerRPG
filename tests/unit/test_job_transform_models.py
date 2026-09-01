"""M13 批4 路4B · 6b 职业库 transform 段数据模型测试（transform 段 11 字段 +
state_policy 3 字段：解析 / 默认值兜底 / 枚举 / 登记表）。

文件名：test_job_transform_models.py
创建时间：2026-09-02
作者：Hermes 子agent-4B（M13 职业库实现组批4路4B：并发同仓，仅新建本文件 +
qbot_rpg/content/job_models.py）

依据：docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
  - §1.3 transform 段 11 字段（#21~31 逐字段类型/必填/默认值）；
  - §1.4 state_policy 子对象 3 字段（#32~34 枚举值域收敛 {clear, keep}，
    默认 clear/keep/keep，V5 红拦）；
  - §0.3 ADR（D-01 单例 transform 段 / D-04 battle+revert 红拦）。
测试目标：qbot_rpg.content.job_models.{TransformDef, StatePolicyDef,
transform_fields, state_policy_fields, 枚举常量}。

测试口径（对齐 test_skill_models.py）：
  - 默认值兜底断言：漏配字段 = 合理默认（三铁律②），不抛错、不填 None；
  - from_entry 全量/缺省：全 11 字段条目 + 仅必填字段条目 + 空条目；
  - 枚举断言：duration 两枚举 / state_policy 三键 clear|keep 二值收敛；
  - 防御性读取：类型异常/负值/非法枚举外值 → 合理默认，不抛错；
  - 登记表断言：transform_fields() 恰 11 键 + state_policy_fields() 恰 3 键，
    枚举/默认/必填与契约一致。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, cast

from qbot_rpg.content.job_models import (
    DEFAULT_COOLDOWN,
    DEFAULT_DISPEL_REVERTS,
    DEFAULT_DURATION,
    DEFAULT_REVERT,
    DEFAULT_SKILL_SET,
    DEFAULT_STATE_POLICY_BUFF,
    DEFAULT_STATE_POLICY_COMBO,
    DEFAULT_STATE_POLICY_MARKS,
    DEFAULT_TRANSFORM_SKILL,
    DEFAULT_TRANSFORM_TO,
    DEFAULT_TURNS,
    STATE_POLICY_VALUES,
    TRANSFORM_DURATION_VALUES,
    StatePolicyDef,
    TransformDef,
    state_policy_fields,
    transform_fields,
)

# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _full_transform_entry() -> Dict[str, object]:
    """全 11 字段合法 transform 段（细化_6b §1.3 逐字段样例：狂战士 berserker 形态）。"""
    return {
        "transform_skill": "berserk",
        "transform_to": "berserker_form",
        "duration": "turns",
        "turns": 4,
        "revert": True,
        "cooldown": 5,
        "dispel_reverts": True,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
        "equip_restrict": ["two_hand_axe"],
        "derive_chains": ["chain_rage"],
    }


def _full_policy_entry() -> Dict[str, object]:
    """state_policy 三键全配条目（§1.4 枚举值域 {clear, keep}）。"""
    return {"combo": "clear", "marks": "keep", "buff": "clear"}


def _transform_def(entry: Mapping[str, object]) -> TransformDef:
    return cast(TransformDef, TransformDef.from_entry(entry))


def _policy_def(entry: Mapping[str, object]) -> StatePolicyDef:
    return StatePolicyDef.from_entry(entry)


# ---------------------------------------------------------------------------
# 1. TransformDef 默认值兜底（三铁律②：漏配 = 合理默认不是报错）
# ---------------------------------------------------------------------------
def test_transform_empty_entry_defaults_full_coverage() -> None:
    """空 transform 段：11 字段全部合理默认，零异常（必填判定归 V1~V8 专项）。"""
    d = _transform_def({})
    assert d.transform_skill == ""          # #21 空串 = 未配置
    assert d.transform_to == ""             # #22 空串 = 未配置
    assert d.duration == "turns"            # #23 兜底 turns（P-1）
    assert d.turns == 0                     # #24 0 = 未配置哨兵（P-2）
    assert d.revert is False                # #25 兜底 false
    assert d.cooldown == 5                  # #26 默认 5
    assert d.dispel_reverts is True         # #27 默认 true
    assert d.state_policy == {}             # #28 缺省空对象
    assert d.skill_set == ""                # #29 空串 = 未配置
    assert d.equip_restrict == ()           # #30 空 = 不限制
    assert d.derive_chains == ()            # #31 缺省空列表


def test_transform_required_only_entry_defaults() -> None:
    """仅必填 7 字段（不含可选/条件字段）：可选字段合理默认，零异常。"""
    d = _transform_def({
        "transform_skill": "berserk",
        "transform_to": "berserker_form",
        "duration": "turns",
        "revert": False,
        "cooldown": 5,
        "state_policy": {},
        "skill_set": "transform_skills",
    })
    assert d.transform_skill == "berserk"
    assert d.transform_to == "berserker_form"
    assert d.duration == "turns"
    assert d.revert is False
    assert d.cooldown == 5
    assert d.skill_set == "transform_skills"
    assert d.turns == 0                     # 条件字段未配 = 哨兵
    assert d.dispel_reverts is True         # 可选字段默认 true
    assert d.equip_restrict == ()
    assert d.derive_chains == ()


def test_transform_full_entry_parsed_exact() -> None:
    """全 11 字段条目：逐字段精确解析（§1.3 #21~31）。"""
    d = _transform_def(_full_transform_entry())
    assert d.transform_skill == "berserk"
    assert d.transform_to == "berserker_form"
    assert d.duration == "turns"
    assert d.turns == 4
    assert d.revert is True
    assert d.cooldown == 5
    assert d.dispel_reverts is True
    assert d.state_policy == {"combo": "clear", "marks": "keep", "buff": "keep"}
    assert d.skill_set == "transform_skills"
    assert d.equip_restrict == ("two_hand_axe",)
    assert d.derive_chains == ("chain_rage",)


def test_transform_default_constants_aligned() -> None:
    """默认常量与契约字段表一致（§1.3 逐字段默认值）。"""
    assert DEFAULT_DURATION == "turns"
    assert DEFAULT_TURNS == 0
    assert DEFAULT_REVERT is False
    assert DEFAULT_COOLDOWN == 5
    assert DEFAULT_DISPEL_REVERTS is True
    assert DEFAULT_TRANSFORM_SKILL == ""
    assert DEFAULT_TRANSFORM_TO == ""
    assert DEFAULT_SKILL_SET == ""


def test_transform_wrong_type_values_fall_back() -> None:
    """异常值类型兜底：非数值/非字符串/非布尔/非列表 → 合理默认，不抛错。"""
    d = _transform_def({
        "transform_skill": 3, "transform_to": ["x"], "duration": 7,
        "turns": "四", "revert": "yes", "cooldown": None,
        "dispel_reverts": 1, "state_policy": "no",
        "skill_set": {"a": 1}, "equip_restrict": "not_a_list",
        "derive_chains": {"b": 2},
    })
    assert d.transform_skill == ""
    assert d.transform_to == ""
    assert d.duration == "turns"
    assert d.turns == 0
    assert d.revert is False
    assert d.cooldown == 5
    assert d.dispel_reverts is True
    assert d.state_policy == {}
    assert d.skill_set == ""
    assert d.equip_restrict == ()
    assert d.derive_chains == ()


def test_transform_negative_cooldown_clamped() -> None:
    """cooldown 负值钳 0（P-3：冷却 ≥0，从「触发」起算）。"""
    for bad in (-1, -99):
        d = _transform_def({"id": "t", "name": "t", "cooldown": bad})
        assert d.cooldown == 0


def test_transform_turns_nonpositive_sentinel() -> None:
    """turns ≤0 / 非整数 → 0 哨兵（P-2：duration=turns 时须 >0，强制归专项）。"""
    for bad in (0, -3, 2.5, "4"):
        d = _transform_def({"id": "t", "name": "t", "turns": bad})
        assert d.turns == 0


def test_transform_duration_enum_values() -> None:
    """duration 两枚举 turns/battle 逐一解析（§1.3 #23）。"""
    for v in TRANSFORM_DURATION_VALUES:
        d = _transform_def({"id": "t", "name": "t", "duration": v})
        assert d.duration == v


def test_transform_dispel_reverts_false_parsed() -> None:
    """dispel_reverts=false 显式解析（形态免疫驱散，[狂战士 L301]）。"""
    d = _transform_def({"id": "t", "name": "t", "dispel_reverts": False})
    assert d.dispel_reverts is False


# ---------------------------------------------------------------------------
# 2. StatePolicyDef（§1.4 #32~34：三键枚举 + 默认值兜底）
# ---------------------------------------------------------------------------
def test_state_policy_full_entry_parsed_exact() -> None:
    """state_policy 三键全配：逐键精确解析（combo/marks/buff）。"""
    p = _policy_def(_full_policy_entry())
    assert p.combo == "clear"
    assert p.marks == "keep"
    assert p.buff == "clear"


def test_state_policy_empty_entry_defaults() -> None:
    """空 state_policy：三键全部合理默认（clear/keep/keep），零异常。"""
    p = _policy_def({})
    assert p.combo == "clear"   # #32 默认 clear
    assert p.marks == "keep"    # #33 默认 keep
    assert p.buff == "keep"     # #34 默认 keep


def test_state_policy_default_constants_aligned() -> None:
    """state_policy 默认常量与契约 §1.4 一致。"""
    assert DEFAULT_STATE_POLICY_COMBO == "clear"
    assert DEFAULT_STATE_POLICY_MARKS == "keep"
    assert DEFAULT_STATE_POLICY_BUFF == "keep"
    assert STATE_POLICY_VALUES == ("clear", "keep")


def test_state_policy_wrong_type_values_fall_back() -> None:
    """异常值类型兜底：非字符串/枚举外值 → 合理默认，不抛错（V5 红拦归专项）。"""
    p = _policy_def({"combo": 3, "marks": None, "buff": ["keep"]})
    assert p.combo == "clear"
    assert p.marks == "keep"
    assert p.buff == "keep"


def test_state_policy_all_enum_values_parsed() -> None:
    """三键全部枚举值逐一解析（值域收敛 {clear, keep} 二值，§1.4 注）。"""
    for key in ("combo", "marks", "buff"):
        for v in STATE_POLICY_VALUES:
            p = _policy_def({key: v})
            assert getattr(p, key) == v


def test_transform_state_policy_def_wiring() -> None:
    """TransformDef.state_policy_def() 接线：非 Mapping → 空策略；Mapping → 三键兜底。"""
    d_missing = _transform_def({})
    sp = d_missing.state_policy_def()
    assert isinstance(sp, StatePolicyDef)
    assert sp.combo == "clear" and sp.marks == "keep" and sp.buff == "keep"
    d_partial = _transform_def({"state_policy": {"combo": "keep"}})
    sp2 = d_partial.state_policy_def()
    assert sp2.combo == "keep"
    assert sp2.marks == "keep" and sp2.buff == "keep"


def test_state_policy_raw_deepcopy_isolation() -> None:
    """raw 为深拷贝快照：外部改原条目不影响 Def（BaseDef 契约，registry 共享安全）。"""
    entry: Dict[str, object] = _full_policy_entry()
    p = _policy_def(entry)
    entry["combo"] = "keep"
    entry["buff"] = "keep"
    assert p.combo == "clear"
    assert p.buff == "clear"


# ---------------------------------------------------------------------------
# 3. 字段登记表（transform_fields 11 键 / state_policy_fields 3 键）
# ---------------------------------------------------------------------------
def test_transform_fields_11_keys_exact() -> None:
    """transform_fields() 恰好 11 键（§1.3 #21~31），键名与契约一致。"""
    f = transform_fields()
    assert set(f.keys()) == {
        "transform_skill", "transform_to", "duration", "turns", "revert",
        "cooldown", "dispel_reverts", "state_policy", "skill_set",
        "equip_restrict", "derive_chains",
    }


def test_transform_fields_required_and_defaults() -> None:
    """transform_fields() 必填/默认/枚举与契约一致（供 field_meta 登记依据）。"""
    f = transform_fields()
    assert f["transform_skill"].required is True
    assert f["transform_skill"].ref_target == "skill"
    assert f["transform_to"].required is True
    assert f["duration"].enum == TRANSFORM_DURATION_VALUES
    assert f["duration"].default == "turns"
    assert f["revert"].required is True and f["revert"].default is False
    assert f["cooldown"].required is True
    assert f["cooldown"].default == 5 and f["cooldown"].range_min == 0
    assert f["dispel_reverts"].default is True
    assert f["state_policy"].required is True
    assert f["state_policy"].type == "obj"
    assert f["state_policy"].children is not None
    assert f["skill_set"].required is True
    assert f["equip_restrict"].element is not None
    assert f["derive_chains"].element is not None
    assert f["derive_chains"].element.ref_target == "skill_chain"


def test_state_policy_fields_3_keys_exact() -> None:
    """state_policy_fields() 恰好 3 键（§1.4 #32~34），键名与契约一致。"""
    f = state_policy_fields()
    assert set(f.keys()) == {"combo", "marks", "buff"}


def test_state_policy_fields_enum_and_defaults() -> None:
    """state_policy_fields() 三键枚举 {clear, keep} 与默认值一致（V5 红拦依据）。"""
    f = state_policy_fields()
    for key, default in (
        ("combo", "clear"),
        ("marks", "keep"),
        ("buff", "keep"),
    ):
        assert f[key].type == "enum"
        assert f[key].enum == STATE_POLICY_VALUES
        assert f[key].default == default


def test_transform_fields_children_wire_state_policy_fields() -> None:
    """transform_fields() 的 state_policy 子对象 children 与 state_policy_fields() 一致。"""
    f = transform_fields()
    sp_meta = f["state_policy"]
    assert sp_meta.children is not None
    assert set(sp_meta.children.keys()) == {"combo", "marks", "buff"}
    spf = state_policy_fields()
    for key in ("combo", "marks", "buff"):
        assert sp_meta.children[key].enum == spf[key].enum
        assert sp_meta.children[key].default == spf[key].default
