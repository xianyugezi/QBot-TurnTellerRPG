"""探针包自带测试（E3 最小样本）。

只用 ``qbot_rpg.ext_api`` 稳定面 + ``qbot_rpg.testing`` 辅助；**不 import 框架内部实现**。
只读、内存库：不写真实内容包、不碰真实玩家库。

运行（约定入口）::

    python scripts/run_pack_tests.py --pack zz_probe_ext
"""
from __future__ import annotations

from pathlib import Path

import qbot_rpg.testing as pkt

#: 以本包为内容根（不认识包名，只看 manifest.json 标识）。
PACK = pkt.pack_root_from(__file__)


def test_pack_root_resolves_to_this_pack() -> None:
    """以本包为内容根：pack_root_from 找到的目录 = 本测试文件所在包的根目录。"""
    assert PACK == Path(__file__).resolve().parents[1]
    assert (PACK / "manifest.json").is_file()
    assert (PACK / "commands.json").is_file()


def test_extension_loads_with_test_switch() -> None:
    """指令扩展可装载（测试开关打开双闸）：声明被注册、handler 齐备。"""
    result = pkt.load_pack_ext(PACK)
    assert result.enabled is True and result.ok is True
    assert result.registered, result.errors
    assert (PACK / "ext" / "commands.py").is_file()


def test_render_hook_loads_and_applies() -> None:
    """渲染钩子可装载：命中声明事件时改写文本，未命中事件落默认。"""
    result = pkt.load_pack_render(PACK)
    assert result.ok is True and result.loaded is True and result.hook is not None
    assert result.hook.apply("command.reply", {}, "正文") != "正文"
    assert result.hook.apply("battle.round", {}, "正文") == "正文"


async def test_command_end_to_end_in_memory() -> None:
    """以本包为内容根装配（内存库）→ 发指令 → 玩家可见文本含探针标记。"""
    async with pkt.pack_app(PACK) as deps:
        assert deps.pack_ext_result.ok
        out = await pkt.send_command(deps, "探针 参数甲")
    assert "参数=参数甲" in out
