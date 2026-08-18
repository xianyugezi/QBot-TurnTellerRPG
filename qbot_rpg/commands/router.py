"""指令路由壳 Router（M4 实装 · 本里程碑仅接口签名）。

职责（细化_3a §1.3 壳层职责清单 · 唯一 NoneBot 适配器接触点）：
  指令注册（on_command）/ 权限三级（机主/GM/普通，无 GM 权限静默）/ 频率限制
  （全局 ≥1s / 单群 ≤20 条·分 / 单日上限）、防抖。
M4 实装依据：细化_3c_指令解析契约 / 细化_4f_基础指令组契约 / 细化_5b_GM指令契约 /
【框架】L1604（NoneBot2 on_command 注册）；【规则】L455-462/L473-480。

本里程碑（M0）**零 nonebot import**（3a R1 测试前提：pytest 可脱离平台跑核心层），
全部签名以 typing 自含；M4 引入 nonebot 后仍保持「只在此层 import nonebot」（3a R2）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

__all__ = ["Router", "register_command", "CommandSpec"]

# 权限三级（细化_3a §1.3；【规则】L455-462）
PERM_OWNER = "owner"     # 机主
PERM_GM = "gm"           # GM
PERM_USER = "user"       # 普通

_NOT_IMPL_MSG = "M4 实装：指令注册/权限/频率（细化_3c / 细化_4f / 细化_5b / 细化_3a §1.3）"


class CommandSpec:
    """指令静态描述（供注册表/帮助/权限对照；M4 由 on_command 消费）。

    name: 指令名（不含前导 /）；aliases: 别名；permission: 权限等级；
    handler: 处理器（解析 → 核心层 → 渲染 → sender 发送）签名占位。
    """

    def __init__(
        self,
        name: str,
        *,
        aliases: Optional[List[str]] = None,
        permission: str = PERM_USER,
        cooldown_seconds: float = 0.0,
        handler: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.name = name
        self.aliases: List[str] = list(aliases or [])
        self.permission = permission
        self.cooldown_seconds = cooldown_seconds
        self.handler = handler

    def matches(self, raw: str) -> bool:
        """M4 实装：指令名/别名匹配（触发模式 @/前缀/直接/敏感词，【框架】L1604）。"""
        raise NotImplementedError(_NOT_IMPL_MSG)


class Router:
    """指令路由注册表（M4 接线 on_command；本里程碑仅签名，零 nonebot）。"""

    def __init__(self) -> None:
        self._specs: Dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def dispatch(self, raw: str, event: Any) -> Any:
        """M4 实装：解析 → 权限/频率 → 分发 → 返回渲染后 str（经 sender 发送）。"""
        raise NotImplementedError(_NOT_IMPL_MSG)


def register_command(
    name: str,
    *,
    aliases: Optional[List[str]] = None,
    permission: str = PERM_USER,
    handler: Optional[Callable[..., Any]] = None,
) -> CommandSpec:
    """M4 实装：NoneBot on_command 注册包壳（唯一在 commands/ 接触 nonebot 的位置之一）。"""
    return CommandSpec(name, aliases=aliases, permission=permission, handler=handler)
