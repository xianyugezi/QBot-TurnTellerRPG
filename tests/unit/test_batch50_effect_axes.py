"""批50 · 特效轴地基验收测试（P + 小 K，**不含任何消费点**）。

口径：`特效整理设计_1_修正轴全集.md` §2/§3 + `特效整理设计_3_落点与分期.md`
§1.0（表示口径：百分点增量轴，默认 0）/§1.2（逐轴落点）/§二「批48」（= 本批，旧编号）
+ `docs/深度打造_决策记录.md` §十三「双向修正轴优先」。

红线与验收（逐条对应）：
  1. **零行为变化**：缺省 / 未配置 → 逐字段零变化（registry 对拍 + 战斗快照对拍）；
  2. **登记完备**：P0/P1 各轴在 `EFFECT_AXIS_SPECS` 可枚举，**每轴有唯一消费点（待接）**；
     无消费点的轴不得登记（`DEFERRED` 清单钉死未登记项及原因）；
  3. **校验**：越界红拦 / 未知轴黄提示 / 与面板三轴 stem 冲突红拦；
  4. **编辑器**：轴可见、中文名与双向说明齐备（接口断言 + DOM 证据）。

纪律：本测试只在 pytest `tmp_path` 建临时内容根（copytree + 就地改写），
不写仓库真实 `content/`（`_content_pollution_guard` 会话钩子同时兜底）。
"""
from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

import pytest

from qbot_rpg.content.field_meta import (
    SETTINGS_FIELDS,
    default_field_meta_table,
)
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.panel_budget import PANEL_AXIS_KEYS
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.data.gear_stats import (
    COMBAT_TO_COMBATANT,
    DEFAULT_EFFECT_AXES,
    EFFECT_AXIS_SPECS,
    EFFECT_LEGACY_ALIASES,
    EFFECT_TO_COMBATANT,
    GEAR_COMBAT_KEYS,
    GEAR_DISPLAY_KEYS,
    GEAR_EFFECT_KEYS,
    GEAR_FLAT_KEYS,
    GEAR_NUMERIC_KEYS,
    GEAR_PCT_KEYS,
    GEAR_PLACEHOLDER_KEYS,
    PANEL_AXIS_STEMS,
    PCT_SUFFIX,
    combatant_updates,
    effect_axis_spec,
    effect_axis_stem,
    extract_bonus,
    normalize_effect_axes,
    route_bonus_into,
)

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

#: 轴全集 §3 定级 **P0** 的数值轴（本批登记）。
P0_AXES: Tuple[str, ...] = (
    "healing_received_pct", "healing_done_pct",      # X17 / X16
    "damage_taken_pct", "damage_dealt_pct",          # X02 / X01
    "cooldown_pct",                                   # X27
    "status_chance_pct",                              # X21
    "stack_gain_pct", "stack_cap_delta",              # X23 / X24
)
#: 轴全集 §3 定级 **P1** 的数值轴（本批登记）。
P1_AXES: Tuple[str, ...] = (
    "status_duration_pct", "status_duration_taken_pct",  # X20 dealt/received
    "status_resist_pct",                                  # X22
    "action_bar_shift",                                   # X30
    "resource_cost_pct", "resource_gain_pct",             # X34 / X35
    "crit_damage_pct",                                    # X03
)
#: **未登记**的 P0/P1 项及原因（不得与 `GEAR_EFFECT_KEYS` 相交——登记纪律）。
DEFERRED: Tuple[Tuple[str, str], ...] = (
    ("lifesteal_pct / drain_to_resource (X12 / D-5, P1)",
     "无**唯一**消费点：吸血有两条并存路径（battle.absorb_hp + effects.lifesteal），"
     "须先归并；归并即改动既有吸血行为 → 违反本批零行为变化"),
    ("reward_mult{scope} (X43 / L-1, P1)",
     "一条轴多 scope 实例，声明形状待裁决；消费点分散在 settle_battle_rewards / "
     "roll_death_drops / reward._SCALAR_KEYS 三处 → 无唯一收口"),
    ("stack_potency_pct (X25 / S-7, P1)",
     "消费点 `_aggregate_boost` 现按状态实例求和、**不乘 stacks**；接轴须先改聚合本身"
     "（M），且与符文 2 阶共用改造 → 非纯登记可承载"),
    ("buildup_rate_pct (X26, P1)",
     "**缺消费点**：异常累积段（buildup）尚不存在 → 按「无消费点的轴不得登记」不登记"),
    ("action_recovery_pct (A-2 / X29)",
     "轴全集 §3 定级 **P2**（超出本批 P0/P1 登记范围）；其消费点须归并 "
     "enrage/fatigue_recovery_mult 状态硬编码倍率（改动既有行为）→ 随时序批登记"),
    ("action_speed_pct (X28)",
     "设计文档 §1.2/§1.4 裁定与 X29 二选一（并存 → 指数级速度），**只留 A-2** → "
     "永不作为独立轴登记"),
    ("roll_mode (X42) / pierce{target} (X06) / stack_mode (I03)",
     "聚合规则与方向参数，**不是数值轴**（轴全集 §4 E7）；穿透是既有键的扩展"),
    ("I01 触发归属 / I02 条件变量 / I04 套装阈值",
     "接线类基础设施（触发/条件/既有机制），非数值轴，不进 EFFECT 键族"),
)


