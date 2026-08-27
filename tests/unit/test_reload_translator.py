"""ReloadResult 人话翻译补测（M6 批3·路A · D3 WIR-09/10）——TC-WIR-07 四模板 + 禁词扫描。

依据：细化_M6_热重载接线.md（D3）§1.4 TPL-15~18 模板表 + TC-WIR-07（成功/失败回退/
连续失败暂停/无变更四路径 + 禁词）+ 【规则】L170 红线词。
注：本文件为路A 迭代上限截断后由主 agent 补建（实现已落盘，测试补齐）。
"""

from __future__ import annotations

from qbot_rpg.commands.reload_result import (
    ALL_RELOAD_TPL_TEXT,
    FORBIDDEN_WORDS,
    TPL_15_SUCCESS,
    TPL_16_ROLLBACK,
    TPL_17_PAUSED,
    TPL_18_NO_CHANGE,
    first_error_reason,
    reload_success_summary,
    render_reload_result,
)
from qbot_rpg.content.hot_reload import ReloadResult
from qbot_rpg.content.models import PackError


def _result(**over):
    """ReloadResult 真实构造（按需覆盖字段；no_change 为轮询无变更标记）。"""
    base = {
        "pack_id": "legal", "ok": False, "changed_modules": (),
        "warnings": (), "errors": (), "restored": False, "paused": False,
        "generation": 1, "no_change": False,
    }
    base.update(over)
    return ReloadResult(**base)


def _error(module="items", field="items.json", kind="unknown_field", detail=None):
    return PackError(module=module, field=field, kind=kind, detail=detail or {})


def test_tpl_15_success_path():
    """成功 → TPL-15：`✅ 已重载【{pack}】：{N} 个模块变更生效`（N=len(changed_modules)）。"""
    r = _result(ok=True, changed_modules=("items", "effects"))
    out = render_reload_result(r)
    assert out == TPL_15_SUCCESS.format(pack="legal", N=2)
    assert "✅ 已重载【legal】：2 个模块变更生效" in out
    # TPL_15_HEAD + summary 拼接等价
    assert TPL_15_SUCCESS.format(pack="legal", N=2) == \
        "✅ 已重载【legal】：" + reload_success_summary(r)


def test_tpl_16_rollback_path():
    """失败回退 → TPL-16：原因 = 首个红拦人话（模块/字段/kind/细节拼接）。"""
    r = _result(errors=(_error(detail={"reason": "bad_ref"}),), restored=True)
    out = render_reload_result(r)
    assert out == TPL_16_ROLLBACK.format(原因=first_error_reason(r.errors))
    assert "❌ 重载失败，已回退旧配置：" in out
    assert "items.json unknown_field" in out
    assert "请修正配置后保存，或手动 /重载 重试" in out


def test_tpl_17_paused_path():
    """连续失败暂停 → TPL-17（N=consecutive_failures）。"""
    r = _result(paused=True, errors=(_error(),))
    out = render_reload_result(r, consecutive_failures=3)
    assert out == TPL_17_PAUSED.format(N=3)
    assert "❌ 连续 3 次重载失败，已暂停自动检测" in out


def test_tpl_18_no_change_path():
    """无变更 → TPL-18：`✅ 内容包无变更，无需重载`。"""
    r = _result(no_change=True)
    assert render_reload_result(r) == TPL_18_NO_CHANGE


def test_render_priority_paused_over_restored():
    """判定优先级：paused 先于其余；no_change 先于 ok（restored 仅 ok=False 时生效，见 test_tpl_16）。"""
    r = _result(paused=True, restored=True, errors=(_error(),))
    assert render_reload_result(r).startswith("❌ 连续")
    # no_change 先于 ok（轮询无变更优先，不误报成功）
    r3 = _result(ok=True, no_change=True, changed_modules=("x",))
    assert render_reload_result(r3) == TPL_18_NO_CHANGE
    # restored（ok=False）先于 no_change（D3 §1.4 顺序：paused > restored > no_change > ok）
    r4 = _result(ok=False, restored=True, no_change=True, errors=(_error(),))
    assert render_reload_result(r4).startswith("❌ 重载失败")


def test_tpl_forbidden_words_scan():
    """四模板禁词扫描（TC-WIR-07：【规则】L170 红线词：必须/强制/上限/封顶/拒绝）。"""
    for tpl in ALL_RELOAD_TPL_TEXT:
        for w in FORBIDDEN_WORDS:
            assert w not in tpl, f"模板命中禁词 {w}：{tpl}"


def test_first_error_reason_structured_and_fallback():
    """首个红拦人话结构化 + 无红拦兜底。"""
    assert "items.json unknown_field" in first_error_reason((_error(),))
    r = first_error_reason((_error(detail={"k1": "v1", "k2": "v2", "k3": "v3", "k4": "v4"}),))
    assert "k1=v1；k2=v2；k3=v3" in r          # detail 前 3 项拼接（含中文分号）
    assert "k4=v4" not in r                    # 超 3 项截断
    assert "配置校验未通过" in first_error_reason(())
