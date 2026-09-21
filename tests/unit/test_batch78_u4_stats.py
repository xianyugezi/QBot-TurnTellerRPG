"""批78 · U4 验收：伤害构成统计聚合 + dummy_log（定稿 §八）。

覆盖：
  - core/damage_stats 纯函数：聚合（来源/通道/会心/格挡/最大连段）、配置归一、环形缓冲；
  - 引擎接线：per-action schema（enabled 时补 name/penetrate）、stats_summary、
    formula.json stats_collector 配置装配；
  - 指令层接线：木桩战后 summary 注入 + dummy_log 写档（普通战斗/关闭/0=不写）；
  - `/木桩 记录` 展示（5 条/页 + TPL-08 页脚 / 空 / 非法页码）；
  - 模板表键存在。

铁律：不写内容包目录（纯内存 ctx/tmp）；期望值由定稿 §八与本次实现口径推导。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

from qbot_rpg.commands.battle_commands import (
    _battle_composition_summary,
    _dispatch_battle_end,
    _realtime_stats_line,
)
from qbot_rpg.commands.dummy_commands import cmd_dummy
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.damage_stats import (
    aggregate_per_action,
    append_dummy_log,
    build_dummy_log_record,
    load_stats_collector_cfg,
)
from qbot_rpg.core.templates import TABLE_TEMPLATES

# ---------------------------------------------------------------------------
# A · 纯函数：聚合 / 配置 / 环形缓冲
# ---------------------------------------------------------------------------

_REC_FIRE = {
    "source": "skill_fireball", "name": "火球术", "seg": 1, "ch_phys": 0, "ch_elem": 214,
    "crit": "high", "blocked": False, "pierce": 0.2, "weak_type": 1.3, "weak_elem": 1.3,
    "final": 310,
}
_REC_BASIC = {
    "source": "basic_attack", "name": "普攻", "seg": 2, "ch_phys": 120, "ch_elem": 0,
    "crit": "none", "blocked": True, "pierce": 0.0, "weak_type": 1.0, "weak_elem": 1.0,
    "final": 120,
}
_REC_DOT = {
    "source": "dot_burn", "name": "灼烧", "seg": 3, "ch_phys": 0, "ch_elem": 100,
    "crit": "low", "blocked": False, "pierce": 0.1, "weak_type": 1.0, "weak_elem": 1.3,
    "final": 100,
}


def test_aggregate_per_action_groups_by_source_and_channels() -> None:
    """定稿 §8.1 L332：同 source 求和 → 总伤害/占比排序；通道占比/最大连段/会心次数。"""
    s = aggregate_per_action([_REC_FIRE, _REC_BASIC, _REC_DOT])
    assert s["records"] == 3
    assert s["total"] == 530 and s["max_hit"] == 310
    assert s["seg_max"] == 3
    assert (s["ch_phys"], s["ch_elem"]) == (120, 314)
    assert (s["ch_phys_pct"], s["ch_elem_pct"]) == (28, 72)
    # 会心：high/low 计入，none 不计；格挡 1 次
    assert s["crits"] == 2
    assert s["blocks"] == 1
    assert s["items"] == [("火球术", 310), ("普攻", 120), ("灼烧", 100)]


def test_aggregate_per_action_empty_and_bad_records() -> None:
    empty = aggregate_per_action([])
    assert empty["records"] == 0 and empty["total"] == 0 and empty["items"] == []
    assert aggregate_per_action(None)["total"] == 0
    # 坏记录（非 Mapping / 负 final）不抛错，负值按 0
    s = aggregate_per_action([None, {"final": -5, "source": "x"}])  # type: ignore[list-item]
    assert s["records"] == 1 and s["total"] == 0 and s["max_hit"] == 0


def test_aggregate_crit_counts_only_positive_non_none() -> None:
    """会心次数=非 none 且 final>0（拒绝/未命中记录 final 0 + crit 缺省 low 不误计）。"""
    recs = [
        {**_REC_FIRE, "final": 0, "crit": "low"},      # 拒绝行动：不计
        {**_REC_FIRE, "final": 50, "crit": "none"},    # 未会心：不计
        {**_REC_FIRE, "final": 50, "crit": "mid"},     # 会心：计
    ]
    assert aggregate_per_action(recs)["crits"] == 1


def test_load_stats_collector_cfg_defaults_and_clamp() -> None:
    """定稿 §8.4 L366：缺省 enabled=true/size=5/realtime=false；size 夹取 0-20。"""
    assert load_stats_collector_cfg(None) == {
        "enabled": True, "dummy_log_size": 5, "dummy_realtime": False}
    assert load_stats_collector_cfg({}) == load_stats_collector_cfg(None)
    got = load_stats_collector_cfg({"stats_collector": {
        "enabled": False, "dummy_log_size": 999, "dummy_realtime": True}})
    assert got == {"enabled": False, "dummy_log_size": 20, "dummy_realtime": True}
    neg = load_stats_collector_cfg({"stats_collector": {"dummy_log_size": -3}})
    assert neg["dummy_log_size"] == 0
    # 坏类型逐键回落
    bad = load_stats_collector_cfg({"stats_collector": {"enabled": "yes", "dummy_log_size": "x"}})
    assert bad == load_stats_collector_cfg(None)


def test_append_dummy_log_ring_and_off() -> None:
    """定稿 §8.3 L354：最新在前、只留最近 N 条；size=0 关闭（不写）。"""
    ps: Dict[str, Any] = {}
    for i in range(4):
        append_dummy_log(ps, {"total": i}, 3)
    assert [r["total"] for r in ps["dummy_log"]] == [3, 2, 1]
    ps2: Dict[str, Any] = {}
    assert append_dummy_log(ps2, {"total": 1}, 0) == []
    assert "dummy_log" not in ps2


def test_build_dummy_log_record_fields() -> None:
    """定稿 §8.3 L357：时间/档位/回合数/总伤害/来源摘要/最大单段/会心/格挡。"""
    s = aggregate_per_action([_REC_FIRE, _REC_BASIC])
    rec = build_dummy_log_record(s, at="2026-09-24T00:00:00Z", dummy_id="dummy_light", turns=5)
    assert set(rec) >= {"at", "dummy_id", "turns", "total", "top", "max_hit", "crits", "blocks"}
    assert rec["total"] == 430 and rec["turns"] == 5 and rec["dummy_id"] == "dummy_light"
    assert rec["top"][0] == ["火球术", 310, 72]


# ---------------------------------------------------------------------------
# B · 引擎接线：per-action schema / 聚合 / 配置装配
# ---------------------------------------------------------------------------

def _record(eng: BattleEngine, name: str, rating: Dict[str, Any],
            damage: Dict[str, Any]) -> None:
    eng._record_action("player", name, "enemy", rating, damage, "actor_ready", name=name)


_R_FIRE = {"crit": "high", "blocked": False, "pierce": 0.2, "weak_type": 1.3, "weak_elem": 1.0}
_D_FIRE = {"ch_phys": 0, "ch_elem": 214, "final": 214}
_R_BASIC = {"crit": "none", "blocked": True, "pierce": 0.0, "weak_type": 1.0, "weak_elem": 1.0}
_D_BASIC = {"ch_phys": 120, "ch_elem": 0, "final": 120}


def test_engine_enabled_per_action_has_schema_keys() -> None:
    """enabled=true（缺省）：per_action 记录带 name（展示名）与 penetrate（§8.1 schema）。"""
    eng = BattleEngine()
    _record(eng, "火球术", _R_FIRE, _D_FIRE)
    rec = eng._snap["stats_collector"]["per_action"][0]
    assert rec["name"] == "火球术"
    assert "penetrate" in rec and rec["penetrate"] == 0.0


def test_engine_disabled_per_action_matches_legacy_field_set() -> None:
    """不启用零变化对拍：enabled=false → per_action 记录字段集 = 批77 基线 10 字段。"""
    eng = BattleEngine()
    eng._stats_cfg = {"enabled": False, "dummy_log_size": 0, "dummy_realtime": False}
    _record(eng, "火球术", _R_FIRE, _D_FIRE)
    rec = eng._snap["stats_collector"]["per_action"][0]
    assert set(rec) == {"source", "seg", "ch_phys", "ch_elem", "crit", "blocked",
                        "pierce", "weak_type", "weak_elem", "final"}


def test_engine_stats_summary_from_records() -> None:
    eng = BattleEngine()
    _record(eng, "火球术", _R_FIRE, _D_FIRE)
    _record(eng, "普攻", _R_BASIC, _D_BASIC)
    s = eng.stats_summary()
    assert s["total"] == 334 and s["max_hit"] == 214 and s["blocks"] == 1
    assert s["items"][0] == ("火球术", 214)


def test_engine_stats_cfg_assembled_from_registry() -> None:
    """formula.json `stats_collector` 段 → 引擎配置（唯一落点，可配不写死）。"""
    reg = SimpleNamespace(modules_raw={"formula": {"stats_collector": {
        "enabled": False, "dummy_log_size": 3, "dummy_realtime": True}}})
    eng = BattleEngine(registry=reg)
    assert eng.stats_collector_cfg() == {
        "enabled": False, "dummy_log_size": 3, "dummy_realtime": True}


# ---------------------------------------------------------------------------
# C · 指令层接线：战后 summary 注入 + dummy_log 写档
# ---------------------------------------------------------------------------

class _StubPipeline:
    def __init__(self) -> None:
        self.kwargs: Dict[str, Any] = {}
        self.calls = 0

    def send_end(self, *a: Any, **k: Any) -> List[str]:
        self.calls += 1
        self.kwargs = k
        return []


class _StubReport:
    ended = True
    status = "draw"
    action_seq = 7
    turn = 7
    outcomes: tuple = ()


class _StubEngine:
    """指令层 stub：只暴露接线层消费的接口（不跑真实战斗）。"""

    def __init__(self, cfg: Dict[str, Any], dummy: bool = True,
                 summary: Dict[str, Any] | None = None) -> None:
        self._cfg = cfg
        self._dummy = dummy
        self._summary = summary

    def stats_collector_cfg(self) -> Dict[str, Any]:
        return dict(self._cfg)

    def _is_dummy_enemy_def(self) -> bool:
        return self._dummy

    def stats_summary(self) -> Dict[str, Any]:
        if self._summary is not None:
            return self._summary
        return aggregate_per_action([_REC_FIRE, _REC_BASIC])


def _run_end(engine: _StubEngine, *, player: Any = None) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "registered": True,
        "player": player if player is not None else {"persistent_state": {}},
    }
    pipe = _StubPipeline()
    _dispatch_battle_end(engine, _StubReport(), pipe, ctx,
                         {"id": "dummy_light", "name": "训练木桩"},
                         "训练木桩", {"exp": 0, "gold": 0, "drops": ()})
    return {"ctx": ctx, "pipe": pipe}


_CFG_ON = {"enabled": True, "dummy_log_size": 5, "dummy_realtime": False}
_CFG_OFF = {"enabled": False, "dummy_log_size": 5, "dummy_realtime": False}


def test_dispatch_end_dummy_sets_summary_and_writes_log() -> None:
    """木桩战 enabled=true → send_end 收 summary（渲染 BREP-25）+ dummy_log 写档。"""
    out = _run_end(_StubEngine(_CFG_ON))
    assert out["pipe"].kwargs["summary"] is not None
    assert out["ctx"]["battle_summary"]["items"][0] == ("火球术", 310)
    log = out["ctx"]["player"]["persistent_state"]["dummy_log"]
    assert log[0]["dummy_id"] == "dummy_light" and log[0]["turns"] == 7


def test_dispatch_end_disabled_no_summary_no_log() -> None:
    """不启用零变化：enabled=false → 不注入 summary、不写 dummy_log。"""
    out = _run_end(_StubEngine(_CFG_OFF))
    assert out["pipe"].kwargs["summary"] is None
    assert "battle_summary" not in out["ctx"]
    assert "dummy_log" not in out["ctx"]["player"]["persistent_state"]


def test_dispatch_end_dummy_log_size_zero_no_log() -> None:
    """dummy_log_size=0（定稿 §8.4）= 关：仍出明细但不写档。"""
    out = _run_end(_StubEngine({"enabled": True, "dummy_log_size": 0,
                                "dummy_realtime": False}))
    assert out["pipe"].kwargs["summary"] is not None
    assert "dummy_log" not in out["ctx"]["player"]["persistent_state"]


def test_dispatch_end_normal_battle_no_summary() -> None:
    """定稿 §8.2 L350：普通战斗默认不展示明细（收集器仍在跑）→ summary=None。"""
    out = _run_end(_StubEngine(_CFG_ON, dummy=False))
    assert out["pipe"].kwargs["summary"] is None
    assert "battle_summary" not in out["ctx"]


def test_realtime_stats_line_and_composition_helper() -> None:
    eng = _StubEngine({"enabled": True, "dummy_log_size": 5, "dummy_realtime": True})
    line = _realtime_stats_line(eng, {})
    assert "总伤害 430" in line and "最大单段 310" in line
    assert _battle_composition_summary(eng, {}) is not None
    assert _battle_composition_summary(_StubEngine(_CFG_OFF), {}) is None
    # 无记录 → 不输出实时行
    empty = _StubEngine(_CFG_ON, summary=aggregate_per_action([]))
    assert _realtime_stats_line(empty, {}) == ""


# ---------------------------------------------------------------------------
# D · `/木桩 记录` 展示
# ---------------------------------------------------------------------------

def _log_ctx(n: int) -> Dict[str, Any]:
    log = [build_dummy_log_record(
        aggregate_per_action([_REC_FIRE, _REC_BASIC]),
        at=f"2026-09-24T0{i}:00:00Z", dummy_id=f"dummy_{i}", turns=i + 1)
        for i in range(n)]
    log.reverse()                                   # 最新在前
    return {
        "registered": True,
        "player": {"persistent_state": {"dummy_log": log}},
        "enemies": [{"id": "dummy_light", "name": "轻甲", "tier": "training",
                     "stats": {"hp": 3000, "con": 5}}],
        "templates": None,
    }


def test_dummy_log_command_renders_rows_and_footer() -> None:
    """`/木桩 记录`：6 条 → 第 1 页 5 条 + TPL-08 页脚（第 1/2 页）。"""
    out = cmd_dummy(parse_command("/木桩 记录"), _log_ctx(6))
    assert "【木桩记录】最近 6 次" in out
    assert "1. 2026-09-24T05:00:00Z｜dummy_5" in out
    assert "第 1/2 页" in out and "木桩 记录" in out
    assert out.count("｜来源：") == 5               # 本页 5 条
    page2 = cmd_dummy(parse_command("/木桩 记录 2"), _log_ctx(6))
    assert "第 2/2 页" in page2
    assert page2.count("｜来源：") == 1


def test_dummy_log_command_empty_and_invalid_page() -> None:
    empty = {"registered": True, "player": {"persistent_state": {}},
             "enemies": [{"id": "dummy_light", "name": "轻甲", "tier": "training",
                          "stats": {"hp": 1}}], "templates": None}
    assert "暂无木桩记录" in cmd_dummy(parse_command("/木桩 记录"), empty)
    bad = cmd_dummy(parse_command("/木桩 记录 0"), _log_ctx(2))
    assert "指令不正确" in bad


# ---------------------------------------------------------------------------
# E · 模板表键
# ---------------------------------------------------------------------------

def test_batch78_template_keys_present() -> None:
    for key in ("battle_stats_realtime", "dummy_log_header", "dummy_log_row",
                "dummy_log_empty"):
        assert key in TABLE_TEMPLATES, key
