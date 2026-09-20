"""批57 · 装备淬炼（temper）+ 分解回收（精粹）+ 循环模拟 单测。

覆盖（对齐任务书「测试与验收」）：
  A 缺省零变化：不配 temper / 不启用精粹 → 引擎不消费、既有强化段逐字段一致。
  B 淬炼上限：单项提升 / 总上限 / 单项上限 / 越限拒绝 / 覆盖表 / 属性白名单 / 消耗。
  C 与强化分账：materialize 只动物化 stats_bonus、不碰 enhance_level；配置段不互相污染。
  D 幂等物化：重放不双计；分配为准；重置回退且不返还。
  E 精粹产出公式：V × k1 × k2 × β^色序（报告 §3.1）；取整/图纸档/单件上限。
  F 返还衰减（主 agent ② 真闸门）：每点返还随淬炼量单调下降，且恒 < 消耗。
  G 经济循环：典型循环产出/消耗 ≈ 1.00×（不再是 84:1）；N 轮模拟余额单调递减（无套利）。
  H 实例分解引擎：按 uid 实例出材料 + 精粹；scope 限定；V 解析。
  I 命令级 uid 分解 E2E：能分解 uid 实例（扣实例 + 返材料 + 入精粹）；未启用回退既有路径。
  J 持久化 / 迁移 / 卸装：字段随实例走（uid 锚定）、读档往返、幂等回填、卸装不丢。
  K 校验器：enhance V8~V13 + settings essence_rate 结构/引用红拦。
  L 编辑器元数据：temper / essence_rate 字段可见、中文名与说明齐备。

纪律：样本全部合成 ctx / 临时目录，**不写任何真实内容包**；不依赖真实玩家库。
"""
from __future__ import annotations

import types
from dataclasses import asdict, replace
from typing import Any, Dict, List, Optional


from qbot_rpg.commands.alchemy_commands import cmd_decompose
from qbot_rpg.content.enhance_models import (
    DEFAULT_CURVE,
    DEFAULT_ENHANCE,
    DEFAULT_VALUES,
    enhance_module_meta,
    parse_enhance_settings,
    validate_enhance,
)
from qbot_rpg.content.forge_settings import (
    FORGE_SETTINGS_DEFAULTS,
    forge_settings_meta,
    read_forge_settings,
)
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.decompose import (
    grant_currency,
    instance_is_crafted,
    material_recovery,
    plan_instance_decompose,
    resolve_invested_value,
)
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.temper import (
    DEFAULT_TEMPER,
    allowed_stats_of,
    cap_state,
    essence_base,
    essence_color_order,
    essence_for_instance,
    materialize_temper,
    normalize_essence_config,
    normalize_temper_config,
    per_stat_cap_of,
    plan_temper,
    reset_alloc,
    resolve_equipment_level,
    simulate_cycle,
    temper_cost,
    temper_refund,
    total_cap_of,
    typical_cycle,
)
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, PlayerAttributes
from qbot_rpg.data.temper_stats import DEFAULT_ESSENCE_RATE
from qbot_rpg.storage.migrations import backfill_instance_temper
from qbot_rpg.storage.repository import _item_from_dict

# 合成淬炼配置：等级 35、上限系数 6 → 总 210 / 单项 105（报告 §4.1 A3 的合成口径，
# **非**真实内容包；全部显式声明 → 不依赖任何包）。
_TEMPER = {"enabled": True, "cap_per_level": 6, "per_stat_cap_ratio": 0.5,
           "cost_per_point": {"essence": 1593, "currency": 0}}
_ESSENCE = {"enabled": True}
_LEVEL = 35
_V_GRAD = 100600.0  # 报告 §4.2 实测：毕业武器节点材料价值（合成常量）


def _instance(*, uid: str = "a" * 32, level: int = _LEVEL, alloc: Optional[Dict[str, int]] = None,
              stats: Optional[Dict[str, float]] = None, quality: str = "白",
              qlevel: int = 5, item_id: str = "sword_x", name: str = "X剑") -> ItemInstance:
    return ItemInstance(
        item_id=item_id, name=name, count=1, quality=quality, bound=False, stack_max=1,
        slot="weapon", stats_bonus=dict(stats or {"atk": 100}), uid=uid,
        required_level=level, quality_level=qlevel, temper_alloc=dict(alloc or {}),
    )


