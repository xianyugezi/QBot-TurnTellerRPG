"""time_cycle / weather_pool 配置校验（M31/M41 · content 层承载）。

依据：细化_2a4a（§1.3 可配项）+ 细化_2a4b（§8 V1-V4）+ m3_shared_contract §5.2/§6.2。

2026-08-26 G0 架构门禁修复：校验函数从 engine/worldtime.py 迁移至 content 层——
依赖矩阵 §1.4（content 仅允许依赖 data），content 校验器不得反向依赖 engine；
engine/worldtime.py 保留同名函数（世界侧可直接用），本模块为 check_pack 收口接入点。
"""

from __future__ import annotations

from typing import Mapping


def validate_time_cycle(settings: Mapping[str, object], report: object) -> None:
    """time_cycle 段校验（M31 · 契约 §6.2 V1~V4 + enabled 类型）。

    settings: 完整 settings dict（可含可选 time_cycle 段；缺省整段 = 全默认，零红拦）。
    report:   收集器（二选一）——
              a) 提供 `_err(module, field, kind, **detail)`（与 content/validator.py `_Checker` 同签名）；
              b) 提供 `errors: list`（追加 {"module","field","kind","detail"} dict）。
    红拦均带人话报错 detail["msg"]（如「季节天数要填整数，最少 1 天」），供命令层直接拼用户文案。
    """
    if not isinstance(settings, Mapping):
        return
    tc = settings.get("time_cycle")
    if not isinstance(tc, Mapping):
        return  # 缺省整段 = 全默认，零红拦

    # enabled 布尔类型（契约 §5.2 / 细化_2a4a §1.3）
    if "enabled" in tc and not isinstance(tc["enabled"], bool):
        _emit(report, "settings", "time_cycle.enabled", "enabled_type",
              rule="enabled_type", got=tc["enabled"],
              msg="time_cycle.enabled 要填 true 或 false")

    # V1 季节天数 ≥1 整数
    season = tc.get("season")
    if isinstance(season, Mapping) and "season_days" in season:
        v = season["season_days"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            _emit(report, "settings", "time_cycle.season.season_days", "V1",
                  rule="season_days_min", minimum=1, got=v,
                  msg="季节天数要填整数，最少 1 天")

    # V1b 枚举开放可配（用户拍板 2026-08-26 / 时间天气定稿 L44）：season.enum 非空 string[] 硬拦
    if isinstance(season, Mapping) and "enum" in season:
        ev = season["enum"]
        if not (isinstance(ev, (list, tuple)) and ev and all(isinstance(x, str) and x for x in ev)):
            _emit(report, "settings", "time_cycle.season.enum", "V1b",
                  rule="season_enum_invalid", got=ev,
                  msg="季节枚举要填非空字符串数组（如 [\"spring\",\"summer\",\"autumn\",\"winter\"]）")
        elif len(ev) == 1:
            _emit(report, "settings", "time_cycle.season.enum", "Y1",
                  rule="season_enum_singleton", got=ev,
                  msg="季节枚举只有 1 种（恒定无季节轮换）——只提示，如需固定季节可忽略")

    # V2 时段分钟 ≥30 整数
    period = tc.get("period")
    if isinstance(period, Mapping) and "period_minutes" in period:
        v = period["period_minutes"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 30:
            _emit(report, "settings", "time_cycle.period.period_minutes", "V2",
                  rule="period_minutes_min", minimum=30, got=v,
                  msg="时段分钟要填整数，最少 30 分钟")

    # V2b 枚举开放可配（用户拍板 2026-08-26 / 时间天气定稿 L44）：period.enum 非空 string[] 硬拦
    if isinstance(period, Mapping) and "enum" in period:
        ev = period["enum"]
        if not (isinstance(ev, (list, tuple)) and ev and all(isinstance(x, str) and x for x in ev)):
            _emit(report, "settings", "time_cycle.period.enum", "V2b",
                  rule="period_enum_invalid", got=ev,
                  msg="时段枚举要填非空字符串数组（如 [\"dawn\",\"noon\",\"dusk\",\"night\",\"midnight\"]）")
        elif len(ev) == 1:
            _emit(report, "settings", "time_cycle.period.enum", "Y2",
                  rule="period_enum_singleton", got=ev,
                  msg="时段枚举只有 1 种（恒定无时段轮换）——只提示，如需固定时段可忽略")

    # V3 天气分钟 ≥30 整数
    weather = tc.get("weather")
    if isinstance(weather, Mapping) and "weather_minutes" in weather:
        v = weather["weather_minutes"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 30:
            _emit(report, "settings", "time_cycle.weather.weather_minutes", "V3",
                  rule="weather_minutes_min", minimum=30, got=v,
                  msg="天气分钟要填整数，最少 30 分钟")

    # V4 默认天气池：非空数组 + 键唯一
    if isinstance(weather, Mapping) and "default_pool" in weather:
        pool = weather["default_pool"]
        if not isinstance(pool, (list, tuple)):
            _emit(report, "settings", "time_cycle.weather.default_pool", "V4",
                  rule="pool_type", got=pool,
                  msg="默认天气池要填数组")
        elif len(pool) == 0:
            _emit(report, "settings", "time_cycle.weather.default_pool", "V4",
                  rule="pool_empty", got=pool,
                  msg="默认天气池至少要 1 种天气")
        else:
            seen: dict = {}
            for i, k in enumerate(pool):
                if not isinstance(k, str):
                    _emit(report, "settings", f"time_cycle.weather.default_pool.{i}", "V4",
                          rule="pool_key_type", got=k,
                          msg="默认天气池的天气键要填字符串")
                elif k in seen:
                    _emit(report, "settings", f"time_cycle.weather.default_pool.{i}", "V4",
                          rule="pool_key_dup", key=k,
                          msg=f"默认天气池天气键重复了：{k}")
                else:
                    seen[k] = i



def validate_weather_pool(cfg: Mapping[str, object], report: object) -> None:
    """默认天气池 V4 校验（细化_2a4b §1.2 R3/R4 + m3_shared_contract §6.2 V4）。

    独立入口供主 agent 收口接入 check_pack（与 validate_time_cycle 并存：后者校验「字符串池」形态的
    time_cycle 段；本函数按细化_2a4b §1.2 的 {key,name,emoji} 对象形态红拦，与 R3/R4 逐条对齐）：
      - default_pool 非空（至少 1 种天气，删到 0 硬拦，R4）；
      - 键唯一（key 全池唯一，R3）；
      - 键 + 中文名齐全（key / name 任一缺失或非字符串红拦，R3）。
    cfg:    完整 settings dict（可含 time_cycle.weather.default_pool；缺省段/缺字段 = 框架默认，零红拦）。
    report: 收集器（二选一）——a) `_err(module, field, kind, **detail)`（与 content/validator.py
            `_Checker` 同签名）；b) `errors: list`（追加 {"module","field","kind","detail"} dict）。
    红拦均带人话报错 detail["msg"]（如「天气『雪』缺中文名 name」），供命令层直接拼用户文案。
    纯函数，零 IO，零 NoneBot。
    """
    if not isinstance(cfg, Mapping):
        return
    tc = cfg.get("time_cycle")
    if not isinstance(tc, Mapping):
        return
    weather = tc.get("weather")
    if not isinstance(weather, Mapping) or "default_pool" not in weather:
        return  # 缺省段/缺字段 = 用框架默认，零红拦
    pool = weather["default_pool"]
    base = "time_cycle.weather.default_pool"
    if not isinstance(pool, (list, tuple)):
        _emit(report, "settings", base, "V4", rule="pool_type", got=pool,
              msg="默认天气池要填数组")
        return
    if len(pool) == 0:
        _emit(report, "settings", base, "V4", rule="pool_empty", got=pool,
              msg="默认天气池至少要 1 种天气")
        return
    seen: dict = {}
    for i, entry in enumerate(pool):
        field = f"{base}.{i}"
        if not isinstance(entry, Mapping):
            _emit(report, "settings", field, "V4", rule="pool_entry_type", got=entry,
                  msg=f"默认天气池第 {i} 项要填对象（含 key/name）")
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            _emit(report, "settings", field, "V4", rule="pool_key_missing", got=key,
                  msg="默认天气池天气条目缺 key（英文小写机器键）")
        elif key in seen:
            _emit(report, "settings", field, "V4", rule="pool_key_dup", key=key,
                  msg=f"默认天气池天气键重复了：{key}")
        else:
            seen[key] = i
        name = entry.get("name")
        label = key if isinstance(key, str) and key else f"第 {i} 项"
        if not isinstance(name, str) or not name:
            _emit(report, "settings", field, "V4", rule="pool_name_missing", key=key,
                  msg=f"天气『{label}』缺中文名 name")


def _emit(report: object, module: str, field: str, kind: str, **detail: object) -> None:
    """向 report 追加一条红拦：优先 _err(module, field, kind, **detail)；否则 `.errors` 列表 append dict。

    兼容三种收集器形态：① 带 `_err` 方法（content/validator.py `_Checker` 同签名）；
    ② 带 `.errors` 列表属性；③ 带 `errors` 键的 Mapping（如 {"errors": []}）。"""
    if report is None:
        return
    err = getattr(report, "_err", None)
    if callable(err):
        err(module, field, kind, **detail)
        return
    errors = getattr(report, "errors", None)
    if isinstance(errors, list):
        errors.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})
        return
    if isinstance(report, Mapping):
        errors = report.get("errors")
        if isinstance(errors, list):
            errors.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})

