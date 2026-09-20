"""M9 批次0·路0B：settings.forge 段解析 + items 材料类字段扩展定义（ITEMS_FORGE_FIELDS）。

文件：qbot_rpg/content/forge_settings.py
创建：2026-08-30
作者：Hermes 子agent-0B（M9 锻造数据层 路0B）
功能：锻造 settings.forge 段读取（read_forge_settings，缺省合并默认值）+ items.json
      材料类扩展字段定义（ITEMS_FORGE_FIELDS：material_tier 两档 + source 来源标签）
      + settings.forge 段 FieldMeta（FORGE_SETTINGS_FIELD_DEFS，供主 agent 收口合并
      SETTINGS_FIELDS["forge"]）+ 素材来源提示文本归一辅助（resolve_source_text）。

依据：细化_2c2a §1.4（S-01~S-05 settings 段）+ 细化_2c2c §2.1（TIER-03a material_tier
      两档元数据 / SOUR-00 来源标签总则）+ 定稿 §12.4（forge_fee/synth_ratio_3to1/
      straight_forge/exp_per_forge 默认与可配语义）
      + docs/m9_shared_contract.md §三（ForgeSettings 全字段表）/ §八（items/settings
      扩展契约：material_tier enum normal/rare + source str + settings.forge 段形态）。
模式参考：
  - qbot_rpg/content/alchemy_settings.py（M8 路0B：settings.alchemy 段解析口径——
    P-6 段缺失/空 → 默认值兜底不报错；键名照契约原样含中文键；读段从 data["xxx"] 取段）
  - qbot_rpg/content/field_meta.py ITEMS_ALCHEMY_FIELDS（字段扩展形态：宽松登记防误拦
    既有内容包——type 为 str 不设枚举 / 新增键不设 required）
  - qbot_rpg/world/battle_boundary.py DeathPenaltyConfig.from_settings（settings 读段
    容错缺省：类型不合法字段回退默认值，运行期兜底不炸，越界/引用问题由校验器硬拦）

铁律：本文件零 NoneBot import、纯函数确定性、无 IO/无定时器睡眠调用、平台无关；只读依赖
      qbot_rpg.content.models（FieldMeta 数据类）。字段定义在本文件自包含持有（对齐
      field_meta 文件头铁律「只提供字段口径默认值」）——field_meta.py/loader.py/fixtures
      由主 agent 收口接线，本文件不改动任何既有文件。

【工程补白】清单（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  （已删除）原 `decompose_rate` 默认表（炼金定稿 L418 六档）随批70 清账移除——
       真源 = `settings.alchemy.decompose_rate`（`core/gem_wallet.py:190`），forge 段不再重复。
  F-2  forge_fee / exp_per_forge 为 str|int 联合形态（定稿 L353/L357：字符串公式或整数），
       FieldMeta 无联合类型 → 登记 type="str" + soft_label=True（永不红拦，防 int 合法值
       被 R-1 误拦；多形态由引擎运行期处理，对齐 seed 字段 soft_label 口径）。
  F-3  resolve_source_text 兜底文本 DEFAULT_UNKNOWN_SOURCE="来源未知"（SOUR-00 要求每条
       素材标注来源；无标注时的确定性兜底，调用方可自行拼接/省略）。
"""

from __future__ import annotations

import copy
from typing import Dict, Mapping, Optional, TypeGuard

from qbot_rpg.content.models import FieldMeta
from qbot_rpg.data.temper_stats import DEFAULT_ESSENCE_RATE, normalize_essence_config

# =====================================================================================
# 常量：settings.forge 段默认值（共享契约 §三 ForgeSettings 表 + 定稿 §12.4）
# =====================================================================================

# 批26 α3：装备增幅技能（skill_amp）全局上下限默认值（CakeGame 装备附加Re《核心配置》
# 的 最小/最大增幅 -90/90 与 最小/最大冷却 -50/100 做**框架默认值**，可经
# settings.forge.skill_amp_bounds 覆盖）。判定逻辑（校验器/引擎）一律读本表或包声明，
# 不硬编码数值——「不硬编码」的落点即此处 + FORGE_SETTINGS_FIELD_DEFS。
DEFAULT_SKILL_AMP_BOUNDS: Dict[str, int] = {
    "damage_min": -90,
    "damage_max": 90,
    "cooldown_min": -50,
    "cooldown_max": 100,
}
_SKILL_AMP_BOUND_KEYS: tuple = ("damage_min", "damage_max", "cooldown_min", "cooldown_max")

