"""SessionManager 单测（M8 批3 路3A）：伪异步仓库内存模拟 load/upsert/delete/idem。

覆盖（收口裁决 2026-08-29 + docs/m8_contract_核心机制 §八 IF-11~19 / §10 铁律 3）：
  - acquire 新建 / 已有活跃会话 → SessionConflictError
  - get_active 有 / 无；restore = get_active 同款
  - suspend 更新 payload + version 递增（幂等语义对齐 sessions.version 列）
  - release 删除会话
  - recycle 透传 recycle_scan（settle/max_days/now 原样转发）
  - settle_alchemy 幂等结算：首调 True（单事务 delete+写键）、次调 False 不双删；
    要素缺失保守不结算；group_id 从会话视图/payload 解析；command="settle:{kind}"；
    command 不参与去重（同 message_id+group+qid 先到者胜）
  - 构造器未注入 repository → 读防御 None / 写抛 RuntimeError（装配缺口明示）
零 NoneBot import；asyncio_mode=auto（pytest.ini）→ async def test_* 直接跑。
"""
from __future__ import annotations

import contextlib
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

import pytest

from qbot_rpg.storage.repository import IdemKey, SessionRow
from qbot_rpg.world.session import (
    SessionConflictError,
    SessionManager,
    SessionView,
)

# 时间戳口径对齐 storage/migrations.utcnow（ISO-8601 UTC，Z 后缀）
_TS_EARLY = "2000-01-01T00:00:00Z"
_TS_LATE = "2099-01-01T00:00:00Z"


class FakeSessionRepo:
    """伪会话仓库（异步）：内存 dict 模拟 load/upsert/delete/recycle/idem/tx。

    幂等键语义对齐真实 schema（4a §1.3）：复合键 = (message_id, group_id,
    player_qid)，command **不参与去重**（schema.py L71-81 注释；先到者胜）。
    tx() 拒绝嵌套（镜像 connection._tx_owner 同任务嵌套防护，供嵌套调用测试）。
    """

    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.idem: Dict[Tuple[str, str, str], str] = {}   # (mid, gid, qid) -> command
        self._tx_depth = 0
        self.tx_open_count = 0
        self.last_recycle: Optional[Dict[str, Any]] = None

    # -- 会话读写 ---------------------------------------------------------------
    async def load_session(self, qid: str) -> Optional[Tuple[str, object, int, int, str, str]]:
        row = self.sessions.get(qid)
        if row is None:
            return None
        return (
            str(row["session_type"]),
            row["payload"],
            int(row["random_seed"]),
            int(row["version"]),
            str(row["created_at"]),
            str(row["last_active_at"]),
        )

    async def upsert_session(self, session: SessionRow) -> None:
        self.sessions[session.player_qid] = {
            "session_type": session.session_type,
            "payload": session.payload,
            "random_seed": session.random_seed,
            "version": session.version,
            "created_at": session.created_at,
            "last_active_at": session.last_active_at,
        }

    async def delete_session(self, qid: str) -> None:
        self.sessions.pop(qid, None)

    async def recycle_scan(
        self,
        *,
        settle: Optional[Callable[[Any, object], Optional[Any]]] = None,
        max_days: float = 30.0,
        now: Optional[str] = None,
        allow_unsettled: bool = False,
    ) -> List[str]:
        self.last_recycle = {
            "settle": settle, "max_days": max_days, "now": now,
            "allow_unsettled": allow_unsettled,
        }
        # 过期判定：last_active_at < (now or 极晚) → 参与回收（透传验证用固定集合）
        deadline = now or _TS_LATE
        return [q for q, row in self.sessions.items()
                if str(row["last_active_at"]) < deadline]

    # -- 幂等 ---------------------------------------------------------------
    async def idem_claim(self, key: IdemKey) -> bool:
        return (key.message_id, key.group_id, key.player_qid) in self.idem

    async def idem_exists(self, key: IdemKey) -> bool:
        return (key.message_id, key.group_id, key.player_qid) in self.idem

    async def write_idem_key(self, key: IdemKey) -> None:
        self.idem[(key.message_id, key.group_id, key.player_qid)] = key.command

    # -- 事务（拒绝嵌套，镜像 connection._tx_owner）----------------------------
    @contextlib.asynccontextmanager
    async def tx(self) -> AsyncIterator["FakeSessionRepo"]:
        if self._tx_depth > 0:
            raise RuntimeError("嵌套事务：调用方不得在已持有 repo.tx() 内调用 settle_alchemy")
        self._tx_depth += 1
        self.tx_open_count += 1
        try:
            yield self
        finally:
            self._tx_depth -= 1


