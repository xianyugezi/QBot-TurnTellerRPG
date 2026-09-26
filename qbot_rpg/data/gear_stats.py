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
- **冷却缩减**   `cooldown_reduction_pct` 归 PLACEHOLDER 档：**只登记键 + 编辑器/展示可见**。
  批50 登记为 `cooldown_pct` 的兼容别名（`sign = -1`）；**批53 起激活**：内容包声明该旧键
  时经聚合入口 `route_legacy_aliases_into_flat` 换算为 `flat["cooldown_pct"] = −旧值`
  （`reduction 30 ⇔ cooldown_pct −30`），再走特效轴既有战斗桥/消费点，**不再「登记了不
  生效」**。该换算**只发生一次**（route_bonus_into 仍显式跳过占位键 → 不双计）。

批47 · 符文（43-B）1 阶数值贡献口径（键空间唯一源仍在本文件）：
- 1 阶符文 = **纯数值加成**，**复用本表既有键族**（FLAT 白值 / PCT 百分比 / COMBAT 战斗直读），
  **不新增符文专属键**（口径 §三.2：符文数值禁止自造键；校验器 `content/rune_models`
  RUNE-05 对 `by_equip_type[*].stats` 的键做 `GEAR_NUMERIC_KEYS` 红拦）。
- 承载（唯一聚合入口）：`core/equipment.aggregate_bonus` 的「符文贡献」段 → 走**同一**
  `route_bonus_into` flat/pct 路由（不新开第二套聚合）；激活孔位一律经
  `core/jewel.JewelSystem.active_rune_sockets`（副手折算件 → 空，失活零额外分支）。
- 语义/上限：flat 档语义=数值加算（上限仅编辑器提示：hp 99999 / mp 9999 / 其余 5000，
  见 `content/field_meta` 派生，非引擎钳制）；pct 档语义=百分点（5=+5%，提示 0-500，
  同既有词条）；COMBAT 档按 `combatant_updates` 的既有封顶。**符文专属数值上限**若需另设
  → 属口径未写，登记「待裁决」，不得在框架写死。

批50 · 特效轴地基（`GEAR_EFFECT_KEYS`；键空间唯一源仍在本文件）：
- 设计口径：`特效整理设计_1_修正轴全集.md` §0.2/§2/§3 + `特效整理设计_3_落点与分期.md`
  §1.0（表示口径裁定）/§1.2（逐轴落点）/§二「批48」（= 本批；该设计文档的批号是旧编号，
  与本仓库的「批48 · 符文特殊效果」无关，本批叫**批50**）。
- **分层（EFFECT 档）**：与 COMBAT 档同路由——**不进属性 pct 层、留 flat**，再由
  `combatant_updates()` 桥进战斗 combatant。理由与 `pierce_pct` 同类：否则
  `healing_received_pct` 会被 `route_bonus_into` 当成 `pct["healing_received"]`
  拆进属性管线而误算/丢失（`_3_落点与分期.md` §1.0 键族落点 + §3 C-06）。
- **表示口径 = 百分点增量轴**：`有效值 = 基准 × clamp(1 + pct/100, min, max)`，键名以
  `_pct` 结尾、**默认 0**（= ×1.0 恒等）；整数阈值语义的轴（层数上限 / 行动条）用
  **加算差值**（无 `_pct` 后缀，默认 0）。范围/默认值由内容包 `settings.effect_axes`
  覆盖，**不写死**；消费点只读声明，禁止硬编码钳制（§0.2 R-5）。
- **登记纪律**：逐轴登记表 `EFFECT_AXIS_SPECS` 是唯一源；每条轴必须写出「唯一消费点
  （本批待接）」——**无消费点的轴不得登记**（`cooldown_reduction_pct` 的教训：登记了
  不生效 = 对作者是陷阱）。本批**只登记，不接任何消费点**：缺省/未配置 → 全量回归
  逐字段零变化（对齐 `core/panel_budget.py` 的 `mult == 1.0` 不动原则）。
- **归并/别名**：`legacy_alias` 声明「旧键 → 本轴」的换算（`pct = sign × 旧键值`；
  `sign = -1` = 旧键语义与本轴相反，如 `immune_dmg` 免伤比 ⇔ 承伤比取负）。旧键自身
  链路本批**不动**。

批56 · 行动速度轴 + 过量治疗开关（决策记录 §十五 D 组裁决 D2/D4）：
- **D2 `action_speed_pct`（X28）**：登记为第 16 条特效轴（P1），消费点 = CTB 有效速度
  （`battle._ctb_actor_speed`，由 `ctb_rules.time_cost` 分母消费）；双向、范围由
  `settings.effect_axes` 声明。**`action_recovery_pct`（X29）按裁决不登记、不实现**——
  归入 `DEPRECATED_EFFECT_AXES`（校验器黄提示，不硬拦）。
- **D4 `overheal`**：**不是轴**（E5 = 布尔开关），故不在此登记表；另见 `OVERHEAL_KEY`
  段与 `core/effects` 的 HP 落点收口。缺省 = 关闭 = 与现状一致（过量部分丢弃）。

批59 · 特效小尾巴（决策记录 §十五 D5 + §二十一 批56 的 BV-1/2/3）：
- **D5 奖励轴登记**：登记第 17 条特效轴 `reward_mult_pct`（X43，P1，D1 百分点口径 =
  `×mult` 换算 `pct=(mult-1)×100`），**`min: 0` 下钳 0**（负掉率无意义）。**消费点待接**：
  奖励类别分散在 `reward.dispatch_reward`（coins/gem/rep，被任务/签到/NPC/钓鱼/成就/PvP 共用）、
  `battle_reward.settle_battle_rewards`（exp 经 `LevelUpEngine.gain_exp`）与
  `battle_reward.roll_death_drops`（掉落 chance）三处 → **无唯一收口，不为交差硬造**。
  该轴 `bridge="settlement"`：**不进战斗桥**（奖励不是 combatant 字段）。
- **BV-1 过量上限 / BV-2 去向**：`overheal` 段扩展 `mode`（keep/discard；`shield` 为**未实现**
  的保留位）+ `cap_pct`/`cap_flat`（上限，默认 `None` = 无额外上限 = 批56 现状）。
- **BV-3 速度轴权表坐标**：`action_speed_pct` 登记进 `EFFECT_AXIS_WEIGHTS`（不再
  `unknown_axis` 黄提示）。

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

import math
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

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
    # 批50 · 特效轴键族
    "GEAR_EFFECT_KEYS",
    "EFFECT_AXIS_SPECS",
    "EFFECT_TO_COMBATANT",
    "EFFECT_LEGACY_ALIASES",
    "DEPRECATED_EFFECT_AXES",
    "DEFAULT_EFFECT_AXES",
    "PANEL_AXIS_STEMS",
    # 批53 · 占位旧键 → 特效轴 兼容换算（聚合入口唯一处）
    "route_legacy_aliases_into_flat",
    # 批52 · 特效轴消费口径（settings 段键名 + 读时钳制取值）
    "EFFECT_AXES_KEY",
    "effect_axis_value",
    # 批59 · 奖励轴登记（X43，D5 下钳 0；消费点待接）
    "EFFECT_CONSUMER_PENDING",
    # 批55 · 特效强度预算（settings.effect_budget 段；另立上限 + A1 度量 —— 纯函数）
    "EFFECT_BUDGET_KEY",
    "EFFECT_AXIS_WEIGHTS",
    "DEFAULT_EFFECT_BUDGET",
    "EFFECT_AGGREGATES",
    "EFFECT_GATE_MODES",
    "EFFECT_UNKNOWN_MODES",
    "normalize_effect_budget",
    "effect_values_of",
    "effect_equiv",
    "effect_cap_pct",
    "check_effect_budget",
    # 批56 · 过量治疗开关（settings.overheal 段；D4 裁决 / E5）
    "OVERHEAL_KEY",
    "DEFAULT_OVERHEAL",
    "normalize_overheal",
    "overheal_enabled",
    # 批59 · BV-1 可配上限 + BV-2 去向枚举（keep/discard；shield 保留未实现）
    "OVERHEAL_MODES",
    "OVERHEAL_MODE_RESERVED",
    "overheal_cap",
    # 批51 · 触发归属（owner）战斗桥键名
    "OWNED_EFFECT_IDS_KEY",
    "effect_axis_spec",
    "effect_axis_stem",
    "normalize_effect_axes",
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
# 批43：占位键——**只登记字段 + 展示**；批53 起作为 `cooldown_pct` 的兼容别名**激活**
# （`route_bonus_into` 仍显式跳过；换算在聚合入口 `route_legacy_aliases_into_flat` 唯一处）。
GEAR_PLACEHOLDER_KEYS: Tuple[str, ...] = ("cooldown_reduction_pct",)

