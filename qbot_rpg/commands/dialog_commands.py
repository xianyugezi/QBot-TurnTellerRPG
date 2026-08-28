"""M7 N-01 /对话 指令壳（qbot_rpg/commands/dialog_commands.py）。

依据：
  - docs/细化/细化_M7_NPC对话接线.md（N-01 RN-01~RN-04 + 1.1~1.4，权威契约）
  - docs/细化/细化_2b2_对话会话状态机.md（七态 S0-S6 / 十五迁移 T01-T15 / R1-R5 / 中断恢复）
  - docs/细化/细化_2b1_NPC数据与发牌员.md（dealer 子结构 / 发牌员三策略 / 孤寂卡）
  - m4_shared_contract §3.1（NPC/对话 B1-B6）

职责（RN-01~RN-04）：/对话 指令壳——持一个 DialogSession 实例（装配层按玩家注入，
本壳只读 ctx["dialog_session"] 并在 ctx 就地改写），驱动**真实引擎**
qbot_rpg/core/dialog.DialogSession + qbot_rpg/core/npc（dispatch_action / deal /
mark_delivered）。零 NoneBot import；纯函数确定性；统一返回 str 回复。

子形态（RN-01）：/对话 无参（列表）/ /对话 N（序号）/ /对话 名称（名称优先禁空格）。
参数解析**委托** dialog.parse_dialog_command(args, npcs)（真实签名 L235）。

会话生命周期（RN-02）：建会话 parse_dialog_command → session.step(("dialog", parsed), ctx)；
会话子词（ROUTE_SESSION 分支送 mode=session_digit → 本壳 cmd_dialog_session）按 subword
调 session.step((sub, value), ctx)；动作执行 step(("select", N)) → exec 请求 → 壳自行调
npc.dispatch_action → 结果映射 ("exec_done", payload) 回传；中断 step(("interrupt", None))
落快照即回（激活保持）；收尾 step(("exit", None)) 清 dialog_active + 事件计数。

【工程补白 · 显式标注】
  1) _result 归一：引擎 step 返回 {transition/trace/from_state/to_state/output/kind/events/
     mark_heard/shop_refs/action/handoff/ended/session_active/snapshot}（dialog.py L932-954）；
     本壳消费前经 _normalize_result 归一为 {ok, kind, state, lines}（细化 §1.2 口径），
     再按 kind 分支（list/menu/narration/exec/subui/ended/command）渲染。
  2) 动作执行接线（RN-03）：菜单选择 N → step 返回 exec 请求（action=选中的 interaction
     条目）→ 壳自行调 npc.dispatch_action(entry, ctx, rng, npc_id, state) → 结果映射
     ("exec_done", payload) 回传 step；payload 六键 info_key/is_info/subui/label/
     shop_refs/completed（引擎 _exec_done 未给 info_key 时按 _exec_index 推导，L724-726）。
  3) 叙述型动作（intel/tutorial/reply/sub_dialog，output 非空）：step 返回 exec 时壳当场
     完成 npc 侧交付记账（npc_delivered 双轨键 + codex 由 dispatch_action 内部解锁）但
     **不喂 exec_done**——玩家翻段后由引擎 _on_exec 末段自动 _exec_done 收尾 mark_heard
     （T11/T10）。功能型（output 空）：当场 dispatch 并喂 exec_done 回菜单（T10）。
  4) 已听双轨键桥接（RN-03）：① dialog 侧 mark_heard 落 ctx["heard"]（info_key 键，菜单置灰，
     引擎结果 mark_heard 上报）；② npc 侧 npc.mark_delivered(ctx, npc_id, f"intel:{ref_id}")
     落 ctx["npc_delivered"]（动作去重；dispatch_action 内部已写，此处幂等兜底防漏）。
  5) 事件写入（RN-10 双表）：收尾 events 优先走 ctx["bump_event"] hook（装配层统一函数，
     签名 (ctx, key)）；缺省双表直写 event_counts + longline_counters（条件引擎读 event_counts，
     冒险日志累计读 longline_counters）。
  6) 发牌员（RN-03）：type=dealer（dealer 子结构）NPC 经 T05 落地菜单 → 壳调
     npc.deal(npc_id, dealer, ctx, rng, rotate_state, greeting)；rotate_state 由装配层按
     npc 持有（persistent_state["npc_rotate"] → ctx["npc_rotate"]）；greeting 取
     dialogues.greeting 兜底空串。同一会话内仅落地（T05）时发牌一次，回菜单（T10）不重发。
  7) 恢复简报（RN-12）：中断（interrupt）→ 快照落盘（状态不变，激活保持）；下次 /对话
     入口（cmd_dialog）前置 dialog.build_resume_brief(snapshot)。会话子词（数字/继续/选择）
     不重复显示简报——避免持续会话每步噪音（细化 RN-12「下次 /对话 或会话路由纯数字」，
     本路收敛为 /对话 入口显示；【工程补白】）。
  8) 每 NPC 可变 state：ctx["npc_rotate"] = {npc_id: 可变 dict} 既承载发牌员 rotate
     指针（state["index"]）也承载 reply cycle 指针（state["reply_index"]），dispatch_action
     与 deal 共用该按 npc 可变 dict（两键不冲突）。
  9) 无 NPC 地图：引擎返回 empty_map（DIALOG_EMPTY_MAP_HINT），壳不建会话原样渲染。

纯函数约定：零 NoneBot import；无 IO；同参同值确定性；事件/已听/会话快照一律经 ctx
就地改写由装配层提交落盘（与 shop/quest 指令壳同款契约）。
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.core import dialog, npc as npc_mod

__all__ = [
    "DIALOG_CMD",
    "cmd_dialog",
    "cmd_dialog_session",
    "cmd_dialog_interrupt",
    "cmd_dialog_confirm",
    "register_dialog_commands",
    "normalize_dialog_result",
]

DIALOG_CMD = "对话"


# -------------------------------------------------------------------------------------
# 结果归一（细化 §1.2 口径：step → {ok, kind, state, lines}）
# -------------------------------------------------------------------------------------
# 引擎 step kind → 壳分支 kind（list/menu/narration/exec/subui/ended/command/noop）
_MENU_KINDS = frozenset({
    "menu", "back_menu", "more_page", "invalid_option",
    "already_heard", "condition_unmet", "depth_blocked", "menu_noop",
})
_LIST_KINDS = frozenset({
    "entered_list", "relist", "empty_map", "index_fail",
    "name_not_found", "list_noop",
})
_SUBUI_KINDS = frozenset({"subui", "subui_unfinished", "subui_noop"})


def _branch_kind(kind: object) -> str:
    """引擎 step kind → 壳分支 kind（纯函数）。

    分支集：list/menu/narration/exec/subui/ended/command/noop；未知/占位一律收敛
    "noop"（idle_noop/exec_noop/bad_event/npcsel_noop/end_noop/interrupted 等无输出分支）。
    """
    if kind == "command":
        return "command"
    if kind in _MENU_KINDS:
        return "menu"
    if kind in _LIST_KINDS:
        return "list"
    if kind in _SUBUI_KINDS:
        return "subui"
    if kind == "next_page":
        return "narration"
    if kind == "exec":
        return "exec"
    if kind == "ended":
        return "ended"
    return "noop"


def normalize_dialog_result(result: Mapping[str, Any]) -> dict:
    """引擎 step 结果 → 归一形态 {ok, kind, state, lines}（纯函数，供消费与测试断言）。

    kind = 壳分支（list/menu/narration/exec/subui/ended/command/noop）；state = to_state；
    lines = output。非 Mapping → 安全失败形态。
    """
    if not isinstance(result, Mapping):
        return {"ok": False, "kind": "noop", "state": None, "lines": []}
    return {
        "ok": bool(result.get("to_state")) and result.get("kind") not in ("bad_event",),
        "kind": _branch_kind(result.get("kind")),
        "state": result.get("to_state"),
        "lines": list(result.get("output") or []),
    }


# -------------------------------------------------------------------------------------
# ctx 读写小工具
# -------------------------------------------------------------------------------------
def _session(ctx: MutableMapping[str, Any]) -> "dialog.DialogSession":
    """取/建当前玩家会话（ctx["dialog_session"]；装配层按玩家注入，缺省自建 IDLE）。

    注入形态：DialogSession 实例直接用；dict 快照 → from_snapshot 恢复；None/其它 → 新建。
    本壳始终把会话实例写回 ctx["dialog_session"]，由装配层提交快照落盘（RN-11）。
    """
    s = ctx.get("dialog_session")
    if isinstance(s, dialog.DialogSession):
        return s
    if isinstance(s, Mapping):
        try:
            restored = dialog.DialogSession.from_snapshot(s)
            ctx["dialog_session"] = restored
            return restored
        except Exception:
            pass
    s = dialog.DialogSession()
    ctx["dialog_session"] = s
    return s


def _active(session: Any) -> bool:
    """会话是否处于激活区间（S1 LIST ~ S5 SUBUI；S0/S6 不算，2b2 §2.0）。"""
    return bool(
        isinstance(session, dialog.DialogSession)
        and session.state not in (dialog.S_IDLE, dialog.S_END)
    )


def _resume_brief(ctx: MutableMapping[str, Any], session: Any) -> Optional[str]:
    """恢复简报（RN-12）：激活会话 → dialog.build_resume_brief(snapshot)；否则 None。"""
    if not _active(session):
        return None
    try:
        return dialog.build_resume_brief(session.to_snapshot(), npc_name=session.npc_name)
    except Exception:
        return None


def _args_string(parsed: Any) -> str:
    """ParsedCommand → /对话 参数串（去首尾空白；多 token 以空格重建，名称禁空格由引擎裁决）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return ""
    return " ".join(str(a) for a in args)


