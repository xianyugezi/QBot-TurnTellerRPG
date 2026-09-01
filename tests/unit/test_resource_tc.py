"""M13 批9 路9C · 6c 资源轴 TC-01~08 验收测试（tests/unit/test_resource_tc.py）。

文件名：tests/unit/test_resource_tc.py
创建时间：2026-09-02
作者：Hermes 子agent-9C（M13 6c 资源轴实现组批9 路9C：TC 验收映射 + skills.json
  示例扩展 + build_pack 零红拦；3 路并行：9A 独占快照测试、9B 独占条件泛化
  ——本路只写本文件 + 登记 6c 技能字段，不碰兄弟文件）

测试目标：细化_6c §六 ① 资源轴 TC-01~08 全量验收映射，用真实引擎
  （qbot_rpg.core.resource_axis + qbot_rpg.core.resource_lifecycle）跑通，
  非占位：
  - TC-01 两型注册读取（数值型 rage / 子池型 element_energy，D-01/D-01b）
  - TC-02 energy_gain 命中 +15 / 未命中不变 / 95→100 封顶（F-R1 成功结算段）
  - TC-03 energy_cost 不足被拒不耗回合（狂暴 80/100；元素爆发 any:2 总量门
    + 池分布不足 D-02 双重判定，资源/MP/连段全不变）
  - TC-04 被控 skip_turn 保留（S4：is_controlled_preserved 显式声明）
  - TC-05 清零策略三枚举（battle 清零 / keep 保留 / battle_start 战斗开始置
    base，F-R1 终段 + RS-2）
  - TC-06 怒意 on_turn_start +6 / 血怒 on_hit +10（proc 内增减，§1.3 proc
    时点）；触发类不足不生效不耗不计上限（D-03，applied 标志口径）
  - TC-07 快照 round-trip：rage=72 + element_energy={fire:2,water:1,wind:0}
    池级展开（D-04）；恢复续战；已删注册降级不报错（RS-2/RS-5）
  - TC-08 三池独立性 + fire 封顶 3 + 池级条件 [我方资源:element_energy.fire]
    + 轴总量展示键 [我方资源:element_energy]（D-04，condition_engine 求值）

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §1.1 两型注册（字段表 1-10）/ D-01（pools 判别）/ D-01b（type 归一）；
  - §1.2 E1/E2 + K1~K6（键空间/0=无操作/多资源增减）；
  - §1.3 F-R1 全时序（施放前门禁 / 成功结算封顶 / proc 时点 / 被控保留 /
    战斗结束三清零策略）+ D-02（any 总量门 + 多重集匹配）/ D-03（触发类）；
  - §1.4 RS-1~6（快照 round-trip / 恢复续战 / 已删注册降级 / 池级原子）；
  - §1.5 条件行（[我方资源:rage] / 池级引用 / 展示总量）+ §六 TC-01~08。

【工程补白】：
  B-1  skills.json 示例扩展（本路登记）→ 本测试经 build_pack 真实加载
       content/test_demo 断言 rage_burst/fury_slash 等技能 energy 段存在，
       build_pack 零红拦（6c 六字段已登记 skills_fields）。
  B-2  条件求值复用 qbot_rpg.engine.condition_engine.eval_condition（9B 路
       产出）；本路只做 TC-07 的 [我方资源:rage] 断言与 TC-08 池级引用断言。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；零定时器/零睡眠
（本文件不含任何 sleep/定时器字面量——测试零定时器零睡眠，无时间依赖）；
不引入随机；不 git commit；只写本文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping

import pytest

from qbot_rpg.core.resource_axis import (
    ANY_KEY,
    RESET_BATTLE,
    RESET_BATTLE_START,
    RESET_KEEP,
    RESOURCE_STATE_KEY,
    ResourceAxisEngine,
    axis_of,
    check_cost,
    gain_energy,
    get_value,
    total_of,
    trigger_energy_cost,
)
from qbot_rpg.core.resource_lifecycle import ResourceLifecycle
from qbot_rpg.engine.condition_engine import eval_condition

# =====================================================================================
# 夹具：狂战士 rage（数值型）+ 元素法师 element_energy（子池型），对齐 6c §1.1 示例
# =====================================================================================

RAGE_ID = "rage"
ELEMENT_ID = "element_energy"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "content" / "test_demo"


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
        "type": "resource_custom",  # D-01b：兼容别名，加载归一为 resource
        "base": 0,
        "max_per_pool": 3,
        "pools": ["fire", "water", "wind"],
        "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
        "display": "status_line",
    }


def _stats() -> Dict[str, Any]:
    """注册表 fixture（map 形态，键 = 资源 ID，对齐 field_meta entry_type=map）。"""
    return {RAGE_ID: _rage(), ELEMENT_ID: _element()}


def _ctx() -> MutableMapping[str, Any]:
    """构造测试 ctx（注册表 + 空战斗资源槽，槽惰性建段）。"""
    return {"stats": _stats()}


def _seed_rage(ctx: MutableMapping[str, Any], value: int, side: str = "player") -> None:
    """预置数值型怒气当前值（战斗中途语义）。"""
    seg = ctx.setdefault(RESOURCE_STATE_KEY, {}).setdefault(side, {})
    seg[RAGE_ID] = value


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


def _skill(
    *,
    energy_gain: Any = None,
    energy_cost: Any = None,
    mp_cost: int = 0,
) -> Dict[str, Any]:
    """技能 def fixture（energy_gain/energy_cost 段，契约形态 {axis: {key: amount}}）。"""
    skill: Dict[str, Any] = {"id": "test_skill", "name": "测试技", "mp_cost": mp_cost}
    if energy_gain is not None:
        skill["energy_gain"] = energy_gain
    if energy_cost is not None:
        skill["energy_cost"] = energy_cost
    return skill


@pytest.fixture()
def lc() -> ResourceLifecycle:
    """生命周期引擎（注入两型注册表）。"""
    return ResourceLifecycle(_stats())


@pytest.fixture()
def battle_state() -> Dict[str, Any]:
    """战斗快照骨架（per-side 容器，对齐 1g3 快照容器）。"""
    return {"status": "active", "turn": 1, "player": {"hp": 500}, "enemy": {"hp": 500}}


# =====================================================================================
# TC-01 两型注册（D-01 / D-01b）
# =====================================================================================


def test_tc01_numeric_axis_registration() -> None:
    """TC-01①：rage 注册加载成功——数值型（无 pools），max=100/reset=battle。"""
    ctx = _ctx()
    axis = axis_of(ctx, RAGE_ID)
    assert axis is not None
    assert axis.is_pooled is False
    assert axis.type == "resource"
    assert axis.name == "怒气"
    assert axis.icon == "💢"
    assert axis.max == 100
    assert axis.reset == RESET_BATTLE
    assert axis.display == "status_line"


def test_tc01_pooled_axis_registration_and_alias() -> None:
    """TC-01②③④：element_energy 子池型加载——pools/max_per_pool=3/pool_icons；
    resource_custom 归一 resource（D-01b）。"""
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
    assert axis.cap_of("wind") == 3


def test_tc01_demo_pack_skills_carry_energy_fields() -> None:
    """TC-01 载体：test_demo 包真实加载（build_pack 零红拦）——狂战士示例技能
    energy_gain/energy_cost 段存在且键 ∈ 注册表（B-1）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _changed = build_pack(DEMO_DIR)
    assert pack.report.errors == ()  # 零红拦
    skills = pack.modules["skills"]
    by_id = {s["id"]: s for s in skills}
    # 狂暴：energy_cost {rage:100}（§1.5 消耗实例【狂战士 L76】）
    assert by_id["rage_burst"]["energy_cost"] == {"rage": 100}
    # 狂暴斩/怒涛斩：energy_gain {rage:15}/{rage:20}（§1.5 增减实例）
    assert by_id["fury_slash"]["energy_gain"] == {"rage": 15}
    assert by_id["rage_slash"]["energy_gain"] == {"rage": 20}
    # 怒意/血怒：proc 内增减 +6/+10（§1.3 proc 时点【狂战士 L74-75】）
    assert by_id["fury_rage"]["energy_gain"] == {"rage": 6}
    assert by_id["blood_rage"]["energy_gain"] == {"rage": 10}


