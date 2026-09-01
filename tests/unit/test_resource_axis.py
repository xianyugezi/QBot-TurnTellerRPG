"""M13 批8 路8B · 6c energy_gain/energy_cost 运行时测试（tests/unit/test_resource_axis.py）。

文件名：tests/unit/test_resource_axis.py
创建时间：2026-09-02
作者：Hermes 子agent-8B（M13 6c 资源轴实现组批8路8B：并发同仓，仅新建本文件 +
  qbot_rpg/core/resource_axis.py；不碰兄弟文件——8A 独占 stats.json 注册段
  schema 扩展，8C 独占 resource_state 快照段；若 8A 未落盘 stats 扩展，
  本路测试一律用内存 fixtures（ctx["stats"] 注入），引擎按字段口径防御读取）

测试目标：qbot_rpg.core.resource_axis（M2 energy_gain/energy_cost 运行时）：
  - 两型注册段读取（D-01：pools 判别）/ type 归一（D-01b）/ 防御归一
    （max 缺省 100、0=不限、max_per_pool 缺省 3、reset 缺省 battle）；
  - 两型统一读写：数值型单值 / 子池型池级（RS-6 池级原子粒度）/
    total_of 总量（D-04 展示键数据源）；
  - energy_gain 结算（TC-02/TC-08）：命中 +15 / 池独立 +1 / 封顶
    （95→100 不累计 / fire 3 封顶第 4 次不累计）/ 0 无操作（D-06）/
    负值钳 0（B-6）/ 未注册资源降级（RS-5）；
  - energy_cost 施放前检查（TC-03）：不足被拒不耗回合（资源不变）/
    any:n 总量门（D-02）/ 具名池扣减方案（B-5）/ 原子扣减不半扣；
  - 触发类 D-03（TC-06③）：不足不生效不耗不计上限 / 生效才耗 /
    applied 标志供触发计数；
  - 引擎注入模式（ResourceAxisEngine：构造器注入 stats/resource_state/
    audit + 技能级便捷入口）。

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §1.2 M2 字段级 schema（E1/E2 + K1~K6）；
  - §1.3 F-R1 回合结清（施放前门禁 / 成功结算封顶 / D-03）；
  - §0.3 ADR（D-01/D-01b/D-02/D-03/D-06）；
  - §1.4 RS-5/RS-6；§六 TC-02/TC-03/TC-06③/TC-08。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机；不 git commit；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.resource_axis import (
    ANY_KEY,
    DEFAULT_MAX,
    DEFAULT_MAX_PER_POOL,
    RESET_BATTLE,
    RESET_BATTLE_START,
    RESET_KEEP,
    RESOURCE_STATE_KEY,
    ResourceAxisEngine,
    add_value,
    apply_gain,
    axes_of,
    axis_of,
    check_cost,
    check_skill_cost,
    check_trigger_cost,
    cost_breakdown,
    gain_energy,
    gain_skill_energy,
    get_value,
    normalize_axis,
    pay_cost,
    pay_skill_cost,
    pay_trigger_cost,
    set_value,
    total_of,
    trigger_energy_cost,
)

# =====================================================================================
# 夹具：狂战士 rage（数值型） + 元素法师 element_energy（子池型），对齐 6c §1.1 示例
# =====================================================================================

RAGE_ID = "rage"
ELEMENT_ID = "element_energy"


def _rage() -> Dict[str, Any]:
    """数值型注册段（狂战士怒气，§1.1 示例：max=100 reset=battle display=status_line）。"""
    return {
        "name": "怒气",
        "type": "resource",
        "icon": "💢",
        "base": 0,
        "max": 100,
        "reset": "battle",
        "display": "status_line",
    }


def _element() -> Dict[str, Any]:
    """子池型注册段（元素法师元素能量，§1.1 示例：pools 三池 max_per_pool=3）。"""
    return {
        "name": "元素能量",
        "type": "resource_custom",
        "base": 0,
        "max_per_pool": 3,
        "pools": ["fire", "water", "wind"],
        "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
        "display": "status_line",
    }


def _stats() -> Dict[str, Any]:
    """注册表 fixture（map 形态，键 = 资源 ID，对齐 field_meta entry_type=map）。"""
    return {RAGE_ID: _rage(), ELEMENT_ID: _element()}


def _ctx(
    *,
    stats: Optional[Mapping[str, Any]] = None,
    resource_state: Optional[Dict[str, Any]] = None,
) -> MutableMapping[str, Any]:
    """构造测试 ctx（注册表 + 战斗资源槽段；默认全空，槽惰性建段）。"""
    ctx: MutableMapping[str, Any] = {"stats": dict(stats) if stats is not None else _stats()}
    if resource_state is not None:
        ctx[RESOURCE_STATE_KEY] = resource_state
    return ctx


def _seed_rage(ctx: MutableMapping[str, Any], value: int, side: str = "player") -> None:
    """预置数值型怒气当前值（战斗中途语义）。"""
    seg = ctx.setdefault(RESOURCE_STATE_KEY, {}).setdefault(side, {})
    seg[RAGE_ID] = value


def _seed_pool(
    ctx: MutableMapping[str, Any],
    axis_id: str,
    values: Mapping[str, int],
    side: str = "player",
) -> None:
    """预置子池型池级当前值（fire/water/wind 部分或全量）。"""
    seg = ctx.setdefault(RESOURCE_STATE_KEY, {}).setdefault(side, {})
    node = seg.setdefault(axis_id, {})
    for k, v in values.items():
        node[k] = v


def _skill(
    *,
    energy_gain: Optional[Mapping[str, Any]] = None,
    energy_cost: Optional[Mapping[str, Any]] = None,
    mp_cost: int = 0,
) -> Dict[str, Any]:
    """技能 def fixture（energy_gain/energy_cost 段，契约形态 {axis: {key: amount}}）。"""
    skill: Dict[str, Any] = {"id": "test_skill", "name": "测试技", "mp_cost": mp_cost}
    if energy_gain is not None:
        skill["energy_gain"] = energy_gain
    if energy_cost is not None:
        skill["energy_cost"] = energy_cost
    return skill


# =====================================================================================
# 一、注册段读取与两型判别（D-01/D-01b/防御归一）
# =====================================================================================


def test_axis_of_numeric_registration():
    """D-01：无 pools 注册段判别为数值型；字段读取正确（TC-01 基线）。"""
    ctx = _ctx()
    axis = axis_of(ctx, RAGE_ID)
    assert axis is not None
    assert axis.is_pooled is False
    assert axis.name == "怒气"
    assert axis.type == "resource"
    assert axis.max == 100
    assert axis.reset == "battle"
    assert axis.display == "status_line"
    assert axis.base == 0
    assert axis.pools == ()


def test_axis_of_pooled_registration():
    """D-01：pools 非空判别为子池型；resource_custom 归一 resource（D-01b）。"""
    ctx = _ctx()
    axis = axis_of(ctx, ELEMENT_ID)
    assert axis is not None
    assert axis.is_pooled is True
    assert axis.type == "resource"  # D-01b 归一
    assert axis.pools == ("fire", "water", "wind")
    assert axis.max_per_pool == 3
    assert axis.pool_icons == {"fire": "🔥", "water": "💧", "wind": "🌪"}
    assert axis.cap_of("fire") == 3
    assert axis.cap_of("water") == 3


def test_axis_of_missing_returns_none():
    """RS-5：未注册资源 → axis_of None（降级不报错不悬空）。"""
    ctx = _ctx()
    assert axis_of(ctx, "heat") is None
    assert axis_of(ctx, "") is None
    assert axis_of(ctx, "rage") is not None


def test_normalize_axis_defensive_defaults():
    """防御归一：max 缺省 100 / max=0 不限 / reset 缺省 battle / max_per_pool 缺省 3。"""
    axis = normalize_axis({"name": "无上限轴"})
    assert axis.max == DEFAULT_MAX
    assert axis.reset == RESET_BATTLE
    assert axis.is_pooled is False
    axis0 = normalize_axis({"name": "零上限轴", "max": 0})
    assert axis0.max == 0  # 0 = 不限（B-7）
    pooled = normalize_axis({"name": "池轴", "pools": ["fire", "water"]})
    assert pooled.is_pooled is True
    assert pooled.max_per_pool == DEFAULT_MAX_PER_POOL  # 缺省 3
    pooled2 = normalize_axis({"name": "池轴2", "pools": ["fire"], "max_per_pool": 5})
    assert pooled2.max_per_pool == 5
    assert normalize_axis({"name": "保留", "reset": "keep"}).reset == RESET_KEEP
    assert normalize_axis({"name": "开战", "reset": "battle_start"}).reset == RESET_BATTLE_START
    assert normalize_axis({"name": "非法", "reset": "daily"}).reset == RESET_BATTLE  # 枚举外兜底


def test_axes_of_both_forms():
    """axes_of 全量读取：map 形态（stats）与 list 形态（resource_axes）兼容（B-2）。"""
    ctx = _ctx()
    axes = axes_of(ctx)
    assert set(axes) == {RAGE_ID, ELEMENT_ID}
    ctx2: MutableMapping[str, Any] = {
        "resource_axes": [
            {"id": "heat", "name": "热量", "max": 50},
            {"id": "focus", "name": "专注资源", "max": 30},
        ]
    }
    axes2 = axes_of(ctx2)
    assert set(axes2) == {"heat", "focus"}
    assert axes2["heat"].max == 50


# =====================================================================================
# 二、两型统一读写（数值型单值 / 子池型池级）
# =====================================================================================


def test_get_set_numeric():
    """数值型统一读写：set_value 单值 / get_value 读取 / 负值钳 0。"""
    ctx = _ctx()
    assert get_value(ctx, RAGE_ID) == 0  # 缺省回落 base=0
    r = set_value(ctx, RAGE_ID, 72)
    assert r["ok"] is True and r["value"] == 72
    assert get_value(ctx, RAGE_ID) == 72
    assert set_value(ctx, RAGE_ID, -5)["value"] == 0  # 钳非负
    assert get_value(ctx, RAGE_ID, key="fire") == 0  # 数值型无池键


def test_get_set_pooled():
    """子池型池级读写（RS-6 池级原子粒度）：set_value 池键 / get_value 池值。"""
    ctx = _ctx()
    assert get_value(ctx, ELEMENT_ID) == 0  # 池级轴本身无单值
    assert get_value(ctx, ELEMENT_ID, key="fire") == 0  # 缺省回落 base=0
    r = set_value(ctx, ELEMENT_ID, 2, key="fire")
    assert r["ok"] is True and r["value"] == 2
    assert get_value(ctx, ELEMENT_ID, key="fire") == 2
    assert get_value(ctx, ELEMENT_ID, key="water") == 0  # 池独立
    assert set_value(ctx, ELEMENT_ID, 9, key="unknown")["ok"] is False  # 未知池拒绝
    r2 = set_value(ctx, ELEMENT_ID, 1)  # key=None → 全池置 base
    assert r2["ok"] is True
    assert get_value(ctx, ELEMENT_ID, key="fire") == 0
    assert get_value(ctx, ELEMENT_ID, key="water") == 0
    assert get_value(ctx, ELEMENT_ID, key="wind") == 0


def test_add_value_cap_numeric():
    """数值型封顶（TC-02③）：95 → +15 封顶 100 不累计；capped 标志。"""
    ctx = _ctx()
    _seed_rage(ctx, 95)
    r = add_value(ctx, RAGE_ID, 15)
    assert r["ok"] is True
    assert r["before"] == 95 and r["after"] == 100 and r["capped"] is True
    assert get_value(ctx, RAGE_ID) == 100


def test_add_value_cap_pooled():
    """子池型每池封顶（TC-08②）：fire=2 → +1 → 3；再 +1 封顶 3 不累计。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 2, "water": 1})
    r = add_value(ctx, ELEMENT_ID, 1, key="fire")
    assert r["after"] == 3 and r["capped"] is False
    r2 = add_value(ctx, ELEMENT_ID, 1, key="fire")
    assert r2["before"] == 3 and r2["after"] == 3 and r2["capped"] is True
    assert get_value(ctx, ELEMENT_ID, key="fire") == 3
    assert get_value(ctx, ELEMENT_ID, key="water") == 1  # 池独立（TC-08①）


