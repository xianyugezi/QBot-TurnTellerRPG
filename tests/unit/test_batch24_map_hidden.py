"""批24 · E1：地图隐藏（禁直接传送）`hidden`（CakeGame `Config_Map.Hid`；§三 E1）。

设计口径（本批拍板，写进报告）：
  · **单一布尔** `maps[].hidden`：置真 = 禁止**直接传送**进入该地图（只能经通道/剧情进入）；
  · 引擎落点 = 传送类入口（`world.movement.direct_teleport`）+ /地图 可传送列表过滤；
  · **不影响通道移动**：`resolve_move` 通道进入照常（隐藏只拦直接传送）；
  · 与隐藏**要素**视图（`monsters.hidden_boss` / `hidden_quest` / `achievements.hidden`）
    不同层，命名区分（本批不混用）。

覆盖：
  - 元数据登记（maps `hidden` bool + 中文 help）+ 编辑器接口可见；
  - 校验：非 bool → R-1 红；true/false/缺省不红不黄；
  - 引擎消费（状态级）：hidden 直接传送被拒（贴提示原文）+ ctx 不变；通道进入照常；
  - 序号传送/列表过滤：hidden 图不列 /地图、不被 /进入 N 选中；
  - 回归：不带 hidden → 逐字段一致（direct_teleport 与 move_to_map 同结果）。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.commands.explore_commands import cmd_enter, cmd_map
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api
from qbot_rpg.world.movement import direct_teleport, map_is_hidden, move_to_map, resolve_move


def parse(raw: str):
    return parse_command(raw)


#: 三图：起点村落（安全/无怪）—上→ 秘境（hidden）—下→ 起点；另有一条通往荒原的普通路。
_MAPS: List[Dict[str, Any]] = [
    {
        "id": "town", "name": "起点村", "desc": "宁静的村口", "monsters": [],
        "exits": {
            "up": {"to": "secret_grove", "mode": "bidirectional"},
            "right": {"to": "plain", "mode": "bidirectional"},
        },
    },
    {
        "id": "secret_grove", "name": "秘境林", "desc": "藤蔓遮蔽的林间秘境",
        "hidden": True, "monsters": [],
        "exits": {"down": {"to": "town", "mode": "bidirectional"}},
    },
    {
        "id": "plain", "name": "荒原", "desc": "开阔的荒原", "monsters": [],
        "exits": {"left": {"to": "town", "mode": "bidirectional"}},
    },
]


def _ctx(map_id: str = "town", discovered: Any = None) -> dict:
    ctx: Dict[str, Any] = {
        "registered": True,
        "is_gm": False,
        "settings": {"default_map": "town"},
        "maps": [dict(m) for m in _MAPS],
        "map_id": map_id,
        "location": map_id,
        "player": {"map_id": map_id, "name": "阿伟"},
        "persistent_state": {"location": map_id},
    }
    if discovered is not None:
        ctx["discovered_maps"] = list(discovered)
    return ctx


# ---------------------------------------------------------------------------
# E1 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_e1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("maps").fields.get("hidden")
    assert fm is not None, "maps 缺 hidden 登记"
    assert fm.type == "bool"
    assert fm.label == "隐藏（禁直接传送）"
    assert fm.help, "hidden 缺中文说明（说明卡）"
    assert tbl.module("maps").field_groups.get("hidden") == "base"
    # 与隐藏要素视图不同层：monsters.hidden_boss 仍是另一个键（不混用）
    mrow = tbl.module("maps").fields["monsters"].element.children
    assert mrow.get("hidden_boss") is not None and "hidden" not in mrow


def test_e1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_e1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e1", "version": "1", "schema_version": 1, "modules": ["maps"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(
        [{"id": "secret_grove", "name": "秘境林", "hidden": True, "monsters": [],
          "exits": {}}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_e1", "maps", "secret_grove", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "hidden")
    assert f["present"] is True
    assert f["type"] == "bool"
    assert f["label"] == "隐藏（禁直接传送）"


# ---------------------------------------------------------------------------
# E1 校验：非 bool → R-1 红；true/false/缺省不红
# ---------------------------------------------------------------------------
def test_e1_validator_non_bool_red() -> None:
    report = check_pack({"maps": [
        {"id": "m1", "name": "图一", "hidden": "yes"}]})
    assert [e for e in report.errors if e.kind == "R-1" and "hidden" in e.field]


def test_e1_validator_bool_and_missing_ok() -> None:
    report = check_pack({"maps": [
        {"id": "m1", "name": "图一", "hidden": True},
        {"id": "m2", "name": "图二", "hidden": False},
        {"id": "m3", "name": "图三"}]})
    assert not [e for e in report.errors if "hidden" in e.field]


# ---------------------------------------------------------------------------
# E1 引擎消费：hidden 直接传送被拒（贴原文）+ ctx 不变；通道照常
# ---------------------------------------------------------------------------
def test_e1_direct_teleport_rejected_message() -> None:
    ctx = _ctx("town")
    res = direct_teleport(ctx, "secret_grove", maps=ctx["maps"])
    assert res["ok"] is False and res["hidden"] is True
    assert res["reason"] == "「秘境林」是隐藏区域，无法直接传送——请从相邻地图的通道走过去"
    assert ctx["map_id"] == "town", "被拒不得改位置"
    assert ctx["location"] == "town"


def test_e1_channel_move_into_hidden_still_works() -> None:
    ctx = _ctx("town")
    res = resolve_move(ctx, "上", maps=ctx["maps"])
    assert res["ok"] is True and res["to"] == "secret_grove"
    assert ctx["map_id"] == "secret_grove"
    assert ctx["location"] == "secret_grove"


def test_e1_hidden_meta_distinct_from_hidden_boss() -> None:
    """命名区分：地图 hidden 与怪物行 hidden_boss 互不影响。"""
    assert map_is_hidden({"hidden": True}) is True
    assert map_is_hidden({"hidden_boss": True}) is False
    assert map_is_hidden(None) is False


# ---------------------------------------------------------------------------
# E1 列表/序号传送过滤
# ---------------------------------------------------------------------------
def test_e1_map_command_excludes_hidden() -> None:
    ctx = _ctx("town", discovered=["town", "secret_grove", "plain"])
    out = cmd_map(parse("/地图"), ctx)
    assert "秘境林" not in out, "hidden 图不得列 /地图"
    assert "起点村" in out and "荒原" in out


def test_e1_enter_numeric_cannot_select_hidden() -> None:
    ctx = _ctx("town", discovered=["town", "secret_grove", "plain"])
    # 已知列表只含 town / plain（secret 被过滤）→ 序号 2 = 荒原，绝不落到秘境
    out = cmd_enter(parse("/进入 2"), ctx)
    assert "荒原" in out and "秘境林" not in out
    assert ctx["persistent_state"]["location"] == "plain"


def test_e1_enter_numeric_hidden_not_in_ordered() -> None:
    from qbot_rpg.commands.explore_commands import _known_maps_for, _maps_index_for

    ctx = _ctx("town", discovered=["town", "secret_grove", "plain"])
    index = _maps_index_for(ctx)
    known = _known_maps_for(ctx, index)
    assert "secret_grove" not in known
    assert {"town", "plain"} <= known


# ---------------------------------------------------------------------------
# E1 回归：不带 hidden → 逐字段一致（direct_teleport == move_to_map）
# ---------------------------------------------------------------------------
def test_e1_regression_without_field_identical() -> None:
    a = _ctx("town")
    b = _ctx("town")
    got = direct_teleport(a, "plain", maps=a["maps"])
    want = move_to_map(b, "plain", maps=b["maps"])
    assert got == want, (got, want)
    assert a["map_id"] == b["map_id"] == "plain"


# ---------------------------------------------------------------------------
# E1 端到端：临时内容根建包 → 加载 → 传送被拒 / 通道可入
# ---------------------------------------------------------------------------
def test_e1_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_e1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_e1", "version": "1", "schema_version": 1, "modules": ["maps"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(_MAPS, ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    maps = pack.modules["maps"]
    secret = next(m for m in maps if m["id"] == "secret_grove")
    assert secret["hidden"] is True

    ctx = {"maps": maps, "map_id": "town", "location": "town"}
    res = direct_teleport(ctx, "secret_grove", maps=maps)
    assert res["ok"] is False and "隐藏区域" in res["reason"]
    assert resolve_move(ctx, "上", maps=maps)["to"] == "secret_grove"
