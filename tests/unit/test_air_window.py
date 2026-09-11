"""跃空窗口（行动条口径）验收测试——增补 v1 §四（2026-09-11 实装）。

口径（docs/veinborn_战斗规则增补_v1.md §四）：
  - 跃空维持 = `ctb.air_time`（缺省 2000 行动条；**隐性口径，玩家不可见**）；
  - 空中使用攻击/技能 → 窗口延长（技能 `air_extend` 正数优先，否则 `ctb.air_extend`
    缺省，默认 150）；每次行动只延长一次；
  - 到期自动落地（now >= expire → 清理姿态 + height=ground + `air_land` 事件，
    半开区间）；到期前保持；
  - 落地统一清理（`_clear_air_stances`）：到期 / air_policy=land / 闪反失败击落；
  - 无姿态而滞空 → 落地（R16 兜底语义保留）。

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG + 固定 seed）。
"""

from __future__ import annotations

from typing import Mapping

from qbot_rpg.core.battle import BattleEngine

# 对齐 tests/unit/test_air_policy.py 构造口径（玩家 spd=50 → 普攻恢复 200 行动条）
PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
         "mag": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30,
         "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}
SEQ = [0.5, 0.5, 0.5, 1.0]

#: 空中姿态状态 def（turns=-1 = 由行动条窗口/落地清理管理，不再按持有者行动次数递减；
#: 与内容包 veinborn statuses.json 同口径）。
_AIR_DEF = {"id": "sw_vault_air", "name": "腾空姿态", "max_stack": 1,
            "duration": {"turns": -1, "charges": 0}, "decay": "none", "effects": []}
#: 无 air_extend 的技能 def（延长走规则缺省）
_SKILL_DEF = {"id": "air_skill", "name": "空斩", "type": "active", "kind": "damage",
              "power": 100, "attack_type": "slash"}
#: 带 air_extend 的技能 def（大幅延长档）
_SKILL_EXT_DEF = {"id": "air_skill_big", "name": "大空斩", "type": "active",
                  "kind": "damage", "power": 100, "attack_type": "slash",
                  "air_extend": 500}


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


def _set_air(eng: BattleEngine, status_id: str = "sw_vault_air") -> None:
    """置「腾空中」：height=air + 空中姿态状态（与真实腾空技能产物一致）。"""
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"side": "front", "height": "ground"})
    ent["height"] = "air"
    rt = eng._new_runtime()
    rt.apply_status(status_id, "player", force=True)
    eng._absorb_runtime(rt)


def _set_height(eng: BattleEngine, height: str) -> None:
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"side": "front", "height": "ground"})
    ent["height"] = height


def _height(eng: BattleEngine) -> str:
    cp = eng._snap.get("combat_position") or {}
    return str((cp.get("player") or {}).get("height") or "ground")


def _expire_of(eng: BattleEngine, status_id: str = "sw_vault_air"):
    for inst in eng._snap.get("status_state", {}).get("player", []) or []:
        if isinstance(inst, dict) and inst.get("status_id") == status_id:
            return inst.get("air_expire_at")
    return None


def _stance_ids(eng: BattleEngine):
    out = []
    for inst in eng._snap.get("status_state", {}).get("player", []) or []:
        if isinstance(inst, dict):
            out.append(str(inst.get("status_id")))
    return out


def _air_land_events(outcomes) -> list:
    evs = []
    for o in outcomes:
        for e in (getattr(o, "side_effects", ()) or ()):
            if isinstance(e, Mapping) and e.get("type") == "air_land":
                evs.append(e)
    return evs


def _start_air(defs=None, config=None) -> BattleEngine:
    merged = {"sw_vault_air": dict(_AIR_DEF), **dict(defs or {})}
    eng = make(defs=merged).start(PLAYER, ENEMY, random_seed=11, config=config)
    _set_air(eng)
    return eng


# =====================================================================================
# 1. 窗口初始化（入空时刻 + air_time）
# =====================================================================================


class TestAirWindowInit:
    def test_init_on_first_action_end(self) -> None:
        """入空后首个行动收尾：窗口初始化 = 行动起始时刻 + air_time（缺省 2000）。

        玩家 spd=50 → 首拍 t=200；普攻延长 +150 → 200 + 2000 + 150 = 2350。
        """
        eng = _start_air()
        assert eng.battle_time == 200.0
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 2350.0
        assert _height(eng) == "air"

    def test_init_not_reset_by_later_actions(self) -> None:
        """窗口一经初始化不再重置：只受延长影响（第二次普攻 +150 → 2500）。"""
        eng = _start_air()
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 2350.0
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 2500.0

    def test_stance_with_turns_minus_one_survives_multiple_actions(self) -> None:
        """turns=-1 空中姿态不随持有者行动次数消失（窗口由行动条管理）。"""
        eng = _start_air()
        for _ in range(4):
            eng.do_action("player", {"type": "guard"})
        assert "sw_vault_air" in _stance_ids(eng)
        assert _height(eng) == "air"


# =====================================================================================
# 2. 延长（使用攻击/技能）
# =====================================================================================


