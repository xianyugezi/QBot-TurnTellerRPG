"""赠送指令：赠送 <物品>*<数量> <玩家>（定稿 L1286/L953 + 4f B5：原子转移引擎）。

文件名：gift_commands.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批2路1）

功能描述：
  - cmd_gift（async handler——跨玩家存档必须事务内读写）：解析物品/数量/目标
    → repo.tx() 自开事务（BEGIN IMMEDIATE 单写串行化）→ 事务内读 A/B 玩家行 →
    校验（A≠B/物品存在/非绑定/数量足/目标已注册）→ A 扣 B 加（双 replace）→
    双 upsert 同事务 COMMIT（原子：不存在「A 扣了 B 没到」窗口）。

依据：
  - /root/docs_archive/RPG框架项目/RPG回合制框架设计文档.md L1286（/赠送 语法：
    物品可带 *数量：/赠送 药水*5 123456）/ L953（非绑定可赠，同群不限制次数）
  - docs/细化/细化_4f_基础指令组契约.md B5/RUL-07（角色名全服唯一=寻址键）
  - docs/指令清单_全量.md（规划索引：交易引擎新建——勘察确认无现成引擎）
  - qbot_rpg/commands/shop_tx.py（事务模式参照：tx.fetchone 读行 → 操作 →
    tx.upsert_player + 幂等键同事务）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  F-G1 目标寻址：优先 QQ 号（数字直给，L1286 示例形态）；角色名 → 事务内
       SELECT nickname=? 反查 qid（角色名全服唯一 B5；查无 → 目标不存在）。
       群成员校验（同群）无可靠实机数据源（ctx 无群成员→存档映射），按
       L953「同群」语义软降级：不硬拦（同群由社交层兜底；无群信息保守放行，
       对齐 alchemy_commands GU-46 缺省口径）。
  F-G2 数量解析：*N 后缀（parsed.qty 已由解析层归一）；无 * → 1。
  F-G3 物品行操作：Player frozen dataclass → dataclasses.replace 流（不转 dict，
       commands 层不 import assembly）；A 扣（count 减/行移除）、B 加（同 item_id
       行堆叠或追加新行——name/quality 从 A 行复制，保持物品属性一致）。
  F-G4 幂等：message_id 幂等由 processing 层统一（每消息恰处理一次）；本指令
       单事务原子已保证无半状态——重发同 message_id 不重入（框架层）。
  F-G5 发送者自身须已注册（ctx player 存在）；接收者离线也能收（存档即达，
       定稿无在线要求——「双方在线」为规划文档补白，实现按存档可达）。
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, List, MutableMapping, Optional, Tuple

from qbot_rpg.core.templates import tpl_of
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player

__all__ = [
    "GIFT_CMD",
    "cmd_gift",
    "register_gift_commands",
]

GIFT_CMD = "赠送"


# ---------------------------------------------------------------------------
# 物品行操作（Player frozen → replace 流）
# ---------------------------------------------------------------------------

def _inv_list(player: Player) -> List[ItemInstance]:
    return list(player.inventory)


def _row_have(inv: List[ItemInstance], item_id: str) -> int:
    return sum(int(r.count) for r in inv if str(r.item_id) == item_id)


def _take_items(player: Player, item_id: str, qty: int) -> Tuple[Player, bool, int]:
    """A 扣 qty（count 减/行移除）。返回 (新 Player, ok, 剩余持有)。"""
    inv = _inv_list(player)
    have = _row_have(inv, item_id)
    if have < qty:
        return player, False, have
    remaining = qty
    out: List[ItemInstance] = []
    for r in inv:
        if str(r.item_id) == item_id and remaining > 0:
            if r.count <= remaining:
                remaining -= r.count
                continue  # 整行移除
            out.append(dataclasses.replace(r, count=r.count - remaining))
            remaining = 0
        else:
            out.append(r)
    new_p = dataclasses.replace(player, inventory=tuple(out))
    return new_p, True, have - qty


def _give_items(player: Player, row: ItemInstance, qty: int,
                max_stack: int = 99) -> Tuple[Player, bool]:
    """B 加 qty（同 item_id 行堆叠 / 追加新行）。返回 (新 Player, ok)。"""
    inv = _inv_list(player)
    out: List[ItemInstance] = []
    remaining = qty
    for r in inv:
        if str(r.item_id) == str(row.item_id) and remaining > 0:
            space = max_stack - r.count
            if space > 0:
                take = min(space, remaining)
                out.append(dataclasses.replace(r, count=r.count + take))
                remaining -= take
            else:
                out.append(r)
        else:
            out.append(r)
    while remaining > 0:
        n = min(max_stack, remaining)
        out.append(dataclasses.replace(row, count=n))
        remaining -= n
    new_p = dataclasses.replace(player, inventory=tuple(out))
    return new_p, True


def _sync_ctx_player(ctx: MutableMapping[str, Any], fresh: Player) -> None:
    """事务后状态同步回 ctx（F-G6）：ctx["player"] 为 Player dataclass → replace；
    dict → 就地更新 inventory/currencies/name（runner 落档一致性）。"""
    cur = ctx.get("player")
    if isinstance(cur, Player):
        ctx["player"] = dataclasses.replace(
            cur, inventory=fresh.inventory, currencies=fresh.currencies)
    elif isinstance(cur, MutableMapping):
        cur["inventory"] = list(fresh.inventory)
        cur["currencies"] = dict(fresh.currencies)


# ---------------------------------------------------------------------------
# 主指令（async：事务内读 A/B → 校验 → 双写）
# ---------------------------------------------------------------------------

async def _gift_core(ctx: MutableMapping[str, Any], item_ref: str, qty: int,
                     target_ref: str) -> str:
    """赠送结算（repo.tx 事务内；消息模板渲染）。"""
    repo = ctx.get("repo")
    if repo is None or not hasattr(repo, "tx"):
        return tpl_of(ctx, "gift_no_system")
    me = ctx.get("player")
    my_qid = str(ctx.get("qid") or ctx.get("qq_id") or "")
    if me is None or not my_qid:
        return tpl_of(ctx, "gift_register_gate")
    # 自己 → 拒绝
    if target_ref == my_qid:
        return tpl_of(ctx, "gift_self")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return tpl_of(ctx, "gift_err_qty")
    if qty < 1:
        return tpl_of(ctx, "gift_err_qty")

    from qbot_rpg.storage.repository import row_to_player  # noqa: PLC0415

    async with repo.tx() as tx:
        # 事务内读发送者（权威读数）
        row_a = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (my_qid,))
        if row_a is None:
            return tpl_of(ctx, "gift_register_gate")
        a = row_to_player(row_a)

        # 目标解析：QQ 号直给 or 角色名反查（F-G1）
        target_qid = target_ref if target_ref.isdigit() else ""
        if not target_qid:
            row_b = await tx.fetchone(
                "SELECT player_qid FROM players WHERE nickname = ?", (target_ref,))
            if row_b is None:
                return tpl_of(ctx, "gift_target_not_found", {"target": target_ref})
            target_qid = str(row_b["player_qid"])
        if target_qid == my_qid:
            return tpl_of(ctx, "gift_self")

        # 读接收者
        row_b = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (target_qid,))
        if row_b is None:
            return tpl_of(ctx, "gift_target_not_found", {"target": target_ref})
        b = row_to_player(row_b)

        # 发送者背包找物品（item_ref = item_id 或 name）
        a_row: Optional[ItemInstance] = None
        for r in a.inventory:
            if str(r.item_id) == item_ref or str(r.name) == item_ref:
                a_row = r
                break
        if a_row is None:
            return tpl_of(ctx, "gift_not_found", {"name": item_ref})
        if a_row.bound:
            return tpl_of(ctx, "gift_bound")
        # 数量足够？（扣减前先看持有）
        have = _row_have(_inv_list(a), str(a_row.item_id))
        if have < qty:
            return tpl_of(ctx, "gift_no_item",
                          {"name": str(a_row.name or a_row.item_id), "have": have})

        # A 扣 + B 加（原子：双 upsert 同事务）
        a2, ok_a, remain = _take_items(a, str(a_row.item_id), qty)
        if not ok_a:
            return tpl_of(ctx, "gift_no_item",
                          {"name": str(a_row.name or a_row.item_id), "have": have})
        b2, _ok_b = _give_items(b, a_row, qty)
        await tx.upsert_player(a2)
        await tx.upsert_player(b2)
        # F-G6 落档一致性：事务已写 A 新状态；runner 每指令会把 ctx["player"]
        # 全量 upsert 覆盖——若 ctx 仍持旧快照会回滚本次扣减。把 ctx["player"]
        # 同步为事务后状态（重复 upsert 幂等无害）
        _sync_ctx_player(ctx, a2)

        tgt_name = str(b2.name or target_ref)
        msg = tpl_of(ctx, "gift_ok", {
            "name": str(a_row.name or a_row.item_id), "qty": qty,
            "target": tgt_name, "remain": remain})
        return msg


def cmd_gift(parsed: Any, ctx: MutableMapping[str, Any]) -> Any:
    """赠送 <物品>*<数量> <玩家>：原子转移（async 事务——返回 coroutine 由
    runner _invoke_handler await）。"""
    p = ctx.get("player")
    if p is None or not ctx.get("registered", False):
        return tpl_of(ctx, "gift_register_gate")
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "gift_err_empty")
    raw_item = str(args[0])
    # F-G2：*N 从物品 token 剥离（parsers args 保留原始形态；qty 已解析层归一）
    item_ref = raw_item.split("*", 1)[0].strip()
    if not item_ref:
        return tpl_of(ctx, "gift_err_empty")
    if len(args) < 2:
        return tpl_of(ctx, "gift_err_missing_player")
    target_ref = str(args[1])
    if not target_ref:
        return tpl_of(ctx, "gift_err_missing_player")
    # F-G2：qty 优先 parsed.qty（parse_command 直调路径）；装配层路由
    # （_parsed_from_route）不解析 qty → 从物品 token *N 兜底
    qty = getattr(parsed, "qty", None)
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        _star = raw_item.split("*", 1)
        if len(_star) == 2 and _star[1].isdigit():
            qty = int(_star[1])
        else:
            qty = 1
    return _gift_core(ctx, item_ref, qty, target_ref)


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------

def register_gift_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 赠送 注册进 Router。"""
    from qbot_rpg.commands.router import CommandSpec  # noqa: PLC0415

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError("gift_commands.register_gift_commands 需要 make_context")
        return make_context(parsed)

    def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _h(parsed: Any, *a: Any, **k: Any) -> Any:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(GIFT_CMD, handler=_wrap(cmd_gift)))
    return router