def _npc_by_id(ctx: Mapping[str, Any], npc_id: Optional[str]) -> Optional[Mapping[str, Any]]:
    """按 id 在 ctx["npcs"] 中取 NPC dict（未命中 → None）。"""
    if not npc_id:
        return None
    for n in ctx.get("npcs") or ():
        if isinstance(n, Mapping) and str(n.get("id")) == str(npc_id):
            return n
    return None


def _greeting_of(npc: Mapping[str, Any]) -> str:
    """NPC 见面语：dialogues.greeting（发牌员孤寂卡兜底），缺省空串。"""
    dlg = npc.get("dialogues")
    if isinstance(dlg, Mapping):
        g = dlg.get("greeting")
        if g:
            return str(g)
    return ""


def _per_npc_state(ctx: MutableMapping[str, Any], npc_id: Optional[str]) -> MutableMapping:
    """按 npc 可变 state（ctx["npc_rotate"] 容器，装配层按 npc 持有）。

    同时承载发牌员 rotate 指针（index）与 reply cycle 指针（reply_index），dispatch_action
    与 deal 共用该 dict（【工程补白 8】）。缺省自建并回写 ctx。
    """
    rotate = ctx.get("npc_rotate")
    if not isinstance(rotate, MutableMapping):
        rotate = {}
        if isinstance(ctx, MutableMapping):
            ctx["npc_rotate"] = rotate
    if npc_id is None:
        npc_id = str(ctx.get("npc_id") or "")
    state = rotate.get(npc_id)
    if not isinstance(state, MutableMapping):
        state = {}
        rotate[npc_id] = state
    return state


