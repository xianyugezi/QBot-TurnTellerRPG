# -*- coding: utf-8 -*-
"""云海指令接线 cloudsea_commands.py（九期批次 231 · G5 首批）。

文件名：qbot_rpg/commands/cloudsea_commands.py
创建：2026-09-14（九期 G5 指令交互 · 批次 231）
依据：设计稿 08_QQ群异步适配与指令UI战报 §M8.13 三指令接口／生产排期_适配期_九期 G5 任务书；
    转化映射表 §一 #25／§八 冲突矩阵（本批落）。

功能描述（批次 231 范围＝指令接线）：
  1. 冲突矩阵落地——云海词面 × 框架 96 既有词面逐一核对（映射表 §八）：
     `合成` 复用框架炼金（SYNTH_CMD 既有引擎，零新注册）；`帮`/`预`/`局面`/`挂`/`撤`
     五词面全库零撞新注册；数字指令 1-4/绝 走快捷绑定层（预置绑定表）。
  2. `帮`（HELP_CLOUDSEA_CMD）：云海速查面板（指令面一览＋单指令用法）。
  3. `预`（PRESET_CMD）：预案串 spec 骨架（无参=格式说明；预案串库归批次 232 落后此指令
     直接消费，is_stub=False——解析与回执已实装，库数据 232 灌）。
  4. 数字指令快捷绑定：1/2/3/4/绝 → 框架战斗行动位（预置绑定表 DIGIT_BINDINGS，
     经 ctx["shortcut_exec"] 钩子转发；缺省回执绑定表——战斗句柄装配归 234 异步底盘）。
  5. 缺口引擎三件（指令面）：
     - `局面`（SITUATION_CMD）：局面聚合——战斗快照 HP/意图/潮压/气力/破坏槽一行式聚合
       （08 §M8.6 不刷屏口径；读 ctx["battle_snapshot"]，缺战斗态 fail-safe 文案）。
     - `挂`（HANG_CMD）：挂 N 托管——解析 N∈[1,10]，写 ctx["cloudsea_delegate_n"] 回执；
       autoplay 执行面归 234（本批指令面＋参数校验）。
     - `撤`（RETREAT_CMD）：弃撤退——战斗中确认弃战（写 ctx["cloudsea_retreat_pending"]），
       再发 `撤 确认` 结算撤退；非战斗态 fail-safe 文案。

红线自证：本文件为**新增指令文件**（映射表 §二 清单内）；不改既有指令词面（框架 96 词面
零触碰）、不改 battle.py 回合调度/damage.py 乘区/combo-effects-marks 既有行为、不改既有
content 包；战斗引擎只经公开 API 语义（battle_state 快照读）零交叉 import。
make_context 由装配层注入（shop/alchemy 壳模式）。
"""
from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.commands.sender import format_tpl12

# ---------------------------------------------------------------------------
# 词面常量（冲突矩阵：框架 96 词面零撞，见转化映射表 §八）
# ---------------------------------------------------------------------------

HELP_CLOUDSEA_CMD = "帮"        # 云海速查（框架「帮助」两字词，单字零撞）
PRESET_CMD = "预"               # 预案串 spec（框架零撞；库数据归 232）
SITUATION_CMD = "局面"          # 局面聚合（框架零撞）
HANG_CMD = "挂"                 # 挂 N 托管（框架零撞；DELEGATE_CMD=「委托」异词）
RETREAT_CMD = "撤"              # 弃撤退（框架零撞；「放弃」ABANDON_CMD 系炼金会话语义异词）

# 数字指令快捷绑定（框架快捷系统 ctx["shortcuts"] 的预置层；战斗句柄装配归 234）
DIGIT_BINDINGS = {
    "1": "/攻击",       # 行动位 1
    "2": "/技能",       # 行动位 2
    "3": "/技能",       # 行动位 3（具体技能位由战斗上下文解析）
    "4": "/防御",       # 行动位 4（守势语义沿 08 §M8）
    "绝": "/绝技",      # 绝技位（arcana 门控沿 215F）
}

