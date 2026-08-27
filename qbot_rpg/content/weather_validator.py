"""天气引擎配置校验器 —— M3 批次2·路I（M41 校验器 V5-V8 接线 + 黄提示）。

依据：细化_2a4b_天气引擎 §8（V4-V8 硬校验 + 黄提示五条）+ m3_shared_contract §6.2
      （校验器 V1–V8 + 黄提示）/ §5.4（条件键三键）/ §6.1（消费方联动）
      + 细化_2a4c_时间天气接口（IF12 配置变更重排 / TC-17 V8 非法占位符）。
      （细化_2a4b 内实际小节：§3.3 覆盖池引用合法性、§6.2 校验器对齐表、§7 TC；
       文件头按任务口径标注 §8 = 校验器 + 黄提示。）

本文件 = M41 校验器 V5-V8 接线（纯函数，零 NoneBot，零 IO）：

  validate_weather(modules, cfg, report) -> None
    V5  地图 weather_pool（maps.json 每图顶层）元素 ∈ 默认池注册键（红拦）
    V6  消费方枚举引用（enemies special_actions 条件 / 采集点 weather_mods /
        lore 图鉴 condition 里的 [季节:X]/[时段:X]/[天气:X] 或 {var,...} 形态；
        param 非法枚举 → 红拦）
    V7  time_cycle.combat.weather_mult.mults 键 ∈ 注册天气集（红拦）
    V8  time_cycle.broadcast.template 占位符 ∈ {type,name,emoji,map}（红拦）
  黄提示（不拦截）：
    W1  season_days=365（全季节 1 天轮换）
    W2  period_minutes=1440（全时段 1 天轮换）
    W3  默认池 > 12 种（抽到单种概率很低）
    W4  池长度 1（单种池恒定：默认池 / 地图覆盖池）
    W5  配置了 time_cycle 但无任何消费方引用
    W6  池配置变更 → 周期重新铺排（对齐 IF12 / TC-16）

V1-V4（season_days≥1 / period_minutes≥30 / weather_minutes≥30 / 池非空键唯一）
已由 engine/worldtime.py validate_time_cycle 覆盖（M31 路C），本文件不重复。

【工程补白】（定稿/契约未显式定义处，显式标注供审查）：
  1. V6 消费方扫描范围（本路）：仅覆盖 enemies special_actions 条件 / 采集点
     （maps.json 每图 gather_points）weather_mods / enemies lore 图鉴 condition；
     其余消费方（怪物 spawn weather_weights 键、钓鱼 seasons/periods、事件/NPC/
     任务条件、king_event.weather 等）不在本路扫描范围，由后续收口接线补充。
  2. V5 注册键来源 = settings time_cycle.weather.default_pool（V4 已校验非空键唯一），
     缺省回退引擎内建 DEFAULT_POOL（与 worldtime.WorldTime.default_pool() 同源同口径）。
  3. W6 静态近似：纯函数校验器无法观测运行时配置编辑；以「显式配置的 default_pool
     键集合 ≠ 引擎内建 DEFAULT_POOL 键集合」近似「池配置变更」，提示周期重新铺排
     （对齐 TC-16 删除默认池天气场景；IF12 全字段重排的运行时热重载归 2a4c，本路不涉）。
  4. REGISTERED_KEYS 收口：优先 import engine/weather_conditions（M40 路H 落盘）；
     未落盘时本地镜像定义并注释收口对齐（三键值域与 worldtime SEASONS/PERIODS 同源）。
  5. report 鸭子类型：兼容 content/validator.py `_Checker._err/_warn`（主收口直传形态）、
     error/warning 方法形态、errors/warnings 列表形态、Mapping 键形态，四选一。

零 NoneBot import（契约 §八 4）；纯函数无 IO（同刻同参必同值）。
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Optional, Tuple

# REGISTERED_KEYS / SEASON_KEYS / PERIOD_KEYS / DEFAULT_POOL：
# 2026-08-26 G0 架构修复——content 层仅允许依赖 data，不得反向依赖 engine；
# 常量本地镜像（与 engine/weather_conditions.py / worldtime.py 同源，收口对齐见文件头补白 4）
SEASON_KEYS: Tuple[str, ...] = ("spring", "summer", "autumn", "winter")
PERIOD_KEYS: Tuple[str, ...] = ("dawn", "noon", "dusk", "night", "midnight")
REGISTERED_KEYS: dict = {"season": SEASON_KEYS, "period": PERIOD_KEYS, "weather": None}
DEFAULT_POOL = ("clear", "cloudy", "rain", "storm", "fog")  # 引擎内建默认天气池（seed 基准）

__all__ = ["validate_weather"]

# 广播模板合法占位符（细化_2a4c §1.2 / 定稿 L337：{type,name,emoji,map}）
ALLOWED_TEMPLATE_KEYS: frozenset = frozenset({"type", "name", "emoji", "map"})
# [季节:X] / [时段:X] / [天气:X] 字符串形态（契约 §5.4；容忍全角冒号）
_BRACKET_RE = re.compile(r"\[(季节|时段|天气)\s*[:：]\s*([^\]]+)\]")
_BRACKET_VAR: dict = {"季节": "season", "时段": "period", "天气": "weather"}
# 播报模板占位符 {X} 形态（X 不含花括号；细化_2a4c TC-17）
_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


# -------------------------------------------------------------------------------------
# 收集器鸭子类型（_Checker._err/_warn / error-warning 方法 / errors-warnings 列表 / Mapping 键）
# -------------------------------------------------------------------------------------
def _err(report: object, module: str, field: str, kind: str, **detail: object) -> None:
    """红拦收集器鸭子类型：① `_err(module, field, kind, **detail)`（validator._Checker 同签名）
    ② `error(...)` 方法 ③ `.errors` 列表 append dict ④ Mapping['errors'] 列表。"""
    if report is None:
        return
    fn = getattr(report, "_err", None)
    if not callable(fn):
        fn = getattr(report, "error", None)
    if callable(fn):
        fn(module, field, kind, **detail)
        return
    errors = getattr(report, "errors", None)
    if isinstance(errors, list):
        errors.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})
        return
    if isinstance(report, Mapping):
        errors = report.get("errors")
        if isinstance(errors, list):
            errors.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})


def _warn(report: object, module: str, field: str, kind: str, **detail: object) -> None:
    """黄提示收集器鸭子类型：① `_warn(module, field, kind, **detail)`（validator._Checker 同签名）
    ② `warning(...)` 方法 ③ `.warnings` 列表 append dict ④ Mapping['warnings'] 列表。"""
    if report is None:
        return
    fn = getattr(report, "_warn", None)
    if not callable(fn):
        fn = getattr(report, "warning", None)
    if callable(fn):
        fn(module, field, kind, **detail)
        return
    warnings = getattr(report, "warnings", None)
    if isinstance(warnings, list):
        warnings.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})
        return
    if isinstance(report, Mapping):
        warnings = report.get("warnings")
        if isinstance(warnings, list):
            warnings.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})


# -------------------------------------------------------------------------------------
# 注册天气集（V5/V6/V7 引用靶）
# -------------------------------------------------------------------------------------
def _registered_weather(cfg: Mapping[str, object]) -> List[str]:
    """注册天气集 = time_cycle.weather.default_pool 键列表；缺省回退引擎内建 DEFAULT_POOL。

    与 worldtime.WorldTime.default_pool() 同口径（V4 已保证非空键唯一；坏配置惰性回退）。
    """
    tc = cfg.get("time_cycle") if isinstance(cfg, Mapping) else None
    weather = tc.get("weather") if isinstance(tc, Mapping) else None
    pool = weather.get("default_pool") if isinstance(weather, Mapping) else None
    if isinstance(pool, (list, tuple)) and pool:
        return [str(k) for k in pool]
    return list(DEFAULT_POOL)


def _declared_enum(cfg: Mapping[str, object], section_key: str,
                   default: Tuple[str, ...]) -> Tuple[str, ...]:
    """声明枚举集（2026-08-26 拍板枚举可配 / 审查 M3 批次2 P1-3）：读
    cfg.time_cycle.<section_key>.enum（非空 string 数组 → tuple）；缺省/坏配置回退默认集。

    与 engine WorldTime._enum_field 同口径（V1b/V2b 已红拦非法 enum，这里只做惰性读取）。
    """
    tc = cfg.get("time_cycle") if isinstance(cfg, Mapping) else None
    sec = tc.get(section_key) if isinstance(tc, Mapping) else None
    ev = sec.get("enum") if isinstance(sec, Mapping) else None
    if isinstance(ev, (list, tuple)) and ev and all(isinstance(x, str) and x for x in ev):
        return tuple(ev)
    return default


# -------------------------------------------------------------------------------------
# V6 消费方条件扫描（enemies special_actions 条件 / lore 图鉴 condition）
# -------------------------------------------------------------------------------------
def _collect_weather_conditions(
    obj: object,
    field: str,
    out: List[Tuple[str, Mapping[str, object]]],
) -> None:
    """递归收集容器内三键天气条件引用（契约 §5.4 形态）。

    仅收集 var ∈ REGISTERED_KEYS（season/period/weather）的 {var,...} dict，与
    [季节:X]/[时段:X]/[天气:X] 字符串形态；其余条件键（其它条件引擎）不属本路扫描范围
    （文件头补白 1）。非容器值（数值等）原样跳过。
    """
    if isinstance(obj, Mapping):
        var = obj.get("var")
        if isinstance(var, str) and var in REGISTERED_KEYS:
            out.append((field, obj))
        for k, v in obj.items():
            _collect_weather_conditions(v, f"{field}.{k}", out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _collect_weather_conditions(v, f"{field}.{i}", out)
    elif isinstance(obj, str):
        for m in _BRACKET_RE.finditer(obj):
            out.append((field, {"var": _BRACKET_VAR[m.group(1)], "op": "eq", "param": m.group(2)}))


def _check_condition(
    cond: Mapping[str, object],
    field: str,
    module: str,
    report: object,
    reg: Iterable[str],
    season_keys: Tuple[str, ...] = SEASON_KEYS,
    period_keys: Tuple[str, ...] = PERIOD_KEYS,
) -> None:
    """单条三键条件枚举校验（V6）：param 非法枚举 → 红拦。

    rule 命名对齐 M40 weather_conditions.validate_condition_keys（season_enum_invalid /
    period_enum_invalid / weather_key_not_registered / param_invalid），消费方一致口径。
    season_keys / period_keys: 声明枚举集（读 cfg.time_cycle.season.enum / period.enum，
    审查 M3 批次2 P1-3——比对目标 = 声明集，自定义枚举内容包的合法条件不再误红拦）。
    """
    if not isinstance(cond, Mapping):
        _err(report, module, field, "V6", rule="condition_not_object",
             got=type(cond).__name__, msg="天气条件要填对象 {var,op,param}")
        return
    var = cond.get("var")
    if var not in REGISTERED_KEYS:
        return  # 非三键条件（其它条件引擎），不属本路扫描范围
    param = cond.get("param")
    if not isinstance(param, str) or not param:
        _err(report, module, field, "V6", rule="param_invalid", param=param,
             msg="天气条件参数要填字符串枚举值")
        return
    if var == "season" and param not in season_keys:
        _err(report, module, field, "V6", rule="season_enum_invalid", param=param,
             allowed=list(season_keys),
             msg="季节 %r 不认识，只有 春夏秋冬（%s）" % (param, "/".join(season_keys)))
        return
    if var == "period" and param not in period_keys:
        _err(report, module, field, "V6", rule="period_enum_invalid", param=param,
             allowed=list(period_keys),
             msg="时段 %r 不认识，只有 晨午昏夜午夜（%s）" % (param, "/".join(period_keys)))
        return
    if var == "weather" and param not in reg:
        _err(report, module, field, "V6", rule="weather_key_not_registered", param=param,
             registered=sorted(reg),
             msg="天气 %r 没有在默认天气池里注册（已注册：%s）"
                 % (param, "/".join(sorted(reg))))


def _iter_map_entries(maps: object):
    """maps 模块形态归一：list（标准，fixtures 形态）→ (idx, entry)；dict（id→entry）→ (id, entry)。"""
    if isinstance(maps, (list, tuple)):
        for idx, entry in enumerate(maps):
            yield idx, entry
    elif isinstance(maps, Mapping):
        for mid, entry in maps.items():
            yield mid, entry


# -------------------------------------------------------------------------------------
# 主入口（M41 V5-V8 接线 + 黄提示；纯函数，零 IO）
# -------------------------------------------------------------------------------------
def validate_weather(
    modules: Optional[Mapping[str, object]],
    cfg: Optional[Mapping[str, object]],
    report: object,
) -> None:
    """M41 校验器 V5-V8 接线 + 黄提示（纯函数，零副作用）。

    modules: 模块名（无 .json 后缀）→ parsed JSON（含 maps/enemies）；None/缺省 = {}。
    cfg:     settings dict（含可选 time_cycle 段；V5 注册键 / V7 mults / V8 template 读取处）。
    report:  收集器鸭子类型（`_Checker._err/_warn` / error-warning 方法 / errors-warnings 列表 /
             Mapping 键，四选一；None = 静默收集）。
    红拦均带人话报错 detail["msg"]，供命令层直接拼用户文案（对齐 validate_time_cycle 口径）。
    """
    if not isinstance(modules, Mapping):
        modules = {}
    if not isinstance(cfg, Mapping):
        cfg = {}
    reg = _registered_weather(cfg)
    # 声明枚举集（2026-08-26 拍板可配 / 审查 M3 批次2 P1-3）：V6 比对目标 = 声明集
    season_keys = _declared_enum(cfg, "season", SEASON_KEYS)
    period_keys = _declared_enum(cfg, "period", PERIOD_KEYS)
    tc = cfg.get("time_cycle")
    tc_ok = isinstance(tc, Mapping)
    consumer_refs = 0  # W5 无消费方引用计数（V5 池元素 + V6 条件/采集 + V7 mults 键）

    # ---- 黄提示（settings 级，不拦截）----
    if tc_ok:
        season = tc.get("season")  # type: ignore[attr-defined]
        if isinstance(season, Mapping) and season.get("season_days") == 365:
            _warn(report, "settings", "time_cycle.season.season_days", "Y",
                  rule="season_days_full_year", days=365,
                  msg="季节天数=365：每个季节一整年才轮换一次（全季节 1 天轮换）")
        period = tc.get("period")  # type: ignore[attr-defined]
        if isinstance(period, Mapping) and period.get("period_minutes") == 1440:
            _warn(report, "settings", "time_cycle.period.period_minutes", "Y",
                  rule="period_minutes_full_day", minutes=1440,
                  msg="时段分钟=1440（24 小时）：全天只有 1 个时段轮换")
        weather = tc.get("weather")  # type: ignore[attr-defined]
        if isinstance(weather, Mapping) and isinstance(weather.get("default_pool"), (list, tuple)):
            pool = weather["default_pool"]
            if len(pool) > 12:
                _warn(report, "settings", "time_cycle.weather.default_pool", "Y",
                      rule="pool_too_many", size=len(pool),
                      msg="默认天气池超过 12 种：抽到单种天气的概率很低")
            if len(pool) == 1:
                _warn(report, "settings", "time_cycle.weather.default_pool", "Y",
                      rule="pool_single_constant", size=1,
                      msg="默认天气池只有 1 种：天气永远不变（单种池恒定）")
        if isinstance(weather, Mapping) and "default_pool" in weather:
            pool = weather["default_pool"]
            if isinstance(pool, (list, tuple)) and pool and \
                    {str(k) for k in pool} != set(DEFAULT_POOL):
                _warn(report, "settings", "time_cycle.weather.default_pool", "Y",
                      rule="pool_config_reorder",
                      msg="默认天气池已变更：天气序列从变更时刻起重新铺排"
                          "（时间配置已变更，周期重新铺排）")

    # ---- V5 地图 weather_pool（maps.json 每图顶层；缺省/空数组=默认池，契约 §6.1）----
    # ---- V6 采集点 weather_mods（maps.json 每图 gather_points；R25 / TC-11）----
    maps = modules.get("maps")
    if maps is not None:
        for idx, entry in _iter_map_entries(maps):
            if not isinstance(entry, Mapping):
                continue
            base = f"maps.{idx}"
            # V5：地图 weather_pool 覆盖池
            pool = entry.get("weather_pool")
            if pool is not None:
                if not isinstance(pool, (list, tuple)):
                    _err(report, "maps", f"{base}.weather_pool", "V5",
                         rule="pool_type", got=type(pool).__name__,
                         msg="地图 weather_pool 要填数组（缺省/空数组=默认池）")
                elif pool:
                    if len(pool) == 1:
                        _warn(report, "maps", f"{base}.weather_pool", "Y",
                              rule="map_pool_single_constant", size=1,
                              msg="这张图覆盖池只有 1 种：该图天气永远不变（恒定）")
                    if len(pool) > 12:
                        _warn(report, "maps", f"{base}.weather_pool", "Y",
                              rule="map_pool_too_many", size=len(pool),
                              msg="这张图覆盖池超过 12 种：抽到单种天气的概率很低")
                    for i, k in enumerate(pool):
                        consumer_refs += 1
                        if not isinstance(k, str) or k not in reg:
                            _err(report, "maps", f"{base}.weather_pool.{i}", "V5",
                                 rule="pool_key_not_registered", key=k, registered=sorted(reg),
                                 map_id=entry.get("id") or entry.get("name") or idx,
                                 msg="地图 %s 的天气 %r 没有在默认天气池里注册（已注册：%s）"
                                     % (entry.get("id") or entry.get("name") or idx, k,
                                        "/".join(sorted(reg))))
            # V6：采集点 weather_mods[].weather ∈ 注册天气集
            gps = entry.get("gather_points")
            if isinstance(gps, (list, tuple)):
                for gi, gp in enumerate(gps):
                    if not isinstance(gp, Mapping):
                        continue
                    wms = gp.get("weather_mods")
                    if not isinstance(wms, (list, tuple)):
                        continue
                    for mi, wm in enumerate(wms):
                        if not isinstance(wm, Mapping) or "weather" not in wm:
                            continue
                        wk = wm["weather"]
                        consumer_refs += 1
                        if not isinstance(wk, str) or wk not in reg:
                            _err(report, "maps",
                                 f"{base}.gather_points.{gi}.weather_mods.{mi}.weather",
                                 "V6", rule="gather_weather_key_not_registered",
                                 weather=wk, registered=sorted(reg),
                                 msg="采集点天气 %r 没有在默认天气池里注册（已注册：%s）"
                                     % (wk, "/".join(sorted(reg))))

    # ---- V6 消费方条件引用（enemies special_actions 条件 + lore 图鉴 condition）----
    enemies = modules.get("enemies")
    if isinstance(enemies, (list, tuple)):
        for ei, entry in enumerate(enemies):
            if not isinstance(entry, Mapping):
                continue
            base = f"enemies.{ei}"
            sas = entry.get("special_actions")
            if isinstance(sas, (list, tuple)):
                for si, sa in enumerate(sas):
                    if not isinstance(sa, Mapping):
                        continue
                    refs: List[Tuple[str, Mapping[str, object]]] = []
                    _collect_weather_conditions(sa, f"{base}.special_actions.{si}", refs)
                    for field, cond in refs:
                        consumer_refs += 1
                        _check_condition(cond, field, "enemies", report, reg,
                                         season_keys, period_keys)
            lore = entry.get("lore")
            if isinstance(lore, (list, tuple)):
                for li, l in enumerate(lore):
                    if not isinstance(l, Mapping) or "condition" not in l:
                        continue
                    refs = []
                    _collect_weather_conditions(l["condition"],
                                                f"{base}.lore.{li}.condition", refs)
                    for field, cond in refs:
                        consumer_refs += 1
                        _check_condition(cond, field, "enemies", report, reg,
                                         season_keys, period_keys)

    # ---- V7 combat.weather_mult.mults 键 ∈ 注册天气集（settings time_cycle.combat 段）----
    if tc_ok:
        combat = tc.get("combat")  # type: ignore[attr-defined]
        if isinstance(combat, Mapping):
            wm = combat.get("weather_mult")
            if wm is not None:
                if not isinstance(wm, Mapping):
                    _err(report, "settings", "time_cycle.combat.weather_mult", "V7",
                         rule="weather_mult_not_object", got=type(wm).__name__,
                         msg="combat.weather_mult 要填对象 {enabled, mults}")
                else:
                    mults = wm.get("mults")
                    if mults is not None:
                        if not isinstance(mults, Mapping):
                            _err(report, "settings", "time_cycle.combat.weather_mult.mults",
                                 "V7", rule="mults_not_object", got=type(mults).__name__,
                                 msg="weather_mult.mults 要填对象 {天气:倍率}")
                        else:
                            for k in mults:
                                consumer_refs += 1
                                if k not in reg:
                                    _err(report, "settings",
                                         f"time_cycle.combat.weather_mult.mults.{k}", "V7",
                                         rule="mults_key_not_registered", key=k,
                                         registered=sorted(reg),
                                         msg="战斗天气修正键 %r 没有在默认天气池里注册"
                                             "（已注册：%s）" % (k, "/".join(sorted(reg))))

    # ---- V8 broadcast.template 占位符 ∈ {type,name,emoji,map}（细化_2a4c TC-17）----
    if tc_ok:
        broadcast = tc.get("broadcast")  # type: ignore[attr-defined]
        if isinstance(broadcast, Mapping) and "template" in broadcast:
            tpl = broadcast["template"]
            if not isinstance(tpl, str):
                _err(report, "settings", "time_cycle.broadcast.template", "V8",
                     rule="template_type", got=type(tpl).__name__,
                     msg="broadcast.template 要填字符串（缺省 {emoji} {name}）")
            elif tpl:
                for m in _TEMPLATE_RE.finditer(tpl):
                    token = m.group(1)
                    if token not in ALLOWED_TEMPLATE_KEYS:
                        _err(report, "settings", "time_cycle.broadcast.template", "V8",
                             rule="template_placeholder_invalid", placeholder=token,
                             allowed=sorted(ALLOWED_TEMPLATE_KEYS),
                             msg="播报模板占位符 {%s} 不认识，只能用 {type}/{name}/{emoji}/{map}"
                                 % token)

    # ---- 黄提示：配置了 time_cycle 但无任何消费方引用（不拦截）----
    if tc_ok and consumer_refs == 0:
        _warn(report, "settings", "time_cycle", "Y", rule="no_consumer_refs",
              msg="已配置 time_cycle，但没有任何内容引用季节/时段/天气（消费方引用为空）")
