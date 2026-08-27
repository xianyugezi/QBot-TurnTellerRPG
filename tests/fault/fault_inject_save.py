"""故障注入脚本②：存档写失败 → 暂存补写（M6 批5·路A · D5 §三 save 脚本 + RW-4 实装）——TC-FLT-07~09。

依据：
  - docs/细化/细化_M6_故障注入.md（D5）§三（FLT-11~17 / TC-FLT-07~09）：
      FLT-11（注入点 = mock storage 写路径 tx() COMMIT 抛 OSError，connection._commit 接缝）
      FLT-12（人话提示「保存失败，请检查磁盘空间」——主依据规则 L320，不引框架 L1175-1176）
      FLT-13（绝不静默丢数据）
      FLT-14（`.pending.jsonl` 追加写，条目 = F-01~04：qid/action/row_payload/created_at）
      FLT-15（磁盘恢复后重放回主库（单事务）→ 成功清空；重放失败保留条目不丢）
      FLT-16（F-1 核销：contract_deviations.md L24 标注「M6 已实装」）
      FLT-17（断言对象：①人话文案 ②pending 文件含数据行 ③重放后 load_player 一致）
  - docs/细化/细化_4a_存储层契约.md（4a）：RW-4 L225（写失败兜底）/ TC-09 L392（存档
    写入失败兜底：人话提示 + .pending 暂存 + 恢复后补写，未丢任何已确认数据）
  - contract_deviations.md L24 F-1（RW-4/TC-09 递延 M4 → 本档核销「M6 已实装」）
  - 定稿《开发规则文档.md》L320（存档写入失败 → 暂存补写）
  - qbot_rpg/storage/pending.py（RW-4 实装落点：PendingQueue / PendingEntry / SAVE_FAILURE_MESSAGE）

覆盖（storage 写路径真实实现 + .pending 实装，不 mock 引擎）：
  TC-FLT-07 写失败人话 + pending 落（F-01~04 数据行，无半写）
  TC-FLT-08 磁盘恢复后重放一致（load_player 与确认数据一致 + pending 清空）
  TC-FLT-09 F-1 核销登记（contract_deviations.md L24 标注 M6 已实装）

【工程补白】注入隔离（D5 §一 1.2/FLT-04）：注入点 = 本用例构造的 Database 实例的
`_commit` 接缝（connection.py tx() COMMIT 抽出方法，FLT-11），monkeypatch 仅作用于测试
实例（实例属性遮蔽类方法），非生产模块全局 patch；每用例独立 :memory: + tmp_path 数据
目录互不串扰（D5 §一 1.2 / TC-FLT-07「独立 :memory: + tmp_path 数据目录」）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from qbot_rpg.storage.connection import Database, StorageError
from qbot_rpg.storage.pending import ACTION_PLAYER_UPSERT, PendingQueue, SAVE_FAILURE_MESSAGE
from qbot_rpg.storage.repository import Repository

from conftest import make_player

REPO_ROOT: Path = Path(__file__).resolve().parents[2]


@dataclass
class SaveEnv:
    """save 脚本环境（收口补建 fixture：repo/db/data_dir/pending 四属性）。"""

    repo: Repository
    db: Database
    data_dir: Path
    pending: PendingQueue


@pytest.fixture
async def save_env(tmp_path):
    """独立文件库 + tmp_path 数据目录（FLT-04 注入隔离：每用例独立实例互不串扰）。"""
    db = Database(str(tmp_path / "save.db"))
    repo = Repository(db, pending_dir=str(tmp_path))
    yield SaveEnv(repo=repo, db=db, data_dir=tmp_path, pending=repo.pending)
    await repo.close()


# ---------------------------------------------------------------------------
# TC-FLT-07：写失败人话 + pending 落（FLT-11~14 / 4a RW-4/TC-09）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flt_07_write_failure_human_message_and_pending(save_env, monkeypatch):
    """TC-FLT-07 写失败人话 + pending 落（D5 FLT-11~14 / 4a RW-4/TC-09 L392）。

    三要素注释：
      注入点 = mock save_env.db._commit 抛 OSError（storage 写路径 tx() COMMIT 磁盘满，
        connection._commit 注入接缝，仅作用于本用例构造的 Database 实例，FLT-11）；
      断言对象 = ① save_player 抛 StorageError 且人话含「保存失败，请检查磁盘空间」
        （FLT-12/17，禁「断言 OSError 上抛」弱断言）② tmp_path/.pending.jsonl 存在且含该
        玩家行（F-01 player_qid / F-02 action=player_upsert / F-03 row_payload 原行完整 /
        F-04 created_at，FLT-14）③ players 表无该行（事务已回滚 = 无半写 = 绝不静默丢数据，
        数据在 pending 中，FLT-13）；
      恢复路径 = finally monkeypatch.undo() 还原 _commit mock（解除 OSError）→ 关闭 repo
        （5d L205-208）。
    """
    repo: Repository = save_env.repo
    player = make_player("10001")
    # 预置另一玩家确认写路径可用（仅本次 COMMIT 注入失败，对照隔离）
    await repo.save_player(make_player("20002"))

    async def boom_commit(conn) -> None:  # type: ignore[no-untyped-def]
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(save_env.db, "_commit", boom_commit)
    try:
        with pytest.raises(StorageError) as ei:
            await repo.save_player(player)
        # ① 人话文案（FLT-12/17：命令层捕获 StorageError 透传即得）
        assert SAVE_FAILURE_MESSAGE in str(ei.value)
        assert "保存失败，请检查磁盘空间" in str(ei.value)
        # ② pending 文件含该数据行（FLT-14，F-01~04）
        pending_path = save_env.data_dir / ".pending.jsonl"
        assert pending_path.exists()
        entries = await save_env.pending.read_all()
        assert len(entries) == 1
        e = entries[0]
        assert e.player_qid == "10001"                              # F-01 目标玩家
        assert e.action == ACTION_PLAYER_UPSERT                     # F-02 动作类型
        assert e.row_payload.get("player_qid") == "10001"           # F-03 原行 payload 完整
        assert e.row_payload.get("nickname") == player.name
        assert e.row_payload.get("level") == player.level
        assert e.created_at                                         # F-04 入队时刻
        # ③ 无半写（事务已回滚；数据在 pending 未丢，FLT-13）
        assert await repo.load_player("10001") is None
        assert await repo.load_player("20002") is not None          # 预置玩家不受影响（隔离）
    finally:
        monkeypatch.undo()  # 恢复路径：还原 _commit mock
        await repo.close()


# ---------------------------------------------------------------------------
# TC-FLT-08：磁盘恢复后重放一致（FLT-15/17 / 4a TC-09）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flt_08_replay_after_disk_recovery_consistent(save_env, monkeypatch):
    """TC-FLT-08 磁盘恢复后重放一致（D5 FLT-15/17 / 4a TC-09 L392）。

    三要素注释：
      注入点 = 先按 TC-FLT-07 注入 COMMIT OSError 落 pending（模拟磁盘满），随后
        **解除 OSError mock（磁盘恢复）**；
      断言对象 = 触发重放（启动/定时路径入口 repo.replay_pending，FLT-15）返回 1
        （逐条重放回主库，单事务）；load_player("10001") 与确认数据逐字段一致
        （round-trip：qid/金币 350/昵称 阿伟/level 35，FLT-17）；.pending.jsonl 已清空
        （FLT-15「成功清空」）；
      恢复路径 = finally monkeypatch.undo() 还原 mock → 关闭 repo（5d L205-208）。
    """
    repo: Repository = save_env.repo
    player = make_player("10001")

    async def boom_commit(conn) -> None:  # type: ignore[no-untyped-def]
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(save_env.db, "_commit", boom_commit)
    try:
        with pytest.raises(StorageError):
            await repo.save_player(player)
        assert await save_env.pending.count() == 1   # 前置：pending 已落 1 条（TC-FLT-07 状态）
    finally:
        monkeypatch.undo()                           # 解除 OSError mock = 磁盘恢复

    # 磁盘恢复后触发重放（启动 bootstrap / 定时检测路径，FLT-15）
    replayed = await repo.replay_pending()
    assert replayed == 1                             # 逐条重放回主库（单事务）
    loaded = await repo.load_player("10001")
    assert loaded is not None
    assert loaded.qid == "10001"                     # load_player 与确认数据一致（FLT-17）
    assert loaded.name == "阿伟"
    assert loaded.level == 35
    assert loaded.currencies.get("gold") == 350
    assert loaded.inventory and loaded.inventory[0].item_id == "potion"  # round-trip 非裸行
    assert not save_env.pending.path.exists()        # pending 已清空（FLT-15）
    await repo.close()


# ---------------------------------------------------------------------------
# TC-FLT-09：F-1 核销登记（FLT-16 / contract_deviations.md L24）
# ---------------------------------------------------------------------------
def test_flt_09_f1_cancellation_recorded():
    """TC-FLT-09 F-1 核销登记（D5 FLT-16 / contract_deviations.md L24）。

    三要素注释：
      注入点 = 无（只读静态检查 contract_deviations.md）；
      断言对象 = §二 P1 递延表 F-1 行已标注「M6 已实装」（RW-4/TC-09 由本批实装核销，
        4a TC-09 由 fault_inject_save 与单元用例双承载）；
      恢复路径 = 无副作用（只读文件）。
    """
    text = (REPO_ROOT / "contract_deviations.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    f1_line = next((ln for ln in lines if ln.startswith("| F-1 |")), None)
    assert f1_line is not None, "contract_deviations.md 缺失 F-1 条目"
    assert "已实装" in f1_line and "M6" in f1_line, f"F-1 未核销 M6 已实装：{f1_line}"
