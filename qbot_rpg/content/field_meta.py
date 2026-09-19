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

from qbot_rpg.content.models import (
    RESET_UNITS,
    AssociationMeta,
    ConditionSubject,
    FieldMeta,
    FieldMetaTable,
    ModuleMeta,
)
# M9 锻造（m9_shared_contract）：forge 模块 ModuleMeta + items 材料类扩展 +
# settings.forge 段。forge_models/forge_settings 仅依赖 content.models（零 field_meta
# import，无循环依赖）；字段定义自包含持有，本表单向 import（防 G0 反向依赖）。
from qbot_rpg.content.enhance_models import enhance_module_meta
from qbot_rpg.content.forge_models import forge_module_meta
from qbot_rpg.content.forge_settings import ITEMS_FORGE_FIELDS, forge_settings_meta
# 批41 · 深度打造数据层（打造参数段默认值 + 图纸/材料字段 + 品质概率阶梯）：
# 自包含持有（零 field_meta import，无循环依赖），与本文件「schema 之家」口径一致。
from qbot_rpg.content.deep_craft_settings import (
    DEEP_CRAFT_SEGMENT_FIELDS,
    ITEMS_BLUEPRINT_FIELDS,
    ITEMS_MATERIAL_CRAFT_FIELDS,
)
# M10 钓鱼（m10_shared_contract）：fishing 模块 ModuleMeta + settings.fishing 段。
# fishing_models 仅依赖 content.models（零 field_meta import，无循环依赖）；
# fishing_settings_meta 自包含持有（防 field_meta↔fishing 循环依赖）。
from qbot_rpg.content.fishing_models import fishing_module_meta, fishing_settings_meta
# 批⑧ 装备词条键空间唯一源（data 层——G0 依赖矩阵 content→{data}，注册表落 data 层
# 供 content/core/commands 全层引用）。
from qbot_rpg.data.gear_stats import (
    GEAR_COMBAT_KEYS,
    GEAR_COMBAT_PCT_KEYS,
    GEAR_COMBAT_VALUE_KEYS,
    GEAR_FLAT_KEYS,
    GEAR_HELP_ZH,
    GEAR_LABELS_ZH,
    GEAR_PCT_KEYS,
    GEAR_PLACEHOLDER_KEYS,
)
# 批B：包展示元数据下放——框架只保留子字段**结构**（无中文名/说明），展示文案在各包
# `content/<包>/field_meta.json`。结构模块由 scripts/migrate_pack_field_meta.py 生成。
from qbot_rpg.content.field_meta_child_structure import CHILD_SPEC
# 批36（采集/挖掘）：季节/时段枚举**单源**取地图专项校验器常量（细化_2a1d V-4Z：季节 ∈ 四季、
# 时段 ∈ 五时段，固定写死枚举）——编辑器下拉与校验器共用同一元组，避免口径分裂。
# map_models 只依赖 content.models（不反向 import 本模块），无循环。
from qbot_rpg.content.map_models import PERIODS_ENUM, SEASONS_ENUM

# -------------------------------------------------------------------------------------
# 编辑器批19 #7：指令别名配置的框架落点（settings.json 的 command_aliases 段）。
# 这是**框架约定位置**（非内容包业务名）；编辑器读取层引用本常量，不在 web 层写死字面量。
# -------------------------------------------------------------------------------------
ALIAS_CONFIG_MODULE = "settings"
ALIAS_CONFIG_KEY = "command_aliases"

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
    # 批46 · 符文地基（43-A）：runes.json 独立注册表（符文 id 命名空间独立于 items.id；
    # 孔位/镶嵌共用 slots 数组，但符文定义含跨装备类型差异表，独立成册）。
    "rune_lib": ("runes",),
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

