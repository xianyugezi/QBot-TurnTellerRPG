"""快捷指令接线 shortcut_commands.py（M6 批次1·路B · qbot_rpg/commands/shortcut_commands.py）。

依据：
  - docs/细化/细化_M6_三引擎与基础指令.md（M6 子细化 D1）§六 /快捷 契约：SHC-01~SHC-05、
    TC-SHC-01~03（承接 4f TC-22/23/17）；§七 P1-2（DELAYED 收口）
  - docs/细化/细化_4f_基础指令组契约.md（母契约）§五：CMD-07/CMD-08、RUL-30/31、
    TPL-4F-10/TPL-4F-11；§6.4 TC-17（帮助目录别名显示替换 → basic_commands.cmd_help 承接）
  - docs/细化/细化_3d_消息模板规范.md（TPL-12 / D-01 emoji 禁令 / 列表 5 条/页）
  - m4_shared_contract §2.2（列表 5 条/页 + CakeGame 式尾段 + 裁决② 夹取）
  - 【规范】6.6（快捷表 {快捷名: 完整指令串} 每玩家独立、随存档持久化，RUL-31）

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /快捷解绑 /快捷列表 从 Router 接到玩家
快捷表（ctx["shortcuts"] 可变 dict）——解绑（SHC-01：不存在 `❌ 没有绑定『xx』`；成功
`✅ 已解绑『xx』`，就地改写 ctx["shortcuts"]）、列表（SHC-02：头部 `【快捷（N/20）】` +
每行 `快捷名 → 指令串`，5 条/页 + CakeGame 式尾段 + 裁决② 夹取；空表引导文案）。
快捷绑定/冲突检测/覆盖重绑机制归 router.check_shortcut_binding（3c §4，既有），本层不重定义
（SHC-01 后半）；持久化落点归 4a 存储层 + 装配层 make_context（SHC-03，本层零 IO）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性；工程补白一律
【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌）。

--------------------------------------------------------------------------------
ctx 消费契约（装配层 make_context 注入；未注入字段按缺省兜底）：
  shortcuts: MutableMapping[str, str]   玩家快捷表 {快捷名: 完整指令串}（解绑就地改写）
  shortcut_max: int                     快捷上限（缺省 20；列表头部分母，RUL-26/31）
--------------------------------------------------------------------------------

【工程补白 · 显式标注】
  1) /快捷解绑 语法 = `快捷解绑 <自定义快捷名>`（CMD-07，恰好 1 参数）；0 参/超参/解析错误
     → TPL-12（格式错误统一）。
  2) /快捷列表 支持可选页码 `快捷列表 [页码]`（m4 §2.2 列表 5 条/页横切；SHC-02 契约仅定
     无参形态，翻页为工程补白扩展）；页码 0/负数/非数字 → TPL-12；超页夹取（裁决②）。
  3) 列表尾段用 CakeGame 式（render_cake_tail：当前页 + Tip），对齐 /背包 /角色 等列表尾段
     统一口径（2026-08-27 用户拍板），不再自造 TPL-08 页脚。
  4) 未注册拦截走 RUL-08 门槛（RUL-08：任何游玩指令；/帮助 豁免 B6，快捷指令非豁免）：
     复用 basic_commands.TPL_REGISTER_GATE。
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_cake_tail,
    resolve_page,
)

# 同包兄弟模块：相对导入（G0 架构门禁不产生 `qbot_rpg.commands` 前缀反向依赖边；
# 同层兄弟引用架构合规，与 sender.py 同口径）。
from .basic_commands import TPL_REGISTER_GATE
from .parsers import parse_int
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    "SHORTCUT_UNBIND_CMD",
    "SHORTCUT_LIST_CMD",
    "DEFAULT_SHORTCUT_MAX",
    # 文案常量
    "TPL_SHORTCUT_EMPTY",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_shortcut_unbind",
    "cmd_shortcut_list",
    # 装配
    "register_shortcut_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SHORTCUT_UNBIND_CMD = "快捷解绑"
SHORTCUT_LIST_CMD = "快捷列表"

# 快捷上限（RUL-26 / 规范 L172：默认 20 条，settings 可配 0=不限；列表头部分母）
DEFAULT_SHORTCUT_MAX = 20

# 空表引导文案（SHC-02 / TPL-4F-11）
TPL_SHORTCUT_EMPTY = "❌ 还没有快捷绑定，试试 /快捷绑定 1 攻击"

# 列表尾段 Tip（工程补白 3；发送'...'即可... 由 tip 自行拼装）
_LIST_TAIL_TIP = "发送'快捷绑定 名字 指令'即可绑定快捷"


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
    """RUL-08 注册门槛（工程补白 4）：ctx["registered"] is False → 拦截文案；
    缺省视为已注册（对齐 basic_commands 工程补白 7）。"""
    if ctx.get("registered", True) is False:
        return TPL_REGISTER_GATE
    return None


def _shortcuts(ctx: MutableMapping[str, Any]) -> MutableMapping[str, str]:
    """玩家快捷表（ctx["shortcuts"] 可变 dict；缺省就地建空表，供解绑/列表读写）。"""
    s = ctx.get("shortcuts")
    if isinstance(s, MutableMapping):
        return s
    if isinstance(s, Mapping):
        fresh: dict = dict(s)
        ctx["shortcuts"] = fresh
        return fresh
    fresh = {}
    ctx["shortcuts"] = fresh
    return fresh


def _shortcut_max(ctx: Mapping[str, Any]) -> int:
    """快捷上限（ctx["shortcut_max"] 缺省 20；0/负数按缺省兜底）。"""
    m = ctx.get("shortcut_max", DEFAULT_SHORTCUT_MAX)
    try:
        m = int(m)
    except (TypeError, ValueError):
        return DEFAULT_SHORTCUT_MAX
    return m if m > 0 else DEFAULT_SHORTCUT_MAX


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx → 回复正文）
# ---------------------------------------------------------------------------

def cmd_shortcut_unbind(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/快捷解绑 <自定义快捷名>（CMD-07 / SHC-01 / TPL-4F-10）：

      语法（CMD-07）  恰好 1 参数；0 参/超参/解析错误 → TPL-12（工程补白 1）
      不存在（SHC-01） `❌ 没有绑定『xx』`
      成功（SHC-01）   `✅ 已解绑『xx』`，就地改写 ctx["shortcuts"]（落档归装配层 SHC-03）
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) != 1:
        return format_tpl12(_fragment(parsed))
    name = str(args[0])
    shortcuts = _shortcuts(ctx)
    if name not in shortcuts:
        return f"❌ 没有绑定『{name}』"
    del shortcuts[name]
    return f"✅ 已解绑『{name}』"


def cmd_shortcut_list(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/快捷列表 [页码]（CMD-08 / SHC-02 / TPL-4F-11）：

      无参        → 第 1 页；每行 `快捷名 → 指令串`，头部 `【快捷（N/20）】`
      空表（SHC-02） → `❌ 还没有快捷绑定，试试 /快捷绑定 1 攻击`
      页码（补白 2） → 5 条/页 + CakeGame 式尾段 + 裁决② 夹取；0/负数/非数字 → TPL-12
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = 1
    if args:
        n = parse_int(str(args[0]))
        if n is None or n < 1:
            return format_tpl12(_fragment(parsed))
        page = n

    shortcuts = _shortcuts(ctx)
    if not shortcuts:
        return TPL_SHORTCUT_EMPTY

    items = [(str(k), str(v)) for k, v in shortcuts.items()]
    res = resolve_page(page, len(items), DEFAULT_PAGE_SIZE)
    if res.invalid:
        return format_tpl12(_fragment(parsed))
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_items = items[start:start + DEFAULT_PAGE_SIZE]

    cap = _shortcut_max(ctx)
    lines: List[str] = [f"【快捷（{len(items)}/{cap}）】"]
    for name, cmd in slice_items:
        lines.append(f"{name} → {cmd}")
    tail = render_cake_tail(res.page, res.total_pages, tip=_LIST_TAIL_TIP)
    if res.clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    lines.append(tail)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次7 待接线）
# ---------------------------------------------------------------------------

def register_shortcut_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /快捷解绑 /快捷列表 注册进 Router（CommandSpec.handler 消费 ParsedCommand；SHC-05 ①）。

    :param make_context: ParsedCommand → 玩家 ctx dict（shortcuts 可变表/shortcut_max 等，
        见本模块各函数消费契约；持久化落档归装配层 SHC-03）。None 时 handler 调用抛
        RuntimeError（【待接线】批次7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】shortcut_commands.register_shortcut_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _unbind(parsed: Any, *a: Any, **k: Any) -> str:
        return cmd_shortcut_unbind(parsed, _ctx(parsed))

    def _list(parsed: Any, *a: Any, **k: Any) -> str:
        return cmd_shortcut_list(parsed, _ctx(parsed))

    router.register(CommandSpec(SHORTCUT_UNBIND_CMD, handler=_unbind))
    router.register(CommandSpec(SHORTCUT_LIST_CMD, handler=_list))
    return router