# =============================================================================
# acquire / get_active / restore
# =============================================================================
async def test_acquire_creates_session_and_returns_view() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    view = await mgr.acquire("u1", "alchemy", payload={"recipe": "r1", "step": 1})

    assert isinstance(view, SessionView)
    assert view.player_qid == "u1"
    assert view.session_type == "alchemy"
    assert view.payload == {"recipe": "r1", "step": 1}
    assert view.version == 1
    assert view.random_seed == 0
    assert view.created_at and view.last_active_at  # 时间戳已落
    # 落库后可读回（视图 = load_session 展开）
    back = await mgr.get_active("u1")
    assert back is not None
    assert back.payload == {"recipe": "r1", "step": 1}
    assert back.version == 1


async def test_acquire_payload_default_empty() -> None:
    mgr = SessionManager(FakeSessionRepo())
    view = await mgr.acquire("u1", "battle")
    assert view.payload == {}


async def test_acquire_conflict_raises() -> None:
    """已有活跃会话 → SessionConflictError（§7.2 全局互斥 / IF-16）。"""
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    with pytest.raises(SessionConflictError):
        await mgr.acquire("u1", "battle")


async def test_get_active_none_when_no_session() -> None:
    mgr = SessionManager(FakeSessionRepo())
    assert await mgr.get_active("nobody") is None


async def test_restore_reads_same_as_get_active() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy", payload={"recipe": "r2"})
    restored = await mgr.restore("u1")
    assert restored is not None
    assert restored.session_type == "alchemy"
    assert restored.payload == {"recipe": "r2"}
    assert await mgr.restore("nobody") is None


# =============================================================================
# suspend / release
# =============================================================================
async def test_suspend_updates_payload_and_increments_version() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy", payload={"step": 1, "chain": []})
    await mgr.suspend("u1", {"step": 2, "chain": ["fire"], "pp": 3})

    view = await mgr.get_active("u1")
    assert view is not None
    assert view.payload == {"step": 2, "chain": ["fire"], "pp": 3}  # payload 已更新
    assert view.version == 2                                          # version 递增 +1
    assert view.session_type == "alchemy"                             # 类型保留
    assert view.created_at                                            # created_at 保留

    # 再次挂起 → version 继续递增（幂等语义对齐 sessions.version 列，§7.2）
    await mgr.suspend("u1", {"step": 3})
    view2 = await mgr.get_active("u1")
    assert view2 is not None
    assert view2.version == 3


async def test_release_deletes_session() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    await mgr.release("u1")
    assert await mgr.get_active("u1") is None
    # 重复释放（无会话行）为幂等空操作，不抛
    await mgr.release("u1")


# =============================================================================
# recycle 透传
# =============================================================================
async def test_recycle_passthrough_returns_recycled_qids() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    await mgr.acquire("u2", "alchemy")

    settle_cb = lambda p, payload: p  # noqa: E731 —— 透传占位回调
    # now=_TS_LATE（未来基准）→ 全部会话 last_active_at(2026) 早于 deadline → 全回收
    recycled = await mgr.recycle(settle=settle_cb, max_days=7.0, now=_TS_LATE)

    assert recycled == ["u1", "u2"]
    assert repo.last_recycle is not None
    assert repo.last_recycle["settle"] is settle_cb
    assert repo.last_recycle["max_days"] == 7.0
    assert repo.last_recycle["now"] == _TS_LATE


async def test_recycle_defaults_forwarded() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.recycle()
    assert repo.last_recycle is not None
    assert repo.last_recycle["max_days"] == 30.0      # 缺省 30 天（§7.1 僵尸回收）
    assert repo.last_recycle["now"] is None
    assert repo.last_recycle["settle"] is None        # 无 settle 默认不删（P1-1）


# =============================================================================
# settle_alchemy 幂等终态结算（§10 铁律 3 / IF-17 同款模式）
# =============================================================================
async def test_settle_alchemy_first_call_settles_and_deletes() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy", payload={"recipe": "r1", "origin_group": "g9"})
    view = await mgr.get_active("u1")
    assert view is not None

    ok = await mgr.settle_alchemy("u1", "m-001", "confirm", view)
    assert ok is True
    # 单事务：delete_session + write_idem_key 原子达成，会话已清
    assert await mgr.get_active("u1") is None
    # tx 计数：acquire（写走事务句柄，1 次）+ settle_alchemy 单事务（1 次）= 2；
    # settle 本身只开 1 次 tx（单事务语义，收口修正 2026-08-29：upsert 属 RepoTransaction）
    assert repo.tx_open_count == 2
    # 幂等键已写：group_id 取自会话视图 payload.origin_group；command=settle:confirm
    assert repo.idem[("m-001", "g9", "u1")] == "settle:confirm"


