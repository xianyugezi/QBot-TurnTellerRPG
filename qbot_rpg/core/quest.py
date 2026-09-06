"""任务引擎（M4 批次4·路E2 · qbot_rpg/core/quest.py）——三原语求值 + 接取/交付/防刷 + 主线置顶 + 双板。

依据：
  - m4_shared_contract.md §3.3（D1-D5：三原语引擎（值型/累计型/事件型）+ 统一 reward + 每日防刷
    （daily_limit≤10 / accept_limit≤5 / quest_daily / 完成即移出）+ 主线置顶（main:true 常驻）+
    任务板 /任务 接取 N / 交付 N（+任务信息/放弃）；双板仲裁（日常+主线）；main 沿用定稿 L138 命名；
    发放器失败策略统一（A1 P1-2：逐条目失败黄字跳过、不中断整批；单事务=结算簿记原子性））
  - docs/细化/细化_2b4_任务引擎契约.md（§二 三原语判定语义表 2.2 / op 双写 2.3 / main_progress 2.5 /
    D-02 数组全与 / D-03 求值失败默认不满足 / §三 统一 reward（D-05 内联糖） / §四 防刷 F-1~F-5 +
    D-04 完成结算单事务 / §五 任务板主线置顶 + 双板仲裁（§5.4 /任务=玩家任务板、委托板 /委托 独立）/
    TC-01~TC-31）
  - docs/审查参考/任务系统设计定稿.md（三原语 L19-36 / op 双写 L37 / 防刷 L183-187 / 统一 reward
    L108-126 / main 常驻不移除 L138 / quest_active L204-207 / quest_daily L208-210 /
    main_progress 默认语义 L61 / 双板仲裁 L190-194）
  - M4 设计审查（审查_M4设计_批次4_jspace.md）：
    · P2-1：2b4「主线不占 accept_limit 亦可配」未登记 → 按契约默认**主线计入行数**（F-2 并发行数
      含主线；不引入主线豁免，语义闭合）。
    · P3-2：quest_daily「今日接取数」被记录但无规则消费 → 本引擎照常记录（定稿 L208-210 三字段），
      防刷闸 = F-2 并发行数（quest_active 行数）；接取数仅供面板/遥测，不另设「每日接取上限」。

【工程补白 · 显式标注】（契约/定稿未显式定义处，按「只建议不限制」取点定型，命名可改）：
  1) 引擎零 IO、零 NoneBot import、纯函数（ctx dict 进出，就地改写可变子结构）；SQLite 事务由
     调用方存储层负责（D-04），本模块以「快照-回滚」保证单次调用无中间态（进程内兜底；跨进程/并发
     由调用方事务 + 条件式 UPDATE 兜底，对齐 shop.py 工程补白 8）。
  2) 状态落点（ctx 就地改写，持久化由调用方完成）：
       ctx["quests"]            quest 定义注册表 {id: quest} 或 ctx["resolve_quest"] 解析器 +
                                ctx["quest_ids"]（resolve 通道缺省 id 列表）
       ctx["quest_active"]      进行中任务表 {quest_id: {"name": str}}（ID+名称冗余，3.18 快照
                                原则；Mapping 形态兼容 condition_engine has_quest 键成员判定）
       ctx["quest_completed"]   已完成任务 id 集合（list/set；非 repeatable 不可再接）
       ctx["quest_daily"]       每日防刷表 {"key": "YYYY-MM-DD", "completed": int,
                                "accepted": int, "decay": {quest_id: 完成次数}}（懒计算重置）
       ctx["longline_counters"] 框架级长线计数（任务只读；main_progress 由本引擎递增）
       ctx["event_counts"]      事件触发计数表（事件型条件读取）
       ctx["inventory"]         in-memory 背包 {item_id: count}（可缺省，走 remove_item/count_item hook）
       ctx["currencies"]/["exp"]/["reputation_state"]  reward 发放桶（dispatch_reward 就地入账）
  3) 防刷限额层级（2b4 §1.3 L106「板级为全局默认、quest 级继承」）：settings.quest_accept_limit /
     settings.quest_daily_limit 为内容包全局覆盖（优先）；否则取所操作 quest 自身 board.accept_limit /
     board.daily_limit；再缺省 5 / 10。quest_daily 为单玩家全局当日计数（D-04 ④ 无条件 +1）。
  4) 主线语义（P2-1 修正口径）：main:true 任务照常接取（计入 accept_limit 行数）、照常结算
     （reward + main_progress 累计 + quest_daily.completed +1 + 移出 quest_active），唯一区别是
     **任务板置顶常驻**（完成亦显示、不随刷新移除）；完成即移出 active 后按 repeatable 规则决定可否
     再接（默认非 repeatable → 已登记 quest_completed 不可再接，防无限领主线奖励）。副本子任务
     （zone 限定「完成仅推进进度不移除本体」）为内容包扩展模型，本批次不实现子任务推进（见 6）。
  5) consume=true 扣物口径：从 conditions 中 var=item_count（含中文别名 [背包:X] 归一）的条目推导
     应扣物品 {param: value}，交付时先校验够数再扣物出包（remove_item hook / inventory 兜底）；
     consume=true 但无 item_count 条件 → 无物可扣（仅领奖），显式标注供内容包自查。
  6) 未实现/延后（零分支占位，不新增判定）：timed.penalty（放弃/超时惩罚，可配默认无，只透传配置）、
     filter（交付品质过滤，炼金委托板用）、bonus（条件倍率）、zone 副本子任务推进、npc 差异化发任务
     （候选命中求值由 quest_available 承接，实际发布走 NPC 侧）；委托板（profession quest_board）
     为独立板，裸 /任务 /接取 /交付 归本引擎（玩家任务板），委托板指令带板前缀（§5.4 双板仲裁，
     本批次只服务玩家任务板）。
  7) 三原语进度读取（quest_progress 展示用 current）：本模块自实现 _read_current/_read_counter，
     镜像 condition_engine._resolve_var/_read_counter 的读取语义（值型当前值 / 累计型 longline_
     counters / 事件型 event_counts）；**满足判定唯一权威 = condition_engine.eval_condition**
     （quest_available），进度 current 仅供面板展示，不参与判定。
  8) 发放器唯一实现 = core/reward.dispatch_reward（A1）：逐条目失败黄字跳过不中断整批（P1-2）；
     仅 batch 级失败（ctx 非法 / reward 形态非法）触发整单回滚。幂等：ctx["tx_id"]+ctx["ledger"]
     （A1 模式），同 tx 重复调用 → idempotent，不二次发放。M4 实现审查批次1 P1-1：物品入包失败
     （无 add_item hook / hook 返回 False）在 reward 层为条目级 skip(item_add_failed)，本引擎结算后
     判定"物品未入包"→ 整单回滚 + 不封口幂等（黄字提示，可重试），防静默丢奖。
  9) 重复衰减（F-4 / TC-23）：repeatable=true 无衰减；repeatable={decay,cap} 第 n 次奖励 ×decay^n
     至 cap 下限（标量数值 int 向下取整、物品数量 floor 至 ≥1）；完成次数记 quest_daily.decay。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；now/rng 注入确定性；工程补白显式标注；
文件头标注依据；不 git commit。
"""

