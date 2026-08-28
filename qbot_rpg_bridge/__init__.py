"""M7 A-04 NoneBot 桥接层（RA-11 · 可选适配层；独立包 qbot_rpg_bridge）。

设计依据（唯一权威）：docs/细化/细化_M7_装配层契约.md 四、A-04（RA-11）：
  - 独立目录 qbot_rpg_bridge/（不在 qbot_rpg 包内，**内核零 NoneBot import 铁律**，
    G0 门禁只扫描 qbot_rpg/，本包不在扫描范围，是唯一允许依赖 NoneBot 的落点）。
  - 结构：桥接层要薄——NoneBot 事件 → 纯数据 event dict（build_event）→
    qbot_rpg.assembly.runner.run_command(event, deps)（async）→ 字符串回复 →
    NoneBot send（send 归 plugin.py 接线）。业务逻辑全部在 qbot_rpg 内核。
  - 会话路由：对话激活时纯数字/继续/离开 **直接透传**——本层零会话状态机，
    run_command 内 route_and_expand 已处理 ROUTE_SESSION（runner.py L484 返回空串
    或指令处理，桥接层不拦截不特殊化）。
  - 无 NoneBot 环境：CLI/测试走 run_command 纯函数驱动——本包 __init__ **零
    NoneBot import**，可脱离 nonebot 安装独立 import/单测；NoneBot 实际接线
    （on_message 注册/发送）只在 plugin.py 内（try-import 保护）。

事件契约（对齐 runner.py L31 / make_context L555 消费字段）：
  event dict = {group_id, user_id, message, channel, message_id, group_name}：
    - user_id 为幂等键 player_qid 要素（runner 取 qq_id 优先、user_id 兜底）；
    - message_id 为幂等键要素（IDEM-2），缺失 → run_command 抛 ValueError（由
      plugin 层 TPL-12 兜底 / 测试断言）；
    - channel 缺省 "group"（对齐 prefix_wiring.CHANNEL_GROUP，前缀注入消费）；
    - group_name 缺省 None（sender 前缀「群名」字段兜底）。

设计纪律：每函数 docstring；确定性（build_event 纯函数，getattr 兜底，零随机
零时钟）；零 NoneBot import（G0 门禁在内核，本包 __init__ 亦保持干净）。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

__all__ = [
    "CHANNEL_DEFAULT",
    "build_event",
    "run_bridge",
]

# 平台缺省通道（对齐 prefix_wiring.CHANNEL_GROUP = "group"，前缀注入/发送出口消费）
CHANNEL_DEFAULT = "group"


def _msg_to_str(message: Any) -> str:
    """NoneBot Message / 任意消息 → 纯文本 str（get_plaintext 优先，str 兜底）。

    入参 message: NoneBot Message 或任意可 str 化对象（可含 None）。
    出参 str——纯文本；空/None → ""。
    核心逻辑: 优先 callable(get_plaintext) 取纯文本（剥离 [CQ:...] 码，路由/指令
    token 不污染）；不可用 → str(message) 兜底；任一异常 → ""（缺省兜底不抛）。
    """
    if message is None:
        return ""
    plain = getattr(message, "get_plaintext", None)
    if callable(plain):
        try:
            text = plain()
        except Exception:  # noqa: BLE001 —— 归一兜底，不抛（RA-01 读快照纪律）
            text = ""
        if text:
            return str(text)
    return str(message)


def build_event(event: Any) -> dict:
    """NoneBot 事件对象 → 纯数据 event dict（RA-11 字段映射；getattr 兜底）。

    入参 event: 鸭式 NoneBot 事件（群消息事件等）——按属性读取 group_id /
      user_id / message / message_id / group_name；零 NoneBot import，任意具
      这些属性的对象皆可（SimpleNamespace / 假事件单测友好）。
    出参 dict：{group_id, user_id, message, channel, message_id, group_name}——
      标量字段强制 str（幂等键/路由消费口径），message 经 _msg_to_str 归一纯文本，
      channel 缺省 CHANNEL_DEFAULT("group")，group_name 缺省 None。
    核心逻辑: getattr 逐字段提取 + 归一；缺失字段安全空值，不抛异常（确定性）。
    """
    return {
        "group_id": str(getattr(event, "group_id", "") or ""),
        "user_id": str(getattr(event, "user_id", "") or ""),
        "message": _msg_to_str(getattr(event, "message", "")),
        "channel": str(getattr(event, "channel", None) or CHANNEL_DEFAULT),
        "message_id": str(getattr(event, "message_id", "") or ""),
        "group_name": getattr(event, "group_name", None),
    }


async def run_bridge(
    event: Any,
    deps: Any,
    *,
    runner: Optional[Callable] = None,
) -> str:
    """NoneBot 事件 → 回复串（薄桥接：build_event → run_command）。

    入参:
      - event: 鸭式 NoneBot 事件（build_event 消费属性）。
      - deps: AssemblyDeps——repo/game_world/registry/settings/queue + router
        （router_setup 产物）等（run_command 消费）。
      - runner: 可注入 runner（async (event_dict, deps) -> str；缺省
        qbot_rpg.assembly.runner.run_command，**惰性 import**——测试注入
        FakeRunner 免真实依赖，确定性）。
    出参 str——最终回复正文（空串 = 无回复/忽略/会话子词/GM 静默；错误 → TPL-12）。
    核心逻辑: build_event(event) → event_dict；await runner(event_dict, deps) 取
    回复串。本函数零 NoneBot import（runner 为 qbot_rpg 内核，平台无关）。
    """
    event_dict = build_event(event)
    if runner is None:
        from qbot_rpg.assembly.runner import run_command as _default_runner

        runner = _default_runner
    return await runner(event_dict, deps)
