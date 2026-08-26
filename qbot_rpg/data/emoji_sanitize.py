"""全仓渲染输出 emoji 剥离（M5 裁决：不用 emoji，docs/m5_shared_contract.md §4.1）。

数据型功能图标字段（物品 icon / NPC 类型图标 / 商店 icon / 天气 emoji / 印记 icon /
GM 结果前缀）一律降级纯文本：渲染出口经 strip_icon_emoji 剥离 emoji 字符，保留
✅/❌ 功能性标记 + 排版符号（| → × / 「」【】）+ CJK 汉字/ASCII 文本符号
（作者可配「剑」「+」等文本图标）。本函数为全仓统一剥离出口。

放 data/ 层：engine/core/world/storage/content/commands 各层均允许依赖 data
（依赖矩阵 §1.4），避免 engine→core 反向依赖（G0 架构门禁）。
"""
from __future__ import annotations

import re

__all__ = ["strip_icon_emoji"]

# emoji 字符类（排除 ✅ U+2705 / ❌ U+274C——功能性标记必须保留）：
#   - U+2600~U+27BF 杂项符号与装饰符（⚙⚠🚫✚➡…，挖掉 ✅❌ 两个码位）
#   - U+1F000~U+1FAFF 表情/象形扩展
#   - U+2300~U+23FF 杂项技术符号（⏰⌚…）
#   - U+2B00~U+2BFF 杂项符号与箭头（⭐…）
#   - U+FE00~U+FE0F 变体选择符（VS16 等）、U+200D ZWJ
_EMOJI_CLASS = (
    "\U00002300-\U000023FF"  # 杂项技术符号（⏰ 等）
    "\U00002B00-\U00002BFF"  # 杂项符号与箭头（⭐ 等）
    "\U0001F000-\U0001FAFF"  # 表情/象形扩展
    "\U00002600-\U00002704"  # 杂项符号（⚙⚠ 等，至 ✅ U+2705 前）
    "\U00002706-\U0000274B"  # ✅ U+2705 后至 ❌ U+274C 前
    "\U0000274D-\U000027BF"  # ❌ U+274C 后至装饰符区段尾（✚✉➡ 等）
    "\U0000FE00-\U0000FE0F"  # 变体选择符（VS16 等）
    "\U0000200D"             # ZWJ 零宽连接符
)
_EMOJI_RE = re.compile("[" + _EMOJI_CLASS + "]+")


def strip_icon_emoji(text: object) -> str:
    """剥离字符串中的 emoji 字符（M5 裁决：渲染输出不用 emoji）。

    仅删除 emoji 字符，保留 ✅/❌ 功能性标记、排版符号（| → × / 「」【】）、
    CJK 汉字与 ASCII 文本符号。非字符串入参 → 空串（容错）。

    应用点：items/NPC/商店/天气/印记 等数据 icon 字段的渲染出口，
    以及 GM 结果前缀（📋📝⚙️ 等数据型功能图标）的降级。
    """
    if text is None:
        return ""
    return _EMOJI_RE.sub("", str(text))
