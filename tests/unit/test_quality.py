"""品质系统引擎单测（M8 批1·路1B · qbot_rpg/core/quality.py）——细化 TC-01~TC-11 引擎可承载部分。

文件：tests/unit/test_quality.py
创建：2026-08-29
作者：Hermes 子agent-1B
功能：QualitySystem 品质系统引擎单测——档位判定/系数/聚合/批量/上限叠加/降级 + 配置注入。

依据：docs/细化/细化_2c4e_品质与特性.md 五（TC-01~TC-26）+ 一（QLT-01~13）+
      docs/m8_contract_核心机制.md §四（QLT-01~13）+ docs/m8_contract_数据与校验.md §五
      （quality_tiers/quality_coef 键集 common/uncommon/rare/legendary，拍板②）+
      批0 落地 content/test_demo/settings.json alchemy 段（[lo,hi] 列表形态）。

覆盖矩阵（每条正例 + 负例，断言精确数值/档位）：
  TC-01 边界落档 39/40/59/60/79/80/100（QLT-02/03）+ 区间内分/越域防御
  TC-02 均值四舍五入 70/70/80→73（QLT-06 工程补白 Q-1）+ 半值上取整/空列表防御
  TC-03 系数 0.8/1.0/1.2/1.5（QLT-04）+ effect_value 乘算 + 未知档位中性 1.0
  TC-04 批量平均品质（QLT-07 均值口径；引擎只算档、特性归会话层）
  TC-05 上限叠加 extra_cap 生效且 ≤100（QLT-08 工程补白 Q-2）
  TC-08 未达标降一档（QLT-10）
  TC-09 降两档 + 传说全不达标降至普通封底（QLT-10 工程补白 Q-3）
  补充：tier_index/index_to_tier 换算 + 降档分数落档不变量 + 配置注入兼容 settings 形态

测试风格对齐 tests/unit/test_levelup.py / test_shop_models.py：纯 pytest、零 NoneBot、
断言具体数值/档位；引擎侧 TC-06/07/10/11（加成道具限次/刻度判定/职业门槛/反馈分级）
属会话/指令层，本引擎零接触（不承载）。
"""

from __future__ import annotations

from qbot_rpg.core.quality import (
    ABSOLUTE_QUALITY_MAX,
    QUALITY_KEYS,
    QUALITY_KEYS_CN,
    QualitySystem,
)


def _qs() -> QualitySystem:
    """默认四档引擎（缺省默认值兜底，对齐批0 settings）。"""
    return QualitySystem()


# ---------------------------------------------------------------------------
# TC-01 品质分边界落档（QLT-02/03）
# ---------------------------------------------------------------------------
def test_tc01_boundary_scores_land_tiers() -> None:
    """TC-01 正例：四档区间边界 39/40/59/60/79/80/100 精确落档（QLT-03 跳档点）。"""
    qs = _qs()
    assert qs.score_to_tier(0) == "common"
    assert qs.score_to_tier(39) == "common"  # 39→普通
    assert qs.score_to_tier(40) == "uncommon"  # 40→精良
    assert qs.score_to_tier(59) == "uncommon"  # 59→精良
    assert qs.score_to_tier(60) == "rare"  # 60→史诗
    assert qs.score_to_tier(79) == "rare"  # 79→史诗
    assert qs.score_to_tier(80) == "legendary"  # 80→传说
    assert qs.score_to_tier(100) == "legendary"  # 100→传说


def test_tc01_interval_inner_scores() -> None:
    """TC-01 负例补充：区间内分数不误落邻档（38/41/50/70/78/81）。"""
    qs = _qs()
    assert qs.score_to_tier(38) == "common"
    assert qs.score_to_tier(41) == "uncommon"
    assert qs.score_to_tier(50) == "uncommon"
    assert qs.score_to_tier(70) == "rare"
    assert qs.score_to_tier(78) == "rare"
    assert qs.score_to_tier(81) == "legendary"


def test_tc01_out_of_domain_defensive_clamp() -> None:
    """【工程补白 Q-4】越域分数裁剪到覆盖域落档（不抛异常）。"""
    qs = _qs()
    assert qs.score_to_tier(-5) == "common"
    assert qs.score_to_tier(150) == "legendary"


# ---------------------------------------------------------------------------
# TC-02 成品品质分 = 投料材料均值四舍五入（QLT-06 工程补白 Q-1）
# ---------------------------------------------------------------------------
def test_tc02_aggregate_mean_round_half_up() -> None:
    """TC-02 正例：70/70/80→73（均值 73.33 四舍五入）；半值上取整；单材料原样；空列表 0。"""
    qs = _qs()
    assert qs.aggregate_quality([70, 70, 80]) == 73  # 220/3=73.33→73（TC-02 口径）
    assert qs.aggregate_quality([85, 90]) == 88  # 87.5→88（半值上取整）
    assert qs.aggregate_quality([70, 71]) == 71  # 70.5→71（round-half-up，
    #   非 Python round(70.5)=70 银行家舍入）
    assert qs.aggregate_quality([85]) == 85
    assert qs.aggregate_quality([]) == 0  # 空列表防御返回 0


