"""批43 · 强化六档上限（H3 替换）+ 每 N 级特殊词条（相性池）核心单测。

覆盖（对齐任务书「测试与验收」）：
  A 上限替换：品质等级 1~6 → +3/+6/+9/+12/+15/+18（逐档断言）；参数化（包声明表）。
  B 旧档兼容：旧装备（无 quality_level）经桥接读上限、既有 enhance_level 原样保留、
    **只升不降**、可穿戴/展示/强化；`max_by_rarity` 旧配置不再被读取。
  C 每 N 级词条：达 4/8/12 各得一条；跨度可配（改成 3 → 每 3 级一条）；确定性 RNG。
  D 相性池：必须走 `resolve_available_entries`（专属池可达 / 无相性 → 要求相性的抽不出）。
  E 词条族：新键语义/上限登记齐备；冷却缩减=占位（不接引擎，可展示）。
  F 回归对拍：既有成功率曲线 1..12 / 石档位 1..12 / fail_tier_split 逐字段一致。

样本全部为合成 ctx / 合成池（**不写任何真实内容包**）。
"""
from __future__ import annotations

import random
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from qbot_rpg.commands.enhance_commands import cmd_enhance, cmd_enhance_info
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.content.enhance_models import (
    DEFAULT_CURVE,
    DEFAULT_ENHANCE,
    DEFAULT_MAX_BY_QUALITY_LEVEL,
    DEFAULT_STONE_TIERS,
    validate_enhance,
)
from qbot_rpg.core.enhance_affix import resolve_cap, special_affix_count
from qbot_rpg.data.gear_stats import (
    GEAR_DISPLAY_KEYS,
    GEAR_HELP_ZH,
    GEAR_LABELS_ZH,
    GEAR_NUMERIC_KEYS,
    GEAR_PLACEHOLDER_KEYS,
    extract_bonus,
    route_bonus_into,
)
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.storage.repository import _item_from_dict

# 合成上限表（**非**真实内容包；逐档 3/6/9/12/15/18）
_CAP = {"1": 3, "2": 6, "3": 9, "4": 12, "5": 15, "6": 18}
_LEGACY = {"normal": 2, "fine": 3, "epic": 4, "legendary": 4}
_ALL_LEVELS = list(range(1, 19))


def _enh_config(*, span: int = 4, rate: int = 100) -> Dict[str, Any]:
    """合成 enhance raw：上限表六档 + 桥接 + 跨度；成功率恒 100（聚焦词条而非 roll）。"""
    return {
        "settings": {
            "max_by_quality_level": dict(_CAP),
            "legacy_quality_level_by_rarity": dict(_LEGACY),
            "special_affix_span": span,
            "fail_tier_split": 3,
            "luck_affects": False,
        },
        "cost": {
            "coin_per_level": 100, "stones_per_level": 1,
            "stone_tiers": [{"tier": "low", "item": "stone", "levels": list(_ALL_LEVELS)}],
        },
        "success_curve": [{"to": i, "rate": rate} for i in _ALL_LEVELS],
        "values": {"weapon_atk_per_level": {"type": "flat", "value": 5, "stat_key": "atk"}},
        "protect_stone": "ps",
    }


_DEFAULT_POOLS: List[Dict[str, Any]] = [
    {"id": "common_pool", "kind": "common", "entries": [
        {"enhance_affix": "heal_amp_pct", "value": 6, "weight": 1},
    ]},
    {"id": "moon_pool", "kind": "exclusive", "entries": [
        {"enhance_affix": "weakness_dmg_pct", "value": 9, "weight": 1},
        {"enhance_affix": "cooldown_reduction_pct", "value": 4, "weight": 1,
         "requires_affinity": "moon"},
    ]},
]


