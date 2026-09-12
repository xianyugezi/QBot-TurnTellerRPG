"""/查看目标 指令壳单测（框架 7.6 L1356/L1367：战斗内目标属性面板，掉落不显示）。

文件：tests/unit/test_target_commands.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批1路3）

覆盖：
  - 战斗外 → battle_target_no_battle
  - 战斗中 → 目标面板（名称/行动数/HP/属性/印记/状态/弱点）
  - 掉落不显示（enemy_def 有 drops 也不出现在面板）
  - 注册：CommandSpec 白名单标记
风格对齐 test_dummy_commands.py（make_ctx + parse_command + 指令壳直调）。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.battle_commands import (
    TARGET_CMD,
    cmd_battle_target,
    register_battle_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router


class _FakeEngine:
    """假战斗引擎：battle_state() 返回构造快照；_enemy_def 可配。"""

    def __init__(self, state: Dict[str, Any], enemy_def: Any = None) -> None:
        self._state = state
        self._enemy_def = enemy_def

    def battle_state(self) -> Dict[str, Any]:
        return dict(self._state)


def _state(enemy: Dict[str, Any], turn: int = 3, action_seq: int = 3,
           marks: list | None = None, statuses: list | None = None) -> Dict[str, Any]:
    """战斗态快照夹具。

    CTB 口径（2026-09-10 收口；批4 路J 面板改【行动数】行）：面板读 `action_seq`
    （已结算行动数），顶层 `turn` 仅为兼容镜像。夹具同时给出两键，`turn` 保留供
    旧断言/回退路径。
    """
    return {
        "turn": turn,
        "action_seq": action_seq,
        "enemy": enemy,
        "marks_state": {"player": [], "enemy": marks or []},
        "status_state": {"player": [], "enemy": statuses or []},
    }


_ENEMY = {
    "name": "脊冢幼兽", "id": "ridge_cub", "hp": 208, "max_hp": 230,
    "atk": 70, "dfn": 13, "spd": 7, "foc": 6, "con": 13,
}
_ENEMY_DEF = {
    "id": "ridge_cub", "name": "脊冢幼兽", "tier": "normal",
    "weakness": {"types": ["打击"], "elements": {"fire": 1.3}},
    "drops": {"battle": [{"item": "wolf_pelt", "chance": 0.5}]},
}


def make_ctx(**over: Any) -> dict:
    base: Dict[str, Any] = {
        "registered": True,
        "player": {"name": "测试勇士", "level": 10, "qid": "u1"},
        "battle_engine": _FakeEngine(_state(_ENEMY), _ENEMY_DEF),
        "templates": None,
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


def test_target_no_battle() -> None:
    """战斗外 → 提示。"""
    ctx = make_ctx(battle_engine=None)
    out = cmd_battle_target(parse("/查看目标"), ctx)
    assert "没有进行中的战斗" in out


def test_target_panel_basic() -> None:
    """战斗中 → 面板含目标名/行动数/HP/属性。"""
    ctx = make_ctx()
    out = cmd_battle_target(parse("/查看目标"), ctx)
    assert "脊冢幼兽" in out
    # 批4 路J：行动数对齐 status_target 口径（【目标】/【行动数】分行，勿用「第 N 行动」）
    assert "【行动数】3" in out
    assert "208/230" in out
    assert "【攻击】70" in out
    assert "【防御】13" in out


def test_target_no_drops_shown() -> None:
    """掉落不显示（drops 字段在 enemy_def 但面板不含掉落字样）。"""
    ctx = make_ctx()
    out = cmd_battle_target(parse("/查看目标"), ctx)
    assert "掉落" not in out
    assert "wolf_pelt" not in out


def test_target_weakness_shown() -> None:
    """弱点段：types/elements 渲染。"""
    ctx = make_ctx()
    out = cmd_battle_target(parse("/查看目标"), ctx)
    assert "打击" in out
    assert "火×1.3" in out
    # 批4 路J：弱点区「标题行 + 每值一行」（少｜多换行）
    assert "【弱点】\n打击\n火×1.3" in out


def test_target_marks_and_status() -> None:
    """印记 + 状态行。"""
    ctx = make_ctx()
    st = _state(_ENEMY,
                marks=[{"name": "裂痕"}],
                statuses=[{"name": "灼烧"}])
    ctx["battle_engine"] = _FakeEngine(st, _ENEMY_DEF)
    out = cmd_battle_target(parse("/查看目标"), ctx)
    assert "裂痕" in out
    assert "灼烧" in out
    # 批4 路J：印记/状态区「标题行 + 每值一行」（少｜多换行）
    assert "【印记】\n裂痕" in out
    assert "【状态】\n灼烧" in out


def test_register_target_command() -> None:
    """注册白名单标记。"""
    router = Router()
    register_battle_commands(router)
    spec = router.get(TARGET_CMD)
    assert spec is not None
    assert spec.whitelisted
