"""框架默认条目预设（批17 · 物品通用预设；用户 2026-09-15 拍板）。

背景 / 依据
-----------
批16 的条目预设（「新建按模板」）原本只能由**内容包**在 `field_meta.json.entry_presets`
里声明。用户 2026-09-15 拍板：把「材料、货币袋、药剂、礼包、装备、技能书」这六种
**通用品类**提升为**框架自带**——任何内容包（含完全空白包）新建 `items` 条目时都能
直接选这六种，包可覆盖 / 追加 / 关闭。

本模块只放**通用品类**，不写死任何内容包业务名 / 包专属词；预设引用的字段键必须在框架
元数据里真实登记过（`qbot_rpg/content/field_meta.py` 的 `items` 模块字段表），由
`framework_preset_key_errors(table)` 提供断言校验（测试与自检共用），**不臆造键名**。

生效预设 = 框架默认 ∪ 包声明（`merge_entry_presets`）
----------------------------------------------------
1. **同 id → 包声明整体覆盖框架默认**（不是字段级合并，避免歧义）；
2. 包可**追加**新预设：框架没有的 id → 追加到框架默认之后，保持包声明顺序；
3. 包可**关闭**某个框架默认（或关闭包自己的预设）：在 `field_meta.json` 顶层声明
   `entry_presets_disable: {"<模块>": ["<预设 id>", ...]}`，被点名的 id 从生效表移除；
4. **无包声明 / 空白包 → 仍然能用框架默认**（空白包也有六种，关键验收）；
5. 不选预设 / 未命中 → 编辑器行为与批16 现状完全一致（预设**只收窄显示面**，
   其余字段进「其他字段」折叠区**仍可编辑**——一号原则）。

预设字段（与包声明同形）
------------------------
`{id, label, help, fields, defaults, id_prefix, id_width}`：
  · `fields` = 该预设**关心的字段键**，顺序即新建表单主区顺序；
  · `defaults` = 初始值（叠加在字段元数据默认值之上；键 ⊆ `fields`）；
  · `id_prefix` / `id_width` = 该预设下的建议 ID 前缀 / 零填充宽度（缺省走批16 口径）。
"""

from __future__ import annotations

from typing import Any, List, Mapping, Sequence, Tuple

# 框架默认预设：`{"<模块>": (预设, ...)}`。本次只覆盖 `items`（物品）六种通用品类；
# 将来其它模块的通用预设按同样结构追加即可（编辑器读取层通用，不写死模块名）。
#
# `defaults.type` 取**通用英文品类值**；与现有内容包 `type` 取值的核对见作者文档与台账：
#   材料 material / 药剂 consumable 与现有包习惯一致；货币 currency、技能书 skill_book
#   亦在引擎类型词表内；装备 equipment、礼包 gift_box 为通用品类词（引擎背包筛选暂未收录，
#   回落「其他」，属已知展示差异，不影响校验与数据）。
FRAMEWORK_ENTRY_PRESETS: Mapping[str, Tuple[Mapping[str, Any], ...]] = {
    "items": (
        {
            "id": "material",
            "label": "材料",
            "help": "材料：名称、稀有度、品阶与来源；价格可后补。",
            "fields": ("name", "type", "desc", "rarity", "material_tier",
                       "source", "price"),
            "defaults": {"type": "material"},
            "id_prefix": "mat",
            "id_width": None,
        },
        {
            "id": "currency_pouch",
            "label": "货币袋",
            "help": "货币袋：默认可用；效果列表留空，填可开出的内容。",
            "fields": ("name", "type", "desc", "usable", "effects"),
            "defaults": {"type": "currency", "usable": True, "effects": []},
            "id_prefix": "pouch",
            "id_width": None,
        },
        {
            "id": "potion",
            "label": "药剂",
            "help": "药剂：默认可用；填效果列表与价格。",
            "fields": ("name", "type", "desc", "usable", "effects", "price"),
            "defaults": {"type": "consumable", "usable": True, "effects": []},
            "id_prefix": "potion",
            "id_width": None,
        },
        {
            "id": "gift_box",
            "label": "礼包",
            "help": "礼包：默认可用；效果列表留空，填可开出的内容。",
            "fields": ("name", "type", "desc", "usable", "effects"),
            "defaults": {"type": "gift_box", "usable": True, "effects": []},
            "id_prefix": "gift",
            "id_width": None,
        },
        {
            "id": "equipment",
            "label": "装备",
            "help": "装备：先选部位，再填攻防与百分比加成。",
            "fields": ("name", "type", "desc", "slot", "price", "dfn", "atk",
                       "atk_pct", "dfn_pct", "crit", "agi", "hp_pct"),
            "defaults": {"type": "equipment"},
            "id_prefix": "eq",
            "id_width": None,
        },
        {
            "id": "skill_book",
            "label": "技能书",
            "help": "技能书：默认可用；填效果列表与价格。",
            "fields": ("name", "type", "desc", "usable", "effects", "price"),
            "defaults": {"type": "skill_book", "usable": True, "effects": []},
            "id_prefix": "book",
            "id_width": None,
        },
    ),
}


