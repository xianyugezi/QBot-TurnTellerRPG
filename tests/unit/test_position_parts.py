"""方位战斗系统 Step 2：parts[] + 破坏力验收测试。

依据：docs/方位战斗系统_框架改造草案.md（v0.6 技术定稿）：
  - §三.3 PartState（EnemyDef.parts[]：positions/break_threshold/target_priority/
    on_break{knockdown,marks,effects}；parts_state 实例段）
  - §三.4 BreakPowerEvent（每 damage segment 一次；break_damage_basis 默认 raw_damage
    ——命中/会心/格挡/防御/乱数后、DamagePipeline 前；公式走 formula 配置）
  - §四 T8（part resolve：position+action → candidate parts → priority 高/同值随机；
    无部位方位=纯本体；破位时序：本次破位不吃本次增伤）
  - §五（knockdown 走既有 status 体系挂 damage_mult；快照透传）
  - 附录 A Step 2（segment 级破坏力；多段每段一次；硬时序单测）
  - N1 数值阶段：测试经 params 注入 battle_position 段（默认零破坏基线不依赖内容包）

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG）。
"""

from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.damage import BattlePositionParams, DamageFormulaParams

# 对齐 test_battle_engine 构造口径
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


def _parts_enemy(parts, **over):
    e = dict(ENEMY)
    e.update(over)
    if parts is not None:
        e["parts"] = parts
    return e


# 龟背式示例（试点包同形）：壳=空中可达（四面全向）；头=地面可达
SHELL_PART = {
    "id": "shell", "name": "龟壳",
    "positions": {"side": ["front", "back", "left", "right"], "height": ["air"]},
    "break_threshold": 10, "target_priority": 0,
    "on_break": {"knockdown": 1, "marks": [], "effects": []},
}
HEAD_PART = {
    "id": "head", "name": "头",
    "positions": {"side": ["front", "back", "left", "right"], "height": ["ground"]},
    "break_threshold": 100, "target_priority": 0,
    "on_break": {"knockdown": 0},
}


def make(**kw):
    eng = BattleEngine(**kw)
    eng._rng = QueueRNG(SEQ)  # 确定性随机源注入（对齐 test_battle_engine 模式）
    return eng


def _enemy_hp(eng: BattleEngine) -> int:
    return int(eng.battle_state()["enemy"]["hp"])


def _player_segment_records(eng: BattleEngine, n: int = 2) -> list:
    """取该玩家行动产生的**最后 n 条玩家段记录**（按 actor 过滤）。

    CTB 迁移（2026-09-10 Wave C · C-5）：`do_action("player", ...)` 尾段经
    `_after_actor_action` → `_resolve_ready_actor` 会自动推进 NPC，把**怪物那一拍**
    也写进 `action_record`。故旧 `action_record[-2:]` 会错取成「玩家次段 + 怪物行动」。
    正确口径 = 只看 `actor == "player"` 的段记录（一次技能多段共属该玩家）。
    """
    recs = [r for r in eng.battle_state()["action_record"] if r.get("actor") == "player"]
    return recs[-n:]


def _parts_state(eng: BattleEngine) -> dict:
    return eng.battle_state().get("parts_state") or {}


# =====================================================================================
# 1. EnemyDef.parts[] schema 校验（R16）
# =====================================================================================

PACKS = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
LEGAL = PACKS / "legal"


