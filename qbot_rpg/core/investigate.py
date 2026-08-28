"""调查引擎（qbot_rpg/core/investigate.py · M7 BCH-06 3f F-05/F-06 · R-07~R-11 · E-02）。

/调查 为第三层线索漏斗唯一主动确认操作【单机】L33：交互点文本彩蛋（R-08）/ 特定时段
蹲点（R-09）/ 隐藏地图揭示（R-07 延伸）+ 多命中优先级 + daily 配额 + 去重（R-11 D-04），
全程不提示原则（R-07 / TC-09）。

依据（真实签名已 read 核对）：
  - docs/细化/细化_3f_单机向体验.md：
    · R-07（2.1）：/调查 [目标]；不提示原则——无交互点/条件不满足 → 泛化环境文本，
      绝不出现「此处似乎有什么」「再调查看看」类暗示。
    · R-08（2.2）：maps.json interact_points[]（E-02 schema：id/alias/map_id/desc/
      lore_condition/hidden_find_id/one_shot 缺省 true）；lore_condition 走统一条件
      引擎（求值失败=不满足 → 泛化文本零暗示）。
    · R-09（2.3）：目标为隐藏要素所在地图 + 当前时刻满足限定窗口（[季节]+[时段]+
      [天气]）→ 隐藏 BOSS 现身；窗口外 → 泛化文本零暗示。
    · R-07 延伸（2.4）：/调查 当前地图，地图级 lore condition 满足 → 一次性揭示
      隐藏地图入口。
    · R-11（2.5 D-04）：一次 /调查 最多 1 条演出/揭示；优先级 隐藏 BOSS 蹲点 >
      隐藏地图 > 交互点彩蛋 > 泛化文本；daily 配额揭示类每日上限 3 次（可配，
      泛化不计）；one_shot 已触发 → 简短确认无卡片。
    · R-14（3.4）：命中彩蛋 → [事件:隐藏发现:ID] 计数 +1（发现即计数）。
    · R-15（3.5）：首见日志 first_seen=true，重复发现不生成首见。
  - docs/细化/细化_M7_交互补全总纲.md（F-05~F-07 模块 core/investigate.py；隐藏 BOSS
    触发契约 R-12 归 BCH-07 hidden_trigger.py，本模块仅回 kind:"hunt" 信号）。
  - qbot_rpg/core/adventure_log.py（log_hidden_find：bump_event 三表 + nested target
    + first_seen 首见日志，真实签名已 read 核对）。
  - qbot_rpg/engine/condition_engine.py（eval_condition(cond, ctx)->bool fail-safe；
    时间三键真实读取键为 season_now/period_now/weather_now 直键或 worldtime 鸭子类型）。

【工程补白 · 显式标注】
  1) interact_points 装载：map_models.MapDef 尚未扩展 E-02 访问器（归内容侧装载批次），
     本模块经 raw 字典兜底读取（BaseDef.raw / BaseDef.get），raw dict 亦可直传。
  2) 隐藏 BOSS 窗口数据源（R-12 归 BCH-07）：本模块从地图 raw monsters[] 行读可选
     `window` 条件键（Mapping，eval_condition 求值），命中 → 回 kind:"hunt" 信号 +
     boss_ref（行 enemy 引用）；实际 BOSS 战 / 保底 / 日限由 BCH-07 消费。
  3) 隐藏地图揭示数据源（R-07 延伸，字段命名补白，内容侧尚未落地）：
       a) 地图级 raw `hidden_reveal`（Mapping 或数组；{map_id, desc?, lore_condition?,
          one_shot?}）——贴合 R-07 §2.4「地图级 lore condition + 介绍文本」；
       b) 既有 exits[dir] mode="hidden" 通道（2a1b 契约）+ condition + desc?（补白）。
     任一命中 → kind:"map_reveal" + map_ref；一次性（one_shot 缺省 true）。
  4) 去重标记落 persistent_state["investigate_revealed"]（list，{egg|map_reveal}:{id}）；
     daily 配额落 persistent_state["investigate_quota"]（{日期: 计数}，任务契约）。
     persistent_state JSON 内键，零新表（3f D-01 零新存储口径）。
  5) 泛化文本（不提示原则）：无命中 → 地图 desc（补白默认）→ 缺省中性文本
     「四周一片寂静，并没有特别的发现。」；可配 settings.investigate.generic_texts 池
     （ctx["rng"] 确定性选择，无 rng → 池首条）。全部零「此处有隐藏」措辞。
  6) 简短确认文本（R-11 去重）：one_shot 已触发 → entry.confirm 或缺省中性文本
     「这里没有新的发现。」（无彩蛋正文、无揭示卡片、不再计数）。
  7) 配额：settings.investigate.daily_quota 缺省 3；揭示类（egg 卡片 / map_reveal /
     hunt）各计 1 次，泛化与确认不计；today 由入参/ctx["today"] 注入（缺省不强制配额，
     确定性；按自然日懒计算重置，对齐 2c1c R-02 窗口纪律）。
  8) 条件求值桥接：条件引擎时间三键真实读取键为 season_now/period_now/weather_now，
     本模块按任务契约从 ctx["season"/"period"/"weather"] 派生直键后再求值。
  9) 命中彩蛋 → 复用 adventure_log.log_hidden_find（内部 bump_event：event_counts
     nested {[事件:隐藏发现]:{ID:count}} + longline_counters + event_log 首见日志），
     与本批契约「event_bus.bump_event nested target + first_seen」同口径。

铁律：零 NoneBot import；纯函数确定性（today/rng 由 ctx 注入）；每函数 docstring；
无 emoji（3d/emoji 纪律）；最小侵入（不改兄弟路 investigate_commands.py）。
"""

