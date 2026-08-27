"""故障注入脚本⑤：并发双购买 → 只扣一次（M6 批5·路C · tests/fault/fault_inject_doublepay.py）。

依据：
  - docs/细化/细化_M6_故障注入.md（D5）§六（FLT-25~29 + TC-FLT-14~16 + §6.1 两路径表）
  - docs/细化/细化_M6_幂等事务三件套.md（D2）§二（SEG-1~9 + TC-SEG-02/03 + §2.5 双扣两路径表）
  - docs/细化/细化_M6_接线闭环总纲.md §七 ADR-06（购买并发防护 = repo.tx() BEGIN IMMEDIATE +
    单写队列串行，不依赖 world 锁）/ ADR-12 ②（购买结算整体搬入 repo.tx()）
  - 开发规则文档.md §4.5 L323（双扣防护「并发两条购买指令 → SQLite 事务下只扣一次（限购/货币）」）

故障点 = 【规则】L323 双扣防护：并发两条 /购买（同 player、不同 message_id）在 SQLite 事务
（repo.tx() = BEGIN IMMEDIATE + 单写连接队列）下严格串行 → 后到事务重读前事务提交后的状态 →
货币恰扣一份 / 限购恰 +1（无「读-改-写」竞态：货币丢失更新/限购漏加，D2 §2.1）。

工程决策（对齐批5·路C 任务书）：
  - 复用 qbot_rpg/commands/shop_tx.py **buy_in_tx 真实实现**（不 mock 引擎/存储）；asyncio.gather
    两路并发 /购买共享同一 Repository，各自走 repo.tx() 排队（D2 §2.5 并发用例骨架，SEG-2）。
  - 货币路径断言（FLT-26 / TC-FLT-14）：currencies 对应币恰扣一份总额（无丢失更新）。
  - 限购路径断言（FLT-27 / TC-FLT-15）：personal_buys[shop][item]["count"] 恰 +1（不 +2）。
  - 不依赖 wild_lock（FLT-28 / ADR-06）。
  - 恢复路径（FLT-29）：用例结束 finally 关闭独立 :memory: 库，无残留半结算状态。

注入隔离（FLT-04 / 细化_5d L205-208）：每用例独立 fixture 起独立 :memory: 库互不串扰；
零 NoneBot、纯 asyncio。双扣归属口径（D5 §10.3 / ADR-D5-03）：M6 故障注入载体为准。

【工程补白】个人限购持久化键 = player.persistent_state["personal_buys"]（对齐 D2 §2.2 与
shop_tx.py 工程补白 2）；world_stock 由事务内读（SEG-2），夹具 refresh.mode=none 避开刷新副作用。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from qbot_rpg.commands.shop_tx import buy_in_tx
from qbot_rpg.data.player import Player
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import IdemKey, Repository, row_to_player

# ---------------------------------------------------------------------------
# 内容包夹具（对齐 core/shop.py 工程补白 2 的 ctx 契约；refresh.mode=none 避开刷新副作用）
# ---------------------------------------------------------------------------

ITEMS = {
    "potion": {"id": "potion", "name": "药水", "price": 250},
    "heal": {"id": "heal", "name": "疗伤药", "price": 250},
    "antidote": {"id": "antidote", "name": "解毒草", "price": 100},
}

SHOPS = {
    "grocery": {
        "id": "grocery", "name": "杂货铺", "type": "normal", "icon": "",
        "currency": "coins", "desc": "新手村杂货铺", "refresh": {"mode": "none"},
        "items": [
            {"item": "potion", "price": 250},                            # 无限库存、无限购（纯货币路径）
            {"item": "heal", "price": 250, "limit": 1, "period": "day"},  # 个人限购 1（D-04）
        ],
    },
}

SETTINGS = {
    "currencies": [
        {"id": "coins", "name": "金币"},
        {"id": "gems", "name": "宝石"},
    ],
    "sell_ratio": 0.3,
}

# 2026-08-26 09:00 UTC+8（确定性：日界桶键 = 2026-08-26，个人限购计数不跨期清零）
NOW = 1787706000


def make_world_ctx(**over):
    """静态世界上下文（装配层批次6/7 注入 buy_in_tx 的部分；world_stock 由事务内读，不在此）。"""
    base = {
        "items": ITEMS,
        "shops": SHOPS,
        "settings": SETTINGS,
        "reputation": 1,
        "now": NOW,
        "world_sold_out": {},
        "last_refresh": {},
        "blackmarket_goods": {},
        "current_shop_ref": None,
    }
    base.update(over)
    return base


def make_player(qid, *, coins=1000, gems=5, personal_buys=None) -> Player:
    """玩家主档（currencies 用 coins/gems 对齐商店夹具；personal_buys 落 persistent_state）。"""
    ps: dict = {}
    if personal_buys is not None:
        ps["personal_buys"] = personal_buys
    return Player(
        qid=qid, name="阿伟", level=5, hp=100, mp=50,
        currencies={"coins": coins, "gems": gems},
        persistent_state=ps,
        created_at="2026-08-01T00:00:00Z",
        last_active_at="2026-08-18T12:00:00Z",
    )


@pytest.fixture
async def repo():
    """独立 :memory: 库（FLT-04 注入隔离：每用例独立库互不串扰）。"""
    db = Database(":memory:")
    r = Repository(db)
    yield r
    await r.close()


async def _buy_in_tx(repo, qid, message_id, *, shop_id="grocery", target, qty=1,
                     world_ctx=None, group_id="g1"):
    """FLT-25 注入点载体：单路 /购买 走 buy_in_tx 真实实现（自开 repo.tx()，SEG-1/SEG-2）。

    同 player_qid、不同 message_id 两路并发 → 各自 BEGIN IMMEDIATE 排队（单写队列严格串行），
    后到事务重读前事务提交后的余额/限购（SEG-2/SEG-6/SEG-7）。
    """
    world_ctx = world_ctx if world_ctx is not None else make_world_ctx()
    key = IdemKey(message_id=message_id, group_id=group_id, player_qid=qid, command="/购买")
    return await buy_in_tx(repo, player_qid=qid, shop_id=shop_id, target=target, qty=qty,
                           idem_key=key, world_ctx=world_ctx)


async def _db_player(repo, qid):
    """读库真相（绕过 60s 读缓存）：结算断言一律以库内为准。玩家缺失 → 测试失败。"""
    row = await repo.db.fetchone_read("SELECT * FROM players WHERE player_qid=?", (qid,))
    if row is None:
        raise AssertionError(f"玩家 {qid} 不在库中")
    return row_to_player(row)


async def _idem_rows(repo):
    rows = await repo.db.fetchall_read("SELECT * FROM idempotency_keys")
    return list(rows)


# ---------------------------------------------------------------------------
# TC-FLT-14：并发双买货币只扣一次（FLT-25/26）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_flt_14_concurrent_buy_currency_deduct_once(repo):
    """TC-FLT-14 并发双买货币只扣一次（FLT-25/26 / D2 TC-SEG-02）。

    注入点=asyncio.gather 两路并发 buy_in_tx（同 player_qid=u1、不同 message_id=m1/m2、
    共享同一 Repository，各自走 repo.tx()=BEGIN IMMEDIATE 排队串行，D2 §2.5 骨架，SEG-2）；
    断言对象=currencies 恰扣一份总额（coins 1000→750，非 500/负余额，无丢失更新，SEG-6）+
    仅成功一路落幂等键 + 另一路事务内重读限购被校验链③拦截（reason=="limit"，SEG-3）；
    恢复路径=finally 关闭独立 :memory: 库（FLT-29，无残留半结算状态）。
    """
    await repo.save_player(make_player("u1", coins=1000))  # 余额充足（D5 TC-FLT-14 前置）
    world = make_world_ctx()
    try:
        # P2-1 修复（M6 批5B dsh 审查）：gather 移入 try——协程意外抛异常时 finally
        # 恢复路径仍执行（原 gather 在 try 外，异常绕过 close）
        r1, r2 = await asyncio.gather(
            _buy_in_tx(repo, "u1", "m1", target="疗伤药", qty=1, world_ctx=world),
            _buy_in_tx(repo, "u1", "m2", target="疗伤药", qty=1, world_ctx=world),
        )
        oks = [r for r in (r1, r2) if r.get("ok")]
        fails = [r for r in (r1, r2) if not r.get("ok")]
        assert len(oks) == 1 and len(fails) == 1          # 恰一路成功（另一路被拦）
        assert fails[0]["reason"] == "limit"              # 后到事务重读限购 → 校验链③（SEG-2/SEG-3）
        p = await _db_player(repo, "u1")
        assert p.currencies["coins"] == 750              # 货币恰扣一份总额 -250，非 -500（SEG-6）
        assert p.currencies["gems"] == 5                 # 他币不动
        assert len(await _idem_rows(repo)) == 1          # 仅成功一路落幂等键（SEG-5）
    finally:
        await repo.close()                                # FLT-29 恢复路径：清理独立 :memory: 库


@pytest.mark.asyncio
async def test_tc_flt_14b_pure_currency_funds_blocked(repo):
    """FLT-26 补强：纯货币路径（无限购/无限库存商品 + 余额仅够一次）→ 并发双买。

    注入点=同 TC-FLT-14（asyncio.gather 两路 buy_in_tx 共享 repo 排队）；断言对象=货币路径
    不依赖限购制造单方失败——药水（无限购）并发双买，后到事务重读余额不足被校验链⑤ funds 拦截，
    currencies 恰扣一份总额（400→150，非 400-500 负余额，无丢失更新）+ 仅 1 路落幂等键；
    恢复路径=finally 关闭独立 :memory: 库（FLT-29）。
    """
    await repo.save_player(make_player("u1", coins=400))  # 药水 250/个，仅够买 1（P2-12 口径）
    world = make_world_ctx()
    r1, r2 = await asyncio.gather(
        _buy_in_tx(repo, "u1", "m1", target="药水", qty=1, world_ctx=world),
        _buy_in_tx(repo, "u1", "m2", target="药水", qty=1, world_ctx=world),
    )
    try:
        oks = [r for r in (r1, r2) if r.get("ok")]
        fails = [r for r in (r1, r2) if not r.get("ok")]
        assert len(oks) == 1 and len(fails) == 1
        assert fails[0]["reason"] == "funds"              # 第二次重读余额不足被拦（FLT-26）
        p = await _db_player(repo, "u1")
        assert p.currencies["coins"] == 150              # 恰扣一份总额 250（无丢失更新/负余额）
        assert len(await _idem_rows(repo)) == 1
    finally:
        await repo.close()                                # FLT-29 恢复路径


# ---------------------------------------------------------------------------
# TC-FLT-15：并发双买限购只 +1（FLT-27）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_flt_15_concurrent_buy_limit_only_plus_one(repo):
    """TC-FLT-15 并发双买限购只 +1（FLT-27 / D2 TC-SEG-03）。

    注入点=asyncio.gather 两路并发 buy_in_tx（同 player、不同 message_id、共享 repo，限购 limit=1）；
    断言对象=personal_buys[shop][item]["count"] 恰 +1（不 +2，SEG-7/D-04）+ 第二条因限购拦
    （校验链③，reason=="limit"）+ 限购桶键 = 当日（2026-08-26）；恢复路径=finally 关闭独立
    :memory: 库（FLT-29，无残留半结算状态）。
    """
    await repo.save_player(make_player("u1", coins=1000))  # 限购 limit=1（D5 TC-FLT-15 前置）
    world = make_world_ctx()
    r1, r2 = await asyncio.gather(
        _buy_in_tx(repo, "u1", "m1", target="疗伤药", qty=1, world_ctx=world),
        _buy_in_tx(repo, "u1", "m2", target="疗伤药", qty=1, world_ctx=world),
    )
    try:
        assert sum(1 for r in (r1, r2) if r.get("ok")) == 1
        p = await _db_player(repo, "u1")
        pb = p.persistent_state["personal_buys"]
        assert pb["grocery"]["heal"]["count"] == 1         # 限购计数恰 +1（不 +2，SEG-7）
        assert pb["grocery"]["heal"]["key"] == "2026-08-26"  # 当日桶键（确定性 NOW）
        fail = next(r for r in (r1, r2) if not r.get("ok"))
        assert fail["reason"] == "limit"                   # 后到事务重读限购 → 校验链③
    finally:
        await repo.close()                                # FLT-29 恢复路径
