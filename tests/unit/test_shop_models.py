"""M4 批次3·路D1：shop.json 商店数据模型（ShopDef 14 顶层字段 + 12 条目字段）+ validate_shops 专项校验测试。

依据：m4_shared_contract §3.2（商店 C1-C6）+ 细化_2b3_商店引擎契约.md（shop.json schema §1.2/§1.4/
refresh 四模式 §1.3 / 校验器边界 §1.6 / 验收 TC-01~TC-42 + 2026-08-27 审查裁决 P1-1~P1-4）
+ 商店系统设计定稿.md（顶层字段表 L128-143 / 条目字段表 L168-181 / refresh §七 L278-302 /
校验链 L338-345 / 校验器 §十一 L408-433 / 示例 L437-511 / 旧字段兼容 L183）
+ 2026-08-27 裁决⑤⑥（m4_shared_contract §0.5-6：stock+per_player 同条目并存 / 不配 refresh=永不刷新）。
测试目标：qbot_rpg.content.shop_models.validate_shops（独立模块专项校验，供主 agent 收口接 check_pack）。

测试口径（对齐 test_npc_models）：
  - validate_shops(modules, report) 为纯函数；report 鸭子类型（本文件 _Report 收集器；
    另含真实 _Checker 收口兼容测试）。
  - 断言级别：errors=拦截（硬拦）/ warnings=黄提示（不拦截）。
  - 合法全量 schema（5 类型 × 14 顶层字段 + 12 条目字段，TC-40 同引擎基线）零红拦零黄。
"""
from __future__ import annotations

