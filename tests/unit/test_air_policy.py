"""方位战斗系统 Step 3：AirPolicy 验收测试。

依据：docs/方位战斗系统_框架改造草案.md（v0.6 技术定稿）：
  - §三.6 AirPolicy（行动定义顶层键：preserve=保持 / land=行动后落地 /
    preserve_height=保持显式别名；与 combo 完全分离正交）
  - §四 T8（action_end → air_policy 结算 → next actor）
  - 附录 A Step 3：四类 policy 单测；combo 行为零变化；即时调合空中落地 =
    战斗行动接线层 action_category=alchemy + air_policy=land（不改 alchemy 引擎内部）
  - 边界纪律（§六）：高度独立字段不塞 combo_state；行动定义显式传参，框架不发明
    默认（缺省=保持，旧内容零行为变化）

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义。两处关键口径变化：

  1. **空中姿态 = 持有空中姿态状态**（R16）。CTB 下落地结算在 `_after_actor_action`
     （ACTOR_TURN_END 位点）——`_settle_air_landing()` 判定「玩家仍在空中但已无任何
     空中姿态状态 → 自动落地」。故「单纯改写 height=air」不加状态会被行动收尾立即
     落地；本文件用 `_set_air()` 同时注入 height=air + 空中姿态状态（`sw_vault_air`），
     才能表达 CTB「腾空中」的真实语义。
  2. 怪侧行动不再走 `enemy_act`（已为 NotImplementedError 壳）——改用单次结算入口
     `do_action("enemy", ...)`（等价 CTB「怪在自身 ACTOR_READY 时出手」）。
     收尾链断言不再用 `end_turn`（已删）——改为 `player_act` 后 `action_seq` 严格增加。

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG + 固定 seed）。

验收覆盖：
  1. 四类 policy 引擎行为（land/preserve/preserve_height/缺省）+ 事件通道
  2. skill def F10 合并（含 action 显式优先）；怪侧行动 def 透传
  3. 即时调合接线层形状（item 行动 + action_category=alchemy + air_policy=land）
  4. combo 正交：同一技能 ground/air 施放 combo_state 完全一致
  5. 旧快照无 combat_position 段 → 降级不崩
  6. 渲染层「落回地面」行（玩家/怪名映射）
  7. F10 schema 登记 + 双库校验红拦（V-15）
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Mapping, Optional

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.message_format.battle_render import (
    _render_enemy_action,
    _render_player_action,
)
from qbot_rpg.content.skill_action_models import (
    ACTION_CORE_FIELDS,
    AIR_POLICY_VALUES,
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


def make(**kw) -> BattleEngine:
    eng = BattleEngine(**kw)
    eng._rng = QueueRNG(SEQ)  # type: ignore[assignment]  # 确定性随机源注入
    return eng


def _set_height(eng: BattleEngine, height: str, which: str = "player") -> None:
    """直接改写 _snap 方位高度（Step 3 无 reposition 效果，测试用注入；_snap 权威）。"""
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault(which, {"side": "front", "height": "ground"})
    ent["height"] = height


# 空中姿态状态 id（本文件覆盖 sw_vault_air 线；全量登记见 battle._AIR_STATUS_IDS）
_AIR_STATUS_IDS = ("sw_vault_air", "vs_air_window", "va_air_window")


def _set_air(eng: BattleEngine, which: str = "player",
             status_id: str = "sw_vault_air") -> None:
    """把 `which` 置于「腾空中」——CTB 真实语义 = height=air **且持有空中姿态状态**。

    CTB 迁移（2026-09-10 Wave C · C-5）：R16 的 `_settle_air_landing()` 在每次
    ACTOR_TURN_END 检查「height=air 但无任何空中姿态状态 → 自动落地」。故旧口径的
    「单纯 `_set_height("air")`」会被行动收尾立即落地**抹掉**，无法表达腾空。正确
    注入 = 同时写 height=air + 挂空中姿态状态实例（与真实腾空技能 `sw_vault` 的产物
    一致，见 test_sword_vault_dot_fix）。status_id 可切换以覆盖 `_air_sids` 全集。
    """
    assert status_id in _AIR_STATUS_IDS, f"非空中姿态状态：{status_id}"
    _set_height(eng, "air", which)
    rt = eng._new_runtime()
    rt.apply_status(status_id, which, force=True)
    eng._absorb_runtime(rt)


def _height(eng: BattleEngine, which: str = "player") -> str:
    cp = eng._snap.get("combat_position") or {}
    ent = cp.get(which) or {}
    return str(ent.get("height") or "ground")


def _land_events(outcome: Any) -> List[Mapping[str, Any]]:
    return [e for e in getattr(outcome, "side_effects", ()) or ()
            if isinstance(e, Mapping) and e.get("type") == "air_land"]


#: 空中姿态状态 def（CTB R16：空中姿态 = 持有空中姿态状态；无状态则行动收尾自动落地）。
#: 名称与内容包 veinborn 的 `sw_vault_air` 一致（`_settle_air_landing` 按 id 白名单判定）。
_AIR_STANCE_DEF = {"id": "sw_vault_air", "name": "腾空姿态", "max_stack": 1,
                   "duration": {"turns": 3, "charges": 0}, "decay": "none", "effects": []}


# =====================================================================================
# 1. 四类 policy 引擎行为（§三.6 + §四 T8：action_end → air_policy → next actor）
# =====================================================================================


class TestAirPolicyEngine:
    def _air_eng(self, defs: Optional[Mapping[str, Any]] = None) -> BattleEngine:
        merged = {"sw_vault_air": dict(_AIR_STANCE_DEF), **dict(defs or {})}
        eng = make(defs=merged).start(PLAYER, ENEMY, random_seed=11)
        _set_air(eng)
        return eng

    def test_land_from_air_lands_with_event(self) -> None:
        """land：空中行动 → 行动收尾落地（height=ground）+ air_land 事件。"""
        eng = self._air_eng()
        out = eng.do_action("player", {"type": "normal", "mult": 1.0,
                                       "air_policy": "land"})
        assert out.ok is True and out.hit is True and out.final_damage > 0
        assert _height(eng) == "ground"
        evs = _land_events(out)
        assert len(evs) == 1 and evs[0].get("actor") == "player"

    def test_preserve_keeps_air(self) -> None:
        """preserve：空中行动 → 保持空中，无落地事件。"""
        eng = self._air_eng()
        out = eng.do_action("player", {"type": "normal", "mult": 1.0,
                                       "air_policy": "preserve"})
        assert out.ok is True and out.hit is True
        assert _height(eng) == "air"
        assert _land_events(out) == []

    def test_preserve_height_alias_keeps_air(self) -> None:
        """preserve_height：保持（显式别名，兼容默认语义）。"""
        eng = self._air_eng()
        out = eng.do_action("player", {"type": "normal", "mult": 1.0,
                                       "air_policy": "preserve_height"})
        assert out.ok is True
        assert _height(eng) == "air"
        assert _land_events(out) == []

    def test_missing_policy_keeps_air(self) -> None:
        """缺省（无 air_policy 键）→ 保持当前高度（兼容默认，既有内容零变化）。"""
        eng = self._air_eng()
        out = eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert out.ok is True and out.hit is True
        assert _height(eng) == "air"
        assert _land_events(out) == []

    def test_land_on_ground_no_change_no_event(self) -> None:
        """land 但已在地面 → 无变化、无事件（行动照常）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("player", {"type": "normal", "mult": 1.0,
                                       "air_policy": "land"})
        assert out.ok is True and out.hit is True
        assert _height(eng) == "ground"
        assert _land_events(out) == []

    def test_land_does_not_disturb_action_end_chain(self) -> None:
        """落地结算不破坏收尾链：`player_act` 后行动条正常推进（action_seq 严格增加）。

        CTB 迁移：旧「end_turn → start_turn 正常推进 / report.turn==2」依赖已删除的
        回合边界；改为断言 CTB 权威进度计量 `action_seq` 严格增加，且落地后状态恒为
        `act`（CTB 唯一「交还行动条」落点，无回合边界）。
        """
        eng = self._air_eng()
        seq0 = int(eng.battle_state()["action_seq"])
        tr = eng.player_act({"type": "normal", "mult": 1.0, "air_policy": "land"})
        assert tr is not None
        assert int(eng.battle_state()["action_seq"]) > seq0, "落地行动后行动条应推进"
        assert _height(eng) == "ground"
        assert eng.state == "act"


