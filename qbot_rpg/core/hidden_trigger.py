"""隐藏要素引擎（qbot_rpg/core/hidden_trigger.py · M7 BCH-07 3f F-08~F-10 · R-12~R-16 · E-03）。

三类隐藏要素（纯配置、不提示原则【单机】L19）：隐藏 BOSS（R-12）/ 隐藏任务（R-13）/
彩蛋一次性揭示（R-14/R-15）。本模块产出触发判定与仪式感揭示原语，不注册任何
「列出全部隐藏要素」指令（R-15：/秘密 不注册，探索感保留）。

依据（真实签名已 read 核对）：
  - docs/细化/细化_3f_单机向体验.md：
    · R-12（3.2）：maps.json 怪物行 `window`（限定窗口条件键）+ enemies BOSS 档 +
      loot special。三触发模式 replace（窗口内替换普通怪物行）/ after（窗口内且前置
      事件/计数达成后追加，如 [事件:环境事件:雨夜]≥3）/ fixed（固定交互点/时刻蹲点
      必出）。条件键 [季节]+[时段]+[天气]+[图鉴完成度]（var:codex 已注册），零新增。
      保底与日限（L84）：条件满足蹲点 100% 必出（无随机）；3 次保底（连续满足条件
      未出战的窗口累计 ≥3 → 下次必触发）；日限 1 次（当日已触发 → 该日不再触发，
      按 server 自然日懒计算）。触发链路：环境事件 → [事件:环境事件:ID] 计数+1 →
      条件满足 → 一次性揭示 → BOSS 战 → 击败 → 图鉴补全 + [事件:隐藏发现:ID] +
      冒险日志（含环境快照）。
    · R-13（3.3 D-05/D-06）：隐藏任务 quest 不上任务板（不配置 board 即天然不上板）+
      quest.npc.conditions（图鉴/事件/物品/时段组合）数组全与（AND）才发；不满足 →
      普通对话分支零暗示。
    · R-15（3.5）：一次性揭示卡片（⛩️ 前缀，无 emoji 降级【发现】）+ 首见日志
      （adventure_log.log_hidden_find，first_seen）+ 图鉴 lore 补全。
  - docs/细化/细化_M7_交互补全总纲.md（F-08~F-10 模块 core/hidden_trigger.py；BCH-07）。
  - qbot_rpg/core/investigate.py（hunt 信号形态 {kind:"hunt", boss_ref, text,...} 复用；
    _condition_ctx 桥接 / _ps_of / _render_text 模式对齐）。
  - qbot_rpg/core/adventure_log.py（log_hidden_find(ctx, hidden_id) -> bump_event dict；
    EVENT_KEY_HIDDEN_FIND="[事件:隐藏发现]"）。
  - qbot_rpg/core/event_bus.py（bump_event 三表：event_counts nested target +
    longline_counters + event_log 环形 300）。
  - qbot_rpg/core/npc.py（available_quests/_action_quest 未消费 quest.npc.conditions——
    BCH-04 登记缺口，本模块提供 npc_quest_conditions_met 求值 helper，npc.py 的接线
    由兄弟路做）。
  - qbot_rpg/engine/condition_engine.py（eval_condition(cond, ctx)->bool fail-safe；
    事件型 [事件:环境事件:雨夜] → name=[事件:环境事件] + param=雨夜，读 event_counts
    嵌套；时间三键真实读取键 season_now/period_now/weather_now 或 worldtime 鸭子类型）。

【工程补白 · 显式标注】
  1) 三触发模式数据源（内容侧尚未落地，字段命名补白）：monsters[] 隐藏 BOSS 行 =
     {enemy, window(条件键,必填), mode?, after?, desc?, hidden_find_id?, title?}。
     mode 缺省 "replace"（非法值/非三值 → replace）；after 模式额外前置条件放
     `row["after"]`（统一条件引擎表达式；None=无额外前置，仅窗口即可）。
  2) 保底语义收敛（R-12 L84「累计 ≥3 → 下次必触发」字面实现）：保底计数
     persistent_state["hidden_boss_pity"] = {boss_ref: count}（只增不减，触发/出战后
     清零）。满足条件但被日限挡下的窗口（当日已触发 = 未出战窗口）+1；累计达 3 即
     「保底就绪」，下一次满足条件的窗口**无条件强制触发**（覆盖日限），随后清零。
     条件满足且当日未触发 → 100% 必出（无随机，reason="condition_met"）。
  3) 日限跟踪 persistent_state["hidden_boss_daily"] = {日期: {boss_ref: count}}——
     按 server 自然日懒计算（日期作键，旧日不挡新日，无需显式重置，对齐 2c1c R-02
     窗口纪律 / investigate 配额口径）；today 入参/ctx["today"] 注入，空串=不强制日限
     （确定性）。
  4) BOSS 战信号（R-12 触发链路）：本模块产出 signal（复用 investigate hunt 形态
     {kind:"hunt", boss_ref, text, mode, hidden_find_id}）；[事件:隐藏发现:ID] 计数 +
     首见日志在**击败后**经 reveal_find 结算（对齐触发链路「击败 → 图鉴条目补全 +
     [事件:隐藏发现:ID] 计数 + 冒险日志」，TC-16 击败后查日志见首见条目）。
  5) 图鉴 lore 补全（R-15）：codex_state 解锁传闻段依赖 2c1c codex 结构 / F-16 定向
     线索（BCH-09 ambient.py）未实装，本模块**不写 codex_state**（最小侵入防污染未知
     结构），只回 lore_pending=True 交接线层，写侧登记 F-16/BCH-09 承接。
  6) 一次性揭示卡片：⛩️ 前缀降级为【发现】（无 emoji 铁律）；重复发现 → 简短确认
     「这里没有新的发现。」（对齐 investigate DEFAULT_CONFIRM_TEXT，R-11 去重口径），
     不再计数/不再生成首见文案。标记 persistent_state["hidden_find_revealed"] = [id...]。
  7) 隐藏任务求值（R-13 D-05）：quest.npc.conditions 数组全与（eval_condition list =
     all）；缺省/空 = 恒可发（2b4 §1.4 conditions 默认 []）；不满足零暗示（helper 只
     回 bool，无提示文本）。候选去重复用三表（quest_active/quest_daily/quest_completed）。
     不提供任何「列出隐藏要素」指令（R-15 铁律）。

铁律：零 NoneBot import；纯函数确定性（today/rng 由 ctx 注入，无随机/时间外部依赖）；
每函数 docstring；无 emoji（【发现】替代 ⛩️）；最小侵入（不改兄弟路文件，npc.py 的
quest.npc.conditions 接线归兄弟路，本模块只提供 helper）。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

from qbot_rpg.core.adventure_log import EVENT_KEY_HIDDEN_FIND, log_hidden_find
from qbot_rpg.engine.condition_engine import eval_condition

__all__ = [
    "PITY_THRESHOLD",
    "BOSS_DAILY_KEY",
    "BOSS_PITY_KEY",
    "REVEALED_KEY",
    "DEFAULT_CONFIRM_TEXT",
    "HUNT_SIGNAL_KIND",
    "check_boss_spawn",
    "check_hidden_quest",
    "npc_quest_conditions_met",
    "reveal_find",
]

# -------------------------------------------------------------------------------------
# 常量（R-12 / 补白 2-6）
# -------------------------------------------------------------------------------------
# 3 次保底（R-12 L84：连续满足条件未出战的窗口累计 ≥3 → 下次必触发）
PITY_THRESHOLD = 3

# 日限跟踪落点：persistent_state["hidden_boss_daily"] = {日期: {boss_ref: count}}
BOSS_DAILY_KEY = "hidden_boss_daily"

# 保底计数落点：persistent_state["hidden_boss_pity"] = {boss_ref: count}
BOSS_PITY_KEY = "hidden_boss_pity"

# 一次性揭示标记落点：persistent_state["hidden_find_revealed"] = [id...]（补白 6）
REVEALED_KEY = "hidden_find_revealed"

# 重复发现简短确认（R-11 去重口径 / 补白 6；对齐 investigate DEFAULT_CONFIRM_TEXT）
DEFAULT_CONFIRM_TEXT = "这里没有新的发现。"

# 三触发模式白名单（R-12）
_BOSS_MODES: tuple = ("replace", "after", "fixed")

# BOSS 战信号形态（复用 investigate hunt 信号 kind，补白 4）
HUNT_SIGNAL_KIND = "hunt"


# -------------------------------------------------------------------------------------
# 内部小工具（纯函数，均带 docstring）
# -------------------------------------------------------------------------------------
def _ps_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
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


def _map_name(map_def: object) -> str:
    """地图名：def.name 或 raw name（兜底空串）。"""
    v = getattr(map_def, "name", None)
    if isinstance(v, str) and v:
        return v
    v = _raw_get(map_def, "name")
    return v if isinstance(v, str) else ""


def _condition_ctx(ctx: Mapping[str, Any]) -> dict:
    """统一条件引擎求值上下文（桥接，对齐 investigate 补白 8）：从 ctx["season"/"period"/
    "weather"] 派生 season_now/period_now/weather_now 直键（条件引擎时间三键真实读取键），
    其余键透传。"""
    out = dict(ctx)
    for src, dst in (("season", "season_now"), ("period", "period_now"),
                     ("weather", "weather_now")):
        v = ctx.get(src)
        if isinstance(v, str) and v:
            out[dst] = v
    return out


def _cond_ok(cond: object, ctx: Mapping[str, Any]) -> bool:
    """统一条件求值（R-12/R-13 / D-03）：None=恒可触发；求值失败/False = 不满足（不抛错）。"""
    if cond is None:
        return True
    try:
        return bool(eval_condition(cond, _condition_ctx(ctx)))
    except Exception:
        return False


def _render_text(template: Optional[str], ctx: Mapping[str, Any], map_def: object) -> str:
    """模板占位符渲染（R-12 演出文本，3d 模板规范子集）：{季节}/{时段}/{天气}/{地图} 注入。"""
    if not isinstance(template, str) or not template:
        return ""
    return (
        template
        .replace("{季节}", str(ctx.get("season") or "--"))
        .replace("{时段}", str(ctx.get("period") or "--"))
        .replace("{天气}", str(ctx.get("weather") or "--"))
        .replace("{地图}", _map_name(map_def) or "--")
    )


def _window_rows(map_def: object) -> list:
    """隐藏 BOSS 窗口行（R-12 数据源，补白 1）：monsters[] 中带 `window` 条件键 +
    enemy 非空的行（与 investigate._window_rows 同口径）。"""
    raw = _raw_get(map_def, "monsters")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)
            and isinstance(e.get("window"), Mapping)
            and isinstance(e.get("enemy"), str) and e.get("enemy")]


def _mode_of(row: Mapping[str, Any]) -> str:
    """三触发模式归一（补白 1）：row["mode"] ∈ {replace,after,fixed}，缺省/非法 → "replace"。"""
    m = row.get("mode")
    if isinstance(m, str) and m in _BOSS_MODES:
        return m
    return "replace"


def _today_of(ctx: Mapping[str, Any], today: Optional[str]) -> str:
    """今日键：入参 today → ctx["today"] → 空串（缺省不强制日限，确定性，补白 3）。"""
    if today is not None:
        return str(today)
    v = ctx.get("today")
    return str(v) if v else ""


def _daily_count(ctx: Mapping[str, Any], today: str, boss_ref: str) -> int:
    """当日已触发次数：persistent_state[hidden_boss_daily][today][boss_ref]（缺省 0）。"""
    if not today:
        return 0
    ps = _ps_of(ctx)
    if ps is None:
        return 0
    d = ps.get(BOSS_DAILY_KEY)
    if not isinstance(d, Mapping):
        return 0
    sub = d.get(today)
    if not isinstance(sub, Mapping):
        return 0
    try:
        v = sub.get(boss_ref)
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _mark_daily(ctx: MutableMapping[str, Any], today: str, boss_ref: str) -> None:
    """当日触发 +1（就地写 persistent_state[hidden_boss_daily][today][boss_ref]；
    today 空串不记，补白 3）。"""
    if not today or not boss_ref:
        return
    ps = _ps_of(ctx)
    if ps is None:
        return
    d = ps.get(BOSS_DAILY_KEY)
    if not isinstance(d, MutableMapping):
        d = {}
        ps[BOSS_DAILY_KEY] = d
    sub = d.get(today)
    if not isinstance(sub, MutableMapping):
        sub = {}
        d[today] = sub
    sub[boss_ref] = _daily_count(ctx, today, boss_ref) + 1


def _pity_of(ctx: Mapping[str, Any], boss_ref: str) -> int:
    """保底计数：persistent_state[hidden_boss_pity][boss_ref]（缺省 0）。"""
    ps = _ps_of(ctx)
    if ps is None:
        return 0
    p = ps.get(BOSS_PITY_KEY)
    if not isinstance(p, Mapping):
        return 0
    try:
        v = p.get(boss_ref)
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _set_pity(ctx: MutableMapping[str, Any], boss_ref: str, value: int) -> None:
    """保底计数写入（就地，只增不减语义由调用方保证，补白 2）。"""
    if not boss_ref:
        return
    ps = _ps_of(ctx)
    if ps is None:
        return
    p = ps.get(BOSS_PITY_KEY)
    if not isinstance(p, MutableMapping):
        p = {}
        ps[BOSS_PITY_KEY] = p
    p[boss_ref] = int(value)


def _prev_hidden_count(ctx: Mapping[str, Any], hidden_id: str) -> int:
    """写入前该隐藏 ID 的嵌套计数（首见判定，R-02/R-15 同 adventure_log 口径）。"""
    ec = ctx.get("event_counts")
    if not isinstance(ec, Mapping):
        return 0
    sub = ec.get(EVENT_KEY_HIDDEN_FIND)
    if not isinstance(sub, Mapping):
        return 0
    try:
        return int(sub.get(hidden_id, 0))
    except (TypeError, ValueError):
        return 0


def _revealed_set(ctx: Mapping[str, Any]) -> set:
    """已一次性揭示标记集合（补白 6）：persistent_state[hidden_find_revealed]。"""
    ps = _ps_of(ctx)
    if ps is None:
        return set()
    raw = ps.get(REVEALED_KEY)
    if isinstance(raw, (list, tuple, set)):
        return {str(x) for x in raw}
    return set()


def _mark_revealed(ctx: MutableMapping[str, Any], rid: str) -> None:
    """写一次性揭示标记（幂等追加，补白 6）。"""
    if not rid:
        return
    ps = _ps_of(ctx)
    if ps is None:
        return
    raw = ps.get(REVEALED_KEY)
    if not isinstance(raw, list):
        raw = []
        ps[REVEALED_KEY] = raw
    if rid not in raw:
        raw.append(rid)


def _spawn_result(ctx: MutableMapping[str, Any], map_def: object, row: Mapping[str, Any],
                  mode: str, boss_ref: str, reason: str) -> dict:
    """触发成功结果（R-12）：核心键 {spawned, mode, boss_ref, reason} + signal（复用
    investigate hunt 形态，补白 4）。首见日志在击败后经 reveal_find 结算。"""
    text = row.get("desc") or row.get("hint")
    if not (isinstance(text, str) and text):
        text = f"你察觉到了「{boss_ref}」出没的迹象。"
    hfid = row.get("hidden_find_id")
    hfid_s = str(hfid) if isinstance(hfid, str) and hfid else None
    signal = {
        "kind": HUNT_SIGNAL_KIND,
        "boss_ref": boss_ref,
        "text": _render_text(text, ctx, map_def),
        "hidden_find_id": hfid_s,
        "mode": mode,
        "first_seen": None,
        "title": str(row.get("title") or boss_ref),
    }
    return {
        "spawned": True,
        "mode": mode,
        "boss_ref": boss_ref,
        "reason": reason,
        "signal": signal,
        "pity": 0,
    }


def _blocked_result(row: Mapping[str, Any], mode: str, boss_ref: str, pity: int) -> dict:
    """触发被日限挡下结果（R-12）：条件满足但当日已触发 → 未出战窗口 +1 已入保底。"""
    return {
        "spawned": False,
        "mode": mode,
        "boss_ref": boss_ref,
        "reason": "daily_limit",
        "signal": None,
        "pity": pity,
    }


# -------------------------------------------------------------------------------------
# 主入口一：隐藏 BOSS 触发判定（R-12）
# -------------------------------------------------------------------------------------
def check_boss_spawn(ctx: MutableMapping[str, Any], map_def: object,
                     *, today: Optional[str] = None) -> dict:
    """隐藏 BOSS 触发判定（R-12，三触发模式 + 100% 必出 + 3 次保底 + 日限 1 次）。

    入参:
      - ctx: 求值上下文（season/period/weather/event_counts/longline_counters/
        persistent_state/settings/today，见文件头）。
      - map_def: 所在/蹲点地图（MapDef 或 raw dict；monsters[] 隐藏 BOSS 行经 raw 兜底
        读取，补白 1）。
      - today: 今日键注入（缺省 ctx["today"]；空串=不强制日限，确定性）。
    出参 dict: {spawned, mode, boss_ref, reason, signal?, pity}；reason ∈
      condition_met（条件满足 100% 必出）/ pity（3 次保底强制触发，覆盖日限）/
      daily_limit（当日已触发被挡下，保底已 +1）/ window_not_met（窗口或 after 前置
      不满足，零暗示）/ no_hidden_boss（无隐藏 BOSS 行）。signal 仅 spawned=True 时
      携带，复用 investigate hunt 形态 {kind:"hunt", boss_ref, text, hidden_find_id,
      mode, title}。
    核心逻辑:
      ① 遍历 monsters[] 隐藏 BOSS 行：window（限定窗口 [季节]+[时段]+[天气]+[图鉴完成度]）
         不满足 → 跳过（零暗示）；after 模式再要求 row["after"] 前置条件（事件/计数）。
      ② 满足条件的首个窗口：保底就绪（pity ≥ 3）→ 无条件强制触发（覆盖日限）并清零；
         否则当日已触发（日限 1 次）→ 挡下 + 保底 +1（累计达 3 即就绪，下次必触发）；
         否则 → 100% 必出（无随机），清保底、记日限。
    """
    rows = _window_rows(map_def)
    if not rows:
        return {"spawned": False, "mode": None, "boss_ref": None,
                "reason": "no_hidden_boss", "signal": None, "pity": 0}
    today_s = _today_of(ctx, today)
    for row in rows:
        mode = _mode_of(row)
        # ① 限定窗口（R-12 条件键；求值失败=不满足，D-03 零暗示）
        if not _cond_ok(row.get("window"), ctx):
            continue
        if mode == "after":
            aft = row.get("after")
            if aft is not None and not _cond_ok(aft, ctx):
                continue
        boss = str(row.get("enemy") or "")
        if not boss:
            continue
        pity = _pity_of(ctx, boss)
        # ② 保底就绪：累计 ≥3 → 本次满足窗口必触发（补白 2），覆盖日限
        if pity >= PITY_THRESHOLD:
            _set_pity(ctx, boss, 0)
            _mark_daily(ctx, today_s, boss)
            return _spawn_result(ctx, map_def, row, mode, boss, "pity")
        # ② 日限 1 次：当日已触发 → 挡下 + 保底 +1（未出战窗口）
        if today_s and _daily_count(ctx, today_s, boss) >= 1:
            new_pity = pity + 1
            _set_pity(ctx, boss, new_pity)
            return _blocked_result(row, mode, boss, new_pity)
        # ② 条件满足 100% 必出（无随机）
        _set_pity(ctx, boss, 0)
        _mark_daily(ctx, today_s, boss)
        return _spawn_result(ctx, map_def, row, mode, boss, "condition_met")
    return {"spawned": False, "mode": None, "boss_ref": None,
            "reason": "window_not_met", "signal": None, "pity": 0}


# -------------------------------------------------------------------------------------
# 主入口二：隐藏任务触发判定（R-13 + D-05 + 补白 7）
# -------------------------------------------------------------------------------------
def npc_quest_conditions_met(ctx: Mapping[str, Any], quest: object) -> bool:
    """quest.npc.conditions 发任务条件求值（R-13 D-05，BCH-04 缺口 helper）。

    quest: 原始 quest 条目（含 npc 字段 {id, conditions, priority}）；conditions 数组
    全与（eval_condition list = all，2b4 D-02）；缺省/空 = 恒可发（2b4 §1.4 默认 []）。
    不满足/求值失败 → False（零暗示，不发任务也不提示「可领任务」）。
    """
    if not isinstance(quest, Mapping):
        return False
    npc = quest.get("npc")
    conds = npc.get("conditions") if isinstance(npc, Mapping) else None
    if conds is None:
        return True
    try:
        return bool(eval_condition(conds, _condition_ctx(ctx)))
    except Exception:
        return False


def check_hidden_quest(ctx: Mapping[str, Any], npc_id: str, quest_refs: object) -> dict:
    """隐藏任务触发判定（R-13 D-05/D-06）：NPC 条件组合全与命中 → 主动发任务。

    入参:
      - ctx: 求值上下文（season/period/weather/event_counts/codex/quest_active/
        quest_daily/quest_completed，见文件头）。
      - npc_id: 当前 NPC ID（匹配 quest.npc.id）。
      - quest_refs: 候选 quest 条目（raw dict 列表；每条 {id|quest_id, npc:{id,
        conditions, priority}, ...}）。
    出参 dict: {grant, quest_id?, reason?, priority?}；reason ∈ granted /
      no_eligible_quest（无 npc 匹配、条件不满足、已接取/已发/已完成）。
    核心逻辑:
      ① 过滤 npc.id == npc_id 的候选；按 npc.priority 升序（小者先，2b4 §1.4）。
      ② 逐条：quest.npc.conditions 全与（npc_quest_conditions_met）+ 三表去重
        （quest_active/quest_daily/quest_completed，对齐 npc.available_quests SM06）。
      ③ 首个命中 → grant=True + quest_id；全部不中 → grant=False（普通对话分支零暗示，
        不发任务不上板，D-06）。
    """
    npc_key = str(npc_id or "")
    cands: list = []
    if isinstance(quest_refs, (list, tuple)):
        for q in quest_refs:
            if not isinstance(q, Mapping):
                continue
            npc = q.get("npc")
            if not isinstance(npc, Mapping):
                continue
            if str(npc.get("id") or "") != npc_key:
                continue
            qid = q.get("quest_id") or q.get("id")
            if not (isinstance(qid, str) and qid):
                continue
            cands.append(q)
    cands.sort(key=lambda q: _priority_of(q))
    for q in cands:
        qid = str(q.get("quest_id") or q.get("id") or "")
        if not npc_quest_conditions_met(ctx, q):
            continue
        if _in_coll(ctx, "quest_active", qid):
            continue
        if _in_quest_daily(ctx, qid):
            continue
        if _in_coll(ctx, "quest_completed", qid):
            continue
        return {"grant": True, "quest_id": qid,
                "reason": "granted", "priority": _priority_of(q)}
    return {"grant": False, "quest_id": None, "reason": "no_eligible_quest", "priority": None}


def _priority_of(quest: Mapping[str, Any]) -> int:
    """quest.npc.priority 归一（2b4 §1.4：≥0 小者先；非法 → 0）。"""
    npc = quest.get("npc")
    v = npc.get("priority") if isinstance(npc, Mapping) else None
    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
        return v
    return 0


def _in_coll(ctx: Mapping[str, Any], key: str, qid: str) -> bool:
    """集合包含判定（quest_active/quest_completed：Mapping/set/list/tuple 均可）。"""
    coll = ctx.get(key)
    if coll is None:
        return False
    if isinstance(coll, Mapping):
        return qid in coll
    if isinstance(coll, (set, frozenset, list, tuple)):
        return qid in coll
    return False


def _in_quest_daily(ctx: Mapping[str, Any], qid: str) -> bool:
    """quest_daily 去重判定：扁平 {qid:...} 或嵌套 {日期: {qid:...}} 两形态兜底（对齐
    npc._in_quest_daily 口径）。"""
    qd = ctx.get("quest_daily")
    if qd is None:
        return False
    if isinstance(qd, Mapping):
        if qid in qd:
            return True
        for v in qd.values():
            if isinstance(v, Mapping) and qid in v:
                return True
        return False
    if isinstance(qd, (set, frozenset, list, tuple)):
        return qid in qd
    return False


# -------------------------------------------------------------------------------------
# 主入口三：彩蛋一次性揭示（R-15 / F-10，仪式感 + 首见日志 + lore 交接）
# -------------------------------------------------------------------------------------
def reveal_find(ctx: MutableMapping[str, Any], hidden_find_id: str, title: str) -> dict:
    """仪式感一次性揭示（R-15 / F-10，补白 5-6）。

    入参:
      - ctx: 求值上下文（event_counts/longline_counters/persistent_state 读写，见文件头）。
      - hidden_find_id: 隐藏要素 ID（写 [事件:隐藏发现:ID]，契约 L113）。
      - title: 揭示标题（BOSS 名/彩蛋名，入卡片）。
    出参 dict:
      {card, first_seen, logged, revealed, hidden_find_id, title, lore_pending, ok}
      - 首次发现：card = 【发现】{title}（⛩️ 降级，无 emoji）+ first_seen=True +
        logged=True（adventure_log.log_hidden_find：三表 + 首见日志）+ revealed=True。
      - 已揭示（one_shot 已消费）：card = 简短确认「这里没有新的发现。」+ first_seen=
        False + logged=False（不再计数/不再生成首见，TC-15）。
      - lore_pending=True（图鉴 lore 补全交接：2c1c/4d 未实装，写侧归 F-16/BCH-09）。
    核心逻辑:
      ① 去重：persistent_state[hidden_find_revealed] 已含该 ID → 简短确认（R-11 口径）。
      ② 首次：log_hidden_find(ctx, hidden_find_id)（[事件:隐藏发现:ID] 计数 + first_seen
        首见日志）+ 标记已揭示 + 输出【发现】卡片。
    """
    if not str(hidden_find_id or ""):
        return {"ok": False, "card": "", "first_seen": False, "logged": False,
                "revealed": False, "hidden_find_id": None, "title": title,
                "lore_pending": False, "reason": "empty_hidden"}
    hfid = str(hidden_find_id)
    shown_title = str(title or hfid)
    rid = f"hidden_find:{hfid}"
    if rid in _revealed_set(ctx):
        # 已 one_shot（补白 6）：简短确认，无卡片、不再计数、不再首见
        return {"ok": True, "card": DEFAULT_CONFIRM_TEXT, "first_seen": False,
                "logged": False, "revealed": True, "hidden_find_id": hfid,
                "title": shown_title, "lore_pending": False}
    first_seen = _prev_hidden_count(ctx, hfid) == 0
    logged = bool(log_hidden_find(ctx, hfid).get("ok"))
    _mark_revealed(ctx, rid)
    card = f"【发现】{shown_title}"
    return {"ok": True, "card": card, "first_seen": first_seen, "logged": logged,
            "revealed": True, "hidden_find_id": hfid, "title": shown_title,
            "lore_pending": True}