# ---------------------------------------------------------------------------
# 批50 · 特效轴（EFFECT）键族
# ---------------------------------------------------------------------------
# 面板三轴 stem（唯一源落在 data 层，使 content 层校验器可红拦「特效轴键名撞面板轴」
# **而不必** content→core 反向依赖；core/panel_budget.PANEL_AXIS_KEYS 由本常量派生）。
PANEL_AXIS_STEMS: Tuple[str, ...] = ("atk", "dfn", "hp")

#: 登记纪律的**待接哨兵**（批59 · D5）：某轴有明确落点方向、但框架尚无**唯一**消费点时，
#: `consumer` 写本哨兵并在 `consumer_note` 写明「候选点有哪些、为何无唯一收口」——
#: **不得**为交差把候选点之一伪造成「唯一消费点」，也不得静默留空绕过登记纪律。
#: 与「空 consumer 视为违反登记纪律」互补：哨兵 = 如实登记的待办，空 = 陷阱。
EFFECT_CONSUMER_PENDING: str = "（消费点待接）"

#: 特效轴逐轴登记表（**唯一源**：键名 / 范围 / 默认 / 显示 / 聚合 / 别名 / 唯一消费点）。
#
# 口径与纪律见模块 docstring「批50 · 特效轴地基」段。要点：
#   · `axis`      —— 键名（`_pct` = 百分点增量轴；无后缀 = 加算差值轴）；
#   · `min/max`   —— **建议缺省**区间（`None` = 该侧不限）；可由内容包 `settings.effect_axes`
#                    覆盖，消费点只读声明，**禁止写死**（§0.2 R-5）；
#   · `default`   —— 缺省值（增量轴恒为 0.0 = ×1.0 恒等 → 缺省零变化）；
#   · `stack`     —— 聚合方式（本批只 `add`，对齐 `_aggregate_boost` 既有口径；多来源
#                    相乘口径见 `_3_落点与分期.md` §1.0「唯一例外 stack_mode」= 待裁决）；
#   · `display`   —— 展示维度 {mode: mult|delta, label: 中文名, help: 说明+双向提示}；
#   · `legacy_alias` —— 旧键兼容别名 ((旧键名, sign), ...)，`pct = sign × 旧键值`；
#   · `consumer`  —— **唯一消费点（本批待接）**；空 = 不得登记（登记纪律，测试钉死）；
#   · `consumer_note` —— 收口范围 / 待接线时的必做事项。
#
# 本批登记范围 = 轴全集 §3 定级 P0/P1 的轴共 15 条（P0 8 + P1 7）。未登记的 P0/P1 项
# 及原因见 `docs/深度打造_实现说明.md`「批50」节与 `tests/unit/test_batch50_effect_axes.py`
# 的 DEFERRED 清单（缺唯一消费点 / 需改聚合本身 / 属非数值轴的基础设施）。
EFFECT_AXIS_SPECS: Tuple[Mapping[str, Any], ...] = (
    # ---- P0（轴全集 §3 P0 表）----
    {
        "axis": "healing_received_pct", "doc_id": "X17", "priority": "P0",
        "min": -200.0, "max": 300.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "受疗修正",
                    "help": "调整「我受到的治疗」：<1 减疗 / >1 增疗；-100 = 禁疗。"},
        "legacy_alias": (),
        "consumer": "effects.heal_apply",
        "consumer_note": "新增唯一收口 heal_apply(ctx, target, ...) 按 **target（受疗侧）**"
                         "聚合；待接时须一次改全 4 处 heal 源（heal 原子 / absorb_heal / "
                         "regen + battle 的 absorb_hp 吸血），只改 1 处必漏。",
    },
    {
        "axis": "healing_done_pct", "doc_id": "X16", "priority": "P0",
        "min": -100.0, "max": 300.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "施疗修正",
                    "help": "调整「我造成的治疗」：<1 削弱 / >1 强化；与受疗修正是两侧字段。"},
        "legacy_alias": (("heal_amp_pct", 1.0),),
        "consumer": "effects.heal_apply",
        "consumer_note": "与受疗修正是同一收口 heal_apply 的 **source（施疗侧）** 取值；"
                         "同批归并悬空旧键 heal_amp_pct（原零消费点）。",
    },
    {
        "axis": "damage_taken_pct", "doc_id": "X02", "priority": "P0",
        "min": -100.0, "max": 300.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "承伤修正",
                    "help": "调整「我受到的伤害」：<1 减伤 / >1 易伤。"
                            "减伤下钳与「多件易伤不叠到秒杀」由包声明区间控制（不写死）。"},
        "legacy_alias": (("immune_dmg", -1.0),),
        "consumer": "battle.damage_taken_mult",
        "consumer_note": "唯一收口 = 既有终伤乘区 `_status_damage_mult`（battle 侧）；"
                         "同批归并免伤旧键 immune_dmg（pct = −immune_dmg，旧链路保留）；"
                         "**不得**动 effects 的 mitigation 阶段（那里只做减伤、混入易伤会与"
                         "护盾/保底伤害交织）。",
    },
    {
        "axis": "damage_dealt_pct", "doc_id": "X01", "priority": "P0",
        "min": -100.0, "max": 1000.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "造成伤害修正",
                    "help": "调整「我造成的伤害」（终伤乘区）：<1 削伤 / >1 增伤。"
                            "定向增伤（弱点/技能限定）用效果条目的条件表达，不另造键。"},
        "legacy_alias": (("weakness_dmg_pct", 1.0),),
        "consumer": "battle.damage_dealt_mult",
        "consumer_note": "批70 已接线：唯一收口 = `battle._damage_dealt_mult`（总伤末 / 双通道末）"
                         "——落于 `total_damage` 之后、承伤乘区之前，对攻击方 raw 施加一次；"
                         "同批收编弱点旧键 weakness_dmg_pct（= 本轴的条件实例，经战斗桥 pct 层"
                         "归并入本轴、只算一次，旧链路保留）；**不替代** atk_pct（属性乘区、"
                         "受 S6/S7 封顶）。未配置（轴 0）→ ×1.0 不触碰 raw（逐字段零变化）。",
    },
    {
        "axis": "cooldown_pct", "doc_id": "X27", "priority": "P0",
        "min": -80.0, "max": 200.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "冷却时长修正",
                    "help": "调整技能冷却时长：<1 缩短冷却 / >1 拉长。结果按 max(0, …) "
                            "截断；负冷却不可达。"},
        "legacy_alias": (("cooldown_reduction_pct", -1.0),),
        "consumer": "battle.skill_cooldown",
        "consumer_note": "统一三样：既有 α3 `1 + 总计/100` 冷却管线（批53 已接线，结果"
                         " max(0, …)）+ 占位键 cooldown_reduction_pct（pct = −旧值；"
                         "经聚合入口换算为 flat['cooldown_pct']，只换算一次 → 不双计）。",
    },
    {
        "axis": "status_chance_pct", "doc_id": "X21", "priority": "P0",
        "min": -100.0, "max": None, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "状态命中修正",
                    "help": "调整施加状态的基础命中概率：<1 更难挂上 / >1 更易挂上；"
                            "> 基准溢出的部分转层数（溢出转层）。"},
        "legacy_alias": (("debuff_chance_pct", 1.0), ("buff_chance_pct", 1.0)),
        "consumer": "effects.status_apply_chance",
        "consumer_note": "批53 已接线：唯一收口 = `apply_status` 命中判定处（source 侧取值）；"
                         "同批归并两个悬空旧键 debuff_chance_pct / buff_chance_pct（经 pct 层"
                         "→ 同一轴，各折一次）；`>100%` 溢出按每满 100% 折 1 层（溢出转层，"
                         "仅 stack 框架）。"
                         "批82 · D2（用户 2026-09-23 裁决 B）：两旧键登记为**通用命中同义别名**"
                         "——当前不分 buff/debuff（一视同仁）；`scope={debuff,buff}` 分治"
                         "为 v1 不做，待真出现「只提减益/只提增益命中」需求再开。",
    },
    {
        "axis": "stack_gain_pct", "doc_id": "X23", "priority": "P0",
        "min": -100.0, "max": None, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "层数获取修正",
                    "help": "调整每次叠层的获取量：<1 叠得慢 / >1 叠得快。"
                            "向上取整与否由包声明控制。"},
        "legacy_alias": (),
        "consumer": "effects.stack_gain",
        "consumer_note": "批53 已接线：唯一收口 = `apply_status` 里「累积至 max_stack」的"
                         "增量处（source 侧；×(1+pct/100) 后四舍五入）。与批48 的"
                         " `status_stat_modifier_sum` stacks 乘算对齐（本轴只改 stacks 数量）。",
    },
    {
        "axis": "stack_cap_delta", "doc_id": "X24", "priority": "P0",
        "min": None, "max": None, "default": 0.0, "stack": "add",
        "display": {"mode": "delta", "label": "层数上限修正",
                    "help": "加算层数上限（不是百分比）：正 = 提高 / 负 = 降低，如 +2 / -1。"},
        "legacy_alias": (),
        "consumer": "effects.stack_cap",
        "consumer_note": "批53 已接线：唯一收口 = `apply_status` 的 max_stack 计算处"
                         "（target 侧；加算 + 下钳 ≥1）。marks.max_stack_of 半边**未接**"
                         "（印记与状态两套容器，登记待裁决）。",
    },
    # ---- P1（轴全集 §3 P1 表）----
    {
        "axis": "status_duration_pct", "doc_id": "X20", "priority": "P1",
        "min": -80.0, "max": 300.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "状态时长修正",
                    "help": "调整「我施加的」状态时长：<1 缩短 / >1 延长；只影响新施加的实例。"},
        "legacy_alias": (),
        "consumer": "effects.apply_status_duration",
        "consumer_note": "批70 已接线：唯一收口 = `effects.apply_status` 建实例处（source 侧），"
                         "对新施加实例的 `Duration{turns,charges}` 双维各缩放一次；"
                         "字段形状不变、不追改存量实例。未配置（轴 0）→ 原值（逐字段零变化）。",
    },
    {
        "axis": "status_duration_taken_pct", "doc_id": "X20", "priority": "P1",
        "min": -100.0, "max": 300.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "受状态时长修正",
                    "help": "调整「我承受的」状态时长：<1 抗控 / >1 更久；与状态抵抗互补。"},
        "legacy_alias": (),
        "consumer": "effects.apply_status_duration",
        "consumer_note": "批70 已接线：与「状态时长修正」共用同一收口 `apply_status` 建实例处，"
                         "按 **target 侧**取值（R-4：同一轴线、两个键实例），两侧系数相乘一次。"
                         "未配置（轴 0）→ 原值（逐字段零变化）。",
    },
    {
        "axis": "status_resist_pct", "doc_id": "X22", "priority": "P1",
        "min": -100.0, "max": None, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "状态抵抗修正",
                    "help": "调整我对状态的抵抗：<1 更易挂上 / >1 更抗；与状态命中是攻防两侧。"},
        "legacy_alias": (),
        "consumer": "effects.resist_roll",
        "consumer_note": "批53 已接线：唯一收口 = `apply_status` 抵抗判定处（target 侧；"
                         "**加算百分点**到既有 resist_table，0..100 钳制）。resist_gain"
                         "（施加后抗性）仍默认关；本轴只扩展 resist 值。",
    },
    {
        "axis": "action_bar_shift", "doc_id": "X30", "priority": "P1",
        "min": None, "max": None, "default": 0.0, "stack": "add",
        "display": {"mode": "delta", "label": "行动条推动",
                    "help": "加算行动条值（不是百分比）：正 = 提前 / 负 = 延后，如 +2 / -1。"},
        "legacy_alias": (),
        "consumer": "ctb_scheduler.action_bar_shift",
        "consumer_note": "批53 已接线：唯一收口 = `battle._after_actor_action` 收尾处，"
                         "复用既有成对原语 hasten_actor（正）/ delay_actor（负）。"
                         "counter_refund 仍走自身规则配置（收编为同一轴属口径变更，"
                         "本批不动，登记待裁决）。",
    },
    {
        "axis": "resource_cost_pct", "doc_id": "X34", "priority": "P1",
        "min": -100.0, "max": 200.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "资源消耗修正",
                    "help": "调整技能/行动的施放资源消耗：<1 省耗 / >1 更贵。"
                            "-100 = 零耗（下钳，不可为负）。"},
        "legacy_alias": (),
        "consumer": "resource_axis.pay_cost",
        "consumer_note": "批53 已接线：唯一收口 = `battle._apply_skill_energy` 读轴 →"
                         " `resource_axis.check_cost/pay_cost` 的 `mult`（同一倍率，"
                         "门禁与扣款一致；`scale_amount_map` 唯一缩放处，下钳 0）。",
    },
    {
        "axis": "resource_gain_pct", "doc_id": "X35", "priority": "P1",
        "min": -100.0, "max": None, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "资源获得修正",
                    "help": "调整资源获取量：<1 回得慢 / >1 回得快。"},
        "legacy_alias": (),
        "consumer": "resource_axis.apply_gain",
        "consumer_note": "批53 已接线：唯一收口 = `battle._apply_skill_energy` 读轴 →"
                         " `resource_axis.apply_gain/gain_energy` 的 `mult`（唯一缩放处）。",
    },
    {
        "axis": "crit_damage_pct", "doc_id": "X03", "priority": "P1",
        "min": -100.0, "max": 300.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "会心倍率修正",
                    "help": "调整会心（暴击）伤害倍率：<1 削弱 / >1 提升；与超会心档位并存。"},
        "legacy_alias": (),
        "consumer": "damage.crit_multiplier",
        "consumer_note": "批53 已接线：唯一收口 = `battle._resolve_damage_action` 的会心乘区"
                         "（crit_roll 之后、入 rating 之前等比缩放；会心三档一视同仁）。"
                         "既有 super_crit_lv / elem_crit_lv（0-3 档）保持独立：前者已由"
                         " crit_roll 离散档叠加，后者作用于元素通道、**不并入**本轴。",
    },
    {
        "axis": "action_speed_pct", "doc_id": "X28", "priority": "P1",
        "min": -80.0, "max": 400.0, "default": 0.0, "stack": "add",
        "display": {"mode": "mult", "label": "行动速度修正",
                    "help": "调整行动速度：正 = 提速 / 负 = 迟缓（+20 = ×1.2）；只保留本轴。"},
        "legacy_alias": (),
        "consumer": "ctb.effective_speed",
        "consumer_note": "批56 已接线：唯一收口 = `battle._ctb_actor_speed`（CTB 入队有效速度），"
                         "由既有 CTB 公式 `time_cost = recovery × speed_reference / "
                         "max(effective_speed, min_speed) + delay` 的分母消费"
                         "（复用 `ctb_rules.time_cost`，不新开管线；min_speed 下限保护沿用）。"
                         "未配置 / 0 → 原值（逐字段零变化）。"
                         "`enrage/fatigue_recovery_mult` 仍走自身规则配置（收编为条件实例属"
                         "口径变更，本批不动，登记待裁决）。",
    },
    # ---- 批59 · D5 奖励轴（X43；**登记 + 下钳 0，消费点待接**）----
    {
        "axis": "reward_mult_pct", "doc_id": "X43", "priority": "P1",
        "min": 0.0, "max": 400.0, "default": 0.0, "stack": "add",
        # 奖励是**结算期**轴，不是 combatant 字段 → 不进战斗桥（见 EFFECT_TO_COMBATANT）。
        "bridge": "settlement",
        # 设计 X43 的 `scope` 声明形状待裁决（多键 vs 对象型轴）→ 原样登记、不承载。
        "scope": ("exp", "coins", "gem", "rep",
                  "drop_chance", "drop_count", "drop_rarity"),
        "display": {"mode": "mult", "label": "奖励倍率修正",
                    "help": "调整结算奖励（经验/货币/掉落）：正 = 提升 / 负 = 减少（下钳 0）。"
                            "当前未实现，配置不生效。"},
        "legacy_alias": (),
        "consumer": EFFECT_CONSUMER_PENDING,
        "consumer_note": "D5 登记：奖励类别分散在**三处**、无唯一收口，故不硬造——"
                         "① 标量 coins/gem/rep 在 `core/reward.dispatch_reward`"
                         "（被任务/签到/NPC/钓鱼/成就/PvP **共用**）；"
                         "② 战斗 exp 在 `core/battle_reward.settle_battle_rewards`"
                         "（经 `LevelUpEngine.gain_exp`，**不走** dispatch_reward）；"
                         "③ 掉落在其 `roll_death_drops` 的 chance roll。"
                         "接线须先裁决 `scope` 承载形状（多键 vs 对象型轴）与是否只作用于"
                         "战斗结算；届时消费点读 `settings.effect_axes` 声明做读时钳制"
                         "（`min: 0` 即 D5）。本批只登记、声明下钳语义，**未接任何消费点**。",
    },
)

