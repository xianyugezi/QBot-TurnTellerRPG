"""调合会话状态机纯逻辑（M8 批3·路3B）——无会话→会话中→挂起(战斗)→恢复→确认/放弃 终态。

文件名：qbot_rpg/core/alchemy_session.py
创建时间：2026-08-29
作者：Hermes 子agent-3B（并发同仓：仅新建本文件 + tests/unit/test_alchemy_session.py；
      兄弟路 3A 在实装 world/session.py SessionManager，本文件零 import 之，只读勿探查）

功能描述：调合会话状态机纯逻辑（零 IO 零 NoneBot 纯函数/纯类）——§7.1 状态迁移表全部 12 行
  可判定（无会话→会话中 / 挂起(战斗) / 恢复 / 确认·放弃 终态）、非法转移模板映射、version
  幂等（重复 /确认 →「已结算」不双扣）、挂起/恢复判定、战斗即时调合豁免互斥（/即时调合 不进入
  本状态机）。供批4 指令壳（/炼金 /投料 /继承 /继承超 /加成 /确认 /放弃 /调合续）与批6A
  结算、批9A 即时调合消费。

依据：
  - docs/m8_contract_核心机制.md 七（§7.1 状态迁移表 12 行 / §7.2 契约要点：version 幂等、
    全局互斥、终态结算模式 settle_exit_idempotent、战斗即时调合不进入本状态机）
  - docs/m8_batch_plan.md 批3·路3B（本路派工）+ 批6A（/确认 结算消费）/ 批9A（/即时调合 豁免）
  - 定稿【炼金】L176-183（再发拒绝模板 L176「调合进行中！/放弃 退出 或 /调合续 继续」、
    L177「已有一个调合会话进行中」、L183 僵尸会话回收（材料返还））
  - 接口摸底 二 + IF-11~19（SessionManager 占位 / SessionRow / settle_exit_idempotent /
    recycle_scan / SessionConflictError）
  - storage/schema.py L24 SESSION_TYPES 已含 alchemy/challenge_alchemy（批0 确认，不改表）

SessionView 消费（鸭子类型，收口裁决见任务书；兄弟路 3A 按此实装）：
  视图形态 {player_qid, session_type, payload, random_seed, version, created_at,
  last_active_at}——dataclass 或 dict 均可；本模块读 .session_type/.version/.payload（属性）
  或 dict 键。session_type 取值：alchemy/challenge_alchemy 为调合类（批0 确认），battle 为
  战斗会话。

【工程补白 · 显式标注】（定稿 12 行未覆盖处的最小必要推导，不得新增定稿外行为）：
  P-1  ALCHEMY_START 与 NEW_RECIPE 统一为「/炼金 <配方>」语义：会话中→拒绝（行5）；挂起→
       恢复（行7「或 /炼金 恢复」）；无会话/终态→启动前置（行1/3）。NEW_RECIPE 仅语义上
       携带「新配方」，状态机判定与 ALCHEMY_START 相同。
  P-2  TERMINATED 视为槽位已清：终态后 /炼金 → 等同无会话可重新 acquire（行1 语义延伸）；
       终态后其它操作事件 → 无会话模板（行2 语义延伸）。settle_exit_idempotent 终态已
       delete_session（§7.2），故终态后 get_active 返回 None。
  P-3  挂起(战斗) 中收到 /投料 /继承 /继承超 /加成 /确认 → 拒绝「调合进行中」（行5 模板复用，
       文本即提示用 /调合续 恢复）；挂起中 /放弃 → 终态退还材料（行10 语义延伸——挂起的会话
       仍持有已投材料，拒绝放弃将滞留材料）。
  P-4  会话中/挂起 超 30 天未活动 → 僵尸回收 recycle（行12 语义延伸：recycle_scan 按
       last_active_at 扫描不区分会话状态，活跃会话同样可回收；终态回调须含已投材料返还，
       定稿 L183）。
  P-5  version 幂等口径（§7.2 version 幂等）：结算标记版本 = 当前版本 + 1（本次终态将版本
       推进一档并写幂等键）；view 缺失（行已 delete_session）即视为已结算；
       terminate_idempotent 同时支持 version 已 ≥ 阈值判定（防御性兜底）。
  P-6  状态机输入防御：携带 session_view 但其 session_type 非 alchemy/challenge_alchemy
       （如 battle）→ 视为「已有活跃会话」（§7.2 全局互斥，其它会话类型占用槽位）→ 拒绝。
  P-7  template_key 直接用定稿模板中文键（无会话/已有活跃/调合进行中/已有一个调合会话进行中/
       已结算），TEMPLATE_MESSAGES 提供壳层可直用的人话文本。
  P-8  transition 增加 conflict 关键字参数（仅 ALCHEMY_START/NEW_RECIPE/RESUME 消费）：
       镜像 SessionManager 互斥现实（get_active 已存在其它会话 / acquire·restore 抛
       SessionConflictError）——纯逻辑不 IO 不持仓库，由壳层在调用前判定并传入（行3/8）。

铁律：零 NoneBot import；零 IO（纯函数同刻同参必同值）；不抛异常（防御降级返回 dict）；
      每条规则注释标注出处（§7.1 迁移表第 N 行 / §7.2 / 定稿行号）；不得新增定稿外行为。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

__all__ = [
    "ALCHEMY_SESSION",
    "CHALLENGE_SESSION",
    "ALCHEMY_SESSION_TYPES",
    "NONE",
    "SESSION_ACTIVE",
    "SUSPENDED",
    "TERMINATED",
    "Event",
    "ACTION_ACQUIRE",
    "ACTION_UPDATE",
    "ACTION_SUSPEND",
    "ACTION_RESTORE",
    "ACTION_SETTLE_CONFIRM",
    "ACTION_SETTLE_ABANDON",
    "ACTION_RECYCLE",
    "ACTION_NONE",
    "TEMPLATE_NO_SESSION",
    "TEMPLATE_ALREADY_ACTIVE",
    "TEMPLATE_IN_PROGRESS",
    "TEMPLATE_ALREADY_ACTIVE_ALCHEMY",
    "TEMPLATE_ALREADY_SETTLED",
    "TEMPLATE_MESSAGES",
    "transition",
    "is_conflict",
    "can_start",
    "terminate_idempotent",
    "suspendable",
    "resumable",
    "instant_ok",
    "is_alchemy_session",
]

# ---------------------------------------------------------------------------
# 会话类型常量（storage/schema.py L24 SESSION_TYPES；批0 确认，不改表）
# ---------------------------------------------------------------------------
ALCHEMY_SESSION: str = "alchemy"
CHALLENGE_SESSION: str = "challenge_alchemy"
ALCHEMY_SESSION_TYPES: tuple = (ALCHEMY_SESSION, CHALLENGE_SESSION)

# ---------------------------------------------------------------------------
# 状态常量（任务书：NONE=无会话 / SESSION_ACTIVE=会话中 / SUSPENDED=挂起(战斗) /
# TERMINATED=终态）
# ---------------------------------------------------------------------------
NONE: str = "none"                 # 无会话
SESSION_ACTIVE: str = "active"     # 会话中
SUSPENDED: str = "suspended"       # 挂起(战斗)
TERMINATED: str = "terminated"     # 终态


class Event(Enum):
    """状态机事件枚举（任务书事件名；§7.1 触发列）。"""

    ALCHEMY_START = "alchemy_start"       # /炼金 <配方> 开会话（行1/3/5；定稿 L176-183）
    FEED = "feed"                         # /投料 追加（行2/4）
    INHERIT = "inherit"                   # /继承（行2/4）
    INHERIT_SUPER = "inherit_super"       # /继承超（行2/4）
    BUFF = "buff"                         # /加成（行2/4）
    CONFIRM = "confirm"                   # /确认（行2/9/11）
    ABANDON = "abandon"                   # /放弃（行2/10）
    BATTLE_INTERRUPT = "battle_interrupt"  # 战斗打断（行6）
    RESUME = "resume"                     # /调合续（行7/8）
    NEW_RECIPE = "new_recipe"             # /炼金 <新配方> 再发（行5；P-1 与 ALCHEMY_START 同语义）
    TIMEOUT = "timeout"                   # 超 30 天未活动僵尸（行12；P-4）


# ---------------------------------------------------------------------------
# 动作常量（任务书：action ∈ acquire/update/suspend/restore/settle_confirm/
# settle_abandon/recycle/无）
# ---------------------------------------------------------------------------
ACTION_ACQUIRE: str = "acquire"            # 开会话（行1）
ACTION_UPDATE: str = "update"              # 状态更新 version 递增（行4）
ACTION_SUSPEND: str = "suspend"            # 战斗打断挂起快照（行6）
ACTION_RESTORE: str = "restore"            # 恢复快照（行7）
ACTION_SETTLE_CONFIRM: str = "settle_confirm"  # /确认 终态品质结算（行9）
ACTION_SETTLE_ABANDON: str = "settle_abandon"  # /放弃 终态退还材料（行10）
ACTION_RECYCLE: str = "recycle"            # 30 天僵尸回收 + settle 回调（行12；P-4）
ACTION_NONE: str = "无"                    # 无动作（非法转移 / 无操作）

# ---------------------------------------------------------------------------
# 非法转移模板键（任务书：无会话/已有活跃/调合进行中/已有一个调合会话进行中/已结算；
# P-7 直接使用定稿中文键，TEMPLATE_MESSAGES 供壳层直用）
# ---------------------------------------------------------------------------
TEMPLATE_NO_SESSION: str = "无会话"        # 行2：「当前没有调合会话，先 /炼金 <配方> 开始」
TEMPLATE_ALREADY_ACTIVE: str = "已有活跃"  # 行3：SessionConflictError 全局互斥「已有活跃会话」
TEMPLATE_IN_PROGRESS: str = "调合进行中"    # 行5：定稿 L176 拒绝模板（全文见 TEMPLATE_MESSAGES）
TEMPLATE_ALREADY_ACTIVE_ALCHEMY: str = "已有一个调合会话进行中"  # 行8：定稿 L177
TEMPLATE_ALREADY_SETTLED: str = "已结算"   # 行11：重复确认幂等「已结算」不双扣

TEMPLATE_MESSAGES: Dict[str, str] = {
    TEMPLATE_NO_SESSION: "当前没有调合会话，先 /炼金 <配方> 开始",
    TEMPLATE_ALREADY_ACTIVE: "已有活跃会话",
    TEMPLATE_IN_PROGRESS: "调合进行中！/放弃 退出 或 /调合续 继续",
    TEMPLATE_ALREADY_ACTIVE_ALCHEMY: "已有一个调合会话进行中",
    TEMPLATE_ALREADY_SETTLED: "已结算",
}


def _dec(
    allowed: bool,
    next_state: str,
    action: str,
    template_key: Optional[str],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """构造迁移判定结果 dict（{allowed, next_state, action, template_key, reason}）。"""
    return {
        "allowed": allowed,
        "next_state": next_state,
        "action": action,
        "template_key": template_key,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# SessionView 鸭子类型读取
# ---------------------------------------------------------------------------
def _attr_or_key(view: Any, name: str) -> Any:
    """鸭子类型读 SessionView 字段：优先属性，回退 dict 键（P-6 / SessionView 契约）。"""
    if view is None:
        return None
    value = getattr(view, name, None)
    if value is None and isinstance(view, dict):
        value = view.get(name)
    return value


def _version_of(view: Any) -> Optional[int]:
    """读视图 version（None=无会话行 / 无法解析）。"""
    raw = _attr_or_key(view, "version")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_alchemy_session(session_view: Any) -> bool:
    """SessionView 是否为调合类会话（alchemy/challenge_alchemy，批0 确认）。

    入参：session_view=会话视图（dataclass/dict 均可）。
    出参：True=调合类会话；False=非调合类（含 battle / 未知 / None）。
    核心逻辑：读 .session_type 或 dict 键，命中 ALCHEMY_SESSION_TYPES 即真（鸭子类型）。
    """
    return _attr_or_key(session_view, "session_type") in ALCHEMY_SESSION_TYPES


# ---------------------------------------------------------------------------
# 状态迁移判定（§7.1 迁移表 12 行）
# ---------------------------------------------------------------------------
def transition(
    state: str,
    event: Event,
    session_view: Any = None,
    *,
    conflict: bool = False,
) -> Dict[str, Any]:
    """状态迁移判定（§7.1 状态迁移表全部 12 行可判定，纯函数零 IO）。

    入参：state=当前状态（NONE/SESSION_ACTIVE/SUSPENDED/TERMINATED）；
         event=Event 事件；session_view=会话视图（鸭子类型，可选）；
         conflict=已有其它活跃会话（镜像 SessionManager 互斥现实，P-8）。
    出参：{allowed, next_state, action, template_key, reason}——
         allowed=True 表示合法迁移；template_key 非 None 表示非法转移模板（P-7 中文键），
         action ∈ acquire/update/suspend/restore/settle_confirm/settle_abandon/recycle/无。
    核心逻辑：按 §7.1 12 行逐一映射；未覆盖处按【工程补白】P-1~P-8 最小必要推导；
         不抛异常（防御降级返回 dict）。
    """
    if event in (Event.ALCHEMY_START, Event.NEW_RECIPE):
        # /炼金 <配方>：开会话 / 再发新配方 统一处理（P-1）
        if state is SESSION_ACTIVE:
            # 行5：会话中再发 → 拒绝「调合进行中」（定稿 L176）
            return _dec(
                False, SESSION_ACTIVE, ACTION_NONE, TEMPLATE_IN_PROGRESS,
                "行5：调合进行中！/放弃 退出 或 /调合续 继续",
            )
        if state is SUSPENDED:
            # 行8：挂起但已有其它活跃会话 → 拒绝「已有一个调合会话进行中」（定稿 L177）
            if conflict:
                return _dec(
                    False, SUSPENDED, ACTION_NONE, TEMPLATE_ALREADY_ACTIVE_ALCHEMY,
                    "行8：已有一个调合会话进行中",
                )
            # 行7：挂起(战斗) + /炼金 恢复 → restore（快照恢复，特性选择与 PP 不丢）
            return _dec(True, SESSION_ACTIVE, ACTION_RESTORE, None, "行7：/炼金 恢复快照")
        # 行1/3：无会话 / 终态（P-2）→ 启动前置判定
        return can_start(state, conflict=conflict)

    if event is Event.RESUME:
        # /调合续
        if state is SUSPENDED:
            if conflict:
                # 行8：挂起但已有活跃会话 → 拒绝（定稿 L177）
                return _dec(
                    False, SUSPENDED, ACTION_NONE, TEMPLATE_ALREADY_ACTIVE_ALCHEMY,
                    "行8：已有一个调合会话进行中",
                )
            # 行7：挂起 → 恢复
            return _dec(True, SESSION_ACTIVE, ACTION_RESTORE, None, "行7：/调合续 恢复快照")
        if state is NONE:
            # 行2 语义：没有会话可续
            return _dec(False, NONE, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：当前没有调合会话")
        if state is SESSION_ACTIVE:
            # 补白：会话进行中无需 /调合续
            return _dec(
                False, SESSION_ACTIVE, ACTION_NONE, TEMPLATE_IN_PROGRESS,
                "P-3：调合进行中，无需 /调合续",
            )
        # TERMINATED（P-2）
        return _dec(
            False, TERMINATED, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：终态已清，无会话可续",
        )

    if event in (Event.FEED, Event.INHERIT, Event.INHERIT_SUPER, Event.BUFF):
        # /投料 追加 /继承 /继承超 /加成
        if state is SESSION_ACTIVE:
            if session_view is not None and not is_alchemy_session(session_view):
                # P-6：活跃会话非调合类（如 battle）→ 全局互斥「已有活跃会话」
                return _dec(
                    False, SESSION_ACTIVE, ACTION_NONE, TEMPLATE_ALREADY_ACTIVE,
                    "P-6：活跃会话非调合类（§7.2 全局互斥）",
                )
            # 行4：状态更新（材料链/连锁/特性/PP/步骤），version 递增
            return _dec(True, SESSION_ACTIVE, ACTION_UPDATE, None, "行4：状态更新，version 递增")
        if state is NONE:
            # 行2：无会话非法转移
            return _dec(False, NONE, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：当前没有调合会话")
        if state is SUSPENDED:
            # P-3：挂起中需先 /调合续 恢复（复用行5 模板，文本即提示）
            return _dec(
                False, SUSPENDED, ACTION_NONE, TEMPLATE_IN_PROGRESS,
                "P-3：挂起中，/调合续 恢复后再操作",
            )
        # TERMINATED（P-2）
        return _dec(False, TERMINATED, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：终态已清，无会话")

    if event is Event.CONFIRM:
        # /确认
        if state is SESSION_ACTIVE:
            if session_view is not None and not is_alchemy_session(session_view):
                return _dec(
                    False, SESSION_ACTIVE, ACTION_NONE, TEMPLATE_ALREADY_ACTIVE,
                    "P-6：活跃会话非调合类（§7.2 全局互斥）",
                )
            view_ver = _version_of(session_view)
            if terminate_idempotent(_settle_marker(view_ver), view_ver):
                # 行11：重复确认 → 终态幂等「已结算」不双扣
                return _dec(
                    True, TERMINATED, ACTION_NONE, TEMPLATE_ALREADY_SETTLED,
                    "行11：重复确认已结算，不双扣",
                )
            # 行9：终态品质结算（settle_exit_idempotent 同款终态结算）
            return _dec(True, TERMINATED, ACTION_SETTLE_CONFIRM, None, "行9：品质结算终态")
        if state is NONE:
            # 行2
            return _dec(False, NONE, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：当前没有调合会话")
        if state is SUSPENDED:
            # P-3：挂起中先 /调合续 恢复
            return _dec(
                False, SUSPENDED, ACTION_NONE, TEMPLATE_IN_PROGRESS,
                "P-3：挂起中，/调合续 恢复后再确认",
            )
        # TERMINATED（P-2 / 行11 幂等延伸）
        return _dec(True, TERMINATED, ACTION_NONE, TEMPLATE_ALREADY_SETTLED, "行11：已结算")

    if event is Event.ABANDON:
        # /放弃
        if state is SESSION_ACTIVE:
            # 行10：终态退还材料
            return _dec(True, TERMINATED, ACTION_SETTLE_ABANDON, None, "行10：退还材料终态")
        if state is SUSPENDED:
            # P-3：挂起中 /放弃 同样终态退还材料（避免材料滞留）
            return _dec(
                True, TERMINATED, ACTION_SETTLE_ABANDON, None, "P-3：挂起中 /放弃 终态退还材料",
            )
        if state is NONE:
            return _dec(False, NONE, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：当前没有调合会话")
        # TERMINATED（P-2）
        return _dec(False, TERMINATED, ACTION_NONE, TEMPLATE_NO_SESSION, "行2：终态已清，无会话")

    if event is Event.BATTLE_INTERRUPT:
        # 战斗打断
        if state is SESSION_ACTIVE:
            # 行6：挂起(战斗)，快照持久化（配方ID+材料链+连锁+特性+触媒+PP+步骤+version）
            return _dec(
                True, SUSPENDED, ACTION_SUSPEND, None,
                "行6：战斗打断 → 挂起(战斗)，快照持久化",
            )
        # 补白：无活跃会话无需挂起（NONE/TERMINATED 无操作；SUSPENDED 已挂起）
        return _dec(True, state, ACTION_NONE, None, "P-3：无活跃会话，无需挂起")

    if event is Event.TIMEOUT:
        # 超 30 天僵尸（行12；P-4 活跃同样回收）
        if state in (SUSPENDED, SESSION_ACTIVE):
            return _dec(
                True, TERMINATED, ACTION_RECYCLE, None,
                "行12：30 天僵尸回收 + settle 回调（含已投材料返还，定稿 L183）",
            )
        return _dec(True, state, ACTION_NONE, None, "P-4：无会话可回收")

    # 未知事件防御（不抛异常）
    return _dec(False, state, ACTION_NONE, None, "未知事件")


def can_start(ctx_state: str, *, conflict: bool = False) -> Dict[str, Any]:
    """会话启动前置（§7.1 行1/3；定稿【炼金】L176-183）——无会话 + 无冲突 → acquire。

    入参：ctx_state=调用方已知会话状态（NONE/SESSION_ACTIVE/SUSPENDED/TERMINATED）；
         conflict=已有其它活跃会话（SessionManager 判定：get_active 非空 / acquire 抛
         SessionConflictError，§7.2 全局互斥私聊+多群）。
    出参：{allowed, next_state, action, template_key, reason}。
    核心逻辑：
      - 无会话/终态 且无冲突 → acquire 开会话（行1；终态后槽位已清可重新开始，P-2）；
      - 无会话/终态 但有冲突 → 拒绝「已有活跃」全局互斥（行3，SessionConflictError）；
      - 会话中 → 拒绝「调合进行中」（行5 语义：再发新配方）；
      - 挂起 → 拒绝「调合进行中」（P-1：挂起需 /调合续 或 /炼金 恢复）。
    """
    if ctx_state in (NONE, TERMINATED):
        if conflict:
            # 行3：已有其它会话（SessionConflictError → 「已有活跃会话」，全局互斥）
            return _dec(
                False, NONE, ACTION_NONE, TEMPLATE_ALREADY_ACTIVE,
                "行3：已有其它会话（§7.2 全局互斥，私聊+多群）",
            )
        # 行1：acquire 成功 → 扣能量（ENG-04）→ 面板渲染（由壳层执行）
        return _dec(True, SESSION_ACTIVE, ACTION_ACQUIRE, None, "行1：acquire 开会话")
    if ctx_state is SESSION_ACTIVE:
        # 行5：会话中再发新配方 → 拒绝
        return _dec(
            False, SESSION_ACTIVE, ACTION_NONE, TEMPLATE_IN_PROGRESS,
            "行5：调合进行中！/放弃 退出 或 /调合续 继续",
        )
    if ctx_state is SUSPENDED:
        # P-1：挂起中 /炼金 → 恢复而非新开会话（行7）
        return _dec(
            False, SUSPENDED, ACTION_NONE, TEMPLATE_IN_PROGRESS,
            "P-1：挂起中，/调合续 或 /炼金 恢复",
        )
    return _dec(False, ctx_state, ACTION_NONE, None, "未知状态")


def is_conflict(exc: object) -> bool:
    """SessionConflictError 判定（鸭子类型，兄弟路 3A 领域异常 world/session.py L20）。

    入参：exc=任意异常对象。
    出参：True=该异常或其父类名为 SessionConflictError（含子类）；False=其它。
    核心逻辑：遍历 MRO 逐个取类型 __name__ 比对（getattr 鸭子类型，零 import 兄弟路文件，
         避免并行仓编辑期间 import 半成品；子类同样命中）。
    """
    for cls in type(exc).__mro__:
        if getattr(cls, "__name__", "") == "SessionConflictError":
            return True
    return False


def terminate_idempotent(current_version: Optional[int], view_version: Optional[int]) -> bool:
    """version 幂等判定（§7.2）——重复 /确认 已结算 → True（不双扣）。

    入参：current_version=结算标记版本（本次终态将写入的版本，P-5 = 当前版本+1）；
         view_version=SessionView.version（load_session 返回行；None=无会话行）。
    出参：True=已结算（view 缺失或 version 已 ≥ 结算标记版本）；False=未结算，可结算。
    核心逻辑：settle_exit_idempotent 终态会 delete_session + 写幂等键（§7.2），重复确认时
         load_session 已返回 None（view_version=None）→ 已结算；version 列兜底：行若仍存在且
         version ≥ 结算标记版本（已推进到/越过结算点）→ 已结算（P-5 防御性兜底）。
    """
    if view_version is None:
        return True
    if current_version is None:
        return False
    return view_version >= current_version


def _settle_marker(view_version: Optional[int]) -> Optional[int]:
    """结算标记版本（P-5）：当前版本 + 1（本次终态将版本推进一档并写幂等键）。"""
    if view_version is None:
        return None
    return view_version + 1


def suspendable(state: str) -> bool:
    """是否可挂起（战斗打断 → 挂起(战斗)，§7.1 行6）：仅会话中可挂起。"""
    return state is SESSION_ACTIVE


def resumable(state: str) -> bool:
    """是否可恢复（/调合续 → 会话中，§7.1 行7）：仅挂起(战斗)可恢复。"""
    return state is SUSPENDED


def instant_ok(in_battle: bool, state: str) -> bool:
    """战斗即时调合豁免互斥（§7.2 / 批9A / F-10）。

    入参：in_battle=是否战斗中；state=当前会话状态（豁免语义参考）。
    出参：True=可即时调合。
    核心逻辑：/即时调合 为战斗内子流程——不新开会话/不挂起战斗/不申请会话槽/豁免互斥
         （INST-02，§7.2）；in_battle=True 时不受会话互斥约束（F-10），即使当前处于
         会话中/挂起也放行（战斗内一步出结果，不进入本状态机）；in_battle=False 时拒绝
         （非战斗场景无即时调合）。state 不参与判定（战斗内无条件豁免），保留参数供
         批9A 消费签名对称。
    """
    return in_battle
