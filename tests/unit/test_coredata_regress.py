"""coredata 审查批 P1 回归（审查_M0_coredata_20260818.md）。

- P1-1 条件加成接线：loader 期红拦可达（配对环 R-5 / 未注册键 R-4 / 合法包通过）
- P1-2 前缀自定义 format 空称号占位符不泄漏
- P1-3 前缀截断可观察（render_prefix_result.truncated）
- P1-4 stats 负数 base/growth → 黄提示 + calc 运行期按 0
"""
from __future__ import annotations

import pytest

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.message_format.prefix_render import (
    render_prefix, render_prefix_result,
)
from qbot_rpg.core.player_attributes import calc_final_attr


# ------------------------- P1-1 条件加成接线 -------------------------
def _cond_pack(conditional: list) -> dict:
    return {
        "stats": {"str": {"name": "力量", "type": "combat", "base": 15, "growth": 1},
                  "int": {"name": "智力", "type": "combat", "base": 15, "growth": 1}},
        "conditional": {"conditional": conditional},
    }


def test_conditional_valid_pack_ok():
    """合法条件规则（str→int）可加载（接线后 loader 期红拦路径可用）。"""
    rep = check_pack(_cond_pack([
        {"id": "c1", "source": "str", "target": "int", "per_point": 1},
    ]), default_field_meta_table())
    assert rep.ok, rep.errors


def test_conditional_cycle_blocked():
    """A→B→A 环 → R-5 红拦（3b TC-05：加载期拒绝）。"""
    rep = check_pack(_cond_pack([
        {"id": "c1", "source": "str", "target": "int", "per_point": 1},
        {"id": "c2", "source": "int", "target": "str", "per_point": 1},
    ]), default_field_meta_table())
    assert not rep.ok
    assert any(e.kind == "R-5" and e.detail.get("rule") == "conditional_cycle"
               for e in rep.errors), rep.errors


def test_conditional_self_cycle_blocked():
    """X→X 自环 → R-5（3b TC-05 自环同样拦截）。"""
    rep = check_pack(_cond_pack([
        {"id": "c1", "source": "str", "target": "str", "per_point": 1},
    ]), default_field_meta_table())
    assert not rep.ok
    assert any(e.kind == "R-5" and e.detail.get("rule") == "conditional_cycle"
               for e in rep.errors)


def test_conditional_unknown_stat_blocked():
    """source/target 引用未注册属性键 → R-4（3b ADR-05）。"""
    rep = check_pack(_cond_pack([
        {"id": "c1", "source": "ghost", "target": "int", "per_point": 1},
    ]), default_field_meta_table())
    assert not rep.ok
    assert any(e.kind == "R-4" for e in rep.errors), rep.errors


# ------------------------- P1-2 前缀自定义 format 称号不泄漏 -------------------------
def test_custom_format_no_decor_hide():
    """自定义 format 无装饰符 + hide_when_empty：[称号] 不得泄漏。"""
    fmt = "【[群名]】[玩家名] [称号]"
    out = render_prefix(35, "阿伟", None, format_template=fmt, hide_when_empty=True,
                        extra={"群名": "测试群"})
    assert "[称号]" not in out, f"称号占位符泄漏：{out!r}"
    assert "【测试群】阿伟" in out


def test_custom_format_no_decor_empty_text():
    """自定义 format 无装饰符 + empty_title_text：占位符替换不泄漏。"""
    fmt = "[职业] Lv[等级].[玩家名] [称号]"
    out = render_prefix(35, "阿伟", None, format_template=fmt,
                        empty_title_text="-", extra={"职业": "剑士"})
    assert "[称号]" not in out, f"称号占位符泄漏：{out!r}"
    assert "剑士 Lv35.阿伟 -" in out


def test_default_three_states_unchanged():
    """默认格式三态回归（不得被 P1-2 修复破坏）。"""
    assert render_prefix(35, "阿伟", "斩龙者") == "Lv35.阿伟 -斩龙者-"
    assert render_prefix(35, "阿伟", None) == "Lv35.阿伟 - -"
    assert render_prefix(35, "阿伟", None, hide_when_empty=True) == "Lv35.阿伟"


# ------------------------- P1-3 前缀截断信号 -------------------------
def test_prefix_truncation_signal():
    res = render_prefix_result(35, "阿伟", "超长称号".ljust(60, "长"), prefix_max_len=20)
    assert res.truncated is True
    assert len(res.prefix) <= 20
    res2 = render_prefix_result(35, "阿伟", "短", prefix_max_len=20)
    assert res2.truncated is False
    assert res2.prefix == "Lv35.阿伟 -短-"


# ------------------------- P1-4 stats 负数黄提示 + calc 按 0 兜底 -------------------------
def test_stats_negative_base_is_warning_not_red():
    """stats.json base=-5 → 黄提示不红拦（3b §4.2/TC-17）。"""
    rep = check_pack({
        "stats": {"hp": {"name": "生命", "type": "resource", "base": -5, "growth": 1}},
    }, default_field_meta_table())
    assert rep.ok, f"负数 base 被红拦：{rep.errors}"
    assert any(w.kind in ("Y-1",) for w in rep.warnings), rep.warnings


def test_calc_negative_base_clamped_to_zero():
    """calc_final_attr 负 base/growth → 按 0 兜底（运行期不放大）。"""
    v = calc_final_attr("str", base=-5, growth=0, level=1, free_points=0,
                        flat_bonus=0, pct_bonus=0, temp_flat=0, temp_pct=0)
    assert v == 0
    v2 = calc_final_attr("str", base=10, growth=-2, level=5, free_points=0,
                         flat_bonus=0, pct_bonus=0, temp_flat=0, temp_pct=0)
    assert v2 == 10  # growth 按 0 → 白值=10
