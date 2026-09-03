"""事件写入引擎（qbot_rpg/core/event_bus.py · M7 BCH-04 N-03 RN-10）。

统一事件写入：条件引擎读取源 event_counts + 冒险日志累计 longline_counters
+ 事件实例日志 event_log（环形 300，3f E-01 模型）。全链路唯一实现，各引擎
结算点经 ctx["bump_event"] hook 或直调本模块。

依据：
  - docs/细化/细化_M7_NPC对话接线.md N-03（RN-09~RN-10：6 预置事件 + 双表+实例日志三路）
  - docs/细化/细化_M7_交互补全总纲.md ADR-05（bump_event 双表 + event_log 环形）
  - docs/细化/细化_3f_单机向体验.md（E-01 事件实例模型 / D-01 零新存储：persistent_state）
  - qbot_rpg/engine/condition_engine.py（event_counts 消费：nested {key:{target:count}} 与
    flat {key:count} 双形态，L366-391 _read_counter；[事件:副本通关:熔岩洞窟] rsplit 拆 param）

【工程补白 · 显式标注】
  1) nested/flat 双形态写：instance 带 target → nested `event_counts[key][target]+=1`
     （对齐 test_condition_engine 的 nested 用法，防 [事件:X] + param 条件读 0）；
     instance 无 target → flat `event_counts[key]+=1`。
  2) 环形容量配置双键兼容：settings["event_log_capacity"] 优先，settings["event_log_cap"]
     兜底（兄弟路 assembly/context.py _fallback_bump_event 用后者），缺省 300。
  3) event_log 落点：ctx["persistent_state"]["event_log"] 优先，兜底 ctx["event_log"]
     直键（兄弟路兜底口径）；条目 ts 用 ctx["now"]/ctx["today"]（缺省 time 现刻 ISO）。
  4) 缺省兜底：ctx 缺任一表/字段不抛异常（只增不减语义），纯函数确定性（now/rng 由
     ctx 注入，无随机/时间外部依赖——ts 缺省用 time.time 为最后兜底）。
  5) M12.5 批5 路5A 事件键注册中心：settings["events"] 段 {事件名: 键名} 可配
     name 段（审计 docs/m125_事件键审计.md：写侧字面/常量 + 读侧前缀匹配双面协议，
     `[事件:` 外壳与 `:target]` 拼装为路由语法硬编码保留，只可配 name 段）；
     resolve_event_key 集中解析 + EVENT_KEY_DEFAULTS 缺省回退现键（向后兼容零破坏）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping, Optional

__all__ = [
    "DEFAULT_EVENT_LOG_CAP",
    "bump_event",
    "EVENT_LOG_KEY",
    "event_key_npc_dialog",
    "EVENT_KEY",
    "EVENT_KEY_DEFAULTS",
    "resolve_event_key",
]

# event_log 在 persistent_state 的键（3f E-01 / ADR-05 落点）
EVENT_LOG_KEY = "event_log"

# 环形容量缺省（3f E-01：300 条可配）
DEFAULT_EVENT_LOG_CAP = 300

# 事件键外壳前缀（路由语法：condition_engine/quest/内容校验器按 `[事件:` 前缀 +
# `]` 尾缀 + rsplit(":") 解析——审计结论风险5：只可配 name 段，外壳硬编码保留）
EVENT_KEY = "[事件:"


def event_key_npc_dialog(npc_id: object) -> str:
    """NPC 对话事件键（N-03 RN-09）：`[事件:NPC对话:{npc_id}]`。"""
    return f"[事件:NPC对话:{npc_id}]"


# ---------------------------------------------------------------------------
# 事件键注册中心（M12.5 批5 路5A：settings["events"] 段可配 name 段）
# ---------------------------------------------------------------------------
# 默认键名表（审计 13 写点/14 行注册表去重后 13 类事件：name 段缺省值 =
# 现字面量/常量，零配置时 resolve_event_key 回退至此，向后兼容零破坏）
EVENT_KEY_DEFAULTS: Mapping[str, str] = {
    "签到": "签到",          # core/checkin.py do_checkin 尾
    "副本通关": "副本通关",    # core/dungeon.py 探索 clear 通关点
    "等级提升": "等级提升",    # core/levelup.py 升级结算
    "怪物击杀": "怪物击杀",    # commands/battle_commands.py win 结算
    "任务完成": "任务完成",    # core/quest.py → adventure_log.log_story_node
    "图鉴新增": "图鉴新增",    # core/codex.py + core/fishing_codex.py + log_codex_new
    "成就达成": "成就达成",    # core/achievements.py _log_milestone
    "首杀": "首杀",          # adventure_log.log_first_kill
    "首钓冠级": "首钓冠级",    # adventure_log.log_first_crown
    "隐藏发现": "隐藏发现",    # adventure_log.log_hidden_find + investigate_commands 兜底
    "里程碑": "里程碑",       # adventure_log.log_milestone
    "环境事件": "环境事件",    # environment_events ENV_EVENT_KEY_BASE
    "NPC对话": "NPC对话",     # dialog 动态键 + event_key_npc_dialog
}


def _events_section(ctx_or_settings: Any) -> Any:
    """取配置 events 段：入参可为 ctx（含 settings 子表）或 settings 本身。

    入参 ctx_or_settings: Mapping——带 "settings" 子表 → settings["events"]；
    否则视为 settings 自身 → settings["events"]。出参: Mapping 或 None（缺失/
    非 Mapping 一律 None，resolve 侧回退默认键，零配置不抛）。
    """
    if not isinstance(ctx_or_settings, Mapping):
        return None
    settings = ctx_or_settings.get("settings")
    if isinstance(settings, Mapping):
        events = settings.get("events")
    else:
        events = ctx_or_settings.get("events")
    return events if isinstance(events, Mapping) else None


def resolve_event_key(ctx_or_settings: Any, event_name: str) -> str:
    """事件键集中解析（M12.5 批5 路5A）：事件名 → 完整事件键。

    入参 ctx_or_settings: ctx（Mapping 含 settings 子表）或 settings 本身
    （含 events 段）均可；event_name: 事件名（如 "签到"，与 settings.events
    键对应）。出参 str 完整事件键 `[事件:XXX]`。解析优先级:
      - settings.events[event_name] 命中：配置值为完整键（已以 `[` 开头）→
        原样直通（可配全键含自定义前缀）；否则为 name 段 → 包 `[事件:...]` 外壳。
      - 未命中 / events 段缺失 / 配置值空 → EVENT_KEY_DEFAULTS 缺省回退
        （零配置/零破坏，等价现字面量）；
      - event_name 未知（不在默认表）→ 以其自身为 name 段回退（向前兼容）。
      - event_name 已带 `[事件:` 外壳（迁移期双解析防呆）→ 原样直通。
    纯函数确定性，任何入参不抛（对齐本模块兜底精神）。
    """
    name = str(event_name or "").strip()
    if not name:
        return ""
    if name.startswith(EVENT_KEY):  # 已解析完整键：直通（防呆，避免二次包壳）
        return name
    conf = _events_section(ctx_or_settings)
    if conf is not None:
        raw = conf.get(name)
        if raw is not None and str(raw).strip():
            value = str(raw).strip()
            if value.startswith("["):  # 配置为完整键（含前缀）：直接透传
                return value
            return f"{EVENT_KEY}{value}]"
    default = EVENT_KEY_DEFAULTS.get(name, name)  # 缺省回退现键（零破坏）
    return f"{EVENT_KEY}{default}]"



def _now_iso(ctx: Mapping[str, Any]) -> str:
    """条目时间戳：ctx.now/today 优先（确定性注入），缺省 UTC 现刻。"""
    for k in ("now", "today"):
        v = ctx.get(k)
        if v:
            s = str(v)
            if s:
                return s
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snapshot_of(ctx: Mapping[str, Any]) -> dict:
    """环境快照（3f R-05）：ctx season/period/weather，缺失 --。"""
    return {
        "season": str(ctx.get("season") or "--"),
        "period": str(ctx.get("period") or "--"),
        "weather": str(ctx.get("weather") or "--"),
    }


def _counter_of(ctx: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
    """取计数器表（event_counts/longline_counters）可变引用：ctx 直键优先，
    persistent_state 兜底；缺失则创建（只增不减语义）。"""
    tbl = ctx.get(key)
    if isinstance(tbl, MutableMapping):
        return tbl
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        sub = ps.get(key)
        if isinstance(sub, MutableMapping):
            return sub
        ps[key] = {}
        return ps[key]
    ctx[key] = {}
    return ctx[key]


def _log_list_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """取 event_log 所属 persistent_state 可变引用（读/写 event_log 用）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    # 兜底：ctx 直键承载 event_log（兄弟路 _fallback 口径），无 persistent_state 时用 ctx 自身
    return ctx


