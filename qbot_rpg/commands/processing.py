"""指令处理入口：幂等键完整链路 + per-player 串行队列（M6 批2·路A · D2 幂等事务三件套的一半）。

依据（权威契约）：
  - docs/细化/细化_M6_幂等事务三件套.md（M6 子细化 D2）：
      §一 IDEM-1~8 + TC-IDEM-01~06（幂等载体=指令处理入口非发送出口 / 键三元组 /
         只查不插 / 同事务提交 / 命中幂等返回 / 失败整单回滚 / 7 天清理 /
         settle_exit_idempotent 实装）
      §三 POOL-1~6 + TC-POOL-01~04（per-player 串行队列：粒度=玩家 / 事务外排队 /
         幂等查重入队前 / 超时失败处理 / 事件循环集成 / 崩溃断线）
      §四 承接 P 项（【批5B】P0-1 / 【批5A】P1-1）
  - docs/细化/细化_M6_接线闭环总纲.md §七 ADR-05（message_id 幂等键载体 = 指令处理入口，
    发送出口仅是崩溃注入点非幂等载体）、ADR-12（三件套前置接线 ①指令入口幂等键同事务
    ③per-player 串行队列）
  - 细化_4a_存储层契约.md §四 IDEM-1~5 / §3.2 F3（事务模板：幂等键与业务写同事务）
  - 定稿《开发规则文档.md》L319（回复前崩溃 → 不双结算）/ L1609（指令处理以 message_id
    做幂等键防重复结算）

职责：装配层核心——**纯 asyncio、零 NoneBot、零 IO 于自身**的指令处理入口。handler 为
业务闭包（由装配层提供，闭包已捕获解析后命令 + 已构建 ctx，含事务内业务写：
读玩家/校验/扣减 → tx.upsert_player 等）。本模块不依赖 on_command；批次6/7 装配层在
指令入口注入 repo/queue 并驱动。

【工程补白 · 显式标注】（D2 §五 决策记录纪律：新决策须标注）
  1) handler 契约：`handler(tx) -> dict`，返回至少含 {ok: bool, message: str}。
     **ok=True 才写幂等键**（IDEM-4 语义延伸：业务成功才落键；业务拒绝如「余额不足」
     不落键，重发可重试，业务级幂等兜底各引擎承担）。异常 → tx() 整体 ROLLBACK（IDEM-6）。
  2) result_hash（F-IDEM-05）：取结果 message 的 SHA-256 前 16 位十六进制摘要。
  3) 发送出口 sender：可选闭包 `sender(result) -> None`；COMMIT 后由消费者调用；
     发送失败不阻塞队列（POOL-6），幂等键已落兜底（TC-IDEM-05「回复前崩溃不双结算」）。
     幂等重放（send=False）不发送（IDEM-5 业务零执行、零发送）。
  4) 私聊 group_id 取 "dm" 哨兵兜底（D2 §1.4 边界异常：键三元组缺失场景）。
  5) 队列任务异常 → 捕获返回失败原因人话消息（不静默吞、不阻塞后续同玩家指令，POOL-4），
     事务已由 tx() 整体 ROLLBACK（IDEM-6：幂等键与业务写同落同不落，无孤儿键）。
  6) 权威判定以事务内 tx.idem_exists 为准（D2 §1.4：BEGIN IMMEDIATE 持锁后二次确认，
     防排队窗口内先到事务已写键）；入口 idem_claim 是快速路径（POOL-3 入队前查重）。
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from qbot_rpg.storage.repository import IdemKey, RepoTransaction, Repository

__all__ = [
    "DM_GROUP_SENTINEL",
    "TPL_IDEMPOTENT_REPLAY",
    "Handler",
    "Sender",
    "QueueItem",
    "PerPlayerQueue",
    "process_message",
]

# 私聊/缺失 group_id 哨兵（D2 §1.4 边界异常；附录 A：装配层落地时统一在 ctx 构建处收敛）
DM_GROUP_SENTINEL: str = "dm"

# 幂等重放文案（IDEM-5：回放 result_hash 摘要或「该指令已处理」；本实现取后者）
TPL_IDEMPOTENT_REPLAY: str = "该指令已处理，请勿重复发送"

# 业务闭包：事务内业务写 + 返回 {ok, message, ...}（闭包捕获解析后命令 + 已构建 ctx，F-POOL-04）
Handler = Callable[[RepoTransaction], Awaitable[Dict[str, Any]]]
# 发送出口：COMMIT 后发送回复（批次6/7 装配注入；失败不阻塞队列 POOL-6）
Sender = Callable[[Dict[str, Any]], Awaitable[None]]


def _result_hash(message: object) -> str:
    """F-IDEM-05 result_hash：结果摘要（SHA-256 前 16 位十六进制）。"""
    return hashlib.sha256(str(message).encode("utf-8")).hexdigest()[:16]


def _replay_reply(command: str, *, queued: bool) -> Dict[str, Any]:
    """幂等重放结果（IDEM-5：业务零执行、零发送）。queued 区分入口命中（未入队）与队列内二次确认命中。"""
    return {
        "ok": False,
        "idempotent": True,
        "queued": queued,
        "send": False,
        "command": command,
        "message": TPL_IDEMPOTENT_REPLAY,
    }


def _failure_reply(command: str, exc: BaseException) -> Dict[str, Any]:
    """队列任务失败结果（POOL-4：失败原因人话消息；事务已 ROLLBACK，IDEM-6 无孤儿键）。"""
    return {
        "ok": False,
        "idempotent": False,
        "queued": True,
        "send": True,
        "command": command,
        "message": f"指令处理失败（已回滚，可重试）：{exc}",
        "error": str(exc),
    }


@dataclass
class QueueItem:
    """per-player 队列条目（D2 §三 F-POOL-01~05；进程内存，随进程丢失 POOL-6）。

    字段：player_qid（队列键 F-POOL-01）、idem_key（含 message_id/group_id/command，
    事务内写键用 F-POOL-02/03）、handler（业务闭包 F-POOL-04）、enqueued_at（入队时刻
    F-POOL-05）、sender（发送出口，可选）、future（消费完成后填充结果 dict）。
    """

    player_qid: str
    idem_key: IdemKey
    handler: Handler
    sender: Optional[Sender] = None
    enqueued_at: float = field(default_factory=time.monotonic)
    future: Optional[asyncio.Future] = None


class PerPlayerQueue:
    """per-player 串行队列（D2 §三 POOL-1~6）。

    粒度 = 玩家（player_qid）：每玩家一条 FIFO asyncio.Queue + 单消费者任务；
    同玩家指令按到达顺序处理（POOL-1，防乱序/双结算），不同玩家队列互不阻塞
    （POOL-2 事务外排队：同玩家必然串行，事务冲突面只在世界资源）。
    注（工程补白）：SQLite 单写连接锁（connection.py _write_lock，SCHEMA-1）串行化
    DB 事务体，「不同玩家并行」落地为 **per-player 队列隔离**——B 永不排在 A 队列后、
    独立消费者驱动、enqueue 不等待 A 消费；事务级并发由 BEGIN IMMEDIATE + 单写队列保证安全。
    幂等键查重在入队前由 process_message 承担（POOL-3：命中 → 幂等返回不入队）。
    队列任务异常 → 捕获返回失败原因人话消息，不阻塞后续同玩家指令（POOL-4）。
    asyncio 单事件循环内 per-player asyncio.Queue + 单消费者任务（POOL-5，
    装配层批次6/7 在指令入口注入并驱动）。
    崩溃/断线：队列为内存态随进程丢失；幂等键落 DB（已落）→ 重发幂等返回兜底（POOL-6）。
    边界异常：不设队列长度上限（D2 §3.4 工程补白：消息量小，排队即幂等安全的串行化）。
    """

    def __init__(self, repo: Repository) -> None:
        self._repo = repo
        self._queues: Dict[str, "asyncio.Queue[QueueItem]"] = {}
        self._consumers: Dict[str, asyncio.Task] = {}
        self._closed = False

    async def enqueue(self, item: QueueItem) -> asyncio.Future:
        """入队（事务外排队 POOL-2）。返回消费完成后的结果 Future。

        每玩家首条入队时拉起单消费者任务；消费者队列空后自行退出，下次入队重新拉起
        （单事件循环内无并发 put 竞态：消费者空检 + return 为同步块，见 _run_consumer）。
        """
        if self._closed:
            raise RuntimeError("PerPlayerQueue 已关闭")
        q = self._queues.get(item.player_qid)
        if q is None:
            q = asyncio.Queue()
            self._queues[item.player_qid] = q
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        item.future = fut
        await q.put(item)
        consumer = self._consumers.get(item.player_qid)
        if consumer is None or consumer.done():
            self._consumers[item.player_qid] = asyncio.create_task(
                self._run_consumer(item.player_qid)
            )
        return fut

    def qsize(self, player_qid: str) -> int:
        """待处理队列长度（观测/测试用；不设上限，D2 §3.4）。"""
        q = self._queues.get(player_qid)
        return q.qsize() if q is not None else 0

    def has_consumer(self, player_qid: str) -> bool:
        """该玩家是否已有（或曾拉起）独立消费者任务（观测/测试用：per-player 隔离）。"""
        consumer = self._consumers.get(player_qid)
        return consumer is not None and not consumer.done()

    async def close(self) -> None:
        """关闭：取消全部消费者任务、清空队列（测试/停机用）。"""
        self._closed = True
        for task in self._consumers.values():
            if not task.done():
                task.cancel()
        self._consumers.clear()
        self._queues.clear()

    # ------------------------------------------------------------------
    # 消费者（单消费者顺序消费，POOL-1/5）
    # ------------------------------------------------------------------
    async def _run_consumer(self, player_qid: str) -> None:
        q = self._queues[player_qid]
        while True:
            item = await q.get()
            result = await self._process_one(item)
            if item.future is not None and not item.future.done():
                item.future.set_result(result)
            # 发送出口（IDEM-1：发送仅是崩溃注入点；失败不阻塞队列 POOL-6）
            if result.get("send", True) and result.get("message") and item.sender is not None:
                try:
                    await item.sender(result)
                except Exception:
                    # 回复前崩溃 → 幂等键已落，同 message_id 重发幂等返回（TC-IDEM-05）
                    pass
            q.task_done()
            # 空检 + return 之间无 await：单事件循环下与 enqueue 的 put 不交错；
            # 若 sender 的 await 期间有新入队，此处 empty()=False 继续消费。
            if q.empty():
                return

    async def _process_one(self, item: QueueItem) -> Dict[str, Any]:
        """单指令单事务（F3 模板）：幂等二次确认（权威）→ 业务写 + write_idem_key 同事务。

        IDEM-3/4：tx.idem_exists 为权威判定（BEGIN IMMEDIATE 持锁后二次确认）；
        未处理 → 业务写 + write_idem_key 同一事务 COMMIT；异常 → tx() ROLLBACK（IDEM-6，
        幂等键与业务写同落同不落，无孤儿键 → 重试按全新处理）。
        """
        key = item.idem_key
        if item.handler is None:
            return _failure_reply(key.command, RuntimeError("处理器（handler）未注入"))
        try:
            async with self._repo.tx() as tx:
                # 权威判定：排队窗口内先到事务已写键 → 幂等重放（D2 §1.4）
                if await tx.idem_exists(key):
                    return _replay_reply(key.command, queued=True)
                result = await item.handler(tx)
                if not isinstance(result, dict):
                    result = {"ok": False, "message": f"处理器未返回 dict：{result!r}"}
                if result.get("ok"):
                    await tx.write_idem_key(IdemKey(
                        message_id=key.message_id,
                        group_id=key.group_id,
                        player_qid=key.player_qid,
                        command=key.command,
                        result_hash=_result_hash(result.get("message", "")),
                    ))
                    result["result_hash"] = result.get("result_hash") or _result_hash(
                        result.get("message", "")
                    )
                result.setdefault("idempotent", False)
                result.setdefault("queued", True)
                result.setdefault("command", key.command)
                return result
        except Exception as exc:  # noqa: BLE001 —— 队列任务异常须捕获转人话（POOL-4），不静默吞
            # tx() 已 ROLLBACK（IDEM-6）
            return _failure_reply(key.command, exc)


async def process_message(
    repo: Repository,
    queue: PerPlayerQueue,
    *,
    message_id: str,
    group_id: str,
    player_qid: str,
    command: str,
    handler: Handler,
    sender: Optional[Sender] = None,
) -> Dict[str, Any]:
    """指令处理入口：幂等键完整链路（D2 §一 IDEM-1~6 / POOL-3）。

    ① idem_claim 只读查重（快速路径；命中 → 幂等返回不入队，业务零执行零发送，
       返回 queued=False）
    ② 未命中 → 入队（事务外排队 POOL-2）→ 队列内单事务【业务写 + write_idem_key】
       （tx.idem_exists 二次确认权威判定 IDEM-3/4）→ COMMIT → 发送（IDEM-1 载体=本入口）
    失败 → 整单回滚（IDEM-6，无孤儿键）。

    参数：repo=Repository；queue=PerPlayerQueue（本入口驱动）；message_id/group_id/
    player_qid=幂等键三元组（IDEM-2，group_id 缺失取 "dm" 哨兵兜底）；command=指令名
    （F-IDEM-04）；handler=业务闭包 handler(tx)->dict（捕获解析后命令+ctx）；sender=发送出口
    （可选）。返回统一 {ok, ...} dict。
    """
    if not message_id or not player_qid or not command:
        raise ValueError("message_id / player_qid / command 均必填（幂等键三元组要素）")
    group_id = (group_id or "").strip() or DM_GROUP_SENTINEL
    key = IdemKey(
        message_id=message_id,
        group_id=group_id,
        player_qid=player_qid,
        command=command,
    )
    # ① 入口只读查重（IDEM-3 只查不插；命中 → 幂等返回不入队 POOL-3）
    if await repo.idem_claim(key):
        return _replay_reply(command, queued=False)
    # ② 未命中 → 入队 → 队列内单事务处理（POOL-2）
    item = QueueItem(player_qid=player_qid, idem_key=key, handler=handler, sender=sender)
    fut = await queue.enqueue(item)
    return await fut