def _load(name: str) -> list:
    data = json.loads((LEGAL / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _base_enemy(**overrides) -> dict:
    import copy

    for e in _load("enemies"):
        if e.get("id") == "rock_weasel":
            enemy = copy.deepcopy(e)
            enemy.update(overrides)
            return enemy
    raise AssertionError("legal/enemies.json 缺少 rock_weasel")


def _errs(rep, rule=None):
    out = [e for e in rep.errors if rule is None or e.detail.get("rule") == rule]
    return out


class TestPartsSchema:
    def test_valid_parts_zero_errors(self) -> None:
        """合法 parts（龟背示例形）→ 零红拦。"""
        enemy = _base_enemy(parts=[SHELL_PART, HEAD_PART])
        rep = check_pack({"action": _load("action"), "effects": _load("effects"),
                          "statuses": _load("statuses"), "items": _load("items"),
                          "enemies": [enemy]})
        assert _errs(rep) == []

    def test_invalid_parts_red_flagged(self) -> None:
        """非法形状红拦：类型/枚举/id 重复/未知键/阈值负/on_break 未知键。"""
        enemy = _base_enemy(parts=[
            {"id": "p1", "name": "坏位置", "break_threshold": 5,
             "positions": {"side": ["up"], "height": ["ground"]}},
            {"id": "p1", "name": "重复 id", "positions": {"side": ["front"], "height": ["air"]},
             "break_threshold": -1, "mystery": 1,
             "on_break": {"bogus": True}},
        ])
        rep = check_pack({"action": _load("action"), "effects": _load("effects"),
                          "statuses": _load("statuses"), "items": _load("items"),
                          "enemies": [enemy]})
        rules = {e.detail.get("rule") for e in rep.errors}
        assert {"R16_part_id_duplicate", "R16_part_positions_enum",
                "R16_part_threshold_negative", "R16_part_unknown_key",
                "R16_part_onbreak_unknown_key"} <= rules


# =====================================================================================
# 2. start 实例化 + 快照透传
# =====================================================================================


class TestPartsStateInit:
    def test_start_initializes_parts_state(self) -> None:
        """start 时按 enemy parts 配置实例化（id → {break_value:0, broken:false}）。"""
        eng = make().start(PLAYER, _parts_enemy([SHELL_PART, HEAD_PART]), random_seed=1)
        st = _parts_state(eng)
        assert set(st) == {"shell", "head"}
        assert st["shell"] == {"break_value": 0, "broken": False}

    def test_no_parts_keeps_empty_state(self) -> None:
        """无 parts 旧怪 → parts_state 保持空（零变化）。"""
        eng = make().start(PLAYER, dict(ENEMY), random_seed=1)
        assert _parts_state(eng) == {}

    def test_parts_state_survives_json_roundtrip(self) -> None:
        """中断恢复：累积值/破位态随快照透传（_snap 权威，恢复不重建）。"""
        ground_shell = dict(SHELL_PART, positions={"side": ["front", "back"],
                                                   "height": ["ground"]})
        eng = make().start(PLAYER, _parts_enemy([ground_shell]), random_seed=1)
        st = eng._snap["parts_state"]
        st["shell"]["break_value"] = 7.0
        snap = json.loads(json.dumps(eng.to_snapshot(), ensure_ascii=False))
        eng2 = BattleEngine.from_snapshot(snap)
        assert eng2._snap["parts_state"]["shell"]["break_value"] == 7.0
        # 续战仍可继续破（配置随 enemy combatant 透传）
        eng2._snap["enemy"]["hp"] = 400
        out = eng2.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 10})
        assert out.hit is True
        assert eng2._snap["parts_state"]["shell"]["broken"] is True


# =====================================================================================
# 3. 破坏力：公式参数/多段 N 次/破位时序（本次不吃增伤）
# =====================================================================================


