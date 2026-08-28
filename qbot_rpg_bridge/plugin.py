"""M7 A-04 NoneBot 插件入口（qbot_rpg_bridge 唯一 NoneBot 依赖点）。

设计依据（docs/细化/细化_M7_装配层契约.md 四、A-04 RA-11）：
  - 结构：on_message 事件 → build_event 字段映射 → run_bridge（调
    qbot_rpg.assembly.runner.run_command，async）→ 字符串回复 → bot.send 回 QQ。
  - 桥接层要薄：本模块**不写业务**，只做 NoneBot 接线（映射/驱动/发送）；
    业务逻辑全部在 qbot_rpg 内核（run_command 已封装路由/上下文/幂等/队列）。
  - 会话路由：对话激活时纯数字/继续/离开 **直接透传**——run_command 内
    route_and_expand 已处理 ROUTE_SESSION，本层零会话状态机、零拦截。

NoneBot 实际接线以 try-import 保护（设计纪律 RA-11「无 NoneBot 环境」）：
  - 无 nonebot 环境（CLI/测试/装配冒烟）：import 本模块不报错（HAS_NONEBOT=False），
    register_plugin() 抛 RuntimeError 提示；_on_message 仍可脱离 NoneBot 以
    FakeBot/FakeEvent 直调单测（纯函数 + 鸭子类型，零 nonebot 依赖）。
  - 有 nonebot 环境：NoneBot 插件加载即 import 本模块 → 模块级 register_plugin()
    完成 on_message 注册（NoneBot 标准插件形态）。

deps 注入：装配完成后调用 set_deps(app_deps)（bootstrap/router_setup 产物），
on_message 处理器从模块级单例读取（NoneBot 单进程模型，全局即可）。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from qbot_rpg_bridge import run_bridge

try:
    from nonebot import on_message

    HAS_NONEBOT = True
except ImportError:  # pragma: no cover —— 无 NoneBot 环境（CLI/测试/冒烟）
    on_message = None  # type: ignore[assignment]
    HAS_NONEBOT = False

# on_message 处理器优先级（block=False 不阻塞其它处理器；run_command 内路由裁决）
_PRIORITY = 10

# 装配依赖单例（NoneBot 启动装配后经 set_deps 注入；未注入 → 消息静默忽略）
_deps: Any = None
_runner: Optional[Callable] = None

__all__ = [
    "HAS_NONEBOT",
    "set_deps",
    "get_deps",
    "register_plugin",
    "_on_message",
]


def set_deps(deps: Any, *, runner: Optional[Callable] = None) -> None:
    """注入装配依赖（bootstrap 装配完成后调用；模块级单例）。

    入参 deps: AssemblyDeps（含 repo/router/queue 等，run_command 消费）；
    runner: 可选覆盖 runner（async (event_dict, deps) -> str，测试/Fake 注入）。
    核心逻辑: 模块级赋值（NoneBot 单进程模型，全局单例即可，确定性）。
    """
    global _deps, _runner
    _deps = deps
    _runner = runner


def get_deps() -> Any:
    """当前装配依赖（未注入 → None；装配前消息由 _on_message 静默忽略）。"""
    return _deps


async def _on_message(bot: Any, event: Any) -> None:
    """on_message 处理器：build_event → run_bridge → bot.send（薄接线）。

    入参 bot: NoneBot Bot（鸭式，需 send(event, text)）；event: 群消息事件
    （鸭式，build_event 消费属性）。
    出参 None（回复经 bot.send；空回复不发；未装配/异常 → TPL-12 兜底不崩）。
    核心逻辑:
      ① _deps 未注入 → 静默忽略（装配前不响应，不抛不崩）；
      ② reply = await run_bridge(event, _deps, runner=_runner)——内核返回回复串
        （空串 = 无回复/忽略/会话子词/GM 静默）；
      ③ reply 非空 → await bot.send(event, reply) 回 QQ。
      异常兜底: 未预期异常 → TPL-12 人话（惰性 import format_tpl12），不裸崩。
    """
    deps = _deps
    if deps is None:
        return  # 未装配：静默忽略
    try:
        reply = await run_bridge(event, deps, runner=_runner)
    except Exception:  # noqa: BLE001 —— 桥接顶层兜底（TPL-12 语义，规则 ⑫⑬）
        from qbot_rpg.commands.sender import format_tpl12

        reply = format_tpl12(str(getattr(event, "message", "") or ""))
    if reply:
        await bot.send(event, reply)


def register_plugin() -> None:
    """NoneBot on_message 注册（NoneBot 插件加载时调用；无 nonebot 环境 → 报错）。

    核心逻辑: HAS_NONEBOT 时 on_message(priority=10, block=False) 建 matcher 并以
    matcher.handle()(_on_message) 挂处理器；无 nonebot 环境抛 RuntimeError 提示
    （防静默失效——RA-11「无 NoneBot 环境走纯函数驱动」须显式声明）。
    """
    if not HAS_NONEBOT:
        raise RuntimeError(
            "qbot_rpg_bridge.plugin 需要 nonebot2 + nonebot-adapter-onebot 环境；"
            "无 NoneBot 环境请走 qbot_rpg.assembly.runner.run_command 纯函数驱动"
        )
    assert on_message is not None  # HAS_NONEBOT 保证；类型收窄供静态检查
    matcher = on_message(priority=_PRIORITY, block=False)
    matcher.handle()(_on_message)


if HAS_NONEBOT:
    # NoneBot 插件加载即注册（模块级执行；无 nonebot 环境跳过，import 安全）
    register_plugin()
