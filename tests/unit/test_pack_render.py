"""内容包渲染钩子 E2 单测（ext/render.py · 事件白名单 · 结算隔离 · 双闸 · 失败隔离）。

覆盖（对照 docs/游戏包扩展点_方案_E.md §三 E2 / §三·装载安全 / §五 与任务验收）：
- 改写生效（命中事件 → 文本被替换）；返回 None/空 → 默认文本不变；
- 未命中事件 / 非该包场景 → 钩子**不被调用**（计数器为证）；
- 异常 / 超时 / 返回非 str → 默认文本 + 日志，链路不崩；
- **结算隔离对拍（最关键）**：同一战斗场景跑两遍（带钩子 vs 不带钩子）→ 引擎快照与
  玩家 hp/mp 逐字段 0 差异，而文本确有改写；
- data 是递归只读快照：无引擎句柄（repo/db/sender/ctx…），包代码改不动框架对象；
- 双闸与 E1 一致；未启用 → `ext/render.py` **从未被 import**（marker + sys.modules）；
- 与 E1 指令扩展共存（同一包 commands.py + render.py 都生效）；
- 通用性：另造一个不同名包的同结构 render.py → 同样生效；
- 真实探针包 zz_probe_ext：build_app_deps → run_command 全链路文本被改写；
- 未装钩子 → ctx["sender"] 仍是原 Sender 实例、发送文本与修前逐字节一致。

纪律：只写 tmp 目录/内存库，不触碰真实内容包数据与玩家存档；零 NoneBot。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import qbot_rpg.commands.battle_commands as bc
from qbot_rpg.assembly.pack_ext import CLI_FLAG, ENV_ENABLE, load_pack_extensions
from qbot_rpg.assembly.pack_render import (
    EVENT_BATTLE_ROUND,
    EVENT_COMMAND_REPLY,
    KNOWN_EVENTS,
    RENDER_FILE,
    RenderHook,
    RenderSender,
    build_render_data,
    load_pack_render_hook,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.prefix_wiring import DEFAULT_MESSAGE_PREFIX_SETTINGS
from qbot_rpg.commands.sender import Sender
from qbot_rpg.core.battle import BattleEngine

REPO = Path(__file__).resolve().parents[2]
PROBE_PACK = REPO / "content" / "zz_probe_ext"

_MANIFEST = {
    "name": "tmp render pack",
    "version": "9.9.9",
    "schema_version": 1,
    "author": "unit-test",
    "modules": [],
}

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


class RecordingSender(Sender):
    """记录型统一出口：send_text 回调收集实际发送段。"""

    def __init__(self) -> None:
        super().__init__(send_text=self._record)
        self.calls: list = []

    def _record(self, text: str, to=None) -> None:
        self.calls.append(text)


def _write_render_pack(
    root: Path,
    *,
    render_src: str | None = None,
    events=None,
    with_commands: bool = False,
) -> Path:
    """在 ``root`` 落一个最小渲染钩子包（只含装载器会读的文件）。"""
    (root / "ext").mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(_MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    if render_src is None:
        render_src = (
            "def render(event, data, default_text):\n"
            "    return default_text + '++'\n"
        )
        if events is not None:
            render_src = f"EVENTS = {events!r}\n" + render_src
    if render_src:
        (root / "ext" / RENDER_FILE).write_text(render_src, encoding="utf-8")
    if with_commands:
        (root / "commands.json").write_text(
            json.dumps(
                {"commands": [{"name": "探针", "handler": "probe", "aliases": []}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "ext" / "commands.py").write_text(
            "def probe(ctx, parsed):\n    return 'CMD:' + ctx.pack_id\n",
            encoding="utf-8",
        )
    return root


def _hook(fn, *, events=None, pack_id: str = "p", timeout: float = 5.0) -> RenderHook:
    return RenderHook(fn, pack_id=pack_id, events=events, timeout=timeout)


def _cmd_only_hook(fn) -> RenderHook:
    return _hook(fn, events=frozenset({EVENT_COMMAND_REPLY}))


# ---------------------------------------------------------------------------
# RenderHook 调用隔离（改写 / None / 非 str / 异常 / 超时）
# ---------------------------------------------------------------------------


def test_apply_replaces_text_on_hit() -> None:
    hook = _cmd_only_hook(lambda e, d, t: f"<{t}>")
    assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "<正文>"


@pytest.mark.parametrize("ret", [None, ""])
def test_apply_none_or_empty_uses_default(ret) -> None:
    hook = _cmd_only_hook(lambda e, d, t: ret)
    assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"


def test_apply_non_str_uses_default_and_logs(caplog) -> None:
    hook = _cmd_only_hook(lambda e, d, t: 123)
    with caplog.at_level(logging.WARNING, logger="qbot_rpg.assembly.pack_render"):
        assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"
    assert any("非 str" in r.getMessage() for r in caplog.records), caplog.records


def test_apply_async_hook_uses_default_and_logs(caplog) -> None:
    """async 钩子不被支持：返回协程 = 非 str → 默认文本 + 日志，且协程被关闭。"""

    async def _async_render(e, d, t):
        return t + "X"

    hook = _cmd_only_hook(_async_render)
    with caplog.at_level(logging.WARNING, logger="qbot_rpg.assembly.pack_render"):
        assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"
    assert any("非 str" in r.getMessage() for r in caplog.records), caplog.records


def test_apply_exception_uses_default_and_logs(caplog) -> None:
    def _boom(e, d, t):
        raise RuntimeError("钩子炸了")

    hook = _cmd_only_hook(_boom)
    with caplog.at_level(logging.ERROR, logger="qbot_rpg.assembly.pack_render"):
        assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"
    assert any("异常/超时" in r.getMessage() for r in caplog.records), caplog.records


def test_apply_timeout_uses_default_and_logs(caplog) -> None:
    def _slow(e, d, t):
        time.sleep(0.3)
        return "迟到的改写"

    hook = _hook(_slow, events=frozenset({EVENT_COMMAND_REPLY}), timeout=0.02)
    with caplog.at_level(logging.ERROR, logger="qbot_rpg.assembly.pack_render"):
        assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"
    assert any("异常/超时" in r.getMessage() for r in caplog.records), caplog.records


def test_hook_not_called_for_unlisted_event() -> None:
    """未命中事件 → 钩子函数**一次都不被调用**（返回默认文本）。"""
    calls: list = []
    hook = _hook(lambda e, d, t: calls.append(e) or "X",
                 events=frozenset({EVENT_BATTLE_ROUND}))
    assert hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"
    assert calls == []


def test_events_none_means_all_known_only() -> None:
    hook = RenderHook(lambda e, d, t: "X", pack_id="p")
    assert hook.applies(EVENT_COMMAND_REPLY) and hook.applies(EVENT_BATTLE_ROUND)
    assert not hook.applies("pack.custom.event")
    assert RenderHook(lambda e, d, t: "X", pack_id="p").apply("unknown.event", {}, "d") == "d"


# ---------------------------------------------------------------------------
# data：递归只读快照 + 无引擎句柄
# ---------------------------------------------------------------------------


def test_render_data_readonly_and_no_engine_handles() -> None:
    live = {"name": "阿伟", "hp": 10, "nested": {"k": [1, 2]}}
    ctx = {
        "qq_id": "u1", "channel": "group", "group_id": "g1", "registered": True,
        "player": live, "repo": object(), "db": object(), "sender": object(),
        "battle_engine": object(), "settings": {"secret": 1},
    }
    data = build_render_data(
        event=EVENT_COMMAND_REPLY, pack_id="p", command="状态", ctx=ctx,
        outcome={"ok": True},
    )
    assert set(data) == {
        "event", "pack_id", "command", "channel", "group_id",
        "player_id", "registered", "player", "outcome",
    }
    for handle in ("repo", "db", "sender", "battle_engine", "settings", "ctx"):
        assert handle not in data, f"data 泄漏了引擎句柄 {handle}"
    assert data["player_id"] == "u1" and data["registered"] is True

    with pytest.raises(TypeError):
        data["command"] = "改"  # type: ignore[index]
    with pytest.raises(TypeError):
        data["player"]["hp"] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        data["player"]["nested"]["k"][0] = 9  # type: ignore[index]
    # 原对象零改动（只读快照是真副本）
    assert live == {"name": "阿伟", "hp": 10, "nested": {"k": [1, 2]}}


def test_render_data_player_dataclass_is_copy_not_live_object() -> None:
    @dataclass
    class P:
        name: str = "a"
        hp: int = 1

    player = P()
    data = build_render_data(event=EVENT_COMMAND_REPLY, pack_id="p", ctx={"player": player})
    assert dict(data["player"]) == {"name": "a", "hp": 1}
    assert data["player"] is not player
    with pytest.raises(TypeError):
        data["player"]["hp"] = 5  # type: ignore[index]


# ---------------------------------------------------------------------------
# 双闸 + 未启用 → 从未 import
# ---------------------------------------------------------------------------


def test_not_enabled_never_imports_render(tmp_path: Path) -> None:
    marker = tmp_path / "render_import.marker"
    src = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n"
        "def render(event, data, default_text):\n"
        "    return default_text\n"
    )
    root = _write_render_pack(tmp_path / "zt_render_off", render_src=src)

    res = load_pack_render_hook(root, settings={}, cli=False)

    assert res.enabled is False and res.loaded is False and res.hook is None
    assert not marker.exists(), "未启用却 import 了包内 render.py"
    assert not [m for m in sys.modules if "zt_render_off" in m]


def test_render_gate_requires_both_switches(tmp_path: Path) -> None:
    root = _write_render_pack(tmp_path / "zt_render_gate", events=(EVENT_COMMAND_REPLY,))
    assert load_pack_render_hook(
        root, settings={"ext": {"enabled": True}}, cli=False
    ).loaded is False
    assert load_pack_render_hook(root, settings={}, cli=True).loaded is False
    on = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert on.ok and on.loaded and on.hook is not None
    assert on.events == (EVENT_COMMAND_REPLY,)


def test_render_gate_argv_and_env_channels(tmp_path: Path) -> None:
    root = _write_render_pack(tmp_path / "zt_render_channels")
    assert load_pack_render_hook(
        root, settings={"ext": {"enabled": True}}, argv=["prog", CLI_FLAG], env={}
    ).loaded
    assert load_pack_render_hook(
        root, settings={"ext": {"enabled": True}}, argv=["prog"], env={ENV_ENABLE: "1"}
    ).loaded


# ---------------------------------------------------------------------------
# 装载：缺文件 / import 失败 / 声明非法 / 路径
# ---------------------------------------------------------------------------


def test_enabled_but_no_render_file_is_ok(tmp_path: Path) -> None:
    root = tmp_path / "zt_render_noimpl"
    (root / "ext").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(_MANIFEST), encoding="utf-8")
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.enabled and res.ok and res.loaded is False and res.hook is None


def test_render_import_failure_isolated(tmp_path: Path) -> None:
    root = _write_render_pack(
        tmp_path / "zt_render_badimport", render_src="raise RuntimeError('坏 import')\n"
    )
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.enabled and res.ok is False and res.hook is None
    assert any("import 失败" in e for e in res.errors), res.errors


def test_render_missing_callable_rejected(tmp_path: Path) -> None:
    root = _write_render_pack(tmp_path / "zt_render_nocall", render_src="EVENTS = ()\n")
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and res.hook is None
    assert any("render" in e for e in res.errors), res.errors


def test_render_events_bare_str_rejected(tmp_path: Path) -> None:
    src = (
        "EVENTS = 'command.reply'\n"
        "def render(event, data, default_text):\n"
        "    return 'X'\n"
    )
    root = _write_render_pack(tmp_path / "zt_render_badevents", render_src=src)
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and res.hook is None
    assert any("EVENTS" in e for e in res.errors), res.errors


def test_render_unknown_event_warned_and_ignored(tmp_path: Path) -> None:
    """包声明了本框架没有的事件 → 警告 + 忽略（向前兼容），已知事件照常生效。"""
    src = (
        "EVENTS = ('command.reply', 'pack.custom')\n"
        "def render(event, data, default_text):\n"
        "    return default_text + '!'\n"
    )
    root = _write_render_pack(tmp_path / "zt_render_unknown", render_src=src)
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok and res.loaded and res.hook is not None
    assert res.events == (EVENT_COMMAND_REPLY,)
    assert any("pack.custom" in w for w in res.warnings), res.warnings
    assert res.hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文!"


def test_render_path_dotdot_rejected(tmp_path: Path) -> None:
    root = _write_render_pack(tmp_path / "zt_render_dotdot")
    res = load_pack_render_hook(
        root / "sub" / "..", settings={"ext": {"enabled": True}}, cli=True
    )
    assert res.ok is False and res.hook is None


def test_render_path_symlink_rejected(tmp_path: Path) -> None:
    root = _write_render_pack(tmp_path / "zt_render_link", render_src="")
    outside = tmp_path / "outside_render.py"
    outside.write_text(
        "def render(event, data, default_text):\n    return 'X'\n", encoding="utf-8"
    )
    (root / "ext" / RENDER_FILE).symlink_to(outside)
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and res.hook is None
    assert any("符号链接" in e for e in res.errors), res.errors


# ---------------------------------------------------------------------------
# 通用性：另一个包同结构 render.py → 同样生效
# ---------------------------------------------------------------------------


def test_second_pack_same_structure_works(tmp_path: Path) -> None:
    root = _write_render_pack(
        tmp_path / "zz_other_render",
        render_src=(
            "EVENTS = ('command.reply',)\n"
            "def render(event, data, default_text):\n"
            "    return default_text + '[其他包]'\n"
        ),
    )
    res = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok and res.loaded and res.pack_id == "zz_other_render"
    assert res.hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文[其他包]"


def test_other_pack_hook_not_called_for_foreign_event(tmp_path: Path) -> None:
    """非该包场景：A 包只接 command.reply、B 包只接 battle.round → 各自互不误触。"""
    a = _write_render_pack(
        tmp_path / "zz_pack_a", render_src=(
            "EVENTS = ('command.reply',)\n"
            "def render(event, data, default_text):\n    return 'A'\n"
        ),
    )
    b = _write_render_pack(
        tmp_path / "zz_pack_b", render_src=(
            "EVENTS = ('battle.round',)\n"
            "def render(event, data, default_text):\n    return 'B'\n"
        ),
    )
    hook_a = load_pack_render_hook(a, settings={"ext": {"enabled": True}}, cli=True).hook
    hook_b = load_pack_render_hook(b, settings={"ext": {"enabled": True}}, cli=True).hook
    assert hook_a is not None and hook_b is not None
    assert hook_a.apply(EVENT_COMMAND_REPLY, {}, "正文") == "A"
    assert hook_b.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文"  # B 不接此事件
    assert hook_b.apply(EVENT_BATTLE_ROUND, {}, "战报") == "B"
    assert hook_a.apply(EVENT_BATTLE_ROUND, {}, "战报") == "战报"


# ---------------------------------------------------------------------------
# runner sender 闭包：顺序（前缀注入后 → 钩子 → 发送）+ 未装钩子逐字节一致
# ---------------------------------------------------------------------------

PREFIX = "Lv35.阿伟 -斩龙者-"


def _runner_ctx(registered: bool = True) -> dict:
    return {
        "registered": registered, "level": 35, "name": "阿伟", "title": "斩龙者",
        "channel": "group", "to": "g1", "group_name": "测试群",
        "settings": DEFAULT_MESSAGE_PREFIX_SETTINGS,
    }


def _make_sender(deps, ctx, command=""):
    from qbot_rpg.assembly.runner import _make_sender as factory

    return factory(deps, ctx, command=command)


def test_runner_hook_applies_after_prefix() -> None:
    """钩子位置 = 前缀注入后、Sender.send 前：拿到的是含前缀的最终文本。"""
    seen: list = []
    hook = _cmd_only_hook(lambda e, d, t: seen.append(t) or t + "【改写】")
    deps = SimpleNamespace(sender=RecordingSender(), pack_render_hook=hook)
    ctx = _runner_ctx()
    sender, state = _make_sender(deps, ctx, command="状态")

    asyncio.run(sender({"message": "正文", "ok": True}))

    assert seen == [f"{PREFIX}\n正文"], seen
    assert deps.sender.calls == [f"{PREFIX}\n正文【改写】"]
    assert state["sent"] == f"{PREFIX}\n正文【改写】"


def test_runner_no_hook_is_byte_identical() -> None:
    """未装钩子：输出与修前逐字节一致，ctx["sender"] 仍是原 Sender 实例。"""
    rec = RecordingSender()
    deps = SimpleNamespace(sender=rec, pack_render_hook=None)
    ctx = _runner_ctx()
    sender, state = _make_sender(deps, ctx, command="状态")

    asyncio.run(sender({"message": "正文", "ok": True}))

    assert rec.calls == [f"{PREFIX}\n正文"]
    assert state["sent"] == f"{PREFIX}\n正文"
    assert ctx["sender"] is rec


def test_runner_unregistered_still_hooked_without_prefix() -> None:
    hook = _cmd_only_hook(lambda e, d, t: t + "【改写】")
    deps = SimpleNamespace(sender=RecordingSender(), pack_render_hook=hook)
    ctx = _runner_ctx(registered=False)
    sender, _ = _make_sender(deps, ctx, command="状态")

    asyncio.run(sender({"message": "正文", "ok": True}))

    assert deps.sender.calls == ["正文【改写】"]  # 未注册无前缀，但钩子照常生效


def test_runner_hook_failure_still_sends_default(caplog) -> None:
    def _boom(e, d, t):
        raise RuntimeError("炸")

    hook = _cmd_only_hook(_boom)
    deps = SimpleNamespace(sender=RecordingSender(), pack_render_hook=hook)
    ctx = _runner_ctx()
    sender, state = _make_sender(deps, ctx, command="状态")

    with caplog.at_level(logging.ERROR, logger="qbot_rpg.assembly.pack_render"):
        asyncio.run(sender({"message": "正文", "ok": True}))

    assert deps.sender.calls == [f"{PREFIX}\n正文"]
    assert state["sent"] == f"{PREFIX}\n正文"


def test_runner_command_event_not_hooked_when_not_declared() -> None:
    """钩子不接 command.reply → 调用计数 0、文本默认。"""
    calls: list = []
    hook = _hook(lambda e, d, t: calls.append(e) or "X",
                 events=frozenset({EVENT_BATTLE_ROUND}))
    deps = SimpleNamespace(sender=RecordingSender(), pack_render_hook=hook)
    ctx = _runner_ctx()
    sender, _ = _make_sender(deps, ctx, command="状态")
    asyncio.run(sender({"message": "正文", "ok": True}))
    assert calls == []
    assert deps.sender.calls == [f"{PREFIX}\n正文"]


# ---------------------------------------------------------------------------
# 战斗正文：ctx["sender"] 同出口（battle.round）
# ---------------------------------------------------------------------------


def test_battle_round_proxied_only_when_declared() -> None:
    hook_on = _hook(lambda e, d, t: t + "【战报改写】", events=frozenset({EVENT_BATTLE_ROUND}))
    rec = RecordingSender()
    deps = SimpleNamespace(sender=rec, pack_render_hook=hook_on)
    ctx = _runner_ctx()
    _make_sender(deps, ctx, command="攻击")
    assert isinstance(ctx["sender"], RenderSender)
    ctx["sender"].send("战报正文", to="g1")
    assert rec.calls == ["战报正文【战报改写】"]

    rec2 = RecordingSender()
    hook_off = _cmd_only_hook(lambda e, d, t: t + "X")
    deps2 = SimpleNamespace(sender=rec2, pack_render_hook=hook_off)
    ctx2 = _runner_ctx()
    _make_sender(deps2, ctx2, command="攻击")
    assert ctx2["sender"] is rec2, "未声明 battle.round 时不应代理 ctx[sender]"


def test_render_sender_passes_through_sender_semantics() -> None:
    """代理不改 Sender 语义：返回值原样透传、其余属性透传。"""
    rec = RecordingSender()
    hook = _hook(lambda e, d, t: "H:" + t, events=frozenset({EVENT_BATTLE_ROUND}))
    proxy = RenderSender(rec, hook, event=EVENT_BATTLE_ROUND)
    out = proxy.send("正文", to="g1")
    assert out == rec.calls == ["H:正文"]
    assert proxy._send_text is rec._send_text  # 属性透传


# ---------------------------------------------------------------------------
# 结算隔离对拍（最关键）：同一战斗场景两遍 → 引擎/玩家状态逐字段 0 差异
# ---------------------------------------------------------------------------

PLAYER = {"max_hp": 500, "hp": 500, "atk": 100, "dfn": 50, "mag": 50, "spd": 50,
          "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50, "spr": 50,
          "lck": 50, "elem_atk": 0, "name": "阿伟"}
ENEMY = {"max_hp": 400, "hp": 400, "atk": 80, "dfn": 40, "mag": 30, "spd": 40,
         "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
         "lck": 10, "elem_atk": 0, "name": "史莱姆"}


def _battle_ctx(sender, *, engine) -> dict:
    return {
        "battle_engine": engine, "sender": sender, "to": "group1", "channel": "group",
        "level": 35, "name": "阿伟", "title": "斩龙者",
        "prefix_settings": DEFAULT_MESSAGE_PREFIX_SETTINGS,
        "player": {"name": "阿伟", "hp": 500, "mp": 100},
        "skills": {"fireball": {"name": "火球术"}},
        "items": {"potion": {"name": "治疗药水", "actions": []}},
    }


# 引擎快照里的 per-instance 身份字段（uuid4；与结算数值无关，两局必然不同）
_IDENTITY_KEYS = ("battle_id", "snapshot_id")


def _settle_snapshot(ctx: dict, engine) -> dict:
    """结算状态快照（逐字段）：引擎快照 + 玩家 hp/mp + 战斗 ctx 结算字段。

    剔除 ``battle_id`` / ``snapshot_id`` 两个 per-instance 身份字段（见
    :data:`_IDENTITY_KEYS`）——它们是每局新建的 uuid，不承载结算数值。
    """
    snap = json.loads(json.dumps(engine.to_snapshot(), ensure_ascii=False, sort_keys=True))
    for key in _IDENTITY_KEYS:
        snap.pop(key, None)
    return {
        "engine": snap,
        "hp": ctx.get("hp"), "mp": ctx.get("mp"),
        "player": dict(ctx.get("player") or {}),
        "battle_status_changes": [dict(x) if isinstance(x, dict) else str(x)
                                  for x in (ctx.get("battle_status_changes") or [])],
        "battle_hint": ctx.get("battle_hint"),
    }


def _assert_identical_settlement(ctx_a: dict, eng_a, ctx_b: dict, eng_b) -> None:
    """逐字段断言两局结算 0 差异；唯一允许不同的是 per-instance 身份字段。"""
    raw_a, raw_b = eng_a.to_snapshot(), eng_b.to_snapshot()
    diff_keys = {k for k in set(raw_a) | set(raw_b) if raw_a.get(k) != raw_b.get(k)}
    assert diff_keys <= set(_IDENTITY_KEYS), f"引擎快照出现结算字段差异：{sorted(diff_keys)}"
    snap_a, snap_b = _settle_snapshot(ctx_a, eng_a), _settle_snapshot(ctx_b, eng_b)
    assert snap_b == snap_a
    for key in snap_a:
        assert snap_b[key] == snap_a[key], f"字段 {key} 出现差异"


def _run_attack(ctx: dict) -> dict:
    return asyncio.run(bc.cmd_battle_attack(parse_command("/攻击"), ctx))


def test_settlement_isolation_hook_vs_no_hook(seed: int) -> None:
    """同一场景跑两遍（带钩子改写战报 vs 不带）→ 结算快照 0 差异，而文本确有改写。"""
    eng_plain = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=seed)
    eng_hooked = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=seed)

    rec_plain = RecordingSender()
    ctx_plain = _battle_ctx(rec_plain, engine=eng_plain)
    _run_attack(ctx_plain)

    rec_hooked = RecordingSender()
    ctx_hooked = _battle_ctx(rec_hooked, engine=eng_hooked)
    # 与 runner 同款：钩子声明 battle.round 时 ctx["sender"] 走渲染代理
    hook = _hook(lambda e, d, t: t + "【改写】", events=frozenset({EVENT_BATTLE_ROUND}))
    ctx_hooked["sender"] = RenderSender(
        rec_hooked, hook, event=EVENT_BATTLE_ROUND, ctx=ctx_hooked, command="攻击"
    )
    _run_attack(ctx_hooked)

    # ① 钩子确已生效：战报文本被改写（证明对拍对照有效）
    assert rec_hooked.calls and all(t.endswith("【改写】") for t in rec_hooked.calls)
    assert not any(t.endswith("【改写】") for t in rec_plain.calls)
    assert [t.replace("【改写】", "") for t in rec_hooked.calls] == rec_plain.calls

    # ② 结算隔离：引擎 + 玩家 + ctx 结算字段逐字段 0 差异
    _assert_identical_settlement(ctx_plain, eng_plain, ctx_hooked, eng_hooked)


def test_settlement_engine_untouched_when_hook_tries_to_mutate() -> None:
    """钩子即使尝试改 data，也动不了引擎/玩家（只读快照隔离）。"""
    eng_plain = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=7)
    ctx_plain = _battle_ctx(RecordingSender(), engine=eng_plain)
    _run_attack(ctx_plain)

    attempts: list = []

    def _evil(event, data, default_text):
        for target in (data, data.get("player"), data.get("outcome")):
            try:
                target["hp"] = -999  # type: ignore[index]
            except Exception as exc:  # noqa: BLE001
                attempts.append(type(exc).__name__)
        return default_text

    eng_evil = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=7)
    hook = _hook(_evil, events=frozenset({EVENT_BATTLE_ROUND}))
    ctx_evil = _battle_ctx(RecordingSender(), engine=eng_evil)
    ctx_evil["sender"] = RenderSender(
        ctx_evil["sender"], hook, event=EVENT_BATTLE_ROUND, ctx=ctx_evil
    )
    _run_attack(ctx_evil)

    assert attempts and set(attempts) == {"TypeError"}, attempts
    _assert_identical_settlement(ctx_plain, eng_plain, ctx_evil, eng_evil)
    # 玩家 hp 由战斗结算正常同步（非钩子所致）；与不带钩子那局逐字段一致
    assert ctx_evil["player"] == ctx_plain["player"]
    assert ctx_evil["hp"] == ctx_plain["hp"] and ctx_evil["mp"] == ctx_plain["mp"]


# ---------------------------------------------------------------------------
# 真实探针包：build_app_deps → run_command 全链路（commands.py + render.py 共存）
# ---------------------------------------------------------------------------


async def test_real_probe_pack_render_end_to_end(tmp_path: Path) -> None:
    from qbot_rpg.assembly.runner import run_command
    from qbot_rpg_bridge.assemble import build_app_deps

    deps = await build_app_deps(
        pack_dir=str(PROBE_PACK),
        db_path=str(tmp_path / "e2e_render.db"),
        settings={"ext": {"enabled": True}},
        enable_pack_ext=True,
    )
    try:
        # E1 指令扩展 + E2 渲染钩子共存
        assert deps.pack_ext_result.ok and deps.pack_ext_result.registered == ("探针",)
        assert deps.pack_render_result.ok and deps.pack_render_result.loaded
        assert deps.pack_render_result.events == (EVENT_COMMAND_REPLY,)
        ev = {
            "group_id": "g1", "user_id": "u1", "message": "探针 参数甲",
            "channel": "group", "message_id": "m-e2-1",
        }
        out = await run_command(ev, deps)
        assert "【扩展探针】" in out and "包=zz_probe_ext" in out
        assert out.endswith("（探针改写）"), out
        ev2 = {**ev, "message": "zzprobe 参数乙", "message_id": "m-e2-2"}
        assert (await run_command(ev2, deps)).endswith("（探针改写）")
    finally:
        await deps.repo.db.close()


async def test_real_probe_pack_render_disabled_by_default(tmp_path: Path) -> None:
    from qbot_rpg.assembly.runner import run_command
    from qbot_rpg_bridge.assemble import build_app_deps

    deps = await build_app_deps(
        pack_dir=str(PROBE_PACK),
        db_path=str(tmp_path / "e2e_render_off.db"),
        enable_pack_ext=False,
    )
    try:
        assert deps.pack_render_result.enabled is False
        assert deps.pack_render_hook is None
        assert not deps.router.has("探针")
        ev = {
            "group_id": "g1", "user_id": "u1", "message": "探针 参数甲",
            "channel": "group", "message_id": "m-e2-off",
        }
        out = await run_command(ev, deps)
        assert "（探针改写）" not in out  # 未启用 → 文本与修前一致
    finally:
        await deps.repo.db.close()


# ---------------------------------------------------------------------------
# 与 E1 同口径：装载器对同一包先装指令再装渲染，互不影响
# ---------------------------------------------------------------------------


def test_commands_and_render_loaders_are_independent(tmp_path: Path) -> None:
    from qbot_rpg.commands.router import AliasTable, Router

    root = _write_render_pack(
        tmp_path / "zt_both", with_commands=True,
        render_src=(
            "EVENTS = ('command.reply',)\n"
            "def render(event, data, default_text):\n    return default_text + 'R'\n"
        ),
    )
    router = Router()
    router.aliases = AliasTable.from_config({})  # type: ignore[attr-defined]
    ext = load_pack_extensions(router, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    render = load_pack_render_hook(root, settings={"ext": {"enabled": True}}, cli=True)
    assert ext.registered == ("探针",) and router.has("探针")
    assert render.loaded and render.hook is not None
    assert render.hook.apply(EVENT_COMMAND_REPLY, {}, "正文") == "正文R"


def test_known_events_contains_both_framework_events() -> None:
    assert EVENT_COMMAND_REPLY in KNOWN_EVENTS and EVENT_BATTLE_ROUND in KNOWN_EVENTS
