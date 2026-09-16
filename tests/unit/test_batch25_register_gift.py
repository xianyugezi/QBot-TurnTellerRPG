"""批25 · K1：注册初始礼包 + 初始等级（CakeGame `Global.md:60,87-89`）。

设计口径（本批拍板，写进报告）：
  · `settings.register_gift` = 列表条目 `{item/id, count}`（沿用既有 `currencies: []` 列表风格），
    新注册玩家发放；`settings.register_level` = int ≥1（初始等级）。
  · **先核查**：注册流程原先只给 default_map/default_job/stats 初始属性，`build_initial_player`
    写死 `level=1`、`inventory=[]`——**无等价初始礼包/初始等级配置** → 本批新增，不跳过。
  · 级上限沿用既有 `settings.level_cap`（只用于把初始等级夹到 [1, cap]，不新开上限键）。

覆盖：元数据登记 + 编辑器可见 / 校验 / 引擎（注册后数值级拿到礼包与等级）/ 落档转换 / 回归。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.assembly.runner import _player_from_dict
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.register_commands import build_initial_player, cmd_register
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api

_JOBS = {"warrior": {"name": "战士", "recommended_newbie": True}}
_ITEMS = {"药水": {"id": "药水", "name": "药水"}, "铁矿": {"id": "铁矿", "name": "铁矿"}}


def make_ctx(**over) -> dict:
    base = {
        "registered": False,
        "player": None,
        "jobs": {k: dict(v) for k, v in _JOBS.items()},
        "stats": {"hp": {"name": "生命", "type": "resource", "base": 100},
                  "mp": {"name": "魔力", "type": "resource", "base": 30},
                  "str": {"name": "力量", "type": "combat", "base": 12}},
        "items": dict(_ITEMS),
        "settings": {"default_job_id": "warrior", "default_map": "新手村",
                     "world_name": "艾泽拉", "level_cap": 45},
        "name_exists": lambda name: False,
    }
    base.update(over)
    return base


def parse(raw: str):
    return parse_command(raw)


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_k1_metadata_registered() -> None:
    fields = default_field_meta_table().module("settings").fields
    for k in ("register_gift", "register_level"):
        assert k in fields, f"settings 缺 {k} 登记"
    gift = fields["register_gift"]
    assert gift.type == "list"
    assert gift.element.children["count"].type == "int"
    assert gift.element.children["item"].ref_target == "item"
    assert gift.label == "注册初始礼包"
    assert fields["register_level"].type == "int"
    assert fields["register_level"].label == "注册初始等级"


def test_k1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_k1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_k1", "version": "1", "schema_version": 1, "modules": ["settings"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "settings.json").write_text(json.dumps({
        "register_gift": [{"item": "药水", "count": 2}],
        "register_level": 5,
    }, ensure_ascii=False), encoding="utf-8")
    d1 = api.entry_detail("pack_k1", "settings", "register_gift", root=tmp_path)
    assert d1["name"] == "注册初始礼包"
    d2 = api.entry_detail("pack_k1", "settings", "register_level", root=tmp_path)
    assert d2["name"] == "注册初始等级"


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def test_k1_validator_invalid_red() -> None:
    report = check_pack({"settings": {
        "register_gift": "药水", "register_level": -3}})
    assert [e for e in report.errors if e.kind == "R-1" and "register_gift" in e.field]
    assert [e for e in report.errors if e.kind == "R-2" and "register_level" in e.field]
    report2 = check_pack({"settings": {
        "register_gift": [{"item": "药水", "count": -1}]}})
    assert [e for e in report2.errors if e.kind == "R-2" and "count" in e.field]


def test_k1_validator_valid_and_missing_ok() -> None:
    report = check_pack({"settings": {
        "register_gift": [{"item": "药水", "count": 2}, {"id": "铁矿", "count": 1}],
        "register_level": 5}})
    assert not [e for e in report.errors
                if "register_gift" in e.field or "register_level" in e.field], report.errors
    report2 = check_pack({"settings": {}})
    assert not [e for e in report2.errors
                if "register_gift" in e.field or "register_level" in e.field]


# ---------------------------------------------------------------------------
# 引擎消费：新账号注册后拿到礼包与初始等级（数值级）
# ---------------------------------------------------------------------------
def test_k1_register_grants_gift_and_level() -> None:
    ctx = make_ctx(settings={"default_job_id": "warrior", "default_map": "新手村",
                             "world_name": "艾泽拉", "level_cap": 45,
                             "register_level": 5,
                             "register_gift": [{"item": "药水", "count": 2},
                                               {"id": "铁矿", "count": 1}]})
    out = cmd_register(parse("/注册 阿伟 战士"), ctx)
    p = ctx["player"]
    assert p["level"] == 5, p
    assert ctx["level"] == 5
    assert p["inventory"] == [
        {"item_id": "药水", "name": "药水", "count": 2, "quality": "normal", "bound": False},
        {"item_id": "铁矿", "name": "铁矿", "count": 1, "quality": "normal", "bound": False},
    ], p["inventory"]
    assert "✅ 注册成功" in out
    # 落档转换：dict 初始背包 → Player.inventory（ItemInstance 元组）
    player = _player_from_dict(p, "10001")
    assert player.level == 5
    assert [(i.item_id, i.count) for i in player.inventory] == [("药水", 2), ("铁矿", 1)]


def test_k1_level_clamped_to_level_cap() -> None:
    ctx = make_ctx(settings={"default_job_id": "warrior", "default_map": "新手村",
                             "level_cap": 10, "register_level": 99})
    p = build_initial_player(ctx, "阿伟", "warrior")
    assert p["level"] == 10


def test_k1_gift_invalid_rows_skipped() -> None:
    ctx = make_ctx(settings={"default_job_id": "warrior", "register_level": 1,
                             "register_gift": ["药水", {"count": 2}, {"item": "铁矿",
                                                                      "count": 0}]})
    p = build_initial_player(ctx, "阿伟", "warrior")
    # 非法行（非对象 / 无 item / count<1 回落 1）——只保留可解析条目
    assert [(i["item_id"], i["count"]) for i in p["inventory"]] == [("铁矿", 1)]


# ---------------------------------------------------------------------------
# 回归：不带新字段 → 逐字段一致（level=1 / inventory=[]）
# ---------------------------------------------------------------------------
def test_k1_regression_without_fields_identical() -> None:
    ctx = make_ctx()
    p = build_initial_player(ctx, "阿伟", "warrior")
    assert p["level"] == 1 and p["inventory"] == []
    ctx2 = make_ctx()
    out = cmd_register(parse("/注册 阿伟 战士"), ctx2)
    assert ctx2["player"]["level"] == 1 and ctx2["player"]["inventory"] == []
    assert "✅ 注册成功" in out