import copy

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.shop_models import (
    BLACKMARKET_LISTING_FIELD,
    LEGACY_PER_PLAYER,
    LEGACY_PER_PLAYER_PERIOD,
    LIMIT_PERIODS,
    REFRESH_HOUR_DEFAULT,
    REFRESH_MODE_DEFAULT,
    REFRESH_MODES,
    REPUTATION_LEVEL_NAMES,
    REPUTATION_LEVELS,
    SCOPE_DEFAULT,
    SCOPES,
    SHOP_TYPE_DEFAULT,
    SHOP_TYPE_NAMES,
    SHOP_TYPES,
    RefreshDef,
    ShopDef,
    ShopItemDef,
    parse_shops,
    validate_shops,
)
from qbot_rpg.content.validator import _Checker


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
class _Report:
    """validate_shops 收集器（鸭子类型：error/warning 与 validator._Checker._err/_warn 签名一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def note(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.notes.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _base_modules() -> dict:
    """标准模块上下文：items 引用靶齐全 + settings 货币注册表（coins/diamond/gems/tickets）。
    **不含 npc**（未接线 → 不触发「未使用商店」噪音；需接线时各用例显式构造）。"""
    return {
        "items": [
            {"id": "potion"}, {"id": "hi_potion"}, {"id": "antidote"}, {"id": "scroll"},
            {"id": "stamina_potion"}, {"id": "iron_sword"}, {"id": "iron_ore"},
            {"id": "mithril"}, {"id": "lucky_charm"}, {"id": "silver_sword"},
            {"id": "mithril_armor"}, {"id": "guild_badge"}, {"id": "festival_sparkler"},
            {"id": "limited_costume"}, {"id": "dragon_scale"}, {"id": "stardust"},
            {"id": "rare_box"},
        ],
        "settings": {"currencies": [
            {"id": "coins"}, {"id": "diamond"}, {"id": "gems"}, {"id": "tickets"},
        ]},
    }


def _wired_modules() -> dict:
    """引用靶 + npc 接线（blacksmith_shop/guild_shop/festival_shop/black_market 均被引用 → 零未使用提示）。"""
    modules = _base_modules()
    modules["npc"] = [
        {"id": "merchant_lin",
         "shop_refs": ["blacksmith_shop", "guild_shop", "festival_shop", "black_market"]},
    ]
    return modules


def _legal_shops() -> list:
    """合法全量商店（TC-40 五类型同引擎基线：normal/npc/reputation/event/blackmarket；
    覆盖 14 顶层字段 + 12 条目字段 + 条目 refresh + 混合支付 + 黑市 listing_count，零红拦零黄）。"""
    return [
        {
            "id": "grocery_shop", "name": "杂货铺", "icon": "🧺", "type": "normal",
            "currency": "coins", "level_required": 0, "desc": "新手村杂货铺",
            # 无 refresh（裁决⑥：缺省 none 永不刷新）
            "items": [
                {"item": "potion", "price": 50, "stock": 0},              # stock 0=无限（TC-08）
                {"item": "hi_potion", "price": 120, "scope": "personal", "limit": 3, "period": "day"},
                {"item": "antidote", "price": 30},
                {"item": "scroll", "price": 100, "scope": "personal", "limit": 5, "period": "week"},
                {"item": "stamina_potion", "price": 200, "min_level": 5},  # 条目级等级门槛
            ],
            "pool": [], "price_fluctuation": 0, "visible": True,
        },
        {
            "id": "blacksmith_shop", "name": "铁匠铺", "icon": "🔨", "type": "npc",
            "currency": "coins", "refresh": {"mode": "daily", "hour": 5},
            "items": [
                {"item": "iron_sword", "price": 500},
                {"item": "iron_ore", "price": 80},
                {"item": "mithril", "price": 300, "stock": 10,
                 "refresh": {"mode": "weekly", "weekday": 1, "hour": 5}},  # 条目级 refresh（global 侧）
                {"item": "lucky_charm", "price": {"coins": 50, "gems": 5}},  # 混合支付（两币同扣）
            ],
            "pool": [], "price_fluctuation": 0, "visible": True,
        },
        {
            "id": "guild_shop", "name": "冒险者公会商店", "icon": "🏰", "type": "reputation",
            "currency": "coins", "reputation_required": {"level": 2},  # 商店级声望门槛
            "items": [
                {"item": "silver_sword", "price": 2000, "reputation_required": {"level": 2}},
                {"item": "mithril_armor", "price": 5000, "reputation_required": {"level": 4}},
                {"item": "guild_badge", "price": 300, "currency": "gems", "stock": 50},
            ],
            "pool": [], "price_fluctuation": 0, "visible": True,
        },
        {
            "id": "festival_shop", "name": "丰收节集市", "icon": "🎆", "type": "event",
            "currency": "tickets",
            "refresh": {"mode": "once", "start": "2026-09-01 00:00", "end": "2026-09-07 23:59"},
            "items": [
                {"item": "festival_sparkler", "price": 10, "stock": 0},
                {"item": "limited_costume", "price": 100, "stock": 200, "sold_out_once": True},
            ],
            "pool": [], "price_fluctuation": 0, "visible": True,
        },
        {
            "id": "black_market", "name": "神秘商人", "icon": "🌙", "type": "blackmarket",
            "currency": "coins", "refresh": {"mode": "daily", "hour": 20},
            "price_fluctuation": 20,
            "open_condition": {"var": "is_night", "op": "is", "value": True},
            "listing_count": 3,  # 【工程补白】2：黑市上架数量（items 为空时的 N 来源）
            "pool": [
                {"item": "dragon_scale", "price": 5000, "scope": "personal", "limit": 1, "period": "week"},
                {"item": "stardust", "price": 800},
                {"item": "rare_box", "price": {"coins": 3000, "gems": 5}, "stock": 5},
            ],
            "items": [],  # 黑市正典形态：货架由 pool 刷新驱动（定稿 L507）
            "visible": True,
        },
    ]


def _check(shops: object, **extra_modules: object):
    """跑 validate_shops；默认带齐全引用靶模块（无 npc 接线）。"""
    modules: dict = _base_modules()
    modules["shop"] = shops
    modules.update(extra_modules)
    rep = _Report()
    validate_shops(modules, rep)
    return rep


def _errs(rep, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


def _shop_by_id(shops: list, sid: str) -> dict:
    for s in shops:
        if s.get("id") == sid:
            return s
    raise AssertionError(f"shop 缺少 {sid}")


# ---------------------------------------------------------------------------
# 合法全量 schema 零红拦 + 访问器 + parse_shops
# ---------------------------------------------------------------------------
def test_legal_shop_full_green() -> None:
    """TC-40：合法全量 schema（五类型 + 14 顶层字段 + 12 条目字段）→ 零红拦零黄。"""
    modules = _wired_modules()
    modules["shop"] = _legal_shops()
    rep = _Report()
    validate_shops(modules, rep)
    assert not rep.errors, f"合法 shop 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 shop 应为零黄提示：{rep.warnings}"


def test_legal_shop_checker_integration() -> None:
    """收口兼容：validate_shops 直传真实 validator._Checker（_err/_warn 鸭子路径）零红拦零黄。"""
    modules = _wired_modules()
    modules["shop"] = _legal_shops()
    checker = _Checker(modules, default_field_meta_table())
    validate_shops(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"


def test_parse_shops() -> None:
    """parse_shops 提取 shop 模块 → ShopDef 元组（非 list/非对象条目跳过）。"""
    shops = _legal_shops()
    defs = parse_shops({"shop": shops})
    assert [d.id for d in defs] == ["grocery_shop", "blacksmith_shop", "guild_shop",
                                    "festival_shop", "black_market"]
    assert parse_shops({"shop": "nope"}) == ()
    assert parse_shops({}) == ()


def test_shopdef_accessors_top_level() -> None:
    """ShopDef 顶层 14 字段访问器（id/name 由 BaseDef；F03-F14 + listing_count）。"""
    d = ShopDef.from_entry(_shop_by_id(_legal_shops(), "guild_shop"))
    assert d.id == "guild_shop"
    assert d.name == "冒险者公会商店"
    assert d.icon == "🏰"  # type: ignore[attr-defined]
    assert d.type == "reputation"  # type: ignore[attr-defined]
    assert d.currency == "coins"  # type: ignore[attr-defined]
    assert d.level_required is None # type: ignore[attr-defined]  # guild 未配 level_required（访问器不伪造默认值，兜底在校验/引擎侧）
    assert d.reputation_required.get("level") == 2  # type: ignore[attr-defined]
    assert d.open_condition is None  # type: ignore[attr-defined]
    assert isinstance(d.refresh, RefreshDef)  # type: ignore[attr-defined]
    assert d.refresh.mode is None # type: ignore[attr-defined]  # 未配 refresh → mode None（裁决⑥：不配=永不刷新）
    assert len(d.items) == 3  # type: ignore[attr-defined]
    assert isinstance(d.items[0], ShopItemDef)  # type: ignore[attr-defined]
    assert d.pool == ()  # type: ignore[attr-defined]
    assert d.price_fluctuation == 0  # type: ignore[attr-defined]
    assert d.visible is True  # type: ignore[attr-defined]
    assert d.desc is None  # type: ignore[attr-defined]

    bm = ShopDef.from_entry(_shop_by_id(_legal_shops(), "black_market"))
    assert bm.type == "blackmarket"  # type: ignore[attr-defined]
    assert bm.price_fluctuation == 20  # type: ignore[attr-defined]
    assert bm.open_condition.get("var") == "is_night"  # type: ignore[attr-defined]
    assert len(bm.pool) == 3  # type: ignore[attr-defined]
    assert bm.listing_count == 3  # type: ignore[attr-defined]
    assert bm.blackmarket_listing_n == 3  # type: ignore[attr-defined]
    assert bm.refresh.mode == "daily"  # type: ignore[attr-defined]
    assert bm.refresh.hour == 20  # type: ignore[attr-defined]
    assert bm.items == ()  # type: ignore[attr-defined]


def test_shopdef_refresh_subobject() -> None:
    """RefreshDef 四模式访问器（daily/weekly/once/none × hour/weekday/start/end）。"""
    d = ShopDef.from_entry(_shop_by_id(_legal_shops(), "festival_shop"))
    assert d.refresh.mode == "once"  # type: ignore[attr-defined]
    assert d.refresh.start == "2026-09-01 00:00"  # type: ignore[attr-defined]
    assert d.refresh.end == "2026-09-07 23:59"  # type: ignore[attr-defined]
    d2 = ShopDef.from_entry(_shop_by_id(_legal_shops(), "blacksmith_shop"))
    assert d2.refresh.mode == "daily"  # type: ignore[attr-defined]
    assert d2.refresh.hour == 5  # type: ignore[attr-defined]
    assert d2.refresh.weekday is None  # type: ignore[attr-defined]


def test_shopitemdef_accessors_12_fields() -> None:
    """ShopItemDef 12 条目字段访问器（item/price/currency/scope/stock/refresh/limit/period/
    reputation_required/min_level/discount/sold_out_once）。"""
    shops = _legal_shops()
    grocery = ShopDef.from_entry(_shop_by_id(shops, "grocery_shop"))
    hi = grocery.items[1]  # type: ignore[attr-defined]
    assert hi.item == "hi_potion"
    assert hi.price == 120
    assert hi.currency is None            # 缺省=商店 currency
    assert hi.scope == "personal"
    assert hi.stock is None
    assert hi.limit == 3
    assert hi.period == "day"
    assert hi.reputation_required == {}
    assert hi.min_level is None
    assert hi.discount is None
    assert hi.sold_out_once is False

    potion = grocery.items[0]  # type: ignore[attr-defined]
    assert potion.stock == 0              # stock 0=无限（TC-08）
    assert potion.sold_out_once is False
    assert potion.price == 50

    blacksmith = ShopDef.from_entry(_shop_by_id(shops, "blacksmith_shop"))
    mithril = blacksmith.items[2]  # type: ignore[attr-defined]
    assert mithril.stock == 10
    assert mithril.refresh.mode == "weekly"
    assert mithril.refresh.weekday == 1
    lucky = blacksmith.items[3]  # type: ignore[attr-defined]
    assert lucky.price == {"coins": 50, "gems": 5}   # 混合支付（TC-19）

    guild = ShopDef.from_entry(_shop_by_id(shops, "guild_shop"))
    assert guild.items[0].reputation_required.get("level") == 2  # type: ignore[attr-defined]
    assert guild.items[2].currency == "gems"  # type: ignore[attr-defined]
    assert guild.items[2].stock == 50  # type: ignore[attr-defined]

    festival = ShopDef.from_entry(_shop_by_id(shops, "festival_shop"))
    assert festival.items[1].sold_out_once is True # type: ignore[attr-defined]  # 一次性售罄（TC-11）

    stamina = grocery.items[4]  # type: ignore[attr-defined]
    assert stamina.min_level == 5


def test_shopitemdef_legacy_and_sides() -> None:
    """旧字段兼容 + 生效侧派生（裁决⑤：scope 只管默认侧；L450/L465 型无损表达）。"""
    # L450 型：stock 0 + per_player 0 同条目并存（global 无限库存 + personal 限购 0=不限）
    e450 = ShopItemDef.from_entry({"item": "potion", "price": 50, "stock": 0,
                                   LEGACY_PER_PLAYER: 0})
    assert e450.stock == 0
    assert e450.per_player == 0
    assert e450.effective_scope == "personal"     # 旧 per_player 存在 → 默认侧 personal
    assert e450.has_global_side is True           # stock 显式 → global 侧生效
    assert e450.has_personal_side is True         # per_player 显式 → personal 侧生效
    assert e450.uses_legacy_fields is True

    # L465 型：stock 10 + per_player 1 + per_player_period day 同条目并存
    e465 = ShopItemDef.from_entry({"item": "mithril", "price": 300, "stock": 10,
                                   LEGACY_PER_PLAYER: 1, LEGACY_PER_PLAYER_PERIOD: "day"})
    assert e465.stock == 10
    assert e465.per_player == 1
    assert e465.per_player_period == "day"
    assert e465.has_global_side is True
    assert e465.has_personal_side is True
    assert e465.effective_scope == "personal"

    # 仅新字段：scope 显式 personal → personal 侧；无 stock/per_player
    e = ShopItemDef.from_entry({"item": "x", "scope": "personal", "limit": 2, "period": "week"})
    assert e.effective_scope == "personal"
    assert e.has_personal_side is True
    assert e.has_global_side is False
    assert e.uses_legacy_fields is False

    # 缺省：无 scope/stock/per_player → 默认 global（stock 0=无限）
    e0 = ShopItemDef.from_entry({"item": "x", "price": 10})
    assert e0.effective_scope == SCOPE_DEFAULT == "global"
    assert e0.has_global_side is True
    assert e0.has_personal_side is False


def test_shopdef_defaults() -> None:
    """缺省兜底：type 缺省 normal、visible 缺省 true、refresh 缺省 none、listing_count 缺省。"""
    d = ShopDef.from_entry({"id": "x", "name": "路人小店", "items": [{"item": "potion"}]})
    assert d.type is None # type: ignore[attr-defined]  # raw 未写 type（默认 normal 为校验侧兜底）
    assert d.visible is True  # type: ignore[attr-defined]
    assert d.refresh.mode is None # type: ignore[attr-defined]  # 裁决⑥
    assert d.items[0].item == "potion"  # type: ignore[attr-defined]
    assert d.pool == ()  # type: ignore[attr-defined]
    assert d.price_fluctuation is None  # type: ignore[attr-defined]
    assert d.listing_count is None  # type: ignore[attr-defined]
    assert d.blackmarket_listing_n == len(d.items) == 1 # type: ignore[attr-defined]  # 缺省 N=len(items)（L216 字面口径）


# ---------------------------------------------------------------------------
# 裁决⑤/⑥
# ---------------------------------------------------------------------------
def test_ruling5_stock_and_per_player_coexist() -> None:
    """裁决⑤：stock+per_player 同条目并存（L450/L465 型）→ 零红拦；仅旧字段迁移黄提示。"""
    shops = _legal_shops()
    _shop_by_id(shops, "grocery_shop")["items"].append(
        {"item": "potion", "price": 50, "stock": 0, LEGACY_PER_PLAYER: 0})        # L450 型
    _shop_by_id(shops, "blacksmith_shop")["items"].append(
        {"item": "mithril", "price": 300, "stock": 10,
         LEGACY_PER_PLAYER: 1, LEGACY_PER_PLAYER_PERIOD: "day"})                  # L465 型
    rep = _check(shops)
    assert not rep.errors, f"并存条目不应有红拦：{rep.errors}"
    # 仅旧字段迁移黄提示（2 条并存条目）
    legacy = [w for w in _warns(rep, "shop_legacy_fields")
              if w["detail"].get("node_id") == "grocery_shop"
              or w["detail"].get("node_id") == "blacksmith_shop"]
    assert len(legacy) == 2
    # 并存条目本身无库存/限购结构红拦
    assert not _errs(rep, "shop_stock_invalid")
    assert not _errs(rep, "shop_per_player_invalid")
    assert not _errs(rep, "shop_entry_period_invalid")


def test_ruling6_refresh_default_none() -> None:
    """裁决⑥：不配置 refresh = 永不刷新（缺省不拦）；显式 none 合法；非法 mode 红拦。"""
    # 未配 refresh（grocery/festival 外的 normal 店）→ 零红拦
    shops = _legal_shops()
    rep = _check(shops)
    assert not _errs(rep, "shop_refresh_mode_required")
    assert not _errs(rep, "shop_refresh_mode_invalid")
    assert REFRESH_MODE_DEFAULT == "none"
    # 显式 {mode: none} 合法
    _shop_by_id(shops, "grocery_shop")["refresh"] = {"mode": "none"}
    rep = _check(shops)
    assert not _errs(rep, "shop_refresh_mode_invalid")
    assert not rep.errors
    # 非法 mode → 红拦
    _shop_by_id(shops, "grocery_shop")["refresh"] = {"mode": "hourly"}
    rep = _check(shops)
    assert len(_errs(rep, "shop_refresh_mode_invalid")) == 1


# ---------------------------------------------------------------------------
# id / name / items / type（TC-02 / §1.6）
# ---------------------------------------------------------------------------
def test_id_required_and_duplicate() -> None:
    """id 缺失 → 红拦；两店同 id → 红拦（唯一性）。"""
    shops = _legal_shops()
    shops[0]["id"] = ""
    rep = _check(shops)
    assert _errs(rep, "shop_id_required")
    shops = _legal_shops()
    shops[1]["id"] = "grocery_shop"
    rep = _check(shops)
    assert len(_errs(rep, "shop_id_duplicate")) == 1


def test_name_required_and_space_forbidden() -> None:
    """name 必填；含空格 → 红拦；·/Ⅱ 允许（合法 fixture 已覆盖）。"""
    shops = [_legal_shops()[0]]
    del shops[0]["name"]
    rep = _check(shops)
    assert _errs(rep, "shop_name_required")
    shops = [_legal_shops()[0]]
    shops[0]["name"] = "铁匠 老周"
    rep = _check(shops)
    assert len(_errs(rep, "shop_name_space_forbidden")) == 1
    shops[0]["name"] = "铁匠·老周Ⅱ"
    rep = _check(shops)
    assert not rep.errors


def test_items_required_and_empty_warning() -> None:
    """items 缺失 → 红拦；items=[]（非黑市）→ 黄提示「这家店空空的？」。"""
    shops = [_legal_shops()[0]]
    del shops[0]["items"]
    rep = _check(shops)
    assert _errs(rep, "shop_items_required")
    shops = [_legal_shops()[0]]
    shops[0]["items"] = []
    rep = _check(shops)
    assert not _errs(rep, "shop_items_required")
    assert len(_warns(rep, "shop_empty")) == 1


def test_type_enum() -> None:
    """type 枚举 5 类（定稿 L133）：非法 → 红拦；缺省 normal 不拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["type"] = "mall"
    rep = _check(shops)
    assert len(_errs(rep, "shop_type_invalid")) == 1
    shops[0].pop("type")
    rep = _check(shops)
    assert not _errs(rep, "shop_type_invalid")
    assert SHOP_TYPE_DEFAULT == "normal"
    assert set(SHOP_TYPES) == {"normal", "npc", "reputation", "event", "blackmarket"}
    assert SHOP_TYPE_NAMES["blackmarket"] == "黑市"


