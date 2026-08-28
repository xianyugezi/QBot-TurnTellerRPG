"""M7 A-05 world 装配单测：GameWorld.get_npcs（挂点→registry→visible 过滤）+ bootstrap 骨架冒烟。

依据：细化_M7_装配层契约 §五（RA-13/RA-14）+ N-02 RN-05。零 NoneBot import；
get_npcs 纯函数确定性（给定注入 maps+registry，输出仅由输入决定）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.assembly.bootstrap import AssembledApp, bootstrap, save_world_state
from qbot_rpg.content.loader import PackLoadError
from qbot_rpg.content.models import NpcDef
from qbot_rpg.content.registry import Registry
from qbot_rpg.data import WorldState
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository
from qbot_rpg.world.game_world import GameWorld

# ---------------------------------------------------------------------------
# 夹具：合成 npc registry / maps（不依赖包 fixture，纯内存）
# ---------------------------------------------------------------------------

NPC_BLACKSMITH: Dict[str, object] = {
    "id": "blacksmith_zhou",
    "name": "铁匠·老周",
    "icon": "锤",
    "map": "rubble_field",
    "type": "merchant",
    "desc": "乱石滩入口的铁匠，兼售杂货。",
    "visible": True,
    "dialogues": {
        "greeting": "欢迎光临铁匠铺。",
        "options": [{"text": "看看货架", "action": "shop", "shop_refs": ["village_shop"]}],
    },
    "interactions": [{"action": "shop", "text": "买东西", "shop_refs": ["village_shop"]}],
    "shop_refs": ["village_shop"],
}

NPC_HIDDEN: Dict[str, object] = {
    "id": "hidden_guard",
    "name": "隐藏守卫",
    "icon": "守",
    "map": "rubble_field",
    "type": "narrator",
    "desc": "条件解锁后显现。",
    "visible": False,
    "dialogues": {"greeting": "（还在暗处）"},
    "interactions": [],
}

NPC_DEALER: Dict[str, object] = {
    "id": "traveling_dealer",
    "name": "行商·骆驼",
    "icon": "驼",
    "map": "volcanic_path",
    "type": "dealer",
    "desc": "游历四方的行商。",
    "dialogues": {"greeting": "今天想听点什么？"},
    "dealer": {"strategy": "condition", "pool": [{"id": "c1", "weight": 1.0}]},
}


def _registry_with(npcs: Dict[str, Dict[str, object]]) -> Registry:
    """合成 npc registry（kind="npc" → Def；与 loader D 阶段同形）。"""
    tables = {"npc": {nid: NpcDef.from_entry(raw) for nid, raw in npcs.items()}}
    names = {nid: str(raw.get("name") or nid) for nid, raw in npcs.items()}
    return Registry(pack_id="test", generation=1, tables=tables, names=names,
                    modules_raw={"npc": list(npcs.values())})


def _make_world(maps: List[Dict[str, object]], registry: Any = None) -> GameWorld:
    """构造 GameWorld（maps 传原始 dict 列表，_index_maps 归一）。"""
    return GameWorld(maps=maps, npc_registry=registry)


# ---------------------------------------------------------------------------
# get_npcs：地图挂点 → registry 解析 → 完整 dict
# ---------------------------------------------------------------------------


def test_get_npcs_resolves_hang_to_full_dict():
    world = _make_world(
        [{"id": "rubble_field", "name": "乱石滩", "npcs": ["blacksmith_zhou"]}],
        _registry_with({"blacksmith_zhou": NPC_BLACKSMITH}),
    )
    out = world.get_npcs("rubble_field")
    assert len(out) == 1
    d = out[0]
    assert d["id"] == "blacksmith_zhou"
    assert d["name"] == "铁匠·老周"
    assert d["type"] == "merchant"
    assert d["visible"] is True
    assert d["dialogues"] == NPC_BLACKSMITH["dialogues"]
    assert d["interactions"] == NPC_BLACKSMITH["interactions"]
    assert d["dealer"] is None


def test_get_npcs_includes_dealer_field():
    world = _make_world(
        [{"id": "volcanic_path", "name": "熔岩径", "npcs": ["traveling_dealer"]}],
        _registry_with({"traveling_dealer": NPC_DEALER}),
    )
    out = world.get_npcs("volcanic_path")
    assert len(out) == 1
    assert out[0]["id"] == "traveling_dealer"
    assert out[0]["dealer"] == NPC_DEALER["dealer"]


def test_get_npcs_filters_visible_false():
    world = _make_world(
        [{"id": "rubble_field", "name": "乱石滩",
          "npcs": ["blacksmith_zhou", "hidden_guard"]}],
        _registry_with({"blacksmith_zhou": NPC_BLACKSMITH, "hidden_guard": NPC_HIDDEN}),
    )
    out = world.get_npcs("rubble_field")
    assert [d["id"] for d in out] == ["blacksmith_zhou"]
    assert all(d["visible"] for d in out)


def test_get_npcs_skips_missing_registry_ref():
    # registry 缺引用 → 跳过（loader 双向校验红拦，此处防御兜底），不抛异常
    world = _make_world(
        [{"id": "rubble_field", "name": "乱石滩",
          "npcs": ["blacksmith_zhou", "ghost"]}],
        _registry_with({"blacksmith_zhou": NPC_BLACKSMITH}),
    )
    assert [d["id"] for d in world.get_npcs("rubble_field")] == ["blacksmith_zhou"]


def test_get_npcs_no_hang_or_unknown_map_or_no_registry_returns_empty():
    reg = _registry_with({"blacksmith_zhou": NPC_BLACKSMITH})
    # 无 npcs 挂点
    w0 = _make_world([{"id": "plain", "name": "空地"}], reg)
    assert w0.get_npcs("plain") == []
    # 空挂点列表
    w1 = _make_world([{"id": "plain", "name": "空地", "npcs": []}], reg)
    assert w1.get_npcs("plain") == []
    # 未知地图
    assert w0.get_npcs("no_such_map") == []
    # 未注入 registry
    w2 = _make_world([{"id": "plain", "name": "空地", "npcs": ["blacksmith_zhou"]}], None)
    assert w2.get_npcs("plain") == []


def test_get_npcs_deterministic():
    maps = [{"id": "rubble_field", "name": "乱石滩",
             "npcs": ["blacksmith_zhou", "hidden_guard"]}]
    reg = _registry_with({"blacksmith_zhou": NPC_BLACKSMITH, "hidden_guard": NPC_HIDDEN})
    world = _make_world(maps, reg)
    assert world.get_npcs("rubble_field") == world.get_npcs("rubble_field")


# ---------------------------------------------------------------------------
# bootstrap 骨架冒烟（legal 包 + 内存库）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_smoke(legal_pack_dir: Path):
    db = Database(":memory:")
    repo = Repository(db)
    try:
        app = await bootstrap({"pack_dir": legal_pack_dir, "repo": repo, "queue": None})
        assert isinstance(app, AssembledApp)
        assert app.game_world is not None
        assert app.registry is not None
        assert app.registry.generation == 1
        assert app.registry_snapshot is not None
        assert app.registry_snapshot.pack_id == app.registry.pack_id
        assert app.session_mgr is not None
        assert app.repo is repo
        assert app.queue is None
        assert app.router is None  # Router 构造归 A-02（context/router_setup 路），装配层占位
        # world_state 持久化接线：装配已 repo.load_world_state() → GameWorld.load
        assert isinstance(app.game_world.to_world_state(), WorldState)
        assert app.game_world._initialized
        # 读/写闭环：写回 world_state 表 → 重读一致
        ok = await save_world_state(app)
        assert ok
        reloaded = await repo.load_world_state()
        assert reloaded == app.game_world.to_world_state()
        # 合法包 maps 无 npcs 挂点 → get_npcs 空（不抛异常）
        assert app.game_world.get_npcs("rubble_field") == []
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_bootstrap_redblock_raises(badref_pack_dir: Path):
    db = Database(":memory:")
    repo = Repository(db)
    try:
        with pytest.raises(PackLoadError):
            await bootstrap({"pack_dir": badref_pack_dir, "repo": repo})
    finally:
        await repo.close()
