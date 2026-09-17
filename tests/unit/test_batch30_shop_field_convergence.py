"""批30 · U8 回归：商店字段按定稿收敛（`scope/limit/period`）+ 旧键兼容读取。

定稿权威：`docs/审查参考/商店系统设计定稿.md:173-177`（字段表 `scope/limit/period`）
与 `:183`（旧 `stock`/`per_player` 自动映射）。
落地：编辑器字段元数据（`qbot_rpg/content/field_meta.py`）+ 校验器
（`qbot_rpg/content/shop_models.py`）+ 引擎兼容读（`qbot_rpg/core/shop.py`）。

断言目标：
  ① 编辑器**写入侧**只出定稿键（`scope/limit/period` 等 12 字段；旧键不进表单）；
  ② 旧数据 **`per_player`/`per_player_period` 仍能被正确解释**（映射到 limit/period 语义，
     不静默丢弃），且校验器只用黄提示建议迁移、不红拦；
  ③ 不带旧键 / 已迁移的数据**逐字段一致**；
  ④ 内容包实际数据（`content/*/shop.json`）无旧键；包展示名（`field_meta.json`）同步。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Mapping

import pytest

from qbot_rpg.content.field_meta import SHOP_FIELDS, SHOP_ITEM_ENTRY_CHILDREN, SHOP_REFRESH_CHILDREN
from qbot_rpg.content.shop_models import (
    LEGACY_PER_PLAYER,
    LEGACY_PER_PLAYER_PERIOD,
    LIMIT_PERIODS,
    REFRESH_MODES,
    SCOPES,
    SHOP_TYPES,
    ShopItemDef,
    validate_shops,
)
from qbot_rpg.core.shop import _entry_limit, _entry_period

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"

# 定稿 12 条目字段（细化_2b3 §1.4 / 商店定稿 :173-177）
AUTHORITATIVE_ITEM_FIELDS = {
    "item", "price", "currency", "scope", "stock", "refresh", "limit", "period",
    "reputation_required", "min_level", "discount", "sold_out_once",
}


class _Report:
    """validate_shops 收集器（鸭子类型，对齐 tests/unit/test_shop_models.py::_Report）。"""

    def __init__(self) -> None:
        self.errors: List[dict] = []
        self.warnings: List[dict] = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _check(shops: object):
    rep = _Report()
    validate_shops({"shop": shops}, rep)
    return rep


def _shop(items: list) -> list:
    return [{"id": "s1", "name": "测试店", "type": "normal", "items": items, "pool": []}]


# ---------------------------------------------------------------------------
# ① 写入侧：编辑器元数据只出定稿键
# ---------------------------------------------------------------------------

def test_editor_item_fields_are_authoritative_keys():
    """编辑器条目字段集 = 定稿 12 字段；旧键 `per_player`/`per_player_period` 不可写。"""
    assert set(SHOP_ITEM_ENTRY_CHILDREN) == AUTHORITATIVE_ITEM_FIELDS
    assert LEGACY_PER_PLAYER not in SHOP_ITEM_ENTRY_CHILDREN
    assert LEGACY_PER_PLAYER_PERIOD not in SHOP_ITEM_ENTRY_CHILDREN


def test_editor_enums_match_shop_models():
    """下拉枚举与 `shop_models` 同源：scope/period/refresh.mode/type（写入不产生非法值）。"""
    assert tuple(SHOP_ITEM_ENTRY_CHILDREN["scope"].enum) == SCOPES
    assert tuple(SHOP_ITEM_ENTRY_CHILDREN["period"].enum) == LIMIT_PERIODS
    assert tuple(SHOP_REFRESH_CHILDREN["mode"].enum) == REFRESH_MODES
    assert tuple(SHOP_FIELDS["type"].enum) == SHOP_TYPES


def test_editor_period_is_str_enum_not_obj():
    """批30 修正：`period` 是 day/week/month 字符串枚举（旧元数据误登记为 obj「上架时段」）。"""
    assert SHOP_ITEM_ENTRY_CHILDREN["period"].type == "str"
    assert SHOP_ITEM_ENTRY_CHILDREN["limit"].type == "int"
    assert SHOP_ITEM_ENTRY_CHILDREN["scope"].type == "str"
    # refresh 子键与定稿一致（mode/hour/weekday/start/end；旧 `interval` 已清）
    assert set(SHOP_REFRESH_CHILDREN) == {"mode", "hour", "weekday", "start", "end"}


def test_editor_help_mentions_legacy_mapping():
    """scope/limit/period 说明卡写明旧键映射（迁移提示，非静默）。"""
    scope_help = SHOP_ITEM_ENTRY_CHILDREN["scope"].help
    assert "per_player" in scope_help
    assert "personal" in scope_help


# ---------------------------------------------------------------------------
# ② 兼容读取：旧键映射到新键语义
# ---------------------------------------------------------------------------

def test_legacy_read_maps_to_new_semantics():
    """`per_player` → limit 语义、`per_player_period` → period 语义（不静默丢弃）。"""
    entry = {"item": "potion", "price": 50, LEGACY_PER_PLAYER: 3,
             LEGACY_PER_PLAYER_PERIOD: "week"}
    d = ShopItemDef.from_entry(entry)
    assert d.limit is None and d.period is None       # 新键未写
    assert d.per_player == 3 and d.per_player_period == "week"  # 旧键可读
    assert d.effective_scope == "personal"            # scope 默认归属 personal
    assert d.has_personal_side is True
    assert d.uses_legacy_fields is True
    # 引擎兼容读（同一映射口径）
    assert _entry_limit(entry) == 3
    assert _entry_period(entry) == "week"


def test_legacy_entry_validated_soft_only():
    """旧键条目：不红拦（兼容），仅 Y-6 黄提示建议迁移。"""
    rep = _check(_shop([{"item": "potion", "price": 50,
                         LEGACY_PER_PLAYER: 3, LEGACY_PER_PLAYER_PERIOD: "week"}]))
    assert rep.errors == []
    assert any(w["kind"] == "Y-6" for w in rep.warnings)
    # 新键同条目零黄（逐字段一致 + 无迁移噪音）
    rep_new = _check(_shop([{"item": "potion", "price": 50,
                             "scope": "personal", "limit": 3, "period": "week"}]))
    assert rep_new.errors == [] and rep_new.warnings == []


def test_invalid_new_keys_still_red():
    """门禁只严不松：新键非法值仍红拦（scope/period 枚举）。"""
    rep = _check(_shop([
        {"item": "potion", "price": 50, "scope": "server"},
        {"item": "ether", "price": 60, "period": "hour"},
    ]))
    rules = {e["detail"].get("rule") for e in rep.errors}
    assert "shop_entry_scope_invalid" in rules
    assert "shop_entry_period_invalid" in rules


# ---------------------------------------------------------------------------
# ③ 逐字段一致：旧键迁移前后等价
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy,new", [
    ({"item": "a", "price": 10, LEGACY_PER_PLAYER: 1, LEGACY_PER_PLAYER_PERIOD: "day"},
     {"item": "a", "price": 10, "scope": "personal", "limit": 1, "period": "day"}),
    ({"item": "b", "price": 20, LEGACY_PER_PLAYER: 5, LEGACY_PER_PLAYER_PERIOD: "month"},
     {"item": "b", "price": 20, "scope": "personal", "limit": 5, "period": "month"}),
    ({"item": "c", "price": 30}, {"item": "c", "price": 30}),
])
def test_legacy_new_field_equivalence(legacy: Mapping, new: Mapping):
    """同语义新/旧条目在引擎消费面（limit/period/生效侧）逐字段一致。"""
    dl, dn = ShopItemDef.from_entry(legacy), ShopItemDef.from_entry(new)
    assert _entry_limit(dict(legacy)) == _entry_limit(dict(new))
    assert _entry_period(dict(legacy)) == _entry_period(dict(new))
    assert dl.effective_scope == dn.effective_scope
    assert dl.has_personal_side == dn.has_personal_side
    assert dl.has_global_side == dn.has_global_side


# ---------------------------------------------------------------------------
# ④ 内容包数据与展示名
# ---------------------------------------------------------------------------

def _iter_shop_entries(doc: object):
    for shop in (doc if isinstance(doc, list) else []):
        if not isinstance(shop, Mapping):
            continue
        for key in ("items", "pool"):
            for e in shop.get(key) or []:
                if isinstance(e, Mapping):
                    yield e


def test_content_packs_have_no_legacy_keys():
    """全内容包 shop.json 无旧键（迁移已无残留）；有旧键则应迁移为新键而非静默丢弃。"""
    packs = sorted(p for p in CONTENT.glob("*/shop.json"))
    assert packs, "内容包 shop.json 一个都没找到（探针失效）"
    offenders = []
    for path in packs:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for e in _iter_shop_entries(doc):
            if LEGACY_PER_PLAYER in e or LEGACY_PER_PLAYER_PERIOD in e:
                offenders.append((path.name, e.get("item")))
    assert offenders == [], f"仍有旧键残留：{offenders}"


def test_pack_display_metadata_synced():
    """内容包展示名同步：refresh 不再提 manual/fixed/interval；type 枚举对齐定稿 5 类。"""
    for path in sorted(CONTENT.glob("*/field_meta.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        shop = (doc.get("field_help") or {}).get("shop")
        if not shop:
            continue
        refresh = shop.get("refresh") or {}
        assert "interval" not in refresh, path.name
        mode_help = refresh.get("mode", "")
        assert "none" in mode_help and "once" in mode_help, path.name
        assert "manual" not in mode_help and "fixed" not in mode_help, path.name
        type_help = shop.get("type", "")
        for t in SHOP_TYPES:
            assert t in type_help, (path.name, t)
