"""特性继承引擎单测（M8 批5 · qbot_rpg/core/trait_inherit.py）。

文件：tests/unit/test_trait_inherit.py
创建：2026-08-29
作者：Hermes 子agent-5A-1
功能：TraitInherit 引擎纯逻辑直测（零 IO 零 NoneBot）——
  TC-12 等级化位（正式1/精通2/专家3/见习0 拒绝「无继承位」）
  TC-13 SP 特性位+1 叠加 + 总上限 + 内容包 trait_slot_max 1-6 边界
  TC-14 继承成功写入快照 traits + PP 扣除（INH-08）
  TC-15 PP 预算（3 普通+1 超=5 恰好 / 第 4 个 PP 不足 / 挂起恢复 PP 不清零、新会话重置）
  TC-18 group 互斥（同组拒绝+组外通过+与已选/已占金色位冲突）
  TC-19 repeatable=false 拒绝 / repeatable=true 可重复
  TC-20 负面特性（宗师自动附带 / 宗师门槛 / 占位不耗 PP）
  TC-22 超特性第 4 位独占 + 宗师门槛 + 关闭独占共用位池
  TC-23 无金色素材第 4 位空缺（金色池空 → 拒绝）
  TC-24 超 PP2 / 普通 PP1
  INH-01 候选清单来源（不可凭空继承）
  apply_to_snapshot version 递增 / pool_normal/pool_gold / check_placement_conflict 复核
  asyncio_mode=auto（本文件全为纯函数直测，无 async 用例）。

依据：docs/细化/细化_2c4e_品质与特性.md（INH-01~16 / TSC-11~14 / TC-12~24）+
  docs/m8_contract_指令契约.md §4（GU-13~16/F-04/M-04）+ m8_contract_核心机制.md
  §五/§十（pp_cost/pp_refresh/gold_slot_exclusive）。
测试风格对齐 tests/unit/test_alchemy_core.py（traits/items/recipe 注册表夹具 + 直接构造
  快照池）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from qbot_rpg.core.proficiency import ProficiencyEngine
from qbot_rpg.core.trait_inherit import DEFAULT_TRAIT_SLOT_PANEL_ID, TraitInherit

# ---------------------------------------------------------------------------
# 夹具：traits 注册表 + settings + 候选池（对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------

TRAITS: Dict[str, dict] = {
    "trait_burn_boost": {"id": "trait_burn_boost", "name": "灼烧强化", "rarity": "normal",
                         "group": "fire_boost", "repeatable": False, "source": "素材"},
    "trait_burn_snap": {"id": "trait_burn_snap", "name": "灼烧爆燃", "rarity": "normal",
                        "group": "fire_boost", "repeatable": False, "source": "素材"},
    "trait_poison_boost": {"id": "trait_poison_boost", "name": "剧毒强化", "rarity": "normal",
                           "group": "venom_boost", "repeatable": False, "source": "素材"},
    "trait_heal_boost": {"id": "trait_heal_boost", "name": "回复强化", "rarity": "normal",
                         "group": "", "repeatable": True, "source": "成品"},
    "trait_mp_flow": {"id": "trait_mp_flow", "name": "魔力流转", "rarity": "normal",
                      "group": "", "repeatable": True, "source": "成品"},
    "trait_guard_up": {"id": "trait_guard_up", "name": "守护", "rarity": "normal",
                       "group": "", "repeatable": True, "source": "素材"},
    "trait_berserk": {"id": "trait_berserk", "name": "狂化", "rarity": "normal",
                      "group": "berserk", "repeatable": False, "source": "素材",
                      "negative": "trait_frailty"},
    "trait_frailty": {"id": "trait_frailty", "name": "脆弱", "rarity": "normal",
                      "group": "debuff", "repeatable": False, "source": "素材"},
    "trait_fire_15": {"id": "trait_fire_15", "name": "灼烧强化·精", "rarity": "super",
                      "group": "fire_boost", "repeatable": False, "source": "金色素材"},
    "trait_fire_25": {"id": "trait_fire_25", "name": "灼烧强化·大师", "rarity": "super",
                      "group": "fire_boost", "repeatable": False, "source": "金色素材",
                      "negative": "trait_frailty"},
}

# 普通候选池（INH-01/03：source=素材/成品 → 普通池；条目形态 [(tid, name, pp)]）
N_POOL: List[Tuple[str, str, int]] = [
    ("trait_burn_boost", "灼烧强化", 1),
    ("trait_burn_snap", "灼烧爆燃", 1),
    ("trait_poison_boost", "剧毒强化", 1),
    ("trait_heal_boost", "回复强化", 1),
    ("trait_mp_flow", "魔力流转", 1),
    ("trait_guard_up", "守护", 1),
    ("trait_berserk", "狂化", 1),
]
# 金色超特性候选池（TSC-13：source=金色素材 → 超特性池）
G_POOL: List[Tuple[str, str, int]] = [
    ("trait_fire_15", "灼烧强化·精", 2),
    ("trait_fire_25", "灼烧强化·大师", 2),
]

SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "pp_cost": {"normal": 1, "super": 2},
        "gold_slot_exclusive": True,
    },
}


def make_ctx() -> dict:
    """引擎 ctx（traits 注册表：group/repeatable/negative 等 def 字段解析，T-2）。"""
    return {"traits": TRAITS}


def make_engine(settings: Any = None) -> TraitInherit:
    """构造引擎（配置注入 + ProficiencyEngine；缺省默认值兜底）。"""
    s: Any = settings if settings is not None else SETTINGS
    return TraitInherit(prof=ProficiencyEngine(settings=s), settings=s)


def make_snap(*, normal: Any = None, gold: Any = None, pp_used: int = 0,
              pp_budget: int = 5, traits: Any = None, gold_slot: Any = None,
              negatives: Any = None, version: int = 1) -> dict:
    """会话快照（pool{normal,gold,awaken} / pp{used,budget} / traits / gold_slot /
    negatives / version，对齐 AlchemyCore.new_snapshot+apply_feed 形态）。"""
    return {
        "recipe_id": "rcp_flame",
        "materials": [],
        "chain": {},
        "element_scores": {},
        "pool": {"normal": list(normal or []), "gold": list(gold or []), "awaken": []},
        "catalyst": None,
        "pp": {"used": pp_used, "budget": pp_budget},
        "step": "feed",
        "version": version,
        "job_tier": 3,
        "job_tier_index": 3,
        "traits": list(traits or []),
        "gold_slot": gold_slot,
        "negatives": list(negatives or []),
    }


def make_player(level: int = 3, sp_slots: int = 0) -> dict:
    """玩家状态 dict（proficiency dict 形态 M8 决策 4；SP 特性位+1 解锁计数）。"""
    return {"proficiency": {"alchemy": {
        "level": level, "exp": 0, "sp_earned": sp_slots, "sp_used": 0,
        "unlocks": {DEFAULT_TRAIT_SLOT_PANEL_ID: sp_slots},
    }}}


# ---------------------------------------------------------------------------
# TC-12 等级化位（INH-14：正式1/精通2/专家3 见习0）
# ---------------------------------------------------------------------------
def test_tc12_tier_slot_progression() -> None:
    """TC-12 正例：inherit_slots 正式1/精通2/专家3/王3/见习0（等级化位）。"""
    eng = make_engine()
    assert eng.inherit_slots(make_player(0), 0) == 0   # 见习无继承位
    assert eng.inherit_slots(make_player(1), 1) == 1   # 正式
    assert eng.inherit_slots(make_player(2), 2) == 2   # 精通
    assert eng.inherit_slots(make_player(3), 3) == 3   # 专家
    assert eng.inherit_slots(make_player(6), 6) == 3   # 王（封顶 3）


def test_tc12_apprentice_rejected() -> None:
    """TC-12 负例：见习 /继承 → 拒绝「见习无继承位」（INH-14/L344）。"""
    eng = make_engine()
    res = eng.select_traits(make_player(0), make_snap(normal=N_POOL),
                            ["trait_burn_boost"], job_tier_index=0, ctx=make_ctx())
    assert res["ok"] is False and res["reason"] == "no_inherit_slot"
    assert "见习无继承位" in res["message"]


def test_tc12_formal_one_slot_ok_two_rejected() -> None:
    """TC-12：正式 1 项可继承；第 2 项 → 「继承超 1 项」（INH-06）。"""
    eng = make_engine()
    ok = eng.select_traits(make_player(1), make_snap(normal=N_POOL),
                           ["trait_burn_boost"], job_tier_index=1, ctx=make_ctx())
    assert ok["ok"] is True and ok["traits"] == ["trait_burn_boost"]
    bad = eng.select_traits(make_player(1), make_snap(normal=N_POOL),
                            ["trait_burn_boost", "trait_poison_boost"],
                            job_tier_index=1, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "slot_overflow"
    assert "继承超 1 项" in bad["message"] and bad["limit"] == 1


def test_tc12_proficient_two_ok_three_rejected() -> None:
    """TC-12：精通 2 项可继承；第 3 项 → 「继承超 2 项」。"""
    eng = make_engine()
    ok = eng.select_traits(make_player(2), make_snap(normal=N_POOL),
                           ["trait_burn_boost", "trait_poison_boost"],
                           job_tier_index=2, ctx=make_ctx())
    assert ok["ok"] is True and len(ok["traits"]) == 2
    bad = eng.select_traits(make_player(2), make_snap(normal=N_POOL),
                            ["trait_burn_boost", "trait_poison_boost", "trait_heal_boost"],
                            job_tier_index=2, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "slot_overflow"
    assert "继承超 2 项" in bad["message"] and bad["limit"] == 2


def test_tc12_expert_three_ok_four_rejected() -> None:
    """TC-12：专家 3 项可继承；第 4 项 → 「继承超 3 项」（默认上限 3，INH-06）。"""
    eng = make_engine()
    ok = eng.select_traits(make_player(3), make_snap(normal=N_POOL),
                           ["trait_burn_boost", "trait_poison_boost", "trait_heal_boost"],
                           job_tier_index=3, ctx=make_ctx())
    assert ok["ok"] is True and len(ok["traits"]) == 3
    bad = eng.select_traits(
        make_player(3), make_snap(normal=N_POOL),
        ["trait_burn_boost", "trait_poison_boost", "trait_heal_boost", "trait_mp_flow"],
        job_tier_index=3, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "slot_overflow"
    assert "继承超 3 项" in bad["message"] and bad["limit"] == 3


# ---------------------------------------------------------------------------
# TC-13 SP 特性位+1 叠加 + 上限（INH-15：可多次、与等级位叠加、总上限 6）
# ---------------------------------------------------------------------------
def test_tc13_sp_slot_bonus_stack_and_total_cap() -> None:
    """TC-13：SP「特性位+1」×2 → 上限 5（专家 3+2）；×4 → 钳制总上限 6（REC-12）。"""
    eng = make_engine()
    assert eng.inherit_slots(make_player(3, sp_slots=2), 3) == 5
    assert eng.inherit_slots(make_player(3, sp_slots=4), 3) == 6  # 总上限 6
    # 5 项可继承（专家 3 + SP×2；非互斥非负面特性集）
    five = ["trait_burn_boost", "trait_poison_boost", "trait_heal_boost",
            "trait_mp_flow", "trait_guard_up"]
    ok = eng.select_traits(make_player(3, sp_slots=2), make_snap(normal=N_POOL),
                           five, job_tier_index=3, ctx=make_ctx())
    assert ok["ok"] is True and len(ok["traits"]) == 5
    # 第 6 项 → 继承超 5 项（PP 预算 6 先过 PP 再撞位；burn_snap 与 burn_boost 同组，
    # 但位余量校验先于 group 互斥，F-04 顺序 GU-14→GU-15→GU-16）
    six = five + ["trait_burn_snap"]
    bad = eng.select_traits(make_player(3, sp_slots=2),
                            make_snap(normal=N_POOL, pp_budget=6),
                            six, job_tier_index=3, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "slot_overflow"
    assert "继承超 5 项" in bad["message"] and bad["limit"] == 5


def test_tc13_config_trait_slot_max_boundary() -> None:
    """TC-13：内容包 trait_slot_max 1-6 边界生效（INH-06 可配 1-6；T-1 上限钳制）。"""
    eng1 = make_engine({"alchemy": dict(SETTINGS["alchemy"], trait_slot_max=1)})
    assert eng1.inherit_slots(make_player(3), 3) == 1  # 专家位被钳到 1
    bad = eng1.select_traits(make_player(3), make_snap(normal=N_POOL),
                             ["trait_burn_boost", "trait_poison_boost"],
                             job_tier_index=3, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "slot_overflow" and bad["limit"] == 1
    eng6 = make_engine({"alchemy": dict(SETTINGS["alchemy"], trait_slot_max=6)})
    assert eng6.inherit_slots(make_player(3), 3) == 3  # 6 不改变自然等级位（专家 ≤3）


# ---------------------------------------------------------------------------
# TC-14 继承成功写入快照 traits（INH-08/STO-03）
# ---------------------------------------------------------------------------
def test_tc14_inherit_writes_traits_and_pp() -> None:
    """TC-14：/继承 灼烧强化,回复强化 → 二者写入快照 traits + PP 扣 2（INH-08）。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL)
    res = eng.select_traits(make_player(3), snap,
                            ["trait_burn_boost", "trait_heal_boost"],
                            job_tier_index=3, ctx=make_ctx())
    assert res["ok"] is True
    assert res["traits"] == ["trait_burn_boost", "trait_heal_boost"]
    assert res["pp_used"] == 2
    snap2 = eng.apply_to_snapshot(snap, res["traits"], pp_used=res["pp_used"])
    assert snap2["traits"] == ["trait_burn_boost", "trait_heal_boost"]
    assert snap2["pp"]["used"] == 2
    assert snap2["version"] == 2   # §7.1 行4：状态更新 version 递增
    assert snap2["step"] == "inherit"
    assert snap["traits"] == []    # 原快照只读不改写（纯函数）


