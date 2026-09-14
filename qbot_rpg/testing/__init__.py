"""内容包自带测试的框架辅助面（E3 · ``qbot_rpg.testing``）。

面向 ``content/<pack>/tests/`` 的**通用**测试辅助（换任何包都适用，不写死包名）。
内容包测试只应 import ``qbot_rpg.ext_api``（扩展稳定面）+ 本包（测试辅助面）。

实现放在装配层（``qbot_rpg/assembly/testing_support.py``）——「以该包为内容根装配出可跑
指令的 deps」必然接线 ``commands``，按 TC-03 只有装配层可以；本模块是公开转出面。

用法（包测试文件内）::

    import qbot_rpg.testing as pkt

    PACK = pkt.pack_root_from(__file__)          # 以本包为内容根

    async def test_my_command():
        async with pkt.pack_app(PACK, enable_pack_ext=True) as deps:
            assert deps.pack_ext_result.ok
            out = await pkt.send_command(deps, "我的指令")
            assert out

pytest 侧另有可选 fixture（``pack_root`` / ``pack_deps``），由
``scripts/run_pack_tests.py`` 通过 ``-p qbot_rpg.testing.pytest_plugin`` 自动加载；
单独 import ``qbot_rpg.testing`` 不会引入 pytest。
"""

from __future__ import annotations

from qbot_rpg.assembly.testing_support import (
    MANIFEST_FILE,
    PackValidation,
    build_pack_deps,
    close_pack_deps,
    empty_router,
    ext_settings,
    in_memory_db,
    load_pack_ext,
    load_pack_render,
    pack_app,
    pack_root_from,
    send_command,
    validate_pack_data,
)

__all__ = [
    "MANIFEST_FILE",
    "PackValidation",
    "build_pack_deps",
    "close_pack_deps",
    "empty_router",
    "ext_settings",
    "in_memory_db",
    "load_pack_ext",
    "load_pack_render",
    "pack_app",
    "pack_root_from",
    "send_command",
    "validate_pack_data",
]
