"""批36 · X2 `/采集` 指令壳（qbot_rpg/commands/gather_commands.py）。

定位：世界层指令壳——把一次 `/采集` 接到 `qbot_rpg.core.gathering`（纯函数引擎），
产出材料走**既有入包链路**，冷却增量写回玩家上下文；本壳零守卫以外的资源写入
（原子性由装配层 save_player 包裹，对齐 forge/alchemy 口径）。

形态（【总纲】L1280）：`/采集`（**无参数**——「在当前地图采集（采集点配置；怪物数量为
0=无限资源的地图可无限采集）」）。带参 → 人话用法提示（不静默，对齐 /休息 先例）。

挖掘通道：定稿把「挖掘」写作**素材来源通道/产物族（矿石系）**，无独立指令、gather_points
schema 亦无通道字段（【锻造】L151-158 + 审计四方 L405）→ 本壳**不新造 `/挖掘`**；矿石系
与草药系采集点同引擎同入口（依据与待裁决见 docs/采集挖掘_实现口径.md §四 GA-1）。

依据：
  · docs/采集挖掘_实现口径.md（本批调研：定稿原句 + 行号 + 对照 + 范围 + 待裁决）；
  · 2a1d §一 GP-01~GP-11 / L72 判定时序 / GP-07 刷新 / TC-01~TC-04；
  · 【总纲】L1280/L1305（/采集 形态 + 进图直接采集）；【时间天气】L204-207（天气修正）；
  · 模式参考：commands/fishing_commands.py（_render/tpl_of + _body_args + _current_map_node）
    与 commands/forge_commands.py::_add_item（入包 hook 优先 / inventory 兜底）。

【工程补白 · 显式标注】
  G-1  冷却状态落点 = ctx["gather_state"]（dict；键 "<map_id>:<point_id>" → ready_at 秒）。
       本壳只做**就地写回**，落盘由装配层 save_player 统一负责（引擎纯函数不回写）。
  G-2  批量产出逐件入包（每点 1 件，材料 id）；入包失败（无 hook 且无 inventory）→
       该行降级为 ❌ 入包失败，且**不写冷却**（防空耗）。
  G-3  消息行序：产出 → 落空 → 冷却 → 时节门控 → 天气不出；空态兜底走
       gather_cooling / gather_gated / gather_none 聚合文案。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.core.gathering import (
    GATHER_STATE_KEY,
    gather,
)
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）

__all__ = [
    "GATHER_CMD",
    "RARITY_CN",
    "cmd_gather",
    "register_gather_commands",
]

# 指令名（DEFAULT_WHITELIST 已含「采集」，见 commands/parsers.py）
GATHER_CMD: str = "采集"

# 稀有度中文名（档位表取 core.weather_consumers.RARITY_TIERS：普通/稀有/金色/觉醒）
RARITY_CN: Mapping[str, str] = {
    "normal": "普通",
    "rare": "稀有",
    "gold": "金色",
    "awakened": "觉醒",
}

# 季节/时段中文名（门控行兜底展示）
_SEASON_CN: Mapping[str, str] = {
    "spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬",
}
_PERIOD_CN: Mapping[str, str] = {
    "dawn": "晨", "noon": "午", "dusk": "昏", "night": "夜", "midnight": "午夜",
}

# 本地 fallback 文案（F-6 同款：tpl_of 命中全量模板表则以表为准；本组逐字镜像表内文案）
_DEF_GATHER_HEADER: str = "【采集】{map_name}"
_DEF_GATHER_EMPTY: str = "❌ 本图没有采集点\n发 地图 换个地方"
_DEF_GATHER_NO_LOCATION: str = "❌ 位置未知\n发 位置 查看当前位置"
_DEF_GATHER_USAGE: str = "❌ 采集 不需要参数\n发 采集 直接采集"
_DEF_GATHER_PRODUCE_LINE: str = "✅ 采到 {item}（{rarity}）"
_DEF_GATHER_MISS_LINE: str = "{point}：什么也没采到"
_DEF_GATHER_COOLING_LINE: str = "{point}：采空了\n{minutes} 分钟后恢复"
_DEF_GATHER_GATED_LINE: str = "{point}：当前{which}不出"
_DEF_GATHER_BLOCKED_LINE: str = "{point}：{weather}天不出"
_DEF_GATHER_NONE: str = "❌ 这次什么也没采到\n发 采集 再试一次"
_DEF_GATHER_GATED: str = "❌ 当前时节没有可采的点\n换个时段或季节再来"
_DEF_GATHER_COOLING: str = "❌ 采集点都在恢复中\n{minutes} 分钟后再来"
_DEF_GATHER_UNLIMITED: str = "本图资源无限\n可反复采集"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------
def _render(ctx: Mapping[str, Any], key: str, fallback: str, data: Mapping[str, Any]) -> str:
    """模板渲染：tpl_of 优先（全量模板表；内容包可覆盖）；空串 → 本地 fallback 兜底。"""
    rendered = tpl_of(ctx, key, data)
    if rendered:
        return rendered
    try:
        return fallback.format_map(data)
    except (KeyError, ValueError):
        return fallback


def _body_args(parsed: Any) -> List[str]:
    """参数提取（对齐 fishing_commands._body_args）：tokens[1:] 优先，args 兜底。"""
    raw_tokens = list(getattr(parsed, "tokens", None) or [])
    if raw_tokens:
        return [str(t) for t in raw_tokens[1:]]
    args = list(getattr(parsed, "args", None) or [])
    return [str(a) for a in args]


def current_map_node(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """当前地图节点：ctx["maps"] 按 ctx["location"] 定位（list / Mapping 双形态兼容）。

    缺失/未定位 → None（调用方转「位置未知」空态，不崩）。同 fishing_commands 口径。
    """
    location = ctx.get("location")
    maps = ctx.get("maps")
    if isinstance(maps, Mapping):
        node = maps.get(location) if isinstance(location, str) else None
        return node if isinstance(node, Mapping) else None
    if isinstance(maps, (list, tuple)):
        loc = str(location or "")
        for e in maps:
            if isinstance(e, Mapping) and str(e.get("id") or "") == loc:
                return e
        return None
    return None


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """入包（对齐 forge_commands._add_item：ctx["add_item"] hook 优先；inventory 兜底）。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, False))
        except Exception:  # noqa: BLE001 —— 入包失败按失败处理（调用方不写冷却）
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _apply_state(ctx: MutableMapping[str, Any], updates: Mapping[str, float]) -> None:
    """冷却增量就地写回（G-1）：ctx["gather_state"][<map>:<point>] = ready_at。

    非 MutableMapping / 不可赋值 → 跳过（不崩；落盘由装配层统一负责）。
    """
    if not updates:
        return
    state = ctx.get(GATHER_STATE_KEY)
    if not isinstance(state, MutableMapping):
        state = {}
        try:
            ctx[GATHER_STATE_KEY] = state
        except (TypeError, KeyError):
            return
    for key, ready_at in updates.items():
        state[key] = ready_at