# settings.forge 段默认值（共享契约 §三 ForgeSettings：S-01~05 + 2c2d 补白键 + P1-1 裁决可配档位）
FORGE_SETTINGS_DEFAULTS: Dict[str, object] = {
    "forge_fee": "节点等级×10",          # S-01（str|int）
    "synth_ratio_3to1": True,           # S-02（P1 3:1 合成开关）
    "straight_forge": True,             # S-03（直锻模式）
    "exp_per_forge": "节点等级×2",       # S-05（str|int）
    "sets_enabled": True,               # 2c2d 补白键（P1 套装开关）
    "augments_enabled": True,           # 2c2d 补白键（P2 客制开关）
    "skill_amp_bounds": DEFAULT_SKILL_AMP_BOUNDS,  # 批26 α3：增幅技能上下限（可覆盖）
    "set_piece_counts": [2, 3, 5],  # P1-1 裁决：套装档位集合可配（默认 2/3/5）
    "set_tier_exact": True,         # P1-1 裁决：达到档位才激活；false=未达也可激活低档
    # 2026-09-14：满套/件数上限可选显式配置；None = 未配置（由 forge_sets.
    # derive_set_max_pieces 从 settings.slot_defs 防具部位推导），正整数 = 显式上限
    "set_max_pieces": None,
    # 批57 · 精粹产出率 `essence_rate`（原案 §12/§14；报告 §3.1 公式 + 主 agent ①/② 裁定）。
    # 缺省 enabled=False → 不启用精粹，与现状逐字段一致。**与「材料回收分解率」**
    # 分键、语义相反不可合键**（报告 C-5：材料回收随生产等级递增 / 精粹随品质正向）；
    # 材料回收的真源 = `settings.alchemy.decompose_rate`（批70 已删 forge 段重复键）。
    "essence_rate": dict(DEFAULT_ESSENCE_RATE),
}

# settings.forge 段可解析键（read_forge_settings 遍历顺序，照共享契约 §八 settings.json 形态）
FORGE_SETTINGS_KEYS: tuple = (
    "forge_fee",
    "synth_ratio_3to1",
    "straight_forge",
    "exp_per_forge",
    "sets_enabled",
    "augments_enabled",
    "set_piece_counts",
    "set_tier_exact",
    # 2026-09-14 用户拍板「套装档位不要硬编码数量」：满套/件数上限可选显式配置；
    # 默认 None（未配置）→ forge_sets.derive_set_max_pieces 从 settings.slot_defs
    # 防具部位推导（推导不出=不设上限）
    "set_max_pieces",
    # 批26 α3：装备增幅技能上下限（obj；空/缺失 → DEFAULT_SKILL_AMP_BOUNDS）
    "skill_amp_bounds",
    # 批57：精粹产出率段（obj；缺省 enabled=False → 不启用）
    "essence_rate",
)

# 素材档位两档（细化_2c2c TIER-03a：normal/rare；与装备品质四档 TIER-03b 不混用）
MATERIAL_TIER_VALUES: tuple = ("normal", "rare")

# 素材来源提示兜底文本（【工程补白 F-3】SOUR-00 无标注时的确定性兜底）
DEFAULT_UNKNOWN_SOURCE: str = "来源未知"

