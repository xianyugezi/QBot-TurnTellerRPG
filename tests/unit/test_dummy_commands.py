"""/木桩 /调整木桩 指令壳单测（怪物模块 §十五：训练木桩特例）。

文件：tests/unit/test_dummy_commands.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批1路2）

覆盖：
  - /木桩 无参 → 档位列表（序号+名称+HP/防御）
  - /木桩 <序号> → 进入训练战（BattleEngine battle_type=dummy + session acquire）
  - /木桩 <名字> → 普通怪名 → 自动建覆盖进默认木桩
  - /调整木桩 <怪物名> → 覆盖面板（persistent_state.dummy_override）
  - /调整木桩（无参）→ 重置
  - /调整木桩 不存在的怪 → 黄提示
  - 注册：两指令 CommandSpec（白名单标记）
风格对齐 test_enhance_commands.py（make_ctx + parse_command + 指令壳直调）。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.dummy_commands import (
    ADJUST_DUMMY_CMD,
    DUMMY_CMD,
    cmd_adjust_dummy,
    cmd_dummy,
    register_dummy_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router

# veinborn 木桩条目（测试直喂 ctx，免整包加载）
_DUMMY_LIGHT = {
    "id": "dummy_light", "name": "训练木桩·轻甲", "tier": "training", "type": "dummy",
    "stats": {"hp": 3000, "con": 5},
}
_DUMMY_HEAVY = {
    "id": "dummy_heavy", "name": "训练木桩·重甲", "tier": "training", "type": "dummy",
    "stats": {"hp": 5000, "con": 40},
}
_WOLF = {
    "id": "wasteland_wolf", "name": "荒原狼", "tier": "normal",
    "stats": {"hp": 380, "con": 19},
    "weakness": {"types": ["打击"]},
}


class _FakeSessionMgr:
    """假 session 管理器：get_active → None；acquire 记录。"""

    def __init__(self) -> None:
        self.acquired: list = []

    async def get_active(self, player_qid: str) -> None:
        return None

    async def acquire(self, player_qid: str, session_type: str, **kw: Any) -> Any:
        self.acquired.append((player_qid, session_type))
        return None

    async def release(self, player_qid: str) -> None:
        return None


def make_ctx(**over: Any) -> dict:
    """已注册玩家 ctx（enemies 含 2 木桩 + 1 普通怪；session_mgr fake）。"""
    base: Dict[str, Any] = {
        "registered": True,
        "player": {
            "name": "测试勇士", "level": 10, "qid": "u1",
            "hp": 400, "mp": 30,
            "currencies": {"coins": 1000},
            "inventory": [],
            "equipment": {},
            "persistent_state": {},
            "attributes": {"base": {"atk": 60.0, "def": 30.0}},
            "in_battle": False,
        },
        "enemies": [_DUMMY_LIGHT, _DUMMY_HEAVY, _WOLF],
        "session_mgr": _FakeSessionMgr(),
        "templates": None,
        "registry": None,
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


def test_dummy_list_no_arg() -> None:
    """/木桩 无参 → 档位列表。"""
    ctx = make_ctx()
    out = cmd_dummy(parse("/木桩"), ctx)
    assert "训练木桩·轻甲" in out
    assert "训练木桩·重甲" in out
    assert "HP 3000" in out
    assert "发送 /木桩" in out


def test_dummy_start_by_index() -> None:
    """/木桩 1 → 轻甲训练战（async 启动成功 + acquire）。"""
    import asyncio

    ctx = make_ctx()
    out = asyncio.run(cmd_dummy(parse("/木桩 1"), ctx))
    assert isinstance(out, dict) and out.get("ok")
    assert "训练木桩·轻甲" in out["message"]
    sm = ctx["session_mgr"]
    assert len(sm.acquired) == 1
    assert sm.acquired[0][1] == "battle"


def test_dummy_start_by_name() -> None:
    """/木桩 训练木桩·重甲 → 重甲训练战。"""
    import asyncio

    ctx = make_ctx()
    out = asyncio.run(cmd_dummy(parse("/木桩 训练木桩·重甲"), ctx))
    assert isinstance(out, dict) and out.get("ok")
    assert "训练木桩·重甲" in out["message"]


def test_dummy_start_normal_monster_auto_overlay() -> None:
    """/木桩 荒原狼 → 普通怪名 → 自动建覆盖（dummy_override=荒原狼面板）进默认木桩。"""
    import asyncio

    ctx = make_ctx()
    out = asyncio.run(cmd_dummy(parse("/木桩 荒原狼"), ctx))
    assert isinstance(out, dict) and out.get("ok")
    ps = ctx["player"]["persistent_state"]
    ov = ps.get("dummy_override")
    assert ov is not None
    assert ov.get("name") == "荒原狼"
    assert out["message"].startswith("⚔️ 与 训练木桩·荒原狼")


def test_dummy_battle_lock_when_active() -> None:
    """/木桩 已有战斗 → 拒绝。"""
    import asyncio

    class _Busy:
        async def get_active(self, qid: str) -> Any:
            class _S:
                session_type = "battle"
            return _S()

        async def acquire(self, *a: Any, **k: Any) -> Any:
            return None

    ctx = make_ctx(session_mgr=_Busy())
    out = asyncio.run(cmd_dummy(parse("/木桩 1"), ctx))
    assert isinstance(out, dict) and not out.get("ok")
    assert "已经在战斗中" in out["message"]


def test_adjust_dummy_overlay() -> None:
    """/调整木桩 荒原狼 → 覆盖面板写入。"""
    ctx = make_ctx()
    out = cmd_adjust_dummy(parse("/调整木桩 荒原狼"), ctx)
    assert "荒原狼" in out
    ov = ctx["player"]["persistent_state"]["dummy_override"]
    assert ov["def_base"] == 19
    assert ov["weakness"]["types"] == ["打击"]


def test_adjust_dummy_reset() -> None:
    """/调整木桩（无参）→ 重置。"""
    ctx = make_ctx()
    cmd_adjust_dummy(parse("/调整木桩 荒原狼"), ctx)
    out = cmd_adjust_dummy(parse("/调整木桩"), ctx)
    assert "重置" in out
    assert "dummy_override" not in ctx["player"]["persistent_state"]


def test_adjust_dummy_missing() -> None:
    """/调整木桩 不存在怪 → 黄提示。"""
    ctx = make_ctx()
    out = cmd_adjust_dummy(parse("/调整木桩 不存在"), ctx)
    assert "不存在" in out


def test_dummy_not_registered_gate() -> None:
    """未注册 → 注册门槛。"""
    ctx = make_ctx(registered=False, player=None)
    out = cmd_dummy(parse("/木桩"), ctx)
    assert "请先 /注册" in out


def test_register_dummy_commands() -> None:
    """两指令注册。"""
    router = Router()
    register_dummy_commands(router)
    for name in (DUMMY_CMD, ADJUST_DUMMY_CMD):
        spec = router.get(name)
        assert spec is not None
        assert spec.whitelisted


# ---------------------------------------------------------------------------
# /木桩 退出（2026-09-06 拍板：木桩战可中途退出——释放战斗会话）
# ---------------------------------------------------------------------------

class _FakeDummyEngine:
    """假木桩战斗引擎（仅暴露 dummy 判定与快照）。"""

    def __init__(self, is_dummy: bool = True) -> None:
        self._dummy = is_dummy

    def _is_dummy_enemy_def(self) -> bool:
        return self._dummy

    def to_snapshot(self) -> dict:
        return {}


class _ReleaseSessionMgr(_FakeSessionMgr):
    """记录 release 调用的 session 管理器。"""

    def __init__(self) -> None:
        super().__init__()
        self.released: list = []

    async def release(self, player_qid: str) -> None:
        self.released.append(player_qid)


def test_dummy_exit_no_battle() -> None:
    """战斗外 /木桩 退出 → 无训练战提示。"""
    ctx = make_ctx()
    out = cmd_dummy(parse("/木桩 退出"), ctx)
    assert isinstance(out, str) and "没有进行中的训练战" in out


def test_dummy_exit_not_dummy_battle() -> None:
    """普通战斗（非木桩）→ 拒绝（不借木桩词退普通战）。"""
    ctx = make_ctx(battle_engine=_FakeDummyEngine(is_dummy=False))
    out = cmd_dummy(parse("/木桩 退出"), ctx)
    assert isinstance(out, str) and "不是训练木桩" in out


def test_dummy_exit_ok_releases_session() -> None:
    """木桩战中退出 → 返回 _battle_persist release（post-commit 释放会话）。"""
    sm = _ReleaseSessionMgr()
    ctx = make_ctx(battle_engine=_FakeDummyEngine(is_dummy=True), session_mgr=sm,
                   qid="u1")
    out = cmd_dummy(parse("/木桩 退出"), ctx)
    assert isinstance(out, dict) and out.get("ok")
    assert "已退出训练木桩" in out["message"]
    assert out.get("_battle_persist") == ("release", "u1")