# ===========================================================================
# A. 缺省零变化
# ===========================================================================
def test_a1_temper_disabled_by_default() -> None:
    cfg = normalize_temper_config(None)
    assert cfg["enabled"] is False
    assert cfg == normalize_temper_config({})
    chk = plan_temper({"atk": 1}, {}, "atk", 1, level=35, cfg=cfg)
    assert chk["ok"] is False and chk["reason"] == "disabled"


def test_a2_essence_disabled_by_default() -> None:
    assert normalize_essence_config(None)["enabled"] is False
    assert read_forge_settings({})["essence_rate"]["enabled"] is False
    plan = plan_instance_decompose(_instance(), cfg={})
    assert plan["ok"] is False and plan["reason"] == "essence_disabled"


def test_a3_instance_new_fields_default_empty() -> None:
    inst = ItemInstance(item_id="x", name="x", count=1, quality="normal", bound=False)
    assert inst.required_level == 0
    assert inst.temper_alloc == {}
    # 新字段默认空 → 不影响既有字段/序列化语义（除新增两键外逐字段一致）
    d = asdict(inst)
    assert d["required_level"] == 0 and d["temper_alloc"] == {}
    assert d["enhance_level"] == 0 and d["stats_bonus"] == {}


def test_a4_enhance_legacy_sections_unchanged() -> None:
    """temper 段为**纯新增**：既有 5 段（settings/cost/curve/values/protect_stone）逐字段不变。"""
    parsed = parse_enhance_settings({})
    base = {k: v for k, v in DEFAULT_ENHANCE.items() if k != "temper"}
    got = {k: v for k, v in parsed.items() if k != "temper"}
    assert got == base
    assert parsed["success_curve"] == DEFAULT_CURVE
    assert parsed["values"] == DEFAULT_VALUES


def test_a5_forge_defaults_new_key_only() -> None:
    raw = read_forge_settings({})
    for k, v in FORGE_SETTINGS_DEFAULTS.items():
        if k != "essence_rate":
            assert raw[k] == v
    assert raw["essence_rate"]["enabled"] is False


# ===========================================================================
# B. 淬炼上限 / 越限
# ===========================================================================
def test_b1_caps_by_level() -> None:
    cfg = normalize_temper_config(_TEMPER)
    assert total_cap_of(35, cfg) == 210
    assert total_cap_of(10, cfg) == 60
    assert per_stat_cap_of("atk", 210, cfg) == 105
    st = cap_state({"atk": 30}, 35, cfg)
    assert st["total_used"] == 30 and st["total_remaining"] == 180
    assert st["per_stat"]["atk"] == {"used": 30, "cap": 105, "remaining": 75}


def test_b2_single_point_raise() -> None:
    cfg = normalize_temper_config(_TEMPER)
    p = plan_temper({"atk": 100}, {}, "atk", 1, level=35, cfg=cfg, essence_balance=10 ** 9)
    assert p["ok"] is True
    assert p["new_alloc"] == {"atk": 1}
    assert p["delta"] == 1.0
    assert p["cost"] == {"essence": 1593, "currency": 0}


def test_b3_per_stat_cap_reject() -> None:
    cfg = normalize_temper_config(_TEMPER)
    bad = plan_temper({"atk": 100}, {"atk": 105}, "atk", 1, level=35, cfg=cfg)
    assert bad["ok"] is False and bad["reason"] == "per_stat_cap"


def test_b4_total_cap_reject() -> None:
    cfg = normalize_temper_config(_TEMPER)
    alloc = {"atk": 105, "hp": 105}  # 合计 = 210 = 总上限
    # 目标属性单品未超限（mp 0/105），但总点数会越界 → total_cap
    bad = plan_temper({"atk": 100, "hp": 100, "mp": 100}, alloc, "mp", 1, level=35, cfg=cfg)
    assert bad["ok"] is False and bad["reason"] == "total_cap"