# =====================================================================================
# items.json 材料类扩展字段（共享契约 §八 items/settings 扩展契约；供主 agent 收口
# items_fields.update(ITEMS_FORGE_FIELDS) 使用，宽松登记防误拦既有内容包）
# =====================================================================================
ITEMS_FORGE_FIELDS: Dict[str, FieldMeta] = {
    # material_tier 素材档位两档（TIER-03a：normal/rare，独立于装备品质四档 TIER-03b）
    # —— 新增键不设 required，既有内容包材料类无此字段 → 默认放行（§2.3 未知字段兜底）；
    #    缺省语义 normal（普通基础材料），行覆写 > items 元数据（M-03/AR-3 双源仲裁风格）
    # 批68 · §4 字段中文名 + Tip：补中文名与一句话说明（修前界面裸露英文键、无说明）。
    "material_tier": FieldMeta(type="enum", enum=MATERIAL_TIER_VALUES, default="normal",
                               label="材料档位",
                               help="素材档：普通(normal) / 稀有(rare)；缺省普通。"),
    # source 素材来源标签（SOUR-00：采集点/怪物/商店，显示文本）；str 结构校验不设枚举
    # 防误拦（既有 items 无此键 → 放行；来源文本由引擎消费，宽严归校验器 V10 引用层）
    # 批68 · §4 Tip：补一句话说明。（中文名按门禁语义保留原始键兜底实例，见报告）
    "source": FieldMeta(type="str", help="素材来源标签（采集点/怪物/商店等，自由文本）。"),
}

