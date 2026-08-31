"""M10 钓鱼·批2·路2C（主 agent 收口补齐）：/鱼讯 + /收杆 三选一 指令壳。

文件名：qbot_rpg/commands/fishing_reel_commands.py
创建时间：2026-08-31
作者：Hermes 主 agent（路2C 子 agent 撞 429 半落盘——fishing_roll.py 已落盘完整，
      指令壳/测试缺失，由主 agent 按 M9 先例接手补齐，契约同源）

功能描述（T08 / T09 · 细化_2c1b §四/§五）：
  /鱼讯 推进（T08，细化 §五）：
    - S2 等待中：返回 钓点/已耗时/等待中（TC-21）
    - S3 已触发：返回 鱼讯类别（含金闪标记行）+ 收杆提醒（TC-22）
    - 空闲：返回空态「无进行中钓局」不报错（TC-23）
  /收杆 三选一（T09，细化 §四）：
    - 满力/自动/止损 三选一；缺省参数默认自动（细化 §4.1 实现层默认）
    - 止损：不 roll，饵已计耗不返还、不触发鱼讯收益（TC-17）
    - 满力/自动：注入 roll_hook 调 core.fishing_roll.roll_rarity（种子 42/2026
      可复现 54/37/9 与 70/25/5，TC-15/16）
    - 决策窗超时（carry_sec）→ TR-07 SL 跑鱼；非法 choice → 提示三选一

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §四（收杆三选一 + roll 锚点 4.2 +
    止损语义）+ §五（/鱼讯 推进 TC-21/22/23）+ §六 TC-15~20
  - 定稿 §1 M5（收杆三选一 L19）/ §6 L111（/收杆 三选一）/ §四 L94（概率锚点）
  - docs/m10_shared_contract.md §二 IF-10（reel_in）/ §四 4.2（roll 概率锚点）
  - docs/m10_接口摸底.md §九（rng 注入种子 42/2026、F3 嵌套事务、qid 注入）
模式参考：
  - qbot_rpg/commands/fishing_commands.py（路2A 指令壳：register_* + cmd_* +
    _mode_of/_render + _body_args + tpl_of fallback）
  - qbot_rpg/core/fishing_roll.py（路2C 已落盘：roll_rarity/roll_weights/
    has_matching_bait/pull_odds_of）

【工程补白】（显式标注供审查）：
  R-1  roll_hook 注入：引擎 reel_in 的 roll_hook 注入位（callable(ctx, fs,
      choice)->dict）在装配层挂 roll_rarity 包装——本指令壳直接构造引擎时
      注入 self._roll_hook（包装 roll_rarity 返回 {ok, rarity}），测试注入
      mock；装配层 make_context 注入 ctx["fishing_engine"] 后指令壳复用。
  R-2  /收杆 参数解析：tokens[1:] 首参 = 满力|自动|止损（别名 满/自/止 兼容）；
      无参 → 自动（细化 §4.1 实现层默认）；非法 → 提示三选一（不报错）。
  R-3  /鱼讯 状态读取：读 ctx["fish_state"]（_ps_init 挂 ps 形态）——state 为
      WAITING/BITE/IDLE 三态；已耗时 = now - cast_at（负 → 0）。
  R-4  消息模板：本地 fallback 常量（批6 fishing_tpl 分区迁移，同路2A 约定），
      渲染走 tpl_of(ctx, "fish_*", {...}) key 占位。

铁律：零 NoneBot import（commands 层只用 parsed/ctx 契约）；纯函数确定性
      （同刻同参必同值）；零定时器/零睡眠（时间戳懒判）；渲染零 emoji；
      文件头标注依据；不 git commit。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core.fishing import (
    STATE_BITE,
    STATE_WAITING,
    FishingEngine,
)
from qbot_rpg.core.fishing_roll import roll_rarity
from qbot_rpg.core.fishing_settings import fishing_cfg
from qbot_rpg.core.templates import tpl_of

from .router import CommandSpec

__all__ = [
    "FISH_BITE_CMD",
    "FISH_REEL_CMD",
    "CHOICE_FULL",
    "CHOICE_AUTO",
    "CHOICE_STOP",
    "cmd_fish_bite",
    "cmd_fish_reel",
    "register_fishing_reel_commands",
]

# ---------------------------------------------------------------------------
# 指令名常量 + 收杆三选一
# ---------------------------------------------------------------------------
FISH_BITE_CMD: str = "鱼讯"
FISH_REEL_CMD: str = "收杆"

CHOICE_FULL: str = "满力"
CHOICE_AUTO: str = "自动"
CHOICE_STOP: str = "止损"

# 别名（R-2：满/自/止 兼容）→ 引擎英文键（REEL_CHOICES: full/auto/stop）
_CHOICE_ALIASES: Mapping[str, str] = {
    "满力": "full",
    "满": "full",
    "自动": "auto",
    "自": "auto",
    "止损": "stop",
    "止": "stop",
}

# ---------------------------------------------------------------------------
# 消息常量（R-4：TODO 批6 fishing_tpl 分区迁移，默认模板与旧输出逐字一致）
# ---------------------------------------------------------------------------
_DEF_BITE_WAITING: str = "等待中：{spot} · 已耗时 {elapsed}s（鱼讯未触发）"
_DEF_BITE_TRIGGERED: str = "{kind_cn}！{golden_line}收杆吧：/收杆 满力 / 自动 / 止损"
_DEF_BITE_IDLE: str = "无进行中钓局"
_DEF_REEL_STOP: str = "已止损收杆（饵已消耗，本局无鱼获）"
_DEF_REEL_RUN: str = "收杆成功！{kind_cn} · {rarity_cn}"
_DEF_REEL_TIMEOUT: str = "鱼跑了……（收杆超时）"
_DEF_REEL_BAD_CHOICE: str = "请选择：满力 / 自动 / 止损"

# 稀有度中文标记（对齐 fishing_commands._RARITY_CN 口径）
_RARITY_CN: Mapping[str, str] = {
    "normal": "普通",
    "rare": "稀有",
    "gold": "金色",
}

# 鱼讯类别中文（对齐 fishing.KIND_LABELS：micro 微动 / tug 拉扯 / violent 猛烈）
_KIND_CN: Mapping[str, str] = {
    "micro": "微动",
    "tug": "拉扯",
    "violent": "猛烈",
}


# ---------------------------------------------------------------------------
# 私有 helper（对齐路2A 口径）
# ---------------------------------------------------------------------------
def _mode_of(ctx: Mapping[str, Any]) -> str:
    """mode 三态读取（fishing_cfg 兜底，off 全拒绝）。"""
    cfg = fishing_cfg(ctx)
    mode = cfg.get("mode")
    return str(mode) if isinstance(mode, str) else "full"


def _render(ctx: Mapping[str, Any], key: str, fallback: str, data: Mapping[str, Any]) -> str:
    """tpl_of 渲染 + 本地 fallback（批6 迁模板后 tpl_of 分区 key 生效）。"""
    out = tpl_of(ctx, key, data)
    return out if out else fallback.format(**data)


def _body_args(parsed: Any) -> list:
    """参数提取（对齐路2A _body_args：tokens[1:] 优先，args 兜底）。"""
    raw_tokens = list(getattr(parsed, "tokens", None) or [])
    if raw_tokens:
        return [str(t) for t in raw_tokens[1:]]
    args = list(getattr(parsed, "args", None) or [])
    return [str(a) for a in args]


def _normalize_choice(raw: str) -> Optional[str]:
    """收杆选项归一（R-2：满力/满/自动/自/止损/止；非法 → None）。"""
    return _CHOICE_ALIASES.get(raw.strip())


def _elapsed(ctx: Mapping[str, Any], fs: Mapping[str, Any]) -> int:
    """已耗时（R-3：now - cast_at，负 → 0 夹取，对齐路2B C-4）。"""
    now = ctx.get("now")
    cast_at = fs.get("cast_at")
    if not isinstance(now, (int, float)) or not isinstance(cast_at, (int, float)):
        return 0
    return max(0, int(now) - int(cast_at))


def _kind_cn(kind: object) -> str:
    """鱼讯类别中文（未知 → 原样）。"""
    return _KIND_CN.get(str(kind), str(kind))


def _rarity_cn(rarity: object) -> str:
    """稀有度中文（未知 → 原样）。"""
    return _RARITY_CN.get(str(rarity), str(rarity))


def _engine_of(ctx: MutableMapping[str, Any]) -> FishingEngine:
    """引擎复用（对齐路2B：ctx["fishing_engine"] 已注入 → 复用；缺省自建）。"""
    eng = ctx.get("fishing_engine")
    if isinstance(eng, FishingEngine):
        return eng

    def _roll_hook(_ctx: Any, fs: Any, choice: Any) -> dict:
        r = roll_rarity(choice, _ctx, _ctx, _ctx.get("rng"))
        return {"ok": True, "rarity": r}

    eng = FishingEngine(
        settings=ctx.get("settings"),
        rng=ctx.get("rng"),
        roll_hook=_roll_hook,
    )
    ctx["fishing_engine"] = eng
    return eng


# ---------------------------------------------------------------------------
# /鱼讯 主入口（T08 · 细化 §五）
# ---------------------------------------------------------------------------
def cmd_fish_bite(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """状态查询（TC-21/22/23，纯函数确定性）。

    路由：
      - off 模式 → 拒绝（GU-01，对齐路2A）
      - S2 等待中 → 钓点/已耗时/等待中
      - S3 已触发 → 鱼讯类别（含金闪标记行）+ 收杆提醒
      - 空闲/无钓局 → 空态「无进行中钓局」不报错
    """
    if _mode_of(ctx) == "off":
        return _render(ctx, "fish_off", "钓鱼功能已关闭", {})

    fs = ctx.get("fish_state")
    if not isinstance(fs, MutableMapping):
        return _render(ctx, "fish_bite_idle", _DEF_BITE_IDLE, {})

    state = fs.get("state")
    spot_id = fs.get("spot_id")
    spot = str(spot_id or "--")

    if state == STATE_WAITING:
        return _render(ctx, "fish_bite_waiting", _DEF_BITE_WAITING, {
            "spot": spot,
            "elapsed": _elapsed(ctx, fs),
        })

    if state == STATE_BITE:
        kind = fs.get("bite_kind") or "micro"
        golden = bool(fs.get("golden"))
        golden_line = "（金闪！）" if golden else ""
        return _render(ctx, "fish_bite_triggered", _DEF_BITE_TRIGGERED, {
            "kind_cn": _kind_cn(kind),
            "golden_line": golden_line,
        })

    # 空闲 / 其它
    return _render(ctx, "fish_bite_idle", _DEF_BITE_IDLE, {})


# ---------------------------------------------------------------------------
# /收杆 主入口（T09 · 细化 §四）
# ---------------------------------------------------------------------------
def cmd_fish_reel(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """收杆三选一（TC-15~20，纯函数确定性）。

    路由：
      - off 模式 → 拒绝（GU-01）
      - 无参 → 默认自动（细化 §4.1 实现层默认）
      - 满力/自动 → 引擎 reel_in（注入 roll_hook）→ 出鱼（批3 结算接线）
      - 止损 → 不 roll，饵已计耗不返还、无收益（TC-17）
      - 决策窗超时 → TR-07 跑鱼（TC-08）
      - 非法 choice → 提示三选一（R-2）
    """
    if _mode_of(ctx) == "off":
        return _render(ctx, "fish_off", "钓鱼功能已关闭", {})

    args = _body_args(parsed)
    raw = args[0] if args else CHOICE_AUTO  # 无参 → 默认自动
    choice = _normalize_choice(raw)
    if choice is None:
        return _render(ctx, "fish_reel_bad_choice", _DEF_REEL_BAD_CHOICE, {})

    eng = _engine_of(ctx)
    result = eng.reel_in(ctx, choice)

    if isinstance(result, Mapping) and result.get("ok") is False:
        # 拒绝场景（无进行中钓局 / 决策窗超时 / 状态异常）
        reason = result.get("reason")
        if reason == "timeout" or reason == "lost":
            return _render(ctx, "fish_reel_timeout", _DEF_REEL_TIMEOUT, {})
        if reason == "no_session" or reason == "idle":
            return _render(ctx, "fish_bite_idle", _DEF_BITE_IDLE, {})
        msg = result.get("message")
        if isinstance(msg, str) and msg:
            return msg
        return _render(ctx, "fish_reel_bad_choice", _DEF_REEL_BAD_CHOICE, {})

    # 成功：止损 vs 满力/自动（choice 已是引擎英文键）
    if choice == "stop":
        return _render(ctx, "fish_reel_stop", _DEF_REEL_STOP, {})

    rarity = "normal"
    kind = "micro"
    if isinstance(result, Mapping):
        roll = result.get("roll") or {}
        if isinstance(roll, Mapping):
            rarity = str(roll.get("rarity") or rarity)
        kind = str(result.get("kind") or result.get("bite_kind") or kind)
    return _render(ctx, "fish_reel_success", _DEF_REEL_RUN, {
        "kind_cn": _kind_cn(kind),
        "rarity_cn": _rarity_cn(rarity),
    })


# ---------------------------------------------------------------------------
# 装配：register_fishing_reel_commands（/鱼讯 + /收杆）
# ---------------------------------------------------------------------------
def register_fishing_reel_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /鱼讯 + /收杆 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 fish_state/fishing_engine/
        now/settings 等，见 cmd_fish_bite/cmd_fish_reel ctx 契约）。None 时 handler
        调用抛 RuntimeError（【待接线】装配层注入，对齐路2A 口径）。
    """

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "fishing_reel_commands.register_fishing_reel_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _bite(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_fish_bite(parsed, injected)
        return cmd_fish_bite(parsed, _ctx(parsed))

    def _reel(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_fish_reel(parsed, injected)
        return cmd_fish_reel(parsed, _ctx(parsed))

    router.register(CommandSpec(FISH_BITE_CMD, handler=_bite))
    router.register(CommandSpec(FISH_REEL_CMD, handler=_reel))
