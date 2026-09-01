"""图鉴里程碑阶梯 + 100% 收集闭环（codex_milestones.py · M7 BCH-08 · F-12/F-13 · R-20/R-21/E-05）。

依据：
  - docs/细化/细化_3f_单机向体验.md：
    · R-20（4.4 闭环驱动链）：100% 图鉴包含隐藏要素条目 → 阶梯里程碑推进 →
      100% 收藏家称号 → 消息前缀 [称号] 展示
    · R-21（4.5 授予链与幂等）：每次图鉴点亮事件结算时检查补全；五档里程碑
      25/50/75/90/100，跨档跳升逐档检查（如 45%→52% 只授予 50% 档）；
      授予幂等（D-07，已授予不重复授予）
    · R-18（4.2 里程碑阶梯）：90% desc 软锚「全收集还有更深处」为唯一明示例外
    · R-19（4.3 100% 专属奖励三件套）：收藏家称号（title_state 可佩戴）+
      世界之书（本批承载为冒险日志聚合段「世界之书」完整传记段）+
      隐藏神龛解锁（本批落 persistent_state["hidden_shrine"]，BCH-09/F-16 消费）
  - docs/细化/细化_M7_交互补全总纲.md ADR-10（F-12 成就接缝裁定）：
    · 里程碑完成度计算/五档触发/90% 软锚/称号/三件套归 M7（本模块）
    · 阶梯成就记录（4c 成就系统）递延 M11，M7 登记 DELAYED——本批用
      称号位（title_state）+ 冒险日志（log_milestone）承载，M11 成就引擎
      接管时迁移（工程补白见下）
  - qbot_rpg/core/adventure_log.py（log_milestone/read_log/ADVENTURE_LOG_TAGS，
    真实签名已 read 核对）、qbot_rpg/core/event_bus.py（bump_event 三表，
    真实签名已 read 核对）、qbot_rpg/assembly/context.py（title_state → ctx["title"]
    → 前缀 [称号] 渲染；_current_title 读 current/title 键，真实形态已 read 核对）

职责：
  check_milestones 为图鉴引擎/装配层提供唯一检查触发入口（mark_seen 结算后调用）：
  图鉴完成度达 25/50/75/90/100 各触发一次里程碑事件（{milestone, pct, message}）；
  25/50/75/90 授予称号位（收藏新手/收藏家/资深收藏家/收藏大师）；100 三件套
  （收藏家称号 + 世界之书聚合段 + 隐藏神龛条目）；全部经 persistent_state
  已授予集合幂等（每档只授一次，重复达档不重授，升级可覆盖称号低→高）。

【工程补白 · 显式标注】
  1) 兄弟路 codex.py（图鉴引擎，F-11 分册聚合+加权完成度）未落盘/只读勿改：
     本模块完成度读取 = ctx["codex"]（全局 pct 标量，兄弟路维护）优先，
     惰性 import qbot_rpg.core.codex.codex_progress 兜底（ImportError 等 →
     0），绝不直接探查/修改兄弟路文件。
  2) ADR-10 成就递延登记：本批五档里程碑与 100% 三件套**不落 4c 成就系统**
     （M11 实现）；承载 = 称号位 title_state["current"]（装配层 _current_title
     读取 → ctx["title"] → 前缀 [称号] 渲染）+ 冒险日志 log_milestone
     （[事件:里程碑:{pct}]）+ persistent_state["hidden_shrine"]。M11 成就引擎
     接管时据此迁移（granted 集合 + title_state 即迁移源）。
  3) 世界之书（R-19 三件套第 2 件）本批承载 = 冒险日志聚合段：从 event_log
     读全部六类（ADVENTURE_LOG_TAGS 固定组序）生成「世界之书」完整传记段
     （结构化 categories + total）。唯一物品（inventory 唯一标记）落位待
     BCH-09/F-16 或物品系统批次（D-01 零新存储纪律，本批不新增存储）。
  4) 隐藏神龛（R-19 三件套第 3 件）本批只落 persistent_state["hidden_shrine"]
     = true 标记，商店 event 条目解锁（2b3 复用）由 BCH-09/F-16 消费。
  5) 90% 软锚（R-18 唯一明示例外）：90% 档 message 显式含「全收集还有更深处」，
     其余档位零明示。
  6) 纯函数确定性：today 由入参注入（None → ctx["today"] → 兜底）；event_log
     /persistent_state 读写全部走 ctx 容器（含 player.persistent_state 兜底，
     对齐 adventure_log._persistent_state_of 口径）。

铁律：零 NoneBot import；纯函数确定性（today ctx 注入）；每函数 docstring；
无 emoji；不 git commit。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, cast

from qbot_rpg.core.adventure_log import ADVENTURE_LOG_TAGS, log_milestone
from qbot_rpg.core.event_bus import EVENT_LOG_KEY

__all__ = [
    "MILESTONE_DEFS",
    "MILESTONE_PCTS",
    "COLLECTOR_TITLE",
    "CODE_X_MILESTONES_KEY",
    "HIDDEN_SHRINE_KEY",
    "check_milestones",
]

# -------------------------------------------------------------------------------------
# 里程碑五档（R-20：25/50/75/90/100，升序 = 跨档连升逐档触发序）
# 称号位（title_state["current"]）：25 收藏新手 / 50 收藏家 / 75 资深收藏家 /
# 90 收藏大师 / 100 收藏家（最终三件套称号，覆盖 90 档收藏大师）
# -------------------------------------------------------------------------------------
MILESTONE_DEFS: tuple = (
    {"pct": 25, "tier": "收藏新手",
     "message": "图鉴完成度达到 25%，获得称号「收藏新手」"},
    {"pct": 50, "tier": "收藏家",
     "message": "图鉴完成度达到 50%，称号晋升「收藏家」"},
    {"pct": 75, "tier": "资深收藏家",
     "message": "图鉴完成度达到 75%，称号晋升「资深收藏家」"},
    {"pct": 90, "tier": "收藏大师",
     "message": "图鉴完成度达到 90%，称号晋升「收藏大师」。全收集还有更深处"},
    {"pct": 100, "tier": "收藏家",
     "message": "图鉴完成度达到 100%，获得称号「收藏家」、世界之书与隐藏神龛"},
)

MILESTONE_PCTS: tuple = tuple(int(d["pct"]) for d in MILESTONE_DEFS)

# 100% 三件套称号（R-19 第 1 件）
COLLECTOR_TITLE = "收藏家"

# 幂等存储（E-05 / D-07）：persistent_state["codex_milestones"] = 已授予档位集合
CODE_X_MILESTONES_KEY = "codex_milestones"

# 隐藏神龛标记（R-19 第 3 件；BCH-09/F-16 商店 event 条目解锁消费）
HIDDEN_SHRINE_KEY = "hidden_shrine"

# 六类中文组名（世界之书聚合段展示；对齐 R-03 固定组序）
_TAG_NAMES: dict = {
    "first_kill": "首杀",
    "first_crown": "首钓冠级",
    "story_node": "剧情节点",
    "hidden_find": "隐藏发现",
    "milestone": "里程碑",
    "codex_new": "图鉴新增",
}


# -------------------------------------------------------------------------------------
# 内部小工具（均纯函数确定性）
# -------------------------------------------------------------------------------------
def _persistent_state_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """持久化容器定位（写幂等集合/隐藏神龛/世界之书记录用）。

    入参 ctx: 上下文。出参 MutableMapping 或 None。
    核心逻辑: ctx["persistent_state"] → ctx["player"].persistent_state（Mapping 或
    对象属性）→ ctx 自身（裸测试容器兜底，对齐 adventure_log._persistent_state_of
    口径）；全部非可变 → None（不抛异常，授予跳过）。
    """
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = ctx.get("player")
    if isinstance(player, Mapping):
        ps2 = player.get("persistent_state")
        if isinstance(ps2, MutableMapping):
            return ps2
    elif player is not None:
        ps2 = getattr(player, "persistent_state", None)
        if isinstance(ps2, MutableMapping):
            return ps2
    if isinstance(ctx, MutableMapping):
        return ctx
    return None


def _granted_of(ps: Mapping[str, Any]) -> set:
    """已授予档位集合（E-05 幂等读）：persistent_state["codex_milestones"]。

    入参 ps: 持久化容器。出参 set[str]（档位 pct 字符串）。
    核心逻辑: list/tuple/set/frozenset 直读；Mapping 形态（含 granted 键的
    字典升级形态）取 granted；其它 → 空集（不抛异常）。
    """
    raw = ps.get(CODE_X_MILESTONES_KEY)
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(x) for x in raw}
    if isinstance(raw, Mapping):
        g = raw.get("granted")
        if isinstance(g, (list, tuple, set, frozenset)):
            return {str(x) for x in g}
    return set()


def _record_grant(ps: MutableMapping[str, Any], pct: int) -> None:
    """授予落账（E-05）：已授予集合加档并回写（按数值升序，JSON 可序列化）。

    入参 ps: 持久化容器；pct: 达成档位。出参 None（就地改写）。
    核心逻辑: 读集合 → 加档 → 按 int 升序转 list 回写。
    """
    granted = _granted_of(ps)
    granted.add(str(pct))
    try:
        ps[CODE_X_MILESTONES_KEY] = sorted(granted, key=lambda s: int(s))
    except (TypeError, ValueError):
        ps[CODE_X_MILESTONES_KEY] = sorted(granted)


def _write_title(ctx: MutableMapping[str, Any], tier: str) -> bool:
    """称号位写入（R-19 第 1 件 + R-21 升级覆盖）：title_state["current"] = 档位称号。

    入参 ctx: 可变上下文；tier: 档位称号（收藏新手/…/收藏大师/收藏家）。
    出参 bool（是否实际写入称号位）。
    核心逻辑: 定位 player.title_state（Mapping 或对象属性，缺失则仅对 dict
    player 补建）→ 写 current 键（低→高覆盖）；同时回写 ctx["title"]（当前
    会话前缀 [称号] 渲染即时生效）；无称号位 → False（不抛异常，授予记录
    title_written=false 显式标注）。
    """
    player = ctx.get("player")
    ts: Optional[MutableMapping[str, Any]] = None
    if isinstance(player, Mapping):
        raw = player.get("title_state")
        if isinstance(raw, MutableMapping):
            ts = raw
        elif raw is None and isinstance(player, MutableMapping):
            ts = {}
            player["title_state"] = ts
    elif player is not None:
        raw = getattr(player, "title_state", None)
        if isinstance(raw, MutableMapping):
            ts = raw
    if ts is None:
        return False
    ts["current"] = str(tier)
    if isinstance(ctx, MutableMapping):
        ctx["title"] = str(tier)
    return True


def _read_pct(ctx: Mapping[str, Any]) -> float:
    """图鉴完成度读取（ctx["codex"] 标量优先，codex_progress 惰性兜底）。

    入参 ctx: 上下文。出参 float（0-100 夹取；任何缺失/非法 → 0）。
    核心逻辑: ctx["codex"] 数值化（int/float/str 均可）；缺失 → 惰性 import
    codex_progress(ctx) 兜底；越界夹取 0-100。
    M11 批2 路2B（G-17）：float 精确值不 int 截断——COD-08 里程碑判定用未取整值。
    """
    raw = ctx.get("codex")
    if raw is None:
        try:
            from qbot_rpg.core.codex import codex_progress as _codex_progress

            if callable(_codex_progress):
                _r = _codex_progress(cast(MutableMapping, ctx))
                if isinstance(_r, Mapping):
                    raw = _r.get("pct")
                else:
                    raw = _r
        except Exception:
            raw = None
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v))


def _event_log_of(ctx: Mapping[str, Any]) -> list:
    """event_log 源（世界之书聚合段数据源）：persistent_state["event_log"] 优先，
    ctx["event_log"] 兜底（对齐 adventure_log._event_log_of 口径）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, Mapping):
        log = ps.get(EVENT_LOG_KEY)
        if isinstance(log, list):
            return log
    log = ctx.get(EVENT_LOG_KEY)
    return log if isinstance(log, list) else []


