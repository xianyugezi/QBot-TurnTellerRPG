"""环境 lore 定向（qbot_rpg/core/environment_lore.py · M7 BCH-09 · F-15/F-16 · R-22~R-24 · E-06）。

环境文本泛暗示（R-23 / F-15，三层线索漏斗第一层）+ 图鉴 lore 定向线索（R-24 / F-16，
第二层）+ 定向解锁接线（codex.unlock_lore 惰性兜底）+ 图鉴条目 lore 展示数据源
（lore_view 不泄露原则）。

依据（真实签名已 read 核对）：
  - docs/细化/细化_3f_单机向体验.md：
    · R-22（5.1）：环境文本泛暗示——载体 地图介绍/天气演出文本，暗写代号不直接点名
      【单机】L31；窗口 季节/时段/天气条件组合（L58/L114）；概率 氛围 10-20% 特殊
      2-5%（L85）；懒触发不轰炸（L65）。
    · R-23（5.2 / F-16）：图鉴 lore 定向线索——怪物/鱼类条目补全后解锁传闻段
      【单机】L32；层级 = 基础段（点亮可见）+ 传闻段（补全解锁）+ 深层传闻
      （隐藏发现后解锁）L71。
    · R-25（5.4 漏斗衔接）：任何一层都不提前泄露下一层（不提示原则）——传闻段只在
      lore_unlocked 后出现，基础段（弱点/机制/掉落策略提示）点亮即可见。
    · R-07 / TC-09：泛化环境文本零「此处有隐藏」类措辞。
  - docs/细化/细化_4d_图鉴聚合契约.md §5.4：lore 文案预留「传闻」语义位（desc 前缀
    「传闻：」约定，内容包自定）；隐藏要素发现后该条目 lore 行全集一次性解锁。
  - docs/细化/细化_2a1d_地图字段扩展.md LC-A~LC-E：enemies.json lore 条目可选
    `condition`（{var:season|period|weather, op:eq, param:X}，2a4c 三键约定）；
    unlock 阈值与 condition **同时满足才显示**该条（AND，LC-01）；求值失败默认不满足
    （LC-D）；存档只存解锁状态不复制文本（【怪物】L230 / LC-E）。
  - qbot_rpg/core/codex.py（unlock_lore(ctx, category, ref_id)->dict 写 codex_state
    lore_unlocked，未 seen 返回 not_seen_yet；CATEGORIES monster→enemy / weapon→
    equipment / item→item；codex_view entries 已暴露 lore_unlocked——真实签名已 read
    核对，L201-213 / L264-270）。
  - qbot_rpg/core/investigate.py（_condition_ctx 桥接：season/period/weather → 条件引擎
    三键 season_now/period_now/weather_now；_render_text 模板占位符；DEFAULT_GENERIC_TEXT
    泛化缺省——R-23 复用口径，补白 2）。
  - qbot_rpg/engine/condition_engine.py（eval_condition(cond, ctx)->bool fail-safe；
    三键 var ∈ _PARAM_OPERAND_VARS，value 缺省时 param 作比较操作数 L669-672）。

【工程补白 · 显式标注】
  1) 模块命名补白：M7 总纲（细化_M7_交互补全总纲.md §三 F-15~F-18）规划 core/ambient.py
     合体模块；本批 3f 任务拆分 environment_lore.py 单承 F-15/F-16 定向侧，F-17/F-18
     （环境事件注册 / 校验器可达性）归兄弟路。总纲 ambient.py 未落地，无命名冲突。
  2) maps.json `lore.ambient[]` schema（内容侧尚未落地，字段命名补白，E-06 延伸）：
     地图条目顶层 `lore: {ambient: [{text, window?, weight?}]}`——text 泛暗示正文；
     window 接受两种形态：条件表达式（var/all/any/not → eval_condition）或
     {season, period, weather} 直接值形态（值为 str/list，全匹配才通过，对齐
     investigate_commands 本地兜底口径）；weight 为 R-22 概率分流保留位（氛围 10-20%/
     特殊 2-5% 归 F-17 懒触发消费，本模块不实现概率门——纯函数确定性）。
  3) enemies.json `lore` 条目 {unlock, desc, condition?}（2a1d LC-01~LC-04）：
     desc 前缀「传闻：」= 传闻段/深层传闻（4d §5.4 语义位）；无前缀 = 基础段策略提示。
     lore_view 只回解锁后传闻（未解锁 → None 不泄露，R-25）；lore_hint 未解锁只回
     基础段（unlock 阈值 + condition 同时满足的行，LC-01/LC-E）。
  4) 解锁接线（3f hidden_trigger 补白 5 / codex unlock_lore 缺口的本批收口）：
     unlock_lore_wired 惰性 import qbot_rpg.core.codex.unlock_lore（已提供接口）写
     codex_state lore_unlocked；import 失败 → 直写 codex_state 兜底。消费接线
     （hidden_trigger.reveal_find 的 lore_pending / codex_milestones 100% 世界之书 /
     彩蛋发现）为登记补白交收口——本模块不改兄弟路文件，由对应批次调用本函数。
  5) 展示接线：commands/codex_commands.py `_category_page` 最小侵入追加「（传闻）」
     行尾标记（消费 codex_view 已暴露的 lore_unlocked，未解锁零标记），改动仅 1 行
     append，不改引擎/存储。
  6) 纯函数确定性：rng 由 ctx 注入（choice/randrange），无 rng → 池首条；season/
     period/weather 从 ctx 直读（对齐 investigate 补白 8 口径），无外部时间依赖。
  7) 泛化缺省文本复用 investigate.DEFAULT_GENERIC_TEXT（惰性 import 兜底，R-23 复用
     口径）；本地零暗示池补齐多样性（全部零「此处有隐藏」措辞，TC-09）。

铁律：零 NoneBot import；纯函数确定性（rng ctx 注入）；每函数 docstring；无 emoji；
最小侵入（不改兄弟路环境事件/校验器文件）；不 git commit。
"""

