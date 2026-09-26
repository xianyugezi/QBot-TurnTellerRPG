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
import re
import shutil
import subprocess
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


# =====================================================================================
# G. 前端（index.html）：推荐组合区 + 两处空态引导 + 页脚批次串（DOM 文本存在性）
# =====================================================================================
NODE = shutil.which("node")
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str, next_name: str) -> str:
    """截取 index.html 里 `function name(` 到下一个 `function next_name(` 的源码。"""
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end].rstrip()
    lines = src.split("\n")
    while lines:
        tail = lines[-1].strip()
        if tail == "" or tail.startswith("//") or tail.startswith("/*") \
                or tail.startswith("*") or tail.endswith("*/"):
            lines.pop()
            continue
        break
    src = "\n".join(lines)
    assert src.endswith("}"), (name, src[-40:])
    return src


# 内联页面里的转义函数 esc（node 下补桩，与既有批次同一手法）。
_ESC_STUB = (
    "global.esc = function (v) { return String(v == null ? '' : v)"
    ".replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')"
    ".replace(/\"/g, '&quot;').replace(/'/g, '&#39;'); };\n"
)


def _run_node(script: str) -> Any:
    assert NODE, "node 不可用"
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_frontend_preset_section_markup_and_wiring() -> None:
    html = _html()
    for token in ('id="mp-presets"', "renderModulePresets(d)", "function presetCardHtml(",
                  "function renderModulePresets(", "function onApplyModulePreset(",
                  "data-preset=", "/module-preset/", "/apply", "已自动带上：",
                  "dependency_added_labels", "回退最近一次模块变更"):
        assert token in html, token


def test_frontend_preset_card_renders_only_backend_data() -> None:
    script = (_ESC_STUB + _fn_src("presetCardHtml", "renderModulePresets")
              + "\nvar a = presetCardHtml({id:'zz',label:'组合甲',help:'一句话说明',"
              + "audience:'面向新人',modules:['a','b'],add_modules:['a','b'],"
              + "auto_deps:['b'],already:false});"
              + "\nvar b = presetCardHtml({id:'yy',label:'组合乙',modules:['a'],"
              + "add_modules:[],auto_deps:[],already:true});"
              + "\nconsole.log(JSON.stringify({a:a,b:b}));")
    out = _run_node(script)
    assert 'data-preset="zz"' in out["a"] and "组合甲" in out["a"]
    assert "一句话说明" in out["a"] and "面向新人" in out["a"]
    assert "将新增 2 个模块" in out["a"] and "含自动补勾依赖 1 个" in out["a"]
    assert "disabled" not in out["a"]
    assert "disabled" in out["b"] and "mp-preset on" in out["b"]
    assert "已全部启用" in out["b"]


def test_frontend_preset_region_has_no_hardcoded_module_list() -> None:
    src = (_fn_src("presetCardHtml", "renderModulePresets")
           + _fn_src("renderModulePresets", "onApplyModulePreset")
           + _fn_src("onApplyModulePreset", "renderAliasPanel"))
    for word in ("basic_rpg", "life_adventure", "story_exploration",
                 "skills", "equipment", "items", "veinborn"):
        assert word not in src, word


def test_frontend_two_empty_states_distinguish_cases() -> None:
    script = (_ESC_STUB + _fn_src("listEmptyHtml", "renderEmptyPack")
              + "\nglobal.state = {modules: [], views: []};"
              + "\nvar none = listEmptyHtml();"
              + "\nglobal.state = {modules: [{module:'skills'}], views: []};"
              + "\nvar has = listEmptyHtml();"
              + "\nconsole.log(JSON.stringify({none:none, has:has}));")
    out = _run_node(script)
    assert "还没启用任何模块" in out["none"]
    assert "data-open-modules" in out["none"] and "⚙" in out["none"]
    assert "推荐组合" in out["none"]
    assert "还没启用任何模块" not in out["has"]
    assert "这个模块还没有条目" in out["has"] and "+ 新建条目" in out["has"]


def test_frontend_rows_use_empty_state_guide() -> None:
    assert "listEmptyHtml()" in _fn_src("renderEmptyPack", "refreshAfterModuleChange")
    assert "listEmptyHtml()" in _fn_src("renderEntries", "entryItemEl")