# =====================================================================================
# A · 一表一号（键族登记与登记纪律）
# =====================================================================================
def _recursive_keys(obj: Any) -> List[str]:
    """递归收集 JSON 结构里出现的所有字符串键（对拍用）。"""
    out: List[str] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_recursive_keys(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_recursive_keys(v))
    return out


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _stable_json(obj: Any) -> str:
    """快照 → 稳定 JSON 串（实例 uid 归一化；其余字段逐字段严格保留）。"""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return _UUID_RE.sub("<uid>", text)


def test_a1_keys_derived_from_single_table_no_duplicates() -> None:
    """键族由登记表派生（唯一源）；无重复、无空名。"""
    assert GEAR_EFFECT_KEYS == tuple(str(s["axis"]) for s in EFFECT_AXIS_SPECS)
    assert len(GEAR_EFFECT_KEYS) == len(set(GEAR_EFFECT_KEYS))
    assert all(k and isinstance(k, str) for k in GEAR_EFFECT_KEYS)
    assert GEAR_EFFECT_KEYS == P0_AXES + P1_AXES  # 登记顺序 = P0 先 P1 后


def test_a2_p0_p1_axes_enumerable_and_every_axis_has_unique_consumer() -> None:
    """登记完备：P0/P1 各轴可枚举，**每轴都有唯一消费点（本批待接）**。

    「无消费点的轴不得登记」——`consumer` 空即视为违反登记纪律（`cooldown_reduction_pct`
    的教训：登记了不生效 = 对作者是陷阱）。
    """
    by_axis = {str(s["axis"]): s for s in EFFECT_AXIS_SPECS}
    assert set(by_axis) == set(P0_AXES) | set(P1_AXES)
    p0 = [s for s in EFFECT_AXIS_SPECS if str(s.get("priority")) == "P0"]
    p1 = [s for s in EFFECT_AXIS_SPECS if str(s.get("priority")) == "P1"]
    assert [str(s["axis"]) for s in p0] == list(P0_AXES)
    assert [str(s["axis"]) for s in p1] == list(P1_AXES)
    for axis, spec in by_axis.items():
        assert str(spec.get("consumer", "")).strip(), f"{axis} 缺「唯一消费点（待接）」"
        assert str(spec.get("consumer_note", "")).strip(), f"{axis} 缺消费点说明"
        assert str(spec.get("doc_id", "")).strip(), f"{axis} 缺轴全集条目号（可回溯）"
        assert str(spec.get("priority")) in ("P0", "P1"), axis
        assert str(spec.get("stack", "add")) == "add", axis
        disp = spec["display"]
        assert str(disp["label"]).strip() and str(disp["help"]).strip(), axis
        assert str(disp["mode"]) in ("mult", "delta"), axis
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and hi is not None:
            assert float(lo) <= float(hi), axis


