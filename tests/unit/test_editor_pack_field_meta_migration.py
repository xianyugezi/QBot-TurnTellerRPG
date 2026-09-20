"""编辑器重写批B · 迁移等价性门禁（veinborn/test_demo 迁移前 ↔ 迁移后 diff=0）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C。

本用例**调用** `scripts/compare_field_meta_migration.py`：它用 `git worktree` 检出基线
（批30 重定到本批 U8 商店字段收敛提交 8e56cc3；批29 曾重定清理内容包 `transfer_allowed` 残留
与条件集补齐；批28 已把空壳键 `transfer_allowed` 从框架侧删除。批30 把商店条目字段元数据由
M4 旧口径收敛到定稿 `scope/limit/period`：新增 currency/scope/refresh/… 9 字段（soft）、
`period` obj→str、`price_fluctuation` obj→int、`refresh.mode` manual/fixed→once/none、
`type` general/black/quest→npc/blackmarket、label/help 更新——均为**本批有意**的字段收敛；
对拍实证硬差异全部在 shop 命名空间内、非 shop 硬差异 = 0。重定到本批末提交后，基线树与当前树
**逐字段 diff=0**，**删除项 = 0、无既有 label/help/group 严格键改动**），在基线树与当前树各跑一遍
`scripts/editor_readonly_snapshot.py`（模块树 / 条目列表 / 条目详情 / 条目索引 / 引用候选 /
包列表），递归对拍并输出差异报告。

批15 语义化定稿（对拍口径，实现见 `compare_snapshots` / `_diff`）：
  ① **删除任一项 → 红**（hard）；② **任一值变化 → 红**（hard），唯一例外是派生展示键
  `control` / `widget` / `block_layout` / `number_step`（呈现层推导，删除它们仍红）；
  ③ **新增项 → 允许**（soft），但必须显式打印「新增 N 项（功能演化）」且逐条列出；
  ④ **迁移相关字段严格相等**：`label` / `help` / `group` 与模块声明（`module_labels` /
  `module_tree` → `modules.modules`、`index.modules[].label`、`entries/*.label`、
  `detail/*.module_label`）逐字段严格断言，**新增 / 删除 / 改值全红**。

`test_gate_semantics_*` 是**自证测试**：人为造删除 / 值变化 → 必须红；造新增 → 必须绿。
无 git / 无基线 ref 的环境自动跳过集成对拍（`compare_snapshots` 自证测试不依赖 git）。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "compare_field_meta_migration.py"
# 批32 重定基线：8e56cc3 → cad91df（本批四项末提交）。原因（对拍实证，非 shop 命名空间）：
#   · 新增框架 settings 字段 `pack_protection`（数据包保护开关）→ settings 条目 list 多 1 条
#     （count/total_count/unconfigured_count、index.total、模块声明计数各 +1，纯新增）；
#   · 4 处既有 **字符串引用字段**补 `ref_target` 展示层标注（maps.monsters[].enemy=enemy；
#     shop.items[].item / dungeon.drops.*[].item / maps.gather_points[].item=item）→ 对应
#     `ref_target` 与派生 `hint`/`help_card.*` 由空变「引用：X」（新增面，无删除）。
#   · 删除项 = 0（输出无「仅迁移前有」）；label/help/group/module_labels/module_tree 严格键零改动。
#   重定后基线树与当前树逐字段 diff=0（同批13.1/批23/批30 先例）。
# 批36（2026-09-19 采集/挖掘引擎）重定：cad91df → c6d33c4（本批编辑器侧提交）。
#   原因 = 本批**有意**变更（非迁移回归）：maps.gather_points 按细化_2a1d GP-01~GP-11 补全
#   三键（periods/seasons/respawn_minutes）+ rarity str→enum + 逐字段 help（严格键变动）；
#   模板全量表 +13 条 gather_* 键（templates 计数 824→837）；gathering implemented→True。
#   对拍实证：删除项 = 0、硬差异 80 条全部属上述三类；重定后 0 差异。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
#   二次重定（同批）c6d33c4 → 9cdaa04：rarity.help 去 ✨（emoji 纪律门禁要求；
#   help 属口径④严格键）→ 重定到含该修正的收尾提交，对拍回到 0 差异。
# 批37（2026-09-19 战后恢复引擎）重定：9cdaa04 → d324e92（本批字段/模板/测试提交）。
#   原因 = 本批**有意**变更（非迁移回归）：新增 settings.post_battle_recovery 段
#   （settings 条目 +1）+ 模板表 battle_settle_recovery（templates 计数 837→838）。
#   对拍实证：删除项 = 0、36 条硬差异全部为上述两类计数变动；重定后 0 差异。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批38（2026-09-19 深度打造地基）重定：d324e92 → c7fe678（本批字段/引擎/测试提交）。
#   原因 = 本批**有意**变更（非迁移回归）：新增 settings.equipment_offhand + 相性四段
#   （settings 条目 +5）、slot_defs 值结构子字段 role（整体成表新增一列）、
#   items/equipment 新增 handedness/affinities 两字段。
#   对拍实证：删除项 = 0、硬差异全部为上述计数/新增列变动；重定后 0 差异。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批39（2026-09-19 合成公用层）重定：c7fe678 → 00b65f5（本批字段/编辑器提交）。
#   原因 = 本批**有意**变更（非迁移回归）：新增 settings.deep_craft（打造路径开关，条目 +1）
#   + recipe 目录条目 purpose / settings_section 更新（模块级展示声明）。
#   对拍实证：删除项 = 0、硬差异全部为上述计数/purpose 变动；重定后 0 差异。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批39 二次重定（同批）：00b65f5 → 0e1d7b4（settings.alchemy.mode 补中文名 + 说明卡；
#   mode 字段级 label/help 属口径④严格键，新增 → 重定后 0 差异）。
# 批39 三次重定（同批）：0e1d7b4 → b812891（alchemy 段级 label/help 新增，口径④严格键）。
# 批41（2026-09-19 深度打造主流程）重定：b812891 → de0cb85（本批 A/B 字段与模板提交）。
#   原因 = 本批**有意**变更（非迁移回归）：
#     · items 新增材料打造字段 material_level / material_quality / craft_cost
#       （stats 分组 23→26）+ 图纸字段 blueprint_* 12 条（effects 分组 6→8，模板槽位）；
#     · settings.deep_craft 段补 craft_rules / quality_colors / quality_exp_by_color /
#       blueprint_grades / quality_draw_table 五个子字段（既有 enabled 原样保留）；
#     · 模板全量表 +16 条 deep_craft_* 键（templates 计数 838→854，framework 836→852）。
#   对拍实证：删除项 = 0，硬差异全部为上述计数/新增列变动；重定后 0 差异。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批43（2026-09-20 强化六档与特殊词条）重定：de0cb85 → 0d2011e。
#   原因 = 本批**有意**变更（非迁移回归），含**一处有意删除**（H3「替换现在的」）：
#     · 删 enhance.settings.max_by_rarity（四档 5/8/10/12）→ 换 max_by_quality_level
#       （品质等级 6 档 +3/+6/+9/+12/+15/+18）+ legacy_quality_level_by_rarity（旧档桥接，
#       旧装备上限只升不降、既有 enhance_level 原样保留）→ settings 行 5→7；
#     · data/gear_stats 新增 5 词条键（含冷却缩减占位）→ items/equipment 字段各 +5；
#     · 模板全量表 +2 条 enhance_affix_gain / enhance_info_affix_row（854→856）。
#   对拍实证：29 条差异全部为上述四类（1 处有意删除 + 新增/派生计数位移），
#   无 label/help/group 严格键的无意改动；重定后基线树与当前树逐字段 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批44（2026-09-20 投入概率暴击）重定：0d2011e → 1b76ab4（本批字段/模板提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无严格键改值）：
#     · settings.deep_craft.craft_rules 新增 quality_exp_crit 子对象（12 子字段：
#       enabled/grades/chance_by_grade/chance_default/mult_by_grade/mult_default/
#       additive_exp/applies_to/affects_quality_level/rolls_per_craft/exp_cap/rng_stream）；
#     · 模板全量表 +1 条 deep_craft_crit_gain（templates 计数 856→857）。
#   对拍实证：删除项 = 0、无 label/help/group 无意改动；重定后基线树与当前树 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批45（2026-09-20 装备占比校准）重定：1b76ab4 → 1e2f68c（本批字段/引擎提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无严格键改值）：
#     · settings 新增 panel_budget（白值/装备/buff 份 + 装备面板倍率，5 子字段）
#       + monster_scaling（hp/atk 倍率 + 防御补偿 + def_k，4 子字段）→ settings 条目 +2；
#     · 编辑器 settings 页字段数 +2（unconfigured_count 45→47，见 test_editor_batch131_segments）。
#   对拍实证：删除项 = 0、无既有 label/help/group 改动；重定后基线树与当前树 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批46（2026-09-20 符文地基）重定：1e2f68c → 0d55330（本批字段/模块登记提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#     · 新增 runes 模块（kind=rune；条目字段 tier/family/by_equip_type/effects/bias 等）
#       → veinborn 模块声明 +1、index/modules 计数位移；
#     · settings 新增 rune_sockets 段（default_count 1 子字段）→ settings 条目 +1
#       （unconfigured_count 47→48，见 test_editor_batch131_segments）；
#     · veinborn.field_meta.json 新增 module_labels["runes"]="符文"（严格键**新增**，非改值）。
#   对拍实证（对旧基线 1e2f68c）：删除项 = 0；23 条差异全部为上述新增 + 派生展示计数位移
#   （+4 soft 新增：runes 条目 + rune_sockets 段 ×2 包）；重定后基线树与当前树 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
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
#   原因 = 本批**有意**变更，仅 1 处既有严格键 help 改值：items/equipment 的
#   `cooldown_reduction_pct` help 由「【占位】…不接引擎」改为「兼容别名已生效」；
#   删除项 = 0、无新增；重定后基线树与当前树逐字段 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批55（2026-09-20 特效强度预算）重定：b9df5c7 → f1e942e（本批字段/文档提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   · settings 新增 `effect_budget` 段（enabled/aggregate/cap_equiv_pct/tier_mult/
#     gate_mode/unknown_axis/report_effective_share/axis_weights）→ settings 条目 +1
#     （两包 count/unconfigured 各 +1，见 test_editor_batch131_segments 49→50）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批56（2026-09-21 行动速度轴 + 过量治疗）重定：f1e942e → 138f0d2（本批文档/页脚提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   · items/equipment 词条新增 1 个特效轴键 `action_speed_pct`（中文名 + 双向说明 +
#     可负区间）→ items/equipment 的 stats `@more` 溢出展示计数各 +1
#     （veinborn items 46→47 / equipment 41→42；test_demo items 46→47）；
#   · settings 新增 `overheal` 段（enabled 1 子字段）→ settings 条目 +1
#     （两包 count/unconfigured 各 +1，见 test_editor_batch131_segments 50→51）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批57（2026-09-21 淬炼与分解回收）重定：138f0d2 → 427047e（本批字段/引擎提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（无删除/无既有严格键改值）：
#   · `enhance` 模块新增 `temper` 段（15 子字段）→ 该模块 own/count/total +1、
#     entries/enhance 计数 5→6（unconfigured 0→1，派生 index/modules 计数位移）；
#   · `settings.forge` 新增 `essence_rate` 段（13 子字段）→ forge 字段表纯新增。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
# 批59（2026-09-22 特效小尾巴）重定：427047e → ee15c78（本批字段/元数据提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（删除 0 / 无既有严格键改值）：
#   · items/equipment 词条新增 1 个特效轴键 `reward_mult_pct`（X43，中文名 + 双向说明 +
#     `min:0` 区间）→ items/equipment 的 stats `@more` 溢出展示计数各 +1
#     （veinborn items 47→48 / equipment 42→43；test_demo items 47→48）；
#   · settings 的既有 `overheal` 段新增 `mode`/`cap_pct`/`cap_flat` 三子字段（纯新增，
#     不改既有 `enabled` 的 label/help/range）。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
# 批62（2026-09-22 深炼金口径 C + /淬炼 指令壳）重定：ee15c78 → d06dd0b（本批模板提交）。
#   原因 = 本批**有意**变更（非迁移回归），全部为**新增**（删除 0 / 无既有严格键改值）：
#   · 模板全量表 +22 条 `temper_*` 键（`/淬炼` 指令壳文案；templates 计数 857→879，
#     framework_default_count 855→877）→ veinborn/test_demo 的 entries/templates 与
#     index.modules 计数派生位移（**计数位移 = 硬差异**，故须重定基线，同批36 口径）。
#   · 本批不新增 settings 字段/键（`quality_cap_delta` 是既有 `affinity_effects` 的**内层动态
#     键**，field_meta children 留空）→ settings 条目计数不变。
#   对拍实证：删除项 = 0；无既有 label/help/group/module_labels/module_tree 改值；
#   重定后基线树与当前树逐字段 diff=0。
#   与 scripts/compare_field_meta_migration.py 的 DEFAULT_BASELINE_REF 同基线。
# 批66（2026-09-23 新用户卡点修复）重定：d06dd0b → e757f59（本批字段说明收尾提交）。
#   原因 = 本批**有意**变更（非迁移回归），删除项 = 0，全部为**新增/改值且仅在 `help`**：
#   · 卡点4「Tip 补齐 + ≤60 字（忌长文）」：特效轴/词条说明缩短、去 Markdown `**` 与
#     `settings.*` 英文键引用（严格键 help 改值）；F_NAME/F_TYPE/F_PRICE/F_ATK/F_DEF/
#     F_EFFECTS 与 items 常用字段（slot/bind/usable/desc/quality/elements/traits/…）补
#     一句话 help（严格键 help 新增）；基础词条 help 接入 GEAR_HELP_ZH；
#   · 无 label/group/module_labels/module_tree 变动；无字段/键删除。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
# 批68（2026-09-23 新手上路打磨）重定：e757f59 → 526957f（本批字段说明收尾提交）。
#   原因 = 本批**有意**变更（非迁移回归），删除项 = 0，全部为**新增/改值且仅在 `label`/`help`**：
#   · §4「Tip 纪律」收尾：列表元素列「值」/嵌套对象子字段补一句话 help（effects/job_restrict/
#     traits/grant_skills/skill_amp/attack_override/job_override/elements 八元素/
#     blueprint_material_slots/blueprint_fixed_stats/blueprint_level_band/
#     blueprint_random_stat_count/blueprint_random_set_affix_count/blueprint_learn），
#     material_tier/source 补说明——对拍 `.help`/`.help_card.help` 新增 196 条（98 处）；
#   · §4「字段中文名」：F_NAME/F_TYPE/F_PRICE/F_ATK/F_DEF/F_EFFECTS 与 items/equipment
#     常用字段补 label；对拍 `label` 改值 4 条（conditional.name 'name' → '名称'）；
#   · 无 help 删除、无字段/键删除、无 group/module_labels/module_tree 变动；
#     `source` 未补 label（保留「框架登记类型但无中文名 → 原始键兜底」用例实例）。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
# 批70（2026-09-23 「登记了却不生效」清账 · 33 条）重定：526957f → 01bea48（本批 R4 说明提交）。
#   原因 = 本批**有意**变更（非迁移回归），删除项 = 0，全部为**改值且仅在 `help`**：
#   · R4 `reward_mult_pct` 轴 `display.help` 追加「当前未实现，配置不生效。」（≤60 字、无
#     Markdown/英文配置键，守批67 卡点4 护栏）；流入 equipment/items 字段描述符的
#     `.help` / `.help_card.help` 共 6 处改值；
#   · R10–R22 formula / R23 report_effective_share / R24–R25 settings.env_event|log_card /
#     R26–R33 ai|hidden 视图补「【未实现】」help——不在本对拍快照面内（diff=0）；
#   · R9 copy_slot：内容包 field_meta.json `field_help...alchemy.farming` 转嵌套并补说明（soft）；
#   · 无 label/group/module_labels/module_tree 变动；无字段/键删除（forge.decompose_rate 删除
#     不在本快照面内）。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
# 批71（2026-09-23 包专属残留清理）重定：01bea48 → 07293ee（本批页脚/CHANGELOG 提交）。
#   原因 = 本批**有意**变更（非迁移回归），删除项 = 0（输出无「仅迁移前有」），25 条硬差异
#   全部为**纯新增 + 派生计数位移**：
#   · 模板全量表 +6 键（battle_lock_no_monster/already_in_battle/has_other_session/
#     no_map/weak_block + explore_rest_reason_not_safe）→ templates 计数 879→885、
#     veinborn covered_count 2→4、index.total / 模块声明 count 位移；
#   · `statuses` 模块登记 `stance` 字段（批71 · A1）+ veinborn 6 条状态声明 `"stance":"air"`
#     → `detail/statuses.fields[stance]` 新增、`statuses.blocks.默认[]` 新增；
#   · `marks` 模块登记 `role` 字段（批71 · E1）+ veinborn `sword_flow` 声明
#     `"role":"combo_counter"` → `detail/marks.fields[role]` 新增、`blocks.默认[@more]` 4→5。
#   无 label/help/group/module_labels/module_tree 严格键删除；无字段/键删除。
#   对拍实证：删除项 = 0；重定后基线树与当前树逐字段 diff=0。
BASELINE_REF = "07293ee"
CONTENT = REPO / "content"


def _load_gate() -> Any:
    """按路径加载门禁脚本（scripts/ 不是包，不能 import）。"""
    spec = importlib.util.spec_from_file_location("compare_field_meta_migration", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _descriptor(**over: Any) -> Dict[str, Any]:
    """一个最小字段描述符（对拍用的合成样本；不写死任何真实模块/字段名）。"""
    d: Dict[str, Any] = {"key": "f", "label": "字段", "help": "说明", "group": "默认",
                         "control": "objform", "widget": "obj", "type": "obj"}
    d.update(over)
    return d


def _snap(fields: List[Dict[str, Any]], **module_over: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"fields": fields, "module_label": "模块"}
    body.update(module_over)
    return {"p": {"detail/m": body}}


def _run(before: Dict[str, Any], after: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    return _load_gate().compare_snapshots(before, after, ["p"], cap=1000)


# ---------------------------------------------------------------------------
# 自证：删除 / 值变化 → 红；新增 → 绿（且必须列出）
# ---------------------------------------------------------------------------
def test_gate_semantics_deletion_is_red() -> None:
    before = _snap([_descriptor(), _descriptor(key="g", label="另一个")])
    after = _snap([_descriptor(key="g", label="另一个")])
    hard, soft = _run(before, after)
    assert hard, "删除字段必须判红"
    assert any("仅迁移前有（删除）" in h for h in hard)


def test_gate_semantics_value_change_is_red() -> None:
    before = _snap([_descriptor()])
    after = _snap([_descriptor(label="改了")])
    hard, _ = _run(before, after)
    assert hard, "既有值变化必须判红"
    assert any(".label:" in h for h in hard)


def test_gate_semantics_addition_is_green_and_listed() -> None:
    before = _snap([_descriptor()])
    after = _snap([_descriptor(), _descriptor(key="g", label="新字段")])
    hard, soft = _run(before, after)
    assert not hard, "新增字段必须判绿"
    assert any("仅迁移后有（新增）" in s for s in soft), "新增必须逐条列出（不得静默）"


def test_gate_semantics_strict_label_addition_is_red() -> None:
    """口径 ④：迁移相关字段 `label` 在基线缺失、当前补上 → 也算红（严格断言）。"""
    before = _snap([{k: v for k, v in _descriptor().items() if k != "label"}])
    after = _snap([_descriptor()])
    hard, _ = _run(before, after)
    assert hard and any(".label:" in h and "严格断言" in h for h in hard)


def test_gate_semantics_strict_module_decl_change_is_red() -> None:
    """口径 ④：模块声明（module_labels / module_tree → modules.modules）严格相等。"""
    before = {"p": {"modules": {"modules": [{"module": "a", "label": "甲"}]}}}
    after = {"p": {"modules": {"modules": [{"module": "a", "label": "乙"}]}}}
    hard, _ = _run(before, after)
    assert hard, "模块显示名变化必须判红"


def test_gate_semantics_derived_control_change_is_green_but_deletion_is_red() -> None:
    """派生展示键（control）值变化记 soft（呈现层）；**删除**它仍判红。"""
    before = _snap([_descriptor()])
    changed = _snap([_descriptor(control="kvtable")])
    hard, soft = _run(before, changed)
    assert not hard, "control 值变化属呈现层，应记 soft"
    assert any("派生展示键" in s for s in soft)
    dropped = _snap([{k: v for k, v in _descriptor().items() if k != "control"}])
    hard2, _ = _run(before, dropped)
    assert hard2 and any(".control:" in h and "删除" in h for h in hard2)



def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def _have_baseline() -> bool:
    if not (REPO / ".git").exists():
        return False
    if _git("rev-parse", "--git-dir").returncode != 0:
        return False
    return _git("rev-parse", "--verify", f"{BASELINE_REF}^{{commit}}").returncode == 0


def _pack_dirs(root: Path) -> set:
    """内容根下含 manifest.json 的包目录名（动态发现，不写死任何包名）。"""
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir()
            if d.is_dir() and (d / "manifest.json").is_file()}


def _sync_new_packs_to(baseline_root: Path) -> None:
    """把当前 content/ 里基线没有的包原样补进基线树。

    批D 起 content/ 会新增探针包；`list_packs`（全包名册）因此合法地多一项，而本门禁是
    **逐包**等价性。补进基线后两侧名册一致，`veinborn`/`test_demo` 的逐字段仍须 0 差异
    （口径不放松）。不写死新包名——按「当前有、基线没有」动态发现。
    """
    base_content = baseline_root / "content"
    for name in sorted(_pack_dirs(CONTENT) - _pack_dirs(base_content)):
        shutil.copytree(CONTENT / name, base_content / name)


def test_field_meta_migration_is_behaviour_preserving() -> None:
    """对拍迁移前后编辑器只读接口：逐字段 diff 必须为 0。"""
    if not _have_baseline():
        pytest.skip(
            "无 git 工作树或基线 ref，跳过对拍"
            "（可用 scripts/compare_field_meta_migration.py 手工跑）")
    with tempfile.TemporaryDirectory(prefix="packmeta-mig-") as tmp:
        wt = Path(tmp) / "repo"
        add = _git("worktree", "add", "--detach", str(wt), BASELINE_REF)
        assert add.returncode == 0, add.stderr
        try:
            _sync_new_packs_to(wt)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--baseline-ref", BASELINE_REF,
                 "--baseline-root", str(wt)],
                cwd=str(REPO), capture_output=True, text=True, timeout=600,
            )
        finally:
            _git("worktree", "remove", "--force", str(wt))
    assert proc.returncode == 0, (
        "批B 迁移对拍存在差异（应 0）：\n" + proc.stdout[-4000:] + "\n" + proc.stderr[-2000:])
    assert "差异条数：0" in proc.stdout, proc.stdout[-4000:]
    # 口径 ③：新增项必须显式计入输出（不得静默）。
    assert "新增 " in proc.stdout and "项（功能演化" in proc.stdout, proc.stdout[-2000:]
