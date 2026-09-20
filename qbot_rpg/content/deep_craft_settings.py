"""批41 · 深度打造数据层：打造参数段默认值 + 图纸/材料字段定义 + 品质概率阶梯。
批44 · 投入概率暴击：`craft_rules.quality_exp_crit` 默认值（缺省关）+ 字段元数据。

文件：qbot_rpg/content/deep_craft_settings.py
功能：深度打造（打造家族的「深度层」）的**包声明口径**与**编辑器字段元数据**：

  1. `settings.deep_craft` 段默认值（`DEFAULT_DEEP_CRAFT_RULES` /
     `DEFAULT_QUALITY_COLORS` / `DEFAULT_BLUEPRINT_GRADES` / `DEFAULT_QUALITY_DRAW_TABLE`）
     ——全部可被内容包覆盖；引擎只读，不内置业务数值（对齐 forge_settings 的
     「默认表 + 包覆盖」做法）。
  2. `DEEP_CRAFT_RULE_FIELDS` / `DEEP_CRAFT_SEGMENT_FIELDS`：`settings.deep_craft`
     子字段 FieldMeta（中文名/说明/范围/枚举，编辑器可见）。
  3. `ITEMS_MATERIAL_CRAFT_FIELDS` / `ITEMS_BLUEPRINT_FIELDS`：items 条目新增字段
     （材料：等级/品质/成本；图纸：档位/产出/材料槽/固定属性/随机属性位/套装词条/
     被动/等级带/学习条件）——**图纸是物品的一种**，不新造平行物品体系。

依据：
  - `docs/深度打造_决策记录.md` §一 H1/H2/H6、§二 N1~N4/N6、§六（合成公用层；
    打造只做深度层）。
  - `打造系统_原案_20260919.md` §1/§3/§4/§5/§6/§8/§11/§12/§13。
  - `打造系统_B_数值与经验规划.md` §1.1~1.6/§2.1~2.3/§3.1~3.2（13 行共享阶梯 +
    图纸档上移 1/2/3 行）。
  - `打造系统_A_框架映射与数据模型.md` B-1~B-3（schema 草案）。

铁律：零 NoneBot import；纯数据 + 纯函数（无 IO/无随机/无时间）；不含任何内容包专有
      业务名（相性 id / 图纸 id / 材料 id 全部由包声明，本文件只给框架默认枚举与
      概率阶梯）。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.models import FieldMeta

__all__ = [
    "DEFAULT_QUALITY_COLORS",
    "DEFAULT_BLUEPRINT_GRADES",
    "DEFAULT_QUALITY_DRAW_TABLE",
    "DEFAULT_QUALITY_EXP_BY_COLOR",
    "DEFAULT_QUALITY_LEVEL_THRESHOLDS",
    "DEFAULT_DEEP_CRAFT_RULES",
    "DEEP_CRAFT_RULE_FIELDS",
    "DEEP_CRAFT_SEGMENT_FIELDS",
    "ITEMS_MATERIAL_CRAFT_FIELDS",
    "ITEMS_BLUEPRINT_FIELDS",
    "MATERIAL_CRAFT_KEYS",
    "BLUEPRINT_KEYS",
    "read_deep_craft_settings",
    "grade_of",
]

# =====================================================================================
# 一、默认值（包可覆盖；引擎只读）
# =====================================================================================

# 品质颜色 6 档（原案 §6：白绿蓝紫橙红 = 普通/优秀/精良/史诗/传说/神话）。
# 框架默认枚举；包可声明自己的 id/中文名（引擎按 id 关联概率表与经验基数）。
DEFAULT_QUALITY_COLORS: List[Dict[str, Any]] = [
    {"id": "白", "name": "普通"},
    {"id": "绿", "name": "优秀"},
    {"id": "蓝", "name": "精良"},
    {"id": "紫", "name": "史诗"},
    {"id": "橙", "name": "传说"},
    {"id": "红", "name": "神话"},
]

# 图纸档 4 档（原案 §13：铜银金彩；银/金/彩起步比上一档高一级 → 行偏移 +0/+1/+2/+3）。
# cost_cap = 该档单次打造总 cost 上限（N3「按图纸档缩放」；量级取 B 路推演，
# 由掉落经济校准——标「待实际数据校准」，全部可配）。per-blueprint 可用
# `blueprint_cost_cap` 覆盖。
DEFAULT_BLUEPRINT_GRADES: List[Dict[str, Any]] = [
    {"id": "铜", "name": "铜图纸", "level_offset": 0, "cost_cap": 600},
    {"id": "银", "name": "银图纸", "level_offset": 1, "cost_cap": 3900},
    {"id": "金", "name": "金图纸", "level_offset": 2, "cost_cap": 18000},
    {"id": "彩", "name": "彩图纸", "level_offset": 3, "cost_cap": 86000},
]

# 品质阶梯 13 行（原案 §13 铜表 1~10 + B 路 §3.1 用户口径「银/金/彩 = 铜表上移
# 1/2/3 行」）。**行号共享**：图纸档只决定可用行窗口，品质等级 L → 行 L + 偏移。
# 红品质仅第 10 行起出现（铜行10 = 5%）；每行权重和 = 100。
DEFAULT_QUALITY_DRAW_TABLE: Dict[str, Dict[str, Dict[str, int]]] = {
    "ladder": {
        "1": {"白": 75, "绿": 25},
        "2": {"白": 55, "绿": 30, "蓝": 15},
        "3": {"白": 45, "绿": 33, "蓝": 20, "紫": 2},
        "4": {"白": 25, "绿": 40, "蓝": 30, "紫": 5},
        "5": {"白": 19, "绿": 30, "蓝": 35, "紫": 15, "橙": 1},
        "6": {"白": 16, "绿": 20, "蓝": 35, "紫": 25, "橙": 4},
        "7": {"白": 10, "绿": 15, "蓝": 30, "紫": 30, "橙": 15},
        "8": {"白": 4, "绿": 10, "蓝": 20, "紫": 40, "橙": 26},
        "9": {"绿": 2, "蓝": 12, "紫": 50, "橙": 36},
        "10": {"蓝": 5, "紫": 40, "橙": 50, "红": 5},
        "11": {"紫": 30, "橙": 60, "红": 10},
        "12": {"紫": 20, "橙": 60, "红": 20},
        "13": {"紫": 5, "橙": 55, "红": 40},
    }
}

# 品阶基数（每材料品质颜色 → 品质经验基数；B 路 §1.2 假设 A4，单调递增）。
DEFAULT_QUALITY_EXP_BY_COLOR: Dict[str, float] = {
    "白": 1.0, "绿": 1.6, "蓝": 2.6, "紫": 4.2, "橙": 7.0, "红": 11.0,
}

# 品质经验阈值（1~10 级；B 路 §2.1 假设 A8「前密后疏」，全可配）。
DEFAULT_QUALITY_LEVEL_THRESHOLDS: List[int] = [0, 25, 60, 110, 180, 275, 400, 560, 780, 1080]

# settings.deep_craft.craft_rules 默认值（N1~N4 全部落包声明）。
DEFAULT_DEEP_CRAFT_RULES: Dict[str, Any] = {
    # 等级加权：主材料槽合计 main，其余自由槽合计 free（和 = 1 → 同级材料 → 同级装备）。
    "material_level_weight": {"main": 0.6, "free": 0.4},
    "level_rounding": "floor",                 # floor / round / ceil
    "quality_exp_affinity_bonus": 1.5,         # 与图纸同相性材料的品质经验倍率（原案 §6「更多」）
    "quality_level_thresholds": DEFAULT_QUALITY_LEVEL_THRESHOLDS,
    "slot_decay": 0.25,                        # 同材料第 n 件边际衰减（第 5 件归 0）
    "max_per_kind": 5,                         # 单材料件数上限
    "max_kinds": 10,                           # 材料种数上限（原案 §12：玩家最大投入 10 种）
    "type_bonus": 1.03,                        # 每多 1 种的广度奖励
    "global_decay": 1.0,                       # 全局衰减（N1；1.0 = 不衰减）
    "cost_base": 60,                           # 固定工费
    "cost_per_kind": 20,                       # 每材料种数附加 cost
    "cost_floor_ratio": 0.0,                   # 总 cost 下限 = cap × 本比例（0 = 不设下限）
    # 材料互动 → 品质经验乘子（原案 §12 互动；幅度未定 → 包声明系数，见工程补白 G-3）
    "interaction": {"conflict": -0.25, "amplify": 0.15},
    # ---- 批44 · 投入概率暴击（决策记录 §七；草案 v2 §3.2 形状）----
    # 设计意图：**用「投料时按概率暴击给额外品质经验」替代「拉高 cost cap」或「强制扩充
    # 彩档材料表」**，使高档图纸有机会冲破常规经验上限达到品质 10（原案 §6 要求 1~10 级）。
    # 全部可配、缺省保守：`enabled=false` → 不掷、不消费随机数，行为与既有逐字段一致；
    # 逐档概率低档更高、高档更低（铜 15% / 银 10% / 金 7% / 彩 5%，§七建议值，待实测校准）。
    "quality_exp_crit": {
        "enabled": False,                      # 默认关（不声明 = 零变化）
        "grades": [],                          # 适用图纸档；空 = 全档（可只开高档）
        "chance_by_grade": {"铜": 0.15, "银": 0.10, "金": 0.07, "彩": 0.05},
        "chance_default": 0.05,                # 档未声明时的概率（缺省保守）
        "mult_by_grade": {"铜": 2.0, "银": 2.0, "金": 2.0, "彩": 2.0},
        "mult_default": 1.0,                   # 档未声明时的倍率（1.0 = 不加成）
        "additive_exp": 0.0,                   # 命中时的固定加经验（与倍率可叠加；默认关）
        "applies_to": "quality_exp",           # 作用目标（当前仅品质经验）
        "affects_quality_level": True,         # 是否参与品质等级判定（false = 仅展示经验）
        "rolls_per_craft": 1,                  # 每次打造掷数（1~2；>1 显著抬高期望）
        "exp_cap": "last_threshold",           # none / last_threshold（取阈值末项）/ 数值
        "rng_stream": "player",                # 随机流标记（引擎只走注入的玩家级随机流）
    },
    # 随机属性 / 随机套装词条条数缺省（图纸可各自覆盖）
    "random_stat_count": {"min": 0, "max": 2},
    "random_set_affix_count": {"min": 0, "max": 2},
}

# =====================================================================================
# 二、字段元数据（编辑器可见；一号原则：中文名 / 类型 / 范围 / 枚举 / 引用 / 必填）
# =====================================================================================

# settings.deep_craft.craft_rules 的子字段
DEEP_CRAFT_RULE_FIELDS: Dict[str, FieldMeta] = {
    "material_level_weight": FieldMeta(
        type="obj", label="材料等级占比",
        children={
            "main": FieldMeta(type="number", range_min=0.0, range_max=1.0, label="主材料槽占比"),
            "free": FieldMeta(type="number", range_min=0.0, range_max=1.0, label="自由槽合计占比"),
        },
        help="等级 = Σ(材料等级 × 占比)；主材料槽合计 main、其余自由槽合计 free，二者之和"
             "应为 1（完全同级材料 → 该级装备）。"),
    "level_rounding": FieldMeta(
        type="enum", enum=("floor", "round", "ceil"), default="floor", label="等级取整"),
    "quality_exp_affinity_bonus": FieldMeta(
        type="number", range_min=1.0, default=1.5, label="同相性品质经验倍率",
        help="材料相性与图纸相性相同时的品质经验倍率（原案 §6「增加更多」）。"),
    "quality_level_thresholds": FieldMeta(
        type="list", element=FieldMeta(type="int", range_min=0), label="品质经验阈值",
        help="品质等级 1~10 的累计经验阈值（第 1 项通常为 0）；长度 = 品质等级上限。"),
    "slot_decay": FieldMeta(
        type="number", range_min=0.0, range_max=1.0, default=0.25, label="同材料件数衰减",
        help="同一材料第 n 件按 (1 − decay×(n−1)) 计入（≤0 即止）。"),
    "max_per_kind": FieldMeta(
        type="int", range_min=1, default=5, label="单材料件数上限"),
    "max_kinds": FieldMeta(
        type="int", range_min=1, default=10, label="材料种数上限"),
    "type_bonus": FieldMeta(
        type="number", range_min=1.0, default=1.03, label="材料种数奖励",
        help="每多 1 种材料的品质经验倍率（广度奖励）。"),
    "global_decay": FieldMeta(
        type="number", range_min=0.0, default=1.0, label="全局衰减"),
    "cost_base": FieldMeta(type="int", range_min=0, default=60, label="固定工费"),
    "cost_per_kind": FieldMeta(type="int", range_min=0, default=20, label="每种材料附加费"),
    "cost_floor_ratio": FieldMeta(
        type="number", range_min=0.0, range_max=1.0, default=0.0, label="cost 下限比例",
        help="总 cost 下限 = 该档上限 × 本比例（0 = 不设下限）。"),
    "interaction": FieldMeta(
        type="obj", label="互动经验系数",
        children={
            "conflict": FieldMeta(type="number", allow_negative=True, default=-0.25,
                                  label="冲突系数"),
            "amplify": FieldMeta(type="number", allow_negative=True, default=0.15,
                                 label="增幅系数"),
        },
        help="材料相性冲突/增幅对品质经验的乘子系数（触发 1 对 ×(1+系数)）。"),
    # ---- 批44 · 投入概率暴击（决策记录 §七；草案 v2 §3.2 形状）----
    "quality_exp_crit": FieldMeta(
        type="obj", label="投入暴击（品质经验）",
        children={
            "enabled": FieldMeta(type="bool", default=False, label="启用投入暴击",
                                 help="缺省关闭：不声明 = 不掷、不消耗随机数，"
                                      "行为与既有逐字段一致。"),
            "grades": FieldMeta(
                type="list", element=FieldMeta(type="str"), label="适用图纸档",
                help="图纸档 id（需在 blueprint_grades 声明）；留空 = 全档，可只开高档。"),
            "chance_by_grade": FieldMeta(
                type="obj", soft_label=True, label="逐档暴击概率",
                help="图纸档 id → 概率（0~1）；未声明的档回落到「缺省暴击概率」。"),
            "chance_default": FieldMeta(
                type="number", range_min=0.0, range_max=1.0, default=0.05,
                label="缺省暴击概率"),
            "mult_by_grade": FieldMeta(
                type="obj", soft_label=True, label="逐档暴击倍率",
                help="图纸档 id → 命中时的品质经验倍率；未声明的档回落到「缺省暴击倍率」。"),
            "mult_default": FieldMeta(
                type="number", range_min=0.0, default=1.0, label="缺省暴击倍率",
                help="1.0 = 不加成（命中只记标记）；建议为自有档位显式声明倍率。"),
            "additive_exp": FieldMeta(
                type="number", allow_negative=True, default=0.0, label="暴击固定加经验",
                help="命中时在倍率之外追加的固定品质经验（默认 0，与倍率可叠加）。"),
            "applies_to": FieldMeta(
                type="enum", enum=("quality_exp",), default="quality_exp", label="作用目标"),
            "affects_quality_level": FieldMeta(
                type="bool", default=True, label="影响品质等级判定",
                help="false = 暴击经验只体现在展示，品质等级仍按暴击前经验判定。"),
            "rolls_per_craft": FieldMeta(
                type="int", range_min=1, range_max=2, default=1, label="每次打造掷数",
                help="每次打造掷数（1~2）；任一命中即暴击，>1 会显著抬高期望。"),
            "exp_cap": FieldMeta(
                type="str", soft_label=True, label="经验封顶",
                help="none = 不封顶；last_threshold = 封到品质等级阈值末项（保证可达品质 10 但"
                     "不溢出）；也可填数值。"),
            "rng_stream": FieldMeta(
                type="enum", enum=("player",), default="player", label="随机流",
                help="随机流标记；引擎只走批40 玩家级随机流（可注入确定性 RNG 复现）。"),
        },
        help="投料提交时按图纸档掷一次概率，命中给额外品质经验（倍率可配），使高档图纸有机会"
             "冲破常规经验上限达到品质 10 —— **用「投入概率暴击」替代「拉高 cost cap / 强制"
             "扩充材料表」**（决策记录 §七 用户裁定）。全部参数包声明、可调；缺省关闭（不声明"
             "= 行为与既有逐字段一致，且不消耗随机数）。"),
    "random_stat_count": FieldMeta(
        type="obj", label="随机属性条数",
        children={
            "min": FieldMeta(type="int", range_min=0, label="最少"),
            "max": FieldMeta(type="int", range_min=0, label="最多"),
        }),
    "random_set_affix_count": FieldMeta(
        type="obj", label="随机套装词条条数",
        children={
            "min": FieldMeta(type="int", range_min=0, label="最少"),
            "max": FieldMeta(type="int", range_min=0, label="最多"),
        }),
}

# settings.deep_craft 段子字段（在 field_meta.SETTINGS_FIELDS["deep_craft"] 上合并）
DEEP_CRAFT_SEGMENT_FIELDS: Dict[str, FieldMeta] = {
    "enabled": FieldMeta(
        type="bool", default=False, label="是否启用深度打造",
        help="开启后「打造」路径可用；基础合成仍走公用合成层（settings.alchemy.mode）。"),
    "craft_rules": FieldMeta(
        type="obj", children=DEEP_CRAFT_RULE_FIELDS, label="打造规则参数",
        help="等级加权 / 品质经验 / cost 约束的包声明参数（框架不内置业务数值）。"),
    "quality_colors": FieldMeta(
        type="list", label="品质颜色",
        element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str", required=True, label="颜色 ID"),
            "name": FieldMeta(type="str", label="中文名"),
        }),
        help="品质 6 档（白绿蓝紫橙红），概率表与经验基数按该 id 关联。"),
    "quality_exp_by_color": FieldMeta(
        type="obj", soft_label=True, label="品阶经验基数",
        help="材料品质颜色 → 单件品质经验基数（单调递增）；缺省用框架默认表。"),
    "blueprint_grades": FieldMeta(
        type="list", label="图纸档位",
        element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str", required=True, label="档位 ID"),
            "name": FieldMeta(type="str", label="中文名"),
            "level_offset": FieldMeta(type="int", range_min=0, label="品质阶梯行偏移"),
            "cost_cap": FieldMeta(type="int", range_min=0, label="总 cost 上限"),
        }),
        help="铜银金彩四档：行偏移决定品质概率阶梯起点（银/金/彩 = 铜表上移 1/2/3 行），"
             "cost_cap = 该档单次打造总 cost 上限（按档缩放，防低阶材料填满预算）。"),
    "quality_draw_table": FieldMeta(
        type="obj", label="品质概率阶梯",
        children={
            "ladder": FieldMeta(
                type="obj", soft_label=True, label="阶梯行",
                help="行号 → {颜色: 权重}；品质等级 L → 行 L + 该图纸档 level_offset。"
                     "红品质仅第 10 行起出现。"),
        }),
}

# =====================================================================================
# 三、items 条目新增字段（材料 + 图纸）
# =====================================================================================

MATERIAL_CRAFT_KEYS: Tuple[str, ...] = ("material_level", "material_quality", "craft_cost")
BLUEPRINT_KEYS: Tuple[str, ...] = (
    "blueprint_grade", "blueprint_output", "blueprint_slot", "blueprint_recipe",
    "blueprint_level_band", "blueprint_material_slots", "blueprint_fixed_stats",
    "blueprint_random_stat_count", "blueprint_fixed_set_affix",
    "blueprint_random_set_affix_count", "blueprint_random_set_affix_pool",
    "blueprint_passive", "blueprint_learn", "blueprint_cost_cap",
)

ITEMS_MATERIAL_CRAFT_FIELDS: Dict[str, FieldMeta] = {
    "material_level": FieldMeta(
        type="int", range_min=1, label="材料等级",
        help="打造时按占比参与装备等级计算（完全同级材料 → 该级装备）；缺省视为 1。"),
    "material_quality": FieldMeta(
        type="str", soft_label=True, label="材料品质",
        help="品质颜色 id（需先声明档位）：决定单件材料的品质经验基数；缺省最低档。"),
    "craft_cost": FieldMeta(
        type="int", range_min=0, label="材料 cost",
        help="单件投入 cost；缺省回落到 price。总 cost 超图纸档上限 → 拒绝。"),
}

ITEMS_BLUEPRINT_FIELDS: Dict[str, FieldMeta] = {
    "blueprint_grade": FieldMeta(
        type="str", soft_label=True, label="图纸档位",
        help="图纸档 id（需先声明档位）：决定品质概率行偏移与费用上限。"),
    "blueprint_output": FieldMeta(
        type="str", ref_target="item", label="产出物品",
        help="打造产出的装备/物品（items∪equipment 同库）。"),
    "blueprint_slot": FieldMeta(
        type="str", options_ref="settings.slot_defs", label="装备部位",
        help="产出装备的部位（需先在装备槽位里声明）。"),
    "blueprint_recipe": FieldMeta(
        type="str", ref_target="recipe", label="基础合成配方",
        help="图纸引用的配方 id：声明材料需求与标准产出，打造层再加品质/等级。"),
    "blueprint_level_band": FieldMeta(
        type="obj", label="等级带",
        children={
            "min": FieldMeta(type="int", range_min=1, label="最低等级"),
            "max": FieldMeta(type="int", range_min=1, label="最高等级"),
        },
        help="防退化约束①：计算出的装备等级必须落在该区间，否则拒绝（防低阶材料堆预算）。"),
    "blueprint_material_slots": FieldMeta(
        type="list", label="材料槽",
        element=FieldMeta(type="obj", children={
            "role": FieldMeta(type="enum", enum=("main", "free"), label="槽角色"),
            "item": FieldMeta(type="str", ref_target="item", label="指定材料"),
            "tag": FieldMeta(type="str", label="材料标签"),
            "count": FieldMeta(type="int", range_min=1, label="需求件数"),
            "weight": FieldMeta(type="number", range_min=0.0, label="等级占比"),
        }),
        help="固定材料槽（指定物品）+ 自由材料槽（按标签过滤）；主槽占大等级比。"),
    "blueprint_fixed_stats": FieldMeta(
        type="list", label="固定属性",
        element=FieldMeta(type="obj", children={
            "stat": FieldMeta(type="str", label="属性键"),
            "value_rule": FieldMeta(type="str", label="数值规则"),
            "value": FieldMeta(type="number", allow_negative=True, label="固定值"),
        }),
        help="图纸固定 1~3 条属性（原案 §3）；数值可由品质/等级系数缩放（value_rule）。"),
    "blueprint_random_stat_count": FieldMeta(
        type="obj", label="随机属性条数",
        children={
            "min": FieldMeta(type="int", range_min=0, range_max=2, label="最少"),
            "max": FieldMeta(type="int", range_min=0, range_max=2, label="最多"),
        },
        help="随机属性 0~2 条（原案 §3），从相性池抽取。"),
    "blueprint_fixed_set_affix": FieldMeta(
        type="str", label="固定套装词条",
        help="图纸固定 1 条套装词条（原案 §4）。"),
    "blueprint_random_set_affix_count": FieldMeta(
        type="obj", label="随机套装词条条数",
        children={
            "min": FieldMeta(type="int", range_min=0, range_max=2, label="最少"),
            "max": FieldMeta(type="int", range_min=0, range_max=2, label="最多"),
        },
        help="随机套装词条 0~2 条（原案 §4），从相性池抽取。"),
    "blueprint_random_set_affix_pool": FieldMeta(
        type="str", label="随机套装词条池",
        help="随机套装词条的候选池 id（空 = 用相性池）。"),
    "blueprint_passive": FieldMeta(
        type="str", label="固定被动",
        help="图纸固定装备被动 id（原案 §11）。"),
    "blueprint_learn": FieldMeta(
        type="obj", label="学习条件",
        children={
            "item": FieldMeta(type="str", ref_target="item", label="学习所需图纸物品"),
            "job": FieldMeta(type="str", ref_target="job", label="职业要求"),
            "level": FieldMeta(type="int", range_min=1, label="等级要求"),
        },
        help="学习该图纸的条件；学习后持久化到玩家 learned_blueprints（换包同 id 保留）。"),
    "blueprint_cost_cap": FieldMeta(
        type="int", range_min=0, label="cost 上限覆盖",
        help="覆盖图纸档的 cost_cap（0/缺省 = 用档位值）。"),
}

# =====================================================================================
# 四、读段：settings.deep_craft → 归一配置（缺省合并默认；纯函数）
# =====================================================================================
def _as_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _deep_merge(base: Dict[str, Any], over: Mapping[str, Any]) -> Dict[str, Any]:
    """浅层深合并（obj 递归合并；标量/列表显式覆盖）。不改入参。"""
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(dict(out[key]), val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def _merge_rows(defaults: List[Dict[str, Any]], raw: Any) -> List[Dict[str, Any]]:
    """列表形（quality_colors / blueprint_grades）：包声明覆盖同名 id 行，缺省保留。"""
    if not isinstance(raw, list):
        return copy.deepcopy(defaults)
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    by_id = {str(d.get("id")): d for d in defaults}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        merged = _deep_merge(by_id.get(rid, {}), row)
        merged["id"] = rid
        rows.append(merged)
        seen.add(rid)
    for d in defaults:
        if str(d.get("id")) not in seen:
            rows.append(copy.deepcopy(d))
    return rows


def read_deep_craft_settings(settings_raw: object) -> Dict[str, Any]:
    """settings（或 settings.deep_craft 段）→ 深度打造归一配置（纯函数，缺省兜底）。

    入参：settings_raw = settings.json 顶层 dict（或已取出的 deep_craft 段）。
    出参：{enabled, craft_rules, quality_colors, blueprint_grades, quality_draw_table,
      quality_exp_by_color}——
      段缺失/非对象 → 默认表全量（enabled=False）；类型不合法回退默认
      （运行期不炸，越界/引用问题由校验器红拦——对齐 forge_settings 口径）。
    """
    src = _as_map(settings_raw)
    seg = src.get("deep_craft") if "deep_craft" in src else src
    seg = _as_map(seg)

    rules = _deep_merge(DEFAULT_DEEP_CRAFT_RULES, _as_map(seg.get("craft_rules")))
    # 阈值列表：显式合法（非空 list[int]）才覆盖默认。
    raw_th = seg.get("craft_rules") if isinstance(seg.get("craft_rules"), Mapping) else {}
    th = raw_th.get("quality_level_thresholds")
    if isinstance(th, list) and th and all(
        isinstance(x, int) and not isinstance(x, bool) for x in th
    ):
        rules["quality_level_thresholds"] = list(th)

    colors = _merge_rows(DEFAULT_QUALITY_COLORS, seg.get("quality_colors"))
    grades = _merge_rows(DEFAULT_BLUEPRINT_GRADES, seg.get("blueprint_grades"))

    table = _deep_merge(DEFAULT_QUALITY_DRAW_TABLE, _as_map(seg.get("quality_draw_table")))
    if not isinstance(table.get("ladder"), Mapping):
        table["ladder"] = copy.deepcopy(DEFAULT_QUALITY_DRAW_TABLE["ladder"])

    exp_by_color = dict(DEFAULT_QUALITY_EXP_BY_COLOR)
    raw_exp = seg.get("quality_exp_by_color")
    if isinstance(raw_exp, Mapping):
        for k, v in raw_exp.items():
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool):
                exp_by_color[k] = float(v)

    return {
        "enabled": (seg.get("enabled") if isinstance(seg.get("enabled"), bool) else False),
        "craft_rules": rules,
        "quality_colors": colors,
        "blueprint_grades": grades,
        "quality_draw_table": table,
        "quality_exp_by_color": exp_by_color,
    }


def grade_of(config: Mapping[str, Any], grade_id: object) -> Optional[Dict[str, Any]]:
    """图纸档位行（按 id；缺失 → None）。"""
    for row in config.get("blueprint_grades") or []:
        if isinstance(row, Mapping) and row.get("id") == grade_id:
            return dict(row)
    return None
