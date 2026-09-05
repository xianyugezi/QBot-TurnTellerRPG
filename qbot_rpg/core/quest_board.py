"""委托板引擎（2c5b QBD/REP/CMD/ANT 主链——/委托 查看/接取/交付 + 声望链）。

文件名：quest_board.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批2路3）

配置源：ctx["quest_board_cfg"]（settings.quest_board 段）：
  {refresh_days: 3, penalty: 0.10, daily_limit: 10, active_limit: 5,
   rep_levels: [["陌生",0],["熟悉",100],["信赖",300],["崇敬",600],["传说",1000]],
   grade_bonus: {S:1.5, A:1.0, B:0.5}, tiers: [委托条目]}
委托条目字段（QBD-03）：{id, name, desc, star(1-5), require{item,count,quality?,trait?},
  rep_base, rep_min(可选), job_level(可选), reward(可选 S 档奖励)}
存档：ctx["quest_board_state"]（persistent_state）：
  {board: [条目(含可用标记)], generated_at, active: {id: {accepted_at, deadline_ts}},
   delivered: [], last_penalty_at}
声望：ctx["reputation_state"]["quest_board"] 值（就地引用 player.reputation_state 落档；
  Player dataclass 字段 Dict[str,int] 按板独立，REP-01/04）。
判定链（REP-07/ANT-04）：三档评价 → 声望入账 → 升阶判定 → S 档奖励——单事务由
调用方（指令壳/入口层）承担；本引擎纯函数零 IO，返回 dict 结果。
"""
from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional

DEFAULT_REP_LEVELS: List[List[Any]] = [
    ["陌生", 0], ["熟悉", 100], ["信赖", 300], ["崇敬", 600], ["传说", 1000],
]
DEFAULT_GRADE_BONUS: Mapping[str, float] = {"S": 1.5, "A": 1.0, "B": 0.5}
_QUALITY_ORDER: Mapping[str, int] = {
    "normal": 0, "普通": 0,
    "fine": 1, "精良": 1,
    "epic": 2, "史诗": 2,
    "legendary": 3, "传说": 3,
}


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------