from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional, Tuple, cast

from qbot_rpg.engine.condition_engine import eval_condition

__all__ = [
    "RUMOR_PREFIX",
    "DEFAULT_AMBIENT_TEXT",
    "ENV_KEYS",
    "ambient_context",
    "lore_hint",
    "lore_view",
    "unlock_lore_wired",
]

# -------------------------------------------------------------------------------------
# 常量（R-22 / 4d §5.4 / 2a1d LC 系列）
# -------------------------------------------------------------------------------------
# 传闻段语义位（4d §5.4：desc 前缀「传闻：」= 传闻/深层传闻，内容包自定）
RUMOR_PREFIX = "传闻："

# 泛化缺省文本（R-07 / TC-09 零暗示；复用 investigate.DEFAULT_GENERIC_TEXT 口径）
DEFAULT_AMBIENT_TEXT = "四周一片寂静，并没有特别的发现。"

# 环境三键（R-05 快照 + 2a4c 三键约定；直接值形态匹配用）
ENV_KEYS: Tuple[str, ...] = ("season", "period", "weather")

# 分册 → registry kind（对齐 codex.CATEGORIES；codex 不可用时的本地兜底）
_LOCAL_CATEGORIES: Mapping[str, Tuple[str, ...]] = {
    "monster": ("enemy",),
    "weapon": ("equipment",),
    "item": ("item",),
}

# 零暗示泛化池（R-23 复用口径 + 本地多样性；绝无「此处有隐藏」措辞，TC-09）
_NEUTRAL_POOL: Tuple[str, ...] = (
    "四周一片寂静，并没有特别的发现。",
    "风穿过原野，带起一阵沙沙声，别无他物。",
    "眼前的景象一如既往，并无异常。",
    "你仔细环顾四周，一切如常。",
)


