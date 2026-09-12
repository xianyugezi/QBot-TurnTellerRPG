"""跃空受身验收测试——批⑨（2026-09-12 实装；翔虫续航方案已拆除，受身为无消耗自动档）。

口径（docs/veinborn_战斗规则增补_v1.md §四；怪猎对照研究 D-16）：
  - 受身：被击落时「当次窗口仍有效 + 非『不可受身』」→ **自动**取消倒地与硬直
    （凌空翻身稳落；`air_recover` 事件 + battle_air_recover 行；零数值）；
  - 窗口失效（未初始化/已过期）→ 原完整击落链（倒地 + 行动条硬直）不受影响；
  - 「不可受身」例外 = 致命扑杀（击落三招中唯一；其余两招可受身）；
  - 无资源依赖（翔虫续航资源未采纳——起跳/延长/回复类消耗不存在）。

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG 固定序列）。
"""

from __future__ import annotations

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

_VEINBORN = Path("content/veinborn")


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


def _fx_types(outcome) -> list:
    return [str(x.get("type")) for x in (getattr(outcome, "side_effects", ()) or ())]


def _player_ready(eng: BattleEngine) -> float:
    view = eng._ctb.get_actor("player") if eng._ctb is not None else None
    assert view is not None
    return float(view.next_ready)


# =====================================================================================
# 1. 内容守卫：击落三招的「不可受身」例外口径
# =====================================================================================


class TestRecoverContent:
    def test_recover_exception_tag_contract(self) -> None:
        """击落三招中恰「致命扑杀」带不可受身（例外口径；其余可受身）。"""
        raw, _, _ = _pack()
        acts = {a["id"]: a for a in raw["action"]}
        kd = [aid for aid, a in acts.items() if a.get("air_drop") == "knockdown"]
        assert sorted(kd) == ["sa_quake_stomp", "sb_lethal_pounce", "zb_ambush"]
        tagged = [aid for aid in kd if "不可受身" in (acts[aid].get("tags") or [])]
        assert tagged == ["sb_lethal_pounce"]


# =====================================================================================
# 2. 引擎：受身（窗口有效自动取消；窗口失效/例外 → 完整击落）
# =====================================================================================


class TestAirRecover:
    @pytest.mark.parametrize("sid", ["zb_ambush", "sa_quake_stomp"])
    def test_recover_cancels_knockdown(self, sid: str) -> None:
        """窗口仍有效 + 非不可受身 → 自动受身：无倒地、无硬直、稳落（免耗资源）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        before = _player_ready(eng)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": sid})
        fx = _fx_types(out)
        assert "air_recover" in fx and "air_drop" not in fx
        assert _height(eng) == "ground"
        assert "knockdown" not in _status_ids(eng)
        assert "sw_vault_air" not in _status_ids(eng)   # 落地清理照常
        assert _player_ready(eng) == pytest.approx(before)  # 无硬直
        notes = [n for n in eng._snap.get("battle_notes", []) if isinstance(n, dict)
                 and n.get("type") == "air_recover"]
        assert len(notes) == 1

    def test_knockdown_when_window_expired(self) -> None:
        """当次窗口已过期 → 无受身：完整击落链（倒地 + 硬直）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=1.0)
        before = _player_ready(eng)
        now = float(eng.battle_time)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        fx = _fx_types(out)
        assert "air_drop" in fx and "air_recover" not in fx
        assert "knockdown" in _status_ids(eng)
        assert _player_ready(eng) == pytest.approx(max(before, now) + 400.0)

    def test_knockdown_when_window_uninitialized(self) -> None:
        """窗口未初始化（无到期值）→ 不算「仍有效」→ 完整击落。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng)   # 无 air_expire_at
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        fx = _fx_types(out)
        assert "air_drop" in fx and "air_recover" not in fx
        assert "knockdown" in _status_ids(eng)

    def test_no_recover_when_tagged(self) -> None:
        """「不可受身」例外（致命扑杀）：窗口有效也不受身。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce)
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        out = eng.do_action("enemy", {"type": "skill", "skill_id": "sb_lethal_pounce"})
        fx = _fx_types(out)
        assert "air_drop" in fx and "air_recover" not in fx
        assert "knockdown" in _status_ids(eng)

    def test_recover_delay_config_untouched(self) -> None:
        """受身成功路径不吃 air_drop_delay；完整击落路径照旧吃（配置口径回归）。"""
        raw, all_defs, ce = _pack()
        eng = _fresh(raw, all_defs, ce, config={"ctb": {"air_drop_delay": 900}})
        eng.do_action("player", {"type": "guard"})
        _set_air(eng, expire=999999.0)
        before = _player_ready(eng)
        eng.do_action("enemy", {"type": "skill", "skill_id": "zb_ambush"})
        assert _player_ready(eng) == pytest.approx(before)   # 受身路径：无延迟


# =====================================================================================
# 3. 渲染（受身行；零数值）
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
