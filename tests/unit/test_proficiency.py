"""ProficiencyEngine 单测（M8 批1·路A）——细化_2c5a TC-01~TC-23 引擎可承载部分 + 关键规则正反例。

文件名：tests/unit/test_proficiency.py
创建时间：2026-08-29
作者：Hermes 子agent-1A
功能描述：qbot_rpg.core.proficiency.ProficiencyEngine 纯函数直测（对齐 test_shop_models /
test_formula_property 模式）：职业等级（TC-01/02/03）、经验来源（TC-05/08）、入账顺序与 SP 发放
（TC-09/10/11）、SP 面板（TC-13/14/15/16/18）、称号（TC-19/20/21/22）、存档校验（TC-26）。

依据：
  - docs/细化/细化_2c5a_职业等级与SP.md：LVL-01/02/04/05/06、EXP-02/03/06、SP-01/04/05/06、
    TTL-01/03/05/08、§5.1 JSON 样例、§5.3 玩家存档 schema、§七 TC-01~TC-26。
  - content/test_demo/proficiency.json（批0 落地数据）：真实样例兼容性。

【工程补白 · 注记】
  - TC-09「一次入账 350 熟练（跨 2 个阈值：300→700）」在本引擎「累计阈值 + 存档 exp=当前级内余量」
    口径下精确复现：起点 level 1（正式）/ 余量 250 → 入账 350 → 余量 600 跨阈值 300（相邻差 200）
    升精通、余量 400 跨阈值 700（相邻差 400）升专家 → 连跳 2 级、SP +2。用例即按该口径构造。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from qbot_rpg.core.proficiency import ProficiencyEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

# 细化 §5.1 JSON 样例形态（8 项 sp_panel，含特性位/复制/进化/挑战，覆盖 TC-15/17/18）
_ALCHEMY_ENTRY: Dict[str, Any] = {
    "id": "alchemy",
    "tier_names": ["见习", "正式", "精通", "专家", "大师", "宗师", "王"],
    "job_rank_levels": [0, 100, 300, 700, 1500, 3000, 6000],
    "exp_sources": {"craft": 1.0, "gather": 1.0, "combat": 1.0},
    "sp_per_level": 1,
    "sp_panel": [
        {"id": "quality_cap_10", "name": "品质上限+10", "cost": 1, "repeatable": True,
         "max_repeat": 5},
        {"id": "input_count_1", "name": "投入次数+1", "cost": 1, "repeatable": True,
         "max_repeat": 3},
        {"id": "trait_slot_1", "name": "特性位+1", "cost": 1, "repeatable": True,
         "max_repeat": 3},
        {"id": "unlock_copy", "name": "解锁复制", "cost": 1, "repeatable": False},
        {"id": "unlock_evolve", "name": "解锁进化", "cost": 1, "repeatable": False},
        {"id": "unlock_challenge", "name": "解锁挑战", "cost": 1, "repeatable": False},
        {"id": "gather_qty_1", "name": "采集量+1", "cost": 1, "repeatable": False},
        {"id": "chain_cap_1", "name": "连锁上限+1", "cost": 1, "repeatable": False},
    ],
    "energy": {"enabled": False, "max_by_tier": [5, 8, 10, 12, 15, 18, 20], "regen_sec": 1800},
    "job_tier_map": {
        "见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
        "大师": [31, 40], "宗师": [41, 50], "王": [51, 99],
    },
    "titles": [
        {"id": "contest_champion", "name": "品评冠军", "icon": "🏆", "source": "contest",
         "desc": "每周品评会冠军"}
    ],
}

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "job_tier_map": {
            "见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99],
        },
    },
}


def _engine(
    entries: Optional[Sequence[Mapping[str, Any]]] = None,
    settings: Optional[Mapping[str, Any]] = None,
) -> ProficiencyEngine:
    return ProficiencyEngine(entries, settings)


def _default_engine() -> ProficiencyEngine:
    """全默认（无条目、无 settings）→ 兜底 7 级/成长曲线/倍率 1.0/SP 面板 []。"""
    return _engine()


def _alchemy_engine(**overrides: Any) -> ProficiencyEngine:
    entry = copy.deepcopy(_ALCHEMY_ENTRY)
    entry.update(overrides)
    return _engine([entry], _DEFAULT_SETTINGS)


def _player() -> Dict[str, Any]:
    """新玩家状态 dict（角色 12 级，无 proficiency/title_state，TC-02 双尺基线）。"""
    return {"qid": "u1", "level": 12, "name": "测试者"}


def _player_with_prof(
    *, level: int = 0, exp: int = 0, sp_earned: int = 0, sp_used: int = 0,
    unlocks: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    p = _player()
    p["proficiency"] = {
        "alchemy": {
            "level": level, "exp": exp, "sp_earned": sp_earned, "sp_used": sp_used,
            "unlocks": dict(unlocks or {}),
        }
    }
    return p


# ---------------------------------------------------------------------------
# TC-01 七阶名链 / 内容包改名（LVL-01/02）
# ---------------------------------------------------------------------------
def test_tc01_tier_names_default_and_rename() -> None:
    """正例：默认 7 级见习→王；level=0 即见习；内容包改名全链显示新名。负例：越界钳制末档。"""
    eng = _default_engine()
    assert eng.tier_name("alchemy", 0) == "见习"
    assert eng.tier_name("alchemy", 1) == "正式"
    assert eng.tier_name("alchemy", 6) == "王"
    assert eng.tier_index_for_level("alchemy", 0) == 0
    assert eng.tier_index_for_level("alchemy", 6) == 6
    # 越界（等级 7+）→ 钳制到末档「王」（负例边界）
    assert eng.tier_index_for_level("alchemy", 99) == 6
    assert eng.tier_name("alchemy", 99) == "王"

    # 内容包改名（TC-01：内容包改名「学士/…/皇」→ 全链显示新名）
    eng2 = _alchemy_engine(tier_names=["学士", "工匠", "精通", "专家", "大师", "宗师", "皇"])
    assert eng2.tier_name("alchemy", 0) == "学士"
    assert eng2.tier_name("alchemy", 1) == "工匠"
    assert eng2.tier_name("alchemy", 6) == "皇"


# ---------------------------------------------------------------------------
# TC-02 双尺独立（LVL-04）
# ---------------------------------------------------------------------------
def test_tc02_dual_scale_independent() -> None:
    """正例：升职业等级不动角色等级；升角色等级不影响职业等级。"""
    eng = _alchemy_engine()
    p = _player_with_prof()  # 角色 12 级
    r = eng.gain_prof_exp(p, "alchemy", 100, source="craft")
    assert r["ok"] is True
    assert p["level"] == 12  # 角色等级不动（LVL-04 双尺独立）
    assert p["proficiency"]["alchemy"]["level"] == 1  # 职业等级独立升级

    # 角色等级变化不影响职业等级（两套尺子互不换算）
    p2 = _player_with_prof(level=3, exp=0)
    p2["level"] = 30
    r2 = eng.gain_prof_exp(p2, "alchemy", 10, source="craft")
    assert r2["ok"] is True
    assert p2["proficiency"]["alchemy"]["level"] == 3  # 10 < 100-0 未跨阈值


# ---------------------------------------------------------------------------
# TC-03 job_tier_map 区间校验（LVL-06）
# ---------------------------------------------------------------------------
def test_tc03_job_tier_map_range_positive_and_negative() -> None:
    """正例：正式（6-10）可调合 level 8；晋升精通（11-20）可调合 level 15。
    负例：正式不可调合 level 15。"""
    eng = _alchemy_engine()
    p_formal = _player_with_prof(level=1)  # 正式（6-10）
    assert eng.recipe_level_eligible(p_formal, "alchemy", 8) is True
    assert eng.recipe_level_eligible(p_formal, "alchemy", 15) is False  # TC-03 负例「等级不足」
    assert eng.recipe_level_eligible(p_formal, "alchemy", 5) is False  # 低于下界

    p_master = _player_with_prof(level=2)  # 精通（11-20）
    assert eng.recipe_level_eligible(p_master, "alchemy", 15) is True  # TC-03 晋升后同配方可调合


def test_tc03_job_tier_map_settings_main_and_entry_override() -> None:
    """LVL-06：主落点 settings.alchemy.job_tier_map；proficiency 条目可选覆盖
    （字段缺省=settings）。"""
    # 仅 settings（无条目）→ 用 settings 区间
    eng = _engine(settings=_DEFAULT_SETTINGS)
    p = _player_with_prof(level=1)
    assert eng.recipe_level_eligible(p, "alchemy", 8) is True
    assert eng.recipe_level_eligible(p, "alchemy", 15) is False

    # 条目覆盖 settings（正式 6-15）
    eng2 = _engine([{**_ALCHEMY_ENTRY, "job_tier_map": {
        "见习": [1, 5], "正式": [6, 15], "精通": [16, 25], "专家": [26, 35],
        "大师": [36, 45], "宗师": [46, 60], "王": [61, 99],
    }}], _DEFAULT_SETTINGS)
    assert eng2.recipe_level_eligible(p, "alchemy", 12) is True  # 覆盖后 12 ∈ 正式 6-15
    assert eng2.recipe_level_eligible(p, "alchemy", 16) is False


def test_tc03_recipe_level_invalid_conservative_reject() -> None:
    """负例：recipe_level 非正整数 → 保守拒绝 False（【工程补白】）。"""
    eng = _alchemy_engine()
    p = _player_with_prof(level=2)
    assert eng.recipe_level_eligible(p, "alchemy", 0) is False
    assert eng.recipe_level_eligible(p, "alchemy", -3) is False
    assert eng.recipe_level_eligible(p, "alchemy", True) is False  # bool 拒
    assert eng.recipe_level_eligible(p, "alchemy", "15") is False  # 非 int 拒


# ---------------------------------------------------------------------------
# TC-05 制作入账：合成经验 = 配方等级 ×1（EXP-03/CASC-01，引擎承载入账）
# ---------------------------------------------------------------------------
def test_tc05_synth_exp_recipe_level_gain_and_levelup() -> None:
    """正例：/合成 火焰弹（配方等级 5）→ 熟练 +5；累计达阈值 100 → 升「正式」。"""
    eng = _alchemy_engine()
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 5, source="craft")
    assert r["ok"] is True
    assert r["exp_gained"] == 5  # 配方等级×1（amount 由调用方按 EXP-03 口径传入）
    assert r["level"] == 0
    assert r["tier_from"] == r["tier_to"] == "见习"
    assert r["level_ups"] == 0
    assert r["sp_gained"] == 0

    # 累计达阈值 100 → 升「正式」（+升级公告数据由装配层据 level_ups 渲染）
    r2 = eng.gain_prof_exp(p, "alchemy", 95, source="craft")
    assert r2["ok"] is True
    assert r2["level"] == 1
    assert r2["level_ups"] == 1
    assert r2["sp_gained"] == 1
    assert r2["tier_from"] == "见习"
    assert r2["tier_to"] == "正式"
    # 返回 dict 键断言
    for key in ("ok", "exp_gained", "level", "tier_from", "tier_to", "sp_gained", "level_ups"):
        assert key in r2


# ---------------------------------------------------------------------------
# TC-08 三来源倍率可配（EXP-02）
# ---------------------------------------------------------------------------
def test_tc08_exp_sources_multiplier_craft_double() -> None:
    """正例：exp_sources.craft=2.0 → 制作经验翻倍（amount 5 → exp_gained 10）。"""
    eng = _alchemy_engine(exp_sources={"craft": 2.0, "gather": 1.0, "combat": 1.0})
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 5, source="craft")
    assert r["exp_gained"] == 10  # 5 × 2.0


def test_tc08_exp_sources_combat_zero() -> None:
    """正例：exp_sources.combat=0 → 战斗不再涨熟练（入账 0、不升级不发 SP）。"""
    eng = _alchemy_engine(exp_sources={"craft": 1.0, "gather": 1.0, "combat": 0.0})
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 999, source="combat")
    assert r["ok"] is True
    assert r["exp_gained"] == 0  # 999 × 0.0 → 0
    assert r["level_ups"] == 0
    assert r["level"] == 0
    assert r["sp_gained"] == 0


def test_tc08_exp_sources_unknown_source_default() -> None:
    """负例：未知来源 → 默认倍率 1.0（EXP-02 兜底，不拒绝）。"""
    eng = _alchemy_engine()
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 7, source="forging")
    assert r["ok"] is True
    assert r["exp_gained"] == 7


# ---------------------------------------------------------------------------
# TC-09 入账顺序与连跳 SP（EXP-06/LVL-05/SP-01）
# ---------------------------------------------------------------------------
def test_tc09_chain_level_up_sp_per_level() -> None:
    """正例：一次入账 350 跨 2 阈值（300→700）→ 连跳 2 级 + SP +2；先入账后升级再发 SP 可观测。"""
    eng = _alchemy_engine()
    # 起点：level 1（正式）/ 余量 250（【工程补白】口径：存档 exp = 当前级内余量）
    p = _player_with_prof(level=1, exp=250)
    r = eng.gain_prof_exp(p, "alchemy", 350, source="craft")
    assert r["ok"] is True
    assert r["exp_gained"] == 350
    assert r["level_ups"] == 2          # 跨阈值 300（需 200）与 700（需 400）→ 连跳 2 级
    assert r["level"] == 3              # 正式 → 专家
    assert r["tier_from"] == "正式"
    assert r["tier_to"] == "专家"
    assert r["sp_gained"] == 2          # 每级 sp_per_level=1 × 2 级
    # 存档落点：sp_earned=2、exp=当前级余量 0（1500-700 相邻差 400 恰好耗尽）
    assert p["proficiency"]["alchemy"]["sp_earned"] == 2
    assert p["proficiency"]["alchemy"]["exp"] == 0
    for key in ("ok", "exp_gained", "level", "tier_from", "tier_to", "sp_gained", "level_ups"):
        assert key in r


def test_tc09_gain_exp_invalid_amount() -> None:
    """负例：amount ≤ 0 / 非 int → 拒绝 {ok:False, reason:"exp_amount_invalid"}，不改存档。"""
    eng = _alchemy_engine()
    p = _player()
    for bad in (0, -5, True, "10", 3.5):
        r = eng.gain_prof_exp(p, "alchemy", bad, source="craft")  # type: ignore[arg-type]
        assert r["ok"] is False
        assert r["reason"] == "exp_amount_invalid"
    assert "proficiency" not in p  # 拒绝路径零副作用


# ---------------------------------------------------------------------------
# TC-10 sp_per_level 可配（SP-01）
# ---------------------------------------------------------------------------
def test_tc10_sp_per_level_two() -> None:
    """正例：sp_per_level=2 → 升 1 级 SP +2。"""
    eng = _alchemy_engine(sp_per_level=2)
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 100, source="craft")
    assert r["level_ups"] == 1
    assert r["sp_gained"] == 2
    assert p["proficiency"]["alchemy"]["sp_earned"] == 2


def test_tc10_sp_per_level_zero() -> None:
    """正例：sp_per_level=0 → 升级不发 SP（SP-01 范围 ≥0）。"""
    eng = _alchemy_engine(sp_per_level=0)
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 100, source="craft")
    assert r["level_ups"] == 1
    assert r["sp_gained"] == 0
    assert p["proficiency"]["alchemy"]["sp_earned"] == 0


# ---------------------------------------------------------------------------
# TC-11 未跨阈值不发 SP、SP 可跨级累积（SP-01）
# ---------------------------------------------------------------------------
def test_tc11_no_cross_no_sp_then_accumulate() -> None:
    """正例：99/100 未跨阈值 → 不升级、SP 不增加；SP 跨级累积（3 级攒 3 点，升级 +1 → 4 点）。"""
    eng = _alchemy_engine()
    p = _player()
    # 99/100：不升级、SP 不增加
    r = eng.gain_prof_exp(p, "alchemy", 99, source="craft")
    assert r["level_ups"] == 0
    assert r["sp_gained"] == 0
    assert p["proficiency"]["alchemy"]["level"] == 0
    assert p["proficiency"]["alchemy"]["sp_earned"] == 0
    # 跨阈值 100 → 升 1 级 +1 SP
    r = eng.gain_prof_exp(p, "alchemy", 1, source="craft")
    assert r["level_ups"] == 1
    assert r["sp_gained"] == 1
    # SP 可跨级累积：再升 2 级 → sp_earned 3（未消耗不归零）
    eng.gain_prof_exp(p, "alchemy", 200, source="craft")   # 精通（300）
    eng.gain_prof_exp(p, "alchemy", 400, source="craft")   # 专家（700）
    assert p["proficiency"]["alchemy"]["level"] == 3
    assert p["proficiency"]["alchemy"]["sp_earned"] == 3
    assert eng.sp_available(p, "alchemy") == 3
    # 再升 1 级 → 4 点
    eng.gain_prof_exp(p, "alchemy", 800, source="craft")   # 大师（1500）
    assert p["proficiency"]["alchemy"]["sp_earned"] == 4
    assert eng.sp_available(p, "alchemy") == 4


# ---------------------------------------------------------------------------
# TC-13 未购买不生效（SP-02：不是等级自动给）
# ---------------------------------------------------------------------------
def test_tc13_not_purchased_not_effective() -> None:
    """正例：仅升等级不购买 → 解锁计数仍 0（消费方据此判「品质上限仍 100」）；购买后计数 1。"""
    eng = _alchemy_engine()
    p = _player()
    # 升到精通（2 级）不购买 → 未生效
    eng.gain_prof_exp(p, "alchemy", 300, source="craft")
    assert eng.unlock_count(p, "alchemy", "quality_cap_10") == 0
    assert eng.sp_available(p, "alchemy") == 2  # SP 未消耗全部可用
    # 购买 1 次 → 生效（计数 1，消费方据此 +10 品质上限）
    r = eng.unlock_item(p, "alchemy", "quality_cap_10")
    assert r["ok"] is True
    assert r["unlock_count"] == 1
    assert eng.unlock_count(p, "alchemy", "quality_cap_10") == 1
    assert eng.sp_available(p, "alchemy") == 1


# ---------------------------------------------------------------------------
# TC-14 sp_used 双计 + 重载不重复扣点（SP-06）
# ---------------------------------------------------------------------------
def test_tc14_sp_used_double_count_and_reload_no_double_spend() -> None:
    """正例：解锁 → SP 1→0、sp_used 0→1（sp_earned=1 不变）；重载存档 → 不重复扣点、状态一致。"""
    eng = _alchemy_engine()
    p = _player_with_prof(sp_earned=1)
    r = eng.unlock_item(p, "alchemy", "quality_cap_10")
    assert r["ok"] is True
    node = p["proficiency"]["alchemy"]
    assert node["sp_earned"] == 1  # 累计发放不变
    assert node["sp_used"] == 1    # 累计消耗 0→1
    assert eng.sp_available(p, "alchemy") == 0
    for key in ("ok", "sp_used_delta", "unlock_count", "panel_id", "panel_name"):
        assert key in r

    # 重载存档（JSON round-trip 等价：deepcopy 重建玩家状态）→ 状态一致
    p_reloaded = copy.deepcopy(p)
    r2 = eng.unlock_item(p_reloaded, "alchemy", "quality_cap_10")
    assert r2["ok"] is False
    assert r2["reason"] == "sp_insufficient"  # 不重复扣点
    assert p_reloaded["proficiency"]["alchemy"]["sp_used"] == 1
    assert eng.unlock_count(p_reloaded, "alchemy", "quality_cap_10") == 1
    # 存档校验通过（sp_used == sp_earned）
    assert eng.validate_load(p_reloaded) == []


# ---------------------------------------------------------------------------
# TC-15 特性位上限（SP-03/TC-15）
# ---------------------------------------------------------------------------
def test_tc15_trait_slot_max_repeat() -> None:
    """正例：特性位+1 购买 3 次 → 计数 3（消费方 3→6）；第 4 次 → max_repeat_reached。"""
    eng = _alchemy_engine()
    p = _player_with_prof(sp_earned=5)
    for i in range(3):
        r = eng.unlock_item(p, "alchemy", "trait_slot_1")
        assert r["ok"] is True
        assert r["unlock_count"] == i + 1
    assert eng.unlock_count(p, "alchemy", "trait_slot_1") == 3
    r4 = eng.unlock_item(p, "alchemy", "trait_slot_1")
    assert r4["ok"] is False
    assert r4["reason"] == "max_repeat_reached"
    assert eng.unlock_count(p, "alchemy", "trait_slot_1") == 3  # 拒绝不改计数


# ---------------------------------------------------------------------------
# TC-16 SP 不足拒绝（SP-05）
# ---------------------------------------------------------------------------
def test_tc16_sp_insufficient_reject() -> None:
    """正例：SP=0 → 解锁任意项 → 拒绝并提示 SP 不足（reason:"sp_insufficient"）。"""
    eng = _alchemy_engine()
    p = _player_with_prof()  # sp_earned=0
    r = eng.unlock_item(p, "alchemy", "quality_cap_10")
    assert r["ok"] is False
    assert r["reason"] == "sp_insufficient"
    assert eng.unlock_count(p, "alchemy", "quality_cap_10") == 0
    assert "sp_used" not in p["proficiency"]["alchemy"] or \
        p["proficiency"]["alchemy"]["sp_used"] == 0  # 拒绝零副作用


# ---------------------------------------------------------------------------
# TC-18 解锁计数（SP-03，供其它系统消费）
# ---------------------------------------------------------------------------
def test_tc18_unlock_count_consumption() -> None:
    """正例：采集量+1 / 连锁上限+1 解锁计数 1（消费方据此加产出/连锁段数）；
    非 repeatable 二次拒绝。"""
    eng = _alchemy_engine()
    p = _player_with_prof(sp_earned=4)
    r = eng.unlock_item(p, "alchemy", "gather_qty_1")
    assert r["ok"] is True
    assert eng.unlock_count(p, "alchemy", "gather_qty_1") == 1
    r2 = eng.unlock_item(p, "alchemy", "gather_qty_1")
    assert r2["ok"] is False
    assert r2["reason"] == "not_repeatable"  # repeatable=false 已购 → 拒绝（SP-03 单次）
    r3 = eng.unlock_item(p, "alchemy", "chain_cap_1")
    assert r3["ok"] is True
    assert eng.unlock_count(p, "alchemy", "chain_cap_1") == 1
    # repeatable 项可多次计数
    r4 = eng.unlock_item(p, "alchemy", "quality_cap_10")
    r5 = eng.unlock_item(p, "alchemy", "quality_cap_10")
    assert r4["ok"] is True and r5["ok"] is True
    assert eng.unlock_count(p, "alchemy", "quality_cap_10") == 2


def test_tc18_panel_not_found() -> None:
    """负例：面板项不存在 → {ok:False, reason:"panel_not_found"}；空面板职业同理。"""
    eng = _alchemy_engine()
    p = _player_with_prof(sp_earned=3)
    r = eng.unlock_item(p, "alchemy", "no_such_panel")
    assert r["ok"] is False
    assert r["reason"] == "panel_not_found"
    # 未配置职业（默认面板 []）→ 拒绝
    eng2 = _default_engine()
    r2 = eng2.unlock_item(p, "alchemy", "quality_cap_10")
    assert r2["ok"] is False
    assert r2["reason"] == "panel_not_found"
    assert eng2.sp_panel_defs("alchemy") == []


def test_tc18_sp_panel_defs_normalization() -> None:
    """正例：sp_panel_defs 归一 {id,name,cost,repeatable,max_repeat,desc}；缺省字段兜底。"""
    eng = _alchemy_engine()
    defs = eng.sp_panel_defs("alchemy")
    assert len(defs) == 8
    d = {x["id"]: x for x in defs}
    assert set(d["quality_cap_10"].keys()) == {
        "id", "name", "cost", "repeatable", "max_repeat", "desc"}
    assert d["quality_cap_10"] == {
        "id": "quality_cap_10", "name": "品质上限+10", "cost": 1,
        "repeatable": True, "max_repeat": 5, "desc": "",
    }
    assert d["unlock_copy"]["repeatable"] is False
    assert d["unlock_copy"]["max_repeat"] == 1  # 【工程补白 5】非 repeatable 默认 1


# ---------------------------------------------------------------------------
# TC-19 图鉴全亮授王（TTL-01/03）
# ---------------------------------------------------------------------------
def test_tc19_grant_king_all_lit() -> None:
    """正例：图鉴全点亮 → 授「炼金王」（title id=职业 ID，TTL-03），
    自动进可佩戴列表；幂等不重复。"""
    eng = _alchemy_engine()
    p = _player()
    r = eng.grant_king_title(p, "alchemy", codex_all_lit=True)
    assert r["ok"] is True
    assert r["granted"] is True
    assert r["title_id"] == "alchemy"
    for key in ("ok", "granted", "title_id"):
        assert key in r
    assert eng.owned_titles(p) == ["alchemy"]
    # 重复授予 → 幂等 {ok:True, granted:False}
    r2 = eng.grant_king_title(p, "alchemy", codex_all_lit=True)
    assert r2["ok"] is True
    assert r2["granted"] is False
    assert eng.owned_titles(p) == ["alchemy"]


# ---------------------------------------------------------------------------
# TC-20 图鉴未亮不授（TTL-01：王条件与等级区间解耦）
# ---------------------------------------------------------------------------
def test_tc20_king_not_granted_when_codex_incomplete() -> None:
    """正例：图鉴未全亮（即使等级在王区间）→ 不授王称号（reason:"codex_incomplete"）。"""
    eng = _alchemy_engine()
    p = _player_with_prof(level=6, exp=0)  # 王区间但图鉴未亮（TC-20 负例）
    r = eng.grant_king_title(p, "alchemy", codex_all_lit=False)
    assert r["ok"] is False
    assert r["reason"] == "codex_incomplete"
    assert eng.owned_titles(p) == []


# ---------------------------------------------------------------------------
# TC-21 双职业王并存（TTL-01 不唯一、按职业独立授予）
# ---------------------------------------------------------------------------
def test_tc21_dual_king_titles_coexist() -> None:
    """正例：炼金+钓鱼图鉴均全亮 → 炼金王+钓鱼王并存，互不冲突。"""
    eng = _alchemy_engine()
    p = _player()
    assert eng.grant_king_title(p, "alchemy", codex_all_lit=True)["granted"] is True
    assert eng.grant_king_title(p, "fishing", codex_all_lit=True)["granted"] is True
    assert eng.owned_titles(p) == ["alchemy", "fishing"]


# ---------------------------------------------------------------------------
# TC-22 佩戴替换 1 槽（TTL-05）
# ---------------------------------------------------------------------------
def test_tc22_equip_replace_single_slot() -> None:
    """正例：佩戴炼金王 → 前缀渲染「炼金王」；再佩戴品评冠军 → 替换式顶掉；取消佩戴 → 空。"""
    eng = _alchemy_engine()
    p = _player()
    eng.grant_king_title(p, "alchemy", codex_all_lit=True)
    ts = p["title_state"]
    # 三来源共用：冠军称号手工入列表（TTL-04 由装配层注册）
    ts["owned"] = ["alchemy", "contest_champion"]

    r = eng.equip_title(p, "alchemy")
    assert r["ok"] is True
    assert r["equipped"] == "alchemy"
    assert p["title_state"]["equipped"] == "alchemy"
    for key in ("ok", "equipped", "replaced"):
        assert key in r

    r2 = eng.equip_title(p, "contest_champion")
    assert r2["ok"] is True
    assert r2["equipped"] == "contest_champion"
    assert r2["replaced"] == "alchemy"  # 替换式顶掉（1 槽）
    assert p["title_state"]["equipped"] == "contest_champion"

    # 取消佩戴 → equipped 空（前缀渲染为空，TC-22）
    r3 = eng.equip_title(p, None)
    assert r3["ok"] is True
    assert r3["equipped"] is None
    assert p["title_state"]["equipped"] is None


def test_tc22_equip_not_owned_reject() -> None:
    """负例：佩戴未拥有称号 → {ok:False, reason:"title_not_owned"}。"""
    eng = _alchemy_engine()
    p = _player()
    r = eng.equip_title(p, "alchemy")
    assert r["ok"] is False
    assert r["reason"] == "title_not_owned"
    assert "equipped" not in p.get("title_state", {}) or p["title_state"]["equipped"] is None


# ---------------------------------------------------------------------------
# TC-26 存档校验（SP-06）
# ---------------------------------------------------------------------------
def test_tc26_validate_load_clean_and_corrupt() -> None:
    """正例：合法存档（sp_used ≤ sp_earned）→ 问题列表空；sp_used > sp_earned → 报出该职业。"""
    eng = _alchemy_engine()
    p = _player_with_prof(level=4, exp=850, sp_earned=4, sp_used=2,
                          unlocks={"quality_cap_10": 2, "trait_slot_1": 1})  # 细化 §5.3 存档例
    assert eng.validate_load(p) == []

    p2 = _player_with_prof(sp_earned=1, sp_used=2)  # 超支（重放/双扣痕迹）
    problems = eng.validate_load(p2)
    assert len(problems) == 1
    prob = problems[0]
    assert prob["job_id"] == "alchemy"
    assert prob["sp_earned"] == 1
    assert prob["sp_used"] == 2
    for key in ("job_id", "sp_earned", "sp_used"):
        assert key in prob
    # 无 proficiency 段 / 非 dict 玩家 → 空
    assert eng.validate_load(_player()) == []
    assert eng.validate_load("not-a-player") == []


def test_tc26_invalid_player_guards() -> None:
    """负例：非 dict 玩家入参 → 各方法保守拒绝/零值（不抛异常）。"""
    eng = _alchemy_engine()
    assert eng.gain_prof_exp("x", "alchemy", 10)["ok"] is False
    assert eng.gain_prof_exp("x", "alchemy", 10)["reason"] == "invalid_player"
    assert eng.sp_available("x", "alchemy") == 0
    assert eng.unlock_count("x", "alchemy", "a") == 0
    assert eng.owned_titles("x") == []
    assert eng.validate_load("x") == []
    assert eng.recipe_level_eligible("x", "alchemy", 5) is False


# ---------------------------------------------------------------------------
# 批0 落地数据兼容（content/test_demo/proficiency.json 真实样例形态）
# ---------------------------------------------------------------------------
def test_real_proficiency_json_compat() -> None:
    """正例：引擎构造兼容批0 真实样例（7 级 tier_names / job_rank_levels / exp_sources / sp_panel /
    energy enabled=false / job_tier_map / titles），并跑通入账/解锁核心路径。"""
    path = Path(__file__).resolve().parents[2] / "content" / "test_demo" / "proficiency.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 1
    eng = _engine(data, _DEFAULT_SETTINGS)

    entry = data[0]
    assert eng.tier_name("alchemy", 0) == entry["tier_names"][0] == "见习"
    assert eng.tier_name("alchemy", 6) == "王"
    # 成长曲线 + 档位（LVL-05）
    p = _player()
    r = eng.gain_prof_exp(p, "alchemy", 100, source="craft")
    assert r["ok"] is True and r["level"] == 1
    # 真实 job_tier_map 覆盖 settings（正式 6-15）：level 1 可调合 level 12、不可调合 level 5
    assert eng.recipe_level_eligible(p, "alchemy", 12) is True
    assert eng.recipe_level_eligible(p, "alchemy", 5) is False
    # 真实 sp_panel（4 项，gather_qty_1 repeatable=false / max_repeat=1）
    defs = eng.sp_panel_defs("alchemy")
    assert len(defs) == 4
    gq = {d["id"]: d for d in defs}["gather_qty_1"]
    assert gq["repeatable"] is False and gq["max_repeat"] == 1
    p2 = _player_with_prof(sp_earned=2)
    ru = eng.unlock_item(p2, "alchemy", "gather_qty_1")
    assert ru["ok"] is True
    assert eng.unlock_count(p2, "alchemy", "gather_qty_1") == 1
    assert eng.unlock_item(p2, "alchemy", "gather_qty_1")["reason"] == "not_repeatable"
