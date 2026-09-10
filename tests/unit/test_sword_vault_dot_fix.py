"""御剑·腾空闪避回馈 + dot 破位 单测（2026-09-09 原稿修复）。

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义 对照
  - 旧「`player_act` 内隐含一次完整轮：玩家先手 → 怪固定后手反击」→ CTB 无先手/
    后手对：一次 `player_act` 只推进到「下一个玩家 ready」，NPC 连锁由调度器
    自动推进（调度器只派发事件，行动内容执行见下述缺口）。故闪避回馈用例改为
    用**单次结算入口** `do_action("enemy", action_dict)` 显式驱动怪的攻击
    （`enemy_act` 已为 NotImplementedError 壳，禁止调用）——这精确对应 CTB
    「怪在自身 ACTOR_READY 时行动」的等价语义。
  - 旧「回合结束 DOT（tick=turn_end）在 end_turn ⑥ tick」→ CTB 目标位点
    `ACTOR_TURN_END` / `AFTER_ACTION`（迁移目标：行动者行动后结算 DOT）。

CTB 迁移说明（2026-09-10 更新，原登记的两项缺口均已修复）：
  1. NPC 行动内容已接线：`CTBScheduler` 新增 `npc_resolver` 回调，引擎
     `_resolve_npc_action()` 在 ACTION_RESOLVE 位点执行 MonsterAI 决策 +
     `do_action` 全链路（写 action_record / 结算伤害）。本文件仍以
     `do_action("enemy", action_dict)` 显式驱动怪的攻击——这精确对应 CTB
     「怪在自身 ACTOR_READY 时行动」的等价语义，且把「谁先动」这一变量隔离掉，
     使断言只考察伤害/姿态/剑势本身。
  2. `effects.tick_turn_end` 已接线：`_after_actor_action`（ACTOR_TURN_END 位点）
     调它结算旧 end_turn ⑥ 的全部内容（turn_end DOT / 吸收回复 / 持续双维扣减），
     并复核双方死亡。故 `tick="turn_end"` 的 DOT（含 `part_break_per_tick`）在
     CTB 下正常结算。

铁律：零 NoneBot import；纯逻辑断言；确定性随机。直接 build_pack 仓库 veinborn
内容包（与 e2e test_m13_fullchain 同风格）。
"""
import copy
from pathlib import Path


from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine

_PACK = Path("content/veinborn")


def _load_pack():
    pack, _ = build_pack(_PACK)
    assert pack.report.ok, f"veinborn 应零红拦：{pack.report.errors}"
    raw = pack.registry.modules_raw
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    ce = ComboEngine(defs={**all_defs, **chains},
                     resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i))
    return raw, all_defs, ce


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _mk_enemy(et, st, parts=None):
    m = {"id": et["id"], "hp": 20000, "max_hp": 20000, "mp": 0, "atk": int(st.get("str", 10)),
         "dfn": int(st.get("con", 10)), "mag": 0, "spd": 0, "foc": 0, "lck": 0,
         "con": int(st.get("con", 10)), "agi": 0, "name": et["name"]}
    if parts:
        m["parts"] = parts
    return m


def test_sw_vault_dodge_feedback():
    """腾空原版（方位制）：sw_vault 挂腾空姿态（air+status）；怪 ground 技打空中玩家
    =position miss（够不着）→ 闪避回馈 +30 剑势。

    CTB 迁移：怪侧攻击经 `do_action("enemy", ...)` 显式驱动（替代已删除的
    enemy_act + 自动后手）。
    """
    raw, all_defs, ce = _load_pack()
    et = next(e for e in raw["enemies"] if e["id"] == "gravel_tortoise")
    st = et.get("stats") or {}
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    player = {"max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60, "foc": 10,
              "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10, "elem_atk": 0,
              "name": "P", "spd": 10, "mag": 10, "proficiency": {"alchemy": {"level": 4, "exp": 0}}}
    eng.start(player, _mk_enemy(et, st, et.get("parts")), random_seed=7)
    snap = eng._snap

    def aura():
        return next((x["count"] for x in snap["marks_state"].get("player", [])
                     if x["mark_id"] == "sword_aura"), 0)

    eng.player_act({"type": "skill", "skill_id": "sw_vault"})
    assert any(s.get("status_id") == "sw_vault_air"
               for s in snap.get("status_state", {}).get("player", [])), "腾空姿态未挂"
    a0 = aura()
    assert a0 == 15, f"腾空斩灌注剑势应 15，got {a0}"
    # CTB：怪在自身 ACTOR_READY 时行动（单次结算入口显式驱动）——ground 技打空中玩家
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "gj_ram", "mult": 1.0})
    assert out.hit is False, "ground 技打空中玩家应 miss（够不着）"
    assert aura() == a0 + 30, "被攻击 miss 应闪避回馈 +30 剑势"


def test_dot_part_break_per_tick():
    """二阶残响 dot：每跳对目标未破部位造成破坏值（part_break_per_tick）。

    CTB 目标位点：`ACTOR_TURN_END` / `AFTER_ACTION`（旧「回合结束 DOT」→ 行动者
    行动后结算）。2026-09-10 已接线：`_after_actor_action` 调 `effects.tick_turn_end`
    —— 玩家行动收尾即结算敌方 turn_end DOT 的每跳破位值。
    """
    raw, all_defs, ce = _load_pack()
    et = next(e for e in raw["enemies"] if e["id"] == "gravel_tortoise")
    st = et.get("stats") or {}
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    player = {"max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60, "foc": 10,
              "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10, "elem_atk": 0,
              "name": "P", "spd": 10, "mag": 10, "proficiency": {"alchemy": {"level": 4, "exp": 0}}}
    eng.start(player, _mk_enemy(et, st, et.get("parts")), random_seed=7)
    snap = eng._snap
    snap["enemy"].setdefault("dot_pool", {})["sw_omni_dot"] = {
        "status_id": "sw_omni_dot", "value": 60, "tick": "turn_end", "turns": 2,
        "source": "player", "part_break_per_tick": 5}
    before = copy.deepcopy(snap.get("parts_state") or {})
    eng.player_act({"type": "skill", "skill_id": "sw_slash"})
    after = snap.get("parts_state") or {}
    for pid, pst in after.items():
        old = float((before.get(pid) or {}).get("break_value", 0))
        inc = float(pst.get("break_value", 0)) - old
        assert inc >= 5.0, f"dot tick 后 {pid} 破坏值应含 dot 每跳 5，实际增量 {inc}"
