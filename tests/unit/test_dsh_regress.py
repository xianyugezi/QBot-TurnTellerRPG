"""dsh 审查批承诺回归（细化_3e2#TC-09 防空转 / 细化_3e#TC-08/29 互斥与 formula 安全）。

2026-08-18 content 层审查（审查_M0_content_20260818.md）：
- P0-1 防空转失效（坏包每 3s 空转、paused 形同虚设）→ 本文件 TC-09 断言
- P0-2 部位互斥误判（双部位互斥被误 R-5）→ 本文件断言双部位放行 / 三环拦截
- P1-1 formula 黑名单绕过（${} 插值）与块注释误伤 → 本文件断言插值拦截 / 注释不拦
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.hot_reload import HotReloadWatcher
from qbot_rpg.content.validator import check_formula, check_pack


# ------------------------- P0-2 部位互斥 -------------------------
def _equipment_report(entries):
    return check_pack({"equipment": entries}, default_field_meta_table())


def test_two_slot_mutex_not_a_cycle():
    """双部位互斥（武器↔盾合法语义）不误判 R-5。"""
    entries = [
        {"id": "sword", "name": "剑", "slot": "s1", "excludes": ["s2"]},
        {"id": "shield", "name": "盾", "slot": "s2", "excludes": ["s1"]},
    ]
    rep = _equipment_report(entries)
    assert rep.ok, f"双部位互斥被误判：{rep.errors}"


def test_three_slot_cycle_blocked():
    """三部位互斥成环 → R-5 红拦（细化_3e L167 人话示例）。"""
    entries = [
        {"id": "a", "name": "部位A", "slot": "s1", "excludes": ["s2"]},
        {"id": "b", "name": "部位B", "slot": "s2", "excludes": ["s3"]},
        {"id": "c", "name": "部位C", "slot": "s3", "excludes": ["s1"]},
    ]
    rep = _equipment_report(entries)
    assert not rep.ok
    assert any(e.kind == "R-5" for e in rep.errors)


# ------------------------- P1-1 formula 安全例外 -------------------------
def test_formula_template_interp_blocked():
    """模板串 ${eval(...)} 插值不得绕过黑名单（P1-1 修复）。"""
    hit = check_formula("`x = ${eval('process.exit()')}`")
    assert hit is not None, "${eval} 插值绕过黑名单"


def test_formula_block_comment_not_blocked():
    """块注释内黑名单词不误报（`/* process */` 合法公式放行）。"""
    hit = check_formula("a = b + 1 /* process */")
    assert hit is None, f"块注释误报：{hit}"


def test_formula_line_comment_not_blocked():
    """`//` 行注释内黑名单词不误报。"""
    assert check_formula("a = 1 // eval is not called here") is None


def test_formula_plain_eval_blocked():
    assert check_formula("eval('x')") is not None
    assert check_formula("new Function('return 1')") is not None


def test_formula_new_expr_blocked():
    assert check_formula("new Date()") is not None  # new 表达式一律拦截


# ------------------------- P0-1 防空转 -------------------------
def _write_pack(tmp: Path, good: bool) -> None:
    manifest = {"name": "spin", "version": "1.0.0", "schema_version": 1,
                "author": "t", "modules": ["effects"]}
    (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if good:
        effects = [
            {"id": "heal", "type": "heal", "name": "回复", "power": 50},
        ]
    else:
        # 缺必填 id → R-5 红拦（确保好/坏包真能区分；power 超范围仅黄提示不红拦）
        effects = [{"type": "heal", "name": "坏", "power": 50}]
    (tmp / "effects.json").write_text(json.dumps(effects, ensure_ascii=False), encoding="utf-8")


async def _reload_direct(w, source, detected):
    import asyncio
    return await asyncio.to_thread(w._reload_sync, source, detected)


@pytest.mark.asyncio
async def test_antispin_after_first_failure(tmp_path):
    """防空转：坏包一次失败后 _detect_changes 不再重复触发同一签名（BLK-5/TC-09）。"""
    tmp = tmp_path / "spin"
    tmp.mkdir()
    _write_pack(tmp, good=True)
    w = HotReloadWatcher(tmp)
    r0 = await _reload_direct(w, "poll", ("effects",))
    assert r0.ok  # 好包建立基线

    # 写坏包 → 失败 → _last_attempt 应记录 effects 签名
    _write_pack(tmp, good=False)
    r_bad = await _reload_direct(w, "poll", ("effects",))
    assert not r_bad.ok and r_bad.restored
    assert "effects" in w._last_attempt, "失败路径未写防空转签名"

    # 同签名：下一轮检测不得再触发（防空转核心）
    events = await asyncio.to_thread(w._detect_changes)
    assert "effects" not in events, f"坏包空转重试：{events}"


@pytest.mark.asyncio
async def test_three_consecutive_failures_pauses(tmp_path):
    """连续 3 次失败 → 自动轮询暂停（BLK-5/paused），手动 reload 仍可用。"""
    tmp = tmp_path / "pause"
    tmp.mkdir()
    _write_pack(tmp, good=True)
    w = HotReloadWatcher(tmp)
    await _reload_direct(w, "poll", ("effects",))
    _write_pack(tmp, good=False)
    for _ in range(3):
        await _reload_direct(w, "poll", ("effects",))
    assert w.consecutive_failures >= 3
    assert w.paused is True, "连续 3 次失败后未暂停自动轮询"