from __future__ import annotations

import copy
from typing import Any, List, Mapping, MutableMapping, MutableSet, Optional

from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.reward import dispatch_reward, normalize_reward
from qbot_rpg.engine.condition_engine import (
    normalize_op,
    normalize_var,
    eval_condition,
)

__all__ = [
    "DEFAULT_ACCEPT_LIMIT",
    "DEFAULT_DAILY_LIMIT",
    "DEFAULT_BOARD",
    "BOARD_SLOTS",
    "resolve_quest",
    "quest_exists",
    "quest_conditions_met",
    "quest_available",
    "quest_daily_state",
    "quest_daily_reset",
    "quest_accept",
    "quest_progress",
    "quest_complete",
    "quest_abandon",
    "quest_board",
    "resolve_board_index",
]

# -------------------------------------------------------------------------------------
# 常量（2b4 §1.2/§1.3 默认值兜底 D-07 / 定稿 L183-184 / quest_models 占位壳常量对齐）
# -------------------------------------------------------------------------------------
DEFAULT_ACCEPT_LIMIT: int = 5   # 同时接取上限（F-2，默认 ≤5，0=不限）
DEFAULT_DAILY_LIMIT: int = 10   # 每日完成上限（F-1，默认 ≤10，0=不限）

# 默认板（2b4 §1.3 L105 D-07：漏配 board = 每日默认板）
DEFAULT_BOARD: dict = {
    "slot": "daily",
    "refresh": "daily",
    "limit": 0,
    "accept_limit": DEFAULT_ACCEPT_LIMIT,
    "daily_limit": DEFAULT_DAILY_LIMIT,
}

BOARD_SLOTS: tuple = ("daily", "weekly", "event")

# 事件型 var 固定前缀（2b4 §2.2 ③）
_EVENT_PREFIX = "[事件:"

# 快照-回滚覆盖的可变 ctx 子结构（工程补白 1）
_SNAP_KEYS: tuple = (
    "currencies", "exp", "reputation_state", "quest_active", "quest_completed",
    "quest_daily", "longline_counters", "inventory",
)


# -------------------------------------------------------------------------------------
# 基础工具（纯函数，对齐 shop.py 口径）
# -------------------------------------------------------------------------------------
def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _to_int(value: object, default: int = 0) -> int:
    """容错整型化（面板/计数展示用）：非法 → default。"""
    if isinstance(value, (int, str, bytes, float)) and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _num(x: object) -> Optional[float]:
    """数值化（对齐 condition_engine._num）：int/float 直通；数字串转数值；bool 不算。"""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, str):
        try:
            return float(x)
        except (ValueError, TypeError):
            return None
    return None


def _settings(ctx: Mapping[str, Any]) -> Mapping:
    settings = ctx.get("settings")
    return settings if isinstance(settings, Mapping) else {}


def _now(ctx: Mapping[str, Any]) -> Optional[int]:
    """UTC+8 秒级时间戳：ctx["now"] 注入优先（确定性可测）；缺省 None → dayroll 取当前。"""
    now = ctx.get("now")
    return int(now) if now is not None else None


def _cfg(ctx: Mapping[str, Any]) -> Mapping:
    """dayroll 配置：统一配置键 refresh_time（默认 05:00，与签到/商店同刻对齐）。"""
    return _settings(ctx)