from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.adventure_log import EVENT_KEY_HIDDEN_FIND, log_hidden_find
from qbot_rpg.engine.condition_engine import eval_condition

__all__ = [
    "DEFAULT_DAILY_QUOTA",
    "QUOTA_KEY",
    "REVEALED_KEY",
    "DEFAULT_GENERIC_TEXT",
    "DEFAULT_CONFIRM_TEXT",
    "KIND_PRIORITY",
    "daily_quota_of",
    "investigate_map",
]

# -------------------------------------------------------------------------------------
# 常量（R-11 D-04 / 补白 4-7）
# -------------------------------------------------------------------------------------
# 揭示类每日配额缺省（可配 settings.investigate.daily_quota）
DEFAULT_DAILY_QUOTA = 3

# daily 配额落点（任务契约：persistent_state["investigate_quota"] = {日期: 计数}）
QUOTA_KEY = "investigate_quota"

# 一次性去重标记落点（补白 4：persistent_state["investigate_revealed"] = [标记...]）
REVEALED_KEY = "investigate_revealed"

# 泛化环境文本（不提示原则：零「此处有隐藏」措辞）
DEFAULT_GENERIC_TEXT = "四周一片寂静，并没有特别的发现。"

# one_shot 已触发后的简短确认（R-11 去重：无彩蛋正文、无揭示卡片）
DEFAULT_CONFIRM_TEXT = "这里没有新的发现。"

# 多命中优先级（R-11 D-04：隐藏 BOSS 蹲点 > 隐藏地图 > 交互点彩蛋 > 泛化文本）
KIND_PRIORITY: Tuple[str, ...] = ("hunt", "map_reveal", "egg")


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
    """地图定义 raw 读取（兜底，补白 1）：BaseDef.get/raw（MapDef）或纯 dict；缺省 None。"""
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


def _norm(s: object) -> str:
    """别名/名称归一：非空字符串 strip + 小写（目标匹配用）。"""
    if not isinstance(s, str):
        return ""
    return s.strip().lower()


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


def _map_desc(map_def: object) -> str:
    """地图介绍文本：def.desc 或 raw desc（兜底空串）。"""
    v = getattr(map_def, "desc", None)
    if isinstance(v, str) and v:
        return v
    v = _raw_get(map_def, "desc")
    return v if isinstance(v, str) else ""


