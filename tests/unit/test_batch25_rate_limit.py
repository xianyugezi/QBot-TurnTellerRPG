"""批25 · K3：指令限流 `settings.rate_limit`（CakeGame `Global.md:187`）。

设计口径（本批拍板，写进报告）：
  · 形态 = `{interval_sec, count, scope}`；缺省/0 = 不限流（行为与现状逐字段一致）；
  · 位置 = **消息层/路由层**（`assembly/runner._run_command_inner`，进入事务前）；
  · scope：`player`（按玩家，缺省）/ `group`（按群共享额度）；
  · 超限行为 = **人话提示**（「操作太频繁，请稍后再试」）——对齐框架「不静默吞」纪律，
    玩家可懂；固定窗口计数不膨胀、防刷屏；
  · **状态不污染存档**：计数挂 `deps` 运行时属性；时间源 = `ctx["now"]`（deps.dayroll 注入）。

覆盖：元数据 + 校验 / 连续超限被限流（时间注入，非 flaky）/ 窗口重置 / 按玩家与按群 /
未启用不变 / 计数不落存档 / 回归。
"""
from __future__ import annotations

import contextlib
from typing import Any, Dict

from qbot_rpg.assembly.context import AssemblyDeps
from qbot_rpg.assembly.runner import RATE_LIMIT_MESSAGE, run_command
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.commands.router import CommandSpec, Router
from qbot_rpg.commands.sender import Sender
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.registry import Registry
from qbot_rpg.content.validator import check_pack
from qbot_rpg.data import Player, PlayerAttributes


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


def make_player(qid: str = "10001", **over: Any) -> Player:
    base: dict = dict(
        qid=qid, name=f"玩家{qid}", job_id="warrior", level=1, exp=0, hp=100, mp=30,
        currencies={}, inventory=(),
        attributes=PlayerAttributes(base={"hp": 100.0, "mp": 30.0}),
        persistent_state={"location": "town"},
    )
    base.update(over)
    return Player(**base)


def make_settings(**over: Any) -> dict:
    s: dict = {"default_map": "town", "level_cap": 45, "exp_curve": lambda lv: 100 * lv,
               "attr_types": {"hp": "resource"}, "stats": {}}
    s.update(over)
    return s


async def build_env(settings: dict, players=None, clock=None) -> dict:
    players = players or {"10001": make_player()}
    repo = FakeRepo(players)
    queue = PerPlayerQueue(repo)  # type: ignore[arg-type]
    router = Router()
    router.register(CommandSpec("打招呼", handler=lambda parsed, ctx: "你好"))
    sender = Sender()
    deps = AssemblyDeps(repo=repo, game_world=StubGameWorld(),
                        registry=Registry(pack_id="t", generation=1, tables={},
                                          names={}, modules_raw={}),
                        settings=settings, session_mgr=_Session())
    # 时间注入：deps.dayroll → (epoch 秒, 日期键)；clock 为单元素 list（可变）
    t = clock if clock is not None else [1000]
    deps.dayroll = lambda: (t[0], "2026-09-16")  # type: ignore[assignment]
    deps.router = router  # type: ignore[attr-defined]
    deps.queue = queue
    deps.sender = sender  # type: ignore[attr-defined]
    return {"deps": deps, "clock": t}


async def say(env: dict, mid: str, qid: str = "10001", group: str = "g1") -> str:
    return await run_command(
        {"group_id": group, "user_id": qid, "message": "/打招呼", "channel": "group",
         "message_id": mid}, env["deps"])


# ---------------------------------------------------------------------------
# 元数据 + 校验
# ---------------------------------------------------------------------------
def test_k3_metadata_registered() -> None:
    fields = default_field_meta_table().module("settings").fields
    rl = fields.get("rate_limit")
    assert rl is not None and rl.type == "obj"
    for k in ("interval_sec", "count", "scope"):
        assert k in rl.children, f"rate_limit 缺 {k}"
    assert rl.children["scope"].enum == ("player", "group")
    assert "0 = 不限流" in (rl.children["interval_sec"].help or "")


def test_k3_validator_invalid_red() -> None:
    report = check_pack({"settings": {"rate_limit": {"interval_sec": "10"}}})
    assert [e for e in report.errors if e.kind == "R-1" and "interval_sec" in e.field]
    report2 = check_pack({"settings": {"rate_limit": {"scope": "server"}}})
    assert [e for e in report2.errors if e.kind == "R-1" and "scope" in e.field]


