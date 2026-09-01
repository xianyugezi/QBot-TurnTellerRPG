"""统一条件引擎纯模块 —— M4 批次0·路A2（A2 唯一实现）：{var,op,value,param} 四键条件求值。

依据：m4_shared_contract §1 A2（9 运算符/三原语/组合/互译表/求值失败默认 False）
      + NPC 系统设计定稿 §四（4.0 统一条件语法 / 4.1 比较运算符 / 4.2 运算符总表 /
        4.3 var 键空间总表 / 4.3.1 中文↔英文互译表（唯一权威主表）/
        4.3.2 事件注册表 / 4.4 组合 any/all/not 嵌套）
      + 任务系统设计定稿 L19-36（条件三原语）/ L37（op 符号双写）/ L39-44（别名映射速查）
      + 细化_2b4_任务引擎契约 §二（2.2 三原语判定语义表 / 2.3 op 双写等价表 /
        2.4 param 目标维度 / D-02 数组全与 / D-03 求值失败默认不满足）。

本文件 = A2 统一条件引擎唯一实现（m4_shared_contract §1 A2 推荐新建；weather_conditions.py
M40 三键保持薄封装不动，combo.py 战斗条件语义不同不混）：
  eval_condition(cond, ctx) -> bool      条件求值（fail-safe，不抛错）
  normalize_op(op) / normalize_var(var)  运算符双写归一 / 中英互译表 var 归一
  REGISTERED_VARS                         var 键空间注册表（NPC 4.3 九类 + 签到/扩展）
  VAR_ALIASES                             中英互译表（NPC 4.3.1 权威，中→英配置存储用英文）
  OPERATORS / OP_SYMBOL_ALIASES           9 运算符白名单 + 符号双写映射
  EVENT_PRESETS                           预置事件注册表（NPC 4.3.2）
  validate_condition(cond, report)        条件表达式结构校验（供校验器/编辑器复用）

求值语义（对齐 NPC 4.0-4.4 / 任务 L19-36 / 2b4 §二）：
  - 结构 {var, op, value, param}；9 运算符 gt/ge/lt/le/eq/ne/between/is/not；
    符号双写 >= > <= < = != 归一（NPC 4.1）；旧 min/max 简写 → ge/le（NPC 4.2 兼容）。
  - 旧 {type,var,op,value} 的 type 忽略（var 归一，黄提示「旧格式，建议迁移」）；
    旧 event 原语 {type:"event", event, target, count} 等价归一为
    {var:"[事件:event]", op:"ge", value:count, param:target}（NPC 4.0）。
  - 三原语（任务 L25-36）：值型（level/item_count 读当前值）/ 累计型
    （gain_count/kill_count/dungeon_clear/main_progress 读 longline_counters）/
    事件型（var 前缀 [事件:xxx]，读事件计数）。
  - 组合：any/all/not 嵌套递归求值（NPC 4.4）；conditions 数组（list/tuple）= 全与
    （2b4 D-02「数组全与 + 支持 {all:[...]} 嵌套」）。
  - var 中文变量键经 VAR_ALIASES 互译为英文条件键（NPC 4.3.1：编辑面板显示中文、
    配置存储与校验一律英文条件键）。
  - 求值失败默认 False 不抛错（D-03 / m4_shared_contract §1 A2）。

【工程补白】（契约/定稿未显式定义处，显式标注供审查）：
  1. ctx 读取双通道（对齐 weather_conditions）：直接值键优先（level/inventory/...），
     ctx["player"] 嵌套次之（_ctx_get）；时间三键（season/period/weather）支持直接值键
     season_now/period_now/weather_now（字符串，优先）或 ctx["worldtime"] 鸭子类型
     （season_now()/period_now()/weather_now(map_id)，缺该方法/缺 map_id → fail-safe
     False），weather 上下文按 map_id 绑定（对齐 2a4c IF04）。
  2. param 优先于 var 内嵌目标：中文别名 [背包:铁矿] 内嵌目标「铁矿」仅在 param 缺省时
     使用（NPC 4.3.1）；事件名内嵌目标 [事件:副本通关:熔岩洞窟] 在 param 缺省时取内嵌值
     （NPC 4.3.2「:ID 写在事件名内」与「目标写进 param」两种写法同义）。
  3. 默认 op：非事件型缺省 eq（对齐 2a4c 三键简写，简写与完整形等价）；事件型缺省 ge 且
     value 缺省 1（2b4 §2.2 L147「事件触发次数 ≥ value（默认 1）」——{var:"[事件:落石]"}
     简写即「已触发过」）。
  3a. 三键 param 作比较操作数（2a4c §2.1「eq+param 判定」）：season/period/weather 三个 var
      的约定形态 {op:"eq", param:X} 中 value 键不参与——求值时若 value 缺省、var 属三键且
      param 存在，则以 param 作为比较操作数（{var:"[季节:X]", op:"eq"} / {var:"season",
      op:"eq", param:X} / 简写 {var:"season", param:X} 三种写法等价）。
  4. 求值失败口径（D-03）：未知 var / op 非法 / param 维度缺失 / 上下文无法取值 → False。
     计数器类细分：longline_counters 缺表 = 计数 0（玩家存档长期计数，缺失即从未发生；
     ge 1 → False、eq 0 → True 语义成立）；事件计数表（event_counts）整体缺失 = 求值失败
     → None → False（特征未接线，严格 fail-safe）；事件名在表中缺条目 = 计数 0（注册事件
     从未触发）。
  5. is/not 语义（NPC 4.1/4.2 全量示例可回查）：is = 布尔存在判定 —— value 为布尔 →
     与当前布尔相等比较（is_night is true/false）；current 为布尔 → 存在即真（has_item 等
     谓词 var，value 作目标被解析消费）；其余 → 相等比较（job is 剑士 ≡ eq）。not = is 的
     取反（{var:job, op:not, value:X} ≡ 职业 ≠ X；{var:has_item, op:not, ...} ≡ not_has_item）。
  6. x_ 扩展键：内容包自定义键，经 ctx["ext_vars"]（Mapping）读取；未定义 → None → False。
  7. between 区间 [a,b] 允许乱序（自动排序）；gt/ge/lt/le 数值比较前做数值化
     （数字串 "10" 视为 10，bool 不视为数值）。
  8. 校验器（validate_condition）：只做结构红拦（var 未注册 / op 非法 / 结构错误）；旧格式、
     未登记事件只黄提示不拦（NPC 4.5「只建议不限制」）；事件名未在 EVENT_PRESETS → 黄提示
     「事件未登记，确认拼写或先登记」（NPC 4.3.2）。

铁律：零 NoneBot import；纯函数无 IO（同刻同参必同值）；fail-safe 不抛错。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Tuple

__all__ = [
    "OPERATORS",
    "OP_SYMBOL_ALIASES",
    "OP_LEGACY_ALIASES",
    "REGISTERED_VARS",
    "VAR_CATEGORIES",
    "VAR_ALIASES",
    "EVENT_PRESETS",
    "CHECKIN_TABLES",
    "CHECKIN_FIELDS",
    "normalize_op",
    "normalize_var",
    "eval_condition",
    "validate_condition",
]

# -------------------------------------------------------------------------------------
# 运算符：9 种白名单 + 符号双写（NPC 4.1/4.2 + 任务 L37）+ 旧简写兼容（NPC 4.2）
# -------------------------------------------------------------------------------------
OPERATORS: Tuple[str, ...] = ("gt", "ge", "lt", "le", "eq", "ne", "between", "is", "not")

OP_SYMBOL_ALIASES: dict = {
    ">=": "ge",
    ">": "gt",
    "<=": "le",
    "<": "lt",
    "=": "eq",
    "!=": "ne",
}

# NPC 4.2 兼容：旧 min/max 简写自动映射（min=ge、max=le）
OP_LEGACY_ALIASES: dict = {"min": "ge", "max": "le"}


def normalize_op(op: object) -> Optional[str]:
    """运算符归一：英文 9 种直接通过；符号双写 >= > <= < = != → ge gt le lt eq ne；
    旧简写 min/max → ge/le。非法/非字符串 → None（fail-safe → 求值 False）。"""
    if not isinstance(op, str) or not op:
        return None
    o = op.strip().lower()
    if o in OPERATORS:
        return o
    if o in OP_SYMBOL_ALIASES:
        return OP_SYMBOL_ALIASES[o]
    if o in OP_LEGACY_ALIASES:
        return OP_LEGACY_ALIASES[o]
    return None


# -------------------------------------------------------------------------------------
# var 键空间注册表（NPC 4.3 九类 + 签到（2026-08-16 登记）+ 资源轴（6c A7/A9）+ 扩展；供校验器/编辑器）
# -------------------------------------------------------------------------------------
VAR_CATEGORIES: dict = {
    "任务类": ("has_quest", "quest_completed", "quest_state"),
    "物品类": ("has_item", "not_has_item", "item_count"),
    "职业类": ("job", "job_level"),
    "熟练类": ("prof_level",),
    "状态类": ("level", "reputation", "main_progress", "codex"),
    "累计类": ("gain_count", "kill_count"),
    "副本类": ("dungeon_clear",),
    "事件类": ("[事件:<事件名>]",),
    "资源类": ("resource", "[我方资源:<资源ID>]", "[对方资源:<资源ID>]"),
    "时间类": ("time", "is_day", "is_night", "season", "period", "weather"),
    "关系类": ("affection",),
    "签到类": ("[签到:<表名>.<字段>]",),
    "组合": ("any", "all", "not"),
    "扩展": ("x_<自定义>",),
}

# var → 类别（扁平注册表；事件/签到为前缀模式键，运行时按前缀识别）
REGISTERED_VARS: dict = {}
for _cat, _keys in VAR_CATEGORIES.items():
    for _k in _keys:
        REGISTERED_VARS[_k] = _cat

# -------------------------------------------------------------------------------------
# 中英互译表（NPC 4.3.1 唯一权威主表；中→英，配置存储与校验用英文条件键）
# 形态：精确键 → (var, None)；带 {T} 占位 → (var, "{T}")，运行时按前缀/后缀提取目标进 param
# -------------------------------------------------------------------------------------
VAR_ALIASES: dict = {
    "[当前等级]": ("level", None),
    "[背包:{T}]": ("item_count", "{T}"),
    "[累计获得:{T}]": ("gain_count", "{T}"),
    "[累计击杀:{T}]": ("kill_count", "{T}"),
    "[副本通关:{T}]": ("dungeon_clear", "{T}"),
    "[图鉴完成度]": ("codex", None),
    "[主线进度]": ("main_progress", None),
    "[熟练度:{T}]": ("prof_level", "{T}"),
    "[声望:{T}]": ("reputation", "{T}"),
    "[职业]": ("job", None),
    "[季节:{T}]": ("season", "{T}"),
    "[时段:{T}]": ("period", "{T}"),
    "[天气:{T}]": ("weather", "{T}"),
    # 资源轴变量（6c A7/A9 + D-04 池级引用）：stats.json 注册即自动可用；
    # 内嵌目标 = 资源轴 ID（数值型=轴 ID；子池型=池级 axis.pool 或轴 ID
    # （轴 ID 无池后缀 = 池级展示总量：各池和，D-04））
    "[我方资源:{T}]": ("resource", "{T}"),
    "[对方资源:{T}]": ("resource", "{T}"),
    # 签到三键（用户裁决⑧）：缺省表名 = 主表 loop
    "[签到:连续天数]": ("[签到:loop.连续天数]", None),
    "[签到:本月天数]": ("[签到:loop.本月天数]", None),
    "[签到:今日已签]": ("[签到:loop.今日已签]", None),
}

# -------------------------------------------------------------------------------------
# 事件注册表（NPC 4.3.2 预置事件清单：可直接引用；内容包扩展须登记，校验器黄提示）
# -------------------------------------------------------------------------------------
EVENT_PRESETS: Tuple[str, ...] = (
    "[事件:副本通关]",
    "[事件:任务完成]",
    "[事件:签到]",
    "[事件:怪物击杀]",
    "[事件:等级提升]",
    "[事件:NPC对话]",
)

# 签到表名 + 中文字段 → 内部字段（用户裁决⑧：[签到:<表名>.<字段>]，缺省表名=loop）
CHECKIN_TABLES: Tuple[str, ...] = ("loop", "monthly", "activity")
CHECKIN_FIELDS: dict = {
    "连续天数": "streak",
    "本月天数": "month_days",
    "今日已签": "today_signed",
    # 直接写英文内部字段亦接受（编辑器英文通道）
    "streak": "streak",
    "month_days": "month_days",
    "today_signed": "today_signed",
}

# param 即比较操作数的 var（2a4c 三键约定：{var:"season"|"period"|"weather", op:"eq",
# param:X}，value 键不参与、op 缺省按 eq、简写 {var,param:X} 等价）。求值时若 value 缺省，
# 以 param 作为比较操作数（补白 3a）；其余 var 的 param 一律是目标维度（目标物品/怪物/板等）。
_PARAM_OPERAND_VARS: Tuple[str, ...] = ("season", "period", "weather")


# -------------------------------------------------------------------------------------
# var 归一（中英互译 + 内嵌目标提取）→ (英文条件键, 内嵌 param 目标)
# -------------------------------------------------------------------------------------
def normalize_var(var: object) -> Tuple[Optional[str], Optional[str]]:
    """var 归一 → (英文条件键, 内嵌目标)。未注册/非法 → (None, None)（fail-safe → False）。

    识别顺序：① REGISTERED_VARS 精确键直接通过；② VAR_ALIASES 精确别名；
    ③ VAR_ALIASES 带 {T} 占位（[背包:铁矿] → ("item_count", "铁矿")）；
    ④ 前缀模式：[事件:...]/[签到:...]（内容含内嵌目标另行解析）/ x_ 扩展。
    """
    if not isinstance(var, str) or not var:
        return None, None
    v = var.strip()
    if v in REGISTERED_VARS:
        return v, None
    if v in VAR_ALIASES:
        k, p = VAR_ALIASES[v]
        return (k, p) if p is None else (k, None)
    for pat, (k, p) in VAR_ALIASES.items():
        if "{T}" not in pat:
            continue
        prefix, suffix = pat.split("{T}", 1)
        if (
            v.startswith(prefix)
            and v.endswith(suffix)
            and len(v) > len(prefix) + len(suffix)
        ):
            return k, v[len(prefix): len(v) - len(suffix)]
    # 资源轴侧前缀路径（6c A7/A9）：[我方资源:rage] / [对方资源:element_energy.fire]
    # 在 VAR_ALIASES 精确匹配后单独识别——内嵌目标整体（轴 ID / 池级 axis.pool）
    # 连同侧前缀（我方/对方）整体交给 _resolve_resource 解析（保持 alias 内嵌
    # 目标与 var=resource 四键条件 param 的取数语义完全一致）
    if v.startswith("[我方资源:") and v.endswith("]"):
        return "resource", v[len("[我方资源:"):-1]
    if v.startswith("[对方资源:") and v.endswith("]"):
        return "resource", v[len("[对方资源:"):-1]
    if v.startswith("[事件:") and v.endswith("]"):
        return v, None
    if v.startswith("[签到:") and v.endswith("]"):
        return v, None
    if v.startswith("x_"):
        return v, None
    return None, None


def _parse_event_var(var: str) -> Tuple[str, Optional[str]]:
    """事件名内嵌目标：`[事件:副本通关:熔岩洞窟]` → ("[事件:副本通关]", "熔岩洞窟")（NPC 4.3.2）。"""
    inner = var[len("[事件:"):]
    if inner.endswith("]"):
        inner = inner[:-1]
    if ":" in inner:
        name, target = inner.rsplit(":", 1)
        if name and target:
            return "[事件:" + name + "]", target
    return var, None


def _parse_checkin_body(body: str, ctx: Optional[Mapping] = None) -> Tuple[Optional[str], Optional[str]]:
    """[签到:<表名>.<字段>] 解析 → (表名, 内部字段)；缺省表名 = 主表 loop（用户裁决⑧）。

    表名双口径（审查_M4实现_批次5_jspace.md P1-2）：生效 type 名（loop/monthly/activity）直接通过；
    表 id 限定键（如 [签到:checkin_monthly.本月天数]，表 id 恰为定稿正典示例）经 ctx["checkin_tables"]
    映射到生效 type 再消费——兑现内容层校验器「表 id 或生效 type 两口径皆可解析」承诺，条件不再静默 False。"""
    if "." in body:
        table, field = body.split(".", 1)
    else:
        table, field = "loop", body
    if table in CHECKIN_TABLES:
        field_internal = CHECKIN_FIELDS.get(field)
        if field_internal is None:
            return None, None
        return table, field_internal
    if isinstance(ctx, Mapping):
        tables = ctx.get("checkin_tables")
        if isinstance(tables, Mapping):
            hit = tables.get(table)
            if isinstance(hit, Mapping):
                typ = hit.get("type", "loop")
                if typ in CHECKIN_TABLES:
                    field_internal = CHECKIN_FIELDS.get(field)
                    if field_internal is None:
                        return None, None
                    return typ, field_internal
    return None, None


# -------------------------------------------------------------------------------------
# ctx 读取工具（纯函数 fail-safe）
# -------------------------------------------------------------------------------------
def _ctx_get(ctx: Mapping[str, Any], key: str) -> Any:
    """直接值键优先，ctx["player"] 嵌套次之（对齐 weather_conditions 双通道）。"""
    if key in ctx:
        return ctx[key]
    player = ctx.get("player")
    if isinstance(player, Mapping) and key in player:
        return player[key]
    return None


def _num(x: object) -> Optional[float]:
    """数值化：int/float 直通；数字串 "10" → 10.0；bool 不视为数值；非法 → None。"""
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


def _num_of(x: object, default: float = 0.0) -> float:
    """数值化兜底：_num 成功取之，失败取 default（计数器类缺失=0 语义，补白 4）。"""
    v = _num(x)
    return v if v is not None else default


def _codex_category_pct(ctx: Mapping[str, Any], category: str) -> Optional[float]:
    """codex 分册完成度（M11 4c §2.2 / 摸底 G3）：param 分册维度读取。

    取值通道（fail-safe，engine 层零 core 依赖——G0 依赖矩阵 engine→data 单向）：
      ① ctx["codex_categories"]（{分册名: pct} 投影，装配层注入，裸 ctx 可用）→ 直取；
      ② 皆缺 → None（D-03 求值失败=不满足）。
    分册名非法（非 str/空）→ None；未知分册 → None（fail-safe）。
    """
    if not isinstance(category, str) or not category:
        return None
    proj = ctx.get("codex_categories")
    if isinstance(proj, Mapping):
        v = proj.get(category)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _eq(a: object, b: object) -> bool:
    """宽松相等：数值与数字串相等；bool 必须同型同值；其余字符串比较。"""
    if a is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb
    return str(a) == str(b)


def _op_is(current: object, value: object) -> bool:
    """is 语义（NPC 4.1/4.2）：value 为布尔 → 与当前布尔相等比较；
    current 为布尔 → 存在即真（谓词 var，value 作目标已被解析消费）；其余 → 相等比较。"""
    if isinstance(value, bool):
        return bool(current) == value
    if isinstance(current, bool):
        return bool(current)
    return _eq(current, value)


def _apply_op(op: str, current: object, value: object) -> bool:
    """单原子条件算子求值。current 为 None（解析失败）→ False（D-03）。"""
    if current is None:
        return False
    if op == "is":
        return _op_is(current, value)
    if op == "not":
        return not _op_is(current, value)
    if op == "eq":
        return _eq(current, value)
    if op == "ne":
        return not _eq(current, value)
    a = _num(current)
    if op in ("gt", "ge", "lt", "le"):
        b = _num(value)
        if a is None or b is None:
            return False
        if op == "gt":
            return a > b
        if op == "ge":
            return a >= b
        if op == "lt":
            return a < b
        return a <= b
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return False
        lo, hi = _num(value[0]), _num(value[1])
        if a is None or lo is None or hi is None:
            return False
        if lo > hi:
            lo, hi = hi, lo  # 区间乱序自动排序（补白 7）
        return lo <= a <= hi
    return False


def _read_counter(
    ctx: Mapping[str, Any], table_key: str, name: str, param: Optional[str]
) -> Optional[float]:
    """读计数器表（longline_counters / event_counts），支持嵌套与扁平两形态：

    nested: table[name] = {param: count}；无 param 时 table[name] 标量 = count
    flat:   table[f"{name}:{param}"] = count；无 param 时 table[name] = count
    表缺失 → 由调用方决定（0 或 None）；条目缺失 → 0（从未发生）。
    """
    table = ctx.get(table_key)
    if not isinstance(table, Mapping):
        return 0.0
    sub = table.get(name)
    if isinstance(sub, Mapping):
        if param is None:
            return 0.0  # 嵌套形态需 param 维度
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


def _exists(ctx: Mapping[str, Any], key: str, target: object) -> Optional[bool]:
    """集合包含判定（inventory/quest_active/quest_completed：Mapping/set/list 均可）。
    上下文缺失 / 无目标 → None（fail-safe False）。"""
    if target is None:
        return None
    coll = ctx.get(key)
    if coll is None:
        return None
    if isinstance(coll, Mapping):
        return target in coll
    if isinstance(coll, (set, frozenset)):
        return target in coll
    if isinstance(coll, (list, tuple)):
        return target in coll
    return None


def _bool_of(ctx: Mapping[str, Any], key: str, time_val: str) -> Optional[bool]:
    """布尔状态（is_day/is_night）：直接值键优先，其次 ctx["time"]，最后 period 推导。"""
    v = _ctx_get(ctx, key)
    if isinstance(v, bool):
        return v
    t = _ctx_get(ctx, "time")
    if isinstance(t, str):
        return t == time_val
    p = _period_now(ctx)
    if p is None:
        return None
    if time_val == "night":
        return p in ("night", "midnight")
    return p not in ("night", "midnight")


# -------------------------------------------------------------------------------------
# 时间三键取值（鸭子类型对齐 weather_conditions：直接值优先 → worldtime 实例）
# -------------------------------------------------------------------------------------
def _now_of(ctx: Mapping[str, Any]) -> Optional[int]:
    n = ctx.get("now")
    return n if isinstance(n, int) else None


def _season_now(ctx: Mapping[str, Any]) -> Optional[str]:
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
        return None
    return v if isinstance(v, str) else None


def _period_now(ctx: Mapping[str, Any]) -> Optional[str]:
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
# var 取值（三原语解析；返回值 None = 解析失败 → 不满足）
# -------------------------------------------------------------------------------------
def _resolve_var(
    ctx: Mapping[str, Any], var: str, param: Optional[str], value: object
) -> object:
    if var == "level":
        return _num(_ctx_get(ctx, "level"))
    if var == "item_count":
        if param is None:
            return None  # param 维度缺失 → fail-safe（D-03）
        inv = ctx.get("inventory")
        if not isinstance(inv, Mapping):
            return None
        return _num(inv.get(param, 0))
    if var == "has_item":
        return _exists(ctx, "inventory", param or value)
    if var == "not_has_item":
        e = _exists(ctx, "inventory", param or value)
        return None if e is None else not e
    if var == "has_quest":
        return _exists(ctx, "quest_active", param or value)
    if var == "quest_completed":
        return _exists(ctx, "quest_completed", param or value)
    if var == "quest_state":
        qs = ctx.get("quest_state")
        if not isinstance(qs, Mapping) or param is None:
            return None
        return qs.get(param)
    if var == "job":
        return _ctx_get(ctx, "job")
    if var == "job_level":
        return _num(_ctx_get(ctx, "job_level"))
    if var == "prof_level":
        pl = _ctx_get(ctx, "prof_level")
        if isinstance(pl, Mapping):
            if param is None:
                return None
            return _num(pl.get(param, 0))
        return _num(pl)
    if var == "reputation":
        rep = _ctx_get(ctx, "reputation")
        if isinstance(rep, Mapping):
            return _num(rep.get(param or "global", 0))
        return _num(rep)
    if var == "main_progress":
        direct = _ctx_get(ctx, "main_progress")
        if direct is not None:
            return _num(direct)
        return _read_counter(ctx, "longline_counters", "main_progress", None)
    if var == "codex":
        if param is not None:
            # 分册维度（4c §2.2 映射 + 摸底 G3）：{var:codex, param:"monster"} 读分册
            # 完成度。优先 ctx["codex_state"] 现算（codex_progress(ctx, category)），
            # 兜底 ctx["codex_categories"]（{分册: pct} 投影，装配层可注入）——
            # 避免裸 ctx（无 registry）时静默 0；两者皆缺 → fail-safe None（D-03）。
            return _codex_category_pct(ctx, param)
        return _num(_ctx_get(ctx, "codex"))
    if var == "gain_count":
        if param is None:
            return None
        return _read_counter(ctx, "longline_counters", "gain_count", param)
    if var == "kill_count":
        if param is None:
            return None
        return _read_counter(ctx, "longline_counters", "kill_count", param)
    if var == "dungeon_clear":
        if param is None:
            return None
        return _read_counter(ctx, "longline_counters", "dungeon_clear", param)
    if var == "time":
        t = _ctx_get(ctx, "time")
        if isinstance(t, str):
            return t
        p = _period_now(ctx)
        if p is None:
            return None
        return "night" if p in ("night", "midnight") else "day"
    if var == "is_day":
        return _bool_of(ctx, "is_day", "day")
    if var == "is_night":
        return _bool_of(ctx, "is_night", "night")
    if var == "season":
        return _season_now(ctx)
    if var == "period":
        return _period_now(ctx)
    if var == "weather":
        return _weather_now(ctx)
    if var == "affection":
        af = _ctx_get(ctx, "affection")
        if isinstance(af, Mapping):
            return _num(af.get(param or "global", 0))
        return _num(af)
    if var == "resource":
        # 6c A7/A9 资源轴变量求值（M13 批9 路9B）：var=resource 数值比较
        # （gt/ge/lt/le/eq/ne/between + param=资源轴 ID；含池级引用
        # [我方资源:element_energy.fire]，D-04）。
        # 我方=player / 对方=enemy（_RESOURCE_SIDE_MAP）；池级引用形态
        # axis.pool → 子池型该池当前值；轴 ID 无池后缀 → 数值型单键 /
        # 子池型各池展示总量（D-04「总量提供展示键」）；未注册键 →
        # None（fail-safe False，D-03 / V5 黄提示在加载期拦截）。
        return _resolve_resource(ctx, param)
    if var.startswith("[签到:"):
        return _resolve_checkin(ctx, var)
    if var.startswith("[事件:"):
        return _read_counter(ctx, "event_counts", var, param)
    if var.startswith("x_"):
        ext = ctx.get("ext_vars")
        if not isinstance(ext, Mapping):
            return None
        return ext.get(var)
    return None


def _resolve_checkin(ctx: Mapping[str, Any], var: str) -> object:
    """[签到:<表名>.<字段>] 取值：ctx["checkin"] 嵌套 {表: {内部字段: 值}} 优先，
    扁平复合键 {var: 值} 次之；签到上下文整体缺失 → None（fail-safe False）。"""
    body = var[len("[签到:"):]
    if body.endswith("]"):
        body = body[:-1]
    table, field = _parse_checkin_body(body, ctx)
    if table is None or field is None:
        return None
    ck = ctx.get("checkin")
    if not isinstance(ck, Mapping):
        return None
    t = ck.get(table)
    if isinstance(t, Mapping) and field in t:
        return _num(t[field])
    if var in ck:
        return _num(ck[var])  # 扁平复合键
    return 0  # 表在但该字段无值 → 0（未签/未满）


# -------------------------------------------------------------------------------------
# 资源轴变量取值（6c A7/A9 + D-04 池级引用；M13 批9 路9B）
# -------------------------------------------------------------------------------------
# 我方=player / 对方=enemy（战斗快照 per-side 惯例；6c §1.4 快照形态
# resource_state.player / resource_state.enemy【资源轴 L102-108】）
_RESOURCE_SIDE_MAP: dict = {
    "我方": "player",
    "对方": "enemy",
}


def _resolve_resource(ctx: Mapping[str, Any], target: object) -> Optional[float]:
    """var=resource 取值：ctx["resource_state"] 的 per-side 段读取资源当前值。

    参数：target = 资源引用（param 或 [我方资源:X] 内嵌目标），形态：
      - 轴 ID（数值型）："rage" → 单键当前值；
      - 池级引用（子池型，D-04）："element_energy.fire" → 该池当前值；
      - 轴 ID（子池型，无池后缀）："element_energy" → 各池和（展示总量，
        D-04「总量提供展示键 [我方资源:element_energy]」）；
      - 侧前缀（我方/对方）：仅 [我方资源:X] / [对方资源:X] 别名路径携带，
        经 _RESOURCE_SIDE_MAP 映射为 player/enemy；var=resource 四键条件
        缺省我方（player）。
    失败口径（D-03 / V5）：资源上下文缺失 / 轴未注册 / 池名未注册 /
    数值型轴带池后缀 / 非法引用 → None（求值 False，不抛错）。
    """
    if not isinstance(target, str) or not target:
        return None
    side = "player"  # var=resource 四键条件缺省我方（player）
    axis = target
    if ":" in target:
        side_prefix, _, axis = target.partition(":")
        mapped = _RESOURCE_SIDE_MAP.get(side_prefix)
        if mapped is None:
            return None  # 未知侧前缀 → fail-safe（防御）
        side = mapped
    if not axis:
        return None
    rs = ctx.get("resource_state")
    if not isinstance(rs, Mapping):
        return None  # 资源上下文整体缺失 → fail-safe（D-03）
    side_state = rs.get(side)
    if not isinstance(side_state, Mapping):
        return None  # 该侧无资源段 → fail-safe
    axis_id, _, pool = axis.partition(".")
    if not axis_id:
        return None
    if axis_id not in side_state:
        return None  # 轴未注册/未初始化 → fail-safe（V5 黄提示在加载期拦截）
    raw = side_state.get(axis_id)
    if pool:
        # 池级引用：子池型该池当前值
        if not isinstance(raw, Mapping):
            return None  # 数值型轴带池后缀 → fail-safe
        v = raw.get(pool)
        return _num(v)
    if isinstance(raw, Mapping):
        # 子池型轴 ID（无池后缀）= 各池和（展示总量，D-04）
        total = 0.0
        for pool_v in raw.values():
            pv = _num(pool_v)
            if pv is None:
                return None  # 池值非法 → fail-safe（防御）
            total += pv
        return total
    return _num(raw)


# -------------------------------------------------------------------------------------
# 求值主入口（fail-safe：任何异常形态 → False，不抛错）
# -------------------------------------------------------------------------------------
def _as_cond_list(x: object) -> list:
    if isinstance(x, (list, tuple)):
        return list(x)
    if isinstance(x, Mapping):
        return [x]
    return []


def eval_condition(cond: object, ctx: object) -> bool:
    """统一条件求值 -> bool（fail-safe：任何异常形态 → False，不抛错）。

    cond: 条件表达式。原子 {var,op,value,param}；组合 {all:[...]}/{any:[...]}/{not:...}
          嵌套递归；list/tuple = conditions 数组全与（2b4 D-02）；
          旧 {type,var,op,value} 的 type 忽略；旧 event 原语 {type:"event",...} 等价归一。
    ctx:  求值上下文（Mapping，见文件头补白 1）——level/inventory/longline_counters/
          quest_active/quest_completed/event_counts/checkin/season_now/.../worldtime 等。
    返回：求值失败（未知 var / op 非法 / param 缺失 / 上下文无法取值）→ False（D-03）。
    """
    if not isinstance(ctx, Mapping):
        return False
    if isinstance(cond, (list, tuple)):
        return all(eval_condition(c, ctx) for c in cond)
    if not isinstance(cond, Mapping):
        return False
    if "var" in cond:
        return _eval_atomic(cond, ctx)
    if "all" in cond:
        return all(eval_condition(c, ctx) for c in _as_cond_list(cond["all"]))
    if "any" in cond:
        return any(eval_condition(c, ctx) for c in _as_cond_list(cond["any"]))
    if "not" in cond:
        return not eval_condition(cond["not"], ctx)
    # 旧 event 原语（NPC 4.0）：{type:"event", event, target, count} → 四键等价归一
    if cond.get("type") == "event" and isinstance(cond.get("event"), str):
        return _eval_atomic(
            {
                "var": "[事件:" + cond["event"] + "]",
                "op": "ge",
                "value": cond.get("count", 1),
                "param": cond.get("target"),
            },
            ctx,
        )
    return False


def _eval_atomic(cond: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    raw_var = cond.get("var")
    var, embedded = normalize_var(raw_var)
    if var is None:
        return False  # 未注册 var → 不满足（D-03）
    is_event = var.startswith("[事件:")
    op = normalize_op(cond.get("op"))
    if op is None:
        # 补白 3：事件型缺省 ge，其余缺省 eq
        op = "ge" if is_event else "eq"
    value = cond.get("value")
    if is_event and value is None:
        value = 1  # 2b4 §2.2 L147「事件触发次数 ≥ value（默认 1）」
    param = cond.get("param")
    if param is None and embedded is not None:
        param = embedded  # 中文别名内嵌目标（补白 2）；资源别名内嵌 = 轴 ID/池级引用
    if is_event:
        var, emb = _parse_event_var(var)
        if param is None and emb is not None:
            param = emb  # 事件名内嵌目标（NPC 4.3.2，补白 2）
    if var == "resource" and embedded is not None:
        # 资源别名内嵌目标（补白 2 精神：内嵌目标与 param 同义）：
        # 别名缺省 param → 内嵌目标即轴 ID/池级引用，且须补侧前缀
        # （[我方资源:X] → "我方:X" / [对方资源:X] → "对方:X"），由
        # _resolve_resource 按 _RESOURCE_SIDE_MAP 映射 player/enemy；
        # 显式 param 直写（四键条件）不补前缀、原样交给 _resolve_resource
        # （无前缀 → 缺省我方 player；带我方:/对方: 前缀 → 按映射）
        if param == embedded:  # param 缺省被通用别名分支填为内嵌目标（无侧前缀）
            if cond.get("var", "").startswith("[对方资源:"):
                param = "对方:" + embedded
            else:
                param = "我方:" + embedded
    if value is None and var in _PARAM_OPERAND_VARS and param is not None:
        value = param  # 三键约定：value 缺省时 param 作比较操作数（补白 3a）
    current = _resolve_var(ctx, var, param, value)
    return _apply_op(op, current, value)


# -------------------------------------------------------------------------------------
# 校验器（供校验器/编辑器复用；结构红拦 + 旧格式/未登记事件黄提示，NPC 4.5 只建议不限制）
# -------------------------------------------------------------------------------------
def _emit(report: object, module: str, field: str, kind: str, **detail: object) -> None:
    """向 report 追加一条记录：优先 _err(module, field, kind, **detail)（validator._Checker
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