# 批18 · effects.type 的**展示层候选值**（编辑器下拉可选；不改校验判定）。
# 依据：effects.type 是**开放词汇**（框架 L0 动作 + 内容包泛化类别 + `x_` 自定义通道），
# 故校验仍按 `type=str` 放行（不设 enum，防误拦 x_ 与包内新词）；这里只给作者一个
# 「常见类型」候选下拉，批18 起加入 gain_currency（给货币）/ learn_skill（学技能）。
# 与 effects.py 的 execute_action L0 词汇 + 现有内容包实测取值对齐（新增词随专项追加）。
EFFECT_TYPE_CHOICES: Tuple[str, ...] = (
    # 直行/修正器/容器 L0 词汇（core/effects.execute_action）
    "damage", "heal", "stat_modifier", "dot", "control", "status_apply", "dispel",
    "shield", "mark_add", "mark_remove", "clear_marks", "summon", "convert",
    "interrupt", "aoe", "lifesteal", "pierce", "mitigation", "proc",
    "reposition", "reposition_all", "element_modifier",
    # 内容包既有泛化类别（历史取值，保留可选）
    "attack", "buff", "status", "utility",
    # 批18 新增效果类型（背包内使用消费：见 commands/use_commands.py）
    "gain_currency", "learn_skill",
)
# effects.type 专用字段元数据：type=str（校验口径不变）+ editor=select（展示层下拉）+
# enum_options（候选值）。既有 enum/hint/help/label/校验语义全部不变——只多一个下拉候选。
F_EFFECT_TYPE = FieldMeta(type="str", editor="select", enum_options=EFFECT_TYPE_CHOICES)

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
def _gear_combat_field(key: str) -> FieldMeta:
    """COMBAT 战斗直读键 → 字段元数据（items/equipment/enemies.stats 三处共用，单一源）。

    显示口径随键分档（仅编辑器提示）：百分比（% 0-100）/ 穿值（点 ≥0）/ 会心（可负）/
    其余档位键（级）。键与中文名来自 data.gear_stats 唯一注册表；批22 · A3/D1 起
    怪物 stats 也用同一构建器，不新造第二套命名。
    """
    label = GEAR_LABELS_ZH.get(key, key)
    help_ = GEAR_HELP_ZH.get(key, "")
    if key == "crit":
        return FieldMeta(type="number", range_min=-99, range_max=99, allow_negative=True,
                         label=label + "（可负）", unit="%")
    if key in GEAR_COMBAT_PCT_KEYS:
        return FieldMeta(type="number", range_min=0, range_max=100, label=label, unit="%",
                         help=help_)
    if key in GEAR_COMBAT_VALUE_KEYS:
        return FieldMeta(type="number", range_min=0, range_max=99999, label=label, unit="点",
                         help=help_)
    return FieldMeta(type="number", range_min=0, range_max=2 if key == "earplug" else 3,
                     label=label, unit="级")


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
# 批22 · D1：怪物常驻吸血/穿透/免伤——**复用 A3 的键**（同注册表 data.gear_stats：
# GEAR_COMBAT_PCT_KEYS + GEAR_COMBAT_VALUE_KEYS），走同一战斗桥（battle_launch_commands.
# _enemy_combatant 应用 combatant_updates）；不新造第二套命名。取值语义与玩家装备词条
# 完全一致（见 gear_stats 模块 docstring 的数值口径）。
for _ck in (*GEAR_COMBAT_PCT_KEYS, *GEAR_COMBAT_VALUE_KEYS):
    ENEMY_STATS_CHILDREN[_ck] = _gear_combat_field(_ck)
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
# 批16 #10：本表是**使用处**（引用处）——probability/weight 留空 = 用行动定义处的默认值。
ACTION_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    "action": FieldMeta(type="ref", ref_target="action", required=True, label="行动"),
    "probability": FieldMeta(type="number", range_min=0, range_max=1, label="概率",
                             help="使用处覆盖：留空 = 用行动定义处的默认值。"),
    "weight": FieldMeta(type="number", range_min=0, range_max=100, label="权重",
                        help="使用处覆盖：留空 = 用行动定义处的默认值。"),
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
    # 批12 #3：`currency` 用**展示层引用**（options_ref）出下拉——候选来自本模块
    # `currencies` 列表的 id（编辑器唯一的「内部键空间」通用机制）；字段 type 仍为 str，
    # F-02 存在性硬拦仍由 _check_settings_1g4 判定（校验语义零变化）。
    "drop_currency": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "currency": FieldMeta(type="str", options_ref="settings.currencies"),
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
    "slot_defs": FieldMeta(type="obj", children={
        # 批38 · ③：部位定义子字段结构登记（含角色 role）——编辑器「装备槽位」键值表逐列出控件；
        # 键 = 部位 id（动态键空间）；缺省 role=main。数值/失活消费见 core/equipment（H7）。
        "name": FieldMeta(type="str", label="部位名"),
        "max": FieldMeta(type="int", range_min=1, label="可装备数量"),
        "role": FieldMeta(
            type="enum", enum=("main", "offhand"), default="main", label="部位角色",
            help="main=主装备位（缺省）；offhand=副手位——需 settings.equipment_offhand."
                 "enabled 开启后按副手规则生效（单手武器作副手：数值类属性折算、"
                 "百分比/强化特殊词条/装备被动/套装词条/符文附魔不激活）。"),
    }, soft_label=True, label="装备槽位"),
    # 批38 · H7 副手装备开关（settings.equipment_offhand；默认 false = 与本系统引入前一致）。
    # 形态 {enabled, single_hand_scale}；消费点 core/equipment.EquipmentEngine（归一入口）
    # + aggregate_bonus（数值折算/百分比与战斗键失活）+ equip_mods/forge_sets/jewel 读取点。
    # 注：`slot_defs.<部位>.role` 的字段登记在批38 ③（部位角色 main/offhand）；本开关为总闸。
    "equipment_offhand": FieldMeta(type="obj", children={
        "enabled": FieldMeta(type="bool", default=False, label="是否启用副装备",
                             help="开启后，settings.slot_defs 中 role=offhand 的部位按副手规则"
                                  "生效（单手武器作副手：数值类属性按折算比例、其余加成不激活）。"
                                  "关闭 = 行为与本系统引入前逐字段一致（默认关闭）。"),
        "single_hand_scale": FieldMeta(type="number", range_min=0.0, range_max=1.0,
                                       default=0.5, label="单手作副手折算",
                                       help="单手武器放进副手部位时，数值类属性的折算比例"
                                            "（0.5=50%）；百分比类属性、强化特殊词条、装备被动、"
                                            "套装词条、符文附魔一律不激活。"),
    }, label="副手装备",
        help="副手装备总开关（默认关闭）。在「装备槽位」里把某部位角色设为「副手」后，"
             "本开关控制副手规则是否生效。"),
    # 批45 · 装备占比校准（settings.panel_budget）——决策记录 §三 补充 1（用户 2026-09-19）。
    # 面板预算 white:equip:buff（上游模型 7:8:5，docs/veinborn_阶段一_数值模型_1-35_v2.md:32）；
    # 装备面板倍率 equip_stat_mult 乘在装备这一份 → 占比 = equip×mult/(white+equip×mult+buff)。
    # 引擎消费点：core/equipment.aggregate_bonus（只作用面板轴 atk/dfn/hp，读时生效可回滚）。
    "panel_budget": FieldMeta(type="obj", children={
        "white": FieldMeta(type="number", range_min=0.0, default=7, label="面板预算·白值份",
                           help="面板预算中「白值（基础+职业成长）」占的份数（设计口径，冻结不动）。"
                                "占比 = 装备份×倍率 ÷（白值份 + 装备份×倍率 + buff份）。"),
        "equip": FieldMeta(type="number", range_min=0.0, default=8, label="面板预算·装备基准份",
                           help="面板预算中「装备」占的基准份数（设计口径，冻结不动）。"
                                "有效装备份 = 本值 × 装备面板倍率。"),
        "buff": FieldMeta(type="number", range_min=0.0, default=5, label="面板预算·buff份",
                          help="面板预算中「战斗临时加成（buff）」占的份数（设计口径，冻结不动）。"),
        "equip_stat_mult": FieldMeta(
            type="number", range_min=0.0, default=1.0, label="装备面板倍率",
            help="装备加成的总额度倍率，乘在装备「面板轴」atk/dfn/hp 上（读时聚合，不改落档数值，"
                 "改回 1.0 即完全回滚）。1.0=现状；2.25 → 装备份 8→18、装备占比 40%→60%、"
                 "面板总功率 ×1.5（此为批45 校准值）。"),
    }, label="面板预算（装备占比）",
        help="面板数值预算：白值份 : 装备份 : buff份 的设计配比与装备倍率。"
             "用于把「装备占比」调到目标值（批45：40%→60%），同时保持白值与 buff 绝对数值不变。"),
    # 批45 · 怪物数值倍率（settings.monster_scaling）——按面板总功率同比例重校，保斩杀回合。
    # 引擎消费点：commands/battle_launch_commands._enemy_combatant（读 enemies.json → combatant）。
    "monster_scaling": FieldMeta(type="obj", children={
        "hp_mult": FieldMeta(type="number", range_min=0.0, default=1.0, label="怪物生命倍率",
                             help="怪物 hp/max_hp 的缩放倍率（1.0=现状）。批45 校准 1.5（+50%，"
                                  "与面板总功率同比例）。"),
        "atk_mult": FieldMeta(type="number", range_min=0.0, default=1.0, label="怪物攻击倍率",
                              help="怪物攻击（str→atk）的缩放倍率（1.0=现状）。批45 校准 1.5。"),
        "def_factor": FieldMeta(
            type="number", range_min=0.0, default=1.0, label="怪物防御系数补偿",
            help="怪物防御（体质 con）的仿射补偿：con' = (con+K)×本值 − K（K=def_k）。"
                 "因防御系数 K/(con+K) 非线性，等比缩 con 会破坏「斩杀回合不变」；"
                 "本值按中值档面板实测比值反解（批45 = 1.0828）。1.0=防御不变。"),
        "def_k": FieldMeta(type="number", range_min=0.0, default=100.0, label="防御公式常数 K",
                           help="防御系数 K/(con+K) 的常数 K（与战斗数值层 defense.k 同源，默认 100）。"
                                "仅用于防御系数补偿的反解基准。"),
    }, label="怪物数值倍率",
        help="怪物侧数值重校（默认全 1.0 = 现状）。按面板总功率比例同步怪物生命/攻击；"
             "防御按斩杀回合不变式做补偿，目标 = 保持既有斩杀回合数与手感。"),
    # 批39 · 「合成」提升为打造与炼金的公用系统——三条启用路径在编辑器可见可配：
    #   · 合成（公用层）+ 炼金（+深度炼金）：由 settings.alchemy.mode 三态声明推导
    #     （full 三层漏斗 / simple 仅合成层 / off 关闭；枚举单一事实源 MODE_VALUES，
    #      该字段既有登记见下方 alchemy 段，不改其 label/help——字段元数据对拍门禁）；
    #   · 打造（深度打造）：settings.deep_craft.enabled（obj + enabled，默认关，与批38
    #     settings.equipment_offhand 同风格）。推导唯一入口 = core/craft_paths.py。
    # 键名刻意避开既有 M9 锻造配置段 settings.forge，防语义混淆。
    "deep_craft": FieldMeta(type="obj", children={
        "enabled": FieldMeta(type="bool", default=False, label="是否启用深度打造",
                             help="开启后，「打造」路径可用：图纸 / 材料相性 / 随机属性与套装词条 / "
                                  "品质经验 / 强化词条 / 符文 / 淬炼等**深度层**玩法。"
                                  "深度打造的基础合成（配方+材料 → 标准版产出）走**公用合成层**，"
                                  "不另造第二套合成。关闭 = 不启用打造（默认关闭）。"),
    }, label="深度打造",
        help="打造路径开关（默认关闭）。三条启用路径：① 只启用合成（settings.alchemy.mode"
             "=simple）；② 合成 + 炼金（mode=full）；③ 合成 + 打造（本开关开启）。"
             "合成是打造与炼金的公用层；关闭打造不影响合成与炼金。"),
    # 批46 · 符文地基（43-A）：符文孔位缺省段（口径 §二.2a；原案 §9「所有装备固定三个孔位」）。
    # 落点 = settings.rune_sockets（obj）；引擎消费点 = core/jewel.JewelSystem.rune_socket_defs
    # （已登记 slots.json 的装备用登记数组，未登记 → 按本段 default_count 开孔，与装饰珠
    # 共用同一孔位数组）。符文总闸复用 settings.deep_craft.enabled（口径 §二.5，不新增总闸）。
    "rune_sockets": FieldMeta(type="obj", children={
        "default_count": FieldMeta(
            type="int", range_min=1, range_max=3, default=3, label="缺省孔位数",
            help="未在 slots.json 登记的装备按此孔位数开孔（1-3；默认 3=原案「固定三个孔位」）。"
                 "已登记装备仍用登记数组（向后兼容），符文与装饰珠共用同一孔位数组。"),
    }, label="符文孔位",
        help="符文孔位缺省配置。符文与既有装饰珠共用 slots.json 的孔位数组（一槽一物、互斥）；"
             "本段只管「未登记装备的缺省开孔数」。符文系统总闸 = 深度打造开关。"),
    # 批38 · ④ 相性通用层（打造与深度炼金共用；settings 顶层四段，非打造私有）。
    # 引擎 = core/affinity.py（纯函数）；对外单一查询 resolve_available_entries()。
    "affinities": FieldMeta(
        type="list", label="相性定义",
        element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str", required=True, label="相性 ID"),
            "name": FieldMeta(type="str", label="中文名"),
            "desc": FieldMeta(type="str", label="说明"),
            "exclusive_pool": FieldMeta(type="str", label="专属池引用"),
        }),
        help="相性注册表：id 为内容包自定义（框架不内置任何相性名）；专属池指向"
             "「相性词条池」的池 id。打造/深度炼金共用同一定义。"),
    "affinity_pools": FieldMeta(
        type="list", label="相性词条池",
        element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str", required=True, label="池 ID"),
            "kind": FieldMeta(type="enum", enum=("common", "exclusive", "linkage"),
                              label="池类型"),
            "desc": FieldMeta(type="str", label="说明"),
            "entries": FieldMeta(type="list", label="词条行", element=FieldMeta(type="obj", children={
                "stat": FieldMeta(type="str", label="属性键"),
                "effect_ref": FieldMeta(type="str", label="效果引用"),
                "weight": FieldMeta(type="number", range_min=0, label="权重"),
                "min_level": FieldMeta(type="int", range_min=1, label="最低等级"),
                "requires_affinity": FieldMeta(type="str", label="要求相性"),
                "value_rule": FieldMeta(type="str", label="数值规则"),
                # 批42 · C：随机属性值 + 随机套装词条载荷
                # （`stat`+`value` = 随机属性候选；`set_affix` = 随机套装词条候选）。
                "value": FieldMeta(type="number", allow_negative=True, label="固定值"),
                "set_affix": FieldMeta(type="str", label="套装词条"),
            })),
        }),
        help="一个池结构同时服务随机属性/套装词条/强化词条/相性专属池：kind=common 通用池"
             "（任意相性可抽）；exclusive 专属池；linkage 联动覆盖池。"
             "查询接口 = 「通用池 ∪ 主相性专属池（联动命中则被覆盖）」并按 requires_affinity 过滤。"),
    "affinity_linkage": FieldMeta(
        type="list", label="相性联动",
        element=FieldMeta(type="obj", children={
            "main": FieldMeta(type="str", label="主相性"),
            "sub": FieldMeta(type="str", label="副相性"),
            "override_pool": FieldMeta(type="str", label="覆盖池"),
        }),
        help="主+副相性配对的特殊联动：命中时专属池被「覆盖池」替换（原案 §12）。"),
    "affinity_reactions": FieldMeta(
        type="list", label="材料相性互动",
        element=FieldMeta(type="obj", children={
            "kind": FieldMeta(type="enum", enum=("conflict", "amplify", "reverse"),
                              label="互动类型"),
            "from": FieldMeta(type="str", label="源相性（反转）"),
            "to": FieldMeta(type="str", label="目标相性（反转）"),
            "pair": FieldMeta(type="list", element=FieldMeta(type="str"),
                              label="相性对（冲突/增幅）"),
            "value": FieldMeta(type="number", allow_negative=True, label="系数/加值"),
        }),
        help="材料间的相性互动：conflict=互相减少 / amplify=互相增加 / reverse=把 from 相性"
             "转为 to；结算顺序 = 材料投入顺序（原案 §12）。"),
    # 批25 K1：注册初始礼包 + 初始等级（CakeGame `Global.md:60` `set.NovicesReward`
    # 「注册新手礼包，物品名*数量」+ `:87-89` `OccupationSet.LV/Goods/GoodsNumber`
    # 「注册/初始等级；开局物品；开局物品数量」）。
    # 形态沿用既有 `currencies: []` 之类列表风格：`register_gift` = 列表条目 {item/id,count}；
    # 初始等级单独一个整数键（我们**无既有初始等级配置**——`build_initial_player` 原写死 1，
    # 故新增 `register_level`，不与 `level_cap`（上限）混用；超过上限按上限夹取）。
    # 引擎落点：`commands/register_commands.build_initial_player`（新注册玩家发放 + 定级）。
    "register_gift": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "item": FieldMeta(type="str", ref_target="item", label="物品引用"),
        "id": FieldMeta(type="str", label="物品 ID（等价别名）"),
        "count": FieldMeta(type="int", range_min=1, label="数量"),
    }), label="注册初始礼包",
        help="新注册玩家发放的物品清单（item/count）；缺省 = 不发。"),
    "register_level": FieldMeta(type="int", range_min=1, label="注册初始等级",
                                help="新注册玩家的初始等级（≥1 整数）；缺省 1，"
                                     "超过 settings.level_cap 时按上限夹取。"),
    # 批25 K2：按状态禁用指令（CakeGame `Global.md:143-145` `Limit_ins.ws/iw/fc`
    # 「虚弱状态下禁用的指令 / 野外地图中禁用 / 被强制战斗中禁用（功能名，| 分隔）」）。
    # 形态 = 三个指令名列表（按状态分键，可优化为对象——取「按状态命名、每态一列表」，
    # 与既有 `command_aliases` 的「值列表」风格一致；空/缺省 = 该态不禁用）。
    # 引擎落点：`assembly/runner._state_command_gate`（**沿用既有路由前置判定链**，
    # 与未注册/战斗中/GM 权限同一处 `_run_command_inner`，不散落多套）。
    "command_gates": FieldMeta(type="obj", children={
        "weak": FieldMeta(type="list", element=FieldMeta(type="str"),
                          label="虚弱禁用", help="虚弱状态下禁用的指令名列表。"),
        "wild": FieldMeta(type="list", element=FieldMeta(type="str"),
                          label="野外禁用", help="野外地图（有刷怪行的地图）中禁用的指令名列表。"),
        "forced_battle": FieldMeta(type="list", element=FieldMeta(type="str"),
                                   label="强战禁用",
                                   help="被强制战斗（伏击战 battle_type=ambush）中禁用的指令名列表。"),
    }, label="按状态禁用指令",
        help="按玩家当前状态禁用指定指令：虚弱 / 野外地图 / 被强制战斗中各一列表；空=该态不禁用。"),
    # 批25 K3：指令限流（CakeGame `Global.md:187` `rate_limit.interval/number/object`
    # 「默认 0=不限流」）。形态 = `{interval_sec, count, scope}`；缺省/0 = 不限流。
    # 引擎落点：`assembly/runner._rate_limit_blocked`（**消息层/路由层**前置判定；固定窗口
    # 计数存 `deps` 运行时属性，**不落存档**；时间源 = ctx["now"]（由 deps.dayroll 注入，
    # 可测可控）。scope 支持 player（按玩家，缺省）/ group（按群）。
    # 超限行为：**人话提示**（对齐框架「不静默吞」纪律，玩家可懂；固定窗口防刷屏）。
    "rate_limit": FieldMeta(type="obj", children={
        "interval_sec": FieldMeta(type="int", range_min=0, zero_unlimited=True,
                                  label="窗口秒数",
                                  help="限流窗口长度（秒，≥1）；缺省/0 = 不限流。"),
        "count": FieldMeta(type="int", range_min=0, zero_unlimited=True, label="窗口内次数",
                           help="单个窗口内允许的指令条数（≥1）；缺省/0 = 不限流。"),
        "scope": FieldMeta(type="enum", enum=("player", "group"), label="限流粒度",
                           help="player=按玩家（缺省）；group=按群（全群共享额度）。"),
    }, label="指令限流",
        help="指令级限流：窗口秒数 + 窗口内允许条数 + 粒度（按玩家/按群）；缺省/0 = 不限流。"),
    # 批25 K4：消息分段长度上限（CakeGame `Global.md:46`「每段消息长度上限，超出自动
    # 分段发送，0=不限制」）。**运行时发送分段**——与既有「结构化行 ≤14 全角」的
    # **模板排版门禁**是两件事（那是模板文本规范/静态校验；本项是发送前按上限自动分段，
    # 防 QQ 截断）。缺省/0 = 沿用框架既有单条预算（QQ 4000 字）。
    # 引擎落点：`commands/sender.Sender.default_budget` + `assembly/runner._make_sender`
    # （装配层按 settings 注入；所有经 Sender 出口的文本——含战斗正文——同一预算）。
    "message_chunk_len": FieldMeta(type="int", range_min=0, zero_unlimited=True,
                                   label="消息分段长度上限",
                                   help="发送前每段文本的最大长度（字符，≥1）；超出自动分段发送。"
                                        "缺省/0 = 沿用框架默认单条预算（QQ 4000 字）。"
                                        "注意：这是**运行时发送分段**，与模板排版的行长规范无关。"),
    # 批32 A1：数据包保护（框架 §6.12-25「作者更新中」）。形态 = {enabled}；缺省 false
    # （缺省/未配置 → 行为与现状逐字段一致，零新增拦截）。开启后：
    #   · 玩家（非 GM）发送任何指令 → 人话提示「作者更新中，请稍后再试...」；
    #   · 装配进入游玩前跑**既有包校验**，红拦级问题（含声明但缺模块数据）→ 拒绝进入游玩
    #     并给人话提示（哪个包 / 什么问题 / 去哪改）。
    # 引擎落点：`content/pack_protection.py`（复用既有 `build_pack`/`check_pack` 校验器）
    # + `assembly/bootstrap.py`（进入游玩门禁）+ `assembly/runner.py`（玩家指令拦截）。
    # 只影响运行期门禁，**不影响编辑器本身的编辑功能**（编辑器读取/写入链路不经过本开关）。
    "pack_protection": FieldMeta(type="obj", children={
        "enabled": FieldMeta(type="bool", label="开启数据包保护",
                             help="开启后玩家指令返回「作者更新中」；进入游玩前校验失败（含"
                                  "声明但缺模块数据）会被拒绝。大改版期间开启，发布后关闭。"),
    }, label="数据包保护",
        help="作者更新中：开启期间玩家指令被拦截并提示稍后再试；进入游玩前跑既有包校验，"
             "半成品包被拒绝进入（提示哪个包/什么问题/去哪改）。缺省 false = 不启用。"),
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
    # 批24 G1：任务重置周期——**并入现有 daily**（不新开平行字段）。
    # 值形态：bool（true ≡ {count:1, unit:"日"}，兼容旧包）| {count, unit} | {reset:{count,unit}}。
    # 保留 soft_label=True（daily 可为 bool，泛型类型判定会误拦 → 值形态校验归 quest_models
    # 专项校验器 `_check_daily_reset`）。子字段登记供编辑器表单渲染 + 说明卡。
    "daily": FieldMeta(type="obj", children={
        "count": FieldMeta(type="int", allow_negative=True, range_min=1,
                           label="重置间隔数",
                           help="每 N 个周期可再接取/重置；-1=永不重置；正整数值。"),
        "unit": FieldMeta(type="str", enum=RESET_UNITS, label="重置单位",
                          help="周期单位（年/季/月/周/日/时/分/秒）；缺省语义对齐 daily:true=每日。"),
        "reset": FieldMeta(type="obj", children={}, soft_label=True, label="重置周期（嵌套）"),
    }, soft_label=True, label="每日"),
}

