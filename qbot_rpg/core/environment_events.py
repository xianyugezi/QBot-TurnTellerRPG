"""环境事件注册与渲染时间线（qbot_rpg/core/environment_events.py · M7 BCH-09 · F-17 · R-24~R-26）。

环境事件注册表：事件定义 {event_id, tag, template_id, params, condition, priority} 从
maps.json 装载（每张地图 raw 的 `environment_events[]` 顶层字段；或隐藏 BOSS window
关联事件：monsters[] 窗口行携带 event_id → 派生事件，condition = window [+ after]）。
触发 → [事件:环境事件:ID] 计数（event_bus.bump_event nested target）+ 事件实例日志
（tag=environment，独立环境段，供 /日志 环境段或 event_timeline 消费）。

依据（真实签名已 read 核对）：
  - docs/细化/细化_3f_单机向体验.md：
    · R-24（5.3 F-17）：事件注册预置 `[事件:环境事件:ID]` / `[事件:隐藏发现:ID]` 两行，
      可被任务/隐藏要素引用；效果引用 npc_appear/quest_window/shop 限时/monster_boost。
    · R-25（5.4）：泛暗示 → 定向 → 确认三层漏斗衔接，任何一层不提前泄露下一层。
    · R-26（渲染时间线）：event_timeline(ctx, limit) -> 最近环境事件行（时间戳 + 快照
      season/period/weather + 事件简述），供 /日志 或冒险日志环境段消费。
  - qbot_rpg/core/event_bus.py（bump_event(ctx, key, *, instance) -> dict：三表同写，
    instance.target → event_counts nested {key:{target:count}}；event_log 环形 300 可配）。
  - qbot_rpg/core/adventure_log.py（log_hidden_find 归隐藏发现语义，本模块环境事件
    不走该函数——采用「独立环境段」tag=environment 经 bump_event 直写，语义分离）。
  - qbot_rpg/engine/condition_engine.py（eval_condition(cond, ctx) -> bool fail-safe；
    [事件:环境事件:雨夜] → name=[事件:环境事件] + param=雨夜，读 event_counts 嵌套；
    时间三键真实读取键 season_now/period_now/weather_now）。

【工程补白 · 显式标注】
  1) 事件键约定（对齐 adventure_log 口径）：bump_event 用 base 键
     `[事件:环境事件]` + target=event_id → event_counts["[事件:环境事件]"][event_id]；
     条件引擎引用全键 [事件:环境事件:ID]（nested 形态，与补白 N-03/ADR-05 一致）。
  2) 注册表装载双形态：maps.json 为 map raw **list**（每元素一张地图），"顶层
     environment_events[]" 落地为任一 map raw 的 `environment_events` 字段（list）；
     兼容顶层单 dict {environment_events:[...]} 形态（内容包可整体挂一页）。事件定义
     map_id 取所在 map raw 的 id（缺省 None = 全局事件，任意地图进入均检查）。
  3) 隐藏 BOSS window 关联事件（任务 A 部分 "或隐藏 BOSS window 关联事件"）：monsters[]
     窗口行带 `event_id`（或 `env_event_id`）→ 派生事件，condition = 行 `window` 条件键
     （after 模式再并入 `after` 前置：condition = {all:[window, after]}）；派生事件
     priority=100、tag=environment、params 带 boss_ref/map_id。窗口行未带 event_id →
     不派生（内容作者显式声明才注册，防意外事件）。
  4) 触发时机（R-26）：装配层/地图进入时调用 check_environment_events(ctx, map_def)；
     条件满足即计数+日志（隐藏 BOSS after 模式依赖 [事件:环境事件:ID] 计数，hidden_trigger
     已消费，BCH-07 已就绪）。去重/懒触发/概率演出归兄弟路 F-15 ambient（BCH-09 路 A），
     本模块不做频控（事件本身可重复计数，语义 = "窗口内每次进入"）。
  5) event_timeline 只读不改（纯函数）：过滤 tag ∈ {environment, ambient}，倒序取 limit；
     行含 ts / snapshot{season,period,weather} / event_id / summary（模板文本渲染，兜底
     params name/title/event_id）。模板文本源 = registry 中事件 def 的 text/desc（若携带）；
     summary 渲染用条目快照注入占位符（确定性，不依赖现刻）。

铁律：零 NoneBot import；纯函数确定性（now/rng 由 ctx 注入）；每函数 docstring；
无 emoji；最小侵入（复用 event_bus 模式，不改兄弟路文件）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.event_bus import EVENT_LOG_KEY, bump_event
from qbot_rpg.engine.condition_engine import eval_condition

__all__ = [
    "ENVIRONMENT_TAG",
    "AMBIENT_TAG",
    "ENVIRONMENT_TAGS",
    "ENV_EVENT_KEY_BASE",
    "DEFAULT_ENV_EVENT_PRIORITY",
    "event_key_environment",
    "load_environment_events",
    "EnvironmentEventRegistry",
    "check_environment_events",
    "event_timeline",
]

# -------------------------------------------------------------------------------------
# 常量（R-24 / 补白 1-3）
# -------------------------------------------------------------------------------------
# 环境事件条目 tag（R-26 时间线过滤）
ENVIRONMENT_TAG = "environment"
AMBIENT_TAG = "ambient"
ENVIRONMENT_TAGS: Tuple[str, ...] = (ENVIRONMENT_TAG, AMBIENT_TAG)

# 环境事件 base 键（bump_event 用；条件引擎引用全键 [事件:环境事件:ID]）
ENV_EVENT_KEY_BASE = "[事件:环境事件]"

# 事件定义缺省优先级（补白 3：派生事件 / 定义缺省）
DEFAULT_ENV_EVENT_PRIORITY = 0

# 模板占位符合法集（3d 模板规范子集，对齐 investigate._render_text / hidden_trigger._render_text）
_TEMPLATE_KEYS: Tuple[str, ...] = ("季节", "时段", "天气", "地图")


# -------------------------------------------------------------------------------------
# 内部小工具（纯函数，均带 docstring）
# -------------------------------------------------------------------------------------
def _raw_get(map_def: object, key: str) -> Any:
    """地图定义 raw 读取（兜底）：BaseDef.get/raw（MapDef）或纯 dict；缺省 None。"""
    if map_def is None:
        return None
    getter = getattr(map_def, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            pass
    raw = getattr(map_def, "raw", None)
    if isinstance(raw, Mapping):
        return raw.get(key)
    if isinstance(map_def, Mapping):
        return map_def.get(key)
    return None


def _map_id(map_def: object) -> str:
    """地图 id：def.id 或 raw id（兜底空串）。"""
    v = getattr(map_def, "id", None)
    if isinstance(v, str) and v:
        return v
    v = _raw_get(map_def, "id")
    return v if isinstance(v, str) else ""


def _map_name(map_def: object) -> str:
    """地图名：def.name 或 raw name（兜底空串）。"""
    v = getattr(map_def, "name", None)
    if isinstance(v, str) and v:
        return v
    v = _raw_get(map_def, "name")
    return v if isinstance(v, str) else ""


def _window_rows(map_raw: Mapping[str, Any]) -> list:
    """隐藏 BOSS 窗口行（R-12 数据源）：monsters[] 中带 `window` 条件键 + enemy 非空的行。"""
    raw = map_raw.get("monsters")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)
            and isinstance(e.get("window"), Mapping)
            and isinstance(e.get("enemy"), str) and e.get("enemy")]


def _full_key(base: str, target: object) -> str:
    """全键形态：base 尾 `]` 前插 `:{target}`（对齐条件引擎 _parse_event_var 的
    name:param 解析：[事件:环境事件:ID] → name=[事件:环境事件] + param=ID）。"""
    if base.endswith("]"):
        return f"{base[:-1]}:{target}]"
    return f"{base}:{target}"


def event_key_environment(event_id: object) -> str:
    """环境事件全键（条件引用形态）：`[事件:环境事件:{event_id}]`（契约 [事件:环境事件:ID]）。"""
    return _full_key(ENV_EVENT_KEY_BASE, event_id)


def _template_id(event_id: str) -> str:
    """条目模板 ID 约定（对齐 adventure_log._template_id）：`environment.{event_id}`。"""
    return f"environment.{event_id}"


def _condition_ctx(ctx: Mapping[str, Any]) -> dict:
    """统一条件引擎求值上下文（桥接，对齐 investigate 补白 8）：从 ctx["season"/"period"/
    "weather"] 派生 season_now/period_now/weather_now 直键（条件引擎时间三键真实读取键）。"""
    out = dict(ctx)
    for src, dst in (("season", "season_now"), ("period", "period_now"),
                     ("weather", "weather_now")):
        v = ctx.get(src)
        if isinstance(v, str) and v:
            out[dst] = v
    return out


def _cond_ok(cond: object, ctx: Mapping[str, Any]) -> bool:
    """统一条件求值（R-24 / D-03）：None=恒可触发；求值失败/False = 不满足（不抛错）。"""
    if cond is None:
        return True
    try:
        return bool(eval_condition(cond, _condition_ctx(ctx)))
    except Exception:
        return False


def _render_text(template: Optional[str], ctx: Mapping[str, Any], map_def: object) -> str:
    """模板占位符渲染（3d 模板规范子集）：{季节}/{时段}/{天气}/{地图} 注入，缺省 --。"""
    if not isinstance(template, str) or not template:
        return ""
    return (
        template
        .replace("{季节}", str(ctx.get("season") or "--"))
        .replace("{时段}", str(ctx.get("period") or "--"))
        .replace("{天气}", str(ctx.get("weather") or "--"))
        .replace("{地图}", _map_name(map_def) or "--")
    )


def _prev_count(ctx: Mapping[str, Any], key: str, target: str) -> int:
    """写入前该 target 的嵌套计数（首见判定，对齐 adventure_log._prev_count 口径）。"""
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


def _event_log_of(ctx: Mapping[str, Any]) -> list:
    """event_log 源：persistent_state["event_log"] 优先，ctx["event_log"] 兜底（对齐
    event_bus._log_list_of / adventure_log._event_log_of 兜底口径）。"""
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


def _snapshot_clean(snapshot: object) -> dict:
    """快照归一（R-05）：{season, period, weather}，缺失 "--"。"""
    out = {"season": "--", "period": "--", "weather": "--"}
    if isinstance(snapshot, Mapping):
        for k in ("season", "period", "weather"):
            v = snapshot.get(k)
            if isinstance(v, str) and v:
                out[k] = v
    return out


# -------------------------------------------------------------------------------------
# 事件定义装载（R-24 / 补白 2-3）
# -------------------------------------------------------------------------------------
def _is_normalized(entry: Mapping[str, Any]) -> bool:
    """已归一形判定：含 event_id + raw（dict）双标记（标准 def 由 _norm_def 产出；
    raw 定义通常无 raw 键）。已归一形直通保留 map_id 等字段，防二次归一丢作用域。"""
    return "event_id" in entry and isinstance(entry.get("raw"), Mapping)


def _norm_def(entry: object, map_id: Optional[str]) -> Optional[dict]:
    """单个环境事件定义归一 → 标准形 {event_id, tag, template_id, params, condition,
    priority, map_id, text, raw}；event_id 缺失/非 str → None（跳过）。已归一形（补白 5）
    直通保留既有 map_id，不再二次归一。"""
    if not isinstance(entry, Mapping):
        return None
    if _is_normalized(entry):
        d = dict(entry)
        d["map_id"] = d.get("map_id") or map_id or None
        return d
    event_id = entry.get("event_id") or entry.get("id")
    if not (isinstance(event_id, str) and event_id):
        return None
    tag = entry.get("tag")
    if not (isinstance(tag, str) and tag in ENVIRONMENT_TAGS):
        tag = ENVIRONMENT_TAG
    template_id = entry.get("template_id")
    if not (isinstance(template_id, str) and template_id):
        template_id = _template_id(event_id)
    params = entry.get("params")
    params = dict(params) if isinstance(params, Mapping) else {}
    priority = entry.get("priority")
    priority = (int(priority) if isinstance(priority, int)
                and not isinstance(priority, bool) else DEFAULT_ENV_EVENT_PRIORITY)
    text = entry.get("text")
    if not (isinstance(text, str) and text):
        text = entry.get("desc")
    text = text if isinstance(text, str) else None
    return {
        "event_id": event_id,
        "tag": tag,
        "template_id": template_id,
        "params": params,
        "condition": entry.get("condition"),
        "priority": priority,
        "map_id": map_id or None,
        "text": text,
        "raw": dict(entry),
    }


def _derive_from_window_rows(map_raw: Mapping[str, Any], map_id: Optional[str]) -> list:
    """隐藏 BOSS window 关联事件派生（补白 3）：monsters[] 窗口行带 event_id/env_event_id
    → 派生事件，condition = 行 `window` 限定窗口条件键（after 模式的前置 `after` 条件
    归 hidden_trigger.check_boss_spawn 消费，不并入事件自身条件——事件每次窗口满足即
    计数，累积次数供 after 模式判定），priority=100。"""
    out: list = []
    for row in _window_rows(map_raw):
        ev = row.get("event_id") or row.get("env_event_id")
        if not (isinstance(ev, str) and ev):
            continue
        out.append(_norm_def({
            "event_id": ev,
            "tag": ENVIRONMENT_TAG,
            "template_id": _template_id(ev),
            "params": {"boss_ref": row.get("enemy"), "map_id": map_id},
            "condition": row.get("window"),
            "priority": 100,
            "text": row.get("desc") or row.get("hint"),
        }, map_id))
    return [d for d in out if d is not None]


def load_environment_events(maps_data: object) -> dict:
    """从 maps.json 装载环境事件注册表（R-24，补白 2）→ {event_id: def}。

    入参 maps_data: maps.json 内容——list[map raw]（每元素一张地图，字段
    `environment_events[]`）或顶层 {environment_events:[...]} 或单张地图 dict。
    出参 dict: {event_id: 标准事件 def}；event_id 全局唯一（重复取先，duplicates 计数）。
    装载来源两路：① map raw 的 `environment_events[]` 字段（显式定义）；② 隐藏 BOSS
    window 关联事件（monsters[] 窗口行 event_id 派生，补白 3）。缺数据 → 空 dict。
    """
    entries: list = []
    if isinstance(maps_data, Mapping):
        if "environment_events" in maps_data:
            for e in _list_of(maps_data.get("environment_events")):
                d = _norm_def(e, None)
                if d is not None:
                    entries.append(d)
        if "id" in maps_data or "monsters" in maps_data:  # 单张地图形态
            mid = maps_data.get("id")
            mid = mid if isinstance(mid, str) else None
            entries.extend(_derive_from_window_rows(maps_data, mid))
    elif isinstance(maps_data, (list, tuple)):
        for item in maps_data:
            if not isinstance(item, Mapping):
                continue
            mid = item.get("id")
            mid = mid if isinstance(mid, str) else None
            if isinstance(item.get("environment_events"), list):
                for e in item["environment_events"]:
                    d = _norm_def(e, mid)
                    if d is not None:
                        entries.append(d)
            entries.extend(_derive_from_window_rows(item, mid))
    return _index(entries)


def _index(entries: Iterable[Mapping[str, Any]]) -> dict:
    """事件定义索引：{event_id: def}，重复 event_id 取先（确定性，装载序）。"""
    out: dict = {}
    for e in entries:
        eid = e.get("event_id")
        if eid not in out:
            out[eid] = e
    return out


def _list_of(value: object) -> list:
    """list 归一：list/tuple 直通；单 dict → [dict]；其余 → []。"""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return [value]
    return []


# -------------------------------------------------------------------------------------
# 环境事件注册表（R-24：定义装载 + O(1) 查询 + 地图适用过滤 + 模板文本解析）
# -------------------------------------------------------------------------------------
class EnvironmentEventRegistry:
    """环境事件注册表（F-17）：{event_id: 标准 def} 索引 + 查询 + 地图适用 + 模板文本。"""

    __slots__ = ("_by_id", "_order")

    def __init__(self, events: Optional[Iterable[Mapping[str, Any]]] = None) -> None:
        """装载事件定义（归一后建索引）；events 缺省 None → 空注册表。"""
        self._by_id: dict = {}
        self._order: list = []
        for e in (events or []):
            d = _norm_def(e, None)
            if d is None:
                continue
            eid = d["event_id"]
            if eid not in self._by_id:
                self._by_id[eid] = d
                self._order.append(eid)

    @classmethod
    def from_maps(cls, maps_data: object) -> "EnvironmentEventRegistry":
        """由 maps.json（list[map raw] 或 dict）构建（补白 2，复用 load_environment_events）。"""
        return cls(load_environment_events(maps_data).values())

    def get(self, event_id: object) -> Optional[dict]:
        """O(1) 查询：event_id → 标准 def；未注册 → None。"""
        return self._by_id.get(str(event_id))

    def ids(self) -> Tuple[str, ...]:
        """已注册 event_id 元组（装载序，确定性）。"""
        return tuple(self._order)

    def all(self) -> list:
        """全部标准 def 列表（装载序深拷贝引用）。"""
        return [self._by_id[i] for i in self._order]

    def applicable(self, map_id: object) -> list:
        """该地图适用的事件（map_id 缺省/空 = 全局事件）：按 (-priority, 装载序) 排序
        （高优先级先触发，对齐 /调查 优先级语义，确定性）。"""
        mid = str(map_id) if map_id is not None else ""
        cands = [self._by_id[i] for i in self._order
                 if self._by_id[i].get("map_id") in (None, "", mid)]
        cands.sort(key=lambda d: (-d.get("priority", 0), self._order.index(d["event_id"])))
        return cands

    def template_text(self, event_id: object) -> Optional[str]:
        """事件模板文本（def.text/desc，供时间线简述渲染）；未注册/无文本 → None。"""
        d = self.get(event_id)
        return d.get("text") if d is not None else None

    def __len__(self) -> int:
        return len(self._order)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EnvironmentEventRegistry n={len(self._order)}>"


def _registry_of(
    ctx: Mapping[str, Any],
    map_def: object,
    registry: object,
) -> EnvironmentEventRegistry:
    """注册表解析（补白 4）：显式 registry（实例/dict/list）→ ctx 注入
    （environment_events / env_event_registry / maps_data）→ map_def 单图兜底 → 空。"""
    if isinstance(registry, EnvironmentEventRegistry):
        return registry
    if isinstance(registry, Mapping):
        vals = [v for v in registry.values() if isinstance(v, Mapping)]
        return EnvironmentEventRegistry(vals)
    if isinstance(registry, (list, tuple)):
        return EnvironmentEventRegistry.from_maps(registry)
    for key in ("environment_events", "env_event_registry"):
        v = ctx.get(key)
        if isinstance(v, EnvironmentEventRegistry):
            return v
        if isinstance(v, Mapping):
            return EnvironmentEventRegistry([x for x in v.values() if isinstance(x, Mapping)])
        if isinstance(v, (list, tuple)):
            return EnvironmentEventRegistry.from_maps(v)
    maps_data = ctx.get("maps_data")
    if isinstance(maps_data, (list, tuple)):
        return EnvironmentEventRegistry.from_maps(maps_data)
    if isinstance(maps_data, Mapping):
        return EnvironmentEventRegistry.from_maps(maps_data)
    if map_def is not None:
        return EnvironmentEventRegistry.from_maps(map_def)
    return EnvironmentEventRegistry()


# -------------------------------------------------------------------------------------
# 主入口一：触发检查（R-26 触发时机 / 补白 4）
# -------------------------------------------------------------------------------------
def check_environment_events(
    ctx: MutableMapping[str, Any],
    map_def: object,
    registry: object = None,
) -> dict:
    """装配层/地图进入时环境事件检查（R-24/R-26，补白 4）：条件满足即计数+日志。

    入参:
      - ctx: 求值/写入上下文（season/period/weather/event_counts/longline_counters/
        persistent_state/settings/maps_data/now，见文件头）。
      - map_def: 进入的地图（MapDef 或 raw dict；event 定义从 registry 读取）。
      - registry: 可选——EnvironmentEventRegistry 实例 / {event_id: def} dict /
        maps_data list；缺省 None → ctx["environment_events"] → ctx["maps_data"] →
        map_def 单图兜底 → 空注册表（不抛错）。
    出参 dict: {triggered: [条目...], count}；触发条目含 {event_id, key, tag,
    template_id, priority, first_seen, ok, count}。条件满足即 bump_event（base 键
    [事件:环境事件] + target=event_id，nested 计数）并写事件实例日志（tag=environment，
    独立环境段）。条件不满足 / 无适用事件 → triggered=[]，零写入零暗示。
    """
    reg = _registry_of(ctx, map_def, registry)
    map_id = _map_id(map_def)
    triggered: list = []
    for ev in reg.applicable(map_id):
        if not _cond_ok(ev["condition"], ctx):
            continue
        event_id = ev["event_id"]
        first_seen = _prev_count(ctx, ENV_EVENT_KEY_BASE, event_id) == 0
        params = dict(ev["params"])
        params.setdefault("event_id", event_id)
        res = bump_event(
            ctx,
            ENV_EVENT_KEY_BASE,
            instance={
                "event_id": event_id,
                "tag": ev["tag"],
                "target": event_id,
                "first_seen": first_seen,
                "template_id": ev["template_id"],
                "params": params,
            },
        )
        triggered.append({
            "event_id": event_id,
            "key": event_key_environment(event_id),
            "tag": ev["tag"],
            "template_id": ev["template_id"],
            "priority": ev["priority"],
            "first_seen": first_seen,
            "ok": bool(res.get("ok")),
            "count": _prev_count(ctx, ENV_EVENT_KEY_BASE, event_id),
        })
    return {"triggered": triggered, "count": len(triggered)}


# -------------------------------------------------------------------------------------
# 主入口二：渲染时间线（R-26）
# -------------------------------------------------------------------------------------
def _summarize(
    ctx: Mapping[str, Any],
    entry: Mapping[str, Any],
    registry: Optional[EnvironmentEventRegistry],
) -> str:
    """时间线事件简述：registry 模板文本（def.text/desc）渲染优先 → params
    name/title/event_id 兜底 → "--"。渲染用条目快照注入占位符（确定性，不依赖现刻）。"""
    event_id = str(entry.get("event_id") or "")
    text = registry.template_text(event_id) if registry is not None else None
    if not text:
        params = entry.get("params")
        params = params if isinstance(params, Mapping) else {}
        for k in ("name", "title", "event_id"):
            v = params.get(k)
            if isinstance(v, str) and v:
                text = v
                break
    if not text:
        text = event_id or "--"
    render_ctx = dict(ctx)
    snap = entry.get("snapshot")
    if isinstance(snap, Mapping):
        for k in ("season", "period", "weather"):
            v = snap.get(k)
            if isinstance(v, str) and v:
                render_ctx[k] = v
    return _render_text(text, render_ctx, None)


def event_timeline(
    ctx: Mapping[str, Any],
    limit: int = 10,
    registry: object = None,
) -> list:
    """渲染时间线（R-26）：最近环境事件行（tag=environment/ambient），倒序取 limit。

    入参:
      - ctx: 读取上下文（persistent_state["event_log"] 或 ctx["event_log"]，见文件头）。
      - limit: 最大行数（非法/≤0 → 10）。
      - registry: 可选——模板文本源（EnvironmentEventRegistry 实例 / {event_id: def}
        dict / maps_data list）；缺省 None → 仅 params 兜底简述。
    出参 list[dict]: 每行 {ts, snapshot{season,period,weather}, event_id, tag,
    template_id, params, summary}，最新在前（event_log 追加序反转）。纯函数只读不改。
    """
    try:
        limit_i = max(1, int(limit))
    except (TypeError, ValueError):
        limit_i = 10
    if isinstance(registry, EnvironmentEventRegistry):
        reg = registry
    elif isinstance(registry, Mapping):
        reg = EnvironmentEventRegistry([v for v in registry.values() if isinstance(v, Mapping)])
    elif isinstance(registry, (list, tuple)):
        reg = EnvironmentEventRegistry.from_maps(registry)
    else:
        reg = None
    rows: list = []
    for e in reversed(_event_log_of(ctx)):
        if _entry_tag(e) not in ENVIRONMENT_TAGS:
            continue
        rows.append({
            "ts": str(e.get("ts") or "--"),
            "snapshot": _snapshot_clean(e.get("snapshot")),
            "event_id": str(e.get("event_id") or ""),
            "tag": _entry_tag(e),
            "template_id": e.get("template_id"),
            "params": dict(e.get("params") or {}),
            "summary": _summarize(ctx, e, reg),
        })
        if len(rows) >= limit_i:
            break
    return rows
