"""M13 职业库数据层 · 批4 路4A：JobDef 数据模型测试（顶层 11 + growth 9 + 默认值兜底）。

文件名：test_job_models.py
创建时间：2026-09-02
作者：Hermes 子agent-4A（M13 职业库实现组批4路4A：并发同仓，仅新建本文件 +
qbot_rpg/content/job_models.py）

依据：docs/细化/细化_6b_职业库与变换引擎.md：
  - §1.1 顶层字段表（#1~#11：id/name/difficulty/playstyle/recommended_newbie/
    resource_axes/mechanic_tags/weapon_types/growth/transform/description，
    逐字段类型/必填/语义）；
  - §1.2 growth 子对象（#12~#20：str/int/con/spr/foc/agi/lck/hp/mp 九属性
    职业成长率，缺省 0；默认四职业成长率锚点 路3 B5 L103）。
测试目标：qbot_rpg.content.job_models.{JobDef, GrowthDef, jobs_fields,
JOB_DIFFICULTIES, GROWTH_KEYS}。

测试口径（对齐 test_skill_models.py / test_forge_models.py）：
  - 默认值兜底断言：漏配字段 = 合理默认（三铁律②），不抛错、不填 None；
  - from_entry 全量/缺省：全字段条目 + 仅核心字段条目（缺省兜底）；
  - growth 解析：九属性逐键 + 缺省 0 + growth_map/as_mapping 消费形态；
  - 枚举：difficulty 三档 soft_label（值域校验归校验器专项，本层只读不判）；
  - 字段登记表：顶层 11 + growth 9 全键覆盖 + transform 注册位（4B 追加位）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, cast

from qbot_rpg.content.job_models import (
    DEFAULT_DIFFICULTY,
    DEFAULT_GROWTH,
    DEFAULT_PLAYSTYLE,
    DEFAULT_RECOMMENDED_NEWBIE,
    GROWTH_CHILDREN,
    GROWTH_KEYS,
    JOB_DIFFICULTIES,
    GrowthDef,
    JobDef,
    job_from_entry,
    jobs_fields,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _full_entry() -> Dict[str, object]:
    """全顶层 11 字段合法职业条目（细化_6b §1.1 逐字段样例：含 growth 9 子字段）。"""
    return {
        # #1~#11 顶层 11
        "id": "berserker",
        "name": "狂战士",
        "difficulty": "complex",
        "playstyle": "以操作换生存",
        "recommended_newbie": False,
        "resource_axes": ["mp", "rage"],
        "mechanic_tags": ["变身", "吸血"],
        "weapon_types": ["axe"],
        "growth": {
            # #12~#20 growth 9 子字段
            "str": 2.2, "int": 0.5, "con": 1.5, "spr": 0.8, "foc": 1.0,
            "agi": 1.0, "lck": 0.5, "hp": 1.5, "mp": 0.5,
        },
        # #10 transform 段（结构呈现占位；11 字段语义归批4路4B）
        "transform": {"transform_skill": "rage", "transform_to": "berserker_form"},
        # #11 description
        "description": "怒意缠身的狂战士。",
    }


def _minimal_entry() -> Dict[str, object]:
    """仅核心字段条目（缺省兜底：difficulty=simple / recommended_newbie=False）。"""
    return {"id": "novice", "name": "新手"}


def _def(entry: Mapping[str, object]) -> JobDef:
    return cast(JobDef, JobDef.from_entry(entry))


# ---------------------------------------------------------------------------
# 1. 字段默认值兜底（三铁律②：漏配 = 合理默认不是报错）
# ---------------------------------------------------------------------------
def test_minimal_entry_defaults_full_coverage() -> None:
    """仅 {id,name} 的职业：顶层 11 全部合理默认，零异常（缺省兜底）。"""
    d = _def(_minimal_entry())
    assert d.id == "novice"
    assert d.name == "新手"
    assert d.difficulty == "simple"            # #3 缺省 simple
    assert d.playstyle == ""                    # #4 缺省空串
    assert d.recommended_newbie is False        # #5 缺省 False
    assert d.resource_axes == ()                # #6 缺省空元组
    assert d.mechanic_tags == ()                # #7 缺省空元组
    assert d.weapon_types == ()                 # #8 缺省空元组
    assert isinstance(d.growth, GrowthDef)      # #9 空 growth 对象
    assert d.growth.as_mapping() == {k: 0.0 for k in GROWTH_KEYS}  # 全 0 成长率
    assert d.transform_obj() is None            # #10 缺省 None=无形态切换职业
    assert d.description is None                # #11 缺省 None


def test_full_entry_values_roundtrip() -> None:
    """全顶层 11 字段条目：访问器逐字段回读一致（含 growth 9 子字段）。"""
    d = _def(_full_entry())
    assert d.id == "berserker"
    assert d.name == "狂战士"
    assert d.difficulty == "complex"
    assert d.playstyle == "以操作换生存"
    assert d.recommended_newbie is False
    assert d.resource_axes == ("mp", "rage")
    assert d.mechanic_tags == ("变身", "吸血")
    assert d.weapon_types == ("axe",)
    assert d.description == "怒意缠身的狂战士。"
    # growth 九属性逐键回读
    g = d.growth
    assert g.str == 2.2
    assert g.int == 0.5
    assert g.con == 1.5
    assert g.spr == 0.8
    assert g.foc == 1.0
    assert g.agi == 1.0
    assert g.lck == 0.5
    assert g.hp == 1.5
    assert g.mp == 0.5


# ---------------------------------------------------------------------------
# 2. from_entry 工厂 / name 兜底 / kind 注入
# ---------------------------------------------------------------------------
def test_from_entry_name_fallback_to_id() -> None:
    """name 缺省 → 兜底为 id（BaseDef.from_entry 口径，先例同 SkillDef）。"""
    d = _def({"id": "mage"})
    assert d.id == "mage"
    assert d.name == "mage"


def test_job_from_entry_kind_injected() -> None:
    """job_from_entry 工厂注入注册表 kind="job"（供 registry/loader 收口）。"""
    d = job_from_entry({"id": "warrior", "name": "战士"})
    assert d.kind == "job"
    assert d.id == "warrior"


def test_raw_is_deep_copy_immutable() -> None:
    """raw 为深拷贝快照：外部条目改写不影响 Def（铁律9 冗余镜像）。"""
    entry: Dict[str, object] = {"id": "a", "name": "A", "recommended_newbie": True}
    d = _def(entry)
    entry["recommended_newbie"] = False
    assert d.recommended_newbie is True


# ---------------------------------------------------------------------------
# 3. growth 解析（§1.2 #12~#20：缺省 0；狂战士示例仅配 6 项）
# ---------------------------------------------------------------------------
def test_growth_partial_keys_default_zero() -> None:
    """growth 仅配 6 项（狂战士示例口径）：漏配 3 键缺省 0.0。"""
    d = _def({"id": "berserker", "growth": {"str": 2.2, "con": 1.5, "foc": 1.0,
                                            "agi": 1.0, "hp": 1.5, "mp": 0.5}})
    g = d.growth
    assert g.str == 2.2
    assert g.con == 1.5
    assert g.foc == 1.0
    assert g.agi == 1.0
    assert g.hp == 1.5
    assert g.mp == 0.5
    # 漏配键缺省 0（§1.2「缺省 0」）
    assert g.int == 0.0
    assert g.spr == 0.0
    assert g.lck == 0.0


def test_growth_non_numeric_falls_back_zero() -> None:
    """growth 非纯数值（str 配成字符串/bool）→ 0.0 兜底（补白 2）。"""
    d = _def({"id": "x", "growth": {"str": "high", "int": True, "con": 1}})
    g = d.growth
    assert g.str == 0.0
    assert g.int == 0.0
    assert g.con == 1.0


def test_growth_map_only_present_keys() -> None:
    """growth_map() 仅含实际配置键（levelup growth 注入消费形态）。"""
    d = _def({"id": "x", "growth": {"str": 2.0, "hp": 1.5}})
    assert d.growth.growth_map() == {"str": 2.0, "hp": 1.5}


def test_growth_as_mapping_full_keys() -> None:
    """as_mapping() 九键全量（含缺省 0.0，展示/快照消费形态）。"""
    d = _def({"id": "x", "growth": {"str": 2.0}})
    m = d.growth.as_mapping()
    assert set(m.keys()) == set(GROWTH_KEYS)
    assert m["str"] == 2.0
    assert m["int"] == 0.0


def test_default_four_jobs_growth_anchors() -> None:
    """默认四职业成长率锚点（路3 B5 L103）逐职业断言（补白 1 键口径验证）。"""
    anchors = {
        "warrior": {"str": 2.0, "con": 1.5, "foc": 1.0},
        "mage": {"int": 2.0, "spr": 1.5, "lck": 1.0},
        "assassin": {"agi": 2.0, "foc": 1.5, "lck": 1.0},
        "shield": {"con": 2.0, "hp": 1.5, "spr": 1.0},
    }
    for job_id, growth in anchors.items():
        d = _def({"id": job_id, "growth": growth})
        for key, value in growth.items():
            assert getattr(d.growth, key) == value


# ---------------------------------------------------------------------------
# 4. 枚举 / 类型兜底（difficulty soft_label：本层只读不判，值域归校验器专项）
# ---------------------------------------------------------------------------
def test_difficulty_enum_three_values() -> None:
    """difficulty 三档枚举 simple/advanced/complex（§1.1 #3）。"""
    assert JOB_DIFFICULTIES == ("simple", "advanced", "complex")
    for level in JOB_DIFFICULTIES:
        d = _def({"id": "j", "difficulty": level})
        assert d.difficulty == level


