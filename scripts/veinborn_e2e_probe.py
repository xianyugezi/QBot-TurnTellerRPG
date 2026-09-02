"""veinborn 实机 e2e：注册→锁定幼兽→连续攻击到战斗结束（验证完整 PvE 循环）。"""
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_veinborn_e2e.db"

from qbot_rpg.commands import battle_commands as BC  # noqa: E402

# 收集 pipeline 发送的正文（真实 bot 收到的内容）
_SENT: list[str] = []
_orig_send = BC.BattlePipeline.send


def _spy_send(self, text, **kw):
    _SENT.append(str(text))
    return _orig_send(self, text, **kw)


BC.BattlePipeline.send = _spy_send


async def main() -> None:
    from qbot_rpg_bridge.assemble import build_app_deps
    from qbot_rpg.assembly import runner as R

    if os.path.exists("/tmp/rpg_veinborn_e2e.db"):
        os.remove("/tmp/rpg_veinborn_e2e.db")
    deps = await build_app_deps()

    async def say(text: str) -> str:
        ev = {"group_id": "g1", "user_id": "u_e2e", "message": text,
              "message_id": str(uuid.uuid4()), "channel": "group"}
        try:
            return await asyncio.wait_for(R.run_command(ev, deps), timeout=25)
        except Exception as e:
            return f"[异常 {type(e).__name__}] {e}"

    await say("/注册")
    _SENT.clear()
    r = await say("/锁定")
    print(f"/锁定: {(r or '')[:100]}")
    _SENT.clear()

    # 连续攻击直到战斗结束（最多 15 轮）
    for i in range(15):
        _SENT.clear()
        await say("/攻击 脊斩")
        joined = " | ".join(_SENT)
        print(f"回合{i + 1}: {joined[:180]}")
        if "死亡" in joined or "战斗结束" in joined or "胜利" in joined or "lose" in joined or "win" in joined:
            print("战斗结束")
            break
        if not _SENT:
            print("  (无发送——可能已结束)")
            break


if __name__ == "__main__":
    asyncio.run(main())
