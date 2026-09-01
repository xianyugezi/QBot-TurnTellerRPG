"""M10 钓鱼实机冒烟（部署用 · test_demo 包全链路）。

按真实玩家流程测钓鱼：注册 → /钓鱼 列钓点 → 抛竿（等待）→ /鱼讯（推进）→
/收杆（三选一）→ 出鱼结算 → /图鉴 鱼册 → 每日对账。收集所有回复到文件。
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根

os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/test_demo"
os.environ["QBotRPG_DB_PATH"] = "/root/QBot-TurnTellerRPG/data/rpg_fishing_smoke.db"

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402

FLOW = [
    "/注册",
    "/状态",
    "/钓鱼",
    "/钓鱼 月光草甸",       # 有参下钩（spot 名）
    "/鱼讯",                 # 等待中（未到期）或推进
    "/收杆 自动",            # 收杆（自动）→ 出鱼结算
    "/收杆 止损",            # 无会话 → 空态
    "/图鉴",                 # 总览（含鱼册）
    "/图鉴 鱼",              # 鱼册分册
]


async def main() -> None:
    deps = await build_app_deps()
    out: list[str] = []
    async def say(text: str, uid: str = "u_钓鱼冒烟") -> str:
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
    with open("/tmp/fishingflow.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(out))
    # 简单断言：钓鱼链路至少出鱼成功一次
    joined = "\n".join(out)
    checks = {
        "钓鱼列钓点": "/钓鱼" in joined and ("垂钓点" in joined or "钓点" in joined),
        "抛竿受理": "已抛竿" in joined or "下钩" in joined or "钓点" in joined,
        "鱼讯推进": "鱼讯" in joined or "等待" in joined,
        "收杆结算": "出鱼成功" in joined,
        "图鉴鱼册": "鱼图鉴" in joined or "银鳞鲤" in joined,
    }
    print("=== M10 钓鱼实机冒烟结果 ===")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    ok = all(checks.values())
    print(f"总判定: {'通过' if ok else '失败（看 /tmp/fishingflow.txt 断点）'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
