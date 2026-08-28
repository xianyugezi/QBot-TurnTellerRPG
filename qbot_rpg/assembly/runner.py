"""A-03 processing 驱动与发送出口（M7 装配层 runner · 指令处理完整链路）。

依据（权威契约 = docs/细化/细化_M7_装配层契约.md 三、A-03 RA-08~RA-10 + ADR-08）：
  - RA-08 processing 驱动：完整链路
      ① route_and_expand（router 管线：快捷→别名→白名单→忽略；对话会话路由
         dialog_active）→ 路由决策 → ParsedCommand（单次路由决策，3c §5.3）
      ② make_context(event, deps)（async，A-01 工厂）→ ctx（读快照）
      ③ handler = 指令组 handler 闭包（捕获 ParsedCommand + ctx，适配 processing
         `handler(tx) -> {ok, message}` 契约；业务写由指令壳经注入 make_context
         在事务内完成，幂等键同事务落库）
      ④ process_message(repo, queue, *, message_id, group_id, player_qid, command,
         handler, sender)（qbot_rpg/commands/processing.py L252 真实签名，async）——
         幂等键三元组 + per-player 队列 + 同事务
      ⑤ sender 闭包：apply_message_prefix（M5 前缀注入）→ Sender.send（CQ 转义 /
         4000 分片 / 重试）
  - RA-10 / ADR-08 收口：
      · 权限校验：process_message 前按 RouteResult.spec.permission 检查
        （deps.permission_store 提供 is_gm 判定）；GM 指令走 GmResult 分发
        （静默 / 消息 / 审计，本装配层接线）
      · PerPlayerQueue 超时：消费者挂起 wait_for 超时 → 丢弃等待（背景消费者继续，
        幂等键兜底；processing 无此能力，本模块包一层）
      · cleanup_idem_keys 调度：schedule_cleanup(repo, interval) 懒清理，零 apscheduler
      · 错误兜底：未预期异常 → TPL-12（sender.format_tpl12）+ 日志
        （data.logging_utils）+ 事务回滚（processing 内 tx() ROLLBACK，IDEM-6）

设计纪律（RA-01 / RA-04 / ADR-08）：
  - 纯 asyncio、零 NoneBot import（G0 门禁）；每函数带 docstring；确定性
    （无随机、无时钟依赖；RNG/now 由 make_context 注入源提供）。
  - 本模块为装配层最顶驱动：只组装（读）不写业务；业务写在指令壳 handler 内
    （同事务 write_idem_key 由 processing 承担，IDEM-2/4）。
  - 事件契约：event = {group_id, user_id|qq_id, message, channel, message_id, ...}。
    message_id 为幂等键要素（IDEM-2），由桥接层注入；缺失 → ValueError（被顶层
    兜底转 TPL-12 + 日志）。
  - deps 契约（AssemblyDeps 之外、本模块读取的扩展字段，均 getattr 缺省兜底）：
      router          Router 实例（router_setup.build_router 产物，bootstrap 注入）——必填
      queue           PerPlayerQueue（processing）——必填
      permission_store GM 权限存储（is_gm(qid)/user_of(qid)，缺省 None=非 GM）
      audit_store     GM 审计存储（record_audit 追加写，缺省 None）
      audit_hmac_key  审计 HMAC 密钥（可选）
      sender          Sender 传输层（缺省 Sender() 收集 delivered）
      queue_timeout   per-player 队列处理超时秒数（缺省 None=不设超时）
  - 会话路由（ROUTE_SESSION）：会话子词 → 归 A-04 桥接层状态机接线；本 runner
    不消费，返回空串（不误当成指令处理，2b2 R1）。
  - 指令别名隐藏（ROUTE_HIDDEN，A04）：原指令被隐藏 → 返回「没有这个指令，试试
    『别名』？」提示，不执行。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.assembly.context import make_context
from qbot_rpg.commands.gm_commands import (
    ROLE_ADMIN,
    ROLE_MANAGER,
    GmResult,
    role_of,
)
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.commands.prefix_wiring import CHANNEL_GROUP, apply_message_prefix
from qbot_rpg.commands.processing import PerPlayerQueue, process_message
from qbot_rpg.commands.router import (
    PERM_GM,
    PERM_OWNER,
    ROUTE_HIDDEN,
    ROUTE_SESSION,
    Router,
    RouteResult,
    RoutingContext,
    route_and_expand,
)
from qbot_rpg.commands.sender import Sender, format_tpl12
from qbot_rpg.data.logging_utils import get_logger
from qbot_rpg.data.player import Player, PlayerAttributes

__all__ = [
    "DEFAULT_QUEUE_TIMEOUT",
    "TIMEOUT_MESSAGE",
    "run_command",
    "schedule_cleanup",
]

# 日志（data.logging_utils 统一命名空间；规则 ⑪ 强制日志）
logger = get_logger("assembly.runner")

# per-player 队列处理超时（秒）：None = 不设超时（生产默认，等待队列消费者完成）。
# 经 deps.queue_timeout 注入；超时 → 丢弃本等待（背景消费者继续，幂等键兜底，ADR-08）。
DEFAULT_QUEUE_TIMEOUT: Optional[float] = None

# 队列超时兜底文案（POOL-4 人话；幂等键由消费者侧落库，重发幂等返回兜底）。
TIMEOUT_MESSAGE: str = "指令处理超时，请稍后重试（若已处理将提示重复发送）"


# =============================================================================
# 路由上下文（RA-08 ①）
# =============================================================================
async def _load_player_for_routing(deps: Any, qid: str) -> Any:
    """读档取路由所需玩家快照（shortcuts / dialog_active；async，60s 缓存）。

    入参 deps: AssemblyDeps；qid: 玩家 QQ 号。出参 Player 或 None（读档失败/
    未注册/仓库不可用 → None，不抛异常——路由上下文按缺省兜底）。
    核心逻辑: repo.load_player(qid)（兼容 get_player）；任何异常 → None。
    """
    repo = getattr(deps, "repo", None)
    loader: Any = getattr(repo, "load_player", None)
    if not callable(loader):
        loader = getattr(repo, "get_player", None)
    if not qid or not callable(loader):
        return None
    try:
        return await loader(qid)
    except Exception:
        return None


def _battle_active(deps: Any, qid: str) -> bool:
    """战斗会话激活判定（RoutingContext.battle_active；裁决①：战斗中裸数字=快捷）。

    入参 deps: AssemblyDeps；qid: str。出参 bool。核心逻辑: session_mgr.get_active(qid)
    非 None → True；缺失/异常 → False（不抛异常）。
    """
    mgr = getattr(deps, "session_mgr", None)
    if mgr is None:
        return False
    fn = getattr(mgr, "get_active", None)
    if not callable(fn):
        return False
    try:
        return fn(qid) is not None
    except Exception:
        return False


def _routing_context(deps: Any, router: Router, event: Mapping, player: Any) -> RoutingContext:
    """构造路由上下文（RA-08 ①：registry/shortcuts/aliases/dialog_active/battle_active）。

    入参 deps: AssemblyDeps；router: Router（registry 源）；event: 事件映射；player:
    路由玩家快照（shortcuts/dialog_active 读取源）。出参 RoutingContext。
    核心逻辑: 玩家 persistent_state 装载 shortcuts/dialog_active（缺省空/False）；
    别名取 settings.command_aliases；前缀模式取 settings.command_mode/require_at/
    at_text（缺省 global_shortcut/False/@机器人）。全部缺省兜底，不抛异常。
    """
    settings = getattr(deps, "settings", None)
    settings = settings if isinstance(settings, Mapping) else {}
    ps: Mapping = {}
    if player is not None:
        p = getattr(player, "persistent_state", None)
        if isinstance(p, Mapping):
            ps = p
    qid = str(event.get("qq_id") or event.get("user_id") or "")
    return RoutingContext({
        "registry": router,
        "shortcuts": ps.get("shortcuts") or {},
        "aliases": settings.get("command_aliases"),
        "dialog_active": bool(ps.get("dialog_active", False)),
        "battle_active": _battle_active(deps, qid),
        "command_mode": settings.get("command_mode") or "global_shortcut",
        "require_at": bool(settings.get("require_at", False)),
        "at_text": settings.get("at_text") or "@机器人",
    })


# =============================================================================
# RouteResult → ParsedCommand（RA-08 ①；单次路由决策）
# =============================================================================
def _parsed_from_route(route: RouteResult, raw: str) -> ParsedCommand:
    """RouteResult → ParsedCommand（指令壳消费形态；单次路由决策，不再二次路由）。

    入参 route: RouteResult（route_and_expand 产物）；raw: 原始消息。出参 ParsedCommand。
    核心逻辑: 由 route 字段翻译——command/mode/args_text(空白分列)/display_name/
    compact/prefix_stripped/expand_count/session_route 对齐 ParsedCommand 契约
    （3c §3.2 P01-P18；args 位置参数 = args_text 空白分列，指令壳消费的 token 形态）。
    """
    text = route.text or raw
    args_text = route.args_text or ""
    args = [a for a in str(args_text).split()] if args_text else []
    return ParsedCommand(
        raw=route.raw or raw,
        tokens=list(text.split()) or [text],
        command=route.command,
        args=args,
        mode=route.mode,
        session_candidate=bool(route.session_route),
        session_route=bool(route.session_route),
        expand_count=route.expand_count,
        prefix_stripped=route.prefix_stripped,
        compact=route.compact,
        display_name=route.display_name,
    )


def _spec_of(route: RouteResult, router: Router) -> Optional[Any]:
    """RouteResult → 命中指令的 CommandSpec（别名/快捷展开后经 router 反查）。

    入参 route: RouteResult；router: Router。出参 CommandSpec 或 None。
    核心逻辑: route.spec 优先（白名单直中已带）；否则按 route.command 反查
    router.get（别名/快捷展开场景 spec 未置，command=原指令名）。
    """
    if route.spec is not None:
        return route.spec
    if route.command:
        getter = getattr(router, "get", None)
        if callable(getter):
            return getter(route.command)
    return None


# =============================================================================
# 权限校验（RA-10 / ADR-08：GM 指令前门控）
# =============================================================================
def _requires_gm(spec: Any) -> bool:
    """指令是否需要 GM 权限（spec.is_gm 标记 / permission ∈ {gm, owner}）。

    入参 spec: CommandSpec。出参 bool。核心逻辑: E02 执行层二次检查位 +
    RA-10「按 spec.permission 检查」——GM/机主 指令均须 GM 身份。
    """
    return bool(
        getattr(spec, "is_gm", False)
        or getattr(spec, "permission", None) in (PERM_GM, PERM_OWNER)
    )


def _permission_store_is_gm(deps: Any, qid: str) -> bool:
    """GM 身份判定（deps.permission_store 提供；缺省 False=非 GM）。

    入参 deps: AssemblyDeps；qid: str。出参 bool。核心逻辑: 优先 store.is_gm(qid)
    回调；其次 store.user_of(qid) → GmUser.role 归一 ∈ {admin, manager}；任何
    缺失/异常 → False（安全失败，最低权限，5b §1.1 静默语义）。
    """
    store = getattr(deps, "permission_store", None)
    if store is None:
        return False
    is_gm_fn = getattr(store, "is_gm", None)
    if callable(is_gm_fn):
        try:
            return bool(is_gm_fn(qid))
        except Exception:
            return False
    user_of = getattr(store, "user_of", None)
    if callable(user_of):
        try:
            u = user_of(qid)
            if u is None:
                return False
            return role_of(getattr(u, "role", "")) in (ROLE_ADMIN, ROLE_MANAGER)
        except Exception:
            return False
    return False


# =============================================================================
# handler 闭包（RA-08 ③：适配 processing 契约 handler(tx) -> {ok, message}）
# =============================================================================
def _accepts_ctx(fn: Any) -> bool:
    """handler 是否接受 ctx 关键字（*args/**kwargs 或显式 ctx 形参）。

    入参 fn: 可调用（spec.handler）。出参 bool。核心逻辑: inspect.signature 判定
    是否含 VAR_KEYWORD（**k）或名为 ctx 的形参——兼容 `(parsed, *a, **k)` 指令壳
    handler 与纯 `(parsed)` lambda 两类形态（前者吃 ctx=ctx 注入，后者不注入，
    避免 TypeError）。
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD or p.name == "ctx"
        for p in sig.parameters.values()
    )


async def _invoke_handler(
    fn: Any,
    parsed: ParsedCommand,
    ctx: Optional[Mapping[str, Any]] = None,
) -> Any:
    """调用指令壳 handler（同步/异步皆可；None → 未注册失败结果）。

    入参 fn: 可调用（spec.handler）；parsed: ParsedCommand；ctx: 玩家上下文
    （handler 接受 ctx 时以 ctx=ctx 注入，供 GM 审计/闭包消费；不接受则不传）。
    出参 handler 原始返回（str/dict/GmResult/None 等）。核心逻辑:
    fn(parsed[, ctx=ctx]) + inspect.isawaitable 兼容异步 handler；fn 为 None →
    {ok: False} 失败结果（防装配缺口）。
    """
    if fn is None:
        return {"ok": False, "message": "指令处理器未注册"}
    if ctx is not None and _accepts_ctx(fn):
        out = fn(parsed, ctx=ctx)
    else:
        out = fn(parsed)
    if inspect.isawaitable(out):
        out = await out
    return out


def _normalize_plain(out: Any) -> Dict[str, Any]:
    """普通指令 handler 返回归一 → {ok, message, ...}（processing 契约）。

    入参 out: str/dict/None/其它。出参 Dict[str, Any]（至少含 ok/message）。
    核心逻辑: Mapping → 原样补 message/ok；str → {ok: True, message}；None →
    空消息成功；其它类型 → 失败人话（不静默吞、不裸崩）。
    """
    if isinstance(out, Mapping):
        d = dict(out)
        if "message" not in d:
            d["message"] = ""
        d.setdefault("ok", bool(d.get("message")))
        return d
    if out is None:
        return {"ok": True, "message": ""}
    if isinstance(out, str):
        return {"ok": True, "message": out}
    return {"ok": False, "message": f"指令处理器返回异常类型：{type(out).__name__}"}


def _dispatch_gm_result(result: GmResult, ctx: MutableMapping[str, Any]) -> Dict[str, Any]:
    """GmResult 分发（RA-10 / ADR-08：静默 / 消息 / 审计，归装配层接线）。

    入参 result: GmResult；ctx: 玩家上下文（已注入 permission_store/audit_store）。
    出参 processing 结果 dict。核心逻辑:
      - silent=True        → 零出站零审计（{ok: False, send: False}，防探测，5b §0）；
      - ok=True 且无消息   → 静默执行成功不回显（send=False，工程补白 2）；
      - 其余              → 出站（send=True，message 为查询正文 / TPL-12 报错）；
      审计：handle_gm_command 已经 record_audit 写入 ctx[\"audit_log\"]/audit_store
      （有权限执行时成败皆写；静默分支不写，5b §4）。
    """
    if result.silent:
        return {"ok": False, "send": False, "message": ""}
    if result.ok and not result.message:
        return {"ok": True, "send": False, "message": ""}
    return {"ok": bool(result.ok), "send": True, "message": result.message or ""}


def _player_from_dict(d: Mapping[str, Any], qid: str) -> Player:
    """业务写落档转换（A-03 REG-06 ③）：注册建号 dict → Player dataclass。

    入参 d: build_initial_player 产出的可变 dict（字段对齐 Player 语义）；
    qid: 玩家数据键（QQ 号）。出参 Player（tx.upsert_player 消费，data dataclass 禁裸 dict）。
    核心逻辑: 字段映射 + 缺省兜底（inventory/equipment/attributes 等按 Player 默认）。
    """
    attrs = d.get("attributes")
    attributes = attrs if isinstance(attrs, PlayerAttributes) else PlayerAttributes()
    return Player(
        qid=qid,
        name=str(d.get("name") or ""),
        job_id=str(d.get("job_id") or "novice"),
        level=int(d.get("level") or 1),
        exp=int(d.get("exp") or 0),
        hp=int(d.get("hp") or 1),
        mp=int(d.get("mp") or 1),
        currencies=dict(d.get("currencies") or {}),
        inventory=tuple(d.get("inventory") or ()),
        equipment=dict(d.get("equipment") or {}),
        attributes=attributes,
        achievement_state=tuple(d.get("achievement_state") or ()),
        title_state=dict(d.get("title_state") or {}),
        persistent_state=dict(d.get("persistent_state") or {}),
        longline_counters=dict(d.get("longline_counters") or {}),
        reputation_state=dict(d.get("reputation_state") or {}),
        codex_state=dict(d.get("codex_state") or {}),
        schema_version=int(d.get("schema_version") or 4),
    )


def _make_handler(spec: Any, parsed: ParsedCommand, ctx: MutableMapping[str, Any]):
    """构造 processing Handler 闭包（捕获 ParsedCommand + ctx；事务内由消费者调用）。

    入参 spec: CommandSpec；parsed: ParsedCommand；ctx: dict。出参 handler 闭包
    `handler(tx) -> Dict[str, Any]`。核心逻辑:
      - GM 指令（spec.is_gm）→ 调指令壳 handler（返回 GmResult）→ _dispatch_gm_result
        分发（静默/消息/审计）；
      - 普通指令 → 指令壳 handler 返回 str/dict → _normalize_plain 归一；
      - 业务写（读玩家/校验/扣减/tx.upsert_player）由指令壳 handler 内部完成
        （经注入 make_context 在事务内读写；幂等键由 processing 同事务落库 IDEM-4）。
    """
    if getattr(spec, "is_gm", False):

        async def _gm_handler(tx: Any) -> Dict[str, Any]:  # noqa: ARG001 —— tx 由 processing 注入
            out = await _invoke_handler(getattr(spec, "handler", None), parsed, ctx=ctx)
            if isinstance(out, GmResult):
                return _dispatch_gm_result(out, ctx)
            return _normalize_plain(out)

        return _gm_handler

    async def _plain_handler(tx: Any) -> Dict[str, Any]:  # noqa: ARG001 —— tx 由 processing 注入
        out = await _invoke_handler(getattr(spec, "handler", None), parsed, ctx=ctx)
        # 注销删档分支（2026-08-28 用户拍板 /注销）：指令壳成功时置
        # ctx["unregister_player"]=True + ctx["player"]=None，此处同事务删档。
        # 必须在 upsert 之前（否则删档后被重新写入）。未删到（并发竞态/行已无）
        # → 重复注销模板（「你没有可注销的角色」）。
        if ctx.get("unregister_player"):
            qid = str(ctx.get("qq_id") or ctx.get("user_id") or "")
            if qid:
                deleted = await tx.delete_player(qid)
                out = _normalize_plain(out)
                if not deleted:
                    out = {**out, "message": "❌ 你没有可注销的角色"}
            return out
        # 业务写落档（装配层 REG-06 ③ / A-03 接线）：ctx["player"] 变更 → 同事务 upsert。
        # 已注册玩家每次指令全量写回（RW-3 单事务 upsert，幂等安全）；新注册 dict → 转换。
        p = ctx.get("player")
        if isinstance(p, Player):
            await tx.upsert_player(p)
        elif isinstance(p, dict):
            qid = str(ctx.get("qq_id") or ctx.get("user_id") or "")
            if qid:
                await tx.upsert_player(_player_from_dict(p, qid))
        return _normalize_plain(out)

    return _plain_handler


# =============================================================================
# sender 闭包（RA-08 ⑤ / RA-09：前缀注入 → Sender.send）
# =============================================================================
def _make_sender(deps: Any, ctx: Mapping[str, Any]):
    """构造发送出口闭包（apply_message_prefix → Sender.send；记录已发送文本）。

    入参 deps: AssemblyDeps（sender 传输层，缺省 Sender() 收集 delivered）；
    ctx: 玩家上下文（level/name/title/channel/settings/group_name/to 读取源）。
    出参 (sender, state)：sender 为 processing Sender 契约闭包
    `async sender(result) -> None`；state[\"sent\"] 记录最近一次发送的完整文本
    （含前缀，供 run_command 返回）。
    核心逻辑: 仅注册玩家注入前缀（未注册无 level/name，前缀无意义，直发正文）；
    前缀渲染（M5 7 字段）→ prefixed.text 非空 → sender.send（CQ 转义/分片/重试）。
    """
    sender_obj = getattr(deps, "sender", None) or Sender()
    state: Dict[str, Any] = {"sent": None}
    channel = str(ctx.get("channel") or CHANNEL_GROUP)

    async def sender(result: Dict[str, Any]) -> None:
        """发送出口闭包：COMMIT 后由 processing 消费者调用（失败不阻塞队列，POOL-6）。"""
        text = result.get("message")
        if not text:
            return
        if ctx.get("registered"):
            prefixed = apply_message_prefix(
                str(text),
                level=ctx.get("level") or 0,
                name=str(ctx.get("name") or "玩家"),
                title=ctx.get("title"),
                channel=channel,
                is_system=False,
                settings=ctx.get("settings"),
                extra={"群名": ctx.get("group_name")},
            )
            out_text = prefixed.text
        else:
            out_text = str(text)
        if out_text:
            sender_obj.send(out_text, to=ctx.get("to"))
            state["sent"] = out_text

    return sender, state


# =============================================================================
# process_message 驱动（RA-08 ④ + RA-10 超时包一层）
# =============================================================================
async def _drive_process(
    repo: Any,
    queue: PerPlayerQueue,
    *,
    message_id: str,
    group_id: Any,
    player_qid: str,
    command: str,
    handler: Any,
    sender: Any,
    timeout: Optional[float],
) -> Dict[str, Any]:
    """process_message 驱动（幂等键三元组 + per-player 队列 + 同事务）。

    入参: 见 process_message 真实签名（qbot_rpg/commands/processing.py L252）——
    repo/queue/message_id/group_id/player_qid/command/handler/sender；timeout:
    队列处理超时秒数（None=不设）。出参 {ok, message, ...} dict。
    核心逻辑: 超时经 asyncio.wait_for 包裹——消费者挂起超时 → 丢弃本等待（返回
    TIMEOUT_MESSAGE，不静默吞、不阻塞后续同玩家指令，POOL-4）；背景消费者继续
    处理并落幂等键（同 message_id 重发幂等返回兜底，ADR-08）。processing 无此
    能力，本层包一层。
    """
    if timeout:
        try:
            return await asyncio.wait_for(
                process_message(
                    repo, queue,
                    message_id=message_id, group_id=group_id, player_qid=player_qid,
                    command=command, handler=handler, sender=sender,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "per-player 队列处理超时（丢弃等待，幂等键兜底）: qid=%s command=%s",
                player_qid, command,
            )
            return {"ok": False, "send": False, "message": TIMEOUT_MESSAGE}
    return await process_message(
        repo, queue,
        message_id=message_id, group_id=group_id, player_qid=player_qid,
        command=command, handler=handler, sender=sender,
    )


# =============================================================================
# 主入口
# =============================================================================
async def _run_command_inner(event: Mapping, deps: Any, raw: str) -> str:
    """run_command 核心链路（RA-08 ①~⑤；未预期异常交由外层 TPL-12 兜底）。"""
    qid = str(event.get("qq_id") or event.get("user_id") or "")
    if not qid:
        raise ValueError("run_command 需要 event 的 qq_id / user_id（幂等键 player_qid 要素）")
    message_id = str(event.get("message_id") or "")
    if not message_id:
        raise ValueError("run_command 需要 event['message_id']（幂等键要素，由桥接层注入）")
    if not raw:
        return ""

    router = getattr(deps, "router", None)
    if router is None:
        raise RuntimeError(
            "run_command 需要 deps.router（router_setup.build_router 产物）")
    repo = getattr(deps, "repo", None)
    queue = getattr(deps, "queue", None)
    if queue is None:
        raise RuntimeError("run_command 需要 deps.queue（PerPlayerQueue 实例）")

    # -- ① 路由（快捷→别名→白名单→忽略；对话会话路由 dialog_active）------------
    player = await _load_player_for_routing(deps, qid)
    route = route_and_expand(raw, _routing_context(deps, router, event, player))

    if route.ignored:
        return ""
    if route.kind == ROUTE_SESSION:
        # 会话子词 → 送状态机（A-04 桥接层接线；本 runner 不消费，不误当指令处理）
        return ""
    if route.kind == ROUTE_HIDDEN:
        # 原指令被隐藏（A04）：「没有这个指令，试试『别名』？」不执行
        return f"没有这个指令，试试『{route.display_name}』？"
    if not route.command:
        return ""

    spec = _spec_of(route, router)
    if spec is None:
        return ""

    # -- ② make_context（A-01 工厂，async）→ ctx（读快照） ---------------------
    ctx = await make_context(event, deps)

    # GM 上下文注入（permission_store/audit_store，gm_commands handle_gm_command 消费）
    if getattr(spec, "is_gm", False):
        ctx["permission_store"] = getattr(deps, "permission_store", None)
        ctx["audit_store"] = getattr(deps, "audit_store", None)
        ctx["audit_hmac_key"] = getattr(deps, "audit_hmac_key", None)

    # -- RA-10 权限校验（process_message 前按 spec.permission 检查；GM 静默）-----
    if _requires_gm(spec) and not _permission_store_is_gm(deps, qid):
        logger.info("GM 指令权限拦截（零出站零审计）: qid=%s command=%s", qid, spec.name)
        return ""

    # -- ③ ParsedCommand + handler 闭包（捕获 ctx + 事务内业务写） ---------------
    parsed = _parsed_from_route(route, raw)
    handler = _make_handler(spec, parsed, ctx)

    # -- ⑤ sender 闭包（前缀注入 → Sender.send） ---------------------------------
    sender, send_state = _make_sender(deps, ctx)

    # -- ④ process_message（幂等键三元组 + per-player 队列 + 同事务 + 超时包层）---
    timeout = getattr(deps, "queue_timeout", None)
    outcome = await _drive_process(
        repo, queue,
        message_id=message_id, group_id=event.get("group_id"), player_qid=qid,
        command=spec.name, handler=handler, sender=sender, timeout=timeout,
    )

    # -- 结果 → 回复串（已发送文本优先；幂等重放/静默回退 outcome.message）--------
    sent = send_state.get("sent")
    if sent:
        return str(sent)
    return str(outcome.get("message") or "")


async def run_command(event: Mapping, deps: Any) -> str:
    """A-03 完整指令处理链路（RA-08 ①~⑤ + RA-10 收口），返回回复串。

    入参:
      - event: Mapping——{message, message_id, group_id, user_id|qq_id, channel,
        group_name/to/per_channel}（message_id 为幂等键要素，桥接层注入）。
      - deps: AssemblyDeps——repo/game_world/registry/settings/queue + router
        （router_setup 产物）/permission_store/audit_store/sender/queue_timeout。
    出参: str——最终回复正文（已发送文本含前缀；未命中指令/忽略/会话子词/GM 静默
      → 空串；幂等重放 → 「该指令已处理，请勿重复发送」）。

    核心逻辑:
      ① route_and_expand（快捷→别名→白名单→忽略；dialog_active 会话路由）；
      ② make_context(event, deps)（async）→ ctx；
      ③ handler = 指令组 handler 闭包（捕获 ctx + 事务内业务写，适配 processing）；
      ④ process_message（幂等键三元组 + per-player 队列 + 同事务，IDEM-1~6）；
      ⑤ sender 闭包：apply_message_prefix → Sender.send（CQ 转义/分片/重试）。
      权限/超时/清理/错误兜底按 RA-10 / ADR-08 收口（见模块 docstring）。

    错误兜底: 未预期异常（路由/make_context/process_message 外层）→ 记日志 +
      TPL-12 统一报错（sender.format_tpl12，3d §5.1）；事务回滚由 processing 内
      tx() ROLLBACK 承担（IDEM-6，无孤儿键）。
    """
    raw = str(event.get("message") or "")
    try:
        return await _run_command_inner(event, deps, raw)
    except Exception as exc:  # noqa: BLE001 —— 顶层兜底必须吞（规则 ⑫⑬：记日志返兜底）
        logger.exception("run_command 未预期异常（TPL-12 兜底）: %r", exc)
        return format_tpl12(raw)


# =============================================================================
# 幂等键清理调度（RA-10 / D2 IDEM-7：7 天窗口懒清理，零 apscheduler）
# =============================================================================
async def _cleanup_loop(repo: Any, interval: float) -> None:
    """周期清理循环：先执行一次，再按 interval 休眠循环（懒清理）。

    入参 repo: Repository（cleanup_idem_keys(retention_days=7.0)）；interval: 秒。
    核心逻辑: while True——先跑一次清理（任何异常记日志不中断循环），再 sleep；
    由 schedule_cleanup 创建后台任务，随进程生命周期（WIR-04 schedule_polling 同款）。
    """
    while True:
        try:
            await repo.cleanup_idem_keys()
        except Exception:  # noqa: BLE001 —— 清理失败不阻断业务（规则 ⑬）
            logger.exception("cleanup_idem_keys 异常（不中断循环）")
        await asyncio.sleep(interval)


def schedule_cleanup(repo: Any, interval: float) -> asyncio.Task:
    """幂等键 7 天滚动清理调度（RA-10 / D2 IDEM-7；零 apscheduler，懒清理）。

    入参 repo: Repository；interval: 清理周期秒数。出参 asyncio.Task（后台清理任务）。
    核心逻辑: 当前事件循环 create_task(_cleanup_loop)；启动即清理一次，之后按
    interval 周期滚动删除过期幂等键（保留 7 天窗口，IDEM-5/D-03）。调用方（bootstrap/
    装配冒烟）持有 task 并在停机时 cancel。
    """
    return asyncio.get_running_loop().create_task(_cleanup_loop(repo, interval))
