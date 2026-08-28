"""全框架可玩流程测试（部署用 · M0~M7 可玩内容冒烟）。

按真实玩家流程逐指令发消息，收集所有回复到文件，供断点分析。
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根

os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/demo_full"
os.environ["QBotRPG_DB_PATH"] = "/root/QBot-TurnTellerRPG/data/rpg_full_test.db"

from qbot_rpg_bridge.assemble import build_app_deps
from qbot_rpg.assembly import runner as R

FLOW = [
    "/注册",
    "/状态",
    "/背包",
    "/装备",
    "/签到",
    "/任务",
    "/进入 上",
    "/进入 下",
    "/锁定",
    "/攻击",
    "/防御",
    "/调查",
    "/图鉴",
    "/日志",
    "/对话",
    "/商店",
    "/快捷绑定 攻击 2",
    "/快捷列表",
]


async def main() -> None:
    deps = await build_app_deps()
    out: list[str] = []
    async def say(text: str, uid: str = "u_全流程") -> str:
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
        out.append(f">>> {msg}\n{(r or '(无回复/静默)')[:300]}\n---")
    with open("/tmp/fullflow.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(out))


if __name__ == "__main__":
    asyncio.run(main())
