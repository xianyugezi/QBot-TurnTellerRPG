"""编辑器重写批17 · 物品通用预设（框架默认六种）测试。

覆盖任务书要求（通用，不写死内容包业务名）：
  · 框架默认预设表 `qbot_rpg/content/entry_presets.py`：材料/货币袋/药剂/礼包/装备/技能书；
  · **键校验**：六个预设的所有 `fields` 与 `defaults` 的键都存在于框架 `items` 元数据
    （元数据表断言，防臆造键名）；
  · 合并规则 `生效预设 = 框架默认 ∪ 包声明`：同 id 包覆盖 / 包追加 / 包关闭
    （`entry_presets_disable`）/ **空白包也有六种**；
  · 编辑器接入：`new_entry_detail(presets=…)` / `new_entry_slot(preset=…)` /
    `suggest_id(preset=…)` 走合并表；`id_prefix` 联动（材料 → `mat_001`）；
  · 不选预设 = 现状（回归）；一号原则（其余字段折叠仍可编辑）；
  · 端到端：空白包按「材料」预设真写盘（defaults 落盘）→ 回退逐字节复原；HTTP 写链路。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import entry_presets as entry_presets_mod
from qbot_rpg.content import field_meta_pack as pack_meta
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 框架默认预设的期望清单（id / 中文名 / id_prefix）——与元数据无关的稳定契约。
EXPECTED = [
    ("material", "材料", "mat"),
    ("currency_pouch", "货币袋", "pouch"),
    ("potion", "药剂", "potion"),
    ("gift_box", "礼包", "gift"),
    ("equipment", "装备", "eq"),
    ("skill_book", "技能书", "book"),
]


def _items_keys() -> set:
    mmeta = default_field_meta_table().module("items")
    return {str(k) for k in mmeta.fields}


# ---------------------------------------------------------------------------
# 一、框架默认预设：键校验（防臆造）+ 内容契约
# ---------------------------------------------------------------------------
def test_framework_preset_keys_all_registered() -> None:
    """所有预设的 fields 与 defaults 键都必须是框架 items 元数据里真实登记的键。"""
    table = default_field_meta_table()
    assert entry_presets_mod.framework_preset_key_errors(table) == []
    known = _items_keys()
    presets = entry_presets_mod.framework_presets("items")
    assert presets, "框架 items 应有默认预设"
    for p in presets:
        for key in list(p["fields"]) + list(p["defaults"]):
            assert str(key) in known, f"{p['id']} 引用了未登记键 {key}"


def test_framework_six_presets_contract() -> None:
    presets = entry_presets_mod.framework_presets("items")
    assert [(p["id"], p["label"], p["id_prefix"]) for p in presets] == EXPECTED
    for p in presets:
        assert p["help"] and isinstance(p["help"], str)      # 一句话 help 齐备
        assert p["fields"] and all(isinstance(k, str) for k in p["fields"])
        assert set(p["defaults"]) <= set(p["fields"])        # defaults 只含关心字段
        assert p["id_prefix"]                                 # 供自动 ID 用


def test_framework_type_defaults_are_generic_words() -> None:
    """`type` 默认值取通用英文品类值（核查现有包后的口径，见文档/台账）。"""
    got = {p["id"]: p["defaults"].get("type") for p in entry_presets_mod.framework_presets("items")}
    assert got == {
        "material": "material", "currency_pouch": "currency", "potion": "consumable",
        "gift_box": "gift_box", "equipment": "equipment", "skill_book": "skill_book",
    }


def test_unknown_module_has_no_framework_presets() -> None:
    assert entry_presets_mod.framework_presets("things") == ()
    assert entry_presets_mod.merge_entry_presets("things") == ()


# ---------------------------------------------------------------------------
# 二、合并规则（纯函数）：同 id 包覆盖 / 追加 / 关闭 / 空白包
# ---------------------------------------------------------------------------
def test_merge_blank_pack_keeps_framework_defaults() -> None:
    merged = entry_presets_mod.merge_entry_presets("items")
    assert [p["id"] for p in merged] == [pid for pid, _l, _p in EXPECTED]


def test_merge_same_id_pack_overrides_whole_item() -> None:
    pack = [{"id": "material", "label": "包材料", "help": "包口径",
             "fields": ("name",), "defaults": {"type": "ore"}, "id_prefix": "ore"}]
    merged = entry_presets_mod.merge_entry_presets("items", pack)
    hit = [p for p in merged if p["id"] == "material"]
    assert len(hit) == 1
    # 整体覆盖：label/fields/defaults/id_prefix 全按包声明，不做字段级合并
    assert hit[0]["label"] == "包材料" and hit[0]["fields"] == ("name",)
    assert hit[0]["defaults"] == {"type": "ore"} and hit[0]["id_prefix"] == "ore"
    # 位置仍是框架默认的位置；其余五个默认不受影响
    assert [p["id"] for p in merged] == [pid for pid, _l, _p in EXPECTED]


def test_merge_pack_appends_new_preset() -> None:
    pack = [{"id": "relic", "label": "遗物", "help": "h",
             "fields": ("name", "desc"), "defaults": {}, "id_prefix": "relic"}]
    merged = entry_presets_mod.merge_entry_presets("items", pack)
    assert [p["id"] for p in merged] == [pid for pid, _l, _p in EXPECTED] + ["relic"]


def test_merge_disable_framework_and_pack_presets() -> None:
    pack = [{"id": "relic", "label": "遗物", "help": "h",
             "fields": ("name",), "defaults": {}, "id_prefix": "relic"}]
    merged = entry_presets_mod.merge_entry_presets(
        "items", pack, disabled=("gift_box", "relic"))
    ids = [p["id"] for p in merged]
    assert "gift_box" not in ids and "relic" not in ids
    assert ids == ["material", "currency_pouch", "potion", "equipment", "skill_book"]


def test_parse_entry_presets_disable_shape() -> None:
    decl = pack_meta.parse_field_meta(
        {"schema_version": 1, "entry_presets_disable": {"items": ["gift_box"]}}, "pk")
    assert decl.entry_presets_disable == {"items": ("gift_box",)}
    assert "entry_presets_disable" in pack_meta.TOP_LEVEL_KEYS
    for bad in ({"schema_version": 1, "entry_presets_disable": {"items": "gift_box"}},
                {"schema_version": 1, "entry_presets_disable": {"items": [""]}},
                {"schema_version": 1, "entry_presets_disable": {"items": ["a", "a"]}}):
        with pytest.raises(pack_meta.PackFieldMetaError):
            pack_meta.parse_field_meta(bad, "pk")


# ---------------------------------------------------------------------------
# 三、编辑器接入：空白包也有六种 / 覆盖 / 追加 / 关闭 / 自动 ID
# ---------------------------------------------------------------------------
@pytest.fixture()
def blank_root(tmp_path: Path) -> Path:
    """一份「空白包」副本（无 `field_meta.json`）：验证框架默认不依赖包声明。"""
    root = tmp_path / "content"
    root.mkdir()
    shutil.copytree(CONTENT / "demo_blank", root / "blank")
    return root


def test_blank_pack_has_six_framework_presets(blank_root: Path) -> None:
    d = api.new_entry_detail("blank", "items", root=blank_root, name="新")
    got = [(p["id"], p["label"]) for p in d["presets"]]
    assert got == [(pid, label) for pid, label, _p in EXPECTED]
    assert all(p["help"] for p in d["presets"])
    # 不选预设 = 现状回归：全部字段主区、无「其他字段」
    assert d["preset"] == "" and d["other_fields"] == []
    assert d["suggested_id"] == "item_001"


def _pack_with_presets(root: Path, name: str, decl: Dict[str, Any]) -> str:
    pack = root / name
    pack.mkdir()
    (pack / "manifest.json").write_text(json.dumps({
        "name": name, "version": "1", "schema_version": 1, "modules": ["items"],
    }, ensure_ascii=False), encoding="utf-8")
    (pack / "items.json").write_text(json.dumps([
        {"id": "mat_001", "name": "旧材料", "type": "material"},
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    (pack / "field_meta.json").write_text(json.dumps(
        {"schema_version": 1, **decl}, ensure_ascii=False, indent=2), encoding="utf-8")
    return name


def test_api_pack_override_append_disable(blank_root: Path) -> None:
    name = _pack_with_presets(blank_root, "packp", {
        "entry_presets": {"items": [
            {"id": "material", "label": "包材料", "help": "包口径",
             "fields": ["name", "desc"], "defaults": {"type": "ore"}, "id_prefix": "ore"},
            {"id": "relic", "label": "遗物", "help": "包新增",
             "fields": ["name"], "defaults": {}},
        ]},
        "entry_presets_disable": {"items": ["gift_box"]},
    })
    d = api.new_entry_detail(name, "items", root=blank_root, name="x")
    ids = [p["id"] for p in d["presets"]]
    assert ids == ["material", "currency_pouch", "potion", "equipment", "skill_book", "relic"]
    # 覆盖生效：材料预设按包声明（label/字段/默认值/前缀）
    d2 = api.new_entry_detail(name, "items", root=blank_root, name="x", preset="material")
    assert d2["preset_help"] == "包口径"
    assert [f["key"] for f in d2["fields"]] == ["name", "desc"]
    assert api.suggest_id(name, "items", root=blank_root, name="x", preset="material")[
        "suggested_id"] == "ore_001"
    # 追加生效：新增预设命中
    d3 = api.new_entry_detail(name, "items", root=blank_root, name="x", preset="relic")
    assert [f["key"] for f in d3["fields"]] == ["name"]
    # 关闭生效：被关闭的框架默认不可选（未命中 → 现状）
    d4 = api.new_entry_detail(name, "items", root=blank_root, name="x", preset="gift_box")
    assert d4["preset"] == "gift_box" and d4["fields"] and not d4["other_fields"]


def test_api_preset_field_order_and_other_fields(blank_root: Path) -> None:
    d = api.new_entry_detail("blank", "items", root=blank_root, name="x", preset="material")
    # 主区顺序 = 预设声明的 fields 顺序（含 type/price）
    assert [f["key"] for f in d["fields"]] == [
        "name", "type", "desc", "rarity", "material_tier", "source", "price"]
    # 其余字段进「其他字段」折叠区且**仍可编辑**（一号原则）
    assert d["other_fields"] and all(f["editable"] for f in d["other_fields"])
    assert d["preset_missing_fields"] == []
    assert d["field_count"] == len(d["fields"]) + len(d["other_fields"])


def test_api_suggest_id_uses_preset_prefix(blank_root: Path) -> None:
    # 空白包 items.json 已有 id "potion"（不匹配前缀）→ mat_001
    out = api.suggest_id("blank", "items", root=blank_root, name="龙鳞", preset="material")
    assert out["suggested_id"] == "mat_001" and out["id_rule"]["prefix"] == "mat"
    for preset, prefix in (("currency_pouch", "pouch"), ("potion", "potion"),
                           ("gift_box", "gift"), ("equipment", "eq"),
                           ("skill_book", "book")):
        assert api.suggest_id("blank", "items", root=blank_root, name="x",
                              preset=preset)["suggested_id"] == f"{prefix}_001"
    # 不选预设 → 模块级兜底（无包声明 → item_001），行为与现状一致
    assert api.suggest_id("blank", "items", root=blank_root, name="x")[
        "suggested_id"] == "item_001"


def test_api_defaults_applied_from_framework_preset(blank_root: Path) -> None:
    d = api.new_entry_detail("blank", "items", root=blank_root, name="x", preset="potion")
    f = {x["key"]: x for x in d["fields"]}
    assert f["type"]["value"] == "consumable" and f["usable"]["value"] is True
    assert f["effects"]["value"] == []


# ---------------------------------------------------------------------------
# 四、端到端：按「材料」预设真写盘 → 回退逐字节复原
# ---------------------------------------------------------------------------
def test_blank_pack_create_with_material_preset_then_rollback(blank_root: Path) -> None:
    pack_dir = blank_root / "blank"
    before = (pack_dir / "items.json").read_bytes()
    env = editor_ops.create_entry(
        "blank", "items", "mat_001", {"name": "新素材", "desc": "测试"},
        root=blank_root, preset="material")
    assert env["ok"] is True, env
    written = json.loads((pack_dir / "items.json").read_text(encoding="utf-8"))
    assert len(written) == 2
    new = written[1]
    # defaults 落盘：type=material（服务端按生效预设初始化，不依赖前端提交）
    assert new["type"] == "material" and new["name"] == "新素材"
    assert new["id"] == "mat_001"
    assert written[0] == {"id": "potion", "name": "药水", "type": "consumable",
                          "price": 100, "effects": ["heal_small"], "usable": True}
    rb = editor_ops.rollback_module("blank", "items", root=blank_root)
    assert rb.get("ok") is True, rb
    assert (pack_dir / "items.json").read_bytes() == before


def test_create_without_preset_is_regression(blank_root: Path) -> None:
    pack_dir = blank_root / "blank"
    env = editor_ops.create_entry("blank", "items", "item_001", {"name": "无预设"},
                                  root=blank_root)
    assert env["ok"] is True, env
    written = json.loads((pack_dir / "items.json").read_text(encoding="utf-8"))
    # 无预设 → 不注入框架预设 defaults（type 未写）
    assert "type" not in written[1]


# ---------------------------------------------------------------------------
# 五、HTTP 写链路：`presets` 来自框架默认 + POST 按预设 defaults 落盘
# ---------------------------------------------------------------------------
def test_http_blank_pack_framework_presets(blank_root: Path) -> None:
    from fastapi.testclient import TestClient

    from editor_host import create_app

    with TestClient(create_app(pack="blank", root=str(blank_root), role="owner")) as client:
        got = client.get("/api/pack/blank/module/items/new").json()
        assert [p["id"] for p in got["presets"]] == [pid for pid, _l, _p in EXPECTED]
        assert all(p["help"] for p in got["presets"])
        r = client.post("/api/pack/blank/module/items/entry",
                        json={"entry_id": "mat_001",
                              "patch": {"name": "新素材"}, "preset": "material"}).json()
        assert r["ok"] is True, r
        written = json.loads((blank_root / "blank" / "items.json").read_text(encoding="utf-8"))
        assert written[1]["type"] == "material"
