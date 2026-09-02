"""Debug: 看实机 /攻击 的 pipeline.send 实际发了什么。"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_veinborn_g3d.db"

from qbot_rpg.commands import battle_commands as BC  # noqa: E402

_orig_send = BC.BattlePipeline.send


def _spy_send(self, text, **kw):
    print(f"[SPY-send] len={len(text or '')} text={repr((text or '')[:200])}", flush=True)
    return _orig_send(self, text, **kw)


BC.BattlePipeline.send = _spy_send


async def main():
    from qbot_rpg_bridge.assemble import build_app_deps
    from qbot_rpg.assembly import runner as R

    if os.path.exists("/tmp/rpg_veinborn_g3d.db"):
        os.remove("/tmp/rpg_veinborn_g3d.db")
    deps = await build_app_deps()

    async def say(text: str) -> str:
        ev = {"group_id": "g1", "user_id": "u_vbg3d", "message": text,
              "message_id": str(uuid.uuid4()), "channel": "group"}
        try:
            return await asyncio.wait_for(R.run_command(ev, deps), timeout=25)
        except Exception as e:
            return f"[异常 {type(e).__name__}] {e}"

    print("== /注册 ==")
    await say("/注册")
    print("== /锁定 ==")
    r = await say("/锁定")
    print(f"回复: {(r or '')[:150]}")
    print("== /攻击 脊斩 ==")
    r = await say("/攻击 脊斩")
    print(f"回复: {(r or '')[:300]}")


asyncio.run(main())
