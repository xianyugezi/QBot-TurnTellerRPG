"""PVP 指令壳（qbot_rpg/commands/pvp_commands.py · M11 批3 路3B）。

指令（对齐细化_4e PVP决斗契约 CMD-05/06，定稿 §3.19 L353-354 / L1287-1288）：
  /锁定玩家 <QQ号>     指定目标（显示对方状态：等级/职业/血量/装备摘要）
  /攻击玩家 <技能序号> 对锁定玩家攻击（技能序号解析同 /攻击，不加 `*`）

PVP 语义（用户 2026-08-28 + 2026-09-01 拍板）：
  - 决斗四指令（/决斗 + 接受/拒绝/信息）已删除不复活，只做 /锁定玩家 /攻击玩家；
  - PVP = 玩家互斗非镜像：/锁定玩家 锁定真实玩家档案；/攻击玩家 直接攻击锁定玩家
    （目标 = 活人玩家档案，非野怪镜像）；
  - 偷袭：目标正在与怪物战斗时仍可锁定并攻击（复用会话互斥/战斗干预机制）。

依据：
  - docs/细化/细化_4e_PVP决斗契约.md（CMD-05/06 + CMD-R02~R05 参数解析 + 错误模板
    4 类；TC-10/TC-12 行动路由）
  - docs/m11_启动包.md §2.3（指令双原语 + 偷袭语义 + 战斗复用）
  - qbot_rpg/commands/forge_commands.py（CommandSpec 注册 + _fragment + _gate 先例）
  - qbot_rpg/commands/achievement_commands.py（register_* 签名 + _wrap 注入先例）
  - qbot_rpg/commands/battle_commands.py（/攻击 技能序号解析：_resolve_skill 口径，
    序号 1 起、不加 `*`——DEFAULT_NO_QUANTITY 语义由 parsers 层承担）
  - qbot_rpg/commands/parsers.py（DEFAULT_WHITELIST / DEFAULT_PREFIX_REQUIRED /
    ERR_* 四类错误模板常量）

【工程补白 · 显式标注】
  F-1  3A 引擎（core/pvp.py）与本路并行开发、可能未落盘：本壳按契约签名
       pvp_lock(ctx, qq) / pvp_attack(ctx, skill_seq) 调用，运行时惰性 import
       探测；引擎缺失 → 明确「未接线」提示（不静默）。收口联调时引擎落盘即通。
  F-2  QQ 号校验：纯数字 9-11 位（群内 QQ 规则，细化_4e CMD-01 L41 同口径）；
       非数字 → 缺参/格式错误模板（CMD-R04）。解析层只做结构校验，
       玩家存在性/在线判定归引擎（壳层不重复实现）。
  F-3  技能序号解析复用 battle_commands._resolve_skill 口径：数字序号 1 起映射
       ctx[\"skills\"] 配置序，名称/id 亦可；不加 `*`（与 /攻击 语义一致）。
  F-4  错误模板 4 类（CMD-R05）：缺参（pvp_err_missing）/ 超参（pvp_err_too_many）/
       未知分隔符（pvp_err_unknown_sep）/ 保留字符（pvp_err_reserved，黄提示不拦截）
       ——对齐 parsers.ERR_* 常量；渲染统一 tpl_of（pvp_tpl 分区，内容包可覆盖）。
  F-5  对方状态展示：引擎返回 target 映射（level/job/hp/max_hp/equipment）→
       pvp_lock_status_* 模板逐行渲染；字段缺省整行降级（对齐 status_commands
       target_line P2-9 口径，防 None 拼接）。装备摘要 = equipment 映射按槽位
       逐件 `槽位：物品`，空 → 「无」。
  F-6  /攻击玩家 结算：引擎返回 result 映射（name/damage/hp/max_hp/ended 等）→
       pvp_attack_ok 行 + 可选 pvp_attack_result_line 伤害行；引擎缺省兜底
       「结算由 PVP 引擎输出」。
  F-7  注册门槛（RUL-08）：ctx[\"registered\"] is False → pvp_registered_gate 拒绝
       （对齐 achievement_commands._gate / battle_commands._gate）。
  F-8  handler 契约：返回 str（回复正文，对齐 status/achievement 壳层）；
       register_pvp_commands(router, *, make_context=None) 签名对齐
       register_achievement_commands；make_context 缺省 → RuntimeError【待接线】。
  F-9  白名单/前缀：parsers.DEFAULT_WHITELIST 已加 锁定玩家/攻击玩家；
       DEFAULT_PREFIX_REQUIRED 不加（可快捷，对齐普通指令）；
       CommandSpec whitelisted=True 注册，无 GM 标记。

铁律：零 NoneBot import；纯函数确定性；渲染输出无 emoji（仅 ✅/❌ + 排版符号）；
模板配置化（tpl_of + pvp_tpl 分区）；错误模板文案唯一源 = pvp_tpl。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）

# 同包兄弟模块：相对导入（G0 架构门禁，与 forge_commands 同口径）

__all__ = [
    # 指令名常量
    "LOCK_CMD",
    "ATTACK_PLAYER_CMD",
    # 参数解析
    "parse_pvp_lock_arg",
    "parse_pvp_attack_arg",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_pvp_lock",
    "cmd_pvp_attack",
    # 装配
    "register_pvp_commands",
]

# ---------------------------------------------------------------------------
# 常量：指令名
# ---------------------------------------------------------------------------

LOCK_CMD: str = "锁定玩家"
ATTACK_PLAYER_CMD: str = "攻击玩家"

# QQ 号规则：纯数字 9-11 位（群内 QQ 规则，细化_4e CMD-01 L41 同口径；CMD-R04）
_RE_QQ = re.compile(r"^[0-9]{9,11}$")


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------


def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 forge_commands._fragment）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """注册门槛（RUL-08，F-7）：未注册玩家 → 统一拒绝文案。"""
    if ctx.get("registered", True) is False:
        return tpl_of(ctx, "pvp_registered_gate", {})
    return None


def _player_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家状态 dict（ctx[\"player\"] 优先；缺省 ctx 自身——测试可把 ctx 直接当 player）。"""
    player = ctx.get("player")
    if isinstance(player, MutableMapping):
        return player
    return ctx


