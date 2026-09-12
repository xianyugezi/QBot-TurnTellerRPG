"""对空闭环验收测试——A-1 怪物对空覆盖 + D-16 被击落（2026-09-11 批③实装）。

口径（docs/veinborn_战斗规则增补_怪猎对照研究_20260911.md §一）：
  - **A-1 对空覆盖（缺口级）**：怪物招式表 ≥20% 可触达空中（`position_rule.height`
    含 "air"）——不补则跃空=零风险安全区（无风险=无决策=没有玩法）；攻击类对空行动
    带「对空」标签（设计口径标注）；
  - **D-16 被击落**：怪物攻击命中空中玩家（到达伤害收尾=方位检查已过）——
      柔和档（缺省）：跃空窗口缩短 `ctb.air_hit_shrink`（缺省 400 行动条；隐性口径）；
      击落档（`action.air_drop == "knockdown"` 对空必杀）：立即落地 + 倒地 + 行动条
      硬直（`ctb.air_drop_delay` 缺省 400，经 `delay_actor`）+「将你从空中击落」行；
  - 护栏：非攻击（mult≤0，召唤/辅助防御） / 地面玩家 / 防反成功（完全免伤早退）——
    均不吃对空后果。
  - （批⑨ 补充：击落档在「当次窗口仍有效」时由受身自动取消——本文件完整击落链测试
    以过期窗口驱动；受身专项见 test_air_recover.py。）

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG 固定序列）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qbot_rpg.content.loader import build_pack
from qbot_rpg.content.skill_action_models import (
    ACTION_FIELD_REGISTRY,
    AIR_DROP_VALUES,
    validate_actions,
)
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.message_format.battle_render import _render_enemy_action
from qbot_rpg.core.monster_ai import MonsterAI


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i % len(self.seq)]
        self.i += 1
        return v


_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 10, "mag": 10,
}


def _pack():
    """加载 veinborn 包并构建 defs/combo 引擎（对齐 test_counter_parry_dodge 口径）。"""
    pack, _ = build_pack(Path("content/veinborn"))
    raw = pack.registry.modules_raw
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    ce = ComboEngine(
        defs={**all_defs, **chains},
        resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
    )
    return raw, all_defs, ce


def _enemy(raw, eid, *, spd=None):
    et = next(e for e in raw["enemies"] if e["id"] == eid)
    st = et.get("stats") or {}
    _spd = int(st.get("agi", 10) or 10) if spd is None else int(spd)
    return et, {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": int(st.get("str", 10)), "dfn": int(st.get("con", 10)),
        "mag": 0, "spd": _spd, "foc": 0, "lck": 0,
        "con": int(st.get("con", 10)), "agi": 0, "name": et["name"],
    }


def _fresh(raw, all_defs, ce, *, spd=1, config=None):
    """构造引擎（config 经 start 注入——ctb 段随调度器 rule 生效，勿转后改写 _config）。"""
    et, mob = _enemy(raw, "ridge_cub", spd=spd)
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7, config=config)
    eng._enemy_ai = ai
    return eng


def _set_air(eng: BattleEngine, status_id: str = "sw_vault_air", expire=None) -> None:
    """玩家置空中 + 空中姿态（可选直写窗口 air_expire_at，精确控制口径）。"""
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"side": "front", "height": "ground"})
    ent["height"] = "air"
    rt = eng._new_runtime()
    rt.apply_status(status_id, "player", force=True)
    eng._absorb_runtime(rt)
    if expire is not None:
        for inst in eng._snap.get("status_state", {}).get("player", []) or []:
            if isinstance(inst, dict) and inst.get("status_id") == status_id:
                inst["air_expire_at"] = float(expire)


def _height(eng: BattleEngine) -> str:
    cp = eng._snap.get("combat_position") or {}
    return str((cp.get("player") or {}).get("height") or "ground")


def _status_ids(eng: BattleEngine) -> list:
    _insts = eng._snap.get("status_state", {}).get("player", []) or []
    return [str(i.get("status_id")) for i in _insts if isinstance(i, dict)]


def _expire_of(eng: BattleEngine, status_id: str = "sw_vault_air"):
    for inst in eng._snap.get("status_state", {}).get("player", []) or []:
        if isinstance(inst, dict) and inst.get("status_id") == status_id:
            return inst.get("air_expire_at")
    return None


def _fx_types(outcome) -> list:
    return [str(x.get("type")) for x in (getattr(outcome, "side_effects", ()) or ())]


def _player_ready(eng: BattleEngine) -> float:
    view = eng._ctb.get_actor("player") if eng._ctb is not None else None
    assert view is not None
    return float(view.next_ready)


# =====================================================================================
# 1. 内容守卫：对空覆盖率 + 标签一致性 + 击落清单（A-1）
# =====================================================================================


class TestContentAirCoverage:
    def _scan(self):
        raw, _, _ = _pack()
        acts = {a["id"]: a for a in raw["action"]}
        out = []
        for e in raw["enemies"]:
            seen = []
            for ph in e.get("phases", []):
                for a in ph.get("actions", []):
                    if a.get("action") not in seen:
                        seen.append(a.get("action"))
            for a in e.get("actions", []):
                if a.get("action") not in seen:
                    seen.append(a.get("action"))
            dmg = [x for x in seen if x in acts and float(acts[x].get("power", 0) or 0) > 0]
            air = [x for x in dmg
                   if "air" in (acts[x].get("position_rule", {}).get("height") or [])]
            out.append((e["id"], dmg, air))
        return acts, out

    def test_monster_air_coverage_ratio(self) -> None:
        """每只攻击怪：≥1 对空手段且比例 ≥20%（缺口级——跃空风险闭环先决）。"""
        acts, rows = self._scan()
        for mid, dmg, air in rows:
            if not dmg:
                continue  # 木桩/无攻击怪
            assert air, f"{mid} 无对空手段（缺口级：跃空将成零风险安全区）"
            ratio = len(air) / len(dmg)
            assert ratio >= 0.2, f"{mid} 对空覆盖 {len(air)}/{len(dmg)}={ratio:.0%} < 20%"

    def test_air_moves_carry_tag(self) -> None:
        """攻击类对空行动带「对空」标签（设计口径标注；height 与标签一致性守卫）。"""
        acts, _ = self._scan()
        for aid, a in acts.items():
            if float(a.get("power", 0) or 0) <= 0:
                continue
            has_air = "air" in (a.get("position_rule", {}).get("height") or [])
            has_tag = "对空" in (a.get("tags") or [])
            assert has_air == has_tag, (
                f"{aid} 对空口径不一致：height含air={has_air} 标签对空={has_tag}")

    def test_knockdown_moves_contract(self) -> None:
        """对空必杀（air_drop=knockdown）清单 = 策划口径三招，且均已可对空。"""
        acts, _ = self._scan()
        kd = sorted(aid for aid, a in acts.items() if a.get("air_drop") == "knockdown")
        assert kd == ["sa_quake_stomp", "sb_lethal_pounce", "zb_ambush"], (
            f"击落档清单变化：{kd}（设计口径：震落/扑杀/拖拽三招）")
        for aid in kd:
            a = acts[aid]
            assert "air" in (a.get("position_rule", {}).get("height") or []), (
                f"{aid} 标为对空必杀但不可对空")


# =====================================================================================
# 2. 引擎：柔和档（窗口缩短，缺省）
# =====================================================================================


class TestAirShrink:
    def test_air_hit_shrinks_window_by_default(self) -> None:
        """怪对空命中空中玩家 → 窗口 -400（缺省），仍滞空、伤害照常。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        _set_air(eng, expire=999999.0)
        hp0 = int(eng._snap["player"]["hp"])
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "bb_cub_bite"})
        assert out.hit is True
        assert _expire_of(eng) == 999999.0 - 400.0
        assert _height(eng) == "air"
        assert int(eng._snap["player"]["hp"]) < hp0

    def test_shrink_below_now_lands_at_action_end(self) -> None:
        """窗口缩短至当前时刻以下 → 行动收尾自动落地（柔和档可致落地，无硬直）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        _set_air(eng, expire=100.0)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "bb_cub_bite"})
        assert _height(eng) == "ground"
        assert "sw_vault_air" not in _status_ids(eng)
        assert "air_land" in _fx_types(out)
        assert "air_drop" not in _fx_types(out)

    def test_shrink_configurable(self) -> None:
        """ctb.air_hit_shrink 可调（隐性口径，配置驱动）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce, config={"ctb": {"air_hit_shrink": 700}})
        _set_air(eng, expire=999999.0)
        eng.do_action("enemy", {"type": "skill", "skill_id": "bb_cub_bite"})
        assert _expire_of(eng) == 999999.0 - 700.0

    def test_ground_only_move_miss_keeps_window(self) -> None:
        """地面技（bb_slam 仍 ground-only）打空中=未命中 → 窗口不动（缺口修复边界）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        _set_air(eng, expire=999999.0)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "bb_slam"})
        assert "position_miss" in _fx_types(out)
        assert _expire_of(eng) == 999999.0

    def test_no_rule_normal_no_shrink(self) -> None:
        """无 position_rule 的兜底普攻（旧「全量」口径）不吃对空后果（非对空招式）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        _set_air(eng, expire=999999.0)
        out = eng.do_action("enemy", {"type": "normal", "mult": 1.0})
        assert out.hit is True
        assert _expire_of(eng) == 999999.0

    def test_non_attack_does_not_shrink(self) -> None:
        """非攻击行动（mult=0，如防御/召唤）命中空中玩家 → 不吃对空后果。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        _set_air(eng, expire=999999.0)
        eng.do_action("enemy", {"type": "skill", "skill_id": "gj_armor"})
        assert _expire_of(eng) == 999999.0


# =====================================================================================
# 3. 引擎：击落档（对空必杀）
# =====================================================================================


class TestAirKnockdown:
    def test_knockdown_full_chain(self) -> None:
        """zb_ambush（潜袭拖拽）命中空中玩家：落地 + 姿态清理 + 倒地 + 硬直 + 事件。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})   # 归一化起步（时间轴推进一拍）
        _set_air(eng, expire=1.0)   # 窗口已过期（受身不适用）→ 验证完整击落链
        before = _player_ready(eng)
        now = float(eng.battle_time)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        fx = _fx_types(out)
        assert "air_drop" in fx and "air_land" not in fx
        assert _height(eng) == "ground"
        assert "sw_vault_air" not in _status_ids(eng)
        assert "knockdown" in _status_ids(eng)
        _kd = [i for i in eng._snap["status_state"]["player"]
               if isinstance(i, dict) and i.get("status_id") == "knockdown"]
        # air_drop_turns 缺省 3；本次行动收尾（tick_turn_end 双端扣减）已扣 1 → 观测值 2
        # （剩 2 次收尾扣减额度：撑过「玩家下一拍 + 怪下一次出手」的追击窗）
        assert int(_kd[0].get("turns", 0)) == 2
        expected = max(before, now) + 400.0   # air_drop_delay 缺省 400
        assert _player_ready(eng) == pytest.approx(expected)
        notes = [n for n in eng._snap.get("battle_notes", []) if isinstance(n, dict)
                 and n.get("type") == "air_drop"]
        assert len(notes) == 1

    def test_knockdown_delay_configurable(self) -> None:
        """ctb.air_drop_delay 可调。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce, config={"ctb": {"air_drop_delay": 900}})
        _set_air(eng, expire=1.0)   # 窗口已过期（受身不适用）
        before = _player_ready(eng)
        now = float(eng.battle_time)
        eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        assert _player_ready(eng) == pytest.approx(max(before, now) + 900.0)

    def test_knockdown_turns_configurable(self) -> None:
        """air_drop_turns 可调（倒地追击窗覆写值）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce, config={"air_drop_turns": 5})
        _set_air(eng, expire=1.0)   # 窗口已过期（受身不适用）
        eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        _kd = [i for i in eng._snap["status_state"]["player"]
               if isinstance(i, dict) and i.get("status_id") == "knockdown"]
        assert _kd and int(_kd[0].get("turns", 0)) == 4   # 5 - 本次收尾 1 次扣减

    def test_knockdown_only_vs_air(self) -> None:
        """地面玩家吃同一招：正常命中，无击落/无倒地/无硬直（对空必杀仅对空生效）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        before = _player_ready(eng)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        assert "air_drop" not in _fx_types(out)
        assert "knockdown" not in _status_ids(eng)
        assert _player_ready(eng) == before

    def test_parry_success_immune_to_knockdown(self) -> None:
        """防反成功（完全免伤）早退 → 不吃击落：保持空中、无倒地、无硬直。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        _set_air(eng, expire=999999.0)
        eng._snap["counter_stance"] = {
            "type": "parry", "skill": "sw_guard_counter",
            "cast_time": float(eng.battle_time), "action_time": 400.0,
        }
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        fx = _fx_types(out)
        assert "parry" in fx and "parry_counter" in fx
        assert "air_drop" not in fx
        assert _height(eng) == "air"
        assert "knockdown" not in _status_ids(eng)
        assert "sw_vault_air" in _status_ids(eng)   # 击落未发生：姿态与滞空保持


