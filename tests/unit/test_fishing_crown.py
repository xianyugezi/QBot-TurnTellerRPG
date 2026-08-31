"""M10 钓鱼·批3·路3B：冠级百分位生成与六档判定单测（tests/unit/test_fishing_crown.py）。

文件名：tests/unit/test_fishing_crown.py
创建时间：2026-08-31
作者：Hermes 子agent-3B（M10 钓鱼实现组批3·路3B：冠级六档 T11）

覆盖：细化_2c1a §六 B 冠级六档判定（TC-05~09 / TC-09b）+ 确定性重放 +
      gen_size_weight 线性插值边界（TC-06）+ rng 注入三态容错。
用例数：28 例（≥22 硬性要求；含种子化收敛 TC-05 双种子 2 例）。

依据：
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §二（2.1 L98-109 / 2.2 L111-122 /
    2.3 L124-135）+ §六 TC-05~09 / TC-09b
  - docs/m10_shared_contract.md §一（crown_thresholds 默认 5/85/95）/ §五 铁律
铁律：零 NoneBot import；确定性测试种子化（无裸 random）；docstring 不含
      计时器函数字面量（M43 探针，用「零定时器/零睡眠」措辞）；无 emoji。
"""

from __future__ import annotations

import random
from typing import Dict, Mapping, Tuple, cast

from qbot_rpg.core.fishing_crown import (
    CROWN_BIG_GOLD,
    CROWN_BIG_SILVER,
    CROWN_GOLD,
    CROWN_LABELS,
    CROWN_NORMAL,
    CROWN_ORDER,
    CROWN_REVERSE,
    CROWN_SILVER,
    DEFAULT_CROWN_THRESHOLDS,
    crown_of,
    gen_size_weight,
)
from qbot_rpg.content.fishing_models import FishDef

# 夹具基准行（细化 §1.3 示例鱼种 + 共享契约 §二：size 10~60 / weight 0.3~5.0）
_SILVER_CARP: Dict[str, object] = {
    "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
    "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
    "seasons": [], "periods": [], "hours": ["00:00-24:00"],
    "spots": ["map_laketown:pier_01"], "preferred_bait": ["饵_蚯蚓"],
    "codex_text": {"desc": "鳞片泛银光的鲤，黄昏时最活跃。", "unit": "cm-kg",
                   "best_mask": "{name} · 最大 {best_size}cm/{best_weight}kg · "
                                "{best_crown} · 逆金冠×{reverse_crown_count}"},
    "king": None,
}

# 默认阈值（细化 §2.1：reverse=5 / silver=85 / gold=95）
_T = DEFAULT_CROWN_THRESHOLDS


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _carp() -> FishDef:
    return cast(FishDef, FishDef.from_entry(dict(_SILVER_CARP)))


def _carp_raw() -> Dict[str, object]:
    return dict(_SILVER_CARP)


# ---------------------------------------------------------------------------
# TC-06 线性插值（gen_size_weight 确定性注入）
# ---------------------------------------------------------------------------
class _FixedRng:
    """固定序列 rng：size_pct 命中第一个值、weight_pct 命中第二个值（确定性）。"""

    def __init__(self, values: Tuple[float, ...]) -> None:
        self._values = list(values)

    def random(self) -> float:
        if not self._values:
            raise AssertionError("rng 序列耗尽（每次出鱼恰消费 2 次）")
        return self._values.pop(0)


def test_tc06_interp_mid_fishdef() -> None:
    """TC-06：size_pct=50 → size = 10 + (60-10)×0.5 = 35.0；weight_pct=50 → 2.65。"""
    out = gen_size_weight(_carp(), _FixedRng((0.5, 0.5)))
    assert out["size_pct"] == 50.0
    assert out["weight_pct"] == 50.0
    assert out["size"] == 35.0
    assert abs(out["weight"] - (0.3 + (5.0 - 0.3) * 0.5)) < 1e-9


