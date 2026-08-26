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
}
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
