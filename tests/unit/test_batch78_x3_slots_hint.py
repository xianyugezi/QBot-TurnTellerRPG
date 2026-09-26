"""批78 · X3 验收：slots 模块 ↔ settings.slot_defs 黄提示（不同数据空间；目录声明驱动）。

背景（登记表 X3 重核）：批19 #5 目录条目「两处都在表达装备部位定义」的描述与实现冲突——
slots.json 条目形态 = {equip_id, slots:[{slot_level}]}（契约 §四 SLOTS_FIELD_DEFS，
core/jewel.py 消费）= **珠插槽 / 镶嵌孔位**；settings.slot_defs（EQP-04）才是运行时
**部位表**。本批按既有 `overlap_with` / `overlap_note` 机制纠正描述为黄提示（不硬拦），
说明「这两处是什么关系、改哪里」，不因包未声明而让能力消失，框架内不出现包业务名。

铁律：只读仓库（不写内容包目录）；断言走真实 pack 数据。
"""
from __future__ import annotations

from pathlib import Path

from qbot_rpg.content.module_catalog import CATALOG_BY_MODULE
from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"


def test_slots_entry_corrected_to_jewel_sockets() -> None:
    """目录条目定位纠正：label/purpose 说明是珠插槽（非装备部位表）。"""
    e = CATALOG_BY_MODULE["slots"]
    assert e.label == "珠插槽"
    assert "珠插槽" in e.purpose and "部位表" in e.purpose
    assert e.overlap_with == "settings.slot_defs" and e.overlap_note


def test_slots_overlap_note_explains_relation_and_where_to_edit() -> None:
    """黄提示文案：说明二者**不同数据空间**（部位表 vs 珠插槽）、各自单一源、不阻断。"""
    note = CATALOG_BY_MODULE["slots"].overlap_note
    for token in ("settings.slot_defs", "部位表", "珠插槽", "core/jewel.py",
                  "不同数据空间", "单一源", "不阻断"):
        assert token in note, token


def test_overlap_hint_mechanism_driven_by_catalog() -> None:
    """提示机制仍在（目录声明驱动，不写死模块名）：veinborn 有 slot_defs → 黄提示。"""
    hits = api.list_entries("veinborn", "slots", root=CONTENT)["overlap_hints"]
    assert len(hits) == 1
    h = hits[0]
    assert h["level"] == "yellow" and h["code"] == "module_overlap"
    assert h["target"] == "settings.slot_defs" and h["target_present"] is True
    assert "单一源" in h["message"] and "不阻断" in h["message"]


def test_overlap_hint_reports_absent_other_side() -> None:
    """另一处无数据也照提示（如实给出 target_present=False，不硬拦）。

    test_demo：slots.json 有 4 条珠插槽，settings.json 无 slot_defs → target_present False。
    """
    hits = api.list_entries("test_demo", "slots", root=CONTENT)["overlap_hints"]
    assert len(hits) == 1
    assert hits[0]["target"] == "settings.slot_defs"
    assert hits[0]["target_present"] is False


def test_frontend_still_renders_overlap_hints() -> None:
    """编辑器接口/前端契约未变（黄提示渲染入口在场）。"""
    html = (REPO / "qbot_rpg" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    for token in ("overlap_hints", "renderListHints", "lh-ov"):
        assert token in html, token