# ---------------------------------------------------------------------------
# TC-15 PP 预算（INH-09/TSC-14：普通1/超2，会话内累计，pp_refresh=会话重置）
# ---------------------------------------------------------------------------
def test_tc15_pp_budget_exact_and_insufficient() -> None:
    """TC-15：PP 5/5：3 普通(PP3)+1 超(PP2)=5 恰好；再继承第 4 个普通 → 「PP 不足」。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, gold=G_POOL, pp_budget=5)
    # 3 普通选非 fire_boost 组（fire_15 金色位组 fire_boost，INH-10 成品共存互斥）
    res = eng.select_traits(
        make_player(5), snap,
        ["trait_poison_boost", "trait_heal_boost", "trait_mp_flow"],
        super_trait="trait_fire_15", job_tier_index=5, ctx=make_ctx())
    assert res["ok"] is True
    assert res["gold_slot"] == "trait_fire_15"
    assert res["pp_used"] == 5  # 3×1 + 2 = 5 恰好
    snap2 = eng.apply_to_snapshot(snap, res["traits"], super_trait=res["gold_slot"],
                                  pp_used=res["pp_used"])
    # 已用满（会话内累计）：第 4 个普通 → PP 不足（PP 校验先于 group，F-04 顺序）
    bad = eng.select_traits(make_player(5), snap2, ["trait_burn_boost"],
                            job_tier_index=5, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "pp_insufficient"
    assert "PP 不足" in bad["message"]


def test_tc15_pp_persist_across_suspend_and_reset() -> None:
    """TC-15：挂起/恢复 PP 不清零（快照携带 used）；/确认 结算后随会话重置（新快照 used=0）。"""
    eng = make_engine()
    snap1 = make_snap(normal=N_POOL, pp_budget=5)
    r1 = eng.select_traits(make_player(3), snap1, ["trait_burn_boost"],
                           job_tier_index=3, ctx=make_ctx())
    s1 = eng.apply_to_snapshot(snap1, r1["traits"], pp_used=r1["pp_used"])
    assert s1["pp"]["used"] == 1  # 挂起/恢复不清零
    # 新会话（pp_refresh=会话重置）→ used 归 0
    snap2 = make_snap(normal=N_POOL, pp_budget=5)
    r2 = eng.select_traits(make_player(3), snap2, ["trait_poison_boost"],
                           job_tier_index=3, ctx=make_ctx())
    assert r2["pp_used"] == 1


# ---------------------------------------------------------------------------
# TC-18 group 互斥（INH-10：组内最多 1 项）
# ---------------------------------------------------------------------------
def test_tc18_group_conflict_reject_and_pass() -> None:
    """TC-18：A、B 同 group（fire_boost）→ 拒绝「互斥组内最多 1 项」；A+组外 C → 通过。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL)
    bad = eng.select_traits(make_player(3), snap,
                            ["trait_burn_boost", "trait_burn_snap"],
                            job_tier_index=3, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "group_conflict"
    assert "互斥组内最多 1 项" in bad["message"] and "fire_boost" in bad["message"]
    ok = eng.select_traits(make_player(3), snap,
                           ["trait_burn_boost", "trait_poison_boost"],
                           job_tier_index=3, ctx=make_ctx())
    assert ok["ok"] is True
    assert ok["traits"] == ["trait_burn_boost", "trait_poison_boost"]


def test_tc18_group_conflict_with_already_selected() -> None:
    """TC-18：与已选特性同组（快照 traits 已含 fire_boost）→ 拒绝并提示组名。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, traits=["trait_burn_boost"], pp_used=1)
    bad = eng.select_traits(make_player(3), snap, ["trait_burn_snap"],
                            job_tier_index=3, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "group_conflict"
    assert bad["group"] == "fire_boost"


# ---------------------------------------------------------------------------
# TC-19 repeatable（INH-11：false 不可重复；true 可重复）
# ---------------------------------------------------------------------------
def test_tc19_repeatable_false_reject() -> None:
    """TC-19：repeatable=false 特性第二次 /继承 → 拒绝（批内重复 + 与已选重复）。"""
    eng = make_engine()
    bad = eng.select_traits(make_player(3), make_snap(normal=N_POOL),
                            ["trait_burn_boost", "trait_burn_boost"],
                            job_tier_index=3, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "not_repeatable"
    snap = make_snap(normal=N_POOL, traits=["trait_burn_boost"], pp_used=1)
    bad2 = eng.select_traits(make_player(3), snap, ["trait_burn_boost"],
                             job_tier_index=3, ctx=make_ctx())
    assert bad2["ok"] is False and bad2["reason"] == "not_repeatable"


def test_tc19_repeatable_true_allow() -> None:
    """TC-19：repeatable=true 特性可重复，成品上多次出现（受叠加规则约束）。"""
    eng = make_engine()
    ok = eng.select_traits(make_player(3), make_snap(normal=N_POOL),
                           ["trait_heal_boost", "trait_heal_boost"],
                           job_tier_index=3, ctx=make_ctx())
    assert ok["ok"] is True
    assert ok["traits"] == ["trait_heal_boost", "trait_heal_boost"]


# ---------------------------------------------------------------------------
# TC-20 负面特性（INH-12：宗师继承强力特性需承受 1 个同源负面）
# ---------------------------------------------------------------------------
def test_tc20_negative_auto_attach() -> None:
    """TC-20：宗师 /继承 强力特性（狂化，negative 配置）→ 自动附带 1 个同源负面。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, pp_budget=5)
    res = eng.select_traits(make_player(5), snap, ["trait_berserk"],
                            job_tier_index=5, ctx=make_ctx())
    assert res["ok"] is True
    assert res["traits"] == ["trait_berserk"]
    assert res["negatives"] == ["trait_frailty"]  # 自动附带 1 负面
    assert res["pp_used"] == 1  # 负面不耗 PP（T-4）
    snap2 = eng.apply_to_snapshot(snap, res["traits"], negatives=res["negatives"],
                                  pp_used=res["pp_used"])
    assert snap2["negatives"] == ["trait_frailty"]


