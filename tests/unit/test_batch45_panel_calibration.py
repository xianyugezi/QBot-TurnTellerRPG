"""批45 · 装备占比校准（40% → 60%）单测：参数化 / 斩回不变 / 回归对拍 / 编辑器 / 校验器。

依据：`docs/深度打造_决策记录.md` §三 补充 1（装备 8→18 ×2.25；白值 7/buff 5 不动；
面板总功率 20→30 ⇒ 怪物侧同比例重校，目标 = 保持既有斩杀回合数）。

覆盖：
  A. **占比口径**：装备预算占比 1.0→40%、2.25→60%（±1%）；白值份/buff 份冻结。
  B. **装备面板倍率**：只乘面板轴 atk/dfn/hp（flat + 对应 pct）；战斗词条/其余属性**不动**；
     缺省/1.0 → 与既有聚合**逐字段一致**（回归对拍）。
  C. **怪物数值倍率**：hp/atk ×比例；con 仿射补偿 `(con+K)×f−K`；其余键不动；缺省 → 原值。
  D. **斩回不变式**：中值（半buff）档，装备 ×2.25 + 怪物 ×1.5 + con 补偿 → 三只代表怪斩回相同。
  E. **编辑器可见**：settings.panel_budget / monster_scaling 元数据（中文名 + 说明）。
  F. **校验器**：合法 → 0 错；结构/类型/负值 → 红拦。

测试只构造内存数据，不写任何真实内容包。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from qbot_rpg.commands.battle_launch_commands import _enemy_combatant
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.damage import defense_factor
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.panel_budget import (
    PANEL_AXIS_KEYS,
    equip_share,
    normalize_monster_scaling,
    normalize_panel_budget,
    scale_monster_con,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.gear_stats import route_bonus_into
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes

SLOTS: Dict[str, Any] = {
    "weapon": {"name": "武器", "max": 1},
    "head": {"name": "头部", "max": 1},
}

#: 校准样本（与 scripts/batch45_measure.py 同口径；lv35 白值 + 毕业装）
WHITE = {"atk": 360.0, "dfn": 251.0, "hp": 808.0}
EQUIP = {"atk": 486.0, "dfn": 61.0, "hp": 0.0, "crit": 2.0, "atk_pct": 5.0,
         "dfn_pct": 3.0, "agi": 3.0}
BUFF_HALF = 360.0 / 7.0 * 5.0 * 0.5          # 半档 buff atk ≈ 128.571
MULT = 2.25                                   # 批45 校准倍率（装备预算 8→18）


def _item(item_id: str, slot: str, stats: Dict[str, float]) -> ItemInstance:
    return ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                        bound=False, stack_max=1, slot=slot, stats_bonus=dict(stats))


def _player(rows: List[ItemInstance], base: Dict[str, float]) -> Dict[str, Any]:
    return {"inventory": list(rows), "equipment": {},
            "attributes": PlayerAttributes(base=dict(base))}


def _agg(stats: Dict[str, float], slot: str, panel_budget: Any) -> Dict[str, Any]:
    eng = EquipmentEngine(slots=SLOTS, panel_budget=panel_budget)
    row = _item("gear", slot, stats)
    p = _player([row], {})
    assert eng.equip(p, row, slot)["ok"] is True
    return eng.aggregate_bonus(p)


# ---------------------------------------------------------------------------
# A. 占比口径
# ---------------------------------------------------------------------------
def test_equip_share_default_is_40pct_and_calibrated_is_60pct() -> None:
    """装备占比：缺省 7:8:5 → 40.00%；equip_stat_mult=2.25 → 18/30 = 60.00%（±1%）。"""
    assert abs(equip_share(None) - 0.40) < 1e-9
    assert abs(equip_share({"equip_stat_mult": MULT}) - 0.60) < 1e-9
    share = equip_share({"equip_stat_mult": MULT})
    assert abs(share - 0.60) <= 0.01, "装备占比必须落在 60% ±1%"


def test_panel_budget_normalize_freezes_white_and_buff() -> None:
    """白值份 / buff 份冻结（不随倍率变化）；缺省/非法 → 现状。"""
    b = normalize_panel_budget({"white": 7, "equip": 8, "buff": 5, "equip_stat_mult": MULT})
    assert (b["white"], b["equip"], b["buff"]) == (7.0, 8.0, 5.0)
    d = normalize_panel_budget(None)
    assert d["equip_stat_mult"] == 1.0 and (d["white"], d["equip"], d["buff"]) == (7.0, 8.0, 5.0)
    bad = normalize_panel_budget({"white": "x", "equip": -3, "equip_stat_mult": True})
    assert bad["white"] == 7.0 and bad["equip"] == 8.0 and bad["equip_stat_mult"] == 1.0


# ---------------------------------------------------------------------------
# B. 装备面板倍率
# ---------------------------------------------------------------------------
def test_equip_multiplier_scales_only_panel_axes() -> None:
    """×2.25 只乘 atk/dfn/hp（含 _pct）；crit/agi 等战斗与其余属性不动。"""
    base = _agg(EQUIP, "weapon", {"equip_stat_mult": MULT})
    assert base["flat"]["atk"] == EQUIP["atk"] * MULT
    assert base["flat"]["dfn"] == EQUIP["dfn"] * MULT
    assert base["flat"]["crit"] == EQUIP["crit"]          # 战斗词条不动
    assert base["flat"]["agi"] == EQUIP["agi"]            # 其余属性不动
    assert base["pct"]["atk"] == EQUIP["atk_pct"] * MULT  # pct 面板轴
    assert base["pct"]["dfn"] == EQUIP["dfn_pct"] * MULT


def test_equip_multiplier_default_is_noop_regression() -> None:
    """缺省 / 显式 1.0 → 与既有聚合口径逐字段一致（回归对拍）。"""
    raw_flat: Dict[str, float] = {}
    raw_pct: Dict[str, float] = {}
    route_bonus_into(EQUIP, raw_flat, raw_pct)
    for cfg in (None, {"equip_stat_mult": 1.0}, {}):
        agg = _agg(EQUIP, "weapon", cfg)
        assert agg["flat"] == raw_flat
        assert agg["pct"] == raw_pct


def test_equip_multiplier_does_not_change_final_attributes_when_default() -> None:
    """缺省倍率下最终属性与手算一致（白值 + 原始装备加成）。"""
    row = _item("gear", "weapon", {"atk": 100.0, "crit": 2.0})
    eng = EquipmentEngine(slots=SLOTS)
    p = _player([row], {"atk": 20.0})
    assert eng.equip(p, row, "weapon")["ok"] is True
    final = calc_all_final_attributes(p["attributes"])
    assert final["atk"] == 120 and final.get("crit", 0) == 2


# ---------------------------------------------------------------------------
# C. 怪物数值倍率
# ---------------------------------------------------------------------------
def test_monster_scaling_default_is_identity() -> None:
    """缺省/非映射 → hp/atk/con 原值（与本批引入前一致）。"""
    entry = {"id": "m", "stats": {"hp": 1000, "str": 200, "con": 150, "agi": 10, "foc": 20}}
    for sc in (None, {}, {"hp_mult": 1.0, "atk_mult": 1.0, "def_factor": 1.0}):
        c = _enemy_combatant(entry, sc)
        assert (c["hp"], c["max_hp"], c["atk"], c["con"], c["dfn"]) == (1000, 1000, 200, 150, 150)
        assert (c["agi"], c["foc"]) == (10, 20)
    # 原语义保留：仅 dfn 无 con → con=10（兜底）、dfn=dfn
    c2 = _enemy_combatant({"id": "m2", "stats": {"hp": 100, "str": 10, "dfn": 77}})
    assert c2["con"] == 10 and c2["dfn"] == 77


def test_monster_scaling_hp_atk_and_con_compensation() -> None:
    """hp/atk ×1.5；con 仿射补偿 (con+K)×f−K；其余键不动。"""
    entry = {"id": "m", "stats": {"hp": 1000, "str": 200, "con": 150, "agi": 10, "foc": 20}}
    sc = {"hp_mult": 1.5, "atk_mult": 1.5, "def_factor": 1.0828}
    c = _enemy_combatant(entry, sc)
    assert (c["hp"], c["max_hp"], c["atk"]) == (1500, 1500, 300)
    assert c["con"] == round(scale_monster_con(150, 1.0828, 100.0))
    assert c["dfn"] == c["con"]
    assert (c["agi"], c["foc"]) == (10, 20)   # 命中/闪避/格挡参数不动


def test_monster_scaling_normalize_defaults() -> None:
    """缺省 def_k=100；非法回落 1.0（批55 追加方案 C 两键，缺省 1.0 = 现状）。"""
    d = normalize_monster_scaling(None)
    assert d == {"hp_mult": 1.0, "atk_mult": 1.0, "def_factor": 1.0, "def_k": 100.0,
                 "effect_hp_mult": 1.0, "effect_atk_mult": 1.0}
    assert normalize_monster_scaling({"hp_mult": "x", "def_factor": -1})["hp_mult"] == 1.0
    assert normalize_monster_scaling({"def_factor": -1})["def_factor"] == 1.0
    # 批55：方案 C 缺省 1.0（不配置即不存在）；非法同样回落 1.0。
    assert normalize_monster_scaling({"effect_hp_mult": -2})["effect_hp_mult"] == 1.0
    assert normalize_monster_scaling({"effect_atk_mult": "x"})["effect_atk_mult"] == 1.0


# ---------------------------------------------------------------------------
# D. 斩回不变式（本批硬指标）
# ---------------------------------------------------------------------------
#: (hp, con) 三只代表怪：普通 / 精英 / Boss（真实内容口径，见测量报告 §1.1）
MONSTERS = ((2524, 154), (4285, 344), (4733, 376))


def _turns(atk: float, hp: float, con: float) -> int:
    d = max(1, math.floor(atk * defense_factor(con)))
    return math.ceil(hp / d)


def test_kill_turns_preserved_after_calibration() -> None:
    """中值档：装备 ×2.25（面板 +62%）+ 怪物 hp ×1.5、con 补偿 → 斩回逐只不变。

    反解 `def_factor = R/1.5`（R = 面板 atk 实测比值）；断言三只怪斩回完全相同。
    """
    panel_pre = int(WHITE["atk"] + EQUIP["atk"] + BUFF_HALF)
    panel_post = int(WHITE["atk"] + EQUIP["atk"] * MULT + BUFF_HALF)
    r = panel_post / panel_pre
    def_factor = r / 1.5
    assert abs(def_factor - 1.0828) < 5e-3, "补偿系数应与校准值一致"
    for hp, con in MONSTERS:
        con_post = scale_monster_con(con, def_factor, 100.0)
        pre = _turns(panel_pre, hp, con)
        post = _turns(panel_post, hp * 1.5, con_post)
        assert pre == post, f"斩回必须不变：hp={hp} con={con} {pre}→{post}"


def test_white_and_buff_absolute_values_unchanged() -> None:
    """白值 / buff 绝对数值不变（装备倍率只作用于装备）。"""
    def _final(panel_budget: Any) -> Dict[str, int]:
        eng = EquipmentEngine(slots=SLOTS, panel_budget=panel_budget)
        # 直接用引擎聚合口径（单武器槽）
        row = _item("gear", "weapon", {"atk": EQUIP["atk"]})
        pl = _player([row], dict(WHITE))
        assert eng.equip(pl, row, "weapon")["ok"] is True
        eng.aggregate_bonus(pl)
        pl["attributes"].temp["flat"] = {"atk": BUFF_HALF}
        return calc_all_final_attributes(pl["attributes"])

    pre = _final(None)
    post = _final({"equip_stat_mult": MULT})
    assert pre["hp"] == post["hp"] == WHITE["hp"]
    assert pre["dfn"] == 251 and post["dfn"] == 251        # 无装备 dfn → 不变
    # 白值 + buff 不变：扣掉各自装备增量后，剩余（白值+buff）一致（出口 floor 容差 1）
    pre_rest = pre["atk"] - EQUIP["atk"]
    post_rest = post["atk"] - EQUIP["atk"] * MULT
    assert abs(pre_rest - post_rest) <= 1.0


# ---------------------------------------------------------------------------
# E. 编辑器可见
# ---------------------------------------------------------------------------
def test_editor_metadata_has_panel_budget_and_monster_scaling() -> None:
    """编辑器可见：面板预算 + 怪物数值倍率（中文名 + 说明齐备）。"""
    table = default_field_meta_table()
    meta = table.module("settings")
    assert meta is not None
    pb = meta.fields["panel_budget"]
    assert pb.type == "obj" and pb.label and pb.help
    assert pb.children["equip_stat_mult"].label == "装备面板倍率"
    assert pb.children["equip_stat_mult"].help
    for k in ("white", "equip", "buff"):
        assert pb.children[k].label and pb.children[k].help
    ms = meta.fields["monster_scaling"]
    assert ms.type == "obj" and ms.label and ms.help
    for k in ("hp_mult", "atk_mult", "def_factor", "def_k"):
        assert ms.children[k].label and ms.children[k].help


# ---------------------------------------------------------------------------
# F. 校验器
# ---------------------------------------------------------------------------
def test_validator_panel_budget_and_monster_scaling() -> None:
    """合法 → 0 错；结构/类型/负值 → 红拦。"""
    ok = check_pack({"settings": {
        "panel_budget": {"white": 7, "equip": 8, "buff": 5, "equip_stat_mult": 2.25},
        "monster_scaling": {"hp_mult": 1.5, "atk_mult": 1.5, "def_factor": 1.0828},
    }})
    assert [(e.field, e.detail.get("rule")) for e in ok.errors] == []

    bad_struct = check_pack({"settings": {"panel_budget": 3}}).errors
    assert any(e.detail.get("rule") == "section_structure" for e in bad_struct)
    bad_type = check_pack({"settings": {"panel_budget": {"equip": "8"}}}).errors
    assert any(e.field.endswith(".equip") and e.detail.get("rule") == "type" for e in bad_type)
    bad_neg = check_pack({"settings": {"monster_scaling": {"hp_mult": -1}}}).errors
    assert any(e.detail.get("rule") == "value_below_min" for e in bad_neg)
    bad_struct2 = check_pack({"settings": {"monster_scaling": []}}).errors
    assert any(e.detail.get("rule") == "section_structure" for e in bad_struct2)


def test_validator_panel_budget_all_zero_is_warning_not_error() -> None:
    """三份全 0 → 黄提示（不硬拦）。"""
    rep = check_pack({"settings": {"panel_budget": {"white": 0, "equip": 0, "buff": 0}}})
    assert not rep.errors
    assert any(w.detail.get("rule") == "panel_budget_all_zero" for w in rep.warnings)


def test_panel_axis_keys_are_panel_only() -> None:
    """面板轴 = atk/dfn/hp（不含 crit/agi 等）。"""
    assert set(PANEL_AXIS_KEYS) == {"atk", "dfn", "hp"}
