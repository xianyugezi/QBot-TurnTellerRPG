"""批25 · K2：按状态禁用指令 `settings.command_gates`（CakeGame `Global.md:143-145`）。

依据 `Limit_ins.ws/iw/fc`「虚弱状态下禁用的指令 / 野外地图中禁用 / 被强制战斗中禁用」。
设计口径（本批拍板，写进报告）：
  · 形态 = `{weak: [指令名], wild: [指令名], forced_battle: [指令名]}`（按状态分键、每态一列表）；
  · **沿用既有判定链**：与未注册 / GM 权限同处 `assembly/runner._run_command_inner`
    路由后、handler 前（不散落多套）；GM 指令不受玩家状态门禁影响；
  · 状态口径：weak = `weak_remaining_sec>0`/`weakened`；wild = 当前地图有非空 `monsters`；
    forced_battle = `in_battle` 且战斗快照 `battle_type=="ambush"`；
  · 命中 → 人话提示；非命中状态/指令 → 照常执行。

覆盖：元数据 + 校验 / 引擎（三态各禁 + 非命中照常）/ 回归（不带配置行为不变）。
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.assembly.runner import run_command
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.commands.router import CommandSpec, Router
from qbot_rpg.commands.sender import Sender
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.registry import Registry
from qbot_rpg.content.validator import check_pack
from qbot_rpg.data import Player, PlayerAttributes
from qbot_rpg.web import api


# ---------------------------------------------------------------------------
# 夹具（自含；对齐 test_assembly_runner 的鸭子类型 repo/队列）
# ---------------------------------------------------------------------------
class FakeTx:
    def __init__(self, repo: "FakeRepo") -> None:
        self._repo = repo

    async def idem_exists(self, key: Any) -> bool:
        return False

    async def write_idem_key(self, key: Any) -> None:
        pass

    async def upsert_player(self, player: Any) -> None:
        self._repo._player = player


class FakeRepo:
    def __init__(self, player: Any = None) -> None:
        self._player = player

    async def load_player(self, qid: str):  # noqa: ANN001
        p = self._player
        return p if (p is not None and p.qid == str(qid)) else None

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
    def __init__(self, view: Any = None) -> None:
        self._view = view

    def get_active(self, qid: str):  # noqa: ANN001
        return self._view


def make_player(**over: Any) -> Player:
    base: dict = dict(
        qid="10001", name="阿伟", job_id="warrior", level=5, exp=0, hp=100, mp=30,
        currencies={"coins": 10}, inventory=(),
        attributes=PlayerAttributes(base={"hp": 100.0, "mp": 30.0}),
        persistent_state={"location": "town"},
    )
    base.update(over)
    return Player(**base)


def make_registry(with_wild: bool = False) -> Registry:
    tables: dict = {
        "job": {"warrior": SimpleNamespace(name="战士")},
        "effect": {}, "item": {}, "shop": {},
    }
    if with_wild:
        tables["map"] = {
            "wild_map": SimpleNamespace(raw={"id": "wild_map", "name": "荒原",
                                             "monsters": [{"enemy": "slime", "count": 1}]}),
            "town": SimpleNamespace(raw={"id": "town", "name": "镇子", "monsters": []}),
        }
    return Registry(pack_id="t", generation=1, tables=tables, names={}, modules_raw={})


def make_settings(**over: Any) -> dict:
    s: dict = {
        "default_map": "town", "level_cap": 45, "shortcut_max": 20,
        "exp_curve": lambda lv: 100 * lv, "conditional_rules": [],
        "attr_types": {"hp": "resource", "mp": "resource"},
        "stats": {"hp": {"base": 100}, "mp": {"base": 30}},
    }
    s.update(over)
    return s


async def build_env(player: Player, *, settings: dict, session: Any = None,
                    with_wild: bool = False) -> dict:
    repo = FakeRepo(player)
    queue = PerPlayerQueue(repo)  # type: ignore[arg-type]
    router = Router()
    router.register(CommandSpec("状态", handler=lambda parsed, ctx: "面板"))
    router.register(CommandSpec("打招呼", handler=lambda parsed, ctx: "你好"))
    sender = Sender()
    deps = AssemblyDeps(repo=repo, game_world=StubGameWorld(),
                        registry=make_registry(with_wild), settings=settings,
                        session_mgr=session or _Session(None))
    deps.router = router  # type: ignore[attr-defined]
    deps.queue = queue
    deps.sender = sender  # type: ignore[attr-defined]
    return {"deps": deps, "event": {
        "group_id": "g1", "user_id": "10001", "message": "/状态",
        "channel": "group", "message_id": "m1"}}


async def run(env: dict, message: str, mid: str = None) -> str:
    event = dict(env["event"])
    event["message"] = message
    if mid:
        event["message_id"] = mid
    return await run_command(event, env["deps"])


# ---------------------------------------------------------------------------
# 元数据 + 校验
# ---------------------------------------------------------------------------
def test_k2_metadata_registered() -> None:
    fields = default_field_meta_table().module("settings").fields
    cg = fields.get("command_gates")
    assert cg is not None and cg.type == "obj"
    for k in ("weak", "wild", "forced_battle"):
        assert k in cg.children, f"command_gates 缺 {k}"
        assert cg.children[k].type == "list"
        assert cg.children[k].element.type == "str"


def test_k2_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_k2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_k2", "version": "1", "schema_version": 1, "modules": ["settings"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "settings.json").write_text(json.dumps(
        {"command_gates": {"weak": ["锁定"], "wild": ["地图"],
                           "forced_battle": ["回城"]}}, ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_k2", "settings", "command_gates", root=tmp_path)
    assert d["name"] == "按状态禁用指令"
    keys = {f["key"] for f in d["fields"]}
    assert {"weak", "wild", "forced_battle"} <= keys


def test_k2_validator_invalid_red() -> None:
    report = check_pack({"settings": {"command_gates": {"weak": "状态"}}})
    assert [e for e in report.errors if e.kind == "R-1" and "weak" in e.field]
    report2 = check_pack({"settings": {"command_gates": {"wild": ["状态", 5]}}})
    assert [e for e in report2.errors if e.kind == "R-1" and "wild" in e.field]


def test_k2_validator_valid_and_missing_ok() -> None:
    report = check_pack({"settings": {"command_gates": {
        "weak": ["锁定"], "wild": ["地图"], "forced_battle": ["回城"]}}})
    assert not [e for e in report.errors if "command_gates" in e.field], report.errors
    report2 = check_pack({"settings": {}})
    assert not [e for e in report2.errors if "command_gates" in e.field]


# ---------------------------------------------------------------------------
# 引擎消费：三态各禁（贴提示）+ 非命中照常
# ---------------------------------------------------------------------------
async def test_k2_weak_blocks() -> None:
    player = make_player(persistent_state={"location": "town",
                                           "weak_until": "2099-01-01T00:00:00+00:00"})
    env = await build_env(player, settings=make_settings(command_gates={"weak": ["状态"]}))
    out = await run(env, "/状态")
    assert out == "当前虚弱状态，暂不能使用「状态」", out
    # 未列入 weak 的指令照常
    env["event"]["message_id"] = "m2"
    assert (await run(env, "/打招呼", "m2")).endswith("你好")


async def test_k2_wild_blocks() -> None:
    player = make_player(persistent_state={"location": "wild_map"})
    env = await build_env(player, settings=make_settings(command_gates={"wild": ["状态"]}),
                          with_wild=True)
    out = await run(env, "/状态")
    assert out == "当前野外地图，暂不能使用「状态」", out


async def test_k2_wild_not_blocked_in_safe_map() -> None:
    player = make_player(persistent_state={"location": "town"})
    env = await build_env(player, settings=make_settings(command_gates={"wild": ["状态"]}),
                          with_wild=True)
    assert (await run(env, "/状态")).endswith("面板")


async def test_k2_forced_battle_blocks() -> None:
    view = SimpleNamespace(session_type="battle", payload={"battle_type": "ambush"})
    player = make_player(persistent_state={"location": "town"})
    env = await build_env(player,
                          settings=make_settings(command_gates={"forced_battle": ["状态"]}),
                          session=_Session(view))
    out = await run(env, "/状态")
    assert out == "当前被强制战斗中，暂不能使用「状态」", out


async def test_k2_normal_battle_does_not_trigger_forced_gate() -> None:
    view = SimpleNamespace(session_type="battle", payload={"battle_type": "dungeon"})
    player = make_player(persistent_state={"location": "town"})
    env = await build_env(player,
                          settings=make_settings(command_gates={"forced_battle": ["状态"]}),
                          session=_Session(view))
    assert (await run(env, "/状态")).endswith("面板")


async def test_k2_non_gated_command_runs_in_weak() -> None:
    player = make_player(persistent_state={"location": "town",
                                           "weak_until": "2099-01-01T00:00:00+00:00"})
    env = await build_env(player, settings=make_settings(command_gates={"weak": ["锁定"]}))
    assert (await run(env, "/状态")).endswith("面板")


# ---------------------------------------------------------------------------
# 回归：不带 command_gates → 行为逐字段一致
# ---------------------------------------------------------------------------
async def test_k2_regression_without_config_identical() -> None:
    weak = make_player(persistent_state={"location": "town",
                                         "weak_until": "2099-01-01T00:00:00+00:00"})
    env = await build_env(weak, settings=make_settings())
    assert (await run(env, "/状态")).endswith("面板")
    # ctx 仍带虚弱镜像（只是没有门禁配置 → 不拦）
    ctx = await make_context(env["event"], env["deps"])
    assert ctx["weak_remaining_sec"] > 0