def test_b5_allowed_stats_and_reject() -> None:
    cfg = normalize_temper_config(_TEMPER)
    assert allowed_stats_of({"atk": 1, "hp": 2}, cfg) == ("atk", "hp")
    # 空属性 → 回退框架白值键族
    assert "atk" in allowed_stats_of({}, cfg)
    bad = plan_temper({"atk": 1}, {}, "not_a_stat", 1, level=35, cfg=cfg)
    assert bad["ok"] is False and bad["reason"] == "stat_not_allowed"


def test_b6_not_enough_essence() -> None:
    cfg = normalize_temper_config(_TEMPER)
    bad = plan_temper({"atk": 1}, {}, "atk", 1, level=35, cfg=cfg, essence_balance=100)
    assert bad["ok"] is False and bad["reason"] == "not_enough_essence"


def test_b7_cost_growth_and_weight_and_currency() -> None:
    cfg = normalize_temper_config({
        "enabled": True, "cap_per_level": 6, "cost_growth": 0.5,
        "cost_per_point": {"essence": 100, "currency": 10},
        "stat_weight": {"crit": 2.0},
    })
    flat = temper_cost("atk", 0, 210, 1, cfg)
    assert flat == {"essence": 100, "currency": 10}
    heavy = temper_cost("crit", 0, 210, 1, cfg)
    assert heavy == {"essence": 200, "currency": 20}
    grown = temper_cost("atk", 210, 210, 1, cfg)  # 已满投 → ×(1+0.5)
    assert grown["essence"] == 150


def test_b8_cap_overrides() -> None:
    cfg = normalize_temper_config(dict(_TEMPER, total_cap=40, per_stat_cap={"atk": 12}))
    assert total_cap_of(35, cfg) == 40
    assert per_stat_cap_of("atk", 40, cfg) == 12
    assert per_stat_cap_of("hp", 40, cfg) == 20
    cfg2 = normalize_temper_config(dict(_TEMPER, total_cap=None,
                                        total_cap_by_level={"35": 99}))
    assert total_cap_of(35, cfg2) == 99


def test_b9_level_missing_cap_zero() -> None:
    cfg = normalize_temper_config(_TEMPER)
    assert resolve_equipment_level(0, cfg) == 0
    assert total_cap_of(0, cfg) == 0
    bad = plan_temper({"atk": 1}, {}, "atk", 1, level=0, cfg=cfg)
    assert bad["ok"] is False and bad["reason"] in ("per_stat_cap", "total_cap")
    # default_level 可配兜底
    cfg2 = normalize_temper_config(dict(_TEMPER, default_level=10))
    assert total_cap_of(resolve_equipment_level({}, cfg2), cfg2) == 60


# ===========================================================================
# C. 与强化分账
# ===========================================================================
def test_c1_materialize_does_not_touch_enhance_level() -> None:
    inst = _instance(alloc={"atk": 3})
    old = dict(inst.temper_alloc)
    new = {"atk": 4}
    sb = materialize_temper(inst.stats_bonus, old, new, normalize_temper_config(_TEMPER))
    assert sb["atk"] == 101.0  # 100 + (4-3)
    # 分账：物化只产 stats_bonus，不含 enhance_level（不污染强化账本）
    assert "enhance_level" not in sb
    assert replace(inst, stats_bonus=sb).enhance_level == inst.enhance_level == 0


def test_c2_plan_has_no_enhance_key() -> None:
    cfg = normalize_temper_config(_TEMPER)
    p = plan_temper({"atk": 1}, {}, "atk", 1, level=35, cfg=cfg)
    assert "enhance_level" not in p
    assert set(p["new_alloc"]) == {"atk"}


def test_c3_enhance_config_not_consumed_by_temper() -> None:
    """既有强化「成功率/失败段」不因淬炼而改（成功曲线/石档位保持原值）。"""
    parsed = parse_enhance_settings({"temper": {"enabled": True}})
    assert parsed["success_curve"] == DEFAULT_CURVE
    assert parsed["settings"].get("fail_tier_split", 3) == 3
    assert parsed["cost"]["stone_tiers"]  # 石档位段原样存在


