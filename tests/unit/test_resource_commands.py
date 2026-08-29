"""资源循环指令壳单测（M8 批10-2 · alchemy_commands.py 的 /种植 /收获 /代工 /收取）。

文件：tests/unit/test_resource_commands.py
创建：2026-08-29
作者：Hermes 子agent-10-2
功能：cmd_plant / cmd_harvest / cmd_helper / cmd_collect 异步直测（守卫→引擎→透传，真实
  HarvestEngine / HelperEngine 消费 + 真实 ctx 玩家状态）。TC-29（种植/收获：正式成功 /
  未成熟收获拒绝 / 收获品质≥种子+继承特性 / 见习拒绝）+ TC-30（代工：精通设定 键值列表
  原例解析 消耗能源道具 / 缺能源拒绝 / tick 后台产出 / 收取入包+队列清空 / 非精通拒绝）。
  每条正例 + 反例，断言精确文本/数值/存档。

依据：
  - docs/m8_contract_指令契约.md §20（/种植 /收获：GU-60/61、F-21、M-21、TC-29）+ §21
    （/代工：P-22/SEP-22 键值列表、GU-62/63、F-22、M-22、TC-30；收取用 /收取）——
    2026-08-28 用户拍板指令名改用「代工」。
  - docs/细化/细化_2c5c_种植品评代工.md（FARM-01~10 / ASST-01~09 + TC-01~08/16~20）
  - qbot_rpg/core/alchemy_harvest.py（H-1~H-9）+ qbot_rpg/core/alchemy_helper.py（B-1~B-11）

测试风格对齐 tests/unit/test_alchemy_commands.py（parse_command 直调 + 全字段 ctx）+ 
tests/unit/test_alchemy_harvest.py / test_alchemy_helper.py（引擎夹具形态）；asyncio_mode=auto
直接 await。

【工程补白 · 注记】
  - 白名单：/种植 /收获 /收取 不在 parsers.DEFAULT_WHITELIST（/代工 已在），测试显式传
    whitelist=WHITELIST 扩充——真实白名单补齐归批11 路11A 装配职责（IF-34）。
  - 时钟：ctx["now"] = T0 注入（壳层 _clock_of 优先读取），tick 用显式 now 参数（B-8），
    与墙钟解耦保证确定性。
  - tick 为后台调度职责（批11 装配），指令层无 /触发——测试用 HelperEngine.tick 直调模拟
    后台产出后走 /收取 指令验证入包+清空。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.commands.alchemy_commands import (
    COLLECT_CMD,
    HARVEST_CMD,
    HELPER_CMD,
    PLANT_CMD,
    cmd_collect,
    cmd_harvest,
    cmd_helper,
    cmd_plant,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.core.alchemy_helper import HelperEngine
from qbot_rpg.core.alchemy_harvest import DEFAULT_HARVEST_SEC

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

ITEMS: Dict[str, Mapping[str, Any]] = {
    # 收获表形态种子（H-1：seed: {output, quality_floor, traits}；/种植 番茄种子 按名命中）
    "tomato_seed": {
        "id": "tomato_seed", "name": "番茄种子", "type": "种子", "price": 20,
        "seed": {"output": "tomato", "quality_floor": 40,
                 "traits": ["trait_sweet", "trait_fresh"]},
    },
    "tomato": {"id": "tomato", "name": "番茄", "type": "material", "price": 10},
    # 简单形态种子（H-1：seed: true；收获=种子自身 品质/特性取种子字段）
    "fire_herb_seed": {
        "id": "fire_herb_seed", "name": "火焰草种子", "type": "种子", "price": 50,
        "seed": True, "quality": 50, "traits": ["trait_burn_boost"],
    },
    # 非种子素材（GU-61a 反例）
    "herb": {"id": "herb", "name": "草药", "type": "material", "price": 5},
    # 代工材料（B-3 能源道具 + 代采目标）
    "candy": {"id": "candy", "name": "糖果", "type": "material"},
    "pie": {"id": "pie", "name": "馅饼", "type": "material"},
    "iron_ore": {"id": "iron_ore", "name": "矿石", "type": "material"},
    "potion": {"id": "potion", "name": "药剂", "type": "consumable"},
}

TRAITS: Dict[str, Mapping[str, Any]] = {
    "trait_sweet": {"id": "trait_sweet", "name": "甘甜", "rarity": "normal"},
    "trait_fresh": {"id": "trait_fresh", "name": "鲜嫩", "rarity": "normal"},
    "trait_burn_boost": {"id": "trait_burn_boost", "name": "灼烧强化", "rarity": "normal"},
}

RECIPES: Dict[str, Mapping[str, Any]] = {
    # 代调=药剂*2：配方名「药剂」按 name 精确命中（P-22）；output 药剂×1
    "rcp_potion": {
        "id": "rcp_potion", "name": "药剂", "kind": "craft", "level": 1,
        "output": {"item": "potion", "count": 1}, "materials": [], "cost": {},
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "farming": {
            "enabled": True,
            "harvest_sec": DEFAULT_HARVEST_SEC,
            "plots_max": 3,
            "trait_inherit": {"正式": 1, "精通": 2, "专家": 3},
            "greenhouse": {"unlock_tier": "大师", "copy_cost": {"gem": 10, "gold": 1000}},
        },
    },
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

# 白名单扩充（/代工 已在 DEFAULT_WHITELIST；/种植 /收获 /收取 补齐——批11 装配 IF-34）
WHITELIST = frozenset(DEFAULT_WHITELIST | {"种植", "收获", "收取"})

# 固定时钟（B-8：壳层 _clock_of 优先读 ctx["now"]；tick 显式传 now）
T0 = 1_700_000_000


def make_ctx(
    prof_level: Optional[int] = 2,
    inventory: Optional[Mapping[str, int]] = None,
    now: Optional[int] = T0,
    **over: Any,
) -> MutableMapping[str, Any]:
    """全字段资源循环 ctx（每场景新造避免互污染；prof_level = 档位索引 0~6）。

    prof_level = 炼金职业档位（1=正式 种植解锁 / 2=精通 代工解锁；None → 无建档=见习）。
    now = 时钟注入（壳层 _clock_of 优先；None → 墙钟兜底）。
    """
    base: Dict[str, Any] = {
        "qid": "u1",
        "name": "阿伟",
        "proficiency": (
            {"alchemy": {"level": prof_level, "exp": 0}} if prof_level is not None else {}
        ),
        "inventory": dict(inventory) if inventory else {},
        "items": ITEMS,
        "traits": TRAITS,
        "recipe": RECIPES,
        "settings": DEFAULT_SETTINGS,
        "helpers": {},
        "now": now,
    }
    base.update(over)
    return base


def _p(raw: str):
    """parse_command（扩充白名单，/代工 键值列表原例语法）。"""
    return parse_command(raw, whitelist=WHITELIST)


# ---------------------------------------------------------------------------
# TC-29 /种植：GU-60 正式解锁 · GU-61 种子校验 · F-21 地块存档
# ---------------------------------------------------------------------------
async def test_plant_formal_ok() -> None:
    """TC-29 正例：正式玩家 /种植 番茄种子 → 透传「已种植〈番茄种子〉，4 小时后可收获」。

    地块占用（harvest_at=now+14400）、消耗 1 颗种子、消息 M5 纯文本零 emoji。
    """
    ctx = make_ctx(prof_level=1, inventory={"tomato_seed": 3})
    out = await cmd_plant(_p("/种植 番茄种子"), ctx)
    assert out == "已种植〈番茄种子〉，4 小时后可收获"
    assert "🌱" not in out
    # F-21 数据落点（player.farm_plots dict）+ FARM-01 消耗 1 种子
    assert ctx["farm_plots"][1] == {
        "seed": "tomato_seed", "planted_at": T0, "harvest_at": T0 + DEFAULT_HARVEST_SEC,
    }
    assert ctx["inventory"]["tomato_seed"] == 2


async def test_plant_apprentice_rejected() -> None:
    """TC-29 反例：见习（tier 0）/种植 → 壳层 GU-60 拒绝「❌ 等级不足…正式」，零写入。"""
    ctx = make_ctx(prof_level=0, inventory={"tomato_seed": 3})
    out = await cmd_plant(_p("/种植 番茄种子"), ctx)
    assert out == "❌ 等级不足：炼金职业需达到 正式（种植解锁）"
    assert "farm_plots" not in ctx
    assert ctx["inventory"]["tomato_seed"] == 3  # 未消耗


async def test_plant_no_args_tpl12() -> None:
    """P-21 反例：/种植 缺参 → TPL-12（❌ 指令不正确）。"""
    out = await cmd_plant(_p("/种植"), make_ctx(prof_level=1))
    assert "指令不正确" in out


async def test_plant_seed_not_found_rejected() -> None:
    """TC-29 反例：种子不存在 / 非种子物品 → 透传引擎 seed_not_found 提示。"""
    ctx = make_ctx(prof_level=1, inventory={"tomato_seed": 3})
    out1 = await cmd_plant(_p("/种植 不存在的种子"), ctx)
    assert "种子不存在" in out1
    # 存在但无 seed 标记（GU-61：种子存在且带 seed 标记）
    out2 = await cmd_plant(_p("/种植 草药"), ctx)
    assert "未找到带 seed 标记的物品" in out2


async def test_plant_seed_missing_inventory_rejected() -> None:
    """GU-61/H-6 反例：背包无种子道具 → 透传「背包中没有〈番茄种子〉，无法种植」。"""
    ctx = make_ctx(prof_level=1, inventory={})
    out = await cmd_plant(_p("/种植 番茄种子"), ctx)
    assert "背包中没有〈番茄种子〉，无法种植" in out
    assert "farm_plots" not in ctx


# ---------------------------------------------------------------------------
# TC-29 /收获：GU-60 · F-21 未成熟拒绝 / 到点收获（品质≥种子+继承特性）/ 入包清空
# ---------------------------------------------------------------------------
async def test_harvest_apprentice_rejected() -> None:
    """TC-29 反例：见习 /收获 → 壳层 GU-60 拒绝「❌ 等级不足…收获」。"""
    out = await cmd_harvest(_p("/收获"), make_ctx(prof_level=0))
    assert out == "❌ 等级不足：炼金职业需达到 正式（收获解锁）"


async def test_harvest_immature_rejected() -> None:
    """TC-29 正例前半：种植后未到 harvest_at → /收获 透传「作物还未成熟」，地块保留。"""
    ctx = make_ctx(prof_level=1, inventory={"tomato_seed": 3})
    await cmd_plant(_p("/种植 番茄种子"), ctx)
    out = await cmd_harvest(_p("/收获"), ctx)
    assert "作物还未成熟" in out
    assert len(ctx["farm_plots"]) == 1  # 未误清空


async def test_harvest_ok_quality_floor_and_traits() -> None:
    """TC-29 正例：到点 /收获 → 收获品质≥种子品质 40（精良）+ 继承特性（正式 1 项）+ 入包清空。

    折叠单条消息（RATE-05）：「收获〈番茄〉×1（品质 精良·继承特性：甘甜）
    （超出继承上限丢弃：鲜嫩）」。"""
    ctx = make_ctx(prof_level=1, inventory={"tomato_seed": 3})
    await cmd_plant(_p("/种植 番茄种子"), ctx)
    ctx["now"] = T0 + DEFAULT_HARVEST_SEC
    out = await cmd_harvest(_p("/收获"), ctx)
    assert "收获〈番茄〉×1（品质 精良·继承特性：甘甜）" in out
    assert "超出继承上限丢弃：鲜嫩" in out          # FARM-03 超出丢弃提示
    assert "🌾" not in out                          # M5 纯文本
    # F-21 入包 + 地块清空（FARM-06/10）
    assert ctx["inventory"]["tomato"] == 1
    assert ctx["farm_plots"] == {}


async def test_harvest_all_mature_plots_folded() -> None:
    """F-21 正例：多地块成熟 → /收获 无参收全部，折叠单条消息（RATE-05）。"""
    ctx = make_ctx(prof_level=3, inventory={"tomato_seed": 3, "fire_herb_seed": 2})
    await cmd_plant(_p("/种植 番茄种子"), ctx)
    await cmd_plant(_p("/种植 火焰草种子"), ctx)
    ctx["now"] = T0 + DEFAULT_HARVEST_SEC
    out = await cmd_harvest(_p("/收获"), ctx)
    assert "收获〈番茄〉×1" in out and "收获〈火焰草种子〉×1" in out
    assert ctx["inventory"]["tomato"] == 1
    assert ctx["farm_plots"] == {}


async def test_harvest_no_plots_rejected() -> None:
    """F-21 反例：无任何种植地块 → /收获 透传「还没有种植任何作物」。"""
    out = await cmd_harvest(_p("/收获"), make_ctx(prof_level=1))
    assert "还没有种植任何作物" in out


# ---------------------------------------------------------------------------
# TC-30 /代工：GU-62 精通 · 键值列表原例解析 · GU-63 能源道具 · F-22 状态存档
# ---------------------------------------------------------------------------
async def test_helper_proficient_ok() -> None:
    """TC-30 正例：精通玩家 /代工 小助手 代采=矿石*5,代调=药剂*2（键值列表原例）。

    → 消耗 糖果×1、状态存档、消息纯文本「小助手 开始代采 矿石*5，代调 药剂*2（消耗 糖果×1）」。
    """
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    out = await cmd_helper(_p("/代工 小助手 代采=矿石*5,代调=药剂*2"), ctx)
    assert out == "小助手 开始代采 矿石*5，代调 药剂*2（消耗 糖果×1）"
    assert "⚒" not in out and "📦" not in out      # M-22 降级纯文本（B-9）
    assert ctx["inventory"]["candy"] == 0           # GU-63 消耗 糖果×1
    # F-22 状态存档（助手名/配置/启动时间/产出队列）
    entry = ctx["helpers"]["小助手"]
    assert entry["config"]["gather"] == {"target": "矿石", "item_id": "iron_ore", "count": 5}
    assert entry["config"]["craft"] == {
        "target": "药剂", "count": 2, "item": "potion", "item_count": 1,
    }
    assert entry["started_at"] == T0 and entry["queue"] == {}


async def test_helper_no_energy_rejected() -> None:
    """GU-63 反例：背包无能源道具 → 透传「缺少能源道具」，状态零写入。"""
    ctx = make_ctx(prof_level=2, inventory={})
    out = await cmd_helper(_p("/代工 小助手 代采=矿石*5"), ctx)
    assert "缺少能源道具" in out
    assert ctx["helpers"] == {}


async def test_helper_not_proficient_rejected() -> None:
    """GU-62 反例：非精通（正式/无建档）→ 壳层拒绝「❌ 等级不足：代工助手需炼金职业 ≥ 精通」。"""
    for lv in (None, 0, 1):
        ctx = make_ctx(prof_level=lv, inventory={"candy": 1})
        out = await cmd_helper(_p("/代工 小助手 代采=矿石*5"), ctx)
        assert out == "❌ 等级不足：代工助手需炼金职业 ≥ 精通"
        assert ctx["helpers"] == {} and ctx["inventory"]["candy"] == 1


async def test_helper_no_args_tpl12() -> None:
    """P-22 反例：/代工 缺参 → TPL-12（❌ 指令不正确）。"""
    out = await cmd_helper(_p("/代工"), make_ctx(prof_level=2))
    assert "指令不正确" in out


async def test_helper_no_task_rejected() -> None:
    """F-22 反例：/代工 小助手 无键值列表 → 透传引擎 no_task「请指定 代采 或 代调 任务…」。"""
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    out = await cmd_helper(_p("/代工 小助手"), ctx)
    assert "请指定 代采 或 代调 任务" in out
    assert ctx["helpers"] == {} and ctx["inventory"]["candy"] == 1  # 未消耗


async def test_helper_recipe_not_found_rejected() -> None:
    """TC-30 反例：代调配方不存在 → 透传「代调配方不存在」，能源未扣（先配方后扣能源）。"""
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    out = await cmd_helper(_p("/代工 小助手 代调=不存在的配方*1"), ctx)
    assert "代调配方不存在" in out
    assert ctx["inventory"]["candy"] == 1


async def test_helper_invalid_spec_rejected() -> None:
    """P-22/SEP-22 反例：非法键值（数量非正整）→ 透传 parse_task_spec 拒绝「任务数量非法」。"""
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    out = await cmd_helper(_p("/代工 小助手 代采=矿石*0"), ctx)
    assert "任务数量非法" in out
    assert ctx["helpers"] == {}


# ---------------------------------------------------------------------------
# TC-30 /收取：后台 tick 产出（HelperEngine 直调模拟）→ 指令收取入包+队列清空
# ---------------------------------------------------------------------------
async def test_tick_then_collect_ok() -> None:
    """TC-30 正例：设定 代采=矿石*5,代调=药剂*2 → tick 2 周期（矿石×10/药剂×4）→
    /收取 → 「收取：矿石×10、药剂×4」入包 + 队列清空。

    tick 为后台调度职责（批11 装配），此处用真实 HelperEngine.tick 直调模拟后台产出。
    """
    ctx = make_ctx(prof_level=2, inventory={"candy": 1})
    await cmd_helper(_p("/代工 小助手 代采=矿石*5,代调=药剂*2"), ctx)
    eng = HelperEngine(settings=DEFAULT_SETTINGS)
    r = eng.tick(ctx, ctx, now=T0 + 3600)  # 2 周期（tick_sec=1800）
    assert r["ok"] is True and r["total_ticks"] == 2
    out = await cmd_collect(_p("/收取"), ctx)
    assert out == "收取：矿石×10、药剂×4"
    assert "📦" not in out                       # M-22 降级纯文本（B-9）
    assert ctx["inventory"]["iron_ore"] == 10    # 入包（F-22/ASST-06）
    assert ctx["inventory"]["potion"] == 4
    assert ctx["helpers"]["小助手"]["queue"] == {}  # 队列清空


async def test_collect_empty_queue_rejected() -> None:
    """TC-30 反例：无待收产出 → /收取 透传「当前没有待收取的代工产出」（空队列提示）。"""
    out = await cmd_collect(_p("/收取"), make_ctx(prof_level=2))
    assert "当前没有待收取的代工产出" in out


# ---------------------------------------------------------------------------
# 装配：register_alchemy_commands 注册 4 指令 + k.get("ctx") 注入
# ---------------------------------------------------------------------------
async def test_register_resource_commands() -> None:
    """装配：register_alchemy_commands 注册 种植/收获/代工/收取 四条 CommandSpec。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: dict(make_ctx()))
    for cmd in (PLANT_CMD, HARVEST_CMD, HELPER_CMD, COLLECT_CMD):
        assert router.has(cmd)
        spec = router.get(cmd)
        assert spec is not None and spec.whitelisted
    assert {PLANT_CMD, HARVEST_CMD, HELPER_CMD, COLLECT_CMD} <= set(router.names())


async def test_register_handlers_injectable_ctx() -> None:
    """装配：handler 支持 k.get("ctx") 注入（async 处理器 await 执行，runner 口径）。"""
    router = Router()
    ctx = make_ctx(prof_level=1, inventory={"tomato_seed": 2})
    register_alchemy_commands(router, make_context=lambda p: {})
    spec = router.get(PLANT_CMD)
    assert spec is not None and spec.handler is not None
    out = await spec.handler(_p("/种植 番茄种子"), ctx=ctx)
    assert "已种植〈番茄种子〉，4 小时后可收获" in out
