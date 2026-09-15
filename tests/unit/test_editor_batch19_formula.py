"""编辑器重写批19 · 段 C：formula 区域翻译（用户 #9）。

用户反馈 #9：包 `formula.json` 的键 `damage_base` / `heal_rate` / `battle_position`
（含嵌套 `break_base_damage` 等）**框架与包都无中文名**。

本批口径：
  · 按 `qbot_rpg/core/formula_loader.py` 的**实际消费面**逐键登记中文名（不臆造）；
  · `battle_position.*` 的中文名与 `core/damage.py::BattlePositionParams` 字段一一对应
    （结构性断言，键名漂移会红）；
  · `damage_base` / `heal_rate` 是既有包普遍存在的兼容键（当前 Python 侧不消费）→
    如实登记 + help 写明现状，不冒充「已消费」；
  · 包侧可用 `field_meta.json` 的 `field_labels.formula` 覆盖中文名。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from qbot_rpg.core.damage import BattlePositionParams
from qbot_rpg.core.formula_loader import load_formula_params
from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"


def _formula_fields() -> dict:
    mmeta = api.default_field_meta_table().module("formula")
    assert mmeta is not None
    return dict(mmeta.fields)


# =====================================================================================
# A · 登记 + 中文名
# =====================================================================================
def test_named_formula_keys_registered_with_chinese_labels() -> None:
    fields = _formula_fields()
    for key, label in (("damage_base", "伤害基础公式"), ("heal_rate", "治疗量公式"),
                       ("battle_position", "方位战斗参数"), ("monster_def_rate", "怪物防御率")):
        assert key in fields, key
        assert fields[key].label == label, (key, fields[key].label)


def test_battle_position_children_match_consumed_dataclass() -> None:
    """battle_position 子键 = BattlePositionParams 字段（不臆造、不遗漏消费面）。"""
    bp = _formula_fields()["battle_position"]
    assert bp.type == "obj"
    assert set(bp.children) == set(BattlePositionParams.__dataclass_fields__)
    for key, fm in bp.children.items():
        assert fm.label and fm.label != key, key


def test_consumed_loader_sections_still_registered() -> None:
    """load_formula_params 消费的全部顶层段/键都在登记表内（可核到的都登记，不臆造）。"""
    fields = _formula_fields()
    data = json.loads((CONTENT / "veinborn" / "formula.json").read_text(encoding="utf-8"))
    data = dict(data)
    # 让读取器把每段都实际走一遍（缺省回退也算消费）
    from qbot_rpg.core.damage import DamageFormulaParams
    for seg in ("damage", "hit", "crit", "block", "battle_position", "defense",
                "weakness", "type_affinity", "derived", "stat_map"):
        assert seg in fields, seg
        assert isinstance(data.get(seg), (dict, type(None))), seg
    # crit 的两个 E19/E21 键按消费面补齐
    crit_children = fields["crit"].children
    assert "negative_crit" in crit_children and "elem_crit_step" in crit_children
    # 读取器本身不因登记而改变（结构与默认值不变）
    assert isinstance(load_formula_params(data), DamageFormulaParams)


def test_no_fabricated_keys() -> None:
    """登记的新键必须真实存在于消费面：damage_base/heal_rate 是包内既有键。"""
    data = json.loads((CONTENT / "veinborn" / "formula.json").read_text(encoding="utf-8"))
    assert "damage_base" in data and "heal_rate" in data and "battle_position" in data
    assert set(data["battle_position"]) == set(BattlePositionParams.__dataclass_fields__)


# =====================================================================================
# B · 编辑器实测：三个键的中文名都出现
# =====================================================================================
def test_entry_detail_translates_actual_formula_keys() -> None:
    for key, label in (("damage_base", "伤害基础公式"), ("heal_rate", "治疗量公式")):
        d = api.entry_detail("veinborn", "formula", key, root=CONTENT)
        assert [f["label"] for f in d["fields"]] == [label], key
    bp = api.entry_detail("veinborn", "formula", "battle_position", root=CONTENT)
    labels = {f["key"]: f["label"] for f in bp["fields"]}
    assert labels == {
        "break_base_damage": "基准伤害",
        "break_sqrt_coef": "根号系数",
        "broken_part_mult": "已破部位增伤乘区",
    }


def test_compat_keys_help_states_not_consumed() -> None:
    fields = _formula_fields()
    assert "未消费" in fields["damage_base"].help or "不消费" in fields["damage_base"].help
    assert "不消费" in fields["heal_rate"].help


# =====================================================================================
# C · 包侧覆盖（field_labels.formula）
# =====================================================================================
def test_pack_field_labels_override_formula(tmp_path: Path) -> None:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    pm = tmp_path / "veinborn" / "field_meta.json"
    decl = json.loads(pm.read_text(encoding="utf-8"))
    decl.setdefault("field_labels", {})["formula"] = {"damage_base": "包内伤害基式"}
    pm.write_text(json.dumps(decl, ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("veinborn", "formula", "damage_base", root=tmp_path)
    assert d["fields"][0]["label"] == "包内伤害基式"