def test_total_of_pooled():
    """子池型总量（D-04 展示键数据源）：fire2+water1+wind0 = 3；数值型 = 单值。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 2, "water": 1, "wind": 0})
    assert total_of(ctx, ELEMENT_ID) == 3
    _seed_rage(ctx, 72)
    assert total_of(ctx, RAGE_ID) == 72


# =====================================================================================
# 三、energy_gain 结算（M2 E1 / TC-02 / TC-08）
# =====================================================================================


def test_gain_energy_hit_increases():
    """TC-02①：怒击 energy_gain {rage:15} 命中结算 → 怒气 +15。"""
    ctx = _ctx()
    _seed_rage(ctx, 0)
    r = gain_energy(ctx, RAGE_ID, {"rage": 15})
    assert r["ok"] is True
    assert r["gained"] == [{"key": "rage", "amount": 15, "before": 0, "after": 15,
                            "capped": False}]
    assert get_value(ctx, RAGE_ID) == 15
    assert r["events"][0]["type"] == "energy_gain"
    assert r["events"][0]["source"] == "skill"


def test_gain_energy_pooled_independent():
    """TC-08①：火球术 → 仅 fire +1，water/wind 不变（池独立增减）。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 0, "water": 0, "wind": 0})
    r = gain_energy(ctx, ELEMENT_ID, {"fire": 1})
    assert r["ok"] is True
    assert get_value(ctx, ELEMENT_ID, key="fire") == 1
    assert get_value(ctx, ELEMENT_ID, key="water") == 0
    assert get_value(ctx, ELEMENT_ID, key="wind") == 0


