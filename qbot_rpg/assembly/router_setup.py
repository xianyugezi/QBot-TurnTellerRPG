"""A-02 Router 构造与全指令注册（M7 装配层 · qbot_rpg/assembly/router_setup.py）。

依据（唯一权威）：docs/细化/细化_M7_装配层契约.md 二、A-02（RA-05~RA-07）+ TCA-02
（全指令组注册 + 白名单一致 + 无冲突）。真实签名已实读核对（2026-08-28）：
  - qbot_rpg/commands/router.py L194：Router(command_mode=..., require_at=...)；
    L201 register(spec, replace=False)（重名冲突 ValueError）；L221 names()；
    L224 whitelist_names()；L228 gm_commands()；L649/665 AliasTable.from_config。
  - 各指令组 register 函数尾部签名均为 (router, *, make_context=None)（ParsedCommand →
    ctx dict 同步契约；basic L1539 / register L478 / status L388 / shortcut L219 /
    quest L440 / shop L452 / checkin L478 / battle L839 / explore L272）。
  - qbot_rpg/commands/parsers.py L107 DEFAULT_WHITELIST（44 条）；L84-86 三模式。
  - qbot_rpg/data/gm_constants.py L35 GM_COMMANDS（5 条：重载/封禁/日志/编辑/设置）。

【工程补白 · 显式标注】（对齐仓库「决策记录纪律」，新决策须标注）
  1) make_context 双源注入：register 契约要求同步 `(parsed) -> dict`，而真实
     make_context 为 async `(event, deps) -> dict`（context.py L551，RA-01 签名偏差
     已由 BCH-01 标注）。本模块解析顺序：deps.make_context（可调用，A-03 runner /
     测试注入，可含事件上下文，同步或异步形态由注入方保证）→ 否则包装真实工厂为
     同步适配器（事件由 deps 鸭式上下文推导，_await_sync 桥接——无运行中事件循环时
     asyncio.run 执行；运行中循环内调用抛明确 RuntimeError 提示生产注入）。
  2) Router 交付（M4）无 aliases/shortcuts/gm 槽（__init__ 仅 _specs/command_mode/
     require_at）：RA-07 别名/快捷/GM 权限装载以**鸭式挂载** router.aliases /
     router.shortcuts / router.gm_commands_set 承载（**不用 gm_commands 名**——会遮蔽
     Router.gm_commands() 方法）；运行时快捷表仍以 ctx["shortcuts"] 为准（make_context
     L662 已装载，route_message 消费），本处为无 ctx 路由的缺省回退。gm 权限运行时源
     为 ctx["gm_commands"]（make_context L713 注入），本处为装配级快照供接线/校验。
  3) RA-06「对话/日志/调查/GM」组本里程碑未建（N-01/F-01/F-05 各路由交付、GM 归 M12），
     故注册清单仅 9 组 22 指令——与 parsers.DEFAULT_WHITELIST（44 条）的差集
     （制造/战斗邻近/地图/对话/GM 等）为 M7 合法非空，见 check_consistency 语义。

零 NoneBot import（架构铁律 G0）；仅依赖 commands / data 层 + 兄弟 BCH-01 context
（惰性 import，防循环）。纯装配零引擎改动。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Mapping, cast

from qbot_rpg.commands import (
    alchemy_commands,
    basic_commands,
    battle_commands,
    checkin_commands,
    codex_commands,
    dialog_commands,
    explore_commands,
    fishing_commands,
    fishing_reel_commands,
    forge_commands,
    investigate_commands,
    log_commands,
    quest_commands,
    register_commands,
    shop_commands,
    shortcut_commands,
    status_commands,
    unregister_commands,
    use_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST
from qbot_rpg.commands.router import AliasTable, CommandSpec, Router
from qbot_rpg.data.gm_constants import GM_COMMANDS

__all__ = [
    "REGISTER_GROUPS",
    "DEFAULT_COMMAND_MODE",
    "build_router",
    "check_consistency",
]

# 前缀模式缺省（parsers.MODE_GLOBAL_SHORTCUT，L86；Router 构造同缺省）
DEFAULT_COMMAND_MODE = "global_shortcut"

# ---------------------------------------------------------------------------
# RA-06 注册清单（M7 落地时点；dialog/log/investigate 归各自路，GM 归 M12）
# ---------------------------------------------------------------------------
REGISTER_GROUPS: tuple = (
    basic_commands.register_basic_commands,        # /角色 /背包 /装备 /技能 /帮助
    register_commands.register_register_commands,  # /注册
    unregister_commands.register_unregister_commands,  # /注销（2026-08-28 新增）
    status_commands.register_status_commands,      # /状态
    shortcut_commands.register_shortcut_commands,  # /快捷解绑 /快捷列表
    quest_commands.register_quest_commands,        # /任务
    shop_commands.register_shop_commands,          # /商店 /购买 /出售
    use_commands.register_use_commands,            # /使用（2026-08-28 接线：穿戴+道具）
    checkin_commands.register_checkin_commands,    # /签到
    battle_commands.register_battle_commands,      # /攻击 /防御 /逃跑 /道具
    explore_commands.register_explore_commands,    # /进入 /休息
    dialog_commands.register_dialog_commands,      # /对话（N-01，BCH-03）
    log_commands.register_log_commands,            # /日志（F-03/F-04，BCH-05，ADR-09）
    investigate_commands.register_investigate_commands,  # /调查（F-05/F-06，BCH-06）
    codex_commands.register_codex_commands,        # /图鉴（BCH-08；M8 收口：含炼金分册）
    alchemy_commands.register_alchemy_commands,    # M8 炼金 30+ 指令（/图鉴 并入 codex）
    forge_commands.register_forge_commands,        # M9 锻造 六指令（P0-1 收口 2026-08-30：
    #   /锻造 /确认 /图纸 /锻造树 /套装 /客制；/确认 状态分派器 replace 接管炼金同名）
    # M10 钓鱼（批8 审查 A3 P0-1 收口 2026-09-01）：/钓鱼 /鱼讯 /收杆 三指令
    fishing_commands.register_fishing_commands,    # /钓鱼 钓点列举+鱼讯参考
    fishing_reel_commands.register_fishing_reel_commands,  # /鱼讯 + /收杆 三选一
)


def _stub_unimplemented(hint: str) -> Callable[..., str]:
    """未实装指令 stub handler（固定提示；CommandSpec.handler 契约 (parsed, *a, **k)）。"""
    def _h(parsed: Any, *a: Any, **k: Any) -> str:
        return hint
    return _h


# ---------------------------------------------------------------------------
# make_context 解析（工程补白 1：双源注入 + async 同步桥接）
# ---------------------------------------------------------------------------
def _await_sync(coro: Any) -> Any:
    """同步执行协程：无运行中事件循环 → asyncio.run(coro)（smoke/测试路径）。

    入参 coro: 协程对象。出参: 协程执行结果。
    核心逻辑: get_running_loop 探测——无运行中循环（同步上下文）用 asyncio.run；
    有运行中循环（A-03 runner 内）→ 明确 RuntimeError（asyncio.run 在运行中循环内
    调用会抛 RuntimeError，这里前置给出带【待接线】的人话提示，指导注入 deps.make_context）。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if hasattr(coro, "close"):
        coro.close()  # 防协程泄漏（运行中循环无法 run，close 释放）
    raise RuntimeError(
        "【待接线】默认 make_context 适配器不能在运行中的事件循环内同步调用 async "
        "make_context（asyncio.run 冲突）；请由 A-03 runner 注入 deps.make_context"
        "（含事件上下文的适配器，见 build_router 工程补白 1）"
    )