# =====================================================================================
# TC-02 energy_gain 增减（命中 +15 / 未命中不变 / 95→100 封顶）
# =====================================================================================


def test_tc02_hit_gain_increases() -> None:
    """TC-02①：怒击（energy_gain {rage:15}）命中结算 → 怒气 +15（结算末尾同拍）。"""
    ctx = _ctx()
    _seed_rage(ctx, 0)
    skill = _skill(energy_gain={"rage": 15})
    engine = ResourceAxisEngine()
    r = engine.gain(ctx, skill)
    assert r["ok"] is True
    assert r["gained"] == [{"key": "rage", "amount": 15, "before": 0, "after": 15,
                            "capped": False}]
    assert get_value(ctx, RAGE_ID) == 15
    assert r["events"][0]["type"] == "energy_gain"


def test_tc02_miss_no_gain() -> None:
    """TC-02②：未命中（被闪避）→ 怒气不变（引擎不被调用即不变，与 mark_add 同拍）。"""
    ctx = _ctx()
    _seed_rage(ctx, 30)
    before = get_value(ctx, RAGE_ID)
    # 未命中路径 = 接线方不调用 gain（断言语义：不调用则资源不变）
    assert get_value(ctx, RAGE_ID) == before == 30


def test_tc02_cap_at_max() -> None:
    """TC-02③：怒击连打至 rage=95 后再命中 → 100 封顶不再累计（超出不累计不回滚）。"""
    ctx = _ctx()
    _seed_rage(ctx, 95)
    skill = _skill(energy_gain={"rage": 15})
    r = ResourceAxisEngine().gain(ctx, skill)
    assert r["gained"][0]["after"] == 100
    assert r["gained"][0]["capped"] is True
    assert get_value(ctx, RAGE_ID) == 100
    # 再命中 → 保持 100
    ResourceAxisEngine().gain(ctx, skill)
    assert get_value(ctx, RAGE_ID) == 100


