"""品评会指令：/投稿 <道具> + /排行榜（2c5c CT-01~09 周赛）。

文件名：contest_commands.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批3路2）

投稿/看榜需要全局投稿板（跨玩家）→ repo.tx() 自开事务读写 world_state
"contest_board"（对齐 shop_tx 世界库存 CAS 模式）。冠军结算=懒计算
（新周首访/首投时结算上周冠军：称号+宝石+声望，同事务）。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core import contest as ct
from qbot_rpg.storage.repository import row_to_player  # noqa: F401  # 类型注解处延迟导入

__all__ = [
    "SUBMIT_CMD", "RANK_CMD",
    "cmd_contest_submit", "cmd_contest_rank",
    "register_contest_commands",
]

SUBMIT_CMD = "投稿"
RANK_CMD = "排行榜"

_WS_KEY = "contest_board"


def _now_of(ctx: MutableMapping[str, Any]) -> int:
    import time  # noqa: PLC0415
    n = ctx.get("now")
    try:
        if n is None:
            raise TypeError
        return int(n)
    except (TypeError, ValueError):
        return int(time.time())


async def _read_board(tx: Any) -> dict:
    row = await tx.fetchone("SELECT value_json FROM world_state WHERE key = ?", (_WS_KEY,))
    if row is None or not row["value_json"]:
        return {"week": "", "entries": [], "settled_week": ""}
    try:
        v = json.loads(row["value_json"])
        return v if isinstance(v, dict) else {"week": "", "entries": [], "settled_week": ""}
    except (TypeError, ValueError):
        return {"week": "", "entries": [], "settled_week": ""}


async def _write_board(tx: Any, board: dict, now_ts: int) -> None:
    row = await tx.fetchone(
        "SELECT version FROM world_state WHERE key = ?", (_WS_KEY,))
    val = json.dumps(board, ensure_ascii=False)
    from datetime import datetime, timezone  # noqa: PLC0415
    ts = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
    if row is None:
        await tx.execute(
            "INSERT INTO world_state (key, value_json, version, updated_at)"
            " VALUES (?,?,1,?)", (_WS_KEY, val, ts))
    else:
        await tx.execute(
            "UPDATE world_state SET value_json = ?, version = version + 1,"
            " updated_at = ? WHERE key = ?", (val, ts, _WS_KEY))


async def _settle_if_new_week(ctx: MutableMapping[str, Any], tx: Any,
                              now_ts: int) -> list:
    """懒结算（CT-06/07/09）：当前周 ≠ 板上周且板上周未结算 → 给冠军发奖。
    返回奖励消息列表。"""
    board = await _read_board(tx)
    cur_week = ct.week_key_of(now_ts)
    if board.get("settled_week") == board.get("week"):
        return []
    if not board.get("week") or board.get("week") == cur_week:
        return []
    # 结算上周冠军
    entries = board.get("entries") or []
    msgs: list = []
    if entries:
        top = max(entries, key=lambda e: (float(e.get("score", 0) or 0),
                                          -int(e.get("seq", 0) or 0)))
        top_qid = str(top.get("qid") or "")
        cfg = ct.cfg_of(ctx)
        _rw = cfg.get("reward")
        reward: dict = dict(_rw) if isinstance(_rw, Mapping) else {}
        title_name = str(reward.get("title") or "品评冠军")
        gem = int(reward.get("gem", 0) or 0)
        _rep_cfg = reward.get("reputation")
        if isinstance(_rep_cfg, Mapping):
            rep_win = int(_rep_cfg.get("win", 30) or 30)
        else:
            rep_win = 30
        # 冠军玩家存档（同事务）
        if top_qid:
            row = await tx.fetchone(
                "SELECT * FROM players WHERE player_qid = ?", (top_qid,))
            if row is not None:
                p = row_to_player(row)
                # 称号入 title_state.owned；宝石入 currencies.gem；声望入 reputation_state
                import dataclasses  # noqa: PLC0415
                new_title: dict = dict(p.title_state)  # title_state.owned 列表键
                owned_any = new_title.get("owned")
                owned: list = list(owned_any) if isinstance(owned_any, (list, tuple)) else []
                if title_name not in owned:
                    owned = list(owned) + [title_name]
                    new_title["owned"] = owned
                cur_cur = dict(p.currencies)
                cur_cur["gem"] = int(cur_cur.get("gem", 0) or 0) + gem
                rep_st = dict(p.reputation_state)
                rep_st["contest"] = int(rep_st.get("contest", 0) or 0) + rep_win
                p2 = dataclasses.replace(p, title_state=new_title,
                                         currencies=cur_cur,
                                         reputation_state=rep_st)
                await tx.upsert_player(p2)
                msgs.append(f"【上周冠军】{top.get('name', top_qid)}"
                            f"（称号「{title_name}」+宝石{gem}+声望{rep_win}）")
    board["settled_week"] = board.get("week", "")
    await _write_board(tx, board, now_ts)
    return msgs


async def _submit_core(ctx: MutableMapping[str, Any], item_ref: str) -> str:
    """投稿结算（repo.tx 事务内）。"""
    repo = ctx.get("repo")
    if repo is None or not hasattr(repo, "tx"):
        return "❌ 品评会未开放"
    me = ctx.get("player")
    my_qid = str(ctx.get("qid") or ctx.get("qq_id") or "")
    if me is None or not my_qid:
        return "❌ 请先 /注册 创建角色"
    now_ts = _now_of(ctx)
    if not ct.enabled(ctx):
        return "❌ 品评会未开启（本周暂无活动）"
    ok, hint = ct.in_window(ctx, now_ts)
    if not ok:
        return f"❌ {hint}"

    from qbot_rpg.storage.repository import row_to_player as _rtp  # noqa: PLC0415

    async with repo.tx() as tx:
        row_a = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (my_qid,))
        if row_a is None:
            return "❌ 请先 /注册 创建角色"
        a = _rtp(row_a)
        # 背包找道具（精确名/id → 前缀唯一）
        target = None
        for r in a.inventory:
            if str(r.item_id) == item_ref or str(r.name) == item_ref:
                target = r
                break
        if target is None:
            cands = [r for r in a.inventory
                     if str(r.name).startswith(item_ref)
                     or str(r.item_id).startswith(item_ref)]
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                return f"❌ 「{item_ref}」匹配多个物品，请用编号（/背包）"
        if target is None:
            return f"❌ 背包里没有「{item_ref}」"
        # 一期限一件（persistent_state.contest_entries 期键）
        week = ct.week_key_of(now_ts)
        import dataclasses  # noqa: PLC0415
        ps = dict(a.persistent_state)
        rec_raw = ps.get("contest_entries")
        rec: dict = dict(rec_raw) if isinstance(rec_raw, dict) else {}
        if ct.entry_exists(rec, week, my_qid):
            return "❌ 本期已投稿过（每期限投一件）"
        # 四维评分
        cfg = ct.cfg_of(ctx)
        weights = cfg.get("score_weights")
        weights = weights if isinstance(weights, Mapping) else {}
        total, dims = ct.score_item(target, weights)
        # 扣道具（tuple replace）+ 玩家记录
        inv = list(a.inventory)
        for i, r in enumerate(inv):
            if r is target or (str(r.item_id) == str(target.item_id)
                               and str(r.name) == str(target.name)):
                if r.count <= 1:
                    inv.pop(i)
                else:
                    inv[i] = dataclasses.replace(r, count=r.count - 1)
                break
        rec[week] = {"qid": my_qid, "item": str(target.item_id),
                     "name": str(target.name), "score": total}
        ps["contest_entries"] = rec
        a2 = dataclasses.replace(a, inventory=tuple(inv), persistent_state=ps)
        # 声望 +submit
        rep_st = dict(a2.reputation_state)
        _rw2 = cfg.get("reward")
        reward: dict = dict(_rw2) if isinstance(_rw2, Mapping) else {}
        _rep_cfg2 = reward.get("reputation")
        if isinstance(_rep_cfg2, Mapping):
            rep_sub = int(_rep_cfg2.get("submit", 5) or 5)
        else:
            rep_sub = 5
        rep_st["contest"] = int(rep_st.get("contest", 0) or 0) + rep_sub
        a2 = dataclasses.replace(a2, reputation_state=rep_st)
        await tx.upsert_player(a2)
        # 全局投稿板（同事务；先懒结算上周）
        msgs = await _settle_if_new_week(ctx, tx, now_ts)
        board = await _read_board(tx)
        if board.get("week") != week:
            board = {"week": week, "entries": [], "settled_week": ""}
        board.setdefault("entries", [])
        board["entries"].append({
            "qid": my_qid, "name": str(a2.name or my_qid),
            "item": str(target.item_id), "item_name": str(target.name),
            "score": total, "seq": len(board["entries"]) + 1,
        })
        await _write_board(tx, board, now_ts)
        _sync_ctx_player(ctx, a2)
        msg = f"✅ 已投稿：{target.name}（品评 {total} 分）声望 +{rep_sub}"
        if msgs:
            msg += "\n" + "\n".join(msgs)
        return msg


def _sync_ctx_player(ctx: MutableMapping[str, Any], fresh: Any) -> None:
    """事务后状态同步回 ctx（防 runner 旧快照覆盖——同赠送 F-G6）。

    ctx["player"] 为 Player dataclass（装配层 L1188 注入实例）→ 直接替换为
    fresh（事务后权威状态，runner 落档即一致）；dict 形态 → 就地更新字段。
    """
    import dataclasses  # noqa: PLC0415
    cur = ctx.get("player")
    if dataclasses.is_dataclass(fresh) and dataclasses.is_dataclass(cur):
        ctx["player"] = fresh
    elif isinstance(cur, MutableMapping) and hasattr(fresh, "inventory"):
        try:
            cur["inventory"] = list(fresh.inventory)
            cur["persistent_state"] = dict(fresh.persistent_state)
            cur["reputation_state"] = dict(fresh.reputation_state)
        except (TypeError, KeyError):
            pass


async def _rank_core(ctx: MutableMapping[str, Any]) -> str:
    """排行榜（事务内读全局板；新周懒结算先行）。"""
    repo = ctx.get("repo")
    if repo is None or not hasattr(repo, "tx"):
        return "❌ 品评会未开放"
    now_ts = _now_of(ctx)
    async with repo.tx() as tx:
        msgs = await _settle_if_new_week(ctx, tx, now_ts)
        board = await _read_board(tx)
        entries = board.get("entries") or []
        if not entries:
            return "本期暂无投稿（/投稿 <道具> 参赛）"
        top = sorted(entries, key=lambda e: (float(e.get("score", 0) or 0),
                                             -int(e.get("seq", 0) or 0)),
                     reverse=True)[:10]
        lines = [f"【品评会排行】（{board.get('week', '')}）"]
        for i, e in enumerate(top, start=1):
            medal = "冠军" if i == 1 else ("亚军" if i == 2 else ("季军" if i == 3 else f"{i}."))
            lines.append(f"{medal} {e.get('name', '?')}｜{e.get('item_name', '?')}"
                         f"｜{e.get('score')} 分")
        if msgs:
            lines.append("\n".join(msgs))
        return "\n".join(lines)


def cmd_contest_submit(parsed: Any, ctx: MutableMapping[str, Any]) -> Any:
    """/投稿 <道具>：品评会投稿（async tx——返回 coroutine 由 runner await）。"""
    if ctx.get("player") is None or not ctx.get("registered", False):
        return "❌ 请先 /注册 创建角色"
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return "❌ 参数错误：/投稿 <道具名>"
    raw = str(args[0])
    item_ref = raw.split("*", 1)[0].strip()
    return _submit_core(ctx, item_ref)


def cmd_contest_rank(parsed: Any, ctx: MutableMapping[str, Any]) -> Any:
    """/排行榜：品评会排行（async tx）。"""
    return _rank_core(ctx)


def register_contest_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /投稿 /排行榜 注册进 Router。"""
    from qbot_rpg.commands.router import CommandSpec  # noqa: PLC0415

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError("contest_commands.register_contest_commands 需要 make_context")
        return make_context(parsed)

    def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _h(parsed: Any, *a: Any, **k: Any) -> Any:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(SUBMIT_CMD, handler=_wrap(cmd_contest_submit)))
    router.register(CommandSpec(RANK_CMD, handler=_wrap(cmd_contest_rank)))
    return router