def test_entry_not_object() -> None:
    """items/pool 条目非对象 → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"] = ["potion", {"item": "antidote"}]
    rep = _check(shops)
    assert len(_errs(rep, "shop_entry_not_object")) == 1
    bm = _shop_by_id(_legal_shops(), "black_market")
    bm["pool"] = [123]
    rep = _check([bm])
    assert len(_errs(rep, "shop_pool_entry_not_object")) == 1


# ---------------------------------------------------------------------------
# 引用悬空（item / currency；TC-41 侧 / §1.6）
# ---------------------------------------------------------------------------
def test_item_ref_dangling() -> None:
    """item 引用不存在 → 红拦；items 模块缺失 → 跳过引用检查（默认放行）。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["item"] = "no_such_item"
    rep = _check(shops)
    assert len(_errs(rep, "shop_item_ref_missing")) == 1
    rep = _check(shops, items=None)
    assert not _errs(rep, "shop_item_ref_missing")


def test_currency_ref_unregistered() -> None:
    """currency 未注册 → 红拦（商店级 + 条目级）；自定义 settings 货币 → 合法。"""
    shops = [_legal_shops()[0]]
    shops[0]["currency"] = "souls"
    rep = _check(shops)
    assert len(_errs(rep, "shop_currency_unregistered")) == 1
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["currency"] = "souls"
    rep = _check(shops)
    assert len(_errs(rep, "shop_currency_unregistered")) == 1
    # 自定义 settings 货币注册后合法
    modules = _base_modules()
    modules["settings"]["currencies"].append({"id": "souls"})
    modules["shop"] = shops
    rep = _Report()
    validate_shops(modules, rep)
    assert not _errs(rep, "shop_currency_unregistered")
    # settings 模块缺失 → 默认模板兜底（coins/diamond）：coins 商店合法
    shops2 = [_legal_shops()[0]]           # grocery 用 coins（默认模板内）
    rep = _check(shops2, settings=None)
    assert not rep.errors


