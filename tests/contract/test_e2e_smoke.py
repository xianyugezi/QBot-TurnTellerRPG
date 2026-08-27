"""内容包冒烟（细化_5d TC-5d-06 / G0：validator 全量 + 模拟最小装载）。

合法包 load_pack 全流程；坏引用包被红拦。四个包 README 齐全（TC-5d-13）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.content.loader import load_pack, PackLoadError


@pytest.mark.asyncio
async def test_legal_pack_loads(legal_pack_dir):
    pack = await load_pack(legal_pack_dir)
    assert pack.report.ok
    assert not pack.report.errors
    # 用 registry.resolve 断言 item 注册表非空（不依赖 RegistrySnapshot 内部结构）
    items = pack.modules.get("items") or []
    assert isinstance(items, list) and len(items) > 0
    assert pack.registry.resolve(items[0]["id"], "item") is not None


@pytest.mark.asyncio
async def test_badref_pack_blocked(badref_pack_dir):
    with pytest.raises(PackLoadError) as ei:
        await load_pack(badref_pack_dir)
    kinds = {e.kind for e in ei.value.report.errors}
    assert "R-4" in kinds


def test_four_pack_readmes():
    from conftest import REQUIRED_PACKS, PACKS_DIR  # type: ignore[import-not-found]
    for name in REQUIRED_PACKS:
        readme = PACKS_DIR / name / "README.md"
        assert readme.exists(), f"{name} 缺 README"
        text = readme.read_text(encoding="utf-8")
        assert "破坏点" in text or "不合法" in text or "说明" in text
