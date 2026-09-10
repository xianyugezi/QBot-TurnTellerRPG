"""CTB 调度器（有状态）—— CTB 重写 · Agent 2（调度器架构）。

依据：
  - docs/ctb/01_asset_inventory.md §0.2「CTB 事件位点词典」（10 种事件）+
    §0.1 三分类口径（时序旧方法留 `NotImplementedError` 壳）。
  - 需求文档 CTB 重写：核心公式 `next_ready = current_time + recovery(action) *
    speed_reference / max(effective_speed, min_speed) + action_delay`（实现见 ctb_rules）。
  - 本项目硬约束（m3 铁律 1 / M43① 零定时器）：**绝不使用真实计时器 / 休眠 / 并发线程**；
    时间是引擎推进的逻辑时间。

本文件 = CTB 有状态调度器（不依赖 qbot_rpg.core.battle，可独立跑绿）：
  CTBScheduler
    ├─ 逻辑时间推进     advance_to_next_ready() / battle_time / current_time
    ├─ 行动队列         push_actor() / rebuild() / peek_next() / pop_next()
    ├─ 事件模型         注册 subscribe(event, cb) + drain_events()（顺序确定）
    ├─ generation 票据  每票带 generation；bump_generation() 递增；旧票回流被丢弃
    ├─ 可暂停输入式     npc 连锁自动推进 / 玩家 Ready 暂停 / 多 NPC 合并上报
    └─ 确定性           同初始态 + 同行动序列 + 同 seed → 完全可复现（本层不消费随机）

关键设计（对齐任务书 §d/§e）：
  1. 逻辑时间：唯一推进源是调度器自身的 `_time`，由 `advance_to_next_ready()` 单调递增；
     无任何真实时钟参与推进（零休眠 / 零并发线程 / 零 wall-clock 依赖）。
  2. 行动队列：最小 `next_ready` 出队；同刻并列按冻结 tie-break 规则
     （speed 降序 → 阵营 player 优先 → actor_id 字典序 → 入队 seq FIFO 兜底）。
  3. 事件：外部订阅 / 消费；`drain_events()` 返回按时序冻结的事件列表（可复现）。
  4. generation 票据：每次状态变更（死亡 / 速度变化 / 规则变更 / 重建队列）递增 generation；
     旧 generation 的票回流时被识别并丢弃（计入 `stale_dropped` 审计），不污染队列。
  5. 可暂停输入式 CTB：NPC 连锁 → 自动推进并累积 `ActionBatchReport`；遇玩家 Ready → 暂停，
     `should_pause_for_input()` 返回 True，控制权交还引擎。

【工程补白】（任务书未逐字拍死、实现需收敛处，显式标注供审查）：
  1. 单位抽象：调度器不持有战斗数值，只持有「调度视图」——actor_id / side / effective_speed /
     is_player。速度变化经 `update_speed()` 触发 重新入队 + generation 递增。
  2. 先手随机注入：本层不消费随机；首轮「先手判定」等随机因素经 `initiative_fn` 注入
     （签名 `fn(actors, seed) -> {actor_id: ready_offset}`），未注入 → 全 0 偏移（确定性）。
  3. 暂停判定：默认「玩家方 units 的 ready 时刻到达即暂停」；`is_player` 由 push 时给出。
     队列为空 → `should_pause_for_input()` True（无后续可自动推进，须引擎介入）。
  4. 死亡：`mark_dead()` 立即移除调度视图 + bump generation；已出队旧票回流被丢弃。
  5. 事件派发顺序以 ctb_rules.EVENT_ORDER 为逻辑序；一次行动链路
     ACTOR_READY → ACTOR_TURN_START → BEFORE_ACTION → ACTION_RESOLVE → AFTER_ACTION →
     ACTOR_TURN_END 由调度器在 resolve 时按序 emit。
  6. 队列重建 `rebuild()`：保留存活单位，按新 timestamp（或保留原 ready）重排 + bump generation；
     用于加速 / 减速 / 规则变更后的整体重排。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.core.ctb_rules import (
    CTB_TIEBREAK_RULE,
    ActionBatchReport,
    CtbEvent,
    CtbRuleConfig,
    build_tiebreak_key,
    next_ready,
    resolve_rule_config,
)

__all__ = [
    "CtbTicket",
    "CtbActorView",
    "CTBScheduler",
]

_logger = logging.getLogger("qbot_rpg.ctb_scheduler")


# ---------------------------------------------------------------------------
# 一、调度票据（带 generation，防旧票回流污染）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CtbTicket:
    """一次 ready 的调度票据。

    票据在 actor ready 时签发；携带 generation。状态变更（死亡 / 速度变化 / 规则变更 /
    队列重建）递增 generation 后，旧票据回流 `resolve_ticket()` 会被识别并丢弃。

    字段：
      actor_id:    单位稳定标识
      generation:  签发时的调度代数
      ready_at:    该票对应的 ready 时刻
      seq:         全局签发序号（同刻同速同阵营时 FIFO 兜底；确定性）
      side:        阵营（player/enemy）
      effective_speed: 签发时的有效速度（tie-break 用）
    """

    actor_id: str
    generation: int
    ready_at: float
    seq: int
    side: str = "enemy"
    effective_speed: float = 0.0


# ---------------------------------------------------------------------------
# 二、单位调度视图（不含战斗数值；引擎侧持有真实单位）
# ---------------------------------------------------------------------------
@dataclass
class CtbActorView:
    """调度器持有的**单位调度视图**（最小投影，非战斗单位本体）。

    字段：
      actor_id:        稳定标识（tie-break 字典序键）
      side:            阵营（player/enemy；未知走兜底优先级）
      effective_speed: 有效速度（含增益/减益；下限保护由公式层负责）
      is_player:       是否玩家控制（决定「可暂停输入式」语义）
      alive:           存活标记（死亡后不再入队）
      next_ready:      当前行动条 ready 时刻
      ticket:          当前票据（None → 尚未 ready）
      meta:            透传元数据（引擎自用，例如 hp/技能；调度器不解释）
    """

    actor_id: str
    side: str = "enemy"
    effective_speed: float = 0.0
    is_player: bool = False
    alive: bool = True
    next_ready: float = 0.0
    ticket: Optional[CtbTicket] = None
    meta: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 三、调度器主体
# ---------------------------------------------------------------------------
class CTBScheduler:
    """CTB 逻辑时间调度器（无真实 timer；逻辑时间完全由本类推进）。

    用法骨架（引擎侧）::

        ctb = CTBScheduler(config=settings)
        ctb.subscribe(CtbEvent.ACTOR_READY, on_ready)
        ctb.push_actor("p1", side="player", effective_speed=100, is_player=True)
        ctb.push_actor("e1", side="enemy", effective_speed=75)
        ctb.start()                        # emit BATTLE_START + 首轮 ready
        while not ctb.finished:
            if ctb.should_pause_for_input():
                break                      # 交还控制权给引擎/玩家
            event = ctb.advance_to_next_ready()   # NPC 自动推进
            ...
    """

    def __init__(
        self,
        config: Any = None,
        initiative_fn: Optional[Callable[[List[CtbActorView], Any], Mapping[str, float]]] = None,
        seed: Any = None,
        npc_resolver: Optional[Callable[[str, int], Any]] = None,
    ) -> None:
        """构造调度器（纯内存，无 IO / 无 timer）。

        :param config: 规则配置（CtbRuleConfig / settings Mapping / None）
        :param initiative_fn: 首轮先手偏置注入接口（本层不消费随机，随机归引擎）；
            签名 fn(actors, seed) -> {actor_id: ready_offset}；None → 全 0 偏移
        :param seed: 随机种子（仅透传给 initiative_fn，调度器自身不使用）
        :param npc_resolver: **NPC 行动执行回调**（2026-09-10 补：修复「NPC 链只派发
            事件、不执行行动」的生产缺口）。签名 `fn(actor_id, action_seq) -> recovery`。
            调度器在 NPC 走到 ACTION_RESOLVE 位点时调用它，由**引擎**侧完成真实行动
            （MonsterAI 决策 + 伤害/效果结算），并把该行动的 recovery 回传用于重签票据。
            本层不感知战斗数值，保持「调度器只调度、引擎才执行」的分层契约。
            None → 仅派发事件（向后兼容：单测可只验事件序，不碰引擎）。
        """
        self._rule: CtbRuleConfig = resolve_rule_config(config)
        self._initiative_fn = initiative_fn
        self._seed = seed
        self._npc_resolver = npc_resolver

        self._actors: Dict[str, CtbActorView] = {}
        self._queue: List[CtbActorView] = []          # 待 ready 队列（含已 ready 待消费）
        self._time: float = 0.0                        # 逻辑时间（唯一推进源）
        self._generation: int = 0                      # 调度代数（票据失效基准）
        self._seq: int = 0                             # 全局签发序号
        self._started: bool = False
        self._finished: bool = False
        self._events: List[Dict[str, Any]] = []        # 未消费事件缓冲（时序确定）
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._batch: Optional[ActionBatchReport] = None
        self._paused: bool = False
        self._paused_actor_id: Optional[str] = None
        self._stale_dropped: int = 0                   # 旧 generation 丢弃计数（审计）
        self._action_seq: int = 0
        _logger.debug("CTBScheduler 初始化：rule=%s seed=%s", self._rule, self._seed)

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------
    @property
    def battle_time(self) -> float:
        """当前逻辑时间（= BATTLE_TIME_ADVANCE 累积；无真实时钟）。"""
        return self._time

    @property
    def current_time(self) -> float:
        """battle_time 别名（语义等价）。"""
        return self._time

    @property
    def generation(self) -> int:
        """当前调度代数（票据失效基准）。"""
        return self._generation

    @property
    def finished(self) -> bool:
        """战斗是否已结束（BATTLE_END 已派发）。"""
        return self._finished

    @property
    def action_seq(self) -> int:
        """已派发的行动序号（CTB 下替代旧「回合数」的行动计数源）。"""
        return self._action_seq

    @property
    def stale_dropped(self) -> int:
        """被丢弃的旧 generation 票据计数（审计/测试断言用）。"""
        return self._stale_dropped

    @property
    def tiebreak_rule(self) -> str:
        """冻结的 tie-break 规则文本（供审计引用）。"""
        return CTB_TIEBREAK_RULE

    # ------------------------------------------------------------------
    # 事件订阅 / 消费
    # ------------------------------------------------------------------
    def subscribe(self, event: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """订阅某类事件（同事件多订阅按注册序回调；非法入参静默忽略）。

        :param event: 事件名（建议用 CtbEvent 常量）
        :param callback: 回调 fn(payload)
        """
        try:
            if not isinstance(event, str) or not callable(callback):
                _logger.warning("subscribe 忽略非法入参：event=%r cb=%r", event, callback)
                return
            self._subscribers.setdefault(event, []).append(callback)
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("subscribe 失败：event=%r", event)

    def drain_events(self) -> List[Dict[str, Any]]:
        """取出并清空未消费事件缓冲（返回按时序冻结的副本；可复现）。

        :return: 事件 payload 列表（浅拷贝顶层，防外部改动内部缓冲）
        """
        try:
            out = [dict(e) for e in self._events]
            self._events = []
            return out
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("drain_events 失败，返回空列表")
            return []

    def peek_events(self) -> List[Dict[str, Any]]:
        """查看（不清空）事件缓冲。"""
        return [dict(e) for e in self._events]

    def _emit(self, event: str, actor_id: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        """派发事件：写缓冲 + 回调订阅者（回调异常不阻断主流程）。

        :param event: 事件名
        :param actor_id: 相关单位（可 None）
        :param extra: 附加字段（并入 payload）
        :return: 事件 payload（同时已入缓冲）
        """
        payload: Dict[str, Any] = {
            "event": event,
            "time": self._time,
            "generation": self._generation,
            "actor_id": actor_id,
        }
        try:
            payload.update(extra)
        except Exception:  # pragma: no cover - extra 异常兜底
            _logger.exception("事件附加字段合并失败：%s", event)
        self._events.append(payload)
        for cb in list(self._subscribers.get(event, ())):
            try:
                cb(payload)
            except Exception:  # 兜底：订阅者异常不得阻断调度
                _logger.exception("事件订阅者异常：event=%s cb=%r", event, cb)
        return payload

    # ------------------------------------------------------------------
    # 队列构建
    # ------------------------------------------------------------------
    def push_actor(
        self,
        actor_id: Any,
        side: str = "enemy",
        effective_speed: Any = 0,
        is_player: bool = False,
        ready_offset: Any = None,
        meta: Optional[Mapping[str, Any]] = None,
    ) -> Optional[CtbActorView]:
        """登记一个单位并签发首张票据（入队）。

        :param actor_id: 稳定标识（重复 id → 覆盖并重签，bump generation）
        :param side: 阵营（player/enemy）
        :param effective_speed: 有效速度
        :param is_player: 是否玩家控制
        :param ready_offset: 首轮 ready 偏置（None → 0；可由 initiative_fn 提供）
        :param meta: 透传元数据
        :return: 新建的调度视图（非法入参 → None）
        """
        try:
            view = CtbActorView(
                actor_id=str(actor_id),
                side=str(side),
                effective_speed=_to_float(effective_speed, 0.0),
                is_player=bool(is_player),
                meta=dict(meta) if isinstance(meta, Mapping) else {},
            )
            if view.actor_id in self._actors:
                _logger.debug("push_actor 覆盖已存在单位：%s（bump generation）", view.actor_id)
                self.bump_generation("actor_reset")
            self._actors[view.actor_id] = view
            offset = _to_float(ready_offset, 0.0)
            self._enqueue(view, base_time=self._time + offset)
            self._rebuild_queue()
            return view
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("push_actor 失败：actor_id=%r", actor_id)
            return None

    def _enqueue(
        self,
        view: CtbActorView,
        base_time: Optional[float] = None,
        recovery: Optional[Any] = None,
    ) -> None:
        """为某单位计算下一次 ready 并签发票据。

        :param view: 调度视图
        :param base_time: 起算时间（None → 当前 ready/时间）
        :param recovery: 本次行动的行动恢复值；None → 规则默认 default_recovery。
            引擎在每次行动结算后传入实际 action 的 recovery（普攻 100 / 重技能 150…），
            这是 CTB「行动代价」的唯一注入点（P0：per-action recovery）。
        """
        base = self._time if base_time is None else base_time
        rec = self._rule.default_recovery if recovery is None else recovery
        action = {"recovery": rec}
        view.next_ready = next_ready(base, action, view.effective_speed, self._rule)
        self._seq += 1
        view.ticket = CtbTicket(
            actor_id=view.actor_id,
            generation=self._generation,
            ready_at=view.next_ready,
            seq=self._seq,
            side=view.side,
            effective_speed=view.effective_speed,
        )

    def _rebuild_queue(self) -> None:
        """按冻结 tie-break 规则重排待 ready 队列（存活且未消费的单位）。"""
        alive = [v for v in self._actors.values() if v.alive]
        # 需要 ready 的单位 = 已签发票据（ticket 为 None 表示本拍已消费、待重签）
        pending = [v for v in alive if v.ticket is not None]
        pending.sort(
            key=lambda v: build_tiebreak_key(
                v.next_ready, v.effective_speed, v.side, v.actor_id
            ) + (v.ticket.seq if v.ticket else 0,)
        )
        self._queue = pending

    # ------------------------------------------------------------------
    # generation 票据失效机制
    # ------------------------------------------------------------------
    def bump_generation(self, reason: str = "") -> int:
        """递增调度代数，使所有在途旧票失效。

        触发场景：单位死亡 / 加速减速 / CTB 规则变更 / 队列重建。

        :param reason: 触发原因（审计日志）
        :return: 新的 generation
        """
        self._generation += 1
        _logger.debug("bump_generation -> %d（reason=%s）", self._generation, reason)
        return self._generation

    def invalidate_ticket(self, reason: str = "state_change") -> int:
        """bump_generation 的语义别名（状态变更使票据失效）。"""
        return self.bump_generation(reason)

    def is_ticket_stale(self, ticket: Any) -> bool:
        """判断票据是否为旧 generation（True → 必须丢弃）。"""
        try:
            if not isinstance(ticket, CtbTicket):
                return True
            return ticket.generation != self._generation
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("is_ticket_stale 失败，按失效处理")
            return True

    def resolve_ticket(self, ticket: Any) -> bool:
        """票据回流消费入口：校验 generation，旧票丢弃且不污染队列。

        :param ticket: 待消费票据（应为当前 generation）
        :return: True = 票有效（消费成功）；False = 旧票/非法票（已丢弃）
        """
        try:
            if self.is_ticket_stale(ticket):
                self._stale_dropped += 1
                _logger.debug(
                    "丢弃旧票据：actor=%s gen=%s（当前 gen=%s）",
                    getattr(ticket, "actor_id", None),
                    getattr(ticket, "generation", None),
                    self._generation,
                )
                return False
            return True
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("resolve_ticket 失败，按丢弃处理")
            self._stale_dropped += 1
            return False

    # ------------------------------------------------------------------
    # 逻辑时间推进
    # ------------------------------------------------------------------
    def start(self) -> None:
        """开始战斗：派发 BATTLE_START；应用首轮先手偏置并重排队列。"""
        if self._started:
            return
        self._started = True
        self._emit(CtbEvent.BATTLE_START, time=self._time)
        self._apply_initiative()
        self._rebuild_queue()
        self._refresh_pause_state()

    def _apply_initiative(self) -> None:
        """应用注入的首轮先手偏置（initiative_fn；未注入 → 全 0，确定性）。"""
        if self._initiative_fn is None:
            return
        try:
            actors = list(self._actors.values())
            offsets = self._initiative_fn(actors, self._seed) or {}
            for view in actors:
                off = _to_float(offsets.get(view.actor_id), 0.0)
                if off:
                    view.next_ready += off
                    if view.ticket is not None:
                        view.ticket = CtbTicket(
                            actor_id=view.actor_id,
                            generation=view.ticket.generation,
                            ready_at=view.next_ready,
                            seq=view.ticket.seq,
                            side=view.side,
                            effective_speed=view.effective_speed,
                        )
        except Exception:  # 兜底：先手注入异常不阻断（退化为 0 偏置）
            _logger.exception("initiative_fn 执行异常，退化为 0 偏置")

    def peek_next(self) -> Optional[CtbActorView]:
        """查看下一名将 ready 的单位（不出队、不推进时间）。"""
        self._rebuild_queue()
        return self._queue[0] if self._queue else None

    def pop_next(self) -> Optional[CtbActorView]:
        """取出下一名将 ready 的单位（不推进时间；调用方负责 emit 链路）。

        :return: 队首单位视图（空队列 → None）
        """
        self._rebuild_queue()
        if not self._queue:
            return None
        return self._queue[0]

    def advance_to_next_ready(self) -> Optional[Dict[str, Any]]:
        """推进逻辑时间到下一个 ready，派发完整行动链路事件。

        流程（顺序确定，可复现）：
          1. 取最小 next_ready 单位（冻结 tie-break）
          2. 若目标时刻 > 当前时间 → 推进 `_time` 并派发 BATTLE_TIME_ADVANCE
          3. 派发 ACTOR_READY
          4. 若为玩家 → 暂停（return ACTOR_READY 事件，等引擎 resolve）
             若为 NPC → 自动派发完整链路事件并重签票据（return ACTOR_TURN_END 事件）

        :return: 本次推进的关键事件 payload（空队列/已结束 → None）
        """
        if self._finished:
            return None
        try:
            self._rebuild_queue()
            if not self._queue:
                self._refresh_pause_state()
                return None

            view = self._queue[0]
            if view.ticket is None or self.is_ticket_stale(view.ticket):
                # 票据失效：跳过该单位并重签（不消费旧票时间）
                self.resolve_ticket(view.ticket)
                self._resign_after_skip(view)
                self._rebuild_queue()
                return self.advance_to_next_ready()

            # 1) 时间推进（若目标在未来）
            if view.next_ready > self._time:
                delta = view.next_ready - self._time
                self._time = view.next_ready
                self._emit(
                    CtbEvent.BATTLE_TIME_ADVANCE,
                    actor_id=view.actor_id,
                    delta=delta,
                    battle_time=self._time,
                )
            elif view.next_ready < self._time:
                # 理论不发生（ready 单调）；防御：钳到当前时间
                view.next_ready = self._time

            # 2) 消费票据 → 出队
            self.resolve_ticket(view.ticket)
            self._action_seq += 1
            action_seq = self._action_seq
            view.next_ready = self._time
            view.ticket = None

            # 3) ACTOR_READY
            ready_evt = self._emit(
                CtbEvent.ACTOR_READY,
                actor_id=view.actor_id,
                side=view.side,
                is_player=view.is_player,
                action_seq=action_seq,
            )
            self._begin_batch_if_needed(view)

            if view.is_player:
                # 玩家 ready → 暂停，交还控制权
                self._paused = True
                self._paused_actor_id = view.actor_id
                if self._batch is not None:
                    self._batch.mark_pause(view.actor_id, view.next_ready)
                    self._batch.end_time = self._time
                return ready_evt

            # NPC → 自动推进完整链路
            return self._auto_resolve_npc(view, action_seq)
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("advance_to_next_ready 失败，返回 None")
            return None

    def _resign_after_skip(self, view: CtbActorView) -> None:
        """票据失效跳过后重签该单位（不推进时间；防死循环）。"""
        try:
            view.next_ready = self._time + max(self._rule.min_speed, 1e-9)
            self._enqueue(view, base_time=view.next_ready)
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("_resign_after_skip 失败：%s", view.actor_id)

    def _auto_resolve_npc(
        self, view: CtbActorView, action_seq: int, recovery: Optional[Any] = None
    ) -> Dict[str, Any]:
        """NPC 连锁自动推进：派发 TURN_START → BEFORE → RESOLVE → AFTER → TURN_END。

        2026-09-10 补（生产缺口修复）：在 ACTION_RESOLVE 位点调用引擎注入的
        `npc_resolver(actor_id, action_seq)`，由**引擎**执行该 NPC 的真实行动
        （MonsterAI 决策 → 命中/伤害/效果结算 → 写 action_record）。调度器自身
        不碰战斗数值；未注入 resolver 时退化为纯派发（旧行为，单测可用）。

        :param view: NPC 调度视图
        :param action_seq: 本次行动序号
        :param recovery: 本次行动恢复值（None → 规则默认）；决定下次 ready
        :return: ACTOR_TURN_END 事件 payload
        """
        self._emit(CtbEvent.ACTOR_TURN_START, actor_id=view.actor_id, action_seq=action_seq)
        self._emit(CtbEvent.BEFORE_ACTION, actor_id=view.actor_id, action_seq=action_seq)
        # ACTION_RESOLVE 位点：引擎侧执行真实行动（唯一执行入口）
        _rec = recovery
        if self._npc_resolver is not None:
            try:
                _r = self._npc_resolver(str(view.actor_id), int(action_seq))
                if _r is not None:
                    _rec = _r
            except Exception:  # pragma: no cover - 兜底不崩（NPC 执行异常不阻断时间轴）
                _logger.exception("npc_resolver 执行失败：actor=%s", view.actor_id)
        self._emit(CtbEvent.ACTION_RESOLVE, actor_id=view.actor_id, action_seq=action_seq)
        self._emit(CtbEvent.AFTER_ACTION, actor_id=view.actor_id, action_seq=action_seq)
        end_evt = self._emit(
            CtbEvent.ACTOR_TURN_END, actor_id=view.actor_id, action_seq=action_seq
        )
        if self._batch is not None:
            self._batch.add(
                {
                    "actor_id": view.actor_id,
                    "side": view.side,
                    "event": CtbEvent.ACTOR_TURN_END,
                    "time": self._time,
                    "action_seq": action_seq,
                }
            )
            self._batch.end_time = self._time

        # NPC 行动中被击杀 → 其 next_ready / 重签交给死亡同步处理（不再重签）
        if not view.alive:
            return end_evt

        # 重签该 NPC 的下一次 ready（进入下一轮；recovery 决定行动代价）
        self._enqueue(view, base_time=self._time, recovery=_rec)
        self._rebuild_queue()
        self._refresh_pause_state()
        return end_evt

    def complete_player_action(self, recovery: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """玩家行动结算完成后由引擎调用：派发本拍剩余链路并解除暂停。

        引擎在玩家 ready 暂停后执行真实行动，再调用本接口把链路走完
        （ACTOR_TURN_START → BEFORE → RESOLVE → AFTER → TURN_END），并重签票据。

        :param recovery: 本次玩家行动的行动恢复值（普攻 100 / 重技能 150…）；
            None → 规则默认 default_recovery。这是玩家侧行动代价的注入点。
        :return: ACTOR_TURN_END 事件 payload（无暂停中玩家 → None）
        """
        try:
            if not self._paused or self._paused_actor_id is None:
                return None
            view = self._actors.get(self._paused_actor_id)
            action_seq = self._action_seq
            if view is not None:
                self._emit(
                    CtbEvent.ACTOR_TURN_START, actor_id=view.actor_id, action_seq=action_seq
                )
                self._emit(
                    CtbEvent.BEFORE_ACTION, actor_id=view.actor_id, action_seq=action_seq
                )
                self._emit(
                    CtbEvent.ACTION_RESOLVE, actor_id=view.actor_id, action_seq=action_seq
                )
                self._emit(CtbEvent.AFTER_ACTION, actor_id=view.actor_id, action_seq=action_seq)
                end_evt = self._emit(
                    CtbEvent.ACTOR_TURN_END, actor_id=view.actor_id, action_seq=action_seq
                )
                if view.alive:
                    self._enqueue(view, base_time=self._time, recovery=recovery)
            else:
                end_evt = None
            self._paused = False
            self._paused_actor_id = None
            self._finish_batch_if_closed()
            self._rebuild_queue()
            self._refresh_pause_state()
            return end_evt
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("complete_player_action 失败，返回 None")
            return None

    # ------------------------------------------------------------------
    # 可暂停输入式 CTB 语义
    # ------------------------------------------------------------------
    def _begin_batch_if_needed(self, view: CtbActorView) -> None:
        """NPC 行动开始一个合并上报批次（玩家行动不开启批次）。"""
        if not view.is_player and self._batch is None:
            self._batch = ActionBatchReport(start_time=self._time, end_time=self._time)

    def _finish_batch_if_closed(self) -> None:
        """暂停解除后关闭当前批次（保留最近一次，供引擎取用后 take_batch 清空）。"""
        if self._batch is not None:
            self._batch.end_time = self._time

    @property
    def current_batch(self) -> Optional[ActionBatchReport]:
        """当前累积的 NPC 行动合并上报（无 → None）。"""
        return self._batch

    def take_batch(self) -> Optional[ActionBatchReport]:
        """取出并清空当前 NPC 行动合并上报（引擎消费一次）。

        :return: ActionBatchReport（无批次 → None）
        """
        batch = self._batch
        self._batch = None
        return batch

    def should_pause_for_input(self) -> bool:
        """查询「当前是否应该暂停并请求玩家输入」。

        语义：玩家 ready 已到达（`_paused`）或队列已空（无后续可自动推进）→ True；
        NPC 连锁可继续自动推进 → False。

        :return: True = 应暂停交还控制权
        """
        try:
            if self._finished:
                return False
            if self._paused:
                return True
            self._rebuild_queue()
            return not self._queue
        except Exception:  # pragma: no cover - 兜底不崩（保守暂停）
            _logger.exception("should_pause_for_input 失败，保守返回 True")
            return True

    @property
    def paused(self) -> bool:
        """是否处于玩家输入暂停态。"""
        return self._paused

    @property
    def paused_actor_id(self) -> Optional[str]:
        """触发暂停的玩家 actor id（未暂停 → None）。"""
        return self._paused_actor_id

    def _refresh_pause_state(self) -> None:
        """刷新暂停标记：队列空且未结束 → 视为需介入（无自动推进对象）。"""
        self._rebuild_queue()
        if not self._queue and not self._finished:
            _logger.debug("队列为空，等待引擎介入（无后续自动推进）")

    # ------------------------------------------------------------------
    # 状态变更（触发 generation 递增）
    # ------------------------------------------------------------------
    def update_speed(self, actor_id: Any, effective_speed: Any) -> bool:
        """更新单位有效速度（加速/减速）：重排 + bump generation。

        旧票据作废；新 ready 基于当前时间按新速度重算。

        :param actor_id: 单位标识
        :param effective_speed: 新有效速度
        :return: True = 更新成功
        """
        view = self._actors.get(str(actor_id))
        if view is None:
            _logger.warning("update_speed 未找到单位：%s", actor_id)
            return False
        try:
            view.effective_speed = _to_float(effective_speed, view.effective_speed)
            self.bump_generation("speed_change")
            if view.alive:
                self._enqueue(view, base_time=self._time)
            self._rebuild_queue()
            return True
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("update_speed 失败：%s", actor_id)
            return False

    def mark_dead(self, actor_id: Any) -> bool:
        """标记单位死亡：移出队列 + bump generation（旧票回流必被丢弃）。

        :param actor_id: 死亡单位标识
        :return: True = 单位存在且转为死亡
        """
        view = self._actors.get(str(actor_id))
        if view is None:
            return False
        try:
            view.alive = False
            view.ticket = None
            self.bump_generation("actor_death")
            self._emit(CtbEvent.ACTOR_DEATH, actor_id=view.actor_id)
            self._rebuild_queue()
            self._refresh_pause_state()
            if not any(v.alive for v in self._actors.values()) or self._all_one_side_dead():
                self.finish()
            return True
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("mark_dead 失败：%s", actor_id)
            return False

    def _all_one_side_dead(self) -> bool:
        """判定是否某一方全灭（player / enemy 任一侧存活数为 0）。"""
        sides: Dict[str, int] = {}
        for v in self._actors.values():
            if v.alive:
                sides[v.side] = sides.get(v.side, 0) + 1
        if not sides:
            return True
        return len(sides) < 2 and len(self._actors) > 1

    def change_rules(self, overrides: Optional[Mapping[str, Any]] = None) -> None:
        """变更 CTB 规则（recovery / speed_reference / min_speed / action_delay）。

        规则变更使所有在途票据失效（bump generation），随后全体按新规则重算 ready。

        :param overrides: 规则覆盖（None → 无变化，仅 bump）
        """
        try:
            self._rule = self._rule.with_overrides(overrides)
            self.bump_generation("rule_change")
            for view in self._actors.values():
                if view.alive:
                    self._enqueue(view, base_time=self._time)
            self._rebuild_queue()
            _logger.debug("change_rules: %s", self._rule)
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("change_rules 失败")

    def finish(self) -> None:
        """结束战斗：派发 BATTLE_END（幂等）。"""
        if self._finished:
            return
        self._finished = True
        self._emit(CtbEvent.BATTLE_END, time=self._time)
        _logger.debug("BATTLE_END at time=%.4f seq=%d", self._time, self._action_seq)

    # ------------------------------------------------------------------
    # 可复现性 / 快照
    # ------------------------------------------------------------------
    def state_signature(self) -> Tuple[Any, ...]:
        """计算调度器状态签名（确定性；用于复现性断言/等价比较）。

        :return: 元组签名（时间 / 代数 / 行动序号 / 队列 actor 序）
        """
        try:
            self._rebuild_queue()
            return (
                round(self._time, 6),
                self._generation,
                self._action_seq,
                tuple(v.actor_id for v in self._queue),
            )
        except Exception:  # pragma: no cover - 兜底不崩
            _logger.exception("state_signature 失败，返回空签名")
            return ()

    def to_snapshot(self) -> Dict[str, Any]:
        """导出调度状态（JSON 友好；供引擎落快照，注意：本项目 CTB 为删档口径）。"""
        return {
            "time": self._time,
            "generation": self._generation,
            "seq": self._seq,
            "action_seq": self._action_seq,
            "started": self._started,
            "finished": self._finished,
            "stale_dropped": self._stale_dropped,
            "actors": [
                {
                    "actor_id": v.actor_id,
                    "side": v.side,
                    "effective_speed": v.effective_speed,
                    "is_player": v.is_player,
                    "alive": v.alive,
                    "next_ready": v.next_ready,
                }
                for v in self._actors.values()
            ],
        }

    def actors(self) -> List[CtbActorView]:
        """返回全部单位视图（拷贝列表，防外部改内部容器）。"""
        return list(self._actors.values())

    def get_actor(self, actor_id: Any) -> Optional[CtbActorView]:
        """按 id 取单位视图（无 → None）。"""
        return self._actors.get(str(actor_id))


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _to_float(value: Any, default: float) -> float:
    """宽松数值化：非法 / None / bool → default（调度层不抛错）。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
