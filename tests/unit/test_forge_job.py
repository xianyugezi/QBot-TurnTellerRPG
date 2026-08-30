"""M9 锻造·批3·路3A：铸造职业门槛+熟练计价+经验明细单元测试（tests/unit/test_forge_job.py）。

文件名：test_forge_job.py
创建时间：2026-08-30
作者：Hermes 子agent-3A（M9 锻造实现组批3·路3A：并发同仓，仅新建本文件 +
  qbot_rpg/core/forge_job.py；proficiency.json 的 forge 实例由并发路3B 补充 sp_panel，
  本路只读消费——不改动批0/批1/批2 既有文件与兄弟路文件）

依据：docs/细化/细化_2c2d_锻造套装与客制.md §3.1（CAST 表：见习1-5→王51+，可锻上限=
  职业等级 L213）+ 定稿 §10.1 L213/L214（熟练节点×2）+ 细化_2c5a（LVL/EXP 通用机制）+
  docs/m9_shared_contract.md §三（exp_per_forge）+ content/test_demo/proficiency.json
  （forge 实例：job_rank_levels [0,100,300,700,1500,3000,6000]，7 级见习→王）。
测试目标：qbot_rpg.core.forge_job.{forge_prof_node, forge_level, level_gate_met,
  forge_exp_for, gain_forge_exp, exp_to_next, rank_name, configure_proficiency}。

覆盖矩阵：
  A 节点与等级：forge_prof_node 缺省创建 / forge_level 缺省 0 / 非 Mapping 兜底
  B 等级门槛（L213）：职业等级 5 可锻节点 5（见习区间上限）ok / 职业等级 10 可锻
    节点 6-10（正式区间）ok / 越级拒（need/current/missing）/ 非法 node_level 拒
  C 经验计价（L214）：节点 8×2=16；exp_per_forge 可配 int=3 → 24、str「节点等级×3」
    → 24；非法 node_level → 0
  D 入账升级（EXP-01 craft）：gain_forge_exp 多次入账 → 升级 + SP + 见习→正式；
    返回引擎结果 dict（exp_gained/level/tier_from/tier_to/sp_gained/level_ups）
  E 经验明细：exp_to_next 缺口（还差 N）/ 已满级 maxed
  F 档位名：rank_name 见习→正式→王
  G 真实 proficiency.json：forge 实例存在且字段合规（tier_names 7 级见习→王 /
    job_rank_levels 对齐 alchemy / exp_sources craft=1.0 / sp_per_level=1）

铁律：零 NoneBot import；纯函数确定性；零定时器探针合规（M43：docstring 不写睡眠/定时器
      字样）；不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from qbot_rpg.core.forge_job import (
    FORGE_JOB_ID,
    configure_proficiency,
    exp_to_next,
    forge_exp_for,
    forge_level,
    forge_prof_node,
    gain_forge_exp,
    level_gate_met,
    rank_name,
)

# 仓库根 = tests/unit/test_forge_job.py 上溯两级
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROF_JSON = _REPO_ROOT / "content" / "test_demo" / "proficiency.json"

# 成长曲线（对齐 alchemy / forge 实例默认形态，proficiency.py _DEFAULT_RANK_LEVELS）
_RANKS = (0, 100, 300, 700, 1500, 3000, 6000)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _player(level: int = 0, exp: int = 0) -> dict:
    """构造带 forge 节点的玩家 dict（对齐 proficiency dict 形态）。"""
    return {"proficiency": {"forge": {"level": level, "exp": exp,
                                      "sp_earned": 0, "sp_used": 0, "unlocks": {}}}}


# ===========================================================================
# A 节点与等级
# ===========================================================================
def test_forge_prof_node_creates_default() -> None:
    player: dict = {}
    node = forge_prof_node(player)
    assert node == {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}
    assert player["proficiency"]["forge"] is node


def test_forge_prof_node_returns_existing() -> None:
    player = _player(level=7)
    node = forge_prof_node(player)
    assert node is not None
    assert node is player["proficiency"]["forge"]
    assert node["level"] == 7


def test_forge_prof_node_non_mapping_none() -> None:
    assert forge_prof_node(None) is None
    assert forge_prof_node("str") is None


def test_forge_level_default_zero() -> None:
    assert forge_level({}) == 0
    assert forge_level(None) == 0
    assert forge_level({"proficiency": {"forge": {"level": "x"}}}) == 0


def test_forge_level_reads_node() -> None:
    assert forge_level(_player(level=5)) == 5
    assert forge_level(_player(level=0)) == 0


# ===========================================================================
# B 等级门槛（定稿 §10.1 L213：节点 level ≤ 职业等级 → ok）
# ===========================================================================
def test_level_gate_apprentice_node5_ok() -> None:
    # 见习区间上限：职业等级 5 可锻节点等级 5（5 ≤ 5）
    res = level_gate_met(_player(level=5), 5)
    assert res == {"ok": True, "need": 5, "current": 5, "missing": 0}


def test_level_gate_formal_nodes_6_to_10_ok() -> None:
    # 正式区间：职业等级 10 可锻节点等级 6 / 10（6≤10 / 10≤10）
    for nlv in (6, 10):
        res = level_gate_met(_player(level=10), nlv)
        assert res["ok"] is True, nlv
        assert res["need"] == nlv
        assert res["current"] == 10
        assert res["missing"] == 0


def test_level_gate_over_level_rejected() -> None:
    # 越级拒：职业等级 5 锻节点 6 → 还差 1；锻节点 12 → 还差 7
    res = level_gate_met(_player(level=5), 6)
    assert res == {"ok": False, "reason": "level_insufficient",
                   "need": 6, "current": 5, "missing": 1}
    res = level_gate_met(_player(level=5), 12)
    assert res == {"ok": False, "reason": "level_insufficient",
                   "need": 12, "current": 5, "missing": 7}


def test_level_gate_default_level_zero_rejects() -> None:
    # 无 forge 节点（职业等级 0）锻任意 level≥1 节点 → 拒
    res = level_gate_met({}, 1)
    assert res == {"ok": False, "reason": "level_insufficient",
                   "need": 1, "current": 0, "missing": 1}


def test_level_gate_invalid_node_level_rejected() -> None:
    for bad in (0, -1, "5", True, None):
        res = level_gate_met(_player(level=5), bad)
        assert res["ok"] is False, bad
        assert res["reason"] == "invalid_node_level"
        assert res["current"] == 5
        assert res["missing"] == 0


# ===========================================================================
# C 经验计价（定稿 L214：熟练节点×2，exp_per_forge 可配）
# ===========================================================================
def test_forge_exp_default_node8_is_16() -> None:
    assert forge_exp_for(8, None) == 16
    assert forge_exp_for(8, {}) == 16


def test_forge_exp_int_coeff() -> None:
    # exp_per_forge=3 → 节点 8 × 3 = 24
    settings = {"forge": {"exp_per_forge": 3}}
    assert forge_exp_for(8, settings) == 24


def test_forge_exp_str_formula() -> None:
    settings = {"forge": {"exp_per_forge": "节点等级×3"}}
    assert forge_exp_for(8, settings) == 24
    # 纯数字串 / 段内数字亦可解析
    assert forge_exp_for(8, {"forge": {"exp_per_forge": "×5"}}) == 40


def test_forge_exp_invalid_node_level_zero() -> None:
    assert forge_exp_for(0, None) == 0
    assert forge_exp_for(-3, None) == 0
    assert forge_exp_for("8", None) == 0
    assert forge_exp_for(True, None) == 0


def test_forge_exp_settings_segment_direct() -> None:
    # forge 段本身（含 FORGE_SETTINGS_KEYS 任一键）亦兼容
    assert forge_exp_for(8, {"exp_per_forge": 4}) == 32


# ===========================================================================
# D 入账升级（EXP-01 craft 来源，委托 ProficiencyEngine）
# ===========================================================================
def test_gain_forge_exp_credits_and_levels_up() -> None:
    player = _player(level=0)
    # 节点 8 → 每件 16 exp；7 件 = 112 ≥ 100（0→1 阈值差）→ 升 1 级余量 12
    last: dict = {}
    for _ in range(7):
        last = gain_forge_exp(player, 8, None)
        assert last["ok"] is True
    assert last["exp_gained"] == 16
    assert last["level"] == 1
    assert last["tier_from"] == "见习"
    assert last["tier_to"] == "正式"
    assert last["sp_gained"] == 1
    assert last["level_ups"] == 1
    assert forge_level(player) == 1
    assert player["proficiency"]["forge"]["exp"] == 112 - _RANKS[1]
    assert player["proficiency"]["forge"]["sp_earned"] == 1


def test_gain_forge_exp_multi_level_jump() -> None:
    # 大额一次入账连跳：节点 150 → 300 exp → 0→1（100）+1→2（200）→ level 2 余量 0
    player = _player(level=0)
    res = gain_forge_exp(player, 150, None)
    assert res["ok"] is True
    assert res["level"] == 2
    assert res["level_ups"] == 2
    assert res["sp_gained"] == 2
    assert res["tier_to"] == "精通"
    assert forge_level(player) == 2


def test_gain_forge_exp_invalid_node_level_rejected() -> None:
    player = _player(level=0)
    res = gain_forge_exp(player, 0, None)
    assert res["ok"] is False
    assert res["reason"] == "exp_amount_invalid"
    assert forge_level(player) == 0


def test_gain_forge_exp_default_prof_node_created() -> None:
    # 无 forge 节点的玩家入账 → 缺省创建节点
    player: dict = {}
    res = gain_forge_exp(player, 8, None)
    assert res["ok"] is True
    assert player["proficiency"]["forge"]["exp"] == 16


# ===========================================================================
# E 经验明细（exp_to_next：「还差 N 熟练」）
# ===========================================================================
def test_exp_to_next_gap() -> None:
    # level 0 / exp 0 → 本级阈值差 100，还差 100
    res = exp_to_next(_player(level=0, exp=0))
    assert res["ok"] is True
    assert res["level"] == 0
    assert res["exp"] == 0
    assert res["cost"] == 100
    assert res["missing"] == 100
    assert res["rank"] == "见习"
    assert res["next_rank"] == "正式"
    assert res["maxed"] is False

    # level 1 / exp 12 → 阈值差 200（300-100），还差 188
    res = exp_to_next(_player(level=1, exp=12))
    assert res["cost"] == 200
    assert res["missing"] == 188
    assert res["rank"] == "正式"
    assert res["next_rank"] == "精通"


def test_exp_to_next_maxed() -> None:
    # 王（末档 level 6）→ 无缺口
    res = exp_to_next(_player(level=6, exp=0))
    assert res["ok"] is True
    assert res["maxed"] is True
    assert res["cost"] == 0
    assert res["missing"] == 0
    assert res["next_rank"] is None
    assert res["rank"] == "王"


def test_exp_to_next_default_node() -> None:
    res = exp_to_next({})
    assert res["level"] == 0
    assert res["exp"] == 0
    assert res["missing"] == 100


# ===========================================================================
# F 档位名（rank_name：见习→正式→王）
# ===========================================================================
def test_rank_name_tiers() -> None:
    assert rank_name(_player(level=0)) == "见习"
    assert rank_name(_player(level=1)) == "正式"
    assert rank_name(_player(level=2)) == "精通"
    assert rank_name(_player(level=6)) == "王"


def test_rank_name_default_apprentice() -> None:
    assert rank_name({}) == "见习"
    assert rank_name(None) == "见习"


# ===========================================================================
# G 真实 proficiency.json：forge 实例合规 + configure_proficiency 注入
# ===========================================================================
def test_real_proficiency_json_forge_instance() -> None:
    profs = cast(list, _load_json(_PROF_JSON))
    forge = next((e for e in profs if e.get("id") == FORGE_JOB_ID), None)
    assert forge is not None, "proficiency.json 缺 forge 实例"
    assert forge["tier_names"] == ["见习", "正式", "精通", "专家", "大师", "宗师", "王"]
    assert forge["job_rank_levels"] == list(_RANKS)  # 对齐 alchemy 模式
    assert forge["exp_sources"].get("craft") == 1.0
    assert forge["sp_per_level"] == 1


def test_configure_proficiency_injects_forge() -> None:
    profs = cast(list, _load_json(_PROF_JSON))
    engine = configure_proficiency(profs)
    assert engine is not None
    # 注入后：forge 职业等级缺省 0、rank 见习；入账升级走真实曲线
    player: dict = {}
    res = gain_forge_exp(player, 8, None)
    assert res["ok"] is True
    assert res["tier_from"] == "见习"
    assert forge_level(player) == 0
    assert player["proficiency"]["forge"]["exp"] == 16