def test_tc20_negative_requires_grandmaster() -> None:
    """TC-20/INH-12：负面特性（宗师解锁）——大师（tier4）选强力特性 → 「负面特性需宗师」。"""
    eng = make_engine()
    res = eng.select_traits(make_player(4), make_snap(normal=N_POOL),
                            ["trait_berserk"], job_tier_index=4, ctx=make_ctx())
    assert res["ok"] is False and res["reason"] == "grandmaster_required"
    assert "负面特性需宗师" in res["message"]


def test_tc20_negative_occupies_slot() -> None:
    """TC-20/T-4：负面占普通位——slot_cap=1 时强力特性+负面=2 位 → 继承超 1 项。"""
    eng = make_engine()
    res = eng.select_traits(make_player(5), make_snap(normal=N_POOL, pp_budget=5),
                            ["trait_berserk"], job_tier_index=5, ctx=make_ctx(),
                            slot_cap=1)
    assert res["ok"] is False and res["reason"] == "slot_overflow"
    assert res["limit"] == 1


# ---------------------------------------------------------------------------
# TC-22 超特性第 4 位独占 + 宗师门槛（TSC-11/12）
# ---------------------------------------------------------------------------
def test_tc22_super_requires_grandmaster() -> None:
    """TC-22/TSC-11：超特性继承需宗师——大师（tier4）→ 「超特性继承需宗师」。"""
    eng = make_engine()
    res = eng.select_traits(make_player(4), make_snap(normal=N_POOL, gold=G_POOL),
                            [], super_trait="trait_fire_15", job_tier_index=4,
                            ctx=make_ctx())
    assert res["ok"] is False and res["reason"] == "grandmaster_required"
    assert "超特性继承需宗师" in res["message"]


