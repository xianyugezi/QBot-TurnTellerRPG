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

from dataclasses import replace
from typing import Any, Dict, Mapping, Optional, Tuple

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
# M9 锻造（m9_shared_contract）：forge 模块 ModuleMeta + items 材料类扩展 +
# settings.forge 段。forge_models/forge_settings 仅依赖 content.models（零 field_meta
# import，无循环依赖）；字段定义自包含持有，本表单向 import（防 G0 反向依赖）。
from qbot_rpg.content.enhance_models import enhance_module_meta
from qbot_rpg.content.forge_models import forge_module_meta
from qbot_rpg.content.forge_settings import ITEMS_FORGE_FIELDS, forge_settings_meta
# M10 钓鱼（m10_shared_contract）：fishing 模块 ModuleMeta + settings.fishing 段。
# fishing_models 仅依赖 content.models（零 field_meta import，无循环依赖）；
# fishing_settings_meta 自包含持有（防 field_meta↔fishing 循环依赖）。
from qbot_rpg.content.fishing_models import fishing_module_meta, fishing_settings_meta
# 批⑧ 装备词条键空间唯一源（data 层——G0 依赖矩阵 content→{data}，注册表落 data 层
# 供 content/core/commands 全层引用）。
from qbot_rpg.data.gear_stats import (
    GEAR_COMBAT_KEYS,
    GEAR_FLAT_KEYS,
    GEAR_LABELS_ZH,
    GEAR_PCT_KEYS,
)

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

# 常见数值字段（range 仅 Y-1 提示用）。批4.6：unit = 说明卡「数值 / 比例」判定
# 用的展示单位（只影响说明文案，不参与任何校验判定）。
F_PRICE = FieldMeta(type="number", range_min=0, range_max=50000)
F_ATK = FieldMeta(type="number", range_min=0, range_max=5000, unit="点")
F_DEF = FieldMeta(type="number", range_min=0, range_max=5000, unit="点")
F_HP = FieldMeta(type="number", range_min=0, range_max=99999, unit="点")
F_POWER = FieldMeta(type="number", range_min=0, range_max=500)
# 技能倍率（skills.power；按百分比算，100 = 一倍威力）——与 action/effects 的 power 不同，
# 单列一个常量，避免把「倍率 %」误挂到效果强度/行动威力上（批4.6）。
F_SKILL_POWER = FieldMeta(type="number", range_min=0, range_max=500, unit="%")
F_DURATION = FieldMeta(type="number", range_min=0, range_max=999, unit="回合")
F_MAX_STACK = FieldMeta(type="int", zero_unlimited=True, range_min=0, range_max=999, unit="层")
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
# 九属性单位统一为「点」（批4.6 展示维度；说明卡据此判「数值」而非「比例」）。
ENEMY_STATS_CHILDREN = {
    k: replace(v, unit="点") for k, v in ENEMY_STATS_CHILDREN.items()}
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
# 批4 UX：补展示层中文名（label 只影响编辑器列头/表单显示，不参与任何校验判定）。
ACTION_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "action": FieldMeta(type="ref", ref_target="action", required=True, label="行动"),
    "probability": FieldMeta(type="number", range_min=0, range_max=1, label="概率"),
    "weight": FieldMeta(type="number", range_min=0, range_max=100, label="权重"),
    "condition": FieldMeta(type="str", label="条件"),  # 条件权重修正（obj 形态 A2 放宽）
    "cooldown": FieldMeta(type="number", range_min=0, range_max=999, label="冷却"),
    "hungry": FieldMeta(type="number", range_min=0, range_max=999, label="饥饿值"),
}
# special_actions[].trigger（1.4 A06-A09；type 13 类枚举 + x_ 前缀 → str，A2 R2/R11/R12）
SPECIAL_ACTION_TRIGGER_CHILDREN: Dict[str, FieldMeta] = {
    "type": FieldMeta(type="str", label="类型"),
    "value": FieldMeta(type="number", label="数值"),
    "timing": FieldMeta(type="str", label="时机"),  # current_turn/next_turn/first_turn（A2）
    "action": FieldMeta(type="str", label="行动"),
    "chance": FieldMeta(type="number", range_min=0, range_max=100, label="概率"),
    # position_match 方位触发参数（方位 v0.6 §三.2/附录 A Step 1；枚举校验 A2 路）
    "which": FieldMeta(type="str", label="对象"),  # self=怪物自己 / player=玩家
    "side": FieldMeta(type="list", element=FieldMeta(type="str"), label="方位"),
    "height": FieldMeta(type="list", element=FieldMeta(type="str"), label="高度"),
}
# special_actions[] 条目（1.4 A04-A15）
SPECIAL_ACTION_CHILDREN: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", label="标识"),
    "action": FieldMeta(type="ref", ref_target="action", required=True, label="行动"),
    "trigger": FieldMeta(type="obj", children=SPECIAL_ACTION_TRIGGER_CHILDREN, label="触发条件"),
    "once": FieldMeta(type="bool", label="仅触发一次"),
    "priority": FieldMeta(type="number", label="优先级"),
    "trigger_cooldown": FieldMeta(type="number", range_min=0, range_max=999, label="触发冷却"),
    "max_triggers": FieldMeta(type="number", range_min=0, range_max=999, label="最大触发次数"),
    "post_state": FieldMeta(type="obj", label="触发后状态", children={
        "state": FieldMeta(type="str", label="状态"),
        "turns": FieldMeta(type="number", label="持续回合"),
    }),
    "chain_ref": FieldMeta(type="str", label="连招引用"),  # → chains[].id（引用存在 A2 R15）
    # 说明文案（veinborn 实测在数据里出现；原为未登记键 → 编辑器列头只能显示原始键）
    "desc": FieldMeta(type="str", label="说明"),
}
# chains[].actions[] 节点（1.4 F14 / AI 定稿 §八：{action, chance 0-1, role, armor}）
CHAIN_NODE_CHILDREN: Dict[str, FieldMeta] = {
    "action": FieldMeta(type="ref", ref_target="action", required=True, label="行动"),
    "chance": FieldMeta(type="number", range_min=0.0, range_max=1.0, label="概率"),
    "role": FieldMeta(type="enum", enum=("chain", "finisher"), label="角色"),
    "armor": FieldMeta(type="bool", label="霸体"),  # 霸体免疫打断
}
# chains[] 条目（F14）
CHAIN_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", label="标识"),
    "actions": FieldMeta(type="list",
                         element=FieldMeta(type="obj", children=CHAIN_NODE_CHILDREN),
                         label="行动节点"),
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
    # M12.5 批4：settings.json 实测标量键补登记（编辑器 obj 表单渲染源——
    # default_map 引用 map id / world_name 展示名；缺 label 的容器段也补中文段名）
    "default_map": FieldMeta(type="str", label="默认地图"),
    "world_name": FieldMeta(type="str", label="世界名称"),
    "currencies": FieldMeta(type="list", element=FieldMeta(type="obj", children=CURRENCY_ENTRY_CHILDREN), label="货币"),
    "death_penalty": FieldMeta(type="obj", children=DEATH_PENALTY_CHILDREN, label="死亡惩罚"),
    # 2026-09-03 用户拍板：装备槽位 = 内容包可配置项（8 槽需求根因——引擎原硬编码
    # 6 槽）。settings.slots 段形态（对齐 core/equipment.EquipmentEngine slots 注入）：
    #   {"slots": {"weapon": {"name": "武器", "max": 1, "occupies": []}, ...}}
    # 装配层 make_context 读它注入 ctx["slots"]（渲染层 _slot_order/_slot_name 消费）
    # + ctx["equip_engine"]（EquipmentEngineAdapter(slots=...)）；缺省无配置 → 默认 6 槽。
    # 注意：与 M8 slots.json 模块（装饰珠插槽 {equip_id, slots:[{slot_level}]}）是
    # 不同数据空间——这里是「装备部位定义」；字段 key 用 slot_defs 避免与既有撞名。
    "slot_defs": FieldMeta(type="obj", children={}, soft_label=True, label="装备槽位"),
}

# =============================================================================
# M12 批4 路4A：quest/shop/npc/checkin 正式字段表注入（编辑器 19 页 meta_source
# 数据源，P-07；此前 fields={} 专项全权，编辑器无字段元数据 → 表单无法渲染）。
# 依据：docs/细化/细化_5a2_编辑器扩展页.md（NPC 10 标签 N-01~10 / 签到 7 区 CK-01~08）
# + 真实内容包 content/test_demo/{quest,shop,npc,checkin}.json 条目口径（实测交叉验证）。
# 宽松登记原则（对齐蓝图风险 2）：专项校验器（validate_quests/shops/npcs/checkins）
# 全权深结构，本表只登记「字段口径 + label」供编辑器表单——仅 id required=True；
# 嵌套容器一律 obj children={} / list element obj 防泛型误拦（str|dict|list 多形态
# 字段用 soft_label 直通）；枚举仅在契约闭合处登（真实内容零新增拦截）。
# =============================================================================

# ---- quest（quest_models L270-271 17 顶层；reward str|dict|list 三形态 2b4 D-01）----
QUEST_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="任务 ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "desc": FieldMeta(type="str", label="描述"),
    "type": FieldMeta(type="str", label="类型"),
    "main": FieldMeta(type="bool", label="主线标记"),
    "zone": FieldMeta(type="str", label="区域"),
    "consume": FieldMeta(type="obj", children={}, soft_label=True, label="消耗"),
    "repeatable": FieldMeta(type="bool", label="可重复"),
    "conditions": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                            label="解锁条件"),
    "reward": FieldMeta(type="obj", children={}, soft_label=True,
                        label="奖励（支持 货币/物品/多形态）"),
    "board": FieldMeta(type="obj", children={}, soft_label=True, label="任务板"),
    "timed": FieldMeta(type="obj", children={}, soft_label=True, label="限时"),
    "unlock_chain": FieldMeta(type="str", soft_label=True, label="解锁链（前驱任务 ID）"),
    "filter": FieldMeta(type="obj", children={}, soft_label=True, label="筛选"),
    "bonus": FieldMeta(type="obj", children={}, soft_label=True, label="加成"),
    "npc": FieldMeta(type="obj", children={}, soft_label=True, label="NPC 关联"),
    "daily": FieldMeta(type="obj", children={}, soft_label=True, label="每日"),
}

# ---- shop（shop_models 顶层访问器 15；refresh 4 模式×5 key；条目 price 混合支付）----
SHOP_ITEM_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "item": FieldMeta(type="str", label="物品引用"),
    "price": FieldMeta(type="obj", children={}, soft_label=True, label="价格（混合支付）"),
    "stock": FieldMeta(type="int", label="库存"),
    "limit": FieldMeta(type="int", label="限购"),
    "period": FieldMeta(type="obj", children={}, soft_label=True, label="上架时段"),
}
SHOP_REFRESH_CHILDREN: Dict[str, FieldMeta] = {
    "mode": FieldMeta(type="str", enum=("daily", "weekly", "manual", "fixed"), label="刷新模式"),
    "start": FieldMeta(type="str", label="开始时间"),
    "end": FieldMeta(type="str", label="结束时间"),
    "hour": FieldMeta(type="int", label="刷新小时"),
    "interval": FieldMeta(type="int", label="间隔天数"),
}
SHOP_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="商店 ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "icon": FieldMeta(type="str", label="图标"),
    "type": FieldMeta(type="str", enum=("normal", "general", "black", "reputation",
                                        "event", "quest"), label="类型"),
    "currency": FieldMeta(type="str", label="默认货币"),
    "level_required": FieldMeta(type="int", label="等级门槛"),
    "reputation_required": FieldMeta(type="obj", children={}, soft_label=True,
                                     label="声望门槛"),
    "open_condition": FieldMeta(type="obj", children={}, soft_label=True,
                                label="开放条件"),
    "refresh": FieldMeta(type="obj", children=SHOP_REFRESH_CHILDREN, soft_label=True,
                         label="刷新规则"),
    "items": FieldMeta(type="list", element=FieldMeta(type="obj",
                                                      children=SHOP_ITEM_ENTRY_CHILDREN),
                       label="商品列表"),
    "pool": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                      soft_label=True, label="黑市池"),
    "price_fluctuation": FieldMeta(type="obj", children={}, soft_label=True,
                                   label="价格波动"),
    "visible": FieldMeta(type="bool", label="可见"),
    "desc": FieldMeta(type="str", label="描述"),
    "listing_count": FieldMeta(type="int", label="上架数（黑市）"),
}

# ---- npc（NPCDef 顶层 15 + 6 子表；type 6 枚举 / dealer strategy 3 枚举）----
NPC_DIALOGUE_OPTION_CHILDREN: Dict[str, FieldMeta] = {
    "text": FieldMeta(type="str", label="选项文本"),
    "next": FieldMeta(type="str", label="下一对话"),
    "action": FieldMeta(type="obj", children={}, soft_label=True, label="选项动作"),
}
NPC_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="NPC ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "icon": FieldMeta(type="str", label="图标"),
    "map": FieldMeta(type="obj", children={}, soft_label=True, label="地图挂点"),
    "type": FieldMeta(type="str", enum=("merchant", "blacksmith", "quest", "inn",
                                        "alchemist", "fisher", "quest_giver",
                                        "tutor"), label="类型"),
    "desc": FieldMeta(type="str", label="描述"),
    "visible": FieldMeta(type="bool", label="可见"),
    "dialogues": FieldMeta(type="obj", children={
        "greeting": FieldMeta(type="obj", children={}, soft_label=True, label="问候语"),
        "options": FieldMeta(type="list",
                             element=FieldMeta(type="obj", children=NPC_DIALOGUE_OPTION_CHILDREN),
                             label="对话选项"),
    }, label="对话"),
    "interactions": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                              soft_label=True, label="交互"),
    "quests": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                        soft_label=True, label="任务"),
    "dealer": FieldMeta(type="obj", children={}, soft_label=True, label="商人配置"),
    "repair": FieldMeta(type="obj", children={}, soft_label=True, label="修理"),
    "tutorials": FieldMeta(type="list", element=FieldMeta(type="str"), label="教学"),
    "shop_refs": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                           soft_label=True, label="商店引用"),
    # 批4.5：实测顶层键（原表未登记 → 纯展示宽字段）
    "intel_refs": FieldMeta(type="list", soft_label=True, label="情报引用"),
}

# ---- checkin（CheckinDef 顶层 7+bonus；period.start/end 仅 activity 必填不设 required）----
CHECKIN_PERIOD_CHILDREN: Dict[str, FieldMeta] = {
    "cycle_days": FieldMeta(type="int", label="周期天数"),
    "reset_on_break": FieldMeta(type="bool", label="断签重置"),
    "start": FieldMeta(type="str", label="开始日期（activity）"),
    "end": FieldMeta(type="str", label="结束日期（activity）"),
}
CHECKIN_REWARD_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "day": FieldMeta(type="int", label="第 N 天"),
    "days": FieldMeta(type="int", label="连续 N 天"),
    "items": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                       soft_label=True, label="物品奖励"),
    "coins": FieldMeta(type="int", label="金币"),
    "gem": FieldMeta(type="int", label="宝石"),
    "exp": FieldMeta(type="int", label="经验"),
    "rep": FieldMeta(type="int", label="声望"),
}
CHECKIN_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="签到表 ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "type": FieldMeta(type="str", enum=("loop", "monthly", "activity"), label="周期类型"),
    "desc": FieldMeta(type="str", label="描述"),
    "period": FieldMeta(type="obj", children=CHECKIN_PERIOD_CHILDREN, label="周期配置"),
    "rewards": FieldMeta(type="obj", children={
        "daily": FieldMeta(type="list",
                           element=FieldMeta(type="obj", children=CHECKIN_REWARD_ENTRY_CHILDREN),
                           label="每日奖励"),
        "streak": FieldMeta(type="list",
                            element=FieldMeta(type="obj", children=CHECKIN_REWARD_ENTRY_CHILDREN),
                            label="连签奖励"),
        "monthly_total": FieldMeta(type="list",
                                   element=FieldMeta(type="obj", children=CHECKIN_REWARD_ENTRY_CHILDREN),
                                   label="月度累计奖励"),
    }, label="奖励配置"),
    "makeup": FieldMeta(type="obj", children={}, soft_label=True, label="补签规则"),
}