def test_tc02_aggregate_negative_cases() -> None:
    """TC-02 负例：非边界均值不误进位/不误档。"""
    qs = _qs()
    assert qs.aggregate_quality([70, 70, 79]) == 73  # 219/3=73.0 精确
    assert qs.aggregate_quality([30, 30, 30]) == 30
    assert qs.aggregate_quality([84]) == 84  # 单材料不聚合不改变


# ---------------------------------------------------------------------------
# TC-03 档位系数与效果数值（QLT-04）
# ---------------------------------------------------------------------------
def test_tc03_quality_coef() -> None:
    """TC-03 正例：四档系数 0.8/1.0/1.2/1.5 精确。"""
    qs = _qs()
    assert qs.coef_for("common") == 0.8
    assert qs.coef_for("uncommon") == 1.0
    assert qs.coef_for("rare") == 1.2
    assert qs.coef_for("legendary") == 1.5


def test_tc03_effect_value_scaling() -> None:
    """TC-03 正例：成品效果数值 = 基准 × 档位系数（史诗×1.2 / 传说×1.5 / 普通×0.8 / 精良×1.0）。"""
    qs = _qs()
    assert qs.effect_value(100, "common") == 80.0
    assert qs.effect_value(100, "uncommon") == 100.0
    assert qs.effect_value(100, "rare") == 120.0
    assert qs.effect_value(100, "legendary") == 150.0


def test_tc03_effect_value_negative() -> None:
    """TC-03 负例：基准 0 → 0；未知档位中性系数 1.0（防御，不放大也不缩小）。"""
    qs = _qs()
    assert qs.effect_value(0, "legendary") == 0.0
    assert qs.coef_for("unknown_tier") == 1.0
    assert qs.effect_value(50, "unknown_tier") == 50.0


# ---------------------------------------------------------------------------
# TC-04 批量平均品质（QLT-07，均值口径；引擎只算档、特性归会话层）
# ---------------------------------------------------------------------------
def test_tc04_batch_tier_by_average() -> None:
    """TC-04 正例：批量按平均品质档出货（73→rare / 88→legendary / 40→uncommon）。"""
    qs = _qs()
    assert qs.batch_tier([70, 70, 80]) == "rare"  # 均值 73 → rare（与 TC-02 同口径）
    assert qs.batch_tier([85, 90]) == "legendary"  # 均值 88 → legendary
    assert qs.batch_tier([40, 40, 40]) == "uncommon"  # 均值 40 → uncommon


def test_tc04_batch_negative() -> None:
    """TC-04 负例：批量档不越过均值档；空批量兜底 common。"""
    qs = _qs()
    assert qs.batch_tier([70, 70, 79]) == "rare"  # 73 → rare，非 legendary
    assert qs.batch_tier([30, 30, 30]) == "common"
    assert qs.batch_tier([]) == "common"  # 空 → 0 → common（防御）


# ---------------------------------------------------------------------------
# TC-05 品质上限三处叠加（QLT-08 工程补白 Q-2）
# ---------------------------------------------------------------------------
def test_tc05_extra_cap_relaxes_reachable_cap() -> None:
    """TC-05 正例：extra_cap 生效——配方原上限 70，SP/核心/挑战 +10 放宽到 80。"""
    qs = _qs()
    assert qs.cap_quality(85, extra_cap=0, hard_max=70) == 70  # 无加成被原上限裁剪
    assert qs.cap_quality(85, extra_cap=10, hard_max=70) == 80  # +10 放宽可达上限
    assert qs.cap_quality(95, extra_cap=30, hard_max=70) == 95  # +30 全放宽（<100）


def test_tc05_cap_never_exceeds_100() -> None:
    """TC-05 正例：品质分仍 ≤100（QLT-08 硬顶，ABSOLUTE_QUALITY_MAX=100）。"""
    qs = _qs()
    assert qs.cap_quality(120, extra_cap=40, hard_max=70) == 100
    assert qs.cap_quality(105, extra_cap=0, hard_max=100) == 100
    assert qs.cap_quality(200, extra_cap=50, hard_max=100) == 100
    assert ABSOLUTE_QUALITY_MAX == 100