def _event_from_parsed(parsed: Any, deps: Any) -> dict:
    """ParsedCommand → 事件映射（默认适配器桥接用，smoke/测试路径）。

    入参 parsed: ParsedCommand 或等价对象；deps: 装配依赖容器。
    出参 dict{group_id, user_id, message, channel}。
    核心逻辑: qid/group/channel 由 deps 鸭式上下文推导（default_qid /
    default_group_id / default_channel），缺失 → 安全空值（qid="" → registered=False
    ctx，不抛错）；message 取 parsed.raw（缺省 parsed.command）。
    """
    qid = str(getattr(deps, "default_qid", "") or "")
    return {
        "group_id": str(getattr(deps, "default_group_id", "") or "dm"),
        "user_id": qid,
        "message": str(getattr(parsed, "raw", None) or getattr(parsed, "command", "") or ""),
        "channel": str(getattr(deps, "default_channel", "") or "qq"),
    }


def _resolve_make_context(deps: Any) -> Callable[[Any], dict]:
    """解析 register 注入的 make_context（同步契约 (parsed) -> dict）。

    入参 deps: 装配依赖容器（AssemblyDeps 或鸭式等价）。
    出参 Callable[[ParsedCommand], dict]。
    核心逻辑: deps.make_context 可调用 → 原样用（A-03 runner/测试注入，含事件上下文）；
    否则惰性 import qbot_rpg.assembly.context.make_context（async (event, deps)）包装为
    同步适配器——事件由 _event_from_parsed 推导，_await_sync 桥接。惰性 import 防循环。
    """
    injected = getattr(deps, "make_context", None)
    if callable(injected):
        return cast(Callable[[Any], dict], injected)

    from qbot_rpg.assembly.context import make_context as _async_factory

    def _ctx(parsed: Any) -> dict:
        return _await_sync(_async_factory(_event_from_parsed(parsed, deps), deps))

    return _ctx


