"""编辑器重写批14 · #4 对象子字段可编辑（用户原话：很多该能编辑的地方无法编辑，
比如死亡掉落的掉落经验和掉落物品）。

根因（审计 ①-3 第 19/20/21 条）：`qbot_rpg/web/api.py::_EDIT_BY_WIDGET["obj"] = ("readonly", False)`
——对象型子字段被整体渲染为只读块 → `death_penalty.drop_exp/drop_items`、`slot_defs.{部位}`
等嵌套子字段全不可编。

本批机制（**不写死任何模块名/字段名**，一号原则）：
  · `obj` → `objform` 可编辑控件；子字段按**框架元数据**递归渲染（布尔→开关 / 数字→数字框 /
    文本→输入框 / 枚举→下拉 / 引用→引用选择器），嵌套任意层；
  · **按元数据渲染、而非只渲染数据里已存在的键**：框架登记了但包未配置的子字段 →
    未配置态（present=False）显示、可填写；
  · 元数据未登记的子字段 → 兜底控件（按实际值推断）+ 标注「元数据未登记，按实际值推断」；
  · 动态键空间（对象未登记子字段）可新增/删除子项；
  · 编辑/保存仍走既有链路（校验 → 原子写 → 备份 → 可回退）；**不放宽校验**。

覆盖：
  A. 嵌套两层子字段可编（drop_exp / drop_items；进而是任意元数据登记对象）；
  B. 端到端写盘 → 原始 JSON 真变 → 回退逐字节复原；
  C. 未注册子字段兜底控件 + 标注；动态键空间可增删；
  D. 未知键仍红拦（负向断言；既有补丁白名单 + 校验器判定不变）；
  E. 一号原则自检：demo_blank / veinborn 同一模块字段集合一致（差异只在有没有值）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

SETTINGS_META = api.default_field_meta_table().module("settings")


def _by_key(fields) -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f for f in fields}


def _desc(detail: Dict[str, Any], *path: str) -> Dict[str, Any]:
    node = detail
    for seg in path:
        kids = node["children"] if "children" in node else node["fields"]
        node = _by_key(kids)[seg]
    return node


# =====================================================================================
# A · 嵌套两层子字段可编（元数据驱动的通用机制）
# =====================================================================================
def test_nested_two_level_object_subfields_are_editable() -> None:
    """死亡惩罚的 drop_exp / drop_items（嵌套两层）子字段全部可编。"""
    d = api.entry_detail("veinborn", "settings", "death_penalty", root=CONTENT)
    for obj_key, children in (("drop_exp", {"enabled": "bool", "percent": "number"}),
                              ("drop_items", {"enabled": "bool", "count": "number"})):
        obj = _desc(d, obj_key)
        assert obj["control"] == "objform" and obj["editable"] is True, obj_key
        kids = _by_key(obj["children"])
        for ck, ctl in children.items():
            assert ck in kids, (obj_key, ck)
            assert kids[ck]["control"] == ctl and kids[ck]["editable"] is True
    # 三层：time_cycle.combat.weather_mult（嵌套对象里的对象）
    d2 = api.entry_detail("demo_blank", "settings", "time_cycle", root=CONTENT)
    wm = _desc(d2, "combat", "weather_mult")
    assert wm["control"] == "objform" and wm["editable"] is True
    assert _by_key(wm["children"])["enabled"]["control"] == "bool"


def test_metadata_registered_children_rendered_even_when_absent() -> None:
    """一号原则：元数据登记了但数据未配置的子字段 → 未配置态（present=False）也在列、可填。"""
    d = api.entry_detail("demo_blank", "settings", "time_cycle", root=CONTENT)
    assert d["unconfigured"] is True
    season = _desc(d, "season")
    kids = _by_key(season["children"])
    assert kids["season_days"]["present"] is False
    assert kids["season_days"]["control"] == "number"
    # 对象存在但某个登记子键缺失 → 也补出（present=False）
    d2 = api.entry_detail("veinborn", "settings", "death_penalty", root=CONTENT)
    assert _by_key(_desc(d2, "drop_exp")["children"])["percent"]["present"] is True


def test_objform_control_is_generic_not_module_specific() -> None:
    """通用机制：不写死模块名/字段名——只看类型登记。"""
    meta = FieldMetaTable(modules={
        "m": ModuleMeta(entry_type="list", fields={
            "o": FieldMeta(type="obj", children={
                "flag": FieldMeta(type="bool", label="开关"),
                "num": FieldMeta(type="int", label="数"),
            }),
        }),
    })
    assert api.control_for(meta.module("m").fields["o"], "obj") == "objform"
    assert api.is_editable_control("objform") is True


# =====================================================================================
# B · 端到端写盘 → 原始 JSON 真变 → 回退逐字节复原
# =====================================================================================
@pytest.fixture()
def pack_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


def test_nested_object_write_then_rollback(pack_copy: Path) -> None:
    """改 drop_exp.percent（嵌套两层）→ settings.json 真变 → 回退复原（贴原始 JSON diff）。"""
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    before = json.loads(before_text)
    assert before["death_penalty"]["drop_exp"]["percent"] == 10

    res = editor_ops.save_entry(
        "veinborn", "settings", "death_penalty",
        {"drop_exp": {"enabled": True, "percent": 25}}, root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after_text = sf.read_text(encoding="utf-8")
    after = json.loads(after_text)
    assert after["death_penalty"]["drop_exp"] == {"enabled": True, "percent": 25}
    # 只动了 drop_exp；其余键逐字节语义不变
    assert after["death_penalty"]["drop_items"] == before["death_penalty"]["drop_items"]
    assert set(after["death_penalty"]) == set(before["death_penalty"])

    rb = editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert rb["ok"] is True, rb
    assert sf.read_text(encoding="utf-8") == before_text


def test_nested_object_boolean_write_then_rollback(pack_copy: Path) -> None:
    """改 drop_items.enabled（布尔子字段）→ 写盘 → 回退。"""
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    res = editor_ops.save_entry(
        "veinborn", "settings", "death_penalty",
        {"drop_items": {"enabled": True, "count": 3}}, root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["death_penalty"]["drop_items"] == {"enabled": True, "count": 3}
    editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert sf.read_text(encoding="utf-8") == before_text


def test_validate_does_not_write(pack_copy: Path) -> None:
    """预检（validate）绝不落盘——对象子字段补丁走同一链路。"""
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    res = editor_ops.validate_entry(
        "veinborn", "settings", "death_penalty",
        {"drop_exp": {"enabled": False, "percent": 1}}, root=pack_copy, role="owner")
    assert res["phase"] == "validate"
    assert sf.read_text(encoding="utf-8") == before_text


# =====================================================================================
# C · 未注册子字段兜底控件 + 标注；动态键空间可增删
# =====================================================================================
def test_unregistered_subfield_fallback_control_and_note() -> None:
    """数据里多出、元数据未登记的键 → 兜底控件（按实际值推断）+ 标注。

    批15 #9：slot_defs 这类「键 → 小结构」的密集映射改键值表格渲染——子键不再逐个出
    objform 字段，而是表格列（列按值推断）+ 每列标注「元数据未登记」。
    """
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=CONTENT)
    field = d["fields"][0]
    assert field["control"] == "kvtable"
    cols = {c["key"]: c for c in field["kv_table"]["columns"]}
    assert cols["name"]["control"] == "text" and cols["name"]["meta_unregistered"] is True
    assert cols["max"]["control"] == "number" and cols["max"]["meta_unregistered"] is True
    assert "未登记" in cols["name"]["meta_note"]


def test_unconfigured_open_object_renders_one_field() -> None:
    """未配置的开放对象段（obj children={} soft）→ 整段一值字段，可编、未配置态。"""
    d = api.entry_detail("demo_blank", "settings", "imprints", root=CONTENT)
    assert d["unconfigured"] is True
    assert d["open_keys"] is False  # 未配置段的写路径是「整段一值」，不走条目级增删
    assert d["field_count"] >= 1


def test_entry_level_open_keys_add_delete_then_rollback(pack_copy: Path) -> None:
    """动态键空间（已配置的 obj 段）可新增/删除子项；写盘 + 回退。

    批15 #9：slot_defs 由「每键一个 objform 字段」升级为**整条目键值表格**（whole_table）：
    新增/删除既可走整表提交（前端表格），也保留逐键补丁写路径（向后兼容）。
    """
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=pack_copy)
    assert d["whole_table"] is True and d["open_keys"] is False
    kv = d["fields"][0]["kv_table"]
    before_slots = set(json.loads(before_text)["slot_defs"])
    assert kv["open_keys"] is True and {r["key"] for r in kv["rows"]} == before_slots

    add = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"belt": {"name": "腰带", "max": 1}},
                                root=pack_copy, role="owner")
    assert add["ok"] is True, add
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["slot_defs"]["belt"] == {"name": "腰带", "max": 1}
    rb1 = editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert rb1["ok"] is True, rb1
    assert sf.read_text(encoding="utf-8") == before_text

    # 删除一个已有部位（走 open_keys 写路径）→ 写盘 → 回退
    delete = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                   {"weapon": None}, root=pack_copy, role="owner")
    assert delete["ok"] is True, delete
    final = json.loads(sf.read_text(encoding="utf-8"))
    assert "weapon" not in final["slot_defs"]
    assert set(final["slot_defs"]) == set(json.loads(before_text)["slot_defs"]) - {"weapon"}
    rb2 = editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert rb2["ok"] is True, rb2
    assert sf.read_text(encoding="utf-8") == before_text


# =====================================================================================
# D · 未知键仍红拦（负向断言：本批不放宽任何校验/白名单）
# =====================================================================================
def test_unknown_subfield_of_registered_object_still_rejected(
        pack_copy: Path) -> None:
    """登记了子字段的固定 schema 对象：未知子键仍在补丁白名单外 → 拒绝写入（零落盘）。"""
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    with pytest.raises(api.BadRequest):
        editor_ops.save_entry("veinborn", "settings", "death_penalty",
                              {"drop_exp": {"enabled": True, "percent": 10},
                               "bogus_field": 1}, root=pack_copy, role="owner")
    assert sf.read_text(encoding="utf-8") == before_text
    # 固定 schema 的对象不给「+ 子项」（不臆造键）→ open_keys=False
    slot = api.entry_slot("veinborn", "settings", "death_penalty", root=pack_copy)
    assert slot["open_keys"] is False


def test_unknown_key_red_block_via_validator_unchanged(tmp_path: Path) -> None:
    """校验器判定不变（负向断言）：本批只改展示，未登记键该红拦仍红拦。"""
    import copy

    from qbot_rpg.content.validator import check_pack
    pack_dir, modules = api.load_pack_modules("veinborn", root=CONTENT)
    meta = api.field_meta_table()
    # ① 严格模块（skills V-11 登记表）：未知顶层键 → R-5 红拦
    mods = copy.deepcopy(modules)
    mods["skills"][0]["totally_unknown_key"] = 1
    rep = check_pack(mods, meta)
    assert any(e.kind == "R-5" and e.detail.get("rule") == "skill_field_unregistered"
               for e in rep.errors)
    # ② 泛型模块：类型错误仍 R-1 红拦（对象子字段填成文本）
    meta2 = FieldMetaTable(modules={
        "cfg": ModuleMeta(entry_type="object", fields={
            "obj": FieldMeta(type="obj", children={
                "n": FieldMeta(type="int", range_min=0, range_max=10),
            }),
        }),
    })
    report = check_pack({"cfg": {"obj": {"n": "不是数字"}}}, meta2)
    assert report.errors and report.errors[0].kind == "R-1"


# =====================================================================================
# E · 一号原则自检：同一模块字段集合跨包一致（差异只在有没有值）
# =====================================================================================
def test_field_sets_equal_across_blank_and_full_pack() -> None:
    """demo_blank / veinborn 打开同一模块的同一段：字段键集合一致（元数据驱动）。"""
    registered = {str(k) for k in SETTINGS_META.fields}
    for pack in ("demo_blank", "veinborn"):
        d = api.entry_detail(pack, "settings", "death_penalty", root=CONTENT)
        assert d["field_count"] == len(d["fields"])
        keys = {f["key"] for f in d["fields"]}
        assert {"weak_duration_sec", "drop_currency", "drop_exp", "drop_items"} <= keys
        dp = _by_key(d["fields"])["drop_exp"]
        assert {c["key"] for c in dp["children"]} == {"enabled", "percent"}
    assert len(registered) > 0


def test_registered_child_set_independent_of_data() -> None:
    """框架登记的 settings 顶层段集合跨包一致（批13.1 已立；本批续证对象子字段同源）。

    批19 #8：被 entry_tree 挂到父节点的段不再出现在 settings 条目列表里，但仍在
    「父节点挂载」里可见 → 跨包口径取「本模块条目 ∪ 从本模块挂出去的段」。
    """
    def visible(pack: str) -> set:
        ids = {e["id"] for e in api.list_entries(pack, "settings", root=CONTENT)["entries"]}
        mods = api.list_modules(pack, root=CONTENT)

        def walk(nodes: list) -> None:
            for n in nodes or []:
                for item in n.get("mounted") or []:
                    if item.get("from") == "settings":
                        ids.add(item["id"])
                walk(n.get("children") or [])

        walk(mods["modules"])
        for v in mods.get("views") or []:
            for item in v.get("mounted") or []:
                if item.get("from") == "settings":
                    ids.add(item["id"])
        return ids

    blank = visible("demo_blank")
    full = visible("veinborn")
    assert blank == full
    reg = set(SETTINGS_META.fields)
    assert reg <= blank


def test_one_principle_all_object_modules_children_cross_pack() -> None:
    """一号原则（广义）：任一 object 模块的每个已登记对象的**子字段集合**，在两个包
    （几乎空白 vs 功能齐全）里都按框架元数据出齐——差异只在有没有值，不在字段集合。"""
    meta = api.default_field_meta_table()
    checked = 0
    for mod, mmeta in meta.modules.items():
        if mmeta is None or mmeta.entry_type != "object":
            continue
        for seg, fm in mmeta.fields.items():
            if not (fm.type == "obj" and fm.children):
                continue
            want = {str(k) for k in fm.children}
            for pack in ("demo_blank", "veinborn"):
                try:
                    d = api.entry_detail(pack, mod, seg, root=CONTENT)
                except api.NotFound:
                    continue
                # 数据形态不是对象（如该段实际是列表/标量）时不套用对象子字段口径
                raw = json.loads((CONTENT / pack / f"{mod}.json").read_text(encoding="utf-8"))
                val = raw.get(seg) if isinstance(raw, Mapping) else None
                if val is not None and not isinstance(val, Mapping):
                    continue
                keys = {f["key"] for f in d["fields"]}
                assert want <= keys, (mod, seg, pack, want - keys)
                checked += 1
    assert checked >= 4, checked


# =====================================================================================
# F · 前端契约（objform 渲染 + 增删键 + 嵌套草稿）
# =====================================================================================
def test_frontend_has_objform_editor_and_note() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("objFormEdit", "data-opath", "data-objadd", "data-objdel",
                  "META_UNREGISTERED_HINT", "元数据未登记，按实际值推断",
                  "data-openadd", "data-keydel"):
        assert token in html, token
