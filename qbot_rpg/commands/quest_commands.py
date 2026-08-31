"""任务指令接线 quest_commands.py（M4 批次4·路E3 · qbot_rpg/commands/quest_commands.py）。

依据：
  - m4_shared_contract.md §2.3（基础指令组 + GM 指令，页码夹取口径）+ §3.3（任务 D1-D5：
    /任务 接取 N / 交付 N（+任务信息/放弃）；双板仲裁（日常+主线）；主线置顶 main:true 常驻；
    完成交付 → 统一 reward 发放结果提示）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、
    页码越界夹取 +「已到最后一页」2026-08-27 用户裁决②、0/负数/非数字 → TPL-12、
    错误模板统一、emoji 纪律）
  - docs/细化/细化_2b4_任务引擎契约.md（§5 任务板：主线置顶 / 接取序号 / 交付 / 双板仲裁；
    §3 统一 reward 逐键入账 + P1-2 逐条目失败黄字跳过；TC-24~28 任务板交互）
  - docs/细化/细化_3d_消息模板规范.md（§1.2 TPL-08 页脚 / TPL-12 指令出错；§二 列表分页；
    §四 emoji 禁令；§5.4 错误文案唯一源）
  - 2026-08-27 用户裁决②（超总页数 → 夹取最后一页 +「已到最后一页」；0/负数/非数字 → TPL-12）
  - 2026-08-27 用户拍板：列表尾段统一 CakeGame 式「当前页 + Tip」（render_cake_tail）
  - qbot_rpg/core/quest.py（M4 批次4·路E2 同批并行 · 收口接口：quest_board(ctx)->{sections,total,tip} /
    resolve_board_index(ctx, seq)->quest_id / quest_accept / quest_complete / quest_abandon /
    quest_progress(quest_id, ctx)）与 qbot_rpg/core/reward.py（A1 dispatch_reward 唯一发放器）

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /任务（无参=任务板 5 条/页 + CakeGame 式尾段
（当前页 + Tip）+ 裁决② 页码夹取；日常+主线双板主线置顶）与 /任务 接取 N / 交付 N / 信息 N /
放弃 N 四条子指令从 Router 接到 core/quest.py 引擎——指令解析（parsers.parse_command 已 token 化
→ 本模块取子指令词 + 序号）、展示序号 → quest_id（引擎 resolve_board_index）、任务板渲染
（core/message_format/list_render 5 条/页 + CakeGame 式尾段 + 裁决② 夹取 + 双板段头）、
接取/交付/信息/放弃结果透传（引擎按定稿合成 ✅/❌ 业务文案；交付奖励统一发放结果提示，
含 P1-2 逐条目失败黄字跳过注记）、错误统一 TPL-12（sender.format_tpl12，文案唯一源 errors.py
D-04）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性（now/rng 由 ctx
注入）；工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用
（仅 ✅/❌ 功能性标记）。本模块只做「装配接线 + 渲染」，业务结算全部委托引擎。

--------------------------------------------------------------------------------
消费接口（core/quest.py · 路E2 已收口 · 本层按以下真实签名消费，不做二次判断）：
  quest_board(ctx) -> dict
      {ok: True, sections: [{title, slot, rows:[row...]}], total: N, tip: str}
      row 字段：index（全局展示序号，/任务 接取 N 即此序号）/ quest_id / name / type /
        main（bool 主线置顶）/ active / completed / repeatable / marked（active 且非主线 → 渲染 *）/
        met（条件全真）/ progress（[{var,op,param,target,current,met}] 三原语进度）/ section
  resolve_board_index(ctx, seq) -> Optional[str]  展示序号 → quest_id；None = 越界/非法
  quest_accept(quest_id, ctx) -> dict    {ok, message, quest_id, name, active_count, accept_limit}
  quest_complete(quest_id, ctx) -> dict  {ok, message(统一 reward 发放结果提示), granted, skipped,
                                          completed_today, daily_limit, idempotent, ...}
  quest_progress(quest_id, ctx) -> dict  {ok, quest_id, name, met, consume, required_items,
                                          conditions:[{var,op,param,target,current,met}], active}
  quest_abandon(quest_id, ctx) -> dict   {ok, message, quest_id, name, penalty}

--------------------------------------------------------------------------------
【工程补白 · 显式标注】
  1) **引擎解析**：core/quest.py（路E2 同批并行）已收口落盘，本层以 `ctx["quest_engine"]`
     注入优先（测试/装配可注入替代实现），否则懒加载 `qbot_rpg.core.quest`；两者皆不可得 →
     RuntimeError「【待接线】…」（防御路径，不阻塞本层导入）。
  2) **5 条/页横切由本层统一**：引擎 quest_board 一次性返回全部分组行（sections），本层扁平化
     后按 m4 §2.2 5 条/页重分页（跨路分页口径收敛，与 shop_commands 同模式）；页脚只用
     render_footer（TPL-08），禁止自造页脚。
  3) **双板段头**：引擎 sections 已带标题（"主线（常驻）"/"每日板上任务"/"NPC 支线"），本层
     按 2b4 §5.2 排版包成「━━ 标题 ━━」；尾段 Tip **不用引擎 tip**（引擎 tip 为 §5.1 裸
     `/接取` 旧口径），以本层 _BOARD_TAIL_TIP 为准（`领取任务 序号`，意见一同步）。
  4) **裸 /接取 /交付 /放弃 /任务信息 不注册**（2b4 §5.1 旧列法与 §5.4 双板仲裁）：本批只接
     m4 §3.3 收口形式 `/任务 <子词> <N>`（任务派工单口径），避免与批次 6 基础指令组注册冲突；
     委托板（/委托）独立板不在本批范围。
  5) **/任务 <整数> 二义性**：整数参数 = 页码（m4 §2.2 翻页 + CakeGame 尾段「当前页：X/Y」），
     0/负数/非数字 → TPL-12（裁决②）；超总页数 → 夹取最后一页 +「已到最后一页」（裁决②）。
  6) **展示序号越界/非法**（resolve_board_index → None）：返回引擎口径「❌ 任务不存在」
     （对齐 quest_accept no_quest message），不走 TPL-12（命令本身合法，参数值域问题）。
  7) **/任务 信息 N 渲染**：引擎 quest_progress 成功态无 message 字段（进度数据在 conditions），
     本层按「三原语进度逐条显示」（2b4 §5.1）合成正文（var/op 互译中文展示，判定权威仍在引擎）。
  8) 本模块的玩家上下文工厂 make_context（NoneBot 事件 + 存储 → ctx dict）由装配层注入
     （register_quest_commands 的 make_context 参数），**批次6/7 装配待接线**；注入前本层可纯
     函数单测（直接构造 ctx + 注入真实 quest 引擎）。
"""