def test_tc06_interp_mid_mapping() -> None:
    """TC-06（Mapping 形态）：同一插值公式对 raw dict 生效。"""
    out = gen_size_weight(_carp_raw(), _FixedRng((0.5, 0.5)))
    assert out["size"] == 35.0


def test_tc06_size_pct_zero_hits_min() -> None:
    """边界 size_pct=0 → size_min=10.0（百分位不封 100，0 是可达下界）。"""
    out = gen_size_weight(_carp(), _FixedRng((0.0, 0.0)))
    assert out["size_pct"] == 0.0
    assert out["weight_pct"] == 0.0
    assert out["size"] == 10.0
    assert out["weight"] == 0.3


def test_tc06_size_pct_near_max_approaches_max() -> None:
    """边界 size_pct→99.99... 趋近 size_max：0.99999999 → 60（不封 100）。

    百分位域 [0,100) 不含 100，原始插值恒 < max；round(…, 4) 后可能精确
    吸附到 max（59.9999995 → 60.0），语义仍为「趋近上界」。
    """
    out = gen_size_weight(_carp(), _FixedRng((0.99999999, 0.99999999)))
    assert out["size_pct"] < 100.0
    assert out["weight_pct"] < 100.0
    assert out["size"] <= 60.0
    assert out["size"] > 59.9999
    assert out["weight"] <= 5.0
    assert out["weight"] > 4.9999


def test_tc06_rounding_four_decimals() -> None:
    """【工程补白 C-5】插值结果保留 4 位小数（批量结算浮点稳定）。"""
    out = gen_size_weight(_carp(), _FixedRng((0.123456789, 0.987654321)))
    for key in ("size", "weight"):
        v = out[key]
        assert isinstance(v, float)
        assert round(v, 4) == v


def test_gen_size_weight_consumes_two_randoms() -> None:
    """每次出鱼恰消费 2 次 rng.random()（size_pct/weight_pct 独立生成）。"""
    class _TightRng:
        def __init__(self) -> None:
            self.calls = 0

        def random(self) -> float:
            self.calls += 1
            if self.calls > 2:
                raise AssertionError("一次出鱼不应消费超过 2 次随机")
            return 0.5

    tight = _TightRng()
    out = gen_size_weight(_carp(), tight)
    assert tight.calls == 2
    assert out["size_pct"] == 50.0
    assert out["weight_pct"] == 50.0


def test_gen_size_weight_rng_from_ctx() -> None:
    """【工程补白 C-2】rng 缺省 → ctx["rng"] 注入生效（确定性同源）。"""
    rng = _rng(2026)
    via_ctx = gen_size_weight(_carp(), ctx={"rng": rng})
    rng2 = _rng(2026)
    via_arg = gen_size_weight(_carp(), rng2)
    assert via_ctx == via_arg


def test_gen_size_weight_broken_species_defaults_zero() -> None:
    """【工程补白 C-1】区间键缺失/非数字 → 0 兜底不炸（数据合法性归 V1）。"""
    out = gen_size_weight({"id": "broken"}, _FixedRng((0.5, 0.5)))
    assert out["size"] == 0.0
    assert out["weight"] == 0.0


# ---------------------------------------------------------------------------
# 确定性重放（同种子同调用序 → 恒同结果）
# ---------------------------------------------------------------------------
def test_deterministic_replay_same_seed_same_result() -> None:
    """确定性重放：种子 42 双跑逐字段一致（含 pct 与插值数值）。"""
    a = gen_size_weight(_carp(), _rng(42))
    b = gen_size_weight(_carp(), _rng(42))
    assert a == b
    assert a["size_pct"] == b["size_pct"]
    assert a["size"] == b["size"]


def test_deterministic_replay_different_seed_differs() -> None:
    """确定性重放（反例）：种子 42 vs 2026 序列不同 → 结果可区分（非恒等）。"""
    a = gen_size_weight(_carp(), _rng(42))
    b = gen_size_weight(_carp(), _rng(2026))
    assert (a["size_pct"], a["weight_pct"]) != (b["size_pct"], b["weight_pct"])


