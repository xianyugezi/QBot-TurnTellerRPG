"""
模板分区：pvp_tpl（PVP 指令（pvp_commands）；M11 批3 路3B）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = PVP 指令壳（/锁定玩家 /攻击玩家）渲染文案。key 命名：
pvp_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样保留。

分区（段落）：
- 解析错误 4 类：pvp_err_missing / pvp_err_too_many / pvp_err_unknown_sep /
  pvp_err_reserved（对齐指令分隔符规范 L72 错误模板四类，CMD-R05）
- 引擎入口错误：pvp_engine_missing / pvp_engine_unavailable
- /锁定玩家：pvp_lock_ok / pvp_lock_status_line* / pvp_lock_equip_summary /
  pvp_lock_self / pvp_lock_not_found / pvp_lock_no_target
- /攻击玩家：pvp_attack_no_target / pvp_attack_ok / pvp_attack_result_line
- 门禁/兜底：pvp_registered_gate / pvp_not_registered

渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 | → × /「」【】）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 解析错误 4 类（对齐规范 L72 / 细化_4e CMD-R05）——
    "pvp_err_missing": "请指定目标：/锁定玩家 <QQ号>，或 /攻击玩家 <技能序号>",
    "pvp_err_too_many": "参数过多，PVP 指令只需 1 个参数",
    "pvp_err_unknown_sep": "PVP 指令不支持列表/数量/键值参数",
    "pvp_err_reserved": "参数含保留字符（* , = + / 空格），请重新输入",

    # —— 引擎入口错误（3A 引擎未接线 / 未实现）——
    "pvp_engine_missing": "❌ PVP 引擎未接线（core/pvp.py 未实现，后续里程碑）",
    "pvp_engine_unavailable": "❌ PVP 引擎不可用（core/pvp.py 未实现，后续里程碑）",

    # —— /锁定玩家 ——
    "pvp_lock_ok": "✅ 已锁定玩家：{name}",
    "pvp_lock_status_level": "【等级】{level}",
    "pvp_lock_status_job": "【职业】{job}",
    "pvp_lock_status_hp": "【血量】{hp}/{max_hp}",
    "pvp_lock_status_equip": "【装备】{summary}",
    "pvp_lock_equip_summary": "{slot}：{item}",
    "pvp_lock_self": "❌ 不能锁定自己",
    "pvp_lock_not_found": "❌ 未找到玩家：{qq}（对方未注册或不在线）",
    "pvp_lock_no_target": "❌ 请先 /锁定玩家 <QQ号> 指定目标",

    # —— /攻击玩家 ——
    "pvp_attack_no_target": "❌ 请先 /锁定玩家 <QQ号> 指定目标",
    "pvp_attack_ok": "✅ 对 {name} 发起攻击：{result}",
    "pvp_attack_result_line": "{name} 受到 {damage} 点伤害，剩余 {hp}/{max_hp}",

    # —— 门禁/兜底 ——
    "pvp_registered_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",
    "pvp_not_registered": "❌ 请先 /注册 创建角色（/注册 名字 职业）",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    # —— 解析错误 4 类 ——
    "pvp_err_missing": set(),
    "pvp_err_too_many": set(),
    "pvp_err_unknown_sep": set(),
    "pvp_err_reserved": set(),

    # —— 引擎入口错误 ——
    "pvp_engine_missing": set(),
    "pvp_engine_unavailable": set(),

    # —— /锁定玩家 ——
    "pvp_lock_ok": {"name"},
    "pvp_lock_status_level": {"level"},
    "pvp_lock_status_job": {"job"},
    "pvp_lock_status_hp": {"hp", "max_hp"},
    "pvp_lock_status_equip": {"summary"},
    "pvp_lock_equip_summary": {"slot", "item"},
    "pvp_lock_self": set(),
    "pvp_lock_not_found": {"qq"},
    "pvp_lock_no_target": set(),

    # —— /攻击玩家 ——
    "pvp_attack_no_target": set(),
    "pvp_attack_ok": {"name", "result"},
    "pvp_attack_result_line": {"name", "damage", "hp", "max_hp"},

    # —— 门禁/兜底 ——
    "pvp_registered_gate": set(),
    "pvp_not_registered": set(),
}