# ---- shop（shop_models 顶层访问器 15；refresh 4 模式×5 key；条目 price 混合支付）----
# 批30（U8 · 2026-09-16）：条目字段元数据按**定稿权威键**收敛——定稿字段表
# `scope/limit/period`（商店定稿 :173-177）为准，旧键 `per_player`/`per_player_period`
# 仅兼容读取（`content/shop_models.py:108-110` + `core/shop.py:536-549`），**不进入编辑器
# 可写字段**（避免写入旧键）。枚举与 `shop_models.SHOP_*` 同源（此处不 import 以免
# 反向依赖：field_meta 被 shop_models 依赖）。宽度/类型对齐 shop_models 访问器。
SCOPES: Tuple[str, ...] = ("global", "personal")            # shop_models.SCOPES
LIMIT_PERIODS: Tuple[str, ...] = ("day", "week", "month")   # shop_models.LIMIT_PERIODS
SHOP_TYPES: Tuple[str, ...] = ("normal", "npc", "reputation", "event", "blackmarket")
REFRESH_MODES: Tuple[str, ...] = ("daily", "weekly", "once", "none")
SHOP_MIGRATION_HELP = (
    "旧字段 per_player 自动映射为 scope=personal + limit，per_player_period 映射为 period；"
    "本编辑器只写定稿键 scope/limit/period（保存时按定稿键落盘）"
)
SHOP_REFRESH_CHILDREN: Dict[str, FieldMeta] = {
    "mode": FieldMeta(type="str", enum=REFRESH_MODES, label="刷新模式",
                      help="daily 每日 / weekly 每周 / once 时间窗内一次 / none 永不刷新（缺省）"),
    "hour": FieldMeta(type="int", label="刷新小时", unit="时",
                      help="daily/weekly 的刷新时刻 0~23（缺省 5=05:00）"),
    "weekday": FieldMeta(type="int", label="刷新星期",
                         help="weekly 的星期 1~7（1=周一，缺省 1）"),
    "start": FieldMeta(type="str", label="开始时间",
                       help="once 时间窗开始（格式 2026-09-01 00:00）"),
    "end": FieldMeta(type="str", label="结束时间",
                     help="once 时间窗结束（格式 2026-09-07 23:59）"),
}
SHOP_ITEM_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    # 批32 C1：展示层引用标注（既有引用扫描覆盖「商店商品 → 物品」；type 仍 str，校验不变）。
    "item": FieldMeta(type="str", ref_target="item", label="物品引用",
                      help="items.json 物品 ID（显示按名字、存储按 ID）"),
    "price": FieldMeta(type="obj", children={}, soft_label=True, label="价格（混合支付）",
                       help="整数覆盖价，或 {货币键:数量} 混合支付对象；缺省=物品基准价"),
    "currency": FieldMeta(type="str", label="货币覆盖",
                          help="条目级货币（settings.currencies 键）；缺省=商店默认货币"),
    "scope": FieldMeta(type="str", enum=SCOPES, label="商品范围",
                       help="global=全服共享库存（默认）/ personal=每人独立限购。" + SHOP_MIGRATION_HELP),
    "stock": FieldMeta(type="int", label="全服库存",
                       help="global 侧库存，0=无限；仅 scope=global 生效"),
    "refresh": FieldMeta(type="obj", children=SHOP_REFRESH_CHILDREN, soft_label=True,
                         label="库存刷新",
                         help="条目级刷新覆盖商店级；仅 global 侧"),
    "limit": FieldMeta(type="int", label="个人限购",
                       help="personal 侧每周期可买上限，0=不限；仅 scope=personal 生效。"
                            "旧键 per_player 映射到此"),
    "period": FieldMeta(type="str", enum=LIMIT_PERIODS, label="限购周期",
                        help="个人限购清零周期 day/week/month；旧键 per_player_period 映射到此"),
    "reputation_required": FieldMeta(type="obj", children={}, soft_label=True, label="声望门槛",
                                     help="{level:N} 条目级声望门槛（更严于商店级）"),
    "min_level": FieldMeta(type="int", label="等级门槛",
                           help="条目级等级门槛，0=不限"),
    "discount": FieldMeta(type="int", label="折扣",
                          help="0~100 减价百分比；原价划线展示"),
    "sold_out_once": FieldMeta(type="bool", label="售罄后下架",
                               help="true=售出后永久下架，刷新不恢复（仅 global）"),
}
SHOP_FIELDS: Dict[str, FieldMeta] = {
    "id": FieldMeta(type="str", required=True, label="商店 ID"),
    "name": FieldMeta(type="str", required=True, label="名称"),
    "icon": FieldMeta(type="str", label="图标"),
    "type": FieldMeta(type="str", enum=SHOP_TYPES, label="类型",
                      help="normal 普通 / npc NPC 店 / reputation 声望 / event 活动 / blackmarket 黑市"),
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
    "price_fluctuation": FieldMeta(type="int", label="价格波动", unit="%",
                                   help="黑市价格随机浮动 ±%（0~50，0=固定价）"),
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
# 批25 H1：NPC 功能次数上限（CakeGame `Ext_NPC_Info与Function.md:150-151`
# `Day_number`/`User_number`「每玩家每日 / 累计触发上限（进度存 UserData 区段
# `NPC_Day_number.Function.<功能名>`，按日期键；0/空=不限）」）。
# 形态 = `interactions[]` 条目上的两个可选整数（**沿用既有条目结构，不新开层级**）。
# 引擎落点：`core/npc.dispatch_action` 调该功能前判定、成功后记账；进度按既有玩家态
# 口径（persistent_state 的 `npc_delivered` 域）存 `limit_day:<功能名>` / `limit_total:<功能名>`；
# 每日以日期键（dayroll 日界，settings.refresh_time 缺省 05:00）重置（与 give_item daily 同刻）。
# 与既有 `repeat`（give_item 行为级 once/daily）分工：`repeat` 管动作行为，本组管**额度**。
#
# 批25 H2：NPC 功能收费多通道（CakeGame `Ext_NPC_Info与Function.md:93`
# `consume_gold / consume_diamond / consume_goods`「选用该功能需支付的代价」）。
# **沿用既有 `interactions[].cost` 对象扩展子键**（不新开平行字段）：既有 `coins` 保留；
# 新增 `gem`/`diamond` 两个常见货币通道（键=settings.currencies[].id，实际任意已配置
# 货币键都按同一规则扣除）+ `items:[{item,count}]` 物品通道。
# 引擎落点：`core/npc._check_cost`（校验先行、不足给人话）→ `_apply_cost`（复用既有
# `ctx["currencies"]` 与物品出入库 hook `remove_item`/`add_item`/`count_item`，与
# dungeon entry_cost 同口径，全量校验后一次扣除 = all-or-nothing）。
NPC_INTERACTION_COST_CHILDREN: Dict[str, FieldMeta] = {
    "coins": FieldMeta(type="int", range_min=0, label="金币",
                       help="金币通道：需支付的数量（缺省/0 = 该通道免费）。"),
    "gem": FieldMeta(type="int", range_min=0, label="宝石",
                     help="宝石通道（货币键 `gem`）；需为已配置货币。缺省/0 = 不扣。"),
    "diamond": FieldMeta(type="int", range_min=0, label="钻石",
                         help="钻石通道（货币键 `diamond`）；需为已配置货币。缺省/0 = 不扣。"),
    "items": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "item": FieldMeta(type="str", label="物品引用"),
        "id": FieldMeta(type="str", label="物品 ID（等价别名）"),
        "count": FieldMeta(type="int", range_min=1, label="数量"),
    }), label="物品通道",
        help="需交付的物品清单（item/count）；不足则不执行、不扣任何一项。"),
}
NPC_INTERACTION_CHILDREN: Dict[str, FieldMeta] = {
    # 功能名（进度键身份）：显式声明则用；缺省由引擎按动作+菜单文案/物品指纹派生。
    "key": FieldMeta(type="str", label="功能标识",
                     help="该功能在玩家进度里的稳定标识；缺省按动作+菜单文案派生。"
                          "改动文案/标识会重置该功能的额度计数。"),
    "daily_limit": FieldMeta(type="int", range_min=1, label="每日次数上限",
                             help="每玩家每日可调用该功能的次数（≥1 整数）；缺省 = 不限。"
                                  "按 dayroll 日界（settings.refresh_time，缺省 05:00）每日重置。"),
    "total_limit": FieldMeta(type="int", range_min=1, label="累计次数上限",
                             help="每玩家累计可调用该功能的次数（≥1 整数）；缺省 = 不限。"),
    # 收费（多通道）：既有 coins + 新增 gem/diamond/items（同结构扩展，供编辑器表单）。
    "cost": FieldMeta(type="obj", children=NPC_INTERACTION_COST_CHILDREN,
                      label="功能费用"),
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
    "interactions": FieldMeta(type="list",
                              element=FieldMeta(type="obj",
                                                children=NPC_INTERACTION_CHILDREN),
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
        # 批32 C1：展示层引用标注——使既有引用扫描覆盖「地图刷怪行 → 怪物」，
        # 条目级「📍未使用」角标据此不再把已放入地图的怪物误标（type 仍 str，校验不变）。
        "enemy": FieldMeta(type="str", ref_target="enemy", label="怪物引用"),
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
        # 批24 E2：主动遭遇（CakeGame `Config_Map.md:68/69`「主动触发强制战斗的概率」
        # +「触发后进攻数量随机区间」）。语义 = **进入/移动结算时按概率主动触发战斗**，
        # 与 `count`（同场存量）/`signal`/`hidden_boss` 都不同。挂在刷怪行上（不新造层级）。
        "encounter_chance": FieldMeta(type="int", range_min=0, range_max=100, unit="%",
                                      label="主动遭遇概率",
                                      help="该怪组在进入本图时主动触发强制战斗的概率（0-100）；"
                                           "0/缺省 = 不主动触发。"),
        "encounter_count_min": FieldMeta(type="int", range_min=1, label="主动遭遇最少参战数",
                                          help="触发后参战怪数随机区间下限（缺省=行 count）。"),
        "encounter_count_max": FieldMeta(type="int", range_min=1, label="主动遭遇最多参战数",
                                          help="触发后参战怪数随机区间上限（缺省=下限；min>max 红拦）。"),
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
# 批24 E3：进图消耗/门票信物（maps[].entry_cost）——CakeGame `Config_Map.Consume`
# 「进图消耗（INI 节式）：TRUE=进入时扣除（门票）/ FALSE=仅须持有」。形态取
# `{items:[{item,count}], consume:bool}`：items 支持多件物品（旧 dungeon.entry_item
# 只有单件且恒扣，无法表达「仅校验持有」）；consume 缺省 true（= 既有 entry_item 扣除语义）。
ENTRY_COST_ITEM_CHILDREN: Dict[str, FieldMeta] = {
    "item": FieldMeta(type="str", label="物品引用"),
    "count": FieldMeta(type="int", range_min=1, label="数量"),
}
ENTRY_COST_CHILDREN: Dict[str, FieldMeta] = {
    "items": FieldMeta(type="list",
                       element=FieldMeta(type="obj", children=ENTRY_COST_ITEM_CHILDREN),
                       label="所需物品"),
    "consume": FieldMeta(type="bool", label="进入时扣除",
                         help="true=进入时扣除（门票）；false=仅校验持有，不扣。缺省 true。"),
}
DUNGEON_DROP_ENTRY_CHILDREN: Dict[str, FieldMeta] = {
    # drops.normal/boss 普通掉落行（细化_2a1d §2.4 样例 {item,chance}）
    # 批32 C1：展示层引用标注（既有引用扫描覆盖「副本掉落 → 物品」；type 仍 str，校验不变）。
    "item": FieldMeta(type="str", ref_target="item", label="掉落物品"),
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
    # 批24 E5：副本层间推进（CakeGame `ext_smallcopymap副本组.md:77`「击杀数量传送阈值」）。
    # 语义 = 副本内累计击杀达阈值 → 按 dungeon.maps 顺序序列推进到下一层；缺省无此机制。
    "advance_on_kill_count": FieldMeta(type="int", range_min=1, label="击杀推进阈值",
                                       help="副本内累计击杀达到该数后，按 maps 顺序推进到下一层"
                                            "（≥1 整数；缺省 = 不按击杀推进，维持通道走图）。"),
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
    # 批25 I1：计入总数/完成度（CakeGame `成就系统.md:88` `AddTrue`「计入总数（默认 TRUE）」）。
    # 语义 = 完成度统计的分母**只计 counted=true 的成就**（隐藏/彩蛋成就不拉低「全成就」进度）；
    # `counted=false` 的成就照常可达成与发奖，仅不参与完成度。与 `hidden`（是否隐藏）**正交**
    # ——他们两者是独立两列（`成就系统.md:88,89`），隐藏 ≠ 不计入。
    # 引擎落点：`core/achievements.achievement_progress`（分母/分子均按 counted 过滤）+
    # `commands/achievement_commands.cmd_achievements` 的列表头完成度。
    "counted": FieldMeta(type="bool", label="计入总数",
                         help="完成度统计是否计入该成就（缺省 true）；false 的成就照常可达成、"
                              "照常发奖，只是不拉低「全成就」进度。"),
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
#
# 批13 C（审计 ①-4-23 / 战斗数值层定稿 L189/L244/L366）：formula.json 为战斗数值唯一
# 配置源；上述 `damage/hit/crit/block/...` 公式段此前只有 stat_map 登记 → 段落编辑无字段
# 口径。本批按定稿逐段补登记（含 range/enum）；**仅展示层**：段值形态仍是 formula/obj，
# 校验语义不变（数值超范围由战斗数值专项校验器提示，不在此红拦）。
def _formula_sections() -> Dict[str, FieldMeta]:
    """战斗数值公式段字段表（展示层；键名/层级照 战斗数值层设计定稿 §5.1）。"""
    return {
        # §5.1 伤害通道（L189）
        "damage": FieldMeta(type="obj", label="伤害通道", children={
            "base_attack_mult": FieldMeta(type="number", range_min=0, label="基础攻击倍率"),
            "rng": FieldMeta(type="list", element=FieldMeta(type="number"),
                             label="乱数区间[下,上]"),
            "floor_mode": FieldMeta(type="enum", enum=("channel_end", "per_segment"),
                                    label="取整时机"),
            "deep_floor": FieldMeta(type="bool", label="深层向下取整"),
        }),
        "hit": FieldMeta(type="obj", label="命中", children={
            "k": FieldMeta(type="number", range_min=0.05, range_max=1, label="K_HIT 系数"),
            "cap_min": FieldMeta(type="int", range_min=0, range_max=100, label="命中率下限%"),
            "cap_max": FieldMeta(type="int", range_min=0, range_max=100, label="命中率上限%"),
        }),
        "crit": FieldMeta(type="obj", label="会心", children={
            "p_coef": FieldMeta(type="number", range_min=0, label="会心率系数"),
            "cap": FieldMeta(type="int", range_min=0, range_max=100, label="会心率封顶%"),
            "tiers": FieldMeta(type="obj", label="会心档倍率", children={
                "high": FieldMeta(type="number", range_min=1.0, range_max=3.0, label="高会心倍率"),
                "mid": FieldMeta(type="number", range_min=1.0, range_max=3.0, label="中会心倍率"),
                "low": FieldMeta(type="number", range_min=1.0, range_max=3.0, label="低会心倍率"),
            }),
            "tier_p": FieldMeta(type="list", element=FieldMeta(type="number"),
                                label="降档边界[a,b]"),
            "crit_mult_up": FieldMeta(type="obj", label="超会心档位加成", children={
                "lv1": FieldMeta(type="number", range_min=0, label="Lv1 加成"),
                "lv2": FieldMeta(type="number", range_min=0, label="Lv2 加成"),
                "lv3": FieldMeta(type="number", range_min=0, label="Lv3 加成"),
            }),
            # 批19 #9：按 formula_loader 实际消费面补齐（E19/E21，此前未登记）。
            "negative_crit": FieldMeta(type="number", label="负会心倍率",
                                       help="会心系数为负（负会心）时的伤害倍率修正（E19）。"),
            "elem_crit_step": FieldMeta(type="number", range_min=0, label="元素会心步进",
                                        help="元素会心逐档步进值（E21）。"),
        }),
        "block": FieldMeta(type="obj", label="格挡", children={
            "k": FieldMeta(type="number", range_min=0, label="格挡系数"),
            "cap": FieldMeta(type="int", range_min=0, range_max=100, label="格挡率封顶%"),
            "magic_ignores": FieldMeta(type="bool", label="魔法无视格挡"),
            "halve_after_block": FieldMeta(type="bool", label="格挡后减半"),
        }),
        "defense": FieldMeta(type="obj", label="防御减伤", children={
            "mode": FieldMeta(type="enum", enum=("ratio", "subtract"), label="减伤模式"),
            "k": FieldMeta(type="number", range_min=0, label="减伤系数"),
            "pierce_types": FieldMeta(type="obj", soft_label=True, label="打类型破防"),
        }),
        "weakness": FieldMeta(type="obj", label="弱点", children={
            "type_mult": FieldMeta(type="number", range_min=0, label="类型弱点倍率"),
            "element_mult": FieldMeta(type="number", range_min=0, label="元素弱点倍率"),
        }),
        "weapon_type_mult": FieldMeta(type="obj", soft_label=True, label="武器类型倍率"),
        "type_affinity": FieldMeta(type="obj", label="攻击类型倾向", children={
            "enabled": FieldMeta(type="bool", label="启用倾向"),
            "blunt_pierce": FieldMeta(type="number", range_min=0, range_max=1, label="打击破防"),
            "thrust_hit": FieldMeta(type="number", range_min=0, label="突刺命中加成"),
            "slash_crit": FieldMeta(type="number", range_min=0, label="斩击会心加成"),
            "magic_ignore_block": FieldMeta(type="bool", label="魔法无视格挡"),
        }),
        "elements": FieldMeta(type="obj", soft_label=True, label="元素注册表"),
        "luck": FieldMeta(type="obj", label="幸运修正", children={
            "enhance_rate": FieldMeta(type="number", range_min=0, label="强化成功率修正"),
            "effect_prob": FieldMeta(type="number", range_min=0, label="效果触发概率修正"),
            "max_mod": FieldMeta(type="number", range_min=0, label="修正上限"),
        }),
        "derived": FieldMeta(type="obj", label="技能派生", children={
            "max_total_mult": FieldMeta(type="number", range_min=0, label="派生倍率封顶"),
        }),
        "power": FieldMeta(type="obj", label="威力上限", children={
            "max": FieldMeta(type="int", range_min=0, range_max=99999, label="威力滑条上限"),
            "formula_max": FieldMeta(type="int", range_min=0, range_max=99999,
                                     label="公式路径上限"),
        }),
        "effects_link": FieldMeta(type="obj", label="效果拦截链", children={
            "intercept_order": FieldMeta(type="list", element=FieldMeta(type="str"),
                                         label="拦截顺序"),
            "pierce_cap": FieldMeta(type="number", range_min=0, range_max=1, label="穿透封顶"),
        }),
        "death_check": FieldMeta(type="obj", label="死亡判定", children={
            "mutual_kill_result": FieldMeta(type="enum", enum=("draw", "player_loss"),
                                            label="互杀结果"),
            "mutual_kill_basis": FieldMeta(type="enum", enum=("order", "hp_ratio"),
                                           label="互杀判定基准"),
            "no_target_action": FieldMeta(type="enum", enum=("fallback", "skip"),
                                          label="后手无目标处理"),
            "boss_end_immediate": FieldMeta(type="bool", label="BOSS 死亡立刻结束"),
        }),
        # §八 伤害构成统计 / dummy_log（L366）
        "stats_collector": FieldMeta(type="obj", label="伤害统计", children={
            "enabled": FieldMeta(type="bool", label="启用收集"),
            "dummy_log_size": FieldMeta(type="int", range_min=0, range_max=20,
                                        label="木桩记录保留次数（0=关）"),
            "dummy_realtime": FieldMeta(type="bool", label="木桩实时摘要"),
        }),
    }


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
    # 批19 #9（审计 A12 / ①-4-23）：formula.json 里包实际存在、此前框架侧无中文名的键，
    # 按 `core/formula_loader.py` 的**实际消费面**逐键登记（不臆造）。
    #   · damage_base / heal_rate：既有包普遍存在的「JS 公式风格」兼容键；当前 Python 侧
    #     `load_formula_params` **未消费**（读取器只消费段参数与 stat_map），保留为兼容键。
    #   · battle_position 段：`BattlePositionParams`（方位战斗 v0.6）三参数，真实消费。
    #   · monster_def_rate：O1 怪物防御率，真实消费（`load_formula_params` L164）。
    "damage_base": FieldMeta(
        type="formula", label="伤害基础公式",
        help="兼容保留键（JS 公式风格）。当前 Python 侧 formula_loader 不消费它——"
             "战斗数值以 damage/hit/crit/... 段参数与 stat_map 为准；保留以免旧包报错。"),
    "heal_rate": FieldMeta(
        type="formula", label="治疗量公式",
        help="兼容保留键（JS 公式风格）。当前 Python 侧 formula_loader 不消费它；"
             "治疗效果以 effects 的数值口径与公式引擎表达式为准。"),
    "monster_def_rate": FieldMeta(
        type="number", range_min=0, label="怪物防御率",
        help="怪物防御率（O1，待策划裁决；工程默认 1.0）。真实消费点 = "
             "core/formula_loader.py 装配 DamageFormulaParams.monster_def_rate。"),
    "battle_position": FieldMeta(
        type="obj", label="方位战斗参数",
        children={
            "break_base_damage": FieldMeta(
                type="number", range_min=0, label="基准伤害",
                help="破坏力公式 √ 括号内的减项（N1 数值阶段）。"),
            "break_sqrt_coef": FieldMeta(
                type="number", range_min=0, label="根号系数",
                help="破坏力公式 break_delta = break_power + 系数 × √(max(0, basis − 基准伤害))。"),
            "broken_part_mult": FieldMeta(
                type="number", range_min=0, label="已破部位增伤乘区",
                help="已破部位常驻增伤乘区（方位战斗 v0.6 §二.3），缺省 1.0。"),
        }),
    **_formula_sections(),
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
    "mode": FieldMeta(type="enum", enum=MODE_VALUES, default="full", label="模块模式",
                      help="合成 / 炼金启用路径三态（批39）：full=三层漏斗（合成 + 炼金 + "
                           "深度炼金）；simple=**仅合成层**（公用；无炼金层/深度炼金/职业等级/"
                           "特性/能量条）；off=关闭（合成层亦拒绝）。打造路径另由 "
                           "settings.deep_craft.enabled 控制。"),
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
    return FieldMeta(
        type="obj", children=ALCHEMY_SETTINGS_FIELD_DEFS, label="炼金 / 合成",
        help="合成与炼金的启用路径（批39）：由「模块模式」三态声明推导——"
             "full=三层漏斗（合成 + 炼金 + 深度炼金）；simple=仅合成层（公用；玩家可只启用合成）；"
             "off=关闭。深度打造另由「深度打造 ▸ 是否启用深度打造」控制；"
             "合成是打造与炼金的公用层。")


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
        "revive", "message_key", "skill",
    )),
    ("数值", (
        "power", "break_power", "mp_cost", "hp_cost", "cooldown", "hits", "level",
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

# =====================================================================================
# 子字段结构由 CHILD_SPEC 提供（批B）；中文名/说明由包 field_meta.json 覆盖。
#   · 表形态 {子键: 中文名 | {孙键: ...}}，递归到任意深度；list 元素对象的 children 同样覆盖；
#   · children 里**已声明**的键 → 只补 label（type/required/enum/children 原样保留）；
#   · 真实内容包出现、children **未登记**的键 → 补一个 soft_label=True 的「纯展示子字段」
#     （validator 对 soft_label 立即 return → 校验语义零变化），避免界面留裸键；
#   · **动态键空间**（键名由内容定义：ai.states.<状态名> / settings.slot_defs.<部位> /
#     consume_marks.<印记> / element_req.<元素> / job_tier_map.<档位> 等）**不猜键名**，
#     保持原始键显示，登记于批报「待确认清单」。
# 命名依据：stats.json（hp 生命/mp 法力/…）、docs/m2_shared_contract（enemies 八段 + AI）、
# docs/m3_shared_contract（zone_change）、docs/m13_6a~6c（skills/jobs/skill_chains）、
# docs/veinborn/03_schema_修正稿.md、data/gear_stats.GEAR_LABELS_ZH；
# 术语冲突按 docs/编辑器重写_需求与约束.md §六（mp 法力 / con 体质 / mag 法强 / pv 防护值）。
def _soft_display(label: str, ftype: str = "",
                  children: Optional[Mapping[str, FieldMeta]] = None,
                  help: Optional[str] = None) -> FieldMeta:
    """纯展示子字段（soft_label=True → 泛型校验短路、永不红拦；仅供编辑器显示中文名/说明）。

    批4.6 补：默认 type 留空（=「类型未登记」）而非 "str"——只有中文名、没有类型依据的
    节点不得声称是文本，说明卡/表单据此改用**实际值**推断真实类型（实机问题①根因）。
    显式传 ftype 的调用（如 _soft_display("每回合破坏值", "int")）不受影响。
    """
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


def _from_child_spec(spec: Any) -> Any:
    """结构 spec → 装饰器认的「空文案」子结构表（批B：中文名已下放到包声明）。

    spec 表示法：`None` 叶子 / 嵌套 dict 容器 / `{"__list__": …}` list-of-obj 容器。
    """
    if spec is None:
        return ""
    if isinstance(spec, Mapping):
        if "__list__" in spec:
            return _soft_list("", {k: _from_child_spec(v)
                                   for k, v in spec["__list__"].items()})
        return {k: _from_child_spec(v) for k, v in spec.items()}
    return ""


def _child_spec(module: str) -> Optional[Mapping[str, Any]]:
    """模块子字段结构表（框架只保留结构；展示文案由包 `field_meta.json` 覆盖）。"""
    spec = CHILD_SPEC.get(module)
    return _from_child_spec(spec) if spec is not None else None


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
) -> Tuple[Dict[str, str], Tuple[str, ...]]:
    """(分组键→组, 分组顺序) 二元组；组显示名已在批B 下放到包 `field_meta.json`。

    `labels` 参数保留（批B 之前传入组显示名表），此处不再使用。
    """
    groups: Dict[str, str] = {}
    order: Tuple[str, ...] = ()
    for group, keys in defs:
        order = order + (group,)
        for key in keys:
            groups.setdefault(key, group)
    return groups, order


# 批B：模块**分组结构**（分组键→组 + 顺序）仍归框架；组显示名已下放到包
# content/<包>/field_meta.json 的 group_labels。
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

ITEMS_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", (
        "id", "name", "type", "slot", "bind", "usable", "job_restrict", "use_level",
        "quality", "rarity", "material_tier", "source", "awaken", "seed",
        "max_hold",  # 批26 α2：获取数量上限（items∪equipment 同库）
        "handedness",  # 批38 ③：手数（单手/双手；装备基本属性）
    )),
    ("stats", (
        "price", "atk", "def", "dfn", "foc", "hp", "agi", "mp",
        "elements", "base_effects",
        "affinities",  # 批38 ④：材料/图纸相性值 {相性id: 数值}
        # 批41：材料打造字段（等级/品质/成本）——决定装备等级与品质经验。
        "material_level", "material_quality", "craft_cost",
        *GEAR_FLAT_KEYS, *GEAR_PCT_KEYS, *GEAR_COMBAT_KEYS,
        # 批43：占位词条（冷却缩减）——登记可见、不接引擎。
        *GEAR_PLACEHOLDER_KEYS,
    )),
    # 批26 α组（装备侧）：装备附加字段归「效果」分组（grant_skills/skill_amp/
    # attack_override/job_override）——沿用既有分组（不开新分组键，模块分组数
    # 仍守 2~4 不变式；组显示名归包声明）。
    ("effects", ("effects", "traits", "grant_skills", "skill_amp",
                 "attack_override", "job_override",
                 # 批41：图纸字段（深度打造模板；图纸是物品的一种）。
                 "blueprint_grade", "blueprint_output", "blueprint_slot",
                 "blueprint_recipe", "blueprint_level_band", "blueprint_material_slots",
                 "blueprint_fixed_stats", "blueprint_random_stat_count",
                 "blueprint_fixed_set_affix", "blueprint_random_set_affix_count",
                 "blueprint_random_set_affix_pool", "blueprint_passive",
                 "blueprint_learn", "blueprint_cost_cap")),
    ("text", ("desc", "brief", "detail")),
)