#: 已按 D 组裁决**废弃**的轴：键 → (替代轴, 裁决依据/原因)。
#: **不得登记、不得实现**——校验器对内容声明/词条命中本表者给**黄提示**（不硬拦），
#: 提示作者改用替代轴。唯一源落本文件（轴键空间的唯一源），validator 只读。
DEPRECATED_EFFECT_AXES: Dict[str, Tuple[str, str]] = {
    "action_recovery_pct": (
        "action_speed_pct",
        "行动速度与行动后摇数学互为倒数，二者并存会让作者叠加导致指数级加速；"
        "D2 裁决只保留「行动速度」。",
    ),
}

#: 特效轴键族（登记表派生的键名元组——**唯一源**，grep 可枚举）。
GEAR_EFFECT_KEYS: Tuple[str, ...] = tuple(str(_s["axis"]) for _s in EFFECT_AXIS_SPECS)

#: 特效轴 → 战斗桥目标键（**本批只桥接、不求值**：`combatant_updates` 只映射非零项，
#: 缺省 0 → combatant 不新增任何字段 → 全量回归逐字段零变化）。
#: 封顶一律 `None`：钳制归内容包 `settings.effect_axes` 声明 + 消费点读取，引擎不写死。
#:
#: 批59：桥接受轴条目的 `bridge` 字段控制——缺省 `"combatant"`（进战斗桥）；
#: `"settlement"`（如奖励轴 `reward_mult_pct`）是**结算期**轴，**不进 combatant**
#: （奖励不是战斗体字段，桥进去只会污染快照且无人读）。
EFFECT_TO_COMBATANT: Tuple[str, ...] = tuple(
    str(_s["axis"]) for _s in EFFECT_AXIS_SPECS
    if str(_s.get("bridge", "combatant")) == "combatant"
)

