# -*- coding: utf-8 -*-
"""九期215（D-01 内容包 emoji 白名单）：注册口 + 校验器。

铁律基线：框架默认模板渲染零 emoji（仅 ✅/❌ 功能性标记，D-5B）；云海内容包
按 D-01 契约声明 emoji 白名单，经本模块注册后战报渲染面放行。

- ``register_emoji_whitelist(emojis)``：幂等注册（内容包装配时调用一次）；
- ``validate_emoji_use(text) -> (ok, unknown)``：文本中出现的 emoji 是否全部
  在注册白名单内（功能性标记 ✅/❌ 恒放行）；
- 未注册任何白名单 → 校验恒通过（零行为，兼容既有内容包）。
"""
from __future__ import annotations

import re
from typing import FrozenSet, Iterable, Optional, Tuple

__all__ = ["register_emoji_whitelist", "validate_emoji_use", "registered_emoji"]

#: 恒放行的功能性标记（D-5B 既有口径，不依赖注册）
FUNCTIONAL_MARKS: FrozenSet[str] = frozenset({"✅", "❌"})

#: emoji/符号粗扫模式：非 ASCII、非常用中文标点的单码位（含 variation selector）
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF\u25A0-\u25FF]"
)

_WHITELIST: Optional[FrozenSet[str]] = None


def register_emoji_whitelist(emojis: Iterable[str]) -> FrozenSet[str]:
    """注册内容包 emoji 白名单（幂等覆盖式；空表＝清空＝回到恒通过态）。"""
    global _WHITELIST
    _WHITELIST = frozenset(e for e in emojis if e)
    return _WHITELIST


def registered_emoji() -> Optional[FrozenSet[str]]:
    return _WHITELIST


def validate_emoji_use(text: str) -> Tuple[bool, Tuple[str, ...]]:
    """校验文本 emoji 是否全部在注册白名单内。

    Returns:
        (ok, unknown)：ok=True 全部合法（含未注册态恒通过）；unknown 为
        越白名单 emoji 元组（供装配期告警，不在战斗期抛错——零行为红线）。
    """
    if _WHITELIST is None:
        return True, ()
    found = set(_EMOJI_RE.findall(text or ""))
    unknown = tuple(sorted(found - _WHITELIST - FUNCTIONAL_MARKS))
    return (not unknown), unknown
