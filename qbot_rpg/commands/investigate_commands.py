"""M7 3f F-05~F-07 /调查 指令壳 + maps 扩展（qbot_rpg/commands/investigate_commands.py）。

承接 docs/细化/细化_3f_单机向体验.md（权威契约，全篇行号引用）：

  - R-07（§2.1 指令签名与总则）：`/调查 [目标]`（目标可选：交互点别名 / 地图名 /
    省略=当前地图）；不提示原则——无交互点、或 lore condition 不满足时回复**泛化环境
    文本**，绝不出现「此处似乎有什么」「再调查看看」类暗示。
  - R-08（§2.2 交互点文本彩蛋）：maps.json `interact_points[]`（E-02 schema）；/调查
    别名命中 → 彩蛋正文 + 发现卡片 + [事件:隐藏发现:ID] 计数。
  - R-09（§2.3 特定时段蹲点）：/调查 目标为隐藏要素所在地图/代号，当前时刻满足限定
    窗口（[季节]+[时段]+[天气] 组合）且其余条件满足 → 隐藏 BOSS 现身；窗口外 → 泛化
    文本零暗示；蹲点成功输出：环境演出文本（狼嗥）→ 图鉴传闻引用 → 发现卡片 → 进入
    BOSS 战信号（F-08 R-12 接线归 BCH-07 本批：ctx 有 battle 发起能力时接进真实 BOSS
    战，无则保持信号文本）。
  - R-11（§2.5 频控与冷却，D-04）：一次 /调查 最多输出 1 条演出/揭示；daily 配额
    （揭示类命中每日上限 3 次，可配；泛化文本不计配额，超限 → 泛化文本）；去重——
    已 one_shot 的只回简短确认（无彩蛋正文、无揭示卡片）。
  - R-15（§3.5 仪式感揭示）：一次性揭示卡片（⛩️ 在 3d §四 emoji 纪律下禁用以文本
    【发现】卡片替代）+ 首见日志 + [事件:隐藏发现:ID] 计数。
  - F-07（§2.4 隐藏地图揭示）：/调查 当前地图，地图级 lore condition 满足 → 一次性
    揭示隐藏地图入口（介绍文本）。

引擎接线（兄弟路 core/investigate.py 已落盘，真实签名已 read 核对）：
  investigate_map(ctx, map_def, target=None, *, today=None) -> dict
    {kind, text, hidden_find_id?, one_shot?, quota_remaining, first_seen?,
     boss_ref?, map_ref?, interact_point_id?}；kind ∈ generic / egg / egg_confirm /
    map_reveal / map_reveal_confirm / hunt（L503-579）。
  本壳**惰性 import 优先消费**（改引擎不动本壳）；未落盘/异常/形态不符 → 本地兼容
  引擎 investigate_map_local 兜底（R-07~R-11 契约，存储键与兄弟路对齐）。

【工程补白 · 显式标注】
  1) 本地兜底引擎（investigate_map_local）仅在兄弟路不可用时触发；其一次性去重落点
     与配额落点**对齐兄弟路**（persistent_state["investigate_revealed"] 列表 /
     persistent_state["investigate_quota"] = {今日: 计数}），两引擎可互换不冲突。
  2) 本地兜底的地图级彩蛋（R-07 2.1「命中地图级彩蛋」）：无目标 /调查 当前地图时，
     按索引序取首个 lore condition 满足且未发现的交互点作为地图级彩蛋（契约未定义
     地图级彩蛋与交互点彩蛋的精确分野，取最简口径）。
  3) 本地兜底的隐藏 BOSS 蹲点行 schema（E-03 载体 = maps.json 怪物行限定窗口，契约
     未给逐字字段名）：怪物行带 `hidden_boss: true`（或 `boss: true` + `window`）即
     蹲点目标；`window` 接受两种形态——条件表达式（var/all/any/not → 统一条件引擎）
     或 {season, period, weather} 直接值形态（值为 str/list，全匹配才通过）。
  4) 泛化文本（R-22 / R-07 零暗示）：环境快照头 `（季节·时段·天气）` + 中性文本池，
     rng 确定性选择（rng 注入；未注入 → 池首条），池内零暗示措辞。
  5) 渲染兜底：hunt 的图鉴传闻引用仅在引擎提供 `lore` 字段时渲染（本地兜底由怪物行
     codex_ref 提供；兄弟路未提供则不拼接——壳层不凭空编造 lore 内容）。
  6) 环境值语言透传：season/period/weather 直接 str() 渲染（对齐 event_bus._snapshot_of
     透传口径）；窗口匹配用同一 ctx 值比对（测试/装配以英文枚举值注入，对齐 2a1b
     SEASONS_ENUM / PERIODS_ENUM 与条件引擎取值通道）。
  7) hunt → BOSS 战接线（3f R-12 / F-08，BCH-07 本批）：hunt 信号出现时经
     launch_hunt_battle 接进真实 BOSS 战发起——ctx["start_battle"] hook 优先（装配层
     注入，start_battle(ctx, boss_ref) -> dict），ctx["battle_engine"] 次之（callable
     或带 start_battle/launch/start 方法的发起接口，同签名 (ctx, boss_ref) -> dict）；
     无发起能力/发起失败 → 保持既有信号文本（最小侵入，未装配战斗时不改变行为）。
     boss_ref 取 result.boss_ref，兜底 boss/enemy/title（兼容本地兜底引擎无 boss_ref 形态）。

铁律：零 NoneBot import；纯函数确定性（rng/now/today 由 ctx 注入）；每函数 docstring；
无装饰 emoji（3d §四：仅 ✅/❌ 功能性标记 + 排版符号；⛩️ 等装饰性 emoji 禁用）。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.commands.sender import format_tpl12
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）

__all__ = [
    "INVESTIGATE_CMD",
    "KIND_HUNT",
    "KIND_HIDDEN_MAP",
    "KIND_EGGSHELL",
    "KIND_AMBIENT",
    "INVESTIGATE_QUOTA_PS_KEY",
    "INVESTIGATE_QUOTA_DEFAULT_DAILY",
    "INVESTIGATE_REVEALED_PS_KEY",
    "cmd_investigate",
    "investigate_map_local",
    "render_investigate_result",
    "launch_hunt_battle",
    "register_investigate_commands",
]

# ---------------------------------------------------------------------------
# 指令与常量（3f R-07 / R-11）
# ---------------------------------------------------------------------------

INVESTIGATE_CMD = "调查"

# 壳渲染分支（任务契约四分支；本地兜底引擎词汇）
KIND_HUNT = "hunt"              # 隐藏 BOSS 蹲点成功（R-09）
KIND_HIDDEN_MAP = "hidden_map"  # 隐藏地图入口一次性揭示（F-07 / §2.4；= 兄弟路 map_reveal）
KIND_EGGSHELL = "eggshell"      # 交互点文本彩蛋（R-08；= 兄弟路 egg）
KIND_AMBIENT = "ambient"        # 泛化环境文本（R-22 零暗示；= 兄弟路 generic）

# daily 配额（R-11 / D-04）：揭示类命中每日上限，可配 settings.investigate.daily_quota
INVESTIGATE_QUOTA_PS_KEY = "investigate_quota"
INVESTIGATE_QUOTA_DEFAULT_DAILY = 3

# one_shot 去重落点（对齐兄弟路 core/investigate.py REVEALED_KEY：列表）
INVESTIGATE_REVEALED_PS_KEY = "investigate_revealed"

# RUL-08 注册门槛（对齐 explore_commands / basic_commands；文本 investigate_tpl 分区，渲染 tpl_of）
_TPL_REGISTER_GATE_KEY = "investigate_register_gate"

# 无当前位置调查兜底（R-07 无 map_def 场景；文本 investigate_tpl 分区，渲染 tpl_of）
_TPL_NO_MAP_KEY = "investigate_no_map"

# 泛化环境文本池 key 序（R-22 / R-07 零暗示：绝无「此处有隐藏」类措辞，工程补白 4）
_AMBIENT_POOL_KEYS: tuple = (
    "investigate_ambient_1",
    "investigate_ambient_2",
    "investigate_ambient_3",
    "investigate_ambient_4",
    "investigate_ambient_5",
)

# 去重简短确认 key（R-11 / TC-15：已 one_shot 只回简短确认，无正文无卡片）
_EGGSHELL_DONE_KEY = "investigate_eggshell_done"
_HUNT_DONE_KEY = "investigate_hunt_done"
_HIDDEN_MAP_DONE_KEY = "investigate_hidden_map_done"

# 蹲点默认演出/信号 key（R-09 / 3f L101-106；信号默认文本 BCH-07 更新——BOSS 战接线
# 已交付，移除「接线归后续批次」占位；hunt 实际发起见 launch_hunt_battle 工程补白 7）
_DEFAULT_HUNT_INTRO_KEY = "investigate_hunt_intro"
_DEFAULT_HUNT_SIGNAL_KEY = "investigate_hunt_signal"

# 隐藏地图入口揭示默认介绍 key（F-07 无 intro/desc 时兜底）
_DEFAULT_HIDDEN_MAP_TEXT_KEY = "investigate_hidden_map_text"


# ---------------------------------------------------------------------------
# 基础工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 basic/explore 同口径）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    return "/" + str(getattr(parsed, "command", "") or "")


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛：registered is False → 拦截文案（缺省视为已注册，对齐 basic）。"""
    if ctx.get("registered", True) is False:
        return tpl_of(ctx, _TPL_REGISTER_GATE_KEY)
    return None


