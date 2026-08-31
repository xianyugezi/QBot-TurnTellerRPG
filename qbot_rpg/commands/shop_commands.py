"""商店指令接线 shop_commands.py（M4 批次3·路D3 重派 · qbot_rpg/commands/shop_commands.py）。

依据：
  - m4_shared_contract.md §2.3（基础指令组 + GM 指令，页码夹取口径）+ §3.2（C1-C6 商店：
    /商店 /购买 /出售 + /商店 列表（补缺漏）；stock 0=无限；库存+个人限购并存裁决⑤；
    刷新不配=永不刷新裁决⑥）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、页码越界夹取 +
    「已到最后一页」裁决②、0/负数/非数字 → TPL-12、错误模板统一、emoji 纪律）
  - docs/细化/细化_2b3_商店引擎契约.md（§2.1 入口 /商店 /购买 /出售 + 补缺漏 /商店 列表；
    §2.2 校验链 6 步顺序即提示优先级 D-01；§2.3 原子结算；§三 出售链路；§四 当前商店机制 D-06；
    §五 多货币；TC-01~42）+ 2026-08-27 用户裁决②（页码夹取最后一页）
  - docs/细化/细化_3d_消息模板规范.md（§1.2 TPL-08 页脚 / TPL-12 指令出错；§二 列表分页；
    §四 emoji 禁令；§5.4 错误文案唯一源）+ docs/细化/细化_4f（RUL-16 页码夹取）
  - qbot_rpg/core/shop.py（批次3·路D2 引擎，本模块为其**指令壳接线消费方**）

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /商店 /购买 /出售 三条指令从 Router 接到
core/shop.py 引擎——指令解析（parsers.parse_command 已 token 化 → 本模块取 args/qty）、
商店解析（引擎 resolve_shop_arg：无参→当前→默认；序号/名称）、列表渲染（core/message_format/
list_render 5 条/页 + TPL-08 页脚 + 裁决② 页码夹取）、购买/出售结果透传（引擎已按定稿模板
合成 ✅/❌ 业务文案）、错误统一 TPL-12（sender.format_tpl12，文案唯一源 errors.py D-04）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性（now/rng 由 ctx 注入）；
工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌ 功能性标记
+ 配置化商店 icon 数据图标豁免，m4 §2.2）。本模块只做「装配接线 + 渲染」，业务结算全部委托引擎。

【工程补白 · 显式标注】
  1) **跨路分页口径收敛**：引擎 core/shop.py shop_browse/shop_list 按定稿 L82「一次一屏 ≤10」切片
     （_PAGE_SIZE=10）；m4 §2.2 / 3d D-02 横切要求**列表 5 条/页 + TPL-08 页脚**（m4 实现层唯一权威）。
     本模块以「逐页取全量行 → 5 条/页重分页」收敛：`_all_browse_rows`/`_all_shop_rows` 把引擎
     10 条切片合并为全量，再由 list_render 口径分页渲染；尾段只用 render_cake_tail
     （CakeGame 式「当前页 + Tip」，2026-08-27 用户拍板），禁止自造页脚。裁决② 夹取与
     TPL-12 由本层统一判定（引擎侧 10 条夹取被本层 5 条口径覆盖）。
  2) **/商店 <整数> 二义性裁决（2b3 TC-02 序号切换 vs 3d/m4 §2.2 页码横切）**：整数参数**页码优先**
     （m4 §2.2「/商店 2 翻页」+ CakeGame 尾段「当前页：X/Y」跨系统自洽）；页码超当前店 5 条总页数
     且命中可用商店序号（resolve_shop_arg）→ 商店切换（TC-02）；两者皆不中 → 夹取最后一页 +
     「已到最后一页」（裁决②）。0/负数/非数字 → TPL-12（裁决②）。商店切换另经「/商店 <名称>」
     （名称精确匹配，定稿 L39/L131）与「/商店 列表」一览。
  3) **引擎 title 字段（"LV{等级}.{玩家名}"）不采用**：3d §3.1 前缀首行由装配层 prefix_render
     （TPL-01~06）统一渲染，本层只输出正文（店名头 + 商品行 + 页脚），避免双前缀。
  4) **/购买 /出售 目标解析**（名称优先 → 序号兜底）与全部业务文案（✅/❌ 购买成功/校验链六步
     提示/出售拦截）由引擎负责（2b3 §2.1/§2.2/§三 + 定稿 L94-100/L360）；本层透传 `message`，
     余额不足「❌ 金币不足：还差 X」即 2b3 校验链⑤ 差额口径（任务要求「余额不足提示差额」）。
  5) 本模块的玩家上下文工厂 `make_context`（NoneBot 事件 + 存储 → ctx dict）由装配层注入
     （register_shop_commands 的 make_context 参数），**批次6/7 装配待接线**；注入前本层可纯
     函数单测（直接构造 ctx）。
"""

