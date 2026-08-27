"""故障注入脚本④ fault_inject_formula.py（M6 批5·路B · D5 FLT 件套）——TC-FLT-12/13 公式兜底 0。

依据：
  - 细化_M6_故障注入.md（D5）§五：FLT-22（注入点 = 公式含死循环/非法变量/未注册占位符/超长>4KB/
    黑名单命中）/ FLT-23（兜底 0 不崩：evaluate() 返回 0.0 + warning，进程不崩）/
    FLT-24（条件不满足不崩溃：条件表达式引用未注册字段/求值异常 → 默认「条件不满足」安全失败，
    战斗不崩溃、可继续行动）+ TC-FLT-12/13
  - formula_engine.py L957-1027（evaluate_detail L957-1019 / evaluate L1022-1027：黑名单/未知占位符/
    超时/结果类型非法 → 0.0 + warning；AST 黑名单 constructor/Function/eval/globalThis/process；
    长度 ≤4096B；10ms 超时 watchdog）
  - 细化_1c3_连段测试集 TC-13 L46（条件表达式引用未注册字段/求值异常 → 求值失败默认「条件不满足」
    安全失败，战斗不崩溃、可继续行动）
  - 细化_5d_测试体系总纲 L205-208（注入隔离纪律：独立 fixture、夹具内注入）

工程决策（对齐 D5 §五 / 任务批5·路B）：
  - 直接调 formula_engine.evaluate/evaluate_detail 断言兜底 0 + warning（FLT-23）
  - 战斗条件表达式引用未注册字段 → combo.evaluate_condition 返回 False（默认条件不满足）+ 随后正常
    条件/行动仍正确（战斗不崩、可继续行动，FLT-24 / 1c3 TC-13 同断言）
  - 恢复路径 = 纯函数无副作用（D5 §五：无副作用（纯函数），无需 finally）；独立 ctx fixture（FLT-04）

零 NoneBot import；纯 core 层调用。
"""

from __future__ import annotations

import pytest

from qbot_rpg.core.combo import ConditionCtx, ComboEngine, evaluate_condition
from qbot_rpg.core.formula_engine import (
    FORMULA_MAX_LENGTH,
    EvaluatorCtx,
    evaluate,
    evaluate_detail,
)


@pytest.fixture
def ctx() -> EvaluatorCtx:
    """独立求值上下文 fixture（FLT-04）：frozen 纯数据，每用例独立构造，互不串扰。"""
    return EvaluatorCtx(
        attacker={"atk": 100, "max_hp": 500, "hp": 400},
        target={"hp_pct": 0.5},
        battle={"round": 3},
        rng_state=1,
    )


# ---------------------------------------------------------------------------------------
# TC-FLT-12：死循环 / 非法变量 / 超长 / 黑名单 → 兜底 0（FLT-22/23）
# ---------------------------------------------------------------------------------------
def test_flt12_dead_loop_fallback_zero(ctx: EvaluatorCtx) -> None:
    """三要素注释（FLT-03）：
    注入点 = 死循环公式 `while(true){}`（FLT-22，10ms 超时 watchdog 真实中断）；
    断言对象 = evaluate_detail 返回 0.0 + warning 非空，evaluate() 返回 0.0（进程不崩，FLT-23，
            formula_engine L957-1027）；
    恢复路径 = 纯函数无副作用（D5 §五：无副作用（纯函数））。"""
    expr = "while(true){}"
    value, warnings = evaluate_detail(expr, ctx)
    assert value == 0.0, f"死循环公式必须兜底 0.0（got {value}）"
    assert len(warnings) >= 1, "死循环必须产生 warning"
    assert any(w.startswith("eval_failed:") for w in warnings), f"warnings 应含 eval_failed: {warnings}"
    # P2-2 修复（M6 批5B dsh 审查）：锁定 watchdog 真实中断——排除 node 缺失的
    # runner_unavailable 假绿（node 环境缺失时该用例应显式失败而非静默通过）
    assert not any("runner_unavailable" in w for w in warnings), \
        f"node 运行器不可用（环境问题）：{warnings}"
    # 进程不崩：evaluate() 正常返回 0.0（10ms 超时 watchdog 中断，F-3）
    assert evaluate(expr, ctx) == 0.0