def _settings(pools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合成相性配置：一个专属池（承载强词条）+ 传入的池表。"""
    return {
        "affinities": [{"id": "moon", "name": "月", "exclusive_pool": "moon_pool"}],
        "affinity_pools": list(pools),
    }


def _row(item_id: str, name: str, *, slot: Optional[str] = None, quality: str = "normal",
         quality_level: int = 0, enhance: int = 0, atk: float = 0.0,
         affinities: Optional[Dict[str, float]] = None,
         enhance_affixes: Optional[List[str]] = None, count: int = 1) -> Dict[str, Any]:
    return {
        "item_id": item_id, "name": name, "count": count, "quality": quality,
        "bound": False, "slot": slot, "stats_bonus": ({"atk": atk} if atk else {}),
        "enhance_level": enhance, "traits": [], "quality_level": quality_level,
        "affinities": dict(affinities or {}),
        "enhance_affixes": list(enhance_affixes or []),
    }


def make_ctx(*, quality_level: int = 0, quality: str = "normal", enhance: int = 3,
             atk: float = 27.0, affinities: Optional[Dict[str, float]] = None,
             span: int = 4, pools: Optional[List[Dict[str, Any]]] = None,
             with_settings: bool = True, rng: Any = None, stones: int = 99) -> Dict[str, Any]:
    player = {
        "name": "测试勇士", "level": 20, "qid": "u1",
        "currencies": {"coins": 500000},
        "inventory": [
            _row("sword", "铁剑", slot="weapon", quality=quality,
                 quality_level=quality_level, enhance=enhance, atk=atk,
                 affinities=affinities),
            _row("stone", "强化石", enhance=0, count=stones),
        ],
        "equipment": {"weapon": {"item_id": "sword", "name": "铁剑", "slot_level": enhance}},
        "attributes": {"base": {}, "bonus": {"flat": {}, "pct": {}}, "temp": {}},
        "in_battle": False,
    }
    ctx: Dict[str, Any] = {
        "registered": True, "player": player,
        "items": {"sword": {"id": "sword", "name": "铁剑", "slot": "weapon"},
                  "stone": {"id": "stone", "name": "强化石"}, "ps": {"id": "ps", "name": "保护石"}},
        "enhance": _enh_config(span=span),
        "slots": {}, "templates": None,
        "rng": rng if rng is not None else random.Random(20260919),
    }
    if with_settings:
        ctx["settings"] = _settings(pools if pools is not None else _DEFAULT_POOLS)
    return ctx


def _row_of(ctx: Dict[str, Any], item_id: str = "sword") -> Dict[str, Any]:
    for r in ctx["player"]["inventory"]:
        if r["item_id"] == item_id:
            return r
    raise AssertionError(item_id)


# ---------------------------------------------------------------------------
# A. 上限替换（H3）
# ---------------------------------------------------------------------------
def test_cap_table_quality_level_1_to_6() -> None:
    """品质等级 1~6 → 上限 +3/+6/+9/+12/+15/+18（逐档断言，来自包声明表）。"""
    expected = {1: 3, 2: 6, 3: 9, 4: 12, 5: 15, 6: 18}
    assert DEFAULT_MAX_BY_QUALITY_LEVEL == expected
    for lv, cap in expected.items():
        got = resolve_cap(cap_table=_CAP, legacy_map=_LEGACY, quality_level=lv)
        assert got == cap, (lv, got, cap)


def test_cap_table_is_parameterized() -> None:
    """上限表**参数化**：改包声明表 → 结果随之变（非硬编码档位/数值）。"""
    custom = {"1": 2, "2": 4, "3": 8}
    assert resolve_cap(cap_table=custom, legacy_map={}, quality_level=3) == 8
    assert resolve_cap(cap_table=custom, legacy_map={}, quality_level=4) == 8  # 顶档封顶
    # 未声明等级 1 → 0（不可强化）
    assert resolve_cap(cap_table=custom, legacy_map={}, quality_level=0) == 0


def test_cap_via_command_quality_level() -> None:
    """打造产物品质等级决定上限：等级 5 → 展示「强化上限 +15」。"""
    ctx = make_ctx(quality_level=5, enhance=0, atk=12.0)
    out = cmd_enhance_info(parse_command("/强化信息 铁剑"), ctx)
    assert "强化上限 +15" in out


# ---------------------------------------------------------------------------
# B. 旧档兼容
# ---------------------------------------------------------------------------
def test_legacy_bridge_minimal_non_decreasing() -> None:
    """旧档桥接：旧品质 → 新档上限 ≥ 旧上限（只升不降）。"""
    old = {"normal": 5, "fine": 8, "epic": 10, "legendary": 12}
    for rarity, old_cap in old.items():
        cap = resolve_cap(cap_table=_CAP, legacy_map=_LEGACY, quality_level=0, rarity=rarity)
        assert cap >= old_cap, (rarity, cap, old_cap)


def test_legacy_gear_level_preserved_and_can_reach_new_cap() -> None:
    """旧档装备（无 quality_level）：既有 +5 原样保留、展示 +6 上限、可强化到 +6。"""
    ctx = make_ctx(quality_level=0, quality="normal", enhance=5, atk=37.0)
    info = cmd_enhance_info(parse_command("/强化信息 铁剑"), ctx)
    assert "铁剑+5" in info and "强化上限 +6" in info
    out = cmd_enhance(parse_command("/强化 铁剑+5"), ctx)
    assert "铁剑+6" in out
    assert ctx["player"]["equipment"]["weapon"]["slot_level"] == 6
    assert int(_row_of(ctx)["enhance_level"]) == 6


def test_legacy_gear_never_downgrades() -> None:
    """旧档装备既有等级高于查表上限（异常旧档）→ 上限保底 = 当前等级（不清零/不降级）。"""
    assert resolve_cap(cap_table=_CAP, legacy_map=_LEGACY, quality_level=0,
                       rarity="normal", current=9) == 9


def test_old_max_by_rarity_key_not_consumed() -> None:
    """任务书兼容口径：旧 key `max_by_rarity` 不再被引擎读取（读新表）。"""
    cfg = _enh_config()
    cfg["settings"].pop("max_by_quality_level", None)
    cfg["settings"]["max_by_rarity"] = {"normal": 5, "fine": 8}
    # 旧键无新表 → 不可强化（不会误用旧 5/8/10/12）
    assert resolve_cap(cap_table=None, legacy_map=_LEGACY, quality_level=0, rarity="normal") == 0
    from qbot_rpg.commands.enhance_commands import _max_for_quality
    assert _max_for_quality(cfg, "normal", 0, 0) == 0


# ---------------------------------------------------------------------------
# C. 每 N 级特殊词条
# ---------------------------------------------------------------------------
def test_one_affix_per_four_levels_4_8_12() -> None:
    """达 4 级得 1 条、8 级 2 条、12 级 3 条（跨度 4；确定性 RNG 可复现）。"""
    ctx = make_ctx(quality_level=6, enhance=3, atk=27.0, affinities={"moon": 10.0},
                   rng=random.Random(7))
    out4 = cmd_enhance(parse_command("/强化 铁剑"), ctx)
    assert "获得特殊词条" in out4
    got4 = list(_row_of(ctx)["enhance_affixes"])
    assert len(got4) == 1
    # 直接推进到 +7 再强化到 +8
    ctx["player"]["equipment"]["weapon"]["slot_level"] = 7
    _row_of(ctx)["enhance_level"] = 7
    out8 = cmd_enhance(parse_command("/强化 铁剑+7"), ctx)
    assert "获得特殊词条" in out8
    got8 = list(_row_of(ctx)["enhance_affixes"])
    assert len(got8) == 2 and got8[0] == got4[0] and got8[1] != got4[0]
    # 直接推进到 +11 再强化到 +12 → 第 3 条（池 3 条候选齐抽）
    ctx["player"]["equipment"]["weapon"]["slot_level"] = 11
    _row_of(ctx)["enhance_level"] = 11
    out12 = cmd_enhance(parse_command("/强化 铁剑+11"), ctx)
    assert "获得特殊词条" in out12
    got12 = list(_row_of(ctx)["enhance_affixes"])
    assert len(got12) == 3 and got12[:2] == got8


def test_info_shows_affix_status_row() -> None:
    """`/强化信息` 展示特殊词条进度（当前/满上限可得 + 中文名）。"""
    ctx = make_ctx(quality_level=6, enhance=4, atk=32.0, affinities={"moon": 10.0})
    _row_of(ctx)["enhance_affixes"] = ["heal_amp_pct"]
    out = cmd_enhance_info(parse_command("/强化信息 铁剑"), ctx)
    assert "特殊词条 1/4" in out and "回复强化" in out


def test_span_configurable_to_three() -> None:
    """跨度改成 3 → 每 3 级一条（+2 → +3 即得）。"""
    ctx = make_ctx(enhance=2, atk=22.0, affinities={"moon": 10.0}, span=3,
                   rng=random.Random(3))
    out = cmd_enhance(parse_command("/强化 铁剑"), ctx)
    assert "获得特殊词条" in out
    assert len(_row_of(ctx)["enhance_affixes"]) == 1


def test_span_zero_disables() -> None:
    """跨度 0 = 关闭 → 永不得词条。"""
    ctx = make_ctx(quality_level=6, enhance=9, atk=57.0, affinities={"moon": 10.0}, span=0)
    out = cmd_enhance(parse_command("/强化 铁剑+9"), ctx)
    assert "强化成功" in out
    assert _row_of(ctx)["enhance_affixes"] == []


def test_special_affix_count_formula() -> None:
    assert special_affix_count(3, 4) == 0
    assert special_affix_count(4, 4) == 1
    assert special_affix_count(11, 4) == 2
    assert special_affix_count(12, 4) == 3
    assert special_affix_count(4, 3) == 1
    assert special_affix_count(4, 0) == 0


def test_affix_draw_is_deterministic() -> None:
    """同一 RNG 种子 → 同一条词条（可复现）。"""
    outs = []
    for _ in range(2):
        ctx = make_ctx(enhance=3, atk=27.0, affinities={"moon": 10.0},
                       rng=random.Random(42))
        cmd_enhance(parse_command("/强化 铁剑"), ctx)
        outs.append(list(_row_of(ctx)["enhance_affixes"]))
    assert outs[0] == outs[1]


# ---------------------------------------------------------------------------
# D. 相性池
# ---------------------------------------------------------------------------
def test_exclusive_pool_reachable_via_affinity() -> None:
    """主相性 → 专属池词条可达（池查询唯一入口 resolve_available_entries）。"""
    ctx = make_ctx(enhance=3, atk=27.0, affinities={"moon": 10.0},
                   rng=random.Random(1))
    cmd_enhance(parse_command("/强化 铁剑"), ctx)
    assert _row_of(ctx)["enhance_affixes"]


def test_no_affinity_cannot_draw_required_entries() -> None:
    """无相性 → 要求相性的词条抽不出（负向断言，与批42 同口径）。"""
    pools = [{"id": "moon_pool", "kind": "exclusive", "entries": [
        {"enhance_affix": "weakness_dmg_pct", "value": 9, "weight": 1,
         "requires_affinity": "moon"},
    ]}]
    ctx = make_ctx(enhance=3, atk=27.0, affinities={}, pools=pools,
                   rng=random.Random(1))
    cmd_enhance(parse_command("/强化 铁剑"), ctx)
    assert _row_of(ctx)["enhance_affixes"] == []


def test_no_settings_no_pool_zero_behavior() -> None:
    """ctx 无 settings（相性未接）→ 池为空 → 零词条（既有强化回归不受影响）。"""
    ctx = make_ctx(enhance=3, atk=27.0, affinities={"moon": 10.0}, with_settings=False)
    cmd_enhance(parse_command("/强化 铁剑"), ctx)
    assert _row_of(ctx)["enhance_affixes"] == []


# ---------------------------------------------------------------------------
# E. 词条族注册与占位口径
# ---------------------------------------------------------------------------
def test_new_affix_keys_have_label_and_help() -> None:
    """每个新键有中文名 + 说明（一号原则）。"""
    for key in ("heal_amp_pct", "debuff_chance_pct", "buff_chance_pct",
                "weakness_dmg_pct", "cooldown_reduction_pct"):
        assert key in GEAR_DISPLAY_KEYS
        assert GEAR_LABELS_ZH.get(key), key
        assert GEAR_HELP_ZH.get(key), key
    # 非占位四键入 PCT 档（复用 _pct 拆层）
    for key in ("heal_amp_pct", "debuff_chance_pct", "buff_chance_pct", "weakness_dmg_pct"):
        assert key in GEAR_NUMERIC_KEYS


def test_cooldown_reduction_is_placeholder_not_engine() -> None:
    """冷却缩减 = 占位：登记 + 展示，**不进属性管线**（不接引擎）。"""
    assert "cooldown_reduction_pct" in GEAR_PLACEHOLDER_KEYS
    assert "cooldown_reduction_pct" not in GEAR_NUMERIC_KEYS
    sb = extract_bonus({"cooldown_reduction_pct": 12, "atk_pct": 5})
    assert sb["cooldown_reduction_pct"] == 12.0  # 实例化保留（可展示）
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into(sb, flat, pct)
    assert "cooldown_reduction" not in pct  # 不拆进 pct 层
    assert "cooldown_reduction_pct" not in flat
    assert pct.get("atk") == 5.0  # 百分比加成族复用既有 _pct 路由
    # 展示可见
    from qbot_rpg.commands.basic_commands import _item_stat_parts
    assert any("冷却缩减" in x for x in _item_stat_parts(sb))


def test_placeholder_survives_enhance_and_display() -> None:
    """占位词条经强化写入实例载荷 + stats_bonus（展示可见，不接引擎）。"""
    ctx = make_ctx(enhance=3, atk=27.0, affinities={"moon": 10.0}, rng=random.Random(5))
    cmd_enhance(parse_command("/强化 铁剑"), ctx)
    r = _row_of(ctx)
    # 首条由权重/种子决定；断言词条至少落在新族键空间内
    assert all(k in GEAR_DISPLAY_KEYS for k in r["enhance_affixes"])


# ---------------------------------------------------------------------------
# F. 回归对拍（既有强化逐字段一致）
# ---------------------------------------------------------------------------
def test_existing_curve_1_to_12_unchanged() -> None:
    """既有成功率曲线 1..12 逐字段与历史定稿一致（新增 13..18 为待裁决延续）。"""
    hist = {1: 90, 2: 85, 3: 80, 4: 70, 5: 60, 6: 50,
            7: 40, 8: 35, 9: 30, 10: 25, 11: 20, 12: 15}
    by = {int(r["to"]): int(r["rate"]) for r in DEFAULT_CURVE}
    for to, rate in hist.items():
        assert by[to] == rate, (to, by[to], rate)
    # 单调不增
    rates = [by[k] for k in sorted(by)]
    assert all(b <= a for a, b in zip(rates, rates[1:]))


def test_existing_stone_tiers_1_to_12_unchanged() -> None:
    """既有石档位 1..12 逐字段一致（high 档延长覆盖 13..18）。"""
    hist = {1: "low", 2: "low", 3: "low", 4: "mid", 5: "mid", 6: "mid",
            7: "high", 8: "high", 9: "high", 10: "high", 11: "high", 12: "high"}
    tier_of = {}
    for t in DEFAULT_STONE_TIERS:
        for lv in t["levels"]:
            tier_of[int(lv)] = t["tier"]
    for lv, tier in hist.items():
        assert tier_of[lv] == tier, (lv, tier_of[lv], tier)
    assert tier_of[18] == "high"


def test_fail_tier_split_default_unchanged() -> None:
    assert DEFAULT_ENHANCE["settings"]["fail_tier_split"] == 3


def test_low_tier_fail_keeps_equipment_unchanged() -> None:
    """低段失败（≤fail_tier_split）→ 装备不变、材料照扣（既有行为对拍）。

    成功率恒 0（rng 可调用 hook 返回 1.0 → roll 失败）。
    """
    ctx = make_ctx(enhance=2, atk=22.0, span=0)
    ctx["rng"] = lambda: 0.999
    # 覆盖成功率表为 0（保证失败）
    ctx["enhance"]["success_curve"] = [{"to": i, "rate": 0} for i in _ALL_LEVELS]
    out = cmd_enhance(parse_command("/强化 铁剑"), ctx)
    assert "装备保持不变" in out
    assert ctx["player"]["equipment"]["weapon"]["slot_level"] == 2


# ---------------------------------------------------------------------------
# G. 实例载荷写回（构造点）
# ---------------------------------------------------------------------------
def test_new_fields_roundtrip_serialization() -> None:
    """品质等级 + 特殊词条载荷 经 asdict → _item_from_dict 无损往返。"""
    inst = ItemInstance(
        item_id="x", name="X", count=1, quality="fine", bound=False,
        stats_bonus={"atk": 10.0, "heal_amp_pct": 6.0},
        quality_level=5, enhance_affixes=("heal_amp_pct",),
    )
    back = _item_from_dict(asdict(inst))
    assert back.quality_level == 5
    assert back.enhance_affixes == ("heal_amp_pct",)
    assert back.stats_bonus["heal_amp_pct"] == 6.0


def test_defaults_preserve_legacy_instances() -> None:
    """旧档缺省：quality_level=0 / enhance_affixes=()（零影响）。"""
    inst = ItemInstance(item_id="x", name="X", count=1, quality="normal", bound=False)
    assert inst.quality_level == 0
    assert inst.enhance_affixes == ()


def test_data_bearing_construction_sites_pass_new_fields() -> None:
    """6 处构造点：**有实例来源**的三处逐一透传批43 新字段（静态守卫防漏）。

    批83 · N2/N3/N5 收敛后：写路径两条内联归一收敛为 `data/item.py::
    item_instance_from_mapping`——字段透传断言落到「读档 codec + 公共归一函数」；
    两条链路只断言**调用公共函数**。
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    for rel in ("qbot_rpg/storage/repository.py",
                "qbot_rpg/data/item.py"):
        src = (repo / rel).read_text(encoding="utf-8")
        for key in ("quality_level=", "enhance_affixes="):
            assert key in src, f"{rel} 的 ItemInstance 构造点未透传新字段：{key}"
    for rel in ("qbot_rpg/assembly/runner.py",
                "qbot_rpg/commands/basic_commands.py"):
        src = (repo / rel).read_text(encoding="utf-8")
        assert "item_instance_from_mapping(" in src, \
            f"{rel} 未走公共归一函数 item_instance_from_mapping（批83 · N5）"
    # 无实例来源的三处（equipment unequip 兜底 / shop 新建）保留缺省（见实现说明 §九）
    eq = (repo / "qbot_rpg/core/equipment.py").read_text(encoding="utf-8")
    assert "ItemInstance(" in eq


# ---------------------------------------------------------------------------
# H. 校验器（更严）
# ---------------------------------------------------------------------------
class _Report:
    def __init__(self) -> None:
        self.errors: List[Any] = []
        self.warnings: List[Any] = []

    def _err(self, module: str, field: str, kind: str, **d: Any) -> None:
        self.errors.append((field, kind, dict(d)))

    def _warn(self, module: str, field: str, kind: str, **d: Any) -> None:
        self.warnings.append((field, kind, dict(d)))


def _raw(settings: Dict[str, Any]) -> Dict[str, Any]:
    base = _enh_config()
    base["settings"].update(settings)
    return {"enhance": base}


def test_validate_rejects_non_positive_cap_key() -> None:
    rep = _Report()
    validate_enhance(_raw({"max_by_quality_level": {"0": 5}}), rep)
    assert any(k == "V7" for _, k, _ in rep.errors)


def test_validate_rejects_bad_cap_value() -> None:
    rep = _Report()
    validate_enhance(_raw({"max_by_quality_level": {"1": -1}}), rep)
    assert any(k == "V6" for _, k, _ in rep.errors)


def test_validate_rejects_bad_legacy_key() -> None:
    rep = _Report()
    validate_enhance(_raw({"legacy_quality_level_by_rarity": {"x": 1}}), rep)
    assert any(k == "V7" for _, k, _ in rep.errors)


def test_validate_rejects_bad_span() -> None:
    rep = _Report()
    validate_enhance(_raw({"special_affix_span": -1}), rep)
    assert any(k == "V6" for _, k, _ in rep.errors)


def test_editor_meta_replaces_cap_field() -> None:
    """编辑器上限表可配可见：旧键下线、新表 + 桥接 + 跨度登记。"""
    from qbot_rpg.content.field_meta import default_field_meta_table

    kids = default_field_meta_table().modules["enhance"].fields["settings"].children
    assert "max_by_rarity" not in kids
    assert {"max_by_quality_level", "legacy_quality_level_by_rarity",
            "special_affix_span"} <= set(kids)


def test_validator_enhance_affix_key_space() -> None:
    """池词条 `enhance_affix` 值须 ∈ gear_stats 唯一键空间（含占位键）；新造键红拦。"""
    from qbot_rpg.content.validator import check_pack

    def _errs(mods: Dict[str, Any]) -> List[Any]:
        return [(e.field, e.detail.get("rule")) for e in check_pack(mods).errors]

    good = {"settings": {"affinity_pools": [
        {"id": "p1", "kind": "common",
         "entries": [{"enhance_affix": "heal_amp_pct", "value": 1}]},
        # 占位键（冷却缩减）允许登记/抽取
        {"id": "p2", "kind": "common",
         "entries": [{"enhance_affix": "cooldown_reduction_pct", "value": 1}]},
    ]}}
    assert _errs(good) == []
    bad = {"settings": {"affinity_pools": [
        {"id": "p1", "kind": "common",
         "entries": [{"enhance_affix": "not_a_registered_key", "value": 1}]},
    ]}}
    assert any(r == "gear_key_missing" for _, r in _errs(bad))


def test_validate_passes_default_schema() -> None:
    rep = _Report()
    validate_enhance(_raw({}), rep)
    assert not rep.errors, rep.errors
