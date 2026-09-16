"""批24 · E2：主动遭遇概率 + 参战数区间（CakeGame `Config_Map.md:68/69`；§三 E2）。

设计口径（本批拍板，写进报告）：
  · 挂在**刷怪行**（`maps.monsters[]` 行上，不新造一层）：`encounter_chance`（百分数 0-100）
    + `encounter_count_min` / `encounter_count_max`（参战数随机区间）；
  · 引擎落点 = `world.encounter.roll_encounter`，接在 `world.movement.move_to_map`（进入/移动
    结算）——命中返回 `encounter` 信号 {enemy, count, min, max}；
  · 随机源 = 引擎既有 RNG 口径（`random.Random`；`rng` 参数 > `ctx["rng"]`），不得另造；
  · 边界：`min > max` → 校验红拦；`chance=0`/缺字段 → 不主动触发（行为与现状逐字段一致）。

覆盖：
  - 元数据登记（monsters 行三键）+ 编辑器接口可见；
  - 校验：min>max → R-5 红；chance 非整数 R-1 / 负数 R-2（泛型）；0/缺省不红；
  - 引擎消费（多种子、确定性）：触发/不触发两态与独立重放一致 + 参战数落在区间；
  - 集成：move_to_map → encounter 信号；resolve_move 透传；
  - 回归：不带 encounter 字段 → move_to_map 返回逐字段一致（无 encounter 键）。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.world.encounter import roll_encounter
from qbot_rpg.world.movement import move_to_map, resolve_move
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api


def _map(rows: List[Dict[str, Any]], mid: str = "wild") -> Dict[str, Any]:
    return {"id": mid, "name": "野外", "desc": "荒野", "monsters": rows, "exits": {}}


# ---------------------------------------------------------------------------
# E2 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_e2_metadata_registered() -> None:
    tbl = default_field_meta_table()
    mrow = tbl.module("maps").fields["monsters"].element.children
    assert "encounter_chance" in mrow
    assert mrow["encounter_chance"].type == "int"
    assert mrow["encounter_chance"].range_min == 0 and mrow["encounter_chance"].range_max == 100
    assert mrow["encounter_count_min"].type == "int"
    assert mrow["encounter_count_max"].type == "int"
    # 不新造层级：仍在刷怪行上（与 count/hidden_boss 同行）
    assert "count" in mrow and "hidden_boss" in mrow


def test_e2_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_e2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2", "version": "1", "schema_version": 1, "modules": ["maps"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(
        [_map([{"enemy": "wolf", "count": 3, "respawn_minutes": 5,
                "encounter_chance": 40, "encounter_count_min": 1,
                "encounter_count_max": 3}])], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_e2", "maps", "wild", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "monsters")
    keys = [c["key"] for c in f["element"]["children"]]
    assert {"encounter_chance", "encounter_count_min", "encounter_count_max"} <= set(keys)


# ---------------------------------------------------------------------------
# E2 校验
# ---------------------------------------------------------------------------
def test_e2_validator_min_gt_max_red() -> None:
    report = check_pack({"maps": [_map([
        {"enemy": "e", "respawn_minutes": 5, "encounter_count_min": 5,
         "encounter_count_max": 2}])]})
    assert [e for e in report.errors
            if e.kind == "R-5" and "encounter_count_min" in e.field]


def test_e2_validator_min_le_max_ok() -> None:
    report = check_pack({"maps": [_map([
        {"enemy": "e", "respawn_minutes": 5, "encounter_count_min": 2,
         "encounter_count_max": 2}])]})
    assert not [e for e in report.errors if "encounter" in e.field]


def test_e2_validator_types_red() -> None:
    report = check_pack({"maps": [_map([
        {"enemy": "e", "respawn_minutes": 5, "encounter_chance": "high"}])]})
    assert [e for e in report.errors if e.kind == "R-2" and "encounter_chance" in e.field]
    report_chance = check_pack({"maps": [_map([
        {"enemy": "e", "respawn_minutes": 5, "encounter_chance": 150}])]})
    assert [e for e in report_chance.errors
            if e.kind == "R-2" and "encounter_chance" in e.field]
    report2 = check_pack({"maps": [_map([
        {"enemy": "e", "respawn_minutes": 5, "encounter_count_max": -1}])]})
    assert [e for e in report2.errors if e.kind == "R-2" and "encounter_count_max" in e.field]


def test_e2_validator_zero_and_missing_ok() -> None:
    report = check_pack({"maps": [
        _map([{"enemy": "e", "respawn_minutes": 5, "encounter_chance": 0}]),
        _map([{"enemy": "e", "respawn_minutes": 5}], mid="wild2")]})
    assert not [e for e in report.errors if "encounter" in e.field]


# ---------------------------------------------------------------------------
# E2 引擎消费：确定性触发/不触发 + 参战数区间（多种子，独立重放）
# ---------------------------------------------------------------------------
def test_e2_roll_deterministic_and_in_range() -> None:
    chance = 50
    row = {"enemy": "wolf", "count": 3, "encounter_chance": chance,
           "encounter_count_min": 2, "encounter_count_max": 5}
    m = _map([row])
    seen_true = seen_false = False
    for seed in range(40):
        res = roll_encounter(m, random.Random(seed))
        expected_hit = random.Random(seed).random() * 100 < chance
        assert (res is not None) == expected_hit, f"seed={seed}"
        if res is not None:
            seen_true = True
            assert 2 <= res["count"] <= 5, f"seed={seed} count={res['count']}"
            assert res["enemy"] == "wolf" and res["min"] == 2 and res["max"] == 5
        else:
            seen_false = True
    assert seen_true and seen_false, "多种子必须覆盖触发/不触发两态"


def test_e2_chance_zero_never_triggers() -> None:
    m = _map([{"enemy": "wolf", "count": 3, "encounter_chance": 0,
               "encounter_count_min": 1, "encounter_count_max": 5}])
    for seed in range(20):
        assert roll_encounter(m, random.Random(seed)) is None


def test_e2_missing_field_never_triggers() -> None:
    m = _map([{"enemy": "wolf", "count": 3}])
    for seed in range(20):
        assert roll_encounter(m, random.Random(seed)) is None


def test_e2_no_range_falls_back_to_row_count() -> None:
    m = _map([{"enemy": "wolf", "count": 4, "encounter_chance": 100}])
    res = roll_encounter(m, random.Random(7))
    assert res is not None and res["count"] == 4
    assert res["min"] == res["max"] == 4


def test_e2_first_hit_short_circuits() -> None:
    m = _map([
        {"enemy": "a", "count": 1, "encounter_chance": 100, "encounter_count_min": 1,
         "encounter_count_max": 1},
        {"enemy": "b", "count": 9, "encounter_chance": 100, "encounter_count_min": 9,
         "encounter_count_max": 9},
    ])
    res = roll_encounter(m, random.Random(3))
    assert res is not None and res["enemy"] == "a"


# ---------------------------------------------------------------------------
# E2 集成：move_to_map → encounter 信号；resolve_move 透传
# ---------------------------------------------------------------------------
def _ctx(maps: List[Dict[str, Any]], rng: Any = None, map_id: str = "town") -> dict:
    ctx: Dict[str, Any] = {
        "maps": maps, "map_id": map_id, "location": map_id,
        "player": {"map_id": map_id},
        "persistent_state": {"location": map_id},
    }
    if rng is not None:
        ctx["rng"] = rng
    return ctx


def test_e2_move_to_map_emits_encounter() -> None:
    maps = [
        {"id": "town", "name": "村", "monsters": [], "exits": {"up": {"to": "wild"}}},
        _map([{"enemy": "wolf", "count": 2, "encounter_chance": 100,
               "encounter_count_min": 3, "encounter_count_max": 3}]),
    ]
    ctx = _ctx(maps, rng=random.Random(0))
    moved = move_to_map(ctx, "wild", maps=maps)
    assert moved["ok"] is True
    assert moved["encounter"]["enemy"] == "wolf"
    assert moved["encounter"]["count"] == 3, "min=max=3 → 参战数恒 3"


def test_e2_resolve_move_propagates_encounter() -> None:
    maps = [
        {"id": "town", "name": "村", "monsters": [],
         "exits": {"up": {"to": "wild", "mode": "bidirectional"}}},
        {"id": "wild", "name": "野外",
         "monsters": [{"enemy": "wolf", "count": 2, "respawn_minutes": 5,
                       "encounter_chance": 100}],
         "exits": {"down": {"to": "town", "mode": "bidirectional"}}},
    ]
    ctx = _ctx(maps, rng=random.Random(0))
    res = resolve_move(ctx, "上", maps=maps)
    assert res["ok"] is True and res["to"] == "wild"
    assert res.get("encounter", {}).get("enemy") == "wolf"


# ---------------------------------------------------------------------------
# E2 回归：不带 encounter 字段 → move_to_map 返回逐字段一致（无 encounter 键）
# ---------------------------------------------------------------------------
def test_e2_regression_without_field_identical() -> None:
    maps = [
        {"id": "town", "name": "村", "monsters": [], "exits": {"up": {"to": "plain"}}},
        {"id": "plain", "name": "荒原", "monsters": [{"enemy": "e", "count": 1}],
         "exits": {"down": {"to": "town"}}},
    ]
    a = _ctx(maps, rng=random.Random(1))
    got = move_to_map(a, "plain", maps=maps)
    want = {"ok": True, "map_id": "plain", "name": "荒原", "desc": None, "lore": None}
    assert got == want, got
    # chance=0 同样不加键（行为与现状一致）
    maps0 = [dict(maps[0]),
             {"id": "plain", "name": "荒原",
              "monsters": [{"enemy": "e", "count": 1, "encounter_chance": 0}],
              "exits": {"down": {"to": "town"}}}]
    c = _ctx(maps0, rng=random.Random(2))
    assert "encounter" not in move_to_map(c, "plain", maps=maps0)


# ---------------------------------------------------------------------------
# E2 端到端：临时内容根建包 → 加载 → 进图触发遭遇
# ---------------------------------------------------------------------------
def test_e2_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_e2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_e2", "version": "1", "schema_version": 1, "modules": ["maps"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(
        [_map([{"enemy": "wolf", "count": 2, "respawn_minutes": 5,
                "encounter_chance": 100,
                "encounter_count_min": 2, "encounter_count_max": 4}])],
        ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    maps = pack.modules["maps"]
    ctx = _ctx(maps, rng=random.Random(5), map_id="town")
    moved = move_to_map(ctx, "wild", maps=maps)
    enc = moved.get("encounter")
    assert enc is not None and 2 <= enc["count"] <= 4