from __future__ import annotations

import importlib
import re
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
    "QUEST_CMD", "SUB_ACCEPT", "SUB_DELIVER", "SUB_INFO", "SUB_ABANDON", "SUBWORDS",
    "SUB_ACCEPT_ALIASES",
    # 渲染常量
    "TPL_NO_BOARD", "TPL_NO_QUEST", "BOARD_PAGE_SIZE",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_quest", "cmd_quest_board", "cmd_quest_accept",
    "cmd_quest_deliver", "cmd_quest_info", "cmd_quest_abandon",
    # 渲染 / 工具
    "render_board", "board_line", "info_text", "progress_text", "sub_and_seq",
    # 装配
    "register_quest_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

QUEST_CMD = "任务"

# 子指令词（m4 §3.3 收口形式：/任务 接取 N / 交付 N / 信息 N / 放弃 N）
SUB_ACCEPT = "接取"
SUB_DELIVER = "交付"
SUB_INFO = "信息"
SUB_ABANDON = "放弃"
SUBWORDS: tuple = (SUB_ACCEPT, SUB_DELIVER, SUB_INFO, SUB_ABANDON)

# P2-12 QA 修复：任务板 Tip「领取任务 序号」与实际子词「接取」不一致（QA 黑盒：按 Tip
# 发「任务 领取 1」被拒）→ 补「领取」为「接取」的等价子词（Tip 保持口语化「领取」不变，
# 玩家发「领取」/「领取N」同样可接取；对齐仓库别名先例 MY_SKILL_CMD「我的技能」）。
SUB_ACCEPT_ALIASES: tuple = ("领取",)
# 子词识别全集 = 规范子词 + 接取别名（空格/紧凑形式双认，_SUB_SEQ_RE 同源）
_ALL_SUBWORDS: tuple = SUBWORDS + SUB_ACCEPT_ALIASES