def test_gain_energy_zero_and_negative():
    """D-06/B-6：值 0 无操作（不写事件）；负值钳 0 不写负值。"""
    ctx = _ctx()
    _seed_rage(ctx, 10)
    r0 = gain_energy(ctx, RAGE_ID, {"rage": 0})
    assert r0["ok"] is True and r0["gained"] == [] and r0["events"] == []
    assert get_value(ctx, RAGE_ID) == 10  # 不变
    rn = gain_energy(ctx, RAGE_ID, {"rage": -5})
    assert rn["gained"] == []  # 负值钳 0 → 无操作
    assert get_value(ctx, RAGE_ID) == 10


def test_gain_energy_unregistered_axis():
    """RS-5：未注册资源 gain → 降级跳过不报错（ok=True 空 gained）。"""
    ctx = _ctx()
    r = gain_energy(ctx, "heat", {"heat": 10})
    assert r["ok"] is True and r["gained"] == []


def test_gain_energy_multi_axis():
    """K6：多资源同时增减 {rage:10, heat:5}（heat 未注册降级跳过，rage 生效）。"""
    ctx = _ctx()
    _seed_rage(ctx, 0)
    r = apply_gain(ctx, {RAGE_ID: {"rage": 10}, "heat": {"heat": 5}})
    assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 10
    assert len(r["events"]) == 1  # 仅 rage 事件（heat 降级无事件）


