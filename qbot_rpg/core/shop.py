"""商店引擎（M4 批次3·路D2 · qbot_rpg/core/shop.py）——浏览/购买原子防双扣/出售/刷新四模式/当前商店。

依据：
  - m4_shared_contract.md §3.2（C1-C6：五类型 normal/npc/reputation/event/blackmarket；stock 0=无限；
    sold_out_once 售出永久下架不随刷新恢复；**库存 + 个人限购同条目并存（裁决⑤）**；
    **个人限购清零以条目 period（day/week/month，默认每日 05:00）为准（裁决⑤）**；
    refresh 四模式 daily/weekly/once/none；**不配置 = 永不刷新（裁决⑥）**；
    刷新三件事（库存回满/限购清零/黑市重抽）同刻发生；原子防双扣（SQLite 事务 + 会话快照幂等）；
    当前商店机制（地图级状态兜底商店中断恢复）；/商店 /购买 /出售 + /商店 列表）
  - docs/细化/细化_2b3_商店引擎契约.md（§1.3 刷新四模式×5key + 刷新语义三件事 + 惰性补刷；
    §1.4 条目 12 字段 + 旧字段兼容映射；§1.5 五类型「引擎统一性铁律：type 只影响入口/可见性/刷新默认值，
    购买/限购/库存逻辑完全同一套」；§2 购买链路（6 步校验链 D-01 顺序即提示优先级 +
    原子结算 D-03 防双扣/防超卖 + D-05 数量上限提示不拦截）；§3 出售链路（基准价×比率/
    sell_price 覆盖 + 绑定/任务关键拦截 + 限购不计出售 D-04）；§四 当前商店机制（地图级 D-06）；
    §五 多货币结算（混合支付整单原子 D-02）；2026-08-27 裁决⑤⑥（P1-3/P1-4 用户拍板））
  - docs/审查参考/商店系统设计定稿.md（refresh §1.3 L281-292 刷新三件事 + 原子结算 L345-348 +
    校验链 L338-344 + 当前商店 L305-327 + 多货币 L193/L238-242 + 置灰不隐藏 L81/L219-220 +
    出售价 L191-192/L353-360 + 声望 5 级制【任务】L220/L229-240：陌生0/熟悉100/信赖300/崇敬600/传说1000）
  - M4 设计审查裁决（审查_M4设计_批次3_jspace.md P1-3 限购清零以 period 为准 / P1-4 默认 refresh=none）
  - M4 实现审查批次4（审查_M4实现_批次4_jspace.md P1-1：黑市 listing_count 引擎读取 + N 解析统一口径）

【工程补白 · 显式标注】（契约/定稿未给字段名或落点，按"只建议不限制"取点定型，命名可改）：
  1) 引擎零 IO、零 NoneBot import、纯函数（ctx dict 进出，就地改写可变子结构）；事务（SQLite）由调用方
     存储层负责——本模块在进程内以「快照-回滚」保证单次调用无中间态（见 8），跨进程/并发由调用方
     事务 + 条件式 UPDATE 兜底（D-03）。
  2) 状态落点（ctx 就地改写，持久化由调用方完成）：
       ctx["currencies"]          玩家货币表 {币键: int}（就地扣减/累加）
       ctx["inventory"]           in-memory 背包 {item_id: count}（可缺省，走 add_item/remove_item hook）
       ctx["add_item"]/["remove_item"]/["count_item"] hook：add_item(item_id,count,bound)->bool；
                                    remove_item(item_id,count)->bool；count_item(item_id)->int。
       ctx["personal_buys"]       个人限购计数 {shop_id: {item_id: {"count": int, "key": str}}}（玩家存档）
       ctx["world_stock"]         全服库存 {shop_id: {item_id: int}}（世界状态，跨群共享）
       ctx["world_sold_out"]      sold_out_once 永久下架标记 {shop_id: {item_id: True}}（世界状态）
       ctx["last_refresh"]        商店上次刷新日期键 {shop_id: "YYYY-MM-DD"}（世界状态）
       ctx["blackmarket_goods"]   黑市当前上架货架 {shop_id: [goods...]}（世界状态，含浮动后上架价）
       ctx["current_shop_ref"]    当前商店（地图级，NPC 2b1 已写入 refs[0]）；ctx["current_shop_refs"] 挂载列表
  3) 物品/商店注册表：ctx["items"]（dict id→item）或 ctx["resolve_item"]；ctx["shops"]（dict id→shop）
     或 ctx["resolve_shop"]。商店 type 引擎统一（1.5 铁律）：除黑市货架来源与刷新默认值外无分叉。
  4) 刷新时刻：统一配置键 refresh_time（默认 05:00，dayroll A3 唯一实现）；商店显式配 hour（daily/weekly）
     时按该店覆盖（2b3 §1.3「hour 默认 5」+ TC-41 黑市 hour:20）。个人限购 period 清零边界一律走
     全局 refresh_time（裁决⑤「独立驱动」），week 边界默认周一（settings.week_start 可配，默认 1=周一）。
  5) 黑市上架数 N（审查_M4实现_批次4 P1-1 统一口径，与 content/shop_models.blackmarket_listing_n/校验器一致）：
     listing_count>0 → N=listing_count；items 非空 → len(items)；否则 → len(pool)（示例 black_market
     items=[] pool=3 → 全池上架，定稿 L216/L507 正典）。刷新重抽：rng 注入确定性（ctx["rng"]，Random 实例
     或 random 模块），不重复抽样；上架价 = 基准价 × (1 ± price_fluctuation%)（randint，整型取整）；
     混合支付池条目不浮动。
  6) 校验链顺序即提示优先级（D-01）：①店存在且可见→②门槛→③限购→④库存→⑤货币→⑥数量上限。
     ⑥「提示不拦截」（D-05/TC-03）：先按上限截断执行量（余额/库存按截断后数量校验），再跑 ③④⑤；
     截断提示随结果携带（TC-03「按 99 截断执行」优先于链序）。
  7) 出售链路：价 = items 基准价 × settings.sell_ratio（默认 30%）向下取整，或 items.sell_price 单条覆盖；
     绑定/任务关键（sellable:false 或 id 前缀 x_，settings.sell_x_marker 可关，默认拦截）拒绝；
     大额确认（settings.sell_confirm_threshold>0 才启用，默认关）与货币持有上限（货币 cap 配置才拦截）
     均为可配兜底；出售不计限购、不碰全服库存（D-04）。
  8) 原子防双扣：buy/sell 结算阶段先做校验链全过再进入「快照-应用-失败回滚」；幂等闸复用 A1 模式
     （ctx["tx_id"]+ctx["ledger"]，同 tx 重复调用直接返回 idempotent，不重复扣款/入包）。
  9) 声望等级：读 ctx["reputation"]（int=等级 / mapping=按板，param 缺省 global，与 condition_engine 一致）；
     缺省回退按 ctx["reputation_state"] 值经阈值表换算（ctx["rep_levels"] 可配，默认 5 级制）；商店级与
     条目级门槛取更严（2b3 §2.2 ②）。

纯函数约定：同刻同参必同值；rng/now 注入确定性；工程补白显式标注。
"""

from __future__ import annotations

import copy
import math
import random
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Mapping, MutableMapping, MutableSet, Optional

