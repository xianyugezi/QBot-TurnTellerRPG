"""全量模板表门禁测试（2026-09-12 消息模板重构·批1 基建）。

覆盖：
① 表结构（templates dict、键值均为 str）；
② 表并入聚合：DEFAULT_TEMPLATES / tpl_of 走表文本；内容包覆盖仍可覆盖同 key；
③ 占位符白名单自动派生（表 key 在白名单，且与文本占位符一致）；
④ 宽度校验 0 FAIL（scripts/check_template_width.py，手机QQ 14 全角封顶）；
（表值 emoji 纪律断言在 test_emoji_discipline.py::test_template_table_no_emoji。）

脚本经 importlib 加载（scripts 无 __init__.py，对齐 test_check_m7_content 模式）。
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLE = REPO / "qbot_rpg" / "core" / "templates" / "template_table.json"
_CHECK = REPO / "scripts" / "check_template_width.py"
_spec = importlib.util.spec_from_file_location("check_template_width_mod", _CHECK)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

# T6/T7 复核修复：手工冻结集合（独立于表值的第三方对照，见该文件说明）。
_FROZEN_PATH = REPO / "tests" / "unit" / "_template_frozen_sets.py"
_spec_frozen = importlib.util.spec_from_file_location("template_frozen_sets", _FROZEN_PATH)
_frozen = importlib.util.module_from_spec(_spec_frozen)  # type: ignore[arg-type]
_spec_frozen.loader.exec_module(_frozen)  # type: ignore[union-attr]


def _doc():
    return json.loads(TABLE.read_text(encoding="utf-8"))


def test_table_shape():
    """表结构：templates 为 dict（可空），键非空、值为 str。"""
    doc = _doc()
    assert isinstance(doc.get("templates"), dict)
    for key, text in doc["templates"].items():
        assert isinstance(key, str) and key
        assert isinstance(text, str) and text


def test_table_merges_into_aggregate():
    """表条目录入聚合：DEFAULT_TEMPLATES 与 tpl_of（无 ctx）均走表文本。"""
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES, tpl_of

    for key, text in _doc()["templates"].items():
        assert DEFAULT_TEMPLATES[key] == text, f"聚合未走表：{key}"
        assert tpl_of(None, key) == text, f"tpl_of 未走表：{key}"


def test_content_pack_can_cover_table_key():
    """内容包覆盖链对表 key 生效：resolve_templates 同名覆盖。"""
    doc = _doc()
    if not doc["templates"]:
        return  # 空表（迁移前）跳过
    from qbot_rpg.core.templates import resolve_templates

    key = next(iter(doc["templates"]))
    merged = resolve_templates({key: "覆盖样例"})
    assert merged[key] == "覆盖样例"


def test_whitelist_matches_frozen_allowlist():
    """T6：占位符名必须等于**手工冻结**的期望集合（原「⊆ 自动派生白名单」恒真）。

    表值占位符（全局并集）与 ``_template_frozen_sets.FROZEN_PLACEHOLDERS`` 双向相等：
      - 表内出现未登记占位符名（拼错/新机制）→ 失败，必须在冻结集显式登记；
      - 冻结集有表内已不用的名字（陈旧）→ 失败，鞭策同步清理。
    逐键再断言自动派生白名单只含冻结名（派生白名单不得超出允许名集）。
    """
    from qbot_rpg.core.templates import PLACEHOLDER_WHITELIST

    used: set = set()
    for key, text in _doc()["templates"].items():
        phs = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", text))
        used |= phs
        extra = set(PLACEHOLDER_WHITELIST[key]) - _frozen.FROZEN_PLACEHOLDERS
        assert not extra, f"{key} 白名单含未登记占位符：{extra}"
    assert used == set(_frozen.FROZEN_PLACEHOLDERS), (
        f"占位符名集合漂移：新增 {sorted(used - set(_frozen.FROZEN_PLACEHOLDERS))} / "
        f"冻结集陈旧 {sorted(set(_frozen.FROZEN_PLACEHOLDERS) - used)}"
    )


def test_width_no_fail():
    """宽度校验：表内 0 FAIL（14 全角封顶；WARN 由独立冻结清单门禁，见下条）。"""
    fails, _warns = _mod.scan(TABLE)
    assert not fails, "宽度 FAIL：\n" + "\n".join(
        f"{r['key']} L{r['line_no']} {r['half']}/28 {r['line']!r}" for r in fails[:20]
    )


def test_width_warn_matches_frozen_allowlist():
    """T7：WARN 集合 == 显式冻结豁免清单 → 新增 WARN 直接失败。

    新增 WARN 的正确处理：改窄该行，或在 template_table.json 的 ``meta.prose_keys``
    显式登记豁免（登记后扫描器整键跳过、不再产生 WARN）。此处同时断言 WARN 键未被
    prose 豁免（二者口径不得重叠）。
    """
    _fails, warns = _mod.scan(TABLE)
    actual = {(r["key"], r["line_no"], r["half_est"]) for r in warns}
    expected = set(_frozen.WIDTH_WARN_ALLOWLIST)
    assert actual == expected, (
        f"宽度 WARN 漂移：新增 {sorted(actual - expected)} / 已消除未删登记 "
        f"{sorted(expected - actual)}；新增 WARN 须改窄或登记 meta.prose_keys"
    )
    prose = set((_doc().get("meta") or {}).get("prose_keys") or {})
    assert not (prose & {r["key"] for r in warns}), "WARN 键不应同时登记 prose_keys 豁免"


def test_derived_line_registered_as_intentional_exemption():
    """技能详情派生行（遗留 #37）：登记为**有意豁免** —— 整行全量显示、不折行。

    口径来源：2026-09-12 用户拍板（同「怪物状态」行）。键 `skill_info_derived`，
    经 meta.prose_keys 跳过宽度门禁（非介绍类豁免，属有意超宽）。
    """
    meta = _doc().get("meta") or {}
    reason = (meta.get("prose_keys") or {}).get("skill_info_derived", "")
    assert reason, "skill_info_derived 未登记为有意豁免"
    assert "不折行" in reason and "用户拍板" in reason
    assert "派生：{names}" in _doc()["templates"].get("skill_info_derived", "")


def test_load_table_tolerates_corrupt_table(tmp_path):
    """M4（复核修复 2026-09-12）：JSON 截断 / 编码损坏 / 文件缺失 → 空表回落，绝不抛。"""
    from qbot_rpg.core.templates import _load_table

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{ not json", encoding="utf-8")
    assert _load_table(bad_json) == {}

    bad_utf = tmp_path / "bad_utf.json"
    bad_utf.write_bytes(b'{"templates": {"a": "\xff\xfe"}}')       # 非法 UTF-8
    assert _load_table(bad_utf) == {}

    assert _load_table(tmp_path / "missing.json") == {}

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"templates": {"k": "v", "n": 1}}), encoding="utf-8")
    assert _load_table(good) == {"k": "v"}                          # 只收 str 值


def test_hud_lines_registered_as_intentional_exemption():
    """L3/L6（复核修复 2026-09-12）：HUD 三数值键 +「怪物状态」行登记 meta.prose_keys。

    口径来源：用户 2026-09-12 拍板（HUD 数值行极端大数值允许超 28 半角；
    怪物状态行整行全量枚举、不折行）→ 宽度门禁跳过。
    """
    prose = (_doc().get("meta") or {}).get("prose_keys") or {}
    for key in ("battle_hud_enemy_status", "battle_hud_player_hp",
                "battle_hud_player_mp", "battle_hud_enemy_hp"):
        assert prose.get(key), f"{key} 未登记 prose_keys"
        assert "2026-09-12" in prose[key] and "用户拍板" in prose[key]

    # 登记后宽度门禁跳过 → HUD 三数值键不再进 WARN
    _fails, warns = _mod.scan(TABLE)
    warned = {r["key"] for r in warns}
    assert not (warned & {"battle_hud_player_hp", "battle_hud_player_mp",
                          "battle_hud_enemy_hp"})


# ---------------------------------------------------------------------------
# L1/L2（复核修复 2026-09-12）：缺 key 回落默认表 + 未知键 warning/strict
# ---------------------------------------------------------------------------


def test_render_template_falls_back_to_default_for_partial_map():
    """L1：局部覆盖 templates 缺 key → 回落 DEFAULT_TEMPLATES（不再静默返空串）。

    契约边界：
      - 覆盖 dict 缺 key → 默认表值；
      - 覆盖 dict 显式置空串 → 仍按覆盖生效（空行语义，不回退）；
      - 默认表也没有的 key → 空串。
    """
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES, render_template, tpl_of

    key = "basic_register_gate"
    assert render_template({}, key, {}) == DEFAULT_TEMPLATES[key]
    assert tpl_of({"templates": {"unrelated_key": "x"}}, key) == DEFAULT_TEMPLATES[key]
    assert tpl_of({"templates": {key: "自定义门槛"}}, key) == "自定义门槛"
    assert tpl_of({"templates": {key: ""}}, key) == ""
    assert render_template({}, "definitely_not_a_key_xyz", {}) == ""


def test_resolve_templates_warns_on_unknown_key(caplog):
    """L2：内容包未知 key 记 warning（不再静默）；strict=True 抛错供校验脚本用。"""
    from qbot_rpg.core.templates import resolve_templates

    with caplog.at_level(logging.WARNING, logger="qbot_rpg.core.templates"):
        merged = resolve_templates({"no_such_tpl_key_xyz": "拼错", "basic_register_gate": "覆盖"})
    assert merged["basic_register_gate"] == "覆盖"
    assert "no_such_tpl_key_xyz" not in merged
    assert any("no_such_tpl_key_xyz" in r.getMessage() for r in caplog.records), \
        "未知 key 未记 warning"

    with pytest.raises(ValueError, match="不在表内"):
        resolve_templates({"no_such_tpl_key_xyz": "拼错"}, strict=True)
