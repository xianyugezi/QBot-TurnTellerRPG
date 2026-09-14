"""内容包指令扩展点 E1 单测（ext_api 稳定面 + 通用装载器 + 双闸 + 失败隔离）。

覆盖（对照 docs/游戏包扩展点_方案_E.md §三 E1 / §三·装载安全 与任务验收）：
- 双闸：缺省/单闸都不启用；两闸同时才启用；未启用时包内模块**从未被 import**（marker 断言）；
- 启用：声明指令被注册、Router 可命中（parse → dispatch）、handler 返回玩家可见文本、别名可命中；
- 重名：与框架指令名/别名/包内自冲突 → 拒绝 + 报错含冲突对象 + 框架行为不变 + 整包原子回滚；
- 路径：`..` 与符号链接（commands.json / ext/commands.py）→ 拒绝；
- 声明非法：缺 name/handler、字段类型错、未知字段、顶层形态错 → 拒绝且报错清晰；
- 失败隔离：import 失败 / handler 抛异常 → 不抛到顶层，玩家看到默认提示，其它指令正常；
- 通用性：两个不同名的 tmp 包同结构 → 都生效（证明与包名无关）；
- 真实探针包 zz_probe_ext：build_app_deps → run_command 全链路命中并返回文本。

纪律：只写 tmp 目录/内存库，不触碰真实内容包与玩家存档；零 NoneBot。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from qbot_rpg import ext_api
from qbot_rpg.assembly.pack_ext import (
    CLI_FLAG,
    ENV_ENABLE,
    load_pack_extensions,
    pack_ext_enabled,
    resolve_cli_enabled,
    settings_enabled,
)
from qbot_rpg.commands.router import (
    ROUTE_ALIAS,
    ROUTE_COMMAND,
    AliasTable,
    CommandSpec,
    Router,
)
from qbot_rpg.ext_api import EXT_API_VERSION, ExtContext
from qbot_rpg.storage.connection import Database

REPO = Path(__file__).resolve().parents[2]
PROBE_PACK = REPO / "content" / "zz_probe_ext"

_MANIFEST = {
    "name": "tmp ext pack",
    "version": "9.9.9",
    "schema_version": 1,
    "author": "unit-test",
    "modules": ["settings", "stats", "formula", "effects", "items"],
}

_DEFAULT_IMPL = """\
from qbot_rpg import ext_api


def probe(ctx, parsed):
    return "OK:" + ctx.pack_id + ":" + ctx.args_text
