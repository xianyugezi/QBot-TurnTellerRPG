"""批57 · 实例级分解引擎（decompose）——纯函数、可独立测。

文件：qbot_rpg/core/decompose.py
定位：core 纯引擎（同 `core/gem_wallet.py` 风格）。解决报告 **C-4 / R-3**：既有 `/分解`
  按 `item_id` 取物品定义、**无法分解独有的 uid 实例**；本模块提供「按 uid 实例分解」
  的纯计算路径，产出**材料（按 `decompose_rate`）+ 精粹（按 `essence_rate`）**。

两套率**分键、语义相反、不可合键**（报告 **C-5** / 决策记录 N5）：
  · `decompose_rate`（既有，材料回收）：按**生产等级**档 0.40→0.65，**单调递增**；
    本模块**只消费调用方注入的 rate**（由既有 `GemWallet.decompose_rate` 口径解析），
    不自行读取，避免与 `settings.alchemy` / `settings.forge` 双表分叉。
  · `essence_rate`（新，精粹产出）：按品质色序 `β^色序` 的**正向**系数（缺省 β=1.2，
    主 agent C-7 裁定），**单调递增**——与材料回收方向相反但对象/产出物不同，故分键。

真闸门（主 agent ②，替代失效的 `β^色序` 闸门）：
  ① 淬炼投入**不可逆**——`temper_alloc` 不会回到玩家；分解只返还**受衰减的**精粹；
  ② `temper_refund`（每点绝对返还）**随淬炼量衰减**（`refund_decay`），且恒
     `< cost_per_point.essence` ⇒ 每轮「淬炼→分解」净损 ⇒ 无套利（证据见 `core/temper`.
     simulate_cycle` 与 `scripts/batch57_cycle_sim.py`）。

【缺省零变化】`essence_rate.enabled=False` 且调用方不注入 → 本模块不被调用；
  即使被调用，`plan_instance_decompose` 在 scope 不符/未启用时返回拒绝，不改任何状态。

【内容包业务名纪律】不出现任何内容包/物品/属性业务名；材料 id/价格/品质颜色均由调用方注入。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.temper import (
    alloc_total,
    essence_for_instance,
    normalize_essence_config,
    normalize_temper_config,
    resolve_equipment_level,
    total_cap_of,
)

__all__ = [
    "instance_is_crafted",
    "scope_allows",
    "material_recovery",
    "resolve_invested_value",
    "plan_instance_decompose",
    "currency_space",
    "grant_currency",
]


def _as_int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):  # pragma: no cover
        return None
    if f != int(f):
        return None
    return int(f)


def _num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """实例字段双读（ItemInstance dataclass / 落档 dict 行）。"""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def instance_is_crafted(instance: Any) -> bool:
    """是否为「打造产物实例」（报告 §3.4 G2 对象限定判据）。

    判据（任一即打造产物）：带非空 `uid`，且 `required_level > 0`（打造写入的装备等级）
    或 `quality_level > 0`（打造写入的品质等级）或已有 `temper_alloc`（淬炼过）。
    非打造装备（商店/掉落定义级）三项皆空 → False → 精粹 scope 拒。
    """
    if _field(instance, "uid") and (_as_int(_field(instance, "required_level", 0)) or 0) > 0:
        return True
    if _field(instance, "uid") and (_as_int(_field(instance, "quality_level", 0)) or 0) > 0:
        return True
    if _field(instance, "uid") and alloc_total(_field(instance, "temper_alloc", {})) > 0:
        return True
    return False


def scope_allows(instance: Any, cfg: Mapping[str, Any]) -> bool:
    """分解对象范围判定（`essence_rate.scope`：crafted_equipment / all_equipment）。"""
    scope = str(cfg.get("scope") or "crafted_equipment")
    if scope == "all_equipment":
        return bool(_field(instance, "uid")) or bool(_field(instance, "item_id"))
    return instance_is_crafted(instance)


def material_recovery(node_materials: Any, rate: Any,
                      names: Optional[Mapping[str, str]] = None
                      ) -> List[Tuple[str, str, int]]:
    """材料返还（口径对齐既有 `gem_wallet._recover_materials`：**逐材料 id** floor）。

    入参 node_materials：[(material_id, count)] 或 [{"item"/"id":…, "count":…}]。
    出参 [(item_id, 显示名, 返还数)]，返还 0 的材料不进列表。
    """
    r = _num(rate)
    if r is None or r <= 0:
        return []
    out: List[Tuple[str, str, int]] = []
    if not isinstance(node_materials, (list, tuple)):
        return out
    for m in node_materials:
        if isinstance(m, Mapping):
            mid = m.get("item") if m.get("item") is not None else m.get("id")
            cnt = m.get("count")
        elif isinstance(m, (list, tuple)) and len(m) >= 2:
            mid, cnt = m[0], m[1]
        else:
            continue
        if not isinstance(mid, str) or not mid:
            continue
        c = _as_int(cnt)
        if c is None or c < 0:
            continue
        total = int(math.floor(c * r))
        if total <= 0:
            continue
        name = (names or {}).get(mid, mid) if isinstance(names, Mapping) else mid
        out.append((mid, str(name), total))
    return out


def resolve_invested_value(instance: Any, *, node_materials: Any = None,
                           prices: Optional[Mapping[str, Any]] = None,
                           item_def: Any = None,
                           cfg: Mapping[str, Any]) -> float:
    """解析「投入价值 V」（报告 §3.1B；缺省 V1 = 蓝图节点固定材料价值）。

    v_basis：
      · `node_materials`（缺省）→ Σ(节点材料件数 × `prices[id]`)；算不出 → 回退 item_price。
      · `item_price`  → `item_def.price`；
      · `fixed`       → `cfg.v_fixed`；
      · `level_scaled`→ `cfg.v_per_level × 装备等级`。
    """
    basis = str(cfg.get("v_basis") or "node_materials")
    if basis == "fixed":
        return float(_num(cfg.get("v_fixed")) or 0.0)
    if basis == "level_scaled":
        return float(_num(cfg.get("v_per_level")) or 0.0) * resolve_equipment_level(instance, cfg)
    if basis == "node_materials" and isinstance(node_materials, (list, tuple)) \
            and isinstance(prices, Mapping):
        total = 0.0
        for m in node_materials:
            if isinstance(m, Mapping):
                mid = m.get("item") if m.get("item") is not None else m.get("id")
                cnt = m.get("count")
            elif isinstance(m, (list, tuple)) and len(m) >= 2:
                mid, cnt = m[0], m[1]
            else:
                continue
            c = _as_int(cnt)
            p = _num(prices.get(str(mid))) if isinstance(mid, str) else None
            if c is None or c < 0 or p is None:
                continue
            total += c * p
        if total > 0:
            return total
    # item_price 回退
    if isinstance(item_def, Mapping):
        p = _num(item_def.get("price"))
        if p is not None:
            return p
    return 0.0


def plan_instance_decompose(instance: Any, *, cfg: Mapping[str, Any],
                            cfg_temper: Optional[Mapping[str, Any]] = None,
                            node_materials: Any = None,
                            prices: Optional[Mapping[str, Any]] = None,
                            item_def: Any = None, grade: Any = None,
                            material_rate: Any = None,
                            material_names: Optional[Mapping[str, str]] = None,
                            declared_colors: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    """实例级分解计划（纯计算，不落账）：材料 + 精粹。

    出参（ok）：{ok, uid, item_id, materials:[(id,name,count)], material_rate,
      essence:{base,refund,total,color_index}, value, grade, scope}。
    拒绝：{ok:False, reason, message}——未启用 / scope 不符 / uid 缺失 / 无任何产出。
    """
    uid = str(_field(instance, "uid") or "")
    if not uid:
        return {"ok": False, "reason": "no_uid", "message": "该物品没有实例 uid，无法按实例分解"}
    ec = normalize_essence_config(cfg)
    tc = normalize_temper_config(cfg_temper)
    if not ec.get("enabled"):
        return {"ok": False, "reason": "essence_disabled",
                "message": "精粹未启用（settings.forge.essence_rate.enabled=false）"}
    if not scope_allows(instance, ec):
        return {"ok": False, "reason": "scope_not_allowed",
                "message": "该物品不在精粹分解对象范围内"}
    value = resolve_invested_value(instance, node_materials=node_materials,
                                   prices=prices, item_def=item_def, cfg=ec)
    grade_cfg = grade
    materials = material_recovery(node_materials, material_rate, material_names)
    alloc = _field(instance, "temper_alloc", {})
    cap = total_cap_of(resolve_equipment_level(instance, tc), tc)
    essence = essence_for_instance(
        value=value, quality=_field(instance, "quality"), grade=grade_cfg,
        temper_points=alloc_total(alloc), total_cap=cap, cfg=ec,
        declared_colors=declared_colors,
    )
    emap = dict(essence)
    emap.pop("color_index", None)
    if not materials and emap["total"] <= 0:
        return {"ok": False, "reason": "nothing_recovered",
                "message": "该件分解无任何材料/精粹产出"}
    return {
        "ok": True, "reason": None, "uid": uid,
        "item_id": str(_field(instance, "item_id") or ""),
        "materials": materials, "material_rate": _num(material_rate),
        "essence": emap, "essence_color_index": essence.get("color_index", 0),
        "value": value, "grade": grade_cfg, "scope": ec.get("scope"),
        "temper_points": alloc_total(alloc), "total_cap": cap,
    }


def currency_space(settings_currencies: Any) -> Tuple[str, ...]:
    """货币键空间（`settings.currencies[].id`；缺省回退 ('coins','diamond')）。"""
    if isinstance(settings_currencies, (list, tuple)):
        ids: List[str] = []
        for e in settings_currencies:
            eid = e.get("id") if isinstance(e, Mapping) else None
            if isinstance(eid, str) and eid:
                ids.append(eid)
        if ids:
            return tuple(ids)
    return ("coins", "diamond")


def grant_currency(currencies: Any, currency_id: str, amount: Any,
                   space: Sequence[str]) -> Dict[str, Any]:
    """精粹入账（就地改 `currencies`；复刻 `gem_wallet.grant_gem` 的货币键空间硬前置）。

    出参 {ok, reason?, currency, amount, balance?}。未登记该货币 → ok:False（不静默发）。
    """
    amt = _as_int(amount)
    if amt is None or amt < 0:
        return {"ok": False, "reason": "invalid_amount", "message": f"数额非法: {amount!r}"}
    if not isinstance(currencies, MutableMapping):
        return {"ok": False, "reason": "missing_bucket", "message": "货币表缺失，无法入账"}
    cid = str(currency_id or "")
    if cid not in tuple(space or ()):
        return {"ok": False, "reason": "unknown_currency",
                "message": f"「{cid}」未登记在货币键空间（settings.currencies）",
                "currency_space": list(space or ())}
    currencies[cid] = int(currencies.get(cid, 0)) + amt
    return {"ok": True, "reason": None, "currency": cid, "amount": amt,
            "balance": int(currencies[cid])}
