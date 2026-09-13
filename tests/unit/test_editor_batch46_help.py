"""编辑器重写批4.6 · 字段说明气泡（点击/悬停显示字段解释）。

覆盖任务书要求：
  · **元数据新维度**：`FieldMeta.help`（一句话说明）+ `FieldMeta.unit`（数值单位）；
    只加展示语义，type/required/default/enum/children/校验规则一律不动；
  · **自动拼装**（换包零改动、一定能出）：字段名（中文+原始键）、类型语义、
    数值还是比例/百分比、建议范围（zero_unlimited 写明 0=不限）、默认值、是否必填、
    枚举候选、引用目标；判不出来如实说「未标注」；
  · **人工 help**：关键模块（skills/enemies/items/equipment/effects/statuses/marks/
    skill_chains/action/settings）高频字段逐条中文说明；缺省（无 help）不报错；
  · **交互**：悬停中文名出卡、点击固定/关闭、Esc 与点空白关闭、键盘可达、aria 标注、
    卡片不遮住正在编辑的字段、窄窗口避让、长文可滚动（细滚动条令牌）；
  · **前端纯逻辑用 node 直接执行断言**（与既有做法一致）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta as fm_mod
from qbot_rpg.content.models import FieldMeta
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

# 本批必做的 10 个模块 → 顶层人工说明表；批4.6 补追加 maps/quest/jobs/npc/shop
HELP_TABLES = {
    "skills": fm_mod.SKILLS_FIELD_HELP,
    "enemies": fm_mod.ENEMIES_FIELD_HELP,
    "items": fm_mod.ITEMS_FIELD_HELP,
    "equipment": fm_mod.EQUIPMENT_FIELD_HELP,
    "effects": fm_mod.EFFECTS_FIELD_HELP,
    "statuses": fm_mod.STATUSES_FIELD_HELP,
    "marks": fm_mod.MARKS_FIELD_HELP,
    "skill_chains": fm_mod.SKILL_CHAINS_FIELD_HELP,
    "action": fm_mod.ACTION_FIELD_HELP,
    "settings": fm_mod.SETTINGS_FIELD_HELP,
    "maps": fm_mod.MAPS_FIELD_HELP,
    "quest": fm_mod.QUEST_FIELD_HELP,
    "jobs": fm_mod.JOBS_FIELD_HELP,
    "npc": fm_mod.NPC_FIELD_HELP,
    "shop": fm_mod.SHOP_FIELD_HELP,
}
CHILD_HELP_TABLES = {
    "skills": fm_mod.SKILLS_CHILD_HELP,
    "enemies": fm_mod.ENEMIES_CHILD_HELP,
    "items": fm_mod.ITEMS_CHILD_HELP,
    "statuses": fm_mod.STATUSES_CHILD_HELP,
    "effects": fm_mod.EFFECTS_CHILD_HELP,
    "skill_chains": fm_mod.SKILL_CHAINS_CHILD_HELP,
    "settings": fm_mod.SETTINGS_CHILD_HELP,
    "maps": fm_mod.MAPS_CHILD_HELP,
    "quest": fm_mod.QUEST_CHILD_HELP,
    "jobs": fm_mod.JOBS_CHILD_HELP,
    "npc": fm_mod.NPC_CHILD_HELP,
    "shop": fm_mod.SHOP_CHILD_HELP,
}


# =====================================================================================
# 一、元数据层：help / unit 为可选展示维度
# =====================================================================================
def test_field_meta_help_and_unit_default_empty() -> None:
    """缺省构造零改动：不写 help/unit 时为空串，既有 560+ 处 FieldMeta 构造不受影响。"""
    fm = FieldMeta(type="int")
    assert fm.help == "" and fm.unit == ""
    named = FieldMeta(type="number", help="说明", unit="点")
    assert named.help == "说明" and named.unit == "点"


@pytest.mark.parametrize("mod", list(HELP_TABLES))
def test_help_tables_cover_every_declared_field(mod: str) -> None:
    """必做模块的每个顶层字段都有中文说明（覆盖统计见批报）。"""
    meta = api.field_meta_table().module(mod)
    assert meta is not None and meta.fields, mod
    covered = HELP_TABLES[mod]
    missing = [k for k, f in meta.fields.items() if not f.help]
    assert not missing, (mod, missing)
    # 表本身要有覆盖（不是空表靠字段自带 help 蒙混）
    assert len(covered) >= 10, (mod, len(covered))


@pytest.mark.parametrize("mod", [m for m in HELP_TABLES if m != "equipment"])
def test_help_tables_have_no_phantom_keys(mod: str) -> None:
    """说明表的键必须是本模块真实字段（不臆造字段名）；equipment 复用 items 表，单独放行。"""
    meta = api.field_meta_table().module(mod)
    extra = set(HELP_TABLES[mod]) - set(meta.fields)
    assert not extra, (mod, sorted(extra))


def test_equipment_help_reuses_items_plus_excludes() -> None:
    assert fm_mod.EQUIPMENT_FIELD_HELP["excludes"] == (
        "互斥部位：装备这些部位时不能同时装备本件（成环会被校验拦下）。")
    for key, text in fm_mod.ITEMS_FIELD_HELP.items():
        assert fm_mod.EQUIPMENT_FIELD_HELP.get(key) == text, key


def test_help_text_is_nonempty_single_line() -> None:
    """说明是「一句话」：非空、无换行（避免卡片排版被撑成段落）。"""
    for mod, table in HELP_TABLES.items():
        for key, text in table.items():
            assert isinstance(text, str) and text.strip(), (mod, key)
            assert "\n" not in text and "\r" not in text, (mod, key)


def test_child_help_only_targets_declared_children() -> None:
    """嵌套说明只作用于已声明的子字段（不新增字段节点、不越界）。"""
    skills = api.field_meta_table().module("skills")
    assert skills is not None
    level = skills.fields["level"]
    assert level.children["max"].help and level.children["growth"].help
    per_round = skills.fields["trigger_limit"].children["per_round"]
    assert per_round.help and per_round.unit == "次"


def _walk_help_table(spec: Any) -> Any:
    """展平嵌套说明表，产出所有 (键, 文案)（含 `_help` 节点说明）。"""
    if isinstance(spec, str):
        yield spec
    elif isinstance(spec, dict):
        for key, sub in spec.items():
            yield key
            yield from _walk_help_table(sub)


@pytest.mark.parametrize("mod", list(CHILD_HELP_TABLES))
def test_child_help_tables_are_wellformed(mod: str) -> None:
    """嵌套说明表：文案非空单行；`_help` 是节点说明而非子键。"""
    for item in _walk_help_table(CHILD_HELP_TABLES[mod]):
        if item == "_help":
            continue
        assert isinstance(item, str) and item.strip(), (mod, item)
        assert "\n" not in item and "\r" not in item, (mod, item)


def test_settings_child_help_covers_key_segments() -> None:
    """settings 各段（战斗/任务板/炼金/经济/行动条）的高频键都有中文说明。"""
    table = api.field_meta_table().module("settings")
    assert table is not None
    battle = table.fields["battle"].children
    for key in ("enrage_damage_mult", "fatigue_stagger_chance", "stun_enabled",
                "stun_escalation", "backstab_bonus"):
        assert battle[key].help, key
    quest_board = table.fields["quest_board"].children
    for key in ("enabled", "refresh_days", "penalty", "active_limit", "daily_limit"):
        assert quest_board[key].help, key
    alchemy = table.fields["alchemy"].children
    for key in ("mode", "quality_tiers", "energy_enabled", "decompose_rate"):
        assert alchemy[key].help, key
    currencies = table.fields["currencies"].element.children
    assert currencies["id"].help and currencies["cap"].help
    assert table.fields["ctb"].children["enabled"].help
    assert table.fields["ctb"].children["default_recovery"].help


def test_new_module_help_reaches_descriptors() -> None:
    """maps/quest/jobs/npc/shop 的顶层 + 嵌套中文说明经装饰层进入描述符。"""
    for mod, entry_key, child_key in (
        ("maps", "monsters", "enemy"),
        ("quest", "reward", "coins"),
        ("jobs", "growth", "mp"),
        ("npc", "interactions", "action"),
        ("shop", "refresh", "mode"),
    ):
        fm = api.field_meta_table().module(mod).fields[entry_key]
        assert fm.help, (mod, entry_key)
        kids = fm.children or {}
        if not kids and fm.element is not None:
            kids = fm.element.children or {}
        assert kids[child_key].help, (mod, entry_key, child_key)
    # 真实包反查：maps 刷怪行列出 enemy 列且带人工说明
    entries = api.list_entries("veinborn", "maps", root=CONTENT)["entries"]
    d = api.entry_detail("veinborn", "maps", str(entries[0]["id"]), root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    if by["monsters"].get("columns"):
        cols = {c["key"]: c for c in by["monsters"]["columns"]}
        assert cols["enemy"]["help"] and cols["enemy"]["help_card"]["help"]


def test_decoration_adds_help_but_keeps_validation_contract() -> None:
    """_decorate_field_meta 补 help 时，type/required/default/enum/children 原样。"""
    import dataclasses

    children = {"x": FieldMeta(type="int", range_min=0, range_max=9, label="内层")}
    original = FieldMeta(
        type="enum", required=True, default="a", enum=("a", "b"),
        range_min=1, range_max=3, probability=True, soft_label=True,
        allow_negative=True, children=children, multiline=True,
    )
    out = fm_mod._decorate_field_meta(
        {"k": original}, {"k": "g1"}, {"k": "中文名"}, None, {"k": "字段说明"})
    got = out["k"]
    assert got.help == "字段说明"
    for f in dataclasses.fields(FieldMeta):
        if f.name in ("help", "label", "group"):
            continue
        assert getattr(got, f.name) == getattr(original, f.name), f.name


def test_missing_help_falls_back_silently() -> None:
    """help 可选：未撰写说明的模块/字段照常可用、无异常（缺省回退）。"""
    table = api.field_meta_table()
    dungeon = table.module("dungeon")
    assert dungeon is not None
    assert any(f.help == "" for f in dungeon.fields.values())  # dungeon 本批未写说明
    # 全表实例化不报错 + help 一律是字符串
    for meta in table.modules.values():
        for f in meta.fields.values():
            assert isinstance(f.help, str) and isinstance(f.unit, str)


# =====================================================================================
# 二、自动拼装（api.help_card）：类型/比例/范围/默认/必填/枚举/引用/unit
# =====================================================================================
@pytest.mark.parametrize("ftype,zh", [
    ("str", "文本"), ("text", "文本"),
    ("int", "数字"), ("float", "数字"), ("number", "数字"),
    ("bool", "布尔"), ("enum", "枚举"), ("ref", "引用"),
    ("list", "列表"), ("obj", "对象"), ("map", "映射"), ("formula", "公式"),
])
def test_type_semantic(ftype: str, zh: str) -> None:
    assert api._type_semantic(ftype) == zh


def test_type_semantic_unknown_is_honest() -> None:
    assert api._type_semantic(None) == "未标注"
    assert api._type_semantic("weird") == "未标注"


@pytest.mark.parametrize("fm,expected", [
    (FieldMeta(type="number", probability=True, range_min=0, range_max=1),
     "比例（0~1，按百分比表示概率）"),
    (FieldMeta(type="number", unit="%", range_min=0, range_max=100),
     "百分比（数值自带 % 单位）"),
    (FieldMeta(type="number", unit="点", range_min=0, range_max=9999),
     "数值（单位：点）"),
    (FieldMeta(type="number", unit="回合", range_min=0, range_max=999),
     "数值（单位：回合）"),
    (FieldMeta(type="number", range_min=0, range_max=1),
     "比例（0~1；元数据未标注百分比单位）"),
    (FieldMeta(type="number", range_min=0, range_max=9999),
     "数值（未标注单位）"),
    (FieldMeta(type="int", range_min=0, range_max=999), "数值（未标注单位）"),
    (FieldMeta(type="str"), "不适用（非数值字段）"),
    (FieldMeta(type="bool"), "不适用（非数值字段）"),
])
def test_scale_semantic(fm: FieldMeta, expected: str) -> None:
    assert api._scale_semantic(fm) == expected


def test_scale_semantic_unregistered_is_honest() -> None:
    assert api._scale_semantic(None) == "未标注"


# =====================================================================================
# 二·补（实机问题①）：元数据未登记类型时按实际值推断，不得把数值说成文本
# =====================================================================================
@pytest.mark.parametrize("value,kind", [
    (True, "bool"), (False, "bool"),
    (60, "int"), (0, "int"), (60.0, "int"),
    (1.15, "float"), (0.12, "float"),
    ("x", "str"), ([], "list"), ({"a": 1}, "obj"), (None, None),
])
def test_infer_value_kind(value: object, kind: object) -> None:
    assert api._infer_value_kind(value) == kind


@pytest.mark.parametrize("value,expected", [
    (60, "数值（整数）"), (0.12, "数值（小数）"), (1.15, "数值（小数）"),
    (True, "布尔"), ("x", "文本"), ([], "列表"), ({"a": 1}, "对象"), (None, "未标注"),
])
def test_resolve_type_inferred_from_value(value: object, expected: str) -> None:
    text, source = api._resolve_type(None, value)
    assert text == expected
    assert source == ("" if value is None else "元数据未登记，按实际值推断")


def test_resolve_type_registered_wins_over_value() -> None:
    text, source = api._resolve_type(FieldMeta(type="str"), 1.15)
    assert text == "文本" and source == ""


@pytest.mark.parametrize("value,expected", [
    (1.15, "数值（未标注单位）"),
    (0.12, "疑似比例（当前值在 0~1；元数据未标注单位）"),
    ("x", "不适用（非数值字段）"),
    (True, "不适用（非数值字段）"),
    (None, "未标注"),
])
def test_scale_semantic_unregistered_uses_value(value: object, expected: str) -> None:
    """未登记类型的数值字段：判得出比例依据就给依据，判不出说「未标注单位」。"""
    assert api._scale_semantic(None, value) == expected


def test_help_card_infers_type_and_source_from_value() -> None:
    """实机样本：只有中文名的 battle 占位节点 → 卡片按 1.15 推断「数值（小数）」+ 来源。"""
    placeholder = FieldMeta(type="", label="狂暴伤害倍率")
    card = api.help_card("enrage_damage_mult", placeholder, 1.15)
    assert card["type"] == "数值（小数）"
    assert card["type_source"] == "元数据未登记，按实际值推断"
    assert card["scale"] == "数值（未标注单位）"
    assert card["unregistered"] is False  # 有中文名元数据，只是没登记类型


def test_help_card_unregistered_key_infers_from_value() -> None:
    card = api.help_card("ghost", None, 3)
    assert card["type"] == "数值（整数）"
    assert card["type_source"] == "元数据未登记，按实际值推断"
    assert card["scale"] == "数值（未标注单位）"
    assert card["unregistered"] is True
    # 无值可推断 → 仍如实「未登记」
    assert api.help_card("ghost", None)["type"] == "未登记"


def test_soft_display_does_not_claim_text_type() -> None:
    """_soft_display 默认不再声称 type=str；显式类型调用不受影响。"""
    assert fm_mod._soft_display("说明").type == ""
    assert fm_mod._soft_display("每回合破坏值", "int").type == "int"


def test_settings_battle_real_machine_inference() -> None:
    """实机复现：settings.battle 的数值/布尔字段不再被标成文本/不适用。"""
    d = api.entry_detail("veinborn", "settings", "battle", root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    mult = by["enrage_damage_mult"]
    assert mult["type"] == "number"                       # 表单 chip 也纠偏
    assert mult["help_card"]["type"] == "数值（小数）"
    assert mult["help_card"]["type_source"] == "元数据未登记，按实际值推断"
    chance = by["fatigue_stagger_chance"]["help_card"]
    assert chance["scale"] == "疑似比例（当前值在 0~1；元数据未标注单位）"
    assert by["stun_ko_skip"]["help_card"]["type"] == "布尔"
    assert by["stun_ko_skip"]["help_card"]["scale"] == "不适用（非数值字段）"


@pytest.mark.parametrize("fm,expected", [
    (FieldMeta(type="int", range_min=0, range_max=999), "建议 0 ~ 999"),
    (FieldMeta(type="int", range_min=0, range_max=999, zero_unlimited=True),
     "建议 0 ~ 999；0 = 不限"),
    (FieldMeta(type="number", range_min=0), "建议 ≥ 0"),
    (FieldMeta(type="number", range_max=500), "建议 ≤ 500"),
    (FieldMeta(type="str"), "未标注"),
])
def test_range_semantic(fm: FieldMeta, expected: str) -> None:
    assert api._range_semantic(fm) == expected


@pytest.mark.parametrize("value,expected", [
    (None, "无默认值"), (5, "5"), (0, "0"), (True, "是"), (False, "否"),
    ("common", "common"),
])
def test_default_semantic(value: object, expected: str) -> None:
    card = api.help_card("k", FieldMeta(type="str", default=value))
    assert card["default"] == expected


def test_help_card_required_enum_ref_and_help() -> None:
    fm = FieldMeta(type="enum", required=True, enum=("a", "b"),
                   ref_target=None, help="选一个。", label="类别")
    card = api.help_card("tier", fm)
    assert card["required"] is True
    assert card["enum"] == ["a", "b"]
    assert card["help"] == "选一个。"
    assert card["label"] == "类别" and card["key"] == "tier"
    assert card["unregistered"] is False
    ref = api.help_card("effect", FieldMeta(type="ref", ref_target="effect"))
    assert ref["ref_target"] == "effect"
    assert ref["scale"] == "不适用（非数值字段）"


def test_help_card_unregistered_falls_back() -> None:
    card = api.help_card("ghost", None)
    assert card["unregistered"] is True
    assert card["label"] == "ghost"
    assert card["help"] == ""
    assert card["type"] == "未登记" and card["scale"] == "未标注"
    assert card["default"] == "未标注" and card["range"] == "未标注"
    assert card["enum"] == [] and card["ref_target"] is None


# =====================================================================================
# 三、描述符接线：api.entry_detail / 列表列都带 help_card / unit / help
# =====================================================================================
def _first_entry(module: str) -> str:
    entries = api.list_entries("veinborn", module, root=CONTENT)["entries"]
    assert entries, module
    return str(entries[0]["id"])


def test_entry_descriptor_carries_help_card() -> None:
    d = api.entry_detail("veinborn", "skills", _first_entry("skills"), root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    assert by["power"]["unit"] == "%"
    assert by["power"]["help"]
    card = by["power"]["help_card"]
    assert card["scale"] == "百分比（数值自带 % 单位）"
    assert card["range"] == "建议 0 ~ 500"
    assert card["help"] == by["power"]["help"]
    assert by["cooldown"]["unit"] == "回合"


def test_enemy_list_column_carries_help_card() -> None:
    entries = api.list_entries("demo_full", "enemies", root=CONTENT)["entries"]
    d = api.entry_detail("demo_full", "enemies", str(entries[0]["id"]), root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    action_col = {c["key"]: c for c in by["actions"]["columns"]}["action"]
    assert action_col["help_card"]["type"] == "引用"
    assert action_col["help_card"]["ref_target"] == "action"


def test_module_without_help_still_serializes() -> None:
    """未写说明的模块（checkin）照常出描述符，help 为空、help_card 自动拼装齐全。"""
    d = api.entry_detail("veinborn", "checkin", _first_entry("checkin"), root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    name = by["name"]
    assert name["help"] == ""
    assert name["help_card"]["type"] == "文本"
    assert name["help_card"]["help"] == ""


def test_framework_has_no_hardcoded_help_text() -> None:
    """人工说明只准住在元数据层（field_meta）；编辑器框架不得写死业务文案。"""
    banned = ["技能倍率", "每段独立结算", "耳栓等级", "白值加算"]
    for path in (REPO / "qbot_rpg" / "web" / "api.py",
                 REPO / "qbot_rpg" / "web" / "editor_ops.py",
                 REPO / "qbot_rpg" / "web" / "static" / "index.html",
                 REPO / "scripts" / "editor_host.py"):
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path} 写死了业务说明：{word}"


# =====================================================================================
# 四、前端静态：说明模块 / 卡片容器 / aria / 键盘 / 视觉令牌
# =====================================================================================
def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def test_frontend_has_help_module_and_card_container() -> None:
    html = _html()
    assert "/* EDITOR_HELP_BEGIN */" in html and "/* EDITOR_HELP_END */" in html
    assert 'id="help-card"' in html and 'role="tooltip"' in html
    for token in ("function helpCardHtml(", "function helpLines(", "function helpPlace(",
                  "function helpTriggerHtml(", "function bindHelp("):
        assert token in html, token
    # 三处字段标签渲染都经过说明触发器（主表单 / 列表表头 / 对象子字段）
    assert html.count("helpTriggerHtml(") >= 4


def test_frontend_keyboard_and_aria_reachable() -> None:
    html = _html()
    assert 'tabindex="0"' in html
    assert 'role="button"' in html
    assert "aria-expanded" in html
    assert 'aria-label="字段说明' in html
    assert '"Escape"' in html and '"Enter"' in html
    # 注册表随渲染重建（不留陈旧 id）
    assert "resetHelpCards()" in html


def test_frontend_help_css_uses_tokens_and_scroll() -> None:
    html = _html()
    match = re.search(r"\.help-card\s*\{([^}]*)\}", html)
    assert match, "index.html 缺少 .help-card 样式"
    rule = match.group(1)
    assert "var(--line-strong)" in rule        # 细边框
    assert "var(--bg)" in rule                  # 深色底
    assert "max-height" in rule and "overflow: auto" in rule  # 长文可滚动
    assert "var(--font-mono)" in rule
    # 滚动条走细滚动条令牌
    assert ".help-card::-webkit-scrollbar" in html
    assert "var(--sb-size)" in html and "var(--sb-thumb)" in html
    # 卡片不抢字段焦点：fixed 定位由 helpPlace 计算
    assert "position: fixed" in rule


# =====================================================================================
# 五、node 直接执行 EDITOR_HELP 纯逻辑（状态机 / 拼装 / 定位 / 转义）
# =====================================================================================
def _marked_block(begin: str, end: str) -> str:
    html = _html()
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert match, f"index.html 缺少标记块 {begin} … {end}"
    return match.group(1)


_JS_HARNESS = r"""
global.esc = function (v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
const fs = require("fs");
eval(fs.readFileSync(process.argv[1], "utf8"));
const out = {};
const card = {
  key: "power", label: "威力", type: "数字", scale: "百分比（数值自带 % 单位）",
  range: "建议 0 ~ 500", default: "无默认值", required: false, enum: [],
  ref_target: null, unit: "%", help: "技能倍率。", unregistered: false
};
out.lines = helpLines(card);
out.html = helpCardHtml(card);
out.title = helpTitle(card);
// 无人工 help（自动拼装照常出，且没有「说明」行）
out.auto = helpLines({
  key: "k", label: "k", type: "文本", scale: "不适用（非数值字段）",
  range: "未标注", default: "无默认值", required: false, enum: [], ref_target: null, help: ""
});
// 推断来源（批4.6 补·实机问题①）：类型行显式带出「按实际值推断」
out.inferred = helpLines({
  key: "enrage_damage_mult", label: "狂暴伤害倍率", type: "数值（小数）",
  type_source: "元数据未登记，按实际值推断", scale: "数值（未标注单位）",
  range: "未标注", default: "无默认值", required: false, enum: [],
  ref_target: null, help: ""
});
// 候选值 / 引用目标 / 必填
out.enumRef = helpLines({
  key: "r", label: "引用", type: "引用", scale: "不适用（非数值字段）",
  range: "未标注", default: "无默认值", required: true,
  enum: ["a", "b"], ref_target: "effect", help: ""
});
// 未登记回退
out.unreg = helpCardHtml({
  key: "ghost", label: "ghost", type: "未登记", scale: "未标注", range: "未标注",
  default: "未标注", required: false, enum: [], ref_target: null, help: "", unregistered: true
});
// 转义
out.escaped = helpCardHtml({
  key: "x", label: "<b>", type: "文本", scale: "不适用（非数值字段）",
  range: "未标注", default: "无默认值", required: false, enum: [], ref_target: null,
  help: "<script>"
});
// 空卡
out.empty = helpCardHtml(null);
out.emptyLines = helpLines(null);
// 状态机
out.s0 = helpStateClosed();
out.hover = helpHover(out.s0, "h1");
out.hoverPinned = helpHover({ open: true, pinned: true, id: "h2" }, "h1");
out.unhover = helpUnhover(out.hover);
out.unhoverPinned = helpUnhover({ open: true, pinned: true, id: "h2" });
out.click = helpClick(out.s0, "h1");
out.clickAgain = helpClick({ open: true, pinned: true, id: "h1" }, "h1");
out.keyEnter = helpKey(out.s0, "h1", "Enter");
out.keySpace = helpKey(out.s0, "h1", " ");
out.keyEsc = helpKey({ open: true, pinned: true, id: "h1" }, "h1", "Escape");
out.visible = helpVisible({ open: true, pinned: true, id: "h1" }, "h1");
out.visibleOther = helpVisible({ open: true, pinned: true, id: "h1" }, "h2");
// 定位：优先下方、窄窗口避让、不与正在编辑的字段重叠
const anchor = { left: 300, top: 100, right: 360, bottom: 120 };
const avoid = { left: 16, top: 96, right: 900, bottom: 130 };
const size = { w: 260, h: 180 };
out.below = helpPlace(anchor, size, { w: 1000, h: 700 }, avoid, 6);
out.belowOverlap = helpOverlaps(out.below, avoid);
// 下方放不下（字段靠近视口底部）→ 翻到上方（仍不遮字段）
const anchor2 = { left: 300, top: 400, right: 360, bottom: 420 };
const avoid2 = { left: 16, top: 396, right: 900, bottom: 430 };
const tall = helpPlace(anchor2, { w: 260, h: 300 }, { w: 1000, h: 700 }, avoid2, 6);
out.tall = tall;
out.tallOverlap = helpOverlaps(tall, avoid2);
// 窄窗口：水平 clamp 进视口
const narrow = helpPlace(anchor, size, { w: 320, h: 700 }, avoid, 6);
out.narrow = narrow;
out.narrowInView = narrow.left >= 0 && narrow.right <= 320;
// 触发器：注册 + 键盘可达标注
out.trig = helpTriggerHtml(
  { key: "power", label: "威力", help_card: card }, "威力 <span class=\"fkey\">power</span>");
out.trigId = Object.keys(HELP_CARDS)[0];
out.registered = HELP_CARDS[out.trigId] === card;
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过说明气泡纯逻辑执行")
def test_help_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "help_module.js"
    src.write_text(_marked_block("/* EDITOR_HELP_BEGIN */", "/* EDITOR_HELP_END */"),
                   encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _JS_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)

    # ---- 拼装：人工说明优先，自动项齐全 ----
    keys = [r["k"] for r in out["lines"]]
    assert keys[0] == "说明"
    for k in ("类型", "数值/比例", "建议范围", "默认值", "填写要求"):
        assert k in keys
    assert out["title"] == "威力（power）"
    assert "技能倍率。" in out["html"]
    assert "百分比（数值自带 % 单位）" in out["html"]
    # 无人工 help → 没有「说明」行，但自动项照常
    assert "说明" not in [r["k"] for r in out["auto"]]
    assert any(r["k"] == "类型" for r in out["auto"])
    # 元数据未登记类型 → 类型行显式标注推断来源
    inferred_type = {r["k"]: r["v"] for r in out["inferred"]}["类型"]
    assert inferred_type == "数值（小数） · 元数据未登记，按实际值推断"
    # 枚举候选 / 引用目标 / 必填
    enum_ref = {r["k"]: r["v"] for r in out["enumRef"]}
    assert enum_ref["候选值"] == "a / b"
    assert enum_ref["引用目标"] == "effect"
    assert enum_ref["填写要求"] == "必填"
    # 未登记如实标注
    assert "元数据未登记" in out["unreg"]
    # 转义（不注入标签）
    assert "&lt;b&gt;" in out["escaped"] and "&lt;script&gt;" in out["escaped"]
    assert out["empty"] == "" and out["emptyLines"] == []

    # ---- 状态机：悬停开 / 固定不被悬停覆盖 / 点击切换 / 键盘可达 / Esc 关 ----
    assert out["s0"] == {"open": False, "pinned": False, "id": None}
    assert out["hover"] == {"open": True, "pinned": False, "id": "h1"}
    assert out["hoverPinned"] == {"open": True, "pinned": True, "id": "h2"}
    assert out["unhover"] == {"open": False, "pinned": False, "id": None}
    assert out["unhoverPinned"] == {"open": True, "pinned": True, "id": "h2"}
    assert out["click"] == {"open": True, "pinned": True, "id": "h1"}
    assert out["clickAgain"] == {"open": False, "pinned": False, "id": None}
    assert out["keyEnter"] == {"open": True, "pinned": True, "id": "h1"}
    assert out["keySpace"] == {"open": True, "pinned": True, "id": "h1"}
    assert out["keyEsc"] == {"open": False, "pinned": False, "id": None}
    assert out["visible"] is True and out["visibleOther"] is False

    # ---- 定位：不遮住正在编辑的字段；放不下会翻面；窄窗口收进视口 ----
    assert out["below"]["placement"] == "below"
    assert out["belowOverlap"] is False
    assert out["tall"]["placement"] == "above" and out["tallOverlap"] is False
    assert out["narrowInView"] is True

    # ---- 触发器：注册说明卡 + 键盘可达标注 ----
    assert 'class="flabel helpable"' in out["trig"]
    assert 'tabindex="0"' in out["trig"] and 'role="button"' in out["trig"]
    assert 'aria-expanded="false"' in out["trig"]
    assert "data-help=" in out["trig"]
    assert out["registered"] is True