# ===========================================================================
# D. 幂等物化 / 重置
# ===========================================================================
def test_d1_first_materialize() -> None:
    cfg = normalize_temper_config(_TEMPER)
    assert materialize_temper({"atk": 10}, {}, {"atk": 3}, cfg) == {"atk": 13.0}


def test_d2_replay_is_idempotent() -> None:
    cfg = normalize_temper_config(_TEMPER)
    sb = {"atk": 13.0}
    assert materialize_temper(sb, {"atk": 3}, {"atk": 3}, cfg) == {"atk": 13.0}


def test_d3_incremental_delta_not_double_count() -> None:
    cfg = normalize_temper_config(_TEMPER)
    assert materialize_temper({"atk": 13.0}, {"atk": 3}, {"atk": 5}, cfg) == {"atk": 15.0}


def test_d4_reset_reverts_and_no_refund() -> None:
    cfg = normalize_temper_config(_TEMPER)
    r = reset_alloc({"atk": 5}, cfg)
    assert r["ok"] is True and r["new_alloc"] == {} and r["refund"] == 0
    assert materialize_temper({"atk": 15.0}, {"atk": 5}, {}, cfg) == {"atk": 10.0}


# ===========================================================================
# E. 精粹产出公式
# ===========================================================================
def test_e1_essence_base_formula() -> None:
    cfg = normalize_essence_config(_ESSENCE)
    # 100600 × 0.35 × 0.50 × 1.2^0 = 17605（报告 §4.3 基准白装）
    assert essence_base(100600, 0, cfg) == 17605
    # β 正向：红（色序 5）→ 17605 × 1.2^5 = 43806.6 → floor 43806
    assert essence_base(100600, 5, cfg) == 43806
    assert essence_base(0, 0, cfg) == 0


def test_e2_grade_override_and_rounding() -> None:
    cfg = normalize_essence_config(dict(_ESSENCE, grade_of={"彩": 0.60}))
    assert essence_base(1000, 0, cfg, "彩") == 210       # 1000*0.35*0.6
    assert essence_base(1000, 0, cfg, "铜") == 175       # 回退 k2=0.5
    for mode, exp in (("floor", 175), ("round", 175), ("ceil", 175)):
        assert essence_base(1000, 0, normalize_essence_config(
            dict(_ESSENCE, rounding=mode)), "铜") == exp
    assert essence_base(1001, 0, normalize_essence_config(
        dict(_ESSENCE, rounding="floor")), "铜") == 175
    assert essence_base(1001, 0, normalize_essence_config(
        dict(_ESSENCE, rounding="ceil")), "铜") == 176


def test_e3_cap_per_item() -> None:
    cfg = normalize_essence_config(dict(_ESSENCE, cap_per_item=100))
    assert essence_base(100600, 0, cfg) == 100


def test_e4_color_order() -> None:
    cfg = normalize_essence_config(_ESSENCE)
    colors = ["白", "绿", "蓝", "紫", "橙", "红"]
    assert essence_color_order("白", cfg, colors) == 0
    assert essence_color_order("红", cfg, colors) == 5
    assert essence_color_order("未知", cfg, colors) == 0
    override = normalize_essence_config(dict(_ESSENCE, color_order={"红": 1}))
    assert essence_color_order("红", override, colors) == 1


def test_e5_essence_for_instance_folds_refund() -> None:
    ec = normalize_essence_config(_ESSENCE)
    tc = normalize_temper_config(_TEMPER)
    got = essence_for_instance(value=100600, quality="白", temper_points=210,
                               total_cap=total_cap_of(35, tc), cfg=ec)
    assert got["base"] == 17605
    assert got["refund"] == temper_refund(210, 210, ec)
    assert got["total"] == got["base"] + got["refund"]


# ===========================================================================
# F. 返还衰减（真闸门）
# ===========================================================================
def test_f1_refund_decays_with_investment() -> None:
    ec = normalize_essence_config(_ESSENCE)
    cap = 210
    per_point = []
    for frac in (0.25, 0.5, 1.0):
        p = int(round(cap * frac))
        r = temper_refund(p, cap, ec)
        per_point.append(r / p)
        assert r < p * 1593  # 恒 < 消耗（G6）
    # 每点返还**严格下降**（衰减）
    assert per_point[0] > per_point[1] > per_point[2]


