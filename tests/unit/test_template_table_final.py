"""消息模板重构 · 终态门禁（2026-09-12 收口）。

迁移期每个分区文件各有一条「守卫测试」（断言该分区键已迁表 + 分区为空壳）；
终态分区文件删除后这些守卫统一作废 → 本文件以**一条**门禁覆盖同样的防护：

  ① 分区文件已删除：core/templates/ 下只剩 __init__.py / base.py / template_table.json
  ② 表内每个 key 的占位符 ⊆ 聚合白名单（防内容包拼错 key 导致占位符不替换）
  ③ 聚合默认表包含全部表内 key（表为唯一存储 → 聚合必须完备）
  ④ base.py 核心键仍在（非迁移范围，不得被误删）
  ⑤ test_demo 内容包无「表外键」（收敛为仅有意差异：包内 key 必须存在于表内）
"""

from __future__ import annotations

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
    """② 表内模板块占位符必须在白名单内（否则渲染时不被替换）。"""
    for key, tpl in TABLE_TEMPLATES.items():
        found = set(_PLACEHOLDER_RE.findall(tpl))
        assert found <= PLACEHOLDER_WHITELIST.get(key, set()), f"{key} 占位符未登记白名单"


def test_aggregate_contains_all_table_keys() -> None:
    """③ 表为唯一存储 → 聚合默认表必须包含全部表内 key（逐字一致）。"""
    missing = [k for k, v in TABLE_TEMPLATES.items() if DEFAULT_TEMPLATES.get(k) != v]
    assert missing == [], f"聚合表缺失/不一致的 key: {missing[:10]}"


def test_base_templates_still_present() -> None:
    """④ base.py 核心键仍在（非迁移范围）。"""
    assert DEFAULT_TEMPLATES.get("register_gate"), "base 核心键丢失"


def test_test_demo_pack_has_no_unknown_keys() -> None:
    """⑤ test_demo 内容包无表外键（收敛为仅有意差异）。"""
    pack = json.loads((_REPO / "content" / "test_demo" / "templates.json").read_text())
    extra = sorted(k for k in pack if k not in TABLE_TEMPLATES)
    assert extra == [], f"内容包含表外旧键（应删除或补表）: {extra[:10]}"


def test_table_key_count_not_regressed() -> None:
    """键数下限（防误删整段）：迁移收口时 706 键（删 7 死键后）。"""
    assert len(TABLE_TEMPLATES) >= 700