def _interact_points(map_def: object) -> List[Mapping[str, Any]]:
    """interact_points[]（E-02）→ 合法条目列表（raw 兜底；id 非空 str 才收）。"""
    raw = _raw_get(map_def, "interact_points")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)
            and isinstance(e.get("id"), str) and e.get("id")]


def _window_rows(map_def: object) -> List[Mapping[str, Any]]:
    """隐藏 BOSS 窗口行（补白 2）：monsters[] 中带 `window` 条件键 + enemy 非空的行。"""
    raw = _raw_get(map_def, "monsters")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)
            and isinstance(e.get("window"), Mapping)
            and isinstance(e.get("enemy"), str) and e.get("enemy")]


def _norm_reveal_cand(e: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """hidden_reveal 条目 → 统一候选（map_ref/desc/lore_condition/one_shot）；缺 map_ref → None。"""
    ref = e.get("map_ref")
    if not (isinstance(ref, str) and ref):
        ref = e.get("map_id")
    if not (isinstance(ref, str) and ref):
        return None
    return {
        "map_ref": ref,
        "desc": e.get("desc"),
        "lore_condition": e.get("lore_condition"),
        "one_shot": bool(e.get("one_shot", True)),
    }


def _hidden_reveals(map_def: object) -> List[Mapping[str, Any]]:
    """隐藏地图揭示候选（补白 3）：地图级 raw hidden_reveal（单/数组）+ exits 隐藏。"""
    out: List[Mapping[str, Any]] = []
    hr = _raw_get(map_def, "hidden_reveal")
    if isinstance(hr, Mapping):
        hr = [hr]
    if isinstance(hr, list):
        for e in hr:
            nc = _norm_reveal_cand(e)
            if nc is not None:
                out.append(nc)
    ex = _raw_get(map_def, "exits")
    if isinstance(ex, Mapping):
        for entry in ex.values():
            if not isinstance(entry, Mapping):
                continue
            if (entry.get("mode") == "hidden" and isinstance(entry.get("to"), str)
                    and entry.get("to")):
                out.append({
                    "map_ref": entry.get("to"),
                    "desc": entry.get("desc"),
                    "lore_condition": entry.get("condition"),
                    "one_shot": bool(entry.get("one_shot", True)),
                })
    return out


def _condition_ctx(ctx: Mapping[str, Any]) -> dict:
    """统一条件引擎求值上下文（桥接，补白 8）：从 ctx["season"/"period"/"weather"] 派生
    season_now/period_now/weather_now 直键（条件引擎时间三键真实读取键），其余键透传。"""
    out = dict(ctx)
    for src, dst in (("season", "season_now"), ("period", "period_now"),
                     ("weather", "weather_now")):
        v = ctx.get(src)
        if isinstance(v, str) and v:
            out[dst] = v
    return out


def _cond_ok(cond: object, ctx: Mapping[str, Any]) -> bool:
    """统一条件求值（R-08 / D-03）：null=恒可触发；求值失败/False = 不满足（不抛错）。"""
    if cond is None:
        return True
    try:
        return bool(eval_condition(cond, _condition_ctx(ctx)))
    except Exception:
        return False


def _render_text(template: Optional[str], ctx: Mapping[str, Any], map_def: object) -> str:
    """模板占位符渲染（R-14，3d 模板规范子集，补白 1/5）：{季节}/{时段}/{天气}/{地图} 注入。"""
    if not isinstance(template, str) or not template:
        return ""
    return (
        template
        .replace("{季节}", str(ctx.get("season") or "--"))
        .replace("{时段}", str(ctx.get("period") or "--"))
        .replace("{天气}", str(ctx.get("weather") or "--"))
        .replace("{地图}", _map_name(map_def) or "--")
    )


def _generic_text(ctx: Mapping[str, Any], map_def: object) -> str:
    """泛化环境文本（不提示原则）：settings 池（rng 确定性）→ 地图 desc → 缺省中性文本。"""
    s = ctx.get("settings")
    if isinstance(s, Mapping):
        inv = s.get("investigate")
        if isinstance(inv, Mapping):
            pool = inv.get("generic_texts")
            if isinstance(pool, list) and pool and all(isinstance(t, str) and t for t in pool):
                rng = ctx.get("rng")
                if rng is not None and hasattr(rng, "choice"):
                    try:
                        return _render_text(rng.choice(pool), ctx, map_def)
                    except Exception:
                        pass
                return _render_text(pool[0], ctx, map_def)
    desc = _map_desc(map_def)
    if desc:
        return desc
    return DEFAULT_GENERIC_TEXT


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
    """已触发一次性标记集合（补白 4）：persistent_state[investigate_revealed]。"""
    ps = _ps_of(ctx)
    if ps is None:
        return set()
    raw = ps.get(REVEALED_KEY)
    if isinstance(raw, (list, tuple, set)):
        return {str(x) for x in raw}
    return set()


def _mark_revealed(ctx: MutableMapping[str, Any], rid: str) -> None:
    """写一次性标记（幂等追加，补白 4）。"""
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


def _quota_used(ctx: Mapping[str, Any], today: str) -> int:
    """今日已用配额：persistent_state[investigate_quota][today]（缺省 0；today 空 = 0）。"""
    if not today:
        return 0
    ps = _ps_of(ctx)
    if ps is None:
        return 0
    q = ps.get(QUOTA_KEY)
    if not isinstance(q, Mapping):
        return 0
    v = q.get(today)
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _consume_quota(ctx: MutableMapping[str, Any], today: str) -> int:
    """配额 +1（就地写 persistent_state[investigate_quota][today]），返回新计数。"""
    if not today:
        return 0
    ps = _ps_of(ctx)
    if ps is None:
        return 0
    q = ps.get(QUOTA_KEY)
    if not isinstance(q, MutableMapping):
        q = {}
        ps[QUOTA_KEY] = q
    cur = _quota_used(ctx, today)
    q[str(today)] = cur + 1
    return cur + 1


# -------------------------------------------------------------------------------------
# 各命中类的判定（R-08 / R-09 / R-07 延伸）——纯函数，回结果 dict 或 None（不命中）
# -------------------------------------------------------------------------------------
def _egg_outcome(ctx: MutableMapping[str, Any], map_def: object,
                 point: Mapping[str, Any], today: str, cap: int) -> Optional[dict]:
    """交互点彩蛋判定（R-08）：lore_condition 不满足 → None（不命中，零暗示）；
    命中 → 去重确认（one_shot 已触发）或揭示卡片（计数 + 首见日志 + 配额）。"""
    if not _cond_ok(point.get("lore_condition"), ctx):
        return None
    pid = str(point.get("id") or "")
    one_shot = bool(point.get("one_shot", True))
    rid = f"egg:{pid}" if pid else ""
    quota_left = max(0, cap - _quota_used(ctx, today))
    if one_shot and rid and rid in _revealed_set(ctx):
        # R-11 去重：已 one_shot → 简短确认，无彩蛋正文、无揭示卡片、不再计数
        text = point.get("confirm")
        if not (isinstance(text, str) and text):
            text = DEFAULT_CONFIRM_TEXT
        return {
            "kind": "egg_confirm",
            "text": _render_text(text, ctx, map_def),
            "hidden_find_id": None,
            "one_shot": True,
            "quota_remaining": quota_left,
            "first_seen": None,
            "boss_ref": None,
            "map_ref": None,
            "interact_point_id": pid,
        }
    if rid:
        _mark_revealed(ctx, rid)
    _consume_quota(ctx, today)
    hidden_id = point.get("hidden_find_id")
    hfid = str(hidden_id) if isinstance(hidden_id, str) and hidden_id else None
    first_seen = None
    if hfid:
        # R-14/R-15：发现即计数 + 首见日志（event_bus.bump_event nested target）
        first_seen = _prev_hidden_count(ctx, hfid) == 0
        log_hidden_find(ctx, hfid)
    text = point.get("desc")
    if not (isinstance(text, str) and text):
        text = DEFAULT_GENERIC_TEXT
    return {
        "kind": "egg",
        "text": _render_text(text, ctx, map_def),
        "hidden_find_id": hfid,
        "one_shot": one_shot,
        "quota_remaining": max(0, cap - _quota_used(ctx, today)),
        "first_seen": first_seen,
        "boss_ref": None,
        "map_ref": None,
        "interact_point_id": pid,
    }


def _map_reveal_outcome(ctx: MutableMapping[str, Any], map_def: object,
                        cand: Mapping[str, Any], today: str, cap: int) -> Optional[dict]:
    """隐藏地图揭示（R-07 延伸）：lore_condition 不满足 → None（零暗示）；
    命中 → 去重确认或一次性揭示（标记 + 配额）。"""
    if not _cond_ok(cand.get("lore_condition"), ctx):
        return None
    ref = str(cand.get("map_ref") or "")
    one_shot = bool(cand.get("one_shot", True))
    rid = f"map_reveal:{ref}" if ref else ""
    quota_left = max(0, cap - _quota_used(ctx, today))
    if one_shot and rid and rid in _revealed_set(ctx):
        return {
            "kind": "map_reveal_confirm",
            "text": DEFAULT_CONFIRM_TEXT,
            "hidden_find_id": None,
            "one_shot": True,
            "quota_remaining": quota_left,
            "first_seen": None,
            "boss_ref": None,
            "map_ref": ref,
            "interact_point_id": None,
        }
    if rid:
        _mark_revealed(ctx, rid)
    _consume_quota(ctx, today)
    text = cand.get("desc")
    if not (isinstance(text, str) and text):
        text = f"发现了一条隐藏通道，通往「{ref}」。"
    return {
        "kind": "map_reveal",
        "text": _render_text(text, ctx, map_def),
        "hidden_find_id": None,
        "one_shot": one_shot,
        "quota_remaining": max(0, cap - _quota_used(ctx, today)),
        "first_seen": None,
        "boss_ref": None,
        "map_ref": ref,
        "interact_point_id": None,
    }


def _hunt_outcome(ctx: MutableMapping[str, Any], map_def: object,
                  row: Mapping[str, Any], today: str, cap: int) -> Optional[dict]:
    """特定时段蹲点（R-09）：window 限定窗口求值不满足 → None（零暗示）；
    命中 → kind:"hunt" 信号 + boss_ref（触发契约 R-12 归 BCH-07，本批不接战）。"""
    if not _cond_ok(row.get("window"), ctx):
        return None
    boss = str(row.get("enemy") or "")
    if not boss:
        return None
    _consume_quota(ctx, today)
    text = row.get("desc") or row.get("hint")
    if not (isinstance(text, str) and text):
        text = f"你察觉到了「{boss}」出没的迹象。"
    return {
        "kind": "hunt",
        "text": _render_text(text, ctx, map_def),
        "hidden_find_id": None,
        "one_shot": None,
        "quota_remaining": max(0, cap - _quota_used(ctx, today)),
        "first_seen": None,
        "boss_ref": boss,
        "map_ref": None,
        "interact_point_id": None,
    }


def _generic_result(ctx: Mapping[str, Any], map_def: object,
                    cap: int, today: str) -> dict:
    """泛化环境文本结果（不提示原则；不计配额，R-11）。"""
    return {
        "kind": "generic",
        "text": _generic_text(ctx, map_def),
        "hidden_find_id": None,
        "one_shot": None,
        "quota_remaining": max(0, cap - _quota_used(ctx, today)),
        "first_seen": None,
        "boss_ref": None,
        "map_ref": None,
        "interact_point_id": None,
    }


# -------------------------------------------------------------------------------------
# 主入口
# -------------------------------------------------------------------------------------
def investigate_map(ctx: MutableMapping[str, Any], map_def: object,
                    target: Optional[str] = None, *, today: Optional[str] = None) -> dict:
    """/调查 引擎主入口（R-07~R-11）→ 结果 dict。

    入参:
      - ctx: 求值上下文（season/period/weather/event_counts/longline_counters/
        persistent_state/settings/today/rng，见文件头）。
      - map_def: 被调查地图（MapDef 或 raw dict；interact_points 经 raw 兜底读取）。
      - target: 可选目标（交互点别名/id 或地图名/id；省略=当前地图整体调查）。
      - today: 今日键注入（缺省 ctx["today"]；空串=不强制配额，确定性）。
    出参 dict:
      {kind, text, hidden_find_id?, one_shot?, quota_remaining, first_seen?,
       boss_ref?, map_ref?, interact_point_id?}；
      kind ∈ generic / egg / egg_confirm / map_reveal / map_reveal_confirm / hunt。
    核心逻辑:
      ① 目标归一：匹配交互点别名/id → 点级；匹配地图 id/名或省略 → 地图级；
         否则 → 泛化文本（不提示原则，零暗示）。
      ② 地图级按优先级 hunt > map_reveal > egg（R-11 D-04），首次命中即返回
         （一次 /调查 最多 1 条演出/揭示）；点级仅该交互点。
      ③ daily 配额（R-11）：揭示类（egg 卡片 / map_reveal / hunt）各计 1 次
         （settings.investigate.daily_quota 缺省 3；泛化与确认不计）；超限 → 泛化文本。
      ④ 去重（R-11）：one_shot（缺省 true）已触发 → 简短确认，无卡片无计数。
      ⑤ 命中彩蛋 → log_hidden_find 写 [事件:隐藏发现:ID]（nested + first_seen 首见
         日志，R-14/R-15）；hunt 仅回信号，BOSS 战归 BCH-07（R-12）。
    """
    cap = daily_quota_of(ctx)
    today_s = _today_of(ctx, today)

    # ③ R-11：揭示类配额超限 → 泛化文本（零暗示；确认/泛化不受此限）
    if today_s and _quota_used(ctx, today_s) >= cap:
        return _generic_result(ctx, map_def, cap, today_s)

    mid = _map_id(map_def)
    mname = _map_name(map_def)
    points = _interact_points(map_def)
    t = _norm(target)

    matched: Optional[Mapping[str, Any]] = None
    if t:
        for p in points:
            if _norm(p.get("id")) == t:
                matched = p
                break
            aliases = p.get("alias")
            if isinstance(aliases, list) and any(
                    _norm(a) == t for a in aliases if isinstance(a, str)):
                matched = p
                break

    map_level = True
    if t:
        if matched is not None:
            map_level = False
        elif not (t == _norm(mid) or t == _norm(mname)):
            # 目标既非交互点也非本图 → 泛化（不提示原则，零暗示）
            return _generic_result(ctx, map_def, cap, today_s)

    if map_level:
        # ② 优先级：隐藏 BOSS 蹲点 > 隐藏地图 > 交互点彩蛋（R-11 D-04）
        for row in _window_rows(map_def):
            r = _hunt_outcome(ctx, map_def, row, today_s, cap)
            if r is not None:
                return r
        for cand in _hidden_reveals(map_def):
            r = _map_reveal_outcome(ctx, map_def, cand, today_s, cap)
            if r is not None:
                return r
        for p in points:
            r = _egg_outcome(ctx, map_def, p, today_s, cap)
            if r is not None:
                return r
    else:
        assert matched is not None
        r = _egg_outcome(ctx, map_def, matched, today_s, cap)
        if r is not None:
            return r
    return _generic_result(ctx, map_def, cap, today_s)


def _today_of(ctx: Mapping[str, Any], today: Optional[str]) -> str:
    """今日键：入参 today → ctx["today"] → 空串（缺省不强制配额，确定性）。"""
    if today is not None:
        return str(today)
    v = ctx.get("today")
    return str(v) if v else ""


def daily_quota_of(ctx: Mapping[str, Any]) -> int:
    """揭示类每日配额（R-11）：settings.investigate.daily_quota，缺省 3。"""
    s = ctx.get("settings")
    if isinstance(s, Mapping):
        inv = s.get("investigate")
        if isinstance(inv, Mapping):
            v = inv.get("daily_quota")
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
    return DEFAULT_DAILY_QUOTA
