"""批61 · 深炼金口径 B（附加型：相性 → 追加效果/状态）· 验收。

依据：
  · `/root/deliverables/深炼金接入_施工清单.md`（预检：G2/G5 已消解、`effect_ref` 零消费者、
    `_pick_weighted` 已跨模块复用）；
  · `/root/deliverables/深炼金相性_玩法口径_可开工版.md` §四（口径 B 附加型：载荷键即作用域
    S1 / 抽取完全复用 / B-1 只查不落 / B-2 写实例 + 使用分派）§六 G3′/G4′ §七 §八。

纪律：
  · 框架零内容包业务名：全部相性 id / 池 id / 效果 id 均为**临时合成**（不写真实包名）；
  · **不写真实内容包**：端到端只读 `content/zz_craft_demo` 的**临时副本**（见后段）；
  · 缺省零变化：无相性 / 池无 `effect_ref` 行 → `picked == []`，且不消耗 `ctx["rng"]`。
"""
from __future__ import annotations

import dataclasses
import random
from typing import Any, Dict, List

import pytest

from qbot_rpg.core import alchemy_affinity as aa
from qbot_rpg.core.alchemy_affinity import effect_refs_of, plan_effect_refs
from qbot_rpg.core.alchemy_settle import SettleEngine
from qbot_rpg.core.deep_craft import resolve_available_entries as craft_entries
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.storage.repository import _item_from_dict

# ---------------------------------------------------------------------------
# 临时合成夹具（零真实内容包业务名）
# ---------------------------------------------------------------------------
_A = "lunar"
_B = "frost"
_E_BURN = "eff_burn"
_E_SLOW = "eff_slow"
_E_CHAIN = "eff_chain"


def _settings() -> Dict[str, Any]:
    """两相性 + 通用池 + 两专属池 + 联动池（覆盖 S1 三条作用域判定）。"""
    return {
        "affinities": [
            {"id": _A, "name": "甲", "exclusive_pool": "p_a"},
            {"id": _B, "name": "乙", "exclusive_pool": "p_b"},
        ],
        "affinity_pools": [
            {"id": "p_common", "kind": "common", "entries": [
                {"stat": "atk", "weight": 10},                       # 打造通道（不该被抽）
                {"effect_ref": _E_SLOW, "weight": 30, "requires_affinity": _B},
            ]},
            {"id": "p_a", "kind": "exclusive", "entries": [
                {"effect_ref": _E_BURN, "weight": 50},
            ]},
            {"id": "p_b", "kind": "exclusive", "entries": [
                {"effect_ref": _E_SLOW, "weight": 50},
            ]},
            {"id": "p_link", "kind": "linkage", "entries": [
                {"effect_ref": _E_CHAIN, "weight": 60},
            ]},
        ],
        "affinity_linkage": [
            {"main": _A, "sub": _B, "override_pool": "p_link"},
        ],
    }


# ===========================================================================
# 1) 池唯一入口：抽取确实走 resolve_available_entries + _pick_weighted
# ===========================================================================
def test_pool_query_goes_through_single_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """monkeypatch 双向探针：`plan_effect_refs` 必须调用 `resolve_available_entries`
    与 `_pick_weighted`（未自造池逻辑——若自算池，探针计数为 0）。"""
    calls: List[Any] = []
    real_entries = aa.resolve_available_entries
    real_pick = aa._pick_weighted

    def spy_entries(*args: Any, **kw: Any) -> Any:
        calls.append(("entries", args, kw))
        return real_entries(*args, **kw)

    def spy_pick(*args: Any, **kw: Any) -> Any:
        calls.append(("pick", args, kw))
        return real_pick(*args, **kw)

    monkeypatch.setattr(aa, "resolve_available_entries", spy_entries)
    monkeypatch.setattr(aa, "_pick_weighted", spy_pick)
    out = plan_effect_refs({_A: 5}, _settings())
    assert out["picked"] == [_E_BURN]
    kinds = [c[0] for c in calls]
    assert "entries" in kinds and "pick" in kinds
    # 池查询只调一次；载荷键 = 唯一源 effect_ref
    assert kinds.count("entries") == 1
    pick_args = [c for c in calls if c[0] == "pick"][0]
    assert pick_args[1][2] == "effect_ref"