#: `settings.effect_axes` 段键名（批52：battle/effects 消费点从引擎配置读该段做**读时钳制**）。
#: 与 `normalize_effect_axes` 配套；未配置 = 缺省表 = 恒等（零变化）。
EFFECT_AXES_KEY: str = "effect_axes"

# ---------------------------------------------------------------------------
# 批51 · 触发归属（owner）战斗桥键名 —— **唯一源**
# ---------------------------------------------------------------------------
#: combatant 侧「本侧拥有的 trigger 效果 id 集合」键名（值为 str 列表）。
#:
#: 口径（`core/event_dispatcher.dispatch_event` 的 `owner_effect_ids`）：
#:   · 装配层（装备被动/效果归属展开）在本键写入该侧拥有的效果 id；
#:   · `core/battle._dispatch_event` 读到本键 → 作为归属作用域传给分派器
#:     （带 `trigger` 的效果只在其宿主侧触发，不再全局误触发）；
#:   · **键缺省 = 不启用归属过滤**（全库扫描旧行为，逐字段零变化）。
#: 键名登记在本模块（与 `COMBAT_TO_COMBATANT` / `EFFECT_TO_COMBATANT` 同为战斗桥
#: 键名的唯一源），使 core 层与 commands 层共用同一常量、不各自写死字面量。
OWNED_EFFECT_IDS_KEY: str = "owned_effect_ids"

# 数值键全集（实例化转换 / 展示 / 编辑器遍历用；批50 起含特效轴键族）
GEAR_NUMERIC_KEYS: Tuple[str, ...] = (
    GEAR_FLAT_KEYS + GEAR_PCT_KEYS + GEAR_COMBAT_KEYS + GEAR_EFFECT_KEYS
)
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
    "heal_amp_pct": "回复强化：治疗/回复效果按该比例提升（百分点，0-500）。",
    # 批82 · D2（用户 2026-09-23 裁决 B：v1 不分治）：两旧键 = `status_chance_pct` 的
    # **通用命中同义别名**，对 buff/debuff 一视同仁（批53 有意归并，effects 消费点无分支）。
    "debuff_chance_pct": "通用状态命中提升（当前不分 buff/debuff；"
                         "与 buff_chance_pct 同义别名，百分点，0-500）。",
    "buff_chance_pct": "通用状态命中提升（当前不分 buff/debuff；"
                       "与 debuff_chance_pct 同义别名，百分点，0-500）。",
    "weakness_dmg_pct": "弱点伤害增加：命中目标弱点时伤害按该比例提升（百分点，0-500）。",
    # 占位键（原案 §7；批53 起作为 cooldown_pct 的兼容别名**生效**）
    "cooldown_reduction_pct": "冷却缩减（百分点）：作为「冷却时长修正」的兼容别名，只换算一次。",
    # 批66 · 卡点4：基础词条一句话说明（编辑器字段说明卡；≤60 字，忌长文）。
    "atk": "攻击加成（点）。",
    "def": "防御加成（点；旧键，建议改用 dfn）。",
    "dfn": "防御加成（点）。",
    "hp": "生命上限加成（点）。",
    "mp": "法力上限加成（点）。",
    "str": "力量属性加成（点）。",
    "con": "体质属性加成（点）。",
    "agi": "敏捷属性加成（点）。",
    "foc": "专注属性加成（点）。",
    "spr": "精神属性加成（点）。",
    "lck": "幸运属性加成（点）。",
    "spd": "速度属性加成（点）。",
    "mag": "法强属性加成（点）。",
    "atk_pct": "攻击加成（百分点）。",
    "dfn_pct": "防御加成（百分点）。",
    "hp_pct": "生命上限加成（百分点）。",
    "mp_pct": "法力上限加成（百分点）。",
    "crit": "会心（暴击）率加成（百分点，可负）。",
    "earplug": "耳栓档（0-2 级；抵消音波类效果）。",
    "super_crit_lv": "超会心档（0-3 级；提高会心伤害）。",
    "elem_crit_lv": "属性会心档（0-3 级；提高属性会心伤害）。",
}

# 批50：特效轴的中文名 / 说明由 `EFFECT_AXIS_SPECS` 唯一源派生（**不重复手写**）——
# 展示（详情面板）、编辑器字段表（field_meta）与说明卡共用同一份文案。
for _spec in EFFECT_AXIS_SPECS:
    _axis = str(_spec["axis"])
    _disp = _spec["display"]
    GEAR_LABELS_ZH[_axis] = str(_disp["label"])
    GEAR_HELP_ZH[_axis] = str(_disp["help"])
