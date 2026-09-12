"""跃空续航「翔虫」+ 受身验收测试——批⑨（2026-09-12 实装）。

口径（docs/veinborn_战斗规则增补_v1.md §四；怪猎对照研究 D-15/D-16）：
  - 翔虫独立轴（2 格，行动条自然回复）：**起跳耗 1 格**（不足 → 被拒零时间成本，
    R-6）；**大幅延长耗 1 格**（专门空中技能 `air_extend`；不足 → 回落缺省小幅、
    不拒绝）；**受身耗 1 格**；
  - 受身：被击落时「窗口仍有效 + 翔虫≥1 + 非『不可受身』」→ 自动耗 1 格取消
    倒地与硬直（`air_recover` 事件，「借翔虫之力翻身」行）；
  - 隐性口径：行动条数字玩家不可见（文案零原始数值）；翔虫格数可配
    （settings["ctb"]["air_wirebug_*"]）；
  - 未注册翔虫轴的内容包（demo/legal 等）→ 零操作降级（跃空免费、无受身）。

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG 固定序列）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.message_format.battle_render import (
    _render_air_recover_lines,
    _render_enemy_action,
)
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

#: 跃空续航「翔虫」资源轴注册段（与内容包 stats.json 同口径；测试注入用）
_WIREBUG_REG = {
    "wirebug": {
        "name": "翔虫", "type": "rage", "base": 2, "max": 2,
        "reset": "battle", "display": "status_line",
    },
}

_VEINBORN = Path("content/veinborn")

#: 测试用起跳技（与内容策同形态：reposition height=air + 姿态授予；无冷却/限次）
_LEAP_DEF = {
    "id": "wi_leap", "name": "跃空·测", "type": "active", "kind": "utility",
    "power": 0, "mp_cost": 0, "cooldown": 0,
    "effects": [
        {"type": "reposition", "target": "self", "height": "air"},
        {"type": "status_apply", "target": "self", "status_id": "rb_vault_air"},
    ],
}
#: 测试用大幅延长技能（专空气技：技能显式 air_extend）
_BIG_DEF = {
    "id": "wi_air_big", "name": "空斩·大", "type": "active", "kind": "damage",
    "power": 100, "attack_type": "slash", "mp_cost": 0, "cooldown": 0,
    "air_extend": 500,
}
#: 普通空中技能（无 air_extend → 小幅免费）
_SMALL_DEF = {
    "id": "wi_air_s", "name": "空斩·小", "type": "active", "kind": "damage",
    "power": 100, "attack_type": "slash", "mp_cost": 0, "cooldown": 0,
}


def _pack():
    """加载 veinborn 包并构建 defs/combo 引擎（对齐 test_anti_air 口径）。"""
    pack, _ = build_pack(_VEINBORN)
    raw = pack.registry.modules_raw
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    return raw, all_defs, chains


def _pack_ext():
    """veinborn 包 + 三个测试技能 def（同引擎装配口径重建 combo 引擎）。"""
    raw, all_defs, chains = _pack()
    defs = dict(all_defs)
    defs.update({"wi_leap": dict(_LEAP_DEF), "wi_air_big": dict(_BIG_DEF),
                 "wi_air_s": dict(_SMALL_DEF)})
    ce = ComboEngine(
        defs={**defs, **chains},
        resolver=lambda i, k: chains.get(i) if k == "skill_chain" else defs.get(i),
    )
    return raw, defs, ce


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


def _fresh(raw, all_defs, ce, *, spd=1, config=None, wirebug=True):
    """构造引擎；wirebug=True → 注入翔虫注册表（start 前——battle_start_init 播种 base）。"""
    et, mob = _enemy(raw, "ridge_cub", spd=spd)
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    if wirebug:
        eng._resource_registry = dict(_WIREBUG_REG)  # type: ignore[attr-defined]
    eng.start(dict(_PLAYER), mob, random_seed=7, config=config)
    eng._enemy_ai = ai
    return eng


def _wb(eng: BattleEngine) -> int:
    seg = (eng._snap.get("resource_state") or {}).get("player") or {}
    return int(seg.get("wirebug", -1))


def _set_wb(eng: BattleEngine, n: int) -> None:
    rs = eng._snap.setdefault("resource_state", {})
    seg = rs.setdefault("player", {})
    seg["wirebug"] = int(n)


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


def _regen_node(eng: BattleEngine):
    node = eng._snap.get("air_wirebug")
    return node if isinstance(node, dict) else {}


# =====================================================================================
# 1. 配置与内容守卫
# =====================================================================================


class TestWirebugConfig:
    def test_rule_defaults(self) -> None:
        """CtbRuleConfig 缺省：2 格 / 回复 1500 / 起跳·延长·受身各 1 格。"""
        from qbot_rpg.core.ctb_rules import CtbRuleConfig

        c = CtbRuleConfig()
        assert c.air_wirebug_max == 2.0
        assert c.air_wirebug_regen == 1500.0
        assert c.air_wirebug_leap_cost == 1.0
        assert c.air_wirebug_extend_cost == 1.0
        assert c.air_wirebug_recover_cost == 1.0

    def test_settings_override_pipe(self) -> None:
        """settings["ctb"] 段可调（管道接通口径，对齐 air_time 先例）。"""
        from qbot_rpg.core.ctb_rules import resolve_rule_config

        c = resolve_rule_config({"ctb": {"air_wirebug_max": 3, "air_wirebug_regen": 800}})
        assert c.air_wirebug_max == 3.0
        assert c.air_wirebug_regen == 800.0

    def test_content_axis_registered(self) -> None:
        """veinborn stats.json 注册翔虫轴（2 格满格开局、战斗级重置、状态行可见）。"""
        st = json.loads((_VEINBORN / "stats.json").read_text(encoding="utf-8"))
        ax = st.get("wirebug") or {}
        assert ax.get("name") == "翔虫"
        assert int(ax.get("base", -1)) == 2
        assert int(ax.get("max", -1)) == 2
        assert ax.get("reset") == "battle"
        assert ax.get("display") == "status_line"

    def test_recover_exception_tag_contract(self) -> None:
        """击落三招中恰「致命扑杀」带不可受身（例外口径；其余可受身）。"""
        raw, _, _ = _pack()
        acts = {a["id"]: a for a in raw["action"]}
        kd = [aid for aid, a in acts.items() if a.get("air_drop") == "knockdown"]
        assert sorted(kd) == ["sa_quake_stomp", "sb_lethal_pounce", "zb_ambush"]
        tagged = [aid for aid in kd if "不可受身" in (acts[aid].get("tags") or [])]
        assert tagged == ["sb_lethal_pounce"]


# =====================================================================================
# 2. 起跳耗格（含不足被拒零时间成本）
# =====================================================================================


class TestLeapCost:
    def test_leap_consumes_one(self) -> None:
        """起跳（地面 → 空中）耗 1 格；窗口初始化、回复计时起表。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        assert _wb(eng) == 2
        out = eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert out.ok is True
        assert _wb(eng) == 1
        assert _height(eng) == "air"
        assert "rb_vault_air" in _status_ids(eng)
        assert _expire_of(eng, "rb_vault_air") is not None  # 窗口已初始化
        node = _regen_node(eng)
        assert node.get("next_regen_at") is not None  # 回复计时起表

    def test_real_content_leap_consumes(self) -> None:
        """真实内容跃空技（rb_vault）同口径耗 1 格（内容集成守卫）。"""
        raw, all_defs, chains = _pack()
        ce = ComboEngine(
            defs={**all_defs, **chains},
            resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
        )
        eng = _fresh(raw, all_defs, ce)
        out = eng.do_action("player", {"type": "skill", "skill_id": "rb_vault"})
        assert out.ok is True
        assert _wb(eng) == 1
        assert _height(eng) == "air"

    def test_refuse_when_no_charge(self) -> None:
        """翔虫 0 → 起跳被拒（零时间成本）：不耗行动条、不落地变化、文案零数值。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "guard"})   # 归一化起步
        _set_wb(eng, 0)
        t0 = float(eng.battle_time)
        r0 = _player_ready(eng)
        out = eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert out.ok is False
        assert "翔虫" in out.message and "被拒" in out.message
        assert not re.search(r"\d", out.message), f"被拒文案含数字：{out.message}"
        assert float(eng.battle_time) == pytest.approx(t0)   # 零时间成本
        assert _player_ready(eng) == pytest.approx(r0)       # 行动条未推进
        assert _height(eng) == "ground"                      # 未入空
        assert "rb_vault_air" not in _status_ids(eng)
        assert _wb(eng) == 0

    def test_no_cost_when_already_airborne(self) -> None:
        """已空中再跃：不重复计费（窗口维持零消耗；起跳仅对「地面 → 空中」）。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert _wb(eng) == 1
        out2 = eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert out2.ok is True
        assert _wb(eng) == 1
        assert _height(eng) == "air"

    def test_non_leap_skill_free(self) -> None:
        """非起跳技（无入空 effects）不耗格。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        out = eng.do_action("player", {"type": "skill", "skill_id": "wi_air_s"})
        assert out.ok is True
        assert _wb(eng) == 2

    def test_no_registry_degrades_free(self) -> None:
        """未注册翔虫（内容包未启用）→ 零操作降级：跃空照常、无拒绝。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce, wirebug=False)
        out = eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert out.ok is True
        assert _height(eng) == "air"