# ---------------------------------------------------------------------------
# refresh 四模式（§1.3 / 定稿 L281-285/L417 / TC-33~TC-36）
# ---------------------------------------------------------------------------
def test_refresh_mode_enum() -> None:
    """refresh.mode 非四枚举 → 红拦；四种模式各自合法。"""
    assert set(REFRESH_MODES) == {"daily", "weekly", "once", "none"}
    shops = [_legal_shops()[0]]
    shops[0]["refresh"] = {"mode": "minutely"}
    rep = _check(shops)
    assert len(_errs(rep, "shop_refresh_mode_invalid")) == 1
    for mode, conf in (("daily", {"mode": "daily", "hour": 5}),
                       ("weekly", {"mode": "weekly", "weekday": 1, "hour": 5}),
                       ("once", {"mode": "once", "start": "2026-09-01 00:00",
                                 "end": "2026-09-07 23:59"}),
                       ("none", {"mode": "none"})):
        shops[0]["refresh"] = conf
        rep = _check(shops)
        assert not _errs(rep, "shop_refresh_mode_invalid"), f"{mode} 应合法"
        assert not rep.errors, f"{mode} 不应有红拦：{rep.errors}"


def test_refresh_once_window_required_and_format() -> None:
    """once 缺 start/end 时间窗 → 红拦；格式不符 → 黄提示。"""
    shops = [_legal_shops()[0]]
    shops[0]["refresh"] = {"mode": "once"}
    rep = _check(shops)
    assert _errs(rep, "shop_refresh_once_start_missing")
    assert _errs(rep, "shop_refresh_once_end_missing")
    shops[0]["refresh"] = {"mode": "once", "start": "09-01", "end": "2026-09-07 23:59"}
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_refresh_once_format")) == 1
    assert REFRESH_HOUR_DEFAULT == 5


