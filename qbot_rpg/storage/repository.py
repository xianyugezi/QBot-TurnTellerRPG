"""存档读写仓库：玩家/会话/世界状态/幂等/回收 + 编解码 + round-trip。

依据：细化_4a_存储层契约 §二 存档读写（F1 管线：懒加载 + 60s 短缓存，指令级
失效；RW-3 单事务 upsert players+sessions；WAL 多读 RW-1）、§三 F3 事务模板
（async with storage.tx() as tx: tx.upsert...，幂等键与业务写同事务）、§四 幂等
（IDEM-1~5，7 天保留滚动清理）、§五 回收（RC-1 僵尸会话 30 天回收，D-05
storage 只提供「按 last_active_at 扫描 + 按退出结算写回」单事务接口）、§六
迁移（首次访问懒迁移 D-06）、SCHEMA-5（ID+名称冗余）、SCHEMA-6（JSON 列兜底）、
MIG-1（字段级迁移：缺补默认/多忽略）。

约束：仅 import qbot_rpg.data 与 storage 自身层；零 NoneBot（3a R1）。
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import datetime
import json
from dataclasses import dataclass, field  # noqa: F401（field 供类型注释可读）
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    cast,
)

from qbot_rpg.data import (
    EquipmentSlot,
    ItemInstance,
    Player,
    PlayerAttributes,
    WorldState,
)
from qbot_rpg.data.types import ItemID, PlayerQID
from qbot_rpg.storage.connection import Database, StorageError, Transaction
from qbot_rpg.storage.migrations import (
    DB_SCHEMA_VERSION,
    META_KEY,
    ensure_meta,  # noqa: F401
    migrate_database,
    utcnow,
)

# 世界状态字段 → world_state.key（4a §1.3 / §0.1；常驻不回收）
WORLD_STATE_FIELDS: Tuple[str, ...] = (
    "map_boss",
    "world_stock",
    "spawn_timers",
    "dummy_override",
    "last_spawn_time",
)

# job_id 在 players 宽表无独立列（4a §1.2 唯一数据源），按 D-01「固定列只承载
# 框架必须字段」折入 persistent_state 保留键。（见 contract_deviations.md）
_JOB_ID_KEY: str = "job_id"


class _WorldCasConflict(Exception):
    """内部哨兵异常：世界资源 CAS 冲突 → 强制事务 ROLLBACK。

    修复（2026-08-18 dsh 审查 P0-1）：原实现在事务体内 `return False` 走 COMMIT，
    冲突前已写的键半写落盘。raise 后 tx() 的 except 分支统一 ROLLBACK（4a TX-3 整体回滚）。
    """


# ===========================================================================
# 时间工具
# ===========================================================================
def parse_utc(ts: str) -> datetime.datetime:
    """解析 ISO-8601 UTC（容忍 Z 后缀）；失败回退到 epoch（视为极旧，参与回收）。"""
    s = ts if not ts.endswith("Z") else ts[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def ago_utc(days: float) -> str:
    """now - days 的 ISO-8601 UTC 字符串。"""
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000.0


# ===========================================================================
# 编解码：Player ⟷ players 行（schema §1.2；MIG-1 缺补默认/多忽略）
# ===========================================================================
def _j(o: object) -> str:
    return json.dumps(o, ensure_ascii=False)


def _jloads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return copy.deepcopy(default)
    try:
        v = json.loads(raw)
        return v if v is not None else copy.deepcopy(default)
    except (TypeError, ValueError):
        return copy.deepcopy(default)


def player_to_row(player: Player) -> Dict[str, Any]:
    """Player → players 行（JSON 列序列化；inventory/equipment 含 ID+名称冗余）。

    job_id 折入 persistent_state（_JOB_ID_KEY），无独立列（见文件头注释）。
    """
    persistent = dict(player.persistent_state)
    persistent[_JOB_ID_KEY] = player.job_id
    return {
        "player_qid": player.qid,
        "nickname": player.name,
        "level": player.level,
        "exp": player.exp,
        "hp": player.hp,
        "mp": player.mp,
        "currencies": _j(player.currencies),
        "inventory": _j([dataclasses.asdict(i) for i in player.inventory]),
        "equipment": _j({s: dataclasses.asdict(e) for s, e in player.equipment.items()}),
        "stats": _j(dataclasses.asdict(player.attributes)),
        "persistent_state": _j(persistent),
        "longline_counters": _j(player.longline_counters),
        "reputation_state": _j(player.reputation_state),
        "codex_state": _j(player.codex_state),
        "achievement_state": _j(list(player.achievement_state)),
        "title_state": _j(player.title_state),
        "content_pack_id": player.content_pack_id,
        "content_pack_version": player.content_pack_version,
        "schema_version": player.schema_version,
        "last_seen_group": player.last_seen_group,
        "created_at": player.created_at,
        "last_active_at": player.last_active_at,
    }


def _item_from_dict(d: Dict[str, Any]) -> ItemInstance:
    """inventory JSON 元素 → ItemInstance；缺省补默认、未知键多忽略（MIG-1）。"""
    stats = d.get("stats_bonus")
    return ItemInstance(
        item_id=cast(ItemID, str(d.get("item_id") or "")),
        name=str(d.get("name") or ""),
        count=int(d.get("count", 1)),
        quality=str(d.get("quality") or "normal"),
        bound=bool(d.get("bound", False)),
        slot=d.get("slot"),
        stats_bonus=dict(stats) if isinstance(stats, dict) else {},
        traits=tuple(d.get("traits") or ()),
        cooldown_until=d.get("cooldown_until"),
    )


def _equip_from_dict(d: Dict[str, Any]) -> EquipmentSlot:
    gems = d.get("gems")
    return EquipmentSlot(
        item_id=cast(ItemID, str(d.get("item_id") or "")),
        name=str(d.get("name") or ""),
        slot_level=int(d.get("slot_level", 0)),
        locked=bool(d.get("locked", False)),
        gems=tuple(gems) if isinstance(gems, (list, tuple)) else (),
    )


def _float_map(src: Any) -> Dict[str, float]:
    if not isinstance(src, dict):
        return {}
    return {str(k): float(v) for k, v in src.items()}


def _attrs_from_dict(d: Any) -> PlayerAttributes:
    if not isinstance(d, dict):
        d = {}
    bonus = d.get("bonus")
    bonus = bonus if isinstance(bonus, dict) else {}
    temp = d.get("temp")
    temp = temp if isinstance(temp, dict) else {}
    return PlayerAttributes(
        base=_float_map(d.get("base")),
        bonus={"flat": _float_map(bonus.get("flat")), "pct": _float_map(bonus.get("pct"))},
        temp={"pct": _float_map(temp.get("pct")), "flat": _float_map(temp.get("flat"))},
        cond=_float_map(d.get("cond")),
    )


def _obj_dict(v: Any) -> Dict[str, object]:
    return v if isinstance(v, dict) else {}


def _int_dict(v: Any) -> Dict[str, int]:
    if not isinstance(v, dict):
        return {}
    return {str(k): int(val) for k, val in v.items()}


def row_to_player(row: Any) -> Player:
    """players 行 → Player；缺列补默认、未知列多忽略（MIG-1/SCHEMA-6）。

    row 为 sqlite3.Row（支持 keys() 与下标）。用 col() 语义访问：row 缺失的列
    一律回默认值（缺补默认）；row 上不存在的列直接忽略（多忽略）。
    """

    def col(k: str) -> Any:
        return row[k] if k in row.keys() else None

    inv_raw = _jloads(col("inventory"), [])
    inv_items: List[ItemInstance] = [
        _item_from_dict(d) for d in inv_raw if isinstance(d, dict)
    ]
    equip_raw = _jloads(col("equipment"), {})
    equipment: Dict[str, EquipmentSlot] = {
        str(s): _equip_from_dict(d)
        for s, d in equip_raw.items()
        if isinstance(d, dict)
    }
    persistent = _jloads(col("persistent_state"), {})
    if not isinstance(persistent, dict):
        persistent = {}
    job_id = str(persistent.pop(_JOB_ID_KEY, "novice") or "novice")

    return Player(
        qid=cast(PlayerQID, str(col("player_qid") or "")),
        name=str(col("nickname") or ""),
        job_id=job_id,
        level=int(col("level") or 1),
        exp=int(col("exp") or 0),
        hp=int(col("hp") or 1),
        mp=int(col("mp") or 1),
        currencies=_jloads(col("currencies"), {}),
        inventory=tuple(inv_items),
        equipment=equipment,
        attributes=_attrs_from_dict(_jloads(col("stats"), {})),
        achievement_state=tuple(_jloads(col("achievement_state"), [])),
        title_state=_jloads(col("title_state"), {}),
        persistent_state=persistent,
        longline_counters=_jloads(col("longline_counters"), {}),
        reputation_state=_jloads(col("reputation_state"), {}),
        codex_state=_jloads(col("codex_state"), {}),
        content_pack_id=col("content_pack_id") or "",
        content_pack_version=col("content_pack_version") or "",
        schema_version=int(col("schema_version") or 4),
        last_seen_group=col("last_seen_group"),
        created_at=col("created_at") or "",
        last_active_at=col("last_active_at") or "",
    )


# ===========================================================================
# 独立数据对象（storage 层内部，供事务/RW API 使用）
# ===========================================================================
@dataclass(frozen=True)
class SessionRow:
    """会话快照行（4a §1.3 sessions 表；storage 内部类型）。payload 为快照对象/dict。"""

    player_qid: str
    session_type: str
    payload: object                     # BattleSnapshot 或 JSON 可序列化 dict
    random_seed: int
    version: int = 1
    created_at: str = ""
    last_active_at: str = ""


@dataclass(frozen=True)
class IdemKey:
    """指令幂等键（4a §1.3 idempotency_keys 表 / IDEM-1）。"""

    message_id: str
    group_id: str
    player_qid: str
    command: str
    result_hash: Optional[str] = None
    created_at: str = ""


def _now() -> str:
    return utcnow()


# ===========================================================================
# Repository
# ===========================================================================
class Repository:
    """存档读写仓库（storage 门面：load/save/事务/幂等/回收/round-trip）。"""

    def __init__(self, db: Database, *, cache_ttl_seconds: float = 60.0) -> None:
        self._db = db
        self._cache_ttl = cache_ttl_seconds
        self._player_cache: Dict[str, Tuple[float, Player]] = {}
        self._negative_cache: Dict[str, float] = {}       # 负缓存（防抖查）
        self._negative_ttl = 5.0
        self._boot_lock = asyncio.Lock()
        self._booted = False

    # -- 生命周期 ------------------------------------------------------------
    @property
    def db(self) -> Database:
        return self._db

    async def _bootstrap(self) -> None:
        """懒迁移：首次访问前执行 ensure_meta + migrate_database（D-06 懒迁移）。

        迁移失败（state=="failed"）不置 _booted，下次访问重试；并打印告警
        （P2-8 修复：迁移结果可观测、取消信号不吞）。
        """
        if self._booted:
            return
        async with self._boot_lock:
            if self._booted:
                return
            result = await migrate_database(self._db)
            if result.state == "failed":
                print(f"[storage] 存档迁移失败，携带旧版 schema 继续运行: {result.note}")
                return  # 不置 _booted → 下次访问重试迁移（服务不崩）
            self._booted = True

    async def close(self) -> None:
        await self._db.close()
        self._player_cache.clear()
        self._negative_cache.clear()
        self._booted = False

    # =======================================================================
    # 事务模板（4a §3.2 F3）：async with repo.tx() as tx: tx.upsert...
    # =======================================================================
    @contextlib.asynccontextmanager
    async def tx(self) -> AsyncIterator["RepoTransaction"]:
        await self._bootstrap()
        async with self._db.tx() as base:
            yield RepoTransaction(base, self)

    # =======================================================================
    # 玩家读写（F1：懒加载 + 60s 短缓存，指令级失效；RW-3 单事务 upsert）
    # =======================================================================
    def invalidate_player(self, qid: str) -> None:
        """指令级失效：任何写路径后调用，规避陈旧读缓存。"""
        self._player_cache.pop(qid, None)
        self._negative_cache.pop(qid, None)

    def invalidate_all(self) -> None:
        self._player_cache.clear()
        self._negative_cache.clear()

    async def load_player(self, qid: str) -> Optional[Player]:
        """只读连接读档；60s 短缓存 + 5s 负缓存（RW-1 无上下线，随时读档续玩）。"""
        await self._bootstrap()
        hit = self._player_cache.get(qid)
        if hit is not None and (self._cache_ttl <= 0 or hit[0] + self._cache_ttl > _now_ms()):
            return hit[1]
        neg = self._negative_cache.get(qid)
        if neg is not None and neg + self._negative_ttl > _now_ms():
            return None
        row = await self._db.fetchone_read(
            "SELECT * FROM players WHERE player_qid = ?", (qid,)
        )
        if row is None:
            self._negative_cache[qid] = _now_ms()
            return None
        player = row_to_player(row)
        self._player_cache[qid] = (_now_ms(), player)
        return player

    async def player_exists(self, qid: str) -> bool:
        await self._bootstrap()
        return (await self._db.fetchone_read(
            "SELECT 1 FROM players WHERE player_qid = ?", (qid,)
        )) is not None

    async def save_player(self, player: Player) -> None:
        """单事务 upsert 玩家行（RW-3；引擎层按 F3 与 session/幂等键同事务）。"""
        async with self.tx() as tx:
            await tx.upsert_player(player)
        self.invalidate_player(player.qid)

    # =======================================================================
    # 会话读写（单玩家 1 会话互斥 = 主键，SCHEMA-7）
    # =======================================================================
    async def load_session(
        self, qid: str
    ) -> Optional[Tuple[str, object, int, int, str, str]]:
        """返回 (session_type, payload, random_seed, version, created_at, last_active_at)。"""
        await self._bootstrap()
        row = await self._db.fetchone_read(
            "SELECT * FROM sessions WHERE player_qid = ?", (qid,)
        )
        if row is None:
            return None
        return (
            str(row["session_type"]),
            _jloads(row["payload_json"], {}),
            int(row["random_seed"]),
            int(row["version"]),
            str(row["created_at"]),
            str(row["last_active_at"]),
        )

    # =======================================================================
    # 世界状态读 + CAS 写（TX-3 世界资源 CAS，跨群写入串行化）
    # =======================================================================
    async def load_world_state(self) -> WorldState:
        """读 world_state 全量 → WorldState（缺行补默认）。"""
        await self._bootstrap()
        rows = await self._db.fetchall_read("SELECT key, value_json FROM world_state")
        data: Dict[str, Any] = {k: {} for k in WORLD_STATE_FIELDS}
        data["last_spawn_time"] = ""
        for r in rows:
            v = _jloads(r["value_json"], {})
            data[r["key"]] = v
        return WorldState(
            map_boss=_obj_dict(data.get("map_boss")),
            world_stock=_int_dict(data.get("world_stock")),
            spawn_timers=_obj_dict(data.get("spawn_timers")),
            dummy_override=_obj_dict(data.get("dummy_override")),
            last_spawn_time=str(data.get("last_spawn_time") or ""),
        )

    async def _world_versions_map(self) -> Dict[str, int]:
        rows = await self._db.fetchall_read("SELECT key, version FROM world_state")
        return {str(r["key"]): int(r["version"]) for r in rows}

    async def save_world_state(
        self, ws: WorldState, expected_versions: Dict[str, int], *, now: Optional[str] = None
    ) -> bool:
        """世界状态 CAS 单事务写回（TX-3）。

        对每个字段行执行 UPDATE ... WHERE key=? AND version=?（version+1）；
        对不存在行 INSERT（要求期望版本 0）。任一冲突 → raise 哨兵异常强制整体
        ROLLBACK 后返回 False（P0-1 修复：冲突前已写的键不得半写落盘）；调用方
        重读版本后重试；全部命中 → 单事务 COMMIT 返回 True。
        """
        ts = now or _now()
        values: Dict[str, object] = {
            "map_boss": ws.map_boss,
            "world_stock": ws.world_stock,
            "spawn_timers": ws.spawn_timers,
            "dummy_override": ws.dummy_override,
            "last_spawn_time": ws.last_spawn_time,
        }
        try:
            async with self.tx() as tx:
                for key in WORLD_STATE_FIELDS:
                    exp = int(expected_versions.get(key, 0))
                    cur = await tx.fetchone(
                        "SELECT version FROM world_state WHERE key = ?", (key,)
                    )
                    if cur is None:
                        if exp != 0:
                            raise _WorldCasConflict()          # 期望已存在但实际缺失
                        await tx.execute(
                            "INSERT INTO world_state (key, value_json, version, updated_at)"
                            " VALUES (?,?,?,?)",
                            (key, _j(values[key]), 1, ts),
                        )
                    else:
                        if int(cur["version"]) != exp:
                            raise _WorldCasConflict()          # CAS 冲突 → 整体回滚
                        await tx.execute(
                            "UPDATE world_state SET value_json = ?, version = version + 1,"
                            " updated_at = ? WHERE key = ? AND version = ?",
                            (_j(values[key]), ts, key, exp),
                        )
        except _WorldCasConflict:
            return False                                     # 任何冲突 → 全部回滚
        return True

    # =======================================================================
    # 幂等（IDEM-1~5：message_id+group_id+qid 复合键；7 天保留滚动清理）
    # =======================================================================
    @staticmethod
    def _idem_where() -> str:
        return "message_id = ? AND group_id = ? AND player_qid = ?"

    async def idem_claim(self, key: IdemKey) -> bool:
        """幂等状态检查（只读，不插入）。

        修复（2026-08-18 dsh 审查 P1-1）：原实现自带事务先插入幂等键再返回，导致
        幂等键在独立事务提前 COMMIT，违反 IDEM-2「幂等键与业务写同事务」——业务
        随后失败回滚会留下孤儿幂等键，同 message_id 重试被幂等空吞（操作黑洞）。
        现在只查不插；插入必须由调用方在业务事务内 write_idem_key：

            async with repo.tx() as tx:
                if await tx.idem_exists(key):   # 已处理 → 幂等重放
                    return True
                await tx.write_idem_key(key)    # 与业务写同事务（IDEM-2）
                <业务写>

        返回 True = 已处理（幂等重放，业务零执行）；返回 False = 首次（未处理）。
        """
        await self._bootstrap()
        row = await self._db.fetchone_read(
            f"SELECT 1 FROM idempotency_keys WHERE {self._idem_where()}",
            (key.message_id, key.group_id, key.player_qid),
        )
        return row is not None

    async def idem_find(
        self, message_id: str, group_id: str, qid: str
    ) -> Optional[IdemKey]:
        """幂等键查询（只读；命中返回完整记录用于重放 result_hash）。"""
        await self._bootstrap()
        row = await self._db.fetchone_read(
            f"SELECT * FROM idempotency_keys WHERE {self._idem_where()}",
            (message_id, group_id, qid),
        )
        if row is None:
            return None
        return IdemKey(
            message_id=str(row["message_id"]),
            group_id=str(row["group_id"]),
            player_qid=str(row["player_qid"]),
            command=str(row["command"]),
            result_hash=row["result_hash"],
            created_at=str(row["created_at"]),
        )

    async def cleanup_idem_keys(
        self, retention_days: float = 7.0, *, now: Optional[str] = None
    ) -> int:
        """幂等键 7 天滚动清理（IDEM-5 / D-03，idx_idem_created 支撑）。"""
        deadline = ago_utc(retention_days)
        if now is not None and parse_utc(now) < parse_utc(deadline):
            deadline = now
        async with self.tx() as tx:
            await tx.execute(
                "DELETE FROM idempotency_keys WHERE created_at < ?", (deadline,)
            )
            row = await tx.fetchone("SELECT changes() AS c")
            if row is not None:
                return int(row["c"] or 0)
            return 0

    # =======================================================================
    # 回收（RC-1 / D-05：storage 只提供单事务扫描 + 结算写回接口）
    # =======================================================================
    async def recycle_scan(
        self,
        *,
        settle: Optional[Callable[[Player, object], Optional[Player]]] = None,
        max_days: float = 30.0,
        now: Optional[str] = None,
    ) -> List[str]:
        """单事务回收过期会话（last_active_at < now-30d）。返回被回收 qid 列表。

        settle(player, session_payload) 由会话管理器注入（D-05：storage 不自行
        决定结算语义）；默认 None = 不结算仅删除会话行。结算与删除同一事务
        （RC-1 / TC-15，中途失败不残留半结算）。
        """
        await self._bootstrap()
        deadline = ago_utc(max_days)
        if now is not None and parse_utc(now) < parse_utc(deadline):
            deadline = now
        recycled: List[str] = []
        async with self.tx() as tx:
            rows = await tx.fetchall(
                "SELECT * FROM sessions WHERE last_active_at < ?", (deadline,)
            )
            for row in rows:
                qid = str(row["player_qid"])
                payload = _jloads(row["payload_json"], {})
                if settle is not None:
                    p = await self._load_player_in_tx(tx, qid)
                    if p is not None:
                        p2 = settle(p, payload)
                        if p2 is not None:
                            await _upsert_player(tx, p2)
                await tx.execute("DELETE FROM sessions WHERE player_qid = ?", (qid,))
                recycled.append(qid)
        for qid in recycled:
            self.invalidate_player(qid)
        return recycled

    async def _load_player_in_tx(
        self, tx: "RepoTransaction", qid: str
    ) -> Optional[Player]:
        row = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (qid,))
        return row_to_player(row) if row is not None else None

    # =======================================================================
    # round-trip 校验工具（4a TC-12 往返一致；MIG-5 迁移 round-trip）
    # =======================================================================
    def codec_roundtrip(self, player: Player) -> Tuple[bool, str]:
        """编解码往返：row → Player → asdict 全字段一致（不碰 DB）。"""
        row = player_to_row(player)
        back = row_to_player(dict(row))
        if dataclasses.asdict(back) == dataclasses.asdict(player):
            return True, "codec round-trip OK"
        return False, "codec round-trip 字段不一致"

    async def db_roundtrip(self, player: Player) -> Tuple[bool, str]:
        """入库往返：save_player → load_player → asdict 全字段一致（TC-12）。"""
        await self._bootstrap()
        await self.save_player(player)
        back = await self.load_player(player.qid)
        if back is None:
            return False, "save 后 load 为空"
        if dataclasses.asdict(back) == dataclasses.asdict(player):
            return True, "db round-trip OK"
        # 定位差异字段
        a = dataclasses.asdict(player)
        b = dataclasses.asdict(back)
        for k in a.keys():
            if a[k] != b.get(k):
                return False, f"db round-trip 字段不一致: {k}"
        return False, "db round-trip 字段不一致"


# ===========================================================================
# 事务态仓库操作（F3 模板：幂等键与业务写同事务提交 IDEM-2）
# ===========================================================================
_UPSERT_PLAYER_SQL = """
INSERT INTO players (
    player_qid, nickname, level, exp, hp, mp, currencies, inventory, equipment,
    stats, persistent_state, longline_counters, reputation_state, codex_state,
    achievement_state, title_state, content_pack_id, content_pack_version,
    schema_version, last_seen_group, created_at, last_active_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(player_qid) DO UPDATE SET
    nickname=excluded.nickname, level=excluded.level, exp=excluded.exp,
    hp=excluded.hp, mp=excluded.mp, currencies=excluded.currencies,
    inventory=excluded.inventory, equipment=excluded.equipment,
    stats=excluded.stats, persistent_state=excluded.persistent_state,
    longline_counters=excluded.longline_counters,
    reputation_state=excluded.reputation_state, codex_state=excluded.codex_state,
    achievement_state=excluded.achievement_state, title_state=excluded.title_state,
    content_pack_id=excluded.content_pack_id,
    content_pack_version=excluded.content_pack_version,
    schema_version=excluded.schema_version, last_seen_group=excluded.last_seen_group,
    last_active_at=excluded.last_active_at
"""


async def _upsert_player(tx: "RepoTransaction", player: Player) -> None:
    row = player_to_row(player)
    await tx.execute(
        _UPSERT_PLAYER_SQL,
        (
            row["player_qid"], row["nickname"], row["level"], row["exp"], row["hp"],
            row["mp"], row["currencies"], row["inventory"], row["equipment"],
            row["stats"], row["persistent_state"], row["longline_counters"],
            row["reputation_state"], row["codex_state"], row["achievement_state"],
            row["title_state"], row["content_pack_id"], row["content_pack_version"],
            row["schema_version"], row["last_seen_group"], row["created_at"],
            row["last_active_at"],
        ),
    )


def _payload_to_json(payload: object) -> str:
    if isinstance(payload, (str, bytes)):
        return str(payload)
    if dataclasses.is_dataclass(payload):
        return _j(dataclasses.asdict(payload))
    return _j(payload)


class RepoTransaction:
    """F3 事务句柄：基础执行原语 + 领域级 upsert（data dataclass，禁裸 dict）。"""

    __slots__ = ("_base", "_repo")

    def __init__(self, base: Transaction, repo: Repository) -> None:
        self._base = base
        self._repo = repo

    @property
    def is_active(self) -> bool:
        return self._base.is_active

    # -- 原语 -----------------------------------------------------------------
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return await self._base.execute(sql, params)

    async def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> Any:
        return await self._base.executemany(sql, seq)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Any]:
        return await self._base.fetchone(sql, params)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[Any]:
        return await self._base.fetchall(sql, params)

    # -- 领域级（F3 模板：同事务提交）--------------------------------------------
    async def upsert_player(self, player: Player) -> None:
        await _upsert_player(self, player)
        self._repo.invalidate_player(player.qid)

    async def upsert_session(self, session: SessionRow) -> None:
        ts = session.last_active_at or _now()
        created = session.created_at or ts
        await self.execute(
            "INSERT INTO sessions (player_qid, session_type, version, payload_json,"
            " random_seed, created_at, last_active_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(player_qid) DO UPDATE SET"
            " session_type=excluded.session_type, version=excluded.version,"
            " payload_json=excluded.payload_json, random_seed=excluded.random_seed,"
            " last_active_at=excluded.last_active_at",
            (
                session.player_qid, session.session_type, session.version,
                _payload_to_json(session.payload), session.random_seed, created, ts,
            ),
        )

    async def delete_session(self, qid: str) -> None:
        await self.execute("DELETE FROM sessions WHERE player_qid = ?", (qid,))

    async def write_idem_key(self, key: IdemKey) -> None:
        """幂等键插入（IDEM-2：与业务写同事务提交，消除崩溃窗口）。"""
        await self.execute(
            "INSERT OR IGNORE INTO idempotency_keys"
            " (message_id, group_id, player_qid, command, result_hash, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (key.message_id, key.group_id, key.player_qid, key.command,
             key.result_hash, key.created_at or _now()),
        )

    async def idem_exists(self, key: IdemKey) -> bool:
        """幂等状态查询（事务内 F4 判定）。返回 True = 已处理（幂等重放）。"""
        row = await self.fetchone(
            f"SELECT 1 FROM idempotency_keys WHERE "
            f"message_id = ? AND group_id = ? AND player_qid = ?",
            (key.message_id, key.group_id, key.player_qid),
        )
        return row is not None


__all__ = [
    "Repository",
    "RepoTransaction",
    "SessionRow",
    "IdemKey",
    "player_to_row",
    "row_to_player",
    "parse_utc",
    "ago_utc",
    "StorageError",
    "DB_SCHEMA_VERSION",
    "META_KEY",
]