def test_tc22_super_4th_slot_exclusive_occupy_once() -> None:
    """TC-22/TSC-12：宗师 /继承超 → 占用第 4 位（普通位 3 个之外）；重复 → 第 4 位已占用。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, gold=G_POOL, pp_budget=5)
    ok = eng.select_traits(make_player(5), snap, [],
                           super_trait="trait_fire_15", job_tier_index=5, ctx=make_ctx())
    assert ok["ok"] is True and ok["gold_slot"] == "trait_fire_15"
    assert ok["pp_used"] == 2
    snap2 = eng.apply_to_snapshot(snap, ok["traits"], super_trait=ok["gold_slot"],
                                  pp_used=ok["pp_used"])
    # 第 4 位独占：普通位 3 项仍可继承（不占普通位）
    ok2 = eng.select_traits(make_player(5), snap2,
                            ["trait_poison_boost", "trait_heal_boost", "trait_mp_flow"],
                            job_tier_index=5, ctx=make_ctx())
    assert ok2["ok"] is True and len(ok2["traits"]) == 3
    # 与已占第 4 位同组（fire_boost）→ 成品共存层面互斥（INH-10）
    bad2 = eng.select_traits(make_player(5), snap2, ["trait_burn_boost"],
                             job_tier_index=5, ctx=make_ctx())
    assert bad2["ok"] is False and bad2["reason"] == "group_conflict"
    assert bad2["group"] == "fire_boost"
    # 第 4 位已被占：再 /继承超 → 第 4 位金色已占用
    bad = eng.select_traits(make_player(5), snap2, [],
                            super_trait="trait_fire_25", job_tier_index=5, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "gold_slot_occupied"


def test_tc22_gold_not_exclusive_shares_normal_pool() -> None:
    """TSC-12：gold_slot_exclusive=false → 超特性与普通共用位池（仍受位上限约束）。"""
    eng = make_engine({"alchemy": dict(SETTINGS["alchemy"], gold_slot_exclusive=False)})
    snap = make_snap(normal=N_POOL, gold=G_POOL, pp_budget=5)
    # 3 普通 + 超（占用普通位）= 4 位 → 继承超 3 项
    bad = eng.select_traits(make_player(5), snap,
                            ["trait_poison_boost", "trait_heal_boost", "trait_mp_flow"],
                            super_trait="trait_fire_15", job_tier_index=5, ctx=make_ctx())
    assert bad["ok"] is False and bad["reason"] == "slot_overflow" and bad["limit"] == 3
    # 2 普通 + 超 = 3 位 → 通过；超特性并入普通 traits、gold_slot 空
    ok = eng.select_traits(make_player(5), snap,
                           ["trait_poison_boost", "trait_heal_boost"],
                           super_trait="trait_fire_15", job_tier_index=5, ctx=make_ctx())
    assert ok["ok"] is True and ok["gold_slot"] is None
    assert "trait_fire_15" in ok["traits"]


# ---------------------------------------------------------------------------
# TC-23 无金色素材第 4 位空缺（TSC-13）
# ---------------------------------------------------------------------------
def test_tc23_no_gold_pool_4th_vacant() -> None:
    """TC-23：无金色素材投料 → 超特性池空 → /继承超 拒绝、第 4 位空缺。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, gold=[])
    res = eng.select_traits(make_player(5), snap, [],
                            super_trait="trait_fire_15", job_tier_index=5, ctx=make_ctx())
    assert res["ok"] is False and res["reason"] == "not_in_pool"
    assert "金色素材" in res["message"]