# =====================================================================================
# settings.forge 段 FieldMeta（对齐 ALCHEMY_SETTINGS_FIELD_DEFS 形态；供主 agent 收口
# SETTINGS_FIELDS["forge"] = forge_settings_meta()）
# =====================================================================================
FORGE_SETTINGS_FIELD_DEFS: Dict[str, FieldMeta] = {
    # S-01 forge_fee（定稿 L353）：str|int 联合（"节点等级×10" 或整数金币）——soft_label
    # 永不红拦（【工程补白 F-2】，防 int 合法值被 R-1 type=str 误拦）
    "forge_fee": FieldMeta(type="str", soft_label=True),
    # S-02 synth_ratio_3to1（定稿 L354）：P1 3:1 合成开关
    "synth_ratio_3to1": FieldMeta(type="bool", default=True),
    # S-03 straight_forge（定稿 L355）：直锻模式（小白 1 步 / 深度预览 2 步）
    "straight_forge": FieldMeta(type="bool", default=True),
    # S-05 exp_per_forge（定稿 L357）：str|int 联合（"节点等级×2" 或整数）——soft_label 永不红拦
    "exp_per_forge": FieldMeta(type="str", soft_label=True),
    # 2c2d 补白键：P1 套装开关 / P2 客制开关（共享契约 §三 sets_enabled/augments_enabled）
    "sets_enabled": FieldMeta(type="bool", default=True),
    "augments_enabled": FieldMeta(type="bool", default=True),
    # P1-1 裁决（2026-08-30）：套装技能档位集合可配（默认 [2,3,5]；可配 [1,4]/[7,8]/[3,6,9,12]）
    "set_piece_counts": FieldMeta(type="list", element=FieldMeta(type="int")),
    # P1-1 裁决：激活语义（true=达到档位才激活；false=未达到也能激活低档）
    "set_tier_exact": FieldMeta(type="bool", default=True),
    # 2026-09-14 用户拍板：满套/件数上限可选显式配置（正整数；缺省由
    # forge_sets.derive_set_max_pieces 从 settings.slot_defs 防具部位推导）
    "set_max_pieces": FieldMeta(type="int", range_min=1),
    # 批26 α3：装备增幅技能全局上下限（可经 settings.forge.skill_amp_bounds 覆盖；
    # 默认值 = DEFAULT_SKILL_AMP_BOUNDS，判定逻辑不硬编码）
    "skill_amp_bounds": FieldMeta(type="obj", children={
        "damage_min": FieldMeta(type="int", default=-90, label="伤害增幅下限"),
        "damage_max": FieldMeta(type="int", default=90, label="伤害增幅上限"),
        "cooldown_min": FieldMeta(type="int", default=-50, label="冷却增幅下限"),
        "cooldown_max": FieldMeta(type="int", default=100, label="冷却增幅上限"),
    }),
    # 批57 · 精粹产出率（原案 §12/§14；报告 §3.1）。**与 decompose_rate 分键**：
    # decompose_rate = 材料回收（随生产等级递增）；essence_rate = 精粹产出（随品质正向）。
    "essence_rate": FieldMeta(type="obj", label="精粹产出率", help=(
        "分解打造装备产出的「装备精粹」：投入价值 V × k1 × k2 × β^色序。"
        "与「分解回收率 decompose_rate」（材料回收）**必须是两个键**——"
        "前者随生产等级递增、后者随品质正向，语义相反不可合并。"
        "缺省 enabled=false → 不启用精粹，与现状逐字段一致。"), children={
        "enabled": FieldMeta(type="bool", default=False, label="启用精粹",
                             help="关闭（缺省）= 不产出精粹，与现状逐字段一致。"),
        "v_basis": FieldMeta(type="enum",
                             enum=("node_materials", "item_price", "fixed", "level_scaled"),
                             label="投入价值口径",
                             help="node_materials（缺省）= 蓝图节点固定材料价值（报告 V1）；"
                                  "item_price = 物品定义 price；fixed / level_scaled 见下。"),
        "v_fixed": FieldMeta(type="number", default=0.0, label="固定投入价值",
                             help="v_basis=fixed 时的常量。"),
        "v_per_level": FieldMeta(type="number", default=0.0, label="每级投入价值",
                                 help="v_basis=level_scaled 时：装备等级 × 本值。"),
        "k1": FieldMeta(type="number", default=0.35, label="材料价值基准系数",
                        help="报告 N5 区间 0.30–0.40，缺省 0.35。"),
        "k2": FieldMeta(type="number", default=0.50, label="图纸档基准系数",
                        help="报告 N5 区间 0.40–0.60，缺省 0.50；逐档可用 grade_of 覆盖。"),
        "grade_of": FieldMeta(type="obj", label="图纸档系数覆盖",
                              help="{图纸档 id: k2 值}；留空 = 统一用 k2。"),
        "beta": FieldMeta(type="number", default=1.2, label="色序系数",
                          help="品质越高单件回收价值越高的**正向**系数（主 agent C-7 裁定，"
                               "缺省 1.2；原 β=0.6 的「衰减闸门」已判定无效）。"),
        "color_order": FieldMeta(type="obj", label="色序映射覆盖",
                                 help="{品质色 id: 序}；留空 = 按 deep_craft.quality_colors "
                                      "声明顺序派生。"),
        "rounding": FieldMeta(type="enum", enum=("floor", "round", "ceil"), label="取整",
                              help="整体取整一次（不逐材料 floor）。"),
        "temper_refund": FieldMeta(type="int", range_min=0, default=800, label="每点淬炼返还",
                                   help="已淬炼件分解时每点返还的精粹（绝对）；"
                                        "必须 < temper.cost_per_point.essence（否则可套利）。"),
        "refund_decay": FieldMeta(type="number", label="返还衰减系数",
                                  help="每点实际返还 = 本值 × 衰减^(已投点/总上限)；"
                                       "随淬炼量下降，堵死「淬炼→分解→再淬炼」循环。"),
        "scope": FieldMeta(type="enum", enum=("crafted_equipment", "all_equipment"),
                           label="分解对象范围",
                           help="crafted_equipment（缺省）= 仅打造装备可出精粹"
                                "（防商店/掉落廉价装刷精粹）。"),
        "cap_per_item": FieldMeta(type="int", range_min=0, label="单件产出上限",
                                  help="软闸门；留空 = 不设。"),
        "essence_currency": FieldMeta(type="str", label="精粹货币键",
                                      help="须登记进 settings.currencies（否则入账被拒）。"),
    }),
}


def forge_settings_meta() -> FieldMeta:
    """settings.forge 段 FieldMeta（type=obj + 全字段 children；合并进 SETTINGS_FIELDS）。"""
    return FieldMeta(type="obj", children=FORGE_SETTINGS_FIELD_DEFS)


# =====================================================================================
# 工具：类型判定（排除 bool——bool 是 int 子类）
# =====================================================================================
def _is_int(v: object) -> TypeGuard[int]:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_nonneg_int(v: object) -> TypeGuard[int]:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _nonempty_str(v: object) -> bool:
    return isinstance(v, str) and bool(v.strip())


