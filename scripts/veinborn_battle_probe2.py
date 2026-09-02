"""veinborn 实机战斗流程 v2：/锁定 触发 → 四色出牌 → 部位破坏。"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_veinborn_battle2.db"

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402

FLOW = [
    "/注册",
    "/锁定 gravelcrown_hunt怪物",
    "/状态",
    "/攻击 脊斩",
    "/攻击 桩移",
    "/攻击 脊挡",
    "/攻击 堑跃",
    "/攻击 贯核击",
]


async def main() -> None:
    if os.path.exists("/tmp/rpg_veinborn_battle2.db"):
        os.remove("/tmp/rpg_veinborn_battle2.db")
    deps = await build_app_deps()
    out: list[str] = []

    async def say(text: str, uid: str = "u_vb3") -> str:
        ev = {
            "group_id": "g1", "user_id": uid, "message": text,
            "message_id": str(uuid.uuid4()), "channel": "group", "group_name": "测试群",
        }
        try:
            return await asyncio.wait_for(R.run_command(ev, deps), timeout=30)
        except Exception as e:  # noqa: BLE001
            return f"[异常 {type(e).__name__}] {e}"

    for msg in FLOW:
        r = await say(msg)
        out.append(f">>> {msg}\n{(r or '(无回复/静默)')[:700]}\n---")
        print(f">>> {msg}\n{(r or '(无回复/静默)')[:700]}\n")

    text = "\n\n".join(out)
    with open("/tmp/veinborn_battle2_flow.txt", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    asyncio.run(main())