def _eval_condition(ctx: Mapping[str, Any], cond: object) -> bool:
    """条件求值（对齐 dialog._eval_condition 口径）：无条件 → True；hook 异常 → False。"""
    if not cond:
        return True
    hook = ctx.get("eval_condition")
    if callable(hook):
        try:
            return bool(hook(cond, ctx.get("condition_ctx")))
        except Exception:
            return False
    return True


# -------------------------------------------------------------------------------------
# 副作用写入（已听双轨 / 事件双表 / 商店移交 / 会话激活落位）
# -------------------------------------------------------------------------------------
def _mark_heard(ctx: MutableMapping[str, Any], keys: Any) -> None:
    """dialog 侧已听写入（RN-03 ①）：mark_heard 键加入 ctx["heard"]（菜单置灰）。"""
    heard = ctx.get("heard")
    if not isinstance(heard, set):
        if isinstance(heard, (list, tuple)):
            heard = set(heard)
        else:
            heard = set()
        ctx["heard"] = heard
    for k in keys or ():
        heard.add(str(k))


def _bump_events(ctx: MutableMapping[str, Any], events: Any) -> None:
    """事件写入（RN-10 三表）：优先 ctx["bump_event"] hook（装配层统一函数），
    缺省调 event_bus.bump_event（event_counts + longline_counters + event_log 环形）。"""
    for key in events or ():
        if not key:
            continue
        hook = ctx.get("bump_event")
        if callable(hook):
            try:
                hook(ctx, str(key))
                continue
            except Exception:
                pass
        try:
            from qbot_rpg.core.event_bus import bump_event
            bump_event(ctx, str(key))
        except Exception:
            pass


