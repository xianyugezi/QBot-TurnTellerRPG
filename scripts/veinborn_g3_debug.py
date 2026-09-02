"""验证 G3：/锁定 后 session 落档 + 下指令能恢复 battle_engine。"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_veinborn_g3b.db"


async def main() -> None:
    if os.path.exists("/tmp/rpg_veinborn_g3b.db"):
        os.remove("/tmp/rpg_veinborn_g3b.db")
    from qbot_rpg_bridge.assemble import build_app_deps  # noqa: PLC0415
    from qbot_rpg.assembly import runner as R  # noqa: PLC0415

    deps = await build_app_deps()

    async def say(text: str, uid: str = "u_vbg3b") -> str:
        ev = {"group_id": "g1", "user_id": uid, "message": text,
              "message_id": str(uuid.uuid4()), "channel": "group"}
        try:
            return await asyncio.wait_for(R.run_command(ev, deps), timeout=30)
        except Exception as e:  # noqa: BLE001
            return f"[异常 {type(e).__name__}] {e}"

    print(">>> /注册")
    r = await say("/注册")
    print(f"  {r[:200]}")
    print(">>> /锁定")
    r = await say("/锁定")
    print(f"  {r[:250]}")

    # 直接查 session
    sm = deps.session_mgr
    act = await sm.get_active("u_vbg3b")
    print(f"\nsession: {act.session_type if act else None}")
    if act:
        pl = act.payload
        print(f"payload type: {type(pl).__name__}")
        if isinstance(pl, dict):
            print(f"payload keys: {list(pl.keys())[:15]}")
            print(f"has player: {'player' in pl}, has enemy: {'enemy' in pl}")
    # 下一指令 /状态 看 in_battle / battle_engine
    print("\n>>> /状态")
    r = await say("/状态")
    print(f"  {r[:150]}")

    # 手动调 make_context 看 battle_engine
    from qbot_rpg.assembly.context import make_context  # noqa: PLC0415

    ctx = await make_context({"group_id": "g1", "user_id": "u_vbg3b", "qq_id": "u_vbg3b",
                              "message": "/攻击", "channel": "group"}, deps)
    print(f"\nmake_context: in_battle={ctx.get('in_battle')} battle_engine={type(ctx.get('battle_engine')).__name__ if ctx.get('battle_engine') else None}")


if __name__ == "__main__":
    asyncio.run(main())