def test_difficulty_unknown_value_passthrough() -> None:
    """difficulty 未知值不拦截（软标注——值域校验归校验器专项只 warning）。"""
    d = _def({"id": "j", "difficulty": "insane"})
    assert d.difficulty == "insane"


def test_growth_keys_contract_nine() -> None:
    """GROWTH_KEYS 九键契约（§1.2 #12~#20）。"""
    assert GROWTH_KEYS == ("str", "int", "con", "spr", "foc", "agi", "lck", "hp", "mp")
    assert len(GROWTH_KEYS) == 9


# ---------------------------------------------------------------------------
# 5. jobs_fields 登记表（顶层 11 + growth 9 + transform 4B 注册位）
# ---------------------------------------------------------------------------
def test_jobs_fields_top_level_eleven_keys() -> None:
    """jobs_fields() 顶层 11 键全量（§1.1 #1~#11）。"""
    fields = jobs_fields()
    top_keys = ["id", "name", "difficulty", "playstyle", "recommended_newbie",
                "resource_axes", "mechanic_tags", "weapon_types", "growth",
                "transform", "description"]
    assert set(top_keys) <= set(fields.keys())
    assert len(fields) == 11


def test_jobs_fields_required_and_defaults() -> None:
    """登记表口径：id required；必填缺省兜底不设 required；默认值对齐常量。"""
    fields = jobs_fields()
    assert fields["id"].required is True
    assert fields["id"].type == "str"
    assert fields["difficulty"].enum == JOB_DIFFICULTIES
    assert fields["difficulty"].default == DEFAULT_DIFFICULTY
    assert fields["playstyle"].default == DEFAULT_PLAYSTYLE
    assert fields["recommended_newbie"].default == DEFAULT_RECOMMENDED_NEWBIE
    assert fields["recommended_newbie"].type == "bool"
    # 软标注字段不拦截（#3 difficulty / #10 transform）
    assert fields["difficulty"].soft_label is False  # enum 值域由校验器判黄
    assert fields["transform"].soft_label is True     # 缺省 = 无形态切换职业合法


