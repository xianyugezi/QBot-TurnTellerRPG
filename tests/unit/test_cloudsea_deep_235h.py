# -*- coding: utf-8 -*-
"""九期批次 235H 定向测试：`深度炼成` 新指令 spec＋并账/settings＋R4/R5 口径。"""
import json
import io
import os
from types import SimpleNamespace

from qbot_rpg.commands import cloudsea_deep_commands as dc

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Router:
    def __init__(self):
        self.specs = {}

    def register(self, spec):
        self.specs[spec.name] = spec


def _lib():
    return json.load(io.open(os.path.join(
        _ROOT, "content", "cloudsea", "recipes.json"), encoding="utf-8"))


def _ctx(**kw):
    base = {"cloudsea_recipes": _lib(), "alchemy_level": 10,
            "cloudsea_consts": {"C.ALCHEMY.DEEP_RANK_STEP": 2,
                                "C.ALCHEMY.DEEP_COST_MULT": 2,
                                "C.ALCHEMY.MASTERY_PER_DEEP": 2,
                                "C.ALCHEMY.LEVEL_MAX": 10}}
    base.update(kw)
    return base


def _parsed(args):
    return SimpleNamespace(command="深度炼成", args=list(args), error=None)


# ---------------------------------------------------------------- R5 词面


def test_face_no_clash_with_framework_deep():
    """R5：`深度炼成` ≠ 框架旧词「深度炼金」（DEEP_CMD），零撞。"""
    assert dc.DEEP_CMD_CLOUDSEA == "深度炼成"
    r = _Router()
    dc.register_cloudsea_deep_commands(r)
    assert "深度炼成" in r.specs and "深度炼金" not in r.specs


# ---------------------------------------------------------------- 一览


def test_list_at_max_level():
    out = dc.cmd_deep_list(_ctx(alchemy_level=10))
    assert "一览" in out and "AD-001" in out and "AD2-001" in out
    assert "二段" in out


def test_list_low_level_empty():
    out = dc.cmd_deep_list(_ctx(alchemy_level=1))
    assert "暂无已达门槛" in out


def test_gate_formula_top_capped():
    """门槛＝可制＋段×STEP 顶格 LEVEL_MAX：Lv10 时二段门槛 10+4→顶 10，全开。"""
    lib = _lib()
    consts = dc._consts(_ctx())
    g = dc._gate_lv(10, 2, consts)
    assert g == 10  # 顶格不破 LEVEL_MAX


# ---------------------------------------------------------------- 制造单


def test_make_single_hit_tree():
    out = dc.cmd_deep_make("AD-001", _ctx())
    assert "深度炼成" in out and "焰愈药剂·渊煮" in out
    assert "×2" in out and "R4" in out and "不进调和池" in out


def test_make_ad2_has_tide_rare():
    out = dc.cmd_deep_make("AD2-001", _ctx())
    assert "潮髓系稀有料" in out and "二段" in out


def test_make_gate_blocked():
    out = dc.cmd_deep_make("AD-001", _ctx(alchemy_level=3))
    assert "熟练不够" in out


def test_make_ambiguous():
    out = dc.cmd_deep_make("渊煮", _ctx())  # 多条渊煮系
    assert "命中多条" in out or "未识别" in out or "❓" in out


def test_make_unknown_tpl12():
    out = dc.cmd_deep_make("不存在的东西", _ctx())
    assert "❌" in out


# ---------------------------------------------------------------- 并账与 settings


def test_ledger_formula_closed():
    s = json.load(io.open(os.path.join(_ROOT, "content", "cloudsea", "settings.json"),
                          encoding="utf-8"))
    led = s["alchemy_ledger"]
    lib = _lib()
    assert led["keys"]["RECIPE_TOTAL"] == len(lib["recipes"]) == 86
    assert led["keys"]["DEEP_TOTAL"] == len(lib["depth1"]) == 42
    assert led["keys"]["DEEP2_TOTAL"] == len(lib["depth2"]) == 14
    assert led["keys"]["RECIPE_TOTAL"] + led["keys"]["DEEP_TOTAL"] \
        + led["keys"]["DEEP2_TOTAL"] == 142


def test_proficiency_axis_declared():
    s = json.load(io.open(os.path.join(_ROOT, "content", "cloudsea", "settings.json"),
                          encoding="utf-8"))
    assert s["proficiency_axis"]["axis"] == "alchemy_mastery"
    assert s["proficiency_axis"]["mastery_per_deep"] == 2
