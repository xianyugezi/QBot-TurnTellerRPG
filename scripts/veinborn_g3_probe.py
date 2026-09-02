"""G3 实机开战 e2e：注册 → /锁定 开战 → /攻击 四色 → 战斗推进。"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_veinborn_g3.db"

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402

FLOW = [
    "/注册",
    "/状态",
    "/锁定",
    "/攻击 脊斩",
    "/状态",
]


async def main() -> None:
    if os.path.exists("/tmp/rpg_veinborn_g3.db"):
        os.remove("/tmp/rpg_veinborn_g3.db")
    deps = await build_app_deps()
    out: list[str] = []

    async def say(text: str, uid: str = "u_vbg3") -> str:
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
        out.append(f">>> {msg}\n{(r or '(无回复/静默)')[:600]}\n---")
        print(f">>> {msg}\n{(r or '(无回复/静默)')[:600]}\n")

    text = "\n\n".join(out)
    with open("/tmp/veinborn_g3_flow.txt", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    asyncio.run(main())