EQUIPMENT_FIELD_GROUPS: Dict[str, str] = {
    _k: _g for _g, _keys in ITEMS_GROUP_DEFS for _k in _keys
}
EQUIPMENT_FIELD_GROUPS["excludes"] = "base"
EQUIPMENT_GROUP_ORDER: Tuple[str, ...] = tuple(_g for _g, _ in ITEMS_GROUP_DEFS)

MAPS_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "battle", "revert", "safe_zone", "hidden", "camp", "camp_name")),
    ("ranges", ("min", "max", "lower", "upper", "reset", "mechanics")),
    ("refs", ("enemy_pool", "monsters", "exits", "respawn_point", "npcs",
              "gate_guard", "gather_points", "dungeon_entrances", "weather_pool",
              "entry_cost")),
    ("text", ("desc",)),
)

QUEST_GROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "type", "main", "zone", "repeatable", "desc")),
    ("conditions", ("conditions", "unlock_chain", "consume", "filter")),
    ("reward", ("reward", "bonus", "daily", "board", "timed")),
    ("refs", ("npc",)),
)


ENEMIES_FIELD_GROUPS, ENEMIES_GROUP_ORDER = \
    _group_declaration(ENEMIES_GROUP_DEFS, {})
ITEMS_FIELD_GROUPS, ITEMS_GROUP_ORDER = \
    _group_declaration(ITEMS_GROUP_DEFS, {})
MAPS_FIELD_GROUPS, MAPS_GROUP_ORDER = \
    _group_declaration(MAPS_GROUP_DEFS, {})
QUEST_FIELD_GROUPS, QUEST_GROUP_ORDER = \
    _group_declaration(QUEST_GROUP_DEFS, {})


# =====================================================================================
# 批20 C：**二级分组（子页签）**结构声明——只有「一个分组」的长模块（效果 / 状态 / 派生链 /
# 行动 / 职业 / NPC / 商店）在这里把字段再分一层；编辑器把子分组渲染成**二级页签**（既有
# `button.gtab` 机制扩展），长模块首屏不再一条长滚动。
#   · 结构（键 → 子分组 + 顺序）归框架；**显示名归框架默认 + 包覆盖**（`subgroup_labels`，
#     与 `module_catalog.label` / 模块 `module_labels` 同一「框架默认 + 包声明覆盖」口径）。
#   · 与 group_order/group_labels 同属「编辑器显示维度」，不影响校验（校验器只读 fields）。
# =====================================================================================
def _subgroup_declaration(
    defs: Tuple[Tuple[str, Tuple[str, ...]], ...],
) -> Tuple[Dict[str, str], Tuple[str, ...]]:
    """(字段键→子分组, 子分组顺序) 二元组（与 `_group_declaration` 同形态）。"""
    return _group_declaration(defs, {})


# 效果：标识 / 数值 / 引用 / 行为 / 文本（字段键取自框架 `effects_fields` 登记）。
EFFECTS_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "type")),
    ("numeric", ("power", "duration", "probability", "max_stack", "value", "pct",
                 "turns", "count", "skip_turn", "part_break_per_tick",
                 "amount_min", "amount_max")),
    ("refs", ("currency", "skill", "level", "require_status", "apply_status",
              "require_mark", "apply_mark", "status", "stat", "mark", "marks_on",
              "target")),
    ("behavior", ("actions", "patch", "tick", "trigger", "filter", "class",
                  "control_type", "polarity", "ignore_shield", "ignore_immune")),
    ("text", ("desc",)),
)
EFFECTS_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识", "numeric": "数值与持续", "refs": "引用与目标",
    "behavior": "行为与触发", "text": "文本",
}
# 状态：标识 / 持续 / 效果 / 文本。
STATUSES_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "type", "decay", "max_stack")),
    ("duration", ("duration",)),
    ("effects", ("effects", "on_enter", "on_tick", "on_expire", "on_dodge_effects",
                 "damage_mult")),
    ("text", ("desc", "description")),
)
STATUSES_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识", "duration": "持续", "effects": "效果与触发", "text": "文本",
}
# 派生链：标识 / 链结构（连段数、后继、步骤、行动与效果）。
SKILL_CHAINS_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "type", "trigger_skill", "max_combo",
              "max_combo_behavior", "job_scope")),
    ("chain", ("next", "steps", "actions", "effects")),
)
SKILL_CHAINS_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识", "chain": "连段结构",
}
# 行动：标识 / 数值 / 行为 / 引用。
ACTION_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "kind", "type", "attack_type", "element", "intent", "tags")),
    ("numeric", ("power", "break_power", "cost", "cool", "cooldown", "recovery",
                 "weight", "probability", "roar", "charge_turns", "hungry")),
    ("behavior", ("position_rule", "air_policy", "air_drop", "chain", "armor",
                  "interrupt", "condition", "trigger_limit", "charge_armor",
                  "reveal_condition", "preview", "preview_chain")),
    ("refs", ("effects", "skill", "require_status", "apply_status", "apply_mark")),
)
ACTION_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识与类型", "numeric": "数值", "behavior": "行为", "refs": "引用",
}
# 职业：标识 / 成长 / 形态变换 / 转职前置 / 进阶继承。
JOBS_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "difficulty", "playstyle", "recommended_newbie", "is_basic")),
    ("tags", ("mechanic_tags", "weapon_types", "resource_axes")),
    ("growth", ("growth",)),
    ("transform", ("transform",)),
    ("advance", ("advance",)),
    ("inherit", ("inherit",)),
    ("text", ("description",)),
)
JOBS_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识与定位", "tags": "标签与武器", "growth": "成长率",
    "transform": "形态变换", "advance": "转职前置", "inherit": "进阶继承", "text": "文本",
}
# NPC：标识 / 对话与交互 / 关联引用。
NPC_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "icon", "map", "type", "desc", "visible")),
    ("dialog", ("dialogues", "interactions", "tutorials")),
    ("refs", ("quests", "shop_refs", "intel_refs", "dealer", "repair")),
)
NPC_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识", "dialog": "对话与交互", "refs": "关联引用",
}
# 商店：标识 / 规则 / 货架。
SHOP_SUBGROUP_DEFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("base", ("id", "name", "icon", "type", "currency", "visible", "desc")),
    ("rules", ("level_required", "reputation_required", "open_condition", "refresh",
               "price_fluctuation", "listing_count")),
    ("items", ("items", "pool")),
)
SHOP_SUBGROUP_LABELS: Dict[str, str] = {
    "base": "标识", "rules": "门槛与刷新", "items": "货架",
}
EFFECTS_FIELD_SUBGROUPS, EFFECTS_SUBGROUP_ORDER = \
    _subgroup_declaration(EFFECTS_SUBGROUP_DEFS)
