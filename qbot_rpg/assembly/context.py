"""A-01 make_context 工厂（M7 装配层核心，唯一 ctx 组装入口）。

依据：docs/细化/细化_M7_装配层契约.md 一、A-01（RA-01~RA-04）——ctx 字段全景以
1.3 节 RA-03 表为准（权威 = 各指令壳 docstring 真实消费字段）。字段缺省兜底（不抛
异常）；registered=False 时 player 相关字段 None（RUL-08 注册门槛拦截）。

设计纪律（RA-01 / RA-04）：
  - 纯函数：make_context 只**组装（读）**不写业务；写操作由各引擎在事务内完成。
  - 确定性：rng / now 由 deps.rng_factory / deps.dayroll 注入；未注入走默认。
  - 统一返回 dict；battle 的 sender/battle_engine 等由战斗接线（battle_commands
    装配）注入，本工厂缺省 None（指令壳自兜底 / 抛【待接线】）。

【工程补白 · 显式标注】
  1) 签名偏差：契约 RA-01 写 `make_context(event, deps) -> dict`（同步），但真实
     Repository.load_player 为 async（qbot_rpg/storage/repository.py L442，仓库无
     同步 get_player）——读档必经 await。故本工厂实现为 **async def**（返回仍为
     dict）；A-03 runner 本身 async（process_message），链路一致。测试/调用方须
     await。
  2) RA-03「repo.get_player(qid)」实为 Repository.load_player(qid)（async，60s
     缓存 + 5s 负缓存）；registered = load_player(qid) is not None。
  3) RA-03「player_attributes.calc_all_final_attributes(player)」实参应为
     player.attributes（PlayerAttributes，真实签名 L218）；conditional_rules /
     attr_types / resource_pct 取自 settings，条件规则原始 dict 先归一再算。
  4) RA-03「levelup.exp_to_next(level)」实为 LevelUpEngine.exp_next(level)
     （levelup.py L110，满级=0）；LevelUpEngine 由 settings（level_cap/exp_curve）
     现构造（deps 未含 levelup 引擎）。
  5) 兄弟路并行写 world/game_world.py（BCH-01 路 B，get_npcs 等归其交付）：本模块
     对 game_world 一律 getattr + try/except 兜底读取（get_map / monster_pool /
     get_npcs / world_stock），当前未实装/未交付 → 安全缺省值，不阻塞不抛错。
  6) 除 RA-03 权威字段外，额外注入各指令壳/引擎显式要求且可由 deps 安全推导的键：
     settings / items / shops / resolve_item / resolve_shop / add_item /
     remove_item / count_item / personal_buys / last_refresh / blackmarket_goods /
     default_map / resolve_attr_final（审查_M4实现_批次2 P0-1 与 reward.py/shop.py
     工程补白要求的入包 hook 落点）。
  7) inventory 双形态：ctx["inventory"] = {item_id: count} 计数映射（任务/条件引擎
     消费，RA-03 / quest.py L35 / shop_tx._inventory_from_player 同口径）；
     ctx["inventory_items"] = list[ItemInstance] 展示列表（basic/equip 消费）。
  8) N-03/RN-10 装配级事件 hook（N-02 挂载收口 · BCH-04）：ctx["bump_event"] 惰性
     import qbot_rpg.core.event_bus.bump_event（兄弟路 BCH-04 路A 交付中，未落盘 →
     本地安全兜底 _fallback_bump_event，同写 longline_counters + event_counts +
     event_log 三表，ADR-05）；另注入 ctx["codex_state"]（player.codex_state，NPC
     intel 图鉴点亮 O07/1e 口径，npc._action_intel 消费）与 ctx["event_log"]
     （persistent_state["event_log"] 环形数组，3f E-01 模型 BCH-07 扩展实例形态）。

零 NoneBot import（架构铁律，G0 门禁）；仅依赖 core/world/storage/content/data/commands。
"""

from __future__ import annotations

import inspect
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.levelup import LevelUpEngine
from qbot_rpg.core.player_attributes import (
    ConditionalRule,
    calc_all_final_attributes,
)
from qbot_rpg.data import Player, PlayerAttributes

__all__ = ["AssemblyDeps", "make_context"]

# 时区统一 UTC+8（对齐 core/dayroll.py _TZ_UTC8 口径）
_TZ_UTC8 = timezone(timedelta(hours=8))

# 环境标量缺失占位（RA-03：season/period/weather 缺失 → "--"）
_MISSING_ENV = "--"


# =============================================================================
# AssemblyDeps 依赖容器（RA-02）
# =============================================================================
def _default_rng_factory(qid: str) -> random.Random:
    """默认确定性 RNG 工厂：以 qid（QQ 号）为种子 → random.Random 实例。

    同 qid 同种子 → 同玩家同局序列可复现（确定性注入的缺省实现）。
    """
    return random.Random(str(qid))


def _default_dayroll() -> tuple:
    """默认 dayroll：当前 UTC+8 时刻 → (now, today)。

    返回 (datetime, str)：now 为 UTC+8 datetime；today 为 "YYYY-MM-DD" 日期键。
    生产由 runner 注入 refresh_time 对齐实现；本默认仅兜底。
    """
    now = datetime.now(_TZ_UTC8)
    return now, now.strftime("%Y-%m-%d")


@dataclass
class AssemblyDeps:
    """make_context 装配依赖容器（RA-02）：存储/世界/注册表/会话/确定性源。

    字段（类型按契约，宽松读法见各 docstring）：
      - repo: Repository（storage）——load_player(qid) 读档（async）。
      - game_world: GameWorld（world）——get_map/monster_pool/get_npcs 兜底读。
      - registry: content Registry——resolve(id, kind) / all_ids(kind) / modules_raw。
      - settings: Mapping——settings.json 装载（default_map/level_cap/shortcut_max/
        resource_pct/exp_curve/conditional_rules/attr_types/imprints/stats/quest_* 等）。
      - queue: PerPlayerQueue（processing，A-03 驱动用；本工厂不消费）。
      - session_mgr: SessionManager（world/session）——get_active(qid) 战斗/对话会话。
      - rng_factory: Callable[[str], random.Random]——确定性 RNG（seed 工厂）。
      - dayroll: Callable[[], tuple]——今日键（refresh_time 对齐）→ (now, today)。
      - time_query: Callable[[], Any]——环境快照 season/period。
      - weather_query: Callable[[], Any]——环境快照 weather。
    """

    repo: Any
    game_world: Any
    registry: Any
    settings: Mapping = field(default_factory=dict)
    queue: Any = None
    session_mgr: Any = None
    rng_factory: Callable[[str], random.Random] = field(default=_default_rng_factory)
    dayroll: Callable[[], tuple] = field(default=_default_dayroll)
    time_query: Optional[Callable[[], Any]] = None
    weather_query: Optional[Callable[[], Any]] = None


