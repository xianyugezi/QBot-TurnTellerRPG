"""模板分区：gift_tpl（赠送指令（gift_commands）；2026-09-06 指令缺口补全批2路1）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：渲染走 tpl_of(ctx, "gift_*", {...})；占位符白名单见下；渲染零 emoji
（仅 ✅/❌ 功能性标记）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    "gift_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",
    "gift_err_empty": "参数错误：/赠送 <物品>*<数量> <玩家>（示例：/赠送 药水*5 123456）",
    "gift_err_qty": "参数错误：数量须为正整数（示例：/赠送 药水*5 123456）",
    "gift_err_missing_player": "参数错误：缺少接收玩家（示例：/赠送 药水*5 123456）",
    "gift_not_found": "未找到「{name}」",
    "gift_bound": "❌ 绑定物品不可赠送（签到/任务奖励默认绑定）",
    "gift_self": "❌ 不能赠送给自己",
    "gift_no_item": "❌ 背包里没有「{name}」或数量不足（持有 {have}）",
    "gift_no_system": "❌ 赠送未启用",
    "gift_target_not_found": "❌ 接收玩家不存在或未注册：{target}",
    "gift_ok": "✅ 已赠送 {name}×{qty} 给 {target}（你剩余 {remain}）",
    "gift_receive": "（{target_name} 收到 {name}×{qty}）",
    "gift_system_disabled": "❌ 赠送未开放",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "gift_register_gate": set(),
    "gift_err_empty": set(),
    "gift_err_qty": set(),
    "gift_err_missing_player": set(),
    "gift_not_found": {"name"},
    "gift_bound": set(),
    "gift_self": set(),
    "gift_no_item": {"name", "have"},
    "gift_no_system": set(),
    "gift_target_not_found": {"target"},
    "gift_ok": {"name", "qty", "target", "remain"},
    "gift_receive": {"target_name", "name", "qty"},
    "gift_system_disabled": set(),
}
