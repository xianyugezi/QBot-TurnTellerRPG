"""批29 · ②：α4 条件集补齐（新增 `level` / `job` / `quest` 三类条件）回归 + 端到端。

背景：批27 结论——「同技按条件换形态」已由 `skill_chains` 步骤 + `mode:"replace"`
（`core/combo._resolve_derivation` 路径 c）等价表达，但条件集只有 combo 既有条件
（count / hp% / 状态 / round / 印记 / 方位），缺 level / job / quest。批29 按用户拍板
「12 做」补齐，**严格沿用同一条件对象形态与同一求值入口**（`core/combo.py::
evaluate_condition` + `ConditionCtx`），不新开条件系统。

覆盖：
  A. 三类新条件的求值语义（纯函数，含边界与安全失败）；
  B. **回归对拍**：既有条件（count/hp%/状态/round/印记/方位 + and/or/not）逐字段判定
     与冻结期望一致；不带新条件 → 行为不变；
  C. **端到端（临时内容根）**：临时内容根 → `load_pack`（含校验）→ `_battle_defs` →
     `BattleEngine.do_action`；level 满足放进阶技、不满足放基础技；job / quest 各一条
     数值/状态级证据。

测试只建临时内容根（tmp_path），绝不写真实内容包。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pytest

from qbot_rpg.commands.battle_launch_commands import _battle_defs, _player_combatant
from qbot_rpg.content.loader import load_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ConditionCtx, evaluate_condition


# =====================================================================================
# A. 三类新条件求值语义（纯函数）
# =====================================================================================
def _ctx(**over: Any) -> ConditionCtx:
    return ConditionCtx(**over)


def test_level_condition_ops_and_boundary() -> None:
    c = _ctx(level=10)
    assert evaluate_condition({"level": {"min": 10}}, c) is True   # 边界含
    assert evaluate_condition({"level": {"max": 10}}, c) is True
    assert evaluate_condition({"level": {"eq": 10}}, c) is True
    assert evaluate_condition({"level": 10}, c) is True            # 裸整数 = eq 简写
    assert evaluate_condition({"level": {"min": 11}}, c) is False
    assert evaluate_condition({"level": {"eq": 9}}, c) is False
    assert evaluate_condition({"level": {"min": 1}}, _ctx(level=0)) is False


def test_job_condition_in_and_not_in() -> None:
    sw = _ctx(job="swordsman")
    assert evaluate_condition({"job": {"in": ["swordsman"]}}, sw) is True
    assert evaluate_condition({"job": {"in": ["mage"]}}, sw) is False
    assert evaluate_condition({"job": {"not_in": ["mage"]}}, sw) is True
    assert evaluate_condition({"job": {"not_in": ["swordsman"]}}, sw) is False
    # 集合外语义的「与」：in 与 not_in 同现须都成立
    assert evaluate_condition({"job": {"in": ["swordsman"], "not_in": ["mage"]}}, sw) is True
    assert evaluate_condition({"job": {"in": ["swordsman"], "not_in": ["swordsman"]}}, sw) is False
    # 未设置职业 → 恒不满足（安全失败，非「集合外也满足」）
    assert evaluate_condition({"job": {"in": ["swordsman"]}}, _ctx()) is False
    assert evaluate_condition({"job": {"not_in": ["mage"]}}, _ctx()) is False
    # 形态非法 → 不满足
    assert evaluate_condition({"job": ["swordsman"]}, sw) is False
    assert evaluate_condition({"job": {"x": ["swordsman"]}}, sw) is False


def test_quest_condition_three_states() -> None:
    ctx = _ctx(quest_active=frozenset({"q_run"}),
               quest_completed=frozenset({"q_done"}))
    assert evaluate_condition({"quest": {"q_run": {"state": "in_progress"}}}, ctx) is True
    assert evaluate_condition({"quest": {"q_done": {"state": "completed"}}}, ctx) is True
    assert evaluate_condition({"quest": {"q_new": {"state": "not_started"}}}, ctx) is True
    # 状态不匹配 → 不满足
    assert evaluate_condition({"quest": {"q_run": {"state": "completed"}}}, ctx) is False
    assert evaluate_condition({"quest": {"q_done": {"state": "not_started"}}}, ctx) is False
    # 多任务 = 全部满足（AND）
    assert evaluate_condition(
        {"quest": {"q_run": {"state": "in_progress"}, "q_done": {"state": "completed"}}},
        ctx) is True
    assert evaluate_condition(
        {"quest": {"q_run": {"state": "in_progress"}, "q_new": {"state": "completed"}}},
        ctx) is False
    # 枚举非法 / 结构非法 → 不满足（安全失败）
    assert evaluate_condition({"quest": {"q_run": {"state": "doing"}}}, ctx) is False
    assert evaluate_condition({"quest": {"q_run": {}}}, ctx) is False
    assert evaluate_condition({"quest": {}}, ctx) is False


def test_new_conditions_nest_in_combinations() -> None:
    """三类新条件与 and/or/not 任意拓扑组合（沿用同一递归入口）。"""
    ctx = _ctx(level=12, job="swordsman",
               quest_completed=frozenset({"q_main"}))
    cond = {"and": [
        {"level": {"min": 10}},
        {"or": [{"job": {"in": ["mage"]}},
                {"quest": {"q_main": {"state": "completed"}}}]},
        {"not": {"level": {"max": 5}}},
    ]}
    assert evaluate_condition(cond, ctx) is True


# =====================================================================================
# B. 回归对拍：既有条件逐字段判定一致（冻结期望，防新键影响旧口径）
# =====================================================================================
def _marks_lookup(_mkey: str, _which: str, _rule: Mapping[str, Any],
                  _mid: Optional[str]) -> bool:
    return True


_BASE_CTX = ConditionCtx(
    count=3, target_hp_pct=50.0,
    self_statuses=frozenset({"st_a"}), target_statuses=frozenset({"st_b"}),
    round_=3,
    positions={"self": {"side": "front", "height": "ground"},
               "target": {"side": "back", "height": "air"}},
)

_FROZEN: List[Any] = [
    ({}, True),
    ({"count": 3}, True),
    ({"count": {"eq": 3}}, True),
    ({"count": {"min": 3}}, True),
    ({"count": {"max": 2}}, False),
    ({"target_hp_pct": {"max": 50}}, True),
    ({"target_hp_pct": {"min": 50}}, True),
    ({"target_hp_pct": {"min": 51}}, False),
    ({"self_status": {"has": ["st_a"]}}, True),
    ({"self_status": {"has": ["st_x"]}}, False),
    ({"target_status": {"has": ["st_b"]}}, True),
    ({"round": {"eq": 3}}, True),
    ({"round": {"min": 4}}, False),
    ({"position_match": {"which": "self", "side": ["front"], "height": ["ground"]}}, True),
    ({"position_match": {"which": "target", "side": ["front"]}}, False),
    ({"unknown_key": 1}, False),
    ({"and": [{"count": {"eq": 3}}, {"target_hp_pct": {"max": 50}}]}, True),
    ({"or": [{"count": {"eq": 9}}, {"round": {"eq": 3}}]}, True),
    ({"not": {"count": {"eq": 9}}}, True),
]


def test_existing_conditions_identical_field_by_field() -> None:
    """对拍断言：既有条件判定与冻结期望逐条一致（本批不得改变旧口径）。"""
    got = [(cond, evaluate_condition(cond, _BASE_CTX, _marks_lookup)) for cond, _ in _FROZEN]
    assert got == _FROZEN


def test_marks_conditions_unchanged_with_lookup() -> None:
    """印记条件：有接线 → 交 marks_lookup；无接线 → 安全失败（既有口径不变）。"""
    assert evaluate_condition({"marks_total": {"min": 2}}, _BASE_CTX, _marks_lookup) is True
    assert evaluate_condition({"self_marks": {"m1": {"min": 5}}}, _BASE_CTX, _marks_lookup) is True
    assert evaluate_condition({"marks_total": {"min": 2}}, _BASE_CTX, None) is False


def test_condition_ctx_new_fields_have_safe_defaults() -> None:
    """ConditionCtx 新字段缺省 = 安全失败口径；不影响既有字段缺省。"""
    c = ConditionCtx()
    assert (c.count, c.target_hp_pct, c.round_) == (0, 100.0, 1)
    assert (c.level, c.job) == (0, "")
    assert not c.quest_active and not c.quest_completed


# =====================================================================================
# C. 端到端（临时内容根）：临时包 → load_pack（含校验）→ BattleEngine 形态替换
# =====================================================================================
def _write_pack(root: Path) -> Path:
    d = root / "pack_cond"
    d.mkdir()
    modules: Dict[str, Any] = {
        "manifest.json": {"name": "pack_cond", "version": "1", "schema_version": 1,
                          "modules": ["jobs", "quest", "skills", "skill_chains"]},
        "jobs.json": [{"id": "swordsman", "name": "剑士"}, {"id": "mage", "name": "法师"}],
        "quest.json": [{"id": "q_main", "name": "主线"}, {"id": "q_side", "name": "支线"}],
        "skills.json": [
            {"id": "basic_atk", "name": "普攻", "type": "basic", "kind": "damage", "power": 50},
            {"id": "base_lv", "name": "基础等级式", "type": "active", "kind": "damage",
             "power": 100, "chain_refs": ["lv_chain"]},
            {"id": "adv_lv", "name": "进阶等级式", "type": "active", "kind": "damage",
             "power": 400},
            {"id": "base_job", "name": "基础职业式", "type": "active", "kind": "damage",
             "power": 100, "chain_refs": ["job_chain"]},
            {"id": "adv_job", "name": "进阶职业式", "type": "active", "kind": "damage",
             "power": 400},
            {"id": "base_quest", "name": "基础任务式", "type": "active", "kind": "damage",
             "power": 100, "chain_refs": ["quest_chain"]},
            {"id": "adv_quest", "name": "进阶任务式", "type": "active", "kind": "damage",
             "power": 400},
        ],
        "skill_chains.json": [
            {"id": "lv_chain", "name": "等级演化", "trigger_skill": "base_lv",
             "max_combo": 1, "max_combo_behavior": "reset",
             "steps": [{"from": "base_lv", "to": "adv_lv", "mode": "replace",
                        "condition": {"level": {"min": 10}}}]},
            {"id": "job_chain", "name": "职业演化", "trigger_skill": "base_job",
             "max_combo": 1, "max_combo_behavior": "reset",
             "steps": [{"from": "base_job", "to": "adv_job", "mode": "replace",
                        "condition": {"job": {"in": ["swordsman"]}}}]},
            {"id": "quest_chain", "name": "任务演化", "trigger_skill": "base_quest",
             "max_combo": 1, "max_combo_behavior": "reset",
             "steps": [{"from": "base_quest", "to": "adv_quest", "mode": "replace",
                        "condition": {"quest": {"q_main": {"state": "completed"}}}}]},
        ],
    }
    for name, data in modules.items():
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


@pytest.fixture(scope="module")
def cond_pack(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """临时内容根建包 → load_pack（校验通过才返回；三新条件合法 → 0 红拦）。"""
    root = tmp_path_factory.mktemp("b29cond")
    return asyncio.run(load_pack(_write_pack(root)))


_ENEMY = {"hp": 9999, "max_hp": 9999, "mp": 0, "max_mp": 0, "atk": 0, "dfn": 0,
          "spd": 1, "name": "桩"}


def _engine(pack: Any, *, level: int, job_id: str = "",
            quest_active: Optional[Mapping[str, Any]] = None,
            quest_completed: Optional[List[str]] = None) -> BattleEngine:
    all_defs, _chains, ce = _battle_defs(pack.registry)
    eng = BattleEngine(defs=all_defs, registry=pack.registry, combo_engine=ce)
    player = {"qid": "p1", "name": "玩家", "level": level, "hp": 3000, "max_hp": 3000,
              "mp": 200, "max_mp": 200, "attributes": {"base": {"atk": 100.0}}}
    ctx: Dict[str, Any] = {"player": player, "job_id": job_id}
    if quest_active is not None:
        ctx["quest_active"] = quest_active
    if quest_completed is not None:
        ctx["quest_completed"] = quest_completed
    eng.start(_player_combatant(ctx), dict(_ENEMY), random_seed=7)
    return eng


def _form(eng: BattleEngine, skill_id: str) -> Dict[str, Any]:
    out = eng.do_action("player", {"type": "skill", "skill_id": skill_id})
    assert out.ok is True, out
    combo = out.combo_result if isinstance(out.combo_result, Mapping) else {}
    return {"form_id": combo.get("form_id"), "derived": combo.get("derived"),
            "damage": out.final_damage}


# ---- level：满足 → 进阶技；不满足 → 基础技（前后证据） ----
def test_e2e_level_condition_switches_form(cond_pack: Any) -> None:
    low = _form(_engine(cond_pack, level=9), "base_lv")
    high = _form(_engine(cond_pack, level=10), "base_lv")
    assert low["form_id"] is None, low              # 不满足 → 基础技（零改写）
    assert high["form_id"] == "adv_lv", high        # 满足 → 自动替换为进阶技
    assert high["derived"] is True and high["damage"] > low["damage"], (low, high)


# ---- job：命中集合内 → 进阶技；集合外 → 基础技（状态级证据） ----
def test_e2e_job_condition_switches_form(cond_pack: Any) -> None:
    hit = _form(_engine(cond_pack, level=1, job_id="swordsman"), "base_job")
    miss = _form(_engine(cond_pack, level=1, job_id="mage"), "base_job")
    assert hit["form_id"] == "adv_job", hit
    assert miss["form_id"] is None, miss
    assert hit["damage"] > miss["damage"], (hit, miss)


# ---- quest：已完成 → 进阶技；进行中 / 未接取 → 基础技（三态证据） ----
def test_e2e_quest_condition_switches_form(cond_pack: Any) -> None:
    done = _form(_engine(cond_pack, level=1, quest_completed=["q_main"]), "base_quest")
    running = _form(_engine(cond_pack, level=1, quest_active={"q_main": {"name": "主线"}}),
                    "base_quest")
    untouched = _form(_engine(cond_pack, level=1), "base_quest")
    assert done["form_id"] == "adv_quest", done
    assert running["form_id"] is None and untouched["form_id"] is None, (running, untouched)


def test_e2e_pack_conditions_pass_content_validation(cond_pack: Any) -> None:
    """临时包经 load_pack 校验通过（含新 validator 对 level/job/quest 的红拦口径）。"""
    raw = cond_pack.registry.modules_raw
    assert len(raw.get("skill_chains", [])) == 3


def test_e2e_existing_condition_step_unaffected(cond_pack: Any) -> None:
    """既有条件（无新键）链在临时包里仍按旧口径工作（不带新条件 → 行为不变）。"""
    all_defs, _chains, ce = _battle_defs(cond_pack.registry)
    chain = dict(next(c for c in cond_pack.registry.modules_raw["skill_chains"]
                      if c["id"] == "lv_chain"))
    chain["id"] = "hp_chain"
    chain["trigger_skill"] = "base_job"
    chain["steps"] = [{"from": "base_job", "to": "adv_job", "mode": "replace",
                       "condition": {"target_hp_pct": {"max": 50}}}]
    defs = dict(all_defs)
    defs["hp_chain"] = chain
    defs["base_job"] = {**defs["base_job"], "chain_refs": ["hp_chain"]}
    ce2 = type(ce)(defs={**defs, "hp_chain": chain}, resolver=lambda i, k: defs.get(i))
    eng = BattleEngine(defs=defs, registry=cond_pack.registry, combo_engine=ce2)
    eng.start(_player_combatant({"player": {"qid": "p1", "name": "玩家", "level": 1,
                                            "hp": 3000, "max_hp": 3000, "mp": 200,
                                            "max_mp": 200,
                                            "attributes": {"base": {"atk": 100.0}}}}),
              {"hp": 40, "max_hp": 100, "mp": 0, "max_mp": 0, "atk": 0, "dfn": 0,
               "spd": 1, "name": "残血桩"}, random_seed=7)
    out = eng.do_action("player", {"type": "skill", "skill_id": "base_job"})
    assert (out.combo_result or {}).get("form_id") == "adv_job", out.combo_result


# =====================================================================================
# D. 校验（红拦）：比较符合法 / 阈值范围 / 引用 ∈ jobs·quest / 状态枚举
# =====================================================================================
def _vchain(condition: Any, *, jobs: Any = None, quest: Any = None) -> Dict[str, Any]:
    mods: Dict[str, Any] = {
        "skill_chains": [{"id": "c1", "trigger_skill": "s1",
                          "steps": [{"from": "s1", "to": "s2", "mode": "replace",
                                     "condition": condition}]}],
    }
    if jobs is not None:
        mods["jobs"] = jobs
    if quest is not None:
        mods["quest"] = quest
    return mods


def _rules(condition: Any, *, jobs: Any = None, quest: Any = None) -> List[str]:
    from qbot_rpg.content.skill_validator import validate_skill_chains

    report: Dict[str, Any] = {"errors": [], "warnings": []}
    validate_skill_chains(_vchain(condition, jobs=jobs, quest=quest), report)
    return [rec.get("rule", "") for rec in report["errors"]]


def test_validator_accepts_valid_new_conditions_and_existing_keys() -> None:
    assert _rules({"level": {"min": 10}}, jobs=[{"id": "j1"}], quest=[{"id": "q1"}]) == []
    assert _rules({"job": {"in": ["j1"]}}, jobs=[{"id": "j1"}],
                  quest=[{"id": "q1"}]) == []
    assert _rules({"quest": {"q1": {"state": "completed"}}}, jobs=[{"id": "j1"}],
                  quest=[{"id": "q1"}]) == []
    # 既有条件键（count/状态/round/印记/方位）不产生任何红拦（零影响）
    assert _rules({"count": {"eq": 3}, "round": {"min": 1},
                   "self_status": {"has": ["st"]},
                   "position_match": {"which": "self"}}) == []


def test_validator_level_op_and_threshold_red() -> None:
    assert "level_op_invalid" in _rules({"level": {"gt": 10}})
    assert "level_threshold_invalid" in _rules({"level": {"min": 0}})
    assert "level_threshold_invalid" in _rules({"level": {"eq": 1.5}})
    assert "level_threshold_invalid" in _rules({"level": {"max": True}})
    assert "level_op_invalid" in _rules({"level": {"min": 1, "eq": 2, "x": 3}})
    assert "level_shape" in _rules({"level": []})


def test_validator_job_ref_red() -> None:
    assert "job_ref_missing" in _rules({"job": {"in": ["ghost"]}}, jobs=[{"id": "j1"}])
    # 表缺失 → 引用不存在（红拦）
    assert "job_ref_missing" in _rules({"job": {"in": ["j1"]}})
    assert "job_op_invalid" in _rules({"job": {"has": ["j1"]}}, jobs=[{"id": "j1"}])
    assert "job_set_invalid" in _rules({"job": {"in": []}}, jobs=[{"id": "j1"}])


def test_validator_quest_ref_and_state_red() -> None:
    assert "quest_ref_missing" in _rules({"quest": {"ghost": {"state": "completed"}}},
                                         quest=[{"id": "q1"}])
    assert "quest_ref_missing" in _rules({"quest": {"q1": {"state": "completed"}}})
    assert "quest_state_invalid" in _rules({"quest": {"q1": {"state": "doing"}}},
                                           quest=[{"id": "q1"}])
    assert "quest_state_key_invalid" in _rules({"quest": {"q1": {"st": "completed"}}},
                                               quest=[{"id": "q1"}])
    assert "quest_state_shape" in _rules({"quest": {"q1": "completed"}}, quest=[{"id": "q1"}])


def test_validator_walks_nested_combinations() -> None:
    cond = {"and": [{"count": {"eq": 3}},
                    {"not": {"quest": {"ghost": {"state": "completed"}}}}]}
    assert "quest_ref_missing" in _rules(cond, quest=[{"id": "q1"}])


def test_check_pack_red_flags_bad_job_ref() -> None:
    """内容侧整包校验：悬空 job 引用 → V-9 红拦（loader 聚合拒绝加载）。"""
    from qbot_rpg.content.validator import check_pack

    report = check_pack(_vchain({"job": {"in": ["ghost"]}}, jobs=[{"id": "j1"}]))
    assert any(e.kind == "V-9" and e.detail.get("rule") == "job_ref_missing"
               for e in report.errors), report.errors