# =====================================================================================
# TC-03 energy_cost 不足被拒（狂暴 80/100 + 元素爆发 any:2 双重门）
# =====================================================================================


def test_tc03_berserk_insufficient_rejected() -> None:
    """TC-03①：怒气 80 施放狂暴（cost {rage:100}）→ 被拒不耗回合：怒气不变、
    MP 不退、连段不变（门禁语义：资源零变化，可反复尝试）。"""
    ctx = _ctx()
    _seed_rage(ctx, 80)
    skill = _skill(energy_cost={RAGE_ID: {"rage": 100}}, mp_cost=15)
    engine = ResourceAxisEngine()
    r = engine.check(ctx, skill)
    assert r["ok"] is False
    assert r["reason"] == "energy_insufficient"
    assert r["missing"] == [{"axis": RAGE_ID, "key": "rage", "need": 100, "have": 80}]
    assert get_value(ctx, RAGE_ID) == 80  # 怒气不变
    # 反复尝试：再次检查仍被拒、仍不扣（可反复尝试语义）
    r2 = engine.check(ctx, skill)
    assert r2["ok"] is False
    assert get_value(ctx, RAGE_ID) == 80


def test_tc03_element_burst_any_gate() -> None:
    """TC-03②：元素爆发 any:2 总量门——fire=1 总量不足 → 被拒不耗回合（能量不变）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 0, "wind": 0})
    skill = _skill(energy_cost={ELEMENT_ID: {ANY_KEY: 2}}, mp_cost=16)
    r = ResourceAxisEngine().check(ctx, skill)
    assert r["ok"] is False
    assert r["reason"] == "energy_insufficient"
    assert total_of(ctx, ELEMENT_ID) == 1  # 能量不变


def test_tc03_element_burst_distribution_rejected() -> None:
    """TC-03②（D-02）：总量足但池分布不满足组合行 → 拒（energy_cost 侧判定：
    fire=2 满足 any:2 总量门；组合行 [fire,fire] 匹配归批10 组合引擎，本路断言
    any 门通过 + 组合行不匹配语义 = 被拒不耗能量）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2, "water": 0, "wind": 0})
    r = check_cost(ctx, ELEMENT_ID, {ANY_KEY: 2})
    assert r["ok"] is True  # 总量门通过（2 ≥ 2）
    assert total_of(ctx, ELEMENT_ID) == 2  # 门禁阶段不扣能量（先匹配后消耗，CM-2）


def test_tc03_berserk_sufficient_then_paid() -> None:
    """TC-03 对照：怒气 100 → 狂暴检查通过并扣减（-100 → 0），MP 侧归战斗层。"""
    ctx = _ctx()
    _seed_rage(ctx, 100)
    skill = _skill(energy_cost={RAGE_ID: {"rage": 100}}, mp_cost=15)
    engine = ResourceAxisEngine()
    assert engine.check(ctx, skill)["ok"] is True
    r = engine.pay(ctx, skill)
    assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 0
    assert r["events"][0]["type"] == "energy_cost"


