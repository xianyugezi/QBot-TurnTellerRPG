"""炼金指令壳单测（M8 批2·路2A · qbot_rpg/commands/alchemy_commands.py）。

文件名：tests/unit/test_synthesis_commands.py
创建时间：2026-08-29
作者：Hermes 子agent-2A
功能描述：cmd_synthesis + register_alchemy_commands 纯函数直测（仿 test_shop_commands 模式）：
  成功路径渲染 / 缺材料差异 / 深度拒绝 / 等级不足 / 超限提示不拦 / TPL-12 / 注册与解析接线 /
  零装饰 emoji。

集成口径：直接驱动**真实引擎** qbot_rpg/core/synthesis.py（批2 路2A 已落盘），构造全字段 ctx
  （items/recipe/settings/currencies/proficiency/inventory），断言命令层输出。引擎配置单源：
  cmd_synthesis 以 ctx["settings"] 构造 SynthesisEngine（对齐 shell 工程补白 1）。

覆盖：/合成 成功（单件/批量 ×N / M-01 文案）· 缺材料差异 · 深度拒绝（synth_allowed=false）·
  等级不足（无职业）· 超限提示不拦 · /合成 缺参 → TPL-12 · 未知配方 · 注册（Router.has/names）·
  无 make_context → RuntimeError · parse_command 集成（qty/序号）· 零装饰 emoji。

依据：
  - docs/m8_contract_指令契约.md §1 /合成（GU-01~04/F-01/M-01）+ §六 IF 清单（cmd_synth 壳签名 /
    register_alchemy_commands 装配）+ §3.4（max_qty 注入属批11，壳层只透传引擎 advisory）。
  - tests/unit/test_shop_commands.py（纯函数单测模式：make_ctx 全字段构造 + parse_command 直调）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.alchemy_commands import (
    SYNTH_CMD,
    cmd_synthesis,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.core.synthesis import DEFAULT_MAX_QTY

# ---------------------------------------------------------------------------
# 夹具（对齐 core/synthesis.py ctx 契约 + shop 壳层 settings 桶）
# ---------------------------------------------------------------------------

ITEMS = {
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable"},
    "deep_core": {"id": "deep_core", "name": "秘银核心", "type": "material"},
}

RECIPES = {
    "rcp_mana_potion": {
        "id": "rcp_mana_potion", "name": "魔力药水配方", "kind": "craft", "level": 5,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2}],
        "output": {"item": "mana_potion", "count": 1},
        "cost": {"coins": 30, "gem": 0},
    },
    "rcp_flame_bomb": {
        "id": "rcp_flame_bomb", "name": "火焰弹配方", "kind": "craft", "level": 31,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "moon_grass", "count": 3}],
        "output": {"item": "flame_bomb", "count": 1},
        "cost": {"coins": 200, "gem": 0},
    },
    "rcp_deep": {
        "id": "rcp_deep", "name": "深度秘银配方", "kind": "craft", "level": 31,
        "synth_allowed": False, "master_only": True,
        "materials": [{"id": "deep_core", "count": 2}],
        "output": {"item": "deep_core", "count": 1},
        "cost": {"coins": 0, "gem": 0},
    },
}

SETTINGS = {
    "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
    "alchemy": {
        "mode": "full",
        "max_qty": DEFAULT_MAX_QTY,
        "job_tier_map": {
            "见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99],
        },
    },
}


def make_ctx(**over):
    """全字段玩家合成 ctx（含 settings 桶；cmd_synthesis 以 ctx["settings"] 构造引擎）。"""
    base = {
        "qid": "u1",
        "name": "阿伟",
        "proficiency": {"fishing": {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0,
                                    "unlocks": {}}},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"water_crystal": 20, "herb": 10},
        "items": ITEMS,
        "recipe": RECIPES,
        "settings": SETTINGS,
    }
    base.update(over)
    return base


def _fishing(level: int = 0, exp: int = 0) -> dict:
    """钓鱼职业节点（level = 档位索引 0~6；4=大师 31-40）。"""
    return {"fishing": {"level": level, "exp": exp, "sp_earned": 0, "sp_used": 0, "unlocks": {}}}


def parse(raw: str):
    """parse_command 封装（合成 已在 DEFAULT_WHITELIST +
    DEFAULT_QUANTITY_COMMANDS，parsers.py L112/149）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# /合成 成功路径（M-01 文案 / 批量 / 熟练入账）