def _world_book(ctx: Mapping[str, Any]) -> dict:
    """世界之书聚合段（R-19 第 2 件，工程补白 3）：从 event_log 读全部六类生成。

    入参 ctx: 上下文。出参 dict: {"world_book": {total, categories: [{tag, name,
    count, latest_ts}]}}（categories 按 ADVENTURE_LOG_TAGS 固定组序）。
    核心逻辑: 逐条事件实例按 tag 归入六类计数 + 最新 ts；非六类 tag（如
    N-03 预置 tag=event）不计入；纯函数只读，不落盘不改写。
    """
    entries = _event_log_of(ctx)
    counts = {t: 0 for t in ADVENTURE_LOG_TAGS}
    latest: dict = {}
    for e in entries:
        tag = str(e.get("tag") or "event") if isinstance(e, Mapping) else "event"
        if tag not in counts:
            continue
        counts[tag] += 1
        ts = str(e.get("ts") or "") if isinstance(e, Mapping) else ""
        if ts and ts > str(latest.get(tag) or ""):
            latest[tag] = ts
    categories = [
        {"tag": t, "name": _TAG_NAMES.get(t, t), "count": counts[t],
         "latest_ts": latest.get(t)}
        for t in ADVENTURE_LOG_TAGS
    ]
    return {"world_book": {"total": sum(counts.values()), "categories": categories}}


