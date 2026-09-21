"""批80 · 技能等级维度（数据侧打通 + 作为「公式变量」暴露）验收。

用户口径（2026-09-23）：技能等级做完后**作为变量使用**，作者在技能公式里自行引用；
**框架只提供变量，不硬编码任何「等级 → 数值」映射**（第 3 步硬编码消费取消）。

覆盖：
  A 统一读表（三源并集 + 取最大合并 + 纯读）
  B F18 声明生效（max≥2 进等级线 / 上限夹取 / 校验红拦 / 标量兼容）
  C 变量生效（[技能等级:<技能ID>] 数值随等级变化；不引用 → 逐字节一致）
  D 展示（/技能 行 Lv；缺省 1 / 未进线 → 不渲染，逐字节等价现状）
  E 沙箱（占位符展开为数值字面量，白名单/黑名单零放宽）
"""

from __future__ import annotations

import copy

from qbot_rpg.commands.basic_commands import skill_line
from qbot_rpg.content.skill_validator import validate_skills
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.formula_engine import (
    FORMULA_BLACKLIST,
    EvaluatorCtx,
    _expand_placeholders,
    evaluate,
)
from qbot_rpg.core.skill_slots_battle import (
    leveled_skill_levels,
    set_skill_levels,
    skill_level_axis,
    skill_level_cap,
)

# F18 声明形状（field_meta.py F18：{max, growth}，growth 长度 = max 且 growth[0] = 1.0）
_F18 = {"max": 3, "growth": [1.0, 1.1, 1.2]}


# =====================================================================================
# A · 统一读表（三源并集）
# =====================================================================================


def test_union_equip_source():
    """来源① 装备 equip_skills → 读表收录。"""
    assert set_skill_levels({"equip_skills": {"a": 2}}) == {"a": 2}


def test_union_set_source():
    """来源② 套装 set_skills → 读表收录（既有行为不回归）。"""
    assert set_skill_levels({"set_skills": {"a": 3}}) == {"a": 3}


def test_union_skill_slots_source():
    """来源③ 学技能行 slots[].level → 读表收录（passive 行无 level 不收）。"""
    ctx = {
        "skill_slots_state": {
            "slots": [
                {"slot": "active", "skill_id": "a", "level": 4},
                {"slot": "passive", "skill_id": "b"},
            ]
        }
    }
    assert set_skill_levels(ctx) == {"a": 4}


def test_union_multi_source_takes_max():
    """同技能多源命中 → 取最大（plan §2.1 / N1 口径）。"""
    ctx = {
        "equip_skills": {"a": 2},
        "set_skills": {"a": 3},
        "skill_slots_state": {"slots": [{"slot": "active", "skill_id": "a", "level": 1}]},
    }
    assert set_skill_levels(ctx) == {"a": 3}


def test_union_cleans_and_defaults():
    """非法项（bool/0/负/非 str id/非 Mapping 容器）跳过；全缺 → {}。"""
    ctx = {"equip_skills": {"a": True, "b": 0, "c": -1, 3: 2}, "set_skills": "bad"}
    assert set_skill_levels(ctx) == {}
    assert set_skill_levels({}) == {}


def test_union_is_pure_read():
    """纯读：调用不改写 ctx（不写存档）。"""
    ctx = {"equip_skills": {"a": 2}, "set_skills": {"b": 1}, "skill_slots_state": {"slots": []}}
    before = copy.deepcopy(ctx)
    set_skill_levels(ctx)
    leveled_skill_levels(ctx)
    assert ctx == before


# =====================================================================================
# B · F18 声明生效 + 校验闭合
# =====================================================================================


def test_axis_object_max_ge_2_enters():
    """对象且 max≥2 → 进等级线（cap = max）。"""
    assert skill_level_axis({"level": _F18}) is True
    assert skill_level_cap({"level": _F18}) == 3