# ---------------------------------------------------------------------------
def test_synthesis_ok_single():
    """M-01：/合成 魔力药水配方 → ✅ 魔力药水 ×1（消耗：水结晶×5 + 草药×2 + 金币 30）。"""
    out = cmd_synthesis(parse("/合成 魔力药水配方"), make_ctx())
    assert out == "✅ 魔力药水 ×1（消耗：水结晶×5 + 草药×2 + 金币 30）"


def test_synthesis_ok_batch():
    """/合成 魔力药水配方*3 → 批量 ×3、消耗×3、熟练经验入账。"""
    ctx = make_ctx()
    out = cmd_synthesis(parse("/合成 魔力药水配方*3"), ctx)
    assert out == "✅ 魔力药水 ×3（消耗：水结晶×15 + 草药×6 + 金币 90）"
    assert ctx["inventory"]["mana_potion"] == 3
    assert ctx["inventory"]["water_crystal"] == 5   # 20 - 15
    assert ctx["currencies"]["coins"] == 910        # 1000 - 90
    assert ctx["proficiency"]["fishing"]["exp"] == 15  # 配方等级 5 × 3


def test_synthesis_ok_old_space_qty():
    """旧空格数量兼容：/合成 魔力药水配方 2 → qty=2。"""
    out = cmd_synthesis(parse("/合成 魔力药水配方 2"), make_ctx())
    assert out == "✅ 魔力药水 ×2（消耗：水结晶×10 + 草药×4 + 金币 60）"


def test_synthesis_ok_by_seq():
    """/合成 1 → 序号解析（注册表第一项=魔力药水配方）。"""
    out = cmd_synthesis(parse("/合成 1"), make_ctx())
    assert out.startswith("✅ 魔力药水 ×1")


# ---------------------------------------------------------------------------
# /合成 拒绝路径（缺料差异 / 深度 / 等级不足 / 未知配方 / 超限）
# ---------------------------------------------------------------------------
def test_synthesis_missing_materials_diff():
    """GU-04/TC-23：缺料全拒 + 差异提示（缺 水结晶×N + 草药×N + 金币 N），零副作用。"""
    ctx = make_ctx(inventory={"water_crystal": 3, "herb": 10}, currencies={"coins": 1000, "gem": 0})
    out = cmd_synthesis(parse("/合成 魔力药水配方"), ctx)
    assert "❌ 材料不足：缺 水结晶×2" in out
    assert "金币 30" not in out  # 金币充足不列差异
    assert ctx["inventory"]["water_crystal"] == 3  # 全拒不部分扣料
    assert ctx["proficiency"]["fishing"]["exp"] == 0


def test_synthesis_missing_coins_diff():
    """/合成 金币不足 → 差异提示含「金币 N」（全拒不部分执行）。"""
    ctx = make_ctx(currencies={"coins": 10, "gem": 0})
    out = cmd_synthesis(parse("/合成 魔力药水配方"), ctx)
    assert "缺 金币 20" in out
    assert ctx["currencies"]["coins"] == 10


def test_synthesis_deep_rejected():
    """GU-03/TC-07：深度配方 synth_allowed=false → 「深度未解锁」拒绝。"""
    ctx = make_ctx(proficiency=_fishing(4))  # 钓鱼大师但深度不可合成
    out = cmd_synthesis(parse("/合成 深度秘银配方"), ctx)
    assert "❌ 深度未解锁" in out


def test_synthesis_level_insufficient():
    """GU-02/TC-01：钓鱼专家（档位 3）→ 大师级配方（level 31）→ 等级不足并提示缺哪种职业。"""
    ctx = make_ctx(proficiency=_fishing(3))
    out = cmd_synthesis(parse("/合成 火焰弹配方"), ctx)
    assert "❌ 等级不足" in out
    assert "钓鱼" in out