del _spec, _axis, _disp
#: 旧键 → 特效轴 的别名反查表（`{旧键名: (轴键名, sign)}`；`pct = sign × 旧键值`）。
#: **只作声明与后续接线的单一入口**：本批不消费、不改写任何既有链路。
EFFECT_LEGACY_ALIASES: Dict[str, Tuple[str, float]] = {
    str(_legacy): (str(_s["axis"]), float(_sign))
    for _s in EFFECT_AXIS_SPECS
    for _legacy, _sign in _s.get("legacy_alias", ())
}

#: `settings.effect_axes` 的**缺省声明**（逐轴 min/max/default/display/stack/legacy_alias）。
#: 内容包同名段按轴覆盖（见 `normalize_effect_axes`）；缺省值即本表 → 未配置 = 与引入前
#: 逐字段一致（对齐 `core/panel_budget.py` 的「包声明驱动 + 缺省恒等」风格）。
DEFAULT_EFFECT_AXES: Dict[str, Dict[str, Any]] = {
    str(_s["axis"]): {
        "min": _s.get("min"),
        "max": _s.get("max"),
        "default": float(_s.get("default", 0.0)),
        "display": dict(_s["display"]),
        "stack": str(_s.get("stack", "add")),
        "legacy_alias": tuple(_s.get("legacy_alias", ())),
    }
    for _s in EFFECT_AXIS_SPECS
}


def effect_axis_spec(axis: str) -> Mapping[str, Any]:
    """按轴键取登记表原始条目（未登记 → 空映射）。只读，不改任何状态。"""
    key = str(axis)
    for spec in EFFECT_AXIS_SPECS:
        if str(spec["axis"]) == key:
            return spec
    return {}


def effect_axis_stem(axis: str) -> str:
    """特效轴键的**属性 stem**（去掉 `_pct` 后缀）——用于「不得与面板三轴 stem 冲突」判定。

    例：`atk_pct` → `atk`（撞面板轴，须红拦）；`damage_taken_pct` → `damage_taken`；
    加算轴（无 `_pct` 后缀）→ 原键名本身。
    """
    ks = str(axis)
    if ks.endswith(PCT_SUFFIX) and len(ks) > len(PCT_SUFFIX):
        return ks[: -len(PCT_SUFFIX)]
    return ks


def _as_effect_number(value: Any) -> Optional[float]:
    """声明段数值清洗：布尔/非数值/NaN/Inf → None（交由校验器黄提示或回落缺省）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    fv = float(value)
    if math.isnan(fv) or math.isinf(fv):
        return None
    return fv


def normalize_effect_axes(cfg: Any) -> Dict[str, Dict[str, Any]]:
    """`settings.effect_axes` → 逐轴有效声明（缺省表 ⊕ 内容包覆盖）。

    读时参数化（对齐 `core/panel_budget.normalize_*`）：**不写死范围/默认值**，包声明优先；
    非法/缺失字段逐项回落缺省表 → 未配置 = 缺省表 = 恒等（增量轴默认 0.0 = ×1.0）。

    返回 `{轴键: {min, max, default, display, stack, legacy_alias, declared}}`；
    `declared` = 本轴是否被内容包显式声明（校验器据此区分「自造轴」与「覆盖已登记轴」）。
    未知轴（不在 `GEAR_EFFECT_KEYS`）**原样保留**并标 `declared=True`，由校验器黄提示，
    本函数不擅自吞掉——「未知轴黄提示」而非静默丢弃。
    """
    out: Dict[str, Dict[str, Any]] = {
        axis: dict(entry) | {"declared": False}
        for axis, entry in DEFAULT_EFFECT_AXES.items()
    }
    if not isinstance(cfg, Mapping):
        return out
    for raw_axis, raw_entry in cfg.items():
        axis = str(raw_axis)
        base = dict(out.get(axis) or DEFAULT_EFFECT_AXES.get(axis) or {
            "min": None, "max": None, "default": 0.0,
            "display": {"mode": "mult", "label": axis, "help": ""},
            "stack": "add", "legacy_alias": (),
        })
        if isinstance(raw_entry, Mapping):
            for field in ("min", "max", "default"):
                if field in raw_entry:
                    num = _as_effect_number(raw_entry.get(field))
                    if num is not None:
                        base[field] = num
            if isinstance(raw_entry.get("display"), Mapping):
                disp = dict(base.get("display") or {})
                disp.update(raw_entry["display"])
                base["display"] = disp
            elif isinstance(raw_entry.get("display"), str):
                base["display"] = dict(base.get("display") or {}) | {
                    "mode": str(raw_entry["display"])
                }
            if isinstance(raw_entry.get("stack"), str):
                base["stack"] = str(raw_entry["stack"])
            if isinstance(raw_entry.get("legacy_alias"), (list, tuple)):
                base["legacy_alias"] = tuple(raw_entry["legacy_alias"])
        out[axis] = base | {"declared": True}
    return out


def effect_axis_value(combatant: Any, axis: str, cfg: Any = None) -> float:
    """combatant 上某特效轴的**有效取值**（读时按声明区间钳制；缺失/非法 → 0.0）。

    批52 · 特效轴消费口径（唯一读点辅助）：
      · 取值来源 = `combatant[axis]`（由 `combatant_updates` 桥接进战斗体；非数值/布尔 → 0）；
      · 钳制 = `normalize_effect_axes(cfg)[axis]` 的 `min/max`（`None` = 该侧不限）——
        **消费点只读声明、不写死区间**（`_3_落点与分期.md` §0.2 R-5）；
      · 未配置 `cfg` → 登记表建议区间（默认增量轴 0.0 = ×1.0 恒等 → 缺省零变化）。
    """
    value = 0.0
    if isinstance(combatant, Mapping):
        raw = combatant.get(str(axis))
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = float(raw)
    entry = normalize_effect_axes(cfg).get(str(axis)) or {}
    lo, hi = entry.get("min"), entry.get("max")
    if lo is not None:
        value = max(float(lo), value)
    if hi is not None:
        value = min(float(hi), value)
    return value


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

    批50：**EFFECT 键同 COMBAT 例外——一律留 flat、不进属性 pct 层**（理由与
    `pierce_pct` 同）：否则 `healing_received_pct` 会被拆成 `pct["healing_received"]`
    误算/丢失；EFFECT 键由 `combatant_updates()` 桥进战斗 combatant。
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
                and ks not in GEAR_COMBAT_KEYS
                and ks not in GEAR_EFFECT_KEYS):
            stem = ks[: -len(PCT_SUFFIX)]
            pct[stem] = pct.get(stem, 0.0) + fv
        else:
            flat[ks] = flat.get(ks, 0.0) + fv


def route_legacy_aliases_into_flat(
    bonus: Mapping[str, Any],
    flat: MutableMapping[str, float],
) -> None:
    """占位旧键 → 特效轴 的**唯一兼容换算**（批53）：`flat[axis] += sign × 旧值`。

    只在聚合入口（`core.equipment.aggregate_bonus` 的逐件 `route_bonus_into` 之后）调用，
    与 `route_bonus_into` 的分层判定**互不重叠**：

      · 只处理 `GEAR_PLACEHOLDER_KEYS` 中且已在 `EFFECT_LEGACY_ALIASES` 声明的旧键
        （当前 = `cooldown_reduction_pct → ("cooldown_pct", -1)`）；`route_bonus_into`
        对这些键仍显式 `continue`（不进 pct 层、**也不进 flat**）→ 本函数是**唯一**写入点
        → 同一旧键不可能被两条路径各消费一次（**不双计**）；
      · 属性 pct 层旧键（`heal_amp_pct` 等）由 `combatant_updates(flat, pct)` 归并，
        COMBAT 旧键（`immune_dmg`）在各自消费点换算——本函数**不碰**它们；
      · 非数值 / 布尔 / 未声明别名 → 跳过；未配置（内容包不带占位键）→ 不写任何键
        （缺省逐字段零变化）。

    语义：旧键 `cooldown_reduction_pct = 30`（= 冷却缩减 30%）→ `flat["cooldown_pct"] = -30`
    → 消费点 `1 + (-30)/100 = 0.7` 倍冷却，与轴全集 §X27 `reduction_p ⇔ mult = 1 - p/100`
    一致。
    """
    for k, v in bonus.items():
        ks = str(k)
        if ks not in GEAR_PLACEHOLDER_KEYS:
            continue
        legacy = EFFECT_LEGACY_ALIASES.get(ks)
        if legacy is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        axis, sign = legacy
        fv = float(v)
        if fv == 0.0:
            continue
        flat[str(axis)] = flat.get(str(axis), 0.0) + float(sign) * fv


def combatant_updates(
    flat: Mapping[str, Any], pct: Optional[Mapping[str, Any]] = None,
) -> Dict[str, float]:
    """聚合 flat → combatant 战斗桥更新项（非零项；封顶按 COMBAT_TO_COMBATANT）。

    crit 保留浮点（百分点、可负=赌狗流）；耳栓/超会心/属性会心按整数档位封顶。

    批50：**特效轴桥接行**（EFFECT_TO_COMBATANT）——把 EFFECT 键接入战斗桥。
    本批**只桥接、不求值**：战斗侧无任何读取点，且只映射**非零项**，故缺省 0 / 未配置
    → 输出与引入前**逐字段一致**。封顶一律 `None`：钳制归内容包 `settings.effect_axes`
    声明 + 消费点读取，引擎不写死（§0.2 R-5）。

    批52 · **旧键别名归并**（可选 `pct` 形参）：`EFFECT_LEGACY_ALIASES` 中**属性 pct 层来源**
    的旧键（如 `heal_amp_pct` → `pct["heal_amp"]`，原悬空/无消费点）按
    `axis += sign × 旧值` 并入对应特效轴（与 EFFECT 键**加算**，同轴 `stack=add` 口径）。
    只处理 `GEAR_PCT_KEYS` 内的旧键——COMBAT 键（`immune_dmg`）由自身链路承接、在其
    **消费点**换算（不在此重复并入，避免双计）；PLACEHOLDER（`cooldown_reduction_pct`）
    仍不接引擎。`pct=None`（缺省）→ 行为与批51 及此前**逐字段一致**（本批零变化红线）。
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
    for src in EFFECT_TO_COMBATANT:
        v = flat.get(src)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if fv == 0.0:
            continue
        out[src] = fv
    if isinstance(pct, Mapping):
        for legacy, (axis, sign) in EFFECT_LEGACY_ALIASES.items():
            if legacy not in GEAR_PCT_KEYS:
                continue  # 非 pct 层旧键（COMBAT/占位）不走本换算
            stem = legacy[: -len(PCT_SUFFIX)] if legacy.endswith(PCT_SUFFIX) else legacy
            v = pct.get(stem)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            fv = float(v)
            if fv == 0.0:
                continue
            out[axis] = out.get(axis, 0.0) + float(sign) * fv
    return out


