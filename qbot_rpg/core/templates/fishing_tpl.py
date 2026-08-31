"""
模板分区：fishing_tpl（钓鱼指令（fishing_commands / fishing_reel_commands /
fishing_codex_commands）；2026-09-01 模板配置化分区，批6 路6A 主 agent 收口）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 指令壳 _DEF_* fallback 逐字迁移（本地 fallback 与批1-5 引擎
MSG_* 文案一致），默认值改动会导致现有测试断言失效——需与指令壳渲染处
tpl_of(ctx, "fish_*", {...}) 一致。

key 命名：fish_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时
原样保留（提示缺失）。渲染零 emoji（仅功能性标记 + 排版符号 | → × / ■ 等）。

分区（段落）：
- /钓鱼 钓点列举：fish_off / fish_spot_list_header / fish_spot_line /
  fish_spot_empty / fish_intent_ref
- 鱼讯：fish_bite_idle / fish_bite_waiting / fish_bite_triggered
- 收杆：fish_reel_bad_choice / fish_reel_timeout / fish_reel_stop /
  fish_reel_success
- 鱼图鉴：fish_codex_header / fish_codex_summary / fish_codex_empty

注意：模块级 _DEF_* 常量在指令壳中保留为向后兼容导出（值 = 本分区默认文案），
渲染一律走 tpl_of（_render 优先 tpl_of，空串回退本地 fallback）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— /钓鱼 钓点列举（fishing_commands）——
    "fish_off": "钓鱼功能已关闭",
    "fish_spot_list_header": "【垂钓点】当前地图：{map_name}",
    "fish_spot_line": "- {spot_name}｜时段：{periods}｜稀有度：{rarity}",
    "fish_spot_empty": "【垂钓点】本图暂无可钓鱼点",
    "fish_intent_ref": "微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！",

    # —— 鱼讯（fishing_reel_commands cmd_fish_bite）——
    "fish_bite_idle": "无进行中钓局",
    "fish_bite_waiting": "等待中：{spot} · 已耗时 {elapsed}s（鱼讯未触发）",
    "fish_bite_triggered": "{kind_cn}！{golden_line}收杆吧：/收杆 满力 / 自动 / 止损",

    # —— 收杆（fishing_reel_commands cmd_fish_reel）——
    "fish_reel_bad_choice": "请选择：满力 / 自动 / 止损",
    "fish_reel_timeout": "鱼跑了……（收杆超时）",
    "fish_reel_stop": "已止损收杆（饵已消耗，本局无鱼获）",
    "fish_reel_success": "收杆成功！{kind_cn} · {rarity_cn}",

    # —— 鱼图鉴（fishing_codex_commands render_fish_codex）——
    "fish_codex_header": "【鱼图鉴】",
    "fish_codex_summary": "已捕获 {caught} 种 · 鱼王讨伐胜利 {king} 次",
    "fish_codex_empty": "（还没有捕获记录）",
}

PLACEHOLDER_WHITELIST: Dict[str, Any] = {
    "fish_off": (),
    "fish_spot_list_header": ("map_name",),
    "fish_spot_line": ("spot_name", "periods", "rarity"),
    "fish_spot_empty": (),
    "fish_intent_ref": (),
    "fish_bite_idle": (),
    "fish_bite_waiting": ("spot", "elapsed"),
    "fish_bite_triggered": ("kind_cn", "golden_line"),
    "fish_reel_bad_choice": (),
    "fish_reel_timeout": (),
    "fish_reel_stop": (),
    "fish_reel_success": ("kind_cn", "rarity_cn"),
    "fish_codex_header": (),
    "fish_codex_summary": ("caught", "king"),
    "fish_codex_empty": (),
}
