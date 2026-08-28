"""使用指令接线 use_commands.py（2026-08-28 用户拍板：装备穿戴统一用「使用」）。

依据：用户拍板「用使用」（装备穿戴 + 背包道具统一走 /使用）；白名单 parsers.py 已有
「使用」（DEFAULT_WHITELIST + DEFAULT_QUANTITY_COMMANDS）；设计契约见 记录.md 需求池。
职责：/使用 <序号> 或 <物品名> 统一承载——装备类（ItemInstance.slot 非空）→ 穿戴
（复用 basic_commands._equip_engine 适配器）；消耗类（物品 def usable/type=consumable +
effects 含 heal）→ 扣减 + 回血；其他 → 不可直接使用。战斗内拒绝。

零 IO、零 NoneBot、纯函数确定性（引擎注入/懒加载；读 ctx 快照）。零装饰 emoji。
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, MutableMapping, Optional

from .basic_commands import TPL_REGISTER_GATE, _equip_engine
from .router import CommandSpec

USE_CMD = "使用"

# 模板（D-04 文案唯一源本模块；仅 ✅/❌ +「」排版符）
TPL_IN_BATTLE = "❌ 战斗中不能使用物品"
TPL_NO_ARG = "❌ /使用：需要物品序号或名称（/使用 1 或 /使用 疗伤药）"
TPL_NO_ITEM = "❌ 背包里没有这个物品"
TPL_CANNOT_USE = "❌ 这个物品不能直接使用"
TPL_BOUND = "❌ 这个物品已绑定，无法使用"

__all__ = [
    "USE_CMD",
    "TPL_IN_BATTLE", "TPL_NO_ARG", "TPL_NO_ITEM", "TPL_CANNOT_USE", "TPL_BOUND",
    "cmd_use", "register_use_commands",
]


def _def_dict(d: Any) -> dict:
    """内容包 Def → dict（registry 表值形态兼容：dict 直返 / Def.raw 提取 / 缺省空）。"""
    if isinstance(d, dict):
        return d
    raw = getattr(d, "raw", None)
    return raw if isinstance(raw, dict) else {}


def _inventory_engine(ctx: MutableMapping[str, Any]) -> Any:
    """背包引擎解析（ctx["inventory_engine"] 注入优先 → 懒加载 InventoryEngine）。"""
    eng = ctx.get("inventory_engine")
    if eng is not None:
        return eng
    mod = importlib.import_module("qbot_rpg.core.inventory")
    return mod.InventoryEngine()


def _sorted_rows(player: MutableMapping[str, Any], ctx: MutableMapping[str, Any]) -> list:
    """背包行按 /背包 展示序（acquired_at 倒序，同适配器 _sorted_inventory 口径）。

    入参 player: 玩家状态 dict；ctx: 上下文（equip_engine 可注入）。出参 list[ItemInstance]。
    核心逻辑: 复用 _equip_engine(ctx)._sorted_inventory(player)（注入/懒加载同一适配器）。
    """
    adapter = _equip_engine(ctx)
    return list(adapter._sorted_inventory(player))  # noqa: SLF001 —— 同包适配器口径复用


def _resolve_row(
    player: MutableMapping[str, Any],
    target: str,
    ctx: MutableMapping[str, Any],
) -> tuple:
    """解析使用目标 → (ItemInstance, 背包序号 index|None)。

    入参 player/ctx；target: 数字序号或物品名。出参 (inst, index)——inst None = 未找到。
    核心逻辑: 数字 → _sorted_rows 下标（1 起）；名称 → item_id/name 精确匹配（未命中
    → 名称模糊匹配首项）。
    """
    rows = _sorted_rows(player, ctx)
    if target.isdigit():
        index = int(target)
        if 1 <= index <= len(rows):
            return rows[index - 1], index
        return None, None
    for i, r in enumerate(rows, 1):
        if str(getattr(r, "item_id", "") or "") == target:
            return r, i
    for i, r in enumerate(rows, 1):
        if str(getattr(r, "name", "") or "") == target:
            return r, i
    return None, None


def _use_consumable(
    ctx: MutableMapping[str, Any],
    player: MutableMapping[str, Any],
    inst: Any,
    item_def: dict,
) -> str:
    """消耗类使用：heal 效果 → 扣减 + 回血（先 remove_item 成功再回血）。

    入参 ctx/player/inst/item_def。出参 str——成功/失败模板。
    核心逻辑: effects 表聚合 heal power → InventoryEngine.remove_item(1)（失败透传
    not_enough/bound）→ calc_all_final_attributes 取 max_hp → player["hp"]=min 回血。
    """
    effects_map = ctx.get("effect_table") or {}
    heal_total = 0
    for eid in item_def.get("effects") or []:
        edef = _def_dict(effects_map.get(str(eid)))
        if edef.get("type") == "heal":
            try:
                heal_total += int(edef.get("power") or 0)
            except (TypeError, ValueError):  # noqa: PERF203 —— 单条坏效果跳过
                continue
    if heal_total <= 0:
        return TPL_CANNOT_USE
    inv = _inventory_engine(ctx)
    res = inv.remove_item(player, str(getattr(inst, "item_id", "") or ""), 1)
    if not res.get("ok"):
        reason = str(res.get("reason") or "")
        if reason == "bound":
            return TPL_BOUND
        return TPL_NO_ITEM
    attrs = player.get("attributes")
    max_hp = 100
    if attrs is not None:
        try:
            mod = importlib.import_module("qbot_rpg.core.player_attributes")
            finals = mod.calc_all_final_attributes(attrs)
            max_hp = int(finals.get("hp") or 100)
        except Exception:  # noqa: BLE001 —— 属性计算失败兜底 100
            max_hp = 100
    cur = int(player.get("hp") or 0)
    player["hp"] = min(max_hp, cur + heal_total)
    return f"✅ 使用成功：{getattr(inst, 'name', '')}（生命 +{heal_total}）"


def cmd_use(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/使用 指令壳：序号/名称 → 装备穿戴或消耗使用（统一承载）。

    入参 parsed: ParsedCommand（args 消费）；ctx: 玩家上下文。出参 str——回复正文。
    核心逻辑: 未注册 → TPL_REGISTER_GATE；战斗中 → TPL_IN_BATTLE；缺参 →
    TPL_NO_ARG；解析目标（_resolve_row）→ 装备类（ItemInstance.slot 或 item_def.slot）
    → _equip_engine.equip_wear（序号）→ 消耗类（usable/type=consumable）→ _use_consumable
    → 其他 → TPL_CANNOT_USE。
    """
    if not bool(ctx.get("registered")):
        return TPL_REGISTER_GATE
    if ctx.get("battle_session"):
        return TPL_IN_BATTLE
    player = ctx.get("player")
    if not isinstance(player, MutableMapping):
        return TPL_REGISTER_GATE
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return TPL_NO_ARG
    target = str(args[0])
    inst, index = _resolve_row(player, target, ctx)
    if inst is None:
        return TPL_NO_ITEM
    item_id = str(getattr(inst, "item_id", "") or "")
    item_def = _def_dict((ctx.get("items") or {}).get(item_id))
    slot = getattr(inst, "slot", None) or item_def.get("slot")
    if slot:
        if index is None:
            return TPL_NO_ITEM
        adapter = _equip_engine(ctx)
        res = adapter.equip_wear(index, ctx)
        return str(res.get("message") or TPL_CANNOT_USE)
    usable = bool(item_def.get("usable"))
    if usable or str(item_def.get("type") or "") == "consumable":
        return _use_consumable(ctx, player, inst, item_def)
    return TPL_CANNOT_USE


def register_use_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /使用 注册进 Router（同 register_commands 模式；make_context 由装配层注入）。"""
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】use_commands.register_use_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _use(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_use(parsed, injected)
        return cmd_use(parsed, _ctx(parsed))

    router.register(CommandSpec(USE_CMD, handler=_use))
    return router