def test_k3_validator_valid_and_missing_ok() -> None:
    report = check_pack({"settings": {"rate_limit": {
        "interval_sec": 10, "count": 3, "scope": "group"}}})
    assert not [e for e in report.errors if "rate_limit" in e.field], report.errors
    report2 = check_pack({"settings": {}})
    assert not [e for e in report2.errors if "rate_limit" in e.field]


# ---------------------------------------------------------------------------
# 引擎消费：连续超限被限流（时间注入，非 flaky）
# ---------------------------------------------------------------------------
async def test_k3_player_scope_blocks_over_limit() -> None:
    env = await build_env(make_settings(rate_limit={
        "interval_sec": 10, "count": 2, "scope": "player"}))
    r1 = await say(env, "m1")
    r2 = await say(env, "m2")
    r3 = await say(env, "m3")
    assert r1.endswith("你好") and r2.endswith("你好")
    assert r3 == RATE_LIMIT_MESSAGE, r3


async def test_k3_window_reset_after_interval() -> None:
    env = await build_env(make_settings(rate_limit={
        "interval_sec": 10, "count": 1, "scope": "player"}))
    assert (await say(env, "m1")).endswith("你好")
    assert await say(env, "m2") == RATE_LIMIT_MESSAGE
    env["clock"][0] = 1010  # 窗口滚动（时间注入）
    assert (await say(env, "m3")).endswith("你好")
    assert await say(env, "m4") == RATE_LIMIT_MESSAGE


async def test_k3_player_scope_isolated_between_players() -> None:
    players = {"10001": make_player("10001"), "10002": make_player("10002")}
    env = await build_env(make_settings(rate_limit={
        "interval_sec": 10, "count": 1, "scope": "player"}), players=players)
    assert (await say(env, "m1", qid="10001")).endswith("你好")
    assert await say(env, "m2", qid="10001") == RATE_LIMIT_MESSAGE
    assert (await say(env, "m3", qid="10002")).endswith("你好")


async def test_k3_group_scope_shared() -> None:
    players = {"10001": make_player("10001"), "10002": make_player("10002")}
    env = await build_env(make_settings(rate_limit={
        "interval_sec": 10, "count": 1, "scope": "group"}), players=players)
    assert (await say(env, "m1", qid="10001", group="g1")).endswith("你好")
    # 同群他人共享额度 → 被限
    assert await say(env, "m2", qid="10002", group="g1") == RATE_LIMIT_MESSAGE
    # 另一群不共享
    assert (await say(env, "m3", qid="10002", group="g2")).endswith("你好")


# ---------------------------------------------------------------------------
# 未启用 → 行为不变；计数不污染存档
# ---------------------------------------------------------------------------
async def test_k3_disabled_no_limiting() -> None:
    env = await build_env(make_settings())
    for i in range(10):
        assert (await say(env, f"m{i}")).endswith("你好")
    # interval/count = 0 → 同样不限流
    env2 = await build_env(make_settings(rate_limit={
        "interval_sec": 0, "count": 0, "scope": "player"}))
    for i in range(10):
        assert (await say(env2, f"n{i}")).endswith("你好")


async def test_k3_counts_not_persisted() -> None:
    env = await build_env(make_settings(rate_limit={
        "interval_sec": 10, "count": 1, "scope": "player"}))
    await say(env, "m1")
    assert await say(env, "m2") == RATE_LIMIT_MESSAGE
    # 计数只在 deps 运行时属性
    assert isinstance(getattr(env["deps"], "_rate_limit_state"), dict)
    player = env["deps"].repo._players["10001"]
    assert "rate_limit" not in player.persistent_state
    assert "_rate_limit_state" not in player.persistent_state


# ---------------------------------------------------------------------------
# 回归：不带 rate_limit → 行为逐字段一致
# ---------------------------------------------------------------------------
async def test_k3_regression_without_config_identical() -> None:
    a = await build_env(make_settings())
    b = await build_env(make_settings(rate_limit=None))
    ra = await say(a, "m1")
    rb = await say(b, "m1")
    assert ra == rb and ra.endswith("你好")