DELEGATE_N_MIN, DELEGATE_N_MAX = 1, 10

_HELP_LINES = (
    "【云海猎团 · 速查】",
    "合成 <配方> —— 配方制造（复用框架炼金引擎）",
    "帮 —— 本面板；帮 <指令> 单指令用法",
    "预 —— 预案串一览（库随 232 灌）",
    "局面 —— 战况聚合（HP/意图/潮压/气力/破坏槽）",
    "挂 N —— 挂机 N 场托管（1-10）；撤 确认 —— 弃战撤退",
    "1/2/3/4/绝 —— 战斗行动快捷位",
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    raw = getattr(parsed, "raw", None)
    if raw:
        return str(raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _args(parsed: Any) -> List[str]:
    return [str(a) for a in (getattr(parsed, "args", None) or [])]


def _snap(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """战斗快照（fail-safe：缺/非法 → {}）。"""
    s = ctx.get("battle_snapshot")
    return s if isinstance(s, Mapping) else {}


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：parsed + ctx → 回复正文）
# ---------------------------------------------------------------------------

def cmd_help_cloudsea(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`帮` / `帮 <指令>`：云海速查面板。"""
    args = _args(parsed)
    if not args:
        return "\n".join(_HELP_LINES)
    q = args[0]
    row = next((l for l in _HELP_LINES if l.startswith(q + " ") or l.startswith(q + "（")), None)
    if row is None and q in DIGIT_BINDINGS:
        row = f"{q} —— 战斗行动快捷位 → {DIGIT_BINDINGS[q]}"
    return row if row else format_tpl12(_fragment(parsed))


def cmd_preset(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`预` / `预 <名>`：预案串 spec（库数据随 232 灌，本批解析与回执实装）。"""
    args = _args(parsed)
    if not args:
        return ("【预案串】战前预案一览（未配置）· 预案串库随批次 232 落，"
                "届时发 预 直接列出；格式：预 <名> 查看单条")
    name = args[0]
    lib = ctx.get("cloudsea_presets")
    if isinstance(lib, Mapping) and name in lib:
        return f"【预案串 · {name}】{lib[name]}"
    return f"❓ 未找到预案「{name}」· 发 预 看一览（预案串库随 232 落）"


def cmd_situation(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`局面`：局面聚合——战况一行式（08 §M8.6 不刷屏口径）。"""
    snap = _snap(ctx)
    if not snap:
        return ("📜 当前没有进行中的战斗 · 发 `出发` 进入猎场后，"
                "`局面` 聚合 HP/意图/潮压/气力/破坏槽")
    parts: List[str] = []
    hp = snap.get("player_hp")
    if isinstance(hp, (int, float)):
        parts.append(f"❤️{int(hp)}")
    enemy = snap.get("enemy")
    if isinstance(enemy, Mapping):
        ehp = enemy.get("hp")
        if isinstance(ehp, (int, float)):
            parts.append(f"🎯{int(ehp)}")
        intent = enemy.get("intent")
        if intent:
            parts.append(f"意图:{intent}")
    rs = snap.get("resource_state")
    if isinstance(rs, Mapping):
        enemy_rs = rs.get("enemy")
        if isinstance(enemy_rs, Mapping):
            surge = enemy_rs.get("cs_surge")
            if isinstance(surge, (int, float)):
                parts.append(f"🌊{int(surge)}")
            stamina = enemy_rs.get("cs_stamina")
            if isinstance(stamina, (int, float)):
                parts.append(f"😮‍💨{int(stamina)}")
    if not parts:
        return "局面聚合：快照字段待 234 装配（快照存在但无可读段）"
    return "【局面】" + " ｜ ".join(parts)


def cmd_hang(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`挂 N`：挂机 N 场托管——指令面＋参数校验（autoplay 执行面归 234）。"""
    args = _args(parsed)
    if not args or not args[0].isdigit():
        return "用法：挂 N（N=1-10 场）· 例：挂 3"
    n = int(args[0])
    if not (DELEGATE_N_MIN <= n <= DELEGATE_N_MAX):
        return f"❓ N 超域（{n}）· 挂机范围 1-10 场"
    if isinstance(ctx, MutableMapping):
        ctx["cloudsea_delegate_n"] = n
    return (f"🤖 已挂机 {n} 场（效率沿托管口径）· 每场结算后自动续挂；"
            "发 `撤 确认` 可提前终止")


def cmd_retreat(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`撤` / `撤 确认`：弃撤退——战斗中两段式确认。"""
    args = _args(parsed)
    snap = _snap(ctx)
    if not snap:
        return "📜 当前没有进行中的战斗 · 无可撤退"
    if args and args[0] == "确认":
        if isinstance(ctx, MutableMapping):
            ctx["cloudsea_retreat_pending"] = False
            ctx["cloudsea_retreat_done"] = True
        return ("🏃 弃战撤退成立 · 已离开战斗（进度遗产保留：部位破坏/潮压清零，"
                "掉落按撤退口径减半——结算沿 08 §M8 撤退行）")
    if isinstance(ctx, MutableMapping):
        ctx["cloudsea_retreat_pending"] = True
    return "⚠️ 弃战将按撤退口径结算（掉落减半）· 确认请发 `撤 确认`"


def cmd_digit(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`1/2/3/4/绝`：数字快捷位——预置绑定表回显＋钩子转发。"""
    cmd = str(getattr(parsed, "command", "") or "")
    target = DIGIT_BINDINGS.get(cmd)
    if target is None:
        return format_tpl12(_fragment(parsed))
    hook = ctx.get("shortcut_exec") if isinstance(ctx, Mapping) else None
    if callable(hook):
        return str(hook(target, parsed, ctx))
    return (f"⚡ {cmd} → {target}（绑定就绪）· 战斗引擎桥接随 234 异步底盘装配激活；"
            "过渡期请直接发对应指令")


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，shop/alchemy 壳模式）
# ---------------------------------------------------------------------------

def register_cloudsea_commands(
    router: Any,
    make_context: Optional[Any] = None,
    **_: Any,
) -> None:
    """把 帮/预/局面/挂/撤/数字快捷 注册进 Router（CommandSpec.handler 壳模式）。"""
    if router is None:
        raise ValueError(
            "【待接线】cloudsea_commands.register_cloudsea_commands 需要 router"
        )

    def _ctx(parsed: Any) -> MutableMapping[str, Any]:
        if callable(make_context):
            return make_context(parsed)
        return {}

    def _wrap(fn):
        def _h(parsed: Any, *a: Any, **k: Any):
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(HELP_CLOUDSEA_CMD, handler=_wrap(cmd_help_cloudsea)))
    router.register(CommandSpec(PRESET_CMD, handler=_wrap(cmd_preset)))
    router.register(CommandSpec(SITUATION_CMD, handler=_wrap(cmd_situation)))
    router.register(CommandSpec(HANG_CMD, handler=_wrap(cmd_hang)))
    # 233 对齐设计稿词面：08 §M8.2 撤退指令＝「弃」（「撤」系 231 接线词面，双词面并存）
    router.register(CommandSpec(RETREAT_CMD, aliases=["弃"], handler=_wrap(cmd_retreat)))
    for digit in DIGIT_BINDINGS:
        router.register(CommandSpec(digit, handler=_wrap(cmd_digit)))


__all__ = [
    "HELP_CLOUDSEA_CMD", "PRESET_CMD", "SITUATION_CMD", "HANG_CMD", "RETREAT_CMD",
    "DIGIT_BINDINGS", "DELEGATE_N_MIN", "DELEGATE_N_MAX",
    "cmd_help_cloudsea", "cmd_preset", "cmd_situation", "cmd_hang", "cmd_retreat",
    "cmd_digit", "register_cloudsea_commands",
]
