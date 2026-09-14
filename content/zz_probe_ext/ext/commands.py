"""内容包扩展探针实现（E1 验证用）。

只 import ``qbot_rpg.ext_api``（稳定面）：这只证明「包内自持指令」的约定形态，
不代表框架里写死任何包名或指令名。
"""

from __future__ import annotations

from qbot_rpg import ext_api


def probe(ctx, parsed):
    """探针指令：回显包 id / 玩家 id / 参数，证明扩展已由框架装载生效。"""
    lines = [
        f"【扩展探针】包={ctx.pack_id}",
        f"玩家={ctx.player_id or '未注册'}",
    ]
    if ctx.args:
        lines.append("参数=" + " ".join(ctx.args))
    lines.append(f"ext_api=v{ext_api.EXT_API_VERSION}")
    return "\n".join(lines)