def _apply_shop_refs(ctx: MutableMapping[str, Any], refs: Any) -> None:
    """商店移交（RN-06）：result.shop_refs 非空且当前商店空 → 记首个为当前商店
    （对齐 npc._action_shop 标量形态；dispatch_action 已写则幂等跳过）。"""
    refs = [r for r in (refs or ()) if r]
    if not refs:
        return
    cur = ctx.get("current_shop_ref")
    if cur is None or cur == [] or cur == "":
        ctx["current_shop_ref"] = refs[0]


def _npc_side_write(ctx: MutableMapping[str, Any], npc_id: Optional[str],
                    entry: Mapping[str, Any], dispatch: Optional[Mapping[str, Any]]) -> None:
    """npc 侧已听双轨键（RN-03 ②）：交付成功后 npc.mark_delivered(ctx, npc_id,
    f"intel:{ref_id}") / tutorial:{id} 落 ctx["npc_delivered"]。

    dispatch_action 内部（_action_intel/_action_tutorial）已写同键，此处幂等兜底防漏
    （【工程补白 4】）；仅当本次为新交付（dispatch ok 且 kind=info）时补写。
    """
    if not npc_id:
        return
    if not (dispatch and dispatch.get("ok")):
        return
    if str(dispatch.get("kind")) != "info":
        return
    for ref in entry.get("intel_refs") or ():
        rid = ref.get("id") if isinstance(ref, Mapping) else ref
        if rid:
            npc_mod.mark_delivered(ctx, str(npc_id), f"intel:{rid}")
    for ref in entry.get("tutorials") or ():
        rid = ref.get("id") if isinstance(ref, Mapping) else ref
        if rid:
            npc_mod.mark_delivered(ctx, str(npc_id), f"tutorial:{rid}")


def _touch_active(ctx: MutableMapping[str, Any], session: Any, active: bool) -> None:
    """会话激活落位：active=True → dialog_active 置真 + 会话实例回写；
    False → dialog_active 清 + 会话快照清（收尾，RN-13）。"""
    ctx["dialog_active"] = bool(active)
    ctx["dialog_session"] = session if active else None


# -------------------------------------------------------------------------------------
# 渲染
# -------------------------------------------------------------------------------------
def _render(kind: str, lines: List[str], *, resume: Optional[str] = None) -> str:
    """分支渲染 → str 回复。

    - command：带指令词不消费 → 空串（返回壳继续正常解析 R2）；
    - 其余：resume 简报（若有）+ lines 换行拼接；全空 → resume 或空串。
    """
    if kind == "command":
        return ""
    parts: List[str] = []
    if resume:
        parts.append(resume)
    body = "\n".join(lines) if lines else ""
    if body:
        parts.append(body)
    return "\n".join(parts)


def _is_fresh_landing(result: Mapping[str, Any]) -> bool:
    """是否 T05 落地（T02/T03 → S3 MENU 的新落地，非 T10 回菜单）。

    trace 含 ("T05", ...) 迁移即新落地——发牌员发牌只在此时触发（【工程补白 6】）。
    """
    for tr in result.get("trace") or ():
        if isinstance(tr, (tuple, list)) and len(tr) >= 1 and tr[0] == "T05":
            return True
    return False


