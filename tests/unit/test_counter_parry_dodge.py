"""防反/闪反双子机制单测（2026-09-09 用户拍板标签制：不 roll——怪行动可反标签+玩家姿态）。

- 防反：怪行动带「可防反」+ 玩家防反姿态（守势 parry）→ 完全免伤 + 自动反击
- 闪反：怪行动带「可闪反」+ 玩家闪反姿态（回环/腾空 dodge）位移出范围 → 免伤（天然）+ 反击
- 失败：行动无标签 → 受伤（姿态减伤照常）+ 无反击

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义。
  1. 怪侧行动经单次结算入口 `do_action("enemy", ...)` 显式驱动（`enemy_act` 已为
     NotImplementedError 壳）——等价 CTB「怪在自身 ACTOR_READY 时出手」。
  2. 姿态窗口口径（R10 消费侧，2026-09-10 定稿）：`counter_stance` 写入时记
     `_stance_owner_seq = action_seq`，消费侧 `_player_stance` 要求
     `当前 action_seq >= 记`（「自写入起、至持有者再次行动止」）——CTB 下等价于
     「写入的那一拍之后的所有怪行动都在窗口内」，直到玩家**下一次**行动才过期。
  3. `test_parry_stance_expires_across_action_seq`（下方）：锁定「玩家再次行动后
     姿态失效」这一窗口上界；`test_parry_via_player_act_end_to_end`：锁定经
     `player_act` 的「守势 → 敌后手」端到端链路**可**防反（写入一拍 + 后续怪行动）。
"""
from pathlib import Path


from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.monster_ai import MonsterAI


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _pack():
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


_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 10, "mag": 10,
    "proficiency": {"alchemy": {"level": 4, "exp": 0}},
}


def _enemy(raw, eid, *, spd=None):
    """构造敌人战斗侧数值。

    CTB 迁移（2026-09-10）：`spd` 不再是「排序用的装饰字段」，而是**行动条推进的
    唯一分母**——`next_ready` 增量 = `recovery * speed_reference / max(spd, min_speed)`。
    故 `spd=0` 在 CTB 下等价于「该单位永不 ready」（cost 被 clamp 到 min_speed 后
    仍极大），旧回合制里「spd=0 表示怪不抢先手」的用法不再成立。

    :param spd: 显式指定速度；None → 取敌人 def 的 `stats.agi`（CTB 下怪也需要能行动）
    """
    et = next(e for e in raw["enemies"] if e["id"] == eid)
    st = et.get("stats") or {}
    _spd = int(st.get("agi", 10) or 10) if spd is None else int(spd)
    return et, {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": int(st.get("str", 10)), "dfn": int(st.get("con", 10)),
        "mag": 0, "spd": _spd, "foc": 0, "lck": 0,
        "con": int(st.get("con", 10)), "agi": 0, "name": et["name"],
    }


def _fresh(raw, all_defs, ce):
    et, mob = _enemy(raw, "ridge_cub")
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7)
    eng._enemy_ai = ai
    return eng


def _fx_types(outcomes):
    out = []
    for o in outcomes:
        for x in (getattr(o, "side_effects", ()) or ()):
            out.append(str(x.get("type")))
    return out