def framework_presets(module: object) -> Tuple[Mapping[str, Any], ...]:
    """某模块的框架默认预设（无 → 空元组）；只读。"""
    return tuple(FRAMEWORK_ENTRY_PRESETS.get(str(module or ""), ()))


def _preset_id(item: Mapping[str, Any]) -> str:
    return str(item.get("id") or "")


def merge_entry_presets(
        module: object,
        pack_presets: Sequence[Mapping[str, Any]] = (),
        disabled: Sequence[object] = ()) -> Tuple[Mapping[str, Any], ...]:
    """生效预设 = 框架默认 ∪ 包声明；返回**新元组**，不改任何入参。

    规则（与 docstring 一致，纯函数）：
      · 框架默认按声明顺序在前；包声明同 id → **整体覆盖**（位置仍是框架默认的位置）；
      · 包声明的**新 id** → 追加到末尾（保持包声明顺序）；
      · `disabled` 里的 id（框架或包）→ 从结果移除（关闭）。
    """
    merged: List[Mapping[str, Any]] = list(framework_presets(module))
    index = {_preset_id(p): i for i, p in enumerate(merged)}
    extras: List[Mapping[str, Any]] = []
    for item in pack_presets or ():
        if not isinstance(item, Mapping):
            continue
        pid = _preset_id(item)
        if pid and pid in index:
            merged[index[pid]] = item
        else:
            extras.append(item)
    merged.extend(extras)
    off = {str(x) for x in (disabled or ()) if str(x or "")}
    if off:
        merged = [p for p in merged if _preset_id(p) not in off]
    return tuple(merged)


def framework_preset_key_errors(table: object) -> List[str]:
    """框架默认预设的**键合理性**自检（用元数据表断言，防臆造键名）。

    返回人话错误列表（空 = 全部合法）；检查：
      · 每个预设的 `id` 非空、同模块内唯一；
      · `fields` 与 `defaults` 里的每个键都在该模块框架元数据的字段表里真实登记。
    """
    errors: List[str] = []
    for module, presets in FRAMEWORK_ENTRY_PRESETS.items():
        mmeta = table.module(str(module)) if table is not None else None
        known: set = set()
        if mmeta is not None:
            known |= {str(k) for k in mmeta.fields}
            if mmeta.value_meta is not None and mmeta.value_meta.children:
                known |= {str(k) for k in mmeta.value_meta.children}
        seen: set = set()
        for i, preset in enumerate(presets):
            pid = _preset_id(preset)
            if not pid:
                errors.append(f"{module}[{i}] 缺少 id")
                continue
            if pid in seen:
                errors.append(f"{module} 预设 id 重复：{pid}")
            seen.add(pid)
            keys = [str(k) for k in (preset.get("fields") or ())]
            keys += [str(k) for k in (preset.get("defaults") or {})]
            for key in keys:
                if key not in known:
                    errors.append(f"{module}.{pid} 引用未登记字段键：{key}")
    return errors


__all__ = [
    "FRAMEWORK_ENTRY_PRESETS",
    "framework_presets",
    "merge_entry_presets",
    "framework_preset_key_errors",
]
