"""批62 · 装备淬炼独立指令壳 `/淬炼`（批57 引擎/状态/配置/校验之上**只差指令**）。

文件：qbot_rpg/commands/temper_commands.py
定位：对齐 `commands/enhance_commands.py`（强化壳）与 `/分解` 实例分支的既有风格——
  **数值/上限/消耗/物化全部委托 `core/temper.py`**（唯一源），本壳只做「定位实例 → 调引擎
  → 落账 → 出文案」。批57 已备：`core/temper.py`（纯引擎）+ `ItemInstance.temper_alloc`/
  `required_level`（状态）+ `enhance.json → temper`（配置）+ `enhance_models` V8~V13（校验）+
  `storage` 缺补迁移；本批按报告 C-1「引擎独立 + 一个指令壳」补齐末尾一环。

功能（最小交互，与规格/报告 §2 一致）：
  · `/淬炼 <装备>`：**只读查看**上限 / 已投 / 剩余 / 每点消耗；
  · `/淬炼 <装备> <属性>*<点数>[,…]`：**执行**单项/多项淬炼（先全量校验、再一次性落账，
    任一项越限/精粹不足则整条拒绝——不半扣）；
  · 未启用 / 越限 / 精粹不足 / 属性非法 → 模板表人话提示（不崩、不静默）。

参数形态（既有约定，`docs/深度打造_决策记录.md` / 炼金定稿 :12）：数量用 `*`（点数，
缺省 `temper.points_per_action`）、多项用 `,`（逐项 `属性*点数`）；沿用 `/精造` 的
「自由参数」登记（多位置参数豁免 S7 铁律 3）。

铁律：
  · 零 NoneBot import；文案**一律**走模板表（本模块零硬编码文案、**禁 emoji**）；
  · 不含任何内容包业务名（装备/属性/货币名全部来自内容包声明与实例）；
  · 缺省零变化：`temper.enabled=false` / 无 `enhance` 段 → 只回「未启用」，不写任何状态。
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.content.enhance_models import parse_enhance_settings
from qbot_rpg.core.temper import (
    allowed_stats_of,
    materialize_temper,
    per_stat_cap_of,
    plan_temper,
    temper_cost,
    total_cap_of,
)
from qbot_rpg.core.templates import tpl_of
from qbot_rpg.data.gear_stats import GEAR_LABELS_ZH

# 同包兄弟模块：相对导入（架构门禁同 enhance_commands / deep_craft_commands 口径）。
from .parsers import ERR_TOO_MANY
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    "TEMPER_CMD",
    "cmd_temper",
    "register_temper_commands",
]

#: 主入口名（批62 全量扫描选定：`router_setup` 注册名 / `CommandSpec.aliases` /
#: `parsers.DEFAULT_WHITELIST` / 各包 `settings.command_aliases` **四源零冲突**，
#: 详见 tests/unit/test_batch62_temper_command.py 的扫描用例）。
TEMPER_CMD: str = "淬炼"

#: 引擎拒绝原因码 → 模板 key（本模块零硬编码文案）。
_REASON_TPL: Dict[str, str] = {
    "disabled": "temper_disabled",
    "invalid_points": "temper_reason_invalid_points",
    "stat_not_allowed": "temper_reason_stat_not_allowed",
    "per_stat_cap": "temper_reason_per_stat_cap",
    "total_cap": "temper_reason_total_cap",
    "not_enough_essence": "temper_reason_not_enough_essence",
}


# ---------------------------------------------------------------------------
# 通用读取（dict / 实例双形态，鸭子类型）
# ---------------------------------------------------------------------------
def _fld(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _cfg(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """`enhance.json → temper` 归一配置（`parse_enhance_settings` 已补默认/回退）。"""
    raw = ctx.get("enhance")
    return parse_enhance_settings(raw).get("temper") or {}


def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 deep_craft_commands 口径）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _fmt_num(v: Any) -> str:
    """数值展示：整数去掉小数点，其余 `%g`（与 enhance_commands._fmt_num 同口径）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return f"{f:g}"