# ---- M12.5 批1 路1C：C 类空表宽松注入（对齐 M12 4A npc 注入先例——仅 id required
#      + 宽 obj/list 容器 + 闭合枚举；深结构由专项校验器 dungeon_models/
#      achievements_models 全权，泛型并行零新增拦截；编辑器表单数据源 P-07）----
# 依据 docs/m125_模块字段摸底.md：dungeon.json 实测 9 顶层键（2 条，maps=list(4)/
# subquests=list/safe_zone=str 引用 map id/drops=obj 深嵌套）；type 实测闭合值
# {explore,boss}；entry_limit 数值但专项全权 → 宽容器不设 range 防误拦。
DUNGEON_MAP_ELEM_CHILDREN: Dict[str, FieldMeta] = {
    # maps.json 地图条目顶层键并集（9 内容包实测：id/name/desc/npcs/monsters/exits/
    # mechanics/gate_guard/gather_points/dungeon_entrances；mechanics/gather_points
    # 为 list-of-dict 深嵌套 → 宽容器防误拦）
    "id": FieldMeta(type="str", label="地图 ID"),
    "name": FieldMeta(type="str", label="地图名"),
    "desc": FieldMeta(type="str", label="描述"),
    "npcs": FieldMeta(type="list", element=FieldMeta(type="str"), label="NPC 列表"),
    "monsters": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        # monsters 刷怪行并集键（9 包实测 enemy/count/respawn_minutes；veinborn 扩展
        # name/hidden_boss/intro/signal；细化_2a1b §2.1 另含 active_time/seasons/
        # periods/weather_weights 时段天气键——宽松登记，专项刷怪校验 R24-26 全权）
        "enemy": FieldMeta(type="str", label="怪物引用"),
        "count": FieldMeta(type="int", label="同时在场上限"),
        "respawn_minutes": FieldMeta(type="int", label="刷新间隔(分钟)"),
        "name": FieldMeta(type="str", label="展示名"),
        "hidden_boss": FieldMeta(type="bool", label="隐藏首领"),
        "intro": FieldMeta(type="str", label="出场台词"),
        "signal": FieldMeta(type="str", label="信号词"),
        "active_time": FieldMeta(type="obj", children={}, soft_label=True,
                                 label="出没钟点窗口"),
        "seasons": FieldMeta(type="list", element=FieldMeta(type="str"),
                             label="季节限定"),
        "periods": FieldMeta(type="list", element=FieldMeta(type="str"),
                             label="时段限定"),
        "weather_weights": FieldMeta(type="obj", children={}, soft_label=True,
                                      label="天气出现率倍率"),
    }), label="刷怪行"),
    "exits": FieldMeta(type="obj", children={}, soft_label=True, label="通道出口"),
    "mechanics": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                            soft_label=True, label="地图机制"),
    "gate_guard": FieldMeta(type="obj", children={}, soft_label=True, label="门卫"),
    "gather_points": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                                soft_label=True, label="采集点"),
    "dungeon_entrances": FieldMeta(type="list", element=FieldMeta(type="obj",
                                                                    children={}),
                                    soft_label=True, label="副本入口"),
}
DUNGEON_DROP_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    # drops.normal/boss 普通掉落行（细化_2a1d §2.4 样例 {item,chance}）
    "item": FieldMeta(type="str", label="掉落物品"),
    "chance": FieldMeta(type="number", label="掉落概率"),
}
DUNGEON_FIRST_CLEAR_CHILDREN: Dict[str, FieldMeta] = {
    "items": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "item": FieldMeta(type="str", label="物品引用"),
        "count": FieldMeta(type="int", label="数量"),
    }), label="首通素材"),
    "title": FieldMeta(type="str", label="称号引用"),
    "codex": FieldMeta(type="list", element=FieldMeta(type="str"), label="图鉴点亮"),
}
DUNGEON_DROPS_CHILDREN: Dict[str, FieldMeta] = {
    # drops 容器实测键并集：normal/boss（list of {item,chance}）+
    # first_clear（首通子段 {items[],title,codex}，细化_2a1d §2.3/§2.4 结构同构）
    "normal": FieldMeta(type="list", element=FieldMeta(type="obj",
                                                        children=DUNGEON_DROP_ENTRY_CHILDREN),
                         label="普通掉落"),
    "boss": FieldMeta(type="list", element=FieldMeta(type="obj",
                                                       children=DUNGEON_DROP_ENTRY_CHILDREN),
                       label="首领掉落"),
    "first_clear": FieldMeta(type="obj", children=DUNGEON_FIRST_CLEAR_CHILDREN,
                              label="首通奖励"),
}
DUNGEON_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="副本 ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "type": FieldMeta(type="str", enum=("explore", "boss"), label="副本类型"),
    "entry_item": FieldMeta(type="str", label="入场道具"),
    "entry_limit": FieldMeta(type="obj", children={}, soft_label=True, label="入场限制"),
    # 实测 maps[] 为 str（引用 maps.json 地图 id，dungeon_models.maps 访问器
    # str 元组）——批1 list[obj] 与实测形态不符，改 list[str] 对齐真实内容；
    # children 细化走 DUNGEON_MAP_ELEM_CHILDREN（maps 页整图编辑，此处只引用 id）
    "maps": FieldMeta(type="list", element=FieldMeta(type="str"), label="地图序列"),
    "boss_room": FieldMeta(type="str", label="首领房地图"),
    "boss": FieldMeta(type="str", label="首领怪物"),
    "subquests": FieldMeta(type="list", element=FieldMeta(type="str"), label="子任务"),
    "safe_zone": FieldMeta(type="str", label="安全区地图"),
    "drops": FieldMeta(type="obj", children=DUNGEON_DROPS_CHILDREN,
                       soft_label=True, label="掉落配置"),
}

# achievements.json 实测 7 顶层键（8 条）+ hidden 段（1 条实测 clue_ref/mode/
# reveal_text）；trigger 实测闭合值 {check}；once 实测 bool true；conditions/
# reward 宽容器（专项 achievements_models ACH01-13 全权）。
ACHIEVEMENT_COND_CHILDREN: Dict[str, FieldMeta] = {
    # conditions 三原语条目并集键（实测 var/op/value/param；4c §2.2 var 注册表 +
    # COND_OPERATORS 9 运算符；[事件:xxx]/x_ 前缀 var 运行时识别 → type=str 宽）
    "var": FieldMeta(type="str", label="变量"),
    "op": FieldMeta(type="str", label="运算符"),
    # value 全包实测恒 int（16/16：成就条件目标值=次数/数值，无字符串形态）——
    # 标 int 闭合真实内容，泛型零误拦
    "value": FieldMeta(type="int", label="目标值"),
    "param": FieldMeta(type="str", label="参数"),
}
ACHIEVEMENT_REWARD_CHILDREN: Dict[str, FieldMeta] = {
    # reward 条目键并集（实测 coins/title；4c §三 + REWARD_ITEM_KEYS 口径含
    # item/id/count/bound + 标量 gem/exp/rep/prof——宽登记防误拦）
    "item": FieldMeta(type="str", label="物品引用"),
    "id": FieldMeta(type="str", label="物品 ID"),
    "count": FieldMeta(type="int", label="数量"),
    "bound": FieldMeta(type="bool", label="绑定"),
    "coins": FieldMeta(type="int", label="金币"),
    "gem": FieldMeta(type="int", label="宝石"),
    "exp": FieldMeta(type="int", label="经验"),
    "rep": FieldMeta(type="int", label="声望"),
    "prof": FieldMeta(type="int", label="熟练度"),
    "title": FieldMeta(type="str", label="称号引用"),
}
ACHIEVEMENT_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="成就 ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "desc": FieldMeta(type="str", label="描述"),
    "conditions": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        # 单对象 ≡ 单元素数组糖（ACH-12）；children 拆三原语逐键可编
        **ACHIEVEMENT_COND_CHILDREN,
    }), label="解锁条件"),
    "trigger": FieldMeta(type="str", enum=("check",), label="触发方式"),
    "once": FieldMeta(type="bool", label="仅一次"),
    "hidden": FieldMeta(type="obj", children={
        # hidden 实测段键（clue_ref/mode/reveal_text，8 条实测 1 条含段）
        "clue_ref": FieldMeta(type="str", label="线索引用"),
        "mode": FieldMeta(type="str", label="隐藏模式"),
        "reveal_text": FieldMeta(type="str", label="揭示文案"),
    }, soft_label=True, label="隐藏配置"),
    "reward": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        **ACHIEVEMENT_REWARD_CHILDREN,
    }), label="奖励"),
}

# ---- AI 视图（5a2 PA-01~06，extends=monster——enemies.json 条目内嵌 AI 键视图；
#      无真实 json 独立模块，按契约最小登记宽容器；表字段语义 = 敌人条目 AI 配置区）----
AI_FIELDS: Dict[str, FieldMeta] = {
    "ai_actions": FieldMeta(type="obj", children={}, soft_label=True, label="行动表"),
    "ai_cond_actions": FieldMeta(type="obj", children={}, soft_label=True,
                                 label="条件行动"),
    "ai_state_machine": FieldMeta(type="obj", children={}, soft_label=True,
                                  label="状态机"),
    "ai_phases": FieldMeta(type="obj", children={}, soft_label=True, label="阶段"),
    "ai_combo": FieldMeta(type="obj", children={}, soft_label=True, label="连招链"),
    "ai_zone_switch": FieldMeta(type="obj", children={}, soft_label=True, label="换区"),
}

# ---- 隐藏要素视图（5a2 PH-01~04：隐藏BOSS/隐藏任务/彩蛋；可达性黄提示由专项管）----
HIDDEN_FIELDS: Dict[str, FieldMeta] = {
    "hidden_boss": FieldMeta(type="obj", children={}, soft_label=True, label="隐藏 BOSS"),
    "hidden_quest": FieldMeta(type="obj", children={}, soft_label=True, label="隐藏任务"),
    "easter_egg": FieldMeta(type="obj", children={}, soft_label=True, label="彩蛋"),
}

# ---- 环境事件视图（5a2 PE-01~04：settings.json env_event 段——窗口条件+效果引用）----
ENV_EVENT_FIELDS: Dict[str, FieldMeta] = {
    "env_event": FieldMeta(type="obj", children={}, soft_label=True,
                           label="环境事件（settings.env_event 段）"),
}

# ---- 日志卡片视图（5a2 PL-01~04：settings.json log_card 段——记录类型/快照/容量）----
LOG_CARD_FIELDS: Dict[str, FieldMeta] = {
    "log_card": FieldMeta(type="obj", children={}, soft_label=True,
                          label="日志卡片（settings.log_card 段）"),
}

# settings 段扩展（5a2 环境事件/日志卡片挂 settings.json；缺省零影响——无配置段不触发）
SETTINGS_FIELDS.setdefault("env_event", FieldMeta(type="obj", children={}, soft_label=True,
                                                  label="环境事件"))
SETTINGS_FIELDS.setdefault("log_card", FieldMeta(type="obj", children={}, soft_label=True,
                                                 label="日志卡片"))

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

# M12.5 需求1 批D：formula 模块 stat_map 段字段口径（编辑器 meta 返回供 stat_map
# 段逐键中文表单化渲染；校验宽松不红拦）。formula.json 顶层 stat_map = {语义键:
# combatant 键}——语义键固定 13 个，值 = combatant 键名字符串（内容包自定义 stat
# 全量透传后任意键合法，stat_map 缺省 = 现值键名零破坏）。
FORMULA_FIELDS: Dict[str, FieldMeta] = {
    "stat_map": FieldMeta(
        type="obj",
        label="属性映射",
        children={
            "hit_focus": FieldMeta(type="str", label="命中·攻击方属性"),
            "hit_spd": FieldMeta(type="str", label="命中·防御方属性"),
            "crit_luck": FieldMeta(type="str", label="会心·攻击方属性"),
            "block_focus": FieldMeta(type="str", label="格挡·防御方属性"),
            "def_con": FieldMeta(type="str", label="防御·防御方属性"),
            "atk_atk": FieldMeta(type="str", label="物理攻击力属性"),
            "mag_int": FieldMeta(type="str", label="魔法攻击力属性"),
            "enemy_str": FieldMeta(type="str", label="敌方力量映射"),
            "enemy_con": FieldMeta(type="str", label="敌方体质映射"),
            "enemy_spr": FieldMeta(type="str", label="敌方精神映射"),
            "enemy_agi": FieldMeta(type="str", label="敌方敏捷映射"),
            "atk_base": FieldMeta(type="str", label="效果攻击力基值属性"),
            "dfn_base": FieldMeta(type="str", label="效果防御基值属性"),
        },
    ),
}

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
    # ALC-20 / ALC-20'（L425）+ ALC-25（方位 v0.6 修正 #8/N2：熟练度乘区配置段；
    # 缺段=引擎无乘区 1.0——默认值不内建，数值归内容包配置）
    BATTLE_ALCHEMY_KEY: FieldMeta(type="obj", children={
        "auto_use": FieldMeta(type="bool", default=True),
        "per_battle_limit": FieldMeta(type="int", range_min=1, default=1),
        "proficiency_multiplier": FieldMeta(type="obj", children={
            "min": FieldMeta(type="number", label="熟练度乘区下限"),
            "max": FieldMeta(type="number", label="熟练度乘区上限"),
            "curve": FieldMeta(type="str", label="乘区曲线形态"),
        }),
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
# 编辑器重写批1：模块级字段分组表（编辑器页签 = 元数据声明的分组，编辑器不写死业务分组）
# -------------------------------------------------------------------------------------
# 口径：
#   · 分组唯一来源 = 元数据（本表 / FieldMeta.group）；编辑器只按它渲染页签。
#   · 只给 skills 模块落地 4 个分组（用户 2026-09-13 拍板：基本/数值/效果列表/文本）；
#     其余模块不给声明 → 编辑器用单一默认分组兜底（缺省兜底，不误伤任何模块）。
#   · 表里允许出现「fields 尚未登记、但真实内容包条目里存在」的键（brief/derive_only/
#     energy_gain/energy_cost/revert_form 等）——这类键照样落进正确分区，不掉进兜底组。
#   · 仅影响界面展示：校验器只读 fields，本表不参与校验（零新增拦截，基线不受影响）。
SKILLS_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("基本", (
        "id", "name", "kind", "type", "attack_type", "element", "tag", "armor",
        "interrupt", "position_rule", "air_policy", "block_mode", "job_restrict",
        "job_form", "counter_type", "counter_skill", "revert_form", "derive_only",
        "skill",
    )),
    ("数值", (
        "power", "break_power", "mp_cost", "cooldown", "hits", "level",
        "trigger_limit", "hit_mod", "crit_mod", "action_time", "air_extend",
        "recovery", "stun",
    )),
    ("效果列表", (
        "effects", "chain_refs", "consume_marks", "energy_gain", "energy_cost",
        "combo_table", "season",
    )),
    ("文本", ("desc", "brief", "detail")),
)
SKILLS_FIELD_GROUPS: Dict[str, str] = {
    _k: _g for _g, _keys in SKILLS_GROUP_DEFS for _k in _keys
}
SKILLS_GROUP_ORDER: Tuple[str, ...] = tuple(_g for _g, _ in SKILLS_GROUP_DEFS)

# skills 字段中文名（显示层唯一来源；用户 2026-09-13 需求 §一.4「字段名一律中文显示」+
# 样式稿 s3 的字段列头）。label 只进显示层，不动数据层、不参与任何校验判定。
SKILLS_FIELD_LABELS: Dict[str, str] = {
    # 基本
    "id": "标识", "name": "名称", "kind": "类别", "type": "类型",
    "attack_type": "攻击类型", "element": "元素", "tag": "标签", "armor": "霸体",
    "interrupt": "打断", "position_rule": "方位命中规则", "air_policy": "空中策略",
    "block_mode": "格挡模式", "job_restrict": "职业限制", "job_form": "形态",
    "counter_type": "反击类型", "counter_skill": "反击技能", "revert_form": "还原形态",
    "derive_only": "仅派生可用", "skill": "技能引用",
    # 数值
    "power": "威力", "break_power": "破坏力固有值", "mp_cost": "消耗量", "cooldown": "冷却",
    "hits": "段数", "level": "等级", "trigger_limit": "触发上限", "hit_mod": "命中修正",
    "crit_mod": "会心修正", "action_time": "行动时间", "air_extend": "空中延长",
    "recovery": "行动恢复", "stun": "气绝值",
    # 效果列表
    "effects": "附加效果", "chain_refs": "派生链引用", "consume_marks": "消耗印记",
    "energy_gain": "资源轴增减", "energy_cost": "资源轴消耗", "combo_table": "组合表达",
    "season": "季节",
    # 文本
    "desc": "说明", "brief": "简述", "detail": "详情",
}


# -------------------------------------------------------------------------------------
# 编辑器重写批3：把「分组」声明扩到更多模块（页签 = 元数据分组；顺序 + 显示名均来自元数据）
# -------------------------------------------------------------------------------------
# 口径与 skills 完全一致，只加**展示层元数据**：
#   · 分组键（group key）用稳定机器键（base/stats/...），界面显示名走 ModuleMeta.group_labels
#     （缺省回退分组键本身，见 qbot_rpg/web/api.py::_group_summary）；
#   · 分组顺序 = group_order（元数据声明；缺省按首次出现顺序，兜底逻辑在 api 层）；
#   · 每模块 2~4 个分组；覆盖该模块 fields 的键 + 真实内容包里常见的未登记键
#     （desc/monsters/exits/ai/phases/rewards 等）——未登记键照样落进正确分区；
#   · **零新增业务字段**、零新增校验拦截（校验器只读 fields，本段不参与任何判定）。
# 新增模块 = 本段加一组常量 + 在 _module_table() 里挂到对应 ModuleMeta，编辑器零改动。
ENEMIES_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # 2026-09-13 用户拍板：HP/ATK/DEF 这类数值**单独一页**，不再塞进「基本」。
    ("base", ("id", "name", "tier", "type", "area", "desc")),
    ("stats", (
        "hp", "atk", "def", "def_base", "monster_def_rate", "drop_rate",
        "stats", "weakness", "resistance", "elem_res", "pv", "pv_recover", "phases",
        "zone_change",
    )),
    ("actions", ("actions", "special_actions", "chains", "skills", "traits", "effects", "parts", "ai")),
    ("drops", ("drops", "lore", "rewards")),
)
ENEMIES_GROUP_LABELS: Dict[str, str] = {
    "base": "基本", "stats": "数值与抗性", "actions": "行动与效果", "drops": "掉落与图鉴",
}

ITEMS_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", (
        "id", "name", "type", "slot", "bind", "usable",
        "quality", "rarity", "material_tier", "source", "awaken", "seed",
    )),
    ("stats", (
        "price", "atk", "def", "dfn", "foc", "hp", "agi", "mp",
        "elements", "base_effects",
        *GEAR_FLAT_KEYS, *GEAR_PCT_KEYS, *GEAR_COMBAT_KEYS,
    )),
    ("effects", ("effects", "traits")),
    ("text", ("desc", "brief", "detail")),
)
ITEMS_GROUP_LABELS: Dict[str, str] = {
    "base": "基本", "stats": "数值与属性", "effects": "效果", "text": "文本",
}
# equipment 是 items 的「同类」模块（共享 items_fields + excludes）：分组表复用 items，
# 只为装备独有的 excludes 补一个归属（否则会掉进兜底组）。
EQUIPMENT_FIELD_GROUPS: Dict[str, str] = {
    _k: _g for _g, _keys in ITEMS_GROUP_DEFS for _k in _keys
}
EQUIPMENT_FIELD_GROUPS["excludes"] = "base"
EQUIPMENT_GROUP_ORDER: Tuple[str, ...] = tuple(_g for _g, _ in ITEMS_GROUP_DEFS)

