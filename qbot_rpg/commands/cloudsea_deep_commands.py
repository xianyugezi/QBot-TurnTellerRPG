# -*- coding: utf-8 -*-
"""`深度炼成` 新指令文件（九期批次 235H · G5A 收官 · 独立分账 250–400 行）。

文件名：qbot_rpg/commands/cloudsea_deep_commands.py
依据：设计稿 19_炼金系统/00_框架.md §三（单层语义）＋§七·一（AD1/AD2 两段层级化）；
    R5 裁决＝`深度炼成` 新指令词面（框架旧词「深度炼金」DEEP_CMD 系异机制，冲突矩阵
    已登记映射表 §八）；R4＝sellable:false 不绑定；数据源＝content/cloudsea/recipes.json
    （235 直载 142 条目）；错误文案＝content/cloudsea/templates.json err_deep_*（233）。

功能（spec：无参数一览＋制造单）：
  - `深度炼成`（无参数）→ 已达门槛的深度配方一览（AD1 段＋AD2 段分组，门槛＝可制 Lv＋
    DEEP_RANK_STEP×段数，顶格 LEVEL_MAX）；
  - `深度炼成 <序号|名称>` → 深度制造单（树形：材料 ×DEEP_COST_MULT／AD2 加潮髓稀有料＋
    附加费沿深度档费率＋熟练 +MASTERY_PER_DEEP；门槛/材料校验 fail-safe 文案）。

红线自证：新增指令文件（零改既有词面——「深度炼金」DEEP_CMD 框架旧词零触碰）；
    bound 口径按 R4（sellable:false＋不绑定，消费走常规扣减）；纯指令层零引擎 import
    （战斗引擎零触碰）；G5A 0 引擎 hook 保持（本文件为指令壳，配方数值全部 recipes.json
    数据直载）。
"""
from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.commands.sender import format_tpl12
from qbot_rpg.core.cloudsea_err import expand_consts

DEEP_CMD_CLOUDSEA = "深度炼成"   # R5：与框架 DEEP_CMD=「深度炼金」异词零撞

# 共享数字（12 号 §W 键域；缺省值＝设计稿申报值，运行时经 consts 注入覆盖）
KEY_DEEP_COST_MULT = "$C.ALCHEMY.DEEP_COST_MULT"
KEY_DEEP_RANK_STEP = "$C.ALCHEMY.DEEP_RANK_STEP"
KEY_MASTERY_PER_DEEP = "$C.ALCHEMY.MASTERY_PER_DEEP"
KEY_LEVEL_MAX = "$C.ALCHEMY.LEVEL_MAX"
DEFAULTS = {"C.ALCHEMY.DEEP_COST_MULT": 2, "C.ALCHEMY.DEEP_RANK_STEP": 2,
            "C.ALCHEMY.MASTERY_PER_DEEP": 2, "C.ALCHEMY.LEVEL_MAX": 10}


def _consts(ctx: Mapping[str, Any]) -> dict:
    """常量表（调用方注入优先，缺省＝设计稿申报值）。"""
    c = ctx.get("cloudsea_consts") if isinstance(ctx, Mapping) else None
    merged = dict(DEFAULTS)
    if isinstance(c, Mapping):
        merged.update({str(k): v for k, v in c.items()})
    return merged