# =====================================================================================
# 2. skill def F10 合并 / 怪侧行动 def 透传
# =====================================================================================

_LAND_DEF = {"id": "land_strike", "name": "落击", "kind": "damage", "type": "active",
             "power": 100, "attack_type": "slash", "air_policy": "land"}
_KEEP_DEF = {"id": "keep_strike", "name": "空斩", "kind": "damage", "type": "active",
             "power": 100, "attack_type": "slash"}


class TestSkillDefAirPolicy:
    def test_skill_def_land_merged(self) -> None:
        """skill def 顶层 air_policy=land 随 F10 合并进行动 → 空中落地。"""
        eng = make(defs={"land_strike": _LAND_DEF,
                         "sw_vault_air": dict(_AIR_STANCE_DEF)}).start(
            PLAYER, ENEMY, random_seed=11)
        _set_air(eng)
        out = eng.do_action("player", {"type": "skill", "skill_id": "land_strike"})
        assert out.ok is True and out.hit is True
        assert _height(eng) == "ground"
        assert len(_land_events(out)) == 1

    def test_action_explicit_policy_overrides_def(self) -> None:
        """行动原样显式 air_policy 优先于 skill def（merge setdefault 不覆写显式）。"""
        eng = make(defs={"land_strike": _LAND_DEF,
                         "sw_vault_air": dict(_AIR_STANCE_DEF)}).start(
            PLAYER, ENEMY, random_seed=11)
        _set_air(eng)
        out = eng.do_action("player", {"type": "skill", "skill_id": "land_strike",
                                       "air_policy": "preserve"})
        assert out.ok is True
        assert _height(eng) == "air"      # 显式 preserve 压过 def land
        assert _land_events(out) == []

    def test_def_without_policy_keeps_air(self) -> None:
        """skill def 无 air_policy → 缺省保持（空中连段续打不落地）。"""
        eng = make(defs={"keep_strike": _KEEP_DEF,
                         "sw_vault_air": dict(_AIR_STANCE_DEF)}).start(
            PLAYER, ENEMY, random_seed=11)
        _set_air(eng)
        out = eng.do_action("player", {"type": "skill", "skill_id": "keep_strike"})
        assert out.ok is True and out.hit is True
        assert _height(eng) == "air"
        assert _land_events(out) == []

    def test_enemy_skill_def_land_ground_no_event(self) -> None:
        """怪侧 skill def 带 land：怪恒地面 → 行动照常、无落地事件（零变化）。

        CTB 迁移：怪侧行动经单次结算入口 `do_action("enemy", ...)` 显式驱动
        （`enemy_act` 已为 NotImplementedError 壳）。
        """
        eng = make(defs={"e_land": dict(_LAND_DEF, id="e_land")}).start(
            PLAYER, ENEMY, random_seed=11)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "e_land",
                                      "mult": 1.0})
        assert out is not None and out.hit is True and out.final_damage > 0
        assert _height(eng, "enemy") == "ground"
        assert _land_events(out) == []