MAPS_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "battle", "revert", "safe_zone", "camp", "camp_name")),
    ("ranges", ("min", "max", "lower", "upper", "reset", "mechanics")),
    ("refs", ("enemy_pool", "monsters", "exits", "respawn_point", "npcs",
              "gate_guard", "gather_points", "dungeon_entrances")),
    ("text", ("desc",)),
)
MAPS_GROUP_LABELS: Dict[str, str] = {
    "base": "基本", "ranges": "数值与区间", "refs": "关联", "text": "文本",
}

QUEST_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "type", "main", "zone", "repeatable", "desc")),
    ("conditions", ("conditions", "unlock_chain", "consume", "filter")),
    ("reward", ("reward", "bonus", "daily", "board", "timed")),
    ("refs", ("npc",)),
)
QUEST_GROUP_LABELS: Dict[str, str] = {
    "base": "基本", "conditions": "条件", "reward": "奖励", "refs": "关联",
}


# -------------------------------------------------------------------------------------
# 编辑器重写批3.5：各模块**字段**中文名（显示层唯一来源，与 SKILLS_FIELD_LABELS 同款）
# -------------------------------------------------------------------------------------
# 口径：
#   · 只影响展示（`FieldMeta.label` 仅编辑器只读/表单渲染消费），不参与任何校验判定；
#     _decorate_field_meta 只补 label/group，type/required/default/enum/children 全部原样保留。
#   · 字段自带 label 优先（例如装备词条 label 来自 data/gear_stats.GEAR_LABELS_ZH），
#     本表只填空缺键，不覆盖既有 label。
#   · 命名一律取游戏内既有文案：stats.json（hp 生命 / mp 法力 / agi 敏捷 / foc 专注 /
#     spr 精神 / lck 幸运 / atk 攻击 / dfn 防御）、怪物模块设计定稿（pv 防护值）、
#     m12_UX 方案（弱点/PV/抗性）。未在既有文案中出现的键，取值理由见报批记录。
#   · 键名并排由前端统一渲染（中文名为主 + 弱化键名为辅），本表只提供中文名。
ENEMIES_FIELD_LABELS: Dict[str, str] = {
    # 基本
    "id": "标识", "name": "名称", "tier": "怪物档位", "type": "类型",
    "area": "区域", "desc": "说明",
    # 数值与抗性
    "stats": "属性", "weakness": "弱点", "pv": "防护值", "pv_recover": "防护值恢复",
    "resistance": "抗性", "def_base": "基础防御", "elem_res": "元素抗性",
    "hp": "生命", "atk": "攻击", "def": "防御",
    "monster_def_rate": "怪物防御率", "drop_rate": "掉落率",
    # 行动与效果
    "actions": "行动表", "special_actions": "特殊行动", "chains": "连招",
    "effects": "效果", "traits": "特性", "skills": "技能",
    # 掉落与图鉴
    "drops": "掉落", "lore": "图鉴",
}

ITEMS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "type": "类型", "price": "价格",
    "atk": "攻击", "def": "防御", "effects": "效果", "slot": "部位",
    "bind": "绑定", "usable": "可使用", "quality": "品质", "rarity": "稀有度",
    "material_tier": "素材档位", "elements": "元素", "base_effects": "基础效果",
    "traits": "特性", "awaken": "觉醒", "seed": "种子", "source": "来源",
    "desc": "说明",
}
# equipment 与 items 同类（共享 items_fields + excludes）：字段名表复用 items，
# 装备独有的 excludes 单补一个归属（否则该键在中/英文之间没有中文名）。
EQUIPMENT_FIELD_LABELS: Dict[str, str] = dict(ITEMS_FIELD_LABELS)
EQUIPMENT_FIELD_LABELS["excludes"] = "互斥部位"

MAPS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "enemy_pool": "敌人池",
    "battle": "战斗地图", "revert": "回退标记", "safe_zone": "安全区",
    "min": "最小值", "max": "最大值", "lower": "下限", "upper": "上限",
    "reset": "重置", "respawn_point": "复活点",
}

# quest 字段的 label 早已随 M12 字段表（见 QUEST_FIELDS）逐字登记；此处保留同款字段名表，
# 供 decoration 单一入口消费（fm.label 优先，本表实际只兜底未来新增/漏标键，不覆盖既有值）。
QUEST_FIELD_LABELS: Dict[str, str] = {
    "id": "任务 ID", "name": "名称", "desc": "描述", "type": "类型",
    "main": "主线标记", "zone": "区域", "consume": "消耗", "repeatable": "可重复",
    "conditions": "解锁条件", "reward": "奖励（支持 货币/物品/多形态）", "board": "任务板",
    "timed": "限时", "unlock_chain": "解锁链（前驱任务 ID）", "filter": "筛选",
    "bonus": "加成", "npc": "NPC 关联", "daily": "每日",
}

# ---- 批3.5 余量补全：技能族与行动/职业库的字段名表（同样只补空缺 label）----
EFFECTS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "type": "类型", "power": "威力",
    "duration": "持续", "probability": "概率", "max_stack": "最大层数",
    "require_status": "需求状态", "apply_status": "施加状态",
    "require_mark": "需求印记", "apply_mark": "施加印记", "patch": "数值补丁",
    # 批4.5：真实内容包实有顶层键（纯展示宽字段的中文名）
    "actions": "行动表", "class": "类别", "control_type": "控制类型", "count": "层数",
    "desc": "说明", "filter": "筛选", "mark": "印记", "marks_on": "所需印记",
    "part_break_per_tick": "每回合破坏值", "pct": "百分比", "polarity": "极性",
    "skip_turn": "跳过回合", "stat": "属性", "status": "状态", "target": "目标",
    "tick": "触发时点", "trigger": "触发条件", "turns": "持续回合", "value": "数值",
}

STATUSES_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "type": "类型", "max_stack": "最大层数",
    "duration": "持续", "decay": "衰减", "effects": "效果列表",
    "on_enter": "进入时", "on_tick": "每回合", "on_expire": "失效时",
    "desc": "说明", "description": "描述", "on_dodge_effects": "闪避时效果",
}

MARKS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "icon": "图标", "type": "类型",
    "max_stack": "最大层数", "appliable_to": "可施加对象", "polarity": "极性",
    "element": "元素", "duration": "持续", "desc": "说明", "probability": "概率",
    "description": "描述",
}

SKILL_CHAINS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "type": "类型", "next": "下一节点",
    "actions": "行动引用", "effects": "效果列表",
}

ACTION_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "kind": "类别", "type": "类型",
    "position_rule": "方位命中规则", "power": "威力", "attack_type": "攻击类型",
    "element": "元素", "effects": "效果列表", "cost": "消耗",
    "cool": "冷却（旧键）", "weight": "权重", "probability": "概率",
    "intent": "意图", "roar": "咆哮等级", "cooldown": "冷却",
    "recovery": "行动恢复", "hungry": "饥饿值", "chain": "连锁行动",
    "armor": "霸体", "interrupt": "打断", "tags": "标签",
    "preview": "意图预告", "preview_chain": "链预告", "reveal_condition": "揭示条件",
    "require_status": "需求状态", "apply_status": "施加状态", "skill": "技能引用",
    "apply_mark": "施加印记", "condition": "条件", "trigger_limit": "触发上限",
    "charge_armor": "蓄力霸体", "charge_turns": "蓄力回合",
}

JOBS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "difficulty": "难度", "playstyle": "玩法",
    "recommended_newbie": "推荐新手", "resource_axes": "资源轴",
    "mechanic_tags": "机制标签", "weapon_types": "可用武器类型",
    "growth": "成长率", "transform": "形态切换", "description": "职业介绍",
}


# =====================================================================================
# 编辑器重写批4.5：嵌套子字段中文名（递归；含 element.children）
# =====================================================================================
# 与模块级 *_FIELD_LABELS 同款：只补**展示层** label，不参与任何校验判定。
#   · 表形态 {子键: 中文名 | {孙键: ...}}，递归到任意深度；list 元素对象的 children 同样覆盖；
#   · children 里**已声明**的键 → 只补 label（type/required/enum/children 原样保留）；
#   · 真实内容包出现、children **未登记**的键 → 补一个 soft_label=True 的「纯展示子字段」
#     （validator 对 soft_label 立即 return → 校验语义零变化），避免界面留裸键；
#   · **动态键空间**（键名由内容定义：ai.states.<状态名> / settings.slot_defs.<部位> /
#     consume_marks.<印记> / element_req.<元素> / job_tier_map.<档位> 等）**不猜键名**，
#     保持原始键显示，登记于批报「待确认清单」。
# 命名依据：stats.json（hp 生命/mp 法力/…）、docs/m2_shared_contract（enemies 八段 + AI）、
# docs/m3_shared_contract（zone_change）、docs/m13_6a~6c（skills/jobs/skill_chains）、
# docs/veinborn/03_schema_修正稿.md、既有 *_FIELD_LABELS、data/gear_stats.GEAR_LABELS_ZH；
# 术语冲突按 docs/编辑器重写_需求与约束.md §六（mp 法力 / con 体质 / mag 法强 / pv 防护值）。
def _soft_display(label: str, ftype: str = "str",
                  children: Optional[Mapping[str, FieldMeta]] = None,
                  help: Optional[str] = None) -> FieldMeta:
    """纯展示子字段（soft_label=True → 泛型校验短路、永不红拦；仅供编辑器显示中文名/说明）。"""
    return FieldMeta(type=ftype, soft_label=True, label=label, children=dict(children or {}),
                     help=(help or ""))


def _soft_list(label: str, spec: Mapping[str, Any]) -> FieldMeta:
    """纯展示的 list-of-obj 子字段（元素 children 由嵌套中文名表展开）。"""
    return FieldMeta(type="list", soft_label=True, label=label,
                     element=FieldMeta(type="obj", children=_soft_tree(spec)))


def _soft_tree(spec: Mapping[str, Any]) -> Dict[str, FieldMeta]:
    """把嵌套中文名表展开成纯展示子字段表（未登记键的兜底；FieldMeta 值原样收编）。

    容器自身中文名用保留键 `_label` 表达：{"_label": "珠同名递减", "n": "次数", ...}。
    """
    out: Dict[str, FieldMeta] = {}
    for key, sub in spec.items():
        if key == "_label":
            continue
        if isinstance(sub, FieldMeta):
            out[key] = sub if sub.soft_label else replace(sub, soft_label=True)
        elif isinstance(sub, Mapping):
            out[key] = _soft_display(str(sub.get("_label", key)), "obj",
                                     _soft_tree(sub))
        else:
            out[key] = _soft_display(str(sub))
    return out


def _split_help(sub: Any) -> Tuple[Optional[str], Optional[Mapping[str, Any]]]:
    """从嵌套说明表的一项里拆出（本字段说明, 子字段说明表）。

    · 字符串 → 本字段说明（无子说明）；
    · 映射   → `_help` 键为本字段说明，其余键为子字段说明（递归同形态）。
    """
    if isinstance(sub, str):
        return (sub or None, None)
    if isinstance(sub, Mapping):
        own = sub.get("_help")
        kids = {k: v for k, v in sub.items() if k != "_help"}
        return (str(own) if own else None, kids or None)
    return (None, None)


def _decorate_one(fm: FieldMeta, label: Optional[str],
                  nested: Optional[Mapping[str, Any]],
                  help_text: Optional[str] = None,
                  nested_helps: Optional[Mapping[str, Any]] = None) -> FieldMeta:
    """对单个字段补 label/help + 递归装饰 children / element.children（只补展示层）。

    批4.6 起同时可补 `help`（人工说明）；说明表**只作用于已声明的 children 键**，
    不会凭空新建字段节点（未登记键由嵌套中文名表 spec 负责补 soft_label 展示节点）。
    """
    kw: Dict[str, object] = {}
    if label and not fm.label:
        kw["label"] = label
    if help_text and not fm.help:
        kw["help"] = help_text
    has_nested = bool(nested) or bool(nested_helps)
    if has_nested and fm.type == "obj":
        kids = _decorate_tree(fm.children if fm.children else {},
                              nested or {}, nested_helps)
        if kids is not None:
            kw["children"] = kids
    elif has_nested and fm.type == "list":
        elem = fm.element
        if elem is None or elem.type == "obj":
            base = elem.children if (elem is not None and elem.children) else {}
            kids = _decorate_tree(base, nested or {}, nested_helps)
            if kids is not None:
                kw["element"] = replace(
                    elem if elem is not None else FieldMeta(type="obj"),
                    type="obj", children=kids)
    return replace(fm, **kw) if kw else fm


def _decorate_tree(children: Mapping[str, FieldMeta],
                   spec: Mapping[str, Any],
                   helps: Optional[Mapping[str, Any]] = None) -> Optional[Mapping[str, FieldMeta]]:
    """按嵌套中文名表装饰一层 children；有变化返回新表，无变化返回 None（不传 children=）。

    `helps`（批4.6）= 与 spec 平行的嵌套**说明**表；只对已存在的 children 键生效，
    不新增节点（未登记键的 soft 节点由 spec 负责）。
    """
    changed = False
    out: Dict[str, FieldMeta] = {}
    for key, fm in children.items():
        sub = spec.get(key)
        label = sub if isinstance(sub, str) else (
            sub.get("_label") if isinstance(sub, Mapping) else
            (sub.label if isinstance(sub, FieldMeta) else None))
        nested = ({k: v for k, v in sub.items() if k != "_label"}
                  if isinstance(sub, Mapping) else None)
        help_text, nested_helps = _split_help(helps.get(key) if helps else None)
        new_fm = _decorate_one(fm, label, nested, help_text, nested_helps)
        if new_fm is not fm:
            changed = True
        out[key] = new_fm
    for key, sub in spec.items():
        if key in children or key == "_label":
            continue
        help_text, nested_helps = _split_help(helps.get(key) if helps else None)
        if isinstance(sub, FieldMeta):
            base = sub if sub.soft_label else replace(sub, soft_label=True)
            out[key] = replace(base, help=help_text) if (help_text and not base.help) else base
        elif isinstance(sub, Mapping):
            label = str(sub.get("_label", key))
            help_text = help_text or str(sub.get("_help") or "") or None
            out[key] = _soft_display(label, "obj", _soft_tree(sub), help=help_text)
        else:
            out[key] = _soft_display(str(sub), help=help_text)
        changed = True
    return out if changed else None


# ---- enemies（八段嵌套；依据 m2_shared_contract 第一节 + veinborn/test_demo 实测）----
ENEMIES_CHILD_LABELS: Dict[str, Any] = {
    "stats": {"hp": "生命", "mp": "法力", "str": "力量", "int": "智力", "con": "体质",
              "spr": "精神", "foc": "专注", "agi": "敏捷", "luk": "幸运"},
    "weakness": {"types": "弱点类型", "elements": "弱点元素"},
    "resistance": {"immune": "免疫效果", "stun": "气绝抗性"},
    "actions": {"action": "行动", "probability": "概率", "weight": "权重",
                "condition": "条件", "cooldown": "冷却", "hungry": "饥饿值"},
    "special_actions": {
        "id": "标识", "action": "行动", "once": "仅触发一次", "priority": "优先级",
        "trigger_cooldown": "触发冷却", "max_triggers": "最大触发次数",
        "chain_ref": "连招引用", "desc": "说明",
        "trigger": {"type": "触发类型", "value": "数值", "timing": "时机", "action": "行动",
                    "chance": "概率", "which": "对象", "side": "方位", "height": "高度",
                    "mark": "印记", "min": "最小层数", "absent": "印记不存在"},
        "post_state": {"state": "状态", "turns": "持续回合"},
    },
    "chains": {"id": "标识",
               "actions": {"action": "行动", "chance": "概率", "role": "角色", "armor": "霸体"}},
    "drops": {
        "battle": {"_label": "战斗掉落", "item": "掉落物品", "chance": "掉落概率",
                   "condition": "掉落条件", "count": "数量"},
        "special": {"_label": "特殊掉落", "item": "掉落物品", "chance": "掉落概率",
                    "condition": "掉落条件", "count": "数量"},
        "death": {"_label": "死亡掉落", "item": "掉落物品", "chance": "掉落概率",
                  "condition": "掉落条件", "count": "数量"},
    },
    "lore": {"unlock": "解锁进度", "desc": "说明"},
    "parts": {
        "id": "部位 ID", "name": "部位名", "break_threshold": "破坏阈值",
        "target_priority": "命中优先级",
        "positions": {"side": "可达方位", "height": "可达高度"},
        "on_break": {"knockdown": "倒地时长", "marks": "破位印记", "effects": "破位效果"},
    },
    # ai.states 的键 = 内容自定义状态名（动态键空间）→ 只登记静态的 transitions
    "ai": {"transitions": _soft_list("状态转移", {
        "from": "源状态", "to": "目标状态", "condition": "切换条件"})},
    "phases": {
        "threshold": "触发阈值", "enter_action": "进入行动", "broadcast": "播报",
        "actions": _soft_list("行动表", {"action": "行动", "weight": "权重", "probability": "概率"}),
    },
    "rewards": {"exp": "经验"},
    "zone_change": {"enabled": "启用", "hp_threshold": "残血阈值",
                    "targets": "目标怪物", "timing": "切换时机"},
}

# ---- skills（M13 6a；level/trigger_limit/effects/energy 轴）----
SKILLS_CHILD_LABELS: Dict[str, Any] = {
    "level": {"max": "最大等级", "growth": "成长曲线"},
    "trigger_limit": {"per_round": "每回合上限", "per_battle": "每场上限"},
    "effects": {"type": "效果类型", "effect": "效果引用", "target": "目标", "count": "层数",
                "pct": "百分比", "mark": "印记", "status_id": "状态 ID", "marks_on": "所需印记",
                "polarity": "极性", "overrides": "数值覆盖"},
    "consume_marks": {},
}

