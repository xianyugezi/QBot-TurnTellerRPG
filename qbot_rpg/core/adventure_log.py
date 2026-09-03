"""冒险日志引擎（qbot_rpg/core/adventure_log.py · M7 BCH-05 · 3f F-01/F-02 · R-02/R-03/R-05）。

六类自动记录 + 分组分页展示数据源 + 环境快照透传 + N-04 会话快照 30 天惰性清理。

依据：
  - docs/细化/细化_3f_单机向体验.md：
    · R-02（1.2 六类自动记录表：first_kill / first_crown / story_node / hidden_find /
      milestone / codex_new，全挂事件注册表，longline_counters 只增不减累计，
      首见 first_seen=true 仅 hidden_find/first_kill/first_crown 三类）
    · R-03（1.4 分组展示与分页：按六类分组、组序固定（首杀→首钓冠级→剧情节点→
      隐藏发现→里程碑→图鉴新增）、组内倒序、每页 5 条、/日志 N 翻页、越界回落最末页、
      空组不渲染）
    · R-05（1.6 环境快照：每条必附 [季节]/[时段]/[天气]，缺失 "--"，只读展示）
    · E-01（1.3 冒险日志条目模型：event_id/tag/count_key/template_id/params/
      snapshot{season,period,weather}/first_seen/ts；环形 300 可配）
  - docs/细化/细化_M7_NPC对话接线.md N-04（RN-11：persistent_state["dialog_session"]
    30 天惰性清理，last_active_at 超 30 天 → 清除恢复上下文；与已交付标记
    npc_heard/npc_delivered 常驻分离）
  - qbot_rpg/core/event_bus.py（bump_event 三表 + event_log 环形，真实签名已 read 核对）

职责：
  六类记录函数 log_*（每类一个事件键约定，经 bump_event 三表写入 + instance 携带
  tag/first_seen/params/快照）；read_log 分组分页展示数据源；cleanup_dialog_snapshot
  RN-11 会话快照惰性清理。

【工程补白 · 显式标注】
  1) 事件键约定（R-02 语义，与 N-03 预置事件分离）：
       first_kill   → [事件:首杀]         + target=怪物ID（nested，条件全键 [事件:首杀:ID]）
       first_crown  → [事件:首钓冠级]     + target=鱼种ID（nested）
       story_node   → [事件:任务完成]     + 无 target（**flat**，复用 N-03 预置键——
                      quest 结算点既有点，保持 test_event_bus 平铺断言与条件引擎读取源不变）
       hidden_find  → [事件:隐藏发现]     + target=隐藏ID（nested，对齐契约 [事件:隐藏发现:ID]）
       milestone    → [事件:里程碑]       + target=完成度（nested，如 [事件:里程碑:50]）
       codex_new    → [事件:图鉴新增]     + target=条目（nested）
     bump_event 带 target → event_counts 写 nested {key:{target:count}}（条件引擎
     _read_counter nested 形态）；无 target → flat。
  2) template_id 约定：六类统一 f"adventure.{tag}"（E-01 必选字段落值；渲染模板 ID 的
     注册/解析归渲染侧（log_commands 兄弟路）约定，本引擎只提供句柄，params 自带展示
     数据可兜底渲染）。
  3) 首见判定（R-02）：first_kill/first_crown/hidden_find 的 first_seen = 写入前该
     target 的 event_counts 嵌套计数为 0（首见）；story_node/milestone/codex_new 恒
     first_seen=false（非首见类）。重复触发计数只增不减，不再生成首见文案。
  4) read_log 只读不改（纯函数）；组内倒序 = event_log 追加序反转（bump_event 按
     时间追加，反转即最新在前，稳定可复现）；非六类 tag 条目（如 N-03 预置 tag=event）
     不进入六类分组（R-03 只展示六类）。
  5) cleanup_dialog_snapshot 纯函数确定性：now 由入参/ctx["now"] 注入，缺省 UTC 现刻
     为最后兜底（对齐 event_bus._now_iso 口径）；无 last_active_at/last_active 或解析
     失败 → 保留不误删。last_active_at 的落盘（装配层提交快照时盖章）归对话持久化装配
     批次【工程补白 · 待接线】，本函数只做读取侧清理。
  6) 未接线记录登记（本批次只接线 first_kill/story_node，battle/quest 已有点）：
       first_crown  → 钓鱼结算（2c1b/2c1c）批次接线
       hidden_find  → 3f 隐藏要素（BCH-07）接线
       milestone    → 图鉴完成度阶梯（F-12 归 BCH-08）接线
       codex_new    → 图鉴点亮（2c1c/4d 未实装）接线

铁律：零 NoneBot import；纯函数确定性（now/rng 由 ctx 注入）；每函数 docstring；
最小侵入（复用 event_bus 模式，不新增存储）；不 git commit。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, MutableMapping, Optional

from qbot_rpg.core.event_bus import EVENT_LOG_KEY, bump_event, resolve_event_key

__all__ = [
    # 六类 tag（R-02 表，组序固定 R-03）
    "ADVENTURE_LOG_TAGS",
    "FIRST_KILL_TAG",
    "FIRST_CROWN_TAG",
    "STORY_NODE_TAG",
    "HIDDEN_FIND_TAG",
    "MILESTONE_TAG",
    "CODEX_NEW_TAG",
    # 事件键（R-02 约定；full 形态供条件引擎/展示引用）
    "EVENT_KEY_FIRST_KILL",
    "EVENT_KEY_FIRST_CROWN",
    "EVENT_KEY_STORY_NODE",
    "EVENT_KEY_HIDDEN_FIND",
    "EVENT_KEY_MILESTONE",
    "EVENT_KEY_CODEX_NEW",
    "event_key_first_kill",
    "event_key_first_crown",
    "event_key_story_node",
    "event_key_hidden_find",
    "event_key_milestone",
    "event_key_codex_new",
    # 记录函数
    "log_first_kill",
    "log_first_crown",
    "log_story_node",
    "log_hidden_find",
    "log_milestone",
    "log_codex_new",
    # 展示数据源
    "read_log",
    "ADVENTURE_LOG_PAGE_SIZE",
    # N-04 RN-11 会话快照惰性清理
    "cleanup_dialog_snapshot",
    "DIALOG_SNAPSHOT_KEY",
    "DIALOG_SNAPSHOT_TTL_DAYS",
]

# -------------------------------------------------------------------------------------
# 六类 tag 与组序（R-02 表 / R-03 组序固定：首杀 → 首钓冠级 → 剧情节点 → 隐藏发现 →
# 里程碑 → 图鉴新增）
# -------------------------------------------------------------------------------------
FIRST_KILL_TAG = "first_kill"          # 首杀（怪物首次击杀结算）
FIRST_CROWN_TAG = "first_crown"        # 首钓冠级（出鱼结算冠级≥gold）
STORY_NODE_TAG = "story_node"          # 剧情节点（主线任务关键节点）
HIDDEN_FIND_TAG = "hidden_find"        # 隐藏发现（[事件:隐藏发现:ID]）
MILESTONE_TAG = "milestone"            # 里程碑（图鉴阶梯 25/50/75/90/100 达成）
CODEX_NEW_TAG = "codex_new"            # 图鉴新增（任意条目点亮/补全）

ADVENTURE_LOG_TAGS: tuple = (
    FIRST_KILL_TAG,
    FIRST_CROWN_TAG,
    STORY_NODE_TAG,
    HIDDEN_FIND_TAG,
    MILESTONE_TAG,
    CODEX_NEW_TAG,
)

# -------------------------------------------------------------------------------------
# 事件键约定（R-02 语义；base 键用于 bump_event，target 携带按目标维度；full 形态
# 为条件引擎/展示引用全键）
#
# M12.5 批5 收口：以下 EVENT_KEY_* 常量的写读点（log_* 内 _prev_count/bump_event）
# 已改经 resolve_event_key(ctx, 事件名) 解析（settings.events 段可配 name 段）。
# 常量保留仅供 event_key_* 全键函数拼装与外部引用/测试 import —— 仅=缺省值，
# 解析中心 EVENT_KEY_DEFAULTS 缺省回退同值（零配置零破坏；配置改名后写点落新键，
# 条件/展示按新键写即可）。
# -------------------------------------------------------------------------------------
EVENT_KEY_FIRST_KILL = "[事件:首杀]"  # 写读点缺省值（resolve_event_key(ctx, "首杀")）
EVENT_KEY_FIRST_CROWN = "[事件:首钓冠级]"  # 写读点缺省值（resolve_event_key(ctx, "首钓冠级")）
# story_node 复用 N-03 预置键 [事件:任务完成]（quest 结算点既有点；flat 保持条件引擎
# 读取源与 test_event_bus 平铺断言不变）
EVENT_KEY_STORY_NODE = "[事件:任务完成]"  # 写读点缺省值（resolve_event_key(ctx, "任务完成")）
EVENT_KEY_HIDDEN_FIND = "[事件:隐藏发现]"  # 写读点缺省值（resolve_event_key(ctx, "隐藏发现")）
EVENT_KEY_MILESTONE = "[事件:里程碑]"  # 写读点缺省值（resolve_event_key(ctx, "里程碑")）
EVENT_KEY_CODEX_NEW = "[事件:图鉴新增]"  # 写读点缺省值（resolve_event_key(ctx, "图鉴新增")）


def _full_key(base: str, target: object) -> str:
    """全键形态：base 尾 `]` 前插 `:{target}`（对齐条件引擎 _parse_event_var 的
    name:param 解析：`[事件:首杀:蚀月之狼]` → name=[事件:首杀] + param=蚀月之狼）。"""
    if base.endswith("]"):
        return f"{base[:-1]}:{target}]"
    return f"{base}:{target}"


def event_key_first_kill(monster_id: object) -> str:
    """首杀事件全键（条件引用形态）：`[事件:首杀:{monster_id}]`。"""
    return _full_key(EVENT_KEY_FIRST_KILL, monster_id)


def event_key_first_crown(fish_id: object) -> str:
    """首钓冠级事件全键：`[事件:首钓冠级:{fish_id}]`。"""
    return _full_key(EVENT_KEY_FIRST_CROWN, fish_id)


def event_key_story_node(node: object) -> str:
    """剧情节点事件全键：`[事件:任务完成:{node}]`（写入侧 flat，展示/引用形态）。"""
    return _full_key(EVENT_KEY_STORY_NODE, node)


def event_key_hidden_find(hidden_id: object) -> str:
    """隐藏发现事件全键：`[事件:隐藏发现:{hidden_id}]`（契约 [事件:隐藏发现:ID]）。"""
    return _full_key(EVENT_KEY_HIDDEN_FIND, hidden_id)


def event_key_milestone(pct: object) -> str:
    """里程碑事件全键：`[事件:里程碑:{pct}]`。"""
    return _full_key(EVENT_KEY_MILESTONE, pct)


def event_key_codex_new(entry: object) -> str:
    """图鉴新增事件全键：`[事件:图鉴新增:{entry}]`。"""
    return _full_key(EVENT_KEY_CODEX_NEW, entry)


# -------------------------------------------------------------------------------------
# 内部小工具
# -------------------------------------------------------------------------------------
def _prev_count(ctx: Mapping[str, Any], key: str, target: str) -> int:
    """写入前该 target 的嵌套计数（首见判定，R-02）：event_counts[key][target]。"""
    ec = ctx.get("event_counts")
    if not isinstance(ec, Mapping):
        return 0
    sub = ec.get(key)
    if not isinstance(sub, Mapping):
        return 0
    try:
        return int(sub.get(target, 0))
    except (TypeError, ValueError):
        return 0


def _template_id(tag: str) -> str:
    """条目模板 ID 约定（工程补白 2）：`adventure.{tag}`。"""
    return f"adventure.{tag}"


# -------------------------------------------------------------------------------------
# 六类记录函数（R-02：每类一个事件键约定，经 bump_event 三表写入）
# -------------------------------------------------------------------------------------
def log_first_kill(
    ctx: MutableMapping[str, Any],
    monster_name: str,
    *,
    monster_id: Optional[str] = None,
) -> dict:
    """首杀日志（R-02 first_kill，工程补白 6 已接线 battle）：「首次击败 {怪物}」。

    事件键 [事件:首杀]（base）+ target=怪物ID（nested）；首见（该怪物首次击杀）
    first_seen=true，重复击杀计数只增不减不再标首见。params 带怪物名/ID 供渲染。
    """
    if not str(monster_name or ""):
        return {"ok": False, "reason": "empty_name"}
    target = str(monster_id) if monster_id is not None else str(monster_name)
    # M12.5 批5 收口：写读键经解析中心（settings.events 可配，缺省回退 EVENT_KEY_FIRST_KILL）
    key = resolve_event_key(ctx, "首杀")
    first_seen = _prev_count(ctx, key, target) == 0
    return bump_event(
        ctx,
        key,
        instance={
            "tag": FIRST_KILL_TAG,
            "target": target,
            "first_seen": first_seen,
            "template_id": _template_id(FIRST_KILL_TAG),
            "params": {"name": str(monster_name), "monster_id": target},
        },
    )


def log_first_crown(
    ctx: MutableMapping[str, Any],
    fish_name: str,
    *,
    fish_id: Optional[str] = None,
) -> dict:
    """首钓冠级日志（R-02 first_crown，工程补白 6 待钓鱼批次接线）：「首次钓获金冠 {鱼}」。

    事件键 [事件:首钓冠级]（base）+ target=鱼种ID（nested）；首见 first_seen=true。
    """
    if not str(fish_name or ""):
        return {"ok": False, "reason": "empty_name"}
    target = str(fish_id) if fish_id is not None else str(fish_name)
    # M12.5 批5 收口：写读键经解析中心（settings.events 可配，缺省回退 EVENT_KEY_FIRST_CROWN）
    key = resolve_event_key(ctx, "首钓冠级")
    first_seen = _prev_count(ctx, key, target) == 0
    return bump_event(
        ctx,
        key,
        instance={
            "tag": FIRST_CROWN_TAG,
            "target": target,
            "first_seen": first_seen,
            "template_id": _template_id(FIRST_CROWN_TAG),
            "params": {"name": str(fish_name), "fish_id": target},
        },
    )


def log_story_node(
    ctx: MutableMapping[str, Any],
    node: str,
    *,
    name: Optional[str] = None,
) -> dict:
    """剧情节点日志（R-02 story_node，工程补白 6 已接线 quest）：「主线·{节点} 落幕」。

    事件键 [事件:任务完成]（**flat**，复用 N-03 预置键——quest 结算点既有点，保持
    条件引擎读取源与平铺计数不变）；节点信息入 params（node/name）；非首见类恒
    first_seen=false。
    """
    if not str(node or ""):
        return {"ok": False, "reason": "empty_node"}
    # M12.5 批5 收口：写读键经解析中心（settings.events 可配，缺省回退 EVENT_KEY_STORY_NODE）
    key = resolve_event_key(ctx, "任务完成")
    return bump_event(
        ctx,
        key,
        instance={
            "tag": STORY_NODE_TAG,
            "first_seen": False,
            "template_id": _template_id(STORY_NODE_TAG),
            "params": {"node": str(node), "name": str(name) if name else str(node)},
        },
    )


def log_hidden_find(ctx: MutableMapping[str, Any], hidden_id: str) -> dict:
    """隐藏发现日志（R-02 hidden_find，工程补白 6 待 BCH-07 隐藏要素接线）。

    事件键 [事件:隐藏发现]（base）+ target=隐藏ID（nested，契约 [事件:隐藏发现:ID]）；
    首见 first_seen=true（首见日志，重复发现不生成首见文案）。
    """
    if not str(hidden_id or ""):
        return {"ok": False, "reason": "empty_hidden"}
    target = str(hidden_id)
    # M12.5 批5 收口：写读键经解析中心（settings.events 可配，缺省回退 EVENT_KEY_HIDDEN_FIND）
    key = resolve_event_key(ctx, "隐藏发现")
    first_seen = _prev_count(ctx, key, target) == 0
    return bump_event(
        ctx,
        key,
        instance={
            "tag": HIDDEN_FIND_TAG,
            "target": target,
            "first_seen": first_seen,
            "template_id": _template_id(HIDDEN_FIND_TAG),
            "params": {"id": target},
        },
    )


def log_milestone(ctx: MutableMapping[str, Any], pct: object) -> dict:
    """里程碑日志（R-02 milestone，工程补白 6 待 BCH-08 图鉴阶梯接线）：「图鉴完成度达到 X%」。

    事件键 [事件:里程碑]（base）+ target=完成度（nested，如 [事件:里程碑:50]）；
    非首见类恒 first_seen=false。
    """
    if pct is None:
        return {"ok": False, "reason": "empty_pct"}
    target = str(pct)
    # M12.5 批5 收口：写读键经解析中心（settings.events 可配，缺省回退 EVENT_KEY_MILESTONE）
    key = resolve_event_key(ctx, "里程碑")
    return bump_event(
        ctx,
        key,
        instance={
            "tag": MILESTONE_TAG,
            "target": target,
            "first_seen": False,
            "template_id": _template_id(MILESTONE_TAG),
            "params": {"pct": target},
        },
    )


def log_codex_new(ctx: MutableMapping[str, Any], entry: str) -> dict:
    """图鉴新增日志（R-02 codex_new，工程补白 6 待 codex 点亮接线）：「图鉴新增：{条目}」。

    事件键 [事件:图鉴新增]（base）+ target=条目（nested）；非首见类恒 first_seen=false。
    """
    if not str(entry or ""):
        return {"ok": False, "reason": "empty_entry"}
    target = str(entry)
    # M12.5 批5 收口：写读键经解析中心（settings.events 可配，缺省回退 EVENT_KEY_CODEX_NEW）
    key = resolve_event_key(ctx, "图鉴新增")
    return bump_event(
        ctx,
        key,
        instance={
            "tag": CODEX_NEW_TAG,
            "target": target,
            "first_seen": False,
            "template_id": _template_id(CODEX_NEW_TAG),
            "params": {"entry": target},
        },
    )


# -------------------------------------------------------------------------------------
# 展示数据源（R-03 分组分页；R-05 快照随条目透传）
# -------------------------------------------------------------------------------------
ADVENTURE_LOG_PAGE_SIZE = 5


def _event_log_of(ctx: Mapping[str, Any]) -> list:
    """event_log 源：persistent_state["event_log"] 优先，ctx["event_log"] 兜底（对齐
    event_bus._log_list_of 兜底口径）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, Mapping):
        log = ps.get(EVENT_LOG_KEY)
        if isinstance(log, list):
            return log
    log = ctx.get(EVENT_LOG_KEY)
    return log if isinstance(log, list) else []


