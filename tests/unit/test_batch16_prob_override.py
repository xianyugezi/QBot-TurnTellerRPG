"""批16 · #10 行动概率/权重「使用处 > 定义处」覆盖测试（框架/引擎层，通用）。

依据：`docs/编辑器修改意见0915_台账与方案.md` §批 4 #10 已定口径——
  · 定义处（`action.json` 的 `probability` / `weight`）保留为**默认值**；
  · 使用处（怪物 AI 行动表 `enemies.json.actions[]`）声明可覆盖；
  · 取值顺序 **使用处 > 定义处 > 缺省**；
  · 无覆盖时与修前逐字段一致（同一场景跑两遍 0 差异）；
  · 接入点 `MonsterAI._random_pool`（入池闸门）与 `MonsterAI._weight_for`（权重基准）。

本测试不写死任何业务模块/字段名；行动 id/敌人配置全部为本测试合成。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.core.monster_ai import IDLE, NORMAL, MonsterAI

# ------------------------------------------------------------------ 合成行动库 / 敌人
# 定义处（action.json 语义）：
#   alpha：定义处是锚点（probability 0）且 weight 7 → 被使用处覆盖
#   beta ：定义处 probability 1 / weight 30 → 使用处不写，取定义处默认
#   gamma：定义处既无 probability 也无 weight → 与修前逐字段一致（不入池 / 权重 1.0）
#   delta：定义处 probability 1 → 使用处显式 0 覆盖（锚点）
DEFS: Dict[str, Dict[str, Any]] = {
    "alpha": {"id": "alpha", "tags": ["attack"], "probability": 0, "weight": 7},
    "beta": {"id": "beta", "tags": ["attack"], "probability": 1, "weight": 30},
    "gamma": {"id": "gamma", "tags": ["attack"]},
    "delta": {"id": "delta", "tags": ["attack"], "probability": 1, "weight": 50},
}

ENEMY = {
    "id": "e", "name": "e",
    "actions": [
        {"action": "alpha", "probability": 1, "weight": 40},   # 覆盖定义处锚点 + 权重
        {"action": "beta"},                                    # 使用处不写 → 定义处默认
        {"action": "gamma", "weight": 10},                     # 定义处无 probability → 不入池
        {"action": "delta", "probability": 0, "weight": 99},   # 显式 0 覆盖定义处 1
    ],
    "special_actions": [], "chains": [], "ai": {"states": {}, "transitions": []},
}


class _Rng:
    def random(self) -> float:
        return 0.5


def _new_state() -> dict:
    ai = {"state": NORMAL, "exec_state": IDLE, "phase": 1, "chain_pos": 0, "chain_queue": [],
          "chain_id": None, "chain_cooldowns": {}, "charge": None, "trigger_cooldowns": {},
          "action_cooldowns": {}, "hungry_count": {}, "intent": {}, "forced_queue": [],
          "boss_phase": 1}
    return {"turn": 1, "player": {"hp": 500, "max_hp": 500},
            "enemy": {"hp": 100, "max_hp": 100, "pv": 10}, "ai_state": ai}


def _ai() -> MonsterAI:
    return MonsterAI(ENEMY, DEFS, _Rng())


# ------------------------------------------------------------------ 修前参考实现（对拍基线）
def _legacy_pool(actions, cooldowns):
    """修前 L6 池：只看使用处 probability（缺省 0）。"""
    return [e["action"] for e in actions
            if float(e.get("probability", 0)) > 0
            and int(cooldowns.get(e.get("action"), 0)) <= 0]


def _legacy_weight(entry):
    """修前权重基准：只看使用处 weight（缺省 1.0）。"""
    w = entry.get("weight")
    return float(w) if w is not None else 1.0


# ------------------------------------------------------------------ 一、使用处覆盖定义处
def test_use_site_probability_and_weight_override_definition() -> None:
    ai = _ai()
    bs = _new_state()
    pool = [e["action"] for e in ai._random_pool(bs["ai_state"], bs)]
    # alpha 使用处 probability=1 覆盖定义处 0 → 入池；delta 使用处显式 0 覆盖定义处 1 → 出池
    assert pool == ["alpha", "beta"], pool
    # alpha 使用处 weight=40 覆盖定义处 7
    entry = next(e for e in ENEMY["actions"] if e["action"] == "alpha")
    assert ai._weight_for(entry, bs["ai_state"], bs) == 40.0
    # beta 使用处不写 → 定义处 weight=30 作默认
    beta = next(e for e in ENEMY["actions"] if e["action"] == "beta")
    assert ai._weight_for(beta, bs["ai_state"], bs) == 30.0


def test_probabilities_follow_override_order() -> None:
    probs = _ai().pool_probabilities(_new_state())
    assert set(probs) == {"alpha", "beta"}
    assert abs(probs["alpha"] - 40 / 70) < 1e-9, probs
    assert abs(probs["beta"] - 30 / 70) < 1e-9, probs


# ------------------------------------------------------------------ 二、无覆盖对拍 0 差异
def test_no_override_scenario_identical_to_legacy_and_deterministic() -> None:
    ai = _ai()
    actions = ENEMY["actions"]
    cooldowns: Dict[str, int] = {}
    # 同场景跑两遍 → 0 差异（确定性）
    run1 = _ai().pool_probabilities(_new_state())
    run2 = _ai().pool_probabilities(_new_state())
    assert run1 == run2

    # 与「修前逐字段一致」对拍：修前只看使用处的池/权重。
    # 覆盖场景下「使用处声明了值」的条目（alpha / delta）应与修前完全一致：
    legacy_pool = _legacy_pool(actions, cooldowns)
    assert "alpha" in legacy_pool and "delta" not in legacy_pool
    for aid in ("alpha",):
        entry = next(e for e in actions if e["action"] == aid)
        assert ai._weight_for(entry, _new_state()["ai_state"], _new_state()) == \
            _legacy_weight(entry)
    # 使用处与定义处都没有该键（gamma 的 probability）→ 与修前一致：不入池
    assert "gamma" not in legacy_pool
    assert "gamma" not in run1


def test_missing_everywhere_matches_pre_change_defaults() -> None:
    # 定义处/使用处都无 probability（gamma）→ 默认 0（不入池）、weight 默认 1.0
    ai = _ai()
    gamma = next(e for e in ENEMY["actions"] if e["action"] == "gamma")
    assert ai._param(gamma, "probability", 0) == 0
    assert ai._param(gamma, "weight", None) == 10  # 使用处声明了 weight，取使用处
    bare = {"action": "gamma"}                     # 两处都没有 → 缺省
    assert ai._param(bare, "probability", 0) == 0
    assert ai._param(bare, "weight", None) is None
    assert ai._weight_for(bare, _new_state()["ai_state"], _new_state()) == 1.0


def test_definition_only_entry_enters_pool_by_default() -> None:
    # 使用处完全不声明 → 定义处 probability/weight 作为默认值生效
    enemy = {"actions": [{"action": "beta"}], "special_actions": [], "chains": [],
             "ai": {"states": {}, "transitions": []}}
    ai = MonsterAI(enemy, DEFS, _Rng())
    bs = _new_state()
    assert [e["action"] for e in ai._random_pool(bs["ai_state"], bs)] == ["beta"]
    probs = ai.pool_probabilities(bs)
    assert probs == {"beta": 1.0}


def test_explicit_zero_use_site_still_wins() -> None:
    # 显式 0 是有效覆盖（不是「未声明」）
    ai = _ai()
    bs = _new_state()
    delta = next(e for e in ENEMY["actions"] if e["action"] == "delta")
    assert ai._param(delta, "probability", None) == 0
    assert "delta" not in [e["action"] for e in ai._random_pool(bs["ai_state"], bs)]


# ------------------------------------------------------------------ 三、印记侧无需改动（事实核查）
def test_marks_json_has_no_probability_keys() -> None:
    """印记（marks.json）无概率/权重类键 → 印记侧无需改动（若有则本断言提醒补实现）。"""
    content = Path(__file__).resolve().parents[2] / "content"
    marks_files = sorted(content.glob("*/marks.json"))
    assert marks_files, "未发现任何 marks.json（内容目录结构变化？）"
    prob_like = ("prob", "weight", "chance", "rate")
    for path in marks_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else list(data.values())
        for row in rows:
            if not isinstance(row, dict):
                continue
            hits = [k for k in row if any(s in str(k).lower() for s in prob_like)]
            assert not hits, f"{path.name} 出现概率类键 {hits}：印记侧需补「使用处覆盖」实现"
