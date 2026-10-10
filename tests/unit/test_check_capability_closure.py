"""能力闭环门禁（scripts/check_capability_closure.py）单测 · 日研 Q3 最小形态。

覆盖：
  ① 现网（真实 EFFECT_AXIS_SPECS）通过：每轴有消费点声明，普通轴未被误判为「待接」；
  ② 空 `consumer` / 空 `consumer_note` → D-01 命中（守「无消费点的轴不得登记」）；
  ③ 新增哨兵轴 → D-02 红拦；接线后未从冻结点移除哨兵 → D-02 红拦（双向）；
  ④ `locate_consumers` 分类：tmp 目录中真实存在的模块符号 → 可定位；否则 → 仅契约命名。

脚本无 `__init__.py`（scripts 目录），按 test_check_m7_content 的 importlib 模式加载。
"""
from __future__ import annotations

import importlib.util
import pathlib
from typing import Dict, List

_CHECK = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "check_capability_closure.py"
_spec = importlib.util.spec_from_file_location("check_capability_closure_mod", _CHECK)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

REPO = pathlib.Path(__file__).resolve().parents[2]
CORE = REPO / "qbot_rpg" / "core"
SENTINEL = "（消费点待接）"


def _specs() -> List[Dict[str, object]]:
    from qbot_rpg.data.gear_stats import EFFECT_AXIS_SPECS

    return [dict(s) for s in EFFECT_AXIS_SPECS]


# --------------------------------------------------------------------------- ① 现网
def test_live_axes_pass_closure_gate() -> None:
    from qbot_rpg.data.gear_stats import EFFECT_AXIS_SPECS

    errors, pending, located, contract_only = _mod.run_check(
        list(EFFECT_AXIS_SPECS), CORE, SENTINEL)
    assert errors == [], errors
    assert pending == list(_mod.FROZEN_PENDING), pending
    assert len(located) + len(contract_only) == len(EFFECT_AXIS_SPECS)


def test_frozen_pending_is_known_axis() -> None:
    axes = {str(s["axis"]) for s in _specs()}
    for frozen in _mod.FROZEN_PENDING:
        assert frozen in axes, f"冻结点 {frozen} 已不在轴表中，请同步 FROZEN_PENDING"


# --------------------------------------------------------------------------- ② 缺消费点声明
def test_missing_consumer_is_flagged() -> None:
    specs = _specs()
    specs.append({"axis": "brand_new_axis_pct", "consumer": "", "consumer_note": ""})
    errors, _, _, _ = _mod.run_check(specs, CORE, SENTINEL)
    assert any("brand_new_axis_pct" in e and "consumer" in e for e in errors), errors


def test_missing_consumer_note_is_flagged() -> None:
    specs = _specs()
    specs.append({"axis": "note_less_axis", "consumer": "damage.crit_multiplier",
                  "consumer_note": " "})
    errors, _, _, _ = _mod.run_check(specs, CORE, SENTINEL)
    assert any("note_less_axis" in e and "consumer_note" in e for e in errors), errors


# --------------------------------------------------------------------------- ③ 哨兵轴冻结（双向）
def test_new_pending_axis_is_blocked() -> None:
    specs = _specs()
    specs.append({"axis": "silently_unwired_pct", "consumer": SENTINEL, "consumer_note": "待接"})
    errors, pending, _, _ = _mod.run_check(specs, CORE, SENTINEL)
    assert "silently_unwired_pct" in pending
    assert any("新增" in e and "silently_unwired_pct" in e for e in errors), errors


def test_wired_but_still_frozen_is_blocked() -> None:
    specs = [s for s in _specs() if str(s["axis"]) != _mod.FROZEN_PENDING[0]]
    errors, _, _, _ = _mod.run_check(specs, CORE, SENTINEL)
    assert any("已接线但未从 FROZEN_PENDING 移除" in e for e in errors), errors


# --------------------------------------------------------------------------- ④ 分类
def test_locate_consumers_splits_located_and_contract(tmp_path: pathlib.Path) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "effects.py").write_text("def apply_status():\n    pass\n", encoding="utf-8")
    specs = [
        {"axis": "real", "consumer": "effects.apply_status", "consumer_note": "x"},
        {"axis": "planned", "consumer": "effects.not_yet_written", "consumer_note": "x"},
        {"axis": "elsewhere", "consumer": "nosuchmod.fn", "consumer_note": "x"},
    ]
    located, contract_only = _mod.locate_consumers(specs, core)
    assert located == ["real -> effects.apply_status"]
    assert len(contract_only) == 2