def _dealer_delivery(ctx: MutableMapping[str, Any], session: Any) -> Optional[str]:
    """发牌员交付（RN-03）：落地 NPC 带 dealer 子结构 → npc.deal(...) 抽一张牌。

    deal 返回孤寂卡（无牌）→ message=greeting 兜底；抽中 → 交付结果 message。
    抽中/孤寂卡 message 非空 → 返回文案前置到菜单；无 message → None（不打扰）。
    rotate_state 取 ctx["npc_rotate"][npc_id]（按 npc 持有），deal 内部原地推进指针。
    """
    npc = _npc_by_id(ctx, getattr(session, "npc_id", None))
    if not isinstance(npc, Mapping):
        return None
    dealer = npc.get("dealer")
    if not isinstance(dealer, Mapping):
        return None
    npc_id = str(npc.get("id") or "")
    state = _per_npc_state(ctx, npc_id)
    try:
        res = npc_mod.deal(npc_id, dealer, ctx, ctx.get("rng"), state, _greeting_of(npc))
    except Exception:
        return None
    if isinstance(res, Mapping):
        msg = res.get("message")
        if msg:
            return str(msg)
    return None


def _menu_rerender(ctx: MutableMapping[str, Any], session: Any) -> List[str]:
    """S3 MENU 重显（中断恢复「菜单层重显」RN-12）：/对话 进入已激活 S_MENU 时引擎
    对 dialog 事件不消费（menu_noop），壳按当前 npc/heard/条件/页码重渲染交互菜单。"""
    if not _active(session):
        return []
    if getattr(session, "state", None) != dialog.S_MENU:
        return []
    npc = _npc_by_id(ctx, getattr(session, "npc_id", None))
    if not isinstance(npc, Mapping):
        return []
    interactions = [o for o in (npc.get("interactions") or ()) if isinstance(o, Mapping)]
    heard = ctx.get("heard") or ()
    conditions = {
        i: _eval_condition(ctx, it.get("condition")) for i, it in enumerate(interactions)
    }
    menu = dialog.render_interaction_menu(
        interactions, heard=heard, conditions=conditions,
        page=int(getattr(session, "menu_page", 0) or 0),
    )
    head = f"{session.npc_name}：" if getattr(session, "npc_name", None) else ""
    return ([head] if head else []) + menu["lines"]


# -------------------------------------------------------------------------------------
# 动作执行接线（RN-03）
# -------------------------------------------------------------------------------------
def _dispatch_entry(entry: Mapping[str, Any], ctx: MutableMapping[str, Any],
                    npc_id: Optional[str], state: MutableMapping) -> dict:
    """壳自行调 npc.dispatch_action(entry, ctx, rng, npc_id, state)（真实签名 L688）。

    异常 → 安全失败 {ok: False, message}（不裸崩，TPL-12 兜底由装配层）。
    """
    try:
        out = npc_mod.dispatch_action(entry, ctx, ctx.get("rng"), npc_id, state)
    except Exception:
        return {"ok": False, "action": entry.get("action"), "message": "动作执行异常"}
    return out if isinstance(out, Mapping) else {"ok": False, "message": "动作返回异常"}


def _payload_of(dispatch: Mapping[str, Any], entry: Mapping[str, Any]) -> dict:
    """dispatch 结果 → exec_done payload 六键（RN-03：info_key/is_info/subui/label/
    shop_refs/completed）。info_key 仅显式携带；未给 → 引擎按 _exec_index 推导（L724-726）。"""
    raw_data = dispatch.get("data")
    data: Mapping[str, Any] = raw_data if isinstance(raw_data, Mapping) else {}
    shop_refs = list(data.get("shop_refs") or entry.get("shop_refs") or [])
    is_info = bool(dispatch.get("ok") and str(dispatch.get("kind")) == "info")
    subui = bool(entry.get("subui") or data.get("subui"))
    return {
        "info_key": entry.get("info_key"),
        "is_info": is_info,
        "subui": subui,
        "label": entry.get("label") or entry.get("text") or data.get("subui_label"),
        "shop_refs": shop_refs,
        "completed": None,
    }


