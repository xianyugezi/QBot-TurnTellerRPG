"""升级引擎单测（M6 批次1·路A · qbot_rpg/core/levelup.py）——TC-LVL-01~06 全量 + 配置注入补充。

依据：细化_M6_三引擎与基础指令（D1）§一（LVL-01~LVL-12 / TC-LVL-01~TC-LVL-06）；
【规则】L293（levelup 必测：经验曲线边界 0 经验/满级不增长/升级回满 HP/MP）；
【3b】§1.1 白值口径（白值 = base + growth×(lv-1) + 自由加点）；【2c5a】SP-01（每级 SP）。

测试风格对齐 tests/unit/test_basic_commands.py：纯 pytest、零 NoneBot、断言具体行为。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.levelup import LevelUpEngine
from qbot_rpg.data.player import PlayerAttributes


def make_lvl_player(**over):
    """构造 LevelUpEngine 消费的玩家状态 dict（ctx 玩家表示，可变）。"""
    base = {
        "level": 1,
        "exp": 0,
        "hp": 100,
        "mp": 30,
        "job_id": "warrior",
        "attributes": PlayerAttributes(
            base={"hp": 100.0, "mp": 30.0, "str": 15.0, "con": 10.0}
        ),
    }
    base.update(over)
    return base


def _sp(player, job="warrior"):
    """proficiency.<job>.sp_earned（缺省 0）。"""
    prof = (player.get("proficiency") or {}).get(job) or {}
    return prof.get("sp_earned", 0)


# ---------------------------------------------------------------------------
# TC-LVL-01 0 经验边界（LVL-02）
# ---------------------------------------------------------------------------
def test_tc_lvl_01_zero_exp_boundary():
    """TC-LVL-01：gain_exp(player, 0) / gain_exp(player, -5) → 幂等拒绝，exp/level 不变，无升级事件。"""
    eng = LevelUpEngine()
    player = make_lvl_player()

    r0 = eng.gain_exp(player, 0)
    assert r0["ok"] is False and r0["reason"] == "exp_amount_invalid"

    rn = eng.gain_exp(player, -5)
    assert rn["ok"] is False and rn["reason"] == "exp_amount_invalid"

    assert player["exp"] == 0 and player["level"] == 1
    assert "proficiency" not in player          # 无 SP 发放落点产生
    # 布尔/非 int 同样幂等拒绝（LVL-02 精神：非法入账一律拒绝）
    assert eng.gain_exp(player, True)["reason"] == "exp_amount_invalid"
    assert eng.gain_exp(player, "100")["reason"] == "exp_amount_invalid"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TC-LVL-02 满级不增长（LVL-03）
# ---------------------------------------------------------------------------
def test_tc_lvl_02_cap_no_growth():
    """TC-LVL-02：level=cap=45 时入账 10000 → exp 不增长、level 仍 45、无回满/重算副作用。"""
    eng = LevelUpEngine(level_cap=45)
    player = make_lvl_player(level=45, exp=1200, hp=5, mp=2)

    r = eng.gain_exp(player, 10000)

    assert r["ok"] is True
    assert r["level_ups"] == 0
    assert r["exp_next"] == 0                 # LVL-11：满级 exp_next=0
    assert player["level"] == 45 and player["exp"] == 1200  # 经验不增长
    assert player["hp"] == 5 and player["mp"] == 2          # 无回满副作用
    assert "proficiency" not in player                      # 无 SP 发放


# ---------------------------------------------------------------------------
# TC-LVL-03 升级回满（LVL-05/LVL-07）
# ---------------------------------------------------------------------------
def test_tc_lvl_03_level_up_full_heal():
    """TC-LVL-03：level=3 hp=5/100 mp=2/30 入账 100（跨阈值 300）→ level=4、exp 扣减阈值、
    hp/mp 回满、sp_earned +sp_per_level。"""
    eng = LevelUpEngine()  # exp_curve 默认 100×lv → 升 4 级需 300；sp_per_level=1
    player = make_lvl_player(level=3, exp=200, hp=5, mp=2)

    r = eng.gain_exp(player, 100)

    assert r["ok"] is True
    assert r["level"] == 4 and r["level_ups"] == 1
    assert player["level"] == 4
    assert player["exp"] == 0                 # 300-300=0：exp 扣减阈值
    assert player["hp"] == 100 and player["mp"] == 30     # 回满（上限=重算后最终属性）
    assert r["hp_restored"] == 95 and r["mp_restored"] == 28
    assert _sp(player) == 1                   # sp_earned +sp_per_level（默认 1）
    assert r["sp_earned_delta"] == 1
    assert r["exp_next"] == 400               # exp_to_next(4)=100×4


# ---------------------------------------------------------------------------
# TC-LVL-04 跨级与 exp_next（LVL-04/LVL-11）
# ---------------------------------------------------------------------------
def test_tc_lvl_04_multi_level_and_exp_next():
    """TC-LVL-04：单次入账连升 2 级 → 逐级结算、SP 按级数发放、返回 exp_next=exp_to_next(新级)。

    注（D1 TC-LVL-04 示例数值修正）：D1 原文「level=4 exp=395 +300」在默认曲线
    100×lv（阈值 400/500/600）下仅够升 1 级（695-400=295 < 500），无法连升 2 级；
    为使用例真正覆盖「跨级连升」行为，改用 exp=600 +500（→1100：-400=700→-500=200），
    行为断言（连升 2 级 / SP+2 / exp_next=exp_to_next(6)）与 D1 完全一致。
    """
    eng = LevelUpEngine()
    player = make_lvl_player(level=4, exp=600, hp=5, mp=2)

    r = eng.gain_exp(player, 500)

    assert r["ok"] is True
    assert r["level"] == 6 and r["level_ups"] == 2
    assert player["level"] == 6 and player["exp"] == 200   # 1100-400-500=200
    assert r["sp_earned_delta"] == 2                       # 每级 1 SP，共 2
    assert _sp(player) == 2
    assert r["exp_next"] == 600                            # exp_to_next(6)=100×6
    # 多级连升只在最后一级结算后回满一次（LVL-05）
    assert player["hp"] == 100 and player["mp"] == 30
    assert r["hp_restored"] == 95


# ---------------------------------------------------------------------------
# TC-LVL-05 换职业不重算（LVL-06）
# ---------------------------------------------------------------------------
def test_tc_lvl_05_job_change_does_not_recalc():
    """TC-LVL-05：战士 lv=10 str 白值 15+1.5×9=28.5；换职业后白值仍 28.5（不加点不重算）。"""
    eng = LevelUpEngine(growth={"str": 1.5})  # 职业成长率 jobs.json 可配（F-05）
    player = make_lvl_player(level=1, exp=0)

    r = eng.gain_exp(player, 5000)  # 阈值和=100+…+900=4500 → 连升 9 级至 lv=10
    assert r["level_ups"] == 9 and player["level"] == 10
    assert player["attributes"].base["str"] == pytest.approx(15.0 + 1.5 * 9)  # 28.5

    # 换职业（job_id 变更）→ 白值不重算（【3b】L174 精神）
    player["job_id"] = "mage"
    assert player["attributes"].base["str"] == pytest.approx(28.5)


# ---------------------------------------------------------------------------
# TC-LVL-06 自由加点校验（LVL-08）
# ---------------------------------------------------------------------------
def test_tc_lvl_06_allocate_point_validation():
    """TC-LVL-06：allocate_point(player, "str", 2) → base.str=17；非法属性拒绝并提示属性不存在。"""
    eng = LevelUpEngine()
    player = make_lvl_player()  # base.str=15

    r = eng.allocate_point(player, "str", 2)
    assert r["ok"] is True and r["base"] == 17.0
    assert player["attributes"].base["str"] == 17.0

    r_bad = eng.allocate_point(player, "no_such", 1)
    assert r_bad["ok"] is False
    assert r_bad["reason"] == "attr_not_found"
    assert "属性不存在" in r_bad["message"]     # LVL-E3 文案

    # amount < 1 拒绝（LVL-08：amount ≥ 1）
    assert eng.allocate_point(player, "str", 0)["reason"] == "invalid_amount"


# ---------------------------------------------------------------------------
# 补充：配置注入（LVL-01/LVL-03/LVL-07 构造器注入路径）
# ---------------------------------------------------------------------------
def test_supplement_custom_curve_cap_and_sp():
    """配置注入：dict 曲线 / 自定义 level_cap / sp_per_level 均生效（D1 B-1 兜底可覆盖）。"""
    eng = LevelUpEngine(
        exp_curve={1: 50, 2: 60}, level_cap=3, sp_per_level=2,
        growth={"hp": 5.0},
    )
    player = make_lvl_player(level=1, exp=45, hp=5, mp=2)

    r = eng.gain_exp(player, 10)  # 45+10=55 ≥ exp_to_next(1)=50 → 升 2 级
    assert r["level_ups"] == 1 and player["level"] == 2 and player["exp"] == 5
    assert r["sp_earned_delta"] == 2 and _sp(player) == 2
    # 满级 cap=3 拦截（LVL-03）
    player["level"] = 3
    r2 = eng.gain_exp(player, 999)
    assert r2["level_ups"] == 0 and r2["exp_next"] == 0
    assert player["level"] == 3 and player["exp"] == 5


def test_supplement_curve_dict_missing_level_fallback():
    """dict 曲线表越界 → 默认 100×lv 兜底（工程补白，防表越界崩溃）。"""
    eng = LevelUpEngine(exp_curve={1: 50})
    player = make_lvl_player()
    assert eng.exp_next(1) == 50
    assert eng.exp_next(5) == 500  # 表无 5 → 默认 100×5
