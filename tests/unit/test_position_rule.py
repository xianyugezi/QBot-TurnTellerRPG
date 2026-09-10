"""方位战斗系统 Step 1：PositionState + PositionRule 验收测试。

依据：docs/方位战斗系统_框架改造草案.md（v0.6 技术定稿）：
  - §三.1 PositionState（combat_position 每 combatant：side/height）
  - §三.2 PositionRule（ActionCore 统一扩展 side[]/height[]，缺省=全量；命中资格）
  - §四 T8 结算时序（height check → 无命中资格 → miss 语义：照常消耗、无伤害/破坏力，
    文案「够不着」，不拒绝施放）
  - 附录 A Step 1：ActionCore 扩展 position_rule（skills/action 共用）；miss 语义
    （够不着不拒施放）；条件 position_match（统一原语，勿做多个零散条件）
  - 硬性规则：玩家技能 position_rule 消费点=部位命中资格（Step 2 part resolve），
    Step 1 只登记/校验不消费（引擎对玩家侧 rule 惰性）；怪物行动 rule 消费点=玩家
    位置 miss（本步接线）

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG + 固定 seed）。

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义。
  - 怪侧 miss 语义（本文件 §5）原经 `enemy_act` 驱动；CTB 下 `enemy_act` 已为
    NotImplementedError 壳，改用单次结算入口 `do_action("enemy", ...)`——等价
    CTB「怪在自身 ACTOR_READY 时出手」，miss 语义（够不着不拒施放/照常消耗）不变。
  - 「打空仍占行动槽」（末用例）改为断言 CTB 权威进度计量 `action_seq` 随行动推进，
    不再依赖已删除的 `end_turn` / 回合边界。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, Optional
from types import SimpleNamespace

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ConditionCtx, evaluate_condition
from qbot_rpg.core.message_format.battle_render import _render_enemy_action
from qbot_rpg.core.monster_conditions import TRIGGER_TYPES, evaluate_conditions_all
from qbot_rpg.core.position import position_of, rule_permits, spec_permits
from qbot_rpg.content.skill_action_models import (
    ACTION_CORE_FIELDS,
    action_core_meta,
    skill_action_meta,
    validate_actions,
)
from qbot_rpg.content.skill_models import skills_fields
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


_AIR_STANCE_DEF = {"id": "sw_vault_air", "name": "腾空姿态", "max_stack": 1,
                   "duration": {"turns": 3, "charges": 0}, "decay": "none", "effects": []}


def make() -> BattleEngine:
    """构造引擎（默认含空中姿态状态 def，供 CTB「真实腾空」注入用）。"""
    eng = BattleEngine(defs={"sw_vault_air": dict(_AIR_STANCE_DEF)})
    eng._rng = QueueRNG(SEQ)  # type: ignore[assignment]  # 确定性随机源注入（对齐 test_battle_engine）
    return eng


def _snap_put_position(eng: BattleEngine, side: Optional[str] = None,
                       height: Optional[str] = None, which: str = "player") -> None:
    """直接改写 _snap 方位（Step 1 阶段无 reposition 效果，测试用注入；_snap 为权威）。

    CTB（R16）：置 height=air 须同时挂空中姿态状态，否则该 actor 行动收尾会被
    `_settle_air_landing` 自动落地（「无姿态却滞空」在 CTB 不成立）。
    """
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault(which, {"side": "front", "height": "ground"})
    if side:
        ent["side"] = side
    if height:
        ent["height"] = height
        if height == "air":
            rt = eng._new_runtime()
            rt.apply_status("sw_vault_air", which, force=True)
            eng._absorb_runtime(rt)


def enemy_act_ctb(eng: BattleEngine, action_dict: Mapping[str, Any]) -> Optional[Any]:
    """CTB 等价于旧 `enemy_act(action_dict=...)`：**直接经 `do_action` 提交一次怪物行动**。

    为何不走 `player_act` 驱动：玩家一旦提交行动，`_face_enemy()` / 空中姿态落地
    （R16）会把玩家方位**重置为正面贴地**，从而抹掉本组测试要验证的「玩家在空中 /
    绕到背后」前置位姿。CTB 下 `do_action(actor, action_dict)` 仍是**单次行动结算**
    的合法入口（【平移】语义），等价于旧 `enemy_act` 的「显式指定内容 → 单次结算」，
    且不触碰玩家位姿与调度器时间轴 → 位姿断言纯净。
    """
    return eng.do_action("enemy", dict(action_dict))


# =====================================================================================
# 1. position 纯函数（rule_permits / position_of 矩阵）
# =====================================================================================


class TestPositionRuleCore:
    def test_rule_missing_or_empty_permits_all(self) -> None:
        """规则缺省/空 dict → 全量放行（既有行动零变化）。"""
        assert rule_permits(None, "front", "ground") is True
        assert rule_permits({}, "back", "air") is True
        assert rule_permits("not-a-mapping", "front", "ground") is True

    def test_axis_default_or_empty_means_all(self) -> None:
        """轴缺省/空数组 = 该轴全量（§三.2 缺省=全部）。"""
        assert rule_permits({"side": ["front"]}, "front", "air") is True   # height 轴缺省
        assert rule_permits({"height": ["air"]}, "back", "air") is True    # side 轴缺省
        assert rule_permits({"side": [], "height": ["ground"]}, "front", "ground") is True

    def test_both_axes_must_hit(self) -> None:
        """两轴显式限定 → 必须同时覆盖（交集语义）。"""
        rule = {"side": ["front", "back"], "height": ["ground"]}
        assert rule_permits(rule, "front", "ground") is True
        assert rule_permits(rule, "back", "ground") is True
        assert rule_permits(rule, "left", "ground") is False    # side 未覆盖
        assert rule_permits(rule, "front", "air") is False      # height 未覆盖

    def test_str_single_value_wrapped(self) -> None:
        """引擎侧防御：str 单值等价单元素数组。"""
        assert rule_permits({"side": "front"}, "front", "ground") is True
        assert rule_permits({"side": "front"}, "back", "ground") is False

    def test_position_of_defaults_when_section_missing(self) -> None:
        """快照缺 combat_position 段 → 缺省正面贴地（旧快照不崩，RS-5 口径）。"""
        assert position_of({}, "player") == ("front", "ground")
        assert position_of({"combat_position": None}, "player") == ("front", "ground")

    def test_position_of_reads_and_degrades(self) -> None:
        """正常读取 + 缺侧/非法值逐级降级。"""
        snap = {"combat_position": {
            "player": {"relative_to": "enemy", "side": "back", "height": "air"},
            "enemy": {"side": "front"},
        }}
        assert position_of(snap, "player") == ("back", "air")
        assert position_of(snap, "enemy") == ("front", "ground")   # height 缺失 → ground
        assert position_of(snap, "nobody") == ("front", "ground")  # 未知侧 → 缺省

    def test_spec_permits_ignores_extra_keys(self) -> None:
        """spec_permits 忽略 which 等额外键（统一条件原语）。"""
        spec = {"which": "self", "side": ["front"], "height": ["air"]}
        assert spec_permits(spec, ("front", "air")) is True
        assert spec_permits(spec, ("back", "air")) is False


# =====================================================================================
# 2. ActionCore schema：登记 + 形状校验（skills/action 双库）
# =====================================================================================


class TestPositionRuleSchema:
    def test_action_core_fields_registered(self) -> None:
        """position_rule 进入 ActionCore 元数据单点（skills/action 共用，V-11 放行）。"""
        assert "position_rule" in ACTION_CORE_FIELDS
        assert "position_rule" in skills_fields().keys()
        # ActionCore 元数据单点公开工厂（field_meta 登记源）同含 F08
        assert "position_rule" in action_core_meta().keys()
        assert "position_rule" in skill_action_meta().fields.keys()

    def test_action_valid_rule_passes(self) -> None:
        """合法 position_rule（含空轴=全量）→ 零红拦。"""
        report: dict = {"errors": [], "warnings": []}
        validate_actions({"action": [
            {"id": "a1", "name": "地面扫尾", "position_rule": {"side": ["left", "right"],
                                                              "height": ["ground"]}},
            {"id": "a2", "name": "全量攻击", "position_rule": {}},
            {"id": "a3", "name": "旧行动无规则"},
        ]}, report)
        assert report["errors"] == []

    def test_action_invalid_rule_red_flagged(self) -> None:
        """非对象/枚举外/未知轴 → 红拦；合法值只建议不限制。"""
        report: dict = {"errors": [], "warnings": []}
        validate_actions({"action": [
            {"id": "b1", "name": "规则非对象", "position_rule": "front"},
            {"id": "b2", "name": "方位枚举外", "position_rule": {"side": ["up"]}},
            {"id": "b3", "name": "高度枚举外", "position_rule": {"height": ["sea"]}},
            {"id": "b4", "name": "未知轴", "position_rule": {"facing": ["front"]}},
            {"id": "b5", "name": "轴类型错", "position_rule": {"side": 3}},
        ]}, report)
        rules = {e["rule"] for e in report["errors"]}
        assert {"position_rule_shape", "position_rule_axis_enum",
                "position_rule_unknown_axis", "position_rule_axis_type"} <= rules

    def test_skill_valid_rule_passes(self) -> None:
        """skills.json 侧 position_rule 登记后放行（V-11 + 形状校验零红）。"""
        report: dict = {"errors": [], "warnings": []}
        validate_skills({"skills": [
            {"id": "s0", "name": "普攻", "kind": "damage", "type": "basic",
             "power": 100, "attack_type": "slash"},
            {"id": "s1", "name": "跃空斩", "kind": "damage", "type": "active",
             "power": 120, "attack_type": "slash",
             "position_rule": {"height": ["air"]}},
        ]}, report)
        assert report["errors"] == []

    def test_skill_invalid_rule_red_flagged(self) -> None:
        """skills.json 侧形状红拦与行动库同源（V-14）。"""
        report: dict = {"errors": [], "warnings": []}
        validate_skills({"skills": [
            {"id": "s0", "name": "普攻", "kind": "damage", "type": "basic",
             "power": 100, "attack_type": "slash"},
            {"id": "s2", "name": "坏规则", "kind": "damage", "type": "active",
             "power": 100, "attack_type": "slash",
             "position_rule": {"side": ["under"]}},
        ]}, report)
        assert any(e.get("rule") == "position_rule_axis_enum" for e in report["errors"])


# =====================================================================================
# 3. 条件 position_match（combo 统一条件原语）
# =====================================================================================


class TestComboPositionMatch:
    def _ctx(self, self_pos, target_pos):
        return ConditionCtx(positions={"self": self_pos, "target": target_pos})

    def test_match_self_position(self) -> None:
        """self 方位命中（空中技派生条件：自己 height=air）。"""
        ctx = self._ctx({"side": "front", "height": "air"}, {"side": "front", "height": "ground"})
        assert evaluate_condition(
            {"position_match": {"which": "self", "height": ["air"]}}, ctx) is True
        assert evaluate_condition(
            {"position_match": {"which": "self", "side": ["back"]}}, ctx) is False
        assert evaluate_condition(
            {"position_match": {"height": ["air"]}}, ctx) is True  # which 缺省 self

    def test_match_target_position(self) -> None:
        """target 方位命中（目标在背后才能追击）。"""
        ctx = self._ctx({"side": "back", "height": "ground"}, {"side": "back", "height": "ground"})
        assert evaluate_condition(
            {"position_match": {"which": "target", "side": ["back"]}}, ctx) is True
        assert evaluate_condition(
            {"position_match": {"which": "target", "side": ["front"]}}, ctx) is False

    def test_fail_safe_when_no_position_data(self) -> None:
        """ctx.positions 缺省/未知 which/spec 非对象 → 条件不满足（安全失败）。"""
        ctx = ConditionCtx()  # positions 缺省 {}
        assert evaluate_condition({"position_match": {"height": ["air"]}}, ctx) is False
        ctx2 = self._ctx(
            {"side": "front", "height": "ground"}, {"side": "front", "height": "ground"})
        assert evaluate_condition(
            {"position_match": {"which": "nobody", "side": ["front"]}}, ctx2) is False
        assert evaluate_condition({"position_match": "air"}, ctx2) is False

    def test_compound_and_empty_condition(self) -> None:
        """复合拓扑 + 空条件恒真（未知键安全失败不受影响）。"""
        ctx = self._ctx({"side": "front", "height": "air"}, {"side": "front", "height": "ground"})
        assert evaluate_condition(
            {"and": [{"position_match": {"height": ["air"]}}, {"count": {"eq": 0}}]}, ctx) is True
        assert evaluate_condition(
            {"position_match": {"height": ["ground"]}, "and": []}, ctx) is False
        assert evaluate_condition({}, ctx) is True


# =====================================================================================
# 4. 怪物条件行动 position_match trigger
# =====================================================================================


class TestMonsterPositionMatchTrigger:
    def test_trigger_type_registered(self) -> None:
        """TRIGGER_TYPES 含 position_match（16 类）。"""
        assert "position_match" in TRIGGER_TYPES

    def test_player_air_triggers_air_action(self) -> None:
        """玩家在空中 → 对空行动匹配；落地 → 不匹配。"""
        sa: List[Mapping[str, Any]] = [{"id": "air_strike", "priority": 1, "trigger": {
            "type": "position_match", "which": "player", "height": ["air"]}}]
        bs_air = {"ai_state": {}, "turn": 1, "combat_position": {
            "player": {"side": "front", "height": "air"},
            "enemy": {"side": "front", "height": "ground"}}}
        bs_ground = {"ai_state": {}, "turn": 1, "combat_position": {
            "player": {"side": "front", "height": "ground"},
            "enemy": {"side": "front", "height": "ground"}}}
        rng = random.Random(7)
        assert evaluate_conditions_all(sa, bs_air, rng=rng, commit=False)
        assert evaluate_conditions_all(sa, bs_ground, rng=rng, commit=False) == []

    def test_self_side_and_axes(self) -> None:
        """which=self 读怪物自己方位；side/height 双轴交集。"""
        sa: List[Mapping[str, Any]] = [{"id": "self_check", "priority": 1, "trigger": {
            "type": "position_match", "which": "self", "side": ["front"],
            "height": ["ground"]}}]
        bs: Dict[str, Any] = {"ai_state": {}, "turn": 1, "combat_position": {
            "player": {"side": "front", "height": "ground"},
            "enemy": {"side": "front", "height": "ground"}}}
        rng = random.Random(3)
        assert evaluate_conditions_all(sa, bs, rng=rng, commit=False)
        bs["combat_position"]["enemy"]["height"] = "air"
        assert evaluate_conditions_all(sa, bs, rng=rng, commit=False) == []


# =====================================================================================
# 5. 战斗引擎：怪物 miss（够不着）语义 + 玩家侧 rule 惰性（施放门禁不变）
# =====================================================================================


class TestBattleEnemyPositionMiss:
    def test_ground_sweep_hits_ground_player(self) -> None:
        """地面扫尾（height=[ground]）打地面玩家 → 正常命中（基线）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        out = enemy_act_ctb(eng, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"height": ["ground"]}})
        assert out is not None and out.hit is True
        assert out.final_damage > 0

    def test_ground_only_rule_misses_air_player(self) -> None:
        """玩家在空中 → 地面技打空：照常消耗、无伤害、文案够不着（不拒绝施放）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        hp_before = eng.battle_state()["player"]["hp"]
        _snap_put_position(eng, None, "air")   # 玩家 height=air
        out = enemy_act_ctb(eng, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"height": ["ground"]}})
        assert out is not None
        assert out.ok is True and out.hit is False
        assert out.final_damage == 0 and out.raw_damage == 0
        assert "够不着" in out.message
        assert eng.battle_state()["player"]["hp"] == hp_before  # 无扣血
        # side_effects 带 position_miss 事件（含方位格，渲染层模板消费）
        pm = [e for e in out.side_effects if e.get("type") == "position_miss"]
        assert pm and pm[0]["height"] == "air" and pm[0]["side"] == "front"
        # action_record 的 rating 记 miss 标记（日志/测试可观察；rating 整包入流水）
        last = [r for r in eng.battle_state()["action_record"]
                if r.get("actor") == "enemy"][-1]
        assert last["rating"].get("position_miss") is True

    def test_air_rule_hits_air_player(self) -> None:
        """对空技打空中玩家 → 命中（同规则命中面）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        _snap_put_position(eng, None, "air")
        out = enemy_act_ctb(eng, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"height": ["air"]}})
        assert out is not None and out.hit is True and out.final_damage > 0

    def test_side_axis_misses_player_at_back(self) -> None:
        """玩家绕到背后 → 正面技（side=[front]）打空；背后技命中。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        _snap_put_position(eng, "back", None)
        out = enemy_act_ctb(eng, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"side": ["front"]}})
        assert out is not None and out.hit is False and out.final_damage == 0
        eng2 = make().start(PLAYER, ENEMY, random_seed=11)
        _snap_put_position(eng2, "back", None)
        out2 = enemy_act_ctb(eng2, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"side": ["back"]}})
        assert out2 is not None and out2.hit is True and out2.final_damage > 0

    def test_legacy_snapshot_without_position_section_misses_air_rule(self) -> None:
        """旧快照无 combat_position 段 → 降级地面正面：对空技打空（不崩）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        eng._snap.pop("combat_position", None)
        out = enemy_act_ctb(eng, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"height": ["air"]}})
        assert out is not None and out.hit is False and "够不着" in out.message

    def test_player_side_rule_inert_until_step2(self) -> None:
        """玩家技能 position_rule 本步惰性（消费点=Step 2 part resolve）：不造成 miss，
        施放门禁/伤害照常（地面怪照常被打）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        hp_before = eng.battle_state()["enemy"]["hp"]
        out = eng.do_action("player", {
            "type": "skill", "mult": 1.0,
            "position_rule": {"height": ["air"]}})  # 若引擎误判会 miss
        assert out.hit is True and out.final_damage > 0
        assert eng.battle_state()["enemy"]["hp"] < hp_before

    def test_position_miss_action_slot_consumed(self) -> None:
        """打空仍占行动槽（消耗语义）：行动照常结算、落 action_record（不拒绝施放）。

        CTB 迁移（2026-09-10 Wave C · C-5）：旧「guard → enemy_act → end_turn(turn==2)」
        验证「打空占槽 + 回合推进」。CTB 无回合边界——「行动槽消耗」的可观测语义改为：
        打空**照常完成一次行动结算**（落 action_record、rating 记 position_miss、
        `hit=False` 但 `ok=True`），即行 动被消费而非被拒（区别于门禁拒绝）。
        """
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        _snap_put_position(eng, None, "air")
        rec_before = len([r for r in eng.battle_state()["action_record"]
                          if r.get("actor") == "enemy"])
        out = enemy_act_ctb(eng, {
            "type": "normal", "mult": 1.0,
            "position_rule": {"height": ["ground"]}})
        assert out is not None and out.ok is True and out.hit is False
        # 打空=照常消耗行动槽（结算完成、落流水），非门禁拒绝
        recs = [r for r in eng.battle_state()["action_record"] if r.get("actor") == "enemy"]
        assert len(recs) == rec_before + 1, "打空仍落一次行动流水（槽已消耗）"
        assert recs[-1]["rating"].get("position_miss") is True
        assert eng.state == "act", "结算后引擎回到可行动态"


# =====================================================================================
# 6. 渲染层：够不着行（模板配置化）vs 既有躲开行
# =====================================================================================


class TestPositionMissRender:
    def _outcome(self, position_miss: bool, side: str = "back", height: str = "air"):
        effects = ({"type": "position_miss", "side": side, "height": height},) \
            if position_miss else ()
        return SimpleNamespace(
            actor="enemy", action_type="normal", target="P", hit=False,
            side_effects=effects, final_damage=0, raw_damage=0, target_hp=495,
            player_max_hp=500, target_name="E", message="",
            intent_skill=None, special_action=None, player_guarding=False,
            defending=False, blocked=False, crit="low",
        )

    def test_position_miss_line_uses_template(self) -> None:
        """position_miss 标记 → 渲染「够不着」专属行（含中文方位——方位制闪避反馈）。"""
        line = _render_enemy_action(self._outcome(True))
        assert line is not None
        assert "够不着" in line and "背后上空" in line
        assert "躲开" not in line

    def test_dodge_miss_still_brep11(self) -> None:
        """miss 渲染兜底（模板含躲开行——roll miss 已移除，行为上不再触发）。"""
        line = _render_enemy_action(self._outcome(False))
        assert line is not None and "躲开" in line and "够不着" not in line
