"""批62 · 深炼金口径 C（品质型：相性 → 品质上限加值）· 验收。

依据：
  · `/root/deliverables/深炼金相性_玩法口径_可开工版.md` §五：
    5.1 前置核查（定稿 `:167` = 基础调合 **100% 成功**、无成功率字段 → 5.3 **成功率型不可开工**）；
    5.2 可开工部分 = 品质型（`quality_cap_delta`，复用 `extra_cap` 通道，改动只在
        `_extra_cap` 内）；
    5.5 验收点 C-V1（上限加值生效）/ C-V2（与 SP/核心/挑战求和且 ≤100）/ C-V3（缺省零变化）/
        C-V4（`quality_coef` 不被改写，证明没有新乘区）。
  · `/root/deliverables/深炼金接入_施工清单.md` 批59-B · **B4**（`_extra_cap` 内加相性第 ④ 源）。

纪律：
  · 框架零内容包业务名：相性 id / 材料 / 配方全部临时合成，不写真实内容包；
  · 唯一源：相性取值复用 `core/alchemy_affinity.quality_cap_delta`（`_extra_cap` 不自己查表）；
  · 缺省零变化：不配 `affinity_effects` / 快照无相性 → 与批61 末（基线 `cff0562`）逐字段一致。

【明确不做成功率（规格判定）】成功率型在规格 §5.3 被判"不建议做/不可开工"：定稿是 100% 成功，
新增失败率要改定稿 + 插 roll + 定义失败后果，且与"未达标=品质降级（不吞材料）"双重惩罚冲突。
故本批**只做品质档**，测试中亦无任何成功率/失败分支断言。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Tuple

import pytest

from qbot_rpg.content.validator import check_pack
from qbot_rpg.core import alchemy_affinity as aa
from qbot_rpg.core.alchemy_affinity import quality_cap_delta
from qbot_rpg.core.alchemy_settle import SettleEngine
from qbot_rpg.data.affinity_keys import AFFINITY_EFFECT_QUALITY_CAP

# ---------------------------------------------------------------------------
# 临时合成夹具（零真实内容包业务名）
# ---------------------------------------------------------------------------
_A = "lunar"
_B = "frost"
_KEY = AFFINITY_EFFECT_QUALITY_CAP  # 键名唯一源 = data/affinity_keys（测试不另写字符串）


def _settings_effects(table: Mapping[str, Any], **over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {
        "affinities": [{"id": _A, "name": "甲"}, {"id": _B, "name": "乙"}],
        "alchemy": {"affinity_effects": dict(table)},
    }
    s.update(over)
    return s


# ===========================================================================
# 1) 取值纯函数 `quality_cap_delta`（复用 main_sub_of + resolve_affinity_effect）
# ===========================================================================
def test_helper_two_level_key_and_defaults() -> None:
    """`"主|副"` 更具体优先；无相性 / 表缺失 / 键未声明 → 0（零变化兜底）。"""
    s = _settings_effects({_A: {_KEY: 10}, f"{_A}|{_B}": {_KEY: 15}})
    assert quality_cap_delta({_A: 5}, s) == 10          # 单独主
    assert quality_cap_delta({_A: 5, _B: 2}, s) == 15   # 主|副 更具体
    assert quality_cap_delta({}, s) == 0                # 无相性
    assert quality_cap_delta(None, s) == 0
    assert quality_cap_delta({_A: 5}, {}) == 0          # 表缺失
    assert quality_cap_delta({_A: 5}, _settings_effects({_A: {"healing_done_pct": 20}})) == 0


def test_helper_clamps_and_rejects_bad_values() -> None:
    """负值下钳 0；浮点截断；bool / 非数 → 0（防御降级，不抛异常）。"""
    neg = _settings_effects({_A: {_KEY: -7}})
    assert quality_cap_delta({_A: 5}, neg) == 0
    trunc = _settings_effects({_A: {_KEY: 3.9}})
    assert quality_cap_delta({_A: 5}, trunc) == 3
    for bad in (True, "10", None, [1]):
        assert quality_cap_delta({_A: 5}, _settings_effects({_A: {_KEY: bad}})) == 0


def test_helper_reuses_single_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """唯一源探针：必须调 `resolve_affinity_effect`（若自造查表，计数为 0）。"""
    calls: List[Any] = []
    real = aa.resolve_affinity_effect

    def spy(*args: Any, **kw: Any) -> Any:
        calls.append(args)
        return real(*args, **kw)

    monkeypatch.setattr(aa, "resolve_affinity_effect", spy)
    assert quality_cap_delta({_A: 5}, _settings_effects({_A: {_KEY: 10}})) == 10
    assert len(calls) == 1


# ===========================================================================
# 2) C-V1 · `_extra_cap` 第 ④ 源 + 真实结算管线 → 产物品质档提升
# ===========================================================================
class _Prof:
    """最小熟练引擎替身：只提供 `_extra_cap` 需要的 `unlock_count`。"""

    def __init__(self, sp_count: int = 0) -> None:
        self._n = sp_count

    def unlock_count(self, player: Any, job: str, key: str) -> int:
        return self._n


def _confirm_ctx(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
    def add_item(item_id: str, count: int, bound: bool = True, quality: Any = None,
                 traits: Any = (), affinities: Any = None, **kw: Any) -> Dict[str, Any]:
        bucket.append({"item_id": item_id, "count": count, "quality": quality,
                       "traits": tuple(traits), "affinities": dict(affinities or {}),
                       "extra_keys": sorted(kw)})
        return {"ok": True}

    def count_item(_iid: str) -> int:
        return 99

    def remove_item(_iid: str, _cnt: int) -> Dict[str, Any]:
        return {"ok": True}

    return {
        "add_item": add_item,
        "count_item": count_item,
        "remove_item": remove_item,
        "items": {"m": {"id": "m", "name": "材料", "quality": 70},
                  "potion": {"id": "potion", "name": "药"}},
        "recipe": {"r": _RECIPE},
    }


_RECIPE = {"id": "r", "level": 1, "quality_cap": 59, "element_req": {},
           "output": {"item": "potion", "count": 1}}


def _snap(aff: Any) -> Dict[str, Any]:
    return {"recipe_id": "r", "materials": [{"item": "m", "count": 1, "quality": 70}],
            "traits": [], "element_scores": {}, "affinity_values": aff}


def _confirm(settings: Any, aff: Any,
             prof: Any = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    bucket: List[Dict[str, Any]] = []
    eng = SettleEngine(prof=prof, settings=settings)
    out = asyncio.run(eng.confirm(_confirm_ctx(bucket), _snap(aff), qid="1"))
    return out, bucket


def test_c_v1_affinity_widens_cap_and_raises_tier() -> None:
    """C-V1：材料均值 70 被 `recipe.quality_cap=59` 卡住；相性命中 → 上限放宽到 69 →
    品质档 uncommon → rare（档位真提升，非仅数值）。"""
    settings = _settings_effects({_A: {_KEY: 10}})
    base, base_bucket = _confirm(settings, {})
    hit, hit_bucket = _confirm(settings, {_A: 5})
    assert (base["ok"], hit["ok"]) == (True, True)
    # 负向：无相性 → 未被放宽（59，卡在配方原上限）
    assert base["quality_score"] == 59 and base["tier"] == "uncommon"
    # 正向：相性 +10 → 69 → rare
    assert hit["quality_score"] == 69 and hit["tier"] == "rare"
    assert base["tier"] != hit["tier"]
    # 产物档位随结算结果落实例；相性值随产物落实例（批60 G1 已通）
    assert base_bucket[0]["quality"] == "uncommon"
    assert hit_bucket[0]["quality"] == "rare"
    assert hit_bucket[0]["affinities"] == {_A: 5}
    assert base_bucket[0]["affinities"] == {}


def test_c_v1_different_affinity_different_cap() -> None:
    """两组相性不同加值 → 不同上限/档位（差异由相性而非材料驱动）。"""
    settings = _settings_effects({_A: {_KEY: 10}, _B: {_KEY: 5}})
    a, _ = _confirm(settings, {_A: 5})
    b, _ = _confirm(settings, {_B: 5})
    assert (a["quality_score"], b["quality_score"]) == (69, 64)
    assert (a["tier"], b["tier"]) == ("rare", "rare")  # 64 仍在 rare 区间 [60,79]


def test_c_v1_same_input_reproducible() -> None:
    """同输入可复现（纯函数 + 确定性管线；无随机流消费）。"""
    settings = _settings_effects({_A: {_KEY: 10}})
    runs = [_confirm(settings, {_A: 5})[0] for _ in range(3)]
    assert [(r["quality_score"], r["tier"], r["coef"]) for r in runs] == \
        [(69, "rare", 1.2)] * 3


# ===========================================================================
# 3) C-V2 · 与既有三处叠加（SP / 核心 / 挑战）+ 相性，且仍 ≤100
# ===========================================================================
def test_c_v2_four_sources_sum() -> None:
    """SP×10 + 快照 extra_cap/core_cap/challenge_cap + 相性 = 求和（同机制同单位）。"""
    settings = _settings_effects({_A: {_KEY: 10}})
    snap = {"extra_cap": 4, "core_cap": 6, "challenge_cap": 10, "affinity_values": {_A: 5}}
    eng = SettleEngine(prof=_Prof(sp_count=2), settings=settings)
    assert eng._extra_cap({}, snap) == 2 * 10 + 4 + 6 + 10 + 10  # 50


def test_c_v2_capped_at_100() -> None:
    """上限叠爆不越权：`cap_quality` 硬顶 100（相性加值再大也只放宽可达上限）。"""
    settings = _settings_effects({_A: {_KEY: 999}})
    eng = SettleEngine(settings=settings)
    extra = eng._extra_cap({}, {"affinity_values": {_A: 5}})
    assert extra == 999
    assert eng._quality.cap_quality(100, extra_cap=extra, hard_max=50) == 100


def test_c_v2_confirm_reaches_summed_cap() -> None:
    """端到端：`recipe.quality_cap=50` + 四源合计 40（SP 10 + extra/core/challenge 20
    + 相性 10）→ 可达上限 90，材料均值 100 被放宽到 90（未被 50 卡住）。"""
    settings = _settings_effects({_A: {_KEY: 10}})
    profile = _Prof(sp_count=1)
    bucket: List[Dict[str, Any]] = []
    eng = SettleEngine(prof=profile, settings=settings)
    recipe = {"id": "r", "level": 1, "quality_cap": 50, "element_req": {},
              "output": {"item": "potion", "count": 1}}
    ctx = _confirm_ctx(bucket)
    ctx["recipe"] = {"r": recipe}
    snap = {"recipe_id": "r", "materials": [{"item": "m", "count": 1, "quality": 100}],
            "traits": [], "element_scores": {},
            "extra_cap": 4, "core_cap": 6, "challenge_cap": 10, "affinity_values": {_A: 5}}
    assert eng._extra_cap(ctx, snap) == 10 + 4 + 6 + 10 + 10  # 40（四源求和）
    out = asyncio.run(eng.confirm(ctx, snap, qid="1"))
    assert out["ok"] is True
    assert out["quality_score"] == 90 and out["tier"] == "legendary"


# ===========================================================================
# 4) C-V4 · 不越权：`quality_coef` 逐档值不变（证明没有新乘区）
# ===========================================================================
def test_c_v4_quality_coef_unchanged_and_single_source() -> None:
    """相性只放宽上限，不引入第二套品质系数：`coef` 恒等于 `coef_for(tier)`。"""
    settings = _settings_effects({_A: {_KEY: 10}})
    for tier in ("common", "uncommon", "rare", "legendary"):
        assert settings.get("alchemy", {}).get("quality_coef") is None  # 未声明新系数
    out, _ = _confirm(settings, {_A: 5})
    eng = SettleEngine(settings=settings)
    assert out["coef"] == eng._quality.coef_for(out["tier"])


# ===========================================================================
# 5) 校验器：`quality_cap_delta` 收进内层键空间（其余非法键照旧红拦）
# ===========================================================================
def _verrs(mods: Dict[str, Any]) -> List[Tuple[str, Any]]:
    return [(e.field, e.detail.get("rule")) for e in check_pack(mods).errors]


def test_validator_accepts_quality_cap_delta() -> None:
    good = {"settings": {
        "affinities": [{"id": _A}, {"id": _B}],
        "alchemy": {"affinity_effects": {
            _A: {_KEY: 10, "healing_done_pct": 20},
            f"{_A}|{_B}": {_KEY: 5},
        }},
    }}
    assert _verrs(good) == []


def test_validator_still_rejects_unknown_inner_key_and_bad_value() -> None:
    bad_key = {"settings": {
        "affinities": [{"id": _A}],
        "alchemy": {"affinity_effects": {_A: {"not_a_registered_axis": 1}}},
    }}
    assert any(r == "gear_key_missing" for _, r in _verrs(bad_key))
    bad_val = {"settings": {
        "affinities": [{"id": _A}],
        "alchemy": {"affinity_effects": {_A: {_KEY: "x"}}},
    }}
    assert any(r == "type" for _, r in _verrs(bad_val))


# ===========================================================================
# 6) C-V3 · 缺省零变化对拍（基线 = 批61 末提交 cff0562）
# ===========================================================================
_REPO = __import__("pathlib").Path(__file__).resolve().parents[2]
_BASELINE_REF = "cff0562"
_PROBE = r'''
import asyncio
import json

from qbot_rpg.core.alchemy_settle import SettleEngine

A = "lunar"
# 键名字面量：基线树（cff0562）尚无 data/affinity_keys 常量，跨版本对拍只能写字面量。
bucket = []


def add_item(item_id, count, bound=True, quality=None, traits=(), affinities=None, **kw):
    bucket.append({
        "item_id": item_id, "count": count, "bound": bound, "quality": quality,
        "traits": list(traits), "affinities": dict(affinities or {}), "extra_keys": sorted(kw),
    })
    return {"ok": True}


def count_item(_iid):
    return 99


def remove_item(_iid, _cnt):
    return {"ok": True}


RECIPE = {"id": "r", "level": 1, "quality_cap": 59, "element_req": {},
          "output": {"item": "potion", "count": 1}}
ITEMS = {"m": {"id": "m", "name": "材料", "quality": 70},
         "potion": {"id": "potion", "name": "药"}}
# 声明了 affinity_effects 但快照无相性 → 取值 0（缺省零变化场景）
SETTINGS = {"affinities": [{"id": A}],
            "alchemy": {"affinity_effects": {A: {"quality_cap_delta": 10}}}}


def run(settings, aff):
    bucket.clear()
    eng = SettleEngine(settings=settings)
    ctx = {"add_item": add_item, "count_item": count_item, "remove_item": remove_item,
           "items": ITEMS, "recipe": {"r": RECIPE}}
    snap = {"recipe_id": "r", "materials": [{"item": "m", "count": 1, "quality": 70}],
            "traits": [], "element_scores": {}, "affinity_values": aff}
    out = asyncio.run(eng.confirm(ctx, snap, qid="1"))
    return {"bucket": bucket, "out": out}


cases = {
    "empty_settings_no_aff": run({}, {}),
    "declared_table_no_aff": run(SETTINGS, {}),
    "three_sources_no_aff": run({}, {}),
}
eng = SettleEngine(settings=SETTINGS)
cases["extra_cap_probe"] = {
    "none": eng._extra_cap({}, {}),
    "three": eng._extra_cap({}, {"extra_cap": 4, "core_cap": 6, "challenge_cap": 10}),
    "no_aff": eng._extra_cap({}, {"affinity_values": {}}),
}
print(json.dumps(cases, sort_keys=True, default=list))
'''


def _run_probe(tree: Any) -> Dict[str, Any]:
    import subprocess
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(_PROBE)
        script = fh.name
    proc = subprocess.run(
        [sys.executable, script], cwd=str(tree),
        env={"PYTHONPATH": str(tree), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    import json as _json
    return _json.loads(proc.stdout.strip().splitlines()[-1])


def _have_git() -> bool:
    import subprocess
    if not (_REPO / ".git").exists():
        return False
    r = subprocess.run(["git", "rev-parse", "--verify", f"{_BASELINE_REF}^{{commit}}"],
                       cwd=str(_REPO), capture_output=True, text=True)
    return r.returncode == 0


@pytest.mark.skipif(not _have_git(), reason="无 git 或基线 ref，跳过缺省对拍")
def test_c_v3_default_zero_change_against_baseline() -> None:
    """无相性 / 未命中相性 → `confirm` 返回体 + add_item 参数与基线逐字段一致。"""
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="b62-baseline-") as tmp:
        wt = Path(tmp) / "base"
        add = subprocess.run(["git", "worktree", "add", "--detach", str(wt), _BASELINE_REF],
                             cwd=str(_REPO), capture_output=True, text=True)
        assert add.returncode == 0, add.stderr
        try:
            before = _run_probe(wt)
            after = _run_probe(_REPO)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=str(_REPO), capture_output=True, text=True)
    assert before == after