# =====================================================================================
# read_forge_settings：settings.forge 段读取（缺省合并默认值，纯函数确定性）
# =====================================================================================
def read_forge_settings(settings_raw: object) -> Dict[str, object]:
    """解析 settings.forge 段，缺省合并默认值（共享契约 §三 ForgeSettings 表）。

    入参：
      settings_raw —— settings 模块原始数据（Mapping，取 data["forge"] 段；None/非 Mapping
                      /段缺失/段为空 → 全默认值兜底，对齐 alchemy_settings P-6 口径）。
    出参：
      合并后的 dict（键序照 FORGE_SETTINGS_KEYS）：forge_fee / synth_ratio_3to1 /
      straight_forge / exp_per_forge / sets_enabled / augments_enabled。
    核心逻辑（纯函数、确定性、无副作用）：
      - 段缺失/非对象 → FORGE_SETTINGS_DEFAULTS 深拷贝全量返回（不报错，对齐炼金读段模式）。
      - 段存在 → 逐键取值：显式键覆盖默认；类型不合法回退默认（运行期兜底不炸，
        越界/引用问题由校验器硬拦——对齐 battle_boundary from_settings 容错口径）。
      - decompose_rate：**批70 起不再识别**（重复键清账）——真源 =
        `settings.alchemy.decompose_rate`；包内残留由校验器黄提示指向新位置。
      - forge_fee / exp_per_forge：非空 str 或非负 int 生效，其余回退默认。
      - 布尔键（synth_ratio_3to1/straight_forge/sets_enabled/augments_enabled）：
        仅 bool 生效，其余回退默认。
    """
    out: Dict[str, object] = copy.deepcopy(FORGE_SETTINGS_DEFAULTS)
    if not isinstance(settings_raw, Mapping):
        return out
    forge = settings_raw.get("forge")
    if not isinstance(forge, Mapping):
        return out  # 段缺失/空/非对象 → 全默认值兜底（alchemy_settings P-6 对齐）

    # ---- S-01 forge_fee：非空 str 或非负 int ----
    v = forge.get("forge_fee")
    if _nonempty_str(v) or _is_nonneg_int(v):
        out["forge_fee"] = v

    # ---- S-02/S-03 + 2c2d 补白键：仅 bool 生效 ----
    for key in ("synth_ratio_3to1", "straight_forge", "sets_enabled", "augments_enabled"):
        if isinstance(forge.get(key), bool):
            out[key] = forge[key]

    # ---- 批70 · S-04 `decompose_rate` **已删除**（登记却不生效的重复键）----
    # 真源 = `settings.alchemy.decompose_rate`（消费点 `core/gem_wallet.py:190`）。
    # 迁移：原 `settings.forge.decompose_rate` 的写法无效 → 改到 `settings.alchemy.decompose_rate`。
    # 此处**不再合并/登记**该键；包内残留时由校验器黄提示（`_check_forge_settings_migration`）。

    # ---- S-05 exp_per_forge：非空 str 或非负 int ----
    v = forge.get("exp_per_forge")
    if _nonempty_str(v) or _is_nonneg_int(v):
        out["exp_per_forge"] = v

    # ---- P1-1 裁决（2026-08-30）：set_piece_counts 档位集合可配（正整数列表）----
    spc = forge.get("set_piece_counts")
    if isinstance(spc, (list, tuple)) and spc:
        cleaned = [x for x in spc if isinstance(x, int) and not isinstance(x, bool) and x >= 1]
        if cleaned:
            out["set_piece_counts"] = sorted(set(cleaned))

    # ---- P1-1 裁决：set_tier_exact 激活语义（仅 bool 生效）----
    if isinstance(forge.get("set_tier_exact"), bool):
        out["set_tier_exact"] = forge["set_tier_exact"]

    # ---- 2026-09-14：set_max_pieces 满套/件数上限显式配置（仅正整数生效；
    #      未配置保持默认 None，由 forge_sets.derive_set_max_pieces 从 slot_defs 推导）----
    smp = forge.get("set_max_pieces")
    if _is_int(smp) and smp >= 1:
        out["set_max_pieces"] = smp

    # ---- 批26 α3：skill_amp_bounds 上下限（obj；逐键仅 int 生效，缺省保留默认）----
    sab = forge.get("skill_amp_bounds")
    if isinstance(sab, Mapping):
        bounds = dict(DEFAULT_SKILL_AMP_BOUNDS)
        for k in _SKILL_AMP_BOUND_KEYS:
            if _is_int(sab.get(k)):
                bounds[k] = int(sab[k])
        out["skill_amp_bounds"] = bounds

    # ---- 批57：essence_rate 精粹产出率（走 data 层唯一归一逻辑；缺省 enabled=false）----
    out["essence_rate"] = normalize_essence_config(forge.get("essence_rate"))

    return out


