"""消息模板重构 · 终态门禁（2026-09-12 收口）。

迁移期每个分区文件各有一条「守卫测试」（断言该分区键已迁表 + 分区为空壳）；
终态分区文件删除后这些守卫统一作废 → 本文件以**一条**门禁覆盖同样的防护：

  ① 分区文件已删除：core/templates/ 下只剩 __init__.py / base.py / template_table.json
  ② 表内每个 key 的占位符 ⊆ **手工冻结的允许名集**（T6：原自动派生白名单恒真，已弃用）
  ③ 聚合默认表包含全部表内 key（表为唯一存储 → 聚合必须完备）
  ④ base.py 核心键仍在（非迁移范围，不得被误删）
  ⑤ 全部 content/*/templates.json 内容包无「表外键」（T8：原只查 test_demo）
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

from qbot_rpg.core.templates import (
    DEFAULT_TEMPLATES,
    PLACEHOLDER_WHITELIST,
    TABLE_TEMPLATES,
)

_TPL_DIR = pathlib.Path(__file__).resolve().parents[2] / "qbot_rpg" / "core" / "templates"
_REPO = _TPL_DIR.parents[2]
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")

# T6 复核修复：手工冻结占位符允许名（独立于表值的对照，见 _template_frozen_sets.py）。
_FROZEN_PATH = _REPO / "tests" / "unit" / "_template_frozen_sets.py"
_spec_frozen = importlib.util.spec_from_file_location("template_frozen_sets", _FROZEN_PATH)
_frozen = importlib.util.module_from_spec(_spec_frozen)  # type: ignore[arg-type]
_spec_frozen.loader.exec_module(_frozen)  # type: ignore[union-attr]

#: 迁移期 22 个分区文件（终态必须全部删除）
_MIGRATED_PARTITIONS = (
    "achievement_tpl.py", "alchemy_tpl.py", "basic_rem_tpl.py", "battle_tpl.py",
    "checkin_tpl.py", "codex_tpl.py", "dialog_tpl.py", "dummy_tpl.py", "enhance_tpl.py",
    "explore_tpl.py", "fishing_tpl.py", "forge_tpl.py", "gift_tpl.py", "investigate_tpl.py",
    "job_tpl.py", "log_tpl.py", "pvp_tpl.py", "quest_tpl.py", "register_rem_tpl.py",
    "shortcut_tpl.py", "use_tpl.py",
)


def test_partitions_removed() -> None:
    """① 分区文件已删除（终态：只剩加载器 + base + 全量表）。"""
    left = sorted(p.name for p in _TPL_DIR.glob("*_tpl.py"))
    assert left == [], f"迁移期分区文件应已全部删除，仍存在: {left}"
    assert sorted(p.name for p in _TPL_DIR.glob("*.py")) == ["__init__.py", "base.py"]


def test_table_placeholders_covered_by_whitelist() -> None:
    """② 表内占位符必须落在**手工冻结**的允许名集内（T6：原断言恒真）。

    原 `found ⊆ PLACEHOLDER_WHITELIST[key]` 中右侧由同一份表值自动派生 → 恒真。
    现改为对照 `_template_frozen_sets.FROZEN_PLACEHOLDERS`：双向相等（表内不得有
    未登记占位符名；冻结集不得残留表内已不用的名字）。
    """
    used: set = set()
    for key, tpl in TABLE_TEMPLATES.items():
        found = set(_PLACEHOLDER_RE.findall(tpl))
        extra = set(PLACEHOLDER_WHITELIST.get(key, set())) - _frozen.FROZEN_PLACEHOLDERS
        assert not extra, f"{key} 自动派生白名单含未登记占位符：{extra}"
        used |= found
    assert used == set(_frozen.FROZEN_PLACEHOLDERS), (
        f"表内占位符名漂移：未登记 {sorted(used - set(_frozen.FROZEN_PLACEHOLDERS))} / "
        f"冻结集陈旧 {sorted(set(_frozen.FROZEN_PLACEHOLDERS) - used)}"
    )


def test_aggregate_contains_all_table_keys() -> None:
    """③ 表为唯一存储 → 聚合默认表必须包含全部表内 key（逐字一致）。"""
    missing = [k for k, v in TABLE_TEMPLATES.items() if DEFAULT_TEMPLATES.get(k) != v]
    assert missing == [], f"聚合表缺失/不一致的 key: {missing[:10]}"


def test_base_templates_still_present() -> None:
    """④ base.py 核心键仍在（非迁移范围）。"""
    assert DEFAULT_TEMPLATES.get("register_gate"), "base 核心键丢失"


def test_all_content_packs_have_no_unknown_keys() -> None:
    """⑤ T8：**全部** content/*/templates.json 无表外键（原只查 test_demo）。

    内容包拼错/表删键时，`resolve_templates` 会静默丢弃（L2 已加 warning），本门禁
    遍历所有内容包把该问题前移到测试期；并顺手断言 `resolve_templates(strict=True)`
    对表外包抛错（校验脚本可用）。
    """
    from qbot_rpg.core.templates import resolve_templates

    packs = sorted((_REPO / "content").glob("*/templates.json"))
    assert packs, "未发现任何 content/*/templates.json（路径/布局变动？）"
    problems: dict[str, list[str]] = {}
    for path in packs:
        doc = json.loads(path.read_text(encoding="utf-8"))
        tpl_raw = doc.get("templates") if isinstance(doc, dict) else None
        pack = tpl_raw if isinstance(tpl_raw, dict) else {}
        try:
            resolve_templates(pack, strict=True)     # 表外键 → ValueError（校验脚本口径）
        except ValueError as exc:
            problems[path.parent.name] = [str(exc)]
        extra = sorted(k for k in pack if k not in TABLE_TEMPLATES)
        if extra:
            problems.setdefault(path.parent.name, []).extend(extra[:10])
    assert problems == {}, f"内容包含表外旧键（应删除或补表）: {problems}"


def test_table_key_count_not_regressed() -> None:
    """键数下限（防误删整段）：迁移收口时 706 键（删 7 死键后）。"""
    assert len(TABLE_TEMPLATES) >= 700