def test_axis_rejects_scalar_null_missing_and_max1():
    """标量 level:1（veinborn 11 条）/ null / 缺省 / max=1 → 不进线、不报错。"""
    for defn in ({"level": 1}, {"level": None}, {}, {"level": {"max": 1, "growth": [1.0]}}):
        assert skill_level_axis(defn) is False, defn
        assert skill_level_cap(defn) is None


def test_leveled_filters_and_clamps():
    """leveled_skill_levels = 三源并集 ∩ 进线技能，等级夹取到 F18 max。"""
    ctx = {
        "set_skills": {"a": 3, "b": 5, "c": 2},
        "skills": {
            "a": {"level": _F18},              # 进线，max=3 → 3
            "b": {"level": 1},                 # 标量 → 不进线
            "c": {"level": {"max": 2, "growth": [1.0, 1.1]}},  # 进线，来源 2 → 2
            "d": {"level": {"max": 3, "growth": [1.0, 1.1, 1.2]}},  # 无来源 → 不收
        },
    }
    assert leveled_skill_levels(ctx) == {"a": 3, "c": 2}


def test_leveled_without_skill_table_is_empty():
    """ctx["skills"] 缺失 → {}（无声明可判，不臆造等级线）。"""
    assert leveled_skill_levels({"set_skills": {"a": 3}}) == {}


def _f18_errors(entries):
    report = {}
    validate_skills({"skills": entries}, report)
    return [e for e in report.get("errors", []) if e.get("kind") == "F18"]


def test_validator_accepts_blade_dance_shape():
    """既有 blade_dance {max:3, growth:[1.0,1.1,1.2]} 必须通过。"""
    assert _f18_errors([{"id": "blade_dance", "level": _F18}]) == []


def test_validator_compat_scalar_and_null():
    """标量 level:1 / null / 缺省 → 零 F18 红拦（兼容既有数据）。"""
    assert _f18_errors([{"id": "x", "level": 1}]) == []
    assert _f18_errors([{"id": "x", "level": None}]) == []
    assert _f18_errors([{"id": "x"}]) == []


def test_validator_red_on_growth_length():
    errs = _f18_errors([{"id": "x", "level": {"max": 3, "growth": [1.0, 1.1]}}])
    assert [e["rule"] for e in errs] == ["skill_level_growth_length"]


def test_validator_red_on_growth_base():
    errs = _f18_errors([{"id": "x", "level": {"max": 2, "growth": [2.0, 1.1]}}])
    assert [e["rule"] for e in errs] == ["skill_level_growth_base"]


def test_validator_red_on_max_and_growth_types():
    assert [e["rule"] for e in _f18_errors([{"id": "x", "level": {"max": "3", "growth": [1.0]}}])] \
        == ["skill_level_max_invalid"]
    assert [e["rule"] for e in _f18_errors([{"id": "x", "level": {"max": 2, "growth": "x"}}])] \
        == ["skill_level_growth_invalid"]
    assert [e["rule"] for e in _f18_errors([{"id": "x", "level": {"max": 2, "growth": [1.0, "a"]}}])] \
        == ["skill_level_growth_invalid"]


# =====================================================================================
# C · 变量生效（[技能等级:<技能ID>]）
# =====================================================================================


def _engine_eval(levels, expr):
    engine = BattleEngine()
    cfg = {"skill_levels": {"player": levels}} if levels else {}
    engine.start({"max_hp": 100, "hp": 100, "atk": 50},
                 {"max_hp": 100, "hp": 100}, random_seed=1, config=cfg)
    return engine._make_eval_formula("player", "enemy")(expr)


def test_variable_value_tracks_level():
    """变量生效：同一公式随等级变化（两组数值）。"""
    assert _engine_eval({"fireball": 2}, "[技能等级:fireball]*10") == 20.0
    assert _engine_eval({"fireball": 3}, "[技能等级:fireball]*10") == 30.0


