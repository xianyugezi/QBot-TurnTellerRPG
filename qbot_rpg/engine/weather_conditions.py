"""条件键三键求值纯模块 —— M3 批次2·路H（M40 条件键三键注册）：[季节:X] / [时段:X] / [天气:X]。

依据：细化_2a4b_天气引擎.md（§4 权重修正 / §5 [天气:X] 条件判断 R28~R32）
      + 细化_2a4c_时间天气接口.md（§2 条件键接入：2.1 注册 / 2.2 消费方 / 2.3 V6 校验）
      + m3_shared_contract §5.4（条件键三键）/ §6.1（消费方联动）/ §八 铁律（8 每功能可追溯）。

本文件 = M40 三键注册的「求值函数 + 注册表 + 校验器」纯模块：
  eval_condition(cond, ctx) -> bool      三键求值（fail-safe，不抛错）
  REGISTERED_KEYS                         三键值域注册表（供校验器 V6 / 条件编辑器）
  validate_condition_keys(cond, report)   条件表达式枚举校验（V6 消费方枚举引用红拦）

三键语义（契约 §5.4 / 2a4c §2.1 / 细化_2a4b §5）：
  {var:"season",  op:"eq", param:X}  [季节:X]  X ∈ 四季固定枚举；季节为全局值
  {var:"period",  op:"eq", param:X}  [时段:X]  X ∈ 五时段固定枚举；时段为全局值
  {var:"weather", op:"eq", param:X}  [天气:X]  X ∈ 注册天气集（内容包自定义）；按玩家当前所在图取值
  op 兼容 eq / ==（等价于 param == 当前值 ? true : false，2a4c §2.1 L100）；
  value 键不参与（2a4c §2.1 L100「eq+param 判定」）；简写 {var, param:X} 求值等价
  （op 缺省按 eq，对齐 2a4c TC-18「简写与完整形等价」）。

【工程补白】（定稿/契约未显式定义处，显式标注供审查）：
  1. 季节/时段取值双通道：ctx 提供 worldtime 实例（供 IF02 season_now / IF03 period_now /
     IF04 weather_now）或直接提供 season_now/period_now 值（字符串）。直接值键优先于
     worldtime 实例——方便消费方/测试在无完整时钟时注入确定值。
  2. 天气取值：ctx["worldtime"].weather_now(ctx["map_id"])（IF04 语义，上下文绑定，
     2a4c §2.1 L100）；亦接受 ctx["weather_now"] 直接值（字符串，优先）。weather_now
     为批次 2 IF08 抽签落地后的 WorldTime 方法——本模块按鸭子类型调用（缺该方法 /
     缺 map_id → fail-safe False）。ctx["now"]（可选，UTC+8 秒级时间戳）转发给
     worldtime 查询方法（IF02~IF04 now 参数，缺省 = 当前）。
  3. 求值失败默认不满足（fail-safe）：未知 var / op 非法 / param 非法枚举 / 上下文
     无法取值 → 一律 False，不抛错（对齐 2a1d LC-D「求值失败默认不满足」）。
  4. 天气键值域动态（内容包自定义）：REGISTERED_KEYS["weather"] = None 表示值域依赖
     default_pool 注册键，由收口在接入 check_pack 时经 registered_weather 注入校验；
     本模块不内置天气集合（细化_2a4b R1/R6）。求值侧仅做字符串相等比较，键合法性
     归校验器。
  5. 条件引擎正式接线：本路提供求值函数 + 注册表 + 校验器；实际条件引擎（既有
     {var,op,value,param} 统一求值链）的三键注册/求值接入由收口完成——消费方
     （任务/NPC/副本事件/成就/图鉴）引用三键即生效，零新增机制（契约 §八 铁律 7）。

铁律：零 NoneBot import（契约 §八 4）；纯函数无 IO（同刻同参必同值）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Tuple

from qbot_rpg.engine.worldtime import PERIODS, SEASONS

__all__ = [
    "SEASON_KEYS",
    "PERIOD_KEYS",
    "REGISTERED_KEYS",
    "eval_condition",
    "validate_condition_keys",
]

# -------------------------------------------------------------------------------------
# 三键值域：季节/时段固定枚举（与 worldtime.SEASONS/PERIODS 同源，单口登记防碎片化）
# -------------------------------------------------------------------------------------
SEASON_KEYS: tuple = SEASONS  # ("spring","summer","autumn","winter")
PERIOD_KEYS: tuple = PERIODS  # ("dawn","noon","dusk","night","midnight")

# 三键注册表（契约 §5.4 / 2a4c §2.1 注册 3 行；供校验器 V6 与条件编辑器）：
#   weather 值域动态（内容包 default_pool 注册键）→ None 表示由收口经 registered_weather 注入
REGISTERED_KEYS: dict = {
    "season": SEASON_KEYS,
    "period": PERIOD_KEYS,
    "weather": None,
}

# 运算符白名单：eq / ==（2a4c §2.1「op 用 eq」；== 为兼容别名，求值等价）
_KNOWN_OPS: tuple = ("eq", "==")


# -------------------------------------------------------------------------------------
# 三键求值（fail-safe：任何异常形态 → False，不抛错）
# -------------------------------------------------------------------------------------
def eval_condition(cond: object, ctx: object) -> bool:
    """三键求值：{var:"season"|"period"|"weather", op:"eq"|"==", param:X} -> bool。

    参数类型放宽为 object（fail-safe 契约）：非 Mapping / 异常形态一律 False 不抛错。

    cond: 条件表达式（三键完整形；value 键不参与，2a4c §2.1 L100；op 缺省按 eq）。
    ctx:  求值上下文（见文件头补白）——season_now / period_now / weather_now 直接值
          （字符串，优先），或 worldtime 实例（供 season_now()/period_now()/
          weather_now(map_id)）；weather 另需 map_id（玩家当前所在图）；now（可选）
          转发给 worldtime 查询方法。
    返回：未知 var / op 非法 / param 非法 / 上下文无法取值 → False（fail-safe，不抛错）。
    """
    if not isinstance(cond, Mapping) or not isinstance(ctx, Mapping):
        return False
    var = cond.get("var")
    if var not in REGISTERED_KEYS:
        return False
    op = cond.get("op", "eq")
    if op not in _KNOWN_OPS:
        return False
    param = cond.get("param")
    # 枚举开放可配（用户拍板 2026-08-26）：ctx 可注入 season_keys/period_keys（内容包自定义完整枚举集），
    # 缺省模块级 SEASON_KEYS/PERIOD_KEYS
    _sk = ctx.get("season_keys")
    _pk = ctx.get("period_keys")
    season_keys: Tuple[str, ...] = tuple(_sk) if isinstance(_sk, (tuple, list)) else SEASON_KEYS
    period_keys: Tuple[str, ...] = tuple(_pk) if isinstance(_pk, (tuple, list)) else PERIOD_KEYS
    if var == "season":
        if not isinstance(param, str) or param not in season_keys:
            return False
        return _season_now(ctx) == param
    if var == "period":
        if not isinstance(param, str) or param not in period_keys:
            return False
        return _period_now(ctx) == param
    # var == "weather"：X ∈ 注册天气集；值域动态 → 求值侧仅字符串相等比较（键合法性归校验器）
    if not isinstance(param, str) or not param:
        return False
    return _weather_now(ctx) == param


def _now_of(ctx: Mapping[str, Any]) -> Optional[int]:
    """ctx 注入的 UTC+8 时间戳（缺省 None → worldtime 取当前）。"""
    n = ctx.get("now")
    return n if isinstance(n, int) else None


def _season_now(ctx: Mapping[str, Any]) -> Optional[str]:
    """当前季节（全局值，IF02）：直接值键 season_now 优先 → worldtime.season_now(now)。"""
    v = ctx.get("season_now")
    if isinstance(v, str):
        return v
    fn = getattr(ctx.get("worldtime"), "season_now", None)
    if not callable(fn):
        return None
    try:
        now = _now_of(ctx)
        v = fn() if now is None else fn(now)
    except Exception:
        return None  # fail-safe：worldtime 异常 → 无值 → 不满足
    return v if isinstance(v, str) else None


def _period_now(ctx: Mapping[str, Any]) -> Optional[str]:
    """当前时段（全局值，IF03）：直接值键 period_now 优先 → worldtime.period_now(now)。"""
    v = ctx.get("period_now")
    if isinstance(v, str):
        return v
    fn = getattr(ctx.get("worldtime"), "period_now", None)
    if not callable(fn):
        return None
    try:
        now = _now_of(ctx)
        v = fn() if now is None else fn(now)
    except Exception:
        return None
    return v if isinstance(v, str) else None


def _weather_now(ctx: Mapping[str, Any]) -> Optional[str]:
    """当前图天气（上下文绑定，IF04）：weather_now 直接值优先 → worldtime.weather_now(map_id)。"""
    v = ctx.get("weather_now")
    if isinstance(v, str):
        return v
    fn = getattr(ctx.get("worldtime"), "weather_now", None)
    map_id = ctx.get("map_id")
    if not callable(fn) or not isinstance(map_id, str) or not map_id:
        return None
    try:
        now = _now_of(ctx)
        v = fn(map_id) if now is None else fn(map_id, now)
    except Exception:
        return None
    return v if isinstance(v, str) else None


# -------------------------------------------------------------------------------------
# 校验器（契约 §6.2 V6 消费方枚举引用 / 2a1d V-4Z 枚举越界硬拦；供收口接入 check_pack）
# -------------------------------------------------------------------------------------
def _emit(report: object, module: str, field: str, kind: str, **detail: object) -> None:
    """向 report 追加一条红拦：优先 _err(module, field, kind, **detail)（validator._Checker
    同签名）；其次 .error(...)；其次 .errors 列表 append dict；其次 Mapping["errors"]。"""
    if report is None:
        return
    err = getattr(report, "_err", None)
    if callable(err):
        err(module, field, kind, **detail)
        return
    err = getattr(report, "error", None)
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


def validate_condition_keys(
    cond: object,
    report: object,
    registered_weather: Optional[Iterable[str]] = None,
) -> None:
    """三键条件表达式枚举校验（契约 §6.2 V6 / 2a1d V-4Z）。

    cond: 条件表达式 {var, op, param}（三键完整形）；也接受列表（多条件 AND，2a1d LC-C）
          逐项校验。
    report: 收集器（鸭子类型，见 _emit；收口时直传 validator._Checker 实例）。
    registered_weather: 注册天气集（default_pool keys 可迭代）；None = 收口未注入 →
            天气键值域校验跳过（值域依赖内容包注册集，2a1d LC-D 不崩）；季节/时段
            固定枚举恒校验。
    红拦（error）：var 不在三键 / op 非 eq/== / param 非字符串或非法枚举 /（注入时）
    weather 键不在注册天气集。均带人话 msg，供命令层直接拼用户文案。
    """
    if isinstance(cond, (list, tuple)):
        for item in cond:
            validate_condition_keys(item, report, registered_weather)
        return
    if not isinstance(cond, Mapping):
        _emit(report, "condition", "condition", "V6",
              rule="condition_not_object", got=type(cond).__name__,
              msg="条件表达式要填对象 {var,op,param}")
        return
    var = cond.get("var")
    if var not in REGISTERED_KEYS:
        _emit(report, "condition", "condition.var", "V6",
              rule="var_not_registered", var=var,
              allowed=sorted(REGISTERED_KEYS),
              msg="条件变量键 %r 不认识，只有 季节/时段/天气（season/period/weather）" % (var,))
        return
    op = cond.get("op")
    if op not in _KNOWN_OPS:
        _emit(report, "condition", "condition.op", "V6",
              rule="op_not_eq", op=op, allowed=list(_KNOWN_OPS),
              msg="季节/时段/天气条件只支持 eq 等于判定（op 填 eq）")
        return
    param = cond.get("param")
    if not isinstance(param, str) or not param:
        _emit(report, "condition", "condition.param", "V6",
              rule="param_invalid", param=param,
              msg="条件参数要填字符串枚举值")
        return
    if var == "season" and param not in SEASON_KEYS:
        _emit(report, "condition", "condition.param", "V6",
              rule="season_enum_invalid", param=param, allowed=list(SEASON_KEYS),
              msg="季节 %r 不认识，只有 春夏秋冬（%s）" % (param, "/".join(SEASON_KEYS)))
        return
    if var == "period" and param not in PERIOD_KEYS:
        _emit(report, "condition", "condition.param", "V6",
              rule="period_enum_invalid", param=param, allowed=list(PERIOD_KEYS),
              msg="时段 %r 不认识，只有 晨午昏夜午夜（%s）" % (param, "/".join(PERIOD_KEYS)))
        return
    if var == "weather":
        if registered_weather is None:
            return  # 值域依赖内容包注册集，收口未注入 → 跳过（2a1d LC-D）
        reg = {str(k) for k in registered_weather}
        if param not in reg:
            _emit(report, "condition", "condition.param", "V6",
                  rule="weather_key_not_registered", param=param,
                  registered=sorted(reg),
                  msg="天气 %r 没有在默认天气池里注册（已注册：%s）"
                      % (param, "/".join(sorted(reg))))