def _lib(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """配方库（装配层注入 recipes.json 内容；缺省空库 fail-safe）。"""
    lib = ctx.get("cloudsea_recipes")
    return lib if isinstance(lib, Mapping) else {}


def _player_lv(ctx: Mapping[str, Any]) -> int:
    return int(ctx.get("alchemy_level") or 0)


def _gate_lv(base_lv: int, segment: int, consts: dict) -> int:
    """深度门槛＝可制 Lv＋段数×DEEP_RANK_STEP，顶格 LEVEL_MAX（§七·二 R3 不破顶）。"""
    step = int(consts.get("C.ALCHEMY.DEEP_RANK_STEP", 2))
    lv_max = int(consts.get("C.ALCHEMY.LEVEL_MAX", 10))
    return min(base_lv + segment * step, lv_max)


def _match(query: str, lib: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """序号精确 → 名称子串（多命中走 err_name_ambiguous）。"""
    out = []
    for seg in ("depth1", "depth2"):
        for a in lib.get(seg, []) or []:
            if query == a["id"] or query == a["name"] or query in a["name"]:
                out.append(a)
    return out


def cmd_deep_list(ctx: MutableMapping[str, Any]) -> str:
    """无参数：已达门槛的深度配方一览（AD1／AD2 分组；门槛未达不列——§三 一览口径）。"""
    lib = _lib(ctx)
    consts = _consts(ctx)
    lv = _player_lv(ctx)
    rows: List[str] = []
    for seg, label in (("depth1", "一段"), ("depth2", "二段")):
        for a in lib.get(seg, []) or []:
            base = next((r for r in lib.get("recipes", []) or []
                         if r["id"] == a.get("base_ref")), None)
            base_lv = int(base["craft_lv"]) if base else 0
            if lv >= _gate_lv(base_lv, 1 if seg == "depth1" else 2, consts):
                rows.append(f"├ {a['id']} {a['name']}（{label}·{a['effect']}）")
    if not rows:
        return expand_consts(
            "📜 暂无已达门槛的深度配方 · 门槛＝可制 Lv＋$C.ALCHEMY.DEEP_RANK_STEP，"
            "先 `合成` 练熟练，点亮后此处出一览", consts)
    header = f"【深度炼成 · 一览（熟练 Lv{lv}）】"
    return "\n".join([header] + rows + ["▸ 深度炼成 <序号|名称> 看制造单 / 帮 速查"])


def cmd_deep_make(query: str, ctx: MutableMapping[str, Any]) -> str:
    """制造单：门槛/材料校验 → 深度制造单树（bound 口径 R4 注记）。"""
    lib = _lib(ctx)
    consts = _consts(ctx)
    lv = _player_lv(ctx)
    hits = _match(query, lib)
    if not hits:
        return format_tpl12(f"/深度炼成 {query}")
    if len(hits) > 1:
        return expand_consts(
            "❓ 「{q}」命中多条深度配方 · 发更完整名称或编号".replace("{q}", query), consts)
    a = hits[0]
    seg = 1 if a["id"].startswith("AD-") else 2
    base = next((r for r in lib.get("recipes", []) or [] if r["id"] == a.get("base_ref")), None)
    base_lv = int(base["craft_lv"]) if base else 0
    gate = _gate_lv(base_lv, seg, consts)
    if lv < gate:
        return expand_consts(
            "📓 熟练不够（门槛 Lv{g} · 现Lv{lv}）· 先 `合成` 稳产练熟练"
            "（每次 +$C.ALCHEMY.MASTERY_PER_DEEP），达标自动点亮"
            .replace("{g}", str(gate)).replace("{lv}", str(lv)), consts)
    mult = int(consts.get("C.ALCHEMY.DEEP_COST_MULT", 2))
    mats = base["materials"] if base else a.get("effect", "")
    lines = [
        f"⚗️ 深度炼成 · {a['name']} ×1（{a['id']}·{'一段' if seg == 1 else '二段'}）",
        f"├ 材料（×{mult}）：{mats}" + ("＋潮髓系稀有料 ×1" if seg == 2 else ""),
        f"├ 附加费：深度档费率（§四·3 联算）｜熟练 +"
        f"{consts.get('C.ALCHEMY.MASTERY_PER_DEEP', 2)}",
        f"└ 产物：{a['effect']}（申报系数 ×{a['coef'] if a.get('coef') is not None else '复合申报'}）"
        f"· sellable:false 不绑定（R4）· 不进调和池",
        "▸ 深度炼成（一览）/ 合成（常规稳产）/ 帮 速查",
    ]
    return "\n".join(lines)


def _handler(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    args = [str(a) for a in (getattr(parsed, "args", None) or [])]
    if not args:
        return cmd_deep_list(ctx)
    return cmd_deep_make(args[0], ctx)


def register_cloudsea_deep_commands(
    router: Any,
    make_context: Optional[Any] = None,
    **_: Any,
) -> None:
    """`深度炼成` 注册（R5 独立分账：本文件自持词面/解析/渲染，不并框架炼金指令）。"""
    if router is None:
        raise ValueError("【待接线】cloudsea_deep_commands 需要 router")

    def _h(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if not isinstance(injected, MutableMapping):
            injected = make_context(parsed) if callable(make_context) else {}
        return _handler(parsed, injected)

    router.register(CommandSpec(DEEP_CMD_CLOUDSEA, handler=_h))


__all__ = [
    "DEEP_CMD_CLOUDSEA", "DEFAULTS",
    "cmd_deep_list", "cmd_deep_make", "register_cloudsea_deep_commands",
]