def test_gain_skill_energy_entry():
    """技能级入口：energy_gain 段（契约形态 {axis: {key: amount}}）命中后追加。"""
    ctx = _ctx()
    skill = _skill(energy_gain={RAGE_ID: {"rage": 15}})
    r = gain_skill_energy(ctx, skill)
    assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 15


def test_gain_skill_energy_no_segment():
    """技能无 energy_gain 段 → 无操作（ok=True 空）。"""
    ctx = _ctx()
    r = gain_skill_energy(ctx, _skill())
    assert r["ok"] is True and r["gained"] == [] and r["events"] == []


# =====================================================================================
# 四、energy_cost 施放前检查（M2 E2 / TC-03 / D-02）
# =====================================================================================


def test_check_cost_numeric_sufficient():
    """数值型消耗足够：怒气 80 施放狂暴（cost {rage:100}）→ 检查通过（80<100 时见下例）。"""
    ctx = _ctx()
    _seed_rage(ctx, 100)
    r = check_cost(ctx, RAGE_ID, {"rage": 100})
    assert r["ok"] is True and r["missing"] == []


def test_check_cost_numeric_insufficient():
    """TC-03①：怒气 80 施放狂暴（cost {rage:100}）→ 被拒不耗回合（资源不变）。"""
    ctx = _ctx()
    _seed_rage(ctx, 80)
    r = check_cost(ctx, RAGE_ID, {"rage": 100})
    assert r["ok"] is False
    assert r["reason"] == "energy_insufficient"
    assert r["missing"] == [{"axis": RAGE_ID, "key": "rage", "need": 100, "have": 80}]
    assert get_value(ctx, RAGE_ID) == 80  # 不变（不耗回合语义）