from qbot_rpg.core.dayroll import (
    WINDOW_EXPIRED,
    WINDOW_NOT_STARTED,
    WINDOW_OPEN,
    is_window_open,
    normalize_hhmm,
    resolve_refresh_time,
    today_of,
    weeks_elapsed,
)
from qbot_rpg.engine.condition_engine import eval_condition

__all__ = [
    "SHOP_TYPES",
    "REFRESH_MODES",
    "PERIODS",
    "SCOPE_GLOBAL",
    "SCOPE_PERSONAL",
    "DEFAULT_BUY_CAP",
    "DEFAULT_SELL_RATIO",
    "DEFAULT_CURRENCY",
    "REPUTATION_LEVELS",
    "REPUTATION_NAMES",
    "resolve_shop",
    "shop_exists",
    "default_shop_id",
    "current_shop_id",
    "set_current_shop",
    "clear_current_shop",
    "resolve_shop_arg",
    "resolve_refresh",
    "shop_open_state",
    "shop_refresh_due",
    "shop_apply_refresh",
    "shop_lazy_refresh",
    "next_stock_message",
    "shop_goods",
    "resolve_goods_ref",
    "price_for",
    "personal_limit_state",
    "shop_browse",
    "shop_buy",
    "shop_sell",
    "shop_list",
]

# -------------------------------------------------------------------------------------
# 常量（对齐 2b3 §1.2/§1.3/§1.4 / 定稿 L133/L173/L176-177/L44 / 【任务】L220）
# -------------------------------------------------------------------------------------
SHOP_TYPES: tuple = ("normal", "npc", "reputation", "event", "blackmarket")
REFRESH_MODES: tuple = ("daily", "weekly", "once", "none")
PERIODS: tuple = ("day", "week", "month")

SCOPE_GLOBAL = "global"
SCOPE_PERSONAL = "personal"

# 数量上限默认 ≤99（可配，2b3 D-05 / 定稿 L44）
DEFAULT_BUY_CAP = 99
# 出售通用比率默认 30%（定稿 L191）
DEFAULT_SELL_RATIO = 0.30
# 默认货币键（settings 第一货币缺省；定稿 L134 / reward.DEFAULT_CURRENCY_IDS 口径 coins）
DEFAULT_CURRENCY = "coins"

# 声望 5 级制（【任务】L220/L229-240：陌生0/熟悉100/信赖300/崇敬600/传说1000；ctx["rep_levels"] 可配）
REPUTATION_LEVELS: tuple = (("陌生", 0), ("熟悉", 100), ("信赖", 300), ("崇敬", 600), ("传说", 1000))
REPUTATION_NAMES: tuple = tuple(name for name, _ in REPUTATION_LEVELS)

_TZ_UTC8 = timezone(timedelta(hours=8))

_WEEKDAY_NAMES: dict = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}

# 快照-回滚覆盖的可变 ctx 子结构（工程补白 8）
_SNAP_KEYS: tuple = (
    "currencies", "inventory", "personal_buys",
    "world_stock", "world_sold_out", "last_refresh", "blackmarket_goods",
)

# 出售到账默认货币名兜底（settings currencies[].name 优先）
_CURRENCY_NAME_FALLBACK: dict = {"coins": "金币", "gem": "宝石"}

_PAGE_SIZE = 10  # 一次一屏 ≤10 条（定稿 L82/L369）


# -------------------------------------------------------------------------------------
# 基础工具（纯函数）
# -------------------------------------------------------------------------------------
def _now(ctx: Mapping[str, Any]) -> int:
    """UTC+8 秒级时间戳：ctx["now"] 注入优先（确定性可测），缺省 = 当前。"""
    now = ctx.get("now")
    if now is not None:
        return int(now)
    return int(time.time())


def _rng(ctx: Mapping[str, Any]):
    """rng 注入：ctx["rng"]（Random 实例或 random 模块）→ 确定性；缺省 = random 模块。"""
    rng = ctx.get("rng")
    if rng is None:
        return random
    return rng


def _settings(ctx: Mapping[str, Any]) -> Mapping:
    settings = ctx.get("settings")
    return settings if isinstance(settings, Mapping) else {}


def _cfg(ctx: Mapping[str, Any]) -> Mapping:
    return _settings(ctx)


def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _first_currency(ctx: Mapping[str, Any]) -> str:
    """settings 第一货币键；缺省 = DEFAULT_CURRENCY。"""
    currencies = _settings(ctx).get("currencies")
    if isinstance(currencies, list) and currencies:
        for e in currencies:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
                return e["id"]
    return DEFAULT_CURRENCY


def _currency_name(ctx: Mapping[str, Any], key: str) -> str:
    """货币键 → 中文名（settings currencies[].name；缺省兜底表；再缺省原键）。"""
    currencies = _settings(ctx).get("currencies")
    if isinstance(currencies, list):
        for e in currencies:
            if isinstance(e, Mapping) and e.get("id") == key:
                name = e.get("name")
                if isinstance(name, str) and name:
                    return name
    return _CURRENCY_NAME_FALLBACK.get(key, key)


def _currency_cap(ctx: Mapping[str, Any], key: str) -> Optional[int]:
    """货币持有上限（settings currencies[].cap；未配 = None 不限）。"""
    currencies = _settings(ctx).get("currencies")
    if isinstance(currencies, list):
        for e in currencies:
            if isinstance(e, Mapping) and e.get("id") == key:
                cap = _as_int(e.get("cap"))
                if cap is not None and cap >= 0:
                    return cap
    return None


def _fmt(n: int) -> str:
    """千分位格式化（定稿「剩余 1,000 金币」）。"""
    return f"{int(n):,}"


