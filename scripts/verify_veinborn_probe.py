"""veinborn 预设包部署实测：真实装配（build_app_deps）+ run_command 全链路。

验证 veinborn 在真实装配管线（非模拟 BattleEngine 直拼）下的表现：
  注册 → 选职业（脊剑士）→ 触发遭遇砾冕 → 四色出牌 → 部位破坏 → 困斗/宣泄 → 专精翻面

用法：QBotRPG_PACK_DIR=/root/QBot-TurnTellerRPG/content/veinborn .venv/bin/python scripts/verify_veinborn_probe.py
"""
import asyncio
import json
import os
import sqlite3
import sys

sys.path.insert(0, "/root/QBot-TurnTellerRPG")
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"

QID = "u_vbprobe"
DB = "/tmp/rpg_veinborn_probe.db"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name} {detail}")


def db_row():
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT persistent_state FROM players WHERE player_qid=?", (QID,)
    ).fetchone()
    conn.close()
    return row or (None,)


async def main() -> None:
    if os.path.exists(DB):
        os.remove(DB)
    sys.argv = ["probe", f"--db={DB}", f"--qq={QID}"]
    from qbot_rpg_bridge.assemble import build_app_deps  # noqa: PLC0415
    from qbot_rpg.assembly.runner import run_command  # noqa: PLC0415

    deps = await build_app_deps()
    out: list = []

    async def say(text: str) -> str:
        ev = {
            "message": text,
            "message_id": f"vb_{len(out)}",
            "group_id": "g_vbprobe",
            "user_id": QID,
            "qq_id": QID,
            "channel": "group",
        }
        r = await run_command(ev, deps)
        resp = str(r)
        out.append((text, resp))
        return resp

    # ---- 1. 注册 ----
    print("== 1. 注册 ==")
    resp = await say("/注册")
    check("注册成功", "成功" in resp or "欢迎" in resp or "注册" in resp, resp[:80])

    # ---- 2. 看职业（veinborn 应有脊剑士/脉矢手）----
    print("\n== 2. 职业列表 ==")
    resp = await say("/转职")
    check("职业列表含脊剑士", "脊剑士" in resp, resp[:120])
    check("职业列表含脉矢手", "脉矢手" in resp, resp[:120])

    # ---- 3. 选脊剑士 ----
    print("\n== 3. 转职脊剑士 ==")
    resp = await say("/转职 脊剑士")
    check("转职成功", "脊剑士" in resp and ("成功" in resp or "转职" in resp or "成为" in resp), resp[:150])

    # ---- 4. 触发遭遇（地图/副本/打猎指令试探）----
    print("\n== 4. 触发战斗 ==")
    # 试探可用指令（先打野/出发/狩猎）
    for cmd in ("/地图", "/状态"):
        resp = await say(cmd)
        print(f"  {cmd}: {resp[:100]}")
        if "脊剑士" in resp or "精力" in resp:
            break

    # 战斗触发：查当前在哪（demo 地图还是 veinborn 缺地图——veinborn 精简包暂无 maps）
    # 尝试常用遭遇指令
    resp = await say("/出发")
    print(f"  /出发: {resp[:150]}")

    for text, resp in out[-10:]:
        print(f"\n>>> {text}\n  {resp[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