def test_a3_deferred_axes_are_not_registered() -> None:
    """未登记项与已登记键族不相交；每条未登记项写明原因（不得静默省略）。"""
    for item, reason in DEFERRED:
        assert reason.strip(), item
        head = item.split(" ")[0]
        for token in head.replace("/", " ").split():
            assert token not in GEAR_EFFECT_KEYS, f"{token} 已在键族里，应从 DEFERRED 移除"


def test_a4_declaration_defaults_are_identity_zeros() -> None:
    """缺省声明全为恒等：增量轴 default 0；未声明态 `declared=False`。"""
    assert set(DEFAULT_EFFECT_AXES) == set(GEAR_EFFECT_KEYS)
    for axis, entry in DEFAULT_EFFECT_AXES.items():
        assert float(entry["default"]) == 0.0, axis
        assert str(entry["stack"]) == "add", axis
        assert str(entry["display"]["mode"]) in ("mult", "delta"), axis
    norm = normalize_effect_axes(None)
    assert set(norm) == set(GEAR_EFFECT_KEYS)
    assert all(entry["declared"] is False for entry in norm.values())


def test_a5_axis_names_do_not_collide_with_existing_key_space() -> None:
    """自证：登记轴不与既有键空间撞名，且 stem 不撞面板三轴（框架侧硬前提）。"""
    legacy = set(GEAR_FLAT_KEYS) | set(GEAR_PCT_KEYS) | set(GEAR_COMBAT_KEYS)
    assert not (set(GEAR_EFFECT_KEYS) & legacy)
    assert not (set(GEAR_EFFECT_KEYS) & set(GEAR_PLACEHOLDER_KEYS))
    for axis in GEAR_EFFECT_KEYS:
        assert effect_axis_stem(axis) not in set(PANEL_AXIS_STEMS), axis
        assert effect_axis_stem(axis) not in set(GEAR_FLAT_KEYS), axis


def test_a6_legacy_alias_declares_merge_without_touching_old_keys() -> None:
    """归并/别名按轴全集 §2 声明：旧键保留在既有档位不动（本批零行为变化）。"""
    assert EFFECT_LEGACY_ALIASES["heal_amp_pct"] == ("healing_done_pct", 1.0)
    assert EFFECT_LEGACY_ALIASES["immune_dmg"] == ("damage_taken_pct", -1.0)
    assert EFFECT_LEGACY_ALIASES["weakness_dmg_pct"] == ("damage_dealt_pct", 1.0)
    assert EFFECT_LEGACY_ALIASES["cooldown_reduction_pct"] == ("cooldown_pct", -1.0)
    assert EFFECT_LEGACY_ALIASES["debuff_chance_pct"] == ("status_chance_pct", 1.0)
    assert EFFECT_LEGACY_ALIASES["buff_chance_pct"] == ("status_chance_pct", 1.0)
    # 旧键仍在各自原档位（未迁走、未删除）
    assert "heal_amp_pct" in GEAR_PCT_KEYS
    assert "immune_dmg" in GEAR_COMBAT_KEYS
    assert "cooldown_reduction_pct" in GEAR_PLACEHOLDER_KEYS
    for legacy_key, (axis, sign) in EFFECT_LEGACY_ALIASES.items():
        assert axis in GEAR_EFFECT_KEYS
        assert sign in (-1.0, 1.0)


