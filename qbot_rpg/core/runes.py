"""批46 · 符文地基（43-A）——符文定义解析层（qbot_rpg/core/runes.py）。

定位：符文**定义/跨装备类型差异表/3 合 1 判定/1 阶数值求值**的纯解析层，批48（43-D）新增
**2/3 阶效果引用解析**（`rune_effect_refs_of` / `active_rune_effect_refs`）——供战斗接线按侧、
按时点执行；效果语义仍**一律引用 `effects` 注册表**（口径 §三.2），本层不内联执行语义。
批47（43-B）在此新增 **1 阶数值贡献求值**
（`rune_stats_of` / `sum_rune_stats`）：差异表解析（default + 覆盖）**只在此求值处发生**，
不在数据层展开成多份；输出键取自 `data/gear_stats.GEAR_NUMERIC_KEYS`（唯一源）。
**孔位执行**
（镶嵌/拆卸/激活读取）仍在 `core/jewel.py`（口径 §二.5：孔位执行不新造）。
基础刻度常量与阶位/缺省孔位纯解析在 `data/runes.py`（content 校验层同源引用，架构矩阵
`content → {data}`）；本文件在其上叠加差异表解析与 3 合 1 纯函数。

依据：
  - `/root/deliverables/符文系统_实现口径.md`：
      §〇 结论速览 3/4/5（三阶独立刻度 ≠ 既有四档品质；3 合 1 执行器形状可复用但档位
        解析另给；镶嵌状态挂 ItemInstance.uid 的落档容器，不挂 EquipmentSlot）；
      §二.1 符文定义（runes.json 条目形状：id/name/tier/family/by_equip_type/effects/bias）；
      §二.2 孔位与镶嵌（复用 slots.json；缺省孔位段；persistent_state["rune_sockets"] 键=uid）；
      §二.3 三合一规则（禁跳级，必成，档位解析另给）；
      §二.5 命名（引擎 core/runes.py；符文 items.type = "符文"）。
  - 用户原案 `打造系统_原案_20260919.md` §9（固定三孔；同类不同装备效果不同；三阶；
    3 合 1；2 阶起特殊效果；3 阶偏向性）。
  - 决策记录 `docs/深度打造_决策记录.md` H1（孔位镶嵌 = 共享基础设施）、H2（品质正交）。
  - 批38 预留：`core/jewel.py:363-373` `active_sockets`（副手失活唯一读取入口）；
    批40：`ItemInstance.uid`（`data/item.py`）。

【工程补白 · 显式标注】（口径未写死处，按最小必要推导，全部可配、可改）：
  R-1  阶位刻度：`tier ∈ {1,2,3}`（原案 §9「三阶」）。**独立字段**，绝不读 `quality`
       （既有 quality 四档，H2 正交）。见 `data/runes.rune_tier_of`。
  R-2  跨装备类型差异表：`by_equip_type` 为 `{类型键: 覆盖条目}`，**必须含 `default`**
       （兜底）；已登记 `items.type` 键优先，未登记 → default。解析 = default 与命中类型
       条目**顶层浅覆盖**（命中条目的键整键替换 default 同键：`stats`/`effects`/`bias` 均
       整块覆盖，不做 stats 逐键合并——口径 §二.1 示例的 armor_body 只给 dfn、不带 default
       的 atk，即「按类型给一份完整效果」语义）。类型键口径 = `items.type`（口径 §二.1 R2
       默认项①，可改；本解析层不写死具体键集合 → 校验层按运行时 `items.type` 值域判）。
  R-3  3 合 1 的档位推进是**纯函数**：3×同阶同 id → +1 阶；越阶/跳级/满阶一律拒绝
       （`resolve_rune_upgrade`）。执行器（扣料/产出/原子提交）复用 `core/upgrade.py`
       `_exec_jewel` 形状，新增 `_exec_rune`（档位走本模块的阶位解析，不走 quality 序号）。
  R-4  缺省孔位数 `settings.rune_sockets.default_count`（默认 3 = 原案「固定三个孔位」；
       可改）。已登记 `slots.json` 的装备用登记数组（与装饰珠**共用同一孔位数组**），
       未登记 → 缺省 N 孔全开。见 `data/runes.socket_count_of`。
  R-5  符文系统总闸 = `settings.deep_craft.enabled`（口径 §二.5：符文挂在深度打造之下，
       无需新总闸；默认关）。关闭时镶嵌/拆卸/3 合 1 全部拒绝。
  R-6  **1 阶数值贡献求值**（批47 · 43-B）：`rune_stats_of` / `sum_rune_stats` 只做
       「差异解析 + 键白名单 + 数值清洗」；**孔位激活/副手失活/聚合路由都不在本层**——
       分别归 `core/jewel.active_rune_sockets`（唯一孔位读取入口）与
       `core/equipment.aggregate_bonus`（唯一聚合入口）。本层零 gear_stats 键新增。
  R-7  **2/3 阶效果引用解析**（批48 · 43-D）：`rune_effect_refs_of` / `active_rune_effect_refs`
       只做「差异解析 + 引用归一」；效果语义**一律引用 effects 注册表**（§三.2），触发
       时点由符文引用条目的 `trigger` 声明（不写进注册表 → 不产生全局触发泄漏），
       只对其**穿戴者**侧生效；真正执行在 `core/battle._rune_candidates`。
  R-8  **3 阶偏向性**（批48 · 43-D；口径 Q7 默认口径 = 偏向某相性）：`bias =
       {affinity, bonus_pct}`，宿主装备主/副相性（批38 `core/affinity.rank_affinities`）
       命中 → 该符文数值贡献 ×(1+bonus_pct/100)；未命中/无 bias → 原值（逐字段一致）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；不抛异常（缺省兜底/防御降级）；
      工程补白显式标注；不新增口径外机制行为。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

# 基础刻度常量 + 阶位/缺省孔位纯解析（data 层：content 校验层同源引用，架构矩阵 content→{data}）
from qbot_rpg.data.gear_stats import GEAR_NUMERIC_KEYS
from qbot_rpg.data.runes import (
    DEFAULT_EQUIP_TYPE_KEY,
    DEFAULT_SOCKET_COUNT,
    MAX_RUNE_TIER,
    MIN_RUNE_TIER,
    RUNES_STATE_KEY,
    RUNE_TIERS,
    RUNE_TYPE,
    RUNE_UPGRADE_COUNT,
    next_rune_tier,
    rune_tier_of,
    socket_count_of,
)

__all__ = [
    # 常量（自 data/runes.py 再导出，保持 core.runes 既有引用面）
    "DEFAULT_EQUIP_TYPE_KEY",
    "DEFAULT_SOCKET_COUNT",
    "MAX_RUNE_TIER",
    "MIN_RUNE_TIER",
    "RUNES_STATE_KEY",
    "RUNE_TIERS",
    "RUNE_TYPE",
    "RUNE_UPGRADE_COUNT",
    # 纯解析
    "active_rune_effect_refs",
    "by_equip_type_of",
    "next_rune_tier",
    "resolve_by_equip_type",
    "resolve_rune_upgrade",
    "rune_bias_of",
    "rune_effect_refs_of",
    "rune_effects_of",
    "rune_family_of",
    "rune_stats_of",
    "rune_tier_of",
    "socket_count_of",
    "sum_rune_stats",
]

# 数值键白名单（唯一源 data/gear_stats.GEAR_NUMERIC_KEYS；求值处防御性过滤）。
_NUMERIC_KEY_SET = frozenset(GEAR_NUMERIC_KEYS)


# ---------------------------------------------------------------------------
# 通用读取（防御：任意形态不强崩）
# ---------------------------------------------------------------------------
def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Mapping 归一（其余 → 空 Mapping；符文定义 dict/Def 双形态由调用方 raw 归一）。"""
    return value if isinstance(value, Mapping) else {}