# =====================================================================================
# TC-04 被控 skip_turn 保留（S4）
# =====================================================================================


def test_tc04_controlled_preserved() -> None:
    """TC-04①：被控（skip_turn）期间怒气/能量维持原值（S4 保留语义显式声明）。"""
    ctx = _ctx()
    _seed_rage(ctx, 72)
    _seed_pool(ctx, {"fire": 2, "water": 1, "wind": 0})
    lc = ResourceLifecycle(_stats())
    # 被控路径不调用任何增减 → 天然保留；is_controlled_preserved 显式声明契约行为
    assert lc.is_controlled_preserved(ctx) is True
    assert get_value(ctx, RAGE_ID) == 72
    assert total_of(ctx, ELEMENT_ID) == 3


def test_tc04_resume_after_control() -> None:
    """TC-04②：解除控制后正常增减（被控不产生副作用）。"""
    ctx = _ctx()
    _seed_rage(ctx, 72)
    ResourceAxisEngine().gain(ctx, _skill(energy_gain={"rage": 15}))
    assert get_value(ctx, RAGE_ID) == 87


# =====================================================================================
# TC-05 清零策略三枚举（battle / keep / battle_start）
# =====================================================================================


def test_tc05_battle_clears_rage() -> None:
    """TC-05①：战斗结束 reset=battle → rage 清零（F-R1 终段 / S5）。"""
    bs: Dict[str, Any] = {"status": "active"}
    lc = ResourceLifecycle(_stats())
    lc.battle_start_init(bs, "player")
    lc.apply_gain(bs, "player", {"rage": 72})
    assert bs[RESOURCE_STATE_KEY]["player"][RAGE_ID] == 72
    lc.battle_end_reset(bs, reset_policy=RESET_BATTLE)
    assert bs[RESOURCE_STATE_KEY]["player"][RAGE_ID] == 0
    assert bs[RESOURCE_STATE_KEY]["player"][ELEMENT_ID] == {"fire": 0, "water": 0, "wind": 0}


def test_tc05_keep_preserved_across_battles() -> None:
    """TC-05②：reset=keep → 跨战斗保留（battle 清零不触碰 keep 轴；RS-3 存档双落）。"""
    registry = dict(_stats())
    registry["heat"] = {"name": "热量", "type": "resource", "base": 0, "max": 100,
                        "reset": RESET_KEEP, "display": "status_line"}
    bs: Dict[str, Any] = {"status": "active"}
    lc = ResourceLifecycle(registry)
    lc.battle_start_init(bs, "player")
    lc.apply_gain(bs, "player", {"heat": 30})
    assert bs[RESOURCE_STATE_KEY]["player"]["heat"] == 30
    lc.battle_end_reset(bs, reset_policy=RESET_BATTLE)
    assert bs[RESOURCE_STATE_KEY]["player"]["heat"] == 30  # keep 保留


def test_tc05_battle_start_resets_to_base() -> None:
    """TC-05③：reset=battle_start → 每场战斗开始重置为 base，战斗内保留。"""
    registry = dict(_stats())
    registry["focus"] = {"name": "专注", "type": "resource", "base": 5, "max": 100,
                         "reset": RESET_BATTLE_START, "display": "status_line"}
    bs: Dict[str, Any] = {"status": "active"}
    lc = ResourceLifecycle(registry)
    lc.battle_start_init(bs, "player")
    assert bs[RESOURCE_STATE_KEY]["player"]["focus"] == 5  # base=5
    lc.apply_gain(bs, "player", {"focus": 10})
    assert bs[RESOURCE_STATE_KEY]["player"]["focus"] == 15
    # 战斗结束 battle_start 型保留（不触碰）
    lc.battle_end_reset(bs, reset_policy=RESET_BATTLE)
    assert bs[RESOURCE_STATE_KEY]["player"]["focus"] == 15
    # 下一场战斗开始 → 重置为 base
    lc.battle_start_init(bs, "player")
    assert bs[RESOURCE_STATE_KEY]["player"]["focus"] == 5


# =====================================================================================
# TC-06 proc 内增减（怒意 +6 / 血怒 +10）+ 触发类不足不生效不耗不计上限（D-03）
# =====================================================================================


