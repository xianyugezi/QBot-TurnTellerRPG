"""战斗击杀奖励结算引擎（2026-09-03 · PvE 奖励断链修复）。

依据：
  - docs/veinborn_阶段一_进度存档_20260903.md §三.1（拦路缺口：击杀奖励落账
    （enemy rewards/drops → 玩家 exp/币/掉落 + 升级）从未实现——battle_reward_fn
    装配恒 None，context.py L1175，炼金/钓鱼/签到各有结算唯独 PvE 战斗没有）
  - qbot_rpg/core/reward.py（A1 dispatch_reward 唯一发放器：货币键空间
    settings.currencies[].id；item 入包走 ctx["add_item"] hook，缺 hook/失败 →
    skip(item_add_failed) 不伪装已发放）
  - qbot_rpg/core/levelup.py（LevelUpEngine.gain_exp：exp 入账→跨级判定→升级回满
    HP/MP/SP 发放/白值重算，LVL-01~LVL-12；操作对象为 MutableMapping dict——
    attributes 须为 PlayerAttributes 实例（gain_exp L163-165 isinstance 校验））
  - docs/细化/细化_5e_战斗战报格式.md（军规5 结算一次性：经验/掉落只在战斗结束
    消息输出一次）
  - qbot_rpg/commands/battle_commands.py L338-362（_battle_rewards 消费契约：
    fn(engine, report, ctx) -> {exp,gold,drops}；drops 为 (名称, 数量) 二元组序列
    或含 name/count 键 dict 序列，render_battle_end L922-932 消费）

【工程补白 · 显式标注】
  1) 本引擎只做「击杀结算」（胜利方玩家拿奖励），失败/逃跑/平局不结算；
     触发判定在指令层（dispatch_round win 分支 / battle_reward_fn 内），本层
     纯函数只算不判胜负。
  2) 结算落点 = ctx 就地引用（对齐 reward/checkin/forge 先例）：
     - exp/level/hp/mp/currencies/attributes 全在 player dict（MutableMapping）；
     - 生产 ctx["player"] 为 Player frozen dataclass → 本层先 dataclasses.asdict
       转可变 dict 写回 ctx["player"]（对齐 basic_commands._player L1104-1110 /
       use_commands._resolve_player 先例），runner 落档走 _player_from_dict
       dict 分支（runner.py L493-496，inventory 经 _coerce_inventory_items 还原）。
     - 币经 player["currencies"] 就地累加（键空间 settings.currencies[].id）；
     - 物品经 ctx["add_item"] hook 入包（缺 hook/False → 黄字 skip P1-1）。
  3) 幂等：ctx["tx_id"]+ctx["ledger"] 同给才生效（对齐 dispatch_reward 口径）；
     战斗结算正常封口（内容错误逐条 skip 不中断，P1-2）。
  4) 掉落概率：每死亡掉落独立 roll（chance 0-100，rng 注入铁律 6）；count 支持
     int 或 [min,max]（对齐 demo 包 drops.death count 形态）。
  5) exp 数值合法（>=0）；rewards.currencies 键空间非法（不在 settings
     currencies[].id）→ 该币 skip（unknown_currency，P1-2 逐条目跳过）。
  6) 掉落物渲染：返回 drops = [(显示名, 数量)]，显示名经 ctx["items"][id].name /
     resolve_item 解析（缺省回退 item_id 原样）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；rng 确定性注入；工程补白显式标注。
"""

from __future__ import annotations

import dataclasses
import random
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.levelup import LevelUpEngine
from qbot_rpg.data.player import Player, PlayerAttributes

__all__ = [
    "settle_battle_rewards",
    "roll_death_drops",
    "reward_entries_from_enemy",
]