def _dispatch_feedback(dispatch: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    """功能型动作交付反馈：dispatch message 前置到菜单输出。

    失败（金币不足等）→ 反馈必显；成功且无 shop_refs → 反馈业务文案（治疗完成等）；
    shop_refs 成功 → 引擎已输出「已打开商店」行，返回空串防冗余。
    """
    if not isinstance(dispatch, Mapping):
        return ""
    if payload.get("shop_refs"):
        return ""
    msg = dispatch.get("message")
    return str(msg) if msg else ""


# -------------------------------------------------------------------------------------
# 结果消费（副作用 + 分支渲染）
# -------------------------------------------------------------------------------------
def _consume(result: Mapping[str, Any], ctx: MutableMapping[str, Any],
             session: Any, *, resume: Optional[str] = None) -> str:
    """消费 step 结果：副作用写入（已听/事件/商店/激活落位）+ 按 kind 分支渲染。

    - command：不消费 → 空串（返回壳正常解析 R2）；
    - menu 新落地 + dealer NPC → 发牌文案前置；
    - menu 无输出（/对话 进入已激活 S_MENU）→ 菜单重显（中断恢复）；
    - ended：清激活 + 事件计数（引擎 result.events 已上报），无输出。
    """
    if not isinstance(result, Mapping):
        return resume or ""
    norm = normalize_dialog_result(result)
    kind, lines = norm["kind"], list(norm["lines"])

    _mark_heard(ctx, result.get("mark_heard") or ())
    _bump_events(ctx, result.get("events") or ())
    _apply_shop_refs(ctx, result.get("shop_refs") or ())
    active = bool(result.get("session_active", False))
    _touch_active(ctx, session, active)

    if kind == "menu" and _is_fresh_landing(result):
        deal_msg = _dealer_delivery(ctx, session)
        if deal_msg:
            lines = [deal_msg] + lines
    if not lines and kind == "menu" and _active(session):
        lines = _menu_rerender(ctx, session)

    return _render(kind, lines, resume=resume)


# -------------------------------------------------------------------------------------
# 指令壳入口
# -------------------------------------------------------------------------------------
def cmd_dialog(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/对话 [参数] 主入口（RN-01）：无参列表 / N 序号 / 名称（名称优先禁空格）。

    参数解析委托 dialog.parse_dialog_command(args, npcs)；建会话事件
    session.step(("dialog", parsed), ctx) 驱动引擎；结果经 _consume 渲染。
    已激活会话（中断恢复 RN-12）：前置恢复简报；S_MENU 下引擎对 dialog 不消费 →
    _menu_rerender 重显菜单。
    """
    if not isinstance(ctx, MutableMapping):
        return ""
    session = _session(ctx)
    resume = _resume_brief(ctx, session)
    npcs = ctx.get("npcs") or []
    parsed_dialog = dialog.parse_dialog_command(_args_string(parsed), npcs)
    result = session.step(("dialog", parsed_dialog), ctx)
    return _consume(result, ctx, session, resume=resume)


def cmd_dialog_session(subword: Any, ctx: MutableMapping[str, Any]) -> str:
    """会话子词入口（RN-02）：router.route_message ROUTE_SESSION 分支送 mode=session_digit
    → 桥接层调本函数，壳按 subword 调 session.step((sub, value), ctx)。

    subword = (category, value)，category ∈ digit/continue/exit/select（classify_session_input
    归一子词）。step 返回 exec 请求 → _handle_exec 自行 dispatch_action；其余经 _consume。
    无激活会话 / 非子词形态 → 空串（不消费）。
    恢复简报仅在 /对话 入口显示（【工程补白 7】），会话子词不重复带简报。
    """
    if not isinstance(ctx, MutableMapping):
        return ""
    session = ctx.get("dialog_session")
    if not isinstance(session, dialog.DialogSession):
        return ""
    if session.state in (dialog.S_IDLE, dialog.S_END):
        return ""
    if not (isinstance(subword, (tuple, list)) and len(subword) == 2):
        return ""
    result = session.step((subword[0], subword[1]), ctx)
    if result.get("kind") == "exec":
        return _handle_exec(result, ctx, session, resume=None)
    return _consume(result, ctx, session, resume=None)


def _handle_exec(result: Mapping[str, Any], ctx: MutableMapping[str, Any],
                 session: Any, *, resume: Optional[str] = None) -> str:
    """exec 请求消费（RN-03）：壳自行调 npc.dispatch_action 并回传 exec_done。

    叙述型（output 非空）：当场完成 npc 侧交付记账，渲染叙述段（不喂 exec_done，由引擎
    翻段收尾 mark_heard）；功能型（output 空）：dispatch → payload → step(("exec_done",
    payload)) 回菜单，并前置 dispatch 交付反馈文案。
    """
    entry = result.get("action")
    lines = list(result.get("output") or [])
    npc_id = getattr(session, "npc_id", None) or ctx.get("npc_id")
    state = _per_npc_state(ctx, npc_id)
    ctx["dialog_active"] = True
    ctx["dialog_session"] = session
    if not isinstance(entry, Mapping):
        return _render("noop", lines, resume=resume)

    dispatch = _dispatch_entry(entry, ctx, npc_id, state)
    _npc_side_write(ctx, npc_id, entry, dispatch)

    if lines:
        # 叙述型：渲染叙述；交付记账已由 dispatch 完成；exec_done 由引擎末段收尾
        return _render("narration", lines, resume=resume)

    # 功能型：映射 exec_done payload 六键回传
    payload = _payload_of(dispatch, entry)
    result2 = session.step(("exec_done", payload), ctx)
    out = _consume(result2, ctx, session, resume=resume)
    feedback = _dispatch_feedback(dispatch, payload)
    if feedback:
        out = f"{feedback}\n{out}" if out else feedback
    return out


def cmd_dialog_interrupt(ctx: MutableMapping[str, Any]) -> str:
    """中断入口（RN-12）：step(("interrupt", None)) 落快照即回，状态不变。

    中断不迁移、激活保持（2b2 §2.3）；会话实例仍置 ctx["dialog_session"]，由装配层提交
    快照落盘（persistent_state["dialog_session"]）；无激活会话 → 空串。返回空串。
    """
    if not isinstance(ctx, MutableMapping):
        return ""
    session = ctx.get("dialog_session")
    if not isinstance(session, dialog.DialogSession):
        return ""
    if session.state in (dialog.S_IDLE, dialog.S_END):
        return ""
    session.step(("interrupt", None), ctx)
    ctx["dialog_active"] = True
    ctx["dialog_session"] = session
    return ""


def cmd_dialog_confirm(ctx: MutableMapping[str, Any], *, completed: bool = True) -> str:
    """子界面确认入口（RN-03 · S5 SUBUI）：step(("confirm_done", {"completed": ...}))。

    completed=True → T13 回菜单；False → 留子界面提示「『label』未完成」。当前 10 类动作
    均为单轮交付（引擎不产 SUBUI），本入口为 heal 确认/任务交付确认预留（2b2 §2.0 S5）。
    """
    if not isinstance(ctx, MutableMapping):
        return ""
    session = ctx.get("dialog_session")
    if not isinstance(session, dialog.DialogSession):
        return ""
    if session.state != dialog.S_SUBUI:
        return ""
    resume = _resume_brief(ctx, session)
    result = session.step(("confirm_done", {"completed": bool(completed)}), ctx)
    return _consume(result, ctx, session, resume=resume)


# -------------------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，BCH-03 后 REGISTER_GROUPS 接入）
# -------------------------------------------------------------------------------------
def register_dialog_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /对话 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 npcs/heard/npc_delivered/
        settings/eval_condition/condition_ctx/rng/dialog_session 等，见 core/dialog.py
        工程补白 + 细化_M7 N-01 RN-02 ctx 前置）。None 时 handler 调用抛 RuntimeError
        （【待接线】BCH-03 装配入口注入；此时若 runner 注入了 ctx=ctx 则回退用之）。
    返回 router（链式）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】dialog_commands.register_dialog_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _dialog(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_dialog(parsed, injected)
        return cmd_dialog(parsed, _ctx(parsed))

    router.register(CommandSpec(DIALOG_CMD, handler=_dialog))
    return router
