"""M10 钓鱼·批3·路3A：出鱼结算单测（tests/unit/test_fishing_settle.py）。

文件名：tests/unit/test_fishing_settle.py
创建时间：2026-08-31
作者：Hermes 子agent-3A（M10 钓鱼实现组批3·路3A：出鱼结算 T10）

覆盖：细化_2c1b §六 F 结算与图鉴点亮（TC-24 / TC-25）+ 细化_2c1a §四 图鉴记录
      （G-01~G-07 更新规则）+ 路3A 工程补白 S-1~S-9：
  - 结算三要素 size/weight/crown 齐全（TC-24）
  - 图鉴首获点亮（2c1a §4.2 L206）+ 计数递增（G-01）
  - best/min/reverse 极值更新（G-02~G-07）
  - 熟练经验入账（source=gather，job_id=fishing；prof_engine 注入）
  - 奖励入账（金币/物品，reward 发放器）
  - 纯收藏差分=0（TC-25：同鱼同尺寸同重量不同冠级 → 价值/经验/售价全同）
  - 止损无结算 / 缺快照拒绝 / 无鱼种拒绝 / 幂等去重
  - 确定性（同 seed 同 ctx 同快照 → 恒同结果）
用例数：22 例（≥18 硬性要求；含 TC-24/TC-25 覆盖）。

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §四 4.4（出鱼结算接线）+ §六 TC-24/25
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §四（G-01~G-07）/ §2.4（纯收藏 L46-48）
  - docs/m10_接口摸底.md §三（mark_seen 覆盖陷阱）/ §四（reward）/ §六（proficiency
    批5 才加实例）/ §九（rng 注入、种子化确定性）
铁律：零 NoneBot import；确定性测试种子化（无裸 random）；docstring 不含
      「time.sleep」字面量（M43 探针，用「零定时器/零睡眠」措辞）；无 emoji。
"""

from __future__ import annotations

import random
from typing import Any, Dict, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing_settle import (
    CROWN_PRIORITY,
    DEFAULT_PROF_EXP_AMOUNT,
    DEFAULT_SETTLE_REWARD,
    fish_codex_update,
    settle_catch,
)
from qbot_rpg.core.proficiency import ProficiencyEngine

# =====================================================================================
# 夹具
# =====================================================================================

SPOT = "map_laketown:pier_01"

# 夹具鱼种（细化 §1.3 基准行 silver_carp 银鳞鲤：size 10~60 / weight 0.3~5.0）
_SILVER_CARP: Dict[str, Any] = {
    "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
    "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
    "seasons": [], "periods": [], "hours": ["00:00-24:00"],
    "spots": [SPOT], "preferred_bait": ["饵_蚯蚓"],
    "codex_text": {"desc": "鳞片泛银光的鲤，黄昏时最活跃。", "unit": "cm-kg",
                   "best_mask": "{name} · 最大 {best_size}cm/{best_weight}kg · "
                                "{best_crown} · 逆金冠×{reverse_crown_count}"},
    "king": None,
}

_RARE_LOACH: Dict[str, Any] = {
    "id": "rare_loach", "name": "赤纹泥鳅", "rarity": "rare",
    "size_min": 5.0, "size_max": 30.0, "weight_min": 0.1, "weight_max": 1.0,
    "spots": [SPOT], "preferred_bait": ["饵_面团"],
}

_GOLDEN_KOI: Dict[str, Any] = {
    "id": "golden_koi", "name": "金鳞鲤", "rarity": "gold",
    "size_min": 20.0, "size_max": 90.0, "weight_min": 1.0, "weight_max": 12.0,
    "spots": [SPOT], "preferred_bait": ["饵_黄金虫"],
}

# 全夹具池（_fish / _ctx fish_table 共用）
_SPECIES: Dict[str, Dict[str, Any]] = {
    "silver_carp": _SILVER_CARP,
    "rare_loach": _RARE_LOACH,
    "golden_koi": _GOLDEN_KOI,
}

# 固定时钟（UTC+8 epoch 秒；远离 dayroll 05:00 日界）
BASE_NOW = 1_800_000_000


class _FixedRng:
    """固定序列 rng（确定性：每次出鱼恰消费 2 次 random()——size_pct/weight_pct）。"""

    def __init__(self, values: tuple) -> None:
        self._values = list(values)

    def random(self) -> float:
        if not self._values:
            raise AssertionError("rng 序列耗尽（每次出鱼恰消费 2 次）")
        return self._values.pop(0)


def _rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


