"""反击返还（C11）验收测试——2026-09-12 批⑤实装。

口径（docs/veinborn_战斗规则增补_怪猎对照研究_20260911.md §C-11）：
  - **反击返还**：防反/闪反成功 → 玩家下一次 ready 返还 `ctb.counter_refund`
    （缺省 200 行动条；可配、0=关）；「节奏加速」收益（对标怪猎派生取消后摇）。
  - **落空不双罚**：失败路径（行动不可反）不返还——只付行动条。
  - 语义：`next_ready ← max(now, next_ready − refund)`（下限钳到当前时刻=最多
    「立即行动」，不倒流）；**挂点须在 `_run_counter` 之前**——反击技内部走
    完整收尾链（含本拍时间轴推进），先返还才能让推进落在提早后的 ready 上。
  - 隐性口径：玩家不可见（加速本身即反馈）——本测试为引擎级断言。

> 批⑥（2026-09-12）口径：内容恢复值逐动作化后，**期望值一律由内容推导**——守势/
> 闪反技能的 `recovery` × 速度系数（`_bars`/`_settle`），不写死绝对时序。

铁律：零 NoneBot import；确定性（_QR 固定序列）；真跑断言（非静态）。
"""

from __future__ import annotations

from pathlib import Path

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.ctb_rules import DEFAULT_RECOVERY, SPEED_REFERENCE
from qbot_rpg.core.monster_ai import MonsterAI


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i % len(self.seq)]
        self.i += 1
        return v


def _pack(*, strip_counter_tags: bool = False):
    """加载 veinborn 包并构建 defs/combo 引擎。

    :param strip_counter_tags: 测试专用——剥掉全部行动的「可防反/可闪反」标签
        （造「行动不可反」的干净失败场景：守势持窗但永不触发）。
    """
    pack, _ = build_pack(Path("content/veinborn"))
    raw = pack.registry.modules_raw
    if strip_counter_tags:
        for _a in raw["action"]:
            if isinstance(_a, dict) and _a.get("tags"):
                _a["tags"] = [t for t in _a["tags"]
                              if t not in ("可防反", "可闪反")]
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


# 玩家 spd=10（每拍 1000 行动条）；怪 spd=8（每拍 1250）——怪首拍在玩家行动后
# +250 处（落进 400 行动条守势窗口），自然触发防反/闪反（对齐既有反制测试几何）。
_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 10, "mag": 10,
}


def _fresh(raw, all_defs, ce, *, spd=8, config=None):
    et = next(e for e in raw["enemies"] if e["id"] == "ridge_cub")
    st = et.get("stats") or {}
    mob = {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": int(st.get("str", 10)), "dfn": int(st.get("con", 10)),
        "mag": 0, "spd": int(spd), "foc": 0, "lck": 0,
        "con": int(st.get("con", 10)), "agi": 0, "name": et["name"],
    }
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7, config=config)
    eng._enemy_ai = ai
    return eng


def _fx_types(report) -> list:
    out = []
    for o in (getattr(report, "outcomes", None) or []):
        for x in (getattr(o, "side_effects", ()) or ()):
            out.append(str(x.get("type")))
    return out


def _player_ready(eng) -> float:
    view = eng._ctb.get_actor("player")
    assert view is not None
    return float(view.next_ready)


def _spy_hasten(eng) -> list:
    """包装调度器 hasten_actor 记录调用（失败路径无调用=不返还的直接证据）。"""
    calls = []
    orig = eng._ctb.hasten_actor

    def _spy(actor_id, refund_bars=0.0):
        calls.append((str(actor_id), float(refund_bars)))
        return orig(actor_id, refund_bars)

    eng._ctb.hasten_actor = _spy  # type: ignore[method-assign]
    return calls


def _rec(raw, sid):
    """技能恢复值（内容读取；批⑥ 后逐动作可调——期望值推导用）。"""
    return next(s for s in raw["skills"] if s["id"] == sid)["recovery"]


def _bars(rec, spd):
    """恢复值 → 行动条（cost = rec × SPEED_REFERENCE / spd）。"""
    return rec * SPEED_REFERENCE / spd


def _settle(raw, skill_id, refund, *, spd=10):
    """防反/闪反成功后收口（内容推导）：max(本拍 ready − 返还, 怪出手时刻)。"""
    ready_after = _bars(DEFAULT_RECOVERY, spd) + _bars(_rec(raw, skill_id), spd)
    enemy_moment = _bars(DEFAULT_RECOVERY, 8)   # 怪 spd=8 首拍（初始缺省恢复）
    return max(ready_after - refund, enemy_moment)


# =====================================================================================
# 1. 防反成功 → 返还（E2E：spd=8，怪 +250 出手落窗）
# =====================================================================================


def test_parry_success_refunds_action_bar():
    """防反成功：返还缺省 200，收口 = _settle(sw_guard, 200)（内容推导）。

    挂点回归：若返还在 `_run_counter` 之后才生效，收口将停在守势后 ready（未提早）
    ——`_settle` 断言即挂点顺序守卫（批⑥ 起不写死绝对时序）。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    calls = _spy_hasten(eng)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr)
    assert "parry" in fx and "parry_counter" in fx, f"防反应触发，got {fx}"
    assert tr.player == 900, "防反成功应完全免伤"
    # 返还证据链：恰一次调用 + 时点/数值正确 + 时间轴收口在 1800
    assert calls == [("player", 200.0)], f"返还调用异常：{calls}"
    expect = _settle(raw, "sw_guard", 200.0)
    assert eng.battle_time == expect, f"防反后收口应 {expect}，got {eng.battle_time}"
    assert _player_ready(eng) == expect


def test_no_counter_no_refund_baseline():
    """对照：普攻（无防反）→ 不返还，收口于 2000（自然 ready）。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    calls = _spy_hasten(eng)
    eng.player_act({"type": "normal"})
    assert calls == [], f"无防反不应有返还调用：{calls}"
    assert eng.battle_time == 2000.0, f"对照收口应 2000，got {eng.battle_time}"


