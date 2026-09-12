"""/赠送 指令壳单测（定稿 L1286/L953：原子转移 + 绑定禁赠 + 目标寻址）。

文件：tests/unit/test_gift_commands.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批2路1）

覆盖：
  - 成功赠送：A 扣 B 加（同事务双写）
  - 绑定物品禁赠
  - 数量不足拒绝
  - 自己给自己拒绝
  - 目标未注册拒绝
  - 角色名寻址（反查 qid）
  - 注册门槛 / 缺参
  - 注册白名单
风格：文件库（WAL）+ Repository（对齐 test_idem_processing）。
"""
from __future__ import annotations

from typing import List

import pytest

from qbot_rpg.commands.gift_commands import (
    GIFT_CMD,
    cmd_gift,
    register_gift_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository

from conftest import make_player  # type: ignore[import-not-found]


@pytest.fixture
async def repo_factory(tmp_path):
    made: List[Repository] = []
    counter = [0]

    async def factory(qid: str = "10001") -> Repository:
        counter[0] += 1
        db = Database(str(tmp_path / f"repo_{counter[0]}.db"))
        repo = Repository(db)
        made.append(repo)
        return repo

    yield factory
    for repo in made:
        await repo.close()


def _ctx(repo: Repository, qid: str = "10001") -> dict:
    return {
        "registered": True,
        "qid": qid,
        "player": {"name": "阿伟", "qid": qid},
        "repo": repo,
        "templates": None,
    }


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


async def _inv_item(repo: Repository, qid: str, item_id: str) -> int:
    p = await repo.load_player(qid)
    if p is None:
        return -1
    return sum(int(r.count) for r in p.inventory if str(r.item_id) == item_id)


async def test_gift_ok_atomic(repo_factory) -> None:
    """成功：A 扣 2 药水 → B 加 2（双写同事务）。"""
    repo = await repo_factory("10001")
    await repo.save_player(make_player("10001", name="阿伟"))
    await repo.save_player(make_player("20002", name="小美"))
    out = await cmd_gift(parse("/赠送 药水*2 20002"), _ctx(repo))
    assert isinstance(out, str) and "已赠送" in out
    assert await _inv_item(repo, "10001", "potion") == 3
    assert await _inv_item(repo, "20002", "potion") == 7


async def test_gift_by_name_lookup(repo_factory) -> None:
    """角色名寻址：/赠送 药水 小美 → 反查 qid 成功。"""
    repo = await repo_factory("10001")
    await repo.save_player(make_player("10001", name="阿伟"))
    await repo.save_player(make_player("20002", name="小美"))
    out = await cmd_gift(parse("/赠送 药水 小美"), _ctx(repo))
    assert isinstance(out, str) and "已赠送" in out
    assert "小美" in out
    assert await _inv_item(repo, "20002", "potion") == 6


async def test_gift_bound_rejected(repo_factory) -> None:
    """绑定物品（铁剑 bound=True）→ 拒绝。"""
    repo = await repo_factory("10001")
    await repo.save_player(make_player("10001", name="阿伟"))
    await repo.save_player(make_player("20002", name="小美"))
    out = await cmd_gift(parse("/赠送 铁剑 20002"), _ctx(repo))
    assert isinstance(out, str) and "绑定" in out
    assert await _inv_item(repo, "10001", "iron_sword") == 1  # 未扣
    assert await _inv_item(repo, "20002", "iron_sword") == 1  # B 自带 1 把，未新增


async def test_gift_self_rejected(repo_factory) -> None:
    """自己给自己 → 拒绝。"""
    repo = await repo_factory("10001")
    await repo.save_player(make_player("10001", name="阿伟"))
    out = await cmd_gift(parse("/赠送 药水 10001"), _ctx(repo))
    assert isinstance(out, str) and "自己" in out


async def test_gift_insufficient(repo_factory) -> None:
    """数量不足 → 拒绝。"""
    repo = await repo_factory("10001")
    await repo.save_player(make_player("10001", name="阿伟"))
    await repo.save_player(make_player("20002", name="小美"))
    out = await cmd_gift(parse("/赠送 药水*99 20002"), _ctx(repo))
    assert isinstance(out, str) and ("不足" in out or "没有" in out)
    assert await _inv_item(repo, "20002", "potion") == 5  # 未加


async def test_gift_target_missing(repo_factory) -> None:
    """目标不存在 → 拒绝。"""
    repo = await repo_factory("10001")
    await repo.save_player(make_player("10001", name="阿伟"))
    out = await cmd_gift(parse("/赠送 药水 99999"), _ctx(repo))
    assert isinstance(out, str) and "不存在" in out


async def test_gift_no_repo_ctx(repo_factory) -> None:
    """无 repo 注入 → 系统未启用提示。"""
    repo = await repo_factory("10001")
    ctx = _ctx(repo)
    ctx["repo"] = None
    out = await cmd_gift(parse("/赠送 药水 20002"), ctx)
    assert isinstance(out, str) and ("未启用" in out or "未开放" in out)


def test_gift_register_gate() -> None:
    """未注册 → 注册门槛（同步路径）。"""
    ctx = {"registered": False, "player": None, "repo": None}
    out = cmd_gift(parse("/赠送 药水 20002"), ctx)
    assert "请先注册" in out


def test_gift_missing_args() -> None:
    """缺参 → 缺少参数。"""
    ctx = {"registered": True, "player": {"name": "阿伟"}, "repo": None}
    out = cmd_gift(parse("/赠送"), ctx)
    assert "缺少参数" in out
    out2 = cmd_gift(parse("/赠送 药水"), ctx)
    assert "接收玩家" in out2


def test_register_gift_command() -> None:
    """注册白名单。"""
    router = Router()
    register_gift_commands(router)
    spec = router.get(GIFT_CMD)
    assert spec is not None
    assert spec.whitelisted
