"""购买事务包裹（M6 批2·路B · qbot_rpg/commands/shop_tx.py）——购买结算整体搬入 repo.tx()（SEG 件套）+ 双扣两路径防护载体。

购买结算**整体**在 repo.tx()（BEGIN IMMEDIATE）内完成：事务内读玩家行/世界库存 → 6 步校验链 →
扣减（货币/入包/库存/限购）→ 玩家写回 + 世界库存 CAS + write_idem_key → 出 with = COMMIT；
任一步失败整单回滚（SEG-1）。本模块是双扣防护两路径（货币路径/限购路径）的独立可测载体
（TC-SEG-01~05），供装配层（批次6/7 make_context/on_command）接线；零 NoneBot、纯 asyncio。

依据：
  - docs/细化/细化_M6_幂等事务三件套.md（D2）：§二 SEG-1~9（规则表）+ §2.4 边界异常 +
    §2.5 双扣两路径表 + TC-SEG-01~05；§四 承接【批5B】P0-2（并发读-改-写竞态）/ P1-1（双扣载体）
  - docs/细化/细化_M6_接线闭环总纲.md §七 ADR-06（购买并发防护不依赖 world 锁，依赖
    repo.tx()=BEGIN IMMEDIATE + 单写队列串行）/ ADR-12 ②（购买结算整体搬入 repo.tx()）
  - qbot_rpg/core/shop.py shop_buy（L1020-1153）：内存 ctx 快照-回滚（L1114-1132）保留为
    **事务内校验层**（SEG-4），不替代 SQLite 事务；docstring L1023「调用方应包裹 SQLite 事务（存储层）」
  - 细化_4a_存储层契约.md：F3（幂等键与业务写同事务 IDEM-2）/ TX-1~6

【工程补白】（契约/定稿未定义落点，按「只建议不限制」取点定型，命名/键名可改，收口由装配层/主 agent 对齐）：
  1) 结算 ctx 构建分「玩家态」与「世界态」两路（D2 §2.4 边界异常末条）：玩家态
     （currencies/inventory/personal_buys/level/name/reputation_state）一律在**事务内重读**
     玩家行（SEG-2），绝不取 load_player 60s 缓存的陈旧读数；世界态（items/shops/settings/
     rep_levels/world_sold_out/last_refresh/blackmarket_goods + reputation/now 等）由装配层
     注入 world_ctx（批次6/7 make_context 接线）。
  2) personal_buys 持久化键 = player.persistent_state["personal_buys"]
     （qbot_rpg/data/player.py L93「非会话持久（checkin/shop/resource/time/dummy_log）」约定，
     键名与 ctx 对齐）。
  3) world_stock 持久化格式 = **扁平** {f"{shop_id}:{item_id}": int}（对齐 data/world_state.py L27
     world_stock: Dict[str, int] 与 repository._int_dict 加载约束——嵌套结构会让 _int_dict 崩溃）；
     ctx 内为**嵌套** {shop_id: {item_id: int}}（core/shop.py 工程补白 2）。本模块提供双向转换。
  4) save_world_state 自开独立事务（repository.py L470），不可在买事务内嵌套
     （connection.py _tx_owner 同任务防嵌套 L335-339）→ 库存 CAS 在本事务内联
     （SELECT version 比对 → UPDATE ... WHERE version=?，与 save_world_state 单键逻辑同构），
     与玩家写/幂等键同一 COMMIT（SEG-1）；CAS 冲突 → 抛异常强制整单回滚（不半写玩家/库存）。
  5) 本模块只持久化 D2 §2.2 点名的 players 三态（currencies/inventory/personal_buys）+ world_stock；
     world_sold_out/last_refresh/blackmarket_goods 的持久化路径归装配层/后续批（D2 未定义，
     测试用 refresh.mode=none 商店避开刷新副作用）。
  6) 校验链拦截（③限购/④库存/⑤货币等）与幂等命中均**不写幂等键**（D2 §2.5 骨架 `if res["ok"]`
     才写键）——拦截即指令已处理，重发按新处理再校验（重复拦截幂等安全）；仅买入成功落键。
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.shop import shop_buy
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player
from qbot_rpg.storage.repository import IdemKey, Repository, RepoTransaction, row_to_player

__all__ = [
    "PERSONAL_BUYS_KEY",
    "WORLD_STOCK_SEP",
    "buy_in_open_tx",
    "buy_in_tx",
    "world_stock_from_ctx",
    "world_stock_to_ctx",
]

# 【工程补白 2】personal_buys 持久化键（player.persistent_state）
PERSONAL_BUYS_KEY = "personal_buys"

# 【工程补白 3】world_stock 扁平键分隔符（持久化格式 {f"{shop_id}{SEP}{item_id}": int}）
WORLD_STOCK_SEP = ":"

_WORLD_STOCK_ROW_KEY = "world_stock"

# shop_buy 会就地改写的世界态 ctx 键（除 world_stock 外；工程补白 1/5）——深拷贝防污染 world_ctx
_MUTATED_WORLD_KEYS = ("world_sold_out", "last_refresh", "blackmarket_goods")


def _jloads(raw: Optional[str], default: Any) -> Any:
    """宽容 JSON 反序列化（对齐 repository._jloads 语义，缺失/脏值回默认）。"""
    if not raw:
        return copy.deepcopy(default)
    try:
        v = json.loads(raw)
        return v if v is not None else copy.deepcopy(default)
    except (TypeError, ValueError):
        return copy.deepcopy(default)


def world_stock_to_ctx(flat: Mapping[str, Any]) -> dict:
    """扁平 world_stock {f"{shop_id}:{item_id}": int} → ctx 嵌套 {shop_id: {item_id: int}}。

    core/shop.py 工程补白 2 要求嵌套结构；未知/畸形键跳过（SCHEMA-6 多忽略精神）。
    """
    out: dict = {}
    for key, val in flat.items():
        if not isinstance(key, str) or WORLD_STOCK_SEP not in key:
            continue
        shop_id, _, item_id = key.partition(WORLD_STOCK_SEP)
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        out.setdefault(shop_id, {})[item_id] = n
    return out


def world_stock_from_ctx(nested: Mapping[str, Any]) -> dict:
    """ctx 嵌套 world_stock {shop_id: {item_id: int}} → 扁平 {f"{shop_id}:{item_id}": int}（持久化格式）。"""
    out: dict = {}
    for shop_id, node in nested.items():
        if not isinstance(node, Mapping):
            continue
        for item_id, val in node.items():
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            out[f"{shop_id}{WORLD_STOCK_SEP}{item_id}"] = n
    return out


def _inventory_from_player(player: Player) -> dict:
    """Player.inventory（ItemInstance 元组）→ ctx 背包 {item_id: count}（同 id 叠加）。"""
    out: dict = {}
    for inst in player.inventory:
        out[inst.item_id] = int(out.get(inst.item_id, 0)) + int(inst.count)
    return out


def _personal_buys_from_player(player: Player) -> dict:
    """Player.persistent_state[PERSONAL_BUYS_KEY] → ctx 限购计数（深拷贝防串改）。"""
    raw = player.persistent_state.get(PERSONAL_BUYS_KEY, {})
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def _build_ctx(
    player: Player,
    world_ctx: Mapping[str, Any],
    world_stock_ctx: Mapping[str, Any],
    now: Optional[int],
) -> dict:
    """结算 ctx：玩家态走事务内重读（SEG-2），世界态来自 world_ctx（装配层注入）。"""
    ctx: dict = dict(world_ctx)
    for k in _MUTATED_WORLD_KEYS:  # 工程补白 5：防 shop_buy 就地改写污染装配层 world_ctx
        if k in ctx:
            ctx[k] = copy.deepcopy(ctx[k])
    ctx["level"] = player.level
    ctx["name"] = player.name
    ctx["currencies"] = dict(player.currencies)
    ctx["inventory"] = _inventory_from_player(player)
    ctx["personal_buys"] = _personal_buys_from_player(player)
    ctx["world_stock"] = dict(world_stock_ctx)  # 嵌套结构（shop.py 工程补白 2）
    ctx["reputation_state"] = dict(player.reputation_state)
    if now is not None:
        ctx["now"] = now
    return ctx


def _ctx_inventory_to_player(
    inv_ctx: Any, old: Tuple[ItemInstance, ...], items: Any
) -> Tuple[ItemInstance, ...]:
    """ctx 背包 {item_id: count} → Player.inventory（保留旧实例 quality/bound/slot/stats 等字段）。

    - count<=0 → 移除该实例；新 item_id 以 items 注册表名 + 默认字段构造（工程补白 5）。
    - 同 id 多实例：合并计数到首实例，其余保留原样（购买场景物品通常单实例，防御性处理）。
    """
    if not isinstance(inv_ctx, Mapping):
        return old
    out: list = []
    by_id: dict = {}
    for inst in old:
        by_id.setdefault(inst.item_id, []).append(inst)
    for raw_id, raw_count in inv_ctx.items():
        item_id = str(raw_id)
        try:
            n = int(raw_count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        pool = by_id.get(item_id, [])
        if pool:
            # P1-1 修复（M6 批2 审查）：ctx 背包为 {item_id: count} 扁平计数，n 已是同 id
            # 多实例的合并总量——其余实例必须移除（count 归并到首实例），否则
            # pool[1:] 原计数 + 合并总量 = 计数膨胀（静默数据损坏）。
            out.append(replace(pool[0], count=n))
            by_id[item_id] = []
        else:
            name = ""
            slot_v: Optional[str] = None
            sb: Dict[str, float] = {}
            item_cfg = items.get(item_id) if isinstance(items, Mapping) else None
            if isinstance(item_cfg, Mapping):
                name = str(item_cfg.get("name") or "")
                slot_v = str(item_cfg.get("slot") or "") or None
                # 2026-09-03 装备加成断链修复：def 数值字段 → stats_bonus（穿装聚合读它）
                for _sk in ("atk", "def", "hp", "mp", "str", "con", "agi", "foc", "spr", "lck", "spd", "mag"):
                    _v = item_cfg.get(_sk)
                    if isinstance(_v, (int, float)) and not isinstance(_v, bool) and _v:
                        sb[_sk] = float(_v)
            out.append(ItemInstance(item_id=item_id, name=name, count=n,
                                    quality="normal", bound=False, slot=slot_v,
                                    stats_bonus=sb))
    for rest in by_id.values():  # 旧背包中 ctx 未涉及的实例原样保留
        out.extend(rest)
    return tuple(out)


def _player_after_buy(player: Player, ctx: MutableMapping[str, Any], items: Any) -> Player:
    """把 shop_buy 结算后的 ctx 玩家态（currencies/inventory/personal_buys）合并回 Player。"""
    ps = dict(player.persistent_state)
    ps[PERSONAL_BUYS_KEY] = copy.deepcopy(ctx.get("personal_buys") or {})
    return replace(
        player,
        currencies=dict(ctx.get("currencies") or {}),
        inventory=_ctx_inventory_to_player(ctx.get("inventory"), player.inventory, items),
        persistent_state=ps,
    )


async def _read_world_stock_in_tx(tx: RepoTransaction) -> Tuple[dict, int]:
    """事务内读 world_stock 行（SEG-2 持写锁重读）：返回 (扁平 dict, version)；行缺失 → ({}, 0)。"""
    row = await tx.fetchone(
        "SELECT value_json, version FROM world_state WHERE key = ?", (_WORLD_STOCK_ROW_KEY,)
    )
    if row is None:
        return {}, 0
    data = _jloads(row["value_json"], {})
    return (data if isinstance(data, dict) else {}), int(row["version"] or 0)


async def _write_world_stock_in_tx(
    tx: RepoTransaction, flat: Mapping[str, int], expected_version: int, ts: str
) -> None:
    """事务内联世界库存 CAS 写回（工程补白 4：save_world_state 单键语义同构，同事务提交）。

    CAS 冲突（行缺失但期望已存在 / version 不符）→ 抛 RuntimeError → 触发整单 ROLLBACK
    （不半写玩家/库存，SEG-1 失败整单回滚）。
    """
    value = json.dumps(dict(flat), ensure_ascii=False)
    cur = await tx.fetchone(
        "SELECT version FROM world_state WHERE key = ?", (_WORLD_STOCK_ROW_KEY,)
    )
    if cur is None:
        if expected_version != 0:
            raise RuntimeError("world_stock CAS 冲突：期望已存在但实际缺失（整单回滚）")
        await tx.execute(
            "INSERT INTO world_state (key, value_json, version, updated_at) VALUES (?,?,?,?)",
            (_WORLD_STOCK_ROW_KEY, value, 1, ts),
        )
        return
    if int(cur["version"]) != expected_version:
        raise RuntimeError("world_stock CAS 冲突：版本不符（整单回滚）")
    await tx.execute(
        "UPDATE world_state SET value_json = ?, version = version + 1, updated_at = ?"
        " WHERE key = ? AND version = ?",
        (value, ts, _WORLD_STOCK_ROW_KEY, expected_version),
    )


async def buy_in_open_tx(
    tx: RepoTransaction,
    *,
    player_qid: str,
    shop_id: str,
    target: str,
    qty: int,
    world_ctx: Mapping[str, Any],
    now: Optional[int] = None,
) -> dict:
    """购买结算事务内逻辑（收口对齐路A processing.py Handler 契约 `handler(tx) -> dict`）。

    由调用方在 `async with repo.tx() as tx:` 内调用（D2 §2.5 并发用例骨架）：
    事务内读玩家行/世界库存（SEG-2）→ 构造 ctx → shop_buy 6 步校验链 + 内存快照-回滚
    （SEG-3/SEG-4）→ 成功则 tx.upsert_player 写回 + 库存 CAS + （调用方）write_idem_key；
    校验链拦截/内部回滚 → 返回 {ok:False}，调用方零 DB 写。幂等键（idem_exists/write_idem_key）
    由入口层负责（路A process_message / 本模块 buy_in_tx 独立入口），本函数**不做幂等判定**。

    :param tx: 已开启的事务句柄（BEGIN IMMEDIATE，持写锁；单写队列使并发事务严格串行，SEG-2）
    :param player_qid: 购买者（玩家行在**事务内重读**，非 load_player 60s 缓存陈旧读数，SEG-2）
    :param shop_id: 商店 id（校验链①）
    :param target: 商品引用（名称优先 → item id → 列表序号）
    :param qty: 购买数量（⑥数量上限提示不拦截先截断）
    :param world_ctx: 静态世界上下文（items/shops/settings/rep_levels/world_sold_out/last_refresh/
        blackmarket_goods + reputation/now 等，装配层批次6/7 注入；工程补白 1）
    :param now: 确定性时间戳注入（UTC+8 秒级；None = 用 world_ctx 的 now 或引擎缺省）
    :return: 统一 dict {ok, ...}（成功含 shop_buy 全字段；校验链拦截含 ok=False，零 DB 写）
    """
    # SEG-2：事务内读玩家行（权威结算读数，非预取缓存）
    row = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (player_qid,))
    if row is None:
        return {"ok": False, "reason": "no_player", "message": "❌ 玩家不存在"}

    player = row_to_player(row)

    # SEG-2：事务内读世界库存（持写锁重读；行缺失 → {} 版本 0，shop_buy 以条目 stock 兜底）
    flat_stock, stock_version = await _read_world_stock_in_tx(tx)

    ctx = _build_ctx(player, world_ctx, world_stock_to_ctx(flat_stock), now)

    # SEG-3/SEG-4：6 步校验链（顺序即提示优先级）+ 内存快照-回滚（事务内校验层）
    res = shop_buy(shop_id, target, qty, ctx)
    if not res.get("ok"):
        return dict(res)  # 校验链拦截/内部回滚：零 DB 写（内存已还原），调用方 COMMIT 空事务

    # ---- 结算成功：玩家写回 + 库存 CAS，与调用方的 write_idem_key 同一事务 COMMIT（SEG-1/SEG-5）----
    items = world_ctx.get("items") if isinstance(world_ctx, Mapping) else None
    await tx.upsert_player(_player_after_buy(player, ctx, items))

    flat_after = world_stock_from_ctx(ctx.get("world_stock") or {})
    if flat_after != flat_stock:
        await _write_world_stock_in_tx(tx, flat_after, stock_version, _now_ts())

    return dict(res)


async def buy_in_tx(
    repo: Repository,
    *,
    player_qid: str,
    shop_id: str,
    target: str,
    qty: int,
    idem_key: Optional[IdemKey] = None,
    world_ctx: Mapping[str, Any],
    now: Optional[int] = None,
) -> dict:
    """购买结算整体搬入 repo.tx()（SEG-1）——独立入口（自开事务），供测试/独立调用。

    `async with repo.tx() as tx:` 内：事务内幂等权威判定（SEG-5，idem_key 非 None 时）→
    buy_in_open_tx（事务内读-校验-扣减-写回，SEG-2/3/4）→ ok 则 write_idem_key（IDEM-2 同事务）
    → 出 with = COMMIT；失败整单回滚。收口：buy_in_open_tx 亦可直接作为路A processing.py
    process_message 的 handler(tx)（幂等判定由入口层承担，本函数仅独立形态的薄封装）。

    :param repo: 存档仓库（tx() = BEGIN IMMEDIATE + 单写队列，并发事务严格串行，SEG-2）
    :param player_qid: 购买者（玩家行在**事务内重读**，非 load_player 60s 缓存陈旧读数，SEG-2）
    :param shop_id: 商店 id（校验链①）
    :param target: 商品引用（名称优先 → item id → 列表序号）
    :param qty: 购买数量（⑥数量上限提示不拦截先截断）
    :param idem_key: 幂等键（message_id/group_id/player_qid 三元组，SEG-5）；None = 跳过幂等判定
    :param world_ctx: 静态世界上下文（见 buy_in_open_tx）
    :param now: 确定性时间戳注入（UTC+8 秒级）
    :return: 统一 dict {ok, ...}（成功含 shop_buy 全字段 + committed/idem_key_written；
        幂等命中/校验链拦截含 committed=False）
    """
    async with repo.tx() as tx:
        # SEG-5/IDEM-3/4：事务内幂等权威判定（查重只读；写键与业务同事务提交）
        if idem_key is not None and await tx.idem_exists(idem_key):
            # P2-2 统一（M6 批2 审查）：幂等重放语义与 processing._replay_reply 一致——
            # ok=False（非新处理）+ idempotent=True（唯一重放信号）；装配层凭 idempotent
            # 位区分重放，不按 ok 误判为失败（send 抑制由装配层按 idempotent 处理）。
            return {
                "ok": False,
                "idempotent": True,
                "message": "✅ 已结算（重复指令，未重复扣款）",
                "bought": {}, "paid": {}, "remaining": {},
                "truncated": False, "advisory": None, "applied": False,
                "committed": False, "idem_key_written": False,
            }

        res = await buy_in_open_tx(
            tx, player_qid=player_qid, shop_id=shop_id, target=target, qty=qty,
            world_ctx=world_ctx, now=now,
        )
        if not res.get("ok"):
            out = dict(res)
            out.setdefault("committed", False)
            out.setdefault("idem_key_written", False)
            return out  # 校验链拦截/内部回滚：零 DB 写，出 with = COMMIT（空事务）

        idem_written = False
        if idem_key is not None:
            await tx.write_idem_key(idem_key)  # 与业务写同事务（IDEM-2/SEG-5）
            idem_written = True

        out = dict(res)
        out["committed"] = True
        out["idem_key_written"] = idem_written
        return out


def _now_ts() -> str:
    """ISO-8601 UTC 时间戳（world_state updated_at）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
