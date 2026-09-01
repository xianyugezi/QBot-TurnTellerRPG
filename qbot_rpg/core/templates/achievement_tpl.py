"""
模板分区：achievement_tpl（成就指令（achievement_commands）；M11 批1 路1C）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 成就指令壳（/成就 /成就信息 /称号）渲染文案。key 命名：
ach_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样保留。

分区（段落）：
- 列表：ach_list_header / ach_list_line / ach_list_locked / ach_list_tail
- 详情：ach_view_header / ach_view_desc / ach_view_hidden / ach_view_not_found
- 揭示：ach_reveal_card
- 称号：ach_title_header / ach_title_line / ach_title_equip_ok / ach_title_equip_fail /
  ach_title_empty / ach_title_help
- 空态：ach_empty

渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 | → × /「」【】）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 列表（/成就 [页数]）——
    "ach_list_header": "【成就】第 {page}/{pages} 页｜已达成 {done}/{total}",
    "ach_list_line": "{index}. {name}｜{state}",
    "ach_list_locked": "{index}. ？？？",
    "ach_list_tail": "共 {total} 项成就｜输入 /成就信息 <N> 查看详情",
    # —— 详情（/成就信息 <N>）——
    "ach_view_header": "【成就】{name}",
    "ach_view_desc": "描述：{desc}",
    "ach_view_hidden": "？？？",
    "ach_view_not_found": "❌ 成就不存在：{aid}",
    # —— 揭示（隐藏成就达成瞬间）——
    "ach_reveal_card": "【隐藏成就】{name}\n{reveal_text}",
    # —— 称号（/称号 查看 /称号 佩戴 <N>）——
    "ach_title_header": "【称号】当前佩戴：{current}",
    "ach_title_line": "{index}. {title_id}",
    "ach_title_equip_ok": "✅ 已佩戴称号：{title_id}",
    "ach_title_equip_fail": "❌ 无法佩戴称号：{title_id}（未拥有）",
    "ach_title_empty": "【称号】暂无称号",
    "ach_title_help": "用法：/称号 查看 或 /称号 佩戴 <N>",
    # —— 空态 ——
    "ach_empty": "【成就】暂无成就",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "ach_list_header": {"page", "pages", "done", "total"},
    "ach_list_line": {"index", "name", "state"},
    "ach_list_locked": {"index"},
    "ach_list_tail": {"total"},
    "ach_view_header": {"name"},
    "ach_view_desc": {"desc"},
    "ach_view_hidden": set(),
    "ach_view_not_found": {"aid"},
    "ach_reveal_card": {"name", "reveal_text"},
    "ach_title_header": {"current"},
    "ach_title_line": {"index", "title_id"},
    "ach_title_equip_ok": {"title_id"},
    "ach_title_equip_fail": {"title_id"},
    "ach_title_empty": set(),
    "ach_title_help": set(),
    "ach_empty": set(),
}