class TestAirExtend:
    def test_normal_extends_by_default(self) -> None:
        """普攻 → +ctb.air_extend（缺省 150）。"""
        eng = _start_air()
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 2350.0

    def test_skill_without_extend_uses_default(self) -> None:
        """技能未给 air_extend → 规则缺省 150。"""
        eng = _start_air(defs={"air_skill": dict(_SKILL_DEF)})
        eng.do_action("player", {"type": "skill", "skill_id": "air_skill"})
        assert _expire_of(eng) == 2350.0

    def test_skill_with_extend_uses_skill_value(self) -> None:
        """技能 air_extend 正数 → 用技能值（大幅延长档）。"""
        eng = _start_air(defs={"air_skill_big": dict(_SKILL_EXT_DEF)})
        eng.do_action("player", {"type": "skill", "skill_id": "air_skill_big"})
        assert _expire_of(eng) == 2700.0

    def test_guard_does_not_extend(self) -> None:
        """防御不是攻击/技能 → 不延长（窗口保持 init 值）。"""
        eng = _start_air()
        eng.do_action("player", {"type": "guard"})
        assert _expire_of(eng) == 2200.0

    def test_extend_once_per_action(self) -> None:
        """每次行动只延长一次（多级收尾重入幂等——连续两次普攻 = +150 ×2，非 ×4）。"""
        eng = _start_air()
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 2500.0


# =====================================================================================
# 3. 到期自动落地（半开区间 + 清理 + 事件）
# =====================================================================================


class TestAirExpiry:
    def test_expire_lands_clears_and_emits(self) -> None:
        """now >= expire → 自动落地：清理姿态 + height=ground + air_land 事件（恰好一次）。"""
        eng = _start_air()
        eng.do_action("player", {"type": "normal", "mult": 1.0})   # expire 2350
        assert eng._ctb is not None
        eng._ctb._time = 2350.0
        eng._sync_counts()
        out = eng.do_action("player", {"type": "guard"})
        assert _height(eng) == "ground"
        assert "sw_vault_air" not in _stance_ids(eng)
        evs = _air_land_events([out] + list(eng._npc_outcomes))
        assert len(evs) == 1 and evs[0].get("actor") == "player"

    def test_not_expired_stays_air(self) -> None:
        """now < expire（半开区间）→ 保持空中。"""
        eng = _start_air()
        eng.do_action("player", {"type": "normal", "mult": 1.0})   # expire 2350
        assert eng._ctb is not None
        eng._ctb._time = 2349.9
        eng._sync_counts()
        eng.do_action("player", {"type": "guard"})
        assert _height(eng) == "air"

    def test_expired_event_not_repeated(self) -> None:
        """air_land 事件取走即清：后续行动不再重复播报。"""
        eng = _start_air()
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert eng._ctb is not None
        eng._ctb._time = 2350.0
        eng._sync_counts()
        eng.do_action("player", {"type": "guard"})
        eng._npc_outcomes = []
        out2 = eng.do_action("player", {"type": "guard"})
        assert _air_land_events([out2] + list(eng._npc_outcomes)) == []

    def test_air_policy_land_clears_stances(self) -> None:
        """air_policy=land 落地 → 空中姿态随落地清理（统一清理点）。"""
        eng = _start_air()
        out = eng.do_action("player", {"type": "normal", "mult": 1.0,
                                       "air_policy": "land"})
        assert _height(eng) == "ground"
        assert "sw_vault_air" not in _stance_ids(eng)
        assert len(_air_land_events([out])) == 1

    def test_no_stance_but_air_lands(self) -> None:
        """无姿态而滞空 → 落地（R16 兜底语义保留）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        _set_height(eng, "air")
        out = eng.do_action("player", {"type": "guard"})
        assert _height(eng) == "ground"
        assert len(_air_land_events([out] + list(eng._npc_outcomes))) == 1


# =====================================================================================
# 4. 配置化（ctb.air_time / ctb.air_extend；隐性口径可调）
# =====================================================================================


# =====================================================================================
# 5. 内容审计（增补 v1 §四「关联状态同步审计」守卫）
# =====================================================================================


class TestAirStanceContentAudit:
    def test_every_air_vault_applies_stance(self) -> None:
        """所有跃空技（reposition height=air）必须挂空中姿态——否则行动收尾无姿态
        → 被 R16 兜底静默落地（rb/vc/po 三处 2026-09-11 审计修复的回归守卫）。"""
        import json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from qbot_rpg.core.battle import _AIR_STATUS_IDS  # noqa: PLC0415

        sk = json.loads(
            Path("content/veinborn/skills.json").read_text(encoding="utf-8"))
        missing = []
        for s in sk:
            effs = [e for e in (s.get("effects") or []) if isinstance(e, Mapping)]
            to_air = any(e.get("type") == "reposition" and e.get("height") == "air"
                         for e in effs)
            if not to_air:
                continue
            stances = [str(e.get("status_id")) for e in effs
                       if e.get("type") == "status_apply"]
            if not any(sid in _AIR_STATUS_IDS for sid in stances):
                missing.append(str(s.get("id")))
        assert missing == [], f"这些跃空技缺空中姿态挂载：{missing}"


class TestAirWindowConfig:
    def test_air_time_override(self) -> None:
        """air_time=3000 → 窗口 = 200 + 3000 + 150（普攻延长仍走缺省）。"""
        eng = _start_air(config={"ctb": {"air_time": 3000}})
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 3350.0

    def test_air_extend_override(self) -> None:
        """air_extend=300 → 延长用覆盖值。"""
        eng = _start_air(config={"ctb": {"air_extend": 300}})
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert _expire_of(eng) == 2500.0

    def test_settings_segment_pipeline(self) -> None:
        """settings["ctb"] 段（resolve_ctb_settings）→ 引擎可调（管道接通验收）。"""
        from qbot_rpg.core.ctb_config import resolve_ctb_settings  # noqa: PLC0415

        seg = resolve_ctb_settings({"ctb": {"air_time": 4000, "air_extend": 0}})
        assert seg["air_time"] == 4000
        eng = _start_air(config={"ctb": seg})
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        # air_extend 段显式 0 → 读 0 → 不延长；窗口 = 200 + 4000（air_time 覆盖生效）
        assert _expire_of(eng) == 4200.0