def _fish(id: str) -> FishDef:
    return cast(FishDef, FishDef.from_entry(_SPECIES[id]))

def _ctx(**kw: Any) -> Dict[str, Any]:
    """构造结算 ctx：settings / rng / fish_table / codex_state / currencies /
    proficiency / prof_engine 注入（对齐 make_context 装配形态：ctx["proficiency"]
    与 player.persistent_state.proficiency 同一对象，_ps_init 挂 ps 即落档）。"""
    ps: Dict[str, Any] = {"proficiency": {}}
    ctx: Dict[str, Any] = {
        "now": BASE_NOW,
        "settings": {"fishing": {"crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95}}},
        "rng": _rng(42),
        "fish_table": {sid: dict(raw) for sid, raw in _SPECIES.items()},
        "codex_state": {},
        "currencies": {},
        "proficiency": ps["proficiency"],
        "player": {"persistent_state": ps},
        "items": {"铁矿": {"id": "铁矿", "name": "铁矿", "quality": "normal"}},
        "prof_engine": ProficiencyEngine(),
    }
    ctx.update(kw)
    return ctx


def _snap(species_id: str = "silver_carp", **kw: Any) -> Dict[str, Any]:
    """reel_in 写入的 last 快照（批1 B-6 形态；可覆盖/扩展键）。"""
    snap: Dict[str, Any] = {
        "choice": "auto",
        "kind": "nibble",
        "golden": False,
        "target_species_id": species_id,
        "target_rarity": "normal",
        "spot_id": SPOT,
        "bite_ts": BASE_NOW,
        "reel_ts": BASE_NOW,
    }
    snap.update(kw)
    return snap


def _sw(crown: str) -> Dict[str, float]:
    """按目标冠级反推 size_pct/weight_pct（用于纯收藏差分构造）。

    reverse: 双 <5；big_gold: 双 ≥95；gold: 单边 ≥95；big_silver: 双 ≥85 且 <95；
    silver: 单边 ≥85 且 <95；normal: 其余。
    """
    if crown == "reverse":
        return {"size_pct": 2.0, "weight_pct": 3.0}
    if crown == "big_gold":
        return {"size_pct": 96.0, "weight_pct": 97.0}
    if crown == "gold":
        return {"size_pct": 96.0, "weight_pct": 50.0}
    if crown == "big_silver":
        return {"size_pct": 86.0, "weight_pct": 87.0}
    if crown == "silver":
        return {"size_pct": 86.0, "weight_pct": 50.0}
    return {"size_pct": 50.0, "weight_pct": 50.0}


def _catch(size: float = 35.0, weight: float = 2.65, crown: str = "normal") -> Dict[str, object]:
    """fish_codex_update 直测用 catch 记录。"""
    return {"size": size, "weight": weight, "crown": crown}


# =====================================================================================
# A. 结算三要素 + happy path（TC-24）
# =====================================================================================
def test_tc24_settle_triple_elements_present() -> None:
    """TC-24：满力/自动收杆成功 → 结算记录三要素 size/weight/crown 齐全。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap())
    assert got["ok"] is True
    assert got["size"] == 35.0
    assert abs(got["weight"] - 2.65) < 1e-9
    assert got["crown"] in CROWN_PRIORITY + ("reverse",)
    # 结算记录三要素显式携带
    assert {"size", "weight", "crown"} <= set(got.keys())


def test_settle_happy_path_full_wiring() -> None:
    """happy path 全接线：图鉴点亮 + 熟练经验 + 奖励 + 消息骨架一次完成。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap())
    assert got["ok"] is True
    assert got["name"] == "银鳞鲤"
    assert got["rarity"] == "normal"
    assert got["first_seen"] is True
    assert got["caught_count"] == 1
    assert got["best_crown"] == "normal"
    # 图鉴条目落 codex_state["fish"]（防 mark_seen 覆盖形态）
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["seen"] is True
    assert entry["caught_count"] == 1
    assert entry["best_size"] == 35.0
    assert abs(entry["best_weight"] - 2.65) < 1e-9
    assert entry["min_size"] == 35.0
    assert entry["reverse_crown_count"] == 0
    # 奖励入账（金币少量默认）
    assert ctx["currencies"].get("coins", 0) == DEFAULT_SETTLE_REWARD["coins"]
    assert got["reward"] != []
    # 熟练经验：proficiency 桶挂 player.persistent_state（_ps_init 形态）
    ps = ctx["player"]["persistent_state"]
    assert ps.get("proficiency", {}).get("fishing", {}).get("exp", 0) == DEFAULT_PROF_EXP_AMOUNT
    assert got["exp_gained"] == DEFAULT_PROF_EXP_AMOUNT
    # 消息骨架（批6 模板化前占位）
    assert "message" in got and "银鳞鲤" in got["message"]


def test_settle_auto_snapshot_from_fish_state() -> None:
    """last_snapshot 缺省 → 自动读 ctx["fish_state"]["last"]（指令壳传参形态兜底）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    ctx["fish_state"] = {"last": _snap()}
    got = settle_catch(ctx)
    assert got["ok"] is True
    assert got["species_id"] == "silver_carp"


def test_settle_golden_koi_rarity_carried() -> None:
    """gold 鱼种：rarity 从鱼种数据读取并携带（结算消息展示用）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap("golden_koi"))
    assert got["ok"] is True
    assert got["rarity"] == "gold"
    assert got["name"] == "金鳞鲤"


