"""M2 战斗世界边界（C2 路 · 细化_1g4）单元测试：固化 /tmp/smoke_battle_boundary.py 的 24 断言。

依据：细化_1g4_战斗世界边界.md（LOST-01/02/03/04/06 丢失判定链 / HR-01/03/04 脱战回血 /
DEATH-01/03/04/05/06 死亡结算 / RACE-02 先到先得锁 / TIME-01 超时键 / TIME-05 僵尸回收 /
F-06 复活点 BFS）＋ docs/m2_shared_contract.md §七（1g4 世界边界：逻辑层+接口预留）。

原 /tmp/smoke_battle_boundary.py 已全绿（exit 0, SMOKE PASS: 24 assertions），此处按 pytest
惯例固化：断言逻辑原样保留不改语义。分组：
  decide_lost 丢失判定链（目标在场/被击杀挂起/刷新等待/刷新成功/无刷新行/时段结束/玩家退出）
  脱战回血（野图失败回满 / 副本 BOSS 豁免 J-01 / 木桩豁免 HR-04 / 击杀走刷新 / 解锁回血）
  复活点（配置优先 respawn_points > BFS 最近安全区 > 默认新手村）
  先到先得锁（无锁获得 / 有锁拒绝）
  死亡结算（货币 10% 扣除 / 经验 percent=5 百分比语义 / 绑定物品免疫掉落）
  超时键不识别（battle_timeout/turn_timeout 拒绝；正常配置无超时键）
  30 天僵尸回收（30 天回收 / 29 天不回收）

确定性：settle_item_drops 注入 seeded_rng fixture（D6 SED-4 迁移①，可复现，铁律 8）；其余纯规则。
"""
from __future__ import annotations

from qbot_rpg.data.item import ItemInstance
from qbot_rpg.world.battle_boundary import (
    LOST_ENTER_PENDING,
    LOST_EXIT_BY_PLAYER,
    LOST_EXIT_NO_RESPAWN,
    LOST_EXIT_PERIOD_END,
    LOST_RESOLVE_NORMAL,
    LOST_RESPAWNED,
    LOST_WAIT_REFRESH,
    CurrencyDrop,
    HEAL_SOURCE_BATTLE_FAIL,
    HEAL_SOURCE_KILL,
    HEAL_SOURCE_LEAVE_MAP,
    HEAL_SOURCE_UNLOCK,
    WildLock,
    assert_no_battle_timeout,
    decide_heal_and_unlock,
    decide_lost,
    find_nearest_respawn_point,
    is_heal_exempt,
    settle_currency_drops,
    settle_exp_drop,
    settle_item_drops,
    should_zombie_recycle,
    try_acquire_lock,
)


# ================================================================== 1. decide_lost 丢失判定链（LOST-02/03/04/06）

def test_decide_lost_chain():
    assert decide_lost(target_present=True, has_pending=False, spawn_row_exists=True,
                       can_respawn=True, refreshed=False) == LOST_RESOLVE_NORMAL, \
        "目标在场→正常结算"
    assert decide_lost(target_present=False, has_pending=False, spawn_row_exists=True,
                       can_respawn=True, refreshed=False) == LOST_ENTER_PENDING, \
        "目标被击杀→丢失挂起"
    assert decide_lost(target_present=False, has_pending=True, spawn_row_exists=True,
                       can_respawn=True, refreshed=False) == LOST_WAIT_REFRESH, \
        "挂起中未到刷新→继续等"
    assert decide_lost(target_present=False, has_pending=True, spawn_row_exists=True,
                       can_respawn=True, refreshed=True) == LOST_RESPAWNED, \
        "刷新成功→战斗继续"
    assert decide_lost(target_present=False, has_pending=True, spawn_row_exists=False,
                       can_respawn=False, refreshed=False) == LOST_EXIT_NO_RESPAWN, \
        "无刷新行→按退出"
    assert decide_lost(target_present=False, has_pending=False, spawn_row_exists=True,
                       can_respawn=True, refreshed=False, period_ended=True) == \
        LOST_EXIT_PERIOD_END, "时段结束→按退出"
    assert decide_lost(target_present=False, has_pending=True, spawn_row_exists=True,
                       can_respawn=True, refreshed=False, player_exited=True) == \
        LOST_EXIT_BY_PLAYER, "玩家主动退出→按退出"


# ================================================================== 2. 脱战回血（HR-01/03/04）

