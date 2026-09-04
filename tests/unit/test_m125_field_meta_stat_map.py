"""M12.5 需求1 批D 验证：field_meta/编辑器 stat_map 段字段。

依据：docs/m125_战斗数值动态化方案.md 批 D。
验收：field_meta formula 模块 fields 注入 stat_map 段（编辑器 meta 返回 13 个
中文语义键）；注入零红拦（既有 content 校验全绿）。
"""
from __future__ import annotations

from qbot_rpg.content.field_meta import FORMULA_FIELDS, default_field_meta_table

STAT_MAP_SEMANTIC_KEYS = {
    "hit_focus", "hit_spd", "crit_luck", "block_focus", "def_con",
    "atk_atk", "mag_int", "enemy_str", "enemy_con", "enemy_spr", "enemy_agi",
    "atk_base", "dfn_base",
}


def test_formula_field_meta_has_stat_map_obj() -> None:
    """field_meta formula 模块 fields 含 stat_map（obj + 13 中文子键）。"""
    t = default_field_meta_table()
    mm = t.modules["formula"]
    assert mm.entry_type == "map"
    sm = mm.fields.get("stat_map")
    assert sm is not None and sm.type == "obj"
    assert sm.label == "属性映射"
    assert set(sm.children) == STAT_MAP_SEMANTIC_KEYS
    for key, cmeta in sm.children.items():
        assert cmeta.type == "str"
        assert cmeta.label  # 中文 label 兜底（非技术用户要求）


def test_formula_fields_constant_shallow_copied() -> None:
    """FORMULA_FIELDS 常量引用时外层 dict 新实例（防调用方改外层；FieldMeta frozen 共享零风险）。"""
    t = default_field_meta_table()
    mm = t.modules["formula"]
    assert mm.fields is not FORMULA_FIELDS  # default 表每次新实例、外层不共享
    # 两次 default 表调用互不影响
    t2 = default_field_meta_table()
    assert t2.modules["formula"].fields is not mm.fields
    assert set(t2.modules["formula"].fields) == {"stat_map"}


def test_stat_map_field_meta_validates_pack_ok(legal_pack_dir) -> None:
    """带合法 stat_map 的内容包过 check_pack 零红（C3 黄校验兼容）。"""
    import json

    from qbot_rpg.content.validator import check_pack

    formula_path = legal_pack_dir / "formula.json"
    formula = json.loads(formula_path.read_text(encoding="utf-8"))
    formula["stat_map"] = {"hit_focus": "custom_focus", "crit_luck": "lck"}
    report = check_pack({"formula": formula, "manifest": {
        "name": "t", "version": "1.0.0", "schema_version": 1, "author": "a",
        "modules": ["formula"],
    }}, default_field_meta_table())
    assert not report.errors
