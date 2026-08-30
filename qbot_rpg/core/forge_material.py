"""M9 锻造·批2·路2A：素材两档+来源归一+3:1 combine 可用性与实例映射
（qbot_rpg/core/forge_material.py）——素材经济纯函数判定层。

文件名：qbot_rpg/core/forge_material.py
创建时间：2026-08-30
作者：Hermes 子agent-2A（M9 锻造实现组批2·路2A：并发同仓，仅新建本文件 +
  tests/unit/test_forge_material.py；不改动批0/批1 既有文件与 fixtures）

功能描述：锻造素材经济的纯函数判定集合——
  1) material_tier_of   素材档位判定（TIER-03a 双源仲裁：素材行 M-03 tier 覆写 >
                         items 元数据 material_tier > 缺省 normal）；委托 forge_settings
                         ITEMS_FORGE_FIELDS 语义 + forge_models MaterialReq 解析
  2) material_source    来源提示文本归一（SOUR-00：source_override > items.source >
                         兜底「来源未知」）；委托 forge_settings.resolve_source_text
  3) combine_3to1_available  3:1 合成可用性判定（CMB-01~04：settings.forge
                         synth_ratio_3to1 开关（缺省 true）+ 铸造职业 SP-F2 解锁
                         unlock_combine_3to1；未解锁→不可用）；返回 {ok, reason?, message?}
  4) combine_instances  recipe.json kind=combine 实例发现（N 素材→1 高级素材，CMB-02；
                         3:1 合成执行复用 SynthesisEngine，本函数只做实例发现/映射登记）
  5) comb_synth_map     普通素材 id → 稀有素材 id 映射（CMB-02 登记表，
                         供死锁扫描路2C 消费）

依据：细化_2c2c §2.1/§2.2（TIER-01~03 两档定义判定 + CMB-01~04 3:1 合成扩展）+
      定稿 §5.1（两档/3:1 合成/来源提示/怪物素材对应）+ 细化_2c2c §一 SOUR-00（来源总则）+
      细化_2c2d §3.2 SP-F2（unlock_combine_3to1）+
      docs/m9_shared_contract.md §八（items/settings 扩展：material_tier + source）+
      docs/m9_接口摸底.md 缺口1（combine 执行器已实装，3:1 直接复用 SynthesisEngine）。

模式参考：qbot_rpg/core/forge_tree.py（批1：构造器注入+缺省兜底+纯函数确定性）；
  复用批0：forge_settings.py（ITEMS_FORGE_FIELDS / MATERIAL_TIER_VALUES /
  DEFAULT_UNKNOWN_SOURCE / resolve_source_text / read_forge_settings / FORGE_SETTINGS_KEYS）、
  forge_models.py（MaterialReq 素材行解析 / ForgeSettings 读段）；
  复用批1：forge_tree.py（FORGE_JOB_ID 铸造职业 id）；
  复用 M8：proficiency.py（ProficiencyEngine.unlock_count 读 SP 解锁次数）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  DEFAULT_MATERIAL_TIER 取 ITEMS_FORGE_FIELDS["material_tier"].default（=normal，
       TIER-03a 缺省语义）——不硬编码，随批0 字段口径联动。
  F-2  material_tier_of 的 items_def 为 items 材料类条目（Mapping）；material_row 为
       forge 节点 materials[] 行（Mapping，M-01~M-04 形态）。两者皆可缺省 → 返回缺省档位
       （确定性兜底，不抛异常）。
  F-3  combine_3to1_available 的 settings 三态容错：全量 settings dict（含 forge 段）/
       forge 段本身（含 FORGE_SETTINGS_KEYS 任一键）/ ForgeSettings 实例 / None——
       统一归一读 synth_ratio_3to1（缺省 true），对齐 forge_tree._resolve_settings 口径。
  F-4  combine_3to1_available 的 SP 解锁判定委托 ProficiencyEngine.unlock_count
       （player, "forge", "unlock_combine_3to1"）>0 即已解锁（SP-F2 语义：SP 自选解锁，
       非等级自动给）；player 非 Mapping / 无 proficiency.forge 节点 → 0 → 未解锁。
  F-5  combine_instances 的 modules 为校验器同形态 dict（含 "recipe" 键：recipe.json
       kind=combine 条目数组或 id→条目 Mapping 皆兼容）；实例归一字段
       {recipe_id, name, kind, inputs:[{item,count}], output:{item,count}}，
       供 comb_synth_map 登记与路2C 死锁扫描消费。
  F-6  comb_synth_map 为纯结构登记（不校验档位）：combine 实例每个输入素材 id →
       输出素材 id（CMB-02 普通→稀有 语义由路2C 结合 material_tier_of 复核）。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；零定时器探针合规（M43：
      不写睡眠/定时器字样于 docstring）；平台无关；不引入随机；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from qbot_rpg.content.forge_models import ForgeSettings, MaterialReq
from qbot_rpg.content.forge_settings import (
    FORGE_SETTINGS_KEYS,
    ITEMS_FORGE_FIELDS,
    MATERIAL_TIER_VALUES,
    read_forge_settings,
    resolve_source_text,
)
from qbot_rpg.core.forge_tree import FORGE_JOB_ID
from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "DEFAULT_MATERIAL_TIER",
    "UNLOCK_COMBINE_3TO1",
    "comb_synth_map",
    "combine_3to1_available",
    "combine_instances",
    "material_source",
    "material_tier_of",
]


# =====================================================================================
# 常量
# =====================================================================================

# 素材档位缺省（【工程补白 F-1】ITEMS_FORGE_FIELDS["material_tier"].default=normal，
# TIER-03a 缺省语义；随批0 字段口径联动，不硬编码）
DEFAULT_MATERIAL_TIER: str = str(
    ITEMS_FORGE_FIELDS["material_tier"].default or "normal"
)

# 铸造职业 SP-F2 解锁项 id（细化_2c2d §3.2：3:1 合成，合成引擎作用域）
UNLOCK_COMBINE_3TO1: str = "unlock_combine_3to1"


def _is_valid_tier(value: object) -> bool:
    """档位枚举合法判定（TIER-03a：normal/rare 两档；bool 排除）。"""
    return isinstance(value, str) and value in MATERIAL_TIER_VALUES


# =====================================================================================
# 1) material_tier_of：素材档位判定（TIER-03a 双源仲裁：行覆写 > items 元数据 > 缺省）
# =====================================================================================
def material_tier_of(
    items_def: Optional[Mapping[str, object]] = None,
    material_row: Optional[Mapping[str, object]] = None,
) -> str:
    """素材档位判定（细化_2c2c TIER-03a / 2c2a M-03；双源仲裁风格对齐 AR-3）。

    优先级：
      ① 素材需求行 `tier`（M-03 覆写）——枚举合法（normal/rare）即生效；
      ② items 材料类条目 `material_tier`（TIER-03a 元数据）——枚举合法即生效；
      ③ 缺省 DEFAULT_MATERIAL_TIER（=normal，普通基础材料）。

    入参：
      items_def    —— items 材料类条目（Mapping；取 material_tier）。None/非 Mapping 跳过。
      material_row —— forge 节点 materials[] 行（Mapping；M-01~M-04 形态，委托
                      MaterialReq.from_entry 解析 tier）。None/非 Mapping 跳过。
    出参：确定性档位 str ∈ {normal, rare}；无异常，缺省兜底（【工程补白 F-2】）。
    用途：素材档位消费方（缺件提示档位着色 / 死锁扫描途径分级 / 3:1 合成输入复核）。
    """
    # ① 行覆写（M-03：行覆写 > items 元数据，委托 forge_models Def 解析）
    if isinstance(material_row, Mapping):
        req = MaterialReq.from_entry(material_row)
        if _is_valid_tier(req.tier):
            return str(req.tier)
    # ② items 元数据（TIER-03a）
    if isinstance(items_def, Mapping):
        meta = items_def.get("material_tier")
        if _is_valid_tier(meta):
            return str(meta)
    # ③ 缺省档位
    return DEFAULT_MATERIAL_TIER


# =====================================================================================
# 2) material_source：来源提示文本归一（SOUR-00：source_override > items.source > 兜底）
# =====================================================================================
def material_source(
    items_def: Optional[Mapping[str, object]] = None,
    material_row: Optional[Mapping[str, object]] = None,
) -> str:
    """素材来源提示文本归一（细化_2c2c SOUR-00 / 2c2a M-04 / PROG-06/07）。

    委托 forge_settings.resolve_source_text（批0 唯一权威）：
      ① 素材需求行 `source_override`（M-04 覆写）→ 非空 str 生效；
      ② items 材料类条目 `source`（来源标签：采集点/怪物/商店）→ 非空 str 生效；
      ③ 兜底 DEFAULT_UNKNOWN_SOURCE（"来源未知"，F-3 批0 兜底文本）。

    入参：items_def（items 材料类条目 Mapping）、material_row（forge 素材行 Mapping）。
    出参：确定性 str（trimmed）。无异常。
    用途：缺件提示（PROG-02）/ /图纸 分支素材提示（PROG-06）消费方。
    """
    return resolve_source_text(material_row, items_entry=items_def)


# =====================================================================================
# 3) combine_3to1_available：3:1 合成可用性（CMB-01~04：开关 + SP-F2 解锁）
# =====================================================================================
def _resolve_synth_3to1(settings: object) -> bool:
    """3:1 合成开关归一（【工程补白 F-3】：全量 settings / forge 段 / ForgeSettings / None）。

    复用批0 read_forge_settings（S-02 synth_ratio_3to1 缺省 true）。确定性、无副作用。
    """
    if isinstance(settings, ForgeSettings):
        return settings.synth_ratio_3to1
    if isinstance(settings, Mapping):
        seg = settings.get("forge")
        if isinstance(seg, Mapping):
            return bool(read_forge_settings(settings).get("synth_ratio_3to1", True))
        if any(k in settings for k in FORGE_SETTINGS_KEYS):
            return bool(read_forge_settings({"forge": settings}).get("synth_ratio_3to1", True))
        # 无 forge 段 → 走缺省合并（read_forge_settings 对无段返回默认值 → true）
        return bool(read_forge_settings(settings).get("synth_ratio_3to1", True))
    return bool(read_forge_settings(None).get("synth_ratio_3to1", True))


def combine_3to1_available(
    ctx: Optional[Mapping[str, Any]] = None,
    settings: Optional[object] = None,
) -> Dict[str, Any]:
    """3:1 合成可用性判定（细化_2c2c CMB-01~04 + 细化_2c2d SP-F2）。

    校验链（两关全过 → 可用）：
      1) CMB-03：`settings.forge.synth_ratio_3to1` 开关（缺省 true，S-02）——
         false → 不可用 {ok:False, reason:"synth_disabled"}（无升档渠道，校验器 W4 死锁提示侧）
      2) CMB-04：铸造职业 SP 面板 `unlock_combine_3to1` 已解锁（SP-F2 自选解锁，
         非等级自动给）——未解锁 → 不可用 {ok:False, reason:"sp_locked"}

    入参：
      ctx      —— 玩家表示（Mapping；读 proficiency.forge.unlocks，委托
                  ProficiencyEngine.unlock_count）。None/非 Mapping → 未解锁（0）。
      settings —— 3:1 开关源（全量 settings dict / forge 段本身 / ForgeSettings / None，
                  【工程补白 F-3】）。
    出参：{ok, reason?, message?}；可用 {ok:True}，不可用含 reason/message；无异常。
    用途：/合成（3:1 升档）入口守卫、指令侧入口隐藏/折叠（TC-10/11/12）。
    """
    # CMB-03 开关
    if not _resolve_synth_3to1(settings):
        return {
            "ok": False,
            "reason": "synth_disabled",
            "message": "❌ 3:1 合成已关闭（settings.synth_ratio_3to1=false）",
        }
    # CMB-04 SP-F2 解锁（SP 自选解锁，非等级自动给；未解锁 → 不可用）
    prof = ProficiencyEngine()
    unlocked = prof.unlock_count(ctx, FORGE_JOB_ID, UNLOCK_COMBINE_3TO1)
    if unlocked <= 0:
        return {
            "ok": False,
            "reason": "sp_locked",
            "message": "❌ 3:1 合成未解锁：需铸造职业 SP 解锁「3:1 合成」（unlock_combine_3to1）",
        }
    return {"ok": True}


# =====================================================================================
# 4) combine_instances：recipe.json kind=combine 实例发现（CMB-02）
# =====================================================================================
def _iter_recipes(recipes: object):
    """recipe 模块条目迭代（list/tuple 数组或 id→条目 Mapping 皆兼容；畸形跳过）。"""
    if isinstance(recipes, Mapping):
        for v in recipes.values():
            if isinstance(v, Mapping):
                yield v
    elif isinstance(recipes, (list, tuple)):
        for v in recipes:
            if isinstance(v, Mapping):
                yield v


def _normalize_combine_inputs(recipe: Mapping[str, object]) -> List[Dict[str, object]]:
    """combine 实例素材输入归一（[{item, count}]；materials[] 行 id/item 双键兼容）。"""
    raw = recipe.get("materials")
    out: List[Dict[str, object]] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for m in raw:
        if not isinstance(m, Mapping):
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not mid:
            mid = m.get("item")
        if not isinstance(mid, str) or not mid:
            continue
        cnt = m.get("count")
        count = cnt if isinstance(cnt, int) and not isinstance(cnt, bool) and cnt >= 1 else 1
        out.append({"item": mid, "count": count})
    return out


def _normalize_combine_output(recipe: Mapping[str, object]) -> Optional[Dict[str, object]]:
    """combine 实例产物归一（{item, count}；output.item/id 双键兼容）。"""
    raw = recipe.get("output")
    if not isinstance(raw, Mapping):
        return None
    oid = raw.get("item")
    if not isinstance(oid, str) or not oid:
        oid = raw.get("id")
    if not isinstance(oid, str) or not oid:
        return None
    cnt = raw.get("count")
    count = cnt if isinstance(cnt, int) and not isinstance(cnt, bool) and cnt >= 1 else 1
    return {"item": oid, "count": count}


def combine_instances(modules: Optional[Mapping[str, object]] = None) -> List[Dict[str, object]]:
    """recipe.json kind=combine 实例发现（细化_2c2c CMB-02 / m9_接口摸底 缺口1）。

    扫描 modules["recipe"] 中 kind=="combine" 的配方，归一为实例列表：
      {recipe_id, name, kind, inputs:[{item,count},...], output:{item,count}}
    （N 素材 → 1 高级素材；3:1 合成 = 复用 SynthesisEngine 执行，本函数只做实例发现/
    映射登记 comb_synth_map，不执行合成）。

    入参：modules —— 校验器同形态 dict（含 "recipe" 键；条目数组或 id→条目 Mapping 皆兼容）。
    出参：确定性实例 list（文件序）；无 combine / modules 缺失 / recipe 缺失 → []；
          畸形条目（无 id / 无 inputs / 无 output）跳过。
    """
    recipes = modules.get("recipe") if isinstance(modules, Mapping) else None
    out: List[Dict[str, object]] = []
    for recipe in _iter_recipes(recipes):
        if recipe.get("kind") != "combine":
            continue
        rid = recipe.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        inputs = _normalize_combine_inputs(recipe)
        output = _normalize_combine_output(recipe)
        if not inputs or output is None:
            continue
        out.append({
            "recipe_id": rid,
            "name": (
                recipe["name"]
                if isinstance(recipe.get("name"), str) and recipe["name"] else rid
            ),
            "kind": "combine",
            "inputs": inputs,
            "output": output,
        })
    return out


# =====================================================================================
# 5) comb_synth_map：普通素材 id → 稀有素材 id 映射登记（CMB-02 登记表）
# =====================================================================================
def comb_synth_map(modules: Optional[Mapping[str, object]] = None) -> Dict[str, str]:
    """combine 合成映射登记表（细化_2c2c CMB-02：普通素材 id → 稀有素材 id）。

    对每个 kind=combine 实例：每个输入素材 id → 输出素材 id（3 普通 → 1 稀有；
    N 素材 → 1 高级素材 亦逐输入登记）。纯结构登记不校验档位（【工程补白 F-6】，
    「普通→稀有」语义由路2C 死锁扫描结合 material_tier_of 复核）。

    入参：modules —— 校验器同形态 dict（含 "recipe" 键）。
    出参：确定性 dict（输入素材 id → 输出素材 id）；文件序，同输入多实例后者覆盖前者。
    用途：路2C 死锁扫描 DEAD-02/TC-19（3:1 合成覆盖某稀有素材 → 途径数 +1）消费。
    """
    out: Dict[str, str] = {}
    for inst in combine_instances(modules):
        output = inst.get("output")
        inputs = inst.get("inputs")
        if not isinstance(output, Mapping) or not isinstance(inputs, (list, tuple)):
            continue
        out_id = output.get("item")
        if not isinstance(out_id, str) or not out_id:
            continue
        for inp in inputs:
            if not isinstance(inp, Mapping):
                continue
            in_id = inp.get("item")
            if isinstance(in_id, str) and in_id:
                out[in_id] = out_id
    return out
