"""批60 · 深炼金相性接入 · 第 1 步验收（G1 相性进快照 + 口径 A 强度型 + 实例链）。

依据：
  · `/root/deliverables/深炼金接入_施工清单.md` §2 批59-A/B/C（本批 = A1~A3 + B1/B2/B3 + C1~C4）；
  · `/root/deliverables/深炼金相性_玩法口径_可开工版.md` §三（口径 A 强度型）/ §六（G1/G3/G4）/
    §七（配置形状）/ §八（分期）。

纪律：
  · 框架零内容包业务名：本文件不写死任何真实相性名/轴值（全部临时合成声明）；
  · **不写真实内容包**：端到端只**只读** `content/zz_craft_demo`（`pack_app` 内存库，不写字节）；
  · 缺省零变化：不声明相性 → 逐字段一致（`_probe` 对拍见 §对拍）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.core.affinity import accumulate_affinity, rank_affinities
from qbot_rpg.core.alchemy_core import AlchemyCore

REPO = Path(__file__).resolve().parents[2]
#: 批60 前一个提交（main 最新）= G1 对拍基线（缺 ref / 无 git → 跳过集成对拍）。
BASELINE_REF = "28a8264"

# ---------------------------------------------------------------------------
# 临时合成夹具（零真实内容包业务名）
# ---------------------------------------------------------------------------
_AFF = "lunar"
_SUB = "frost"
_PLAIN = "plain_ore"
_DROP = "drop_ore"

_SETTINGS_AFF: Dict[str, Any] = {
    "affinities": [{"id": _AFF, "name": "甲"}, {"id": _SUB, "name": "乙"}],
    "affinity_reactions": [{"kind": "amplify", "pair": [_AFF, _SUB], "value": 3}],
}
_ITEMS: Dict[str, Any] = {
    "moon_dew": {"id": "moon_dew", "name": "露", "type": "material",
                 "affinities": {_AFF: 16}},
    "frost_shard": {"id": "frost_shard", "name": "霜", "type": "material",
                    "affinities": {_SUB: 11}},
    _PLAIN: {"id": _PLAIN, "name": "素", "type": "material"},
    _DROP: {"id": _DROP, "name": "杂", "type": "material",
            "affinities": {_AFF: "x", "": 3, _SUB: True, "ember": 2}},
}
_RECIPE: Dict[str, Any] = {"id": "r_probe", "slots": 4, "pp_budget": 5}


def _core(settings: Any = None) -> AlchemyCore:
    return AlchemyCore(settings=settings or {})


def _ctx(count: int = 99) -> Dict[str, Any]:
    return {"items": _ITEMS, "recipe": {"r_probe": _RECIPE},
            "count_item": lambda _i: count}


def _feed(items: List[Any], settings: Any = None) -> Dict[str, Any]:
    core = _core(settings)
    snap0 = core.new_snapshot(_RECIPE)
    return core.apply_feed(snap0, items, _ctx())


# ===========================================================================
# G1 · 材料相性进炼金记录与快照（零行为变化）
# ===========================================================================
def test_g1_new_snapshot_has_three_affinity_keys() -> None:
    """新快照形态扩展 3 键（`affinity_values`/`affinity_main`/`affinity_sub`），缺省空。"""
    snap = _core().new_snapshot(_RECIPE)
    assert snap["affinity_values"] == {}
    assert snap["affinity_main"] is None
    assert snap["affinity_sub"] is None


def test_g1_material_record_carries_affinities() -> None:
    """材料声明相性 → 记录带 `affinities`（float），数值原样。"""
    out = _feed([{"item": "moon_dew"}])
    assert out["ok"], out
    rec = out["snap"]["materials"][0]
    assert rec["affinities"] == {_AFF: 16.0}


def test_g1_material_without_affinity_is_empty_and_no_error() -> None:
    """材料无 `affinities` 声明 → 记录 `affinities == {}`，其余不改、不抛。"""
    out = _feed([{"item": _PLAIN}])
    assert out["ok"], out
    rec = out["snap"]["materials"][0]
    assert rec["affinities"] == {}
    assert rec["item"] == _PLAIN and rec["count"] == 1


def test_g1_invalid_affinity_values_dropped() -> None:
    """非法值（字符串 / 空键 / 布尔 / 非声明键保留但值合法）→ 只保留合法数对。"""
    out = _feed([{"item": _DROP}])
    assert out["ok"], out
    rec = out["snap"]["materials"][0]
    # 字符串被丢弃、空键被丢弃、布尔被丢弃；数值 2 保留（键非空 str + 值为 int）
    assert rec["affinities"] == {"ember": 2.0}


def test_g1_snapshot_affinity_equals_direct_generic_calls() -> None:
    """快照 `affinity_values/main/sub` 与直调 `accumulate_affinity`+`rank_affinities` 同值。"""
    out = _feed([{"item": "moon_dew"}, {"item": "frost_shard"}],
                settings=_SETTINGS_AFF)
    assert out["ok"], out
    snap = out["snap"]
    per_mat = [{"lunar": 16}, {"frost": 11}]
    values = accumulate_affinity(per_mat, _SETTINGS_AFF["affinity_reactions"])
    ranked = rank_affinities(values, _SETTINGS_AFF["affinities"])
    assert snap["affinity_values"] == values
    assert snap["affinity_main"] == ranked["main"]
    assert snap["affinity_sub"] == ranked["sub"]
    assert (snap["affinity_main"], snap["affinity_sub"]) == (_AFF, _SUB)


def test_g1_no_affinity_config_behaves_as_before() -> None:
    """不配相性（settings 无相性段 + 材料无声明）→ 全流程零变化（快照仅多 3 个空键）。"""
    out = _feed([{"item": _PLAIN}])
    assert out["ok"], out
    snap = out["snap"]
    assert snap["affinity_values"] == {}
    assert snap["affinity_main"] is None and snap["affinity_sub"] is None
    assert snap["chain"]["segments"] == 0
    assert snap["element_scores"] == {}
    assert snap["pool"] == {"normal": [], "gold": [], "awaken": []}
    assert snap["version"] == 2


def test_g1_material_affinity_accumulates_even_without_definitions() -> None:
    """材料声明相性、`settings.affinities` 缺段：仍按通用层累计（与打造同口径）。

    说明：未声明的相性 id 会被校验器红拦（`affinity_ref_missing`），故真实内容包里
    「材料带相性但 settings 缺相性段」不成立；此处只钉死「累计逻辑不依赖定义段」。
    """
    out = _feed([{"item": "moon_dew"}])
    assert out["ok"], out
    snap = out["snap"]
    assert snap["affinity_values"] == {_AFF: 16.0}
    assert snap["affinity_main"] == _AFF and snap["affinity_sub"] is None



def test_g1_snapshot_affinity_zero_when_materials_have_none() -> None:
    """配了相性但材料全无声明 → `affinity_values == {}`、main/sub 均 None（负向）。"""
    out = _feed([{"item": _PLAIN}], settings=_SETTINGS_AFF)
    assert out["ok"], out
    snap = out["snap"]
    assert snap["affinity_values"] == {}
    assert snap["affinity_main"] is None and snap["affinity_sub"] is None


# ---------------------------------------------------------------------------
# G1 对拍门禁：基线树 vs 当前树，同一探针逐字段比对（缺省零变化）
# ---------------------------------------------------------------------------
_PROBE = r'''
import json, sys
from qbot_rpg.core.alchemy_core import AlchemyCore

ITEMS = {
    "moon_dew": {"id": "moon_dew", "name": "露", "type": "material",
                 "affinities": {"lunar": 16}},
    "plain_ore": {"id": "plain_ore", "name": "素", "type": "material"},
}
RECIPE = {"id": "r_probe", "slots": 4, "pp_budget": 5}
CTX = {"items": ITEMS, "recipe": {"r_probe": RECIPE}, "count_item": lambda _i: 99}

core = AlchemyCore(settings={})          # 不配相性 = 缺省
snap0 = core.new_snapshot(RECIPE)
out = core.apply_feed(snap0, [{"item": "moon_dew"}, {"item": "plain_ore"}], CTX)
snap = out["snap"]
print(json.dumps({
    "feed_ok": out["ok"],
    "snap": {k: v for k, v in snap.items() if k != "materials"},
    "records": snap["materials"],
    "return_keys": sorted(out.keys()),
}, sort_keys=True, default=list))
'''


def _run_probe(tree: Path) -> Dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(_PROBE)
        script = fh.name
    proc = subprocess.run(
        [sys.executable, script], cwd=str(tree),
        env={"PYTHONPATH": str(tree), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _have_git() -> bool:
    if not (REPO / ".git").exists():
        return False
    r = subprocess.run(["git", "rev-parse", "--verify", f"{BASELINE_REF}^{{commit}}"],
                       cwd=str(REPO), capture_output=True, text=True)
    return r.returncode == 0


@pytest.mark.skipif(not _have_git(), reason="无 git 或基线 ref，跳过 G1 对拍")
def test_g1_default_zero_change_against_baseline() -> None:
    """默认（不配相性）下当前树与基线树逐字段一致——仅新增 3 个快照键 + 1 个记录键。"""
    with tempfile.TemporaryDirectory(prefix="b60-g1-") as tmp:
        wt = Path(tmp) / "base"
        add = subprocess.run(["git", "worktree", "add", "--detach", str(wt), BASELINE_REF],
                             cwd=str(REPO), capture_output=True, text=True)
        assert add.returncode == 0, add.stderr
        try:
            before = _run_probe(wt)
            after = _run_probe(REPO)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=str(REPO), capture_output=True, text=True)
    # 共同键逐值一致
    common = set(before["snap"]) & set(after["snap"])
    for k in common:
        assert before["snap"][k] == after["snap"][k], k
    assert set(after["snap"]) - set(before["snap"]) == {
        "affinity_values", "affinity_main", "affinity_sub"}
    assert set(before["snap"]) - set(after["snap"]) == set()
    # 材料记录：其余 10 键逐字段一致，仅多 `affinities`
    assert len(before["records"]) == len(after["records"]) == 2
    for b, a in zip(before["records"], after["records"]):
        assert set(a) - set(b) == {"affinities"}
        assert set(b) - set(a) == set()
        for k in set(b) & set(a):
            assert b[k] == a[k], k
    # apply_feed 返回体键集不变（口径 A 不新增返回键）
    assert before["return_keys"] == after["return_keys"]