def test_tc05_cap_default_negative() -> None:
    """TC-05 负例：默认 hard_max=100 下不误裁剪低分；负分裁剪到 0。"""
    qs = _qs()
    assert qs.cap_quality(85) == 85
    assert qs.cap_quality(95, extra_cap=10) == 95
    assert qs.cap_quality(50, extra_cap=0) == 50
    assert qs.cap_quality(-5, extra_cap=0) == 0


# ---------------------------------------------------------------------------
# TC-08 未达标降一档（QLT-10 工程补白 Q-3）
# ---------------------------------------------------------------------------
def test_tc08_degrade_one_tier() -> None:
    """TC-08 正例：差 1 档降 1 档，降后分数落在降后档位区间顶（hi）。"""
    qs = _qs()
    assert qs.degrade_quality(80, 1) == ("rare", 79)  # 传说→史诗（80 入 [60,79]→79）
    assert qs.degrade_quality(60, 1) == ("uncommon", 59)  # 史诗→精良
    assert qs.degrade_quality(40, 1) == ("common", 39)  # 精良→普通


def test_tc08_degrade_floor_no_negative() -> None:
    """TC-08 负例：普通封底不再降（绝不成负档、不吞材料——降级出货语义）。"""
    qs = _qs()
    assert qs.degrade_quality(30, 1) == ("common", 30)  # 普通降 1 档仍普通，分不变
    assert qs.degrade_quality(39, 1) == ("common", 39)
    assert qs.degrade_quality(30, 3) == ("common", 30)


# ---------------------------------------------------------------------------
# TC-09 降两档 + 传说全不达标降至普通封底（QLT-10）
# ---------------------------------------------------------------------------
def test_tc09_degrade_two_tiers() -> None:
    """TC-09 正例：差 2 档降 2 档。"""
    qs = _qs()
    assert qs.degrade_quality(95, 2) == ("uncommon", 59)  # 传说→精良
    assert qs.degrade_quality(75, 2) == ("common", 39)  # 史诗→普通


def test_tc09_legendary_all_fail_to_common() -> None:
    """TC-09 正例：传说级刻度全不达标 → 降至普通仍出货（最低普通封底）。"""
    qs = _qs()
    assert qs.degrade_quality(100, 3) == ("common", 39)  # 差 3 档 → 普通封底
    assert qs.degrade_quality(88, 5) == ("common", 39)  # 差 5 档也封底普通（绝不成负档）
    assert qs.degrade_quality(80, 1) != ("common", 39)  # 只差 1 档 → 史诗，非普通


def test_tc09_degrade_nonpositive_levels() -> None:
    """TC-09 负例：levels ≤0 → 不降级原样返回（防御）。"""
    qs = _qs()
    assert qs.degrade_quality(85, 0) == ("legendary", 85)
    assert qs.degrade_quality(85, -2) == ("legendary", 85)


def test_degrade_score_maps_back_to_tier() -> None:
    """不变量【工程补白 Q-3】：降档后分数落降后档位区间，score_to_tier(降后分数) == 降后档位。"""
    qs = _qs()
    for score in (0, 20, 39, 40, 59, 60, 79, 80, 100):
        for levels in (0, 1, 2, 3, 5):
            tier, s = qs.degrade_quality(score, levels)
            assert qs.score_to_tier(s) == tier, (score, levels, tier, s)


# ---------------------------------------------------------------------------
# 档位序号换算（tier_index / index_to_tier，供降级与珠升阶下一步）
# ---------------------------------------------------------------------------
def test_tier_index_roundtrip() -> None:
    """档位序号 0-3 换算 + 双向往返一致（QLT-03 单调序）。"""
    qs = _qs()
    assert qs.tier_index("common") == 0
    assert qs.tier_index("uncommon") == 1
    assert qs.tier_index("rare") == 2
    assert qs.tier_index("legendary") == 3
    assert qs.index_to_tier(0) == "common"
    assert qs.index_to_tier(3) == "legendary"
    assert [qs.index_to_tier(i) for i in range(4)] == ["common", "uncommon", "rare", "legendary"]
    assert [qs.index_to_tier(qs.tier_index(t)) for t in QUALITY_KEYS] == list(QUALITY_KEYS)


def test_index_to_tier_clamp_and_unknown() -> None:
    """越界序号裁剪（防负档）；未知档位序号回落 0（普通封底，防御）。"""
    qs = _qs()
    assert qs.index_to_tier(-1) == "common"
    assert qs.index_to_tier(99) == "legendary"
    assert qs.tier_index("no_such_tier") == 0


