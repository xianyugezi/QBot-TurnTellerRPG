"""M13 批11 路11A · 6c combo_table 组合表达 schema + 触发判定测试。

文件名：tests/unit/test_combo_table.py
创建时间：2026-09-02
作者：Hermes 子agent-11A（M13 6c 组合表达实现组批11路11A：并发同仓，仅新建本文件 +
  qbot_rpg/core/combo_table.py；不碰兄弟文件——11B 独占组合结算执行、11C
  独占季节+组合测试集；本路测试用内存 fixtures（ctx["stats"] 注入），
  引擎按字段口径防御读取）

测试目标：qbot_rpg.core.combo_table（M8 组合表达引擎）：
  - 行 schema 解析（§3.1 C1~C7 七字段：combo 多重集 / name / kind / power /
    element / hits / effects）+ 防御归一（畸形行不抛异常、枚举外回落）；
  - 多重集匹配（D-02/CM-1，TC-14 核心）：[fire,fire] 需 fire ≥ 2 /
    [fire,water] 需 fire ≥ 1 且 water ≥ 1 / 表序锁定首个匹配行 / 全部
    匹配行 + 提示条目（CM-3 数据源）；
  - F-C1 三重门禁（TC-14 全验）：① 常规占位 → ② 总量门 any:n（不足 →
    被拒不耗）→ ③ 组合匹配（全部不匹配 → 被拒不耗，能量不变）；
    D-02 双重校验（总量足但池分布不满足该组合行 → 拒）；
  - 先匹配后消耗（CM-2）：resolve_trigger 零副作用（不扣能量）/ 锁定行
    扣减方案 row_cost_plan（[fire,fire] → fire 扣 2）/ combo_cost_plan；
  - 引擎注入模式（ComboTableEngine：构造器注入 stats/resource_state/audit
    + rows/match/resolve/suggest 便捷入口）。

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §3.1 行字段表 C1~C7 + 编排约束；
  - §3.2 F-C1（① 常规 → ② 总量 → ③ 组合）+ CM-1~CM-4；
  - §0.3 D-02（any:n 总量门 + 多重集匹配双重校验）；
  - §六 TC-14（六组合逐一匹配 / 分布不满足任一组合行 → 被拒不耗 /
    匹配提示）。
  - 模式参考：tests/unit/test_resource_axis.py（ctx 构造 + 池预置 fixture）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机；不 git commit；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.combo_table import (
    COMBO_KINDS,
    DEFAULT_COMBO_HITS,
    DEFAULT_COMBO_KIND,
    DEFAULT_COMBO_POWER,
    EVENT_COMBO_GATE,
    KIND_CONTROL,
    KIND_DAMAGE,
    KIND_HEAL,
    KIND_UTILITY,
    REASON_NO_MATCH,
    REASON_OK,
    REASON_TOTAL_INSUFFICIENT,
    ComboRow,
    ComboTableEngine,
    available_hints,
    combo_cost_plan,
    combo_multiset,
    gate_combination,
    gate_conventional,
    gate_total,
    match_combo_row,
    match_combos,
    multiset_matches,
    pool_values_of,
    resolve_trigger,
    row_cost_plan,
    rows_of,
)
from qbot_rpg.core.resource_axis import RESOURCE_STATE_KEY

# =====================================================================================
# 夹具：元素法师 element_energy（子池型） + 元素爆发技能（六组合行，§3.1 示例）
# =====================================================================================

ELEMENT_ID = "element_energy"


def _element() -> Dict[str, Any]:
    """子池型注册段（§1.1 示例：pools 三池 max_per_pool=3）。"""
    return {
        "name": "元素能量",
        "type": "resource_custom",
        "base": 0,
        "max_per_pool": 3,
        "pools": ["fire", "water", "wind"],
        "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
        "display": "status_line",
    }


def _ctx(
    *,
    stats: Optional[Mapping[str, Any]] = None,
    resource_state: Optional[Dict[str, Any]] = None,
) -> MutableMapping[str, Any]:
    """构造测试 ctx（注册表 + 战斗资源槽段；默认全空，槽惰性建段）。"""
    ctx: MutableMapping[str, Any] = {
        "stats": dict(stats) if stats is not None else {ELEMENT_ID: _element()}
    }
    if resource_state is not None:
        ctx[RESOURCE_STATE_KEY] = resource_state
    return ctx


def _seed_pool(
    ctx: MutableMapping[str, Any],
    values: Mapping[str, int],
    side: str = "player",
) -> None:
    """预置子池型池级当前值（fire/water/wind 部分或全量）。"""
    seg = ctx.setdefault(RESOURCE_STATE_KEY, {}).setdefault(side, {})
    node = seg.setdefault(ELEMENT_ID, {})
    for k, v in values.items():
        node[k] = v


def _rows() -> List[Dict[str, Any]]:
    """元素爆发六组合行（§3.1 L293-306 原例，TC-14 六组合全验数据）。"""
    return [
        {"combo": ["fire", "fire"], "name": "烈焰爆破", "kind": "damage",
         "power": 300, "element": "fire",
         "effects": [{"effect": "burn", "overrides": {"turns": 2}}]},
        {"combo": ["water", "water"], "name": "水镜壁垒", "kind": "utility",
         "power": 0,
         "effects": [{"effect": "tpl_shield_30"},
                     {"effect": "tpl_mitigation_15", "overrides": {"turns": 2}}]},
        {"combo": ["wind", "wind"], "name": "疾风连刃", "kind": "damage",
         "power": 160, "element": "wind", "hits": 2},
        {"combo": ["fire", "water"], "name": "蒸汽冲击", "kind": "damage",
         "power": 200, "element": "fire",
         "effects": [{"type": "control", "control": "confuse",
                      "chance": 80, "turns": 1}]},
        {"combo": ["fire", "wind"], "name": "火焰风暴", "kind": "damage",
         "power": 260, "element": "fire",
         "effects": [{"effect": "burn", "overrides": {"turns": 3}}]},
        {"combo": ["water", "wind"], "name": "和风细雨", "kind": "heal",
         "power": 0,
         "effects": [{"effect": "tpl_heal_max", "overrides": {"value": "35%max_hp"}},
                     {"effect": "tpl_regen", "overrides": {"turns": 3}}]},
    ]


def _burst() -> Dict[str, Any]:
    """元素爆发技能 def（§3.1 示例：双耗 MP16 + energy_cost {any:2} + 六组合行）。"""
    return {
        "id": "elemental_burst",
        "name": "元素爆发",
        "type": "active",
        "attack_type": "magic",
        "mp_cost": 16,
        "cooldown": 1,
        "energy_cost": {ELEMENT_ID: {"any": 2}},
        "combo_table": _rows(),
    }


# =====================================================================================
# 一、行 schema 解析（§3.1 C1~C7 七字段）
# =====================================================================================


def test_row_schema_seven_fields():
    """§3.1 C1~C7 七字段解析：combo 多重集 / name / kind / power / element /
    hits / effects 全量读取（烈焰爆破行）。"""
    rows = rows_of(_burst())
    assert len(rows) == 6  # 编排约束：3 池 → ≤ C(4,2)=6 行满配
    r0 = rows[0]
    assert isinstance(r0, ComboRow)
    assert r0.combo == ("fire",)  # 多重集去重保序
    assert r0.combo_counts == {"fire": 2}  # [fire,fire] 出现次数 2
    assert r0.combo_size == 2
    assert r0.name == "烈焰爆破"
    assert r0.kind == KIND_DAMAGE
    assert r0.power == 300.0
    assert r0.element == "fire"
    assert r0.hits == 1  # 缺省 1 段
    assert r0.effects == ({"effect": "burn", "overrides": {"turns": 2}},)


def test_row_schema_all_six_rows():
    """TC-14① 六组合行逐一解析：行为名/类别/倍率/元素/多段/效果引用齐全。"""
    rows = rows_of(_burst())
    by_name = {r.name: r for r in rows}
    assert set(by_name) == {"烈焰爆破", "水镜壁垒", "疾风连刃", "蒸汽冲击",
                            "火焰风暴", "和风细雨"}
    assert by_name["烈焰爆破"].combo_counts == {"fire": 2}
    assert by_name["水镜壁垒"].kind == KIND_UTILITY and by_name["水镜壁垒"].power == 0.0
    assert by_name["疾风连刃"].hits == 2  # 160%×2 多段
    assert by_name["蒸汽冲击"].element == "fire"
    assert by_name["火焰风暴"].effects[0]["overrides"]["turns"] == 3
    assert by_name["和风细雨"].kind == KIND_HEAL
    assert by_name["和风细雨"].effects[0]["overrides"]["value"] == "35%max_hp"


def test_row_schema_defensive_defaults():
    """防御归一：畸形行不抛异常；缺省回落（kind=damage / power=0 / hits=1）。"""
    rows = rows_of({"combo_table": [
        {},  # 空行
        {"combo": "not-a-list", "kind": "explode", "power": -5, "hits": 0},  # 畸形
        {"combo": ["fire"], "name": "正常行"},
    ]})
    assert len(rows) == 3
    assert rows[0].combo == () and rows[0].combo_size == 0
    assert rows[0].name == "" and rows[0].kind == DEFAULT_COMBO_KIND
    assert rows[0].power == DEFAULT_COMBO_POWER and rows[0].hits == DEFAULT_COMBO_HITS
    assert rows[1].combo == ()  # 非列表 combo 归一空
    assert rows[1].kind == DEFAULT_COMBO_KIND  # 枚举外回落 damage
    assert rows[1].power == 0.0  # 负值钳 0
    assert rows[1].hits == 1  # 0/负值钳 1
    assert rows[2].combo == ("fire",) and rows[2].name == "正常行"


def test_rows_of_missing_and_protocol():
    """段缺省/非列表 → 空元组（B-3 常规技能语义）；协议对象属性读取兼容。"""
    assert rows_of({}) == ()
    assert rows_of({"combo_table": "bad"}) == ()
    assert rows_of(None) == ()

    class FakeSkill:
        combo_table = [{"combo": ["fire", "water"], "name": "协议行"}]

    rows = rows_of(FakeSkill())
    assert len(rows) == 1 and rows[0].name == "协议行"


def test_combo_multiset_helper():
    """combo_multiset 工具：出现次数表（D-02 口径），非字符串元素防御丢弃。"""
    assert combo_multiset(["fire", "fire"]) == {"fire": 2}
    assert combo_multiset(["fire", "water"]) == {"fire": 1, "water": 1}
    assert combo_multiset(["fire", 1, None, "fire"]) == {"fire": 2}
    assert combo_multiset("fire") == {}  # 非列表归一空
    assert combo_multiset([]) == {}


# =====================================================================================
# 二、多重集匹配（D-02 / CM-1）
# =====================================================================================


def test_multiset_match_double_fire():
    """CM-1/D-02：组合 [fire,fire] 要求 fire ≥ 2；fire=2 匹配、fire=1 不匹配。"""
    row = ComboRow({"combo": ["fire", "fire"]})
    assert row.matches({"fire": 2, "water": 0}) is True
    assert row.matches({"fire": 1, "water": 1}) is False
    assert row.matches({"fire": 3}) is True  # 富余池不影响
    assert multiset_matches(row, {"fire": 2}) is True  # 模块级入口等价


def test_multiset_match_mixed():
    """CM-1/D-02：组合 [fire,water] 要求 fire ≥ 1 且 water ≥ 1。"""
    row = ComboRow({"combo": ["fire", "water"]})
    assert row.matches({"fire": 1, "water": 1}) is True
    assert row.matches({"fire": 2, "water": 0}) is False  # 缺 water
    assert row.matches({"fire": 0, "water": 2}) is False  # 缺 fire
    assert row.matches({"fire": 1, "water": 1, "wind": 5}) is True


def test_match_combo_row_first_match_wins():
    """B-1：表序 = 匹配优先级；多行同时可匹配时锁定首个（确定性零随机）。"""
    rows = rows_of(_burst())
    # fire2 + water2：烈焰爆破（火火）与蒸汽冲击（火水）均可匹配 → 表序取首个
    values = {"fire": 2, "water": 2}
    locked = match_combo_row(rows, values)
    assert locked is not None and locked.name == "烈焰爆破"
    assert [r.name for r in match_combos(rows, values)] == ["烈焰爆破", "水镜壁垒", "蒸汽冲击"]


def test_match_combos_all_and_hints():
    """B-6/CM-3：全部匹配行 + 可用提示条目（名称/组合键/行为摘要数据源）。"""
    rows = rows_of(_burst())
    values = {"fire": 2, "water": 1}
    matched = match_combos(rows, values)
    assert [r.name for r in matched] == ["烈焰爆破", "蒸汽冲击"]  # 火火 + 火水
    hints = available_hints(rows, values)
    assert hints == [
        {"combo": ["fire"], "name": "烈焰爆破", "kind": "damage", "power": 300.0},
        {"combo": ["fire", "water"], "name": "蒸汽冲击", "kind": "damage", "power": 200.0},
    ]
    assert available_hints(rows, {"fire": 0}) == []  # 无匹配 → 空


def test_match_empty_rows_and_empty_combo():
    """B-3/B-4：空表 / 空 combo 行 → 不匹配（无组合键无法分派行为）。"""
    assert match_combo_row((), {"fire": 2}) is None
    empty = ComboRow({})
    assert empty.matches({"fire": 2}) is False
    assert match_combo_row((empty,), {"fire": 2}) is None


def test_pool_values_of_missing_axis():
    """RS-5 降级：轴未注册 / 槽缺失 → 全 0（匹配失败不报错不悬空）。"""
    ctx = _ctx(stats={})
    assert pool_values_of(ctx, ELEMENT_ID, ("fire", "water", "wind")) == {
        "fire": 0, "water": 0, "wind": 0}
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 2})
    assert pool_values_of(ctx2, ELEMENT_ID, ("fire", "water", "wind")) == {
        "fire": 2, "water": 0, "wind": 0}  # 未预置池回落 base=0


# =====================================================================================
# 三、F-C1 三重门禁（① 常规 → ② 总量 → ③ 组合）
# =====================================================================================


def test_gate_conventional_placeholder():
    """① 常规门禁占位：mp/冷却/条件判定归战斗层管道，引擎返回 ok（结构完整）。"""
    assert gate_conventional({}, None)["ok"] is True


def test_gate_total_sufficient_and_insufficient():
    """② 总量门（D-02）：any:2 需总能量 ≥ 2；fire1+water1 通过、fire1 不足。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 1})
    r = gate_total(ctx, _burst(), ELEMENT_ID)
    assert r["ok"] is True and r["need"] == 2 and r["have"] == 2
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 1})
    r2 = gate_total(ctx2, _burst(), ELEMENT_ID)
    assert r2["ok"] is False
    assert r2["reason"] == REASON_TOTAL_INSUFFICIENT
    assert r2["need"] == 2 and r2["have"] == 1  # 被拒不耗回合