def test_flt12_illegal_variable_fallback_zero(ctx: EvaluatorCtx) -> None:
    """三要素注释（FLT-03）：
    注入点 = 非法变量 / 未注册占位符 `[未知字段]`（FLT-22，§四 未知占位符 → 0 + warning）；
    断言对象 = evaluate_detail 返回 0.0 + unknown_placeholder warning，evaluate() 返回 0.0（FLT-23）；
    恢复路径 = 纯函数无副作用（D5 §五）。"""
    expr = "[未知字段]"
    value, warnings = evaluate_detail(expr, ctx)
    assert value == 0.0, f"未注册占位符必须兜底 0.0（got {value}）"
    assert any(w.startswith("unknown_placeholder:[未知字段]") for w in warnings), (
        f"warnings 应含 unknown_placeholder: {warnings}"
    )
    assert evaluate(expr, ctx) == 0.0


def test_flt12_oversized_formula_fallback_zero(ctx: EvaluatorCtx) -> None:
    """三要素注释（FLT-03）：
    注入点 = 超长公式（>4KB，FLT-22，长度上限 FORMULA_MAX_LENGTH=4096）；
    断言对象 = evaluate_detail 返回 0.0 + formula_too_long warning，evaluate() 返回 0.0（FLT-23）；
    恢复路径 = 纯函数无副作用（D5 §五）。"""
    expr = "1 + " * (FORMULA_MAX_LENGTH + 10)
    assert len(expr) > FORMULA_MAX_LENGTH, "前置：载荷必须超 4KB"
    value, warnings = evaluate_detail(expr, ctx)
    assert value == 0.0, f"超长公式必须兜底 0.0（got {value}）"
    assert "formula_too_long" in warnings, f"warnings 应含 formula_too_long: {warnings}"
    assert evaluate(expr, ctx) == 0.0


def test_flt12_blacklist_hit_fallback_zero(ctx: EvaluatorCtx) -> None:
    """三要素注释（FLT-03）：
    注入点 = 黑名单命中（eval / globalThis / process，AST 黑名单，FLT-22）；
    断言对象 = 每个黑名单公式 evaluate_detail 返回 0.0 + blacklist warning，evaluate() 返回 0.0
            （FLT-23，双保险之求值期兜底）；
    恢复路径 = 纯函数无副作用（D5 §五）。"""
    for expr in ("eval('1')", "globalThis.x", "process.exit(1)"):
        value, warnings = evaluate_detail(expr, ctx)
        assert value == 0.0, f"黑名单公式 {expr!r} 必须兜底 0.0（got {value}）"
        assert any(w.startswith("blacklist:") for w in warnings), (
            f"warnings 应含 blacklist: {warnings}"
        )
        assert evaluate(expr, ctx) == 0.0


# ---------------------------------------------------------------------------------------
# TC-FLT-13：条件表达式引用未注册字段 → 条件不满足，战斗不崩、可继续行动（FLT-24 / 1c3 TC-13）
# ---------------------------------------------------------------------------------------
def test_flt13_condition_unregistered_field_not_satisfied() -> None:
    """三要素注释（FLT-03）：
    注入点 = 条件表达式引用未注册字段（未知键 condition 对象，1c3 TC-13 L46）；
    断言对象 = evaluate_condition 返回 False（默认「条件不满足」安全失败，不抛异常，FLT-24）+ 同一
            ctx 随后正常条件仍正确求值（count 满足 → True、无条件 → True，证明引擎不崩、可继续行动）；
    恢复路径 = 纯函数无副作用（D5 §五）。"""
    cctx = ConditionCtx(count=3, target_hp_pct=50.0, round_=2)
    # 引用未注册字段 → 条件不满足（安全失败，不抛异常）
    assert evaluate_condition({"unregistered_field": {"eq": 1}}, cctx) is False
    assert evaluate_condition({"no_such_status_field": {"has": ["x"]}}, cctx) is False
    # 引擎仍可继续正常求值（战斗不崩、可继续行动）
    assert evaluate_condition({"count": {"min": 3}}, cctx) is True
    assert evaluate_condition({"count": 3}, cctx) is True
    assert evaluate_condition(None, cctx) is True