def _currencies(ctx: Mapping[str, Any], player: Any) -> Optional[MutableMapping[str, Any]]:
    """货币桶（`ctx["currencies"]` 优先；缺省玩家 currencies）。"""
    cur = ctx.get("currencies")
    if isinstance(cur, MutableMapping):
        return cur
    if isinstance(player, Mapping):
        c = player.get("currencies")
        return c if isinstance(c, MutableMapping) else None
    c = getattr(player, "currencies", None) if player is not None else None
    return c if isinstance(c, MutableMapping) else None


def _balance(currencies: Any, currency_id: str) -> int:
    if not isinstance(currencies, Mapping):
        return 0
    try:
        return max(0, int(currencies.get(currency_id, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _currency_name(ctx: Mapping[str, Any], currency_id: str) -> str:
    """货币 id → 内容包中文名（缺省回 id；不写死任何业务名）。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        for entry in (settings.get("currencies") or []):
            if isinstance(entry, Mapping) and str(entry.get("id") or "") == currency_id:
                return str(entry.get("name") or currency_id)
    return currency_id


# ---------------------------------------------------------------------------
# 实例定位（名称 / uid / 名称#uid前缀；dict / 实例 / 会话通道三形态）
# ---------------------------------------------------------------------------
def _target_parts(target: Any) -> Tuple[str, str]:
    """目标 → (名称, uid 前缀)；`名称` / `uid` / `名称#uid前缀`（对齐 /分解 口径）。"""
    t = str(target or "").strip()
    if "#" in t:
        name, _, uid = t.partition("#")
        return name.strip(), uid.strip()
    if len(t) == 32 and all(c in "0123456789abcdef" for c in t.lower()):
        return "", t
    return t, ""


def _matches(row: Any, name: str, uid: str) -> bool:
    ruid = str(_fld(row, "uid", "") or "")
    if not ruid:
        return False  # 无实例身份（uid）不可精确淬炼——与 /分解 实例分支同门槛
    if uid:
        if not ruid.lower().startswith(uid.lower()):
            return False
        if not name:
            return True
    rname = str(_fld(row, "name", "") or "")
    rid = str(_fld(row, "item_id", "") or "")
    return rname == name or rid == name


def _find_instances(ctx: Mapping[str, Any], target: Any) -> List[Dict[str, Any]]:
    """按名称/uid 定位装备实例 → [{kind, player/list, index, row}]（保序，含歧义候选）。"""
    name, uid = _target_parts(target)
    if not name and not uid:
        return []
    hits: List[Dict[str, Any]] = []
    player = ctx.get("player")
    if isinstance(player, Mapping):
        inv = player.get("inventory")
        if isinstance(inv, (list, tuple)):
            for idx, row in enumerate(inv):
                if _matches(row, name, uid):
                    hits.append({"kind": "player_dict", "player": player, "index": idx, "row": row})
    elif player is not None and hasattr(player, "inventory"):
        for idx, row in enumerate(tuple(getattr(player, "inventory", ()) or ())):
            if _matches(row, name, uid):
                hits.append({"kind": "player_obj", "player": player, "index": idx, "row": row})
    insts = ctx.get("inventory_instances")
    if isinstance(insts, list):
        for idx, row in enumerate(insts):
            if _matches(row, name, uid):
                hits.append({"kind": "session", "list": insts, "index": idx, "row": row})
    return hits


def _rebuild_row(row: Any, alloc: Mapping[str, int], stats: Mapping[str, float]) -> Any:
    """把新分配/新面板写回实例行（dict → 新 dict；ItemInstance → dataclasses.replace）。"""
    new_alloc = {str(k): int(v) for k, v in alloc.items() if int(v) > 0}
    new_stats = {str(k): float(v) for k, v in stats.items()}
    if isinstance(row, Mapping):
        out = dict(row)
        out["temper_alloc"] = new_alloc
        out["stats_bonus"] = new_stats
        return out
    return dataclasses.replace(row, temper_alloc=new_alloc, stats_bonus=new_stats)


def _write_row(ctx: MutableMapping[str, Any], hit: Mapping[str, Any], new_row: Any) -> None:
    """写回实例行：会话通道标 dirty（runner 合并）；玩家通道重建 inventory（对象→replace）。"""
    kind = hit.get("kind")
    if kind == "session":
        lst = hit.get("list")
        if isinstance(lst, list):
            lst[int(hit["index"])] = new_row
        ctx["_m8_dirty_inventory"] = True
        return
    player = hit.get("player")
    if isinstance(player, MutableMapping):
        inv = list(player.get("inventory") or [])
        inv[int(hit["index"])] = new_row
        player["inventory"] = inv
        return
    inv = list(getattr(player, "inventory", ()) or ())
    inv[int(hit["index"])] = new_row
    ctx["player"] = dataclasses.replace(player, inventory=tuple(inv))


# ---------------------------------------------------------------------------
# 属性解析 / 查看
# ---------------------------------------------------------------------------
def _resolve_stat(raw: Any, allowed: Tuple[str, ...]) -> str:
    """属性 token → 可淬炼属性键（键精确优先；中文名唯一命中回退；否则空）。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if s in allowed:
        return s
    hits = [k for k in allowed if GEAR_LABELS_ZH.get(k) == s]
    return hits[0] if len(hits) == 1 else ""


def _stat_tokens(parsed: Any) -> List[str]:
    """参数 → 属性 token 列表（`,` 列表 → `parsed.targets`；缺省 args[1:] 空格分隔）。

    两种装配路径都要兜住：解析器可能把 `a*1,b*2` 展开进 `targets`，也可能原样留在
    `args[1]`（装配层解析配置差异）——故两者都按 `,` 再拆一次（幂等：已展开的 token
    不含 `,`）。
    """
    targets = getattr(parsed, "targets", None)
    raw = [str(t) for t in targets] if targets else \
        [str(a) for a in (getattr(parsed, "args", None) or [])[1:]]
    out: List[str] = []
    for tok in raw:
        out.extend(part for part in tok.split(",") if part.strip())
    return out


def _render_view(ctx: Mapping[str, Any], row: Any, cfg: Mapping[str, Any],
                 currency_name: str) -> str:
    """只读查看：总上限 / 已投 / 剩余 / 逐属性上限 + 每点消耗。"""
    level = _fld(row, "required_level", 0)
    cap = total_cap_of(level, cfg)
    alloc = _fld(row, "temper_alloc", {}) or {}
    used = sum(max(0, _as_int(v) or 0) for v in alloc.values()) if isinstance(alloc, Mapping) else 0
    name = str(_fld(row, "name", "") or _fld(row, "item_id", "") or "")
    if cap <= 0:
        return tpl_of(ctx, "temper_no_level", {"name": name})
    if used >= cap:
        return tpl_of(ctx, "temper_at_max", {"name": name, "used": used, "cap": cap})
    lines = [tpl_of(ctx, "temper_info_title",
                    {"name": name, "used": used, "cap": cap, "remain": max(0, cap - used)})]
    allowed = allowed_stats_of(_fld(row, "stats_bonus", {}) or {}, cfg)
    for stat in allowed:
        cur = 0
        if isinstance(alloc, Mapping):
            cur = max(0, _as_int(alloc.get(stat)) or 0)
        pcap = per_stat_cap_of(stat, cap, cfg)
        lines.append(tpl_of(ctx, "temper_info_stat_row",
                            {"stat": GEAR_LABELS_ZH.get(stat, stat), "used": cur, "cap": pcap}))
        cost = temper_cost(stat, used, cap, 1, cfg).get("essence", 0)
        lines.append(tpl_of(ctx, "temper_info_cost_row",
                            {"stat": GEAR_LABELS_ZH.get(stat, stat), "cost": cost,
                             "currency": currency_name}))
    return "\n".join(lines)


def _as_int(v: Any) -> Optional[int]:
    """非 bool 整数读取（浮点整数亦可）；非法 → None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return int(f) if f == int(f) else None


# ---------------------------------------------------------------------------
# 执行（先全量校验 → 一次性落账）
# ---------------------------------------------------------------------------
def _parse_specs(parsed: Any, cfg: Mapping[str, Any], allowed: Tuple[str, ...]
                 ) -> Tuple[List[Tuple[str, int]], Optional[str], str]:
    """token 列表 → [(属性键, 点数)]；解析失败 → (部分, 模板 key, 出错 token 名)。"""
    default_n = _as_int(cfg.get("points_per_action")) or 1
    specs: List[Tuple[str, int]] = []
    for tok in _stat_tokens(parsed):
        raw = str(tok).strip()
        if not raw:
            continue
        sname, star, snum = raw.partition("*")
        stat = _resolve_stat(sname, allowed)
        if not stat:
            return specs, "temper_reason_stat_not_allowed", sname
        if star:
            n = _parse_points(snum)
            if n is None:
                return specs, "temper_reason_invalid_points", sname
        else:
            n = default_n
        specs.append((stat, n))
    return specs, None, ""


def _parse_points(raw: Any) -> Optional[int]:
    """点数 token → 正整数（缺省/非法 → None；`*` 后必须写正整数）。"""
    s = str(raw or "").strip()
    if s.isdigit():
        n = int(s)
        return n if n >= 1 else None
    return None


def _execute(ctx: MutableMapping[str, Any], hit: Mapping[str, Any], specs: List[Tuple[str, int]],
             cfg: Mapping[str, Any], currency_id: str, currency_name: str) -> str:
    """单项/多项淬炼：逐项 plan（累计校验）→ 全通过才物化 + 扣精粹 + 写回。"""
    row = hit["row"]
    stats_bonus = _fld(row, "stats_bonus", {}) or {}
    old_alloc = _fld(row, "temper_alloc", {}) or {}
    level = _fld(row, "required_level", 0)
    cap = total_cap_of(level, cfg)
    currencies = _currencies(ctx, hit.get("player") or ctx.get("player"))
    balance = _balance(currencies, currency_id)
    work: Dict[str, int] = {str(k): int(v) for k, v in old_alloc.items()
                            if (_as_int(v) or 0) > 0} if isinstance(old_alloc, Mapping) else {}
    total_cost = 0
    before: Dict[str, float] = {}
    for stat, points in specs:
        plan = plan_temper(stats_bonus, work, stat, points, level=level, cfg=cfg,
                           essence_balance=max(0, balance - total_cost))
        if not plan.get("ok"):
            reason = str(plan.get("reason") or "")
            tkey = _REASON_TPL.get(reason, "temper_reason_invalid_points")
            detail = plan.get("cap") if isinstance(plan.get("cap"), Mapping) else {}
            cost = plan.get("cost") if isinstance(plan.get("cost"), Mapping) else {}
            need = int(cost.get("essence") or 0) if cost else 0
            if reason == "stat_not_allowed":
                return tpl_of(ctx, tkey, {"stat": GEAR_LABELS_ZH.get(stat, stat)})
            if reason == "per_stat_cap":
                return tpl_of(ctx, tkey, {
                    "stat": GEAR_LABELS_ZH.get(stat, stat),
                    "cap": detail.get("per_stat", per_stat_cap_of(stat, cap, cfg)),
                    "used": detail.get("used", 0)})
            if reason == "total_cap":
                return tpl_of(ctx, tkey, {
                    "stat": GEAR_LABELS_ZH.get(stat, stat),
                    "cap": detail.get("total", cap), "used": detail.get("used", 0)})
            if reason == "not_enough_essence":
                return tpl_of(ctx, tkey, {"need": need or int(cost.get("essence") or 0),
                                          "have": max(0, balance - total_cost),
                                          "currency": currency_name})
            return tpl_of(ctx, tkey)
        before.setdefault(stat, float((_fld(row, "stats_bonus", {}) or {}).get(stat, 0.0) or 0.0))
        work = {str(k): int(v) for k, v in plan["new_alloc"].items()}
        total_cost += int((plan.get("cost") or {}).get("essence") or 0)
    if not specs:
        return tpl_of(ctx, "temper_err_stat")
    new_stats = materialize_temper(stats_bonus, old_alloc, work, cfg)
    _write_row(ctx, hit, _rebuild_row(row, work, new_stats))
    if currencies is not None and total_cost > 0:
        currencies[currency_id] = max(0, balance - total_cost)
    name = str(_fld(row, "name", "") or _fld(row, "item_id", "") or "")
    lines = [tpl_of(ctx, "temper_ok_title", {"name": name})]
    for stat, _points in specs:
        key = GEAR_LABELS_ZH.get(stat, stat)
        lines.append(tpl_of(ctx, "temper_ok_stat", {
            "stat": key,
            "cur": _fmt_num(before.get(stat, 0.0)),
            "new": _fmt_num(new_stats.get(stat, before.get(stat, 0.0)))}))
    lines.append(tpl_of(ctx, "temper_ok_cost",
                        {"cost": total_cost, "currency": currency_name}))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def cmd_temper(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/淬炼 <装备> [属性*点数,…]` 主入口（查看 / 执行）。

    守卫：解析错误 → TPL-12；未注册 → 注册门槛；战斗中 → 战斗锁；未启用 → 未启用提示；
    装备未找到 / 同名多件 → 人话提示（不崩、不静默）。
    """
    if getattr(parsed, "error", None):
        # 「参数过多」给专属人话（已登记自由参数，正常不触发；其余解析错误走 TPL-12）。
        if str(parsed.error) == ERR_TOO_MANY:
            return tpl_of(ctx, "temper_err_extra")
        return format_tpl12(_fragment(parsed))
    player = ctx.get("player")
    if player is None:
        return tpl_of(ctx, "temper_register_gate")
    if ctx.get("in_battle"):
        return tpl_of(ctx, "temper_battle_lock")
    cfg = _cfg(ctx)
    if not cfg.get("enabled"):
        return tpl_of(ctx, "temper_disabled")
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "temper_usage")

    target = str(args[0])
    hits = _find_instances(ctx, target)
    if not hits:
        return tpl_of(ctx, "temper_not_found", {"name": target})
    if len(hits) > 1:
        cands = []
        for h in hits:
            cap = total_cap_of(_fld(h["row"], "required_level", 0), cfg)
            alloc = _fld(h["row"], "temper_alloc", {}) or {}
            used = sum(max(0, _as_int(v) or 0) for v in alloc.values()) \
                if isinstance(alloc, Mapping) else 0
            cands.append(tpl_of(ctx, "temper_ambiguous_line", {
                "name": str(_fld(h["row"], "name", "") or _fld(h["row"], "item_id", "") or ""),
                "used": used, "cap": cap}))
        return tpl_of(ctx, "temper_ambiguous", {"candidates": "\n".join(cands)})

    hit = hits[0]
    currency_id = str(cfg.get("essence_currency") or "essence")
    currency_name = _currency_name(ctx, currency_id)
    specs, err, err_stat = _parse_specs(parsed, cfg, allowed_stats_of(
        _fld(hit["row"], "stats_bonus", {}) or {}, cfg))
    if err:
        if err == "temper_reason_stat_not_allowed":
            return tpl_of(ctx, err, {"stat": err_stat})
        return tpl_of(ctx, err)
    if not specs:
        return _render_view(ctx, hit["row"], cfg, currency_name)
    return _execute(ctx, hit, specs, cfg, currency_id, currency_name)


def register_temper_commands(
    router: Any,
    *,
    make_context: Optional[Any] = None,
) -> Any:
    """把 `/淬炼` 注册进 Router（handler 支持 `k.get("ctx")` 装配注入）。"""
    def _ctx(parsed: Any) -> Dict[str, Any]:
        if make_context is None:
            raise RuntimeError(
                "【待接线】temper_commands.register_temper_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _handler(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_temper(parsed, injected)
        return cmd_temper(parsed, _ctx(parsed))

    router.register(CommandSpec(TEMPER_CMD, handler=_handler))
    return router