# ---- jobs（M13 6b：transform 形态切换 + growth 九属性）----
JOBS_CHILD_LABELS: Dict[str, Any] = {
    # growth 契约 = 九属性（m13_6b §1.2）；veinborn 另出现 atk/dfn（超出契约、真实包独有）→
    # 不并入契约键集（job_lib 硬计数门禁要求恰好 9 键），保持原始键显示并记入批报。
    "growth": {"str": "力量", "int": "智力", "con": "体质", "spr": "精神", "foc": "专注",
               "agi": "敏捷", "lck": "幸运", "hp": "生命", "mp": "法力"},
    "transform": {
        "transform_skill": "触发技能", "transform_to": "目标形态", "duration": "持续类型",
        "turns": "持续回合", "revert": "结束后还原", "cooldown": "形态冷却",
        "dispel_reverts": "被驱散还原", "skill_set": "形态技能组",
        "equip_restrict": "形态装备限制", "derive_chains": "形态派生链",
        "state_policy": {"_label": "状态策略", "combo": "连段", "marks": "印记", "buff": "增益"},
    },
}

# ---- maps（整图编辑；maps_fields 缺登记的地图段一并补展示层）----
MAPS_CHILD_LABELS: Dict[str, Any] = {
    "monsters": {"enemy": "怪物引用", "count": "同时在场上限",
                 "respawn_minutes": "刷新间隔(分钟)", "name": "展示名",
                 "hidden_boss": "隐藏首领", "intro": "出场台词", "signal": "信号词"},
    "exits": {
        "up": {"to": "目标地图", "mode": "通行模式", "condition": "解锁条件"},
        "down": {"to": "目标地图", "mode": "通行模式", "condition": "解锁条件"},
        "left": {"to": "目标地图", "mode": "通行模式", "condition": "解锁条件"},
        "right": {"to": "目标地图", "mode": "通行模式", "condition": "解锁条件"},
    },
    "mechanics": {"id": "标识", "desc": "说明",
                  "on_step": {"type": "类型", "damage": "伤害"}},
    "gather_points": {"id": "标识", "item": "物品引用", "rarity": "稀有度", "rate": "概率"},
    "dungeon_entrances": {"dungeon": "副本引用", "name": "名称"},
    "camp": {"name": "名称", "safe": "安全区", "unlock": "解锁方式"},
}

# ---- quest（conditions 条件行 / reward 多形态 / npc 关联）----
QUEST_CHILD_LABELS: Dict[str, Any] = {
    "conditions": {"var": "变量", "op": "运算符", "value": "目标值", "param": "参数"},
    "npc": {"id": "标识"},
    "reward": {"coins": "金币", "gem": "宝石", "exp": "经验", "rep": "声望",
               "prof": "熟练度", "item": "物品引用", "count": "数量"},
}

# ---- effects / statuses / marks（技能族：效果词条 + 状态桶 + 印记）----
EFFECTS_CHILD_LABELS: Dict[str, Any] = {
    "patch": {"target": "目标", "value": "数值", "pct": "百分比"},
    "actions": {"type": "类型", "count": "层数", "mark": "印记", "target": "目标"},
}
STATUSES_CHILD_LABELS: Dict[str, Any] = {
    "duration": {"turns": "持续回合", "charges": "层数"},
}
MARKS_CHILD_LABELS: Dict[str, Any] = {}

# ---- skill_chains（M13 6a steps 派生链）----
SKILL_CHAINS_CHILD_LABELS: Dict[str, Any] = {
    "steps": {"from": "源技能", "to": "目标技能", "tag": "标签", "priority": "优先级",
              "mode": "模式", "armor": "霸体", "consume": "消耗",
              "condition": {"count": "计数"},
              "variant_override": {"power": "威力"}},
}

# ---- action（AI 字段里的条件/触发上限补充；deeper 由 ACTION_FIELD_LABELS 覆盖）----
ACTION_CHILD_LABELS: Dict[str, Any] = {}

# ---- npc（交互动作 15 键 + 对话选项）----
NPC_CHILD_LABELS: Dict[str, Any] = {
    "dialogues": {
        "greeting": {},
        "options": {"text": "选项文本", "next": "下一对话", "action": "选项动作",
                    "quests": "任务", "shop_refs": "商店引用", "intel_refs": "情报引用",
                    "tutorials": "教学", "heal": "治疗", "cost": "消耗"},
    },
    "interactions": {
        "action": "交互动作", "text": "文本", "repeat": "可重复", "turns": "持续回合",
        "map": "地图挂点", "items": "物品", "effects": "效果",
        "quests": {"quest_id": "任务 ID"},
        "condition": {"var": "变量", "op": "运算符", "value": "数值", "param": "参数"},
        "cost": {"coins": "金币"},
        "heal": {"hp": "生命", "mp": "法力"},
    },
    "quests": {"quest_id": "任务 ID"},
}

# ---- shop（商品条目 + 刷新规则）----
SHOP_CHILD_LABELS: Dict[str, Any] = {
    "items": {"sold_out_once": "售罄后下架"},
    "refresh": {},
    "pool": {},
}

# ---- checkin（奖励条目里的 items[]）----
CHECKIN_CHILD_LABELS: Dict[str, Any] = {
    "rewards": {
        "daily": {"items": {"id": "物品 ID", "count": "数量"}},
        "streak": {"items": {"id": "物品 ID", "count": "数量"}},
        "monthly_total": {"items": {"id": "物品 ID", "count": "数量"}},
    },
    "period": {},
}

# ---- dungeon（掉落/首通已带 label；此处兜底）----
DUNGEON_CHILD_LABELS: Dict[str, Any] = {
    "drops": {},
    "entry_limit": {},
}

# ---- achievements（条件/奖励/hidden 已带 label）----
ACHIEVEMENT_CHILD_LABELS: Dict[str, Any] = {
    "conditions": {},
    "reward": {},
    "hidden": {},
}

# ---- traits / recipe / proficiency / slots（M8 炼金 + 特性）----
TRAITS_CHILD_LABELS: Dict[str, Any] = {}
RECIPE_CHILD_LABELS: Dict[str, Any] = {
    "materials": {"id": "物品 ID", "item": "物品引用", "count": "数量"},
    "inputs": {"item": "物品引用", "count": "数量"},
    "output": {"item": "物品引用", "count": "数量"},
    "cost": {"coins": "金币", "gem": "宝石"},
    "evolve_to": {"id": "目标物品",
                  "condition": {"_label": "进化条件", "count": "数量", "source": "来源"}},
}
PROFICIENCY_CHILD_LABELS: Dict[str, Any] = {
    "sp_panel": {"id": "标识", "name": "名称", "cost": "消耗", "repeatable": "可重复",
                 "max_repeat": "最大次数", "desc": "说明"},
    "energy": {"enabled": "启用", "max_by_tier": "各档上限", "regen_sec": "恢复秒数"},
    "titles": {"id": "标识", "name": "名称", "icon": "图标", "source": "来源", "desc": "说明"},
}
SLOTS_CHILD_LABELS: Dict[str, Any] = {
    "slots": {"slot_level": "槽位等级"},
}

# ---- conditional（细化_3b 条件加成）----
CONDITIONAL_CHILD_LABELS: Dict[str, Any] = {
    "conditional": {"id": "标识", "name": "名称", "source": "来源属性",
                    "target": "产出属性", "per_point": "每点产出", "note": "备注"},
}

# ---- manifest（包清单；模块层级声明的子结构 label）----
MANIFEST_CHILD_LABELS: Dict[str, Any] = {
    "module_tree": {"module": "模块", "label": "显示名", "children": "子模块"},
    "module_groups": {"module": "模块", "label": "显示名", "children": "子模块"},
}

# ---- settings（世界设置；段子结构兜底 —— alchemy/forge/fishing 深表见各段模块）----
SETTINGS_CHILD_LABELS: Dict[str, Any] = {
    "currencies": {"id": "标识", "name": "名称", "icon": "图标",
                   "cap": "上限", "note": "备注"},
    "death_penalty": {
        "weak_duration_sec": "虚弱时长(秒)",
        "drop_currency": {"_label": "掉落货币", "currency": "货币", "ratio": "比例"},
        "drop_exp": {"_label": "掉落经验", "enabled": "启用", "percent": "百分比"},
        "drop_items": {"_label": "掉落物品", "enabled": "启用", "count": "数量"},
    },
    "alchemy": {
        "mode": "模式", "quality_tiers": "品质档位数", "quality_coef": "品质系数",
        "chain_map": "连锁映射",
        "pp_cost": {"_label": "点数消耗", "normal": "普通消耗", "super": "超级消耗"},
        "pp_refresh": "点数刷新时机", "energy_enabled": "启用精力",
        "energy_max": "精力上限", "energy_regen_sec": "精力恢复秒数",
        "energy_regen_sec_safe": "安全区精力恢复秒数", "decompose_rate": "分解回收率",
        "catalyst_unlock_tier": "触媒解锁档位", "catalyst_consume": "消耗触媒",
        "gem.分解": "宝石分解", "gem.复制": "宝石复制", "gem.成品合成": "成品合成",
        "gem.配方合成": "配方合成", "gem.特性合成": "特性合成", "gem.珠升阶": "珠升阶",
        "gem.复制额外": "复制额外消耗", "copy_extra_cost": "复制额外消耗(别名)",
        "gem.decompose_formula": "宝石分解公式",
        "gem_diminish": {"_label": "珠同名递减", "n": "同名次数", "mult": "递减倍率"},
        "synth_exp": "合成经验", "sp_per_level": "每级技能点",
        "sp_panel": {"_label": "技能面板", "id": "标识", "name": "名称", "cost": "消耗",
                     "repeatable": "可重复", "max_repeat": "最大次数", "desc": "说明"},
        "战斗道具": {"_label": "战斗道具", "强度公式": "强度公式", "珠触发上限": "珠触发上限"},
        "战斗即时调合": {"_label": "战斗即时调合", "auto_use": "自动使用",
                   "per_battle_limit": "每场上限",
                   "proficiency_multiplier": {"_label": "熟练度乘区", "min": "下限",
                                              "max": "上限", "curve": "曲线形态"}},
        "max_qty": "数量上限", "job_tier_map": "职业档位映射",
        "farming": {"_label": "种植", "enabled": "启用种植", "harvest_sec": "收获秒数",
                    "plots_max": "最大田块数", "trait_inherit": "特性继承",
                    "greenhouse": {"_label": "温室", "copy_cost": {"_label": "复制消耗",
                                                                   "coins": "金币",
                                                                   "gem": "宝石"},
                                   "copy_slot": "复制槽位",
                                   "unlock_tier": "解锁档位"}},
    },
    "forge": {"forge_fee": "锻造费", "synth_ratio_3to1": "三合一合成比例",
              "straight_forge": "直接锻造", "decompose_rate": "分解回收率",
              "exp_per_forge": "每次锻造经验", "sets_enabled": "启用套装",
              "augments_enabled": "启用客制强化", "set_piece_counts": "套装部件数",
              "set_tier_exact": "套装档位精确匹配"},
    "fishing": {
        "mode": "模式", "bait_ids": "鱼饵引用", "daily_limit": "每日上限",
        "wait_sec": {"_label": "等待秒数", "min": "最小等待秒数", "max": "最大等待秒数"},
        "energy": {"_label": "精力", "enabled": "启用精力"},
        "bait_bonus": {"_label": "鱼饵加成", "gold": "金色鱼饵加成", "rare": "稀有鱼饵加成"},
        "rod_full_bonus": {"_label": "满竿加成", "gold": "金色满竿加成",
                           "rare": "稀有满竿加成"},
        "crown_thresholds": {"_label": "冠级阈值", "reverse": "倒扣阈值",
                             "silver": "银冠阈值", "gold": "金冠阈值"},
        "king_event": {"_label": "鱼王事件", "enabled": "启用鱼王事件",
                       "window_daily": "每日窗口", "chance": "概率"},
    },
    "assistant": {
        "enabled": "启用", "energy_items": "精力道具", "unlock_tier": "解锁档位",
        "helpers": _soft_list("助手列表", {
            "id": "标识", "name": "名称", "desc": "说明", "tier": "档位",
            "gather_rate": "采集速率", "quality_bonus": "品质加成",
            "trait_bonus": "特性加成"}),
        "queue": {"_label": "队列", "max_slots": "最大槽位", "tick_sec": "结算秒数"},
    },
    # battle 段 = 战斗数值动态化（M12.5 战斗数值方案）实测键并集；命名取引擎既有术语
    "battle": {
        "enrage_damage_mult": "狂暴伤害倍率", "enrage_recovery_mult": "狂暴恢复倍率",
        "fatigue_recovery_mult": "疲劳恢复倍率",
        "fatigue_stagger_chance": "疲劳踉跄概率",
        "rage_cool_actions": "怒气冷却行动数", "rage_per_damage": "每次受伤怒气",
        "roar_combo_clear": "咆哮清连段", "roar_heavy_delay": "重咆哮延迟",
        "roar_light_delay": "轻咆哮延迟", "stamina_drain_blunt": "打击精力消耗",
        "stamina_max": "精力上限", "stamina_regen_per_action": "每行动精力恢复",
        "stun_back_mult": "气绝反制倍率", "stun_base_threshold": "气绝基础阈值",
        "stun_decay_per_action": "每行动气绝衰减", "stun_escalation": "气绝递增",
        "stun_hint_at": "气绝提示阈值", "stun_ko_skip": "气绝跳过回合",
        "stun_ko_window": "气绝窗口", "stun_side_mult": "方位气绝倍率",
    },
    "command_aliases": {},
    "contest": {
        "enabled": "启用",
        "reward": {"_label": "奖励", "gem": "宝石", "title": "称号",
                   "reputation": {"_label": "声望", "submit": "提交", "win": "获胜"}},
        # 注：contest 下的排期子段键名（含 M43① 零定时器扫描词）不在本表登记，
        # 保留原始键显示并列入批报「待确认清单」（不猜中文名，避免触发全仓定时器门禁）。
        "score_weights": {"_label": "评分权重", "awaken": "觉醒", "potential": "潜力",
                          "quality": "品质", "trait": "特性"},
    },
    "ctb": {"enabled": "启用", "default_recovery": "默认行动恢复"},
    "events": {},
    "exp_curve": {},
    "level_cap": "等级上限",
    "quest_board": {
        "enabled": "启用", "refresh_days": "刷新天数", "penalty": "惩罚",
        "active_limit": "同时接取上限", "daily_limit": "每日上限",
        "rep_levels": "声望等级", "grade_bonus": {"_label": "评级加成",
                                                "S": "S 级", "A": "A 级", "B": "B 级"},
        "tiers": _soft_list("任务板档位", {
            "id": "标识", "name": "名称", "desc": "说明",
            "job_level": "职业等级", "rep_base": "基础声望", "rep_min": "最低声望",
            "star": "星级", "reward": "奖励",
            "require": {"_label": "需求", "count": "数量", "item": "物品",
                        "quality": "品质"}}),
    },
}

# ---- forge / fishing / enhance（深结构展示层；宽容器 soft_label 语义保持）----
FORGE_CHILD_LABELS: Dict[str, Any] = {
    "trees": {
        "id": "标识", "name": "名称", "type": "类型", "roots": "根节点",
        "nodes": {"id": "标识", "name": "名称", "item": "物品", "output_item": "产出物品",
                  "type": "类型", "level": "等级", "parent": "前置节点", "branch": "分支",
                  "stats": "属性", "slots": {"level": "等级"},
                  "materials": {"item": "物品", "count": "数量", "tier": "档位",
                                "source_override": "来源覆盖"},
                  "cost": {}, "rarity": "稀有度", "monster_source": "怪物来源",
                  "final": "终点", "augmentable": "可强化", "king_only": "王级专属",
                  "final_tier": "终段"},
    },
    "sets": {
        "id": "标识", "name": "名称", "variant": "变体", "pieces": "部件",
        "skills": {"piece_count": "部件数", "skill": "技能", "level": "等级",
                   "effect_ref": "效果引用"},
        "desc": "说明", "enabled": "启用", "codex_group": "图鉴分组",
    },
    "augments": {
        "augments": {"id": "标识", "name": "名称", "kind": "类别", "effect": "效果",
                     "stat_key": "属性键", "value": "数值",
                     "cost": {"item": "物品", "count": "数量"},
                     "repeatable": "可重复", "max_repeat": "最大次数",
                     "slot_level": "槽位等级", "disabled": "禁用", "trace": "追溯"},
        "limit_by_rarity": {"quality": "品质", "times": "次数", "final_only": "仅终段"},
    },
    "settings": {},
}
FISHING_CHILD_LABELS: Dict[str, Any] = {
    "species": {
        "id": "标识", "name": "名称", "rarity": "稀有度", "king": "鱼王",
        "hours": "出没钟点", "periods": "时段", "seasons": "季节", "spots": "钓点",
        "preferred_bait": "偏好鱼饵", "size_min": "最小尺寸", "size_max": "最大尺寸",
        "weight_min": "最小重量", "weight_max": "最大重量",
        "codex_text": {"best_mask": "最佳尺寸掩码", "desc": "说明", "unit": "单位"},
    },
    "king": {"id": "标识", "enabled": "启用", "chance": "概率", "hint": "提示",
             "enemy_id": "怪物引用", "species_id": "鱼种引用", "window_daily": "每日窗口"},
}
ENHANCE_CHILD_LABELS: Dict[str, Any] = {
    "cost": {"coin_per_level": "每级金币", "stones_per_level": "每级石头",
             "stone_tiers": {"item": "物品", "levels": "等级区间", "tier": "档位"}},
    "settings": {
        "fail_tier_split": "失败档位拆分", "level_gated": "等级门槛",
        "luck_affects": "幸运影响", "shatter_mode": "碎裂模式",
        "transfer_allowed": "允许转移",
        "max_by_rarity": {"normal": "普通", "fine": "精良", "epic": "史诗",
                          "legendary": "传说"},
    },
    "success_curve": {"rate": "成功率", "to": "目标等级"},
    "values": {
        "weapon_atk_per_level": {"stat_key": "属性键", "type": "类型", "value": "数值"},
        "armor_def_per_level": {"stat_key": "属性键", "type": "类型", "value": "数值"},
    },
}

