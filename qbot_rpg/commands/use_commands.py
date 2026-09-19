"""使用指令接线 use_commands.py（2026-08-28 用户拍板：装备穿戴统一用「使用」）。

依据：用户拍板「用使用」（装备穿戴 + 背包道具统一走 使用）；白名单 parsers.py 已有
「使用」（DEFAULT_WHITELIST + DEFAULT_QUANTITY_COMMANDS）；设计契约见 记录.md 需求池。
职责：使用 <序号> 或 <物品名> 统一承载——装备类（ItemInstance.slot 非空）→ 穿戴
（复用 basic_commands._equip_engine 适配器）；消耗类（物品 def usable/type=consumable +
effects）→ 扣减 + 结算效果；其他 → 不可直接使用。战斗内拒绝。

批18（效果扩展）：「消耗类」不再只认 heal——按效果 `type` 分派：
  · heal          → 回血（原有行为，逐字节不变）；
  · gain_currency → 给玩家货币（`[amount_min, amount_max]` 内取随机；`amount_min==amount_max`
                    或只配 `amount_min` = 固定金额）——随机源用引擎既有 RNG（ctx["rng"]，
                    缺省 `random` 模块，与 core/effects.chance_roll 同一兜底，**不新引入随机源**）；
  · learn_skill   → 把技能以指定等级（缺省 1）授予玩家（按 core/skill_slots 装配快照口径，
                    写入 `persistent_state.skill_slots`；已学会 → 幂等不重复授予）。
  两者都写在 effects.json 的效果条目上（物品 `effects` 只放引用 id）——持续回合等语义
  也归效果条目（物品级不设重复来源，批18 段A 裁定）。

2026-09-12 消息模板重构·批11 路B：本模块 use_* 文案唯一源 = 全量模板表
qbot_rpg/core/templates/template_table.json，use_tpl 分区已清空。

零 IO、零 NoneBot、纯函数确定性（引擎注入/懒加载；读 ctx 快照）。零装饰 emoji。
"""
from __future__ import annotations

import importlib
import random
from typing import Any, Callable, List, Mapping, MutableMapping, Optional, Tuple

from .basic_commands import _equip_engine
from .router import CommandSpec
from qbot_rpg.core.equipment import item_requirement_error
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）
from qbot_rpg.data.player import Player

USE_CMD = "使用"

# 批18：消耗类效果的三种分派类型（物品 effects → 效果定义 type）。未知类型照旧忽略
# （效果引擎/专项校验职责；本层只消费已裁决的三类）。
_EFFECT_HEAL = "heal"
_EFFECT_GAIN_CURRENCY = "gain_currency"
_EFFECT_LEARN_SKILL = "learn_skill"
# 技能槽类型（镜像 core/skill_slots 常量；commands 层不 import core 常量做字面绑定，
# 只用于把「已学技能」写进装配快照的槽位标记）。
_SLOT_KINDS: Tuple[str, ...] = ("basic", "active", "passive", "trigger")
_DEFAULT_SLOT_KIND = "active"

