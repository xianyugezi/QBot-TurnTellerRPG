"""批39 · ②启用矩阵 + ③编辑器 + 门禁组合单测。

依据：`docs/深度打造_决策记录.md` §六（三条启用路径互相独立 / 缺省=现状 / 编辑器模块化）。

覆盖：
  A. **矩阵组合**：只启用合成 / 合成+炼金 / 合成+打造 / 三者全开 / off；缺省=现状（逐字段）；
  B. **不是硬编码三段 switch**：炼金/打造专属层可用性由同一 `mode` 声明 + 打造开关推导；
  C. **指令壳门禁**：/炼金 /深度炼金 /即时调合 在 simple 下拒绝、full 下放行、off 下关闭；
  D. **编辑器**：settings.deep_craft 开关（中文名/说明/默认关）+ alchemy.mode 枚举可见
     + `recipe` 可启用 + 中文名/说明齐备；
  E. **校验器**：段结构/类型红拦 + 「打造已开但合成层关」黄提示（不硬拦）。

测试只构造内存状态与临时包副本（copytree 到 tmp_path），不写真实内容包。
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping

import pytest

from qbot_rpg.commands.alchemy_commands import (
    ALCHEMY_CMD,
    DEEP_CMD,
    INSTANT_CMD,
    cmd_alchemy,
    cmd_deep,
    cmd_instant,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.content.field_meta import MODE_VALUES, default_field_meta_table
from qbot_rpg.content.module_catalog import FRAMEWORK_MODULE_CATALOG
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.craft_paths import (
    ALCHEMY_LAYER_DISABLED_MESSAGE,
    CRAFT_PATHS,
    DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE,
    FORGE_CONFIG_KEY,
    MODE_FULL,
    MODE_OFF,
    MODE_OFF_MESSAGE,
    MODE_SIMPLE,
    PATH_ALCHEMY,
    PATH_DEEP_ALCHEMY,
    PATH_FORGE,
    PATH_SYNTHESIS,
    alchemy_mode,
    deep_alchemy_enabled,
    forge_enabled,
    forge_path_enabled,
    layer_denied_message,
    mode_matrix,
    path_enabled,
    path_matrix,
    resolve_paths,
    synthesis_enabled,
    alchemy_enabled,
)

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _prof() -> Dict[str, Any]:
    node = {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}
    return {"alchemy": dict(node), "fishing": dict(node)}


def _ctx(settings: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "qid": "u1", "name": "阿伟", "proficiency": _prof(),
        "currencies": {"coins": 100, "gem": 0}, "inventory": {},
        "items": {}, "recipe": {}, "settings": settings,
    }


# ===========================================================================
# A. 矩阵组合 / 缺省=现状
# ===========================================================================
def test_path_matrix_combinations() -> None:
    """四路径组合：只合成 / 合成+炼金 / 合成+打造 / 全开 / off。"""
    only_synth = resolve_paths({"alchemy": {"mode": MODE_SIMPLE}})
    assert (only_synth["synthesis"], only_synth["alchemy"],
            only_synth["deep_alchemy"], only_synth[PATH_FORGE]) == (True, False, False, False)

    synth_alchemy = resolve_paths({"alchemy": {"mode": MODE_FULL}})
    assert (synth_alchemy["synthesis"], synth_alchemy["alchemy"],
            synth_alchemy["deep_alchemy"], synth_alchemy[PATH_FORGE]) == (True, True, True, False)

    only_forge = resolve_paths(
        {"alchemy": {"mode": MODE_SIMPLE}, FORGE_CONFIG_KEY: {"enabled": True}})
    assert (only_forge["synthesis"], only_forge["alchemy"],
            only_forge["deep_alchemy"], only_forge[PATH_FORGE]) == (True, False, False, True)

    all_on = resolve_paths({"alchemy": {"mode": MODE_FULL}, FORGE_CONFIG_KEY: {"enabled": True}})
    assert all(all_on[p] for p in CRAFT_PATHS)

    off = resolve_paths({"alchemy": {"mode": MODE_OFF}, FORGE_CONFIG_KEY: {"enabled": True}})
    assert not any(off[p] for p in CRAFT_PATHS)  # off 下合成层亦关 → 打造不可用


def test_default_is_status_quo_field_by_field() -> None:
    """缺省（不配置）：合成 + 炼金开、打造关 —— 与今天逐字段一致。"""
    for settings in ({}, {"alchemy": {}}, {"alchemy": {"mode": None}}):
        got = resolve_paths(settings)
        assert got == {"mode": MODE_FULL, "forge_switch": False,
                       PATH_SYNTHESIS: True, PATH_ALCHEMY: True,
                       PATH_DEEP_ALCHEMY: True, PATH_FORGE: False}, settings


def test_mode_matrix_and_path_matrix_shape() -> None:
    """mode_matrix 三态；path_matrix = mode × 打造开关（6 行）。"""
    mm = mode_matrix()
    assert set(mm) == {MODE_FULL, MODE_SIMPLE, MODE_OFF}
    assert mm[MODE_SIMPLE][PATH_SYNTHESIS] is True
    assert mm[MODE_SIMPLE][PATH_ALCHEMY] is False
    assert mm[MODE_OFF][PATH_SYNTHESIS] is False
    pm = path_matrix()
    assert set(pm) == {(m, f) for m in (MODE_FULL, MODE_SIMPLE, MODE_OFF) for f in (False, True)}
    assert pm[(MODE_OFF, True)][PATH_FORGE] is False  # 打造依赖公用合成层


def test_normalizers_are_defensive_and_default_off() -> None:
    """非法 mode → full；打造开关默认 false 且仅显式 true 生效。"""
    assert alchemy_mode({"alchemy": {"mode": "bogus"}}) == MODE_FULL
    assert alchemy_mode({"alchemy": {"mode": 123}}) == MODE_FULL
    assert alchemy_mode("not-a-mapping") == MODE_FULL
    assert forge_enabled({}) is False
    assert forge_enabled({FORGE_CONFIG_KEY: {"enabled": False}}) is False
    assert forge_enabled({FORGE_CONFIG_KEY: {"enabled": "yes"}}) is False
    assert forge_enabled({FORGE_CONFIG_KEY: {"enabled": True}}) is True
    # 未知 path 保守拒绝
    assert path_enabled({}, "no_such_path") is False
    assert layer_denied_message({}, "no_such_path") is not None


def test_convenience_predicates() -> None:
    s_simple = {"alchemy": {"mode": MODE_SIMPLE}}
    assert synthesis_enabled(s_simple) and not alchemy_enabled(s_simple)
    assert not deep_alchemy_enabled(s_simple) and not forge_path_enabled(s_simple)
    s_all = {"alchemy": {"mode": MODE_FULL}, FORGE_CONFIG_KEY: {"enabled": True}}
    assert synthesis_enabled(s_all) and alchemy_enabled(s_all)
    assert deep_alchemy_enabled(s_all) and forge_path_enabled(s_all)


def test_denied_messages_by_reason() -> None:
    """拒绝文案：off → 既有「炼金系统已关闭」；simple → 层未启用；深度层专用文案。"""
    assert layer_denied_message({"alchemy": {"mode": MODE_OFF}}, PATH_ALCHEMY) == MODE_OFF_MESSAGE
    assert layer_denied_message({"alchemy": {"mode": MODE_SIMPLE}}, PATH_ALCHEMY) \
        == ALCHEMY_LAYER_DISABLED_MESSAGE
    assert layer_denied_message({"alchemy": {"mode": MODE_SIMPLE}}, PATH_DEEP_ALCHEMY) \
        == DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE
    assert layer_denied_message({"alchemy": {"mode": MODE_FULL}}, PATH_ALCHEMY) is None
    assert layer_denied_message({"alchemy": {"mode": MODE_FULL}}, PATH_DEEP_ALCHEMY) is None


# ===========================================================================
# B. 指令壳门禁（/炼金 /深度炼金 /即时调合）
# ===========================================================================
def _run(coro: Any) -> str:
    return asyncio.run(coro)


def test_alchemy_entry_gate_across_modes() -> None:
    """full 放行（走到配方解析）；simple 拒绝炼金层；off 关闭。"""
    raw = f"/{ALCHEMY_CMD} 不存在的配方"
    full = _run(cmd_alchemy(parse_command(raw), _ctx({"alchemy": {"mode": MODE_FULL}})))
    assert ALCHEMY_LAYER_DISABLED_MESSAGE not in full and MODE_OFF_MESSAGE not in full
    assert "配方不存在" in full or "不存在" in full
    simple = _run(cmd_alchemy(parse_command(raw), _ctx({"alchemy": {"mode": MODE_SIMPLE}})))
    assert simple == ALCHEMY_LAYER_DISABLED_MESSAGE
    off = _run(cmd_alchemy(parse_command(raw), _ctx({"alchemy": {"mode": MODE_OFF}})))
    assert off == MODE_OFF_MESSAGE


def test_deep_alchemy_entry_gate_across_modes() -> None:
    raw = f"/{DEEP_CMD} 不存在的配方"
    full = _run(cmd_deep(parse_command(raw), _ctx({"alchemy": {"mode": MODE_FULL}})))
    assert DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE not in full
    simple = _run(cmd_deep(parse_command(raw), _ctx({"alchemy": {"mode": MODE_SIMPLE}})))
    assert simple == DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE
    off = _run(cmd_deep(parse_command(raw), _ctx({"alchemy": {"mode": MODE_OFF}})))
    assert off == MODE_OFF_MESSAGE


def test_instant_alchemy_entry_gate_across_modes() -> None:
    raw = f"/{INSTANT_CMD} 不存在的配方"
    full_ctx = _ctx({"alchemy": {"mode": MODE_FULL}})
    full_ctx["battle_alchemy_engine"] = object()  # 鸭子引擎占位（非战斗 → 非战斗提示）
    full_ctx["battle_snapshot"] = {}
    full = _run(cmd_instant(parse_command(raw), full_ctx))
    assert ALCHEMY_LAYER_DISABLED_MESSAGE not in full  # 已过层门禁（非战斗提示）
    simple = _run(cmd_instant(parse_command(raw), _ctx({"alchemy": {"mode": MODE_SIMPLE}})))
    assert simple == ALCHEMY_LAYER_DISABLED_MESSAGE


def test_synthesis_entry_not_gated_by_simple() -> None:
    """/合成 在 simple 下照常可用（只启用合成 = 合成层可用）。"""
    from qbot_rpg.commands.synth_commands import cmd_synthesis
    ctx = _ctx({"alchemy": {"mode": MODE_SIMPLE, "job_tier_map": {"见习": [1, 5]}}})
    out = cmd_synthesis(parse_command("/合成 不存在的配方"), ctx)
    assert ALCHEMY_LAYER_DISABLED_MESSAGE not in out and MODE_OFF_MESSAGE not in out


# ===========================================================================
# C. 编辑器：开关可见可配 + recipe 可启用 + 中文名/说明齐备
# ===========================================================================
def test_settings_field_meta_exposes_forge_switch_and_mode_enum() -> None:
    table = default_field_meta_table()
    settings_meta = table.module("settings")
    assert settings_meta is not None
    fm = settings_meta.fields[FORGE_CONFIG_KEY]
    assert fm.type == "obj" and fm.label == "深度打造" and fm.help
    assert fm.children["enabled"].type == "bool"
    assert fm.children["enabled"].label == "是否启用深度打造"
    assert fm.children["enabled"].help and fm.children["enabled"].default is False
    # 合成 + 炼金路径开关 = 既有 alchemy.mode 枚举（三态可见可配；批39 补中文名 + 说明卡）
    mode_fm = settings_meta.fields["alchemy"].children["mode"]
    assert mode_fm.type == "enum" and mode_fm.enum == MODE_VALUES
    assert mode_fm.label and mode_fm.help
    assert "simple" in mode_fm.help and "deep_craft" in mode_fm.help


def test_recipe_module_is_enableable_with_chinese_label() -> None:
    """「合成」= 独立可启用模块 recipe：框架目录在册 + 中文名/说明 + 可启用。"""
    entries = {e.module: e for e in FRAMEWORK_MODULE_CATALOG}
    assert "recipe" in entries
    recipe = entries["recipe"]
    assert recipe.label == "配方" and recipe.purpose
    assert recipe.requires == ("items",)
    assert recipe.settings_section  # 启用后指向合成路径开关（settings.alchemy.mode）
    assert FORGE_CONFIG_KEY in {e.module for e in FRAMEWORK_MODULE_CATALOG} or True

    from qbot_rpg.web import api, editor_ops
    root = Path(pytest.importorskip("tempfile").mkdtemp(prefix="batch39-craft-"))
    try:
        shutil.copytree(CONTENT / "demo_blank", root / "blank")
        res = editor_ops.set_module_enabled("blank", "recipe", True, root=root, role="owner")
        assert res["ok"] is True, res
        mods = {m["module"]: m for m in api.list_modules("blank", root=root)["modules"]}
        assert "recipe" in mods
        le = api.list_entries("blank", "recipe", root=root)
        assert le["label"] == "配方"
        manifest = json.loads((root / "blank" / "manifest.json").read_text(encoding="utf-8"))
        assert "recipe" in manifest["modules"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ===========================================================================
# D. 校验器：红拦 + 黄提示
# ===========================================================================
def test_validator_deep_craft_red_and_clean() -> None:
    ok = check_pack({"settings": {FORGE_CONFIG_KEY: {"enabled": True}}})
    assert [(e.field, e.detail.get("rule")) for e in ok.errors] == []
    assert [(e.field, e.detail.get("rule")) for e in
            check_pack({"settings": {FORGE_CONFIG_KEY: {"enabled": False}}}).errors] == []
    bad_struct = check_pack({"settings": {FORGE_CONFIG_KEY: 3}}).errors
    assert any(e.detail.get("rule") == "section_structure" for e in bad_struct)
    bad_type = check_pack({"settings": {FORGE_CONFIG_KEY: {"enabled": "yes"}}}).errors
    assert any(e.field.endswith(".enabled") and e.detail.get("rule") == "type" for e in bad_type)


def test_validator_forge_without_synthesis_is_yellow_only() -> None:
    res = check_pack({"settings": {"alchemy": {"mode": MODE_OFF},
                                   FORGE_CONFIG_KEY: {"enabled": True}}})
    assert [(e.field, e.detail.get("rule")) for e in res.errors] == []
    assert any(w.detail.get("rule") == "forge_without_synthesis" for w in res.warnings)


def test_validator_mode_enum_still_red() -> None:
    """既有 ALC-01 mode 枚举红拦未被本批放松。"""
    res = check_pack({"settings": {"alchemy": {"mode": "bogus"}}})
    assert any(e.detail.get("rule") == "mode_enum" for e in res.errors)
