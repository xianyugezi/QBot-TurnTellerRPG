"""编辑器重写批3 · 分区页签（元数据驱动）测试。

覆盖任务书要求：
  · 分组**顺序**来自元数据（group_order）、**显示名**来自元数据（group_labels，缺省用组键）；
  · 元数据未声明分组的模块 → 单一默认分组兜底（现状保持）；
  · 页签带字段计数徽标；空分组有零计数 + 空态标记；分组内字段两列网格；
  · 切换分组**草稿不丢**（node 执行纯 JS 分组模块 + 草稿模块）；
  · 编辑器框架不写死任何内容包的业务分组词。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content.models import ModuleMeta
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

# 批3 起声明分组的模块（至少这几个；只加元数据、不加业务字段）
GROUPED_MODULES = ("skills", "enemies", "items", "equipment", "maps", "quest")


# ---------------------------------------------------------------------------
# 一、元数据声明：顺序 + 显示名
# ---------------------------------------------------------------------------
def test_named_modules_declare_ordered_groups_with_labels() -> None:
    table = api.field_meta_table()
    for mod in GROUPED_MODULES:
        meta = table.module(mod)
        assert meta is not None, mod
        assert 2 <= len(meta.group_order) <= 4, (mod, meta.group_order)
        assert len(set(meta.group_order)) == len(meta.group_order), mod  # 无重复
        # 显示名解析后一律非空（缺省回退组键——技能页的组键本身就是中文名）
        for g in meta.group_order:
            assert meta.group_labels.get(g, g), (mod, g)
        # 每个分组的成员键都映射到某个已声明/已命名的组
        known = set(meta.group_order) | set(meta.group_labels)
        assert set(meta.field_groups.values()) <= known, mod
    # 批3 新模块必须真的声明了「显示名 ≠ 组键」——证明显示名可声明、不是写死的
    for mod in ("enemies", "items", "maps", "quest"):
        meta = table.module(mod)
        assert meta is not None
        assert set(meta.group_labels) == set(meta.group_order), mod
        assert any(meta.group_labels[g] != g for g in meta.group_order), mod


def test_group_labels_default_to_group_key() -> None:
    mmeta = ModuleMeta(
        entry_type="list",
        fields={},
        field_groups={"a": "g1", "b": "g2"},
        group_order=("g1", "g2", "g3"),
        group_labels={"g1": "甲"},  # g2/g3 未声明显示名 → 用组键
    )
    groups = api._group_summary(
        [{"group": "g1"}, {"group": "g2"}, {"group": "g2"}], mmeta)
    assert [(g["name"], g["label"], g["count"]) for g in groups] == [
        ("g1", "甲", 1), ("g2", "g2", 2), ("g3", "g3", 0),
    ]


def test_group_order_follows_declaration_not_first_seen() -> None:
    """字段出现顺序与声明顺序相反时，页签顺序仍按声明。"""
    mmeta = ModuleMeta(
        entry_type="list", fields={},
        field_groups={"z": "second", "a": "first"},
        group_order=("first", "second"),
    )
    groups = api._group_summary(
        [{"group": "second"}, {"group": "first"}], mmeta)
    assert [g["name"] for g in groups] == ["first", "second"]


def test_declared_empty_group_kept_with_zero_count() -> None:
    mmeta = ModuleMeta(entry_type="list", fields={},
                       field_groups={"a": "only"},
                       group_order=("only", "unused"),
                       group_labels={"only": "有", "unused": "无"})
    groups = api._group_summary([{"group": "only"}], mmeta)
    assert groups == [
        {"name": "only", "label": "有", "count": 1},
        {"name": "unused", "label": "无", "count": 0},
    ]


def test_default_single_group_fallback_unchanged() -> None:
    """无分组声明的模块仍只有单一默认分组（现状保持）。"""
    table = api.field_meta_table()
    meta = table.module("effects")
    assert meta is not None and not meta.field_groups and not meta.group_order
    groups = api._group_summary([{"group": api.DEFAULT_GROUP}], meta)
    assert groups == [{"name": api.DEFAULT_GROUP, "label": api.DEFAULT_GROUP, "count": 1}]


# ---------------------------------------------------------------------------
# 二、真实条目：分组顺序/显示名/计数
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mod", GROUPED_MODULES)
def test_entry_groups_match_declared_order_and_labels(mod: str) -> None:
    meta = api.field_meta_table().module(mod)
    assert meta is not None
    eid = api.list_entries("veinborn", mod, root=CONTENT)["entries"][0]["id"]
    detail = api.entry_detail("veinborn", mod, eid, root=CONTENT)
    groups = detail["groups"]
    assert [g["name"] for g in groups] == list(meta.group_order), (mod, groups)
    for g in groups:
        assert g["label"] == meta.group_labels.get(g["name"], g["name"])
    assert sum(g["count"] for g in groups) == detail["field_count"]
    assert detail["group_count"] == len(groups)


def test_skills_group_names_still_come_from_metadata() -> None:
    detail = api.entry_detail("veinborn", "skills", "rb_slash", root=CONTENT)
    assert [g["name"] for g in detail["groups"]] == ["基本", "数值", "效果列表", "文本"]
    assert all(g["label"] == g["name"] for g in detail["groups"])  # 未声明显示名 → 回退组键
    assert sum(g["count"] for g in detail["groups"]) == detail["field_count"]


# ---------------------------------------------------------------------------
# 三、切换分组不丢草稿（node 执行 index.html 内联纯 JS 模块）
# ---------------------------------------------------------------------------
_GROUPS_HARNESS = r"""
const D = require(process.argv[1]);
const G = require(process.argv[2]);
const out = {};
const groups = [
  { name: "stats", label: "数值", count: 3 },
  { name: "base", label: "基本", count: 1 },
  { name: "void", label: "空组", count: 0 },
  { name: "nameless" },
];
const fields = [
  { key: "a", group: "base" },
  { key: "b", group: "stats" },
  { key: "c", group: "stats" },
  { key: "d", group: "stats" },
  { key: "extra", group: "loose" },
];
const v = G.view(groups, fields);
out.names = v.map(function (x) { return x.name; });
out.labels = v.map(function (x) { return x.label; });
out.counts = v.map(function (x) { return x.count; });
out.empty = v.map(function (x) { return x.empty; });
out.baseKeys = v[1].fields.map(function (f) { return f.key; });
out.looseLabel = v[4].label;      // 未声明显示名的兜底组 → 用组键
out.namelessLabel = v[3].label;   // 有 name 无 label → 用 name
out.activeInit = v.active;

