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
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLE = REPO / "qbot_rpg" / "core" / "templates" / "template_table.json"
_CHECK = REPO / "scripts" / "check_template_width.py"
_spec = importlib.util.spec_from_file_location("check_template_width_mod", _CHECK)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


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


def test_whitelist_derived():
    """白名单派生：表 key 在白名单内，且登记集合 ⊇ 文本占位符。"""
    from qbot_rpg.core.templates import PLACEHOLDER_WHITELIST

    for key, text in _doc()["templates"].items():
        assert key in PLACEHOLDER_WHITELIST, f"缺白名单：{key}"
        phs = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", text))
        assert phs <= set(PLACEHOLDER_WHITELIST[key]), f"白名单不一致：{key}"


def test_width_no_fail():
    """宽度校验：表内 0 FAIL（14 全角封顶；WARN 为提示，各批人工核大数值场景）。"""
    fails, _warns = _mod.scan(TABLE)
    assert not fails, "宽度 FAIL：\n" + "\n".join(
        f"{r['key']} L{r['line_no']} {r['half']}/28 {r['line']!r}" for r in fails[:20]
    )


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