def read_skill_amp_bounds(settings_raw: object) -> Dict[str, int]:
    """读取 settings.forge.skill_amp_bounds 上下限（批26 α3；缺省 → 框架默认）。

    入参 settings_raw：settings 模块原始数据（Mapping，取 ["forge"]["skill_amp_bounds"]；
    None/非 Mapping/段缺失 → DEFAULT_SKILL_AMP_BOUNDS）。逐键仅非 bool int 生效，
    其余回退默认（运行期容错不炸；非法形态由校验器红拦）。纯函数、无副作用。
    """
    out = dict(DEFAULT_SKILL_AMP_BOUNDS)
    if not isinstance(settings_raw, Mapping):
        return out
    forge = settings_raw.get("forge")
    if not isinstance(forge, Mapping):
        return out
    sab = forge.get("skill_amp_bounds")
    if isinstance(sab, Mapping):
        for k in _SKILL_AMP_BOUND_KEYS:
            if _is_int(sab.get(k)):
                out[k] = int(sab[k])
    return out


# =====================================================================================
# resolve_source_text：素材来源提示文本归一（SOUR-00 / M-04 / PROG-06/07）
# =====================================================================================
def resolve_source_text(
    material_row: Optional[Mapping[str, object]] = None,
    items_entry: Optional[Mapping[str, object]] = None,
    *,
    fallback: str = DEFAULT_UNKNOWN_SOURCE,
) -> str:
    """素材来源提示文本归一（细化_2c2c SOUR-00 / 2c2a M-04 / PROG-06/07）。

    优先级（双源仲裁风格，行覆写 > items 元数据，对齐 M-03/AR-3）：
      ① 素材需求行 source_override（M-04，forge 素材行显式覆写）——非空 str 生效；
      ② items.json 材料类条目 source（来源标签：采集点/怪物/商店）——非空 str 生效；
      ③ fallback 默认文本（缺省 DEFAULT_UNKNOWN_SOURCE="来源未知"，【工程补白 F-3】）。

    入参：
      material_row —— forge 节点 materials[] 行（Mapping；取 source_override）；None 跳过。
      items_entry  —— items.json 材料类条目（Mapping；取 source）；None 跳过。
      fallback     —— 两者皆缺/空时的确定性兜底文本（调用方可按需覆写或置空省略拼接）。
    出参：确定性 str（trimmed），无副作用。
    用途：缺件提示（PROG-02「缺：火龙鳞×2（来源：火龙掉落/商店）」）/ /图纸 分支素材提示
          （PROG-06「雷剑 ← 雷兽牙（雷兽掉落）」）消费方直接拼接。
    """
    if isinstance(material_row, Mapping):
        ov = material_row.get("source_override")
        if _nonempty_str(ov):
            return str(ov).strip()
    if isinstance(items_entry, Mapping):
        src = items_entry.get("source")
        if _nonempty_str(src):
            return str(src).strip()
    return fallback


__all__ = [
    # 常量 / 默认值
    "DEFAULT_SKILL_AMP_BOUNDS",
    "FORGE_SETTINGS_DEFAULTS",
    "FORGE_SETTINGS_KEYS",
    "MATERIAL_TIER_VALUES",
    "DEFAULT_UNKNOWN_SOURCE",
    # 字段定义
    "ITEMS_FORGE_FIELDS",
    "FORGE_SETTINGS_FIELD_DEFS",
    "forge_settings_meta",
    # 读段 + 来源归一
    "read_forge_settings",
    "read_skill_amp_bounds",
    "resolve_source_text",
]