def test_refresh_hour_weekday_invalid() -> None:
    """daily hour / weekly weekday 非法 → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["refresh"] = {"mode": "daily", "hour": 25}
    rep = _check(shops)
    assert _errs(rep, "shop_refresh_hour_invalid")
    shops[0]["refresh"] = {"mode": "weekly", "weekday": 0}
    rep = _check(shops)
    assert _errs(rep, "shop_refresh_weekday_invalid")
    shops[0]["refresh"] = {"mode": "weekly", "weekday": 8}
    rep = _check(shops)
    assert _errs(rep, "shop_refresh_weekday_invalid")
    shops[0]["refresh"] = {"mode": "weekly", "weekday": 1, "hour": 5}
    rep = _check(shops)
    assert not rep.errors


def test_entry_refresh_invalid() -> None:
    """条目级 refresh（global 侧库存回满覆盖）mode 非法 → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["refresh"] = {"mode": "fortnightly"}
    rep = _check(shops)
    assert len(_errs(rep, "shop_refresh_mode_invalid")) == 1
    assert "shop.items.0.refresh" in _errs(rep, "shop_refresh_mode_invalid")[0]["field"]


# ---------------------------------------------------------------------------
# 价格校验链（TC-17~TC-20 / §1.6）
# ---------------------------------------------------------------------------
def test_price_invalid_values() -> None:
    """price 负数 / bool / 非数字 / 空对象 → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["price"] = -1
    rep = _check(shops)
    assert len(_errs(rep, "shop_price_invalid")) == 1
    shops[0]["items"][0]["price"] = True
    rep = _check(shops)
    assert len(_errs(rep, "shop_price_invalid")) == 1
    shops[0]["items"][0]["price"] = "cheap"
    rep = _check(shops)
    assert len(_errs(rep, "shop_price_invalid")) == 1
    shops[0]["items"][0]["price"] = {}
    rep = _check(shops)
    assert len(_errs(rep, "shop_price_invalid")) == 1   # 混合支付缺货币键
    assert "缺货币键" in _errs(rep, "shop_price_invalid")[0]["detail"]["msg"]


def test_price_mixed_payment_keys() -> None:
    """混合支付对象键值非法 / 键未注册 → 红拦；合法双币 → 零红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["price"] = {"coins": -5, "gems": 5}
    rep = _check(shops)
    assert len(_errs(rep, "shop_price_invalid")) == 1
    shops[0]["items"][0]["price"] = {"coins": 50, "souls": 5}
    rep = _check(shops)
    assert len(_errs(rep, "shop_price_currency_unregistered")) == 1
    shops[0]["items"][0]["price"] = {"coins": 50, "gems": 5}
    rep = _check(shops)
    assert not rep.errors


