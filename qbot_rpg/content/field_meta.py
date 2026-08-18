"""字段元数据表缺省实现（细化_3e §5.3：校验唯一数据源；新字段 = 本表加一行，校验器零代码变更）。

依据：
  - 细化_3e_loader校验接线 §5.2（每模块校验清单：manifest/effects/statuses/marks/skill_chains/action/
    formula/items/equipment/traits/enemies/maps/stats/npc）
  - 细化_3e_loader校验接线 §5.3（全部字段的 名称/类型/默认值/范围/引用目标 从本表读取；缺失字段默认放行）
  - 细化_3a_架构分层契约 §3.3 U2（Def 类落 content/，本表同为 content/ 数据）
  - 细化_1e_怪物八段schema（enemies 字段：hp/atk/def/drop_rate/actions/probability/weight）
  - 细化_1d_印记系统契约（marks：type="mark"、max_stack=0 不限、duration "battle"/"turns:N"）
  - 细化_3b_玩家属性三层 §4.2（StatDef：base/growth/max/min/type=resource|combat）

铁律：只提供「字段口径」默认值；editor/CSV/Schema/validator 四处共用一张元数据表（L140），
正式表在编辑器里程碑注入，本文件为 M0 引擎可运行的缺省口径。枚举尽量宽松，避免误阻断合法包。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta

# -------------------------------------------------------------------------------------
# 命名空间（ID 跨模块唯一，细化_3a §4.2 line 254：效果注册表三表统一 / 行动注册表 / 派生链注册表）
# -------------------------------------------------------------------------------------
NAMESPACES: Dict[str, Tuple[str, ...]] = {
    "effect_family": ("effects", "statuses", "marks"),  # 效果注册表三表统一（ID 跨表唯一）
    "chain_lib": ("skill_chains",),  # 派生链注册表
    "action_lib": ("action",),  # 行动注册表
    "item_lib": ("items", "equipment"),  # 物品注册表（装备同库）
    "trait_lib": ("traits",),
    "enemy_lib": ("enemies",),
    "map_lib": ("maps",),
    "stat_lib": ("stats",),
    "npc_lib": ("npc",),
}

# -------------------------------------------------------------------------------------
# 常用字段（供各模块复用）
# -------------------------------------------------------------------------------------
F_ID = FieldMeta(type="str", required=True)
F_NAME = FieldMeta(type="str")
F_TYPE = FieldMeta(type="str")  # type 枚举由正式元数据表注入（细化_1b/1e）；缺省不设枚举防误阻断

# 效果引用列表（items/equipment/traits/enemies 通用）
F_EFFECTS = FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="effect"))

# 常见数值字段（range 仅 Y-1 提示用）
F_PRICE = FieldMeta(type="number", range_min=0, range_max=50000)
F_ATK = FieldMeta(type="number", range_min=0, range_max=5000)
F_DEF = FieldMeta(type="number", range_min=0, range_max=5000)
F_HP = FieldMeta(type="number", range_min=0, range_max=99999)
F_POWER = FieldMeta(type="number", range_min=0, range_max=500)
F_DURATION = FieldMeta(type="number", range_min=0, range_max=999)
F_MAX_STACK = FieldMeta(type="int", zero_unlimited=True, range_min=0, range_max=999)
F_PROBABILITY = FieldMeta(type="number", probability=True, range_min=0.0, range_max=1.0)
F_DROP_RATE = FieldMeta(type="number", probability=True, range_min=0.0, range_max=1.0)

# -------------------------------------------------------------------------------------
# stat（stats.json 键空间条目）
# -------------------------------------------------------------------------------------
STAT_CHILDREN: Dict[str, FieldMeta] = {
    "name": FieldMeta(type="str"),
    "type": FieldMeta(type="str"),  # resource|combat（正式表注入枚举）
    # 3b §4.2/TC-17：base/growth 负数 → 黄提示（allow_negative），运行期按 0（calc 兜底）
    "base": FieldMeta(type="number", range_min=0, range_max=5000, allow_negative=True),
    "growth": FieldMeta(type="number", range_min=0, range_max=50, allow_negative=True),
    "max": FieldMeta(type="number", range_min=0, range_max=999999),
    "min": FieldMeta(type="number", range_min=0, range_max=999999),
    "display": FieldMeta(type="str"),
}

# -------------------------------------------------------------------------------------
# 模块元数据
# -------------------------------------------------------------------------------------
def _module_table() -> Dict[str, ModuleMeta]:
    manifest_fields: Dict[str, FieldMeta] = {
        "name": FieldMeta(type="str", required=True),
        "version": FieldMeta(type="str", required=True),
        "schema_version": FieldMeta(type="int", required=True),
        "author": FieldMeta(type="str"),
        "modules": FieldMeta(type="list", required=True, element=FieldMeta(type="str")),
    }
    effects_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "power": F_POWER, "duration": F_DURATION,
        "probability": F_PROBABILITY, "max_stack": F_MAX_STACK,
        # 引用的 status/mark ID（细化_1b；引用缺失 R-4）
        "require_status": FieldMeta(type="ref", ref_target="status"),
        "apply_status": FieldMeta(type="ref", ref_target="status"),
        "require_mark": FieldMeta(type="ref", ref_target="mark"),
        "apply_mark": FieldMeta(type="ref", ref_target="mark"),
        "patch": FieldMeta(type="obj", children={"target": FieldMeta(type="str"),
                                                 "value": FieldMeta(type="number"),
                                                 "pct": FieldMeta(type="bool")}),
    }
    statuses_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "max_stack": F_MAX_STACK, "duration": F_DURATION,
        "decay": FieldMeta(type="str"),  # 枚举（per_turn…）由正式表注入
        "effects": F_EFFECTS,
        "on_enter": FieldMeta(type="ref", ref_target="effect"),
        "on_tick": FieldMeta(type="ref", ref_target="effect"),
        "on_expire": FieldMeta(type="ref", ref_target="effect"),
    }
    marks_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME,
        "type": FieldMeta(type="enum", enum=("mark",)),
        "max_stack": F_MAX_STACK, "duration": F_DURATION,
        "probability": F_PROBABILITY,
        "require_status": FieldMeta(type="ref", ref_target="status"),
        "apply_status": FieldMeta(type="ref", ref_target="status"),
        "apply_effect": FieldMeta(type="ref", ref_target="effect"),
    }
    skill_chains_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        # 链节点引用（skill/action）。M0 无技能库模块，缺省仅结构（成环 R-5）；
        # 正式元数据表注入 ref_target="skill"/"action" 后自动启用 R-4。
        "next": FieldMeta(type="list", element=FieldMeta(type="str")),
        "actions": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="action")),
        "effects": F_EFFECTS,
    }
    action_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "power": F_POWER, "cost": FieldMeta(type="number", range_min=0, range_max=9999),
        "cool": FieldMeta(type="number", range_min=0, range_max=9999),
        "probability": F_PROBABILITY, "weight": FieldMeta(type="number", range_min=0, range_max=100),
        "effects": F_EFFECTS,
        "require_status": FieldMeta(type="ref", ref_target="status"),
        "apply_status": FieldMeta(type="ref", ref_target="status"),
        "skill": FieldMeta(type="ref", ref_target="skill_or_any"),
    }
    items_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "price": F_PRICE, "atk": F_ATK, "def": F_DEF,
        "effects": F_EFFECTS,
        "slot": FieldMeta(type="str"),  # 装备部位（正式表可注入 ref_target=slot）
        "bind": FieldMeta(type="bool"),
        "usable": FieldMeta(type="bool"),
    }
    equipment_fields: Dict[str, FieldMeta] = dict(items_fields)
    # 部位互斥：entry.slot 与 entry.excludes 列表内部位互斥成环 → R-5（equipment 专项，§5.2 + L167）
    equipment_fields["slot"] = FieldMeta(type="str")
    equipment_fields["excludes"] = FieldMeta(type="list", element=FieldMeta(type="str"))
    traits_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "probability": F_PROBABILITY, "max_stack": F_MAX_STACK,
        "effects": F_EFFECTS,
        "require_status": FieldMeta(type="ref", ref_target="status"),
        "apply_status": FieldMeta(type="ref", ref_target="status"),
    }
    enemies_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "hp": F_HP, "atk": F_ATK, "def": F_DEF,
        "drop_rate": F_DROP_RATE,
        "effects": F_EFFECTS,
        "traits": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="trait")),
        "actions": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="action")),
        "skills": FieldMeta(type="list", element=FieldMeta(type="str")),  # 技能库 M6 注入
    }
    maps_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME,
        "enemy_pool": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="enemy")),
        "battle": FieldMeta(type="bool"), "revert": FieldMeta(type="bool"),
        # 区域/副本区间（min>max 死配置 → R-5，min/max 由校验器泛化检测）
        "min": FieldMeta(type="int"), "max": FieldMeta(type="int"),
        "lower": FieldMeta(type="int"), "upper": FieldMeta(type="int"),
        "reset": FieldMeta(type="obj"),
    }
    stats_fields: Dict[str, FieldMeta] = {}
    formula_fields: Dict[str, FieldMeta] = {}
    npc_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME,
        "favor": FieldMeta(type="number", range_min=0, range_max=9999),
        "price": F_PRICE,
        "items": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="item")),
    }
    # 条件加成（细化_3b §3.2 join/属性联动配置）：每点 source → target +per_point
    # 结构 conditional.json = { "conditional": [ {id, source, target, per_point, note} ] }
    conditional_fields: Dict[str, FieldMeta] = {
        "conditional": FieldMeta(
            type="list",
            element=FieldMeta(
                type="obj",
                children={
                    "id": F_ID,
                    "name": F_NAME,
                    "source": FieldMeta(type="str", required=True),   # 触发属性（引 stats 键空间）
                    "target": FieldMeta(type="str", required=True),   # 产出属性（引 stats 键空间）
                    "per_point": FieldMeta(type="number"),            # 每点产出量（缺省 1）
                    "note": FieldMeta(type="str"),
                },
            ),
        ),
    }

    return {
        "manifest": ModuleMeta(entry_type="object", fields=manifest_fields),
        "effects": ModuleMeta(entry_type="list", fields=effects_fields, kind="effect", namespace="effect_family"),
        "statuses": ModuleMeta(entry_type="list", fields=statuses_fields, kind="status", namespace="effect_family"),
        "marks": ModuleMeta(entry_type="list", fields=marks_fields, kind="mark", namespace="effect_family"),
        "skill_chains": ModuleMeta(entry_type="list", fields=skill_chains_fields, kind="skill_chain",
                                   namespace="chain_lib", chain_field="next"),
        "action": ModuleMeta(entry_type="list", fields=action_fields, kind="action", namespace="action_lib"),
        "formula": ModuleMeta(entry_type="map", fields=formula_fields, kind="formula", namespace="formula_lib"),
        "items": ModuleMeta(entry_type="list", fields=items_fields, kind="item", namespace="item_lib"),
        "equipment": ModuleMeta(entry_type="list", fields=equipment_fields, kind="equipment",
                                namespace="item_lib", mutex_field="excludes"),
        "traits": ModuleMeta(entry_type="list", fields=traits_fields, kind="trait", namespace="trait_lib"),
        "enemies": ModuleMeta(entry_type="list", fields=enemies_fields, kind="enemy", namespace="enemy_lib"),
        "maps": ModuleMeta(entry_type="list", fields=maps_fields, kind="map", namespace="map_lib"),
        "stats": ModuleMeta(entry_type="map", fields=stats_fields, kind="stat", namespace="stat_lib",
                            key_regex=r"[a-z][a-z0-9_]*"),
        "npc": ModuleMeta(entry_type="list", fields=npc_fields, kind="npc", namespace="npc_lib"),
        # 条件加成（细化_3b §3.2；环 + 引用存在性专项校验见 validator._check_conditional）
        "conditional": ModuleMeta(entry_type="object", fields=conditional_fields,
                                  kind="conditional", namespace="cond_lib"),
    }


def default_field_meta_table() -> FieldMetaTable:
    """实例化缺省字段元数据表（每次调用返回全新实例，避免跨包共享可变引用）。"""
    modules = _module_table()
    # stats 键空间条目字段（map 值对象 schema：属性键已由 key_regex + id 键空间约束）
    modules["stats"] = ModuleMeta(
        entry_type="map",
        fields={},
        kind="stat",
        namespace="stat_lib",
        key_regex=r"[a-z][a-z0-9_]*",
        value_meta=FieldMeta(type="obj", children=STAT_CHILDREN),
    )
    # formula：键=公式名，值为公式字符串或 {formula: 表达式}（长度>4KB / AST 黑名单 → 红拦，§3.3）
    modules["formula"] = ModuleMeta(
        entry_type="map",
        fields={},
        kind="formula",
        namespace="formula_lib",
        value_meta=FieldMeta(type="formula"),
    )
    return FieldMetaTable(modules=modules, namespaces=dict(NAMESPACES))


__all__ = ["default_field_meta_table", "FieldMeta", "ModuleMeta", "FieldMetaTable"]
