"""成就校验器单测（tests/unit/test_achievements_models.py · M11 批1 路1B）。

覆盖细化_4c 契约 TC-18~22 + ACH-01~13 规则正反例，对齐 docs/m11_成就摸底.md §四 承载表。
"""

from qbot_rpg.content.achievements_models import (
    validate_achievements,
)


# ---------------------------------------------------------------------------
# 测试收集器（三形态之一：dict）
# ---------------------------------------------------------------------------
def _report() -> dict:
    return {"errors": [], "warnings": []}


def _errs(report: dict) -> list:
    return report["errors"]


def _warns(report: dict) -> list:
    return report["warnings"]


def _modules(achievements: list, **extra) -> dict:
    """校验器 modules（achievements 键 + 引用靶模块）。"""
    m = {
        "achievements": achievements,
        "items": [{"id": "铁矿", "type": "material"}, {"id": "世界之书", "type": "unique"}],
        "proficiency": [
            {"id": "alchemy", "titles": [
                {"id": "contest_champion"}, {"id": "achievement_100_craft"}]},
        ],
        "settings": {"currencies": [{"id": "coins"}, {"id": "diamond"}]},
    }
    m.update(extra)
    return m


def _ok_ach(**over) -> dict:
    """一条合法成就（D-09 默认兜底）。"""
    a = {
        "id": "ach_test",
        "name": "测试成就",
        "conditions": [{"var": "level", "op": "ge", "value": 5}],
    }
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# ⑤ schema 与校验器（TC-19~22）
# ---------------------------------------------------------------------------
def test_tc19_defaults():
    """最小配置 {id,name,conditions} 无其它字段 → 默认值兜底成功加载。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach()]), rep)
    assert not _errs(rep)


def test_tc19_name_too_long_warn():
    """name 超 20 字 → 黄提示。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(name="这" * 21)]), rep)
    assert not _errs(rep)
    assert any("name" in str(w.get("field", "")) for w in _warns(rep))


def test_tc20_alias_singleton():
    """condition 单对象 ≡ conditions 数组；同给异值 → 黄提示。"""
    # 单对象（condition 别名）
    rep1 = _report()
    cond_single = {"var": "level", "op": "ge", "value": 5}
    validate_achievements(_modules([_ok_ach(condition=cond_single)]), rep1)
    assert not _errs(rep1)
    # 数组
    rep2 = _report()
    cond_arr = [{"var": "level", "op": "ge", "value": 5}]
    validate_achievements(_modules([_ok_ach(conditions=cond_arr)]), rep2)
    assert not _errs(rep2)
    # 同给异值 → 黄提示
    rep3 = _report()
    validate_achievements(_modules([_ok_ach(
        condition={"var": "level", "op": "ge", "value": 5},
        conditions=[{"var": "level", "op": "ge", "value": 10}],
    )]), rep3)
    assert not _errs(rep3)
    assert any("alias" in str(w.get("rule", "")) for w in _warns(rep3))


def test_tc21_trigger_hard_block():
    """trigger:event（非 check）→ 硬拦结构错误。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(trigger="event")]), rep)
    assert any("trigger" in str(e.get("rule", "")) for e in _errs(rep))


def test_tc22_inline_vs_structured():
    """内联串 ≡ 结构化数组（D-05）：两种写法校验都放行。"""
    rep1 = _report()
    validate_achievements(_modules([_ok_ach(reward="exp=500,coins=1000")]), rep1)
    assert not _errs(rep1)
    rep2 = _report()
    validate_achievements(_modules([_ok_ach(reward=[{"exp": 500}, {"coins": 1000}])]), rep2)
    assert not _errs(rep2)


# ---------------------------------------------------------------------------
# ACH 规则正反例（TC-09 t_fake 硬拦 + 其它）
# ---------------------------------------------------------------------------
def test_tc09_title_ref_missing_hard_block():
    """title 引用未注册（t_fake）→ 硬拦。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(reward=[{"title": "t_fake"}])]), rep)
    assert any("title" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_conditions_empty_warn():
    """conditions 为空 = 接取即达成（黄提示不拦）。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(conditions=[])]), rep)
    assert not _errs(rep)
    assert any("empty" in str(w.get("rule", "")) for w in _warns(rep))


def test_ach_once_false_warn():
    """once=false 通胀提示（黄）。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(once=False)]), rep)
    assert not _errs(rep)
    assert any("inflation" in str(w.get("rule", "")) for w in _warns(rep))


def test_ach_hidden_no_reveal_warn():
    """hidden 缺 reveal_text → 黄提示。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(hidden={"mode": "locked"})]), rep)
    assert not _errs(rep)
    assert any("reveal" in str(w.get("rule", "")) for w in _warns(rep))


def test_ach_hidden_mode_invalid():
    """hidden.mode 非法 → 硬拦。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(hidden={"mode": "bogus"})]), rep)
    assert any("mode" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_negative_reward_hard_block():
    """reward 负数 → 硬拦（R-2）。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(reward=[{"coins": -5}])]), rep)
    assert any("negative" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_unknown_var_hard_block():
    """条件 var 未注册 → 硬拦。"""
    rep = _report()
    cond_bad_var = [{"var": "bogus_var", "op": "ge", "value": 1}]
    validate_achievements(_modules([_ok_ach(conditions=cond_bad_var)]), rep)
    assert any("var" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_unknown_op_hard_block():
    """条件 op 非法 → 硬拦。"""
    rep = _report()
    cond_bad_op = [{"var": "level", "op": "bogus", "value": 1}]
    validate_achievements(_modules([_ok_ach(conditions=cond_bad_op)]), rep)
    assert any("op" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_item_ref_missing_hard_block():
    """奖励物品未注册 → 硬拦。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(reward=[{"item": "不存在之物", "count": 1}])]), rep)
    assert any("item" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_event_not_registered_warn():
    """事件 var 未在预置注册表 → 黄提示。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(
        conditions=[{"var": "[事件:不存在的事件]", "op": "ge", "value": 1}])]), rep)
    assert not _errs(rep)
    assert any("event" in str(w.get("rule", "")) for w in _warns(rep))


def test_ach_duplicate_id_hard_block():
    """id 重复 → 硬拦（ACH-02）。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(), _ok_ach()]), rep)
    assert any("duplicate" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_currency_unregistered_hard_block():
    """货币键未注册（settings 无 gem）→ 硬拦。"""
    rep = _report()
    validate_achievements(_modules([_ok_ach(reward=[{"gem": 5}])]), rep)
    assert any("currency" in str(e.get("rule", "")) for e in _errs(rep))


def test_ach_valid_full_config_no_error():
    """完整合法配置（含隐藏成就 + 称号奖励）→ 零红。"""
    rep = _report()
    validate_achievements(_modules([
        _ok_ach(
            id="ach_full",
            desc="完整配置",
            conditions=[{"var": "codex", "op": "ge", "value": 50}],
            trigger="check",
            once=True,
            hidden={"mode": "locked", "reveal_text": "灯火即神鱼。",
                    "clue_ref": ["神鱼支线"]},
            reward=[{"coins": 100}, {"title": "achievement_100_craft"}],
        ),
    ]), rep)
    assert not _errs(rep)
