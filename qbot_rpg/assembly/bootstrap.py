"""装配启动（细化_M7 A-05：world 装配 RA-13/RA-14；骨架）。

流程（RA-12）：loader 装载（红拦校验）→ registry 快照 → GameWorld 注入装载 →
world_state 持久化接线（load/to_world_state 经 storage/repository 读写 world_state
表）→ SessionManager 初始化 → 返回装配对象（router 占位 None，归 A-02 路）。

零 NoneBot import（架构铁律）；仅依赖 qbot_rpg.content / qbot_rpg.world /
qbot_rpg.storage（repo 鸭子类型）/ qbot_rpg.data。纯装配零引擎改动。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.content.loader import load_pack
from qbot_rpg.content.pack_protection import enforce_play_gate
from qbot_rpg.content.registry import Registry, RegistrySnapshot
from qbot_rpg.world.game_world import GameWorld
from qbot_rpg.world.session import SessionManager

__all__ = ["AssembledApp", "bootstrap", "save_world_state"]


@dataclass(frozen=True)
class AssembledApp:
    """装配产物（细化_M7 RA-12/RA-13）：可运行入口所需全部接线。"""

    game_world: GameWorld
    registry: Registry
    session_mgr: SessionManager
    repo: Any                                   # storage.Repository（鸭子类型，防循环 import）
    queue: Any = None                           # processing.PerPlayerQueue（M6 已建，未接时 None）
    router: Any = None                          # Router 归 A-02 构造，装配层占位
    registry_snapshot: Optional[RegistrySnapshot] = None  # 热重载回退/世代绑定（RA-15）


async def bootstrap(deps: Mapping[str, Any]) -> AssembledApp:
    """装配启动（RA-12/RA-13；骨架冒烟可跑，确定性依赖注入）。

    deps 键：
      pack_dir   Path|str —— 内容包目录（manifest.json 所在；红拦校验上抛 PackLoadError）
      repo       Repository —— storage 门面（world_state/玩家读写）
      queue      可选 —— per-player 队列（未接 → None）
      settings   可选 —— settings.json 装载（M7 其它路消费，本骨架透传不使用）

    流程（RA-12）：**数据包保护门禁**（批32 A1：未开启零额外校验直接放行；开启时复用既有
    包校验，半成品 → 拒绝进入游玩）→ loader 装载（红拦校验）→ registry 快照 → GameWorld
    注入装载（maps=pack.modules；npc_registry=registry 供 get_npcs）→ world_state 持久化
    接线（repo.load_world_state() → GameWorld.load）→ SessionManager 初始化 →
    返回 AssembledApp。零 NoneBot import。
    """
    pack_dir = Path(deps["pack_dir"])
    # 批32 A1：数据包保护门禁（`settings.pack_protection.enabled`，读包内 settings.json）。
    # 未开启（缺省）→ 直接返回 allowed、不跑任何校验（现状逐字段一致）；开启且半成品 →
    # 抛 PackProtectionError（人话含哪个包/什么问题/去哪改）。不经过 `deps["settings"]`，
    # 也不影响编辑器（编辑器走 web 层，不经过本入口）。
    await asyncio.to_thread(enforce_play_gate, pack_dir)
    pack = await load_pack(pack_dir)
    registry = pack.registry
    snap = registry.snapshot()
    world = GameWorld(maps=pack.modules, npc_registry=registry)
    ws = await deps["repo"].load_world_state()
    world.load(ws)
    return AssembledApp(
        game_world=world,
        registry=registry,
        session_mgr=SessionManager(deps["repo"]),
        repo=deps["repo"],
        queue=deps.get("queue"),
        router=None,
        registry_snapshot=snap,
    )


async def save_world_state(app: AssembledApp) -> bool:
    """世界状态写回接线（world_state 表 CAS；RA-13 读/写闭环的写半边）。

    GameWorld.to_world_state() → repo.save_world_state(ws, expected_versions)。
    期望版本取当前表内各行 version（缺失行按 0 插入）；CAS 冲突 → False
    （调用方重读版本后重试，4a TX-3）。纯接线零业务逻辑。
    """
    expected: Dict[str, int] = {}
    rows = await app.repo.db.fetchall_read("SELECT key, version FROM world_state")
    for r in rows or ():
        expected[str(r["key"])] = int(r["version"])
    ws = app.game_world.to_world_state()
    return bool(await app.repo.save_world_state(ws, expected))