# =============================================================================
# 工具（纯函数，均带 docstring：入参 / 出参 / 核心逻辑）
# =============================================================================
def _safe_call(fn: Any, *args: Any, default: Any = None) -> Any:
    """安全调用：fn 不可调用或执行抛异常 → 返回 default（字段缺省兜底，不抛异常）。

    入参 fn: 可调用或 None；default: 兜底值。出参: fn(*args) 成功结果或 default。
    核心逻辑: callable 判定 + try/except 吞异常（装配层读快照纪律，RA-01）。
    """
    if not callable(fn):
        return default
    try:
        return fn(*args)
    except Exception:
        return default


def _count_map(inventory: Any) -> Dict[str, int]:
    """玩家背包 → {item_id: count} 计数映射（同 id 叠加）。

    入参 inventory: 可迭代（ItemInstance 元组，data/player.Player.inventory）。
    出参 Dict[str, int]。核心逻辑: 逐实例累加 count（对齐 shop_tx._inventory_from_player）。
    """
    out: Dict[str, int] = {}
    if not inventory:
        return out
    for inst in inventory:
        iid = str(getattr(inst, "item_id", "") or "")
        if not iid:
            continue
        try:
            c = int(getattr(inst, "count", 1))
        except (TypeError, ValueError):
            c = 1
        out[iid] = out.get(iid, 0) + c
    return out


def _current_title(title_state: Any) -> Optional[str]:
    """当前佩戴称号：title_state dict 的 current 键（缺省 None）。

    入参 title_state: Mapping（Player.title_state）。出参 Optional[str]。
    核心逻辑: 兼容 str（直接返回）与 dict（取 current，再取 title 兜底）。
    """
    if isinstance(title_state, str):
        return title_state
    if isinstance(title_state, Mapping):
        v = title_state.get("current") or title_state.get("title")
        return str(v) if v else None
    return None


def _worn_refs(equipment: Any) -> Dict[str, str]:
    """装备槽 → item_id 快速引用（worn_refs）。

    入参 equipment: Mapping（Player.equipment，槽位 → EquipmentSlot）。
    出参 Dict[str, str] {slot: item_id}。核心逻辑: 逐槽取实例 item_id。
    """
    out: Dict[str, str] = {}
    if not isinstance(equipment, Mapping):
        return out
    for slot, inst in equipment.items():
        iid = getattr(inst, "item_id", None)
        if iid:
            out[str(slot)] = str(iid)
    return out


def _job_name(registry: Any, job_id: str) -> str:
    """职业 ID → 中文名：registry jobs 表 resolve(id, "job").name；缺省返回 job_id。

    入参 registry: content Registry；job_id: str。出参 str。
    核心逻辑: resolve + 取 name 属性/键；任何缺失回退 job_id（不抛异常）。
    """
    if not job_id:
        return job_id
    resolve = getattr(registry, "resolve", None)
    if callable(resolve):
        try:
            job = resolve(job_id, "job")
        except Exception:
            job = None
        if job is not None:
            name = getattr(job, "name", None)
            if not name and isinstance(job, Mapping):
                name = job.get("name")
            if name:
                return str(name)
    # 2026-08-31 用户拍板：内容包无 jobs 表时职业名留空（不显示英文 id「novice」）
    return ""


def _def_name(def_obj: Any, fallback: str) -> str:
    """内容包 Def → 显示名（name 属性/键优先）；缺省返回 fallback。"""
    if def_obj is not None:
        name = getattr(def_obj, "name", None)
        if not name and isinstance(def_obj, Mapping):
            name = def_obj.get("name")
        if name:
            return str(name)
    return fallback


