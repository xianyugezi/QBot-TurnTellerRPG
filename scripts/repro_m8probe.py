"""M8 批14 部署实测：炼金引导任务链 + prof 奖励落档 + 炼金全链路。

验证：① 注册 → ② 任务板见炼金引导链 → ③ q_start 交付 → ④ q_alchemy_start 接取/交付
（奖励炼金熟练度 prof exp=150 → 解锁 /炼金）→ ⑤ 炼金全链路（合成→炼金→投料→继承→确认→分解）
→ ⑥ DB 落档验证（proficiency.alchemy 节点 + farm_plots + currencies）。
"""
import asyncio
import os
import sqlite3
import sys
import uuid

sys.path.insert(0, "/root/QBot-TurnTellerRPG")
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/test_demo"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_m8probe.db"

from qbot_rpg_bridge.assemble import build_app_deps
from qbot_rpg.assembly.runner import run_command


async def main() -> None:
    deps = await asyncio.wait_for(build_app_deps(), timeout=60)
    print("指令数:", len(deps.router.names()))

    async def say(text: str, uid: str = "u_m8p") -> None:
        ev = {"group_id": "g1", "user_id": uid, "message": text,
              "message_id": str(uuid.uuid4()), "channel": "group", "group_name": "测试群"}
        r = await asyncio.wait_for(run_command(ev, deps), timeout=30)
        msg = (r or "(静默)").replace("\n", " | ")
        print(f">>> {text}\n   {msg[:170]}")

    def db_row() -> tuple:
        conn = sqlite3.connect("/tmp/rpg_m8probe.db")
        row = conn.execute(
            "SELECT persistent_state FROM players WHERE player_qid='u_m8p'"
        ).fetchone()
        conn.close()
        return row or (None,)

    def db_inject(ps_patch: dict, currencies: dict) -> None:
        """测试钩子：直接改 DB（绕过主线前置，聚焦 M8 新机制验证）。

        currencies 存独立列（repository L157/267），persistent_state 存 ps。
        """
        import json as _j
        conn = sqlite3.connect("/tmp/rpg_m8probe.db")
        row = conn.execute(
            "SELECT persistent_state FROM players WHERE player_qid='u_m8p'"
        ).fetchone()
        if not row:
            conn.close()
            return
        ps = _j.loads(row[0])
        ps.update(ps_patch)
        conn.execute("UPDATE players SET persistent_state=?, currencies=? WHERE player_qid='u_m8p'",
                     (_j.dumps(ps, ensure_ascii=False), _j.dumps(currencies)))
        conn.commit()
        conn.close()

    # 1. 注册
    await say("/注册 炼金学徒")
    # 测试钩子：注入 500 金币（绕过新手经济，聚焦 M8 引导链验证）
    db_inject({}, {"coins": 500})
    # 2. 任务板（应含主线 + 炼金引导链入口——q_start 未完成时引导链未解锁属正确）
    await say("/任务")
    await say("/任务 接取 1")
    # 送材料直接交付 q_start（避免打怪/商店依赖——本脚本聚焦炼金链）
    # 用 /商店 买药水（village_shop 有 potion；商品名=英文 id，脚本用 id 避免解析歧义）
    await say("/商店 晨风杂货铺")
    await say("/购买 potion 1")
    await say("/任务 交付 1")
    # 3. 炼金引导链（NPC 支线：8 炼金初窥 → 9 第一炉 → 10 春耕 → 11 返璞）
    await say("/任务 2")
    await say("/任务 接取 8")   # q_alchemy_start 炼金初窥（NPC 支线第 8 号）
    await say("/商店 晨风杂货铺")
    await say("/购买 moon_grass 1")
    await say("/任务 交付 8")
    # 4. DB 验证 prof 奖励落档
    row = db_row()
    ps = row[0] if row and row[0] else "{}"
    print("\n[DB] prof 落档:", "alchemy" in ps)
    # 5. 炼金全链路（见习档；配方名=test_demo 实际名 火焰弹配方）
    await say("/商店 晨风杂货铺")
    await say("/购买 moon_grass 1")
    await say("/购买 star_iron 1")
    await say("/合成 火晶石炼制")
    await say("/炼金 火焰弹配方")
    await say("/投料 火晶石,月光草")
    await say("/继承 灼烧强化")
    await say("/确认")
    # 6. 引导任务 9/10/11 交付（需先炼成火焰弹 / 持有火晶石×2 / 持有星铁）
    await say("/任务 接取 9")   # 第一炉火焰弹（q_alchemy_brew）
    await say("/任务 交付 9")
    await say("/商店 晨风杂货铺")
    await say("/购买 alch_ember_crystal 2")   # q10 需火晶石×2（投料已耗 1，补购）
    await say("/任务 接取 10")  # 春耕火晶
    await say("/任务 交付 10")
    await say("/商店 晨风杂货铺")
    await say("/购买 star_iron 1")           # q11 需星铁（分解返料也可能补）
    await say("/任务 接取 11")  # 返璞归真
    await say("/任务 交付 11")
    await say("/分解 火焰弹")
    row = db_row()
    ps = row[0] if row and row[0] else "{}"
    print("\n[DB] 尾 400:", ps[-400:])


if __name__ == "__main__":
    asyncio.run(main())