# 任务板分页每页上限（m4 §2.2 横切；引擎 sections 全量返回后由本层重分页，工程补白 2）
BOARD_PAGE_SIZE: int = DEFAULT_PAGE_SIZE  # 5 条/页

# CakeGame 式尾段 Tip 内容（`Tip:` 之后部分，2026-08-27 用户拍板统一列表尾段；无斜杠指令名）
# 意见一同步：Tip 改「领取任务 序号」（替代「任务 接取 序号」）
_BOARD_TAIL_TIP = "发送'领取任务 序号'即可领取任务"    # /任务 任务板

# 任务板不可用兜底（引擎 ok=False 且无 message 时）
TPL_NO_BOARD = "❌ 任务板暂不可用"

# 展示序号越界/非法（resolve_board_index → None；对齐引擎 no_quest 口径，工程补白 6）
TPL_NO_QUEST = "❌ 任务不存在"

# 空板文案（无任何任务行；纯文本无 emoji）
_EMPTY_BOARD = "（任务板空空如也）"

# 紧凑「子词+序号」形态：接取3 / 放弃2 / 交付5 / 领取3（分隔符 `*` 连数量、`+` 等级均不适用序号）
# 注：rf 字符串内 `\d` 为原样正则（勿写 `\\d`，rf 下会变成字面反斜杠+d）
_SUB_SEQ_RE = re.compile(rf"^({'|'.join(_ALL_SUBWORDS)})(\d+)$")

