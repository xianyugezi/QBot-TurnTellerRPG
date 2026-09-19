"""批40 · H4 装备实例落档唯一键 `uid` 单测。

覆盖（依据 docs/深度打造_决策记录.md §一 H4 + 打造系统_C E1/Q1）：
  · 生成口径：`new_item_uid` 唯一/形态；`ItemInstance` 自动补发、显式保留、replace 保号、
    `compare=False`（结构等价语义不突变）；
  · 编解码/入库往返：uid 与 EquipmentSlot.uid 逐字段读回；**新库直接具备**（不经迁移步）；
  · 存档迁移 v2→v3：旧档 inventory 行全量补发、equipment 槽回指匹配行、无损（未知键/值
    原样）、幂等（重复执行零改动）；纯函数 `backfill_instance_uids` 同口径；
  · **同 id 两件实例不串**：穿戴聚合按 uid 取对行（对照旧机制「item_id 首匹配」的错行证据）；
  · 卸下/使用/扣减按 uid 精确定位（`InventoryEngine.remove_item(uid=...)` / `find_by_uid`）。

纪律：零 NoneBot；迁移用 tmp_path 真实文件库（**绝不触碰真实玩家库**）；不写真实内容包。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.inventory import InventoryEngine
from qbot_rpg.data.item import ItemInstance, new_item_uid
from qbot_rpg.data.player import EquipmentSlot, Player, PlayerAttributes
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.migrations import (
    DB_SCHEMA_VERSION,
    backfill_instance_uids,
    migrate_database,
)
from qbot_rpg.storage.repository import Repository
from qbot_rpg.storage.schema import CREATE_TABLE_META, CREATE_TABLE_PLAYERS

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
_HEX = set("0123456789abcdef")


def _item(item_id: str = "sword", atk: float = 5.0, **kw) -> ItemInstance:
    return ItemInstance(
        item_id=item_id, name=f"{item_id}-名", count=1, quality="normal",
        bound=False, stack_max=1, slot="weapon", stats_bonus={"atk": atk}, **kw,
    )


def _player(inv, equip, attrs=None):
    return {
        "inventory": list(inv),
        "equipment": dict(equip),
        "attributes": attrs if attrs is not None else PlayerAttributes(),
    }


# ---------------------------------------------------------------------------
# 生成口径与类型语义
# ---------------------------------------------------------------------------
def test_new_item_uid_unique_and_hex():
    """uid = 32 位小写十六进制；大批量互不相同（唯一口径）。"""
    ids = {new_item_uid() for _ in range(2000)}
    assert len(ids) == 2000
    assert all(len(u) == 32 and set(u) <= _HEX for u in ids)


def test_item_instance_autofills_uid_and_preserves_explicit():
    a = _item()
    assert a.uid and len(a.uid) == 32
    # 显式 uid 原样保留（迁移/等价重建路径）
    b = _item(uid="fixed-uid-0001")
    assert b.uid == "fixed-uid-0001"


def test_uid_excluded_from_equality_structure_semantics():
    """compare=False：结构等价的两件仍 `==`（不因 uid 破坏既有比较语义）。"""
    import dataclasses

    a = _item(atk=7.0)
    b = _item(atk=7.0)
    assert a.uid != b.uid
    assert a == b
    assert dataclasses.replace(a, count=1) == a


# ---------------------------------------------------------------------------
# 编解码 / 新库直接具备
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_codec_and_db_roundtrip_preserves_uid():
    row_item = _item(atk=9.0)
    player = Player(
        qid="10001", name="往返", inventory=(row_item,),
        achievement_state=(),  # 既有 codec 口径：成就态 tuple
        equipment={"weapon": EquipmentSlot(
            item_id="sword", name="剑", slot_level=2, gems=("ruby",), uid=row_item.uid)},
    )
    repo = Repository(Database(":memory:"))
    try:
        ok, msg = repo.codec_roundtrip(player)
        assert ok, msg
        ok2, msg2 = await repo.db_roundtrip(player)
        assert ok2, msg2
        back = await repo.load_player("10001")
        assert back is not None
        assert back.inventory[0].uid == row_item.uid
        assert back.equipment["weapon"].uid == row_item.uid
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_new_database_has_uid_without_migration_step():
    """新库直接具备：空库版本=当前值、新建实例天然带 uid、槽 uid 回指（不经 2→3）。"""
    repo = Repository(Database(":memory:"))
    try:
        it = _item(atk=3.0)
        assert it.uid
        await repo.save_player(Player(
            qid="10002", name="新库", inventory=(it,),
            equipment={"weapon": EquipmentSlot(item_id="sword", name="剑", uid=it.uid)},
        ))
        meta = await repo.db.fetchone_read(
            "SELECT db_schema_version FROM meta WHERE key='global'"
        )
        assert int(meta["db_schema_version"]) == DB_SCHEMA_VERSION == 3
        back = await repo.load_player("10002")
        assert back is not None and back.inventory[0].uid == it.uid
    finally:
        await repo.close()


# ---------------------------------------------------------------------------
# 迁移纯函数：幂等 / 无损 / 槽回指
# ---------------------------------------------------------------------------
def test_backfill_instance_uids_idempotent_and_lossless():
    inv = [
        {"item_id": "sword", "name": "甲", "count": 1, "stats_bonus": {"atk": 1.0},
         "custom_key": "keepA"},
        {"item_id": "sword", "name": "乙", "count": 1, "stats_bonus": {"atk": 10.0},
         "custom_key": "keepB"},
        {"item_id": "potion", "name": "药", "count": 3, "uid": "preset-uid"},
    ]
    equip = {"weapon": {"item_id": "sword", "name": "甲", "slot_level": 3,
                        "gems": ["ruby"], "unknown_keep": "G"}}
    before = json.loads(json.dumps(inv))
    out_inv, out_equip, changed = backfill_instance_uids(inv, equip)
    assert changed == 3  # 甲、乙两行 + weapon 槽回指（preset 行不补）
    assert out_inv[0]["uid"] and out_inv[1]["uid"]
    assert out_inv[0]["uid"] != out_inv[1]["uid"]
    assert out_inv[2]["uid"] == "preset-uid"          # 已有 uid 不动
    # 槽回指首个未消费的同 item_id 行（甲），对齐既有「首匹配」语义
    assert out_equip["weapon"]["uid"] == out_inv[0]["uid"]
    # 无损：未知键/数值/镶嵌原样
    assert out_equip["weapon"]["unknown_keep"] == "G"
    assert out_equip["weapon"]["gems"] == ["ruby"]
    assert out_equip["weapon"]["slot_level"] == 3
    assert out_inv[0]["custom_key"] == "keepA" and out_inv[1]["custom_key"] == "keepB"
    assert out_inv[0]["stats_bonus"] == before[0]["stats_bonus"]
    # 幂等：再跑一次零改动
    out_inv2, out_equip2, changed2 = backfill_instance_uids(out_inv, out_equip)
    assert changed2 == 0
    assert out_inv2 == out_inv and out_equip2 == out_equip


# ---------------------------------------------------------------------------
# 旧档 → 新档：真实文件库迁移 v2→v3
# ---------------------------------------------------------------------------
def _make_v2_old_db(path: Path) -> None:
    """原生 sqlite3 造 v2 旧档：真实 players 行（无 uid 的 inventory/equipment）。"""
    inv = [
        {"item_id": "sword", "name": "甲", "count": 1, "quality": "normal",
         "bound": False, "stack_max": 1, "slot": "weapon",
         "stats_bonus": {"atk": 1.0}, "custom_key": "keepA"},
        {"item_id": "sword", "name": "乙", "count": 1, "quality": "normal",
         "bound": False, "stack_max": 1, "slot": "weapon",
         "stats_bonus": {"atk": 10.0}, "custom_key": "keepB"},
        {"item_id": "potion", "name": "药", "count": 5, "quality": "normal",
         "bound": False, "stack_max": 99},
    ]
    equip = {"weapon": {"item_id": "sword", "name": "甲", "slot_level": 4,
                        "locked": True, "gems": ["ruby"], "unknown_keep": "G"}}
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            CREATE_TABLE_PLAYERS.strip() + ";\n" + CREATE_TABLE_META.strip() + ";"
        )
        conn.execute(
            "INSERT INTO players (player_qid, nickname, level, exp, hp, mp, currencies,"
            " inventory, equipment, content_pack_id, content_pack_version, schema_version,"
            " created_at, last_active_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("10086", "旧档玩家", 7, 1234, 88, 42, '{"gold": 999}',
             json.dumps(inv, ensure_ascii=False), json.dumps(equip, ensure_ascii=False),
             "oldpack", "1.0", 4, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
            " VALUES ('global', 2, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_migrate_v2_old_db_backfills_uid(tmp_path):
    path = tmp_path / "old_v2.db"
    _make_v2_old_db(path)
    database = Database(str(path))
    try:
        result = await migrate_database(database)
        assert result.state == "migrated"
        assert (2, 3) in result.applied_steps
        assert result.to_version == DB_SCHEMA_VERSION == 3

        row = await database.fetchone_read("SELECT * FROM players WHERE player_qid='10086'")
        inv = json.loads(row["inventory"])
        equip = json.loads(row["equipment"])
        # 旧字段无损
        assert row["nickname"] == "旧档玩家" and json.loads(row["currencies"]) == {"gold": 999}
        assert inv[0]["custom_key"] == "keepA" and inv[1]["custom_key"] == "keepB"
        assert inv[1]["stats_bonus"] == {"atk": 10.0}
        assert equip["weapon"]["unknown_keep"] == "G"
        assert equip["weapon"]["gems"] == ["ruby"] and equip["weapon"]["slot_level"] == 4
        # 全量补发 uid
        assert all(r.get("uid") for r in inv)
        assert inv[0]["uid"] != inv[1]["uid"] != inv[2]["uid"]
        # 槽 uid 回指匹配行（首匹配 甲）
        assert equip["weapon"]["uid"] == inv[0]["uid"]

        # 迁移后再读档：实例 uid 稳定（不再惰性变化）
        repo = Repository(database)
        p = await repo.load_player("10086")
        assert p is not None and all(it.uid for it in p.inventory)
        assert p.equipment["weapon"].uid == inv[0]["uid"]

        again = await migrate_database(database)
        assert again.state == "up_to_date"
    finally:
        await database.close()


# ---------------------------------------------------------------------------
# 同 id 两件实例不串（核心验收）
# ---------------------------------------------------------------------------
def test_same_id_two_instances_do_not_cross_after_reload():
    """两件同 item_id、异词条实例：槽 uid 指 A → 聚合 A 词条；空 uid 旧机制取首件（B）。"""
    eng = EquipmentEngine()
    a = _item(atk=10.0)
    b = _item(atk=1.0)
    # inventory 顺序 = [B, A]：旧「item_id 首匹配」会命中 B（错），uid 精确命中 A（对）
    equip_a = {"weapon": EquipmentSlot(item_id="sword", name="剑甲", uid=a.uid)}
    # 模拟重登/读档：无 _worn_rows 进程态引用
    player = _player([b, a], equip_a)
    snap = eng.aggregate_bonus(player)
    assert snap["flat"].get("atk") == 10.0, "槽 uid 应精确取到 A 的词条"

    # 对照（修复前机制）：槽无 uid + 无进程态引用 → item_id 首匹配取到 B
    legacy = _player([b, a], {"weapon": EquipmentSlot(item_id="sword", name="剑", uid="")})
    snap_legacy = eng.aggregate_bonus(legacy)
    assert snap_legacy["flat"].get("atk") == 1.0, "旧机制取首件（串到 B）——本批修复对象"

    # 换穿另一件：槽身份随 uid 切换 → 聚合切到 B
    res = eng.equip(player, b, "weapon")
    assert res["ok"] is True
    assert player["equipment"]["weapon"].uid == b.uid
    snap2 = eng.aggregate_bonus(player)
    assert snap2["flat"].get("atk") == 1.0

    # 再穿回 A：仍精确
    res2 = eng.equip(player, a, "weapon")
    assert res2["ok"] is True
    assert player["equipment"]["weapon"].uid == a.uid
    assert eng.aggregate_bonus(player)["flat"].get("atk") == 10.0


def test_unequip_returns_exact_instance_uid():
    """卸下按槽 uid 精确回查：uid 保留在回包行（身份连续），另一件不受影响。"""
    eng = EquipmentEngine()
    a = _item(atk=10.0, enhance_level=5)
    b = _item(atk=1.0)
    player = _player([b, a], {"weapon": EquipmentSlot(
        item_id="sword", name="剑甲", slot_level=5, uid=a.uid)})
    res = eng.unequip(player, "weapon")
    assert res["ok"] is True
    assert "weapon" not in player["equipment"]
    assert [r.uid for r in player["inventory"]] == [b.uid, a.uid]


# ---------------------------------------------------------------------------
# 背包 uid 精确定位
# ---------------------------------------------------------------------------
def test_inventory_remove_and_find_by_uid():
    inv = InventoryEngine()
    a = _item(atk=10.0)
    b = _item(atk=1.0)
    p = {"inventory": [b, a]}
    assert inv.find_by_uid(p, a.uid) is a
    r = inv.remove_item(p, "sword", 1, uid=a.uid)
    assert r["ok"] is True and r.get("uid") == a.uid
    assert inv.find_by_uid(p, a.uid) is None
    assert inv.find_by_uid(p, b.uid) is b
    # uid 与 item_id 不一致 → 拒绝，不误扣
    r2 = inv.remove_item(p, "potion", 1, uid=b.uid)
    assert r2["ok"] is False and r2["reason"] == "not_enough"
    assert inv.find_by_uid(p, b.uid) is b


def test_remove_by_uid_keeps_structurally_equal_twin():
    """结构完全等价的两件（仅 uid 不同）按 uid 删 → 不得误删首件（同一性定位）。"""
    inv = InventoryEngine()
    a = ItemInstance(item_id="x", name="x", count=1, quality="normal",
                     bound=False, stack_max=1)
    b = ItemInstance(item_id="x", name="x", count=1, quality="normal",
                     bound=False, stack_max=1)
    assert a == b and a.uid != b.uid
    p = {"inventory": [a, b]}
    r = inv.remove_item(p, "x", 1, uid=b.uid)
    assert r["ok"] is True
    assert inv.find_by_uid(p, b.uid) is None
    assert inv.find_by_uid(p, a.uid) is a


def test_inventory_add_multi_instance_assigns_distinct_uid():
    inv = InventoryEngine()
    p: dict = {}
    src = _item(atk=2.0)
    res = inv.add_item(p, src, count=3)
    assert res["ok"] is True and res["added"] == 3
    uids = [r.uid for r in p["inventory"]]
    assert len(uids) == 3 and len(set(uids)) == 3 and all(uids)