# ---------------------------------------------------------------------------
# build_router（RA-05 构造 + RA-06 全注册 + RA-07 配置装载）
# ---------------------------------------------------------------------------
def build_router(deps: Any) -> Router:
    """装配 Router：RA-05 构造 + RA-06 九指令组全注册 + RA-07 配置装载（TCA-02）。

    入参 deps: 装配依赖容器（AssemblyDeps 或鸭式等价；settings 为 Mapping 含
      command_mode / require_at / command_aliases；可选 make_context / shortcuts /
      default_qid / default_group_id / default_channel 鸭式字段）。
    出参 Router：command_mode/require_at 已按 settings 装载；9 组 22 指令已注册
      （重名冲突由 Router.register 抛 ValueError，TCA-02「无冲突」）；别名/快捷/GM
      权限以鸭式挂载（router.aliases / router.shortcuts / router.gm_commands_set）。

    核心逻辑:
      ① Router(command_mode=settings.command_mode 缺省 global_shortcut,
        require_at=bool(settings.require_at 缺省 False))——RA-07 前缀模式；
      ② _resolve_make_context(deps) → 逐组 register(router, make_context=ctx_factory)；
      ③ 别名装载：settings.command_aliases → AliasTable.from_config（RA-07 3c §六.7）；
      ④ GM 权限：data.gm_constants.GM_COMMANDS 快照挂 router.gm_commands_set；
      ⑤ 快捷表：deps.shortcuts 映射挂 router.shortcuts（无 ctx 路由缺省回退）。
    """
    settings = getattr(deps, "settings", None)
    settings = dict(settings) if isinstance(settings, Mapping) else {}

    command_mode = str(settings.get("command_mode") or DEFAULT_COMMAND_MODE)
    require_at = bool(settings.get("require_at", False))
    router = Router(command_mode=command_mode, require_at=require_at)

    ctx_factory = _resolve_make_context(deps)
    for reg in REGISTER_GROUPS:
        reg(router, make_context=ctx_factory)

    # 【2026-08-30 实机反馈】白名单/帮助引导过但尚未实现的指令 → 明确「尚未实装」提示，
    # 不再静默空回（玩家发「锁定1/怪物/采集/强化/调合/职业/转职」收到空串=像 bug）。
    # 逐个注册 stub（handler 返回固定提示；占位待对应里程碑实现后移除）。
    _UNIMPLEMENTED_HINTS: Dict[str, str] = {
        "锁定": "❌ 战斗锁定尚未实装（后续里程碑；当前用 /攻击 进入战斗）",
        "锁定怪物": "❌ 战斗锁定尚未实装（后续里程碑；当前用 /攻击 进入战斗）",
        "怪物": "❌ 怪物列表尚未实装（后续里程碑）",
        "采集": "❌ 采集尚未实装（后续里程碑）",
        "强化": "❌ 装备强化尚未实装（后续里程碑）",
        "调合": "❌ 调合尚未实装（后续里程碑）",
        "职业": "❌ 职业面板尚未实装（后续里程碑；/技能 查看技能）",
        "职业列表": "❌ 职业列表尚未实装（后续里程碑）",
        "转职": "❌ 转职尚未实装（后续里程碑）",
        # 2026-08-31 QA P1-4：帮助页引导的战斗指令 stub（防静默空回）。
        # 【2026-08-31 用户拍板】防御/道具/逃跑 战斗指令已定稿删除（引擎机制保留只删入口），
        # 白名单/帮助/stub 一律不出现这三个词 → 仅保留 快捷绑定 stub。
        "快捷绑定": "❌ 快捷绑定尚未实装（后续里程碑；/快捷列表 查看已绑快捷）",
    }
    for _name, _hint in _UNIMPLEMENTED_HINTS.items():
        if _name not in set(router.names()):
            router.register(CommandSpec(_name, whitelisted=True,
                                        handler=_stub_unimplemented(_hint)))

    # RA-07 配置装载（鸭式挂载，见模块工程补白 2；setattr 规避 Router 无属性槽的
    # 静态检查告警——Router 为 M4 交付类，本层只挂不改）
    setattr(router, "aliases", AliasTable.from_config(settings.get("command_aliases")))
    setattr(router, "gm_commands_set", frozenset(GM_COMMANDS))
    setattr(router, "shortcuts", dict(getattr(deps, "shortcuts", None) or {}))
    return router


