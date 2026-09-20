#!/usr/bin/env python3
"""批B 等价性门禁：对 veinborn/test_demo 做「迁移前（基线）↔ 迁移后」只读接口逐字段对拍。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C——
「迁移前后接口对拍 diff=0（键集合、label、help、group、module_tree 逐项比对）」。

做法：
  1. 用 `git worktree` 检出基线（默认 `DEFAULT_BASELINE_REF`；批23 重定），在基线树里跑
     `scripts/editor_readonly_snapshot.py`（`qbot_rpg` 走 PYTHONPATH 指向基线）；
  2. 在当前工作树跑同一脚本；
  3. 递归对拍两份 JSON，输出差异报告；**删除 = 0 且值变化 = 0（派生展示键除外）→ 退出码 0**，
     否则 1；迁移相关字段（label/help/group/module_labels/module_tree）另做严格断言。

增量容忍（2026-09-14，settings.battle.min_damage 实装）：
  批B 门禁的硬约束是「迁移不得修改/删除既有键」。后续批次**新增**字段（如
  settings.battle.min_damage）是合法演进，只应报告、不应冒充迁移差异。故对拍分两桶：
  hard=修改/删除（必须 0）、soft=新增（允许，列出）。列表元素带唯一 key/id/name 时逐键
  对齐，确保「既有元素被改」仍被 hard 抓住（不会因长度变化被整体跳过）。

判定口径（批15 语义化定稿，2026-09-15；实现见 `_diff` / `_strip_module_decl`）：
  ① **删除任一项 → 红**（hard）：`a`（迁移后）缺 `b`（迁移前）有的键 / 列表元素，一律硬差异；
  ② **任一值变化 → 红**（hard）：标量/结构值不等即硬差异。唯一例外是**派生展示键**
     （`control` / `widget` / `block_layout` / `number_step`）——它们由元数据 + 值形态推导，
     是**呈现层**结果（如批15 #9 把动态键空间由 objform 表格化为 kvtable、#2 把曲线纠偏为
     curve），改的只是呈现、不改迁移口径，故记 soft；**删除它们仍是 hard**（结构不能消失）；
  ③ **新增项 → 允许**（soft），但必须显式计入输出：打印「新增 N 项（功能演化）」并逐条列出
     （不得静默吞掉；列表逐 key 对齐后，既有元素被改/删仍被 ①/② 抓住）；
  ④ **迁移相关字段严格相等**：`label` / `help` / `group` 三个描述符键，以及模块声明
     （`module_labels` / `module_tree` → `modules.modules`、`index.modules[].label`、
     `entries/*.label`、`detail/*.module_label`）整体——这组做**逐字段严格断言**：
     **新增 / 删除 / 改值全红**，不受 ②/③ 的派生展示键与新增容忍影响。

用法（仓库根执行）：

    PYTHONPATH= .venv/bin/python scripts/compare_field_meta_migration.py
    PYTHONPATH= .venv/bin/python scripts/compare_field_meta_migration.py \
        --baseline-root /path/to/baseline
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(__file__).resolve().with_name("editor_readonly_snapshot.py")
DEFAULT_PACKS = ("veinborn", "test_demo")
# 批12（2026-09-15）重定基线：995e91b → 112584d。原因：db7bb35 起内容包合法新增
# traits/recipe/slots/dungeon/achievements/conditional 等模块，使 995e91b 基线在
# 「模块目录/索引/包列表 module_count」上产生与迁移无关的硬差异。重定到本批父提交，
# 使门禁继续只守「字段级元数据迁移不得改/删」。
# 批13.1（2026-09-15）重定基线：112584d → 46baff3。原因：段入口机制合法改变
# **条目列表口径**（对象型模块补入框架已登记的未配置段）→ settings/conditional 的
# 条目数、index.total 与 entries 列表长度随之变化，属与「字段级元数据迁移」无关的
# 展示层演进。
# 批14（2026-09-15）重定基线：46baff3 → f7d9c25（本批 #6 末提交）。原因：对象子字段
# 可编辑机制把 `obj` 控件由 `readonly` → `objform`，并使未登记映射按对象渲染；部位字段
# `slot` 由纯文本 → 展示层引用下拉（options_ref）。均为**展示层控件形态**演进（type /
# required / 枚举 / 引用目标等校验口径零变化），与「字段级元数据迁移不得改/删」无冲突；
# 重定到本批末提交后，门禁继续只守字段级改/删。
# 批19（2026-09-16）重定基线：f7d9c25 → 5e908bb（本批 F 段末提交）。原因：#4 把消息模板
# 条目列表由「包覆盖 2 条」扩为「包覆盖 ∪ 框架全量模板表键」（条目计数 / 索引 / 详情形态
# 变化）；#8 `entry_tree` 把 settings 的 env_event/time_cycle 条目改归 maps（条目列表 /
# 计数 / 索引口径变化）；#9 补 formula 中文名（label 由键名变中文）；#5 给条目列表/模块树
# 加 purpose/unused/overlap_hints 展示键；#6 模块名回落目录中文名。以上均为**展示层**
# 演进（type/required/枚举/引用目标等校验口径零变化），与「字段级元数据迁移不得改/删」
# 无冲突；重定到本批末提交后，门禁继续只守字段级改/删。
# 批20（2026-09-16）重定基线：5e908bb → a2fe3c5（本批 C 段末提交）。原因：
#   · A 段把「对象型字段里的映射」由 objform 改渲染为**键值表格**（control 由 objform → kvtable，
#     kv_table 新增 typed 行模式；control 属派生展示键，故记 soft），并新增 `element` 描述符；
#   · B 段 `entry_merge_filtered` 使装备页条目列表 = 自身 ∪ 并入（条目计数 / 索引口径变化，
#     已按 B 的计数契约三处自洽）；
#   · C 段给 7 个长模块声明**二级分组**（`subgroup` 由空串 → 命名子分组、`block` 由「主块 /
#     隐式更多字段」→ 命名子分组），并新增中栏分组展示键 `group` / `group_label`。
# 以上均为**展示层**演进（type / required / 枚举 / 引用目标 / 必填等校验口径零变化），与
# 「字段级元数据迁移不得改/删」无冲突；重定到本批末提交后，门禁继续只守字段级改/删。
# 批23（2026-09-16）重定基线：8aa9c9d → 7c90427（本批新增字段末提交）。原因：
#   本批一次性**新增**字段（skills `hp_cost`、jobs `advance`/`is_basic`）与 3 条
#   job_advance_* 模板键，使展示块 `keys`/`count`、条目计数、index.total 与
#   templates 计数增长。对拍实证：硬差异全部是 `blocks.*.keys`/`count`、
#   `fields[*].(block|subgroup)` 位移与 templates/index 计数，**无任何删除**
#   （「仅迁移前有（删除）」= 0）与 `label`/`help`/`group` 严格键改动；新增项
#   逐条列出（hp_cost / advance / is_basic / job_advance_*）。重定到本批末提交后，
#   门禁继续只守字段级改/删（后续批次再加字段会重新触发展示块位移并重定，
#   流程同批14/19/20/22）。
# 批24（2026-09-16）重定基线：7c90427 → 1068f93（本批新增字段末提交）。原因：
#   本批一次性**新增**字段（maps `hidden`/`entry_cost`、maps.monsters 行
#   `encounter_chance`/`encounter_count_min`/`encounter_count_max`、dungeon
#   `advance_on_kill_count`、quest `daily` 重置周期子字段）使展示块
#   `keys`/`count`、`fields[*].(block|subgroup)`、`daily.children` 与
#   `index.total` 增长。对拍实证：硬差异全部是展示块位移 + `daily.children`/
#   `open_keys` 形态变化，**无任何删除**（「仅迁移前有（删除）」= 0）与
#   `label`/`help`/`group` 严格键改动；新增项逐条列出（hidden / entry_cost /
#   encounter_* / advance_on_kill_count）。重定到本批末提交后，门禁继续只守
#   字段级改/删。
# 批25（2026-09-17）重定基线：1068f93 → d6304ac（本批新增字段末提交）。原因：
#   本批一次性**新增**字段（npc `interactions[].key/daily_limit/total_limit`、
#   `interactions[].cost` 扩 gem/diamond/items、achievements `counted`、settings
#   `register_gift`/`register_level`/`command_gates`/`rate_limit`/`message_chunk_len`）
#   使展示块 `keys`/`count`、`fields[*].(block|subgroup)`、`cost` 子块标签与
#   `index.total` 增长。对拍实证：硬差异全部是展示块位移 + 新字段标签，**无任何
#   删除**（「仅迁移前有（删除）」= 0）与既有 `help`/`group` 严格键改动；`cost`
#   由纯键名变中文段名属本批**有意**的展示层补充。重定到本批末提交后，门禁继续
#   只守字段级改/删（后续批次再加字段会重新触发展示块位移并重定，流程同批14/19/20/22/24）。
# 批26（2026-09-17）重定基线：d6304ac → f051348（本批装备侧字段末提交）。原因：α组新增
# items/equipment `grant_skills`/`max_hold`/`skill_amp`/`attack_override`/`job_override`，
# 使展示块 `base[@more]`/`effects[]` 的 `keys`/`count` 随新增字段增长（派生展示聚合），
# 属**新增引起的展示层位移**：对拍实证硬差异全部是这些派生块聚合 + 新字段描述符，
# **无任何删除**（「仅迁移前有（删除）」= 0）与既有 `label`/`help`/`group` 严格键改动。
# 重定到本批末提交后，门禁继续只守字段级改/删。
# 批28（2026-09-17）重定基线：357ca16 → 4b9d82d（本批 D-6 删除提交）。原因：**有意删除**
# 空壳键 `transfer_allowed`（框架子结构 + V5 校验 + 缺省锚点），内容包 `veinborn`
# 的展示名（field_meta.json）把该键回填为纯展示 soft 子字段，使 enhance.settings 的
# `keys` 顺序由 [.., transfer_allowed, max_by_rarity] 位移为 [.., max_by_rarity,
# transfer_allowed]。对拍实证硬差异**仅此两处顺序位移**（「仅迁移前有（删除）」= 0、
# 既有 label/help/group 严格键改动 = 0）；属本批**有意**的字段删除引起的展示层位移。
# 重定到本批 D-6 提交后，门禁继续只守字段级改/删。
# 批29（2026-09-17）重定基线：4b9d82d → 9777ed5（本批 ① 残留清理 + ② 条件集补齐
# + 条件说明的末提交）。
# 原因（均为本批**有意**变更，非迁移回归）：
#   ① ① 清理内容包残留：删 `content/veinborn/enhance.json` 数据键 +
#      `content/veinborn/field_meta.json` 展示名 → enhance.settings 少一个纯展示 soft
#      子字段，对拍出现 1 处「仅迁移前有（删除）」硬差异（门禁口径①：删除任一项 → 红）；
#   ② ② 条件集补齐：`skill_chains.steps[].condition` 新增 level/job/quest 三个主体
#      （subjects 新增项 = soft）+ `ConditionSubject.value_enum` 新描述符（各主体新增项
#      = soft）+ 条件字段新增 `help` 说明（口径④严格字段：新增 → 红）+ 条件 `ops`
#      集合由 4 → 7（数组长度变化 = 硬差异，命名/引用/枚举等**校验口径零变化**，
#      仅编辑器主体/比较符可选项与说明扩充）。
# 两处均属「本批有意的字段删除 + 展示层控件可选项/说明扩充」，重定到本批末提交后，
# 门禁继续只守「字段级元数据迁移不得改/删」。
# 批30（2026-09-16）重定基线：9777ed5 → 8e56cc3（本批 U8 商店字段定稿收敛提交）。
# 原因（本批**有意**变更，非迁移回归）：
#   U8 把商店条目字段元数据从 M4 期的旧口径收敛到定稿 `scope/limit/period`：
#   ① 新增 9 个条目字段（currency/scope/refresh/reputation_required/min_level/
#      discount/sold_out_once 等）= soft 新增（对拍「新增 202 项」全部来自 items 列的
#      新字段展开）；
#   ② 修正既有描述符：`period` obj→str（连带 `period.children`/`period.open_keys`
#      各 1 处「仅迁移前有（删除）」）、`price_fluctuation` obj→int（连带 children/
#      open_keys 删除）、`refresh.mode` 枚举 manual/fixed→once/none、`type` 枚举
#      general/black/quest→npc/blackmarket、`stock`/`limit`/`period` label 与 help
#      更新（口径④严格键：label/help 变动 = 红）。
#   对拍实证：全部 153 条硬差异**均在 shop 命名空间内**（非 shop 硬差异 = 0）；
#   10 处「仅迁移前有（删除）」全部是上述 obj→基础类型收敛时消失的 `children`/
#   `open_keys`/`interval` 派生描述符，无任何字段被无意删除。重定到本批末提交后，
#   门禁继续只守「字段级元数据迁移不得改/删」。
# 批33（2026-09-17）：本批未改 `field_meta.py`，但发现默认常量仍停在 8e56cc3——
# 批32 已按台账 §二十一 重定到 cad91df（`tests/unit/test_editor_pack_field_meta_migration.py`
# 亦用 cad91df），此处对齐默认值，使默认跑法与 pytest 门禁同基线；对拍 0 差异。
# 批36（2026-09-19 采集/挖掘引擎）：cad91df → c6d33c4（本批编辑器侧提交）。
# 原因（本批**有意**变更，非迁移回归）：
#   ① `maps.gather_points` 子字段按细化_2a1d GP-01~GP-11 补全——新增 periods/seasons/
#      respawn_minutes 三键（新增项 = soft）、rarity 由 str 收敛为 enum(normal/rare/gold)、
#      逐字段补 help（口径④严格键 label/help 变动 = 硬差异，故必须重定）；
#   ② 模板全量表新增 13 条 `gather_*` 键 → templates 模块计数 824 → 837（计数变动 = 硬差异）；
#   ③ 目录条目 `gathering` implemented False → True + purpose 更新。
#   对拍实证：重定前 80 条硬差异**全部**为上述三类（无任何字段/条目被无意删除，
#   删除项 = 0），加法项 76 条逐条列出。重定到本批末提交后，门禁继续只守
#   「字段级元数据迁移不得改/删」。
# 二次重定（同批）：c6d33c4 → 9cdaa04。原因：emoji 纪律门禁要求 field_meta 的
#   `gather_points[].rarity.help` 去掉 ✨（改为「上限觉醒档」）——help 属口径④严格键，
#   与 c6d33c4 基线不一致；重定到含该修正的本批测试/收尾提交后，对拍回到 0 差异。
# 批37（2026-09-19 战后恢复引擎）：9cdaa04 → d324e92（本批字段/模板/测试提交）。
# 原因（本批**有意**变更，非迁移回归）：
#   ① 新增框架 settings 段 `post_battle_recovery`（战后恢复三字段）→ settings 条目列表
#      多 1 条（count/total_count/unconfigured_count、index.total、模块声明计数各 +1，
#      纯新增）；
#   ② 模板全量表新增 `battle_settle_recovery` 键（templates 计数 837 → 838）；
#   对拍实证：删除项 = 0（无「仅迁移前有」）；36 条硬差异全部为上述两类的计数变动，
#   8 条新增项逐条列出。重定到本批末提交后，基线树与当前树逐字段 diff=0。
# 批38（2026-09-19 深度打造地基）：d324e92 → c7fe678（本批字段/引擎/测试提交）。
# 原因（本批**有意**变更，非迁移回归；删除项 = 0，全部为新增）：
#   ① 新增框架 settings 段 `equipment_offhand`（副手开关两字段）；
#   ② `slot_defs` 登记值结构子字段 `role`（部位角色 main/offhand；整体成表条目新增一列）；
#   ③ items/equipment 新增 `handedness`（手数）与 `affinities`（相性声明）两字段；
#   ④ 新增相性通用层 settings 四段（affinities/affinity_pools/affinity_linkage/
#      affinity_reactions）；
#   → settings 条目列表 +5 条（count/total_count/unconfigured_count、index.total、
#      模块声明计数各 +5）；items/equipment 条目字段各 +2。
#   对拍实证：删除项 = 0（无「仅迁移前有」）；硬差异全部为上述计数/新增列变动，
#   新增项逐条列出（test_gate_semantics_addition_is_green_and_listed 口径）。
#   重定到本批末提交后，基线树与当前树逐字段 diff=0。
# 批39（2026-09-19 合成公用层）：c7fe678 → 00b65f5（本批字段/编辑器/测试提交）。
# 原因（本批**有意**变更，非迁移回归；删除项 = 0，全部为新增）：
#   ① 新增框架 settings 段 `deep_craft`（打造路径开关：enabled 一字段）；
#   ② `recipe` 目录条目 purpose 补「第 1 层【合成】，打造与炼金公用」+ settings_section
#      指向 settings.alchemy.mode（模块级展示声明，非字段级迁移回归）；
#   → settings 条目列表 +1（count/total_count/unconfigured_count、index.total、
#      模块声明计数各 +1）。
#   对拍实证：删除项 = 0（无「仅迁移前有」）；硬差异全部为上述计数/purpose 变动，
#   新增项逐条列出（test_gate_semantics_addition_is_green_and_listed 口径）。
#   重定到本批字段提交后，基线树与当前树逐字段 diff=0。
# 批39 二次重定（同批）：00b65f5 → 0e1d7b4（settings.alchemy.mode 补中文名 + 说明卡）。
#   原因 = 本批**有意**变更（非迁移回归）：mode 字段级 label/help（口径④严格键）新增。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
# 批39 三次重定（同批）：0e1d7b4 → b812891（settings.alchemy 段补中文段名 + 说明卡）。
#   原因 = 本批**有意**变更（非迁移回归）：alchemy 段级 label/help（口径④严格键）新增。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
# 批41（2026-09-19 深度打造主流程）重定：b812891 → de0cb85。
#   原因 = 本批**有意**变更（非迁移回归）：items 新增材料打造字段 3 条 + 图纸字段 12 条；
#   settings.deep_craft 段补 5 个子字段；模板全量表 +16 条 deep_craft_* 键。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
# 批43（2026-09-20 强化六档与特殊词条）重定：de0cb85 → 0d2011e。
#   原因 = 本批**有意**变更（非迁移回归），含**一处有意删除**（H3 用户拍板「替换现在的」）：
#   ① 删除 enhance.settings.max_by_rarity（四档 5/8/10/12，字段元数据 + 同名节点）——
#      此行属门禁口径①「删除任一项 → 红」，为**有意替换**：改用 max_by_quality_level
#      （品质等级 6 档 → +3/+6/+9/+12/+15/+18）+ legacy_quality_level_by_rarity（旧档兼容
#      桥接：normal→2/fine→3/epic→4/legendary→4，旧装备上限**只升不降**、既有
#      enhance_level 原样保留）。**旧档兼容证据**：旧档无 quality_level → 桥接读上限，
#      旧上限 5/8/10/12 对应新上限 6/9/12/12（均 ≥ 旧值），且 resolve_cap = max(表值, 当前
#      等级) 绝不降级/清零（tests/unit/test_batch43_enhance_tiers.py 逐档断言 + 旧档实证）。
#   ② 新增 settings 行 special_affix_span（每 N 级特殊词条跨度）。
#   ③ data/gear_stats 新增 5 个词条键（回复强化/减益概率/增益概率/弱点伤害 + 冷却缩减占位）
#      → items/equipment 字段各 +5，`blocks.stats[@more]` 计数随之后移。
#   ④ 模板全量表 +2 条 enhance_affix_gain / enhance_info_affix_row（templates 计数 854→856）。
#   对拍实证：29 条差异**全部**为上述四类（1 处有意删除 + 26 项新增 + 派生展示计数位移）；
#   无任何 label/help/group 严格键的**无意**改动。
#   重定到本批末提交后，门禁继续只守「字段级元数据迁移不得改/删」。
# 批44（2026-09-20 投入概率暴击）重定：0d2011e → 1b76ab4（本批字段/模板/文档提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**：
#   ① settings.deep_craft.craft_rules 新增 quality_exp_crit 子对象 + 其 12 个子字段
#      （中文名/说明卡；既有 craft_rules 子字段与 enabled 原样保留）；
#   ② 模板全量表 +1 条 deep_craft_crit_gain（templates 计数 856→857）。
#   对拍实证：删除项 = 0、无 label/help/group 严格键的无意改动；重定后 0 差异。
# 批46（2026-09-20 符文地基）重定：1e2f68c → 0d55330（本批字段/模块登记提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   ① 新增 runes 模块（kind=rune；tier/family/by_equip_type/effects/bias 字段）——
#      veinborn 模块声明 +1、index/modules 计数位移；
#   ② settings 新增 rune_sockets 段（default_count）→ settings 条目 +1（两包 unconfigured +1）；
#   ③ veinborn.field_meta.json 新增 module_labels["runes"]="符文"（严格键**新增**）。
#   对拍实证：删除项 = 0；23 条差异全部为上述新增 + 派生展示计数位移（+4 soft 新增）；
#   重定后基线树与当前树逐字段 diff=0。
# 批50（2026-09-20 特效轴地基）重定：0d55330 → e70edd2（本批字段/模板/测试提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   ① settings 新增 `effect_axes` 声明段（min/max/default/display/stack/legacy_alias）→
#      settings 条目 +1（veinborn 49→50、test_demo 51→52，unconfigured 各 +1）；
#   ② items/equipment 词条新增 15 个特效轴键（中文名 + 双向说明 + 可负区间）→
#      stats 分组 `@more` 溢出展示计数位移（veinborn items 31→46 / equipment 26→41，
#      test_demo items 31→46）——**计数位移 = 硬差异**，故须重定基线（同批36 口径）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
# 批53（2026-09-20 时序与资源轴）重定：e70edd2 → b9df5c7（本批文档/说明提交）。
#   原因 = 本批**有意**变更（非迁移回归），仅 **1 处既有严格键 help 改值**（无删除/无新增）：
#   · items/equipment 的 `cooldown_reduction_pct` help：由「【占位】…明确不接任何引擎消费」
#     改为「批53 起作为 cooldown_pct 的兼容别名生效（30 ⇔ −30，只换算一次、不双计）」——
#     该键本批**真接线**，原文案已成为陷阱；label/range/group 均不变。
#   对拍实证：删除项 = 0；硬差异 6 条全部为同一 help（×2 模块 ×2 派生键 ×2 包）；
#   重定后基线树与当前树逐字段 diff=0。
# 批55（2026-09-20 特效强度预算）重定：b9df5c7 → f1e942e（本批字段/文档提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   · settings 新增 `effect_budget` 段（8 子字段）→ settings 条目 +1（两包 count/
#     unconfigured 各 +1，派生的 index/modules 计数位移）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
# 批56（2026-09-21 行动速度轴 + 过量治疗）重定：f1e942e → 138f0d2（本批文档/页脚提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   · items/equipment 词条新增 1 个特效轴键 `action_speed_pct` → stats `@more` 计数各 +1；
#   · settings 新增 `overheal` 段（1 子字段）→ settings 条目 +1（派生计数位移）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
# 批57（2026-09-21 淬炼与分解回收）重定：138f0d2 → 427047e（本批字段/引擎提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   · `enhance` 模块新增 `temper` 段（15 子字段）→ 该模块 own/count/total +1、
#     entries/enhance 计数 5→6（unconfigured 0→1，派生的 index/modules 计数位移）；
#   · `settings.forge` 新增 `essence_rate` 段（13 子字段）→ forge 字段表新增（纯新增）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
# 批59（2026-09-22 特效小尾巴）重定：427047e → ee15c78（本批字段/元数据提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（删除 0 / 无既有严格键改值）：
#   · items/equipment 新增特效轴键 `reward_mult_pct`（X43，`min:0`）→ stats `@more` 计数 +1；
#   · settings.`overheal` 新增 mode/cap_pct/cap_flat 三子字段。
# 批62（2026-09-22 深炼金口径 C + /淬炼 指令壳）重定：ee15c78 → d06dd0b（本批模板提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（删除 0 / 无既有严格键改值）：
#   · 模板全量表 +22 条 `temper_*` 键（`/淬炼` 指令壳文案；templates 857→879，
#     framework_default_count 855→877）→ entries/templates 与 index/modules 计数派生位移；
#   · 本批不新增 settings 字段/键（`quality_cap_delta` 是既有 `affinity_effects` 内层动态键）。
DEFAULT_BASELINE_REF = "d06dd0b"


def _env(root: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.pop("PYTHONSAFEPATH", None)
    return env


def _snapshot(root: Path, packs: List[str]) -> Any:
    proc = subprocess.run(
        [sys.executable, str(SNAPSHOT), *packs],
        cwd=str(root), env=_env(root), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"快照执行失败（{root}）：\n{proc.stderr}")
    return json.loads(proc.stdout)


class _Baseline:
    def __init__(self, root: Optional[Path], ref: str) -> None:
        self._tmp: Optional[Path] = None
        if root is not None:
            self.root = root
        else:
            import importlib.util
            import tempfile
            spec = importlib.util.spec_from_file_location(
                "migrate_pack_field_meta", SNAPSHOT.with_name("migrate_pack_field_meta.py"))
            mig = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mig)  # type: ignore[union-attr]
            self._mig = mig
            self._tmp = Path(tempfile.mkdtemp(prefix="packmeta-cmp-"))
            wt = self._tmp / "repo"
            subprocess.run(["git", "worktree", "add", "--detach", str(wt), ref],
                           cwd=str(REPO_ROOT), check=True, capture_output=True, text=True)
            self.root = wt

    def close(self) -> None:
        if self._tmp is not None:
            subprocess.run(["git", "worktree", "remove", "--force", str(self.root)],
                           cwd=str(REPO_ROOT), capture_output=True, text=True)
            try:
                self._tmp.rmdir()
            except OSError:
                pass


def _list_key(items: Any) -> Optional[dict]:
    """list-of-dict 的**逐键对齐**索引（元素带唯一 key/id/name 时返回 {键: 元素}）。

    用于把「新增字段」与「既有字段被改/被删」区分开：批B 门禁必须抓住后者，而后续
    批次合法新增的字段只应算「新增」、不算差异（见本文件顶注「增量容忍」）。
    非 list、或元素缺统一唯一键、或键重复 → None（回退到定长下标对拍）。
    """
    if not isinstance(items, list) or not items:
        return None
    for id_key in ("key", "id", "name"):
        if all(isinstance(x, dict) and id_key in x for x in items):
            keys = [str(x[id_key]) for x in items]
            if len(set(keys)) == len(keys):
                return {str(x[id_key]): x for x in items}
    return None


#: 模块详情里的**派生计数**键：其值由 fields/groups 列表推导，列表已逐键对齐，
#: 计数本身只随合法新增而变 → 不计差异（避免「加一个字段」被计成 3 条差异）。
_DERIVED_COUNT_KEYS = frozenset({"field_count", "group_count", "association_count"})
#: 分组描述符键集（同集合的 dict 视作 group 描述符，其 count 为派生值，跳过）。
_GROUP_KEYS = frozenset({"name", "label", "count"})


def _strip_module_decl(snap: Any) -> Any:
    """取出**模块级展示声明**（模块树 / 模块显示名），单独成子树的严格对拍口径。

    批12 起：模块显示名与模块层级属**包展示声明**，会随批次刻意重组（「属性/公式条目并入
    基础」「生活模块挂到既有父模块下」）。迁移门禁的硬约束包含「**字段级** key/label/help/
    group/type 不得被改/删」与「`module_labels` / `module_tree` 严格相等」，故把下列内容
    从主对拍里**摘出**（避免与字段描述混在一条路径上），改为独立子树按 `strict=True` 对拍
    ——新增 / 删除 / 改值全红：
      · `modules.modules`（模块树结构，源自 `module_tree`）；
      · `index.modules[].label`（模块索引里的中文名，源自 `module_labels`）；
      · `entries/<模块>.label` 与 `detail/<模块>.module_label`（模块显示名）。
    其余（字段描述、计数、条目集合、引用候选）一律仍按 ①②③ 口径对拍。
    """
    decl: dict = {}
    hard = copy.deepcopy(snap)
    if not isinstance(hard, dict):
        return hard, decl
    mods = hard.get("modules")
    if isinstance(mods, dict) and "modules" in mods:
        decl["modules"] = mods.pop("modules")
        decl["modules.notes"] = mods.pop("notes", None)   # 批13：聚合视图声明 note（模块级）
    idx = hard.get("index")
    if isinstance(idx, dict) and isinstance(idx.get("modules"), list):
        decl["index.labels"] = [m.pop("label", None) for m in idx["modules"]
                                if isinstance(m, dict)]
        # 批13：模块 namespace 属**模块级注册**（templates 由未登记 → 登记为 template_lib），
        # 非字段级迁移差异 → 记 soft。
        decl["index.namespaces"] = [m.pop("namespace", None) for m in idx["modules"]
                                    if isinstance(m, dict)]
    for key in list(hard):
        if key.startswith("entries/"):
            body = hard[key]
            if isinstance(body, dict):
                decl[f"{key}.label"] = body.pop("label", None)
        elif key.startswith("detail/"):
            body = hard[key]
            if isinstance(body, dict):
                decl[f"{key}.module_label"] = body.pop("module_label", None)
    return hard, decl


def _is_fallback_field(d: Any) -> bool:
    """字段描述符是否来自「元数据未登记 → 按实际值兜底」的旧形态（批13 容忍用）。

    批13 把这些**软展示字段**补成正式登记（type/widget/control/help_card 由兜底推断
    变成显式登记）——这是展示层补登记，不是迁移改键；对拍里计入 soft。
    """
    if not isinstance(d, dict):
        return False
    card = d.get("help_card")
    if isinstance(card, dict):
        if card.get("unregistered") is True:
            return True
        src = str(card.get("type_source") or "")
        if "未登记" in src or "实际值" in src:
            return True
        if card.get("type") == "未标注" and card.get("range") == "未标注":
            return True
    # 兜底标量字段（map 值不是对象）：key 为空但带 widget/control。
    return d.get("key") == "" and ("widget" in d or "control" in d)


#: 由列描述 / 元数据**派生**的展示键：其值只随呈现层演化而变（列已逐键对齐）→ 记 soft。
#: 批15 增补 `control` / `widget`：它们是「元数据类型 × 值形态 → 控件形态」的推导结果
#: （`_EDIT_BY_WIDGET` / `_effective_widget`），#9 表格化、#2 曲线化改的正是这两个值，
#: 属呈现层演进；但**删除它们仍算硬差异**（结构不能消失）。
_DERIVED_DISPLAY_KEYS = frozenset({"control", "widget", "block_layout", "number_step"})
#: 迁移相关字段：这批键做**逐字段严格断言**（新增 / 删除 / 改值全红，且沿子树传播）。
_STRICT_KEYS = frozenset({"label", "help", "group"})


def _diff(a: Any, b: Any, path: str, hard: List[str], soft: List[str],
          cap: int = 200, strict: bool = False) -> None:
    """递归对拍：hard = 删除 / 值变化（必须为 0）；soft = 合法新增 / 派生展示键（允许，仅报告）。

    口径（批15 语义化定稿，2026-09-15）：
      ① 删除任一项 → hard（不因 strict 与否而放松）；
      ② 值变化 → hard；例外：`_DERIVED_DISPLAY_KEYS` 的值变化记 soft（仅呈现层），
         但**缺失**（删除）仍为 hard；
      ③ 新增项 → soft（逐条列出，不得静默）；
      ④ `strict=True`（或跨入 `_STRICT_KEYS` 子树）→ 新增 / 删除 / 改值全 red，
         不受 ②/③ 容忍影响（用于 `label` / `help` / `group` 与模块声明子树）。
    列表元素带唯一 key/id/name 时逐键对齐，因此「既有元素被改」仍会被 hard 抓住，
    不会因长度变化被整体跳过。
    """
    if len(hard) >= cap:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        # 批13：基线（b）是兜底软字段、当前（a）补成正式登记 → 描述符差异记 soft。
        if _is_fallback_field(b) and not _is_fallback_field(a):
            soft.append(f"{path}: 兜底软字段 → 正式登记（批13 展示层补登记）")
            return
        keys = set(a) | set(b)
        if keys and keys <= _GROUP_KEYS:
            keys = keys - {"count"}
        for key in sorted(keys):
            if key in _DERIVED_COUNT_KEYS:
                continue
            key_strict = strict or key in _STRICT_KEYS
            if (not key_strict and key in _DERIVED_DISPLAY_KEYS
                    and key in a and key in b and a.get(key) != b.get(key)):
                soft.append(f"{path}.{key}: {b.get(key)!r} → {a.get(key)!r}（派生展示键）")
                continue
            if key not in a:
                hard.append(f"{path}.{key}: 仅迁移前有（删除）")
            elif key not in b:
                if key_strict:
                    hard.append(f"{path}.{key}: 仅迁移后有（迁移相关字段，严格断言）")
                else:
                    soft.append(f"{path}.{key}: 仅迁移后有（新增）")
            else:
                _diff(a[key], b[key], f"{path}.{key}", hard, soft, cap, key_strict)
        return
    if isinstance(a, list) and isinstance(b, list):
        ka, kb = _list_key(a), _list_key(b)
        if ka is not None and kb is not None:
            for key in sorted(set(ka) | set(kb)):
                if key not in ka:
                    # 批13：基线兜底空键字段被正式登记替代（模板等 map 模块）→ soft。
                    if _is_fallback_field(kb[key]):
                        soft.append(f"{path}[{key}]: 兜底软字段被正式登记替代（批13）")
                    else:
                        hard.append(f"{path}[{key}]: 仅迁移前有（删除）")
                elif key not in kb:
                    if strict:
                        hard.append(f"{path}[{key}]: 仅迁移后有（迁移相关字段，严格断言）")
                    else:
                        soft.append(f"{path}[{key}]: 仅迁移后有（新增）")
                else:
                    _diff(ka[key], kb[key], f"{path}[{key}]", hard, soft, cap, strict)
            return
        if len(a) != len(b):
            hard.append(f"{path}: 数组长度 {len(b)} → {len(a)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", hard, soft, cap, strict)
        return
    if a != b:
        hard.append(f"{path}: {b!r} → {a!r}")


def compare_snapshots(before: Mapping[str, Any], after: Mapping[str, Any],
                      packs: Sequence[str], cap: int = 200) -> Tuple[List[str], List[str]]:
    """对两份快照跑口径 ①~④，返回 `(hard, soft)`（纯函数，供自证测试直接调）。

    · hard = 删除 / 值变化 / 迁移相关字段的严格变动 → 必须为空才算通过；
    · soft = 新增项 / 派生展示键的值变化（逐条列出，不得静默）。
    模块声明子树（module_labels / module_tree）以 `strict=True` 对拍（口径 ④）。
    """
    hard: List[str] = []
    soft: List[str] = []
    for pack in packs:
        after_hard, after_decl = _strip_module_decl(after.get(pack))
        before_hard, before_decl = _strip_module_decl(before.get(pack))
        _diff(after_hard, before_hard, pack, hard, soft, cap)
        _diff(after_decl, before_decl, f"{pack}·模块声明", hard, soft, cap, strict=True)
    return hard, soft


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="批B 迁移前后只读接口对拍")
    parser.add_argument("--pack", action="append", dest="packs")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--baseline-root", default=None)
    parser.add_argument("--max-diffs", type=int, default=200)
    args = parser.parse_args(argv)
    packs = args.packs or list(DEFAULT_PACKS)

    baseline = _Baseline(Path(args.baseline_root) if args.baseline_root else None,
                         args.baseline_ref)
    try:
        before = _snapshot(baseline.root, packs)
        after = _snapshot(REPO_ROOT, packs)
    finally:
        baseline.close()

    diffs, added = compare_snapshots(before, after, packs, args.max_diffs)

    print("批B 等价性对拍（迁移前 ↔ 迁移后）")
    print(f"  基线：{args.baseline_root or args.baseline_ref} · 包：{', '.join(packs)}")
    print(f"  差异条数：{len(diffs)}（删除/修改 = 硬差异，必须 0）")
    print(f"  新增 {len(added)} 项（功能演化，允许，逐条列出）")
    for line in added[:args.max_diffs]:
        print("   +", line)
    for line in diffs:
        print("   -", line)
    if diffs:
        print("对拍失败：存在删除/修改差异（或迁移相关字段 label/help/group/"
              "module_labels/module_tree 的严格变动）")
        return 1
    print("对拍通过：删除/修改 = 0；迁移相关字段（label / help / group / "
          "module_labels / module_tree）逐字段严格相等；新增项已逐条列出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