def _resolve_item(item_id: object, ctx: Mapping[str, Any]) -> Optional[Mapping]:
    """物品注册表解析：ctx["items"] dict 或 ctx["resolve_item"] 解析器；查无 → None。"""
    if not isinstance(item_id, str):
        return None
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            return hit
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            hit = resolver(item_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


def _item_name(item_id: str, ctx: Mapping[str, Any]) -> str:
    item = _resolve_item(item_id, ctx)
    if item is not None:
        name = item.get("name")
        if isinstance(name, str) and name:
            return name
    return item_id


# -------------------------------------------------------------------------------------
# 商店解析 / 当前商店机制（2b3 §四 / 定稿 L305-327）
# -------------------------------------------------------------------------------------
def resolve_shop(ctx: Mapping[str, Any], shop_id: object) -> Optional[Mapping]:
    """商店定义解析：ctx["shops"] dict（id→shop）或 ctx["resolve_shop"] 解析器；查无 → None。"""
    if not isinstance(shop_id, str):
        return None
    shops = ctx.get("shops")
    if isinstance(shops, Mapping):
        hit = shops.get(shop_id)
        if isinstance(hit, Mapping):
            return hit
    resolver = ctx.get("resolve_shop")
    if callable(resolver):
        try:
            hit = resolver(shop_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


def shop_exists(ctx: Mapping[str, Any], shop_id: object) -> bool:
    return resolve_shop(ctx, shop_id) is not None


def _all_shop_ids(ctx: Mapping[str, Any]) -> List[str]:
    """全表商店 id（稳定序：dict 顺序或 resolve 缺省排序）。"""
    shops = ctx.get("shops")
    if isinstance(shops, Mapping):
        return [sid for sid in shops if isinstance(sid, str)]
    resolver = ctx.get("resolve_shop")
    if callable(resolver):
        ids = ctx.get("shop_ids")
        if isinstance(ids, (list, tuple)):
            return [sid for sid in ids if isinstance(sid, str)]
    return []


def default_shop_id(ctx: Mapping[str, Any]) -> Optional[str]:
    """全局默认商店：第一个 type=normal 的商店；无则第一个商店；空 → None（兜底 normal，定稿 L203/L212-213）。"""
    for sid in _all_shop_ids(ctx):
        shop = resolve_shop(ctx, sid)
        if shop is not None and shop.get("type", "normal") == "normal":
            return sid
    for sid in _all_shop_ids(ctx):
        if resolve_shop(ctx, sid) is not None:
            return sid
    return None


def current_shop_id(ctx: Mapping[str, Any]) -> Optional[str]:
    """当前商店（地图级，ctx["current_shop_ref"]）：引用存在才返回，否则 None（离图已清则回退默认）。"""
    ref = ctx.get("current_shop_ref")
    if isinstance(ref, str) and resolve_shop(ctx, ref) is not None:
        return ref
    return None


def set_current_shop(ctx: MutableMapping[str, Any], shop_id: object) -> None:
    """记录当前商店（地图级状态；打开瞬间写入，NPC 2b1 action:shop 已写 refs[0]）。"""
    ctx["current_shop_ref"] = shop_id


def clear_current_shop(ctx: MutableMapping[str, Any]) -> None:
    """清除当前商店（离开该地图 → /商店 回退全局默认，定稿 L312）。"""
    ctx["current_shop_ref"] = None


def resolve_shop_arg(ref: object, ctx: Mapping[str, Any]) -> Optional[str]:
    """/商店 [arg] → shop id（2b3 §四 TC-01/02/29-32 / 定稿 L37-39）：
      无参 → 当前商店 → 全局默认（normal 兜底）；
      int 序号 → 当前挂载 shop_refs 内切换（D-06）；无挂载回退全表序号（工程补白）；
      str 名称 → 先当前挂载精确匹配、再全表 name 精确匹配（禁空格、允许 ·/Ⅱ）。
    """
    if ref is None or ref == "":
        cur = current_shop_id(ctx)
        return cur or default_shop_id(ctx)
    # 当前挂载列表：ctx["current_shop_refs"]（NPC 多店）→ 回退当前商店单元素 → 全表（工程补白）
    refs = ctx.get("current_shop_refs")
    if isinstance(refs, (list, tuple)) and refs:
        base = [r for r in refs if isinstance(r, str) and resolve_shop(ctx, r) is not None]
    else:
        cur = current_shop_id(ctx)
        if cur is not None:
            base = [cur]
        else:
            base = _all_shop_ids(ctx)
    if not base:
        return None
    if isinstance(ref, int) and not isinstance(ref, bool):
        return base[ref - 1] if 1 <= ref <= len(base) else None
    if isinstance(ref, str):
        s = ref.strip()
        if not s:
            return None
        for sid in base:
            shop = resolve_shop(ctx, sid)
            if shop is not None and shop.get("name") == s:
                return sid
        # 全表名称匹配（当前商店不在挂载列表时）
        for sid in _all_shop_ids(ctx):
            shop = resolve_shop(ctx, sid)
            if shop is not None and shop.get("name") == s:
                return sid
        if s.isdigit():
            i = int(s)
            return base[i - 1] if 1 <= i <= len(base) else None
    return None


# -------------------------------------------------------------------------------------
# refresh 配置解析 / 开放门 / 惰性补刷（2b3 §1.3 / 定稿 L281-302 / 裁决⑤⑥）
# -------------------------------------------------------------------------------------
def resolve_refresh(refresh: object, ctx: Mapping[str, Any]) -> dict:
    """refresh 子对象归一（4 模式 × key）：
      daily   {mode, hour=5}
      weekly  {mode, weekday=1, hour=5}
      once    {mode, start, end}
      none    {mode}
    **裁决⑥：不配置（None/空 dict/非法 mode）= none = 永不刷新**（P1-4 / 2b3 §1.3 / 定稿 L285/L300）。
    """
    out: dict = {"mode": "none"}
    if not isinstance(refresh, Mapping):
        return out
    mode = refresh.get("mode")
    if mode not in REFRESH_MODES:
        return out
    out["mode"] = mode
    if mode == "daily":
        hour = _as_int(refresh.get("hour"))
        out["hour"] = hour if hour is not None else 5
    elif mode == "weekly":
        hour = _as_int(refresh.get("hour"))
        out["hour"] = hour if hour is not None else 5
        wd = _as_int(refresh.get("weekday"))
        out["weekday"] = wd if wd is not None and 1 <= wd <= 7 else 1
    elif mode == "once":
        out["start"] = refresh.get("start")
        out["end"] = refresh.get("end")
    return out


def _shop_refresh_cfg(ctx: Mapping[str, Any], shop: Mapping) -> Mapping:
    """刷新边界配置：全局 settings 上覆盖该店显式 hour（daily/weekly，工程补白 4 / TC-41）。"""
    base = dict(_settings(ctx))
    raw = shop.get("refresh")
    if isinstance(raw, Mapping) and raw.get("mode") in ("daily", "weekly") and "hour" in raw:
        base["refresh_time"] = normalize_hhmm(raw["hour"])
    return base


def _reset_offset(cfg: Mapping) -> timedelta:
    """日界偏移（与 dayroll A3 同口径）：刷新时刻 → timedelta。"""
    hhmm = resolve_refresh_time(cfg)
    return timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:5]))


def _shop_refresh_hhmm(ctx: Mapping[str, Any], shop: Mapping) -> str:
    """商店下次补货时刻（HH:MM）：该店显式 hour 覆盖全局 refresh_time。"""
    raw = shop.get("refresh")
    if isinstance(raw, Mapping) and raw.get("mode") in ("daily", "weekly") and "hour" in raw:
        return normalize_hhmm(raw["hour"])
    return resolve_refresh_time(_settings(ctx))


def shop_open_state(shop: Mapping, ctx: Mapping[str, Any]) -> dict:
    """商店开放门（校验链①）：visible / open_condition / once 时间窗。
    返回 {open: bool, reason: str|None, message: str|None}；
    open_condition 求值失败默认不满足（安全失败，TC-42）；once start 未到/end 已过 = 未开门（TC-34）。
    """
    if shop.get("visible") is False:
        return {"open": False, "reason": "hidden", "message": "❌ 这家店还没开门"}
    cond = shop.get("open_condition")
    if cond:
        if not eval_condition(cond, ctx):
            return {"open": False, "reason": "condition", "message": "❌ 这家店还没开门"}
    refresh = resolve_refresh(shop.get("refresh"), ctx)
    if refresh["mode"] == "once":
        st = is_window_open(refresh.get("start"), refresh.get("end"), _now(ctx))
        if st == WINDOW_NOT_STARTED:
            return {"open": False, "reason": "window_not_started", "message": "❌ 这家店还没开门"}
        if st == WINDOW_EXPIRED:
            return {"open": False, "reason": "window_expired", "message": "❌ 这家店还没开门"}
    return {"open": True, "reason": None, "message": None}


