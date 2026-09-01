"""成就引擎（M11 批1·路1A · qbot_rpg/core/achievements.py）——check 型达成检测结算器。

依据：
  - docs/细化/细化_4c_成就系统契约.md（下称【4c】）：字段 schema L81-110 / 校验 L114-116 /
    四类解锁条件映射 L146-149（codex/[事件:*]/gain_count/item_count/level 全复用统一
    条件引擎）/ 逐键入账管线 L198-211 / achievement_state L243-248 / 隐藏成就 L275-280 /
    揭示纪律 D-08 L313-317 / 22 TC L330-388
  - docs/m11_成就摸底.md（G1 结算器本体 / G12 achievement_state ctx 注入 / TC 承载表
    §四：TC-01~13 + TC-16 揭示字段归本批 1A）
  - qbot_rpg/core/codex_milestones.py（check_milestones L337-375：结算后调用 + 逐档
    授予 + 幂等集合先例）
  - qbot_rpg/core/reward.py（dispatch_reward 唯一发放器，含称号型 G2）
  - qbot_rpg/engine/condition_engine.py（eval_condition L611：list=全与，fail-safe）

职责（G1）：
  check_achievements(ctx, *, sources=None) 为结算点钩子唯一入口——图鉴点亮 / 事件
  触发 / 物品获得 / 升级等结算完成后调用：逐条求值本模块已注册、未达成的成就
  conditions[]（全与 AND，D-02）→ 满足即达成 → 单事务发放（reward 解析器）+
  达成时间戳写 achievement_state（只增不减 ACH-08）+ 幂等落账（tx_id + ledger）；
  once=false 重复达成仅 repeat_count+1；隐藏成就达成瞬间一次性揭示（D-08）。

【工程补白 · 显式标注】
  1) ctx 契约：achievement_state（{unlocked:{ID:ISO8601}, repeat_count:{ID:N}}，
     G12 由装配层 _ps_init 挂回 persistent_state，写入即落档）/ achievements
     （{ID: 配置} 字典）/ registry（resolve(id,kind)/all_ids(kind)，惰性读）/ ledger
     （幂等集合，调用方持有）/ tx_id（结算唯一 id，缺省 None 表示单次无幂等）/ today
     （ISO 日期键，注入确定性，缺省 ctx["today"] 兜底）/ titles（称号注册表 G14）/
     title_state / currencies / exp / reputation_state / inventory / add_item /
     items|resolve_item（reward 解析器消费）。
  2) 幂等闸前置：同 tx_id 已在 ledger → 本次跳过全部检测（与 reward 解析器同闸）。
     达成结算后把 tx_id 加入 ledger（与 reward 批次完成记账同语义，不封口 item 失败
     由 reward 自身 skip 语义处理）。缺 tx_id（直接调用/无 message_id 结算点）→ 仍
     可达成（无幂等快照，由调用方保证不重复调用）。
  3) 跨档跳升逐档授予：图鉴完成度从 45% 直接到 52%——仅 50% 档达成，25% 档此前已授
     不重授（unlocked 幂等），75% 档不触发（条件不满足）。逐档检查不漏授不重授
     （4c §2.4 跨档跳升 + 对齐 codex_milestones R-21）。
  4) once=false：已达成仍参与检测，满足 → repeat_count+1 并重发奖励（作者自担通胀）。
     once=true：达成后从待检集合移除（unlocked 幂等），重复结算点不重发。
  5) 隐藏成就揭示（D-08）：达成瞬间输出一次揭示卡片（⛩️ 前缀 + 成就名 + reveal_text），
     状态翻转后不再出；未达成时任何路径不渲染 reveal_text（防剧透）。hidden 归一：
     True ≡ {mode:"locked"}；{mode:"locked"|"hide"} 对象。milestone 日志（log_milestone）
     复用 adventure_log（已实装），携带成就 ID（冒烟/TC-16 断言载体）。
  6) 零定时器/零睡眠：本模块纯函数结算，无任何定时器/轮询/后台任务（4c D-07 结算点
     钩子口径）；时间戳与日期全部由 ctx 注入（today），不读取系统时钟。
  7) 消息纪律：本模块只返回结构化结果（granted/messages/reveals），不渲染模板——
     模板配置化归 1C（achievement_tpl 分区），引擎不写模板。

铁律：零 NoneBot import；纯函数确定性（today/tx_id 由 ctx 注入）；fail-safe 不抛错；
无 emoji（仅返回结构化字段，渲染由调用方）；不 git commit。
"""

