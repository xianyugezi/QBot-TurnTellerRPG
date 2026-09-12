"""
模板分区：基础默认模板表（2026-08-31 模板配置化包拆分）。

本文件 = 默认模板 + 占位符白名单（帮助/背包/商店/列表尾段；注册/状态/角色
2026-09-12 消息模板重构批1 已迁全量模板表 template_table.json）。
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