def _qid_of(ctx: Mapping[str, Any]) -> Optional[str]:
    """当前玩家 id（自我锁定判定用；ctx[\"qid\"] → ctx[\"player\"] 内 qid/qq/player_qid）。"""
    qid = ctx.get("qid")
    if qid:
        return str(qid)
    player = ctx.get("player")
    if isinstance(player, Mapping):
        for k in ("qid", "qq", "player_qid"):
            v = player.get(k)
            if v:
                return str(v)
    return None


def _pvp_engine(ctx: Mapping[str, Any]):
    """PVP 引擎（core/pvp.py，3A 并行路）惰性加载；缺失 → None（F-1）。

    引擎模块须暴露 pvp_lock(ctx, qq) -> Mapping / pvp_attack(ctx, skill_id) ->
    Mapping；引擎未落盘时返回 None，壳层给出明确未接线提示。importlib 动态加载
    规避静态分析对未落盘模块的报错（3A 并行路交付后即通）。
    """
    try:
        import importlib  # noqa: PLC0415

        return importlib.import_module("qbot_rpg.core.pvp")
    except Exception:  # noqa: BLE001 —— 引擎缺失 → None（F-1 未接线兜底）
        return None


def _resolve_skill(ctx: Mapping[str, Any], text: str) -> Optional[str]:
    """/攻击玩家 <技能序号> 解析：技能 id/名称/序号 → skill_id（F-3）。

    对齐 battle_commands._resolve_skill 口径：ctx[\"skills\"] 配置序，
    数字序号 1 起映射；名称/id 亦可；不加 `*`（parsers 层已拒绝数量）。
    """
    skills = ctx.get("skills")
    if not isinstance(skills, Mapping):
        return None
    items = list(skills.items())
    for sid, d in items:
        name = d.get("name") if isinstance(d, Mapping) else getattr(d, "name", None)
        if sid == text or str(name) == text:
            return sid
    if text.isdigit():
        idx = int(text)
        if 1 <= idx <= len(items):
            return items[idx - 1][0]
    return None


