"""方位战斗系统 Step 4：RepositionEffect 验收测试。

依据：docs/方位战斗系统_框架改造草案.md（v0.6 技术定稿）：
  - §三.5 RepositionEffect（effects 新原子：reposition=set_relative 单目标方位设定 /
    reposition_all=rotate + mapping 全场重映射；走既有「敌方行动 effects 通道」）
  - §二.5 怪物方位行动置换原语（冲锋=rotate 前→后；转身=180° 全映射）
  - §四 T8（reposition 类效果结算于效果段，随行动 effects 顺序执行）
  - 附录 A Step 4：置换映射单测；不加 battle.py 特殊函数（边界纪律 §六）
  - N6（reposition target 路由：1v1 仅 self/player；组队里程碑扩全场）

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义 对照
  - 旧「敌侧行动用 `enemy_act(action_dict=...)`（玩家先手 → 怪固定后手）」→
    CTB 无先手/后手对：怪物与玩家同走 `ACTOR_READY → BEFORE_ACTION →
    ACTION_RESOLVE` 通道。测试用**单次结算入口** `do_action("enemy", action_dict)`
    驱动敌侧行动（`enemy_act` 已为 NotImplementedError 壳，禁止调用）。
  - 旧「完整回合收尾：`end_turn` → `start_turn` 推进，断言 `report.turn == 2`」→
    CTB「一次 `player_act` 提交行动 + 调度器自动推进，断言 `action_seq` 严格增加、
    状态仍为可行动态」。`turn` 现为 action_seq 兼容镜像，不作进度断言。

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG + 固定 seed）。

验收覆盖：
  1. reposition 单目标 set_relative（side/height 单轴/双轴；target=self/player/enemy
     绝对侧解析——怪 reposition 玩家写 target="player"）
  2. reposition_all rotate mapping（全场=施放者除外；部分/全映射；height 不动）
  3. 错误防御（未知 target/mode/非法 side/缺 mapping → 效果失败不崩、行动照常）
  4. 真实行动链（怪 skill def effects → 玩家方位翻转 + position_changed 事件）
  5. 旧快照无 combat_position 段 → 降级无操作不崩
  6. 渲染层「移动到了{pos}」行（玩家/怪名映射）
  7. V-12 kind 推断（reposition → utility 黄提示）；显式 kind 零红拦
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Mapping

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.message_format.battle_render import (
    _render_enemy_action,
    _render_player_action,
)
from qbot_rpg.content.skill_validator import validate_skills

# 对齐 tests/unit/test_battle_engine.py 构造口径
PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
         "mag": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30,
         "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}
SEQ = [0.5, 0.5, 0.5, 1.0]


class QueueRNG:
    """确定性随机源（对齐 test_battle_engine.QueueRNG）。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def make(**kw) -> BattleEngine:
    eng = BattleEngine(**kw)
    eng._rng = QueueRNG(SEQ)  # type: ignore[assignment]  # 确定性随机源注入
    return eng


def _pos(eng: BattleEngine, which: str = "player"):
    cp = eng._snap.get("combat_position") or {}
    ent = cp.get(which) or {}
    return (str(ent.get("side") or "front"), str(ent.get("height") or "ground"))


def _fx(outcome: Any, ftype: str) -> List[Mapping[str, Any]]:
    return [e for e in getattr(outcome, "side_effects", ()) or ()
            if isinstance(e, Mapping) and e.get("type") == ftype]


# =====================================================================================
# 1. reposition：单目标 set_relative（side/height 单轴或双轴；绝对侧解析）
# =====================================================================================


