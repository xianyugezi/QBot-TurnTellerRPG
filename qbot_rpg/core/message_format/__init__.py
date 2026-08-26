"""纯字符串渲染包（细化_3a §5，D-04）：引擎结算 → str，无 CQ 码/无平台语法。"""
from __future__ import annotations

# strip_icon_emoji 实现位于 data/emoji_sanitize.py（跨层共享工具放 data 层，
# 避免 engine→core 反向依赖；本包 re-export 供 core/commands 层消费方沿用旧路径）。
from qbot_rpg.data.emoji_sanitize import strip_icon_emoji

__all__ = ["strip_icon_emoji"]