# -------------------------------------------------------------------------------------
# 内部小工具（纯函数，均带 docstring）
# -------------------------------------------------------------------------------------
def _raw_get(defn: object, key: str) -> Any:
    """定义 raw 读取（兜底）：BaseDef.get/raw（MapDef/EnemyDef）或纯 dict；缺省 None。"""
    if defn is None:
        return None
    getter = getattr(defn, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            pass
    raw = getattr(defn, "raw", None)
    if isinstance(raw, Mapping):
        return raw.get(key)
    if isinstance(defn, Mapping):
        return defn.get(key)
    return None


def _map_name(map_def: object) -> str:
    """地图名：def.name 或 raw name（兜底空串）。"""
    v = getattr(map_def, "name", None)
    if isinstance(v, str) and v:
        return v
    v = _raw_get(map_def, "name")
    return v if isinstance(v, str) else ""


def _condition_ctx(ctx: Mapping[str, Any]) -> dict:
    """统一条件引擎求值上下文（桥接，对齐 investigate 补白 8）：从 ctx[\"season\"/\"period\"/\"
    \"weather\"] 派生 season_now/period_now/weather_now 直键（条件引擎时间三键真实读取键），
    其余键透传。"""
    out = dict(ctx)
    for src, dst in (("season", "season_now"), ("period", "period_now"),
                     ("weather", "weather_now")):
        v = ctx.get(src)
        if isinstance(v, str) and v:
            out[dst] = v
    return out


def _cond_ok(cond: object, ctx: Mapping[str, Any]) -> bool:
    """统一条件求值（LC-D / D-03）：None=恒满足；求值失败/False = 不满足（不抛错）。"""
    if cond is None:
        return True
    try:
        return bool(eval_condition(cond, _condition_ctx(ctx)))
    except Exception:
        return False


def _window_ok(window: object, ctx: Mapping[str, Any]) -> bool:
    """ambient 窗口匹配（补白 2 两种形态）：条件表达式（var/all/any/not/type →
    eval_condition）或 {season,period,weather} 直接值形态（值为 str/list，全匹配才通过）。"""
    if window is None:
        return True
    if not isinstance(window, Mapping):
        return False
    if any(k in window for k in ("var", "all", "any", "not", "type")):
        return _cond_ok(window, ctx)
    for key in ENV_KEYS:
        if key not in window:
            continue
        want = window[key]
        got = str(ctx.get(key) or "")
        if isinstance(want, (list, tuple, set, frozenset)):
            if got not in {str(x) for x in want}:
                return False
        elif str(want) != got:
            return False
    return True


def _render_text(template: Optional[str], ctx: Mapping[str, Any],
                 map_def: object) -> str:
    """模板占位符渲染（3d 模板规范子集，对齐 investigate._render_text）：{季节}/{时段}/
    {天气}/{地图} 注入。"""
    if not isinstance(template, str) or not template:
        return ""
    return (
        template
        .replace("{季节}", str(ctx.get("season") or "--"))
        .replace("{时段}", str(ctx.get("period") or "--"))
        .replace("{天气}", str(ctx.get("weather") or "--"))
        .replace("{地图}", _map_name(map_def) or "--")
    )


def _env_header(ctx: Mapping[str, Any]) -> str:
    """环境快照头（R-05 展示口径）：`（{季节}·{时段}·{天气}）`，缺失键 → "--"；
    三键全缺 → 空串（不输出占位头）。"""
    parts = [str(ctx.get(k) or "--") for k in ENV_KEYS]
    if all(p == "--" for p in parts):
        return ""
    return "（" + "·".join(parts) + "）"


def _neutral_text(ctx: Mapping[str, Any]) -> str:
    """零暗示泛化文本（R-07 / TC-09）：rng 确定性选择（无 rng → 池首条）。"""
    rng = ctx.get("rng")
    if rng is not None and hasattr(rng, "randrange"):
        try:
            return _NEUTRAL_POOL[rng.randrange(len(_NEUTRAL_POOL))]
        except Exception:
            pass
    return _NEUTRAL_POOL[0]


def _default_generic() -> str:
    """泛化缺省文本（R-23 复用 investigate.DEFAULT_GENERIC_TEXT；惰性 import 兜底）。"""
    try:
        from qbot_rpg.core.investigate import DEFAULT_GENERIC_TEXT  # noqa: PLC0415
        if isinstance(DEFAULT_GENERIC_TEXT, str) and DEFAULT_GENERIC_TEXT:
            return DEFAULT_GENERIC_TEXT
    except Exception:
        pass
    return DEFAULT_AMBIENT_TEXT


def _category_kinds(category: str) -> Tuple[str, ...]:
    """分册 → registry kind（codex.CATEGORIES 惰性优先，本地兜底）。"""
    try:
        from qbot_rpg.core.codex import CATEGORIES  # noqa: PLC0415
        kinds = CATEGORIES.get(category)
        if kinds:
            return tuple(kinds)
    except Exception:
        pass
    return _LOCAL_CATEGORIES.get(category, ())


def _resolve_def(ctx: Mapping[str, Any], category: str, ref_id: str) -> object:
    """条目定义解析（经 registry）：category 各 kind 逐表 resolve，首个命中返回。"""
    reg = ctx.get("registry")
    if reg is None or not hasattr(reg, "resolve"):
        return None
    for kind in _category_kinds(category):
        try:
            d = reg.resolve(ref_id, kind)
            if d is not None:
                return d
        except Exception:
            continue
    return None


def _lore_lines(defn: object) -> List[Mapping[str, Any]]:
    """enemies.json lore 条目列表（{unlock, desc, condition?}，2a1d LC-01）；非 list 形态 → []。"""
    raw = _raw_get(defn, "lore")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)]


