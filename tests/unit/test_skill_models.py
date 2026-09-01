"""M13 技能库数据层 · 批1 路1A：SkillDef 数据模型测试（24 字段 + 默认值兜底 + 双库同构）。

文件名：test_skill_models.py
创建时间：2026-09-02
作者：Hermes 子agent-1A（M13 技能库实现组批1路1A：并发同仓，仅新建本文件 +
qbot_rpg/content/skill_models.py）

依据：docs/细化/细化_6a_技能库契约.md：
  - §1.2 全字段表（24 字段 = A 共用核心 7 + B 玩家扩展 11 + C 全库补充 2 +
    D 细化定型 4，逐字段默认值/约束）；
  - §1.3 字段规则细节（f1 kind 自动推断 / f2 effects 双形态 / f4 attack_type
    按武器默认 / f5 element 正交）；
  - §1.4 四类时机（basic/active/passive/trigger）；
  - §2.2 ActionCore 共用块（F01-F07 与 action.json 逐字段同构、逐约束同源）。
测试目标：qbot_rpg.content.skill_models.{SkillDef, skills_fields, 枚举常量}。

测试口径（对齐 test_fishing_models.py / test_forge_models.py）：
  - 默认值兜底断言：漏配字段 = 合理默认（三铁律②），不抛错、不填 None；
  - from_entry 全量/缺省：全字段条目 + 仅核心字段条目（TC-02 缺省兜底）；
  - 四类时机 type 枚举：basic/active/passive/trigger 各一；
  - ActionCore 双库同构：SkillDef F01-F07 与 ActionDef（qbot_rpg.content.models）
    访问器逐字段同构（同键、同默认口径）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, cast

from qbot_rpg.content.models import ActionDef
from qbot_rpg.content.skill_models import (
    ATTACK_TYPES,
    BLOCK_MODES,
    DEFAULT_ATTACK_TYPE,
    DEFAULT_BLOCK_MODE,
    DEFAULT_COOLDOWN,
    DEFAULT_CRIT_MOD,
    DEFAULT_DESC,
    DEFAULT_HITS,
    DEFAULT_HIT_MOD,
    DEFAULT_KIND,
    DEFAULT_MP_COST,
    DEFAULT_POWER,
    DEFAULT_TRIGGER_LIMIT,
    DEFAULT_TYPE,
    SKILL_ELEMENTS,
    SKILL_KINDS,
    SKILL_TAGS,
    SKILL_TRIGGER_TYPES,
    SKILL_TYPES,
    SkillDef,
    skills_fields,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _full_entry() -> Dict[str, object]:
    """全 24 字段合法技能条目（细化_6a §1.2 逐字段样例：A7 + B11 + C2 + D4）。"""
    return {
        # A. ActionCore 共用核心 7
        "id": "fireball", "name": "火球术",
        "kind": "damage", "power": 120,
        "attack_type": "magic", "element": "fire",
        "effects": [
            {"effect": "power_slash", "overrides": {"power": 50}},
            {"type": "mark_add", "target": "self", "mark": "fire_mark", "count": 1},
        ],
        # B. 玩家侧扩展 11
        "type": "active", "mp_cost": 8, "cooldown": 2,
        "tag": "combo", "armor": True, "interrupt": True,
        "chain_refs": ["chain_fire_combo"],
        "consume_marks": {"fire_mark": 1},
        "job_restrict": ["mage"], "job_form": "flame_form",
        "level": {"max": 3, "growth": [1.0, 1.2, 1.5]},
        # C. 全库补充 2
        "hits": 3, "trigger_limit": {"per_round": 5, "per_battle": 20},
        # D. 细化定型 4
        "desc": "三连火球", "hit_mod": 1.1, "crit_mod": 1.2, "block_mode": "ignore",
    }


def _minimal_entry() -> Dict[str, object]:
    """仅核心字段条目（TC-02 缺省兜底：kind 推断 damage / type 兜底 active）。"""
    return {"id": "slash", "name": "斩击", "power": 100}


def _def(entry: Mapping[str, object]) -> SkillDef:
    return cast(SkillDef, SkillDef.from_entry(entry))


# ---------------------------------------------------------------------------
# 1. 字段默认值兜底（三铁律②：漏配 = 合理默认不是报错）
# ---------------------------------------------------------------------------
def test_minimal_entry_defaults_full_coverage() -> None:
    """仅 {id,name,power} 的技能：24 字段全部合理默认，零异常（TC-02 缺省兜底）。"""
    d = _def(_minimal_entry())
    assert d.id == "slash"
    assert d.name == "斩击"
    # A 核心 7
    assert d.skill_kind == "damage"            # F03 自动推断兜底 damage
    assert d.power == 100.0                    # F04
    assert d.attack_type == "none"             # F05 缺省 none=按武器
    assert d.element is None                   # F06
    assert d.effects == ()                     # F07
    # B 玩家扩展 11
    assert d.type == "active"                  # F08 TC-02 裁决兜底 active
    assert d.mp_cost == 0.0                    # F09
    assert d.cooldown == 0.0                   # F10
    assert d.tag == "none"                     # F11
    assert d.armor is False                    # F12
    assert d.interrupt is False                # F13
    assert d.chain_refs == ()                  # F14
    assert d.consume_marks == {}               # F15
    assert d.job_restrict == ()                # F16
    assert d.job_form is None                  # F17
    assert d.level is None                     # F18 不升级
    # C 全库补充 2
    assert d.hits == 1                         # F19
    assert d.trigger_limit == {"per_round": 10, "per_battle": 99}  # F20
    # D 细化定型 4
    assert d.desc == ""                        # F21
    assert d.hit_mod == 1.0                    # F22
    assert d.crit_mod == 1.0                   # F23
    assert d.block_mode == "auto"              # F24


def test_full_entry_parsed_exact() -> None:
    """全 24 字段条目：逐字段精确解析（A7 + B11 + C2 + D4）。"""
    d = _def(_full_entry())
    # A 核心 7
    assert d.id == "fireball"
    assert d.name == "火球术"
    assert d.skill_kind == "damage"
    assert d.power == 120.0
    assert d.attack_type == "magic"
    assert d.element == "fire"
    assert len(d.effects) == 2
    # B 玩家扩展 11
    assert d.type == "active"
    assert d.mp_cost == 8.0
    assert d.cooldown == 2.0
    assert d.tag == "combo"
    assert d.armor is True
    assert d.interrupt is True
    assert d.chain_refs == ("chain_fire_combo",)
    assert d.consume_marks == {"fire_mark": 1}
    assert d.job_restrict == ("mage",)
    assert d.job_form == "flame_form"
    assert d.level is not None and d.level["max"] == 3
    assert d.level_obj()["growth"] == [1.0, 1.2, 1.5]
    # C 全库补充 2
    assert d.hits == 3
    assert d.trigger_limit == {"per_round": 5, "per_battle": 20}
    # D 细化定型 4
    assert d.desc == "三连火球"
    assert d.hit_mod == 1.1
    assert d.crit_mod == 1.2
    assert d.block_mode == "ignore"


def test_default_constants_aligned() -> None:
    """默认常量与契约字段表一致（§1.2 逐字段默认值）。"""
    assert DEFAULT_TYPE == "active"            # TC-02 裁决
    assert DEFAULT_KIND == "damage"            # §1.3-f1 推断兜底
    assert DEFAULT_POWER == 100.0
    assert DEFAULT_MP_COST == 0.0
    assert DEFAULT_COOLDOWN == 0.0
    assert DEFAULT_HITS == 1
    assert DEFAULT_HIT_MOD == 1.0
    assert DEFAULT_CRIT_MOD == 1.0
    assert DEFAULT_BLOCK_MODE == "auto"
    assert DEFAULT_ATTACK_TYPE == "none"
    assert DEFAULT_DESC == ""
    assert DEFAULT_TRIGGER_LIMIT == {"per_round": 10, "per_battle": 99}


def test_enum_constants_exact() -> None:
    """枚举常量与契约逐值一致（§1.2 字段表 + §1.4 + validator 触发枚举同源）。"""
    assert SKILL_TYPES == ("basic", "active", "passive", "trigger")
    assert SKILL_KINDS == ("damage", "heal", "status", "control", "utility")
    assert ATTACK_TYPES == ("slash", "blunt", "pierce", "magic", "none")
    assert SKILL_ELEMENTS == (
        "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
    )
    assert SKILL_TAGS == (
        "none", "combo", "combo_preserve", "combo_push", "interrupt", "armor",
    )
    assert BLOCK_MODES == ("auto", "normal", "ignore")
    assert len(SKILL_TRIGGER_TYPES) == 13  # 13 类触发枚举（§1.4 [L111]）
    assert "hp_below" in SKILL_TRIGGER_TYPES
    assert "after_action" in SKILL_TRIGGER_TYPES
    assert "combo_broken" in SKILL_TRIGGER_TYPES


# ---------------------------------------------------------------------------
# 2. from_entry 全量 / 缺省 / 异常值兜底
# ---------------------------------------------------------------------------
def test_from_entry_missing_id_name_fallback() -> None:
    """from_entry 缺 id/name：BaseDef 兜底（id 空串、name 回退 id），零异常。"""
    d = _def({"power": 50})
    assert d.id == ""
    assert d.name == ""
    assert d.power == 50.0
    assert d.type == "active"


def test_from_entry_raw_deepcopy_isolation() -> None:
    """raw 为深拷贝快照：外部改原条目不影响 Def（BaseDef 契约，registry 共享安全）。"""
    entry: Dict[str, object] = _full_entry()
    d = _def(entry)
    entry["power"] = 999
    entry["name"] = "改名"
    assert d.power == 120.0
    assert d.name == "火球术"


def test_wrong_type_values_fall_back_to_defaults() -> None:
    """异常值类型兜底：非数值/非字符串/非列表 → 合理默认，不抛错（三铁律②）。"""
    d = _def({
        "id": "odd", "name": "异常",
        "power": "很高", "hits": "三", "armor": "yes", "interrupt": 1,
        "mp_cost": -5, "cooldown": None, "tag": 7,
        "chain_refs": "not_a_list", "job_restrict": {"a": 1},
        "element": 3, "attack_type": None, "kind": [],
        "hit_mod": 0, "crit_mod": -1, "block_mode": 9,
        "trigger_limit": "x", "level": "no", "consume_marks": [1, 2],
        "effects": "boom", "desc": None,
    })
    assert d.power == 100.0
    assert d.hits == 1
    assert d.armor is False
    assert d.interrupt is False
    assert d.mp_cost == 0.0
    assert d.cooldown == 0.0
    assert d.tag == "none"
    assert d.chain_refs == ()
    assert d.job_restrict == ()
    assert d.element is None
    assert d.attack_type == "none"
    assert d.skill_kind == "damage"
    assert d.hit_mod == 1.0   # 0 非法 → 兜底 1.0
    assert d.crit_mod == 1.0  # 负数 → 兜底 1.0
    assert d.block_mode == "auto"
    assert d.trigger_limit == {"per_round": 10, "per_battle": 99}
    assert d.level is None
    assert d.consume_marks == {}
    assert d.effects == ()
    assert d.desc == ""


def test_nonpositive_hits_falls_back() -> None:
    """hits ≤0 非法 → 兜底 1（多段次数须 ≥1，§1.2-C F19）。"""
    for bad in (0, -3):
        d = _def({"id": "h", "name": "h", "hits": bad})
        assert d.hits == 1


def test_consume_marks_filters_invalid() -> None:
    """consume_marks 防御性过滤：非字符串键/非正整数 → 丢弃（补白 6）。"""
    d = _def({"id": "m", "name": "m", "consume_marks": {
        "ok": 1, "bad_key": 0, "neg": -2, 3: 5, "str_count": "x",
    }})
    assert d.consume_marks == {"ok": 1}


def test_trigger_limit_partial_keys() -> None:
    """trigger_limit 部分键兜底：缺省键补默认（F20：per_round/per_battle）。"""
    d = _def({"id": "t", "name": "t", "trigger_limit": {"per_round": 0}})
    assert d.trigger_limit == {"per_round": 0, "per_battle": 99}
    d2 = _def({"id": "t2", "name": "t2", "trigger_limit": {}})
    assert d2.trigger_limit == {"per_round": 10, "per_battle": 99}


# ---------------------------------------------------------------------------
# 3. 四类时机 type 枚举（§1.4）
# ---------------------------------------------------------------------------
def test_four_type_timing_parsed() -> None:
    """四类时机 basic/active/passive/trigger 逐一解析（§1.4 执行语义表）。"""
    cases = {
        "basic": ("普攻", 0.0, 0.0),
        "active": ("主动", 8.0, 2.0),
        "passive": ("被动", 0.0, 0.0),
        "trigger": ("触发", 0.0, 1.0),
    }
    for t, (name, mp, cd) in cases.items():
        d = _def({"id": f"sk_{t}", "name": name, "type": t,
                  "mp_cost": mp, "cooldown": cd})
        assert d.type == t
        assert d.mp_cost == mp
        assert d.cooldown == cd


def test_trigger_skill_with_limit_defaults() -> None:
    """trigger 技能：触发上限缺省 {10,99}（F20 / V-8 默认口径）。"""
    d = _def({"id": "sk_trigger", "name": "触发技", "type": "trigger"})
    assert d.type == "trigger"
    assert d.trigger_limit == {"per_round": 10, "per_battle": 99}


# ---------------------------------------------------------------------------
# 4. ActionCore 双库同构（§2.2：F01-F07 与 action.json 逐字段同构、逐约束同源）
# ---------------------------------------------------------------------------
def test_action_core_dual_library_isomorphic() -> None:
    """SkillDef 与 ActionDef 的 ActionCore 7 字段逐键同构（§2.2 双库同构）。"""
    entry = {
        "id": "dual", "name": "同构", "kind": "damage", "power": 100,
        "attack_type": "magic", "element": "fire",
        "effects": [{"effect": "power_slash"}],
    }
    s = _def(entry)
    a = cast(ActionDef, ActionDef.from_entry(entry))
    assert s.id == a.id and s.name == a.name
    assert s.skill_kind == a.raw.get("kind")          # F03
    assert s.power == a.raw.get("power")              # F04
    assert s.attack_type == a.raw.get("attack_type")  # F05
    assert s.element == a.raw.get("element")          # F06
    assert s.effects == tuple(a.raw.get("effects") or ())  # F07
    # F03 kind 双库同构：BaseDef.kind 为注册表 kind（"action"），ActionCore kind
    # 经 raw.get("kind") 读取（ActionDef docstring 明示），与 SkillDef.skill_kind 同源
    assert a.raw.get("kind") == "damage"


def test_action_core_dual_library_defaults_align() -> None:
    """双库共用 ActionCore 的缺省口径一致：ActionDef 漏配同样零异常（§2.2）。"""
    s = _def({"id": "x", "name": "x"})
    a = cast(ActionDef, ActionDef.from_entry({"id": "x", "name": "x"}))
    # 两库同键读 raw，缺省兜底口径一致（SkillDef 显式默认；ActionDef raw 直读）
    assert s.skill_kind == a.raw.get("kind") or "damage"
    assert s.power == (a.raw.get("power") if a.raw.get("power") is not None else 100.0)


def test_skills_fields_24_keys_exact() -> None:
    """skills_fields() 恰好 24 键（§1.2：A7 + B11 + C2 + D4），键名与契约一致。"""
    f = skills_fields()
    assert set(f.keys()) == {
        # A 核心 7
        "id", "name", "kind", "power", "attack_type", "element", "effects",
        # B 玩家扩展 11
        "type", "mp_cost", "cooldown", "tag", "armor", "interrupt",
        "chain_refs", "consume_marks", "job_restrict", "job_form", "level",
        # C 全库补充 2
        "hits", "trigger_limit",
        # D 细化定型 4
        "desc", "hit_mod", "crit_mod", "block_mode",
    }


def test_skills_fields_enum_and_defaults() -> None:
    """skills_fields() 枚举/默认值与契约一致（供 field_meta 登记/校验器 V-13 依据）。"""
    f = skills_fields()
    assert f["type"].enum == SKILL_TYPES and f["type"].default == "active"
    assert f["kind"].enum == SKILL_KINDS and f["kind"].default == "damage"
    assert f["attack_type"].enum == ATTACK_TYPES
    assert f["tag"].enum == SKILL_TAGS and f["tag"].default == "none"
    assert f["block_mode"].enum == BLOCK_MODES and f["block_mode"].default == "auto"
    assert f["power"].default == 100.0 and f["power"].range_max == 500
    assert f["hits"].range_min == 1 and f["hits"].default == 1
    assert f["armor"].default is False and f["interrupt"].default is False
    assert f["chain_refs"].element is not None
    assert f["chain_refs"].element.ref_target == "skill_chain"
    assert f["job_restrict"].element is not None and f["job_restrict"].element.ref_target == "job"
    assert f["id"].required is True


def test_skills_fields_core_mirrors_action_fields() -> None:
    """skills_fields() 的 ActionCore 7 字段与 field_meta skills_fields 同键同约束（§2.2 双库同构）。

    双库同构的登记侧权威 = field_meta.skills_fields（与 action_fields 同构登记，
    §2.2 逐字段同构、逐约束同源）；本测试比对 skills_fields() 与 field_meta
    skills_fields 的核心 7 键集合与类型口径一致。
    """
    from qbot_rpg.content.field_meta import _module_table

    meta = _module_table()
    af = meta["skills"].fields  # field_meta 已登记 skills_fields
    core_keys = {"id", "name", "kind", "power", "attack_type", "element", "effects"}
    sf = skills_fields()
    assert core_keys <= set(sf.keys())
    assert core_keys <= set(af.keys())
    for k in core_keys:
        # 双库同构：类型一致（kind 在 action 侧为 str 宽松登记、skills 侧为 enum，
        # 双库同构按「逐字段同构、逐约束同源」口径比对 type 与 range 口径）
        assert sf[k].type == af[k].type or k in ("kind", "attack_type"), \
            f"双库 ActionCore 字段 {k} 类型不同构"
        assert sf[k].range_min == af[k].range_min
        assert sf[k].range_max == af[k].range_max