# ---- 世界状态存取（工程补白 2）-------------------------------------------------------
def _world_stock(ctx: Mapping[str, Any], shop_id: str, item_id: str, default: int) -> int:
    ws = ctx.get("world_stock")
    if isinstance(ws, Mapping):
        node = ws.get(shop_id)
        if isinstance(node, Mapping):
            v = node.get(item_id)
            if isinstance(v, int) and not isinstance(v, bool):
                return v
    return default


def _set_world_stock(ctx: MutableMapping[str, Any], shop_id: str, item_id: str, value: int) -> None:
    ws = ctx.setdefault("world_stock", {})
    ws.setdefault(shop_id, {})[item_id] = value


def _is_sold_out(ctx: Mapping[str, Any], shop_id: str, item_id: str) -> bool:
    so = ctx.get("world_sold_out")
    if isinstance(so, Mapping):
        node = so.get(shop_id)
        if isinstance(node, Mapping) and node.get(item_id):
            return True
    return False


def _mark_sold_out(ctx: MutableMapping[str, Any], shop_id: str, item_id: str) -> None:
    so = ctx.setdefault("world_sold_out", {})
    so.setdefault(shop_id, {})[item_id] = True


def _last_refresh(ctx: Mapping[str, Any], shop_id: str) -> Optional[str]:
    lr = ctx.get("last_refresh")
    if isinstance(lr, Mapping):
        v = lr.get(shop_id)
        if isinstance(v, str):
            return v
    return None


def _set_last_refresh(ctx: MutableMapping[str, Any], shop_id: str, key: str) -> None:
    ctx.setdefault("last_refresh", {})[shop_id] = key


def _blackmarket_goods(ctx: Mapping[str, Any], shop_id: str) -> Optional[list]:
    bg = ctx.get("blackmarket_goods")
    if isinstance(bg, Mapping):
        g = bg.get(shop_id)
        if isinstance(g, list):
            return g
    return None


def _set_blackmarket_goods(ctx: MutableMapping[str, Any], shop_id: str, goods: list) -> None:
    ctx.setdefault("blackmarket_goods", {})[shop_id] = list(goods)


# ---- 条目字段归一（2b3 §1.4 + 旧字段兼容 D-08 / 裁决⑤ 并存）-----------------------------
def _entry_stock(entry: Mapping) -> int:
    """条目 global 库存：stock（0=无限）；负/非法 → 0。"""
    v = _as_int(entry.get("stock"))
    return v if v is not None and v > 0 else 0


def _entry_limit(entry: Mapping) -> int:
    """条目 personal 限购：limit（或旧 per_player 兼容映射）；负/非法 → 0。"""
    v = _as_int(entry.get("limit"))
    if v is None or v <= 0:
        v = _as_int(entry.get("per_player"))
    return v if v is not None and v > 0 else 0


def _entry_period(entry: Mapping) -> str:
    """限购周期：period（或旧 per_player_period）；缺省 day。"""
    p = entry.get("period")
    if not isinstance(p, str) or p not in PERIODS:
        p = entry.get("per_player_period")
    return p if isinstance(p, str) and p in PERIODS else "day"


def _entry_sold_out_once(entry: Mapping) -> bool:
    return entry.get("sold_out_once") is True


def _entry_currency(entry: Mapping, shop: Mapping, ctx: Mapping[str, Any]) -> str:
    """货币解析（5.2 三层）：条目 currency → 商店 currency → settings 第一货币。"""
    c = entry.get("currency")
    if not isinstance(c, str) or not c:
        c = shop.get("currency")
    if not isinstance(c, str) or not c:
        c = _first_currency(ctx)
    return c


def _discount_price(price: int, discount: object) -> int:
    """折扣：price × (100 - discount%) // 100（discount 0~100 夹取）。"""
    d = _as_int(discount)
    if d is None:
        d = 0
    d = max(0, min(100, d))
    return price * (100 - d) // 100


def _fluctuate(base: int, pct: object, rng) -> int:
    """黑市价格浮动：基准价 × (1 ± pct%)（randint 确定性；0=固定价）。"""
    p = _as_int(pct)
    if p is None or p <= 0:
        return base
    spread = base * max(0, p) // 100
    return max(0, base + int(rng.randint(-spread, spread)))


def _redraw_blackmarket(shop: Mapping, ctx: Mapping[str, Any]) -> list:
    """黑市重抽（刷新三件事③ / TC-41）：pool 不重复抽样 N 件，上架价 = 基准价 × (1±浮动率)。
    N 解析（审查_M4实现_批次4 P1-1 统一口径，对齐定稿 L216/L507 正典）：listing_count>0 → 该值；
    items 非空 → len(items)；否则 → len(pool)；k 上限夹取 len(pool)。"""
    pool = shop.get("pool")
    if not isinstance(pool, list) or not pool:
        return []
    fluct = shop.get("price_fluctuation")
    items_cfg = shop.get("items")
    listing = _as_int(shop.get("listing_count"))
    if listing is not None and listing > 0:
        n = listing
    elif isinstance(items_cfg, list) and items_cfg:
        n = len(items_cfg)
    else:
        n = len(pool)
    rng = _rng(ctx)
    k = max(0, min(int(n), len(pool)))
    idxs = rng.sample(range(len(pool)), k)
    goods: List[dict] = []
    for i in idxs:
        entry = dict(pool[i])
        base = _entry_base_price(entry, ctx)
        if base is not None and fluct:
            entry["price"] = _fluctuate(base, fluct, rng)
        goods.append(entry)
    return goods


def _entry_base_price(entry: Mapping, ctx: Mapping[str, Any]) -> Optional[int]:
    """条目基准价：int price 直取；obj（混合支付）→ None（不浮动）；缺省 = items 基准价。"""
    raw = entry.get("price")
    if isinstance(raw, Mapping):
        return None
    base = _as_int(raw)
    if base is not None:
        return base
    item = _resolve_item(entry.get("item"), ctx)
    if item is not None:
        return _as_int(item.get("price"))
    return None


def _clear_shop_stock(ctx: MutableMapping[str, Any], shop_id: str) -> None:
    """清空该店全服库存计数（黑市重抽新货架从零计；sold_out 永久标记保留）。"""
    ws = ctx.get("world_stock")
    if isinstance(ws, MutableMapping):
        ws.pop(shop_id, None)


def shop_refresh_due(shop: Mapping, ctx: Mapping[str, Any]) -> bool:
    """惰性补刷判定（2b3 §1.3 / TC-33/35/36）：
      none → 永不（裁决⑥）；黑市首次无货架 → 需上架（初始抽选）；
      daily → 日界跨期（today_of refreshed）；weekly → 跨周 ≥1；once → 不周期补货（窗口门在 open_state）。
    """
    shop_id = shop["id"]
    is_bm = shop.get("type") == "blackmarket"
    if is_bm and _blackmarket_goods(ctx, shop_id) is None:
        return True  # 黑市首次上架（初始抽选；模式 none 也仅此一次）
    refresh = resolve_refresh(shop.get("refresh"), ctx)
    mode = refresh["mode"]
    if mode == "none":
        return False
    last = _last_refresh(ctx, shop_id)
    if last is None:
        return False  # 首启：库存初始即满，无需补刷（工程补白）
    cfg = _shop_refresh_cfg(ctx, shop)
    if mode == "daily":
        return bool(today_of(last, _now(ctx), cfg).get("refreshed"))
    if mode == "weekly":
        return weeks_elapsed(last, _now(ctx), cfg, weekday=refresh.get("weekday", 1)) >= 1
    return False