# ---------------------------------------------------------------------------
# 批55 · 特效强度预算（`settings.effect_budget`）—— 另立上限（方案 B）+ A1 度量（纯函数）
# ---------------------------------------------------------------------------
# 依据：`docs/特效强度预算_设计.md` §二方案 B + §三推荐（B 主 + A1 度量 + C 备用）。
#
# 问题：`PANEL_AXIS_KEYS` 只覆盖 atk/dfn/hp，特效轴（本文件 EFFECT + COMBAT 档吸血/免伤）
# 会抬高真实战力却**不进 `equip_share`** → 实机口径把 Boss 压到 ≈39–41（贴死 40 下沿）。
# 本段**不改任何战斗数值**：只做「度量」（`effect_equiv` / `effective_equip_share`）与
# 「设上限」（`check_effect_budget`）。缺省整段不存在 / `enabled=false` → 全 0 / gate 静默。
#
# 数据层落点原因（对齐批50 `PANEL_AXIS_STEMS` 的同一取舍）：`content/validator` 需读本段做
# 内容校验，而架构矩阵 `content → {data}` **禁止 content→core**；故纯函数放 data 层，
# `core/panel_budget` 再导出（core→data 合法）。
EFFECT_BUDGET_KEY: str = "effect_budget"

#: 输出等效 × 生存等效的合成口径。
EFFECT_AGGREGATES: Tuple[str, ...] = ("geometric", "product", "max")
#: 超限处理：off = 静默 / warn = 黄提示（不阻断）/ red = 红拦（拒绝）。
EFFECT_GATE_MODES: Tuple[str, ...] = ("off", "warn", "red")
#: 权表未登记轴出现时的行为。
EFFECT_UNKNOWN_MODES: Tuple[str, ...] = ("ignore", "warn", "red")

#: **特效等效权表**（坐标表，不是加法定律）：`{键: {calib, output, survival}}`，
#: 外推规则固定 `等效% = 轴值 / calib × 校准等效%`（线性、单向可负）。
#:
#: 校准点 = `docs/特效强度预算_设计.md` §2.2 实测点（`doc_id` 见各行）。整表可被内容包
#: `settings.effect_budget.axis_weights` **逐键覆盖 / 追加**（不写死）；`calib` 为 0 的
#: 条目按「不参与折算」处理。未登记的**已登记特效轴** = `unknown_axis` 行为。
EFFECT_AXIS_WEIGHTS: Dict[str, Dict[str, Any]] = {
    # X27 冷却：轮转模型 C=4 / k=0.4 → +6.8%（区间 +2.9%~+25%）；轴值负 = 缩短冷却 = 正收益。
    "cooldown_pct": {"calib": -20.0, "output": 6.8, "survival": 0.0, "doc_id": "X27"},
    # X02 承伤：1/(1−0.25) − 1 = +33.3%（精确）；轴值正 = 易伤 = 负收益。
    "damage_taken_pct": {"calib": -25.0, "output": 0.0, "survival": 33.3, "doc_id": "X02"},
    # X12 吸血：净损血率模型，中/高怪 ×1.43~×1.48，overheal 封顶后取下沿 +43%。
    "absorb_hp": {"calib": 15.0, "output": 0.0, "survival": 43.0, "doc_id": "X12"},
    # X17 受疗：治疗占比相关（+5%~+20%），取保守下沿 +5%。
    "healing_received_pct": {"calib": 15.0, "output": 0.0, "survival": 5.0, "doc_id": "X17"},
    # X01 造成伤害：终伤乘区线性 +10% ⇔ +10%。
    "damage_dealt_pct": {"calib": 10.0, "output": 10.0, "survival": 0.0, "doc_id": "X01"},
    # X28 行动速度（批59 · BV-3 登记）：速度 = 出手频率 = **乘性输出杠杆**。
    # 依据 = 实现说明 §18.7「把 +20% 速度当作输出侧 ×1.2」；同节实测档位尺下
    # +20% 速度 → 普通 5.5→5.04 / 精英 12.5→11.46 / Boss 48→44（≈输出 +8.3%）。
    # 本表取更严的**设计口径**（+20 ⇔ +20%）→ 闸偏保守；可被包声明逐键覆盖。
    "action_speed_pct": {"calib": 20.0, "output": 20.0, "survival": 0.0, "doc_id": "X28"},
}

#: 新增 `settings.effect_budget` 的缺省（**整段不存在 / enabled=false → 完全无行为**）。
#: 缺省口径按 `docs/特效强度预算_设计.md` §三推荐：cap 8% × 档位 1.5/1.0/0.625
#: = 普通 12% / 精英 8% / Boss 5%；合成 geometric；超限 warn（上线初期观察）。
DEFAULT_EFFECT_BUDGET: Dict[str, Any] = {
    "enabled": False,
    "aggregate": "geometric",
    "cap_equiv_pct": 8.0,
    "tier_mult": {"normal": 1.5, "elite": 1.0, "boss": 0.625},
    "gate_mode": "warn",
    "unknown_axis": "warn",
    "report_effective_share": True,
    "axis_weights": {k: dict(v) for k, v in EFFECT_AXIS_WEIGHTS.items()},
}