# ---- 尚未覆盖模块的**顶层**字段中文名（与既有 *_FIELD_LABELS 同款）----
MANIFEST_FIELD_LABELS: Dict[str, str] = {
    "name": "内容包名", "version": "版本", "schema_version": "结构版本", "author": "作者",
    "modules": "模块清单", "module_tree": "模块层级声明",
    "module_groups": "模块层级声明（别名）", "module_labels": "模块显示名",
}
TRAITS_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "type": "类型", "probability": "概率",
    "max_stack": "最大层数", "effects": "效果列表", "require_status": "需求状态",
    "apply_status": "施加状态", "rarity": "稀有度", "group": "互斥组",
    "repeatable": "可重复继承", "source": "可继承池分类",
}
RECIPE_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "name": "名称", "kind": "配方类别", "level": "准入等级",
    "synth_allowed": "允许合成", "master_only": "大师独占", "materials": "材料",
    "inputs": "投入材料", "output": "产出", "cost": "消耗", "slots": "槽位数",
    "element_req": "元素需求", "effects": "效果列表", "traits_inherit": "可继承特性数",
    "catalyst": "触媒", "combine_from": "合成来源", "evolve_to": "进化线",
    "pp_budget": "熟练点预算",
}
PROFICIENCY_FIELD_LABELS: Dict[str, str] = {
    "id": "标识", "tier_names": "档位名称", "job_rank_levels": "职业等级门槛",
    "exp_sources": "经验来源", "sp_per_level": "每级技能点", "sp_panel": "技能面板",
    "energy": "精力", "job_tier_map": "职业档位映射", "titles": "称号",
}
SLOTS_FIELD_LABELS: Dict[str, str] = {
    "equip_id": "装备引用", "slots": "插槽",
}
STATS_FIELD_LABELS: Dict[str, str] = {
    "name": "名称", "type": "属性类型", "base": "基础值", "growth": "成长值",
    "max": "上限", "min": "下限", "display": "显示方式",
}
SETTINGS_FIELD_LABELS: Dict[str, str] = {
    "default_map": "默认地图", "world_name": "世界名称", "currencies": "货币",
    "death_penalty": "死亡惩罚", "slot_defs": "装备槽位", "alchemy": "炼金",
    "forge": "锻造", "fishing": "钓鱼", "env_event": "环境事件", "log_card": "日志卡片",
}
CONDITIONAL_FIELD_LABELS: Dict[str, str] = {"conditional": "条件加成"}


# =====================================================================================
# 编辑器重写批4.6：字段**说明**元数据（说明卡「人工补充」部分；只补 FieldMeta.help）
# =====================================================================================
# 口径（与 *_FIELD_LABELS 同款，只加展示维度）：
#   · 只写**有依据**的高频/易错字段：依据 = stats.json / docs/m2_shared_contract /
#     docs/m3_shared_contract / docs/m13_6a~6c / docs/m8_shared_contract / 各字段定义处注释；
#     无依据的字段**不瞎写**，缺省（无 help）时编辑器只用自动拼装内容，不报错；
#   · 一句话说明「这个字段干什么、填多少、是数值还是比例」；用词遵循需求 §六 术语表
#     （mp 法力 / con 体质 / mag 法强 / pv 防护值），不造词；
#   · 嵌套字段用 `*_CHILD_HELP`（形态与 *_CHILD_LABELS 平行：str 或
#     {`_help`: 本节点说明, 子键: …}）；说明只作用于**已声明**的子字段，不新增字段节点；
#   · 数值单位走 FieldMeta.unit（定义处直接声明），说明卡自动拼装时据此判定「数值 / 比例」。
# 覆盖模块：skills / enemies / items / equipment / effects / statuses / marks /
#           skill_chains / action / settings（本批必做 10 个）。
SKILLS_FIELD_HELP: Dict[str, str] = {
    "id": "技能的唯一标识；派生链、反击技、怪物技能表都用它引用这个技能。",
    "name": "技能显示名，出现在技能卡、战报与列表中。",
    "kind": "技能类别：damage 伤害 / heal 治疗 / status 状态 / control 控制 / utility 功能。",
    "type": "技能时机：basic 普攻 / active 主动 / passive 被动 / trigger 触发。",
    "attack_type": "攻击类型（斩 / 打 / 突 / 魔 / 无）；留空表示按武器决定。",
    "element": "技能元素（八元素之一）；留空或 null 表示按武器元素。",
    "tag": "连段标签：none 连段外 / combo 可接 / combo_preserve 保持连段 / "
           "combo_push 推进连段 / interrupt 打断 / armor 霸体。",
    "armor": "开启后发动期间霸体，不被打断。",
    "interrupt": "开启后该技能命中可打断对方行动。",
    "position_rule": "方位命中规则：从哪个方位打才命中、有没有方位加成；由方位系统判定。",
    "air_policy": "对空中目标的处理策略（能否命中、是否击落等）。",
    "block_mode": "格挡模式：auto 按默认规则 / normal 正常被格挡 / ignore 无视格挡。",
    "power": "技能倍率，按百分比算（100 = 一倍威力；常见 10~500）。",
    "break_power": "破坏力固有值，参与部位破坏计算（建议 0~500）。",
    "mp_cost": "每次施放消耗的法力点数；普攻通常为 0。",
    "cooldown": "施放后的冷却回合数；0 表示无冷却。",
    "hits": "一段行动内独立结算的段数；1 表示只打一下。",
    "hit_mod": "命中率乘数修正（1 = 不变；大于 1 更容易命中）。",
    "crit_mod": "会心判定乘数修正（1 = 不变；大于 1 更容易会心）。",
    "action_time": "发动后占据的行动条时长（反应窗口）；缺省取 ctb 默认值。",
    "air_extend": "跃空窗口延长的行动条数量；缺省取 ctb 配置。",
    "recovery": "行动结束后的行动条恢复量；缺省取 ctb.default_recovery。",
    "stun": "命中积累的气绝值；气绝满会使目标硬直。",
    "trigger_limit": "触发上限：per_round 每回合最多几次 / per_battle 每场最多几次；0 = 不限。",
    "level": "升级配置：max 最高等级 / growth 每级倍率列表；留空表示该技能不升级。",
    "effects": "技能附加效果：可引用已有效果（effect），也可写原子动作（type/…）；可留空。",
    "chain_refs": "本技能可转入的派生链引用（skill_chains 的标识）。",
    "consume_marks": "施放时消耗的印记与层数，形如 {印记标识: 层数}；留空表示不消耗。",
    "job_restrict": "允许使用本技能的职业列表；留空表示所有职业可用。",
    "job_form": "形态技绑定的形态名（对应职业 transform 的目标形态）；留空 = 非形态技。",
    "counter_type": "防反 / 闪反姿态标记：parry 防反 / dodge 闪反。",
    "counter_skill": "姿态成功时派生反击的技能标识。",
    "revert_form": "还原技标记：处于形态时用它切回原形态。",
    "derive_only": "开启后该技能只能由派生链进入，不直接出现在可用技能列表里。",
    "energy_gain": "资源轴（能量）的增减配置；键为资源轴名、值为增减量。",
    "energy_cost": "资源轴（能量）的消耗配置；键为资源轴名、值为消耗量。",
    "season": "季节技能组：只在指定季节可用。",
    "combo_table": "组合表达表：按条件切换不同效果行的配置。",
    "skill": "旧格式的技能引用（兼容旧内容包）；新内容请用 chain_refs。",
    "desc": "一句话说明，显示在技能卡、战报与悬浮说明里。",
    "brief": "简述：可自由写标签文字，也可留空（留空 = 列表里不显示简述行）。",
    "detail": "详情长文本，编辑器里用大输入框填写。",
}
SKILLS_CHILD_HELP: Dict[str, Any] = {
    "level": {"max": "技能最高等级（1~99）。",
              "growth": "每级倍率列表，长度应与最高等级一致。",
              "_help": "技能的升级配置。"},
    "trigger_limit": {"per_round": "每回合最多触发次数；0 = 不限。",
                      "per_battle": "每场战斗最多触发次数；0 = 不限。",
                      "_help": "技能触发的次数上限。"},
    "effects": {"type": "原子动作类型（damage / mark_add / status_add…）。",
                "effect": "引用的效果标识（effects 注册表）。",
                "target": "效果作用对象（self 自身 / enemy 敌方）。",
                "count": "施加层数或数量。",
                "pct": "数值是否按百分比解释。",
                "mark": "关联的印记标识。",
                "status_id": "关联的状态标识。",
                "marks_on": "需要目标身上已有的印记。",
                "polarity": "效果极性（正面 / 负面）。",
                "overrides": "对引用效果的数值覆盖。",
                "_help": "技能附加效果的一条（引用效果或原子动作）。"},
    "consume_marks": {"_help": "施放消耗的 {印记标识: 层数} 表。"},
}

ENEMIES_FIELD_HELP: Dict[str, str] = {
    "id": "怪物唯一标识；地图刷怪、掉落与 AI 都用它引用。",
    "name": "怪物显示名。",
    "tier": "怪物档位：normal 普通 / elite 精英 / boss 首领 / training 训练木桩。",
    "type": "怪物类型标记（dummy = 训练木桩）；旧包的 type:monster 仍兼容。",
    "area": "所属区域名（用于图鉴/叙事分组，不决定刷怪地图）。",
    "desc": "图鉴里的一句话说明。",
    "stats": "怪物九属性基础值（生命/法力/力量/智力/体质/精神/专注/敏捷/幸运）；"
             "留空的属性按默认值处理。",
    "weakness": "弱点：types 弱点类型 / elements 弱点元素；命中弱点有额外收益。",
    "resistance": "抗性：immune 免疫的效果 / stun 气绝抗性。",
    "pv": "防护值（0~500）：击破前本体减伤；训练木桩强制为 0。",
    "pv_recover": "防护值恢复时机：battle_end 战斗结束时回满 / none 不恢复。",
    "def_base": "基础防御值（木桩向字段）。",
    "elem_res": "元素抗性表：元素标识 → 正数减伤 / 负数增伤。",
    "hp": "旧格式的生命值，保留兼容旧内容包；新内容请写在 stats 段里。",
    "atk": "旧格式的攻击值，保留兼容旧内容包；新内容请写在 stats 段里。",
    "def": "旧格式的防御值，保留兼容旧内容包；新内容请写在 stats 段里。",
    "monster_def_rate": "怪物防御率：1.0 = 与玩家同档；越高越抗打，可填负数（运行时按 0 兜底）。",
    "drop_rate": "掉落率系数（0~1 的比例，按百分比表示），作为掉落表的整体调整值。",
    "actions": "普通行动表：每项包含行动引用、权重、概率、条件与冷却。",
    "special_actions": "特殊行动表：条件触发型行动（触发类型/阈值/时机/触发后状态等）。",
    "chains": "连招表：一段行动后按概率衔接的后续行动。",
    "drops": "掉落表：battle 战斗掉落 / special 特殊掉落 / death 死亡掉落。",
    "lore": "图鉴条目：解锁进度与说明文字。",
    "effects": "怪物自带效果列表（引用效果注册表）。",
    "traits": "怪物特性列表（引用特性注册表）。",
    "skills": "怪物技能表（技能标识列表）。",
    "parts": "部位破坏表：每个部位的破坏阈值、可达方位、命中优先级与破位行为。",
    "ai": "AI 行为配置：状态机与状态转移条件。",
    "phases": "阶段表：按血量阈值切换行动与播报。",
    "rewards": "讨伐奖励（经验等）。",
    "zone_change": "换区行为：残血到阈值时切换目标怪物。",
}
ENEMIES_CHILD_HELP: Dict[str, Any] = {
    "stats": {"hp": "生命基础值。", "mp": "法力基础值。", "str": "力量基础值。",
              "int": "智力基础值。", "con": "体质基础值。", "spr": "精神基础值。",
              "foc": "专注基础值。", "agi": "敏捷基础值。", "luk": "幸运基础值。"},
    "weakness": {"types": "弱点类型列表。", "elements": "弱点元素列表。"},
    "resistance": {"immune": "免疫的效果列表。", "stun": "气绝抗性。"},
    "actions": {"action": "行动引用（action 注册表）。", "probability": "选择概率（0~1 的比例）。",
                "weight": "入池权重：越大越容易被选到。", "condition": "选择条件。",
                "cooldown": "该行动的冷却回合数。", "hungry": "饥饿值消耗。"},
    "special_actions": {
        "id": "特殊行动标识。", "action": "引用的行动。", "once": "是否整场只触发一次。",
        "priority": "多个特殊行动的判定优先级。", "trigger_cooldown": "触发冷却回合数。",
        "max_triggers": "最多触发次数。", "chain_ref": "触发的连招引用。", "desc": "说明文字。",
        "trigger": {"type": "触发类型。", "value": "触发阈值。", "timing": "判定时机。",
                    "action": "参照的行动。", "chance": "触发概率（0~1 的比例）。",
                    "which": "作用对象。", "side": "方位条件。", "height": "高度条件。",
                    "mark": "参照的印记。", "min": "印记最少层数。", "absent": "是否需要印记不存在。"},
        "post_state": {"state": "触发后进入的状态。", "turns": "状态持续回合数。"},
    },
    "chains": {"id": "连招标识。",
               "actions": {"action": "衔接的行动。", "chance": "衔接概率（0~1 的比例）。",
                           "role": "衔接角色。", "armor": "衔接期间是否霸体。"}},
    "drops": {"battle": {"_help": "战斗胜利掉落。", "item": "掉落物品。",
                         "chance": "掉落概率（0~1 的比例）。", "condition": "掉落条件。",
                         "count": "掉落数量或数量区间。"},
              "special": {"_help": "特殊掉落。", "item": "掉落物品。",
                          "chance": "掉落概率（0~1 的比例）。", "condition": "掉落条件。",
                          "count": "掉落数量或数量区间。"},
              "death": {"_help": "死亡掉落。", "item": "掉落物品。",
                        "chance": "掉落概率（0~1 的比例）。", "condition": "掉落条件。",
                        "count": "掉落数量或数量区间。"}},
    "lore": {"unlock": "图鉴解锁进度。", "desc": "图鉴说明文字。"},
    "parts": {"id": "部位标识。", "name": "部位名。", "break_threshold": "破坏阈值（建议 0~99999）。",
              "target_priority": "被命中优先级。",
              "positions": {"side": "可达方位。", "height": "可达高度。"},
              "on_break": {"knockdown": "破位后倒地时长（次行动）。", "marks": "破位施加的印记。",
                           "effects": "破位触发的效果。"},
              "_help": "怪物可破坏部位的一条。"},
    "ai": {"transitions": {"from": "源状态。", "to": "目标状态。", "condition": "切换条件。",
                           "_help": "AI 状态转移的一条。"}},
    "phases": {"threshold": "进入本阶段的血量阈值。", "enter_action": "进入阶段时执行的行动。",
               "broadcast": "进入阶段时的播报文案。",
               "actions": {"action": "阶段内的行动。", "weight": "入池权重。",
                           "probability": "选择概率（0~1 的比例）。", "_help": "阶段行动表。"},
               "_help": "怪物阶段表的一条。"},
    "rewards": {"exp": "讨伐获得的经验值。"},
    "zone_change": {"enabled": "是否启用换区。", "hp_threshold": "触发换区的残血阈值。",
                    "targets": "换区目标怪物。", "timing": "切换时机。"},
}

ITEMS_FIELD_HELP: Dict[str, str] = {
    "id": "物品唯一标识；商店、掉落、配方都用它引用。",
    "name": "物品显示名。",
    "type": "物品类别（武器 / 防具 / 消耗品 / 素材…）；装备类物品会进入装备模块。",
    "slot": "装备部位（如 weapon / armor）；普通物品留空。",
    "bind": "开启后装备或使用即绑定。",
    "usable": "开启后可以在背包里直接使用。",
    "quality": "品质档：common 普通 / uncommon 精良 / rare 史诗 / legendary 传说。",
    "rarity": "素材稀有度：普通 / 稀有 / 金色。",
    "material_tier": "素材档位（锻造与炼金使用）。",
    "price": "基础售价（以默认货币计的数量）。",
    "atk": "攻击加成（白值，单位：点）。",
    "def": "防御加成（旧键，单位：点）；现行键请用 dfn。",
    "dfn": "防御加成（白值，单位：点）。",
    "foc": "专注加成（白值，单位：点）。",
    "hp": "生命加成（白值，单位：点）。",
    "agi": "敏捷加成（白值，单位：点）。",
    "elements": "元素属性值：八元素（地/水/火/风/雷/晶/月/无）的投料累计值。",
    "base_effects": "基础效果（固定数值，引用效果注册表）；标准珠只有这一套。",
    "effects": "附加效果列表（引用效果注册表）。",
    "traits": "特性列表（引用特性注册表）。",
    "awaken": "觉醒标记：开启表示可作为觉醒素材。",
    "seed": "种植标记：开启或写收获表表示可种植。",
    "source": "来源说明（掉落 / 商店 / 合成等）。",
    "desc": "说明文字。",
}
# 装备词条键（GEAR_*）说明按注册表口径批量生成（唯一源 = data/gear_stats.py：
# FLAT=白值加算、PCT=百分点、COMBAT=战斗直读），不手写、不造词。
for _k in GEAR_FLAT_KEYS:
    ITEMS_FIELD_HELP.setdefault(_k, "属性加成（白值加算，单位：点）。")
for _k in GEAR_PCT_KEYS:
    ITEMS_FIELD_HELP.setdefault(_k, "百分比加成（单位：百分点，5 = +5%）。")
ITEMS_FIELD_HELP.setdefault("crit", "会心加成（百分点，可填负数；战斗直读）。")
ITEMS_FIELD_HELP.setdefault("earplug", "耳栓等级（上限 2；用于反制咆哮）。")
ITEMS_FIELD_HELP.setdefault("super_crit_lv", "超会心等级（上限 3）。")
ITEMS_FIELD_HELP.setdefault("elem_crit_lv", "属性会心等级（上限 3）。")
EQUIPMENT_FIELD_HELP: Dict[str, str] = dict(ITEMS_FIELD_HELP)
EQUIPMENT_FIELD_HELP["excludes"] = "互斥部位：装备这些部位时不能同时装备本件（成环会被校验拦下）。"
ITEMS_CHILD_HELP: Dict[str, Any] = {
    "elements": {el: f"{el}元素累计值。" for el in ALCHEMY_ELEMENTS},
}

