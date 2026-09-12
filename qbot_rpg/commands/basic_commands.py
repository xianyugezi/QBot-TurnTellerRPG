"""基础指令组接线 basic_commands.py（M4 批次6·路G1 · qbot_rpg/commands/basic_commands.py）。

依据：m4_shared_contract §2.3 + 4f + 裁决②
  - m4_shared_contract.md §2.3（基础指令组：/角色 /背包 /装备 /技能 /帮助 等，4f RUL-01~34，
    页码夹取口径）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、页码越界夹取 +「已到最后一页」
    2026-08-27 用户裁决②、0/负数/非数字 → TPL-12、错误模板统一、emoji 纪律：
    icon 字段渲染剥离 emoji（M5 裁决「不用 emoji」；m4 §2.2 数据型功能图标豁免已作废，以 docs/全局图标登记表.md 为准））
  - docs/细化/细化_4f_基础指令组契约.md（RUL-01~34：/状态 面板五区 B4 裁决 → 本路 /角色 承载
    「LV 行固定头部 + 属性三层结构」玩家面板；/背包 RUL-16~19 行格式与分页；/装备 4b §三 装备栏
    穿戴；/技能 6a 技能库字段 + M2 技能卡「LV 行固定头部 + 派生指向」；/帮助 RUL-20~25 分组目录
    与 GM 保密、RUL-08 注册门槛 + B6 /帮助 豁免）
  - docs/细化/细化_3d_消息模板规范.md（TPL-08 页脚 / TPL-12 指令出错 / D-01 emoji 禁令 / D-04 错误
    文案唯一源 / §2.2 页码输入 + 裁决② 尾注）
  - docs/细化/细化_3b_玩家属性三层.md（白值/加成/临时三层结构 → /角色 面板，管线出口
    qbot_rpg/core/player_attributes.calc_all_final_attributes）
  - docs/细化/细化_6a_技能库契约.md（skills.json 字段：type/mp_cost/desc/chain_refs/job_restrict；
    chain_refs → skill_chains.json 派生链 → 「可派生成：XX」指向）
  - docs/细化/细化_4b_物品与背包契约.md（INV-01~07 行结构 + RUL-19 行格式：图标/×数量/品质/绑定；
    icon 字段渲染剥离 emoji（M5 裁决「不用 emoji」，docs/全局图标登记表.md 作废 m4 §2.2 数据型图标豁免）
    排序 acquired_at 倒序 INV-07/RUL-17）
  - 2026-08-27 用户裁决②（列表页码超总页数 → 夹取最后一页 +「已到最后一页」；0/负数/非数字 → TPL-12）

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /角色 /背包 /装备 /技能 /帮助 五条基础指令从
Router 接到 core 层——指令解析（parsers.parse_command 已 token 化 → 本模块取页码/子词/序号）、
玩家面板/背包/装备栏/技能列表渲染（core/message_format/list_render 5 条/页 + 裁决② 夹取；
尾段统一 CakeGame 式「当前页 + Tip」render_cake_tail，2026-08-27 用户拍板）、
装备穿卸委托装备引擎（core/equipment.py，M6 批1 已实装 EquipmentEngine + 适配层，
注入优先 → 懒加载 →【待接线】RuntimeError，与 checkin_commands 同模式）、错误统一
TPL-12（sender.format_tpl12，文案唯一源 errors.py D-04）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性（now/rng 由 ctx
注入）；工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌
功能性标记；icon 字段渲染剥离 emoji（M5 裁决，m4 §2.2 豁免已作废，登记表为准）。本模块只做「装配接线 + 渲染」，状态变更全部委托引擎。

--------------------------------------------------------------------------------
消费接口（core/equipment.py · M6 批次1·路A 已实装 · EQP-12 适配层，注入优先）：
  EquipmentEngineAdapter（本文件）实现 equip_wear(index: int, ctx) -> dict {ok, message}
  / equip_remove(slot_id: str, ctx) -> dict {ok, message}：包装真实
  core.equipment.EquipmentEngine.equip/unequip，从 ctx["player"]（可变 dict）解析背包
  ItemInstance 并就地更新玩家状态，组装中文消息（EQP-E1~E5 边界文案）。
  ctx["equip_engine"] 注入优先（装配层注入适配器 / 测试注入替身）；
  未注入 → _equip_engine 懒加载构造 EquipmentEngineAdapter（EQP-12 兜底）。
  （装备栏渲染由本层纯函数从 ctx["equipment"] 直读，不依赖引擎）

--------------------------------------------------------------------------------
【工程补白 · 显式标注】
  1) **5 条/页横切由本层统一**：/角色 属性三层明细、/背包 物品行、/装备 槽位、/技能 技能行、
     /帮助 目录/组页 全部按 m4 §2.2 5 条/页；尾段统一 CakeGame 式「当前页 + Tip 尾行」
     （render_cake_tail，2026-08-27 用户拍板，替代 TPL-08 页脚）：当前页恒显示 + 各指令定制
     Tip（/角色=查看当前装备、/装备=穿戴、/技能=技能说明、/帮助=翻页查看指令；/背包/背包筛选
     带货币行 + 类型词）。2026-09-12 专项·尾行 Tip 统一后，各 Tip 均为全量表键
     （tip_bag / tip_bag_view / tip_consume / tip_equip / tip_view / tip_skill /
     tip_help / tip_help_dir / tip_help_group，免斜杠口径；内容包可覆盖），本层零文案常量。
  2) **4f TPL-4F-06 目录页脚「输入 /帮助 组名 翻页」归一**：2026-08-27 用户拍板后基础指令组
     列表尾段不再用 TPL-08，统一 CakeGame 式（当前页 + Tip）；/帮助 目录/组页 Tip =
     「发 帮助 <页数> 翻页」（表键 tip_help_dir；单页回落 tip_help「发 帮助 <组名> 组内指令」）。
  3) **/角色 = 玩家属性面板（B4 裁决承接）**：4f /状态 面板五区中「前缀行/位置行/效果区」由装配层
     prefix_render 与后续批次承接；本路 /角色 聚焦任务口径「LV 行固定头部 + 属性三层结构
     （白值/加成/临时）」，9 项属性 5 条/页 = 2 页 + CakeGame 尾段（当前页 + Tip）+ 裁决② 夹取。resource 型（生命/魔力）
     显示 当前/上限（当前取 ctx["hp"]/ctx["mp"]）；最终值经 3b 管线 calc_all_final_attributes。
  4) **/装备 不加翻页（意见一同步）**：面板一次性展示全部已装备槽位（头部 `【装备】`、
     槽位行去序号、空槽不显示、Tip「使用 序号」）；切换装备走显式子词
     「穿 <序号>」（背包序号）/「卸 <槽位>」（槽位名/id/序号，本层 resolve_equip_slot 纯
     解析 → 引擎）；槽位名/序号解析失败 = 值域文案「❌ 没有这个装备槽位」（命令合法，不走 TPL-12，
     对齐 quest「任务不存在」口径）。
  5) **/技能 派生指向**：skill.chain_refs → ctx["skill_chains"] 链定义（steps[].from == 本技能 →
     收集 steps[].to → 技能名解析，1c2 派生链语义）；无派生链 → 不输出「可派生成」。技能按
     type 排序 basic→active→passive→trigger（6a §1.5 普攻固定第 1 位），job_restrict 过滤当前职业。
  6) **/帮助 分组目录**：内置分组表（冒险/战斗/成长/制造生活/快捷 + GM 组 B8 仅 GM 渲染）；
     普通玩家 5 组单页；GM 6 组 2 页（带 CakeGame 尾段）；组内指令列表 5 条/页。未注册玩家返回注册引导版
     （B6 豁免）。GM 判定读 ctx["is_gm"]（缺省 False=普通玩家，对齐 RUL-25 静默隐藏）。
  7) **注册门槛（RUL-08）**：/角色 /背包 /装备 /技能 在 ctx["registered"] is False 时统一返回
     「❌ 请先创建角色 / 发 注册 名字 职业」（批5·路O 新规范：免斜杠、拆两行）；/帮助 豁免（B6）。
     ctx 缺省 registered=True
     （未注入时不拦截，保持既有命令壳纯函数可测）。
  8) **/背包 数据源**：ctx["inventory"]（ItemInstance 或 dict 行均可，兼容 4a 存档行形态）优先，
     ctx["player"].inventory 兜底；排序 = acquired_at 倒序（INV-07/RUL-17），无时间字段保持存储序
     （稳定排序）；图标读 items.json 配置（渲染剥离 emoji，M5 裁决；m4 §2.2 数据型图标豁免已作废），缺省不显示。
  9) 本模块的玩家上下文工厂 make_context（NoneBot 事件 + 存储 → ctx dict）由装配层注入
     （register_basic_commands 的 make_context 参数），**批次7 装配待接线**；注入前本层可纯
     函数单测（直接构造 ctx + 注入真实/替身装备引擎）。
  10) **/装备 换真实引擎（EQP-12 / D1 P1-5 ③）**：EquipmentEngineAdapter 包装真实
     core.equipment.EquipmentEngine（M6 路A 已实装），保持 equip_wear/equip_remove 消费接口
     签名（不破坏既有 FakeEquipEngine 注入测试）；未注入时懒加载兜底（_equip_engine）。
  11) **/帮助 别名显示替换（SHC-04 / 4f RUL-24 / TC-17）**：目录行与组页指令名按
     settings.command_aliases 显示层替换（keep_original:false → 仅显别名；true → 双名并显）；
     解析/触发走 router/parsers 别名机制（既有），本层只做显示层替换。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.message_format import strip_icon_emoji
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）
from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_cake_tail,
    resolve_page,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.gear_stats import GEAR_LABELS_ZH, GEAR_NUMERIC_KEYS, PCT_SUFFIX
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.logging_utils import get_logger
from qbot_rpg.data.player import EquipmentSlot, Player, PlayerAttributes

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .parsers import parse_int
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名 / 子指令词
    "VIEW_CMD", "BAG_CMD", "BAG_FILTER_CMD", "EQUIP_CMD", "SKILL_CMD", "HELP_CMD",
    "VIEW_DETAIL_CMD", "cmd_view_detail",
    "SUB_REMOVE",
    # 渲染常量
    "TPL_REGISTER_GATE", "TPL_EMPTY_BAG", "TPL_NO_SLOT", "TPL_EQUIP_NAME_HINT",
    "QUALITY_LABELS", "TYPE_LABELS", "DEFAULT_SLOT_NAMES",
    "HELP_GROUPS", "GM_HELP_GROUP", "GROUP_ORDER",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_view", "cmd_bag", "cmd_equip", "cmd_skill", "cmd_help",
    # 渲染 / 工具
    "attr_line", "bag_line", "equip_line", "skill_line", "group_page_line",
    "resolve_equip_slot", "parse_page_arg", "view_header", "skill_rows",
    "EquipmentEngineAdapter",
    # 装配
    "register_basic_commands",
]

# ---------------------------------------------------------------------------
# 常量：指令名 / 子指令词 / 业务文案
# ---------------------------------------------------------------------------

VIEW_CMD = "角色"
VIEW_DETAIL_CMD = "角色详细"  # 2026-08-27 用户拍板：/角色 简洁版 + /角色详细 三层明细
BAG_CMD = "背包"
EQUIP_CMD = "装备"
SKILL_CMD = "技能"
MY_SKILL_CMD = "我的技能"  # 2026-08-30 实机反馈：玩家用「我的技能」→ 映射 技能（别名）
# 2026-09-05 用户需求：技能详情 / 技能派生 独立指令
SKILL_INFO_CMD = "技能详情"
SKILL_CHAIN_CMD = "技能派生"
HELP_CMD = "帮助"

# 装备子指令词（非解析器固定子词，经 args 位置参数识别；对齐 checkin「状态/补签」模式）
# 2026-09-05 用户拍板：穿戴统一「使用 序号」——「穿」子词整体删除（无独立指令，
# 「装备 穿 N」落名称形式友好提示），仅保留「卸」
SUB_REMOVE = "卸"
# 2026-09-06 设计定稿独立词：卸下 <部位>（转发现有 装备 卸 逻辑）
UNEQUIP_CMD = "卸下"

# RUL-08 注册门槛（4f §1.4 / TC-05；/帮助 豁免见 B6；模板配置化：basic_register_gate 可内容包覆盖）
# 批5·路O（2026-09-12）：文案与新规范统一（免斜杠、拆两行），模板 key = basic_register_gate
TPL_REGISTER_GATE = "❌ 请先创建角色\n发 注册 名字 职业"

# /背包 空背包（4f §3.4 边界：对齐 L1353 反向兜底；模板配置化：basic_empty_bag）
TPL_EMPTY_BAG = "❌ 背包空空如也"

# /装备 槽位解析失败（值域问题，命令合法，不走 TPL-12；工程补白 4；模板配置化：basic_no_slot）
TPL_NO_SLOT = "❌ 没有这个装备槽位"

# /装备 名称形式（如 /装备 铁剑）→ 友好提示引导序号用法（P2-11 QA：名称被泛化
# 拒绝回「❌ 指令不正确」，应提示 /装备 <序号>；命令合法，不走 TPL-12，对齐 TPL_NO_SLOT；
# 模板配置化：basic_equip_name_hint）
TPL_EQUIP_NAME_HINT = "❌ 穿戴请用 使用 <序号>\n序号见 背包 列表\n示例：发 使用 1"

# 品质四档（4b GRD-x 唯一注册表；RUL-19：仅非 normal 档标注）
QUALITY_LABELS: Mapping[str, str] = {
    "normal": "",
    "fine": "精良",
    "epic": "史诗",
    "legendary": "传说",
}

# 技能 type 四类中文（6a §1.4）
# 技能标签兜底（2026-09-12 用户拍板：标签=**自由文本**，内容包 `brief` 字段为准；
# 本表仅在未配置 brief 时按机制兜底生成，供玩家先看到像样的标签行）。
# 资源/精力键展示名（消耗行）：内容包 `energy_cost` 键 → 中文（自由文本 brief 之外仍可覆盖）
_ENERGY_LABELS: Mapping[str, str] = {
    "focus": "聚焦", "stamina": "精力", "mp": "灵能", "sp": "SP",
}

_SKILL_TAG_ORDER: Tuple[str, ...] = (
    "damage", "cost", "combo", "derive", "air", "dodge", "parry",
    "move", "part", "multi", "armor", "interrupt",
)
_SKILL_TAG_LABELS: Mapping[str, str] = {
    "damage": "【伤害】",
    "cost": "【消耗】",
    "combo": "【连段】",
    "derive": "【派生】",
    "air": "【跃空】",
    "dodge": "【闪反】",
    "parry": "【防反】",
    "move": "【机动】",
    "part": "【部位】",
    "multi": "【多段】",
    "armor": "【霸体】",
    "interrupt": "【打断】",
}

TYPE_LABELS: Mapping[str, str] = {
    "basic": "普攻",
    "active": "主动",
    "passive": "被动",
    "trigger": "触发",
}
KIND_LABELS: Mapping[str, str] = {
    "damage": "伤害",
    "heal": "治疗",
    "buff": "增益",
    "debuff": "减益",
    "guard": "格挡",
    "dodge": "闪避",
    "utility": "功能性",
}

# 装备槽位缺省中文名（slots.json 未配置时兜底；EQP-04 slot_schema 引用）
DEFAULT_SLOT_NAMES: Mapping[str, str] = {
    "weapon": "武器",
    "armor_head": "头部",
    "armor_body": "身体",
    "armor_hand": "手部",
    "armor_leg": "腿部",
    "armor_foot": "脚部",
}

# 槽位缺省顺序（4b §3.1：武器 + 五部位；ctx["slot_order"] 可覆盖）
DEFAULT_SLOT_ORDER: tuple = (
    "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
)

# 属性名兜底（stats.json name 缺失时；4f RUL-12 全中文）
_DEFAULT_STAT_NAMES: Mapping[str, str] = {
    "hp": "生命", "mp": "魔力", "str": "力量", "int": "智力", "con": "体质",
    "spr": "精神", "foc": "专注", "agi": "敏捷", "lck": "幸运",
}

# 属性默认展示顺序（stats.json 键序缺失时；九预置 3b §4.1）
_DEFAULT_STAT_ORDER: tuple = ("hp", "mp", "str", "int", "con", "spr", "foc", "agi", "lck")

# /帮助 分组目录（4f RUL-21 六组顺序：冒险/战斗/成长/制造生活/快捷/GM；组内指令按框架章节顺序）
HELP_GROUPS: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = (
    # 冒险 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("冒险", (
              ("角色", "查看角色面板"),
              ("角色详细", "查看角色完整属性（角色 详细）"),
              ("状态", "查看当前战斗状态/效果"),
              ("我的状态", "查看自身状态详情"),
              ("背包", "查看背包（背包 查看 <序号|名称> 看详情）"),
              ("背包筛选", "按类型筛选背包"),
              ("装备", "查看已穿戴装备"),
              ("位置", "查看当前位置与通道"),
              ("地图", "查看可传送地图（仅驿站/营地）"),
              ("进入", "移动/传送：进入 <方向|序号>"),
              ("调查", "调查当前环境线索"),
              ("时间", "查看游戏内时间"),
              ("天气", "查看当前天气"),
              ("怪物", "查看当前地图怪物列表"),
              ("图鉴", "查看怪物/物品图鉴"),
              ("教学", "查看玩法教学"),
              )),
    # 战斗 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("战斗", (
              ("攻击", "攻击当前目标（攻击 或 攻击 <技能>）"),
              ("锁定", "锁定目标开战：锁定 <序号>"),
              ("锁定怪物", "锁定指定怪物"),
              ("查看目标", "战斗中查看目标状态"),
              ("技能", "查看技能列表"),
              ("技能详情", "查看技能详细说明"),
              ("技能派生", "查看技能派生链"),
              ("技能面板", "查看技能装备面板"),
              ("我的技能", "查看已装配技能"),
              ("使用", "使用物品/穿戴装备：使用 <序号|名称>"),
              ("卸下", "卸下装备"),
              ("木桩", "进入训练木桩练手"),
              ("调整木桩", "设置木桩面板"),
              ("确认", "确认锻造/操作（预览后确认）"),
              ("放弃", "放弃当前操作/任务"),
              )),
    # 任务 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("任务", (
              ("任务", "查看任务板（任务 领取/交付 <序号>）"),
              ("任务信息", "查看任务详情"),
              ("接取", "接取任务"),
              ("交付", "交付已完成任务"),
              ("委托", "生活委托板"),
              ("签到", "每日签到领奖励"),
              ("赠送", "赠送物品给玩家：赠送 <道具> <玩家>"),
              ("成就", "查看成就列表"),
              ("成就信息", "查看成就详情"),
              ("称号", "查看/佩戴称号"),
              )),
    # 商店 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("商店", (
              ("商店", "浏览当前商店（商店 <页码>）"),
              ("商店列表", "查看可用商店列表"),
              ("商店进入", "进入指定商店：商店进入 <序号|名称>"),
              ("购买", "购买商品：购买 <序号> [数量]"),
              ("出售", "出售物品"),
              ("对话", "与 NPC 对话：对话 <序号|名称>"),
              ("分解", "分解装备成素材"),
              ("休息", "在安全区休息恢复"),
              )),
    # 成长 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("成长", (
              ("转职", "转换职业"),
              ("职业", "查看职业列表"),
              ("职业列表", "查看可选职业"),
              ("职业详情", "查看职业详细说明"),
              ("强化", "强化装备：强化 <装备名>[+等级]"),
              ("强化信息", "查询强化详情"),
              ("强化保护", "带保护石强化"),
              ("镶嵌", "装备开孔/镶嵌"),
              ("拆珠", "拆下镶嵌珠"),
              ("珠升阶", "镶嵌珠升阶"),
              ("进化", "装备进化"),
              )),
    # 制造 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("制造", (
              ("锻造", "锻造装备：锻造 <装备名>"),
              ("锻造树", "查看锻造树"),
              ("图纸", "查看锻造图纸/材料链"),
              ("打造", "打造装备"),
              ("铸造", "铸造（打造系入口）"),
              ("套装", "查看套装效果"),
              ("客制", "查看客制强化"),
              ("炼金", "炼金制作"),
              ("深度炼金", "深度炼金（进阶调合）"),
              ("即时调合", "战斗中即时调合"),
              ("调合", "调合材料"),
              ("调合续", "继续上次调合"),
              ("投料", "炼金投料"),
              ("成品合成", "合成成品"),
              ("配方合成", "按配方合成"),
              ("特性合成", "特性合成"),
              ("合成", "合成物品"),
              )),
    # 生活 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("生活", (
              ("种植", "种植作物"),
              ("收获", "收取成熟作物"),
              ("温室", "查看温室状态"),
              ("代工", "委托助手代工"),
              ("收取", "收取助手产出"),
              ("投稿", "品评会投稿：投稿 <道具>"),
              ("排行榜", "查看品评会排行"),
              ("采集", "采集资源"),
              ("钓鱼", "抛竿钓鱼"),
              ("收杆", "收杆（钓鱼）"),
              ("鱼讯", "查看鱼讯"),
              )),
    # 快捷 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("快捷", (
              ("快捷列表", "查看已绑快捷指令"),
              ("快捷绑定", "绑定快捷指令（待实装）"),
              ("快捷解绑", "解绑快捷指令"),
              )),
    # 账号 组（2026-09-06 全量重建：覆盖全部已注册玩家指令）
    ("账号", (
              ("注册", "创建角色：注册 <角色名> [职业]"),
              ("注销", "删除角色：注销"),
              )),
)


# 2026-08-31 用户拍板：目录总览行展示子集（仅影响总览，/帮助 <组名> 组页仍显示完整组）
# 2026-09-06 全量重建：9 组无特例——目录行统一取各组前 5 条
_DIRECTORY_SHOW: Dict[str, Tuple[str, ...]] = {}

# GM 组（RUL-25：无 GM 权限不渲染、不提示存在；GM 可见）
GM_HELP_GROUP: Tuple[str, Tuple[Tuple[str, str], ...]] = (
    "GM", (("重载", "重载内容包"), ("封禁", "封禁玩家"), ("日志", "查看日志"),
           ("编辑", "编辑配置"), ("设置", "设置参数")),
)

# 分组名常量（目录页/组页引用）
GROUP_ORDER: Tuple[str, ...] = tuple(g[0] for g in HELP_GROUPS) + (GM_HELP_GROUP[0],)

# 批5·路O（2026-09-12）：原硬编码 _REGISTER_GUIDE 已删（全仓零引用；注册引导统一走
# basic_register_guide 模板，见 cmd_help 未注册分支）。

# 目录头（4f TPL-4F-06；2026-08-31 用户拍板：标题只留【指令总览】，翻页提示由尾段 Tip 承担）
_DIRECTORY_TITLE = "【指令总览】"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _fmt_num(v: object) -> str:
    """数值渲染：整数去小数、浮点去尾零、非法原样。"""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def _fmt_bonus(flat: float, pct: float) -> str:
    """加成/临时层摘要：`+5·+10%`；双零 → `0`。"""
    parts: List[str] = []
    if flat:
        parts.append(f"+{_fmt_num(flat)}")
    if pct:
        parts.append(f"+{_fmt_num(pct)}%")
    return "·".join(parts) if parts else "0"


def parse_page_arg(text: Optional[str]) -> Optional[int]:
    """页码参数归一：None → 1；整数 ≥1 → 原值；0/负数/非数字 → None（壳层转 TPL-12，裁决②）。"""
    if text is None:
        return 1
    n = parse_int(text)
    if n is None or n < 1:
        return None
    return n


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛：ctx["registered"] is False → 拦截文案；缺省视为已注册（工程补白 7）。

    模板配置化 2026-08-31：basic_register_gate 可内容包覆盖；TPL_REGISTER_GATE 常量保留
    供兄弟模块（status/shortcut/use/forge/shop/checkin/quest/codex/battle/log/dialog）
    复用（其渲染处由各自批次迁移）。
    """
    if ctx.get("registered", True) is False:
        return tpl_of(ctx, "basic_register_gate")
    return None