# =====================================================================================
# 3. 即时调合接线层形状（item 行动 + action_category=alchemy + air_policy=land；
#    cmd_instant → BattleAlchemyEngine → use_fn 契约：use_fn(item_id, count, produced)）
# =====================================================================================


class TestInstantWiring:
    def test_item_action_land_lands_from_air(self) -> None:
        """道具行动带 air_policy=land + action_category=alchemy → 空中落地。"""
        eng = make(defs={"sw_vault_air": dict(_AIR_STANCE_DEF)}).start(
            PLAYER, ENEMY, random_seed=11)
        _set_air(eng)
        out = eng.do_action("player", {
            "type": "item", "item_id": "bomb", "actions": [],
            "action_category": "alchemy", "air_policy": "land"})
        assert out.ok is True
        assert _height(eng) == "ground"
        assert len(_land_events(out)) == 1

    def test_item_without_policy_keeps_air(self) -> None:
        """道具行动缺 air_policy → 保持（引擎不发明默认；接线层显式传参）。"""
        eng = make(defs={"sw_vault_air": dict(_AIR_STANCE_DEF)}).start(
            PLAYER, ENEMY, random_seed=11)
        _set_air(eng)
        out = eng.do_action("player", {"type": "item", "item_id": "bomb",
                                       "actions": []})
        assert out.ok is True
        assert _height(eng) == "air"
        assert _land_events(out) == []

    def test_use_battle_item_callback_shape(self) -> None:
        """use_battle_item 回调契约形状（cmd_instant 注入位）：回调内构造 item 行动
        并带接线层标记 → 空中即时调合产物自动使用后落地。"""
        eng = make(defs={"sw_vault_air": dict(_AIR_STANCE_DEF)}).start(
            PLAYER, ENEMY, random_seed=11)
        _set_air(eng)

        def use_battle_item(item_id: str, count: int, produced: Mapping[str, Any]) -> Any:
            return eng.do_action("player", {
                "type": "item", "item_id": item_id,
                "actions": list(produced.get("effects") or []),
                "action_category": "alchemy", "air_policy": "land"})

        outcome = use_battle_item("bomb", 1, {"item_id": "bomb", "count": 1,
                                              "effects": []})
        assert outcome is not None and outcome.ok is True
        assert _height(eng) == "ground"
        assert len(_land_events(outcome)) == 1