def test_gen_pcts_in_range() -> None:
    """百分位域：任意种子生成的 size_pct/weight_pct ∈ [0, 100)（均匀分布域）。"""
    for seed in (1, 7, 42, 2026):
        rng = _rng(seed)
        for _ in range(200):
            out = gen_size_weight(_carp(), rng)
            assert 0.0 <= out["size_pct"] < 100.0
            assert 0.0 <= out["weight_pct"] < 100.0


# ---------------------------------------------------------------------------
# TC-07 边界 4.9 vs 5.0（逆金冠严格 <）
# ---------------------------------------------------------------------------
def test_tc07_49_both_below_reverse_is_reverse() -> None:
    """TC-07：size=4.9 且 weight=4.9（双 <5）→ 逆金冠。"""
    assert crown_of(4.9, 4.9, _T) == CROWN_REVERSE


def test_tc07_50_not_reverse() -> None:
    """TC-07：size=5.0 且 weight=4.0 → 任一边 5.0 不判逆金冠（严格 <）。"""
    assert crown_of(5.0, 4.0, _T) != CROWN_REVERSE


def test_tc07_50_both_below_silver_is_normal() -> None:
    """TC-07 补：size=5.0 且 weight=4.0 → 普通（5 未达银冠 85、金冠 95）。"""
    assert crown_of(5.0, 4.0, _T) == CROWN_NORMAL


def test_tc07_49_and_50_mixed() -> None:
    """TC-07 补：size=4.9 且 weight=5.0（一边达 5）→ 非逆金冠 → 普通。"""
    assert crown_of(4.9, 5.0, _T) == CROWN_NORMAL


# ---------------------------------------------------------------------------
# TC-08 边界 84.9 vs 85.0（银冠 >=）、94.9 vs 95.0（金冠 >=）
# ---------------------------------------------------------------------------
def test_tc08_849_below_silver_is_normal() -> None:
    """TC-08：84.9 不达银冠级（<85）→ 普通。"""
    assert crown_of(84.9, 84.9, _T) == CROWN_NORMAL


def test_tc08_850_hits_silver() -> None:
    """TC-08：85.0 达银冠级（>=85）双达 → 大银冠。"""
    assert crown_of(85.0, 85.0, _T) == CROWN_BIG_SILVER


def test_tc08_850_single_hits_silver() -> None:
    """TC-08：85.0 单边达银冠级 → 银冠。"""
    assert crown_of(85.0, 50.0, _T) == CROWN_SILVER


def test_tc08_949_below_gold_is_silver() -> None:
    """TC-08：94.9 不达金冠级（<95）但达银冠级 → 银冠（单边 94.9 ≥85）。"""
    assert crown_of(94.9, 94.9, _T) == CROWN_BIG_SILVER


def test_tc08_950_hits_gold() -> None:
    """TC-08：95.0 达金冠级（>=95）双达 → 大金冠。"""
    assert crown_of(95.0, 95.0, _T) == CROWN_BIG_GOLD


def test_tc08_950_single_hits_gold() -> None:
    """TC-08：95.0 单边达金冠级 → 金冠。"""
    assert crown_of(95.0, 50.0, _T) == CROWN_GOLD


def test_tc08_85_gold_mix_silver() -> None:
    """TC-08 补：85.0 与 95.0 混合（一边达金冠级）→ 金冠。"""
    assert crown_of(95.0, 85.0, _T) == CROWN_GOLD


# ---------------------------------------------------------------------------
# TC-09 混合极端（判定顺序写死）
# ---------------------------------------------------------------------------
def test_tc09_mixed_extreme_gold() -> None:
    """TC-09：size=97（≥95）且 weight=3（<5）→ 金冠（非逆金冠、非大金冠）。"""
    assert crown_of(97.0, 3.0, _T) == CROWN_GOLD