class TestBreakPower:
    def _bp_engine(self, parts, bpp: BattlePositionParams | None = None, **kw):
        params = DamageFormulaParams(battle_position=bpp or BattlePositionParams())
        return make(params=params, **kw).start(PLAYER, _parts_enemy(parts), random_seed=3)

    def test_break_delta_formula_and_threshold(self) -> None:
        """delta = break_power + sqrt_coef×√(basis−base)；累计达阈值 → broken + 事件。"""
        eng = self._bp_engine([dict(SHELL_PART, positions={"side": ["front"],
                                                           "height": ["ground"]},
                                    break_threshold=10)],
                              bpp=BattlePositionParams(break_base_damage=0,
                                                       break_sqrt_coef=2.0))
        out = eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 5})
        assert out.hit is True
        st = eng._snap["parts_state"]["shell"]
        # 单段 basis = 段 raw（无破位乘区）；delta = 5 + 2×√raw（raw>0）
        seg_final = out.raw_damage
        expect = 5.0 + 2.0 * (max(0, seg_final) ** 0.5)
        assert abs(st["break_value"] - expect) < 1e-6
        assert st["broken"] is True
        events = [e for e in out.side_effects if e.get("type") == "part_break"]
        assert events and events[0]["part"] == "shell"

    def test_multi_segment_break_power_per_segment(self) -> None:
        """多段技能 hits=N → 破坏力每段一次（N 次累计；高阈值不破仍累计）。"""
        eng = self._bp_engine([dict(SHELL_PART, positions={"side": ["front"],
                                                           "height": ["ground"]},
                                    break_threshold=9999)],
                              bpp=BattlePositionParams(break_sqrt_coef=1.0))
        out = eng.do_action("player", {
            "type": "skill", "mult": 1.0, "break_power": 3,
            "segments": [{"mult": 1.0}, {"mult": 1.0}]})
        assert out.hit is True
        st = eng._snap["parts_state"]["shell"]
        assert st["broken"] is False
        # 每段一次：delta = break_power + √(段 raw)（basis 按段记录 final 反推）
        # CTB 迁移：段记录按 actor 过滤取（`do_action` 尾段自动推进 NPC 一拍）
        recs = _player_segment_records(eng, 2)
        expected = sum(3.0 + float(r["damage"]["final"]) ** 0.5 for r in recs)
        assert abs(st["break_value"] - expected) < 1e-6
        dmg_events = [e for e in out.side_effects if e.get("type") == "part_damage"]
        assert len(dmg_events) == 2  # 每段一次事件（N 次写死）
        assert dmg_events[0]["break_delta"] == dmg_events[1]["break_delta"]  # 同 roll 循环

    def test_break_this_segment_no_self_bonus(self) -> None:
        """硬时序：本次破位不吃本次增伤——破位段伤害 == 无部位本体伤害。"""
        bp = BattlePositionParams(broken_part_mult=1.5, break_sqrt_coef=1.0)
        parts = [dict(SHELL_PART, positions={"side": ["front"], "height": ["ground"]},
                      break_threshold=1)]  # 一击即破
        eng_a = make(params=DamageFormulaParams(battle_position=bp)).start(
            PLAYER, _parts_enemy(parts), random_seed=3)
        eng_b = make(params=DamageFormulaParams(battle_position=bp)).start(
            PLAYER, dict(ENEMY), random_seed=3)  # 无部位对照
        act = {"type": "normal", "mult": 1.0, "break_power": 1}
        a1 = eng_a.do_action("player", dict(act))
        b1 = eng_b.do_action("player", dict(act))
        assert a1.final_damage == b1.final_damage      # 破位段不吃 broken 乘区
        assert eng_a._snap["parts_state"]["shell"]["broken"] is True

    def test_broken_bonus_applies_next_segment(self) -> None:
        """破位后（同行动次段）打已破部位 = 常驻增伤 × broken_part_mult。

        CTB 迁移（2026-09-10 Wave C · C-5）：段记录改按 actor 过滤取（`do_action` 尾段
        会自动推进 NPC 一拍，旧 `action_record[-2:]` 会混入怪物记录）。
        """
        bp = BattlePositionParams(broken_part_mult=1.5, break_sqrt_coef=1.0)
        parts = [dict(SHELL_PART, positions={"side": ["front"], "height": ["ground"]},
                      break_threshold=1)]
        eng = make(params=DamageFormulaParams(battle_position=bp)).start(
            PLAYER, _parts_enemy(parts), random_seed=3)
        out = eng.do_action("player", {
            "type": "skill", "mult": 1.0, "break_power": 1,
            "segments": [{"mult": 1.0}, {"mult": 1.0}]})
        assert out.hit is True
        recs = _player_segment_records(eng, 2)
        d1, d2 = int(recs[0]["damage"]["final"]), int(recs[1]["damage"]["final"])
        assert d2 > d1 and d2 <= int(d1 * 1.5) + 1    # 次段 ≈ 首段 ×1.5（同 rolls）
        assert recs[0]["rating"].get("part") == "shell"
        assert recs[0]["rating"].get("part_broken") is True

    def test_break_base_damage_reduces_basis(self) -> None:
        """√ 括号内减基准（formula 配置）：basis = max(0, raw − base)。"""
        eng = self._bp_engine([dict(SHELL_PART, positions={"side": ["front"],
                                                           "height": ["ground"]},
                                    break_threshold=1000)],
                              bpp=BattlePositionParams(break_base_damage=60,
                                                       break_sqrt_coef=1.0))
        out = eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 0})
        raw = out.raw_damage
        expect = max(0.0, float(raw) - 60.0) ** 0.5
        assert abs(eng._snap["parts_state"]["shell"]["break_value"] - expect) < 1e-6


