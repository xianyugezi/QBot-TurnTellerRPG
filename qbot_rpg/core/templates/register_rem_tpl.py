"""
模板分区：register_rem（注册指令剩余 + 商店指令剩余，2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 register_commands.py / shop_commands.py 的逐字文案迁移
（注册成功回显 / 名字校验 / 指令参数错误 / 商店无店·空店·一览标题 / 购买出售失败兜底 /
尾段 Tip），默认值改动会导致现有测试断言失效——需与两模块渲染处
tpl_of(ctx, "register_*"/"shop_*", {...}) 一致。

注意：shop_header / shop_row / shop_tail（尾段）已在 base.py 迁移，本分区不重复收录。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 注册：名字校验（REG-02 / RUL-02；【框架】L1156 安全补强）——
    "register_name_too_long": "❌ 角色名最多 20 个字",
    "register_name_bad_chars": "❌ 角色名含非法字符，请重新输入（过滤控制字符/超长 emoji）",

    # —— 注册：重名红拦 / 职业不存在（REG-03 / RUL-03/07 / B5）——
    "register_dup_name": "❌ 已经有一个叫『{name}』的角色了，换个名字吧",
    "register_job_not_found": "❌ 没有『{job}』这个职业，可用：{list}",
    "register_job_recommended": "（推荐）",

    # —— 注册：保留字符黄提示尾缀（RUL-02 ③「只建议不限制」）——
    "register_reserved_hint": "（提示：{hint}）",

    # —— 注册成功回显（TPL-4F-01 语义；工程补白 1 前缀行 + 初始属性逐行 + 引导行）——
    "register_success_prefix": "Lv1.{name} - -",
    "register_success_welcome": "✅ 注册成功！欢迎来到「{world}」世界",
    "register_success_job_loc": "职业：{job} ｜ 位置：{location}",
    "register_success_recommended": "（推荐新手）",
    "register_success_attr_title": "初始属性：",
    "register_success_hp": "生命 {hp}/{hp}",
    "register_success_mp": "魔力 {mp}/{mp}",
    "register_success_atk": "攻击 {atk}",
    "register_success_dfn": "防御 {dfn}",
    "register_success_next": "下一步：发 /帮助 查看指令，或 /锁定 {location}怪物开战。",

    # —— 注册：指令参数错误（REG-01；3d §5.1「原因 + 正确用法」句式）——
    "register_args_too_many": "❌ 指令不正确：/注册 最多 2 个参数。正确格式：{usage}",
    "register_args_missing": "❌ 指令不正确：/注册 需要角色名。正确格式：{usage}"
                             "（或直接发 /注册，将用你的 QQ 号作为名字）",

    # —— 注册：无参 QQ 号兜底提示（用户拍板 2026-08-28：零输入开玩）——
    "register_auto_name": "已自动用你的 QQ 号「{name}」作为名字",

    # —— 商店：无店 / 空店 / 一览标题（shop_commands；2b3 §2.1 + 定稿 L421）——
    "shop_no_shop": "❌ 商店不存在",
    "shop_browse_empty": "（这家店空空的）",
    "shop_list_title": "可用商店一览",

    # —— 商店：购买/出售失败兜底（引擎 message 缺失时的命令层兜底）——
    "shop_buy_fail": "❌ 购买失败",
    "shop_sell_fail": "❌ 出售失败",

    # —— 商店：CakeGame 式尾段 Tip 内容（尾段格式 list_tail 在 base.py，此处仅 Tip 文案）——
    "shop_browse_tail_tip": "发送'购买 序号'即可购买物品。",
    "shop_list_tail_tip": "发送'商店 <名称>'即可进入商店",

    # —— 商店：商品单价 / 折扣标记 / 一览行前缀（数据型展示片段）——
    "shop_price_single": "{unit}({currency})",
    "shop_price_part": "{amount}({currency})",
    "shop_discount_marker": "[折扣 -{discount}%]",
    "shop_overview_row_prefix": "{index}. {name}",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "register_name_too_long": set(),
    "register_name_bad_chars": set(),
    "register_dup_name": {"name"},
    "register_job_not_found": {"job", "list"},
    "register_job_recommended": set(),
    "register_reserved_hint": {"hint"},
    "register_success_prefix": {"name"},
    "register_success_welcome": {"world"},
    "register_success_job_loc": {"job", "location"},
    "register_success_recommended": set(),
    "register_success_attr_title": set(),
    "register_success_hp": {"hp"},
    "register_success_mp": {"mp"},
    "register_success_atk": {"atk"},
    "register_success_dfn": {"dfn"},
    "register_success_next": {"location"},
    "register_args_too_many": {"usage"},
    "register_args_missing": {"usage"},
    "register_auto_name": {"name"},
    "shop_no_shop": set(),
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
