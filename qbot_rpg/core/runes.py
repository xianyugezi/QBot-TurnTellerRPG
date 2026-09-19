"""批46 · 符文地基（43-A）——符文定义解析层（qbot_rpg/core/runes.py）。

定位：符文**定义/跨装备类型差异表/3 合 1 判定**的纯解析层，不接战斗效果
（1 阶数值落 `gear_stats`、2/3 阶 effects 接线 = 后续批 43-B/D）。**孔位执行**
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

铁律：零 NoneBot import；纯函数（同刻同参必同值）；不抛异常（缺省兜底/防御降级）；
      工程补白显式标注；不新增口径外机制行为。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

# 基础刻度常量 + 阶位/缺省孔位纯解析（data 层：content 校验层同源引用，架构矩阵 content→{data}）
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
    "by_equip_type_of",
    "next_rune_tier",
    "resolve_by_equip_type",
    "resolve_rune_upgrade",
    "rune_effects_of",
    "rune_family_of",
    "rune_tier_of",
    "socket_count_of",
]


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
