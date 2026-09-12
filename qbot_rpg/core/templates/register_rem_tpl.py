"""
模板分区：register_rem（注册指令剩余 + 商店指令剩余，2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批1：注册指令剩余（register_*）已迁全量模板表并移除。
- 批10·路C：商店指令剩余 13 键（无店 shop_no_shop / 进店用法 shop_enter_usage /
  未命中 shop_enter_not_found / 空店 shop_browse_empty / 一览标题 shop_list_title /
  购买出售失败兜底 shop_buy_fail·shop_sell_fail / 尾段 Tip shop_browse_tail_tip·
  shop_list_tail_tip / 数据片段 shop_price_single·shop_price_part·
  shop_discount_marker·shop_overview_row_prefix）全部迁入全量表
  `qbot_rpg/core/templates/template_table.json`，按手机QQ 14 全角新规范重写
  （错误行 ❌ + 原因（+ 下一步）两行化、用法/提示行免斜杠、段头【商店】+副题、
  尾段 Tip 收窄至「Tip:」前缀后 ≤28 半角）；本分区默认表与占位符白名单清空
  （白名单由表自动派生，见 core/templates/__init__.py）。
- 本路结构锚点保留：数据片段 shop_price_single / shop_price_part（半角括号货币单位）、
  shop_discount_marker（方括号折扣标记）、shop_overview_row_prefix（序号前缀，
  壳层再拼类型徽标/描述/门槛标记）——属固定结构片段，非可自由重排文案。
- 本路无死键（13 键均有 tpl_of 调用点）。
- 渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。

历史铁律（2026-08-31）：字符串 = 写死在 shop_commands.py 的逐字文案迁移（商店无店·空店·
一览标题 / 购买出售失败兜底 / 尾段 Tip）。注：该「逐字对齐」口径已被 2026-09-12 消息模板
重构新规范取代（旧文案不作参考，信息要素/占位符不变）。shop_header / shop_row /
shop_tail（尾段）在 base.py 收录，本分区不重复。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：13 键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
