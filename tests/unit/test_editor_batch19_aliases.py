"""编辑器重写批19 · 段 D：指令别名完整（用户 #7）。

用户反馈 #7：包 `settings.command_aliases` 只有 1 条，编辑器看不到框架侧的别名机制。

**框架侧现状核查结论（本批坐实）**：框架**没有**独立的静态别名表——运行时别名有两处来源：
  ① 各指令注册时自带的 `CommandSpec.aliases`（`Router.register` 挂到 spec；即「框架内置」）；
  ② 包 `settings.command_aliases`，装配层用**既有** `AliasTable.from_config` 装载（「包覆盖」）。
`qbot_rpg/assembly/router_setup.py::framework_builtin_aliases()` 从既有 `REGISTER_GROUPS`
装配读取 ①（不另造表）。别名视图在**装配层**（`qbot_rpg/assembly/editor_aliases.py`）组装：
web 读取层按架构矩阵不得依赖 commands/assembly，故由宿主 `scripts/editor_host.py` 注入。
"""

from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.assembly import editor_aliases
from qbot_rpg.assembly.router_setup import framework_builtin_aliases
from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _aliases(pack: str, root: Path = CONTENT) -> dict:
    return editor_aliases.list_aliases(root / pack)


def _settings_pack(root: Path, aliases: object) -> Path:
    pkg = root / "p"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "P", "version": "1", "schema_version": 1, "modules": ["settings"]}),
        encoding="utf-8")
    (pkg / "settings.json").write_text(json.dumps({"command_aliases": aliases}),
                                       encoding="utf-8")
    return pkg


# =====================================================================================
# A · 框架侧内置别名：从既有实现读取（不另造表）
# =====================================================================================
def test_framework_builtin_aliases_read_from_command_specs() -> None:
    fw = framework_builtin_aliases()
    assert isinstance(fw, dict) and fw, "框架内置别名不应为空（至少指令壳自带别名）"
    # 独立复核：注册后各 CommandSpec.aliases 的并集应与它一致（同一来源）
    from qbot_rpg.commands.router import Router
    from qbot_rpg.assembly.router_setup import REGISTER_GROUPS
    r = Router()
    for reg in REGISTER_GROUPS:
        reg(r, make_context=None)
    expected = {}
    for name in r.names():
        for alias in getattr(r.get(name), "aliases", None) or []:
            expected.setdefault(str(alias), str(name))
    assert fw == expected
    for alias, command in fw.items():
        assert alias and command and alias != command


def test_framework_aliases_are_readonly_snapshot() -> None:
    """每次组装返回独立对象：调用方改动不污染后续。"""
    a = _aliases("veinborn")
    a["framework"].append({"alias": "x", "command": "y"})
    b = _aliases("veinborn")
    assert all(r["alias"] != "x" for r in b["framework"])


# =====================================================================================
# B · 包声明完整渲染 + 两类来源 + 同键覆盖
# =====================================================================================
def test_veinborn_aliases_two_sources() -> None:
    al = _aliases("veinborn")
    assert al["sources"] == ["framework", "pack"]
    assert al["framework"], al["framework"]
    assert al["pack_declared"], al["pack_declared"]
    pack_row = al["pack_declared"][0]
    assert pack_row["command"] and pack_row["alias"]
    assert pack_row["source"] == "pack"
    if any(r["alias"] == pack_row["alias"] for r in al["framework"]):
        assert pack_row["overrides_framework"] is True
    for row in al["merged"]:
        if row["alias"] == pack_row["alias"]:
            assert row["source"] == "pack"
    assert al["note"] == ""


def test_pack_alias_override_and_extra(tmp_path: Path) -> None:
    _settings_pack(tmp_path, {
        "任务": {"alias": "领任务", "keep_original": False},
        "炼金": {"command": "炼金"},
    })
    al = _aliases("p", tmp_path)
    by_alias = {r["alias"]: r for r in al["pack_declared"]}
    assert by_alias["领任务"]["command"] == "任务"
    assert by_alias["领任务"]["keep_original"] is False
    # 备选形态（键=别名，值含 command）也归一化
    assert "炼金" in by_alias
    # 框架内置仍在（包不删减框架能力）
    assert al["framework"]


def test_bad_pack_alias_config_reported_not_crashed(tmp_path: Path) -> None:
    _settings_pack(tmp_path, {"任务": 12345})
    al = _aliases("p", tmp_path)
    assert al["pack_declared"] == [] and al["note"]


def test_no_alias_config_is_empty_pack_side(tmp_path: Path) -> None:
    pkg = tmp_path / "p2"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "P", "version": "1", "schema_version": 1, "modules": ["settings"]}),
        encoding="utf-8")
    (pkg / "settings.json").write_text("{}", encoding="utf-8")
    al = _aliases("p2", tmp_path)
    assert al["pack_declared"] == []
    assert al["framework"]        # 一号原则：包没配也看得到框架内置能力


# =====================================================================================
# C · 宿主注入 + 架构合规（web 读取层不依赖 commands/assembly）+ 前端契约
# =====================================================================================
def test_host_injects_alias_view_and_keeps_web_layer_clean() -> None:
    host = (REPO / "scripts" / "editor_host.py").read_text(encoding="utf-8")
    assert "editor_aliases.list_aliases" in host
    assert '"/api/pack/{pack_id}/aliases"' in host
    # 架构：web 读取层不得 import commands / assembly（别名视图放装配层）
    src = (REPO / "qbot_rpg" / "web" / "api.py").read_text(encoding="utf-8")
    for bad in ("import qbot_rpg.commands", "from qbot_rpg.commands",
                "import qbot_rpg.assembly", "from qbot_rpg.assembly"):
        assert bad not in src, bad


def test_frontend_alias_panel_contract() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("mp-aliases", "renderAliasPanel", "al.framework_note", "al.pack_declared",
                  "框架内置 · "):
        assert token in html, token
