"""RW-4 `.pending` 暂存补写队列（M6 批5·路A · D5 FLT-11~17 实装 · 核销 contract_deviations F-1）。

依据（权威契约）：
  - docs/细化/细化_4a_存储层契约.md（4a）：
      RW-4 L225「写抛 OSError → 弹『保存失败，请检查磁盘空间』人话提示 + 本地暂存
      （`.pending` 文件队列），磁盘恢复后补写；**绝不静默丢数据**」
      TC-09 L392（存档写入失败兜底：人话提示 + .pending 暂存 + 恢复后补写，未丢任何已确认数据）
  - docs/细化/细化_M6_故障注入.md（M6 子细化 D5）§三：
      FLT-11（注入点 = storage 写路径 save_player / tx() COMMIT 抛 OSError）
      FLT-12（人话通道「保存失败，请检查磁盘空间」）
      FLT-13（绝不静默丢数据）
      FLT-14（`.pending.jsonl` 追加写，条目 = F-01~04）
      FLT-15（磁盘恢复后重放回主库（单事务）→ 成功清空；重放失败保留条目不丢）
      FLT-16（F-1 核销）/ FLT-17（断言对象）
      字段 §九 F-01~F-04（player_qid / action / row_payload / created_at）
  - contract_deviations.md L24 F-1（RW-4/TC-09 递延 M4 → 本档核销「M6 已实装」）
  - 定稿《开发规则文档.md》L320（存档写入失败 → 暂存补写）+ 细化_3d D-04（唯一文案源）

【工程补白 · 显式标注】（D5 ADR-D5-01 落点收敛）
  - 文案源定位：D5 ADR-D5-01 建议「进 3d 消息模板注册表 / commands/errors.py 文案源」；
    G0 架构门禁 R3（test_g0_architecture test_commands_web_not_depended）**禁止 storage 反向
    import commands**，故 `SAVE_FAILURE_MESSAGE` 文案源定在 storage 层本模块，命令层（批次6/7）
    捕获 StorageError 时直接透传该人话即可，无需二次翻译（文案已人话化）。
  - 重放动作语义：F-02 action 支持 player_upsert / session_upsert / delete_session 三类
    （与 D5 §九 F-02 一致）；重放落点 = qbot_rpg/storage/repository.py `Repository.replay_pending()`
    （单事务整批回写 → 成功清空 → 失败保留），本模块只做条目持久化/读取/清空，零 DB 依赖
    （避免 repository ↔ pending 循环 import；重放是写库逻辑归 repository）。

字段（D5 §九 F-01~04，均 JSON 可序列化）：
  - F-01 player_qid：条目目标玩家（str）
  - F-02 action：重放动作类型（str：player_upsert / session_upsert / delete_session）
  - F-03 row_payload：序列化行数据（dict，重放时整行写回）
  - F-04 created_at：入队时刻（ISO-8601 UTC 字符串）
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

from qbot_rpg.data.logging_utils import get_logger

_logger = get_logger("storage.pending")

#: RW-4 暂存补写文件名（数据目录下，4a RW-4 / D5 FLT-14）
PENDING_FILENAME: str = ".pending.jsonl"

#: 写失败人话文案（D5 FLT-12 / 4a RW-4 L225 / 规则 L320；文案源 = 本模块，见文件头【工程补白】）
SAVE_FAILURE_MESSAGE: str = "保存失败，请检查磁盘空间"

#: 重放动作类型（D5 §九 F-02）
ACTION_PLAYER_UPSERT: str = "player_upsert"      # 玩家行整行回写
ACTION_SESSION_UPSERT: str = "session_upsert"    # 会话行整行回写
ACTION_DELETE_SESSION: str = "delete_session"    # 删除会话行

#: 合法动作集合（重放时未知动作 → 视为坏条目保留不丢）
VALID_ACTIONS: frozenset = frozenset(
    {ACTION_PLAYER_UPSERT, ACTION_SESSION_UPSERT, ACTION_DELETE_SESSION}
)

#: 时间戳格式与 repository._now / migrations.utcnow 对齐（ISO-8601 UTC，Z 定长）
_TS_FMT: str = "%Y-%m-%dT%H:%M:%SZ"


def _utcnow() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime(_TS_FMT)


@dataclass(frozen=True)
class PendingEntry:
    """`.pending` 暂存条目（D5 §九 F-01~04）。

    row_payload 为**序列化行数据**（F-03）：player_upsert = players 行
    （qbot_rpg/storage/repository.py player_to_row 输出）；session_upsert =
    会话行字段（含解析后 payload 对象）；delete_session = 仅 player_qid 键。
    重放时按 action 整行写回主库（repository.replay_pending 消费）。
    """

    player_qid: str                      # F-01 目标玩家
    action: str                          # F-02 重放动作类型
    row_payload: Dict[str, Any] = field(default_factory=dict)   # F-03 序列化行数据
    created_at: str = ""                 # F-04 入队时刻（ISO-8601）

    def to_line(self) -> str:
        """JSONL 单行序列化（无换行符注入：json.dumps 保证换行安全）。"""
        data = asdict(self)
        data["created_at"] = self.created_at or _utcnow()
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_line(cls, line: str) -> "PendingEntry":
        """JSONL 单行反序列化；字段缺省补默认、未知键多忽略（MIG-1 语义）。"""
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"pending 条目非 dict：{line!r}")
        payload_raw = raw.get("row_payload")
        row_payload: Dict[str, Any] = {}
        if isinstance(payload_raw, dict):
            row_payload = dict(payload_raw)
        return cls(
            player_qid=str(raw.get("player_qid") or ""),
            action=str(raw.get("action") or ""),
            row_payload=row_payload,
            created_at=str(raw.get("created_at") or ""),
        )


class PendingQueue:
    """RW-4 `.pending` 暂存队列（D5 FLT-14）：数据目录 `.pending.jsonl` 追加写。

    职责（只做文件持久化，零 DB 依赖）：
      - append：JSONL 追加写一行（写入后 fsync，防崩溃丢行——RW-4 绝不静默丢数据）
      - read_all / count：读取全部条目（坏行跳过不丢、记告警）
      - clear：重放成功清空（删除文件；删除失败 → 写空文件标记，防重放重复）

    重放（FLT-15：磁盘恢复后逐条重放回主库（单事务）→ 成功清空 → 失败保留条目不丢）
    由 qbot_rpg/storage/repository.py `Repository.replay_pending()` 承担（本模块不 import
    repository，避免循环依赖；见文件头【工程补白】）。
    """

    def __init__(self, data_dir: Union[str, Path]) -> None:
        self._dir = Path(data_dir)
        self._path = self._dir / PENDING_FILENAME

    # -- 路径 --------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self._dir

    @property
    def path(self) -> Path:
        """`.pending.jsonl` 绝对路径（测试断言对象：D5 TC-FLT-07「tmp_path 下含该数据行」）。"""
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    # -- 写入 --------------------------------------------------------------
    async def append(self, entry: PendingEntry) -> None:
        """追加写一行（JSONL）。写盘 OSError 原样上抛（绝不静默吞错：上层记日志兜底）。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        line = entry.to_line()
        # 同步追加写 + fsync：行粒度原子落盘（F-03 原行 payload 完整保留；防半行/丢行）
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # -- 读取 --------------------------------------------------------------
    async def read_all(self) -> List[PendingEntry]:
        """读取全部条目（按入队顺序）；坏行跳过保留（不删原文件，记告警防静默丢）。"""
        if not self._path.exists():
            return []
        entries: List[PendingEntry] = []
        with open(self._path, "r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = PendingEntry.from_line(line)
                except (ValueError, TypeError) as exc:
                    # 坏行不丢：记告警并跳过（重放仍按其余条目进行；坏行保留待人工审计）
                    _logger.warning("pending 第 %s 行解析失败跳过（保留原文件）：%s", line_no, exc)
                    continue
                if not entry.player_qid or entry.action not in VALID_ACTIONS:
                    _logger.warning("pending 第 %s 行字段非法跳过（保留原文件）：%r", line_no, entry)
                    continue
                entries.append(entry)
        return entries

    async def count(self) -> int:
        return len(await self.read_all())

    # -- 清空 --------------------------------------------------------------
    async def clear(self) -> None:
        """重放成功清空（FLT-15「成功清空」）。删除失败 → 写空文件标记（防重放重复处理）。"""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            # 删除失败（仍不可写）→ 覆盖为空文件：下次重放 read_all 为空，不重复回写
            with open(self._path, "w", encoding="utf-8") as fh:
                fh.write("")


__all__ = [
    "ACTION_DELETE_SESSION",
    "ACTION_PLAYER_UPSERT",
    "ACTION_SESSION_UPSERT",
    "PENDING_FILENAME",
    "SAVE_FAILURE_MESSAGE",
    "VALID_ACTIONS",
    "PendingEntry",
    "PendingQueue",
]
