"""九期批次 222 · 装备技能聚合器与 27 技三档注入（gear_skill 条件扩展）。

定位：**可选加载的纯函数工具**（§三承诺：不改 combo/effects/marks 既有行为；
不 import 战斗引擎任何模块）。消费方＝content/cloudsea（223 装备全量接线）与
`skill_tiers.json` 数据面；装配层不注册本模块即不存在。

27 技三档口径（`现行口径速查.md` §三；`12` §S 键域）：
  - 档① 基础档：固有技能固定①档，跨套装生效；
  - 档②③：套装同名可叠全身 ≤3 档；质变档每套 ≤1 条（满 5 件质变仅
    王骸系与巨兽系 ★7–9）。
  - 数值精化（per-tier 实值）＝`18_/07_技能词表` 词面域，223 装备全量接线时
    以 `$C.SKILL.*` 键引回填；本模块只做**结构注入与条件判定**。

条件扩展（gear_skill 条件）：gear 条目可声明
    {"set": <套装id>, "count": <件数阈值>, "tier": <达档>}
聚合器按「已装备件数 ≥ 阈值 → 该档解锁」单调判定；多条件取最高达档。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

TIERS: tuple = (1, 2, 3)
#: 质变档（档③）套装亲和白名单——满 5 件质变仅王骸系与巨兽系 ★7–9（§三 三规则）
MUTATION_AFFINITY: frozenset = frozenset({"王骸", "巨兽"})

__all__ = ["TIERS", "MUTATION_AFFINITY", "load_tiers", "resolve_tier", "aggregate_gear_skills"]


def load_tiers(path: str) -> Dict[str, Any]:
    """读取 skill_tiers.json（27 技三档骨架）；非法 JSON → {"techs": []} 兜底。

    纯 IO、零引擎依赖；文件缺失 → 空表（可选加载语义：无数据 = 无注入）。
    """
    try:
        import json

        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 可选加载：缺文件/坏文件 → 空表
        return {"techs": []}
    return data if isinstance(data, dict) and isinstance(data.get("techs"), list) else {"techs": []}


def resolve_tier(gear: Sequence[Mapping[str, Any]], tech: Mapping[str, Any]) -> int:
    """单技达档判定：gear（已装备条目 [{set, count}]）逐条件比对技的 tiers 门。

    tech 形态（skill_tiers.json 条目）：
        {"tech": 破浪, "line": 攻势, "tiers": [{"tier": 1, "gate": null},
                {"tier": 2, "gate": {"set": "王骸", "count": 2}},
                {"tier": 3, "gate": {"set": "王骸", "count": 5, "mutation": true}}]}
    档① gate=null 恒解锁；达档取满足条件的最高 tier；无 tiers 键 → 1。
    纯函数。
    """
    tiers = tech.get("tiers") if isinstance(tech, Mapping) else None
    if not isinstance(tiers, list) or not tiers:
        return 1
    equipped: Dict[str, int] = {}
    for g in gear or ():
        if isinstance(g, Mapping) and g.get("set"):
            equipped[str(g["set"])] = equipped.get(str(g["set"]), 0) + int(g.get("count", 1) or 1)
    best = 1
    for t in tiers:
        if not isinstance(t, Mapping):
            continue
        tier_no = int(t.get("tier", 1) or 1)
        gate = t.get("gate")
        if gate is None:
            best = max(best, tier_no)
            continue
        if not isinstance(gate, Mapping):
            continue
        need_set = str(gate.get("set", ""))
        need_n = int(gate.get("count", 1) or 1)
        if equipped.get(need_set, 0) >= need_n:
            best = max(best, tier_no)
    return min(best, max(TIERS))


def aggregate_gear_skills(base_skills: Sequence[Mapping[str, Any]],
                          techs: Sequence[Mapping[str, Any]],
                          gear: Sequence[Mapping[str, Any]],
                          base_index: Optional[Mapping[str, int]] = None) -> List[Dict[str, Any]]:
    """27 技三档注入：基础技能 + 装备达档 → 档位变体派生列表。

    base_skills ＝ 既有 skills.json 条目（被 gear 技引用的档①母体）；
    techs ＝ skill_tiers.json["techs"]；gear ＝ 已装备 [{set, count}]。
    产出：新列表（不 mutate 入参）＝base_skills 原样 ＋ 达档 ≥2 的技追加
    派生条目 {"id": "<base>#t2", "derive_only": True, "tier": n, ...母体字段拷贝}。
    质变档（档③）对非亲和套装（MUTATION_AFFINITY 外）自动降档为 2——
    §三「满 5 件质变仅王骸系与巨兽系 ★7–9」的聚合器侧表达。
    纯函数、零副作用、零引擎 import。
    """
    out: List[Dict[str, Any]] = [dict(s) for s in base_skills or ()]
    idx = base_index if base_index is not None else {str(s.get("id")): i for i, s in enumerate(out)}
    for tech in techs or ():
        if not isinstance(tech, Mapping):
            continue
        tier = resolve_tier(gear, tech)
        if tier < 2:
            continue
        base_id = str(tech.get("base_skill", ""))
        i = idx.get(base_id)
        if i is None:
            continue
        for n in range(2, tier + 1):
            if n == 3:
                affinity = any(a in str(tech.get("affinity", "")) for a in MUTATION_AFFINITY)
                gate3 = next((t.get("gate") for t in tech.get("tiers", [])
                              if isinstance(t, Mapping) and t.get("tier") == 3), None)
                if not affinity and isinstance(gate3, Mapping):
                    need_set = str(gate3.get("set", ""))
                    if not any(a in need_set for a in MUTATION_AFFINITY):
                        continue  # 非亲和套装：质变档不注入（§三 三规则）
            variant = dict(out[i])
            variant["id"] = f"{base_id}#t{n}"
            variant["derive_only"] = True
            variant["tier"] = n
            variant["name"] = f"{variant.get('name', base_id)}·档{('①②③')[n - 1]}"
            out.append(variant)
    return out
