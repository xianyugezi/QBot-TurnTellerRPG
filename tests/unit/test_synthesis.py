"""SynthesisEngine 单测（M8 批2·路2A）——细化_2c4a TC-01/02/07/08/09/15/16/23 引擎可承载部分。

文件名：tests/unit/test_synthesis.py
创建时间：2026-08-29
作者：Hermes 子agent-2A
功能描述：qbot_rpg.core.synthesis.SynthesisEngine 纯函数直测（对齐 test_proficiency/test_shop
  模式）：跨职业区间准入（TC-01/02）、synth_allowed 深度拦截/放行提示（TC-07/08/09）、标准版产出
  （TC-15）、数量上限提示不拦 + 缺料全拒差异（TC-16/23）、熟练经验=配方等级×1（CASC-01/EXP-03）、
  图鉴回调被调、不耗能量断言（LAY-05）。

依据：
  - docs/细化/细化_2c4a_炼金三层漏斗.md：LAY-01/LAY-04a/LAY-05/CASC-01/CASC-02/CASC-04/JOB-03；
    验收 TC-01/02/07/08/09/15/16/23。
  - docs/m8_contract_指令契约.md §1 /合成（GU-01~04/F-01/M-01）+ §3.4（max_qty 拍板⑤）。
  - qbot_rpg/core/proficiency.py（level = 档位索引 0~6：level 3=专家 21-30、level 4=大师 31-40，
    默认 job_tier_map——本文件夹具按此口径构造，TC-01 叙事「25 级/31 级」落为档位索引）。

【工程补白 · 注记】
  - ctx 顶层即玩家状态（proficiency/currencies/inventory），settings 走引擎构造器注入（单源，
    对齐 core/synthesis.py 工程补白 1）——本文件夹具与实现一致。
  - 熟练档位口径：ProficiencyEngine 存档 level = 档位索引 0~6（对齐 proficiency.py 补白 3），
    非叙事「角色 25 级」；TC-01 用 level 3=专家 / level 4=大师 精确复现「专家拒 / 大师放行」。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.proficiency import ProficiencyEngine
from qbot_rpg.core.synthesis import DEFAULT_MAX_QTY, SynthesisEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

ITEMS: Dict[str, Mapping[str, Any]] = {
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable"},
    "deep_core": {"id": "deep_core", "name": "秘银核心", "type": "material"},
}

RECIPES: Dict[str, Mapping[str, Any]] = {
    # 见习级普通配方（level 5 ∈ 见习 1-5）——TC-15/16/23 / 熟练经验
    "rcp_mana_potion": {
        "id": "rcp_mana_potion", "name": "魔力药水配方", "kind": "craft", "level": 5,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2}],
        "output": {"item": "mana_potion", "count": 1},
        "cost": {"coins": 30, "gem": 0},
    },
    # 单材料+金币配方（对齐 TC-23 契约文案「缺 水结晶×5 + 金币 30」）
    "rcp_pure": {
        "id": "rcp_pure", "name": "纯净药水配方", "kind": "craft", "level": 5,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "water_crystal", "count": 5}],
        "output": {"item": "mana_potion", "count": 1},
        "cost": {"coins": 30, "gem": 0},
    },
    # 大师级普通配方（level 31 ∈ 大师 31-40）——TC-01/09
    "rcp_flame_bomb": {
        "id": "rcp_flame_bomb", "name": "火焰弹配方", "kind": "craft", "level": 31,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "moon_grass", "count": 3}],
        "output": {"item": "flame_bomb", "count": 1},
        "cost": {"coins": 200, "gem": 0},
    },
    # 深度配方默认 synth_allowed=false（CASC-04）——TC-07/09
    "rcp_deep": {
        "id": "rcp_deep", "name": "深度秘银配方", "kind": "craft", "level": 31,
        "synth_allowed": False, "master_only": True,
        "materials": [{"id": "deep_core", "count": 2}],
        "output": {"item": "deep_core", "count": 1},
        "cost": {"coins": 0, "gem": 0},
    },
    # 深度配方内容包改 synth_allowed=true（CASC-04）——TC-08
    "rcp_deep_true": {
        "id": "rcp_deep_true", "name": "深度开放配方", "kind": "craft", "level": 31,
        "synth_allowed": True, "master_only": True,
        "materials": [{"id": "deep_core", "count": 1}],
        "output": {"item": "deep_core", "count": 1},
        "cost": {"coins": 0, "gem": 0},
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "mode": "full",
        "max_qty": DEFAULT_MAX_QTY,
        # 默认 job_tier_map（细化_2c4a JOB-03 / proficiency.py 缺省兜底）
        "job_tier_map": {
            "见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99],
        },
    },
}


def _engine(settings: Optional[Mapping[str, Any]] = None,
            prof: Optional[ProficiencyEngine] = None) -> SynthesisEngine:
    """构造引擎：settings 构造器注入（单源）；prof 缺省走内部
    ProficiencyEngine(settings=settings)。"""
    return SynthesisEngine(
        prof=prof, settings=settings if settings is not None else DEFAULT_SETTINGS
    )


def make_ctx(**over: Any) -> MutableMapping[str, Any]:
    """全字段玩家合成 ctx（core/synthesis.py 工程补白 1 契约；每场景新造避免互污染）。"""
    base: Dict[str, Any] = {
        "qid": "u1",
        "name": "阿伟",
        "proficiency": {},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {},
        "items": ITEMS,
        "recipe": RECIPES,
    }
    base.update(over)
    return base


def _fishing_player(level: int = 0, exp: int = 0) -> MutableMapping[str, Any]:
    """钓鱼职业玩家（level = 档位索引 0~6：3=专家 21-30 / 4=大师 31-40，对齐 proficiency.py）。"""
    return make_ctx(proficiency={
        "fishing": {"level": level, "exp": exp, "sp_earned": 0, "sp_used": 0, "unlocks": {}},
    })


def _stocked_pure_player() -> MutableMapping[str, Any]:
    """见习钓鱼玩家 + 满足 rcp_pure（水结晶×5 + 金币 30）材料。"""
    ctx = _fishing_player(level=0)
    ctx["currencies"]["coins"] = 100
    ctx["inventory"] = {"water_crystal": 5}
    return ctx


# ---------------------------------------------------------------------------
# TC-01 跨职业区间准入：拒绝 / 放行（CASC-02/JOB-03）
# ---------------------------------------------------------------------------
def test_tc01_range_gate_reject_then_allow() -> None:
    """钓鱼专家（档位 3，区间 21-30）→ /合成 大师级配方（level 31）拒绝；升大师（档位 4）→ 放行。"""
    eng = _engine()
    ctx = _fishing_player(level=3, exp=850)
    res = eng.check_eligible(ctx, "rcp_flame_bomb")
    assert res["ok"] is False
    assert res["reason"] == "level_insufficient"
    assert "等级不足" in res["message"]
    assert "钓鱼" in res["message"]  # 提示缺哪种职业（TC-02 口径）

    ctx2 = _fishing_player(level=4)
    res2 = eng.check_eligible(ctx2, "rcp_flame_bomb")
    assert res2["ok"] is True
    assert res2["job_id"] == "fishing"
    assert res2["recipe_level"] == 31


# ---------------------------------------------------------------------------
# TC-02 无职业拒绝（错误模板「等级不足」）
# ---------------------------------------------------------------------------
def test_tc02_no_job_reject() -> None:
    """新玩家无任何制造职业熟练 → 拒绝并提示未习得任何制造/资源职业。"""
    eng = _engine()
    ctx = make_ctx()  # 无 proficiency 桶
    res = eng.check_eligible(ctx, "rcp_mana_potion")
    assert res["ok"] is False
    assert res["reason"] == "level_insufficient"
    assert "等级不足" in res["message"]
    assert "未习得任何制造/资源职业" in res["message"]


# ---------------------------------------------------------------------------
# TC-07/08/09 synth_allowed 深度拦截/放行（CASC-04）
# ---------------------------------------------------------------------------
def test_tc07_deep_synth_not_allowed_reject() -> None:
    """深度配方（master_only=true）默认 synth_allowed=false → /合成 拒绝「深度未解锁」。"""
    eng = _engine()
    ctx = _fishing_player(level=4)  # 钓鱼大师，但深度产出不可经合成层获取
    res = eng.check_eligible(ctx, "rcp_deep")
    assert res["ok"] is False
    assert res["reason"] == "synth_not_allowed"
    assert "深度未解锁" in res["message"]


def test_tc08_deep_synth_allowed_hint() -> None:
    """内容包将深度配方 synth_allowed=true → 可执行，返回提示「绕过深度炼金玩法」不阻断。"""
    eng = _engine()
    ctx = _fishing_player(level=4)
    res = eng.check_eligible(ctx, "rcp_deep_true")
    assert res["ok"] is True
    assert res["hint"] == "提示：此深度配方可被合成，将绕过深度炼金玩法"


def test_tc09_master_can_normal_not_deep() -> None:
    """钓鱼大师 → 可合大师级普通配方；同等级深度配方（synth_allowed=false）
    不可合（跨职业只通合成层）。"""
    eng = _engine()
    ctx = _fishing_player(level=4)
    assert eng.check_eligible(ctx, "rcp_flame_bomb")["ok"] is True
    assert eng.check_eligible(ctx, "rcp_deep")["ok"] is False


# ---------------------------------------------------------------------------
# TC-15 标准版产出：品质固定无特性（LAY-04a）
# ---------------------------------------------------------------------------
def test_tc15_standard_output_fixed_quality_no_traits() -> None:
    """/合成 魔力药水 → 标准版：品质固定（标准）、无任何特性/超特性/进化/核心类。"""
    eng = _engine()
    so = eng.standard_output(RECIPES["rcp_mana_potion"], ctx=make_ctx())
    assert so["ok"] is True
    assert so["quality_fixed"] is True
    assert so["quality"] == "标准"
    assert so["traits"] == []
    assert so["awaken"] is None
    assert so["evolution"] is None
    assert so["core"] is None
    assert so["item_name"] == "魔力药水"
    assert so["count"] == 1


def test_tc15_synthesize_produces_standard_item() -> None:
    """成功合成入包的就是标准版成品（直接 add_item，无品质/特性字段附加）。"""
    eng = _engine()
    ctx = _stocked_pure_player()
    res = eng.synthesize(ctx, "rcp_pure", 1)
    assert res["ok"] is True
    assert ctx["inventory"]["mana_potion"] == 1  # 标准版直接入包
    assert ctx["inventory"]["water_crystal"] == 0


# ---------------------------------------------------------------------------
# TC-16 数量上限：超限提示不拦（拍板⑤）+ 缺材料全拒差异
# ---------------------------------------------------------------------------
def test_tc16_qty_cap_hint_not_block_and_shortfall() -> None:
    """max_qty=3：请求 10 → 提示「最多一次使用 3 个」不拦、按 3 截断执行；缺料则全拒+差异提示。"""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["alchemy"]["max_qty"] = 3
    eng = _engine(settings=settings)
    # 材料只够 1 份（水结晶 8 需 15）→ 截断后仍缺料 → 全拒不部分执行，差异按截断后数量提示
    ctx = _fishing_player(level=0)
    ctx["currencies"]["coins"] = 100
    ctx["inventory"] = {"water_crystal": 8, "herb": 2}
    res = eng.synthesize(ctx, "rcp_mana_potion", 10)
    assert res["ok"] is False
    assert res["reason"] == "materials"
    assert res["advisory"] == "最多一次使用 3 个"
    assert "缺 水结晶×7" in res["message"]   # 3 份需 15，持有 8 → 差 7
    assert ctx["inventory"]["water_crystal"] == 8  # 全拒：不部分扣料
    assert ctx["currencies"]["coins"] == 100
    # 材料够 3 份 → 按 3 截断执行成功 + 提示
    ctx2 = _fishing_player(level=0)
    ctx2["currencies"]["coins"] = 200
    ctx2["inventory"] = {"water_crystal": 15, "herb": 6}
    res2 = eng.synthesize(ctx2, "rcp_mana_potion", 10)
    assert res2["ok"] is True
    assert res2["produced"]["count"] == 3
    assert "最多一次使用 3 个" in res2["message"]
    assert ctx2["inventory"]["water_crystal"] == 0  # 3 份扣 15


# ---------------------------------------------------------------------------
# TC-23 缺 水结晶×5 + 金币 30 全拒差异提示（GU-04 原子校验）
# ---------------------------------------------------------------------------
def test_tc23_missing_materials_and_coins_all_reject_diff() -> None:
    """/合成 缺 水结晶×5 + 金币 30 → 全拒不部分执行，提示差异「缺 水结晶×5 + 金币 30」。"""
    eng = _engine()
    ctx = _fishing_player(level=0)
    ctx["currencies"]["coins"] = 0   # 金币 0
    ctx["inventory"] = {}            # 无水结晶
    res = eng.synthesize(ctx, "rcp_pure", 1)
    assert res["ok"] is False
    assert res["reason"] == "materials"
    assert "缺 水结晶×5 + 金币 30" in res["message"]
    assert res["produced"] is None
    assert res["exp_gained"] == 0
    # 全拒：零副作用（无扣料无入包无经验）
    assert ctx["inventory"] == {}
    assert ctx["currencies"]["coins"] == 0
    assert ctx["proficiency"]["fishing"]["exp"] == 0


# ---------------------------------------------------------------------------
# 熟练经验 = 配方等级 × 成品数（CASC-01/EXP-03，source='craft'）
# ---------------------------------------------------------------------------
def test_exp_gained_equals_recipe_level_x_outputs() -> None:
    """配方等级 5 × 成品 2 = 10 熟练，入账到达标职业（钓鱼），经验=配方等级×1 口径。"""
    eng = _engine()
    ctx = _fishing_player(level=0, exp=0)
    ctx["currencies"]["coins"] = 200
    ctx["inventory"] = {"water_crystal": 10, "herb": 4}
    res = eng.synthesize(ctx, "rcp_mana_potion", 2)
    assert res["ok"] is True
    assert res["exp_gained"] == 10  # 5 × 2 × 1
    node = ctx["proficiency"]["fishing"]
    assert node["exp"] == 10
    assert node["level"] == 0  # 10 < 100 未跨阈值（熟练引擎口径：经验=当前级内余量）


def test_exp_single_craft_recipe_level_x1() -> None:
    """单次合成 1 个成品：熟练经验 = 配方等级 ×1（CASC-01 基准）。"""
    eng = _engine()
    ctx = _stocked_pure_player()
    res = eng.synthesize(ctx, "rcp_pure", 1)
    assert res["ok"] is True
    assert res["exp_gained"] == 5  # 配方等级 5 × 1


# ---------------------------------------------------------------------------
# 图鉴回调被调（工程补白 10）
# ---------------------------------------------------------------------------
def test_on_codex_callback_invoked() -> None:
    """on_codex 回调被调用（player, recipe_id, count）；成功路径后图鉴点亮。"""
    eng = _engine()
    ctx = _fishing_player(level=0)
    ctx["currencies"]["coins"] = 200
    ctx["inventory"] = {"water_crystal": 10, "herb": 4}
    calls: list = []
    res = eng.synthesize(
        ctx, "rcp_mana_potion", 2, on_codex=lambda p, rid, c: calls.append((rid, c))
    )
    assert res["ok"] is True
    assert calls == [("rcp_mana_potion", 2)]


def test_on_codex_absent_skipped() -> None:
    """默认 on_codex=None → 图鉴点亮跳过（不报错）。"""
    eng = _engine()
    ctx = _stocked_pure_player()
    res = eng.synthesize(ctx, "rcp_pure", 1)
    assert res["ok"] is True


# ---------------------------------------------------------------------------
# 不耗能量（LAY-05/ENG-07：保底通道）
# ---------------------------------------------------------------------------
def test_no_energy_consumed() -> None:
    """/合成 不耗能量：ctx 能量桶原样（即使 energy_enabled 开启/能量为 0 也永可用）。"""
    eng = _engine()
    ctx = _stocked_pure_player()
    ctx["energy"] = {"current": 0, "max": 5}  # 能量 0 仍可合成（TC-22 合成豁免语义）
    res = eng.synthesize(ctx, "rcp_pure", 1)
    assert res["ok"] is True
    assert ctx["energy"] == {"current": 0, "max": 5}  # 未耗能量


# ---------------------------------------------------------------------------
# 补充：多职业达标取等级最高者（EXP-03 工程补白）/ 序号解析 / 边界
# ---------------------------------------------------------------------------
def test_multi_job_eligible_picks_highest_level() -> None:
    """多职业同时达标 → 取等级最高者（EXP-03 工程补白 3）；等级最高者信息入回执。"""
    eng = _engine()
    ctx = make_ctx(proficiency={
        "fishing": {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}},
        "forging": {"level": 3, "exp": 0, "sp_earned": 0, "sp_used": 0,
                    "unlocks": {}},  # 专家 21-30
    })
    # level 25 配方 ∈ 专家区间 → forging（等级更高）达标，fishing（见习 1-5）不达标
    ctx["recipe"] = dict(RECIPES)
    ctx["recipe"]["rcp_lv25"] = {
        "id": "rcp_lv25", "name": "精铸配方", "kind": "craft", "level": 25,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "moon_grass", "count": 1}],
        "output": {"item": "flame_bomb", "count": 1},
        "cost": {"coins": 0, "gem": 0},
    }
    res = eng.check_eligible(ctx, "rcp_lv25")
    assert res["ok"] is True
    assert res["job_id"] == "forging"


def test_recipe_resolve_by_sequence() -> None:
    """P-01 序号兜底：'1' → 注册表第一项（rcp_mana_potion）。"""
    eng = _engine()
    ctx = _fishing_player(level=0)
    res = eng.check_eligible(ctx, "1")
    assert res["ok"] is True
    assert res["recipe"]["id"] == "rcp_mana_potion"


def test_recipe_not_found() -> None:
    """GU-02：配方不存在 → 拒绝。"""
    eng = _engine()
    res = eng.check_eligible(make_ctx(), "不存在配方")
    assert res["ok"] is False
    assert res["reason"] == "recipe_not_found"
    assert res["message"] == "❌ 配方不存在"


def test_mode_off_reject() -> None:
    """GU-01：settings.alchemy.mode=off → 炼金系统已关闭。"""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["alchemy"]["mode"] = "off"
    eng = _engine(settings=settings)
    res = eng.check_eligible(_stocked_pure_player(), "rcp_pure")
    assert res["ok"] is False
    assert res["reason"] == "mode_off"
    assert "已关闭" in res["message"]


def test_invalid_count_reject() -> None:
    """count 归一：0/负数/非数字 → 「数量无效」全拒。"""
    eng = _engine()
    ctx = _stocked_pure_player()
    res = eng.synthesize(ctx, "rcp_pure", 0)
    assert res["ok"] is False
    assert res["reason"] == "invalid_count"
    assert ctx["inventory"]["water_crystal"] == 5  # 零副作用


def test_prof_injected_engine() -> None:
    """构造器注入 prof（真实 ProficiencyEngine）→ 区间准入与缺省 prof 同口径。"""
    prof = ProficiencyEngine(settings=DEFAULT_SETTINGS)
    eng = SynthesisEngine(prof=prof, settings=DEFAULT_SETTINGS)
    ctx = _fishing_player(level=4)
    assert eng.check_eligible(ctx, "rcp_flame_bomb")["ok"] is True
    assert eng.check_eligible(ctx, "rcp_deep")["ok"] is False


def test_success_message_m01_format() -> None:
    """成功消息 M-01 格式：✅ 魔力药水 ×1（消耗：水结晶×5 + 草药×2 + 金币 30）。"""
    eng = _engine()
    ctx = _stocked_pure_player()
    ctx["inventory"]["herb"] = 2
    ctx["currencies"]["coins"] = 100
    res = eng.synthesize(ctx, "rcp_mana_potion", 1)
    assert res["ok"] is True
    assert res["message"] == "✅ 魔力药水 ×1（消耗：水结晶×5 + 草药×2 + 金币 30）"