def _codex_pct(ctx: Mapping[str, Any]) -> float:
    """图鉴完成度（unlock 阈值判据，4d §5.2 D-05）：ctx[\"codex\"] 标量优先，惰性
    codex_progress 兜底；任何缺失/非法 → 0.0（fail-safe）。"""
    raw = ctx.get("codex")
    if raw is None:
        try:
            from qbot_rpg.core.codex import codex_progress  # noqa: PLC0415
            r = codex_progress(cast(MutableMapping, ctx))
            if isinstance(r, Mapping):
                raw = r.get("pct")
            else:
                raw = r
        except Exception:
            raw = None
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _base_visible_lines(lines: List[Mapping[str, Any]],
                        ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """基础段可见行（LC-01/LC-E）：unlock 阈值（完成度 ≥ unlock）与 condition **同时
    满足**才显示；阈值缺失 = 恒过（unlock 0 语义）；求值失败/非法 → 该行不显示。"""
    pct = _codex_pct(ctx)
    out: List[Mapping[str, Any]] = []
    for ln in lines:
        u = ln.get("unlock")
        if u is not None:
            try:
                if float(u) > pct:
                    continue
            except (TypeError, ValueError):
                continue  # 非法 unlock → 不显示（LC-D fail-safe）
        if not _cond_ok(ln.get("condition"), ctx):
            continue
        out.append(ln)
    return out


def _rumor_lines(lines: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """传闻段/深层传闻行（4d §5.4）：desc 前缀「传闻：」的 lore 行；无 → 空表。"""
    return [ln for ln in lines
            if isinstance(ln.get("desc"), str) and ln["desc"].startswith(RUMOR_PREFIX)]


def _join_desc(lines: List[Mapping[str, Any]], ctx: Mapping[str, Any],
               map_def: object) -> str:
    """lore 行 desc 渲染拼接（模板占位符注入；非 str desc 行跳过）。"""
    parts = [
        _render_text(str(ln["desc"]), ctx, map_def)
        for ln in lines
        if isinstance(ln.get("desc"), str) and ln["desc"]
    ]
    return "\n".join(parts)


def _seen_entry(ctx: Mapping[str, Any], category: str,
                ref_id: str) -> Optional[Mapping[str, Any]]:
    """codex_state 条目读取（已见判定）：codex_state[category][ref_id] Mapping；缺失 → None。"""
    st = ctx.get("codex_state")
    if not isinstance(st, Mapping):
        return None
    cat = st.get(category)
    if not isinstance(cat, Mapping):
        return None
    entry = cat.get(ref_id)
    return entry if isinstance(entry, Mapping) else None


def _lore_unlocked_of(ctx: Mapping[str, Any], category: str, ref_id: str) -> bool:
    """条目 lore_unlocked 读取（codex_state 直读，未解锁 → False）。"""
    entry = _seen_entry(ctx, category, ref_id)
    return bool(entry is not None and entry.get("lore_unlocked"))


def _ambient_pool(map_def: object) -> List[Mapping[str, Any]]:
    """maps.json lore.ambient[] 池（补白 2 字段命名）：顶层 lore Mapping + ambient 列表；
    仅收 text 非空 str 的 Mapping 条目。"""
    lore = _raw_get(map_def, "lore")
    if not isinstance(lore, Mapping):
        return []
    amb = lore.get("ambient")
    if not isinstance(amb, list):
        return []
    return [e for e in amb if isinstance(e, Mapping)
            and isinstance(e.get("text"), str) and e.get("text")]


def _pick_ambient(ctx: Mapping[str, Any], matched: List[Mapping[str, Any]],
                  map_def: object) -> str:
    """匹配 ambient 片段确定性选择（R-22 懒触发概率门归 F-17）：rng choice/randrange，
    无 rng → 首条。"""
    if not matched:
        return ""
    if len(matched) == 1:
        return _render_text(str(matched[0].get("text") or ""), ctx, map_def)
    rng = ctx.get("rng")
    if rng is not None and hasattr(rng, "choice"):
        try:
            return _render_text(str(rng.choice(matched).get("text") or ""), ctx, map_def)
        except Exception:
            pass
    if rng is not None and hasattr(rng, "randrange"):
        try:
            e = matched[rng.randrange(len(matched))]
            return _render_text(str(e.get("text") or ""), ctx, map_def)
        except Exception:
            pass
    return _render_text(str(matched[0].get("text") or ""), ctx, map_def)


# -------------------------------------------------------------------------------------
# 主入口一：环境文本泛暗示（R-23 / F-15，第一层漏斗）
# -------------------------------------------------------------------------------------
def ambient_context(ctx: Mapping[str, Any], map_def: object = None) -> str:
    """环境泛暗示文本（R-23 / F-15）：环境快照头 + 地图 lore.ambient[] 窗口匹配片段。

    入参:
      - ctx: 求值上下文（season/period/weather/rng/settings，见文件头）。
      - map_def: 当前地图（MapDef 或 raw dict；lore.ambient[] 经 raw 兜底读取，补白 2）。
    出参 str: `（{季节}·{时段}·{天气}）\\n{泛暗示正文}`；无快照 → 仅正文。
    核心逻辑:
      ① 环境快照头（R-05 展示口径，缺失键 "--"、全缺无头）；
      ② maps.json lore.ambient[] 逐条 window 匹配（条件表达式或 {season,period,weather}
         直接值形态，补白 2）→ 命中池 rng 确定性选择；
      ③ 无命中/无池 → 零暗示泛化池（R-07 / TC-09，绝无「此处有隐藏」措辞）。
      输出供 /调查 泛化文本 / 地图进入介绍 / 冒险日志环境段复用。
    """
    pool = _ambient_pool(map_def)
    matched = [e for e in pool if _window_ok(e.get("window"), ctx)]
    body = _pick_ambient(ctx, matched, map_def)
    if not body:
        body = _neutral_text(ctx)
    header = _env_header(ctx)
    return f"{header}\n{body}" if header else body


# -------------------------------------------------------------------------------------
# 主入口二：图鉴 lore 定向线索（R-24 / F-16，第二层漏斗）
# -------------------------------------------------------------------------------------
def lore_hint(ctx: Mapping[str, Any], category: str, ref_id: str,
              *, map_def: object = None) -> str:
    """图鉴 lore 定向线索（R-24 / F-16，第二层漏斗；R-25 不提前泄露下一层）。

    入参:
      - ctx: 求值上下文（codex_state/registry/codex/season/period/weather/rng）。
      - category: 分册名（monster/weapon/item）。
      - ref_id: 条目 id。
      - map_def: 可选当前地图（未 seen 泛化零暗示回落用）。
    出参 str: 定向线索文本——已见+传闻解锁 → 传闻段（「传闻：」行，缺省全 lore 行）；
      已见未解锁 → 基础段（unlock 阈值 + condition 同时满足的策略提示行，LC-01/LC-E）；
      未 seen / 无可见行 → 环境泛暗示（零暗示，不泄露名称与传闻）。
    核心逻辑: 三层分级（基础段 → 传闻段），任何一层不提前泄露下一层（R-25）。
    """
    rid = str(ref_id)
    if _seen_entry(ctx, category, rid) is None:
        return ambient_context(ctx, map_def)
    defn = _resolve_def(ctx, category, rid)
    lines = _lore_lines(defn)
    if _lore_unlocked_of(ctx, category, rid):
        rumors = _rumor_lines(lines)
        chosen = rumors if rumors else lines
        text = _join_desc(chosen, ctx, map_def)
        if text:
            return text
    base = _base_visible_lines(lines, ctx)
    if base:
        return _join_desc(base, ctx, map_def)
    return ambient_context(ctx, map_def)


def lore_view(ctx: Mapping[str, Any], category: str, ref_id: str) -> dict:
    """图鉴条目 lore 展示数据源（F-16 / R-25 不泄露）：lore_unlocked → 传闻正文，否则 None。

    入参:
      - ctx: 求值上下文（codex_state/registry）。
      - category: 分册名（monster/weapon/item）。
      - ref_id: 条目 id。
    出参 dict: {ok, unlocked, text, reason, category, ref_id}——reason ∈
      no_def（registry 无此条目）/ not_seen（未见，不泄露）/ locked（已见未解锁，
      不泄露）/ unlocked（已解锁，text=传闻正文）。
    核心逻辑: 定义解析 → 已见判定 → lore_unlocked 判定；仅 unlocked 时返回正文
      （「传闻：」行优先，缺省全 lore 行），其余一律 text=None（不泄露，R-25）。
    """
    rid = str(ref_id)
    defn = _resolve_def(ctx, category, rid)
    if defn is None:
        return {"ok": False, "unlocked": False, "text": None, "reason": "no_def",
                "category": category, "ref_id": rid}
    entry = _seen_entry(ctx, category, rid)
    if entry is None:
        return {"ok": True, "unlocked": False, "text": None, "reason": "not_seen",
                "category": category, "ref_id": rid}
    if not entry.get("lore_unlocked"):
        return {"ok": True, "unlocked": False, "text": None, "reason": "locked",
                "category": category, "ref_id": rid}
    lines = _lore_lines(defn)
    rumors = _rumor_lines(lines)
    text = _join_desc(rumors if rumors else lines, ctx, None)
    return {"ok": True, "unlocked": True, "text": text, "reason": "unlocked",
            "category": category, "ref_id": rid}


# -------------------------------------------------------------------------------------
# 主入口三：定向 lore 解锁接线（3f hidden_trigger 补白 5 / codex unlock_lore 缺口收口）
# -------------------------------------------------------------------------------------
def unlock_lore_wired(ctx: MutableMapping[str, Any], category: str,
                      ref_id: str) -> dict:
    """定向 lore 解锁接线（F-16 / R-15 图鉴 lore 补全）：写 codex_state lore_unlocked=true。

    入参:
      - ctx: 可变上下文（codex_state 写）。
      - category: 分册名（monster/weapon/item）。
      - ref_id: 条目 id。
    出参 dict: {ok, category, ref_id, unlocked, via}——via ∈ codex（经
      qbot_rpg.core.codex.unlock_lore 已提供接口）/ fallback（惰性 import 失败直写
      codex_state）；未 seen / 未知分册 → ok=False（不写入，不泄露）。
    核心逻辑: 惰性 import codex.unlock_lore 优先（真实签名已 read 核对，L201-213），
      import 失败 → 直写 codex_state[category][ref_id].lore_unlocked=true（仅已见条目）。
      消费接线（hidden_trigger.reveal_find lore_pending / 图鉴里程碑 / 100% 世界之书
      触发点）为登记补白交收口，由对应批次调用本函数。
    """
    rid = str(ref_id)
    via = "codex"
    try:
        from qbot_rpg.core.codex import unlock_lore as _unlock  # noqa: PLC0415
        res = _unlock(ctx, category, rid)
        if isinstance(res, Mapping) and res.get("ok"):
            return {"ok": True, "category": category, "ref_id": rid,
                    "unlocked": True, "via": via}
        return {"ok": False,
                "reason": res.get("reason") if isinstance(res, Mapping) else None,
                "category": category, "ref_id": rid, "unlocked": False, "via": via}
    except Exception:
        via = "fallback"
    # 惰性兜底：直写 codex_state（仅已见条目，不泄露）
    st = ctx.get("codex_state")
    if not isinstance(st, MutableMapping):
        st = {}
        ctx["codex_state"] = st
    cat = st.get(category)
    if not isinstance(cat, MutableMapping):
        cat = {}
        st[category] = cat
    entry = cat.get(rid)
    if not (isinstance(entry, Mapping) and entry.get("seen")):
        return {"ok": False, "reason": "not_seen_yet", "category": category,
                "ref_id": rid, "unlocked": False, "via": via}
    new_entry = dict(entry)
    new_entry["lore_unlocked"] = True
    cat[rid] = new_entry
    return {"ok": True, "category": category, "ref_id": rid,
            "unlocked": True, "via": via}