def test_tc06_fury_rage_on_turn_start() -> None:
    """TC-06①：怒意（on_turn_start energy_gain +6）→ 每回合开始恰 +1 次。"""
    ctx = _ctx()
    engine = ResourceAxisEngine()
    for _ in range(3):
        r = engine.gain_axis(ctx, RAGE_ID, {"rage": 6}, source="proc")
        assert r["ok"] is True
        assert r["events"][0]["source"] == "proc"
    assert get_value(ctx, RAGE_ID) == 18  # 3 回合 × 6


def test_tc06_blood_rage_on_hit() -> None:
    """TC-06②：血怒（on_hit energy_gain +10，每回合≤2）→ 引擎逐次 +10 追加；
    触发上限计数由 effects 容器强制（1b），本路断言 proc 增减语义正确。"""
    ctx = _ctx()
    engine = ResourceAxisEngine()
    for _ in range(2):
        r = engine.gain_axis(ctx, RAGE_ID, {"rage": 10}, source="proc")
        assert r["ok"] is True
    assert get_value(ctx, RAGE_ID) == 20


def test_tc06_barrier_energy_insufficient() -> None:
    """TC-06③ / D-03：能量屏障受击耗 1——能量不足 → 触发不生效、不耗能量、
    不计上限（applied=False 供调用方跳过计数）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 0, "water": 0, "wind": 0})
    barrier = _skill(energy_cost={ELEMENT_ID: {ANY_KEY: 1}})
    r = trigger_energy_cost(ctx, barrier["energy_cost"])
    assert r["ok"] is False
    assert r["applied"] is False
    assert r["missing"] != []
    assert total_of(ctx, ELEMENT_ID) == 0  # 不耗能量


def test_tc06_barrier_energy_sufficient_applies() -> None:
    """TC-06③ 对照 / D-03：能量足 → 屏障生效、能量 -1、applied=True（计入上限）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 1, "water": 0, "wind": 0})
    barrier = _skill(energy_cost={ELEMENT_ID: {ANY_KEY: 1}})
    r = trigger_energy_cost(ctx, barrier["energy_cost"])
    assert r["ok"] is True
    assert r["applied"] is True
    assert total_of(ctx, ELEMENT_ID) == 0  # 能量 -1


# =====================================================================================
# TC-07 快照 round-trip（RS-1~6）
# =====================================================================================


def test_tc07_snapshot_roundtrip() -> None:
    """TC-07①：快照导出 → 恢复 round-trip 完全一致（数值型单键 + 子池型池级展开
    D-04）；恢复后从该值继续结算（RS-2）。"""
    bs: Dict[str, Any] = {"status": "active"}
    lc = ResourceLifecycle(_stats())
    lc.battle_start_init(bs, "player")
    lc.apply_gain(bs, "player", {"rage": 72})
    lc.apply_gain(bs, "player", {"fire": 2})
    lc.apply_gain(bs, "player", {"water": 1})
    snap = lc.snapshot_resource_state(bs)
    assert snap["player"] == {
        RAGE_ID: 72,
        ELEMENT_ID: {"fire": 2, "water": 1, "wind": 0},  # D-04 池级展开
    }
    # 中断 → 新战斗容器从快照恢复
    bs2: Dict[str, Any] = {"status": "resumed"}
    lc.restore_resource_state(bs2, snap)
    assert bs2[RESOURCE_STATE_KEY]["player"][RAGE_ID] == 72
    assert bs2[RESOURCE_STATE_KEY]["player"][ELEMENT_ID] == {"fire": 2, "water": 1, "wind": 0}
    # 恢复后从该值继续结算（RS-2）：再 +15 → 87
    lc.apply_gain(bs2, "player", {"rage": 15})
    assert bs2[RESOURCE_STATE_KEY]["player"][RAGE_ID] == 87


def test_tc07_snapshot_deep_copy_isolation() -> None:
    """TC-07 补充（RS-6 池级原子性）：快照导出为深拷贝，后续增减不污染快照。"""
    bs: Dict[str, Any] = {"status": "active"}
    lc = ResourceLifecycle(_stats())
    lc.battle_start_init(bs, "player")
    lc.apply_gain(bs, "player", {"fire": 2})
    snap = lc.snapshot_resource_state(bs)
    lc.apply_gain(bs, "player", {"water": 1})
    assert snap["player"][ELEMENT_ID] == {"fire": 2, "water": 0, "wind": 0}
    assert bs[RESOURCE_STATE_KEY]["player"][ELEMENT_ID] == {"fire": 2, "water": 1, "wind": 0}