def test_f2_refund_zero_when_disabled_ratio() -> None:
    ec = normalize_essence_config(dict(_ESSENCE, temper_refund=0))
    assert temper_refund(210, 210, ec) == 0


def test_f3_refund_requires_cost_relation() -> None:
    """G6：temper_refund 必须 ≤ cost_per_point.essence（校验器 V8 红拦，见 K2）。"""
    ec = normalize_essence_config(dict(_ESSENCE, temper_refund=2000))
    assert temper_refund(210, 210, ec) > 210 * 1593 * 0  # 数值合法但被校验器拦
    rep = _Report()
    validate_enhance({
        "enhance": {"temper": _TEMPER},
        "settings": {"forge": {"essence_rate": {"enabled": True, "temper_refund": 2000}}},
    }, rep)
    assert any(k == "V8" for _f, k, _d in rep.errors)


# ===========================================================================
# G. 经济循环（两处数值证据）
# ===========================================================================
def test_g1_typical_cycle_not_84to1() -> None:
    cyc = typical_cycle(value=_V_GRAD, level=35)
    assert cyc["cap"] == 210
    assert cyc["per_item_essence"] == 17605
    assert cyc["produced"] == 1672475
    assert cyc["consumed"] == 1672650
    assert 0.99 <= cyc["ratio"] <= 1.01          # ≈ 1.00×（p=1 时才是 1593×）
    assert 1590 <= cyc["balance_point_p"] <= 1595  # 反解平衡点 ≈ 1593


def test_g2_cycle_no_arbitrage_monotonic() -> None:
    sim = simulate_cycle(rounds=20, value=_V_GRAD, level=35,
                         decompose_per_round=1, temper_per_round=1,
                         start_essence=400000)
    assert sim["per_round_delta"] < 0
    assert sim["monotonic_decrease"] is True
    assert sim["rows"][-1]["balance"] < sim["rows"][0]["balance"]


def test_g3_refund_curve_diminishing() -> None:
    sim = simulate_cycle(rounds=3, value=_V_GRAD, level=35)
    ratios = [row["ratio"] for row in sim["refund_curve"]]
    assert ratios == sorted(ratios, reverse=True)
    assert all(0.0 <= r < 1.0 for r in ratios)


def test_g4_zero_refund_is_strictly_one_way() -> None:
    sim = simulate_cycle(rounds=5, value=_V_GRAD, level=35,
                         cfg_essence={"enabled": True, "temper_refund": 0})
    assert sim["refund_full"] == 0
    assert sim["per_round_delta"] < 0


# ===========================================================================
# H. 实例分解引擎
# ===========================================================================
def test_h1_uid_instance_decompose_plan() -> None:
    inst = _instance(alloc={"atk": 210})
    node = [{"item": "a", "count": 15}, {"item": "b", "count": 8}]
    prices = {"a": 5000, "b": 3200}
    plan = plan_instance_decompose(inst, cfg=_ESSENCE, cfg_temper=_TEMPER,
                                   node_materials=node, prices=prices,
                                   material_rate=0.65,
                                   declared_colors=["白", "绿", "蓝", "紫", "橙", "红"])
    assert plan["ok"] is True
    assert plan["uid"] == inst.uid and plan["item_id"] == "sword_x"
    assert plan["value"] == 100600.0
    assert plan["materials"] == [("a", "a", 9), ("b", "b", 5)]
    assert plan["essence"]["base"] == 17605
    assert plan["essence"]["refund"] == 84000
    assert plan["essence"]["total"] == 101605


def test_h2_scope_crafted_only() -> None:
    plain = ItemInstance(item_id="ring", name="戒指", count=1, quality="normal",
                         bound=False, uid="c" * 32)
    assert instance_is_crafted(plain) is False
    assert plan_instance_decompose(plain, cfg=_ESSENCE)["reason"] == "scope_not_allowed"
    # all_equipment 范围放行（有 uid 即可）
    plan = plan_instance_decompose(plain, cfg=dict(_ESSENCE, scope="all_equipment"),
                                   prices={}, item_def={"price": 100})
    assert plan["ok"] is True and plan["essence"]["base"] == 17


