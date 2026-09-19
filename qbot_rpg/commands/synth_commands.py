"""批39 · 合成公用层：第 1 层【合成】指令壳（qbot_rpg/commands/synth_commands.py）。

文件名：qbot_rpg/commands/synth_commands.py
创建时间：2026-09-19
作者：主 agent（批39 · 「合成」提升为打造与炼金的公用系统）

功能描述：**合成（跨职业）是打造与炼金的公用第 1 层**——本模块是该公用层的指令落点，
  与炼金专属层（`commands/alchemy_commands.py`）解耦。承载内容：

  - `/合成 <配方>*<数量>`（`SYNTH_CMD`）——配方+材料 → 直接得标准版成品；全部业务逻辑
    委托公用引擎 `core/synthesis.py::SynthesisEngine`（守卫 GU-01~03 / 原子校验 GU-04 /
    标准版产出 LAY-04a / 熟练经验 CASC-01 / 合成图鉴 / 数量上限）。
  - `register_synth_commands(router, *, make_context=None)` 装配入口（仿
    `shop_commands.register_shop_commands` 壳模式；`make_context` 由装配层注入）。

依据：
  - `docs/深度打造_决策记录.md` §六（用户 2026-09-19 二次拍板：「合成」提升为打造与炼金的
    公用系统；落地动作 1「指令归位：/合成 从 alchemy_commands 提到公用层，保持指令名与
    行为不变」）。
  - `docs/审查参考/炼金系统设计定稿.md` :5/:18/:36/:44/:47（第 1 层【合成】（跨职业）——
    配方+材料 → 直接得成品；只产标准版）。
  - `docs/审查参考/RPG回合制框架设计文档.md` :2719/:2720（`mode` 三态 full/simple/off；
    simple 仅合成层）。

归位纪律（批39 红线）：
  - **指令名 / 参数形态 / 输出文案 / 行为一律不变**——`cmd_synthesis` 为原
    `alchemy_commands.cmd_synthesis` 的**逐字搬迁**（提层前后同输入同输出，回归对拍见
    `tests/unit/test_batch39_synth_relocation.py`）。
  - 兼容性再导出：`alchemy_commands.SYNTH_CMD` / `alchemy_commands.cmd_synthesis` 继续可用
    （历史调用方零改动）。
  - 同名指令**只注册一次**：`/合成` 的注册从 `register_alchemy_commands` **移出**到本模块，
    全量装配（`assembly/router_setup.REGISTER_GROUPS`）不得双注册。

铁律（对齐同层指令模块）：零 NoneBot import；`CommandSpec.handler` 消费 ParsedCommand；
  `handler` 支持 `k.get("ctx")` 装配层注入；本模块不含任何内容包业务名。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core.synthesis import SynthesisEngine
from qbot_rpg.core.templates import tpl_of

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规）。
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    "SYNTH_CMD",
    "cmd_synthesis",
    "register_synth_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SYNTH_CMD = "合成"


# ---------------------------------------------------------------------------
# 解析辅助（与 alchemy_commands 同口径；本模块自持，避免公用层反向依赖炼金层）
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


# ---------------------------------------------------------------------------
# 指令处理器
# ---------------------------------------------------------------------------

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
    return str(res.get("message") or tpl_of(ctx, "alchemy_synth_fail"))


# ---------------------------------------------------------------------------
# 装配入口
# ---------------------------------------------------------------------------

def register_synth_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把公用合成层指令 `/合成` 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    handler 支持 k.get("ctx") 注入（装配层 _invoke_handler 以 ctx=ctx 注入，
    assembly/runner.py；runner 对 isawaitable 结果自动 await）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 player/settings/items/recipe/
        currencies/proficiency 等）。None 时 handler 调用抛 RuntimeError（【待接线】）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】synth_commands.register_synth_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _synth(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_synthesis(parsed, injected)
        return cmd_synthesis(parsed, _ctx(parsed))

    # 同名指令只注册一次：/合成 的注册在本模块（已从 alchemy_commands 移出）。
    router.register(CommandSpec(SYNTH_CMD, handler=_synth))
    return router