def test_frontend_left_column_unavailable_guide_present() -> None:
    src = _fn_src("renderModules", "enableAvailableModule")
    assert "未启用 · 框架能力" in src
    assert "sep-h" in src and "推荐组合" in src


def test_frontend_batch65_css_uses_tokens_only() -> None:
    html = _html()
    for begin in (".mp-presets {", ".mp-preset {", ".lempty {"):
        start = html.index(begin)
        seg = html[start:html.index("}", start) + 1]
        assert "var(--" in seg, begin
        assert not re.search(r"#[0-9a-fA-F]{3,6}", seg), begin


def test_frontend_footer_batch_string_is_current() -> None:
    html = _html()
    m = re.search(r'<div class="panel-ft"><span>(.*?)</span></div>', html)
    assert m and m.group(1) == "批82 · 手册剩余项收口", m and m.group(1)
    assert "批62 · 深炼金口径C与淬炼指令" not in html


# =====================================================================================
# H. 依赖闭包标签 + 零变化对拍 + 端到端（宿主 HTTP）
# =====================================================================================
def test_apply_preset_reports_dependency_labels(root: Path) -> None:
    res = editor_ops.apply_module_preset("blank_pack", "life_adventure", root=root)
    assert res["ok"] is True
    assert set(res["dependency_added"]) == {"maps", "effects"}
    assert res["dependency_added_labels"]
    assert len(res["dependency_added_labels"]) == len(res["dependency_added"])
    assert all(lbl for lbl in res["dependency_added_labels"])


def test_dependency_labels_empty_when_already_enabled(root: Path) -> None:
    editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root)
    res = editor_ops.apply_module_preset("blank_pack", "basic_rpg", root=root)
    assert res["ok"] is True
    assert res["dependency_added"] == [] and res["dependency_added_labels"] == []


def test_no_op_byte_for_byte_unchanged(root: Path) -> None:
    """不做任何操作：反复读接口后整包逐字节不变（含 manifest.json 不被改写）。"""
    pkg = root / "blank_pack"
    before = {p.name: p.read_bytes() for p in sorted(pkg.iterdir())}
    for _ in range(3):
        api.module_catalog("blank_pack", root=root)
        api.list_modules("blank_pack", root=root)
    after = {p.name: p.read_bytes() for p in sorted(pkg.iterdir())}
    assert after == before
    assert not (pkg / "manifest.json.bak").exists()


def test_apply_disabled_preset_is_bad_request(tmp_path: Path) -> None:
    pkg = tmp_path / "dis"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "关闭", "version": "1", "schema_version": 1, "modules": [],
        "module_presets_disable": ["basic_rpg"],
    })
    cat = api.module_catalog("dis", root=tmp_path)
    assert "basic_rpg" not in [p["id"] for p in cat["presets"]]
    with pytest.raises(api.BadRequest):
        editor_ops.apply_module_preset("dis", "basic_rpg", root=tmp_path)


def test_e2e_blank_apply_preset_then_create_then_rollback(tmp_path: Path) -> None:
    pkg = tmp_path / "e2e"
    pkg.mkdir()
    _write(pkg / "manifest.json",
           {"name": "端到端", "version": "1", "schema_version": 1, "modules": []})
    with _client(tmp_path, pack="e2e") as client:
        cat = client.get("/api/pack/e2e/module-catalog").json()
        assert [p["id"] for p in cat["presets"]] == [
            "basic_rpg", "life_adventure", "story_exploration"]
        applied = client.post("/api/pack/e2e/module-preset/basic_rpg/apply").json()
        assert applied["ok"] is True
        assert "skills" in _read(pkg / "manifest.json")["modules"]
        # 能新建条目：先补一个普攻（V-7 要求），再新建物品
        skill = client.post(
            "/api/pack/e2e/module/skills/entry",
            json={"entry_id": "zz_basic", "patch": {"name": "普攻", "type": "basic"}}).json()
        assert skill["ok"] is True
        item = client.post(
            "/api/pack/e2e/module/items/entry",
            json={"entry_id": "zz_item", "patch": {"name": "测试物品"}}).json()
        assert item["ok"] is True
        # 回退最近一次模块变更 → 整个组合一次撤销
        assert client.post("/api/pack/e2e/manifest/rollback").json()["ok"] is True
        assert _read(pkg / "manifest.json")["modules"] == []