def test_h3_material_recovery_floors() -> None:
    assert material_recovery([("a", 3), ("b", 1)], 0.5) == [("a", "a", 1)]
    assert material_recovery([], 0.5) == []
    assert material_recovery([("a", 3)], 0.0) == []


def test_h4_resolve_invested_value_bases() -> None:
    node = [{"item": "a", "count": 15}, {"item": "b", "count": 8}]
    prices = {"a": 5000, "b": 3200}
    inst = _instance()
    ec = normalize_essence_config(_ESSENCE)
    assert resolve_invested_value(inst, node_materials=node, prices=prices, cfg=ec) == 100600.0
    assert resolve_invested_value(inst, item_def={"price": 77}, cfg=ec) == 77.0
    assert resolve_invested_value(inst, cfg=normalize_essence_config(
        dict(_ESSENCE, v_basis="fixed", v_fixed=5))) == 5.0
    assert resolve_invested_value(_instance(level=10), cfg=normalize_essence_config(
        dict(_ESSENCE, v_basis="level_scaled", v_per_level=10))) == 100.0


def test_h5_no_uid_rejected() -> None:
    class _NoUid:
        uid = ""
    assert plan_instance_decompose(_NoUid(), cfg=_ESSENCE)["reason"] == "no_uid"


def test_h6_grant_currency_space_hard_gate() -> None:
    bucket: Dict[str, int] = {}
    bad = grant_currency(bucket, "essence", 5, ("coins",))
    assert bad["ok"] is False and bad["reason"] == "unknown_currency"
    ok = grant_currency(bucket, "essence", 5, ("coins", "essence"))
    assert ok["ok"] is True and bucket["essence"] == 5
    assert grant_currency(bucket, "essence", -1, ("essence",))["reason"] == "invalid_amount"


# ===========================================================================
# I. 命令级 uid 分解 E2E
# ===========================================================================
def _decompose_ctx(inst: ItemInstance, *, enabled: bool = True) -> Dict[str, Any]:
    player: Dict[str, Any] = {"inventory": [inst], "equipment": {},
                              "currencies": {}, "level": 10, "proficiency": {}}
    added: List[Any] = []
    ctx: Dict[str, Any] = {
        "player": player, "currencies": player["currencies"],
        "items": {"sword_x": {"id": "sword_x", "name": "X剑", "price": 100},
                  "a": {"id": "a", "name": "材A", "price": 5000},
                  "b": {"id": "b", "name": "材B", "price": 3200}},
        "forge": {"trees": [{"nodes": [{"item": "sword_x", "materials": [
            {"item": "a", "count": 15}, {"item": "b", "count": 8}]}]}]},
        "settings": {
            "forge": {"essence_rate": {"enabled": enabled}},
            "currencies": [{"id": "coins", "name": "金币"},
                           {"id": "essence", "name": "装备精粹"}],
            "deep_craft": {"quality_colors": [{"id": c} for c in
                                              ["白", "绿", "蓝", "紫", "橙", "红"]]},
        },
        "wallet": types.SimpleNamespace(decompose_rate=lambda _i: 0.65),
        "add_item": lambda iid, n: added.append((str(iid), int(n))),
        "enhance": {"temper": {"enabled": True}},
    }
    ctx["_added"] = added
    return ctx


def _run(coro: Any) -> Any:
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_i1_command_decomposes_uid_instance() -> None:
    inst = _instance(uid="d" * 32, alloc={"atk": 210})
    ctx = _decompose_ctx(inst)
    parsed = types.SimpleNamespace(error=None, args=["X剑"], qty=None)
    out = _run(cmd_decompose(parsed, ctx))
    assert "分解" in out and "无材料" not in out
    assert ctx["player"]["inventory"] == []                 # uid 实例被扣（UID 锚定）
    assert ctx["_added"] == [("a", 9), ("b", 5)]            # 材料返还
    assert ctx["player"]["currencies"]["essence"] == 101605  # 精粹入账
    assert "装备精粹" in out