EFFECTS_FIELD_HELP: Dict[str, str] = {
    "id": "效果唯一标识；技能与状态用它引用这个效果。",
    "name": "效果显示名。",
    "type": "效果类别：damage 伤害 / heal 治疗 / status 状态 / control 控制 / utility 功能等。",
    "power": "效果强度数值（伤害量、治疗量或加成量，含义随类型而定）。",
    "duration": "效果持续回合数；0 或留空表示即时生效或不限制。",
    "probability": "触发概率（0~1 的比例，按百分比表示）。",
    "max_stack": "最大叠加层数；0 = 不限。",
    "require_status": "生效需要目标已有的状态（引用状态注册表）。",
    "apply_status": "命中后施加的状态（引用状态注册表）。",
    "require_mark": "生效需要目标已有的印记（引用印记注册表）。",
    "apply_mark": "命中后施加的印记（引用印记注册表）。",
    "patch": "数值补丁：target 目标属性 / value 数值 / pct 是否按百分比。",
    "actions": "效果附属行动表。",
    "class": "效果分类。",
    "control_type": "控制类型（眩晕 / 沉默 / 击退等）。",
    "count": "层数或次数。",
    "desc": "说明文字。",
    "filter": "效果的筛选条件。",
    "mark": "关联的印记标识。",
    "marks_on": "需要目标身上已有的印记。",
    "part_break_per_tick": "每个回合积累的部位破坏值。",
    "pct": "数值是否按百分比解释。",
    "polarity": "效果极性（正面 / 负面）。",
    "skip_turn": "是否让目标跳过回合。",
    "stat": "作用的属性标识。",
    "status": "关联的状态标识。",
    "target": "作用对象（self 自身 / enemy 敌方）。",
    "tick": "效果的触发时点（每回合 / 进入时 / 失效时）。",
    "trigger": "触发条件。",
    "turns": "持续回合数。",
    "value": "数值。",
}
EFFECTS_CHILD_HELP: Dict[str, Any] = {
    "patch": {"target": "要修改的属性。", "value": "修改数值。", "pct": "是否按百分比修改。"},
    "actions": {"type": "原子动作类型。", "count": "层数或数量。", "mark": "关联的印记。",
                "target": "作用对象。"},
}

STATUSES_FIELD_HELP: Dict[str, str] = {
    "id": "状态唯一标识；技能和效果用它引用这个状态。",
    "name": "状态显示名。",
    "type": "状态类别。",
    "max_stack": "最大叠加层数；0 = 不限。",
    "duration": "持续配置：turns 持续回合数 / charges 可消耗次数；-1 = 该维永不自然结束（引擎哨兵）。",
    "decay": "衰减方式（如 per_turn 每回合递减）。",
    "effects": "状态附带的效果列表。",
    "on_enter": "进入状态时触发的效果引用。",
    "on_tick": "每回合结算时触发的效果引用。",
    "on_expire": "状态失效时触发的效果引用。",
    "damage_mult": "受击增伤倍率（例如破位/倒地时提高受到的伤害）。",
    "desc": "说明文字。",
    "description": "描述文字（旧键，兼容旧内容包）。",
    "on_dodge_effects": "闪避成功时触发的效果列表。",
}
STATUSES_CHILD_HELP: Dict[str, Any] = {
    "duration": {"turns": "持续回合数（-1 = 该维永不自然结束）。",
                 "charges": "可消耗次数（-1 = 该维永不自然结束）。",
                 "_help": "状态的持续配置。"},
}

MARKS_FIELD_HELP: Dict[str, str] = {
    "id": "印记唯一标识；技能和效果用它引用这个印记。",
    "name": "印记显示名。",
    "icon": "印记图标。",
    "type": "固定为 mark（印记）。",
    "max_stack": "最大层数；0 = 不限。",
    "appliable_to": "可施加对象，取 self（自身）/ enemy（敌方）的子集。",
    "polarity": "极性：positive 正面 / negative 负面。",
    "element": "可选元素引用（八元素之一）；留空表示无元素。",
    "duration": "持续写「battle」= 整场战斗 /「turns:N」= 持续 N 回合。",
    "probability": "施加概率（0~1 的比例，按百分比表示）。",
    "desc": "说明文字。",
    "description": "描述文字（旧键，兼容旧内容包）。",
}

SKILL_CHAINS_FIELD_HELP: Dict[str, str] = {
    "id": "派生链唯一标识；技能的 chain_refs 用它引用。",
    "name": "派生链显示名。",
    "type": "派生链类别。",
    "next": "链上的后继节点标识列表；互相成环会被校验拦下。",
    "actions": "链节点引用的行动（action 注册表）。",
    "effects": "链上的效果列表（引用效果注册表）。",
    "max_combo": "最大连段数。",
    "max_combo_behavior": "达到满连段后的行为（继续 / 中断等）。",
    "steps": "派生步骤：from 源技能 → to 目标技能；可带触发条件、优先级、消耗与数值覆盖。",
    "trigger_skill": "触发这条派生链的技能标识。",
}
SKILL_CHAINS_CHILD_HELP: Dict[str, Any] = {
    "steps": {"from": "源技能标识。", "to": "目标技能标识。", "tag": "步骤标签。",
              "priority": "多个步骤的判定优先级。", "mode": "派生模式。",
              "armor": "派生期间是否霸体。", "consume": "派生消耗。",
              "condition": {"count": "触发所需的计数。", "_help": "触发条件。"},
              "variant_override": {"power": "覆盖后的威力。", "_help": "数值覆盖。"},
              "_help": "派生链的一个步骤。"},
}

ACTION_FIELD_HELP: Dict[str, str] = {
    "id": "行动唯一标识；怪物行动表、连招与技能都用它引用。",
    "name": "行动显示名。",
    "kind": "行动类别：basic 基础 / active 主动 / …（按行动库约定）。",
    "type": "行动类型（旧键，兼容旧内容包）。",
    "position_rule": "方位命中规则：从哪个方位打才命中、有没有方位加成。",
    "break_power": "破坏力固有值，参与部位破坏计算（建议 0~500）。",
    "air_policy": "对空中目标的处理策略（能否命中、是否击落等）。",
    "air_drop": "对空击落规则（如 knockdown = 击中空中目标即击落）。",
    "power": "行动威力。",
    "attack_type": "攻击类型（斩 / 打 / 突 / 魔 / 无）。",
    "element": "元素标识（八元素之一）。",
    "effects": "行动附带的效果列表。",
    "cost": "消耗（旧键）；现行请用技能的 mp_cost。",
    "cool": "冷却（旧键）；现行请用 cooldown。",
    "weight": "入池权重：越大越容易被选到。",
    "probability": "入池开关/概率（0~1 的比例）：0 = 不选，1 = 必选。",
    "intent": "意图类型（伤害 / 防御 / 蓄力 / 治疗 / 控制 / buff / debuff / 印记 / 功能），用于意图预告。",
    "roar": "咆哮等级：1 轻 / 2 大；对应耳栓反制。",
    "cooldown": "行动冷却回合数；0 表示无冷却。",
    "recovery": "行动结束后的行动条恢复量。",
    "hungry": "饥饿值消耗。",
    "chain": "连锁行动：后续衔接的行动标识列表（旧写法）。",
    "armor": "开启后发动期间霸体，不被打断。",
    "interrupt": "开启后命中可打断对方行动。",
    "tags": "行动标签列表。",
    "preview": "意图预告的内容。",
    "preview_chain": "链预告的内容。",
    "reveal_condition": "预告在什么条件下揭示。",
    "require_status": "发动需要自身已有的状态。",
    "apply_status": "命中后施加的状态。",
    "skill": "关联的技能引用（可指向任意技能）。",
    "apply_mark": "命中后施加的印记。",
    "condition": "触发/选择条件（对象或字符串，深结构由专项校验）。",
    "trigger_limit": "触发上限配置。",
    "charge_armor": "蓄力期间是否霸体。",
    "charge_turns": "蓄力回合数。",
}

SETTINGS_FIELD_HELP: Dict[str, str] = {
    "default_map": "新存档默认进入的地图标识。",
    "world_name": "世界/服务器显示名。",
    "currencies": "货币定义表：每种货币的标识、名称、图标与上限。",
    "death_penalty": "死亡惩罚：虚弱时长与掉落货币/经验/物品的比例。",
    "slot_defs": "装备部位定义表：键为部位标识，值为名称、最大件数与占用关系。",
    "alchemy": "炼金段：模式、品质档位、精力、宝石分解/复制、战斗调合等全局参数。",
    "forge": "锻造段：费用、合成比例、分解回收率、套装开关与套装部件数。",
    "fishing": "钓鱼段：鱼种、鱼王、钓点、鱼饵与尺寸/重量区间。",
    "env_event": "环境事件段。",
    "log_card": "日志卡片文案段。",
    "assistant": "助手段配置。",
    "battle": "战斗参数段。",
    "command_aliases": "指令别名表。",
    "contest": "竞技段配置（排期等）。",
    "ctb": "行动条（CTB）参数：时间尺度、默认行动时间与恢复值等。",
    "events": "事件文案段。",
    "exp_curve": "经验曲线：等级 → 升级所需经验。",
    "level_cap": "等级上限。",
    "quest_board": "任务板段。",
}


def _decorate_module_meta(mmeta: ModuleMeta, labels: Mapping[str, str] = (),
                          child_labels: Optional[Mapping[str, Any]] = None,
                          helps: Optional[Mapping[str, str]] = None,
                          child_helps: Optional[Mapping[str, Any]] = None) -> ModuleMeta:
    """模块 ModuleMeta 的 fields 过一遍展示层装饰（helper 工厂模块用；校验语义零变化）。"""
    return replace(mmeta, fields=_decorate_field_meta(
        mmeta.fields, mmeta.field_groups, labels, child_labels, helps, child_helps))


def _group_declaration(
    defs: Tuple[Tuple[str, Tuple[str, ...]], ...],
    labels: Mapping[str, str],
) -> Tuple[Dict[str, str], Tuple[str, ...], Dict[str, str]]:
    """(分组键→组, 分组顺序, 组→显示名) 三元组；供 ModuleMeta 直接挂载。"""
    groups: Dict[str, str] = {}
    order: Tuple[str, ...] = ()
    for group, keys in defs:
        order = order + (group,)
        for key in keys:
            groups.setdefault(key, group)
    return groups, order, dict(labels)


ENEMIES_FIELD_GROUPS, ENEMIES_GROUP_ORDER, ENEMIES_GROUP_LABEL_MAP = \
    _group_declaration(ENEMIES_GROUP_DEFS, ENEMIES_GROUP_LABELS)
ITEMS_FIELD_GROUPS, ITEMS_GROUP_ORDER, ITEMS_GROUP_LABEL_MAP = \
    _group_declaration(ITEMS_GROUP_DEFS, ITEMS_GROUP_LABELS)
MAPS_FIELD_GROUPS, MAPS_GROUP_ORDER, MAPS_GROUP_LABEL_MAP = \
    _group_declaration(MAPS_GROUP_DEFS, MAPS_GROUP_LABELS)
QUEST_FIELD_GROUPS, QUEST_GROUP_ORDER, QUEST_GROUP_LABEL_MAP = \
    _group_declaration(QUEST_GROUP_DEFS, QUEST_GROUP_LABELS)


