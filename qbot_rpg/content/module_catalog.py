"""框架通用模块目录（内容编辑器批8 · 顶栏「模块开关」的数据源）。

定位（用户 2026-09-13 点名）：
  · 空白包没有任何模块声明，编辑器左栏全空 → 小白用户不知道从哪开始；
  · 给一个「可启用模块清单」，勾选后写入包 `manifest.json` 的 `modules` 并按骨架创建数据文件。

**模块种类是框架概念**：这里的模块键、通用中文默认名、一句话用途、骨架形态（entry_type）、
前置模块（requires）都属于「框架通用知识」，与「展示元数据下放（展示文案进包）」不冲突：

  · 本表只在**包没有声明中文名时**兜底；包内 `field_meta.json.module_labels` /
    `manifest.module_labels` / `module_tree` 节点 label 声明了中文名 → **优先用包的**
    （优先级实现在 `qbot_rpg/web/api.py::module_catalog`，与只读层同一口径）；
  · 本表不含任何内容包的专属业务字段（没有属性表 / 套装 / buff 表之类），
    换包零改动：包的模块声明/展示声明变化时，编辑器代码不用改。

排除项（有意不放进「可启用清单」）：
  · `manifest` 不是独立数据文件（它就是包清单本身，`manifest.json`）；
  · `ai` / `hidden` / `env_event` / `log_card` / `editor` 是编辑器扩展视图 / 页表注册，
    没有对应的独立内容数据文件；
  这些模块若被某个包**已经在 manifest 里声明**，仍会出现在面板里（走「包声明」合集），
  只是不作为空白包的候选。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ModuleCatalogEntry:
    """一个「可启用模块」的框架通用知识。

    module     ：模块键（= manifest.modules 里的名字 = 数据文件名去后缀）
    label      ：通用中文默认名（包未声明中文名时的兜底；包声明优先）
    purpose    ：一句话用途（面板里给非技术用户看的说明）
    entry_type ：骨架形态（list → `[]`；map / object → `{}`）；与框架 ModuleMeta 一致
    requires   ：前置模块键（勾选本模块时若前置未启用 → 黄提示「建议同时启用」，不硬拦）
    implemented：引擎是否已实现（False = 目录条目仍列出但标「未实现」，不可启用；
                 一号原则：框架设计了但尚未实装的能力也让作者看得见，而不是消失）
    settings_section：配置当前实际落点（settings.json 的段路径）；非空 = 该「模块」目前
                 是能力标记，运行时配置读的是该 settings 段（编辑器据此提示作者去哪配）
    """

    module: str
    label: str
    purpose: str
    entry_type: str = "list"
    requires: Tuple[str, ...] = ()
    implemented: bool = True
    settings_section: str = ""
    # 编辑器批19 #5：与其他落点的**功能重叠**声明（通用、包无关的框架知识）。
    # `overlap_with` = 另一处落点（如 settings.json 的段路径）；非空 → 编辑器在模块页给
    # **黄提示**（不硬拦）：建议归口一处，并展示 `overlap_note` 说明各自定位（如实核查）。
    overlap_with: str = ""
    overlap_note: str = ""


# 面板顶部的人话引导（面向非技术用户；不静默）。
MODULE_PANEL_HINT = (
    "勾选你要做的内容类型；不勾的模块不会出现在左侧模块树。"
    "停用只会移除声明，数据文件保留，重新勾选即可恢复。"
)

# =====================================================================================
# 框架通用模块目录（顺序 = 面板默认展示顺序：先内容模块，后规则/设置类）
# =====================================================================================
FRAMEWORK_MODULE_CATALOG: Tuple[ModuleCatalogEntry, ...] = (
    # ---- 内容主体：技能家族 ----
    ModuleCatalogEntry("skills", "技能", "玩家可释放的技能条目。", "list"),
    ModuleCatalogEntry("skill_chains", "派生链", "技能之间的派生 / 连段关系（触发技 → 后继技）。",
                       "list", requires=("skills",)),
    ModuleCatalogEntry("effects", "效果", "可复用效果：伤害、治疗、印记增减等。", "list"),
    ModuleCatalogEntry("statuses", "状态", "持续若干回合的状态与叠加规则。", "list"),
    ModuleCatalogEntry("marks", "印记", "战斗中的可消耗 / 可叠加印记定义。", "list"),
    ModuleCatalogEntry("action", "行动", "独立行动定义（供技能 / 怪物引用）。", "list"),
    ModuleCatalogEntry("jobs", "职业", "职业注册表与转职变换规则。", "list"),
    # ---- 内容主体：物品家族 ----
    ModuleCatalogEntry("items", "物品", "可持有 / 可使用 / 可丢弃的物品条目。", "list"),
    ModuleCatalogEntry("equipment", "装备", "物品中的装备类（部位、属性、词条、套装）。",
                       "list", requires=("items",)),
    ModuleCatalogEntry("traits", "特性", "角色 / 物品的特性与被动标签。", "list"),
    ModuleCatalogEntry("recipe", "配方",
                       "合成配方：材料与产出（第 1 层【合成】，打造与炼金公用）。",
                       "list", requires=("items",), settings_section="settings.alchemy.mode"),
    ModuleCatalogEntry("proficiency", "熟练度", "熟练度等级与对应效果。", "list"),
    ModuleCatalogEntry("slots", "装备槽", "装备槽位定义（部位与可装备范围）。",
                       "list", requires=("items",),
                       # 批19 #5：与「基础 ▸ 装备槽位（settings.slot_defs）」功能重叠——实测
                       # 两个内容包的 slot_defs 各有 8 部位，而 slots.json 为空。编辑器给黄提示
                       # （不硬拦）：建议归口一处，并说明二者定位（不猜：见下方 overlap_note）。
                       overlap_with="settings.slot_defs",
                       overlap_note=(
                           "两处都在表达「装备部位定义」：settings.slot_defs 是运行时消费的"
                           "部位表（编辑器「基础 ▸ 装备槽位」可增删改，装备/物品的「部位」"
                           "引用它）；slots 模块（slots.json）是条目化的部位 / 可装备范围"
                           "定义。当前内容包把数据放在 settings.slot_defs（8 部位），"
                           "slots.json 为空。建议归口一处，避免两边同改不同步；"
                           "本提示不阻断保存。")),
    ModuleCatalogEntry("forge", "锻造", "锻造系统配置（词条、套装、强化目标）。", "object"),
    ModuleCatalogEntry("enhance", "强化", "装备强化的规则与等级效果。",
                       "object", requires=("equipment",)),
    ModuleCatalogEntry("fishing", "钓鱼", "钓鱼系统配置（鱼池、产出、难度）。", "object"),
    # ---- 框架已实现的生活/生产系统（编辑器批13 · 审计 ①-6）----
    # 说明：这些系统的运行时配置目前多落在 settings.<段>（settings_section 标注），
    # 文件型模块条目用于让作者在左栏/⚙ 面板看到「框架支持这项能力」；启用会创建空骨架。
    ModuleCatalogEntry("farming", "种植", "种植 / 温室：定时收获、田块与特性继承配置。",
                       "object", requires=("items",),
                       settings_section="settings.alchemy.farming"),
    ModuleCatalogEntry("contest", "品评会", "品评会：评分维度权重、周赛排期与冠军奖励。",
                       "object", requires=("proficiency",),
                       settings_section="settings.contest"),
    ModuleCatalogEntry("assistant", "代工助手", "代工助手：后台代采/代调、助手解锁与收取队列。",
                       "object", requires=("items",),
                       settings_section="settings.assistant"),
    ModuleCatalogEntry("quest_board", "委托板", "委托板：委托池档位、刷新与声望门槛配置。",
                       "object", requires=("quest",),
                       settings_section="settings.quest_board"),
    ModuleCatalogEntry("codex", "图鉴", "图鉴：四册（怪物/鱼/物品/制造）完成度加权。",
                       "object", settings_section="settings.codex"),
    # 采集/挖掘（批36 · X2）：`/采集` 独立指令 + `maps.gather_points` 结算已实装
    # （core/gathering.py + commands/gather_commands.py + map_models 校验 V-1Z~V-5Z）。
    # 数据落点 = maps 子段（U1 已裁决），故无独立数据文件、无 settings 段——
    # 启用本模块 = 声明「本包使用地图采集点」；实际配置在地图卡片【采集点】里。
    ModuleCatalogEntry("gathering", "采集/挖掘", "在地图采集点采集素材（含天气出率修正）。",
                       "object", requires=("maps",)),
    # ---- 内容主体：世界与交互 ----
    ModuleCatalogEntry("enemies", "怪物", "敌人条目：属性、行动、掉落、阶段。", "list"),
    ModuleCatalogEntry("maps", "地图", "地图与场景：区域、出口、怪物、机关。", "list"),
    ModuleCatalogEntry("dungeon", "副本", "副本配置：层数、房间、进入条件。", "list"),
    ModuleCatalogEntry("npc", "NPC", "可交互 NPC：对话、功能、位置。", "list"),
    ModuleCatalogEntry("shop", "商店", "商店售卖的物品与货币。", "list"),
    ModuleCatalogEntry("quest", "任务", "任务定义：条件、目标、奖励。", "list"),
    ModuleCatalogEntry("checkin", "签到", "签到 / 每日奖励配置。", "list"),
    ModuleCatalogEntry("achievements", "成就", "成就条目与解锁条件。", "list"),
    # ---- 规则与全局数据 ----
    ModuleCatalogEntry("conditional", "条件加成", "条件触发的属性加成规则。", "object"),
    ModuleCatalogEntry("stats", "属性表", "游戏属性定义（属性键 → 属性值对象）。", "map"),
    ModuleCatalogEntry("formula", "公式库", "可复用公式与数值表达式。", "map"),
    ModuleCatalogEntry("templates", "消息模板", "消息文案的模板覆盖（键 = 模板名，值 = 文案）。",
                       "map"),
    ModuleCatalogEntry("settings", "通用设置", "全局设置：经济、惩罚、面板、指令别名等。",
                       "object"),
)

# 模块键 → 目录条目（只读索引；供 API / 写入层按模块键查询）。
CATALOG_BY_MODULE: Dict[str, ModuleCatalogEntry] = {
    entry.module: entry for entry in FRAMEWORK_MODULE_CATALOG
}


def catalog_entry(module: object) -> Optional[ModuleCatalogEntry]:
    """按模块键取目录条目（未知模块 → None；不抛）。"""
    if not isinstance(module, str):
        return None
    return CATALOG_BY_MODULE.get(module)


__all__ = [
    "CATALOG_BY_MODULE",
    "FRAMEWORK_MODULE_CATALOG",
    "MODULE_PANEL_HINT",
    "ModuleCatalogEntry",
    "catalog_entry",
]