def shop_apply_refresh(shop: Mapping, ctx: MutableMapping[str, Any]) -> dict:
    """刷新三件事（2b3 §1.3 / 定稿 L289-292；裁决⑤ ②限购清零改由 period 独立驱动，本处不含）：
      ① 全体库存回满（sold_out_once 永久下架不恢复，TC-11）
      ③ 黑市商品重抽（pool 抽选 + 价格重浮动，货架 goods 列表保持打开）
      写 last_refresh = 当前日界键。
    返回 {refreshed: True, mode, goods, refilled: int, redrawn: bool}。
    """
    shop_id = shop["id"]
    is_bm = shop.get("type") == "blackmarket"
    if is_bm:
        goods = _redraw_blackmarket(shop, ctx)
        _set_blackmarket_goods(ctx, shop_id, goods)
        _clear_shop_stock(ctx, shop_id)
    else:
        goods = list(shop.get("items", []) or [])
        _clear_shop_stock(ctx, shop_id)
    refilled = 0
    for entry in goods:
        stock = _entry_stock(entry)
        if stock <= 0:
            continue
        item_id = entry.get("item")
        if not isinstance(item_id, str):
            continue
        if _is_sold_out(ctx, shop_id, item_id):
            continue  # 一次性售罄永久下架（TC-11）
        _set_world_stock(ctx, shop_id, item_id, stock)
        refilled += 1
    cfg = _shop_refresh_cfg(ctx, shop)
    key = today_of(None, _now(ctx), cfg).get("today", "")
    _set_last_refresh(ctx, shop_id, key)
    return {"refreshed": True, "mode": resolve_refresh(shop.get("refresh"), ctx)["mode"],
            "goods": goods, "refilled": refilled, "redrawn": is_bm}


def shop_lazy_refresh(shop_id: str, ctx: MutableMapping[str, Any]) -> dict:
    """惰性补刷入口：操作商店时按时间差补算（TC-33/35 离线多天一次补到当前，不逐周期重放）。"""
    shop = resolve_shop(ctx, shop_id)
    if shop is None:
        return {"refreshed": False, "reason": "no_shop"}
    if not shop_refresh_due(shop, ctx):
        return {"refreshed": False}
    return shop_apply_refresh(shop, ctx)


def next_stock_message(shop: Mapping, ctx: Mapping[str, Any]) -> Optional[str]:
    """「下次补货：明早 ${refresh_time}」（定稿 L97）：daily → 明早 HH:MM；weekly → 下周X HH:MM；
      none/once/sold_out 无周期补货 → None。"""
    refresh = resolve_refresh(shop.get("refresh"), ctx)
    if refresh["mode"] == "daily":
        return f"明早 {_shop_refresh_hhmm(ctx, shop)}"
    if refresh["mode"] == "weekly":
        wd = refresh.get("weekday", 1)
        return f"下周{_WEEKDAY_NAMES.get(wd, '一')} {_shop_refresh_hhmm(ctx, shop)}"
    return None


# -------------------------------------------------------------------------------------
# 货架 / 商品解析 / 价格 / 个人限购（2b3 §1.4/§2/裁决⑤）
# -------------------------------------------------------------------------------------
def shop_goods(shop: Mapping, ctx: Mapping[str, Any]) -> list:
    """当前上架货架：黑市 = blackmarket_goods（已抽选+浮动价）；其余 = items[]。"""
    if shop.get("type") == "blackmarket":
        g = _blackmarket_goods(ctx, shop["id"])
        if g is None:
            return []  # 尚未上架（调用方须先 shop_lazy_refresh）
        return g
    return list(shop.get("items", []) or [])


def resolve_goods_ref(goods: list, ref: object, ctx: Mapping[str, Any]) -> Optional[Mapping]:
    """货架内商品解析（2b3 §2.1 名称优先 → item id → 列表序号）：查无 → None。"""
    if isinstance(ref, int) and not isinstance(ref, bool):
        return goods[ref - 1] if 1 <= ref <= len(goods) else None
    if isinstance(ref, str):
        s = ref.strip()
        if not s:
            return None
        for e in goods:
            item = _resolve_item(e.get("item"), ctx)
            if item is not None and item.get("name") == s:
                return e
        for e in goods:
            if e.get("item") == s:
                return e
        if s.isdigit():
            i = int(s)
            return goods[i - 1] if 1 <= i <= len(goods) else None
    return None


def price_for(entry: Mapping, shop: Mapping, ctx: Mapping[str, Any]) -> dict:
    """条目结算单价（折扣后）：
      single → {kind:"single", unit:int, currency:str}（条目覆盖价 → items 基准价 → 0；currency 三层解析）
      mixed  → {kind:"mixed", parts:{币键:int}}（price 对象两币同扣，D-02）
    """
    raw = entry.get("price")
    if isinstance(raw, Mapping):
        parts: dict = {}
        for k, v in raw.items():
            amount = _as_int(v)
            if amount is None or amount < 0:
                amount = 0
            parts[k] = _discount_price(amount, entry.get("discount"))
        return {"kind": "mixed", "parts": parts}
    base = _as_int(raw)
    if base is None:
        item = _resolve_item(entry.get("item"), ctx)
        if item is not None:
            base = _as_int(item.get("price"))
    if base is None:
        base = 0
    unit = _discount_price(base, entry.get("discount"))
    return {"kind": "single", "unit": unit, "currency": _entry_currency(entry, shop, ctx)}


def _period_bucket_key(period: str, ctx: Mapping[str, Any]) -> str:
    """限购周期桶键（裁决⑤：period 独立驱动；边界 = 全局 refresh_time 日界）：
      day → 归属日期键；week → 本周边界（默认周一）日期键；month → 当月首日日期键。
    """
    cfg = _cfg(ctx)
    now = _now(ctx)
    offset = _reset_offset(cfg)
    shifted = datetime.fromtimestamp(now, tz=_TZ_UTC8) - offset
    d: date = shifted.date()
    if period == "day":
        return d.isoformat()
    if period == "week":
        ws = _as_int(_settings(ctx).get("week_start"))
        wd = ws if ws is not None and 1 <= ws <= 7 else 1
        start = d - timedelta(days=(d.weekday() - (wd - 1)) % 7)
        return start.isoformat()
    return d.replace(day=1).isoformat()


def _personal_node(ctx: MutableMapping[str, Any], shop_id: str, item_id: str) -> dict:
    pb = ctx.setdefault("personal_buys", {})
    return pb.setdefault(shop_id, {}).setdefault(item_id, {})


def personal_limit_state(entry: Mapping, shop_id: str, ctx: MutableMapping[str, Any]) -> dict:
    """个人限购状态（裁决⑤：以条目 period 独立驱动惰性清零）：
      返回 {limit, count, period, bucket, key, reset: bool}；
      跨期访问 → 计数清零并更新桶键（玩家操作时补算，TC-15 隔天可再买）。
    """
    limit = _entry_limit(entry)
    if limit <= 0:
        return {"limit": 0, "count": 0, "period": None, "bucket": None, "key": None, "reset": False}
    period = _entry_period(entry)
    item_id = entry.get("item")
    if not isinstance(item_id, str):
        item_id = str(item_id)
    key = _period_bucket_key(period, ctx)
    node = _personal_node(ctx, shop_id, item_id)
    reset = False
    if node.get("key") != key:
        node["count"] = 0
        node["key"] = key
        reset = True
    return {"limit": limit, "count": int(node.get("count", 0)), "period": period,
            "bucket": f"{shop_id}:{item_id}", "key": key, "reset": reset}