def _render_effects(active_effects: Any, registry: Any) -> List[Dict[str, Any]]:
    """active_effects → 展示列表（effects，status/battle 消费）。

    入参 active_effects: Mapping {effect_id: {effect, turns, refreshed}}；
    registry: content Registry。出参 List[Dict] [{name, remaining, duration, source}]。
    核心逻辑: 逐条渲染——name 经 registry effect 表反查（缺省 effect_id）、
    remaining=turns、duration 缺省 None、source 取条目 source/effect。
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(active_effects, Mapping):
        return out
    resolve = getattr(registry, "resolve", None)
    for eid, entry in active_effects.items():
        if not isinstance(entry, Mapping):
            continue
        d = None
        if callable(resolve):
            try:
                d = resolve(str(eid), "effect")
            except Exception:
                d = None
        out.append({
            "name": _def_name(d, str(eid)),
            "remaining": entry.get("turns"),
            "duration": None,
            "source": entry.get("source") or (
                str(entry["effect"]) if isinstance(entry.get("effect"), (str, int)) else None
            ),
        })
    return out


def _coerce_rules(rules: Any) -> list:
    """条件加成规则归一：raw dict → ConditionalRule（calc_all_final_attributes 入参形态）。

    入参 rules: Iterable（ConditionalRule 或 raw dict）。出参 List[ConditionalRule]。
    核心逻辑: 已实例直用；Mapping 转 ConditionalRule；非法行跳过（不抛异常）。
    """
    out: list = []
    if not rules:
        return out
    for r in rules:
        if isinstance(r, ConditionalRule):
            out.append(r)
        elif isinstance(r, Mapping):
            try:
                out.append(ConditionalRule(
                    source=str(r.get("source", "")),
                    target=str(r.get("target", "")),
                    per_point=float(r.get("per_point", 0.0)),
                    rule_id=r.get("rule_id"),
                ))
            except (TypeError, ValueError):
                continue
    return out


def _quest_active_init(ps: Any) -> Any:
    """quest_active 键强制 dict（quest 引擎期望 Mapping；旧存档 list 格式归一）。

    入参 ps: persistent_state。出参 dict（挂回 ps）。核心逻辑: 已有 dict 直返；
    list/缺省 → 归一 dict 挂回（2026-08-29 修复 quest_active 用 [] 导致引擎
    _active_node 判定失败新建独立对象 → 接取不落档）。
    """
    raw = ps.get("quest_active")
    if isinstance(raw, MutableMapping):
        return raw
    if isinstance(raw, (list, tuple)):
        # 旧存档 list 格式 → dict（元素转键，不丢数据）
        converted = {str(x): {"name": str(x)} for x in raw if isinstance(x, str)}
        ps["quest_active"] = converted
        return converted
    node: MutableMapping[str, Any] = {}
    ps["quest_active"] = node
    return node


def _ps_init(ps: Any, key: str, empty: Any) -> Any:
    """persistent_state 键惰性挂回（引擎写 ctx 对应键 → ps 持久化落档）。

    入参 ps: 玩家 persistent_state（dict）；key: 键名；empty: 缺省空值（list/dict）。
    出参 该键当前值（缺省时挂回 ps 并返回）。核心逻辑: ps 缺 key → 挂回可变副本并
    返回（引擎写入它即落档）；已有 → 直返。修复 2026-08-29 部署实测 quest_active
    首接取丢失（ps 缺省时 ctx 拿到独立空对象不挂回 → 落档丢）。
    """
    if key in ps:
        return ps[key]
    if isinstance(empty, Mapping):
        node: Any = dict(empty)
    elif isinstance(empty, (list, tuple)):
        node = list(empty)
    else:
        node = empty
    ps[key] = node
    return node


def _prof_level_map(raw: Any) -> Dict[str, int]:
    """职业等级映射 {job_id: level}（M8 批14 测试探针：quest 引擎 var=prof_level 条件消费）。

    入参 raw: persistent_state.proficiency（dict {job_id: {level, ...}} 或 {job_id: level}）。
    出参 {job_id: level int}——兼容两形态；缺失/非法 → 空 dict（引导任务不提前解锁）。
    """
    out: Dict[str, int] = {}
    if not isinstance(raw, Mapping):
        return out
    for job_id, node in raw.items():
        if isinstance(node, Mapping):
            try:
                lv = int(node.get("level", 0) or 0)
            except (TypeError, ValueError):
                lv = 0
            out[str(job_id)] = max(0, lv)
        else:
            try:
                out[str(job_id)] = max(0, int(node or 0))
            except (TypeError, ValueError):
                continue
    return out


def _coerce_heard(raw: object) -> set:
    """已听集合归一：persistent_state 任意形态（list/tuple/set）→ set（dialog 消费集合语义）。"""
    if isinstance(raw, (list, tuple, set)):
        return set(raw)
    return set()


def _attr_final(
    attributes: Any,
    conditional_rules: Any,
    settings: Mapping,
    attr_types: Any,
) -> Dict[str, int]:
    """最终层属性计算（attr_final）：calc_all_final_attributes 管线出口。

    入参 attributes: PlayerAttributes；conditional_rules: settings 规则源；
    settings: Mapping（resource_pct）；attr_types: Mapping 或 None。
    出参 Dict[str, int]（失败 → {}，字段缺省兜底）。
    核心逻辑: 规则归一 → calc_all_final_attributes(attributes, rules, resource_pct, attr_types)。
    """
    try:
        resource_pct = bool(settings.get("resource_pct", False))
        return calc_all_final_attributes(
            attributes,
            conditional_rules=_coerce_rules(conditional_rules),
            resource_pct=resource_pct,
            attr_types=attr_types,
        )
    except Exception:
        return {}


def _exp_next(settings: Mapping, level: Any) -> int:
    """升级所需经验（exp_next，LVL-11 口径满级=0）。

    入参 settings: Mapping（level_cap/exp_curve）；level: int。
    出参 int。核心逻辑: 由 settings 现构造 LevelUpEngine → exp_next(level)。
    """
    try:
        eng = LevelUpEngine(
            level_cap=int(settings.get("level_cap", 45) or 45),
            exp_curve=settings.get("exp_curve"),
        )
        return int(eng.exp_next(int(level)))
    except Exception:
        return 0


def _table_from_registry(registry: Any, kind: str) -> Dict[str, Any]:
    """registry 表 → {id: Def} 映射（items/shops 等；modules_raw 优先已由调用方定）。

    入参 registry: content Registry；kind: str（"item"/"shop"/...）。
    出参 Dict[str, Any]。核心逻辑: all_ids(kind) → resolve(id, kind) 建映射。

    M8 批14 部署实测（repro_m8probe）根治：resolve 返回 **Def 对象**（非 dict，含 .raw
    dict），此前直接透传 → 指令层 `_find_def/_find_item` 的 `isinstance(val, Mapping)` +
    `.get()` 契约全断 → 配方/材料/商店名解析失败（实测 /合成 配方不存在 /购买 没有这个
    商品 /商店 名称解析拒）。统一 Def → raw dict 转换（映射值恒为 dict，消费方 Mapping.get
    契约成立），一并覆盖 items/recipe/traits/effect/quest/shop 表。
    """
    out: Dict[str, Any] = {}
    all_ids = getattr(registry, "all_ids", None)
    resolve = getattr(registry, "resolve", None)
    if not callable(all_ids) or not callable(resolve):
        return out
    try:
        for iid in all_ids(kind):
            d = resolve(iid, kind)
            if d is not None:
                if isinstance(d, Mapping):
                    out[str(iid)] = d
                else:
                    raw = getattr(d, "raw", None)
                    if isinstance(raw, dict):
                        out[str(iid)] = raw
                    else:
                        out[str(iid)] = d  # 无 raw 的兜底原样（消费方按属性鸭子）
    except Exception:
        return out
    return out


def _forge_module_raw(registry: Any) -> Mapping[str, object]:
    """forge.json 顶层 raw dict（M9 P0-1 收口 2026-08-30）。

    入参 registry: content Registry。出参 forge 模块原始解析结果（Mapping，含
    trees/sets/augments/settings 四段）；无 registry / 无 forge 模块 → {}（GU-01
    锻造系统未启用兜底）。核心逻辑: registry.modules_raw["forge"]（Registry 新增
    public 访问器，对齐 _stats_table 从 modules_raw 取模块的模式）。
    """
    raw = getattr(registry, "modules_raw", None)
    if isinstance(raw, Mapping):
        v = raw.get("forge")
        if isinstance(v, Mapping):
            return v
    return {}


def _templates_table(registry: Any) -> Dict[str, Any]:
    """消息模板（2026-08-31 用户拍板：模板配置化，内容包 templates.json 可覆盖默认）。

    入参 registry: Registry。出参 Dict[key, str]（已合并默认 + 内容包覆盖）。
    核心逻辑: registry.modules_raw["templates"] 覆盖 core.templates.DEFAULT_TEMPLATES；
    内容包未声明 templates 模块 → 纯默认（零配置零破坏）。
    """
    from qbot_rpg.core.templates import resolve_templates

    raw = getattr(registry, "modules_raw", None)
    overrides = raw.get("templates") if isinstance(raw, Mapping) else None
    return resolve_templates(overrides)


def _stats_table(registry: Any, settings: Mapping) -> Dict[str, Any]:
    """初始属性模板（stats，/注册 build_initial_player 消费）。

    入参 registry: Registry；settings: Mapping。出参 Dict[attr_id, def]。
    核心逻辑: settings["stats"] 优先；缺省 registry.modules_raw["stats"]（原始模块形态）。
    """
    s = settings.get("stats")
    if isinstance(s, Mapping) and s:
        return dict(s)
    raw = getattr(registry, "modules_raw", None)
    if isinstance(raw, Mapping):
        st = raw.get("stats")
        if isinstance(st, Mapping):
            return dict(st)
        if isinstance(st, (list, tuple)):
            out: Dict[str, Any] = {}
            for e in st:
                if isinstance(e, Mapping) and e.get("id"):
                    out[str(e["id"])] = e
            if out:
                return out
    # 兜底：registry 装载表（loader 键名规范化 stats→stat 单数；StatDef.raw 提取原始 dict）
    tbl = getattr(registry, "_tables", None)
    if isinstance(tbl, Mapping):
        st = tbl.get("stat") or tbl.get("stats")
        if isinstance(st, Mapping):
            out = {}
            for k, v in st.items():
                if isinstance(v, Mapping):
                    out[str(k)] = dict(v)
                else:
                    vraw = getattr(v, "raw", None)
                    out[str(k)] = dict(vraw) if isinstance(vraw, Mapping) else v
            if out:
                return out
    return {}


def _restore_dialog_session(raw: Any) -> Any:
    """persistent_state["dialog_session"] → DialogSession（from_snapshot，缺省 None）。

    入参 raw: Mapping 会话快照。出参 DialogSession 或 None。
    核心逻辑: 惰性 import core.dialog.DialogSession.from_snapshot 恢复；失败 → None。
    """
    if not isinstance(raw, Mapping):
        return None
    try:
        from qbot_rpg.core.dialog import DialogSession

        return DialogSession.from_snapshot(raw)
    except Exception:
        return None


def _dialog_snapshot_or_cleared(ps: Mapping) -> Any:
    """RN-11（N-04）：读取前对 persistent_state 的 dialog_session 做 30 天惰性清理。

    入参 ps: 玩家 persistent_state（Mapping；可写时就地清除过期快照）。出参 Any:
    清理后的 dialog_session 原值（过期已清除 → None）。核心逻辑: 惰性 import
    core.adventure_log.cleanup_dialog_snapshot；过期 → 就地清除 + 返回 None；
    read-only/无快照/解析失败 → 原样返回（不误删）。与已交付标记
    npc_heard/npc_delivered（常驻不回收）分离。
    """
    try:
        from qbot_rpg.core.adventure_log import cleanup_dialog_snapshot

        cleanup_dialog_snapshot({"persistent_state": ps})
    except Exception:
        pass
    return ps.get("dialog_session")


def _get_map(game_world: Any, location: Optional[str]) -> Any:
    """map_def：game_world.get_map(location) 兜底读（兄弟路未实装 → None）。

    入参 game_world: GameWorld；location: Optional[str]。出参 MapDef 或 None。
    """
    if not location:
        return None
    fn = getattr(game_world, "get_map", None)
    return _safe_call(fn, location, default=None)


def _monster_pool(game_world: Any, location: Optional[str]) -> List[Any]:
    """monster_pool：game_world.monster_pool(location) 兜底读（缺省 []）。

    入参 game_world: GameWorld；location: Optional[str]。出参 List。
    """
    if not location:
        return []
    fn = getattr(game_world, "monster_pool", None)
    r = _safe_call(fn, location, default=[])
    return list(r) if isinstance(r, (list, tuple)) else []


def _npcs(game_world: Any, location: Optional[str]) -> List[Any]:
    """npcs：game_world.get_npcs(location) 兜底读（BCH-01 路 B 交付前 → []）。

    入参 game_world: GameWorld；location: Optional[str]。出参 List[dict]。
    """
    if not location:
        return []
    fn = getattr(game_world, "get_npcs", None)
    r = _safe_call(fn, location, default=[])
    return list(r) if isinstance(r, (list, tuple)) else []


def _event_key_parts(key: str) -> tuple:
    """事件键 → (name, param)：`[事件:NPC对话:张三]` → ("[事件:NPC对话]", "张三")。

    规则: 前缀 `[事件:` 且尾缀 `]` → 剥离外壳后按最后一个 ':' 切分（对齐
    condition_engine._parse_event_var 的 name:target 口径）；无内嵌目标/非事件键 →
    (key, None)。出参 tuple[str, Optional[str]]，纯函数确定性。
    """
    if key.startswith("[事件:") and key.endswith("]"):
        inner = key[len("[事件:"):-1]
        if ":" in inner:
            name, _, target = inner.rpartition(":")
            return "[事件:" + name + "]", target
    return key, None


def _fallback_bump_event(ctx: MutableMapping[str, Any], key: str,
                         *, instance: Any = None) -> None:
    """bump_event 安全缺省实现（RN-10 · ADR-05 三表；兄弟路 event_bus 落盘前兜底）。

    入参 ctx: 可变 ctx（就地读写）；key: 事件键；instance: 事件实例（缺省自动构造
    {"key", "ts"}）。出参 None。核心逻辑:
      - longline_counters[原始事件键] +1（冒险日志累计口径，RN-09 全键）；
      - event_counts 写**条件引擎可读形态**（condition_engine._read_counter 扁平口径：
        无参 → name 标量 +1；带内嵌目标 → "name:param" 复合键 +1）——否则 [事件:*]
        条件读不到计数（dsh 审查 P1-3 口径）；
      - event_log 环形追加（settings.event_log_cap 缺省 300，超限弹首条；event_log
        缺省/非 list → 仅双表，不抛错）。

    确定性：纯函数原地改写 ctx；instance 缺省由 ctx["now"] 派生（注入可复现）。
    【工程补白】event_log 实例最小形态 {"key","ts"}；3f E-01 模型（snapshot/first_seen/
    ts）由 BCH-07 批次扩展，本兜底保持稳定最小契约。
    """
    if not isinstance(ctx, MutableMapping) or not key:
        return
    key = str(key)
    node = ctx.get("longline_counters")
    if isinstance(node, MutableMapping):
        node[key] = int(node.get(key, 0) or 0) + 1
    name, param = _event_key_parts(key)
    node = ctx.get("event_counts")
    if isinstance(node, MutableMapping):
        if param is None:
            node[name] = int(node.get(name, 0) or 0) + 1
        else:
            compound = f"{name}:{param}"
            node[compound] = int(node.get(compound, 0) or 0) + 1
    if instance is None:
        instance = {"key": key, "ts": ctx.get("now")}
    log = ctx.get("event_log")
    if isinstance(log, list):
        cap = 300
        settings = ctx.get("settings")
        if isinstance(settings, Mapping):
            cap = int(settings.get("event_log_cap", 300) or 300)
        if cap > 0 and len(log) >= cap:
            log.pop(0)
        log.append(instance)
    elif isinstance(log, MutableMapping):  # 映射形态兜底（{key: instance}）
        log[key] = instance


def _resolve_bump_event() -> Callable[..., Any]:
    """装配级 bump_event hook：惰性 import core.event_bus.bump_event（兄弟路 BCH-04 路A）。

    未落盘（ImportError/AttributeError 等）→ 返回 _fallback_bump_event（RN-10 三表安全
    兜底，不抛错不阻塞装配）。出参 Callable，签名 (ctx, key, *, instance=None)——与
    dialog_commands._bump_events 的 hook(ctx, key) 调用形态兼容。
    """
    try:
        from qbot_rpg.core.event_bus import bump_event

        if callable(bump_event):
            return bump_event
    except Exception:
        pass
    return _fallback_bump_event


def _coerce_event_log(raw: object) -> list:
    """event_log 归一：persistent_state["event_log"]（JSON 数组）→ 可写 list（缺省 []）。

    入参 raw: 任意形态（list 直通复用；tuple/set 转 list；None/其它 → []）。
    出参 list。核心逻辑: 仅 list 原样返回（装配提交写回同容器），其余安全空值。
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, (tuple, set, frozenset)):
        return list(raw)
    return []