# =====================================================================================
# 4. 渲染 + schema
# =====================================================================================


class TestAirDropRender:
    def _enemy_outcome(self, events):
        return SimpleNamespace(
            actor="enemy", action_type="normal", target="P", hit=True,
            side_effects=events, final_damage=50, raw_damage=50, target_hp=450,
            player_max_hp=500, target_name="P", attacker_name="泽骨鳄",
            message="", intent_skill=None, special_action=None,
            player_guarding=False, defending=False, blocked=False, crit="low",
        )

    def test_air_drop_line(self) -> None:
        """air_drop 事件 → 怪行动行集含「将你从空中击落」（怪名映射）。"""
        ev = ({"type": "air_drop", "actor": "player", "attacker": "enemy"},)
        line = _render_enemy_action(self._enemy_outcome(ev))
        assert line is not None and "将你从空中击落" in line
        assert "泽骨鳄" in line

    def test_no_event_no_line(self) -> None:
        """无 air_drop 事件 → 不渲染击落行。"""
        line = _render_enemy_action(self._enemy_outcome(()))
        assert line is None or "将你从空中击落" not in line


class TestAirDropSchema:
    def test_registered(self) -> None:
        """air_drop 进入行动库字段注册表 + 枚举常量。"""
        assert AIR_DROP_VALUES == ("knockdown",)
        assert "air_drop" in ACTION_FIELD_REGISTRY

    def test_valid_passes(self) -> None:
        report: dict = {"errors": [], "warnings": []}
        validate_actions({"action": [
            {"id": "a1", "name": "击落技", "air_drop": "knockdown"},
            {"id": "a2", "name": "缺省柔和"},
        ]}, report)
        assert report["errors"] == []

    def test_invalid_red_flagged(self) -> None:
        report: dict = {"errors": [], "warnings": []}
        validate_actions({"action": [
            {"id": "b1", "name": "类型错", "air_drop": 3},
            {"id": "b2", "name": "枚举外", "air_drop": "launch"},
        ]}, report)
        rules = {e["rule"] for e in report["errors"]}
        assert {"air_drop_type", "air_drop_enum"} <= rules
