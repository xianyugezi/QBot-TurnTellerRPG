"""M12.5 批2：test_demo 全模块页登记可达性（22 页 CRUD list 全通 + 条目数）。

依据：docs/m125_启动包.md 验收门禁 2（27 模块全在编辑器可点开——list 型 CRUD）。
批1 路1A 动态页表打通后，editor.json 登记即驱动 pages_crud；本测试验证
content/test_demo/editor.json 当前 22 页登记全量可达（list 200 + 无 404），
并抽查扩展模块条目数非空（页面非空列表可编辑）。

铁律：零 NoneBot import；纯 pytest；无 emoji；全中文注释；ruff E501 零豁免。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from qbot_rpg.content.editor_registry import load_editor_registry
from qbot_rpg.content.loader import load_pack
from qbot_rpg.web import pages_crud

_REPO = Path(__file__).resolve().parent.parent.parent


def _pack():
    return asyncio.run(load_pack(_REPO / "content" / "test_demo"))


def test_editor_registry_all_pages_registered() -> None:
    """editor.json 登记页数 ≥22（六页 + 6 扩展视图 + D 类 11 + C 类 2 等）。"""
    reg = _pack().registry
    ed = load_editor_registry(reg)
    ids = [p.page_id for p in ed.pages]
    assert len(ids) >= 22
    for must in ("skill", "monster", "quest", "npc", "checkin", "ai", "hidden",
                 "env_event", "log_card", "items", "equipment", "slots",
                 "action", "effects", "statuses", "marks", "traits",
                 "skill_chains", "recipe", "proficiency"):
        assert must in ids, f"editor.json 缺登记页 {must}"


def test_all_registered_pages_list_ok() -> None:
    """每登记页 list 端点全通（CRUD 守卫动态页表放行，零 404）。"""
    reg = _pack().registry
    ed = load_editor_registry(reg)
    ctx = {"modules_raw": reg.modules_raw}
    bad = []
    for pg in ed.pages:
        out = pages_crud.list_page_items(pg.page_id, ctx)
        if not out.get("ok"):
            bad.append((pg.page_id, out.get("errors")))
    assert bad == [], f"list 不通的页: {bad}"


def test_extension_modules_have_entries() -> None:
    """D 类扩展模块真实条目存在（页面非空可编辑）。"""
    reg = _pack().registry
    raw = reg.modules_raw
    for mod, min_n in (("items", 1), ("action", 1), ("effects", 1),
                       ("marks", 1), ("recipe", 1), ("skill_chains", 1),
                       ("npc", 1), ("checkin", 1), ("dungeon", 1),
                       ("achievements", 1)):
        data = raw.get(mod)
        assert isinstance(data, list) and len(data) >= min_n, \
            f"{mod} 条目不足（{type(data).__name__} {len(data) if isinstance(data, list) else '?'}）"