def cfg_of(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    c = ctx.get("quest_board_cfg")
    return c if isinstance(c, Mapping) else {}


def _cfg(ctx: Mapping[str, Any], key: str, default: Any) -> Any:
    c = cfg_of(ctx)
    return c.get(key, default) if key in c else default


def enabled(ctx: Mapping[str, Any]) -> bool:
    """模块开关（settings.quest_board.enabled；缺省 True）。"""
    c = cfg_of(ctx)
    return c.get("enabled", True) is not False


def tiers_of(ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    c = cfg_of(ctx)
    t = c.get("tiers")
    return [x for x in t if isinstance(x, Mapping)] if isinstance(t, list) else []


def _tiers_enabled(ctx: Mapping[str, Any]) -> bool:
    return bool(tiers_of(ctx))


def rep_levels_of(ctx: Mapping[str, Any]) -> List[List[Any]]:
    c = cfg_of(ctx)
    lv = c.get("rep_levels")
    return lv if isinstance(lv, list) and lv else DEFAULT_REP_LEVELS


def rep_level(ctx: Mapping[str, Any], value: int) -> tuple:
    """声望值 → (档名, 档序 1 起)；值 ≥ 阈值取最高档（REP-04/05 只升不降语义）。"""
    levels = rep_levels_of(ctx)
    name, idx = str(levels[0][0]), 1
    for i, row in enumerate(levels, start=1):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        if value >= int(row[1]):
            name, idx = str(row[0]), i
    return name, idx


def rep_value(ctx: Mapping[str, Any]) -> int:
    """当前声望值（reputation_state["quest_board"]；缺省 0）。"""
    rs = ctx.get("reputation_state")
    if isinstance(rs, Mapping):
        v = rs.get("quest_board", 0)
        return int(v) if isinstance(v, (int, float)) else 0
    return 0


# ---------------------------------------------------------------------------
# 板状态存档容器
# ---------------------------------------------------------------------------

def state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """quest_board_state 读写容器（persistent_state 挂回；缺省新建）。"""
    st = ctx.get("quest_board_state")
    if not isinstance(st, MutableMapping):
        st = {"board": [], "generated_at": 0, "active": {}, "delivered": [],
              "last_penalty_at": 0}
        ctx["quest_board_state"] = st
    return st


# ---------------------------------------------------------------------------
# 板刷新（QBD-02：懒计算——读取时判定周期）
# ---------------------------------------------------------------------------

def _board_refresh(ctx: MutableMapping[str, Any], now: int) -> dict:
    """懒刷新：refresh_days 到期 → 旧板进行中未交付触发惩罚结算（QBD-09）+
    生成新列表。返回 {refreshed, penalty_msgs}。"""
    st = state_of(ctx)
    refresh_days = int(_cfg(ctx, "refresh_days", 3) or 3)
    period = max(1, refresh_days) * 86400
    gen = int(st.get("generated_at", 0) or 0)
    # 未生成过 → 立即生成（首访板）
    if gen == 0:
        st["board"] = [dict(t) for t in tiers_of(ctx)]
        st["generated_at"] = now
        st["last_penalty_at"] = now
        return {"refreshed": True, "penalty_msgs": []}
    if now - gen < period:
        return {"refreshed": False, "penalty_msgs": []}
    # 周期到期：惩罚结算（旧 active 未交付 ×1 次；同批只一次——last_penalty_at 标记）
    penalty_msgs: List[str] = []
    active = st.get("active")
    if isinstance(active, MutableMapping) and active:
        penalty = float(_cfg(ctx, "penalty", 0.10) or 0.0)
        if penalty > 0:
            # 乘法扣减：值 ×(1-penalty)，向下取整（QBD-08/TC-19：105→94）
            rs = ctx.get("reputation_state")
            if isinstance(rs, MutableMapping):
                cur = rep_value(ctx)
                newv = int(cur * (1.0 - penalty))
                rs["quest_board"] = newv
                penalty_msgs.append(f"委托到期未交付：声望 -{cur - newv}（{cur}→{newv}）")
        st["active"] = {}
        st["last_penalty_at"] = now
    # 生成新列表（同配置条目重上架；delivered 保留防重）
    st["board"] = [dict(t) for t in tiers_of(ctx)]
    st["generated_at"] = now
    return {"refreshed": True, "penalty_msgs": penalty_msgs}


# ---------------------------------------------------------------------------
# 板查看（CMD-03）
# ---------------------------------------------------------------------------

def board_view(ctx: MutableMapping[str, Any], now: int) -> dict:
    """板列表（懒刷新先行）。返回 {ok, rows, tip, rep_name, penalty_msgs, disabled}。
    row：{index, name, star, require_txt, rep_base, rep_min, job_level, visible}——
    可见性（REP-08/09）：rep 值 ≥ rep_min 且 job_level 达标；不达标 → 隐藏（目标感）。
    """
    if not enabled(ctx):
        return {"ok": False, "reason": "mode_off", "message": "❌ 委托板未开启",
                "disabled": True}
    if not _tiers_enabled(ctx):
        return {"ok": False, "reason": "no_tiers",
                "message": "委托板：委托任务板没有配置任何委托（配置 quest_board.tiers）",
                "disabled": False, "rows": [], "tip": ""}
    refresh = _board_refresh(ctx, now)
    st = state_of(ctx)
    rows: List[dict] = []
    active = st.get("active")
    active = active if isinstance(active, MutableMapping) else {}
    rep = rep_value(ctx)
    index = 0
    for t in tiers_of(ctx):
        if str(t.get("id")) in active:
            continue  # 进行中不进可接列表
        index += 1
        rep_min = int(t.get("rep_min", 0) or 0)
        job_lv = int(t.get("job_level", 0) or 0)
        visible = rep >= rep_min  # job_level 门槛信息（proficiency 体系未接→仅提示）
        req = t.get("require")
        if isinstance(req, Mapping):
            itm = ctx.get("items")
            nm = None
            if isinstance(itm, Mapping):
                d = itm.get(str(req.get("item")))
                if isinstance(d, Mapping):
                    nm = d.get("name")
            req_txt = f"{nm or req.get('item')}×{req.get('count', 1)}"
            if req.get("quality"):
                qn = req["quality"]
                req_txt += f"（品质≥{qn}）"
            if req.get("trait"):
                req_txt += f"（特性：{req['trait']}）"
        else:
            req_txt = "?"
        rows.append({
            "index": index, "id": str(t.get("id")), "name": str(t.get("name") or t.get("id")),
            "star": int(t.get("star", 1) or 1), "require_txt": req_txt,
            "rep_base": int(t.get("rep_base", 10) or 10),
            "rep_min": rep_min, "job_level": job_lv, "visible": visible,
        })
    rep_name, rep_idx = rep_level(ctx, rep)
    return {"ok": True, "rows": rows, "tip": "/委托 接取 <序号> 领取", "rep_name": rep_name,
            "rep_idx": rep_idx, "rep_value": rep, "penalty_msgs": refresh["penalty_msgs"],
            "active_count": len(active)}


# ---------------------------------------------------------------------------
# 接取（QBD-04 / ANT-02）
# ---------------------------------------------------------------------------

def board_accept(ctx: MutableMapping[str, Any], seq: int, now: int) -> dict:
    """接取板第 seq 条（可见列表序号）。上限 active_limit（默认 5，0=不限）。
    成功 → active[id] = {accepted_at, deadline_ts=now+refresh_days 天}。"""
    if not enabled(ctx):
        return {"ok": False, "reason": "mode_off", "message": "❌ 委托板未开启"}
    if not _tiers_enabled(ctx):
        return {"ok": False, "reason": "no_tiers", "message": "❌ 委托板：没有可接取的委托"}
    _board_refresh(ctx, now)  # 懒刷新（副作用：到期惩罚+换板）
    st = state_of(ctx)
    active = st.get("active")
    if not isinstance(active, MutableMapping):
        active = {}
        st["active"] = active
    limit = int(_cfg(ctx, "active_limit", 5) or 5)
    if limit > 0 and len(active) >= limit:
        return {"ok": False, "reason": "active_full",
                "message": f"❌ 同时进行中的委托已达上限（{limit}），先交付或等截止"}
    view = board_view(ctx, now)
    if not view.get("ok"):
        return {"ok": False, "reason": "no_board", "message": "❌ 委托板：暂无委托"}
    rows = [r for r in view.get("rows", []) if r.get("visible")]
    if seq < 1 or seq > len(rows):
        return {"ok": False, "reason": "out_of_range",
                "message": f"❌ 委托板：序号 {seq} 不存在（当前可接取 {len(rows)} 条）"}
    row = rows[seq - 1]
    tid = str(row["id"])
    if tid in active:
        return {"ok": False, "reason": "dup",
                "message": "❌ 委托板：该委托已在进行中"}
    if not row.get("visible"):
        return {"ok": False, "reason": "rep_locked",
                "message": f"❌ 委托板：声望不足（需要 {row['rep_min']}，当前 {rep_value(ctx)}）"}
    refresh_days = int(_cfg(ctx, "refresh_days", 3) or 3)
    active[tid] = {"accepted_at": now,
                   "deadline_ts": now + max(1, refresh_days) * 86400}
    return {"ok": True, "message": f"✅ 已接取委托：{row['name']}（截止 {refresh_days} 天后）",
            "id": tid, "name": row["name"]}


# ---------------------------------------------------------------------------
# 交付评价（QBD-06 三轴 S/A/B + REP-06 声望）
# ---------------------------------------------------------------------------

def _quality_idx(q: Any) -> int:
    if isinstance(q, (int, float)) and not isinstance(q, bool):
        return int(q)
    return _QUALITY_ORDER.get(str(q), 0)


def evaluate_delivery(ctx: Mapping[str, Any], quest: Mapping[str, Any],
                      row: Mapping[str, Any]) -> dict:
    """三轴评价（QBD-06：品质/特性/数量 → S/A/B）。
    row：背包行（含 item_id/name/count/quality/traits）。
    品质轴：row.quality ≥ require.quality（档位序比较；无门槛 → 达标）
    特性轴：require.trait 在 row.traits 中（无门槛 → 达标）
    数量轴：row.count ≥ require.count
    S=三轴达标且 ≥2 轴超额（品质>1 档或数量 2×）；A=全达标；B=品质不足仍可交（TC-10）。
    """
    req = quest.get("require")
    if not isinstance(req, Mapping):
        return {"grade": "A", "axes": {"quality": True, "trait": True, "count": True},
                "score": 1.0}
    rq = req.get("quality")
    rt = req.get("trait")
    rn = int(req.get("count", 1) or 1)
    axes = {"quality": True, "trait": True, "count": True}
    exceed = 0
    # 行读取鸭子形态（ItemInstance dataclass / dict 通用）
    def _g(row_: Mapping[str, Any], key: str, dflt: Any) -> Any:
        if isinstance(row_, Mapping):
            return row_.get(key, dflt)
        return getattr(row_, key, dflt)
    # 品质
    if rq:
        have_q = _quality_idx(_g(row, "quality", "normal"))
        need_q = _quality_idx(rq)
        axes["quality"] = have_q >= need_q
        if have_q - need_q >= 1:
            exceed += 1
    # 特性
    if rt:
        traits = _g(row, "traits", ()) or ()
        has_rt = isinstance(traits, (list, tuple)) and str(rt) in [str(t) for t in traits]
        axes["trait"] = has_rt
    # 数量
    have_n = int(_g(row, "count", 0) or 0)
    axes["count"] = have_n >= rn
    if have_n >= rn * 2:
        exceed += 1
    if not axes["quality"]:
        # TC-10：品质不足仍可交付 → B 档
        grade = "B"
    elif all(axes.values()) and exceed >= 2:
        grade = "S"
    elif all(axes.values()):
        grade = "A"
    else:
        grade = "B"
    bonus = {**DEFAULT_GRADE_BONUS, **_cfg(ctx, "grade_bonus", {})} if isinstance(
        _cfg(ctx, "grade_bonus", {}), Mapping) else dict(DEFAULT_GRADE_BONUS)
    mult = float(bonus.get(grade, 1.0))
    return {"grade": grade, "axes": axes, "mult": mult}


def board_deliver(ctx: MutableMapping[str, Any], seq: int,
                  item_ref: str, now: int) -> dict:
    """交付：委托编号=进行中委托序号（按 active 添加顺序编 1..n）→ 道具名/编号。
    评价 → 声望入账（rep_base × mult）→ 升阶判定消息 → S 档奖励发放。
    单事务由入口层保证（ANT-04）；本函数纯内存操作 ctx 引用。
    """
    if not enabled(ctx):
        return {"ok": False, "reason": "mode_off", "message": "❌ 委托板未开启"}
    refresh = _board_refresh(ctx, now)
    st = state_of(ctx)
    active = st.get("active")
    active = active if isinstance(active, MutableMapping) else {}
    if not active:
        return {"ok": False, "reason": "no_active", "message": "❌ 委托板：没有进行中的委托"}
    # active 序号 → 委托 id（按接受时间序）
    ordered = sorted(active.items(), key=lambda kv: int(kv[1].get("accepted_at", 0) or 0))
    if seq < 1 or seq > len(ordered):
        return {"ok": False, "reason": "out_of_range",
                "message": f"❌ 委托板：进行中委托编号 {seq} 不存在（当前 {len(ordered)} 单）"}
    tid, _rec = ordered[seq - 1]
    # 找委托条目
    quest = None
    for t in tiers_of(ctx):
        if str(t.get("id")) == tid:
            quest = t
            break
    if quest is None:
        return {"ok": False, "reason": "no_quest", "message": "❌ 委托板：委托不存在"}
    # 背包找道具行（item_id 或名称精确优先 → 前缀唯一）
    inv = ctx.get("inventory")
    # 行列表（ctx["inventory_items"] 实例列表；兼容 ItemInstance dataclass / dict）
    rows_all: List[Any] = []
    ii = ctx.get("inventory_items")
    if isinstance(ii, (list, tuple)):
        rows_all = list(ii)
    if not rows_all:
        pl = ctx.get("player")
        if isinstance(pl, MutableMapping) and isinstance(pl.get("inventory"), (list, tuple)):
            rows_all = list(pl["inventory"])
        elif isinstance(inv, (list, tuple)):
            rows_all = list(inv)

    def _g2(row_: Any, key: str, dflt: Any) -> Any:
        if isinstance(row_, Mapping):
            return row_.get(key, dflt)
        return getattr(row_, key, dflt)

    def _key(row_: Any) -> str:
        return str(_g2(row_, "item_id", "") or "")

    def _name(row_: Any) -> str:
        return str(_g2(row_, "name", "") or "")

    target: Optional[Any] = None
    for r in rows_all:
        if _key(r) == item_ref or _name(r) == item_ref:
            target = r
            break
    if target is None:
        cands = [r for r in rows_all
                 if _name(r).startswith(item_ref) or _key(r).startswith(item_ref)]
        if len(cands) == 1:
            target = cands[0]
        elif len(cands) > 1:
            return {"ok": False, "reason": "ambiguous",
                    "message": f"❌ 委托板：「{item_ref}」匹配多个物品，请用编号（/背包）"}
    if target is None:
        return {"ok": False, "reason": "no_item",
                "message": f"❌ 委托板：背包里没有「{item_ref}」"}
    # 评价
    ev = evaluate_delivery(ctx, quest, target)
    if not ev["axes"]["count"]:
        return {"ok": False, "reason": "count_short",
                "message": f"❌ 委托板：数量不足（需要 {quest.get('require', {}).get('count', 1)}，"
                           f"你有 {target.get('count')}）"}
    # 扣道具（行 count 减；就地改 player.inventory 或 ctx）
    _consume_row(ctx, target, 1)
    # 声望入账（REP-06：rep_base × grade mult）
    rep_base = int(quest.get("rep_base", 10) or 10)
    gain = int(rep_base * ev["mult"])
    rs = ctx.get("reputation_state")
    if not isinstance(rs, MutableMapping):
        rs = {}
        ctx["reputation_state"] = rs
    before = rep_value(ctx)
    rs["quest_board"] = before + gain
    after = before + gain
    # 升阶判定
    lvl_before = rep_level(ctx, before)
    lvl_after = rep_level(ctx, after)
    msgs = [f"✅ 委托完成：{quest.get('name')} {ev['grade']} 档 声望 +{gain}"]
    if lvl_after[1] > lvl_before[1]:
        msgs.append(f"⭐ 升阶：{lvl_before[0]} → {lvl_after[0]}")
    # S 档奖励（REP-10：quest.reward）
    if ev["grade"] == "S":
        rw = quest.get("reward")
        if isinstance(rw, list) and rw:
            for g in rw:
                if isinstance(g, Mapping) and g.get("item"):
                    _grant_item(ctx, g)
                    gname = str(g.get("item"))
                    itab = ctx.get("items")
                    if isinstance(itab, Mapping):
                        d = itab.get(gname)
                        if isinstance(d, Mapping) and d.get("name"):
                            gname = str(d.get("name"))
                    msgs.append(f"奖励：{gname}×{g.get('count', 1)}")
    # 记录防重（ANT-05）
    delivered = st.get("delivered")
    if not isinstance(delivered, list):
        delivered = []
        st["delivered"] = delivered
    delivered.append(tid)
    active.pop(tid, None)
    # 惩罚消息（刷新触发）
    if refresh["penalty_msgs"]:
        msgs = refresh["penalty_msgs"] + msgs
    return {"ok": True, "message": "\n".join(msgs), "grade": ev["grade"],
            "gain": gain, "rep_value": after, "delivered": tid}


def _consume_row(ctx: MutableMapping[str, Any], row: Any, n: int) -> None:
    """扣道具（ctx hooks remove_item——装配层 hook 改计数映射 + 标 _m8_dirty_inventory
    落档 merge；按 id 扣 n，评价已先行保证目标行品质/数量达标）。"""
    def _key(row_: Any) -> str:
        if isinstance(row_, Mapping):
            return str(row_.get("item_id", "") or "")
        return str(getattr(row_, "item_id", "") or "")
    rm = ctx.get("remove_item") if hasattr(ctx, "get") else None
    if callable(rm):
        rm(_key(row), n)
        return
    # 兜底：计数映射就地扣
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        iid = _key(row)
        have = int(inv.get(iid, 0) or 0)
        if have <= n:
            inv.pop(iid, None)
        else:
            inv[iid] = have - n


def _grant_item(ctx: MutableMapping[str, Any], g: Mapping[str, Any]) -> None:
    """S 档奖励入包（ctx hooks add_item——落档 merge 自动；带 quality/traits）。"""
    add = ctx.get("add_item") if hasattr(ctx, "get") else None
    if callable(add):
        add(str(g.get("item")), int(g.get("count", 1) or 1))
        return
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        iid = str(g.get("item"))
        inv[iid] = int(inv.get(iid, 0) or 0) + int(g.get("count", 1) or 1)


__all__ = [
    "board_view", "board_accept", "board_deliver", "evaluate_delivery",
    "rep_level", "rep_value", "state_of", "cfg_of", "enabled",
    "DEFAULT_REP_LEVELS", "DEFAULT_GRADE_BONUS",
]