def _item_name(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品 id → 展示名（items 表 name；缺省回退原 id）。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    elif isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                name = e.get("name")
                if isinstance(name, str) and name:
                    return name
    return item_id


def _minutes(seconds: float) -> int:
    """剩余秒 → 分钟（向上取整；至少 1 分钟，避免「0 分钟后恢复」）。"""
    return max(1, int((float(seconds) + 59.0) // 60.0))


def _gate_which(seasons: List[str], periods: List[str]) -> str:
    """门控展示词：优先时段，其次季节，都无 → 「时节」。"""
    if periods:
        return "/".join(_PERIOD_CN.get(p, p) for p in periods)
    if seasons:
        return "/".join(_SEASON_CN.get(s, s) for s in seasons)
    return "时节"


# ---------------------------------------------------------------------------
# /采集 主入口
# ---------------------------------------------------------------------------
def cmd_gather(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/采集 主入口（纯逻辑 + 注入 rng/now；产出走入包链路）。

    路由：带参 → 用法提示；无参 → 结算当前地图全部采集点（引擎 gather），渲染结果并把
    冷却增量写回 ctx["gather_state"]。所有分支均有**人话提示**，无静默空回。
    """
    if _body_args(parsed):
        return _render(ctx, "gather_usage", _DEF_GATHER_USAGE, {})

    node = current_map_node(ctx)
    if node is None:
        return _render(ctx, "gather_no_location", _DEF_GATHER_NO_LOCATION, {})

    map_id = str(node.get("id") or ctx.get("location") or "")
    map_name = str(node.get("name") or map_id or "--")

    result = gather(
        node,
        map_id,
        season=ctx.get("season"),
        period=ctx.get("period"),
        weather=ctx.get("weather"),
        state=ctx.get(GATHER_STATE_KEY),
        rng=ctx.get("rng"),
        now=ctx.get("now"),
    )
    if not result.get("ok"):
        return _render(ctx, "gather_empty", _DEF_GATHER_EMPTY, {})

    lines: List[str] = [
        _render(ctx, "gather_header", _DEF_GATHER_HEADER, {"map_name": map_name})
    ]

    # ① 产出（逐件入包；成功才写冷却，G-2）
    applied_updates: Dict[str, float] = {}
    updates = result.get("state_updates") or {}
    for item in result["produced"]:
        ok = _add_item(ctx, str(item["item"]), 1)
        if not ok:
            lines.append(_render(ctx, "gather_blocked_line", _DEF_GATHER_BLOCKED_LINE,
                                 {"point": item["name"], "weather": "入包失败"}))
            continue
        rarity = RARITY_CN.get(str(item["rarity"]), str(item["rarity"]))
        lines.append(_render(ctx, "gather_produce_line", _DEF_GATHER_PRODUCE_LINE,
                             {"item": _item_name(ctx, str(item["item"])), "rarity": rarity}))
        key = f"{map_id}:{item['point_id']}"
        if key in updates:
            applied_updates[key] = updates[key]
    _apply_state(ctx, applied_updates)

    # ② 落空 / 冷却 / 时节门控 / 天气不出（人话提示）
    for item in result["missed"]:
        lines.append(_render(ctx, "gather_miss_line", _DEF_GATHER_MISS_LINE,
                             {"point": item["name"]}))
    for item in result["cooling"]:
        lines.append(_render(ctx, "gather_cooling_line", _DEF_GATHER_COOLING_LINE,
                             {"point": item["name"],
                              "minutes": _minutes(item["remaining_sec"])}))
    for item in result["gated"]:
        lines.append(_render(ctx, "gather_gated_line", _DEF_GATHER_GATED_LINE,
                             {"point": item["name"],
                              "which": _gate_which(item["seasons"], item["periods"])}))
    for item in result["blocked"]:
        weather = item.get("weather")
        lines.append(_render(ctx, "gather_blocked_line", _DEF_GATHER_BLOCKED_LINE,
                             {"point": item["name"],
                              "weather": str(weather) if weather else "当前天气"}))

    # ③ 空态兜底（理论上 ① / ② 已覆盖；防御性保留，且用上聚合文案）
    if len(lines) == 1:
        if result["cooling"]:
            lines.append(_render(ctx, "gather_cooling", _DEF_GATHER_COOLING, {
                "minutes": _minutes(min(i["remaining_sec"] for i in result["cooling"]))}))
        elif result["gated"]:
            lines.append(_render(ctx, "gather_gated", _DEF_GATHER_GATED, {}))
        else:
            lines.append(_render(ctx, "gather_none", _DEF_GATHER_NONE, {}))

    if result.get("unlimited") and result["produced"]:
        lines.append(_render(ctx, "gather_unlimited", _DEF_GATHER_UNLIMITED, {}))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 装配：register_gather_commands
# ---------------------------------------------------------------------------
def register_gather_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /采集 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 maps/location/season/period/
        weather/items/inventory/rng/now 等）。None 时 handler 调用抛 RuntimeError
        （【待接线】装配层注入，对齐 fishing/forge_commands 口径）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "gather_commands.register_gather_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _gather(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_gather(parsed, injected)
        return cmd_gather(parsed, _ctx(parsed))

    router.register(CommandSpec(GATHER_CMD, handler=_gather))
    return router
