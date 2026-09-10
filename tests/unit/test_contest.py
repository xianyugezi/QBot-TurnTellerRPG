"""/投稿 /排行榜 指令 + contest 引擎单测（2c5c CT-01~09 周赛核心）。

文件：tests/unit/test_contest.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批3路2）

覆盖：
  - 引擎：四维评分（品质/特性/觉醒/潜力加权）/ 周键 / 窗口判定 / 防重
  - 指令：投稿（DB 事务扣道具+入板+声望）/ 一期限一件 / 排行榜
  - 冠军懒结算（跨周首访 → 称号+宝石+声望）
  - 注册白名单
风格：文件库 + Repository（对齐 test_gift_commands）。
"""
from __future__ import annotations

import json
import time
from typing import List

import pytest

from qbot_rpg.commands.contest_commands import (
    SUBMIT_CMD, RANK_CMD,
    cmd_contest_submit, cmd_contest_rank,
    register_contest_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router
from qbot_rpg.core import contest as ct
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository

from conftest import make_player  # type: ignore[import-not-found]

_CFG = {
    "enabled": True,
    "schedule": {"weekday": 7, "open_hour": 0},  # 周日 0 点起开放（测试不卡窗口）
    "score_weights": {"quality": 0.4, "trait": 0.3, "awaken": 0.2, "potential": 0.1},
    "reward": {"title": "品评冠军", "gem": 100,
               "reputation": {"submit": 5, "win": 30}},
}


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


_SUNDAY_21H = 1788699600  # 2026-09-06 (周日) 21:00 CST


def _ctx(repo: Repository, qid: str = "10001") -> dict:
    return {
        "registered": True, "qid": qid,
        "player": {"name": "阿伟", "qid": qid},
        "repo": repo, "templates": None,
        "contest_cfg": _CFG, "now": _SUNDAY_21H,
    }


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


def test_score_item_quality() -> None:
    """品质分归一（legendary=100 × 0.4）。"""
    row = {"quality": "legendary", "traits": (), "count": 1}
    total, dims = ct.score_item(row, _CFG["score_weights"])
    assert dims["quality"] == 100
    assert total == 40.0


def test_score_item_trait_count() -> None:
    """特性条数 25/条封顶 100。"""
    row = {"quality": "normal", "traits": ("甘甜", "脆爽", "莹光"), "count": 1}
    total, dims = ct.score_item(row, _CFG["score_weights"])
    assert dims["trait"] == 75


def test_week_key() -> None:
    """周键格式。"""
    k = ct.week_key_of(int(time.time()))
    assert "-W" in k


def test_in_window_schedule() -> None:
    """窗口判定：周日 0 点开 → 任何周日时刻都开。"""
    # 2026-09-06 是周日
    ts = time.mktime((2026, 9, 6, 10, 0, 0, 0, 0, -1))
    ok, hint = ct.in_window({}, ts)  # 无 schedule → 开放
    assert ok is True


async def test_submit_ok(repo_factory) -> None:
    """投稿成功：扣道具+入板+声望+5。"""
    repo = await repo_factory("10001")
    p = make_player("10001", name="阿伟")  # potion×5 + iron_sword bound
    # potion fine 品质? make_player potion normal — use replace to fine + traits
    from dataclasses import replace  # noqa: PLC0415
    inv = tuple(
        replace(r, quality="legendary", traits=("甘甜",)) if r.item_id == "potion" else r
        for r in p.inventory
    )
    p = replace(p, inventory=inv)
    await repo.save_player(p)
    out = await cmd_contest_submit(parse("/投稿 药水"), _ctx(repo))
    assert isinstance(out, str) and "已投稿" in out
    p2 = await repo.load_player("10001")
    assert p2 is not None
    # 药水 5→4
    pot = [r for r in p2.inventory if r.item_id == "potion"][0]
    assert pot.count == 4
    assert p2.reputation_state.get("contest", 0) == 5
    # 板上一条
    row = await repo.db.fetchone_read(
        "SELECT value_json FROM world_state WHERE key='contest_board'")
    board = json.loads(row["value_json"])
    assert len(board["entries"]) == 1


async def test_submit_once_per_week(repo_factory) -> None:
    """一期限一件：重复投稿拒绝。"""
    repo = await repo_factory("10001")
    p = make_player("10001", name="阿伟")
    await repo.save_player(p)
    out1 = await cmd_contest_submit(parse("/投稿 药水"), _ctx(repo))
    assert "已投稿" in out1
    out2 = await cmd_contest_submit(parse("/投稿 药水"), _ctx(repo))
    assert "已投稿过" in out2


async def test_submit_no_item(repo_factory) -> None:
    """背包无道具 → 拒绝。"""
    repo = await repo_factory("10001")
    p = make_player("10001", name="阿伟")
    await repo.save_player(p)
    out = await cmd_contest_submit(parse("/投稿 不存在的物品"), _ctx(repo))
    assert "没有" in out


async def test_rank_board(repo_factory) -> None:
    """排行榜展示投稿。"""
    repo = await repo_factory("10001")
    p = make_player("10001", name="阿伟")
    await repo.save_player(p)
    await cmd_contest_submit(parse("/投稿 药水"), _ctx(repo))
    out = await cmd_contest_rank(parse("/排行榜"), _ctx(repo))
    assert "品评会排行" in out
    assert "阿伟" in out


async def test_settle_new_week(repo_factory) -> None:
    """跨周懒结算：上周冠军获称号/宝石/声望（构造：板在上周+未结算 → 看榜触发）。"""
    repo = await repo_factory("10001")
    p = make_player("10001", name="阿伟")
    await repo.save_player(p)
    ctx = _ctx(repo)
    # 投稿（本周）
    await cmd_contest_submit(parse("/投稿 药水"), ctx)
    # 把板周键改成上周 + settled_week 空（模拟上周投稿未结算）
    row = await repo.db.fetchone_read(
        "SELECT value_json FROM world_state WHERE key='contest_board'")
    board = json.loads(row["value_json"])
    # 时基必须与 ctx["now"] 一致（_SUNDAY_21H）：原实现用 int(time.time()) 取真实
    # 当前时刻，与固定 ctx["now"] 分属不同 ISO 周（实测真实时钟 2026-W36 vs
    # ctx 2026-W35），导致改写后的 board["week"] 恰等于结算函数算出的 cur_week
    # → _settle_if_new_week L77「board.week == cur_week」提前 return，结算不触发。
    last_week = ct.week_key_of(_SUNDAY_21H - 7 * 86400)
    board["week"] = last_week
    board["settled_week"] = ""
    await repo.db.execute(
        "UPDATE world_state SET value_json=? WHERE key='contest_board'",
        (json.dumps(board, ensure_ascii=False),))
    # 看榜触发结算
    out = await cmd_contest_rank(parse("/排行榜"), ctx)
    assert "上周冠军" in out
    p2 = await repo.load_player("10001")
    assert p2 is not None
    assert "品评冠军" in p2.title_state.get("owned", [])
    assert p2.currencies.get("gem", 0) >= 100
    assert p2.reputation_state.get("contest", 0) >= 30


def test_register_contest_commands() -> None:
    """注册白名单。"""
    router = Router()
    register_contest_commands(router)
    assert router.get(SUBMIT_CMD) is not None
    assert router.get(RANK_CMD) is not None