def test_price_zero_warning() -> None:
    """price=0 常驻商品 → 黄提示「免费商品确认？」（定稿 L423）。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["price"] = 0
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_price_zero")) == 1


def test_stock_limit_discount_negative() -> None:
    """stock/limit/discount/per_player 负数 → 红拦；stock 小库存（1~4）→ 黄提示（TC-09/定稿 L422）。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["stock"] = -1
    rep = _check(shops)
    assert _errs(rep, "shop_stock_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["items"][1]["limit"] = -1
    rep = _check(shops)
    assert _errs(rep, "shop_limit_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["items"][2]["discount"] = -5
    rep = _check(shops)
    assert _errs(rep, "shop_discount_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["items"][0][LEGACY_PER_PLAYER] = -1
    rep = _check(shops)
    assert _errs(rep, "shop_per_player_invalid")
    # stock 1~4 → 抢购黄提示
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["stock"] = 3
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_stock_small")) == 1


def test_discount_out_of_range() -> None:
    """discount >100 → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["discount"] = 150
    rep = _check(shops)
    assert _errs(rep, "shop_discount_invalid")


def test_scope_and_period_enum() -> None:
    """scope ∉ global/personal、period ∉ day/week/month → 红拦（§1.4#4/#8）。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["scope"] = "server"
    rep = _check(shops)
    assert _errs(rep, "shop_entry_scope_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["period"] = "hour"
    rep = _check(shops)
    assert _errs(rep, "shop_entry_period_invalid")
    assert set(LIMIT_PERIODS) == {"day", "week", "month"}
    # 旧 per_player_period 同样校验
    shops = [_legal_shops()[0]]
    shops[0]["items"][0][LEGACY_PER_PLAYER_PERIOD] = "hour"
    rep = _check(shops)
    assert _errs(rep, "shop_entry_period_invalid")


def test_sold_out_once_and_visible_bool() -> None:
    """sold_out_once / visible 非 bool → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["sold_out_once"] = "yes"
    rep = _check(shops)
    assert _errs(rep, "shop_entry_sold_out_once_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["visible"] = 1
    rep = _check(shops)
    assert _errs(rep, "shop_visible_invalid")


def test_level_gates_negative() -> None:
    """level_required / min_level 负数 → 红拦。"""
    shops = [_legal_shops()[0]]
    shops[0]["level_required"] = -1
    rep = _check(shops)
    assert _errs(rep, "shop_level_required_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["items"][0]["min_level"] = -1
    rep = _check(shops)
    assert _errs(rep, "shop_entry_min_level_invalid")


def test_reputation_required_validation() -> None:
    """reputation_required 结构：非对象 / level 非法 → 红拦；5 级制外 → 黄提示。"""
    shops = [_legal_shops()[0]]
    shops[0]["reputation_required"] = 5
    rep = _check(shops)
    assert _errs(rep, "shop_reputation_not_object")
    shops = [_legal_shops()[0]]
    shops[0]["reputation_required"] = {"level": -1}
    rep = _check(shops)
    assert _errs(rep, "shop_reputation_level_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["reputation_required"] = {"level": "two"}
    rep = _check(shops)
    assert _errs(rep, "shop_reputation_level_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["reputation_required"] = {"level": 9}
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_reputation_unreachable")) == 1
    assert REPUTATION_LEVELS == (1, 2, 3, 4, 5)
    assert REPUTATION_LEVEL_NAMES[3] == "信赖"


def test_price_fluctuation_bounds() -> None:
    """黑市 price_fluctuation 越界（<0 或 >50）→ 红拦；>30% → 黄提示（定稿 L141/L424）。"""
    shops = [_legal_shops()[0]]
    shops[0]["price_fluctuation"] = 51
    rep = _check(shops)
    assert _errs(rep, "shop_price_fluctuation_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["price_fluctuation"] = -1
    rep = _check(shops)
    assert _errs(rep, "shop_price_fluctuation_invalid")
    shops = [_legal_shops()[0]]
    shops[0]["price_fluctuation"] = 40
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_fluctuation_high")) == 1
    # 非黑市店也可配（引擎统一，仅数值域校验）
    shops = [_legal_shops()[0]]
    shops[0]["price_fluctuation"] = 20
    rep = _check(shops)
    assert not rep.errors


# ---------------------------------------------------------------------------
# 开放条件（统一条件引擎；TC-42）
# ---------------------------------------------------------------------------
def test_open_condition_structure_errors() -> None:
    """open_condition 结构红拦：var 未注册 / op 非法 / 空条件。"""
    shops = [_legal_shops()[0]]
    for cond, rule in (({"var": "foobar", "op": "eq", "value": 1}, "var_not_registered"),
                       ({"var": "is_night", "op": "xx", "value": True}, "op_invalid"),
                       ({}, "condition_empty")):
        shops[0]["open_condition"] = cond
        rep = _check(shops)
        assert len(_errs(rep, rule)) == 1, f"{rule} 应红拦"


def test_open_condition_soft_warnings() -> None:
    """open_condition 软提示：旧格式 / 事件未登记 → 黄提示不拦（只建议不限制）。"""
    shops = [_legal_shops()[0]]
    shops[0]["open_condition"] = {"type": "job", "var": "job", "op": "eq", "value": "剑士"}
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "legacy_format")) == 1
    shops[0]["open_condition"] = {"var": "[事件:落石]", "op": "ge", "value": 1}
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "event_not_registered")) == 1


def test_open_condition_combos() -> None:
    """open_condition 组合 any/all/not 嵌套合法 → 零记录。"""
    shops = [_legal_shops()[0]]
    shops[0]["open_condition"] = {"all": [
        {"var": "is_night", "op": "is", "value": True},
        {"not": {"var": "level", "op": "lt", "value": 3}},
    ]}
    rep = _check(shops)
    assert not rep.errors
    assert not rep.warnings


# ---------------------------------------------------------------------------
# 黑市专项（TC-41 / 定稿 §四 / 【工程补白】2）
# ---------------------------------------------------------------------------
def test_blackmarket_pool_and_listing() -> None:
    """黑市：pool 空 → 黄提示；listing_count/items/pool 三者皆空 → 黄提示（审查 P1-1 统一口径）。"""
    bm = copy.deepcopy(_shop_by_id(_legal_shops(), "black_market"))
    bm["pool"] = []
    rep = _check([bm])
    assert not rep.errors
    assert len(_warns(rep, "shop_blackmarket_pool_empty")) == 1
    # 正典形态 items=[] 无 listing_count（pool 非空）→ 不再误报（回退 len(pool)，定稿 L507）
    bm = copy.deepcopy(_shop_by_id(_legal_shops(), "black_market"))
    bm.pop(BLACKMARKET_LISTING_FIELD)
    bm["items"] = []
    rep = _check([bm])
    assert not rep.errors
    assert not _warns(rep, "shop_blackmarket_no_listing")
    # 三者皆空 → 黄提示
    bm = copy.deepcopy(_shop_by_id(_legal_shops(), "black_market"))
    bm.pop(BLACKMARKET_LISTING_FIELD)
    bm["items"] = []
    bm["pool"] = []
    rep = _check([bm])
    assert not rep.errors
    assert len(_warns(rep, "shop_blackmarket_no_listing")) == 1
    # listing_count 非法 → 红拦
    bm = copy.deepcopy(_shop_by_id(_legal_shops(), "black_market"))
    bm[BLACKMARKET_LISTING_FIELD] = -1
    rep = _check([bm])
    assert _errs(rep, "shop_listing_count_invalid")


def test_blackmarket_listing_n_resolution() -> None:
    """【工程补白】2 / 审查_M4实现_批次4 P1-1：黑市上架数量 N 解析统一口径
    （listing_count>0 → 该值；items 非空 → len(items)；否则 → len(pool)，对齐定稿 L216/L507 正典）。"""
    bm = _shop_by_id(_legal_shops(), "black_market")
    d = ShopDef.from_entry(bm)
    assert d.blackmarket_listing_n == 3 # type: ignore[attr-defined]  # listing_count=3
    bm2 = copy.deepcopy(bm)
    bm2.pop(BLACKMARKET_LISTING_FIELD)
    bm2["items"] = [{"item": "stardust", "price": 800}]
    d2 = ShopDef.from_entry(bm2)
    assert d2.blackmarket_listing_n == 1 # type: ignore[attr-defined]  # 回退 len(items)
    # 正典形态：items=[] 无 listing_count → 回退 len(pool)（定稿 L507，不再判 0）
    bm3 = copy.deepcopy(bm)
    bm3.pop(BLACKMARKET_LISTING_FIELD)
    bm3["items"] = []
    d3 = ShopDef.from_entry(bm3)
    assert d3.blackmarket_listing_n == len(bm3["pool"]) == 3 # type: ignore[attr-defined]  # 回退 len(pool)
    # items 与 pool 皆空 → 0（黄提示侧）
    bm4 = copy.deepcopy(bm)
    bm4.pop(BLACKMARKET_LISTING_FIELD)
    bm4["items"] = []
    bm4["pool"] = []
    d4 = ShopDef.from_entry(bm4)
    assert d4.blackmarket_listing_n == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 黄提示族：空店 / 同物不同价 / 未使用商店（TC-20 ③ 侧 / 定稿 L426-427）
# ---------------------------------------------------------------------------
def test_legacy_fields_migration_warning() -> None:
    """旧 per_player/per_player_period 使用 → 黄提示「建议迁移」（裁决⑤兼容 + 迁移建议）。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"].append({"item": "potion", "price": 50,
                              LEGACY_PER_PLAYER: 2, LEGACY_PER_PLAYER_PERIOD: "week"})
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_legacy_fields")) == 1


def test_same_item_diff_price_warning() -> None:
    """同物不同价（多条目同 item 不同 price）→ 黄提示（定稿 L427）；items 模块缺失 → 跳过。"""
    shops = [_legal_shops()[0]]
    shops[0]["items"].append({"item": "potion", "price": 60})  # 与 items[0] potion 50 不同价
    rep = _check(shops)
    assert not rep.errors
    assert len(_warns(rep, "shop_same_item_diff_price")) == 1
    # items 模块缺失 → 跳过（默认放行）
    rep = _check(shops, items=None)
    assert not _warns(rep, "shop_same_item_diff_price")


def test_unused_shop_warning() -> None:
    """未使用商店（npc 已声明 shop_refs 时，非 normal 店未被引用）→ 黄提示（定稿 L426）。"""
    shops = _legal_shops()
    modules = _base_modules()
    modules["shop"] = shops
    # npc 只引用 blacksmith_shop → guild/festival/black_market 未使用（grocery normal 豁免）
    modules["npc"] = [{"id": "lin", "shop_refs": ["blacksmith_shop"]}]
    rep = _Report()
    validate_shops(modules, rep)
    unused = _warns(rep, "shop_unused")
    assert len(unused) == 3
    ids = {w["detail"].get("id") for w in unused}
    assert ids == {"guild_shop", "festival_shop", "black_market"}
    # npc 未接线（模块缺失）→ 不触发
    rep = _check(shops)
    assert not _warns(rep, "shop_unused")