from __future__ import annotations

import math
from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.message_format import strip_icon_emoji
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）
from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_cake_tail,
    resolve_page,
)
from qbot_rpg.core.shop import (
    resolve_shop_arg,
    shop_browse,
    shop_buy,
    shop_list,
    shop_sell,
)

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .basic_commands import TPL_REGISTER_GATE
from .parsers import parse_int
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名常量
    "SHOP_CMD", "BUY_CMD", "SELL_CMD", "LIST_KEYWORD",
    # 商店类型徽标 / 业务模板常量
    "TYPE_BADGES", "TPL_NO_SHOP", "TPL_REGISTER_GATE",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_shop", "cmd_shop_list", "cmd_shop_browse", "cmd_buy", "cmd_sell",
    # 渲染
    "render_shops_overview", "render_shop_items", "format_number",
    # 装配
    "register_shop_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SHOP_CMD = "商店"
BUY_CMD = "购买"
SELL_CMD = "出售"
LIST_KEYWORD = "列表"

# 商店类型徽标（列表/浏览头，数据型功能徽标，非装饰 emoji——纯文本）
TYPE_BADGES: Mapping[str, str] = {
    "normal": "[普通商店]",
    "npc": "[NPC 商店]",
    "reputation": "[声望商店]",
    "event": "[活动商店]",
    "blackmarket": "[黑市]",
}

# 商店不存在（引擎校验链① 口径，no_shop 分支；未开门分支由引擎 gate message 透传）
# 渲染走 register_rem_tpl 分区 shop_no_shop（2026-08-31 模板配置化；本常量保留为 API/测试锚点）
TPL_NO_SHOP = "❌ 商店不存在"

