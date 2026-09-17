"""批32 · A1：数据包保护（框架 §6.12-25「作者更新中」）。

定稿原文（`docs/审查参考/RPG回合制框架设计文档.md` L1191-1197）：
  · 编辑器【通用设置】开启「数据包保护」：编辑期间玩家发送任何指令 →
    返回「作者更新中，请稍后再试...」；
  · 关闭保护 / 保存发布后玩家恢复正常游玩；
  · 用于大改版时避免玩家用半成品数据游玩。

本批最小实现（复用既有机制，门禁只能更严）：
  · `settings.pack_protection.enabled`（缺省 false = 现状逐字段一致）；
  · 开启 → 进入游玩前跑**既有包校验**（`loader.build_pack`）→ 红拦 + 保护期升级的
    「manifest 声明但缺模块数据（Y-6）」→ 拒绝进入游玩并给人话提示（哪个包/什么问题/去哪改）；
  · 开启 → 玩家（非 GM）指令在既有判定链统一返回「作者更新中，请稍后再试...」；
  · **不影响编辑器**：门禁只在 `assembly/bootstrap.py` 与 `assembly/runner.py`，编辑器不动。

测试只写临时目录/临时内容根；不触碰真实 `content/`（批19.1 门禁）。
"""
from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qbot_rpg.assembly.bootstrap import bootstrap
from qbot_rpg.assembly.context import AssemblyDeps
from qbot_rpg.assembly.runner import (
    _pack_protection_gate,
    run_command,
)
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.commands.router import PERM_GM, CommandSpec, Router
from qbot_rpg.commands.sender import Sender
from qbot_rpg.content import pack_protection as pp
from qbot_rpg.content.field_meta import SETTINGS_FIELDS, default_field_meta_table

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"


# ---------------------------------------------------------------------------
# 夹具：临时内容包（半成品 / 完整包副本）
# ---------------------------------------------------------------------------
def _write_pack(root: Path, *, modules: list, files: dict, settings: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(
        {"name": "半成品包", "version": "1", "schema_version": 1, "modules": modules},
        ensure_ascii=False), encoding="utf-8")
    for name, data in files.items():
        (root / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False),
                                           encoding="utf-8")
    (root / "settings.json").write_text(json.dumps(settings, ensure_ascii=False),
                                        encoding="utf-8")
    return root


def _halfbaked(root: Path, *, enabled: bool) -> Path:
    """声明 items + enemies，只写 items.json（enemies.json 缺失 = 半成品）。"""
    settings = {"pack_protection": {"enabled": True}} if enabled else {}
    return _write_pack(
        root, modules=["items", "enemies"],
        files={"items": [{"id": "i1", "name": "铁剑"}]},
        settings=settings)