__all__ = [
    "USE_CMD",
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


def _field(row: Any, key: str) -> Any:
    """dict/对象兼容字段读取（2026-09-05：asdict 化行是 dict，getattr 失效）。"""
    try:
        if isinstance(row, Mapping):
            return row.get(key)
        return getattr(row, key, None)
    except Exception:  # noqa: BLE001
        return None


def _resolve_player(ctx: MutableMapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """玩家状态解析（兼容装配层 Player dataclass + 指令层 dict）。

    入参 ctx: 玩家上下文。出参 MutableMapping 或 None。核心逻辑: dict 直返；
    Player dataclass → asdict 转可变 dict 并写回 ctx（引擎就地修改 + 落档 dict 兼容）。
    """
    p = ctx.get("player")
    if isinstance(p, MutableMapping):
        return p
    if isinstance(p, Player):
        import dataclasses  # noqa: PLC0415

        d = dataclasses.asdict(p)
        ctx["player"] = d
        return d
    return None


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
        if str(_field(r, "item_id") or "") == target:
            return r, i
    for i, r in enumerate(rows, 1):
        if str(_field(r, "name") or "") == target:
            return r, i
    return None, None


def _resolve_rng(ctx: MutableMapping[str, Any]) -> Any:
    """消耗类随机取值源（引擎既有 RNG 单源；不新引入随机源）。

    优先 `ctx["rng"]`（装配层注入的确定性 Random 实例，种子化）；缺注入/无 randint →
    兜底标准库 `random` 模块（与 core/effects.chance_roll 的 `random.random()` 同源）。
    """
    r = ctx.get("rng")
    if r is not None and hasattr(r, "randint"):
        return r
    return random


def _pick_amount(ctx: MutableMapping[str, Any], lo: int, hi: int) -> int:
    """在闭区间 `[lo, hi]` 内取整（lo==hi → 固定值，不消耗随机数）。"""
    if hi <= lo:
        return lo
    return int(_resolve_rng(ctx).randint(lo, hi))


def _int_or_none(value: object) -> Optional[int]:
    """非 bool 整数读取（其余 → None）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _currency_grant_of(edef: Mapping[str, Any]) -> Optional[Tuple[str, int, int]]:
    """效果定义 → (货币 id, 下限, 上限)；口径不成立/缺货币 → None（本层跳过，校验层已报）。

    取值口径（批18 裁定，与 effects 文档一致）：
      · `amount_min` == `amount_max` → 必给固定值；
      · 缺 `amount_max` → 视为等于 `amount_min`；
      · 缺 `amount_min` → 视为等于 `amount_max`（对称缺省）；
      · 两者都缺 / 货币为空 / 下限 > 上限 → 本层不生效（校验层红拦死配置）。
    """
    currency = edef.get("currency")
    if not isinstance(currency, str) or not currency:
        return None
    lo = _int_or_none(edef.get("amount_min"))
    hi = _int_or_none(edef.get("amount_max"))
    if lo is None and hi is None:
        return None
    if lo is None:
        lo = hi
    if hi is None:
        hi = lo
    if lo is None or hi is None or lo < 0 or hi < 0 or lo > hi:
        return None
    return (currency, lo, hi)


def _skill_grant_of(edef: Mapping[str, Any]) -> Optional[Tuple[str, int]]:
    """效果定义 → (技能 id, 等级)；缺技能 id → None。等级缺省/非法 → 1（校验层红拦）。"""
    skill = edef.get("skill")
    if not isinstance(skill, str) or not skill:
        return None
    level = _int_or_none(edef.get("level"))
    if level is None or level < 1:
        level = 1
    return (skill, level)


def _slot_kind_of(skill_id: str, ctx: Mapping[str, Any]) -> str:
    """技能槽类型（读 ctx["skills"] 技能表 type；未知/缺表 → active，对齐 skill_slots 缺省）。"""
    table = ctx.get("skills")
    row: Any = None
    if isinstance(table, Mapping):
        row = table.get(skill_id)
    kind = row.get("type") if isinstance(row, Mapping) else getattr(row, "type", None)
    return kind if isinstance(kind, str) and kind in _SLOT_KINDS else _DEFAULT_SLOT_KIND


def _add_currency(
    ctx: MutableMapping[str, Any], player: MutableMapping[str, Any],
    currency: str, amount: int,
) -> None:
    """货币入账（就地累加）：写 player["currencies"]，并同步 ctx["currencies"] 副本（若有）。"""
    pb = player.get("currencies")
    if not isinstance(pb, MutableMapping):
        pb = {}
        player["currencies"] = pb
    pb[currency] = int(pb.get(currency, 0) or 0) + int(amount)
    cb = ctx.get("currencies")
    if isinstance(cb, MutableMapping) and cb is not pb:
        cb[currency] = int(cb.get(currency, 0) or 0) + int(amount)


def _currency_name(ctx: Mapping[str, Any], currency: str) -> str:
    """货币显示名（settings.currencies[].name 优先；缺省回 id，复用 reward 唯一实现）。"""
    try:
        from qbot_rpg.core.reward import currency_display_name  # noqa: PLC0415
        name = currency_display_name(ctx, currency)
    except Exception:  # noqa: BLE001 —— 显示名解析失败不阻断使用
        name = ""
    return name or currency


def _grant_skill(
    ctx: MutableMapping[str, Any], player: MutableMapping[str, Any],
    skill_id: str, level: int,
) -> bool:
    """把技能以指定等级授予玩家（按装配快照 `persistent_state.skill_slots` 口径）。

    写入：`slots` 追加 `{slot, skill_id, level}`（slot 取技能表 type，缺省 active），
    active 同步 `active_order`，passive/trigger 同步对应槽；已学会（任一容器已含该 id）
    → 幂等返回 False（不重复授予、不改既有等级）。返回是否本次新授予。
    """
    from qbot_rpg.core.skill_slots import SLOT_STATE_KEY, save_slots_to_state  # noqa: PLC0415

    ps = player.get("persistent_state")
    if not isinstance(ps, MutableMapping):
        ps = {}
        player["persistent_state"] = ps
    snap = ps.get(SLOT_STATE_KEY)
    if not isinstance(snap, MutableMapping):
        snap = {"slots": [], "active_order": [], "passive": [], "trigger": [], "version": 1}
        ps[SLOT_STATE_KEY] = snap
    slots = snap.get("slots")
    if not isinstance(slots, list):
        slots = []
        snap["slots"] = slots
    active_order = snap.get("active_order")
    if not isinstance(active_order, list):
        active_order = []
        snap["active_order"] = active_order
    known = any(isinstance(r, Mapping) and r.get("skill_id") == skill_id for r in slots)
    known = known or skill_id in active_order
    for container in ("passive", "trigger"):
        rows = snap.get(container)
        if isinstance(rows, list) and any(
                isinstance(r, Mapping) and r.get("skill_id") == skill_id for r in rows):
            known = True
    if known:
        save_slots_to_state(player, snap)  # 仍走落档链路（幂等覆盖，不改内容）
        return False
    kind = _slot_kind_of(skill_id, ctx)
    slots.append({"slot": kind, "skill_id": skill_id, "level": int(level)})
    if kind == "active":
        if skill_id not in active_order:
            active_order.append(skill_id)
    elif kind in ("passive", "trigger"):
        rows = snap.get(kind)
        if not isinstance(rows, list):
            rows = []
            snap[kind] = rows
        rows.append({"slot": kind, "skill_id": skill_id})
    if _int_or_none(snap.get("version")) is None:
        snap["version"] = 1
    save_slots_to_state(player, snap)
    # 同回合内 ctx["skill_slots_state"]（_ps_init 绑定的存档节点）与 player 侧可能不是同一
    # 对象（Player dataclass → asdict 的既有现象）——同步一份，保证同拍读一致。
    st = ctx.get("skill_slots_state")
    if isinstance(st, MutableMapping) and st is not snap:
        st.clear()
        st.update(snap)
    return True


def _use_consumable(
    ctx: MutableMapping[str, Any],
    player: MutableMapping[str, Any],
    inst: Any,
    item_def: dict,
) -> str:
    """消耗类使用：按效果类型结算（heal / gain_currency / learn_skill）。

    入参 ctx/player/inst/item_def。出参 str——成功/失败模板（use_cannot_use/use_bound/
    use_no_item/use_ok/use_gain_currency_ok/use_learn_skill_ok/…，tpl_of 渲染）。
    核心逻辑（批18 扩展，heal 路径逐字节不变）：
      1) 先扫效果表：heal 聚合 power；gain_currency 解析区间；learn_skill 解析技能/等级；
         三类都没有 → use_cannot_use（不扣物品）；
      2) InventoryEngine.remove_item(1) 成功后才结算（失败透传 not_enough/bound）；
      3) heal → 取 max_hp 回血；gain_currency → 既有 RNG 区间取值 + 货币入账；
         learn_skill → 授予技能（已学会幂等）。
    """
    effects_map = ctx.get("effect_table") or {}
    heal_total = 0
    currency_grants: List[Tuple[str, int, int]] = []
    skill_grants: List[Tuple[str, int]] = []
    for eid in item_def.get("effects") or []:
        edef = _def_dict(effects_map.get(str(eid)))
        etype = str(edef.get("type") or "")
        if etype == _EFFECT_HEAL:
            try:
                heal_total += int(edef.get("power") or 0)
            except (TypeError, ValueError):  # noqa: PERF203 —— 单条坏效果跳过
                continue
        elif etype == _EFFECT_GAIN_CURRENCY:
            grant = _currency_grant_of(edef)
            if grant is not None:
                currency_grants.append(grant)
        elif etype == _EFFECT_LEARN_SKILL:
            sgrant = _skill_grant_of(edef)
            if sgrant is not None:
                skill_grants.append(sgrant)
    if heal_total <= 0 and not currency_grants and not skill_grants:
        return tpl_of(ctx, "use_cannot_use")
    inv = _inventory_engine(ctx)
    # 批40 · H4：按实例 uid 精确扣减「被使用的这一件」（同 item_id 多件不误扣别件）
    res = inv.remove_item(
        player, str(_field(inst, "item_id") or ""), 1,
        uid=str(_field(inst, "uid") or ""),
    )
    if not res.get("ok"):
        reason = str(res.get("reason") or "")
        if reason == "bound":
            return tpl_of(ctx, "use_bound")
        return tpl_of(ctx, "use_no_item")
    # ---- heal（既有路径，逐字节不变）----
    if heal_total > 0:
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
        if not currency_grants and not skill_grants:
            return tpl_of(ctx, "use_ok", {
                "name": str(_field(inst, "name") or ""),
                "heal_total": heal_total,
            })
    name = str(_field(inst, "name") or "")
    lines: List[str] = []
    # ---- gain_currency（引擎既有 RNG；min==max 固定金额）----
    for currency, lo, hi in currency_grants:
        amount = _pick_amount(ctx, lo, hi)
        if amount > 0:
            _add_currency(ctx, player, currency, amount)
        lines.append(tpl_of(ctx, "use_gain_currency_ok", {
            "name": name, "currency": _currency_name(ctx, currency), "amount": amount,
        }))
    # ---- learn_skill（幂等授予）----
    for skill_id, level in skill_grants:
        granted = _grant_skill(ctx, player, skill_id, level)
        lines.append(tpl_of(ctx, "use_learn_skill_ok" if granted else "use_learn_skill_known", {
            "name": name, "skill": skill_id, "level": level,
        }))
    if heal_total > 0:
        lines.insert(0, tpl_of(ctx, "use_ok", {"name": name, "heal_total": heal_total}))
    if not lines:
        return tpl_of(ctx, "use_cannot_use")
    return "\n".join(lines)


def cmd_use(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """使用 指令壳：序号/名称 → 装备穿戴或消耗使用（统一承载）。

    入参 parsed: ParsedCommand（args 消费）；ctx: 玩家上下文。出参 str——回复正文。
    核心逻辑: 未注册 → basic_register_gate；战斗中 → use_in_battle；缺参 → use_no_arg；
    解析目标（_resolve_row）→ 装备类（ItemInstance.slot 或 item_def.slot）
    → _equip_engine.equip_wear（序号）→ 消耗类（usable/type=consumable）→ _use_consumable
    → 其他 → use_cannot_use（均 tpl_of 渲染，内容包可覆盖）。
    """
    if not bool(ctx.get("registered")):
        return tpl_of(ctx, "basic_register_gate")
    if ctx.get("battle_session"):
        return tpl_of(ctx, "use_in_battle")
    player = _resolve_player(ctx)  # 兼容 Player dataclass + dict（写回 ctx）
    if player is None:
        return tpl_of(ctx, "basic_register_gate")
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "use_no_arg")
    target = str(args[0])
    inst, index = _resolve_row(player, target, ctx)
    if inst is None:
        return tpl_of(ctx, "use_no_item")
    # 2026-09-05 修复：_resolve_player 对 Player dataclass 走 asdict → 背包行变 dict，
    # getattr 取不到字段（item_id/slot 全空 → 装备被误判「不能直接使用」）。统一
    # dict/对象兼容取值（与 basic_commands._is_equip_row 同口径）。
    item_id = _field(inst, "item_id")
    item_def = _def_dict((ctx.get("items") or {}).get(item_id))
    slot = _field(inst, "slot") or item_def.get("slot")
    if slot:
        if index is None:
            return tpl_of(ctx, "use_no_item")
        adapter = _equip_engine(ctx)
        res = adapter.equip_wear(index, ctx)
        return str(res.get("message") or tpl_of(ctx, "use_cannot_use"))
    usable = bool(item_def.get("usable"))
    if usable or str(item_def.get("type") or "") == "consumable":
        # 批22 · A1：消耗类同样受职业限制（框架字段 job_restrict）——装备类已在
        # equip_wear 内判（/使用 装备走同一路径，不重复判）。
        _req = item_requirement_error(
            item_def,
            job_id=str(_field(player, "job_id") or ctx.get("job_id") or ""),
            level=int(_field(player, "level") or ctx.get("level") or 1),
        )
        if _req:
            return _req
        return _use_consumable(ctx, player, inst, item_def)
    return tpl_of(ctx, "use_cannot_use")


def register_use_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 使用 注册进 Router（同 register_commands 模式；make_context 由装配层注入）。"""
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
