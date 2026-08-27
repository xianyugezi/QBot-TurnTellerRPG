"""列表分页渲染（细化_3d §二 列表分页 + m4_shared_contract §2.2 + 2026-08-27 用户裁决②）。

依据：m4_shared_contract §2.2（列表 5 条/页上限 + 页脚固定 TPL-08 + 页码夹取 + 错误模板统一 + emoji 纪律）
     + 细化_3d_消息模板规范 §1.2（TPL-07 条目行 / TPL-08 页脚）、§二（列表分页：5 条上限/
       页码输入/页脚格式）、§四（功能性标记与 emoji 禁令 D-01）、§5.4（错误文案唯一源 D-04）
     + 2026-08-27 用户裁决②（3d 尾注）：超总页数 → 夹取最后一页 + 「已到最后一页」；
       0/负数/非数字 → TPL-12 报错（本模块只标记 invalid，文案由壳层组装）
     + 细化_4f_基础指令组契约 RUL-16（页码越界夹取）/ RUL-18（页脚 TPL-08 应用）

铁律（m4_shared_contract §0）：纯函数、零 NoneBot import、模板字符串不硬编码路径。
- 页脚固定 TPL-08，禁止各系统自造页脚（3d D-02/D-05）：系统渲染列表一律引用本模块 render_footer。
- 页码非法（0/负数/非数字）→ 本模块 resolve_page 标记 invalid=True；TPL-12 文案唯一源 =
  commands/errors.py（3d D-04），因 core→commands 依赖方向禁止（3a R3），由壳层 sender 组装。
- 装饰性 emoji 全局禁用（3d §四 D-01）：本模块输出（条目行/页脚/夹取提示）均为纯文本，零 emoji。

（注：panel_render.paginate 为 M0 遗留切片工具；本模块是 M4 列表模板唯一实现——5 条/页 +
裁决② 夹取 + TPL-08 页脚。后续系统按 3d D-05 引用本模块，不另造页脚。
2026-08-27 用户拍板：列表尾段统一 CakeGame 消息模板风格（当前页 + Tip 尾行，
render_cake_tail）；/背包 已按此落地，本批起 /角色 /装备 /技能 /帮助 及 /商店 /任务 /签到
列表尾段同步切换，TPL-08 render_footer 仍供 gm/battle 等既有系统沿用。）
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "LAST_PAGE_HINT",
    "ListPage",
    "PageResolution",
    "page_items",
    "render_cake_tail",
    "render_footer",
    "render_item_line",
    "render_list_page",
    "render_list_page_text",
    "resolve_page",
]

# 列表分页每页上限（3d §2.1 D-02 / 规则 8.2：默认 5 条/页）
DEFAULT_PAGE_SIZE: int = 5

# 裁决② 夹取提示（4f §3.4 边界：`/背包 9` 且仅 3 页 → 第 3 页 + （已到最后一页））
LAST_PAGE_HINT: str = "（已到最后一页）"


@dataclass(frozen=True)
class PageResolution:
    """页码解析结果（2026-08-27 用户裁决②）。

    - ``invalid=True``：0/负数/非数字 → 壳层应组装 TPL-12 统一报错（3d §2.2），page=None。
    - ``clamped=True``：超总页数 → 夹取到最后一页（page=total_pages），附 LAST_PAGE_HINT。
    - 正常：page ∈ 1..total_pages。
    """

    page: Optional[int]
    total_pages: int
    total: int
    invalid: bool = False
    clamped: bool = False


@dataclass(frozen=True)
class ListPage:
    """列表页渲染结果：条目行 + 夹取提示 + 页脚（全部纯 str，零 emoji）。"""

    lines: Tuple[str, ...]   # 条目行（TPL-07）
    page: int                # 实际渲染页码（夹取后）
    total_pages: int
    total: int
    clamped: bool            # 是否夹取到最后一页（裁决②）
    hint: str                # clamped 时 LAST_PAGE_HINT，否则 ""
    footer: str              # TPL-08（单页/无指令时 ""）


def _coerce_int(value: object) -> Optional[int]:
    """把页码输入归一为整数；非数字/布尔/非整数浮点 → None（→ invalid）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    return None


def resolve_page(raw_page: object, total: int, per_page: int = DEFAULT_PAGE_SIZE) -> PageResolution:
    """页码解析（裁决② 全口径）。

    - 0/负数/非数字 → invalid=True（不静默兜底，3d §2.2「不静默翻到兜底页」→ 裁决② TPL-12）。
    - 超总页数 → 夹取最后一页 + clamped=True（裁决②）。
    - 空列表（total=0）总页数=1（单页空列表，panel_render.paginate 同口径）。
    """
    if per_page <= 0:
        raise ValueError(f"per_page 必须 > 0，got {per_page}")
    total_pages = max(1, math.ceil(total / per_page)) if total else 1
    page = _coerce_int(raw_page)
    if page is None or page < 1:
        return PageResolution(page=None, total_pages=total_pages, total=total, invalid=True)
    if page > total_pages:
        return PageResolution(page=total_pages, total_pages=total_pages, total=total, clamped=True)
    return PageResolution(page=page, total_pages=total_pages, total=total)


