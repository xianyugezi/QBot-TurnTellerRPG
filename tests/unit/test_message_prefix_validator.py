"""M5-02 message_prefix 段校验器（红/黄分类）单元测试 —— tests/unit/test_message_prefix_validator.py

测试目标：qbot_rpg.content.validator.check_pack 中 settings.message_prefix 段校验
（`_check_message_prefix`，红拦 kind=MP-1 / 黄提示 kind=MP-2）。
依据：【前缀】§九 L112-121 + 细化_3d 附·校验器行 L358 + m5_shared_contract §1.4。
断言级别：errors=红拦（拒绝加载，rep.ok=False）/ warnings=黄提示（可加载，rep.ok=True）。
"""
from __future__ import annotations

from qbot_rpg.content.models import PackError, PackWarning, ValidationReport
from qbot_rpg.content.validator import (
    MESSAGE_PREFIX_DEFAULT_FORMAT,
    check_pack,
    message_prefix_unknown_placeholders,
)


def _rep(mp: object) -> ValidationReport:
    """check_pack 整包校验（settings 仅含 message_prefix 段）。"""
    return check_pack({"settings": {"message_prefix": mp}})


def _errs(rep: ValidationReport, rule=None) -> list:
    return [e for e in rep.errors if rule is None or e.detail.get("rule") == rule]


def _warns(rep: ValidationReport, rule=None) -> list:
    return [w for w in rep.warnings if rule is None or w.detail.get("rule") == rule]


def _ok(mp: object) -> ValidationReport:
    """断言包可加载（零红拦）并返回报告。"""
    rep = _rep(mp)
    assert rep.ok, (
        f"应可加载（零红拦）：{mp} → "
        f"{[(e.field, e.detail.get('rule')) for e in rep.errors]}"
    )
    return rep


def _assert_red(err: PackError, rule: str, field: str) -> None:
    assert err.kind == "MP-1", f"红拦 kind 应为 MP-1，实际 {err.kind}"
    assert err.detail.get("rule") == rule
    assert err.field == field


def _assert_yellow(w: PackWarning, rule: str) -> None:
    assert w.kind == "MP-2", f"黄提示 kind 应为 MP-2，实际 {w.kind}"
    assert w.detail.get("rule") == rule


# -------------------------------------------------------------------------------------
# 合法包：零红零黄
# -------------------------------------------------------------------------------------
def test_legal_pack_zero_red_yellow():
    rep = _rep({"enabled": True, "format": "Lv[等级].[玩家名] -[称号]-"})
    assert rep.ok
    assert not rep.errors, f"合法包不应红拦：{rep.errors}"
    assert not rep.warnings, f"合法包不应黄提示：{rep.warnings}"


def test_legal_full_config_zero_red_yellow():
    rep = _rep({
        "enabled": True, "format": "Lv[等级].[玩家名] -[称号]-",
        "show_on_system": False, "per_channel": "group",
        "hide_when_empty": True, "empty_title_text": "-", "prefix_max_len": 40,
    })
    assert rep.ok
    assert not rep.errors and not rep.warnings


def test_section_absent_zero_red_yellow():
    # 段未配置 → 走默认模板（3d §1.2），零红零黄
    rep = check_pack({"settings": {"currencies": []}})
    assert rep.ok
    assert not rep.errors and not rep.warnings


def test_prefix_max_len_zero_ok():
    # 0=不限（【前缀】L100）→ 不红不黄；段内字段缺省也不红（全有默认值，§十 示例 5）
    rep = _ok({"enabled": False, "prefix_max_len": 0})
    assert not rep.errors and not rep.warnings


# -------------------------------------------------------------------------------------
# 红拦（kind=MP-1，拒绝加载）
# -------------------------------------------------------------------------------------
def test_enabled_non_bool_red():
    rep = _rep({"enabled": "yes", "format": "Lv[等级].[玩家名]"})
    errs = _errs(rep, "enabled_type")
    assert len(errs) == 1
    _assert_red(errs[0], "enabled_type", "settings.message_prefix.enabled")
    assert errs[0].detail["got"] == "str"
    assert not rep.ok


def test_format_non_string_red():
    rep = _rep({"enabled": True, "format": 123})
    errs = _errs(rep, "format_type")
    assert len(errs) == 1
    _assert_red(errs[0], "format_type", "settings.message_prefix.format")
    assert not rep.ok