def test_i2_disabled_falls_back_no_instance_removal() -> None:
    """未启用精粹 → 实例路径整段跳过；既有 item_id 路径行为不变、实例不被动。"""
    inst = _instance(uid="e" * 32)
    ctx = _decompose_ctx(inst, enabled=False)
    # 既有 item_id 路径需要 items 定义可分解（这里定义无 quality 章 → 标准版拒），
    # 关键是**实例不被扣、精粹不入账**。
    ctx["wallet"] = types.SimpleNamespace(
        decompose=lambda *a, **k: {"ok": False, "reason": "standard_not_decomposable",
                                   "message": "❌ 标准版不可分解"},
        decompose_rate=lambda _i: 0.65,
    )
    parsed = types.SimpleNamespace(error=None, args=["X剑"], qty=None)
    _run(cmd_decompose(parsed, ctx))
    assert len(ctx["player"]["inventory"]) == 1
    assert ctx["player"]["currencies"].get("essence", 0) == 0
    assert ctx["_added"] == []


# ===========================================================================
# J. 持久化 / 迁移 / 卸装
# ===========================================================================
def test_j1_item_roundtrip_preserves_temper() -> None:
    inst = _instance(alloc={"atk": 7, "hp": 3})
    d = asdict(inst)
    back = _item_from_dict(d)
    assert back.temper_alloc == {"atk": 7, "hp": 3}
    assert back.required_level == _LEVEL


def test_j2_backfill_idempotent_lossless() -> None:
    rows = [{"item_id": "old"}]
    out, n = backfill_instance_temper(rows)
    assert n == 2 and out[0]["temper_alloc"] == {} and out[0]["required_level"] == 0
    _, n2 = backfill_instance_temper(rows)
    assert n2 == 0
    keep = [{"item_id": "x", "temper_alloc": {"atk": 2}, "required_level": 9}]
    backfill_instance_temper(keep)
    assert keep[0]["temper_alloc"] == {"atk": 2} and keep[0]["required_level"] == 9
    # 非 list / 非 dict 行不触碰
    assert backfill_instance_temper(None)[1] == 0
    assert backfill_instance_temper([1, "x"])[1] == 0


def test_j3_unequip_preserves_temper_alloc() -> None:
    eng = EquipmentEngine()
    a = _instance(uid="f" * 32, alloc={"atk": 30})
    other = _instance(uid="g" * 32, item_id="sword2", name="Y剑", alloc={"hp": 1})
    player: Dict[str, Any] = {
        "inventory": [other, a],
        "equipment": {"weapon": EquipmentSlot(
            item_id="sword_x", name="X剑", slot_level=0, uid=a.uid)},
        "attributes": PlayerAttributes(),
    }
    res = eng.unequip(player, "weapon")
    assert res["ok"] is True
    back = [r for r in player["inventory"] if r.uid == a.uid][0]
    assert back.temper_alloc == {"atk": 30}      # 淬炼状态随实例（uid 锚定）走
    assert other.temper_alloc == {"hp": 1}


def test_j4_repository_read_drops_bad_temper_entries() -> None:
    back = _item_from_dict({"item_id": "x", "name": "x", "count": 1,
                            "quality": "normal", "bound": False,
                            "temper_alloc": {"atk": 3, "hp": 0, "mp": -1, "bogus": "z"}})
    assert back.temper_alloc == {"atk": 3}


# ===========================================================================
# K. 校验器
# ===========================================================================
class _Report:
    def __init__(self) -> None:
        self.errors: List[Any] = []
        self.warnings: List[Any] = []

    def _err(self, module: str, field: str, kind: str, **d: Any) -> None:
        self.errors.append((field, kind, dict(d)))

    def _warn(self, module: str, field: str, kind: str, **d: Any) -> None:
        self.warnings.append((field, kind, dict(d)))


def _enh(mods: Dict[str, Any]) -> Dict[str, Any]:
    base = {"temper": dict(_TEMPER)}
    base["temper"].update(mods)
    return {"enhance": {"temper": base["temper"]}}