# -------------------------------------------------------------------------------------
# 授予链（R-21：每档一次，跨档连升逐档触发；E-05 幂等；D-07 不重授）
# -------------------------------------------------------------------------------------
def _grant_tier(
    ctx: MutableMapping[str, Any],
    tier_def: Mapping[str, Any],
    today: Optional[str],
) -> dict:
    """单档授予（内部，R-21）：称号位 + 冒险日志 log_milestone + 幂等落账。

    入参 ctx: 可变上下文；tier_def: 档位定义（pct/tier/message）；today: 日期键
    （注入确定性）。出参 dict: {ok, grant?}——ok=true 时 grant = {milestone, pct,
    tier, message, title_written, today}。
    核心逻辑: 已授予档（E-05）→ {ok:false, reason:already_granted} 跳过；否则
    写称号位（低→高覆盖）→ log_milestone([事件:里程碑:{pct}]) → 集合落账 →
    组装里程碑事件记录。
    """
    pct = int(tier_def["pct"])
    ps = _persistent_state_of(ctx)
    if ps is None:
        return {"ok": False, "reason": "no_persistent_state"}
    if str(pct) in _granted_of(ps):
        return {"ok": False, "reason": "already_granted"}
    wrote = _write_title(ctx, str(tier_def["tier"]))
    log_milestone(ctx, pct)
    _record_grant(ps, pct)
    return {
        "ok": True,
        "grant": {
            "milestone": f"codex_milestone_{pct}",
            "pct": pct,
            "tier": str(tier_def["tier"]),
            "message": str(tier_def["message"]),
            "title_written": wrote,
            "today": today,
        },
    }