def _effect_flag(cfg: Mapping[str, Any], key: str, default: bool) -> bool:
    """严格布尔读键：缺键/非布尔 → `default`（不把 truthy 值当开关）。"""
    v = cfg.get(key, default)
    return v if isinstance(v, bool) else bool(default)


def _effect_choice(cfg: Mapping[str, Any], key: str, allowed: Tuple[str, ...],
                   default: str) -> str:
    v = cfg.get(key, default)
    return str(v) if isinstance(v, str) and v in allowed else default


def normalize_effect_budget(cfg: Any) -> Dict[str, Any]:
    """`settings.effect_budget` → 有效配置（缺省/非法逐项回落；缺段 → `enabled=false`）。

    形状与缺省见 `DEFAULT_EFFECT_BUDGET`。整段不存在、非映射、`enabled != true` →
    聚合器返回 0、gate 静默 → 与引入前**逐字段一致**。`axis_weights` 在缺省权表上
    **逐键覆盖 / 追加**（数值非法则忽略该字段）；`tier_mult` 可增自定义档位键。
    """
    m: Mapping[str, Any] = cfg if isinstance(cfg, Mapping) else {}
    out: Dict[str, Any] = dict(DEFAULT_EFFECT_BUDGET)
    out["enabled"] = _effect_flag(m, "enabled", False)
    out["aggregate"] = _effect_choice(m, "aggregate", EFFECT_AGGREGATES, "geometric")
    out["gate_mode"] = _effect_choice(m, "gate_mode", EFFECT_GATE_MODES, "warn")
    out["unknown_axis"] = _effect_choice(m, "unknown_axis", EFFECT_UNKNOWN_MODES, "warn")
    out["report_effective_share"] = _effect_flag(m, "report_effective_share", True)
    cap = _as_effect_number(m.get("cap_equiv_pct"))
    out["cap_equiv_pct"] = max(0.0, cap) if cap is not None else 8.0
    tier_mult: Dict[str, float] = {
        str(k): max(0.0, float(v))
        for k, v in dict(DEFAULT_EFFECT_BUDGET["tier_mult"]).items()
    }
    raw_tm = m.get("tier_mult")
    if isinstance(raw_tm, Mapping):
        for raw_key, raw_val in raw_tm.items():
            num = _as_effect_number(raw_val)
            if num is not None:
                tier_mult[str(raw_key)] = max(0.0, num)
    out["tier_mult"] = tier_mult
    weights: Dict[str, Dict[str, Any]] = {
        str(k): dict(v) for k, v in DEFAULT_EFFECT_BUDGET["axis_weights"].items()
    }
    raw_w = m.get("axis_weights")
    if isinstance(raw_w, Mapping):
        for raw_key, raw_entry in raw_w.items():
            key = str(raw_key)
            base = dict(weights.get(key) or {"calib": 0.0, "output": 0.0, "survival": 0.0})
            if isinstance(raw_entry, Mapping):
                for field in ("calib", "output", "survival"):
                    if field not in raw_entry:
                        continue
                    num = _as_effect_number(raw_entry.get(field))
                    if num is not None:
                        base[field] = num
                if raw_entry.get("doc_id") is not None:
                    base["doc_id"] = str(raw_entry.get("doc_id"))
            weights[key] = base
    out["axis_weights"] = weights
    return out


def _combine_equiv(output_pct: float, survival_pct: float, aggregate: str) -> float:
    """输出等效 × 生存等效 → 综合等效（%）；`max` 取两者较大者。"""
    if aggregate == "max":
        return max(float(output_pct), float(survival_pct))
    rel_out = max(0.0, 1.0 + float(output_pct) / 100.0)
    rel_surv = max(0.0, 1.0 + float(survival_pct) / 100.0)
    if aggregate == "product":
        return (rel_out * rel_surv - 1.0) * 100.0
    return (math.sqrt(rel_out * rel_surv) - 1.0) * 100.0


def effect_values_of(bonus: Any, cfg: Any = None) -> Dict[str, float]:
    """从 `stats_bonus` / 聚合 flat 映射抽出**特效相关取值**（旧键经 `legacy_alias` 换算）。

    只保留三类键：权表键（含 COMBAT 档的 `absorb_hp` 等）、登记特效轴
    （`GEAR_EFFECT_KEYS`，进 unknown 判定）、旧键别名（换算为轴，如
    `immune_dmg:25 → damage_taken_pct:-25`）。其余键（atk/crit/…）静默忽略。
    同键多来源**加算**（与 EFFECT 轴 `stack=add` 口径一致）。
    """
    cfg_n = normalize_effect_budget(cfg)
    recognized = set(str(k) for k in cfg_n["axis_weights"]) | set(GEAR_EFFECT_KEYS)
    out: Dict[str, float] = {}
    if not isinstance(bonus, Mapping):
        return out
    for raw_key, raw_val in bonus.items():
        fv = _as_effect_number(raw_val)
        if fv is None or fv == 0.0:
            continue
        key = str(raw_key)
        alias = EFFECT_LEGACY_ALIASES.get(key)
        if alias is not None:
            axis, sign = alias
            out[str(axis)] = out.get(str(axis), 0.0) + float(sign) * fv
        elif key in recognized:
            out[key] = out.get(key, 0.0) + fv
    return out


def effect_equiv(values: Any, cfg: Any = None) -> Dict[str, Any]:
    """一个 build（`{键: 轴值}`）→ 特效等效（**只读、不改任何战斗数值**；方案 B 聚合器）。

    返回 `{enabled, output_pct, survival_pct, equiv_pct, aggregate, unknown}`；
    `unknown` = **已登记特效轴**（`GEAR_EFFECT_KEYS`）但权表未登记的键（排序去重）；
    完全不属于特效键空间的键（如 atk/crit）**静默忽略**。`enabled != true` → 全 0。
    """
    cfg_n = normalize_effect_budget(cfg)
    result: Dict[str, Any] = {
        "enabled": bool(cfg_n["enabled"]),
        "output_pct": 0.0,
        "survival_pct": 0.0,
        "equiv_pct": 0.0,
        "aggregate": str(cfg_n["aggregate"]),
        "unknown": [],
    }
    if not cfg_n["enabled"] or not isinstance(values, Mapping):
        return result
    weights: Mapping[str, Any] = cfg_n["axis_weights"]
    registered = set(GEAR_EFFECT_KEYS)
    output_pct = 0.0
    survival_pct = 0.0
    unknown = set()
    for raw_key, raw_val in values.items():
        fv = _as_effect_number(raw_val)
        if fv is None or fv == 0.0:
            continue
        key = str(raw_key)
        weight = weights.get(key)
        if not isinstance(weight, Mapping):
            if key in registered:
                unknown.add(key)
            continue
        calib = _as_effect_number(weight.get("calib"))
        if not calib:
            continue
        ratio = fv / float(calib)
        output_pct += ratio * float(_as_effect_number(weight.get("output")) or 0.0)
        survival_pct += ratio * float(_as_effect_number(weight.get("survival")) or 0.0)
    result["output_pct"] = output_pct
    result["survival_pct"] = survival_pct
    result["equiv_pct"] = _combine_equiv(output_pct, survival_pct, str(cfg_n["aggregate"]))
    result["unknown"] = sorted(unknown)
    return result


def effect_cap_pct(tier: Any = None, cfg: Any = None) -> float:
    """按档位的特效综合等效上限 = `cap_equiv_pct × tier_mult[tier]`（未启用 → 0.0）。

    档位缺省/未登记 → `tier_mult` 回落 1.0（不写死档位名，内容包可自行增键）。
    """
    cfg_n = normalize_effect_budget(cfg)
    if not cfg_n["enabled"]:
        return 0.0
    tier_mult: Mapping[str, Any] = cfg_n["tier_mult"]
    mult = 1.0
    if tier is not None and str(tier) in tier_mult:
        mult = float(tier_mult[str(tier)])
    return max(0.0, float(cfg_n["cap_equiv_pct"]) * mult)