def _to_int(value: Any) -> Optional[int]:
    """int 归一（bool 除外）；非 int/可转数字串 → None（对齐 jewel/upgrade 口径）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _to_float(value: Any) -> Optional[float]:
    """float 归一（bool 除外）；非数值 → None（对齐 gear_stats 数值清洗口径）。"""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 符文族 / 效果声明（定义层读取）
# ---------------------------------------------------------------------------
def rune_family_of(rune_def: Any) -> str:
    """符文族名（3 合 1 的输入族判定；同族才允许互为输入）。缺省 → 空串。"""
    d = _as_mapping(rune_def)
    fam = d.get("family")
    return str(fam) if isinstance(fam, str) else ""


def rune_effects_of(rune_def: Any) -> List[Mapping[str, Any]]:
    """符文效果声明（引用 effects 注册表 + 可带 overrides）。

    出参：list[Mapping]（只保留 Mapping 元素；非法元素丢弃——引用存在性由校验层红拦）。
    """
    d = _as_mapping(rune_def)
    raw = d.get("effects")
    if not isinstance(raw, (list, tuple)):
        return []
    return [e for e in raw if isinstance(e, Mapping)]


# ---------------------------------------------------------------------------
# R-2 跨装备类型差异表解析（default + 覆盖）
# ---------------------------------------------------------------------------
def _merge_over(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """default + 覆盖：**顶层浅覆盖**（命中条目的键整键替换 default 同键，含 `stats`）。"""
    out: Dict[str, Any] = {k: v for k, v in base.items()}
    out.update(override)
    return out


def resolve_by_equip_type(rune_def: Any, equip_type: Any = None) -> Dict[str, Any]:
    """同符文在不同装备类型的效果解析（R-2：default + 覆盖）。

    入参：
      - rune_def：符文定义。
      - equip_type：装备类型键（`items.type` 取值；None/空 → 仅 default）。
    出参：解析后的效果条目 dict（命中类型条目与 default 顶层浅覆盖）；无 default 且无命中 →
          空 dict（校验层红拦「by_equip_type 必须含 default」）。
    核心：`by_equip_type[equip_type]` 命中 → 该条目覆盖 default（顶层键整键替换，含
          `stats` 整块覆盖；未在覆盖条目出现的键沿用 default）。
    """
    d = _as_mapping(rune_def)
    table = _as_mapping(d.get("by_equip_type"))
    default = _as_mapping(table.get(DEFAULT_EQUIP_TYPE_KEY))
    key = str(equip_type) if isinstance(equip_type, str) and equip_type else ""
    override = _as_mapping(table.get(key)) if key else {}
    if not override:
        return {k: v for k, v in default.items()}
    return _merge_over(default, override)


def by_equip_type_of(rune_def: Any, equip_type: Any = None) -> Dict[str, Any]:
    """`resolve_by_equip_type` 的别名（对外可读名，语义完全一致）。"""
    return resolve_by_equip_type(rune_def, equip_type)


# ---------------------------------------------------------------------------
# R-2/R-4 1 阶数值贡献求值（批47 · 43-B；差异解析唯一发生处）
# ---------------------------------------------------------------------------
# R-8（批48 · 43-D）3 阶「偏向性」字段口径（工程补白：口径 Q7 未逐字写死，任务默认口径
# = 偏向某相性、对接批38 相性层）：
#   bias = {"affinity": <相性 id>, "bonus_pct": <数值>}
#   语义：宿主装备的**主/副相性**（`core/affinity.rank_affinities` 判定）命中 `affinity`
#   → 该符文数值贡献 ×(1 + bonus_pct/100)；不命中 → 不加成（default 语义）。
RUNE_BIAS_AFFINITY_KEY: str = "affinity"
RUNE_BIAS_BONUS_KEY: str = "bonus_pct"


def rune_bias_of(rune_def: Any, equip_type: Any = None) -> Dict[str, Any]:
    """3 阶偏向性解析（差异解析后；R-8）：`{affinity, bonus_pct}`；无效 → {}。

    入参：rune_def 符文定义；equip_type 类型键（bias 亦可按类型覆盖，同差异表）。
    出参：`{"affinity": str, "bonus_pct": float}`；`affinity` 缺/非法 → {}（校验层红拦）。
    """
    entry = resolve_by_equip_type(rune_def, equip_type)
    bias = entry.get("bias")
    if bias is None:
        bias = _as_mapping(rune_def).get("bias")
    b = _as_mapping(bias)
    aff = b.get(RUNE_BIAS_AFFINITY_KEY)
    if not isinstance(aff, str) or not aff:
        return {}
    bonus = _to_float(b.get(RUNE_BIAS_BONUS_KEY))
    return {RUNE_BIAS_AFFINITY_KEY: aff, RUNE_BIAS_BONUS_KEY: bonus if bonus is not None else 0.0}


def _affinity_matched(affinity: str, item_affinities: Any) -> bool:
    """宿主装备主/副相性是否命中偏向相性（对接批38 相性层 `rank_affinities`）。"""
    values = _as_mapping(item_affinities)
    if not values:
        return False
    try:
        from qbot_rpg.core.affinity import rank_affinities  # 同层引用（相性通用层）
        ranked = rank_affinities(values)
    except Exception:  # noqa: BLE001 —— 相性层不可用 → 不命中（不阻断数值求值）
        return False
    return affinity in (ranked.get("main"), ranked.get("sub"))


def rune_stats_of(
    rune_def: Any,
    equip_type: Any = None,
    item_affinities: Any = None,
) -> Dict[str, float]:
    """符文数值贡献**求值处**（批47 · 43-B）：解析差异表后取 `stats` 数值键。

    入参：
      - rune_def：符文定义（by_equip_type default + 覆盖）。
      - equip_type：装备类型键 = **`items.type`**（R-2/Q5 本批口径）；None/空 → default。
      - item_affinities（批48 · R-8）：宿主装备相性声明 `{相性id: 数值}`（`items.affinities`）；
        主/副相性命中 `bias.affinity` → 数值 ×(1+bonus_pct/100)。缺省 None → 不加成。
    出参：{gear_stats 数值键: 数值}（同键只出现一次；缺/非法 → {}）。
    核心：
      · 差异解析**只在此处发生**（`resolve_by_equip_type` 的 default + 顶层浅覆盖），
        不在数据层把 by_equip_type 展开成多份；
      · 只保留 `GEAR_NUMERIC_KEYS`（唯一源 `data/gear_stats.py`）内的键——自造键由校验器
        RUNE-05 红拦，此处再防御性丢弃（占位/未知键不进引擎）；
      · 布尔/非数值/0 丢弃（0 不改变聚合结果，且与既有 extract_bonus 口径一致）；
      · 偏向加成只放大**该符文自身**贡献（不触碰同件其它符文），未命中 → 原值逐字段一致。
    """
    entry = resolve_by_equip_type(rune_def, equip_type)
    stats = _as_mapping(entry.get("stats"))
    out: Dict[str, float] = {}
    for k, v in stats.items():
        ks = str(k)
        if ks not in _NUMERIC_KEY_SET:
            continue
        fv = _to_float(v)
        if fv is None or fv == 0.0:
            continue
        out[ks] = fv
    bias = rune_bias_of(rune_def, equip_type)
    if out and bias and _affinity_matched(bias[RUNE_BIAS_AFFINITY_KEY], item_affinities):
        factor = 1.0 + float(bias[RUNE_BIAS_BONUS_KEY]) / 100.0
        out = {k: v * factor for k, v in out.items()}
    return out


def sum_rune_stats(
    rune_ids: Any,
    runes: Any,
    equip_type: Any = None,
    item_affinities: Any = None,
) -> Dict[str, float]:
    """同件装备上多个**激活**符文的数值贡献合并（同键加算；缺定义/空槽跳过）。

    入参：
      - rune_ids：激活符文 id 序列（由 `jewel.active_rune_sockets` 读取；None/空槽元素跳过）。
      - runes：符文注册表 `{rune_id: 定义}`（缺表/非 Mapping → 空）。
      - equip_type：装备类型键（`items.type`；决定每枚符文的差异解析）。
      - item_affinities（批48 · R-8）：宿主装备相性声明（决定 3 阶偏向是否命中）。
    出参：{gear_stats 数值键: 合计值}（纯函数；不读孔位、不判副手——那两件事归
          `jewel.active_rune_sockets`，本函数只做效果求值）。
    """
    out: Dict[str, float] = {}
    reg = _as_mapping(runes)
    if not isinstance(rune_ids, (list, tuple)):
        return out
    for rid in rune_ids:
        if rid is None or rid == "":
            continue
        d = reg.get(str(rid))
        if not isinstance(d, Mapping):
            continue
        for k, v in rune_stats_of(d, equip_type, item_affinities).items():
            out[k] = out.get(k, 0.0) + v
    return out


# ---------------------------------------------------------------------------
# R-3 3 合 1 纯函数（3×同阶同 id → 1×高一阶；禁跳级；必成）
# ---------------------------------------------------------------------------
def resolve_rune_upgrade(
    rune_def: Any,
    count: Any,
    output_tier: Any = None,
) -> Dict[str, Any]:
    """3 合 1 进阶判定**纯函数**（R-3：3×同阶同 id → +1 阶；禁跳级；必成）。

    入参：
      - rune_def：输入符文定义（同 id 的 3 件由调用方按 item_id 聚合后传入代表定义）。
      - count：输入件数（须 ≥ `RUNE_UPGRADE_COUNT`=3）。
      - output_tier：配方声明的产出阶（可选）。给了就必须 == 输入阶 + 1（**禁跳级**）。
    出参（纯数据，无副作用）：
      - 成功 → {ok: True, rune_id, tier_in, tier_out, count}
      - 拒绝 → {ok: False, reason, ...}；reason ∈
        rune_tier_missing（定义阶缺失/非法）/ rune_input_count（件数不足）/
        rune_max_tier（已满阶，链终点）/ rune_skip_tier（产出阶 ≠ 输入阶+1，越阶/跳级）。
    核心：**必成**（无随机，对齐 `_exec_jewel` 拍板）；同 id 由调用方按单条目 ×3 保证
          （对齐 `_exec_jewel` U-J2）；本函数只判阶位推进，不碰背包/货币（提交归执行器）。
    """
    tier = rune_tier_of(rune_def)
    d = _as_mapping(rune_def)
    rid = str(d.get("id") or "")
    n = _to_int(count)
    if tier is None:
        return {
            "ok": False,
            "reason": "rune_tier_missing",
            "rune_id": rid,
            "tier_in": None,
            "tier_out": None,
            "count": n,
        }
    if n is None or n < RUNE_UPGRADE_COUNT:
        return {
            "ok": False,
            "reason": "rune_input_count",
            "rune_id": rid,
            "tier_in": tier,
            "tier_out": None,
            "count": n,
        }
    out = next_rune_tier(tier)
    if out is None:
        return {
            "ok": False,
            "reason": "rune_max_tier",
            "rune_id": rid,
            "tier_in": tier,
            "tier_out": None,
            "count": n,
        }
    if output_tier is not None:
        declared = _to_int(output_tier)
        if declared != out:
            return {
                "ok": False,
                "reason": "rune_skip_tier",
                "rune_id": rid,
                "tier_in": tier,
                "tier_out": declared,
                "expected_tier": out,
                "count": n,
            }
    return {
        "ok": True,
        "reason": "",
        "rune_id": rid,
        "tier_in": tier,
        "tier_out": out,
        "count": n,
    }


def _iter_rune_entries(runes: Any) -> Sequence[Mapping[str, Any]]:
    """符文注册表条目迭代（list/dict 两形态归一；供上层/测试复用）。"""
    if isinstance(runes, Mapping):
        return [v for v in runes.values() if isinstance(v, Mapping)]
    if isinstance(runes, (list, tuple)):
        return [e for e in runes if isinstance(e, Mapping)]
    return []


# ---------------------------------------------------------------------------
# R-6 · 2/3 阶效果引用解析（批48 · 43-D；战斗接线侧取数）
# ---------------------------------------------------------------------------
# 符文效果引用条目键（工程补白 R-7：ref = {effect, trigger?, overrides?, target?}）
RUNE_EFFECT_REF_KEY: str = "effect"
RUNE_EFFECT_TRIGGER_KEY: str = "trigger"
RUNE_EFFECT_OVERRIDES_KEY: str = "overrides"
RUNE_EFFECT_TARGET_KEY: str = "target"


def rune_effect_refs_of(rune_def: Any, equip_type: Any = None) -> List[Dict[str, Any]]:
    """符文声明的**效果引用**列表（差异解析后；元素 = 归一化引用 dict）。

    入参：rune_def 符文定义；equip_type 装备类型键（`items.type`，决定差异解析）。
    出参：list[dict]，元素 `{effect, [trigger], [target], [overrides]}`；非法/空 → []。
    核心（工程补白 R-7，口径 §二.1/R6 未写死触发行）：
      · 效果条目取自差异解析结果（`by_equip_type.<type>` 覆盖条目优先），未声明 →
        回落符文顶层 `effects`（口径 §二.1 形状草案的顶层字段）；
      · `effect` 非空串才保留（悬空引用由校验器 RUNE-06 红拦）；
      · `trigger` = 战斗事件时点（`core/event_dispatcher.EVENT_POINTS`；符文只在其
        穿戴者侧、匹配该事件时触发——**不写进 effects 注册表** → 不产生全局泄漏）；
      · `target`/`overrides` 原样透传（执行时并入子动作）。
    """
    entry = resolve_by_equip_type(rune_def, equip_type)
    raw = entry.get("effects")
    if raw is None:
        raw = _as_mapping(rune_def).get("effects")
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[Dict[str, Any]] = []
    for e in raw:
        if not isinstance(e, Mapping):
            continue
        eid = e.get(RUNE_EFFECT_REF_KEY)
        if not isinstance(eid, str) or not eid:
            continue
        ref: Dict[str, Any] = {RUNE_EFFECT_REF_KEY: eid}
        for key in (RUNE_EFFECT_TRIGGER_KEY, RUNE_EFFECT_TARGET_KEY,
                    RUNE_EFFECT_OVERRIDES_KEY):
            if key in e:
                ref[key] = e[key]
        out.append(ref)
    return out


def active_rune_effect_refs(ctx: Any, jewel: Any = None) -> List[Dict[str, Any]]:
    """**已穿戴件激活符文的全部效果引用**（战斗接线取数唯一入口；孔位经
    `jewel.active_rune_sockets`）。

    链路：worn 枚举（复用 `EquipmentEngine` 唯一枚举）→ `active_rune_sockets`
    （**唯一孔位读取入口**，副手失活自动继承）→ 每枚符文按 `items.type` 差异解析
    → 汇总效果引用。缺 runes/jewel/数据源/总闸关 → []（零贡献，不抛）。
    """
    c = _as_mapping(ctx)
    if not _as_mapping(c.get("runes")):
        return []
    try:  # lazy：core.equipment 顶层 import core.runes（避免模块级环）
        from qbot_rpg.core.equipment import EquipmentEngine
        from qbot_rpg.core.jewel import JewelSystem
    except Exception:  # noqa: BLE001 —— 依赖不可用 → 零贡献（不阻断战斗装配）
        return []
    jw = jewel if jewel is not None else c.get("jewel")
    if jw is None:
        try:
            jw = JewelSystem(settings=c.get("settings"))
        except Exception:  # noqa: BLE001 —— 设置形态异常 → 零贡献
            return []
    engine = EquipmentEngine(
        slots=c.get("slots"), offhand=c.get("equipment_offhand"),
        runes=c.get("runes"), items=c.get("items"), jewel=jw,
    )
    try:
        return engine.active_rune_effects(c.get("player"))
    except Exception:  # noqa: BLE001 —— 读取失败按无符文效果（不阻断装配）
        return []