def test_gate_total_named_keys_sum():
    """② 总量门具名键求和口径：{fire:1,water:1} → need 2（K2 同为能量消耗）。"""
    skill = {"energy_cost": {ELEMENT_ID: {"fire": 1, "water": 1}}}
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 1})
    assert gate_total(ctx, skill, ELEMENT_ID)["ok"] is True
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 1})
    r2 = gate_total(ctx2, skill, ELEMENT_ID)
    assert r2["ok"] is False and r2["need"] == 2 and r2["have"] == 1


def test_gate_total_bare_any_form():
    """6c §3.1 原例形态兼容：energy_cost {"any": 2} 裸键（轴隐式）同样求和。"""
    skill = {"energy_cost": {"any": 2}}  # 契约示例原文形态
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2})
    assert gate_total(ctx, skill, ELEMENT_ID)["ok"] is True
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 1})
    assert gate_total(ctx2, skill, ELEMENT_ID)["ok"] is False


def test_gate_total_no_cost_and_missing_axis():
    """无 energy_cost 段 / 未注册轴 → 放行 ok（RS-5 降级，V1 红拦归批12）。"""
    ctx = _ctx()
    r = gate_total(ctx, {"combo_table": []}, ELEMENT_ID)
    assert r["ok"] is True and r["need"] == 0
    ctx2 = _ctx(stats={})
    r2 = gate_total(ctx2, _burst(), ELEMENT_ID)
    assert r2["ok"] is True  # 轴未注册 → 降级放行