# 展示用 var/op 互译（纯渲染，判定权威在引擎 condition_engine；未知键原样显示）
_VAR_DISPLAY: Mapping[str, str] = {
    "level": "等级", "item_count": "背包数量", "has_item": "持有物品",
    "gain_count": "累计获得", "kill_count": "累计击杀", "main_progress": "主线进度",
    "codex": "图鉴", "reputation": "声望", "dungeon_clear": "副本通关",
    "job": "职业", "job_level": "职业等级", "prof_level": "熟练度",
    "has_quest": "进行中任务", "quest_completed": "已完成任务",
}
_OP_DISPLAY: Mapping[str, str] = {
    "ge": "≥", "gt": ">", "le": "≤", "lt": "<", "eq": "=", "ne": "≠",
    "between": "∈", "is": "是", "not": "非",
}


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


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛（2026-08-31 QA 修复：/任务 此前缺门槛，未注册玩家可直接接取）。

    本地导入避免跨包循环；ctx["registered"] is False → 拦截文案；缺省视为已注册。
    """
    if ctx.get("registered", True) is False:
        from .basic_commands import TPL_REGISTER_GATE  # noqa: PLC0415

        return TPL_REGISTER_GATE
    return None


def _display_var(var: object) -> str:
    """三原语 var 展示名（英文键 → 中文，事件键保留，未知键原样）。"""
    key = str(var) if var is not None else "?"
    return _VAR_DISPLAY.get(key, key)


def _display_op(op: object) -> str:
    key = str(op) if op is not None else "?"
    return _OP_DISPLAY.get(key, key)


def progress_text(cond: Mapping[str, Any]) -> str:
    """单条三原语条件进度串：`背包数量 ≥ 20（当前 12）`。"""
    var = _display_var(cond.get("var"))
    op = _display_op(cond.get("op"))
    param = cond.get("param")
    target = cond.get("target")
    current = cond.get("current")
    base = f"{var} {op} {target}" if target is not None else f"{var} {op}"
    if param is not None:
        base += f"（{param}）"
    if current is not None:
        base += f"，当前 {current}"
    return base


def board_line(index: int, row: Mapping[str, Any]) -> str:
    """任务板条目行（2b4 §5.2 / TC-24/25）：`N. [主线]名称*  进度 12/20`。

    - 主线 → 名称前缀 `[主线]`；marked（active 且非主线）→ 后缀 `*`（TC-25，引擎已算）；
    - 进度 = 首条三原语条件 current/target（引擎 row.progress 列表）。
    """
    name = str(row.get("name") or "?")
    if row.get("main"):
        name = f"[主线] {name}"
    if row.get("marked"):
        name = f"{name}*"
    line = f"{index}. {name}"
    prog = row.get("progress")
    if isinstance(prog, list) and prog:
        c = prog[0]
        if isinstance(c, Mapping):
            cur = c.get("current")
            target = c.get("target")
            if cur is not None and target is not None:
                line += f"  进度 {cur}/{target}"
    return line


def info_text(res: Mapping[str, Any], seq: object) -> str:
    """/任务 信息 N 正文（2b4 §5.1：三原语进度逐条显示 + 交付判定；工程补白 7）。"""
    name = res.get("name") or "?"
    lines: List[str] = [f"✅ 任务进度：{name}"]
    for c in res.get("conditions") or []:
        if not isinstance(c, Mapping):
            continue
        mark = "✅" if c.get("met") else "❌"
        lines.append(f"- {progress_text(c)} {mark}")
    if res.get("met"):
        lines.append(f"✅ 条件已满足，可交付（/任务 交付 {seq}）")
    else:
        lines.append("❌ 条件未达成，继续努力")
    return "\n".join(lines)


def _canonical_sub(sub: object) -> str:
    """子词归一（P2-12 QA）：别名「领取」→ 规范词「接取」（SUB_ACCEPT）；其余原样。"""
    if sub in SUB_ACCEPT_ALIASES:
        return SUB_ACCEPT
    return str(sub) if sub is not None else ""


def sub_and_seq(parsed: Any) -> tuple:
    """提取子指令词 + 序号原文（别名归一：领取 → 接取）。

    返回 (sub, seq_text)：
      - `/任务 接取 3` / `/任务接取 3`        → ("接取", "3")
      - `/任务 领取 3` / `/任务领取 3`        → ("接取", "3")   # P2-12 别名「领取」
      - `/任务 接取3` / `任务放弃2`（紧凑）     → ("接取", "3") / ("放弃", "2")
      - `/任务 放弃 2`（放弃 为解析器固定子词，入 fixed_subword）→ ("放弃", "2")
      - 非子指令（页码 / 其它）→ (None, None)
    """
    args = list(getattr(parsed, "args", None) or [])
    fixed = getattr(parsed, "fixed_subword", None)
    # 固定子词优先（放弃/查看 等，3c P09）：子词在 fixed_subword，序号取 args[0]
    if fixed in _ALL_SUBWORDS:
        return _canonical_sub(fixed), (args[0] if args else None)
    if not args:
        return None, None
    first = str(args[0])
    if first in _ALL_SUBWORDS:
        return _canonical_sub(first), (args[1] if len(args) > 1 else None)
    # 紧凑「子词+序号」（任务放弃2 → args=["放弃2"]）
    m = _SUB_SEQ_RE.match(first)
    if m:
        return _canonical_sub(m.group(1)), m.group(2)
    return None, None


# ---------------------------------------------------------------------------
# 引擎解析（注入优先 → 懒加载 core.quest；均不可得 → 【待接线】RuntimeError）
# ---------------------------------------------------------------------------

def _engine_of(ctx: Mapping[str, Any]) -> Any:
    """解析 quest 引擎命名空间（工程补白 1）。

    - ctx["quest_engine"] 注入优先（测试/装配注入，签名见文件头消费接口）；
    - 否则懒加载 qbot_rpg.core.quest（路E2 已收口落盘）；
    - 两者皆不可得 → RuntimeError「【待接线】…」（防御路径，不阻塞本层导入）。
    """
    eng = ctx.get("quest_engine")
    if eng is not None:
        return eng
    try:
        return importlib.import_module("qbot_rpg.core.quest")
    except Exception as exc:  # ModuleNotFoundError / ImportError
        raise RuntimeError(
            "【待接线】core/quest.py（M4 批次4·路E2）不可用，任务引擎缺失；"
            "装配时注入 ctx['quest_engine']（quest_board/resolve_board_index/quest_accept/"
            "quest_complete/quest_progress/quest_abandon 消费接口）"
        ) from exc


# ---------------------------------------------------------------------------
# 任务板渲染（5 条/页 + 双板段头 + CakeGame 式尾段 + 裁决② 夹取；纯文本零装饰 emoji）
# ---------------------------------------------------------------------------

def _flatten_sections(board: Mapping[str, Any]) -> list:
    """引擎 sections → 全量 (段标题, row) 有序对（工程补白 2/3）。"""
    pairs: list = []
    for section in board.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        title = section.get("title") or ""
        for row in section.get("rows") or []:
            if isinstance(row, Mapping):
                pairs.append((title, row))
    return pairs


def render_board(board: Mapping[str, Any], page: object, *,
                 per_page: int = BOARD_PAGE_SIZE, ctx: Optional[Mapping[str, Any]] = None) -> str:
    """/任务 任务板列表正文（工程补白 2/3；模板配置化 2026-08-31：ctx 传 list_tail 覆盖尾段）：

    - 引擎 sections 扁平化后按 5 条/页横切（m4 §2.2）；段头「━━ {引擎标题} ━━」首次出现输出
      （表头不计条数，3d §2.1）；
    - 页码超总页数 → 夹取最后一页 + LAST_PAGE_HINT（裁决②）；0/负数/非数字 → raise ValueError
      （壳层应先经 resolve_page 判 TPL-12）；
    - CakeGame 式尾段（当前页 + Tip，2026-08-27 用户拍板统一列表尾段）。
    """
    pairs = _flatten_sections(board)
    total = int(board.get("total", len(pairs)))
    res = resolve_page(page, total, per_page)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 resolve_page 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None  # 非法已拦截，夹取后恒有页码
    if not pairs:
        return _EMPTY_BOARD
    start = (res.page - 1) * per_page
    slice_pairs = pairs[start:start + per_page]
    lines: List[str] = []
    seen: set = set()
    for i, (title, row) in enumerate(slice_pairs):
        if title and title not in seen:
            lines.append(f"━━ {title} ━━")
            seen.add(title)
        lines.append(board_line(start + i + 1, row))
    tail = render_cake_tail(res.page, res.total_pages, tip=_BOARD_TAIL_TIP,
                            templates=ctx.get("templates") if isinstance(ctx, Mapping) else None)
    if res.clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    lines.append(tail)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx → 回复正文）
# ---------------------------------------------------------------------------

def _seq_to_quest_id(ctx: Mapping[str, Any], engine: Any, seq: int) -> Optional[str]:
    """展示序号 → quest_id（引擎 resolve_board_index；None = 越界/非法）。"""
    try:
        return engine.resolve_board_index(ctx, seq)
    except Exception:
        return None


def cmd_quest_board(ctx: Mapping[str, Any], page: object) -> str:
    """/任务 [页码]：任务板列表（5 条/页 + TPL-08 页脚 + 裁决② 夹取；板不可用 → 引擎消息透传）。"""
    engine = _engine_of(ctx)
    board = engine.quest_board(ctx)
    if not board or not board.get("ok"):
        return str(board.get("message") or TPL_NO_BOARD) if board else TPL_NO_BOARD
    return render_board(board, page)


def cmd_quest_accept(ctx: Mapping[str, Any], seq: int) -> str:
    """/任务 接取 N：展示序号 → quest_id → 引擎接取（accept_limit/状态闸/unlock_chain 校验，消息透传）。"""
    engine = _engine_of(ctx)
    qid = _seq_to_quest_id(ctx, engine, seq)
    if qid is None:
        return TPL_NO_QUEST
    res = engine.quest_accept(qid, ctx)
    return str(res.get("message") or "❌ 接取失败")


def cmd_quest_deliver(ctx: Mapping[str, Any], seq: int) -> str:
    """/任务 交付 N：完成交付 → 统一 reward 发放结果提示（引擎 message，2b4 §3.2）；
    P1-2 逐条目失败黄字跳过注记（skipped 由本层渲染「（跳过：reason）」不吞整批）。"""
    engine = _engine_of(ctx)
    qid = _seq_to_quest_id(ctx, engine, seq)
    if qid is None:
        return TPL_NO_QUEST
    res = engine.quest_complete(qid, ctx)
    parts: List[str] = [str(res.get("message") or "❌ 交付失败")]
    for s in res.get("skipped") or []:
        if isinstance(s, Mapping) and s.get("reason"):
            parts.append(f"（跳过：{s['reason']}）")
        else:
            parts.append("（跳过）")
    return "\n".join(parts)


def cmd_quest_info(ctx: Mapping[str, Any], seq: int) -> str:
    """/任务 信息 N：查看已接任务进度（三原语进度逐条显示，本层合成；工程补白 7）。"""
    engine = _engine_of(ctx)
    qid = _seq_to_quest_id(ctx, engine, seq)
    if qid is None:
        return TPL_NO_QUEST
    res = engine.quest_progress(qid, ctx)
    if not res or not res.get("ok"):
        return str(res.get("message") or TPL_NO_QUEST) if res else TPL_NO_QUEST
    return info_text(res, seq)


def cmd_quest_abandon(ctx: Mapping[str, Any], seq: int) -> str:
    """/任务 放弃 N：放弃进行中任务（默认无惩罚，引擎处理可配惩罚，消息透传）。"""
    engine = _engine_of(ctx)
    qid = _seq_to_quest_id(ctx, engine, seq)
    if qid is None:
        return TPL_NO_QUEST
    res = engine.quest_abandon(qid, ctx)
    return str(res.get("message") or "❌ 放弃失败")


def cmd_quest(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/任务 [参数] 主入口（m4 §3.3 收口形式）：

      无参            → 任务板列表第 1 页（5 条/页 + TPL-08 页脚 + 双板段头）
      <整数>          → 页码翻页（裁决②：超页夹取最后一页 + 已到最后一页；0/负数/非数字 → TPL-12）
      接取 N / 交付 N / 信息 N / 放弃 N → 子指令（序号不带 `*`，2b4 §5.1）
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    gate = _gate(ctx)
    if gate is not None:
        return gate
    sub, seq = sub_and_seq(parsed)
    if sub is not None:
        n = parse_int(seq) if seq is not None else None
        if n is None or n < 1:
            return format_tpl12(_fragment(parsed))
        if sub == SUB_ACCEPT:
            return cmd_quest_accept(ctx, n)
        if sub == SUB_DELIVER:
            return cmd_quest_deliver(ctx, n)
        if sub == SUB_INFO:
            return cmd_quest_info(ctx, n)
        if sub == SUB_ABANDON:
            return cmd_quest_abandon(ctx, n)
    # 页码路径（工程补白 5）
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return cmd_quest_board(ctx, 1)
    raw_page = str(args[0])
    n = parse_int(raw_page)
    if n is None or n < 1:
        return format_tpl12(_fragment(parsed))
    return cmd_quest_board(ctx, n)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次6/7 待接线）
# ---------------------------------------------------------------------------

def register_quest_commands(router: Any, *, make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /任务 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 quest_engine 注入（工程补白 1）/
        quests/quest_active/quest_completed/quest_daily/longline_counters/items/currencies
        /settings 等，见 core/quest.py 工程补白 2）。None 时 handler 调用抛 RuntimeError
        （【待接线】批次6/7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】quest_commands.register_quest_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _quest(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_quest(parsed, injected)
        return cmd_quest(parsed, _ctx(parsed))

    router.register(CommandSpec(QUEST_CMD, handler=_quest))
    return router
