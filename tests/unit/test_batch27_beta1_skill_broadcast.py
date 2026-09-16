"""批27 · β1：每技能战斗播报模板 `message_key`（CakeGame Config_Skills.AttackTips）。

**现状核查结论（本批拍板）**：既有 `templates` 是**全局键**文案覆盖
（`core/templates/template_table.json` + 包 `templates.json` 覆盖同 key），
战斗渲染用 `{action}`（技能名）占位——**无按技能粒度**。故按最小方案落地：
  · `skills[].message_key` **只存模板键**（`core/templates/template_table.json` 的 key），
    **不把整段文案存进技能数据**（红线）；缺省 "" = 走既有默认键；
  · 引擎消费：`core/message_format/battle_render` 按最终 skill_id（派生/组合后
    实际技能）取键渲染玩家命中/未命中/施放行；未配置/查无 → 回落既有默认键，
    **行为逐字段一致**；
  · 编辑器：字段 `options_ref="templates"` → 下拉候选 = 全量模板表 key；
  · 校验：仅 str（泛型 R-1）。
**边界（如实登记）**：内容包只能覆盖模板表中**已存在**的键
（`tests/unit/test_template_table_final.py::test_all_content_packs_have_no_unknown_keys`
门禁：包不得新增表外键）；因此"某技能独有文案"需要该键在框架表内——
本批不放松该门禁（门禁只能更严），语料新增走框架表登记。

覆盖：
  - 元数据登记（skills，str + options_ref）+ 编辑器可见；
  - 校验：非 str → R-1 红；
  - 引擎消费（输出原文）：带 message_key 的技能 → 渲染自定义模板；不带 → 默认模板
    逐字段一致；派生后按**实际 skill_id** 取键（接线注入证据）；
  - 回归：未配置字段 / 空串 / 查无键 → 与现状一致。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from qbot_rpg.commands.battle_commands import _inject_display_outcomes
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import ActionOutcome
from qbot_rpg.core.message_format.battle_render import (
    _render_player_hit,
    _render_player_miss,
    _render_skill_cast_line,
)
from qbot_rpg.core.templates import resolve_templates
from qbot_rpg.web import api

_BASIC = {"id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
          "power": 100}


def _templates(**extra: str) -> Dict[str, Any]:
    """全量默认模板 + 测试注入的「技能私有键」（键名不写死在框架，仅测试自造）。"""
    tpls: Dict[str, Any] = dict(resolve_templates({}))
    tpls.update(extra)
    return tpls


def _outcome(*, skill_id: str = "", action_type: str = "skill",
             hit: bool = True, final_damage: int = 42,
             combo_result: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        actor="player", action_type=action_type, target="桩", hit=hit,
        crit="low", blocked=False, final_damage=final_damage, target_hp=58,
        skill_id=skill_id, action_name="基础式", message="",
        combo_result=combo_result, side_effects=(),
    )


# ---------------------------------------------------------------------------
# β1 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_b1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("skills").fields.get("message_key")
    assert fm is not None, "skills 缺 message_key 登记"
    assert fm.type == "str"
    assert fm.options_ref == "templates", "编辑器下拉来源应为全量模板表"
    assert fm.label == "战斗播报模板" and fm.help
    assert tbl.module("skills").field_groups.get("message_key") == "基本"


def test_b1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_b1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_b1", "version": "1", "schema_version": 1,
         "modules": ["skills"]}, ensure_ascii=False), encoding="utf-8")
    (root / "skills.json").write_text(json.dumps([
        dict(_BASIC),
        {"id": "roar", "name": "怒吼", "type": "active", "kind": "damage",
         "message_key": "battle_player_hit"}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_b1", "skills", "roar", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "message_key")
    assert f["present"] is True and f["type"] == "str"


# ---------------------------------------------------------------------------
# β1 校验：str 口径
# ---------------------------------------------------------------------------
def test_b1_validator_non_str_red() -> None:
    report = check_pack({"skills": [
        dict(_BASIC), {"id": "s", "name": "技", "message_key": 123}]})
    assert [e for e in report.errors if e.kind == "R-1" and "message_key" in e.field], report.errors


def test_b1_validator_str_and_missing_ok() -> None:
    report = check_pack({"skills": [
        dict(_BASIC),
        {"id": "s", "name": "技", "message_key": "battle_player_hit"},
        {"id": "t", "name": "普通技"},
    ]})
    assert not [e for e in report.errors if "message_key" in e.field], report.errors


# ---------------------------------------------------------------------------
# β1 引擎消费（输出原文）
# ---------------------------------------------------------------------------
def test_b1_per_skill_broadcast_renders_custom_text() -> None:
    """带 message_key 的技能 → 按技能自定义模板渲染（贴输出原文）。"""
    ctx = {
        "templates": _templates(battle_player_hit_custom="🔥 你{action}，轰出 {damage} 点！"),
        "skills": {"ember": {"id": "ember", "message_key": "battle_player_hit_custom"}},
    }
    out = _outcome(skill_id="ember")
    assert _render_player_hit(out, ctx=ctx) == "🔥 你发动技能 基础式，轰出 42 点！"


def test_b1_unconfigured_uses_default_verbatim() -> None:
    """未配置字段/空串/查无键 → 与既有默认模板逐字段一致。"""
    ctx = {"templates": _templates(battle_player_hit_custom="不该出现"),
           "skills": {
               "plain": {"id": "plain"},
               "empty": {"id": "empty", "message_key": ""},
               "ghost": {"id": "ghost", "message_key": "no_such_template_key"},
           }}
    default_line = _render_player_hit(_outcome(), ctx=ctx)
    for sid in ("plain", "empty", "ghost"):
        assert _render_player_hit(_outcome(skill_id=sid), ctx=ctx) == default_line
    assert "42" in default_line and "基础式" in default_line


def test_b1_miss_and_cast_lines_follow_message_key() -> None:
    ctx = {
        "templates": _templates(
            skill_miss_custom="{target} 躲开了 {action}",
            skill_cast_custom="✨ 你发动了 {skill_name}",
        ),
        "skills": {
            "dodgy": {"id": "dodgy", "message_key": "skill_miss_custom"},
            "caster": {"id": "caster", "message_key": "skill_cast_custom"},
        },
    }
    miss = _render_player_miss(_outcome(skill_id="dodgy", hit=False), ctx=ctx)
    assert miss == "桩 躲开了 基础式", miss
    cast_oc = _outcome(skill_id="caster", final_damage=0)
    cast_oc.skill_name = "怒吼"
    assert _render_skill_cast_line(cast_oc, ctx=ctx) == "✨ 你发动了 怒吼"


def test_b1_wiring_injects_actual_skill_id_after_derivation() -> None:
    """接线注入的是**实际 skill_id**：派生 combo_result.form_id 优先于源技能。"""
    derived = ActionOutcome(
        ok=True, seq=1, actor="player", action_type="skill", target="enemy",
        hit=True, crit="low", blocked=False, raw_damage=10, final_damage=10,
        target_hp=50, side_effects=(), combo_result={"form_id": "adv"})
    out = _inject_display_outcomes(
        [derived], enemy_name="桩", player_max_hp=500, enemy_max_hp=100,
        player_action={"type": "skill", "skill_id": "base"}, skill_name="基础式")
    assert out[0].skill_id == "adv", out[0].skill_id
    # 未派生时回退源技能 id
    plain = ActionOutcome(
        ok=True, seq=2, actor="player", action_type="skill", target="enemy",
        hit=True, crit="low", blocked=False, raw_damage=10, final_damage=10,
        target_hp=50, side_effects=())
    out2 = _inject_display_outcomes(
        [plain], enemy_name="桩", player_max_hp=500, enemy_max_hp=100,
        player_action={"type": "skill", "skill_id": "base"}, skill_name="基础式")
    assert out2[0].skill_id == "base", out2[0].skill_id


def test_b1_pack_override_of_referenced_key() -> None:
    """内容包覆盖能力仍在：技能引用既有键 → 包 templates 覆盖该键即换文案。"""
    ctx = {
        "templates": resolve_templates({"battle_player_hit": "🅱 {action} → {damage}"}),
        "skills": {"legacy": {"id": "legacy", "message_key": "battle_player_hit"}},
    }
    assert _render_player_hit(_outcome(skill_id="legacy"), ctx=ctx) == "🅱 发动技能 基础式 → 42"
