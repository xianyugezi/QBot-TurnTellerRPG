#!/usr/bin/env python3
"""G0 架构检查脚本（细化_3a §六 验收 TC-01 ~ TC-04 / 铁律 R1-R3 / D-03）。

纯 ast 静态扫描，**不 import 任何 qbot_rpg 模块** —— 零依赖可运行（脱离 NoneBot / fastapi）。
检查项（对齐细化_3a §六 覆盖矩阵 ①/②）：

  TC-01   ast 全仓扫描 qbot_rpg/{core,world,storage,content,data} 全部 .py（递归），
          断言 import 图无任何 nonebot（Import/ImportFrom 节点；含 importlib 动态加载）→ R1
  TC-02   全仓扫描 import nonebot 的文件集合，仅允许 qbot_rpg/commands/ 内 → R2
  TC-03   qbot_rpg 全包 import 图分析：
            · core/world/storage/content/data 之间无环（Kahn 拓扑）
            · commands/web 不被任何层 import
            · 依赖方向符合 §1.4 矩阵（web→{content,core,storage,data} 等，反向即违规）→ R3 / D-05
  TC-06   跨域业务直调冻结（跨族且目标为业务模块 → 新增即失败；日研 Q1 口径②）\n  TC-05   core 内部直调边冻结（新增 core→core import 即失败；日研 Q1）
  TC-04   data/ 五类（Player/BattleSnapshot/StatusInstance/ItemInstance/WorldState）
          各定义一次（全仓唯一）且 dataclass(frozen=True) → D-03 / U1

退出码：全部通过 → 打印 ARCH-OK，exit 0；任一失败 → 打印违规清单，exit 1。
用法：python scripts/check_architecture.py [--path 仓库根]   （默认取脚本所在目录的父目录 = 仓库根）
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from typing import Dict, FrozenSet, Iterator, List, Optional, Sequence, Set, Tuple

# 零 NoneBot 五层（TC-01 扫描范围；web 属平台无关但不在此 5 层扫描集，见细化_3a TC-01）
ZERO_NB_LAYERS: Tuple[str, ...] = ("core", "world", "storage", "content", "data")
# 依赖方向矩阵（细化_3a §1.4 / §2.2）：layer -> 允许依赖的 qbot_rpg 层
ALLOWED_DEP: Dict[str, Set[str]] = {
    "commands": {"core", "world", "storage", "content", "data"},
    "web": {"content", "core", "storage", "data"},
    "core": {"data", "content", "world", "storage"},
    # core 依赖面（细化_3a §1.4 原文）：data、content（registry 只读）、world（写世界状态）、
    # storage（经 repository 接口）。2026-09-10 架构违规修复：原 ALLOWED_DEP 私设第 8 层
    # "engine"（契约 §1.4 只有 7 层），违反 §2.3「原 engine/ 更名 core/」的收敛要求——
    # 已将 qbot_rpg/engine/{condition_engine,time_query,weather_conditions,
    # weather_consumers,worldtime}.py 迁入 qbot_rpg/core/，engine 层撤销。
    "world": {"data", "storage", "content"},
    "storage": {"data"},
    "content": {"data"},
    "data": set(),
    # M7 装配层（顶层）：组装 commands 指令组 + 全业务层接线，方向放行（见 TC-03 slayer 豁免）
    "assembly": {"commands", "core", "world", "storage", "content", "data"},
    "root": set(),  # qbot_rpg/__init__.py 包元信息；不参与方向约束（M0 无业务 import）
}
# TC-05 · core 内部「业务模块直调」冻结基线（2026-10-10 · 日研 Q1 口子）
# 口径：core/ 下 **文件级** import 边（同层互引在 §1.4 矩阵下合法，但按用户口径
# 「L1 业务模块间禁直调、必须走事件」——先**冻结现状**，禁止新增直调边；
# 新增边须走事件/注册表，或在**本表**登记并写明理由（治理元数据例外：登记即承诺）。
# 由脚本自身扫描口径生成（`collect_import_edges`），共 192 条。
CORE_EDGE_BASELINE: FrozenSet[str] = frozenset((
"qbot_rpg/core/achievements.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/achievements.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/adventure_log.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/alchemy_affinity.py -> qbot_rpg/core/affinity.py",
    "qbot_rpg/core/alchemy_affinity.py -> qbot_rpg/core/deep_craft.py",
    "qbot_rpg/core/alchemy_auto.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/alchemy_battle.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/alchemy_battle.py -> qbot_rpg/core/energy_bar.py",
    "qbot_rpg/core/alchemy_battle.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/alchemy_battle.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/alchemy_core.py -> qbot_rpg/core/affinity.py",
    "qbot_rpg/core/alchemy_core.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/alchemy_deep.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/alchemy_deep.py -> qbot_rpg/core/alchemy_session.py",
    "qbot_rpg/core/alchemy_deep.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/alchemy_deep.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/alchemy_deep.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/alchemy_harvest.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/alchemy_harvest.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/alchemy_harvest.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/alchemy_helper.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/alchemy_helper.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/alchemy_helper.py -> qbot_rpg/core/synthesis.py",
    "qbot_rpg/core/alchemy_helper.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/alchemy_meta.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/alchemy_meta.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/alchemy_settle.py -> qbot_rpg/core/alchemy_affinity.py",
    "qbot_rpg/core/alchemy_settle.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/alchemy_settle.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/alchemy_settle.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/__init__.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/battle_season.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/combo.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/combo_settle.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/combo_table.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/ctb_rules.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/ctb_scheduler.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/damage.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/damage_stats.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/effects.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/equip_mods.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/event_dispatcher.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/formula_engine.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/formula_loader.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/marks.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/monster_ai.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/monster_chains.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/position.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/resource_axis.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/resource_lifecycle.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/season_events.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/skill_season.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/transform.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/transform_revert.py",
    "qbot_rpg/core/battle_reward.py -> qbot_rpg/core/levelup.py",
    "qbot_rpg/core/battle_reward.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/checkin.py -> qbot_rpg/core/dayroll.py",
    "qbot_rpg/core/checkin.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/checkin.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/checkin.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/codex.py -> qbot_rpg/core/adventure_log.py",
    "qbot_rpg/core/codex.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/codex_milestones.py -> qbot_rpg/core/adventure_log.py",
    "qbot_rpg/core/codex_milestones.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/codex_milestones.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/combo.py -> qbot_rpg/core/position.py",
    "qbot_rpg/core/combo_settle.py -> qbot_rpg/core/combo_table.py",
    "qbot_rpg/core/combo_table.py -> qbot_rpg/core/__init__.py",
    "qbot_rpg/core/combo_table.py -> qbot_rpg/core/resource_axis.py",
    "qbot_rpg/core/ctb_config.py -> qbot_rpg/core/ctb_rules.py",
    "qbot_rpg/core/ctb_scheduler.py -> qbot_rpg/core/ctb_rules.py",
    "qbot_rpg/core/decompose.py -> qbot_rpg/core/temper.py",
    "qbot_rpg/core/deep_craft.py -> qbot_rpg/core/affinity.py",
    "qbot_rpg/core/dialog.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/dialog.py -> qbot_rpg/core/message_format/__init__.py",
    "qbot_rpg/core/dungeon.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/dungeon_boss.py -> qbot_rpg/core/monster_phases.py",
    "qbot_rpg/core/effects.py -> qbot_rpg/core/combo.py",
    "qbot_rpg/core/effects.py -> qbot_rpg/core/effect_types.py",
    "qbot_rpg/core/effects.py -> qbot_rpg/core/formula_engine.py",
    "qbot_rpg/core/effects.py -> qbot_rpg/core/marks.py",
    "qbot_rpg/core/enhance_affix.py -> qbot_rpg/core/affinity.py",
    "qbot_rpg/core/enhance_affix.py -> qbot_rpg/core/deep_craft.py",
    "qbot_rpg/core/environment_events.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/environment_events.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/environment_lore.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/environment_lore.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/environment_lore.py -> qbot_rpg/core/investigate.py",
    "qbot_rpg/core/environment_lore.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/equip_mods.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/equipment.py -> qbot_rpg/core/panel_budget.py",
    "qbot_rpg/core/equipment.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/equipment.py -> qbot_rpg/core/runes.py",
    "qbot_rpg/core/event_dispatcher.py -> qbot_rpg/core/effect_types.py",
    "qbot_rpg/core/event_dispatcher.py -> qbot_rpg/core/effects.py",
    "qbot_rpg/core/fishing.py -> qbot_rpg/core/dayroll.py",
    "qbot_rpg/core/fishing.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_bait.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_cast.py -> qbot_rpg/core/fishing.py",
    "qbot_rpg/core/fishing_codex.py -> qbot_rpg/core/adventure_log.py",
    "qbot_rpg/core/fishing_codex.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/fishing_codex.py -> qbot_rpg/core/fishing_crown.py",
    "qbot_rpg/core/fishing_crown.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_economy.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_job.py -> qbot_rpg/core/fishing_codex.py",
    "qbot_rpg/core/fishing_job.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/fishing_king.py -> qbot_rpg/core/dayroll.py",
    "qbot_rpg/core/fishing_king.py -> qbot_rpg/core/fishing_codex.py",
    "qbot_rpg/core/fishing_king.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_mode.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_roll.py -> qbot_rpg/core/fishing_bait.py",
    "qbot_rpg/core/fishing_roll.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_settle.py -> qbot_rpg/core/fishing_codex.py",
    "qbot_rpg/core/fishing_settle.py -> qbot_rpg/core/fishing_crown.py",
    "qbot_rpg/core/fishing_settle.py -> qbot_rpg/core/fishing_settings.py",
    "qbot_rpg/core/fishing_settle.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/forge_augments.py -> qbot_rpg/core/forge_job.py",
    "qbot_rpg/core/forge_augments.py -> qbot_rpg/core/forge_sp.py",
    "qbot_rpg/core/forge_bounds.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/forge_deadlock.py -> qbot_rpg/core/forge_material.py",
    "qbot_rpg/core/forge_job.py -> qbot_rpg/core/forge_tree.py",
    "qbot_rpg/core/forge_job.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/forge_king.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/forge_king.py -> qbot_rpg/core/forge_tree.py",
    "qbot_rpg/core/forge_king.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/forge_material.py -> qbot_rpg/core/forge_tree.py",
    "qbot_rpg/core/forge_material.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/forge_progress.py -> qbot_rpg/core/forge_tree.py",
    "qbot_rpg/core/forge_set_skills.py -> qbot_rpg/core/forge_sets.py",
    "qbot_rpg/core/forge_sets.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/forge_sp.py -> qbot_rpg/core/forge_job.py",
    "qbot_rpg/core/forge_sp.py -> qbot_rpg/core/forge_tree.py",
    "qbot_rpg/core/forge_sp.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/formula_loader.py -> qbot_rpg/core/damage.py",
    "qbot_rpg/core/gathering.py -> qbot_rpg/core/weather_consumers.py",
    "qbot_rpg/core/gem_wallet.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/hidden_trigger.py -> qbot_rpg/core/adventure_log.py",
    "qbot_rpg/core/hidden_trigger.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/hidden_trigger.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/inventory.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/investigate.py -> qbot_rpg/core/adventure_log.py",
    "qbot_rpg/core/investigate.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/investigate.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/jewel.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/jewel.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/jewel.py -> qbot_rpg/core/runes.py",
    "qbot_rpg/core/job_slots.py -> qbot_rpg/core/skill_slots.py",
    "qbot_rpg/core/levelup.py -> qbot_rpg/core/event_bus.py",
    "qbot_rpg/core/levelup.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/message_format/battle_render.py -> qbot_rpg/core/message_format/list_render.py",
    "qbot_rpg/core/message_format/battle_render.py -> qbot_rpg/core/message_format/prefix_render.py",
    "qbot_rpg/core/message_format/battle_render.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/message_format/battle_render.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/message_format/panel_render.py -> qbot_rpg/core/message_format/prefix_render.py",
    "qbot_rpg/core/message_format/panel_render.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/monster_ai.py -> qbot_rpg/core/monster_chains.py",
    "qbot_rpg/core/monster_ai.py -> qbot_rpg/core/monster_conditions.py",
    "qbot_rpg/core/monster_ai.py -> qbot_rpg/core/monster_intent.py",
    "qbot_rpg/core/monster_ai.py -> qbot_rpg/core/monster_phases.py",
    "qbot_rpg/core/monster_conditions.py -> qbot_rpg/core/position.py",
    "qbot_rpg/core/npc.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/npc.py -> qbot_rpg/core/dayroll.py",
    "qbot_rpg/core/npc.py -> qbot_rpg/core/quest.py",
    "qbot_rpg/core/npc.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/player_attributes.py -> qbot_rpg/core/damage.py",
    "qbot_rpg/core/pvp.py -> qbot_rpg/core/battle.py",
    "qbot_rpg/core/pvp.py -> qbot_rpg/core/equip_mods.py",
    "qbot_rpg/core/pvp.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/pvp.py -> qbot_rpg/core/skill_slots_battle.py",
    "qbot_rpg/core/quest.py -> qbot_rpg/core/adventure_log.py",
    "qbot_rpg/core/quest.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/quest.py -> qbot_rpg/core/dayroll.py",
    "qbot_rpg/core/quest.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/reward.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/reward.py -> qbot_rpg/core/codex_milestones.py",
    "qbot_rpg/core/rune_battle.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/rune_battle.py -> qbot_rpg/core/jewel.py",
    "qbot_rpg/core/runes.py -> qbot_rpg/core/affinity.py",
    "qbot_rpg/core/shop.py -> qbot_rpg/core/condition_engine.py",
    "qbot_rpg/core/shop.py -> qbot_rpg/core/dayroll.py",
    "qbot_rpg/core/shop.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/shop.py -> qbot_rpg/core/templates/__init__.py",
    "qbot_rpg/core/synthesis.py -> qbot_rpg/core/proficiency.py",
    "qbot_rpg/core/synthesis.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/templates/__init__.py -> qbot_rpg/core/templates/base.py",
    "qbot_rpg/core/time_query.py -> qbot_rpg/core/worldtime.py",
    "qbot_rpg/core/trait_inherit.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/upgrade.py -> qbot_rpg/core/quality.py",
    "qbot_rpg/core/upgrade.py -> qbot_rpg/core/reward.py",
    "qbot_rpg/core/upgrade.py -> qbot_rpg/core/runes.py",
    "qbot_rpg/core/weather_conditions.py -> qbot_rpg/core/worldtime.py",
    "qbot_rpg/core/weather_consumers.py -> qbot_rpg/core/weather_conditions.py",
))
# ---------------------------------------------------------------- TC-06 口径
#: 「L1 业务模块族」前缀（同族内直调视为合法：同一玩法的内部实现细节）
CORE_FAMILY_PREFIXES: Tuple[str, ...] = (
    "alchemy",
    "ctb",
    "weather",
    "combo",
    "codex",
    "quest",
    "shop",
    "dungeon",
    "monster",
    "transform",
    "resource",
    "equip",
    "battle",
    "marks",
    "effects",
    "damage",
    "checkin",
    "position",
    "reward",
    "stats",
    "status",
    "season",
)
#: 支撑模块白名单（**允许被业务模块直调**；用户 2026-10-10 拍板口径②：
#: 基础设施 + 共享服务/基础件。fan-in 实测：__init__ 14 / reward 12 / condition_engine 9 /
#: event_bus 9 / proficiency 9 / quality 7 / dayroll 6 / adventure_log 6 / affinity 5）
CORE_SUPPORT_MODULES: Tuple[str, ...] = (
    "__init__",
    "adventure_log",
    "affinity",
    "condition_engine",
    "core",
    "ctb_config",
    "ctb_rules",
    "damage",
    "dayroll",
    "equip_mods",
    "event_bus",
    "event_dispatcher",
    "formula_engine",
    "formula_loader",
    "levelup",
    "marks",
    "message_format",
    "position",
    "proficiency",
    "quality",
    "resource_axis",
    "reward",
    "stats",
    "templates",
)
#: 跨族业务直调边冻结基线（52 条，2026-10-11 实测）：口径 = 源族≠目标族 且 目标不在支撑白名单。
#: 冻结后**新增跨族业务直调边即 FAIL**；收敛一条就从本表删一条（只提示，不奖励/不惩罚）。
CROSS_DOMAIN_BASELINE: FrozenSet[str] = frozenset((
    "qbot_rpg/core/alchemy_affinity.py -> qbot_rpg/core/deep_craft.py",
    "qbot_rpg/core/alchemy_battle.py -> qbot_rpg/core/energy_bar.py",
    "qbot_rpg/core/alchemy_helper.py -> qbot_rpg/core/synthesis.py",
    "qbot_rpg/core/alchemy_meta.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/combo.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/combo_settle.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/combo_table.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/ctb_scheduler.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/damage_stats.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/effects.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/monster_ai.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/monster_chains.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/resource_lifecycle.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/season_events.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/skill_season.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/transform.py",
    "qbot_rpg/core/battle.py -> qbot_rpg/core/transform_revert.py",
    "qbot_rpg/core/decompose.py -> qbot_rpg/core/temper.py",
    "qbot_rpg/core/dungeon_boss.py -> qbot_rpg/core/monster_phases.py",
    "qbot_rpg/core/effects.py -> qbot_rpg/core/combo.py",
    "qbot_rpg/core/effects.py -> qbot_rpg/core/effect_types.py",
    "qbot_rpg/core/enhance_affix.py -> qbot_rpg/core/deep_craft.py",
    "qbot_rpg/core/environment_lore.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/environment_lore.py -> qbot_rpg/core/investigate.py",
    "qbot_rpg/core/equip_mods.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/equipment.py -> qbot_rpg/core/panel_budget.py",
    "qbot_rpg/core/equipment.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/equipment.py -> qbot_rpg/core/runes.py",
    "qbot_rpg/core/event_dispatcher.py -> qbot_rpg/core/effect_types.py",
    "qbot_rpg/core/event_dispatcher.py -> qbot_rpg/core/effects.py",
    "qbot_rpg/core/forge_bounds.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/forge_king.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/forge_sets.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/gathering.py -> qbot_rpg/core/weather_consumers.py",
    "qbot_rpg/core/inventory.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/jewel.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/jewel.py -> qbot_rpg/core/runes.py",
    "qbot_rpg/core/job_slots.py -> qbot_rpg/core/skill_slots.py",
    "qbot_rpg/core/levelup.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/message_format/panel_render.py -> qbot_rpg/core/player_attributes.py",
    "qbot_rpg/core/npc.py -> qbot_rpg/core/quest.py",
    "qbot_rpg/core/pvp.py -> qbot_rpg/core/battle.py",
    "qbot_rpg/core/pvp.py -> qbot_rpg/core/skill_slots_battle.py",
    "qbot_rpg/core/reward.py -> qbot_rpg/core/codex.py",
    "qbot_rpg/core/reward.py -> qbot_rpg/core/codex_milestones.py",
    "qbot_rpg/core/rune_battle.py -> qbot_rpg/core/equipment.py",
    "qbot_rpg/core/rune_battle.py -> qbot_rpg/core/jewel.py",
    "qbot_rpg/core/templates/__init__.py -> qbot_rpg/core/templates/base.py",
    "qbot_rpg/core/time_query.py -> qbot_rpg/core/worldtime.py",
    "qbot_rpg/core/trait_inherit.py -> qbot_rpg/core/alchemy_core.py",
    "qbot_rpg/core/upgrade.py -> qbot_rpg/core/runes.py",
    "qbot_rpg/core/weather_conditions.py -> qbot_rpg/core/worldtime.py",
))

# TC-04 五类（细化_3a §3.2 / D-03）
REQUIRED_TYPES: Tuple[str, ...] = (
    "Player", "BattleSnapshot", "StatusInstance", "ItemInstance", "WorldState",
)

_OK = True


def _is_falsy_constant(node: ast.AST) -> bool:
    """字面量假值（False/0/''/None）——`if False:` 死分支判定。"""
    return isinstance(node, ast.Constant) and not bool(node.value)


def _is_truthy_constant(node: ast.AST) -> bool:
    """字面量真值（True/非 0 数/非空串）。"""
    return isinstance(node, ast.Constant) and bool(node.value)


def walk_live(tree: ast.AST) -> Iterator[ast.AST]:
    """遍历 AST，跳过**字面量常假分支**的死代码（`if False: import x` 不产生真实依赖边）。

    - test 为常假常量 → 只走 orelse；常真常量 → 只走 body；否则两分支都要。
    用于 import 图 / nonebot 扫描 / 类定义归属，保证静态扫描与真实运行时一致。
    """
    stack: List[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        yield node
        children: List[ast.AST]
        if isinstance(node, ast.If):
            if _is_falsy_constant(node.test):
                children = list(node.orelse)
            elif _is_truthy_constant(node.test):
                children = list(node.body)
            else:
                children = list(ast.iter_child_nodes(node))
        else:
            children = list(ast.iter_child_nodes(node))
        stack.extend(reversed(children))


def _fail(msg: str) -> None:
    global _OK
    _OK = False
    print(f"  ✗ {msg}")


def iter_qbot_py_files(repo_root: str) -> List[str]:
    """qbot_rpg/ 下全部 .py（递归，跳过 __pycache__/.venv）。"""
    pkg = os.path.join(repo_root, "qbot_rpg")
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(pkg):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def layer_of(path: str) -> str:
    """文件所属层：qbot_rpg/<layer>/... → layer；qbot_rpg/__init__.py → root。"""
    parts = os.path.relpath(path).split(os.sep)
    for i, p in enumerate(parts):
        if p == "qbot_rpg":
            return parts[i + 1] if i + 1 < len(parts) else "root"
    return "unknown"


def _importlib_dynamic(tree: ast.Module, file: str) -> List[Tuple[str, str]]:
    """检测 importlib.import_module / __import__ 动态加载 nonebot（TC-01 强调 importlib）。"""
    hits: List[Tuple[str, str]] = []

    def _arg_str(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    for node in walk_live(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            target_names: Optional[Tuple[str, ...]] = None
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "importlib" and fn.attr == "import_module":
                target_names = ("importlib.import_module",)
            elif isinstance(fn, ast.Name) and fn.id == "__import__":
                target_names = ("__import__",)
            if target_names is not None and node.args:
                name = _arg_str(node.args[0])
                if name and name == "nonebot" or (name and name.startswith("nonebot.")):
                    hits.append((file, f"{target_names[0]}('{name}') (2-arg/_dynamic)"))
    return hits


def find_nonebot_imports(tree: ast.Module, file: str) -> List[Tuple[str, str, int]]:
    """返回实际 import nonebot 的 (文件, 描述, 行号) 列表（Import/ImportFrom 节点 + 动态加载）。

    遍历**活代码**（walk_live 跳过 `if False:` / `if TYPE_CHECKING:` 类死分支），
    与运行时行为一致 —— 死分支里的 import 不构成真实 nonebot 依赖（R1/R2 口径）。

    P1-1（架构复查）：ImportFrom 节点同时检查 `node.module` 与符号名——
    `from nonebot import on_command` 的 module 才是 "nonebot"，只比对 alias.name
    会漏检这一契约明文点名的形态（NoneBot 插件最惯用写法）。
    """
    hits: List[Tuple[str, str, int]] = []
    for node in walk_live(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if mod == "nonebot" or mod.startswith("nonebot."):
                    hits.append((file, f"import {mod}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "nonebot" or mod.startswith("nonebot."):
                names = ", ".join(a.name for a in node.names)
                hits.append((file, f"from {mod} import {names}", node.lineno))
    for f, desc in _importlib_dynamic(tree, file):
        hits.append((f, desc, 0))
    return hits


def _edge_key(root: str, src: str, dst: str) -> str:
    """相对仓库根的稳定边键：`qbot_rpg/core/a.py -> qbot_rpg/core/b.py`。"""
    rel_src = os.path.relpath(src, root).replace(os.sep, "/")
    rel_dst = os.path.relpath(dst, root).replace(os.sep, "/")
    return f"{rel_src} -> {rel_dst}"


def check_tc01(root: str, files: List[str]) -> None:
    """TC-01：零 NoneBot 五层无一 nonebot import（R1）。"""
    print("TC-01  零 NoneBot 五层（core/world/storage/content/data）无 nonebot import（R1）")
    violations: List[str] = []
    for file in files:
        layer = layer_of(file)
        if layer not in ZERO_NB_LAYERS:
            continue
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError as exc:
            violations.append(f"{file} 语法错误: {exc}")
            continue
        for _, desc, lineno in find_nonebot_imports(tree, file):
            violations.append(f"{file}:{lineno}  {desc}")
    if violations:
        for v in violations:
            _fail(f"TC-01 命中：{v}")
    else:
        print("  ✓ 通过（未发现任何 nonebot import 节点）")


def check_tc02(root: str, files: List[str]) -> None:
    """TC-02：全仓 nonebot import 仅允许 qbot_rpg/commands/ 内（R2）。"""
    print("TC-02  全仓 nonebot import 仅允许 qbot_rpg/commands/ 内（R2）")
    commands_dir = os.path.join(root, "qbot_rpg", "commands")
    offenders: List[str] = []
    for file in files:
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError as exc:
            _fail(f"TC-02 语法错误：{file}: {exc}")
            continue
        hits = find_nonebot_imports(tree, file)
        for hit_file, desc, lineno in hits:
            if not os.path.dirname(hit_file).startswith(commands_dir):
                offenders.append(f"{hit_file}:{lineno}  {desc}")
    if offenders:
        for o in offenders:
            _fail(f"TC-02 越界（非 commands/）：{o}")
    else:
        print("  ✓ 通过（nonebot import 集合为空或全部位于 commands/ 内）")


# ---------------------------------------------------------------------------
# import 图解析（TC-03）
# ---------------------------------------------------------------------------
def _resolve_module(parts: Sequence[str], repo_root: str) -> Optional[str]:
    """把 qbot_rpg 模块路径点组件解析为磁盘上**真实存在**的 .py 文件；不存在 → None。

    - parts == ["qbot_rpg"]                             → qbot_rpg/__init__.py
    - parts == ["qbot_rpg", "data", "types"]            → 先 data/types.py，再 data/types/__init__.py
    - 没有任何真实文件命中 → None（**不发明兜底路径**，避免伪造依赖边/伪环）
    """
    if not parts or parts[0] != "qbot_rpg":
        return None
    pkg_root = os.path.join(repo_root, "qbot_rpg")
    if len(parts) == 1:
        return os.path.join(pkg_root, "__init__.py")
    rel = os.path.join(*parts[1:])
    for cand in (
        os.path.join(pkg_root, rel + ".py"),
        os.path.join(pkg_root, rel, "__init__.py"),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def _resolve_submodule(module_parts: Sequence[str], name: str, repo_root: str) -> Optional[str]:
    """``from 模块 import name`` 时，name 若为真实子模块（如 from qbot_rpg.data import player）→ 边；否则 None。"""
    if not name or name == "*":
        return None
    return _resolve_module(list(module_parts) + [name], repo_root)


def _type_checking_nodes(tree: ast.Module) -> Set[int]:
    """收集 ``if TYPE_CHECKING:`` 块的子孙节点 id（这些 import 运行时不存在，不产生真实依赖边）。

    2026-09-10 修复「循环 import 误报」：content/models.py 用
    ``if TYPE_CHECKING: from qbot_rpg.content.registry import Registry`` 做前向引用
    （避免 content 层内部成环），运行时该分支不执行、不 import——TC-03 契约「禁止循环
    import」的语义是**运行时依赖图**，故 TYPE_CHECKING 分支必须排除。
    与 walk_live 的「字面量常假分支」不同：TYPE_CHECKING 是 typing 常量（值为 False），
    ast 层面无法按常量求值，需按名字显式识别。
    """
    out: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        )
        if is_tc:
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    out.add(id(child))
    return out


def collect_import_edges(tree: ast.Module, file: str, repo_root: str) -> List[str]:
    """返回该文件 import 的 intra-qbot_rpg 目标文件路径列表（含相对 import 解析）。

    TYPE_CHECKING 块内的 import 不计（前向引用，运行时无依赖边 → 不参与环判定）。
    """
    pkg_depth = file.replace(repo_root, "").lstrip(os.sep).split(os.sep)
    cur_pkg = pkg_depth[:-1]  # 文件所在包（不含文件名）
    # 例如 qbot_rpg/core/player_attributes.py → ["qbot_rpg","core"]
    edges: List[str] = []
    tc_skips = _type_checking_nodes(tree)
    for node in walk_live(tree):
        if id(node) in tc_skips:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                t = _resolve_module(alias.name.split("."), repo_root)
                if t and t != file:
                    edges.append(t)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if not node.module:
                    continue
                module_parts: List[str] = node.module.split(".")
                base = _resolve_module(module_parts, repo_root)
                if base and base != file:
                    edges.append(base)
                # from X import name：name 若为真实子模块（from qbot_rpg.data import player）→ 加边
                for al in node.names:
                    sub = _resolve_submodule(module_parts, al.name, repo_root)
                    if sub and sub != file:
                        edges.append(sub)
            else:
                # 相对 import：node.level 往上跳；node.module 为同层子模块名（可为 None）
                up = node.level
                base_pkg = cur_pkg[: len(cur_pkg) - (up if up < len(cur_pkg) else len(cur_pkg))]
                if not base_pkg:
                    continue
                sub = node.module or ""
                cand_parts = base_pkg + ([sub] if sub else [])
                base = _resolve_module(cand_parts, repo_root)
                if base and base != file:
                    edges.append(base)
                if sub:
                    for al in node.names:
                        subb = _resolve_module(base_pkg + [sub, al.name], repo_root)
                        if subb and subb != file:
                            edges.append(subb)
    return list(dict.fromkeys(edges))  # 去重保序


def check_tc03(root: str, files: List[str]) -> None:
    """TC-03：import 图——依赖方向 + 无环 + commands/web 不被依赖（R3 / D-05）。"""
    print("TC-03  import 图：依赖方向矩阵 + 无环 + commands/web 不被依赖（R3/D-05）")
    by_file: Dict[str, Tuple[str, List[str]]] = {}  # file -> (layer, targets)
    for file in files:
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError as exc:
            _fail(f"TC-03 语法错误：{file}: {exc}")
            continue
        by_file[file] = (layer_of(file), collect_import_edges(tree, file, root))

    layer_violations: List[str] = []
    for src, (slayer, targets) in by_file.items():
        for tgt in targets:
            tlayer = layer_of(tgt)
            if tlayer == slayer:
                continue  # 同层内部模块互引合法（§1.4 矩阵只约束跨层方向）
            if slayer == "assembly":
                continue  # M7 装配层：顶层接线 commands 指令组 + 全业务层，方向豁免（ADR-03）
            if tlayer in ("commands", "web"):
                layer_violations.append(
                    f"{os.path.relpath(src)} → {os.path.relpath(tgt)}："
                    f"commands/web 被依赖（TC-03 禁止）"
                )
            else:
                allowed = ALLOWED_DEP.get(slayer)
                if allowed is not None and tlayer not in allowed:
                    layer_violations.append(
                        f"{os.path.relpath(src)}[{slayer}] → {os.path.relpath(tgt)}[{tlayer}]："
                        f"违反依赖矩阵 §1.4（{slayer} 允许: {allowed}）"
                    )

    # 有向环检测：Kahn 拓扑（文件级全图；涉零五层+root+commands/web 一并判断）
    indeg: Dict[str, int] = {f: 0 for f in files if f in by_file}
    adj: Dict[str, List[str]] = {f: [] for f in files if f in by_file}
    for src, (_, targets) in by_file.items():
        for tgt in targets:
            if tgt in adj:
                adj[src].append(tgt)
                indeg[tgt] += 1
    queue = [f for f, d in indeg.items() if d == 0]
    order: List[str] = []
    while queue:
        f = queue.pop()
        order.append(f)
        for nxt in adj.get(f, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    cycled = [f for f, d in indeg.items() if d > 0]

    if layer_violations:
        for v in layer_violations:
            _fail(f"TC-03 依赖方向：{v}")
    elif cycled:
        _fail(f"TC-03 循环 import（拓扑剩余 {len(cycled)} 个节点，含环）: "
              + ", ".join(os.path.relpath(f) for f in sorted(cycled)))
    else:
        print(f"  ✓ 通过（{len(by_file)} 文件拓扑序合法、方向矩阵全绿、commands/web 无人依赖）")


def check_tc04(root: str, files: List[str]) -> None:
    """TC-04：五类各定义一次（全仓唯一）且 dataclass(frozen=True)（D-03 / U1）。"""
    print("TC-04  data/ 五类各定义一次且 frozen=True（D-03/U1）")
    found: Dict[str, List[Tuple[str, int, bool]]] = {n: [] for n in REQUIRED_TYPES}
    for file in files:
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError:
            continue
        for node in walk_live(tree):
            if isinstance(node, ast.ClassDef) and node.name in REQUIRED_TYPES:
                frozen = False
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "dataclass":
                        for kw in dec.keywords:
                            if kw.arg == "frozen" and (isinstance(kw.value, ast.Constant) and kw.value.value is True):
                                frozen = True
                found[node.name].append((file, node.lineno, frozen))
    problems: List[str] = []
    for name in REQUIRED_TYPES:
        defs = found[name]
        in_data = [d for d in defs if layer_of(d[0]) == "data"]
        outside = [d for d in defs if layer_of(d[0]) != "data"]
        if len(defs) == 0:
            problems.append(f"{name}：未定义（data/ 必须定义一次）")
        elif len(defs) > 1:
            problems.append(f"{name}：定义 {len(defs)} 次（应唯一）: "
                            + ", ".join(f"{os.path.relpath(d[0])}:{d[1]}" for d in defs))
        elif len(in_data) != 1:
            problems.append(f"{name}：定义不在 data/ 层（{os.path.relpath(in_data[0][0]) if (in_data or outside) else '无'}）")
        elif not in_data[0][2]:
            problems.append(f"{name}：data/{os.path.relpath(in_data[0][0])}:{in_data[0][1]} 缺 dataclass(frozen=True)")
        elif outside:
            problems.append(f"{name}：data/ 之外重复定义 -> {', '.join(os.path.relpath(o[0]) for o in outside)}")
    if problems:
        for p in problems:
            _fail(f"TC-04 命中：{p}")
    else:
        print("  ✓ 通过（Player/BattleSnapshot/StatusInstance/ItemInstance/WorldState 各一次 + frozen）")


def check_tc05(root: str, files: List[str]) -> None:
    """TC-05：core 内部直调边冻结 —— **新增** core→core import 边即失败（日研 Q1）。

    口径：同层互引在 §1.4 矩阵下合法（TC-03 有意放行），但按用户 2026-10-10 口径
    「L1 业务模块间禁直调、必须走事件」，先冻结现状：现有边登记在 `CORE_EDGE_BASELINE`
    （single source），**新增边**须改走事件/注册表，或在基线中登记并写明理由。
    边**减少**（重构合并）只提示不失败，避免「改好了反而红」。
    """
    print("TC-05  core 内部直调边冻结：新增 core→core import 边即失败（日研 Q1）")
    current: Set[str] = set()
    for file in files:
        if layer_of(file) != "core":
            continue
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError:
            continue
        for tgt in collect_import_edges(tree, file, root):
            if tgt == file or layer_of(tgt) != "core":
                continue
            current.add(_edge_key(root, file, tgt))

    added = sorted(current - CORE_EDGE_BASELINE)
    removed = sorted(CORE_EDGE_BASELINE - current)
    if added:
        for e in added:
            _fail(
                f"TC-05 新增 core 内部直调边：{e} —— 按口径应改走事件/注册表；"
                "确需直调请在 scripts/check_architecture.py:CORE_EDGE_BASELINE 登记并写明理由"
            )
    if removed:
        print(f"  · 提示：{len(removed)} 条基线边已不存在（重构删边，非违规）：{removed[:3]}"
              + (" …" if len(removed) > 3 else ""))
    if not added:
        print(f"  ✓ 通过（当前 {len(current)} 条 core 内部边，基线 {len(CORE_EDGE_BASELINE)} 条，无新增）")


def _module_stem(rel_path: str) -> str:
    """`qbot_rpg/core/alchemy_core.py` → `alchemy_core`（message_format 子包归一名）。"""
    parts = rel_path.split("/")
    if len(parts) >= 3 and parts[2] == "message_format":
        return "message_format"
    return os.path.basename(rel_path).removesuffix(".py")


def _family_of(stem: str) -> str:
    """模块名 → 业务族（支撑白名单 → `(支撑)`）。"""
    if stem in CORE_SUPPORT_MODULES:
        return "(支撑)"
    for prefix in CORE_FAMILY_PREFIXES:
        if stem.startswith(prefix):
            return prefix
    return stem.split("_")[0]


def check_tc06(root: str, files: List[str]) -> None:
    """TC-06：**跨域业务直调**冻结（用户 2026-10-10 口径②·日研 Q1）。

    口径：同族内直调合法；目标 ∈ `CORE_SUPPORT_MODULES`（基础设施 + 共享服务）合法；
    **跨族且目标是业务模块** = 应走事件/注册表的耦合 → 冻结现有 52 条（`CROSS_DOMAIN_BASELINE`），
    **新增即 FAIL**（比 TC-05 更精确：TC-05 冻结全部 core→core 边，TC-06 标出「该走事件」的那一批）。

    白名单/族划分**属治理元数据**：若把它们改宽（例如把业务模块挪进支撑白名单）会让基线边
    「突然合法」→ 本检查按**基线边失配**报 FAIL，要求显式登记（防静默绕过）。
    """
    print("TC-06  跨域业务直调冻结：新增 core 跨族业务 import 边即失败（口径②）")
    current: Set[str] = set()
    for file in files:
        if layer_of(file) != "core":
            continue
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError:
            continue
        for tgt in collect_import_edges(tree, file, root):
            if tgt == file or layer_of(tgt) != "core":
                continue
            key = _edge_key(root, file, tgt)
            s = _module_stem(key.split(" -> ")[0])
            d = _module_stem(key.split(" -> ")[1])
            if _family_of(s) == _family_of(d) or d in CORE_SUPPORT_MODULES:
                continue
            current.add(key)

    added = sorted(current - CROSS_DOMAIN_BASELINE)
    lost = sorted(CROSS_DOMAIN_BASELINE - current)
    if added:
        for e in added:
            _fail(
                f"TC-06 新增跨域业务直调边：{e} —— 跨族业务模块之间应走事件/注册表；"
                "确需直调请在 CROSS_DOMAIN_BASELINE 登记并写明理由"
            )
    if lost:
        print(f"  · 提示：{len(lost)} 条基线边已不在「跨域业务」口径内（收敛或分类变更）：{lost[:3]}"
              + (" …" if len(lost) > 3 else ""))
    if not added:
        print(f"  ✓ 通过（当前跨域业务边 {len(current)} 条，基线 {len(CROSS_DOMAIN_BASELINE)} 条，无新增）")


def main(argv: Optional[Sequence[str]] = None) -> int:
    global _OK
    parser = argparse.ArgumentParser(description="G0 架构检查（细化_3a TC-01~06）")
    parser.add_argument(
        "--path", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="仓库根目录（默认脚本父目录）",
    )
    args = parser.parse_args(argv)
    root = os.path.abspath(args.path)
    if not os.path.isdir(os.path.join(root, "qbot_rpg")):
        print(f"✗ 无效仓库根（无 qbot_rpg/）: {root}")
        return 2

    _OK = True
    files = iter_qbot_py_files(root)
    print(f"ARCH 扫描 {len(files)} 个 .py（{root}）")
    check_tc01(root, files)
    check_tc02(root, files)
    check_tc03(root, files)
    check_tc04(root, files)
    check_tc05(root, files)
    check_tc06(root, files)

    if _OK:
        print("ARCH-OK  TC-01/TC-02/TC-03/TC-04/TC-05/TC-06 全部通过（细化_3a 分层契约满足）")
        return 0
    print("ARCH-FAIL 存在违规，详见上方清单（质量门禁红）")
    return 1


if __name__ == "__main__":
    sys.exit(main())