# ---------------------------------------------------------------------------
# /角色：玩家属性面板（LV 行固定头部 + 属性三层结构，5 条/页 + TPL-08 + 裁决②）
# ---------------------------------------------------------------------------

def _player_fields(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """玩家基础字段归一（ctx 直取 → ctx["player"] dataclass 兜底）。"""
    p = ctx.get("player")
    if p is not None and not isinstance(p, Mapping):
        return {
            "name": str(getattr(p, "name", None) or ctx.get("name") or "?"),
            "level": int(getattr(p, "level", None) or ctx.get("level") or 1),
            "exp": getattr(p, "exp", None) if getattr(p, "exp", None) is not None else ctx.get("exp"),
            "job_id": str(getattr(p, "job_id", None) or ctx.get("job_id") or ""),
            "hp": getattr(p, "hp", None) if getattr(p, "hp", None) is not None else ctx.get("hp"),
            "mp": getattr(p, "mp", None) if getattr(p, "mp", None) is not None else ctx.get("mp"),
        }
    return {
        "name": str(ctx.get("name") or "?"),
        "level": int(ctx.get("level") or 1),
        "exp": ctx.get("exp"),
        "job_id": str(ctx.get("job_id") or ""),
        "hp": ctx.get("hp"),
        "mp": ctx.get("mp"),
    }


def _job_name(ctx: Mapping[str, Any], job_id: str) -> Optional[str]:
    """职业 id → 中文名（ctx["jobs"] 映射；缺失返回 None）。"""
    if not job_id:
        return None
    jobs = ctx.get("jobs")
    if isinstance(jobs, Mapping):
        d = jobs.get(job_id)
        if isinstance(d, Mapping):
            return str(d.get("name")) if d.get("name") else None
        if d is not None and hasattr(d, "get"):
            n = d.get("name")
            return str(n) if n else None
    return None


def _base_header(ctx: Mapping[str, Any], label: str) -> str:
    """LV 行固定头部基座：`【{label}】Lv3.阿伟（战士）`。"""
    f = _player_fields(ctx)
    job = str(ctx.get("job_name") or _job_name(ctx, f["job_id"]) or "")
    # 2026-08-31：内容包无 jobs 表时 job_name 为空 → 默认职业兜底「新手」防显示（?）
    if not job and f["job_id"] == "novice":
        job = "新手"
    return f"【{label}】Lv{f['level']}.{f['name']}（{job}）"


def view_header(ctx: Mapping[str, Any]) -> str:
    """角色面板头部（2026-08-31 用户拍板 + 模板配置化：模板来自 ctx[templates]
    role_header/role_level/role_job/role_exp/role_max，内容包可覆盖）。"""
    f = _player_fields(ctx)
    lines: List[str] = [
        tpl_of(ctx, "role_header", {"name": f["name"]}),
        tpl_of(ctx, "role_level", {"level": f["level"]}),
    ]
    job = str(ctx.get("job_name") or _job_name(ctx, f["job_id"]) or "")
    if not job and f["job_id"] == "novice":
        job = "新手"
    if job:
        lines.append(tpl_of(ctx, "role_job", {"job": job}))
    max_lv = ctx.get("max_level")
    if max_lv is not None and f["level"] >= int(max_lv):
        lines.append(tpl_of(ctx, "role_max", {}))
    elif f["exp"] is not None:
        nxt = ctx.get("exp_next")
        if nxt is not None:
            lines.append(tpl_of(ctx, "role_exp",
                                {"exp": _fmt_num(f["exp"]), "exp_next": _fmt_num(nxt)}))
        else:
            lines.append(tpl_of(ctx, "role_exp_only", {"exp": _fmt_num(f["exp"])}))
    return "\n".join(lines)


def _to_attributes(ctx: Mapping[str, Any]) -> PlayerAttributes:
    """属性三层归一为 PlayerAttributes（3b §4.4 三子层键空间；dict 形态兼容，工程补白 3）。"""
    attrs = ctx.get("attributes")
    if isinstance(attrs, PlayerAttributes):
        return attrs
    raw = attrs if isinstance(attrs, Mapping) else ctx.get("attr_layers")
    if raw is None:
        raw = {}
    bonus = dict(raw.get("bonus") or {}) if isinstance(raw.get("bonus"), Mapping) else {}
    temp = dict(raw.get("temp") or {}) if isinstance(raw.get("temp"), Mapping) else {}
    return PlayerAttributes(
        base=dict(raw.get("base") or {}),
        bonus={
            "flat": dict(bonus.get("flat") or {}),
            "pct": dict(bonus.get("pct") or {}),
        },
        temp={
            "pct": dict(temp.get("pct") or {}),
            "flat": dict(temp.get("flat") or {}),
        },
        cond=dict(raw.get("cond") or {}),
    )


def _stat_name(ctx: Mapping[str, Any], attr_id: str) -> str:
    """属性 id → 中文名（stats.json 配置优先；缺省兜底表）。"""
    stats = ctx.get("stats")
    if isinstance(stats, Mapping):
        d = stats.get(attr_id)
        if isinstance(d, Mapping) and d.get("name"):
            return str(d["name"])
        if d is not None and hasattr(d, "get"):
            n = d.get("name")
            if n:
                return str(n)
    return _DEFAULT_STAT_NAMES.get(attr_id, attr_id)


def _stat_order(ctx: Mapping[str, Any], attrs: PlayerAttributes) -> List[str]:
    """属性展示顺序：stats.json 键序优先；最终只显示 stats.json 声明键。

    M12.5 动态化（2026-09-04）：原 union 把 attrs 残留键（老档案删属性前的
    base/bonus 键）也列入显示 → 删属性后老玩家面板仍显示已删属性。现改为
    「stats.json 声明键为准」：attrs 层（base/bonus/temp/cond）只取声明键交集，
    未声明键一律不显示（属性注册表唯一源 = stats.json）。stats 缺失时回落
    attrs 键并集（旧行为兜底，兼容无 stats 的裸 ctx 测试）。
    """
    stats = ctx.get("stats")
    if isinstance(stats, Mapping) and stats:
        order = [str(k) for k in stats.keys()]
        return order
    order = list(_DEFAULT_STAT_ORDER)
    union = set(attrs.base) | set(attrs.flat_bonus()) | set(attrs.pct_bonus()) \
        | set(attrs.temp_flat()) | set(attrs.temp_pct()) | set(attrs.cond)
    for k in union:
        if k not in order:
            order.append(k)
    return order


def attr_line(attr_id: str, stat_name: str, final: int,
              attrs: PlayerAttributes, current: Optional[int] = None,
              *, detail: bool = False, ctx: Any = None) -> str:
    """属性行（无序号，2026-08-27 用户拍板 /角色 面板属性前不加序号；模板配置化
    2026-08-31：行格式来自 ctx[templates] role_attr*，内容包可覆盖，ctx=None 用默认）：
    detail=False（/角色 简洁版）→ `【力量】29` / resource `【生命】30/100`；
    detail=True（/角色详细 完整版）→ `【力量】29（白值 15 ｜ 加成 +5·+10% ｜ 临时 +3·+20%）`。"""
    if not detail:
        if current is not None:
            return tpl_of(ctx, "role_attr_resource",
                          {"attr_name": stat_name, "cur": _fmt_num(current),
                           "max": final})
        return tpl_of(ctx, "role_attr", {"attr_name": stat_name, "value": final})
    base = float(attrs.base.get(attr_id, 0.0))
    flat = float(attrs.flat_bonus().get(attr_id, 0.0))
    pct = float(attrs.pct_bonus().get(attr_id, 0.0))
    tflat = float(attrs.temp_flat().get(attr_id, 0.0))
    tpct = float(attrs.temp_pct().get(attr_id, 0.0))
    bonus = _fmt_bonus(flat, pct)
    temp = _fmt_bonus(tflat, tpct)
    if current is not None:
        return tpl_of(ctx, "role_attr_detail_resource",
                      {"attr_name": stat_name, "cur": _fmt_num(current), "max": final,
                       "base": _fmt_num(base), "bonus": bonus, "temp": temp})
    return tpl_of(ctx, "role_attr_detail",
                  {"attr_name": stat_name, "value": final,
                   "base": _fmt_num(base), "bonus": bonus, "temp": temp})


def _render_attr_page(ctx: Mapping[str, Any], page: int, *, detail: bool = False) -> str:
    """/角色 正文：LV 行固定头部 + 全部属性行（2026-08-31 用户反馈：属性面板不再
    5 条/页分页——玩家属性是固定集合，分页导致「属性缺很多」观感，改为一次全量展示）。

    detail=False（/角色）→ 简洁属性行；detail=True（/角色详细）→ 三层明细行。"""
    attrs = _to_attributes(ctx)
    f = _player_fields(ctx)
    final = calc_all_final_attributes(
        attrs,
        conditional_rules=ctx.get("conditional_rules") or (),
        resource_pct=_resource_pct(ctx),
        attr_types=ctx.get("attr_types"),
    )
    order = _stat_order(ctx, attrs)
    items: List[Tuple[str, Optional[int]]] = []
    for attr_id in order:
        if attr_id not in final:
            continue
        current = None
        if attr_id in ("hp", "mp"):
            cur = f.get(attr_id)
            current = int(cur) if cur is not None else None
        items.append((attr_id, current))
    lines: List[str] = [view_header(ctx)]
    for attr_id, cur in items:
        lines.append(attr_line(attr_id, _stat_name(ctx, attr_id),
                               final[attr_id], attrs, current=cur, detail=detail))
    return "\n".join(lines)


def _resource_pct(ctx: Mapping[str, Any]) -> bool:
    """settings.resource_pct（3b ADR-02：resource 型百分比默认关）。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        return bool(settings.get("resource_pct", False))
    return False


def cmd_view(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/角色 [页码]：玩家属性面板（LV 行固定头部 + 属性三层结构 5 条/页 + TPL-08 + 裁决② 夹取；
    0/负数/非数字 → TPL-12；超参/未知子词 → TPL-12）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_attr_page(ctx, page)


def cmd_view_detail(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/角色详细 [页码]：完整属性面板（三层明细：白值/加成/临时，2026-08-27 用户拍板
    /角色 简洁、/角色详细 才显示三层；5 条/页 + CakeGame 式尾段 + 裁决② 夹取）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_attr_page(ctx, page, detail=True)


# ---------------------------------------------------------------------------
# /背包：物品列表（5 条/页 + ×数量/品质/绑定 + TPL-08 + 裁决②）
# ---------------------------------------------------------------------------

def _inventory_rows(ctx: Mapping[str, Any]) -> list:
    """背包行归一（ctx["inventory"] 优先 → ctx["player"].inventory 兜底）；按 acquired_at 倒序
    （INV-07/RUL-17），无时间字段保持存储序（稳定排序，工程补白 8）。"""
    # M8 批12 装配层 inventory 双形态（context.py L976/L1053）：ctx["inventory"] =
    # {item_id: count} 计数映射（任务/条件引擎消费），ctx["inventory_items"] =
    # list[ItemInstance] 展示列表。本函数是展示入口 → 必须优先读 inventory_items，
    # 否则把计数映射的 key 当行 → 物品名全 [?]（实机部署反馈「神必bug」，2026-08-30）。
    inv = ctx.get("inventory_items")
    if inv is None:
        inv = ctx.get("inventory")
    if inv is None:
        player = ctx.get("player")
        if player is not None:
            inv = getattr(player, "inventory", None)
    if isinstance(inv, Mapping):
        rows = []
        for _item_id, _count in inv.items():
            if _count <= 0:
                continue
            rows.append({"item_id": _item_id, "count": _count})
    else:
        rows = list(inv) if inv else []

    def _key(r: Any) -> str:
        if isinstance(r, Mapping):
            t = r.get("acquired_at")
            return str(t) if t is not None else ""
        return ""

    try:
        return sorted(rows, key=_key, reverse=True)
    except TypeError:  # 混合类型时间字段 → 保持原序
        return rows


def _item_icon(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品图标（items.json 配置；M5 裁决不用 emoji——渲染出口剥离 emoji 字符，保纯文本
    /自定义文本符号，作者可配「剑」「+」等；缺省空）。"""
    if not item_id:
        return ""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        d = items.get(item_id)
        if isinstance(d, Mapping):
            return strip_icon_emoji(d.get("icon") or "")
        if d is not None and hasattr(d, "get"):
            return strip_icon_emoji(d.get("icon") or "")
    return ""


def _row_fields(row: Any, ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """背包行字段归一（ItemInstance dataclass 与 dict 行兼容，4a 存档行形态）。

    2026-09-06 zerc 反馈：背包行 name 缺失/为空时回退 item_id 导致详情显示英文
    id（【linge_blade_d】）——name 缺失改查 items 注册表中文名兜底，最后才回退
    item_id（仅注册表也查无的未知物品）。"""
    if isinstance(row, Mapping):
        item_id = str(row.get("item_id") or "")
        name = str(row.get("name") or "")
        count = row.get("count", 1)
        quality = str(row.get("quality") or "normal")
        bound = bool(row.get("bound"))
        icon = strip_icon_emoji(str(row.get("icon") or "") or _item_icon(ctx, item_id))
    else:
        item_id = str(getattr(row, "item_id", "") or "")
        name = str(getattr(row, "name", None) or "")
        count = getattr(row, "count", 1)
        quality = str(getattr(row, "quality", None) or "normal")
        bound = bool(getattr(row, "bound", False))
        icon = strip_icon_emoji(_item_icon(ctx, item_id))
    if not name:
        # name 缺失 → items 注册表中文名兜底（不再裸显英文 id）
        _d = _item_def(ctx, item_id) if item_id else None
        if isinstance(_d, Mapping):
            _nm = _d.get("name")
            if isinstance(_nm, str) and _nm:
                name = _nm
    if not name:
        name = item_id or "?"
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 1
    return {
        "item_id": item_id, "name": name, "count": count,
        "quality": quality, "bound": bound, "icon": icon,
    }


def bag_line(index: int, row: Any, ctx: Mapping[str, Any]) -> str:
    """物品行（用户 2026-08-27 自定义模板）：`{序号}.[{名称}]×{数量}`。

    方括号包名称（标识清晰，替代 icon 显示——M5 不用 emoji 后 icon 剥离，用户模板
    无图标）；×数量**恒显示**（含 ×1，对齐用户模板）；非 normal 品质追加 `（精良）`
    （4b GRD-x 注册表，RUL-19 仅非 normal 标注）；绑定追加 `（绑定）`。`×` 为展示
    符号（输入侧一律 `*`，铁律 1）。
    """
    f = _row_fields(row, ctx)
    line = tpl_of(ctx, "bag_row", {"idx": index, "name": f["name"], "count": f["count"]})
    q = QUALITY_LABELS.get(f["quality"])
    if q:
        line += tpl_of(ctx, "basic_quality_suffix", {"quality": q})
    if f["bound"]:
        line += tpl_of(ctx, "basic_bound_suffix")
    return line


def _currency_display_name(ctx: Mapping[str, Any], key: str) -> str:
    """货币键 → 中文名（settings currencies[].name 优先；缺省兜底 coins=金币/gem=钻石，
    框架 §8.1 默认模板「金币 + 钻石」）。"""
    # 2026-09-06 硬编码清理：统一 reward.currency_display_name（settings id 匹配；
    # 原版误读 key 字段且 gem/钻石 fallback 与其他模块不一致）
    from qbot_rpg.core.reward import currency_display_name  # noqa: PLC0415

    return currency_display_name(ctx, key)


def _currency_lines(ctx: Mapping[str, Any]) -> List[str]:
    """货币行（用户模板：`金币：0` / `钻石：0`）——遍历 ctx["currencies"]（key→余额）。"""
    cur = ctx.get("currencies")
    if not isinstance(cur, Mapping) or not cur:
        return []
    return [tpl_of(ctx, "basic_currency_row",
                   {"name": _currency_display_name(ctx, str(k)), "value": v})
            for k, v in cur.items()]


# CakeGame 式尾段 Tip 内容（`Tip:` 之后部分，2026-08-27 用户拍板统一列表尾段）。
# 2026-09-12 专项·尾行 Tip 统一：文案常量全部撤除 → 全量表键（免斜杠「发 <指令> <参数>」写法；
# 内容包 templates.json 可覆盖同键）；本层只留键名，渲染统一走 tpl_of(ctx, key)。
#   tip_bag        /背包     兜底（含货币行 + 类型词）
#   tip_bag_view   /背包     轮换池①：物品详情发现性引导
#   tip_consume    /背包     轮换池②（有装备时追加）：消耗品直发物品名
#   tip_equip      /装备     穿戴引导 + /背包 轮换池②（2026-09-05 用户拍板穿戴统一走 使用——
#                            「使用 N」实测可穿，勿教「装备 穿」）
#   tip_view       /角色     属性面板下一步（留表；旧常量亦零调用点，待批18 死键清扫裁决）
#   tip_skill      /技能     技能列表翻页（2026-09-05 模拟器审计：原「帮助 技能」不可解析）
#   tip_help       /帮助 组页 单页引导（2026-09-05 实机反馈：单页教翻页 = 空转引导，改教组内指令）
#   tip_help_dir   /帮助 目录 多页翻页（GM 6 组 2 页；紧凑形态「帮助2」解析层仍双认）
#   tip_help_group /帮助 <组名> 组页 多页翻页（紧凑形态「帮助冒险2」解析层仍双认）


def _cake_tail(page: int, total_pages: int, *, category_word: Optional[str] = None,
               tip: str = "", clamped: bool = False, templates: Optional[Mapping[str, Any]] = None) -> str:
    """CakeGame 式尾段（当前页 + 可选夹取提示 + Tip 尾行；模板配置化 2026-08-31：
    templates=ctx["templates"] 传 list_tail 可覆盖整体格式，缺省用内置默认）。

    夹取提示（裁决② LAST_PAGE_HINT）由本层按各指令 clamped 逻辑插入「当前页」与「Tip」之间，
    对齐 /背包 尾段顺序：`当前页：X/Y` → `（已到最后一页）` → `Tip:...`。
    """
    tail = render_cake_tail(page, total_pages, category_word=category_word, tip=tip,
                            templates=templates)
    if clamped:
        # 2026-09-05 修复：tail 无换行（单页 tip 空）时 replace 不命中 → 提示丢失；
        # 统一「当前页 →（已到最后一页）→ Tip」顺序：无 tip 时提示接尾
        if "\n" in tail:
            tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
        else:
            tail = f"{tail}\n{LAST_PAGE_HINT}" if tail else LAST_PAGE_HINT
    return tail


# 装备类型集（type 字段命中 = 装备——背包 Tip 区分穿戴/使用；内容包 type 自定义
# 走 row.slot 兜底：有 slot 即装备）
_EQUIP_TYPE_HINTS: tuple = ("weapon", "armor", "helmet", "gloves", "boots", "necklace",
                            "ring", "charm", "trinket", "shield", "装备", "武器", "防具")


def _is_equip_row(row: Any, ctx: Mapping[str, Any]) -> bool:
    """行是否装备（type 命中装备集或定义含 slot）。"""
    try:
        if isinstance(row, Mapping):
            t = str(row.get("type") or "")
            if row.get("slot") and not t:
                return True
        else:
            t = str(getattr(row, "type", "") or "")
            if getattr(row, "slot", None) and not t:
                return True
        if t in _EQUIP_TYPE_HINTS:
            return True
        # 定义兜底（items 表查 type）
        iid = row.get("item_id") if isinstance(row, Mapping) else getattr(row, "item_id", None)
        if iid:
            d = _item_def(ctx, str(iid))
            if isinstance(d, Mapping):
                dt = str(d.get("type") or "")
                if dt in _EQUIP_TYPE_HINTS or (d.get("slot") and not dt):
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _bag_has_equip(rows: Any, ctx: Mapping[str, Any]) -> bool:
    """背包行里是否有装备（2026-09-05 模拟器审计：有装备时 Tip 须教穿戴路径）。"""
    try:
        return any(_is_equip_row(r, ctx) for r in (rows or []))
    except Exception:  # noqa: BLE001
        return False


def _bag_tail_lines(page: int, total_pages: int, total: int, clamped: bool,
                    ctx: Mapping[str, Any], category_word: str = "全部",
                    tip: str = "") -> List[str]:
    """/背包 尾段：货币行 + `当前页：{page}/{total_pages}({类型词})` + 夹取提示 + Tip。

    （类型词 = 当前筛选的物品类型，用户 2026-08-27 拍板：/背包 → 全部，/背包筛选
    装备 → 装备、/背包筛选药剂 → 药剂 等；原「共 N 条」改显示筛选类型。
    tip 空 → 默认 tip_bag 表键（2026-09-05 模拟器审计：背包含装备时 Tip 教
    「使用 物品名」与装备实际穿戴路径「装备 穿 序号」矛盾——调用方按内容传 tip）"""
    lines: List[str] = list(_currency_lines(ctx))
    lines.append(_cake_tail(page, total_pages, category_word=category_word,
                            tip=tip or tpl_of(ctx, "tip_bag"), clamped=clamped,
                            templates=ctx.get("templates")))
    return lines


def _render_bag_page(ctx: Mapping[str, Any], page: int) -> str:
    """/背包 正文（用户自定义模板）：物品行 5 条/页 `{序号}.[{名称}]×{数量}` + 货币行
    + 当前页 + Tip；裁决② 夹取；空背包 → TPL_EMPTY_BAG。"""
    rows = _inventory_rows(ctx)
    if not rows:
        return tpl_of(ctx, "basic_empty_bag")
    res = resolve_page(page, len(rows), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_rows = rows[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [bag_line(start + i + 1, r, ctx) for i, r in enumerate(slice_rows)]
    # 2026-09-05 模拟器审计：背包有装备时 Tip 教「使用 物品名」与穿戴实际路径
    # （装备 穿 序号）矛盾——有装备 → Tip 含穿戴引导
    # 2026-09-06 实机反馈：玩家想查看物品详情连试「查看1/物品详情1」全静默——
    # 详情正确形态是「背包 查看 <序号|名|部位>」，Tip 必须教（发现性引导）
    # 2026-09-06 用户拍板：Tip 太长 → 每次随机出现其中一条（轮换引导）
    # 2026-09-12 专项·尾行 Tip 统一：池内文案 → 全量表键（免斜杠，内容包可覆盖）
    _tip_pool = [tpl_of(ctx, "tip_bag_view"),
                 tpl_of(ctx, "tip_equip")]
    if _bag_has_equip(rows, ctx):
        _tip_pool.append(tpl_of(ctx, "tip_consume"))
    # 2026-09-06 用户拍板「每次随机出现其中一条」：ctx rng 每指令同 seed 重播种
    # （确定性设计）→ randrange 恒取序列首值 → 无法轮换。Tip 为展示层装饰
    # （非游戏数值，无公平性要求），按当前时间秒级轮换（每指令变化、无状态、
    # 不破坏确定性数值引擎）；测试 make_ctx 注入固定 now → 取池首条断言稳定。
    # 轮换种子用毫秒级真实时间（展示层装饰；ctx.now 秒级同秒连发不变）
    import time as _time  # noqa: PLC0415
    try:
        _ms = int(_time.time() * 1000)
    except (TypeError, ValueError):
        _ms = 0
    _btip = _tip_pool[_ms % len(_tip_pool)]
    lines.extend(_bag_tail_lines(res.page, res.total_pages, res.total, res.clamped, ctx,
                                 tip=_btip))
    return "\n".join(lines)


def cmd_bag(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/背包 [页码]：物品列表（5 条/页 + TPL-08 + 裁决② 夹取；0/负数/非数字 → TPL-12）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    fs = getattr(parsed, "fixed_subword", None)
    if fs == "查看":
        # 2026-09-05 新功能：背包 查看 <序号|物品名|部位> —— 物品/已装备详情
        args_v = list(getattr(parsed, "args", None) or [])
        return _cmd_bag_view(ctx, args_v)
    if fs:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    # router 链路（route_and_expand）不抽 fixed_subword → args[0] 可能直接是「查看」；
    # 2026-09-06 实机「背包查看1」紧凑形：args[0]=「查看1」→ 拆子词+数字
    if args and str(args[0]) == "查看":
        return _cmd_bag_view(ctx, list(args[1:]))
    if args and str(args[0]).startswith("查看"):
        _rest = str(args[0])[2:]
        if _rest.isdigit():
            return _cmd_bag_view(ctx, [str(int(_rest))])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_bag_page(ctx, page)


def _cmd_bag_view(ctx: Mapping[str, Any], args: list) -> str:
    """背包 查看 <序号|物品名|部位>：物品/已装备详情（2026-09-05 新功能）。

    - 部位名（武器/身体/头部…）→ 查装备栏该部位已装备详情
    - 数字 → 背包第 N 件（展示序同 /背包）
    - 名称 → 背包/物品注册表匹配
    """
    if not args:
        return tpl_of(ctx, "bag_view_usage")
    target = str(args[0])
    rows = _inventory_rows(ctx)
    # 1) 数字 → 背包序号（背包展示序，用户语义优先）
    if target.isdigit():
        n = int(target)
        if 1 <= n <= len(rows):
            return _render_item_detail(rows[n - 1], ctx, source="bag")
        return tpl_of(ctx, "bag_view_no_item")
    # 2) 名称：先背包行匹配（item_id/name），再物品注册表，最后槽位名（部位）
    for r in rows:
        f = _row_fields(r, ctx)
        if f["item_id"] == target or f["name"] == target:
            return _render_item_detail(r, ctx, source="bag")
    d = _item_def(ctx, target)
    if isinstance(d, Mapping):
        return _render_item_detail({"item_id": d.get("id") or target, "count": 1}, ctx, source="def")
    if d is None:
        items = ctx.get("items")
        if isinstance(items, Mapping):
            for dd in items.values():
                if isinstance(dd, Mapping) and str(dd.get("name") or "") == target:
                    d = dd
                    break
    if isinstance(d, Mapping):
        return _render_item_detail({"item_id": d.get("id") or target, "count": 1}, ctx, source="def")
    # 3) 槽位名（武器/身体…）→ 已装备详情
    slot_hit = resolve_equip_slot(ctx, target)
    if slot_hit is not None:
        eq = _equipment_map(ctx)
        slot = eq.get(slot_hit)
        if slot is None:
            return tpl_of(ctx, "bag_view_empty_slot", {"slot": _slot_name(ctx, slot_hit)})
        return _render_item_detail(slot, ctx, source="equip")
    return tpl_of(ctx, "bag_view_no_item")


def _render_item_detail(row: Any, ctx: Mapping[str, Any], *, source: str) -> str:
    """物品详情面板（2026-09-05 新功能：背包 查看 / 装备部位详情渲染）。"""
    f = _row_fields(row, ctx)
    item_id = f["item_id"]
    d = _item_def(ctx, item_id) or {}
    lines: List[str] = [tpl_of(ctx, "bag_view_header", {"name": f["name"]})]
    # 类型（大类中文：weapon→装备/consumable→药剂…）+ 品质 + 数量 + 绑定
    meta_bits: List[str] = []
    t = str(d.get("type") or "")
    if t:
        _cat_key = _CATEGORY_BY_TYPE.get(t)
        meta_bits.append(_CATEGORY_CN.get(_cat_key or "", t))
    q = QUALITY_LABELS.get(str(f.get("quality") or "normal"))
    if q:
        meta_bits.append(q)
    if source in ("bag", "def"):
        meta_bits.append(f"×{f.get('count', 1)}")
    if f.get("bound"):
        meta_bits.append("绑定")
    if meta_bits:
        lines.append(" ".join(meta_bits))
    # 装备数值键（批⑧ 键空间收口：统一取自 data.gear_stats——含 dfn/会心/百分比/
    # 耳栓等；原手写 12 键缺 dfn/crit/_pct → 卡片不显示核心词条）
    stats = _item_stat_parts(d)
    if stats:
        lines.append("｜".join(stats))
    # 装备槽位
    slot = d.get("slot") or getattr(row, "slot", None)
    if slot and source != "equip":
        lines.append(tpl_of(ctx, "bag_view_slot", {"slot": _slot_name(ctx, str(slot))}))
    # 效果（消耗品 effects → effect_table 翻译）
    effs = d.get("effects") or []
    if effs:
        et = ctx.get("effect_table") or {}
        parts = []
        for eid in effs:
            ed = et.get(str(eid)) if isinstance(et, Mapping) else None
            if isinstance(ed, Mapping):
                etp = str(ed.get("type") or "")
                if etp == "heal":
                    parts.append(f"恢复 {int(ed.get('power') or 0)}")
                else:
                    parts.append(str(ed.get("name") or etp or eid))
            else:
                parts.append(str(eid))
        if parts:
            lines.append(tpl_of(ctx, "bag_view_effect", {"effects": "；".join(parts)}))
    # 描述
    desc = str(d.get("desc") or "")
    if desc:
        lines.append(desc)
    return "\n".join(lines)


def _stat_name_zh(key: str) -> str:
    """属性键 → 中文名（详情面板用；stats.json 配置优先？——缺省表兜底）。"""
    _m = {"atk": "攻击", "def": "防御", "hp": "生命", "mp": "魔力", "str": "力量",
          "con": "体魄", "agi": "敏捷", "foc": "专注", "spr": "精神", "lck": "幸运",
          "spd": "速度", "mag": "魔法"}
    return _m.get(key, key)


def _item_stat_parts(d: Mapping[str, Any]) -> List[str]:
    """装备详情词条行（批⑧ 注册表驱动：会心带符号 %、百分比键 +N%、等级键 LvN；
    0/非数值跳过——旧实现会把饰玉的 dfn:0 渲染成「防御 0」）。"""
    parts: List[str] = []
    for k in GEAR_NUMERIC_KEYS:
        v = d.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v == 0:
            continue
        iv = int(v)
        if k.endswith(PCT_SUFFIX):
            _base = GEAR_LABELS_ZH.get(k[: -len(PCT_SUFFIX)], k[: -len(PCT_SUFFIX)])
            parts.append(f"{_base} {'+' if iv > 0 else ''}{iv}%")
        elif k == "crit":
            parts.append(f"{GEAR_LABELS_ZH.get(k, k)} {'+' if iv > 0 else ''}{iv}%")
        elif k in ("earplug", "super_crit_lv", "elem_crit_lv"):
            parts.append(f"{GEAR_LABELS_ZH.get(k, k)} Lv{iv}")
        else:
            parts.append(f"{GEAR_LABELS_ZH.get(k) or _stat_name_zh(k)} {iv}")
    return parts


# ---------------------------------------------------------------------------
# /背包筛选：筛选链（框架 §7.4 L1336-1344 / 4f RUL-16 / TC-14）
# 语法：背包筛选 <物品类型> [类型 <子类目>] [品质 <品质>] [页码]
# 筛选链：物品类型 → 类型(子类目) → 品质，可叠加；结果 >5 条分页 5 条/页 + TPL-08
# ---------------------------------------------------------------------------

BAG_FILTER_CMD = "背包筛选"

# 物品大类判定（items.json type 键 → 大类键；用户 2026-08-27 拍板类型词体系：
# 装备/药剂/货币袋/材料/技能书/任务/其他）
_EQUIP_SLOT_KEYS = frozenset({
    "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
})
_CATEGORY_BY_TYPE = {
    **{k: "equip" for k in _EQUIP_SLOT_KEYS},
    "consumable": "consumable", "potion": "consumable", "medicine": "consumable",
    "material": "material", "ore": "material", "herb": "material",
    "quest": "quest",
    "currency": "currency", "coin": "currency", "bag": "currency",
    "skill_book": "skill_book", "scroll": "skill_book",
}
# 大类键 → 展示中文（当前页类型词；consumable 用户词「药剂」）
_CATEGORY_CN = {
    "equip": "装备", "consumable": "药剂", "material": "材料", "quest": "任务",
    "currency": "货币袋", "skill_book": "技能书", "other": "其他",
}
# 中文类型词 → 大类键（筛选匹配 + 校验；含别名：消耗品/药水 = 药剂类）
_TYPE_WORD_ALIASES = {
    "装备": "equip", "武器": "equip",
    "消耗品": "consumable", "药剂": "consumable", "药水": "consumable",
    "材料": "material", "素材": "material",
    "任务": "quest",
    "货币袋": "currency", "货币": "currency", "钱袋": "currency",
    "技能书": "skill_book",
    "其他": "other",
}
# 物品类型词表（语料兜底：未知大类词 → 不匹配，展示原分类）
_CATEGORY_WORDS = frozenset(_TYPE_WORD_ALIASES) | frozenset(_CATEGORY_CN.values())


def _item_def(ctx: Mapping[str, Any], item_id: str) -> Optional[Mapping[str, Any]]:
    """items.json 物品定义（ctx[\"items\"]；非 Mapping/缺 id → None）。"""
    if not item_id:
        return None
    items = ctx.get("items")
    if isinstance(items, Mapping):
        d = items.get(item_id)
        if isinstance(d, Mapping):
            return d
    return None


def _row_type_key(row: Any, ctx: Mapping[str, Any], f: Mapping[str, Any]) -> str:
    """物品子类键（type）：row 直接字段优先 → items.json 定义兜底。"""
    if isinstance(row, Mapping):
        t = row.get("type")
        if t:
            return str(t)
    else:
        t = getattr(row, "type", None)
        if t:
            return str(t)
    d = _item_def(ctx, f["item_id"])
    if d is not None:
        return str(d.get("type") or "")
    return ""


def _item_category(type_key: str) -> str:
    """子类键 → 大类键（框架 §7.4 物品类型；未知 → other）。"""
    return _CATEGORY_BY_TYPE.get(type_key, "other")


def _category_key(word: str) -> str:
    """中文类型词 → 大类键（别名归一：消耗品/药水/药剂 均 → consumable；非中文原样）。"""
    return _TYPE_WORD_ALIASES.get(word, word)


def _quality_key(word: str) -> Optional[str]:
    """品质词 → 内部键（中文标签或直接键；未知 → None）。"""
    if word in QUALITY_LABELS:
        return word
    rev = {v: k for k, v in QUALITY_LABELS.items() if v}
    return rev.get(word)


def _subtype_match(word: str, type_key: str) -> bool:
    """子类词匹配：直接键（weapon）或中文部位名（武器）。"""
    if not word:
        return True
    if word == type_key:
        return True
    return DEFAULT_SLOT_NAMES.get(type_key) == word


def _parse_filter_args(args: List[str]) -> Tuple[str, Optional[str], Optional[str], int]:
    """解析筛选链参数 → (物品类型词, 子类词, 品质词, 页码)。

    语法（框架 §7.4）：`<物品类型> [类型 <子类目>] [品质 <品质>] [页码]`；
    末尾纯数字 = 页码；其余按「类型/品质」键值对解析，裸词按 品质→子类 容错。
    """
    if not args:
        return "", None, None, 1
    page = 1
    if args[-1].isdigit():
        page = int(args[-1])
        args = args[:-1]
    if not args:
        return "", None, None, page
    cat_word = args[0]
    sub_word: Optional[str] = None
    qual_word: Optional[str] = None
    rest = args[1:]
    i = 0
    while i < len(rest):
        w = rest[i]
        if w in ("类型", "子类") and i + 1 < len(rest):
            sub_word = rest[i + 1]
            i += 2
        elif w == "品质" and i + 1 < len(rest):
            qual_word = rest[i + 1]
            i += 2
        elif qual_word is None and _quality_key(w) is not None:
            qual_word = w
            i += 1
        elif sub_word is None:
            sub_word = w
            i += 1
        else:
            i += 1  # 无法识别的词跳过（不阻断）
    return cat_word, sub_word, qual_word, page


def _filter_inventory_rows(rows: Sequence[Any], ctx: Mapping[str, Any],
                           cat_word: str, sub_word: Optional[str],
                           qual_word: Optional[str]) -> List[Any]:
    """筛选链逐级过滤（物品类型 → 子类 → 品质 可叠加）。"""
    out: List[Any] = []
    for r in rows:
        f = _row_fields(r, ctx)
        type_key = _row_type_key(r, ctx, f)
        if cat_word and _category_key(cat_word) != _item_category(type_key):
            continue
        if sub_word and not _subtype_match(sub_word, type_key):
            continue
        if qual_word:
            qk = _quality_key(qual_word)
            if qk is None or f["quality"] != qk:
                continue
        out.append(r)
    return out


def _render_rows_page(ctx: Mapping[str, Any], rows: Sequence[Any], cmd: str,
                      page: int, category_word: str = "全部") -> str:
    """通用列表分页渲染（5 条/页 + 用户 /背包 尾段：货币/当前页(类型词)/Tip + 裁决② 夹取；空 → TPL_EMPTY_BAG）。"""
    if not rows:
        return tpl_of(ctx, "basic_empty_bag")
    res = resolve_page(page, len(rows), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_rows = rows[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [bag_line(start + i + 1, r, ctx) for i, r in enumerate(slice_rows)]
    lines.extend(_bag_tail_lines(res.page, res.total_pages, res.total, res.clamped, ctx,
                                 category_word=category_word))
    return "\n".join(lines)


def cmd_bag_filter(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/背包筛选 <物品类型> [类型 <子类目>] [品质 <品质>] [页码]：筛选链（4f RUL-16）。

    物品类型（装备/消耗品/材料/任务/其他）→ 类型(子类目) → 品质 可叠加过滤；
    结果 >5 条分页 5 条/页 + TPL-08 + 裁决② 夹取；空筛选 → TPL_EMPTY_BAG。
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    # 裁决②：尾随数字页码 0/负数 → TPL-12（非数字保留为筛选词容错，见 _parse_filter_args）
    if args:
        last = args[-1]
        if last.isdigit() and int(last) < 1:
            return format_tpl12(_fragment(parsed))
        if len(last) > 1 and last[0] == "-" and last[1:].isdigit():
            return format_tpl12(_fragment(parsed))
    cat_word, sub_word, qual_word, page = _parse_filter_args(args)
    if not cat_word:
        # 缺物品类型词 → 提示用法（值域/用法问题，非 TPL-12 指令错误；对齐 4f 提示风；
        # 模板配置化：basic_filter_hint）
        return tpl_of(ctx, "basic_filter_hint")
    if cat_word not in _CATEGORY_WORDS:
        return tpl_of(ctx, "basic_filter_unknown", {"word": cat_word})
    rows = _filter_inventory_rows(_inventory_rows(ctx), ctx, cat_word, sub_word, qual_word)
    return _render_rows_page(ctx, rows, BAG_FILTER_CMD, page, category_word=cat_word)


# ---------------------------------------------------------------------------
# /装备：装备栏（5 条/页 + TPL-08 + 裁决②）/ 切换（穿 <序号> / 卸 <槽位>）
# ---------------------------------------------------------------------------

def _slot_order(ctx: Mapping[str, Any]) -> List[str]:
    """槽位顺序：ctx["slot_order"] 覆盖；slots.json 包装形态 {"slots":{...}} 取键序；
    缺省武器+五部位（4b §3.1，P2-8 修复对齐 EquipmentEngine 构造形态）。"""
    order = ctx.get("slot_order")
    if isinstance(order, (list, tuple)) and order:
        return [str(s) for s in order]
    slots = ctx.get("slots")
    if isinstance(slots, Mapping) and "slots" in slots and isinstance(slots["slots"], Mapping):
        keys = list(slots["slots"].keys())
        if keys:
            return [str(s) for s in keys]
    return list(DEFAULT_SLOT_ORDER)


def _slot_name(ctx: Mapping[str, Any], slot_id: str) -> str:
    """槽位 id → 中文名（ctx["slots"] 配置优先，含包装形态 {"slots":{...}}；缺省兜底表）。"""
    slots = ctx.get("slots")
    if isinstance(slots, Mapping):
        if "slots" in slots and isinstance(slots["slots"], Mapping):
            slots = slots["slots"]  # P2-8 修复：包装形态取内层
        d = slots.get(slot_id)
        if isinstance(d, Mapping) and d.get("name"):
            return str(d["name"])
        if d is not None and hasattr(d, "get"):
            n = d.get("name")
            if n:
                return str(n)
    return DEFAULT_SLOT_NAMES.get(slot_id, slot_id)


def _equipment_map(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """玩家装备栏（ctx["equipment"] → ctx["player"].equipment 兜底）。"""
    eq = ctx.get("equipment")
    if eq is None:
        player = ctx.get("player")
        if player is not None:
            eq = getattr(player, "equipment", None)
    return eq if isinstance(eq, Mapping) else {}


def _slot_info(slot: Any) -> Optional[Mapping[str, Any]]:
    """槽位实例归一（EquipmentSlot dataclass / dict）；空槽 → None。"""
    if slot is None:
        return None
    if isinstance(slot, Mapping):
        if not slot.get("item_id") and not slot.get("name"):
            return None
        return {
            "item_id": str(slot.get("item_id") or ""),
            "name": str(slot.get("name") or slot.get("item_id") or "?"),
            "enhance": int(slot.get("slot_level", slot.get("enhance", 0)) or 0),
            "locked": bool(slot.get("locked")),
        }
    item_id = getattr(slot, "item_id", None)
    name = getattr(slot, "name", None)
    if not item_id and not name:
        return None
    return {
        "item_id": str(item_id or ""),
        "name": str(name or item_id or "?"),
        "enhance": int(getattr(slot, "slot_level", 0) or 0),
        "locked": bool(getattr(slot, "locked", False)),
    }


def equip_line(slot_id: str, slot: Any, ctx: Mapping[str, Any]) -> Optional[str]:
    """装备栏行（意见一同步：去序号）：`武器：铁剑 +3`；空槽（部位没有装备）→ None
    （空槽不显示，由 _render_equip_page 过滤）。"""
    slot_name = _slot_name(ctx, slot_id)
    info = _slot_info(slot)
    if info is None:
        return None
    line = tpl_of(ctx, "basic_equip_line", {"slot": slot_name, "name": info["name"]})
    if info["enhance"]:
        line += tpl_of(ctx, "basic_equip_enh", {"enhance": info["enhance"]})
    return line


def _render_equip_page(ctx: Mapping[str, Any], page: int = 1) -> str:
    """/装备 正文（意见一同步：不加翻页）：头部 `【装备】` + 非空槽位一行一个 + Tip。

    空槽（部位没有装备）不显示；一次性展示全部已装备槽位（无页码/夹取尾段，
    不翻页）；`page` 参数保留仅兼容旧整数参数路径，实际不再分页。
    """
    order = _slot_order(ctx)
    eq = _equipment_map(ctx)
    # 槽位视图 = 顺序槽位全集；ctx 内额外槽位追加（内容包自定义部位 EQP-04）
    items = list(order)
    for sid in eq:
        if sid not in items:
            items.append(sid)
    lines: List[str] = [tpl_of(ctx, "basic_equip_header")]
    for sid in items:
        ln = equip_line(sid, eq.get(sid), ctx)
        if ln:
            lines.append(ln)
    lines.append(f"Tip:{tpl_of(ctx, 'tip_equip')}")
    return "\n".join(lines)


def resolve_equip_slot(ctx: Mapping[str, Any], arg: object) -> Optional[str]:
    """槽位参数 → slot_id（槽位 id / 中文名 / 序号）；找不到 → None（值域文案，工程补白 4）。"""
    if arg is None:
        return None
    s = str(arg)
    order = _slot_order(ctx)
    if s in order:
        return s
    for sid in order:
        if _slot_name(ctx, sid) == s:
            return sid
    n = parse_int(s)
    if n is not None and 1 <= n <= len(order):
        return order[n - 1]
    return None


# 引擎拒绝 reason → 模板 key（模板配置化 2026-08-31；basic_equip_reason_* 可内容包覆盖）
_EQUIP_REASON_KEYS: Mapping[str, str] = {
    "slot_mismatch": "basic_equip_reason_slot_mismatch",
    "mutual_exclusion": "basic_equip_reason_mutual_exclusion",
    "empty_slot": "basic_equip_reason_empty_slot",
    "in_battle": "basic_equip_reason_in_battle",
    "item_not_found": "basic_equip_reason_item_not_found",
    "unknown_slot": "basic_equip_reason_unknown_slot",
    "max_reached": "basic_equip_reason_max_reached",
}


class EquipmentEngineAdapter:
    """真实 EquipmentEngine 适配层（EQP-12 / D1 P1-5 ③：/装备 命令换真实引擎）。

    实现本模块文件头声明的消费接口 equip_wear(index, ctx) / equip_remove(slot_id, ctx)
    -> {ok, message}（对齐 FakeEquipEngine 替身签名，不破坏既有测试注入路径）：
      - 从 ctx 解析玩家（ctx["player"] 可变 dict）与背包（player["inventory"] 元素
        ItemInstance，含 item_id/type(slot)/name/stats_bonus 等）；
      - 调用 core.equipment.EquipmentEngine.equip(player, item, slot) / unequip(player, slot)；
      - 就地更新 ctx["player"]（引擎直接改 equipment/inventory/attributes）；
      - 组装中文消息（✅/❌ + 人话，对齐 EQP-E1~E5 边界文案：这个位置穿不上/互斥冲突/
        该槽位没有装备/战斗中不可更换装备（战前换装））。
    装配层注入 ctx["equip_engine"] = 适配器；本类亦为懒加载兜底（_equip_engine）。

    【工程补白】
      1) equip_wear 的目标槽位取 ItemInstance.slot（可装备槽位类型，data/item.py L34；
         与 EquipmentEngine EQP-02 部位匹配口径一致）。
      2) 失败消息以引擎 message 透传（引擎已按 EQP-E1~E5 合成人话），reason 兜底防漏。
      3) 玩家状态缺失（未注册/未建档）→ 明确提示先 /注册。
    """

    def __init__(
        self,
        slots: Optional[Any] = None,
        mutual_exclusions: Optional[Sequence[Sequence[str]]] = None,
        engine: Optional[EquipmentEngine] = None,
    ) -> None:
        """构造适配器（引擎可注入覆盖；否则以 slots 配置构造真实 EquipmentEngine）。"""
        self._engine = engine if engine is not None else EquipmentEngine(
            slots=slots, mutual_exclusions=mutual_exclusions,
        )

    @staticmethod
    def _player(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
        p = ctx.get("player")
        if isinstance(p, MutableMapping):
            return p
        # 装配层 make_context 注入 Player dataclass（2026-08-28 部署实测）——
        # asdict 转可变 dict 并写回 ctx（引擎就地修改 + 落档 dict 转换兼容）。
        if isinstance(p, Player):
            import dataclasses  # noqa: PLC0415

            d = dataclasses.asdict(p)
            if isinstance(ctx, MutableMapping):
                ctx["player"] = d
                # M12.5/veinborn kill_count 落档断链：asdict 深拷贝切断 ctx 共享键
                # （longline_counters/currencies 等）与 player 子结构的引用——战斗写
                # ctx["longline_counters"] 落在旧对象上，落档（读 d["longline_counters"]）
                # 拿空。asdict 后重挂 ctx 共享键 → 新 dict 子结构（就地改 = 落档保留）。
                for _k in ("longline_counters", "currencies", "event_counts",
                           "quest_active", "quest_completed", "quest_daily",
                           "reputation_state", "codex_state", "title_state"):
                    _sub = d.get(_k)
                    if isinstance(_sub, MutableMapping) and _k in ctx:
                        ctx[_k] = _sub
            return d
        return None

    @staticmethod
    def _sorted_inventory(player: MutableMapping[str, Any]) -> list:
        """背包行展示序（P1-2 修复，M6 批1B 审查）：与 /背包 _inventory_rows 同口径——
        按 acquired_at 倒序（RUL-17），无时间字段保持存储序（稳定排序）。适配层按此序
        取穿装序号，避免「/背包 显示第 N 件」与「穿第 N 件」错位。"""
        inv = player.get("inventory")
        if not isinstance(inv, (list, tuple)):
            return []
        rows = list(inv)

        def _key(r: Any) -> str:
            if isinstance(r, Mapping):
                t = r.get("acquired_at")
                return str(t) if t is not None else ""
            return str(getattr(r, "acquired_at", "") or "")

        try:
            return sorted(rows, key=_key, reverse=True)
        except TypeError:  # 混合类型时间字段 → 保持原序
            return rows

    def equip_wear(self, index: int, ctx: MutableMapping[str, Any]) -> dict:
        """装备背包第 index 件（1 起，按 /背包 展示序=acquired_at 倒序）；返回 {ok, message, ...}。

        模板配置化 2026-08-31：消息走 basic_equip_* 模板（basic_equip_no_player / no_item /
        not_equippable / no_slot / ok / replaced / fail），内容包可覆盖同 key。
        """
        player = self._player(ctx)
        if player is None:
            return {"ok": False, "message": tpl_of(ctx, "basic_equip_no_player")}
        sorted_inv = self._sorted_inventory(player)
        if not (1 <= index <= len(sorted_inv)):
            return {"ok": False, "message": tpl_of(ctx, "basic_equip_no_item")}
        item = sorted_inv[index - 1]
        # M12.5/veinborn 收口：装配层 Player dataclass asdict 后 inventory 为
        # list[dict]（_player 静态转换），引擎契约须 ItemInstance——dict 形态归一
        # 转换（字段与 ItemInstance 对齐；非 dict 保持原样走 isinstance 判定）。
        if isinstance(item, Mapping):
            try:
                _sb = item.get("stats_bonus")
                item = ItemInstance(
                    item_id=str(item.get("item_id") or ""),
                    name=str(item.get("name") or ""),
                    count=int(item.get("count", 1)),
                    quality=str(item.get("quality") or "normal"),
                    bound=bool(item.get("bound", False)),
                    slot=str(item.get("slot")) if item.get("slot") else None,
                    stats_bonus=dict(_sb) if isinstance(_sb, Mapping) else {},
                    traits=tuple(item.get("traits") or ()),
                    enhance_level=int(item.get("enhance_level", 0) or 0),
                )
            except (TypeError, ValueError):
                pass
        if not isinstance(item, ItemInstance):
            return {"ok": False, "message": tpl_of(ctx, "basic_equip_not_equippable")}
        if not item.slot:
            return {"ok": False, "message": tpl_of(ctx, "basic_equip_no_slot")}
        # dict 归一后写回 sorted 列表对应的背包实例，引擎 _inv 定位同一性需要
        # （引擎按 r is item or r == item 找背包行——asdict dict 与原 ItemInstance
        # 相等性成立但同一性失败；直接改背包列表对应位为归一实例）
        player["inventory"] = [
            item if (r is sorted_inv[index - 1]) else r for r in player["inventory"]
        ]
        res = self._engine.equip(player, item, item.slot)
        if res.get("ok"):
            msg = tpl_of(ctx, "basic_equip_ok", {"name": item.name})
            if res.get("replaced"):
                msg += tpl_of(ctx, "basic_equip_replaced")
            return {"ok": True, "message": msg, "slot": item.slot, **res}
        return {"ok": False, "message": self._fail_message(ctx, res, "basic_equip_fail_wear")}

    def equip_remove(self, slot_id: str, ctx: MutableMapping[str, Any]) -> dict:
        """卸下槽位装备；返回 {ok, message, ...}。"""
        player = self._player(ctx)
        if player is None:
            return {"ok": False, "message": tpl_of(ctx, "basic_equip_no_player")}
        old = None
        equipment = player.get("equipment")
        if isinstance(equipment, Mapping):
            old = equipment.get(slot_id)
        res = self._engine.unequip(player, slot_id)
        if res.get("ok"):
            old_name = ""
            if old is not None:
                old_name = str(getattr(old, "name", "") or "")
                if not old_name and isinstance(old, Mapping):
                    old_name = str(old.get("name") or "")
            item_id = str(res.get("item_id") or "")
            return {"ok": True, "message": tpl_of(ctx, "basic_equip_remove_ok",
                                                 {"name": old_name or item_id}), **res}
        return {"ok": False, "message": self._fail_message(ctx, res, "basic_equip_fail_remove")}

    @staticmethod
    def _fail_message(ctx: Mapping[str, Any], res: Mapping[str, Any], fallback_key: str) -> str:
        """引擎拒绝 → ❌ 文案（message 透传；缺省按 reason 兜底人话，模板配置化 basic_equip_*）。

        fallback_key = 无匹配 reason 时的兜底模板 key（basic_equip_fail_wear / _remove）。
        """
        msg = res.get("message")
        if msg:
            return tpl_of(ctx, "basic_equip_fail", {"msg": msg})
        reason = str(res.get("reason") or "")
        key = _EQUIP_REASON_KEYS.get(reason, fallback_key)
        return tpl_of(ctx, "basic_equip_fail", {"msg": tpl_of(ctx, key, {})})


_logger = get_logger("basic_commands.equip")


def _equip_engine(ctx: Mapping[str, Any]) -> Any:
    """装备引擎解析（注入优先 → 懒加载真实 EquipmentEngine 适配层（EQP-12）；均不可得 →
    【待接线】RuntimeError，与 checkin_commands 同模式，工程补白 9）。

    - ctx["equip_engine"] 注入优先（装配层/测试注入适配器或替身，equip_wear/equip_remove 消费接口）；
    - 未注入 → importlib 守卫导入 qbot_rpg.core.equipment（路A 已实装）后构造
      EquipmentEngineAdapter（slots 配置取自 ctx["slots"]）——懒加载路径。
    """
    eng = ctx.get("equip_engine")
    if eng is not None:
        return eng
    try:
        importlib.import_module("qbot_rpg.core.equipment")
        return EquipmentEngineAdapter(slots=ctx.get("slots"))
    except Exception as exc:  # ModuleNotFoundError / ImportError / 构造失败
        raise RuntimeError(
            "【待接线】core/equipment.py（M6 批1 已实装 EquipmentEngine + 适配层）装备引擎不可用；"
            "装配时注入 ctx['equip_engine']（equip_wear/equip_remove 消费接口）"
        ) from exc



def _cmd_equip_remove(ctx: Mapping[str, Any], slot_id: str) -> str:
    """/装备 卸 <槽位>：卸下槽位装备（引擎 equip_remove，消息透传）。"""
    engine = _equip_engine(ctx)
    try:
        res = engine.equip_remove(slot_id, ctx)
    except Exception as exc:  # P2-3 修复：裸吞异常留日志（防故障不可诊断）
        _logger.exception("equip_remove 异常（slot=%s）: %s", slot_id, exc)
        res = {}
    return str(res.get("message") or tpl_of(ctx, "basic_equip_remove_fail"))


def cmd_equip(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/装备 [参数] 主入口（4b §三 装备穿戴；意见一同步：不加翻页）：

      无参 / <整数>    → 装备栏一次性展示全部已装备槽位（头部【装备】；空槽不显示；
                        整数页码忽略不再翻页）
      穿 <序号>       → 切换穿戴背包第 N 件（引擎）
      卸 <槽位>       → 卸下槽位装备（槽位名/id/序号；解析失败 → 值域文案 TPL_NO_SLOT）
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return _render_equip_page(ctx, 1)
    first = str(args[0])
    if first == SUB_REMOVE:
        slot_arg = args[1] if len(args) > 1 else None
        if slot_arg is None or len(args) > 2:
            return format_tpl12(_fragment(parsed))
        sid = resolve_equip_slot(ctx, slot_arg)
        if sid is None:
            return tpl_of(ctx, "basic_no_slot")
        return _cmd_equip_remove(ctx, sid)
    # 名称形式（非数字非子词，如 /装备 铁剑）→ 友好提示引导序号（P2-11 QA；命令合法，
    # 不走 TPL-12，对齐 TPL_NO_SLOT 值域文案口径；模板配置化：basic_equip_name_hint）
    if parse_int(first) is None:
        return tpl_of(ctx, "basic_equip_name_hint")
    # 整数 = 页码（0/负数 → parse_page_arg None → TPL-12，保留裁决②）
    page = parse_page_arg(first)
    if page is None:
        return format_tpl12(_fragment(parsed))
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    return _render_equip_page(ctx, page)


# ---------------------------------------------------------------------------
# /技能：技能列表（LV 行固定头部 + 类型/MP/描述 + 派生指向「可派生成：XX」）
# ---------------------------------------------------------------------------


def cmd_unequip(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """卸下 <部位|序号>：卸除指定部位装备（2026-09-06 独立词，转发 装备 卸 逻辑）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "unequip_usage")
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    sid = resolve_equip_slot(ctx, str(args[0]))
    if sid is None:
        return tpl_of(ctx, "basic_no_slot")
    return _cmd_equip_remove(ctx, sid)


def _skill_def(ctx: Mapping[str, Any], sid: str) -> Any:
    """技能定义解析（ctx["skills"] 映射 / resolve_skill 解析器）；查无 → None。"""
    if not sid:
        return None
    skills = ctx.get("skills")
    if isinstance(skills, Mapping):
        d = skills.get(sid)
        if d is not None:
            return d
    resolver = ctx.get("resolve_skill")
    if callable(resolver):
        try:
            return resolver(sid)
        except Exception:
            return None
    return None


def _skill_name(ctx: Mapping[str, Any], sid: str) -> str:
    """技能 id → 显示名（定义 name 冗余；查无 → id 原样）。"""
    d = _skill_def(ctx, sid)
    if d is None:
        return sid
    if isinstance(d, Mapping):
        return str(d.get("name") or sid)
    n = getattr(d, "name", None)
    return str(n or sid)


def _skill_field(defn: Any, key: str, default: Any = None) -> Any:
    """技能定义字段取值（Mapping / Def.get 双兼容）。"""
    if isinstance(defn, Mapping):
        return defn.get(key, default)
    if defn is not None and hasattr(defn, "get"):
        try:
            return defn.get(key, default)
        except Exception:
            return default
    return default


def _chain_def(ctx: Mapping[str, Any], cid: str) -> Any:
    """派生链定义解析（ctx["skill_chains"] 映射 / resolve_chain 解析器）；查无 → None。"""
    if not cid:
        return None
    chains = ctx.get("skill_chains")
    if isinstance(chains, Mapping):
        d = chains.get(cid)
        if d is not None:
            return d
    resolver = ctx.get("resolve_chain")
    if callable(resolver):
        try:
            return resolver(cid)
        except Exception:
            return None
    return None


def _derived_names(ctx: Mapping[str, Any], sid: str, chain_refs: Sequence[Any]) -> List[str]:
    """派生指向（1c2 派生链 + 6a F14 chain_refs）：链 steps[].from == sid → steps[].to 技能名。"""
    out: List[str] = []
    seen: set = set()
    for ref in chain_refs or ():
        cid = str(ref)
        chain = _chain_def(ctx, cid)
        if chain is None:
            continue
        steps = _skill_field(chain, "steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            if str(step.get("from") or "") != sid:
                continue
            # 连段计数段过滤（2026-09-09：sword_flow 恰等=连用第 N 连形态，非派生）
            _c0 = step.get("condition")
            if isinstance(_c0, Mapping):
                _sm0 = _c0.get("self_marks")
                if isinstance(_sm0, Mapping) and "sword_flow" in _sm0:
                    _v0 = _sm0["sword_flow"]
                    if isinstance(_v0, Mapping) and _v0.get("min") is not None \
                            and int(_v0.get("max", _v0["min"])) == int(_v0["min"]):
                        continue
            to_id = step.get("to")
            if not to_id:
                continue
            to_id = str(to_id)
            if to_id in seen:
                continue
            seen.add(to_id)
            out.append(_skill_name(ctx, to_id))
    return out


def _derived_tags(defn: Any) -> List[str]:
    """按技能机制推导标签（**仅兜底**：内容包 `brief` 为空时使用；自由文本以 brief 为准）。"""
    tags: List[str] = []
    kind = str(_skill_field(defn, "kind", "") or "")
    if kind == "damage" or _skill_field(defn, "power", 0):
        tags.append("damage")
    if (int(_skill_field(defn, "mp_cost", 0) or 0) > 0
            or bool(_skill_field(defn, "consume_marks", None))
            or bool(_skill_field(defn, "energy_cost", None))):
        tags.append("cost")
    if str(_skill_field(defn, "tag", "") or "") == "combo":
        tags.append("combo")
    if _skill_field(defn, "chain_refs", None):
        tags.append("derive")
    if _skill_field(defn, "air_policy", None):
        tags.append("air")
    _ctr = str(_skill_field(defn, "counter_type", "") or "")
    if _ctr == "dodge":
        tags.append("dodge")
    elif _ctr == "parry":
        tags.append("parry")
    _eff = [str((e.get("type") or e.get("effect")) or "")
            for e in (_skill_field(defn, "effects", None) or ()) if isinstance(e, Mapping)]
    if "reposition" in _eff:
        tags.append("move")
    if _skill_field(defn, "break_power", None):
        tags.append("part")
    if int(_skill_field(defn, "hits", 1) or 1) > 1:
        tags.append("multi")
    if _skill_field(defn, "armor", False):
        tags.append("armor")
    if _skill_field(defn, "interrupt", False):
        tags.append("interrupt")
    return [_SKILL_TAG_LABELS[t] for t in _SKILL_TAG_ORDER if t in tags]


def skill_brief(ctx: Mapping[str, Any], sid: str) -> str:
    """技能简述行（列表用）：内容包 `brief` 自由文本（编辑器「简述」文本框）→ 兜底机制标签。

    2026-09-12 用户拍板：标签是**文本类型**，后续由内容作者自定义；本函数只负责取值与兜底。
    """
    defn = _skill_def(ctx, sid)
    brief = _skill_field(defn, "brief", None)
    if isinstance(brief, str) and brief.strip():
        return brief.strip()
    return "".join(_derived_tags(defn))


def skill_line(index: int, sid: str, ctx: Mapping[str, Any]) -> str:
    """技能行（2026-09-12 用户样稿）：`{序号}. {名称}（{类型}）` + 简述行 + 分隔线。

    样稿形态：
        6. 御剑·回收（主动）
        【机动】【回收】
        ————
    简述 = 内容包 `brief`（自由文本）；缺省按机制兜底标签。模板：
    basic_skill_row / basic_skill_brief / basic_skill_sep（内容包可覆盖）。
    """
    defn = _skill_def(ctx, sid)
    name = _skill_name(ctx, sid)
    type_label = TYPE_LABELS.get(str(_skill_field(defn, "type", "active")), "主动")
    parts: List[str] = [tpl_of(ctx, "basic_skill_row",
                               {"idx": index, "name": name, "type": type_label})]
    brief = skill_brief(ctx, sid)
    if brief:
        parts.append(tpl_of(ctx, "basic_skill_brief", {"brief": brief}))
    sep = tpl_of(ctx, "basic_skill_sep")
    if sep:
        parts.append(sep)
    return "\n".join(parts)


def _job_visible(ctx: Mapping[str, Any], sid: str) -> bool:
    """技能对当前职业可见性（6a §4.3 装配过滤：job_restrict 空=通用；非空须含当前职业）。"""
    job_id = str(_player_fields(ctx)["job_id"])
    restrict = _skill_field(_skill_def(ctx, sid), "job_restrict", None)
    if isinstance(restrict, (list, tuple)) and restrict:
        return job_id in {str(r) for r in restrict}
    return True


def skill_rows(ctx: Mapping[str, Any]) -> List[str]:
    """当前职业可见技能 id 列表（job_restrict 过滤 + type 排序 basic→active→passive→trigger，
    6a §1.5 普攻固定第 1 位；工程补白 5）。placeholder:true 技能（如 transform.skill_set
    引用的技能组占位容器）不显示（2026-09-03：占位条目误入玩家技能列表）。"""
    skills = ctx.get("skills")
    ids: List[str] = []
    if isinstance(skills, Mapping):
        ids = [str(k) for k in skills.keys()]
    else:
        resolver = ctx.get("resolve_skill")
        ids = list(ctx.get("skill_ids") or ()) if callable(resolver) else []
    order_map = {"basic": 0, "active": 1, "passive": 2, "trigger": 3}

    def _key(sid: str) -> tuple:
        t = str(_skill_field(_skill_def(ctx, sid), "type", "active"))
        return (order_map.get(t, 4), sid)

    def _placeholder(sid: str) -> bool:
        # 1) 被任意 job transform.skill_set 引用为「技能组容器」的占位技能
        #    （2026-09-03：mastery_skills 类占位条目误入玩家技能列表）
        jobs = ctx.get("jobs")
        if isinstance(jobs, Mapping):
            for _jd in jobs.values():
                _jd_raw = _jd if isinstance(_jd, Mapping) else getattr(_jd, "raw", None)
                if isinstance(_jd_raw, Mapping):
                    _t = _jd_raw.get("transform")
                    if isinstance(_t, Mapping) and str(_t.get("skill_set") or "") == sid:
                        return True
        return False

    def _usable_now(sid: str) -> bool:
        # 2026-09-05 用户需求：技能列表只显示「可以使用」的技能：
        #  - job_form 非空 = 形态专属技（战斗形态中才可用；列表为非战斗常态查看
        #    → 隐藏，形态中技能经技能面板/派生另行呈现）
        #  - derive_only=True = 派生专属技（战斗中经派生获得 → 隐藏）
        #  - placeholder = 技能组占位容器（既有 _placeholder）
        _d = _skill_def(ctx, sid)
        if _skill_field(_d, "job_form", None):
            return False
        if _skill_field(_d, "derive_only", False):
            return False
        return True

    visible = [sid for sid in ids
               if _job_visible(ctx, sid) and not _placeholder(sid)
               and _usable_now(sid)]
    visible.sort(key=_key)
    return visible


def _render_skill_page(ctx: Mapping[str, Any], page: int) -> str:
    """/技能 正文：LV 行固定头部 + 技能行 5 条/页 + TPL-08 + 裁决② 夹取。"""
    sids = skill_rows(ctx)
    res = resolve_page(page, len(sids), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_ids = sids[start:start + DEFAULT_PAGE_SIZE]
    f = _player_fields(ctx)
    job = str(ctx.get("job_name") or _job_name(ctx, f["job_id"]) or "?")
    lines: List[str] = [
        tpl_of(ctx, "basic_skill_header",
               {"level": f["level"], "name": f["name"], "job": job}),
    ]
    # 2026-09-12 用户拍板：**普攻（type=basic）不出现在技能列表**——行内跳过，
    # 但分页与序号仍按完整列表计（技能详情 <序号> / 攻击 <序号> 口径不变）。
    for i, sid in enumerate(slice_ids):
        if str(_skill_field(_skill_def(ctx, sid), "type", "active")) == "basic":
            continue
        lines.append(skill_line(start + i + 1, sid, ctx))
    if sids:
        lines.append(_cake_tail(res.page, res.total_pages, tip=tpl_of(ctx, "tip_skill"),
                                clamped=res.clamped,
                                templates=ctx.get("templates")))
    return "\n".join(lines)


def cmd_skill(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/技能 [页码]：技能列表（LV 行固定头部 + 类型/MP/描述 + 派生指向「可派生成：XX」；
    5 条/页 + TPL-08 + 裁决② 夹取；0/负数/非数字 → TPL-12）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_skill_page(ctx, page)


# ---------------------------------------------------------------------------
# /帮助：分组目录（5 组单页 / GM 6 组 2 页）+ 组页指令列表（5 条/页）+ 注册引导版（B6）
# ---------------------------------------------------------------------------



def _resolve_skill_arg(ctx: Mapping[str, Any], arg: str) -> Optional[str]:
    """技能详情/派生参数解析：序号（技能列表序）→ 名称 → job 限定名；查无 → None。"""
    sids = skill_rows(ctx)
    if arg.isdigit():
        n = int(arg)
        if 1 <= n <= len(sids):
            return sids[n - 1]
        return None
    # 名称匹配（含从技能全表查——形态/派生技不在列表但可查详情）
    all_ids = list(ctx.get("skill_ids") or ())
    skills = ctx.get("skills")
    if isinstance(skills, Mapping):
        all_ids = list(skills.keys())
    for sid in all_ids:
        if sid == arg or _skill_name(ctx, sid) == arg:
            return sid
    return None


def cmd_skill_info(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """技能详情 <序号|名称>：完整技能信息面板（2026-09-05 新功能）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "skill_info_usage")
    sid = _resolve_skill_arg(ctx, str(args[0]))
    if sid is None:
        return tpl_of(ctx, "skill_info_not_found", {"name": str(args[0])})
    return _render_skill_info(ctx, sid)


def cmd_skill_chain(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """技能派生 <序号|技能名>：可派生技能及条件（2026-09-05 新功能）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "skill_chain_usage")
    sid = _resolve_skill_arg(ctx, str(args[0]))
    if sid is None:
        return tpl_of(ctx, "skill_chain_not_found", {"name": str(args[0])})
    return _render_skill_chain(ctx, sid)


def _mark_display_name(ctx: Mapping[str, Any], mid: str) -> str:
    """印记展示名（消耗行）：ctx["marks"] 定义 name → 回落 id（不臆造）。"""
    marks = ctx.get("marks")
    if isinstance(marks, Mapping):
        d = marks.get(mid)
        if isinstance(d, Mapping):
            return str(d.get("name") or mid)
        if d is not None:
            return str(d)
    return mid


def _render_skill_info(ctx: Mapping[str, Any], sid: str) -> str:
    """技能详情面板（2026-09-12 CTB 重写；模板 skill_info_* 可内容包覆盖）。

    CTB 口径（去回合制残留）：
      - 消耗：灵能 / 精力 / 印记（剑势·剑印等按定义名）+ 冷却（N 次行动）；
        **不再输出旧回合式的「每次行动限 N 次」**（trigger_limit 是引擎护栏，非玩家消耗）
      - 效果：威力 / 段数 / 破坏值 / 霸体 / 打断
      - **行动恢复**（recovery，CTB 核心数值：越大＝下一次行动来得越晚）
      - 派生指向（发 技能派生 查看条件）
      - 面板尾部文本 = 技能 def `detail`（编辑器「详情」文本框）→ 回落 `desc`
    行宽口径：结构化行 ≤14 全角；详情文本属介绍类，允许自然折行。
    """
    defn = _skill_def(ctx, sid)
    name = _skill_name(ctx, sid)
    lines = [tpl_of(ctx, "skill_info_header", {"name": name})]
    if defn is None:
        lines.append(tpl_of(ctx, "skill_info_not_found", {"name": sid}))
        return "\n".join(lines)
    # 类型
    t = str(_skill_field(defn, "type", "active"))
    lines.append(tpl_of(ctx, "skill_info_line", {"k": "类型", "v": TYPE_LABELS.get(t, t)}))
    # 标签（简述行同源：内容包 brief 自由文本 → 机制兜底）
    brief = skill_brief(ctx, sid)
    if brief:
        lines.append(tpl_of(ctx, "skill_info_line", {"k": "标签", "v": brief}))
    # 消耗（CTB：灵能 / 精力 / 印记 / 冷却行动数）
    costs: List[str] = []
    try:
        mp = int(_skill_field(defn, "mp_cost", 0))
        if mp > 0:
            costs.append(f"{mp} 灵能")
    except (TypeError, ValueError):
        pass
    _energy = _skill_field(defn, "energy_cost", None)
    if isinstance(_energy, Mapping):
        for k, v in _energy.items():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                costs.append(f"{_ENERGY_LABELS.get(str(k), str(k))} {n}")
    _consume = _skill_field(defn, "consume_marks", None)
    if isinstance(_consume, Mapping):
        for k, v in _consume.items():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                costs.append(f"{_mark_display_name(ctx, str(k))} {n}")
    cd = _skill_field(defn, "cooldown", 0)
    if cd:
        costs.append(f"冷却 {cd} 次行动")
    if costs:
        lines.append(tpl_of(ctx, "skill_info_line", {"k": "消耗", "v": "、".join(costs)}))
    # 效果（kind/power/段数/破坏值/霸体/打断）
    effs: List[str] = []
    kd = str(_skill_field(defn, "kind", ""))
    if kd:
        pw = _skill_field(defn, "power")
        effs.append(KIND_LABELS.get(kd, kd) + (f" 威力 {pw}" if pw else ""))
    hits = _skill_field(defn, "hits", 1)
    if hits and int(hits) > 1:
        effs.append(f"{hits} 段")
    bp = _skill_field(defn, "break_power", None)
    if bp:
        effs.append(f"破坏值 {bp}")
    if _skill_field(defn, "armor"):
        effs.append("霸体")
    if _skill_field(defn, "interrupt"):
        effs.append("打断")
    if effs:
        lines.append(tpl_of(ctx, "skill_info_line", {"k": "效果", "v": "、".join(str(e) for e in effs)}))
    # 行动恢复（CTB 核心：下一次行动的时间代价）
    rec = _skill_field(defn, "recovery", None)
    if rec:
        lines.append(tpl_of(ctx, "skill_info_line", {"k": "行动恢复", "v": rec}))
    # 派生指向
    chain_refs = _skill_field(defn, "chain_refs")
    if isinstance(chain_refs, (list, tuple)) and chain_refs:
        derived = _derived_names(ctx, sid, chain_refs)
        if derived:
            lines.append(tpl_of(ctx, "skill_info_line",
                                {"k": "派生", "v": "、".join(derived) + "（发 技能派生 查看条件）"}))
    # 详情文本（编辑器「详情」文本框 → 回落 desc）
    detail = _skill_field(defn, "detail", None)
    if not (isinstance(detail, str) and detail.strip()):
        detail = _skill_field(defn, "desc", None)
    if isinstance(detail, str) and detail:
        lines.append(detail)
    return "\n".join(lines)


def _render_skill_chain(ctx: Mapping[str, Any], sid: str) -> str:
    """技能派生面板：该技能可派生的技能 + 条件 + 效果变化。"""
    defn = _skill_def(ctx, sid)
    name = _skill_name(ctx, sid)
    chain_refs = _skill_field(defn, "chain_refs")
    lines = [tpl_of(ctx, "skill_chain_header", {"name": name})]
    found = False
    if isinstance(chain_refs, (list, tuple)):
        for ref in chain_refs:
            chain = _chain_def(ctx, str(ref))
            if chain is None:
                continue
            steps = _skill_field(chain, "steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                if str(step.get("from") or "") != sid:
                    continue
                found = True
                to_id = str(step.get("to") or "")
                to_name = _skill_name(ctx, to_id) if to_id else "?"
                # 条件（count 连用 N 次；tag 标签；marks/status/or——2026-09-09 扩展）
                cond_parts: List[str] = []
                cond = step.get("condition")

                def _mark_cn(mkid: str) -> str:
                    _tbl = ctx.get("marks") if isinstance(ctx.get("marks"), Mapping) else {}
                    _d = _tbl.get(str(mkid)) if isinstance(_tbl, Mapping) else None
                    return str(_d.get("name") or mkid) if isinstance(_d, Mapping) else str(mkid)

                def _status_cn(sid2: str) -> str:
                    _tbl = ctx.get("statuses") if isinstance(ctx.get("statuses"), Mapping) else {}
                    _d = _tbl.get(str(sid2)) if isinstance(_tbl, Mapping) else None
                    return str(_d.get("name") or sid2) if isinstance(_d, Mapping) else str(sid2)

                def _cond_cn(c: Mapping[str, Any]) -> List[str]:
                    parts: List[str] = []
                    cnt = c.get("count")
                    if cnt is not None:
                        if isinstance(cnt, Mapping) and cnt.get("eq") is not None:
                            parts.append(f"连用 {cnt['eq']} 次")
                        else:
                            parts.append(f"连用 {cnt} 次")
                    sm = c.get("self_marks")
                    if isinstance(sm, Mapping):
                        for mk, mv in sm.items():
                            if not isinstance(mv, Mapping):
                                continue
                            mn = mv.get("min")
                            mx = mv.get("max")
                            if mn is None:
                                continue
                            mkn = _mark_cn(str(mk))
                            if mx is not None and int(mx) == int(mn):
                                parts.append(f"{mkn} {mn}")
                            else:
                                parts.append(f"{mkn}≥{mn}")
                    ss = c.get("self_status")
                    if isinstance(ss, Mapping):
                        for s2 in ss.get("has") or ():
                            parts.append(f"姿态《{_status_cn(str(s2))}》")
                    tm = c.get("target_marks")
                    if isinstance(tm, Mapping):
                        for mk, mv in tm.items():
                            if isinstance(mv, Mapping) and mv.get("min") is not None:
                                parts.append(f"目标《{_mark_cn(str(mk))}》积累 {mv['min']}")
                    ors = c.get("or")
                    if isinstance(ors, list):
                        subs: List[str] = []
                        for o2 in ors:
                            if isinstance(o2, Mapping):
                                subs.extend(_cond_cn(o2))
                        if subs:
                            parts.append("或".join(subs))
                    return parts

                if isinstance(cond, Mapping):
                    # 连段计数段过滤（2026-09-09 实机：sword_flow 恰等 = 连用第 N 连
                    # 自动化形态，非印派生——派生面板不列连段段）
                    _sm0 = cond.get("self_marks")
                    if isinstance(_sm0, Mapping) and "sword_flow" in _sm0:
                        _v0 = _sm0["sword_flow"]
                        if isinstance(_v0, Mapping) and _v0.get("min") is not None \
                                and int(_v0.get("max", _v0["min"])) == int(_v0["min"]):
                            continue
                    cond_parts.extend(_cond_cn(cond))
                tag = step.get("tag")
                if tag and str(tag) != "none":
                    cond_parts.append(f"触发：{tag}")
                if not cond_parts:
                    cond_parts.append("满足条件")
                # 效果变化（mode 默认 replace 不展示；variant_override 展示）
                extra: List[str] = []
                vo = step.get("variant_override")
                if isinstance(vo, Mapping) and vo.get("power"):
                    extra.append(f"威力 {vo['power']}")
                if _skill_field(step, "armor"):
                    extra.append("霸体")
                ln = f"{to_name}（{'、'.join(cond_parts)}"
                if extra:
                    ln += "；" + "、".join(str(e) for e in extra)
                ln += "）"
                lines.append(ln)
    if not found:
        lines.append(tpl_of(ctx, "skill_chain_none", {}))
    return "\n".join(lines)


def _command_alias_display(ctx: Mapping[str, Any], name: str) -> str:
    """指令显示名别名替换（SHC-04 / 4f RUL-24 / 规范 6.7 L213-215）：

    消费 settings.command_aliases（形态对齐 parsers._normalize_aliases）：
      - {"锻造": "炼器"}（缺省 keep_original:true）→ 双名并显 `锻造/炼器`；
      - {"炼金": {"alias": "炼丹", "keep_original": false}} → 仅显别名 `炼丹`；
      - 无别名配置/原指令不在表 → 原指令名。
    """
    settings = ctx.get("settings")
    if not isinstance(settings, Mapping):
        return name
    aliases = settings.get("command_aliases")
    if not isinstance(aliases, Mapping):
        return name
    entry = aliases.get(name)
    if entry is None:
        return name
    if isinstance(entry, str):
        return f"{name}/{entry}"
    if isinstance(entry, Mapping):
        alias = entry.get("alias")
        if not alias:
            return name
        if entry.get("keep_original", True):
            return f"{name}/{alias}"
        return str(alias)
    return name


def _help_groups(ctx: Mapping[str, Any]) -> Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]:
    """分组目录：普通玩家 5 组；GM 追加第 6 组（B8/RUL-25，GM 判定 ctx["is_gm"]）。

    2026-09-05 模拟器审计动态化：装配层注入 ctx["registered_cmds"]（已注册非 stub
    指令名）时，组内指令按注册表过滤——未实装 stub（采集/强化/调合/快捷绑定等）与
    未注册词（合成等）不再出现在帮助里（玩家照帮助发出去不再是「尚未实装/指令不正确」）。
    无注入键（单测直调）→ 静态全表（兼容旧行为）。
    """
    groups = list(HELP_GROUPS)
    reg = ctx.get("registered_cmds")
    if isinstance(reg, (set, list, tuple)) and reg:
        groups = [
            (gname, tuple((cname, desc) for cname, desc in cmds if cname in reg))
            for gname, cmds in groups
        ]
        groups = [(gname, cmds) for gname, cmds in groups if cmds]
    if ctx.get("is_gm"):
        groups.append(GM_HELP_GROUP)
    return tuple(groups)


def _group_summary(ctx: Mapping[str, Any], group: Tuple[str, Tuple[Tuple[str, str], ...]]) -> str:
    """目录行（2026-08-31 用户拍板：`冒险 — 角色/背包/位置/任务`，单横线、去 `/帮助 组名` 后缀）。

    展示子集 _DIRECTORY_SHOW 优先（仅影响总览行，组页 /帮助 <组名> 仍显示完整指令集）；
    无子集 → 取组内前 5 条 + …。
    """
    name, cmds = group
    show = _DIRECTORY_SHOW.get(name)
    if show:
        names = list(show)
    else:
        names = [_command_alias_display(ctx, c[0]) for c in cmds]
    shown = "/".join(names[:5])
    if len(names) > 5:
        shown += "…"
    return tpl_of(ctx, "help_directory_row", {"group": name, "cmds": shown})


def _render_help_directory(ctx: Mapping[str, Any], page: int) -> str:
    """/帮助 目录：组摘要 5 条/页 + TPL-08 + 裁决② 夹取（普通玩家 5 组单页无页脚；GM 6 组 2 页）。"""
    groups = _help_groups(ctx)
    res = resolve_page(page, len(groups), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_groups = groups[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [tpl_of(ctx, "help_directory_title", {})]
    for i, g in enumerate(slice_groups):
        lines.append(_group_summary(ctx, g))
    if groups:
        # 2026-09-05 模拟器审计：目录仅 1 页时教「帮助2 翻页」是无效引导（普通玩家
        # 5 组 1 页；GM 6 组 2 页才需要）——单页渲染「发 帮助 <组名> 组内指令」
        # 引导（新手不知道组页存在，A 路审计）；多页才教翻页
        if (res.total_pages or 1) > 1:
            _dir_tip = tpl_of(ctx, "tip_help_dir")
        else:
            _dir_tip = tpl_of(ctx, "tip_help")
        lines.append(_cake_tail(res.page, res.total_pages, tip=_dir_tip, clamped=res.clamped,
                                templates=ctx.get("templates")))
    return "\n".join(lines)


def group_page_line(index: int, cmd: Tuple[str, str], ctx: Optional[Mapping[str, Any]] = None) -> str:
    """组页指令行（4f RUL-23；模板配置化 2026-08-31：help_group_row）：`1. 状态 —— 查看角色状态`。"""
    return tpl_of(ctx, "help_group_row", {"idx": index, "cmd": cmd[0], "desc": cmd[1]})


def _render_help_group(ctx: Mapping[str, Any], group_name: str, page: int) -> str:
    """/帮助 <组名>：组内指令列表 5 条/页 + TPL-08（页脚指令=帮助 <组名>）+ 裁决② 夹取。"""
    groups = _help_groups(ctx)
    group = next((g for g in groups if g[0] == group_name), None)
    if group is None:
        return format_tpl12(f"/{HELP_CMD} {group_name}")
    cmds = list(group[1])
    res = resolve_page(page, len(cmds), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_cmds = cmds[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [tpl_of(ctx, "basic_help_group_header", {"group": group_name})]
    for i, c in enumerate(slice_cmds):
        # SHC-04/RUL-24：指令名按 settings.command_aliases 显示层替换（TC-17）
        display = _command_alias_display(ctx, c[0])
        lines.append(group_page_line(start + i + 1, (display, c[1]), ctx))
    if cmds:
        # 2026-09-05 模拟器审计：组页单页（≤5 条）教「帮助<组名><页数>」翻页是
        # 空转引导（无处可翻）——仅多页组渲染翻页 Tip
        _g_tip = tpl_of(ctx, "tip_help_group") if (res.total_pages or 1) > 1 else ""
        lines.append(_cake_tail(res.page, res.total_pages, tip=_g_tip, clamped=res.clamped,
                                templates=ctx.get("templates")))
    return "\n".join(lines)


def cmd_help(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/帮助 [参数] 主入口（4f RUL-20 + B6）：

      无参            → 分组目录（普通 5 组单页；GM 6 组 2 页）
      <组名>          → 指定分组指令列表（5 条/页 + TPL-08；未知组名 → TPL-12）
      <整数>          → 目录页码（裁决②：超页夹取最后一页 + 已到最后一页；0/负数/非数字 → TPL-12）
      未注册（B6）    → 注册引导版（豁免注册门槛）
    """
    # B6 注册引导版（豁免）——P2-6 修复：未注册判定前置到 parsed.error 之前，
    # 未注册玩家任意 /帮助（含解析错误）均返回引导版（B6「/帮助 豁免注册门槛」）。
    # 模板配置化：basic_register_guide（内容包可覆盖）。
    if ctx.get("registered", True) is False:
        return tpl_of(ctx, "basic_register_guide")
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return _render_help_directory(ctx, 1)
    first = str(args[0])
    if len(args) > 2:
        return format_tpl12(_fragment(parsed))
    # 紧凑「组名+页码」粘合拆分（2026-09-05 实机反馈）：parsers 把「帮助冒险2」
    # 解析为 args=['冒险2']（紧凑单 token）——此处按组名前缀拆成 (冒险, 2)。
    # 「帮助2」（args=['2']）不受影响（纯数字走下方目录页码路径）。
    if first not in GROUP_ORDER and len(args) == 1:
        for gname in sorted(GROUP_ORDER, key=len, reverse=True):
            if first.startswith(gname):
                rest = first[len(gname):]
                if rest.isdigit() and int(rest) >= 1:
                    page = parse_page_arg(rest)
                    if page is None:
                        return format_tpl12(_fragment(parsed))
                    return _render_help_group(ctx, gname, page)
                break  # 组名前缀但剩余非页码（如「冒险x」）→ 交 TPL-12
    if first in GROUP_ORDER:
        page = parse_page_arg(args[1] if len(args) > 1 else None)
        if page is None:
            return format_tpl12(_fragment(parsed))
        return _render_help_group(ctx, first, page)
    page = parse_page_arg(first)
    if page is None:
        return format_tpl12(_fragment(parsed))
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    return _render_help_directory(ctx, page)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次7 待接线）
# ---------------------------------------------------------------------------

def register_basic_commands(router: Any, *, make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /角色 /背包 /装备 /技能 /帮助 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（name/level/exp/job_id/attributes/inventory/
        equipment/skills/skill_chains/stats/items/jobs/slots/settings/registered/is_gm/equip_engine
        等，见本模块各渲染函数消费契约）。None 时 handler 调用抛 RuntimeError
        （【待接线】批次7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】basic_commands.register_basic_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _wrap(handler: Callable[..., str]) -> Callable[..., str]:
        def _h(parsed: Any, *a: Any, **k: Any) -> str:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return handler(parsed, injected)
            return handler(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(VIEW_CMD, handler=_wrap(cmd_view)))
    router.register(CommandSpec(VIEW_DETAIL_CMD, handler=_wrap(cmd_view_detail)))
    router.register(CommandSpec(BAG_CMD, handler=_wrap(cmd_bag)))
    router.register(CommandSpec(BAG_FILTER_CMD, handler=_wrap(cmd_bag_filter)))
    router.register(CommandSpec(EQUIP_CMD, handler=_wrap(cmd_equip)))
    router.register(CommandSpec(UNEQUIP_CMD, handler=_wrap(cmd_unequip)))  # 2026-09-06 独立词
    router.register(CommandSpec(SKILL_CMD, handler=_wrap(cmd_skill)))
    router.register(CommandSpec(MY_SKILL_CMD, handler=_wrap(cmd_skill)))  # 我的技能 → 技能
    # 2026-09-05 用户需求：技能详情 / 技能派生
    router.register(CommandSpec(SKILL_INFO_CMD, handler=_wrap(cmd_skill_info)))
    router.register(CommandSpec(SKILL_CHAIN_CMD, handler=_wrap(cmd_skill_chain)))
    router.register(CommandSpec(HELP_CMD, handler=_wrap(cmd_help)))
    return router