STATUSES_FIELD_SUBGROUPS, STATUSES_SUBGROUP_ORDER = \
    _subgroup_declaration(STATUSES_SUBGROUP_DEFS)
SKILL_CHAINS_FIELD_SUBGROUPS, SKILL_CHAINS_SUBGROUP_ORDER = \
    _subgroup_declaration(SKILL_CHAINS_SUBGROUP_DEFS)
ACTION_FIELD_SUBGROUPS, ACTION_SUBGROUP_ORDER = \
    _subgroup_declaration(ACTION_SUBGROUP_DEFS)
JOBS_FIELD_SUBGROUPS, JOBS_SUBGROUP_ORDER = \
    _subgroup_declaration(JOBS_SUBGROUP_DEFS)
NPC_FIELD_SUBGROUPS, NPC_SUBGROUP_ORDER = \
    _subgroup_declaration(NPC_SUBGROUP_DEFS)
SHOP_FIELD_SUBGROUPS, SHOP_SUBGROUP_ORDER = \
    _subgroup_declaration(SHOP_SUBGROUP_DEFS)


# ---- 派生条件的主体声明（批5 条件行编辑器；键名不写死，缺省按实际值推断）----
# 条件结构 = {主体: {比较符: 值}} 或 {主体: {二级键: {比较符: 值}}}；and/or 为逻辑组合主体。
# 批29 α4：任务状态枚举（镜像 core/combo.QUEST_STATES——G0 单向依赖：content 层不 import
# core；语义实现单点在 core/combo.evaluate_condition，此处只供编辑器枚举与校验白名单）。
CHAIN_QUEST_STATES: Tuple[str, ...] = ("in_progress", "completed", "not_started")

CHAIN_CONDITION_SUBJECTS: Dict[str, ConditionSubject] = {
    "count": ConditionSubject(label="连段计数", ops=("eq", "min", "max")),
    "self_marks": ConditionSubject(label="自身印记", key_ref="mark", ops=("eq", "min", "max")),
    "target_marks": ConditionSubject(label="目标印记", key_ref="mark", ops=("eq", "min", "max")),
    "self_status": ConditionSubject(label="自身状态", value_ref="status", ops=("has",)),
    "target_hp_pct": ConditionSubject(label="目标生命百分比", ops=("min", "max")),
    # 批29 α4：补齐 level/job/quest 三类——形态同族（值/集合/两级键），
    # 求值单点在 core/combo.evaluate_condition，此处只声明展示与控件。
    "level": ConditionSubject(label="玩家等级", ops=("eq", "min", "max")),
    "job": ConditionSubject(label="职业", value_ref="job", ops=("in", "not_in")),
    "quest": ConditionSubject(label="任务进度", key_ref="quest",
                              ops=("state",), value_enum=(CHAIN_QUEST_STATES)),
    "and": ConditionSubject(label="且（全部满足）", combine=True),
    "or": ConditionSubject(label="或（任一满足）", combine=True),
}

# ---- 技能模块的「关联分区」声明（批5 派生界面；编辑器只按声明渲染，不写死模块/字段名）----
SKILLS_ASSOCIATIONS: Tuple[AssociationMeta, ...] = (
    AssociationMeta(
        module="skill_chains", field="trigger_skill",
        label="派生 · 本技能触发的链",
        hint="以下派生链以本技能为触发技；可逐步骤改派生条件、派生技能、派生消耗、"
             "数值覆盖、优先级、模式、霸体。保存写入派生链模块（校验 + 原子写 + 备份）。"),
    AssociationMeta(
        module="skill_chains", field="steps[].to",
        label="派生 · 本技能为派生目标", editable=False,
        hint="以下派生链的某个步骤以本技能为派生目标（只读摘要；点「打开」到派生链条目编辑）。"),
)

