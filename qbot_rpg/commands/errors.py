"""领域异常 → 人话翻译壳 Errors（M4 实装 · 本里程碑仅接口签名）。

职责（细化_3a §1.3 / §5.4 R4）：捕获 core/world 抛出的领域异常（BattleNotInProgress 等），
翻译为统一错误模板（细化_3d §五 TPL-12/13/14：指令不正确 / 条件不满足 / 资源不足），
「原因 + 正确用法 + 下一步」句式（【规则】L117；【框架】L1349-1357）。
唯一允许静默的场景：无 GM 权限使用 GM 指令（【规则】L114-116，注释注明设计决策）。

本里程碑（M0）零 nonebot import（3a R1）；模板常量在此登记，供 M4 errors 实现引用。
"""
from __future__ import annotations

from typing import Any, Optional, Type

__all__ = [
    "errors",
    "translate_error",
    "TPL_ERR_BAD_COMMAND",
    "TPL_ERR_CONDITION",
    "TPL_ERR_LACK_RESOURCE",
]

# 统一错误模板（细化_3d §五 TPL-12/13/14；禁止各系统自造文案 D-04）
TPL_ERR_BAD_COMMAND: str = "❌ 指令不正确：{fragment}。输入 /帮助 查看可用指令。"
TPL_ERR_CONDITION: str = "❌ 条件不满足：{name}（当前 {current}，需要 {required}）"
TPL_ERR_LACK_RESOURCE: str = "❌ 资源不足：需要 {resource}{amount}，当前 {current}"


def errors() -> Type[Exception]:
    """M4 实装：领域异常类型（BattleNotInProgress 等在此定义）。占位返回 Exception 基类。"""
    raise NotImplementedError(
        "M4 实装：领域异常定义映射（细化_3a §5.4 / 细化_3c）"
    )


def translate_error(exc: Any) -> Optional[str]:
    """M4 实装：领域异常 → 统一人话文案；无 GM 权限场景返回 None（静默）。"""
    raise NotImplementedError("M4 实装：领域异常 → TPL-12/13/14（细化_3d §五）")