def validate_condition(cond: object, report: object) -> None:
    """条件表达式结构校验（递归 any/all/not 与数组）。

    cond: 条件表达式（原子/组合/数组）。report: 鸭子类型收集器（同 weather_conditions）。
    红拦（error）：var 未注册 / op 非法 / 结构错误 / 缺 var 与组合键。
    黄提示（不拦）：旧格式 {type,var,op,value}（type 非空）→「旧格式，建议迁移」；
            旧 event 原语 {type:"event",...} → 建议迁移四键；
            事件 var 未在预置事件注册表 →「事件未登记，确认拼写或先登记」（NPC 4.3.2）。
    """
    if isinstance(cond, (list, tuple)):
        for c in cond:
            validate_condition(c, report)
        return
    if not isinstance(cond, Mapping):
        _emit(report, "condition", "condition", "CND", rule="condition_not_object",
              got=type(cond).__name__,
              msg="条件表达式要填对象 {var,op,value,param} 或 any/all/not 组合")
        return
    if "var" in cond:
        var, embedded = normalize_var(cond.get("var"))
        if var is None:
            _emit(report, "condition", "condition.var", "CND", rule="var_not_registered",
                  var=cond.get("var"), allowed=sorted(REGISTERED_VARS),
                  msg="条件变量键 %r 未注册" % (cond.get("var"),))
            return
        param = cond.get("param")
        if param is None and embedded is not None:
            param = embedded  # 中文别名内嵌目标（补白 2）；资源别名内嵌 = 轴 ID/池级引用
        if cond.get("op") is not None and normalize_op(cond.get("op")) is None:
            _emit(report, "condition", "condition.op", "CND", rule="op_invalid",
                  op=cond.get("op"),
                  allowed=list(OPERATORS) + list(OP_SYMBOL_ALIASES) + list(OP_LEGACY_ALIASES),
                  msg="条件运算符 %r 不认识（9 种：%s，符号双写 >= > <= < = !=）"
                      % (cond.get("op"), "/".join(OPERATORS)))
        elif cond.get("type"):
            _emit(report, "condition", "condition.type", "CND", rule="legacy_format",
                  msg="旧格式 {type,var,op,value}，建议迁移为 {var,op,value,param}（type 忽略）")
        if var.startswith("[事件:"):
            name, _ = _parse_event_var(var)
            if name not in EVENT_PRESETS:
                _emit(report, "condition", "condition.var", "CND", rule="event_not_registered",
                      var=var, presets=list(EVENT_PRESETS),
                      msg="事件 %r 未在事件注册表登记，确认拼写或先登记" % (var,))
        elif var == "resource" and not isinstance(param, str):
            _emit(report, "condition", "condition.param", "CND", rule="resource_param_missing",
                  var=var, param=param,
                  msg="资源条件 {var:resource,...} 需 param=资源轴 ID（数值型=轴 ID；"
                      "子池型=池级 axis.pool 或轴 ID=池级展示总量），当前 param 缺失或非字符串")
        return
    if "all" in cond:
        for c in _as_cond_list(cond["all"]):
            validate_condition(c, report)
        return
    if "any" in cond:
        for c in _as_cond_list(cond["any"]):
            validate_condition(c, report)
        return
    if "not" in cond:
        validate_condition(cond["not"], report)
        return
    if cond.get("type") == "event" and isinstance(cond.get("event"), str):
        _emit(report, "condition", "condition", "CND", rule="legacy_format",
              msg="旧 event 原语 {type:event,...}，建议迁移为 "
                  "{var:'[事件:x]',op:'ge',value:count,param:target}")
        return
    _emit(report, "condition", "condition", "CND", rule="condition_empty",
          msg="条件表达式缺 var 或 any/all/not 键")
