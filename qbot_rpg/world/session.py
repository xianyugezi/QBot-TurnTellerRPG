"""会话管理与并发互斥 SessionManager（M1/M4 设计 · M8 批3 路3A 实装）。

职责（细化_3a §2.1 / §0.1；【框架】L335-345 3.18）：单玩家 1 会话互斥、会话挂起/恢复、
跨群并发互斥——sessions 表以 player_qid 为主键即互斥约束（细化_4a §1.3 SCHEMA-7，
FK → players ON DELETE CASCADE）。M1 接入战斗会话（对局快照 BattleSnapshot）；M4
接入其它会话（炼金/副本等）。

M8 实装依据：
  - docs/m8_contract_核心机制.md §八 B 组 IF-11~19（真实签名）+ §七（调合会话状态机）
    + §10 铁律 3（会话终态幂等：单事务 delete_session + write_idem_key，
    command="settle:{kind}"，调用方不得嵌套 repo.tx()）。
  - 收口裁决 2026-08-29：全部方法 async（repository 全 async，落库硬需求）；
    get_active/acquire/restore 返回 SessionView（视图 dataclass，payload 原样保留）；
    acquire 冲突 → SessionConflictError；构造器注入 repository（bootstrap.py L61 注入）。

会话时长（快照续战/中断恢复，对齐细化_1g3）：战斗会话快照续战语义归 core/battle.py。
零 NoneBot import（3a R1）；key = 玩家 QQ 号（3a D-06），群号仅作来源记录。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Tuple

from qbot_rpg.storage.migrations import utcnow          # 全存储层共用时间戳口径（Z 后缀）
from qbot_rpg.storage.repository import IdemKey, SessionRow

__all__ = ["SessionManager", "SessionConflictError", "SessionView"]

# 结算幂等键 group_id 哨兵：settle_alchemy 不接收指令 group_id，幂等键语义
# (player_qid, settlement_kind, message_id) 不含群（IDEM-8），缺失时以 "dm" 兜底
# （D2 §1.4 边界异常；与 battle_boundary.DM_GROUP_SENTINEL / processing 同值）。
_DM_GROUP_SENTINEL: str = "dm"


@dataclass(frozen=True)
class SessionView:
    """会话视图（收口裁决 2026-08-29 #2）：get_active/acquire/restore 的返回形态。

    字段对齐 sessions 表列（IF-09 SessionRow 语义；IF-03 load_session 6 元组展开）。
    payload 为快照对象/dict **原样保留**（调合会话 = 配方ID+材料链+连锁+特性+触媒+PP+
    步骤 等，§7.1）；现有调用方读 payload 字段（target/turn）经 _bs_field/_safe_call
    兜底 None（缺失安全，不抛异常）。缺失 target/turn 字段时 getattr 缺省 None。
    """

    player_qid: str
    session_type: str
    payload: object
    random_seed: int
    version: int
    created_at: str
    last_active_at: str


class SessionConflictError(Exception):
    """单玩家已有其它会话（领域异常，壳层翻译；3a R4 / IF-16）。"""


def _view_from_row(
    player_qid: str, row: Optional[Tuple[str, object, int, int, str, str]]
) -> Optional[SessionView]:
    """load_session 6 元组 → SessionView（无行 → None）。

    入参 player_qid: 玩家 QQ 号；row: (session_type, payload, random_seed, version,
    created_at, last_active_at) 或 None（IF-03）。出参 SessionView 或 None。
    核心逻辑: 逐字段展开构造成冻结 dataclass 视图（payload 原样保留）。
    """
    if row is None:
        return None
    session_type, payload, random_seed, version, created_at, last_active_at = row
    return SessionView(
        player_qid=player_qid,
        session_type=session_type,
        payload=payload,
        random_seed=random_seed,
        version=version,
        created_at=created_at,
        last_active_at=last_active_at,
    )


def _session_group_id(session: object) -> str:
    """结算幂等键的 group_id：优先会话携带的发起群（origin_group/context.group_id），
    缺失 → "dm" 哨兵兜底（D2 §1.4 边界异常；仿 battle_boundary._session_group_id）。

    入参 session: SessionView 或任意对象/dict（payload 兜底源）。出参 str。
    核心逻辑: 顶层 group_id/origin_group → payload 内 origin_group/group_id →
    payload.context.group_id → 哨兵。
    """
    if isinstance(session, Mapping):
        g = session.get("group_id") or session.get("origin_group")
        payload = session.get("payload")
    else:
        g = getattr(session, "group_id", None) or getattr(session, "origin_group", None)
        payload = getattr(session, "payload", None)
    if g:
        return str(g)
    if isinstance(payload, Mapping):
        g = payload.get("origin_group") or payload.get("group_id")
        if not g:
            ctx = payload.get("context")
            if isinstance(ctx, Mapping):
                g = ctx.get("group_id") or ctx.get("origin_group")
        if g:
            return str(g)
    return _DM_GROUP_SENTINEL


class SessionManager:
    """会话互斥：单玩家 1 会话；挂起/恢复；调合终态幂等结算（M8 批3 路3A 实装）。

    全部方法 async（repository 全 async，落库是硬需求）；构造器注入 repository
    （None 时内部缺省无 repo 状态——读方法防御性缺省，写方法抛 RuntimeError 明示
    装配缺口；生产装配 bootstrap.py L61 已传 repository）。零 NoneBot import。
    """

    def __init__(self, repository: Optional[Any] = None) -> None:
        """构造器：注入 storage repository（鸭子类型，防循环 import；收口裁决 #8）。

        入参 repository: Repository 或 None（提供 load_session/upsert_session/
        delete_session/recycle_scan/idem_claim/tx）。出参 None。核心逻辑: 保存引用；
        None 时读方法防御缺省（get_active/restore → None，recycle → []），写方法
        （acquire/release/suspend/settle_alchemy）抛 RuntimeError 明示未注入。
        """
        self._repository = repository

    def _require_repo(self, method: str) -> Any:
        """取注入仓库；未注入 → RuntimeError（落库硬需求，装配注入点 bootstrap.py L61）。

        入参 method: 调用方法名（错误信息定位）。出参 repository 实例。
        核心逻辑: self._repository 非 None 直返；None → raise RuntimeError 明示
        装配缺口（防 AttributeError 难排查）。
        """
        if self._repository is None:
            raise RuntimeError(
                f"SessionManager.{method} 需要注入 repository（装配注入点 bootstrap.py L61）"
            )
        return self._repository

    async def get_active(self, player_qid: str) -> Optional[SessionView]:
        """读当前会话（IF-13；收口裁决 #2）：load_session → SessionView。

        入参 player_qid: 玩家 QQ 号（sessions 主键）。出参 Optional[SessionView]
        （无活跃会话/仓库缺失 → None，不抛异常——读快照纪律）。
        核心逻辑: repository.load_session(qid)（IF-03，6 元组）→ _view_from_row
        构造成视图；仓库未注入/无 load_session/异常 → None。
        """
        repo = self._repository
        if repo is None:
            return None
        loader = getattr(repo, "load_session", None)
        if not callable(loader):
            return None
        try:
            row = await loader(player_qid)
        except Exception:  # noqa: BLE001 —— 读快照纪律：任何异常 → None（不抛）
            return None
        return _view_from_row(player_qid, row)

    async def acquire(
        self, player_qid: str, session_type: str, payload: Optional[Any] = None
    ) -> SessionView:
        """开会话（IF-11；收口裁决 #3）：已有活跃会话 → SessionConflictError。

        入参 player_qid: 玩家 QQ 号；session_type: 会话类型（"battle"/"alchemy"...）；
        payload: 会话快照（缺省 None → {}）。出参 SessionView（新建会话视图）。
        核心逻辑: ① get_active 已有 → raise SessionConflictError（全局互斥，
        §7.2 / 定稿【炼金】L177「已有一个调合会话进行中」）；② 无 → upsert_session
        （SessionRow，random_seed=0，version=1，created_at/last_active_at=now）→ 返回视图。
        """
        active = await self.get_active(player_qid)
        if active is not None:
            raise SessionConflictError(
                f"玩家 {player_qid} 已有活跃会话（{active.session_type}），拒绝新建"
            )
        repo = self._require_repo("acquire")
        ts = utcnow()
        row = SessionRow(
            player_qid=player_qid,
            session_type=session_type,
            payload=payload if payload is not None else {},
            random_seed=0,
            version=1,
            created_at=ts,
            last_active_at=ts,
        )
        # upsert_session 属 RepoTransaction（repository.py L887，真库冒烟修正 2026-08-29）：
        # 写操作必须经 repo.tx() 事务句柄，Repository 本体无该方法（IF-06 归属勘误）。
        async with repo.tx() as tx:
            await tx.upsert_session(row)
        return SessionView(
            player_qid=player_qid,
            session_type=session_type,
            payload=row.payload,
            random_seed=row.random_seed,
            version=row.version,
            created_at=ts,
            last_active_at=ts,
        )

    async def release(self, player_qid: str) -> None:
        """释放会话（IF-12；收口裁决 #4）：delete_session。

        入参 player_qid: 玩家 QQ 号。出参 None。核心逻辑: repository.delete_session(qid)
        （终态/放弃释放；sessions 行不存在 → 删除为幂等空操作，无副作用）。
        """
        repo = self._require_repo("release")
        # delete_session 属 RepoTransaction（repository.py L904，归属勘误同 acquire）。
        async with repo.tx() as tx:
            await tx.delete_session(player_qid)

    async def suspend(self, player_qid: str, snapshot: Any) -> None:
        """挂起会话（IF-14；收口裁决 #5）：快照 payload 写回，version 递增 +1。

        入参 player_qid: 玩家 QQ 号；snapshot: 挂起快照（payload，调合 = 配方ID+
        材料链+连锁+特性+触媒+PP+步骤，§7.1「战斗打断 → 挂起」）。出参 None。
        核心逻辑: 读既有行（保留 session_type/random_seed/created_at）→
        upsert_session(SessionRow(..., payload=snapshot, version=旧version+1,
        last_active_at=now))。version 递增保持幂等语义对齐 sessions.version 列
        （§7.2 / 细化_4a §1.3 SCHEMA-7）。无既有行（正常流程不应触发）→ 以
        version=1 防御性新建（session_type 未知置空串）。
        """
        repo = self._require_repo("suspend")
        row = await repo.load_session(player_qid)
        ts = utcnow()
        if row is None:
            # 防御分支：挂起快照前会话已被释放/从未 acquire（正常流程 3B 先 acquire 再 suspend）
            async with repo.tx() as tx:
                await tx.upsert_session(SessionRow(
                    player_qid=player_qid,
                    session_type="",
                    payload=snapshot if snapshot is not None else {},
                    random_seed=0,
                    version=1,
                    created_at=ts,
                    last_active_at=ts,
                ))
            return
        session_type, _old_payload, random_seed, version, created_at, _last = row
        async with repo.tx() as tx:
            await tx.upsert_session(SessionRow(
                player_qid=player_qid,
                session_type=session_type,
                payload=snapshot if snapshot is not None else {},
                random_seed=random_seed,
                version=version + 1,
                created_at=created_at,
                last_active_at=ts,
            ))

    async def restore(self, player_qid: str) -> Optional[SessionView]:
        """恢复会话（IF-15；收口裁决 #6）：挂起恢复读取 = get_active 同款。

        入参 player_qid: 玩家 QQ 号。出参 Optional[SessionView]（无会话 → None）。
        核心逻辑: 直接委托 get_active（sessions 表即挂起快照载体，恢复即读行）。
        """
        return await self.get_active(player_qid)

    async def recycle(
        self,
        *,
        settle: Optional[Callable[[Any, object], Optional[Any]]] = None,
        max_days: float = 30.0,
        now: Optional[str] = None,
    ) -> List[str]:
        """30 天僵尸会话回收（IF-04 透传；§七 7.1「僵尸回收」行）。

        入参 settle: Optional[Callable[[Player, object], Optional[Player]]] 结算回调
        （由会话管理器注入，§7.2「settle 回调由 SessionManager 注入」；调合终态回调
        必须含已投材料返还口径，定稿【炼金】L183）；max_days: 过期天数（缺省 30.0）；
        now: 基准时刻。出参 List[str] 被回收 qid 列表。
        核心逻辑: repository.recycle_scan(settle=..., max_days=..., now=...)（无
        settle 默认不删除，防静默丢材料，P1-1）；仓库缺失 → []。
        """
        repo = self._repository
        if repo is None:
            return []
        scan = getattr(repo, "recycle_scan", None)
        if not callable(scan):
            return []
        return await scan(settle=settle, max_days=max_days, now=now)

    async def settle_alchemy(
        self,
        player_qid: str,
        message_id: str,
        settlement_kind: str,
        session_view: Optional[Any] = None,
    ) -> bool:
        """调合终态幂等结算封装（收口裁决 #10；§10 铁律 3 同款 settle_exit_idempotent）。

        ⚠️ 接线要求（IDEM-8 / 细化_4a TX-1 单指令单事务）：本方法自行开事务，调用方
        **不得**在已持有的 repo.tx() 内调用（connection.py _tx_owner 拒绝同任务嵌套 tx）。

        流程（IDEM-3/4/6 语义，仿 battle_boundary.settle_exit_idempotent L821）：
          ① repository.idem_claim 只读查重（快速路径）→ 命中 → 返回 False（已结算，
             不双结算）；② 未命中 → 单事务【delete_session + write_idem_key】：
             tx.idem_exists 二次确认（权威判定）→ 命中 → False；未命中 →
             tx.delete_session(player_qid) + tx.write_idem_key(key) → COMMIT；
          ③ 事务内异常 → tx() 已 ROLLBACK（IDEM-6：无孤儿键、无半结算），异常向上抛。
        幂等键 = (message_id, group_id, player_qid)，command=f"settle:{kind}"
        （§10 铁律 3；command 不参与去重，4a schema 注释 L844-847，先到者胜）。
        返回 True = 本次完成结算（未结算过）；False = 已结算/要素缺失。

        入参 player_qid: 玩家 QQ 号；message_id: 触发结算的 QQ 消息 id（幂等键要素）；
        settlement_kind: 结算类型（"confirm"/"abandon"...，并入 command）；session_view:
        会话视图（发起群 group_id 来源，缺省 None → "dm" 哨兵兜底）。出参 bool。
        """
        repo = self._require_repo("settle_alchemy")
        if not player_qid or not message_id or not settlement_kind:
            # 幂等键要素缺失 → 无法建立键，保守不结算（不写键不删会话，防误删状态）
            return False
        key = IdemKey(
            message_id=message_id,
            group_id=_session_group_id(session_view),
            player_qid=player_qid,
            command=f"settle:{settlement_kind}",
        )
        # ① 入口只读查重（IDEM-3 只查不插；命中 → 已结算，不双结算）
        if await repo.idem_claim(key):
            return False
        # ② 单事务结算 + 写键（IDEM-4；异常由 tx() ROLLBACK 后向上抛，IDEM-6）
        async with repo.tx() as tx:
            if await tx.idem_exists(key):
                return False
            await tx.delete_session(player_qid)
            await tx.write_idem_key(key)
        return True