# =====================================================================================
# 3. 大幅延长耗格（不足回落小幅，不拒绝）
# =====================================================================================


class TestExtendCost:
    def test_big_extend_pays(self) -> None:
        """大幅延长（技能 air_extend）耗 1 格；窗口 +500。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=10000.0)
        out = eng.do_action("player", {"type": "skill", "skill_id": "wi_air_big"})
        assert out.ok is True
        assert _wb(eng) == 1
        assert _expire_of(eng) == pytest.approx(10000.0 + 500.0)

    def test_big_extend_falls_back_when_no_charge(self) -> None:
        """翔虫 0 → 大幅延长回落缺省小幅（+150），行动不被拒。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=10000.0)
        _set_wb(eng, 0)
        out = eng.do_action("player", {"type": "skill", "skill_id": "wi_air_big"})
        assert out.ok is True
        assert _expire_of(eng) == pytest.approx(10000.0 + 150.0)
        assert _wb(eng) == 0

    def test_small_extend_free(self) -> None:
        """普通空中技能（无 air_extend）小幅延长免费。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=10000.0)
        eng.do_action("player", {"type": "skill", "skill_id": "wi_air_s"})
        assert _wb(eng) == 2
        assert _expire_of(eng) == pytest.approx(10000.0 + 150.0)

    def test_extend_cost_configurable(self) -> None:
        """air_wirebug_extend_cost 可调（2 格一扣）。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce, config={"ctb": {"air_wirebug_extend_cost": 2}})
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=10000.0)
        eng.do_action("player", {"type": "skill", "skill_id": "wi_air_big"})
        assert _wb(eng) == 0
        assert _expire_of(eng) == pytest.approx(10000.0 + 500.0)