def test_check_cost_empty_and_zero():
    """空 cost / 0 值键 → 无操作放行（D-06）。"""
    ctx = _ctx()
    _seed_rage(ctx, 0)
    assert check_cost(ctx, RAGE_ID, {})["ok"] is True
    assert check_cost(ctx, RAGE_ID, {"rage": 0})["ok"] is True


def test_check_cost_any_total_gate():
    """D-02 总量门：element_energy fire1+water1 = 2 → any:2 通过；fire1 → 不足。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 1, "water": 1})
    r = check_cost(ctx, ELEMENT_ID, {ANY_KEY: 2})
    assert r["ok"] is True
    ctx2 = _ctx()
    _seed_pool(ctx2, ELEMENT_ID, {"fire": 1})
    r2 = check_cost(ctx2, ELEMENT_ID, {ANY_KEY: 2})
    assert r2["ok"] is False
    assert r2["missing"] == [{"axis": ELEMENT_ID, "key": "any", "need": 2, "have": 1}]


def test_check_cost_pooled_named():
    """子池型具名键（K2）：{fire:2} 需 fire ≥ 2；fire1 → 不足；water 不受影响。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 1, "water": 2})
    r = check_cost(ctx, ELEMENT_ID, {"fire": 2})
    assert r["ok"] is False
    r2 = check_cost(ctx, ELEMENT_ID, {"water": 2})
    assert r2["ok"] is True


def test_cost_breakdown_named_and_any():
    """B-5 扣减方案：any 总量门按池序（pools 注册顺序）从富余池均摊，确定性零随机。

    - {any:2} with fire2/water2/wind0 → fire 2（池序优先）；
    - {any:3} with fire1/water2 → fire 1 + water 2（跨池均摊）；
    - {any:5} with fire2/water2 → None（总量不足 → 不半扣）；
    - 具名键 {fire:1} → 该池扣 1（具名池显式锁定）；
    - 混合 {fire:1, any:2}（K3 互斥，运行时 B-3 any 优先）→ 按 any 处理。
    """
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 2, "water": 2, "wind": 0})
    plan = cost_breakdown(ctx, ELEMENT_ID, {ANY_KEY: 2})
    assert plan is not None
    assert plan == [{"pool": "fire", "amount": 2}]  # 池序优先
    ctx3 = _ctx()
    _seed_pool(ctx3, ELEMENT_ID, {"fire": 1, "water": 2})
    plan3 = cost_breakdown(ctx3, ELEMENT_ID, {ANY_KEY: 3})
    assert plan3 == [{"pool": "fire", "amount": 1}, {"pool": "water", "amount": 2}]
    ctx4 = _ctx()
    _seed_pool(ctx4, ELEMENT_ID, {"fire": 2, "water": 2})
    assert cost_breakdown(ctx4, ELEMENT_ID, {ANY_KEY: 5}) is None  # 总量不足
    ctx5 = _ctx()
    _seed_pool(ctx5, ELEMENT_ID, {"fire": 2, "water": 2})
    assert cost_breakdown(ctx5, ELEMENT_ID, {"fire": 1}) == [{"pool": "fire", "amount": 1}]
    ctx6 = _ctx()
    _seed_pool(ctx6, ELEMENT_ID, {"fire": 2, "water": 2, "wind": 0})
    mixed = cost_breakdown(ctx6, ELEMENT_ID, {"fire": 1, ANY_KEY: 2})
    assert mixed == [{"pool": "fire", "amount": 2}]  # B-3：any 优先，具名键忽略