def _npc_interactions_of(npcs: Any, npc_id: object) -> list:
    """装配级 npc_interactions hook 纯函数：按 id 从 npcs 取 interactions（RN-05，缺省 []）。

    入参 npcs: 当前地图 NPC 列表（ctx["npcs"]）；npc_id: NPC id。出参 List[Mapping]。
    核心逻辑: 逐 NPC 匹配 id（字符串化比较）→ 返回其 interactions[]（仅保留 Mapping 条目，
    对齐 dialog._npc_interactions 的 hook 契约）；未命中 → []。纯函数确定性，不抛错。
    """
    if not npc_id:
        return []
    for n in npcs or ():
        if isinstance(n, Mapping) and str(n.get("id")) == str(npc_id):
            return [o for o in (n.get("interactions") or ()) if isinstance(o, Mapping)]
    return []


async def _battle_session(session_mgr: Any, qid: str) -> Any:
    """battle_session：session_mgr.get_active(qid) 兜底读（缺省 None）。

    入参 session_mgr: SessionManager（get_active 现 async，M8 实装）；qid: str。
    出参 会话视图对象（SessionView）/dict 或 None。
    核心逻辑: get_active 结果 await（兼容同步伪实现：isawaitable 判定，旧测试
    fake 返回 None/抛 NotImplementedError 时 _safe_call 兜底不抛）。
    """
    if session_mgr is None:
        return None
    fn = getattr(session_mgr, "get_active", None)
    out = _safe_call(fn, qid, default=None)
    if inspect.isawaitable(out):
        return await out
    return out


