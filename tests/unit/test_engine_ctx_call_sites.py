"""R3（复核修复 2026-09-12）：新增 `ctx` 形参的引擎方法——调用点必须传 ctx。

背景（复核报告 R3）：`alchemy_battle.instant_eligible` / `alchemy_deep.deep_snapshot` /
`alchemy_helper.parse_task_spec` 新增了可选 `ctx` 形参；漏传时 `tpl_of` 回落默认表，
**不报错**，内容包覆盖静默失效。

覆盖：
  ① AST 门禁：全仓所有对这三个方法的**调用点**必须显式传 ctx（`ctx=` 或
     `parse_task_spec(spec, ctx)` 的位置参数）；`instant_eligible` 目前无活调用点
     （M6 死迁移，另案；一旦新增调用点未传 ctx 本测试即失败）。
  ② 行为：`instant_eligible(ctx=...)` 的内容包覆盖确实贯穿到 `tpl_of`。
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
_SRC = REPO / "qbot_rpg"

#: 方法名 → ctx 传递形态（"kw" 只有 keyword-only；"pos_or_kw" 位置或关键字皆可）
_CTX_METHODS = {
    "instant_eligible": "kw",
    "deep_snapshot": "kw",
    "parse_task_spec": "pos_or_kw",
}


def _iter_ctx_method_calls():
    """遍历 qbot_rpg 下对 _CTX_METHODS 的调用点 → (相对路径, 行号, 方法名, Call)。"""
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if name in _CTX_METHODS:
                yield path.relative_to(REPO).as_posix(), node.lineno, name, node


def _passes_ctx(name: str, call: ast.Call) -> bool:
    if any(kw.arg == "ctx" for kw in call.keywords):
        return True
    if _CTX_METHODS[name] == "pos_or_kw" and len(call.args) >= 2:
        return True
    return False


def test_all_ctx_capable_engine_call_sites_pass_ctx() -> None:
    """R3①：三个新增 ctx 形参方法的全部调用点必须传 ctx（防新调用点漏传）。"""
    missing: list[str] = []
    seen: dict[str, int] = {}
    for rel, lineno, name, call in _iter_ctx_method_calls():
        seen[name] = seen.get(name, 0) + 1
        if not _passes_ctx(name, call):
            missing.append(f"{rel}:{lineno} {name}(...) 未传 ctx")
    assert not missing, "调用点漏传 ctx（内容包覆盖将静默失效）：\n" + "\n".join(missing)
    # 防「扫描不到任何调用点」导致门禁空转：两个活调用点必须被覆盖。
    assert seen.get("deep_snapshot", 0) >= 1, "deep_snapshot 调用点扫描为空（AST 门禁失效）"
    assert seen.get("parse_task_spec", 0) >= 1, "parse_task_spec 调用点扫描为空（AST 门禁失效）"


def test_instant_eligible_ctx_override_reaches_tpl_of() -> None:
    """R3②：`instant_eligible(ctx=...)` 的内容包覆盖生效（证明 ctx 真被消费）。"""
    from qbot_rpg.core.alchemy_battle import BattleAlchemyEngine

    eng = BattleAlchemyEngine()
    # 默认：表默认文案
    default = eng.instant_eligible({}, in_battle=False, battle_alchemy_used=0)
    assert default["ok"] is False and default["reason"] == "not_in_battle"
    assert "仅战斗中可即时调合" in default["message"]

    # 内容包覆盖同名键 → 走覆盖文案（ctx 传递贯穿到 tpl_of）
    overridden = eng.instant_eligible(
        {}, in_battle=False, battle_alchemy_used=0,
        ctx={"templates": {"alchemy_engine_battle_not_in_battle": "【覆盖】仅战斗"}},
    )
    assert overridden["message"] == "【覆盖】仅战斗"


def test_parse_task_spec_signature_accepts_ctx() -> None:
    """R3 补：`parse_task_spec(spec, ctx)` 位置传参与关键字传参等价（调用点契约）。"""
    from qbot_rpg.core.alchemy_helper import parse_task_spec

    spec = "火晶石=2"
    assert parse_task_spec(spec, None) == parse_task_spec(spec, ctx=None)