def test_pay_cost_numeric_atomic():
    """原子扣减：狂暴成功 → 怒气 -100（100→0）；不足 → 拒绝不扣（不半扣）。"""
    ctx = _ctx()
    _seed_rage(ctx, 100)
    r = pay_cost(ctx, RAGE_ID, {"rage": 100})
    assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 0
    assert r["events"][0]["type"] == "energy_cost"
    ctx2 = _ctx()
    _seed_rage(ctx2, 80)
    r2 = pay_cost(ctx2, RAGE_ID, {"rage": 100})
    assert r2["ok"] is False and r2["reason"] == "insufficient"
    assert get_value(ctx2, RAGE_ID) == 80  # 不半扣


def test_check_skill_cost_insufficient():
    """技能级施放前检查：energy_cost 段不足 → ok=False（接线方可走 rejected 管道）。"""
    ctx = _ctx()
    _seed_rage(ctx, 80)
    skill = _skill(energy_cost={RAGE_ID: {"rage": 100}})
    r = check_skill_cost(ctx, skill)
    assert r["ok"] is False
    assert r["axes"] == [RAGE_ID]
    assert get_value(ctx, RAGE_ID) == 80  # 不变


def test_pay_skill_cost_after_check():
    """技能级扣减：先 check 后 pay（原子）；MP 与能量互补并存（K4，mp 侧归战斗层）。"""
    ctx = _ctx()
    _seed_rage(ctx, 100)
    skill = _skill(energy_cost={RAGE_ID: {"rage": 100}}, mp_cost=16)
    assert check_skill_cost(ctx, skill)["ok"] is True
    r = pay_skill_cost(ctx, skill)
    assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 0


# =====================================================================================
# 五、触发类 energy_cost（D-03 / TC-06③）
# =====================================================================================