class TestReposition:
    def test_enemy_repositions_player_to_back(self) -> None:
        """怪冲锋效果：effects reposition target=player side=back → 玩家到怪背后。"""
        eng = make(defs={"charge": {"id": "charge", "name": "冲锋", "kind": "damage",
                                    "type": "active", "power": 100,
                                    "attack_type": "blunt",
                                    "effects": [{"type": "reposition", "target": "player",
                                                 "mode": "set_relative", "side": "back",
                                                 "height": "ground"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        # CTB：单次结算入口驱动敌侧行动（enemy_act 已删除）
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "charge",
                                      "mult": 1.0})
        assert out is not None and out.hit is True
        assert _pos(eng, "player") == ("back", "ground")
        evs = _fx(out, "position_changed")
        assert len(evs) == 1 and evs[0].get("actor") == "player"
        assert evs[0].get("side") == "back"

    def test_side_only_keeps_height(self) -> None:
        """只给 side：height 保持原值（先置空中 → 绕背仍空中）。

        CTB 迁移：旧测试断言「行动后快照 height 仍 air」。CTB 下空中姿态在持有者
        每次 `AFTER_ACTION` 到期落地（`_settle_air_landing`：无空中姿态状态 →
        强制落地 ground，R16）。故改断言**行动结算位点（ACTION_RESOLVE）的
        `position_changed` 事件**保留 height=air（reposition 原语本身不动 height）。
        """
        eng = make(defs={"sneak": {"id": "sneak", "name": "绕背", "kind": "utility",
                                   "type": "active", "power": 0,
                                   "effects": [{"type": "reposition", "target": "self",
                                                "side": "back"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        eng._snap["combat_position"]["player"]["height"] = "air"
        out = eng.do_action("player", {"type": "skill", "skill_id": "sneak"})
        assert out.ok is True
        evs = _fx(out, "position_changed")
        assert len(evs) == 1
        assert evs[0].get("side") == "back"      # side 已改
        assert evs[0].get("height") == "air"     # height 保持（原语只改 side）

    def test_height_only_keeps_side(self) -> None:
        """只给 height：side 保持（跃空技：front → front+air）。"""
        eng = make(defs={"vault": {"id": "vault", "name": "跃空", "kind": "utility",
                                   "type": "active", "power": 0,
                                   "effects": [{"type": "reposition", "target": "self",
                                                "height": "air"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "skill", "skill_id": "vault"})
        assert out.ok is True
        assert len(_fx(out, "position_changed")) == 1
        # 行动结算位点事件：side 保持 front，height 置 air
        ev = _fx(out, "position_changed")[0]
        assert ev.get("side") == "front"
        assert ev.get("height") == "air"

    def test_explicit_enemy_target_moves_enemy(self) -> None:
        """target=enemy 绝对侧：玩家效果把怪方位翻过去（enemy 段无消费方但原语通用）。"""
        eng = make(defs={"spin": {"id": "spin", "name": "旋身", "kind": "utility",
                                  "type": "active", "power": 0,
                                  "effects": [{"type": "reposition", "target": "enemy",
                                               "side": "back"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "skill", "skill_id": "spin"})
        assert out.ok is True
        assert _pos(eng, "enemy") == ("back", "ground")

    def test_unknown_target_fails_gracefully(self) -> None:
        """未知 target → 效果失败（无事件）不崩，行动照常。"""
        eng = make(defs={"bad": {"id": "bad", "name": "坏目标", "kind": "utility",
                                 "type": "active", "power": 100,
                                 "effects": [{"type": "reposition", "target": "bogus",
                                              "side": "back"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "skill", "skill_id": "bad"})
        assert out.ok is True          # 行动本身照常
        assert _fx(out, "position_changed") == []
        assert _pos(eng, "player") == ("front", "ground")

    def test_invalid_side_fails_gracefully(self) -> None:
        """side 枚举外 → 效果失败不崩（无事件无移动）。"""
        eng = make(defs={"bad": {"id": "bad", "name": "坏方位", "kind": "utility",
                                 "type": "active", "power": 100,
                                 "effects": [{"type": "reposition", "target": "self",
                                              "side": "up"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "skill", "skill_id": "bad"})
        assert out.ok is True
        assert _fx(out, "position_changed") == []
        assert _pos(eng, "player") == ("front", "ground")

    def test_two_repositions_last_wins(self) -> None:
        """多 reposition 顺序执行：结算事件按序出且末者胜（行动结算位点）。

        CTB 迁移：空中姿态在 AFTER_ACTION 到期落地，故终态快照 height 归 ground；
        断言改为**行动结算位点**两条 `position_changed` 事件依序产出，末者为
        {front, air}（reposition 顺序执行「最后者胜」的 CTB 语义）。
        """
        eng = make(defs={"dance": {"id": "dance", "name": "闪转", "kind": "utility",
                                   "type": "active", "power": 0,
                                   "effects": [
                                       {"type": "reposition", "target": "self",
                                        "side": "back"},
                                       {"type": "reposition", "target": "self",
                                        "side": "front", "height": "air"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "skill", "skill_id": "dance"})
        assert out.ok is True
        evs = _fx(out, "position_changed")
        assert len(evs) == 2
        assert (evs[0].get("side"), evs[0].get("height")) == ("back", "ground")
        assert (evs[1].get("side"), evs[1].get("height")) == ("front", "air")


# =====================================================================================
# 2. reposition_all：rotate + mapping 全场重映射（施放者除外；height 不动）
# =====================================================================================

ROTATE_180 = {"front": "back", "back": "front", "left": "right", "right": "left"}


class TestRepositionAll:
    def test_enemy_rotate_180_flips_player(self) -> None:
        """怪转身 180°：玩家 side 全翻转（front↔back、left↔right）；怪自身不动。

        CTB 迁移：敌侧行动经单次结算入口 `do_action("enemy", ...)`（无 enemy_act）；
        空中玩家在敌侧 AFTER_ACTION 后会落地（`_settle_air_landing`），故 height
        断言改在**行动结算位点**的 `position_changed` 事件上（rotate 不动 height）。
        """
        for before, after in (("front", "back"), ("left", "right"),
                              ("back", "front"), ("right", "left")):
            eng = make().start(PLAYER, ENEMY, random_seed=11)
            eng._snap["combat_position"]["player"]["side"] = before
            eng._snap["combat_position"]["player"]["height"] = "air"
            out = eng.do_action("enemy", {
                "type": "normal", "mult": 1.0,
                "effects": [{"type": "reposition_all", "mode": "rotate",
                             "mapping": dict(ROTATE_180)}]})
            assert out is not None and out.hit is True
            evs = _fx(out, "position_changed")
            assert len(evs) == 1 and evs[0].get("actor") == "player"
            assert evs[0].get("side") == after          # side 翻转
            assert evs[0].get("height") == "air"        # height 不动（结算位点）
            assert _pos(eng, "enemy") == ("front", "ground")  # 施放者跳过

    def test_partial_mapping_keeps_others(self) -> None:
        """冲锋 rotate {front:back}：front→back，其余侧保持。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        eng._snap["combat_position"]["player"]["side"] = "left"
        out = eng.do_action("enemy", {
            "type": "normal", "mult": 1.0,
            "effects": [{"type": "reposition_all", "mode": "rotate",
                         "mapping": {"front": "back"}}]})
        assert out is not None
        assert _pos(eng, "player") == ("left", "ground")   # left 不在映射 → 保持
        evs = _fx(out, "position_changed")
        assert evs == []                                   # 无变化不发事件

    def test_player_cast_reposition_all_rotates_enemy(self) -> None:
        """玩家施放 reposition_all（对称）：怪 side 翻转，玩家自身跳过。"""
        eng = make(defs={"sweep": {"id": "sweep", "name": "回旋", "kind": "damage",
                                   "type": "active", "power": 100,
                                   "effects": [{"type": "reposition_all",
                                                "mode": "rotate",
                                                "mapping": dict(ROTATE_180)}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "skill", "skill_id": "sweep"})
        assert out.ok is True
        assert _pos(eng, "enemy") == ("back", "ground")
        assert _pos(eng, "player") == ("front", "ground")

    def test_missing_mapping_fails_gracefully(self) -> None:
        """缺 mapping → 效果失败不崩（无事件无移动）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("enemy", {
            "type": "normal", "mult": 1.0,
            "effects": [{"type": "reposition_all", "mode": "rotate"}]})
        assert out is not None and out.hit is True
        assert _fx(out, "position_changed") == []
        assert _pos(eng, "player") == ("front", "ground")

    def test_bad_mode_fails_gracefully(self) -> None:
        """mode 枚举外（reposition_all 仅 rotate）→ 效果失败不崩。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("enemy", {
            "type": "normal", "mult": 1.0,
            "effects": [{"type": "reposition_all", "mode": "spin",
                         "mapping": dict(ROTATE_180)}]})
        assert out is not None
        assert _fx(out, "position_changed") == []
        assert _pos(eng, "player") == ("front", "ground")


# =====================================================================================
# 3. 旧快照降级 + 事件随行动链完整走通
# =====================================================================================


class TestLegacyAndChain:
    def test_missing_position_section_no_crash(self) -> None:
        """旧快照无 combat_position 段：reposition 效果降级无操作，行动照常。"""
        eng = make(defs={"charge": {"id": "charge", "name": "冲锋", "kind": "damage",
                                    "type": "active", "power": 100,
                                    "attack_type": "blunt",
                                    "effects": [{"type": "reposition", "target": "player",
                                                 "side": "back"}]}}).start(
            PLAYER, ENEMY, random_seed=11)
        eng._snap.pop("combat_position", None)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "charge",
                                      "mult": 1.0})
        assert out is not None and out.hit is True
        assert _fx(out, "position_changed") == []

    def test_full_turn_advances_after_reposition(self) -> None:
        """reposition 后时间轴完整推进：CTB 单次 `player_act` 推进 action_seq。

        旧语义「end_turn → start_turn 推进，report.turn == 2」→ CTB「提交一次
        玩家行动 + 调度器自动推进，`action_seq` 严格增加、状态仍可行动」。
        """
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        # 完整行动链：玩家防御占一拍 → 敌侧位移行动（reposition_all）→ 时间轴推进
        g = eng.do_action("player", {"type": "guard"})
        assert g.ok is True
        out = eng.do_action("enemy", {
            "type": "normal", "mult": 1.0,
            "effects": [{"type": "reposition_all", "mode": "rotate",
                         "mapping": dict(ROTATE_180)}]})
        assert out is not None and _pos(eng, "player") == ("back", "ground")
        seq_before = eng.battle_state()["action_seq"]
        report = eng.player_act("normal")
        assert report is not None and report.action_seq > seq_before
        assert eng.battle_state()["action_seq"] > seq_before
        assert eng.state == "act"


# =====================================================================================
# 4. 渲染层「移动到了{pos}」行（模板 battle_position_changed 配置化）
# =====================================================================================


class TestPositionChangedRender:
    def _player_outcome(self, events):
        return SimpleNamespace(
            actor="player", action_type="skill", target="E", hit=True,
            side_effects=events, final_damage=100, raw_damage=100, target_hp=300,
            player_max_hp=500, target_name="E", message="",
            intent_skill=None, special_action=None, player_guarding=False,
            defending=False, blocked=False, crit="low", skill_name=None,
            effect_desc=None, resource_text=None,
        )

    def _enemy_outcome(self):
        return SimpleNamespace(
            actor="enemy", action_type="normal", target="P", hit=True,
            side_effects=({"type": "position_changed", "actor": "player",
                           "side": "back", "height": "ground"},),
            final_damage=50, raw_damage=50, target_hp=450, player_max_hp=500,
            target_name="E", message="", intent_skill=None, special_action=None,
            player_guarding=False, defending=False, blocked=False, crit="low",
        )

    def test_player_self_move_line(self) -> None:
        """玩家机动（self reposition）→ 行动行集含「你 移动到了…」。"""
        lines = _render_player_action(self._player_outcome(
            ({"type": "position_changed", "actor": "player",
              "side": "back", "height": "ground"},)))
        assert any("移动到了" in ln and "你" in ln and "背后" in ln for ln in lines)

    def test_air_position_cn(self) -> None:
        """空中格中文：{pos} 显示「正面上空」等（复用 _position_cn 显示层映射）。"""
        lines = _render_player_action(self._player_outcome(
            ({"type": "position_changed", "actor": "player",
              "side": "front", "height": "air"},)))
        assert any("正面上空" in ln for ln in lines)

    def test_enemy_cast_line_shows_player(self) -> None:
        """怪冲锋 reposition 玩家 → 怪行动行集含「你 移动到了背后」（你=玩家视角）。"""
        line = _render_enemy_action(self._enemy_outcome())
        assert line is not None and "你" in line and "移动到了" in line

    def test_no_position_event_no_line(self) -> None:
        """无 position_changed 事件 → 无「移动到了」行。"""
        lines = _render_player_action(self._player_outcome(()))
        assert not any("移动到了" in ln for ln in lines)


# =====================================================================================
# 5. V-12 kind 推断 + 显式 kind 零红拦
# =====================================================================================


class TestRepositionValidator:
    def test_kind_inferred_utility(self) -> None:
        """kind 缺省 + reposition 效果 → 黄提示推断 utility（非红拦）。"""
        report: dict = {"errors": [], "warnings": []}
        validate_skills({"skills": [
            {"id": "s0", "name": "普攻", "kind": "damage", "type": "basic",
             "power": 100, "attack_type": "slash"},
            {"id": "s1", "name": "跃空", "type": "active", "power": 0,
             "effects": [{"type": "reposition", "target": "self", "height": "air"}]},
        ]}, report)
        assert report["errors"] == []
        assert any(e.get("rule") == "kind_inferred"
                   and e.get("value") == "utility" for e in report["warnings"])

    def test_explicit_kind_utility_zero_red(self) -> None:
        """显式 kind=utility 的 reposition 技 → 零红零黄。"""
        report: dict = {"errors": [], "warnings": []}
        validate_skills({"skills": [
            {"id": "s0", "name": "普攻", "kind": "damage", "type": "basic",
             "power": 100, "attack_type": "slash"},
            {"id": "s1", "name": "冲锋", "kind": "damage", "type": "active",
             "power": 120, "attack_type": "blunt",
             "effects": [{"type": "reposition_all", "mode": "rotate",
                          "mapping": {"front": "back"}}]},
        ]}, report)
        assert report["errors"] == [] and report["warnings"] == []