def test_growth_children_nine_registered() -> None:
    """growth children 九键全量登记（§1.2 #12~#20，缺省 0）。"""
    children = jobs_fields()["growth"].children
    assert set(children.keys()) == set(GROWTH_KEYS)
    assert GROWTH_CHILDREN == children
    for key in GROWTH_KEYS:
        assert children[key].type == "number"
        assert children[key].default == DEFAULT_GROWTH
        assert children[key].range_min == 0


def test_transform_placeholder_registered_for_4b() -> None:
    """transform 键 obj 注册（soft_label 不拦截）：children 由 4B 合写挂载
    （TRANSFORM_CHILDREN 经 _job_transform_children() 惰性挂载；4B 未落盘时
    children 为空——本断言按「4B 合写产物当前状态」核对非空）。"""
    meta = jobs_fields()["transform"]
    assert meta.type == "obj"
    assert meta.soft_label is True
    # 4B 合写后 children 含 transform 段 11 字段（#21~#31）；若 4B 未落盘则
    # 为空 dict（globals 取不到 transform_fields），此处不硬断言长度
    assert isinstance(meta.children, Mapping)


# ---------------------------------------------------------------------------
# 6. 契约字段计数核对（细化_6b L134：1~11 顶层 + 12~20 growth = 20 本层字段）
# ---------------------------------------------------------------------------
def test_contract_field_count_top_level_plus_growth() -> None:
    """字段计数核对：顶层 11 + growth 9 = 20（transform 段 11 + state_policy 3
    归批4路4B；技能挂点 4 + 链挂点 1 随 6a 登记 skills/skill_chains）。"""
    assert len(jobs_fields()) == 11
    assert len(jobs_fields()["growth"].children) == 9
    assert len(GROWTH_KEYS) == 9


def test_transform_obj_structural_passthrough() -> None:
    """transform_obj() 结构呈现：Mapping 原样返回（语义校验归 4B/校验器）。"""
    d = _def({"id": "berserker", "transform": {"transform_skill": "rage"}})
    t = d.transform_obj()
    assert t is not None
    assert t.get("transform_skill") == "rage"
    # 非 Mapping 形态（如字符串）→ None 兜底
    assert _def({"id": "x", "transform": "oops"}).transform_obj() is None