# =====================================================================================
# 4. 行动条自然回复
# =====================================================================================


class TestRegen:
    def test_tick_regens_after_interval(self) -> None:
        """到点回复 1 格（行动条口径）；满格后清计时。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert _wb(eng) == 1
        # 强制到点（等效行动条已流逝一个间隔）
        node = eng._snap.setdefault("air_wirebug", {})
        node["next_regen_at"] = float(eng.battle_time) - 1.0
        eng._tick_air_wirebug()
        assert _wb(eng) == 2
        assert node.get("next_regen_at") is None

    def test_regen_via_action_settlement(self) -> None:
        """行动收尾自动回复（无需手动 tick：guard 一拍后满格）。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce)
        eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        node = eng._snap.setdefault("air_wirebug", {})
        node["next_regen_at"] = float(eng.battle_time) - 1.0
        eng.do_action("player", {"type": "guard"})
        assert _wb(eng) == 2

    def test_regen_zero_disables(self) -> None:
        """air_wirebug_regen=0 → 不回复、不起表。"""
        raw, defs, ce = _pack_ext()
        eng = _fresh(raw, defs, ce, config={"ctb": {"air_wirebug_regen": 0}})
        eng.do_action("player", {"type": "skill", "skill_id": "wi_leap"})
        assert _wb(eng) == 1
        assert _regen_node(eng).get("next_regen_at") is None
        eng.do_action("player", {"type": "guard"})
        assert _wb(eng) == 1


# =====================================================================================
# 5. 受身（被击落时自动取消倒地）
# =====================================================================================