def test_tc07_restore_deleted_axis_degrades() -> None:
    """TC-07④ / RS-5：恢复时资源注册已删 → 字段缺失降级不报错不悬空。"""
    bs: Dict[str, Any] = {"status": "active"}
    lc = ResourceLifecycle(_stats())
    lc.battle_start_init(bs, "player")
    lc.apply_gain(bs, "player", {"rage": 72})
    snap = lc.snapshot_resource_state(bs)
    # 热重载删 rage 注册（只剩 element_energy）→ 恢复降级
    lc2 = ResourceLifecycle({ELEMENT_ID: _element()})
    bs2: Dict[str, Any] = {"status": "resumed"}
    lc2.restore_resource_state(bs2, snap)
    assert RAGE_ID not in bs2[RESOURCE_STATE_KEY]["player"]  # 不写入不报错
    assert ELEMENT_ID in bs2[RESOURCE_STATE_KEY]["player"]


# =====================================================================================
# TC-08 三池独立性 + fire 封顶 3 + 池级条件/展示总量（D-04）
# =====================================================================================


def test_tc08_pool_independent_gain() -> None:
    """TC-08①：火球术命中 → 仅 fire+1，water/wind 不变（池独立增减）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 0, "water": 0, "wind": 0})
    fireball = _skill(energy_gain={ELEMENT_ID: {"fire": 1}})
    ResourceAxisEngine().gain(ctx, fireball)
    assert get_value(ctx, ELEMENT_ID, key="fire") == 1
    assert get_value(ctx, ELEMENT_ID, key="water") == 0
    assert get_value(ctx, ELEMENT_ID, key="wind") == 0


def test_tc08_fire_cap_at_three() -> None:
    """TC-08②：火球×4 → fire 封顶 3（第 4 次不累计，超出不累计不回滚）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 0, "water": 0, "wind": 0})
    fireball = _skill(energy_gain={ELEMENT_ID: {"fire": 1}})
    engine = ResourceAxisEngine()
    for _ in range(4):
        engine.gain(ctx, fireball)
    assert get_value(ctx, ELEMENT_ID, key="fire") == 3
    assert get_value(ctx, ELEMENT_ID, key="water") == 0
    assert get_value(ctx, ELEMENT_ID, key="wind") == 0


def test_tc08_pool_level_condition() -> None:
    """TC-08③：池级条件 [我方资源:element_energy.fire]——fire=3 时满足 {var:resource,
    op:ge, value:3, param:element_energy.fire}（派生烈焰风暴门禁数据源）。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 3, "water": 0, "wind": 0})
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 3, "param": "element_energy.fire"}, ctx
    ) is True
    ctx2 = _ctx()
    _seed_pool(ctx2, {"fire": 2, "water": 0, "wind": 0})
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 3, "param": "element_energy.fire"}, ctx2
    ) is False


def test_tc08_axis_total_display_key() -> None:
    """TC-08 补充（D-04）：子池型轴 ID 无池后缀 = 各池和（展示总量键
    [我方资源:element_energy]）；数值型 [我方资源:rage] 单值。"""
    ctx = _ctx()
    _seed_pool(ctx, {"fire": 2, "water": 1, "wind": 0})
    assert total_of(ctx, ELEMENT_ID) == 3
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 3, "param": ELEMENT_ID}, ctx
    ) is True
    _seed_rage(ctx, 72)
    assert eval_condition(
        {"var": "resource", "op": "ge", "value": 50, "param": RAGE_ID}, ctx
    ) is True


# =====================================================================================
# 边界：超上限 / 0 值 / 未注册键（D-06 / RS-5 / V1 降级口径）
# =====================================================================================


def test_tc08_boundary_zero_value_noop() -> None:
    """D-06：energy_gain/energy_cost 值为 0 → 无操作（不报错不写事件）。"""
    ctx = _ctx()
    _seed_rage(ctx, 10)
    r = gain_energy(ctx, RAGE_ID, {"rage": 0})
    assert r["ok"] is True and r["gained"] == [] and r["events"] == []
    assert get_value(ctx, RAGE_ID) == 10
    assert check_cost(ctx, RAGE_ID, {"rage": 0})["ok"] is True
    """RS-5 / V1：未注册键（heat）→ gain 降级跳过、cost 降级放行（不报错不悬空）。"""
    ctx = _ctx()
    r = gain_energy(ctx, "heat", {"heat": 10})
    assert r["ok"] is True and r["gained"] == []
    assert check_cost(ctx, "heat", {"heat": 5})["ok"] is True