"""


def _write_pack(
    root: Path,
    *,
    commands=None,
    impl: str | None = _DEFAULT_IMPL,
    decl_text: str | None = None,
    manifest=None,
) -> Path:
    """在 ``root`` 落一个最小扩展包（只含装载器会读的文件，不涉数据模块）。"""
    (root / "ext").mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(manifest or _MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    if decl_text is None:
        decl_text = json.dumps(
            {"commands": commands if commands is not None else []}, ensure_ascii=False
        )
    (root / "commands.json").write_text(decl_text, encoding="utf-8")
    if impl is not None:
        (root / "ext" / "commands.py").write_text(impl, encoding="utf-8")
    return root


def _decl(name="探针", handler="probe", aliases=None, **over):
    d = {"name": name, "handler": handler, "aliases": list(aliases or [])}
    d.update(over)
    return d


def _fw_router(names=("帮助", "状态"), aliases=None) -> Router:
    """最小框架 Router：注册若干既有指令 + 挂别名表（冲突检测/路由消费）。"""
    r = Router()
    for n in names:
        r.register(CommandSpec(n))
    r.aliases = AliasTable.from_config(aliases or {})  # type: ignore[attr-defined]
    return r


def _parsed(command="探针", args=(), raw=""):
    return SimpleNamespace(
        command=command, args=list(args), tokens=[command, *args], raw=raw or command
    )


def test_double_gate_helpers() -> None:
    """双闸判定：settings/CLI 各自解析 + 合取语义。"""
    assert settings_enabled({}) is False
    assert settings_enabled({"ext": {"enabled": True}}) is True
    assert settings_enabled({"ext": {"enabled": "1"}}) is True
    assert settings_enabled({"ext": {"enabled": False}}) is False
    assert settings_enabled({"ext": "oops"}) is False

    assert resolve_cli_enabled(argv=["prog"], env={}) is False
    assert resolve_cli_enabled(argv=["prog", CLI_FLAG], env={}) is True
    assert resolve_cli_enabled(argv=["prog"], env={ENV_ENABLE: "true"}) is True
    assert resolve_cli_enabled(argv=["prog"], env={ENV_ENABLE: "0"}) is False

    assert pack_ext_enabled({"ext": {"enabled": True}}, cli=True) is True
    assert pack_ext_enabled({"ext": {"enabled": True}}, cli=False) is False
    assert pack_ext_enabled({}, cli=True) is False


# =============================================================================
# 双闸：未启用 → 指令不存在 + 包内模块从未被 import
# =============================================================================
def test_not_enabled_never_imports_pack_module(tmp_path: Path) -> None:
    """缺省（两闸都关）→ 不读 ext/、不 import 任何包内 Python（marker 文件为证）。"""
    marker = tmp_path / "imported.marker"
    impl = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n"
        "def probe(ctx, parsed):\n    return 'ok'\n"
    )
    root = _write_pack(tmp_path / "zt_noimport", commands=[_decl()], impl=impl)
    r = _fw_router()

    res = load_pack_extensions(r, pack_dir=root, settings={}, cli=False)

    assert res.enabled is False and res.ok is True and res.registered == ()
    assert not r.has("探针")
    assert not marker.exists(), "未启用却 import 了包内模块"
    assert not [m for m in sys.modules if "zt_noimport" in m]


def test_only_settings_gate_disabled(tmp_path: Path) -> None:
    """只开第一闸（settings）→ 仍不启用（包不能自己授权自己执行代码）。"""
    root = _write_pack(tmp_path / "zt_gate_a", commands=[_decl()])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=False)
    assert res.enabled is False and not r.has("探针")


def test_only_cli_gate_disabled(tmp_path: Path) -> None:
    """只开第二闸（--enable-pack-ext）→ 仍不启用。"""
    root = _write_pack(tmp_path / "zt_gate_b", commands=[_decl()])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={}, cli=True)
    assert res.enabled is False and not r.has("探针")


def test_cli_flag_via_argv_and_env(tmp_path: Path) -> None:
    """第二闸两种通道：argv 参数 / 环境变量都能开。"""
    root = _write_pack(tmp_path / "zt_gate_c", commands=[_decl()])
    r1 = _fw_router()
    assert load_pack_extensions(
        r1, pack_dir=root, settings={"ext": {"enabled": True}}, argv=["prog", CLI_FLAG], env={}
    ).registered == ("探针",)
    r2 = _fw_router()
    assert load_pack_extensions(
        r2, pack_dir=root, settings={"ext": {"enabled": True}}, argv=["prog"], env={ENV_ENABLE: "1"}
    ).registered == ("探针",)


# =============================================================================
# 启用：注册 + 路由 + handler + 别名
# =============================================================================
async def test_enabled_registers_routes_and_returns_text(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_ok", commands=[_decl(aliases=["zzp"])])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)

    assert res.ok and res.registered == ("探针",) and res.aliases == ("zzp",)
    assert r.has("探针") and r.get("探针").whitelisted

    route = r.dispatch("/探针 甲乙")
    assert route.kind == ROUTE_COMMAND and route.command == "探针"
    out = await r.get("探针").handler(
        _parsed("探针", ["甲乙"], "探针 甲乙"), ctx={"qq_id": "u1"}
    )
    assert out == "OK:zt_ok:甲乙"

    aroute = r.dispatch("zzp 丙", {"aliases": r.aliases})
    assert aroute.kind == ROUTE_ALIAS and aroute.command == "探针"
    aout = await r.get("探针").handler(_parsed("探针", ["丙"]), ctx={"qq_id": "u1"})
    assert aout == "OK:zt_ok:丙"


def test_second_pack_same_structure_works(tmp_path: Path) -> None:
    """通用性：另造一个不同名的包、同样结构 → 同样生效（与包名无关）。"""
    root = _write_pack(tmp_path / "zz_other_pack", commands=[_decl(name="潮汐", handler="probe")])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.registered == ("潮汐",)
    route = r.dispatch("潮汐")
    assert route.kind == ROUTE_COMMAND and route.command == "潮汐"


def test_gm_only_maps_to_gm_spec(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_gm", commands=[_decl(gm_only=True)])
    r = _fw_router()
    load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    spec = r.get("探针")
    assert spec.is_gm is True and spec.permission == "gm"


# =============================================================================
# 重名拒绝
# =============================================================================
def test_duplicate_framework_name_rejected_and_unchanged(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_dup_name", commands=[_decl(name="帮助", handler="probe")])
    r = _fw_router(names=("帮助",))
    before = r.get("帮助")

    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)

    assert res.ok is False and res.registered == ()
    assert r.get("帮助") is before, "框架既有指令被覆盖/替换"
    assert any("帮助" in e and "冲突" in e for e in res.errors), res.errors


def test_duplicate_framework_alias_rejected(tmp_path: Path) -> None:
    """包指令名撞框架既有别名 → 拒绝，报错指认别名归属。"""
    root = _write_pack(tmp_path / "zt_dup_fwalias", commands=[_decl(name="zt", handler="probe")])
    r = _fw_router(names=("状态",), aliases={"状态": "zt"})
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False
    assert any("zt" in e and "状态" in e for e in res.errors), res.errors


def test_alias_collides_with_framework_command_rejected(tmp_path: Path) -> None:
    root = _write_pack(
        tmp_path / "zt_dup_alias", commands=[_decl(name="潮汐", aliases=["帮助"], handler="probe")]
    )
    r = _fw_router(names=("帮助",))
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False
    assert any("帮助" in e and "别名" in e for e in res.errors), res.errors
    assert not r.has("潮汐")


def test_alias_collides_with_framework_spec_alias_rejected(tmp_path: Path) -> None:
    """框架指令自带 aliases（CommandSpec.aliases，不在 AliasTable 里）同样要检出。"""
    root = _write_pack(
        tmp_path / "zt_spec_alias",
        commands=[_decl(name="潮汐", aliases=["领取任务"], handler="probe")],
    )
    r = Router()
    r.register(CommandSpec("任务", aliases=["领取任务"]))
    r.aliases = AliasTable.from_config({})  # type: ignore[attr-defined]
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and not r.has("潮汐")
    assert any("领取任务" in e and "任务" in e for e in res.errors), res.errors


def test_intra_pack_conflict_rejected_atomically(tmp_path: Path) -> None:
    """包内一条合法 + 一条与框架重名 → 整包拒绝（不留半装）。"""
    root = _write_pack(
        tmp_path / "zt_atomic",
        commands=[_decl(name="潮汐", handler="probe"), _decl(name="帮助", handler="probe")],
    )
    r = _fw_router(names=("帮助",))
    before_help = r.get("帮助")
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and res.registered == ()
    assert not r.has("潮汐")
    assert r.get("帮助") is before_help, "框架既有指令不得被改动"


def test_intra_pack_duplicate_names(tmp_path: Path) -> None:
    root = _write_pack(
        tmp_path / "zt_intra", commands=[_decl(name="潮汐"), _decl(name="潮汐")]
    )
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("重复" in e for e in res.errors), res.errors


# =============================================================================
# 声明非法
# =============================================================================
def test_declaration_missing_name(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_bad_name", commands=[{"handler": "probe"}])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("name" in e for e in res.errors), res.errors


def test_declaration_missing_handler(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_bad_handler", commands=[{"name": "探针"}])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("handler" in e for e in res.errors), res.errors


@pytest.mark.parametrize(
    "bad",
    [
        {"name": 123, "handler": "probe"},
        {"name": "探 针", "handler": "probe"},
        {"name": "探针", "handler": "not an identifier"},
        {"name": "探针", "handler": "probe", "aliases": "x"},
        {"name": "探针", "handler": "probe", "aliases": [1]},
        {"name": "探针", "handler": "probe", "gm_only": "yes"},
        {"name": "探针", "handler": "probe", "usage": 3},
        {"name": "探针", "handler": "probe", "typo_key": 1},
    ],
)
def test_declaration_bad_field_types(tmp_path: Path, bad: dict) -> None:
    root = _write_pack(tmp_path / "zt_badfield", commands=[bad])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and res.errors, bad
    assert r.names() == ["帮助", "状态"]


def test_declaration_top_level_not_object(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_toplevel", decl_text="[1, 2, 3]")
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("顶层" in e for e in res.errors), res.errors


def test_declaration_commands_not_array(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_cmds", decl_text='{"commands": {"name": "x"}}')
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("数组" in e for e in res.errors), res.errors


def test_missing_impl_file(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_noimpl", commands=[_decl()], impl=None)
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("缺少实现文件" in e for e in res.errors), res.errors


def test_missing_handler_function(tmp_path: Path) -> None:
    root = _write_pack(
        tmp_path / "zt_nofunc", commands=[_decl()], impl="def other(ctx, parsed):\n    return 'x'\n"
    )
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("缺少 handler" in e for e in res.errors), res.errors


def test_malformed_json_isolated(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_badjson", decl_text="{not json")
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("JSON" in e for e in res.errors), res.errors


# =============================================================================
# 路径非法
# =============================================================================
def test_dotdot_pack_dir_rejected(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_dotdot", commands=[_decl()])
    tricky = root / ".." / "zt_dotdot"
    r = _fw_router()
    res = load_pack_extensions(
        r, pack_dir=tricky, settings={"ext": {"enabled": True}}, cli=True
    )
    assert res.ok is False and any(".." in e for e in res.errors), res.errors


def test_symlink_impl_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside_impl.py"
    outside.write_text("def probe(ctx, parsed):\n    return 'x'\n", encoding="utf-8")
    root = _write_pack(tmp_path / "zt_symlink_impl", commands=[_decl()], impl=None)
    os.symlink(outside, root / "ext" / "commands.py")
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("符号链接" in e for e in res.errors), res.errors
    assert not r.has("探针")


def test_symlink_decl_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"commands": [_decl()]}), encoding="utf-8")
    root = tmp_path / "zt_symlink_decl"
    (root / "ext").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(_MANIFEST), encoding="utf-8")
    os.symlink(outside, root / "commands.json")
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("符号链接" in e for e in res.errors), res.errors


# =============================================================================
# 失败隔离
# =============================================================================
async def test_import_failure_isolated(tmp_path: Path) -> None:
    root = _write_pack(
        tmp_path / "zt_importerr",
        commands=[_decl()],
        impl="raise RuntimeError('boom at import')\n",
    )
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("import 失败" in e for e in res.errors), res.errors
    assert not r.has("探针")
    # 框架其它指令照常
    assert r.dispatch("/帮助").kind == ROUTE_COMMAND


async def test_handler_exception_isolated(tmp_path: Path) -> None:
    root = _write_pack(
        tmp_path / "zt_handlererr",
        commands=[_decl(name="探针", handler="boom"), _decl(name="稳固", handler="probe")],
        impl=(
            "def boom(ctx, parsed):\n    raise RuntimeError('boom')\n"
            "def probe(ctx, parsed):\n    return 'ok'\n"
        ),
    )
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok and set(res.registered) == {"探针", "稳固"}

    out = await r.get("探针").handler(_parsed(), ctx={"qq_id": "u1"})
    assert out == "❌ 功能暂不可用"  # 人话兜底，不崩
    # 同一包的其它指令照常
    assert await r.get("稳固").handler(_parsed(command="稳固"), ctx={"qq_id": "u1"}) == "ok"


# =============================================================================
# ext_api 稳定面
# =============================================================================
def test_ext_api_exports_required_surface() -> None:
    required = {
        "ExtContext", "tpl", "rng", "log", "EXT_API_VERSION",
        "get_pack_state", "set_pack_state", "patch_pack_state",
        "clear_pack_state", "list_pack_states",
    }
    assert required <= set(ext_api.__all__)
    assert EXT_API_VERSION == "1"
    with pytest.raises(AttributeError):
        _ = ext_api.not_a_stable_name  # noqa: B018


def test_ext_api_tpl_pack_override() -> None:
    default = ext_api.tpl("err_bad_command", {"fragment": "x"})
    assert "x" in default
    override = {"err_bad_command": "OVERRIDE {fragment}"}
    ctx = ExtContext(pack_id="p", ctx={"templates": override})
    assert ctx.tpl("err_bad_command", {"fragment": "y"}) == "OVERRIDE y"
    # 未知 key → 空串，不抛
    assert ctx.tpl("no_such_key_zz", {}) == ""


def test_ext_api_rng_deterministic() -> None:
    a = ExtContext(pack_id="p", ctx={"qq_id": "u1"})
    b = ExtContext(pack_id="p", ctx={"qq_id": "u1"})
    c = ExtContext(pack_id="p", ctx={"qq_id": "u2"})
    assert [a.rng.randint(0, 999) for _ in range(5)] == [b.rng.randint(0, 999) for _ in range(5)]
    assert [a.rng.randint(0, 999) for _ in range(5)] != [c.rng.randint(0, 999) for _ in range(5)]


def test_ext_api_player_is_readonly() -> None:
    import dataclasses

    @dataclasses.dataclass
    class P:
        name: str
        hp: int

    ctx = ExtContext(pack_id="p", ctx={"player": P("a", 1), "settings": {"x": 1}})
    assert ctx.player["name"] == "a" and ctx.player["hp"] == 1
    with pytest.raises(TypeError):
        ctx.player["hp"] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        ctx.settings["x"] = 2  # type: ignore[index]


async def test_ext_api_pack_state_roundtrip() -> None:
    db = Database(":memory:")
    try:
        repo = SimpleNamespace(db=db)
        ctx = ExtContext(pack_id="p1", ctx={"qq_id": "u1", "repo": repo})
        assert await ctx.get_state() == {}
        await ctx.set_state({"a": 1})
        assert await ctx.get_state() == {"a": 1}
        assert await ctx.patch_state({"b": 2}) == {"a": 1, "b": 2}
        await ctx.clear_state()
        assert await ctx.get_state() == {}

        other = ExtContext(pack_id="p2", ctx={"qq_id": "u1", "repo": repo})
        assert await other.get_state() == {}
        unregistered = ExtContext(pack_id="p1", ctx={"repo": repo})
        assert await unregistered.get_state() == {}
        with pytest.raises(ext_api.ExtApiUnavailable):
            await unregistered.set_state({"x": 1})
    finally:
        await db.close()


# =============================================================================
# 真实探针包：build_app_deps → run_command 全链路
# =============================================================================
async def test_real_probe_pack_end_to_end(tmp_path: Path) -> None:
    from qbot_rpg.assembly.runner import run_command
    from qbot_rpg_bridge.assemble import build_app_deps

    deps = await build_app_deps(
        pack_dir=str(PROBE_PACK),
        db_path=str(tmp_path / "e2e.db"),
        settings={"ext": {"enabled": True}},
        enable_pack_ext=True,
    )
    try:
        assert deps.pack_ext_result.ok
        assert deps.pack_ext_result.registered == ("探针",)
        ev = {
            "group_id": "g1", "user_id": "u1", "message": "探针 参数甲",
            "channel": "group", "message_id": "m-e1",
        }
        out = await run_command(ev, deps)
        assert "【扩展探针】" in out
        assert "包=zz_probe_ext" in out and "参数=参数甲" in out

        ev2 = {**ev, "message": "zzprobe 参数乙", "message_id": "m-e2"}
        out2 = await run_command(ev2, deps)
        assert "参数=参数乙" in out2
    finally:
        await deps.repo.db.close()


async def test_real_probe_pack_disabled_by_default(tmp_path: Path) -> None:
    from qbot_rpg_bridge.assemble import build_app_deps

    deps = await build_app_deps(
        pack_dir=str(PROBE_PACK),
        db_path=str(tmp_path / "e2e_off.db"),
        enable_pack_ext=False,
    )
    try:
        assert deps.pack_ext_result.enabled is False
        assert not deps.router.has("探针")
    finally:
        await deps.repo.db.close()


def test_probe_pack_conflict_variant_rejected(tmp_path: Path) -> None:
    """真实探针包改声明撞框架指令 → 拒绝；报错含冲突对象；框架指令行为不变。"""
    import shutil

    root = tmp_path / "zz_probe_ext_conflict"
    shutil.copytree(PROBE_PACK, root)
    (root / "commands.json").write_text(
        json.dumps(
            {
                "commands": [
                    _decl(name="探针", handler="probe"),
                    _decl(name="帮助", handler="probe"),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = _fw_router(names=("帮助",))
    before_help = r.get("帮助")
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and res.registered == ()
    assert any("帮助" in e and "冲突" in e for e in res.errors), res.errors
    assert not r.has("探针")
    assert r.get("帮助") is before_help


def test_cli_parse_enable_flag() -> None:
    """CLI 侧第二闸：--enable-pack-ext 可传；未传 → None（回落 env/argv）。"""
    from qbot_rpg_bridge.assemble import _parse_cli

    assert _parse_cli([]).enable_pack_ext is None
    assert _parse_cli(["--enable-pack-ext"]).enable_pack_ext is True
    assert _parse_cli(["--pack-dir", "/tmp/x"]).pack_dir == "/tmp/x"


def test_alias_equals_own_name_rejected(tmp_path: Path) -> None:
    root = _write_pack(tmp_path / "zt_selfalias", commands=[_decl(aliases=["探针"])])
    r = _fw_router()
    res = load_pack_extensions(r, pack_dir=root, settings={"ext": {"enabled": True}}, cli=True)
    assert res.ok is False and any("别名与指令名相同" in e for e in res.errors), res.errors
