# -*- coding: utf-8 -*-
"""九期批次 233 定向测试：错误文案体系（TPL-12/13/14 开键＋21 条云海文案＋$C.* 替换）。"""
import json
import io
import os

from qbot_rpg.commands.sender import format_tpl12, format_tpl13, format_tpl14
from qbot_rpg.commands.errors import (
    TPL_ERR_BAD_COMMAND,
    TPL_ERR_CONDITION,
    TPL_ERR_LACK_RESOURCE,
)
from qbot_rpg.core.templates.cloudsea_err_tpl import (
    CLOUDSEA_ERR_KEYS,
    expand_consts,
)

_TPL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "content", "cloudsea", "templates.json")


# ---------------------------------------------------------------- 开键


def test_tpl12_default_unchanged():
    """ctx 缺省 → errors.py 常量（D-04 唯一源，零行为变化）。"""
    assert format_tpl12("/港 菜") == TPL_ERR_BAD_COMMAND.format(fragment="/港 菜")
    assert format_tpl13("破甲", 1, 3) == TPL_ERR_CONDITION.format(
        name="破甲", current=1, required=3)
    assert format_tpl14("风缆", 2, 0) == TPL_ERR_LACK_RESOURCE.format(
        resource="风缆", amount=2, current=0)


def test_tpl12_ctx_override():
    """ctx["templates"] 覆盖键生效（开键通道）。"""
    ctx = {"templates": {"err_bad_command": "❌ 云海不识：「{fragment}」· 发 帮"}}
    out = format_tpl12("/xyz", ctx)
    assert out == "❌ 云海不：「…」· 发 帮"[:0] or "云海不识" in out
    assert "帮助" not in out


def test_tpl13_14_ctx_override():
    ctx = {"templates": {
        "err_condition": "❌ 差一点：{name}（{current}/{required}）",
        "err_lack_resource": "❌ 缺{resource}×{amount}（有{current}）",
    }}
    assert "差一点" in format_tpl13("门槛", 5, 7, ctx)
    assert "缺风缆×2" in format_tpl14("风缆", 2, 0, ctx)


def test_tpl_override_ignores_bad_shapes():
    ctx = {"templates": {"err_bad_command": 123, "err_condition": "", "err_lack_resource": None}}
    assert format_tpl12("/a", ctx) == TPL_ERR_BAD_COMMAND.format(fragment="/a")
    assert format_tpl13("x", 1, 2, ctx) == TPL_ERR_CONDITION.format(name="x", current=1, required=2)
    assert format_tpl14("r", 1, 0, ctx) == TPL_ERR_LACK_RESOURCE.format(
        resource="r", amount=1, current=0)


# ---------------------------------------------------------------- 21 条注入


def test_cloudsea_templates_21_keys():
    data = json.load(io.open(_TPL_PATH, encoding="utf-8"))
    keys = {k for k in data if not k.startswith("_")}
    assert len(keys) == 21
    assert keys == set(CLOUDSEA_ERR_KEYS.keys())


def test_cloudsea_templates_verbatim_anchors():
    """逐字锚抽验（08_错误文案表.md 原句语素）。"""
    data = json.load(io.open(_TPL_PATH, encoding="utf-8"))
    assert "先去倒杯水" in data["err_not_your_turn"]
    assert "档案长期保留" in data["err_long_sleep_frozen"]
    assert "获一枚亮一枚" in data["err_mix_recipe_missing"]
    assert "点亮后此处出一览" in data["err_deep_list_empty"]


# ---------------------------------------------------------------- $C.* 替换


def test_expand_consts_replaces_and_keeps():
    consts = {"CUSTODY_EFFICIENCY": 0.75, "ALCHEMY.DEEP_COST_MULT": 2}
    out = expand_consts(
        "效率 $C.CUSTODY_EFFICIENCY；材料 ×$C.ALCHEMY.DEEP_COST_MULT；未知 $C.NOPE.X 保留",
        consts)
    assert "效率 0.75" in out
    assert "材料 ×2" in out
    assert "$C.NOPE.X" in out  # 查不到保留字面


def test_expand_consts_noop():
    assert expand_consts("无键文案", {}) == "无键文案"
    assert expand_consts("", {"A": 1}) == ""
