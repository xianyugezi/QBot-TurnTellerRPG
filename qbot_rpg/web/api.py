"""Web 编辑器外壳 API（M6 实装 · 本里程碑仅骨架）。

职责（细化_3a D-05 / §2.1）：FastAPI 编辑器外壳——读写 content 包（热重载）、
core 模拟试玩、storage 运营页只读。依赖方向 web → {content, core, storage, data}，
任何层不得反向依赖 web；**不 import nonebot**（3a R1 语境下 web 亦零 NoneBot，D-05）。

M6 实装依据：细化_5a_编辑器契约（页面/操作） / 细化_5a2_编辑器扩展页 / 细化_3e2_热重载契约
（编辑器保存 → 原子写 → 热重载）；launcher 联动见 web/launcher_hint.py（M6）。

fastapi 属 M6 运行时依赖；本里程碑以惰性/防御方式占位，保证不装 fastapi 时包仍可 import
（pytest 核心层不触碰 web 路由）。
"""
from __future__ import annotations

from typing import Any, Optional

try:  # M6 才接运行时依赖；缺失时降级为占位（不破坏 M0 单测可导入性）
    from fastapi import APIRouter, FastAPI  # type: ignore
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment,misc]
    APIRouter = None  # type: ignore[assignment,misc]
    _HAS_FASTAPI = False

__all__ = ["create_app", "iter_routes", "FastAPI", "APIRouter"]


def create_app(state: Optional[Any] = None) -> Any:
    """M6 实装：构造 FastAPI 应用（/packs /preview 等路由；D-05 编辑器外壳）。"""
    raise NotImplementedError("M6 实装：FastAPI 编辑器路由（细化_5a / 细化_3e2）")


def iter_routes(app: Any) -> Any:
    """M6 实装：遍历注册路由（供插件入口拉起子进程后健康检查/日志）。"""
    raise NotImplementedError("M6 实装：路由枚举（细化_5a）")
