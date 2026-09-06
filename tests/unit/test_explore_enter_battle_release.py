"""/进入 离开锁定地图 → 战斗解除（2026-09-06 拍板）单测。

文件：tests/unit/test_explore_enter_battle_release.py
创建：2026-09-06
作者：Hermes 主代理（木桩退出/离图解战后续）

覆盖（_leave_battle_on_move 纯函数）：
  - 移动成功到新地图 + 战斗活跃 → release 元组 + 附加文案
  - 移动失败 → None（不解除）
  - 进副本（type=dungeon）→ None（不解除——副本身份另一套语义）
  - 不在战斗（engine None）→ None
  - 无 sender ctx → 回落（仍有 _battle_persist）
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.explore_commands import _leave_battle_on_move


class _FakeEngine:
    """假战斗引擎（仅存在性判定）。"""

    def _is_dummy_enemy_def(self) -> bool:
        return False


class _FakeSender:
    """假 sender（无 send 调用记录——pipeline 需要）。"""

    def __init__(self) -> None:
        self.sent: list = []

    def send(self, text: str, **kw: Any) -> None:
        self.sent.append(text)


def _base_ctx(**over: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "registered": True,
        "qid": "u1",
        "player": {"name": "测试勇士", "level": 10, "qid": "u1"},
        "map_id": "a1_bone_field",
        "location": "a1_bone_field",
        "battle_engine": _FakeEngine(),
        "sender": _FakeSender(),
        "templates": None,
    }
    ctx.update(over)
    return ctx


def test_move_leave_releases() -> None:
    """移动成功到新图 + 战斗中 → release。"""
    ctx = _base_ctx()
    result = {"ok": True, "to": "a2_ridge_hills", "name": "断脊丘陵"}
    out = _leave_battle_on_move(ctx, result, "✅ 你来到了「断脊丘陵」")
    assert out is not None
    assert out.get("_battle_persist") == ("release", "u1")
    assert "战斗解除" in out.get("message", "")
    assert out.get("send") is False


def test_move_fail_no_release() -> None:
    """移动失败 → 不解除。"""
    ctx = _base_ctx()
    result = {"ok": False, "reason": "此方向没有通道"}
    assert _leave_battle_on_move(ctx, result, "❌ 此方向没有通道") is None


def test_dungeon_no_release() -> None:
    """进副本（type=dungeon）→ 不解除。"""
    ctx = _base_ctx()
    result = {"ok": True, "type": "dungeon", "dungeon_id": "dg1", "name": "蚀脉洞窟"}
    assert _leave_battle_on_move(ctx, result, "✅ 你进入了「蚀脉洞窟」（副本）") is None


def test_no_battle_no_release() -> None:
    """不在战斗（engine None）→ 不解除。"""
    ctx = _base_ctx(battle_engine=None)
    result = {"ok": True, "to": "a2_ridge_hills", "name": "断脊丘陵"}
    assert _leave_battle_on_move(ctx, result, "✅ 你来到了「断脊丘陵」") is None


def test_no_sender_fallback() -> None:
    """无 sender（轻量 ctx）→ 回落仍带 _battle_persist。"""
    ctx = _base_ctx()
    ctx.pop("sender", None)
    result = {"ok": True, "to": "a2_ridge_hills", "name": "断脊丘陵"}
    out = _leave_battle_on_move(ctx, result, "✅ 你来到了「断脊丘陵」")
    assert out is not None
    assert out.get("_battle_persist") == ("release", "u1")