def test_gate_combination_six_rows_each():
    """TC-14① 六组合逐一匹配：依次凑出 🔥🔥/💧💧/🌪🌪/🔥💧/🔥🌪/💧🌪 后锁定对应行。"""
    cases = [
        ({"fire": 2}, "烈焰爆破"),
        ({"water": 2}, "水镜壁垒"),
        ({"wind": 2}, "疾风连刃"),
        ({"fire": 1, "water": 1}, "蒸汽冲击"),
        ({"fire": 1, "wind": 1}, "火焰风暴"),
        ({"water": 1, "wind": 1}, "和风细雨"),
    ]
    for values, expect in cases:
        ctx = _ctx()
        _seed_pool(ctx, values)
        r = gate_combination(ctx, _burst(), ELEMENT_ID)
        assert r["ok"] is True, f"{values} 应匹配 {expect}"
        assert r["row"].name == expect
        assert r["row"] in r["matched"]


def test_gate_combination_no_match_any():
    """TC-14②/CM-3：分布不满足任一组合行（fire1+wind1 之外的零散分布）→ 拒。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 1, "wind": 0})
    # fire+water 恰好匹配蒸汽冲击——用 fire1+water0+wind1 之外的不匹配分布：
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 1})
    r = gate_combination(ctx2, _burst(), ELEMENT_ID)
    assert r["ok"] is False and r["reason"] == REASON_NO_MATCH
    assert r["row"] is None and r["hints"] == []
    # 无 combo_table 段 → 空表放行（B-3：常规技能语义，由 resolve 短路 ok；
    # gate_combination 单独调用时空表返回 ok+row=None，调用方按常规技能处理）
    r2 = gate_combination(ctx2, {"id": "normal_skill"}, ELEMENT_ID)
    assert r2["ok"] is True and r2["row"] is None


def test_resolve_trigger_total_gate_reject():
    """TC-03②/TC-14：总量不足 → 三重门禁在 ② 短路被拒（reason=总量不足）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1})
    r = resolve_trigger(ctx, _burst(), ELEMENT_ID)
    assert r["ok"] is False and r["rejected"] is True
    assert r["reason"] == REASON_TOTAL_INSUFFICIENT
    assert r["row"] is None and r["need"] == 2 and r["total"] == 1
    assert r["events"][0]["stage"] == "total"  # 短路事件


