"""M4 批次0·路A2：统一条件引擎 condition_engine 测试 —— qbot_rpg.engine.condition_engine。

依据：m4_shared_contract §1 A2（9 运算符/三原语/组合/互译表/求值失败默认 False）
      + NPC 系统设计定稿 §四（4.0-4.4：{var,op,value,param} / 9 运算符 / is-not 语义 /
        互译表 4.3.1 / 事件注册表 4.3.2 / 组合 4.4）
      + 任务系统设计定稿 L19-36（三原语）/ L37（op 符号双写）
      + 细化_2b4_任务引擎契约 §二（2.2 三原语判定语义 / 2.3 op 双写 / D-02 数组全与 / D-03 fail-safe）

测试口径（对齐 test_maps_schema / test_weather_conditions 风格）：构造输入 → 跑纯函数 →
断言结果。eval_condition(cond, ctx) 全形态 fail-safe（不抛错、求值失败默认 False）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.engine.condition_engine import (
    CHECKIN_FIELDS,
    CHECKIN_TABLES,
    EVENT_PRESETS,
    OPERATORS,
    OP_LEGACY_ALIASES,
    OP_SYMBOL_ALIASES,
    REGISTERED_VARS,
    VAR_ALIASES,
    eval_condition,
    normalize_op,
    normalize_var,
    validate_condition,
)


class _Report:
    """validate_condition 收集器（鸭子类型：_err 与 validator._Checker 同签名）。"""

    def __init__(self) -> None:
        self.errors: list = []

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _rules(rep: _Report) -> list:
    return [e["detail"].get("rule") for e in rep.errors]


# ---------------------------------------------------------------------------
# 运算符：9 种白名单 + 符号双写归一 + 旧简写兼容
# ---------------------------------------------------------------------------
def test_operators_9_present() -> None:
    assert OPERATORS == ("gt", "ge", "lt", "le", "eq", "ne", "between", "is", "not")


def test_op_symbol_dual_write_normalize() -> None:
    # NPC 4.1 / 任务 L37：符号双写 >= > <= < = != ≡ ge gt le lt eq ne
    assert normalize_op(">=") == "ge"
    assert normalize_op(">") == "gt"
    assert normalize_op("<=") == "le"
    assert normalize_op("<") == "lt"
    assert normalize_op("=") == "eq"
    assert normalize_op("!=") == "ne"
    assert OP_SYMBOL_ALIASES == {">=": "ge", ">": "gt", "<=": "le", "<": "lt", "=": "eq", "!=": "ne"}


def test_op_legacy_min_max_compat() -> None:
    # NPC 4.2 兼容：旧 min/max 简写自动映射（min=ge、max=le）
    assert normalize_op("min") == "ge"
    assert normalize_op("max") == "le"
    assert OP_LEGACY_ALIASES == {"min": "ge", "max": "le"}


def test_op_invalid_or_non_string() -> None:
    assert normalize_op("gte") is None
    assert normalize_op("==") is None
    assert normalize_op(5) is None
    assert normalize_op(None) is None
    assert normalize_op("") is None


# ---------------------------------------------------------------------------
# 比较运算符语义（level 12 / value 10 基准）
# ---------------------------------------------------------------------------
def _ctx(**kw):
    base = {"level": 12}
    base.update(kw)
    return base


def test_gt_ge_lt_le() -> None:
    assert eval_condition({"var": "level", "op": "gt", "value": 10}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "gt", "value": 12}, _ctx()) is False
    assert eval_condition({"var": "level", "op": "ge", "value": 12}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "ge", "value": 13}, _ctx()) is False
    assert eval_condition({"var": "level", "op": "lt", "value": 10}, _ctx()) is False
    assert eval_condition({"var": "level", "op": "lt", "value": 13}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "le", "value": 12}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "le", "value": 11}, _ctx()) is False


def test_eq_ne() -> None:
    assert eval_condition({"var": "level", "op": "eq", "value": 12}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "eq", "value": 10}, _ctx()) is False
    assert eval_condition({"var": "level", "op": "ne", "value": 10}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "ne", "value": 12}, _ctx()) is False
    # 数字串宽容相等
    assert eval_condition({"var": "level", "op": "eq", "value": "12"}, _ctx()) is True


def test_symbol_dual_write_equivalent() -> None:
    # TC-11 口径：>= ≡ ge、!= ≡ ne 等六对产出完全一致
    c = _ctx()
    for sym, eng in ((">=", "ge"), (">", "gt"), ("<=", "le"), ("<", "lt"), ("=", "eq"), ("!=", "ne")):
        assert eval_condition({"var": "level", "op": sym, "value": 11}, c) == \
            eval_condition({"var": "level", "op": eng, "value": 11}, c)
    # 具体一对：>= 12 真 / > 12 假（符号与英文等价）
    assert eval_condition({"var": "level", "op": ">=", "value": 12}, c) is True
    assert eval_condition({"var": "level", "op": "ge", "value": 12}, c) is True
    assert eval_condition({"var": "level", "op": ">", "value": 12}, c) is False
    assert eval_condition({"var": "level", "op": "gt", "value": 12}, c) is False


def test_between() -> None:
    assert eval_condition({"var": "level", "op": "between", "value": [5, 10]}, _ctx()) is False
    assert eval_condition({"var": "level", "op": "between", "value": [5, 12]}, _ctx()) is True
    assert eval_condition({"var": "level", "op": "between", "value": [10, 15]}, _ctx()) is True
    # 区间乱序自动排序
    assert eval_condition({"var": "level", "op": "between", "value": (15, 10)}, _ctx()) is True
    # 非法 value → False
    assert eval_condition({"var": "level", "op": "between", "value": [10]}, _ctx()) is False
    assert eval_condition({"var": "level", "op": "between", "value": 10}, _ctx()) is False


def test_is_not_semantics() -> None:
    # is：存在判定（NPC 4.1）
    ctx = _ctx(inventory={"铁矿": 5}, job="剑士")
    assert eval_condition({"var": "has_item", "op": "is", "value": "铁矿"}, ctx) is True
    assert eval_condition({"var": "has_item", "op": "is", "value": "铜矿"}, ctx) is False
    assert eval_condition({"var": "not_has_item", "op": "is", "value": "铜矿"}, ctx) is True
    assert eval_condition({"var": "not_has_item", "op": "is", "value": "铁矿"}, ctx) is False
    # is：字符串相等（job is 剑士）
    assert eval_condition({"var": "job", "op": "is", "value": "剑士"}, ctx) is True
    # not：is 取反（job ≠ 元素法师）
    assert eval_condition({"var": "job", "op": "not", "value": "元素法师"}, ctx) is True
    assert eval_condition({"var": "job", "op": "not", "value": "剑士"}, ctx) is False


def test_is_night_bool() -> None:
    assert eval_condition({"var": "is_night", "op": "is", "value": True}, _ctx(is_night=True)) is True
    assert eval_condition({"var": "is_night", "op": "is", "value": False}, _ctx(is_night=True)) is False
    assert eval_condition({"var": "is_night", "op": "not", "value": True}, _ctx(is_night=True)) is False
    # 由 time 推导
    assert eval_condition({"var": "is_night", "op": "is", "value": True}, _ctx(time="night")) is True
    assert eval_condition({"var": "is_day", "op": "is", "value": True}, _ctx(time="day")) is True


# ---------------------------------------------------------------------------
# 三原语：值型（level / item_count）
# ---------------------------------------------------------------------------
def test_value_primitive_level() -> None:
    # 任务 L29 / TC-06：LV10 满足 / LV9 不满足
    assert eval_condition({"var": "level", "op": "ge", "value": 10}, _ctx(level=10)) is True
    assert eval_condition({"var": "level", "op": "ge", "value": 10}, _ctx(level=9)) is False
    # ctx["player"] 嵌套通道
    assert eval_condition({"var": "level", "op": "ge", "value": 10}, {"player": {"level": 12}}) is True


def test_value_primitive_item_count_exact() -> None:
    # 任务 L28 / TC-07：param 精确目标维度（铁矿 ≠ 铁矿石）
    ctx = _ctx(inventory={"铁矿": 20, "铁矿石": 20})
    assert eval_condition({"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"}, ctx) is True
    assert eval_condition({"var": "item_count", "op": "ge", "value": 21, "param": "铁矿"}, ctx) is False
    assert eval_condition({"var": "item_count", "op": "ge", "value": 20, "param": "铁矿石"}, ctx) is True
    assert eval_condition({"var": "item_count", "op": "ge", "value": 30, "param": "铁矿"}, ctx) is False
    # param 维度缺失 → fail-safe False
    assert eval_condition({"var": "item_count", "op": "ge", "value": 1}, ctx) is False
    # 背包表缺失 → fail-safe False
    assert eval_condition({"var": "item_count", "op": "ge", "value": 1, "param": "铁矿"}, _ctx()) is False


# ---------------------------------------------------------------------------
# 三原语：累计型（gain_count / kill_count 读 longline_counters）
# ---------------------------------------------------------------------------
def test_cumulative_gain_count_flat_and_nested() -> None:
    # 任务 L31 / TC-08：读 longline_counters（跨任务复用，任务只读不重复计数）
    flat = _ctx(longline_counters={"gain_count:铁矿": 30})
    assert eval_condition({"var": "gain_count", "op": "ge", "value": 30, "param": "铁矿"}, flat) is True
    assert eval_condition({"var": "gain_count", "op": "ge", "value": 31, "param": "铁矿"}, flat) is False
    nested = _ctx(longline_counters={"gain_count": {"铁矿": 30}})
    assert eval_condition({"var": "gain_count", "op": "ge", "value": 30, "param": "铁矿"}, nested) is True
    # param 缺失 → fail-safe False
    assert eval_condition({"var": "gain_count", "op": "ge", "value": 1}, flat) is False


def test_cumulative_kill_count() -> None:
    # 任务 L31 / TC-09：击杀计数读 longline_counters
    ctx = _ctx(longline_counters={"kill_count": {"岩皮鼬": 5}})
    assert eval_condition({"var": "kill_count", "op": "ge", "value": 5, "param": "岩皮鼬"}, ctx) is True
    assert eval_condition({"var": "kill_count", "op": "ge", "value": 6, "param": "岩皮鼬"}, ctx) is False


def test_cumulative_missing_counter_is_zero() -> None:
    # 长线计数缺失 = 从未发生 = 0（ge 1 → False；eq 0 → True）
    ctx = _ctx(longline_counters={})
    assert eval_condition({"var": "gain_count", "op": "ge", "value": 1, "param": "铁矿"}, ctx) is False
    assert eval_condition({"var": "gain_count", "op": "eq", "value": 0, "param": "铁矿"}, ctx) is True


def test_dungeon_clear_and_main_progress() -> None:
    ctx = _ctx(longline_counters={"dungeon_clear": {"熔岩洞窟": 3}, "main_progress": 4})
    assert eval_condition({"var": "dungeon_clear", "op": "ge", "value": 3, "param": "熔岩洞窟"}, ctx) is True
    assert eval_condition({"var": "dungeon_clear", "op": "ge", "value": 1, "param": "未通关副本"}, ctx) is False
    # main_progress 直接值优先，其次 longline_counters
    assert eval_condition({"var": "main_progress", "op": "ge", "value": 3}, ctx) is True
    assert eval_condition({"var": "main_progress", "op": "ge", "value": 5}, ctx) is False
    assert eval_condition({"var": "main_progress", "op": "ge", "value": 3}, _ctx(main_progress=2)) is False


# ---------------------------------------------------------------------------
# 三原语：事件型（[事件:xxx] 读事件计数）
# ---------------------------------------------------------------------------
def test_event_primitive() -> None:
    # 任务 L34-35 / TC-10：事件触发计数 ≥ value
    ctx = _ctx(event_counts={"[事件:dungeon_clear]": {"熔岩洞窟": 3}})
    assert eval_condition(
        {"var": "[事件:dungeon_clear]", "op": "ge", "value": 1, "param": "熔岩洞窟"}, ctx
    ) is True
    assert eval_condition(
        {"var": "[事件:dungeon_clear]", "op": "ge", "value": 5, "param": "熔岩洞窟"}, ctx
    ) is False
    # 未通关（该事件未触发过）→ 不满足
    assert eval_condition(
        {"var": "[事件:dungeon_clear]", "op": "ge", "value": 1, "param": "未通关副本"}, ctx
    ) is False


def test_event_default_op_and_value() -> None:
    # 2b4 §2.2 L147：事件型 op 缺省 ge、value 缺省 1 —— {var:"[事件:落石]"} = 「已触发过」
    ctx = _ctx(event_counts={"[事件:落石]": 2})
    assert eval_condition({"var": "[事件:落石]"}, ctx) is True
    assert eval_condition({"var": "[事件:落石]", "op": "ge"}, ctx) is True
    ctx0 = _ctx(event_counts={"[事件:落石]": 0})
    assert eval_condition({"var": "[事件:落石]"}, ctx0) is False


def test_event_embedded_target_in_name() -> None:
    # NPC 4.3.2：「:ID 写在事件名内」与「目标写进 param」两种写法同义
    ctx = _ctx(event_counts={"[事件:副本通关]": {"熔岩洞窟": 1}})
    a = eval_condition({"var": "[事件:副本通关:熔岩洞窟]", "op": "ge", "value": 1}, ctx)
    b = eval_condition({"var": "[事件:副本通关]", "op": "ge", "value": 1, "param": "熔岩洞窟"}, ctx)
    assert a is True and a == b


def test_event_not_registered_false() -> None:
    # TC-31：条件引用未注册事件 → 求值失败默认不满足，不崩溃
    ctx = _ctx(event_counts={})
    assert eval_condition({"var": "[事件:future_patch]", "op": "ge", "value": 1}, ctx) is False
    # 事件计数表整体缺失 → 求值失败 → False（fail-safe）
    assert eval_condition({"var": "[事件:future_patch]", "op": "ge", "value": 1}, _ctx()) is False


def test_legacy_event_format_normalized() -> None:
    # NPC 4.0 旧 event 原语 {type:"event", event, target, count} → 四键等价
    ctx = _ctx(event_counts={"[事件:map_enter]": {"新手村": 5}})
    assert eval_condition(
        {"type": "event", "event": "map_enter", "target": "新手村", "count": 2}, ctx
    ) is True
    assert eval_condition(
        {"type": "event", "event": "map_enter", "target": "新手村", "count": 9}, ctx
    ) is False


# ---------------------------------------------------------------------------
# 组合：any/all/not 嵌套递归 + conditions 数组全与（2b4 D-02）
# ---------------------------------------------------------------------------
def test_combination_all() -> None:
    cond = {"all": [
        {"var": "level", "op": "ge", "value": 10},
        {"var": "has_item", "op": "is", "value": "铁矿"},
    ]}
    assert eval_condition(cond, _ctx(level=12, inventory={"铁矿": 1})) is True
    assert eval_condition(cond, _ctx(level=9, inventory={"铁矿": 1})) is False
    assert eval_condition(cond, _ctx(level=12, inventory={})) is False


def test_combination_any() -> None:
    cond = {"any": [
        {"var": "job", "op": "eq", "value": "剑士"},
        {"var": "job_level", "op": "ge", "value": 2},
    ]}
    assert eval_condition(cond, _ctx(job="剑士", job_level=1)) is True
    assert eval_condition(cond, _ctx(job="矿工", job_level=2)) is True
    assert eval_condition(cond, _ctx(job="矿工", job_level=1)) is False


def test_combination_not_nested() -> None:
    cond = {"not": {"var": "job", "op": "eq", "value": "元素法师"}}
    assert eval_condition(cond, _ctx(job="剑士")) is True
    assert eval_condition(cond, _ctx(job="元素法师")) is False
    # 深嵌套：any 内嵌 all + not
    cond2 = {"any": [
        {"all": [
            {"var": "level", "op": "ge", "value": 10},
            {"var": "job", "op": "eq", "value": "剑士"},
        ]},
        {"not": {"var": "has_item", "op": "is", "value": "铁矿"}},
    ]}
    assert eval_condition(cond2, _ctx(level=12, job="剑士", inventory={"铁矿": 1})) is True
    assert eval_condition(cond2, _ctx(level=9, job="剑士", inventory={})) is True
    assert eval_condition(cond2, _ctx(level=9, job="剑士", inventory={"铁矿": 1})) is False


def test_conditions_array_all_and() -> None:
    # 2b4 D-02 / TC-12：conditions 数组全与 —— 必须两条同时满足
    conds = [
        {"var": "level", "op": "ge", "value": 10},
        {"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"},
    ]
    assert eval_condition(conds, _ctx(level=12, inventory={"铁矿": 20})) is True
    assert eval_condition(conds, _ctx(level=9, inventory={"铁矿": 20})) is False
    assert eval_condition(conds, _ctx(level=12, inventory={"铁矿": 19})) is False
    # 空数组 = 全真（接取即完成，D-02 口径）
    assert eval_condition([], _ctx()) is True


# ---------------------------------------------------------------------------
# 旧格式兼容：{type,var,op,value} type 忽略、var 归一（TC-29）
# ---------------------------------------------------------------------------
def test_old_format_type_ignored() -> None:
    # 任务 L279 / NPC 4.0：type 忽略，var 归一
    old = {"type": "collect", "var": "level", "op": "ge", "value": 10}
    new = {"var": "level", "op": "ge", "value": 10}
    assert eval_condition(old, _ctx(level=12)) is True
    assert eval_condition(old, _ctx(level=12)) == eval_condition(new, _ctx(level=12))


def test_old_format_chinese_var_normalized() -> None:
    # 旧中文变量键经互译表归一：{type, var:"[当前等级]", op:">=", value:10}
    old = {"type": "slay", "var": "[当前等级]", "op": ">=", "value": 10}
    assert eval_condition(old, _ctx(level=10)) is True
    assert eval_condition(old, _ctx(level=9)) is False


# ---------------------------------------------------------------------------
# fail-safe：任何异常形态 → False，不抛错（D-03 / m4 §1 A2）
# ---------------------------------------------------------------------------
def test_fail_safe_unknown_var() -> None:
    assert eval_condition({"var": "nope", "op": "ge", "value": 1}, _ctx()) is False


def test_fail_safe_illegal_op() -> None:
    assert eval_condition({"var": "level", "op": "gte", "value": 1}, _ctx()) is False


def test_fail_safe_malformed_cond() -> None:
    assert eval_condition(None, _ctx()) is False
    assert eval_condition(42, _ctx()) is False
    assert eval_condition("level", _ctx()) is False
    assert eval_condition({}, _ctx()) is False
    assert eval_condition({"var": "level"}, _ctx()) is False  # 非事件型 op 缺省 eq + value None
    assert eval_condition({"var": "level", "op": "ge", "value": 10}, None) is False
    assert eval_condition({"var": "level", "op": "ge", "value": 10}, "ctx") is False


def test_fail_safe_ctx_missing_value() -> None:
    # 上下文缺失 level → 无法取值 → False
    assert eval_condition({"var": "level", "op": "ge", "value": 1}, {}) is False


# ---------------------------------------------------------------------------
# var 键空间注册表（NPC 4.3 九类 + 签到 + 扩展）
# ---------------------------------------------------------------------------
def test_registered_vars_categories() -> None:
    assert REGISTERED_VARS["level"] == "状态类"
    assert REGISTERED_VARS["has_item"] == "物品类"
    assert REGISTERED_VARS["item_count"] == "物品类"
    assert REGISTERED_VARS["has_quest"] == "任务类"
    assert REGISTERED_VARS["quest_completed"] == "任务类"
    assert REGISTERED_VARS["job"] == "职业类"
    assert REGISTERED_VARS["prof_level"] == "熟练类"
    assert REGISTERED_VARS["gain_count"] == "累计类"
    assert REGISTERED_VARS["kill_count"] == "累计类"
    assert REGISTERED_VARS["dungeon_clear"] == "副本类"
    assert REGISTERED_VARS["time"] == "时间类"
    assert REGISTERED_VARS["is_night"] == "时间类"
    assert REGISTERED_VARS["weather"] == "时间类"
    assert REGISTERED_VARS["affection"] == "关系类"
    assert REGISTERED_VARS["[签到:<表名>.<字段>]"] == "签到类"
    assert REGISTERED_VARS["[事件:<事件名>]"] == "事件类"
    # 组合键
    for k in ("any", "all", "not"):
        assert REGISTERED_VARS[k] == "组合"


def test_event_presets() -> None:
    assert "[事件:副本通关]" in EVENT_PRESETS
    assert "[事件:任务完成]" in EVENT_PRESETS
    assert "[事件:签到]" in EVENT_PRESETS
    assert "[事件:怪物击杀]" in EVENT_PRESETS
    assert "[事件:等级提升]" in EVENT_PRESETS
    assert "[事件:NPC对话]" in EVENT_PRESETS


# ---------------------------------------------------------------------------
# 中英互译表（NPC 4.3.1 权威主表；中→英，配置存储用英文）
# ---------------------------------------------------------------------------
def test_var_aliases_chinese_to_english() -> None:
    assert normalize_var("[当前等级]") == ("level", None)
    assert normalize_var("[职业]") == ("job", None)
    assert normalize_var("[图鉴完成度]") == ("codex", None)
    assert normalize_var("[主线进度]") == ("main_progress", None)
    assert normalize_var("[背包:铁矿]") == ("item_count", "铁矿")
    assert normalize_var("[累计获得:铁矿]") == ("gain_count", "铁矿")
    assert normalize_var("[累计击杀:岩皮鼬]") == ("kill_count", "岩皮鼬")
    assert normalize_var("[副本通关:熔岩洞窟]") == ("dungeon_clear", "熔岩洞窟")
    assert normalize_var("[熟练度:采集]") == ("prof_level", "采集")
    assert normalize_var("[声望:委托板]") == ("reputation", "委托板")
    assert normalize_var("[季节:summer]") == ("season", "summer")
    assert normalize_var("[时段:night]") == ("period", "night")
    assert normalize_var("[天气:rain]") == ("weather", "rain")


def test_var_alias_eval_chinese() -> None:
    # 中文变量键直接求值（内嵌目标进 param）
    ctx = _ctx(inventory={"铁矿": 20})
    assert eval_condition({"var": "[背包:铁矿]", "op": "ge", "value": 20}, ctx) is True
    assert eval_condition({"var": "[背包:铁矿]", "op": "ge", "value": 21}, ctx) is False
    # 中文别名 + 显式 param：param 优先
    assert eval_condition({"var": "[背包:铁矿]", "op": "ge", "value": 5, "param": "铜矿"}, ctx) is False


def test_normalize_var_unknown() -> None:
    assert normalize_var("nope") == (None, None)
    assert normalize_var(None) == (None, None)
    assert normalize_var(5) == (None, None)


# ---------------------------------------------------------------------------
# 签到三键（用户裁决⑧：[签到:<表名>.<字段>]，缺省表名=loop）
# ---------------------------------------------------------------------------
def test_checkin_nested_ctx() -> None:
    ctx = _ctx(checkin={
        "loop": {"streak": 3, "month_days": 5, "today_signed": 1},
        "monthly": {"month_days": 8},
        "activity": {"today_signed": 1},
    })
    # 连续天数（指定表 + 缺省表名两写法同义）
    assert eval_condition({"var": "[签到:loop.连续天数]", "op": "ge", "value": 3}, ctx) is True
    assert eval_condition({"var": "[签到:连续天数]", "op": "ge", "value": 3}, ctx) is True
    assert eval_condition({"var": "[签到:loop.连续天数]", "op": "ge", "value": 4}, ctx) is False
    # 本月天数（默认主表 loop=5；指定 monthly=8）
    assert eval_condition({"var": "[签到:本月天数]", "op": "ge", "value": 5}, ctx) is True
    assert eval_condition({"var": "[签到:monthly.本月天数]", "op": "ge", "value": 8}, ctx) is True
    assert eval_condition({"var": "[签到:monthly.本月天数]", "op": "ge", "value": 9}, ctx) is False
    # 今日已签（activity）
    assert eval_condition({"var": "[签到:activity.今日已签]", "op": "ge", "value": 1}, ctx) is True
    # 英文内部字段直写亦接受
    assert eval_condition({"var": "[签到:loop.streak]", "op": "ge", "value": 3}, ctx) is True


def test_checkin_flat_ctx_and_fail() -> None:
    flat = _ctx(checkin={"[签到:loop.连续天数]": 3})
    assert eval_condition({"var": "[签到:loop.连续天数]", "op": "ge", "value": 3}, flat) is True
    # 签到上下文整体缺失 → fail-safe False
    assert eval_condition({"var": "[签到:loop.连续天数]", "op": "ge", "value": 1}, _ctx()) is False
    # 表在但字段无值 → 0
    assert eval_condition({"var": "[签到:monthly.本月天数]", "op": "ge", "value": 1},
                          _ctx(checkin={"monthly": {}})) is False
    # 未知表/未知字段 → fail-safe False
    assert eval_condition({"var": "[签到:weekly.连续天数]", "op": "ge", "value": 1}, flat) is False
    assert eval_condition({"var": "[签到:loop.未知字段]", "op": "ge", "value": 1}, flat) is False


def test_checkin_constants() -> None:
    assert CHECKIN_TABLES == ("loop", "monthly", "activity")
    assert CHECKIN_FIELDS["连续天数"] == "streak"
    assert CHECKIN_FIELDS["本月天数"] == "month_days"
    assert CHECKIN_FIELDS["今日已签"] == "today_signed"


# ---------------------------------------------------------------------------
# 时间三键（season/period/weather）+ time/is_day/is_night
# ---------------------------------------------------------------------------
class _StubWorldTime:
    def __init__(self, season: str = "summer", period: str = "night", weather: dict | None = None):
        self._season = season
        self._period = period
        self._weather = dict(weather or {"misty_forest": "rain"})

    def season_now(self, now=None) -> str:
        return self._season

    def period_now(self, now=None) -> str:
        return self._period

    def weather_now(self, map_id: str, now=None) -> str:
        return self._weather.get(map_id, "clear")


def test_season_period_weather_alias() -> None:
    # 直接值键（对齐 weather_conditions 双通道）
    assert eval_condition({"var": "[季节:summer]", "op": "eq"}, _ctx(season_now="summer")) is True
    assert eval_condition({"var": "season", "op": "eq", "param": "summer"}, _ctx(season_now="summer")) is True
    assert eval_condition({"var": "season", "op": "eq", "param": "winter"}, _ctx(season_now="summer")) is False
    assert eval_condition({"var": "[时段:night]", "op": "eq"}, _ctx(period_now="night")) is True
    assert eval_condition({"var": "weather", "op": "eq", "param": "rain"},
                          _ctx(weather_now="rain", map_id="misty_forest")) is True
    # worldtime 鸭子类型（缺方法/缺 map_id → fail-safe False）
    wt = _StubWorldTime()
    assert eval_condition({"var": "season", "op": "eq", "param": "summer"}, _ctx(worldtime=wt)) is True
    assert eval_condition({"var": "period", "op": "eq", "param": "night"}, _ctx(worldtime=wt)) is True
    assert eval_condition({"var": "weather", "op": "eq", "param": "rain"},
                          _ctx(worldtime=wt, map_id="misty_forest")) is True
    assert eval_condition({"var": "weather", "op": "eq", "param": "rain"}, _ctx(worldtime=wt)) is False


def test_time_derived_from_period() -> None:
    ctx = _ctx(period_now="night")
    assert eval_condition({"var": "time", "op": "eq", "value": "night"}, ctx) is True
    assert eval_condition({"var": "is_night", "op": "is", "value": True}, ctx) is True
    assert eval_condition({"var": "is_day", "op": "is", "value": True}, ctx) is False


# ---------------------------------------------------------------------------
# 其它键：职业/熟练/声望/好感 + x_ 扩展
# ---------------------------------------------------------------------------
def test_job_joblevel_prof_reputation_affection() -> None:
    ctx = _ctx(job="剑士", job_level=3, prof_level={"采集": 4},
               reputation={"委托板": 3, "global": 2}, affection={"老周": 7})
    assert eval_condition({"var": "job", "op": "eq", "value": "剑士"}, ctx) is True
    assert eval_condition({"var": "job_level", "op": "ge", "value": 3}, ctx) is True
    assert eval_condition({"var": "prof_level", "op": "ge", "value": 4, "param": "采集"}, ctx) is True
    assert eval_condition({"var": "prof_level", "op": "ge", "value": 5, "param": "采集"}, ctx) is False
    assert eval_condition({"var": "reputation", "op": "ge", "value": 3, "param": "委托板"}, ctx) is True
    assert eval_condition({"var": "reputation", "op": "ge", "value": 2}, ctx) is True  # param 缺省=全局
    assert eval_condition({"var": "affection", "op": "ge", "value": 7, "param": "老周"}, ctx) is True
    assert eval_condition({"var": "affection", "op": "ge", "value": 8, "param": "老周"}, ctx) is False
    # 标量形态
    assert eval_condition({"var": "prof_level", "op": "ge", "value": 3}, _ctx(prof_level=5)) is True
    assert eval_condition({"var": "reputation", "op": "ge", "value": 2}, _ctx(reputation=4)) is True


def test_quest_predicates() -> None:
    ctx = _ctx(quest_active={"q_ore_20": True}, quest_completed={"q_sword": True},
               quest_state={"q_ore_20": "doing"})
    assert eval_condition({"var": "has_quest", "op": "is", "value": "q_ore_20"}, ctx) is True
    assert eval_condition({"var": "has_quest", "op": "is", "value": "q_other"}, ctx) is False
    assert eval_condition({"var": "quest_completed", "op": "is", "value": "q_sword"}, ctx) is True
    assert eval_condition({"var": "quest_completed", "op": "is", "value": "q_ore_20"}, ctx) is False
    assert eval_condition({"var": "quest_state", "op": "eq", "value": "doing", "param": "q_ore_20"}, ctx) is True
    # 集合形态
    assert eval_condition({"var": "has_quest", "op": "is", "value": "q_ore_20"},
                          _ctx(quest_active={"q_ore_20"})) is True


def test_x_extension() -> None:
    ctx = _ctx(ext_vars={"x_my_flag": 1})
    assert eval_condition({"var": "x_my_flag", "op": "ge", "value": 1}, ctx) is True
    assert eval_condition({"var": "x_my_flag", "op": "ge", "value": 2}, ctx) is False
    # 未定义扩展键 → fail-safe False
    assert eval_condition({"var": "x_other", "op": "ge", "value": 1}, ctx) is False
    assert eval_condition({"var": "x_other", "op": "ge", "value": 1}, _ctx()) is False


# ---------------------------------------------------------------------------
# 校验器：结构红拦 + 旧格式/未登记事件黄提示（NPC 4.5 只建议不限制）
# ---------------------------------------------------------------------------
def test_validate_condition_ok() -> None:
    rep = _Report()
    validate_condition({"var": "level", "op": "ge", "value": 10}, rep)
    assert rep.errors == []


def test_validate_condition_unknown_var_red() -> None:
    rep = _Report()
    validate_condition({"var": "nope", "op": "ge", "value": 1}, rep)
    assert "var_not_registered" in _rules(rep)


def test_validate_condition_illegal_op_red() -> None:
    rep = _Report()
    validate_condition({"var": "level", "op": "gte", "value": 1}, rep)
    assert "op_invalid" in _rules(rep)


def test_validate_condition_legacy_format_yellow() -> None:
    rep = _Report()
    validate_condition({"type": "collect", "var": "level", "op": "ge", "value": 10}, rep)
    assert "legacy_format" in _rules(rep)


def test_validate_condition_event_not_registered_yellow() -> None:
    rep = _Report()
    validate_condition({"var": "[事件:future_patch]", "op": "ge", "value": 1}, rep)
    assert "event_not_registered" in _rules(rep)
    rep2 = _Report()
    validate_condition({"var": "[事件:签到]", "op": "ge", "value": 1}, rep2)
    assert rep2.errors == []


def test_validate_condition_nested_and_bad_shape() -> None:
    rep = _Report()
    validate_condition({"all": [{"var": "level", "op": "ge", "value": 10},
                                {"var": "nope", "op": "ge", "value": 1}]}, rep)
    assert "var_not_registered" in _rules(rep)
    rep2 = _Report()
    validate_condition(42, rep2)
    assert "condition_not_object" in _rules(rep2)
    rep3 = _Report()
    validate_condition({}, rep3)
    assert "condition_empty" in _rules(rep3)