def page_items(
    items: Sequence[Any],
    page: int,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> List[Any]:
    """按（夹取后）页码切片。页码非法抛 ValueError（壳层应先查 resolve_page().invalid 转 TPL-12）。"""
    res = resolve_page(page, len(items), per_page)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 resolve_page 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None  # 非法已拦截，夹取后恒有页码
    start = (res.page - 1) * per_page
    return list(items[start:start + per_page])


def render_item_line(index: int, name: str, value: str = "") -> str:
    """条目行 TPL-07：``{序号}. {条目名} {关键数值}``（如 ``1. 铁剑 攻击+12``）。纯文本无 emoji。"""
    if value:
        return f"{index}. {name} {value}"
    return f"{index}. {name}"


def render_footer(page: int, total_pages: int, total: int, command: str) -> str:
    """页脚 TPL-08：``— 第 {X}/{Y} 页 · 共 {N} 条 · 输入 /{指令} 页码 翻页 —``。

    单页（total_pages<=1）或无指令不输出（3d §2.3 D-02 防刷屏）；页码为固定「页码」字样
    （引导输入，非具体数字，3d §2.3）。禁止各系统自造页脚（D-02/D-05）。
    """
    if total_pages <= 1 or not command:
        return ""
    return f"— 第 {page}/{total_pages} 页 · 共 {total} 条 · 输入 /{command} 页码 翻页 —"


def render_cake_tail(
    page: int,
    total_pages: int,
    *,
    category_word: Optional[str] = None,
    tip: str = "",
) -> str:
    """CakeGame 式列表尾段：``当前页：{page}/{total_pages}[({category_word})]`` + Tip 行。

    2026-08-27 用户拍板：基础指令组列表尾段统一 CakeGame 消息模板风格（当前页 + Tip 尾行，
    替代 TPL-08 页脚）；/背包 已按此落地（basic_commands._bag_tail_lines），本函数为通用实现。

    - 当前页**恒显示**（含单页 1/1，对齐 /背包 模板）；category_word 为当前页类型词（可选，
      如 /背包筛选 装备 → ``当前页：1/2(装备)``）。
    - tip 非空时追加 ``Tip:{tip}`` 行——tip 为 ``Tip:`` 之后的完整内容：CakeGame 通用形
      ``发送'...'即可...`` 由 tip 自行拼装（如 ``发送'使用+物品名'即可使用物品``），
      各指令可按需定制尾句（如 ``发送'装备'查看当前装备``）。
    - 夹取提示（LAST_PAGE_HINT）由调用方按裁决② clamped 逻辑处理（本 helper 不含，
      保证「当前页 →（已到最后一页）→ Tip」顺序由壳层编排）。
    """
    line = f"当前页：{page}/{total_pages}"
    if category_word:
        line += f"({category_word})"
    parts = [line]
    if tip:
        parts.append(f"Tip:{tip}")
    return "\n".join(parts)


def _default_item_line(index: int, item: Any) -> str:
    return render_item_line(index, str(item))


def render_list_page(
    items: Sequence[Any],
    page: int,
    command: str,
    *,
    per_page: int = DEFAULT_PAGE_SIZE,
    formatter: Optional[Callable[[int, Any], str]] = None,
) -> ListPage:
    """列表页渲染：TPL-07 条目行 + 裁决② 夹取提示 + TPL-08 页脚。

    :param page: 目标页码（1..总页数；非法 0/负数/非数字 → 抛 ValueError，壳层应先经
                 resolve_page 判定转 TPL-12——本函数只服务合法页码，含超页夹取）
    :param command: 触发指令名（页脚 `/指令` 用；空则无页脚）
    :param formatter: (序号, 条目) -> str，缺省 TPL-07 骨架（{序号}. {条目}）
    """
    res = resolve_page(page, len(items), per_page)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 resolve_page 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None  # 非法已拦截，夹取后恒有页码
    start = (res.page - 1) * per_page
    page_slice = list(items[start:start + per_page])
    fmt = formatter if formatter is not None else _default_item_line
    lines = tuple(fmt(i + 1, item) for i, item in enumerate(page_slice))
    footer = render_footer(res.page, res.total_pages, res.total, command)
    return ListPage(
        lines=lines,
        page=res.page,
        total_pages=res.total_pages,
        total=res.total,
        clamped=res.clamped,
        hint=LAST_PAGE_HINT if res.clamped else "",
        footer=footer,
    )


def render_list_page_text(
    items: Sequence[Any],
    page: int,
    command: str,
    *,
    per_page: int = DEFAULT_PAGE_SIZE,
    formatter: Optional[Callable[[int, Any], str]] = None,
) -> str:
    """整段列表文本：条目行（换行连接）+ 夹取提示 + 页脚。表头由各系统自管（3d §2 条数不计表头）。"""
    lp = render_list_page(items, page, command, per_page=per_page, formatter=formatter)
    parts: List[str] = list(lp.lines)
    if lp.hint:
        parts.append(lp.hint)
    if lp.footer:
        parts.append(lp.footer)
    return "\n".join(parts)