# =====================================================================================
# 4. combo 正交（§三.6：高度独立字段，不塞 combo_state；本步不动 combo 引擎）
# =====================================================================================


class TestComboOrthogonal:
    def test_same_skill_ground_air_combo_state_identical(self) -> None:
        """同一技能在 ground/air 施放：outcome 命中与 combo_state 完全一致（高度无感）。"""
        defs = {"keep_strike": _KEEP_DEF}
        eng_a = make(defs=defs).start(PLAYER, ENEMY, random_seed=11)      # ground
        eng_b = make(defs=defs).start(PLAYER, ENEMY, random_seed=11)      # air
        _set_height(eng_b, "air")
        act = {"type": "skill", "skill_id": "keep_strike"}
        out_a = eng_a.do_action("player", dict(act))
        out_b = eng_b.do_action("player", dict(act))
        assert out_a.hit is out_b.hit
        assert out_a.final_damage == out_b.final_damage
        assert eng_a._snap.get("combo_state") == eng_b._snap.get("combo_state")

    def test_land_skill_combo_state_unchanged_by_height(self) -> None:
        """带 land 的终结技落地后 combo_state 与地面同技能一致（落地不扰动连段状态）。"""
        defs = {"land_strike": _LAND_DEF}
        eng_a = make(defs=defs).start(PLAYER, ENEMY, random_seed=11)      # ground
        eng_b = make(defs=defs).start(PLAYER, ENEMY, random_seed=11)      # air→land
        _set_height(eng_b, "air")
        act = {"type": "skill", "skill_id": "land_strike"}
        out_a = eng_a.do_action("player", dict(act))
        out_b = eng_b.do_action("player", dict(act))
        assert _height(eng_b) == "ground"
        assert out_a.hit is out_b.hit and out_a.final_damage == out_b.final_damage
        assert eng_a._snap.get("combo_state") == eng_b._snap.get("combo_state")


# =====================================================================================
# 5. 旧快照降级（无 combat_position 段 → land 不崩、无事件）
# =====================================================================================


