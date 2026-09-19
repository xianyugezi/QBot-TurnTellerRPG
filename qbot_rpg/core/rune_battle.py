"""批48 · 符文战斗接线取数层（qbot_rpg/core/rune_battle.py）。

定位：**已穿戴件激活符文的 ctx 级效果引用收集**（战斗装配唯一取数入口）。拆出独立模块
的原因：该入口需要同时引用 `core.equipment`（worn 枚举 + `active_rune_sockets` 消费）与
`core.jewel`（缺省构造 `JewelSystem`），而 `core.equipment` 顶层 import `core.runes`
（数值段）——若把本入口放进 `core/runes.py` 会形成 `runes ↔ equipment` 模块级环
（G0 架构门禁 TC-03 红）。本模块只是**组合层**（core → core），无人反向 import 它。

依据：
  - `/root/deliverables/符文系统_实现口径.md` §三.2（效果一律引用 effects 注册表；符文真正
    生效包含一次战斗接线）+ §〇 结论 8（副手失活经 `active_rune_sockets` 继承）；
  - `docs/深度打造_决策记录.md` H1（孔位镶嵌 = 共享基础设施）。

铁律：零 NoneBot import；core 层（依赖 core/data）；不抛异常（缺省/异常 → 零贡献）；
      孔位一律经 `jewel.active_rune_sockets`（唯一读取入口，副手失活自动继承）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

__all__ = ["active_rune_effect_refs"]


def active_rune_effect_refs(ctx: Any, jewel: Any = None) -> List[Dict[str, Any]]:
    """**已穿戴件激活符文的全部效果引用**（战斗接线取数唯一入口；孔位经
    `jewel.active_rune_sockets`）。

    链路：worn 枚举（复用 `EquipmentEngine` 唯一枚举）→ `active_rune_sockets`
    （**唯一孔位读取入口**，副手失活自动继承）→ 每枚符文按 `items.type` 差异解析
    → 汇总效果引用。缺 runes/jewel/数据源/总闸关 → []（零贡献，不抛）。

    入参：
      - ctx：内容/玩家上下文（`runes`/`items`/`slots`/`equipment_offhand`/`player`/
        `settings`；可选 `jewel` 实例）。
      - jewel：`JewelSystem` 实例（显式优先；缺省取 `ctx["jewel"]`，再缺省按
        `ctx["settings"]` 构造）。
    出参：list[dict]（`core/runes.rune_effect_refs_of` 的合并结果）。
    """
    c = ctx if isinstance(ctx, Mapping) else {}
    runes = c.get("runes")
    if not isinstance(runes, Mapping) or not runes:
        return []
    try:
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
        runes=runes, items=c.get("items"), jewel=jw,
    )
    try:
        return engine.active_rune_effects(c.get("player"))
    except Exception:  # noqa: BLE001 —— 读取失败按无符文效果（不阻断装配）
        return []