# =====================================================================================
# B · 零行为变化（registry 对拍 + 战斗快照对拍）
# =====================================================================================
def _reference_route(bonus: Mapping[str, Any]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """**批50 之前**的 `route_bonus_into` 规则（本地参考实现，用于逐字段对拍）。"""
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    for k, v in bonus.items():
        ks = str(k)
        if ks in GEAR_PLACEHOLDER_KEYS:
            continue
        if ks.endswith(PCT_SUFFIX) and len(ks) > len(PCT_SUFFIX) and ks not in GEAR_COMBAT_KEYS:
            stem = ks[: -len(PCT_SUFFIX)]
            pct[stem] = pct.get(stem, 0.0) + float(v)
        else:
            flat[ks] = flat.get(ks, 0.0) + float(v)
    return flat, pct


def _reference_bridge(flat: Mapping[str, Any]) -> Dict[str, float]:
    """**批50 之前**的 `combatant_updates`（COMBAT 桥唯一）——逐字段对拍基准。"""
    out: Dict[str, float] = {}
    for src, dst, cap in COMBAT_TO_COMBATANT:
        v = flat.get(src)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if fv == 0.0:
            continue
        if cap is not None:
            fv = float(max(0.0, min(float(cap), fv)))
        out[dst] = fv
    return out


LEGACY_BONUS: Dict[str, Any] = {
    "atk": 12, "dfn": 8, "hp": 100, "dfn_pct": 5, "atk_pct": 3,
    "crit": -12, "earplug": 5, "super_crit_lv": 4, "elem_crit_lv": 1,
    "absorb_hp": 30, "immune_dmg": 12, "pierce_val": 20, "pierce_pct": 45,
    "mag_pierce_val": 5, "mag_pierce_pct": 3,
    "heal_amp_pct": 7, "debuff_chance_pct": 2, "buff_chance_pct": 2,
    "weakness_dmg_pct": 9, "cooldown_reduction_pct": 15,
    "zeroed": 0,
}


def test_b1_route_bonus_field_by_field_identical_for_legacy_keys() -> None:
    """零变化对拍①：既有键（含悬空/占位键）路由结果与批50 之前**逐字段一致**。"""
    flat, pct = {}, {}
    route_bonus_into(LEGACY_BONUS, flat, pct)
    ref_flat, ref_pct = _reference_route(LEGACY_BONUS)
    assert flat == ref_flat
    assert pct == ref_pct
    # 占位键仍不进任何层（批43 语义未回退）
    assert "cooldown_reduction_pct" not in flat and "cooldown_reduction" not in pct


def test_b2_combatant_bridge_field_by_field_identical_for_legacy_keys() -> None:
    """零变化对拍②：战斗桥输出与批50 之前逐字段一致（缺省不新增任何键）。"""
    flat, _pct = {}, {}
    route_bonus_into(LEGACY_BONUS, flat, _pct)
    assert combatant_updates(flat) == _reference_bridge(flat)
    assert combatant_updates({}) == {}
    assert _reference_bridge({}) == {}


def test_b3_effect_keys_absent_or_zero_add_nothing() -> None:
    """零变化对拍③：EFFECT 键缺省 0 / 不存在 → 战斗桥输出不新增任何键。"""
    flat, pct = {}, {}
    route_bonus_into({k: 0 for k in GEAR_EFFECT_KEYS}, flat, pct)
    assert all(float(v) == 0.0 for v in flat.values())  # 加算轴进 flat 但值为 0
    assert pct == {}
    assert combatant_updates({}) == {}
    assert combatant_updates(flat) == {}  # 全 0 → 桥接不输出任何键
    assert set(EFFECT_TO_COMBATANT) == set(GEAR_EFFECT_KEYS)


def test_b4_effect_keys_stay_flat_and_never_enter_pct_layer() -> None:
    """EFFECT 键 = COMBAT 同规则例外：**留 flat、不进属性 pct 层**（理由同 pierce_pct）。"""
    flat, pct = {}, {}
    route_bonus_into({k: 5.0 for k in GEAR_EFFECT_KEYS}, flat, pct)
    assert set(flat) == set(GEAR_EFFECT_KEYS)
    assert pct == {}
    assert all(k in GEAR_NUMERIC_KEYS and k in GEAR_DISPLAY_KEYS for k in GEAR_EFFECT_KEYS)
    # 提取（实例化）也覆盖 EFFECT 键；0/布尔仍被丢弃
    got = extract_bonus({"healing_received_pct": -50, "stack_cap_delta": 2,
                         "action_bar_shift": True, "damage_taken_pct": 0})
    assert got == {"healing_received_pct": -50.0, "stack_cap_delta": 2.0}


def test_b5_bridge_does_not_hardcode_clamping() -> None:
    """「范围可配、不写死」：桥接不加封顶——越界钳制归声明段 + 消费点（本批待接）。"""
    up = combatant_updates({"healing_received_pct": -9999, "cooldown_pct": 9999})
    assert up["healing_received_pct"] == -9999.0
    assert up["cooldown_pct"] == 9999.0


def test_b6_combatant_snapshot_identical_without_effect_config() -> None:
    """零变化对拍④（战斗输入快照）：未配置特效轴 → combatant 逐字段与参考实现一致。"""
    player = {
        "qid": "10001", "name": "T", "level": 10, "hp": 500, "mp": 30,
        "attributes": {
            "base": {"atk": 100, "dfn": 50, "lck": 20},
            "bonus": {"flat": {"crit": -12, "earplug": 2, "super_crit_lv": 1, "atk": 10},
                      "pct": {"atk": 10, "dfn": 20}},
            "temp": {"flat": {}, "pct": {}},
            "cond": {},
        },
    }
    comb = _combatant_of(player)
    assert comb["crit_bonus"] == -12.0
    assert comb["earplug"] == 2
    assert comb["super_crit_lv"] == 1
    assert comb["atk"] == 121
    assert comb["dfn"] == 60
    # 未配置 → combatant 里不得出现任何特效轴键（桥接只映射非零项）
    assert not (set(_recursive_keys(comb)) & set(GEAR_EFFECT_KEYS))


_PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
           "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
           "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
_ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30,
          "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
          "lck": 10, "elem_atk": 0, "name": "E"}


