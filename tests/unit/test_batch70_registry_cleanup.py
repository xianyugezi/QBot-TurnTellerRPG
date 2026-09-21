"""批70 · 「登记了却不生效」清账——删除类 / 标注类验收。

对应 `审计4_勿增实体_死实体与空转.md` §2 无消费者登记表：
  · 删除类：R-（§4）`forge.decompose_rate` 重复键（真源 = settings.alchemy.decompose_rate）；
  · 标注类：R4 reward_mult_pct / R9 copy_slot / R10–R22 formula 展示层字段 /
    R23 report_effective_share / R24–R25 settings.env_event|log_card /
    R26–R33 ai|hidden 视图字段——保留键但编辑器说明显式写「未实现」。
  · 接线后预设生效：R6 weapon_dmg / R7 armor_dur_down / R8 armor_dur_up 指向的轴已有消费点。

纪律：只读框架/内容元数据 + 内存构造，不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.content.effect_presets import FRAMEWORK_EFFECT_PRESETS
from qbot_rpg.content.field_meta import (
    AI_FIELDS,
    HIDDEN_FIELDS,
    LOG_CARD_FIELDS,
    ENV_EVENT_FIELDS,
    SETTINGS_FIELDS,
    default_field_meta_table,
)
from qbot_rpg.content.forge_settings import (
    FORGE_SETTINGS_DEFAULTS,
    FORGE_SETTINGS_FIELD_DEFS,
    FORGE_SETTINGS_KEYS,
    read_forge_settings,
)
from qbot_rpg.content.validator import check_pack
from qbot_rpg.data.gear_stats import (
    EFFECT_CONSUMER_PENDING,
    effect_axis_spec,
)

CONTENT = Path(__file__).resolve().parents[2] / "content"


# ===========================================================================
# 删除类 · forge.decompose_rate（重复键清账）
# ===========================================================================
def test_deleted_forge_decompose_rate_absent_from_registry() -> None:
    """键集 / 默认表 / 字段表 / forge.json settings FieldMeta 均不再含该键。"""
    assert "decompose_rate" not in FORGE_SETTINGS_KEYS
    assert "decompose_rate" not in FORGE_SETTINGS_DEFAULTS
    assert "decompose_rate" not in FORGE_SETTINGS_FIELD_DEFS
    from qbot_rpg.content import forge_models
    assert "decompose_rate" not in dict(
        forge_models.FORGE_TOP_FIELD_DEFS["settings"].children)


def test_deleted_forge_decompose_rate_not_read() -> None:
    """残留配置不产生任何输出键（不再被 read_forge_settings 识别）。"""
    got = read_forge_settings({"forge": {"decompose_rate": {"正式": 0.5}}})
    assert "decompose_rate" not in got
    assert set(got) == set(FORGE_SETTINGS_KEYS)


def test_deleted_forge_decompose_rate_absent_from_packs() -> None:
    """包声明同步撤下：test_demo 的 settings.json forge 段 + forge.json settings 段。"""
    settings = json.loads((CONTENT / "test_demo" / "settings.json").read_text("utf-8"))
    assert "decompose_rate" not in settings["forge"]
    assert "decompose_rate" in settings["alchemy"]      # 真源仍在（alchemy 段）
    forge = json.loads((CONTENT / "test_demo" / "forge.json").read_text("utf-8"))
    assert "decompose_rate" not in forge["settings"]


def test_deleted_forge_decompose_rate_yellow_migration_hint() -> None:
    """残余 → 校验器黄提示 Y-21（指向 settings.alchemy.decompose_rate），不阻断。"""
    res = check_pack({"settings": {"forge": {"decompose_rate": {"正式": 0.5}}}})
    assert [(e.field, e.detail.get("rule")) for e in res.errors] == []
    hits = [w for w in res.warnings if w.detail.get("rule") == "moved_to_alchemy"]
    assert hits, [w.detail for w in res.warnings]
    assert hits[0].field == "settings.forge.decompose_rate"
    assert "settings.alchemy.decompose_rate" in str(hits[0].detail.get("msg", ""))
    # 无残留 → 不提示（零噪音）
    clean = check_pack({"settings": {"forge": {"forge_fee": "节点等级×10"}}})
    assert not [w for w in clean.warnings if w.detail.get("rule") == "moved_to_alchemy"]


# ===========================================================================
# 标注类 · 编辑器说明含「未实现」
# ===========================================================================
def _preset_axes(p: dict) -> set:
    return {str(p.get("axis"))} | {str(k) for k in (p.get("defaults") or {})}


def test_r4_reward_mult_pct_marked_unimplemented() -> None:
    """R4：reward_mult_pct 仍是待接哨兵，但 display.help 显式写「未实现」。"""
    spec = effect_axis_spec("reward_mult_pct")
    assert spec["consumer"] == EFFECT_CONSUMER_PENDING
    assert "未实现" in spec["display"]["help"]
    # 预设不得把它当可用能力发售（当前确无预设引用）
    assert not [p for p in FRAMEWORK_EFFECT_PRESETS
                if "reward_mult_pct" in _preset_axes(p)]


def test_r6_r7_r8_presets_point_to_wired_axes() -> None:
    """R6/R7/R8：3 条框架预设指向的轴接线后不再是无消费轴（consumer 非待接哨兵）。"""
    by_id = {str(p["id"]): p for p in FRAMEWORK_EFFECT_PRESETS}
    for pid, axis in (("weapon_dmg", "damage_dealt_pct"),
                      ("armor_dur_down", "status_duration_taken_pct"),
                      ("armor_dur_up", "status_duration_taken_pct")):
        assert by_id[pid]["axis"] == axis
        spec = effect_axis_spec(axis)
        assert spec["consumer"] != EFFECT_CONSUMER_PENDING
        assert "批70" in spec["consumer_note"]


def test_r10_r22_formula_display_fields_marked_unimplemented() -> None:
    """R10–R22：formula 展示层无 reader 字段 help 显式写「未实现」。"""
    fields = default_field_meta_table().module("formula").fields
    cases = [
        (fields["damage"].children, "floor_mode"),
        (fields["damage"].children, "deep_floor"),
        (fields["luck"].children, "enhance_rate"),
        (fields["luck"].children, "effect_prob"),
        (fields["luck"].children, "max_mod"),
        (fields["power"].children, "max"),
        (fields["power"].children, "formula_max"),
        (fields["effects_link"].children, "intercept_order"),
        (fields["effects_link"].children, "pierce_cap"),
        # 批78 · U4：stats_collector 三字段已实装（聚合/dummy_log/dummy_realtime），
        # 从「无 reader → 标未实现」清单移除；改由 tests/unit/test_batch78_u4_stats.py
        # 正向断言其读取点与行为。
        (fields, "weapon_type_mult"),
    ]
    for children, key in cases:
        assert "未实现" in children[key].help, key


def test_r23_report_effective_share_marked_unimplemented() -> None:
    """R23：settings.effect_budget.report_effective_share help 写「未实现」。"""
    field = SETTINGS_FIELDS["effect_budget"].children["report_effective_share"]
    assert "未实现" in field.help


def test_r24_r25_settings_view_sections_marked_unimplemented() -> None:
    """R24/R25：settings.env_event / settings.log_card 两段 help 写「未实现」。"""
    assert "未实现" in SETTINGS_FIELDS["env_event"].help
    assert "未实现" in SETTINGS_FIELDS["log_card"].help
    assert "未实现" in ENV_EVENT_FIELDS["env_event"].help
    assert "未实现" in LOG_CARD_FIELDS["log_card"].help


def test_r26_r33_ai_hidden_views_marked_unimplemented() -> None:
    """R26–R33：ai/hidden 视图字段名与真实键不符 → 逐条 help 写「未实现」（点名真实键）。"""
    for key in ("ai_actions", "ai_cond_actions", "ai_state_machine",
                "ai_phases", "ai_combo", "ai_zone_switch"):
        assert "未实现" in AI_FIELDS[key].help, key
    for key in ("hidden_quest", "easter_egg"):
        assert "未实现" in HIDDEN_FIELDS[key].help, key
    # hidden_boss 是真消费键（monsters 模块 bool），不在此标注（同键异型待裁决）
    assert not (HIDDEN_FIELDS["hidden_boss"].help or "").startswith("【未实现】")
    # 真实键指引（ai.states / ai.transitions / 顶层 phases）
    assert "ai.states" in AI_FIELDS["ai_actions"].help
    assert "phases" in AI_FIELDS["ai_phases"].help


def test_r9_copy_slot_marked_unimplemented_in_pack_help() -> None:
    """R9：copy_slot 在包编辑器说明里写「未实现」（引擎不读复制位）。"""
    for pack in ("veinborn", "test_demo"):
        raw = json.loads((CONTENT / pack / "field_meta.json").read_text("utf-8"))
        farming = raw["field_help"]["settings"]["alchemy"]["farming"]
        assert isinstance(farming, dict)
        assert "未实现" in farming["greenhouse"]["copy_slot"]
