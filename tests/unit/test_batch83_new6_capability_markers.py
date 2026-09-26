"""批83 · NEW-6：能力标记模块可被勾选写入 manifest，且不再触发 WIR-13 门禁误报。

背景（`/root/deliverables/手册剩余项_核清与口径.md` NEW-6 / Q7）：`assistant` / `codex` /
`contest` / `farming` / `gathering` / `quest_board` 6 个目录条目 `implemented=True`、
`settings_section` 非空（gathering 落 `maps` 子段），可被编辑器勾选；`web/editor_ops.py::
set_module_enabled` **实测会把模块写入 `manifest.modules`**。但它们无 loader kind、无
field_meta 校验器 → `check_manifest_modules_registered` 原会报出它们（框架自身门禁误报）。

裁定 + 落地：这 6 个是**文档化的能力标记**（配置落 settings/maps 段，验证由该段承接），
非"漏接校验器"；故 `check_manifest_modules_registered` 对其豁免（`CAPABILITY_MARKER_MODULES`），
同时保持对**真正未登记模块**的拦截。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from qbot_rpg.content.loader import check_manifest_modules_registered
from qbot_rpg.content.module_catalog import CAPABILITY_MARKER_MODULES, catalog_entry
from qbot_rpg.web import editor_ops

_REPO = Path(__file__).resolve().parents[2]
_CONTENT = _REPO / "content"


def test_capability_marker_set_is_exactly_the_six() -> None:
    assert set(CAPABILITY_MARKER_MODULES) == {
        "assistant", "codex", "contest", "farming", "gathering", "quest_board"}
    for mod in CAPABILITY_MARKER_MODULES:
        ce = catalog_entry(mod)
        assert ce is not None and ce.implemented is True


def test_enabling_capability_marker_writes_manifest_and_passes_gate(tmp_path: Path) -> None:
    """勾选 `farming` → 写 manifest.modules（实测）→ 门禁不再误报。"""
    root = tmp_path / "content"
    shutil.copytree(_CONTENT / "demo_blank", root / "demo_blank")
    env = editor_ops.set_module_enabled("demo_blank", "farming", True, root=root,
                                        role="owner")
    assert env.get("errors") == [], env
    manifest = json.loads(
        (root / "demo_blank" / "manifest.json").read_text(encoding="utf-8"))
    assert "farming" in manifest["modules"]           # 确认确实写入 manifest
    assert (root / "demo_blank" / "farming.json").read_text(
        encoding="utf-8").strip() == "{}"
    assert check_manifest_modules_registered(manifest["modules"]) == []


def test_gate_still_reports_unknown_module() -> None:
    """豁免只覆盖 6 个能力标记：真正未登记的模块名仍被拦（防「整包绕过校验」）。"""
    assert check_manifest_modules_registered(["settings", "not_a_real_module"]) == \
        ["not_a_real_module"]


def test_all_six_pass_gate_when_declared() -> None:
    assert check_manifest_modules_registered(list(CAPABILITY_MARKER_MODULES)) == []