def _log_capacity(ctx: Mapping[str, Any]) -> int:
    """环形容量：settings.event_log_capacity 优先 / event_log_cap 兜底 / 缺省 300。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        for k in ("event_log_capacity", "event_log_cap"):
            v = settings.get(k)
            if isinstance(v, int) and v > 0:
                return v
    return DEFAULT_EVENT_LOG_CAP


def _append_ring(log: list, entry: Mapping[str, Any], cap: int) -> None:
    """环形追加：满容量覆盖最旧（头部弹出）。"""
    log.append(dict(entry))
    if len(log) > cap:
        del log[: len(log) - cap]


def bump_event(
    ctx: MutableMapping[str, Any],
    key: str,
    *,
    instance: Optional[Mapping[str, Any]] = None,
) -> dict:
    """统一事件写入（N-03 RN-10 / ADR-05）：三表同写，缺省兜底不抛。

    入参 ctx: 可变上下文（event_counts/longline_counters/persistent_state 读写）；
    key: 事件键（`[事件:XXX]` 或 `[事件:XXX:目标]` 完整键）；instance: 事件实例
    （3f E-01 模型，可选含 target/tag/template_id/params/first_seen）。
    出参 dict: {ok, event_counts, longline_counters, logged}（回显计数与是否写日志）。
    核心逻辑:
      - instance 带 target → event_counts 写 nested {key: {target: count}}
        （对齐条件引擎 _read_counter nested 形态，防 param 条件读 0）；
        否则 flat event_counts[key] += 1。
      - longline_counters[key] += 1（只增不减，冒险日志累计）。
      - persistent_state["event_log"] 环形追加（容量可配，缺省 300），
        条目 = 3f E-01 {event_id, tag, count_key, template_id, params,
        snapshot{season,period,weather}, first_seen, ts}，ts 缺失 "--"。
    """
    try:
        key_s = str(key or "")
        if not key_s:
            return {"ok": False, "reason": "empty_key"}
        ec = _counter_of(ctx, "event_counts")
        ll = _counter_of(ctx, "longline_counters")

        # 条件引擎读取源：nested（instance.target）/ flat
        inst = dict(instance) if instance else {}
        target = inst.get("target")
        if target is not None:
            sub = ec.get(key_s)
            if not isinstance(sub, MutableMapping):
                sub = {}
                ec[key_s] = sub
            sub[str(target)] = int(sub.get(str(target), 0)) + 1
        else:
            ec[key_s] = int(ec.get(key_s, 0)) + 1

        # 冒险日志累计（只增不减）
        ll[key_s] = int(ll.get(key_s, 0)) + 1

        # 事件实例日志（环形）
        cap = _log_capacity(ctx)
        log_host = _log_list_of(ctx)
        log = log_host.get(EVENT_LOG_KEY)
        if not isinstance(log, list):
            log = []
            log_host[EVENT_LOG_KEY] = log
        tag = str(inst.get("tag") or "event")
        entry = {
            "event_id": str(inst.get("event_id") or f"{tag}:{key_s}"),
            "tag": tag,
            "count_key": str(inst.get("count_key") or key_s),
            "template_id": inst.get("template_id"),
            "params": inst.get("params") or {},
            "snapshot": _snapshot_of(ctx),
            "first_seen": bool(inst.get("first_seen", False)),
            "ts": _now_iso(ctx),
        }
        _append_ring(log, entry, cap)

        return {"ok": True, "event_counts": dict(ec), "longline_counters": dict(ll),
                "logged": len(log)}
    except Exception:  # 缺省兜底：任何异常不抛，事件不阻断结算
        return {"ok": False, "reason": "error", "logged": 0}


def read_event_log(
    ctx: Mapping[str, Any],
    *,
    limit: Optional[int] = None,
    tag: Optional[str] = None,
) -> list:
    """事件实例日志读取（EV-05 日志卡片页数据源；倒序最近优先）。

    入参 ctx: 玩家上下文（persistent_state[event_log] 优先，ctx[event_log] 兜底）；
    limit: 返回条数上限（缺省全量，日志卡片页传页大小）；tag: 按 tag 过滤
    （如 milestone/event，缺省不过滤）。
    出参: list[dict]（副本，倒序 = 最新在前；空 → []）。
    纯读零副作用；缺失/异常 → [] 不抛（对齐 bump_event 兜底精神）。
    """
    try:
        raw = None
        ps = ctx.get("persistent_state")
        if isinstance(ps, Mapping):
            raw = ps.get(EVENT_LOG_KEY)
        if not isinstance(raw, list):
            raw = ctx.get(EVENT_LOG_KEY)
        if not isinstance(raw, list):
            return []
        entries = [dict(e) for e in raw if isinstance(e, Mapping)]
        if tag is not None:
            entries = [e for e in entries if str(e.get("tag") or "") == str(tag)]
        entries.reverse()  # 最新在前（倒序）
        if limit is not None and int(limit) > 0:
            entries = entries[: int(limit)]
        return entries
    except Exception:  # 读取异常兜底空（不阻断日志卡片页）
        return []
