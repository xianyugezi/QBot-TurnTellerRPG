"""编辑器重写批14 · #5 校验提示人话化（用户原话：校验提示说明不清晰，小白玩家看不懂）。

现状：错误只带规则码 + 字段路径，没告诉作者「哪里错、为什么错、怎么办」。

本批（**展示层改造，不改校验判定与门禁强度**）：
  · 每条校验反馈补三段式：`where`（哪里：模块/条目/字段中文名）+ `why`（为什么：依据哪条
    要求、期望什么）+ `how`（怎么办：具体动作）；
  · 规则码 / 原始消息 / 位置 收进 `code`/`raw`/`field_path`（前端折叠展示，供我们定位）；
  · 规则库覆盖最常见的通用规则（类型 / 枚举 / 必填 / 引用 / 重复 ID / 范围 / 未知键 /
    区间倒置 / 数字非法…）；
  · **判定不变**：同一份非法数据，修前修后红拦条数与规则码完全一致，只改文案。

覆盖：
  A. 三段式结构断言（每条红/黄都有 where/why/how，且都非空）；
  B. ≥5 条真实错误「修前 vs 修后」对照（原文）；
  C. 判定不变（条数 + kind/rule 完全一致；humanize 不丢条目）；
  D. 覆盖最常见 12 条规则；
  E. 用词口径：可见文案不出现 schema/validator/字段路径 等术语；
  F. 前端契约：三段式渲染 + 折叠排查信息。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from qbot_rpg.content import atomic_store
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

# 触发多条通用规则的合成元数据（用框架自己的 FieldMeta/校验器 → 真实规则，非臆造）
_RULE_META = FieldMetaTable(modules={
    "widgets": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True),
        "name": FieldMeta(type="str", required=True),
        "count": FieldMeta(type="int", range_min=0, range_max=10, allow_negative=False),
        "mode": FieldMeta(type="enum", enum=("alpha", "beta")),
        "owner": FieldMeta(type="ref", ref_target="monsters"),
        "span": FieldMeta(type="obj", children={
            "lo": FieldMeta(type="int"), "hi": FieldMeta(type="int"),
        }),
    }),
})

# 一份「处处违规」的数据：覆盖类型 / 枚举 / 引用 / 必填 / 负数 / 区间倒置 / 未知键…
_BAD_DATA: Dict[str, Any] = {
    "widgets": [
        {"id": "w1", "name": 123, "count": -5, "mode": "gamma", "owner": "ghost",
         "span": {"lo": 9, "hi": 2}},
        {"id": "w2", "count": "8"},  # name 必填缺失
    ],
    "monsters": [{"id": "m1", "name": "样本怪"}],
    "widgets_extra": {},
}


def _raw_errors() -> List[Any]:
    return list(check_pack(_BAD_DATA, _RULE_META).errors)


def _human() -> List[Dict[str, Any]]:
    return atomic_store.humanize_errors(_raw_errors())


# =====================================================================================
# A · 三段式结构断言
# =====================================================================================
def test_every_error_has_three_part_structure() -> None:
    rows = _human()
    assert rows, "示例数据应至少触发一条红拦"
    for r in rows:
        assert r["level"] == "red"
        assert r["code"] and r["rule"]
        assert r["why"] and r["how"], r
        assert r["raw"] and r["message"]
        assert r["field"]


def test_editor_decoration_adds_where_and_keeps_rule_code() -> None:
    """经编辑器装饰后每条都有 `where`（中文名），规则码/原始消息/位置仍可查。"""
    res = editor_ops.validate_entry(
        "veinborn", "settings", "death_penalty",
        {"weak_duration_sec": "不是数字"}, root=CONTENT, role="owner")
    assert res["ok"] is False and res["level"] == "red"
    for e in res["errors"]:
        assert e["where"] and "哪里" not in e["where"]
        assert e["code"] and e["rule"] and e["field_path"]
        assert e["raw"] and e["why"] and e["how"]
    assert "虚弱时长" in res["errors"][0]["where"]


# =====================================================================================
# B · ≥5 条「修前 vs 修后」对照（真实错误原文）
# =====================================================================================
def _pairs() -> List[Tuple[str, str, Dict[str, Any]]]:
    rows = _human()
    by_rule = {}
    for r in rows:
        by_rule.setdefault(r["rule"], r)
    out = []
    for rule in ("type", "enum", "required_missing", "ref_missing", "negative", "dead_range"):
        r = by_rule.get(rule)
        if r is not None:
            out.append((rule, r["message"], r))
    return out


def test_before_after_pairs_cover_at_least_five_rules() -> None:
    pairs = _pairs()
    assert len(pairs) >= 5, [p[0] for p in pairs]
    for rule, before, r in pairs:
        # 修前（单句原文，仍保留）+ 修后（三段式），对照断言
        assert before.startswith("模块「widgets」配置校验未通过：")
        assert r["why"] and r["how"]
        assert before != (r["why"] + r["how"])
    # 每条修后的「为什么」都点明期望，不空泛
    for _rule, _before, r in pairs:
        assert len(r["why"]) >= 6


def test_before_after_samples_are_printable() -> None:
    """把 ≥5 条真实对照打印出来（便于人工核对；断言修后文案可用）。"""
    pairs = _pairs()
    assert len(pairs) >= 5
    for rule, before, r in pairs:
        assert rule and before
        assert r["why"] and r["how"]
        assert r["code"] and r["field_path"] if "field_path" in r else True


# =====================================================================================
# C · 判定不变（条数 + 规则码完全一致；只改文案）
# =====================================================================================
def test_verdict_unchanged_count_and_codes() -> None:
    raw = _raw_errors()
    human = atomic_store.humanize_errors(raw)
    assert len(human) == len(raw)
    assert [e.kind for e in raw] == [h["code"] for h in human]
    assert [str(dict(e.detail).get("rule", "")) for e in raw] == [h["rule"] for h in human]
    assert [e.field for e in raw] == [h["field"] for h in human]


def test_humanize_does_not_swallow_messages() -> None:
    """原始消息逐条保留（`raw`/`message`），不因翻译失败丢条目或丢信息。"""
    rows = _human()
    for raw, h in zip(_raw_errors(), rows):
        detail = dict(raw.detail)
        src = str(detail.get("message") or detail.get("error") or detail.get("msg")
                  or detail.get("rule") or raw.kind)
        assert h["raw"] == src
        assert src in h["message"]


# =====================================================================================
# D · 覆盖最常见 12 条规则
# =====================================================================================
def test_rule_guide_covers_common_rules() -> None:
    needed = {
        "type", "enum", "required_missing", "ref_missing", "ref_not_str",
        "id_duplicate", "negative", "not_a_number", "out_of_common_range",
        "dead_range", "module_structure", "entry_not_object",
    }
    assert needed <= set(atomic_store.RULE_GUIDE), needed - set(atomic_store.RULE_GUIDE)
    for rule in needed:
        why, how = atomic_store.RULE_GUIDE[rule]({})
        assert why and how, rule


def test_listed_categories_have_real_humanized_errors() -> None:
    """任务点名的类别：引用 / 枚举 / 范围 / 必填 / 未知键 / 重复 id / 引用目标不存在。"""
    import copy

    codes: set = set()
    # 引用（ref_missing）/ 枚举 / 必填 / 类型（上文合成数据）
    codes |= {r["rule"] for r in _human()}
    # 范围（黄提示 out_of_common_range）+ 概率极端
    meta = FieldMetaTable(modules={
        "w": ModuleMeta(entry_type="list", fields={
            "n": FieldMeta(type="int", range_min=1, range_max=5),
            "p": FieldMeta(type="float", probability=True),
        }),
    })
    rep = check_pack({"w": [{"id": "a", "n": 99, "p": 0.99}]}, meta)
    codes |= {r["rule"] for r in atomic_store.humanize_warnings(rep.warnings)}
    # 重复 id（同命名空间）
    meta2 = FieldMetaTable(modules={
        "w": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True),
            "name": FieldMeta(type="str"),
        }),
    })
    rep2 = check_pack({"w": [{"id": "dup", "name": "甲"},
                             {"id": "dup", "name": "乙"}]}, meta2)
    codes |= {r["rule"] for r in atomic_store.humanize_errors(rep2.errors)}
    # 未知键（严格模块 skills V-11；真实内容包）
    _pack_dir, modules = api.load_pack_modules("veinborn", root=CONTENT)
    mods = copy.deepcopy(modules)
    mods["skills"][0]["totally_unknown_key"] = 1
    rep3 = check_pack(mods, api.field_meta_table())
    codes |= {r["rule"] for r in atomic_store.humanize_errors(rep3.errors)}
    for want in ("ref_missing", "enum", "required_missing", "out_of_common_range",
                 "id_duplicate", "skill_field_unregistered"):
        assert want in codes, (want, sorted(codes))


# =====================================================================================
# E · 用词口径：可见文案不出现技术术语
# =====================================================================================
_JARGON = ("schema", "validator", "校验器", "字段路径", "validat")


@pytest.mark.parametrize("level", ["red", "yellow"])
def test_visible_text_has_no_jargon(level: str) -> None:
    items: List[Any] = _raw_errors()
    rows = (atomic_store.humanize_errors(items) if level == "red"
            else atomic_store.humanize_warnings(items))
    for r in rows:
        visible = (r["why"] or "") + (r["how"] or "")
        for word in _JARGON:
            assert word not in visible, (word, visible)


def test_warnings_also_three_part() -> None:
    # 概率极端 / 常见区间越界都是黄提示（Y-2 / Y-1）
    meta = FieldMetaTable(modules={
        "w": ModuleMeta(entry_type="list", fields={
            "p": FieldMeta(type="float", probability=True),
            "n": FieldMeta(type="int", range_min=1, range_max=5),
        }),
    })
    rep = check_pack({"w": [{"id": "a", "p": 0.99, "n": 99}]}, meta)
    assert rep.warnings
    rows = atomic_store.humanize_warnings(rep.warnings)
    for r in rows:
        assert r["why"] and r["how"]
        assert r["code"] and r["rule"]


# =====================================================================================
# F · 前端契约：三段式 + 折叠排查信息
# =====================================================================================
def test_frontend_renders_three_part_with_collapsible_raw() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("哪里", "为什么", "怎么办", "排查信息", "vraw", "field_path",
                  "e.where", "e.why", "e.rule"):
        assert token in html, token
