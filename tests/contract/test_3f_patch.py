"""3f 单机向体验·契约层前置（M0 时点最小落点，精细化 3f §六 TC-21 精神）。

3f 全功能（/日志 /调查 隐藏要素 图鉴闭环）依赖 M3/M4/M6（时间天气/任务/NPC/图鉴），
M0 只保证：①3f 补丁包能在 validator 加载不红拦 ②隐藏要素引用未注册条件键走黄提示/放行。
若 validator 尚不支持，则 SKIP 并注明（不补实现——validator 的 3f 扩展属 M6）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.content.loader import load_pack

pytestmark = pytest.mark.asyncio


async def test_3f_patch_pack_loadable(patch3f_dir):
    """3f 补丁包（hidden_elements 未注册条件键）可加载不红拦。"""
    pack = await load_pack(patch3f_dir)
    assert pack.pack_id == (patch3f_dir.name)
    assert pack.report.ok