def test_single_entry_same_result_as_craft_path() -> None:
    """与打造路径同池同源：同一 cfg 下 `plan_effect_refs` 的 rows ≡ 直调池查询后按
    `effect_ref` 分流（不重算池 → 联动覆盖/requires 过滤逐行一致）。"""
    cfg = _settings()
    rows = plan_effect_refs({_A: 5, _B: 2}, cfg)["rows"]
    direct = [e for e in craft_entries(cfg, _A, _B, None) if e.get("effect_ref")]
    assert rows == direct
    # 联动命中 → 专属池被 override_pool 覆盖（打造同语义）
    # 候选顺序 = 池构造顺序（通用池在前，专属/联动池随后）
    assert [r["effect_ref"] for r in rows] == [_E_SLOW, _E_CHAIN]


# ===========================================================================
# 2) 作用域（S1）：无相性负向 / 主专属 / 副通用 / 不同相性不同附加
# ===========================================================================
def test_no_affinity_yields_nothing_and_does_not_consume_rng() -> None:
    """B-V1 负向：无相性 → `effect_ref` 行全部抽不出；且**不消耗**随机流（门禁 5）。"""
    rng = random.Random(20260919)
    before = rng.getstate()
    assert plan_effect_refs({}, _settings(), rng=rng)["picked"] == []
    assert plan_effect_refs(None, _settings(), rng=rng)["picked"] == []
    assert rng.getstate() == before


def test_no_effect_ref_pool_yields_nothing() -> None:
    """池只有打造载荷（无 `effect_ref`）→ 不抽（打造池不被药剂通道误消费）。"""
    cfg = {"affinities": [{"id": _A}], "affinity_pools": [
        {"id": "p", "kind": "common", "entries": [{"stat": "atk", "weight": 10}]}]}
    assert plan_effect_refs({_A: 5}, cfg)["picked"] == []


def test_different_affinity_picks_different_refs() -> None:
    """不同相性 → 不同附加（两组）：甲主 → 专属池 burn；乙主 → 通用池 slow。"""
    assert plan_effect_refs({_A: 5}, _settings())["picked"] == [_E_BURN]
    assert plan_effect_refs({_B: 5}, _settings())["picked"] == [_E_SLOW]


def test_sub_affinity_common_pool_picked() -> None:
    """副相性词条也能抽（`have = {main, sub}`）：主在专属池、副在通用池同时命中。"""
    out = plan_effect_refs({_A: 5, _B: 2}, {"affinities": _settings()["affinities"],
                                           "affinity_pools": _settings()["affinity_pools"]})
    assert out["main"] == _A and out["sub"] == _B
    assert out["picked"] == [_E_SLOW, _E_BURN]


# ===========================================================================
# 3) 加权抽取复用 `_pick_weighted` 的既有语义（权重 / 不放回 / 确定性 / 全 0 首项）
# ===========================================================================
def test_weighted_draw_count_one_respects_weight() -> None:
    """count=1 时按 weight 抽取；固定 rng 种子同参必同值（确定性）。"""
    cfg = {"affinities": [{"id": _A}], "affinity_pools": [
        {"id": "p", "kind": "common", "entries": [
            {"effect_ref": "eff_low", "weight": 0},
            {"effect_ref": "eff_high", "weight": 100},
        ]}]}
    assert plan_effect_refs({_A: 5}, cfg, rng=random.Random(7), count=1)["picked"] == ["eff_high"]
    seeds = [plan_effect_refs({_A: 5}, cfg, rng=random.Random(s), count=1)["picked"]
             for s in range(5)]
    assert seeds == [["eff_high"]] * 5


def test_weight_all_zero_takes_first_and_dedupes() -> None:
    """权重全 0 → 取候选首项（不引入未声明概率）；同载荷键不放回（至多 1 行）。"""
    cfg = {"affinities": [{"id": _A}], "affinity_pools": [
        {"id": "p", "kind": "common", "entries": [
            {"effect_ref": "eff_x"},
            {"effect_ref": "eff_x"},
            {"effect_ref": "eff_y"},
        ]}]}
    out = plan_effect_refs({_A: 5}, cfg, count=3)
    assert out["picked"] == ["eff_x", "eff_y"]