def test_prefix_max_len_negative_red():
    rep = _rep({"enabled": True, "format": "Lv[等级].[玩家名]", "prefix_max_len": -1})
    errs = _errs(rep, "prefix_max_len_negative")
    assert len(errs) == 1
    _assert_red(errs[0], "prefix_max_len_negative", "settings.message_prefix.prefix_max_len")
    assert errs[0].detail["value"] == -1
    assert "0（=不限长度）" in errs[0].detail["msg"]
    assert not rep.ok


def test_section_structure_non_object_red():
    # 结构错误（人话模板）：message_prefix 段是字符串 → 红拦拒绝加载
    rep = check_pack({"settings": {"message_prefix": "hello"}})
    errs = _errs(rep, "section_structure")
    assert len(errs) == 1
    _assert_red(errs[0], "section_structure", "settings.message_prefix")
    assert "要填对象" in errs[0].detail["msg"]
    assert not rep.ok


def test_section_structure_null_red():
    rep = check_pack({"settings": {"message_prefix": None}})
    errs = _errs(rep, "section_structure")
    assert len(errs) == 1
    _assert_red(errs[0], "section_structure", "settings.message_prefix")
    assert not rep.ok


# -------------------------------------------------------------------------------------
# 黄提示（kind=MP-2，可加载）
# -------------------------------------------------------------------------------------
def test_unknown_placeholder_yellow():
    # 未知占位符原样输出不拦（【前缀】L75/L117）→ 黄提示 + 可加载
    rep = _ok({"enabled": True, "format": "[等级][世界]"})
    warns = _warns(rep, "placeholder_unknown")
    assert len(warns) == 1
    _assert_yellow(warns[0], "placeholder_unknown")
    assert warns[0].detail["placeholder"] == "[世界]"
    assert "不认识的东西 [世界]" in warns[0].detail["msg"]


def test_unknown_placeholders_each_emits_yellow():
    rep = _ok({"format": "[世界][职业][火星]"})
    warns = _warns(rep, "placeholder_unknown")
    assert {w.detail["placeholder"] for w in warns} == {"[世界]", "[火星]"}


def test_unknown_placeholder_helper():
    assert message_prefix_unknown_placeholders("Lv[等级].[玩家名] -[称号]-") == []
    assert message_prefix_unknown_placeholders("[等级][世界][群名]") == ["[世界]"]


def test_format_empty_yellow():
    # format 空 → 按默认补全提示（【前缀】L118）
    rep = _ok({"enabled": True, "format": ""})
    warns = _warns(rep, "format_empty")
    assert len(warns) == 1
    _assert_yellow(warns[0], "format_empty")
    assert warns[0].detail["default"] == MESSAGE_PREFIX_DEFAULT_FORMAT
    assert "已按默认格式补全" in warns[0].detail["msg"]


def test_format_too_long_yellow():
    rep = _ok({"format": "X" * 90})  # 90 字符 > 80
    warns = _warns(rep, "format_too_long")
    assert len(warns) == 1
    _assert_yellow(warns[0], "format_too_long")
    assert warns[0].detail["length"] == 90
    assert "注意前缀别刷屏" in warns[0].detail["msg"]


def test_placeholder_too_many_yellow():
    rep = _ok({"format": "[等级]" * 11})  # 11 个占位符 > 10
    warns = _warns(rep, "format_too_long")
    assert len(warns) == 1
    assert warns[0].detail["placeholder_count"] == 11


def test_per_channel_invalid_yellow():
    # per_channel 枚举非法 → 按默认 all 补全提示（【前缀】L120）
    rep = _ok({"enabled": True, "format": "Lv[等级]", "per_channel": "everywhere"})
    warns = _warns(rep, "per_channel_invalid")
    assert len(warns) == 1
    _assert_yellow(warns[0], "per_channel_invalid")
    assert warns[0].detail["got"] == "everywhere"
    assert warns[0].detail["allowed"] == ["all", "group", "private"]
    assert "已按默认 all 补全" in warns[0].detail["msg"]


def test_per_channel_valid_zero():
    for ch in ("all", "group", "private"):
        rep = _ok({"format": "[玩家名]", "per_channel": ch})
        assert not _warns(rep, "per_channel_invalid")


def test_prefix_max_len_large_yellow():
    rep = _ok({"format": "Lv[等级]", "prefix_max_len": 300})  # >200 → 确认提示
    warns = _warns(rep, "prefix_max_len_large")
    assert len(warns) == 1
    _assert_yellow(warns[0], "prefix_max_len_large")
    assert warns[0].detail["value"] == 300
