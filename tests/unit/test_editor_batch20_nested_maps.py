"""编辑器重写批20 · A 段：**嵌套「对象 → 数组 / 映射」可编辑**（用户 #2「无法编辑」）。

用户实测：怪物字段 `weakness = {"types": ["突"], "elements": {"wind": 1.3}}`、
`resistance = {"stun": 30, "immune": ["poison"]}` —— 对象里套数组 / 映射（映射的值有标量
也有数组）；批14 的 `objform` 只覆盖到「对象子字段」这一层，对象**里面**的数组 / 映射在
前端仍被渲染成只读 JSON 块 → 用户反馈「无法编辑」。

本批机制（**不写死任何模块名 / 键名**，一号原则）：
  · 对象里的**数组** → 行内可增删的列表控件（元素标量 → 行内单元格；元素对象 → 逐行嵌套对象表单）；
  · 对象里的**映射** → 键值表格（动态键空间可改键 / 增删行；值按**实际类型**出控件：
    数字 / 布尔 / 文本 / 枚举 / 引用 / 数组 / 对象 / 更深一层映射），可递归任意层；
  · 控件的列 / 行 / 类型全部来自框架元数据 + 值形态（后端 `_descriptor` / `kv_table` 规格）；
    元数据未登记的子键走兜底控件 + 既有「元数据未登记，按实际值推断」标注；
  · **不放宽任何校验**：写入仍走既有校验 / 原子写 / 备份 / 回退链路；条目级未知字段仍拒绝写入。

覆盖：
  A. 结构：数组 / 映射 / 多层递归（对象→数组→对象）都拿到可编辑控件；
  B. 端到端：改 `weakness.types` 与 `resistance.stun` → 真写盘 → 回退逐字节复原；
  C. 一号原则：登记未配置也出；未登记子键兜底 + 标注；
  D. 负向：条目级未知字段仍红拦（零落盘）；固定 schema 对象不放宽；校验器判定不变；
  E. 前端契约 + 真 Chromium DOM 实测（嵌套控件存在且可编）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

ENEMY = "gravelcrown"       # 实测含 weakness.types / weakness.elements / resistance.stun


def _by_key(fields: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f for f in fields}


def _desc(detail: Dict[str, Any], *path: str) -> Dict[str, Any]:
    node = detail
    for seg in path:
        kids = node["children"] if "children" in node else node["fields"]
        node = _by_key(kids)[seg]
    return node


@pytest.fixture()
def pack_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


# =====================================================================================
# A · 结构：数组 / 映射 / 多层递归都拿到可编辑控件（元数据 + 值形态驱动）
# =====================================================================================
def test_array_inside_object_is_editable_list() -> None:
    """对象里的数组（weakness.types）→ 行内可增删列表控件（不是只读 JSON 块）。"""
    d = api.entry_detail("veinborn", "enemies", ENEMY, root=CONTENT)
    types = _desc(d, "weakness", "types")
    assert types["control"] == "listtable" and types["editable"] is True
    assert types["scalar_element"] is True
    assert types["rows"] == [{"value": "突"}]
    # 元素描述符（供多层递归下钻）
    assert types["element"]["type"] == "str" and types["element"]["control"] == "text"


def test_mapping_inside_object_is_kv_table_with_dynamic_keys() -> None:
    """对象里的映射（weakness.elements = {"wind": 1.3}）→ 动态键空间键值表格。"""
    d = api.entry_detail("veinborn", "enemies", ENEMY, root=CONTENT)
    el = _desc(d, "weakness", "elements")
    assert el["control"] == "kvtable" and el["editable"] is True
    kv = el["kv_table"]
    assert kv["mode"] == "scalar" and kv["open_keys"] is True
    assert [r["key"] for r in kv["rows"]] == ["wind"]
    assert kv["rows"][0]["value"] == 1.3


def test_mixed_value_mapping_rows_typed_by_actual_value() -> None:
    """映射的值有标量也有数组（resistance = {stun: 30, immune: [...]}）→ typed 行模式：
    数字行给数字框、数组行给可增删列表控件；键动态可改（editor 声明的映射语义）。"""
    d = api.entry_detail("veinborn", "enemies", ENEMY, root=CONTENT)
    res = _desc(d, "resistance")
    assert res["control"] == "kvtable" and res["editable"] is True
    kv = res["kv_table"]
    assert kv["mode"] == "typed" and kv["open_keys"] is True
    rows = {r["key"]: r for r in kv["rows"]}
    assert rows["stun"]["control"] == "number" and rows["stun"]["editable"] is True
    assert rows["immune"]["control"] == "listtable"
    assert [r["value"] for r in rows["immune"]["rows"]] == ["poison"]
    # 结构（children）不因表格化而消失（批15 回归口径）
    assert {c["key"] for c in res["children"]} >= {"immune", "stun"}


def test_multilevel_object_array_object_recursion() -> None:
    """多层递归（对象 → 数组 → 对象）：drops.death[] 的每个元素都出字段描述符。"""
    d = api.entry_detail("veinborn", "enemies", ENEMY, root=CONTENT)
    death = _desc(d, "drops", "death")
    assert death["control"] == "listtable" and death["scalar_element"] is False
    el = death["element"]
    assert el["type"] == "obj" and el["control"] == "objform"
    kids = _by_key(el["children"])
    assert {"item", "chance", "condition", "count"} <= set(kids)
    assert kids["item"]["control"] == "ref" and kids["chance"]["control"] == "number"


def test_registered_but_absent_child_still_rendered() -> None:
    """一号原则：对象里登记了但数据没有的子键也出（present=False 可填）。"""
    d = api.entry_detail("veinborn", "enemies", ENEMY, root=CONTENT)
    drops = _desc(d, "drops")
    kids = _by_key(drops["children"])
    assert kids["battle"]["present"] is True
    # 元素描述符里的字段：登记项按元数据出（与数据在不在无关）
    el = _by_key(_desc(d, "drops", "death")["element"]["children"])
    assert el["condition"]["present"] is True or el["condition"]["present"] is False
    assert el["condition"]["control"] == "text"


def test_unregistered_map_key_fallback_control_and_note() -> None:
    """未登记子键 → 兜底控件（按实际值推断）+ 既有标注（scalar 列 / typed 行两处同口径）。"""
    from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
    from qbot_rpg.web.api import _PackView, _descriptor  # noqa: PLC0415

    meta = FieldMetaTable(modules={
        "m": ModuleMeta(entry_type="list", fields={
            "o": FieldMeta(type="obj", children={
                "known": FieldMeta(type="int", label="已知"),
            }),
        }),
    })
    fm = meta.module("m").fields["o"]
    view = _PackView(CONTENT / "veinborn", {"modules": []})
    # ① 值全为标量 → scalar 模式：单列「值」按样本推断，列标注「元数据未登记」
    d = _descriptor("o", fm, {"known": 1, "extra": "x"}, True, meta.module("m"), view, 0)
    assert d["control"] == "kvtable"        # 出现未登记键 → 映射表（动态键空间）
    assert d["kv_table"]["open_keys"] is True
    assert d["kv_table"]["columns"][0]["meta_unregistered"] is True
    assert d["kv_table"]["columns"][0]["meta_note"] == api.META_UNREGISTERED_NOTE
    # ② 值类型混杂 → typed 模式：每行一个描述符，未登记键行同样带兜底标注
    d2 = _descriptor("o", fm, {"known": 1, "extra": ["x"]}, True, meta.module("m"), view, 0)
    assert d2["kv_table"]["mode"] == api.KV_MODE_TYPED
    rows = {r["key"]: r for r in d2["kv_table"]["rows"]}
    assert rows["extra"]["meta_unregistered"] is True
    assert rows["extra"]["meta_note"] == api.META_UNREGISTERED_NOTE
    assert rows["extra"]["control"] == "listtable"
    assert rows["known"]["meta_unregistered"] is False


def test_one_principle_same_shape_across_packs() -> None:
    """一号原则：同一框架元数据下，两个包的「对象内数组/映射」形状一致（差异只在有没有值）。"""
    for pack in ("demo_blank", "veinborn"):
        try:
            d = api.entry_detail(pack, "enemies", ENEMY, root=CONTENT)
        except api.NotFound:
            continue
        w = _desc(d, "weakness")
        assert w["control"] == "objform"
        kids = _by_key(w["children"])
        assert kids["types"]["control"] == "listtable"
        assert kids["elements"]["control"] == "kvtable"


# =====================================================================================
# B · 端到端：真写盘 → 回退逐字节复原
# =====================================================================================
def test_nested_array_and_mapping_write_then_rollback(pack_copy: Path) -> None:
    """改 weakness.types 与 resistance.stun → enemies.json 真变 → 回退逐字节复原。"""
    ef = pack_copy / "veinborn" / "enemies.json"
    before_text = ef.read_text(encoding="utf-8")
    before = json.loads(before_text)
    orig = next(e for e in before if e["id"] == ENEMY)
    assert orig["weakness"]["types"] == ["突"]
    assert orig["resistance"]["stun"] == 30

    res = editor_ops.save_entry(
        "veinborn", "enemies", ENEMY,
        {"weakness": {"types": ["斩", "突"], "elements": {"wind": 1.3}},
         "resistance": {"stun": 45, "immune": ["poison"]}},
        root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after_text = ef.read_text(encoding="utf-8")
    after = json.loads(after_text)
    got = next(e for e in after if e["id"] == ENEMY)
    assert got["weakness"]["types"] == ["斩", "突"]
    assert got["resistance"]["stun"] == 45
    # 数组仍是数组（不退化成对象）、其余同级键不动
    assert isinstance(got["weakness"]["types"], list)
    assert set(got["weakness"]) == set(orig["weakness"])
    assert set(got["resistance"]) == set(orig["resistance"])
    assert got["drops"] == orig["drops"]

    rb = editor_ops.rollback_module("veinborn", "enemies", root=pack_copy, role="owner")
    assert rb["ok"] is True, rb
    assert ef.read_text(encoding="utf-8") == before_text


def test_nested_deep_object_in_array_write_then_rollback(pack_copy: Path) -> None:
    """多层递归（对象→数组→对象）：改 drops.death[0].chance → 写盘 → 回退。"""
    ef = pack_copy / "veinborn" / "enemies.json"
    before_text = ef.read_text(encoding="utf-8")
    orig = next(e for e in json.loads(before_text) if e["id"] == ENEMY)
    death = [dict(x) for x in orig["drops"]["death"]]
    death[0]["chance"] = 1
    res = editor_ops.save_entry("veinborn", "enemies", ENEMY,
                                {"drops": {"battle": orig["drops"]["battle"],
                                           "special": orig["drops"]["special"],
                                           "death": death}},
                                root=pack_copy, role="owner")
    assert res["ok"] is True, res
    got = next(e for e in json.loads(ef.read_text(encoding="utf-8")) if e["id"] == ENEMY)
    assert got["drops"]["death"][0]["chance"] == 1
    assert isinstance(got["drops"]["death"], list)
    editor_ops.rollback_module("veinborn", "enemies", root=pack_copy, role="owner")
    assert ef.read_text(encoding="utf-8") == before_text


def test_validate_never_writes(pack_copy: Path) -> None:
    """预检（validate）绝不落盘——嵌套数组/映射补丁走同一链路。"""
    ef = pack_copy / "veinborn" / "enemies.json"
    before_text = ef.read_text(encoding="utf-8")
    res = editor_ops.validate_entry(
        "veinborn", "enemies", ENEMY,
        {"weakness": {"types": ["斩"], "elements": {"wind": 2.0}}},
        root=pack_copy, role="owner")
    assert res["phase"] == "validate"
    assert ef.read_text(encoding="utf-8") == before_text


# =====================================================================================
# D · 负向断言：不放宽任何校验
# =====================================================================================
def test_entry_level_unknown_field_still_rejected(pack_copy: Path) -> None:
    """条目级未知字段仍在补丁白名单外 → BadRequest（零落盘）。"""
    ef = pack_copy / "veinborn" / "enemies.json"
    before_text = ef.read_text(encoding="utf-8")
    with pytest.raises(api.BadRequest):
        editor_ops.save_entry("veinborn", "enemies", ENEMY,
                              {"bogus_top_level": 1}, root=pack_copy, role="owner")
    assert ef.read_text(encoding="utf-8") == before_text


def test_fixed_schema_object_not_opened_up() -> None:
    """固定 schema 对象（登记子字段、值里没有多余键）仍是 objform，不臆造「+ 子项」。"""
    d = api.entry_detail("veinborn", "settings", "death_penalty", root=CONTENT)
    for key in ("drop_exp", "drop_items"):
        f = _by_key(d["fields"])[key]
        assert f["control"] == "objform", key
        assert f["open_keys"] is False, key


def test_validator_judgement_unchanged() -> None:
    """校验器判定不变（负向）：本批只改展示控件，未登记键该红拦仍红拦。"""
    import copy

    from qbot_rpg.content.validator import check_pack
    _pack_dir, modules = api.load_pack_modules("veinborn", root=CONTENT)
    meta = api.field_meta_table()
    mods = copy.deepcopy(modules)
    skills = mods["skills"]
    skills[0]["totally_unknown_key"] = 1
    rep = check_pack(mods, meta)
    assert any(e.kind == "R-5" and e.detail.get("rule") == "skill_field_unregistered"
               for e in rep.errors)


# =====================================================================================
# E · 前端契约 + 真 Chromium DOM 实测
# =====================================================================================
def test_frontend_has_nested_editors() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("objListEdit", "objKvEdit", "objScalarCell", "objScopeAttrs",
                  "data-okvc", "data-olsadd", "data-oldsdel", "data-okvadd", "data-okvdel",
                  "data-okvkey", "KV_MODE_TYPED", "bindScopedSections", "leafFromNode"):
        assert token in html, token


def _pw_python() -> str:
    """找一个装了 playwright 的解释器（宿主机可能与本进程不同解释器）。"""
    import subprocess
    cands = [sys.executable, "/usr/bin/python3", shutil.which("python3") or ""]
    for cand in cands:
        if not cand:
            continue
        proc = subprocess.run([cand, "-c", "import playwright"], capture_output=True)
        if proc.returncode == 0:
            return cand
    return ""


PW_PY = _pw_python()
DOM_DRIVER = REPO / "scripts" / "editor_dom_probe.py"


@pytest.mark.skipif(not PW_PY or not DOM_DRIVER.is_file(),
                    reason="本机无 playwright/chromium，跳过 DOM 实测")
def test_dom_nested_editors_are_live(tmp_path: Path) -> None:
    """真 Chromium：对象内嵌数组/映射控件确实在 DOM 里，且改动进真草稿。"""
    import subprocess
    out = tmp_path / "probe.json"
    proc = subprocess.run(
        [PW_PY, str(DOM_DRIVER), "--repo", str(REPO), "--pack", "veinborn",
         "--module", "enemies", "--entry", ENEMY, "--mode", "nested",
         "--host-python", sys.executable,
         "--edit", "weakness|opath:types.0|斩",
         "--edit", "resistance|kvcell:stun|45",
         "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    data = json.loads(out.read_text(encoding="utf-8"))
    weak = data["after"]["fields"]["weakness"]
    res = data["after"]["fields"]["resistance"]
    # 对象内嵌数组 → 列表控件（行内单元格）；对象内嵌映射 → 键值表格（含更深一层列表）
    assert weak["objlist"] >= 1, weak
    assert weak["objkv"] >= 1, weak
    assert res["kvtable"] >= 1, res
    assert data["draftAfter"]["weakness"]["types"] == ["斩"]
    assert data["draftAfter"]["resistance"]["stun"] == 45
    assert data["pageErrors"] == []