def test_tc09_mixed_extreme_symmetry() -> None:
    """TC-09 对称：size=3（<5）且 weight=97（≥95）→ 金冠（顺序对称）。"""
    assert crown_of(3.0, 97.0, _T) == CROWN_GOLD


def test_tc09_both_extremes_opposite_not_reverse() -> None:
    """TC-09 补：size=97 且 weight=97（双极端高位）→ 大金冠（非逆金冠）。"""
    assert crown_of(97.0, 97.0, _T) == CROWN_BIG_GOLD


def test_tc09_high_low_mix_is_gold_not_big_silver() -> None:
    """TC-09 补：size=90（≥85 未达 95）且 weight=2（<5）→ 金冠? 否——单边 90 仅达银冠。"""
    assert crown_of(90.0, 2.0, _T) == CROWN_SILVER


# ---------------------------------------------------------------------------
# TC-09b 阈值可配（10/80/90 生效）
# ---------------------------------------------------------------------------
_T_CUSTOM = {"reverse": 10, "silver": 80, "gold": 90}


def test_tc09b_custom_thresholds_big_gold() -> None:
    """TC-09b：阈值 10/80/90，size=88 且 weight=92 → 金冠（阈值可配生效）。

    判定链（阈值 10/80/90）：逆金冠须双 <10（否）→ 大金冠须双 ≥90（88 否）→
    金冠单边 ≥90（92 达）→ 金冠。TC-09b 权威期望=金冠（细化 TC-09b 行 268）。
    """
    assert crown_of(88.0, 92.0, _T_CUSTOM) == CROWN_GOLD


def test_tc09b_custom_thresholds_reverse() -> None:
    """TC-09b 补：阈值 10/80/90，size=8 且 weight=8（双 <10）→ 逆金冠。"""
    assert crown_of(8.0, 8.0, _T_CUSTOM) == CROWN_REVERSE


def test_tc09b_custom_thresholds_not_95_default() -> None:
    """TC-09b 补：95 在新阈值下达金冠级（≥90）→ 金冠（阈值可配生效，非写死 95）。"""
    assert crown_of(95.0, 50.0, _T_CUSTOM) == CROWN_GOLD


def test_tc09b_custom_thresholds_gold_single() -> None:
    """TC-09b 补：size=92（≥90）且 weight=50 → 金冠（单边达新金冠阈值）。"""
    assert crown_of(92.0, 50.0, _T_CUSTOM) == CROWN_GOLD


# ---------------------------------------------------------------------------
# 阈值三态（显式 dict / ctx fishing_cfg / None 默认）
# ---------------------------------------------------------------------------
def test_thresholds_ctx_settings() -> None:
    """【工程补白 C-3】thresholds 传 ctx（含 settings.fishing.crown_thresholds）生效。

    88/92 在新阈值 10/80/90 下=金冠（同 test_tc09b_custom_thresholds_big_gold）。
    """
    ctx: Dict[str, object] = {
        "settings": {
            "fishing": {
                "crown_thresholds": {"reverse": 10, "silver": 80, "gold": 90}
            }
        }
    }
    assert crown_of(88.0, 92.0, ctx) == CROWN_GOLD  # type: ignore[arg-type]


def test_thresholds_ctx_fishing_cfg_direct() -> None:
    """【工程补白 C-3】thresholds 传 ctx（含 fishing_cfg 键，装配注入形态）生效。"""
    ctx: Dict[str, object] = {
        "fishing_cfg": {"crown_thresholds": {"reverse": 10, "silver": 80, "gold": 90}}
    }
    assert crown_of(8.0, 8.0, ctx) == CROWN_REVERSE  # type: ignore[arg-type]


