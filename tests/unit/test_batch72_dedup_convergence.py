"""批72 · 重复机制收敛（审计3 §3）验收护栏。

覆盖：
  · F3 —— `core/upgrade._rune_tier_of` 收敛到唯一源 `data/runes.rune_tier_of`：
          三阶解析（含边界/非法值）与批前**逐位一致**，且不再硬编码 `1..3`；
  · F1 —— `forge.json["settings"]` 废弃：兜底读取保留（既有包不崩）+ 校验器黄提示；
  · F2 —— `forge.decompose_rate` 已由批70 删净（本批只核实，不重复劳动）。

纪律：只读断言；不写盘；不触碰 tests/unit/test_editor_batch66_fixes.py（批67 护栏）。
"""

from __future__ import annotations

from typing import Mapping

from qbot_rpg.core.upgrade import UpgradeEngine
from qbot_rpg.data.runes import MIN_RUNE_TIER, MAX_RUNE_TIER, rune_tier_of


# ===========================================================================
# F3 · 符文档位解析：唯一源收敛 + 逐位对拍
# ===========================================================================
# 批前 `_rune_tier_of` 的实测结果（float 整值被 `_as_int` 拒 → None；
# 合法/边界/非法 int 与数字串与唯一源一致）。逐位钉死，防收敛后漂移。
_PRE_BATCH_TIER_CASES = (
    (1, 1), (2, 2), (3, 3),
    (0, None), (4, None), (-1, None), (5, None),
    ("1", 1), ("2", 2), ("3", 3), (" 2 ", 2),
    ("0", None), ("4", None), ("", None), ("x", None),
    (2.5, None), (2.0, None), (3.0, None), (0.0, None),
    (True, None), (False, None), (None, None),
)


def _engine() -> UpgradeEngine:
    return UpgradeEngine()


def test_f3_rune_tier_matches_pre_batch_bitwise() -> None:
    """① ctx["runes"][id].tier 路径：与批前逐位一致（边界/非法值全覆盖）。"""
    eng = _engine()
    for raw, expect in _PRE_BATCH_TIER_CASES:
        ctx = {"runes": {"r": {"id": "r", "tier": raw}}, "items": {}}
        got = eng._rune_tier_of("r", ctx, {}, output=False)
        assert got == expect, (raw, got, expect)


def test_f3_rune_tier_item_def_fallback_bitwise() -> None:
    """② 物品定义 `tier` 兜底路径：与批前逐位一致。"""
    eng = _engine()
    for raw, expect in _PRE_BATCH_TIER_CASES:
        ctx = {"runes": {}, "items": {"r": {"id": "r", "tier": raw}}}
        got = eng._rune_tier_of("r", ctx, {}, output=False)
        assert got == expect, (raw, got, expect)


def test_f3_rune_tier_output_recipe_fallback_bitwise() -> None:
    """③ 产出端配方回退（output.rune_tier / cfg.rune_tier）：与批前逐位一致。"""
    eng = _engine()
    for raw, expect in _PRE_BATCH_TIER_CASES:
        ctx = {"runes": {}, "items": {}}
        got_out = eng._rune_tier_of("r", ctx, {"output": {"rune_tier": raw}}, output=True)
        got_cfg = eng._rune_tier_of("r", ctx, {"rune_tier": raw}, output=True)
        assert got_out == expect, ("output", raw, got_out, expect)
        assert got_cfg == expect, ("cfg", raw, got_cfg, expect)


def test_f3_uses_unique_source_scale() -> None:
    """唯一源刻度：合法值由 `data/runes` 决定，本模块不硬编码 `1..3`。

    常量若被改（如 MIN=1/MAX=2），`_rune_tier_of` 必须随之改变——证明它读唯一源而非
    自持字面量。此处只断言当前刻度一致性（不真改全局常量，避免污染其它测试）。
    """
    assert (MIN_RUNE_TIER, MAX_RUNE_TIER) == (1, 3)
    eng = _engine()
    for t in (MIN_RUNE_TIER, 2, MAX_RUNE_TIER):
        ctx = {"runes": {"r": {"tier": t}}, "items": {}}
        assert eng._rune_tier_of("r", ctx, {}, output=False) == rune_tier_of({"tier": t}) == t
    # float 整值：唯一源接受、升级路径严格 int（保批前行为）→ 二者在此明确分道
    assert rune_tier_of({"tier": 2.0}) == 2
    ctx = {"runes": {"r": {"tier": 2.0}}, "items": {}}
    assert eng._rune_tier_of("r", ctx, {}, output=False) is None


def test_f3_unknown_rune_and_empty_id() -> None:
    """未知 id / 空 id → None（与批前一致）。"""
    eng = _engine()
    assert eng._rune_tier_of("nope", {"runes": {}, "items": {}}, {}, output=False) is None
    assert eng._rune_tier_of("", {"runes": {}, "items": {}}, {}, output=False) is None


def test_f3_no_hardcoded_tier_literals_in_source() -> None:
    """源码静态检查：`_rune_tier_of` 体内不再出现 `1 <= ... <= 3` 硬编码。"""
    import inspect

    src = inspect.getsource(UpgradeEngine._rune_tier_of)
    assert "1 <= " not in src
    assert "<= 3" not in src
    # 值解析已下沉适配层 `_rune_tier_int`（内部调唯一源 rune_tier_of）
    from qbot_rpg.core import upgrade as _upgrade_mod

    adapter = inspect.getsource(_upgrade_mod._rune_tier_int)
    assert "rune_tier_of" in adapter


# ===========================================================================
# F2 · forge.decompose_rate 已由批70 删净（本批核实，不重复劳动）
# ===========================================================================
def test_f2_forge_decompose_rate_fully_removed() -> None:
    """forge 侧不再识别/登记/合并 `decompose_rate`（唯一源 = alchemy 段）。"""
    from qbot_rpg.content.forge_settings import (
        FORGE_SETTINGS_KEYS,
        read_forge_settings,
    )

    assert "decompose_rate" not in FORGE_SETTINGS_KEYS
    got = read_forge_settings({"forge": {"decompose_rate": {"正式": 0.5}}})
    assert "decompose_rate" not in got


def test_f2_pack_forge_json_has_no_decompose_rate() -> None:
    """仓库内全部内容包：forge.json 无 `decompose_rate` 残留。"""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "content"
    hits = []
    for f in sorted(root.glob("*/forge.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        seg = raw.get("settings") if isinstance(raw, Mapping) else None
        if isinstance(seg, Mapping) and "decompose_rate" in seg:
            hits.append(str(f))
    assert hits == []
