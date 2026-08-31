"""M10 钓鱼·批4·路4A：codex fish 分册 + 正式入册 + 渲染单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_codex.py
创建时间：2026-08-31
作者：Hermes 主 agent（路4A 子 agent 撞迭代上限，实现落盘测试缺失，主 agent 补齐）

覆盖：细化_2c1a §四（TC-15/16/17）+ 细化_2c1c §二（R-05/R-06）。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.fishing_codex import (
    CODEX_CATEGORY_FISH,
    CODEX_META_KEY,
    CROWN_PRIORITY,
    KING_VICTORY_COUNT_KEY,
    fish_codex_update,
    fish_meta,
    render_fish_entry_line,
)


def _ctx(**kw: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"codex_state": {}}
    ctx.update(kw)
    return ctx


def _catch(size: float = 35.0, weight: float = 2.65, crown: str = "normal") -> Dict[str, object]:
    return {"size": size, "weight": weight, "crown": crown}


# ---------------------------------------------------------------------------
# 常量 / 分册
# ---------------------------------------------------------------------------
def test_constants() -> None:
    """分册名/七键/优先级链/综述键常量齐全。"""
    assert CODEX_CATEGORY_FISH == "fish"
    assert CODEX_META_KEY == "__meta__"
    assert KING_VICTORY_COUNT_KEY == "king_victory_count"
    assert CROWN_PRIORITY == ("big_gold", "gold", "big_silver", "silver", "normal")


def test_meta_initialized() -> None:
    """fish_meta 缺省建 __meta__ + king_victory_count=0。"""
    ctx = _ctx()
    meta = fish_meta(ctx)
    assert meta[KING_VICTORY_COUNT_KEY] == 0
    assert ctx["codex_state"]["fish"]["__meta__"][KING_VICTORY_COUNT_KEY] == 0


# ---------------------------------------------------------------------------
# 入册七键（G-01~G-07）
# ---------------------------------------------------------------------------
def test_first_catch_creates_entry_and_lights() -> None:
    """首获：建条目 + 点亮（seen=true）+ caught_count=1。"""
    ctx = _ctx()
    r = fish_codex_update(ctx, "silver_carp", _catch())
    assert r["ok"] is True
    assert r["first_seen"] is True
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["seen"] is True
    assert entry["caught_count"] == 1
    assert entry["best_crown"] == "normal"


def test_caught_count_increments() -> None:
    """重复捕获 caught_count 每次 +1（TC-15 序贯）。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch())
    fish_codex_update(ctx, "silver_carp", _catch())
    r = fish_codex_update(ctx, "silver_carp", _catch())
    assert r["caught_count"] == 3
    assert r["first_seen"] is False


def test_best_crown_priority_chain() -> None:
    """best_crown 优先级链（TC-15）：普通→金冠→大金冠→银冠 依次升级。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(crown="normal"))
    fish_codex_update(ctx, "silver_carp", _catch(crown="gold"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "gold"
    fish_codex_update(ctx, "silver_carp", _catch(crown="big_gold"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "big_gold"
    # 低档不降级
    fish_codex_update(ctx, "silver_carp", _catch(crown="silver"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "big_gold"


def test_reverse_crown_separate_count() -> None:
    """逆金冠单独计数 + 刷新 min（TC-16）：reverse_crown_count+1、min 取小、
    best_crown 不计逆金冠。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(size=35.0, weight=2.65, crown="normal"))
    fish_codex_update(ctx, "silver_carp", _catch(size=11.0, weight=0.5, crown="reverse"))
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["reverse_crown_count"] == 1
    assert entry["min_size"] == 11.0
    assert entry["min_weight"] == 0.5
    assert entry["best_crown"] == "normal"  # 逆金冠不入链


def test_best_min_extremes() -> None:
    """best/min 极值：先小后大 → best 取大 min 取小。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(size=30.0, weight=2.0))
    fish_codex_update(ctx, "silver_carp", _catch(size=45.0, weight=4.0))
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["best_size"] == 45.0
    assert entry["best_weight"] == 4.0
    assert entry["min_size"] == 30.0
    assert entry["min_weight"] == 2.0


def test_no_overwrite_preserves_extra_keys() -> None:
    """防覆盖：存量展示键（lore_unlocked/killed）保留。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(crown="gold"))
    ctx["codex_state"]["fish"]["silver_carp"]["lore_unlocked"] = True
    ctx["codex_state"]["fish"]["silver_carp"]["killed"] = True
    fish_codex_update(ctx, "silver_carp", _catch(crown="silver"))
    entry = ctx["codex_state"]["fish"]["silver_carp"]
    assert entry["lore_unlocked"] is True
    assert entry["killed"] is True
    assert entry["caught_count"] == 2


def test_empty_species_rejected() -> None:
    """空 species_id → 拒绝不建条目。"""
    ctx = _ctx()
    r = fish_codex_update(ctx, "", _catch())
    assert r["ok"] is False
    assert "fish" not in ctx["codex_state"]


def test_invalid_catch_rejected() -> None:
    """非法 catch → 拒绝。"""
    ctx = _ctx()
    r = fish_codex_update(ctx, "silver_carp", "bogus")  # type: ignore[arg-type]
    assert r["ok"] is False


def test_invalid_crown_falls_normal() -> None:
    """非法 crown → 保守 normal。"""
    ctx = _ctx()
    fish_codex_update(ctx, "silver_carp", _catch(crown="bogus"))
    assert ctx["codex_state"]["fish"]["silver_carp"]["best_crown"] == "normal"


# ---------------------------------------------------------------------------
# 渲染（R-06：展示格式 + 不写公式）
# ---------------------------------------------------------------------------
def test_render_entry_line_format() -> None:
    """展示格式 `{name} Lv{lv} · 最大 {best_size}cm/{best_weight}kg · {best_crown} · 逆金冠×N`。"""
    line = render_fish_entry_line("银鳞鲤", 45.2, 3.8, "gold", 1, lv=3)
    assert "银鳞鲤" in line
    assert "45.2" in line
    assert "3.8" in line
    assert "金冠" in line
    assert "逆金冠×1" in line
    assert "Lv3" in line


def test_render_unknown_species() -> None:
    """未捕获鱼种渲染 → 空/???（不泄露名称）。"""
    line = render_fish_entry_line("???", 0.0, 0.0, "", 0)
    assert line == "" or "???" in line


def test_render_no_formula() -> None:
    """渲染不写判定公式/阈值（R-06：检索 85/95/5 类阈值词为空）。"""
    line = render_fish_entry_line("银鳞鲤", 45.2, 3.8, "gold", 0)
    for token in ("85", "95", "5%", "阈值"):
        assert token not in line, f"渲染泄露判定公式: {token}"