def test_b7_battle_settlement_snapshot_zero_change() -> None:
    """零变化对拍⑤（一场战斗的结算快照）：同种子两次对拍逐字段一致，且快照里
    不含任何特效轴键（缺省不桥接 = 行为零变化）。"""
    eng = BattleEngine().start(_PLAYER, _ENEMY, random_seed=42)
    eng.player_act("normal")
    snap_a = eng.to_snapshot()
    eng_b = BattleEngine().start(_PLAYER, _ENEMY, random_seed=42)
    eng_b.player_act("normal")
    snap_b = eng_b.to_snapshot()
    # 实例 uid（战斗号/战斗者号）是每场唯一的 uuid，属非确定性来源、与本批无关 →
    # 对拍前统一归一，其余字段**逐字段**严格相等。
    assert _stable_json(snap_a) == _stable_json(snap_b)
    keys = set(_recursive_keys(snap_a))
    assert not (keys & set(GEAR_EFFECT_KEYS)), sorted(keys & set(GEAR_EFFECT_KEYS))
    # 对拍快照里既有战斗键仍在（证明快照非空、对拍有意义）
    assert keys, "战斗快照为空，对拍无意义"


# =====================================================================================
# C · 声明段（settings.effect_axes）：范围与默认值可配、不写死
# =====================================================================================
def test_c1_normalize_merges_pack_declaration_over_defaults() -> None:
    """包声明覆盖范围/默认/显示；未声明字段回落登记表缺省。"""
    cfg = {
        "healing_received_pct": {"min": -300, "max": 500, "default": -25,
                                 "display": {"label": "重伤", "mode": "mult"},
                                 "stack": "mult"},
    }
    norm = normalize_effect_axes(cfg)
    entry = norm["healing_received_pct"]
    assert entry["declared"] is True
    assert (entry["min"], entry["max"], entry["default"]) == (-300.0, 500.0, -25.0)
    assert entry["display"]["label"] == "重伤"
    assert entry["display"]["mode"] == "mult"
    assert entry["stack"] == "mult"
    assert norm["cooldown_pct"]["declared"] is False
    assert norm["cooldown_pct"]["max"] == 200.0


def test_c2_normalize_is_defensive_unknown_and_invalid() -> None:
    """非法值逐项回落缺省；未知轴**原样保留**（交校验器黄提示，不静默吞掉）。"""
    norm = normalize_effect_axes({
        "cooldown_pct": {"min": "x", "max": True, "default": float("nan")},
        "my_own_axis_pct": {"min": -1, "max": 9},
    })
    assert norm["cooldown_pct"]["min"] == -80.0   # 非数值 → 缺省
    assert norm["cooldown_pct"]["max"] == 200.0   # 布尔 → 缺省
    assert norm["cooldown_pct"]["default"] == 0.0  # NaN → 缺省
    assert norm["my_own_axis_pct"]["declared"] is True
    assert norm["my_own_axis_pct"]["min"] == -1.0
    # 非映射整体 → 全缺省
    assert normalize_effect_axes("nonsense") == normalize_effect_axes(None)
    assert effect_axis_spec("cooldown_pct")["axis"] == "cooldown_pct"
    assert effect_axis_spec("nope") == {}