def _equip_summary(equipment: Any) -> str:
    """装备摘要：equipment 映射按槽位逐件 `槽位：物品`；空 → 「无」（F-5）。"""
    if not isinstance(equipment, Mapping):
        return "无"
    parts = []
    for slot, item in equipment.items():
        name = item.get("name") if isinstance(item, Mapping) else str(item)
        parts.append(tpl_of(None, "pvp_lock_equip_summary",
                            {"slot": str(slot), "item": str(name)}))
    return " | ".join(parts) if parts else "无"


# ---------------------------------------------------------------------------
# 参数解析（CMD-R02~R05：空格切参 / ≤1 位置参数 / QQ 纯数字 / 错误模板 4 类）
# ---------------------------------------------------------------------------


def parse_pvp_lock_arg(parsed: Any) -> Optional[str]:
    """/锁定玩家 参数解析：QQ 纯数字 9-11 位；非数字 → None（F-2，CMD-R04）。

    超参/未知分隔符/保留字符由 parsed.error 承载（F-4），调用方先判 error。
    """
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return None
    qq = str(args[0]).strip()
    if not _RE_QQ.fullmatch(qq):
        return None
    return qq


def parse_pvp_attack_arg(parsed: Any) -> Optional[str]:
    """/攻击玩家 参数解析：技能序号（数字/名称/id，F-3）；缺参 → None。

    超参/未知分隔符/保留字符由 parsed.error 承载（F-4），调用方先判 error。
    """
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return None
    return str(args[0]).strip()


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：parsed + ctx → 回复正文）
# ---------------------------------------------------------------------------