def test_synthesis_no_job_reject():
    """TC-02：无任何职业 → 等级不足（未习得任何制造/资源职业）。"""
    ctx = make_ctx(proficiency={})
    out = cmd_synthesis(parse("/合成 魔力药水配方"), ctx)
    assert "❌ 等级不足" in out


def test_synthesis_unknown_recipe():
    """GU-02：配方不存在 → 引擎文案透传。"""
    out = cmd_synthesis(parse("/合成 不存在配方"), make_ctx())
    assert out == "❌ 配方不存在"


def test_synthesis_qty_cap_hint_not_block():
    """拍板⑤：max_qty=3 + 请求 10 → 提示「最多一次使用 3 个」不拦、按 3 截断执行成功。"""
    settings = {
        "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
        "alchemy": {"mode": "full", "max_qty": 3},
    }
    ctx = make_ctx(settings=settings, inventory={"water_crystal": 15, "herb": 6})
    out = cmd_synthesis(parse("/合成 魔力药水配方*10"), ctx)
    assert "✅ 魔力药水 ×3" in out
    assert "最多一次使用 3 个" in out
    assert ctx["inventory"]["mana_potion"] == 3


# ---------------------------------------------------------------------------
# /合成 参数错误 → TPL-12
# ---------------------------------------------------------------------------
def test_synthesis_missing_arg_tpl12():
    """/合成 缺参 → TPL-12 统一报错。"""
    out = cmd_synthesis(parse("/合成"), make_ctx())
    assert out == "❌ 指令不正确：/合成。输入 /帮助 查看可用指令。"


def test_synthesis_parse_error_tpl12():
    """解析 error（如非法参数）→ TPL-12。"""
    out = cmd_synthesis(parse("/合成 配方 1 2 3 4"), make_ctx())
    assert out.startswith("❌ 指令不正确：")


# ---------------------------------------------------------------------------
# 接线：Router 注册 / 无 make_context / 解析集成 / emoji 纪律
# ---------------------------------------------------------------------------
def test_register_alchemy_commands():
    """批11 路11A 装配入口：注册 /合成 CommandSpec（本批仅此一条）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: make_ctx())
    assert router.has(SYNTH_CMD)
    assert {SYNTH_CMD} <= set(router.names())
    assert router.get(SYNTH_CMD).whitelisted


def test_register_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入的显式错误）。"""
    router = Router()
    register_alchemy_commands(router)
    with pytest.raises(RuntimeError):
        router.get(SYNTH_CMD).handler(parse("/合成 魔力药水配方"))


def test_parse_command_integration():
    """解析接线：/合成 配方*N → args[0] 含原文、qty 结构化；数量缺省 1。"""
    p = parse("/合成 魔力药水配方*10")
    assert p.command == "合成" and p.args == ["魔力药水配方*10"] and p.qty == 10
    p = parse("/合成 魔力药水配方")
    assert p.command == "合成" and p.args == ["魔力药水配方"] and p.qty is None


def test_no_decorative_emoji():
    """3d §四 D-01：命令层渲染输出零装饰 emoji（仅 ✅/❌ 功能性标记允许）。"""
    outputs = [
        cmd_synthesis(parse("/合成 魔力药水配方"), make_ctx()),
        cmd_synthesis(parse("/合成 魔力药水配方*3"), make_ctx()),
        cmd_synthesis(parse("/合成 不存在配方"), make_ctx()),
        cmd_synthesis(parse("/合成 深度秘银配方"), make_ctx()),
    ]
    banned = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸⚗️🌱")
    for text in outputs:
        for ch in text:
            assert ch not in banned, f"命中禁用装饰 emoji：{ch} in {text!r}"
            assert ch in ("✅", "❌") or not (0x1F000 <= ord(ch) <= 0x1FAFF), \
                f"命中未登记 emoji：{ch} in {text!r}"