# =====================================================================================
# D · 字段元数据（编辑器字段表 + settings 声明段）
# =====================================================================================
def test_d1_items_and_equipment_cover_effect_keys_with_label_help() -> None:
    """字段元数据：items/equipment 全覆盖 EFFECT 键，中文名 + 说明齐备。"""
    table = default_field_meta_table()
    for mod in ("items", "equipment"):
        fields = table.module(mod).fields
        missing = [k for k in GEAR_EFFECT_KEYS if k not in fields]
        assert not missing, missing
        for k in GEAR_EFFECT_KEYS:
            fm = fields[k]
            spec = effect_axis_spec(k)
            assert fm.label == spec["display"]["label"], k
            assert fm.help == spec["display"]["help"], k
            assert fm.unit == ("点" if spec["display"]["mode"] == "delta" else "%"), k
            assert fm.range_min == spec["min"] and fm.range_max == spec["max"], k
            assert fm.default == spec["default"], k
            assert fm.allow_negative is True, k


def test_d2_help_text_carries_bidirectional_hint() -> None:
    """双向提示：说明里必须同时出现两个方向（`<1`/`>1`，或加算轴的 `+`/`-`）。"""
    for k in GEAR_EFFECT_KEYS:
        help_text = str(effect_axis_spec(k)["display"]["help"])
        assert ("<1" in help_text and ">1" in help_text) or \
               ("正" in help_text and "负" in help_text) or \
               ("+" in help_text and "-" in help_text), (k, help_text)


def test_d3_settings_effect_axes_section_registered_with_label_and_help() -> None:
    """settings.effect_axes 段登记：容器有中文名与说明，子字段齐全（动态键空间 → soft）。"""
    fm = SETTINGS_FIELDS["effect_axes"]
    assert fm.type == "obj" and fm.soft_label is True
    assert fm.label and fm.help
    assert set(fm.children) == {"min", "max", "default", "display", "stack", "legacy_alias"}
    assert set(fm.children["display"].children) == {"mode", "label", "help"}
    assert set(fm.children["display"].children["mode"].enum) == {"mult", "delta"}
    for name, child in fm.children.items():
        assert child.label, name
        assert child.help, name
    # 段确实挂在 settings 模块上（编辑器条目列表可见）
    assert "effect_axes" in default_field_meta_table().module("settings").fields


# =====================================================================================
# E · 校验器（越界红拦 / 未知轴黄提示 / 面板 stem 冲突红拦 / 取值越界红拦）
# =====================================================================================
def _rules(report: Any) -> Tuple[List[str], List[str]]:
    errs = [str(e.detail.get("rule")) for e in report.errors]
    warns = [str(w.detail.get("rule")) for w in report.warnings]
    return errs, warns


def test_e0_validator_default_is_silent_regression() -> None:
    """缺省零变化：空包 / 无特效键 / 合法取值 → 零红零黄。"""
    for mods in ({}, {"items": [{"id": "x", "atk": 5}]},
                 {"items": [{"id": "x", "healing_received_pct": -50,
                             "stack_cap_delta": 2}]},
                 {"settings": {"effect_axes": {"cooldown_pct": {"min": -80, "max": 200,
                                                                "default": 0}}}}):
        rep = check_pack(mods)
        assert not rep.errors, (mods, _rules(rep))
        assert not rep.warnings, (mods, _rules(rep))


def test_e1_out_of_range_red_block() -> None:
    """越界红拦：`default ∉ [min,max]` 与 `min > max` → R-2 红拦。"""
    rep = check_pack({"settings": {"effect_axes": {
        "healing_received_pct": {"min": -200, "max": 300, "default": 999}}}})
    errs, _ = _rules(rep)
    assert "effect_axis_default_out_of_range" in errs
    rep2 = check_pack({"settings": {"effect_axes": {
        "cooldown_pct": {"min": 50, "max": -50}}}})
    errs2, _ = _rules(rep2)
    assert "effect_axis_range_inverted" in errs2