# ---------------------------------------------------------------------------
# TC-24 超 PP2 / 普通 PP1（TSC-14：rarity 是 PP 计价唯一依据）
# ---------------------------------------------------------------------------
def test_tc24_super_pp2_normal_pp1() -> None:
    """TC-24：超特性 PP2（pp_cost.super）；普通特性 PP1（pp_cost.normal）。"""
    eng = make_engine()
    sup = eng.select_traits(make_player(5), make_snap(normal=N_POOL, gold=G_POOL),
                            [], super_trait="trait_fire_15", job_tier_index=5,
                            ctx=make_ctx())
    assert sup["ok"] is True and sup["pp_used"] == 2
    norm = eng.select_traits(make_player(3), make_snap(normal=N_POOL),
                             ["trait_burn_boost"], job_tier_index=3, ctx=make_ctx())
    assert norm["ok"] is True and norm["pp_used"] == 1


# ---------------------------------------------------------------------------
# INH-01 候选清单来源（不可凭空继承）
# ---------------------------------------------------------------------------
def test_inh01_trait_must_come_from_pool() -> None:
    """INH-01：特性须来自投料候选清单——池外特性拒绝「不可凭空继承」。"""
    eng = make_engine()
    res = eng.select_traits(make_player(3), make_snap(normal=N_POOL),
                            ["trait_fire_15"], job_tier_index=3, ctx=make_ctx())
    assert res["ok"] is False and res["reason"] == "not_in_pool"
    assert "候选清单" in res["message"]


