"""HelperEngine 单测（M8 批10-1·路B）——细化_2c5c TC-16~20 / 指令契约 TC-30 引擎可承载部分。

文件名：tests/unit/test_alchemy_helper.py
创建时间：2026-08-29
作者：Hermes 子agent-10B
功能描述：qbot_rpg.core.alchemy_helper.HelperEngine 纯函数直测（对齐 test_synthesis/test_proficiency
  模式）：TC-30 精通玩家 /代工 设定（键值列表 parse_task_spec 解析 / 消耗能源道具 / 缺能源拒绝）、
  tick 后台产出（离线累积 + 余数顺延）、/收取 入包 + 队列清空、非精通拒绝（GU-62）、助手等级提升
  （ASST-07）、状态存档（config/started_at/queue）、队列满（ASST-05）、模块开关（ASST-01）。

依据：
  - docs/m8_contract_指令契约.md §21 /雇工（P-22/SEP-22/GU-62/63/F-22/M-22；收取用 /收取；TC-30）；
    2026-08-28 用户拍板指令名 /雇工 改名 /代工。
  - docs/细化/细化_2c5c_种植品评代工.md §三 ASST-01~09 + §5.1/5.2/5.3（assistant 配置与存档形态）。
  - qbot_rpg/core/alchemy_helper.py（工程补白 B-1~B-11：配置单源 / tick_sec=1800 / max_slots=3 /
    level_thresholds / 纯文本消息 B-9 / ctx["now"] 时钟注入 B-8）。

【工程补白 · 注记】
  - ctx 顶层即玩家状态（proficiency/helpers/inventory），settings 走引擎构造器注入（单源，对齐
    core/alchemy_helper.py 工程补白 1）——本文件夹具与实现一致。
  - 熟练档位口径：ProficiencyEngine 存档 level = 档位索引 0~6（对齐 proficiency.py 补白 3），
    精通 = 档位索引 2；TC-30 用 level 2（精通）精确复现「非精通拒 / 精通放行」。
  - 时钟口径：所有涉及 assign/collect 的用例注入 ctx["now"] = T0（B-8），tick 用显式 now 参数，
    保证纯函数同刻同参同值、与墙钟解耦。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_helper import (
    DEFAULT_LEVEL_THRESHOLDS,
    HelperEngine,
    parse_task_spec,
)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

ITEMS: Dict[str, Mapping[str, Any]] = {
    "candy": {"id": "candy", "name": "糖果", "type": "material"},
    "pie": {"id": "pie", "name": "馅饼", "type": "material"},
    "iron_ore": {"id": "iron_ore", "name": "矿石", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "potion": {"id": "potion", "name": "药剂", "type": "consumable"},
    "elixir": {"id": "elixir", "name": "灵药", "type": "consumable"},
}

RECIPES: Dict[str, Mapping[str, Any]] = {
    # 代调=药剂*2：配方名「药剂」按 name 精确命中（P-22 配方名）；output 药剂×1
    "rcp_potion": {
        "id": "rcp_potion", "name": "药剂", "kind": "craft", "level": 1,
        "output": {"item": "potion", "count": 1}, "materials": [], "cost": {},
    },
    # 代调=灵药*1：配方名「灵药」，output 灵药×2（验证 output.count 乘数）
    "rcp_elixir": {
        "id": "rcp_elixir", "name": "灵药", "kind": "craft", "level": 2,
        "output": {"item": "elixir", "count": 2}, "materials": [], "cost": {},
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "assistant": {
        "enabled": True,
        "unlock_tier": "精通",
        "energy_items": ["candy", "pie"],
        "queue": {"max_slots": 3, "tick_sec": 1800},
        "helpers": [
            {
                "id": "h1", "name": "小助手", "tier": 1,
                "gather_rate": 1.0, "trait_bonus": 0, "quality_bonus": 0,
            },
        ],
        "level_thresholds": [0, 100, 300, 700, 1500],
        "trait_bonus_per_level": 1,
        "quality_bonus_per_level": 5,
    },
}

# 低阈值引擎（等级成长测试用：产 10 即 2 级）
LOW_THRESHOLD_SETTINGS: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
LOW_THRESHOLD_SETTINGS["assistant"]["level_thresholds"] = [0, 10, 30, 60]
LOW_THRESHOLD_SETTINGS["assistant"]["quality_bonus_per_level"] = 5

# 单槽引擎（ASST-05 队列满测试用）
SINGLE_SLOT_SETTINGS: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
SINGLE_SLOT_SETTINGS["assistant"]["queue"] = {"max_slots": 1, "tick_sec": 1800}

# 无助手表引擎（表空 → 任意助手名可用默认系数，B-5）
NO_HELPERS_SETTINGS: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
NO_HELPERS_SETTINGS["assistant"]["helpers"] = []

# 固定时钟（B-8：assign/collect 读 ctx["now"]，tick 显式传 now）
T0 = 1_700_000_000


def _engine(settings: Optional[Mapping[str, Any]] = None) -> HelperEngine:
    """构造引擎：settings 构造器注入（单源）；缺省 DEFAULT_SETTINGS。"""
    return HelperEngine(settings=settings if settings is not None else DEFAULT_SETTINGS)


def make_ctx(
    prof_level: Optional[int] = 2,
    inventory: Optional[Mapping[str, int]] = None,
    now: Optional[int] = None,
    **over: Any,
) -> MutableMapping[str, Any]:
    """全字段玩家代工 ctx（core/alchemy_helper.py 工程补白 1 契约；每场景新造避免互污染）。

    prof_level = 炼金职业档位索引（2 = 精通，GU-62 放行基线；None → 无炼金建档=见习）。
    now = 时钟注入点（B-8：assign/collect 读 ctx["now"]；tick 用显式 now 参数）。
    """
    base: Dict[str, Any] = {
        "qid": "u1",
        "name": "阿伟",
        "proficiency": (
            {"alchemy": {"level": prof_level, "exp": 0}} if prof_level is not None else {}
        ),
        "inventory": dict(inventory) if inventory else {},
        "items": ITEMS,
        "recipe": RECIPES,
        "helpers": {},
        "now": now,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# P-22 / SEP-22 键值列表解析（= 定键、, 分隔、* 数量）
# ---------------------------------------------------------------------------
def test_parse_task_spec_full():
    """TC-30 键值列表原例：'代采=矿石*5,代调=药剂*2' → gather/craft 结构化。"""
    r = parse_task_spec("代采=矿石*5,代调=药剂*2")
    assert r["ok"] is True
    assert r["gather"] == {"target": "矿石", "count": 5}
    assert r["craft"] == {"target": "药剂", "count": 2}


def test_parse_task_spec_default_count_and_aliases():
    """数量缺省 1；gather/craft 别名可用；空串/None → 无任务。"""
    assert parse_task_spec("代采=矿石")["gather"] == {"target": "矿石", "count": 1}
    assert parse_task_spec("gather=矿石*3")["gather"] == {"target": "矿石", "count": 3}
    assert parse_task_spec(None)["ok"] is True
    assert parse_task_spec("")["ok"] is False  # 空串无任何任务段


def test_parse_task_spec_rejects_malformed():
    """非法段/未知键/重复键/非正整数量 → {ok: False, reason: invalid_spec}。"""
    for bad in (
        "代采=矿石*0",
        "代采=矿石*-1",
        "代采=矿石*abc",
        "代采=",
        "未知=矿石*1",
        "代采=矿石*1,代采=矿石*2",
        "代采*矿石*5",
    ):
        r = parse_task_spec(bad)
        assert r["ok"] is False, bad
        assert r["reason"] == "invalid_spec", bad


# ---------------------------------------------------------------------------
# GU-62 职业门槛（≥ 精通）与助手表
# ---------------------------------------------------------------------------
def test_assign_rejects_not_proficient():
    """非精通（档位 1 = 正式 / 无建档）→ 拒 level_insufficient，状态零写入。"""
    eng = _engine()
    for lv in (None, 0, 1):
        ctx = make_ctx(prof_level=lv, inventory={"candy": 1})
        r = eng.assign(ctx, ctx, "小助手", gather="矿石*5")
        assert r["ok"] is False
        assert r["reason"] == "level_insufficient"
        assert "等级不足" in r["message"]
        assert ctx["helpers"] == {}


def test_assign_rejects_unknown_assistant():
    """helpers[] 配置非空且助手不在表内 → 拒 assistant_not_found。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    r = eng.assign(ctx, ctx, "路人甲", gather="矿石*5")
    assert r["ok"] is False
    assert r["reason"] == "assistant_not_found"
    assert ctx["helpers"] == {}


