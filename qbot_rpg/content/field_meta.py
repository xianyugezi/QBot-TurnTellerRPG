"""字段元数据表缺省实现（细化_3e §5.3：校验唯一数据源；新字段 = 本表加一行，校验器零代码变更）。

依据：
  - 细化_3e_loader校验接线 §5.2（每模块校验清单：manifest/effects/statuses/marks/skill_chains/action/
    formula/items/equipment/traits/enemies/maps/stats/npc）
  - 细化_3e_loader校验接线 §5.3（全部字段的 名称/类型/默认值/范围/引用目标 从本表读取；缺失字段默认放行）
  - 细化_3a_架构分层契约 §3.3 U2（Def 类落 content/，本表同为 content/ 数据）
  - 细化_1d_印记系统契约（marks：type="mark"、max_stack=0 不限、duration "battle"/"turns:N"）
  - 细化_3b_玩家属性三层 §4.2（StatDef：name/type/base/growth/role/mh_map/note）
  - 细化_1e_怪物八段schema §1.1~1.6（enemies 八段 18 顶层字段 + stats 九键 + 双维弱点 + 行动表/
    特殊行动/连招 + 掉落三类 + lore）+ m2_shared_contract 第一、四节（M2 A1 路权威字段表）
  - T26（action.json AI 字段：weight/probability/intent/cooldown/condition/hungry/chain/charge_*/
    preview/preview_chain/reveal_condition/armor/interrupt/tags）

⚠️ 字段口径说明（M2 2026-08-26 升级）：enemies 表已由 M0 简化口径（顶层 hp/atk/def/drop_rate/
monster_def_rate）重建为**八段正式表**（细化_1e F01~F18）。M0 旧键**保留注册但标记废弃**
（测试依赖其 R-2/Y-1/Y-2 行为：enemies[].hp 负值红拦、drop_rate 极值黄提示、monster_def_rate
负数容错）；八段新字段按 细化_1e 逐行登记。`type`（dummy 标记）保留 str 不设枚举——
M0 旧包 type:"monster" 需继续放行，枚举判定归 A2 校验器路。条件必填（普通怪八段齐备 vs 木桩豁免）
属 A2 判定口径，本表一律不设 required（避免误拦 M0 旧包）；联合形态字段（drops.count =
number|[min,max]）不注册、走 §2.3 默认放行，防泛型校验器 R-1 误判（A2 R13 专项校验）。

铁律：只提供「字段口径」默认值；editor/CSV/Schema/validator 四处共用一张元数据表（L140），
正式表在编辑器里程碑注入，本文件为 M0 引擎可运行的缺省口径。枚举尽量宽松，避免误阻断合法包。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
# M9 锻造（m9_shared_contract）：forge 模块 ModuleMeta + items 材料类扩展 +
# settings.forge 段。forge_models/forge_settings 仅依赖 content.models（零 field_meta
# import，无循环依赖）；字段定义自包含持有，本表单向 import（防 G0 反向依赖）。
from qbot_rpg.content.forge_models import forge_module_meta
from qbot_rpg.content.forge_settings import ITEMS_FORGE_FIELDS, forge_settings_meta
# M10 钓鱼（m10_shared_contract）：fishing 模块 ModuleMeta + settings.fishing 段。
# fishing_models 仅依赖 content.models（零 field_meta import，无循环依赖）；
# fishing_settings_meta 自包含持有（防 field_meta↔fishing 循环依赖）。
from qbot_rpg.content.fishing_models import fishing_module_meta, fishing_settings_meta

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
    # M4 交互系统（m4_shared_contract §3.1~3.4）：商店/任务/签到独立注册表
    "shop_lib": ("shop",),
    "quest_lib": ("quest",),
    "checkin_lib": ("checkin",),
    # M8 炼金（m8_contract_数据与校验 §一/§三）：recipe/proficiency 独立注册表
    # （slots 无 id 收集不登记 namespace；equip_id 引用 item 走 item_lib）
    "recipe_lib": ("recipe",),
    "proficiency_lib": ("proficiency",),
    # M11 成就（m11 启动包 §2.1）：achievements 独立注册表（顶层 list）
    "achievement_lib": ("achievements",),
    # M13 技能库（细化_6a_技能库契约 §1：skills.json 玩家技能库独立注册表；
    # 与 action 库共用 ActionCore 元数据单点但 ID 各自独立——V-10 跨库重名仅黄提示，
    # 不并入 action_lib，保持双库 ID 空间独立）
    "skill_lib": ("skills",),
    # M13 职业库（细化_6b_职业库与变换引擎契约 §1：jobs.json 职业注册表独立命名空间；
    # 职业 ID 为存档引用键 + 快照冗余键（§1.1 字段 1），独立于 skills/action 双库 ID 空间）
    "job_lib": ("jobs",),
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
# enemies 八段子结构（细化_1e §1.1~1.6 / m2_shared_contract 第一节；M2 A1 路）
# -------------------------------------------------------------------------------------
# stats 九键（1.2 S01-S09；漏配键按难度模板补全 → 不设 required）
ENEMY_STATS_CHILDREN: Dict[str, FieldMeta] = {
    "hp": FieldMeta(type="number", range_min=0, range_max=99999),
    "mp": FieldMeta(type="number", range_min=0, range_max=99999),
    "str": FieldMeta(type="number", range_min=0, range_max=9999),
    "int": FieldMeta(type="number", range_min=0, range_max=9999),
    "con": FieldMeta(type="number", range_min=0, range_max=9999),
    "spr": FieldMeta(type="number", range_min=0, range_max=9999),
    "foc": FieldMeta(type="number", range_min=0, range_max=9999),
    "agi": FieldMeta(type="number", range_min=0, range_max=9999),
    "luk": FieldMeta(type="number", range_min=0, range_max=9999),
}
# 双维弱点（1.3 W01-W02；elements 键=元素 ID → 增伤倍率，元素注册表引用检查归 A2 R3）
WEAKNESS_CHILDREN: Dict[str, FieldMeta] = {
    "types": FieldMeta(type="list", element=FieldMeta(type="str")),
    "elements": FieldMeta(type="obj"),
}
# 天然抗性（1.3 W03-W04；其余键=负面效果 ID → 0-100，未注册键默认放行、A2 引用检查）
RESISTANCE_CHILDREN: Dict[str, FieldMeta] = {
    "immune": FieldMeta(type="list", element=FieldMeta(type="str")),
}
# actions[] 条目（1.4 A01-A03d；probability 纯入池开关 0/1 → 不挂 probability 旗标防 Y-2 噪音）
ACTION_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "action": FieldMeta(type="ref", ref_target="action", required=True),
    "probability": FieldMeta(type="number", range_min=0, range_max=1),
    "weight": FieldMeta(type="number", range_min=0, range_max=100),
    "condition": FieldMeta(type="str"),  # 条件权重修正（obj 形态 A2 放宽）
    "cooldown": FieldMeta(type="number", range_min=0, range_max=999),
    "hungry": FieldMeta(type="number", range_min=0, range_max=999),
}
# special_actions[].trigger（1.4 A06-A09；type 13 类枚举 + x_ 前缀 → str，A2 R2/R11/R12）
SPECIAL_ACTION_TRIGGER_CHILDREN: Dict[str, FieldMeta] = {
    "type": FieldMeta(type="str"),
    "value": FieldMeta(type="number"),
    "timing": FieldMeta(type="str"),  # current_turn/next_turn/first_turn（A2）
    "action": FieldMeta(type="str"),
    "chance": FieldMeta(type="number", range_min=0, range_max=100),
}
# special_actions[] 条目（1.4 A04-A15）
SPECIAL_ACTION_CHILDREN: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str"),
    "action": FieldMeta(type="ref", ref_target="action", required=True),
    "trigger": FieldMeta(type="obj", children=SPECIAL_ACTION_TRIGGER_CHILDREN),
    "once": FieldMeta(type="bool"),
    "priority": FieldMeta(type="number"),
    "trigger_cooldown": FieldMeta(type="number", range_min=0, range_max=999),
    "max_triggers": FieldMeta(type="number", range_min=0, range_max=999),
    "post_state": FieldMeta(type="obj", children={
        "state": FieldMeta(type="str"),
        "turns": FieldMeta(type="number"),
    }),
    "chain_ref": FieldMeta(type="str"),  # → chains[].id（引用存在 A2 R15）
}
# chains[].actions[] 节点（1.4 F14 / AI 定稿 §八：{action, chance 0-1, role, armor}）
CHAIN_NODE_CHILDREN: Dict[str, FieldMeta] = {
    "action": FieldMeta(type="ref", ref_target="action", required=True),
    "chance": FieldMeta(type="number", range_min=0.0, range_max=1.0),
    "role": FieldMeta(type="enum", enum=("chain", "finisher")),
    "armor": FieldMeta(type="bool"),  # 霸体免疫打断
}
# chains[] 条目（F14）
CHAIN_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str"),
    "actions": FieldMeta(type="list", element=FieldMeta(type="obj", children=CHAIN_NODE_CHILDREN)),
}
# drops 三类容器条目（1.5 D01-D04；count 联合形态 number|[min,max] → 不注册默认放行，A2 R13）
DROP_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "item": FieldMeta(type="ref", ref_target="item", required=True),
    "chance": FieldMeta(type="number", range_min=0, range_max=100),
    "condition": FieldMeta(type="str"),  # pv_broken/no_damage/after_action:<id>（A2 R13）
    # "count": 不注册（number | [min,max] 联合形态；泛型校验器无联合类型，误判风险 → §2.3 默认放行）
}
DROPS_CHILDREN: Dict[str, FieldMeta] = {
    "battle": FieldMeta(type="list", element=FieldMeta(type="obj", children=DROP_ENTRY_CHILDREN)),
    "special": FieldMeta(type="list", element=FieldMeta(type="obj", children=DROP_ENTRY_CHILDREN)),
    "death": FieldMeta(type="list", element=FieldMeta(type="obj", children=DROP_ENTRY_CHILDREN)),
}
# lore[] 条目（1.6 L01-L02；unlock 1-100 递增 → 递增判定 A2 R6）
LORE_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "unlock": FieldMeta(type="number", range_min=1, range_max=100, required=True),
    "desc": FieldMeta(type="str"),
}

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
# 1g4 世界边界：settings.death_penalty（F-01~F-04）+ settings.currencies + maps 复活点
# （F-05/F-06）。依据：细化_1g4 §6.1/§6.2/§6.3 + docs/m2_shared_contract 第七节。
# 硬拦规则（F-02 货币引用存在 / F-02·F-04 数值合法 / 超时键不识别）见 validator
# `_check_settings_1g4`（本表只做字段口径 + 泛型 R-1~R-5/Y-1~Y-8；专用规则走专项钩子）。
# -------------------------------------------------------------------------------------
DEATH_PENALTY_CHILDREN: Dict[str, FieldMeta] = {
    # F-01 虚弱时长（秒）默认 60【框架 L285】；负数 → R-2 泛型硬拦；0=不虚弱仅建议不拦截
    "weak_duration_sec": FieldMeta(type="int", range_min=0, range_max=86400),
    # F-02 掉落货币清单 [{currency, ratio}]；空=不掉【框架 L287】；currency 引用存在性 +
    # ratio∈(0,1] 硬拦归 _check_settings_1g4（ref 目标为 settings 内部键空间，非注册表 kind）
    "drop_currency": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "currency": FieldMeta(type="str"),
        "ratio": FieldMeta(type="number", range_min=0.0, range_max=1.0),
    })),
    # F-03 掉落经验 {enabled, percent}【框架 L288】；enabled=false 时 percent 惰性不校验（6.3）
    "drop_exp": FieldMeta(type="obj", children={
        "enabled": FieldMeta(type="bool"),
        "percent": FieldMeta(type="number", range_min=0.0, range_max=100.0),
    }),
    # F-04 随机掉落物品件数 {enabled, count}【框架 L289】；count ≥ 1 整数硬拦归 _check_settings_1g4
    "drop_items": FieldMeta(type="obj", children={
        "enabled": FieldMeta(type="bool"),
        "count": FieldMeta(type="int", range_min=1, range_max=9999),
    }),
}
CURRENCY_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    # 货币键空间（3h §5.1 / 框架 L1096-1097）：id=机器键 snake_case、cap 0=不设上限
    "id": F_ID, "name": FieldMeta(type="str"), "icon": FieldMeta(type="str"),
    "cap": FieldMeta(type="int", range_min=0, range_max=999999),
    "note": FieldMeta(type="str"),
}
# settings 模块已注册字段（其余段 level_cap/pvp/time_cycle/... 由 3h 路登记，缺省放行 §2.3）
SETTINGS_FIELDS: Dict[str, FieldMeta] = {
    "currencies": FieldMeta(type="list", element=FieldMeta(type="obj", children=CURRENCY_ENTRY_CHILDREN)),
    "death_penalty": FieldMeta(type="obj", children=DEATH_PENALTY_CHILDREN),
    # 2026-09-03 用户拍板：装备槽位 = 内容包可配置项（8 槽需求根因——引擎原硬编码
    # 6 槽）。settings.slots 段形态（对齐 core/equipment.EquipmentEngine slots 注入）：
    #   {"slots": {"weapon": {"name": "武器", "max": 1, "occupies": []}, ...}}
    # 装配层 make_context 读它注入 ctx["slots"]（渲染层 _slot_order/_slot_name 消费）
    # + ctx["equip_engine"]（EquipmentEngineAdapter(slots=...)）；缺省无配置 → 默认 6 槽。
    # 注意：与 M8 slots.json 模块（装饰珠插槽 {equip_id, slots:[{slot_level}]}）是
    # 不同数据空间——这里是「装备部位定义」；字段 key 用 slot_defs 避免与既有撞名。
    "slot_defs": FieldMeta(type="obj", children={}, soft_label=True),
}

# =============================================================================
# M8 炼金字段扩展（m8_contract_数据与校验 §四/§五）：items 扩展 / slots 模块 / settings.alchemy 段。
# 定义归属本文件（schema 之家），alchemy_settings 专项校验器单向 import 本表——
# 防 field_meta↔alchemy_settings 循环依赖（G0 TC-03 静态 import 图铁律，函数级 import 亦成环）。
# 收口裁决 2026-08-29：0B 路产出的字段定义迁移至此统一持有。
# =============================================================================
# 品质档键集（B1 拍板②：只允许 common/uncommon/rare/legendary；中文 普通/精良/史诗/传说）
QUALITY_KEYS: Tuple[str, ...] = ("common", "uncommon", "rare", "legendary")
QUALITY_KEYS_CN: Tuple[str, ...] = ("普通", "精良", "史诗", "传说")

# 职业等级枚举（7 档称号；settings 段多处引用，ALC-11/ALC-24/energy_max/decompose_rate）
JOB_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")

# ALC-11 catalyst_unlock_tier 枚举 = 职业等级 7 档 ∪ 默认值 "expert"（=专家 的英文别名）。
# 【工程补白 P-9】契约 §五 默认列写 "expert"、枚举列写中文 7 档（R-07）——同一档，并入 "expert"。
CATALYST_UNLOCK_TIER_ENUM: Tuple[str, ...] = JOB_TIER_NAMES + ("expert",)

# 分解回收率档位（ALC-10：6 档、表自正式起、无见习——见习无分解 DEC-01/05）
DECOMPOSE_TIER_NAMES: Tuple[str, ...] = ("正式", "精通", "专家", "大师", "宗师", "王")

# ALC-01 mode 枚举（定稿 L410 / EDGE-04）
MODE_VALUES: Tuple[str, ...] = ("full", "simple", "off")

# ALC-06 pp_refresh 枚举（定稿 L415 / INH-09：仅 "会话重置"）
PP_REFRESH_ENUM: Tuple[str, ...] = ("会话重置",)

# ALC-22 宝石产出公式枚举（拍板①：默认平铺 flat；rate=⌊基础值×回收率⌋）
DECOMPOSE_FORMULA_ENUM: Tuple[str, ...] = ("flat", "rate")

# ALC-02 合法档位数：3/5/7 可配；4 = B1 固定键集默认档【工程补白 P-2】；0=不限制走兜底
QUALITY_TIER_COUNTS: Tuple[int, ...] = (3, 4, 5, 7)

# ALC-16 珠同名递减默认表（定稿 L420 / BEL-10；空/0=无递减）
DEFAULT_GEM_DIMINISH: Tuple[Tuple[int, float], ...] = ((2, 0.5), (3, 0.25))

# ALC-21 数量上限默认（int32 max，拍板⑤）
MAX_QTY_DEFAULT: int = 2147483647

# ALC-20/20' 战斗即时调合默认（定稿 L425）
BATTLE_ALCHEMY_DEFAULT: Dict[str, object] = {"auto_use": True, "per_battle_limit": 1}

# 8 元素注册表（地水火风雷晶月无；items.elements / REC-05 element_req 引用，定稿 L387）
ALCHEMY_ELEMENTS: Tuple[str, ...] = ("地", "水", "火", "风", "雷", "晶", "月", "无")

# gem.* 中文键（ALC-14/ALC-23/ALC-15，键名照契约原样含点号）
GEM_DECOMPOSE_KEY = "gem.分解"          # ALC-13（拍板②键集）
GEM_DUPLICATE_KEY = "gem.复制"          # ALC-14（复制费基准率，可浮点，拍板④）
GEM_COST_INT_KEYS: Tuple[str, ...] = ("gem.成品合成", "gem.配方合成", "gem.特性合成", "gem.珠升阶")
GEM_EXTRA_KEY = "gem.复制额外"           # ALC-23（复制额外消耗，拍板④）
GEM_EXTRA_ALIAS = "copy_extra_cost"      # ALC-23 别名【工程补白 P-7】
GEM_SECRET_KEY = "gem.秘钥"              # ALC-15（已砍，遗留键 → W 提示）
GEM_DECOMPOSE_FORMULA_KEY = "gem.decompose_formula"  # ALC-22【工程补白键，拍板①】

# 中文段键（ALC-19/ALC-20）
BATTLE_ITEM_KEY = "战斗道具"
BATTLE_ALCHEMY_KEY = "战斗即时调合"

# items.rarity 键名 3 档（契约 §4.1 中文 普通/稀有/金色）
ITEM_RARITY_KEYS: Tuple[str, ...] = ("普通", "稀有", "金色")

# items.json 炼金扩展字段（契约 §四 4.1）
ITEMS_ALCHEMY_FIELDS: Dict[str, FieldMeta] = {
    # type 补 装饰珠 值（另 触媒 type=触媒 供 catalyst 过滤下拉）；seed 可种植标记（定稿 L381/L492）
    # —— 既有 items_fields 的 type 为 str 不设枚举（防误拦既有内容包），此处同口径
    "type": FieldMeta(type="str"),
    # quality 珠等级=品质档（拍板②：common/uncommon/rare/legendary ↔ 普通/精良/史诗/传说，L257/L380）
    "quality": FieldMeta(type="enum", enum=QUALITY_KEYS, default="common"),
    # elements 元素属性值（8 元素 地水火风雷晶月无，投料累计判定 element_req，L380/L152）
    "elements": FieldMeta(type="obj", children={
        el: FieldMeta(type="number", range_min=0) for el in ALCHEMY_ELEMENTS
    }),
    # traits 继承特性 ID 集（炼金珠/成品独有；标准版恒空 TSC-03，L380/L117）。
    # —— 只用 str 结构校验，不设 ref_target：既有 M2 内容包 items.traits 为旧语义
    #    （未知字段放行），登记 ref 会引发泛型 R-4 强校验存量 → 大量误拦；
    #    深引用存在性校验归批7 装饰珠/镶嵌引擎运行时（收口裁决 2026-08-29）。
    "traits": FieldMeta(type="list", element=FieldMeta(type="str")),
    # awaken 觉醒标记（✨素材投料，宗师；并入 traits 效果表，L380/L204）
    "awaken": FieldMeta(type="bool", default=False),
    # rarity 普通/稀有/金色（素材用；3 档默认，契约 §4.1 中文）
    "rarity": FieldMeta(type="enum", enum=ITEM_RARITY_KEYS),
    # base_effects 珠基础效果，固定数值（标准珠=只有这个；炼金珠 base_effects+traits 两套词条，L265/L381）
    "base_effects": FieldMeta(type="obj"),
    # seed 可种植标记（/种植 种子，批10A，L381/L392）
    # M8 批14 收口：软标注（soft_label=永不红拦）——引擎 HarvesterEngine._seed_info
    # 支持两形态（true 简单形态 / {output,quality_floor,traits,...} 收获表形态 L392），
    # 校验器不重复硬拦（「只建议不限制」哲学；非法形态引擎返回 None 安全拒绝）。
    "seed": FieldMeta(type="bool", default=False, soft_label=True),
}

# slots.json 模块字段（契约 §四 4.2）
# 【工程补白 P-4】slots = M8 新增注册模块，与 EQP-04 部位定义形态（core/equipment.py L134
# {slots:{id:def}}）是不同数据空间：slots.json 条目形态 = {equip_id, slots:[{slot_level}]}
# （定稿 L258/L260：1=只装普通 / 2=精良及以下 / 3=全部含传说；槽位数 1-3【工程补白 SOCK-01】）。
SLOTS_FIELD_DEFS: Dict[str, FieldMeta] = {
    # equip_id 引用 items 或 equipment（共享 item_lib；泛型 ref 只能单一 kind →
    # 用 str + validate_slots 跨 items∪equipment 表查，防 equipment 引用误拦）
    # 【收口裁决 2026-08-29】
    "equip_id": FieldMeta(type="str", required=True),
    "slots": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "slot_level": FieldMeta(type="int", range_min=1, range_max=3),
    })),
}


def slots_module_meta() -> ModuleMeta:
    """slots 模块 ModuleMeta（entry_type=list；equip_id 引用 items∪equipment）。

    注：namespace 缺省（模块内唯一）；equip_id 全局唯一由 validate_slots 专项保证。
    """
    return ModuleMeta(entry_type="list", fields=SLOTS_FIELD_DEFS, kind="slots")


# settings.alchemy 段 FieldMeta（契约 §五 全字段表）
ALCHEMY_SETTINGS_FIELD_DEFS: Dict[str, FieldMeta] = {
    # ALC-01（L410）
    "mode": FieldMeta(type="enum", enum=MODE_VALUES, default="full"),
    # ALC-02（L411/QLT-02/03/05）值形态 [lo,hi] 或 {min,max}【工程补白 P-1】
    "quality_tiers": FieldMeta(type="obj"),
    # ALC-03（L412/QLT-04）
    "quality_coef": FieldMeta(type="obj"),
    # ALC-04（L413/QLT-13）
    "chain_map": FieldMeta(type="obj"),
    # ALC-05（L414/TSC-14）
    "pp_cost": FieldMeta(type="obj", children={
        "normal": FieldMeta(type="int", range_min=1),
        "super": FieldMeta(type="int", range_min=1),
    }),
    # ALC-06（L415/INH-09）
    "pp_refresh": FieldMeta(type="str", default="会话重置"),
    # ALC-07（R-08/L416 注）
    "energy_enabled": FieldMeta(type="bool", default=False),
    # ALC-08（L416）
    "energy_max": FieldMeta(type="obj"),
    # ALC-09（L417/LVL-09）
    "energy_regen_sec": FieldMeta(type="int", range_min=0, default=1800),
    "energy_regen_sec_safe": FieldMeta(type="int", range_min=0, default=900),  # 【工程补白键】
    # ALC-10（L418/DEC-02/05）
    "decompose_rate": FieldMeta(type="obj"),
    # ALC-11（R-07；默认 expert = 专家 英文别名【工程补白 P-9】）
    "catalyst_unlock_tier": FieldMeta(
        type="enum", enum=CATALYST_UNLOCK_TIER_ENUM, default="expert",
    ),
    # ALC-12（批5B）
    "catalyst_consume": FieldMeta(type="bool", default=True),
    # ALC-13（L419/拍板②）
    GEM_DECOMPOSE_KEY: FieldMeta(type="obj"),
    # ALC-14（L419/拍板④；复制可浮点）
    GEM_DUPLICATE_KEY: FieldMeta(type="number", range_min=0, default=0.2),
    "gem.成品合成": FieldMeta(type="int", range_min=0, default=10),
    "gem.配方合成": FieldMeta(type="int", range_min=0, default=5),
    "gem.特性合成": FieldMeta(type="int", range_min=0, default=20),
    "gem.珠升阶": FieldMeta(type="int", range_min=0, default=10),
    # ALC-23（拍板④/DUP-03）双键名【工程补白 P-7】
    GEM_EXTRA_KEY: FieldMeta(type="int", range_min=0, default=0),
    GEM_EXTRA_ALIAS: FieldMeta(type="int", range_min=0, default=0),
    # ALC-22（拍板①/DEC-04）【工程补白键】
    GEM_DECOMPOSE_FORMULA_KEY: FieldMeta(type="enum", enum=DECOMPOSE_FORMULA_ENUM, default="flat"),
    # ALC-16（L420/BEL-10）
    "gem_diminish": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "n": FieldMeta(type="int", range_min=2),
        "mult": FieldMeta(type="number", range_min=0.0, range_max=1.0),
    })),
    # ALC-17（L421/EXP-03）
    "synth_exp": FieldMeta(type="str", default="配方等级×1"),
    # ALC-18（L422-423/SP-01/03）
    "sp_per_level": FieldMeta(type="int", range_min=0, default=1),
    "sp_panel": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "id": FieldMeta(type="str"),
        "name": FieldMeta(type="str"),
        "cost": FieldMeta(type="int", range_min=1),
        "repeatable": FieldMeta(type="bool"),
        "max_repeat": FieldMeta(type="int", range_min=1),
        "desc": FieldMeta(type="str"),
    })),
    # ALC-19（L424/BEL-11）
    BATTLE_ITEM_KEY: FieldMeta(type="obj", children={
        "强度公式": FieldMeta(type="str"),
        "珠触发上限": FieldMeta(type="int", range_min=1),
    }),
    # ALC-20 / ALC-20'（L425）
    BATTLE_ALCHEMY_KEY: FieldMeta(type="obj", children={
        "auto_use": FieldMeta(type="bool", default=True),
        "per_battle_limit": FieldMeta(type="int", range_min=1, default=1),
    }),
    # ALC-21（拍板⑤）
    "max_qty": FieldMeta(type="int", range_min=1, default=MAX_QTY_DEFAULT),
    # ALC-24（L34/LVL-06）
    "job_tier_map": FieldMeta(type="obj"),
}


def alchemy_settings_meta() -> FieldMeta:
    """settings.alchemy 段 FieldMeta（type=obj + 全字段 children；合并进 SETTINGS_FIELDS）。"""
    return FieldMeta(type="obj", children=ALCHEMY_SETTINGS_FIELD_DEFS)


# 默认模板货币键空间（F-02 引用存在性兜底：settings 未配 currencies 时按此默认，3h §5.1）
DEFAULT_CURRENCY_IDS: Tuple[str, ...] = ("coins", "diamond")


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
        "max_stack": F_MAX_STACK,
        # duration 权威形态 = 对象 {turns:int, charges:int}（细化_1b §1.2 字段9/子结构 2a）
        # —— 不再用 F_DURATION(number)，否则合法 {turns,charges} 会被 R-1 误拦
        "duration": FieldMeta(type="obj", children={
            "turns": FieldMeta(type="int", range_min=0, range_max=9999),
            "charges": FieldMeta(type="int", range_min=0, range_max=9999),
        }),
        "decay": FieldMeta(type="str"),  # 枚举（per_turn…）由正式表注入
        "effects": F_EFFECTS,
        "on_enter": FieldMeta(type="ref", ref_target="effect"),
        "on_tick": FieldMeta(type="ref", ref_target="effect"),
        "on_expire": FieldMeta(type="ref", ref_target="effect"),
    }
    marks_fields: Dict[str, FieldMeta] = {
        # 印记定稿 §八 数据结构汇总（2026-08-19 定稿对照 P0-1 **部分**修复——5 字段已补；
        # duration/appliable_to 类型本轮 2026-08-24 对齐）：
        # id | name | icon | type=mark | max_stack | appliable_to | polarity
        #  | element(可选) | duration | desc
        "id": F_ID, "name": F_NAME,
        "icon": FieldMeta(type="str"),
        "type": FieldMeta(type="enum", enum=("mark",)),
        "max_stack": F_MAX_STACK,
        # appliable_to 权威 = string[]（细化_1d §1.1 字段6，非空子集 ⊆{self,enemy}）
        "appliable_to": FieldMeta(type="list", element=FieldMeta(type="str")),
        "polarity": FieldMeta(type="enum", enum=("positive", "negative")),
        "element": FieldMeta(type="str"),        # 可选元素引用（element 表 M2 时代入）
        # duration 权威 = "battle" | "turns:N" 字符串（细化_1d §1.1 字段9；印记定稿 §八）
        # —— 不再用 F_DURATION(number)；枚举校验由正式表注入（turns:N 为动态值无法静态枚举）
        "duration": FieldMeta(type="str"),
        "desc": FieldMeta(type="str"),
        "probability": F_PROBABILITY,            # mark_add 概率 proc（AT-10）
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
        # ---- ActionCore 基础（T24-T26 / m2_shared_contract §四）----
        "id": F_ID, "name": F_NAME,
        "kind": FieldMeta(type="str"),  # basic/active/...（枚举判定 A2 路）
        "type": F_TYPE,                  # 旧键兼容
        "power": F_POWER,
        "attack_type": FieldMeta(type="str"),  # 斩/打/突/魔（枚举判定 A2 路）
        "element": FieldMeta(type="str"),      # 元素 ID（元素注册表引用检查 A2/M2）
        "effects": F_EFFECTS,
        "cost": FieldMeta(type="number", range_min=0, range_max=9999),  # 旧键
        "cool": FieldMeta(type="number", range_min=0, range_max=9999),  # 旧键（cooldown 规范名）
        # ---- AI 字段（怪物侧扩展，T26 / m2 §四；缺省兜底不报错）----
        "weight": FieldMeta(type="number", range_min=0, range_max=100),
        # P2-4 修复：不挂 probability 旗标（Y-2 极值误报——0/1 是入池开关非概率值，
        # 与 enemies.actions[].probability 口径一致，1e S1 语义）
        "probability": FieldMeta(type="number", range_min=0, range_max=1),
        "intent": FieldMeta(type="str"),  # 伤害/防御/蓄力/治疗/控制/buff/debuff/印记/功能（枚举 A2）
        "cooldown": FieldMeta(type="number", range_min=0, range_max=999),
        # P2-9 修复：condition 条件权重修正为 obj/string 双形态（1e A03b），
        # str 注册会误拦合法 obj 形态 → 不注册（未知字段默认放行），形态校验留 A2/运行期
        "hungry": FieldMeta(type="number", range_min=0, range_max=999),
        "chain": FieldMeta(type="list", element=FieldMeta(type="str")),  # 历史写法（行动 ID 列表，S2 兼容）
        "armor": FieldMeta(type="bool"),     # 霸体免疫打断（AI 定稿 §八）
        "interrupt": FieldMeta(type="bool"), # 打断行动标记（T19 interrupt 唯一归口）
        "tags": FieldMeta(type="list", element=FieldMeta(type="str")),
        "preview": FieldMeta(type="obj"),          # 意图预告（结构以 1d 系/A2 为准）
        "preview_chain": FieldMeta(type="obj"),    # 链预告（结构以 1d 系/A2 为准）
        "reveal_condition": FieldMeta(type="str"), # 预告揭示条件
        # charge_* 蓄力字段：前缀未知键默认放行（§2.3，键名前缀登记）；结构待 1d 系（A2 专项）
        # ---- M1 旧引用字段（保留）----
        "require_status": FieldMeta(type="ref", ref_target="status"),
        "apply_status": FieldMeta(type="ref", ref_target="status"),
        "skill": FieldMeta(type="ref", ref_target="skill_or_any"),
    }
    skills_fields: Dict[str, FieldMeta] = {
        # ---- M13 技能库（细化_6a_技能库契约 §1.2：A 共用核心 7 字段 F01-F07）----
        # 与 action_fields 的 ActionCore 同构、逐约束同源（§2.2）；skills 侧 attack_type
        # 缺省「按武器」（f4），action 侧按怪物模板——差异在引擎运行期，登记表同构。
        # 类型宽松口径：枚举（kind/type/tag/attack_type/block_mode）走 A2 专项
        # （skill_validator.py V-12/V-13），本表仅登记 str 防泛型误拦（对齐 action 口径）；
        # element/effects 等引用与深结构语义校验由 skills 专项校验器全权（V-1~V-13）。
        # 注意：F07 effects 条目不登记 element=ref —— 专项校验器 V-1 全权（引用 +
        # 原子动作双形态），登记为 ref 会被泛型按整条 dict 报 ref_not_str 误拦。
        "id": F_ID, "name": F_NAME,
        "kind": FieldMeta(type="str"),  # F03 五枚举 damage/heal/status/control/utility（枚举 A2 路）
        "power": F_POWER,               # F04 倍率（滑条 10-500%；派生链累计 ≤1.5× 黄提示 V-6 属 A2）
        "attack_type": FieldMeta(type="str"),  # F05 斩/打/突/魔/无（枚举 A2 路；缺省按武器 f4）
        "element": FieldMeta(type="str", soft_label=True),  # F06 8 元素注册表（V-4 引用检查 A2）；null=按武器元素合法
        # F07 effects：条目不登记 element=ref（双形态：引用 {effect,overrides} /
        # 原子动作 {type,...}，§1.3-f2）——V-1 由 skills 专项校验器全权，登记 ref
        # 会被泛型按整条 dict 报 ref_not_str 误拦（补白见上方 skills_fields 注释）
        "effects": FieldMeta(type="list", element=FieldMeta(type="obj")),
        # ---- B 玩家侧扩展 11 字段（F08-F18，细化_6a §1.2-B）----
        "type": FieldMeta(type="str"),   # F08 basic/active/passive/trigger 四类时机（枚举 A2 路）
        "mp_cost": FieldMeta(type="number", range_min=0, range_max=9999),   # F09 ≥0；basic=0
        "cooldown": FieldMeta(type="number", range_min=0, range_max=999),   # F10 ≥0 整数；basic=0
        "tag": FieldMeta(type="str"),    # F11 none/combo/combo_preserve/combo_push/interrupt/armor（枚举 A2）
        "armor": FieldMeta(type="bool"),         # F12 霸体开关（执行语义快键）
        "interrupt": FieldMeta(type="bool"),     # F13 打断快键（唯一归口 = 效果系统 L0 interrupt，T19）
        "chain_refs": FieldMeta(type="list", element=FieldMeta(type="str")),  # F14 派生链引用 skill_chains.json（V-2）
        "consume_marks": FieldMeta(type="obj"),  # F15 {mark_id: count} 消耗印记（V-3 键存在/上限 A2）
        "job_restrict": FieldMeta(type="list", element=FieldMeta(type="str")),  # F16 职业限制（V-5）
        "job_form": FieldMeta(type="str", soft_label=True),       # F17 形态技（引用 transform 形态名，V-5 扩展判定 A2）；null=非形态技合法
        "level": FieldMeta(type="obj", soft_label=True, children={
            "max": FieldMeta(type="int", range_min=1, range_max=99),
            "growth": FieldMeta(type="list", element=FieldMeta(type="number")),
        }),  # F18 升级 {max, growth}；growth 长度 = max 且 growth[0]=1 级基准（A2 判定）；null=不升级合法
        # ---- C 全库补充 2 字段（F19-F20，细化_6a §1.2-C）----
        "hits": FieldMeta(type="int", range_min=1, range_max=99),  # F19 多段次数（1 轮 1 行动，每段独立结算）
        "trigger_limit": FieldMeta(type="obj", children={
            "per_round": FieldMeta(type="int", range_min=0, zero_unlimited=True),
            "per_battle": FieldMeta(type="int", range_min=0, zero_unlimited=True),
        }),  # F20 触发上限 {per_round, per_battle}；0=不限；技能级 > 库级 defaults > 全局（V-8 引擎强制）
        # ---- D 细化定型 4 字段（F21-F24，细化_6a §1.2-D）----
        "desc": FieldMeta(type="str"),   # F21 一句话说明（技能卡/战报/编辑器悬浮）
        "hit_mod": FieldMeta(type="number", range_min=0.0, range_max=10.0),  # F22 命中率修正（乘数，>0）
        "crit_mod": FieldMeta(type="number", range_min=0.0, range_max=10.0),  # F23 会心判定修正（乘数，>0）
        "block_mode": FieldMeta(type="str"),  # F24 auto/normal/ignore（枚举 A2 路；魔攻击无视格挡规则同源）
        # ---- 兼容旧键（enemies[].skills 引用的技能表旧键）----
        "skill": FieldMeta(type="ref", ref_target="skill_or_any"),
    }
    jobs_fields: Dict[str, FieldMeta] = {
        # ---- M13 职业库（细化_6b_职业库与变换引擎契约 §1.1：顶层 11 字段）----
        # 与 skills_fields 同源模式：枚举宽松口径（difficulty 软标注不拦截；resource_axes/
        # mechanic_tags/weapon_types 引用深校验归 4B 专项），本表仅登记字段口径 + 必填。
        # 注意：transform 段嵌套必填（§1.3 字段 21/22/23/25/26/28/29）登记在子对象 children
        # 上——泛型 R-5 required_missing 对 obj 子字段生效（validator._check_value obj 分支）；
        # duration 枚举 turns|battle 与 state_policy 三键枚举 clear|keep 随契约登记，
        # 枚举外值 → 泛型 R-1 红拦（V4/V5 判定基底，深引用校验 V1~V3/V6~V8 归 4B 专项）。
        "id": F_ID, "name": F_NAME,           # 1/2 职业唯一 ID + 显示名（禁空格，A2 专项）；name 必填归 4B 专项
        "difficulty": FieldMeta(type="str", soft_label=True),  # 3 simple|advanced|complex（软标注：只建议不拦截）
        "playstyle": FieldMeta(type="str"),   # 4 玩法一句话（≤20 字，专项）
        "recommended_newbie": FieldMeta(type="bool"),  # 5 推荐新手？（注册缺省职业取推荐标记）
        "resource_axes": FieldMeta(type="list", element=FieldMeta(type="str")),  # 6 stats.json 注册表引用（4B 专项）
        "mechanic_tags": FieldMeta(type="list", element=FieldMeta(type="str")),  # 7 机制标签（软标注）
        "weapon_types": FieldMeta(type="list", element=FieldMeta(type="str")),   # 8 可用武器类型（4b 联动）
        "growth": FieldMeta(type="obj", children={
            # 12-20 九属性职业成长率（缺省 0；白值增量=白值×growth×职业成长率，3b B2 管线）
            "str": FieldMeta(type="number", range_min=0, range_max=10),
            "int": FieldMeta(type="number", range_min=0, range_max=10),
            "con": FieldMeta(type="number", range_min=0, range_max=10),
            "spr": FieldMeta(type="number", range_min=0, range_max=10),
            "foc": FieldMeta(type="number", range_min=0, range_max=10),
            "agi": FieldMeta(type="number", range_min=0, range_max=10),
            "lck": FieldMeta(type="number", range_min=0, range_max=10),
            "hp": FieldMeta(type="number", range_min=0, range_max=10),
            "mp": FieldMeta(type="number", range_min=0, range_max=10),
        }),
        # 10 transform 段（§1.3 字段 21-31；缺省=无形态切换职业）
        "transform": FieldMeta(type="obj", children={
            "transform_skill": FieldMeta(type="str", required=True),   # 21 触发技能 ID（V2 归属校验 4B）
            "transform_to": FieldMeta(type="str", required=True),      # 22 目标形态 ID（V1/V3 4B）
            "duration": FieldMeta(type="enum", enum=("turns", "battle"), required=True),  # 23 turns|battle
            "turns": FieldMeta(type="int", range_min=1, range_max=999),  # 24 条件必填（duration=turns，4B）
            "revert": FieldMeta(type="bool", required=True),          # 25 结束后还原（battle+true → V4 红拦 4B）
            "cooldown": FieldMeta(type="int", range_min=0, range_max=999, required=True),  # 26 形态冷却
            "dispel_reverts": FieldMeta(type="bool", default=True),   # 27 被驱散→还原钩子（默认 true）
            "state_policy": FieldMeta(type="obj", required=True, children={
                # 32-34 三键 {clear, keep} 二值枚举（§1.4；枚举外值 → 泛型 R-1，V5 判定基底）
                "combo": FieldMeta(type="enum", enum=("clear", "keep"), default="clear"),
                "marks": FieldMeta(type="enum", enum=("keep", "clear"), default="keep"),
                "buff": FieldMeta(type="enum", enum=("keep", "clear"), default="keep"),
            }),
            "skill_set": FieldMeta(type="str", required=True),        # 29 形态技能组 ID（V8 4B）
            "equip_restrict": FieldMeta(type="list", element=FieldMeta(type="str")),  # 30 形态装备限制（可空）
            "derive_chains": FieldMeta(type="list", element=FieldMeta(type="str")),   # 31 形态专属派生链（V8 4B）
        }),
        "description": FieldMeta(type="str"),  # 11 职业介绍文案（3d 注册表渲染）
    }
    # 技能/链侧挂点字段（细化_6b §1.5/§1.6）：revert_form（37）与 derive_only（38）为
    # skills.json 字段、job_scope（39）为 skill_chains.json 字段——随 6a 技能库全量字段
    # 登记；6a 尚未登记前此处预留（缺口登记于细化_6b 附·未定稿依赖 1/3，由 6a 路收口）
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
        # M8 炼金特性（m8_contract_数据与校验 §二 TSC-04~10）：增量扩展 4 键
        # （保留既有 8 键兼容旧内容包；深结构校验由 alchemy_models.validate_traits 专项全权）
        "rarity": FieldMeta(type="enum", enum=("normal", "super")),  # super=超特性（金色）
        "group": FieldMeta(type="str"),                              # 互斥组（组内最多 1 项）
        "repeatable": FieldMeta(type="bool"),                        # 是否可重复继承
        "source": FieldMeta(type="enum", enum=("素材", "成品", "金色素材")),  # 可继承池分类
    }
    enemies_fields: Dict[str, FieldMeta] = {
        # ---- 八段：基础（细化_1e F01-F06 / m2_shared_contract 第一节）----
        "id": F_ID, "name": F_NAME,
        "tier": FieldMeta(type="enum", enum=("normal", "elite", "boss", "training")),  # F03（默认 normal）
        "type": FieldMeta(type="str"),  # F04 "dummy" 标记；M0 旧包 type:"monster" 兼容 → 枚举判定 A2
        "area": FieldMeta(type="str"),  # F05
        "desc": FieldMeta(type="str"),  # F06
        # ---- stats 九键（F07 / 1.2）----
        "stats": FieldMeta(type="obj", children=ENEMY_STATS_CHILDREN),
        # ---- 弱点 / PV / 抗性（F08-F11 / 1.3）----
        "weakness": FieldMeta(type="obj", children=WEAKNESS_CHILDREN),
        "pv": FieldMeta(type="number", range_min=0, range_max=500),  # F09（档区间仅提示；木桩强制 0 A2）
        "pv_recover": FieldMeta(type="enum", enum=("battle_end", "none")),  # F10
        "resistance": FieldMeta(type="obj", children=RESISTANCE_CHILDREN),  # F11
        # ---- 行动表 / 特殊行动 / 连招（F12-F14 / 1.4）----
        "actions": FieldMeta(type="list", element=FieldMeta(type="obj", children=ACTION_ENTRY_CHILDREN)),  # F12
        "special_actions": FieldMeta(type="list", element=FieldMeta(type="obj", children=SPECIAL_ACTION_CHILDREN)),  # F13
        "chains": FieldMeta(type="list", element=FieldMeta(type="obj", children=CHAIN_ENTRY_CHILDREN)),  # F14
        # ---- 掉落 / 图鉴（F15-F16 / 1.5-1.6）----
        "drops": FieldMeta(type="obj", children=DROPS_CHILDREN),  # F15
        "lore": FieldMeta(type="list", element=FieldMeta(type="obj", children=LORE_ENTRY_CHILDREN)),  # F16
        # ---- 木桩向（F17-F18）----
        "def_base": FieldMeta(type="number", range_min=0, range_max=99999),  # F17（≥0）
        "elem_res": FieldMeta(type="obj"),  # F18（元素 ID → 正减伤/负增伤；注册表引用检查 A2）
        # ---- M0 旧键兼容（已废弃，保留注册：测试依赖 R-2/Y-1/Y-2 行为）----
        "hp": F_HP, "atk": F_ATK, "def": F_DEF,
        # R-09（2026-08-18 用户拍板）：每怪可配怪物防御率（默认 1.0=普通同玩家；
        # 负数 → Y-1 黄提示 + 运行期按 0 护栏，不红拦——allow_negative=True）
        "monster_def_rate": FieldMeta(type="number", range_min=0, range_max=5, allow_negative=True),
        "drop_rate": F_DROP_RATE,
        "effects": F_EFFECTS,
        "traits": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="trait")),
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
        # 1g4 F-05/F-06（细化_1g4 §6.2 / 框架 L291）：safe_zone=是否安全区；
        # respawn_point=复活点指向（引用已注册地图 id，泛型 R-4 存在性检查）
        "safe_zone": FieldMeta(type="bool"),
        "respawn_point": FieldMeta(type="ref", ref_target="map"),
    }
    stats_fields: Dict[str, FieldMeta] = {}
    formula_fields: Dict[str, FieldMeta] = {}
    # M4 交互系统 4 模块（m4_shared_contract §3.1~3.4）：字段口径 fields={} 专项全权——
    # 校验唯一落点 = 各 validate_* 专项校验器（npc_models.validate_npcs / shop_models.validate_shops /
    # quest_models.validate_quests / checkin_models.validate_checkins），泛型字段表空表防误拦
    # （同 dungeon 专项全权口径，细化_3e §5.3 未知字段默认放行 §2.3）。
    # npc 旧占位字段（favor/price/items）为 M0 简化口径，非 2b1 顶层 15 字段 → 移除，由 validate_npcs 全权。
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

    # M8 炼金（m8_contract_数据与校验 §一/§三/§四 4.2）：recipe/proficiency/slots 模块
    # + items 扩展字段 + settings.alchemy 段。recipe/proficiency 字段宽松登记防泛型误拦
    # （深结构校验由 alchemy_models 专项全权）；items/slots/settings.alchemy 定义来自
    # alchemy_settings 模块（0B 路产出，收口接线）——延迟导入防 field_meta↔alchemy_settings 循环依赖。
    recipe_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME,
        # kind 三类：craft 合成标准版 / combine 素材合成 / upgrade N 入→1 出（定稿 L354/L370）
        "kind": FieldMeta(type="enum", enum=("craft", "combine", "upgrade")),
        "level": FieldMeta(type="int", range_min=1, range_max=99),   # L354 准入判定
        "synth_allowed": FieldMeta(type="bool"),                     # L354/L505 深度绕过提示
        "master_only": FieldMeta(type="bool"),                       # L357 大师独占
        # materials（craft/combine）与 inputs/output（upgrade）互斥，双 schema 由专项 REC-11 判定
        "materials": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str"), "count": FieldMeta(type="int", range_min=1),
        })),
        "inputs": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "item": FieldMeta(type="str"), "count": FieldMeta(type="int", range_min=1),
        })),
        "output": FieldMeta(type="obj", children={
            "item": FieldMeta(type="str"), "count": FieldMeta(type="int", range_min=1),
        }),
        "cost": FieldMeta(type="obj", children={
            "coins": FieldMeta(type="int", range_min=0),
            "gem": FieldMeta(type="int", range_min=0),
        }),  # L355（复制费基准=cost.coins，拍板④）
        "slots": FieldMeta(type="int", range_min=2, range_max=10),   # L355
        "element_req": FieldMeta(type="obj"),                        # L355/L152（元素键由专项 REC-05）
        "effects": FieldMeta(type="list", element=FieldMeta(type="str")),  # 双形态解析归专项 REC-06
        "traits_inherit": FieldMeta(type="int", range_min=1, range_max=3),  # L356
        "catalyst": FieldMeta(type="list", element=FieldMeta(type="str")),  # L356/L492
        "combine_from": FieldMeta(type="list", element=FieldMeta(type="str")),  # L357/L390
        "evolve_to": FieldMeta(type="obj", children={
            "id": FieldMeta(type="str"),
            "condition": FieldMeta(type="obj", children={
                "count": FieldMeta(type="int", range_min=1),
                "source": FieldMeta(type="str"),
            }),
        }),  # L357/L200 进化线
        "pp_budget": FieldMeta(type="int", range_min=0),             # 【工程补白】L135/INH-09
    }
    proficiency_fields: Dict[str, FieldMeta] = {
        "id": F_ID,
        "tier_names": FieldMeta(type="list", element=FieldMeta(type="str")),  # 细化_2c5a §5.2
        "job_rank_levels": FieldMeta(type="list", element=FieldMeta(type="int", range_min=0)),
        "exp_sources": FieldMeta(type="obj"),
        "sp_per_level": FieldMeta(type="int", range_min=0),
        "sp_panel": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str"), "name": FieldMeta(type="str"),
            "cost": FieldMeta(type="int", range_min=1),
            "repeatable": FieldMeta(type="bool"),
            "max_repeat": FieldMeta(type="int", range_min=1),
            "desc": FieldMeta(type="str"),
        })),
        "energy": FieldMeta(type="obj", children={
            "enabled": FieldMeta(type="bool"),
            "max_by_tier": FieldMeta(type="list", element=FieldMeta(type="int", range_min=0)),
            "regen_sec": FieldMeta(type="int", range_min=0),
        }),
        "job_tier_map": FieldMeta(type="obj"),
        "titles": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str"), "name": FieldMeta(type="str"),
            "icon": FieldMeta(type="str"), "source": FieldMeta(type="str"),
            "desc": FieldMeta(type="str"),
        })),
    }
    # M8 炼金（m8_contract_数据与校验 §四/§五）：items 扩展 + settings.alchemy 段 + slots 模块
    # 字段定义在本文件头部（schema 之家单向持有，alchemy_settings 专项 import 本表——
    # 防 field_meta↔alchemy_settings 循环依赖，G0 TC-03）
    items_fields.update(ITEMS_ALCHEMY_FIELDS)
    SETTINGS_FIELDS["alchemy"] = alchemy_settings_meta()
    # M9 锻造（m9_shared_contract §八）：items 材料类 material_tier/source + settings.forge 段
    items_fields.update(ITEMS_FORGE_FIELDS)
    SETTINGS_FIELDS["forge"] = forge_settings_meta()
    # M10 钓鱼（m10_shared_contract §一）：settings.fishing 段（fishing_settings_meta
    # 自包含持有，防 field_meta↔fishing 循环依赖）
    SETTINGS_FIELDS["fishing"] = fishing_settings_meta()

    return {
        "manifest": ModuleMeta(entry_type="object", fields=manifest_fields),
        "effects": ModuleMeta(entry_type="list", fields=effects_fields, kind="effect", namespace="effect_family"),
        "statuses": ModuleMeta(entry_type="list", fields=statuses_fields, kind="status", namespace="effect_family"),
        "marks": ModuleMeta(entry_type="list", fields=marks_fields, kind="mark", namespace="effect_family"),
        "skill_chains": ModuleMeta(entry_type="list", fields=skill_chains_fields, kind="skill_chain",
                                   namespace="chain_lib", chain_field="next"),
        "action": ModuleMeta(entry_type="list", fields=action_fields, kind="action", namespace="action_lib"),
        # M13 技能库（细化_6a_技能库契约 §1：skills.json 玩家技能库；F01-F24 全字段登记；
        # kind="skill" 与 loader _KIND_FOR_MODULE + DEF_CLASSES 对齐（路1A SkillDef）；
        # 命名空间 skill_lib 独立于 action_lib——V-10 跨库重名仅黄提示）
        "skills": ModuleMeta(entry_type="list", fields=skills_fields, kind="skill", namespace="skill_lib"),
        # M13 职业库（细化_6b_职业库与变换引擎契约 §1.1~1.4：jobs.json 职业注册表；
        # kind="job" 与 loader _KIND_FOR_MODULE + DEF_CLASSES 对齐（批4 路4A/4B JobDef）；
        # 命名空间 job_lib 独立于 skills/action——职业 ID 为存档引用键 + 快照冗余键，
        # 跨库重名不影响引用解析（V1 校验引职业库 ID 空间）。
        # 字段口径说明：difficulty 软标注（§1.1 字段 3「软标注：校验器只 warning 不拦截」→
        # soft_label 永不红拦）；transform 段必填字段（transform_skill/transform_to/duration/
        # revert/cooldown/state_policy/skill_set）随 §1.3 登记 required；state_policy 三键
        # 枚举 {clear, keep}（§1.4）随契约登记，枚举外值 → 泛型 R-1 红拦（V5 判定基底）；
        # growth 九键缺省 0 不设 required（§1.2）。深结构/引用校验（V1~V8 专项）归批4 路4B
        # job_models.validate_jobs 全权（对齐 skills 专项校验器口径），本表登记字段口径。
        "jobs": ModuleMeta(entry_type="list", fields=jobs_fields, kind="job", namespace="job_lib"),
        "formula": ModuleMeta(entry_type="map", fields=formula_fields, kind="formula", namespace="formula_lib"),
        "items": ModuleMeta(entry_type="list", fields=items_fields, kind="item", namespace="item_lib"),
        "equipment": ModuleMeta(entry_type="list", fields=equipment_fields, kind="equipment",
                                namespace="item_lib", mutex_field="excludes"),
        "traits": ModuleMeta(entry_type="list", fields=traits_fields, kind="trait", namespace="trait_lib"),
        # M8 炼金（m8_contract_数据与校验 §一/§三/§四 4.2）：recipe/proficiency 新增登记四件套；
        # slots 由 alchemy_settings.slots_module_meta() 提供（kind=slots，与 loader 注册表同名）
        "recipe": ModuleMeta(entry_type="list", fields=recipe_fields, kind="recipe", namespace="recipe_lib"),
        "proficiency": ModuleMeta(entry_type="list", fields=proficiency_fields,
                                  kind="proficiency", namespace="proficiency_lib"),
        "slots": slots_module_meta(),
        # M9 锻造（m9_shared_contract §〇~§六）：forge.json 顶层 obj——模块级 ModuleMeta
        # 由 forge_module_meta() 提供（entry_type=object）；深结构校验由
        # validate_forge 专项全权（V1-V15/W + 2c2d V1-V8/W1-W4），泛型只做顶层形态
        "forge": forge_module_meta(),
        # M10 钓鱼（m10_shared_contract §三）：fishing.json 顶层 obj——模块级 ModuleMeta
        # 由 fishing_module_meta() 提供（entry_type=object）；深结构校验由
        # validate_fishing 专项全权（V1-V6/W1），泛型只做顶层形态（对齐 forge/dungeon）
        "fishing": fishing_module_meta(),
        "enemies": ModuleMeta(entry_type="list", fields=enemies_fields, kind="enemy", namespace="enemy_lib"),
        "maps": ModuleMeta(entry_type="list", fields=maps_fields, kind="map", namespace="map_lib"),
        # M3 副本（m3_shared_contract §4）：新结构由 dungeon_models.validate_dungeons 专项全权，
        # fields={} 空表防泛型误拦（专项自校验 type/maps/boss/safe_zone 等深结构）
        "dungeon": ModuleMeta(entry_type="list", fields={}, kind="dungeon", namespace="dungeon_lib"),
        "stats": ModuleMeta(entry_type="map", fields=stats_fields, kind="stat", namespace="stat_lib",
                            key_regex=r"[a-z][a-z0-9_]*"),
        # M4 交互系统（m4_shared_contract §3.1~3.4）：npc/shop/quest/checkin 专项全权
        # （fields={} 空表防泛型误拦；深结构由各 validate_* 专项校验器全权，同 dungeon 口径）
        "npc": ModuleMeta(entry_type="list", fields={}, kind="npc", namespace="npc_lib"),
        "shop": ModuleMeta(entry_type="list", fields={}, kind="shop", namespace="shop_lib"),
        "quest": ModuleMeta(entry_type="list", fields={}, kind="quest", namespace="quest_lib"),
        "checkin": ModuleMeta(entry_type="list", fields={}, kind="checkin", namespace="checkin_lib"),
        # M11 成就（4c §1.5）：顶层 list，fields 空表 + 专项校验器全权（对齐 quest/npc 口径）
        "achievements": ModuleMeta(entry_type="list", fields={}, kind="achievement",
                                   namespace="achievement_lib"),
        # 条件加成（细化_3b §3.2；环 + 引用存在性专项校验见 validator._check_conditional）
        "conditional": ModuleMeta(entry_type="object", fields=conditional_fields,
                                  kind="conditional", namespace="cond_lib"),
        # 通用设置（细化_1g4 §6.1 death_penalty + currencies 段；其余段由 3h 路登记缺省放行）。
        # 注意：settings.json 为常驻模块（3h D-01），本表仅登记字段口径；loader 常驻加载归 3h/M 接线。
        "settings": ModuleMeta(entry_type="object", fields=SETTINGS_FIELDS),
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


__all__ = [
    "default_field_meta_table", "FieldMeta", "ModuleMeta", "FieldMetaTable",
    # 1g4 世界边界（细化_1g4 §6；settings 段 + maps F-05/F-06 字段口径）
    "DEATH_PENALTY_CHILDREN", "CURRENCY_ENTRY_CHILDREN", "SETTINGS_FIELDS",
    "DEFAULT_CURRENCY_IDS",
]