# =====================================================================================
# B. 图鉴记录（G-01~G-07 更新规则）
# =====================================================================================
def test_codex_caught_count_increments() -> None:
    """G-01：同一鱼种重复捕获 → caught_count 每次 +1。"""
    ctx = _ctx(rng=_rng(42))  # 无限种子序列（_FixedRng 2 值会耗尽）
    settle_catch(ctx, _snap())
    settle_catch(ctx, _snap())
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["caught_count"] == 2


def test_codex_first_seen_only_once() -> None:
    """首获点亮一次：第二次捕获 first_seen=False，不重复日志/事件。"""
    ctx = _ctx(rng=_rng(42))  # 无限种子序列（_FixedRng 2 值会耗尽）
    r1 = settle_catch(ctx, _snap())
    r2 = settle_catch(ctx, _snap())
    assert r1["first_seen"] is True
    assert r2["first_seen"] is False


def test_codex_best_and_min_extremes() -> None:
    """G-03~G-06：best/min 极值——先小后大 → best 取大、min 取小。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(size=30.0, weight=2.0))
    fish_codex_update(ctx, "silver_carp", _catch(size=45.0, weight=4.0))
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["best_size"] == 45.0
    assert entry["best_weight"] == 4.0
    assert entry["min_size"] == 30.0
    assert entry["min_weight"] == 2.0


def test_codex_best_crown_priority_chain() -> None:
    """G-02：best_crown 优先级链 big_gold > gold > big_silver > silver > normal。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(crown="silver"))
    fish_codex_update(ctx, "silver_carp", _catch(crown="gold"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "gold"
    fish_codex_update(ctx, "silver_carp", _catch(crown="big_gold"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "big_gold"
    # 低档不降级
    fish_codex_update(ctx, "silver_carp", _catch(crown="normal"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "big_gold"


def test_codex_reverse_crown_count_and_min_refresh() -> None:
    """G-07：逆金冠出鱼 reverse_crown_count +1 并刷新 min 记录（2c1a §4.2 L56）。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(size=35.0, weight=2.65, crown="normal"))
    fish_codex_update(ctx, "silver_carp", _catch(size=11.0, weight=0.5, crown="reverse"))
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["reverse_crown_count"] == 1
    assert entry["min_size"] == 11.0
    assert entry["min_weight"] == 0.5
    # 逆金冠不入 best_crown 链（2c1a §4.2：逆金冠是极值收藏不是等级）
    assert entry["best_crown"] == "normal"


def test_codex_mark_seen_no_overwrite() -> None:
    """防 mark_seen 覆盖：已见条目 seen=true 时扩展键不被整条目覆盖冲掉。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(size=35.0, weight=2.65, crown="gold"))
    # 模拟展示层附加键（路4A 渲染写）
    ctx["codex_state"]["fish"]["silver_carp"]["lore_unlocked"] = True
    fish_codex_update(ctx, "silver_carp", _catch(size=40.0, weight=3.0, crown="silver"))
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["lore_unlocked"] is True  # 存量展示键保留
    assert entry["caught_count"] == 2
    assert entry["best_crown"] == "gold"


def test_codex_unknown_species_id_rejected() -> None:
    """空 species_id → 拒绝（不建条目不炸）。"""
    ctx = _ctx()
    r = fish_codex_update(ctx, "", _catch())
    assert r["ok"] is False
    assert "fish" not in ctx["codex_state"]


# =====================================================================================
# C. 熟练经验（source=gather，job_id=fishing，S-6）
# =====================================================================================
def test_prof_exp_granted_gather_source() -> None:
    """熟练经验入账：amount=10，source=gather，job_id=fishing（2c1c 归 gather 系）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap())
    assert got["exp_gained"] == DEFAULT_PROF_EXP_AMOUNT
    fishing = ctx["proficiency"]["fishing"]
    assert fishing["exp"] == DEFAULT_PROF_EXP_AMOUNT
    assert fishing["level"] == 0  # 10 exp 未跨 100 阈值


def test_prof_exp_cfg_override_amount() -> None:
    """内容包可配键 settings.fishing.settle_prof_exp 覆盖默认 10。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)),
               settings={"fishing": {"settle_prof_exp": 25,
                                     "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95}}})
    got = settle_catch(ctx, _snap())
    assert got["exp_gained"] == 25


def test_prof_exp_missing_engine_skips_not_blocking() -> None:
    """prof_engine 缺失（批5 装配前）→ 静默跳过，不阻断结算（S-6 缺省容错）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    ctx.pop("prof_engine")
    got = settle_catch(ctx, _snap())
    assert got["ok"] is True
    assert got["exp_gained"] == 0
    assert "fishing" not in ctx["proficiency"]


def test_prof_exp_player_proficiency_direct_key() -> None:
    """proficiency 直键形态（_ps_init 挂 ps）→ 引擎就地改写即落档。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    ctx["player"] = {"persistent_state": {"proficiency": {}}}
    ctx["proficiency"] = ctx["player"]["persistent_state"]["proficiency"]
    got = settle_catch(ctx, _snap())
    assert got["exp_gained"] == DEFAULT_PROF_EXP_AMOUNT
    prof = ctx["player"]["persistent_state"]["proficiency"]["fishing"]
    assert prof["exp"] == DEFAULT_PROF_EXP_AMOUNT


# =====================================================================================
# D. 奖励入账（reward 发放器直接复用，S-5）
# =====================================================================================
def test_reward_coins_granted() -> None:
    """默认奖励：金币少量入 ctx["currencies"]（reward 发放器一条调用）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap())
    assert ctx["currencies"].get("coins", 0) == DEFAULT_SETTLE_REWARD["coins"]
    assert got["reward"] == [{"type": "currency", "currency": "coins",
                              "amount": DEFAULT_SETTLE_REWARD["coins"]}]


def test_reward_cfg_override_entries() -> None:
    """内容包可配键 settings.fishing.settle_reward 覆盖默认（金币+物品）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)),
               settings={"fishing": {"settle_reward": [{"coins": 50}, {"item": "铁矿", "count": 2}],
                                     "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95}}})
    adds: list = []

    def _add_item(item_id: str, count: int, bound: bool) -> bool:
        adds.append((item_id, count, bound))
        return True

    ctx["add_item"] = _add_item
    got = settle_catch(ctx, _snap())
    assert ctx["currencies"].get("coins", 0) == 50
    assert adds == [("铁矿", 2, True)]
    assert got["reward"] == [
        {"type": "currency", "currency": "coins", "amount": 50},
        {"type": "item", "item": "铁矿", "count": 2, "bound": True, "applied": True},
    ]


# =====================================================================================
# E. 纯收藏差分=0（TC-25）
# =====================================================================================
def test_tc25_collection_diff_zero_same_value() -> None:
    """TC-25：同鱼同 size 同 weight、仅 crown 不同 → 奖励价值/熟练经验完全一致
    （差分=0，冠级纯收藏——结算计算不读取冠级字段进数值）。

    构造：同一 rng（同 size_pct/weight_pct → 同 size/weight），每次换
    crown_thresholds 让同一 pct 判出不同冠级；数值侧（金币/经验/奖励）必须全同。
    """
    # pct 0.86/0.87 → size_pct=86/weight_pct=87（银冠级区）
    cases = [
        # (阈值配置, 期望冠级)
        ({"reverse": 5, "silver": 85, "gold": 95}, "big_silver"),    # 双≥85 → 大银冠
        ({"reverse": 10, "silver": 90, "gold": 98}, "normal"),        # 86<90 不达银 → 普通
        ({"reverse": 1, "silver": 87, "gold": 95}, "silver"),         # 87≥87 单边达银 → 银冠
    ]
    values: Dict[str, tuple] = {}
    for idx, (thresholds, crown) in enumerate(cases):
        ctx = _ctx(rng=_FixedRng((0.86, 0.87)),
                   settings={"fishing": {"crown_thresholds": thresholds}})
        got = settle_catch(ctx, _snap())
        assert got["crown"] == crown, f"case {idx} 期望 {crown} 实得 {got['crown']}"
        values[crown] = (
            ctx["currencies"].get("coins", 0),      # 价值（奖励入账）
            got["exp_gained"],                      # 经验（熟练经验）
            tuple(str(x) for x in got["reward"]),   # 奖励条目
            got["size"], got["weight"],             # 同鱼同尺寸同重量
        )
        # 各冠级落图鉴展示键（best_crown/reverse_crown_count 仅图鉴记录）
        entry = ctx["codex_state"]["fish"]["silver_carp"]
        assert entry["seen"] is True
    base = values["big_silver"]
    for _thresholds, _crown in cases:
        assert values[_crown] == base, f"冠级 {_crown} 差分非 0: {values[_crown]} vs {base}"


def test_tc25_crown_only_in_codex_and_display() -> None:
    """冠级只入图鉴与展示：结算返回携带 crown（展示），数值侧（奖励/经验）与 crown 无关。"""
    ctx = _ctx(rng=_FixedRng((0.96, 0.50)))
    got = settle_catch(ctx, _snap())
    assert got["crown"] == "gold"
    # 图鉴记录冠级（best_crown），数值侧仅金币+经验
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "gold"
    assert ctx["currencies"].get("coins", 0) == DEFAULT_SETTLE_REWARD["coins"]
    assert got["exp_gained"] == DEFAULT_PROF_EXP_AMOUNT


# =====================================================================================
# F. 拒绝场景 / 幂等 / 确定性
# =====================================================================================
def test_missing_snapshot_rejected() -> None:
    """缺快照（无 last、显式 None）→ 拒绝 reason=missing_snapshot，零入账。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, None)
    assert got["ok"] is False
    assert got["reason"] == "missing_snapshot"
    assert ctx["currencies"] == {}
    assert "fish" not in ctx["codex_state"]


def test_snapshot_missing_species_id_rejected() -> None:
    """快照缺 target_species_id / 非 str → 拒绝（止损/跑鱼无 last 的防御兜底）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap(target_species_id=None))
    assert got["ok"] is False
    assert got["reason"] == "missing_snapshot"
    got2 = settle_catch(ctx, _snap(target_species_id=123))
    assert got2["ok"] is False
    assert got2["reason"] == "missing_snapshot"


def test_species_not_found_rejected() -> None:
    """快照目标鱼种不在池 → 拒绝 reason=species_not_found，零入账（S-2）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)))
    got = settle_catch(ctx, _snap("ghost_fish"))
    assert got["ok"] is False
    assert got["reason"] == "species_not_found"
    assert ctx["currencies"] == {}
    assert "fish" not in ctx["codex_state"]
    assert "fishing" not in ctx["proficiency"]


def test_idempotent_same_tx_rejected() -> None:
    """幂等闸（S-7）：同 tx_id 已结算 → 拒绝不重复入账（防双花）。"""
    ctx = _ctx(rng=_FixedRng((0.5, 0.5)), tx_id="tx-1", ledger=set())
    got = settle_catch(ctx, _snap())
    assert got["ok"] is True
    assert ctx["currencies"].get("coins", 0) == DEFAULT_SETTLE_REWARD["coins"]
    got2 = settle_catch(ctx, _snap())
    assert got2["ok"] is False
    assert got2["reason"] == "already_settled"
    assert ctx["currencies"].get("coins", 0) == DEFAULT_SETTLE_REWARD["coins"]  # 未重复入账


def test_deterministic_replay_same_seed_same_result() -> None:
    """确定性：同 seed 同 ctx 同快照 → 恒同结果（注入 rng 单源）。"""
    results = []
    for _ in range(2):
        ctx = _ctx(rng=_rng(2026))
        got = settle_catch(ctx, _snap())
        results.append((got["size"], got["weight"], got["size_pct"], got["weight_pct"],
                        got["crown"], got["first_seen"]))
    assert results[0] == results[1]


def test_different_seed_different_size() -> None:
    """不同 seed → 尺寸/重量不同（百分位独立生成，非恒值）。"""
    ctx_a = _ctx(rng=_rng(42))
    ctx_b = _ctx(rng=_rng(2026))
    a = settle_catch(ctx_a, _snap())
    b = settle_catch(ctx_b, _snap())
    assert a["ok"] is True and b["ok"] is True
    assert (a["size"], a["weight"]) != (b["size"], b["weight"])