def test_thresholds_none_defaults() -> None:
    """thresholds=None → 默认 5/85/95（细化 §2.1 默认值）。"""
    assert crown_of(4.9, 4.9, None) == CROWN_REVERSE
    assert crown_of(85.0, 50.0, None) == CROWN_SILVER
    assert crown_of(95.0, 95.0, None) == CROWN_BIG_GOLD


def test_thresholds_broken_falls_back_defaults() -> None:
    """【工程补白 C-6】阈值键缺/非数字/乱序 → 回落默认（运行时兜底不炸）。"""
    broken: Dict[str, object] = {"reverse": 0, "silver": None, "gold": "x"}
    assert crown_of(4.9, 4.9, broken) == CROWN_REVERSE  # type: ignore[arg-type]
    # 部分键（缺 silver/gold）→ 不视为显式阈值（默认 5/85/95）；reverse=99 乱序不改判
    assert crown_of(85.0, 50.0, {"reverse": 99}) == CROWN_SILVER
    assert crown_of(95.0, 95.0, {}) == CROWN_BIG_GOLD


def test_crown_order_is_hardcoded() -> None:
    """【细化 §2.3】CROWN_ORDER 顺序写死：逆金冠→大金冠→金冠→大银冠→银冠→普通。"""
    assert CROWN_ORDER == (
        CROWN_REVERSE, CROWN_BIG_GOLD, CROWN_GOLD,
        CROWN_BIG_SILVER, CROWN_SILVER, CROWN_NORMAL,
    )


def test_crown_labels_all_six() -> None:
    """CROWN_LABELS 六档中文名齐全（批4 图鉴冠级标注复用；无 emoji）。"""
    assert CROWN_LABELS == {
        CROWN_REVERSE: "逆金冠",
        CROWN_BIG_GOLD: "大金冠",
        CROWN_GOLD: "金冠",
        CROWN_BIG_SILVER: "大银冠",
        CROWN_SILVER: "银冠",
        CROWN_NORMAL: "普通",
    }


# ---------------------------------------------------------------------------
# TC-05 种子化收敛（N=100000，±0.5pp）
# ---------------------------------------------------------------------------
def _classify(size_pct: float, weight_pct: float, t: Mapping[str, int]) -> str:
    """按默认判定顺序六档分类（等价实现，互证 crown_of）。"""
    r = float(t["reverse"])
    s_ = float(t["silver"])
    g = float(t["gold"])
    if size_pct < r and weight_pct < r:
        return CROWN_REVERSE
    if size_pct >= g and weight_pct >= g:
        return CROWN_BIG_GOLD
    if size_pct >= g or weight_pct >= g:
        return CROWN_GOLD
    if size_pct >= s_ and weight_pct >= s_:
        return CROWN_BIG_SILVER
    if size_pct >= s_ or weight_pct >= s_:
        return CROWN_SILVER
    return CROWN_NORMAL


def _run_convergence(seed: int, n: int = 100_000) -> Dict[str, int]:
    """种子化收敛抽样：每轮独立百分位对 → crown_of 六档计数。"""
    rng = _rng(seed)
    counts: Dict[str, int] = {k: 0 for k in CROWN_ORDER}
    for _ in range(n):
        size_pct = rng.random() * 100.0
        weight_pct = rng.random() * 100.0
        counts[crown_of(size_pct, weight_pct, _T)] += 1
    return counts


def test_tc05_convergence_seed42() -> None:
    """TC-05：种子 42 N=100000 六档频率收敛（±0.5pp，理论值见细化 L95）。"""
    counts = _run_convergence(42)
    total = sum(counts.values())
    assert total == 100_000
    freq = {k: v / total * 100.0 for k, v in counts.items()}
    assert abs(freq[CROWN_REVERSE] - 0.25) <= 0.5
    assert abs(freq[CROWN_BIG_GOLD] - 0.25) <= 0.5
    assert abs(freq[CROWN_GOLD] - 9.5) <= 0.5
    assert abs(freq[CROWN_BIG_SILVER] - 1.0) <= 0.5
    assert abs(freq[CROWN_SILVER] - 17.0) <= 0.5
    assert abs(freq[CROWN_NORMAL] - 72.0) <= 0.5