async def test_settle_alchemy_second_call_idempotent_false_no_double_delete() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    view = await mgr.get_active("u1")
    assert view is not None

    assert await mgr.settle_alchemy("u1", "m-001", "confirm", view) is True
    tx_before = repo.tx_open_count
    # 重复结算：idem_claim 快速路径命中 → False，不删（会话已删，零副作用）
    assert await mgr.settle_alchemy("u1", "m-001", "confirm", view) is False
    assert repo.tx_open_count == tx_before          # 二次调用未再开事务
    assert await mgr.get_active("u1") is None


async def test_settle_alchemy_command_does_not_participate_in_dedup() -> None:
    """同 message_id+group+qid 的不同结算类型视为已结算（先到者胜，schema 注释）。"""
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    view = await mgr.get_active("u1")
    assert view is not None

    assert await mgr.settle_alchemy("u1", "m-001", "confirm", view) is True
    # 同键不同 kind（abandon）→ 已结算 False（不双结算；command 仅落审计列）
    assert await mgr.settle_alchemy("u1", "m-001", "abandon", view) is False


async def test_settle_alchemy_missing_elements_no_settle() -> None:
    """幂等键要素缺失 → 保守不结算（不写键不删会话，防误删状态）。"""
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    view = await mgr.get_active("u1")
    assert view is not None

    assert await mgr.settle_alchemy("", "m-001", "confirm", view) is False
    assert await mgr.settle_alchemy("u1", "", "confirm", view) is False
    assert await mgr.settle_alchemy("u1", "m-001", "", view) is False
    assert repo.idem == {}
    assert await mgr.get_active("u1") is not None    # 会话未被删


async def test_settle_alchemy_group_id_falls_back_to_dm_sentinel() -> None:
    """会话无发起群信息 → "dm" 哨兵兜底（D2 §1.4 边界异常）。"""
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy", payload={"recipe": "r1"})  # payload 无 group 信息
    view = await mgr.get_active("u1")
    assert view is not None

    assert await mgr.settle_alchemy("u1", "m-002", "abandon", view) is True
    assert repo.idem[("m-002", "dm", "u1")] == "settle:abandon"


async def test_settle_alchemy_nested_tx_rejected() -> None:
    """调用方不得在已持有 repo.tx() 内调用（§10 铁律 3 / IDEM-8 接线要求）。"""
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy")
    view = await mgr.get_active("u1")
    assert view is not None

    with pytest.raises(RuntimeError):
        async with repo.tx():
            await mgr.settle_alchemy("u1", "m-003", "confirm", view)


# =============================================================================
# 构造器未注入 repository（收口裁决 #8：None 缺省无 repo 状态）
# =============================================================================
async def test_no_repo_reads_defensive_none() -> None:
    mgr = SessionManager()                       # 未注入（装配层应已改 bootstrap.py L61）
    assert await mgr.get_active("u1") is None
    assert await mgr.restore("u1") is None
    assert await mgr.recycle() == []


async def test_no_repo_writes_raise_runtime_error() -> None:
    mgr = SessionManager()
    with pytest.raises(RuntimeError):
        await mgr.acquire("u1", "alchemy")
    with pytest.raises(RuntimeError):
        await mgr.release("u1")
    with pytest.raises(RuntimeError):
        await mgr.suspend("u1", {})
    with pytest.raises(RuntimeError):
        await mgr.settle_alchemy("u1", "m-1", "confirm")


# =============================================================================
# SessionView 载荷读取兼容（收口裁决 #2：payload 原样保留；缺 target/turn 兜底 None）
# =============================================================================
async def test_session_view_payload_field_compat() -> None:
    repo = FakeSessionRepo()
    mgr = SessionManager(repo)
    await mgr.acquire("u1", "alchemy", payload={"target": "slime", "turn": 3})
    view = await mgr.get_active("u1")
    assert view is not None
    # payload 字段读取（现有调用方 _bs_field(bs, "payload") 形态）
    assert view.payload == {"target": "slime", "turn": 3}
    # 视图本身缺 target/turn 字段 → getattr 缺省 None（_bs_field 兜底安全）
    assert getattr(view, "target", None) is None
    assert getattr(view, "turn", None) is None
    assert getattr(view, "player_qid", None) == "u1"
