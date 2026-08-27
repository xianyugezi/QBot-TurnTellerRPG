"""购买结算入 SQLite 事务 + 双扣防护两路径并发验收（M6 批2·路B · tests/unit/test_shop_double_pay.py）。

依据：docs/细化/细化_M6_幂等事务三件套.md（D2）§二（SEG-1~9 + TC-SEG-01~05 + §2.5 双扣两路径表 +
§2.4 边界异常）+ §四（承接【批5B】P0-2 并发读-改-写竞态 / P1-1 双扣两路径载体）；
docs/细化/细化_M6_接线闭环总纲.md §七 ADR-06（购买并发防护 = repo.tx() BEGIN IMMEDIATE + 单写队列串行，
不依赖 world 锁）/ ADR-12 ②。

集成口径：直接驱动 **真实引擎** core/shop.py shop_buy + **真实存储** Repository(:memory:) +
新事务包裹 qbot_rpg/commands/shop_tx.py buy_in_tx；asyncio.gather 同 player 共享同一 Repository，
两条购买各走 repo.tx()（BEGIN IMMEDIATE 单写队列）排队 → 严格串行 → 后到事务重读前事务提交后的
最新状态（SEG-2/SEG-6）——这是双扣两路径（货币路径/限购路径，§2.5）的验收载体。

双扣两路径断言（§2.5 表）：
  - 货币路径（TC-SEG-02）：并发两条 /购买（同 player、不同 message_id）→ currencies 恰扣一份总额
  - 限购路径（TC-SEG-03）：并发两条 /购买（同 player、不同 message_id）→ personal_buys 计数恰 +1

零 NoneBot、纯 asyncio、SQLite 一律 :memory:（细化_5d §3.2）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from qbot_rpg.commands.shop_tx import buy_in_open_tx, buy_in_tx
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
    "dragon_scale": {"id": "dragon_scale", "name": "龙鳞", "price": 100},
}

SHOPS = {
    "grocery": {
        "id": "grocery", "name": "杂货铺", "type": "normal", "icon": "",
        "currency": "coins", "desc": "新手村杂货铺", "refresh": {"mode": "none"},
        "items": [
            {"item": "potion", "price": 250},                            # 无限库存、无限购
            {"item": "heal", "price": 250, "limit": 1, "period": "day"},  # 个人限购 1（D-04）
            {"item": "antidote", "price": 100, "stock": 1},               # 全服库存 1（D-03）
        ],
    },
    "mixed_shop": {
        "id": "mixed_shop", "name": "混合支付店", "type": "normal", "icon": "",
        "currency": "coins", "desc": "", "refresh": {"mode": "none"},
        "items": [{"item": "dragon_scale", "price": {"coins": 50, "gems": 5}}],  # 混合支付（D-02）
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
        "reputation": 1,  # 声望等级（_player_rep_level：rep int → 等级）
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


# ---------------------------------------------------------------------------
# 夹具与助手
# ---------------------------------------------------------------------------

@pytest.fixture
async def repo():
    db = Database(":memory:")
    r = Repository(db)
    yield r
    await r.close()


async def _buy(repo, qid, message_id, *, shop_id="grocery", target="疗伤药", qty=1,
               world_ctx=None, group_id="g1"):
    """D2 §2.5 并发用例骨架：调用方开 tx → buy_in_open_tx（handler 形态）→ ok 才写幂等键。

    收口对齐路A processing.py `_process_one`（事务内 idem_exists 权威判定 + handler(tx) +
    ok=True 才 write_idem_key）——本助手即路A 处理器装配形态的等价物。
    """
    world_ctx = world_ctx if world_ctx is not None else make_world_ctx()
    key = IdemKey(message_id=message_id, group_id=group_id, player_qid=qid, command="/购买")
    async with repo.tx() as tx:                          # BEGIN IMMEDIATE 排队（SEG-1/SEG-2）
        if await tx.idem_exists(key):                    # 事务内幂等权威判定（IDEM-3/4）
            return {"ok": True, "idempotent": True,
                    "message": "✅ 已结算（重复指令，未重复扣款）",
                    "applied": False, "committed": False}
        res = await buy_in_open_tx(tx, player_qid=qid, shop_id=shop_id, target=target,
                                   qty=qty, world_ctx=world_ctx)
        if res.get("ok"):
            await tx.write_idem_key(key)                 # 与业务写同事务（SEG-5）
        return res
    # 出 with = COMMIT


async def _db_player(repo, qid):
    """读库真相（绕过 60s 读缓存）：结算断言一律以库内为准。玩家缺失 → 测试失败（非 None 返回）。"""
    row = await repo.db.fetchone_read("SELECT * FROM players WHERE player_qid=?", (qid,))
    if row is None:
        raise AssertionError(f"玩家 {qid} 不在库中")
    return row_to_player(row)


async def _idem_rows(repo):
    rows = await repo.db.fetchall_read("SELECT * FROM idempotency_keys")
    return list(rows)


async def _world_stock_db(repo):
    row = await repo.db.fetchone_read(
        "SELECT value_json, version FROM world_state WHERE key='world_stock'")
    if row is None:
        return {}, 0
    return json.loads(row["value_json"]), int(row["version"])


async def _seed_world_stock(repo, flat: dict) -> None:
    """预置 world_stock 行（version=1，扁平 {f"{shop_id}:{item_id}": int}）。"""
    async with repo.tx() as tx:
        await tx.execute(
            "INSERT INTO world_state (key, value_json, version, updated_at) VALUES (?,?,?,?)",
            ("world_stock", json.dumps(flat, ensure_ascii=False), 1, "2026-08-26T00:00:00Z"))


# ---------------------------------------------------------------------------
# TC-SEG-01：购买单事务原子性（入包 hook 返回 False → 整单回滚，无中间态）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_seg_01_atomic_rollback(repo):
    """入包通道失败 → 货币/库存/限购/幂等键全部恢复操作前状态（SEG-1 / 2b3 TC-22）。"""
    await repo.save_player(make_player("u1", coins=1000))
    world = make_world_ctx(add_item=lambda item_id, count, bound: False)  # 注入入包失败
    res = await _buy(repo, "u1", "m1", shop_id="grocery", target="解毒草", qty=1, world_ctx=world)
    assert res["ok"] is False
    assert res["reason"] == "item_add_failed"  # shop_buy 内存快照-回滚（SEG-4）后返回
    # 整单回滚断言：货币/库存/限购/幂等键全部回到操作前状态
    p = await _db_player(repo, "u1")
    assert p.currencies == {"coins": 1000, "gems": 5}   # 货币未扣
    assert p.inventory == ()                            # 未入包
    assert "personal_buys" not in p.persistent_state    # 未落限购节点
    stock, _ = await _world_stock_db(repo)
    assert stock == {}                                  # 库存未扣（world_stock 行未产生）
    assert len(await _idem_rows(repo)) == 0             # 无孤儿幂等键（IDEM-6）


# ---------------------------------------------------------------------------
# TC-SEG-02 / TC-SEG-03：并发双购买——货币路径 / 限购路径（§2.5 双扣两路径表）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_seg_02_concurrent_currency_deduct_once(repo):
    """货币路径：并发双购买（同 player、不同 message_id）→ currencies 恰扣一份总额（SEG-6）。"""
    await repo.save_player(make_player("u1", coins=1000))
    world = make_world_ctx()
    r1, r2 = await asyncio.gather(
        _buy(repo, "u1", "m1", target="疗伤药", qty=1, world_ctx=world),
        _buy(repo, "u1", "m2", target="疗伤药", qty=1, world_ctx=world),
    )
    ok = [r for r in (r1, r2) if r["ok"]]
    fail = [r for r in (r1, r2) if not r["ok"]]
    assert len(ok) == 1 and len(fail) == 1            # 恰一路成功
    assert fail[0]["reason"] == "limit"               # 另一路事务内重读限购 → 校验链③（SEG-2/SEG-3）
    p = await _db_player(repo, "u1")
    assert p.currencies["coins"] == 750               # 货币恰扣一份总额：-250 而非 -500（SEG-6）
    assert p.currencies["gems"] == 5                  # 他币不动
    assert len(await _idem_rows(repo)) == 1           # 仅成功一路落幂等键（SEG-5）


@pytest.mark.asyncio
async def test_tc_seg_03_concurrent_limit_only_plus_one(repo):
    """限购路径：并发双购买 → personal_buys 计数恰 +1（不 +2）（SEG-7 / D-04）。"""
    await repo.save_player(make_player("u1", coins=1000))
    world = make_world_ctx()
    r1, r2 = await asyncio.gather(
        _buy(repo, "u1", "m1", target="疗伤药", qty=1, world_ctx=world),
        _buy(repo, "u1", "m2", target="疗伤药", qty=1, world_ctx=world),
    )
    assert sum(1 for r in (r1, r2) if r["ok"]) == 1
    p = await _db_player(repo, "u1")
    pb = p.persistent_state["personal_buys"]
    assert pb["grocery"]["heal"]["count"] == 1        # 限购计数恰 +1（不 +2）
    assert pb["grocery"]["heal"]["key"] == "2026-08-26"


# ---------------------------------------------------------------------------
# TC-SEG-04：限购满并发拦截（两路均在事务内重读限购 → 均被校验链③拒绝，计数不变）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_seg_04_limit_full_concurrent_block(repo):
    pb = {"grocery": {"heal": {"count": 1, "key": "2026-08-26"}}}
    await repo.save_player(make_player("u1", coins=1000, personal_buys=pb))
    world = make_world_ctx()
    r1, r2 = await asyncio.gather(
        _buy(repo, "u1", "m1", target="疗伤药", qty=1, world_ctx=world),
        _buy(repo, "u1", "m2", target="疗伤药", qty=1, world_ctx=world),
    )
    assert all(not r["ok"] for r in (r1, r2))
    assert all(r["reason"] == "limit" for r in (r1, r2))   # 两路均校验链③拒绝
    p = await _db_player(repo, "u1")
    assert p.persistent_state["personal_buys"]["grocery"]["heal"]["count"] == 1  # 计数不变
    assert p.currencies["coins"] == 1000                  # 货币未扣
    assert len(await _idem_rows(repo)) == 0               # 拦截不落键


# ---------------------------------------------------------------------------
# TC-SEG-05：库存并发兜底（global 库存剩 1 → 仅 1 路成功，另一路「已售罄」，不扣成负库存）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_seg_05_stock_concurrent_fallback(repo):
    await repo.save_player(make_player("u1", coins=1000))
    await _seed_world_stock(repo, {"grocery:antidote": 1})  # 全服库存剩 1（world_stock）
    world = make_world_ctx()
    r1, r2 = await asyncio.gather(
        _buy(repo, "u1", "m1", target="解毒草", qty=1, world_ctx=world),
        _buy(repo, "u1", "m2", target="解毒草", qty=1, world_ctx=world),
    )
    ok = [r for r in (r1, r2) if r["ok"]]
    fail = [r for r in (r1, r2) if not r["ok"]]
    assert len(ok) == 1 and len(fail) == 1
    assert fail[0]["reason"] == "stock"                   # 另一路「已售罄」（校验链④）
    stock, _ = await _world_stock_db(repo)
    assert stock == {"grocery:antidote": 0}               # 不扣成负库存（D-03 条件式扣减）
    p = await _db_player(repo, "u1")
    assert sum(i.count for i in p.inventory if i.item_id == "antidote") == 1  # 恰入 1 件
    assert p.currencies["coins"] == 900                   # 恰扣一份 100


# ---------------------------------------------------------------------------
# SEG-5：幂等重发不双扣（独立入口 buy_in_tx(repo) 自开事务 + 事务内二次判定 + 同事务写键）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seg_idempotent_replay_no_double_deduct(repo):
    """独立入口 buy_in_tx(repo)：同 message_id 重发 → 事务内幂等判定命中 → 不重复扣款（IDEM-5/SEG-5）。"""
    await repo.save_player(make_player("u1", coins=1000))
    world = make_world_ctx()
    key = IdemKey(message_id="m1", group_id="g1", player_qid="u1", command="/购买")
    r1 = await buy_in_tx(repo, player_qid="u1", shop_id="grocery", target="药水", qty=1,
                         idem_key=key, world_ctx=world)
    assert r1["ok"] is True and r1["committed"] is True and r1["idem_key_written"] is True
    r2 = await buy_in_tx(repo, player_qid="u1", shop_id="grocery", target="药水", qty=1,
                         idem_key=key, world_ctx=world)  # 同 message_id 重发
    assert r2["ok"] is True and r2["idempotent"] is True and r2["applied"] is False
    assert r2["committed"] is False
    p = await _db_player(repo, "u1")
    assert p.currencies["coins"] == 750      # 只扣一次（不重复扣款，IDEM-5/SEG-5）
    assert len(await _idem_rows(repo)) == 1


@pytest.mark.asyncio
async def test_buy_in_tx_standalone_commits(repo):
    """独立入口 buy_in_tx(repo)：单买成功 → 出 with = COMMIT（SEG-1），玩家/库存/幂等键全落。"""
    await repo.save_player(make_player("u1", coins=1000))
    world = make_world_ctx()
    key = IdemKey(message_id="m9", group_id="g1", player_qid="u1", command="/购买")
    res = await buy_in_tx(repo, player_qid="u1", shop_id="grocery", target="解毒草", qty=1,
                          idem_key=key, world_ctx=world)  # 解毒草：全服库存 1
    assert res["ok"] is True and res["committed"] is True and res["idem_key_written"] is True
    p = await _db_player(repo, "u1")
    assert p.currencies["coins"] == 900
    assert sum(i.count for i in p.inventory if i.item_id == "antidote") == 1
    stock, _ = await _world_stock_db(repo)
    assert stock == {"grocery:antidote": 0}   # 库存 CAS 同事务落盘
    assert len(await _idem_rows(repo)) == 1


# ---------------------------------------------------------------------------
# D2 §2.4 边界异常补充（校验链优先级 / 提示不拦截截断 / 混合支付整单拒绝 / 事务内二次读一致性）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seg_boundary_limit_stock_funds_priority(repo):
    """限购满 + 库存 0 + 货币不足同时成立 → 校验链③限购先拦（D-01 顺序即提示优先级 / 2b3 TC-39）。"""
    pb = {"grocery": {"heal": {"count": 1, "key": "2026-08-26"}}}
    await repo.save_player(make_player("u1", coins=100, personal_buys=pb))  # 100 < 250 货币不足
    await _seed_world_stock(repo, {"grocery:heal": 0})                       # 库存 0
    world = make_world_ctx()
    res = await _buy(repo, "u1", "m1", target="疗伤药", qty=1, world_ctx=world)
    assert res["ok"] is False and res["reason"] == "limit"   # ③先拦，非 stock/funds


@pytest.mark.asyncio
async def test_seg_boundary_truncate_over_cap(repo):
    """数量超过上限（默认 99）→ ⑥「提示不拦截」先截断执行量再校验（D-05/TC-03）。"""
    await repo.save_player(make_player("u1", coins=30000))
    world = make_world_ctx()
    res = await _buy(repo, "u1", "m1", target="药水", qty=150, world_ctx=world)
    assert res["ok"] is True and res["truncated"] is True
    assert res["bought"]["count"] == 99                    # 截断到 99 执行
    assert res["paid"] == {"coins": 99 * 250}
    p = await _db_player(repo, "u1")
    assert p.currencies["coins"] == 30000 - 99 * 250       # 按截断后数量扣款


@pytest.mark.asyncio
async def test_seg_boundary_mixed_payment_whole_reject(repo):
    """混合支付两币任一不足 → 整单拒绝、不部分扣款（D-02）。"""
    await repo.save_player(make_player("u1", coins=100, gems=4))  # 宝石差 1（需 5）
    world = make_world_ctx()
    res = await _buy(repo, "u1", "m1", shop_id="mixed_shop", target="龙鳞", qty=1, world_ctx=world)
    assert res["ok"] is False and res["reason"] == "funds"
    p = await _db_player(repo, "u1")
    assert p.currencies == {"coins": 100, "gems": 4}       # 金币不动、宝石不动（无部分扣款）
    assert len(await _idem_rows(repo)) == 0


@pytest.mark.asyncio
async def test_seg_in_tx_reread_beats_stale_cache(repo):
    """事务内二次读 vs 事务外预读一致性（D2 §2.4 末条）：结算读数走事务内 fetchone，不取陈旧缓存。

    模拟装配层错误地把 load_player 60s 缓存的陈旧余额当结算读：另一写路径直接改库
    （绕过缓存失效）后，buy_in_tx 若用陈旧 ctx 会错误放行；正确实现须事务内重读 → ⑤货币拦截。
    """
    await repo.save_player(make_player("u1", coins=1000))
    await repo.load_player("u1")  # 填充 60s 读缓存（coins=1000）
    async with repo.tx() as tx:   # 另一写路径直接 UPDATE 改库（不失效缓存 → 缓存变陈旧）
        await tx.execute("UPDATE players SET currencies=? WHERE player_qid=?",
                         (json.dumps({"coins": 100, "gems": 5}, ensure_ascii=False), "u1"))
    stale = await repo.load_player("u1")
    assert stale is not None and stale.currencies["coins"] == 1000  # 前提：缓存确已陈旧
    world = make_world_ctx()
    res = await _buy(repo, "u1", "m1", target="药水", qty=1, world_ctx=world)  # 250 > 100
    assert res["ok"] is False and res["reason"] == "funds"   # 事务内重读真实余额 → 拦截
    p = await _db_player(repo, "u1")
    assert p.currencies["coins"] == 100