def cmd_pvp_lock(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/锁定玩家 <QQ号>：指定目标（显示对方状态：等级/职业/血量/装备摘要）。

    解析错误（parsed.error）→ 错误模板 4 类；未注册 → 门槛拒绝；
    QQ 非法/缺参 → pvp_err_missing；锁定自己 → pvp_lock_self；
    引擎缺失 → pvp_engine_missing；target 不存在 → pvp_lock_not_found。
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if getattr(parsed, "error", None):
        return _err_template(ctx, parsed)
    qq = parse_pvp_lock_arg(parsed)
    if qq is None:
        return tpl_of(ctx, "pvp_err_missing", {})
    if str(_qid_of(ctx) or "") == qq:
        return tpl_of(ctx, "pvp_lock_self", {})
    engine = _pvp_engine(ctx)
    if engine is None:
        return tpl_of(ctx, "pvp_engine_missing", {})
    try:
        result = engine.pvp_lock(ctx, qq)
    except Exception:  # noqa: BLE001 —— 引擎异常 → 明确未接线提示（F-1 容错）
        return tpl_of(ctx, "pvp_engine_unavailable", {})
    if not isinstance(result, Mapping):
        return tpl_of(ctx, "pvp_lock_not_found", {"qq": qq})
    if not result.get("ok"):
        return tpl_of(ctx, "pvp_lock_not_found", {"qq": qq})
    return _render_lock_status(ctx, qq, result)


def _render_lock_status(ctx: MutableMapping[str, Any], qq: str, result: Mapping[str, Any]) -> str:
    """锁定成功 → 对方状态卡（等级/职业/血量/装备摘要；字段缺省整行降级，F-5）。"""
    target = result.get("target")
    if not isinstance(target, Mapping):
        return tpl_of(ctx, "pvp_lock_ok", {"name": str(result.get("name") or qq)})
    lines = [tpl_of(ctx, "pvp_lock_ok", {"name": str(target.get("name") or qq)})]
    level = target.get("level")
    if level is not None:
        lines.append(tpl_of(ctx, "pvp_lock_status_level", {"level": level}))
    job = target.get("job")
    if job is not None:
        lines.append(tpl_of(ctx, "pvp_lock_status_job", {"job": job}))
    hp = target.get("hp")
    max_hp = target.get("max_hp")
    if hp is not None and max_hp is not None:
        lines.append(tpl_of(ctx, "pvp_lock_status_hp", {"hp": hp, "max_hp": max_hp}))
    lines.append(tpl_of(ctx, "pvp_lock_status_equip",
                        {"summary": _equip_summary(target.get("equipment"))}))
    return "\n".join(lines)


def cmd_pvp_attack(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/攻击玩家 <技能序号>：对锁定玩家攻击（战斗结算消息，F-6）。

    解析错误 → 错误模板 4 类；未注册 → 门槛拒绝；缺参 → pvp_err_missing；
    引擎缺失 → pvp_engine_missing；未锁定（引擎 result 无 target 或无 ok）→
    pvp_attack_no_target；技能序号非法 → pvp_attack_no_target（值域问题，
    对齐 /攻击 battle_no_skill 口径，不走 TPL-12）。
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if getattr(parsed, "error", None):
        return _err_template(ctx, parsed)
    seq = parse_pvp_attack_arg(parsed)
    if seq is None:
        return tpl_of(ctx, "pvp_err_missing", {})
    skill_id = _resolve_skill(ctx, seq)
    if skill_id is None:
        return tpl_of(ctx, "pvp_attack_no_target", {})
    engine = _pvp_engine(ctx)
    if engine is None:
        return tpl_of(ctx, "pvp_engine_missing", {})
    try:
        result = engine.pvp_attack(ctx, skill_id)
    except Exception:  # noqa: BLE001 —— 引擎异常 → 明确未接线提示（F-1 容错）
        return tpl_of(ctx, "pvp_engine_unavailable", {})
    if not isinstance(result, Mapping):
        return tpl_of(ctx, "pvp_attack_no_target", {})
    if not result.get("ok"):
        return tpl_of(ctx, "pvp_attack_no_target", {})
    return _render_attack_result(ctx, result)


def _render_attack_result(ctx: MutableMapping[str, Any], result: Mapping[str, Any]) -> str:
    """攻击结算消息：pvp_attack_ok 行 + 可选伤害行（result 字段缺省整行降级，F-6）。"""
    name = str(result.get("name") or "对方")
    damage = result.get("damage")
    hp = result.get("hp")
    max_hp = result.get("max_hp")
    result_text = str(result.get("result") or "")
    lines = [tpl_of(ctx, "pvp_attack_ok", {"name": name, "result": result_text})]
    if damage is not None and hp is not None and max_hp is not None:
        lines.append(tpl_of(ctx, "pvp_attack_result_line",
                            {"name": name, "damage": damage, "hp": hp, "max_hp": max_hp}))
    return "\n".join(lines)


def _err_template(ctx: Mapping[str, Any], parsed: Any) -> str:
    """解析错误 → 错误模板 4 类（F-4，CMD-R05）：缺参/超参/未知分隔符/保留字符。

    保留字符违规 = parsers 黄提示入 hints（不拦截）——壳层按 error 标记渲染
    pvp_err_reserved；其余三类按 ERR_* 常量映射。渲染统一 tpl_of。
    """
    from .parsers import (  # noqa: PLC0415 —— 本地导入防循环（parsers 零依赖本模块）
        ERR_MISSING,
        ERR_RESERVED,
        ERR_TOO_MANY,
        ERR_UNKNOWN_SEP,
    )

    err = str(getattr(parsed, "error", "") or "")
    if err == ERR_MISSING:
        return tpl_of(ctx, "pvp_err_missing", {})
    if err == ERR_TOO_MANY:
        return tpl_of(ctx, "pvp_err_too_many", {})
    if err == ERR_UNKNOWN_SEP:
        return tpl_of(ctx, "pvp_err_unknown_sep", {})
    if err == ERR_RESERVED:
        return tpl_of(ctx, "pvp_err_reserved", {})
    return tpl_of(ctx, "pvp_err_missing", {})


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入）
# ---------------------------------------------------------------------------


def register_pvp_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /锁定玩家 /攻击玩家 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → PVP ctx dict（qid/player/skills/registered/
        templates 等，见模块头 ctx 契约）。None 时 handler 调用抛 RuntimeError
        （【待接线】装配注入，对齐 register_achievement_commands F-8）。
    """
    from qbot_rpg.commands.router import CommandSpec as _Spec  # noqa: PLC0415

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】pvp_commands.register_pvp_commands 需要 make_context"
                "（PVP 上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _wrap(fn: Callable[[Any, MutableMapping[str, Any]], str]) -> Callable[..., str]:
        def handler(parsed: Any, *a: Any, **k: Any) -> str:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return handler

    router.register(_Spec(LOCK_CMD, handler=_wrap(cmd_pvp_lock)))
    router.register(_Spec(ATTACK_PLAYER_CMD, handler=_wrap(cmd_pvp_attack)))
    return router
