"""M9 锻造·批2·路2C：素材死锁扫描报告（qbot_rpg/core/forge_deadlock.py）——DEAD-01~07。

文件名：qbot_rpg/core/forge_deadlock.py
创建时间：2026-08-30
作者：Hermes 子agent-2C（M9 锻造实现组批2·路2C：并发同仓，仅新建本文件 +
  tests/unit/test_forge_deadlock.py；不改动批0/批1 已有文件与 fixtures）

功能描述：素材死锁扫描报告（细化_2c2c §四 DEAD-01~07）——对 forge 节点全部
  materials 需求行按素材 id 汇总产出途径数，按档位分级判定是否死锁风险，输出
  缺口建议。W 级不拦截（DEAD-04：普通≥3 途径、稀有≥2 途径；不满足仅提示）。
  - deadlock_report(modules) -> {items, ok}：DEAD-07 死锁扫描报告——每个被 forge
    引用的素材 id 生成一条 {item_id, name, tier, threshold, source_count, sources,
    gap}；sources = 命中的来源通道标签列表（drop/shop/combine/gather/plant/helper）。
  - deadlock_scan_ok(report) -> bool：DEAD-04 W 级不拦截判定——全部素材途径数达标
    → True；存在 gap → False（仅提示不拦截）。
  - deadlock_hint(item_id, report) -> str：DEAD-06 缺口建议文本（「建议补 3:1 合成/
    商店/另一掉落」），无缺口返回空串。
  纯函数确定性（同刻同参必同值）、零 IO 零 NoneBot、不写定时器/睡眠调用。

依据：
  - docs/细化/细化_2c2c_锻造素材经济.md：§四（DEAD-01 主副来源保底 / DEAD-02 三通道
    对策 / DEAD-04 分级保底下限：普通≥3、稀有≥2 / DEAD-06 时间窗口兜底：缺件提示给
    替代途径 / DEAD-07 死锁扫描报告）、§二（TIER-03a material_tier 两档 / CMB-01~03
    3:1 合成 kind=combine / comb_synth_map 普通 id → 稀有 id）、§五 D 验收 TC-18~22。
  - 定稿 §15 风险对策（素材死锁行 L387：3:1 合成 + 商店基础材料 + 分解回收三通道）。
  - docs/m9_shared_contract.md：§六 W4（synth_ratio_3to1=false 且素材死锁风险 → 提示）
    / §三 S-02（synth_ratio_3to1 默认 true）/ §八（items material_tier + source /
    settings.forge 段）。
  - 素材档位两档：qbot_rpg/content/forge_models.py MATERIAL_TIERS / forge_settings.py
    MATERIAL_TIER_VALUES（normal/rare，TIER-03b 与装备品质四档不混用）。
  - 3:1 合成映射：路2A 兄弟文件 qbot_rpg/core/forge_material.py（comb_synth_map）——
    未落盘时本地 try/except import + recipe.json kind=combine 兜底构建（CMB-02）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  途径 = 来源通道类别，每类别至多计 1（对齐 TC-18「稀有甲途径=2（掉落+3:1）」
       、TC-19「comb_synth_map 覆盖 → 途径数 +1」计数口径）。六类：
       drop（怪物掉落，enemies.json drops 或 loot.json）/ shop（商店可买）/
       combine（3:1 合成，仅 settings.synth_ratio_3to1=true 时计，TC-19/TC-11）/
       gather（采集点，maps.json gather_points）/ plant（种植，items seed.output）/
       helper（代工表，若有；缺表不计）。采集/种植/代工表缺失 → 对应来源不计
       （任务契约：缺表则不计）。
  F-2  档位判定（TIER-03a / M-03 双源仲裁）：素材行 tier 覆写（rare）优先；无覆写
       取 items 材料类 material_tier（缺省 normal）。threshold = rare→2 / normal→3
       （DEAD-04 分级保底下限）。
  F-3  孤儿判定（TC-22 闭环无孤儿）：source_count==0 → 该素材不可达（孤儿），计入
       gap（低于任意下限）。报告含 orphan 标记（source_count==0）。
  F-4  deadlock_scan_ok 从 report["items"] 重算（不信任外部 ok 字段），保证纯函数
       确定性；空 items（forge 无素材需求）→ True（无风险即通过）。
  F-5  数据源归一（对齐 loader 形态）：modules["items"] 兼容条目 list / {id: 条目}
       Mapping 两形态；modules["enemies"]/["loot"] 兼容带 drops 段的条目；
       modules["maps"] 采集点取 gather_points[].item；modules["recipe"] combine 段
       取 materials[].id → output.item。settings 读段复用批0 read_forge_settings。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用（M43
零定时器探针）；平台无关；不引入随机；每功能可追溯（文件头标注依据）；不 git commit。
仅依赖标准库 + qbot_rpg.content.forge_settings（read_forge_settings）。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Set, cast

from qbot_rpg.content.forge_settings import read_forge_settings

__all__ = [
    "SOURCE_CHANNELS",
    "CHANNEL_LABELS",
    "TIER_NORMAL",
    "TIER_RARE",
    "THRESHOLD_NORMAL",
    "THRESHOLD_RARE",
    "deadlock_report",
    "deadlock_scan_ok",
    "deadlock_hint",
    "build_comb_synth_map",
    "resolve_comb_synth_map",
]

# =====================================================================================
# 常量：来源通道 / 档位 / 分级保底下限（细化_2c2c DEAD-04 / SOUR-01~05）
# =====================================================================================

# 六类来源通道标签（F-1；途径计数 = 命中的类别数，每类至多 1）
SOURCE_CHANNELS: tuple = ("drop", "shop", "combine", "gather", "plant", "helper")

# 通道中文标签（DEAD-06 缺口建议 / 报告可读）
CHANNEL_LABELS: Dict[str, str] = {
    "drop": "另一掉落",
    "shop": "商店",
    "combine": "3:1 合成",
    "gather": "采集/挖掘",
    "plant": "种植",
    "helper": "代工",
}

# 素材档位两档（TIER-03a / forge_models.MATERIAL_TIERS）
TIER_NORMAL: str = "normal"
TIER_RARE: str = "rare"

# 分级保底下限（DEAD-04：普通 ≥3 途径 / 稀有 ≥2 途径）
THRESHOLD_NORMAL: int = 3
THRESHOLD_RARE: int = 2

_THRESHOLD_BY_TIER: Dict[str, int] = {
    TIER_NORMAL: THRESHOLD_NORMAL,
    TIER_RARE: THRESHOLD_RARE,
}

# 档位判定键（items material_tier / 素材行 tier 覆写；键名照契约 §八/2c2a M-03）
_MATERIAL_TIER_KEY: str = "material_tier"
_ROW_TIER_KEY: str = "tier"


# =====================================================================================
# 归一工具（纯函数，缺省兜底）
# =====================================================================================


def _norm_items(items: object) -> Dict[str, Mapping[str, object]]:
    """items 表归一：条目 list / {id: 条目} Mapping → {id: 条目}（F-5）。"""
    out: Dict[str, Mapping[str, object]] = {}
    if isinstance(items, Mapping):
        for k, v in items.items():
            if isinstance(v, Mapping):
                out[str(k)] = v
        return out
    if isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str):
                out[e["id"]] = e
    return out


def _as_list(value: object) -> List[object]:
    """list/tuple 归一（其余 → []）。"""
    return list(value) if isinstance(value, (list, tuple)) else []


def _drop_item_ids(entry: Mapping[str, object]) -> Set[str]:
    """一条怪/loot 条目的掉落素材 id 集（drops 段 battle/special/death，SOUR-01）。

    兼容形态：entry["drops"] = {battle:[{item}], special:[{item}], death:[{item}]}；
    也兼容 loot.json 平铺条目 {item}（【工程补白】宽松解析）。
    """
    out: Set[str] = set()
    drops = entry.get("drops")
    if isinstance(drops, Mapping):
        for lst in drops.values():
            if not isinstance(lst, (list, tuple)):
                continue
            for row in lst:
                if isinstance(row, Mapping):
                    v = row.get("item") or row.get("id")
                    if isinstance(v, str) and v:
                        out.add(v)
    elif isinstance(entry.get("item"), str) and entry["item"]:
        out.add(cast(str, entry["item"]))
    return out


# =====================================================================================
# 各来源通道的素材 id 集合（F-1 / SOUR-01~05；采集/种植/代工缺表 → 空集）
# =====================================================================================


def _drop_sources(modules: Mapping[str, object]) -> Set[str]:
    """怪物掉落素材集（SOUR-01）：enemies.json drops 段 / loot.json（若有）。"""
    out: Set[str] = set()
    for key in ("enemies", "loot"):
        raw = modules.get(key)
        if isinstance(raw, Mapping):
            # loot.json 顶层 Mapping 形态：{monsters:[...]} 或直接含 drops 段
            inner = raw.get("monsters") if isinstance(raw.get("monsters"), list) else raw
            if isinstance(inner, Mapping) and isinstance(inner.get("drops"), Mapping):
                out |= _drop_item_ids(inner)
            for e in _as_list(inner):
                if isinstance(e, Mapping):
                    out |= _drop_item_ids(e)
        else:
            for e in _as_list(raw):
                if isinstance(e, Mapping):
                    out |= _drop_item_ids(e)
    return out


def _shop_sources(modules: Mapping[str, object]) -> Set[str]:
    """商店可买素材集（SOUR-05）：shop.json items[].item。"""
    out: Set[str] = set()
    for shop in _as_list(modules.get("shop")):
        if not isinstance(shop, Mapping):
            continue
        for row in _as_list(shop.get("items")):
            if isinstance(row, Mapping):
                v = row.get("item") or row.get("id")
                if isinstance(v, str) and v:
                    out.add(v)
    return out


def _combine_sources(modules: Mapping[str, object]) -> Set[str]:
    """3:1 合成产出素材集（CMB-02/CMB-03）：comb_synth_map 的值（稀有 id）。"""
    return set(resolve_comb_synth_map(modules).values())


def _gather_sources(modules: Mapping[str, object]) -> Set[str]:
    """采集点产出素材集（SOUR-02）：maps.json gather_points[].item；缺表 → 空集。"""
    out: Set[str] = set()
    for m in _as_list(modules.get("maps")):
        if not isinstance(m, Mapping):
            continue
        for gp in _as_list(m.get("gather_points")):
            if isinstance(gp, Mapping):
                v = gp.get("item") or gp.get("id")
                if isinstance(v, str) and v:
                    out.add(v)
    return out


def _plant_sources(modules: Mapping[str, object]) -> Set[str]:
    """种植产出素材集（SOUR-03）：items seed 段 output（炼金 L392 收获表形态）。"""
    out: Set[str] = set()
    items = modules.get("items")
    entries: List[object] = []
    if isinstance(items, Mapping):
        entries = list(items.values())
    elif isinstance(items, list):
        entries = list(items)
    for raw in entries:
        if not isinstance(raw, Mapping):
            continue
        seed = raw.get("seed")
        if seed is True:  # 简单形态：可种植，产出 = 种子自身 id
            rid = raw.get("id")
            if isinstance(rid, str) and rid:
                out.add(rid)
        elif isinstance(seed, Mapping):
            ov = seed.get("output")
            if isinstance(ov, str) and ov:
                out.add(ov)
    return out


def _helper_sources(modules: Mapping[str, object]) -> Set[str]:
    """代工表产出素材集（SOUR-04）：modules["helper"] 若有 → 扫描；缺表 → 空集。"""
    out: Set[str] = set()
    raw = modules.get("helper")
    if raw is None:
        return out
    for e in _as_list(raw):
        if not isinstance(e, Mapping):
            continue
        v = e.get("item") or e.get("id")
        if isinstance(v, str) and v:
            out.add(v)
    return out


# =====================================================================================
# 3:1 合成映射（CMB-02）：普通 id → 稀有 id
# =====================================================================================


def build_comb_synth_map(recipe: object) -> Dict[str, str]:
    """从 recipe.json kind=combine 实例构建 comb_synth_map（CMB-02 兜底实现）。

    combine 实例形态：{kind:"combine", materials:[{id:普通素材, count:3}],
    output:{item:稀有素材, count:1}} → map[普通 id] = 稀有 id。每输入映射一条；
    多个输入同输出 → 各自映射（同系升档）。
    """
    out: Dict[str, str] = {}
    for r in _as_list(recipe):
        if not isinstance(r, Mapping):
            continue
        if r.get("kind") != "combine":
            continue
        outp = r.get("output")
        if not isinstance(outp, Mapping):
            continue
        oid = outp.get("item")
        if not isinstance(oid, str) or not oid:
            continue
        for m in _as_list(r.get("materials")):
            if isinstance(m, Mapping):
                mid = m.get("id") or m.get("item")
                if isinstance(mid, str) and mid:
                    out.setdefault(mid, oid)
    return out


def resolve_comb_synth_map(modules: Mapping[str, object]) -> Dict[str, str]:
    """comb_synth_map 解析：路2A 兄弟模块优先，未落盘 → recipe kind=combine 兜底。

    兄弟文件 qbot_rpg/core/forge_material.py 的 comb_synth_map 为函数形态
    comb_synth_map(modules) -> Dict[str, str]（CMB-02 登记表：输入素材 id → 输出
    素材 id）。落地后直接调用对齐真实代码；未落盘（ImportError）/ 未导出（AttributeError）
    → 本地 build_comb_synth_map(modules["recipe"]) 兜底（任务契约：sibling 落盘后
    读真实代码对齐，未落盘时本地兜底）。兄弟函数异常 → 兜底（确定性不抛）。
    """
    try:
        from qbot_rpg.core.forge_material import comb_synth_map
        if callable(comb_synth_map):
            out = comb_synth_map(modules)
            if isinstance(out, Mapping):
                return dict((str(k), str(v)) for k, v in out.items()
                            if isinstance(k, str) and isinstance(v, str) and k and v)
        elif isinstance(comb_synth_map, Mapping):
            return dict((str(k), str(v)) for k, v in comb_synth_map.items()
                        if isinstance(k, str) and isinstance(v, str) and k and v)
    except Exception:
        pass
    return build_comb_synth_map(modules.get("recipe"))


# =====================================================================================
# forge 素材需求收集 + 档位判定
# =====================================================================================


def _collect_material_rows(forge: object) -> Dict[str, List[str]]:
    """遍历 forge 树节点全部 materials 需求行（M-01）→ {素材 id: [行 tier 覆写...]}。

    行 tier 覆写（M-03，rare/normal）收集供档位仲裁（F-2）；行 item 缺失/非 str
    → 跳过（畸形行由批0 V10/V11 硬拦，本层宽松跳过）。节点/树畸形跳过。
    """
    out: Dict[str, List[str]] = {}
    if not isinstance(forge, Mapping):
        return out
    for tree in _as_list(forge.get("trees")):
        if not isinstance(tree, Mapping):
            continue
        for node in _as_list(tree.get("nodes")):
            if not isinstance(node, Mapping):
                continue
            for row in _as_list(node.get("materials")):
                if not isinstance(row, Mapping):
                    continue
                mid = row.get("item") or row.get("id")
                if not isinstance(mid, str) or not mid:
                    continue
                tier = row.get(_ROW_TIER_KEY)
                out.setdefault(mid, [])
                if isinstance(tier, str) and tier:
                    out[mid].append(tier)
    return out


def _tier_of(
    items_map: Mapping[str, Mapping[str, object]],
    item_id: str,
    row_tiers: List[str],
) -> str:
    """素材档位判定（F-2 / TIER-03a / M-03 双源仲裁）：行覆写 > items 元数据。

    行覆写含 rare → rare（M-03 行覆写优先）；否则 items material_tier=rare → rare；
    其余（含缺省）→ normal（TIER-03a 缺省 normal）。
    """
    if TIER_RARE in row_tiers:
        return TIER_RARE
    entry = items_map.get(item_id)
    if isinstance(entry, Mapping):
        mt = entry.get(_MATERIAL_TIER_KEY)
        if mt == TIER_RARE:
            return TIER_RARE
    return TIER_NORMAL


def _name_of(
    items_map: Mapping[str, Mapping[str, object]],
    item_id: str,
) -> str:
    """素材中文名（items 条目 name；缺 → item_id 兜底）。"""
    entry = items_map.get(item_id)
    if isinstance(entry, Mapping):
        n = entry.get("name")
        if isinstance(n, str) and n:
            return n
    return item_id


def _synth_ratio_on(modules: Mapping[str, object]) -> bool:
    """3:1 合成开关（S-02 / CMB-03）：settings.synth_ratio_3to1（默认 true）。

    读段复用批0 read_forge_settings（settings 含 forge 段或缺段全默认兜底）；
    forge 顶层 settings 段兜底。
    """
    settings_raw = modules.get("settings")
    if not isinstance(settings_raw, Mapping):
        forge = modules.get("forge")
        if isinstance(forge, Mapping) and isinstance(forge.get("settings"), Mapping):
            settings_raw = {"forge": forge["settings"]}
    merged = read_forge_settings(settings_raw)
    v = merged.get("synth_ratio_3to1")
    return v if isinstance(v, bool) else True


# =====================================================================================
# DEAD-07 死锁扫描报告（主入口）
# =====================================================================================


def deadlock_report(modules: Mapping[str, object]) -> Dict[str, object]:
    """素材死锁扫描报告（DEAD-07）：forge 全部素材需求行的途径数汇总 + 缺口判定。

    入参：modules —— loader 形态模块原始数据 dict（forge/items/shop/recipe/enemies/
    maps/settings 等键；缺失键 → 对应来源空集/空表，确定性兜底）。
    出参：{"items": [ItemReport...], "ok": bool}。ItemReport = {item_id, name, tier,
    threshold, source_count, sources, gap, orphan}：
      - item_id/name：素材 id 与中文名（items 表）。
      - tier：档位（normal/rare，行覆写 > items material_tier，F-2）。
      - threshold：分级保底下限（rare→2 / normal→3，DEAD-04）。
      - source_count：命中途径数（六类通道类别计数，每类至多 1，F-1）。
      - sources：命中通道标签列表（确定性顺序：drop/shop/combine/gather/plant/helper）。
      - gap：source_count < threshold（DEAD-04 不达标，W 级不拦截）。
      - orphan：source_count==0（不可达/孤儿素材，TC-22；孤儿必 gap）。
    纯函数确定性：items 按 item_id 排序输出；不改写入参。
    """
    forge = modules.get("forge")
    rows = _collect_material_rows(forge)
    items_map = _norm_items(modules.get("items"))

    drop_set = _drop_sources(modules)
    shop_set = _shop_sources(modules)
    gather_set = _gather_sources(modules)
    plant_set = _plant_sources(modules)
    helper_set = _helper_sources(modules)

    # combine 来源仅开关开启时计入（S-02 / CMB-03 / TC-19：关开关 → 途径数 −1）
    synth_on = _synth_ratio_on(modules)
    combine_set = _combine_sources(modules) if synth_on else set()

    items: List[Dict[str, object]] = []
    for mid in sorted(rows):
        row_tiers = rows[mid]
        tier = _tier_of(items_map, mid, row_tiers)
        threshold = _THRESHOLD_BY_TIER.get(tier, THRESHOLD_NORMAL)

        sources: List[str] = []
        if mid in drop_set:
            sources.append("drop")
        if mid in shop_set:
            sources.append("shop")
        if mid in combine_set:
            sources.append("combine")
        if mid in gather_set:
            sources.append("gather")
        if mid in plant_set:
            sources.append("plant")
        if mid in helper_set:
            sources.append("helper")

        source_count = len(sources)
        gap = source_count < threshold
        items.append(
            {
                "item_id": mid,
                "name": _name_of(items_map, mid),
                "tier": tier,
                "threshold": threshold,
                "source_count": source_count,
                "sources": sources,
                "gap": gap,
                "orphan": source_count == 0,
            }
        )

    ok = all(not it["gap"] for it in items)
    return {"items": items, "ok": ok}


# =====================================================================================
# DEAD-04 W 级不拦截判定 / DEAD-06 缺口建议
# =====================================================================================


def deadlock_scan_ok(report: Mapping[str, object]) -> bool:
    """DEAD-04 W 级不拦截判定：全部素材途径数达标 → True；有 gap → False。

    从 report["items"] 重算（F-4，不信任外部 ok 字段）；空 items → True。
    返回 False 仅表示「存在死锁风险提示」，不阻断加载/锻造（W 级）。
    """
    items = report.get("items")
    if not isinstance(items, (list, tuple)):
        return True
    return all(
        not (isinstance(it, Mapping) and it.get("gap") is True) for it in items
    )


def deadlock_hint(item_id: str, report: Mapping[str, object]) -> str:
    """DEAD-06 缺口建议文本：无缺口 → 空串；有缺口 → 「建议补 X/Y/Z」。

    建议通道 = 未命中且可为该素材补的通道（确定性顺序：combine/shop/drop/gather/
    plant/helper），中文标签以「/」连接（DEAD-06：缺件提示必须给出替代途径，
    禁只写单一来源）。文本示例：
      「素材 火龙鳞（稀有）仅 0 途径，低于下限 2；建议补 3:1 合成/商店/另一掉落」
    item_id 不在报告 → 空串（确定性兜底）。
    """
    items = report.get("items")
    if not isinstance(items, (list, tuple)):
        return ""
    target: Optional[Mapping[str, object]] = None
    for it in items:
        if isinstance(it, Mapping) and it.get("item_id") == item_id:
            target = it
            break
    if target is None or target.get("gap") is not True:
        return ""

    name = str(target.get("name") or item_id)
    tier = str(target.get("tier") or TIER_NORMAL)
    th_raw = target.get("threshold")
    threshold = int(th_raw) if isinstance(th_raw, int) and not isinstance(th_raw, bool) \
        else _THRESHOLD_BY_TIER.get(tier, THRESHOLD_NORMAL)
    sc_raw = target.get("source_count")
    source_count = int(sc_raw) if isinstance(sc_raw, int) and not isinstance(sc_raw, bool) else 0

    src_raw = target.get("sources")
    hit = set(src_raw) if isinstance(src_raw, (list, tuple)) else set()
    missing = [c for c in SOURCE_CHANNELS if c not in hit]
    parts = [CHANNEL_LABELS[c] for c in missing]
    suggestion = "/".join(parts) if parts else "补任一其他来源"
    return (
        f"素材 {name}（{tier}）仅 {source_count} 途径，低于下限 {threshold}；"
        f"建议补 {suggestion}"
    )