def _map_raw(map_def: Any) -> Mapping[str, Any]:
    """map_def（MapDef 或 raw dict）→ raw dict；None/异常形态 → 空表。

    MapDef 的 raw 镜像优先；MapDef 直接（无 raw）→ 仅保留 id。
    """
    if map_def is None:
        return {}
    raw = getattr(map_def, "raw", None)
    if isinstance(raw, Mapping):
        return raw
    if isinstance(map_def, Mapping):
        return map_def
    return {"id": str(getattr(map_def, "id", "") or "")}


def _env_header(ctx: Mapping[str, Any]) -> str:
    """环境快照头（3f R-05 展示口径）：`（{季节}·{时段}·{天气}）`，缺失 → "--"。

    值透传 ctx season/period/weather（对齐 event_bus._snapshot_of），不做语言映射；
    文本 investigate_tpl 分区（investigate_env_header），渲染 tpl_of。
    """
    s = str(ctx.get("season") or "--")
    p = str(ctx.get("period") or "--")
    w = str(ctx.get("weather") or "--")
    return tpl_of(ctx, "investigate_env_header", {"season": s, "period": p, "weather": w})


def _ambient_text(ctx: Mapping[str, Any]) -> str:
    """泛化环境文本（R-22 / R-07 零暗示）：环境快照头 + 中性文本池，rng 确定性选择。

    rng 注入（ctx["rng"]）→ randrange 选池条（同 rng 同调用序确定性）；未注入/异常 →
    池首条。池条目 = investigate_tpl 分区逐个 key（investigate_ambient_1..5），渲染 tpl_of；
    快照头与池条零暗示措辞（工程补白 4）。
    """
    rng = ctx.get("rng")
    pool = [tpl_of(ctx, k) for k in _AMBIENT_POOL_KEYS]
    line = pool[0]
    if rng is not None and hasattr(rng, "randrange"):
        try:
            line = pool[rng.randrange(len(pool))]
        except Exception:
            pass
    header = _env_header(ctx)
    return f"{header}\n{line}" if header else line