def test_tc05_convergence_seed2026() -> None:
    """TC-05：种子 2026 N=100000 六档频率收敛（双种子交叉验证）。"""
    counts = _run_convergence(2026)
    total = sum(counts.values())
    freq = {k: v / total * 100.0 for k, v in counts.items()}
    assert abs(freq[CROWN_REVERSE] - 0.25) <= 0.5
    assert abs(freq[CROWN_BIG_GOLD] - 0.25) <= 0.5
    assert abs(freq[CROWN_GOLD] - 9.5) <= 0.5
    assert abs(freq[CROWN_BIG_SILVER] - 1.0) <= 0.5
    assert abs(freq[CROWN_SILVER] - 17.0) <= 0.5
    assert abs(freq[CROWN_NORMAL] - 72.0) <= 0.5


def test_tc05_classifier_parity() -> None:
    """TC-05 互证：crown_of 与等价分类器在种子 42 前 2000 对百分位上完全一致。"""
    rng = _rng(42)
    for _ in range(2000):
        s = rng.random() * 100.0
        w = rng.random() * 100.0
        assert crown_of(s, w, _T) == _classify(s, w, _T)


def test_tc05_expected_probability_math() -> None:
    """TC-05 理论值自检：均匀分布六档概率公式（细化 L95 四档锚点）。

    判定顺序语义下的精确区域划分（区间 [0,100) 均匀）：
      逆金冠 = [0,r)² ；大金冠 = [g,100)² ；金冠 = [g,100)×[0,g) 双向；
      大银冠 = [s_,g)² ；银冠 = [s_,g)×[0,s_) 双向；普通 = [0,s_)² − 逆金冠。
    """
    r, s_, g = 5, 85, 95
    p_reverse = (r / 100.0) ** 2
    p_big_gold = ((100 - g) / 100.0) ** 2
    p_gold = 2 * ((100 - g) / 100.0) * (g / 100.0)
    p_big_silver = ((g - s_) / 100.0) ** 2
    p_silver = 2 * ((g - s_) / 100.0) * (s_ / 100.0)
    p_normal = (s_ / 100.0) ** 2 - p_reverse
    assert abs(p_reverse - 0.0025) < 1e-12
    assert abs(p_big_gold - 0.0025) < 1e-12
    assert abs(p_gold - 0.095) < 1e-9
    assert abs(p_big_silver - 0.01) < 1e-9
    assert abs(p_silver - 0.17) < 1e-9
    assert abs(p_normal - 0.72) < 1e-9
    # 六档概率和为 1（普通=剩余）
    assert abs(p_reverse + p_big_gold + p_gold + p_big_silver + p_silver + p_normal - 1.0) < 1e-12


# ---------------------------------------------------------------------------
# 类型/导出完整性
# ---------------------------------------------------------------------------
def test_module_public_api() -> None:
    """对外 API：六档常量/顺序/标签/默认阈值/两入口函数全部导出。"""
    from qbot_rpg.core import fishing_crown as m
    for name in (
        "CROWN_REVERSE", "CROWN_BIG_GOLD", "CROWN_GOLD", "CROWN_BIG_SILVER",
        "CROWN_SILVER", "CROWN_NORMAL", "CROWN_ORDER", "CROWN_LABELS",
        "DEFAULT_CROWN_THRESHOLDS", "gen_size_weight", "crown_of",
    ):
        assert hasattr(m, name)


def test_fishdef_from_entry_roundtrip() -> None:
    """夹具自证：FishDef.from_entry 往返后四区间访问器可用（gen_size_weight 消费）。"""
    carp = _carp()
    assert carp.size_min == 10.0
    assert carp.size_max == 60.0
    assert carp.weight_min == 0.3
    assert carp.weight_max == 5.0
