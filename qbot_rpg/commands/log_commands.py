"""日志指令接线 log_commands.py（M7 BCH-05 3f F-03/F-04 · qbot_rpg/commands/log_commands.py）。

统一注册「日志」spec（ADR-09：is_gm=True 保留 GM 强制 / 前缀，handler 内按权限分支
玩家/GM 双视图），承接 docs/细化/细化_3f_单机向体验.md：

  - R-01（§1.1 指令签名与权限仲裁）：`/日志 [页码]`（页码可选，默认 1，玩家视图）；
    GM 执行 `/日志` 走系统日志视图；权限判定失败（无 GM 权限执行 GM 视图）→ 3c
    权限拒绝模板回复，不泄露系统日志内容；页码越界 → 夹取最后一页 + 提示（裁决②）。
  - R-02（§1.2 六类自动记录）：首杀 first_kill / 首钓冠级 first_crown / 剧情节点
    story_node / 隐藏发现 hidden_find / 里程碑 milestone / 图鉴新增 codex_new。
  - R-03（§1.4 分组展示与分页）：六类分组、组序固定（首杀→首钓冠级→剧情节点→隐藏发现
    →里程碑→图鉴新增）、组内倒序（最新在前）、每页 5 条、越界回落最末页、空组不渲染。
  - R-04（§1.5 传记 50 段环形）：六类记录 × 自然日聚合叙述段，50 段环形（超出覆盖最旧），
    `/日志 传记` 进入传记视图（无页码 = 最近 1 段，页码翻段），段内附当日快照统计。
  - R-06（§1.7 GM 系统日志）：最近事件倒序（D-03 复用 GM 审计流——指令调用/结算/告警，
    数据源 = ctx[\"audit_log\"]），默认展示 20 条（sys_log.default_show），分页 20 条/页
    （sys_log.page_size），保留窗口 50（sys_log.max_entries）；与冒险日志隔离（不含
    玩家六类记录内容）。
  - 环境快照（§1.6 R-05）：条目快照 [季节]/[时段]/[天气] 展示（缺失 → "--"）。

依据：
  - docs/细化/细化_M7_交互补全总纲.md ADR-09（/日志 注册统一归 log_commands：is_gm=True、
    不并入 gm_commands、不改 parsers GM 判定）
  - docs/仲裁/细化_0_仲裁决议汇总.md R-02（sys_log.default_show=20 / page_size=20 /
    max_entries=50）
  - qbot_rpg/core/event_bus.py（EVENT_LOG_KEY="event_log" / bump_event 条目模型 E-01：
    {event_id, tag, count_key, template_id, params, snapshot, first_seen, ts}）
  - qbot_rpg/assembly/context.py（make_context 注入 ctx[\"event_log\"] / ctx[\"is_gm\"] /
    ctx[\"settings\"] / ctx[\"season\"] / ctx[\"period\"] / ctx[\"weather\"]）
  - 兄弟路 BCH-05 adventure_log.read_log（真实签名 (ctx, tag=None, page=1) -> dict：
    分组页数据 {entries, order, page, pages, total, page_size}；已落盘 → 本模块优先
    消费；未落盘/异常 → 本地兼容读函数兜底，惰性 import 不阻塞）
  - m4_shared_contract §2.2 + 细化_3d（列表 5 条/页上限 + 裁决② 夹取 + CakeGame 式尾段
    render_cake_tail + emoji 纪律 3d D-01：仅 ✅/❌ 功能性标记 + 排版符号）

【工程补白 · 显式标注】
  1) 传记 50 段**零新存储**（3f D-01）：段由 event_log 现算聚合（六类 × 自然日），展示层
     截取最近 50 段（超出覆盖最旧）——与 300 条事件实例环形同源，不新增表。
  2) 权限拒绝模板（3c R-01「按 3c 权限拒绝模板回复」）：文档未给逐字文案，本模块按 3d
     统一错误句式定义 PERMISSION_DENIED（❌ 功能性标记 + 无权限语义 + 零内容泄露）。
  3) 非六类 tag 的事件条目（环境事件等）不进冒险日志分组视图（R-02 六类分组边界）；
     系统日志与冒险日志分域（R-06 隔离），GM 视图不含玩家六类记录内容。
  4) GM 视图「复用 GM 审计流」= 只读 ctx[\"audit_log\"]（gm_commands.record_audit 写入的
     同源数据）；对 /日志 查询本身的审计留痕由 gm_commands/M12 路线承担（本路不重复写）。
  5) 六类条目文本按 R-02 表格逐类模板渲染（D-01 不落自由文本），缺失参数用 count_key
     尾段兜底，确定性输出。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性（now/rng 由
ctx 注入）、每函数 docstring、装饰性 emoji 全局禁用（仅 ✅/❌ 功能性标记 + 排版符号）。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, List, Mapping, MutableMapping, Optional, Sequence, cast

from qbot_rpg.commands.parsers import parse_int
from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.commands.sender import format_tpl12
from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_cake_tail,
    resolve_page,
)

__all__ = [
    "LOG_CMD",
    "BIO_SUBWORD",
    "GM_VIEW_WORDS",
    "EVENT_GROUP_ORDER",
    "EVENT_GROUP_NAMES",
    "ADVENTURE_PAGE_SIZE",
    "BIO_SEGMENT_CAP",
    "SYS_LOG_DEFAULT_SHOW",
    "SYS_LOG_PAGE_SIZE",
    "SYS_LOG_MAX_ENTRIES",
    "PERMISSION_DENIED",
    "cmd_log",
    "render_adventure_page",
    "render_bio_page",
    "render_system_log_page",
    "register_log_commands",
    "_fragment",
]

# ---------------------------------------------------------------------------
# 指令与常量（3f R-01~R-06 / 细化_0 R-02）
# ---------------------------------------------------------------------------

LOG_CMD = "日志"

# 传记子词（3f R-04：`/日志 传记` 进入传记视图）
BIO_SUBWORD = "传记"

# GM 视图显式入口词（权限分支测试锚点：玩家触发 → 权限拒绝模板，3f R-01）
GM_VIEW_WORDS = frozenset({"系统", "sys"})

# 六类分组固定组序（3f R-03：首杀 → 首钓冠级 → 剧情节点 → 隐藏发现 → 里程碑 → 图鉴新增）
EVENT_GROUP_ORDER: tuple = (
    "first_kill",
    "first_crown",
    "story_node",
    "hidden_find",
    "milestone",
    "codex_new",
)

# 六类 tag → 分组显示名（3f R-02 表）
EVENT_GROUP_NAMES: Mapping[str, str] = {
    "first_kill": "首杀",
    "first_crown": "首钓冠级",
    "story_node": "剧情节点",
    "hidden_find": "隐藏发现",
    "milestone": "里程碑",
    "codex_new": "图鉴新增",
}

# 冒险日志每页条数（3f R-03：5 条/页 + m4 §2.2 列表上限）
ADVENTURE_PAGE_SIZE: int = DEFAULT_PAGE_SIZE  # 5

# 传记 50 段环形（3f R-04 / 单机 L53/L87）
BIO_SEGMENT_CAP: int = 50

# GM 系统日志（细化_0 R-02 / 3f R-06）：默认展示 / 每页 / 保留窗口
SYS_LOG_DEFAULT_SHOW: int = 20
SYS_LOG_PAGE_SIZE: int = 20
SYS_LOG_MAX_ENTRIES: int = 50

# 3c 权限拒绝模板（工程补白 2：无 GM 权限执行 GM 视图，不泄露系统日志内容）
PERMISSION_DENIED: str = "❌ 没有 GM 权限，无法查看系统日志。"

# 空文案（纯文本零装饰 emoji）
_EMPTY_ADVENTURE: str = "（暂无冒险日志）"
_EMPTY_BIO: str = "（暂无传记）"
_EMPTY_SYS: str = "（暂无系统日志）"

# CakeGame 式尾段 Tip（2026-08-27 用户拍板：列表尾段统一当前页 + Tip）
_ADV_TAIL_TIP: str = "发送'日志 传记'回溯冒险规律"
_BIO_TAIL_TIP: str = "发送'日志 传记 N'翻看更早的段落"
_SYS_TAIL_TIP: str = "发送'日志 条数=50'扩大查看窗口"

# 环境快照缺失占位（3f R-05：缺失 → "--"，不阻塞）
_MISSING = "--"


# ---------------------------------------------------------------------------
# 工具（纯函数，均带 docstring）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 basic/gm 同口径）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    return "/" + str(getattr(parsed, "command", "") or "")


def _parse_page_arg(text: Optional[str]) -> Optional[int]:
    """页码参数归一：None → 1；整数 ≥1 → 原值；0/负数/非数字 → None（壳层转 TPL-12，裁决②）。"""
    if text is None:
        return 1
    n = parse_int(text)
    if n is None or n < 1:
        return None
    return int(n)


def _entry_tag(entry: Mapping[str, Any]) -> str:
    """条目六类 tag（缺省 "event"——非六类不进冒险日志分组，工程补白 3）。"""
    return str(entry.get("tag") or "event")


def _split_ts(ts: Any) -> tuple:
    """条目时间戳 → (day, time)：ISO/日期串/对象拆日期与 HH:MM，缺省 ("--", "--")。"""
    if ts is None:
        return _MISSING, _MISSING
    if hasattr(ts, "strftime"):  # datetime 对象
        try:
            return ts.strftime("%Y-%m-%d"), ts.strftime("%H:%M")
        except Exception:
            return _MISSING, _MISSING
    s = str(ts).strip()
    if not s:
        return _MISSING, _MISSING
    day = s
    time = _MISSING
    if "T" in s:
        date_part, _, rest = s.partition("T")
        day = date_part
        time = rest[:5] if len(rest) >= 5 else rest
    elif " " in s:
        date_part, _, rest = s.partition(" ")
        day = date_part
        time = rest[:5] if len(rest) >= 5 else rest
    return day, time


def _entry_weather(entry: Mapping[str, Any]) -> str:
    """条目环境快照 weather（3f R-05 展示口径；缺失 → "--"）。"""
    snap = entry.get("snapshot")
    if isinstance(snap, Mapping):
        w = snap.get("weather")
        if w:
            return str(w)
    return _MISSING


def _params_of(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    """条目模板参数（params，缺省 {}；非 Mapping → {}）。"""
    p = entry.get("params")
    return p if isinstance(p, Mapping) else {}


def _count_key_name(entry: Mapping[str, Any]) -> str:
    """count_key 尾段兜底名：`[事件:XX:目标]` → 目标；无 → "". """
    ck = str(entry.get("count_key") or entry.get("event_id") or "")
    if ":" in ck:
        tail = ck.rsplit(":", 1)[-1].rstrip("]")
        return tail
    return ck.strip("[]")


def _entry_text(entry: Mapping[str, Any]) -> str:
    """六类条目文本（R-02 表逐类模板渲染，D-01 不落自由文本；参数缺省 count_key 尾段兜底）。"""
    tag = _entry_tag(entry)
    params = _params_of(entry)
    name = str(
        params.get("name") or params.get("item") or params.get("monster")
        or params.get("target") or ""
    )
    if not name:
        name = _count_key_name(entry)
    if tag == "first_kill":
        return f"首次击败 {name}" if name else "首次击败 未知目标"
    if tag == "first_crown":
        return f"首次钓获金冠 {name}" if name else "首次钓获金冠"
    if tag == "story_node":
        return f"剧情节点：{name}" if name else "剧情节点推进"
    if tag == "hidden_find":
        return f"首次发现隐藏要素『{name}』" if name else "首次发现隐藏要素"
    if tag == "milestone":
        pct = params.get("pct")
        if pct is not None:
            return f"图鉴完成度达到 {pct}%"
        return "图鉴里程碑达成"
    if tag == "codex_new":
        return f"图鉴新增：{name}" if name else "图鉴新增"
    # 非六类（防御路径，正常不进冒险日志分组）
    return str(entry.get("event_id") or entry.get("count_key") or "冒险记录")


def _render_adventure_line(entry: Mapping[str, Any]) -> str:
    """冒险日志条目行（对齐 3f L137 样例）：`[日志] {HH:MM} {天气} · {文本}` + 首见标记。"""
    _, time = _split_ts(entry.get("ts"))
    weather = _entry_weather(entry)
    line = f"[日志] {time} {weather} · {_entry_text(entry)}"
    if bool(entry.get("first_seen")):
        line += "【首见】"
    return line


def _cake_tail(page: int, total_pages: int, tip: str, clamped: bool) -> str:
    """CakeGame 式尾段（当前页 + 夹取提示 + Tip 尾行，顺序：当前页 →（已到最后一页）→ Tip）。"""
    tail = render_cake_tail(page, total_pages, tip=tip)
    if clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    return tail


# ---------------------------------------------------------------------------
# 冒险日志数据源（3f E-01 / ADR-05；兄弟路 read_log 惰性兜底）
# ---------------------------------------------------------------------------

def _resolve_read_log() -> Optional[Callable[..., Any]]:
    """惰性解析兄弟路 BCH-05 adventure_log.read_log（未落盘 → None，走本地兼容读）。

    用 importlib 按名加载（兄弟路文件未落盘时 ImportError 被吞 → None），避免顶层
    import 解析告警，也防兄弟路模块加载失败阻塞本模块导入。read_log 真实签名
    (ctx, tag=None, page=1) -> dict（分组页数据，见 _adventure_data 消费契约）。
    """
    try:
        mod = importlib.import_module("qbot_rpg.core.adventure_log")
        fn = getattr(mod, "read_log", None)
        if callable(fn):
            return cast(Callable[..., Any], fn)
    except Exception:
        pass
    return None


def _event_log_of(ctx: Mapping[str, Any]) -> list:
    """event_log 列表：persistent_state[\"event_log\"] 优先，ctx[\"event_log\"] 兜底（ADR-05）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, Mapping):
        raw = ps.get("event_log")
        if isinstance(raw, list):
            return raw
    raw = ctx.get("event_log")
    return raw if isinstance(raw, list) else []


def _local_entries(ctx: Mapping[str, Any]) -> list:
    """本地兼容读：raw event_log 条目（拷贝防改写；对齐兄弟路 read_log 的读取源口径）。"""
    return [dict(r) if isinstance(r, Mapping) else r for r in _event_log_of(ctx)]


def _flat_display_order(entries: Sequence[Any]) -> list:
    """展示顺序：六类固定组序 × 组内倒序（最新在前，3f R-03）；非六类条目过滤。"""
    buckets: dict = {tag: [] for tag in EVENT_GROUP_ORDER}
    for e in entries:
        tag = _entry_tag(e)
        if tag in buckets:
            buckets[tag].append(e)
    ordered: list = []
    for tag in EVENT_GROUP_ORDER:
        ordered.extend(reversed(buckets[tag]))
    return ordered


def _adventure_data(ctx: Mapping[str, Any], page: int) -> dict:
    """冒险日志分页数据（兄弟路 read_log 优先；本地兼容兜底）。

    出参 dict: {entries: {tag: [entry…]}（仅本页非空组，组序固定）, order: 六类固定组序,
    page: 夹取后页码, pages: 总页数, total: 总条数, page_size, clamped: 是否越界夹取}。
    核心逻辑: 兄弟路 read_log(ctx, page=page) 可用 → 透传（其已完成组内倒序/分页/夹取）；
    否则本地 `_flat_display_order` 展平 + resolve_page 分页（同 3f R-03 口径）。任何
    异常/形态不符 → 本地兜底，不抛错不阻塞（惰性 import 兜底纪律）。
    """
    reader = _resolve_read_log()
    if reader is not None:
        try:
            data = reader(ctx, page=page)
            if isinstance(data, Mapping) and isinstance(data.get("entries"), Mapping):
                entries_map = dict(data["entries"])
                order = list(data.get("order") or EVENT_GROUP_ORDER)
                total_pages = int(data.get("pages") or 1)
                total = int(data.get("total") or 0)
                resolved = int(data.get("page") or 1)
                return {
                    "entries": entries_map,
                    "order": order,
                    "page": resolved,
                    "pages": total_pages,
                    "total": total,
                    "page_size": int(data.get("page_size") or ADVENTURE_PAGE_SIZE),
                    "clamped": int(page) > total_pages,
                }
        except Exception:
            pass
    ordered = _flat_display_order(_local_entries(ctx))
    res = resolve_page(page, len(ordered), ADVENTURE_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 _parse_page_arg 判定并转 TPL-12（裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * ADVENTURE_PAGE_SIZE
    page_groups: dict = {}
    for e in ordered[start:start + ADVENTURE_PAGE_SIZE]:
        tag = _entry_tag(e)
        page_groups.setdefault(tag, []).append(e)
    return {
        "entries": page_groups,
        "order": list(EVENT_GROUP_ORDER),
        "page": res.page,
        "pages": res.total_pages,
        "total": res.total,
        "page_size": ADVENTURE_PAGE_SIZE,
        "clamped": res.clamped,
    }


# ---------------------------------------------------------------------------
# 冒险日志视图（3f R-03：分组展示 + 5 条/页 + 裁决② 夹取 + CakeGame 尾段）
# ---------------------------------------------------------------------------

def render_adventure_page(ctx: Mapping[str, Any], page: int) -> str:
    """冒险日志整页（R-03）：`【冒险日志】第 X 页 / 共 Y 页` + 分组条目 + CakeGame 尾段。

    入参 ctx: 玩家上下文（event_log/is_gm/settings 等）；page: 目标页码（1..，超页夹取）。
    出参 str（空日志 → 空文案）。核心逻辑: _adventure_data（兄弟路 read_log 优先）→
    按固定组序分组渲染（空组不渲染）→ 裁决② 夹取提示 + 当前页 + Tip 尾段。
    """
    data = _adventure_data(ctx, page)
    if not data["total"]:
        return _EMPTY_ADVENTURE
    lines: List[str] = [f"【冒险日志】第 {data['page']} 页 / 共 {data['pages']} 页"]
    for tag in data["order"]:
        group = data["entries"].get(tag) or []
        if not group:
            continue
        lines.append(f"■ {EVENT_GROUP_NAMES.get(tag, tag)}")
        for e in group:
            lines.append(_render_adventure_line(e))
    lines.append(_cake_tail(data["page"], data["pages"], _ADV_TAIL_TIP, data["clamped"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 传记视图（3f R-04：六类 × 自然日聚合叙述段，50 段环形，页码翻段）
# ---------------------------------------------------------------------------

def _bio_segments(ctx: Mapping[str, Any]) -> list:
    """传记聚合段（R-04/D-02 零新存储现算）：六类 × 自然日 → 段（计数 + 天气快照统计）。

    出参 list[dict]{day, tag, count, weather_counts}，按日倒序（同日按固定组序），
    截取最近 BIO_SEGMENT_CAP（50）段（超出覆盖最旧，环形口径）。
    """
    entries = _local_entries(ctx)
    by: dict = {}
    for e in entries:
        tag = _entry_tag(e)
        if tag not in EVENT_GROUP_NAMES:
            continue
        day, _ = _split_ts(e.get("ts"))
        key = (tag, day)
        by.setdefault(key, []).append(e)
    segments: list = []
    for (tag, day), items in by.items():
        weather_counts: dict = {}
        for e in items:
            w = _entry_weather(e)
            weather_counts[w] = weather_counts.get(w, 0) + 1
        segments.append({
            "day": day,
            "tag": tag,
            "count": len(items),
            "weather_counts": weather_counts,
        })
    rank = {tag: i for i, tag in enumerate(EVENT_GROUP_ORDER)}
    # 日倒序（ISO 字典序即时间序）；同日按固定组序（-rank 配合 reverse 得 rank 升序）
    segments.sort(key=lambda s: (s["day"], -rank.get(s["tag"], 99)), reverse=True)
    return segments[:BIO_SEGMENT_CAP]


def render_bio_page(ctx: Mapping[str, Any], page: int) -> str:
    """传记整段（R-04）：`【传记】第 X 段 / 共 Y 段` + 段头 + 快照统计 + CakeGame 尾段。

    入参 ctx: 玩家上下文；page: 段号（1..，无页码=最近 1 段，页码翻段，超段夹取）。
    出参 str（空 → 空文案）。核心逻辑: 聚合段列表 → 每页 1 段切片 → 段文本模板渲染
    （含计数与当日天气快照统计，如「雨夜×2」，支撑回溯规律）。
    """
    segments = _bio_segments(ctx)
    if not segments:
        return _EMPTY_BIO
    res = resolve_page(page, len(segments), 1)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 _parse_page_arg 判定并转 TPL-12（裁决②）"
        )
    assert res.page is not None
    seg = segments[res.page - 1]
    group_name = EVENT_GROUP_NAMES.get(seg["tag"], seg["tag"])
    weather = "、".join(
        f"{w}×{c}" for w, c in sorted(seg["weather_counts"].items())
    ) or _MISSING
    lines: List[str] = [f"【传记】第 {res.page} 段 / 共 {len(segments)} 段"]
    lines.append(f"■ {seg['day']} · {group_name}")
    lines.append(f"[传记] {group_name} {seg['count']} 条 · {weather}")
    lines.append(_cake_tail(res.page, res.total_pages, _BIO_TAIL_TIP, res.clamped))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GM 系统日志视图（3f R-06 / 细化_0 R-02：复用 GM 审计流 ctx["audit_log"]）
# ---------------------------------------------------------------------------

def _sys_default_show(ctx: Mapping[str, Any]) -> int:
    """sys_log.default_show（默认展示条数，可配；缺省 20）。"""
    s = ctx.get("settings")
    if isinstance(s, Mapping):
        node = s.get("sys_log")
        if isinstance(node, Mapping):
            v = node.get("default_show")
            if isinstance(v, int) and v > 0:
                return v
    return SYS_LOG_DEFAULT_SHOW


def _sys_page_size(ctx: Mapping[str, Any]) -> int:
    """sys_log.page_size（每页条数，可配；缺省 20）。"""
    s = ctx.get("settings")
    if isinstance(s, Mapping):
        node = s.get("sys_log")
        if isinstance(node, Mapping):
            v = node.get("page_size")
            if isinstance(v, int) and v > 0:
                return v
    return SYS_LOG_PAGE_SIZE


def _sys_max_entries(ctx: Mapping[str, Any]) -> int:
    """sys_log.max_entries（保留窗口，可配；缺省 50，超出覆盖最旧）。"""
    s = ctx.get("settings")
    if isinstance(s, Mapping):
        node = s.get("sys_log")
        if isinstance(node, Mapping):
            v = node.get("max_entries")
            if isinstance(v, int) and v > 0:
                return v
    return SYS_LOG_MAX_ENTRIES


def _sys_window(ctx: Mapping[str, Any], count: int) -> list:
    """系统日志窗口（D-03 复用 GM 审计流 ctx[\"audit_log\"]）：保留窗口内最近 count 条，倒序。"""
    log = ctx.get("audit_log")
    if not isinstance(log, list):
        return []
    max_entries = _sys_max_entries(ctx)
    window = log[-max_entries:] if max_entries > 0 else list(log)
    return list(reversed(window))[: max(0, int(count))]


def _render_sys_line(record: Mapping[str, Any]) -> str:
    """单条系统日志事件行（D-03 复用 gm_commands.render_log_line，惰性 import；兜底本地格式）。"""
    try:
        from qbot_rpg.commands.gm_commands import render_log_line

        return render_log_line(record)
    except Exception:
        ts = str(record.get("ts") or "?")
        if "T" in ts:
            ts = ts.split("T", 1)[1][:8]
        cmd = str(record.get("command") or "?")
        params = str(record.get("params") or "").strip()
        result = str(record.get("result") or "?")
        qq = str(record.get("qq") or "?")
        line = f"[{ts}] /{cmd}"
        if params:
            line += f" {params}"
        return f"{line} {result} by {qq}"


def render_system_log_page(ctx: Mapping[str, Any], page: int, count: Optional[int] = None) -> str:
    """GM 系统日志整页（R-06）：`【系统日志】第 X 页 / 共 Y 页` + 事件行 + CakeGame 尾段。

    入参 ctx: GM 上下文（audit_log/settings）；page: 目标页码；count: 展示条数
    （缺省 sys_log.default_show=20，上限保留窗口 50）。出参 str（空 → 空文案）。
    核心逻辑: 保留窗口（max_entries）→ 最近 count 条倒序 → page_size 分页（缺省 20）
    → 裁决② 夹取 + 当前页 + Tip 尾段；不含玩家六类记录内容（R-06 隔离）。
    """
    show = int(count) if count is not None and int(count) > 0 else _sys_default_show(ctx)
    events = _sys_window(ctx, min(show, _sys_max_entries(ctx)))
    if not events:
        return _EMPTY_SYS
    per_page = _sys_page_size(ctx)
    res = resolve_page(page, len(events), per_page)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 _parse_page_arg 判定并转 TPL-12（裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * per_page
    slice_events = events[start:start + per_page]
    lines: List[str] = [f"【系统日志】第 {res.page} 页 / 共 {res.total_pages} 页"]
    for rec in slice_events:
        lines.append(_render_sys_line(rec))
    lines.append(_cake_tail(res.page, res.total_pages, _SYS_TAIL_TIP, res.clamped))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口（3f R-01 权限分支 + ADR-09：is_gm=True，handler 内按权限分支）
# ---------------------------------------------------------------------------

def _cmd_sys_log(parsed: Any, ctx: MutableMapping[str, Any], args: List[str]) -> str:
    """GM 系统日志子处理：页码（缺省 1）+ 可选 kv 条数=N（上限保留窗口 50）。"""
    args = list(args or [])
    count = _sys_default_show(ctx)
    for kv in getattr(parsed, "kv", None) or []:
        if isinstance(kv, Mapping) and kv.get("key") == "条数":
            n = parse_int(str(kv.get("value") or ""))
            if n is None or n < 1:
                return format_tpl12(_fragment(parsed))
            count = min(int(n), _sys_max_entries(ctx))
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = _parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    try:
        return render_system_log_page(ctx, page, count)
    except ValueError:
        return format_tpl12(_fragment(parsed))


def cmd_log(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/日志 主入口（3f R-01 权限分支 + TC-01）：

    - 玩家执行 /日志 [页码] → 冒险日志视图（六类分组 5 条/页）；/日志 传记 [段号] → 传记视图；
    - GM 执行 /日志（含显式「系统」子词）→ 系统日志视图（R-06）；
    - 无 GM 权限执行 GM 视图（/日志 系统）→ PERMISSION_DENIED（3c 权限拒绝模板，
      不泄露系统日志内容）；
    - 页码非法（0/负数/非数字/超参）→ TPL-12（3d §5.1 / 裁决②）。
    """
    if getattr(parsed, "error", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    first = str(args[0]) if args else ""
    if first in GM_VIEW_WORDS:
        if not bool(ctx.get("is_gm", False)):
            return PERMISSION_DENIED
        return _cmd_sys_log(parsed, ctx, args[1:])
    if bool(ctx.get("is_gm", False)):
        # 3f R-01：GM 执行 /日志 走系统日志视图
        return _cmd_sys_log(parsed, ctx, args)
    if first == BIO_SUBWORD:
        page = _parse_page_arg(args[1] if len(args) > 1 else None)
        if page is None:
            return format_tpl12(_fragment(parsed))
        try:
            return render_bio_page(ctx, page)
        except ValueError:
            return format_tpl12(_fragment(parsed))
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = _parse_page_arg(first or None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    try:
        return render_adventure_page(ctx, page)
    except ValueError:
        return format_tpl12(_fragment(parsed))


# ---------------------------------------------------------------------------
# 装配（Router 注册；ADR-09：is_gm=True 保留 GM 强制 / 前缀；make_context 装配注入）
# ---------------------------------------------------------------------------

def register_log_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把「日志」注册进 Router（ADR-09：is_gm=True → 路由层强制 / 前缀 W07/L128 + 快捷禁绑
    C02 + 执行层二次检查位 E02；handler 内按 ctx[\"is_gm\"] 分支玩家/GM 双视图）。

    :param make_context: ParsedCommand → 玩家 ctx dict（event_log/is_gm/settings/
        season/period/weather/audit_log 等，见本模块各渲染函数消费契约）。None 时
        handler 调用抛 RuntimeError（【待接线】装配层注入；此时若 runner 注入
        ctx=ctx 则回退用之）。
    返回 router（链式，与 A-02 REGISTER_GROUPS 收口同款签名）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】log_commands.register_log_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _log(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx")
        if isinstance(injected, MutableMapping):
            return cmd_log(parsed, injected)
        return cmd_log(parsed, _ctx(parsed))

    router.register(CommandSpec(LOG_CMD, handler=_log))
    return router