def test_assign_allows_any_name_when_no_helper_table():
    """helpers[] 空 → 任意助手名可用（默认系数 1.0，B-5）。"""
    eng = _engine(NO_HELPERS_SETTINGS)
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    r = eng.assign(ctx, ctx, "散工", gather="矿石*5")
    assert r["ok"] is True
    assert r["assistant"] == "散工"
    assert ctx["helpers"]["散工"]["config"]["gather"]["count"] == 5


def test_assign_rejects_no_task():
    """gather/craft 均缺 → 拒 no_task。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    r = eng.assign(ctx, ctx, "小助手")
    assert r["ok"] is False
    assert r["reason"] == "no_task"
    assert ctx["helpers"] == {}


def test_assign_rejects_recipe_not_found():
    """代调配方不存在 → 拒 recipe_not_found，且未消耗能源（先配方校验后扣能源）。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    r = eng.assign(ctx, ctx, "小助手", craft="不存在的配方*1")
    assert r["ok"] is False
    assert r["reason"] == "recipe_not_found"
    assert ctx["inventory"]["candy"] == 1  # 能源未扣


def test_assign_rejects_module_disabled():
    """assistant.enabled=false → 整模块拒 module_disabled（ASST-01）。"""
    eng = _engine({"assistant": {"enabled": False}})
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    r = eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    assert r["ok"] is False
    assert r["reason"] == "module_disabled"