def test_counter_fail_no_refund():
    """失败路径（行动不可反）：守势持窗但怪行动无「可防反」→ 受伤 + 无返还。

    场景造法：剥掉全部行动的「可防反/可闪反」标签（行为差异仅在反制判定），
    守势照常施放、怪照常出手——失败 = 只付行动条（不双罚）。
    """
    raw, all_defs, ce = _pack(strip_counter_tags=True)
    eng = _fresh(raw, all_defs, ce)
    calls = _spy_hasten(eng)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr)
    assert "parry" not in fx and "parry_counter" not in fx, f"不可反行动不应触发：{fx}"
    assert tr.player < 900, "失败路径应照常受伤（不双罚：只付行动条）"
    assert calls == [], f"失败路径不应返还：{calls}"
    expect = _bars(DEFAULT_RECOVERY, 10) + _bars(_rec(raw, "sw_guard"), 10)
    assert eng.battle_time == expect, f"失败收口应 {expect}（照付守势代价），got {eng.battle_time}"


# =====================================================================================
# 2. 闪反成功 → 返还（同口径）
# =====================================================================================


def test_dodge_success_refunds_action_bar():
    """闪反成功（回环侧移出扑咬方位）：收口 = _settle(sw_circle, 200)（内容推导）。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    calls = _spy_hasten(eng)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_circle"})
    fx = _fx_types(tr)
    assert "dodge_counter" in fx, f"闪反应触发，got {fx}"
    assert tr.player == 900, "闪反成功应免伤"
    assert calls == [("player", 200.0)], f"返还调用异常：{calls}"
    expect = _settle(raw, "sw_circle", 200.0)
    assert eng.battle_time == expect, f"闪反后收口应 {expect}，got {eng.battle_time}"


# =====================================================================================
# 3. 可配：返还值 / 关断 / 下限钳制
# =====================================================================================


def test_refund_configurable():
    """counter_refund=150（settings→ctb 段）→ 收口 = _settle(…, 150)（内容推导）。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce, config={"ctb": {"counter_refund": 150}})
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    assert "parry_counter" in _fx_types(tr)
    expect = _settle(raw, "sw_guard", 150.0)
    assert eng.battle_time == expect, f"got {eng.battle_time} expect {expect}"
    assert _player_ready(eng) == expect


def test_refund_zero_disables():
    """counter_refund=0 → 关（无返还调用、照付守势代价，防反其余效果不变）。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce, config={"ctb": {"counter_refund": 0}})
    calls = _spy_hasten(eng)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    assert "parry_counter" in _fx_types(tr), "关断只影响时间返还，防反本体照常"
    assert calls == [], f"关断不应有返还调用：{calls}"
    expect = _bars(DEFAULT_RECOVERY, 10) + _bars(_rec(raw, "sw_guard"), 10)
    assert eng.battle_time == expect, f"got {eng.battle_time}"


def test_refund_clamped_at_now():
    """超量返还 → 下限钳到当前时刻（最多「立即行动」，不倒流）。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce, config={"ctb": {"counter_refund": 900}})
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    assert "parry_counter" in _fx_types(tr)
    # 守势后 ready − 900 已低于怪出手时刻（1250）=返还下限钳到当前时刻
    floor = _bars(DEFAULT_RECOVERY, 8)
    assert eng.battle_time == floor, f"got {eng.battle_time}"
    assert _player_ready(eng) == floor
    # 超量返还（5000）与 900 同钳到下限（不倒流）
    eng2 = _fresh(raw, all_defs, ce, config={"ctb": {"counter_refund": 5000}})
    tr2 = eng2.player_act({"type": "skill", "skill_id": "sw_guard"})
    assert "parry_counter" in _fx_types(tr2)
    assert eng2.battle_time == floor, f"got {eng2.battle_time}"


# =====================================================================================
# 4. 护栏：无调度器 / 死单位（helper 兜底不抛）
# =====================================================================================


def test_helper_survives_without_scheduler():
    """未装配调度器（直调 helper）→ 静默跳过，绝不抛错。"""
    eng = BattleEngine()
    eng._ctb = None
    eng._hasten_player_after_counter()  # 不抛错即通过

# =====================================================================================
# 5. 渲染：格挡行清洗（「使出X」前缀剥离）
# =====================================================================================


def test_parry_render_strips_shishi_prefix():
    """格挡行不出现「你格挡了使出X」——展示串剥「使出」前缀。"""
    from types import SimpleNamespace

    from qbot_rpg.core.message_format.battle_render import _render_enemy_action

    out = SimpleNamespace(
        action_type="skill", hit=True, action_name="使出晶牙噬咬",
        side_effects=[{"type": "parry", "target": "player",
                       "attacker": "enemy", "skill_id": "x"}],
    )
    rendered = _render_enemy_action(out)
    assert "你格挡了晶牙噬咬（完全免伤）" in rendered, rendered
    assert "使出晶牙噬咬" not in rendered
