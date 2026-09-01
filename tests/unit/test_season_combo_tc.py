"""M13 6c 季节+组合 TC 映射单测（tests/unit/test_season_combo_tc.py · M13 批11 路11C）。

覆盖细化_6c：
  - TC-09~13 季节组：season 判定/换季检测/待结算/置灰/兜底/on_season_change 事件
  - TC-14~16 组合表：combo_table 触发判定/结算
  - TC-17~20 校验：resource_axis_validator V1~V4 + build_pack 分派

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle_season import (
    detect_season_change,
    effective_season,
    filter_skills,
    settle_season_change,
    skill_available,
)
from qbot_rpg.core.combo_settle import reachable_combos, settle_combo
from qbot_rpg.core.combo_table import ComboRow
from qbot_rpg.core.season_events import (
    ON_SEASON_CHANGE,
    SEASON_EVENTS,
    trigger_season_event,
)
from qbot_rpg.core.skill_season import (
    parse_season,
    skill_in_season,
    validate_skill_action,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _battle_state(season: str = "spring", pending: bool = False) -> Dict[str, Any]:
    return {"battle_season": {"season": season, "pending": pending}}


def _skill(**over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {"id": "s1", "name": "技能", "type": "active", "kind": "damage"}
    s.update(over)
    return s


# ---------------------------------------------------------------------------
# TC-09~13 季节组
# ---------------------------------------------------------------------------
def test_tc09_season_parse_and_default() -> None:
    """TC-09：四季解析 + 缺省通用。"""
    assert parse_season("spring") == "spring"
    assert parse_season("SUMMER") != "summer"  # 大小写变体回落通用（SE1 防御）
    assert parse_season(None) == "general"  # 缺省通用（SEASON_ANY）
    assert parse_season("bogus") == "general"  # 未知值回落通用


def test_tc09_skill_in_season() -> None:
    """TC-09：技能 season ∈ {当前季, 通用} → 可用。"""
    assert skill_in_season(_skill(season="spring"), "spring") is True
    assert skill_in_season(_skill(), "summer") is True  # 缺省通用
    assert skill_in_season(_skill(season="winter"), "summer") is False


def test_tc10_validate_skill_action_season_mismatch() -> None:
    """TC-10：非当季技能行动 → 被拒不耗回合（season_mismatch）。"""
    r = validate_skill_action({"season": "winter"}, "summer")
    assert r["ok"] is False
    assert r.get("code") == "season_mismatch" or r.get("reason") == "season_mismatch"


def test_tc10_validate_skill_action_ok() -> None:
    """TC-10：当季/通用技能 → 放行。"""
    r = validate_skill_action({"season": "summer"}, "summer")
    assert r["ok"] is True
    r2 = validate_skill_action({}, "winter")
    assert r2["ok"] is True


def test_tc11_detect_season_change() -> None:
    """TC-11：换季检测——生效季 spring + 当前 summer → pending=True。"""
    state = _battle_state("spring")
    r = detect_season_change(state, "summer")
    assert r.get("changed") is True or r.get("pending") is True


def test_tc11_settle_season_change_switches() -> None:
    """TC-11：结算切换——pending 时切换生效季节。"""
    state = _battle_state("spring", pending=True)
    r = settle_season_change(state, "summer")
    assert r.get("switched") is True
    assert effective_season(state) == "summer"


def test_tc12_filter_skills_grayscale() -> None:
    """TC-12：非当季技能置灰（EFF-3）。"""
    skills = [_skill(id="s1", season="summer"), _skill(id="s2", season="winter"),
               _skill(id="s3")]
    out = filter_skills(skills, "summer")
    by_id = {s["skill_id"]: s for s in out}
    assert by_id["s1"].get("grayscale") is False  # 当季
    assert by_id["s2"].get("grayscale") is True   # 非当季置灰
    assert by_id["s3"].get("grayscale") is False  # 通用


def test_tc12_basic_guard_always_available() -> None:
    """TC-12：普攻/防御兜底全年可用。"""
    assert skill_available(_skill(type="basic"), "summer") is True
    assert skill_available({"type": "guard"}, "summer") is True


def test_tc13_on_season_change_event() -> None:
    """TC-13：on_season_change 事件触发 + 枚举登记。"""
    assert ON_SEASON_CHANGE in SEASON_EVENTS
    state: Dict[str, Any] = {}
    r = trigger_season_event(state, "spring")
    assert r["triggered"] is True
    # 同季幂等
    r2 = trigger_season_event(state, "spring")
    assert r2["triggered"] is False


# ---------------------------------------------------------------------------
# TC-14~16 组合表
# ---------------------------------------------------------------------------
def _combo_row(**over: Any) -> ComboRow:
    raw: Dict[str, Any] = {
        "combo": ["fire", "fire", "water"],
        "name": "蒸汽冲击",
        "kind": "damage",
        "power": 200,
        "element": "fire",
        "hits": 2,
        "effects": [{"type": "damage", "power": 100}],
    }
    raw.update(over)
    return ComboRow(raw)


def test_tc14_combo_table_schema() -> None:
    """TC-14：组合行 7 字段解析。"""
    row = _combo_row()
    assert row.name == "蒸汽冲击"
    assert row.kind == "damage"
    assert row.power == 200
    assert row.element == "fire"
    assert row.hits == 2
    assert len(row.effects) == 1


def test_tc14_multiset_match() -> None:
    """TC-14：多重集匹配（D-02）。"""
    row = _combo_row()
    assert row.matches({"fire": 3, "water": 2, "wind": 0}) is True
    assert row.matches({"fire": 1, "water": 1, "wind": 0}) is False


def test_tc15_settle_combo_ok() -> None:
    """TC-15：组合结算（双耗 MP+能量）。"""
    paid: list = []

    def mp_check(ctx: Any, cost: int) -> bool:
        return True

    def mp_pay(ctx: Any, cost: int) -> None:
        paid.append(cost)

    def energy_check(ctx: Any, axis: str, cost: Dict[str, int]) -> bool:
        return True

    def energy_pay(ctx: Any, axis: str, cost: Dict[str, int]) -> None:
        paid.append((axis, cost))

    r = settle_combo({}, _combo_row(), mp_cost=16,
                     mp_check=mp_check, mp_pay=mp_pay,
                     energy_check=energy_check, energy_pay=energy_pay)
    assert r["ok"] is True
    assert r["energy_cost"] == {"fire": 2, "water": 1}
    assert len(paid) == 2


def test_tc16_reachable_combos() -> None:
    """TC-16：可达性 RE——能量池满足 → 可达行非空。"""
    ctx = {
        "stats": {"element_energy": {
            "name": "元素能量", "type": "element_energy", "base": 0,
            "max_per_pool": 3, "pools": ["fire", "water", "wind"]}},
        "resource_state": {"player": {"element_energy": {"fire": 3, "water": 2, "wind": 0}}},
    }
    skill = {"id": "steam", "name": "蒸汽", "combo_table": [_combo_row().raw]}
    out = reachable_combos(ctx, skill, "element_energy")
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# TC-17~20 校验
# ---------------------------------------------------------------------------
def test_tc17_axis_type_invalid_red() -> None:
    """TC-17：资源轴 type 非法 → V1 红拦。"""
    from qbot_rpg.content.resource_axis_validator import validate_resource_axes

    class R:
        def __init__(self) -> None:
            self.errors: list = []
            self.warnings: list = []

        def _err(self, m: str, f: str, k: str, **d: Any) -> None:
            self.errors.append(d)

        def _warn(self, m: str, f: str, k: str, **d: Any) -> None:
            self.warnings.append(d)

    r = R()
    validate_resource_axes({"stats": {"rage": {"type": "bogus"}}}, r)
    assert any(e.get("rule") == "axis_type_invalid" for e in r.errors)


def test_tc18_pooled_missing_fields_red() -> None:
    """TC-18：子池型缺 pools/max_per_pool → V1 红拦。"""
    from qbot_rpg.content.resource_axis_validator import validate_resource_axes

    class R:
        def __init__(self) -> None:
            self.errors: list = []
            self.warnings: list = []

        def _err(self, m: str, f: str, k: str, **d: Any) -> None:
            self.errors.append(d)

        def _warn(self, m: str, f: str, k: str, **d: Any) -> None:
            self.warnings.append(d)

    r = R()
    validate_resource_axes(
        {"stats": {"ee": {"type": "element_energy"}}}, r)
    rules = {e.get("rule") for e in r.errors}
    assert "pooled_missing_pools" in rules
    assert "pooled_missing_max_per_pool" in rules


def test_tc19_reset_enum_red() -> None:
    """TC-19：reset 枚举外值 → V3 红拦。"""
    from qbot_rpg.content.resource_axis_validator import validate_resource_axes

    class R:
        def __init__(self) -> None:
            self.errors: list = []
            self.warnings: list = []

        def _err(self, m: str, f: str, k: str, **d: Any) -> None:
            self.errors.append(d)

        def _warn(self, m: str, f: str, k: str, **d: Any) -> None:
            self.warnings.append(d)

    r = R()
    validate_resource_axes(
        {"stats": {"rage": {"type": "rage", "reset": "bogus"}}}, r)
    assert any(e.get("rule") == "reset_enum_invalid" for e in r.errors)


def test_tc20_build_pack_zero_red() -> None:
    """TC-20：build_pack test_demo 零红拦（stats 含两型注册段）。"""
    from pathlib import Path  # noqa: PLC0415

    from qbot_rpg.content.loader import build_pack  # noqa: PLC0415

    pack, _ = build_pack(Path("content/test_demo"))
    assert pack.report.ok, f"test_demo 应零红拦：{pack.report.errors}"
