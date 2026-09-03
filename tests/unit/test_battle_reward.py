"""战斗击杀奖励结算单测（2026-09-03 · PvE 奖励断链修复）。

依据：docs/veinborn_阶段一_进度存档_20260903.md §三.1（击杀奖励落账从未实现——
rewards/drops → exp/币/掉落 + 升级）；qbot_rpg/core/battle_reward.py 模块头
（工程补白 1-6）；5e 军规5（结算一次性：胜利才拿奖励）。

覆盖：
  - reward_entries_from_enemy：rewards 解析（exp/currencies 条目化）
  - roll_death_drops：chance 边界（100%/0%/区间）+ count 区间随机 + 非 death 不碰
  - settle_battle_rewards：Player dataclass ctx → asdict 落档、exp 升级回满 SP、
    币入 player.currencies、物品 add_item 入包、返回 (名, 数) drops
  - 幂等（tx_id+ledger 二次调用不重复入账）
  - enemy 无 rewards → 零结算不崩

测试风格对齐 tests/unit/test_levelup.py：纯 pytest、零 NoneBot、确定性 rng。
"""
from __future__ import annotations

import random
from typing import Any

from qbot_rpg.core.battle_reward import (
    reward_entries_from_enemy,
    roll_death_drops,
    settle_battle_rewards,
)
from qbot_rpg.data.player import Player, PlayerAttributes


def make_player(**over: Any):
    """构造 Player dataclass（ctx["player"] 生产形态；frozen，需 asdict 转 dict）。"""
    base: dict = dict(
        qid="10001", name="阿伟", job_id="warrior", level=1, exp=0, hp=100, mp=30,
        currencies={"coins": 10},
        inventory=(),
        equipment={},
        attributes=PlayerAttributes(
            base={"hp": 100.0, "mp": 30.0, "str": 15.0, "con": 10.0}
        ),
        persistent_state={},
    )
    base.update(over)
    return Player(**base)


def make_ctx(player, **over):
    """结算 ctx（对齐 make_context 装配键：items/add_item/currencies 就地引用）。"""
    ctx = {
        "player": player,
        "settings": {"level_cap": 45, "currencies": [{"id": "coins", "name": "金币"}]},
        "items": {
            "vein_shard": {"name": "脉矿碎晶"},
            "barrow_core": {"name": "冢核"},
            "potion": {"name": "药水"},
        },
        "add_item": None,  # 缺省（无 hook → item skip 防静默丢奖）
        "inventory": {},
    }
    ctx.update(over)
    return ctx


def _p(ctx):
    """玩家状态统一访问器（Player dataclass 属性 / dict 下标）。"""
    p = ctx["player"]
    if isinstance(p, dict):
        return p
    return {k: getattr(p, k) for k in (
        "qid", "name", "level", "exp", "hp", "mp", "currencies", "inventory",
        "attributes", "persistent_state", "job_id",
    )}


