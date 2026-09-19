"""装备数值键空间注册表（批⑧ 装备接线收口 · 2026-09-12）。

唯一源（single source of truth）：凡「物品 def 数值字段 → 实例 stats_bonus →
聚合 / 战斗桥 / 展示 / 编辑器字段表」各处的键清单，一律从这里派生。
新增词条 = 本文件加一行（转换/聚合/桥按分层规则自动生效；展示与编辑器自动跟进）。

分层（data 层纯数据模块：零 import、零 IO——content/core/commands 全层可依赖；
字段表 content/field_meta 也要 import 本表，G0 依赖矩阵 content→{data}，
故注册表落 data 层而非 core 层）。

- FLAT   白值加算键：聚合进 attributes.bonus["flat"]（语义=数值加算）。
- PCT    百分比键：def 侧以 "xxx_pct" 命名（单位=百分点，5=+5%）；聚合端拆后缀
         进 attributes.bonus["pct"]["xxx"]；落档/实例层保留 "_pct" 全键。
- COMBAT 战斗直读键：不进属性管线；由 core/pvp._combatant_of 桥进战斗 combatant。
- PLACEHOLDER 占位键：**只登记字段 + 展示**，明确**不接引擎**（不进属性管线、不进战斗桥）。

批43 · 强化特殊词条族（原案 §7 + 决策记录 §一 H3；键空间唯一源仍在本文件）：
- **百分比加成**：复用既有 `_pct` 键族（atk_pct/dfn_pct/hp_pct/mp_pct）——
  `route_bonus_into` 已把 "..._pct" 拆进 attributes.bonus["pct"]，无需新键、无需新路由。
- **回复强化**   `heal_amp_pct`        见下 help：语义=治疗效果加成（百分点）。
- **减益概率提升** `debuff_chance_pct`  见下 help：语义=对敌方施加减益的概率加成（百分点）。
- **增益概率提升** `buff_chance_pct`    见下 help：语义=对己方施加增益的概率加成（百分点）。
- **弱点伤害增加** `weakness_dmg_pct`   见下 help：语义=命中弱点时的伤害加成（百分点）。
  以上四键归 PCT 档（复用 `_pct` 拆层：聚合/展示自动跟进）；**引擎消费口径见批43 报告**
  （现状=聚合 + 展示均已承载，专属战斗消费点未接，属**如实登记的缺口**，非本文件可补）。
- **冷却缩减**   `cooldown_reduction_pct` 归 PLACEHOLDER 档：**占位**——只登记键 + 编辑
  器/展示可见，**明确不接引擎**（不进 pct 拆层、无任何消费点）。原案 §7 明文「冷却缩减
  留成占位属性」。

批22 · A3 常驻战斗词条（全部归 COMBAT 档；逐条归属与数值口径）：
- absorb_hp     ％    吸血比：造成伤害 × absorb_hp% 回血（上限 100），伤害扣除后由
                       battle 消费（不进属性管线、不属于 effects.lifesteal 主动效果）。
- immune_dmg    ％    免伤比：受到的伤害 ×(1 − immune_dmg%)（上限 100），作用于
                       防御/格挡/乱数之后的 raw，与管线 mitigation 阶段叠乘（互不替代）。
- pierce_val    点    物穿值：目标物理防御先做加算削减 max(0, dfn − pierce_val)。
- pierce_pct    ％    物穿比：再对削减后的防御乘算 (1 − pierce_pct%)；与 type_affinity/
                       effects 的既有 pierce 加算后统一封顶 0.6（既有 cap，不放宽）。
- mag_pierce_val 点   法穿值：魔法攻击（attack_type=="magic"）时替代 pierce_val。
- mag_pierce_pct ％   法穿比：魔法攻击时替代 pierce_pct。
物/法穿口径 = 先加算（值）后乘算（比），作用键与 stats.json 战斗减伤键同源
（battle stat_map.def_con，缺省 con；玩家 dfn/con 双写见 core/pvp._combatant_of）。
无这些键时战斗逐字段与旧行为一致（bridge 只映射非零项）。

接线现状（批⑧）：
- 实例化：assembly/context.add_item、commands/shop_tx._new_default_instance → extract_bonus()。
- 聚合：core/equipment.aggregate_bonus → route_bonus_into()（flat/pct 拆层）。
- 战斗桥：core/pvp._combatant_of → combatant_updates()（crit 百分点可负、耳栓封顶 2、
  超会心/属性会心封顶 3）。
- 展示：commands/basic_commands._item_stat_parts；编辑器：content/field_meta 派生。

历史：原三处手写键表（context 13 键 / shop_tx 12 键 / 详情面板 12 键）互相漂移，
crit 与全部 _pct 键漏转 → 装备词条悬空（2026-09-12 批⑧ 勘察实证并收口）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Tuple

__all__ = [
    "GEAR_FLAT_KEYS",
    "GEAR_PCT_KEYS",
    "GEAR_COMBAT_KEYS",
    "GEAR_COMBAT_PCT_KEYS",
    "GEAR_COMBAT_VALUE_KEYS",
    "GEAR_PLACEHOLDER_KEYS",
    "GEAR_NUMERIC_KEYS",
    "GEAR_DISPLAY_KEYS",
    "GEAR_LABELS_ZH",
    "GEAR_HELP_ZH",
    "PCT_SUFFIX",
    "COMBAT_TO_COMBATANT",
    "extract_bonus",
    "route_bonus_into",
    "combatant_updates",
]

PCT_SUFFIX: str = "_pct"

# 白值加算键（聚合进 attributes.bonus["flat"]；def 旧键保留双兼容）
GEAR_FLAT_KEYS: Tuple[str, ...] = (
    "atk", "def", "dfn", "hp", "mp", "str", "con", "agi", "foc", "spr", "lck", "spd", "mag",
)
# 百分比键（单位=百分点；聚合端拆 "_pct" 后缀）
# 批43：追加强化特殊词条四键（回复强化/减益概率/增益概率/弱点伤害）——归 PCT 档复用拆层。
GEAR_PCT_KEYS: Tuple[str, ...] = (
    "atk_pct", "dfn_pct", "hp_pct", "mp_pct",
    "heal_amp_pct", "debuff_chance_pct", "buff_chance_pct", "weakness_dmg_pct",
)
# 战斗直读键（pvp 桥 → combatant）：会心(可负) / 耳栓 / 超会心 / 属性会心
#   + 批22 · A3 常驻战斗词条（吸血/免伤/物穿/法穿）——分层归属见模块 docstring。
GEAR_COMBAT_KEYS: Tuple[str, ...] = (
    "crit", "earplug", "super_crit_lv", "elem_crit_lv",
    "absorb_hp", "immune_dmg", "pierce_val", "pierce_pct",
    "mag_pierce_val", "mag_pierce_pct",
)
# 批22 · A3：COMBAT 键内部再分「显示口径」（单位/范围仅供编辑器提示；聚合/桥口径见函数）。
GEAR_COMBAT_PCT_KEYS: Tuple[str, ...] = (
    "absorb_hp", "immune_dmg", "pierce_pct", "mag_pierce_pct",
)
GEAR_COMBAT_VALUE_KEYS: Tuple[str, ...] = ("pierce_val", "mag_pierce_val")
# 批43：占位键——**只登记字段 + 展示**，明确**不接引擎**（route_bonus_into 显式跳过）。
# 冷却缩减 `cooldown_reduction_pct`：原案 §7「冷却缩减留成占位属性」。
GEAR_PLACEHOLDER_KEYS: Tuple[str, ...] = ("cooldown_reduction_pct",)
# 数值键全集（实例化转换 / 展示 / 编辑器遍历用）
GEAR_NUMERIC_KEYS: Tuple[str, ...] = GEAR_FLAT_KEYS + GEAR_PCT_KEYS + GEAR_COMBAT_KEYS
# 展示/实例化全集 = 数值键 + 占位键（占位键要能被 extract_bonus 保留、被详情面板展示，
# 但不参与 route_bonus_into 分层 → 不接引擎）。
GEAR_DISPLAY_KEYS: Tuple[str, ...] = GEAR_NUMERIC_KEYS + GEAR_PLACEHOLDER_KEYS

# 战斗桥映射：(聚合 flat 键, combatant 键, 封顶) —— None=不封顶（crit 可负）
COMBAT_TO_COMBATANT: Tuple[Tuple[str, str, Any], ...] = (
    ("crit", "crit_bonus", None),
    ("earplug", "earplug", 2),
    ("super_crit_lv", "super_crit_lv", 3),
    ("elem_crit_lv", "elem_crit_lv", 3),
    # 批22 · A3：百分比词条封顶 100（吸血/免伤/穿透比）；穿值不封顶（引擎按 max(0, def-val)）。
    ("absorb_hp", "absorb_hp", 100),
    ("immune_dmg", "immune_dmg", 100),
    ("pierce_val", "pierce_val", None),
    ("pierce_pct", "pierce_pct", 100),
    ("mag_pierce_val", "mag_pierce_val", None),
    ("mag_pierce_pct", "mag_pierce_pct", 100),
)

# 中文 label（展示 / 编辑器共用）
GEAR_LABELS_ZH: Dict[str, str] = {
    "atk": "攻击", "def": "防御", "dfn": "防御", "hp": "生命", "mp": "法力",
    "str": "力量", "con": "体质", "agi": "敏捷", "foc": "专注", "spr": "精神",
    "lck": "幸运", "spd": "速度", "mag": "法强",
    "atk_pct": "攻击%", "dfn_pct": "防御%", "hp_pct": "生命%", "mp_pct": "法力%",
    # 批43 强化特殊词条（stem 供详情面板 `_item_stat_parts` 拆后缀取用；全键供编辑器字段表）
    "heal_amp": "回复强化", "heal_amp_pct": "回复强化%",
    "debuff_chance": "减益概率", "debuff_chance_pct": "减益概率%",
    "buff_chance": "增益概率", "buff_chance_pct": "增益概率%",
    "weakness_dmg": "弱点伤害", "weakness_dmg_pct": "弱点伤害%",
    "cooldown_reduction": "冷却缩减", "cooldown_reduction_pct": "冷却缩减%",
    "crit": "会心", "earplug": "耳栓", "super_crit_lv": "超会心", "elem_crit_lv": "属性会心",
    "absorb_hp": "吸血%", "immune_dmg": "免伤%",
    "pierce_val": "物穿值", "pierce_pct": "物穿%",
    "mag_pierce_val": "法穿值", "mag_pierce_pct": "法穿%",
}

# 中文 help（编辑器字段说明气泡；批22 · A3/D1 新增词条；批43 强化特殊词条族）。
# 只登记新增键——既有键的说明由内容包声明提供（避免改动既有元数据值）。
GEAR_HELP_ZH: Dict[str, str] = {
    "absorb_hp": "造成伤害后按该比例回复自身生命（%）。",
    "immune_dmg": "受到的伤害按该比例减免（%）。",
    "pierce_val": "无视目标等量物理防御（点）。",
    "pierce_pct": "按比例无视目标物理防御（%）。",
    "mag_pierce_val": "魔法攻击无视目标等量防御（点）。",
    "mag_pierce_pct": "魔法攻击按比例无视目标防御（%）。",
    # 批43 强化特殊词条族（语义/上限/承载口径；上限=0-500 百分点，同既有 _pct 档）。
    "heal_amp_pct": "回复强化：治疗/回复效果按该比例提升（百分点，0-500）。"
                    "承载=属性 pct 层聚合 + 展示；专属战斗消费点未接（批43 缺口登记）。",
    "debuff_chance_pct": "减益概率提升：对敌方施加减益效果的基础概率上浮（百分点，0-500）。"
                         "承载=属性 pct 层聚合 + 展示；专属消费点未接（批43 缺口登记）。",
    "buff_chance_pct": "增益概率提升：对己方施加增益效果的基础概率上浮（百分点，0-500）。"
                       "承载=属性 pct 层聚合 + 展示；专属消费点未接（批43 缺口登记）。",
    "weakness_dmg_pct": "弱点伤害增加：命中目标弱点时的伤害按该比例提升（百分点，0-500）。"
                        "承载=属性 pct 层聚合 + 展示；专属伤害乘区未接（批43 缺口登记）。",
    # 占位键（原案 §7 明文）
    "cooldown_reduction_pct": "【占位】冷却缩减（百分点，0-500）：仅登记与展示，"
                              "明确不接任何引擎消费（原案 §7「冷却缩减留成占位属性」）。",
}


def extract_bonus(item_cfg: Mapping[str, Any]) -> Dict[str, float]:
    """def 数值字段 → stats_bonus（FLAT+PCT+COMBAT+占位 全取；0/布尔/非数值排除）。

    批43：遍历 `GEAR_DISPLAY_KEYS`（含占位键）——占位键要能被实例保留并展示，
    但**不进属性管线**（route_bonus_into 显式跳过）。
    """
    out: Dict[str, float] = {}
    for k in GEAR_DISPLAY_KEYS:
        v = item_cfg.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
            out[k] = float(v)
    return out


def route_bonus_into(
    bonus: Mapping[str, Any],
    flat: MutableMapping[str, float],
    pct: MutableMapping[str, float],
) -> None:
    """stats_bonus 键表按层路由："..._pct" → pct[stem]（百分点）；其余 → flat。

    批22 · A3：COMBAT 键即使名字以 "_pct" 结尾（pierce_pct/mag_pierce_pct）也**必须留
    在 flat**（COMBAT 分层 = 不进属性管线，由 combatant_updates() 桥进战斗）；否则会被
    当成属性百分比拆进 pct["pierce"] 而丢失。其余 "_pct" 键拆层口径不变。

    批43：PLACEHOLDER 键（冷却缩减）**显式跳过**——只登记与展示，不接引擎。
    """
    for k, v in bonus.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        ks = str(k)
        if ks in GEAR_PLACEHOLDER_KEYS:
            continue
        if (ks.endswith(PCT_SUFFIX) and len(ks) > len(PCT_SUFFIX)
                and ks not in GEAR_COMBAT_KEYS):
            stem = ks[: -len(PCT_SUFFIX)]
            pct[stem] = pct.get(stem, 0.0) + fv
        else:
            flat[ks] = flat.get(ks, 0.0) + fv


def combatant_updates(flat: Mapping[str, Any]) -> Dict[str, float]:
    """聚合 flat → combatant 战斗桥更新项（非零项；封顶按 COMBAT_TO_COMBATANT）。

    crit 保留浮点（百分点、可负=赌狗流）；耳栓/超会心/属性会心按整数档位封顶。
    """
    out: Dict[str, float] = {}
    for src, dst, cap in COMBAT_TO_COMBATANT:
        v = flat.get(src)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if fv == 0.0:
            continue
        if cap is not None:
            fv = float(max(0.0, min(float(cap), fv)))
        out[dst] = fv
    return out
