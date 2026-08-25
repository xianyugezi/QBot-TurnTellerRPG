"""M2 审查修复回归测试（2026-08-26 dsh 三批审查 P 项修复的验证）。

依据：审查_M2_批次1/2/3_jspace.md 的 P 项修复：
- P1-1(batch1) R15 接续概率 <60% 黄提示 → test_r15_chain_continuation_lt60
- P1-1(batch2) phase 写端（HP→phase 换算 + phase_changed 联动）→ test_phase_write_end
- P1-2(batch2) 断链冷却 max 保留（防锁死）→ test_chain_cooldown_not_reset
- P1-3(batch2) 蓄力 intent 统一走 build_intent → test_charge_intent_uses_build_intent
- P1-1(batch3) combo_broken 一次性标记（决策后清除）→ test_combo_broken_cleared
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from qbot_rpg.content.validator import check_pack

PACKS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
LEGAL_DIR = PACKS_DIR / "legal"


def _load_pack_json(pack_dir: Path, name: str) -> object:
    return json.loads((pack_dir / f"{name}.json").read_text(encoding="utf-8"))


def _legal_enemies() -> list:
    data = _load_pack_json(LEGAL_DIR, "enemies")
    assert isinstance(data, list)
    return data


def _base_enemy(**overrides: object) -> dict:
    for e in _legal_enemies():
        if e.get("id") == "rock_weasel":
            enemy = copy.deepcopy(e)
            enemy.update(overrides)
            return enemy
    raise AssertionError("legal/enemies.json 无 rock_weasel")


def _check_modules(enemies: list, actions: object | None = None) -> object:
    """标准模块上下文（action/effects/statuses/items 取 legal fixtures 作引用基线）+ 传入 enemies 跑校验器。"""
    modules: dict = {
        "action": actions if actions is not None else _load_pack_json(LEGAL_DIR, "action"),
        "effects": _load_pack_json(LEGAL_DIR, "effects"),
        "statuses": _load_pack_json(LEGAL_DIR, "statuses"),
        "items": _load_pack_json(LEGAL_DIR, "items"),
        "enemies": enemies,
    }
    return check_pack(modules)


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w.detail.get("rule") == rule]


# ============ 1. R15 接续概率 <60% 黄提示（batch1 P1-1） ============
def test_r15_chain_continuation_lt60_warns():
    enemy = _base_enemy(
        chains=[{"id": "weak_chain", "cooldown": 2,
                 "actions": [{"action": "fireball", "chance": 0.5, "role": "chain"},
                             {"action": "tail_sweep", "chance": 0.8, "role": "finisher"}]}]
    )
    rep = _check_modules([enemy])
    assert _warns(rep, "R15_chain_continuation_lt60"), (
        f"期望 chance<0.6 黄提示，实际 {[(w.kind, dict(w.detail)) for w in rep.warnings]}")
    # 高接续概率不提示
    enemy_ok = _base_enemy(
        chains=[{"id": "good_chain", "actions": [{"action": "fireball", "chance": 0.8, "role": "chain"}]}]
    )
    rep2 = _check_modules([enemy_ok])
    assert not _warns(rep2, "R15_chain_continuation_lt60"), "chance 0.8 不应触发 <60% 黄提示"


# ============ 2. phase 写端（batch2 P1-1） ============
def test_phase_write_end_updates_ai_state():
    from qbot_rpg.core.monster_ai import MonsterAI, NORMAL

    ACTION_LIB = {"claw": {"id": "claw", "kind": "active", "power": 1.0, "tags": ["attack"]},
                  "roar": {"id": "roar", "kind": "active", "power": 0.0, "tags": ["defense"]}}
    enemy = {
        "id": "phase_boss", "name": "阶段王",
        "actions": [{"action": "claw", "probability": 1, "weight": 1}],
        "special_actions": [], "chains": [],
        "phases": [
            {"threshold": 100, "enter_action": "roar", "broadcast": "常规"},
            {"threshold": 60, "enter_action": "roar", "broadcast": "狂暴化！"},
            {"threshold": 30, "enter_action": "roar", "broadcast": "绝境！"},
        ],
        "ai": {"states": {"enraged": {"enter_action": "roar"}}, "transitions": []},
    }

    class Rng:
        def __init__(self, v): self._v = v
        def random(self): return self._v
        def choice(self, s): return s[0]

    ai = MonsterAI(enemy, ACTION_LIB, Rng(0.5))
    # HP 50% → 阶段 2（60 阈值以下）；max_hp 1000 → hp 500
    bs = {"turn": 1, "player": {"hp": 500, "max_hp": 500},
          "enemy": {"hp": 500, "max_hp": 1000, "pv": 300}, "ai_state": {}}
    r = ai.decide(bs)
    st = bs["ai_state"]
    assert st["phase"] == 2, f"HP 50% 应切阶段 2，实际 {st['phase']}"
    assert st["boss_phase"] == 2, "boss_phase 兼容键同步"
    assert st["state"] == NORMAL
    # enter_action 入强制队列后被 L2 消费 → decide 返回 roar（阶段切换演出先行）
    assert r["action_id"] == "roar" and r["source"] == "L2", (
        f"enter_action 应经 L2 执行（roar），实际 {r.get('action_id')}/{r.get('source')}")
    # 继续掉到 20% → 阶段 3
    bs["enemy"]["hp"] = 200
    ai.decide(bs)
    assert bs["ai_state"]["phase"] == 3, f"HP 20% 应切阶段 3，实际 {bs['ai_state']['phase']}"


# ============ 3. 断链冷却 max 保留（batch2 P1-2） ============
def test_chain_cooldown_not_reset_on_repeat():
    from qbot_rpg.core.monster_ai import MonsterAI

    ACTION_LIB = {"fireball": {"id": "fireball", "kind": "active", "power": 1.6, "tags": ["attack"]},
                  "tail_sweep": {"id": "tail_sweep", "kind": "active", "power": 1.0, "tags": ["attack"]}}
    enemy = {
        "id": "chain_boss", "name": "连招王",
        "actions": [{"action": "fireball", "probability": 1, "weight": 1}],
        "special_actions": [], "chains": [],
        "ai": {"states": {}, "transitions": []},
    }
    # 手动注入一条链 + 冷却中的状态
    enemy["chains"] = [{"id": "molten", "cooldown": 3,
                        "actions": [{"action": "fireball", "chance": 0.8, "role": "chain"}]}]

    class Rng:
        def __init__(self, v): self._v = v
        def random(self): return self._v
        def choice(self, s): return s[0]

    ai = MonsterAI(enemy, ACTION_LIB, Rng(0.9))  # 0.9 > 0.8 → 断链
    bs = {"turn": 1, "player": {"hp": 500, "max_hp": 500},
          "enemy": {"hp": 500, "max_hp": 1000}, "ai_state": {}}
    # 首次触发：断链登记冷却（cooldown 3 + 1 起算偏移 = 4）
    bs["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    ai.decide(bs)
    cd1 = bs["ai_state"]["chain_cooldowns"].get("molten", 0)
    assert cd1 >= 3, f"断链应登记冷却，实际 {cd1}"
    # 冷却中同链重触发：不缩短冷却（max 保留），不重置
    bs["ai_state"]["chain_cooldowns"]["molten"] = 4  # 模拟已有 4 回合冷却
    bs["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    ai.decide(bs)
    cd2 = bs["ai_state"]["chain_cooldowns"].get("molten", 0)
    assert cd2 == 4, f"冷却中重触发不得覆盖冷却，实际 {cd2}"


# ============ 4. 蓄力 intent 统一走 build_intent（batch2 P1-3） ============
def test_charge_intent_uses_build_intent():
    from qbot_rpg.core.monster_ai import MonsterAI

    ACTION_LIB = {"claw": {"id": "claw", "kind": "active", "power": 1.0, "tags": ["attack"]},
                  "doomsday": {"id": "doomsday", "kind": "active", "power": 4.0, "tags": ["attack"],
                               "charge_turns": 2, "charge_armor": True, "preview": True,
                               "preview_chain": ["claw"]}}
    enemy = {
        "id": "charge_drake", "name": "蓄力龙",
        "actions": [{"action": "claw", "probability": 1, "weight": 1},
                    {"action": "doomsday", "probability": 1, "weight": 0, "hungry": 1}],
        "special_actions": [], "chains": [],
        "ai": {"states": {}, "transitions": []},
    }

    class Rng:
        def __init__(self, v): self._v = v
        def random(self): return self._v
        def choice(self, s): return s[0]

    ai = MonsterAI(enemy, ACTION_LIB, Rng(0.001))  # hungry=1 强制蓄力
    bs = {"turn": 1, "player": {"hp": 500, "max_hp": 500},
          "enemy": {"hp": 500, "max_hp": 1000}, "ai_state": {}}
    r = ai.decide(bs)
    assert r.get("charging") is True, "蓄力起手"
    intent = bs["ai_state"]["intent"]
    # P1-3 修复：蓄力 intent 走 build_intent——preview 行动（无 reveal_condition 门禁）
    # 缺省解锁 → name_revealed=True 且 chain_preview 显示（不再硬编码 False）
    assert intent.get("name_revealed") is True, f"蓄力 intent 应走图鉴分级（name_revealed），实际 {intent}"
    assert intent.get("chain_preview") == ["claw"], f"L3 连锁预演应显示，实际 {intent.get('chain_preview')}"
    assert intent.get("category") == "charge" and intent.get("progress") == "1/2"


# ============ 5. combo_broken 一次性标记（batch3 P1-1） ============
def test_combo_broken_cleared_after_decision():
    from qbot_rpg.core.battle import BattleEngine
    from qbot_rpg.core.monster_ai import MonsterAI

    PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
              "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50,
              "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
    ENEMY = {"max_hp": 1000, "hp": 1000, "max_mp": 100, "mp": 100, "atk": 80, "dfn": 40,
             "mag": 30, "int": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "agi": 40,
             "spr": 40, "lck": 10, "elem_atk": 0, "pv": 300, "name": "E", "is_boss": False}
    ACTION_LIB = {"claw": {"id": "claw", "kind": "active", "power": 1.2, "attack_type": "斩", "tags": ["attack"]}}

    class ScriptedRng:
        def __init__(self, values): self._v = list(values); self.calls = 0
        def random(self):
            v = self._v[self.calls % len(self._v)]; self.calls += 1; return v
        def choice(self, seq): return seq[int(self.random() * len(seq)) % len(seq)]

    class QueueRNG:
        def __init__(self, vals): self._v = list(vals); self.i = 0
        def random(self): v = self._v[self.i % len(self._v)]; self.i += 1; return v

    enemy = {"id": "brute", "name": "蛮兽",
             "actions": [{"action": "claw", "probability": 1, "weight": 1}],
             "special_actions": [], "chains": [],
             "ai": {"states": {}, "transitions": []}}
    ai = MonsterAI(enemy, ACTION_LIB, ScriptedRng([0.5]))
    eng = BattleEngine(enemy_ai=ai)
    eng._rng = QueueRNG([0.5] * 16)
    eng.start(dict(PLAYER), dict(ENEMY), random_seed=1)

    # 模拟打断：置 combo_broken（_interrupt_enemy_ai 的行为）
    eng._snap["combo_broken"] = True
    eng._snap["ai_state"] = {"state": "normal", "exec_state": "idle"}
    # 怪物决策（本轮反击）后 combo_broken 应被清除
    eng.enemy_act(None)
    assert eng._snap.get("combo_broken") is None, "决策后 combo_broken 应清除（一次性标记）"
    # 下一回合决策不再命中（标记已清）
    eng._snap["ai_state"] = {"state": "normal", "exec_state": "idle"}
    eng.enemy_act(None)
    assert eng._snap.get("combo_broken") is None, "跨回合不残留 combo_broken"