# 击杀目标（含 rewards + drops.death）
def enemy_entry(**over):
    base = {
        "id": "ridge_cub",
        "name": "脊冢幼兽",
        "rewards": {"exp": 40, "currencies": {"coins": 50}},
        "drops": {
            "battle": [{"item": "potion", "chance": 100, "count": 1}],
            "death": [{"item": "vein_shard", "chance": 100, "count": [1, 2]}],
        },
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# reward_entries_from_enemy
# ---------------------------------------------------------------------------
def test_reward_entries_from_enemy_parses_exp_and_currencies():
    """rewards {exp, currencies:{coins}} → 条目化 [{exp}, {coins}]（dispatch 兼容）。"""
    entries = reward_entries_from_enemy(enemy_entry())
    assert {"exp": 40} in entries
    assert {"coins": 50} in entries


def test_reward_entries_empty_when_no_rewards():
    """enemy 无 rewards 字段 / 空 → []（demo 包既有怪物零奖励，不崩）。"""
    assert reward_entries_from_enemy({"id": "x", "name": "无奖怪"}) == []
    assert reward_entries_from_enemy({}) == []


def test_reward_entries_skips_nonpositive():
    """exp<=0 / 币<=0 不条目化（零奖励不入账）。"""
    e = enemy_entry()
    e["rewards"] = {"exp": 0, "currencies": {"coins": -3}}
    assert reward_entries_from_enemy(e) == []


# ---------------------------------------------------------------------------
# roll_death_drops
# ---------------------------------------------------------------------------
def test_roll_death_drops_100pct_always():
    """chance=100 → 必掉；count=[1,2] 区间在界内。"""
    rng = random.Random(42)
    drops = roll_death_drops(enemy_entry(), rng)
    assert len(drops) == 1
    assert drops[0]["item"] == "vein_shard"
    assert 1 <= drops[0]["count"] <= 2


def test_roll_death_drops_zero_chance_never():
    """chance=0 → 永不掉；chance=0.01 量级 roll 极低概率（rng 注入可复现）。"""
    e = enemy_entry()
    e["drops"]["death"] = [{"item": "vein_shard", "chance": 0, "count": 1}]
    assert roll_death_drops(e, random.Random(0)) == []


def test_roll_death_drops_no_drops_key():
    """无 drops / drops 无 death → []（demo 训练木桩无掉落）。"""
    assert roll_death_drops({"id": "dummy"}, random.Random(0)) == []
    assert roll_death_drops(
        {"id": "x", "drops": {"battle": [{"item": "potion", "chance": 100}]}},
        random.Random(0),
    ) == []


# ---------------------------------------------------------------------------
# settle_battle_rewards 核心
# ---------------------------------------------------------------------------
def test_settle_exp_levels_up_and_restores():
    """击杀 40 exp：exp 入账 + 升级（1→2 需 100？40 不足 → 不升级仅 exp+=40）。"""
    player = make_player(exp=90, level=1)  # 距 2 级还差 10
    ctx = make_ctx(player)
    out = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    # exp 入账 40 → 升 1 级（100 门槛），剩 30 exp
    assert out["exp"] == 40
    p = _p(ctx)
    assert p["level"] == 2
    assert p["exp"] == 30
    assert out["leveled"] is not None
    assert out["leveled"]["level_ups"] == 1
    # 升级回满 HP/MP（上限=重算最终属性，>= 100/30）
    assert p["hp"] >= 100 and p["mp"] >= 30
    # SP 发放落 persistent_state.proficiency.warrior.sp_earned
    prof = p["persistent_state"].get("proficiency") or {}
    assert prof.get("warrior", {}).get("sp_earned", 0) >= 1


def make_add_item(ctx):
    """真实 add_item hook 行为（对齐 context._inventory_hooks：写 ctx["inventory"] 计数）。"""
    calls = []

    def add_item(item_id, count=1, bound=False, **kw):
        calls.append((item_id, count))
        inv = ctx["inventory"]
        inv[item_id] = inv.get(item_id, 0) + int(count)
        return True

    return add_item, calls


def test_settle_currencies_and_drops_into_player():
    """币入 player.currencies.coins；死亡掉落 add_item 入包；drops 返回 (名, 数)。"""
    player = make_player(currencies={"coins": 10})
    ctx = make_ctx(player)
    add_item, calls = make_add_item(ctx)
    ctx["add_item"] = add_item
    out = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    assert out["gold"] == 50
    p = _p(ctx)
    assert p["currencies"]["coins"] == 60
    # 掉落入包（100%）：vein_shard ×1-2（hook 写 ctx 计数映射）
    assert len(calls) == 1 and calls[0][0] == "vein_shard"
    # drops = [(显示名, 数)]
    assert len(out["drops"]) == 1
    assert out["drops"][0][0] == "脉矿碎晶"
    assert 1 <= out["drops"][0][1] <= 2
    # ctx 计数映射（add_item 写入；Player 形态由 runner 落档 merge 进实例列表）
    assert ctx["inventory"].get("vein_shard", 0) >= 1
    assert isinstance(ctx["player"], Player)  # Player 形态保留（replace 提交）


def test_settle_player_dict_form_merges_inventory():
    """ctx["player"] 已是 dict（指令壳 asdict 先例）→ 保留 dict 且 inventory 合并。"""
    player = make_player()
    d = {
        "qid": "10001", "name": "阿伟", "job_id": "warrior", "level": 1, "exp": 0,
        "hp": 100, "mp": 30, "currencies": {"coins": 10},
        "inventory": [], "attributes": player.attributes,
    }
    ctx = make_ctx(d)
    add_item, calls = make_add_item(ctx)
    ctx["add_item"] = add_item
    out = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    assert out["gold"] == 50
    assert ctx["player"]["currencies"]["coins"] == 60
    inv = ctx["player"]["inventory"]
    assert any(x.get("item_id") == "vein_shard" for x in inv)
    assert isinstance(ctx["player"], dict)


def test_settle_no_hook_item_skipped_not_granted():
    """add_item 缺省 None → item 走 skip(item_add_failed) 不静默丢（P1-1）；其余照发。"""
    ctx = make_ctx(make_player())  # add_item None
    out = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    reasons = [s.get("reason") for s in out["skipped"]]
    assert "item_add_failed" in reasons
    # 币照发（条目级失败不中断整批）
    assert _p(ctx)["currencies"]["coins"] == 60


def test_settle_idempotent_tx():
    """同 tx_id + ledger：二次调用幂等早退，不重复入账。"""
    player = make_player()
    ledger = set()
    ctx = make_ctx(player, tx_id="battle:10001:abc", ledger=ledger)
    out1 = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    assert out1["idempotent"] is False
    # 二次（同 ctx 已封口）
    out2 = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    assert out2["idempotent"] is True
    assert _p(ctx)["currencies"]["coins"] == 60  # 未重复加
    assert _p(ctx)["level"] == 1


def test_settle_empty_enemy_no_crash():
    """enemy_entry None / 无 rewards / 无 drops → 零结算不崩。"""
    ctx = make_ctx(make_player())
    assert settle_battle_rewards(ctx, None)["exp"] == 0
    assert settle_battle_rewards(ctx, {"id": "dummy"})["exp"] == 0


# ---------------------------------------------------------------------------
# 未注册/无 attributes 兜底
# ---------------------------------------------------------------------------
def test_settle_attributes_dict_restored_to_playerattributes():
    """attributes 为普通 dict（asdict 深转产物）→ 还原回 PlayerAttributes 并升级。"""
    ctx = make_ctx(make_player())
    # 覆盖为 asdict 形态（dict 而非 PlayerAttributes）——_player_dict 还原
    ctx["player"] = {"level": 1, "exp": 90, "currencies": {"coins": 10},
                     "attributes": {"base": {"hp": 100.0, "mp": 30.0, "str": 15.0,
                                             "con": 10.0},
                                    "bonus": {"flat": {}, "pct": {}},
                                    "temp": {"flat": {}, "pct": {}}, "cond": {}}}
    out = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    assert out["exp"] == 40                      # 还原成功 → 升级入账
    assert ctx["player"]["level"] == 2           # 90 + 40 = 130 → 升 1 级剩 30
    assert isinstance(ctx["player"]["attributes"], PlayerAttributes)


def test_settle_missing_attributes_skips_exp():
    """player 无 attributes 键 → exp skip(missing_bucket)，币/掉落照常。"""
    player = make_player()
    ctx = make_ctx(player)
    # 覆盖 attributes 缺失（生产不会出现，防御路径）
    ctx["player"] = {"level": 1, "exp": 0, "currencies": {"coins": 10}}
    out = settle_battle_rewards(ctx, enemy_entry(), rng=random.Random(1))
    assert any(s.get("reason") == "missing_bucket" for s in out["skipped"])
    assert out["exp"] == 0
    # 币照发（条目级失败不中断整批）
    assert ctx["player"]["currencies"]["coins"] == 60