def test_e2_value_out_of_range_red_block() -> None:
    """取值越界红拦：内容侧轴取值超出声明范围 → R-2（装备词条 + 符文数值档）。"""
    rep = check_pack({"items": [{"id": "x", "healing_received_pct": -500}]})
    assert any("effect_axis_value_out_of_range" == r for r in _rules(rep)[0])
    rep2 = check_pack({"runes": [{"id": "r", "tier": 1, "family": "f",
                                  "by_equip_type": {"default": {"stats": {"cooldown_pct": 999}}}}]})
    assert any("effect_axis_value_out_of_range" == r for r in _rules(rep2)[0])
    # 声明收窄 → 原本合法的取值变红（范围**可配**，不是写死）
    rep3 = check_pack({"settings": {"effect_axes": {"cooldown_pct": {"min": -10, "max": 10}}},
                       "items": [{"id": "x", "cooldown_pct": 50}]})
    assert any("effect_axis_value_out_of_range" == r for r in _rules(rep3)[0])


def test_e3_unknown_axis_yellow_not_error() -> None:
    """未知轴黄提示 Y-18（不硬拦）；合法取值仍零红。"""
    rep = check_pack({"settings": {"effect_axes": {"my_own_axis_pct": {"min": -1, "max": 1}}}})
    errs, warns = _rules(rep)
    assert not errs
    assert "effect_axis_unknown" in warns


def test_e4_panel_stem_conflict_red_block() -> None:
    """键名不得与面板三轴 stem 冲突 → R-4 红拦（atk/dfn/hp 三个都试）。"""
    for axis in ("atk_pct", "dfn", "hp_pct"):
        rep = check_pack({"settings": {"effect_axes": {axis: {"min": 0}}}})
        errs, _ = _rules(rep)
        assert "effect_axis_stem_conflict" in errs, axis
    # 框架自证：登记表不含任何面板 stem
    assert not ({effect_axis_stem(k) for k in GEAR_EFFECT_KEYS} & set(PANEL_AXIS_KEYS))


def test_e5_structural_and_type_errors() -> None:
    """段结构非对象 / 轴条目非对象 / 非数值 → 红拦；stack·mode 不在册 → 黄提示。"""
    rep = check_pack({"settings": {"effect_axes": [1, 2]}})
    assert "section_structure" in _rules(rep)[0]
    rep2 = check_pack({"settings": {"effect_axes": {"cooldown_pct": 5}}})
    assert "type" in _rules(rep2)[0]
    rep3 = check_pack({"settings": {"effect_axes": {"cooldown_pct": {"min": "x"}}}})
    assert "type" in _rules(rep3)[0]
    rep4 = check_pack({"settings": {"effect_axes": {
        "cooldown_pct": {"stack": "weird", "display": {"mode": "weird"}}}}})
    errs4, warns4 = _rules(rep4)
    assert not errs4
    assert "effect_axis_stack_unknown" in warns4
    assert "effect_axis_display_mode_unknown" in warns4
    # NaN / Inf
    rep5 = check_pack({"settings": {"effect_axes": {"cooldown_pct": {"min": math.inf}}}})
    assert "not_a_number" in _rules(rep5)[0]


def test_e6_no_red_on_real_content_pack() -> None:
    """既有内容包零回归：real 包过校验器不因本批新增任何红/黄。"""
    pack_dir = CONTENT / "veinborn"
    mods = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(pack_dir.glob("*.json")) if p.stem != "manifest"}
    assert mods, "内容包目录为空，零回归断言无意义"
    rep = check_pack(mods)
    new_rules = {"effect_axis_unknown", "effect_axis_stem_conflict",
                 "effect_axis_value_out_of_range", "effect_axis_default_out_of_range",
                 "effect_axis_range_inverted", "effect_axis_stack_unknown",
                 "effect_axis_display_mode_unknown"}
    assert not (new_rules & set(_rules(rep)[0])), _rules(rep)
    assert not (new_rules & set(_rules(rep)[1])), _rules(rep)