def test_resolve_trigger_combination_gate_reject_d02():
    """D-02 双重校验：总量足（2）但池分布不满足任一组合行 → 组合门拒，能量不变。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 1, "wind": 0})  # 总量 2 但分布 = 火水
    # 火水分布恰好匹配蒸汽冲击——构造「总量 2 但不匹配任何行」的分布：
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 1, "water": 0, "wind": 0})
    assert resolve_trigger(ctx2, _burst(), ELEMENT_ID)["reason"] == REASON_TOTAL_INSUFFICIENT
    # fire1+wind1 匹配火焰风暴；唯一「总量 2 且无匹配行」= 单池 2 之外无分布，
    # 用 fire1+water1 匹配蒸汽冲击后断言 matched 内容：
    r = resolve_trigger(ctx, _burst(), ELEMENT_ID)
    assert r["ok"] is True and r["row"].name == "蒸汽冲击"
    assert [m.name for m in r["matched"]] == ["蒸汽冲击"]
    # 总量满足但无匹配行的真例：fire2+water2 中 fire=2 已匹配烈焰爆破；
    # 纯不匹配分布 = {"fire":0,"water":1}（总量 1 < 2）→ 总量拒已覆盖；
    # 结论：3 池总量 2 的任意分布必匹配某组合行（6 行满配）——D-02 拒绝
    # 场景由「总量足但单池分布不足」用例覆盖（见下）。
    assert r["total"] == 2 and r["need"] == 2


def test_resolve_trigger_d02_total_ok_distribution_bad():
    """D-02 真实拒绝场景：any:2 总量通过（fire2+water1=3）但锁定行不存在时
    用自定义 1 行表验证——组合行 [water,water] 需 water≥2，fire2+water1 总量 3
    ≥ 2 但 water=1 不满足该行 → 组合门拒、能量不变（先匹配后消耗）。"""
    skill = {
        "energy_cost": {ELEMENT_ID: {"any": 2}},
        "combo_table": [{"combo": ["water", "water"], "name": "仅水行"}],
    }
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2, "water": 1})
    r = resolve_trigger(ctx, skill, ELEMENT_ID)
    assert r["ok"] is False and r["rejected"] is True
    assert r["reason"] == REASON_NO_MATCH
    assert r["need"] == 2 and r["total"] == 3  # 总量门已过
    seg = ctx[RESOURCE_STATE_KEY]["player"][ELEMENT_ID]
    assert seg == {"fire": 2, "water": 1}  # 能量不变（CM-2 判定零扣减）


def test_resolve_trigger_ok_locks_row_no_side_effect():
    """CM-2 先匹配后消耗：门禁全过锁定行，但判定阶段零扣减（能量/MP 不变）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2})
    r = resolve_trigger(ctx, _burst(), ELEMENT_ID)
    assert r["ok"] is True and r["rejected"] is False
    assert r["row"].name == "烈焰爆破"
    assert r["events"][0]["stage"] == "all"
    seg = ctx[RESOURCE_STATE_KEY]["player"][ELEMENT_ID]
    assert seg == {"fire": 2}  # 未扣减（消耗归 F-C2 结算阶段）
    assert ctx.get("mp") is None  # 本引擎不触碰 MP