# ---------------------------------------------------------------------------
# 开关缺省：零额外校验（对拍「行为与现状逐字段一致」）
# ---------------------------------------------------------------------------
def test_off_short_circuits_without_validation(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root = _halfbaked(tmp_path / "p", enabled=False)
    called = {"n": 0}

    def _boom(*_a: Any, **_k: Any) -> Any:
        called["n"] += 1
        raise AssertionError("未开启保护时不得跑包校验")

    monkeypatch.setattr(pp, "build_pack", _boom)
    gate = pp.play_gate(root)
    assert gate["enabled"] is False
    assert gate["allowed"] is True
    assert gate["problems"] == [] and gate["message"] == ""
    assert called["n"] == 0


def test_off_regression_same_as_baseline(tmp_path: Path) -> None:
    """未配置/关闭 → 半成品也不拦（与现状一致：loader 的缺模块只黄提示）。"""
    root = _halfbaked(tmp_path / "p", enabled=False)
    assert pp.play_gate(root)["allowed"] is True
    assert pp.player_notice({}) is None
    assert pp.player_notice({"pack_protection": {"enabled": False}}) is None


# ---------------------------------------------------------------------------
# 开启：半成品被拒 + 人话提示原文
# ---------------------------------------------------------------------------
def test_on_halfbaked_blocked_with_human_message(tmp_path: Path) -> None:
    root = _halfbaked(tmp_path / "p", enabled=True)
    gate = pp.play_gate(root)
    assert gate["enabled"] is True and gate["allowed"] is False
    assert len(gate["problems"]) == 1
    p = gate["problems"][0]
    assert p["rule"] == "module_missing" and p["module"] == "enemies"
    msg = gate["message"]
    assert "数据包保护已开启" in msg
    assert "半成品包" in msg                      # 哪个包
    assert "enemies.json" in msg                  # 什么问题
    assert "编辑器" in msg and "去哪改" in msg    # 去哪改
    assert "pack_protection" not in msg           # 面向作者，不暴露内部键名


def test_enforce_raises_carries_gate(tmp_path: Path) -> None:
    root = _halfbaked(tmp_path / "p", enabled=True)
    with pytest.raises(pp.PackProtectionError) as ei:
        pp.enforce_play_gate(root)
    assert ei.value.gate["allowed"] is False
    assert "数据包保护已开启" in str(ei.value)


def test_on_complete_pack_allowed(tmp_path: Path) -> None:
    dst = tmp_path / "test_demo"
    shutil.copytree(CONTENT / "test_demo", dst)
    sp = dst / "settings.json"
    doc = json.loads(sp.read_text(encoding="utf-8"))
    doc["pack_protection"] = {"enabled": True}
    sp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    gate = pp.play_gate(dst)
    assert gate["allowed"] is True and gate["problems"] == [] and gate["message"] == ""


async def test_bootstrap_rejects_halfbaked_when_enabled(tmp_path: Path) -> None:
    """进入游玩门禁接线：开启 + 半成品 → bootstrap 抛 PackProtectionError。"""
    root = _halfbaked(tmp_path / "p", enabled=True)

    class _Repo:
        async def load_world_state(self) -> dict:
            return {}

    with pytest.raises(pp.PackProtectionError):
        await bootstrap({"pack_dir": str(root), "repo": _Repo()})


async def test_bootstrap_disabled_unchanged(tmp_path: Path) -> None:
    """关闭（缺省）→ bootstrap 不因保护拒绝；缺模块仍按既有 loader 语义放行。"""
    root = _halfbaked(tmp_path / "p", enabled=False)

    class _Repo:
        async def load_world_state(self) -> dict:
            return {}

    app = await bootstrap({"pack_dir": str(root), "repo": _Repo()})
    assert app.registry is not None


# ---------------------------------------------------------------------------
# 运行期玩家指令拦截（复用既有判定链）
# ---------------------------------------------------------------------------
def test_metadata_registered() -> None:
    fm = SETTINGS_FIELDS.get("pack_protection")
    assert fm is not None and fm.type == "obj"
    assert "enabled" in fm.children and fm.children["enabled"].type == "bool"
    # 编辑器可见（框架登记即显示；缺省 = 空表单，不改现状）
    fields = default_field_meta_table().module("settings").fields
    assert "pack_protection" in fields


def test_meta_table_has_field() -> None:
    fields = default_field_meta_table().module("settings").fields
    fm = fields.get("pack_protection")
    assert fm is not None and fm.label == "数据包保护"


class _FakeTx:
    def __init__(self, repo: "_FakeRepo") -> None:
        self._repo = repo

    async def idem_exists(self, key: Any) -> bool:
        return False

    async def write_idem_key(self, key: Any) -> None:
        pass

    async def upsert_player(self, player: Any) -> None:
        self._repo._player = player


class _FakeRepo:
    def __init__(self, player: Any = None) -> None:
        self._player = player

    async def load_player(self, qid: str) -> Any:
        p = self._player
        return p if (p is not None and p.qid == str(qid)) else None

    async def idem_claim(self, key: Any) -> bool:
        return False

    @contextlib.asynccontextmanager
    async def tx(self):
        yield _FakeTx(self)

    async def cleanup_idem_keys(self, retention_days: float = 7.0, **kw: Any) -> int:
        return 0


class _StubWorld:
    def get_map(self, map_id: str) -> Any:
        raise NotImplementedError

    def monster_pool(self, map_id: str) -> Any:
        raise NotImplementedError

    def get_npcs(self, map_id: str) -> Any:
        raise NotImplementedError


class _Session:
    def get_active(self, qid: str) -> Any:
        return None


def _player() -> Any:
    from qbot_rpg.data import Player, PlayerAttributes

    return Player(qid="10001", name="阿伟", job_id="warrior", level=5, exp=0,
                  hp=100, mp=30, currencies={"coins": 10}, inventory=(),
                  attributes=PlayerAttributes(base={"hp": 100.0, "mp": 30.0}),
                  persistent_state={"location": "town"})


def _settings(**over: Any) -> dict:
    s: dict = {"default_map": "town", "level_cap": 45}
    s.update(over)
    return s


async def _run(message: str, *, settings: dict, gm: bool = False) -> str:
    from qbot_rpg.content.registry import Registry

    repo = _FakeRepo(_player())
    router = Router()
    router.register(CommandSpec("状态", handler=lambda parsed, ctx: "面板"))
    router.register(CommandSpec("重启", handler=lambda parsed, ctx: "已重启",
                                permission=PERM_GM))
    deps = AssemblyDeps(repo=repo, game_world=_StubWorld(),
                        registry=Registry(pack_id="t", generation=1, tables={},
                                          names={}, modules_raw={}),
                        settings=settings, session_mgr=_Session())
    deps.router = router  # type: ignore[attr-defined]
    deps.queue = PerPlayerQueue(repo)  # type: ignore[arg-type]
    deps.sender = Sender()  # type: ignore[attr-defined]
    deps.permission_store = SimpleNamespace(is_gm=lambda qid: gm)  # type: ignore[attr-defined]
    event = {"group_id": "g1", "user_id": "10001", "message": message,
             "channel": "group", "message_id": "m1"}
    return await run_command(event, deps)


async def test_player_blocked_when_enabled() -> None:
    out = await _run("/状态", settings=_settings(pack_protection={"enabled": True}))
    assert out == pp.PLAYER_NOTICE == "作者更新中，请稍后再试..."


async def test_player_normal_when_disabled() -> None:
    assert (await _run("/状态", settings=_settings())).endswith("面板")
    assert (await _run("/状态",
                       settings=_settings(pack_protection={"enabled": False}))
            ).endswith("面板")


async def test_gm_unaffected_when_enabled() -> None:
    """保护期 GM/机主仍可运维（GM 指令不受玩家指令拦截）。"""
    assert (await _run("/重启", settings=_settings(pack_protection={"enabled": True}),
                       gm=True)).endswith("已重启")


def test_gate_helper_reads_settings() -> None:
    assert _pack_protection_gate({"settings": {"pack_protection": {"enabled": True}}}) \
        == pp.PLAYER_NOTICE
    assert _pack_protection_gate({"settings": {}}) is None
    assert _pack_protection_gate({}) is None