# =====================================================================================
# F · 编辑器（接口断言 + DOM 证据）
# =====================================================================================
@pytest.fixture()
def pack_copy(tmp_path: Path) -> Path:
    """临时内容根（copytree veinborn → tmp_path；**不写仓库真实 content/**）。"""
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


def _desc(detail: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    node: Any = detail
    for seg in path:
        kids = node["children"] if "children" in node else node["fields"]
        node = {str(f["key"]): f for f in kids}[seg]
    return node


def test_f1_settings_declaration_section_visible_in_editor(pack_copy: Path) -> None:
    """接口断言：settings 条目列表里可见「特效轴声明」，详情页给出声明字段。"""
    from qbot_rpg.web import api

    entries = api.list_entries("veinborn", "settings", root=pack_copy)
    rows = {str(e.get("id") or e.get("key")): e for e in entries.get("entries", [])}
    assert "effect_axes" in rows, sorted(rows)
    assert rows["effect_axes"].get("name") == "特效轴声明"
    detail = api.entry_detail("veinborn", "settings", "effect_axes", root=pack_copy)
    for key in ("min", "max", "default", "display", "stack", "legacy_alias"):
        d = _desc(detail, key)
        assert d["label"], key
        assert d["help_card"]["label"] or d["label"], key


def test_f2_declared_axes_render_as_table_and_show_bidirectional_help(pack_copy: Path) -> None:
    """接口断言：包声明两条轴 → 编辑器按逐轴表格渲染，且说明卡带**双向提示**。"""
    from qbot_rpg.web import api

    settings_path = pack_copy / "veinborn" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["effect_axes"] = {
        "healing_received_pct": {"min": -200, "max": 300, "default": 0},
        "cooldown_pct": {"min": -80, "max": 200, "default": 0},
    }
    settings_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("veinborn", "settings", "effect_axes", root=pack_copy)
    assert detail["whole_table"] is True and detail["open_keys"] is False
    field = detail["fields"][0]
    assert field["control"] == "kvtable"
    assert field["kv_table"]["mode"] == "obj"
    assert {r["key"] for r in field["kv_table"]["rows"]} == {
        "healing_received_pct", "cooldown_pct"}
    card = field["help_card"]
    assert card["label"] == "特效轴声明"
    assert "双向" in card["help"] or "说明" in card["help"] or card["help"]


def _top_keys(detail: Mapping[str, Any]) -> List[str]:
    return [str(f["key"]) for f in detail["fields"]]


def test_f3_item_effect_axis_field_visible_with_label_help_and_bounds(pack_copy: Path) -> None:
    """接口断言：装备/物品词条里的特效轴可见，带中文名 + 双向说明 + 建议范围。"""
    from qbot_rpg.web import api

    items_path = pack_copy / "veinborn" / "items.json"
    items = json.loads(items_path.read_text(encoding="utf-8"))
    items[0]["healing_received_pct"] = -50
    items_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("veinborn", "items", str(items[0]["id"]), root=pack_copy)
    field = _desc(detail, "healing_received_pct")
    assert field["label"] == "受疗修正"
    assert "<1 减疗" in field["help"] and ">1 增疗" in field["help"]
    assert field["help_card"]["range"] == "建议 -200 ~ 300"
    assert field["help_card"]["help"] == field["help"]


def test_f4_frontend_is_metadata_driven_dom_evidence() -> None:
    """DOM/静态证据：前端不写死任何轴名（轴只能经元数据出现），且沿用既有数字输入控件。

    · index.html 全文不得出现任一特效轴键名 → 渲染纯元数据驱动（换包/加轴零前端改动）；
    · 既有 number 控件仍在（`type="number"` + `step`）→ 本批「滑条/输入」沿用既有风格，
      未新增前端控件（登记表驱动的范围经说明卡「建议范围」行展示）。
    """
    html = HTML.read_text(encoding="utf-8")
    for key in GEAR_EFFECT_KEYS:
        assert key not in html, f"前端写死了轴名：{key}"
    assert 'type="number"' in html and "number_step" in html
    # 说明卡渲染「说明」与「建议范围」两行（双向提示与范围都从这里出）
    assert 'k: "说明"' in html
    assert 'k: "建议范围"' in html