def _enemy_name(ctx: Mapping[str, Any], ref: object) -> str:
    """怪物引用 → 怪物名（ctx monsters/enemies 映射查名；未知 → 原引用串）。

    兼容 {id: {name}} 映射与 [{id, name}] 列表两形态（对齐 explore_commands._monster_names）。
    """
    if ref is None:
        return ""
    s = str(ref)
    if not s:
        return ""
    src = ctx.get("monsters")
    if src is None:
        src = ctx.get("enemies")
    if isinstance(src, Mapping):
        entry = src.get(s)
        if isinstance(entry, Mapping):
            nm = entry.get("name")
            if isinstance(nm, str) and nm:
                return nm
    elif isinstance(src, (list, tuple)):
        for e in src:
            if isinstance(e, Mapping) and str(e.get("id") or "") == s:
                nm = e.get("name")
                if isinstance(nm, str) and nm:
                    return nm
    return s


def _boss_name(ctx: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """hunt 结果 → BOSS 显示名：title 优先，boss_ref 查名兜底。"""
    title = result.get("title")
    if isinstance(title, str) and title:
        return title
    ref = result.get("boss_ref")
    if ref:
        return _enemy_name(ctx, ref)
    return ""


# ---------------------------------------------------------------------------
# maps / 交互点解析（本地兜底引擎用；兄弟路引擎自持解析）
# ---------------------------------------------------------------------------

def _maps_index(ctx: Mapping[str, Any]) -> dict:
    """ctx maps → {map_id: raw dict} 索引（兼容 modules dict / 映射 / 列表三形态）。

    与 movement._maps_index 同源口径；MapDef 条目取其 raw 镜像；raw 缺 id → 键兜底。
    """
    raw = ctx.get("maps")
    index: dict = {}
    if isinstance(raw, Mapping):
        inner = raw.get("maps")
        if isinstance(inner, list):
            for m in inner:
                if isinstance(m, Mapping) and m.get("id"):
                    index[str(m["id"])] = m
        else:
            for k, v in raw.items():
                if hasattr(v, "raw"):  # MapDef 鸭子类型（raw 镜像）
                    mid = getattr(v, "id", None) or str(k)
                    raw_v = getattr(v, "raw", None)
                    index[str(mid)] = raw_v if isinstance(raw_v, Mapping) else {"id": str(mid)}
                elif isinstance(v, Mapping):
                    entry = dict(v)
                    if not entry.get("id"):
                        entry["id"] = str(k)
                    index[str(k)] = entry
    elif isinstance(raw, (list, tuple)):
        for m in raw:
            if hasattr(m, "raw"):  # MapDef 鸭子类型（raw 镜像）
                mid = getattr(m, "id", None)
                if mid:
                    raw_m = getattr(m, "raw", None)
                    index[str(mid)] = raw_m if isinstance(raw_m, Mapping) else {"id": str(mid)}
            elif isinstance(m, Mapping) and m.get("id"):
                index[str(m["id"])] = m
    return index


def _resolve_map_def(ctx: Mapping[str, Any]) -> Optional[Any]:
    """当前地图 map_def：ctx["map_def"] 直接 → game_world.get_map(location) → maps 索引。

    装配 ctx 已注入 ctx["map_def"]（兄弟路未实装时 None）；get_map 抛 NotImplementedError
    （GameWorld 占位）→ 安全兜底走 maps 索引（对齐 _get_map 的 _safe_call 口径）。
    """
    md = ctx.get("map_def")
    if md is not None and (isinstance(md, Mapping) or hasattr(md, "raw")):
        return md
    loc = ctx.get("location")
    if loc:
        gw = ctx.get("game_world")
        if gw is not None:
            fn = getattr(gw, "get_map", None)
            if callable(fn):
                try:
                    m = fn(loc)
                    if m is not None:
                        return m
                except Exception:
                    pass
        index = _maps_index(ctx)
        if loc in index:
            return index[loc]
    return None


def _map_by_ref(ctx: Mapping[str, Any], ref: str) -> Optional[Any]:
    """目标引用 → 地图（raw dict）：id 精确匹配优先，name 精确匹配次之；未知 → None。

    本地兜底引擎的 R-09 蹲点目标解析用（/调查 地图名）；name 匹配按全等（地图名禁空格）。
    """
    index = _maps_index(ctx)
    if ref in index:
        return index[ref]
    for entry in index.values():
        if str(entry.get("name") or "") == ref:
            return entry
    return None


def _interact_points(raw: Mapping[str, Any]) -> tuple:
    """maps.json interact_points[]（E-02）→ Mapping 条目元组（非 list/非法行跳过）。"""
    pts = raw.get("interact_points")
    if not isinstance(pts, list):
        return ()
    return tuple(p for p in pts if isinstance(p, Mapping))


def _match_interact_point(raw: Mapping[str, Any], alias: str) -> Optional[Mapping[str, Any]]:
    """交互点匹配（R-08：/调查 目标匹配用）：id 精确 / alias 列表含 / alias 字符串。"""
    for p in _interact_points(raw):
        if str(p.get("id") or "") == alias:
            return p
        al = p.get("alias")
        if isinstance(al, (list, tuple)) and alias in [str(a) for a in al]:
            return p
        if isinstance(al, str) and al == alias:
            return p
    return None


def _point_title(point: Mapping[str, Any]) -> str:
    """交互点显示名：name → id → 首个 alias；全缺 → ""。"""
    name = point.get("name")
    if isinstance(name, str) and name:
        return name
    pid = point.get("id")
    if isinstance(pid, str) and pid:
        return pid
    al = point.get("alias")
    if isinstance(al, (list, tuple)) and al:
        return str(al[0])
    if isinstance(al, str) and al:
        return al
    return ""


def _point_by_id(ctx: Mapping[str, Any], pid: object) -> Optional[Mapping[str, Any]]:
    """按交互点 id 在 ctx 当前地图 interact_points 中取条目（未知 → None）。

    兄弟路 egg 结果仅回 interact_point_id，壳层据此解析显示名（name/别名）。
    """
    if pid is None:
        return None
    raw = _map_raw(ctx.get("map_def"))
    s = str(pid)
    for p in _interact_points(raw):
        if str(p.get("id") or "") == s:
            return p
    return None


def _map_name_by_ref(ctx: Mapping[str, Any], ref: object) -> str:
    """隐藏地图 map_ref → 地图名（ctx maps 索引查名；未知 → 原引用串）。"""
    if ref is None:
        return ""
    s = str(ref)
    if not s:
        return ""
    entry = _maps_index(ctx).get(s)
    if isinstance(entry, Mapping):
        nm = entry.get("name")
        if isinstance(nm, str) and nm:
            return nm
    return s


# ---------------------------------------------------------------------------
# persistent_state：quota（R-11）与 one_shot 去重（R-15/TC-15）——存储对齐兄弟路
# ---------------------------------------------------------------------------

def _persistent_state_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """persistent_state 可变容器定位（对齐 adventure_log._persistent_state_of）：
    ctx["persistent_state"] → ctx["player"].persistent_state → ctx 自身。"""
    if not isinstance(ctx, Mapping):
        return None
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


def _quota_daily_limit(ctx: Mapping[str, Any]) -> int:
    """daily 配额上限（R-11 可配）：settings.investigate.daily_quota，缺省 3。"""
    s = ctx.get("settings")
    if isinstance(s, Mapping):
        inv = s.get("investigate")
        if isinstance(inv, Mapping):
            v = inv.get("daily_quota")
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
    return INVESTIGATE_QUOTA_DEFAULT_DAILY


def _quota_date(ctx: Mapping[str, Any]) -> str:
    """配额自然日（R-11：按 server 自然日，懒计算重置）：ctx today 优先，now 兜底。"""
    for k in ("today", "now"):
        v = ctx.get(k)
        if v:
            s = str(v).strip()
            if s:
                return s[:10]
    return ""


def _quota_state(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """配额状态容器（persistent_state["investigate_quota"] = {今日: 计数}），缺省自建。"""
    ps = _persistent_state_of(ctx)
    if ps is None:
        return None
    raw = ps.get(INVESTIGATE_QUOTA_PS_KEY)
    if not isinstance(raw, MutableMapping):
        raw = {}
        ps[INVESTIGATE_QUOTA_PS_KEY] = raw
    return raw


def _quota_used(ctx: Mapping[str, Any]) -> int:
    """当日已用配额（跨日 → 0，懒重置 R-11；对齐兄弟路 QUOTA_KEY 形态）。"""
    st = _quota_state(ctx)
    if st is None:
        return 0
    n = st.get(_quota_date(ctx))
    return int(n) if isinstance(n, int) and n > 0 else 0


def _quota_exceeded(ctx: Mapping[str, Any]) -> bool:
    """当日揭示配额是否已满（R-11：超限 → 泛化文本，由调用方回落 ambient）。"""
    return _quota_used(ctx) >= _quota_daily_limit(ctx)


def _quota_tick(ctx: MutableMapping[str, Any]) -> None:
    """揭示命中消耗 1 次配额（按自然日键，懒重置 R-11）。"""
    st = _quota_state(ctx)
    if st is None:
        return
    date = _quota_date(ctx)
    if not date:
        return
    st[date] = int(_quota_used(ctx)) + 1


def _revealed_set(ctx: MutableMapping[str, Any]) -> set:
    """已触发一次性标记集合（对齐兄弟路 REVEALED_KEY 列表形态）。"""
    ps = _persistent_state_of(ctx)
    if ps is None:
        return set()
    raw = ps.get(INVESTIGATE_REVEALED_PS_KEY)
    if isinstance(raw, (list, tuple, set)):
        return {str(x) for x in raw}
    return set()


def _found(ctx: MutableMapping[str, Any], key: str) -> bool:
    """是否已发现（one_shot 已消费 → 简短确认，TC-15）。"""
    return key in _revealed_set(ctx)


def _mark_found(ctx: MutableMapping[str, Any], key: str) -> None:
    """标记已发现（状态翻转，one_shot 后不再出正文/卡片，R-15；幂等追加）。"""
    if not key:
        return
    ps = _persistent_state_of(ctx)
    if ps is None:
        return
    raw = ps.get(INVESTIGATE_REVEALED_PS_KEY)
    if not isinstance(raw, list):
        raw = []
        ps[INVESTIGATE_REVEALED_PS_KEY] = raw
    if key not in raw:
        raw.append(key)


def _record_hidden_find(ctx: MutableMapping[str, Any], hidden_id: Optional[str]) -> None:
    """[事件:隐藏发现:ID] 计数 + 首见日志（R-15 / 3f E-01）：adventure_log.log_hidden_find
    优先（已落盘 BCH-05）；不可用 → event_bus 直写 nested 兜底。零抛错。"""
    if not hidden_id:
        return
    try:
        from qbot_rpg.core.adventure_log import log_hidden_find  # noqa: PLC0415
        log_hidden_find(ctx, str(hidden_id))
        return
    except Exception:
        pass
    try:
        hook = ctx.get("bump_event")
        key = f"[事件:隐藏发现:{hidden_id}]"
        if callable(hook):
            hook(ctx, key)
        else:
            from qbot_rpg.core.event_bus import bump_event  # noqa: PLC0415
            bump_event(ctx, key)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 条件求值（R-08 lore_condition / R-09 window 限定窗口；本地兜底引擎用）
# ---------------------------------------------------------------------------

def _condition_ctx(ctx: Mapping[str, Any], map_id: str) -> dict:
    """条件求值上下文：ctx condition_ctx 优先，兜底整 ctx；补三键取值通道。

    条件引擎读 season_now/period_now/weather_now 直键（或 worldtime 鸭子），此处从
    ctx season/period/weather 映射补全；map_id 注入供天气上下文绑定（2a4c IF04）。
    """
    base = ctx.get("condition_ctx")
    cctx = dict(base) if isinstance(base, Mapping) else dict(ctx)
    for k, cur in (("season_now", ctx.get("season")), ("period_now", ctx.get("period")),
                   ("weather_now", ctx.get("weather"))):
        if k not in cctx and cur:
            cctx[k] = str(cur)
    cctx["map_id"] = str(map_id or "")
    return cctx


def _eval_condition(ctx: Mapping[str, Any], cond: object, map_id: str) -> bool:
    """lore/window 条件求值（对齐 dialog._eval_condition 口径）：无条件 → True；
    ctx eval_condition hook 优先 → 统一条件引擎兜底；任何异常/形态 → False（D-03）。"""
    if not cond:
        return True
    cctx = _condition_ctx(ctx, map_id)
    hook = ctx.get("eval_condition")
    if callable(hook):
        try:
            base = ctx.get("condition_ctx")
            arg = base if isinstance(base, Mapping) else cctx
            return bool(hook(cond, arg))
        except Exception:
            return False
    # 无 hook（独立测试/未装配）：保守 False——条件求值统一走 ctx eval_condition hook
    # （commands 层零 engine 直接依赖，G0 架构门禁；装配层 make_context 注入）
    return False


def _cond_ok(ctx: Mapping[str, Any], cond: object, map_id: str) -> bool:
    """条件满足判定（无条件 → True；失败 → False，调用方回落泛化文本 R-07）。"""
    if not cond:
        return True
    return _eval_condition(ctx, cond, map_id)


def _window_match(ctx: Mapping[str, Any], window: object, map_id: str) -> bool:
    """限定窗口匹配（R-09）：window 条件表达式 → 统一条件引擎；{season,period,weather}
    直接值形态 → 逐键全等（值为 str/list，全匹配才通过）；list/tuple → 全与。"""
    if not window:
        return False
    if isinstance(window, (list, tuple)):
        for w in window:
            if not _window_match(ctx, w, map_id):
                return False
        return True
    if not isinstance(window, Mapping):
        return False
    if any(k in window for k in ("var", "all", "any", "not", "type")):
        return _eval_condition(ctx, window, map_id)
    for key, cur in (("season", str(ctx.get("season") or "")),
                     ("period", str(ctx.get("period") or "")),
                     ("weather", str(ctx.get("weather") or ""))):
        want = window.get(key)
        if want is None:
            continue
        if isinstance(want, (list, tuple)):
            if cur not in [str(w) for w in want]:
                return False
        elif not cur or cur != str(want):
            return False
    return True


# ---------------------------------------------------------------------------
# 本地兼容引擎（R-07~R-11；兄弟路 core/investigate.py 不可用时兜底，工程补白 1）
# ---------------------------------------------------------------------------

def _hunt_row(raw: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """蹲点目标行（工程补白 3）：怪物行 hidden_boss:true，或 boss:true 且带 window。"""
    rows = raw.get("monsters")
    if not isinstance(rows, list):
        return None
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        if r.get("hidden_boss") is True:
            return r
        if r.get("window") and r.get("boss") is True:
            return r
    return None


def _hunt_key(row: Mapping[str, Any], map_id: str) -> str:
    """蹲点 one_shot 键：hunt:{enemy}（enemy 缺省 → map_id）。"""
    enemy = row.get("enemy")
    return f"hunt:{enemy}" if enemy else f"hunt:{map_id}"


def _hunt_result(ctx: MutableMapping[str, Any], raw: Mapping[str, Any],
                 map_id: str) -> Optional[dict]:
    """特定时段蹲点（R-09）：窗口 + lore 条件满足 → hunt；窗口外/条件不满足/配额超限
    → None（调用方回落泛化文本零暗示）；已发现 → hunt_done 简短确认。"""
    row = _hunt_row(raw)
    if row is None:
        return None
    if not _window_match(ctx, row.get("window"), map_id):
        return None
    if not _cond_ok(ctx, row.get("lore_condition") or row.get("condition"), map_id):
        return None
    title = str(row.get("name") or row.get("enemy") or "")
    key = _hunt_key(row, map_id)
    if _found(ctx, key):
        return {"kind": "hunt_done", "text": tpl_of(ctx, _HUNT_DONE_KEY), "title": title}
    if _quota_exceeded(ctx):
        return None
    _quota_tick(ctx)
    _mark_found(ctx, key)
    _record_hidden_find(ctx, row.get("hidden_find_id") or row.get("enemy") or map_id)
    return {
        "kind": KIND_HUNT,
        "text": str(row.get("intro") or tpl_of(ctx, _DEFAULT_HUNT_INTRO_KEY)),
        "lore": str(row.get("codex_ref") or ""),
        "title": title,
        "signal": str(row.get("signal") or tpl_of(ctx, _DEFAULT_HUNT_SIGNAL_KEY)),
    }


def _hidden_map_result(ctx: MutableMapping[str, Any], raw: Mapping[str, Any],
                       map_id: str) -> Optional[dict]:
    """隐藏地图揭示（F-07 / §2.4）：地图级 hidden 标记 + lore condition 满足 → 一次性
    揭示入口；已发现 → hidden_map_done；条件不满足/配额超限 → None（回落泛化文本）。"""
    if not (raw.get("hidden") is True or raw.get("hidden_map") is True):
        return None
    if not _cond_ok(ctx, raw.get("lore_condition") or raw.get("condition"), map_id):
        return None
    title = str(raw.get("name") or map_id)
    key = f"hidden_map:{map_id}"
    if _found(ctx, key):
        done = tpl_of(ctx, _HIDDEN_MAP_DONE_KEY)
        return {"kind": "hidden_map_done", "text": done, "title": title}
    if _quota_exceeded(ctx):
        return None
    _quota_tick(ctx)
    _mark_found(ctx, key)
    _record_hidden_find(ctx, raw.get("hidden_find_id") or f"hidden_map:{map_id}")
    intro = str(raw.get("intro") or raw.get("reveal") or raw.get("desc")
                or tpl_of(ctx, _DEFAULT_HIDDEN_MAP_TEXT_KEY))
    return {"kind": KIND_HIDDEN_MAP, "text": intro, "title": title}


def _egg_key(point: Mapping[str, Any], map_id: str = "") -> str:
    """交互点 one_shot 键：egg:{id}（id 缺省 → map_id:{首alias}）。"""
    pid = point.get("id")
    if isinstance(pid, str) and pid:
        return f"egg:{pid}"
    al = point.get("alias")
    if isinstance(al, (list, tuple)) and al:
        return f"egg:{map_id}:{al[0]}"
    if isinstance(al, str) and al:
        return f"egg:{map_id}:{al}"
    return f"egg:{map_id}"


def _eggshell_result(ctx: MutableMapping[str, Any], point: Mapping[str, Any],
                     map_id: str) -> Optional[dict]:
    """交互点文本彩蛋（R-08）：lore condition 满足 → 彩蛋正文 + 发现卡片 + 隐藏发现
    计数；条件不满足/配额超限 → None（回落泛化文本零暗示）；已发现 → eggshell_done。"""
    if not _cond_ok(ctx, point.get("lore_condition"), map_id):
        return None
    title = _point_title(point)
    key = _egg_key(point, map_id)
    if _found(ctx, key):
        return {"kind": "eggshell_done", "text": tpl_of(ctx, _EGGSHELL_DONE_KEY), "title": title}
    if _quota_exceeded(ctx):
        return None
    _quota_tick(ctx)
    _mark_found(ctx, key)
    _record_hidden_find(ctx, point.get("hidden_find_id") or point.get("id"))
    return {"kind": KIND_EGGSHELL, "text": str(point.get("desc") or ""), "title": title}


def _map_eggshell_result(ctx: MutableMapping[str, Any], raw: Mapping[str, Any],
                         map_id: str) -> Optional[dict]:
    """地图级彩蛋（R-07 2.1，工程补白 2）：无目标 /调查 当前地图时取首个条件满足且
    未发现的交互点；全不满足/已发现/配额超限 → None。"""
    for point in _interact_points(raw):
        if not _cond_ok(ctx, point.get("lore_condition"), map_id):
            continue
        key = _egg_key(point, map_id)
        if _found(ctx, key):
            continue
        if _quota_exceeded(ctx):
            return None
        _quota_tick(ctx)
        _mark_found(ctx, key)
        _record_hidden_find(ctx, point.get("hidden_find_id") or point.get("id"))
        return {"kind": KIND_EGGSHELL, "text": str(point.get("desc") or ""),
                "title": _point_title(point)}
    return None


def _ambient_result(ctx: MutableMapping[str, Any], raw: Mapping[str, Any]) -> dict:
    """泛化文本结果（R-07 零暗示 / R-22）：kind=ambient + 环境快照头 + 中性文本。"""
    return {"kind": KIND_AMBIENT, "text": _ambient_text(ctx)}


def investigate_map_local(ctx: MutableMapping[str, Any], map_def: Any,
                          target: Optional[str] = None) -> dict:
    """本地兼容调查引擎（R-07~R-11；兄弟路 core/investigate.py 不可用时兜底）。

    入参 ctx: 玩家上下文（map_def/location/maps/season/period/weather/persistent_state/
    rng/eval_condition/condition_ctx 等）；map_def: 当前地图（MapDef 或 raw dict）；
    target: /调查 目标（交互点别名 / 地图名 / None=当前地图）。

    出参 dict{kind, text, ...}：kind ∈ hunt/hidden_map/eggshell/eggshell_done/
    hunt_done/hidden_map_done/ambient（对应兄弟路 hunt/map_reveal/egg/*_confirm/generic）。

    核心逻辑（R-11 优先级：隐藏 BOSS 蹲点 > 隐藏地图 > 交互点彩蛋 > 泛化文本）：
      - target 为交互点别名 → 彩蛋（eggshell）；命中别名但条件/配额不满足 → 泛化文本。
      - target 为地图名/id（含省略=当前地图）→ 蹲点判定（窗口内 hunt）；当前地图另做
        隐藏地图入口揭示与地图级彩蛋判定。
      - 全未命中 / 窗口外 / 条件不满足 / 配额超限 → 泛化文本（零暗示，R-07）。
    """
    raw = _map_raw(map_def)
    map_id = str(raw.get("id") or "")

    if target is not None:
        t = str(target).strip()
        if not t:
            return investigate_map_local(ctx, map_def, None)
        # ① 交互点别名（R-08）——只查当前地图交互点（你只能调查所在处的点）
        point = _match_interact_point(raw, t)
        if point is not None:
            egg = _eggshell_result(ctx, point, map_id)
            return egg if egg is not None else _ambient_result(ctx, raw)
        # ② 地图名/id（R-09 蹲点；当前地图另做隐藏地图/地图级彩蛋）
        tmap = _map_by_ref(ctx, t)
        if tmap is not None:
            t_raw = _map_raw(tmap)
            t_id = str(t_raw.get("id") or "")
            hunt = _hunt_result(ctx, t_raw, t_id)
            if hunt is not None:
                return hunt
            if t_id == map_id:
                hm = _hidden_map_result(ctx, t_raw, t_id)
                if hm is not None:
                    return hm
                egg = _map_eggshell_result(ctx, t_raw, t_id)
                if egg is not None:
                    return egg
            return _ambient_result(ctx, raw)
        # ③ 未知目标 → 泛化文本（零暗示，R-07）
        return _ambient_result(ctx, raw)

    # 无目标 → 当前地图：蹲点 → 隐藏地图 → 地图级彩蛋 → 泛化文本（R-11 优先级）
    hunt = _hunt_result(ctx, raw, map_id)
    if hunt is not None:
        return hunt
    hm = _hidden_map_result(ctx, raw, map_id)
    if hm is not None:
        return hm
    egg = _map_eggshell_result(ctx, raw, map_id)
    if egg is not None:
        return egg
    return _ambient_result(ctx, raw)


# ---------------------------------------------------------------------------
# 引擎调用（兄弟路优先，本地兜底）
# ---------------------------------------------------------------------------

def _engine_investigate(ctx: MutableMapping[str, Any], map_def: Any,
                        target: Optional[str]) -> dict:
    """调用调查引擎：兄弟路 qbot_rpg.core.investigate.investigate_map(ctx, map_def,
    target=...) 优先（已落盘，真实签名 L503）；未落盘/异常/形态不符 →
    investigate_map_local 兜底。"""
    try:
        mod = importlib.import_module("qbot_rpg.core.investigate")
        fn = getattr(mod, "investigate_map", None)
        if callable(fn):
            res = fn(ctx, map_def, target=target)
            if isinstance(res, Mapping) and res.get("kind"):
                return dict(res)
    except Exception:
        pass
    return investigate_map_local(ctx, map_def, target=target)


# ---------------------------------------------------------------------------
# 渲染（kind → str 回复）
# ---------------------------------------------------------------------------

def _discover_card(ctx: Mapping[str, Any], title: str, *, label: str = "") -> str:
    """一次性发现卡片（R-15：⛩️ 在 3d §四 emoji 纪律下禁用以排版符号文本替代）：
    `【发现】{label}{title}` 单行；title 空 → 空串。文本 investigate_tpl 分区，渲染 tpl_of。"""
    if not title:
        return ""
    return tpl_of(ctx, "investigate_discover_card", {"label": label, "title": title})


def render_investigate_result(result: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
    """引擎 {kind, text} → 回复文本（纯函数；兼容兄弟路与本地兜底双词汇）。

    - hunt（R-09）：环境演出文本（狼嗥）→ 图鉴传闻引用（引擎提供时）→ 发现卡片 →
      进入 BOSS 战信号；
    - map_reveal/hidden_map（F-07）：一次性揭示隐藏地图入口（介绍文本 + 发现卡片）；
    - egg/eggshell（R-08）：彩蛋正文 + 发现卡片；
    - egg_confirm/map_reveal_confirm/eggshell_done/hunt_done/hidden_map_done（TC-15）：
      简短确认（无正文无卡片）；
    - generic/ambient（R-22）：泛化环境文本（零暗示）。
    """
    kind = str(result.get("kind") or KIND_AMBIENT)
    text = str(result.get("text") or "")
    title = str(result.get("title") or "")

    if kind == KIND_HUNT:
        lines: List[str] = []
        if text:
            lines.append(text)
        name = title or _boss_name(ctx, result)
        lore = result.get("lore")
        if isinstance(lore, str) and lore:
            lines.append(lore)
        elif name:
            # 图鉴传闻引用（R-09 / R-23 L349 格式；引擎未给 lore 时中性合成，不编造细节）
            lines.append(tpl_of(ctx, "investigate_codex_ref", {"name": name}))
        card = _discover_card(ctx, name,
                              label=tpl_of(ctx, "investigate_discover_label_boss"))
        if card:
            lines.append(card)
        signal = result.get("signal")
        lines.append(str(signal) if isinstance(signal, str) and signal
                     else tpl_of(ctx, _DEFAULT_HUNT_SIGNAL_KEY))
        return "\n".join(lines)

    if kind in ("map_reveal", KIND_HIDDEN_MAP):
        lines = [text] if text else []
        card = _discover_card(ctx, title or _map_name_by_ref(ctx, result.get("map_ref")),
                              label=tpl_of(ctx, "investigate_discover_label_map"))
        if card:
            lines.append(card)
        return "\n".join(lines) if lines else _ambient_text(ctx)

    if kind in ("egg", KIND_EGGSHELL):
        lines = [text] if text else []
        point = _point_by_id(ctx, result.get("interact_point_id"))
        card_title = title or (_point_title(point) if point is not None else "")
        card = _discover_card(ctx, card_title)
        if card:
            lines.append(card)
        return "\n".join(lines) if lines else _ambient_text(ctx)

    if kind in ("egg_confirm", "map_reveal_confirm", "eggshell_done",
                "hunt_done", "hidden_map_done"):
        return text or tpl_of(ctx, _EGGSHELL_DONE_KEY)

    return text or _ambient_text(ctx)


# ---------------------------------------------------------------------------
# hunt → BOSS 战接线（3f R-12 / F-08，BCH-07；工程补白 7）
# ---------------------------------------------------------------------------

def launch_hunt_battle(ctx: Mapping[str, Any], result: Mapping[str, Any]) -> Optional[dict]:
    """hunt 信号 → 真实 BOSS 战发起（3f R-12 / F-08；RN-12 接线 BCH-07）。

    入参 ctx: 玩家上下文（战斗发起能力）；result: 调查引擎结果 dict（kind=hunt +
    boss_ref）。出参: 发起成功 → {started: True, boss_ref, battle?, message?}；
    非 hunt / 无 boss_ref / 无发起能力 / 发起失败 → None（调用方保持信号文本）。

    核心逻辑: 仅 kind=hunt 且 ctx 有战斗发起能力时发起——ctx["start_battle"] hook
    优先（装配层注入，start_battle(ctx, boss_ref) -> dict）；ctx["battle_engine"]
    次之（callable 或带 start_battle/launch/start 方法的发起接口，同签名
    (ctx, boss_ref) -> dict）。发起返回 ok=False / started=False → 视为失败 → None。
    任何异常 → None（回退信号文本，不崩，对齐 D-03 fail-safe 纪律）。
    """
    if not isinstance(ctx, Mapping) or not isinstance(result, Mapping):
        return None
    if str(result.get("kind") or "") != KIND_HUNT:
        return None
    boss_ref = (result.get("boss_ref") or result.get("boss")
                or result.get("enemy") or result.get("title"))
    if not boss_ref:
        return None
    launcher = ctx.get("start_battle")
    if not callable(launcher):
        engine = ctx.get("battle_engine")
        if engine is not None and not callable(engine):
            for m in ("start_battle", "launch", "start"):
                if callable(getattr(engine, m, None)):
                    launcher = getattr(engine, m)
                    break
        elif callable(engine):
            launcher = engine
    if not callable(launcher):
        return None
    try:
        out = launcher(ctx, boss_ref)
    except Exception:
        return None
    if not isinstance(out, Mapping):
        return None
    if out.get("ok") is False or out.get("started") is False:
        return None
    return {
        "started": True,
        "boss_ref": str(boss_ref),
        "battle": out.get("battle"),
        "message": out.get("message"),
    }


def _render_investigate_result_with_battle(result: Mapping[str, Any],
                                           ctx: Mapping[str, Any]) -> str:
    """调查结果 → 回复文本；hunt 且战斗发起能力存在 → 接真实 BOSS 战（F-08 / R-12）。

    先按既有渲染（render_investigate_result）出蹲点演出/卡片/信号文本；再对 hunt 结果
    尝试 launch_hunt_battle——发起成功且 hook 给出发起消息 → 追加发起消息收尾；未发起
    （无能力/失败/非 hunt）→ 保持既有信号文本（最小侵入，未装配战斗时行为不变）。
    """
    text = render_investigate_result(result, ctx)
    launch = launch_hunt_battle(ctx, result)
    if launch is None:
        return text
    msg = launch.get("message")
    if isinstance(msg, str) and msg:
        return f"{text}\n{msg}"
    return text


# ---------------------------------------------------------------------------
# 指令壳入口
# ---------------------------------------------------------------------------

def cmd_investigate(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/调查 [目标] 主入口（R-07）：目标可选（交互点别名 / 地图名 / 省略=当前地图）。

    参数解析：至多 1 个位置参数（超参 → TPL-12）；无参 → 当前地图整体调查。引擎输出
    {kind, text} → render_investigate_result 渲染。无当前位置 → 明确拒绝文案。
    """
    if not isinstance(ctx, MutableMapping):
        return ""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    target = str(args[0]) if args else None
    map_def = _resolve_map_def(ctx)
    if map_def is None:
        return tpl_of(ctx, _TPL_NO_MAP_KEY)
    result = _engine_investigate(ctx, map_def, target)
    if not isinstance(result, Mapping) or not result.get("kind"):
        result = _ambient_result(ctx, _map_raw(map_def))
    return _render_investigate_result_with_battle(result, ctx)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，REGISTER_GROUPS 收口接入）
# ---------------------------------------------------------------------------

def register_investigate_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /调查 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 map_def/location/maps/
        season/period/weather/persistent_state/rng/eval_condition/condition_ctx 等，
        见本模块各函数消费契约 + R-07 ctx 前置）。None 时 handler 调用抛 RuntimeError
        （【待接线】装配入口注入；此时若 runner 注入了 ctx=ctx 则回退用之）。
    返回 router（链式）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】investigate_commands.register_investigate_commands 需要 "
                "make_context（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _investigate(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_investigate(parsed, injected)
        return cmd_investigate(parsed, _ctx(parsed))

    router.register(CommandSpec(INVESTIGATE_CMD, handler=_investigate))
    return router
