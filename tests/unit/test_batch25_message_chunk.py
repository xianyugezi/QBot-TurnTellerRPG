"""批25 · K4：消息分段长度上限 `settings.message_chunk_len`（CakeGame `Global.md:46`）。

设计口径（本批拍板，写进报告）：
  · 形态 = int ≥1；缺省/0 = 沿用框架默认单条预算（QQ 4000 字）；
  · 引擎 = **运行时发送分段**：`commands/sender.Sender.default_budget`（装配层按 settings
    注入；同一出口含战斗正文），显式 `send(budget=…)` 优先；
  · **与既有「结构化行 ≤14 全角」模板排版门禁是两件事**：后者是模板文本规范（静态校验），
    本项是发送前按上限自动分段（防 QQ 截断）。

覆盖：元数据 + 校验 / Sender 分段数值 / 装配端到端分段 / 0 与缺省不改变默认行为。
"""
from __future__ import annotations

import contextlib
from typing import Any, Dict

from qbot_rpg.assembly.context import AssemblyDeps
from qbot_rpg.assembly.runner import run_command
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.commands.router import CommandSpec, Router
from qbot_rpg.commands.sender import DEFAULT_LENGTH_BUDGET, Sender, segment_by_length
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.registry import Registry
from qbot_rpg.content.validator import check_pack
from qbot_rpg.data import Player, PlayerAttributes

LONG = "长" * 12


class FakeTx:
    def __init__(self, repo: "FakeRepo") -> None:
        self._repo = repo

    async def idem_exists(self, key: Any) -> bool:
        return False

    async def write_idem_key(self, key: Any) -> None:
        pass

    async def upsert_player(self, player: Any) -> None:
        self._repo._players[player.qid] = player


class FakeRepo:
    def __init__(self, players: Dict[str, Player]) -> None:
        self._players = dict(players)

    async def load_player(self, qid: str):  # noqa: ANN001
        return self._players.get(str(qid))

    async def idem_claim(self, key: Any) -> bool:
        return False

    @contextlib.asynccontextmanager
    async def tx(self):
        yield FakeTx(self)

    async def cleanup_idem_keys(self, retention_days: float = 7.0, **kw: Any) -> int:
        return 0


class StubGameWorld:
    def get_map(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def monster_pool(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def get_npcs(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError


class _Session:
    def get_active(self, qid: str):  # noqa: ANN001
        return None


def make_player(qid: str = "10001") -> Player:
    return Player(
        qid=qid, name="阿伟", job_id="warrior", level=1, exp=0, hp=100, mp=30,
        currencies={}, inventory=(),
        attributes=PlayerAttributes(base={"hp": 100.0, "mp": 30.0}),
        persistent_state={"location": "town"},
    )


def make_settings(**over: Any) -> dict:
    s: dict = {"default_map": "town", "level_cap": 45, "exp_curve": lambda lv: 100 * lv,
               "attr_types": {"hp": "resource"}, "stats": {}}
    s.update(over)
    return s


async def build_env(settings: dict) -> dict:
    repo = FakeRepo({"10001": make_player()})
    queue = PerPlayerQueue(repo)  # type: ignore[arg-type]
    router = Router()
    router.register(CommandSpec("长文", handler=lambda parsed, ctx: LONG))
    sender = Sender()
    deps = AssemblyDeps(repo=repo, game_world=StubGameWorld(),
                        registry=Registry(pack_id="t", generation=1, tables={},
                                          names={}, modules_raw={}),
                        settings=settings, session_mgr=_Session())
    deps.router = router  # type: ignore[attr-defined]
    deps.queue = queue
    deps.sender = sender  # type: ignore[attr-defined]
    return {"deps": deps, "sender": sender}


async def run_long(env: dict, mid: str = "m1") -> str:
    return await run_command(
        {"group_id": "g1", "user_id": "10001", "message": "/长文", "channel": "group",
         "message_id": mid}, env["deps"])


# ---------------------------------------------------------------------------
# 元数据 + 校验
# ---------------------------------------------------------------------------
def test_k4_metadata_registered() -> None:
    fm = default_field_meta_table().module("settings").fields.get("message_chunk_len")
    assert fm is not None, "settings 缺 message_chunk_len 登记"
    assert fm.type == "int"
    assert fm.label == "消息分段长度上限"
    assert "运行时发送分段" in (fm.help or "")


def test_k4_validator_invalid_red() -> None:
    report = check_pack({"settings": {"message_chunk_len": "20"}})
    assert [e for e in report.errors if e.kind == "R-1" and "message_chunk_len" in e.field]
    report2 = check_pack({"settings": {"message_chunk_len": -1}})
    assert [e for e in report2.errors if e.kind == "R-2" and "message_chunk_len" in e.field]


def test_k4_validator_valid_and_missing_ok() -> None:
    report = check_pack({"settings": {"message_chunk_len": 20}})
    assert not [e for e in report.errors if "message_chunk_len" in e.field], report.errors
    report2 = check_pack({"settings": {"message_chunk_len": 0}})
    assert not [e for e in report2.errors if "message_chunk_len" in e.field]
    report3 = check_pack({"settings": {}})
    assert not [e for e in report3.errors if "message_chunk_len" in e.field]


# ---------------------------------------------------------------------------
# Sender 分段（数值级）
# ---------------------------------------------------------------------------
def test_k4_sender_default_budget_segments() -> None:
    s = Sender(default_budget=4)
    segs = s.send("aaaaaaaaaa")  # 10 字符 / 每段 4 → 4+4+2
    assert segs == ["aaaa", "aaaa", "aa"], segs
    assert s.delivered == ["aaaa", "aaaa", "aa"]
    # 显式 budget 优先于 default_budget
    assert Sender(default_budget=4).send("aaaaaaaaaa", budget=10) == ["aaaaaaaaaa"]


def test_k4_sender_default_budget_validation() -> None:
    for bad in (0, -1, "5", True):
        try:
            Sender(default_budget=bad)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"default_budget={bad!r} 应报错")


def test_k4_sender_default_unchanged() -> None:
    """缺省预算仍是框架默认（QQ 4000），旧调用逐字段一致。"""
    s = Sender()
    assert s.default_budget == DEFAULT_LENGTH_BUDGET
    assert s.send("你好") == ["你好"]
    assert s.send("a" * DEFAULT_LENGTH_BUDGET) == ["a" * DEFAULT_LENGTH_BUDGET]
    assert segment_by_length("a" * (DEFAULT_LENGTH_BUDGET + 1)) == [
        "a" * DEFAULT_LENGTH_BUDGET, "a"]


# ---------------------------------------------------------------------------
# 装配端到端：settings.message_chunk_len → 发送分段
# ---------------------------------------------------------------------------
async def test_k4_runner_applies_chunk_len() -> None:
    env = await build_env(make_settings(message_chunk_len=5))
    reply = await run_long(env)
    delivered = env["sender"].delivered
    assert all(len(seg) <= 5 for seg in delivered), delivered
    assert len(delivered) > 1, delivered
    # 分段不吞内容：拼回 == 完整体（含前缀注入 + 12 个「长」）
    assert "".join(delivered).count("长") == 12
    # 返回串 = 完整正文（未因分段而截断）
    assert "长" * 12 in reply


async def test_k4_runner_zero_and_missing_use_default() -> None:
    for settings in (make_settings(message_chunk_len=0), make_settings()):
        env = await build_env(settings)
        await run_long(env)
        delivered = env["sender"].delivered
        assert len(delivered) == 1, delivered
        assert len(delivered[0]) <= DEFAULT_LENGTH_BUDGET