# =====================================================================================
# 4. 部位 resolve：方位格 ∩ 规则（含玩家侧 position_rule 消费）
# =====================================================================================


class TestPartResolve:
    def _eng(self, parts):
        return make().start(PLAYER, _parts_enemy(parts), random_seed=5)

    def test_ground_attack_hits_ground_part_only(self) -> None:
        """地面玩家 → 命中地面部位（头）；空中壳不可达（打不到=纯本体无破坏力）。"""
        parts = [SHELL_PART, HEAD_PART]
        eng = self._eng(parts)
        out = eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 10})
        assert out.hit is True
        st = _parts_state(eng)
        assert st["head"]["break_value"] > 0
        assert st["shell"]["break_value"] == 0       # 壳在 air 格，地面玩家未命中
        events = [e for e in out.side_effects if e.get("type") == "part_target"]
        assert events and events[0]["part"] == "head"

    def test_air_player_hits_air_part(self) -> None:
        """玩家跃空（注入快照格）→ 壳可打。"""
        eng = self._eng([SHELL_PART, HEAD_PART])
        eng._snap["combat_position"]["player"]["height"] = "air"
        eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 10})
        st = _parts_state(eng)
        assert st["shell"]["break_value"] > 0
        assert st["head"]["break_value"] == 0

    def test_action_rule_filters_parts(self) -> None:
        """玩家技能 position_rule 消费（F08）：地面技在空中打不到 air 壳。"""
        parts = [SHELL_PART, HEAD_PART]
        eng = self._eng(parts)
        eng._snap["combat_position"]["player"]["height"] = "air"
        out = eng.do_action("player", {"type": "skill", "mult": 1.0, "break_power": 10,
                                       "position_rule": {"height": ["ground"]}})
        assert out.hit is True
        st = _parts_state(eng)
        assert st["shell"]["break_value"] == 0       # 规则挡掉空中部位 → 纯本体
        assert st["head"]["break_value"] == 0
        # 对空技 → 打壳
        eng2 = self._eng(parts)
        eng2._snap["combat_position"]["player"]["height"] = "air"
        eng2.do_action("player", {"type": "skill", "mult": 1.0, "break_power": 10,
                                  "position_rule": {"height": ["air"]}})
        assert _parts_state(eng2)["shell"]["break_value"] > 0

    def test_target_priority_picks_highest(self) -> None:
        """同方位多部位 → target_priority 高者被选中（低者零累计）。"""
        lo = dict(SHELL_PART, id="low", positions={"side": ["front"],
                                                   "height": ["ground"]},
                  break_threshold=9999, target_priority=0)
        hi = dict(SHELL_PART, id="high", positions={"side": ["front"],
                                                    "height": ["ground"]},
                  break_threshold=9999, target_priority=5)
        eng = self._eng([lo, hi])
        out = eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 10})
        assert out.hit is True
        st = _parts_state(eng)
        assert st["high"]["break_value"] > 0 and st["low"]["break_value"] == 0

    def test_equal_priority_picks_one_randomly(self) -> None:
        """同值优先级 → 随机取一（恰一个累计；roll 确定性经 QueueRNG）。"""
        a = dict(SHELL_PART, id="a", positions={"side": ["front"], "height": ["ground"]},
                 break_threshold=9999, target_priority=1)
        b = dict(SHELL_PART, id="b", positions={"side": ["front"], "height": ["ground"]},
                 break_threshold=9999, target_priority=1)
        eng = self._eng([a, b])
        out = eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 10})
        assert out.hit is True
        st = _parts_state(eng)
        picked = [k for k in ("a", "b") if st[k]["break_value"] > 0]
        assert len(picked) == 1

    def test_skill_def_merge_f09(self) -> None:
        """技能 def 的 break_power 随 F09 合并进 action（skills 路径消费）。"""
        eng = make(defs={"crush_strike": {"id": "crush_strike", "power": 100,
                                          "break_power": 30}}).start(
            PLAYER, _parts_enemy([dict(SHELL_PART, positions={"side": ["front"],
                                                              "height": ["ground"]},
                                       break_threshold=1000)]), random_seed=7)
        out = eng.do_action("player", {"type": "skill", "skill_id": "crush_strike"})
        assert out.hit is True
        # delta 含 30 固有（skill def merge）；raw 段伤害存在
        assert eng._snap["parts_state"]["shell"]["break_value"] >= 30.0