# ---------------------------------------------------------------------------
# GU-63 能源道具（消耗 / 缺能源拒绝 / 配置序回退）
# ---------------------------------------------------------------------------
def test_assign_consumes_energy_item():
    """精通玩家设定代采+代调 → 消耗糖果×1、状态存档、消息纯文本（M-22 降级）。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    spec = parse_task_spec("代采=矿石*5,代调=药剂*2")
    r = eng.assign(ctx, ctx, "小助手", gather=spec["gather"], craft=spec["craft"])
    assert r["ok"] is True
    assert ctx["inventory"]["candy"] == 0  # 糖果×1 消耗
    assert r["energy_item"] == "candy"
    assert r["energy_item_name"] == "糖果"
    # 状态存档（助手名/配置/启动时间/产出队列）
    entry = ctx["helpers"]["小助手"]
    assert entry["assistant"] == "小助手"
    assert entry["config"]["gather"] == {"target": "矿石", "item_id": "iron_ore", "count": 5}
    assert entry["config"]["craft"] == {
        "target": "药剂", "count": 2, "item": "potion", "item_count": 1,
    }
    assert entry["started_at"] == T0
    assert entry["queue"] == {}
    # 消息：M-22 纯文本（B-9 无 emoji）
    assert r["message"] == "小助手 开始代采 矿石*5，代调 药剂*2（消耗 糖果×1）"
    assert "📦" not in r["message"] and "⚒" not in r["message"]


def test_assign_rejects_no_energy_item():
    """背包无能源道具 → 拒 no_energy_item，状态零写入。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={})
    r = eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    assert r["ok"] is False
    assert r["reason"] == "no_energy_item"
    assert "缺少能源道具" in r["message"]
    assert ctx["helpers"] == {}


def test_assign_energy_item_fallback_order():
    """energy_items 配置序回退：无糖果有馅饼 → 消耗馅饼（id pie，显示名 馅饼）。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"pie": 1})
    r = eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    assert r["ok"] is True
    assert r["energy_item"] == "pie"
    assert r["energy_item_name"] == "馅饼"
    assert ctx["inventory"].get("pie", 0) == 0


# ---------------------------------------------------------------------------
# F-22 / ASST-04 tick 后台产出（离线累积 + 余数顺延）
# ---------------------------------------------------------------------------
def test_tick_produces_by_cycle():
    """代采=矿石*5、代调=药剂*2，tick_sec=1800：2 周期 → 矿石×10、药剂×4。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5", craft="药剂*2")
    r = eng.tick(ctx, ctx, now=T0 + 3600)  # 2 周期
    assert r["ok"] is True
    assert r["total_ticks"] == 2
    assert r["produced"] == {"小助手": {"iron_ore": 10, "potion": 4}}
    entry = ctx["helpers"]["小助手"]
    assert entry["queue"] == {"iron_ore": 10, "potion": 4}
    assert entry["config"]["produced_total"] == 14
    assert entry["last_tick_at"] == T0 + 3600  # 2×1800 顺延，余数 0