# 商店条目行分隔线（2b3 TC-05：条目间 `---------------` 分隔）
_ROW_SEPARATOR = "---------------"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def format_number(n: object) -> str:
    """千分位格式化（定稿「剩余 1,000 金币」；int 归一，非法原样 str）。"""
    if isinstance(n, bool) or not isinstance(n, (int, float, str)):
        return str(n)
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛：ctx["registered"] is False → 拦截文案；缺省视为已注册。

    2026-08-31 QA 修复：/商店 /购买 /出售 此前缺门槛，未注册玩家可直接浏览/交易。
    """
    if ctx.get("registered", True) is False:
        return TPL_REGISTER_GATE
    return None


def _currency_name(ctx: Mapping[str, Any], key: object) -> str:
    """货币键 → 中文名（settings currencies[].name；缺省兜底表；再缺省原键）。

    【工程补白】镜像引擎 _currency_name 私有实现（settings 消费语义一致，避免跨层改引擎）。
    """
    settings = ctx.get("settings") if isinstance(ctx, Mapping) else None
    currencies = settings.get("currencies") if isinstance(settings, Mapping) else None
    if isinstance(currencies, list):
        for e in currencies:
            if isinstance(e, Mapping) and e.get("id") == key:
                name = e.get("name")
                if isinstance(name, str) and name:
                    return name
    return {"coins": "金币", "gem": "宝石"}.get(key, key) if isinstance(key, str) else str(key)


def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _price_text(price: object, ctx: Mapping[str, Any]) -> str:
    """商品单价文本：single → 「100(金币)」；mixed → 「50(金币)+5(宝石)」（2b3 TC-05/TC-19）。

    模板化：shop_price_single / shop_price_part（register_rem_tpl 分区，内容包可覆盖）。
    """
    if not isinstance(price, Mapping):
        return "?"
    kind = price.get("kind")
    if kind == "mixed":
        parts = price.get("parts")
        if isinstance(parts, Mapping):
            return "+".join(
                tpl_of(ctx, "shop_price_part", {"amount": amt, "currency": _currency_name(ctx, k)})
                for k, amt in parts.items()
            )
        return "?"
    unit = price.get("unit")
    cur = _currency_name(ctx, price.get("currency", ""))
    return tpl_of(ctx, "shop_price_single", {"unit": unit, "currency": cur})


# ---------------------------------------------------------------------------
# 引擎行合并（跨路分页口径收敛，工程补白 1）
# ---------------------------------------------------------------------------

def _all_browse_rows(shop_id: str, ctx: MutableMapping[str, Any]) -> tuple:
    """取该店全部商品行（引擎 shop_browse 按 ≤10 切片返回；逐页合并至 total，再 5 条/页重分页）。

    返回 (rows, last_meta)；shop 不存在/未开门时 rows=[] 且 meta=shop_browse 的
    {ok:False, message}（消息透传）。防御：最多 200 页防异常数据死循环。
    """
    rows: List[Any] = []
    meta: Optional[dict] = None
    page = 1
    while True:
        res = shop_browse(shop_id, ctx, page)
        if not res.get("ok"):
            return [], res
        meta = res
        rows.extend(res.get("rows", []))
        if len(rows) >= int(res.get("total", 0)):
            break
        page += 1
        if page > 200:
            break
    return rows, meta


def _all_shop_rows(ctx: MutableMapping[str, Any]) -> tuple:
    """取全部可见商店行（shop_list 按 ≤10 切片；合并全量再 5 条/页重分页）。"""
    rows: List[Any] = []
    meta: Optional[dict] = None
    page = 1
    while True:
        res = shop_list(ctx, page)
        if not res.get("ok"):
            return [], res
        meta = res
        rows.extend(res.get("rows", []))
        if len(rows) >= int(res.get("total", 0)):
            break
        page += 1
        if page > 200:
            break
    return rows, meta


# ---------------------------------------------------------------------------
# 渲染（5 条/页 + CakeGame 式尾段（当前页 + Tip）+ 裁决② 页码夹取；纯文本，零装饰 emoji）
# ---------------------------------------------------------------------------

def _paginate(items: list, page: object,
              per_page: int = DEFAULT_PAGE_SIZE) -> tuple:
    """5 条/页分页（裁决②：超页夹取 + clamped 标记；非法页码由调用方先经 resolve_page 判 TPL-12）。

    返回 (slice, page, total_pages, total, clamped)。
    """
    res = resolve_page(page, len(items), per_page)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应先经 resolve_page 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * per_page
    sl = list(items[start:start + per_page])
    return sl, res.page, res.total_pages, res.total, res.clamped


def _browse_header(shop: Mapping[str, Any], ctx: Optional[Mapping[str, Any]] = None) -> str:
    """商品列表头（模板配置化 2026-08-31：shop_header，内容包可覆盖）：
    第一行 `{name} {类型徽标}`，介绍单独另起一行（用户拍板）；表头不计入 5 条上限。"""
    parts: List[str] = []
    name = f"{strip_icon_emoji(shop.get('icon', ''))}{shop.get('name', '')}"
    parts.append(name or "商店")
    t = shop.get("type", "normal")
    if t in TYPE_BADGES:
        parts.append(TYPE_BADGES[t])
    line1 = " ".join(parts)
    return tpl_of(ctx, "shop_header",
                  {"name": line1, "badge": "", "desc": str(shop.get("desc") or "")})

def _browse_row_text(row: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
    """商品行（模板配置化 2026-08-31：shop_row，内容包可覆盖）：
    `序号.物品名 ｜ 商品单价：价格(货币名) 标记`（折扣只附 `[折扣 -X%]`，模板 shop_discount_marker）。"""
    idx = row.get("index", "?")
    name = row.get("name", "?")
    price = _price_text(row.get("price"), ctx)
    discount = row.get("discount") or 0
    markers = list(row.get("markers", []) or [])
    if discount:
        markers.append(tpl_of(ctx, "shop_discount_marker", {"discount": discount}))
    marker_txt = " " + " ".join(str(m) for m in markers) if markers else ""
    return tpl_of(ctx, "shop_row", {"idx": idx, "name": name, "price": price, "markers": marker_txt})


def render_shop_items(shop: Mapping[str, Any], rows: list, page: object,
                      ctx: Mapping[str, Any], *,
                      per_page: int = DEFAULT_PAGE_SIZE) -> str:
    """商店商品列表正文：店名头 + 商品行（条目间分隔线）+ CakeGame 式尾段（当前页 + Tip）；
    裁决② 夹取 → （已到最后一页）插在 Tip 前。"""
    sl, pg, pgs, total, clamped = _paginate(rows, page, per_page)
    if not sl:
        return f"{_browse_header(shop, ctx)}\n{tpl_of(ctx, 'shop_browse_empty')}"
    body = f"\n{_ROW_SEPARATOR}\n".join(_browse_row_text(r, ctx) for r in sl)
    out: List[str] = [_browse_header(shop, ctx), body]
    tail = render_cake_tail(pg, pgs, tip=tpl_of(ctx, "shop_browse_tail_tip"))
    if clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    out.append(tail)
    return "\n".join(out)


def _shop_row(index: int, row: Mapping[str, Any], ctx: Optional[Mapping[str, Any]] = None) -> str:
    """商店一览行（定稿 L42/L367-370）：`序号. {icon}{name} {类型徽标} {desc} {门槛标记}`。

    序号前缀模板化：shop_overview_row_prefix（register_rem_tpl 分区，内容包可覆盖）。
    """
    name = f"{strip_icon_emoji(row.get('icon', ''))}{row.get('name', '')}"
    parts: List[str] = [tpl_of(ctx, "shop_overview_row_prefix",
                               {"index": index, "name": name or "?"})]
    t = row.get("type", "normal")
    if t in TYPE_BADGES:
        parts.append(TYPE_BADGES[t])
    if row.get("desc"):
        parts.append(str(row["desc"]))
    line = " ".join(parts)
    markers = list(row.get("markers", []) or [])
    if markers:
        line += " " + " ".join(str(m) for m in markers)
    return line


def render_shops_overview(rows: list, page: object, *,
                          ctx: Optional[Mapping[str, Any]] = None,
                          per_page: int = DEFAULT_PAGE_SIZE) -> str:
    """`/商店 列表`：可用商店一览（类型图标/门槛标记，置灰不隐藏）+ 5 条/页 + CakeGame 式尾段
    （当前页 + Tip）+ 裁决② 夹取。标题/尾段 Tip 模板化：shop_list_title / shop_list_tail_tip。"""
    sl, pg, pgs, total, clamped = _paginate(rows, page, per_page)
    lines: List[str] = [tpl_of(ctx, "shop_list_title")]
    start = (pg - 1) * per_page
    lines.extend(_shop_row(start + i + 1, r, ctx) for i, r in enumerate(sl))
    tail = render_cake_tail(pg, pgs, tip=tpl_of(ctx, "shop_list_tail_tip"))
    if clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    lines.append(tail)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx → 回复正文）
# ---------------------------------------------------------------------------

def cmd_shop_browse(parsed: Any, ctx: MutableMapping[str, Any], shop_id: Optional[str],
                    page: object) -> str:
    """浏览指定商店商品列表（页夹取 + CakeGame 式尾段；店不存在/未开门 → 引擎消息透传）。"""
    if not shop_id:
        return tpl_of(ctx, "shop_no_shop")
    rows, meta = _all_browse_rows(shop_id, ctx)
    if meta is None or not meta.get("ok"):
        return str(meta.get("message") or tpl_of(ctx, "shop_no_shop")) if meta else tpl_of(ctx, "shop_no_shop")
    return render_shop_items(meta.get("shop") or {}, rows, page, ctx)


def cmd_shop_list(parsed: Any, ctx: MutableMapping[str, Any], page: object) -> str:
    """`/商店 列表`：可用商店一览（页码 0/负数/非数字 → TPL-12；超页 → 夹取最后一页）。"""
    rows, meta = _all_shop_rows(ctx)
    if meta is None or not meta.get("ok"):
        return tpl_of(ctx, "shop_no_shop")
    return render_shops_overview(rows, page, ctx=ctx)


def cmd_shop(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """.../商店 [参数] 主入口：

      无参        → 当前商店（地图级）商品列表第 1 页；无则全局默认 normal 兜底（D-06/TC-01）
      列表 [页码] → 可用商店一览（5 条/页 + CakeGame 式尾段 + 裁决② 夹取）
      <名称>     → 名称精确切换商店 → 浏览其商品（TC-02；可带页码，3d §2.2 最后整数=页码）
      <整数>     → 页码优先（m4 §2.2 翻页）→ 超页命中商店序号则切店（TC-02）→ 否则夹取（裁决②）
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    gate = _gate(ctx)
    if gate is not None:
        return gate
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return cmd_shop_browse(parsed, ctx, resolve_shop_arg(None, ctx), 1)
    first = str(args[0])

    # 列表一览
    if first == LIST_KEYWORD:
        page: object = 1
        if len(args) > 1:
            n = parse_int(str(args[1]))
            if n is None or n < 1:
                return format_tpl12(f"/{SHOP_CMD} {LIST_KEYWORD} {args[1]}")
            page = n
        return cmd_shop_list(parsed, ctx, page)

    # 整数：页码优先 → 超页切店 → 夹取（工程补白 2）
    n = parse_int(first)
    if n is not None:
        if n < 1:
            return format_tpl12(f"/{SHOP_CMD} {first}")
        cur = resolve_shop_arg(None, ctx)
        if cur is None:
            return tpl_of(ctx, "shop_no_shop")
        rows, meta = _all_browse_rows(cur, ctx)
        if meta is None or not meta.get("ok"):
            return str(meta.get("message") or tpl_of(ctx, "shop_no_shop")) if meta else tpl_of(ctx, "shop_no_shop")
        pages5 = max(1, math.ceil(len(rows) / DEFAULT_PAGE_SIZE))
        if n > pages5:
            sid = resolve_shop_arg(n, ctx)
            if sid is not None and sid != cur:
                return cmd_shop_browse(parsed, ctx, sid, 1)
        return render_shop_items(meta.get("shop") or {}, rows, n, ctx)

    # 名称（可带页码）
    sid = resolve_shop_arg(first, ctx)
    if sid is None:
        return format_tpl12(f"/{SHOP_CMD} {first}")
    page2: object = 1
    if len(args) > 1:
        pn = parse_int(str(args[1]))
        if pn is None or pn < 1:
            return format_tpl12(f"/{SHOP_CMD} {first} {args[1]}")
        page2 = pn
    return cmd_shop_browse(parsed, ctx, sid, page2)