def _entry_tag(entry: Mapping[str, Any]) -> str:
    """条目 tag 归一：缺省 "event"（对齐 bump_event 条目 tag 兜底）。"""
    return str(entry.get("tag") or "event")


def read_log(
    ctx: Mapping[str, Any],
    tag: Optional[str] = None,
    page: int = 1,
) -> dict:
    """冒险日志展示数据源（3f R-03）：六类分组 + 组序固定 + 组内倒序 + 每页 5 条。

    入参 ctx: 事件上下文（persistent_state["event_log"] 或 ctx["event_log"] 读取源）；
    tag: 可选类别过滤（六类之一；None=全部分组）；page: 页码（越界回落最末页）。
    出参 dict: {entries: {tag: [entry…]}（仅本页非空组，组序固定）, order: 六类固定
    组序, page, pages, total, page_size}。纯函数只读，不落盘不改写。
    核心逻辑:
      - 组内倒序 = event_log 追加序反转（bump_event 按时间追加，反转即最新在前）；
      - 分页 = 按固定组序展平（组内倒序）后每 5 条一页；页内重新按组归组（保留组序）；
      - 非六类 tag 条目（如 N-03 预置 tag=event）不进入六类分组（R-03 只展示六类）；
      - 快照（R-05 season/period/weather）随条目原样透传，缺失 "--"。
    """
    try:
        page_i = max(1, int(page))
    except (TypeError, ValueError):
        page_i = 1
    items = _event_log_of(ctx)
    if tag is not None:
        tag_s = str(tag)
        items = [e for e in items if _entry_tag(e) == tag_s]
    # 组内倒序（追加序反转）后按固定组序展平
    flat: list = []
    for t in ADVENTURE_LOG_TAGS:
        flat.extend(e for e in reversed(items) if _entry_tag(e) == t)
    total = len(flat)
    pages = max(1, (total + ADVENTURE_LOG_PAGE_SIZE - 1) // ADVENTURE_LOG_PAGE_SIZE)
    page_i = min(page_i, pages)
    start = (page_i - 1) * ADVENTURE_LOG_PAGE_SIZE
    page_entries = flat[start:start + ADVENTURE_LOG_PAGE_SIZE]
    entries: dict = {}
    for e in page_entries:
        t = _entry_tag(e)
        entries.setdefault(t, []).append(e)
    return {
        "entries": entries,
        "order": list(ADVENTURE_LOG_TAGS),
        "page": page_i,
        "pages": pages,
        "total": total,
        "page_size": ADVENTURE_LOG_PAGE_SIZE,
    }


# -------------------------------------------------------------------------------------
# N-04 RN-11：dialog_session 30 天惰性清理（读取/启动时调用；与 npc_heard/npc_delivered
# 常驻标记分离）
# -------------------------------------------------------------------------------------
DIALOG_SNAPSHOT_KEY = "dialog_session"
DIALOG_SNAPSHOT_TTL_DAYS = 30
_DIALOG_LAST_ACTIVE_KEYS = ("last_active_at", "last_active")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_ts(value: object) -> Optional[datetime]:
    """时间戳解析：数值（epoch 秒/毫秒）或 ISO 字符串 → aware UTC datetime；失败 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # 毫秒 epoch
            v = v / 1000.0
        try:
            return _EPOCH + timedelta(seconds=v)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)  # 无时区 → 按 UTC（对齐 event_bus ts 口径）
        return dt.astimezone(timezone.utc)
    return None


def _now_dt(now: object, ctx: Mapping[str, Any]) -> datetime:
    """当前时刻（aware UTC）：入参 now → ctx["now"] → 缺省 UTC 现刻（最后兜底）。"""
    if isinstance(now, datetime):
        dt = now
    else:
        raw = ctx.get("now") if isinstance(ctx, Mapping) else None
        if raw is not None:
            parsed = _parse_ts(raw)
            dt = parsed if parsed is not None else datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _persistent_state_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """persistent_state 可变容器定位：ctx["persistent_state"] → ctx["player"].persistent_state
    → ctx 自身（兄弟路直键兜底）；非可变 → None。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = ctx.get("player")
    if isinstance(player, Mapping):
        ps2 = player.get("persistent_state")
        if isinstance(ps2, MutableMapping):
            return ps2
    if isinstance(ctx, MutableMapping):
        return ctx
    return None


def cleanup_dialog_snapshot(
    ctx: MutableMapping[str, Any],
    *,
    now: Optional[datetime] = None,
    ttl_days: int = DIALOG_SNAPSHOT_TTL_DAYS,
) -> bool:
    """RN-11：persistent_state["dialog_session"] 30 天惰性清理（读取/启动时调用）。

    入参 ctx: 可变上下文（persistent_state / player.persistent_state 读写）；now: 注入
    当前时刻（缺省 ctx["now"]，再兜底 UTC 现刻，确定性）；ttl_days: 存活天数（缺省 30）。
    出参 bool: 是否清除了过期会话快照（True=已清除）。
    核心逻辑:
      - 读取 persistent_state["dialog_session"]（Mapping 快照）；非 Mapping → 不清理；
      - 取 last_active_at（兜底 last_active）→ 超 ttl_days → 清除该键并返回 True；
      - 无时间戳 / 解析失败 / 未过期 → 保留（不误删）；npc_heard/npc_delivered 常驻
        标记不在此表、不受本清理影响（分离）。
    工程补白：last_active_at 的落盘盖章归对话持久化装配批次；本函数只做读取侧清理。
    """
    if not isinstance(ctx, MutableMapping) or not ctx:
        return False
    ps = _persistent_state_of(ctx)
    if not isinstance(ps, MutableMapping):
        return False
    raw = ps.get(DIALOG_SNAPSHOT_KEY)
    if not isinstance(raw, Mapping):
        return False
    last = None
    for k in _DIALOG_LAST_ACTIVE_KEYS:
        v = raw.get(k)
        if v is not None and str(v):
            last = v
            break
    if last is None:
        return False
    parsed = _parse_ts(last)
    if parsed is None:
        return False
    try:
        ttl = max(0, int(ttl_days or 0))
    except (TypeError, ValueError):
        ttl = DIALOG_SNAPSHOT_TTL_DAYS
    now_dt = _now_dt(now, ctx)
    if (now_dt - parsed).total_seconds() > ttl * 86400:
        ps.pop(DIALOG_SNAPSHOT_KEY, None)
        return True
    return False