def _grant_100(
    ctx: MutableMapping[str, Any],
    today: Optional[str],
    grant: MutableMapping[str, Any],
) -> None:
    """100% 三件套收尾（内部，R-19/R-21）：世界之书聚合段 + 隐藏神龛标记。

    入参 ctx: 可变上下文；today: 日期键（注入确定性，随记录透传）；grant: 100%
    档授予记录（就地扩展）。出参 None（就地改写 grant）。
    核心逻辑: 生成世界之书聚合段（event_log 六类）→ persistent_state[
    hidden_shrine] = true（BCH-09/F-16 消费）→ grant 附 world_book/hidden_shrine，
    message 追加载入条数。100 档的 log_milestone 已由 _grant_tier 完成，本函数
    不重复写日志（E-05 语义）。
    """
    ps = _persistent_state_of(ctx)
    if ps is None:
        return
    wb = _world_book(ctx)
    ps[HIDDEN_SHRINE_KEY] = True
    grant["world_book"] = wb
    grant["hidden_shrine"] = True
    total = int(wb["world_book"]["total"] or 0)
    if total > 0:
        grant["message"] = f"{grant.get('message', '')}（世界之书已载入 {total} 条冒险见证）"


def check_milestones(
    ctx: MutableMapping[str, Any],
    *,
    today: Optional[str] = None,
) -> dict:
    """图鉴里程碑检查触发（R-20/R-21 唯一入口；mark_seen 结算后调用）。

    入参 ctx: 可变上下文（codex 完成度 / persistent_state / player.title_state /
    event_log 读写）；today: 日期键（注入确定性，None → ctx["today"] 兜底）。
    出参 dict: {granted: [里程碑事件…], message: str}——granted 每项 =
    {milestone, pct, message, …}（100% 档另含 world_book/hidden_shrine）；
    无新达档 → granted=[]，message=""。
    核心逻辑:
      ① today 注入 ctx（bump_event ts 确定性）；
      ② 完成度读取（ctx["codex"] 或惰性 codex_progress）→ 当前 pct；
      ③ 逐档（升序 25→50→75→90→100）判定：pct 达档且未授予（E-05）→
        _grant_tier（称号位 + log_milestone + 落账）；跨档连升（如 45%→52%
        只授 50% 档、20%→60% 连授 25/50 档）逐档触发（R-21 跨档跳升语义）；
      ④ 100% 档新授 → _grant_100 收尾（世界之书 + 隐藏神龛）；
      ⑤ 消息 = 各档 message 换行拼接（90% 档含「全收集还有更深处」软锚）。
    """
    if isinstance(ctx, MutableMapping) and today is not None:
        ctx["today"] = str(today)
    pct = _read_pct(ctx)
    ps = _persistent_state_of(ctx)
    granted = _granted_of(ps) if ps is not None else set()
    records: list = []
    for tier_def in MILESTONE_DEFS:
        if int(tier_def["pct"]) > pct or str(tier_def["pct"]) in granted:
            continue
        r = _grant_tier(ctx, tier_def, today)
        if not r.get("ok"):
            continue
        grant = r["grant"]
        records.append(grant)
        if int(tier_def["pct"]) == 100:
            _grant_100(ctx, today, grant)
    message = "\n".join(str(g["message"]) for g in records)
    return {"granted": records, "message": message}
