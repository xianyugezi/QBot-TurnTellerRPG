"""M9 锻造·批6·路6A：边界铁律接口契约（锻造 100% 确定性 / 带孔唯一来源 / 与炼金·强化·属性弱点
接口契约点 / 费用公式确定性）。

文件名：qbot_rpg/core/forge_bounds.py
创建时间：2026-08-30
作者：Hermes 子agent-6A（M9 锻造实现组批6·路6A：并发同仓，仅新建本文件 +
tests/unit/test_forge_bounds.py；不改动任何已有实现文件）

功能描述（对应规划_路2c2_锻造.md T18「三系统边界与联动闭环」）：
  - determinism_check(modules, settings) -> dict：锻造 100% 确定性校验（定稿 §1.2 边界铁律 1/4：
    「锻造 100% 成功、无随机、随机性不同源」）——扫描 forge 全部节点：无随机字段
    （random/chance/rand/概率/随机 等字段名）、无概率分支、无依赖顺序可变的引用
    （parent/item/output_item 非静态字符串 / branch 非字符串列表 = 序依赖）。返回
    {ok, violations:[{node_id, field, reason}], warnings, scanned_nodes, scanned_fields}；
    violations 为空即 ok=True；W 级（描述字段含「概率/随机」字样）只进 warnings 不拦截。
  - slotted_source_check(settings, modules) -> dict：带孔装备唯一来源校验（定稿 §1.1「锻造=带孔
    装备唯一常规来源」+ §八「锻造产装备带孔位」）——slots 段可配（节点级 slots 即配置位）、
    带孔装备只能由 /锻造 产出：合成(recipe)/掉落(enemies drops)/商店(shop) 表均不得产出
    slots 非空装备；items 中带 slots 条目必须有对应 forge 节点产出。返回
    {ok, violations, warnings, slotted_items, forge_slotted, routes}。
  - alchemy_interface(modules) -> dict：与炼金/强化/属性弱点接口契约（定稿 §1.3 协作闭环 +
    §八 装饰珠联动 + §九 8 属性弱点制 + §十六 三系统对比）——枚举锻造产出可被 炼金镶嵌/强化
    +N/属性弱点 消费的契约点：①炼金镶嵌（带孔装备 slots → 装饰珠 type=装饰珠 嵌入）②强化数值层
    （stats 数值键 ∈ 数值层键空间）③元素通道（stats.element 对齐 alchemy_core ELEMENT_NAMES_CN
    注册表 + monsters weakness.elements 弱点表）。返回 {ok, contracts:[...]}——契约点清单供
    批6B 全链路冒烟消费；元素键不在 alchemy 注册表 = 通道未对齐（如 thunder vs lightning）。
  - forge_fee_check(settings) -> dict：费用结算确定性（定稿 §12.4 forge_fee: 节点等级×10）——
    解析 forge_fee 为「节点等级×N」确定性公式（N 无浮动），金币不足拒绝且零扣减（细化_2c2b
    §1.2 步骤1 原子扣减 / §1.3 失败零副作用）。返回
    {ok, base_fee_per_level, formula, fee_kind, deterministic, gold_insufficient_reject,
     violations} 供冒烟断言。

依据（文件头标注）：
  - /root/docs_archive/RPG框架项目/锻造系统设计定稿.md（v1.0.1）§1.1（带孔唯一来源 L18）、
    §1.2 边界铁律 1~4（L28-32：100% 成功 / 无随机 / 带孔唯一来源 / 随机性不同源）、
    §1.3 协作闭环示例（L35-41：锻造→炼金镶嵌→强化→打弱怪四层叠乘）、
    §八 锻造×装饰珠联动（L188-196：锻造产孔、炼金产珠、孔位等级≥珠等级可镶嵌）、
    §九 锻造×8属性弱点制（L198-205：formula 元素注册表、属性分线、无弱点怪警告不拦截）、
    §十二.4 settings（L354-358：forge_fee 节点等级×10）、
    §十六 三系统对比（L396-407：锻造无随机/炼金品质特性/强化概率成功；产孔→珠插孔联动）。
  - docs/细化/细化_2c2b_锻造流程契约.md §1.2（成功路径：扣素材/扣金币原子写，一次写完无中间态）、
    §1.3（失败零副作用：失败不扣素材不扣金币不加经验）、§4.1（熟练计价）、
    §1.1（守卫 GU-05 素材足够、GU-06 等级足够）。
  - 与邻系统接口（定稿 §十六 / §1.3）：炼金镶嵌消费孔位（孔位等级 ≥ 珠等级）；强化 +N 消费
    数值层（enhance.json 同参数空间，锻造不写数值层）；属性弱点消费元素通道（formula 元素
    注册表 + monsters weakness.elements）。
  - 元素通道口径：锻造侧 FORGE_ELEMENTS（content/forge_models.py L104-106，雷=thunder）；
    炼金侧 ELEMENT_NAMES_CN（core/alchemy_core.py L99-108，雷=lightning）——两注册表键名
    差异由本模块契约点如实上报（不静默归一，暴露配置口径漂移供内容包作者对齐）。
  - 模式参考：core/forge_cascade.py（ForgeNode/validate_forge 消费）、
    content/forge_models.py（_items_map/_enemy_element_weaknesses 引用靶收集）、
    commands/forge_commands.py（_forge_settings/_resolve_cost 读 settings.forge 段）。

【工程补白 · 显式标注】（契约/定稿未给口径处的实现口径，标 B-x）：
  B-1  模块形态：本模块为纯只读校验/枚举（不写玩家存档、不触引擎），modules 为
       {模块名: raw JSON} dict（对齐 validate_forge(modules, report) 形态）；settings 为
       forge 段或完整 settings dict（含 forge 子段时自动取 forge 段，对齐
       forge_commands._forge_settings 口径）。
  B-2  随机字段判定：以「字段名」为硬判据（字段名含 random/chance/rand/prob/luck/seed/roll/
       随机/概率/浮动 任一 token 即随机字段 violation）；字段名正常但值含「概率/随机」字样
       的描述字段（name/desc/source/monster_source/effect/lore）→ W 级 warnings 不拦截
       （定稿 §9 无弱点怪警告、素材来源描述「概率掉落」属文案非机制）。
  B-3  序依赖引用判定：parent/item/output_item 须为静态字符串（None 允许——parent 可为空根）；
       branch 须为字符串列表（id 引用集，天然确定性）；出现 int/float/list/dict 值 →
       violation「依赖引用非静态（序可变）」。node.item/output_item 双写不判序依赖
       （交 forge_models V7 处理）。
  B-4  带孔唯一来源：slots 非空装备的判定以「items 条目自带 slots 非空」∪「forge 节点声明
       slots 非空」为并集；其它产出途径（recipe output / shop items / enemies drops
       battle·special·death）产出该并集内 item → violation。客制开孔（augments kind=slot，
       定稿 §七/§八「开孔道具锻造/掉落/炼金可配」）是给已锻造装备追加孔，不产出新带孔装备
       → 不判违规（登记 routes 说明）。
  B-5  alchemy_interface 契约点结构：contracts 每项 {id, name, consumers, inputs, ok,
       details, issues}；ok 语义=该契约点对齐可消费。整体 ok = 全部契约点 ok。
       元素通道：forge 节点 stats.element 不在 alchemy ELEMENT_NAMES_CN 键集 → 该契约点
       ok=False + issues 列出未对齐键（test_demo 雷剑 element=thunder vs alchemy lightning，
       如实上报）；元素在注册表内但怪物弱点表无该属性 → W 级 issue 不翻转 ok（定稿 §15 警告
       不拦截）。
  B-6  forge_fee_check：forge_fee 缺省 10（S-01 节点等级×10）；"节点等级×10" 字符串解析取
       × 后数字为 base_fee_per_level；int 直接作 base；含随机 token 或解析失败 → ok=False。
       金币不足拒绝零扣减为行为契约（细化_2c2b §1.3 失败零副作用），本函数以
       gold_insufficient_reject=True 登记供冒烟断言（实际拒绝逻辑在 commands 层，已落地）。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用（零定时器、
      零睡眠，仅读数据）；渲染输出无 emoji（仅 ✅/❌ + 排版符号）；每功能可追溯（文件头标注
      依据）；不改动既有实现文件（纯新增本文件 + 测试）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.forge_models import FORGE_ELEMENTS, FORGE_STAT_KEY_SPACE, SLOT_LEVELS
from qbot_rpg.core.alchemy_core import ELEMENT_NAMES_CN

__all__ = [
    "determinism_check",
    "slotted_source_check",
    "alchemy_interface",
    "forge_fee_check",
]

# ---------------------------------------------------------------------------
# 常量（契约口径镜像；B-2 随机 token / B-3 静态引用键 / B-5 元素注册表）
# ---------------------------------------------------------------------------

# 随机字段 token（B-2 硬判据：字段名含其一即随机字段 violation）
_RANDOM_TOKENS: Tuple[str, ...] = (
    "random", "chance", "rand", "prob", "luck", "seed", "roll",
    "随机", "概率", "浮动", "波动",
)

# 描述型字段（值含「概率/随机」字样 → W 级 warnings 不拦截，B-2）
_DESC_FIELDS: Tuple[str, ...] = (
    "name", "desc", "description", "source", "monster_source", "effect", "lore", "note",
)

# 静态引用键（B-3：parent 可 None=根；item/output_item 须字符串）
_REF_KEYS: Tuple[str, ...] = ("parent", "item", "output_item")

# 数值层键空间（定稿 §十六：锻造白值/数值层归 enhance.json 同参数空间；B-5 CP-2）
_NUMERIC_STAT_KEYS: Tuple[str, ...] = tuple(
    k for k in FORGE_STAT_KEY_SPACE
    if k not in ("element", "element_value")
)

# 费用缺省（S-01 节点等级×10）
_DEFAULT_FEE_PER_LEVEL: int = 10
# 费用公式前缀（定稿 §12.4 / 2c2a N-11：forge_fee 节点等级×10）
_FEE_FORMULA_PREFIX: str = "节点等级×"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _as_list(value: object) -> List[object]:
    """归一为 list（None/list/tuple → list；其它 → []）。"""
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _forge_segment(settings: object) -> Mapping[str, object]:
    """settings 归一为 forge 段（B-1）：完整 settings dict 含 forge 子段 → 取子段；
    forge 段本身 / 非 Mapping → 原样（空 Mapping 兜底）。"""
    if isinstance(settings, Mapping):
        seg = settings.get("forge")
        if isinstance(seg, Mapping):
            return seg
        return settings
    return {}


def _iter_forge_nodes(forge: object) -> List[Tuple[int, int, Mapping[str, object]]]:
    """遍历 forge 全部节点 → [(tree_idx, node_idx, node_raw)]（防御形态，纯只读）。"""
    out: List[Tuple[int, int, Mapping[str, object]]] = []
    if not isinstance(forge, Mapping):
        return out
    trees = forge.get("trees")
    if not isinstance(trees, list):
        return out
    for ti, tree in enumerate(trees):
        if not isinstance(tree, Mapping):
            continue
        nodes = tree.get("nodes")
        if not isinstance(nodes, list):
            continue
        for ni, node in enumerate(nodes):
            if isinstance(node, Mapping):
                out.append((ti, ni, node))
    return out


def _iter_keys(value: object, prefix: str) -> List[Tuple[str, str, object]]:
    """递归扫描 dict/list 的叶键 → [(path, key, value)]（限 6 层防异常结构死循环）。"""
    hits: List[Tuple[str, str, object]] = []
    stack: List[Tuple[object, str, int]] = [(value, prefix, 0)]
    while stack:
        cur, path, depth = stack.pop()
        if depth > 6:
            continue
        if isinstance(cur, Mapping):
            for k, v in cur.items():
                key = str(k)
                p = f"{path}.{key}" if path else key
                hits.append((p, key, v))
                if isinstance(v, (Mapping, list, tuple)):
                    stack.append((v, p, depth + 1))
        elif isinstance(cur, (list, tuple)):
            for i, v in enumerate(cur):
                p = f"{path}[{i}]"
                hits.append((p, str(i), v))
                if isinstance(v, (Mapping, list, tuple)):
                    stack.append((v, p, depth + 1))
    return hits


def _hit_random_token(key: str) -> bool:
    """字段名是否命中随机 token（B-2 大小写不敏感）。"""
    low = key.lower()
    return any(tok.lower() in low for tok in _RANDOM_TOKENS)


def _items_map(modules: Mapping[str, object]) -> Dict[str, Mapping[str, object]]:
    """items 模块 → {id: 条目 dict}（list 或 Mapping 形态；非 list → 空 dict）。"""
    out: Dict[str, Mapping[str, object]] = {}
    items = modules.get("items")
    if isinstance(items, list):
        for e in items:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
                out[e["id"]] = e
    elif isinstance(items, Mapping):
        for k, v in items.items():
            if isinstance(k, str) and k and isinstance(v, Mapping):
                out[k] = v
    return out


def _items_slotted(items: Mapping[str, object]) -> Dict[str, Mapping[str, object]]:
    """items 中带孔条目（slots 非空）→ {id: 条目}（B-4）。"""
    out: Dict[str, Mapping[str, object]] = {}
    for iid, e in items.items():
        if not isinstance(e, Mapping):
            continue
        if isinstance(e.get("slots"), (list, tuple)) and e["slots"]:
            out[iid] = e
    return out


# ---------------------------------------------------------------------------
# 1) determinism_check：锻造 100% 确定性（定稿 §1.2 边界铁律 1/4；细化_2c2b §1.2/§1.3）
# ---------------------------------------------------------------------------

def determinism_check(modules: Mapping[str, object], settings: object) -> Dict[str, Any]:
    """锻造 100% 确定性校验（定稿 §1.2 铁律 1/4「锻造 100% 成功、无随机、随机性不同源」）。

    入参：
      - modules：{模块名: raw JSON} dict（含 forge 顶层；items/enemies 可选，本函数不需）。
      - settings：forge 段或完整 settings dict（B-1 归一；本函数仅登记直锻/费用确定性配置态）。

    出参 dict：
      - ok：violations 为空即 True。
      - violations：[{node_id, field, reason}]——硬违规：①随机字段（字段名含 random/chance/
        rand/prob/luck/seed/roll/随机/概率/浮动 任一 token）；②概率分支（上述字段出现在
        产出/素材/改造结构内，含嵌套）；③序依赖引用（parent/item/output_item 非静态字符串、
        branch 含非字符串项）。
      - warnings：[{node_id, field, reason}]——W 级不拦截：描述字段（name/desc/source/
        monster_source/effect/lore）值含「概率/随机」字样（文案非机制，定稿 §9 无弱点怪
        警告同类口径）。
      - scanned_nodes / scanned_fields：扫描规模（可追溯）。

    铁律：纯函数确定性；只读不改写入参；不写定时器/睡眠（零定时器、零睡眠）；零 NoneBot。
    """
    forge = modules.get("forge")
    violations: List[Dict[str, object]] = []
    warnings: List[Dict[str, object]] = []
    scanned_nodes = 0
    scanned_fields = 0

    if isinstance(forge, Mapping):
        for _ti, _ni, node in _iter_forge_nodes(forge):
            node_id = node.get("id")
            node_id_s = str(node_id) if isinstance(node_id, str) and node_id else f"#{_ni}"
            scanned_nodes += 1
            for path, key, value in _iter_keys(node, ""):
                scanned_fields += 1
                # B-2 硬判据：字段名命中随机 token → violation（机制字段）
                if _hit_random_token(key):
                    violations.append({
                        "node_id": node_id_s, "field": path,
                        "reason": f"随机字段 {key!r}（锻造 100% 确定性铁律：无随机/概率字段）",
                    })
                    continue
                # W 级：描述字段值含「概率/随机」字样 → warnings 不拦截（B-2）
                if key in _DESC_FIELDS and isinstance(value, str) and (
                        "概率" in value or "随机" in value):
                    warnings.append({
                        "node_id": node_id_s, "field": path,
                        "reason": "描述文案含「概率/随机」字样（W 级不拦截，非机制随机）",
                    })
                # B-3 序依赖引用：parent/item/output_item 须静态字符串
                if key in _REF_KEYS and value is not None and not isinstance(value, str):
                    violations.append({
                        "node_id": node_id_s, "field": path,
                        "reason": f"引用字段 {key!r} 非静态字符串（序依赖/可变引用，确定性铁律）",
                    })
                # B-3 branch 须字符串列表（id 引用集）
                if key == "branch" and isinstance(value, (list, tuple)):
                    for i, b in enumerate(value):
                        if not isinstance(b, str):
                            violations.append({
                                "node_id": node_id_s,
                                "field": f"{path}[{i}]",
                                "reason": (
                                    f"branch 项 {i} 非字符串 id"
                                    "（分支引用须静态，确定性铁律）"
                                ),
                            })

    _forge_segment(settings)  # 配置态归一（B-1 口径一致；本函数不依赖具体值）
    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "scanned_nodes": scanned_nodes,
        "scanned_fields": scanned_fields,
    }


# ---------------------------------------------------------------------------
# 2) slotted_source_check：带孔装备唯一来源（定稿 §1.1/§八）
# ---------------------------------------------------------------------------

def slotted_source_check(settings: object, modules: Mapping[str, object]) -> Dict[str, Any]:
    """带孔装备唯一来源校验（定稿 §1.1「锻造=带孔装备唯一常规来源」+ §八「锻造产装备带孔位」）。

    入参：
      - settings：forge 段或完整 settings dict（B-1 归一；登记 augments 客制开孔配置态）。
      - modules：{模块名: raw JSON} dict——forge/items 必需；recipe（合成/炼金）、shop（商店）、
        enemies（掉落）可选（缺失 → 该途径不判违规，防御放行）。

    出参 dict：
      - ok：violations 为空即 True。
      - violations：[{source, item_id, reason}]——硬违规：①items 带孔条目（slots 非空）无任何
        forge 节点产出（唯一来源=锻造被绕过）；②recipe output / shop items / enemies drops
        （battle·special·death）产出带孔装备（合成/掉落/商店 表不得产出 slots 非空装备）。
      - warnings：[{source, item_id, reason}]——W 级不拦截：客制开孔（augments kind=slot）存在
        但 settings.augments_enabled=false（开孔渠道被关，非唯一来源违规）。
      - slotted_items：全部带孔装备 item id（并集）。
      - forge_slotted：由 forge 节点产出的带孔 item id。
      - routes：各途径命中带孔装备的 item id（可追溯）。

    铁律：纯函数确定性；只读；零 NoneBot；零定时器/零睡眠；渲染无 emoji。
    """
    violations: List[Dict[str, object]] = []
    warnings: List[Dict[str, object]] = []

    # 收集 forge 产出的带孔 item（B-4）
    forge = modules.get("forge")
    forge_slotted: List[str] = []
    if isinstance(forge, Mapping):
        for _ti, _ni, node in _iter_forge_nodes(forge):
            if isinstance(node.get("slots"), (list, tuple)) and node["slots"]:
                ref = node.get("item") or node.get("output_item")
                if isinstance(ref, str) and ref and ref not in forge_slotted:
                    forge_slotted.append(ref)

    # items 带孔条目（并集）
    items = _items_map(modules)
    items_slotted = _items_slotted(items)
    slotted_ids: List[str] = []
    for iid in sorted(set(list(items_slotted.keys()) + forge_slotted)):
        if iid not in slotted_ids:
            slotted_ids.append(iid)

    # ① items 带孔条目必须由 forge 产出（B-4：唯一来源=锻造）
    for iid in sorted(items_slotted.keys()):
        if iid not in forge_slotted:
            violations.append({
                "source": "items",
                "item_id": iid,
                "reason": "items 条目自带 slots 非空但无 forge 节点产出（带孔唯一来源=锻造被绕过）",
            })

    routes: Dict[str, List[str]] = {
        "recipe": [], "shop": [], "drops": [], "forge": list(forge_slotted),
    }
    slotted_set = set(slotted_ids)

    # ② recipe（合成/炼金）产出带孔装备 → 违规
    recipe = modules.get("recipe")
    if isinstance(recipe, list):
        for r in recipe:
            if not isinstance(r, Mapping):
                continue
            out = r.get("output")
            if isinstance(out, Mapping):
                oi = out.get("item")
                if isinstance(oi, str) and oi in slotted_set and oi not in routes["recipe"]:
                    routes["recipe"].append(oi)
                    violations.append({
                        "source": "recipe",
                        "item_id": oi,
                        "reason": f"合成/炼金配方 {r.get('id')} 产出带孔装备（唯一来源=锻造）",
                    })

    # ③ shop 商店出售带孔装备 → 违规
    shop = modules.get("shop")
    if isinstance(shop, list):
        for s in shop:
            if not isinstance(s, Mapping):
                continue
            for row in _as_list(s.get("items")):
                if not isinstance(row, Mapping):
                    continue
                si = row.get("item")
                if isinstance(si, str) and si in slotted_set and si not in routes["shop"]:
                    routes["shop"].append(si)
                    violations.append({
                        "source": "shop",
                        "item_id": si,
                        "reason": f"商店 {s.get('id')} 出售带孔装备（唯一来源=锻造）",
                    })

    # ④ enemies 掉落带孔装备 → 违规（battle/special/death 三桶）
    enemies = modules.get("enemies")
    if isinstance(enemies, list):
        for m in enemies:
            if not isinstance(m, Mapping):
                continue
            drops = m.get("drops")
            if not isinstance(drops, Mapping):
                continue
            for bucket in ("battle", "special", "death"):
                for row in _as_list(drops.get(bucket)):
                    if not isinstance(row, Mapping):
                        continue
                    di = row.get("item")
                    if isinstance(di, str) and di in slotted_set and di not in routes["drops"]:
                        routes["drops"].append(di)
                        violations.append({
                            "source": "drops",
                            "item_id": di,
                            "reason": f"怪物 {m.get('id')} 掉落带孔装备（唯一来源=锻造）",
                        })

    # 客制开孔配置态（定稿 §八 开孔道具可配：锻造/掉落/炼金；非唯一来源违规，登记 W）
    seg = _forge_segment(settings)
    aug_enabled = seg.get("augments_enabled")
    aug = forge.get("augments") if isinstance(forge, Mapping) else None
    has_slot_aug = False
    if isinstance(aug, Mapping):
        for a in _as_list(aug.get("augments")):
            if isinstance(a, Mapping) and a.get("kind") == "slot":
                has_slot_aug = True
                break
    elif isinstance(aug, list):
        has_slot_aug = any(
            isinstance(a, Mapping) and a.get("kind") == "slot" for a in aug)
    if has_slot_aug and aug_enabled is False:
        warnings.append({
            "source": "augments",
            "item_id": "",
            "reason": (
                "客制开孔（augments kind=slot）存在但 augments_enabled=false"
                "（开孔渠道被关，W 级）"
            ),
        })

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "slotted_items": slotted_ids,
        "forge_slotted": list(forge_slotted),
        "routes": routes,
    }


# ---------------------------------------------------------------------------
# 3) alchemy_interface：与炼金/强化/属性弱点接口契约（定稿 §1.3/§八/§九/§十六）
# ---------------------------------------------------------------------------

def alchemy_interface(modules: Mapping[str, object]) -> Dict[str, Any]:
    """锻造 × 炼金/强化/属性弱点接口契约点枚举（定稿 §1.3 协作闭环 + §八/§九/§十六）。

    入参：modules：{模块名: raw JSON} dict（forge/items 必需；enemies 可选用于弱点对齐）。

    出参 dict：
      - ok：全部契约点 ok（元素通道未对齐 / 缺失镶嵌源 → False）。
      - contracts：契约点清单（供批6B 冒烟消费）——每项 {id, name, consumers, inputs, ok,
        details, issues}：
        * alchemy_mount   炼金镶嵌：带孔锻造节点 slots → 装饰珠（items type=装饰珠）嵌入；
          孔位等级 ∈ {1,2,3}（定稿 §八 孔位等级≥珠等级可镶嵌）。
        * enhance_numeric 强化数值层：锻造 stats 数值键 ∈ 数值层键空间（enhance.json 同参数
          空间，定稿 §十六/§7 归口）。
        * element_weakness 属性弱点：stats.element 对齐 alchemy ELEMENT_NAMES_CN 注册表 +
          monsters weakness.elements 弱点表（定稿 §九）。
      - element_registry：{alchemy: [...], forge: [...], monster_weakness: [...]}（口径镜像）。
      - scanned_nodes：扫描规模。

    元素通道口径（B-5）：forge 元素键不在 ELEMENT_NAMES_CN 键集 → 契约点 ok=False（如实上报，
      不静默归一——test_demo 雷剑 element=thunder vs alchemy lightning）；在注册表内但弱点表
      无该属性 → W 级 issue 不翻转 ok（定稿 §15 警告不拦截）。

    铁律：纯函数确定性；只读；零 NoneBot；零定时器/零睡眠；渲染无 emoji。
    """
    contracts: List[Dict[str, object]] = []
    forge = modules.get("forge")
    items = _items_map(modules)

    slotted_nodes: List[Mapping[str, object]] = []
    elem_nodes: List[Mapping[str, object]] = []
    stat_keys: Dict[str, int] = {}
    scanned_nodes = 0
    if isinstance(forge, Mapping):
        for _ti, _ni, node in _iter_forge_nodes(forge):
            scanned_nodes += 1
            if isinstance(node.get("slots"), (list, tuple)) and node["slots"]:
                slotted_nodes.append(node)
            stats = node.get("stats")
            if isinstance(stats, Mapping):
                elem = stats.get("element")
                if isinstance(elem, str) and elem:
                    elem_nodes.append(node)
                for k in stats.keys():
                    sk = str(k)
                    stat_keys[sk] = stat_keys.get(sk, 0) + 1

    # ---- CP-1 炼金镶嵌（定稿 §八：锻造产孔、炼金产珠、孔位≥珠等级可镶嵌）----
    jewel_items = [e for e in items.values() if e.get("type") == "装饰珠"]
    cp1: Dict[str, Any] = {
        "id": "alchemy_mount",
        "name": "炼金镶嵌（带孔装备 slots → 装饰珠）",
        "consumers": ["alchemy"],
        "inputs": ["slots", "slot_level", "type=装饰珠"],
        "ok": True,
        "details": {},
        "issues": [],
    }
    slot_levels: List[int] = []
    for n in slotted_nodes:
        for s in _as_list(n.get("slots")):
            if isinstance(s, Mapping):
                lv = s.get("level")
                if isinstance(lv, int) and not isinstance(lv, bool) and lv not in slot_levels:
                    slot_levels.append(lv)
    cp1["details"] = {
        "slotted_nodes": [n.get("id") for n in slotted_nodes],
        "slot_levels": sorted(slot_levels),
        "valid_slot_levels": list(SLOT_LEVELS),
        "jewel_count": len(jewel_items),
        "jewel_qualities": sorted({
            str(e.get("quality")) for e in jewel_items if e.get("quality") is not None}),
    }
    if slotted_nodes and not jewel_items:
        cp1["ok"] = False
        cp1["issues"].append("锻造带孔装备存在但 items 无 type=装饰珠 镶嵌源（炼金镶嵌闭环断裂）")
    if any(lv not in SLOT_LEVELS for lv in slot_levels):
        cp1["ok"] = False
        cp1["issues"].append("slots level 越出 {1,2,3}（框架 3.5 孔位等级，炼金镶嵌不可消费）")
    contracts.append(cp1)

    # ---- CP-2 强化数值层（定稿 §十六：锻造白值=数值层渠道，enhance.json 同参数空间）----
    unknown_keys = [k for k in sorted(stat_keys) if k not in FORGE_STAT_KEY_SPACE]
    cp2: Dict[str, Any] = {
        "id": "enhance_numeric",
        "name": "强化数值层（锻造 stats 数值键 → enhance +N）",
        "consumers": ["enhance"],
        "inputs": list(_NUMERIC_STAT_KEYS),
        "ok": len(unknown_keys) == 0,
        "details": {
            "stat_key_usage": dict(sorted(stat_keys.items())),
            "numeric_channel": list(_NUMERIC_STAT_KEYS),
            "unknown_keys": unknown_keys,
        },
        "issues": [],
    }
    if unknown_keys:
        cp2["issues"].append(f"锻造 stats 含数值层外键 {unknown_keys}（强化/客制数值层不可消费）")
    contracts.append(cp2)

    # ---- CP-3 元素通道 / 属性弱点（定稿 §九：formula 元素注册表 + 怪物弱点表）----
    alchemy_elem_keys = sorted(ELEMENT_NAMES_CN.keys())
    monster_weak: List[str] = []
    enemies = modules.get("enemies")
    if isinstance(enemies, list):
        seen: Dict[str, bool] = {}
        for m in enemies:
            if not isinstance(m, Mapping):
                continue
            w = m.get("weakness")
            if isinstance(w, Mapping):
                elems = w.get("elements")
                if isinstance(elems, Mapping):
                    for k in elems.keys():
                        if isinstance(k, str) and k and k not in seen:
                            seen[k] = True
                            monster_weak.append(k)
        monster_weak.sort()
    def _elem_of(n: Mapping[str, object]) -> str:
        st = n.get("stats")
        ev = st.get("element") if isinstance(st, Mapping) else None
        return str(ev) if ev is not None else ""
    forge_elem_used = sorted({_elem_of(n) for n in elem_nodes})
    aligned_keys = [k for k in forge_elem_used if k in ELEMENT_NAMES_CN]
    misaligned = [k for k in forge_elem_used if k not in ELEMENT_NAMES_CN]
    no_weak = [k for k in aligned_keys if k not in monster_weak]
    cp3: Dict[str, Any] = {
        "id": "element_weakness",
        "name": "属性弱点（元素通道 → 怪物弱点表 + 炼金注册表）",
        "consumers": ["alchemy", "battle_weakness"],
        "inputs": ["stats.element", "stats.element_value"],
        "ok": len(misaligned) == 0,
        "details": {
            "forge_element_used": forge_elem_used,
            "alchemy_registry": alchemy_elem_keys,
            "monster_weakness": monster_weak,
            "aligned": aligned_keys,
            "misaligned": misaligned,
            "no_weak_monster": no_weak,
        },
        "issues": [],
    }
    for k in misaligned:
        cp3["issues"].append(
            f"元素键 {k} 不在 alchemy ELEMENT_NAMES_CN 注册表（{alchemy_elem_keys}；"
            f"锻造雷=thunder vs 炼金雷=lightning 口径差异需对齐）")
    for k in no_weak:
        cp3["issues"].append(f"元素 {k} 在注册表内但怪物弱点表无该属性（W 级不拦截，定稿 §15）")
    contracts.append(cp3)

    return {
        "ok": all(bool(c.get("ok")) for c in contracts),
        "contracts": contracts,
        "element_registry": {
            "alchemy": alchemy_elem_keys,
            "forge": list(FORGE_ELEMENTS),
            "monster_weakness": monster_weak,
        },
        "scanned_nodes": scanned_nodes,
    }


# ---------------------------------------------------------------------------
# 4) forge_fee_check：费用结算确定性（定稿 §12.4；细化_2c2b §1.2/§1.3）
# ---------------------------------------------------------------------------

def forge_fee_check(settings: object) -> Dict[str, Any]:
    """费用结算确定性校验（定稿 §12.4 forge_fee: 节点等级×10；细化_2c2b §1.2 原子扣减/
    §1.3 失败零副作用）。

    入参：settings：forge 段或完整 settings dict（B-1 归一；读 forge_fee）。

    出参 dict：
      - ok：公式确定性可解析（节点等级×N，N 为固定非负整数，无随机/浮动）即 True。
      - base_fee_per_level：每级金币系数 N（供冒烟断言：test_demo=10）。
      - formula：公式文本（如 "节点等级×10"）。
      - fee_kind：int / formula / default（来源形态）。
      - deterministic：True（节点等级×N 无浮动，锻造 100% 确定性费用）。
      - gold_insufficient_reject：True（金币不足拒绝且零扣减——细化_2c2b §1.3 失败零副作用
        行为契约，拒绝逻辑在 commands 层已落地，本函数登记供冒烟断言）。
      - violations：解析失败 / 公式含随机 token → [{field, reason}]。

    铁律：纯函数确定性；只读；零 NoneBot；零定时器/零睡眠；渲染无 emoji。
    """
    seg = _forge_segment(settings)
    raw = seg.get("forge_fee")
    violations: List[Dict[str, object]] = []
    base: Optional[int] = None
    kind = "default"

    if isinstance(raw, int) and not isinstance(raw, bool):
        base = raw
        kind = "int"
    elif isinstance(raw, str):
        kind = "formula"
        # 解析 "节点等级×10" / "等级×N" / "×N" 形态：取 × 后数字为每级系数
        if "×" in raw:
            right = raw.split("×", 1)[1].strip()
            if right.isdigit():
                base = int(right)
        elif raw.isdigit():
            base = int(raw)
        if _hit_random_token(raw):
            violations.append({
                "field": "settings.forge_fee",
                "reason": f"费用公式 {raw!r} 含随机 token（锻造费用确定性铁律）",
            })
    if base is None:
        base = _DEFAULT_FEE_PER_LEVEL  # S-01 缺省 节点等级×10
    if base < 0:
        violations.append({
            "field": "settings.forge_fee",
            "reason": f"费用系数 {base} 为负（费用确定性铁律：非负）",
        })

    return {
        "ok": len(violations) == 0,
        "base_fee_per_level": base,
        "formula": f"{_FEE_FORMULA_PREFIX}{base}",
        "fee_kind": kind,
        "deterministic": True,
        "gold_insufficient_reject": True,
        "violations": violations,
    }
