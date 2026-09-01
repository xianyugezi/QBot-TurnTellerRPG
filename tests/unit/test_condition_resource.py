"""6c 资源轴变量与条件泛化单测（tests/unit/test_condition_resource.py · M13 批9 路9B）。

覆盖（细化_6c §0.1 A7/A9 + D-04 池级引用 + §1.5 条件行 + V5 + 摸底 §九 dev-7）：
  1. VAR_ALIASES 登记 [我方资源:{T}] / [对方资源:{T}] → var=resource（内嵌目标提取）
  2. REGISTERED_VARS 登记 resource / [我方资源:<资源ID>] / [对方资源:<资源ID>]
  3. var=resource 四键条件：我方（player）数值型轴 ge/gt/le/lt/eq/ne/between
  4. 我方子池型池级引用 [我方资源:element_energy.fire]（D-04）
  5. 我方子池型轴 ID（无池后缀）= 各池和（展示总量，D-04）
  6. 对方（enemy）资源读取（[对方资源:rage] + var=resource param 我方缺省对照）
  7. 别名路径缺省 = 我方（player）（[我方资源:rage]）
  8. 缺省 fail-safe：resource_state 缺失 / 该侧缺段 / 轴未注册 / 池未注册 /
     数值型轴带池后缀 / param 缺失 → False（D-03 / V5）
  9. 校验器：var=resource 缺 param 红拦提示；[我方资源:X] 别名注册不拦
  10. normalize_var 直接识别资源别名

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性；不碰兄弟文件。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.engine.condition_engine import (
    REGISTERED_VARS,
    VAR_ALIASES,
    eval_condition,
    normalize_var,
    validate_condition,
)

# ---------------------------------------------------------------------------
# fixture：resource_state 上下文（对齐 6c §1.4 快照形态：数值型单键 /
# 子池型池级展开 D-04）
# ---------------------------------------------------------------------------


def _ctx(**kw: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "resource_state": {
            "player": {
                "rage": 72,  # 数值型（狂战士先例【狂战士 L81/L427】）
                "element_energy": {"fire": 2, "water": 1, "wind": 0},  # 池级展开（D-04）
            },
            "enemy": {"rage": 0},
        },
    }
    base.update(kw)
    return base


class _Report:
    """validate_condition 收集器（鸭子类型：_err 与 validator._Checker 同签名）。"""

    def __init__(self) -> None:
        self.errors: list = []

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _rules(rep: _Report) -> list:
    return [e["detail"].get("rule") for e in rep.errors]


# ---------------------------------------------------------------------------
# ① 注册：VAR_ALIASES / REGISTERED_VARS（A7/A9 + V5 载体）
# ---------------------------------------------------------------------------


def test_var_aliases_resource_registered() -> None:
    """[我方资源:{T}] / [对方资源:{T}] 已登记 → var=resource（6c A9 / D-04）。"""
    assert VAR_ALIASES["[我方资源:{T}]"] == ("resource", "{T}")
    assert VAR_ALIASES["[对方资源:{T}]"] == ("resource", "{T}")


def test_registered_vars_resource_keys() -> None:
    """REGISTERED_VARS 登记 resource 与两个资源变量键（NPC 4.3 键空间 + 6c A9）。"""
    assert REGISTERED_VARS.get("resource") == "资源类"
    assert REGISTERED_VARS.get("[我方资源:<资源ID>]") == "资源类"
    assert REGISTERED_VARS.get("[对方资源:<资源ID>]") == "资源类"


def test_normalize_var_resource_alias() -> None:
    """normalize_var 识别资源别名并提取内嵌目标（param 缺省时作目标，补白 2）。"""
    assert normalize_var("[我方资源:rage]") == ("resource", "rage")
    assert normalize_var("[对方资源:rage]") == ("resource", "rage")
    # 池级引用（D-04）：内嵌目标 = 轴 ID + 池名
    assert normalize_var("[我方资源:element_energy.fire]") == ("resource", "element_energy.fire")


# ---------------------------------------------------------------------------
# ② var=resource 我方（player）数值型（A7：gt/ge/lt/le/eq/ne/between + param）
# ---------------------------------------------------------------------------


def test_resource_ge_player_numeric() -> None:
    """{var:resource, op:ge, value:50, param:rage}：我方怒气 72 ≥ 50 → True。"""
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 50, "param": "rage"}, _ctx()
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 72, "param": "rage"}, _ctx()
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 73, "param": "rage"}, _ctx()
    ) is False


def test_resource_gt_lt_le_player_numeric() -> None:
    """gt/lt/le 同口径数值比较（rage=72）。"""
    c = _ctx()
    assert eval_condition({"var": "resource", "op": "gt", "value": 71, "param": "rage"}, c) is True
    assert eval_condition({"var": "resource", "op": "gt", "value": 72, "param": "rage"}, c) is False
    assert eval_condition({"var": "resource", "op": "lt", "value": 73, "param": "rage"}, c) is True
    assert eval_condition({"var": "resource", "op": "le", "value": 72, "param": "rage"}, c) is True
    assert eval_condition({"var": "resource", "op": "le", "value": 71, "param": "rage"}, c) is False


def test_resource_eq_ne_between_player_numeric() -> None:
    """eq/ne/between：宽松数值相等 + 区间（含乱序自动排序，补白 7）。"""
    c = _ctx()
    assert eval_condition({"var": "resource", "op": "eq", "value": 72, "param": "rage"}, c) is True
    assert (
        eval_condition({"var": "resource", "op": "eq", "value": "72", "param": "rage"}, c)
        is True
    )
    assert eval_condition({"var": "resource", "op": "ne", "value": 71, "param": "rage"}, c) is True
    assert eval_condition({"var": "resource", "op": "ne", "value": 72, "param": "rage"}, c) is False
    assert eval_condition(
        {"var": "resource", "op": "between", "value": [60, 80], "param": "rage"}, c
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "between", "value": [80, 60], "param": "rage"}, c
    ) is True  # 区间乱序自动排序
    assert eval_condition(
        {"var": "resource", "op": "between", "value": [80, 90], "param": "rage"}, c
    ) is False


# ---------------------------------------------------------------------------
# ③ 池级引用（D-04）：池级 [我方资源:element_energy.fire] + 轴 ID 展示总量
# ---------------------------------------------------------------------------


def test_resource_pool_level_player() -> None:
    """池级引用：fire=2 ≥ 2 → True；ge 3 → False；eq 0（wind）→ True。"""
    c = _ctx()
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 2, "param": "element_energy.fire"}, c
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 3, "param": "element_energy.fire"}, c
    ) is False
    assert eval_condition(
        {"var": "resource", "op": "eq", "value": 0, "param": "element_energy.wind"}, c
    ) is True


def test_resource_pool_axis_total_player() -> None:
    """子池型轴 ID（无池后缀）= 各池和（展示总量，D-04）：2+1+0=3。"""
    c = _ctx()
    assert eval_condition(
        {"var": "resource", "op": "eq", "value": 3, "param": "element_energy"}, c
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 3, "param": "element_energy"}, c
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 4, "param": "element_energy"}, c
    ) is False


# ---------------------------------------------------------------------------
# ④ 对方（enemy）资源读取（[对方资源:rage] 别名 + 我方缺省对照）
# ---------------------------------------------------------------------------


def test_enemy_resource_alias() -> None:
    """[对方资源:rage]（别名 → 内嵌目标 → 对方=enemy）：enemy.rage=0。"""
    c = _ctx()
    assert eval_condition({"var": "[对方资源:rage]", "op": "eq", "value": 0}, c) is True
    assert eval_condition({"var": "[对方资源:rage]", "op": "ge", "value": 1}, c) is False


def test_enemy_resource_var_resource_side_prefix() -> None:
    """var=resource 支持侧前缀目标（我方:/对方:，_RESOURCE_SIDE_MAP 映射）。"""
    c = _ctx()
    assert eval_condition(
        {"var": "resource", "op": "eq", "value": 0, "param": "对方:rage"}, c
    ) is True
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 1, "param": "对方:rage"}, c
    ) is False
    # 我方前缀 = player 同值
    assert eval_condition(
        {"var": "resource", "op": "eq", "value": 72, "param": "我方:rage"}, c
    ) is True


def test_alias_defaults_to_player() -> None:
    """[我方资源:rage] 别名路径 = player 侧（缺省我方）。"""
    c = _ctx()
    assert eval_condition({"var": "[我方资源:rage]", "op": "ge", "value": 50}, c) is True
    assert eval_condition({"var": "[我方资源:rage]", "op": "eq", "value": 72}, c) is True


# ---------------------------------------------------------------------------
# ⑤ 缺省 fail-safe（D-03 / V5）：任何异常形态 → False 不抛错
# ---------------------------------------------------------------------------


def test_resource_missing_context_fail_safe() -> None:
    """resource_state 整体缺失 → False（D-03 求值失败=不满足）。"""
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 1, "param": "rage"}, {}
    ) is False
    assert eval_condition({"var": "[我方资源:rage]", "op": "ge", "value": 1}, {}) is False


def test_resource_side_missing_fail_safe() -> None:
    """该侧（enemy）无资源段 → False。"""
    c = _ctx()
    c["resource_state"] = {"player": {"rage": 72}}
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 1, "param": "对方:rage"}, c
    ) is False


def test_resource_unregistered_axis_fail_safe() -> None:
    """轴未注册/未初始化（如 [对方资源:heat]）→ False（V5 黄提示在加载期拦截）。"""
    c = _ctx()
    assert eval_condition({"var": "[对方资源:heat]", "op": "ge", "value": 1}, c) is False
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 1, "param": "rage"}, _ctx()
    ) is True  # 对照：已注册轴正常


def test_resource_unregistered_pool_fail_safe() -> None:
    """池名未注册（element_energy.earth）→ False；数值型轴带池后缀（rage.rage）→ False。"""
    c = _ctx()
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 1, "param": "element_energy.earth"}, c
    ) is False
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 1, "param": "rage.rage"}, c
    ) is False


def test_resource_missing_param_fail_safe() -> None:
    """var=resource 无 param / param 非字符串 → False（param 维度缺失，D-03）。"""
    assert eval_condition({"var": "resource", "op": "ge", "value": 1}, _ctx()) is False
    assert eval_condition({"var": "resource", "op": "ge", "value": 1, "param": 42}, _ctx()) is False


# ---------------------------------------------------------------------------
# ⑥ 校验器（validate_condition）：var=resource 缺 param 红拦提示；别名不拦
# ---------------------------------------------------------------------------


def test_validate_resource_missing_param_red_block() -> None:
    """{var:resource} 缺 param → 红拦 resource_param_missing（param 维度必填）。"""
    rep = _Report()
    validate_condition({"var": "resource", "op": "ge", "value": 50}, rep)
    assert "resource_param_missing" in _rules(rep)


def test_validate_resource_alias_no_error() -> None:
    """[我方资源:rage] / [对方资源:rage] 别名 var 校验通过（注册键，零报错）。"""
    rep = _Report()
    validate_condition({"var": "[我方资源:rage]", "op": "ge", "value": 50}, rep)
    validate_condition({"var": "[对方资源:rage]", "op": "eq", "value": 0}, rep)
    assert rep.errors == []
