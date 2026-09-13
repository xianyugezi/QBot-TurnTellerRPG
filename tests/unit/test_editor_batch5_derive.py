"""编辑器重写批5 · 技能派生界面（派生分区 + 条件行编辑器 + 派生技能引用）。

覆盖任务书「派生条件 / 派生技能 / 派生消耗」三件事（docs/编辑器重写_实现方案.md §四 批5）：

  A. **关联分区（元数据声明驱动）**：`ModuleMeta.associations` 声明「本模块条目 ↔ 其他模块
     条目的外键」（含列表内通配 `steps[].to`）；条目页据声明出「相关条目」分区，可编辑分区
     就地编辑、只读分区只出摘要 + 跳转；换模块/换包零改动（通用性用自建合成包验证）。
  B. **条件行编辑器（通用控件）**：condition 结构 ⇄ 条件行模型（主体/比较符/值 + 两级嵌套）；
     键名不写死（元数据声明优先，缺省按实际值形态推断并如实标注）；Python 参考实现
     （condition_rows/condition_value）与前端 EditorCondition 逐条同构（node 实测 71 条真实条件）。
  C. **派生技能引用**：`skill_chains.trigger_skill` / `steps[].from` / `steps[].to` 声明为
     ref→skill（复用批4 引用选择器）；**派生消耗** `consume`（数字）+ `consume_marks`（键值对
     表格，键为印记引用）；**数值覆盖** `variant_override` 为键值对表格。
  D. **落盘**：关联分区的就地编辑仍走批2 唯一写链路（校验 → 备份 → 原子写 → 回读/回退），
     改派生链 = 写 skill_chains，绝不绕开。

全部写盘发生在 tmp_path（仓库 content/ 只读拷贝），不触碰仓库内容包。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.content import field_meta as fm_mod
from qbot_rpg.content.models import (
    AssociationMeta,
    ConditionSubject,
    FieldMeta,
    FieldMetaTable,
    ModuleMeta,
)
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str, next_name: str) -> str:
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end].rstrip()
    assert src.endswith("}"), (name, src[-40:])
    return src


def _js_block(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/",
                  _html(), re.S)
    assert m is not None, name
    return m.group(1)


def _all_conditions() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for pack in ("veinborn", "test_demo"):
        path = CONTENT / pack / "skill_chains.json"
        for chain in json.loads(path.read_text(encoding="utf-8")):
            for step in chain.get("steps", []):
                if step.get("condition") is not None:
                    out.append(step["condition"])
    return out


# =====================================================================================
# A. 元数据声明层
# =====================================================================================
def test_models_new_dimensions_defaults_are_editor_display_only() -> None:
    """批5 新维度都是尾部默认值：既有构造零改动、校验语义零变化。"""
    fm = FieldMeta(type="str")
    assert fm.editor == "" and fm.key_ref == "" and fm.value_ref == ""
    assert dict(fm.condition_subjects) == {}
    mm = ModuleMeta()
    assert mm.associations == ()
    sub = ConditionSubject()
    assert (sub.label, sub.key_ref, sub.value_ref, sub.ops, sub.combine) \
        == ("", None, None, (), False)
    assoc = AssociationMeta()
    assert (assoc.module, assoc.field, assoc.local_field, assoc.editable) == ("", "", "id", True)


def test_skill_chains_declares_condition_editor_and_refs() -> None:
    """派生链元数据：条件编辑器 + 派生技能引用 + 数值覆盖/印记消耗键值对表格。"""
    table = fm_mod.default_field_meta_table()
    sc = table.module("skill_chains")
    assert sc is not None
    assert sc.fields["trigger_skill"].type == "ref"
    assert sc.fields["trigger_skill"].ref_target == "skill"
    step = sc.fields["steps"].element
    assert step is not None and step.type == "obj"
    for key in ("from", "to"):
        assert step.children[key].type == "ref" and step.children[key].ref_target == "skill"
    cond = step.children["condition"]
    assert cond.editor == "condition"
    assert set(cond.condition_subjects) == set(fm_mod.CHAIN_CONDITION_SUBJECTS)
    assert cond.condition_subjects["self_marks"].key_ref == "mark"
    assert cond.condition_subjects["self_status"].value_ref == "status"
    vo = step.children["variant_override"]
    assert vo.editor == "maptable"
    skills = table.module("skills")
    assert skills is not None
    assert skills.fields["consume_marks"].editor == "maptable"
    assert skills.fields["consume_marks"].key_ref == "mark"


def test_skills_module_declares_derive_associations() -> None:
    table = fm_mod.default_field_meta_table()
    skills = table.module("skills")
    assert skills is not None and len(skills.associations) == 2
    by_field = {a.field: a for a in skills.associations}
    assert by_field["trigger_skill"].module == "skill_chains"
    assert by_field["trigger_skill"].editable is True
    assert by_field["steps[].to"].editable is False
    assert all(a.label for a in skills.associations)


def test_decorate_field_meta_preserves_new_dimensions() -> None:
    """装饰只补 label/group/help：editor / condition_subjects / associations 原样保留。"""
    cond = FieldMeta(type="obj", editor="condition",
                     condition_subjects={"k": ConditionSubject(label="K", key_ref="mark")})
    out = fm_mod._decorate_field_meta({"c": cond}, {}, {"c": "条件"},
                                      {"c": {"k": "键"}}, None, None)["c"]
    assert out.label == "条件" and out.editor == "condition"
    assert out.condition_subjects["k"].key_ref == "mark"
    assert any(a.field == "steps[].to" for a in fm_mod.SKILLS_ASSOCIATIONS)


# =====================================================================================
# B. API 层：条件模型 / 控件映射 / 关联分区
# =====================================================================================
def test_condition_roundtrip_on_all_real_conditions() -> None:
    """Python 参考实现：真实内容包全部条件值解析→序列化完全还原（含 and/or 两级嵌套）。"""
    conds = _all_conditions()
    assert len(conds) >= 70
    for cond in conds:
        assert api.condition_value(api.condition_rows(cond)) == cond


def test_condition_rows_levels_and_combine() -> None:
    assert api.condition_rows({"count": {"eq": 3}}) == [
        {"kind": "cmp", "subject": "count", "key": "", "op": "eq", "value": 3}]
    rows = api.condition_rows({"self_marks": {"va_charge": {"min": 5}}})
    assert rows == [{"kind": "cmp", "subject": "self_marks", "key": "va_charge",
                     "op": "min", "value": 5}]
    comb = api.condition_rows({"and": [{"target_hp_pct": {"max": 60}},
                                       {"target_marks": {"cw_scorch": {"min": 3}}}]})
    assert comb[0]["kind"] == "combine" and comb[0]["subject"] == "and"
    assert [r["subject"] for g in comb[0]["children"] for r in g] == [
        "target_hp_pct", "target_marks"]


def test_condition_spec_from_metadata_and_unregistered() -> None:
    table = fm_mod.default_field_meta_table()
    sc = table.module("skill_chains")
    cond = sc.fields["steps"].element.children["condition"]
    spec = api.condition_spec(cond)
    assert spec["declared"] is True
    assert {s["key"] for s in spec["subjects"]} == set(fm_mod.CHAIN_CONDITION_SUBJECTS)
    assert "eq" in spec["ops"]
    # 未声明主体 → declared=False（前端据此如实标注「按实际值推断」）
    bare = api.condition_spec(FieldMeta(type="obj", editor="condition"))
    assert bare["declared"] is False and bare["subjects"] == []


def test_control_for_honors_explicit_editor() -> None:
    assert api.control_for(FieldMeta(type="obj", editor="condition"), "obj") == "condition"
    assert api.control_for(FieldMeta(type="obj", editor="maptable"), "obj") == "maptable"
    assert api.control_for(FieldMeta(type="obj"), "obj") == "readonly"
    # 未知 editor 声明 → 忽略并回退类型映射（不让元数据笔误把字段变成文本输入）
    assert api.control_for(FieldMeta(type="str", editor="no_such_widget"), "text") == "text"
    assert api.is_editable_control("condition") is True
    assert api.is_editable_control("maptable") is True
    assert api.is_editable_control("readonly") is False


def test_entry_detail_step_columns_carry_condition_and_maptable() -> None:
    triggers = [c["trigger_skill"] for c in json.loads(
        (CONTENT / "veinborn" / "skill_chains.json").read_text(encoding="utf-8"))]
    detail = api.entry_detail("veinborn", "skills", triggers[0], root=CONTENT)
    chain = detail["associations"][0]["entries"][0]
    fields = {f["key"]: f for f in chain["fields"]}
    assert fields["trigger_skill"]["control"] == "ref"
    assert fields["trigger_skill"]["ref_target"] == "skill"
    cols = {c["key"]: c for c in fields["steps"]["columns"]}
    assert cols["from"]["control"] == "ref" and cols["from"]["ref_target"] == "skill"
    assert cols["to"]["control"] == "ref" and cols["to"]["ref_target"] == "skill"
    assert cols["condition"]["control"] == "condition"
    assert cols["condition"]["condition"]["declared"] is True
    assert cols["variant_override"]["control"] == "maptable"


def test_associations_on_real_pack_both_directions() -> None:
    chains = json.loads((CONTENT / "veinborn" / "skill_chains.json").read_text(encoding="utf-8"))
    trigger = chains[0]["trigger_skill"]
    target = chains[0]["steps"][0]["to"]
    d_trig = api.entry_detail("veinborn", "skills", trigger, root=CONTENT)
    assert d_trig["association_count"] == 2
    sec = {a["module"] + ":" + a["field"]: a for a in d_trig["associations"]}
    trigger_sec = sec["skill_chains:trigger_skill"]
    assert trigger_sec["editable"] is True and trigger_sec["count"] >= 1
    assert trigger_sec["entries"][0]["id"] == chains[0]["id"]
    assert trigger_sec["entries"][0]["matches"][0]["path"] == "trigger_skill"
    d_tgt = api.entry_detail("veinborn", "skills", target, root=CONTENT)
    tgt_sec = next(a for a in d_tgt["associations"] if a["field"] == "steps[].to")
    assert tgt_sec["editable"] is False and tgt_sec["count"] >= 1
    # 只读分区只出摘要（无 fields），命中路径带下标（列表内通配）
    entry = tgt_sec["entries"][0]
    assert "fields" not in entry
    assert entry["matches"][0]["path"].startswith("steps[")


def test_association_is_generic_metadata_driven(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """自建合成包（任意模块/字段名）：关联分区照样渲染 → 编辑器零业务硬编码。"""
    table = FieldMetaTable(modules={
        "alpha": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "name": FieldMeta(type="str", label="名称"),
        }, associations=(
            AssociationMeta(module="beta", field="owner", label="被引用（可编辑）"),
            AssociationMeta(module="beta", field="rows[].ptr", label="列表内引用（只读）",
                            editable=False),
            AssociationMeta(module="ghost", field="x", label="未声明模块"),
        )),
        "beta": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True),
            "name": FieldMeta(type="str"),
            "owner": FieldMeta(type="ref", ref_target="alpha"),
            "rows": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "ptr": FieldMeta(type="str"), "amt": FieldMeta(type="int"),
            })),
        }),
    })
    pkg = tmp_path / "pack_g"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "G", "version": "1", "schema_version": 1, "modules": ["alpha", "beta"],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "alpha.json").write_text(json.dumps(
        [{"id": "a1", "name": "甲"}], ensure_ascii=False), encoding="utf-8")
    (pkg / "beta.json").write_text(json.dumps([
        {"id": "b1", "name": "乙", "owner": "a1", "rows": [{"ptr": "a1", "amt": 2}]},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(api, "_META_TABLE", table)

    detail = api.entry_detail("pack_g", "alpha", "a1", root=tmp_path)
    secs = {a["field"]: a for a in detail["associations"]}
    assert set(secs) == {"owner", "rows[].ptr", "x"}
    assert secs["owner"]["editable"] is True
    assert secs["owner"]["entries"][0]["id"] == "b1"
    assert secs["owner"]["entries"][0]["fields"], "可编辑分区应出相关条目完整字段"
    assert secs["rows[].ptr"]["editable"] is False
    assert secs["rows[].ptr"]["entries"][0]["matches"][0]["path"] == "rows[0].ptr"
    # 关联模块未在 manifest 声明 → 如实标注，绝不炸
    assert secs["x"]["declared"] is False and secs["x"]["note"]


def test_walk_path_supports_dotted_and_list_wildcards() -> None:
    subject = {"a": {"b": 1}, "rows": [{"to": "x"}, {"to": "y"}], "s": "z"}
    assert api._walk_path(subject, "a.b") == [("a.b", 1)]
    assert api._walk_path(subject, "rows[].to") == [("rows[0].to", "x"), ("rows[1].to", "y")]
    assert api._walk_path(subject, "s") == [("s", "z")]


# =====================================================================================
# C. 落盘：跨模块就地编辑仍走批2 唯一链路
# =====================================================================================
@pytest.fixture()
def veinborn_tmp(tmp_path: Path) -> Path:
    dst = tmp_path / "veinborn"
    shutil.copytree(CONTENT / "veinborn", dst)
    return tmp_path


def test_association_edit_writes_skill_chains_and_rollback(veinborn_tmp: Path) -> None:
    """改派生链的一个条件 → 保存 → skill_chains.json 真的变化 → 回退复原。"""
    pack = veinborn_tmp / "veinborn"
    chains = json.loads((pack / "skill_chains.json").read_text(encoding="utf-8"))
    chain = next(c for c in chains if c["steps"] and c["steps"][0].get("condition"))
    old_cond = chain["steps"][0]["condition"]
    new_cond = {"count": {"eq": 4}}

    steps = json.loads(json.dumps(chain["steps"]))
    steps[0]["condition"] = new_cond
    before = (pack / "skill_chains.json").read_text(encoding="utf-8")
    assert old_cond != new_cond

    res = editor_ops.save_entry("veinborn", "skill_chains", chain["id"], {"steps": steps},
                                root=veinborn_tmp, role=editor_ops.ROLE_OWNER)
    assert res["ok"] is True and res["written"], res
    after = json.loads((pack / "skill_chains.json").read_text(encoding="utf-8"))
    saved = next(c for c in after if c["id"] == chain["id"])
    assert saved["steps"][0]["condition"] == new_cond
    assert (pack / "skill_chains.json.bak").exists()

    rb = editor_ops.rollback_module("veinborn", "skill_chains", root=veinborn_tmp,
                                    role=editor_ops.ROLE_OWNER)
    assert rb["ok"] is True
    assert (pack / "skill_chains.json").read_text(encoding="utf-8") == before
    restored = next(c for c in json.loads(before) if c["id"] == chain["id"])
    assert restored["steps"][0]["condition"] == old_cond


def test_association_edit_red_block_does_not_write(veinborn_tmp: Path) -> None:
    """非法引用（触发技不存在）→ 红拦，零文件改动。"""
    pack = veinborn_tmp / "veinborn"
    chains = json.loads((pack / "skill_chains.json").read_text(encoding="utf-8"))
    chain = next(c for c in chains if c["steps"])
    before = (pack / "skill_chains.json").read_text(encoding="utf-8")
    res = editor_ops.save_entry("veinborn", "skill_chains", chain["id"],
                                {"trigger_skill": "no_such_skill_xyz"},
                                root=veinborn_tmp, role=editor_ops.ROLE_OWNER)
    assert res["ok"] is False and res["errors"]
    assert (pack / "skill_chains.json").read_text(encoding="utf-8") == before


# =====================================================================================
# D. 前端：纯 JS 语义（node 实测）
# =====================================================================================
_COND_HARNESS = r"""
const fs = require("fs");
global.esc = function (v) {
  return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
// selectOptions：与 index.html 生产实现同口径（字符串/对象候选归一）
global.selectOptions = function (value, options, placeholder) {
  var cur = value == null ? "" : String(value);
  var rows = (options || []).map(function (o) {
    if (o && typeof o === "object") {
      var oid = o.id == null ? "" : String(o.id);
      return { id: oid, text: (o.name == null ? oid : String(o.name)) + "（" + oid + "）" };
    }
    return { id: String(o), text: String(o) };
  });
  var has = rows.some(function (o) { return o.id === cur; });
  var html = '<option value="">' + esc(placeholder) + "</option>";
  if (cur && !has) {
    html += '<option value="' + esc(cur) + '" selected>' + esc(cur) + "</option>";
  }
  rows.forEach(function (o) {
    html += '<option value="' + esc(o.id) + '"' + (o.id === cur ? " selected" : "") + ">"
      + esc(o.text) + "</option>";
  });
  return html;
};
global.state = { refCache: {}, refKnown: {} };
global.markDirty = function () {};
global.fillRefSelect = function () {};
global.bindHelp = function () {};
global.EditorDraft = { set: function () {}, discard: function () {} };
eval(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
const meta = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// 一级条件（count/eq）与两级（self_marks/印记/min）渲染
out.level1 = condBodyHtml(EditorCondition.parse({ count: { eq: 3 } }), meta);
out.level2 = condBodyHtml(EditorCondition.parse({ self_marks: { va_charge: { min: 5 } } }), meta);
out.combine = condBodyHtml(
  EditorCondition.parse({ and: [{ target_hp_pct: { max: 60 } }, { count: { eq: 2 } }] }), meta);
out.statusRef = condBodyHtml(
  EditorCondition.parse({ self_status: { has: ["rb_core_window"] } }), meta);
out.unregistered = condBodyHtml(
  EditorCondition.parse({ custom_key: { ge: 7 } }),
  { declared: false, subjects: [], ops: [] });
// 键值对表格
out.mapField = mapBodyHtml(EditorMap.rows({ power: 320 }), { key_ref: "", value_ref: "" });
out.mapMark = mapBodyHtml(EditorMap.rows({ vs_gauge: 4 }), { key_ref: "mark" });
// 结构操作：新增/删除/分支
var rows = EditorCondition.parse({ count: { eq: 3 } });
EditorCondition.addRow(rows, null);
out.afterAdd = JSON.parse(JSON.stringify(rows));
EditorCondition.delRow(rows, [1]);
out.afterDel = EditorCondition.serialize(rows);
var comb = EditorCondition.parse({ or: [{ a: { eq: 1 } }] });
EditorCondition.addBranch(comb, [0]);
EditorCondition.addRow(comb, [0], 1);
out.afterBranch = EditorCondition.serialize(comb);
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_out(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批5 前端语义执行")
    script = tmp_path_factory.mktemp("b5js") / "cond.js"
    cond_src = _js_block("EDITOR_CONDITION")
    map_src = _js_block("EDITOR_MAP")
    fn_src = ("\n" + _fn_src("condBodyHtml", "bindConditionSections")
              + "\n" + _fn_src("mapBodyHtml", "bindMapSections"))
    script.write_text(
        "var module={exports:{}};\n" + cond_src
        + "\nvar EditorCondition=module.exports;\n"
        + "module={exports:{}};\n" + map_src
        + "\nvar EditorMap=module.exports;\n" + fn_src, encoding="utf-8")
    meta = tmp_path_factory.mktemp("b5meta") / "meta.json"
    table = fm_mod.default_field_meta_table()
    cond = table.module("skill_chains").fields["steps"].element.children["condition"]
    meta.write_text(json.dumps(api.condition_spec(cond), ensure_ascii=False), encoding="utf-8")
    runner = tmp_path_factory.mktemp("b5run") / "run.js"
    runner.write_text(_COND_HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(runner), str(script), str(meta)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_js_condition_parse_serialize_roundtrip_and_python_parity(
        tmp_path_factory: pytest.TempPathFactory) -> None:
    if NODE is None:
        pytest.skip("本机无 node")
    cond_js = _js_block("EDITOR_CONDITION")
    script = tmp_path_factory.mktemp("b5par") / "par.js"
    script.write_text("var module={exports:{}};\n" + cond_js + "\n"
                      "var EditorCondition=module.exports;\n"
                      "var data=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));\n"
                      "var out=data.map(function(c){return EditorCondition.serialize("
                      "EditorCondition.parse(c));});\n"
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    conds = _all_conditions()
    data = tmp_path_factory.mktemp("b5par") / "in.json"
    data.write_text(json.dumps(conds), encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(data)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == conds

    # Python 行模型 → Python 序列化 与 JS 序列化 完全一致（同构证据）
    one = tmp_path_factory.mktemp("b5par") / "one.js"
    one.write_text("var module={exports:{}};\n" + cond_js + "\n"
                   "var EditorCondition=module.exports;\n"
                   "var rows=JSON.parse(require('fs').readFileSync(0,'utf8'));\n"
                   "process.stdout.write(JSON.stringify(EditorCondition.serialize(rows)));\n",
                   encoding="utf-8")
    for cond in conds:
        rows = api.condition_rows(cond)
        js_val = json.loads(subprocess.run([NODE, str(one)], input=json.dumps(rows),
                                           capture_output=True, text=True, check=True).stdout)
        assert js_val == api.condition_value(rows), cond


def test_js_condition_editor_renders_rows_with_metadata(js_out: Dict[str, Any]) -> None:
    assert "条件行 · 1 行" in js_out["level1"]
    assert 'data-cpart="subject"' in js_out["level1"]
    assert "连段计数" in js_out["level1"]          # 元数据中文名（不是键名硬编码）
    assert "_eq" in js_out["level1"] or ">eq<" in js_out["level1"]
    # 两级：二级键（印记 ID）与比较符
    assert "自身印记" in js_out["level2"] and ' data-cpart="key"' in js_out["level2"]
    assert "min" in js_out["level2"]
    # 逻辑组合：分支渲染 + 加分支按钮
    assert "cchildren" in js_out["combine"] and "data-caddbranch" in js_out["combine"]
    assert "分支 1" in js_out["combine"]
    # 值引用：self_status 的值走引用选择器（status 候选）
    assert 'data-lref="status"' in js_out["statusRef"]
    # 未声明主体：如实标注「元数据未声明」
    assert "元数据未声明" in js_out["unregistered"]
    assert 'data-cpart="subject"' in js_out["unregistered"]


def test_js_condition_structural_ops(js_out: Dict[str, Any]) -> None:
    assert len(js_out["afterAdd"]) == 2
    assert js_out["afterDel"] == {"count": {"eq": 3}}
    # 加分支：or 列表新增一个分支（空组），组内再加一行 → 序列化保留边界；
    # 未填主体的空行不落盘（条件值形态无法表达无名主体），序列化为 {}
    assert js_out["afterBranch"]["or"][0] == {"a": {"eq": 1}}
    assert len(js_out["afterBranch"]["or"]) == 2
    assert js_out["afterBranch"]["or"][1] == {}


def test_js_map_table_renders_and_refs(js_out: Dict[str, Any]) -> None:
    assert "键值对" in js_out["mapField"] and 'data-mpart="key"' in js_out["mapField"]
    assert "320" in js_out["mapField"]
    assert 'data-lref="mark"' in js_out["mapMark"]   # 消耗印记的键是引用选择器


# ---------------------------------------------------------------------------
# 前端接线（index.html）：列表单元格 / 关联分区渲染 / 保存链路
# ---------------------------------------------------------------------------
def test_frontend_list_cells_support_condition_and_maptable() -> None:
    html = _html()
    assert 'case "condition":' in html and 'case "maptable":' in html
    cell = _fn_src("listCell", "readCellValue")
    assert "data-condcell" in cell and "condBodyHtml" in cell
    assert "data-mapcell" in cell and "mapBodyHtml" in cell


def test_frontend_association_pane_and_forms() -> None:
    html = _html()
    for token in ("function assocPaneHtml", "function bindAssocSections", "function jumpTo",
                  "function saveForm", "function formURL", "function registerForm",
                  "data-fctx", "state.pendingDrafts"):
        assert token in html, token
    # 只读分区出跳转按钮；可编辑分区出保存按钮
    pane = _fn_src("assocPaneHtml", "bindAssocSections")
    assert "ajump" in pane and "asave" in pane and "data-fctx" in pane
    # 关联分区不写死任何内容包模块名（通用性护栏）
    for banned in ('"skill_chains"', '"skills"', '"veinborn"', '"test_demo"'):
        assert banned not in pane, banned


def test_frontend_condition_editor_wiring() -> None:
    html = _html()
    for token in ("function bindConditionSections", "function commitCond", "function redrawCond",
                  "function condBodyHtml", "function mapBodyHtml", "function bindMapSections",
                  "EDITOR_CONDITION_BEGIN", "EDITOR_MAP_BEGIN"):
        assert token in html, token
    assert "bindConditionSections(body)" in html and "bindMapSections(body)" in html
    # 控件映射集中后端：前端只按 control 渲染，不复制类型表
    assert "switch (f.control)" in html


def test_framework_files_have_no_pack_business_names() -> None:
    """批5 新增的编辑器逻辑不得写死任何内容包模块名/字段名（元数据声明除外）。"""
    for path in (REPO / "qbot_rpg" / "web" / "api.py",
                 REPO / "qbot_rpg" / "web" / "static" / "index.html"):
        text = path.read_text(encoding="utf-8")
        for word in ("veinborn", "test_demo"):
            assert word not in text, f"{path} 写死：{word}"