def test_variable_formula_engine_direct():
    """formula_engine 直接注入 attacker.skill_level 容器 → 占位符解析生效。"""
    ctx = EvaluatorCtx(attacker={"skill_level": {"fireball": 3}}, battle={"round": 1})
    assert evaluate("[技能等级:fireball] * 10 + 5", ctx) == 35.0


def test_variable_from_three_sources_end_to_end():
    """端到端：三源并集 ∩ F18 → 注入引擎 config → 公式取值（不写死任何映射）。"""
    ctx = {
        "equip_skills": {"fireball": 2},
        "set_skills": {"fireball": 3},
        "skill_slots_state": {"slots": [{"slot": "active", "skill_id": "fireball", "level": 1}]},
        "skills": {"fireball": {"level": _F18}},
    }
    assert leveled_skill_levels(ctx) == {"fireball": 3}
    assert _engine_eval(leveled_skill_levels(ctx), "[技能等级:fireball]*10") == 30.0


def test_no_reference_is_byte_identical():
    """公式不引用该变量 → 结果逐字节一致（有无等级表对拍）。"""
    expr = "[我方攻击] * 2 + 1"
    assert _engine_eval({"fireball": 3}, expr) == _engine_eval(None, expr) == 101.0


def test_unknown_skill_level_placeholder_is_zero():
    """引用未注入的技能 → 未知占位符 0 + warning（与既有未知占位符口径一致）。"""
    assert _engine_eval({"fireball": 2}, "[技能等级:nope]*10") == 0.0


def test_placeholder_expands_to_numeric_literal():
    """沙箱口径：占位符展开为数值字面量（不引入任何 JS 标识符）。"""
    ctx = EvaluatorCtx(attacker={"skill_level": {"fireball": 3}})
    warnings = []
    assert _expand_placeholders("[技能等级:fireball]", ctx, warnings) == "3"


def test_sandbox_blacklist_unchanged():
    """不得放宽沙箱安全策略：黑名单常量不因本批变化。"""
    assert "eval" in FORMULA_BLACKLIST
    assert "constructor" in FORMULA_BLACKLIST
    assert set(FORMULA_BLACKLIST) == {
        "constructor", "__proto__", "prototype", "Function", "eval", "globalThis",
        "process", "require", "fetch", "setTimeout", "setInterval", "import", "module",
        "exports", "self", "window", "document",
    }


# =====================================================================================
# D · /技能 展示
# =====================================================================================


def _skill_ctx(skill_level, sources):
    ctx = {
        "skills": {"fireball": {"name": "火球术", "type": "active", "brief": ""}},
        "skill_chains": {},
        "templates": {},
    }
    if skill_level is not None:
        ctx["skills"]["fireball"]["level"] = skill_level
    ctx.update(sources)
    return ctx


def test_skill_line_no_level_byte_identical():
    """缺省 1 / 无来源 → 不渲染等级，输出与现状逐字节一致。"""
    assert skill_line(2, "fireball", _skill_ctx(None, {})) == "2. 火球术（主动）\n————"


def test_skill_line_scalar_level_not_rendered():
    """标量 level:1（不进线）→ 不渲染等级。"""
    assert skill_line(2, "fireball", _skill_ctx(1, {"set_skills": {"fireball": 3}})) \
        == "2. 火球术（主动）\n————"


def test_skill_line_renders_level_above_1():
    """F18 进线 + 来源等级 → 渲染「 LvN」。"""
    out = skill_line(2, "fireball", _skill_ctx(_F18, {"set_skills": {"fireball": 2}}))
    assert out == "2. 火球术（主动） Lv2\n————"


def test_skill_line_level_from_equip_source():
    """装备来源等级经统一读表进展示。"""
    out = skill_line(2, "fireball", _skill_ctx(_F18, {"equip_skills": {"fireball": 3}}))
    assert "2. 火球术（主动） Lv3" in out