def test_parry_guard_fully_negates_and_counter():
    """守势（防反姿态）挡可防反扑咬 → 完全免伤（hp 不减）+ parry_counter 反击伤害。

    CTB 迁移（2026-09-10）：姿态写入侧（R11）经真实 `sw_guard` 施放触发（不再手写
    `counter_stance`），随后把窗口对齐到**当前** action_seq —— R10 口径「姿态窗口 =
    写入时的 action_seq == 消费时的 action_seq（本次行动窗口）」。怪物行动经单次结算
    入口 `do_action("enemy", ...)` 显式驱动（`enemy_act` 已删）。核心断言仍是 CTB 语义：
    「同一 action 窗口内可防反 → 完全免伤 + 自动反击」。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    act = next((a for a in raw["action"] if "可防反" in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有可防反行动"
    # 写入侧：真实施放守势（R11 写 counter_stance）
    eng.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    st = eng._snap.get("counter_stance") or {}
    assert st.get("type") == "parry" and st.get("skill") == "sw_guard_counter", \
        f"守势施放应写入防反姿态，got {st}"
    # R10 同一窗口：把姿态的 action_seq 对齐到当前（施放收尾已推进一格）
    st["action_seq"] = eng.action_seq
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = [str(x.get("type")) for x in (getattr(out, "side_effects", ()) or ())]
    assert "parry" in fx and "parry_counter" in fx, f"防反应触发 parry/counter，got {fx}"
    assert out.target_hp == 900, f"防反成功应完全免伤（hp 900），got {out.target_hp}"
    cd = next((int(x.get("damage") or 0)
               for x in (getattr(out, "side_effects", ()) or ())
               if x.get("type") == "parry_counter"), 0)
    assert cd > 0, f"防反反击应造成伤害，got {cd}"


def test_dodge_circle_position_miss_counter():
    """回环（闪反姿态）→ 侧移出扑咬方位 → 未命中（免伤）+ dodge_counter 反击。

    CTB 迁移（2026-09-10）：同 `test_parry_guard_fully_negates_and_counter` —— 真实施放
    回环写姿态（R11），再把姿态窗口对齐到**当前** action_seq（R10 本次行动窗口），怪物
    行动经 `do_action("enemy", ...)` 显式驱动。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    act = next((a for a in raw["action"] if "可闪反" in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有可闪反行动"
    # 真实施放回环 → 位移（side）+ 写姿态
    eng.do_action("player", {"type": "skill", "skill_id": "sw_circle"})
    st = eng._snap.get("counter_stance") or {}
    assert st.get("type") == "dodge" and st.get("skill") == "sw_circle_counter", \
        f"回环施放应写入闪反姿态，got {st}"
    pos = eng._snap.setdefault("combat_position", {}).setdefault("player", {})
    pos["side"] = "right"                      # 位移出正面（回环侧移产物）
    st["action_seq"] = eng.action_seq          # R10 同一窗口
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = [str(x.get("type")) for x in (getattr(out, "side_effects", ()) or ())]
    assert "position_miss" in fx, f"回环侧移后扑咬应未命中，got {fx}"
    assert out.target_hp == 900, f"闪反成功应免伤，got {out.target_hp}"
    cd = next((int(x.get("damage") or 0)
               for x in (getattr(out, "side_effects", ()) or ())
               if x.get("type") == "dodge_counter"), 0)
    assert cd > 0, f"闪反反击应造成伤害，got {cd}"


def test_parry_stance_expires_across_action_seq():
    """CTB 语义：姿态窗口 = 「自写入起至持有者再次行动止」；持有者再行动后即失效。

    锁死 R10 口径：姿态写入 action_seq=N 且持有者此后未再行动 → 有效；
    一旦持有者自己又行动了一次（`_stance_owner_seq` 前移越过写入拍）→ 姿态过期，
    再受同一次可防反攻击不触发 parry（照常受伤）。

    CTB 迁移（2026-09-10）：不再用「写入拍 == 当前拍」的判等口径（那会使姿态在
    敌方后手到达时恒过期）。过期由**持有者再次行动**这一事件保证。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    act = next((a for a in raw["action"] if "可防反" in (a.get("tags") or [])), None)
    assert act is not None
    eng.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    st = eng._snap.get("counter_stance") or {}
    assert st, "守势应写入防反姿态"
    # 模拟「持有者此后又行动了一次」：owner_seq 前移越过写入拍 → 窗口关闭
    eng._stance_owner_seq = int(st.get("action_seq", 0)) + 1
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = [str(x.get("type")) for x in (getattr(out, "side_effects", ()) or ())]
    assert "parry" not in fx, f"持有者再行动后姿态应失效，got {fx}"
    assert out.target_hp < 900, "姿态过期应照常受伤"


def test_parry_via_player_act_end_to_end():
    """端到端：经 `player_act(sw_guard)` 由调度器自动推进敌方后手 → 应触发防反。

    CTB 语义（R10，2026-09-10 修复后）：玩家守势写入姿态 → 窗口为「自写入起至
    持有者再次行动止」，横跨调度器自动推进的敌方后手拍 → 该敌方可防反行动落在
    有效窗口内 → 免伤 + 反击。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr.outcomes)
    assert "parry" in fx and "parry_counter" in fx, f"端到端防反应触发，got {fx}"
    assert tr.player == 900, f"防反成功应完全免伤，got {tr.player}"


def test_guard_vs_non_parryable_action_takes_damage():
    """守势挡不可防反行动 → 受伤（减伤照常）+ 无 parry 事件（用户示例语义）。"""
    raw, all_defs, ce = _pack()
    # 找无「可防反」标签的伤害行动（td_stomp 震地类）
    act = next((a for a in raw["action"]
                if a.get("intent") == "伤害" and "可防反" not in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有不可防反的伤害行动"
    et, mob = _enemy(raw, "ridge_cub")
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7)
    eng._enemy_ai = ai
    # 玩家先施守势（姿态在当次行动）
    eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    # 再开一局干净验证：守势当次行动被不可反行动打
    eng2 = _fresh(raw, all_defs, ce)
    eng2._snap["counter_stance"] = {"type": "parry", "skill": "sw_guard_counter",
                                    "turn": int(eng2._snap.get("turn", 0))}
    out = eng2.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = [str(x.get("type")) for x in (getattr(out, "side_effects", ()) or ())]
    assert "parry" not in fx, f"不可防反行动不应触发防反，got {fx}"
    assert out.target_hp < 900, "不可防反行动应造成伤害"