// 切组不丢草稿：草稿按字段键持有，切到不含该字段的组后计数不变
const draft = D.newDraft();
D.set(draft, "c", 42, 0);         // c 属于 stats（第 0 组）
out.draftBefore = D.count(draft);
G.switchGroup(v, 1);              // 切到 base
out.activeAfter = v.active;
out.draftAfterSwitch = D.count(draft);
out.draftKeysAfterSwitch = D.keys(draft);
G.switchGroup(v, 2);              // 切到空组
out.emptyActiveFields = G.activeFields(v).length;
out.draftAfterEmpty = D.count(draft);
G.switchGroup(v, 99);             // 越界 → 归 0
out.activeReset = v.active;
process.stdout.write(JSON.stringify(out));
"""


def _marked_block(begin: str, end: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert match, f"index.html 缺少标记块 {begin} … {end}"
    return match.group(1)


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 分组/草稿语义执行")
def test_group_js_semantics_and_draft_survives_switch(tmp_path: Path) -> None:
    draft_src = tmp_path / "draft.js"
    draft_src.write_text(_marked_block("/* EDITOR_DRAFT_BEGIN */", "/* EDITOR_DRAFT_END */"),
                         encoding="utf-8")
    groups_src = tmp_path / "groups.js"
    groups_src.write_text(_marked_block("/* EDITOR_GROUPS_BEGIN */", "/* EDITOR_GROUPS_END */"),
                          encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _GROUPS_HARNESS, str(draft_src), str(groups_src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)
    # 顺序 + 显示名 + 计数 + 空分组标记
    assert out["names"] == ["stats", "base", "void", "nameless", "loose"]
    assert out["labels"] == ["数值", "基本", "空组", "nameless", "loose"]
    assert out["counts"] == [3, 1, 0, 0, 1]
    assert out["empty"] == [False, False, True, True, False]
    assert out["baseKeys"] == ["a"]
    assert out["looseLabel"] == "loose" and out["namelessLabel"] == "nameless"
    assert out["activeInit"] == 0
    # 切组草稿不丢
    assert out["draftBefore"] == 1
    assert out["activeAfter"] == 1
    assert out["draftAfterSwitch"] == 1 and out["draftKeysAfterSwitch"] == ["c"]
    assert out["emptyActiveFields"] == 0
    assert out["draftAfterEmpty"] == 1
    assert out["activeReset"] == 0


# ---------------------------------------------------------------------------
# 四、前端接线 + 视觉小修
# ---------------------------------------------------------------------------
def test_frontend_tabs_use_metadata_labels_and_empty_state() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("EditorGroups.view", "EditorGroups.switchGroup", "esc(g.label)",
                  "g.empty", "gempty", "该分组暂无字段"):
        assert token in html, token
    # 页签不再直接显示分组键（显示名来自元数据 label）
    assert "esc(g.name) + \" <b>\"" not in html


def test_frontend_cost_draft_survives_group_switch_wiring() -> None:
    html = HTML.read_text(encoding="utf-8")
    # 切组只切视图索引 + 重标脏，不得丢弃草稿
    assert "EditorGroups.switchGroup(tabs, idx)" in html
    bind_tabs = html.split("function bindTabs()")[1].split("function fieldRow")[0]
    assert "discardDraft()" not in bind_tabs
    assert "markDirty();  // 跨组编辑过的字段仍标脏" in html


def test_frontend_empty_value_wording_unified() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "该条目未写此字段" not in html
    assert "var EMPTY_TEXT" in html
    assert html.count("（空）") == 1  # 只保留常量定义这一处字面量
    assert html.count("EMPTY_TEXT") >= 4


def test_frontend_row_baseline_and_topbar_nowrap_css() -> None:
    html = HTML.read_text(encoding="utf-8")
    # 双列基线对齐：标签固定为单行控件高度的盒子；网格行等高
    assert ".row > .rlab" in html and "min-height: var(--h-ctl)" in html
    assert "align-items: stretch" in html
    # 顶栏窄窗口不换行：nowrap + 省略号 + 窄屏隐藏来源标注
    assert "white-space: nowrap; overflow: hidden;" in html
    assert "text-overflow: ellipsis" in html
    assert "@media (max-width: 900px)" in html


def test_editor_framework_has_no_group_business_words() -> None:
    """编辑器框架不得写死任何内容包的分组词（分组名只允许出现在内容元数据里）。"""
    targets = [
        REPO / "qbot_rpg" / "web" / "api.py",
        REPO / "qbot_rpg" / "web" / "editor_ops.py",
        REPO / "qbot_rpg" / "web" / "__init__.py",
        REPO / "qbot_rpg" / "web" / "static" / "index.html",
        REPO / "scripts" / "editor_host.py",
    ]
    banned = ["基本", "效果列表", "附加效果"]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path} 写死了业务分组名：{word}"