def _decorate_field_meta(
    fields: Mapping[str, FieldMeta],
    groups: Mapping[str, str],
    labels: Mapping[str, str],
    child_labels: Optional[Mapping[str, Any]] = None,
    helps: Optional[Mapping[str, str]] = None,
    child_helps: Optional[Mapping[str, Any]] = None,
) -> Dict[str, FieldMeta]:
    """把模块级分组表/中文名表/说明表叠加到字段元数据（字段自带的 group/label/help 优先）。

    只做展示层补充：type/required/default/enum/ref_target/element/children 原样保留，
    因此对泛型校验器（只读 type 等判定字段）是零行为变化。
    批4.5 起可选 child_labels（嵌套中文名表）递归装饰 children / element.children；
    表里出现、children 未登记的键补 soft_label=True 纯展示子字段（校验短路，语义零变化）。
    批4.6 起可选 helps（模块顶层人工说明）+ child_helps（嵌套人工说明，形态与 child_labels
    平行：str 或 {`_help`: 本节点, 子键: …}）；说明**只补 help 展示维度**，不改任何校验契约，
    缺省（helps 为空 / 字段无说明）时行为与批4.5 完全一致。
    """
    out: Dict[str, FieldMeta] = {}
    helps = helps or {}
    for key, fm in fields.items():
        kw: Dict[str, object] = {}
        if not fm.group and key in groups:
            kw["group"] = groups[key]
        if not fm.label and key in labels:
            kw["label"] = labels[key]
        if not fm.help and key in helps:
            kw["help"] = helps[key]
        spec = child_labels.get(key) if child_labels else None
        help_spec = child_helps.get(key) if child_helps else None
        want_recursive = fm.type in ("obj", "list") and (
            isinstance(spec, Mapping) or isinstance(help_spec, Mapping))
        if want_recursive:
            help_text = help_spec if isinstance(help_spec, str) else None
            nested_helps = help_spec if isinstance(help_spec, Mapping) else None
            new_fm = _decorate_one(
                fm, None, spec if isinstance(spec, Mapping) else None,
                help_text, nested_helps)
            if new_fm.children is not fm.children:
                kw["children"] = new_fm.children
            if new_fm.element is not fm.element:
                kw["element"] = new_fm.element
        out[key] = replace(fm, **kw) if kw else fm
    return out


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
        # 编辑器重写批1：模块层级/显示名（均为可选声明；缺省 → 编辑器平铺显示、用模块键名）。
        # 包用它们声明「物品 ▸ 装备」这类父子关系与中文名，编辑器不写死任何归并关系。
        "module_tree": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                                 soft_label=True, label="模块层级声明"),
        "module_groups": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                                   soft_label=True, label="模块层级声明（module_tree 别名）"),
        "module_labels": FieldMeta(type="obj", children={}, soft_label=True, label="模块显示名"),
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
        # 批4.5：veinborn/test_demo 实有、原表未登记的顶层键 → 纯展示宽字段（soft_label
        # 短路泛型校验；editor 表单/子字段可读，校验语义零变化）
        "actions": _soft_display("行动表", "list"),
        "class": _soft_display("类别"),
        "control_type": _soft_display("控制类型"),
        "count": _soft_display("层数", "int"),
        "desc": _soft_display("说明"),
        "filter": _soft_display("筛选"),
        "mark": _soft_display("印记"),
        "marks_on": _soft_display("所需印记"),
        "part_break_per_tick": _soft_display("每回合破坏值", "int"),
        "pct": _soft_display("百分比", "bool"),
        "polarity": _soft_display("极性"),
        "skip_turn": _soft_display("跳过回合", "number"),
        "stat": _soft_display("属性"),
        "status": _soft_display("状态"),
        "target": _soft_display("目标"),
        "tick": _soft_display("触发时点"),
        "trigger": _soft_display("触发条件"),
        "turns": _soft_display("持续回合", "int"),
        "value": _soft_display("数值"),
    }
    statuses_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "max_stack": F_MAX_STACK,
        # duration 权威形态 = 对象 {turns:int, charges:int}（细化_1b §1.2 字段9/子结构 2a）
        # —— 不再用 F_DURATION(number)，否则合法 {turns,charges} 会被 R-1 误拦
        "duration": FieldMeta(type="obj", children={
            # allow_negative：-1 = 该维「永不被清」引擎哨兵（细化_1b §4.2 D6 口径；
            # 跃空姿态等「行动条窗口管理、不走行动次数递减」的时间型持续用）；负数
            # 仅黄提示（Y-1 越界）不红拦——与 base/growth 负数口径一致。
            "turns": FieldMeta(type="int", range_min=0, range_max=9999,
                               allow_negative=True),
            "charges": FieldMeta(type="int", range_min=0, range_max=9999,
                                 allow_negative=True),
        }),
        "decay": FieldMeta(type="str"),  # 枚举（per_turn…）由正式表注入
        "effects": F_EFFECTS,
        "on_enter": FieldMeta(type="ref", ref_target="effect"),
        "on_tick": FieldMeta(type="ref", ref_target="effect"),
        "on_expire": FieldMeta(type="ref", ref_target="effect"),
        # 受击增伤乘区（方位 v0.6 §五：knockdown 等状态 def 挂 damage_mult；引擎破位乘区消费）
        "damage_mult": FieldMeta(type="number", range_min=0, range_max=10,
                                 label="受击增伤倍率"),
        # 批4.5：实测顶层键（原表未登记 → 纯展示宽字段，soft_label 零校验变化）
        "desc": _soft_display("说明"),
        "description": _soft_display("描述"),
        "on_dodge_effects": _soft_display("闪避时效果", "list"),
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
        "description": _soft_display("描述"),     # 批4.5 实测顶层键（纯展示）
    }
    skill_chains_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        # 链节点引用（skill/action）。M0 无技能库模块，缺省仅结构（成环 R-5）；
        # 正式元数据表注入 ref_target="skill"/"action" 后自动启用 R-4。
        "next": FieldMeta(type="list", element=FieldMeta(type="str")),
        "actions": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="action")),
        "effects": F_EFFECTS,
        # M12.5 批2 路2B（M13 技能链深结构顶层键补登记——实测 skill_chains.json
        # 含 max_combo/max_combo_behavior/steps/trigger_skill（job_scope 归
        # 细化_6b 附·未定稿依赖 1/3，由 6a 路收口——本表不越界登记）；steps
        # 元素 {from,to,tag,condition{mode,count},priority,armor,consume,...}
        # 深结构归 core/combo + 专项校验全权 → 宽 obj 容器防泛型误拦，仅登记
        # 顶层键供编辑器表单渲染（原始 JSON 兜底仍可编深结构））
        "max_combo": FieldMeta(type="int", label="最大连段数"),
        "max_combo_behavior": FieldMeta(type="str", label="满连段行为"),
        "steps": FieldMeta(type="list",
                           element=FieldMeta(type="obj", children={
                               "from": FieldMeta(type="str", label="源技能"),
                               "to": FieldMeta(type="str", label="目标技能"),
                               "tag": FieldMeta(type="str", label="标签"),
                               "condition": FieldMeta(type="obj", children={},
                                                      soft_label=True, label="触发条件"),
                               "priority": FieldMeta(type="int", label="优先级"),
                               "mode": FieldMeta(type="str", label="模式"),
                               "armor": FieldMeta(type="bool", label="霸体"),
                               "consume": FieldMeta(type="int", label="消耗"),
                           }),
                           soft_label=True, label="连段步骤"),
        "trigger_skill": FieldMeta(type="str", label="触发技能"),
    }
    action_fields: Dict[str, FieldMeta] = {
        # ---- ActionCore 基础（T24-T26 / m2_shared_contract §四）----
        "id": F_ID, "name": F_NAME,
        "kind": FieldMeta(type="str"),  # basic/active/...（枚举判定 A2 路）
        "type": F_TYPE,                  # 旧键兼容
        "position_rule": FieldMeta(type="obj"),  # F08 方位命中资格（方位 v0.6 §三.2；枚举校验 A2 路）
        "break_power": FieldMeta(type="number", range_min=0, range_max=500,
                                 label="破坏力固有值"),  # F09（方位 v0.6 §三.4）
        "air_policy": FieldMeta(type="str", label="空中策略"),  # F10（方位 v0.6 §三.6）
        "air_drop": FieldMeta(type="str", label="对空击落"),  # 跃空风险闭环批③（knockdown=击中空中玩家即击落）
        "power": F_POWER,
        "attack_type": FieldMeta(type="str"),  # 斩/打/突/魔（枚举判定 A2 路）
        "element": FieldMeta(type="str"),      # 元素 ID（元素注册表引用检查 A2/M2）
        "effects": F_EFFECTS,
        "cost": FieldMeta(type="number", range_min=0, range_max=9999, unit="点"),  # 旧键
        "cool": FieldMeta(type="number", range_min=0, range_max=9999, unit="回合"),  # 旧键（cooldown 规范名）
        # ---- AI 字段（怪物侧扩展，T26 / m2 §四；缺省兜底不报错）----
        "weight": FieldMeta(type="number", range_min=0, range_max=100),
        # P2-4 修复：不挂 probability 旗标（Y-2 极值误报——0/1 是入池开关非概率值，
        # 与 enemies.actions[].probability 口径一致，1e S1 语义）
        "probability": FieldMeta(type="number", range_min=0, range_max=1),
        "intent": FieldMeta(type="str"),  # 伤害/防御/蓄力/治疗/控制/buff/debuff/印记/功能（枚举 A2）
        "roar": FieldMeta(type="number", range_min=0, range_max=2, unit="级"),  # 批⑦A 咆哮等级（1 轻 / 2 大；耳栓反制）
        "cooldown": FieldMeta(type="number", range_min=0, range_max=999, unit="回合"),
        "recovery": FieldMeta(type="number", range_min=0, unit="行动条"),  # 批⑥ C10 行动恢复值（总恢复值；缺省=ctb.default_recovery）
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
        # 批4.5：实测顶层键（原表未登记 → 纯展示宽字段；soft_label 短路泛型校验，
        # 不新开 ref 校验路径，校验语义零变化）
        "apply_mark": _soft_display("施加印记"),
        "condition": _soft_display("条件", "obj"),
        "trigger_limit": _soft_display("触发上限", "obj"),
        "charge_armor": _soft_display("蓄力霸体", "bool"),
        "charge_turns": _soft_display("蓄力回合", "int"),
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
        "position_rule": FieldMeta(type="obj"),  # F08 方位命中资格（方位 v0.6 §三.2；枚举校验 A2 路）
        "break_power": FieldMeta(type="number", range_min=0, range_max=500,
                                 label="破坏力固有值"),  # F09（方位 v0.6 §三.4）
        "air_policy": FieldMeta(type="str", label="空中策略"),  # F10（方位 v0.6 §三.6）
        "power": F_SKILL_POWER,         # F04 倍率（滑条 10-500%；派生链累计 ≤1.5× 黄提示 V-6 属 A2）
        "attack_type": FieldMeta(type="str"),  # F05 斩/打/突/魔/无（枚举 A2 路；缺省按武器 f4）
        "element": FieldMeta(type="str", soft_label=True),  # F06 8 元素注册表（V-4 引用检查 A2）；null=按武器元素合法
        # F07 effects：条目不登记 element=ref（双形态：引用 {effect,overrides} /
        # 原子动作 {type,...}，§1.3-f2）——V-1 由 skills 专项校验器全权，登记 ref
        # 会被泛型按整条 dict 报 ref_not_str 误拦（补白见上方 skills_fields 注释）
        "effects": FieldMeta(type="list", element=FieldMeta(type="obj")),
        # ---- B 玩家侧扩展 11 字段（F08-F18，细化_6a §1.2-B）----
        "type": FieldMeta(type="str"),   # F08 basic/active/passive/trigger 四类时机（枚举 A2 路）
        "mp_cost": FieldMeta(type="number", range_min=0, range_max=9999, unit="点"),   # F09 ≥0；basic=0
        "cooldown": FieldMeta(type="number", range_min=0, range_max=999, unit="回合"),   # F10 ≥0 整数；basic=0
        "tag": FieldMeta(type="str"),    # F11 none/combo/combo_preserve/combo_push/interrupt/armor（枚举 A2）
        "armor": FieldMeta(type="bool"),         # F12 霸体开关（执行语义快键）
        "interrupt": FieldMeta(type="bool"),     # F13 打断快键（唯一归口 = 效果系统 L0 interrupt，T19）
        "chain_refs": FieldMeta(type="list", element=FieldMeta(type="str")),  # F14 派生链引用 skill_chains.json（V-2）
        "consume_marks": FieldMeta(type="obj"),  # F15 {mark_id: count} 消耗印记（V-3 键存在/上限 A2）
        "job_restrict": FieldMeta(type="list", element=FieldMeta(type="str")),  # F16 职业限制（V-5）
        "job_form": FieldMeta(type="str", soft_label=True),       # F17 形态技（引用 transform 形态名，V-5 扩展判定 A2）；null=非形态技合法
        "level": FieldMeta(type="obj", soft_label=True, children={
            "max": FieldMeta(type="int", range_min=1, range_max=99, unit="级"),
            "growth": FieldMeta(type="list", element=FieldMeta(type="number")),
        }),  # F18 升级 {max, growth}；growth 长度 = max 且 growth[0]=1 级基准（A2 判定）；null=不升级合法
        # ---- C 全库补充 2 字段（F19-F20，细化_6a §1.2-C）----
        "hits": FieldMeta(type="int", range_min=1, range_max=99, unit="段"),  # F19 多段次数（1 轮 1 行动，每段独立结算）
        "trigger_limit": FieldMeta(type="obj", children={
            "per_round": FieldMeta(type="int", range_min=0, zero_unlimited=True, unit="次"),
            "per_battle": FieldMeta(type="int", range_min=0, zero_unlimited=True, unit="次"),
        }),  # F20 触发上限 {per_round, per_battle}；0=不限；技能级 > 库级 defaults > 全局（V-8 引擎强制）
        # ---- D 细化定型 4 字段（F21-F24，细化_6a §1.2-D）----
        "desc": FieldMeta(type="str"),   # F21 一句话说明（技能卡/战报/编辑器悬浮）
        "hit_mod": FieldMeta(type="number", range_min=0.0, range_max=10.0),  # F22 命中率修正（乘数，>0）
        "crit_mod": FieldMeta(type="number", range_min=0.0, range_max=10.0),  # F23 会心判定修正（乘数，>0）
        "block_mode": FieldMeta(type="str"),  # F24 auto/normal/ignore（枚举 A2 路；魔攻击无视格挡规则同源）
        # ---- F25-F26 防反/闪反姿态（2026-09-09 用户拍板标签制：姿态技能配反击类型与反击技）----
        "counter_type": FieldMeta(type="str"),  # F25 parry/dodge（防反/闪反姿态标记）
        "counter_skill": FieldMeta(type="str"),  # F26 姿态成功派生反击技 id（V-2 引用检查）
        "action_time": FieldMeta(type="number", range_min=0, unit="行动条"),  # F27 行动时间（反应窗口时长，行动条；缺省=ctb.default_action_time）
        "air_extend": FieldMeta(type="number", range_min=0, unit="行动条"),  # F28 空中延长（跃空窗口延长量，行动条；缺省=ctb.air_extend）
        "recovery": FieldMeta(type="number", range_min=0, unit="行动条"),  # 批⑥ C10 行动恢复值（总恢复值，行动条；缺省=ctb.default_recovery）
        "stun": FieldMeta(type="number", range_min=0),  # 批⑦A 气绝值（打击 × 正方位积累；全隐性）
        # ---- 兼容旧键（enemies[].skills 引用的技能表旧键）----
        "skill": FieldMeta(type="ref", ref_target="skill_or_any"),
        # ---- 编辑器重写批1：补齐 skills.json 真实在用、但本表原缺登记 8 键 ----
        # 依据：真实内容包实测（veinborn/test_demo 均出现 revert_form/derive_only/
        # energy_gain/energy_cost/brief；skill_models.skills_fields() 早已登记 F29/F30
        # 展示文本与 6b/6c 挂点，本表滞后 → 编辑器「文本」分区拿不到简述/详情）。
        # 一律软标注（soft_label=永不红拦）：补齐前这些键走「未知字段默认放行」，
        # 补齐后仍零新增拦截，泛型校验行为不变（type 仅供参考/渲染）。
        "brief": FieldMeta(type="str", soft_label=True),      # F29 简述（可空）
        # 编辑器重写批2：详情 = 长文本 → 声明 multiline，编辑控件给多行输入框
        # （纯显示维度，不影响任何校验判定；见 models.FieldMeta.multiline）。
        "detail": FieldMeta(type="str", soft_label=True, multiline=True),  # F30 详情（可空）
        "revert_form": FieldMeta(type="bool", soft_label=True),    # 6b 还原技标记
        "derive_only": FieldMeta(type="bool", soft_label=True),    # 6b 仅派生可用
        "energy_gain": FieldMeta(type="obj", soft_label=True),     # 6c 资源轴增减
        "energy_cost": FieldMeta(type="obj", soft_label=True),     # 6c 资源轴消耗
        "season": FieldMeta(type="str", soft_label=True),          # 6c 季节技能组
        "combo_table": FieldMeta(type="list", element=FieldMeta(type="obj"), soft_label=True),
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
        # 批4.5：items/equipment 实测顶层 desc（原表未登记 → 纯展示宽字段）
        "desc": _soft_display("说明"),
    }
    equipment_fields: Dict[str, FieldMeta] = dict(items_fields)
    # 部位互斥：entry.slot 与 entry.excludes 列表内部位互斥成环 → R-5（equipment 专项，§5.2 + L167）
    equipment_fields["slot"] = FieldMeta(type="str")
    equipment_fields["excludes"] = FieldMeta(type="list", element=FieldMeta(type="str"))
    # M12.5/veinborn 属性键收口：装备词条键 atk/dfn/foc/hp/agi（stats.json 声明的
    # combat 键空间；items_fields 复制源仍登记 def 旧键 → 追加 dfn/foc/hp/agi，
    # 保留 def 兼容旧内容包（demo_full 等 def 词条不受影响）。
    # label 区分（三路实测抓 P2）：def 与 dfn 同义「防御」→ 表单两个「防御」无法区分
    # 填错位置；def 标「(旧键)」供 demo_full 兼容识别，dfn 为现行键保持「防御」。
    equipment_fields["def"] = FieldMeta(type="number", range_min=0, range_max=5000,
                                        label="防御(def·旧键)", unit="点")
    equipment_fields["dfn"] = FieldMeta(type="number", range_min=0, range_max=5000, label="防御", unit="点")
    equipment_fields["foc"] = FieldMeta(type="number", range_min=0, range_max=5000, label="专注", unit="点")
    equipment_fields["hp"] = FieldMeta(type="number", range_min=0, range_max=99999, label="生命", unit="点")
    equipment_fields["agi"] = FieldMeta(type="number", range_min=0, range_max=5000, label="敏捷", unit="点")
    # 批⑧ 装备词条键空间收口（2026-09-12）：键与中文 label 取自 data.gear_stats 唯一
    # 注册表——context/shop_tx/详情面板/本表四处曾各持手写键表互相漂移（crit 与 _pct
    # 键漏转/漏展示）。此后新增词条 = 注册表加一行，本表自动跟进；范围仅提示不拦截
    # （枚举宽松口径，防误拦既有包）。items_fields 一并收口——veinborn 武器/防具在
    # items 模块（kind=item）中编辑，同样需要这些词条键。
    for _fm_target in (items_fields, equipment_fields):
        for _k in GEAR_FLAT_KEYS:
            if _k in _fm_target:
                continue
            _fm_target[_k] = FieldMeta(
                type="number", range_min=0,
                range_max=99999 if _k == "hp" else (9999 if _k == "mp" else 5000),
                label=GEAR_LABELS_ZH.get(_k, _k), unit="点")
        for _k in GEAR_PCT_KEYS:
            _fm_target[_k] = FieldMeta(
                type="number", range_min=0, range_max=500,
                label=GEAR_LABELS_ZH.get(_k, _k), unit="%")
        for _k in GEAR_COMBAT_KEYS:
            if _k == "crit":
                # 赌狗流负会心（批⑤ 引擎通道）→ 字段级放行负数（R-2 元数据开关）
                _fm_target[_k] = FieldMeta(
                    type="number", range_min=-99, range_max=99, allow_negative=True,
                    label=GEAR_LABELS_ZH.get(_k, _k) + "（可负）", unit="%")
            else:
                _fm_target[_k] = FieldMeta(
                    type="number", range_min=0,
                    range_max=2 if _k == "earplug" else 3,
                    label=GEAR_LABELS_ZH.get(_k, _k), unit="级")
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
        "pv": FieldMeta(type="number", range_min=0, range_max=500, unit="点"),  # F09（档区间仅提示；木桩强制 0 A2）
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
        "def_base": FieldMeta(type="number", range_min=0, range_max=99999, unit="点"),  # F17（≥0）
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
        # ---- 部位破坏（方位 v0.6 §三.3/附录 A Step 2；专项校验 content/validator _check_enemy_parts）----
        "parts": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str", label="部位 ID"),
            "name": FieldMeta(type="str", label="部位名"),
            "positions": FieldMeta(type="obj", children={
                "side": FieldMeta(type="list", element=FieldMeta(type="str"),
                                  label="可达方位"),
                "height": FieldMeta(type="list", element=FieldMeta(type="str"),
                                    label="可达高度"),
            }, label="可达方位格"),
            "break_threshold": FieldMeta(type="number", range_min=0, range_max=99999,
                                         label="破坏阈值"),
            "target_priority": FieldMeta(type="number", range_min=0, range_max=999,
                                         label="命中优先级"),
            "on_break": FieldMeta(type="obj", children={
                "knockdown": FieldMeta(type="number", range_min=0, range_max=99,
                                       label="倒地时长（次行动）"),
                "marks": FieldMeta(type="list", element=FieldMeta(type="str"),
                                   label="破位印记"),
                "effects": FieldMeta(type="list", element=FieldMeta(type="obj"),
                                     label="破位效果"),
            }, label="破位行为"),
        }), label="部位列表"),
        # 批4.5：AI 引擎依赖段（m2_shared_contract 第一节）实测存在于真实包，原表未登记 →
        # 纯展示宽字段（soft_label 短路泛型校验，零新增拦截）；children 由
        # ENEMIES_CHILD_LABELS 递归补中文名。
        "ai": _soft_display("AI 行为态", "obj"),
        "phases": _soft_display("阶段表", "list"),
        "rewards": _soft_display("奖励", "obj"),
        "zone_change": _soft_display("换区", "obj"),
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
        # 批4.5：真实包 maps.json 实有、原表未登记的地图段（→ 纯展示宽字段，soft_label
        # 短路泛型校验；children 由 MAPS_CHILD_LABELS 递归补中文名）。DUNGEON_MAP_ELEM_CHILDREN
        # 早已为「maps 页整图编辑」预留这些键，本批把它接到 maps 模块。
        "desc": _soft_display("说明"),
        "camp": _soft_display("营地", "obj"),
        "camp_name": _soft_display("营地名"),
        "npcs": FieldMeta(type="list", element=FieldMeta(type="str"),
                          soft_label=True, label="NPC 列表"),
        "monsters": _soft_display("刷怪行", "list"),
        "exits": _soft_display("通道出口", "obj"),
        "mechanics": _soft_display("地图机制", "list"),
        "gate_guard": _soft_display("门卫"),
        "gather_points": _soft_display("采集点", "list"),
        "dungeon_entrances": _soft_display("副本入口", "list"),
    }
    stats_fields: Dict[str, FieldMeta] = {}
    # M12.5 需求1 批D：formula 模块 stat_map 段字段口径（FORMULA_FIELDS 模块级常量，
    # 见定义处；编辑器 meta 返回供 stat_map 段逐键中文表单化渲染）
    formula_fields: Dict[str, FieldMeta] = dict(FORMULA_FIELDS)
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
    # 批4.5：settings.json 真实包实有、原表未登记的顶层段（→ 纯展示宽字段，soft_label
    # 短路泛型校验；children 由 SETTINGS_CHILD_LABELS 递归补中文名）。
    # 依据：content/{veinborn,test_demo,demo_full}/settings.json 实测键并集。
    SETTINGS_FIELDS.update({
        "assistant": _soft_display("助手", "obj"),
        "battle": _soft_display("战斗参数", "obj"),
        "command_aliases": _soft_display("指令别名", "obj"),
        "contest": _soft_display("竞技", "obj"),
        "ctb": _soft_display("行动条", "obj"),
        "events": _soft_display("事件文案", "obj"),
        "exp_curve": _soft_display("经验曲线", "obj"),
        "level_cap": _soft_display("等级上限", "int"),
        "quest_board": _soft_display("任务板", "obj"),
    })

    return {
        "manifest": ModuleMeta(
            entry_type="object",
            fields=_decorate_field_meta(manifest_fields, {}, MANIFEST_FIELD_LABELS,
                                        MANIFEST_CHILD_LABELS)),
        "effects": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(effects_fields, {}, EFFECTS_FIELD_LABELS,
                                                          EFFECTS_CHILD_LABELS,
                                                          EFFECTS_FIELD_HELP,
                                                          EFFECTS_CHILD_HELP),
                              kind="effect", namespace="effect_family"),
        "statuses": ModuleMeta(entry_type="list",
                               fields=_decorate_field_meta(statuses_fields, {}, STATUSES_FIELD_LABELS,
                                                           STATUSES_CHILD_LABELS,
                                                           STATUSES_FIELD_HELP,
                                                           STATUSES_CHILD_HELP),
                               kind="status", namespace="effect_family"),
        "marks": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(marks_fields, {}, MARKS_FIELD_LABELS,
                                                        MARKS_CHILD_LABELS,
                                                        MARKS_FIELD_HELP),
                            kind="mark", namespace="effect_family"),
        "skill_chains": ModuleMeta(entry_type="list",
                                   fields=_decorate_field_meta(skill_chains_fields, {},
                                                               SKILL_CHAINS_FIELD_LABELS,
                                                               SKILL_CHAINS_CHILD_LABELS,
                                                               SKILL_CHAINS_FIELD_HELP,
                                                               SKILL_CHAINS_CHILD_HELP),
                                   kind="skill_chain",
                                   namespace="chain_lib", chain_field="next"),
        "action": ModuleMeta(entry_type="list",
                             fields=_decorate_field_meta(action_fields, {}, ACTION_FIELD_LABELS,
                                                         ACTION_CHILD_LABELS,
                                                         ACTION_FIELD_HELP),
                             kind="action", namespace="action_lib"),
        # M13 技能库（细化_6a_技能库契约 §1：skills.json 玩家技能库；F01-F24 全字段登记；
        # kind="skill" 与 loader _KIND_FOR_MODULE + DEF_CLASSES 对齐（路1A SkillDef）；
        # 命名空间 skill_lib 独立于 action_lib——V-10 跨库重名仅黄提示）
        "skills": ModuleMeta(
            entry_type="list",
            fields=_decorate_field_meta(skills_fields, SKILLS_FIELD_GROUPS, SKILLS_FIELD_LABELS,
                                        SKILLS_CHILD_LABELS, SKILLS_FIELD_HELP,
                                        SKILLS_CHILD_HELP),
            kind="skill", namespace="skill_lib",
            field_groups=dict(SKILLS_FIELD_GROUPS),
            group_order=SKILLS_GROUP_ORDER,
        ),
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
        "jobs": ModuleMeta(entry_type="list",
                           fields=_decorate_field_meta(jobs_fields, {}, JOBS_FIELD_LABELS,
                                                       JOBS_CHILD_LABELS),
                           kind="job", namespace="job_lib"),
        "formula": ModuleMeta(entry_type="map", fields=formula_fields, kind="formula", namespace="formula_lib"),
        "items": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(items_fields, ITEMS_FIELD_GROUPS, ITEMS_FIELD_LABELS,
                                                        None, ITEMS_FIELD_HELP, ITEMS_CHILD_HELP),
                            kind="item", namespace="item_lib",
                            field_groups=ITEMS_FIELD_GROUPS, group_order=ITEMS_GROUP_ORDER,
                            group_labels=ITEMS_GROUP_LABEL_MAP),
        "equipment": ModuleMeta(entry_type="list",
                                fields=_decorate_field_meta(equipment_fields, EQUIPMENT_FIELD_GROUPS, EQUIPMENT_FIELD_LABELS,
                                                            None, EQUIPMENT_FIELD_HELP, ITEMS_CHILD_HELP),
                                kind="equipment",
                                namespace="item_lib", mutex_field="excludes",
                                field_groups=EQUIPMENT_FIELD_GROUPS, group_order=EQUIPMENT_GROUP_ORDER,
                                group_labels=ITEMS_GROUP_LABEL_MAP),
        "traits": ModuleMeta(entry_type="list",
                             fields=_decorate_field_meta(traits_fields, {}, TRAITS_FIELD_LABELS,
                                                         TRAITS_CHILD_LABELS),
                             kind="trait", namespace="trait_lib"),
        # M8 炼金（m8_contract_数据与校验 §一/§三/§四 4.2）：recipe/proficiency 新增登记四件套；
        # slots 由 alchemy_settings.slots_module_meta() 提供（kind=slots，与 loader 注册表同名）
        "recipe": ModuleMeta(entry_type="list",
                             fields=_decorate_field_meta(recipe_fields, {}, RECIPE_FIELD_LABELS,
                                                         RECIPE_CHILD_LABELS),
                             kind="recipe", namespace="recipe_lib"),
        "proficiency": ModuleMeta(entry_type="list",
                                  fields=_decorate_field_meta(proficiency_fields, {},
                                                              PROFICIENCY_FIELD_LABELS,
                                                              PROFICIENCY_CHILD_LABELS),
                                  kind="proficiency", namespace="proficiency_lib"),
        "slots": _decorate_module_meta(slots_module_meta(), SLOTS_FIELD_LABELS,
                                       SLOTS_CHILD_LABELS),
        # M9 锻造（m9_shared_contract §〇~§六）：forge.json 顶层 obj——模块级 ModuleMeta
        # 由 forge_module_meta() 提供（entry_type=object）；M12.5 批3 路3A 注入段级
        # 字段表 FORGE_TOP_FIELD_DEFS（schema_version 精确 + trees/sets/augments/
        # settings 四宽容器 soft_label——泛型零新增拦截）；深结构校验由
        # validate_forge 专项全权（V1-V15/W + 2c2d V1-V8/W1-W4），泛型只做顶层形态
        "forge": _decorate_module_meta(forge_module_meta(), (), FORGE_CHILD_LABELS),
        # M10 钓鱼（m10_shared_contract §三）：fishing.json 顶层 obj——模块级 ModuleMeta
        # 由 fishing_module_meta() 提供（entry_type=object）；深结构校验由
        # validate_fishing 专项全权（V1-V6/W1），泛型只做顶层形态（对齐 forge/dungeon）
        "fishing": _decorate_module_meta(fishing_module_meta(), (), FISHING_CHILD_LABELS),
        # M12.5 强化（2c3a/2c3b）：enhance.json 顶层 obj——模块级 ModuleMeta 由
        # enhance_module_meta() 提供（entry_type=object）；深结构校验由
        # validate_enhance 专项全权（V1~V7），泛型只做顶层形态（对齐 forge/fishing）
        "enhance": _decorate_module_meta(enhance_module_meta(), (), ENHANCE_CHILD_LABELS),
        "enemies": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(enemies_fields, ENEMIES_FIELD_GROUPS,
                                                          ENEMIES_FIELD_LABELS, ENEMIES_CHILD_LABELS,
                                                          ENEMIES_FIELD_HELP, ENEMIES_CHILD_HELP),
                              kind="enemy", namespace="enemy_lib",
                              field_groups=ENEMIES_FIELD_GROUPS, group_order=ENEMIES_GROUP_ORDER,
                              group_labels=ENEMIES_GROUP_LABEL_MAP),
        "maps": ModuleMeta(entry_type="list",
                           fields=_decorate_field_meta(maps_fields, MAPS_FIELD_GROUPS,
                                                       MAPS_FIELD_LABELS, MAPS_CHILD_LABELS),
                           kind="map", namespace="map_lib",
                           field_groups=MAPS_FIELD_GROUPS, group_order=MAPS_GROUP_ORDER,
                           group_labels=MAPS_GROUP_LABEL_MAP),
        # M3 副本（m3_shared_contract §4）：新结构由 dungeon_models.validate_dungeons 专项全权。
        # M12.5 批1 路1C：宽松字段表注入（仅 id required + 宽容器 + 闭合枚举，
        # 泛型零新增拦截——专项校验仍全权深结构）
        "dungeon": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(DUNGEON_FIELDS, {}, {},
                                                          DUNGEON_CHILD_LABELS),
                              kind="dungeon", namespace="dungeon_lib"),
        "stats": ModuleMeta(entry_type="map", fields=stats_fields, kind="stat", namespace="stat_lib",
                            key_regex=r"[a-z][a-z0-9_]*"),
        # M4 交互系统（m4_shared_contract §3.1~3.4）：npc/shop/quest/checkin 专项校验器
        # 全权深结构（R-1~R-5/Y-1~Y-8 专项判定）；M12 批4 路4A 注入正式字段表（宽松登记：
        # 仅 id required + 宽 obj 容器 + 闭合枚举——编辑器表单数据源 P-07，泛型并行零新增拦截）
        "npc": ModuleMeta(entry_type="list",
                          fields=_decorate_field_meta(NPC_FIELDS, {}, {}, NPC_CHILD_LABELS),
                          kind="npc", namespace="npc_lib"),
        "shop": ModuleMeta(entry_type="list",
                           fields=_decorate_field_meta(SHOP_FIELDS, {}, {}, SHOP_CHILD_LABELS),
                           kind="shop", namespace="shop_lib"),
        "quest": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(QUEST_FIELDS, QUEST_FIELD_GROUPS,
                                                        QUEST_FIELD_LABELS, QUEST_CHILD_LABELS),
                            kind="quest", namespace="quest_lib",
                            field_groups=QUEST_FIELD_GROUPS, group_order=QUEST_GROUP_ORDER,
                            group_labels=QUEST_GROUP_LABEL_MAP),
        "checkin": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(CHECKIN_FIELDS, {}, {},
                                                          CHECKIN_CHILD_LABELS),
                              kind="checkin", namespace="checkin_lib"),
        # M11 成就（4c §1.5）：顶层 list；M12.5 批1 路1C 宽松字段表注入
        # （专项校验器 achievements_models ACH01-13 仍全权深结构，泛型零新增拦截）
        "achievements": ModuleMeta(entry_type="list",
                                   fields=_decorate_field_meta(ACHIEVEMENT_FIELDS, {}, {},
                                                               ACHIEVEMENT_CHILD_LABELS),
                                   kind="achievement", namespace="achievement_lib"),
        # 条件加成（细化_3b §3.2；环 + 引用存在性专项校验见 validator._check_conditional）
        "conditional": ModuleMeta(entry_type="object",
                                  fields=_decorate_field_meta(conditional_fields, {},
                                                              CONDITIONAL_FIELD_LABELS,
                                                              CONDITIONAL_CHILD_LABELS),
                                  kind="conditional", namespace="cond_lib"),
        # 通用设置（细化_1g4 §6.1 death_penalty + currencies 段；其余段由 3h 路登记缺省放行）。
        # 注意：settings.json 为常驻模块（3h D-01），本表仅登记字段口径；loader 常驻加载归 3h/M 接线。
        "settings": ModuleMeta(entry_type="object",
                               fields=_decorate_field_meta(SETTINGS_FIELDS, {},
                                                           SETTINGS_FIELD_LABELS,
                                                           SETTINGS_CHILD_LABELS,
                                                           SETTINGS_FIELD_HELP)),
        # M12 批4 路4A 编辑器扩展页视图（5a2 PR-01：editor.json 页表 meta_source 指向；
        # 无独立 json 模块——ai/hidden 是 enemies 条目内嵌视图、env_event/log_card 是
        # settings 段视图；ModuleMeta 仅登记供 /api/meta/{page} 表单元数据，内容包不含
        # 这些模块名 → 校验不触发，WIR-13 loader ⊆ field_meta 单向断言不受影响）
        "ai": ModuleMeta(entry_type="list", fields=AI_FIELDS, kind="ai", namespace="enemy_lib"),
        "hidden": ModuleMeta(entry_type="list", fields=HIDDEN_FIELDS, kind="hidden",
                             namespace="enemy_lib"),
        "env_event": ModuleMeta(entry_type="object", fields=ENV_EVENT_FIELDS,
                                kind="env_event", namespace="settings_lib"),
        "log_card": ModuleMeta(entry_type="object", fields=LOG_CARD_FIELDS,
                               kind="log_card", namespace="settings_lib"),
        # M12.5 批1/2：editor.json 页面注册表模块（M12 起内容包实文件即存在；
        # manifest 声明后才进 modules_raw → 动态页表才生效）。
        # 宽松 obj 登记：仅 schema_version/pages 两键宽容器（编辑器注册表语义，
        # 深结构由内容包 manifest 全权声明）。
        "editor": ModuleMeta(entry_type="object", fields={
            "schema_version": FieldMeta(type="int", label="页表 schema 版本"),
            "pages": FieldMeta(type="list",
                               element=FieldMeta(type="obj", children={}),
                               soft_label=True, label="页面登记"),
        }),
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
        value_meta=FieldMeta(type="obj",
                             children=_decorate_field_meta(STAT_CHILDREN, {},
                                                           STATS_FIELD_LABELS)),
    )
    # formula：键=公式名，值为公式字符串或 {formula: 表达式}（长度>4KB / AST 黑名单 → 红拦，§3.3）；
    # M12.5 需求1 批D：fields 注入 formula_fields（stat_map 段口径，编辑器 meta 可编）；
    # value_meta=formula 保留（map 键值表公式语义；stat_map 键是段容器，字段表只供
    # 编辑器 meta 展示，校验仍走 map 逐键 formula 值校验 + stat_map 宽松黄校验）。
    modules["formula"] = ModuleMeta(
        entry_type="map",
        fields=dict(FORMULA_FIELDS),
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
    # M12.5 批1 路1C：C 类宽松注入表（dungeon/achievements 编辑器表单数据源）
    "DUNGEON_FIELDS", "ACHIEVEMENT_FIELDS",
    # 编辑器重写批1：skills 模块级分组表（页签顺序 = 元数据声明，编辑器零写死）
    "SKILLS_GROUP_DEFS", "SKILLS_FIELD_GROUPS", "SKILLS_GROUP_ORDER", "SKILLS_FIELD_LABELS",
    # 编辑器重写批3：enemies/items/equipment/maps/quest 分组声明（顺序 + 显示名）
    "ENEMIES_GROUP_DEFS", "ENEMIES_FIELD_GROUPS", "ENEMIES_GROUP_ORDER", "ENEMIES_GROUP_LABELS",
    "ITEMS_GROUP_DEFS", "ITEMS_FIELD_GROUPS", "ITEMS_GROUP_ORDER", "ITEMS_GROUP_LABELS",
    "EQUIPMENT_FIELD_GROUPS", "EQUIPMENT_GROUP_ORDER",
    "MAPS_GROUP_DEFS", "MAPS_FIELD_GROUPS", "MAPS_GROUP_ORDER", "MAPS_GROUP_LABELS",
    "QUEST_GROUP_DEFS", "QUEST_FIELD_GROUPS", "QUEST_GROUP_ORDER", "QUEST_GROUP_LABELS",
    # 编辑器重写批3.5：模块**字段**中文名（显示层；前端「中文名 + 原始键」并列渲染的数据源）
    "ENEMIES_FIELD_LABELS", "ITEMS_FIELD_LABELS", "EQUIPMENT_FIELD_LABELS",
    "MAPS_FIELD_LABELS", "QUEST_FIELD_LABELS",
    "EFFECTS_FIELD_LABELS", "STATUSES_FIELD_LABELS", "MARKS_FIELD_LABELS",
    "SKILL_CHAINS_FIELD_LABELS", "ACTION_FIELD_LABELS", "JOBS_FIELD_LABELS",
    # 编辑器重写批4.5：嵌套子字段中文名（递归；含 element.children）+ 余量模块字段名
    "ENEMIES_CHILD_LABELS", "SKILLS_CHILD_LABELS", "JOBS_CHILD_LABELS",
    "MAPS_CHILD_LABELS", "QUEST_CHILD_LABELS", "EFFECTS_CHILD_LABELS",
    "STATUSES_CHILD_LABELS", "MARKS_CHILD_LABELS", "SKILL_CHAINS_CHILD_LABELS",
    "ACTION_CHILD_LABELS", "NPC_CHILD_LABELS", "SHOP_CHILD_LABELS",
    "CHECKIN_CHILD_LABELS", "DUNGEON_CHILD_LABELS", "ACHIEVEMENT_CHILD_LABELS",
    "TRAITS_CHILD_LABELS", "RECIPE_CHILD_LABELS", "PROFICIENCY_CHILD_LABELS",
    "SLOTS_CHILD_LABELS", "CONDITIONAL_CHILD_LABELS", "MANIFEST_CHILD_LABELS",
    "SETTINGS_CHILD_LABELS", "FORGE_CHILD_LABELS", "FISHING_CHILD_LABELS",
    "ENHANCE_CHILD_LABELS",
    "MANIFEST_FIELD_LABELS", "TRAITS_FIELD_LABELS", "RECIPE_FIELD_LABELS",
    "PROFICIENCY_FIELD_LABELS", "SLOTS_FIELD_LABELS", "STATS_FIELD_LABELS",
    "SETTINGS_FIELD_LABELS", "CONDITIONAL_FIELD_LABELS",
    # 编辑器重写批4.6：字段**说明**元数据（说明卡「人工补充」；自动拼装在 web/api.py）
    "SKILLS_FIELD_HELP", "SKILLS_CHILD_HELP",
    "ENEMIES_FIELD_HELP", "ENEMIES_CHILD_HELP",
    "ITEMS_FIELD_HELP", "ITEMS_CHILD_HELP", "EQUIPMENT_FIELD_HELP",
    "EFFECTS_FIELD_HELP", "EFFECTS_CHILD_HELP",
    "STATUSES_FIELD_HELP", "STATUSES_CHILD_HELP",
    "MARKS_FIELD_HELP", "SKILL_CHAINS_FIELD_HELP", "SKILL_CHAINS_CHILD_HELP",
    "ACTION_FIELD_HELP", "SETTINGS_FIELD_HELP",
    "F_SKILL_POWER",
]
