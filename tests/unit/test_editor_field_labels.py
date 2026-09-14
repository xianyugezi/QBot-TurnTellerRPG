"""编辑器重写批3.5 · 字段中文名（中文名 + 原始键并列显示）+ 各模块字段名补全 + V8 修复。

覆盖任务书要求：
  · 显示层并列：字段标签 =「中文名 + 弱化原始键」；无中文名时只显示原始键（现状）；
    渲染逻辑集中在一处（fieldLabelHtml），任何模块/字段同一逻辑，框架不写死业务字段名；
  · 元数据层补全：enemies/items/equipment/maps/quest（本批必做）+ effects/statuses/marks/
    skill_chains/action/jobs（余量补全）的字段中文名表；只加 label，不动校验契约；
  · V8：枚举候选（FieldMeta.enum → 纯字符串）与引用候选（{id,name} 对象）形态归一，
    当前值确在候选内时不得再标「当前值·不在候选内」。
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta as fm_mod
from qbot_rpg.content import field_meta_pack as fmp
from qbot_rpg.content.models import FieldMeta
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _schema_table():
    """批B：展示文案已下放到包；把两个真实包的声明并成「schema 覆盖面」表。"""
    table = api.field_meta_table()
    for pack in ("veinborn", "test_demo"):
        decl = fmp.load_field_meta(CONTENT / pack)
        if decl is not None:
            table = fmp.merge_field_meta_table(table, decl)
    return table


# 本位批必做的 5 个模块 + 余量补全的 6 个模块
REQUIRED_MODULES = ("enemies", "items", "equipment", "maps", "quest")
EXTRA_MODULES = ("effects", "statuses", "marks", "skill_chains", "action", "jobs")


# ---------------------------------------------------------------------------
# 一、元数据：字段中文名表补全
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mod", list(REQUIRED_MODULES) + list(EXTRA_MODULES))
def test_module_fields_all_have_chinese_labels(mod: str) -> None:
    meta = _schema_table().module(mod)
    assert meta is not None and meta.fields, mod
    missing = [k for k, f in meta.fields.items() if not f.label]
    assert not missing, (mod, missing)
    # 至少有一部分字段是「中文名 ≠ 原始键」（证明真的并列，而不是回退键名）
    assert any(f.label != k for k, f in meta.fields.items()), mod


def test_required_label_tables_cover_declared_keys() -> None:
    """本批必做模块：字段名表要覆盖字段表里出现过的键（漏键 → 界面只能显示原始键）。"""
    table = _schema_table()
    for mod in REQUIRED_MODULES:
        meta = table.module(mod)
        assert meta is not None
        uncovered = {k for k, f in meta.fields.items() if f.label == k}
        assert not uncovered, (mod, uncovered)


def test_equipment_reuses_items_labels_plus_excludes() -> None:
    table = _schema_table()
    items = table.module("items")
    equipment = table.module("equipment")
    assert items is not None and equipment is not None
    assert equipment.fields["excludes"].label == "互斥部位"
    # 装备与物品共享字段表：物品有中文名的公共键，装备也有中文名（文案可因旧键标注而不同）。
    for key in set(items.fields) & set(equipment.fields):
        if items.fields[key].label:
            assert equipment.fields[key].label, key


def test_group_display_names_are_not_reused_as_field_labels() -> None:
    """批3 曾把「组显示名」误当「字段中文名」传参；本批起字段名必须是字段级术语。"""
    meta = _schema_table().module("enemies")
    assert meta is not None
    assert meta.fields["stats"].label != meta.group_labels["stats"]
    assert meta.fields["actions"].label != meta.group_labels["actions"]
    assert meta.fields["drops"].label != meta.group_labels["drops"]


def test_decoration_is_label_only_and_keeps_validation_contract() -> None:
    """_decorate_field_meta 只补 label/group：type/required/default/enum/children 原样。"""
    children = {"x": FieldMeta(type="int", range_min=0, range_max=9, label="内层")}
    original = FieldMeta(
        type="enum", required=True, default="a", enum=("a", "b"),
        range_min=1, range_max=3, probability=True, soft_label=True,
        allow_negative=True, children=children, multiline=True,
    )
    out = fm_mod._decorate_field_meta(
        {"k": original}, {"k": "g1"}, {"k": "中文名"})
    got = out["k"]
    assert got.label == "中文名" and got.group == "g1"
    for f in dataclasses.fields(FieldMeta):
        if f.name in ("label", "group"):
            continue
        assert getattr(got, f.name) == getattr(original, f.name), f.name


def test_existing_field_label_wins_over_table() -> None:
    """字段自带 label（如装备词条）优先，字段名表不得覆盖。"""
    own = FieldMeta(type="number", label="自带名")
    out = fm_mod._decorate_field_meta({"k": own}, {}, {"k": "表名"})
    assert out["k"].label == "自带名"


# ---------------------------------------------------------------------------
# 二、真实条目：描述符同时带中文名与原始键，枚举值来自元数据
# ---------------------------------------------------------------------------
def test_enemy_descriptor_has_chinese_label_and_raw_key() -> None:
    d = api.entry_detail("veinborn", "enemies", "gravelcrown", root=CONTENT)
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["tier"]["label"] == "怪物档位"
    assert by_key["stats"]["label"] == "属性"
    assert by_key["pv"]["label"] == "防护值"
    # V8 数据源：tier 的候选里确实含实际值 boss（纯字符串候选，形态由前端归一）
    assert "boss" in by_key["tier"]["enum"]


# ---------------------------------------------------------------------------
# 三、前端：标签并列渲染 + V8 候选归一（node 执行 index.html 内联纯 JS）
# ---------------------------------------------------------------------------
def _marked_block(begin: str, end: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert match, f"index.html 缺少标记块 {begin} … {end}"
    return match.group(1)


_FRONTEND_HARNESS = r"""
global.esc = function (v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
const fs = require("fs");
// 标记块是浏览器内联的普通函数声明（非 UMD 模块）→ 直接 eval 到当前作用域
eval(fs.readFileSync(process.argv[1], "utf8"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
out.juxt = fieldLabelHtml("标识", "id");
out.same = fieldLabelHtml("id", "id");
out.noLabel = fieldLabelHtml("", "ghost");
out.noKey = fieldLabelHtml("名称", "");
out.bothMissing = fieldLabelHtml("", "");
out.escaped = fieldLabelHtml("<b>", "a&b");
// V8：枚举候选（纯字符串）+ 当前值在候选内 → 不得出现「不在候选内」
out.enumIn = selectOptions("boss", ["normal", "elite", "boss", "training"], "（未选择）");
// 当前值不在候选内 → 仍要有显式占位项
out.enumOut = selectOptions("mythic", ["normal", "elite"], "（未选择）");
// 引用候选（对象）→ 名称（标识）形态保持
out.refOpts = selectOptions("r1", [{ id: "r1", name: "赤刃" }], "（未选择）");
out.enumEmpty = selectOptions(null, ["a"], "（未选择）");
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 标签/V8 语义执行")
def test_field_label_and_select_option_js_semantics(tmp_path: Path) -> None:
    label_src = tmp_path / "field_label.js"
    label_src.write_text(
        _marked_block("/* EDITOR_FIELD_LABEL_BEGIN */", "/* EDITOR_FIELD_LABEL_END */"),
        encoding="utf-8")
    opt_src = tmp_path / "select_options.js"
    opt_src.write_text(
        _marked_block("/* EDITOR_SELECT_OPTIONS_BEGIN */", "/* EDITOR_SELECT_OPTIONS_END */"),
        encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _FRONTEND_HARNESS, str(label_src), str(opt_src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)

    # 中文名为主 + 弱化键名为辅
    assert out["juxt"] == '标识 <span class="fkey">id</span>'
    # 无中文名（label == key）→ 只显示原始键，不重复
    assert out["same"] == "id"
    assert out["noLabel"] == "ghost"
    assert out["noKey"] == "名称"
    assert out["bothMissing"] == ""
    assert out["escaped"] == '&lt;b&gt; <span class="fkey">a&amp;b</span>'

    # V8：候选内 → 无「不在候选内」，且实际值被选中
    assert "不在候选内" not in out["enumIn"]
    assert 'value="boss" selected' in out["enumIn"]
    assert 'value="training"' in out["enumIn"]
    # 候选外 → 显式占位项保留
    assert "（当前值·不在候选内）" in out["enumOut"]
    # 引用候选仍显示「名称（标识）」；空值走占位
    assert "赤刃（r1）" in out["refOpts"]
    assert "不在候选内" not in out["enumEmpty"]


def test_frontend_field_render_uses_label_helper() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("fieldLabelHtml(f.label, f.key)",
                  "fieldLabelHtml(c.label, c.key)",
                  "function fieldLabelHtml(label, key)"):
        assert token in html, token
    # 主表单行 / 对象子字段走 fieldLabelHtml（中文 + 弱化键名）。
    assert html.count("fieldLabelHtml(") >= 3
    # 列表表头/块标签走 headerLabelHtml（批5.2 · V11：只留中文 + 类型，键名缩为悬停 tooltip）。
    assert "function headerLabelHtml(label, key)" in html
    assert html.count("headerLabelHtml(") >= 4


def test_frontend_fkey_style_is_weaker_and_smaller() -> None:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(r"\.fkey\s*\{([^}]*)\}", html)
    assert match, "index.html 缺少 .fkey 样式"
    rule = match.group(1)
    assert "var(--text-5)" in rule           # 弱化色（弱于字段标签的 --text-4）
    assert "var(--fs-11)" in rule            # 更小字号（小一号）
    assert ".fkey" in html


def test_frontend_no_hardcoded_business_field_names() -> None:
    """定义在元数据层的字段中文名不得出现在编辑器框架代码里（保持通用）。"""
    banned = ["怪物档位", "防护值", "互斥部位", "行动表"]
    for path in (REPO / "qbot_rpg" / "web" / "api.py",
                 REPO / "qbot_rpg" / "web" / "editor_ops.py",
                 REPO / "qbot_rpg" / "web" / "static" / "index.html",
                 REPO / "scripts" / "editor_host.py"):
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path} 写死了业务字段名：{word}"