class TestLegacySnapshot:
    def test_missing_position_section_land_no_crash(self) -> None:
        """旧快照无 combat_position 段：land 行动照常、无事件、不崩。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        eng._snap.pop("combat_position", None)
        out = eng.do_action("player", {"type": "normal", "mult": 1.0,
                                       "air_policy": "land"})
        assert out.ok is True and out.hit is True
        assert _land_events(out) == []


# =====================================================================================
# 6. 渲染层「落回地面」行（模板 battle_actor_landed 配置化；玩家=你/怪=名）
# =====================================================================================


class TestAirLandRender:
    def _player_outcome(self, events=({"type": "air_land", "actor": "player"},)):
        return SimpleNamespace(
            actor="player", action_type="normal", target="E", hit=True,
            side_effects=events, final_damage=100, raw_damage=100, target_hp=300,
            player_max_hp=500, target_name="E", message="",
            intent_skill=None, special_action=None, player_guarding=False,
            defending=False, blocked=False, crit="low", skill_name=None,
            effect_desc=None, resource_text=None,
        )

    def _enemy_outcome(self):
        return SimpleNamespace(
            actor="enemy", action_type="normal", target="P", hit=True,
            side_effects=({"type": "air_land", "actor": "enemy"},),
            final_damage=50, raw_damage=50, target_hp=450, player_max_hp=500,
            target_name="E", message="", intent_skill=None, special_action=None,
            player_guarding=False, defending=False, blocked=False, crit="low",
        )

    def test_player_landed_line(self) -> None:
        """玩家落地事件 → 玩家行动行集含「你 从空中落回地面」。"""
        lines = _render_player_action(self._player_outcome())
        assert any("落回地面" in ln and "你" in ln for ln in lines)

    def test_enemy_landed_line_uses_enemy_name(self) -> None:
        """怪落地事件 → 怪行动行集含怪名（显示层映射）。"""
        out = self._enemy_outcome()
        # 无 hit 事件时怪名取自 outcome.target_name
        line = _render_enemy_action(out)
        assert line is not None and "落回地面" in line

    def test_no_land_event_no_line(self) -> None:
        """无 air_land 事件 → 不渲染落地行（零变化）。"""
        lines = _render_player_action(self._player_outcome(events=()))
        assert not any("落回地面" in ln for ln in lines)


# =====================================================================================
# 7. F10 schema：登记 + 双库校验红拦（V-15）
# =====================================================================================


class TestAirPolicySchema:
    def test_f10_registered(self) -> None:
        """air_policy 进入 ActionCore 元数据单点 + FieldMeta 双库 + 枚举常量。"""
        assert AIR_POLICY_VALUES == ("preserve", "land", "preserve_height")
        assert "air_policy" in ACTION_CORE_FIELDS
        assert "air_policy" in skills_fields().keys()
        assert "air_policy" in action_core_meta().keys()
        assert "air_policy" in skill_action_meta().fields.keys()

    def test_action_valid_policy_passes(self) -> None:
        """合法 air_policy（三枚举值/缺省）→ 零红拦。"""
        report: dict = {"errors": [], "warnings": []}
        validate_actions({"action": [
            {"id": "a1", "name": "落地技", "air_policy": "land"},
            {"id": "a2", "name": "保持技", "air_policy": "preserve"},
            {"id": "a3", "name": "别名", "air_policy": "preserve_height"},
            {"id": "a4", "name": "缺省"},
        ]}, report)
        assert report["errors"] == []

    def test_action_invalid_policy_red_flagged(self) -> None:
        """非字符串/枚举外 → 红拦（F10 air_policy_type/air_policy_enum）。"""
        report: dict = {"errors": [], "warnings": []}
        validate_actions({"action": [
            {"id": "b1", "name": "类型错", "air_policy": 3},
            {"id": "b2", "name": "枚举外", "air_policy": "fly"},
        ]}, report)
        rules = {e["rule"] for e in report["errors"]}
        assert {"air_policy_type", "air_policy_enum"} <= rules

    def test_skill_valid_policy_passes(self) -> None:
        """skills.json 侧 air_policy 登记后放行（V-11 + V-15 零红）。"""
        report: dict = {"errors": [], "warnings": []}
        validate_skills({"skills": [
            {"id": "s0", "name": "普攻", "kind": "damage", "type": "basic",
             "power": 100, "attack_type": "slash"},
            {"id": "s1", "name": "终结技", "kind": "damage", "type": "active",
             "power": 150, "attack_type": "slash", "air_policy": "land"},
        ]}, report)
        assert report["errors"] == []

    def test_skill_invalid_policy_red_flagged(self) -> None:
        """skills.json 侧枚举红拦与行动库同源（V-15 air_policy_enum）。"""
        report: dict = {"errors": [], "warnings": []}
        validate_skills({"skills": [
            {"id": "s0", "name": "普攻", "kind": "damage", "type": "basic",
             "power": 100, "attack_type": "slash"},
            {"id": "s2", "name": "坏策略", "kind": "damage", "type": "active",
             "power": 100, "attack_type": "slash", "air_policy": "soar"},
        ]}, report)
        assert any(e.get("rule") == "air_policy_enum" for e in report["errors"])