# =====================================================================================
# 5. on_break：knockdown 状态（damage_mult 叠加乘区）/ 事件通道
# =====================================================================================

_KNOCKDOWN_DEF = {"id": "knockdown", "name": "倒地", "category": "weak",
                  "max_stack": 1, "duration": {"turns": 1, "charges": 0},
                  "decay": "none", "damage_mult": 1.5}
_SHELL_DROP_DEF = {"id": "shell_drop", "name": "壳屑", "type": "mark",
                   "max_stack": 1, "duration": {"turns": 0, "charges": 0},
                   "decay": "none", "effects": []}


class TestOnBreak:
    def _eng(self, parts, **kw):
        defs = {"knockdown": _KNOCKDOWN_DEF, "shell_drop": _SHELL_DROP_DEF}
        params = DamageFormulaParams(battle_position=BattlePositionParams(
            broken_part_mult=1.5, break_sqrt_coef=1.0))
        return make(defs=defs, params=params, **kw).start(
            PLAYER, _parts_enemy(parts), random_seed=9)

    def test_break_applies_knockdown_status(self) -> None:
        """破位 → 默认挂 knockdown 状态（turns=on_break.knockdown=1）+ 事件。

        CTB 迁移（2026-09-10）：旧回合制断言「破位后 `status_state.enemy` 里仍有
        knockdown(turns=1)」在 CTB 下不再恒成立——`do_action` 收尾会自动把时间轴
        推进到下一个 ready（敌方 ready=250 早于玩家下一次 ready），**倒地状态在该
        怪物自己行动开始时被 `_start_actor_turn` 递减至 0 并清除**（R3/R4：控制
        按持有者行动次数递减，这正是「倒地一次」的正确语义）。

        故本用例分两段验证 CTB 生命周期：
          1. 破位事件与状态**施加**发生（`part_break` + `status_apply` 出现在本行动
             的 side_effects，证明确实挂了 knockdown）；
          2. 该状态确实在**怪物行动一拍后被消费**（终态为空 = 恰好持续一次敌方行动）。
        """
        part = dict(SHELL_PART, positions={"side": ["front"], "height": ["ground"]},
                    break_threshold=1)
        eng = self._eng([part])
        out = eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 5})
        fx = [str(e.get("type")) for e in (out.side_effects or ())]
        # ① 破位 + 状态施加（同一次行动内发生）
        ev = [e for e in out.side_effects if e.get("type") == "part_break"]
        assert ev, f"破位应产 part_break 事件，got {fx}"
        assert "status_apply" in fx, f"破位应施加倒地状态，got {fx}"
        # ② CTB：敌方 ready 早于玩家下一拍 → 其行动开始消费该 1 拍倒地
        acted = [r for r in (eng._snap.get("action_record") or [])
                 if r.get("actor") == "enemy"]
        assert acted, "CTB 下敌方应已行动（ready=250 早于玩家下一拍）"
        kd = [i for i in eng.battle_state()["status_state"]["enemy"]
              if i.get("status_id") == "knockdown"]
        assert kd == [], "倒地 turns=1 应在怪物行动开始后清零（持有者行动次数口径）"

    def test_knockdown_zero_skips_status(self) -> None:
        """on_break.knockdown=0（部位覆写）→ 破位不倒地。"""
        part = dict(SHELL_PART, id="head", name="头",
                    positions={"side": ["front"], "height": ["ground"]},
                    break_threshold=1, on_break={"knockdown": 0})
        eng = self._eng([part])
        eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 5})
        kd = [i for i in eng.battle_state()["status_state"]["enemy"]
              if i.get("status_id") == "knockdown"]
        assert kd == []

    def test_knockdown_stack_mult_on_broken_part(self) -> None:
        """倒地窗口打已破部位 = 常驻增伤 × 状态 damage_mult 叠加（1.5×1.5=2.25）。

        CTB 迁移（2026-09-10 Wave C · C-5）：段记录按 actor 过滤取（见
        `_player_segment_records` 说明——`do_action` 尾段自动推进 NPC 一拍）。
        """
        part = dict(SHELL_PART, positions={"side": ["front"], "height": ["ground"]},
                    break_threshold=1)
        eng = self._eng([part])
        out = eng.do_action("player", {
            "type": "skill", "mult": 1.0, "break_power": 1,
            "segments": [{"mult": 1.0}, {"mult": 1.0}]})
        assert out.hit is True
        recs = _player_segment_records(eng, 2)
        d1, d2 = int(recs[0]["damage"]["final"]), int(recs[1]["damage"]["final"])
        assert d2 > int(d1 * 2.0)          # 1.5×1.5=2.25 叠加（>2 即证明双乘区生效）
        assert d2 <= int(d1 * 2.25) + 2

    def test_break_marks_applied_to_enemy(self) -> None:
        """on_break.marks → mark_add 落敌方印记（素材掉落标记语义）。"""
        part = dict(SHELL_PART, positions={"side": ["front"], "height": ["ground"]},
                    break_threshold=1,
                    on_break={"knockdown": 0, "marks": ["shell_drop"], "effects": []})
        eng = self._eng([part])
        eng.do_action("player", {"type": "normal", "mult": 1.0, "break_power": 5})
        marks = eng.battle_state().get("marks_state") or {}
        enemy_marks = marks.get("enemy") or []
        hit = [m for m in enemy_marks
               if (m.get("mark_id") == "shell_drop" or m.get("name") == "shell_drop")]
        assert hit, f"enemy 印记应含 shell_drop：{enemy_marks}"


