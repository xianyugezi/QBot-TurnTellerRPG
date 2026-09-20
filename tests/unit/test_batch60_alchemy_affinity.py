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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Tuple

import pytest

from qbot_rpg.commands.use_commands import _use_consumable
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.affinity import accumulate_affinity, rank_affinities
from qbot_rpg.core.alchemy_affinity import axis_pct, main_sub_of
from qbot_rpg.core.alchemy_core import AlchemyCore
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player, PlayerAttributes
from qbot_rpg.storage.repository import _item_from_dict

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


# ===========================================================================
# 口径 A · 强度型：相性 → 特效轴（取值纯函数 + 使用链路消费）
# ===========================================================================
_AXIS = "healing_done_pct"


def _settings_effects(table: Mapping[str, Any], **over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {"affinities": [{"id": _AFF, "name": "甲"}, {"id": _SUB, "name": "乙"}],
                         "alchemy": {"affinity_effects": dict(table)}}
    s.update(over)
    return s


def _use_ctx(settings: Any, *, power: int = 50, hp: int = 30) -> Dict[str, Any]:
    return {
        "registered": True,
        "player": {"name": "试", "level": 1, "job_id": "warrior", "hp": hp,
                   "inventory": [], "equipment": {},
                   "attributes": PlayerAttributes(base={"hp": 1000000.0, "mp": 30.0})},
        "items": {"heal_potion": {"id": "heal_potion", "name": "药", "type": "consumable",
                                  "usable": True, "effects": ["heal_small"]}},
        "effect_table": {"heal_small": {"id": "heal_small", "type": "heal", "power": power}},
        "inventory_engine": SimpleNamespace(
            remove_item=lambda p, iid, count=1, uid="": {"ok": True}),
        "settings": settings,
    }


def _use(aff: Any, ctx: Dict[str, Any], *, with_field: bool = True) -> int:
    inst = SimpleNamespace(item_id="heal_potion", name="药", uid="u1")
    if with_field:
        inst.affinities = aff
    _use_consumable(ctx, ctx["player"], inst, ctx["items"]["heal_potion"])
    return int(ctx["player"]["hp"])


# ---- B1 · 纯函数取值 ----
def test_b1_main_sub_of_matches_generic_rank() -> None:
    settings = _SETTINGS_AFF
    out = main_sub_of({"lunar": 5, "frost": 2}, settings)
    assert out["main"] == _AFF and out["sub"] == _SUB
    assert out["ranked"] == [(_AFF, 5.0), (_SUB, 2.0)]
    assert main_sub_of({}, settings)["main"] is None


def test_b1_axis_pct_two_level_key_and_defaults() -> None:
    """A-V4：`"主|副"` 更具体，优先于 `"主"`；无相性/未知轴/表缺失 → 0.0。"""
    settings = _settings_effects({_AFF: {_AXIS: 20}, f"{_AFF}|{_SUB}": {_AXIS: 30}})
    assert axis_pct({_AFF: 5}, settings, _AXIS) == 20.0          # 单独主
    assert axis_pct({_AFF: 5, _SUB: 2}, settings, _AXIS) == 30.0  # 主|副 更具体
    assert axis_pct({}, settings, _AXIS) == 0.0                  # 无相性
    assert axis_pct({_AFF: 5}, {}, _AXIS) == 0.0                 # 表缺失
    assert axis_pct({_AFF: 5}, settings, "not_an_effect_axis") == 0.0  # 非登记轴


def test_b1_axis_pct_clamped_by_declared_range() -> None:
    """A-V3：超界声明按 `settings.effect_axes` 钳制（区间不由内容包自定）。"""
    over = {"effect_axes": {_AXIS: {"min": -50, "max": 10}}}
    settings = _settings_effects({_AFF: {_AXIS: 9999}}, **over)
    assert axis_pct({_AFF: 5}, settings, _AXIS) == 10.0
    settings2 = _settings_effects({_AFF: {_AXIS: -9999}}, **over)
    assert axis_pct({_AFF: 5}, settings2, _AXIS) == -50.0


# ---- B2 · 使用链路消费（非战斗 /道具）----
def test_a_v2_no_affinity_instance_is_byte_identical() -> None:
    """A-V2/V5：实例无相性（空 dict / 无字段）→ 回血 = 定义 power，逐字节一致。"""
    assert _use({}, _use_ctx({})) == 80              # 30 + 50
    assert _use({}, _use_ctx(_settings_effects({_AFF: {_AXIS: 20}}))) == 80
    assert _use(None, _use_ctx(_settings_effects({_AFF: {_AXIS: 20}})),
                with_field=False) == 80               # 商店药剂：实例根本无该字段


def test_a_v1_only_affinity_differs_changes_heal_ratio() -> None:
    """A-V1：同定义、仅实例相性不同 → 回血比值 = (1+pa/100)/(1+pb/100)（±1 取整）。"""
    settings = _settings_effects({_AFF: {_AXIS: 20}, _SUB: {_AXIS: -10}})
    hp_a = _use({_AFF: 5}, _use_ctx(settings))
    hp_b = _use({_SUB: 5}, _use_ctx(settings))
    heal_a, heal_b = hp_a - 30, hp_b - 30
    assert (heal_a, heal_b) == (60, 45)
    assert abs(heal_a / heal_b - (1.20 / 0.90)) < 1e-9


def test_a_v3_clamp_applied_in_use_path() -> None:
    settings = _settings_effects({_AFF: {_AXIS: 9999}},
                                 effect_axes={_AXIS: {"max": 10}})
    assert _use({_AFF: 5}, _use_ctx(settings)) == 85  # 50 × 1.10 = 55


def test_a_v4_two_level_key_in_use_path() -> None:
    settings = _settings_effects({_AFF: {_AXIS: 20}, f"{_AFF}|{_SUB}": {_AXIS: 30}})
    assert _use({_AFF: 5}, _use_ctx(settings)) == 90               # 50 × 1.20 = 60
    assert _use({_AFF: 5, _SUB: 2}, _use_ctx(settings)) == 95      # 50 × 1.30 = 65


def test_a_v4_axis_parametrised_strength_and_duration() -> None:
    """轴参数化：强度轴与**时长轴**同一取值机制（本批只接治疗消费点，时长消费待接）。"""
    settings = _settings_effects(
        {_AFF: {"healing_done_pct": 20, "status_duration_pct": 25}})
    assert axis_pct({_AFF: 5}, settings, "healing_done_pct") == 20.0
    assert axis_pct({_AFF: 5}, settings, "status_duration_pct") == 25.0
    assert axis_pct({_AFF: 5}, settings, "damage_dealt_pct") == 0.0  # 未在该表声明 → 不生效
    # 时长轴同样可被 K 侧钳制（-80~300 缺省；此处包声明 max=15）
    clamped = _settings_effects({_AFF: {"status_duration_pct": 999}},
                                effect_axes={"status_duration_pct": {"max": 15}})
    assert axis_pct({_AFF: 5}, clamped, "status_duration_pct") == 15.0


def test_a_round_matches_heal_apply_formula() -> None:
    """取整与 `effects.heal_apply` 同式：`int(round(heal × (1+pct/100)))`。"""
    settings = _settings_effects({_AFF: {_AXIS: 7}})
    hp = _use({_AFF: 5}, _use_ctx(settings, power=50))  # 53.5 → 54
    assert hp == 30 + int(round(50 * 1.07))


def test_a_same_input_reproducible() -> None:
    """同输入可复现（纯函数，无随机流消费）。"""
    settings = _settings_effects({_AFF: {_AXIS: 20}})
    first = [_use({_AFF: 5}, _use_ctx(settings)) for _ in range(3)]
    assert first == [90, 90, 90]
    assert axis_pct({_AFF: 5}, settings, _AXIS) == 20.0


# ---- 校验器 V1~V3（配置键空间红拦）----
def _verrs(mods: Dict[str, Any]) -> List[Tuple[str, Any]]:
    return [(e.field, e.detail.get("rule")) for e in check_pack(mods).errors]


def test_validator_affinity_effects_keyspace() -> None:
    good = {"settings": {
        "affinities": [{"id": _AFF}, {"id": _SUB}],
        "alchemy": {"affinity_effects": {
            _AFF: {_AXIS: 20},
            f"{_AFF}|{_SUB}": {_AXIS: 30},
        }},
    }}
    assert _verrs(good) == []
    bad_axis = {"settings": {
        "affinities": [{"id": _AFF}],
        "alchemy": {"affinity_effects": {_AFF: {"not_a_registered_axis": 1}}},
    }}
    assert any(r == "gear_key_missing" for _, r in _verrs(bad_axis))
    bad_aff = {"settings": {
        "affinities": [{"id": _AFF}],
        "alchemy": {"affinity_effects": {"ghost": {_AXIS: 1}}},
    }}
    assert any(r == "affinity_ref_missing" for _, r in _verrs(bad_aff))
    bad_val = {"settings": {
        "affinities": [{"id": _AFF}],
        "alchemy": {"affinity_effects": {_AFF: {_AXIS: "x"}}},
    }}
    assert any(r == "type" for _, r in _verrs(bad_val))


# ===========================================================================
# 端到端（只读夹具 `content/zz_craft_demo` 的**临时副本**）
# ===========================================================================
DEMO_PACK = REPO / "content" / "zz_craft_demo"
_E2E_QID = "60001"
_E2E_EFFECT = {"id": "eff_demo_draught_heal", "name": "示例回复", "type": "heal",
               "power": 100, "desc": "示例：相性影响回复量的饮剂效果。"}
_E2E_POTION = {"id": "demo_lunar_draught", "name": "月华饮剂", "type": "consumable",
               "usable": True, "effects": ["eff_demo_draught_heal"],
               "desc": "示例：相性影响回复量的饮剂。"}
_E2E_RECIPE = {"id": "rcp_demo_lunar_draught", "name": "月华饮剂调和", "kind": "craft",
               "level": 5, "synth_allowed": True, "master_only": False, "slots": 4,
               "element_req": {}, "pp_budget": 5,
               "materials": [{"id": "moonwell_dew", "count": 1}],
               "output": {"item": "demo_lunar_draught", "count": 1},
               "cost": {"coins": 0, "gem": 0}}
_E2E_EFFECTS = {
    "lunar": {_AXIS: 20}, "frost": {_AXIS: -10}, f"{_AFF}|{_SUB}": {_AXIS: 30},
}


def _e2e_patch(pack: Path) -> Dict[str, Any]:
    """临时副本：补药剂/回复效果/炼金用配方 + settings.alchemy(mode=full + 相性效果表)。

    说明：示例包 `alchemy.mode=simple`（炼金层未启用）且无炼金用配方；本端到端按红线
    「只读真实包、写只在临时目录」在副本上补齐，不写 `content/zz_craft_demo` 一个字节。
    """
    for name, entry in (("effects.json", _E2E_EFFECT), ("items.json", _E2E_POTION),
                        ("recipe.json", _E2E_RECIPE)):
        p = pack / name
        rows = json.loads(p.read_text(encoding="utf-8"))
        rows.append(entry)
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    s = json.loads((pack / "settings.json").read_text(encoding="utf-8"))
    alch = dict(s.get("alchemy") or {})
    alch["mode"] = "full"
    alch["affinity_effects"] = dict(_E2E_EFFECTS)
    s["alchemy"] = alch
    (pack / "settings.json").write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return s


def _e2e_player(mat: str) -> Any:
    return Player(
        qid=_E2E_QID, name="示例匠", job_id="warrior", level=35, hp=10, mp=999,
        currencies={"coins": 0, "gem": 0},
        inventory=(ItemInstance(item_id=mat, name=mat, count=90, quality="normal",
                                bound=False),),
        attributes=PlayerAttributes(base={"hp": 100000.0, "mp": 100.0}),
        persistent_state={
            "proficiency": {"alchemy": {"level": 60, "exp": 0, "sp_earned": 0,
                                        "sp_used": 0, "unlocks": {}}},
            "learned_blueprints": {},
        },
    )


def _heal_via_use(inst: Any, settings: Any, power: int = 100) -> int:
    """在受控 ctx 上走真实 `_use_consumable`（假背包引擎，隔离无关的 uid 路径）。"""
    player: Dict[str, Any] = {"hp": 10,
                              "attributes": PlayerAttributes(base={"hp": 1000000.0,
                                                                    "mp": 100.0})}
    ctx: Dict[str, Any] = {
        "player": player,
        "effect_table": {_E2E_EFFECT["id"]: _E2E_EFFECT},
        "inventory_engine": SimpleNamespace(
            remove_item=lambda p, iid, count=1, uid="": {"ok": True}),
        "settings": settings,
    }
    _use_consumable(ctx, player, inst, _E2E_POTION)
    return int(player["hp"]) - 10


async def _run_e2e_case(mat: str, tmp_path: Path) -> Dict[str, Any]:
    import dataclasses

    from qbot_rpg.assembly.testing_support import pack_app, send_command

    pack = Path(tempfile.mkdtemp(prefix=f"b60-pack-{mat}-", dir=str(tmp_path)))
    shutil.copytree(DEMO_PACK, pack, dirs_exist_ok=True)
    settings = _e2e_patch(pack)
    async with pack_app(pack, settings={"alchemy": settings["alchemy"]}) as deps:
        repo = deps.repo
        await repo.save_player(_e2e_player(mat))
        opened = await send_command(deps, "/炼金 月华饮剂调和", user_id=_E2E_QID)
        assert "月华饮剂调和" in opened, opened
        fed = await send_command(deps, f"/投料 {mat}", user_id=_E2E_QID)
        assert "❌" not in fed, fed
        done = await send_command(deps, "/确认", user_id=_E2E_QID)
        assert "确认成功" in done, done
        p = await repo.load_player(_E2E_QID)
        rows = [r for r in p.inventory if r.item_id == "demo_lunar_draught"]
        assert rows, [r.item_id for r in p.inventory]
        inst = rows[-1]
        heal = _heal_via_use(inst, settings)
        # 落档读侧往返（C3/C4 **已支持**，本批仅验收）：asdict → _item_from_dict 不丢相性
        carried = _item_from_dict(dataclasses.asdict(inst))
        return {"affinities": dict(inst.affinities), "heal": heal,
                "carried": dict(carried.affinities)}


@pytest.mark.asyncio
async def test_e2e_demo_pack_alchemy_affinity_flows_to_product_and_heal(tmp_path: Path) -> None:
    """同配方、同材料品质、仅材料相性不同 → 产物实例相性不同 → 实际回血不同（A-V1）。"""
    lunar = await _run_e2e_case("moonwell_dew", tmp_path)
    frost = await _run_e2e_case("frost_marrow", tmp_path)
    # G3：炼金产物实例带相性（此前实测为 False/缺键）
    assert lunar["affinities"] == {"lunar": 16.0}
    assert frost["affinities"] == {"frost": 11.0}
    assert lunar["carried"] == lunar["affinities"]  # 实例字段往返不丢
    # 口径 A：产物实际回血 = power × (1 + pct/100)（lunar=20 → 120；frost=-10 → 90）
    assert (lunar["heal"], frost["heal"]) == (120, 90)
    assert abs(lunar["heal"] / frost["heal"] - (1.20 / 0.90)) < 1e-9


@pytest.mark.asyncio
async def test_e2e_demo_pack_same_input_reproducible(tmp_path: Path) -> None:
    a = await _run_e2e_case("moonwell_dew", tmp_path)
    b = await _run_e2e_case("moonwell_dew", tmp_path)
    assert a == b
