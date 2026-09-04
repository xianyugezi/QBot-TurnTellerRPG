"""M12.5 属性动态化（2026-09-04）：stats.json 删键后老档案残留键不显示。

需求 3：老玩家档案里已存的属性保留（数据不丢），但展示层同步隐藏——
stats.json 是属性注册表唯一源，attrs 残留键（base/bonus 里已删属性）不进面板。
"""
from __future__ import annotations

from qbot_rpg.commands.basic_commands import _stat_order
from qbot_rpg.data.player import PlayerAttributes

_STATS = {
    "hp": {"name": "生命", "type": "resource", "base": 100},
    "str": {"name": "力量", "type": "combat", "base": 10},
}


def _ctx_with_attrs(attrs: PlayerAttributes) -> dict:
    return {
        "stats": {k: dict(v) for k, v in _STATS.items()},
        "settings": {"default_job_id": "warrior", "default_map": "新手村"},
        "attributes": attrs,
        "player": {"level": 1, "hp": 100, "mp": 0},
    }


def test_stat_order_hides_legacy_keys_when_stats_declared() -> None:
    """stats.json 只剩 hp/str 时，attrs 残留 mp/con/int 等不进展示顺序。"""
    attrs = PlayerAttributes(
        base={"hp": 100.0, "mp": 30.0, "str": 12.0, "con": 10.0, "int": 8.0},
    )
    order = _stat_order(_ctx_with_attrs(attrs), attrs)
    assert order == ["hp", "str"], f"应只显示 stats 声明键：{order}"
    assert "mp" not in order and "con" not in order and "int" not in order


def test_stat_order_fallback_union_when_no_stats() -> None:
    """无 stats（裸 ctx）→ 回落 attrs 并集（旧行为兜底）。"""
    attrs = PlayerAttributes(base={"hp": 100.0, "vigor": 5.0})
    order = _stat_order({"stats": None}, attrs)
    assert "hp" in order and "vigor" in order
