"""pytest 插件：内容包自带测试的通用 fixture（E3 · ``qbot_rpg.testing``）。

由 ``scripts/run_pack_tests.py`` 以 ``-p qbot_rpg.testing.pytest_plugin`` 自动加载，
并注入 ``--pack-root <包目录>``。包测试可直接使用：

- ``pack_root``（session）：以该包为内容根（``--pack-root`` 指向的目录）；
- ``pack_deps``（function）：以该包为内容根装配好的 deps（内存库；用完自动关）。

**通用**：本插件不认识任何包名；包名只由 ``--pack-root`` 运行时给出。
单独 import ``qbot_rpg.testing`` 不会加载本模块（pytest 才需要它）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from qbot_rpg.assembly.testing_support import (
    MANIFEST_FILE,
    build_pack_deps,
    close_pack_deps,
)


def pytest_addoption(parser: Any) -> None:
    """注册 ``--pack-root``（内容包目录；由 run_pack_tests.py 注入）。"""
    group = parser.getgroup("qbot-content-pack")
    group.addoption(
        "--pack-root",
        dest="qbot_pack_root",
        default=None,
        metavar="DIR",
        help="内容包目录（以该包为内容根运行其 tests/）；由 scripts/run_pack_tests.py 注入",
    )


@pytest.fixture(scope="session")
def pack_root(request: pytest.FixtureRequest) -> Path:
    """以该包为内容根的目录（``--pack-root``；缺失/非法 → 人话 UsageError）。"""
    raw = request.config.getoption("qbot_pack_root")
    if not raw:
        raise pytest.UsageError(
            "未提供 --pack-root；请用 scripts/run_pack_tests.py --pack <名> 运行包测试"
        )
    path = Path(str(raw))
    if not (path / MANIFEST_FILE).is_file():
        raise pytest.UsageError(
            f"--pack-root 不是内容包目录（缺 {MANIFEST_FILE}）：{path}"
        )
    return path


@pytest.fixture
async def pack_deps(pack_root: Path) -> AsyncIterator[Any]:
    """以 ``pack_root`` 为内容根装配的 deps（内存库；测试结束自动关库）。"""
    deps = await build_pack_deps(pack_root, enable_pack_ext=True)
    try:
        yield deps
    finally:
        await close_pack_deps(deps)