# -------------------------------------------------------------------------------------
# 声望 / 等级门槛（校验链②）
# -------------------------------------------------------------------------------------
def _rep_levels(ctx: Mapping[str, Any]) -> list:
    levels = ctx.get("rep_levels")
    if isinstance(levels, (list, tuple)) and levels:
        return [(name, _as_int(th) or 0) for name, th in levels]
    return list(REPUTATION_LEVELS)


def _player_rep_level(ctx: Mapping[str, Any]) -> int:
    """玩家声望等级（1 起）：
      ctx["reputation"] int = 等级（与 condition_engine 同口径）；mapping = 按板读 global；
      缺省回退按 ctx["reputation_state"] 值经阈值表换算（工程补白 9）。
    """
    rep = ctx.get("reputation")
    if isinstance(rep, Mapping):
        v = rep.get("global", rep.get("default", 0))
    elif isinstance(rep, int) and not isinstance(rep, bool):
        return max(1, rep)  # 已是等级
    else:
        rs = ctx.get("reputation_state")
        v = 0
        if isinstance(rs, Mapping):
            v = rs.get("global", rs.get("default", 0))
    v = _as_int(v) or 0
    lvl = 1
    for i, (_name, th) in enumerate(_rep_levels(ctx), start=1):
        if v >= th:
            lvl = i
    return lvl


def _rep_name(ctx: Mapping[str, Any], level: int) -> str:
    levels = _rep_levels(ctx)
    if 1 <= level <= len(levels):
        return str(levels[level - 1][0])
    return f"L{level}"


def _requirement_state(shop: Mapping, entry: Mapping, ctx: Mapping[str, Any]) -> dict:
    """门槛状态（校验链② / TC-37/38）：商店级与条目级取更严。
      返回 {ok, level_need, level_have, rep_need, rep_have}。
    """
    level_need = max(_as_int(shop.get("level_required")) or 0, _as_int(entry.get("min_level")) or 0)
    level_have = _as_int(ctx.get("level")) or 0
    shop_rep = _as_int((shop.get("reputation_required") or {}).get("level")) or 0
    entry_rep = _as_int((entry.get("reputation_required") or {}).get("level")) or 0
    rep_need = max(shop_rep, entry_rep)
    rep_have = _player_rep_level(ctx)
    return {"ok": level_have >= level_need and rep_have >= rep_need,
            "level_need": level_need, "level_have": level_have,
            "rep_need": rep_need, "rep_have": rep_have}


# -------------------------------------------------------------------------------------
# 快照-回滚（原子防双扣 · 进程内兜底，工程补白 8）
# -------------------------------------------------------------------------------------
def _snapshot(ctx: Mapping[str, Any]) -> dict:
    return {k: copy.deepcopy(ctx.get(k)) for k in _SNAP_KEYS}


def _restore(ctx: MutableMapping[str, Any], snap: dict) -> None:
    for k, v in snap.items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v


class _Rollback(Exception):
    """结算阶段失败标记（进程内回滚触发）。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int, bound: bool) -> bool:
    """入包：优先 ctx["add_item"] hook；回退 ctx["inventory"] in-memory；均无 → False。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, bound))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))    # hook 返回 object，运行时 int() 归一
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


# -------------------------------------------------------------------------------------
# 浏览 / 购买 / 出售 / 列表
# -------------------------------------------------------------------------------------
def _browse_row(entry: Mapping, index: int, shop: Mapping, ctx: Mapping[str, Any]) -> dict:
    """单商品行（置灰不隐藏，TC-07）：含价格/货币名/标记/greyed 判定，供指令层渲染。"""
    item_id = entry.get("item")
    price = price_for(entry, shop, ctx)
    stock = _entry_stock(entry)
    remaining = _world_stock(ctx, shop["id"], item_id, stock) if stock > 0 else None  # type: ignore[arg-type]
    sold_out = stock > 0 and (_is_sold_out(ctx, shop["id"], item_id) or remaining <= 0)  # type: ignore[arg-type,operator]
    req = _requirement_state(shop, entry, ctx)
    # 反斜杠续行行尾无法挂 type: ignore → 改括号化三元式（M6 基线路B，语义不变）
    pl = (personal_limit_state(entry, shop["id"], ctx) if _entry_limit(entry) > 0 else # type: ignore[arg-type]
          {"limit": 0, "count": 0, "period": None})
    markers: List[str] = []
    greyed = False
    if stock > 0:
        if sold_out:
            markers.append("已售罄")
            greyed = True
        else:
            markers.append(f"全服剩 {remaining}")
    if pl["limit"] > 0:  # type: ignore[operator]
        label = {"day": "每日", "week": "每周", "month": "每月"}.get(pl["period"], "每日")  # type: ignore[arg-type]
        if pl["count"] >= pl["limit"]:  # type: ignore[operator]
            markers.append(f"{label}限购 {pl['limit']}（已满）")
            greyed = True
        else:
            markers.append(f"{label}限购 {pl['limit']}")
    if req["level_need"] > req["level_have"]:
        markers.append(f"需要 LV{req['level_need']}")
        greyed = True
    if req["rep_need"] > req["rep_have"]:
        markers.append(f"需要 {_rep_name(ctx, req['rep_need'])}")
        greyed = True
    discount = _as_int(entry.get("discount")) or 0
    return {
        "index": index,
        "item_id": item_id,
        "name": _item_name(item_id, ctx),  # type: ignore[arg-type]
        "price": price,
        "discount": discount,
        "original_unit": _entry_base_price(entry, ctx) or 0,
        "markers": markers,
        "greyed": greyed,
        "can_buy": not greyed,
        "stock_remaining": remaining,
        "sold_out": sold_out,
    }


def shop_browse(shop_id: str, ctx: MutableMapping[str, Any], page: int = 1) -> dict:
    """/商店：商品列表（一次一屏 ≤10，页码夹取，2b3 §四 TC-01/05/06/07）。
    返回 {ok, reason?, message?, shop, title, rows, page, pages, total, tip}。
    """
    shop = resolve_shop(ctx, shop_id)
    if shop is None:
        return {"ok": False, "reason": "no_shop", "message": "❌ 商店不存在"}
    gate = shop_open_state(shop, ctx)
    if not gate["open"]:
        return {"ok": False, "reason": gate["reason"], "message": gate["message"]}
    shop_lazy_refresh(shop_id, ctx)
    goods = shop_goods(shop, ctx)
    rows = [_browse_row(e, i, shop, ctx) for i, e in enumerate(goods, start=1)]
    total = len(rows)
    pages = max(1, math.ceil(total / _PAGE_SIZE))
    p = _as_int(page) or 1
    p = max(1, min(p, pages))  # 页码越界夹取最后一页（用户裁决② / 3d P0-2）
    slice_rows = rows[(p - 1) * _PAGE_SIZE: p * _PAGE_SIZE]
    level = _as_int(ctx.get("level")) or 0
    name = ctx.get("name") or ""
    return {
        "ok": True,
        "shop": {
            "id": shop["id"], "name": shop.get("name", ""), "icon": shop.get("icon", ""),
            "type": shop.get("type", "normal"), "desc": shop.get("desc", ""),
        },
        "title": f"LV{level}.{name}",
        "rows": slice_rows,
        "page": p, "pages": pages, "total": total,
        "tip": "发送'购买+物品名'即可购买商品",
    }


