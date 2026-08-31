"""/使用 指令测试（2026-08-28 用户拍板：装备穿戴统一用「使用」）。

承接 use_commands.py：注册门槛/战斗内拒绝/缺参/无物品/装备穿戴/消耗回血/不可使用。
风格照 test_register_commands.py（make_ctx + parse_command + BANNED_EMOJI 扫描）。

2026-08-31 模板配置化：文案断言改用 use_tpl 默认模板 key（不再依赖 use_commands 的
TPL_* 常量）；新增内容包覆盖 + 白名单外占位符原样保留测试。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router
from qbot_rpg.commands.use_commands import cmd_use, register_use_commands
from qbot_rpg.core.templates.use_tpl import DEFAULT_TEMPLATES as USE_TPL

BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")

# 本模块全部 use_* 模板 key（文案唯一源 use_tpl.py；渲染走 tpl_of）
USE_TPL_KEYS = (
    "use_in_battle", "use_no_arg", "use_no_item", "use_cannot_use", "use_bound", "use_ok",
)


def _fake_item(item_id: str, name: str, slot: str = "") -> Any:
    """假 ItemInstance（item_id/name/slot 字段；acquired_at 供排序）。"""
    return SimpleNamespace(
        item_id=item_id, name=name, slot=slot, acquired_at="2026-08-28 12:00:00",
    )


def make_ctx(**over: Any) -> dict:
    """已注册玩家基础 ctx（每场景新造；注入假引擎）。"""
    items_map = {
        "iron_sword": {"id": "iron_sword", "name": "铁剑", "slot": "weapon"},
        "heal_potion": {
            "id": "heal_potion", "name": "疗伤药", "type": "consumable",
            "usable": True, "effects": ["heal_small"],
        },
        "quest_token": {"id": "quest_token", "name": "任务信物", "type": "material"},
    }
    effects_map = {"heal_small": {"id": "heal_small", "type": "heal", "power": 50}}
    base = {
        "registered": True,
        "player": {
            "name": "测试勇士",
            "level": 1,
            "job_id": "warrior",
            "hp": 30,
            "inventory": [],
            "equipment": {},
            "attributes": {"base": {"hp": 100.0, "mp": 30.0}},
        },
        "items": items_map,
        "effect_table": effects_map,
        "equip_engine": SimpleNamespace(
            _sorted_inventory=lambda p: [_fake_item("iron_sword", "铁剑", "weapon"),
                                          _fake_item("heal_potion", "疗伤药")],
            equip_wear=lambda idx, ctx: {"ok": True, "message": "✅ 已装备：铁剑"},
        ),
        "inventory_engine": SimpleNamespace(
            remove_item=lambda p, item_id, count=1: {"ok": True},
        ),
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（白名单已含「使用」）。"""
    return parse_command(raw)


def test_use_not_registered_gate() -> None:
    """未注册 → TPL_REGISTER_GATE。"""
    ctx = make_ctx(registered=False, player=None)
    assert cmd_use(parse("/使用 1"), ctx) == "❌ 请先 /注册 创建角色（/注册 名字 职业）"


def test_use_in_battle_rejected() -> None:
    """战斗中 → use_in_battle。"""
    ctx = make_ctx(battle_session={"monster_id": "x"})
    assert cmd_use(parse("/使用 1"), ctx) == USE_TPL["use_in_battle"]


def test_use_no_arg() -> None:
    """缺参 → use_no_arg。"""
    ctx = make_ctx()
    assert cmd_use(parse("/使用"), ctx) == USE_TPL["use_no_arg"]


def test_use_no_item() -> None:
    """序号越界/名称未命中 → use_no_item。"""
    ctx = make_ctx()
    assert cmd_use(parse("/使用 99"), ctx) == USE_TPL["use_no_item"]
    assert cmd_use(parse("/使用 不存在的物品"), ctx) == USE_TPL["use_no_item"]


def test_use_wear_equipment() -> None:
    """装备类（有槽位）→ 穿戴（适配器 equip_wear）。"""
    ctx = make_ctx()
    assert cmd_use(parse("/使用 1"), ctx) == "✅ 已装备：铁剑"


def test_use_consumable_heal() -> None:
    """消耗类（heal）→ 扣减 + 回血。"""
    ctx = make_ctx()
    out = cmd_use(parse("/使用 2"), ctx)
    assert "使用成功" in out and "生命 +50" in out
    assert ctx["player"]["hp"] == 80  # 30 + 50（上限 100）


def test_use_consumable_heal_cap() -> None:
    """回血不超过 max_hp。"""
    ctx = make_ctx(player={
        "name": "测试勇士", "level": 1, "job_id": "warrior", "hp": 90,
        "inventory": [], "equipment": {},
        "attributes": {"base": {"hp": 100.0, "mp": 30.0}},
    })
    cmd_use(parse("/使用 2"), ctx)  # 90 + 50 封顶 100
    assert ctx["player"]["hp"] == 100


def test_use_not_consumable() -> None:
    """非装备非消耗（材料）→ use_cannot_use。"""
    ctx = make_ctx()
    ctx["equip_engine"] = SimpleNamespace(
        _sorted_inventory=lambda p: [_fake_item("quest_token", "任务信物")],
        equip_wear=lambda idx, ctx: {"ok": False, "message": "❌ 这件物品不能装备"},
    )
    assert cmd_use(parse("/使用 1"), ctx) == USE_TPL["use_cannot_use"]


def test_use_bound_item() -> None:
    """绑定拒移（remove_item reason=bound）→ use_bound。"""
    ctx = make_ctx()
    ctx["inventory_engine"] = SimpleNamespace(
        remove_item=lambda p, item_id, count=1: {"ok": False, "reason": "bound"},
    )
    assert cmd_use(parse("/使用 2"), ctx) == USE_TPL["use_bound"]


def test_use_no_decorative_emoji() -> None:
    """模板零装饰 emoji。"""
    for key in USE_TPL_KEYS:
        for ch in USE_TPL[key]:
            assert ch not in BANNED_EMOJI, f"命中禁用装饰 emoji：{ch} in {key!r}"


def test_register_use_commands_routes() -> None:
    """register_use_commands：/使用 注册进 Router 且 handler 可命中。"""
    router = Router()
    register_use_commands(router, make_context=lambda p: make_ctx())
    assert router.has("使用")
    spec = router.get("使用")
    assert spec is not None and spec.whitelisted
    handler = spec.handler
    assert handler is not None
    assert handler(parse("/使用 1")) == "✅ 已装备：铁剑"


def test_use_custom_templates_override() -> None:
    """内容包覆盖：ctx.templates 注入自定义 use_ok → 渲染用自定义模板（含占位符）。"""
    ctx = make_ctx()
    ctx["templates"] = {"use_ok": "自定义✅使用{name}回血{heal_total}"}
    out = cmd_use(parse("/使用 2"), ctx)
    assert out == "自定义✅使用疗伤药回血50"
    assert ctx["player"]["hp"] == 80  # 覆盖只影响文案，逻辑照常


def test_use_template_unknown_placeholder_kept() -> None:
    """白名单外占位符：templates 含未登记占位符 → 渲染原样保留不崩。"""
    ctx = make_ctx()
    ctx["templates"] = {"use_ok": "✅ 使用成功：{name}（生命 +{heal_total}）{hint}"}
    out = cmd_use(parse("/使用 2"), ctx)
    assert out == "✅ 使用成功：疗伤药（生命 +50）{hint}"
