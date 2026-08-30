"""tests/unit/test_bridge.py — M7 A-04 NoneBot 桥接层（qbot_rpg_bridge）。

依据：docs/细化/细化_M7_装配层契约.md 四、A-04（RA-11）+ TCA-10（内核零 NoneBot）。

覆盖（**零 NoneBot import**，铁律同内核 G0）：
  - build_event 纯函数：NoneBot 事件（鸭式假对象）→ event dict 字段映射
    （group_id/user_id/message/channel/message_id/group_name）；缺失字段安全缺省；
    Message 纯文本归一（get_plaintext 剥离 CQ 码 / str 兜底）。
  - run_bridge：FakeRunner + FakeDeps 注入 → 调 run_command 契约
    (event_dict, deps) -> str；缺省 runner 路径委托真 run_command（deps 缺 router
    → TPL-12 确定性返回）。
  - plugin._on_message：FakeBot 直调（鸭子类型）——发送回复 / 空回复不发 /
    未装配 deps 静默忽略；无 nonebot 环境 register_plugin 抛 RuntimeError
    （try-import 保护，HAS_NONEBOT 时 skip 成功路径）。

确定性：FakeRunner/FakeBot/FakeDeps 自含；无随机无时钟；无网络。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qbot_rpg_bridge import CHANNEL_DEFAULT, build_event, run_bridge
from qbot_rpg_bridge import plugin as bridge_plugin
from qbot_rpg.commands.sender import format_tpl12


# =============================================================================
# 假件（自含，零 nonebot）
# =============================================================================
class FakeMessage:
    """NoneBot Message 替身：带 get_plaintext（剥离 CQ 码）。"""

    def __init__(self, plain: str, raw: str = ""):
        self._plain = plain
        self._raw = raw or plain

    def get_plaintext(self) -> str:
        return self._plain

    def __str__(self) -> str:
        return self._raw


class FakeDeps:
    """装配依赖替身（缺省无 router → run_command TPL-12 确定性）。"""

    def __init__(self, **kw: Any):
        self.router = None
        self.repo = None
        self.queue = None
        for k, v in kw.items():
            setattr(self, k, v)


class FakeRunner:
    """run_command 替身：记录 (event_dict, deps)，返回预设回复（async）。"""

    def __init__(self, reply: str = "回复"):
        self.reply = reply
        self.calls: list = []

    async def __call__(self, event_dict: dict, deps: Any) -> str:
        self.calls.append((event_dict, deps))
        return self.reply


class FakeBot:
    """NoneBot Bot 替身：记录 send(event, text) 调用。"""

    def __init__(self):
        self.sent: list = []

    async def send(self, event: Any, message: Any, **kw: Any) -> None:
        self.sent.append((event, message, kw))


def make_event(**over: Any) -> SimpleNamespace:
    """构造完整假事件（缺省值覆盖全部契约字段）。"""
    base = dict(
        group_id="10001",
        user_id="20001",
        message="状态",
        message_id="m-1",
        group_name="测试群",
    )
    base.update(over)
    return SimpleNamespace(**base)


# =============================================================================
# build_event 纯函数（事件 → event dict 映射）
# =============================================================================
def test_build_event_full_mapping():
    """完整事件 → 契约 event dict 六字段精确映射。"""
    ev = make_event()
    out = build_event(ev)
    assert out == {
        "group_id": "10001",
        "user_id": "20001",
        "message": "状态",
        "channel": CHANNEL_DEFAULT,
        "message_id": "m-1",
        "group_name": "测试群",
    }


def test_build_event_missing_fields_defaults():
    """缺失字段 → 安全缺省（空串/缺省通道/None），不抛异常。"""
    out = build_event(SimpleNamespace())
    assert out == {
        "group_id": "",
        "user_id": "",
        "message": "",
        "channel": CHANNEL_DEFAULT,
        "message_id": "",
        "group_name": None,
    }


def test_build_event_plaintext_strips_cq():
    """Message 带 get_plaintext → 纯文本（剥离 [CQ:...] 码，路由 token 不污染）。"""
    ev = make_event(
        message=FakeMessage(plain="攻击", raw="[CQ:at,qq=20001]攻击[CQ:image,file=x]")
    )
    assert build_event(ev)["message"] == "攻击"


def test_build_event_strips_leading_at_mention():
    """P2-17 QA：@机器人+指令 → 剥离开头 @提及 段后正常路由（@QQ号 形式）。"""
    ev = make_event(message="@2750511376 攻击")
    assert build_event(ev)["message"] == "攻击"


def test_build_event_strips_leading_at_nickname():
    """P2-17 QA：@昵称+指令 → 剥离开头 @提及（昵称形式，非纯数字 QQ）。"""
    ev = make_event(message="@阿伟 任务")
    assert build_event(ev)["message"] == "任务"


def test_build_event_strips_multiple_at_mentions():
    """P2-17 QA：多个连续 @ 提及 + 指令 → 全部剥离，仅留指令。"""
    ev = make_event(message="@2750511376 @机器人 攻击")
    assert build_event(ev)["message"] == "攻击"


def test_build_event_at_not_leading_kept():
    """@ 不在开头（正文中）→ 不剥离（只清前导提及，避免误伤普通文本）。"""
    ev = make_event(message="帮打@2750511376 快")
    assert build_event(ev)["message"] == "帮打@2750511376 快"


def test_build_event_pure_at_mention_empty():
    """P2-17 QA：纯 @提及（无指令）→ 空串（路由忽略，不误响应）。"""
    ev = make_event(message="@2750511376")
    assert build_event(ev)["message"] == ""


def test_build_event_str_fallback():
    """无 get_plaintext 的 message → str() 兜底归一。"""
    ev = make_event(message="背包")
    assert build_event(ev)["message"] == "背包"


def test_build_event_scalar_coercion():
    """group_id/user_id/message_id 强制 str（幂等键/路由消费口径）。"""
    ev = make_event(group_id=10001, user_id=20001, message_id=999)
    out = build_event(ev)
    assert out["group_id"] == "10001"
    assert out["user_id"] == "20001"
    assert out["message_id"] == "999"


# =============================================================================
# run_bridge（事件 → run_command 契约调用）
# =============================================================================
async def test_run_bridge_injected_runner():
    """注入 FakeRunner → 以 (event_dict, deps) 调用，返回回复串。"""
    deps = FakeDeps()
    runner = FakeRunner(reply="合成回复")
    reply = await run_bridge(make_event(), deps, runner=runner)
    assert reply == "合成回复"
    assert len(runner.calls) == 1
    ev_dict, deps_arg = runner.calls[0]
    assert deps_arg is deps
    # event dict 形态对齐 runner 契约（message_id/group_id/user_id/message 齐备）
    assert ev_dict["group_id"] == "10001"
    assert ev_dict["user_id"] == "20001"
    assert ev_dict["message"] == "状态"
    assert ev_dict["message_id"] == "m-1"


async def test_run_bridge_default_runner_tpl12():
    """缺省 runner → 委托真 run_command（deps 缺 router → TPL-12 确定性兜底）。"""
    deps = FakeDeps()
    reply = await run_bridge(make_event(message="状态"), deps)
    assert reply == format_tpl12("状态")
    assert "指令不正确" in reply


# =============================================================================
# plugin._on_message（NoneBot 事件处理，FakeBot 直调）
# =============================================================================
async def test_on_message_sends_reply(monkeypatch: pytest.MonkeyPatch):
    """on_message：非空回复 → bot.send(event, reply) 回 QQ。"""
    fake_bot = FakeBot()
    runner = FakeRunner(reply="来啦")
    bridge_plugin.set_deps(FakeDeps(), runner=runner)
    ev = make_event()
    await bridge_plugin._on_message(fake_bot, ev)
    assert len(fake_bot.sent) == 1
    sent_event, text, kw = fake_bot.sent[0]
    assert sent_event is ev
    assert text == "来啦"
    assert runner.calls[0][0]["message_id"] == "m-1"
    # 复原，避免污染其它用例
    bridge_plugin.set_deps(None)


async def test_on_message_empty_reply_no_send(monkeypatch: pytest.MonkeyPatch):
    """on_message：空回复（忽略/会话子词/GM 静默）→ 不发。"""
    fake_bot = FakeBot()
    bridge_plugin.set_deps(FakeDeps(), runner=FakeRunner(reply=""))
    await bridge_plugin._on_message(fake_bot, make_event())
    assert fake_bot.sent == []
    bridge_plugin.set_deps(None)


async def test_on_message_unhandled_exception_tpl12():
    """on_message：runner 抛异常 → TPL-12 兜底文案，不裸崩。"""
    fake_bot = FakeBot()

    class BoomRunner:
        async def __call__(self, event_dict: dict, deps: Any) -> str:
            raise RuntimeError("boom")

    bridge_plugin.set_deps(FakeDeps(), runner=BoomRunner())
    await bridge_plugin._on_message(fake_bot, make_event(message="状态"))
    assert len(fake_bot.sent) == 1
    assert fake_bot.sent[0][1] == format_tpl12("状态")
    bridge_plugin.set_deps(None)


async def test_on_message_no_deps_ignored():
    """on_message：未装配 deps → 静默忽略（不响应不抛不崩）。"""
    bridge_plugin.set_deps(None)
    fake_bot = FakeBot()
    await bridge_plugin._on_message(fake_bot, make_event())
    assert fake_bot.sent == []


@pytest.mark.skipif(
    bridge_plugin.HAS_NONEBOT,
    reason="nonebot 已安装：register_plugin 走成功路径（不在此无 NoneBot 单测内）",
)
def test_plugin_register_requires_nonebot():
    """无 nonebot 环境：register_plugin 显式抛 RuntimeError（防静默失效）。"""
    assert not bridge_plugin.HAS_NONEBOT
    with pytest.raises(RuntimeError):
        bridge_plugin.register_plugin()