# -------------------------------------------------------------------------------------
# quest 定义解析（对齐 shop.resolve_shop）
# -------------------------------------------------------------------------------------
def resolve_quest(ctx: Mapping[str, Any], quest_id: object) -> Optional[Mapping]:
    """quest 定义解析：ctx["quests"] dict（id→quest）或 ctx["resolve_quest"] 解析器；查无 → None。"""
    if not isinstance(quest_id, str):
        return None
    quests = ctx.get("quests")
    if isinstance(quests, Mapping):
        hit = quests.get(quest_id)
        if isinstance(hit, Mapping):
            return hit
    resolver = ctx.get("resolve_quest")
    if callable(resolver):
        try:
            hit = resolver(quest_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


def quest_exists(ctx: Mapping[str, Any], quest_id: object) -> bool:
    return resolve_quest(ctx, quest_id) is not None


def _all_quest_ids(ctx: Mapping[str, Any]) -> List[str]:
    """全表 quest id（稳定序：dict 顺序或 resolve_quest 缺省 quest_ids 列表）。"""
    quests = ctx.get("quests")
    if isinstance(quests, Mapping):
        return [qid for qid in quests if isinstance(qid, str)]
    resolver = ctx.get("resolve_quest")
    if callable(resolver):
        ids = ctx.get("quest_ids")
        if isinstance(ids, (list, tuple)):
            return [qid for qid in ids if isinstance(qid, str)]
    return []


def _quest_name(quest: Mapping) -> str:
    name = quest.get("name")
    return name if isinstance(name, str) and name else str(quest.get("id", ""))


# -------------------------------------------------------------------------------------
# 板配置归一 / 防刷限额（2b4 §1.3 默认值兜底 + 层级 L106）
# -------------------------------------------------------------------------------------
def _board(quest: Mapping) -> Mapping:
    board = quest.get("board")
    if isinstance(board, Mapping):
        return board
    return DEFAULT_BOARD


def _accept_limit(ctx: Mapping[str, Any], quest: Mapping) -> int:
    """同时接取上限（F-2）：settings.quest_accept_limit 全局覆盖 → quest.board.accept_limit → 5。"""
    g = _as_int(_settings(ctx).get("quest_accept_limit"))
    if g is not None:
        return max(0, g)
    v = _as_int(_board(quest).get("accept_limit"))
    return max(0, v) if v is not None else DEFAULT_ACCEPT_LIMIT


def _daily_limit(ctx: Mapping[str, Any], quest: Mapping) -> int:
    """每日完成上限（F-1）：settings.quest_daily_limit 全局覆盖 → quest.board.daily_limit → 10。"""
    g = _as_int(_settings(ctx).get("quest_daily_limit"))
    if g is not None:
        return max(0, g)
    v = _as_int(_board(quest).get("daily_limit"))
    return max(0, v) if v is not None else DEFAULT_DAILY_LIMIT


def _board_slot(quest: Mapping) -> str:
    slot = _board(quest).get("slot")
    if isinstance(slot, str) and slot in BOARD_SLOTS:
        return slot
    return "daily"


# -------------------------------------------------------------------------------------
# quest_active / quest_completed / quest_daily 存取
# -------------------------------------------------------------------------------------
def _active_map(ctx: Mapping[str, Any]) -> Mapping:
    raw = ctx.get("quest_active")
    return raw if isinstance(raw, Mapping) else {}


def _active_node(ctx: MutableMapping[str, Any]) -> MutableMapping:
    """quest_active 可写节点：ctx["quest_active"] 存在且可写则返回之；否则新建挂回 ctx。"""
    raw = ctx.get("quest_active")
    if isinstance(raw, MutableMapping):
        return raw
    node: MutableMapping = {}
    ctx["quest_active"] = node
    return node


def _active_ids(ctx: Mapping[str, Any]) -> set:
    return set(_active_map(ctx).keys())


def _is_active(ctx: Mapping[str, Any], quest_id: str) -> bool:
    return quest_id in _active_ids(ctx)


def _completed_set(ctx: Mapping[str, Any]) -> set:
    raw = ctx.get("quest_completed")
    if isinstance(raw, (set, frozenset)):
        return set(raw)
    if isinstance(raw, (list, tuple)):
        return {str(x) for x in raw}
    return set()


def _is_completed(ctx: Mapping[str, Any], quest_id: str) -> bool:
    return quest_id in _completed_set(ctx)


def _repeatable_flag(quest: Mapping) -> object:
    """repeatable：False=完成即移出不可再接；True=可重复；Mapping{decay,cap}=重复衰减（F-4）。"""
    return quest.get("repeatable", False)


def _is_repeatable(quest: Mapping) -> bool:
    r = _repeatable_flag(quest)
    return r is True or isinstance(r, Mapping)


def _daily_node(ctx: MutableMapping[str, Any]) -> MutableMapping:
    """quest_daily 懒计算节点（F-5：每日 05:00 惰性补算重置，对齐 A3 today_of）。

    返回 ctx["quest_daily"]（确保存在且 key=今日）：跨期 → 完成数/接取数/衰减计数清零并更新 key。
    """
    raw = ctx.get("quest_daily")
    node = raw if isinstance(raw, MutableMapping) else {}
    t = today_of(node.get("key"), _now(ctx), _cfg(ctx))
    if node.get("key") != t["today"]:
        node.clear()
        node.update({"key": t["today"], "completed": 0, "accepted": 0, "decay": {}})
        ctx["quest_daily"] = node
    return node


def quest_daily_state(ctx: MutableMapping[str, Any]) -> dict:
    """quest_daily 当前态（含懒计算重置）：{ok, today, completed, accepted, decay, refreshed}。"""
    node = _daily_node(ctx)
    return {
        "ok": True,
        "today": node.get("key"),
        "completed": _to_int(node.get("completed")),
        "accepted": _to_int(node.get("accepted")),
        "decay": dict(node.get("decay") or {}),
        "refreshed": bool(ctx.get("quest_daily") is not None),
    }


def quest_daily_reset(ctx: MutableMapping[str, Any]) -> dict:
    """显式懒计算重置（跨天首个操作惰性补算，F-5 / TC-30）：等价 quest_daily_state 内部重置。"""
    return quest_daily_state(ctx)


# -------------------------------------------------------------------------------------
# 三原语条件求值（满足判定唯一权威 = condition_engine.eval_condition）
# -------------------------------------------------------------------------------------
def quest_conditions_met(quest_or_conditions: object, ctx: Mapping[str, Any]) -> bool:
    """三原语求值（候选/交付判定）：conditions 数组全与（D-02），全部为真 → True。

    - quest 定义（Mapping 带 "conditions"）或裸条件数组/单条件均可。
    - 数组为空 = 接取即完成（定稿 L98）。
    - 求值失败（未知 var / 事件未触发 / param 缺失）→ 默认不满足（D-03），不抛错。
    """
    if isinstance(quest_or_conditions, Mapping):
        conditions = quest_or_conditions.get("conditions")
    else:
        conditions = quest_or_conditions
    return eval_condition(conditions, ctx)


def quest_available(quest_or_conditions: object, ctx: Mapping[str, Any]) -> bool:
    """任务候选可用性求值 = quest_conditions_met（别名，供指令层/NPC 候选命中复用）。

    注：NPC 差异化发任务候选走 quest.npc.conditions（发任务条件，§1.4），本入口对裸条件数组
    直接求值，故两种场景共用同一入口。
    """
    return quest_conditions_met(quest_or_conditions, ctx)


# -------------------------------------------------------------------------------------
# 三原语进度读取（工程补白 7：展示用 current，判定权威仍为 eval_condition）
# -------------------------------------------------------------------------------------
def _read_counter(
    ctx: Mapping[str, Any], table_key: str, name: str, param: Optional[str]
) -> Optional[float]:
    """读计数器表（longline_counters / event_counts），镜像 condition_engine._read_counter：
    nested {name: {param: count}} / flat {f"{name}:{param}": count} 两形态；缺表 → 0。"""
    table = ctx.get(table_key)
    if not isinstance(table, Mapping):
        return 0.0
    sub = table.get(name)
    if isinstance(sub, Mapping):
        if param is None:
            return 0.0
        v = sub.get(param, 0)
        return v if isinstance(v, (int, float)) else 0.0
    if sub is not None:
        if param is None:
            return sub if isinstance(sub, (int, float)) else 0.0
        return 0.0
    if param is not None:
        v = table.get(f"{name}:{param}")
        return v if isinstance(v, (int, float)) else 0.0
    return 0.0


def _read_current(ctx: Mapping[str, Any], var: str, param: Optional[str]) -> object:
    """三原语当前值（进度展示）：值型当前值 / 累计型 longline_counters / 事件型 event_counts。
    读取失败（缺表/param 缺失）→ None（面板不显示，判定仍走 eval_condition）。"""
    if var == "level":
        return _num(ctx.get("level"))
    if var == "item_count":
        if param is None:
            return None
        inv = ctx.get("inventory")
        if not isinstance(inv, Mapping):
            return None
        return _num(inv.get(param, 0))
    if var == "codex":
        return _num(ctx.get("codex"))
    if var == "prof_level":
        pl = ctx.get("prof_level")
        if isinstance(pl, Mapping):
            return _num(pl.get(param or "", 0))
        return _num(pl)
    if var in ("gain_count", "kill_count", "dungeon_clear", "main_progress"):
        return _read_counter(ctx, "longline_counters", var, param)
    if var == "reputation":
        rep = ctx.get("reputation_state")
        if isinstance(rep, Mapping):
            return _num(rep.get(param or "global", 0))
        r = ctx.get("reputation")
        if isinstance(r, Mapping):
            return _num(r.get(param or "global", 0))
        return _num(r)
    if var.startswith(_EVENT_PREFIX):
        return _read_counter(ctx, "event_counts", var, param)
    return None


def _normalized_condition(cond: Mapping) -> dict:
    """条件归一（展示用）：var 中英互译 + 事件名内嵌目标提取 + op 归一。"""
    raw_var = cond.get("var")
    var, embedded = normalize_var(raw_var)
    out = {
        "var": raw_var,
        "op": cond.get("op"),
        "value": cond.get("value"),
        "param": cond.get("param"),
    }
    if var is None:
        return out
    param = cond.get("param")
    if param is None and embedded is not None:
        param = embedded
    if var.startswith(_EVENT_PREFIX):
        inner = var[len(_EVENT_PREFIX):]
        if inner.endswith("]"):
            inner = inner[:-1]
        if ":" in inner:
            name, target = inner.rsplit(":", 1)
            if name and target:
                var, param = "[事件:" + name + "]", target
    out["var_norm"] = var
    out["param"] = param
    out["op_norm"] = normalize_op(cond.get("op"))
    return out


# -------------------------------------------------------------------------------------
# 任务板（主线置顶 + 板槽任务 + NPC 支线，双板仲裁 §5.4）
# -------------------------------------------------------------------------------------
_SECTION_TITLES: dict = {
    "active": "进行中",
    "main": "主线（常驻）",
    "daily": "每日板上任务",
    "weekly": "每周板上任务",
    "event": "活动板上任务",
    "npc": "NPC 支线",
}


def _row_progress(quest: Mapping, ctx: Mapping[str, Any]) -> dict:
    """单任务进度摘要：逐条件 current/target/met + 总 met（供 /任务 列表与 /任务信息 渲染）。"""
    conds = quest.get("conditions")
    if not isinstance(conds, list):
        conds = []
    items = []
    for c in conds:
        if not isinstance(c, Mapping):
            continue
        n = _normalized_condition(c)
        var = n.get("var_norm")
        current = _read_current(ctx, var, n.get("param")) if var else None
        items.append({
            "var": n.get("var_norm") or n.get("var"),
            "op": n.get("op_norm") or n.get("op"),
            "param": n.get("param"),
            "target": n.get("value"),
            "current": current,
            "met": eval_condition(c, ctx),
        })
    return {"met": quest_conditions_met(quest, ctx), "conditions": items}


def _board_row(quest: Mapping, index: int, section: str, ctx: Mapping[str, Any]) -> dict:
    qid = quest["id"]
    active = _is_active(ctx, qid)
    completed = _is_completed(ctx, qid)
    prog = _row_progress(quest, ctx)
    return {
        "index": index,
        "quest_id": qid,
        "name": _quest_name(quest),
        "type": quest.get("type", "collect"),
        "main": quest.get("main") is True,
        "active": active,
        "completed": completed,
        "repeatable": _is_repeatable(quest),
        "marked": active and quest.get("main") is not True,  # 主线置顶不标 *（2b4 §5.2 L285）
        "met": prog["met"],
        "progress": prog["conditions"],
        "section": section,
    }


def _npc_condition_hit(quest: Mapping, ctx: Mapping[str, Any]) -> bool:
    """NPC 支线候选命中：quest.npc.conditions（发任务条件，§1.4）；缺省 = 常驻可发。"""
    npc = quest.get("npc")
    conds = npc.get("conditions") if isinstance(npc, Mapping) else None
    if conds is None:
        return True
    return eval_condition(conds, ctx)


def _is_acceptable(quest: Mapping, ctx: Mapping[str, Any]) -> bool:
    """可接取判定（2026-09-05 任务板过滤：只显示能接的任务）。

    对齐 quest_accept 校验链（除 accept_limit 数量闸——那是全局行数上限，
    非任务自身属性，接取时引擎会拦；板上仍显示可接任务）：
      ① 非进行中（active）
      ② 非已完成（非 repeatable 已完成的不可再接）
      ③ unlock_chain 前置已完成（未完成 → 隐藏，链上任务现在接不了）
      ④ NPC 发任务条件命中（quest.npc.conditions 求值；缺省常驻可发）
    """
    qid = quest["id"]
    if _is_active(ctx, qid):
        return False
    if not _is_repeatable(quest) and _is_completed(ctx, qid):
        return False
    chain = quest.get("unlock_chain")
    if chain is not None and not _is_completed(ctx, str(chain)):
        return False
    return _npc_condition_hit(quest, ctx)


def quest_board(ctx: Mapping[str, Any]) -> dict:
    """/任务：玩家任务板 = 进行中（置顶）+ 可接取（主线/板槽/NPC 支线）。

    2026-09-05 用户拍板（任务板只显示可接取）：原「主线常驻置顶（完成亦显示）」
    语义废弃——已完成/进行中/未解锁的任务全部隐藏，仅显示两类：
      ① 进行中区（置顶）：quest_active 全部任务（带进度，marked 标记 *），
         玩家在此看进度/交付/放弃（序号即板序号）；
      ② 可接取区：_is_acceptable 过滤后的任务（非 active、非已完成非
         repeatable、unlock_chain 前置完成、NPC 条件命中），按 main/daily/
         weekly/event/npc 分组（工程补白 6 分组规则保留）。
    每行带全局展示序号 index（接取/交付/信息/放弃 N 即此序号，跨区连续编号）。
    分组规则（工程补白 6）：main:true → 主线；zone 限定（副本子任务）不占板槽 → 不显示。
    """
    active_rows: List[tuple] = []
    main_rows: List[tuple] = []
    slot_rows: dict = {s: [] for s in BOARD_SLOTS}
    npc_rows: List[tuple] = []
    for qid in _all_quest_ids(ctx):
        quest = resolve_quest(ctx, qid)
        if quest is None:
            continue
        # 进行中任务优先可见（2026-09-05 审计修复 B 路 P2：zone-skip 原先于
        # _is_active——副本子任务若已进 quest_active（扩展路径/NPC 直发）会被
        # zone-skip 拦掉、板上不可达 → 无法交付/放弃。active 检查前置：已接取的
        # zone 任务显示在「进行中」区供操作）。
        if _is_active(ctx, qid):
            active_rows.append((quest, "active"))  # 进行中置顶区
            continue
        # 副本子任务（zone 限定且非 main）不占板槽 → 不显示（任务定稿 L104/L251）。
        # 2026-09-05 用户拍板「引导保留」：main 引导任务即使带 zone 也上板——
        # zone 兼作区域标签的引导主线（veinborn 引导链）不被误判为副本子任务。
        if quest.get("zone") is not None and quest.get("main") is not True:
            continue
        if quest.get("main") is True:
            main_rows.append((quest, "main"))
            continue
        if quest.get("npc") is not None:
            npc_rows.append((quest, "npc"))
            continue
        slot_rows[_board_slot(quest)].append((quest, _board_slot(quest)))

    sections: List[dict] = []
    index = 0
    # 2026-09-05：active 任务 → 置顶「进行中」区（全部可见，供交付/放弃/进度）；
    # 可接取区只放 _is_acceptable 过滤后的行（未解锁/已完成/非命中 → 隐藏）
    for title_key, rows in (
        ("active", active_rows),
        ("main", main_rows),
        ("daily", slot_rows["daily"]),
        ("weekly", slot_rows["weekly"]),
        ("event", slot_rows["event"]),
        ("npc", npc_rows),
    ):
        if not rows:
            continue
        if title_key != "active":
            rows = [(q, s) for q, s in rows if _is_acceptable(q, ctx)]
            if not rows:
                continue
        built = []
        for quest, section in rows:
            index += 1
            built.append(_board_row(quest, index, section, ctx))
        sections.append({"title": _SECTION_TITLES[title_key], "slot": title_key, "rows": built})

    total = index
    # 满员标志（2026-09-05 审计 B 路 P2 + V1 修正）：accept_limit 满时板面提示腾位。
    # 判定对齐 quest_accept 逐任务限额：对每个可接取候选行判 len(active) >= 其
    # 自身 accept_limit → 该行接不了；所有可接候选都接不了才置 active_full
    # （异 limit 场景不误报：A limit=1、B/C limit=5、active=[A,B] 时 C 仍可接）。
    # 无 settings 全局覆盖时 accept_limit 取 quest.board 或默认 5（D-07）。
    active_full = False
    if active_rows:
        # 可接候选（_is_acceptable 过滤后）；无任何候选 → 非满员（「暂无新任务」场景，
        # 2026-09-05 模拟器审计：链锁/完成全锁时误报满员——满员=有候选但都超限）
        _cands = [(_q, _s) for _q, _s in main_rows + slot_rows["daily"]
                  + slot_rows["weekly"] + slot_rows["event"] + npc_rows
                  if _is_acceptable(_q, ctx)]
        if _cands:
            all_blocked = True
            for _q, _s in _cands:
                lim = _accept_limit(ctx, _q)
                if lim <= 0 or len(active_rows) < lim:
                    all_blocked = False
                    break
            active_full = all_blocked
    return {
        "ok": True,
        "sections": sections,
        "total": total,
        "active_full": active_full,
        "tip": "请发送 /接取 <序号> 接取任务（* 为已接取）",
    }


def resolve_board_index(ctx: Mapping[str, Any], ref: object) -> Optional[str]:
    """列表展示序号 → quest_id（/接取 N /交付 N 命中；序号带 `*` 为已接取不计可接序号）。
    返回 None = 序号越界/非法。"""
    n = _as_int(ref)
    if n is None or n <= 0:
        return None
    board = quest_board(ctx)
    seen = 0
    for section in board["sections"]:
        for row in section["rows"]:
            seen += 1
            if seen == n:
                return row["quest_id"]
    return None


# -------------------------------------------------------------------------------------
# 接取（F-2 同时接取上限 + 状态闸 + unlock_chain）
# -------------------------------------------------------------------------------------
def quest_accept(quest_id: str, ctx: MutableMapping[str, Any]) -> dict:
    """/接取 N：校验链（①存在→②非进行中→③非已完成→④unlock_chain→⑤accept_limit）成功入 active。

    成功：quest_active[quest_id] = {"name"}（ID+名称冗余）；quest_daily.accepted +1（懒计算重置，
    P3-2 口径：记录供面板，防刷闸=并发行数）。
    失败 {ok:False, reason, message, detail?}；成功 {ok, message, quest_id, name,
    active_count, accept_limit}。
    """
    quest = resolve_quest(ctx, quest_id)
    if quest is None:
        return {"ok": False, "reason": "no_quest", "message": "❌ 任务不存在"}

    if _is_active(ctx, quest_id):
        return {"ok": False, "reason": "already_active", "message": "❌ 该任务已在进行中"}

    if not _is_repeatable(quest) and _is_completed(ctx, quest_id):
        return {"ok": False, "reason": "already_completed", "message": "❌ 任务已完成"}

    chain = quest.get("unlock_chain")
    if chain is not None and not _is_completed(ctx, str(chain)):
        return {"ok": False, "reason": "chain_locked",
                "message": f"❌ 前置任务未完成（{chain}）",
                "detail": {"unlock_chain": chain}}

    limit = _accept_limit(ctx, quest)
    active = _active_node(ctx)
    if limit > 0 and len(active) >= limit:
        return {"ok": False, "reason": "accept_limit",
                "message": f"❌ 同时最多进行 {limit} 个任务（当前 {len(active)}）",
                "detail": {"limit": limit, "current": len(active)}}

    # 应用（accept 阶段无跨结构原子需求；active + daily 计数同一 ctx 就地完成）
    name = _quest_name(quest)
    node = _daily_node(ctx)
    node["accepted"] = _to_int(node.get("accepted")) + 1
    active[quest_id] = {"name": name}
    return {
        "ok": True,
        "message": f"✅ 已接取：{name}（同时进行 {len(active)}/{limit if limit > 0 else '∞'}）",
        "quest_id": quest_id,
        "name": name,
        "active_count": len(active),
        "accept_limit": limit,
    }


# -------------------------------------------------------------------------------------
# 进度查询 / 交付判定（/任务信息）
# -------------------------------------------------------------------------------------
def quest_progress(quest_id: str, ctx: Mapping[str, Any]) -> dict:
    """/任务信息：三原语进度逐条显示 + 交付判定（met=全真可交付）。

    返回 {ok, quest_id, name, met, consume, required_items, conditions:[{var,op,param,
    target,current,met}], [progress]}; 失败 {ok:False, reason}。
    """
    quest = resolve_quest(ctx, quest_id)
    if quest is None:
        return {"ok": False, "reason": "no_quest", "message": "❌ 任务不存在"}
    prog = _row_progress(quest, ctx)
    return {
        "ok": True,
        "quest_id": quest_id,
        "name": _quest_name(quest),
        "met": prog["met"],
        "consume": quest.get("consume") is True,
        "required_items": _consume_requirements(quest, ctx),
        "conditions": prog["conditions"],
        "active": _is_active(ctx, quest_id),
    }


def _consume_requirements(quest: Mapping, ctx: Mapping[str, Any]) -> dict:
    """consume=true 应扣物品推导（工程补白 5）：conditions 中 var=item_count 的 {param: value} 求和。"""
    req: dict = {}
    if quest.get("consume") is not True:
        return req
    conds = quest.get("conditions")
    if not isinstance(conds, list):
        return req
    for c in conds:
        if not isinstance(c, Mapping):
            continue
        var, embedded = normalize_var(c.get("var"))
        if var != "item_count":
            continue
        param = c.get("param") or embedded
        value = _as_int(c.get("value"))
        if param is None or value is None or value <= 0:
            continue
        key = str(param)
        req[key] = req.get(key, 0) + value
    return req


# -------------------------------------------------------------------------------------
# 完成结算（D-04 单事务：reward + main_progress + 移出 + quest_daily；F-1 每日上限）
# -------------------------------------------------------------------------------------
def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


def _snapshot(ctx: Mapping[str, Any]) -> dict:
    return {k: copy.deepcopy(ctx.get(k)) for k in _SNAP_KEYS}


def _restore(ctx: MutableMapping[str, Any], snap: dict) -> None:
    for k, v in snap.items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v


class _Rollback(Exception):
    """结算阶段失败标记（进程内回滚触发；跨进程由调用方 SQLite 事务兜底，D-04）。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _decay_state(quest: Mapping, ctx: MutableMapping[str, Any]) -> tuple:
    """重复衰减（F-4 / TC-23）：返回 (multiplier, cap_amount, prior_completions)。

    repeatable=true → (1.0, 1, prior)；repeatable={decay,cap} → multiplier = decay^n（不封顶递减），
    cap = 奖励金额下限（「至 cap 下限」= 单条奖励不低于 cap，工程补白 9），n = 已完次数；
    否则 → (1.0, 1, 0)。

    2026-09-05 审计 B 路 P5：bool 分支 prior 恒 0 → decay 遥测覆盖写 1（完成 N 次仍显 1）。
    现统一读 daily.decay[id] 真实累计（与 Mapping 分支同口径；倍率仍恒 1.0 不变）。
    """
    r = _repeatable_flag(quest)
    if not isinstance(r, Mapping):
        prior = 0
        if isinstance(ctx, MutableMapping):
            daily = ctx.get("quest_daily")
            if isinstance(daily, MutableMapping):
                dec = daily.get("decay")
                if isinstance(dec, MutableMapping):
                    prior = _to_int(dec.get(quest.get("id")))
        return 1.0, 1, prior
    decay = r.get("decay", 0.5)
    cap = r.get("cap", 1)
    try:
        decay = float(decay)
    except (TypeError, ValueError):
        decay = 0.5
    cap_i = _to_int(cap, default=1)
    cap_i = max(0, cap_i)
    if decay < 0:
        decay = 0.5
    node = _daily_node(ctx)  # 需可写（内部清零惰性）；此处只读计数
    n = _to_int((node.get("decay") or {}).get(quest["id"]))
    mult = decay ** n
    return mult, cap_i, n


def _scale_reward(entries: List[dict], mult: float, cap: int) -> List[dict]:
    """衰减缩放（工程补白 9）：标量数值/物品数量 int 向下取整，单条金额不低于 cap（奖励下限）。"""
    if mult == 1.0:
        return entries
    out: List[dict] = []
    for e in entries:
        e = dict(e)
        if "item" in e or "id" in e:
            e["count"] = max(cap, int(e.get("count", 1) * mult))
        else:
            for k, v in list(e.items()):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    e[k] = max(cap, int(v * mult))
        out.append(e)
    return out


def _idempotent_hit(ctx: Mapping[str, Any]) -> bool:
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    return bool(
        tx_id is not None
        and isinstance(ledger, MutableSet)
        and tx_id in ledger
    )


def _mark_idempotent(ctx: MutableMapping[str, Any]) -> None:
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None and isinstance(ledger, MutableSet):
        ledger.add(tx_id)


def _item_reward_failed(rw: Mapping[str, Any]) -> bool:
    """P1-1 判定：物品奖励是否未实际入包。

    - rw["skipped"] 中 type==item 且 reason==item_add_failed（hook 缺失 / 返回 False / 抛错）；
    - rw["granted"] 中 type==item 且 applied is False（防御：历史/未来路径残留的伪 granted）。

    命中 → 该物品奖励未入包，须整单回滚 + 不封口幂等（可重试），防静默丢奖。
    """
    for s in rw.get("skipped") or []:
        if (isinstance(s, Mapping) and s.get("type") == "item"
                and s.get("reason") == "item_add_failed"):
            return True
    for g in rw.get("granted") or []:
        if isinstance(g, Mapping) and g.get("type") == "item" and g.get("applied") is False:
            return True
    return False


def quest_complete(quest_id: str, ctx: MutableMapping[str, Any]) -> dict:
    """/交付 N：完成结算（D-04 单事务语义）。

    校验链：①存在 → ②进行中（quest_active 含该任务）→ ③条件全真（三原语交付判定）→
    ④每日完成上限 F-1（daily_limit≤10，0=不限）→ ⑤consume=true 背包够数。
    结算（快照-回滚，单事务）：①reward 发放（dispatch_reward，逐条目失败黄字跳过 P1-2，batch 失败
    回滚；物品未入包 item_add_failed → 整单回滚，P1-1）→ ②main_progress +1（若 main:true）→
    ③移出 quest_active（完成即移出）→ ④quest_daily.completed +1 / 衰减计数更新 →
    ⑤quest_completed 登记（非 repeatable）。
    幂等：同 tx_id 重复调用 → idempotent，不二次发放；物品未入包回滚时**不封口幂等**（可重试，P1-1）。
    """
    if _idempotent_hit(ctx):
        return {"ok": True, "idempotent": True,
                "message": "✅ 已结算（重复指令，未重复发放）", "quest_id": quest_id}

    quest = resolve_quest(ctx, quest_id)
    if quest is None:
        return {"ok": False, "reason": "no_quest", "message": "❌ 任务不存在"}

    if not _is_active(ctx, quest_id):
        return {"ok": False, "reason": "not_active",
                "message": "❌ 该任务未在进行中（请先 /接取）"}

    if not quest_conditions_met(quest, ctx):
        prog = _row_progress(quest, ctx)
        return {"ok": False, "reason": "not_met", "message": "❌ 任务条件未达成，暂不能交付",
                "detail": {"met": False, "conditions": prog["conditions"]}}

    daily = _daily_node(ctx)
    limit = _daily_limit(ctx, quest)
    completed_today = _to_int(daily.get("completed"))
    if limit > 0 and completed_today >= limit:
        return {"ok": False, "reason": "daily_limit",
                "message": f"❌ 今日任务已完成 {completed_today}/{limit}，明早 5 点刷新",
                "detail": {"limit": limit, "completed": completed_today}}

    req = _consume_requirements(quest, ctx)
    if req:
        for item_id, need in req.items():
            have = _count_item(ctx, item_id)
            if have < need:
                return {"ok": False, "reason": "insufficient_items",
                        "message": f"❌ 背包里 {item_id} 只有 {have} 个（需要 {need}）",
                        "detail": {"item": item_id, "have": have, "need": need}}

    # ---- 原子结算（单事务语义：快照 → 应用 → 失败回滚）----
    name = _quest_name(quest)
    mult, cap_amt, prior = _decay_state(quest, ctx)
    snap = _snapshot(ctx)
    try:
        # ① consume 扣物（交付扣物出包，工程补白 5）
        if req:
            for item_id, need in req.items():
                if not _remove_item(ctx, item_id, need):
                    raise _Rollback("item_remove_failed")
        # ① reward 发放（dispatch_reward；batch 级失败回滚，条目级失败跳过 P1-2）
        entries = normalize_reward(quest.get("reward", ""))
        rw = dispatch_reward(_scale_reward(entries, mult, cap_amt), ctx)
        if not rw["ok"]:
            raise _Rollback("reward_failed")
        # M4 实现审查批次1 P1-1：物品奖励未实际入包（无 add_item hook / hook 失败）→
        # 整单回滚 + 不封口幂等（黄字提示"物品未入包"，可重试），防静默丢奖
        if _item_reward_failed(rw):
            raise _Rollback("item_add_failed")
        # ② main_progress 累计（主线 done 计数，落 longline_counters，定稿 L61）
        if quest.get("main") is True:
            llc = ctx.setdefault("longline_counters", {})
            if isinstance(llc, MutableMapping):
                llc["main_progress"] = _to_int(llc.get("main_progress")) + 1
        # ③ 完成即移出 quest_active
        active = ctx.get("quest_active")
        if isinstance(active, MutableMapping):
            active.pop(quest_id, None)
        # ④ quest_daily 完成数 +1 / 衰减计数更新（D-04）
        daily["completed"] = _to_int(daily.get("completed")) + 1
        if _is_repeatable(quest):
            decay = daily.setdefault("decay", {})
            decay[quest_id] = prior + 1
        # ⑤ quest_completed 登记（非 repeatable 不可再接）
        if not _is_repeatable(quest):
            completed = ctx.get("quest_completed")
            if isinstance(completed, MutableSet):
                completed.add(quest_id)
            elif isinstance(completed, list):
                if quest_id not in completed:
                    completed.append(quest_id)
    except _Rollback as exc:
        _restore(ctx, snap)
        if exc.reason == "item_add_failed":
            # P1-1：物品未入包 → 回滚已完成、不封口幂等（ledger 未写），黄字提示可重试
            return {"ok": False, "reason": "item_add_failed",
                    "message": "❌ 物品未入包（奖励未发放，可重试）",
                    "quest_id": quest_id, "retryable": True}
        return {"ok": False, "reason": exc.reason, "message": "❌ 结算失败，已回滚"}

    _mark_idempotent(ctx)
    # M7 N-03 + 3f R-02：任务完成事件写入（RN-10 三表）+ story_node 剧情节点冒险日志。
    # 复用 N-03 预置键 [事件:任务完成] flat（条件引擎读取源 + test_event_bus 平铺断言
    # 不变）；节点信息（quest_id/名称）入 params 供 /日志 渲染。
    try:
        from qbot_rpg.core.adventure_log import log_story_node
        log_story_node(ctx, quest_id, name=name)
    except Exception:
        pass

    completed_today = _to_int(daily.get("completed"))
    mp = 0
    llc = ctx.get("longline_counters")
    if isinstance(llc, Mapping):
        mp = _to_int(llc.get("main_progress"))
    msg = f"✅ 交付完成：{name}"
    if rw["granted"]:
        msg += "（+" + " / ".join(
            _grant_label(g, ctx) for g in rw["granted"][:4]
        ) + "）"
    msg += f"，今日已完成 {completed_today}/{limit if limit > 0 else '∞'}"
    # 2026-09-05 审计 C 路 P2（引导链断点）+ V1 修正：完成后若解锁了新主线
    # （unlock_chain 指向本任务的下一个 main 任务且未完成）→ 消息追加引导。
    # V1 修正：repeatable 任务完成不登记 quest_completed → 后继实际仍 chain_locked
    # （内容校验 quest_models Y-4 已拦此配置，运行时再兜一层防误报话术）。
    next_name = None
    if not _is_repeatable(quest):
        try:
            for _qid2 in _all_quest_ids(ctx):
                _qd = resolve_quest(ctx, _qid2)
                if _qd is None:
                    continue
                if _qd.get("unlock_chain") == quest_id and _qd.get("main") is True \
                        and not _is_completed(ctx, _qid2):
                    next_name = _quest_name(_qd)
                    break
        except Exception:  # noqa: BLE001 —— 引导提示失败不阻断结算
            next_name = None
    if next_name:
        msg += f"\n新主线开放：{next_name}——发 任务 查看（板上领取）"
    return {
        "ok": True,
        "message": msg,
        "quest_id": quest_id,
        "name": name,
        "main": quest.get("main") is True,
        "main_progress": mp,
        "granted": rw["granted"],
        "skipped": rw["skipped"],
        "completed_today": completed_today,
        "daily_limit": limit,
        "decay_multiplier": mult,
        "idempotent": False,
    }


def _grant_label(grant: Mapping, ctx: Mapping[str, Any]) -> str:
    """grant 记录 → 简短展示标签（「铁矿×3」/「exp50」/「金币80」）。

    2026-09-05 显示修复：item 显示中文名（ctx["items"] 注册表含 items∪equipment，
    M12.5 同库语义；查不到 → id 兜底）。
    """
    typ = grant.get("type")
    if typ == "item":
        item_id = grant.get("item")
        nm = None
        try:
            _tbl = ctx.get("items")
            if isinstance(_tbl, Mapping):
                _d = _tbl.get(item_id)
                if isinstance(_d, Mapping) and _d.get("name"):
                    nm = str(_d.get("name"))
                elif _d is not None:
                    _n2 = getattr(_d, "name", None)
                    if _n2:
                        nm = str(_n2)
        except Exception:  # noqa: BLE001 —— 名称解析失败回落 id
            nm = None
        return f"{nm if nm else item_id}×{grant.get('count')}"
    if typ == "currency":
        return f"{_currency_name(ctx, grant.get('currency'))}×{grant.get('amount')}"
    if typ == "exp":
        return f"经验×{grant.get('amount')}"
    if typ == "rep":
        return f"声望×{grant.get('amount')}"
    if typ == "prof":
        return f"{_prof_name(ctx, grant.get('job'))}熟练×{grant.get('amount')}"
    return str(grant)


def _prof_name(ctx: Mapping[str, Any], job: object) -> str:
    """职业 id → 中文名（ctx.jobs 注册表；查无 → id 兜底）。"""
    key = str(job) if job is not None else ""
    if not key:
        return ""
    try:
        jobs = ctx.get("jobs")
        if isinstance(jobs, Mapping):
            jd = jobs.get(key)
            if isinstance(jd, Mapping) and jd.get("name"):
                return str(jd.get("name"))
        elif isinstance(jobs, list):
            for j in jobs:
                if isinstance(j, Mapping) and str(j.get("id") or "") == key:
                    nm = j.get("name")
                    if nm:
                        return str(nm)
    except Exception:  # noqa: BLE001
        pass
    return key


def _currency_name(ctx: Mapping[str, Any], cid: object) -> str:
    """货币 id → 配置中文名（2026-09-06 统一走 reward.currency_display_name）。"""
    from qbot_rpg.core.reward import currency_display_name  # noqa: PLC0415

    return currency_display_name(ctx, cid)


# -------------------------------------------------------------------------------------
# 放弃（TC-27：移除 active，默认无惩罚）
# -------------------------------------------------------------------------------------
def quest_abandon(quest_id: str, ctx: MutableMapping[str, Any]) -> dict:
    """/放弃 N：从 quest_active 移除；默认无惩罚（可配 timed.penalty 仅透传配置，工程补白 6）。"""
    quest = resolve_quest(ctx, quest_id)
    if quest is None:
        return {"ok": False, "reason": "no_quest", "message": "❌ 任务不存在"}
    if not _is_active(ctx, quest_id):
        return {"ok": False, "reason": "not_active", "message": "❌ 该任务未在进行中"}
    active = ctx.get("quest_active")
    name = _quest_name(quest)
    if isinstance(active, MutableMapping):
        active.pop(quest_id, None)
    timed = quest.get("timed")
    penalty = timed.get("penalty") if isinstance(timed, Mapping) else None
    msg = f"✅ 已放弃：{name}"
    if penalty:
        msg += "（惩罚：见配置）"
    return {"ok": True, "message": msg, "quest_id": quest_id, "name": name,
            "penalty": penalty}