def test_tick_offline_accumulate_and_remainder():
    """离线累积：4500s = 2 周期 + 余 900s；再 +900s 仍无新周期（余数顺延不丢不重）。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    r = eng.tick(ctx, ctx, now=T0 + 4500)
    assert r["total_ticks"] == 2
    assert ctx["helpers"]["小助手"]["queue"]["iron_ore"] == 10
    assert ctx["helpers"]["小助手"]["last_tick_at"] == T0 + 3600
    # 再 +900s（累计 5400s = 3 周期）→ 再产 1 周期
    r2 = eng.tick(ctx, ctx, now=T0 + 5400)
    assert r2["total_ticks"] == 1
    assert ctx["helpers"]["小助手"]["queue"]["iron_ore"] == 15


def test_tick_no_elapsed_no_produce():
    """tick 未到周期 → 零产出、last_tick_at 不变。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    r = eng.tick(ctx, ctx, now=T0 + 1799)
    assert r["total_ticks"] == 0
    assert ctx["helpers"]["小助手"]["queue"] == {}


def test_tick_craft_output_count_multiplier():
    """代调=灵药*1（output.count=2）→ 2 周期产 灵药×4（output.count × config.count × ticks）。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", craft="灵药*1")
    r = eng.tick(ctx, ctx, now=T0 + 3600)
    assert r["produced"]["小助手"]["elixir"] == 4  # 2×1×2


def test_tick_no_helpers_is_noop():
    """无任何助手 → {ok: True, produced: {}, total_ticks: 0}。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2)
    r = eng.tick(ctx, ctx, now=T0)
    assert r["ok"] is True
    assert r["produced"] == {}
    assert r["total_ticks"] == 0


# ---------------------------------------------------------------------------
# /收取（F-22 / ASST-06）：入包 + 队列清空
# ---------------------------------------------------------------------------
def test_collect_to_inventory_and_clear():
    """收取：矿石×10、药剂×4 一次入包、队列清空、消息纯文本「收取：矿石×10、药剂×4」。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5", craft="药剂*2")
    eng.tick(ctx, ctx, now=T0 + 3600)
    r = eng.collect(ctx, ctx)
    assert r["ok"] is True
    assert ctx["inventory"]["iron_ore"] == 10
    assert ctx["inventory"]["potion"] == 4
    assert r["message"] == "收取：矿石×10、药剂×4"
    assert "📦" not in r["message"]  # B-9 无 emoji
    assert ctx["helpers"]["小助手"]["queue"] == {}  # 队列清空
    # 等级随累计产出提升，收取不清零 produced_total（B-7 只升不降）
    assert ctx["helpers"]["小助手"]["config"]["produced_total"] == 14
    assert r["last_collect_at"] is not None


def test_collect_empty_queue_rejected():
    """无待收产出 → 拒 queue_empty。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2)
    r = eng.collect(ctx, ctx)
    assert r["ok"] is False
    assert r["reason"] == "queue_empty"
    assert "没有待收取" in r["message"]