# ---------------------------------------------------------------------------
# check_consistency（RA-07 注册自检，装配冒烟 TCA-02/TCA-03 用）
# ---------------------------------------------------------------------------
def check_consistency(router: Any) -> Dict[str, Any]:
    """注册自检：router 注册表 ↔ parsers.DEFAULT_WHITELIST 双向一致性比对。

    入参 router: 装配后的 Router（或等价注册表）。
    出参 dict{ok, registered_not_whitelisted, whitelist_not_registered}：
      - registered_not_whitelisted: 注册且标记 whitelisted 但 parsers 白名单缺失的
        指令（**硬不一致**，装配冒烟断言空；ok = 本列表为空）；
      - whitelist_not_registered: parsers 白名单有但 router 未注册的指令
        （M7 合法非空：制造/战斗邻近/地图/对话/GM 等归后续里程碑，信息性）。

    核心逻辑: whitelisted_names() 与 DEFAULT_WHITELIST 差集、DEFAULT_WHITELIST 与
    names() 差集；sorted 确定性输出。无冲突判定由 Router.register 重名 ValueError 承担。
    """
    registered = set(router.names())
    whitelisted = set(router.whitelist_names())
    registered_not_whitelisted: List[str] = sorted(whitelisted - set(DEFAULT_WHITELIST))
    whitelist_not_registered: List[str] = sorted(set(DEFAULT_WHITELIST) - registered)
    return {
        "ok": not registered_not_whitelisted,
        "registered_not_whitelisted": registered_not_whitelisted,
        "whitelist_not_registered": whitelist_not_registered,
    }
