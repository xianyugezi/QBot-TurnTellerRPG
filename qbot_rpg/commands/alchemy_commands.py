"""炼金指令接线 alchemy_commands.py（M8 批2·路2A ·
qbot_rpg/commands/alchemy_commands.py）——本批只注册 /合成。

文件名：qbot_rpg/commands/alchemy_commands.py
创建时间：2026-08-29
作者：Hermes 子agent-2A（并发同仓：仅新建本文件 + qbot_rpg/core/synthesis.py +
  tests/unit/test_synthesis.py + tests/unit/test_synthesis_commands.py）

功能描述：把 `/合成` 指令从 Router 接到 core/synthesis.py 引擎——指令解析（parsers.parse_command 已
  token 化 → 本模块取 args[0] 配方名/序号 + parsed.qty 数量）、配方解析与全部业务文案委托引擎
  （引擎已按契约 M-01 合成 ✅/❌ 文案）、错误统一 TPL-12
  （sender.format_tpl12，errors.py 唯一文案源）、
  register_alchemy_commands 装配入口（仿 shop_commands.register_shop_commands 壳模式）。

本批范围：**只注册 /合成（SYNTH_CMD）**；其余炼金指令（/炼金 /投料 /继承 /深度炼金 /进化 /分解
  /复制 /图鉴 /技能面板 /种植 /收获 /雇工 /教学 等）由后续批次填充
  （批4A /炼金、批4B /投料、批5 /继承、
  批6 /分解 /确认、批7 /成品合成 /配方合成 /特性合成 /镶嵌 /拆珠 /登记 /复制、批8 /深度炼金 /进化 /
  镶核心 /加成 /挑战 /图鉴 /技能面板 /教学、批10 /种植 /收获 /雇工 /收取）——本模块作为这些指令壳的
  统一落点文件，后续批次追加 cmd_xxx + register 项即可。

依据：
  - docs/m8_contract_指令契约.md §1 /合成（P-01 参数解析 / GU-01~04 /
    F-01 / M-01，实现批次批2 路2A）、
    §六 IF 清单（cmd_synth 签名 (parsed, ctx) -> str；register_alchemy_commands(router, *,
    make_context=None) 壳模式，本契约命名 cmd_synthesis 对齐任务清单）、§3.4 数量上限 max_qty 注入。
  - qbot_rpg/commands/shop_commands.py（壳模式参考：cmd_xxx(parsed, ctx) -> str 纯函数、
    register_shop_commands(router, *, make_context=None)、零 NoneBot import、
    错误走 sender.format_tpl12、
    __all__ 导出、装饰性 emoji 禁用仅 ✅/❌ 功能性标记、_target_of 剥离 `+`/`*N`）。
  - qbot_rpg/core/synthesis.py（SynthesisEngine 引擎，本模块为其指令壳接线消费方）。

铁律（3a R1 / m4 §0）：**零 NoneBot import**、纯函数（同刻同参必同值）、
确定性（now/rng 由 ctx 注入）；
工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌ 功能性标记）。
本模块只做「装配接线 + 解析 + 透传」，业务结算全部委托引擎。

【工程补白 · 显式标注】
  1) 引擎构造：cmd_synthesis 每次调用以 `SynthesisEngine(settings=ctx.get("settings"))` 构造——
     配置单源（构造器注入，对齐 core/synthesis.py 工程补白 1）；
     ctx["settings"] 缺失 → 引擎默认值兜底。
  2) 配方目标解析：parsed.args[0] 保留原文含 `*数量`（解析器契约，对齐 shop cmd_buy `_target_of`），
     qty 已结构化 → 剥离前导 `+`（紧凑连接符收敛）与 `*N` 后传引擎；引擎再按名称/序号解析。
  3) 超限提示（拍板⑤）由引擎在 synthesize 内归一 count 时处理（settings.alchemy.max_qty 缺省
     2147483647）；parsers 侧 max_qty 注入属批11 路11A 装配职责，本层不重复。
  4) make_context 玩家上下文工厂由装配层注入（register_alchemy_commands 的 make_context 参数），
     注入前本层可纯函数单测（直接构造 ctx，仿 test_shop_commands.make_ctx）。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core.synthesis import SynthesisEngine

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 shop_commands.py 同口径）。
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名常量
    "SYNTH_CMD",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_synthesis",
    # 装配
    "register_alchemy_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SYNTH_CMD = "合成"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 shop_commands._fragment）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _target_of(parsed: Any) -> str:
    """配方目标名剥离（解析器契约 + 紧凑 `+` 连接符收敛，对齐 shop_commands._target_of）：

    - 解析器契约：args[0] 保留原文含 `*数量`，qty 已结构化 → 剥离 `*N` 后传引擎
      （`/合成 火焰弹配方*10` → args=["火焰弹配方*10"], qty=10 → 目标 "火焰弹配方"）。
    - 【工程补白】紧凑格式 `合成+火焰弹配方` 中 `+` 为紧凑连接符（解析器归等级分隔符
      → args[0]="+火焰弹配方"）；配方名不含 `+`（保留字符，REC-16），故剥离前导 `+` 收敛。
    """
    t = str(parsed.args[0])
    if t.startswith("+"):
        t = t[1:]
    if "*" in t:
        t = t.split("*", 1)[0]
    return t


def cmd_synthesis(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/合成 <配方>*<数量>`：配方解析（名称/序号）与守卫/原子校验/标准版产出/熟练经验全部委托引擎；
    结果 `message` 透传（含缺材料差异、等级不足、深度未解锁、数量超限提示不拦截）。
    缺参/解析错误 → TPL-12。

    入参：parsed（ParsedCommand）、ctx（玩家表示 + 配方/物品注册表 + settings）。
    出参：回复正文 str（引擎已按契约 M-01 合成 ✅/❌ 业务文案）。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{SYNTH_CMD}")
    target = _target_of(parsed)
    qty = parsed.qty if parsed.qty is not None else 1
    settings = ctx.get("settings")
    engine = SynthesisEngine(settings=settings if isinstance(settings, Mapping) else None)
    res = engine.synthesize(ctx, target, qty)
    return str(res.get("message") or "❌ 合成失败")


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批11 路11A 待接线）
# ---------------------------------------------------------------------------

def register_alchemy_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 `/合成` 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    本批只注册 SYNTH_CMD；其余炼金指令后续批次在此函数追加
    `router.register(CommandSpec(CMD, handler=_xxx))`（文件头列明批次归属）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 items/recipe/settings/currencies/
        proficiency/inventory 等，见 core/synthesis.py 工程补白 1）。None 时 handler 调用抛
        RuntimeError（【待接线】批11 路11A 装配入口注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】alchemy_commands.register_alchemy_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _synth(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_synthesis(parsed, injected)
        return cmd_synthesis(parsed, _ctx(parsed))

    router.register(CommandSpec(SYNTH_CMD, handler=_synth))
    return router