def test_trigger_energy_cost_sufficient_applies():
    """D-03 生效路径：能量足 → 受击屏障生效、能量 -1、applied=True（计入触发上限）。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 1})
    skill = _skill(energy_cost={ELEMENT_ID: {ANY_KEY: 1}})
    r = trigger_energy_cost(ctx, skill["energy_cost"])
    assert r["ok"] is True and r["applied"] is True
    assert total_of(ctx, ELEMENT_ID) == 0  # 能量 -1


def test_trigger_energy_cost_insufficient_not_applied():
    """TC-06③ / D-03：能量不足 → 触发不生效、不耗能量、不计上限（applied=False）。"""
    ctx = _ctx()
    _seed_pool(ctx, ELEMENT_ID, {"fire": 0})
    skill = _skill(energy_cost={ELEMENT_ID: {ANY_KEY: 1}})
    r = trigger_energy_cost(ctx, skill["energy_cost"])
    assert r["ok"] is False and r["applied"] is False
    assert r["missing"] != []
    assert total_of(ctx, ELEMENT_ID) == 0  # 不耗能量
    # 调用方按 applied=False 不计触发上限（断言语义：不足路径绝不 applied=True）


def test_check_trigger_cost_multi_axis_partial():
    """触发类多资源：任一轴不足 → 整体不生效（D-03 原子判定）。"""
    ctx = _ctx()
    _seed_rage(ctx, 100)
    _seed_pool(ctx, ELEMENT_ID, {"fire": 0})
    cost = {RAGE_ID: {"rage": 10}, ELEMENT_ID: {ANY_KEY: 1}}
    r = check_trigger_cost(ctx, cost)
    assert r["ok"] is False
    assert len(r["missing"]) == 1  # 仅 element 不足


def test_pay_trigger_never_costs_when_insufficient():
    """B-4：不足路径 pay_trigger_cost 绝不消耗能量（拒绝且资源不变）。"""
    ctx = _ctx()
    _seed_rage(ctx, 5)
    cost = {RAGE_ID: {"rage": 10}}
    r = pay_trigger_cost(ctx, cost)
    assert r["ok"] is False and r["reason"] == "insufficient"
    assert get_value(ctx, RAGE_ID) == 5  # 不耗


# =====================================================================================
# 六、引擎注入模式（ResourceAxisEngine）
# =====================================================================================


def test_engine_injected_stats_and_state():
    """引擎构造器注入：stats/resource_state 挂 ctx（缺省键不覆盖显式注入，幂等）。"""
    rs: Dict[str, Any] = {"player": {RAGE_ID: 50}}
    stats = _stats()
    engine = ResourceAxisEngine(stats=stats, resource_state=rs)
    ctx: MutableMapping[str, Any] = {}
    engine.check(ctx, _skill(energy_cost={RAGE_ID: {"rage": 30}}))
    assert ctx["stats"] is stats
    assert ctx[RESOURCE_STATE_KEY] is rs
    assert get_value(ctx, RAGE_ID) == 50


def test_engine_gain_and_pay_skill_flow():
    """引擎技能流程：怒击 gain +15 → 狂暴 check 不足被拒（资源不变）→ 满后 pay -100。"""
    ctx = _ctx()
    engine = ResourceAxisEngine()
    r_gain = engine.gain(ctx, _skill(energy_gain={RAGE_ID: {"rage": 15}}))
    assert r_gain["ok"] is True and get_value(ctx, RAGE_ID) == 15
    berserk = _skill(energy_cost={RAGE_ID: {"rage": 100}})
    assert engine.check(ctx, berserk)["ok"] is False
    assert get_value(ctx, RAGE_ID) == 15  # 被拒不耗
    _seed_rage(ctx, 100)
    r_pay = engine.pay(ctx, berserk)
    assert r_pay["ok"] is True and get_value(ctx, RAGE_ID) == 0


def test_engine_trigger_flow_and_audit():
    """引擎触发流程：D-03 applied 标志 + audit 观察口记录。"""
    logs: List[str] = []
    engine = ResourceAxisEngine(audit=logs.append)
    ctx = _ctx()
    barrier = _skill(energy_cost={ELEMENT_ID: {ANY_KEY: 1}})
    r1 = engine.trigger_energy(ctx, barrier)
    assert r1["ok"] is False and r1["applied"] is False  # 无能量 → 不生效
    _seed_pool(ctx, ELEMENT_ID, {"fire": 1})
    r2 = engine.trigger_energy(ctx, barrier)
    assert r2["ok"] is True and r2["applied"] is True
    assert total_of(ctx, ELEMENT_ID) == 0
    assert any("applied=True" in line or "applied=True" in line for line in logs)
    assert len(logs) >= 2


def test_engine_axis_level_proc_gain():
    """轴级 proc 增减（§1.3 proc 时点）：怒意 on_turn_start +6（引擎 gain_axis）。"""
    ctx = _ctx()
    engine = ResourceAxisEngine()
    r = engine.gain_axis(ctx, RAGE_ID, {"rage": 6}, source="proc")
    assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 6
    assert r["events"][0]["source"] == "proc"


def test_engine_pay_axis_insufficient():
    """轴级扣减不足 → 拒绝不半扣（引擎 pay_axis）。"""
    ctx = _ctx()
    _seed_rage(ctx, 5)
    engine = ResourceAxisEngine()
    r = engine.pay_axis(ctx, RAGE_ID, {"rage": 10})
    assert r["ok"] is False
    assert get_value(ctx, RAGE_ID) == 5