# ---- action（AI 字段里的条件/触发上限补充；deeper 由包声明覆盖）----


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
        # 批18：type 用 F_EFFECT_TYPE（type=str 校验口径不变 + 展示层下拉候选，
        # 含 gain_currency / learn_skill；既有 enum/hint/help 不变）。
        "id": F_ID, "name": F_NAME, "type": F_EFFECT_TYPE,
        "power": F_POWER, "duration": F_DURATION,
        "probability": F_PROBABILITY, "max_stack": F_MAX_STACK,
        # 批22 · B2：定向压制开关（CakeGame Config_Skills.IgnoreShield/IgnoreIM；§三 B2）
        # ——**并入 effects 参数**（不升为技能字段，遵循「能并入 effects 就不新增技能字段」）。
        # 引擎：置真时对应结算环节整段跳过——ignore_shield → 管线②护盾吸收；
        # ignore_immune → 管线⑤免疫判定（I2 伤害免疫 + fatal/non-fatal 免疫）。
        # 与既有 pierce（effects.type="pierce"）**不重复**：pierce 削「防御系数」，
        # 本开关跳「护盾/免疫」环节，二者正交，可同时存在。
        "ignore_shield": FieldMeta(type="bool", label="无视护盾",
                                   help="置真：本次伤害跳过护盾吸收（不消耗护盾）。"),
        "ignore_immune": FieldMeta(type="bool", label="无视免疫",
                                   help="置真：本次伤害跳过免疫判定（伤害/致命免疫）。"),
        # ---- 批18 新效果类型字段（gain_currency 给货币 / learn_skill 学技能）----
        # 校验：currency 存在性 + amount 区间/缺省 + skill 存在性/等级 由 validator
        # 专项 `_check_effects_18` 判定（本表只做字段口径 + 泛型 R-1/R-2/R-4）。
        # currency 用展示层引用（options_ref）出货币下拉（候选 = settings.currencies[].id），
        # 字段 type 仍为 str，存在性硬拦在专项钩子（对齐 settings.death_penalty.drop_currency 先例）。
        "currency": FieldMeta(type="str", options_ref="settings.currencies",
                              label="货币", help="给货币引用的货币 id（settings.currencies[].id）。"),
        "amount_min": FieldMeta(type="int", range_min=0, label="最小金额",
                                help="获得货币的下限（含）；与最大金额相等 = 固定金额。"),
        "amount_max": FieldMeta(type="int", range_min=0, label="最大金额",
                                help="获得货币的上限（含）；留空 = 等于最小金额。"),
        "skill": FieldMeta(type="ref", ref_target="skill", label="技能",
                           help="学技能引用的技能 id（skills.json）。"),
        "level": FieldMeta(type="int", range_min=1, label="技能等级",
                           help="授予该技能的等级（≥1；留空 = 1 级）。"),
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
                               "from": FieldMeta(type="ref", ref_target="skill", label="源技能"),
                               "to": FieldMeta(type="ref", ref_target="skill", label="目标技能"),
                               "tag": FieldMeta(type="str", label="标签"),
                               "condition": FieldMeta(type="obj", children={},
                                                      soft_label=True, label="触发条件",
                                                      help="满足才可用（或自动替换为派生技）。"
                                                           "主体：连段计数、目标生命百分比、自身/目标状态、"
                                                           "战斗轮次、印记、方位，以及玩家等级（eq/min/max）、"
                                                           "职业（in/not_in 集合）、任务进度（进行中/已完成/未接取）。",
                                                      editor="condition",
                                                      condition_subjects=dict(
                                                          CHAIN_CONDITION_SUBJECTS)),
                               "priority": FieldMeta(type="int", label="优先级"),
                               "mode": FieldMeta(type="str", label="模式"),
                               "armor": FieldMeta(type="bool", label="霸体"),
                               "consume": FieldMeta(type="int", label="消耗"),
                               # 批5：数值覆盖补丁（{键: 数值}）→ 键值对表格（可增删行）
                               "variant_override": FieldMeta(type="obj", children={},
                                                             soft_label=True, label="数值覆盖",
                                                             editor="maptable"),
                           }),
                           soft_label=True, label="连段步骤"),
        "trigger_skill": FieldMeta(type="ref", ref_target="skill", label="触发技能"),
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
        # 批16 #10：weight/probability 是**定义处默认值**——引用处（怪物行动表等）可覆盖；
        # 说明卡标注「默认值（可被引用处覆盖）」（展示层，取值顺序由消费端实现）。
        "weight": FieldMeta(type="number", range_min=0, range_max=100,
                            overridable_default=True),
        # P2-4 修复：不挂 probability 旗标（Y-2 极值误报——0/1 是入池开关非概率值，
        # 与 enemies.actions[].probability 口径一致，1e S1 语义）
        "probability": FieldMeta(type="number", range_min=0, range_max=1,
                                 overridable_default=True),
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
        # 批23 · B1 技能生命消耗（CakeGame Config_Skills.ConsumeType=HP；§三 B1）：
        # **不引入 consume_type 枚举**——单个数值直接表达「放这招要付血」（少而深）；
        # 与 mp_cost 并列、资源各自独立扣。int ≥ 0，单位=点；缺省/0 = 不消耗生命。
        # 引擎消费：core/battle.py::_apply_skill_hp_cost_gate——施放前置门禁，
        # hp - hp_cost < 1 时阻止释放（被拒不消耗行动，同 energy/marks 语义），
        # 可施放则立即扣血；派生技按最终 skill_id 解析（与 consume_marks 同口径）。
        # 校验：非整数 → 泛型 R-1 红；负数 → 泛型 R-2 红；0 不触发 Y-1/Y-4。
        "hp_cost": FieldMeta(
            type="int", range_min=0, range_max=9999, unit="点", label="生命消耗",
            help="释放自损的生命（点）；留空或填 0 = 不消耗生命。"),
        "cooldown": FieldMeta(type="number", range_min=0, range_max=999, unit="回合"),   # F10 ≥0 整数；basic=0
        "tag": FieldMeta(type="str"),    # F11 none/combo/combo_preserve/combo_push/interrupt/armor（枚举 A2）
        "armor": FieldMeta(type="bool"),         # F12 霸体开关（执行语义快键）
        "interrupt": FieldMeta(type="bool"),     # F13 打断快键（唯一归口 = 效果系统 L0 interrupt，T19）
        # 批27 · β4 技能复活标记（CakeGame《技能附加与变量集表》:53 FHX 复活技能；补漏 §一 β4）：
        # bool；true = 该技能可复活死亡态目标（清死亡标记 + 恢复 HP + 去虚弱），缺省 false。
        # 引擎消费：core/battle.py::revive_side（沿用既有 `revive` 事件链路，见 event_dispatcher）；
        # 释放路径：_resolve_combo_action 按最终 skill_id 判 revive（派生/组合口径同 hp_cost）。
        # 校验：仅 bool（泛型 R-1 红拦）；缺省 = 非复活技（既有包零变化，对拍）。
        "revive": FieldMeta(
            type="bool", label="复活技能",
            help="置真：该技能可复活死亡态目标（清死亡标记并恢复生命）；缺省 = 普通技能。"),
        # 批27 · β1 每技能战斗播报模板（CakeGame Config_Skills.AttackTips / 补漏 §一 β1）：
        # 只存**模板键**（options_ref="templates" → 编辑器下拉 = 全量模板表 key），
        # **不把整段文案存进技能数据**；缺省 "" = 既有全局模板（逐字段一致）。
        # 引擎消费：core/message_format/battle_render 按最终 skill_id 取键渲染命中/未命中/
        # 施放行（渲染回退默认键，未配置零变化）。校验：仅 str（泛型 R-1）。
        "message_key": FieldMeta(
            type="str", options_ref="templates", label="战斗播报模板",
            help="该技能战报所用的模板键（core 模板表 key）；留空 = 用默认战报模板。"),
        "chain_refs": FieldMeta(type="list", element=FieldMeta(type="str")),  # F14 派生链引用 skill_chains.json（V-2）
        "consume_marks": FieldMeta(type="obj", label="消耗印记", editor="maptable",
                                   key_ref="mark"),  # F15 {mark_id: count} 消耗印记（V-3 键存在/上限 A2）
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
        # 批23 · C2 基础/初始职业标记（CakeGame Config_Occupation.Basics；§三 C2）：
        # bool；true = 可作为玩家初始职业。现状核查：注册流程只**自动**取一个缺省
        # 职业（default_job 兜底链），**无「多起始职业选择」UX**——本批不做该系统级
        # 改造，is_basic 作最小消费：兜底链在「推荐」之后取**首个 is_basic**，
        # 并在职业列表标「（初始）」。既有包不带 is_basic → 行为与现状一致。
        # 校验：仅 bool（泛型 R-1）；缺省 = false。
        "is_basic": FieldMeta(type="bool", label="基础/初始职业",
                              help="置真：该职业可作为玩家初始职业；缺省 = 不作为初始职业。"),
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
        # 批23 · C1 转职前置（CakeGame Config_Occupation
        # TransferDemand/TransferLevel/FormerOccupation；§三 C1）：合并为一个
        # `advance` 子对象（**不开三个顶层字段**，遵循「少而深」）。三项均可选、
        # 缺省 = 无该条件；既有职业数据不带 advance → 行为与现状一致（对拍）。
        # 校验：from 引用 jobs / items 元素引用 items → 泛型 R-4 硬拦；
        #       level 非整数 R-1 红、负数 R-2 红、0 → Y-1 黄提示。
        # 引擎：commands/job_commands.py::_advance_block——转职判定逐项校验，
        # 不满足给人话（要求值 vs 当前值）。
        "advance": FieldMeta(type="obj", label="转职前置",
                             help="转职需满足的前置条件（原职业/等级/物品，均可选）。",
                             children={
            "from": FieldMeta(type="ref", ref_target="job", label="原职业前置",
                              help="当前必须正处于该职业（jobs 职业 id）；留空 = 不限原职业。"),
            "level": FieldMeta(type="int", range_min=1, unit="级", label="转职等级门槛",
                               help="转职所需玩家等级（≥1）；留空 = 不限等级。"),
            "items": FieldMeta(
                type="list", element=FieldMeta(type="ref", ref_target="item"),
                label="转职需求物品",
                help="转职须持有的物品（items 物品 id，全部须持有）；留空 = 无物品门槛。"),
        }),
        # 批35 · §6.12-12 进阶职业卡片（职业树继承）：写在**进阶职**一侧，声明母职
        # 与可选技能白名单。与批23 `advance`（前置门槛，能不能转）互补：`inherit`
        # 决定「转过去继承什么」。引擎 = core/job_slots.resolve_inherit_chain +
        # core/skill_slots 装配可见集的额外可见集合（复用既有装配入口，不新开一套）；
        # **只影响技能位装配，不碰属性成长**（2026-09-09 拍板：职业成长跟随职业）。
        # 校验：from 引用 jobs / skills 元素引用 skills → 泛型 R-4 硬拦；from 必填（R-5）。
        # 缺省 = 无继承（既有职业数据行为零变化）。
        "inherit": FieldMeta(type="obj", label="进阶继承",
                             help="转职到本职业时继承哪个职业的技能；留空 = 不继承。",
                             children={
            "from": FieldMeta(type="ref", ref_target="job", required=True,
                              label="继承来源职业",
                              help="母职的 jobs 职业 id；转职到本职业时继承该职业的职业专属技能。"),
            "skills": FieldMeta(
                type="list", element=FieldMeta(type="ref", ref_target="skill"),
                label="继承技能白名单",
                help="skills 技能 id 列表；非空 = 只继承列出的技能；留空 = 继承母职全部职业专属技能。"),
        }),
    }
    # 技能/链侧挂点字段（细化_6b §1.5/§1.6）：revert_form（37）与 derive_only（38）为
    # skills.json 字段、job_scope（39）为 skill_chains.json 字段——随 6a 技能库全量字段
    # 登记；6a 尚未登记前此处预留（缺口登记于细化_6b 附·未定稿依赖 1/3，由 6a 路收口）
    items_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME, "type": F_TYPE,
        "price": F_PRICE, "atk": F_ATK, "def": F_DEF,
        "effects": F_EFFECTS,
        # 批14 #6②：装备部位引用「基础 ▸ 装备槽位（settings.slot_defs）」——展示层下拉候选
        # （字段 type 仍 str，校验语义不变；槽位表变更后候选即时联动）。
        "slot": FieldMeta(type="str", options_ref="settings.slot_defs"),
        "bind": FieldMeta(type="bool"),
        "usable": FieldMeta(type="bool"),
        # 批22 · A1 装备/物品职业限制（CakeGame Config_Goods.Occupation；§三 A1）：
        # 命名与形态复用既有 skills.job_restrict（本表 L1703）——list<str>，元素为 jobs.json
        # 职业 id。与技能侧的唯一差异：元素声明 ref_target="job"（注册表 kind，本表 L2322）
        # → 泛型 R-4 引用存在性校验**硬拦**（缺失职业即红）。技能侧因历史 P-1 由
        # skill_validator V-5 宽松放行；装备侧按「能靠注册表解决就不写第二套」直接走
        # 元数据，门禁只严不宽。空列表/缺失 = 不限职业（与技能同口径）。
        "job_restrict": FieldMeta(
            type="list", element=FieldMeta(type="ref", ref_target="job"),
            label="职业限制",
            help="仅这些职业可穿戴/使用（jobs.json 职业 id）；留空 = 不限职业。"),
        # 批22 · A2 使用/穿戴等级门槛（CakeGame Config_Goods.UseLV；§三 A2）：
        # int ≥ 1。校验口径：非整数 → 泛型 R-1；负数 → 泛型 R-2；0 → 泛型 Y-1 黄提示 +
        # items/equipment 专项校验器 IV-1 红拦（int≥1 是硬口径，见 content/item_validator.py）。
        # 与 settings/shop 的 level_required（商店门槛）语义不同，别混用（§三 A2 备注）。
        # 引擎消费：玩家等级 < use_level → 阻止穿戴/使用（core/equipment.item_requirement_error）。
        "use_level": FieldMeta(
            type="int", range_min=1, range_max=999, unit="级", label="使用等级",
            help="需达到的玩家等级（≥1）；留空 = 不限等级。"),
        # 批4.5：items/equipment 实测顶层 desc（原表未登记 → 纯展示宽字段）
        "desc": _soft_display("说明"),
    }
    # 批26 · α组（装备侧，依据 `CakeGame字段差距_补漏.md` §一 组 α）：装备附加五字段。
    # items∪equipment 同库（item_lib）——veinborn 武器/防具多在 items 模块，故登记在
    # items_fields（equipment_fields 复制同一表），两处编辑器/校验同时可见。
    #   α1 grant_skills   穿戴时获得、卸下收回（level<1 → 专项 IV-2 红拦；skill 缺失
    #                     → 泛型 R-4；与 effects.type=learn_skill、set_skills 不同来源）
    #   α2 max_hold       0=不限 / 1=唯一 / -1=禁止获取（取值仅此三档 → 专项 IV-3 红拦）
    #   α3 skill_amp      伤害/冷却增幅（type 枚举 + 上下限 → 专项 IV-4；上下限在
    #                     settings.forge.skill_amp_bounds，框架默认见 content/forge_settings）
    #   α5 attack_override 普攻替换（skill 须由本件赋予 → 专项 Y-9 黄提示，不硬拦）
    #   α6 job_override   穿戴期职业替换（job 引用 → 泛型 R-4）
    items_fields.update({
        "grant_skills": FieldMeta(
            type="list", label="赋予技能",
            element=FieldMeta(type="obj", children={
                "skill": FieldMeta(type="ref", ref_target="skill", label="技能"),
                "level": FieldMeta(type="int", range_min=1, range_max=99, unit="级", label="等级"),
            }),
            help="穿戴时获得这些技能、卸下时收回（skills 技能 id；等级 ≥1）。"),
        "max_hold": FieldMeta(
            type="int", range_min=-1, range_max=1, allow_negative=True, label="最大获取数量",
            help="获取入口上限：0=不限 / 1=唯一（已持有则拒绝再获取）/ -1=禁止获取。"),
        "skill_amp": FieldMeta(
            type="list", label="增幅技能",
            element=FieldMeta(type="obj", children={
                "skill": FieldMeta(type="ref", ref_target="skill", label="技能"),
                "type": FieldMeta(type="enum", enum=("damage", "cooldown"), label="增幅类型"),
                "value": FieldMeta(type="int", allow_negative=True, label="增幅值"),
            }),
            help="按技能增幅：damage=伤害（1+总计/100 作伤害乘数）/ cooldown=冷却；"
                 "上下限见 settings.forge.skill_amp_bounds。"),
        "attack_override": FieldMeta(
            type="obj", label="替换普攻",
            children={
                "enabled": FieldMeta(type="bool", label="启用"),
                "skill": FieldMeta(type="ref", ref_target="skill", label="替换技能"),
                "chance": FieldMeta(type="int", range_min=0, range_max=100, unit="%",
                                    label="触发概率"),
            },
            help="普攻按概率替换为指定技能（0/缺省=不替换）；仅当该技能由本件"
                 "grant_skills 赋予时生效。"),
        "job_override": FieldMeta(
            type="obj", label="替换职业",
            children={
                "job": FieldMeta(type="ref", ref_target="job", label="替换职业"),
                "level_reset": FieldMeta(type="bool", label="等级重置"),
                "name_override": FieldMeta(type="str", label="替换显示名"),
            },
            help="穿戴期间职业替换为该职业（可等级重置/显示名替换），卸下还原。"),
    })
    # 批38 · ③（H7 载体）：装备/物品手数 `handedness` 登记（包声明驱动；items∪equipment 同库）。
    # 枚举两档；缺省未声明（不参与副手判定 → 与现状语义一致）。数值实装（双手占用/单手
    # 副手判定收紧）归批39+（本批只登记，引擎不消费该字段）。
    items_fields.update({
        "handedness": FieldMeta(
            type="enum", enum=("one_hand", "two_hand"), label="手数",
            help="one_hand=单手（可作副手：数值类属性按 settings.equipment_offhand."
                 "single_hand_scale 折算，百分比/强化特殊词条/装备被动/套装词条/符文附魔"
                 "不激活）；two_hand=双手（不可作副手）；留空=未声明。"),
        # 批38 · ④：材料/图纸的相性声明（词缀 → 相性值）；相性 id 需在 settings.affinities
        # 声明（引用存在性由 validator._check_affinity 跨模块红拦）。
        "affinities": FieldMeta(
            type="obj", children={}, soft_label=True, label="相性",
            help="携带的相性值 {相性id: 数值}（材料/图纸共用）；相性 id 需在"
                 "settings.affinities 声明；打造时按材料投入顺序结算互动。"),
    })
    equipment_fields: Dict[str, FieldMeta] = dict(items_fields)
    # 部位互斥：entry.slot 与 entry.excludes 列表内部位互斥成环 → R-5（equipment 专项，§5.2 + L167）
    equipment_fields["slot"] = FieldMeta(type="str", options_ref="settings.slot_defs")
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
                label=GEAR_LABELS_ZH.get(_k, _k), unit="%",
                help=GEAR_HELP_ZH.get(_k, ""))
        for _k in GEAR_COMBAT_KEYS:
            _fm_target[_k] = _gear_combat_field(_k)
        # 批43：占位键（只登记/展示/可编辑，引擎不消费；help 说明承载口径）
        for _k in GEAR_PLACEHOLDER_KEYS:
            _fm_target[_k] = FieldMeta(
                type="number", range_min=0, range_max=500,
                label=GEAR_LABELS_ZH.get(_k, _k), unit="%",
                help=GEAR_HELP_ZH.get(_k, ""))
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
        # F11：抗性 = 「负面效果 ID → 0-100」映射（框架登记 immune 为正式字段，stun 为 soft
        # 展示键；其余键由内容定义）→ 展示层显式声明为**键值表格**（批20 A：动态键空间，键可
        # 改名、行可增删；type / 校验口径不变，只换控件）。
        "resistance": FieldMeta(type="obj", children=RESISTANCE_CHILDREN,
                                editor="kvtable"),
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
        # 子结构由 CHILD_SPEC 递归补（无文案）。
        "ai": _soft_display("AI 行为态", "obj"),
        "phases": _soft_display("阶段表", "list"),
        "rewards": _soft_display("奖励", "obj"),
        "zone_change": _soft_display("换区", "obj"),
    }
    maps_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME,
        "enemy_pool": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="enemy")),
        "battle": FieldMeta(type="bool"), "revert": FieldMeta(type="bool"),
        # 批24 E1：地图隐藏（`hidden`）——CakeGame `Config_Map.Hid`「隐藏（禁直接传送）」。
        # 语义 = 传送类入口过滤（世界地图序号直接传送被拒 + 人话提示）；通道移动不受影响
        # （通道进入照常）。与隐藏**要素**视图（achievements.hidden / monsters.hidden_boss /
        # hidden_quest）不同层，命名区分。
        "hidden": FieldMeta(type="bool", label="隐藏（禁直接传送）",
                            help="置真 = 禁止直接传送进入该地图，只能从相邻地图的通道（或剧情）"
                                 "进入；不影响通道行走。隐藏区域不列 /地图 传送列表。"),
        # 批24 E3：进图消耗 / 门票信物（从本图进入副本时的校验/扣除；缺省无消耗）。
        "entry_cost": FieldMeta(type="obj", children=ENTRY_COST_CHILDREN,
                                label="进图消耗/门票",
                                help="从本地图进入副本时的门票/信物：items 列出所需物品与数量，"
                                     "consume=true 进入时扣除（门票）/ false 仅校验持有。"),
        # 区域/副本区间（min>max 死配置 → R-5，min/max 由校验器泛化检测）
        "min": FieldMeta(type="int"), "max": FieldMeta(type="int"),
        "lower": FieldMeta(type="int"), "upper": FieldMeta(type="int"),
        "reset": FieldMeta(type="obj"),
        # 1g4 F-05/F-06（细化_1g4 §6.2 / 框架 L291）：safe_zone=是否安全区；
        # respawn_point=复活点指向（引用已注册地图 id，泛型 R-4 存在性检查）
        "safe_zone": FieldMeta(type="bool"),
        "respawn_point": FieldMeta(type="ref", ref_target="map"),
        # 批4.5：真实包 maps.json 实有、原表未登记的地图段（→ 纯展示宽字段，soft_label
        # 短路泛型校验；children 由 CHILD_SPEC 递归补结构）。DUNGEON_MAP_ELEM_CHILDREN
        # 早已为「maps 页整图编辑」预留这些键，本批把它接到 maps 模块。
        "desc": _soft_display("说明"),
        "camp": _soft_display("营地", "obj"),
        "camp_name": _soft_display("营地名"),
        "npcs": FieldMeta(type="list", element=FieldMeta(type="str"),
                          soft_label=True, label="NPC 列表"),
        # 批13 C（审计 ①-2-12/B6）：把 DUNGEON_MAP_ELEM_CHILDREN 的刷怪行结构接到 maps 模块
        # ——此前 maps.monsters 走 CHILD_SPEC 只有 7 键，季节/时段/天气/钟点四键登记了却不生效。
        "monsters": FieldMeta(
            type="list", soft_label=True, label="刷怪行",
            element=FieldMeta(type="obj", children=dict(
                DUNGEON_MAP_ELEM_CHILDREN["monsters"].element.children))),
        "exits": _soft_display("通道出口", "obj"),
        "mechanics": _soft_display("地图机制", "list"),
        "gate_guard": _soft_display("门卫"),
        # 批13 C（审计 ①-2-14/B7/U1）：采集点补 name/weather_mods（时间天气定稿 L160/206）
        # 批36（X2 采集/挖掘引擎）：按细化_2a1d §一 GP-01~GP-11 补全字段元数据——
        #   · 补 GP-05 periods / GP-06 seasons / GP-07 respawn_minutes（此前未登记）；
        #   · rarity 收敛为枚举 GP-04（normal/rare/gold，基础三档；天气 rarity_shift
        #     clamp 到 4 档含 awakened，见 core/weather_consumers.RARITY_TIERS）；
        #   · 逐字段补 help（一号原则：非技术作者看得懂）。
        # 校验权威 = map_models.validate_maps 的 V-1Z~V-5Z（本节点 soft_label 短路泛型）。
        "gather_points": FieldMeta(
            type="list", soft_label=True, label="采集点",
            help="地图采集点：产出物品 / 基础概率 / 稀有度（细化_2a1d GP-01~GP-11）。",
            element=FieldMeta(type="obj", children={
                "id": FieldMeta(type="str", label="采集点 ID",
                                help="采集点唯一标识（全库唯一）；钓鱼点与子任务按此 id 引用。"),
                # 批32 C1：展示层引用标注（既有引用扫描覆盖「采集点产出 → 物品」；type 仍 str）。
                "item": FieldMeta(type="str", ref_target="item", label="产出物品",
                                  help="该点产出的物品 id（引用物品表材料类）。"),
                "rarity": FieldMeta(type="enum", enum=("normal", "rare", "gold"),
                                    label="稀有度",
                                    help="基础稀有度：普通 normal / 稀有 rare / 金色 gold；"
                                         "天气 rarity_shift 会在此基础上平移（上限觉醒档）。"),
                "rate": FieldMeta(type="number", range_min=0, range_max=1, label="出现概率",
                                  help="基础采集概率（0-1）；与天气出率倍率相乘后判定。"),
                "periods": FieldMeta(type="list", element=FieldMeta(type="enum",
                                                                     enum=PERIODS_ENUM),
                                     label="时段偏好",
                                     help="可采集时段白名单（晨/午/昏/夜/午夜）；"
                                          "留空 = 全天不限。"),
                "seasons": FieldMeta(type="list", element=FieldMeta(type="enum",
                                                                     enum=SEASONS_ENUM),
                                     label="季节偏好",
                                     help="可采集季节白名单（春夏秋冬）；留空 = 全年不限。"),
                "respawn_minutes": FieldMeta(type="number", range_min=1,
                                              label="刷新间隔(分钟)",
                                              help="采空后经过多少分钟恢复为可采集；默认 10 分钟。"),
                "name": FieldMeta(type="str", label="展示名"),
                "weather_mods": FieldMeta(
                    type="list", soft_label=True, label="天气修正",
                    help="按天气覆盖出率与稀有度；留空 = 不参与天气联动。",
                    element=FieldMeta(type="obj", children={
                        "weather": FieldMeta(type="str", label="天气键",
                                             help="须是已注册的天气键（默认池）。"),
                        "rate_mult": FieldMeta(type="number", range_min=0, label="概率倍率",
                                               help="出率 = 基础概率 × 该倍率；0 = 该天气不出。"),
                        "rarity_shift": FieldMeta(type="int", label="稀有度偏移",
                                                  help="稀有度档位平移（正数上调/负数下调）；"
                                                       "0 = 不改动。"),
                    })),
            })),
        "dungeon_entrances": _soft_display("副本入口", "list"),
        # 批13 C（审计 ①-2-13/B5）：地图天气池覆盖（时间天气定稿 L141）
        "weather_pool": FieldMeta(type="list", element=FieldMeta(type="str"),
                                  soft_label=True, label="地图天气池覆盖",
                                  help="本地图可选天气键（须已在默认池注册）；空/缺省 = 用默认池。"),
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
    # 批46 · 符文地基（43-A）：runes.json 条目字段（口径 §二.1 形状草案）。
    # 三阶 = 独立刻度（tier 1..3，非 quality 四档，H2）；by_equip_type = default+覆盖
    # 差异表（类型键 = items.type）；effects 引用 effects 注册表（可带 overrides）；
    # bias（3 阶偏向性，Q7）暂为宽容器——机制未裁决前不深描。
    # 深校验由 content/rune_models.validate_runes 专项全权（RUNE-01~07）。
    runes_fields: Dict[str, FieldMeta] = {
        "id": F_ID, "name": F_NAME,
        # 三阶独立刻度（R3）；泛型 R-2 拦越界，专项 RUNE-02 另给规则号。
        "tier": FieldMeta(type="int", range_min=1, range_max=3, label="符文阶"),
        # 同族判定（3 合 1 输入族，R5）；同族才允许互为输入。
        "family": FieldMeta(type="str", label="符文族"),
        "icon": FieldMeta(type="str", label="图标"),
        "desc": FieldMeta(type="str", label="说明"),
        # R2：跨装备类型差异表（键 = items.type；default 兜底必须存在；soft_label=动态键空间）。
        "by_equip_type": FieldMeta(
            type="obj", soft_label=True, label="跨装备类型差异表",
            help="default=兜底条目（必须）；其余键 = items.type（weapon/armor_head/…），"
                 "命中类型优先、未命中回落 default；条目内 stats 走 gear_stats 键空间。"),
        # R6：特殊效果声明（引用 effects 注册表，可带 overrides 覆盖参数）。
        # 批48 · 43-D：新增 `trigger`（战斗事件时点；只写在符文引用条目 → 不泄漏全局）
        # 与 `target`（self/enemy，可按符文覆盖动作目标）。
        "effects": FieldMeta(
            type="list", label="特殊效果",
            element=FieldMeta(type="obj", children={
                "effect": FieldMeta(type="ref", ref_target="effect", label="效果引用"),
                "trigger": FieldMeta(
                    type="str", label="触发时点",
                    help="战斗事件时点（battle_start/action_start/on_hit/turn_end 等，"
                         "见 core/event_dispatcher.EVENT_POINTS）；只在该符文穿戴者一侧、"
                         "该时点触发。**被引用的 effects 条目不要写 trigger**（否则全局限触发）。"),
                "target": FieldMeta(type="str", label="目标",
                                    help="动作目标覆盖：self/enemy（缺省按被引用效果的动作）。"),
                "overrides": FieldMeta(type="obj", soft_label=True, label="参数覆盖"),
            })),
        # R7（批48 已裁定 · R-8）：3 阶偏向性 = 偏向某相性（对接批38 相性层）。
        # 宿主装备主/副相性命中 affinity → 该符文数值贡献 ×(1+bonus_pct/100)。
        "bias": FieldMeta(type="obj", label="偏向性", children={
            "affinity": FieldMeta(type="str", label="偏向相性",
                                  help="相性 id（settings.affinities 引用）；宿主装备主/副"
                                       "相性命中该 id 时生效（批38 rank_affinities 判定）。"),
            "bonus_pct": FieldMeta(type="number", label="偏向加成%",
                                   help="命中时该符文数值贡献按此百分点放大（可负/可 0）。"),
        }, help="3 阶偏向性符文：偏向某相性；命中宿主主/副相性 → 数值加成。"),
    }
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
    # 批41 · 深度打造：items 条目新增「材料打造字段」+「图纸字段」（图纸是物品的一种，
    # 不新造平行物品体系）；settings.deep_craft 段补打造规则参数 / 品质颜色 / 图纸档位 /
    # 品质概率阶梯（既有 enabled 字段定义**原样保留**——字段元数据对拍门禁严格键）。
    items_fields.update(ITEMS_MATERIAL_CRAFT_FIELDS)
    items_fields.update(ITEMS_BLUEPRINT_FIELDS)
    SETTINGS_FIELDS["deep_craft"] = FieldMeta(
        type="obj",
        children={**DEEP_CRAFT_SEGMENT_FIELDS, **SETTINGS_FIELDS["deep_craft"].children},
        label=SETTINGS_FIELDS["deep_craft"].label,
        help=SETTINGS_FIELDS["deep_craft"].help,
    )
    # M10 钓鱼（m10_shared_contract §一）：settings.fishing 段（fishing_settings_meta
    # 自包含持有，防 field_meta↔fishing 循环依赖）
    SETTINGS_FIELDS["fishing"] = fishing_settings_meta()
    # 批4.5：settings.json 真实包实有、原表未登记的顶层段（→ 纯展示宽字段，soft_label
    # 短路泛型校验；children 由 CHILD_SPEC 递归补结构）。
    # 依据：content/{veinborn,test_demo,demo_full}/settings.json 实测键并集。
    SETTINGS_FIELDS.update({
        "assistant": _soft_display("助手", "obj"),
        # settings.battle 段（引擎战斗参数；battle_config.resolve_battle_settings 白名单消费）。
        # min_damage（2026-09-14 用户拍板）：最低伤害保底 int ≥ 0、缺省 0 = 关闭。
        # 软标注（soft_label → 泛型校验短路、永不红拦；中文名/说明可被包 field_meta.json 覆盖）。
        "battle": _soft_display("战斗参数", "obj", {
            "min_damage": FieldMeta(
                type="int", default=0, soft_label=True, label="最低伤害保底",
                help="单次命中伤害的最终下限（所有增伤/减伤/防御后、护盾吸收前）；"
                     "低于该值抬到该值，0 = 关闭。"),
        }),
        "command_aliases": _soft_display("指令别名", "obj"),
        "contest": _soft_display("竞技", "obj"),
        "ctb": _soft_display("行动条", "obj"),
        "events": _soft_display("事件文案", "obj"),
        "exp_curve": _soft_display("经验曲线", "obj"),
        "level_cap": _soft_display("等级上限", "int"),
        "quest_board": _soft_display("任务板", "obj"),
        # ---- 批13 C（审计 ①-1/①-4）：框架已实现、但 settings 段此前无登记的全局配置 ----
        # 一号原则：包没用也要在「基础」卡片里看得见（空值可填）。全部 soft_label——
        # 泛型校验短路，既有内容零新增拦截（各专项校验器/引擎自带缺省兜底）。
        # settings.time_cycle（时间天气定稿 L101-124；core/worldtime.py 消费面）
        "time_cycle": _soft_display("时间天气", "obj", {
            "enabled": FieldMeta(type="bool", default=True, label="启用时间天气"),
            "season": FieldMeta(type="obj", label="季节周期", children={
                "season_days": FieldMeta(type="int", range_min=1, default=7, label="季节天数"),
                "enum": FieldMeta(type="list", element=FieldMeta(type="str"),
                                  label="季节枚举"),
            }),
            "period": FieldMeta(type="obj", label="时段周期", children={
                "period_minutes": FieldMeta(type="int", range_min=30, default=60,
                                            label="时段分钟"),
                "enum": FieldMeta(type="list", element=FieldMeta(type="str"),
                                  label="时段枚举"),
            }),
            "weather": FieldMeta(type="obj", label="天气周期", children={
                "weather_minutes": FieldMeta(type="int", range_min=30, default=60,
                                             label="天气分钟"),
                "default_pool": FieldMeta(
                    type="list", label="默认天气池",
                    element=FieldMeta(type="obj", children={
                        "key": FieldMeta(type="str", label="天气键"),
                        "name": FieldMeta(type="str", label="天气名"),
                        "emoji": FieldMeta(type="str", label="图标"),
                    })),
            }),
            "broadcast": FieldMeta(type="obj", label="变化广播", children={
                "enabled": FieldMeta(type="bool", default=False, label="启用广播"),
                "mode": FieldMeta(type="enum", enum=("lazy", "timer"), default="lazy",
                                  label="广播模式"),
                "template": FieldMeta(type="str", default="{emoji} {name}",
                                      label="播报模板"),
            }),
            "combat": FieldMeta(type="obj", label="战斗天气修正", children={
                "weather_mult": FieldMeta(type="obj", label="天气乘区", children={
                    "enabled": FieldMeta(type="bool", default=False, label="启用战斗修正"),
                    "mults": _soft_display("天气倍率", "obj"),
                }),
            }),
        }, help="时间天气：季节/时段/天气三周期与变化广播（缺省全默认，零配置可玩）。"),
        # settings.message_prefix（消息前缀定稿 L41-48；prefix_wiring 消费 7 字段）
        "message_prefix": _soft_display("消息前缀", "obj", {
            "enabled": FieldMeta(type="bool", default=True, label="启用前缀"),
            "format": FieldMeta(type="str", label="格式模板",
                                help="占位符：{level} 等级 / {name} 玩家名 / {title} 称号。"),
            "show_on_system": FieldMeta(type="bool", default=False, label="系统消息也加前缀"),
            "per_channel": FieldMeta(type="enum", enum=("all", "group", "private"),
                                     default="all", label="生效渠道"),
            "hide_when_empty": FieldMeta(type="bool", default=False, label="无称号时省略称号段"),
            "empty_title_text": FieldMeta(type="str", default="-", label="无称号占位文本"),
            "prefix_max_len": FieldMeta(type="int", range_min=0, default=40,
                                        label="前缀最大长度（0=不限）"),
        }, help="消息前缀：回复首行的玩家身份标识（等级/名字/称号）。"),
        # settings.pvp（core/pvp.py PVP_SETTINGS_KEYS 8 键 + 3h §4.1）
        "pvp": _soft_display("PVP", "obj", {
            "enabled": FieldMeta(type="bool", default=False, label="启用 PVP"),
            "mode": FieldMeta(type="enum", enum=("turn_based", "free"),
                              default="turn_based", label="战斗模式"),
            "level_gate": FieldMeta(type="int", range_min=0, default=10, label="等级门槛"),
            "kill_penalty": FieldMeta(type="enum", enum=("none", "respawn"),
                                      default="none", label="击杀惩罚"),
            "loot": _soft_display("战斗掉落", "obj"),
            "daily_reward_limit": FieldMeta(type="int", range_min=0, default=5,
                                            label="每日奖励上限"),
            "pair_daily_limit": FieldMeta(type="int", range_min=0, default=3,
                                          label="同对每日上限"),
            "exp_on_win": FieldMeta(type="bool", default=False, label="胜方获得经验"),
        }, help="PVP（玩家当野怪）：开关、模式、等级门槛与击杀惩罚。"),
        # settings.post_battle_recovery（批37 · X12；【框架】L294/L298-300 + 3h §4.2）
        # 战后恢复：胜利后按比例回复 HP/MP（默认关；定稿「花钱治疗本身是资源循环的一部分」）。
        # 引擎 core/post_battle_recovery.py 消费；字段默认值 0.2/0.1 沿用 3h §4.2（无定稿依据，
        # 见 docs/战后恢复_实现口径.md §四 D1），`enabled` 默认 false 为定稿 L299 口径。
        "post_battle_recovery": _soft_display("战后恢复", "obj", {
            "enabled": FieldMeta(type="bool", default=False, label="启用战后恢复",
                                 help="胜利后是否按比例自动回复 HP/MP（默认关）。"),
            "heal_ratio": FieldMeta(type="number", default=0.2, range_min=0, range_max=1,
                                    label="战后治疗比例",
                                    help="胜利后按 HP/MP 上限计算的回复比例（0~1，0=不回复）；"
                                         "回复量封顶到上限。默认值与数值口径无定稿依据（待用户裁决）。"),
            "safe_zone_heal": FieldMeta(type="number", default=0.1, range_min=0, range_max=1,
                                        label="安全区停留回复比例",
                                        help="在安全区停留时回复 HP/MP 的比例（0~1）；"
                                             "本批仅登记字段，消费挂安全区判定（待用户裁决）。"),
        }, help="战后恢复：胜利后按比例回复 HP/MP（默认关）。"),
        # settings.codex（core/codex.py:278 消费四册权重；单机向定稿 L43）
        "codex": _soft_display("图鉴", "obj", {
            "weights": FieldMeta(type="obj", label="四册完成度权重", children={
                "monster": FieldMeta(type="number", range_min=0, default=1.0, label="怪物册"),
                "fish": FieldMeta(type="number", range_min=0, default=1.0, label="鱼类册"),
                "item": FieldMeta(type="number", range_min=0, default=1.0, label="物品册"),
                "craft": FieldMeta(type="number", range_min=0, default=1.0, label="制造册"),
            }),
        }, help="图鉴：四册（怪物/鱼/物品/制造）完成度加权，默认等权。"),
        # settings.event_log_cap / event_log_capacity（core/event_bus.py:18 双键兼容）
        "event_log_cap": FieldMeta(type="int", range_min=0, default=300, soft_label=True,
                                   label="冒险日志容量",
                                   help="冒险日志环形缓冲保留条数（缺省 300）。"),
        "event_log_capacity": FieldMeta(type="int", range_min=0, default=300, soft_label=True,
                                        label="冒险日志容量（别名）",
                                        help="与 event_log_cap 同义；二者同时存在时以本键优先。"),
        # settings.command_mode / require_at / at_text（总纲 §7.2；parsers 三模式）
        "command_mode": FieldMeta(
            type="enum",
            enum=("global_shortcut", "combat_shortcut", "prefix_only"),
            default="global_shortcut", soft_label=True, label="指令触发模式",
            help="global_shortcut 全局免前缀 / combat_shortcut 战斗内免前缀 / "
                 "prefix_only 全部指令必须带前缀。"),
        "require_at": FieldMeta(type="bool", default=False, soft_label=True,
                                label="需 @机器人 触发",
                                help="开启后指令需 @机器人 才识别（与触发模式叠加生效）。"),
        "at_text": FieldMeta(type="str", default="@机器人", soft_label=True,
                             label="@ 触发文本",
                             help="识别 @触发 时匹配的文本（如 @机器人）。"),
        # settings.attr_types / conditional_rules / imprints（玩家属性定稿 §八；context.py 消费）
        "attr_types": _soft_display("属性类型映射", "obj",
                                    help="属性键 → 类型（resource 资源轴 / combat 战斗属性）映射。"),
        "conditional_rules": FieldMeta(
            type="list", soft_label=True, label="条件加成规则",
            help="条件触发的属性加成规则列表（source 每 per_point 点 → target 加成）。",
            element=FieldMeta(type="obj", children={
                "id": FieldMeta(type="str", label="标识"),
                "name": FieldMeta(type="str", label="名称"),
                "source": FieldMeta(type="str", label="触发属性"),
                "target": FieldMeta(type="str", label="产出属性"),
                "per_point": FieldMeta(type="number", label="每点产出"),
                "note": FieldMeta(type="str", label="备注"),
            })),
        "imprints": FieldMeta(
            type="list", soft_label=True, label="印记展示",
            help="状态面板展示的印记行（名称/层数/来源）。",
            element=FieldMeta(type="obj", children={
                "name": FieldMeta(type="str", label="印记名"),
                "count": FieldMeta(type="int", range_min=0, label="层数"),
                "source": FieldMeta(type="str", label="来源"),
            })),
        # settings.shortcut_max / default_job_id / max_dialog_depth / resource_pct
        "shortcut_max": FieldMeta(type="int", range_min=0, default=20, soft_label=True,
                                  label="快捷指令上限",
                                  help="玩家可绑定的快捷指令条数上限（缺省 20）。"),
        "default_job_id": FieldMeta(type="ref", ref_target="jobs", soft_label=True,
                                    label="默认职业",
                                    help="新玩家注册时的缺省职业（引用职业库）。"),
        "max_dialog_depth": FieldMeta(type="int", range_min=0, default=2, soft_label=True,
                                      label="对话深度上限（0=不限）",
                                      help="NPC 简单对话树的最大展开深度（0 = 不限）。"),
        "resource_pct": FieldMeta(type="bool", default=False, soft_label=True,
                                  label="资源轴按百分比显示",
                                  help="状态面板把资源轴（剑气/怒气等）按百分比展示。"),
    })

    return {
        "manifest": ModuleMeta(
            entry_type="object",
            fields=_decorate_field_meta(manifest_fields, {}, {},
                                        _child_spec("manifest"))),
        "effects": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(effects_fields, {}, {},
                                                          _child_spec("effects"),
                                                          None,
                                                          None),
                              kind="effect", namespace="effect_family",
                              # 批20 C：二级分组（子页签）——长模块首屏不铺开
                              field_subgroups=dict(EFFECTS_FIELD_SUBGROUPS),
                              subgroup_order=EFFECTS_SUBGROUP_ORDER,
                              subgroup_labels=dict(EFFECTS_SUBGROUP_LABELS)),
        "statuses": ModuleMeta(entry_type="list",
                               fields=_decorate_field_meta(statuses_fields, {}, {},
                                                           _child_spec("statuses"),
                                                           None,
                                                           None),
                               kind="status", namespace="effect_family",
                               field_subgroups=dict(STATUSES_FIELD_SUBGROUPS),
                               subgroup_order=STATUSES_SUBGROUP_ORDER,
                               subgroup_labels=dict(STATUSES_SUBGROUP_LABELS)),
        "marks": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(marks_fields, {}, {},
                                                        _child_spec("marks"),
                                                        None),
                            kind="mark", namespace="effect_family"),
        "skill_chains": ModuleMeta(entry_type="list",
                                   fields=_decorate_field_meta(skill_chains_fields, {},
                                                               {},
                                                               _child_spec("skill_chains"),
                                                               None,
                                                               None),
                                   kind="skill_chain",
                                   namespace="chain_lib", chain_field="next",
                                   field_subgroups=dict(SKILL_CHAINS_FIELD_SUBGROUPS),
                                   subgroup_order=SKILL_CHAINS_SUBGROUP_ORDER,
                                   subgroup_labels=dict(SKILL_CHAINS_SUBGROUP_LABELS)),
        "action": ModuleMeta(entry_type="list",
                             fields=_decorate_field_meta(action_fields, {}, {},
                                                         _child_spec("action"),
                                                         None),
                             kind="action", namespace="action_lib",
                             field_subgroups=dict(ACTION_FIELD_SUBGROUPS),
                             subgroup_order=ACTION_SUBGROUP_ORDER,
                             subgroup_labels=dict(ACTION_SUBGROUP_LABELS)),
        # M13 技能库（细化_6a_技能库契约 §1：skills.json 玩家技能库；F01-F24 全字段登记；
        # kind="skill" 与 loader _KIND_FOR_MODULE + DEF_CLASSES 对齐（路1A SkillDef）；
        # 命名空间 skill_lib 独立于 action_lib——V-10 跨库重名仅黄提示）
        "skills": ModuleMeta(
            entry_type="list",
            fields=_decorate_field_meta(skills_fields, SKILLS_FIELD_GROUPS, {},
                                        _child_spec("skills"), None,
                                        None),
            kind="skill", namespace="skill_lib",
            field_groups=dict(SKILLS_FIELD_GROUPS),
            group_order=SKILLS_GROUP_ORDER,
            # 批5：技能条目页的「派生」关联分区（声明驱动；编辑器不写死模块/字段名）。
            associations=SKILLS_ASSOCIATIONS,
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
                           fields=_decorate_field_meta(jobs_fields, {}, {},
                                                       _child_spec("jobs"), None,
                                                       None),
                           kind="job", namespace="job_lib",
                           field_subgroups=dict(JOBS_FIELD_SUBGROUPS),
                           subgroup_order=JOBS_SUBGROUP_ORDER,
                           subgroup_labels=dict(JOBS_SUBGROUP_LABELS)),
        "formula": ModuleMeta(entry_type="map", fields=formula_fields, kind="formula", namespace="formula_lib"),
        "items": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(items_fields, ITEMS_FIELD_GROUPS, {},
                                                        None, None, None),
                            kind="item", namespace="item_lib",
                            field_groups=ITEMS_FIELD_GROUPS, group_order=ITEMS_GROUP_ORDER,
                            group_labels={}),
        "equipment": ModuleMeta(entry_type="list",
                                fields=_decorate_field_meta(equipment_fields, EQUIPMENT_FIELD_GROUPS, {},
                                                            None, None, None),
                                kind="equipment",
                                namespace="item_lib", mutex_field="excludes",
                                field_groups=EQUIPMENT_FIELD_GROUPS, group_order=EQUIPMENT_GROUP_ORDER,
                                group_labels={}),
        "traits": ModuleMeta(entry_type="list",
                             fields=_decorate_field_meta(traits_fields, {}, {},
                                                         _child_spec("traits")),
                             kind="trait", namespace="trait_lib"),
        # M8 炼金（m8_contract_数据与校验 §一/§三/§四 4.2）：recipe/proficiency 新增登记四件套；
        # slots 由 alchemy_settings.slots_module_meta() 提供（kind=slots，与 loader 注册表同名）
        "recipe": ModuleMeta(entry_type="list",
                             fields=_decorate_field_meta(recipe_fields, {}, {},
                                                         _child_spec("recipe")),
                             kind="recipe", namespace="recipe_lib"),
        # 批46 · 符文地基（43-A）：runes.json list 模块（kind="rune"，
        # 与 loader._KIND_FOR_MODULE / NAMESPACES["rune_lib"] 对齐）。
        "runes": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(runes_fields, {}, {},
                                                        _child_spec("runes")),
                            kind="rune", namespace="rune_lib"),
        "proficiency": ModuleMeta(entry_type="list",
                                  fields=_decorate_field_meta(proficiency_fields, {},
                                                              {},
                                                              _child_spec("proficiency")),
                                  kind="proficiency", namespace="proficiency_lib"),
        "slots": _decorate_module_meta(slots_module_meta(), {},
                                       _child_spec("slots")),
        # M9 锻造（m9_shared_contract §〇~§六）：forge.json 顶层 obj——模块级 ModuleMeta
        # 由 forge_module_meta() 提供（entry_type=object）；M12.5 批3 路3A 注入段级
        # 字段表 FORGE_TOP_FIELD_DEFS（schema_version 精确 + trees/sets/augments/
        # settings 四宽容器 soft_label——泛型零新增拦截）；深结构校验由
        # validate_forge 专项全权（V1-V15/W + 2c2d V1-V8/W1-W4），泛型只做顶层形态
        "forge": _decorate_module_meta(forge_module_meta(), (), _child_spec("forge")),
        # M10 钓鱼（m10_shared_contract §三）：fishing.json 顶层 obj——模块级 ModuleMeta
        # 由 fishing_module_meta() 提供（entry_type=object）；深结构校验由
        # validate_fishing 专项全权（V1-V6/W1），泛型只做顶层形态（对齐 forge/dungeon）
        "fishing": _decorate_module_meta(fishing_module_meta(), (), _child_spec("fishing")),
        # M12.5 强化（2c3a/2c3b）：enhance.json 顶层 obj——模块级 ModuleMeta 由
        # enhance_module_meta() 提供（entry_type=object）；深结构校验由
        # validate_enhance 专项全权（V1~V7），泛型只做顶层形态（对齐 forge/fishing）
        "enhance": _decorate_module_meta(enhance_module_meta(), (), _child_spec("enhance")),
        "enemies": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(enemies_fields, ENEMIES_FIELD_GROUPS,
                                                          {}, _child_spec("enemies"),
                                                          None, None),
                              kind="enemy", namespace="enemy_lib",
                              field_groups=ENEMIES_FIELD_GROUPS, group_order=ENEMIES_GROUP_ORDER,
                              group_labels={}),
        "maps": ModuleMeta(entry_type="list",
                           fields=_decorate_field_meta(maps_fields, MAPS_FIELD_GROUPS,
                                                       {}, _child_spec("maps"),
                                                       None, None),
                           kind="map", namespace="map_lib",
                           field_groups=MAPS_FIELD_GROUPS, group_order=MAPS_GROUP_ORDER,
                           group_labels={}),
        # M3 副本（m3_shared_contract §4）：新结构由 dungeon_models.validate_dungeons 专项全权。
        # M12.5 批1 路1C：宽松字段表注入（仅 id required + 宽容器 + 闭合枚举，
        # 泛型零新增拦截——专项校验仍全权深结构）
        "dungeon": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(DUNGEON_FIELDS, {}, {},
                                                          _child_spec("dungeon")),
                              kind="dungeon", namespace="dungeon_lib"),
        "stats": ModuleMeta(entry_type="map", fields=stats_fields, kind="stat", namespace="stat_lib",
                            key_regex=r"[a-z][a-z0-9_]*"),
        # M4 交互系统（m4_shared_contract §3.1~3.4）：npc/shop/quest/checkin 专项校验器
        # 全权深结构（R-1~R-5/Y-1~Y-8 专项判定）；M12 批4 路4A 注入正式字段表（宽松登记：
        # 仅 id required + 宽 obj 容器 + 闭合枚举——编辑器表单数据源 P-07，泛型并行零新增拦截）
        "npc": ModuleMeta(entry_type="list",
                          fields=_decorate_field_meta(NPC_FIELDS, {}, {}, _child_spec("npc"),
                                                      None, None),
                          kind="npc", namespace="npc_lib",
                          field_subgroups=dict(NPC_FIELD_SUBGROUPS),
                          subgroup_order=NPC_SUBGROUP_ORDER,
                          subgroup_labels=dict(NPC_SUBGROUP_LABELS)),
        "shop": ModuleMeta(entry_type="list",
                           fields=_decorate_field_meta(SHOP_FIELDS, {}, {}, _child_spec("shop"),
                                                       None, None),
                           kind="shop", namespace="shop_lib",
                           field_subgroups=dict(SHOP_FIELD_SUBGROUPS),
                           subgroup_order=SHOP_SUBGROUP_ORDER,
                           subgroup_labels=dict(SHOP_SUBGROUP_LABELS)),
        "quest": ModuleMeta(entry_type="list",
                            fields=_decorate_field_meta(QUEST_FIELDS, QUEST_FIELD_GROUPS,
                                                        {}, _child_spec("quest"),
                                                        None, None),
                            kind="quest", namespace="quest_lib",
                            field_groups=QUEST_FIELD_GROUPS, group_order=QUEST_GROUP_ORDER,
                            group_labels={}),
        "checkin": ModuleMeta(entry_type="list",
                              fields=_decorate_field_meta(CHECKIN_FIELDS, {}, {},
                                                          _child_spec("checkin")),
                              kind="checkin", namespace="checkin_lib"),
        # M11 成就（4c §1.5）：顶层 list；M12.5 批1 路1C 宽松字段表注入
        # （专项校验器 achievements_models ACH01-13 仍全权深结构，泛型零新增拦截）
        "achievements": ModuleMeta(entry_type="list",
                                   fields=_decorate_field_meta(ACHIEVEMENT_FIELDS, {}, {},
                                                               _child_spec("achievements")),
                                   kind="achievement", namespace="achievement_lib"),
        # 条件加成（细化_3b §3.2；环 + 引用存在性专项校验见 validator._check_conditional）
        "conditional": ModuleMeta(entry_type="object",
                                  fields=_decorate_field_meta(conditional_fields, {},
                                                              {},
                                                              _child_spec("conditional")),
                                  kind="conditional", namespace="cond_lib"),
        # 批13 C（审计 ①-4-22）：消息模板配置化（2026-08-31 用户拍板）——内容包
        # templates.json 的键 = 模板名、值 = 文案字符串（core/templates.resolve_templates
        # 覆盖 DEFAULT_TEMPLATES）。此前包已声明但框架无登记 → 补 ModuleMeta（entry_type=map）。
        "templates": ModuleMeta(entry_type="map", fields={}, kind="templates",
                                namespace="template_lib",
                                value_meta=FieldMeta(type="str", multiline=True),
                                # 批19 #4：条目列表 = 包数据键 ∪ 框架全量模板表键
                                # （来源在 `web/framework_keys.py` 注册；不写死模板键名）。
                                key_source="templates"),
        # 通用设置（细化_1g4 §6.1 death_penalty + currencies 段；其余段由 3h 路登记缺省放行）。
        # 注意：settings.json 为常驻模块（3h D-01），本表仅登记字段口径；loader 常驻加载归 3h/M 接线。
        "settings": ModuleMeta(entry_type="object",
                               fields=_decorate_field_meta(SETTINGS_FIELDS, {},
                                                           {},
                                                           _child_spec("settings"),
                                                           None,
                                                           None)),
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
                                                           {})),
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
    "default_field_meta_table",
    "FieldMeta",
    "ModuleMeta",
    "FieldMetaTable",
    "DEATH_PENALTY_CHILDREN",
    "CURRENCY_ENTRY_CHILDREN",
    "SETTINGS_FIELDS",
    "DEFAULT_CURRENCY_IDS",
    "DUNGEON_FIELDS",
    "ACHIEVEMENT_FIELDS",
    "SKILLS_GROUP_DEFS",
    "SKILLS_FIELD_GROUPS",
    "SKILLS_GROUP_ORDER",
    "ENEMIES_GROUP_DEFS",
    "ENEMIES_FIELD_GROUPS",
    "ENEMIES_GROUP_ORDER",
    "ITEMS_GROUP_DEFS",
    "ITEMS_FIELD_GROUPS",
    "ITEMS_GROUP_ORDER",
    "EQUIPMENT_FIELD_GROUPS",
    "EQUIPMENT_GROUP_ORDER",
    "MAPS_GROUP_DEFS",
    "MAPS_FIELD_GROUPS",
    "MAPS_GROUP_ORDER",
    "QUEST_GROUP_DEFS",
    "QUEST_FIELD_GROUPS",
    "QUEST_GROUP_ORDER",
    "CHAIN_CONDITION_SUBJECTS",
    "SKILLS_ASSOCIATIONS",
    "F_SKILL_POWER",
]