def _target_of(parsed: Any) -> str:
    """购买/出售目标名剥离（解析器契约 + 紧凑 `+` 连接符收敛）：

    - 解析器契约：args[0] 保留原文含 `*数量`，qty 已结构化 → 剥离 `*N` 后传引擎
      （`/购买 药水*5` → args=["药水*5"], qty=5 → 目标 "药水"）。
    - 【工程补白】紧凑格式 `'购买+药水'`（2b3 TC-04 / 定稿 L87）中 `+` 为紧凑连接符，
      batch-1 解析器把 `+` 归为等级分隔符 → args[0]="+药水"；购买/出售目标名不含 `+`
      （保留字符 N01），故剥离前导 `+` 收敛（`购买+药水*5` → "+药水*5" → "药水"）。
    """
    t = str(parsed.args[0])
    if t.startswith("+"):
        t = t[1:]
    if "*" in t:
        t = t.split("*", 1)[0]
    return t


def cmd_buy(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/购买 <物品|序号>*<数量>：目标解析（名称优先→序号兜底）与 6 步校验链/原子结算全部委托引擎；
    结果 `message` 透传（含余额不足差额提示、数量上限提示不拦截）。缺参/解析错误 → TPL-12。"""
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    gate = _gate(ctx)
    if gate is not None:
        return gate
    if not parsed.args:
        return format_tpl12(f"/{BUY_CMD}")
    target = _target_of(parsed)
    qty = parsed.qty if parsed.qty is not None else 1
    shop_id = resolve_shop_arg(None, ctx)
    res = shop_buy(shop_id, target, qty, ctx)  # type: ignore[arg-type]  # None=无商店→校验链① no_shop
    return str(res.get("message") or tpl_of(ctx, "shop_buy_fail"))


def cmd_sell(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/出售 <物品>*<数量>：立刻到账（引擎）；绑定/任务关键/数量不足拦截消息透传。缺参 → TPL-12。"""
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    gate = _gate(ctx)
    if gate is not None:
        return gate
    if not parsed.args:
        return format_tpl12(f"/{SELL_CMD}")
    target = _target_of(parsed)
    qty = parsed.qty if parsed.qty is not None else 1
    res = shop_sell(target, qty, ctx)
    return str(res.get("message") or tpl_of(ctx, "shop_sell_fail"))


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次6/7 待接线）
# ---------------------------------------------------------------------------

def register_shop_commands(router: Any, *, make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /商店 /购买 /出售 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 items/shops/settings/currencies/
        inventory/personal_buys/world_stock/current_shop_ref 等，见 core/shop.py 工程补白 2）。
        None 时 handler 调用抛 RuntimeError（【待接线】批次6/7 装配入口注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】shop_commands.register_shop_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _shop(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_shop(parsed, injected)
        return cmd_shop(parsed, _ctx(parsed))

    def _buy(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_buy(parsed, injected)
        return cmd_buy(parsed, _ctx(parsed))

    def _sell(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_sell(parsed, injected)
        return cmd_sell(parsed, _ctx(parsed))

    router.register(CommandSpec(SHOP_CMD, handler=_shop))
    router.register(CommandSpec(BUY_CMD, handler=_buy))
    router.register(CommandSpec(SELL_CMD, handler=_sell))
    return router