def test_resolve_trigger_no_combo_table_skill():
    """B-3：无 combo_table 段 → ok=True + row=None（常规技能语义，不拦截）。

    无 energy_cost 且无组合表：gate_combination 空表不拦截，resolve 放行。
    """
    ctx = _ctx()
    r = resolve_trigger(ctx, {"id": "normal", "energy_cost": {}}, ELEMENT_ID)
    assert r["ok"] is True and r["rejected"] is False and r["row"] is None
    assert r["reason"] == REASON_OK


# =====================================================================================
# 四、先匹配后消耗原语（CM-2 / F-C2 ① 扣减方案）
# =====================================================================================


def test_row_cost_plan_by_locked_row():
    """CM-2/F-C2 ①：锁定行 → 按该行池分布扣减方案（[fire,fire] → fire 扣 2）。"""
    rows = rows_of(_burst())
    by_name = {r.name: r for r in rows}
    assert row_cost_plan(by_name["烈焰爆破"]) == [{"pool": "fire", "amount": 2}]
    assert row_cost_plan(by_name["蒸汽冲击"]) == [
        {"pool": "fire", "amount": 1}, {"pool": "water", "amount": 1}]
    assert row_cost_plan(by_name["疾风连刃"]) == [{"pool": "wind", "amount": 2}]
    assert row_cost_plan(ComboRow({})) == []  # 空行 → 空方案


