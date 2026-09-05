"""模板分区：dummy_tpl（训练木桩指令（dummy_commands）；2026-09-06 指令缺口补全批1路2）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：渲染走 tpl_of(ctx, "dummy_*", {...})；占位符白名单见下；渲染零 emoji
（仅 ✅/❌ 功能性标记 + 排版符号 | → 等）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    "dummy_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",
    "dummy_system_disabled": "❌ 木桩训练未启用（内容包未配置训练木桩）",
    "dummy_battle_lock": "❌ 你已经在战斗中了（先结束当前战斗）",
    "dummy_list_header": "【训练木桩】可挑战档位：",
    "dummy_list_row": "{idx}. {name}（HP {hp}｜防御 {dfn}）",
    "dummy_list_tail": "发送 /木桩 <序号或名称> 进入训练；/调整木桩 <怪物名> 覆盖面板",
    "dummy_list_empty": "当前内容包没有训练木桩（enemies.json 配 tier=training）",
    "dummy_not_found": "未找到木桩「{name}」，发送 /木桩 查看档位",
    "dummy_start": "⚔️ 与 {name}（HP {hp}）的训练战开始！发 攻击 出战（木桩不反击，胜利无掉落）。",
    "dummy_adjust_ok": "✅ 已把木桩面板调整为「{name}」的防御/抗性（HP 仍为木桩值）",
    "dummy_adjust_reset": "✅ 已重置木桩面板为默认档位",
    "dummy_adjust_missing": "怪物「{name}」不存在（enemies.json 里找）",
    "dummy_adjust_usage": "调整木桩：/调整木桩 <怪物名> 覆盖面板（无参=重置）"
                           "\n示例：/调整木桩 荒原狼",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "dummy_register_gate": set(),
    "dummy_system_disabled": set(),
    "dummy_battle_lock": set(),
    "dummy_list_header": set(),
    "dummy_list_row": {"idx", "name", "hp", "dfn"},
    "dummy_list_tail": set(),
    "dummy_list_empty": set(),
    "dummy_not_found": {"name"},
    "dummy_start": {"name", "hp"},
    "dummy_adjust_ok": {"name"},
    "dummy_adjust_reset": set(),
    "dummy_adjust_missing": {"name"},
    "dummy_adjust_usage": set(),
}