def test_flt13_battle_continues_after_failed_condition() -> None:
    """三要素注释（FLT-03）：
    注入点 = 战斗内派生步骤条件引用未注册字段（未知键，apply_action 求值该条件）；
    断言对象 = 该派生不可用（pending_derivations ok=False、原因「条件不满足」）但连段行动仍成功结算
            （ComboActionResult.ok=True、count_after=1、form_id=基技能 a）——战斗不崩溃、可继续行动
            （FLT-24 / 1c3 TC-13 同断言）；
    恢复路径 = 纯函数无副作用（ComboEngine 无全局状态，D5 §五）。"""
    defs = {
        "c1": {
            "id": "c1", "name": "火之连", "trigger_skill": "a", "max_combo": 3,
            "max_combo_behavior": "reset",
            "steps": [
                # 步①：条件引用未注册字段（FLT-24 注入）
                {"from": "a", "to": "b", "mode": "replace",
                 "condition": {"unregistered_skill_field": {"min": 1}}},
                # 步②：正常条件（对照：满足时仍可用）
                {"from": "a", "to": "c", "mode": "replace", "condition": {"count": 2}},
            ],
        },
        "a": {"id": "a", "name": "火球", "tag": "combo"},
        "b": {"id": "b", "name": "大火球", "tag": "combo"},
        "c": {"id": "c", "name": "龙息", "tag": "combo"},
    }
    eng = ComboEngine(defs=defs, resolver=lambda id_, kind: defs.get(id_ or ""))
    snap = {
        "combo_state": {
            "player": {"chain_id": "c1", "chain_name": "火之连", "count": 0,
                       "hold": False, "step_index": -1},
            "enemy": {},
        },
        "turn": 1,
        "player": {"max_hp": 500, "hp": 300},
        "enemy": {"max_hp": 400, "hp": 200},
        "status_state": {"player": [], "enemy": []},
    }

    # 未注册字段条件 → 派生不可用（安全失败），但行动仍成功结算
    result = eng.apply_action("player", {"skill_id": "a", "tag": "combo"}, snap)
    assert result.ok is True, "未注册字段条件不得让行动崩溃（FLT-24）"
    assert result.derivation is False, "未注册字段条件派生应不可用（不触发派生）"
    assert result.form_id == "a", "应降级为基技能 a 结算"
    assert result.count_after == 1, "连段技仍推进计数（战斗不崩、可继续行动）"
    # 派生明细：未注册字段步 ok=False、原因「条件不满足」；正常条件步（count>=2 未达）亦不满足
    pending = eng.pending_derivations("player", snap)
    by_skill = {d.to_skill: d for d in pending}
    assert "b" in by_skill and by_skill["b"].ok is False, "未注册字段条件步必须不可用"
    assert "条件不满足" in by_skill["b"].reason, "应标注原因（1c2 TC-04 置灰）"


def test_flt12_result_type_fallback_zero(ctx: EvaluatorCtx) -> None:
    """P2-4 补测（M6 批5B dsh 审查 / FLT-23 描述面补角）：结果类型非法 → 兜底 0 + result_type 警告。

    三要素注释：
      注入点 = 公式 `1/0`（Python 快路径 ZeroDivisionError → 降级 Node → JS 均值 Infinity
        → result_type:non_finite 分支，formula_engine L886-898）；
      断言对象 = evaluate_detail 返回 0.0 + warnings 含 result_type: 前缀（进程不崩）；
      恢复路径 = 纯函数无副作用（D5 §五）。"""
    value, warnings = evaluate_detail("1/0", ctx)
    assert value == 0.0, f"结果类型非法必须兜底 0.0（got {value}）"
    assert any("result_type" in w for w in warnings), f"warnings 应含 result_type 标记: {warnings}"
    assert evaluate("1/0", ctx) == 0.0