def test_count_zero_is_no_draw() -> None:
    """count=0 → 不抽（显式关闭；不消耗 rng）。"""
    rng = random.Random(1)
    before = rng.getstate()
    assert plan_effect_refs({_A: 5}, _settings(), rng=rng, count=0)["picked"] == []
    assert rng.getstate() == before


# ===========================================================================
# 4) 实例读取口径（effect_refs_of）
# ===========================================================================
class _Inst:
    def __init__(self, refs: Any) -> None:
        self.effect_refs = refs


def test_effect_refs_of_accepts_object_and_dict_dedupes() -> None:
    assert effect_refs_of(_Inst(("a", "b", "a", "", 3))) == ("a", "b")
    assert effect_refs_of({"effect_refs": ["x"]}) == ("x",)
    assert effect_refs_of(_Inst(None)) == ()
    assert effect_refs_of(_Inst("single")) == ()  # str 不是序列载荷
    assert effect_refs_of(None) == ()


# ===========================================================================
# 5) 写实例（G3′ · B-2）：结算 → add_item(effect_refs=…) → 实例落档往返
# ===========================================================================
def _produce_ctx(bucket: List[Dict[str, Any]], **over: Any) -> Dict[str, Any]:
    def add_item(item_id: str, count: int, bound: bool = True, quality: Any = None,
                 traits: Any = (), affinities: Any = None, **kw: Any) -> Dict[str, Any]:
        bucket.append({"item_id": item_id, "count": count, "quality": quality,
                       "affinities": dict(affinities or {}), "kw": dict(kw)})
        return {"ok": True}

    ctx: Dict[str, Any] = {
        "add_item": add_item,
        "rng": random.Random(20260919),
        "items": {"potion": {"id": "potion", "name": "药"}},
    }
    ctx.update(over)
    return ctx


_RECIPE = {"id": "r", "output": {"item": "potion", "count": 1}}


def test_produce_writes_effect_refs_from_pool() -> None:
    """相性命中池 → `add_item(effect_refs=('eff_burn',))`（产物字段证据）。"""
    bucket: List[Dict[str, Any]] = []
    eng = SettleEngine(settings=_settings())
    snap = {"affinity_values": {_A: 5}, "traits": []}
    out = eng._produce(_produce_ctx(bucket), _RECIPE, snap, "common", 1.0)
    assert out is not None
    assert bucket[0]["kw"]["effect_refs"] == (_E_BURN,)
    assert bucket[0]["affinities"] == {_A: 5.0}


def test_produce_default_no_effect_refs_kwarg() -> None:
    """B-V5 零变化：无相性 / 池无 `effect_ref` → **不传** `effect_refs` kwargs。"""
    bucket: List[Dict[str, Any]] = []
    eng = SettleEngine(settings=_settings())
    out = eng._produce(_produce_ctx(bucket), _RECIPE, {"traits": []}, "common", 1.0)
    assert out is not None
    assert "effect_refs" not in bucket[0]["kw"]


def test_instance_effect_refs_roundtrip_and_legacy_default() -> None:
    """落档往返不丢字段；旧档缺键 → 空元组（无损缺省）。"""
    inst = ItemInstance(item_id="potion", name="药", count=1, quality="common",
                        bound=False, effect_refs=(_E_BURN, _E_SLOW))
    d = dataclasses.asdict(inst)
    assert _item_from_dict(d).effect_refs == (_E_BURN, _E_SLOW)
    legacy = dict(d)
    legacy.pop("effect_refs")
    assert _item_from_dict(legacy).effect_refs == ()
    # 非序列 / 非法值 → 空 / 过滤
    bad = dict(d)
    bad["effect_refs"] = "single"
    assert _item_from_dict(bad).effect_refs == ()
    bad["effect_refs"] = [1, "ok", "", "ok"]
    assert _item_from_dict(bad).effect_refs == ("ok",)
    # dataclass 默认值：既有构造点不传 → 空元组（零影响）
    assert ItemInstance(item_id="x", name="x", count=1, quality="normal",
                        bound=False).effect_refs == ()
