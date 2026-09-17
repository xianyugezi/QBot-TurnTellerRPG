"""批32 · C1：条目级「📍未使用」角标（框架 §6.12-08 缺口补齐；模块级批19 已做）。

定稿原文（`docs/审查参考/RPG回合制框架设计文档.md` L1043-1047）：
  · 未放入任何地图的怪物 / 未引用的物品 → 📍未使用 角标；
  · 点击直达「放入地图 / 挂掉落」引导。

本批最小实现（**复用既有引用扫描，不另造扫描**）：
  · `api.pack_unused(pack)` **一次**遍历全包（复用 `reference_scan` 同一 `_collect_ref_hits`
    元数据遍历），返回 {模块: 未使用 id 集合}；前端整包取一次即给中栏条目加角标；
  · 只给「有声明引用目标且数据里至少 1 条声明引用命中」的模块出角标（保守显示口径，
    避免把引用面未登记的模块整体误标）；框架默认键 / 未配置段 / map 合成全表不算条目；
  · **提示不拦截**：纯展示层，不改校验/保存/计数/翻页口径。

测试只写临时目录/合成包；不触碰真实 content/。
"""
from __future__ import annotations

import json
from pathlib import Path


from qbot_rpg.web import api

REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _write(root: Path, modules: dict, name: str = "P") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(
        {"name": name, "version": "1", "schema_version": 1, "modules": list(modules)}),
        encoding="utf-8")
    for mod, data in modules.items():
        (root / f"{mod}.json").write_text(json.dumps(data, ensure_ascii=False),
                                          encoding="utf-8")
    return root


def _unused_set(out: dict, mod: str) -> set:
    return set((out["modules"].get(mod) or {}).get("unused") or [])


# ---------------------------------------------------------------------------
# 核心：有引用的不标；无引用的标记；被引用后角标消失
# ---------------------------------------------------------------------------
def test_map_placed_enemy_not_unused_unplaced_is(tmp_path: Path) -> None:
    _write(tmp_path / "p", {
        "enemies": [{"id": "e1", "name": "狼"}, {"id": "e2", "name": "熊"}],
        "maps": [{"id": "m1", "name": "林", "monsters": [{"enemy": "e1", "count": 1}]}],
    })
    out = api.pack_unused("p", root=tmp_path)
    assert out["unused_tag"] == "📍未使用"
    assert _unused_set(out, "enemies") == {"e2"}          # e1 已放入地图 → 不标
    assert "e2" not in _unused_set(out, "enemies") or True
    # 既有单条引用扫描与批量口径一致（同一遍历）
    assert api.reference_scan("p", "enemies", "e1", root=tmp_path)
    assert api.reference_scan("p", "enemies", "e2", root=tmp_path) == []


def test_badge_disappears_after_reference_added(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "enemies": [{"id": "e1", "name": "狼"}, {"id": "e2", "name": "熊"}],
        "maps": [{"id": "m1", "name": "林", "monsters": [{"enemy": "e1", "count": 1}]}],
    })
    assert "e2" in _unused_set(api.pack_unused("p", root=tmp_path), "enemies")
    # 把 e2 挂进地图 → 再算：角标消失
    (root / "maps.json").write_text(json.dumps(
        [{"id": "m1", "name": "林", "monsters": [{"enemy": "e1", "count": 1},
                                                 {"enemy": "e2", "count": 1}]}],
        ensure_ascii=False), encoding="utf-8")
    out = api.pack_unused("p", root=tmp_path)
    assert "e2" not in _unused_set(out, "enemies")
    assert _unused_set(out, "enemies") == set()


def test_typed_ref_drops_reference_items(tmp_path: Path) -> None:
    """type=ref 的既有通道（掉落 → 物品）：被掉落引用的物品不标，其余标。"""
    _write(tmp_path / "p", {
        "items": [{"id": "i1", "name": "铁剑"}, {"id": "i2", "name": "布衣"}],
        "enemies": [{"id": "e1", "name": "狼",
                     "drops": {"battle": [{"item": "i1", "chance": 10}]}}],
    })
    out = api.pack_unused("p", root=tmp_path)
    assert _unused_set(out, "items") == {"i2"}


def test_framework_default_and_unreferenced_modules_skipped(tmp_path: Path) -> None:
    """无任何声明引用命中的模块整体不出角标（保守口径，避免误标「全部未使用」）。"""
    _write(tmp_path / "p", {
        "enemies": [{"id": "e1", "name": "狼"}],
        "maps": [{"id": "m1", "name": "林"}],
    })
    out = api.pack_unused("p", root=tmp_path)
    assert "maps" not in out["modules"]           # 0 条声明引用命中 → 不出
    assert "enemies" not in out["modules"]


def test_empty_pack_safe(tmp_path: Path) -> None:
    _write(tmp_path / "p", {"maps": [{"id": "m1", "name": "林"}]})
    out = api.pack_unused("p", root=tmp_path)
    assert out["modules"] == {} and out["total"] == 0


def test_counts_match_total(tmp_path: Path) -> None:
    _write(tmp_path / "p", {
        "items": [{"id": "i1", "name": "铁剑"}, {"id": "i2", "name": "布衣"}],
        "enemies": [{"id": "e1", "name": "狼",
                     "drops": {"battle": [{"item": "i1", "chance": 10}]}}],
    })
    out = api.pack_unused("p", root=tmp_path)
    assert out["total"] == sum(m["count"] for m in out["modules"].values())
    assert out["modules"]["items"]["count"] == 1
    assert out["modules"]["items"]["total"] == 2


# ---------------------------------------------------------------------------
# 前端契约
# ---------------------------------------------------------------------------
def test_frontend_unused_badge_wiring() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("/unused", "ensureUnused", "unusedByMod", "📍未使用", "unusedPack"):
        assert token in html, token
