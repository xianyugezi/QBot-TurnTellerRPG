"""炼金 /确认 品质结算引擎单测（M8 批5·路2 · qbot_rpg/core/alchemy_settle.py）。

文件：tests/unit/test_alchemy_settle.py
创建：2026-08-29
作者：Hermes 子agent-5-2
功能：SettleEngine 引擎单测——全量复核/品质均值聚合/档位系数/上限叠加/刻度降级/触媒消耗/
      产出入包（quality+tier+traits）/熟练经验/终态幂等 + /放弃。ctx 直测（items/recipe 注册表 +
      count_item/remove_item/add_item hook + player + fake session_mgr），零 IO 零 NoneBot。

依据：docs/m8_contract_指令契约.md §5（GU-19/F-05/M-05/§10 铁律 3）+
      docs/m8_contract_核心机制.md §四（QLT-06/08/10/04）+ §7.2（version 幂等）+ §10.3 +
      docs/细化/细化_2c4e_品质与特性.md 五（TC-02/03/05/08/09/15/20）+
      docs/细化/细化_2c4f_投料触媒与能量条.md（CAT-04 触媒消耗默认 true / TC-20）。
规则出处以引擎模块注释为准（QLT/GU/F/CAT/EXP 编号 + 定稿/细化行号）。

覆盖矩阵（每条正例 + 反例，断言精确数值/字段）：
  TC-02  品质均值聚合（70/70/80 → 73；round-half-up；无 quality 材料按 0 兜底 Q-S1）
  TC-03  档位系数（史诗×1.2 / 传说×1.5 / 普通×0.8 → 效果数值 base_effects ×coef，QLT-04）
  TC-05  品质上限叠加（SP quality_cap_10×N + 快照 core_cap/challenge_cap → 超配方原上限仍 ≤100）
  TC-08  刻度未达标降一档（火 4/5 → 降 1 档；达标 → 不降，QLT-10）
  TC-09  传说全不达标降至普通封底（3 档全缺 → 降 3 档至 common 仍出货不吞材料）
  TC-15  标准版无特性（快照无 traits → produced.traits=[]；快照带 traits → 写入，LAY-04a/Q-S9）
  TC-20  触媒消耗（catalyst_consume=true 扣 1；false 不扣；触媒移走 → 全量复核拒+差异）
  反例   材料不足全拒+差异短清单、背包零变更、无产出
  产出   成品带 quality=tier 键 + tier + traits + effects/scaled_effects
  熟练   熟练经验=配方等级×1（prof.gain_prof_exp source='craft'，EXP-03）
  幂等   message_id 首调 ok → 二次「已结算」（fake session_mgr 模拟 settle_alchemy，ATO-04/Q-S7）
  /放弃  材料不结算零背包改动、终态 'abandon'、重复放弃「已放弃」

测试风格对齐 tests/unit/test_alchemy_core.py / test_quality.py：纯 pytest（asyncio_mode=auto，
async 测试自动跑事件循环）、断言精确 dict 字段、ctx 直测零 IO。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from qbot_rpg.core.alchemy_settle import (
    SETTLE_ABANDON,
    SETTLE_CONFIRM,
    SP_QUALITY_CAP_10,
    SettleEngine,
)
from qbot_rpg.core.proficiency import ProficiencyEngine

# ---------------------------------------------------------------------------
# 测试数据（items/recipe 注册表，对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------


def _items() -> Dict[str, dict]:
    """测试物品注册表（quality 支持数值分 int / 档位键 str / 无 quality 三种形态）。"""
    return {
        "mat_q70": {"id": "mat_q70", "name": "高阶火药", "type": "material", "quality": 70},
        "mat_q80": {"id": "mat_q80", "name": "秘银晶", "type": "material", "quality": 80},
        "mat_q60": {"id": "mat_q60", "name": "低阶火药", "type": "material", "quality": 60},
        "mat_raw": {"id": "mat_raw", "name": "草药", "type": "material"},  # 无 quality → 0（Q-S1）
        "mat_tier_rare": {"id": "mat_tier_rare", "name": "旧成品", "type": "consumable",
                          "quality": "rare"},  # tier 键 → 中点 69（Q-S2）
        "cat_fire": {"id": "cat_fire", "name": "爆裂壶", "type": "触媒", "elements": {"fire": 5}},
        "fire_bomb": {"id": "fire_bomb", "name": "火焰弹", "type": "consumable",
                      "quality": "common", "effects": ["burn_dot"],
                      "base_effects": {"damage": 100}},  # Q-S10 数值放大基准
    }


def _recipes() -> Dict[str, dict]:
    """测试配方注册表（element_req 单档/多档阶梯 + quality_cap 可配）。"""
    return {
        "r_basic": {"id": "r_basic", "name": "火焰弹配方", "level": 5, "kind": "craft",
                    "output": {"item": "fire_bomb", "count": 1}},
        "r_scale": {"id": "r_scale", "name": "单档刻度配方", "level": 3, "kind": "craft",
                    "output": {"item": "fire_bomb", "count": 1},
                    "element_req": {"fire": [{"threshold": 5, "effect": "burn"}]}},
        "r_scale2": {"id": "r_scale2", "name": "双档刻度配方", "level": 4, "kind": "craft",
                     "output": {"item": "fire_bomb", "count": 1},
                     "element_req": {"fire": [{"threshold": 5, "effect": "burn"},
                                              {"threshold": 8, "effect": "big_burn"}]}},
        "r_scale3": {"id": "r_scale3", "name": "三档刻度配方", "level": 6, "kind": "craft",
                     "output": {"item": "fire_bomb", "count": 1},
                     "element_req": {"fire": [{"threshold": 5, "effect": "burn"},
                                              {"threshold": 8, "effect": "big_burn"},
                                              {"threshold": 12, "effect": "mega_burn"}]}},
        "r_cap60": {"id": "r_cap60", "name": "受限配方", "level": 2, "kind": "craft",
                    "output": {"item": "fire_bomb", "count": 1}, "quality_cap": 60},  # Q-S5
    }


def _settings(catalyst_consume: bool = True) -> Dict[str, Any]:
    """settings dict（alchemy.catalyst_consume，CAT-04）。"""
    return {"alchemy": {"catalyst_consume": catalyst_consume}}


def _player_with_sp(sp_count: int = 2) -> Dict[str, Any]:
    """带 SP「品质上限+10」解锁计数的玩家 dict（QLT-08①）。"""
    return {
        "proficiency": {
            "alchemy": {
                "level": 3, "exp": 0, "sp_earned": 5, "sp_used": sp_count,
                "unlocks": {SP_QUALITY_CAP_10: sp_count},
            }
        }
    }


# ---------------------------------------------------------------------------
# ctx 直测夹具：inventory + count_item/remove_item/add_item hook + player/session_mgr
# ---------------------------------------------------------------------------


def _make_remove(inv: Dict[str, int]):
    """remove_item hook：就地扣减（不足 → not_enough 拒绝），返回 {ok,...}。"""
    def remove(item_id: str, count: int) -> dict:
        have = int(inv.get(item_id, 0))
        if have < count:
            return {"ok": False, "reason": "not_enough"}
        left = have - count
        if left <= 0:
            inv.pop(item_id, None)
        else:
            inv[item_id] = left
        return {"ok": True, "removed": count}
    return remove


def _make_add(produced_list: List[dict]):
    """add_item hook：记录入包条目（quality/traits 透传）并追加到 produced_list。"""
    def add(item_id: str, count: int, bound: bool, *, quality: Optional[str] = None,
            traits: tuple = ()) -> dict:
        produced_list.append({
            "item_id": item_id, "count": count, "bound": bound,
            "quality": quality, "traits": tuple(traits),
        })
        return {"ok": True, "added": count}
    return add


def _ctx(inventory: Optional[Dict[str, int]] = None, *, player: Optional[dict] = None,
         session_mgr: Any = None) -> tuple:
    """构造结算 ctx；返回 (ctx, produced_list)（produced_list 记录 add_item 入包）。"""
    inv: Dict[str, int] = dict(inventory) if inventory else {}
    produced_list: List[dict] = []
    ctx: Dict[str, Any] = {
        "items": _items(),
        "recipe": _recipes(),
        "inventory": inv,
        "count_item": lambda iid: int(inv.get(iid, 0)),
        "remove_item": _make_remove(inv),
        "add_item": _make_add(produced_list),
    }
    if player is not None:
        ctx["player"] = player
    if session_mgr is not None:
        ctx["session_mgr"] = session_mgr
    return ctx, produced_list


def _snap(recipe_id: str, mats: List[dict], *, element_scores: Optional[dict] = None,
          catalyst: Any = None, traits: Any = None, **kw: Any) -> dict:
    """构造会话快照（快照形态：配方ID+材料链+刻度+触媒+traits+version）。"""
    snap: Dict[str, Any] = {
        "recipe_id": recipe_id,
        "materials": mats,
        "element_scores": element_scores or {},
        "catalyst": catalyst,
        "version": 1,
    }
    if traits is not None:
        snap["traits"] = traits
    for k, v in kw.items():
        snap[k] = v
    return snap


def _mat(item_id: str, count: int = 1) -> dict:
    """材料记录（快照形态；quality 缺省走 items def 查询）。"""
    return {"item": item_id, "count": count}


class _FakeSessionMgr:
    """fake session_mgr：模拟 SessionManager.settle_alchemy 幂等（首调 True / 重复 False）。"""

    def __init__(self) -> None:
        self.calls: List[tuple] = []
        self._done: set = set()

    async def settle_alchemy(self, qid: str, message_id: str, kind: str,
                             session_view: Any = None) -> bool:
        self.calls.append((qid, message_id, kind))
        key = (qid, str(message_id), kind)
        if key in self._done:
            return False
        self._done.add(key)
        return True


# ---------------------------------------------------------------------------
# TC-02 品质均值聚合（QLT-06，TC-02）
# ---------------------------------------------------------------------------

async def test_tc02_quality_mean_70_70_80_to_73() -> None:
    """TC-02 正例：投 3 份材料（品质 70/70/80）→ 成品品质分 73（均值四舍五入，round-half-up）。

    档位按 QLT-02 区间 73∈[60,79]→rare→「史诗」（拍板②：rare=史诗；细化 TC-02 原文「73·精良」
    与拍板②区间不一致，以 m8_contract §四 4.1「79 分仍史诗」为准）。
    """
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q70"), _mat("mat_q70"), _mat("mat_q80")])
    ctx, produced = _ctx({"mat_q70": 2, "mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["quality_score"] == 73
    assert r["tier"] == "rare"
    assert r["tier_label"] == "史诗"
    assert r["degraded_levels"] == 0
    assert len(produced) == 1  # 材料不吞，产出入包


async def test_tc02_quality_mean_round_half_up() -> None:
    """TC-02 正例：round-half-up——70/70/70 → 70（无进位）；70/70/80 → 73.33 → 73。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q70"), _mat("mat_q70"), _mat("mat_q70")])
    ctx, _ = _ctx({"mat_q70": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["quality_score"] == 70
    assert r["tier"] == "rare"  # 70∈[60,79]


async def test_tc02_material_no_quality_default_zero() -> None:
    """TC-02 反例（补白 Q-S1）：无 quality 字段材料按 0 分兜底 → 均值 0 → 普通。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_raw"), _mat("mat_raw")])
    ctx, produced = _ctx({"mat_raw": 2})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["quality_score"] == 0
    assert r["tier"] == "common"
    assert r["tier_label"] == "普通"
    assert r["ok"] is True  # 基础调合 100% 成功、绝不吞材料（QLT-06）
    assert len(produced) == 1


async def test_quality_of_numeric_tier_default() -> None:
    """quality_of 直测：int 直用裁剪 / tier 键→档位中点（Q-S2）/ 无字段→0（Q-S1）。"""
    eng = SettleEngine()
    assert eng.quality_of({"quality": 80}) == 80
    assert eng.quality_of({"quality": 150}) == 100  # 裁剪 ≤100
    assert eng.quality_of({"quality": -5}) == 0
    assert eng.quality_of({"quality": "rare"}) == 69  # [60,79] 中点
    assert eng.quality_of({"quality": "legendary"}) == 90  # [80,100] 中点
    assert eng.quality_of({"quality": None}) == 0
    assert eng.quality_of({"no_quality": 1}) == 0
    assert eng.quality_of("not-a-def") == 0


# ---------------------------------------------------------------------------
# TC-03 档位系数（QLT-04，TC-03）：系数只放大效果数值，不改品质分本体
# ---------------------------------------------------------------------------

async def test_tc03_rare_epic_coef_1_2_scales_effects() -> None:
    """TC-03 正例：史诗（rare）档 → 系数 1.2 → 效果数值 基准×1.2（base_effects 数值放大）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q70"), _mat("mat_q70"), _mat("mat_q80")])  # 73→rare
    ctx, produced = _ctx({"mat_q70": 2, "mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["tier"] == "rare"
    assert r["coef"] == 1.2
    assert produced[0]["quality"] == "rare"  # 成品 quality=tier 键（STO-01）
    assert r["produced"]["scaled_effects"] == {"damage": 120.0}  # 100×1.2


async def test_tc03_legendary_coef_1_5_scales_effects() -> None:
    """TC-03 正例：传说（legendary）档 → 系数 1.5 → 效果数值 基准×1.5。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")])  # 80→legendary
    ctx, produced = _ctx({"mat_q80": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["tier"] == "legendary"
    assert r["coef"] == 1.5
    assert r["produced"]["scaled_effects"] == {"damage": 150.0}


async def test_tc03_common_coef_0_8_scales_effects() -> None:
    """TC-03 正例：普通（common）档 → 系数 0.8 → 效果数值 基准×0.8（只放大数值不改结构）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_raw"), _mat("mat_raw")])  # 0→common
    ctx, _ = _ctx({"mat_raw": 2})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["tier"] == "common"
    assert r["coef"] == 0.8
    assert r["produced"]["effects"] == {"damage": 100}  # 结构原样
    assert r["produced"]["scaled_effects"] == {"damage": 80.0}
    assert r["quality_score"] == 0  # 系数不改品质分本体（Q-S6）


# ---------------------------------------------------------------------------
# TC-05 品质上限叠加（QLT-08，TC-05）：SP +10×N / 核心 / 挑战 → 超配方原上限仍 ≤100
# ---------------------------------------------------------------------------

async def test_tc05_sp_extra_cap_relaxes_reachable_cap() -> None:
    """TC-05 正例：配方原上限 60 + SP 品质上限+10×2（+20）→ 均值 80 不被裁剪到 60
    （可达上限 80，仍 ≤100）。"""
    prof = ProficiencyEngine()
    eng = SettleEngine(prof=prof)
    snap = _snap("r_cap60", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")])  # 均值 80
    ctx, _ = _ctx({"mat_q80": 3}, player=_player_with_sp(sp_count=2))
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["quality_score"] == 80  # 超配方原上限 60（extra_cap 生效）
    assert r["tier"] == "legendary"
    assert r["quality_score"] <= 100  # 仍 ≤100（QLT-08）


async def test_tc05_no_sp_capped_to_recipe_hard_max() -> None:
    """TC-05 反例：无 SP/加成 → 可达上限=配方原上限 60 → 均值 80 裁剪到 60（普通上限不放大）。"""
    eng = SettleEngine()
    snap = _snap("r_cap60", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")])
    ctx, _ = _ctx({"mat_q80": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["quality_score"] == 60
    assert r["tier"] == "rare"  # 60∈[60,79]


async def test_tc05_snapshot_core_challenge_extra_cap() -> None:
    """TC-05 正例：快照 core_cap（核心镶嵌 +20）+ challenge_cap（挑战 +10）叠加
    → 超原上限仍 ≤100。"""
    prof = ProficiencyEngine()
    eng = SettleEngine(prof=prof)
    snap = _snap("r_cap60", [_mat("mat_q80"), _mat("mat_q80")],
                 core_cap=20, challenge_cap=10)  # 均值 80 + extra 30 → 可达 90
    ctx, _ = _ctx({"mat_q80": 2}, player=_player_with_sp(sp_count=0))
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["quality_score"] == 80  # ≤可达 90，不裁剪
    assert r["tier"] == "legendary"


async def test_tc05_cap_never_exceeds_100() -> None:
    """TC-05 反例（封顶）：extra_cap 极大 + 均值 100 → 品质分仍 ≤100。"""
    prof = ProficiencyEngine()
    eng = SettleEngine(prof=prof)
    snap = _snap("r_cap60", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")],
                 extra_cap=200)  # 均值 80 + extra 200 → 可达 min(60+200,100)=100
    ctx, _ = _ctx({"mat_q80": 3}, player=_player_with_sp(sp_count=5))
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["quality_score"] <= 100
    assert r["quality_score"] == 80  # 80 ≤ 可达 100 不裁剪


# ---------------------------------------------------------------------------
# TC-08 刻度未达标降一档（QLT-10，TC-08）：不失败不吞材料，品质降一档照样出货
# ---------------------------------------------------------------------------

async def test_tc08_scale_missing_degrades_one_tier() -> None:
    """TC-08 正例：火累计 4（阈值 5 未达标）→ 品质降 1 档（legendary→rare，79）照样出货。"""
    eng = SettleEngine()
    snap = _snap("r_scale", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")],
                 element_scores={"fire": 4})  # 均值 80（legendary）
    ctx, produced = _ctx({"mat_q80": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["degraded_levels"] == 1
    assert r["quality_score"] == 79  # 80 降档裁剪到 rare 区间 [60,79]
    assert r["tier"] == "rare"
    assert r["ok"] is True  # 不失败不吞材料
    assert len(produced) == 1


async def test_tc08_scale_met_no_degrade() -> None:
    """TC-08 反例：火累计 6（阈值 5 达标）→ 不降级（品质 80·传说 出货）。"""
    eng = SettleEngine()
    snap = _snap("r_scale", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")],
                 element_scores={"fire": 6})
    ctx, produced = _ctx({"mat_q80": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["degraded_levels"] == 0
    assert r["quality_score"] == 80
    assert r["tier"] == "legendary"
    assert len(produced) == 1


# ---------------------------------------------------------------------------
# TC-09 传说全不达标降至普通封底（QLT-10，TC-09）：差 N 档降 N 档，最低普通封底仍出货
# ---------------------------------------------------------------------------

async def test_tc09_double_missing_degrades_two_tiers() -> None:
    """TC-09 正例：双档阶梯全不达标（火 4 < 5/8）→ 降 2 档（legendary→uncommon，59）。"""
    eng = SettleEngine()
    snap = _snap("r_scale2", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")],
                 element_scores={"fire": 4})  # levels_missing=2
    ctx, produced = _ctx({"mat_q80": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["degraded_levels"] == 2
    assert r["quality_score"] == 59  # 80 降 2 档 → 裁剪到 uncommon 区间 [40,59]（Q-3 落档稳定）
    assert r["tier"] == "uncommon"
    assert r["ok"] is True
    assert len(produced) == 1  # 材料不吞


async def test_tc09_legendary_all_fail_floor_common() -> None:
    """TC-09 正例：传说级成品三档刻度全不达标 → 降至普通（common）封底仍出货，绝不吞材料。"""
    eng = SettleEngine()
    snap = _snap("r_scale3", [_mat("mat_q80"), _mat("mat_q80"), _mat("mat_q80")],
                 element_scores={})  # 火 0 < 5/8/12 → levels_missing=3
    ctx, produced = _ctx({"mat_q80": 3})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["degraded_levels"] == 3
    assert r["quality_score"] == 39  # 80 降 3 档 → common [0,39] 封底
    assert r["tier"] == "common"
    assert r["tier_label"] == "普通"
    assert r["ok"] is True  # 最低普通封底、不失败、不吞材料（QLT-10）
    assert len(produced) == 1


# ---------------------------------------------------------------------------
# TC-15 标准版无特性（LAY-04a / Q-S9）：快照无 traits → 成品 traits 恒空；有 traits → 写入
# ---------------------------------------------------------------------------

async def test_tc15_standard_no_traits_empty() -> None:
    """TC-15 正例：快照无 traits（未 /继承）→ 成品 traits=[]（标准版无特性，LAY-04a）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")])  # 无 traits 键
    ctx, produced = _ctx({"mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["produced"]["traits"] == []
    assert produced[0]["traits"] == ()  # add_item 收到空 traits 元组


async def test_tc15_with_inherited_traits_passed() -> None:
    """TC-15 反例（带继承）：快照 traits 非空 → 成品 traits 写入
    （INH-08：所选特性随 /确认 写入）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")],
                 traits=["trait_burn_boost", "trait_fire_15"])
    ctx, produced = _ctx({"mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["produced"]["traits"] == ["trait_burn_boost", "trait_fire_15"]
    assert produced[0]["traits"] == ("trait_burn_boost", "trait_fire_15")  # 冻结元组语义


# ---------------------------------------------------------------------------
# TC-20 触媒消耗（CAT-04，TC-20）：catalyst_consume=true 扣 1 / false 不扣 / 移走复核拒
# ---------------------------------------------------------------------------

async def test_tc20_catalyst_consumed_when_enabled() -> None:
    """TC-20 正例：catalyst_consume=true（默认）→ /确认 扣触媒 1 个（同事务，CAT-04）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")], catalyst="cat_fire")
    ctx, _ = _ctx({"mat_q80": 1, "cat_fire": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["catalyst_consumed"] is True
    assert ctx["inventory"].get("cat_fire", 0) == 0  # 触媒已扣


async def test_tc20_catalyst_not_consumed_when_disabled() -> None:
    """TC-20 反例：catalyst_consume=false → 触媒不扣（仅方向修饰，CAT-04 可配）。"""
    eng = SettleEngine(settings=_settings(catalyst_consume=False))
    snap = _snap("r_basic", [_mat("mat_q80")], catalyst="cat_fire")
    ctx, _ = _ctx({"mat_q80": 1, "cat_fire": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["catalyst_consumed"] is False
    assert ctx["inventory"].get("cat_fire", 0) == 1  # 未扣


async def test_tc20_catalyst_moved_away_reject_diff() -> None:
    """TC-20 反例：会话中 /确认 时触媒被移走 → 全量复核拒 + 差异提示（触媒纳入复核，TC-20）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")], catalyst="cat_fire")
    ctx, produced = _ctx({"mat_q80": 1})  # 背包无触媒
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is False
    assert r["reason"] == "materials_insufficient"
    assert any(s.get("item") == "cat_fire" for s in r["shortfall"])
    assert produced == []  # 无产出、零扣料


# ---------------------------------------------------------------------------
# 材料不足全拒差异（GU-19/ATO-02，TC-12）：全量复核拒、材料不扣、无产出
# ---------------------------------------------------------------------------

async def test_materials_insufficient_full_reject_with_diff() -> None:
    """GU-19 反例：材料被移走 → 全量复核拒（材料不足，无法确认）+ 差异短清单 + 背包零变更。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q70", count=2), _mat("mat_q80", count=1)])
    ctx, produced = _ctx({"mat_q70": 1, "mat_q80": 1})  # 缺 火晶石(70)×1
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is False
    assert r["reason"] == "materials_insufficient"
    assert r["message"] == "材料不足，无法确认"
    assert any(s.get("item") == "mat_q70" and s.get("have") == 1 for s in r["shortfall"])
    assert ctx["inventory"].get("mat_q70", 0) == 1  # 不部分扣减
    assert ctx["inventory"].get("mat_q80", 0) == 1
    assert produced == []  # 无产出


async def test_confirm_no_snapshot_rejected() -> None:
    """GU-17 反例：无快照（无会话）→ no_snapshot 拒绝（引擎侧防御，零抛异常）。"""
    eng = SettleEngine()
    ctx, produced = _ctx({})
    r = await eng.confirm(ctx, None, qid="u1", job_tier_index=0)
    assert r["ok"] is False
    assert r["reason"] == "no_snapshot"
    assert produced == []


async def test_confirm_recipe_not_found_rejected() -> None:
    """反例：快照配方在注册表缺失 → recipe_not_found 拒绝（不产出入包）。"""
    eng = SettleEngine()
    snap = _snap("r_ghost", [_mat("mat_q80")])
    ctx, produced = _ctx({"mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is False
    assert r["reason"] == "recipe_not_found"
    assert produced == []


# ---------------------------------------------------------------------------
# 产出字段（STO-01：成品带 quality=tier 键 + tier + traits）与熟练经验（EXP-03）
# ---------------------------------------------------------------------------

async def test_produced_carries_quality_tier_traits_fields() -> None:
    """正例：produced 字典携带 item_id/name/count/quality(=tier 键)/tier/traits（STO-01）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")], traits=["trait_burn_boost"])
    ctx, produced = _ctx({"mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    p = r["produced"]
    assert p["item_id"] == "fire_bomb"
    assert p["name"] == "火焰弹"
    assert p["count"] == 1
    assert p["quality"] == p["tier"] == "legendary"  # 80→legendary
    assert p["traits"] == ["trait_burn_boost"]
    assert p["tier_label"] == "传说"
    assert len(produced) == 1
    assert r["message"] == "确认成功：火焰弹（品质 80·传说）"


async def test_exp_gained_equals_recipe_level() -> None:
    """正例：熟练经验=配方等级×1（EXP-03/CASC-01，source='craft'）→ 配方 level=5 → exp 5。"""
    prof = ProficiencyEngine()
    eng = SettleEngine(prof=prof)
    snap = _snap("r_basic", [_mat("mat_q80")])  # r_basic level=5
    player = {"proficiency": {"alchemy": {"level": 2, "exp": 100, "sp_earned": 1,
                                          "sp_used": 0, "unlocks": {}}}}
    ctx, _ = _ctx({"mat_q80": 1}, player=player)
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["exp_gained"] == 5
    assert player["proficiency"]["alchemy"]["exp"] == 105  # 熟练经验已入账


async def test_exp_skipped_without_prof() -> None:
    """反例：未注入 prof → exp_gained=0（熟练经验由壳层另行入账，引擎不越权）。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")])
    ctx, _ = _ctx({"mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["exp_gained"] == 0


# ---------------------------------------------------------------------------
# 终态幂等（§10 铁律 3 / ATO-04，Q-S7）：message_id 首调 ok → 二次「已结算」零业务写
# ---------------------------------------------------------------------------

async def test_idempotent_confirm_first_ok_second_settled() -> None:
    """正例：同一 message_id 首调 settle_alchemy=True → ok；重投递二次 →「已结算」零重复扣料。"""
    mgr = _FakeSessionMgr()
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")])
    ctx, produced = _ctx({"mat_q80": 1}, session_mgr=mgr)
    # 第一次：gate 通过 → 复核/扣料/产出
    r1 = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3, message_id="m1")
    assert r1["ok"] is True
    assert r1["idempotent"] is False
    assert r1["settled"] is True
    assert ctx["inventory"].get("mat_q80", 0) == 0  # 材料已扣
    assert len(produced) == 1
    assert mgr.calls == [("u1", "m1", SETTLE_CONFIRM)]
    # 第二次：同一 ctx（材料已消耗/会话已删）→ gate 先命中已结算 →「已结算」，零业务写
    r2 = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3, message_id="m1")
    assert r2["ok"] is False
    assert r2["reason"] == "already_settled"
    assert r2["message"] == "已结算"
    assert r2["idempotent"] is True
    assert len(produced) == 1  # 无新增产出
    assert ctx["inventory"].get("mat_q80", 0) == 0  # 未再扣（本来就已扣完）
    assert len(mgr.calls) == 2  # settle_alchemy 被调用两次，第二次返回 False


async def test_confirm_without_message_id_skips_settle() -> None:
    """反例：message_id 未提供 → 跳过终态落键（settled=False），纯结算路径照常产出。"""
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")])
    ctx, produced = _ctx({"mat_q80": 1})
    r = await eng.confirm(ctx, snap, qid="u1", job_tier_index=3)
    assert r["ok"] is True
    assert r["settled"] is False
    assert len(produced) == 1


def test_settle_key_formats() -> None:
    """settle_key 直测：command=f"settle:{kind}"（§10 铁律 3）。"""
    assert SettleEngine.settle_key(SETTLE_CONFIRM) == "settle:confirm"
    assert SettleEngine.settle_key(SETTLE_ABANDON) == "settle:abandon"


# ---------------------------------------------------------------------------
# /放弃（F-05 / §7.1 行10）：材料不结算、会话退出终态
# ---------------------------------------------------------------------------

async def test_abandon_terminates_without_consuming() -> None:
    """正例：/放弃 → ok、材料不结算（零背包改动）、无产出、终态 settle 'abandon'。"""
    mgr = _FakeSessionMgr()
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80", count=2)])
    inv = {"mat_q80": 2}
    ctx, produced = _ctx(inv, session_mgr=mgr)
    r = await eng.abandon(ctx, snap, qid="u1", message_id="a1")
    assert r["ok"] is True
    assert r["message"] == "已放弃"
    assert r["settled"] is True
    assert inv.get("mat_q80", 0) == 2  # 材料不结算不扣（F-05）
    assert produced == []  # 无产出
    assert mgr.calls == [("u1", "a1", SETTLE_ABANDON)]


async def test_abandon_idempotent_second_abandoned() -> None:
    """反例：重复放弃（同 message_id）→「已放弃」幂等，零重复结算。"""
    mgr = _FakeSessionMgr()
    eng = SettleEngine()
    snap = _snap("r_basic", [_mat("mat_q80")])
    ctx, produced = _ctx({"mat_q80": 1}, session_mgr=mgr)
    r1 = await eng.abandon(ctx, snap, qid="u1", message_id="a1")
    assert r1["ok"] is True
    r2 = await eng.abandon(ctx, snap, qid="u1", message_id="a1")
    assert r2["ok"] is False
    assert r2["reason"] == "already_settled"
    assert r2["message"] == "已放弃"
    assert r2["idempotent"] is True
    assert produced == []


async def test_abandon_without_message_id() -> None:
    """反例：/放弃 无 message_id → 纯终态返回（settled=False），由壳层负责落键。"""
    eng = SettleEngine()
    ctx, produced = _ctx({})
    r = await eng.abandon(ctx, None, qid="u1")
    assert r["ok"] is True
    assert r["settled"] is False
    assert produced == []