# ---------------------------------------------------------------------------
# 档位中文名（拍板② 键集 ↔ 中文）与常量
# ---------------------------------------------------------------------------
def test_tier_labels() -> None:
    """档位中文名：普通/精良/史诗/传说；缺标签回落键名自身。"""
    qs = _qs()
    assert qs.tier_label("common") == "普通"
    assert qs.tier_label("uncommon") == "精良"
    assert qs.tier_label("rare") == "史诗"
    assert qs.tier_label("legendary") == "传说"
    assert qs.tier_label("unknown") == "unknown"


def test_quality_key_constants() -> None:
    """键集常量与拍板② 对齐（common/uncommon/rare/legendary ↔ 普通/精良/史诗/传说）。"""
    assert QUALITY_KEYS == ("common", "uncommon", "rare", "legendary")
    assert QUALITY_KEYS_CN == ("普通", "精良", "史诗", "传说")
    assert list(QUALITY_KEYS) == _qs().tier_order


# ---------------------------------------------------------------------------
# 构造器配置注入 + 批0 settings 形态兼容
# ---------------------------------------------------------------------------
def test_constructor_defaults_and_fallbacks() -> None:
    """缺省默认值兜底：None/空配置 → 默认四档区间与系数。"""
    assert _qs().score_to_tier(39) == "common"
    assert _qs().score_to_tier(40) == "uncommon"
    assert _qs().coef_for("legendary") == 1.5
    q_empty = QualitySystem(quality_tiers={}, quality_coef={})
    assert q_empty.score_to_tier(80) == "legendary"
    assert q_empty.coef_for("common") == 0.8


def test_constructor_settings_json_alchemy_shape() -> None:
    """批0 落地 settings.json alchemy 段原样形态（[lo,hi] 列表 + 系数）构造兼容。"""
    tiers = {
        "common": [0, 39],
        "uncommon": [40, 59],
        "rare": [60, 79],
        "legendary": [80, 100],
    }
    coef = {"common": 0.8, "uncommon": 1.0, "rare": 1.2, "legendary": 1.5}
    qs = QualitySystem(quality_tiers=tiers, quality_coef=coef)
    assert qs.score_to_tier(39) == "common"
    assert qs.score_to_tier(40) == "uncommon"
    assert qs.score_to_tier(59) == "uncommon"
    assert qs.score_to_tier(60) == "rare"
    assert qs.score_to_tier(79) == "rare"
    assert qs.score_to_tier(80) == "legendary"
    assert qs.coef_for("common") == 0.8
    assert qs.coef_for("rare") == 1.2
    assert qs.tiers["legendary"] == (80, 100)


def test_constructor_minmax_object_shape() -> None:
    """兼容 {min, max} 对象形态（工程补白 P-1，alchemy_settings 同款）。"""
    tiers = {
        "common": {"min": 0, "max": 39},
        "uncommon": {"min": 40, "max": 59},
        "rare": {"min": 60, "max": 79},
        "legendary": {"min": 80, "max": 100},
    }
    qs = QualitySystem(quality_tiers=tiers)
    assert qs.score_to_tier(59) == "uncommon"
    assert qs.score_to_tier(60) == "rare"


def test_three_tier_configurable() -> None:
    """档位数可配（3/5/7，QLT-05/拍板②）：3 档配置区间判定/标签回落/系数注入生效。"""
    tiers = {"common": [0, 59], "rare": [60, 89], "legendary": [90, 100]}
    coef = {"common": 0.8, "rare": 1.2, "legendary": 1.5}
    qs = QualitySystem(quality_tiers=tiers, quality_coef=coef)
    assert qs.tier_count == 3
    assert qs.score_to_tier(59) == "common"
    assert qs.score_to_tier(60) == "rare"
    assert qs.score_to_tier(89) == "rare"
    assert qs.score_to_tier(90) == "legendary"
    assert qs.tier_label("common") == "普通"
    assert qs.tier_label("rare") == "史诗"
    assert qs.coef_for("rare") == 1.2
    assert qs.degrade_quality(100, 1) == ("rare", 89)  # 3 档下 传说→史诗
    assert qs.degrade_quality(100, 2) == ("common", 59)  # 3 档下 差 2 → 普通封底
    assert qs.tier_label("no_such") == "no_such"  # 缺标签回落键名


def test_readonly_snapshots() -> None:
    """只读快照：tiers/tier_order/tier_count 供批6A/批7B 消费（不暴露内部可变引用）。"""
    qs = _qs()
    assert qs.tiers == {
        "common": (0, 39),
        "uncommon": (40, 59),
        "rare": (60, 79),
        "legendary": (80, 100),
    }
    assert qs.tier_order == ["common", "uncommon", "rare", "legendary"]
    assert qs.tier_count == 4
    qs.tiers["common"] = (0, 0)  # 快照副本可改但不得影响引擎
    assert _qs().score_to_tier(39) == "common"
