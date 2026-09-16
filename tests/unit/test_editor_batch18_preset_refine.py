"""编辑器重写批18 · 框架默认预设细化（段 A）测试。

任务书（批18 · 段 A）：
  1. **装备**预设字段扩到全属性——在原有基础上加入全部属性白值
     `hp,mp,str,con,spr,lck,spd,mag`；顺序 = 标识/部位 → 攻防 → 属性白值 → 百分比/会心；
  2. **药剂**预设 `help` 明确「持续回合在引用的效果里设置（效果的『持续』/『turns』字段）」，
     字段保持 `name,type,desc,usable,effects,price`；**不加**物品级 `duration`（持续属效果语义）；
  3. **货币袋 / 技能书**预设 `help` 补充「需要对应效果类型（给货币 / 学技能），见
     `gain_currency` / `learn_skill`」；
  4. 六个预设 `fields`/`defaults` 键仍须全部通过「框架 items 元数据存在性」断言。

通用、不写死内容包业务名；只读框架元数据与预设表。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest

from qbot_rpg.content import entry_presets as entry_presets_mod
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"

ALL_WHITE_ATTRS = ("hp", "mp", "str", "con", "spr", "lck", "spd", "mag")
EQUIP_BASE = ("name", "type", "desc", "slot", "price")
EQUIP_COMBAT = ("dfn", "atk")
EQUIP_PCT_CRIT = ("atk_pct", "dfn_pct", "hp_pct", "crit")


def _items_keys() -> set:
    mmeta = default_field_meta_table().module("items")
    return {str(k) for k in mmeta.fields}


def _preset(pid: str) -> Dict[str, object]:
    hit = [p for p in entry_presets_mod.framework_presets("items") if p["id"] == pid]
    assert len(hit) == 1, pid
    return dict(hit[0])


# ---------------------------------------------------------------------------
# 一、键存在性断言（六预设，防臆造键名）
# ---------------------------------------------------------------------------
def test_six_presets_keys_still_registered() -> None:
    table = default_field_meta_table()
    assert entry_presets_mod.framework_preset_key_errors(table) == []
    known = _items_keys()
    for p in entry_presets_mod.framework_presets("items"):
        for key in list(p["fields"]) + list(p["defaults"]):
            assert str(key) in known, f"{p['id']} 引用了未登记键 {key}"


def test_six_presets_still_six() -> None:
    presets = entry_presets_mod.framework_presets("items")
    assert [p["id"] for p in presets] == [
        "material", "currency_pouch", "potion", "gift_box", "equipment", "skill_book"]


# ---------------------------------------------------------------------------
# 二、装备：全属性白值 + 顺序
# ---------------------------------------------------------------------------
def test_equipment_preset_covers_all_white_attributes() -> None:
    fields: List[str] = list(_preset("equipment")["fields"])
    for key in ALL_WHITE_ATTRS:
        assert key in fields, f"装备预设缺属性白值 {key}"
    # 原有关键键仍在（不因扩展而丢）
    for key in ("name", "type", "desc", "slot", "price", "dfn", "atk",
                "atk_pct", "dfn_pct", "crit", "agi", "hp_pct"):
        assert key in fields, f"装备预设丢了原有键 {key}"


def test_equipment_preset_field_order() -> None:
    fields = list(_preset("equipment")["fields"])
    # 标识/部位 → 攻防 → 属性白值（含 agi）→ 百分比/会心
    assert fields[: len(EQUIP_BASE)] == list(EQUIP_BASE)
    assert fields[len(EQUIP_BASE): len(EQUIP_BASE) + len(EQUIP_COMBAT)] == list(EQUIP_COMBAT)
    white = fields[len(EQUIP_BASE) + len(EQUIP_COMBAT): len(fields) - len(EQUIP_PCT_CRIT)]
    assert set(ALL_WHITE_ATTRS) <= set(white)
    assert "agi" in white and white.index("agi") == len(white) - 1
    assert fields[-len(EQUIP_PCT_CRIT):] == list(EQUIP_PCT_CRIT)
    # 属性白值全部在百分比/会心之前
    assert max(fields.index(k) for k in ALL_WHITE_ATTRS) < min(
        fields.index(k) for k in EQUIP_PCT_CRIT)


# ---------------------------------------------------------------------------
# 三、药剂：help 文案 + 字段不变 + 无物品级 duration
# ---------------------------------------------------------------------------
def test_potion_fields_unchanged_and_no_item_duration() -> None:
    p = _preset("potion")
    assert list(p["fields"]) == ["name", "type", "desc", "usable", "effects", "price"]
    assert "duration" not in p["fields"]
    assert list(p["defaults"]) == ["type", "usable", "effects"]
    # 主 agent 裁定：持续属效果语义——items 元数据里也没有物品级 duration 字段
    assert "duration" not in _items_keys()


def test_potion_help_states_duration_lives_in_effect() -> None:
    help_text = str(_preset("potion")["help"])
    assert "持续回合" in help_text
    assert "效果" in help_text
    assert "turns" in help_text
    # 明确「在引用的效果里设置」这一语义
    assert "效果里设置" in help_text or "效果中设置" in help_text


# ---------------------------------------------------------------------------
# 四、货币袋 / 技能书：help 指向新效果类型
# ---------------------------------------------------------------------------
def test_currency_pouch_help_points_to_gain_currency() -> None:
    help_text = str(_preset("currency_pouch")["help"])
    assert "gain_currency" in help_text
    assert "learn_skill" in help_text


def test_skill_book_help_points_to_learn_skill() -> None:
    help_text = str(_preset("skill_book")["help"])
    assert "learn_skill" in help_text
    assert "gain_currency" in help_text


def test_currency_pouch_and_skill_book_fields_unchanged() -> None:
    assert list(_preset("currency_pouch")["fields"]) == [
        "name", "type", "desc", "usable", "effects"]
    assert list(_preset("skill_book")["fields"]) == [
        "name", "type", "desc", "usable", "effects", "price"]


# ---------------------------------------------------------------------------
# 五、编辑器接入：装备预设主区顺序即新字段顺序（真读生效预设表）
# ---------------------------------------------------------------------------
@pytest.fixture()
def blank_root(tmp_path: Path) -> Path:
    import shutil

    root = tmp_path / "content"
    root.mkdir()
    shutil.copytree(CONTENT / "demo_blank", root / "blank")
    return root


def test_editor_equipment_preset_main_fields_match(blank_root: Path) -> None:
    d = api.new_entry_detail("blank", "items", root=blank_root, name="x", preset="equipment")
    got = [f["key"] for f in d["fields"]]
    assert got == list(_preset("equipment")["fields"])
    for key in ALL_WHITE_ATTRS:
        assert key in got
    # 一号原则：其余字段进折叠区仍可编辑
    assert all(f["editable"] for f in d["other_fields"])


def test_editor_potion_preset_help_surfaced(blank_root: Path) -> None:
    d = api.new_entry_detail("blank", "items", root=blank_root, name="x", preset="potion")
    assert "turns" in d["preset_help"] and "持续回合" in d["preset_help"]
    # 未选预设里的 help 也在下拉候选上可见
    presets = {p["id"]: p for p in api.new_entry_detail(
        "blank", "items", root=blank_root, name="x")["presets"]}
    assert "gain_currency" in presets["currency_pouch"]["help"]
    assert "learn_skill" in presets["skill_book"]["help"]


def test_editor_blank_pack_still_six(blank_root: Path) -> None:
    d = api.new_entry_detail("blank", "items", root=blank_root, name="x")
    assert [p["id"] for p in d["presets"]] == [
        "material", "currency_pouch", "potion", "gift_box", "equipment", "skill_book"]
    assert json.dumps(d["presets"], ensure_ascii=False)  # 可序列化（HTTP 链路）


# ---------------------------------------------------------------------------
# 六、页脚批次串（当前批目标串；旧批次串不得残留）
# ---------------------------------------------------------------------------
def test_footer_batch_string_is_current() -> None:
    html = (REPO / "qbot_rpg" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "批28 · D组收尾" in html
    assert "批17 · 通用预设" not in html
