"""
模板分区：register_rem（注册指令剩余 + 商店指令剩余，2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。
2026-09-12 消息模板重构批1：注册指令剩余（register_*）已迁全量模板表
（template_table.json）并从本分区移除；本分区现存 = 商店指令剩余。

铁律：字符串 = 2026-08-31 前写死在 shop_commands.py 的逐字文案迁移（商店无店·空店·
一览标题 / 购买出售失败兜底 / 尾段 Tip），默认值改动会导致现有测试断言失效——需与
shop_commands 渲染处 tpl_of(ctx, "shop_*", {...}) 一致。

注意：shop_header / shop_row / shop_tail（尾段）已在 base.py 迁移，本分区不重复收录。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 商店：无店 / 空店 / 一览标题（shop_commands；2b3 §2.1 + 定稿 L421）——
    "shop_no_shop": "❌ 商店不存在",
    # 2026-09-05 商店进入独立指令
    "shop_enter_usage": "商店进入：发 商店进入 <序号|商店名>（序号见 商店列表）",
    "shop_enter_not_found": "❌ 找不到商店「{name}」（发 商店列表 查看可用商店）",
    "shop_browse_empty": "（这家店空空的）",
    "shop_list_title": "可用商店一览",

    # —— 商店：购买/出售失败兜底（引擎 message 缺失时的命令层兜底）——
    "shop_buy_fail": "❌ 购买失败",
    "shop_sell_fail": "❌ 出售失败",

    # —— 商店：CakeGame 式尾段 Tip 内容（尾段格式 list_tail 在 base.py，此处仅 Tip 文案）——
    "shop_browse_tail_tip": "发送'购买 序号'即可购买物品。",
    "shop_list_tail_tip": "发送'商店进入 <序号|名称>'即可进入商店",

    # —— 商店：商品单价 / 折扣标记 / 一览行前缀（数据型展示片段）——
    "shop_price_single": "{unit}({currency})",
    "shop_price_part": "{amount}({currency})",
    "shop_discount_marker": "[折扣 -{discount}%]",
    "shop_overview_row_prefix": "{index}. {name}",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "shop_no_shop": set(),
    "shop_enter_usage": set(),
    "shop_enter_not_found": {"name"},
    "shop_browse_empty": set(),
    "shop_list_title": set(),
    "shop_buy_fail": set(),
    "shop_sell_fail": set(),
    "shop_browse_tail_tip": set(),
    "shop_list_tail_tip": set(),
    "shop_price_single": {"unit", "currency"},
    "shop_price_part": {"amount", "currency"},
    "shop_discount_marker": {"discount"},
    "shop_overview_row_prefix": {"index", "name"},
}