def test_collect_after_empty_then_repeat():
    """第二次收取（队列已空）→ 拒 queue_empty。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    eng.tick(ctx, ctx, now=T0 + 1800)
    assert eng.collect(ctx, ctx)["ok"] is True
    r = eng.collect(ctx, ctx)
    assert r["ok"] is False
    assert r["reason"] == "queue_empty"


# ---------------------------------------------------------------------------
# ASST-05 队列容量 / 重设语义
# ---------------------------------------------------------------------------
def test_assign_queue_full_rejected():
    """max_slots=1：队列已有 矿石 → 新任务 草药 并入超限 → 拒 queue_full；已产出项保留。"""
    eng = _engine(SINGLE_SLOT_SETTINGS)
    ctx = make_ctx(prof_level=2, inventory={"candy": 2}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    eng.tick(ctx, ctx, now=T0 + 1800)
    r = eng.assign(ctx, ctx, "小助手", gather="草药*5")
    assert r["ok"] is False
    assert r["reason"] == "queue_full"
    assert ctx["helpers"]["小助手"]["queue"] == {"iron_ore": 5}  # 已产出项保留
    assert ctx["inventory"]["candy"] == 1  # 未再扣能源


def test_assign_reassign_preserves_queue_and_total():
    """重设同助手：队列/终身累计保留，started_at 刷新。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 3}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    eng.tick(ctx, ctx, now=T0 + 1800)
    entry = ctx["helpers"]["小助手"]
    old_total = entry["config"]["produced_total"]
    assert old_total == 5
    ctx["now"] = T0 + 100  # 重设时钟推进（B-8）
    r = eng.assign(ctx, ctx, "小助手", craft="药剂*2")
    assert r["ok"] is True
    entry = ctx["helpers"]["小助手"]
    assert entry["queue"] == {"iron_ore": 5}  # 已产出保留
    assert entry["config"]["produced_total"] == old_total  # 终身累计保留
    assert entry["config"]["craft"] == {
        "target": "药剂", "count": 2, "item": "potion", "item_count": 1,
    }
    assert entry["started_at"] == T0 + 100  # 重设刷新启动时间


# ---------------------------------------------------------------------------
# ASST-07 助手等级提升（L464 特性更多 / 采集品质更高）
# ---------------------------------------------------------------------------
def test_level_of_base_and_growth():
    """等级随累计产出提升：低阈值引擎 [0,10,30,60]，产 15 → 2 级。"""
    eng = _engine(LOW_THRESHOLD_SETTINGS)
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    assert eng.level_of(ctx, "小助手") == 1  # 未建档 → 1
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    assert eng.level_of(ctx, "小助手") == 1
    eng.tick(ctx, ctx, now=T0 + 1800 * 3)  # 3 周期 → 15 累计
    assert eng.level_of(ctx, "小助手") == 2


def test_level_bonus_matches_level():
    """等级加成 = (level-1) × 每级加成；lvl1 零加成，lvl2 → trait+1 / quality+5。"""
    eng = _engine(LOW_THRESHOLD_SETTINGS)
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5")
    assert eng.level_bonus(ctx, "小助手") == {"level": 1, "trait_bonus": 0, "quality_bonus": 0}
    eng.tick(ctx, ctx, now=T0 + 1800 * 3)
    b = eng.level_bonus(ctx, "小助手")
    assert b["level"] == 2
    assert b["trait_bonus"] == 1  # (2-1)×1
    assert b["quality_bonus"] == 5  # (2-1)×5


def test_level_thresholds_default_constant():
    """默认成长阈值 = (0,100,300,700,1500)（B-7 缺省兜底）。"""
    assert list(DEFAULT_LEVEL_THRESHOLDS) == [0, 100, 300, 700, 1500]


# ---------------------------------------------------------------------------
# 状态存档（F-22 / L403）：config/started_at/queue 完整可重载
# ---------------------------------------------------------------------------
def test_state_persist_full_shape():
    """存档重载语义：helpers 完整结构（assistant/config/queue 等）可重载继续。"""
    eng = _engine()
    ctx = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    eng.assign(ctx, ctx, "小助手", gather="矿石*5", craft="药剂*2")
    eng.tick(ctx, ctx, now=T0 + 3600)
    state = copy.deepcopy(ctx["helpers"])  # 模拟持久化 → 重载
    ctx2 = make_ctx(prof_level=2, inventory={"candy": 1}, now=T0)
    ctx2["helpers"] = state
    # 重载后继续 tick + 收取
    eng2 = _engine()
    r = eng2.tick(ctx2, ctx2, now=T0 + 5400)  # 余 1800 → 再 1 周期
    assert r["produced"]["小助手"]["iron_ore"] == 5
    r2 = eng2.collect(ctx2, ctx2)
    assert r2["ok"] is True
    assert ctx2["inventory"]["iron_ore"] == 15
    assert ctx2["inventory"]["potion"] == 6
    assert ctx2["helpers"]["小助手"]["queue"] == {}
