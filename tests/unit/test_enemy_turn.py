"""怪转向事件化（增补 v1 §三）验收测试——2026-09-11 实装。

口径（docs/veinborn_战斗规则增补_v1.md §三 · 1v1 落地切片）：
  - 玩家绕背/侧移（side ∈ back/left/right）后、玩家行动前：怪**转回面向**
    （玩家 side 归位 front）；
  - **转向消耗行动条**：成本 `ctb.turn_cost`（缺省 400，可调）追加到怪的下一次
    ready（`CTBScheduler.delay_actor`；隐性口径，玩家不可见）；
  - **目标未变不转向（零消耗）**：玩家已在正面 → 无事件、无延迟；
  - 事件 `enemy_turned` 随玩家行动 outcome 出渲染行（`battle_enemy_turned`，
    纯行为播报、零数值）。

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG + 固定 seed）。
"""

from __future__ import annotations

from types import SimpleNamespace

from qbot_rpg.core.battle import BattleEngine

# 玩家 spd=50（首拍 t=200）；怪 spd=20（首拍 t=500）——玩家行动收尾后怪尚未出手，
# 便于对「延迟前/后」做干净的 ready 断言（不含怪自身行动的重签噪声）。
PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
         "mag": 30, "spd": 20, "foc": 50, "con": 50, "str": 80, "int": 30,
         "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}
SEQ = [0.5, 0.5, 0.5, 1.0]


class QueueRNG:
    """确定性随机源（对齐 test_air_policy.QueueRNG）。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def make(**kw) -> BattleEngine:
    eng = BattleEngine(**kw)
    eng._rng = QueueRNG(SEQ)  # type: ignore[assignment]
    return eng


def _start(config=None) -> BattleEngine:
    return make().start(PLAYER, ENEMY, random_seed=11, config=config)


def _set_side(eng: BattleEngine, side: str) -> None:
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"relative_to": "enemy"})
    ent["side"] = side


def _side_of(eng: BattleEngine) -> str:
    cp = eng._snap.get("combat_position") or {}
    return str((cp.get("player") or {}).get("side") or "front")


def _enemy_ready(eng: BattleEngine) -> float:
    view = eng._ctb.get_actor("enemy") if eng._ctb is not None else None
    assert view is not None
    return float(view.next_ready)


def _turn_events(outcomes) -> list:
    evs = []
    for o in outcomes:
        for e in (getattr(o, "side_effects", ()) or ()):
            if isinstance(e, dict) and e.get("type") == "enemy_turned":
                evs.append(e)
    return evs


# =====================================================================================
# 1. 引擎行为（转回面向 + 行动条成本）
# =====================================================================================


class TestEnemyTurnEngine:
    def test_turn_on_side_move(self) -> None:
        """玩家在侧 → 行动前怪转身：side 归位 front + 怪 next_ready +turn_cost + 事件。"""
        eng = _start()
        _set_side(eng, "right")
        before = _enemy_ready(eng)              # 500（怪首拍）
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        assert _side_of(eng) == "front"
        assert _enemy_ready(eng) == before + 400.0   # 转向成本缺省 400
        assert len(_turn_events(rep.outcomes)) == 1

    def test_turn_from_back(self) -> None:
        """背后同样触发转向（side ∈ back/left/right 统一口径）。"""
        eng = _start()
        _set_side(eng, "back")
        before = _enemy_ready(eng)
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        assert _side_of(eng) == "front"
        assert _enemy_ready(eng) == before + 400.0
        assert len(_turn_events(rep.outcomes)) == 1

    def test_no_turn_when_front(self) -> None:
        """「目标未变不转向」：玩家已在正面 → 零消耗、无事件。"""
        eng = _start()
        before = _enemy_ready(eng)
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        assert _side_of(eng) == "front"
        assert _enemy_ready(eng) == before          # 零延迟
        assert _turn_events(rep.outcomes) == []

    def test_turn_cost_configurable(self) -> None:
        """turn_cost 可调（ctb 段）——隐性口径、内容包可覆盖。"""
        eng = _start(config={"ctb": {"turn_cost": 700}})
        _set_side(eng, "left")
        before = _enemy_ready(eng)
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        assert _enemy_ready(eng) == before + 700.0
        assert len(_turn_events(rep.outcomes)) == 1

    def test_turn_zero_cost_when_configured_zero(self) -> None:
        """turn_cost=0（显式）→ 仍转身归位，但零延迟（配置自由度）。"""
        eng = _start(config={"ctb": {"turn_cost": 0}})
        _set_side(eng, "right")
        before = _enemy_ready(eng)
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        assert _side_of(eng) == "front"
        assert _enemy_ready(eng) == before
        assert len(_turn_events(rep.outcomes)) == 1


# =====================================================================================
# 2. 渲染行（模板配置化；零数值）
# =====================================================================================


class TestEnemyTurnRender:
    def test_render_line(self) -> None:
        """enemy_turned 事件 → 「{怪名}转过身来，盯住了你」一行（显示层名映射）。"""
        from qbot_rpg.core.message_format.battle_render import (  # noqa: PLC0415
            _render_enemy_turn_lines,
        )

        out = SimpleNamespace(
            side_effects=({"type": "enemy_turned", "actor": "enemy"},),
            target="灰狼",
        )
        assert _render_enemy_turn_lines(out) == ["灰狼转过身来，盯住了你"]

    def test_template_and_whitelist_registered(self) -> None:
        """模板与白名单登记（模板配置化：内容包可覆盖画面文案）。"""
        from qbot_rpg.core.templates import (  # noqa: PLC0415
            DEFAULT_TEMPLATES,
            PLACEHOLDER_WHITELIST,
        )

        assert DEFAULT_TEMPLATES["battle_enemy_turned"] == "{name}转过身来，盯住了你"
        assert PLACEHOLDER_WHITELIST["battle_enemy_turned"] == {"name"}

    def test_render_ignores_other_events(self) -> None:
        """无 enemy_turned → 空行集（零副作用）。"""
        from qbot_rpg.core.message_format.battle_render import (  # noqa: PLC0415
            _render_enemy_turn_lines,
        )

        out = SimpleNamespace(side_effects=({"type": "air_land", "actor": "player"},))
        assert _render_enemy_turn_lines(out) == []
