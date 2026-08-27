"""签到指令接线 checkin_commands.py（M4 批次5·路F3 · qbot_rpg/commands/checkin_commands.py）。

依据：m4_shared_contract §2.3+§3.4 + 2b5 + 裁决②⑦⑧
  - m4_shared_contract.md §2.3（基础指令组 + GM 指令，页码夹取口径）+ §3.4（签到 E1-E4：
    多表 loop/monthly/activity 并存一次结算；连签独立计数（streak）+ 补签（默认关/两通道/月上限）；
    补签只计不补发（裁决⑦）；里程碑不重复）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、
    页码越界夹取 +「已到最后一页」2026-08-27 用户裁决②、0/负数/非数字 → TPL-12、错误模板统一、emoji 纪律）
  - docs/细化/细化_2b5_签到引擎契约.md（§2.1 入口 /签到 /签到 补签；§2.2 生效表启停判定
    （activity start/end 懒计算自动停用）；§2.3 结算管线 ①~⑥（写死不可重排）；§2.4 汇总单条消息
    输出模板 + 5 条/页上限；§四 补签（makeup 默认关/两通道/月上限/幂等）；§五 幂等 D-02
    「今天已签到」仍附各表当前连签+进度）
  - docs/细化/细化_3d_消息模板规范.md（§1.2 TPL-08 页脚 / TPL-12 指令出错；§二 列表分页；
    §四 emoji 禁令；§5.4 错误文案唯一源）
  - 2026-08-27 用户裁决②（超总页数 → 夹取最后一页 +「已到最后一页」；0/负数/非数字 → TPL-12）
  - 2026-08-27 用户裁决⑦（补签只恢复 signed_days 与 streak 连续性、**不补发所补日期 daily 奖励**；
    里程碑奖励不重复——提示文案由引擎合成，本层透传）
  - 2026-08-27 用户裁决⑧（[签到:<表名>.<字段>] 三键表名限定：连续天数=指定表 streak /
    本月天数=指定表当月 signed_days / 今日已签=指定表今日已签；缺省表名=主表 loop。
    条件键取值由 core/checkin 引擎提供，命令层只需调用，不自行求值）
  - qbot_rpg/core/checkin.py（M4 批次5·路F2 已落盘 · 审查_M4实现_批次2_jspace.md P0-1 修复：
    命令层以真实引擎接口消费，接口签名见下方「消费接口」块）
  - 审查_M4实现_批次2_jspace.md P0-1（命令层 ↔ 引擎接口全面失配修复）+ 审查_M4实现_批次5_jspace.md
    P1-1（补签跨月归一口径）/P1-2（[签到:*] 表 id 双口径消费）/P1-3（bonus mult 键）——本文件承载
    P0-1（消费真实引擎 / tables 重建纯文本 / 缺省表名传 None / resolve 取 .get("id")）。

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /签到（无参=今日结算汇总 5 条/页 +
CakeGame 式尾段（当前页 + Tip）+ 裁决② 夹取；子词「状态」= 连签/月累计/今日已签；子词「补签 <表名>」= 补签）
从 Router 接到 core/checkin.py 引擎——指令解析（parsers.parse_command 已 token 化 → 本模块取
子指令词 + 页码/表名）、结算/状态/补签结果渲染（core/message_format/list_render 5 条/页 +
CakeGame 式尾段 + 裁决② 夹取 + 表段头，正文按 2b5 §2.4 从引擎 tables 重建纯文本）、补签结果透传
（引擎已按定稿合成 ✅/❌ 业务文案，含裁决⑦「只计不补发」提示）、错误统一 TPL-12
（sender.format_tpl12，文案唯一源 errors.py D-04）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性（now/rng 由 ctx 注入）；
工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌ 功能性标记）。
本模块只做「装配接线 + 渲染」，业务结算全部委托引擎。

--------------------------------------------------------------------------------
消费接口（core/checkin.py · M4 批次5·路F2 已落盘 · 审查批次2 P0-1 修复后本层按真实引擎签名消费，
不做二次判断；如后续签名变动 → 登记 contract_deviations）：
  checkin_do(ctx) -> dict
      {ok, today, tables: [{table_id, name, type, active, streak, day, cycle_days, month_days,
        today_signed, already_signed, failed, granted, daily_granted, skipped, notes,
        streak_hits, month_hits, progress_current, progress_total}], message}
      message：引擎合成汇总（纯文本，去 📅/⚠ 装饰 emoji——批次2 后续衔接提醒）；本层正文仍按
        tables 重建（P0-1），首行统一为「✅ 今日签到完成」/ 幂等「今天已签到（重复指令，未重复发放）」
      ok=False 时 message=失败文案（如「❌ 今日无生效签到表」），本层透传不渲染段
  checkin_state(ctx) -> dict
      {ok, today, tables: [{table_id, name, type, active, streak, day, cycle_days, month_days,
        month_total, today_signed, makeup_enabled, makeup_used, makeup_limit, longline,
        progress_current, progress_total}]}
  checkin_makeup(ctx, table_id=None) -> dict
      {ok, message, ...}   裁决⑦：补签只恢复 signed_days/streak 连续性、不补发所补日期 daily 奖励；
      里程碑不重复——提示文案由引擎合成（如「✅ 补签成功（currency）· 只计不补发」）；
      table_id=None → 主表 loop（裁决⑧ 缺省口径）
  resolve_checkin_table(ctx, table_id) -> Optional[Mapping]
      表 id → 表定义 Mapping；非 str 入参/查无 → None。表名/类型名/序号 解析由本层补足
      （见 resolve_checkin_table_arg）。

--------------------------------------------------------------------------------
【工程补白 · 显式标注】
  1) **引擎已落盘（审查批次2 P0-1 修复）**：core/checkin.py（路F2）已实现，本层以
     `ctx["checkin_engine"]` 注入优先（测试/装配注入真实 core/checkin 模块），否则懒加载
     `qbot_rpg.core.checkin`；两者皆不可得 → RuntimeError（防御路径，不阻塞本层导入）。
     测试以真实 core/checkin 驱动（test_checkin_commands.py 已删契约替身，对齐 test_quest_commands）。
  2) **2b5 §2.4 汇总模板降级**：契约示意图（┌─📅 ═══ 表框 + 📅 emoji）为定稿示例表述，
     按 3d D-01 降级为纯文本 + ✅/❌：段头「━━ {表名}（{类型}）━━」，流水行纯文本，禁止装饰 emoji；
     「｜」进度分隔沿用契约"8/31"语义。正文由本层从引擎 checkin_do/checkin_state 的 tables
     重建（P0-1：引擎 message 的汇总框不再透传为正文）。
  3) **5 条/页横切由本层统一**：引擎 tables 全量重建 sections 后本层扁平化按 5 条/页重分页
     （跨路分页口径收敛，与 quest_commands/shop_commands 同模式）；表头不计条数（3d §2.1）；
     尾段只用 render_cake_tail（CakeGame 式「当前页 + Tip」），禁止自造页脚。
  4) **补签表名参数**：2b5 §2.1 仅定「/签到 补签」；多表并存时补签需指定表（任务要求
     「/签到 补签 <表名>」）。缺省表名 → 直接传 None 给 checkin_makeup(ctx, None)，由引擎按
     主表 loop 解析（裁决⑧「缺省表名=主表 loop」——P0-1 修复：不再经 resolve 转 None 触发 TPL_NO_TABLE）。
  5) **/签到 状态 可翻页**：本月累计/连签/今日已签 行数可能超 5 行，按 m4 §2.2 5 条/页 +
     CakeGame 式尾段（当前页 + Tip）横切；页码 0/负数/非数字 → TPL-12（裁决②）。
  6) **/签到 <整数> 二义性**：整数参数 = 页码（m4 §2.2 翻页 + CakeGame 尾段「当前页：X/Y」），
     0/负数/非数字 → TPL-12（裁决②）；超总页数 → 夹取最后一页 +「已到最后一页」（裁决②）。
  7) **补签表名非法/不存在**（resolve_checkin_table_arg → None）：返回「❌ 没有这个签到表」
     （值域问题，命令本身合法，不走 TPL-12；对齐 quest_commands 工程补白 6 口径）。
  8) **[签到:*] 三键（裁决⑧）**：条件键取值完全由 core/checkin 引擎提供（命令层不引用
     condition_engine、不自行求值）；本层仅保证结算/状态调用走引擎后键值已更新（TC-32 语义）。
  9) 本模块的玩家上下文工厂 make_context（NoneBot 事件 + 存储 → ctx dict）由装配层注入
     （register_checkin_commands 的 make_context 参数），**批次6/7 装配待接线**；注入前本层可纯
     函数单测（直接构造 ctx + 注入真实 core/checkin 引擎）。
  10) 补签表名解析增强（P0-1）：真实引擎 resolve_checkin_table 仅按表 id 精确解析；命令层在引擎
     查无后补「表名 / 生效 type 名 / 序号 1..N」解析（对齐 e2e_m4_smoke 旧 CheckinAdapter 口径）。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_cake_tail,
    resolve_page,
)

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .parsers import parse_int
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名 / 子指令词
    "CHECKIN_CMD", "SUB_STATUS", "SUB_MAKEUP", "SUBWORDS",
    # 渲染常量
    "TPL_NO_CHECKIN", "TPL_NO_TABLE",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_checkin", "cmd_checkin_today", "cmd_checkin_status", "cmd_checkin_makeup",
    # 渲染 / 工具
    "render_summary", "flatten_sections", "table_arg_of", "resolve_checkin_table_arg",
    # 装配
    "register_checkin_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CHECKIN_CMD = "签到"

# 子指令词（非解析器固定子词，经 args 位置参数识别；对齐 shop_commands 的「列表」关键词模式）
SUB_STATUS = "状态"
SUB_MAKEUP = "补签"
SUBWORDS: tuple = (SUB_STATUS, SUB_MAKEUP)

# CakeGame 式尾段 Tip 内容（`Tip:` 之后部分，2026-08-27 用户拍板统一列表尾段；无斜杠指令名）
_TAIL_TIP = "发送'签到 补签'即可补签"   # /签到 结算汇总与状态视图（补签为真实子指令）

# 结算/状态不可用兜底（引擎 ok=False 且无 message 时）
TPL_NO_CHECKIN = "❌ 签到暂不可用"

# 补签表名非法/不存在（resolve_checkin_table_arg → None；对齐 quest「任务不存在」值域口径，工程补白 7）
TPL_NO_TABLE = "❌ 没有这个签到表"

# 签到表类型中文标注（镜像 core/checkin._TYPE_CN，段头「{表名}（{类型}）」用；2b5 §2.4 表段头）
_TYPE_CN: dict = {"loop": "常驻循环", "monthly": "月度签到", "activity": "活动"}


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _grant_label(g: Mapping[str, Any]) -> str:
    """grant 记录 → 简短展示标签（镜像 core/checkin._grant_label；「药水×2」「50 coins」「exp20」）。"""
    typ = g.get("type")
    if typ == "item":
        return f"{g.get('item')}×{g.get('count')}"
    if typ == "currency":
        return f"{g.get('amount')} {g.get('currency')}"
    if typ == "exp":
        return f"exp{g.get('amount')}"
    if typ == "rep":
        return f"声望{g.get('amount')}"
    return str(g)


def _progress_line(t: Mapping[str, Any]) -> str:
    """连签进度行（「连签天数：N 天 ｜ 进度 X/Y」，2b5 §2.4）。"""
    return f"连签天数：{t.get('streak', 0)} 天 ｜ 进度 {t.get('progress_current', 0)}/{t.get('progress_total', 0)}"


def _table_rows(t: Mapping[str, Any]) -> List[str]:
    """表结果 → 纯文本流水行（P0-1 真实引擎 tables 重建；2b5 §2.4 口径，无装饰 emoji）。

    - 结算结果形态（checkin_do 返回，判别键 granted）：已签 → 幂等行+进度；失败 → 失败文案；
      正常 → 今日奖励 / notes / 连签进度 / 里程碑提示。
    - 状态查询形态（checkin_state 返回，无 granted）：连签 / 本月累计 / 今日已签 / 补签用量。
    """
    rows: List[str] = []
    if "granted" in t:
        if t.get("already_signed"):
            rows.append("今天已签到（不重复发奖）")
            rows.append(_progress_line(t))
            return rows
        if t.get("failed"):
            rows.append(str(t.get("message") or "结算失败，已回滚"))
            return rows
        daily = t.get("daily_granted") or []
        rows.append("今日奖励：" + ("、".join(_grant_label(g) for g in daily[:4]) if daily else "无"))
        for n in t.get("notes") or []:
            rows.append(str(n))
        rows.append(_progress_line(t))
        for h in t.get("streak_hits") or []:
            if not isinstance(h, Mapping):
                continue
            labs = "、".join(_grant_label(g) for g in (h.get("granted") or [])[:4])
            rows.append(f"[连签里程碑达成] {labs}（连签 {h.get('days')} 天）")
        for h in t.get("month_hits") or []:
            if not isinstance(h, Mapping):
                continue
            labs = "、".join(_grant_label(g) for g in (h.get("granted") or [])[:4])
            rows.append(f"[月度累计达成] {labs}（本月签满 {h.get('days')} 天）")
        return rows
    # checkin_state 状态查询形态
    rows.append(f"连签天数：{t.get('streak', 0)} 天")
    rows.append(f"本月累计：{t.get('month_days', 0)} 天")
    rows.append("今日已签：" + ("是" if t.get("today_signed") else "否"))
    limit = t.get("makeup_limit", 0)
    if t.get("makeup_enabled"):
        rows.append(f"补签：{t.get('makeup_used', 0)}/{limit if limit > 0 else '不限'}")
    return rows


def _sections_from_tables(res: Mapping[str, Any]) -> list:
    """引擎 tables（checkin_do/checkin_state 返回）→ sections（P0-1 正文重建；生效表跳过 inactive）。"""
    sections: list = []
    for t in res.get("tables") or []:
        if not isinstance(t, Mapping):
            continue
        if not t.get("active", True):
            continue
        name = t.get("name") or str(t.get("table_id") or "")
        if not name:
            continue
        typ = str(t.get("type", "loop"))
        title = f"{name}（{_TYPE_CN.get(typ, typ)}）"
        rows = _table_rows(t)
        if rows:
            sections.append({"title": title, "rows": rows})
    return sections


def _sections_of(res: Mapping[str, Any]) -> list:
    """引擎返回 → sections：优先 res["sections"]（旧契约适配器兼容）；否则从 tables 重建（P0-1）。"""
    sections = res.get("sections")
    if isinstance(sections, list):
        return sections
    return _sections_from_tables(res)


def flatten_sections(res: Mapping[str, Any]) -> list:
    """引擎返回 → 全量 (段标题, 流水行) 有序对（工程补白 3；支持 sections 直给或 tables 重建）。"""
    pairs: list = []
    for section in _sections_of(res):
        if not isinstance(section, Mapping):
            continue
        title = section.get("title") or ""
        for row in section.get("rows") or []:
            if isinstance(row, str) and row.strip():
                pairs.append((title, row))
    return pairs


def table_arg_of(parsed: Any, index: int = 1) -> Optional[str]:
    """取第 index 个位置参数原文（补签表名；越界 → None = 缺省主表 loop，工程补白 4）。"""
    args = list(getattr(parsed, "args", None) or [])
    return str(args[index]) if len(args) > index else None


def resolve_checkin_table_arg(ctx: Mapping[str, Any], engine: Any, arg: Optional[str]) -> Optional[str]:
    """表名/类型名/序号/表 id → 表 id（P0-1 修复：真实引擎 resolve_checkin_table 返回表定义 Mapping，
    取 .get("id")；引擎只认表 id，命令层补 表名/生效 type 名/序号 1..N 解析——工程补白 10）。
    arg=None → None（缺省主表由引擎按 None 解析，不经 resolve，防 TPL_NO_TABLE 误伤）；找不到 → None。"""
    if arg is None:
        return None
    s = str(arg).strip()
    if not s:
        return None
    try:
        table = engine.resolve_checkin_table(ctx, s)
    except Exception:
        table = None
    if isinstance(table, Mapping):
        return table.get("id")
    if isinstance(table, str) and table:
        return table
    tables = ctx.get("checkin_tables")
    if isinstance(tables, Mapping):
        items = [(str(tid), t) for tid, t in tables.items() if isinstance(t, Mapping)]
        for tid, t in items:
            if str(t.get("name")) == s or str(t.get("type", "loop")) == s:
                return tid
        if s.isdigit():
            idx = int(s)
            if 1 <= idx <= len(items):
                return items[idx - 1][0]
    return None


# ---------------------------------------------------------------------------
# 引擎解析（注入优先 → 懒加载 core.checkin；均不可得 → 防御 RuntimeError）
# ---------------------------------------------------------------------------

def _engine_of(ctx: Mapping[str, Any]) -> Any:
    """解析 checkin 引擎命名空间（审查批次2 P0-1 修复：真实引擎已落盘）。

    - ctx["checkin_engine"] 注入优先（测试/装配注入真实 core/checkin 模块，接口见文件头消费接口）；
    - 否则懒加载 qbot_rpg.core.checkin（路F2 已落盘）；
    - 两者皆不可得 → RuntimeError（防御路径，不阻塞本层导入）。
    """
    eng = ctx.get("checkin_engine")
    if eng is not None:
        return eng
    try:
        return importlib.import_module("qbot_rpg.core.checkin")
    except Exception as exc:  # ModuleNotFoundError / ImportError
        raise RuntimeError(
            "【待接线】core/checkin.py（M4 批次5·路F2）不可用，签到引擎缺失；"
            "装配时注入 ctx['checkin_engine']（checkin_do/checkin_state/"
            "checkin_makeup/resolve_checkin_table 消费接口）"
        ) from exc


# ---------------------------------------------------------------------------
# 汇总/状态渲染（sections 扁平化 → 5 条/页 + 段头 + CakeGame 式尾段 + 裁决② 夹取）
# ---------------------------------------------------------------------------

def _today_message(res: Mapping[str, Any]) -> str:
    """结算首行（纯文本，D-02 幂等口径）：全部生效表已签 → 幂等文案；否则今日结算完成。"""
    if res.get("idempotent") or res.get("already_signed"):
        return "今天已签到（重复指令，未重复发放）"
    tables = res.get("tables") or []
    active = [t for t in tables if isinstance(t, Mapping) and t.get("active", True)]
    if active and all(t.get("already_signed") for t in active):
        return "今天已签到（重复指令，未重复发放）"
    return "✅ 今日签到完成"


def render_summary(res: Mapping[str, Any], page: object, *,
                   per_page: int = DEFAULT_PAGE_SIZE) -> str:
    """结算/状态正文渲染（工程补白 2/3/5）：

    - 引擎返回（sections 或 tables 重建）扁平化后按 5 条/页横切（m4 §2.2）；段头「━━ {表名}（{类型}）━━」
      首次出现输出（表头不计条数，3d §2.1）；
    - 页码超总页数 → 夹取最后一页 + LAST_PAGE_HINT（裁决②）；0/负数/非数字 → raise ValueError
      （壳层应先经 resolve_page 判 TPL-12）；
    - CakeGame 式尾段（当前页 + Tip，2026-08-27 用户拍板统一列表尾段）；空流水 → 返回 ""
      （由调用方只输出 message）。
    """
    pairs = flatten_sections(res)
    total = int(res.get("total", len(pairs)))
    pg = resolve_page(page, total, per_page)
    if pg.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 resolve_page 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert pg.page is not None  # 非法已拦截，夹取后恒有页码
    if not pairs:
        return ""
    start = (pg.page - 1) * per_page
    slice_pairs = pairs[start:start + per_page]
    lines: List[str] = []
    seen: set = set()
    for title, row in slice_pairs:
        if title and title not in seen:
            lines.append(f"━━ {title} ━━")
            seen.add(title)
        lines.append(row)
    tail = render_cake_tail(pg.page, pg.total_pages, tip=_TAIL_TIP)
    if pg.clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    lines.append(tail)
    return "\n".join(lines)


def _assemble(msg: str, body: str) -> str:
    """message 首行 + 正文（正文为空 → 只输出 message）。"""
    if body:
        return f"{msg}\n{body}"
    return msg


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx → 回复正文）
# ---------------------------------------------------------------------------

def cmd_checkin_today(ctx: Mapping[str, Any], page: object) -> str:
    """/签到 [页码]：今日结算汇总（多表各表奖励 + 连签/月累计进度 + 里程碑提示；
    5 条/页 + CakeGame 式尾段 + 裁决② 夹取；幂等 D-02「今天已签到」仍附进度；板不可用 → 引擎消息透传）。
    消费真实引擎 checkin_do(ctx)，正文从 tables 重建（审查批次2 P0-1）。"""
    engine = _engine_of(ctx)
    res = engine.checkin_do(ctx)
    if not res or not res.get("ok"):
        return str(res.get("message") or TPL_NO_CHECKIN) if res else TPL_NO_CHECKIN
    msg = _today_message(res)
    body = render_summary(res, page)
    return _assemble(msg, body)


def cmd_checkin_status(ctx: Mapping[str, Any], page: object) -> str:
    """/签到 状态 [页码]：连签/本月累计/今日已签（5 条/页 + CakeGame 式尾段 + 裁决② 夹取；
    页码 0/负数/非数字 → TPL-12 由主入口判定）。消费真实引擎 checkin_state(ctx)，正文从 tables 重建
    （审查批次2 P0-1）。"""
    engine = _engine_of(ctx)
    res = engine.checkin_state(ctx)
    if not res or not res.get("ok"):
        return str(res.get("message") or TPL_NO_CHECKIN) if res else TPL_NO_CHECKIN
    msg = "✅ 签到状态"
    body = render_summary(res, page)
    return _assemble(msg, body)


def cmd_checkin_makeup(ctx: Mapping[str, Any], table: Optional[str]) -> str:
    """/签到 补签 <表名>：补签（裁决⑦：只恢复 signed_days/streak，不补发所补日期 daily 奖励；
    里程碑不重复——提示由引擎合成，本层透传）。缺省表名 → 直接传 None 由引擎按主表 loop 解析
    （裁决⑧ 口径，审查批次2 P0-1：不再经 resolve 转 None 触发 TPL_NO_TABLE）；表不存在 → 值域文案。"""
    engine = _engine_of(ctx)
    if table is None:
        tid: Optional[str] = None
    else:
        tid = resolve_checkin_table_arg(ctx, engine, table)
        if tid is None:
            return TPL_NO_TABLE
    res = engine.checkin_makeup(ctx, tid)
    return str(res.get("message") or "❌ 补签失败")


def cmd_checkin(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/签到 [参数] 主入口（m4 §3.4 + 2b5 §2.1 收口形式）：

      无参            → 今日结算汇总第 1 页（多表各表奖励 + 连签/月累计进度 + 里程碑提示，
                         5 条/页 + CakeGame 式尾段 + 双表段头）
      <整数>          → 页码翻页（裁决②：超页夹取最后一页 + 已到最后一页；0/负数/非数字 → TPL-12）
      状态 [页码]     → 连签/月累计/今日已签（可翻页，工程补白 5）
      补签 [<表名>]   → 补签（表名缺省 = 主表 loop，工程补白 4；裁决⑦ 只计不补发提示透传）
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return cmd_checkin_today(ctx, 1)
    first = str(args[0])

    # 子词：状态
    if first == SUB_STATUS:
        page: object = 1
        if len(args) > 1:
            n = parse_int(str(args[1]))
            if n is None or n < 1:
                return format_tpl12(f"/{CHECKIN_CMD} {SUB_STATUS} {args[1]}")
            page = n
        return cmd_checkin_status(ctx, page)

    # 子词：补签
    if first == SUB_MAKEUP:
        table = str(args[1]) if len(args) > 1 else None
        return cmd_checkin_makeup(ctx, table)

    # 紧凑「子词+参数」（工程补白 4/5 延伸：`补签loop` / `状态2` 双认，与 parsers 紧凑双认同构）
    if first.startswith(SUB_MAKEUP):
        rest = first[len(SUB_MAKEUP):]
        return cmd_checkin_makeup(ctx, rest or None)
    if first.startswith(SUB_STATUS):
        rest = first[len(SUB_STATUS):]
        n = parse_int(rest) if rest else 1
        if n is None or n < 1:
            return format_tpl12(f"/{CHECKIN_CMD} {SUB_STATUS} {rest}")
        return cmd_checkin_status(ctx, n)

    # 整数 = 页码路径（工程补白 6）
    n = parse_int(first)
    if n is None or n < 1:
        return format_tpl12(_fragment(parsed))
    return cmd_checkin_today(ctx, n)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次6/7 待接线）
# ---------------------------------------------------------------------------

def register_checkin_commands(router: Any, *, make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /签到 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 checkin_engine 注入（工程补白 1）/
        checkin_tables/checkin_state/currencies/items/now 等，见 core/checkin.py 契约）。
        None 时 handler 调用抛 RuntimeError（【待接线】批次6/7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】checkin_commands.register_checkin_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _checkin(parsed: Any, *a: Any, **k: Any) -> str:
        return cmd_checkin(parsed, _ctx(parsed))

    router.register(CommandSpec(CHECKIN_CMD, handler=_checkin))
    return router
