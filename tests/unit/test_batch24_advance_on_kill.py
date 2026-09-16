"""批24 · E5：副本层间推进 `advance_on_kill_count`
（CakeGame `ext_smallcopymap副本组.md:77`；§三 E5）。

现状核查（如实）：引擎**无**按击杀推进的等价机制——副本层间只有「通道走图 + dungeon.maps
顺序序列集合隔离」（`world/movement._step_walk`）；`grep advance/层间/kill_count` 于
`core/dungeon*.py` / `content/dungeon_models.py` / `field_meta_child_structure.py` 零命中
（补漏报告 V16 维持 ②）。故本批新增，不跳过。

设计口径（本批拍板，写进报告）：
  · `dungeon.advance_on_kill_count`（≥1 整数）：副本内累计击杀达阈值 → `current_map`
    按 `dungeon.maps` **既有顺序序列**推进到下一张；余量结转；最后一层封顶不再推进；
  · 会话新增 `kill_count` 字段（frozen + with_kill_count，随 to_dict/from_dict 落档）；
  · 引擎落点 = `core.dungeon.record_dungeon_kill`，并接入 `explore_run` 的 `("kill", n)` 动作；
  · 缺省/非法阈值 → 不改会话（行为与现状逐字段一致）。

覆盖：
  - 元数据登记 + 编辑器接口可见；
  - 校验：非整数 → R-1 红；0/-1 → R-2 红；缺省不红；
  - 引擎消费（状态级）：未达阈值不推进；达阈值推进下一层（贴 from/to/kills）；余量结转；
    末层封顶；explore_run ("kill") 接线；会话持久化 round-trip；
  - 回归：不带该字段 → record_dungeon_kill 不改会话。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.dungeon import (
    DungeonSession,
    DungeonStateMachine,
    explore_run,
    record_dungeon_kill,
)
from qbot_rpg.web import api

_DUNGEON: Dict[str, Any] = {
    "id": "tower", "name": "试炼塔", "type": "explore",
    "maps": ["floor1", "floor2", "floor3"], "safe_zone": "floor1",
    "advance_on_kill_count": 3,
}
_MAPS = [
    {"id": "floor1", "name": "一层", "monsters": [], "exits": {}},
    {"id": "floor2", "name": "二层", "monsters": [], "exits": {}},
    {"id": "floor3", "name": "三层", "monsters": [], "exits": {}},
]


def _ctx() -> dict:
    return {"map_id": "entrance", "maps": [dict(m) for m in _MAPS]}


def _session() -> DungeonSession:
    ent = DungeonStateMachine().enter(_ctx(), _DUNGEON)
    assert ent["ok"] is True
    return ent["session"]


# ---------------------------------------------------------------------------
# E5 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_e5_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("dungeon").fields.get("advance_on_kill_count")
    assert fm is not None, "dungeon 缺 advance_on_kill_count 登记"
    assert fm.type == "int" and fm.range_min == 1
    assert fm.label == "击杀推进阈值" and fm.help


def test_e5_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_e5"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e5", "version": "1", "schema_version": 1, "modules": ["dungeon"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "dungeon.json").write_text(json.dumps(
        [{"id": "tower", "name": "试炼塔", "type": "explore", "maps": ["a"],
          "advance_on_kill_count": 5}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_e5", "dungeon", "tower", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "advance_on_kill_count")
    assert f["present"] is True and f["type"] == "int"
    assert f["label"] == "击杀推进阈值"


# ---------------------------------------------------------------------------
# E5 校验
# ---------------------------------------------------------------------------
def test_e5_validator_types_red() -> None:
    report = check_pack({"dungeon": [
        {"id": "d1", "name": "D", "type": "explore", "maps": ["m"],
         "advance_on_kill_count": "3"}]})
    assert [e for e in report.errors if e.kind == "R-1"
            and "advance_on_kill_count" in e.field]


def test_e5_validator_non_positive_red() -> None:
    for bad in (0, -1):
        report = check_pack({"dungeon": [
            {"id": "d1", "name": "D", "type": "explore", "maps": ["m"],
             "advance_on_kill_count": bad}]})
        assert [e for e in report.errors if e.kind == "R-2"
                and "advance_on_kill_count" in e.field], bad


def test_e5_validator_missing_ok() -> None:
    report = check_pack({"dungeon": [
        {"id": "d1", "name": "D", "type": "explore", "maps": ["m"]}]})
    assert not [e for e in report.errors if "advance_on_kill_count" in e.field]


# ---------------------------------------------------------------------------
# E5 引擎消费：阈值前不推进 / 达阈值推进 / 余量结转 / 末层封顶
# ---------------------------------------------------------------------------
def test_e5_below_threshold_no_advance() -> None:
    ctx = _ctx()
    s = _session()
    r1 = record_dungeon_kill(ctx, _DUNGEON, s, 1)
    r2 = record_dungeon_kill(ctx, _DUNGEON, r1["session"], 1)
    assert r2["advanced"] is False and r2["to"] == "floor1"
    assert r2["kills"] == 2 and r2["threshold"] == 3


def test_e5_reaching_threshold_advances() -> None:
    ctx = _ctx()
    s = _session()
    step = s
    for _ in range(3):
        r = record_dungeon_kill(ctx, _DUNGEON, step, 1)
        step = r["session"]
    assert r["advanced"] is True
    assert r["from"] == "floor1" and r["to"] == "floor2"
    assert r["kills"] == 0, "恰好达阈值 → 余量 0"
    assert step.current_map == "floor2"
    assert ctx["map_id"] == "floor2", "玩家位置同步推进"


def test_e5_carry_over_remainder() -> None:
    ctx = _ctx()
    s = _session()
    r = record_dungeon_kill(ctx, _DUNGEON, s, 5)   # 5 ≥ 3 → 推进 + 余 2
    assert r["advanced"] is True and r["to"] == "floor2" and r["kills"] == 2


def test_e5_last_floor_capped() -> None:
    ctx = _ctx()
    ent = DungeonStateMachine().enter(ctx, _DUNGEON)
    s = ent["session"].with_current_map("floor3")
    r = record_dungeon_kill(ctx, _DUNGEON, s, 3)
    assert r["advanced"] is False and r["to"] == "floor3"
    assert r["kills"] == 3, "末层封顶不再推进"


def test_e5_explore_run_kill_action() -> None:
    ctx = _ctx()
    out = explore_run(ctx, _DUNGEON, _MAPS,
                      actions=[("kill", 1), ("kill", 1), ("kill", 1)])
    kill_steps = [s for s in out["steps"] if s.get("event") == "kill"]
    assert len(kill_steps) == 3
    assert kill_steps[-1]["advanced"] is True
    assert kill_steps[-1]["to"] == "floor2"
    assert out["session"].current_map == "floor2"


def test_e5_session_persist_roundtrip() -> None:
    ctx = _ctx()
    s = _session()
    r = record_dungeon_kill(ctx, _DUNGEON, s, 2)
    blob = r["session"].to_dict()
    assert blob["kill_count"] == 2
    rebuilt = DungeonSession.from_dict(blob)
    assert rebuilt.kill_count == 2
    assert rebuilt.to_dict() == blob


# ---------------------------------------------------------------------------
# E5 回归：不带该字段 → 不改会话（行为与现状逐字段一致）
# ---------------------------------------------------------------------------
def test_e5_regression_without_field_unchanged() -> None:
    ddef = {k: v for k, v in _DUNGEON.items() if k != "advance_on_kill_count"}
    ctx = _ctx()
    s = _session()
    r = record_dungeon_kill(ctx, ddef, s, 5)
    assert r["advanced"] is False and r["threshold"] is None
    assert r["session"] == s, "无字段 → 会话逐字段不变"
    assert ctx["map_id"] == "entrance", "无字段 → 不改玩家位置"


# ---------------------------------------------------------------------------
# E5 端到端：临时内容根建包 → 加载 → 按其阈值推进
# ---------------------------------------------------------------------------
def test_e5_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_e5"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_e5", "version": "1", "schema_version": 1,
         "modules": ["dungeon", "maps"]}, ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(_MAPS, ensure_ascii=False), encoding="utf-8")
    (root / "dungeon.json").write_text(json.dumps(
        [_DUNGEON], ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    ddef = pack.modules["dungeon"][0]
    ctx = _ctx()
    s = _session()
    r = record_dungeon_kill(ctx, ddef, s, 3)
    assert r["advanced"] is True and r["to"] == "floor2"