# =====================================================================================
# 6. 破位渲染行（Step 6 试点暴露缺口收口：part_break 事件 → 模板两形态）
# =====================================================================================


class TestPartBreakRender:
    """破位行（方位 v0.6 §三.3 渲染可见性）：part_break 事件（knockdown>0 轰然倒地 /
    knockdown=0 部位不倒地）→ battle_part_broken / battle_part_broken_no_knock。"""

    def _player_outcome(self, ev):
        from types import SimpleNamespace

        return SimpleNamespace(
            actor="player", action_type="skill", target="砾背龟", hit=True,
            side_effects=(ev,), final_damage=20, raw_damage=20, target_hp=180,
            player_max_hp=400, target_name="砾背龟", message="",
            intent_skill=None, special_action=None, player_guarding=False,
            defending=False, blocked=False, crit="low",
        )

    def test_break_with_knockdown_line(self) -> None:
        """knockdown>0 破位 → 「{part}被击碎！{name}轰然倒地」（怪名=target 回退）。"""
        from qbot_rpg.core.message_format.battle_render import _render_player_action

        ev = {"type": "part_break", "part": "gravel_shell", "part_name": "砾背壳",
              "knockdown": 2, "actor": "player", "target": "enemy"}
        lines = _render_player_action(self._player_outcome(ev))
        hit = [ln for ln in lines if "被击碎" in ln and "倒地" in ln]
        assert hit and "砾背壳" in hit[0] and "砾背龟" in hit[0]

    def test_break_without_knockdown_line(self) -> None:
        """knockdown=0 部位（如头）破位 → 不倒地文案模板。"""
        from qbot_rpg.core.message_format.battle_render import _render_player_action

        ev = {"type": "part_break", "part": "gravel_head", "part_name": "头",
              "knockdown": 0, "actor": "player", "target": "enemy"}
        lines = _render_player_action(self._player_outcome(ev))
        assert any("被击碎" in ln and "稳立" in ln for ln in lines)
        assert not any("倒地" in ln for ln in lines)

    def test_no_part_break_no_line(self) -> None:
        """无 part_break 事件 → 无破位行。"""
        from qbot_rpg.core.message_format.battle_render import _render_player_action

        lines = _render_player_action(self._player_outcome(
            {"type": "part_damage", "part": "gravel_shell", "part_name": "砾背壳"}))
        assert not any("被击碎" in ln for ln in lines)
