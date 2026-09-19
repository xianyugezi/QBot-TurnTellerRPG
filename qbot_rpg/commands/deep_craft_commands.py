"""批41 · 深度打造主入口 `/精造`（打造家族的「深度层」指令壳）。

文件：qbot_rpg/commands/deep_craft_commands.py
功能：**深度打造**（图纸 + 材料 → 装备）的唯一主入口，三档子功能：

  - `/精造 学习 <图纸>`：学习图纸（消耗 1 张，记入玩家 `learned_blueprints`）；
  - `/精造 <图纸>`：只读预览（图纸档 / 等级带 / cost 上限 / 材料槽）；
  - `/精造 <图纸> <材料>*<数量>,…`：投料打造 → 产出装备实例（带 uid）。

边界铁律（`docs/深度打造_决策记录.md` §六 + `docs/批39_合成公用层接口.md` 三）：
  · **投料 → 基础产出走公用合成层**：`core/synthesis.py` 的 `preview_base_output`
    （投料校验）/ `base_output`（标准版产出定义）/ `requirements_of`（投入需求）
    / `resolve_recipe`（配方解析）——**不重复实现投料校验**；
  · 深度层（等级加权 / 品质经验 / 品质等级 / 品质抽取 / cost 约束 / 图纸档缩放）
    全部委托 `core/deep_craft.py`（纯函数）；
  · **随机一律用玩家级随机流** `ctx["rng"]`（批40 H5），不新建随机源。

依据：`docs/深度打造_决策记录.md` §一 H1/H2/H6、§二 N1~N4/N6、§六；原案 §1/§5/§6/§12/§13；
  `打造系统_B_数值与经验规划.md` §1~§3；批41 A 路 schema（图纸是物品的一种）。

铁律：零 NoneBot import；`CommandSpec.handler` 消费 ParsedCommand；handler 支持
  `k.get("ctx")` 装配注入；**文案一律走模板表**（本模块零硬编码文案）；不含任何内容包
  业务名（图纸/材料/相性 id 全部来自包声明与玩家投入）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.content.deep_craft_settings import grade_of, read_deep_craft_settings
from qbot_rpg.core import craft_paths
from qbot_rpg.core.deep_craft import (
    REJECT_COST_OVER,
    REJECT_COST_UNDER,
    REJECT_DRAW,
    REJECT_KINDS,
    REJECT_LEVEL_BAND,
    REJECT_MAIN_MATERIAL,
    REJECT_NO_MATERIALS,
    REJECT_NOT_LEARNED,
    REJECT_PER_KIND,
    plan_craft,
)
from qbot_rpg.core.synthesis import (
    base_output,
    preview_base_output,
    requirements_of,
    resolve_recipe,
)
from qbot_rpg.core.templates import tpl_of
from qbot_rpg.data.item import new_item_uid

# 同包兄弟模块：相对导入（架构门禁同 synth_commands 口径）。
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    "DEEP_CRAFT_CMD",
    "cmd_deep_craft",
    "register_deep_craft_commands",
]

# 主入口名（决策记录 §5.1：固定名 `精造`，不落框架公共表；别名冲突检查见批38 报告）。
DEEP_CRAFT_CMD: str = "精造"
# 学习子词（非解析器固定子词，作为 args[0] 普通位置参数；`/精造 学习 <图纸>`）。
LEARN_SUBWORD: str = "学习"

# 拒绝原因码 → 模板 key（本模块零硬编码文案）。
_REJECT_TPL: Dict[str, str] = {
    REJECT_NOT_LEARNED: "deep_craft_not_learned",
    REJECT_NO_MATERIALS: "deep_craft_no_materials",
    REJECT_MAIN_MATERIAL: "deep_craft_main_material",
    REJECT_KINDS: "deep_craft_kinds",
    REJECT_PER_KIND: "deep_craft_per_kind",
    REJECT_COST_OVER: "deep_craft_cost_over",
    REJECT_COST_UNDER: "deep_craft_cost_under",
    REJECT_LEVEL_BAND: "deep_craft_level_band",
    REJECT_DRAW: "deep_craft_draw_fail",
}


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------
def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 synth_commands._fragment）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _clean(token: Any) -> str:
    """去掉列表/紧凑连接符（`+`）前缀，返回纯名称。"""
    t = str(token)
    if t.startswith("+"):
        t = t[1:]
    return t.strip()


def _material_tokens(parsed: Any) -> List[Tuple[str, int]]:
    """投入材料 token → [(名称, 件数)]（`名称*N`；缺数量按 1）。

    来源：解析器结构化 `targets`（逗号列表）**优先且互斥**，缺省回落到 `args[1:]`
    （空格分隔）——两者不叠加（列表 token 已在 `targets` 逐项展开，再取 args 会重复计料）。
    """
    raw: List[Any] = []
    if getattr(parsed, "targets", None):
        raw.extend(parsed.targets)
    else:
        raw.extend((getattr(parsed, "args", None) or [])[1:])
    out: List[Tuple[str, int]] = []
    for tok in raw:
        name, _, q = str(tok).partition("*")
        name = _clean(name)
        if not name:
            continue
        n = int(q) if q.isdigit() and int(q) > 0 else 1
        out.append((name, n))
    return out


def _resolve_item(ctx: Mapping[str, Any], ref: str) -> Tuple[Optional[str], Mapping[str, Any]]:
    """物品解析（id 精确 → name 精确）；未命中 → (None, {})。"""
    items = ctx.get("items")
    if not isinstance(items, Mapping) or not isinstance(ref, str) or not ref.strip():
        return None, {}
    if ref in items and isinstance(items[ref], Mapping):
        return ref, items[ref]
    for iid, entry in items.items():
        if isinstance(entry, Mapping) and entry.get("name") == ref:
            return str(iid), entry
    return None, {}


def _count(ctx: Mapping[str, Any], item_id: str) -> int:
    fn = ctx.get("count_item")
    if callable(fn):
        try:
            return int(fn(item_id))
        except Exception:  # noqa: BLE001 —— 计数失败按 0（防崩）
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        try:
            return int(inv.get(item_id, 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _learned(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    node = ctx.get("learned_blueprints")
    return node if isinstance(node, Mapping) else {}


def _mark_learned(ctx: MutableMapping[str, Any], bp_id: str) -> bool:
    node = ctx.get("learned_blueprints")
    if not isinstance(node, MutableMapping):
        node = {}
        ctx["learned_blueprints"] = node
    node[bp_id] = True
    return True


def _instances(ctx: MutableMapping[str, Any]) -> List[Any]:
    insts = ctx.get("inventory_instances")
    if not isinstance(insts, list):
        insts = []
        ctx["inventory_instances"] = insts
    return insts


# ---------------------------------------------------------------------------
# 三段子功能
# ---------------------------------------------------------------------------
def _learn(ctx: MutableMapping[str, Any], ref: str) -> str:
    """`/精造 学习 <图纸>`：持有图纸 → 学习（消耗 1 张 + 记入 learned_blueprints）。"""
    bp_id, bp = _resolve_item(ctx, ref)
    if bp_id is None or not bp.get("blueprint_output"):
        return tpl_of(ctx, "deep_craft_blueprint_not_found", {"target": ref})
    name = str(bp.get("name") or bp_id)
    if _count(ctx, bp_id) < 1:
        return tpl_of(ctx, "deep_craft_learn_owned", {"name": name})
    remove = ctx.get("remove_item")
    if callable(remove):
        remove(bp_id, 1)
    _mark_learned(ctx, bp_id)
    return tpl_of(ctx, "deep_craft_learn_ok", {"name": name})


def _preview(ctx: Mapping[str, Any], ref: str, bp_id: str,
             bp: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    """`/精造 <图纸>`：只读预览（等级带 / cost 上限 / 材料槽）。"""
    grade = grade_of(config, bp.get("blueprint_grade"))
    band = bp.get("blueprint_level_band") if isinstance(
        bp.get("blueprint_level_band"), Mapping) else {}
    fixed: List[str] = []
    free: List[str] = []
    for slot in bp.get("blueprint_material_slots") or []:
        if not isinstance(slot, Mapping):
            continue
        line = str(slot.get("item") or slot.get("tag") or "任意")
        cnt = slot.get("count")
        if isinstance(cnt, int) and cnt > 0:
            line = f"{line}×{cnt}"
        (fixed if slot.get("role") == "main" else free).append(line)
    return tpl_of(ctx, "deep_craft_preview", {
        "name": str(bp.get("name") or bp_id),
        "grade": str(bp.get("blueprint_grade") or "?"),
        "min": band.get("min", "?"),
        "max": band.get("max", "?"),
        "cap": (bp.get("blueprint_cost_cap") if isinstance(bp.get("blueprint_cost_cap"), int)
                and bp.get("blueprint_cost_cap") else (grade or {}).get("cost_cap", "?")),
        "fixed": "、".join(fixed) or "（无）",
        "free": "、".join(free) or "（无）",
    })


def _reject(ctx: Mapping[str, Any], plan: Mapping[str, Any], name: str) -> str:
    key = _REJECT_TPL.get(str(plan.get("reason") or ""))
    if not key:
        return tpl_of(ctx, "deep_craft_draw_fail")
    data: Dict[str, Any] = {"name": name}
    for k in ("kinds", "limit", "item", "count", "cost", "cap", "floor",
              "level", "min", "max"):
        if k in plan:
            data[k] = plan[k]
    band = plan.get("band")
    if isinstance(band, (list, tuple)) and len(band) == 2:
        data["min"], data["max"] = band[0], band[1]
    return tpl_of(ctx, key, data)


def _land(ctx: MutableMapping[str, Any], plan: Mapping[str, Any], bp: Mapping[str, Any],
          bp_id: str, base: Mapping[str, Any]) -> bool:
    """落地：原子扣料 → 装备实例入包（带 uid + 固定/随机属性 + 套装词条 + 相性）→ 快照。

    批42 · C：实例内容**全部来自 `plan_craft` 的纯计划**（固定项照抄 / 随机项走相性池），
    本函数只做搬运与落档；实例字段含 `stats_bonus` / `set_affixes` / `passives` /
    `affinities`（构造点透传清单见 `docs/深度打造_实现说明.md`）。
    """
    rows = plan.get("materials") or []
    # 全量够数预检（含公用层未覆盖的自由材料），全通过再扣，避免部分扣减。
    for m in rows:
        if _count(ctx, str(m["id"])) < int(m["count"]):
            return False
    remove = ctx.get("remove_item")
    if callable(remove):
        for m in rows:
            if not remove(str(m["id"]), int(m["count"])):
                return False
    item_id = str(base.get("item_id") or bp.get("blueprint_output") or "")
    items = ctx.get("items")
    idef = items.get(item_id) if isinstance(items, Mapping) else None
    idef = idef if isinstance(idef, Mapping) else {}
    aff = plan.get("affinity") if isinstance(plan.get("affinity"), Mapping) else {}
    inst = {
        "item_id": item_id,
        "name": str(idef.get("name") or base.get("item_name") or item_id),
        "count": 1,
        "quality": plan.get("quality") or "normal",
        "bound": False,
        "slot": str(bp.get("blueprint_slot") or idef.get("slot") or ""),
        "stats_bonus": dict(plan.get("stats_bonus") or {}),
        "traits": (),
        "enhance_level": 0,
        "uid": new_item_uid(),
        # ---- 批42 · C：相性 / 套装词条 / 被动（打造时求值、冻进实例）----
        "affinities": {str(k): float(v) for k, v in (aff.get("values") or {}).items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)},
        "set_affixes": [str(x) for x in (plan.get("set_affixes") or [])],
        "passives": [str(x) for x in (plan.get("passives") or [])],
        # ---- 批43：品质等级（强化上限按它取）+ 强化特殊词条载荷（新造为空）----
        "quality_level": int(plan.get("quality_level") or 0),
        "enhance_affixes": [],
    }
    _instances(ctx).append(inst)
    ctx["_m8_dirty_inventory"] = True
    snapshot = {
        "blueprint": bp_id,
        "item_id": item_id,
        "uid": inst["uid"],
        "quality": inst["quality"],
        "equipment_level": plan.get("level"),
        "quality_level": plan.get("quality_level"),
        "quality_exp": plan.get("quality_exp"),
        "cost": plan.get("cost"),
        "cost_cap": plan.get("cost_cap"),
        "kinds": plan.get("kinds"),
        "color_row": plan.get("color_row"),
        # 批42 · C：主/副相性 + 词条摘要（便于对拍与展示）
        "affinity_main": aff.get("main"),
        "affinity_sub": aff.get("sub"),
        "random_stats": list(plan.get("random_stats") or []),
        "random_set_affixes": list(plan.get("random_set_affixes") or []),
        "passives": list(plan.get("passives") or []),
    }
    player = ctx.get("player")
    ps = getattr(player, "persistent_state", None) if player is not None else None
    if isinstance(ps, MutableMapping):
        hist = ps.get("deep_craft_instances")
        if not isinstance(hist, list):
            hist = []
            ps["deep_craft_instances"] = hist
        hist.append(dict(snapshot))
        ps["deep_craft_last"] = dict(snapshot)
    else:
        ctx["deep_craft_last"] = dict(snapshot)
    return True


# ---------------------------------------------------------------------------
# 指令处理器
# ---------------------------------------------------------------------------
def cmd_deep_craft(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/精造 [学习] <图纸> [材料*数量,…]` 主入口。

    出参：回复正文 str（全部经模板表；解析错误 → TPL-12）。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "deep_craft_usage")

    settings = ctx.get("settings")
    settings_map = settings if isinstance(settings, Mapping) else {}
    if not craft_paths.forge_path_enabled(settings_map):
        return tpl_of(ctx, "deep_craft_disabled")

    # `/精造 学习 <图纸>`
    if _clean(args[0]) == LEARN_SUBWORD:
        rest = [_clean(a) for a in args[1:]]
        rest += [_clean(t) for t in (getattr(parsed, "targets", None) or [])]
        if not rest:
            return tpl_of(ctx, "deep_craft_usage")
        return _learn(ctx, rest[0])

    ref = _clean(args[0])
    bp_id, bp = _resolve_item(ctx, ref)
    if bp_id is None or not bp.get("blueprint_output"):
        return tpl_of(ctx, "deep_craft_blueprint_not_found", {"target": ref})
    name = str(bp.get("name") or bp_id)
    config = read_deep_craft_settings(settings_map)

    pairs = _material_tokens(parsed)
    if not pairs:
        return _preview(ctx, ref, bp_id, bp, config)

    # ---- 公用合成层：投料校验 + 基础产出定义（不重复实现投料校验）----
    recipe_ref = bp.get("blueprint_recipe")
    recipe = resolve_recipe(ctx, recipe_ref) if recipe_ref else None
    if recipe is None:
        return tpl_of(ctx, "deep_craft_blueprint_not_found", {"target": ref})
    preview = preview_base_output(ctx, recipe_ref, 1, settings=settings_map)
    if not preview.get("ok"):
        return str(preview.get("message") or tpl_of(ctx, "deep_craft_no_materials",
                                                   {"name": name}))
    base = base_output(recipe, ctx)

    # 投入必须覆盖公用配方声明的固定材料（把公用层的需求与玩家投入对齐）。
    submitted: Dict[str, int] = {}
    materials: List[Dict[str, Any]] = []
    for mname, cnt in pairs:
        mid, _mdef = _resolve_item(ctx, mname)
        if mid is None:
            return tpl_of(ctx, "deep_craft_blueprint_not_found", {"target": mname})
        submitted[mid] = submitted.get(mid, 0) + cnt
    for req in requirements_of(recipe, 1).get("materials") or []:
        if submitted.get(str(req.get("item")), 0) < int(req.get("count") or 0):
            return tpl_of(ctx, "deep_craft_no_materials", {"name": name})
    for mid, cnt in submitted.items():
        materials.append({"id": mid, "count": cnt})

    plan = plan_craft(
        blueprint=bp,
        config=config,
        materials=materials,
        material_defs=ctx.get("items") or {},
        learned=bool(_learned(ctx).get(bp_id)),
        rng=ctx.get("rng"),
        # 批42 · C：相性池查询入参 = settings（唯一入口 affinity.resolve_available_entries）
        affinity_config=settings_map,
        trait_defs=ctx.get("traits"),
        affinity_reactions=settings_map.get("affinity_reactions") or (),
    )
    if not plan.get("ok"):
        return _reject(ctx, plan, name)
    if not _land(ctx, plan, bp, bp_id, base):
        return tpl_of(ctx, "deep_craft_no_materials", {"name": name})
    aff = plan.get("affinity") if isinstance(plan.get("affinity"), Mapping) else {}
    return tpl_of(ctx, "deep_craft_ok", {
        "name": str(base.get("item_name") or bp.get("blueprint_output") or bp_id),
        "quality": plan.get("quality"),
        "qlevel": plan.get("quality_level"),
        "level": plan.get("level"),
        "cost": int(plan.get("cost") or 0),
        "cap": plan.get("cost_cap"),
        "kinds": plan.get("kinds"),
        # 批42 · C：成功文案携带相性与随机词条摘要（模板可选用占位符）
        "main": aff.get("main") or "",
        "sub": aff.get("sub") or "",
        "affixes": "、".join(str(x) for x in (plan.get("set_affixes") or [])) or "（无）",
        "passives": "、".join(str(x) for x in (plan.get("passives") or [])) or "（无）",
    })


# ---------------------------------------------------------------------------
# 装配入口
# ---------------------------------------------------------------------------
def register_deep_craft_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把深度打造主入口 `/精造` 注册进 Router（handler 支持 k.get("ctx") 注入）。"""
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】deep_craft_commands.register_deep_craft_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _handler(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_deep_craft(parsed, injected)
        return cmd_deep_craft(parsed, _ctx(parsed))

    router.register(CommandSpec(DEEP_CRAFT_CMD, handler=_handler))
    return router
