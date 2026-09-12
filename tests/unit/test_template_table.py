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