def test_k1_enhance_temper_checks() -> None:
    rep = _Report()
    validate_enhance(_enh({"per_stat_cap_ratio": 1.5}), rep)
    assert any(k == "V9" for _f, k, _ in rep.errors)
    rep = _Report()
    validate_enhance(_enh({"allowed_stats": ["not_a_stat"]}), rep)
    assert any(k == "V10" for _f, k, _ in rep.errors)
    rep = _Report()
    validate_enhance(_enh({"cost_per_point": {"essence": 0}}), rep)
    assert any(k == "V11" for _f, k, _ in rep.errors)
    rep = _Report()
    validate_enhance(_enh({"cap_per_level": None, "total_cap": None,
                           "total_cap_by_level": {}}), rep)
    assert any(k == "V12" for _f, k, _ in rep.errors)
    rep = _Report()
    validate_enhance(_enh({"cost_growth": 2}), rep)
    assert any(k == "V13" for _f, k, _ in rep.errors)


def test_k2_enhance_temper_ratio_warn_and_disabled_skip() -> None:
    rep = _Report()
    validate_enhance(_enh({"per_stat_cap_ratio": 1.0}), rep)
    assert any(k == "V9" for _f, k, _ in rep.warnings)
    # disabled → 完全不校验
    rep = _Report()
    validate_enhance({"enhance": {"temper": {"enabled": False, "per_stat_cap_ratio": 9}}}, rep)
    assert rep.errors == []


def test_k3_settings_essence_rate_red_blocks() -> None:
    base = {"forge": {"essence_rate": {"enabled": True, "essence_currency": "essence"}},
            "currencies": [{"id": "coins"}]}
    rep = check_pack({"settings": base})
    got = [(e.kind, e.detail.get("rule")) for e in rep.errors
           if str(e.field).startswith("settings.forge.essence_rate")]
    assert ("R-4", "currency_ref_missing") in got
    # 登记后放行
    ok = check_pack({"settings": {"forge": {"essence_rate": {
        "enabled": True, "essence_currency": "essence"}},
        "currencies": [{"id": "coins"}, {"id": "essence"}]}})
    assert not [e for e in ok.errors
                if str(e.field).startswith("settings.forge.essence_rate")]
    # 非法枚举 / 数值 → R-1
    bad = check_pack({"settings": {"forge": {"essence_rate": {
        "enabled": True, "scope": "nope", "k1": -1,
        "essence_currency": "essence"}}, "currencies": [{"id": "essence"}]}})
    kinds = {e.detail.get("rule") for e in bad.errors
             if str(e.field).startswith("settings.forge.essence_rate")}
    assert "enum" in kinds and "range" in kinds
    # 缺段放行
    assert not [e for e in check_pack({"settings": {}}).errors
                if "essence_rate" in str(e.field)]


# ===========================================================================
# L. 编辑器元数据
# ===========================================================================
def test_l1_enhance_meta_temper_visible() -> None:
    fields = enhance_module_meta().fields
    assert "temper" in fields
    temper = fields["temper"]
    assert temper.label == "淬炼"
    for key in ("enabled", "cap_per_level", "per_stat_cap_ratio", "cost_per_point",
                "allowed_stats", "value_type", "reset_allowed"):
        assert key in temper.children, key
        assert temper.children[key].label, key
    assert temper.children["cost_per_point"].children["essence"].label


def test_l2_forge_meta_essence_rate_visible() -> None:
    children = forge_settings_meta().children
    assert "essence_rate" in children
    er = children["essence_rate"]
    assert er.label and er.help
    for key in ("enabled", "v_basis", "k1", "k2", "beta", "temper_refund",
                "refund_decay", "scope", "essence_currency"):
        assert key in er.children, key


def test_l3_default_labels_nonempty() -> None:
    cfg = normalize_temper_config(None)
    assert DEFAULT_TEMPER["enabled"] is False
    assert cfg["cost_per_point"]["essence"] == 1593
    assert DEFAULT_ESSENCE_RATE["beta"] == 1.2
