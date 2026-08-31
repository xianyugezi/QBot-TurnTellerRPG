"""
模板分区：shortcut_tpl（快捷指令（shortcut_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。
"""
from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# 默认模板（框架内置；内容包 templates.json 可覆盖同 key）
# 说明：这些字符串 = 迁移前写死在 shortcut_commands.py 的硬编码消息（TPL_SHORTCUT_EMPTY /
# _LIST_TAIL_TIP / 解绑/列表 f-string），现集中到配置层（用户拍板：模板不写死代码）。
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 快捷解绑（cmd_shortcut_unbind / SHC-01 / TPL-4F-10）——
    "shortcut_unbind_missing": "❌ 没有绑定『{name}』",
    "shortcut_unbind_ok": "✅ 已解绑『{name}』",

    # —— 快捷列表（cmd_shortcut_list / SHC-02 / TPL-4F-11）——
    "shortcut_empty": "❌ 还没有快捷绑定，试试 /快捷绑定 1 攻击",
    "shortcut_list_header": "【快捷（{count}/{cap}）】",
    "shortcut_list_row": "{name} → {command}",
    "shortcut_list_tail_tip": "发送'快捷绑定 名字 指令'即可绑定快捷",
}

# ---------------------------------------------------------------------------
# 占位符白名单（每类模板允许的占位符；超出白名单渲染时原样保留）
# ---------------------------------------------------------------------------
PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "shortcut_unbind_missing": {"name"},
    "shortcut_unbind_ok": {"name"},
    "shortcut_empty": set(),
    "shortcut_list_header": {"count", "cap"},
    "shortcut_list_row": {"name", "command"},
    "shortcut_list_tail_tip": set(),
}