def _bs_field(bs: Any, key: str) -> Any:
    """battle_session 快照字段（target/turn）兼容读取：dict 或对象属性。

    入参 bs: 快照；key: str。出参 字段值或 None。
    """
    if bs is None:
        return None
    if isinstance(bs, Mapping):
        return bs.get(key)
    return getattr(bs, key, None)


def _rng(rng_factory: Any, qid: str) -> random.Random:
    """确定性 RNG：deps.rng_factory(qid)（缺省 random.Random(str(qid))）。

    入参 rng_factory: Callable[[str], random.Random]；qid: str。出参 random.Random。
    """
    r = _safe_call(rng_factory, qid, default=None)
    return r if isinstance(r, random.Random) else random.Random(str(qid))


def _as_utc8_timestamp(now: Any) -> Optional[int]:
    """now 归一为绝对秒级时间戳（对齐 checkin/dayroll 引擎契约 _now(ctx) 期望 int）。

    入参 now: datetime（_default_dayroll 返回 UTC+8 datetime）或 int/float（已时间戳）。
    出参 int|None：datetime → int(now.timestamp())（绝对 epoch 秒）；数值 → int()；
    其它 → None（缺省兜底）。
    核心逻辑: 类型分派；bool 除外（True 会被 int() 当 1，防误判）。
    """
    if isinstance(now, datetime):
        return int(now.timestamp())
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        return int(now)
    return None


def _now_today(dayroll: Any) -> tuple:
    """now/today：deps.dayroll() → (datetime, str 日期键)；缺省 (None, "")。

    入参 dayroll: Callable[[], tuple]。出参 tuple[(datetime|None), str]。
    兼容 dayroll 返回 dict（含 now/today 键）或 tuple/list（(now, today)）。
    """
    r = _safe_call(dayroll, default=None)
    if isinstance(r, Mapping):
        return r.get("now"), str(r.get("today") or "")
    if isinstance(r, (tuple, list)) and len(r) >= 2:
        return r[0], str(r[1] or "")
    return None, ""


def _season_period(time_query: Any) -> tuple:
    """season/period：deps.time_query() 环境快照；缺失 → ("--", "--")。

    入参 time_query: Callable。出参 tuple[str, str]。
    核心逻辑: 兼容 Mapping（season/period 键）或标量 str（season）。
    """
    r = _safe_call(time_query, default=None)
    if isinstance(r, Mapping):
        return str(r.get("season") or _MISSING_ENV), str(r.get("period") or _MISSING_ENV)
    if isinstance(r, str) and r:
        return r, _MISSING_ENV
    return _MISSING_ENV, _MISSING_ENV


def _weather(weather_query: Any) -> str:
    """weather：deps.weather_query()；缺失 → "--"。"""
    r = _safe_call(weather_query, default=None)
    return str(r) if r else _MISSING_ENV


def _gm_commands() -> set:
    """GM 指令集合（data.gm_constants.GM_COMMANDS，快捷绑定校验注入；缺省空集）。

    核心逻辑: 惰性 import qbot_rpg.data.gm_constants（data 层通用底层，assembly 可依赖；
    导入失败 → 空集）。
    """
    try:
        from qbot_rpg.data.gm_constants import GM_COMMANDS

        return set(GM_COMMANDS)
    except Exception:
        return set()


def _gem_wallet_of(settings: Any) -> Any:
    """宝石货币引擎（GemWallet，惰性 import 防环；M8 批12 收口装配注入）。"""
    from qbot_rpg.core.gem_wallet import GemWallet  # noqa: PLC0415
    try:
        return GemWallet(settings=settings if isinstance(settings, Mapping) else None)
    except Exception:  # noqa: BLE001 —— 构造失败兜底 None，指令壳自兜底
        return None


def _prof_engine_of_ctx(settings: Any) -> Any:
    """职业熟练度引擎（ProficiencyEngine，惰性 import 防环；M8 批12 收口装配注入）。"""
    from qbot_rpg.core.proficiency import ProficiencyEngine  # noqa: PLC0415
    try:
        return ProficiencyEngine(settings=settings if isinstance(settings, Mapping) else None)
    except Exception:  # noqa: BLE001
        return None


def _inventory_hooks(ctx: MutableMapping[str, Any]) -> dict:
    """背包入包/扣物/计数 hook（add_item/remove_item/count_item，reward.py/shop.py 契约）。

    入参 ctx: 可变 ctx（就地读写 ctx["inventory"] 计数映射 + ctx["inventory_instances"]）。
    出参 Dict[str, Callable] 三个 hook。核心逻辑: 闭包操作 ctx 内 {item_id: count}
    映射——add_item(item_id, count, bound)->bool 累加；remove_item(item_id, count)->bool
    校验够数扣减（0 移除）；count_item(item_id)->int 读取。

    M8 批12 验收收口（落档缺口修复）：① add/remove 就地改背包时置 ctx["_m8_dirty_inventory"]=True
    （runner 落档前据此合并回 ctx["player"]）；② add_item 支持 quality/traits 关键字
    （SettleEngine._produce / 炼金产出实例）→ 追加到 ctx["inventory_instances"]（带品质/特性
    实例通道，Player.inventory 保留实例属性，落档 merge 并入）。
    """
    raw_inv = ctx.get("inventory")
    inv: Dict[str, int] = raw_inv if isinstance(raw_inv, dict) else {}
    ctx["inventory"] = inv
    insts_raw = ctx.get("inventory_instances")
    if isinstance(insts_raw, list):
        insts: Any = insts_raw
    else:
        insts = []
        ctx["inventory_instances"] = insts

    def _mark() -> None:
        ctx["_m8_dirty_inventory"] = True

    def add_item(item_id: str, count: int = 1, bound: bool = False,
                 **kw: Any) -> bool:
        """入包：计数映射累加 count；带 quality/traits → 实例通道；非法 count → False。"""
        try:
            c = int(count)
        except (TypeError, ValueError):
            return False
        if c < 1:
            return False
        key = str(item_id)
        inv[key] = inv.get(key, 0) + c
        # M8 炼金产出实例（quality/traits 关键字）→ 追加实例通道（保留品质/特性落档）
        if kw and (kw.get("quality") is not None or kw.get("traits")):
            insts.append({
                "item_id": key,
                "count": c,
                "quality": kw.get("quality") or "normal",
                "bound": bool(bound),
                "traits": tuple(kw.get("traits") or ()),
            })
        _mark()
        return True

    def remove_item(item_id: str, count: int = 1) -> bool:
        """扣物：够数则扣减（0 移除），否则 False。"""
        try:
            c = int(count)
        except (TypeError, ValueError):
            return False
        if c < 1:
            return False
        key = str(item_id)
        cur = int(inv.get(key, 0))
        if cur < c:
            return False
        if cur == c:
            inv.pop(key, None)
        else:
            inv[key] = cur - c
        _mark()
        return True

    def count_item(item_id: str) -> int:
        """计数：返回 item_id 当前持有数（缺省 0）。"""
        return int(inv.get(str(item_id), 0))

    return {"add_item": add_item, "remove_item": remove_item, "count_item": count_item}