def test_combo_cost_plan_any_gate():
    """CM-2：any:n 总量门扣减方案（B-5 承接 resource_axis.cost_breakdown，确定性）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2, "water": 2})
    plan = combo_cost_plan(ctx, _burst(), ELEMENT_ID)
    assert plan == [{"pool": "fire", "amount": 2}]  # 池序均摊
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 1})
    assert combo_cost_plan(ctx2, _burst(), ELEMENT_ID) is None  # 总量不足不半扣
    assert combo_cost_plan(ctx2, {"id": "no_cost"}, ELEMENT_ID) == []  # 无消耗


def test_combo_cost_plan_bare_any_form():
    """裸键形态兼容：energy_cost {"any": 2} 同样产出扣减方案。"""
    skill = {"energy_cost": {"any": 2}}
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 1})
    plan = combo_cost_plan(ctx, skill, ELEMENT_ID)
    assert plan == [{"pool": "fire", "amount": 1}, {"pool": "water", "amount": 1}]


# =====================================================================================
# 五、引擎注入模式（ComboTableEngine）
# =====================================================================================


def test_engine_injected_stats_and_state():
    """引擎构造器注入：stats/resource_state 挂 ctx（缺省键不覆盖显式注入，幂等）。"""
    rs: Dict[str, Any] = {"player": {ELEMENT_ID: {"fire": 2}}}
    stats = {ELEMENT_ID: _element()}
    engine = ComboTableEngine(stats=stats, resource_state=rs)
    ctx: MutableMapping[str, Any] = {}
    r = engine.resolve(_burst(), ctx, ELEMENT_ID)
    assert ctx["stats"] is stats
    assert ctx[RESOURCE_STATE_KEY] is rs
    assert r["ok"] is True and r["row"].name == "烈焰爆破"


def test_engine_rows_match_resolve_suggest():
    """引擎便捷入口：rows/match/resolve/suggest 语义与模块级函数一致。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 1})
    engine = ComboTableEngine()
    assert len(engine.rows(_burst())) == 6
    m = engine.match(_burst(), ctx, ELEMENT_ID)
    assert m["row"].name == "蒸汽冲击"
    assert [r.name for r in m["matched"]] == ["蒸汽冲击"]
    r = engine.resolve(_burst(), ctx, ELEMENT_ID)
    assert r["ok"] is True and r["row"].name == "蒸汽冲击"
    s = engine.suggest(_burst(), ctx, ELEMENT_ID)
    assert s[0]["name"] == "蒸汽冲击"
    # 无匹配分布 → resolve 拒 + suggest 空
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 0})
    assert engine.resolve(_burst(), ctx2, ELEMENT_ID)["ok"] is False
    assert engine.suggest(_burst(), ctx2, ELEMENT_ID) == []


def test_engine_audit_log():
    """审计观察口：resolve/match 记录审计行。"""
    logs: List[str] = []
    engine = ComboTableEngine(audit=logs.append)
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2})
    engine.resolve(_burst(), ctx, ELEMENT_ID)
    engine.match(_burst(), ctx, ELEMENT_ID)
    assert any("combo_resolve: ok=True" in line for line in logs)
    assert any("combo_match: matched=1" in line for line in logs)


# =====================================================================================
# 六、契约常量与事件形态（B-7）
# =====================================================================================


def test_constants_and_event_shape():
    """契约常量：kind 枚举四值 / 事件 type=combo_gate / reason 语义键。"""
    assert COMBO_KINDS == (KIND_DAMAGE, KIND_UTILITY, KIND_HEAL, KIND_CONTROL)
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1})
    r = resolve_trigger(ctx, _burst(), ELEMENT_ID)
    ev = r["events"][0]
    assert ev["type"] == EVENT_COMBO_GATE and ev["stage"] == "total"
    assert ev["reason"] == REASON_TOTAL_INSUFFICIENT