def _buy_cap(ctx: Mapping[str, Any]) -> int:
    cap = _as_int(_settings(ctx).get("buy_cap"))
    return cap if cap is not None and cap > 0 else DEFAULT_BUY_CAP


def _paid_display(total: Mapping[str, int], ctx: Mapping[str, Any]) -> str:
    """「250 金币」/「50 金币 5 宝石」（混合支付双币同显，TC-19）。"""
    return " ".join(f"{amt} {_currency_name(ctx, k)}" for k, amt in total.items())


def shop_buy(shop_id: str, ref: object, count: object, ctx: MutableMapping[str, Any]) -> dict:
    """/购买 <物品>*<数量>：6 步校验链（D-01 顺序即提示优先级）+ 单事务原子结算（D-03 防双扣/防超卖）。
    返回成功 {ok, message, bought, paid, remaining, truncated, advisory, applied, idempotent}；
    失败 {ok:False, reason, message, detail?}。调用方应包裹 SQLite 事务（存储层）。
    """
    # 幂等闸（会话快照幂等，定稿 L347 / A1 模式，工程补白 8）
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None and isinstance(ledger, MutableSet) and tx_id in ledger:
        return {"ok": True, "idempotent": True, "message": "✅ 已结算（重复指令，未重复扣款）",
                "bought": {}, "paid": {}, "remaining": {}, "truncated": False,
                "advisory": None, "applied": False}

    # ① 商店存在且可见（含 open_condition/时间窗）
    shop = resolve_shop(ctx, shop_id)
    if shop is None:
        return {"ok": False, "reason": "no_shop", "message": "❌ 商店不存在"}
    gate = shop_open_state(shop, ctx)
    if not gate["open"]:
        return {"ok": False, "reason": gate["reason"], "message": gate["message"]}
    shop_lazy_refresh(shop_id, ctx)
    goods = shop_goods(shop, ctx)
    entry = resolve_goods_ref(goods, ref, ctx)
    if entry is None:
        return {"ok": False, "reason": "no_item", "message": "❌ 没有这个商品"}

    # 数量归一 + ⑥ 数量上限（D-05 提示不拦截：先截断执行量，TC-03）
    n = _as_int(count)
    if n is None or n <= 0:
        return {"ok": False, "reason": "invalid_count", "message": "❌ 数量无效"}
    cap = _buy_cap(ctx)
    truncated = n > cap
    n = min(n, cap)
    advisory = "最多一次购买 %d 个" % cap if truncated else None

    item_id = entry.get("item")
    if not isinstance(item_id, str):
        return {"ok": False, "reason": "no_item", "message": "❌ 没有这个商品"}

    # ② 门槛（等级/声望，商店级与条目级取更严）
    req = _requirement_state(shop, entry, ctx)
    if req["level_need"] > req["level_have"]:
        return {"ok": False, "reason": "requirement",
                "message": f"❌ 等级不足：需要 LV{req['level_need']}（当前 LV{req['level_have']}）",
                "detail": {"need": req["level_need"], "have": req["level_have"]}}
    if req["rep_need"] > req["rep_have"]:
        return {"ok": False, "reason": "requirement",
                "message": f"❌ 声望不足：需要 {_rep_name(ctx, req['rep_need'])}（当前 {_rep_name(ctx, req['rep_have'])}）",
                "detail": {"need": req["rep_need"], "have": req["rep_have"]}}

    # ③ 个人限购（period 独立驱动惰性清零，裁决⑤）
    pl = personal_limit_state(entry, shop_id, ctx)
    if pl["limit"] > 0 and pl["count"] + n > pl["limit"]:
        label = {"day": "今日", "week": "本周", "month": "本月"}.get(pl["period"], "今日")
        return {"ok": False, "reason": "limit",
                "message": f"❌ {label}限购 {pl['limit']} 个，已买 {pl['count']} 个",
                "detail": {"limit": pl["limit"], "count": pl["count"], "period": pl["period"]}}

    # ④ 全体库存（global 有限库存；D-03 条件式扣减）
    stock = _entry_stock(entry)
    if stock > 0:
        if _is_sold_out(ctx, shop_id, item_id):
            return {"ok": False, "reason": "stock", "message": "❌ 已售罄（不再补货）",
                    "detail": {"remaining": 0}}
        remaining = _world_stock(ctx, shop_id, item_id, stock)
        if remaining < n:
            tail = next_stock_message(shop, ctx)
            msg = f"❌ 已售罄（下次补货：{tail}）" if tail else "❌ 已售罄"
            return {"ok": False, "reason": "stock", "message": msg,
                    "detail": {"remaining": remaining, "next": tail}}

    # ⑤ 货币余额（含混合支付两币整单判定 D-02：任一不足整单拒绝，提示只指缺的那一币）
    price = price_for(entry, shop, ctx)
    currencies = ctx.get("currencies")
    if not isinstance(currencies, MutableMapping):
        return {"ok": False, "reason": "missing_bucket", "message": "❌ 无法结算货币"}
    total: dict = {}
    if price["kind"] == "mixed":
        for k, unit in price["parts"].items():
            total[k] = unit * n
    else:
        total[price["currency"]] = price["unit"] * n
    for k, amt in total.items():
        have = int(currencies.get(k, 0))
        if have < amt:
            return {"ok": False, "reason": "funds",
                    "message": f"❌ {_currency_name(ctx, k)}不足：还差 {_fmt(amt - have)}",
                    "detail": {"currency": k, "need": amt, "have": have}}

    # 入包通道必须存在（否则扣款无落点，原子性破坏前拒绝）
    if not callable(ctx.get("add_item")) and not isinstance(ctx.get("inventory"), MutableMapping):
        return {"ok": False, "reason": "storage_missing", "message": "❌ 无法入包（背包通道缺失）"}

    # ---- 原子结算（单事务语义：快照 → 应用 → 失败回滚）----
    snap = _snapshot(ctx)
    try:
        for k, amt in total.items():
            currencies[k] = int(currencies.get(k, 0)) - amt
        if not _add_item(ctx, item_id, n, bound=False):
            raise _Rollback("item_add_failed")
        if stock > 0:
            remaining = _world_stock(ctx, shop_id, item_id, stock)
            if remaining < n:
                raise _Rollback("stock_exhausted")  # 并发兜底（D-03 条件式）
            _set_world_stock(ctx, shop_id, item_id, remaining - n)
            if remaining - n == 0 and _entry_sold_out_once(entry):
                _mark_sold_out(ctx, shop_id, item_id)  # 永久下架（TC-11）
        if pl["limit"] > 0:
            node = _personal_node(ctx, shop_id, item_id)
            node["count"] = int(node.get("count", 0)) + n  # 仅买入成功 +1（D-04）
    except _Rollback as exc:
        _restore(ctx, snap)
        return {"ok": False, "reason": exc.reason, "message": "❌ 结算失败，已回滚"}

    if tx_id is not None and isinstance(ledger, MutableSet):
        ledger.add(tx_id)

    remaining_cur = {k: int(currencies.get(k, 0)) for k in total}
    item_name = _item_name(item_id, ctx)
    msg = f"✅ 购买成功：{item_name}×{n}（-{_paid_display(total, ctx)}），" \
          f"剩余 {_fmt(remaining_cur.get(next(iter(total)), 0))} {_currency_name(ctx, next(iter(total)))}"
    if advisory:
        msg += f"；{advisory}"
    return {
        "ok": True,
        "message": msg,
        "bought": {"item_id": item_id, "name": item_name, "count": n},
        "paid": total,
        "remaining": remaining_cur,
        "truncated": truncated,
        "advisory": advisory,
        "applied": True,
        "idempotent": False,
    }