# =============================================================================
# make_context 工厂（A-01 核心）
# =============================================================================
async def make_context(event: Mapping, deps: AssemblyDeps) -> dict:
    """A-01 make_context 工厂：事件 + 装配依赖 → 完整玩家 ctx（读快照，RA-03 全字段）。

    入参:
      - event: Mapping——{group_id, user_id, message, channel}（可含 group_name/
        per_channel/to/qq_id/is_gm）。
      - deps: AssemblyDeps——装配依赖容器（RA-02：repo/game_world/registry/settings/
        queue/session_mgr/rng_factory/dayroll/time_query/weather_query）。
    出参: dict——RA-03 全景 ctx（registered=False 时 player 相关标量字段 None，
      集合类字段安全空值；字段缺省兜底，不抛异常）。

    核心逻辑:
      ① 事件归一 → qid（user_id 或 qq_id）→ repo.load_player(qid) 读档（async）；
      ② registered = player 非 None；
      ③ 已注册：逐字段由 player/persistent_state/settings/registry/game_world/
        session_mgr/确定性源组装；未注册：player 相关标量 None + 安全空值；
      ④ 引擎类（quest_engine/shop_engine/checkin_engine/battle_engine/battle_
        reward_fn 等）由 A-02/战斗接线注入，本工厂缺省 None（指令壳自兜底）；
      ⑤ 全程 try/except 兜底读取（兄弟路 game_world 未实装方法安全缺省）。
    """
    # -- ① 事件归一 + 读档 ---------------------------------------------------
    qid = str(event.get("qq_id") or event.get("user_id") or "")  # QQ 平台身份键 qq_id 优先（RA-03）
    group_id = event.get("group_id")

    player: Optional[Player] = None
    repo = deps.repo
    loader = getattr(repo, "load_player", None) if repo is not None else None
    if not callable(loader):  # 兼容契约名 get_player（真实仓库为 load_player）
        loader = getattr(repo, "get_player", None) if repo is not None else None
    if qid and callable(loader):
        try:
            player = await loader(qid)
        except Exception:
            player = None

    registered = player is not None
    settings = deps.settings if isinstance(deps.settings, Mapping) else {}

    # -- ② 基础 ctx（事件透传 + 注册态） --------------------------------------
    ctx: Dict[str, Any] = {
        "registered": registered,
        "player": player,
        "settings": settings,
        "default_map": settings.get("default_map"),
        # 事件透传（prefix_wiring / sender 消费）
        "group_id": group_id,
        "user_id": event.get("user_id"),
        "message": event.get("message"),
        "channel": event.get("channel"),
        "group_name": event.get("group_name"),
        "per_channel": event.get("per_channel"),
        "to": event.get("to"),
        "qq_id": qid or None,
        "qid": qid or None,  # M8 批14 部署实测：_qid_of 取 ctx["qid"]（会话主键 MUT-02），
        # 仅 qq_id 时 _qid_of 读不到 → session.player_qid=None → /投料 按 qid 查无会话；补键对齐
        "is_gm": bool(event.get("is_gm", False)),
        # M8 批13 审查收口（P0-2 终态结算注入断裂）：message_id 透传——
        # /确认 /放弃 的 SettleEngine gate `if message_id:` 依赖它走 settle_alchemy
        # （delete_session+write_idem_key 同事务）；缺失则终态不删会话不落幂等键。
        "message_id": str(event.get("message_id") or ""),
        # 引擎注入位（A-02 / 战斗接线注入；缺省 None → 指令壳自兜底/【待接线】）
        "quest_engine": None,
        "shop_engine": None,
        "checkin_engine": None,
        "battle_engine": None,
        "battle_reward_fn": None,
        "battle_rewards": {},
        "battle_hint": None,
        "battle_status_changes": [],
        "current_shop_ref": [],
        # M8 炼金（批11-2 收口接线：注册表表视图 + 会话/战斗/引擎注入位；指令壳自兜底）
        "registry": deps.registry,
        "session_mgr": deps.session_mgr,
        "items": _table_from_registry(deps.registry, "item"),
        "recipe": _table_from_registry(deps.registry, "recipe"),
        "traits": _table_from_registry(deps.registry, "trait"),
        # M9 锻造（批C 审查 P0-1 收口 2026-08-30）：ctx["forge"] 注入 forge.json 顶层
        # raw dict（含 trees/sets/augments/settings 四段）——forge 指令壳 _forge_raw
        # 消费；forge 非条目表（顶层 obj），不能走 _table_from_registry（Def→dict
        # 表注入坑见 m9_接口摸底 §八-2），从 registry.modules_raw 直接取模块原始解析
        # 结果（Registry 新增 modules_raw public 访问器）。
        "forge": _forge_module_raw(deps.registry),
        "battle_snapshot": None,          # 战斗接线注入位（即时调合 battle_alchemy_used）
        "battle_alchemy_engine": None,    # 战斗接线注入位（BattleAlchemyEngine）
        "upgrade_unlocks": {},            # 玩家级解锁表（配方合成/进化持久化，装配层回填）
        # M8 批12 验收收口：wallet/prof_engine 实际构造注入（惰性 import 防环，
        # cmd_decompose/cmd_skill_panel 等真实引擎消费；settings 单源注入）
        "wallet": _gem_wallet_of(settings),
        "prof_engine": _prof_engine_of_ctx(settings),
        "resolve_player_name": None,      # /协力 玩家名 hook 注入位
        "same_group": None,               # /协力 同群校验注入位
    }

    # -- ③ 玩家相关字段（registered=False → 标量 None + 集合安全空值） ----------
    if registered:
        assert player is not None
        ps = player.persistent_state if isinstance(player.persistent_state, Mapping) else {}
        attrs = player.attributes if isinstance(player.attributes, PlayerAttributes) \
            else PlayerAttributes()
        conditional_rules = settings.get("conditional_rules") or ()
        attr_types = settings.get("attr_types")
        location = str(ps.get("location") or settings.get("default_map") or "")
        ae_raw = ps.get("active_effects")

        ctx.update({
            "name": player.name,
            "job_id": player.job_id,
            "level": player.level,
            "exp": player.exp,
            "hp": player.hp,
            "mp": player.mp,
            "job_name": _job_name(deps.registry, player.job_id),
            "location": location,
            "title": _current_title(player.title_state),
            "stats": _stats_table(deps.registry, settings),
            "templates": _templates_table(deps.registry),
            "attributes": attrs,
            "attr_final": _attr_final(attrs, conditional_rules, settings, attr_types),
            "exp_next": _exp_next(settings, player.level),
            "level_cap": int(settings.get("level_cap", 45) or 45),
            "conditional_rules": conditional_rules,
            "attr_types": attr_types,
            "imprints": settings.get("imprints") or {},
            "inventory": _count_map(player.inventory),
            "inventory_items": list(player.inventory),
            "equipment": dict(player.equipment),
            "worn_refs": _worn_refs(player.equipment),
            "active_effects": dict(ae_raw) if isinstance(ae_raw, Mapping) else {},
            "effects": _render_effects(ps.get("active_effects"), deps.registry),
            "quest_active": _quest_active_init(ps),
            "quest_completed": _ps_init(ps, "quest_completed", []),
            "quest_daily": _ps_init(ps, "quest_daily", {}),
            "longline_counters": dict(player.longline_counters)
                if isinstance(player.longline_counters, Mapping) else {},
            "event_counts": _ps_init(ps, "event_counts", {}),
            # M8 批12 验收收口裁决（落档缺口修复）：ctx["currencies"] 直接引用
            # player.currencies（frozen dataclass 可变子结构，就地改 = 改 player → 落档保留）。
            # 原 dict() 拷贝导致 M8/reward 宝石金币入账只改副本、Player 实例落档路径不回写丢失。
            "currencies": player.currencies
                if isinstance(player.currencies, MutableMapping) else {},
            # M9 锻造·实机部署收口（2026-08-30）：ctx["title_state"] 就地引用
            # player.title_state（同 currencies 模式）。铸造王授予经
            # grant_king_title 写 player["title_state"]——生产 ctx["player"] 是 Player
            # dataclass，_player_of 回退 ctx 时若 ctx 无 title_state 键 → 授予写到临时
            # 键落档丢失（实机：全链锻造后 title_state.owned 仍空）。挂回后授予即落档。
            "title_state": player.title_state
                if isinstance(player.title_state, MutableMapping) else {},
            "personal_buys": _ps_init(ps, "personal_buys", {}),
            "checkin_state": _ps_init(ps, "checkin", {}),
            "shortcuts": _ps_init(ps, "shortcuts", {}),
            "shortcut_max": int(settings.get("shortcut_max", 20) or 20),
            "npc_delivered": _ps_init(ps, "npc_delivered", {}),
            "heard": _coerce_heard(ps.get("npc_heard")),
            "codex_state": player.codex_state
                if isinstance(player.codex_state, MutableMapping) else {},
            "event_log": _coerce_event_log(ps.get("event_log")),
            "dialog_active": bool(ps.get("dialog_active", False)),
            # RN-11（N-04）：dialog_session 30 天惰性清理（读取/启动时；last_active_at
            # 超 30 天 → 清除恢复上下文，见 _dialog_snapshot_or_cleared）
            "dialog_session": _restore_dialog_session(_dialog_snapshot_or_cleared(ps)),
            # M8 批13 审查收口（P0-1 地块/代工不落档 + P1-4 proficiency 未注入）：
            # _ps_init 挂回 persistent_state 可变引用——引擎写 ctx[farm_plots/helpers/
            # proficiency] 即落档（对齐 currencies 就地引用方案；Player frozen dataclass
            # 无这些字段，引擎经 _player_of 回退 ctx 写入本键）。
            "farm_plots": _ps_init(ps, "farm_plots", {}),
            "helpers": _ps_init(ps, "helpers", {}),
            "proficiency": _ps_init(ps, "proficiency", {}),
            # M9 锻造（批C 审查 P0-2 收口 2026-08-30）：确认窗挂 player.persistent_state
            # ——生产每次指令 make_context 重建 ctx，窗存 ctx 内存键会随本次指令丢弃，
            # 预览后 /确认 恒「无可确认」；改为 _ps_init 挂回 ps（引擎写 ctx 键即落档），
            # 预览/确认 跨指令共享同一窗源（F-3 预留口径，装配层补接线）。
            "forge_preview": _ps_init(ps, "forge_preview", {}),
            # M9 锻造·实机部署收口（2026-08-30）：已锻造集合落档挂回 persistent_state。
            # 部署实测：/锻造 成功扣素材扣金币均落档，但 forge_commands 写
            # player["forged"] 顶层键——生产 ctx["player"] 是 Player dataclass 非
            # MutableMapping，_player_of 回退返回 ctx 自身 → 写入 ctx["forged"]（每指令
            # 重建的临时键）→ 落档丢失 → 前置判定「需先锻造」恒拦。挂回 ps 后引擎写
            # ctx["forged"] 即落档（forge_tree._forged_set 读 player["forged"] 兼容，
            # 因 ctx 即 player 兜底；ps 键名 forge_forged 防与其它系统 forged 冲突）。
            "forged": _ps_init(ps, "forge_forged", []),
            # M8 批14 测试探针（炼金引导任务）：ctx["prof_level"] 职业等级映射
            # {job_id: level}——quest 引擎 var=prof_level 条件（param=job_id）消费；
            # 未注册/无建档 → {} 空（条件不满足，引导任务不提前解锁）。
            "prof_level": _prof_level_map(ps.get("proficiency")),
            # M8 炼金（批11-2 收口）：背包 hooks（_inventory_hooks 就地操作
            # ctx["inventory"] 计数映射，reward/shop 同款契约）+ 玩家级解锁表回填
            # （配方合成/进化持久化，换包同 ID 保留 DUP-06）
            **_inventory_hooks(ctx),
            "upgrade_unlocks": _ps_init(ps, "upgrade_unlocks", {}),
        })
    else:
        ctx.update({
            "name": None, "job_id": None, "level": None, "exp": None,
            "hp": None, "mp": None, "job_name": None, "location": None,
            "title": None, "stats": _stats_table(deps.registry, settings),
            "attributes": None, "attr_final": {}, "exp_next": None,
            "level_cap": int(settings.get("level_cap", 45) or 45),
            "conditional_rules": settings.get("conditional_rules") or (),
            "attr_types": settings.get("attr_types"),
            "imprints": settings.get("imprints") or {},
            "inventory": {}, "inventory_items": [],
            "equipment": {}, "worn_refs": {},
            "active_effects": {}, "effects": [],
            "quest_active": [], "quest_completed": [], "quest_daily": {},
            "longline_counters": {}, "event_counts": {},
            "currencies": {}, "personal_buys": {},
            "checkin_state": {}, "shortcuts": {},
            "shortcut_max": int(settings.get("shortcut_max", 20) or 20),
            "npc_delivered": {}, "heard": set(),
            "codex_state": {}, "event_log": [],
            "dialog_active": False, "dialog_session": None,
        })

    # -- ④ 世界/会话/环境/确定性源（与注册态无关） ------------------------------
    ctx["game_world"] = deps.game_world
    ctx["map_def"] = _get_map(deps.game_world, ctx.get("location"))
    ctx["monster_pool"] = _monster_pool(deps.game_world, ctx.get("location"))
    ctx["npcs"] = _npcs(deps.game_world, ctx.get("location"))
    # npc_interactions hook（RN-05）：按 id 从 ctx["npcs"] 解析 interactions（N-02 收口，
    # dialog 引擎 _npc_interactions 优先消费本 hook；缺省 [] → 菜单仅「离开」）
    ctx["npc_interactions"] = lambda npc_id: _npc_interactions_of(ctx["npcs"], npc_id)
    ctx["world_stock"] = {}      # {shop_id: {item_id: int}}（A-05 world 装配注入快照）
    ctx["world_sold_out"] = {}   # {shop_id: {item_id: True}}（同上）
    ctx["last_refresh"] = {}     # {shop_id: "YYYY-MM-DD"}（同上）
    ctx["blackmarket_goods"] = {}  # {shop_id: [goods...]}（同上）

    battle_session = await _battle_session(deps.session_mgr, qid)
    ctx["battle_session"] = battle_session
    ctx["target"] = _bs_field(battle_session, "target")
    ctx["turn"] = _bs_field(battle_session, "turn")
    # M8 批13 审查收口（P1-3 战斗拦截模板生产不可达）：in_battle 注入——
    # /投料 /继承 /确认 /放弃 的 GU-10 战斗拦截依赖 ctx["in_battle"]；缺则
    # 战斗中发调合指令走错误模板（会话互斥仍兜底，但契约消息不可达）。
    ctx["in_battle"] = bool(
        battle_session is not None
        and isinstance(getattr(battle_session, "session_type", None), str)
        and "battle" in str(getattr(battle_session, "session_type", ""))
    )

    ctx["rng"] = _rng(deps.rng_factory, qid)
    _now, _today = _now_today(deps.dayroll)
    ctx["now"] = _as_utc8_timestamp(_now)
    ctx["today"] = _today
    ctx["season"], ctx["period"] = _season_period(deps.time_query)
    ctx["weather"] = _weather(deps.weather_query)

    # -- ⑤ 注册表/入包 hook（RA-03 之外、各指令壳显式要求） ----------------------
    ctx["gm_commands"] = _gm_commands()
    ctx["items"] = _table_from_registry(deps.registry, "item")
    ctx["effect_table"] = _table_from_registry(deps.registry, "effect")
    # quest 表（装配缺口修复：quest 引擎读 ctx["quests"]/quest_ids，注入 raw dict
    # 保证 resolve_quest Mapping.get 契约；2026-08-29 部署实测 test_demo 任务板空）
    _quests = _table_from_registry(deps.registry, "quest")
    ctx["quests"] = {
        str(k): (dict(v.raw) if isinstance(getattr(v, "raw", None), dict) else v)
        for k, v in _quests.items()
        if isinstance(k, str)
    }
    ctx["quest_ids"] = list(ctx["quests"].keys())
    # M8 批14 部署实测（repro_m8probe）：/商店 <名称> 解析失败——ctx["shops"] 未做
    # Def→raw dict 转换（对比 quest 表 L1049 已修），resolve_shop 的 `isinstance(hit, Mapping)`
    # 判定 False → 名称/全表匹配全拒。对齐 quest 修复：raw dict 保证 Mapping.get 契约。
    _shops = _table_from_registry(deps.registry, "shop")
    ctx["shops"] = {
        str(k): (dict(v.raw) if isinstance(getattr(v, "raw", None), dict) else v)
        for k, v in _shops.items()
        if isinstance(k, str)
    }
    # 签到表（QA 批2 P2-6/P2-7 根因修复 2026-08-31）：ctx["checkin_tables"] 从未注入——checkin 引擎
    # _all_checkin_tables 读 ctx["checkin_tables"] 得 None → 零生效表 → /签到 结算不落表、
    # /签到 状态 只回「✅ 签到状态」空面板、同日重复 /签到 走不到幂等分支（P2-7）。对齐 quest/shop
    # 同款注入：registry kind="checkin"（loader _KIND_FOR_MODULE 已登记），Def→raw dict 保证
    # core/checkin resolve_checkin_table/_all_checkin_tables 的 Mapping.get 契约。
    _checkins = _table_from_registry(deps.registry, "checkin")
    ctx["checkin_tables"] = {
        str(k): (dict(v.raw) if isinstance(getattr(v, "raw", None), dict) else v)
        for k, v in _checkins.items()
        if isinstance(k, str)
    }
    # M8 批14 部署实测收口（/投料 /合成 名解析失败）：registry.resolve 签名 (key, kind)，
    # 指令层 _find_def 单参调用 resolver(key) → TypeError 被 except 吞 → name 扫描永不执行。
    # 注入单参包装绑定 kind（对齐指令壳 resolver 契约）；_find_def 异常也落 name 扫描兜底。
    # M9 实机反馈收口（2026-08-30）：/进入 /位置 空回——ctx["maps"] 从未注入（装配层
    # 只注了 items/quest/shop 表，探索模块读 ctx["maps"] 得 None → 地图索引空 → 入口/
    # 通道/当前位置全失效）。补 maps/dungeons/enemies 三表（对齐 quests 的 raw dict 契约；
    # map kind=map / dungeon kind=dungeon / enemy kind=enemy，见 loader._KIND_FOR_MODULE）。
    for _kind, _key in (("map", "maps"), ("dungeon", "dungeons"), ("enemy", "enemies")):
        _tab = _table_from_registry(deps.registry, _kind)
        _mapped = {
            str(k): (dict(v.raw) if isinstance(getattr(v, "raw", None), dict) else v)
            for k, v in _tab.items()
            if isinstance(k, str)
        }
        if _kind == "map":
            # maps 索引需 list 形态（movement._maps_index 认 modules 容器/条目列表，
            # 不认 {id: raw} dict；dict 形态实测 _maps_index 返回空表 → /进入 /位置 全失效）
            ctx[_key] = list(_mapped.values())
        else:
            ctx[_key] = _mapped
    def _kind_resolver(kind: str):
        def _res(key: Any) -> Any:
            try:
                return deps.registry.resolve(key, kind)
            except Exception:
                return None
        return _res

    ctx["resolve_item"] = _kind_resolver("item")
    ctx["resolve_shop"] = _kind_resolver("shop")
    ctx["resolve_recipe"] = _kind_resolver("recipe")
    ctx["resolve_trait"] = _kind_resolver("trait")
    # bump_event：N-03 RN-10 装配级统一事件 hook（dialog_commands._bump_events 优先消费；
    # 兄弟路 event_bus 未落盘 → 本地三表安全兜底，见 _resolve_bump_event）
    ctx["bump_event"] = _resolve_bump_event()
    ctx.update(_inventory_hooks(ctx))
    # resolve_attr_final：status_commands 兜底取最终层（复用已算 attr_final）
    ctx["resolve_attr_final"] = lambda: ctx.get("attr_final") or {}

    return ctx
