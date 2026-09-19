"""相性通用层（批38 · ④）——**打造与深度炼金共用**，非打造私有。

依据：`docs/深度打造_决策记录.md` §三 补充 2（相性是通用机制、落通用层、不得两处各写一套）
+ `打造系统_原案_20260919.md` §8/§12（材料相性词缀；互动冲突/增幅/反转；结算按投入顺序；
主=最高、副=第二；通用池+专属池；特殊联动覆盖专属池；「本质一个池子，没相性就抽不出来」）
+ `打造系统_A_框架映射与数据模型.md` B-4/B-9（相性/池/联动/材料互动 schema 草案）。

本模块只提供**定义 + 计算 + 校验（校验见 content/validator）+ 查询接口**；**不接任何打造
流程、不做炼金消费**（批40/41/46 消费）。框架零内容包业务名（相性 id/池 id/词条键全部由
内容包声明）。

数据落点（全部 `settings` 顶层，通用层；见 field_meta.SETTINGS_FIELDS）：
  · `settings.affinities[]`       相性定义 `{id, name, desc, exclusive_pool}`
  · `settings.affinity_pools[]`   池 `{id, kind ∈ common/exclusive/linkage, entries[], desc}`
      entries[] 行 `{stat | effect_ref, weight, min_level, requires_affinity, value_rule}`
  · `settings.affinity_linkage[]` 联动 `{main, sub, override_pool}`
  · `settings.affinity_reactions[]` 材料互动 `{kind, from, to, pair, value}`
      kind ∈ conflict/amplify/reverse（互相减少/互相增加/A→B 转换）
材料/图纸的相性声明 = items/equipment 条目 `affinities`：`{相性id: 数值}`（图纸是物品的一种）。

对外**单一查询接口**：`resolve_available_entries(config, main, sub, level=None)` —— 给定主/副
相性 → 可用词条集合（通用池 ∪ 专属池；联动命中 → 专属池被 override_pool 覆盖；无相性 →
要求相性的词条抽不出）。

深度炼金接入点（**稳定 API**，本批不实现消费）：
  · 累积：`accumulate_affinity(contributions, reactions)` → 主/副相性输入；
  · 判定：`rank_affinities(values, order)` → (main, sub)；
  · 选池：`resolve_available_entries(config, main, sub, level)` → 药剂效果候选词条集；
  · 取效果：`resolve_affinity_effect(effect_table, main, sub)` → 按 (主[,副]) 取包声明的效果值。

铁律：零 NoneBot import；core 层零 import content（配置经参数注入）；纯函数确定性
（同刻同参必同值；不读全局 random/时间）；完整类型标注（typing 3.9 兼容）；不写内容包。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.data.affinity_keys import (
    AFFINITY_KEYS,
    POOL_COMMON,
    POOL_EXCLUSIVE,
    POOL_KINDS,
    POOL_LINKAGE,
    REACTION_AMPLIFY,
    REACTION_CONFLICT,
    REACTION_KINDS,
    REACTION_REVERSE,
    affinity_requires,
)

__all__ = [
    "POOL_COMMON",
    "POOL_EXCLUSIVE",
    "POOL_LINKAGE",
    "POOL_KINDS",
    "REACTION_CONFLICT",
    "REACTION_AMPLIFY",
    "REACTION_REVERSE",
    "REACTION_KINDS",
    "AFFINITY_KEYS",
    "normalize_affinity_config",
    "accumulate_affinity",
    "rank_affinities",
    "resolve_available_entries",
    "resolve_affinity_effect",
]

_MISSING = object()


# ---------------------------------------------------------------------------
# 归一（只读、防御性；非法值由校验器红拦，引擎不静默改写作者数据）
# ---------------------------------------------------------------------------
def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _requires_of(entry: Mapping[str, Any]) -> Tuple[str, ...]:
    """词条行 `requires_affinity`（str 或 list）→ 相性 id 元组（缺省空 = 通用）。"""
    return affinity_requires(entry)


def normalize_affinity_config(settings: Any) -> Dict[str, Any]:
    """settings（或仅含相性四段的映射）→ 归一配置视图（纯读，不改原值）。

    出参 `{affinities: {id: {…}}, affinity_list: [...], pools: {id: {…}}, pool_list: [...],
    linkage: [...], reactions: [...]}`；缺段/非法 → 空容器（行为 = 无相性：通用池仍可查）。
    """
    src = _as_map(settings)
    affinities: Dict[str, Dict[str, Any]] = {}
    affinity_list: List[Dict[str, Any]] = []
    for row in _as_list(src.get("affinities")):
        m = _as_map(row)
        aid = m.get("id")
        if not isinstance(aid, str) or not aid:
            continue
        rec = {
            "id": aid,
            "name": str(m.get("name") or aid),
            "desc": str(m.get("desc") or ""),
            "exclusive_pool": str(m.get("exclusive_pool") or ""),
        }
        affinities.setdefault(aid, rec)  # 重复 id 保留首个（校验器红拦）
        affinity_list.append(rec)

    pools: Dict[str, Dict[str, Any]] = {}
    pool_list: List[Dict[str, Any]] = []
    for row in _as_list(src.get("affinity_pools")):
        m = _as_map(row)
        pid = m.get("id")
        if not isinstance(pid, str) or not pid:
            continue
        kind = str(m.get("kind") or POOL_COMMON)
        entries = [
            dict(_as_map(e)) for e in _as_list(m.get("entries")) if isinstance(e, Mapping)
        ]
        rec = {"id": pid, "kind": kind, "desc": str(m.get("desc") or ""), "entries": entries}
        pools.setdefault(pid, rec)
        pool_list.append(rec)

    linkage = [dict(_as_map(r)) for r in _as_list(src.get("affinity_linkage"))
               if isinstance(r, Mapping)]
    reactions = [dict(_as_map(r)) for r in _as_list(src.get("affinity_reactions"))
                 if isinstance(r, Mapping)]
    return {
        "affinities": affinities,
        "affinity_list": affinity_list,
        "pools": pools,
        "pool_list": pool_list,
        "linkage": linkage,
        "reactions": reactions,
    }


# ---------------------------------------------------------------------------
# 材料互动结算（结算顺序 = 材料投入顺序；原案 §12）
# ---------------------------------------------------------------------------
def accumulate_affinity(
    contributions: Sequence[Any],
    reactions: Sequence[Any] = (),
) -> Dict[str, float]:
    """按**材料投入顺序**累计相性值并结算互动（冲突/增幅/反转）。

    入参：
      · contributions：材料（或图纸）相性声明，**按投入顺序**排列；每项 `{相性id: 数值}`。
        图纸相性可作为一个前置/附带贡献项，位置由调用方决定（框架不写死顺序）。
      · reactions：相性互动规则（`settings.affinity_reactions`）。
    出参：`{相性id: 结算后数值}`（≥0，负值截零；确定性、纯函数、不改入参）。

    结算口径（三类；每次投入材料时按下列 1→2→3 顺序结算一次，故整体 = 投入顺序）：
      1) **反转 reverse**：本次材料携带 `from` → 已累计的 `from` 按 `value` 比例转入 `to`
         （`value` 缺省/≥1 = 全额转换；0<value<1 = 按比例；结果保留在 `to`）。
      2) **累加**：把本次材料的相性值加到池上。
      3) **冲突 conflict / 增幅 amplify**：规则 `pair=[X,Y]`，当「本次新材料带来 X 且池中已有 Y」
         （或反之）时，对 X 与 Y **同时**施加 `∓value`（冲突减、增幅加），随后负值截零。
        仅在其中一方为新投入时触发一次（= 顺序敏感；同一次材料内不自我触发）。

    工程补白：本条 `value` 语义（差值/比例）与「互相」的施加方式无原案明确定义，按上述可算、
    可测、可复现口径实现并在此显式标注，便于后续按实测定稿调整（参数全在包声明）。
    """
    opts: Dict[str, Any] = {}
    for r in reactions:
        m = _as_map(r)
        kind = m.get("kind")
        if kind in (REACTION_CONFLICT, REACTION_AMPLIFY, REACTION_REVERSE):
            opts.setdefault(kind, []).append(m)
    reverses = opts.get(REACTION_REVERSE, [])
    pairs = opts.get(REACTION_CONFLICT, []) + opts.get(REACTION_AMPLIFY, [])

    pool: Dict[str, float] = {}

    def _add(k: str, v: float) -> None:
        pool[k] = max(0.0, pool.get(k, 0.0) + v)

    for contrib in contributions:
        cm = _as_map(contrib)
        vals: Dict[str, float] = {}
        for k, v in cm.items():
            fv = _as_float(v)
            if isinstance(k, str) and k and fv is not None and fv != 0:
                vals[k] = fv
        if not vals:
            continue
        # 1) 反转（由本次材料携带的 from 触发；先于累加）
        for r in reverses:
            src = r.get("from")
            dst = r.get("to")
            if not (isinstance(src, str) and src in vals
                    and isinstance(dst, str) and dst):
                continue
            ratio = _as_float(r.get("value"))
            ratio = 1.0 if ratio is None else min(max(ratio, 0.0), 1.0)
            moved = pool.get(src, 0.0) * ratio
            if moved:
                _add(src, -moved)
                _add(dst, moved)
        # 2) 累加
        prev_keys = set(pool.keys())
        for k, v in vals.items():
            _add(k, v)
        # 3) 冲突/增幅（仅在「一方新投入、另一方已在池中」时触发一次）
        for r in pairs:
            pair = r.get("pair")
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                continue
            x, y = str(pair[0]), str(pair[1])
            if not x or not y or x == y:
                continue
            if (x in vals and y in prev_keys) or (y in vals and x in prev_keys):
                mag = _as_float(r.get("value"))
                if mag is None:
                    continue
                if r.get("kind") == REACTION_CONFLICT:
                    mag = -mag
                _add(x, mag)
                _add(y, mag)
    return pool


# ---------------------------------------------------------------------------
# 主/副相性判定（最高 = 主、第二 = 副）
# ---------------------------------------------------------------------------
def rank_affinities(
    values: Any,
    order: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """累计值 → 主/副相性（最高 = 主，第二 = 副；原案 §8）。

    入参：
      · values：`{相性id: 数值}`（≤0 不算入排名）。
      · order：相性**声明顺序**（内容包 `affinities[]` 顺序）；用于并列时确定性破平
        （先声明者优先；缺省按 id 升序）。
    出参：`{main, sub, ranked: [(id, value), ...]}`；无正值 → main/sub 均 None。
    纯函数、确定性。
    """
    vm = _as_map(values)
    pos = {str(k): _as_float(v) for k, v in vm.items()}
    pos = {k: v for k, v in pos.items() if v is not None and v > 0}
    order_index: Dict[str, int] = {}
    for i, x in enumerate(_as_list(order)):
        m = _as_map(x)
        aid = m.get("id") if m else x
        if isinstance(aid, str) and aid:
            order_index.setdefault(aid, i)
    ranked = sorted(pos.items(), key=lambda kv: (-kv[1], order_index.get(kv[0], 1 << 30), kv[0]))
    return {
        "main": ranked[0][0] if ranked else None,
        "sub": ranked[1][0] if len(ranked) > 1 else None,
        "ranked": ranked,
    }


# ---------------------------------------------------------------------------
# 池查询（对外单一接口）
# ---------------------------------------------------------------------------
def _entries_of(pool: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(pool, Mapping):
        return []
    out: List[Dict[str, Any]] = []
    for e in _as_list(pool.get("entries")):
        m = _as_map(e)
        if m:
            row = dict(m)
            row.setdefault("_pool", str(pool.get("id") or ""))
            row.setdefault("_pool_kind", str(pool.get("kind") or ""))
            out.append(row)
    return out


def _matched_linkage(config: Mapping[str, Any], main: Optional[str],
                     sub: Optional[str]) -> Optional[Mapping[str, Any]]:
    if not main:
        return None
    for r in config.get("linkage", []):
        rm = _as_map(r)
        if rm.get("main") == main and rm.get("sub") == (sub or ""):
            return rm
        if rm.get("main") == main and rm.get("sub") in (None, "") and not sub:
            return rm
    return None


def resolve_available_entries(
    config: Any,
    main: Optional[str] = None,
    sub: Optional[str] = None,
    level: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """**对外单一查询接口**：给定主/副相性 → 可用词条集合（原案 §8/§12 池语义）。

    入参：
      · config：`normalize_affinity_config(settings)` 结果，或 settings/含四段的映射
        （内部会再归一，容错双形态）。
      · main / sub：主/副相性 id（可 None = 无相性）。
      · level：装备/药剂等级（给定时按词条行 `min_level` 过滤；缺省不过滤）。
    出参：可用词条行列表（保留声明顺序；每行附 `_pool` / `_pool_kind` 便于追溯）。

    候选构造（「只开启通用池 + 专属池」）：
      ① 通用池（所有 kind=common 的池的全部 entries）；
      ② 主相性专属池（`affinities[main].exclusive_pool` 指向的池）；
      ③ 若 (main, sub) 命中 `affinity_linkage` → ②被 `override_pool` **覆盖**（特殊联动池也是
         专属池的一种）；
      ④ 过滤：`requires_affinity` 必须 ⊆ {main, sub}（**无相性 → 该词条抽不出**）；
         `min_level` 高于 level 的条目排除。
    纯函数、确定性（同刻同参必同值）。
    """
    cfg = config if isinstance(config, Mapping) and "affinity_list" in config \
        else normalize_affinity_config(config)
    affinities = cfg.get("affinities", {})
    pools = cfg.get("pools", {})

    candidates: List[Dict[str, Any]] = []
    for pool in cfg.get("pool_list", []):
        if _as_map(pool).get("kind") == POOL_COMMON:
            candidates.extend(_entries_of(pool))

    main_rec = affinities.get(main) if isinstance(main, str) else None
    linkage = _matched_linkage(cfg, main, sub)
    if linkage is not None:
        candidates.extend(_entries_of(pools.get(str(linkage.get("override_pool") or ""))))
    elif isinstance(main_rec, Mapping):
        candidates.extend(_entries_of(pools.get(str(main_rec.get("exclusive_pool") or ""))))

    have = {x for x in (main, sub) if isinstance(x, str) and x}
    out: List[Dict[str, Any]] = []
    for entry in candidates:
        reqs = _requires_of(entry)
        if any(r not in have for r in reqs):
            continue
        min_level = entry.get("min_level")
        if level is not None and isinstance(min_level, int) and not isinstance(min_level, bool):
            if int(level) < min_level:
                continue
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# 深度炼金接入点（效果取值；稳定 API，本批不消费）
# ---------------------------------------------------------------------------
def resolve_affinity_effect(
    effect_table: Any,
    main: Optional[str],
    sub: Optional[str] = None,
) -> Any:
    """相性 → 效果 的**稳定取值接口**（深度炼金消费点；批38 只留 API）。

    `effect_table` 形态（内容包声明，框架不内置任何相性/效果名）：
      · `{主相性id: 效果}`；
      · `{"<主>|<副>": 效果}`（更具体的键优先）。
    查表顺序：`"main|sub"` → `"main"` → None。找到返回值（任意 JSON 值）；无 → None。
    纯函数、确定性；**不做任何业务解释**（效果含义由炼金侧定义）。
    """
    table = _as_map(effect_table)
    if not table:
        return None
    m = main if isinstance(main, str) else ""
    s = sub if isinstance(sub, str) else ""
    if m and s:
        v = table.get(f"{m}|{s}", _MISSING)
        if v is not _MISSING:
            return v
    if m:
        v = table.get(m, _MISSING)
        if v is not _MISSING:
            return v
    return None