def _int(value: Any, default: int = 0) -> int:
    """防御性整数化（非数值/负值 → default）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


def _item_name_of(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品显示名：ctx["items"][id].name / Def.name / resolve_item；兜底 item_id。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        entry = items.get(item_id)
        if isinstance(entry, Mapping):
            nm = entry.get("name")
            if isinstance(nm, str) and nm:
                return nm
        elif entry is not None:
            nm = getattr(entry, "name", None)
            if isinstance(nm, str) and nm:
                return nm
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            d = resolver(item_id)
            if isinstance(d, Mapping):
                nm = d.get("name")
                if isinstance(nm, str) and nm:
                    return nm
            else:
                nm = getattr(d, "name", None)
                if isinstance(nm, str) and nm:
                    return nm
        except Exception:
            pass
    return str(item_id)


def _count_of(raw: Any, rng: random.Random) -> int:
    """count 数值形态归一：int 直用 / [min,max] 区间随机（对齐 demo drops 形态）。"""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        lo = _int(raw[0], 1)
        hi = _int(raw[1], lo)
        if hi < lo:
            hi = lo
        return rng.randint(lo, hi)
    return _int(raw, 1)


def reward_entries_from_enemy(enemy_entry: Mapping[str, Any]) -> List[dict]:
    """enemies.json 条目 rewards → 结构化奖励条目（dispatch_reward 兼容形态）。

    rewards: {exp:int, currencies:{币id:int}}；无 rewards → []。
    """
    rw = enemy_entry.get("rewards")
    if not isinstance(rw, Mapping):
        return []
    entries: List[dict] = []
    exp = rw.get("exp")
    if isinstance(exp, int) and not isinstance(exp, bool) and exp > 0:
        entries.append({"exp": exp})
    curs = rw.get("currencies")
    if isinstance(curs, Mapping):
        for cid, amt in curs.items():
            if (
                isinstance(cid, str) and cid
                and isinstance(amt, int) and not isinstance(amt, bool) and amt > 0
            ):
                entries.append({cid: amt})
    return entries


def roll_death_drops(
    enemy_entry: Mapping[str, Any],
    rng: random.Random,
) -> List[dict]:
    """死亡掉落 roll（drops.death 表）：chance% 掉落 → [(item_id, count)]。

    只消费 drops.death（击杀结算一次性，对齐 5e 军规5）；battle/special 属
    部位破坏等战斗中掉落，另有消费方（veinborn 破技），本层不触碰。
    无 drops / 空 → []。逐条独立 roll（rng 注入，铁律 6）。
    """
    drops = enemy_entry.get("drops")
    if not isinstance(drops, Mapping):
        return []
    death = drops.get("death")
    if not isinstance(death, list):
        return []
    out: List[dict] = []
    for d in death:
        if not isinstance(d, Mapping):
            continue
        item_id = d.get("item")
        if not isinstance(item_id, str) or not item_id:
            continue
        chance = _int(d.get("chance"), 100)
        if chance >= 100 or (chance > 0 and rng.random() * 100 < chance):
            out.append({"item": item_id, "count": _count_of(d.get("count", 1), rng)})
    return out


def _player_view(ctx: MutableMapping[str, Any]) -> tuple:
    """返回 (orig, work)：orig=ctx 原玩家对象（Player/None/dict 引用），
    work=可变玩家 dict（引擎就地改写用）。

    - ctx["player"] 为 Player（生产装配）：orig=Player 实例，work=asdict 副本
      （attributes 还原 PlayerAttributes——asdict 深转普通 dict，升级引擎
      isinstance 校验）；结算后 _commit_player 用 dataclasses.replace 生成新
      Player 写回 ctx["player"]（保持 Player 分支落档 + inventory merge）。
    - ctx["player"] 为 dict（指令壳 asdict 先例/测试）：orig=None，
      work=该 dict 引用（就地改，_commit_player 只做 inventory 合并）。
    - 无 player（未注册兜底）：orig=None，work=ctx 自身（对齐 _player_of 先例）。
    """
    p = ctx.get("player")
    if isinstance(p, Player):
        d: dict = dataclasses.asdict(p)
        attrs_raw = d.get("attributes")
        if isinstance(attrs_raw, Mapping):
            try:
                d["attributes"] = PlayerAttributes(**attrs_raw)
            except (TypeError, ValueError):
                pass
        return p, d
    if isinstance(p, MutableMapping):
        # 已有可变 dict：attributes 可能被 asdict 转成普通 dict → 还原
        attrs = p.get("attributes")
        if isinstance(attrs, Mapping) and not isinstance(attrs, PlayerAttributes):
            try:
                p["attributes"] = PlayerAttributes(**attrs)
            except (TypeError, ValueError):
                pass
        return None, p
    if isinstance(ctx, MutableMapping):
        return None, ctx
    raise TypeError("战斗奖励结算需要可变玩家状态（ctx['player'] 或 ctx 自身）")


def _commit_player(
    ctx: MutableMapping[str, Any],
    orig: Any,
    work: MutableMapping[str, Any],
) -> None:
    """结算收尾：work dict 的玩家变更提交回 ctx["player"]。

    - orig 为 Player（生产）：把 level/exp/hp/mp/currencies/attributes/
      proficiency(ps)/persistent_state 等变更 dataclasses.replace 成新 Player
      写回 ctx["player"]（frozen dataclass 正道；runner 落档走 Player 分支，
      其 _m8_dirty_inventory merge 会把 ctx["inventory"] 计数并回实例列表——
      add_item hook 已写 ctx["inventory"] + 置 dirty 标记，掉落物品自然落档）。
    - orig 为 None（dict/ctx 形态）：dict 已是可变引用，inventory 计数已写
      ctx["inventory"]；runner 落档 dict 分支读 player["inventory"] 槽——
      把 ctx 计数映射合并进 work["inventory"]（对齐 _ctx_inventory_to_player
      语义，缺 merge 则掉落静默丢）。
    """
    if orig is None:
        _merge_ctx_inventory(ctx, work)
        return
    if not isinstance(orig, Player):
        return
    from dataclasses import replace as _dcreplace  # noqa: PLC0415

    try:
        new = _dcreplace(
            orig,
            level=int(work.get("level", orig.level)),
            exp=int(work.get("exp", orig.exp)),
            hp=int(work.get("hp", orig.hp)),
            mp=int(work.get("mp", orig.mp)),
            currencies=dict(work.get("currencies") or {}),
            attributes=work.get("attributes", orig.attributes),
        )
    except (TypeError, ValueError):
        return
    # proficiency 发放（gain_exp LVL-07 写 work["proficiency"]）挂 ps 落档
    prof = work.get("proficiency")
    if isinstance(prof, Mapping) and prof:
        ps = dict(new.persistent_state)
        ps["proficiency"] = prof
        try:
            new = _dcreplace(new, persistent_state=ps)
        except (TypeError, ValueError):
            pass
    ctx["player"] = new


def _merge_ctx_inventory(
    ctx: MutableMapping[str, Any],
    player: MutableMapping[str, Any],
) -> None:
    """dict 形态兜底：ctx 计数映射 → player["inventory"] 槽（自实现轻量 merge，
    不跨层引 commands/shop_tx——core 层 G0 禁反向依赖）。"""
    inv_ctx = ctx.get("inventory")
    if not isinstance(inv_ctx, Mapping):
        return
    old = player.get("inventory")
    counts: Dict[str, int] = {}
    insts_meta: Dict[str, dict] = {}
    if isinstance(old, (list, tuple)):
        for it in old:
            iid = it.get("item_id") if isinstance(it, dict) else getattr(it, "item_id", None)
            if not iid:
                continue
            n = int(it.get("count") if isinstance(it, dict) else getattr(it, "count", 1) or 1)  # type: ignore[arg-type]
            counts[str(iid)] = counts.get(str(iid), 0) + n
            if isinstance(it, dict):
                insts_meta.setdefault(str(iid), it)
    elif isinstance(old, Mapping):
        for k, v in old.items():
            counts[str(k)] = counts.get(str(k), 0) + int(v or 0)
    # ctx 计数权威（add_item 已累加）
    for k, v in inv_ctx.items():
        counts[str(k)] = int(v or 0)
    out = []
    for iid, n in counts.items():
        if n <= 0:
            continue
        meta = insts_meta.get(str(iid))
        row = dict(meta) if meta else {}
        row.update({"item_id": str(iid), "count": n})
        out.append(row)
    player["inventory"] = out


def settle_battle_rewards(
    ctx: MutableMapping[str, Any],
    enemy_entry: Optional[Mapping[str, Any]] = None,
    *,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """战斗击杀奖励结算（胜利后由指令层调用一次；纯函数就地改写 ctx）。

    入参 ctx: 结算上下文（player/items/add_item/settings/tx_id/ledger 等装配键）；
    enemy_entry: enemies.json 条目（含 rewards/drops.death）；rng: 掉落随机源
    （缺省随机，铁律 6 建议注入）。

    出参 {exp, gold, drops, granted, skipped, idempotent, leveled}：
      - exp/gold: 实发经验/金币（渲染层战斗结束行用）
      - drops: [(显示名, 数量)]（render_battle_end 战利品列表，军规5 一次性）
      - granted/skipped: 逐条入账/跳过记录（对齐 dispatch_reward 形态）
      - idempotent: 同 tx_id 已在 ledger → True（重复调用不重复入账）
      - leveled: 升级信息（level_ups/hp_restored/mp_restored/exp_next，装配层
        可渲染升级推送）

    只结算 rewards（exp/currencies）+ drops.death（死亡掉落）；exp 走
    LevelUpEngine（升级回满/SP/白值重算），币走 player currencies 就地，
    物品走 add_item hook 入包（失败黄字 skip 不中断，P1-1 防静默丢奖）。
    """
    rng = rng if rng is not None else random.Random()
    empty = {"exp": 0, "gold": 0, "drops": [], "granted": [], "skipped": [],
             "idempotent": False, "leveled": None}
    if enemy_entry is None or not isinstance(enemy_entry, Mapping):
        return empty

    # 幂等闸（对齐 dispatch_reward 工程补白⑤）：同 tx 已结算 → 直接返回
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None and ledger is not None and hasattr(ledger, "__contains__"):
        if tx_id in ledger:
            return {**empty, "idempotent": True}

    granted: List[dict] = []
    skipped: List[dict] = []
    exp_granted = 0
    gold_granted = 0
    leveled: Optional[dict] = None

    # 玩家工作副本一次性 view（Player → asdict 副本 / dict → 就地引用）；
    # work 贯穿 ①② 全程变更，④ 统一 commit（避免多次 view 丢变更）
    try:
        orig_player, player = _player_view(ctx)
    except Exception:
        orig_player, player = None, {}

    entries = reward_entries_from_enemy(enemy_entry)
    if entries:
        exp_amt = 0
        cur_entries: List[dict] = []
        for e in entries:
            if "exp" in e:
                exp_amt += _int(e.get("exp"), 0)
            else:
                cur_entries.append(e)
        # ① exp 走 LevelUpEngine（dispatch_reward 的 exp 只加 ctx 标量不升级）
        if exp_amt > 0:
            try:
                attrs = player.get("attributes")
                if not isinstance(attrs, PlayerAttributes):
                    skipped.append({"type": "exp", "amount": exp_amt,
                                    "reason": "missing_bucket"})
                else:
                    settings = ctx.get("settings")
                    settings = settings if isinstance(settings, Mapping) else {}
                    eng = LevelUpEngine(
                        level_cap=int(settings.get("level_cap", 45) or 45),
                        exp_curve=settings.get("exp_curve"),
                    )
                    res = eng.gain_exp(player, exp_amt)
                    if isinstance(res, Mapping) and res.get("ok"):
                        exp_granted += exp_amt
                        granted.append({"type": "exp", "amount": exp_amt,
                                        "level_ups": int(res.get("level_ups", 0) or 0)})
                        if int(res.get("level_ups", 0) or 0) > 0:
                            leveled = {
                                "level": int(res.get("level", player.get("level", 1))),
                                "level_ups": int(res.get("level_ups", 0) or 0),
                                "sp_earned_delta": int(res.get("sp_earned_delta", 0) or 0),
                                "hp_restored": int(res.get("hp_restored", 0) or 0),
                                "mp_restored": int(res.get("mp_restored", 0) or 0),
                                "exp_next": int(res.get("exp_next", 0) or 0),
                            }
                    else:
                        skipped.append({"type": "exp", "amount": exp_amt,
                                        "reason": "grant_failed"})
            except Exception:
                skipped.append({"type": "exp", "amount": exp_amt,
                                "reason": "grant_failed"})
        # ② 币（rewards.currencies）→ dispatch_reward 就地入 work currencies
        if cur_entries:
            from qbot_rpg.core.reward import dispatch_reward  # noqa: PLC0415

            cur = player.get("currencies")
            if not isinstance(cur, MutableMapping):
                player["currencies"] = {}
                cur = player["currencies"]
            reward_ctx: MutableMapping[str, Any] = dict(ctx)
            reward_ctx["currencies"] = cur
            rw = dispatch_reward(cur_entries, reward_ctx)
            granted.extend(list(rw.get("granted") or ()))
            skipped.extend(list(rw.get("skipped") or ()))
            for g in rw.get("granted") or ():
                if isinstance(g, Mapping) and g.get("type") == "currency":
                    gold_granted += _int(g.get("amount"), 0)

    # ③ 死亡掉落（drops.death 表，chance roll）→ dispatch_reward 入包
    #    （add_item hook 写 ctx["inventory"] + inventory_instances + dirty 标记；
    #    Player 形态由 runner 落档 merge，dict 形态由 _commit_player 合并）
    drop_items = roll_death_drops(enemy_entry, rng)
    drop_names: List[Tuple[str, int]] = []
    if drop_items:
        from qbot_rpg.core.reward import dispatch_reward  # noqa: PLC0415

        rw = dispatch_reward(drop_items, ctx)
        granted.extend(list(rw.get("granted") or ()))
        skipped.extend(list(rw.get("skipped") or ()))
        for g in rw.get("granted") or ():
            if isinstance(g, Mapping) and g.get("type") == "item":
                iid = g.get("item") or g.get("item_id")
                if isinstance(iid, str):
                    drop_names.append((_item_name_of(ctx, iid), _int(g.get("count"), 1)))

    # ④ 玩家变更提交（Player → dataclasses.replace 新实例写回 ctx["player"]；
    #    dict 形态 → ctx 计数映射合并进 work["inventory"]）
    try:
        if entries or drop_items or player:
            _commit_player(ctx, orig_player, player)
    except Exception:
        pass

    # 幂等封口：batch 完成（含普通 skipped）即记 ledger；item_add_failed 不封口
    # （P1-1：物品未实际入包 → 可重试，防静默丢奖——对齐 reward.py L497-505）
    if tx_id is not None and ledger is not None and hasattr(ledger, "add"):
        if not any(
            isinstance(s, Mapping) and s.get("type") == "item"
            and s.get("reason") == "item_add_failed"
            for s in skipped
        ):
            ledger.add(tx_id)

    return {
        "exp": exp_granted,
        "gold": gold_granted,
        "drops": drop_names,
        "granted": granted,
        "skipped": skipped,
        "idempotent": False,
        "leveled": leveled,
    }