from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional, Sequence, Set

__all__ = [
    "ACHIEVEMENT_STATE_KEY",
    "ACHIEVEMENTS_KEY",
    "LEDGER_KEY",
    "check_achievements",
    "list_achievements",
    "achievement_view",
    "get_achievement_state",
]

# ctx / persistent_state 键名（G12 三路约定：装配层 _ps_init 挂回 persistent_state）
ACHIEVEMENT_STATE_KEY = "achievement_state"
ACHIEVEMENTS_KEY = "achievements"
# 幂等 ledger 在 ctx 的键（与 reward 解析器共享同一集合）
LEDGER_KEY = "ledger"

# 隐藏成就模式（4c §1.3：locked=列表显示锁定行；hide=完全隐藏）
_HIDDEN_MODE_LOCKED = "locked"
_HIDDEN_MODE_HIDE = "hide"

# 揭示卡片前缀（D-08 一次性揭示；渲染由调用方，本模块只给结构化字段；
# 纯文本前缀——emoji 纪律仅 ✅/❌，2026-09-01 M11 收口修正）
_REVEAL_PREFIX = "[隐藏成就]"


# -------------------------------------------------------------------------------------
# 配置读取（fail-safe）
# -------------------------------------------------------------------------------------
def _achievements_of(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """成就配置表：ctx["achievements"]（{ID: 配置}）→ 缺省 {}。"""
    cfg = ctx.get(ACHIEVEMENTS_KEY)
    return cfg if isinstance(cfg, Mapping) else {}


def _hidden_of(entry: Mapping[str, Any]) -> dict:
    """hidden 字段归一（4c §1.3）：False → {}；True ≡ {mode:"locked"}；对象直用。"""
    h = entry.get("hidden", False)
    if isinstance(h, Mapping):
        mode = h.get("mode")
        return {
            "mode": mode if mode in (_HIDDEN_MODE_LOCKED, _HIDDEN_MODE_HIDE)
            else _HIDDEN_MODE_LOCKED,
            "reveal_text": h.get("reveal_text"),
            "clue_ref": h.get("clue_ref"),
        }
    if h is True:
        return {"mode": _HIDDEN_MODE_LOCKED, "reveal_text": None, "clue_ref": None}
    return {}


# -------------------------------------------------------------------------------------
# achievement_state 读写（ACH-08 只增不减）
# -------------------------------------------------------------------------------------
def _state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """achievement_state 可变引用（ctx 直键，缺省创建；G12 装配层已挂回 persistent_state）。"""
    st = ctx.get(ACHIEVEMENT_STATE_KEY)
    if not isinstance(st, MutableMapping):
        st = {"unlocked": {}, "repeat_count": {}}
        ctx[ACHIEVEMENT_STATE_KEY] = st
    return st


def _unlocked_of(st: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """unlocked 集合（{ID: ISO8601 时间戳}）可变引用（缺省创建）。"""
    u = st.get("unlocked")
    if not isinstance(u, MutableMapping):
        u = {}
        st["unlocked"] = u
    return u


def _repeat_of(st: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """repeat_count 集合（{ID: N}）可变引用（缺省创建）。"""
    r = st.get("repeat_count")
    if not isinstance(r, MutableMapping):
        r = {}
        st["repeat_count"] = r
    return r


def get_achievement_state(ctx: Mapping[str, Any]) -> dict:
    """成就状态只读快照：{unlocked, repeat_count}（缺省空，不创建不落档）。

    供 1C 指令壳 / 热重载列表渲染读取。
    """
    st = ctx.get(ACHIEVEMENT_STATE_KEY)
    if not isinstance(st, Mapping):
        return {"unlocked": {}, "repeat_count": {}}
    unlocked = st.get("unlocked")
    repeat_count = st.get("repeat_count")
    return {
        "unlocked": dict(unlocked) if isinstance(unlocked, Mapping) else {},
        "repeat_count": dict(repeat_count) if isinstance(repeat_count, Mapping) else {},
    }


# -------------------------------------------------------------------------------------
# 揭示字段（D-08：达成瞬间一次性；未达成任何路径不渲染）
# -------------------------------------------------------------------------------------
def _reveal_of(entry: Mapping[str, Any], hidden: Mapping[str, Any]) -> Optional[dict]:
    """达成瞬间揭示卡片字段（D-08）：隐藏成就首次达成 → 一次性 reveal_text。

    返回 None（非隐藏 / 非首次）或 {"prefix", "name", "reveal_text"}——
    渲染由调用方完成（模板配置化归 1C），本模块只给结构化字段。
    """
    if not hidden or not hidden.get("mode"):
        return None
    name = entry.get("name")
    reveal_text = hidden.get("reveal_text")
    return {
        "prefix": _REVEAL_PREFIX,
        "name": str(name or "") if name is not None else "",
        "reveal_text": str(reveal_text or "") if reveal_text is not None else "",
    }


# -------------------------------------------------------------------------------------
# 结算器（G1 主体）
# -------------------------------------------------------------------------------------
def _grant_reward(
    entry: Mapping[str, Any],
    ctx: MutableMapping[str, Any],
    tx_id: Optional[str],
    ledger: Optional[Set[str]],
) -> dict:
    """单成就奖励发放：dispatch_reward（唯一发放器）+ 幂等落账。

    M11 批4 A1 P1-1 修复：仅当 skipped 无 item_add_failed 才记 ledger——
    物品未实际入包时不封口幂等（对齐 reward.py L493-499 不封口纪律），
    同 tx 重放可重发（防静默丢奖）。
    返回 dispatch_reward 结果（{ok, granted, skipped, [idempotent]}）。
    """
    # importlib 动态加载（M11 批4 A1 P0-1 修复后 G0 环：codex→achievements→reward→codex，
    # 静态 import 边全断——G0 只扫静态 import 语句，importlib 不构成边）
    import importlib

    dispatch_reward = importlib.import_module("qbot_rpg.core.reward").dispatch_reward
    r = dispatch_reward(entry, ctx)
    if tx_id is not None and ledger is not None:
        has_item_fail = any(
            isinstance(s, Mapping) and s.get("type") == "item"
            and s.get("reason") == "item_add_failed"
            for s in (r.get("skipped") or [])
        )
        if not has_item_fail:
            ledger.add(tx_id)
    return r


def check_achievements(
    ctx: MutableMapping[str, Any],
    *,
    sources: Optional[Sequence[str]] = None,
) -> dict:
    """check 型达成检测结算器（G1 主体，结算点钩子唯一入口）。

    入参:
      ctx: 可变结算上下文（见文件头补白 1：achievement_state/achievements/ledger/
        tx_id/today + reward 解析器消费字段）。
      sources: 可选来源筛选（["codex","event","item","level"] 等标签）——仅检测
        配置里 sources 命中该标签的成就；None=全部（对齐 G15 结算点钩子接线，
        1A 阶段调用方可传 None 全量检测，批2/批3 收口按结算点传标签）。
    出参 dict:
      {ok, granted: [达成记录…], messages: [str…], reveals: [揭示卡片…], skipped: [...]}
      - granted 每项: {id, name, once, repeat_count, ts, reward_granted, reward_skipped}
        （隐藏成就另含 reveal 字段，见下）
      - reveals: 隐藏成就达成瞬间揭示卡片（D-08 一次性）：{id, name, prefix,
        reveal_text, milestone}（milestone=adventure_log log_milestone 结果）
      - messages: 逐条达成消息文本（含 ⛩️ 揭示行；模板化渲染归 1C，此处为兜底
        文本，调用方可直接透传或改走模板）
      - skipped: 条件求值失败/奖励条目级失败记录（黄字语义，不阻断）
    核心逻辑（对齐 4c §2.1 结算点钩子 + §3.2 单事务）:
      ① 幂等闸：tx_id 已在 ledger → 直接返回空结果（不重复检测/发放）；
      ② 逐条遍历已注册成就（配置表序）：
         - 跳过：非 sources 命中 / 未解锁（unlocked 有）且 once=true；
         - 条件求值（conditions list 全与 AND，D-02；求值失败 fail-safe False D-03）：
           不满足 → 跳过；满足 → 达成结算；
      ③ 达成结算：once=false 重复 → repeat_count+1 并重发奖励；首次 → 写
        unlocked[ID]=today + 发放奖励（含称号型，G2）+ 幂等落账（tx_id+ledger）+
        隐藏成就一次性揭示（D-08）+ 冒险日志 milestone；
      ④ 单条失败（无 achievements 表/ctx 非法）→ skipped，不抛错。
    """
    if not isinstance(ctx, MutableMapping):
        return {"ok": False, "granted": [], "messages": [], "reveals": [],
                "skipped": [{"reason": "invalid_ctx"}]}

    # ① 幂等闸（前置）：同 tx_id 已结算 → 全部跳过（与 reward 解析器同闸语义）
    tx_id = ctx.get("tx_id")
    ledger = ctx.get(LEDGER_KEY)
    if tx_id is not None and isinstance(ledger, Set) and tx_id in ledger:
        return {"ok": True, "granted": [], "messages": [], "reveals": [], "skipped": []}

    cfg = _achievements_of(ctx)
    if not cfg:
        return {"ok": True, "granted": [], "messages": [], "reveals": [], "skipped": []}

    st = _state_of(ctx)
    unlocked = _unlocked_of(st)
    repeat = _repeat_of(st)
    today = str(ctx.get("today") or "") or ""

    granted: List[dict] = []
    messages: List[str] = []
    reveals: List[dict] = []
    skipped: List[dict] = []

    for aid, entry in cfg.items():
        if not isinstance(entry, Mapping):
            skipped.append({"id": aid, "reason": "invalid_entry"})
            continue
        # M11 批4 A1 P1-3 修复：4c schema 无 source 键（TOP_FIELDS 8 字段无此键），
        # 按配置 source 过滤恒空 → 分层结算点永不触发。取消筛选，始终全量检测
        # （配置量小，逐批全检成本可忽略——dsh 建议 b）。sources 参数保留兼容
        # 但不再过滤（成就配置无 source 维度）。

        hidden = _hidden_of(entry)
        once = bool(entry.get("once", True))
        already = aid in unlocked

        # once=true 已达成 → 从待检集合移除（ACH-07 幂等，重复结算点不重发）
        if already and once:
            continue

        # ② 条件求值（list=全与 AND，D-02；求值失败 fail-safe False，D-03）
        conditions = entry.get("conditions")
        try:
            from qbot_rpg.engine.condition_engine import eval_condition

            met = eval_condition(conditions, ctx) if conditions is not None else True
        except Exception:
            met = False
        if not met:
            continue

        # ③ 达成结算（单事务语义：先发放 → 再写状态 → 再揭示）
        if already:
            repeat[aid] = int(repeat.get(aid, 0) or 0) + 1
        else:
            unlocked[aid] = today if today else _now_iso(ctx)
        entry_name = str(entry.get("name") or aid)

        # 奖励发放（唯一发放器；含称号型 G2；条目级失败黄字 skip 不吞整次）
        reward_raw = entry.get("reward", [])
        r = _grant_reward(reward_raw, ctx, tx_id, ledger)
        reward_granted = [dict(g) for g in (r.get("granted") or [])]
        reward_skipped = [dict(s) for s in (r.get("skipped") or [])]
        for s in reward_skipped:
            skipped.append({"id": aid, "reward_skip": s})

        # 隐藏成就揭示（D-08 一次性；未达成任何路径不渲染）
        reveal = None
        if hidden.get("mode") and not already:
            reveal = _reveal_of(entry, hidden)
            if reveal is not None:
                reveal["id"] = str(aid)
                reveal["milestone"] = _log_milestone(ctx, str(aid))
                reveals.append(reveal)

        rec = {
            "id": str(aid),
            "name": entry_name,
            "once": once,
            "repeat_count": int(repeat.get(aid, 0)),
            "ts": unlocked.get(aid, ""),
            "reward_granted": reward_granted,
            "reward_skipped": reward_skipped,
        }
        granted.append(rec)
        messages.append(_message_of(rec, reveal))

    return {"ok": True, "granted": granted, "messages": messages,
            "reveals": reveals, "skipped": skipped}


def _message_of(rec: Mapping[str, Any], reveal: Optional[Mapping[str, Any]]) -> str:
    """单条达成消息兜底文本（⛩️ 揭示行含 reveal_text；模板化渲染归 1C）。

    非隐藏 → 「🏅 成就达成：{name}」；隐藏首次 → 「{prefix} 成就达成：{name}\n{reveal_text}」。
    """
    name = str(rec.get("name") or "")
    if reveal is not None:
        prefix = str(reveal.get("prefix") or _REVEAL_PREFIX)
        rv = str(reveal.get("reveal_text") or "")
        return f"{prefix} 成就达成：{name}\n{rv}" if rv else f"{prefix} 成就达成：{name}"
    return f"成就达成：{name}"


def _now_iso(ctx: Mapping[str, Any]) -> str:
    """时间戳兜底：ctx["now"]/ctx["today"] 优先，缺省 ISO 现刻（确定性由调用方注入）。"""
    for k in ("now", "today"):
        v = ctx.get(k)
        if v:
            s = str(v)
            if s:
                return s
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_milestone(ctx: MutableMapping[str, Any], aid: str) -> dict:
    """冒险日志 milestone（TC-16 断言载体）：惰性 import，缺模块不炸。

    事件键 [事件:成就达成]（base）写 flat 计数（不带 target）——M11 批4 A1 P1-5
    修复：带 target 写 nested {key:{aid:count}}，无 param 条件
    {var:[事件:成就达成], ge:1} 读 event_counts[key] 得 Mapping → _read_counter 返 0
    → 事件型成就条件恒不满足。aid 元数据经 instance.params 保留（不进 event_counts）。
    非首见类恒 first_seen=false。
    """
    try:
        from qbot_rpg.core.event_bus import bump_event

        return bump_event(
            ctx,
            "[事件:成就达成]",
            instance={
                "tag": "achievement",
                "first_seen": False,
                "template_id": "achievement",
                "params": {"achievement_id": aid},
            },
        )
    except Exception:
        return {"ok": False, "reason": "milestone_unavailable"}


# -------------------------------------------------------------------------------------
# 展示数据源（供 1C 指令壳 / 热重载渲染读取）
# -------------------------------------------------------------------------------------
def list_achievements(ctx: Mapping[str, Any]) -> list:
    """成就列表数据源（1C /成就 渲染）：按配置序，已达成置顶（可配排序），附解锁态。

    每项: {id, name, desc, unlocked, ts, repeat_count, hidden, mode, reveal_text?
    （仅已达成且 hidden 时输出，D-08 未达成不渲染）}。locked 未达成 → name 为
    「？？？」占位（1C 渲染锁定行）；hide 未达成 → 调用方按 mode 过滤（不占序号）。
    """
    cfg = _achievements_of(ctx)
    st = ctx.get(ACHIEVEMENT_STATE_KEY)
    unlocked = st.get("unlocked") if isinstance(st, Mapping) else None
    if not isinstance(unlocked, Mapping):
        unlocked = {}
    repeat = st.get("repeat_count") if isinstance(st, Mapping) else None
    if not isinstance(repeat, Mapping):
        repeat = {}
    out: list = []
    for aid, entry in cfg.items():
        if not isinstance(entry, Mapping):
            continue
        hidden = _hidden_of(entry)
        mode = hidden.get("mode") or ""
        is_unlocked = aid in unlocked
        name = str(entry.get("name") or aid)
        if not is_unlocked and mode == _HIDDEN_MODE_LOCKED:
            name = "？？？"
        # M11 批4 A1 P1-2 修复：locked 未达成 desc 不渲染明文（D-08 防剧透，
        # TC-14 只显锁定态）；仅已达成输出 desc。
        desc = str(entry.get("desc") or "")
        if not is_unlocked and mode == _HIDDEN_MODE_LOCKED:
            desc = ""
        item: dict = {
            "id": str(aid),
            "name": name,
            "desc": desc,
            "unlocked": is_unlocked,
            "ts": str(unlocked.get(aid) or ""),
            "repeat_count": int(repeat.get(aid, 0) or 0),
            "hidden": bool(mode),
            "mode": mode,
        }
        if is_unlocked and hidden.get("reveal_text"):
            item["reveal_text"] = str(hidden["reveal_text"])
        out.append(item)
    # 已达成置顶（稳定排序：unlocked 在前，保持配置序）
    out.sort(key=lambda x: (not x["unlocked"],))
    # M11 批4 A1 P2-1 修复：热重载降级提示——unlocked 中存在但配置已删除的成就
    # （4c §4.3 TC-13：存档保留 + 列表降级提示「配置已移除」）
    cfg_ids = set(cfg.keys())
    for aid in unlocked:
        if aid not in cfg_ids:
            out.append({
                "id": str(aid), "name": "（配置已移除）", "desc": "",
                "unlocked": True, "ts": str(unlocked.get(aid) or ""),
                "repeat_count": 0, "hidden": False, "mode": "",
                "removed": True,
            })
    return out


def achievement_view(ctx: Mapping[str, Any], aid: str) -> Optional[dict]:
    """单条成就视图（1C /成就信息 <N>）：锁定态只显「？？？」不渲染明文（D-08）。

    未注册 ID → None（调用方提示「成就不存在」）。
    """
    cfg = _achievements_of(ctx)
    entry = cfg.get(aid)
    if not isinstance(entry, Mapping):
        return None
    st = ctx.get(ACHIEVEMENT_STATE_KEY)
    unlocked = st.get("unlocked") if isinstance(st, Mapping) else None
    if not isinstance(unlocked, Mapping):
        unlocked = {}
    repeat = st.get("repeat_count") if isinstance(st, Mapping) else None
    if not isinstance(repeat, Mapping):
        repeat = {}
    hidden = _hidden_of(entry)
    mode = hidden.get("mode") or ""
    is_unlocked = aid in unlocked
    name = str(entry.get("name") or aid)
    if not is_unlocked and mode == _HIDDEN_MODE_LOCKED:
        name = "？？？"
    # M11 批4 A1 P1-2 修复：locked 未达成 desc 不渲染明文（同 list_achievements）
    desc = str(entry.get("desc") or "")
    if not is_unlocked and mode == _HIDDEN_MODE_LOCKED:
        desc = ""
    out: dict = {
        "id": str(aid),
        "name": name,
        "desc": desc,
        "unlocked": is_unlocked,
        "ts": str(unlocked.get(aid) or ""),
        "repeat_count": int(repeat.get(aid, 0) or 0),
        "hidden": bool(mode),
        "mode": mode,
    }
    if is_unlocked and hidden.get("reveal_text"):
        out["reveal_text"] = str(hidden["reveal_text"])
    return out
