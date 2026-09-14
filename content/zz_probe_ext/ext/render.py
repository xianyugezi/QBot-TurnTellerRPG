"""内容包渲染钩子探针（E2 验证用）。

只证明「包内自持渲染钩子」的约定形态：``EVENTS`` 声明要接的事件 + ``render`` 改写
文本。**不 import 任何** ``qbot_rpg.*``（渲染钩子只拿到只读快照与最终文本，无需框架
句柄）；也不代表框架里写死任何包名或事件专属业务词。
"""

from __future__ import annotations

# 事件白名单：只接指令回复；未命中事件框架不会调用本函数。
EVENTS = ("command.reply",)

_SUFFIX = "（探针改写）"


def render(event, data, default_text):
    """``command.reply`` → 在框架最终文本后缀探针标记；其余 → ``None``（用默认）。"""
    if event != "command.reply":
        return None
    if not default_text:
        return None
    return f"{default_text}{_SUFFIX}"