def _sell_ratio(ctx: Mapping[str, Any]) -> float:
    ratio = _settings(ctx).get("sell_ratio")
    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio >= 0:
        return float(ratio)
    return DEFAULT_SELL_RATIO


def _sell_unit_price(item: Mapping, item_id: str, ctx: Mapping[str, Any]) -> int:
    """出售单价（3b/定稿 L191-192/L353）：items.sell_price 单条覆盖；否则基准价 × 比率（向下取整）。"""
    sp = _as_int(item.get("sell_price"))
    if sp is not None:
        return max(0, sp)
    base = _as_int(item.get("price")) or 0
    return int(base * _sell_ratio(ctx))  # 取整向下（floor）


def shop_sell(ref: object, count: object, ctx: MutableMapping[str, Any]) -> dict:
    """/出售 <物品>*<数量>：立刻到账（定稿 L354），限购不计（D-04）。
    返回成功 {ok, message, sold, unit, total, balance, currency, idempotent}；
    拦截 {ok:False, reason, message}；可选大额确认/货币上限（默认关）。
    """
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None and isinstance(ledger, MutableSet) and tx_id in ledger:
        return {"ok": True, "idempotent": True, "message": "✅ 已结算（重复指令，未重复到账）",
                "sold": {}, "unit": 0, "total": 0, "balance": 0, "currency": None}

    item_id = None
    item: Optional[Mapping] = None
    if isinstance(ref, str):
        s = ref.strip()
        items = ctx.get("items")
        if isinstance(items, Mapping):
            for iid, it in items.items():
                if isinstance(it, Mapping) and it.get("name") == s:
                    item_id, item = iid, it
                    break
        if item is None:
            item = _resolve_item(s, ctx)
            if item is not None:
                item_id = s
    elif isinstance(ref, int) and not isinstance(ref, bool):
        return {"ok": False, "reason": "no_item", "message": "❌ 没有这个物品"}
    if item is None or not isinstance(item_id, str):
        return {"ok": False, "reason": "no_item", "message": "❌ 没有这个物品"}

    # 数量归一
    n = _as_int(count)
    if n is None or n <= 0:
        return {"ok": False, "reason": "invalid_count", "message": "❌ 数量无效"}

    # 校验拦截（定稿 L357-359）
    if item.get("bound") is True:
        return {"ok": False, "reason": "bound", "message": "❌ 绑定物品无法出售"}
    if item.get("sellable") is False:
        return {"ok": False, "reason": "unsellable", "message": "❌ 任务关键物品无法出售"}
    sell_x = _settings(ctx).get("sell_x_marker", True)
    if sell_x is not False and item_id.startswith("x_"):
        return {"ok": False, "reason": "unsellable", "message": "❌ 任务关键物品无法出售"}
    have = _count_item(ctx, item_id)
    if have < n:
        return {"ok": False, "reason": "insufficient",
                "message": f"❌ 背包里只有 {have} 个{_item_name(item_id, ctx)}",
                "detail": {"have": have, "need": n}}

    unit = _sell_unit_price(item, item_id, ctx)
    total = unit * n
    currency = _first_currency(ctx)
    cur_name = _currency_name(ctx, currency)

    # 大额确认（可选默认关，定稿 L355）
    threshold = _as_int(_settings(ctx).get("sell_confirm_threshold"))
    if threshold is not None and threshold > 0 and total > threshold:
        return {"ok": False, "reason": "need_confirm",
                "message": "确认出售？金额较大（回收 %d %s）" % (total, cur_name),
                "detail": {"total": total, "unit": unit, "currency": currency}}

    currencies = ctx.get("currencies")
    if not isinstance(currencies, MutableMapping):
        return {"ok": False, "reason": "missing_bucket", "message": "❌ 无法结算货币"}
    cap = _currency_cap(ctx, currency)
    balance = int(currencies.get(currency, 0))
    if cap is not None and balance + total > cap:
        return {"ok": False, "reason": "currency_cap",
                "message": f"{cur_name}已满，无法再获得（当前 {_fmt(balance)}/{_fmt(cap)}）",
                "detail": {"currency": currency, "cap": cap, "balance": balance}}

    # 立刻到账（快照-回滚）
    snap = _snapshot(ctx)
    try:
        if not _remove_item(ctx, item_id, n):
            raise _Rollback("item_remove_failed")
        currencies[currency] = balance + total
    except _Rollback as exc:
        _restore(ctx, snap)
        return {"ok": False, "reason": exc.reason, "message": "❌ 结算失败，已回滚"}

    if tx_id is not None and isinstance(ledger, MutableSet):
        ledger.add(tx_id)

    new_balance = int(currencies.get(currency, 0))
    msg = f"✅ 出售成功：{_item_name(item_id, ctx)}×{n}（+{_fmt(total)} {cur_name}），" \
          f"剩余 {_fmt(new_balance)} {cur_name}"
    return {"ok": True, "message": msg,
            "sold": {"item_id": item_id, "name": _item_name(item_id, ctx), "count": n},
            "unit": unit, "total": total, "balance": new_balance, "currency": currency,
            "idempotent": False}


def shop_list(ctx: MutableMapping[str, Any], page: int = 1) -> dict:
    """/商店 列表：可见商店一览（含类型图标/门槛标记，置灰不隐藏，定稿 L42/L363-370）。
    返回 {ok, rows, page, pages, total, tip}；每行 {id,name,icon,type,level_required,
    reputation_required,desc,greyed,markers}。
    """
    rows = []
    for sid in _all_shop_ids(ctx):
        shop = resolve_shop(ctx, sid)
        if shop is None or shop.get("visible") is False:
            continue
        req = {"level_need": _as_int(shop.get("level_required")) or 0,
               "rep_need": _as_int((shop.get("reputation_required") or {}).get("level")) or 0}
        markers = []
        greyed = False
        if req["level_need"] > (_as_int(ctx.get("level")) or 0):
            markers.append(f"需要 LV{req['level_need']}")
            greyed = True
        if req["rep_need"] > _player_rep_level(ctx):
            markers.append(f"需要 {_rep_name(ctx, req['rep_need'])}")
            greyed = True
        rows.append({
            "id": sid, "name": shop.get("name", ""), "icon": shop.get("icon", ""),
            "type": shop.get("type", "normal"), "desc": shop.get("desc", ""),
            "level_required": req["level_need"], "reputation_required": req["rep_need"],
            "markers": markers, "greyed": greyed,
        })
    total = len(rows)
    pages = max(1, math.ceil(total / _PAGE_SIZE))
    p = _as_int(page) or 1
    p = max(1, min(p, pages))
    return {"ok": True, "rows": rows[(p - 1) * _PAGE_SIZE: p * _PAGE_SIZE],
            "page": p, "pages": pages, "total": total,
            "tip": "/商店 序号 切换商店"}
