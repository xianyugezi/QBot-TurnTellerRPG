"""
模板分区：基础默认模板表（2026-08-31 模板配置化包拆分）。

本文件 = 已迁移核心 8 类的默认模板 + 占位符白名单（注册/状态/角色/帮助/背包/商店/列表尾段）。
其他模块分区见 use_tpl.py / shortcut_tpl.py / log_tpl.py / codex_tpl.py / dialog_tpl.py /
explore_tpl.py / quest_tpl.py / checkin_tpl.py / battle_tpl.py / forge_tpl.py / alchemy_tpl.py /
basic_rem_tpl.py / register_rem_tpl.py（内容包 templates.json 覆盖同 key）。
"""
from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# 默认模板（框架内置；内容包 templates.json 可覆盖同 key）
# 说明：这些字符串 = 逐组优化敲定的消息形态（2026-08-31 前写死在各命令模块里，
# 现集中到配置层；后续用户调整默认值即改此处或内容包 templates.json）
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 注册 / 注销（register/unregister_commands）——
    "register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",
    "already_registered": "❌ 你已经注册过了！当前角色：{name}（Lv{level}{job}）。\n"
                          "想重新开始请发送注销。",
    "unregister_confirm": "注销将删除角色「{name}」所有数据（等级/装备/背包/图鉴/成就/日志）"
                          "且不可恢复！\n确认请发：/注销 确认",
    "unregister_done": "✅ 角色「{name}」已删除。随时可重新 /注册 开始新的冒险。",

    # —— 状态面板（status_commands）——
    "status_level": "【等级】{level}",
    "status_exp": "【经验】{exp}/{exp_next}",
    "status_exp_only": "【经验】{exp}",
    "status_max_hint": "【已满级】",
    "status_no_attr": "【属性】无",
    "status_attr": "【{attr_name}】{value}",
    "status_attr_resource": "【{attr_name}】{cur}/{max}",
    "status_location": "【位置】{location}",
    "status_target": "【目标】{name} {hp_cur}/{hp_max}（第 {round} 回合）",
    "status_effects": "【效果】{effects}",
    "status_imprints": "【印记】{imprints}",

    # —— 角色面板（basic_commands view_header / attr_line）——
    "role_header": "【角色】{name}",
    "role_level": "【等级】{level}",
    "role_job": "【职业】{job}",
    "role_exp": "【经验】{exp}/{exp_next}",
    "role_exp_only": "【经验】{exp}",
    "role_max": "【已满级】",
    "role_attr": "【{attr_name}】{value}",
    "role_attr_resource": "【{attr_name}】{cur}/{max}",
    "role_attr_detail": "【{attr_name}】{value}（白值 {base} ｜ 加成 {bonus} ｜ 临时 {temp}）",
    "role_attr_detail_resource": "【{attr_name}】{cur}/{max}（白值 {base} ｜ 加成 {bonus}"
                                 " ｜ 临时 {temp}）",

    # —— 帮助目录 / 组页（basic_commands help）——
    "help_directory_title": "【指令总览】",
    "help_directory_row": "{group} — {cmds}",
    "help_group_row": "{idx}. {cmd} —— {desc}",
    "help_group_empty": "该组暂无指令",
    "help_tail": "Tip:发送'帮助 组名'翻页查看指令",

    # —— 背包（basic_commands bag）——
    "bag_empty": "❌ 背包空空如也",
    "bag_row": "{idx}.[{name}]×{count}",
    "bag_tail": "Tip:发送'使用+物品名'即可使用物品",

    # —— 商店（shop_commands）——
    "shop_header": "{name}\n{desc}",   # 2026-08-31 用户拍板：介绍单独换行（name 已含类型徽标）
    "shop_row": "{idx}. {name} ｜ 商品单价：{price}{markers}",
    "shop_empty": "❌ 商店空空如也",
    "shop_tail": "Tip:发送'购买 {idx}'即可购买物品。",

    # —— 列表尾段（CakeGame 式，list_render.render_cake_tail）——
    "list_tail": "当前页：{page}/{pages}{filter}\nTip:{tip}",
}

# ---------------------------------------------------------------------------
# 占位符白名单（每类模板允许的占位符；超出白名单渲染时原样保留）
# ---------------------------------------------------------------------------
PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "register_gate": set(),
    "already_registered": {"name", "level", "job"},
    "unregister_confirm": {"name"},
    "unregister_done": {"name"},
    "status_level": {"level"},
    "status_exp": {"exp", "exp_next"},
    "status_exp_only": {"exp"},
    "status_max_hint": set(),
    "status_no_attr": set(),
    "status_attr": {"attr_name", "value"},
    "status_attr_resource": {"attr_name", "cur", "max"},
    "status_location": {"location"},
    "status_target": {"name", "hp_cur", "hp_max", "round"},
    "status_effects": {"effects"},
    "status_imprints": {"imprints"},
    "role_header": {"name"},
    "role_level": {"level"},
    "role_job": {"job"},
    "role_exp": {"exp", "exp_next"},
    "role_exp_only": {"exp"},
    "role_max": set(),
    "role_attr": {"attr_name", "value"},
    "role_attr_resource": {"attr_name", "cur", "max"},
    "role_attr_detail": {"attr_name", "value", "base", "bonus", "temp"},
    "role_attr_detail_resource": {"attr_name", "cur", "max", "base", "bonus", "temp"},
    "help_directory_title": set(),
    "help_directory_row": {"group", "cmds"},
    "help_group_row": {"idx", "cmd", "desc"},
    "help_group_empty": set(),
    "help_tail": set(),
    "bag_empty": set(),
    "bag_row": {"idx", "name", "count"},
    "bag_tail": set(),
    "shop_header": {"name", "badge", "desc"},
    "shop_row": {"idx", "name", "price", "markers"},
    "shop_empty": set(),
    "shop_tail": {"idx"},
    "list_tail": {"page", "pages", "filter", "tip"},
}