def check_effect_budget(values: Any, tier: Any = None, cfg: Any = None) -> Dict[str, Any]:
    """特效强度预算闸：按档位判超限（**只判不改**；越界动作由 `gate_mode` 决定）。

    返回 `{enabled, equiv_pct, output_pct, survival_pct, cap_pct, over, gate_mode,
    unknown, unknown_axis, action}`——`action` ∈ `ok/off/warn/red`：
      · 未启用 / 未超限 → `ok`；超限 → `gate_mode`（off 静默 / warn 黄提示 / red 拒绝）；
      · 权表未登记轴按 `unknown_axis` 取**更严**者（off/ignore < warn < red）。
    本函数**不改任何战斗数值**；调用方（校验器 / 工具 / 内容包）自行决定呈现方式。
    条目级校验（无档位）调用本次 `tier=None` → 上限 = `cap_equiv_pct`（条目配额）。
    """
    cfg_n = normalize_effect_budget(cfg)
    equiv = effect_equiv(values, cfg)
    cap = effect_cap_pct(tier, cfg)
    over = bool(cfg_n["enabled"]) and float(equiv["equiv_pct"]) > cap
    severity = {"off": 0, "ignore": 0, "ok": 0, "warn": 1, "red": 2}
    action = str(cfg_n["gate_mode"]) if over else "off"
    unknown = list(equiv["unknown"])
    if unknown and severity.get(str(cfg_n["unknown_axis"]), 1) > severity.get(action, 0):
        action = str(cfg_n["unknown_axis"])
    if action in ("off", "ignore", ""):
        action = "ok"
    return {
        "enabled": bool(cfg_n["enabled"]),
        "equiv_pct": float(equiv["equiv_pct"]),
        "output_pct": float(equiv["output_pct"]),
        "survival_pct": float(equiv["survival_pct"]),
        "cap_pct": float(cap),
        "over": over,
        "gate_mode": str(cfg_n["gate_mode"]),
        "unknown": unknown,
        "unknown_axis": str(cfg_n["unknown_axis"]),
        "action": action,
    }


# ---------------------------------------------------------------------------
# 批56 · 过量治疗开关（`settings.overheal`）—— D4 裁决 / 轴全集 §4-E5
# 批59 · BV-1（上限可配）/ BV-2（去向选择点显式化）
# ---------------------------------------------------------------------------
# E5 口径（原文）：过量治疗 `overheal` = **布尔开关**（治疗可否超过最大 HP），无连续方向；
# **不要**用 `healing_received_mult ≥ 0` 表达。它不是特效轴（故不登记进 EFFECT_AXIS_SPECS），
# 而是另立一个内容包开关段，对齐 `settings.effect_budget` 的「包声明 + 框架登记」风格。
#
# **缺省口径 = 与现状一致（丢弃）**：`enabled=false` / 缺段 → 治疗量按 max_hp 封顶，
# 过量部分丢弃（逐字段零变化）。`enabled=true`（或 `mode="keep"`）→ 按 E5 字面
# 「可否超过最大 HP」= **保留**：HP 可超过 max_hp。
#
# 批59 落地的两个待裁决（BV-1 / BV-2）：
#   · **BV-1 上限**：E5 只给布尔、未写「最多超多少」→ 实现为**可配上限**（`cap_pct` =
#     最多超出 max_hp 的百分比；`cap_flat` = 最多超出的点数；同给取**更小**）。
#     **缺省都不给 = 无额外上限**（与批56 现状一致）。
#   · **BV-2 去向**：设计未写清是否转护盾、与既有护盾阶段（伤害链②）先后 →
#     用 `mode` 把选择点**显式化**：本批只实现 `keep`（保留 HP 超额）/ `discard`
#     （丢弃 = 现状）；`shield`（转护盾）是**保留扩展位、未实现**（校验器黄提示）——
#     **不做半成品开关**，护盾阶段原样不动。
#: `settings.overheal` 段键名。
OVERHEAL_KEY: str = "overheal"

#: BV-2 去向枚举（**本批实现**）：keep = 保留 HP 超额；discard = 丢弃（= 现状）。
OVERHEAL_MODES: Tuple[str, ...] = ("keep", "discard")

#: BV-2 **保留未实现**的去向：`shield`（转护盾）。设计未写清 → 不实现、不接受其生效，
#: 校验器只给黄提示（点名「未实现」），避免把半成品开关伪装成可用。
OVERHEAL_MODE_RESERVED: Dict[str, str] = {
    "shield": "转护盾（BV-2）未实现：过量部分去向 / 与既有护盾阶段的先后设计未写清，"
              "本批只支持 mode=keep|discard",
}

#: 缺省声明：discard = 现状（过量丢弃）。**不配置 = 与引入前逐字段一致**。
#: `cap_pct` / `cap_flat` 缺省 None = 无额外上限（BV-1，与批56 现状一致）。
DEFAULT_OVERHEAL: Dict[str, Any] = {
    "enabled": False,
    "mode": "discard",
    "cap_pct": None,
    "cap_flat": None,
}


def normalize_overheal(cfg: Any) -> Dict[str, Any]:
    """`settings.overheal` → 有效声明（缺省 ⊕ 包覆盖；读时归一，不改战斗数值）。

    接受形态（非法一律回落缺省 = discard）：
      · `{"enabled": true/false}`（批56 兼容）；
      · `{"mode": "keep"|"discard"}`（批59 显式去向；给出且合法时以 mode 为准）；
      · 裸布尔 `true/false`（宽松兼容）；
      · 缺段 / None / 其它 → discard。

    `cap_pct` / `cap_flat`（BV-1）：非负数值；缺省 / 非法 / 负 → None（= 无额外上限）。
    返回 `{enabled, mode, cap_pct, cap_flat}`；`mode == "keep"` ⇔ `enabled is True`。
    """
    enabled = False
    mode = "discard"
    mapping = cfg if isinstance(cfg, Mapping) else None
    if isinstance(cfg, bool):
        enabled = bool(cfg)
        mode = "keep" if enabled else "discard"
    elif mapping is not None:
        raw_mode = mapping.get("mode")
        if isinstance(raw_mode, str) and raw_mode in OVERHEAL_MODES:
            mode = raw_mode
            enabled = mode == "keep"
        else:
            raw = mapping.get("enabled", False)
            if isinstance(raw, bool):
                enabled = raw
                mode = "keep" if enabled else "discard"
    cap_pct = _as_effect_number(mapping.get("cap_pct")) if mapping is not None else None
    cap_flat = _as_effect_number(mapping.get("cap_flat")) if mapping is not None else None
    return {
        "enabled": enabled,
        "mode": mode,
        "cap_pct": max(0.0, cap_pct) if cap_pct is not None else None,
        "cap_flat": max(0.0, cap_flat) if cap_flat is not None else None,
    }


def overheal_enabled(cfg: Any = None) -> bool:
    """`settings.overheal` 是否启用保留（缺省/非法 → False = 现状丢弃）。"""
    return bool(normalize_overheal(cfg)["enabled"])


def overheal_cap(max_hp: Any, cfg: Any = None) -> Optional[float]:
    """BV-1：过量治疗下允许的 **HP 上限**（`max_hp` = 不过量时的既有封顶）。

    · 未启用 → 返回 `max_hp`（调用方照旧封顶 → 缺省零变化）；
    · 启用且**未给** `cap_pct/cap_flat` → `None` = **无额外上限**（批56 现状）；
    · 给了 → `max_hp × (1 + cap_pct/100)` 与 `max_hp + cap_flat` 取**更小**者。
    纯读声明、**不写死数值**；非法 `max_hp` 按 0 计。
    """
    base = (float(max_hp)
            if isinstance(max_hp, (int, float)) and not isinstance(max_hp, bool) else 0.0)
    n = normalize_overheal(cfg)
    if not n["enabled"]:
        return base
    ceilings = []
    if n["cap_pct"] is not None:
        ceilings.append(base * (1.0 + float(n["cap_pct"]) / 100.0))
    if n["cap_flat"] is not None:
        ceilings.append(base + float(n["cap_flat"]))
    return min(ceilings) if ceilings else None

