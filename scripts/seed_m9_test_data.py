"""M9 锻造部署前测试数据种子（2026-08-30 用户指示：先填数据防空数据 bug）。

给测试玩家 2750511376（鱼鱼）填充 M9 锻造实机测试所需数据：
  1. 金币（锻造扣费：节点等级×10，满 7 级链全锻需 300+）
  2. 锻造树全部 9 种素材 × 30（ore/star_iron/... 见 forge.json trees.materials）
  3. 铸造职业 level=7（可锻全部节点 + 铸造王门槛）+ sp 解锁标记
  4. 保留既有属性/装备不动（只追加，不覆盖持久化其它键）

通过框架真实装配（build_app_deps）→ repo.load_player → dataclasses.replace 更新 →
repo.upsert_player 落档。零裸 SQL 改存档。

用法：./.venv/bin/python scripts/seed_m9_test_data.py [qid]
"""
import asyncio
import os
import sys

sys.path.insert(0, "/root/QBot-TurnTellerRPG")
os.environ.setdefault("QBotRPG_PACK_DIR", "/root/QBot-TurnTellerRPG/content/test_demo")
os.environ.setdefault("QBotRPG_DB_PATH", "/opt/nonebot-bot/data/qbot_rpg.db")

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.data.player import Player  # noqa: E402
from qbot_rpg.data.item import ItemInstance  # noqa: E402

FORGE_MATERIALS = [
    "ore", "star_iron", "fire_dragon_scale", "ash_core", "ice_crystal_ore",
    "thunder_beast_fang", "alch_ember_crystal", "alch_frost_crystal", "alch_fire_essence",
]
# 铸造 SP 面板真实 id（forge_sp.FORGE_SP_PANEL：非 sp_f1~f5）
FORGE_SP_IDS = [
    "unlock_branch_tree", "unlock_combine_3to1", "unlock_slot_tool",
    "unlock_sets", "unlock_augment",
]
# 测试玩家已有物品名（id→name 映射；从 items.json 读避免硬编码漂移）
def _item_names() -> dict:
    import json
    items = json.load(open("/root/QBot-TurnTellerRPG/content/test_demo/items.json"))
    return {i.get("id"): (i.get("name") or i.get("id")) for i in items}


async def main(qid: str) -> None:
    names = _item_names()
    deps = await asyncio.wait_for(build_app_deps(), timeout=60)
    repo = deps.repo
    p = await repo.load_player(qid)
    if p is None:
        print(f"❌ 玩家 {qid} 不存在，先 /注册")
        return

    # 1) 金币：保留已有，锻造测试给足 5 万（7 级链全程扣费 300+，余量充足）
    #    ⚠️ 权威货币键 = coins（BATCH-05：炼金/锻造统一读 currencies["coins"]），
    #    框架 /注册 初始不落 currencies，forge 扣费读 coins → 缺 coins 实机显示 0
    coins_have = p.currencies.get("coins", 0)
    new_currencies = dict(p.currencies)
    new_currencies["coins"] = coins_have + 50000
    # 权威货币键 = coins（BATCH-05）；剔除旧 gold 键——装配层只认 coins，gold 残留
    # 会在背包/货币显示多出一行「gold：0」（实机 /背包 部署反馈，2026-08-30）
    new_currencies.pop("gold", None)

    # 2) 素材：9 种 × 30（保留已有物品，追加不覆盖；同名素材合并计数）
    have = {inst.item_id: inst for inst in p.inventory}
    new_insts = []
    for mid in FORGE_MATERIALS:
        cnt = 30 + (have[mid].count if mid in have else 0)
        new_insts.append(ItemInstance(
            item_id=mid, name=names.get(mid, mid), count=cnt,
            quality="普通", bound=True, stack_max=99,
        ))

    # 3) 铸造职业 level=7 + sp 解锁全开（sp_earned 足够；unlocks 键=SP 面板真实 id）
    ps = dict(p.persistent_state)
    prof = dict(ps.get("proficiency") or {})
    forge_node = dict(prof.get("forge") or {})
    forge_node.update({"level": 7, "exp": 0, "sp_earned": 500, "sp_used": 0,
                       "unlocks": {sid: 1 for sid in FORGE_SP_IDS}})
    prof["forge"] = forge_node
    # 炼金职业（M9 实机反馈修复 2026-08-30：/合成 是炼金指令，读 proficiency.alchemy——
    # 只设 forge 会报「等级不足：forge 7 不足需 3」（种子缺口，非代码 bug））
    alch_node = dict(prof.get("alchemy") or {})
    alch_node.update({"level": 7, "exp": 0, "sp_earned": 300, "sp_used": 0, "unlocks": {}})
    prof["alchemy"] = alch_node
    ps["proficiency"] = prof

    p2 = Player(
        qid=p.qid, name=p.name, job_id=p.job_id, level=p.level, exp=p.exp,
        hp=p.hp, mp=p.mp, currencies=new_currencies,
        inventory=tuple(new_insts),
        equipment=p.equipment, attributes=p.attributes,
        achievement_state=p.achievement_state, title_state=p.title_state,
        persistent_state=ps, longline_counters=p.longline_counters,
        reputation_state=p.reputation_state, codex_state=p.codex_state,
        content_pack_id=p.content_pack_id, content_pack_version=p.content_pack_version,
        schema_version=p.schema_version, last_seen_group=p.last_seen_group,
        created_at=p.created_at,
    )
    # upsert_player 在 RepoTransaction 上：写操作走 tx() 上下文
    async with repo.tx() as tx:
        await tx.upsert_player(p2)
    # 读回校验
    back = await repo.load_player(qid)
    assert back is not None
    assert back.currencies.get("coins", 0) >= 50000
    assert len(back.inventory) >= len(FORGE_MATERIALS)
    lv = back.persistent_state.get("proficiency", {}).get("forge", {}).get("level")
    assert lv == 7
    print(f"✅ 种子完成 {qid}: coins={back.currencies.get('coins')} "
          f"素材={len(back.inventory)}种 lv={lv}")
    print("素材明细:", {inst.item_id: inst.count for inst in back.inventory})


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "2750511376"
    asyncio.run(main(q))
    # Database 读连接池线程为非 daemon（部署时进程常驻 OK）；CLI 种子强制退出，
    # 否则 aiosqlite worker 线程阻止进程结束（assemble.py L208 同款）
    os._exit(0)
