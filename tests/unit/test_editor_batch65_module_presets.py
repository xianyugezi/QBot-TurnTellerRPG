"""批65 · 编辑器「模块预设组合」（⚙ 模块开关面板顶部「推荐组合」）+ 依赖闭包 · 验收。

覆盖任务书要求：
  A. **框架默认组合**：形状（id/中文名/一句话/适用人群/modules）、三个方向（基础 RPG /
     生活冒险 / 故事探索）、模块键全部在 `module_catalog` 真实登记（自检零错误）。
  B. **机制通用**：合并（包同 id 覆盖 / 追加 / 关闭）、依赖闭包（只读 `module_catalog.requires`，
     不写死模块名）——用合成目录验证，不依赖任何业务模块名。
  C. **API**：空白包也有框架默认组合（一号原则）；包声明覆盖 / 追加 / 关闭生效。
  D. **一键应用**：累加（不取消用户已勾）、依赖自动带上、单次 manifest 备份、骨架落盘；
     「回退最近一次模块变更」能一键撤销整个组合；只读身份拒绝；未知组合拒绝。
  E. **零变化**：只读接口不改包；不应用组合 → manifest 与数据文件逐字段不变。
  F. **通用性护栏**：机制代码不含任何真实内容包名 / 业务字段名。

全部写盘发生在 tmp_path 的临时包，绝不触碰仓库 content/ 下任何包。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from qbot_rpg.content import module_presets as mp
from qbot_rpg.content.module_catalog import FRAMEWORK_MODULE_CATALOG, ModuleCatalogEntry
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
PRESET_SRC = REPO / "qbot_rpg" / "content" / "module_presets.py"


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """空白包（无任何模块声明）→ 验证「框架默认组合仍在」（一号原则）。"""
    blank = tmp_path / "blank_pack"
    blank.mkdir()
    _write(blank / "manifest.json",
           {"name": "空白", "version": "1", "schema_version": 1, "modules": []})
    return tmp_path


# =====================================================================================
# A. 框架默认组合：形状 + 自检
# =====================================================================================
def test_framework_presets_self_check_zero_errors() -> None:
    assert mp.framework_module_preset_errors() == []


def test_framework_presets_cover_three_directions() -> None:
    ids = [p["id"] for p in mp.FRAMEWORK_MODULE_PRESETS]
    assert ids == ["basic_rpg", "life_adventure", "story_exploration"]
    for preset in mp.FRAMEWORK_MODULE_PRESETS:
        assert preset["label"] and preset["help"] and preset["audience"]
        assert preset["modules"]


def test_framework_preset_every_module_is_registered() -> None:
    known = {e.module for e in FRAMEWORK_MODULE_CATALOG}
    for preset in mp.FRAMEWORK_MODULE_PRESETS:
        for mod in preset["modules"]:
            assert mod in known, (preset["id"], mod)


def test_basic_rpg_covers_minimal_playable_set() -> None:
    preset = mp.merge_module_presets()[0]
    mods = set(preset["modules"])
    assert {"items", "skills", "enemies", "maps", "quest"} <= mods


def test_life_adventure_closure_pulls_dependencies() -> None:
    res = mp.resolve_module_presets()
    life = mp.find_module_preset(res, "life_adventure")
    assert life is not None
    assert set(life["auto_deps"]) == {"maps", "effects"}
    assert life["auto_deps"] and all(m in life["modules"] for m in life["auto_deps"])


# =====================================================================================
# B. 纯机制：合并 + 依赖闭包（合成目录，不写死业务模块名）
# =====================================================================================
SYNTH = {
    "a": ModuleCatalogEntry("a", "甲", "甲模块", "list"),
    "b": ModuleCatalogEntry("b", "乙", "乙模块", "list", requires=("a",)),
    "c": ModuleCatalogEntry("c", "丙", "丙模块", "object", requires=("b", "z")),
    "z": ModuleCatalogEntry("z", "未实装", "引擎未实装", "list", implemented=False),
}


def test_clone_closure_is_recursive_and_ordered() -> None:
    got = mp.preset_modules_with_deps(
        ["c"], catalog=SYNTH,
        enableable=lambda m: SYNTH[m].implemented if m in SYNTH else False)
    # 显式在前，依赖按发现顺序补：c 依赖 b、z；b 又依赖 a；z 未实装 → unavailable。
    assert got["ordered"] == ["c", "b", "a"]
    assert got["auto_deps"] == ["b", "a"]
    assert got["unavailable"] == ["z"]


def test_closure_pack_custom_module_without_catalog_entry_is_usable_when_declared() -> None:
    got = mp.preset_modules_with_deps(
        ["zz_custom", "b"], declared=["zz_custom"], catalog=SYNTH,
        enableable=lambda m: SYNTH[m].implemented if m in SYNTH else False)
    assert got["ordered"] == ["zz_custom", "b", "a"]
    assert got["unknown"] == []


def test_closure_unknown_module_is_reported_not_silently_enabled() -> None:
    got = mp.preset_modules_with_deps(["nope"], catalog=SYNTH, enableable=lambda m: False)
    assert got["ordered"] == []
    assert got["unknown"] == ["nope"]


def test_merge_override_append_disable() -> None:
    pack = [
        {"id": "x", "label": "覆盖", "help": "", "audience": "", "modules": ["b"]},
        {"id": "new", "label": "追加", "help": "", "audience": "", "modules": ["a"]},
    ]
    merged = mp.merge_module_presets(pack, disabled=["x", "nope"])
    ids = [p["id"] for p in merged]
    assert "x" not in ids                          # 关闭
    assert ids[-1] == "new"                        # 追加在末尾
    assert "nope" not in ids                       # 关闭不存在的 id = 无害空操作


def test_merge_same_id_pack_overrides_framework_in_place() -> None:
    merged = mp.merge_module_presets(
        [{"id": "basic_rpg", "label": "本包基础", "help": "H", "audience": "A",
          "modules": ["a"]}])
    got = mp.find_module_preset(merged, "basic_rpg")
    assert got is not None and got["label"] == "本包基础"
    assert [p["id"] for p in merged][0] == "basic_rpg"   # 位置不变


def test_merge_ignores_malformed_pack_presets() -> None:
    merged = mp.merge_module_presets(
        [None, {"id": "", "modules": ["a"]}, {"id": "novalue", "modules": []},
         {"id": "bad", "modules": "a"}])
    assert [p["id"] for p in merged] == [p["id"] for p in mp.FRAMEWORK_MODULE_PRESETS]


# =====================================================================================
# C. API：空白包也有框架默认；包声明覆盖 / 追加 / 关闭
# =====================================================================================
def test_catalog_blank_pack_has_framework_presets(root: Path) -> None:
    cat = api.module_catalog("blank_pack", root=root)
    ids = [p["id"] for p in cat["presets"]]
    assert ids == ["basic_rpg", "life_adventure", "story_exploration"]
    assert cat["presets_title"] == "推荐组合"
    assert cat["presets_hint"]
    for p in cat["presets"]:
        assert p["add_modules"], p["id"]
        assert p["already"] is False
        assert p["modules_labels"] and len(p["modules_labels"]) == len(p["modules"])


def test_catalog_pack_declaration_override_append_disable(tmp_path: Path) -> None:
    pkg = tmp_path / "ovr"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "O", "version": "1", "schema_version": 1, "modules": ["skills"],
        "module_presets": [
            {"id": "basic_rpg", "label": "本包基础", "help": "覆盖版", "audience": "本包",
             "modules": ["skills"]},
            {"id": "zz_mine", "label": "我的组合", "help": "追加", "audience": "",
             "modules": ["skills", "maps"]},
        ],
        "module_presets_disable": ["life_adventure"],
    })
    _write(pkg / "skills.json", [])
    cat = api.module_catalog("ovr", root=tmp_path)
    ids = [p["id"] for p in cat["presets"]]
    assert ids == ["basic_rpg", "story_exploration", "zz_mine"]
    basic = mp.find_module_preset(cat["presets"], "basic_rpg")
    assert basic["label"] == "本包基础" and basic["help"] == "覆盖版"
    mine = mp.find_module_preset(cat["presets"], "zz_mine")
    assert mine["add_modules"] == ["maps"]          # skills 已启用


def test_catalog_preset_reports_unknown_module_not_silent(tmp_path: Path) -> None:
    pkg = tmp_path / "bad"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "B", "version": "1", "schema_version": 1, "modules": [],
        "module_presets": [{"id": "p", "label": "P", "help": "", "audience": "",
                            "modules": ["no_such_mod", "skills"]}],
    })
    cat = api.module_catalog("bad", root=tmp_path)
    row = mp.find_module_preset(cat["presets"], "p")
    assert "no_such_mod" not in row["modules"]
    assert row["unknown"] == ["no_such_mod"]
    assert "skills" in row["modules"]


# =====================================================================================
# D. 一键应用
# =====================================================================================
def test_apply_preset_enables_all_with_dependencies(root: Path) -> None:
    pkg = root / "blank_pack"
    res = editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root)
    assert res["ok"] is True
    declared = _read(pkg / "manifest.json")["modules"]
    assert declared == ["items", "equipment", "skills", "skill_chains", "effects",
                        "statuses", "enemies", "maps", "quest", "npc", "shop", "stats"]
    # 骨架落盘：list → []、map → {}、object → {}
    assert _read(pkg / "skills.json") == []
    assert _read(pkg / "stats.json") == {}
    assert _read(pkg / "quest.json") == []
    assert (pkg / "manifest.json.bak").is_file()      # 单次备份


def test_apply_preset_auto_adds_missing_dependencies(root: Path) -> None:
    pkg = root / "blank_pack"
    res = editor_ops.apply_module_preset("blank_pack", "life_adventure", root=root)
    assert res["ok"] is True
    assert set(res["dependency_added"]) == {"maps", "effects"}
    declared = _read(pkg / "manifest.json")["modules"]
    assert "maps" in declared and "effects" in declared
    assert (pkg / "maps.json").is_file() and (pkg / "effects.json").is_file()


def test_apply_preset_does_not_remove_user_selection(root: Path) -> None:
    pkg = root / "blank_pack"
    editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)
    before = _read(pkg / "manifest.json")["modules"]
    res = editor_ops.apply_module_preset("blank_pack", "story_exploration", root=root)
    assert res["ok"] is True
    after = _read(pkg / "manifest.json")["modules"]
    for mod in before:
        assert mod in after                            # 累加：已勾的仍在
    assert "skills" in after


def test_apply_preset_then_rollback_undoes_whole_preset(root: Path) -> None:
    pkg = root / "blank_pack"
    editor_ops.set_module_enabled("blank_pack", "items", True, root=root)  # 用户先勾 1 个
    base = _read(pkg / "manifest.json")["modules"]
    editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root)
    assert len(_read(pkg / "manifest.json")["modules"]) > len(base)
    res = editor_ops.rollback_module_config("blank_pack", root=root)
    assert res["ok"] is True
    assert _read(pkg / "manifest.json")["modules"] == base       # 整个组合一次撤销
    assert (pkg / "skills.json").is_file()                       # 数据文件始终保留


def test_apply_preset_twice_is_idempotent_green(root: Path) -> None:
    editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root)
    res = editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root)
    assert res["ok"] is True and res["enabled"] == []
    assert "都已启用" in res["message"]


def test_apply_unknown_preset_is_bad_request(root: Path) -> None:
    with pytest.raises(api.BadRequest):
        editor_ops.apply_module_preset("blank_pack", "nope", root=root)


def test_apply_preset_readonly_role_forbidden_writes_nothing(root: Path) -> None:
    pkg = root / "blank_pack"
    before = (pkg / "manifest.json").read_bytes()
    with pytest.raises(api.Forbidden):
        editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root,
                                       role=editor_ops.ROLE_GM)
    assert (pkg / "manifest.json").read_bytes() == before
    assert not (pkg / "items.json").exists()


def test_apply_pack_declared_preset_works(tmp_path: Path) -> None:
    pkg = tmp_path / "ovr2"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "O2", "version": "1", "schema_version": 1, "modules": [],
        "module_presets": [{"id": "zz_mine", "label": "我的组合", "help": "H",
                            "audience": "A", "modules": ["skills", "maps"]}],
    })
    res = editor_ops.apply_module_preset("ovr2", "zz_mine", root=tmp_path)
    assert res["ok"] is True
    assert _read(pkg / "manifest.json")["modules"] == ["skills", "maps"]


def test_apply_pack_preset_unknown_module_warns_and_skips(tmp_path: Path) -> None:
    pkg = tmp_path / "bad2"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "B2", "version": "1", "schema_version": 1, "modules": [],
        "module_presets": [{"id": "p", "label": "P", "help": "", "audience": "",
                            "modules": ["no_such_mod", "skills"]}],
    })
    res = editor_ops.apply_module_preset("bad2", "p", root=tmp_path)
    assert res["ok"] is True
    assert _read(pkg / "manifest.json")["modules"] == ["skills"]
    assert any(w.get("code") == "preset_unknown_module" for w in res["warnings"])


# =====================================================================================
# E. 零变化（只读接口不改包；不应用组合 → 逐字段不变）
# =====================================================================================
def test_read_only_catalog_does_not_touch_pack(root: Path) -> None:
    pkg = root / "blank_pack"
    before_manifest = (pkg / "manifest.json").read_bytes()
    before_files = sorted(x.name for x in pkg.iterdir())
    for _ in range(2):
        api.module_catalog("blank_pack", root=root)
    assert (pkg / "manifest.json").read_bytes() == before_manifest
    assert sorted(x.name for x in pkg.iterdir()) == before_files
    assert not (pkg / "manifest.json.bak").exists()


def test_catalog_modules_shape_unchanged_by_presets(root: Path) -> None:
    """新字段只**增加** presets* 键；既有 modules/total/enabled_count 口径逐字段不变。"""
    cat = api.module_catalog("blank_pack", root=root)
    assert set(cat) - {"presets", "presets_title", "presets_hint"} == {
        "pack", "pack_name", "hint", "modules", "total", "enabled_count",
        "manifest_backup",
    }
    assert cat["total"] == len(FRAMEWORK_MODULE_CATALOG)
    assert cat["enabled_count"] == 0


# =====================================================================================
# F. 宿主端点 + 通用性护栏
# =====================================================================================
def _client(root: Path, pack: str = "blank_pack", role: str = "owner"):
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    from editor_host import create_app  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    return TestClient(create_app(pack=pack, root=str(root), role=role))


def test_host_module_preset_endpoint(root: Path) -> None:
    with _client(root) as client:
        cat = client.get("/api/pack/blank_pack/module-catalog").json()
        assert any(p["id"] == "basic_rpg" for p in cat["presets"])
        res = client.post("/api/pack/blank_pack/module-preset/basic_rpg/apply").json()
        assert res["ok"] is True
        assert "skills" in _read(root / "blank_pack" / "manifest.json")["modules"]
        assert client.get("/api/pack/blank_pack/manifest/backup").json()["exists"] is True
        assert client.post("/api/pack/blank_pack/manifest/rollback").json()["ok"] is True
        assert "skills" not in _read(root / "blank_pack" / "manifest.json")["modules"]


def test_preset_source_has_no_real_pack_names_or_business_fields() -> None:
    src = PRESET_SRC.read_text(encoding="utf-8")
    for word in ("veinborn", "test_demo", "cloudsea"):
        assert word not in src, word