# ---------------------------------------------------------------------------
# 候选池读取 + apply_to_snapshot + check_placement_conflict（供批6A 结算复核）
# ---------------------------------------------------------------------------
def test_pool_readers() -> None:
    """pool_normal/pool_gold：从会话快照候选池取普通/金色池（INH-01/TSC-13）。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, gold=G_POOL)
    assert eng.pool_normal(snap) == N_POOL
    assert eng.pool_gold(snap) == G_POOL
    assert eng.pool_normal(None) == []
    assert eng.pool_gold({}) == []


def test_apply_snapshot_increments_version_and_step() -> None:
    """apply_to_snapshot：version 递增 + step=inherit + 原快照只读（INH-08/§7.1 行4）。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, version=3)
    snap2 = eng.apply_to_snapshot(snap, ["trait_burn_boost"], pp_used=1)
    assert snap2["version"] == 4
    assert snap2["step"] == "inherit"
    assert snap2["pp"]["used"] == 1
    assert snap["version"] == 3  # 原快照不变（纯函数）


def test_placement_conflict_group_and_repeatable() -> None:
    """check_placement_conflict：结算复核 group 互斥 + repeatable=false 重复（INH-10/11）。"""
    eng = make_engine()
    snap = make_snap(normal=N_POOL, traits=["trait_burn_boost", "trait_burn_snap"])
    r1 = eng.check_placement_conflict(snap, [], make_ctx())
    assert r1["ok"] is False
    assert any(c["kind"] == "group" and c["group"] == "fire_boost"
               for c in r1["conflicts"])
    snap2 = make_snap(normal=N_POOL, traits=["trait_burn_boost", "trait_burn_boost"])
    r2 = eng.check_placement_conflict(snap2, [], make_ctx())
    assert r2["ok"] is False
    assert any(c["kind"] == "repeatable" and c["trait_id"] == "trait_burn_boost"
               for c in r2["conflicts"])
    snap3 = make_snap(normal=N_POOL, traits=["trait_heal_boost", "trait_heal_boost"])
    r3 = eng.check_placement_conflict(snap3, [], make_ctx())
    assert r3["ok"] is True  # repeatable=true 可重复
    snap4 = make_snap(normal=N_POOL, traits=["trait_burn_boost"],
                      gold_slot="trait_fire_15")
    r4 = eng.check_placement_conflict(snap4, [], make_ctx())
    assert r4["ok"] is False  # 金色第 4 位 + 普通位同组 → 成品共存冲突
    assert any(c["kind"] == "group" and "trait_fire_15" in c["traits"]
               for c in r4["conflicts"])