class TestAirRecover:
    def test_recover_succeeds(self) -> None:
        """窗口有效 + 翔虫≥1 + 非不可受身 → 自动耗 1 格：无倒地、无硬直、稳落。"""
        raw, all_defs, chains = _pack()
        ce = ComboEngine(
            defs={**all_defs, **chains},
            resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
        )
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        before = _player_ready(eng)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        fx = _fx_types(out)
        assert "air_recover" in fx and "air_drop" not in fx
        assert _height(eng) == "ground"
        assert "knockdown" not in _status_ids(eng)
        assert "sw_vault_air" not in _status_ids(eng)   # 落地清理照常
        assert _wb(eng) == 1                            # 受身耗 1 格
        assert _player_ready(eng) == pytest.approx(before)  # 无硬直
        notes = [n for n in eng._snap.get("battle_notes", []) if isinstance(n, dict)
                 and n.get("type") == "air_recover"]
        assert len(notes) == 1

    def test_recover_needs_charge(self) -> None:
        """翔虫 0 → 无受身：击落生效（倒地 + 硬直）。"""
        raw, all_defs, chains = _pack()
        ce = ComboEngine(
            defs={**all_defs, **chains},
            resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
        )
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        _set_wb(eng, 0)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        fx = _fx_types(out)
        assert "air_drop" in fx and "air_recover" not in fx
        assert "knockdown" in _status_ids(eng)

    def test_recover_needs_valid_window(self) -> None:
        """当次窗口已过期 → 无受身（按原击落语义）。"""
        raw, all_defs, chains = _pack()
        ce = ComboEngine(
            defs={**all_defs, **chains},
            resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
        )
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=1.0)   # 早于当前时刻：窗口失效
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        assert "air_drop" in _fx_types(out)
        assert "knockdown" in _status_ids(eng)

    def test_no_recover_when_tagged(self) -> None:
        """「不可受身」例外（致命扑杀）：有格也不受身。"""
        raw, all_defs, chains = _pack()
        ce = ComboEngine(
            defs={**all_defs, **chains},
            resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
        )
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "sb_lethal_pounce"})
        fx = _fx_types(out)
        assert "air_drop" in fx and "air_recover" not in fx
        assert "knockdown" in _status_ids(eng)
        assert _wb(eng) == 2   # 例外：未扣格

    def test_recover_cost_configurable(self) -> None:
        """air_wirebug_recover_cost 可调（2 格一扣）。"""
        raw, all_defs, chains = _pack()
        ce = ComboEngine(
            defs={**all_defs, **chains},
            resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
        )
        eng = _fresh(raw, all_defs, ce, config={"ctb": {"air_wirebug_recover_cost": 2}})
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        assert "air_recover" in _fx_types(out)
        assert _wb(eng) == 0


# =====================================================================================
# 6. 渲染（受身行；零数值）
# =====================================================================================


class TestAirRecoverRender:
    def _enemy_outcome(self, events):
        return SimpleNamespace(
            actor="enemy", action_type="normal", target="P", hit=True,
            side_effects=events, final_damage=50, raw_damage=50, target_hp=450,
            player_max_hp=500, target_name="P", attacker_name="泽骨鳄",
            message="", intent_skill=None, special_action=None,
            player_guarding=False, defending=False, blocked=False, crit="low",
        )

    def test_air_recover_line(self) -> None:
        """air_recover 事件 → 怪行动行集含「翻身」受身行（怪名映射、零数值）。"""
        ev = ({"type": "air_recover", "actor": "player", "attacker": "enemy"},)
        line = _render_enemy_action(self._enemy_outcome(ev))
        assert line is not None and "翻身" in line
        assert "泽骨鳄" in line
        _recover_line = next(x for x in line.split("\n") if "翻身" in x)
        assert not re.search(r"\d", _recover_line), f"受身行含数字：{_recover_line}"

    def test_direct_render_helper(self) -> None:
        ev = ({"type": "air_recover", "actor": "player", "attacker": "enemy"},)
        lines = _render_air_recover_lines(self._enemy_outcome(ev))
        assert len(lines) == 1 and "翻身" in lines[0]

    def test_no_event_no_line(self) -> None:
        line = _render_enemy_action(self._enemy_outcome(()))
        assert line is None or "翻身" not in line
