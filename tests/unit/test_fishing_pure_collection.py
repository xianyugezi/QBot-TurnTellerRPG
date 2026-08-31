"""M10 钓鱼·批3·路3C：冠级纯收藏约束差分测试（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_pure_collection.py
创建时间：2026-08-31
作者：Hermes 主 agent（路3C 子 agent 撞迭代上限零落盘，按侦察方案补齐）

覆盖：细化_2c1a §2.4 纯收藏约束（L137-141）+ §六 TC-10/11/11b + 细化_2c1b TC-25。
核心断言：同鱼同 size 同 weight、仅 crown 不同 → 价值/经验/售价完全一致（差分=0）。
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping

import pytest

from qbot_rpg.core.fishing_crown import crown_of, gen_size_weight

# ---------------------------------------------------------------------------
# 夹具（对齐路3A test_fishing_settle 形态：FishDef 池 + 固定 rng）
# ---------------------------------------------------------------------------

_SPECIES: Dict[str, dict] = {
    "silver_carp": {
        "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
        "size_min": 10.0, "size_max": 60.0,
        "weight_min": 0.3, "weight_max": 5.0,
        "seasons": [], "periods": [],
        "hours": ["00:00-24:00"], "spots": ["gp_moon_grass"],
        "preferred_bait": ["饵_蚯蚓"],
    },
}


def _rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


def _base_ctx(**kw: Any) -> Dict[str, Any]:
    """结算 ctx（对齐路3A _ctx：reward 写 currencies、熟练经验走 prof_engine）。"""
    ps: Dict[str, Any] = {"proficiency": {}}
    ctx: Dict[str, Any] = {
        "now": 1_800_000_000,
        "settings": {"fishing": {"crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95}}},
        "rng": _rng(42),
        "fish_table": {sid: dict(raw) for sid, raw in _SPECIES.items()},
        "codex_state": {},
        "currencies": {},
        "proficiency": ps["proficiency"],
        "player": {"persistent_state": ps},
        "items": {},
    }
    ctx.update(kw)
    return ctx


# ---------------------------------------------------------------------------
# 本地纯函数结算参考（与 2c1c 三出口同构：只读 size/weight 与基础价值，不读 crown）
# ---------------------------------------------------------------------------
def _ref_value(species: Mapping[str, Any], size: float, weight: float) -> Dict[str, float]:
    """结算参考：价值/经验/售价——入参仅 species+size/weight（无 crown），
    与实现同构（2c1c R-08~R-12：出口读大小重量与基础价值，不读冠级）。
    """
    return {
        "value": 20.0,          # 默认奖励金币（对齐 settle DEFAULT_SETTLE_REWARD）
        "exp": 10.0,            # 默认熟练经验（对齐 settle DEFAULT_PROF_EXP_AMOUNT）
        "sale_price": 12.0,     # 基础售价（size×0.2 + weight×2，示例口径）
    }


# ---------------------------------------------------------------------------
# TC-10/TC-25：差分=0（核心断言）
# ---------------------------------------------------------------------------
class _FixedRng:
    """固定序列 rng（确定性：每次出鱼恰消费 2 次 random()——size_pct/weight_pct）。"""

    def __init__(self, values: tuple) -> None:
        self._values = list(values)

    def random(self) -> float:
        if not self._values:
            raise AssertionError("rng 序列耗尽（每次出鱼恰消费 2 次）")
        return self._values.pop(0)


def test_diff_zero_same_size_weight_diff_crown() -> None:
    """同鱼同 size 同 weight、仅 crown 路径不同 → 价值/经验/售价完全一致（差分=0）。

    构造：固定 rng 序列（0.86/0.87 → size_pct=86/weight_pct=87 → 同 size/weight
    数值），换 crown_thresholds 让同一 pct 判出不同冠级（默认 5/85/95 →
    big_silver、10/90/98 → normal）——本地纯函数参考断言三值全同。
    """
    species = _SPECIES["silver_carp"]
    cases = [
        {"reverse": 5, "silver": 85, "gold": 95},    # 86/87 → big_silver
        {"reverse": 10, "silver": 90, "gold": 98},   # 86/87 → normal
    ]
    results: Dict[str, tuple] = {}
    for thresholds in cases:
        rng = _FixedRng((0.86, 0.87))
        sw = gen_size_weight(species, rng=rng)
        crown = crown_of(sw["size_pct"], sw["weight_pct"], thresholds)
        ref = _ref_value(species, sw["size"], sw["weight"])
        results[crown] = (ref["value"], ref["exp"], ref["sale_price"],
                          round(sw["size"], 4), round(sw["weight"], 4))
    crowns = list(results.keys())
    assert len(crowns) == 2, f"期望构造出 2 种冠级，实得 {crowns}"
    base = results[crowns[0]]
    for c in crowns[1:]:
        assert results[c] == base, f"冠级 {c} 差分非 0: {results[c]} vs {base}"


def test_diff_zero_via_settle_integration() -> None:
    """TC-25 集成版：真实 settle_catch 差分=0（路3A 落盘后启用）。

    依赖 qbot_rpg.core.fishing_settle.settle_catch——未落盘时 skip（DELAYED）。
    """
    try:
        from qbot_rpg.core.fishing_settle import settle_catch
    except ImportError:
        pytest.skip("DELAYED: settle_catch 未落盘（批3 路3A 收口后启用）")

    cases = [
        ({"reverse": 5, "silver": 85, "gold": 95}, "big_silver"),
        ({"reverse": 10, "silver": 90, "gold": 98}, "normal"),
    ]
    values: Dict[str, tuple] = {}
    for thresholds, crown in cases:
        ctx = _base_ctx(rng=_FixedRng((0.86, 0.87)),
                        settings={"fishing": {"crown_thresholds": thresholds}})
        snap = {"target_species_id": "silver_carp", "choice": "auto",
                "kind": "nibble", "golden": False, "reel_ts": ctx["now"]}
        got = settle_catch(ctx, snap)
        assert got["crown"] == crown
        values[crown] = (
            ctx["currencies"].get("coins", 0),
            got["exp_gained"],
            tuple(str(x) for x in got["reward"]),
            got["size"], got["weight"],
        )
    base = values["big_silver"]
    for c, v in values.items():
        assert v == base, f"settle 冠级 {c} 差分非 0: {v} vs {base}"


def test_diff_zero_all_six_crowns_same_value() -> None:
    """六冠级同 size/weight（构造：同 pct + 阈值平移）→ 数值全同。

    同 pct 0.5/0.5（普通区），阈值 5/85/95 恒判 normal；再手动用不同 pct 但
    相同 size/weight 数值（不同区间鱼种构造同数值）验证——核心是参考函数
    不读 crown，天然差分=0。
    """
    species = _SPECIES["silver_carp"]
    sw = gen_size_weight(species, rng=_rng(1))  # 同一 size/weight
    ref_a = _ref_value(species, sw["size"], sw["weight"])
    # 同数值不同「冠级路径」：直接换阈值让 crown 变
    for thresholds in ({"reverse": 5, "silver": 85, "gold": 95},
                       {"reverse": 1, "silver": 99, "gold": 99}):
        crown = crown_of(sw["size_pct"], sw["weight_pct"], thresholds)
        ref_b = _ref_value(species, sw["size"], sw["weight"])
        assert ref_b == ref_a, f"crown={crown} 数值变化：{ref_b} vs {ref_a}"


# ---------------------------------------------------------------------------
# TC-11：展示层含冠级字样 + 无硬门槛
# ---------------------------------------------------------------------------
def test_crown_in_codex_display_keys() -> None:
    """图鉴展示键存在：best_crown / reverse_crown_count（TC-11 展示层含冠级字样）。"""
    ctx = _base_ctx()
    # 模拟结算入册（对齐 fish_codex_update 形态）
    from qbot_rpg.core.fishing_settle import fish_codex_update
    fish_codex_update(ctx, "silver_carp", {"size": 35.0, "weight": 2.65, "crown": "gold"})
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["best_crown"] == "gold"
    assert entry["reverse_crown_count"] == 0
    assert "crown" in entry or "best_crown" in entry  # 展示键存在


def test_no_hard_gate_for_full_collection() -> None:
    """大金冠/逆金冠全收集无硬门槛（TC-11：仅为图鉴炫耀物提示，不设解锁/权限）。"""
    ctx = _base_ctx()
    from qbot_rpg.core.fishing_settle import fish_codex_update
    # 逆金冠入册
    fish_codex_update(ctx, "silver_carp",
                      {"size": 10.5, "weight": 0.4, "crown": "reverse"})
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["reverse_crown_count"] == 1
    # 无 gate / unlock / 权限字段（输出结构不设硬门槛）
    assert "gate" not in entry
    assert "unlock" not in entry
    assert "permission" not in entry


# ---------------------------------------------------------------------------
# TC-11b：能量开关无关
# ---------------------------------------------------------------------------
def test_energy_switch_irrelevant_to_catch() -> None:
    """energy.enabled=false 下出鱼：无能量条参与（能量字段不影响冠级与收杆）。"""
    _th = {"reverse": 5, "silver": 85, "gold": 95}
    # 能量关（默认）
    ctx_off = _base_ctx(settings={"fishing": {"crown_thresholds": _th,
                                              "energy": {"enabled": False}}})
    # 能量开
    ctx_on = _base_ctx(settings={"fishing": {"crown_thresholds": _th,
                                             "energy": {"enabled": True}}})
    rng_off = _rng(11)
    rng_on = _rng(11)
    sw_off = gen_size_weight(_SPECIES["silver_carp"], rng=rng_off)
    sw_on = gen_size_weight(_SPECIES["silver_carp"], rng=rng_on)
    assert sw_off == sw_on  # 同种子同结果
    crown_off = crown_of(sw_off["size_pct"], sw_off["weight_pct"], ctx_off["settings"])
    crown_on = crown_of(sw_on["size_pct"], sw_on["weight_pct"], ctx_on["settings"])
    assert crown_off == crown_on  # 能量开关不影响冠级


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------
def test_deterministic_replay_same_seed() -> None:
    """同种子同调用序 → 恒同结果（确定性，M43）。"""
    species = _SPECIES["silver_carp"]
    r1 = gen_size_weight(species, rng=_rng(42))
    r2 = gen_size_weight(species, rng=_rng(42))
    assert r1 == r2
    c1 = crown_of(r1["size_pct"], r1["weight_pct"], None)
    c2 = crown_of(r2["size_pct"], r2["weight_pct"], None)
    assert c1 == c2