def test_heal_and_unlock():
    assert decide_heal_and_unlock(
        HEAL_SOURCE_BATTLE_FAIL, is_dungeon_boss=False, is_dummy=False).heal, \
        "野图战斗失败→回满+解锁"
    assert not decide_heal_and_unlock(
        HEAL_SOURCE_BATTLE_FAIL, is_dungeon_boss=True, is_dummy=False).heal, \
        "副本 BOSS 不恢复（J-01）"
    assert not decide_heal_and_unlock(
        HEAL_SOURCE_LEAVE_MAP, is_dungeon_boss=False, is_dummy=True).heal, \
        "木桩豁免（HR-04）"
    assert decide_heal_and_unlock(
        HEAL_SOURCE_KILL, is_dungeon_boss=False, is_dummy=False).heal is False, \
        "击杀走刷新非回血"
    assert is_heal_exempt(HEAL_SOURCE_UNLOCK, is_dungeon_boss=False, is_dummy=False) is False, \
        "解除锁定→回血"


# ================================================================== 3. 复活点（DEATH-07 / F-06）

def test_find_nearest_respawn_point():
    # 配置优先：volcano 配了 respawn_point → 直接用
    adj = {"volcano": ["cave"], "cave": ["volcano", "village"], "village": ["cave"]}
    assert find_nearest_respawn_point("volcano", adjacency=adj,
                                      respawn_points={"volcano": "newbie_village"},
                                      safe_zones=["village"],
                                      default="newbie_village") == "newbie_village", \
        "复活点=配置优先"
    # 无配置 → BFS 最近安全区（volcano→cave→village）
    assert find_nearest_respawn_point("volcano", adjacency=adj,
                                      respawn_points={}, safe_zones=["village"],
                                      default="newbie_village") == "village", \
        "复活点=BFS 最近安全区"
    assert find_nearest_respawn_point("volcano", adjacency={"volcano": []},
                                      respawn_points={}, safe_zones=["village"],
                                      default="newbie_village") == "newbie_village", \
        "无连通→回默认新手村"


# ================================================================== 4. 先到先得锁（RACE-02）

def test_try_acquire_lock():
    l1 = try_acquire_lock(None, "10001", 1724000000, "sess:10001")
    assert l1.acquired and l1.lock.holder_qid == "10001", "无锁→获得"
    l2 = try_acquire_lock(WildLock(holder_qid="10001", since=1724000000,
                                   battle_ref="sess:10001"),
                          "10002", 1724000001, "sess:10002")
    assert not l2.acquired, "有锁→拒绝"


# ================================================================== 5. 死亡结算（DEATH-01/03/04/05/06）

def test_settle_death_drops(seeded_rng):
    cur, lost = settle_currency_drops({"金币": 1000, "钻石": 50}, [CurrencyDrop("金币", 0.1)])
    assert lost["金币"] == 100 and cur["金币"] == 900, lost
    exp_left, exp_lost = settle_exp_drop(100, 5, True)
    assert exp_lost == 5 and exp_left == 95, "经验 5% 扣除（percent=百分比）"
    # 绑定免疫（DEATH-06）：随机掉 1 件但绑定物品不被选
    items = [{"item_id": "a", "name": "普通", "count": 1, "quality": "n", "bound": False,
              "stack_max": 99},
             {"item_id": "b", "name": "绑定", "count": 1, "quality": "n", "bound": True,
              "stack_max": 99}]
    ii = [ItemInstance(**dict(x)) for x in items]
    kept, dropped = settle_item_drops(tuple(ii), 1, True, rng=seeded_rng())
    assert len(dropped) == 1 and dropped[0].item_id == "a", \
        "绑定物品免疫掉落"


# ================================================================== 6. 超时键不识别（LOST-01/TIME-01）

def test_assert_no_battle_timeout():
    keys = assert_no_battle_timeout({"battle_timeout": 300, "turn_timeout": 30})
    assert "battle_timeout" in keys and "turn_timeout" in keys, "超时键被识别并拒绝"
    assert assert_no_battle_timeout({"season_days": 7}) == (), "正常配置无超时键"


# ================================================================== 7. 30 天僵尸回收（TIME-05）

def test_should_zombie_recycle():
    assert should_zombie_recycle("2026-01-01T00:00:00", "2026-02-01T00:00:00", 30), \
        "30 天无操作→回收"
    assert not should_zombie_recycle("2026-01-20T00:00:00", "2026-02-01T00:00:00", 30), \
        "29 天→不回收"